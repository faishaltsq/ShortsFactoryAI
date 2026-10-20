import json

from packages.core.config import get_settings
from packages.core.orchestration import JobState, JobStore
from packages.core.pipeline import PipelineRunner


def _store(tmp_path):
    return JobStore(tmp_path / "factory.db", tmp_path / "jobs")


def test_full_mock_pipeline(tmp_path):
    settings = get_settings()
    store = _store(tmp_path)
    job = store.create(title="Cahaya matahari")
    runner = PipelineRunner(store, settings, force_mock=True)

    report = runner.run(job.id, stop_at=JobState.STORYBOARD_READY)

    assert report.ok, report.as_dict()
    assert report.final_state == JobState.STORYBOARD_READY.value

    job_dir = store.artifact_root(job.id)
    for name in ("research.json", "topic.json", "script.json", "review.json",
                 "storyboard.json", "draft_qc.json", "metadata.json"):
        assert (job_dir / name).exists(), f"missing artifact {name}"

    storyboard = json.loads((job_dir / "storyboard.json").read_text(encoding="utf-8"))
    assert storyboard["fps"] == 30
    assert (storyboard["width"], storyboard["height"]) == (1080, 1920)
    cursor = 0
    for scene in sorted(storyboard["scenes"], key=lambda s: s["startFrame"]):
        assert scene["startFrame"] == cursor, "scene timing must be contiguous"
        cursor += scene["durationInFrames"]
    duration_s = cursor / storyboard["fps"]
    assert 30 <= duration_s <= 45, f"duration {duration_s}s outside window"

    qc = json.loads((job_dir / "draft_qc.json").read_text(encoding="utf-8"))
    assert qc["overall"] in ("pass", "warn", "fail")

    script = json.loads((job_dir / "script.json").read_text(encoding="utf-8"))
    assert script["segments"][0]["kind"] == "hook"
    assert script["content_type"] == "factual"
    assert script["sources"], "factual script must keep sources"


def test_job_lock_prevents_duplicate_run(tmp_path):
    settings = get_settings()
    store = _store(tmp_path)
    job = store.create(title="dup")
    runner = PipelineRunner(store, settings, force_mock=True)
    assert store.try_lock(job.id) is True
    report = runner.run(job.id, stop_at=JobState.STORYBOARD_READY)
    assert report.ok is False
    assert "lock" in (report.blocked_reason or "")
    store.unlock(job.id)


def test_resume_skips_completed_stages(tmp_path):
    settings = get_settings()
    store = _store(tmp_path)
    job = store.create(title="resume me")
    runner = PipelineRunner(store, settings, force_mock=True)

    first = runner.run(job.id, stop_at=JobState.STORYBOARD_READY)
    assert first.ok, first.as_dict()

    # Simulate a crash at storyboard: artifact gone, job FAILED.
    (store.artifact_root(job.id) / "storyboard.json").unlink()
    store.transition(job.id, JobState.FAILED, error="simulated crash")

    second = runner.run(job.id, stop_at=JobState.STORYBOARD_READY)

    assert second.ok, second.as_dict()
    reused = {s.state for s in second.stages if "reused" in s.detail}
    assert reused == {"IDEA_DISCOVERY", "TOPIC_SELECTED", "SCRIPT_GENERATED", "CREATIVE_REVIEW"}
    assert (store.artifact_root(job.id) / "storyboard.json").exists()
    assert second.final_state == JobState.STORYBOARD_READY.value


def test_live_mode_has_no_mock_in_chain(tmp_path):
    """Fixture content must be unreachable in a live run."""
    settings = get_settings()
    store = _store(tmp_path)
    runner = PipelineRunner(store, settings, force_mock=False)
    names = [p.name for p in runner.router.worker_chain + runner.router.strategist_chain]
    assert "mock" not in names, names
    assert runner.router.allow_mock_default is False


def test_events_are_recorded(tmp_path):
    store = _store(tmp_path)
    job = store.create(title="events")
    store.transition(job.id, JobState.TOPIC_SELECTED, detail="ok")
    events = store.events(job.id)
    assert [e["to_state"] for e in events] == ["IDEA_DISCOVERY", "TOPIC_SELECTED"]
