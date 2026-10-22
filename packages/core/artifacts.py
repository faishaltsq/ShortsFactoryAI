"""Canonical JSON artifact validation at persistence boundaries."""

from __future__ import annotations

from typing import Any
from functools import lru_cache

from jsonschema import Draft202012Validator

from pydantic import BaseModel, ConfigDict, Field

from .media.contracts import AssetManifest, AudioArtifact, RenderArtifact, TechnicalQCArtifact
from .schemas import CreativeReview, ResearchResult, Script, Storyboard, TopicCandidate, TopicSelection, VideoMetadata


class JobSnapshot(BaseModel):
    id: str = Field(pattern="^[0-9a-f]{16}$")
    title: str
    state: str
    attempts: int = Field(ge=0)
    created_at: str
    updated_at: str
    payload: dict[str, Any]
    last_error: str | None = None


class TopicArtifact(BaseModel):
    selection: TopicSelection
    topic: TopicCandidate


class ReviewArtifact(BaseModel):
    review: CreativeReview
    script: Script


class ReviewSection(BaseModel):
    # Model sering menambah catatan sendiri di luar kontrak. Field asing
    # diabaikan, bukan menggagalkan seluruh review: isi yang diminta tetap
    # dipakai, dan satu field ekstra tidak boleh membuang hasil QC.
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    passed: bool = Field(alias="pass")
    findings: list[str] = Field(default_factory=list)


class FactualSection(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    passed: bool = Field(alias="pass")
    unsupported_claims: list[str] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)


class DraftQualityArtifact(BaseModel):
    technical: ReviewSection
    editorial: ReviewSection
    factual: FactualSection
    overall: str = Field(pattern="^(pass|warn|fail)$")


ARTIFACT_MODELS: dict[str, type[BaseModel]] = {
    "job.json": JobSnapshot,
    "research.json": ResearchResult,
    "topic.json": TopicArtifact,
    "script.json": Script,
    "review.json": ReviewArtifact,
    "storyboard.json": Storyboard,
    "draft_qc.json": DraftQualityArtifact,
    "metadata.json": VideoMetadata,
    "assets.json": AssetManifest,
    "audio.json": AudioArtifact,
    "render.json": RenderArtifact,
    "qc.json": TechnicalQCArtifact,
}


@lru_cache(maxsize=32)
def _validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(ARTIFACT_MODELS[name].model_json_schema(by_alias=True))


def validate_artifact(name: str, data: Any) -> dict[str, Any]:
    model = ARTIFACT_MODELS.get(name)
    if model is None:
        raise ValueError(f"unknown artifact contract: {name}")
    canonical = model.model_validate(data).model_dump(mode="json", by_alias=True, exclude_none=True)
    if any(_validator(name).iter_errors(canonical)):
        raise ValueError(f"{name} violates its JSON Schema")
    return canonical
