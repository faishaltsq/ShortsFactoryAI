"""Job persistence: SQLite repository with event log, resume support, no duplicate runs."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..artifacts import validate_artifact
from .states import ARTIFACT_FOR_STATE, PIPELINE_ORDER, JobState, assert_transition


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class JobRecord:
    id: str
    title: str
    state: JobState
    attempts: int
    created_at: str
    updated_at: str
    payload: dict[str, Any]
    last_error: str | None = None


class JobStore:
    def __init__(self, db_path: Path, artifacts_root: Path) -> None:
        self.db_path = db_path
        self.artifacts_root = artifacts_root
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    payload TEXT NOT NULL DEFAULT '{}',
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    locked_at TEXT
                );
                CREATE TABLE IF NOT EXISTS job_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    from_state TEXT,
                    to_state TEXT NOT NULL,
                    detail TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state);
                CREATE INDEX IF NOT EXISTS idx_events_job ON job_events(job_id);
                """
            )

    # --- job lifecycle -------------------------------------------------

    def create(self, *, title: str, state: JobState = JobState.IDEA_DISCOVERY, payload: dict[str, Any] | None = None) -> JobRecord:
        job_id = uuid.uuid4().hex[:16]
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO jobs (id, title, state, payload, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                (job_id, title, state.value, json.dumps(payload or {}, ensure_ascii=False), now, now),
            )
            conn.execute(
                "INSERT INTO job_events (job_id, from_state, to_state, detail, created_at) VALUES (?,?,?,?,?)",
                (job_id, None, state.value, "created", now),
            )
        self.snapshot(job_id)
        return self.get(job_id)

    def snapshot(self, job_id: str) -> Path:
        return self.write_artifact(job_id, "job.json", asdict(self.get(job_id)))

    def get(self, job_id: str) -> JobRecord:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(f"job {job_id} not found")
        return _to_record(row)

    def list(self, *, state: JobState | None = None, limit: int = 100) -> list[JobRecord]:
        query = "SELECT * FROM jobs"
        params: list[Any] = []
        if state is not None:
            query += " WHERE state = ?"
            params.append(state.value)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_to_record(r) for r in rows]

    def transition(self, job_id: str, to_state: JobState, *, detail: str | None = None,
                   error: str | None = None, payload_patch: dict[str, Any] | None = None) -> JobRecord:
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(f"job {job_id} not found")
            record = _to_record(row)
            if record.state is to_state and not payload_patch:
                return record
            if record.state is not to_state:
                assert_transition(record.state, to_state)
            payload = dict(record.payload)
            payload.update(payload_patch or {})
            now = _now()
            attempts = record.attempts + (1 if to_state is JobState.FAILED else 0)
            conn.execute(
                "UPDATE jobs SET state=?, payload=?, updated_at=?, last_error=?, attempts=? WHERE id=?",
                (to_state.value, json.dumps(payload, ensure_ascii=False), now, error, attempts, job_id),
            )
            conn.execute(
                "INSERT INTO job_events (job_id, from_state, to_state, detail, created_at) VALUES (?,?,?,?,?)",
                (job_id, record.state.value, to_state.value, detail or "", now),
            )
        self.snapshot(job_id)
        return self.get(job_id)

    def events(self, job_id: str, limit: int = 200) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT from_state, to_state, detail, created_at FROM job_events WHERE job_id=? ORDER BY id ASC LIMIT ?",
                (job_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    # --- concurrency guards --------------------------------------------

    def try_lock(self, job_id: str) -> bool:
        """Acquire the render/stage lock. Returns False if already held elsewhere."""
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE jobs SET locked_at=? WHERE id=? AND (locked_at IS NULL OR locked_at < ?)",
                (_now(), job_id, _stale_before()),
            )
            return cur.rowcount == 1

    def unlock(self, job_id: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE jobs SET locked_at=NULL WHERE id=?", (job_id,))

    def has_active_jobs(self) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM jobs WHERE state NOT IN (?,?,?,?)",
                (
                    JobState.PUBLISHED.value,
                    JobState.CANCELLED.value,
                    JobState.REJECTED.value,
                    JobState.READY_FOR_APPROVAL.value,
                ),
            ).fetchone()
        return int(row["n"]) > 0

    # --- resume ---------------------------------------------------------

    def next_stage(self, job_id: str) -> JobState | None:
        """Earliest pipeline stage whose artifact is missing or incomplete."""
        record = self.get(job_id)
        if record.state in (JobState.PUBLISHED, JobState.READY_FOR_APPROVAL, JobState.APPROVED):
            return None
        job_dir = self.artifacts_root / job_id
        for state in PIPELINE_ORDER:
            artifact = ARTIFACT_FOR_STATE.get(state)
            if artifact is None:
                continue
            if state is JobState.EDITORIAL_QC and (job_dir / "qc.json").exists():
                continue
            if not (job_dir / artifact).exists():
                return state
        return None

    # --- artifacts -------------------------------------------------------

    def artifact_dir(self, job_id: str) -> Path:
        path = self.artifact_root(job_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write_artifact(self, job_id: str, name: str, data: Any) -> Path:
        if not re.fullmatch(r"[a-z][a-z0-9_]*\.json", name):
            raise ValueError("artifact name must be a canonical JSON filename")
        validated = validate_artifact(name, data)
        path = self.artifact_dir(job_id) / name
        text = json.dumps(validated, ensure_ascii=False, indent=2, allow_nan=False)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)  # atomic on same volume: never a half-written artifact
        return path

    def read_artifact(self, job_id: str, name: str) -> Any:
        path = self.artifact_root(job_id) / name
        if not path.exists():
            raise FileNotFoundError(path)
        return json.loads(path.read_text(encoding="utf-8"))

    def artifact_root(self, job_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{16}", job_id):
            raise ValueError("invalid job id")
        return self.artifacts_root / job_id


def _stale_before() -> str:
    from datetime import timedelta

    return (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat(timespec="seconds")


def _to_record(row: sqlite3.Row) -> JobRecord:
    return JobRecord(
        id=row["id"],
        title=row["title"],
        state=JobState(row["state"]),
        attempts=int(row["attempts"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        payload=json.loads(row["payload"] or "{}"),
        last_error=row["last_error"],
    )
