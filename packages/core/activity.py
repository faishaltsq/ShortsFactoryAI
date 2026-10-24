"""Durable observation of real pipeline work, independent of UI persona data."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from .orchestration import JobStore

AgentId = Literal[
    "FactoryOrchestrator", "ResearchAgent", "TopicSelectionAgent", "ScriptAgent",
    "CreativeDirectorAgent", "StoryboardAgent", "AssetAgent", "AudioAgent",
    "RenderAgent", "QualityAgent", "MetadataAgent",
]
Phase = Literal["running", "validating", "ready", "done", "failed", "blocked", "stopped", "interrupted"]

# Which agent owns each pipeline stage. This is the single source of truth; the
# lifecycle observer imports it rather than keeping its own copy.
# TECHNICAL_QC is owned by RenderAgent because the same process performs the media
# checks. EDITORIAL_QC is a deterministic gate over written artifacts, so it belongs
# to QualityAgent, not MetadataAgent.
STAGE_AGENTS: dict[str, AgentId] = {
    "IDEA_DISCOVERY": "ResearchAgent",
    "TOPIC_SELECTED": "TopicSelectionAgent",
    "SCRIPT_GENERATED": "ScriptAgent",
    "CREATIVE_REVIEW": "CreativeDirectorAgent",
    "STORYBOARD_READY": "StoryboardAgent",
    "ASSETS_READY": "AssetAgent",
    "AUDIO_READY": "AudioAgent",
    "RENDERING": "RenderAgent",
    "TECHNICAL_QC": "RenderAgent",
    "DRAFT_QC": "QualityAgent",
    "METADATA": "MetadataAgent",
    "THUMBNAIL": "RenderAgent",  # Remotion still rendered from the metadata concept
    "EDITORIAL_QC": "QualityAgent",
    "READY_FOR_APPROVAL": "FactoryOrchestrator",
}


class ActivitySnapshot(BaseModel):
    """What the pipeline last reported doing. Written by the runner, never inferred."""

    model_config = ConfigDict(extra="forbid")

    token: str = Field(pattern=r"^[0-9a-f]{32}$")
    agent: AgentId = "FactoryOrchestrator"
    stage: str = Field(default="PREFLIGHT", min_length=1, max_length=64)
    phase: Phase = "running"
    updated_at: str
    completed: dict[AgentId, str] = Field(default_factory=dict)


class ActivityReporter:
    """Writes one snapshot per stage transition; never advances job state."""

    def __init__(self, store: JobStore, job_id: str, token: str) -> None:
        self.store, self.job_id, self.token = store, job_id, token
        self.value: dict = {"token": token, "completed": {}}

    def _write(self, **changes) -> None:
        candidate = {**self.value, **changes, "updated_at": datetime.now(timezone.utc).isoformat()}
        validated = ActivitySnapshot.model_validate(candidate).model_dump(mode="json")
        self.store.set_activity(self.job_id, validated)
        self.value = validated

    def begin(self, agent: str, stage: str, reused: bool = False) -> None:
        self._write(agent=agent, stage=stage, phase="validating" if reused else "running")

    def complete(self, agent: str, artifact: str) -> None:
        self._write(completed={**self.value["completed"], agent: artifact}, phase="ready")

    def finish(self, phase: Phase) -> None:
        self._write(phase=phase)
