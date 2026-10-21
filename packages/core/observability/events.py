"""Typed, credential-safe metadata for the local production observer."""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

AGENT_IDS = (
    "FactoryOrchestrator", "ResearchAgent", "TopicSelectionAgent", "ScriptAgent",
    "CreativeDirectorAgent", "StoryboardAgent", "AssetAgent", "AudioAgent",
    "RenderAgent", "QualityAgent", "MetadataAgent", "PublishAgent",
)
AgentId = Literal[
    "FactoryOrchestrator", "ResearchAgent", "TopicSelectionAgent", "ScriptAgent",
    "CreativeDirectorAgent", "StoryboardAgent", "AssetAgent", "AudioAgent",
    "RenderAgent", "QualityAgent", "MetadataAgent", "PublishAgent",
]
AgentStatus = Literal["idle", "working", "waiting", "blocked", "completed", "failed"]
EventSource = Literal["production", "mock", "demo_fixture"]
EventType = Literal[
    "stage_started", "stage_completed", "stage_failed", "stage_blocked",
    "artifact_reused", "render_progress", "run_started", "run_completed",
    "run_failed", "run_blocked", "job_waiting",
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def safe_text(value: str, limit: int = 240) -> str:
    text = str(value)
    for name, secret in os.environ.items():
        if len(secret) >= 4 and re.search(r"(?:KEY|TOKEN|SECRET|PASSWORD|COOKIE|AUTHORIZATION)", name, re.I):
            text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"(?i)\bBearer\s+[^\s,;]+", "Bearer [REDACTED]", text)
    text = re.sub(r"(?i)\b(?:api[_-]?key|token|secret|password|authorization)\s*[:=]\s*[^\s,;]+",
                  "credential=[REDACTED]", text)
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{12,}\b", "[REDACTED]", text)
    text = re.sub(r"[\x00-\x1f\x7f<>]", " ", text)
    return " ".join(text.split())[:limit]


class StudioEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    event_id: int = Field(ge=1)
    job_id: str = Field(pattern=r"^[0-9a-f]{16}$")
    agent_id: AgentId
    event_type: EventType
    status: AgentStatus
    timestamp: AwareDatetime = Field(default_factory=utc_now)
    description: str = Field(max_length=240)
    progress: float | None = Field(default=None, ge=0, le=100)
    model: str | None = Field(default=None, max_length=120)
    stage: str | None = Field(default=None, pattern=r"^[A-Z_]{1,40}$")
    run_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    source: EventSource = "production"

    @field_validator("description", "model", mode="before")
    @classmethod
    def redact_metadata(cls, value: str | None) -> str | None:
        return safe_text(value, 120 if cls.__name__ == "ModelName" else 240) if value is not None else None
