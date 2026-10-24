import importlib.util
from datetime import datetime, timedelta, timezone

from packages.core.orchestration.jobstore import JobStore


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 21, 3, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


def test_seven_day_plan_persists_rotation_jobs_and_idempotency(tmp_path):
    assert importlib.util.find_spec("packages.core.orchestration.planner"), "persisted planner is missing"
    from packages.core.orchestration.planner import ProductionPlanner

    clock = Clock()
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs", clock=clock)
    start = clock().astimezone(timezone(timedelta(hours=7)))
    planner = ProductionPlanner(store)
    plan = planner.plan_seven_days(start=start, videos_per_day=2, genres=["science", "history", "fiction"],
                                  provider_mode="mock")
    assert len(plan.slots) == 14
    assert [slot.genre for slot in plan.slots] == ["science", "history", "fiction"] * 4 + ["science", "history"]
    assert len({slot.job_id for slot in plan.slots}) == 14
    assert len({slot.due_at for slot in plan.slots}) == 14
    assert all(slot.status == "PENDING" and slot.attempts == 0 for slot in plan.slots)
    assert datetime.fromisoformat(plan.slots[0].due_at) == start
    for slot in plan.slots:
        job = store.get(slot.job_id)
        assert job.payload["provider_mode"] == "mock"
        assert job.payload["genre"] == slot.genre
        assert job.payload["plan_slot_id"] == slot.id
        assert len(store.events(job.id)) == 1
        assert (store.artifact_root(job.id) / "job.json").is_file()
    reopened = JobStore(store.db_path, store.artifacts_root, clock=clock)
    restored = ProductionPlanner(reopened).plan_seven_days(start=start, videos_per_day=2,
                                                          genres=["science", "history", "fiction"],
                                                          provider_mode="mock", retry_base_s=60.0)
    assert restored == plan
    assert len(reopened.list()) == 14


def test_plan_validates_inputs_before_writing_jobs(tmp_path):
    import pytest
    from packages.core.orchestration.planner import ProductionPlanner
    from packages.core.schemas import Genre

    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    planner = ProductionPlanner(store)
    options = {"start": Clock()(), "videos_per_day": 1, "genres": ["science"]}
    for invalid in ({"start": datetime(2026, 10, 21)}, {"videos_per_day": 0},
                    {"videos_per_day": True}, {"videos_per_day": 1001}, {"genres": []},
                    {"genres": ["unknown"]}, {"provider_mode": "automatic"}):
        with pytest.raises(ValueError):
            planner.plan_seven_days(**(options | invalid))
        assert not store.list()
    plan = planner.plan_seven_days(**(options | {"genres": [Genre.science]}))
    assert all(slot.genre == "science" for slot in plan.slots)


def test_plan_recovers_committed_jobs_after_snapshot_interruption(tmp_path, monkeypatch):
    import pytest
    from packages.core.orchestration.planner import ProductionPlanner

    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    options = {"start": Clock()(), "videos_per_day": 1, "genres": ["history"]}
    planner = ProductionPlanner(store)

    def interrupted(_job_id):
        raise OSError("interrupted snapshot")

    monkeypatch.setattr(store, "snapshot", interrupted)
    with pytest.raises(OSError):
        planner.plan_seven_days(**options)
    assert len(store.list()) == 7
    restored_store = JobStore(store.db_path, store.artifacts_root)
    restored = ProductionPlanner(restored_store).plan_seven_days(**options)
    assert len(restored.slots) == len(restored_store.list()) == 7
    assert all((restored_store.artifact_root(slot.job_id) / "job.json").is_file() for slot in restored.slots)


def test_mid_plan_database_failure_rolls_back_jobs_and_slots(tmp_path):
    import sqlite3
    import pytest
    from packages.core.orchestration.planner import ProductionPlanner

    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    planner = ProductionPlanner(store)
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("CREATE TRIGGER interrupt_plan BEFORE INSERT ON production_slots "
                     "WHEN NEW.day_index=2 BEGIN SELECT RAISE(ABORT, 'interrupted'); END")
    with pytest.raises(sqlite3.IntegrityError, match="interrupted"):
        planner.plan_seven_days(start=Clock()(), videos_per_day=1, genres=["science"])
    assert not store.list()
    with sqlite3.connect(store.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM production_plans").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM production_slots").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM job_events").fetchone()[0] == 0


def test_scheduler_disabled_by_default_and_operator_gate_persisted(tmp_path):
    import pytest
    assert importlib.util.find_spec("packages.core.orchestration.scheduler"), "scheduler is missing"
    from packages.core.orchestration.scheduler import Scheduler

    clock = Clock()
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs", clock=clock)
    calls = []
    scheduler = Scheduler(store, runner=lambda *a, **k: calls.append(a))
    assert scheduler.status()["enabled"] is False
    assert scheduler.tick().dispatched == 0
    assert calls == []
    with pytest.raises(PermissionError):
        scheduler.enable()
    assert scheduler.status()["enabled"] is False
    scheduler.enable(operator_confirmed=True)
    reopened = Scheduler(JobStore(store.db_path, store.artifacts_root, clock=clock))
    assert reopened.status()["enabled"] is True
    reopened.pause()
    assert scheduler.status()["enabled"] is False
    assert scheduler.tick().dispatched == 0
    assert calls == []
    assert [event["kind"] for event in scheduler.events()] == ["operator_enabled", "operator_paused"]


def test_tick_dispatches_only_due_jobs_once_and_keeps_provider_mode(tmp_path):
    from packages.core.orchestration.planner import ProductionPlanner
    from packages.core.orchestration import scheduler as module
    assert hasattr(module, "DispatchResult"), "runner result contract is missing"

    clock = Clock()
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs", clock=clock)
    plan = ProductionPlanner(store).plan_seven_days(start=clock(), videos_per_day=1,
                                                   genres=["science"], provider_mode="live")
    calls = []

    def run(job_id, *, provider_mode):
        calls.append((job_id, provider_mode))
        return module.DispatchResult(success=True)

    scheduler = module.Scheduler(store, runner=run)
    assert scheduler.tick().dispatched == 0
    assert calls == []
    scheduler.enable(operator_confirmed=True)
    report = scheduler.tick(limit=10)
    assert report.dispatched == report.completed == 1
    assert calls == [(plan.slots[0].job_id, "live")]
    assert scheduler.planner.get(plan.id).slots[0].status == "COMPLETE"
    assert scheduler.tick().dispatched == 0
    clock.advance(86400)
    assert scheduler.tick().completed == 1
    assert calls[-1] == (plan.slots[1].job_id, "live")
    assert [event["kind"] for event in scheduler.events()] == [
        "operator_enabled", "dispatch_started", "dispatch_complete", "dispatch_started", "dispatch_complete"]


def test_transient_failure_backoff_and_hard_attempt_cap_survive_reboot(tmp_path):
    from packages.core.orchestration.planner import ProductionPlanner
    from packages.core.orchestration.scheduler import Scheduler

    clock = Clock()
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs", clock=clock)
    plan = ProductionPlanner(store).plan_seven_days(start=clock(), videos_per_day=1,
                                                   genres=["science"], max_attempts=3, retry_base_s=10)
    calls = []

    def unavailable(job_id, *, provider_mode):
        calls.append(job_id)
        raise RuntimeError("temporary provider problem with secret-value-not-for-db")

    scheduler = Scheduler(store, runner=unavailable)
    scheduler.enable(operator_confirmed=True)
    assert scheduler.tick().retried == 1
    assert scheduler.planner.get(plan.id).slots[0].status == "RETRY"
    clock.advance(9)
    assert scheduler.tick().dispatched == 0
    clock.advance(1)
    scheduler = Scheduler(JobStore(store.db_path, store.artifacts_root, clock=clock), runner=unavailable)
    assert scheduler.tick().retried == 1
    clock.advance(19)
    assert scheduler.tick().dispatched == 0
    clock.advance(1)
    assert scheduler.tick().failed == 1
    slot = scheduler.planner.get(plan.id).slots[0]
    assert slot.status == "FAILED" and slot.attempts == 3
    clock.advance(1000)
    assert scheduler.tick(limit=10).dispatched == 0
    assert calls == [slot.job_id] * 3
    assert b"secret-value-not-for-db" not in store.db_path.read_bytes()


def test_interrupted_dispatch_recovers_after_expiry_without_creating_jobs(tmp_path):
    import pytest
    from packages.core.orchestration.planner import ProductionPlanner
    from packages.core.orchestration.scheduler import DispatchResult, Scheduler

    clock = Clock()
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs", clock=clock)
    plan = ProductionPlanner(store).plan_seven_days(start=clock(), videos_per_day=1,
                                                   genres=["history"], retry_base_s=10)

    def interrupted(job_id, *, provider_mode):
        assert store.acquire_lease(job_id, ttl_s=60)
        raise KeyboardInterrupt("simulated reboot")

    scheduler = Scheduler(store, runner=interrupted)
    scheduler.enable(operator_confirmed=True)
    with pytest.raises(KeyboardInterrupt):
        scheduler.tick()
    assert scheduler.planner.get(plan.id).slots[0].status == "DISPATCHED"
    clock.advance(119)
    calls = []

    def resume(job_id, *, provider_mode):
        calls.append(job_id)
        token = restored.store.acquire_lease(job_id)
        assert token
        restored.store.release_lease(job_id, token)
        return DispatchResult(True)

    restored = Scheduler(JobStore(store.db_path, store.artifacts_root, clock=clock), runner=resume)
    assert restored.tick().dispatched == 0
    clock.advance(1)
    report = restored.tick()
    assert report.recovered == report.retried == 1
    assert report.dispatched == 0
    clock.advance(10)
    assert restored.tick().completed == 1
    slot = restored.planner.get(plan.id).slots[0]
    assert slot.attempts == 2 and slot.status == "COMPLETE"
    assert calls == [plan.slots[0].job_id]
    assert len(restored.store.list()) == 7


def test_expired_dispatch_does_not_steal_a_live_pipeline_lease(tmp_path):
    import pytest
    from packages.core.orchestration.planner import ProductionPlanner
    from packages.core.orchestration.scheduler import DispatchResult, Scheduler

    clock = Clock()
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs", clock=clock)
    plan = ProductionPlanner(store).plan_seven_days(start=clock(), videos_per_day=1, genres=["science"])
    tokens = []

    def running(job_id, *, provider_mode):
        tokens.append(store.acquire_lease(job_id, ttl_s=600))
        raise SystemExit("interruption")

    first = Scheduler(store, runner=running)
    first.enable(operator_confirmed=True)
    with pytest.raises(SystemExit):
        first.tick()
    clock.advance(120)
    calls = []
    second = Scheduler(JobStore(store.db_path, store.artifacts_root, clock=clock),
                       runner=lambda *a, **k: calls.append(a) or DispatchResult(True))
    report = second.tick()
    assert report.recovered == report.dispatched == 0
    assert calls == []
    assert store.renew_lease(plan.slots[0].job_id, tokens[0], ttl_s=600)
    assert second.planner.get(plan.id).slots[0].status == "DISPATCHED"
    store.release_lease(plan.slots[0].job_id, tokens[0])
    assert second.tick().recovered == 1


def test_completed_pipeline_after_crash_is_not_run_again(tmp_path):
    import sqlite3
    import pytest
    from packages.core.orchestration.planner import ProductionPlanner
    from packages.core.orchestration.scheduler import DispatchResult, Scheduler

    clock = Clock()
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs", clock=clock)
    plan = ProductionPlanner(store).plan_seven_days(start=clock(), videos_per_day=1, genres=["science"])

    def completed_before_crash(job_id, *, provider_mode):
        with sqlite3.connect(store.db_path) as conn:
            conn.execute("UPDATE jobs SET state='READY_FOR_APPROVAL' WHERE id=?", (job_id,))
        raise KeyboardInterrupt("before scheduler acknowledgement")

    first = Scheduler(store, runner=completed_before_crash)
    first.enable(operator_confirmed=True)
    with pytest.raises(KeyboardInterrupt):
        first.tick()
    clock.advance(120)
    calls = []
    restored = Scheduler(JobStore(store.db_path, store.artifacts_root, clock=clock),
                         runner=lambda *a, **k: calls.append(a) or DispatchResult(True))
    report = restored.tick()
    assert report.recovered == report.completed == 1
    assert report.dispatched == 0 and calls == []
    slot = restored.planner.get(plan.id).slots[0]
    assert slot.status == "COMPLETE" and slot.attempts == 1


def test_operator_cancelled_job_never_reaches_runner(tmp_path):
    from packages.core.orchestration.planner import ProductionPlanner
    from packages.core.orchestration.scheduler import DispatchResult, Scheduler
    from packages.core.orchestration.states import JobState

    clock = Clock()
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs", clock=clock)
    plan = ProductionPlanner(store).plan_seven_days(start=clock(), videos_per_day=1, genres=["science"])
    store.transition(plan.slots[0].job_id, JobState.CANCELLED)
    calls = []
    scheduler = Scheduler(store, runner=lambda *a, **k: calls.append(a) or DispatchResult(True))
    scheduler.enable(operator_confirmed=True)
    assert scheduler.tick().failed == 1
    assert calls == []
    slot = scheduler.planner.get(plan.id).slots[0]
    assert slot.status == "FAILED" and slot.attempts == 0


def test_cli_help_and_readonly_status_work_offline_without_creating_db(tmp_path):
    import json
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "scripts" / "schedule.py"
    assert script.is_file(), "operator schedule CLI is missing"
    db = tmp_path / "not-created" / "factory.db"
    help_result = subprocess.run([sys.executable, str(script), "--help"], capture_output=True,
                                 text=True, timeout=15)
    assert help_result.returncode == 0, help_result.stderr
    assert "enable" in help_result.stdout and "pause" in help_result.stdout
    result = subprocess.run([sys.executable, str(script), "--db", str(db), "status"],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["enabled"] is False
    assert not db.parent.exists()


def test_cli_plan_enable_pause_roundtrip_and_disabled_tick_has_no_runner(tmp_path, monkeypatch, capsys):
    import json
    from scripts import schedule

    db, jobs = tmp_path / "factory.db", tmp_path / "jobs"
    prefix = ["--db", str(db), "--artifacts", str(jobs)]
    calls = []

    def forbidden(*a, **k):
        calls.append(a)
        raise AssertionError("provider runner must remain offline")

    monkeypatch.setattr(schedule, "_run_pipeline", forbidden)
    assert schedule.main(prefix + ["tick"]) == 2
    assert not db.exists()
    assert schedule.main(prefix + ["plan", "--start", "2026-10-21T10:00:00+07:00", "--videos-per-day", "2",
                                  "--genres", "science,history"]) == 0
    capsys.readouterr()
    assert schedule.main(prefix + ["status"]) == 0
    assert json.loads(capsys.readouterr().out)["slots"]["PENDING"] == 14
    assert schedule.main(prefix + ["enable"]) == 2
    capsys.readouterr()
    assert schedule.main(prefix + ["enable", "--confirm-unattended"]) == 0
    capsys.readouterr()
    assert schedule.main(prefix + ["status"]) == 0
    assert json.loads(capsys.readouterr().out)["enabled"] is True
    assert schedule.main(prefix + ["pause"]) == 0
    capsys.readouterr()
    assert schedule.main(prefix + ["tick"]) == 2
    assert calls == []


def test_overlapping_plan_changes_cannot_duplicate_due_slots(tmp_path):
    import pytest
    from packages.core.orchestration.planner import ProductionPlanner

    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    planner = ProductionPlanner(store)
    planner.plan_seven_days(start=Clock()(), videos_per_day=1, genres=["science"])
    with pytest.raises(ValueError, match="overlap"):
        planner.plan_seven_days(start=Clock()(), videos_per_day=1, genres=["history"], provider_mode="live")
    assert len(store.list()) == 7


def test_two_planners_share_slots_and_write_snapshots_without_races(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path
    from threading import Barrier, local
    from packages.core.orchestration.planner import ProductionPlanner

    stores = [JobStore(tmp_path / "factory.db", tmp_path / "jobs") for _ in range(2)]
    planners = [ProductionPlanner(store) for store in stores]
    snapshot_barrier, replace_barrier = Barrier(2), Barrier(2)
    original_replace = Path.replace
    seen = local()

    def concurrent_replace(path, target):
        if not getattr(seen, "replaced", False):
            seen.replaced = True
            replace_barrier.wait(timeout=5)
        return original_replace(path, target)

    for store in stores:
        original = store.snapshot

        def snapshot(job_id, original=original):
            if not getattr(seen, "snapshotted", False):
                seen.snapshotted = True
                snapshot_barrier.wait(timeout=5)
            return original(job_id)

        monkeypatch.setattr(store, "snapshot", snapshot)
    monkeypatch.setattr(Path, "replace", concurrent_replace)

    def plan(planner):
        return planner.plan_seven_days(start=Clock()(), videos_per_day=1, genres=["science"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(plan, planners))
    assert results[0] == results[1]
    assert len(stores[0].list()) == 7
    assert all((stores[0].artifact_root(slot.job_id) / "job.json").is_file() for slot in results[0].slots)


def test_stale_dispatch_completion_cannot_overwrite_new_dispatch(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from packages.core.orchestration.planner import ProductionPlanner
    from packages.core.orchestration.scheduler import DispatchResult, Scheduler

    clock = Clock()
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs", clock=clock)
    plan = ProductionPlanner(store).plan_seven_days(start=clock(), videos_per_day=1, genres=["science"],
                                                   retry_base_s=1)
    entered, finish_old = Event(), Event()

    def delayed(*a, **k):
        entered.set()
        assert finish_old.wait(timeout=5)
        return DispatchResult(False, retryable=False)

    first = Scheduler(store, runner=delayed)
    first.enable(operator_confirmed=True)
    second = Scheduler(JobStore(store.db_path, store.artifacts_root, clock=clock),
                       runner=lambda *a, **k: DispatchResult(True))
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(first.tick)
        try:
            assert entered.wait(timeout=5)
            clock.advance(120)
            assert second.tick().recovered == 1
            clock.advance(1)
            assert second.tick().completed == 1
        finally:
            finish_old.set()
        assert future.result(timeout=5).failed == 0
    slot = second.planner.get(plan.id).slots[0]
    assert slot.status == "COMPLETE" and slot.attempts == 2


def test_interrupted_final_attempt_becomes_terminal_failed(tmp_path):
    import pytest
    from packages.core.orchestration.planner import ProductionPlanner
    from packages.core.orchestration.scheduler import DispatchResult, Scheduler

    clock = Clock()
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs", clock=clock)
    plan = ProductionPlanner(store).plan_seven_days(start=clock(), videos_per_day=1, genres=["history"],
                                                   max_attempts=1)

    def interrupted(*a, **k):
        raise KeyboardInterrupt

    scheduler = Scheduler(store, runner=interrupted)
    scheduler.enable(operator_confirmed=True)
    with pytest.raises(KeyboardInterrupt):
        scheduler.tick()
    clock.advance(120)
    scheduler.runner = lambda *a, **k: DispatchResult(True)
    report = scheduler.tick()
    assert report.recovered == report.failed == 1
    assert report.dispatched == 0
    assert scheduler.planner.get(plan.id).slots[0].status == "FAILED"


def test_cli_enabled_tick_uses_persisted_mode_and_bounded_limit(tmp_path, monkeypatch, capsys):
    import json
    from scripts import schedule
    from packages.core.orchestration.scheduler import DispatchResult

    prefix = ["--db", str(tmp_path / "factory.db"), "--artifacts", str(tmp_path / "jobs")]
    calls = []

    def offline_run(store, job_id, *, provider_mode):
        calls.append((job_id, provider_mode))
        return DispatchResult(True)

    monkeypatch.setattr(schedule, "_run_pipeline", offline_run)
    assert schedule.main(prefix + ["plan", "--start", "2020-01-01T10:00:00+07:00", "--videos-per-day", "1",
                                  "--genres", "history", "--mode", "live"]) == 0
    capsys.readouterr()
    assert schedule.main(prefix + ["enable", "--confirm-unattended"]) == 0
    capsys.readouterr()
    assert schedule.main(prefix + ["tick", "--limit", "1"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["dispatched"] == report["completed"] == 1
    assert len(calls) == 1 and calls[0][1] == "live"


def test_cli_runner_adapter_stops_before_uploads(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from scripts.schedule import _run_pipeline
    import packages.core.pipeline as pipeline
    from packages.core.orchestration.states import JobState

    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    job = store.create(title="adapter contract")
    calls = []

    class OfflineRunner:
        def __init__(self, passed_store, settings, *, force_mock):
            assert passed_store is store and settings.db_path == store.db_path
            calls.append(force_mock)

        def run(self, job_id, *, stop_at):
            assert job_id == job.id and stop_at is JobState.READY_FOR_APPROVAL
            return SimpleNamespace(ok=True, final_state=stop_at.value)

    monkeypatch.setattr(pipeline, "PipelineRunner", OfflineRunner)
    assert _run_pipeline(store, job.id, provider_mode="mock").success
    assert _run_pipeline(store, job.id, provider_mode="live").success
    assert calls == [True, False]


def test_tick_rejects_unbounded_or_nonpositive_limits(tmp_path):
    import pytest
    from packages.core.orchestration.scheduler import Scheduler

    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    scheduler = Scheduler(store, runner=lambda *a, **k: None)
    for limit in (0, -1, True, 1001):
        with pytest.raises(ValueError, match="limit"):
            scheduler.tick(limit=limit)


def test_planner_posting_times_place_slots_on_fixed_local_hours(tmp_path):
    from packages.core.orchestration.planner import ProductionPlanner

    start = datetime(2026, 11, 1, tzinfo=timezone(timedelta(hours=7)))
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    plan = ProductionPlanner(store).plan_seven_days(
        start=start, videos_per_day=3, genres=["science"], days=2,
        posting_times=["07:00", "12:00", "19:00"], provider_mode="mock")
    assert len(plan.slots) == 6
    assert [slot.due_at for slot in plan.slots[:3]] == [
        "2026-11-01T00:00:00+00:00", "2026-11-01T05:00:00+00:00", "2026-11-01T12:00:00+00:00"]
    assert [slot.due_at for slot in plan.slots[3:]] == [
        "2026-11-02T00:00:00+00:00", "2026-11-02T05:00:00+00:00", "2026-11-02T12:00:00+00:00"]
    assert [slot.day_index for slot in plan.slots] == [0, 0, 0, 1, 1, 1]


def test_planner_posting_times_and_days_are_validated_before_writing(tmp_path):
    import pytest
    from packages.core.orchestration.planner import ProductionPlanner

    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    planner = ProductionPlanner(store)
    start = datetime(2026, 11, 1, tzinfo=timezone(timedelta(hours=7)))
    options = {"start": start, "videos_per_day": 2, "genres": ["science"]}
    for invalid, message in (
            ({"posting_times": ["07:00"]}, "posting_times must have one HH:MM entry per daily video"),
            ({"posting_times": ["25:00", "07:00"]}, "posting_times entries must be HH:MM in 24-hour form"),
            ({"posting_times": "07:00"}, "posting_times must have one HH:MM entry per daily video"),
            ({"days": 0}, "days must be an integer from 1 to 30"),
            ({"days": 31}, "days must be an integer from 1 to 30"),
            ({"days": True}, "days must be an integer from 1 to 30")):
        with pytest.raises(ValueError, match=message):
            planner.plan_seven_days(**(options | invalid))
        assert not store.list()


def test_planner_identity_tracks_posting_times_and_stays_stable(tmp_path):
    from packages.core.orchestration.planner import ProductionPlanner

    start = datetime(2026, 11, 1, tzinfo=timezone(timedelta(hours=7)))
    options = {"start": start, "videos_per_day": 2, "genres": ["science"], "days": 2,
               "provider_mode": "mock"}
    first = JobStore(tmp_path / "a" / "factory.db", tmp_path / "a" / "jobs")
    morning = ProductionPlanner(first).plan_seven_days(posting_times=["07:00", "12:00"], **options)
    assert ProductionPlanner(first).plan_seven_days(posting_times=["07:00", "12:00"], **options) == morning
    other = JobStore(tmp_path / "b" / "factory.db", tmp_path / "b" / "jobs")
    evening = ProductionPlanner(other).plan_seven_days(posting_times=["19:00", "21:00"], **options)
    assert evening.id != morning.id
    assert len(evening.slots) == len(morning.slots) == 4


def test_planner_without_posting_times_keeps_the_even_split(tmp_path):
    from packages.core.orchestration.planner import ProductionPlanner

    start = datetime(2026, 11, 1, tzinfo=timezone(timedelta(hours=7)))
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    plan = ProductionPlanner(store).plan_seven_days(
        start=start, videos_per_day=2, genres=["science"], days=1, provider_mode="mock")
    assert [slot.due_at for slot in plan.slots] == [
        "2026-10-31T17:00:00+00:00", "2026-11-01T05:00:00+00:00"]


def _scheduler_jobs(tmp_path, states):
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    for index, state in enumerate(states):
        store.create(title=f"Antrean {index}", state=state)
    return store.list()


def test_schedule_defaults_stop_at_approval_not_render(tmp_path):
    from packages.core.orchestration.states import STOP_POINTS, JobState
    from packages.core.scheduler import _effective, due_at
    from packages.core.studio import ScheduleOverride

    now = datetime(2026, 11, 1, 9, tzinfo=timezone.utc)
    assert due_at(ScheduleOverride(enabled=True), [], now=now).due is True
    config = _effective(ScheduleOverride(enabled=True))
    assert config["stop"] == "approval"
    assert STOP_POINTS[config["stop"]] is JobState.READY_FOR_APPROVAL
    assert config["mode"] == "live"


def test_schedule_pauses_when_review_queue_is_full(tmp_path):
    from packages.core.orchestration.states import JobState
    from packages.core.scheduler import due_at
    from packages.core.studio import ScheduleOverride

    now = datetime(2026, 11, 1, 9, tzinfo=timezone.utc)
    jobs = _scheduler_jobs(tmp_path, [JobState.READY_FOR_APPROVAL] * 3)
    plan = due_at(ScheduleOverride(enabled=True, max_pending_approval=3), jobs, now=now)
    assert plan.due is False
    assert "menunggu review (3/3)" in plan.reason
    relaxed = due_at(ScheduleOverride(enabled=True, max_pending_approval=4), jobs, now=now)
    assert relaxed.due is True
    assert due_at(ScheduleOverride(enabled=True, max_pending_approval=0), jobs, now=now).due is True


def test_schedule_respects_posting_hours(tmp_path):
    from packages.core.scheduler import due_at
    from packages.core.studio import ScheduleOverride

    now = datetime(2026, 11, 1, 9, tzinfo=timezone.utc)
    outside = due_at(ScheduleOverride(enabled=True, posting_hours=[7, 12, 19]), [], now=now)
    assert outside.due is False
    assert "di luar jam tayang" in outside.reason
    inside = due_at(ScheduleOverride(enabled=True, posting_hours=[9]), [], now=now)
    assert inside.due is True
    assert due_at(ScheduleOverride(enabled=True, posting_hours=[]), [], now=now).due is True


def test_schedule_override_rejects_unknown_posting_hours():
    import pytest
    from packages.core.studio import ScheduleOverride

    with pytest.raises(ValueError, match="posting_hours"):
        ScheduleOverride(posting_hours=[24])
    with pytest.raises(ValueError, match="max_pending_approval"):
        ScheduleOverride(max_pending_approval=-1)
    assert ScheduleOverride(posting_hours=[19, 7, 7]).posting_hours == [7, 19]
