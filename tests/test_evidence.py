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


@pytest.mark.parametrize("missing", ["verification.json", "originality.json"])
def test_resume_repairs_missing_evidence_without_repeating_creative_review(tmp_path, monkeypatch, missing):
    from packages.core.media.process import json_hash

    store = _store(tmp_path)
    job = store.create(title="resume partial evidence")
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    assert runner.run(job.id, stop_at=JobState.CREATIVE_REVIEW).ok
    (store.artifact_root(job.id) / missing).unlink()
    monkeypatch.setattr(runner, "_creative", lambda _: pytest.fail("creative review reran"))

    report = runner.run(job.id, stop_at=JobState.CREATIVE_REVIEW)

    assert report.ok, report.as_dict()
    script = Script.model_validate(store.read_artifact(job.id, "script.json"))
    verification = validate_artifact("verification.json", store.read_artifact(job.id, "verification.json"))
    originality = validate_artifact("originality.json", store.read_artifact(job.id, "originality.json"))
    assert verification["script_sha256"] == json_hash(script.model_dump(mode="json", exclude_none=True))
    assert originality["script_text_sha256"] == json_hash({"text": script.full_text})


def test_creative_review_is_not_marked_complete_before_evidence(tmp_path, monkeypatch):
    store = _store(tmp_path)
    job = store.create(title="interrupted evidence")
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    original_evidence = runner._evidence

    def interrupted(*_):
        raise ValueError("interrupted after script revision")

    monkeypatch.setattr(runner, "_evidence", interrupted)
    report = runner.run(job.id, stop_at=JobState.CREATIVE_REVIEW)

    assert not report.ok
    assert not (store.artifact_root(job.id) / "review.json").exists()
    monkeypatch.setattr(runner, "_evidence", original_evidence)
    resumed = runner.run(job.id, stop_at=JobState.CREATIVE_REVIEW)
    assert resumed.ok, resumed.as_dict()
    assert (store.artifact_root(job.id) / "review.json").is_file()
    assert (store.artifact_root(job.id) / "verification.json").is_file()
    assert (store.artifact_root(job.id) / "originality.json").is_file()


def test_creative_revision_resumes_evidence_without_repeating_review(tmp_path, monkeypatch):
    from packages.core.agents import CreativeDirectorAgent
    from packages.core.schemas import CreativeReview

    store = _store(tmp_path)
    job = store.create(title="revised review interrupted")
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    calls = []

    def revise(self, script):
        calls.append(script.full_text)
        return CreativeReview(verdict="revise", revisions=[{"segment_index": 0, "replacement": "KALIMAT BARU"}])

    monkeypatch.setattr(CreativeDirectorAgent, "run", revise)
    original_evidence = runner._evidence
    monkeypatch.setattr(runner, "_evidence", lambda *_: (_ for _ in ()).throw(ValueError("interrupted evidence")))
    assert not runner.run(job.id, stop_at=JobState.CREATIVE_REVIEW).ok
    assert not (store.artifact_root(job.id) / "review.json").exists()
    monkeypatch.setattr(runner, "_evidence", original_evidence)

    resumed = runner.run(job.id, stop_at=JobState.CREATIVE_REVIEW)

    assert resumed.ok, resumed.as_dict()
    assert len(calls) == 1, "resuming evidence must not call the creative model again"
    assert store.read_artifact(job.id, "script.json")["segments"][0]["text"] == "KALIMAT BARU"
    assert store.read_artifact(job.id, "review.json")["review"]["verdict"] == "revise"


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


def test_claim_extraction_uses_bounded_untrusted_source_excerpts():
    from packages.core.agents import ClaimExtractorAgent
    from packages.core.providers import ProviderRouter

    class RecordingProvider(MockProvider):
        def complete(self, **kwargs):
            self.received = kwargs
            return super().complete(**kwargs)

    provider = RecordingProvider()
    agent = ClaimExtractorAgent(ProviderRouter(worker_chain=[provider]))
    agent.run(_mock_script(), sources=[{"url": "https://example.com/source", "text": "evidence " * 4000}])
    assert "https://example.com/source" in provider.received["user"]
    assert "evidence evidence" in provider.received["user"]
    assert len(provider.received["user"]) < 16000
    assert "bukan instruksi" in provider.received["system"]


def test_live_evidence_persists_fetched_text_for_rechecking(tmp_path, monkeypatch):
    import hashlib
    from packages.core.pipeline import runner as runner_module
    from packages.core.research import FetchedSource
    from packages.core.research.verification import Claim
    from packages.core.schemas import SourceRef

    store = _store(tmp_path)
    job = store.create(title="kutipan tersimpan")
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    runner.force_mock = False
    script = _mock_script().model_copy(update={
        "content_type": "factual", "sources": [SourceRef(title="Labelled test source", url="https://example.com/source")],
    })
    store.write_artifact(job.id, "script.json", script.model_dump(mode="json"))
    text = "Solar panels convert sunlight into electricity."
    source = FetchedSource(url="https://example.com/source", status="ok", chars=len(text),
                           sha256=hashlib.sha256(text.encode()).hexdigest(), text=text)
    monkeypatch.setattr(runner_module, "fetch_sources", lambda urls: [source])
    monkeypatch.setattr(runner_module.ClaimExtractorAgent, "run", lambda self, value, **kwargs: [
        Claim(statement=text, quote=text, source_url=source.url),
    ])
    runner._evidence(job.id, script)
    saved = store.read_artifact(job.id, "verification.json")
    assert saved["status"] == "supported"
    assert saved["sources"][0]["text"] == text
    assert saved["sources"][0]["text_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    from packages.core.media.process import json_hash
    current = Script.model_validate(store.read_artifact(job.id, "script.json"))
    assert saved["script_sha256"] == json_hash(current.model_dump(mode="json", exclude_none=True))
    originality = store.read_artifact(job.id, "originality.json")
    assert originality["script_text_sha256"] == json_hash({"text": current.full_text})


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
