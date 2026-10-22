"""Read-only production schedule: what is being made, what is queued, what is next.

Every status is derived from the persisted state machine and the optional seven-day
plan, never from an in-memory guess. Nothing here mutates state, calls a provider or
starts a worker, so the schedule cannot claim progress that no artifact supports.

Status vocabulary (the operator-facing labels):
    RESEARCHING  research and writing, before a storyboard exists
    ON GOING     actively in production, from storyboard through publishing
    UPCOMING     a planned slot whose due time has not arrived and no work has begun
    SELESAI      published
    GAGAL        terminal failure
    TERTAHAN     blocked, cancelled or rejected by the operator
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..orchestration.jobstore import JobRecord, JobStore
from ..orchestration.states import PIPELINE_ORDER, JobState
from .events import safe_text, utc_now

RESEARCHING = "RESEARCHING"
ON_GOING = "ON GOING"
UPCOMING = "UPCOMING"
DONE = "SELESAI"
FAILED = "GAGAL"
BLOCKED = "TERTAHAN"

#: Display order, most actionable first.
STATUS_ORDER = (ON_GOING, RESEARCHING, UPCOMING, DONE, FAILED, BLOCKED)

_RESEARCH_STATES = frozenset({
    JobState.IDEA_DISCOVERY, JobState.TOPIC_SELECTED,
    JobState.SCRIPT_GENERATED, JobState.CREATIVE_REVIEW,
})
_DONE_STATES = frozenset({JobState.PUBLISHED})
_FAILED_STATES = frozenset({JobState.FAILED})
_BLOCKED_STATES = frozenset({JobState.BLOCKED, JobState.CANCELLED, JobState.REJECTED})

_STAGE_LABEL = {
    JobState.IDEA_DISCOVERY: "Riset ide",
    JobState.TOPIC_SELECTED: "Topik dipilih",
    JobState.SCRIPT_GENERATED: "Naskah",
    JobState.CREATIVE_REVIEW: "Review kreatif",
    JobState.STORYBOARD_READY: "Storyboard",
    JobState.ASSETS_READY: "Aset",
    JobState.AUDIO_READY: "Audio",
    JobState.RENDERING: "Render",
    JobState.TECHNICAL_QC: "QC teknis",
    JobState.EDITORIAL_QC: "QC editorial",
    JobState.READY_FOR_APPROVAL: "Menunggu approval",
    JobState.APPROVED: "Disetujui",
    JobState.PRIVATE_UPLOAD: "Upload privat",
    JobState.SCHEDULED: "Terjadwal",
    JobState.PUBLISHED: "Terbit",
    JobState.FAILED: "Gagal",
    JobState.CANCELLED: "Dibatalkan",
    JobState.REJECTED: "Ditolak",
    JobState.BLOCKED: "Tertahan",
}

_NEXT_ACTION = {
    JobState.IDEA_DISCOVERY: "Mengumpulkan kandidat topik",
    JobState.TOPIC_SELECTED: "Menyusun naskah",
    JobState.SCRIPT_GENERATED: "Menunggu review kreatif",
    JobState.CREATIVE_REVIEW: "Review kreatif berjalan",
    JobState.STORYBOARD_READY: "Menyiapkan aset",
    JobState.ASSETS_READY: "Menyalin narasi",
    JobState.AUDIO_READY: "Menunggu render",
    JobState.RENDERING: "Merender video",
    JobState.TECHNICAL_QC: "Memeriksa teknis",
    JobState.EDITORIAL_QC: "Memeriksa editorial",
    JobState.READY_FOR_APPROVAL: "Menunggu keputusan operator",
    JobState.APPROVED: "Menunggu unggahan privat",
    JobState.PRIVATE_UPLOAD: "Mengunggah privat",
    JobState.SCHEDULED: "Menunggu jadwal terbit",
    JobState.PUBLISHED: "Selesai terbit",
    JobState.FAILED: "Perlu dijalankan ulang",
    JobState.CANCELLED: "Dihentikan operator",
    JobState.REJECTED: "Ditolak operator",
    JobState.BLOCKED: "Menunggu tindakan operator",
}


def _read_json(root: Path, name: str) -> dict:
    """Best-effort read of a display-only field.

    Deliberately not ``validate_artifact``: a schedule overview must still list a job
    whose optional sidecar is missing or stale. Nothing read here is reported as a
    passed stage.
    """
    path = root / name
    try:
        if not path.is_file() or path.stat().st_size > 2_000_000:
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _stage_index(state: JobState) -> int:
    try:
        return PIPELINE_ORDER.index(state)
    except ValueError:
        return 0


def _progress(index: int) -> int:
    return round(100 * index / (len(PIPELINE_ORDER) - 1))


def _classify(state: JobState, due: datetime | None, dispatched: bool, now: datetime) -> str:
    if state in _DONE_STATES:
        return DONE
    if state in _FAILED_STATES:
        return FAILED
    if state in _BLOCKED_STATES:
        return BLOCKED
    if _is_upcoming(state, due, dispatched, now):
        return UPCOMING
    if state in _RESEARCH_STATES:
        return RESEARCHING
    return ON_GOING


def _is_upcoming(state: JobState, due: datetime | None, dispatched: bool, now: datetime) -> bool:
    """A scheduled slot whose due time has not arrived and that was never dispatched.

    A job that has already left IDEA_DISCOVERY is being worked on regardless of its
    planned time, so a passed deadline never rewrites real progress as "waiting".
    """
    if state is not JobState.IDEA_DISCOVERY or dispatched:
        return False
    return due is not None and due > now


class ScheduleService:
    def __init__(self, store: JobStore) -> None:
        self.store = store

    def _slots(self) -> dict[str, dict]:
        with self.store._connect() as conn:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "production_slots" not in tables:
                return {}
            return {row["job_id"]: dict(row)
                    for row in conn.execute("SELECT * FROM production_slots")}

    def _furthest(self) -> dict[str, int]:
        """Highest pipeline stage each job actually reached, from its own event log.

        A failed job keeps the progress it earned instead of dropping back to zero.
        """
        with self.store._connect() as conn:
            rows = conn.execute("SELECT job_id, to_state FROM job_events").fetchall()
        best: dict[str, int] = {}
        for row in rows:
            try:
                index = _stage_index(JobState(row["to_state"]))
            except ValueError:
                continue
            if index > best.get(row["job_id"], -1):
                best[row["job_id"]] = index
        return best

    def _content(self, root: Path) -> dict[str, Any]:
        topic = _read_json(root, "topic.json")
        script = _read_json(root, "script.json")
        storyboard = _read_json(root, "storyboard.json")
        render = _read_json(root, "render.json")
        metadata = _read_json(root, "metadata.json")
        verification = _read_json(root, "verification.json")

        templates: list[str] = []
        scenes = storyboard.get("scenes")
        if isinstance(scenes, list):
            for scene in scenes:
                name = scene.get("template") if isinstance(scene, dict) else None
                if isinstance(name, str) and name not in templates:
                    templates.append(name)

        topic_body = topic.get("topic") if isinstance(topic.get("topic"), dict) else {}
        genre = topic_body.get("genre") or script.get("genre")
        headline = metadata.get("title") or script.get("title")
        duration = render.get("duration_ms")
        return {
            "genre": genre if isinstance(genre, str) else None,
            "content_type": script.get("content_type") if isinstance(script.get("content_type"), str) else None,
            "headline": headline if isinstance(headline, str) and headline.strip() else None,
            "templates": templates[:6],
            "scene_count": len(scenes) if isinstance(scenes, list) else 0,
            "duration_ms": float(duration) if isinstance(duration, (int, float)) else None,
            "verification": (verification.get("status") if isinstance(verification.get("status"), str)
                             else script.get("verification_status") if isinstance(script.get("verification_status"), str)
                             else "unverified"),
            "sources": len(topic_body.get("sources") or []) if isinstance(topic_body.get("sources"), list) else 0,
        }

    def _entry(self, job: JobRecord, slot: dict | None, now: datetime, furthest: int) -> dict[str, Any]:
        root = self.store.artifact_root(job.id)
        content = self._content(root)
        due = _parse_time(slot.get("due_at")) if slot else None
        if due is None:
            due = _parse_time(job.payload.get("due_at"))
        dispatched = int(slot.get("attempts") or 0) > 0 if slot else False
        status = _classify(job.state, due, dispatched, now)
        index = furthest if job.state not in PIPELINE_ORDER else _stage_index(job.state)
        next_action = _NEXT_ACTION.get(job.state, "—")
        if status == UPCOMING and due is not None:
            next_action = f"Dijadwalkan {due.astimezone().strftime('%d %b %H:%M')}"
        elif status == FAILED and job.last_error:
            next_action = safe_text(job.last_error, 120)
        return {
            "job_id": job.id,
            "title": safe_text(content["headline"] or job.title or "Tanpa judul", 120),
            "status": status,
            "state": job.state.value,
            "stage_label": _STAGE_LABEL.get(job.state, job.state.value),
            "next_action": next_action,
            "genre": content["genre"],
            "content_type": content["content_type"],
            "templates": content["templates"],
            "scene_count": content["scene_count"],
            "duration_ms": content["duration_ms"],
            "verification": content["verification"],
            "sources": content["sources"],
            "progress": _progress(index),
            "due_at": due.isoformat() if due else None,
            "plan_id": slot.get("plan_id") if slot else job.payload.get("plan_id"),
            "slot_status": slot.get("status") if slot else None,
            "attempts": int(slot.get("attempts") or 0) if slot else job.attempts,
            "source": "demo_fixture" if job.payload.get("studio_fixture") is True else (
                "mock" if job.payload.get("provider_mode") == "mock" else "production"),
            "approval_required": job.state is JobState.READY_FOR_APPROVAL,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
        }

    def entries(self) -> dict[str, Any]:
        now = utc_now()
        slots = self._slots()
        furthest = self._furthest()
        jobs = self.store.list(limit=200)
        rows = [self._entry(job, slots.get(job.id), now, furthest.get(job.id, 0)) for job in jobs]

        rows.sort(key=lambda entry: entry["updated_at"], reverse=True)
        rows.sort(key=lambda entry: (
            STATUS_ORDER.index(entry["status"]) if entry["status"] in STATUS_ORDER else len(STATUS_ORDER),
            entry["due_at"] or "9999",
        ))
        counts = Counter(entry["status"] for entry in rows)
        return {
            "generated_at": now.isoformat(),
            "counts": {name: counts.get(name, 0) for name in STATUS_ORDER},
            "total": len(rows),
            "entries": rows,
        }
