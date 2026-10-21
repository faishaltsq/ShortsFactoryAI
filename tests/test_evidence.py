import pytest

from packages.core.artifacts import validate_artifact
from packages.core.config import get_settings
from packages.core.jsonutil import extract_model
from packages.core.orchestration import JobState, JobStore
from packages.core.pipeline import PipelineRunner
from packages.core.providers import MockProvider
from packages.core.schemas import Script, ScriptClaimList, VerificationStatus


def _store(tmp_path) -> JobStore:
    return JobStore(tmp_path / "factory.db", tmp_path / "jobs")


def _mock_script() -> Script:
    result = MockProvider().complete(task="script", system="s", user="u")
    return extract_model(result.content, Script)


def test_mock_claim_extraction_returns_no_fabricated_proof():
    result = MockProvider().complete(task="claim_extraction", system="s", user="u")
    assert extract_model(result.content, ScriptClaimList).claims == []


def test_mock_run_records_verification_and_originality(tmp_path):
    store = _store(tmp_path)
    job = store.create(title="bukti")
    report = PipelineRunner(store, get_settings(), force_mock=True).run(job.id, stop_at=JobState.CREATIVE_REVIEW)
    assert report.ok, report.blocked_reason

    verification = store.read_artifact(job.id, "verification.json")
    validate_artifact("verification.json", verification)
    assert verification["retrieval"] in {"skipped_mock", "not_applicable"}
    assert verification["status"] in {"needs_review", "fictional"}

    originality = store.read_artifact(job.id, "originality.json")
    validate_artifact("originality.json", originality)
    assert originality["verdict"] in {"original", "too_similar"}
    assert originality["enforced"] is False, "fixture runs record overlap without blocking on identical fixtures"


def test_second_mock_job_does_not_block_on_identical_fixture_script(tmp_path):
    store = _store(tmp_path)
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    first = store.create(title="naskah pertama")
    runner.run(first.id, stop_at=JobState.CREATIVE_REVIEW)
    second = store.create(title="naskah kedua")
    report = runner.run(second.id, stop_at=JobState.CREATIVE_REVIEW)
    assert report.ok, report.blocked_reason
    originality = store.read_artifact(second.id, "originality.json")
    assert originality["enforced"] is False


def test_originality_gate_fails_the_job_when_enforced(tmp_path):
    store = _store(tmp_path)
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    shipped = store.create(title="sudah tayang")
    runner.run(shipped.id, stop_at=JobState.CREATIVE_REVIEW)
    script = Script.model_validate(store.read_artifact(shipped.id, "script.json"))

    runner.force_mock = False  # enforcement branch: fictional script needs no network or model call
    script = script.model_copy(update={"content_type": "fictional", "verification_status": VerificationStatus.fictional})
    duplicate = store.create(title="duplikat")
    with pytest.raises(ValueError, match="originality check failed"):
        runner._evidence(duplicate.id, script)

    originality = store.read_artifact(duplicate.id, "originality.json")
    validate_artifact("originality.json", originality)
    assert originality["verdict"] == "too_similar"
    assert originality["max_similarity"] == 1.0
    assert originality["enforced"] is True
    assert originality["nearest_job_id"] == shipped.id


def test_verification_is_written_before_the_originality_gate_fires(tmp_path):
    """A blocked duplicate must still leave its verification record on disk."""
    store = _store(tmp_path)
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    shipped = store.create(title="sudah tayang")
    runner.run(shipped.id, stop_at=JobState.CREATIVE_REVIEW)
    script = Script.model_validate(store.read_artifact(shipped.id, "script.json"))

    runner.force_mock = False
    script = script.model_copy(update={"content_type": "fictional", "verification_status": VerificationStatus.fictional})
    duplicate = store.create(title="duplikat lagi")
    with pytest.raises(ValueError, match="originality check failed"):
        runner._evidence(duplicate.id, script)

    verification = store.read_artifact(duplicate.id, "verification.json")
    validate_artifact("verification.json", verification)
    assert verification["status"] == "fictional"
