from packages.core.orchestration import JobState, JobStore
from packages.core.pipeline import PipelineRunner


def test_running_agent_is_recorded_before_work_and_completion_is_validated(tmp_path, monkeypatch):
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    job = store.create(title="observable")
    runner = PipelineRunner(store, force_mock=True)
    original = runner._script

    def script(job_id):
        value = store.get(job_id).payload["studio_activity"]
        assert value["agent"] == "ScriptAgent"
        assert value["phase"] == "running"
        assert "ScriptAgent" not in value["completed"]
        original(job_id)

    monkeypatch.setattr(runner, "_script", script)
    result = runner.run(job.id, activity_token="c" * 32)
    assert result.ok, result.as_dict()
    value = store.get(job.id).payload["studio_activity"]
    assert value["phase"] == "done"
    assert value["token"] == "c" * 32
    assert value["completed"]["QualityAgent"] == "draft_qc.json"
    assert value["completed"]["MetadataAgent"] == "metadata.json"
    assert "PublishAgent" not in value["completed"]


def test_failure_does_not_mark_the_failing_agent_complete(tmp_path, monkeypatch):
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    job = store.create(title="failure")
    runner = PipelineRunner(store, force_mock=True)

    def fail(job_id):
        raise ValueError("controlled test failure")

    monkeypatch.setattr(runner, "_script", fail)
    assert not runner.run(job.id).ok
    value = store.get(job.id).payload["studio_activity"]
    assert value["phase"] == "failed"
    assert value["agent"] == "ScriptAgent"
    assert "ScriptAgent" not in value["completed"]
    assert store.try_lock(job.id)
    store.unlock(job.id)


def test_cancel_and_resume_report_stopped_and_validating(tmp_path, monkeypatch):
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    job = store.create(title="resume")
    runner = PipelineRunner(store, force_mock=True)
    runner.run(job.id, cancelled=lambda: True)
    assert store.get(job.id).payload["studio_activity"]["phase"] == "stopped"
    assert runner.run(job.id, stop_at=JobState.SCRIPT_GENERATED).ok
    original = runner._read

    def read(job_id, name):
        if name == "research.json":
            assert store.get(job_id).payload["studio_activity"]["phase"] == "validating"
        return original(job_id, name)

    monkeypatch.setattr(runner, "_read", read)
    assert runner.run(job.id, stop_at=JobState.SCRIPT_GENERATED).ok
