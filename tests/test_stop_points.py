"""Every stop point must leave the same validated draft artifacts behind.

Later stops used to produce *fewer* artifacts than earlier ones: the draft gate
and the thumbnail ran only on the storyboard path, so `stop=assets` returned
`ok=True` with no `draft_qc.json` and no `metadata.json`.
"""
import pytest

from packages.core.config import Settings, get_settings
from packages.core.orchestration import JobState, JobStore
from packages.core.orchestration.states import STOP_POINTS
from packages.core.pipeline import PipelineRunner

DRAFT = ("script.json", "review.json", "storyboard.json", "draft_qc.json", "metadata.json")


class _NullObserver:
    """The thumbnail helper only reports progress; a direct call needs no feed."""

    def stage(self, *args, **kwargs):
        pass

    def done(self, *args, **kwargs):
        pass


def test_stop_points_cover_every_stage_the_merged_pipeline_can_stop_at():
    assert STOP_POINTS["research"] is JobState.TOPIC_SELECTED
    assert STOP_POINTS["storyboard"] is JobState.STORYBOARD_READY
    assert STOP_POINTS["render"] is JobState.TECHNICAL_QC
    assert STOP_POINTS["editorial"] is JobState.EDITORIAL_QC
    assert STOP_POINTS["approval"] is JobState.READY_FOR_APPROVAL
    assert set(STOP_POINTS) == {
        "research", "script", "creative", "storyboard",
        "audio", "render", "editorial", "approval",
    }


def _store(tmp_path) -> JobStore:
    return JobStore(tmp_path / "factory.db", tmp_path / "jobs")


def _run(tmp_path, stop: JobState) -> tuple[JobStore, str]:
    store = _store(tmp_path)
    job = store.create(title=f"stop {stop.value}")
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    report = runner.run(job.id, stop_at=stop)
    assert report.ok, report.as_dict()
    return store, job.id


@pytest.mark.parametrize("stop", [JobState.STORYBOARD_READY, JobState.ASSETS_READY])
def test_draft_stops_write_the_full_draft_artifact_set(tmp_path, stop):
    store, job_id = _run(tmp_path, stop)
    root = store.artifact_root(job_id)
    for name in DRAFT:
        assert (root / name).exists(), f"{name} missing at stop={stop.value}"
    metadata = store.read_artifact(job_id, "metadata.json")
    assert metadata["title"]
    assert len(metadata["script_sha256"]) == 64


def test_storyboard_stop_is_not_missing_the_draft_gate(tmp_path):
    store, job_id = _run(tmp_path, JobState.STORYBOARD_READY)
    qc = store.read_artifact(job_id, "draft_qc.json")
    assert qc["overall"] in {"pass", "warn"}
    assert qc["inputs_sha256"]
    assert not (store.artifact_root(job_id) / "assets.json").exists()


def test_asset_stop_writes_the_thumbnail(tmp_path):
    store, job_id = _run(tmp_path, JobState.ASSETS_READY)
    root = store.artifact_root(job_id)
    assert (root / "assets.json").exists()
    thumbnail = store.read_artifact(job_id, "thumbnail.json")
    assert thumbnail["output_path"] == "thumbnail.png"
    assert (root / thumbnail["output_path"]).is_file()
    assert (root / "metadata.json").exists(), "the thumbnail needs the metadata concept"


def test_draft_gate_reports_its_stage_at_a_draft_stop(tmp_path):
    store, job_id = _run(tmp_path, JobState.STORYBOARD_READY)
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    report = runner.run(job_id, stop_at=JobState.STORYBOARD_READY)
    states = {stage.state for stage in report.stages}
    assert {"DRAFT_QC", "METADATA"} <= states


@pytest.mark.parametrize("stop", [JobState.AUDIO_READY, JobState.TECHNICAL_QC, JobState.EDITORIAL_QC])
def test_later_stops_come_after_the_draft_gate_and_thumbnail(tmp_path, stop):
    """The gate and thumbnail run inside the loop, so every later stop inherits them.

    Audio and render need real TTS/Remotion, so the ordering invariant is asserted
    structurally: the artifact-producing stages precede the requested stop.
    """
    from packages.core.orchestration.states import PIPELINE_ORDER

    runner = PipelineRunner(_store(tmp_path), get_settings(), force_mock=True)
    states = [state for state, _, _ in runner._stages()]
    assert states == sorted(states, key=PIPELINE_ORDER.index)
    assert states.index(JobState.STORYBOARD_READY) < states.index(stop)
    assert states.index(JobState.ASSETS_READY) < states.index(stop)


def test_attempt_cap_blocks_instead_of_retrying_forever(tmp_path, monkeypatch):
    store = _store(tmp_path)
    job = store.create(title="selalu gagal")
    settings = get_settings()
    runner = PipelineRunner(store, settings, force_mock=True)

    def explode(job_id):
        raise ValueError("controlled failure")

    monkeypatch.setattr(runner, "_script", explode)

    for _ in range(settings.max_job_attempts):
        report = runner.run(job.id, stop_at=JobState.SCRIPT_GENERATED)
        assert not report.ok
        assert report.final_state == JobState.FAILED.value

    assert store.get(job.id).attempts == settings.max_job_attempts
    capped = runner.run(job.id, stop_at=JobState.SCRIPT_GENERATED)

    assert not capped.ok
    assert capped.final_state == JobState.BLOCKED.value
    assert "attempt cap" in (capped.blocked_reason or "")
    assert store.get(job.id).state is JobState.BLOCKED
    # A blocked job is not terminal: the operator can raise the cap and resume.
    assert JobState.IDEA_DISCOVERY in __import__(
        "packages.core.orchestration.states", fromlist=["TRANSITIONS"]).TRANSITIONS[JobState.BLOCKED]


def test_blocked_job_resumes_after_the_operator_raises_the_cap(tmp_path, monkeypatch):
    store = _store(tmp_path)
    job = store.create(title="cap lalu lanjut")
    runner = PipelineRunner(store, Settings(max_job_attempts=1), force_mock=True)

    def explode(job_id):
        raise ValueError("controlled failure")

    monkeypatch.setattr(runner, "_script", explode)
    assert not runner.run(job.id, stop_at=JobState.SCRIPT_GENERATED).ok
    blocked = runner.run(job.id, stop_at=JobState.SCRIPT_GENERATED)
    assert blocked.final_state == JobState.BLOCKED.value

    generous = PipelineRunner(store, Settings(max_job_attempts=5), force_mock=True)
    resumed = generous.run(job.id, stop_at=JobState.SCRIPT_GENERATED)

    assert resumed.ok, resumed.as_dict()
    assert store.get(job.id).state is JobState.SCRIPT_GENERATED


def test_audio_ready_rerenders_a_thumbnail_stranded_by_measured_timing(tmp_path):
    """Narration re-times the storyboard, so a still rendered from draft timings is stale.

    Regression: the thumbnail was rendered once at ASSETS_READY and never again,
    so every job that reached the approval gate failed on a stale PNG.
    """
    from packages.core.media.process import json_hash
    from packages.core.pipeline.runner import PipelineReport

    store, job_id = _run(tmp_path, JobState.ASSETS_READY)
    draft_thumb = store.read_artifact(job_id, "thumbnail.json")
    board = store.read_artifact(job_id, "storyboard.json")
    assert draft_thumb["storyboard_sha256"] == json_hash(board)

    # Simulate the measured re-time the AudioAgent performs: same content, new timing.
    cursor = 0
    for scene in board["scenes"]:
        scene["durationInFrames"] = 120
        scene["startFrame"] = cursor
        cursor += scene["durationInFrames"]
    store.write_artifact(job_id, "storyboard.json", board)

    runner = PipelineRunner(store, get_settings(), force_mock=True)
    runner.observer = _NullObserver()
    runner._thumb(job_id, PipelineReport(job_id))

    refreshed = store.read_artifact(job_id, "thumbnail.json")
    assert refreshed["storyboard_sha256"] == json_hash(board)
    assert refreshed["storyboard_sha256"] != draft_thumb["storyboard_sha256"]
