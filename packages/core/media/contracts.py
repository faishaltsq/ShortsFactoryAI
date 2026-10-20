"""Validated disk contracts for deterministic media stages."""
from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, Field
from ..schemas import SubtitleCue


class AssetManifest(BaseModel):
    mode: Literal["project-generated-vectors"] = "project-generated-vectors"
    templates: list[str] = Field(min_length=1)
    assets: list[str] = Field(default_factory=list)
    license: Literal["project-original"] = "project-original"


class AudioSegment(BaseModel):
    scene_id: str
    path: str
    raw_duration_ms: float = Field(gt=0)
    duration_frames: int = Field(ge=30)
    sha256: str = Field(pattern="^[0-9a-f]{64}$")


class AudioArtifact(BaseModel):
    engine: Literal["edge-tts"] = "edge-tts"
    voice: str
    rate: str
    narration_path: str
    duration_ms: float = Field(gt=0)
    sha256: str = Field(pattern="^[0-9a-f]{64}$")
    script_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    storyboard_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    fps: int = Field(gt=0)
    total_frames: int = Field(gt=0)
    segments: list[AudioSegment] = Field(min_length=1)
    cues: list[SubtitleCue] = Field(min_length=1)
    timing_source: Literal["edge-tts-word-boundaries+ffprobe"] = "edge-tts-word-boundaries+ffprobe"


class RenderArtifact(BaseModel):
    output_path: str
    sha256: str = Field(pattern="^[0-9a-f]{64}$")
    storyboard_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    audio_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    duration_ms: float = Field(gt=0)
    frame_count: int = Field(gt=0)
    probe: dict[str, Any]
    composition: Literal["Short"] = "Short"


class TechnicalQCArtifact(BaseModel):
    technical_pass: bool
    editorial_pass: Literal[False] = False
    factual_pass: Literal[False] = False
    checks: dict[str, bool]
    notes: list[str]
    render_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    audio_stats: dict[str, float]
