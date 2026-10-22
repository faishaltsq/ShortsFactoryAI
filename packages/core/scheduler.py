"""Scheduler produksi berulang.

Satu thread di dalam proses API yang memeriksa apakah sudah waktunya membuat job
berikutnya. Semua keputusan ("boleh bikin job sekarang?") ada di fungsi murni
`due_at`, sehingga bisa diuji tanpa menunggu jam sungguhan dan tanpa menyentuh
database.

Prinsip yang dipegang:

- Default mati. Operator harus menyalakan lewat Studio.
- Satu job pada satu waktu. Scheduler tidak pernah menumpuk job berjalan.
- Batas harian dihormati, termasuk hitungan job yang dibuat manual.
- Jam sepi dilewati, bukan ditembak.
- Tidak ada ide yang diulang: judul yang sudah pernah dibuat dikirim sebagai
  `avoid_titles` ke ResearchAgent.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
from dataclasses import dataclass

from .orchestration.jobstore import JobStore
from .orchestration.states import JobState
from .studio import ScheduleOverride, StudioConfigError, load_studio

log = logging.getLogger("shorts.scheduler")

# Job yang sudah selesai tidak dihitung sebagai "sedang berjalan", tapi tetap
# dihitung untuk batas harian dan anti-duplikasi judul.
_TERMINAL = {
    JobState.TECHNICAL_QC,
    JobState.EDITORIAL_QC,
    JobState.READY_FOR_APPROVAL,
    JobState.APPROVED,
    JobState.PUBLISHED,
    JobState.CANCELLED,
    JobState.REJECTED,
    JobState.FAILED,
    JobState.BLOCKED,
}

# Job yang tidak tersentuh selama ini dianggap terbengkalai, bukan berjalan.
# Tanpa batas ini satu job yang ditinggal di tengah jalan memblokir scheduler
# selamanya — persis kebalikan dari tujuan scheduler. Satu run penuh memakan
# ~5 menit, jadi 6 jam sudah 70x durasi normal dan tidak mungkin run hidup.
STALE_HOURS = 6

_DEFAULTS = {
    "interval_hours": 24,
    "max_per_day": 1,
    "gap_minutes": 0,
    "mode": "live",
    "stop": "render",
}


@dataclass(frozen=True)
class SchedulePlan:
    """Hasil keputusan: bikin job atau tidak, dan kenapa."""

    due: bool
    reason: str
    title: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {"due": self.due, "reason": self.reason, "title": self.title}


def _effective(schedule: ScheduleOverride) -> dict[str, object]:
    """Gabungkan setelan operator dengan default yang aman."""
    merged = dict(_DEFAULTS)
    for key in ("interval_hours", "max_per_day", "gap_minutes", "mode", "stop"):
        value = getattr(schedule, key, None)
        if value is not None:
            merged[key] = value
    return merged


def _parse(ts: str) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None


def _jobs_today(jobs: list, now: dt.datetime) -> list:
    """Job yang dibuat pada tanggal kalender lokal `now`."""
    same_day = []
    for job in jobs:
        created = _parse(job.created_at)
        if created is None:
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=dt.timezone.utc)
        if created.astimezone(now.tzinfo).date() == now.date():
            same_day.append(job)
    return same_day


def _is_running(job, now: dt.datetime, active_ids: set[str] | None = None) -> bool:
    """Job non-terminal yang benar-benar sedang dikerjakan.

    `active_ids` adalah daftar job yang punya run aktif di proses ini — sumber
    kebenaran sebenarnya. Tanpa itu, job yang ditinggal di tengah jalan akan
    memblokir scheduler selama-lamanya hanya karena `updated_at`-nya belum tua.
    Ambang `STALE_HOURS` tetap dipakai sebagai jaring pengaman untuk job yatim
    dari proses sebelumnya (API restart, mesin mati).
    """
    if job.state in _TERMINAL:
        return False
    if active_ids is not None:
        return job.id in active_ids
    touched = _parse(getattr(job, "updated_at", "") or "") or _parse(job.created_at)
    if touched is None:
        return True
    if touched.tzinfo is None:
        touched = touched.replace(tzinfo=dt.timezone.utc)
    age_h = (now - touched.astimezone(now.tzinfo)).total_seconds() / 3600
    return age_h < STALE_HOURS


def due_at(schedule: ScheduleOverride, jobs: list, *, now: dt.datetime,
           active_ids: set[str] | None = None) -> SchedulePlan:
    """Putuskan apakah sudah waktunya membuat job berikutnya.

    Fungsi murni: tidak menyentuh disk, database, atau jam sistem. Semua input
    diberikan pemanggil, sehingga perilaku bisa diuji pada jam berapa pun.
    """
    cfg = _effective(schedule)

    if not schedule.enabled:
        return SchedulePlan(False, "scheduler dimatikan")

    quiet = set(schedule.quiet_hours or [])
    if now.hour in quiet:
        return SchedulePlan(False, f"jam sepi ({now.hour:02d}:00)")

    # Satu job pada satu waktu: menumpuk job paralel hanya menggandakan biaya
    # dan membuat render saling berebut CPU. Job yang ditinggal tidak menghitung.
    for job in jobs:
        if _is_running(job, now, active_ids):
            return SchedulePlan(False, f"job {job.id} masih berjalan ({job.state.value})")

    today = _jobs_today(jobs, now)
    if len(today) >= int(cfg["max_per_day"]):
        return SchedulePlan(False, f"batas harian tercapai ({len(today)}/{cfg['max_per_day']})")

    # Jeda minimum sejak job terakhir. `gap_minutes` mengatur jarak antar-job
    # dalam satu hari; `interval_hours` mengatur irama utama. Yang lebih ketat
    # menang, supaya dua setelan tidak saling membatalkan.
    if jobs:
        last = max(
            (_parse(j.created_at) for j in jobs if _parse(j.created_at) is not None),
            default=None,
        )
        if last is not None:
            if last.tzinfo is None:
                last = last.replace(tzinfo=dt.timezone.utc)
            elapsed_min = (now - last.astimezone(now.tzinfo)).total_seconds() / 60
            wait = max(int(cfg["gap_minutes"]), int(cfg["interval_hours"]) * 60)
            if elapsed_min < wait:
                return SchedulePlan(
                    False,
                    f"jeda belum lewat ({int(elapsed_min)}/{wait} menit sejak job terakhir)",
                )

    # Judul berikutnya: putar daftar topik operator, lewati yang sudah dipakai.
    used = {j.title.strip().lower() for j in jobs}
    topics = [t.strip() for t in (schedule.topics or []) if t and t.strip()]
    fresh = [t for t in topics if t.lower() not in used]
    if fresh:
        title = fresh[0]
    elif topics:
        # Semua topik sudah dipakai: jangan ulangi. Biarkan ResearchAgent
        # mengarang arah baru, tapi beri tahu judul yang harus dihindari.
        title = None
    else:
        title = None

    return SchedulePlan(True, "jatuh tempo", title=title)


def avoid_titles(jobs: list, limit: int = 60) -> list[str]:
    """Judul yang sudah pernah dipakai, terbaru dulu.

    Dikirim ke ResearchAgent supaya ia tidak mengusulkan ide yang sama lagi.
    Ini yang mencegah "kehabisan ide" menjadi "video berulang".
    """
    ordered = sorted(jobs, key=lambda j: j.created_at, reverse=True)
    return [j.title for j in ordered if j.title.strip()][:limit]


class Scheduler:
    """Thread pengawas: tidur, periksa, buat job bila jatuh tempo."""

    def __init__(
        self,
        store: JobStore,
        *,
        create_job,
        tick_seconds: int = 60,
        now_fn=None,
        active_ids_fn=None,
    ) -> None:
        self.store = store
        self.create_job = create_job
        self.tick_seconds = max(10, int(tick_seconds))
        self._now = now_fn or (lambda: dt.datetime.now().astimezone())
        # Sumber kebenaran "job mana yang benar-benar berjalan". Diberikan API
        # karena hanya proses itu yang tahu run aktifnya.
        self._active_ids = active_ids_fn or (lambda: None)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_plan: dict[str, object] | None = None
        self.last_error: str | None = None
        self.created: list[str] = []

    # --- lifecycle ------------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="scheduler")
        self._thread.start()
        log.info("scheduler started (tick %ss)", self.tick_seconds)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        log.info("scheduler stopped")

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # --- one decision ---------------------------------------------------
    def tick(self) -> SchedulePlan:
        """Satu putaran pemeriksaan. Aman dipanggil manual untuk diagnosa."""
        try:
            studio = load_studio()
        except StudioConfigError as exc:
            self.last_error = f"studio config invalid: {exc}"
            return SchedulePlan(False, self.last_error)

        jobs = self.store.list(limit=500)
        plan = due_at(studio.schedule, jobs, now=self._now(), active_ids=self._active_ids())
        self.last_plan = plan.as_dict()
        self.last_error = None

        if not plan.due:
            return plan

        cfg = _effective(studio.schedule)
        title = plan.title or f"Otomatis {self._now().strftime('%Y-%m-%d %H:%M')}"
        try:
            job_id = self.create_job(
                title=title,
                mode=str(cfg["mode"]),
                stop=str(cfg["stop"]),
                avoid=avoid_titles(jobs),
            )
        except Exception as exc:  # noqa: BLE001 - batas thread
            self.last_error = f"{type(exc).__name__}: {exc}"
            log.exception("scheduler failed to create job")
            return SchedulePlan(False, self.last_error)

        self.created.append(job_id)
        log.info("scheduler created job %s (%s)", job_id, title)
        return SchedulePlan(True, "job dibuat", title=title)

    # --- loop -----------------------------------------------------------
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - thread tidak boleh mati
                log.exception("scheduler tick crashed")
            self._stop.wait(self.tick_seconds)


def status_payload(scheduler: Scheduler | None, schedule: ScheduleOverride) -> dict[str, object]:
    """Ringkasan untuk dashboard: nyala atau tidak, dan apa yang ditunggu."""
    cfg = _effective(schedule)
    return {
        "enabled": bool(schedule.enabled),
        "running": bool(scheduler and scheduler.running),
        "interval_hours": cfg["interval_hours"],
        "max_per_day": cfg["max_per_day"],
        "gap_minutes": cfg["gap_minutes"],
        "mode": cfg["mode"],
        "stop": cfg["stop"],
        "topics": list(schedule.topics or []),
        "quiet_hours": list(schedule.quiet_hours or []),
        "last_plan": scheduler.last_plan if scheduler else None,
        "last_error": scheduler.last_error if scheduler else None,
        "created": list(scheduler.created[-20:]) if scheduler else [],
    }
