import json


def test_persistent_event_replay_redacts_secrets(tmp_path, monkeypatch):
    from packages.core.observability.store import StudioEventStore
    from packages.core.orchestration import JobStore

    monkeypatch.setenv("STUDIO_TEST_API_KEY", "private-sentinel-not-for-ui")
    jobs = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    first_job = jobs.create(title="First")
    second_job = jobs.create(title="Second")
    events = StudioEventStore(jobs.db_path)
    first = events.emit(job_id=first_job.id, agent_id="ResearchAgent", event_type="stage_started",
                        status="working", description="research private-sentinel-not-for-ui", progress=0)
    second = events.emit(job_id=second_job.id, agent_id="ScriptAgent", event_type="stage_completed",
                         status="completed", description="validated script", progress=100)
    reopened = StudioEventStore(jobs.db_path)
    assert [e.event_id for e in reopened.page(after=first.event_id)] == [second.event_id]
    assert reopened.page(after=0, job_id=first_job.id)[0].job_id == first_job.id
    assert "private-sentinel-not-for-ui" not in json.dumps([e.model_dump(mode="json") for e in reopened.page()])
    assert "[REDACTED]" in reopened.page()[0].description


def test_snapshot_preserves_concurrent_tasks_and_expires_work(tmp_path):
    from packages.core.observability.projection import StudioService
    from packages.core.observability.store import StudioEventStore
    from packages.core.orchestration import JobStore

    jobs = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    first, second = jobs.create(title="First"), jobs.create(title="Second")
    events = StudioEventStore(jobs.db_path)
    run_a, run_b = "a" * 32, "b" * 32
    events.begin_run(first.id, run_a)
    events.begin_run(second.id, run_b)
    a = events.emit(job_id=first.id, agent_id="ResearchAgent", event_type="stage_started",
                    status="working", description="First task", run_id=run_a)
    b = events.emit(job_id=second.id, agent_id="ResearchAgent", event_type="stage_started",
                    status="working", description="Second task", run_id=run_b)
    service = StudioService(jobs)
    snapshot = service.snapshot()
    assert snapshot["cursor"] == b.event_id
    assert len(snapshot["agents"]) == 12
    assert {e["job_id"] for e in snapshot["events"]} == {first.id, second.id}
    own = service.snapshot(job_id=first.id)
    agent = next(v for v in own["agents"] if v["agent_id"] == "ResearchAgent")
    assert agent["event_id"] == a.event_id and agent["status"] == "working"
    events.end_run(first.id, run_a)
    restored = StudioService(JobStore(jobs.db_path, jobs.artifacts_root)).snapshot(job_id=first.id)
    agent = next(v for v in restored["agents"] if v["agent_id"] == "ResearchAgent")
    assert agent["status"] == "waiting" and agent["stale"]
    assert restored["health"]["hermes"] == "not_connected"
    assert all(v["status"] == "idle" for v in restored["agents"] if v["agent_id"] != "ResearchAgent")
