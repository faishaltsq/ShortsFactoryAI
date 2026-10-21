"""Validated disk contracts for deterministic media stages."""
from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from ..schemas import SubtitleCue


class LicensedAsset(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
    path: str = Field(min_length=1)
    kind: Literal["image", "music", "sfx"]
    license: str = Field(min_length=1)
    attribution: str = Field(min_length=1)
    source: str = Field(min_length=1)
    sha256: str = Field(pattern="^[0-9a-f]{64}$")
    license_file: str | None = None
    license_sha256: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def explicit_license(self):
        if self.license not in {"project-original", "CC0-1.0", "CC-BY-4.0", "CC-BY-SA-4.0"}:
            if not self.license.startswith("LicenseRef-") or not self.license_file or not self.license_sha256:
                raise ValueError("custom license requires LicenseRef- identifier and a hashed local license_file")
        return self


class LocalAssetLibrary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assets: list[LicensedAsset] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique_ids(self):
        if len({asset.id for asset in self.assets}) != len(self.assets):
            raise ValueError("asset ids must be unique")
        return self


class ResolvedAsset(LicensedAsset):
    staged_path: str


class AssetManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["project-generated-vectors", "licensed-local"] = "project-generated-vectors"
    templates: list[str] = Field(min_length=1)
    assets: list[ResolvedAsset] = Field(default_factory=list)
    license: Literal["project-original", "per-asset"] = "project-original"
    library_root: str | None = None
    manifest_path: str | None = None
    manifest_sha256: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")
    dependencies_sha256: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def local_provenance(self):
        if self.mode == "licensed-local":
            if not self.assets or not all([self.library_root, self.manifest_path, self.manifest_sha256, self.dependencies_sha256]):
                raise ValueError("licensed local assets require source manifest provenance")
            if self.license != "per-asset":
                raise ValueError("licensed local assets require per-asset license data")
        elif self.assets or self.library_root or self.manifest_path or self.manifest_sha256:
            raise ValueError("vector-only manifest must not contain local assets")
        return self


class AudioSegment(BaseModel):
    scene_id: str
    path: str
    raw_duration_ms: float = Field(gt=0)
    duration_frames: int = Field(ge=30)
    sha256: str = Field(pattern="^[0-9a-f]{64}$")


class AnchoredSFX(BaseModel):
    asset_id: str
    scene_id: str
    scene_frame: int = Field(ge=0)
    absolute_frame: int = Field(ge=0)
    volume: float = Field(ge=0, le=1)


class AudioMixArtifact(BaseModel):
    input_narration_path: str
    input_narration_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    assets_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    source_manifest_sha256: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")
    output_path: str
    sha256: str = Field(pattern="^[0-9a-f]{64}$")
    duration_ms: float = Field(gt=0)
    target_lufs: Literal[-16] = -16
    integrated_lufs: float = Field(allow_inf_nan=False)
    true_peak_dbtp: float = Field(le=-1, allow_inf_nan=False)
    ducking: Literal["sidechaincompress", "not-applicable"]
    sfx: list[AnchoredSFX] = Field(default_factory=list)
    filter_sha256: str = Field(pattern="^[0-9a-f]{64}$")


class AudioArtifact(BaseModel):
    assets_sha256: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")
    mix: AudioMixArtifact | None = None
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


class ThumbnailArtifact(BaseModel):
    output_path: str
    sha256: str = Field(pattern="^[0-9a-f]{64}$")
    width: Literal[1080] = 1080
    height: Literal[1920] = 1920
    format: Literal["png"] = "png"
    storyboard_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    metadata_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    assets_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    scene_id: str
    frame: int = Field(ge=0)
    composition: Literal["Thumbnail"] = "Thumbnail"


class TechnicalQCArtifact(BaseModel):
    technical_pass: bool
    editorial_pass: Literal[False] = False
    factual_pass: Literal[False] = False
    checks: dict[str, bool]
    notes: list[str]
    render_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    audio_stats: dict[str, float]
