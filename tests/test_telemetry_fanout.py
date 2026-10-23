from packages.core.observability.telemetry import RunTelemetry
from packages.core.orchestration import JobStore
from packages.core.providers.router import UsageTracker


def test_one_stage_boundary_writes_both_readers(tmp_path):
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    job = store.create(title="fanout")
    UsageTracker(store.db_path)
    telemetry = RunTelemetry(store, job.id, source="mock", activity_token="c" * 32)
    telemetry.start()
    telemetry.stage("ScriptAgent", "SCRIPT_GENERATED", reused=False)
    telemetry.done("ScriptAgent", "SCRIPT_GENERATED", "script.json", reused=False)
    telemetry.finish("SCRIPT_GENERATED", "done")

    activity = store.get(job.id).payload["studio_activity"]
    assert activity["agent"] == "ScriptAgent"
    assert activity["completed"]["ScriptAgent"] == "script.json"
    assert activity["phase"] == "done"
    events = telemetry.events.events.page(job_id=job.id)
    assert any(event.agent_id == "ScriptAgent" for event in events)
