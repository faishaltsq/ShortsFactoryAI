import pytest

from packages.core.config import get_settings
from packages.core.orchestration import JobState, JobStore
from packages.core.pipeline import PipelineRunner
from packages.core.providers import MockProvider, ProviderError, ProviderRouter
from packages.core.providers.router import UsageTracker


def test_explicit_no_mock_skips_fixture_in_chain():
    router = ProviderRouter(worker_chain=[MockProvider()])
    with pytest.raises(ProviderError):
        router.call(agent="ResearchAgent", tier="worker", task="research", system="s", user="u", allow_mock=False)


def test_transition_does_not_release_running_job_lock(tmp_path):
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    job = store.create(title="locked")
    assert store.try_lock(job.id)
    store.transition(job.id, JobState.TOPIC_SELECTED)
    assert not store.try_lock(job.id), "stage transition must not release the pipeline lock"
    store.unlock(job.id)
    assert store.try_lock(job.id)


def test_same_transition_is_idempotent(tmp_path):
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    job = store.create(title="idempotent")
    store.transition(job.id, JobState.TOPIC_SELECTED)
    store.transition(job.id, JobState.TOPIC_SELECTED)
    assert len(store.events(job.id)) == 2


def test_runner_tracks_usage_in_job_database(tmp_path):
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    assert runner.router.tracker.db_path == store.db_path


def test_invalid_artifact_is_not_written(tmp_path):
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    job = store.create(title="invalid")
    with pytest.raises(ValueError):
        store.write_artifact(job.id, "script.json", {"title": "incomplete"})
    assert not (store.artifact_root(job.id) / "script.json").exists()


def test_artifact_path_cannot_escape_job_directory(tmp_path):
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    job = store.create(title="path")
    with pytest.raises(ValueError):
        store.write_artifact(job.id, "../outside.json", {})


def test_unknown_stop_is_rejected_before_stages_run(tmp_path):
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    job = store.create(title="stop")
    with pytest.raises(ValueError, match="stop"):
        runner.run(job.id, stop_at=JobState.PUBLISHED)
    assert len(store.events(job.id)) == 1


def test_corrupted_completed_stage_is_not_reused(tmp_path):
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    job = store.create(title="corrupt")
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    assert runner.run(job.id).ok
    (store.artifact_root(job.id) / "script.json").write_text("{}", encoding="utf-8")
    report = runner.run(job.id)
    assert not report.ok
    assert report.final_state == "FAILED"


def test_job_snapshot_tracks_persisted_state(tmp_path):
    import json
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    job = store.create(title="snapshot")
    store.transition(job.id, JobState.TOPIC_SELECTED)
    data = json.loads((store.artifact_root(job.id) / "job.json").read_text(encoding="utf-8"))
    assert data["id"] == job.id
    assert data["state"] == "TOPIC_SELECTED"


def test_mock_accounting_never_reports_billed_cost(tmp_path):
    tracker = UsageTracker(tmp_path / "usage.db")
    result = MockProvider().complete(task="script", system="s", user="u")
    assert tracker.record(job_id="test", agent="ScriptAgent", result=result, tier="worker") == 0
    assert tracker.daily_totals()["cost"] == 0
