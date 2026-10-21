from datetime import datetime, timedelta, timezone

from packages.core.orchestration.jobstore import JobStore


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 21, 3, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


def test_owned_lease_excludes_another_store(tmp_path):
    assert hasattr(JobStore, "acquire_lease"), "owned job leases are missing"
    clock = Clock()
    first = JobStore(tmp_path / "factory.db", tmp_path / "jobs", clock=clock)
    second = JobStore(first.db_path, first.artifacts_root, clock=clock)
    job = first.create(title="exclusive")
    token = first.acquire_lease(job.id, ttl_s=60)
    assert isinstance(token, str) and len(token) >= 32
    assert second.acquire_lease(job.id, ttl_s=60) is None
    assert second.release_lease(job.id, "wrong-owner") is False
    assert first.release_lease(job.id, token) is True
    assert second.acquire_lease(job.id, ttl_s=60) not in (None, token)


def test_expired_owner_cannot_renew_or_release_replacement(tmp_path):
    clock = Clock()
    first = JobStore(tmp_path / "factory.db", tmp_path / "jobs", clock=clock)
    second = JobStore(first.db_path, first.artifacts_root, clock=clock)
    job = first.create(title="interrupted")
    old = first.acquire_lease(job.id, ttl_s=60)
    assert hasattr(first, "renew_lease"), "lease heartbeats are missing"
    clock.advance(50)
    assert first.renew_lease(job.id, old, ttl_s=60)
    clock.advance(11)
    assert second.acquire_lease(job.id) is None
    clock.advance(49)
    assert first.renew_lease(job.id, old, ttl_s=60) is False
    replacement = second.acquire_lease(job.id, ttl_s=60)
    assert replacement and replacement != old
    assert first.release_lease(job.id, old) is False
    assert first.renew_lease(job.id, old, ttl_s=60) is False
    assert first.acquire_lease(job.id) is None
    assert second.release_lease(job.id, replacement)


def test_legacy_unlock_never_clears_another_instances_lease(tmp_path):
    clock = Clock()
    first = JobStore(tmp_path / "factory.db", tmp_path / "jobs", clock=clock)
    second = JobStore(first.db_path, first.artifacts_root, clock=clock)
    job = first.create(title="legacy")
    assert first.try_lock(job.id)
    second.unlock(job.id)
    assert second.acquire_lease(job.id) is None
    clock.advance(1800)
    replacement = second.acquire_lease(job.id)
    assert replacement
    first.unlock(job.id)
    assert first.acquire_lease(job.id) is None
    assert second.release_lease(job.id, replacement)
    assert first.try_lock(job.id)
    first.unlock(job.id)
    assert second.try_lock(job.id)


def test_two_stores_racing_have_exactly_one_owner(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    clock = Clock()
    stores = [JobStore(tmp_path / "factory.db", tmp_path / "jobs", clock=clock) for _ in range(2)]
    job = stores[0].create(title="race")
    barrier = Barrier(2)

    def acquire(store):
        barrier.wait(timeout=5)
        return store.acquire_lease(job.id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        tokens = list(pool.map(acquire, stores))
    assert sum(token is not None for token in tokens) == 1


def test_old_locked_database_migrates_without_stealing_live_lock(tmp_path):
    import sqlite3

    clock = Clock()
    db = tmp_path / "factory.db"
    job_id = "a" * 16
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY, title TEXT, state TEXT, attempts INTEGER, "
                     "payload TEXT, last_error TEXT, created_at TEXT, updated_at TEXT, locked_at TEXT)")
        conn.execute("INSERT INTO jobs VALUES (?, ?, ?, 0, ?, NULL, ?, ?, ?)",
                     (job_id, "preserved", "IDEA_DISCOVERY", '{"key":"value"}',
                      clock().isoformat(), clock().isoformat(), clock().isoformat()))
    store = JobStore(db, tmp_path / "jobs", clock=clock)
    assert store.get(job_id).payload == {"key": "value"}
    assert store.acquire_lease(job_id) is None
    clock.advance(1800)
    assert store.acquire_lease(job_id)
    reopened = JobStore(db, store.artifacts_root, clock=clock)
    assert reopened.get(job_id).title == "preserved"
    assert reopened.acquire_lease(job_id) is None


def test_transition_compare_and_set_rejects_stale_operator(tmp_path):
    import pytest
    from packages.core.orchestration.states import JobState

    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    job = store.create(title="compare and set")
    store.transition(job.id, JobState.TOPIC_SELECTED, expected_state=JobState.IDEA_DISCOVERY)
    with pytest.raises(ValueError, match="expected state"):
        store.transition(job.id, JobState.SCRIPT_GENERATED, expected_state=JobState.IDEA_DISCOVERY)
    assert store.get(job.id).state is JobState.TOPIC_SELECTED
    assert len(store.events(job.id)) == 2


def test_keeper_renews_while_stage_is_blocked(tmp_path, monkeypatch):
    import importlib.util
    from threading import Event
    assert importlib.util.find_spec("packages.core.orchestration.leases"), "lease keeper is missing"
    from packages.core.orchestration.leases import LeaseKeeper

    clock = Clock()
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs", clock=clock)
    other = JobStore(store.db_path, store.artifacts_root, clock=clock)
    job = store.create(title="long stage")
    token = store.acquire_lease(job.id, ttl_s=60)
    renewed = Event()
    original = store.renew_lease

    def renew(*args, **kwargs):
        result = original(*args, **kwargs)
        if clock() > datetime(2026, 10, 21, 3, tzinfo=timezone.utc):
            renewed.set()
        return result

    monkeypatch.setattr(store, "renew_lease", renew)
    with LeaseKeeper(store, job.id, token, ttl_s=60, interval_s=0.01) as keeper:
        clock.advance(50)
        assert renewed.wait(timeout=5), "background heartbeat did not run"
        clock.advance(20)
        assert other.acquire_lease(job.id) is None
        keeper.check()
    assert other.acquire_lease(job.id)


def test_keeper_rejects_lost_lease_and_never_releases_replacement(tmp_path):
    import pytest
    from packages.core.orchestration.leases import LeaseKeeper, LeaseLostError

    clock = Clock()
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs", clock=clock)
    other = JobStore(store.db_path, store.artifacts_root, clock=clock)
    job = store.create(title="lost lease")
    token = store.acquire_lease(job.id, ttl_s=60)
    with pytest.raises(LeaseLostError):
        with LeaseKeeper(store, job.id, token, ttl_s=60, interval_s=20) as keeper:
            clock.advance(60)
            replacement = other.acquire_lease(job.id)
            assert replacement
            assert keeper.heartbeat() is False
            keeper.check()
    assert store.acquire_lease(job.id) is None
    assert other.release_lease(job.id, replacement)


def test_renew_checks_utc_clock_after_waiting_for_database(tmp_path, monkeypatch):
    clock = Clock()
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs", clock=clock)
    job = store.create(title="clock after database wait")
    token = store.acquire_lease(job.id, ttl_s=60)
    original = store._connect

    def delayed_connect():
        clock.advance(60)
        return original()

    monkeypatch.setattr(store, "_connect", delayed_connect)
    assert store.renew_lease(job.id, token, ttl_s=60) is False


def test_acquire_ttl_starts_after_waiting_for_database(tmp_path, monkeypatch):
    clock = Clock()
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs", clock=clock)
    other = JobStore(store.db_path, store.artifacts_root, clock=clock)
    job = store.create(title="acquire after database wait")
    original = store._connect

    def delayed_connect():
        clock.advance(60)
        return original()

    monkeypatch.setattr(store, "_connect", delayed_connect)
    assert store.acquire_lease(job.id, ttl_s=60)
    assert other.acquire_lease(job.id) is None


def test_keeper_exit_detects_expiry_without_explicit_check(tmp_path):
    import pytest
    from packages.core.orchestration.leases import LeaseKeeper, LeaseLostError

    clock = Clock()
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs", clock=clock)
    job = store.create(title="expired at exit")
    token = store.acquire_lease(job.id, ttl_s=60)
    with pytest.raises(LeaseLostError):
        with LeaseKeeper(store, job.id, token, ttl_s=60, interval_s=20):
            clock.advance(60)
