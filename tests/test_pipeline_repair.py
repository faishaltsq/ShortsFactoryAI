"""Bounded content-repair loop: findings must reach the script, within a hard cap."""
import json

import pytest

from packages.core.approval import review_fingerprint
from packages.core.config import get_settings
from packages.core.orchestration import JobState, JobStore
from packages.core.pipeline import PipelineRunner, RepairExhausted
from packages.core.pipeline.runner import StageRewound
from packages.core.schemas import CreativeReview, Script


def _store(tmp_path) -> JobStore:
    return JobStore(tmp_path / "factory.db", tmp_path / "jobs")


def _failing_review(**overrides) -> dict:
    data = {
        "technical": {"pass": True, "findings": []},
        "editorial": {"pass": False, "findings": ["hook terlalu lambat"]},
        "factual": {"pass": True, "unsupported_claims": [], "findings": []},
        "overall": "fail",
    }
    data.update(overrides)
    return data


def _passing_review() -> dict:
    return {
        "technical": {"pass": True, "findings": []},
        "editorial": {"pass": True, "findings": []},
        "factual": {"pass": True, "unsupported_claims": [], "findings": []},
        "overall": "pass",
    }


def _script(store: JobStore, job_id: str) -> Script:
    return Script.model_validate(store.read_artifact(job_id, "script.json"))


def _patch_quality(monkeypatch, verdicts: list[dict]):
    """Serve the given draft verdicts in order, then keep serving the last one."""
    from packages.core.agents import QualityAgent

    calls: list[dict] = []

    def run(self, storyboard, script):
        index = min(len(calls), len(verdicts) - 1)
        calls.append({"script": script.full_text})
        return dict(verdicts[index])

    monkeypatch.setattr(QualityAgent, "run", run)
    return calls


def _patch_creative(monkeypatch, verdicts: list[str]):
    """Return the given creative verdicts in order; 'reject' also lists a weak spot."""
    from packages.core.agents import CreativeDirectorAgent

    calls: list[str] = []
    original = CreativeDirectorAgent.run

    def run(self, script):
        index = min(len(calls), len(verdicts) - 1)
        calls.append(verdicts[index])
        verdict = verdicts[index]
        if verdict == "reject":
            return CreativeReview(verdict="reject", weak_spots=["hook klise"], notes="hook needs work")
        return original(self, script)

    monkeypatch.setattr(CreativeDirectorAgent, "run", run)
    return calls


def test_draft_failure_rewrites_the_script_and_finishes(tmp_path, monkeypatch):
    store = _store(tmp_path)
    job = store.create(title="repair once")
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    _patch_quality(monkeypatch, [_failing_review(), _passing_review()])
    revised: list[str] = []
    from packages.core.agents import ScriptAgent

    original_revise = ScriptAgent.revise

    def tracked(self, script, findings):
        assert findings, "findings must reach the revision call"
        revised.append(script.full_text)
        return original_revise(self, script, findings)

    monkeypatch.setattr(ScriptAgent, "revise", tracked)

    report = runner.run(job.id, stop_at=JobState.ASSETS_READY)

    assert report.ok, report.as_dict()
    assert report.final_state == JobState.ASSETS_READY.value
    assert len(revised) == 1
    repair = store.read_artifact(job.id, "repair.json")
    assert repair["status"] == "repaired"
    assert len(repair["attempts"]) == 1
    assert repair["attempts"][0]["source"] == "draft_qc"
    assert repair["attempts"][0]["findings"] == ["hook terlalu lambat"]
    assert repair["attempts"][0]["attempt"] == 1
    assert len(repair["attempts"][0]["script_sha256"]) == 64

    script = _script(store, job.id)
    assert script.full_text != revised[0], "script.json must hold the revised text"
    # The gate that now passes is bound to the revised script and its storyboard.
    from packages.core.media.process import json_hash
    from packages.core.schemas import Storyboard

    storyboard = Storyboard.model_validate(store.read_artifact(job.id, "storyboard.json"))
    expected = review_fingerprint(script.model_dump(mode="json", exclude_none=True),
                                  storyboard.model_dump(mode="json", exclude_none=True))
    assert store.read_artifact(job.id, "draft_qc.json")["inputs_sha256"] == expected
    assert [scene.segment for scene in storyboard.scenes] == [s.text for s in script.segments]


def test_exhausted_repair_blocks_the_job_without_writing_media(tmp_path, monkeypatch):
    store = _store(tmp_path)
    job = store.create(title="never passes")
    settings = get_settings()
    runner = PipelineRunner(store, settings, force_mock=True)
    _patch_quality(monkeypatch, [_failing_review()])
    revise_calls: list[int] = []
    from packages.core.agents import ScriptAgent
    from packages.core.schemas import ScriptSegment

    def always_changes(self, script, findings):
        # A revision that keeps changing text, so the budget — not the no-op guard — ends it.
        revise_calls.append(1)
        segments = [ScriptSegment(kind=s.kind, text=f"{s.text} (revisi {len(revise_calls)})")
                    for s in script.segments]
        return script.model_copy(update={"segments": segments})

    monkeypatch.setattr(ScriptAgent, "revise", always_changes)

    report = runner.run(job.id, stop_at=JobState.ASSETS_READY)

    assert not report.ok
    assert report.final_state == JobState.BLOCKED.value
    assert "exhausted" in (report.blocked_reason or "")
    assert len(revise_calls) == settings.max_repairs
    repair = store.read_artifact(job.id, "repair.json")
    assert repair["status"] == "exhausted"
    assert len(repair["attempts"]) == settings.max_repairs
    assert not (store.artifact_root(job.id) / "assets.json").exists()
    assert store.get(job.id).state is JobState.BLOCKED


def test_unchanged_revision_blocks_instead_of_retrying_the_same_call(tmp_path, monkeypatch):
    store = _store(tmp_path)
    job = store.create(title="model refuses")
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    _patch_quality(monkeypatch, [_failing_review()])

    report = runner.run(job.id, stop_at=JobState.ASSETS_READY)

    # The mock's second revision returns the first revision verbatim: no progress.
    assert not report.ok
    assert report.final_state == JobState.BLOCKED.value
    repair = store.read_artifact(job.id, "repair.json")
    assert repair["status"] == "exhausted"
    assert len(repair["attempts"]) == 2
    assert store.get(job.id).state is JobState.BLOCKED


def test_creative_rejection_rewrites_and_reviews_again(tmp_path, monkeypatch):
    store = _store(tmp_path)
    job = store.create(title="creative reject")
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    verdicts = _patch_creative(monkeypatch, ["reject", "approve"])

    report = runner.run(job.id, stop_at=JobState.STORYBOARD_READY)

    assert report.ok, report.as_dict()
    assert verdicts == ["reject", "approve"]
    repair = store.read_artifact(job.id, "repair.json")
    assert repair["status"] == "repaired"
    assert [attempt["source"] for attempt in repair["attempts"]] == ["creative_review"]
    assert repair["attempts"][0]["findings"] == ["hook needs work", "hook klise"]
    assert store.read_artifact(job.id, "review.json")["review"]["verdict"] == "approve"
    # The rejected draft was invalidated with the script; the draft on disk now
    # belongs to the revised script and carries the approving verdict.
    draft = store.read_artifact(job.id, "creative_draft.json")
    assert draft["review"]["verdict"] == "approve"
    assert Script.model_validate(draft["source_script"]).full_text == _script(store, job.id).full_text


def test_resume_after_a_repair_calls_no_model_twice(tmp_path, monkeypatch):
    store = _store(tmp_path)
    job = store.create(title="resume repaired")
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    quality_calls = _patch_quality(monkeypatch, [_failing_review(), _passing_review()])
    revise_calls: list[int] = []
    from packages.core.agents import ScriptAgent

    original_revise = ScriptAgent.revise

    def tracked(self, script, findings):
        revise_calls.append(1)
        return original_revise(self, script, findings)

    monkeypatch.setattr(ScriptAgent, "revise", tracked)
    assert runner.run(job.id, stop_at=JobState.ASSETS_READY).ok
    assert len(revise_calls) == 1

    quality_before = len(quality_calls)
    second = runner.run(job.id, stop_at=JobState.ASSETS_READY)

    assert second.ok, second.as_dict()
    assert len(revise_calls) == 1, "a resumed run must not revise again"
    assert len(quality_calls) == quality_before, "a resumed run must not re-review"
    assert store.read_artifact(job.id, "repair.json")["status"] == "repaired"


def test_repair_is_refused_once_media_exists(tmp_path, monkeypatch):
    store = _store(tmp_path)
    job = store.create(title="media guard")
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    _patch_quality(monkeypatch, [_passing_review()])
    assert runner.run(job.id, stop_at=JobState.STORYBOARD_READY).ok

    root = store.artifact_root(job.id)
    (root / "render.json").write_text(json.dumps({"output_path": "output.mp4"}), encoding="utf-8")
    before = sorted(path.name for path in root.glob("*.json"))

    with pytest.raises(ValueError, match="repair refused"):
        runner._repair(job.id, source="draft_qc", findings=["hook terlalu lambat"])

    assert not (root / "repair.json").exists(), "a refused repair writes no attempt"
    assert sorted(path.name for path in root.glob("*.json")) == before


def test_stage_rewound_is_a_distinct_signal():
    assert issubclass(StageRewound, Exception)
    assert issubclass(RepairExhausted, ValueError)


def test_draft_failure_with_existing_media_blocks_without_spending_an_attempt(tmp_path, monkeypatch):
    """A script that cannot be revised is an operator decision, not a retry.

    Regression: this raised a plain ValueError, so each resume burned one attempt
    on the same unchangeable state until the cap turned it into BLOCKED with a
    misleading "attempt cap" reason.
    """
    from packages.core.pipeline.runner import PipelineReport

    store = _store(tmp_path)
    job = store.create(title="media guard blocks")
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    _patch_quality(monkeypatch, [_passing_review()])
    assert runner.run(job.id, stop_at=JobState.STORYBOARD_READY).ok

    root = store.artifact_root(job.id)
    (root / "render.json").write_text(json.dumps({"output_path": "output.mp4"}), encoding="utf-8")
    from packages.core.approval import review_fingerprint

    script = _script(store, job.id)
    board = store.read_artifact(job.id, "storyboard.json")
    review = _failing_review()
    review["inputs_sha256"] = review_fingerprint(script.model_dump(mode="json", exclude_none=True), board)
    store.write_artifact(job.id, "draft_qc.json", review)
    before = store.get(job.id).attempts

    report = PipelineReport(job.id)
    with pytest.raises(RepairExhausted, match="cannot be revised"):
        runner._draft_checks(job.id, report)

    assert store.get(job.id).attempts == before, "an operator decision must not consume the retry budget"
