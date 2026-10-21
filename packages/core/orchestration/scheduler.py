"""Persisted, opt-in scheduler. A tick never starts a daemon or publishes."""
from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .jobstore import JobStore
from .planner import ProductionPlanner


@dataclass(frozen=True)
class DispatchResult:
    success: bool
    retryable: bool = True
    error_code: str | None = None


@dataclass
class TickReport:
    enabled: bool
    dispatched: int = 0
    completed: int = 0
    failed: int = 0
    retried: int = 0
    recovered: int = 0


class Scheduler:
    def __init__(self, store: JobStore, runner: Callable | None = None) -> None:
        self.store = store
        self.runner = runner
        self.planner = ProductionPlanner(store)
        with store._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS scheduler_control (
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS scheduler_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    slot_id TEXT REFERENCES production_slots(id),
                    kind TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT OR IGNORE INTO scheduler_control VALUES (1,0,?)",
                         (store.utc_now().isoformat(),))
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(production_slots)")}
            for name, kind in (("dispatch_token", "TEXT"), ("dispatch_expires_at", "REAL"),
                               ("next_attempt_at", "REAL"), ("last_error_code", "TEXT")):
                if name not in columns:
                    conn.execute(f"ALTER TABLE production_slots ADD COLUMN {name} {kind}")

    def enable(self, *, operator_confirmed: bool = False) -> None:
        if operator_confirmed is not True:
            raise PermissionError("explicit operator confirmation is required")
        self._set_enabled(True)

    def pause(self) -> None:
        self._set_enabled(False)

    def _set_enabled(self, enabled: bool) -> None:
        stamp = self.store.utc_now().isoformat()
        with self.store._connect() as conn:
            conn.execute("UPDATE scheduler_control SET enabled=?, updated_at=? WHERE id=1", (int(enabled), stamp))
            conn.execute("INSERT INTO scheduler_events (kind,created_at) VALUES (?,?)",
                         ("operator_enabled" if enabled else "operator_paused", stamp))

    def status(self) -> dict:
        return self.read_status(self.store.db_path)

    @staticmethod
    def read_status(db_path: Path) -> dict:
        status = {"enabled": False, "slots": {}, "plans": 0, "next_due_at": None}
        if not db_path.is_file():
            return status
        conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "scheduler_control" in tables:
                control = conn.execute("SELECT enabled FROM scheduler_control WHERE id=1").fetchone()
                status["enabled"] = bool(control and control[0])
            if "production_plans" in tables:
                status["plans"] = conn.execute("SELECT COUNT(*) FROM production_plans").fetchone()[0]
            if "production_slots" in tables:
                status["slots"] = dict(conn.execute("SELECT status,COUNT(*) FROM production_slots GROUP BY status"))
                status["next_due_at"] = conn.execute(
                    "SELECT MIN(due_at) FROM production_slots WHERE status IN ('PENDING','RETRY')"
                ).fetchone()[0]
        finally:
            conn.close()
        return status

    def events(self) -> list[dict]:
        with self.store._connect() as conn:
            return [dict(row) for row in conn.execute("SELECT slot_id,kind,created_at FROM scheduler_events ORDER BY id")]

    def tick(self, *, limit: int = 1) -> TickReport:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("tick limit must be an integer from 1 to 1000")
        report = TickReport(enabled=self.status()["enabled"])
        if not report.enabled:
            return report
        self._recover_expired(report)
        if self.runner is None:
            raise ValueError("an explicit runner callback is required")
        for _ in range(limit):
            claim = self._claim()
            if claim is None:
                break
            result = _terminal_result(claim["job_state"])
            if result is None:
                report.dispatched += 1
                try:
                    result = self.runner(claim["job_id"], provider_mode=claim["provider_mode"])
                    if not isinstance(result, DispatchResult):
                        result = DispatchResult(False, retryable=False, error_code="runner_contract")
                except Exception:
                    result = DispatchResult(False, error_code="runner_exception")
            status = self._finish(claim, result)
            if status == "COMPLETE":
                report.completed += 1
            elif status == "FAILED":
                report.failed += 1
            elif status == "RETRY":
                report.retried += 1
        return report

    def _claim(self) -> dict | None:
        with self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            now = self.store.utc_now()
            if not conn.execute("SELECT enabled FROM scheduler_control WHERE id=1").fetchone()["enabled"]:
                return None
            slot = conn.execute(
                "SELECT s.*,j.state AS job_state FROM production_slots s JOIN jobs j ON j.id=s.job_id "
                "WHERE (s.status='PENDING' OR (s.status='RETRY' AND s.next_attempt_at<=?)) AND s.due_at<=? "
                "AND s.attempts<s.max_attempts "
                "AND (j.lease_owner IS NULL OR j.lease_expires_at<=?) ORDER BY s.due_at,s.id LIMIT 1",
                (now.timestamp(), now.isoformat(), now.timestamp()),
            ).fetchone()
            if slot is None:
                return None
            claim = dict(slot)
            increment = 0 if _terminal_result(claim["job_state"]) is not None else 1
            claim["attempts"] += increment
            claim["dispatch_token"] = uuid.uuid4().hex
            conn.execute("UPDATE production_slots SET status='DISPATCHED', attempts=attempts+?, "
                         "dispatch_token=?,dispatch_expires_at=? WHERE id=?",
                         (increment, claim["dispatch_token"], now.timestamp() + 120, slot["id"]))
            conn.execute("INSERT INTO scheduler_events (slot_id,kind,created_at) VALUES (?,?,?)",
                         (slot["id"], "dispatch_started" if increment else "dispatch_skipped", now.isoformat()))
        return claim

    def _finish(self, claim: dict, result: DispatchResult) -> str | None:
        with self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            return self._settle(conn, claim, result)

    def _settle(self, conn: sqlite3.Connection, claim: dict, result: DispatchResult) -> str | None:
        now = self.store.utc_now()
        job_state = conn.execute("SELECT state FROM jobs WHERE id=?", (claim["job_id"],)).fetchone()["state"]
        result = _terminal_result(job_state) or result
        retry = not result.success and result.retryable and claim["attempts"] < claim["max_attempts"]
        status = "COMPLETE" if result.success else "RETRY" if retry else "FAILED"
        next_attempt = now.timestamp() + min(86400, claim["retry_base_s"] * 2 ** (claim["attempts"] - 1))
        code = None if result.success else "runner_failed"
        if result.error_code in {"runner_exception", "runner_contract"}:
            code = result.error_code
        cur = conn.execute("UPDATE production_slots SET status=?,dispatch_token=NULL,dispatch_expires_at=NULL, "
                           "next_attempt_at=?,last_error_code=? "
                           "WHERE id=? AND status='DISPATCHED' AND dispatch_token=?",
                           (status, next_attempt if retry else None, code, claim["id"], claim["dispatch_token"]))
        if cur.rowcount != 1:
            return None
        conn.execute("INSERT INTO scheduler_events (slot_id,kind,created_at) VALUES (?,?,?)",
                     (claim["id"], f"dispatch_{status.lower()}", now.isoformat()))
        return status

    def _recover_expired(self, report: TickReport) -> None:
        with self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            now = self.store.utc_now()
            if not conn.execute("SELECT enabled FROM scheduler_control WHERE id=1").fetchone()["enabled"]:
                return
            rows = conn.execute(
                "SELECT s.* FROM production_slots s JOIN jobs j ON j.id=s.job_id "
                "WHERE s.status='DISPATCHED' AND s.dispatch_expires_at<=? "
                "AND (j.lease_owner IS NULL OR j.lease_expires_at<=?) ORDER BY s.due_at LIMIT 1000",
                (now.timestamp(), now.timestamp()),
            ).fetchall()
            for row in rows:
                status = self._settle(conn, dict(row), DispatchResult(False))
                if status is None:
                    continue
                conn.execute("INSERT INTO scheduler_events (slot_id,kind,created_at) "
                             "VALUES (?,'dispatch_recovered',?)", (row["id"], now.isoformat()))
                report.recovered += 1
                if status == "RETRY":
                    report.retried += 1
                elif status == "COMPLETE":
                    report.completed += 1
                else:
                    report.failed += 1


def _terminal_result(state: str) -> DispatchResult | None:
    if state in {"READY_FOR_APPROVAL", "APPROVED", "PRIVATE_UPLOAD", "SCHEDULED", "PUBLISHED"}:
        return DispatchResult(True)
    if state in {"CANCELLED", "REJECTED", "BLOCKED"}:
        return DispatchResult(False, retryable=False)
    return None
