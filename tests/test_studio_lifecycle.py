from packages.core.config import get_settings
from packages.core.orchestration import JobState, JobStore
from packages.core.pipeline import PipelineRunner


def test_real_mock_worker_emits_lifecycle_without_fake_resume_work(tmp_path):
    from packages.core.observability.store import StudioEventStore

    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    job = store.create(title="Explicitly labelled mock content")
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    assert runner.run(job.id).ok
    events = StudioEventStore(store.db_path).page(limit=500)
    for agent in ("ResearchAgent", "ScriptAgent", "StoryboardAgent", "QualityAgent", "MetadataAgent"):
        own = [e for e in events if e.agent_id == agent]
        assert [e.status for e in own] == ["working", "completed"]
        assert all(e.source == "mock" for e in own)
    cursor = events[-1].event_id
    assert runner.run(job.id).ok
    resumed = StudioEventStore(store.db_path).page(after=cursor, limit=500)
    assert all(e.status != "working" for e in resumed if e.agent_id != "FactoryOrchestrator")
    assert {e.agent_id for e in resumed if e.event_type == "artifact_reused"} >= {"ResearchAgent", "ScriptAgent"}
    assert store.get(job.id).state == JobState.STORYBOARD_READY
