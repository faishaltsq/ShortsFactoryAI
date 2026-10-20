"""Worker-owned lifecycle events and persisted liveness, not UI timers."""
from __future__ import annotations

import sqlite3
import threading
import uuid

from ..orchestration.jobstore import JobStore
from .events import safe_text
from .store import StudioEventStore

STAGE_AGENTS = {
    "IDEA_DISCOVERY": "ResearchAgent", "TOPIC_SELECTED": "TopicSelectionAgent",
    "SCRIPT_GENERATED": "ScriptAgent", "CREATIVE_REVIEW": "CreativeDirectorAgent",
    "STORYBOARD_READY": "StoryboardAgent", "ASSETS_READY": "AssetAgent",
    "AUDIO_READY": "AudioAgent", "RENDERING": "RenderAgent", "TECHNICAL_QC": "QualityAgent",
    "DRAFT_QC": "QualityAgent", "METADATA": "MetadataAgent",
}


class RunObserver:
    def __init__(self, store: JobStore, job_id: str, *, source: str) -> None:
        self.events = StudioEventStore(store.db_path)
        self.job_id, self.source, self.run_id = job_id, source, uuid.uuid4().hex
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._active: str | None = None

    def _emit(self, agent: str, event_type: str, status: str, description: str, *, stage: str | None = None,
              progress: float | None = None, model: str | None = None) -> None:
        self.events.emit(job_id=self.job_id, agent_id=agent, event_type=event_type, status=status,
                         description=description, stage=stage, progress=progress, model=model,
                         source=self.source, run_id=self.run_id)

    def start(self) -> None:
        self.events.begin_run(self.job_id, self.run_id)
        self._emit("FactoryOrchestrator", "run_started", "working", "Workflow berjalan di worker Python.")
        self._thread = threading.Thread(target=self._heartbeat, name="studio-worker-lease", daemon=True)
        self._thread.start()

    def _heartbeat(self) -> None:
        while not self._stop.wait(5):
            try:
                self.events.heartbeat(self.job_id, self.run_id)
            except sqlite3.Error:
                # A failing lease deliberately expires: the UI must not imply liveness.
                return

    def _model(self, agent: str) -> str | None:
        with self.events.connect() as conn:
            row = conn.execute("SELECT model FROM usage_log WHERE job_id=? AND agent=? ORDER BY id DESC LIMIT 1",
                               (self.job_id, agent)).fetchone()
        return safe_text(row[0], 120) if row else None

    def started(self, stage: str) -> None:
        self._active = stage
        self._emit(STAGE_AGENTS[stage], "stage_started", "working", f"Menjalankan {stage}.", stage=stage, progress=0)

    def completed(self, stage: str, *, reused: bool = False) -> None:
        self._emit(STAGE_AGENTS[stage], "artifact_reused" if reused else "stage_completed", "completed",
                   "Artefak lama diverifikasi dan digunakan kembali." if reused else "Artefak selesai dan tervalidasi.",
                   stage=stage, progress=100, model=self._model(STAGE_AGENTS[stage]))
        self._active = None

    def failed(self, *, blocked: bool = False, error_type: str = "Error") -> None:
        if self._active:
            stage = self._active
            self._emit(STAGE_AGENTS[stage], "stage_blocked" if blocked else "stage_failed", "blocked" if blocked else "failed",
                       f"{error_type}: {stage} {'terblokir' if blocked else 'gagal'}; lihat diagnostik lokal.", stage=stage)
            self._active = None

    def render_progress(self, progress) -> None:
        if self._active == "RENDERING":
            self._emit("RenderAgent", "render_progress", "working",
                       f"Remotion {progress.phase}: {progress.completed}/{progress.total} frame.",
                       stage="RENDERING", progress=progress.percent)

    def finish(self, state: str) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=6)
        try:
            status = "failed" if state == "FAILED" else "blocked" if state == "BLOCKED" else "waiting" if state == "CANCELLED" else "completed"
            kind = "run_failed" if status == "failed" else "run_blocked" if status in {"blocked", "waiting"} else "run_completed"
            self._emit("FactoryOrchestrator", kind, status, f"Worker berhenti pada state {state}.")
        finally:
            self.events.end_run(self.job_id, self.run_id)
