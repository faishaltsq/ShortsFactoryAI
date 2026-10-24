"""Deterministic editorial approval gate.

A job becomes eligible for the operator only when every artifact that has to be
true is true: technical QC passed, the LLM editorial review did not fail, the
script's claims are not contradicted by its sources, the originality gate holds,
and the render, audio, assets and metadata artifacts all exist and validate.
Nothing here asks a model for an opinion, and nothing here approves anything:
the operator's explicit call is a separate step.
"""
from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, field

from .artifacts import validate_artifact
from .media.process import checked_path, json_hash
from .orchestration import JobState
from .orchestration.jobstore import JobStore

APPROVAL_INPUTS = (
    "script.json", "storyboard.json", "verification.json", "originality.json", "draft_qc.json",
    "qc.json", "metadata.json", "assets.json", "audio.json", "render.json",
)


def _validated_input(store: JobStore, job_id: str, name: str) -> dict:
    store.artifact_root(job_id)
    checked_path(store.artifacts_root, f"{job_id}/{name}")
    return validate_artifact(name, store.read_artifact(job_id, name))


def approval_fingerprint(store: JobStore, job_id: str) -> str:
    """Bind an operator decision to canonical inputs, not mutable job status."""
    data = {name: _validated_input(store, job_id, name) for name in APPROVAL_INPUTS}
    for name in ("thumbnail.json", "mix.json"):
        if (store.artifact_root(job_id) / name).is_file():
            data[name] = _validated_input(store, job_id, name)
    return json_hash(data)


class ApprovalRejected(ValueError):
    """The job is not eligible; the reason is a list of concrete blockers."""


@dataclass
class ApprovalGate:
    eligible: bool
    blockers: list[str] = field(default_factory=list)
    checks: list[dict[str, object]] = field(default_factory=list)
    requires_operator_approval: bool = True
    checked_at: str = ""
    inputs_sha256: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "eligible": self.eligible,
            "blockers": self.blockers,
            "checks": self.checks,
            "requires_operator_approval": self.requires_operator_approval,
            "checked_at": self.checked_at,
            "inputs_sha256": self.inputs_sha256,
        }


def _check(name: str, passed: bool, detail: str) -> dict[str, object]:
    return {"name": name, "pass": passed, "detail": detail}


def _factual_sources_verified(script: dict, verification: dict) -> bool:
    from .research.retrieval import FetchedSource
    from .research.verification import Claim, build_report
    from .schemas import VerificationStatus

    if (verification.get("status") != "supported" or verification.get("retrieval") != "live" or
            verification.get("script_sha256") != json_hash(script)):
        return False
    cited = {source["url"] for source in script.get("sources", []) if source.get("url")}
    sources = []
    for entry in verification.get("sources", []):
        text = entry.get("text", "")
        if (entry["status"] == "ok" and entry["url"] in cited and text and
                entry.get("text_sha256") == hashlib.sha256(text.encode("utf-8")).hexdigest() and
                entry.get("chars") == len(text)):
            sources.append(FetchedSource(url=entry["url"], status="ok", text=text))
    claims = [Claim(statement=c["statement"], quote=c["quote"], source_url=c["source_url"])
              for c in verification.get("checks", [])]
    report = build_report(claims, sources)
    return bool(claims) and bool(sources) and report.status is VerificationStatus.supported


def review_fingerprint(script: dict, storyboard: dict) -> str:
    """Bind a draft review to what the reviewer is allowed to judge.

    Timing is excluded on purpose. The reviewer prompt forbids judging duration
    or subtitle sync, and AudioAgent rewrites every duration from measured
    narration. Hashing the timed fields would invalidate a correct review and
    force a second pass that re-fails on numbers the reviewer was told to ignore.
    """
    content = {**storyboard}
    content["scenes"] = [
        {**scene,
         "text": [{k: v for k, v in element.items() if k not in {"inFrame", "outFrame"}}
                  for element in scene.get("text") or []]}
        for scene in storyboard.get("scenes", [])
    ]
    for scene in content["scenes"]:
        scene.pop("startFrame", None)
        scene.pop("durationInFrames", None)
    content.pop("subtitles", None)
    content.pop("narration", None)
    return json_hash({"script": script, "storyboard": content})


def evaluate(store: JobStore, job_id: str) -> ApprovalGate:
    """Read every gate input from disk; missing artifacts are blockers, not crashes."""
    blockers: list[str] = []
    checks: list[dict[str, object]] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append(_check(name, passed, detail))
        if not passed:
            blockers.append(f"{name}: {detail}")

    data: dict[str, dict] = {}
    for name in APPROVAL_INPUTS:
        try:
            data[name] = _validated_input(store, job_id, name)
        except (OSError, ValueError, KeyError):
            add(f"artifact:{name}", False, "missing or invalid artifact")
            data[name] = {}

    script, storyboard = data["script.json"], data["storyboard.json"]
    verification, originality = data["verification.json"], data["originality.json"]
    draft, qc, render = data["draft_qc.json"], data["qc.json"], data["render.json"]
    metadata, assets, audio = data["metadata.json"], data["assets.json"], data["audio.json"]
    is_mock = store.get(job_id).payload.get("provider_mode") == "mock"
    checks_pass = bool(qc.get("checks")) and all(qc.get("checks", {}).values())
    add("technical_qc", qc.get("technical_pass") is True and checks_pass and bool(render) and
        qc.get("render_sha256") == render.get("sha256"), "QC must pass and bind to this render")
    editorial = draft.get("editorial", {})
    review_hash = review_fingerprint(script, storyboard)
    add("editorial_review", editorial.get("pass") is True and draft.get("overall") in {"pass", "warn"} and
        draft.get("inputs_sha256") == review_hash, f"draft review overall={draft.get('overall', 'missing')}; inputs must match")
    status = verification.get("status")
    if script.get("content_type") == "fictional":
        verified = status == "fictional" and verification.get("retrieval") == "not_applicable"
    elif is_mock:
        verified = status in {"supported", "needs_review"}
    else:
        verified = _factual_sources_verified(script, verification)
    add("source_verification", bool(verified), f"verification status {status or 'missing'}; mock={is_mock}")
    verdict = originality.get("verdict")
    original = (bool(originality) and verdict == "original" and
                originality.get("max_similarity", 1) < originality.get("threshold", 0))
    if is_mock and originality and not originality.get("enforced"):
        original = True
    elif not is_mock:
        from .schemas import Script
        text_hash = json_hash({"text": Script.model_validate(script).full_text}) if script else ""
        original = (original and originality.get("enforced") is True and
                    originality.get("script_text_sha256") == text_hash)
    add("originality", original, f"verdict {verdict or 'missing'}; enforced={originality.get('enforced')}")
    add("metadata", bool(metadata.get("title", "").strip() and metadata.get("description", "").strip()) and
        metadata.get("script_sha256") == json_hash(script), "title/description must bind to current script")
    add("assets", bool(assets.get("templates")), "templates must resolve from the local manifest")
    add("audio", bool(audio.get("narration_path")), "measured narration required")
    add("render", bool(render.get("output_path")), "render contract required")
    try:
        from .media.audio import verify_audio
        from .media.contracts import AudioArtifact, RenderArtifact
        from .media.render import verify_render
        from .schemas import Script, Storyboard

        root = store.artifact_root(job_id).resolve()
        if not root.is_relative_to(store.artifacts_root.resolve()):
            raise ValueError("job directory escaped artifact root")
        if not script or not storyboard or not audio or not render:
            raise ValueError("required media inputs missing")
        audio_model = AudioArtifact.model_validate(audio)
        board_model = Storyboard.model_validate(storyboard)
        verify_audio(audio_model, Script.model_validate(script), board_model, root)
        verify_render(RenderArtifact.model_validate(render), board_model, audio_model, root)
        add("media_integrity", True, "physical files, dependency hashes and FFprobe validated")
    except (OSError, ValueError, KeyError, RuntimeError):
        add("media_integrity", False, "media missing, corrupt, stale or outside job directory")

    headline = (metadata.get("thumbnail") or {}).get("text")
    if isinstance(headline, str) and headline.strip():
        try:
            from .media.contracts import AssetManifest, ThumbnailArtifact
            from .media.thumbnail import verify_thumbnail
            from .schemas import Storyboard

            root = store.artifact_root(job_id).resolve()
            if not root.is_relative_to(store.artifacts_root.resolve()):
                raise ValueError("job directory escaped artifact root")
            thumb = _validated_input(store, job_id, "thumbnail.json")
            verify_thumbnail(ThumbnailArtifact.model_validate(thumb), Storyboard.model_validate(storyboard),
                             metadata, root, assets=AssetManifest.model_validate(assets))
            add("thumbnail", True, f"validated 1080x1920 PNG for '{headline.strip()}'")
        except (OSError, ValueError, KeyError, RuntimeError):
            add("thumbnail", False, "thumbnail missing, corrupt or stale against metadata")

    return ApprovalGate(
        eligible=not blockers,
        blockers=blockers,
        checks=checks,
        checked_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        inputs_sha256=approval_fingerprint(store, job_id) if not blockers else "",
    )


def require_eligible(store: JobStore, job_id: str) -> ApprovalGate:
    gate = evaluate(store, job_id)
    if not gate.eligible:
        raise ApprovalRejected("; ".join(gate.blockers))
    return gate


def operator_name(explicit: str | None = None) -> str:
    return explicit or os.environ.get("SHORTS_OPERATOR", "operator")


def stamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def pending(store: JobStore) -> list[tuple[str, str, ApprovalGate]]:
    """Jobs waiting for approval with a freshly re-read verdict, id-first."""
    return [
        (record.id, record.title, evaluate(store, record.id))
        for record in store.list(state=JobState.READY_FOR_APPROVAL)
    ]


def approve(store: JobStore, job_id: str, operator: str | None = None) -> ApprovalGate:
    """Approve a pending job after re-reading its gate from disk.

    A stale verdict is never trusted: eligibility is recomputed at the moment of
    the decision, so artifacts edited after the run cannot ride through.
    """
    who = operator_name(operator)
    record = store.get(job_id)
    if record.state is not JobState.READY_FOR_APPROVAL:
        raise ApprovalRejected(f"job is {record.state.value}, not READY_FOR_APPROVAL")
    gate = evaluate(store, job_id)
    if not gate.eligible:
        raise ApprovalRejected("; ".join(gate.blockers))
    try:
        recorded = _validated_input(store, job_id, "approval.json")
        editorial = _validated_input(store, job_id, "editorial_qc.json")
    except (OSError, ValueError, KeyError) as exc:
        raise ApprovalRejected("approval artifacts missing or invalid") from exc
    if (not recorded["eligible"] or recorded.get("inputs_sha256") != gate.inputs_sha256 or
            editorial["overall"] != "pass" or editorial.get("inputs_sha256") != gate.inputs_sha256):
        raise ApprovalRejected("approval verdict is stale; rerun editorial gate before approving")
    store.transition(
        job_id,
        JobState.APPROVED,
        detail=f"approved by {who}",
        payload_patch={"approved_by": who, "approved_at": stamp(), "approved_inputs_sha256": gate.inputs_sha256},
    )
    return gate


def reject(store: JobStore, job_id: str, reason: str, operator: str | None = None) -> JobState:
    """Reject a pending job; the reason is recorded on the job payload."""
    who = operator_name(operator)
    record = store.get(job_id)
    if record.state is not JobState.READY_FOR_APPROVAL:
        raise ApprovalRejected(f"job is {record.state.value}, not READY_FOR_APPROVAL")
    store.transition(
        job_id,
        JobState.REJECTED,
        detail=f"rejected by {who}: {reason}",
        payload_patch={"rejected_by": who, "rejected_at": stamp(), "reject_reason": reason},
    )
    return JobState.REJECTED
