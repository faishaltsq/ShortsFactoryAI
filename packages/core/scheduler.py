"""Recurring production scheduler, independent of the HTTP transport."""
from __future__ import annotations

import datetime as dt
import logging
import threading
from dataclasses import dataclass
from typing import Callable

from .orchestration.jobstore import JobStore
from .orchestration.states import JobState
from .studio import ScheduleOverride, StudioConfigError, load_studio

log = logging.getLogger("shorts.scheduler")
STALE_HOURS = 6
_TERMINAL = {
    JobState.TECHNICAL_QC, JobState.EDITORIAL_QC, JobState.READY_FOR_APPROVAL,
    JobState.APPROVED, JobState.PUBLISHED, JobState.CANCELLED, JobState.REJECTED,
    JobState.FAILED, JobState.BLOCKED,
}
_DEFAULTS: dict[str, object] = {
    "interval_hours": 24, "max_per_day": 1, "gap_minutes": 0,
    "mode": "live", "stop": "approval", "max_pending_approval": 3,
}


@dataclass(frozen=True)
class SchedulePlan:
    due: bool
    reason: str
    title: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {"due": self.due, "reason": self.reason, "title": self.title}


def _effective(schedule: ScheduleOverride) -> dict[str, object]:
    config = dict(_DEFAULTS)
    for key in _DEFAULTS:
        value = getattr(schedule, key, None)
        if value is not None:
            config[key] = value
    return config


def _parse(value: str | None) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def _aware(value: dt.datetime, timezone: dt.tzinfo) -> dt.datetime:
    return value.replace(tzinfo=dt.timezone.utc) if value.tzinfo is None else value.astimezone(timezone)


def _jobs_today(jobs: list, now: dt.datetime) -> list:
    return [job for job in jobs
            if (created := _parse(job.created_at)) is not None
            and _aware(created, now.tzinfo or dt.timezone.utc).date() == now.date()]


def _is_running(job, now: dt.datetime, active_ids: set[str] | None) -> bool:
    if job.state in _TERMINAL:
        return False
    if active_ids is not None:
        return job.id in active_ids
    touched = _parse(getattr(job, "updated_at", "") or "") or _parse(job.created_at)
    if touched is None:
        return True
    now_tz = now.tzinfo or dt.timezone.utc
    age = (now - _aware(touched, now_tz)).total_seconds() / 3600
    return age < STALE_HOURS


def due_at(schedule: ScheduleOverride, jobs: list, *, now: dt.datetime,
           active_ids: set[str] | None = None) -> SchedulePlan:
    config = _effective(schedule)
    if not schedule.enabled:
        return SchedulePlan(False, "scheduler dimatikan")
    if now.hour in set(schedule.quiet_hours or []):
        return SchedulePlan(False, f"jam sepi ({now.hour:02d}:00)")
    hours = set(schedule.posting_hours or [])
    if hours and now.hour not in hours:
        return SchedulePlan(False, f"di luar jam tayang ({now.hour:02d}:00)")
    pending = sum(1 for job in jobs if job.state is JobState.READY_FOR_APPROVAL)
    cap = int(config["max_pending_approval"])
    if cap and pending >= cap:
        return SchedulePlan(False, f"menunggu review ({pending}/{cap})")
    for job in jobs:
        if _is_running(job, now, active_ids):
            return SchedulePlan(False, f"job {job.id} masih berjalan ({job.state.value})")
    today = _jobs_today(jobs, now)
    if len(today) >= int(config["max_per_day"]):
        return SchedulePlan(False, f"batas harian tercapai ({len(today)}/{config['max_per_day']})")
    valid_created = [_parse(job.created_at) for job in jobs]
    last = max((value for value in valid_created if value is not None), default=None)
    if last is not None:
        now_tz = now.tzinfo or dt.timezone.utc
        elapsed_minutes = (now - _aware(last, now_tz)).total_seconds() / 60
        wait_minutes = max(int(config["gap_minutes"]), int(config["interval_hours"]) * 60)
        if elapsed_minutes < wait_minutes:
            return SchedulePlan(False, f"jeda belum lewat ({int(elapsed_minutes)}/{wait_minutes} menit sejak job terakhir)")
    used = {job.title.strip().lower() for job in jobs}
    topics = [topic.strip() for topic in (schedule.topics or []) if topic and topic.strip()]
    title = next((topic for topic in topics if topic.lower() not in used), None)
    return SchedulePlan(True, "jatuh tempo", title)


def avoid_titles(jobs: list, limit: int = 60) -> list[str]:
    return [job.title for job in sorted(jobs, key=lambda item: item.created_at, reverse=True)
            if job.title.strip()][:limit]


class Scheduler:
    def __init__(self, store: JobStore, *, create_job: Callable[..., str], tick_seconds: int = 60,
                 now_fn: Callable[[], dt.datetime] | None = None,
                 active_ids_fn: Callable[[], set[str] | None] | None = None) -> None:
        self.store = store
        self.create_job = create_job
        self.tick_seconds = max(10, int(tick_seconds))
        self._now = now_fn or (lambda: dt.datetime.now().astimezone())
        self._active_ids = active_ids_fn or (lambda: None)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_plan: dict[str, object] | None = None
        self.last_error: str | None = None
        self.created: list[str] = []

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="scheduler")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def tick(self) -> SchedulePlan:
        try:
            config = load_studio()
        except StudioConfigError as exc:
            self.last_error = f"studio config invalid: {exc}"
            return SchedulePlan(False, self.last_error)
        jobs = self.store.list(limit=500)
        plan = due_at(config.schedule, jobs, now=self._now(), active_ids=self._active_ids())
        self.last_plan = plan.as_dict()
        self.last_error = None
        if not plan.due:
            return plan
        options = _effective(config.schedule)
        title = plan.title or f"Otomatis {self._now().strftime('%Y-%m-%d %H:%M')}"
        try:
            job_id = self.create_job(title=title, mode=str(options["mode"]),
                                     stop=str(options["stop"]), avoid=avoid_titles(jobs))
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            log.exception("scheduler failed to create job")
            return SchedulePlan(False, self.last_error)
        self.created.append(job_id)
        return SchedulePlan(True, "job dibuat", title)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("scheduler tick crashed")
            self._stop.wait(self.tick_seconds)


def status_payload(scheduler: Scheduler | None, schedule: ScheduleOverride) -> dict[str, object]:
    config = _effective(schedule)
    return {
        "enabled": bool(schedule.enabled),
        "running": bool(scheduler and scheduler.running),
        "interval_hours": config["interval_hours"],
        "max_per_day": config["max_per_day"],
        "gap_minutes": config["gap_minutes"],
        "mode": config["mode"],
        "stop": config["stop"],
        "topics": list(schedule.topics or []),
        "quiet_hours": list(schedule.quiet_hours or []),
        "posting_hours": list(schedule.posting_hours or []),
        "max_pending_approval": config["max_pending_approval"],
        "last_plan": scheduler.last_plan if scheduler else None,
        "last_error": scheduler.last_error if scheduler else None,
        "created": list(scheduler.created[-20:]) if scheduler else [],
    }
