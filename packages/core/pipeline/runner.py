"""Persisted production pipeline; fixture content is unreachable in live mode."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from ..activity import ActivityReporter, STAGE_AGENTS
from ..agents import CreativeDirectorAgent, MetadataAgent, QualityAgent, ResearchAgent, ScriptAgent, StoryboardAgent, TopicSelectionAgent
from ..artifacts import validate_artifact
from ..config import Settings, get_settings
from ..orchestration import JobState, JobStore
from ..orchestration.states import PIPELINE_ORDER, can_transition
from ..providers import BudgetExceededError, ProviderError, build_router
from ..schemas import Genre, ResearchResult, Script, Storyboard, TopicCandidate

DEFAULT_GENRES = list(Genre)


@dataclass
class StageReport:
    state: str
    ok: bool
    artifact: str | None = None
    elapsed_ms: int = 0
    detail: str = ""


@dataclass
class PipelineReport:
    job_id: str
    stages: list[StageReport] = field(default_factory=list)
    final_state: str = ""
    blocked_reason: str | None = None

    @property
    def ok(self) -> bool:
        return (not self.blocked_reason and self.final_state not in {"FAILED", "BLOCKED", "CANCELLED", "REJECTED"}
                and bool(self.stages) and all(s.ok for s in self.stages))

    def as_dict(self) -> dict[str, Any]:
        return {"job_id": self.job_id, "final_state": self.final_state, "ok": self.ok,
                "blocked_reason": self.blocked_reason, "stages": [s.__dict__ for s in self.stages]}


class PipelineRunner:
    def __init__(self, store: JobStore, settings: Settings | None = None, *, force_mock: bool = False) -> None:
        self.store = store
        self.settings = settings or get_settings()
        self.force_mock = force_mock
        self.router = build_router(self.settings, db_path=store.db_path, mock_only=force_mock)
        self.router.allow_mock_default = force_mock
        if not force_mock:
            self.router.worker_chain = [p for p in self.router.worker_chain if p.name != "mock"]
            self.router.strategist_chain = [p for p in self.router.strategist_chain if p.name != "mock"]

    def _stages(self):
        return [
            (JobState.IDEA_DISCOVERY, "research.json", self._research),
            (JobState.TOPIC_SELECTED, "topic.json", self._topic),
            (JobState.SCRIPT_GENERATED, "script.json", self._script),
            (JobState.CREATIVE_REVIEW, "review.json", self._creative),
            (JobState.STORYBOARD_READY, "storyboard.json", self._storyboard),
            (JobState.ASSETS_READY, "assets.json", self._assets),
            (JobState.AUDIO_READY, "audio.json", self._audio),
            (JobState.RENDERING, "render.json", self._render),
            (JobState.TECHNICAL_QC, "qc.json", self._technical_qc),
        ]

    def _read(self, job_id: str, name: str) -> dict[str, Any]:
        data = validate_artifact(name, self.store.read_artifact(job_id, name))
        if name == "audio.json":
            from ..media.audio import verify_audio
            from ..media.contracts import AudioArtifact
            verify_audio(AudioArtifact.model_validate(data), self._script_model(job_id), self._storyboard_model(job_id), self.store.artifact_root(job_id))
        elif name == "render.json":
            from ..media.contracts import AudioArtifact, RenderArtifact
            from ..media.render import verify_render
            audio = AudioArtifact.model_validate(self._read(job_id, "audio.json"))
            verify_render(RenderArtifact.model_validate(data), self._storyboard_model(job_id), audio, self.store.artifact_root(job_id))
        elif name == "qc.json":
            if not data["technical_pass"]:
                raise ValueError("technical QC failed: " + "; ".join(data["notes"]))
            if data["render_sha256"] != self._read(job_id, "render.json")["sha256"]:
                raise ValueError("QC report no longer matches render")
        return data

    def _script_model(self, job_id: str) -> Script:
        return Script.model_validate(self._read(job_id, "script.json"))

    def _storyboard_model(self, job_id: str) -> Storyboard:
        return Storyboard.model_validate(self._read(job_id, "storyboard.json"))

    def _research(self, job_id: str) -> None:
        # Judul yang sudah pernah dibuat dikirim sebagai larangan supaya
        # ResearchAgent tidak mengusulkan ide yang sama berulang kali. Tanpa
        # ini, produksi otomatis menghasilkan video yang mirip terus.
        from ..scheduler import avoid_titles

        record = self.store.get(job_id)
        # Judul yang dibawa payload (dari scheduler) dipakai lebih dulu: itu
        # hasil keputusan jadwal, bukan tebakan.
        banned = list(record.payload.get("avoid_titles") or [])
        if not banned:
            banned = avoid_titles(self.store.list(limit=500))
        banned = [t for t in banned if t and t != record.title][:60]
        result = ResearchAgent(self.router).run(
            genres=DEFAULT_GENRES,
            avoid_titles=banned,
            day_focus=record.title,
        )
        if not result.candidates:
            raise ValueError("research returned zero candidates")
        self.store.write_artifact(job_id, "research.json", result.model_dump(mode="json"))

    def _topic(self, job_id: str) -> None:
        research = ResearchResult.model_validate(self._read(job_id, "research.json"))
        agent = TopicSelectionAgent(self.router)
        selection = agent.run(research.candidates, recent_genres=[])
        topic = agent.resolve(research.candidates, selection)
        self.store.write_artifact(job_id, "topic.json", {
            "selection": selection.model_dump(mode="json"), "topic": topic.model_dump(mode="json")})

    def _script(self, job_id: str) -> None:
        topic = TopicCandidate.model_validate(self._read(job_id, "topic.json")["topic"])
        script = ScriptAgent(self.router).run(topic)
        self.store.write_artifact(job_id, "script.json", script.model_dump(mode="json"))

    def _creative(self, job_id: str) -> None:
        script = self._script_model(job_id)
        agent = CreativeDirectorAgent(self.router)
        review = agent.run(script)
        if review.verdict == "reject":
            raise ValueError("creative review rejected script")
        revised = agent.apply(script, review)
        self.store.write_artifact(job_id, "review.json", {
            "review": review.model_dump(mode="json"), "script": revised.model_dump(mode="json")})
        self.store.write_artifact(job_id, "script.json", revised.model_dump(mode="json"))

    def _storyboard(self, job_id: str) -> None:
        p = self.settings.production
        storyboard = StoryboardAgent(self.router, fps=p.fps, width=p.width, height=p.height).run(self._script_model(job_id))
        if self.force_mock:
            storyboard.watermark = {"text": "SHORTS FACTORY · DEMO / MOCK SCRIPT"}
        self.store.write_artifact(job_id, "storyboard.json", storyboard.model_dump(mode="json"))

    def _cancelled(self, job_id: str) -> bool:
        return self.store.get(job_id).state is JobState.CANCELLED

    def _assets(self, job_id: str) -> None:
        from ..media.assets import AssetAgent
        manifest = AssetAgent().run(self._storyboard_model(job_id))
        self.store.write_artifact(job_id, "assets.json", manifest.model_dump(mode="json"))

    def _audio(self, job_id: str) -> None:
        from ..media.audio import AudioAgent
        prod = self.settings.production
        timed, audio = AudioAgent(voice=prod.tts_voice, rate=prod.tts_rate).run(
            self._script_model(job_id), self._storyboard_model(job_id), self.store.artifact_root(job_id),
            cancelled=lambda: self._cancelled(job_id))
        self.store.write_artifact(job_id, "storyboard.json", timed.model_dump(mode="json", exclude_none=True))
        self.store.write_artifact(job_id, "audio.json", audio.model_dump(mode="json"))

    def _render(self, job_id: str) -> None:
        from ..media.contracts import AudioArtifact
        from ..media.render import RenderAgent
        audio = AudioArtifact.model_validate(self._read(job_id, "audio.json"))
        render = RenderAgent().run(self._script_model(job_id), self._storyboard_model(job_id), audio,
                                   self.store.artifact_root(job_id), cancelled=lambda: self._cancelled(job_id))
        self.store.write_artifact(job_id, "render.json", render.model_dump(mode="json"))

    def _technical_qc(self, job_id: str) -> None:
        from ..media.contracts import AudioArtifact, RenderArtifact
        from ..media.render import technical_quality
        audio = AudioArtifact.model_validate(self._read(job_id, "audio.json"))
        render = RenderArtifact.model_validate(self._read(job_id, "render.json"))
        qc = technical_quality(self._storyboard_model(job_id), audio, render, self.store.artifact_root(job_id),
                               cancelled=lambda: self._cancelled(job_id))
        self.store.write_artifact(job_id, "qc.json", qc.model_dump(mode="json"))

    def _draft_checks(self, job_id: str, report: PipelineReport, activity: ActivityReporter) -> None:
        script, storyboard = self._script_model(job_id), self._storyboard_model(job_id)
        root = self.store.artifact_root(job_id)
        reused = (root / "draft_qc.json").exists()
        activity.begin("QualityAgent", "DRAFT_QC", reused=reused)
        if not reused:
            review = QualityAgent(self.router).run(storyboard, script)
            self.store.write_artifact(job_id, "draft_qc.json", review)
        review = self._read(job_id, "draft_qc.json")
        passed = review["overall"] != "fail" and review["editorial"]["pass"]
        report.stages.append(StageReport("DRAFT_QC", passed, "draft_qc.json",
                                        detail="draft only; no rendered media verification"))
        if not passed:
            raise ValueError("draft editorial review failed")
        activity.complete("QualityAgent", "draft_qc.json")
        reused = (root / "metadata.json").exists()
        activity.begin("MetadataAgent", "METADATA", reused=reused)
        if not reused:
            meta = MetadataAgent(self.router).run(script)
            self.store.write_artifact(job_id, "metadata.json", meta.model_dump(mode="json"))
        self._read(job_id, "metadata.json")
        activity.complete("MetadataAgent", "metadata.json")
        report.stages.append(StageReport("METADATA", True, "metadata.json"))

    def run(self, job_id: str, *, stop_at: JobState = JobState.STORYBOARD_READY,
            cancelled=None, activity_token: str | None = None) -> PipelineReport:
        stages = self._stages()
        if stop_at not in {state for state, _, _ in stages}:
            raise ValueError(f"unsupported stop: {stop_at.value}")
        report = PipelineReport(job_id)
        record = self.store.get(job_id)
        if record.state in {JobState.CANCELLED, JobState.PUBLISHED, JobState.REJECTED}:
            report.final_state, report.blocked_reason = record.state.value, "terminal job cannot be resumed"
            return report
        if not self.store.try_lock(job_id):
            report.final_state, report.blocked_reason = record.state.value, "job is already running (lock held)"
            return report
        self.router.job_id = job_id
        current_stage = "PREFLIGHT"
        activity = ActivityReporter(self.store, job_id, activity_token or uuid4().hex)
        outcome = "interrupted"
        try:
            activity.begin("FactoryOrchestrator", "PREFLIGHT")
            mode = "mock" if self.force_mock else "live"
            prior_mode = record.payload.get("provider_mode")
            if prior_mode and prior_mode != mode:
                raise ValueError("provider mode cannot change for an existing job")
            if not prior_mode:
                if (self.store.artifact_root(job_id) / "research.json").exists():
                    raise ValueError("legacy job lacks provider provenance; start a new job")
                self.store.transition(job_id, record.state, payload_patch={"provider_mode": mode}, detail="provider mode set")
            if record.state in {JobState.FAILED, JobState.BLOCKED}:
                self.store.transition(job_id, JobState.IDEA_DISCOVERY, detail="resume from validated artifacts")
            for state, artifact, run_stage in stages:
                current_stage = state.value
                if self.store.get(job_id).state is JobState.CANCELLED:
                    report.blocked_reason = "cancelled by operator"
                    break
                if cancelled is not None and callable(cancelled) and cancelled():
                    report.blocked_reason = "dibatalkan operator"
                    break
                started = time.perf_counter()
                reused = (self.store.artifact_root(job_id) / artifact).exists()
                activity.begin(STAGE_AGENTS[state.value], state.value, reused=reused)
                if reused:
                    data = self._read(job_id, artifact)
                    if artifact == "review.json" and data["review"]["verdict"] == "reject":
                        raise ValueError("stored creative review rejected script")
                else:
                    if state is JobState.RENDERING and self.store.get(job_id).state is JobState.AUDIO_READY:
                        self.store.transition(job_id, state, detail="render started under exclusive job lock")
                    run_stage(job_id)
                    self._read(job_id, artifact)
                current = self.store.get(job_id).state
                if state is not JobState.IDEA_DISCOVERY and current is not state:
                    if can_transition(current, state):
                        self.store.transition(job_id, state, detail=f"{artifact} {'reused' if reused else 'validated'}")
                    elif current not in PIPELINE_ORDER or PIPELINE_ORDER.index(current) < PIPELINE_ORDER.index(state):
                        raise ValueError(f"cannot advance from {current.value} to {state.value}")
                # Only after _read and legal state advancement: an artifact that
                # failed validation never counts as this agent's completed work.
                activity.complete(STAGE_AGENTS[state.value], artifact)
                report.stages.append(StageReport(state.value, True, artifact, int((time.perf_counter() - started) * 1000),
                                                "reused existing artifact" if reused else "; ".join(self.router.last_notes)))
                if state is stop_at:
                    break
            if stop_at is JobState.STORYBOARD_READY and not report.blocked_reason:
                current_stage = "DRAFT_CHECKS"
                self._draft_checks(job_id, report, activity)
            outcome = "stopped" if report.blocked_reason else "done"
        except BudgetExceededError as exc:
            outcome = "blocked"
            current = self.store.get(job_id).state
            if can_transition(current, JobState.BLOCKED):
                self.store.transition(job_id, JobState.BLOCKED, detail=str(exc))
            report.blocked_reason = str(exc)
            report.stages.append(StageReport(current_stage, False, detail=str(exc)))
        except (ProviderError, ValueError, KeyError, OSError, RuntimeError) as exc:
            outcome = "failed"
            current = self.store.get(job_id).state
            detail = f"{type(exc).__name__}: {str(exc)[:400]}"
            if can_transition(current, JobState.FAILED):
                self.store.transition(job_id, JobState.FAILED, error=detail)
            report.stages.append(StageReport(current_stage, False, detail=detail))
        finally:
            try:
                activity.finish(outcome)
            finally:
                self.store.unlock(job_id)
        report.final_state = self.store.get(job_id).state.value
        return report


def run_once(title: str, *, force_mock: bool = True, stop_at: JobState = JobState.STORYBOARD_READY) -> PipelineReport:
    from ..config import JOBS_DIR
    settings = get_settings()
    store = JobStore(settings.db_path, JOBS_DIR)
    job = store.create(title=title)
    return PipelineRunner(store, settings, force_mock=force_mock).run(job.id, stop_at=stop_at)
