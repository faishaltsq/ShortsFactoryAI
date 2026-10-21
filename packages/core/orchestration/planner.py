"""Atomic seven-day plans; no providers or background workers are involved."""
from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass, fields
from datetime import datetime, timedelta, timezone
from typing import Sequence

from ..schemas import Genre
from .jobstore import JobStore


@dataclass(frozen=True)
class PlanSlot:
    id: str
    plan_id: str
    day_index: int
    slot_index: int
    due_at: str
    genre: str
    provider_mode: str
    job_id: str
    status: str
    attempts: int
    max_attempts: int
    retry_base_s: float


@dataclass(frozen=True)
class ProductionPlan:
    id: str
    start: str
    timezone: str
    videos_per_day: int
    genres: tuple[str, ...]
    provider_mode: str
    slots: tuple[PlanSlot, ...]


class ProductionPlanner:
    def __init__(self, store: JobStore) -> None:
        self.store = store
        with store._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS production_plans (
                    id TEXT PRIMARY KEY,
                    start TEXT NOT NULL,
                    timezone TEXT NOT NULL,
                    videos_per_day INTEGER NOT NULL,
                    genres TEXT NOT NULL,
                    provider_mode TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS production_slots (
                    id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL REFERENCES production_plans(id),
                    day_index INTEGER NOT NULL,
                    slot_index INTEGER NOT NULL,
                    due_at TEXT NOT NULL,
                    genre TEXT NOT NULL,
                    provider_mode TEXT NOT NULL,
                    job_id TEXT NOT NULL UNIQUE REFERENCES jobs(id),
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(plan_id, day_index, slot_index)
                );
                CREATE INDEX IF NOT EXISTS idx_production_slots_due ON production_slots(status, due_at);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_production_slots_unique_due ON production_slots(due_at);
            """)
            conn.execute("BEGIN IMMEDIATE")
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(production_slots)")}
            for name, definition in (("max_attempts", "INTEGER NOT NULL DEFAULT 3"),
                                     ("retry_base_s", "REAL NOT NULL DEFAULT 60")):
                if name not in columns:
                    conn.execute(f"ALTER TABLE production_slots ADD COLUMN {name} {definition}")

    def plan_seven_days(self, *, start: datetime, videos_per_day: int, genres: Sequence[str],
                        provider_mode: str = "mock", max_attempts: int = 3,
                        retry_base_s: float = 60) -> ProductionPlan:
        if start.tzinfo is None or start.utcoffset() is None:
            raise ValueError("start must be a timezone-aware datetime")
        if type(videos_per_day) is not int or not 1 <= videos_per_day <= 1000:
            raise ValueError("videos_per_day must be an integer from 1 to 1000")
        if provider_mode not in {"mock", "live"}:
            raise ValueError("provider_mode must be mock or live")
        if not genres or isinstance(genres, str):
            raise ValueError("genres must be a nonempty sequence")
        if type(max_attempts) is not int or not 1 <= max_attempts <= 10:
            raise ValueError("max_attempts must be an integer from 1 to 10")
        if not math.isfinite(retry_base_s) or not 0 < retry_base_s <= 86400:
            raise ValueError("retry_base_s must be finite and between 0 and 86400")
        zone = getattr(start.tzinfo, "key", str(start.tzinfo))
        genre_values = tuple(Genre(genre).value for genre in genres)
        retry_base_s = float(retry_base_s)
        spec = [start.isoformat(), zone, videos_per_day, genre_values, provider_mode, max_attempts, retry_base_s]
        plan_id = uuid.uuid5(uuid.NAMESPACE_URL, json.dumps(spec)).hex
        stamp = self.store.utc_now().isoformat()
        with self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM production_plans WHERE id=?", (plan_id,)).fetchone() is None:
                conn.execute("INSERT INTO production_plans VALUES (?,?,?,?,?,?,?)",
                             (plan_id, start.isoformat(), zone, videos_per_day, json.dumps(genre_values),
                              provider_mode, stamp))
                for day in range(7):
                    begin = (start + timedelta(days=day)).astimezone(timezone.utc)
                    end = (start + timedelta(days=day + 1)).astimezone(timezone.utc)
                    for index in range(videos_per_day):
                        slot_id = uuid.uuid5(uuid.NAMESPACE_URL, f"{plan_id}:{day}:{index}").hex
                        job_id = uuid.uuid4().hex[:16]
                        genre = genre_values[(day * videos_per_day + index) % len(genre_values)]
                        due = (begin + (end - begin) * (index / videos_per_day)).isoformat()
                        if conn.execute("SELECT 1 FROM production_slots WHERE due_at=?", (due,)).fetchone():
                            raise ValueError("plan overlaps an existing production slot; reuse the existing plan")
                        payload = {"plan_id": plan_id, "plan_slot_id": slot_id, "genre": genre,
                                   "provider_mode": provider_mode, "due_at": due}
                        conn.execute("INSERT INTO jobs (id,title,state,payload,created_at,updated_at) "
                                     "VALUES (?,?,'IDEA_DISCOVERY',?,?,?)",
                                     (job_id, f"Produksi {genre} {due}", json.dumps(payload), stamp, stamp))
                        conn.execute("INSERT INTO job_events (job_id,from_state,to_state,detail,created_at) "
                                     "VALUES (?,NULL,'IDEA_DISCOVERY','planned',?)", (job_id, stamp))
                        conn.execute("INSERT INTO production_slots "
                                     "(id,plan_id,day_index,slot_index,due_at,genre,provider_mode,job_id,"
                                     "max_attempts,retry_base_s) VALUES (?,?,?,?,?,?,?,?,?,?)",
                                     (slot_id, plan_id, day, index, due, genre, provider_mode, job_id,
                                      max_attempts, retry_base_s))
        plan = self.get(plan_id)
        for slot in plan.slots:
            if not (self.store.artifact_root(slot.job_id) / "job.json").is_file():
                self.store.snapshot(slot.job_id)
        return plan

    def get(self, plan_id: str) -> ProductionPlan:
        with self.store._connect() as conn:
            row = conn.execute("SELECT * FROM production_plans WHERE id=?", (plan_id,)).fetchone()
            if row is None:
                raise KeyError(f"plan {plan_id} not found")
            slots = conn.execute("SELECT * FROM production_slots WHERE plan_id=? ORDER BY day_index,slot_index",
                                 (plan_id,)).fetchall()
        return ProductionPlan(row["id"], row["start"], row["timezone"], row["videos_per_day"],
                              tuple(json.loads(row["genres"])), row["provider_mode"],
                              tuple(PlanSlot(**{field.name: slot[field.name] for field in fields(PlanSlot)})
                                    for slot in slots))
