import pytest

from packages.core.orchestration import JobStore


def test_set_activity_persists_without_touching_state_or_events(tmp_path):
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    job = store.create(title="aktivitas")
    before = store.get(job.id)
    events_before = store.events(job.id)
    store.set_activity(job.id, {
        "token": "a" * 32, "agent": "ScriptAgent", "stage": "SCRIPT_GENERATED",
        "phase": "running", "updated_at": "2026-10-22T00:00:00+00:00", "completed": {},
    })
    after = store.get(job.id)
    assert after.state is before.state
    assert after.updated_at == before.updated_at
    assert after.payload["studio_activity"]["agent"] == "ScriptAgent"
    # apex's create() already logs the creation transition; activity must add none.
    assert store.events(job.id) == events_before


def test_set_activity_rejects_a_bad_token_before_writing(tmp_path):
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    job = store.create(title="aktivitas")
    with pytest.raises(ValueError):
        store.set_activity(job.id, {"token": "short", "updated_at": "x", "completed": {}})
    assert "studio_activity" not in store.get(job.id).payload