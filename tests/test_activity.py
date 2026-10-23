import json

import pytest
from pydantic import ValidationError

from packages.core.activity import ActivityReporter
from packages.core.orchestration import JobStore


def test_activity_roundtrip_does_not_advance_job_or_append_events(tmp_path):
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    job = store.create(title="activity")
    before = store.events(job.id)
    tracker = ActivityReporter(store, job.id, "a" * 32)
    tracker.begin("ScriptAgent", "SCRIPT_GENERATED", reused=True)
    fresh = JobStore(store.db_path, store.artifacts_root).get(job.id)
    assert fresh.state == job.state
    assert fresh.payload["studio_activity"]["phase"] == "validating"
    assert store.events(job.id) == before
    tracker.complete("ScriptAgent", "script.json")
    tracker.finish("done")
    saved = store.get(job.id).payload["studio_activity"]
    assert saved["completed"] == {"ScriptAgent": "script.json"}
    assert saved["phase"] == "done"
    snapshot = json.loads((store.artifact_root(job.id) / "job.json").read_text())
    assert snapshot["payload"]["studio_activity"] == saved


def test_activity_rejects_unknown_agent_and_phase_without_writing(tmp_path):
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    job = store.create(title="validation")
    tracker = ActivityReporter(store, job.id, "b" * 32)
    with pytest.raises(ValidationError):
        tracker.begin("UnknownAgent", "unknown")
    assert "studio_activity" not in store.get(job.id).payload
    with pytest.raises(ValidationError):
        store.set_activity(job.id, {"token": "b" * 32, "phase": "invented"})
    assert "studio_activity" not in store.get(job.id).payload
