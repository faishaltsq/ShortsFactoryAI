"""Scheduler produksi berulang: keputusan murni, tanpa menunggu jam sungguhan."""
from __future__ import annotations

import datetime as dt

import pytest

from packages.core.scheduler import avoid_titles, due_at
from packages.core.studio import ScheduleOverride


def _job(job_id: str, state, title: str = "judul", created: str = "2026-10-22T01:00:00+00:00",
         updated: str | None = None):
    class J:
        id = job_id
        created_at = created

        def __init__(self) -> None:
            self.state = state
            self.title = title
            # Default: job baru saja tersentuh, jadi dianggap masih berjalan
            # bila state-nya non-terminal.
            self.updated_at = updated or created

    return J()


def _at(hour: int, minute: int = 0) -> dt.datetime:
    return dt.datetime(2026, 10, 22, hour, minute, tzinfo=dt.timezone.utc)


def test_mati_secara_default_tidak_membuat_job():
    plan = due_at(ScheduleOverride(), [], now=_at(9))
    assert plan.due is False
    assert "dimatikan" in plan.reason


def test_enabled_tanpa_job_membuat_job():
    plan = due_at(ScheduleOverride(enabled=True), [], now=_at(9))
    assert plan.due is True


def test_job_yang_masih_berjalan_menahan_job_baru():
    from packages.core.orchestration.states import JobState

    # Baru dibuat: benar-benar sedang jalan, bukan terbengkalai.
    jobs = [_job("a" * 16, JobState.RENDERING, created="2026-10-22T09:55:00+00:00")]
    plan = due_at(ScheduleOverride(enabled=True, max_per_day=5), jobs, now=_at(10))
    assert plan.due is False
    assert "masih berjalan" in plan.reason


def test_batas_harian_dihormati():
    from packages.core.orchestration.states import JobState

    jobs = [
        _job("a" * 16, JobState.TECHNICAL_QC, created="2026-10-22T01:00:00+00:00"),
        _job("b" * 16, JobState.TECHNICAL_QC, created="2026-10-22T05:00:00+00:00"),
    ]
    plan = due_at(ScheduleOverride(enabled=True, max_per_day=2, interval_hours=1), jobs, now=_at(12))
    assert plan.due is False
    assert "batas harian" in plan.reason


def test_interval_belum_lewat_menahan_job():
    from packages.core.orchestration.states import JobState

    # Job terakhir 08:00 UTC, sekarang 09:00, interval 24 jam.
    jobs = [_job("a" * 16, JobState.TECHNICAL_QC, created="2026-10-22T08:00:00+00:00")]
    plan = due_at(ScheduleOverride(enabled=True, interval_hours=24, max_per_day=3), jobs, now=_at(9))
    assert plan.due is False
    assert "jeda belum lewat" in plan.reason


def test_interval_lewat_membuat_job():
    from packages.core.orchestration.states import JobState

    # Job kemarin, sekarang sudah 24 jam lebih.
    jobs = [_job("a" * 16, JobState.TECHNICAL_QC, created="2026-10-21T06:00:00+00:00")]
    plan = due_at(ScheduleOverride(enabled=True, interval_hours=24, max_per_day=1), jobs, now=_at(9))
    assert plan.due is True


def test_jam_sepi_dilewati():
    plan = due_at(ScheduleOverride(enabled=True, quiet_hours=[0, 1, 2, 3]), [], now=_at(2))
    assert plan.due is False
    assert "jam sepi" in plan.reason


def test_topik_diputar_dan_yang_sudah_dipakai_dilewati():
    from packages.core.orchestration.states import JobState

    # Job kemarin: lolos interval 24 jam, tapi judulnya tetap harus dihindari.
    schedule = ScheduleOverride(enabled=True, max_per_day=5, topics=["Lubang hitam", "Sinyal alien"])
    jobs = [_job("a" * 16, JobState.TECHNICAL_QC, title="Lubang hitam", created="2026-10-21T06:00:00+00:00")]
    plan = due_at(schedule, jobs, now=_at(9))
    assert plan.due is True
    assert plan.title == "Sinyal alien"


def test_semua_topik_terpakai_tidak_mengulang_judul():
    from packages.core.orchestration.states import JobState

    schedule = ScheduleOverride(enabled=True, max_per_day=5, topics=["Lubang hitam"])
    jobs = [_job("a" * 16, JobState.TECHNICAL_QC, title="Lubang hitam", created="2026-10-21T06:00:00+00:00")]
    plan = due_at(schedule, jobs, now=_at(9))
    # Tetap membuat job, tapi tanpa memaksa judul yang sudah dipakai.
    assert plan.due is True
    assert plan.title is None


def test_avoid_titles_terbaru_dulu_dan_unik():
    from packages.core.orchestration.states import JobState

    jobs = [
        _job("a" * 16, JobState.TECHNICAL_QC, title="lama", created="2026-10-20T01:00:00+00:00"),
        _job("b" * 16, JobState.TECHNICAL_QC, title="baru", created="2026-10-22T01:00:00+00:00"),
    ]
    assert avoid_titles(jobs) == ["baru", "lama"]


def test_quiet_hours_ditolak_di_luar_0_23():
    with pytest.raises(ValueError):
        ScheduleOverride(quiet_hours=[24])


def test_stop_tidak_dikenal_ditolak():
    with pytest.raises(ValueError):
        ScheduleOverride(stop="ngawur")


def test_interval_menang_atas_gap_yang_lebih_longgar():
    """Dua setelan jeda tidak boleh saling membatalkan; yang ketat menang."""
    from packages.core.orchestration.states import JobState

    # Job 2 jam lalu. gap_minutes=5 sendirian akan mengizinkan, tapi
    # interval_hours=6 belum lewat.
    jobs = [_job("a" * 16, JobState.TECHNICAL_QC, created="2026-10-22T07:00:00+00:00")]
    plan = due_at(
        ScheduleOverride(enabled=True, interval_hours=6, gap_minutes=5, max_per_day=5),
        jobs,
        now=_at(9),
    )
    assert plan.due is False
    assert "jeda belum lewat" in plan.reason


def test_gap_menang_bila_lebih_ketat_dari_interval():
    from packages.core.orchestration.states import JobState

    # Interval 1 jam tapi gap 120 menit: gap yang menahan.
    jobs = [_job("a" * 16, JobState.TECHNICAL_QC, created="2026-10-22T07:30:00+00:00")]
    plan = due_at(
        ScheduleOverride(enabled=True, interval_hours=1, gap_minutes=120, max_per_day=5),
        jobs,
        now=_at(9),
    )
    assert plan.due is False
    assert "jeda belum lewat" in plan.reason


def test_job_terbengkalai_tidak_memblokir_selamanya():
    """Satu job yang ditinggal di tengah jalan tidak boleh membekukan scheduler."""
    from packages.core.orchestration.states import JobState

    # Non-terminal, tapi terakhir tersentuh 10 jam lalu (> STALE_HOURS).
    stale = _job(
        "a" * 16,
        JobState.SCRIPT_GENERATED,
        created="2026-10-21T20:00:00+00:00",
        updated="2026-10-21T23:00:00+00:00",
    )
    plan = due_at(
        ScheduleOverride(enabled=True, max_per_day=5, interval_hours=1),
        [stale],
        now=_at(9),
    )
    assert plan.due is True


def test_job_yang_baru_disentuh_tetap_menahan():
    from packages.core.orchestration.states import JobState

    # Non-terminal dan baru diperbarui 1 menit lalu: benar-benar masih jalan.
    fresh = _job(
        "a" * 16,
        JobState.RENDERING,
        created="2026-10-22T08:59:00+00:00",
        updated="2026-10-22T08:59:00+00:00",
    )
    plan = due_at(
        ScheduleOverride(enabled=True, max_per_day=5, interval_hours=1),
        [fresh],
        now=_at(9),
    )
    assert plan.due is False
    assert "masih berjalan" in plan.reason


def test_active_ids_menentukan_bukan_timestamp():
    """Job yatim bertimestamp baru tetap tidak menghalangi scheduler.

    Kasus nyata: job ditinggal di SCRIPT_GENERATED dengan updated_at 2 jam lalu.
    Tanpa daftar run aktif, scheduler menunggu 6 jam penuh tanpa alasan.
    """
    from packages.core.orchestration.states import JobState

    orphan = _job(
        "a" * 16,
        JobState.SCRIPT_GENERATED,
        created="2026-10-22T08:42:00+00:00",
        updated="2026-10-22T08:43:00+00:00",
    )
    schedule = ScheduleOverride(enabled=True, max_per_day=5, interval_hours=1)

    # Tidak ada run aktif -> boleh membuat job baru.
    plan = due_at(schedule, [orphan], now=_at(10, 50), active_ids=set())
    assert plan.due is True

    # Ada run aktif untuk job itu -> tahan.
    plan = due_at(schedule, [orphan], now=_at(10, 50), active_ids={"a" * 16})
    assert plan.due is False
    assert "masih berjalan" in plan.reason
