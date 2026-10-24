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

    from packages.core.prompts import MAX_CLAIM_SOURCE_CHARS

    provider = RecordingProvider()
    agent = ClaimExtractorAgent(ProviderRouter(worker_chain=[provider]))
    agent.run(_mock_script(), sources=[{"url": "https://example.com/source", "text": "evidence " * 20000}])
    assert "https://example.com/source" in provider.received["user"]
    assert "evidence evidence" in provider.received["user"]
    # Bounded, but bounded by the declared source cap rather than a silent head slice.
    assert len(provider.received["user"]) < MAX_CLAIM_SOURCE_CHARS + 4000
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


def test_unreadable_citations_trigger_a_rewrite_before_any_render(tmp_path, monkeypatch):
    """Every live job used to burn TTS and a render before the gate found no source.

    Source readability is now checked at CREATIVE_REVIEW, while a rewrite is free,
    so the repair loop can replace the dead citations.
    """
    from packages.core.pipeline import runner as runner_module
    from packages.core.pipeline.runner import EvidenceUnavailable
    from packages.core.research import FetchedSource
    from packages.core.schemas import SourceRef

    store = _store(tmp_path)
    job = store.create(title="sumber mati")
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    runner.force_mock = False
    script = _mock_script().model_copy(update={
        "content_type": "factual",
        "sources": [SourceRef(title="Paywalled", url="https://example.com/paywalled")],
    })
    store.write_artifact(job.id, "script.json", script.model_dump(mode="json"))
    monkeypatch.setattr(runner_module, "fetch_sources", lambda urls: [
        FetchedSource(url="https://example.com/paywalled", status="http_403", error="http_403"),
    ])

    with pytest.raises(EvidenceUnavailable, match="no cited source could be read"):
        runner._evidence(job.id, script)

    assert not (store.artifact_root(job.id) / "audio.json").exists(), \
        "the failure must land before any paid media work"


def test_a_readable_citation_is_not_treated_as_a_failure(tmp_path, monkeypatch):
    from packages.core.pipeline import runner as runner_module
    from packages.core.research import FetchedSource

    store = _store(tmp_path)
    job = store.create(title="sumber hidup")
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    runner.force_mock = False
    from packages.core.schemas import SourceRef

    script = _mock_script().model_copy(update={
        "content_type": "factual",
        "sources": [SourceRef(title="Reachable", url="https://example.com/ok")],
    })
    store.write_artifact(job.id, "script.json", script.model_dump(mode="json"))
    monkeypatch.setattr(runner_module, "fetch_sources", lambda urls: [
        FetchedSource(url="https://example.com/ok", status="ok", chars=10, text="evidence text"),
    ])
    monkeypatch.setattr(runner_module.ClaimExtractorAgent, "run", lambda self, value, **kwargs: [])

    runner._evidence(job.id, script)  # must not raise
    assert store.read_artifact(job.id, "verification.json")["retrieved"] == 1


def test_reused_review_with_dead_citations_rewinds_instead_of_failing(tmp_path, monkeypatch):
    """The reuse path must reach the same repair loop as the fresh path.

    Regression: `_ensure_evidence` raised straight out of the reuse branch, so a
    resumed job died on dead citations with no rewrite attempt.
    """
    from packages.core.pipeline import runner as runner_module
    from packages.core.pipeline.runner import StageRewound
    from packages.core.research import FetchedSource
    from packages.core.schemas import SourceRef

    store = _store(tmp_path)
    job = store.create(title="kutipan mati saat reuse")
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    runner.force_mock = False
    script = _mock_script().model_copy(update={
        "content_type": "factual",
        "sources": [SourceRef(title="Paywalled", url="https://example.com/paywalled")],
    })
    store.write_artifact(job.id, "script.json", script.model_dump(mode="json"))
    store.transition(job.id, JobState.TOPIC_SELECTED, detail="test setup")
    store.transition(job.id, JobState.SCRIPT_GENERATED, detail="test setup")
    monkeypatch.setattr(runner_module, "fetch_sources", lambda urls: [
        FetchedSource(url="https://example.com/paywalled", status="http_403", error="http_403"),
    ])
    monkeypatch.setattr(runner_module.ScriptAgent, "revise", lambda self, script, findings: script.model_copy(
        update={"segments": script.segments}))

    with pytest.raises(StageRewound):
        runner._ensure_evidence(job.id)

    record = store.read_artifact(job.id, "repair.json")
    assert record["attempts"][0]["source"] == "evidence"


def test_cached_verification_with_zero_readable_sources_is_rechecked(tmp_path, monkeypatch):
    """A cache written when every source failed must not suppress a re-read."""
    from packages.core.pipeline import runner as runner_module
    from packages.core.research import FetchedSource
    from packages.core.schemas import SourceRef
    from packages.core.media.process import json_hash

    store = _store(tmp_path)
    job = store.create(title="cache nol sumber")
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    runner.force_mock = False
    script = _mock_script().model_copy(update={
        "content_type": "factual",
        "sources": [SourceRef(title="Dead", url="https://example.com/dead")],
    })
    store.write_artifact(job.id, "script.json", script.model_dump(mode="json"))
    store.write_artifact(job.id, "verification.json", {
        "status": "needs_review", "retrieval": "live", "retrieved": 0, "checks": [],
        "sources": [{"url": "https://example.com/dead", "status": "http_403"}],
        "script_sha256": json_hash(script.model_dump(mode="json", exclude_none=True)),
    })
    store.write_artifact(job.id, "originality.json", {
        "script_text_sha256": json_hash({"text": script.full_text}),
        "verdict": "original", "max_similarity": 0.0, "compared": 0, "threshold": 0.55,
        "enforced": True, "note": "",
    })
    calls = []
    monkeypatch.setattr(runner_module, "fetch_sources", lambda urls: calls.append(urls) or [
        FetchedSource(url="https://example.com/dead", status="http_403", error="http_403"),
    ])

    with pytest.raises(Exception):
        runner._ensure_evidence(job.id)

    assert calls, "the cached zero-source verdict must not short-circuit a re-read"


def test_revision_that_only_replaces_dead_sources_is_accepted(tmp_path, monkeypatch):
    """A citation repair changes sources, not prose, and must not be rejected as unchanged."""
    from packages.core.agents import ScriptAgent
    from packages.core.providers import MockProvider, ProviderRouter
    from packages.core.schemas import SourceRef

    router = ProviderRouter(worker_chain=[MockProvider()])
    agent = ScriptAgent(router)
    original = _mock_script().model_copy(update={
        "content_type": "factual",
        "sources": [SourceRef(title="Dead", url="https://example.com/dead")],
    })
    revised = original.model_copy(update={
        "sources": [SourceRef(title="Live", url="https://example.com/live")],
    })
    monkeypatch.setattr(agent, "_ask", lambda **kwargs: type("R", (), {"content": revised.model_dump_json()})())
    out = agent.revise(original, ["sumber tidak dapat dibaca"])
    assert [s.url for s in out.sources] == ["https://example.com/live"]


def test_stale_unsupported_status_is_recomputed_from_stored_evidence(tmp_path):
    """A verdict written by an older matcher must not outlive the fix.

    The job was rejected while `[ page needed ]` was still treated as source text.
    Resuming re-read the stored `status` and rejected again even though every quote
    in the same record now matches. The aggregate is derived from `checks`, so it
    is recomputed without a model call.
    """
    import hashlib
    from packages.core.media.process import json_hash
    from packages.core.schemas import SourceRef

    store = _store(tmp_path)
    job = store.create(title="status usang")
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    runner.force_mock = False
    text = ("He was surprised that some people attributed human-like feelings to the computer "
            "program, [ page needed ] a phenomenon that came to be called the ELIZA effect.")
    script = _mock_script().model_copy(update={
        "content_type": "factual", "verification_status": VerificationStatus.unsupported,
        "sources": [SourceRef(title="ELIZA", url="https://example.com/eliza")],
    })
    store.write_artifact(job.id, "script.json", script.model_dump(mode="json"))
    quote = ("He was surprised that some people attributed human-like feelings to the computer "
             "program, a phenomenon that came to be called the ELIZA effect.")
    store.write_artifact(job.id, "verification.json", {
        "status": "unsupported", "retrieval": "live", "retrieved": 1,
        "checks": [{"statement": "efek ELIZA", "status": "unsupported", "quote": quote,
                    "source_url": "https://example.com/eliza", "matched": "", "reason": "quote not found"}],
        "sources": [{"url": "https://example.com/eliza", "status": "ok", "text": text,
                     "chars": len(text), "text_sha256": hashlib.sha256(text.encode()).hexdigest()}],
        "script_sha256": json_hash(script.model_dump(mode="json", exclude_none=True)),
    })
    store.write_artifact(job.id, "originality.json", {
        "script_text_sha256": json_hash({"text": script.full_text}),
        "verdict": "original", "max_similarity": 0.0, "compared": 0, "threshold": 0.55,
        "enforced": True, "note": "",
    })

    runner._refresh_evidence(job.id)

    saved = store.read_artifact(job.id, "verification.json")
    assert saved["status"] == "supported", saved
    assert saved["script_sha256"] == json_hash(
        Script.model_validate(store.read_artifact(job.id, "script.json")).model_dump(mode="json", exclude_none=True))


def test_recompute_does_not_rewrite_a_script_bound_to_measured_media(tmp_path):
    """verification_status participates in the narration hash, so it must not move.

    Recomputing the verdict after a render used to rewrite script.json and make
    `verify_audio` reject narration that still matched the spoken words.
    """
    from packages.core.media.process import json_hash

    store = _store(tmp_path)
    job = store.create(title="media terikat")
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    script = _mock_script().model_copy(update={"content_type": "factual",
                                               "verification_status": VerificationStatus.unsupported})
    store.write_artifact(job.id, "script.json", script.model_dump(mode="json"))
    (store.artifact_root(job.id) / "audio.json").write_text('{}', encoding="utf-8")
    before = (store.artifact_root(job.id) / "script.json").read_bytes()
    verification = {
        "status": "unsupported", "retrieval": "live", "retrieved": 1,
        "checks": [{"statement": "x", "status": "supported", "quote": "a quote long enough to match",
                    "source_url": "https://example.com/s"}],
        "sources": [{"url": "https://example.com/s", "status": "ok",
                     "text": "a quote long enough to match here"}],
        "script_sha256": json_hash(script.model_dump(mode="json", exclude_none=True)),
    }

    assert runner._restatus_verification(job.id, script, verification) is True

    assert (store.artifact_root(job.id) / "script.json").read_bytes() == before
    assert store.read_artifact(job.id, "verification.json")["status"] == "supported"
