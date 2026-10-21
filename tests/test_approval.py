"""Approval gate tests use real, labelled offline media and injected model fixtures."""
import shutil
import subprocess
import wave
from pathlib import Path

import pytest

from packages.core.approval import ApprovalRejected, approve, evaluate, pending, reject
from packages.core.artifacts import validate_artifact
from packages.core.config import get_settings
from packages.core.media.process import json_hash, probe_media, sha256_file
from packages.core.orchestration import JobState, JobStore
from packages.core.pipeline import PipelineRunner
from packages.core.schemas import Genre, SceneSpec, Script, ScriptSegment, Storyboard, SubtitleCue

_MEDIA: Path | None = None


@pytest.fixture(scope="module")
def labelled_media(tmp_path_factory):
    root = tmp_path_factory.mktemp("approval-labelled-offline-media")
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
        "sine=frequency=440:sample_rate=48000:duration=30", "-c:a", "pcm_s16le", str(root / "narration.wav"),
    ], check=True, capture_output=True, timeout=30)
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
        "color=c=white:s=160x284:r=30:d=30", "-i", str(root / "narration.wav"),
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(root / "output.mp4"),
    ], check=True, capture_output=True, timeout=45)
    with wave.open(str(root / "narration.wav"), "rb") as source:
        for index in range(2):
            with wave.open(str(root / f"s{index}.wav"), "wb") as output:
                output.setparams(source.getparams())
                output.writeframes(source.readframes(15 * 48000))
    return root


@pytest.fixture(autouse=True)
def use_labelled_media(labelled_media, monkeypatch):
    monkeypatch.setattr(__import__(__name__, fromlist=["_MEDIA"]), "_MEDIA", labelled_media)


def _store(tmp_path) -> JobStore:
    return JobStore(tmp_path / "factory.db", tmp_path / "jobs")


def _seed(store: JobStore, job_id: str, *, verification: str = "fictional",
          originality: tuple[str, bool] = ("original", False), editorial_pass: bool = True) -> None:
    """Seed gate inputs with valid schemas, dependency hashes and real offline files."""
    assert _MEDIA is not None
    record = store.get(job_id)
    if not record.payload.get("provider_mode"):
        store.transition(job_id, record.state, payload_patch={"provider_mode": "mock"})
    root = store.artifact_dir(job_id)
    for name in ("narration.wav", "output.mp4", "s0.wav", "s1.wav"):
        shutil.copyfile(_MEDIA / name, root / name)
    script = Script(
        title="Uji gerbang", genre=Genre.mystery, content_type="fictional", verification_status="fictional",
        segments=[
            ScriptSegment(kind="hook", text="Ada satu pertanyaan yang belum dijawab."),
            ScriptSegment(kind="body", text="Dan jawabannya mengubah segalanya."),
        ],
    )
    cues = [SubtitleCue(id=f"c{i}", text=segment.text, startMs=i * 15000, endMs=(i + 1) * 15000)
            for i, segment in enumerate(script.segments)]
    storyboard = Storyboard(
        id="sb-uji", width=160, height=284,
        scenes=[SceneSpec(sceneId=f"s{i}", template="KineticTypography", segment=segment.text,
                          startFrame=i * 450, durationInFrames=450) for i, segment in enumerate(script.segments)],
        subtitles=cues, narration={"src": "narration.wav", "durationMs": 30000},
    )
    storyboard_hash = json_hash(storyboard.model_dump(mode="json", exclude_none=True))
    audio_hash = sha256_file(root / "narration.wav")
    render_hash = sha256_file(root / "output.mp4")
    store.write_artifact(job_id, "script.json", script.model_dump(mode="json"))
    store.write_artifact(job_id, "storyboard.json", storyboard.model_dump(mode="json"))
    script_data = script.model_dump(mode="json", exclude_none=True)
    board_data = storyboard.model_dump(mode="json", exclude_none=True)
    store.write_artifact(job_id, "draft_qc.json", {
        "inputs_sha256": json_hash({"script": script_data, "storyboard": board_data}),
        "technical": {"pass": True, "findings": []},
        "editorial": {"pass": editorial_pass, "findings": []},
        "factual": {"pass": True}, "overall": "pass" if editorial_pass else "fail",
    })
    store.write_artifact(job_id, "metadata.json", {
        "script_sha256": json_hash(script_data),
        "title": "Judul uji", "description": "Deskripsi uji", "tags": ["uji"], "thumbnail": {},
    })
    store.write_artifact(job_id, "verification.json", {
        "status": verification, "retrieval": "not_applicable" if verification == "fictional" else "skipped_mock",
        "checks": [], "sources": [], "retrieved": 0, "note": "",
    })
    verdict, enforced = originality
    store.write_artifact(job_id, "originality.json", {
        "verdict": verdict, "max_similarity": 1.0 if verdict == "too_similar" else 0.0,
        "compared": 0, "threshold": 0.55, "enforced": enforced, "note": "",
    })
    store.write_artifact(job_id, "qc.json", {
        "technical_pass": True, "checks": {"duration": True}, "notes": [],
        "render_sha256": render_hash, "audio_stats": {"integrated_loudness": -16.0},
    })
    store.write_artifact(job_id, "assets.json", {
        "mode": "project-generated-vectors", "templates": ["KineticTypography"],
        "assets": [], "license": "project-original",
    })
    store.write_artifact(job_id, "audio.json", {
        "engine": "edge-tts", "voice": "labelled-offline-test-tone", "rate": "+0%",
        "narration_path": "narration.wav", "duration_ms": 30000.0,
        "sha256": audio_hash, "script_sha256": json_hash(script.model_dump(mode="json", exclude_none=True)),
        "storyboard_sha256": storyboard_hash, "fps": 30, "total_frames": 900,
        "segments": [{"scene_id": f"s{i}", "path": f"s{i}.wav", "raw_duration_ms": 15000,
                      "duration_frames": 450, "sha256": sha256_file(root / f"s{i}.wav")} for i in range(2)],
        "cues": [cue.model_dump(mode="json") for cue in cues],
        "timing_source": "edge-tts-word-boundaries+ffprobe",
    })
    probe = probe_media(root / "output.mp4")
    store.write_artifact(job_id, "render.json", {
        "output_path": "output.mp4", "sha256": render_hash, "storyboard_sha256": storyboard_hash,
        "audio_sha256": audio_hash, "duration_ms": float(probe["format"]["duration"]) * 1000,
        "frame_count": 900, "probe": probe, "composition": "Short",
    })


def _pending_job(store: JobStore, **seed_kwargs):
    job = store.create(title="menunggu", state=JobState.TECHNICAL_QC,
                       payload={"provider_mode": "mock"})
    _seed(store, job.id, **seed_kwargs)
    return job


def _only_approval_stages(runner: PipelineRunner) -> None:
    """Run just the two new stages; the earlier stages are already on disk.

    Everything before EDITORIAL_QC is a rendered production pipeline with its
    own tests; these stages are what is under test here, so the seed above
    stands in for them instead of paying for another render.
    """
    runner._stages = lambda: [
        (JobState.EDITORIAL_QC, "editorial_qc.json", runner._editorial_qc),
        (JobState.READY_FOR_APPROVAL, "approval.json", runner._approval_gate),
    ]


def test_gate_reports_every_missing_artifact_on_a_fresh_job(tmp_path):
    store = _store(tmp_path)
    job = store.create(title="masih kosong")
    gate = evaluate(store, job.id)
    assert gate.eligible is False
    names = {check["name"] for check in gate.checks}
    assert {"technical_qc", "editorial_review", "metadata", "assets", "audio", "render"} <= names
    assert gate.blockers, "a job with no artifacts has blockers, not a crash"
    assert gate.requires_operator_approval is True
    assert gate.checked_at


def test_gate_requires_verification_artifact(tmp_path):
    store = _store(tmp_path)
    job = store.create(title="bukti hilang")
    _seed(store, job.id)
    (store.artifact_root(job.id) / "verification.json").unlink()
    gate = evaluate(store, job.id)
    assert not gate.eligible
    assert any("verification.json" in blocker for blocker in gate.blockers)


def test_gate_requires_originality_artifact(tmp_path):
    store = _store(tmp_path)
    job = store.create(title="orisinalitas hilang")
    _seed(store, job.id)
    (store.artifact_root(job.id) / "originality.json").unlink()
    gate = evaluate(store, job.id)
    assert not gate.eligible
    assert any("originality.json" in blocker for blocker in gate.blockers)


def test_gate_rejects_nonexistent_physical_media(tmp_path):
    store = _store(tmp_path)
    job = store.create(title="hanya metadata")
    _seed(store, job.id)
    (store.artifact_root(job.id) / "output.mp4").unlink()
    gate = evaluate(store, job.id)
    assert not gate.eligible
    assert any("media_integrity" in blocker for blocker in gate.blockers)


def test_gate_passes_a_complete_job(tmp_path):
    store = _store(tmp_path)
    job = store.create(title="lengkap")
    _seed(store, job.id)
    gate = evaluate(store, job.id)
    assert gate.eligible is True, gate.blockers
    assert gate.blockers == []
    assert {"technical_qc", "editorial_review", "source_verification", "originality", "media_integrity"} <= {
        check["name"] for check in gate.checks
    }


def test_gate_blocks_a_contradicted_claim(tmp_path):
    store = _store(tmp_path)
    job = store.create(title="klaim dibantah")
    _seed(store, job.id, verification="unsupported")
    gate = evaluate(store, job.id)
    assert gate.eligible is False
    assert any("source_verification" in blocker for blocker in gate.blockers)


def test_gate_blocks_an_enforced_duplicate(tmp_path):
    store = _store(tmp_path)
    job = store.create(title="naskah kembar")
    _seed(store, job.id, originality=("too_similar", True))
    gate = evaluate(store, job.id)
    assert gate.eligible is False
    assert any("originality" in blocker for blocker in gate.blockers)


def test_gate_records_unenforced_overlap_without_blocking(tmp_path):
    store = _store(tmp_path)
    job = store.create(title="fixture kembar")
    _seed(store, job.id, originality=("too_similar", False))
    gate = evaluate(store, job.id)
    assert gate.eligible is True, "fixture runs record identical scripts without enforcing"


def test_gate_blocks_a_failing_editorial_review(tmp_path):
    store = _store(tmp_path)
    job = store.create(title="ulasan gagal")
    _seed(store, job.id, editorial_pass=False)
    gate = evaluate(store, job.id)
    assert gate.eligible is False
    assert any("editorial_review" in blocker for blocker in gate.blockers)


def test_runner_lands_a_complete_job_on_ready_for_approval(tmp_path):
    store = _store(tmp_path)
    job = _pending_job(store)
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    _only_approval_stages(runner)
    report = runner.run(job.id, stop_at=JobState.READY_FOR_APPROVAL)

    assert report.ok, report.blocked_reason
    assert report.final_state == JobState.READY_FOR_APPROVAL
    assert store.get(job.id).state is JobState.READY_FOR_APPROVAL, "pipeline never approves itself"

    editorial = validate_artifact("editorial_qc.json", store.read_artifact(job.id, "editorial_qc.json"))
    assert editorial["overall"] == "pass"
    assert all(check["pass"] for check in editorial["checks"])

    gate = validate_artifact("approval.json", store.read_artifact(job.id, "approval.json"))
    assert gate["eligible"] is True
    assert gate["requires_operator_approval"] is True
    assert gate["checked_at"]
    assert gate["blockers"] == []
    from packages.core.observability.projection import StudioService
    view = StudioService(store).snapshot(job_id=job.id)["jobs"][0]
    assert view["quality"]["editorial"] is True
    assert view["approval_required"] is True


def test_runner_rejects_an_ineligible_job_instead_of_failing_it(tmp_path):
    store = _store(tmp_path)
    job = _pending_job(store, verification="unsupported")
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    _only_approval_stages(runner)
    report = runner.run(job.id, stop_at=JobState.READY_FOR_APPROVAL)

    assert report.ok is False
    assert report.final_state == "REJECTED", "an ineligible job is rejected, not crashed"
    assert store.get(job.id).state is JobState.REJECTED
    editorial = store.read_artifact(job.id, "editorial_qc.json")
    assert editorial["overall"] == "fail"
    failed = [check for check in editorial["checks"] if not check["pass"]]
    assert failed and failed[0]["name"] == "source_verification"


def test_ineligible_job_never_reaches_ready_for_approval_on_rerun(tmp_path):
    store = _store(tmp_path)
    job = _pending_job(store, verification="unsupported")
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    _only_approval_stages(runner)
    runner.run(job.id, stop_at=JobState.READY_FOR_APPROVAL)
    assert store.get(job.id).state is JobState.REJECTED
    assert not (store.artifact_root(job.id) / "approval.json").exists()
    assert not pending(store), "a rejected job is not waiting for anyone"


def test_approval_requires_the_operator_and_records_who(tmp_path):
    store = _store(tmp_path)
    job = _pending_job(store)
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    _only_approval_stages(runner)
    runner.run(job.id, stop_at=JobState.READY_FOR_APPROVAL)

    assert [row[0] for row in pending(store)] == [job.id]
    approve(store, job.id, operator="koko")
    record = store.get(job.id)
    assert record.state is JobState.APPROVED
    assert record.payload["approved_by"] == "koko"
    assert record.payload["approved_at"]
    assert len(record.payload["approved_inputs_sha256"]) == 64
    assert pending(store) == []


def test_approval_refuses_metadata_changed_since_gate(tmp_path):
    store = _store(tmp_path)
    job = _pending_job(store)
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    _only_approval_stages(runner)
    assert runner.run(job.id, stop_at=JobState.READY_FOR_APPROVAL).ok
    metadata = store.read_artifact(job.id, "metadata.json")
    metadata["title"] = "Judul berbeda setelah pemeriksaan"
    store.write_artifact(job.id, "metadata.json", metadata)
    with pytest.raises(ApprovalRejected, match="stale"):
        approve(store, job.id, operator="koko")
    assert store.get(job.id).state is JobState.READY_FOR_APPROVAL


def test_runner_refreshes_gate_after_inputs_change(tmp_path):
    store = _store(tmp_path)
    job = _pending_job(store)
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    _only_approval_stages(runner)
    assert runner.run(job.id, stop_at=JobState.READY_FOR_APPROVAL).ok
    before = store.read_artifact(job.id, "approval.json")["inputs_sha256"]
    metadata = store.read_artifact(job.id, "metadata.json")
    metadata["title"] = "Judul disunting operator"
    store.write_artifact(job.id, "metadata.json", metadata)
    assert runner.run(job.id, stop_at=JobState.READY_FOR_APPROVAL).ok
    assert store.read_artifact(job.id, "approval.json")["inputs_sha256"] != before
    approve(store, job.id, operator="koko")
    assert store.get(job.id).state is JobState.APPROVED


def test_runner_rechecks_eligibility_instead_of_trusting_cached_gate(tmp_path):
    store = _store(tmp_path)
    job = _pending_job(store)
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    _only_approval_stages(runner)
    assert runner.run(job.id, stop_at=JobState.READY_FOR_APPROVAL).ok
    (store.artifact_root(job.id) / "output.mp4").write_bytes(b"not an MP4")
    report = runner.run(job.id, stop_at=JobState.READY_FOR_APPROVAL)
    assert not report.ok
    assert report.final_state == "REJECTED"


def test_approval_requires_gate_artifact_not_only_state(tmp_path):
    store = _store(tmp_path)
    job = _pending_job(store)
    store.transition(job.id, JobState.EDITORIAL_QC)
    store.transition(job.id, JobState.READY_FOR_APPROVAL)
    with pytest.raises(ApprovalRejected, match="approval"):
        approve(store, job.id, operator="koko")


def test_gate_blocks_live_facts_without_verification(tmp_path):
    store = _store(tmp_path)
    job = _pending_job(store, verification="needs_review", originality=("original", True))
    store.transition(job.id, job.state, payload_patch={"provider_mode": "live"})
    script = store.read_artifact(job.id, "script.json")
    script.update(content_type="factual", verification_status="needs_review")
    store.write_artifact(job.id, "script.json", script)
    gate = evaluate(store, job.id)
    assert not gate.eligible
    assert any(b.startswith("source_verification:") for b in gate.blockers)


def _live_factual_job(store):
    import hashlib
    job = _pending_job(store, verification="supported", originality=("original", True))
    store.transition(job.id, job.state, payload_patch={"provider_mode": "live"})
    script = store.read_artifact(job.id, "script.json")
    script.update(content_type="factual", verification_status="supported", sources=[
        {"title": "Labelled offline evidence", "url": "https://example.com/source"},
    ])
    script = Script.model_validate(script)
    store.write_artifact(job.id, "script.json", script.model_dump(mode="json"))
    digest = json_hash(script.model_dump(mode="json", exclude_none=True))
    audio = store.read_artifact(job.id, "audio.json")
    audio["script_sha256"] = digest
    store.write_artifact(job.id, "audio.json", audio)
    text = script.full_text
    verification = {
        "status": "supported", "retrieval": "live", "script_sha256": digest, "retrieved": 1,
        "checks": [{"statement": text, "status": "supported", "quote": text,
                    "source_url": "https://example.com/source", "matched": text}],
        "sources": [{"url": "https://example.com/source", "status": "ok", "text": text,
                     "chars": len(text), "text_sha256": hashlib.sha256(text.encode()).hexdigest()}],
    }
    store.write_artifact(job.id, "verification.json", verification)
    originality = store.read_artifact(job.id, "originality.json")
    originality["script_text_sha256"] = json_hash({"text": text})
    store.write_artifact(job.id, "originality.json", originality)
    for name, field, digest in (
        ("draft_qc.json", "inputs_sha256", json_hash({
            "script": script.model_dump(mode="json", exclude_none=True),
            "storyboard": store.read_artifact(job.id, "storyboard.json"),
        })),
        ("metadata.json", "script_sha256", digest),
    ):
        record = store.read_artifact(job.id, name)
        record[field] = digest
        store.write_artifact(job.id, name, record)
    return job


def test_live_gate_accepts_replayable_quote_checks(tmp_path):
    store = _store(tmp_path)
    job = _live_factual_job(store)
    gate = evaluate(store, job.id)
    assert gate.eligible, gate.blockers


def test_live_gate_rechecks_quote_against_saved_source(tmp_path):
    store = _store(tmp_path)
    job = _live_factual_job(store)
    verification = store.read_artifact(job.id, "verification.json")
    verification["checks"][0]["quote"] = "Kutipan ini tidak pernah terdapat dalam sumber"
    store.write_artifact(job.id, "verification.json", verification)
    gate = evaluate(store, job.id)
    assert not gate.eligible
    assert any(b.startswith("source_verification:") for b in gate.blockers)


def test_live_gate_rejects_stale_evidence_script_hash(tmp_path):
    store = _store(tmp_path)
    job = _live_factual_job(store)
    verification = store.read_artifact(job.id, "verification.json")
    verification["script_sha256"] = "a" * 64
    store.write_artifact(job.id, "verification.json", verification)
    gate = evaluate(store, job.id)
    assert not gate.eligible
    assert any(b.startswith("source_verification:") for b in gate.blockers)


@pytest.mark.parametrize("name,field", [("draft_qc.json", "inputs_sha256"), ("metadata.json", "script_sha256")])
def test_gate_rejects_stale_review_or_metadata(tmp_path, name, field):
    store = _store(tmp_path)
    job = _pending_job(store)
    data = store.read_artifact(job.id, name)
    data[field] = "a" * 64
    store.write_artifact(job.id, name, data)
    gate = evaluate(store, job.id)
    assert not gate.eligible
    assert any(b.startswith("editorial_review:" if name == "draft_qc.json" else "metadata:") for b in gate.blockers)


def test_gate_blocks_media_changed_after_qc(tmp_path):
    store = _store(tmp_path)
    job = _pending_job(store)
    with (store.artifact_root(job.id) / "output.mp4").open("ab") as output:
        output.write(b"changed after QC")
    gate = evaluate(store, job.id)
    assert not gate.eligible
    assert any(b.startswith("media_integrity:") for b in gate.blockers)


def test_gate_rejects_invalid_artifact_shape(tmp_path):
    store = _store(tmp_path)
    job = _pending_job(store)
    (store.artifact_root(job.id) / "qc.json").write_text('{"technical_pass": true}', encoding="utf-8")
    gate = evaluate(store, job.id)
    assert not gate.eligible
    assert any("qc.json" in b for b in gate.blockers)


def test_approval_refuses_a_stale_verdict(tmp_path):
    store = _store(tmp_path)
    job = _pending_job(store)
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    _only_approval_stages(runner)
    runner.run(job.id, stop_at=JobState.READY_FOR_APPROVAL)

    # Someone edits the artifact after the run; eligibility is re-read, not cached.
    broken = store.read_artifact(job.id, "verification.json")
    broken["status"] = "unsupported"
    store.write_artifact(job.id, "verification.json", broken)
    with pytest.raises(ApprovalRejected, match="source_verification"):
        approve(store, job.id, operator="koko")
    assert store.get(job.id).state is JobState.READY_FOR_APPROVAL


def test_runner_rejects_failed_editorial_review(tmp_path):
    store = _store(tmp_path)
    job = _pending_job(store, editorial_pass=False)
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    _only_approval_stages(runner)
    report = runner.run(job.id, stop_at=JobState.READY_FOR_APPROVAL)
    assert not report.ok
    assert report.final_state == "REJECTED"
    assert store.read_artifact(job.id, "editorial_qc.json")["overall"] == "fail"


def test_pipeline_does_not_rerun_operator_approved_job(tmp_path):
    store = _store(tmp_path)
    job = _pending_job(store)
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    _only_approval_stages(runner)
    assert runner.run(job.id, stop_at=JobState.READY_FOR_APPROVAL).ok
    approve(store, job.id, operator="koko")
    before = store.events(job.id)
    report = runner.run(job.id, stop_at=JobState.READY_FOR_APPROVAL)
    assert report.final_state == "APPROVED"
    assert report.blocked_reason
    assert store.events(job.id) == before


def test_approval_refuses_a_job_that_is_not_pending(tmp_path):
    store = _store(tmp_path)
    job = store.create(title="belum siap", state=JobState.TECHNICAL_QC)
    with pytest.raises(ApprovalRejected, match="not READY_FOR_APPROVAL"):
        approve(store, job.id, operator="koko")


def test_rejection_records_the_reason(tmp_path):
    store = _store(tmp_path)
    job = _pending_job(store)
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    _only_approval_stages(runner)
    runner.run(job.id, stop_at=JobState.READY_FOR_APPROVAL)

    reject(store, job.id, "judul menyesatkan", operator="koko")
    record = store.get(job.id)
    assert record.state is JobState.REJECTED
    assert record.payload["reject_reason"] == "judul menyesatkan"
    assert record.payload["rejected_by"] == "koko"
