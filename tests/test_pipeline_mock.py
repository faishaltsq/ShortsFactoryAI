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


def test_pipeline_keeps_lease_during_a_blocked_stage(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from threading import Event, Lock, Thread

    from packages.core.agents import ResearchAgent
    from packages.core.orchestration.leases import LeaseKeeper

    now = datetime(2026, 10, 21, tzinfo=timezone.utc)
    clock_lock = Lock()

    def clock():
        with clock_lock:
            return now

    def advance(seconds):
        nonlocal now
        with clock_lock:
            now += timedelta(seconds=seconds)

    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs", clock=clock)
    rival = JobStore(store.db_path, store.artifacts_root, clock=clock)
    job = store.create(title="long research")
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    started, release, renewed = Event(), Event(), Event()
    original_research = ResearchAgent.run
    original_renew = store.renew_lease
    original_keeper_init = LeaseKeeper.__init__

    def blocked_research(self, *args, **kwargs):
        started.set()
        if not release.wait(30):
            raise TimeoutError("test stage was not released")
        return original_research(self, *args, **kwargs)

    def fast_keeper(self, *args, **kwargs):
        kwargs["interval_s"] = 0.01
        original_keeper_init(self, *args, **kwargs)

    def tracked_renew(*args, **kwargs):
        started_at = clock()
        result = original_renew(*args, **kwargs)
        if started_at > datetime(2026, 10, 21, tzinfo=timezone.utc) and result:
            renewed.set()
        return result

    monkeypatch.setattr(ResearchAgent, "run", blocked_research)
    monkeypatch.setattr(LeaseKeeper, "__init__", fast_keeper)
    monkeypatch.setattr(store, "renew_lease", tracked_renew)
    reports = []
    thread = Thread(target=lambda: reports.append(runner.run(job.id, stop_at=JobState.STORYBOARD_READY)))
    thread.start()
    try:
        assert started.wait(5)
        advance(1700)
        assert renewed.wait(2), "pipeline has no heartbeat during a long stage"
        renewed.clear()
        advance(200)
        assert renewed.wait(2), "pipeline stopped renewing after the original lease expired"
        assert rival.acquire_lease(job.id) is None, "another worker stole the active pipeline"
    finally:
        release.set()
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert reports[0].ok, reports[0].as_dict()
    assert rival.acquire_lease(job.id) is not None


def test_pipeline_stops_without_failing_job_when_lease_is_stolen(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from packages.core.agents import ResearchAgent

    now = datetime(2026, 10, 21, tzinfo=timezone.utc)
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs", clock=lambda: now)
    rival = JobStore(store.db_path, store.artifacts_root, clock=lambda: now)
    job = store.create(title="expired during research")
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    original_research = ResearchAgent.run
    replacement = []

    def steal_during_stage(self, *args, **kwargs):
        nonlocal now
        now += timedelta(seconds=1800)
        replacement.append(rival.acquire_lease(job.id))
        return original_research(self, *args, **kwargs)

    monkeypatch.setattr(ResearchAgent, "run", steal_during_stage)
    report = runner.run(job.id, stop_at=JobState.STORYBOARD_READY)

    assert replacement[0]
    assert report.ok is False
    assert report.blocked_reason == "job lease ownership lost"
    assert store.get(job.id).state is JobState.IDEA_DISCOVERY
    assert not any(event["to_state"] == "FAILED" for event in store.events(job.id))
    assert rival.release_lease(job.id, replacement[0])


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


def test_draft_cache_binds_review_and_metadata_to_inputs(tmp_path, monkeypatch):
    from packages.core.agents import QualityAgent, MetadataAgent
    from packages.core.media.process import json_hash
    from packages.core.schemas import Script, Storyboard

    store = _store(tmp_path)
    job = store.create(title="dependency-aware review cache")
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    assert runner.run(job.id).ok
    script = Script.model_validate(store.read_artifact(job.id, "script.json"))
    storyboard = Storyboard.model_validate(store.read_artifact(job.id, "storyboard.json"))
    expected = json_hash({"script": script.model_dump(mode="json", exclude_none=True),
                          "storyboard": storyboard.model_dump(mode="json", exclude_none=True)})
    assert store.read_artifact(job.id, "draft_qc.json")["inputs_sha256"] == expected
    assert store.read_artifact(job.id, "metadata.json")["script_sha256"] == json_hash(
        script.model_dump(mode="json", exclude_none=True))
    calls = []
    original_review, original_metadata = QualityAgent.run, MetadataAgent.run

    def reviewed(self, *args):
        calls.append("review")
        return original_review(self, *args)

    def metadata(self, *args):
        calls.append("metadata")
        return original_metadata(self, *args)

    monkeypatch.setattr(QualityAgent, "run", reviewed)
    monkeypatch.setattr(MetadataAgent, "run", metadata)
    assert runner.run(job.id).ok
    assert calls == []
    board = store.read_artifact(job.id, "storyboard.json")
    board["watermark"] = {"text": "Changed fixture label"}
    store.write_artifact(job.id, "storyboard.json", board)
    assert runner.run(job.id).ok
    assert calls == ["review"]
    data = store.read_artifact(job.id, "script.json")
    data["title"] = "Changed fixture title"
    store.write_artifact(job.id, "script.json", data)
    assert runner.run(job.id).ok
    assert calls == ["review", "review", "metadata"]


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
