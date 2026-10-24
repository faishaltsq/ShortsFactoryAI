"""A cached artifact is only reused while it still matches what it was derived from.

Before this, editing `script.json` left `storyboard.json` marked "reused existing
artifact" and the run reported `ok=True` with the old narration still in the
storyboard; the mismatch surfaced later as "narration no longer matches the script".
"""
import pytest

from packages.core.approval import review_fingerprint
from packages.core.config import get_settings
from packages.core.orchestration import JobState, JobStore
from packages.core.pipeline import PipelineRunner
from packages.core.schemas import Script, Storyboard


def _store(tmp_path) -> JobStore:
    return JobStore(tmp_path / "factory.db", tmp_path / "jobs")


def _edit_segment(store: JobStore, job_id: str) -> str:
    data = store.read_artifact(job_id, "script.json")
    data["segments"][0]["text"] = "Hook yang sudah disunting operator dan jauh lebih panjang."
    store.write_artifact(job_id, "script.json", data)
    return data["segments"][0]["text"]


def test_edited_script_regenerates_the_storyboard_and_downstream_drafts(tmp_path):
    store = _store(tmp_path)
    job = store.create(title="invalidation")
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    assert runner.run(job.id, stop_at=JobState.ASSETS_READY).ok
    root = store.artifact_root(job.id)
    before = {name: (root / name).stat().st_mtime_ns for name in
              ("storyboard.json", "assets.json", "draft_qc.json", "metadata.json")}

    new_text = _edit_segment(store, job.id)
    report = runner.run(job.id, stop_at=JobState.ASSETS_READY)

    assert report.ok, report.as_dict()
    script = Script.model_validate(store.read_artifact(job.id, "script.json"))
    board = Storyboard.model_validate(store.read_artifact(job.id, "storyboard.json"))
    assert script.segments[0].text == new_text
    assert [scene.segment for scene in board.scenes] == [s.text for s in script.segments], \
        "the storyboard must carry the edited narration"
    after = {name: (root / name).stat().st_mtime_ns for name in before}
    assert all(after[name] != before[name] for name in before), \
        "every derived draft artifact must be regenerated"


def test_edited_script_regenerates_the_bound_draft_review(tmp_path):
    store = _store(tmp_path)
    job = store.create(title="review rebind")
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    assert runner.run(job.id, stop_at=JobState.STORYBOARD_READY).ok
    before = store.read_artifact(job.id, "draft_qc.json")["inputs_sha256"]

    _edit_segment(store, job.id)
    assert runner.run(job.id, stop_at=JobState.STORYBOARD_READY).ok

    script = Script.model_validate(store.read_artifact(job.id, "script.json"))
    board = Storyboard.model_validate(store.read_artifact(job.id, "storyboard.json"))
    from packages.core.media.process import json_hash

    expected = review_fingerprint(script.model_dump(mode="json", exclude_none=True),
                                  board.model_dump(mode="json", exclude_none=True))
    assert store.read_artifact(job.id, "draft_qc.json")["inputs_sha256"] == expected
    assert store.read_artifact(job.id, "draft_qc.json")["inputs_sha256"] != before


def test_invalidation_refuses_to_run_when_media_exists(tmp_path):
    store = _store(tmp_path)
    job = store.create(title="media guard")
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    assert runner.run(job.id, stop_at=JobState.ASSETS_READY).ok
    root = store.artifact_root(job.id)
    (root / "render.json").write_text('{"output_path": "output.mp4"}', encoding="utf-8")
    storyboard_before = (root / "storyboard.json").read_bytes()

    with pytest.raises(ValueError, match="repair refused"):
        runner._invalidate_from(job.id)

    assert (root / "storyboard.json").read_bytes() == storyboard_before, \
        "a refused invalidation must delete nothing"


def test_media_guard_stops_the_run_instead_of_orphaning_the_render(tmp_path):
    store = _store(tmp_path)
    job = store.create(title="render guard")
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    assert runner.run(job.id, stop_at=JobState.ASSETS_READY).ok
    root = store.artifact_root(job.id)
    (root / "render.json").write_text('{"output_path": "output.mp4"}', encoding="utf-8")

    _edit_segment(store, job.id)
    report = runner.run(job.id, stop_at=JobState.ASSETS_READY)

    assert not report.ok
    assert report.final_state == "FAILED"
    assert "repair refused" in (report.stages[-1].detail or "")
    assert (root / "render.json").exists()


def test_unrelated_storyboard_edit_does_not_force_a_rerun(tmp_path):
    """Only the script binds the storyboard; a watermark change is not a re-script."""
    store = _store(tmp_path)
    job = store.create(title="watermark only")
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    assert runner.run(job.id, stop_at=JobState.STORYBOARD_READY).ok
    root = store.artifact_root(job.id)
    board = store.read_artifact(job.id, "storyboard.json")
    board["watermark"] = {"text": "label baru"}
    store.write_artifact(job.id, "storyboard.json", board)
    before = (root / "script.json").stat().st_mtime_ns

    report = runner.run(job.id, stop_at=JobState.STORYBOARD_READY)

    assert report.ok, report.as_dict()
    assert (root / "script.json").stat().st_mtime_ns == before, "the script must not be rewritten"
