"""Append-only, versioned SQLite observability beside the job state store."""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .events import StudioEvent

_COLUMNS = tuple(StudioEvent.model_fields)


class StudioEventStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        with self.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS studio_migrations (
                    version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS studio_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES jobs(id),
                    agent_id TEXT NOT NULL, event_type TEXT NOT NULL, status TEXT NOT NULL,
                    timestamp TEXT NOT NULL, description TEXT NOT NULL, progress REAL,
                    model TEXT, stage TEXT, run_id TEXT, source TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_studio_task ON studio_events(job_id, agent_id, event_id DESC);
                CREATE TABLE IF NOT EXISTS studio_worker_leases (
                    job_id TEXT PRIMARY KEY REFERENCES jobs(id), run_id TEXT NOT NULL,
                    expires_at REAL NOT NULL
                );
                INSERT OR IGNORE INTO studio_migrations(version) VALUES (1);
            """)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def emit(self, **fields) -> StudioEvent:
        event = StudioEvent(event_id=1, **fields)
        data = event.model_dump(mode="json")
        names = [name for name in _COLUMNS if name != "event_id"]
        with self.connect() as conn:
            cur = conn.execute(
                f"INSERT INTO studio_events ({','.join(names)}) VALUES ({','.join('?' for _ in names)})",
                [data[name] for name in names],
            )
            return event.model_copy(update={"event_id": cur.lastrowid})

    def page(self, *, after: int = 0, limit: int = 100, job_id: str | None = None,
             through: int | None = None) -> list[StudioEvent]:
        if after < 0 or not 1 <= limit <= 500:
            raise ValueError("invalid event cursor or page size")
        query = "SELECT * FROM studio_events WHERE event_id>?"
        params: list = [after]
        if through is not None:
            query += " AND event_id<=?"
            params.append(through)
        if job_id is not None:
            query += " AND job_id=?"
            params.append(job_id)
        query += " ORDER BY event_id LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            return [self._event(row) for row in conn.execute(query, params)]

    @staticmethod
    def _event(row: sqlite3.Row) -> StudioEvent:
        return StudioEvent.model_validate({name: row[name] for name in _COLUMNS})

    def begin_run(self, job_id: str, run_id: str, *, ttl_s: float = 20) -> None:
        with self.connect() as conn:
            conn.execute("INSERT INTO studio_worker_leases VALUES (?,?,?) ON CONFLICT(job_id) DO UPDATE "
                         "SET run_id=excluded.run_id, expires_at=excluded.expires_at",
                         (job_id, run_id, time.time() + ttl_s))

    def heartbeat(self, job_id: str, run_id: str, *, ttl_s: float = 20) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE studio_worker_leases SET expires_at=? WHERE job_id=? AND run_id=?",
                         (time.time() + ttl_s, job_id, run_id))

    def end_run(self, job_id: str, run_id: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE studio_worker_leases SET expires_at=0 WHERE job_id=? AND run_id=?", (job_id, run_id))

    def raw_snapshot(self, *, job_id: str | None = None) -> dict:
        with self.connect() as conn:
            conn.execute("BEGIN")
            cursor = conn.execute("SELECT COALESCE(MAX(event_id),0) FROM studio_events").fetchone()[0]
            jobs = [dict(row) for row in conn.execute(
                "SELECT * FROM jobs" + (" WHERE id=?" if job_id else "") + " ORDER BY updated_at DESC, id DESC LIMIT 100",
                (job_id,) if job_id else (),
            )]
            job_ids = [row["id"] for row in jobs]
            if not job_ids:
                return {"cursor": cursor, "jobs": [], "latest": [], "events": [], "leases": {}}
            placeholders = ",".join("?" for _ in job_ids)
            latest = [self._event(row) for row in conn.execute(
                "SELECT * FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY job_id,agent_id ORDER BY event_id DESC) AS rn "
                f"FROM studio_events WHERE event_id<=? AND job_id IN ({placeholders})) WHERE rn=1",
                [cursor, *job_ids],
            )]
            events = [self._event(row) for row in conn.execute(
                f"SELECT * FROM studio_events WHERE event_id<=? AND job_id IN ({placeholders}) ORDER BY event_id DESC LIMIT 100",
                [cursor, *job_ids],
            )]
            leases = {row["job_id"]: dict(row) for row in conn.execute(
                f"SELECT * FROM studio_worker_leases WHERE job_id IN ({placeholders})", job_ids)}
            for job in jobs:
                job["payload"] = json.loads(job["payload"])
            return {"cursor": cursor, "jobs": jobs, "latest": latest, "events": events, "leases": leases}
