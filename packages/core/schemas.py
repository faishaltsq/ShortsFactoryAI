"""Typed domain models. These are the contracts between agents, pipeline and renderer."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

TemplateId = Literal[
    "KineticTypography",
    "MotionComic",
    "EducationalExplainer",
    "HistoricalTimeline",
    "ParallaxStory",
    "InfographicMotion",
]

ALLOWED_TEMPLATES = {
    "KineticTypography",
    "MotionComic",
    "EducationalExplainer",
    "HistoricalTimeline",
    "ParallaxStory",
    "InfographicMotion",
}


class Genre(str, Enum):
    educational = "educational"
    science = "science"
    history = "history"
    mystery = "mystery"
    fiction = "fiction"
    general_knowledge = "general_knowledge"
    animated_narrative = "animated_narrative"


class VerificationStatus(str, Enum):
    supported = "supported"
    needs_review = "needs_review"
    unsupported = "unsupported"
    fictional = "fictional"


class SourceRef(BaseModel):
    title: str
    url: str | None = None
    publisher: str | None = None
    published: str | None = None
    accessed: str | None = None


class TopicCandidate(BaseModel):
    topic_id: str
    title: str
    genre: Genre
    hook: str
    angle: str
    sources: list[SourceRef] = Field(default_factory=list)
    verification: VerificationStatus = VerificationStatus.needs_review
    visual_potential: int = Field(ge=0, le=10, default=5)
    novelty: int = Field(ge=0, le=10, default=5)


class ResearchResult(BaseModel):
    candidates: list[TopicCandidate] = Field(default_factory=list)


class SelectionScores(BaseModel):
    originality: int = Field(ge=0, le=10)
    hook: int = Field(ge=0, le=10)
    verifiability: int = Field(ge=0, le=10)
    visual: int = Field(ge=0, le=10)
    genre_diversity: int = Field(ge=0, le=10)


class TopicSelection(BaseModel):
    selected_topic_id: str
    rationale: str
    scores: SelectionScores
    genre: Genre


class ScriptSegment(BaseModel):
    kind: Literal["hook", "body", "payoff"]
    text: str


class Script(BaseModel):
    title: str
    genre: Genre
    content_type: Literal["factual", "fictional"] = "factual"
    segments: list[ScriptSegment]
    sources: list[SourceRef] = Field(default_factory=list)
    estimated_duration_s: int = Field(ge=15, le=90, default=40)
    verification_status: VerificationStatus = VerificationStatus.needs_review

    @field_validator("segments")
    @classmethod
    def _must_have_hook_and_payoff(cls, v: list[ScriptSegment]) -> list[ScriptSegment]:
        kinds = {s.kind for s in v}
        if "hook" not in kinds:
            raise ValueError("script must contain a hook segment")
        if len(v) < 2:
            raise ValueError("script needs at least hook and one more segment")
        return v

    @property
    def full_text(self) -> str:
        return " ".join(s.text for s in self.segments)


class ScriptClaim(BaseModel):
    """One factual assertion a model says the script makes, with its quoted evidence."""

    statement: str = Field(min_length=1)
    quote: str = Field(default="")
    source_url: str = Field(default="")


class ScriptClaimList(BaseModel):
    claims: list[ScriptClaim] = Field(default_factory=list)


class CreativeReview(BaseModel):
    verdict: Literal["approve", "revise", "reject"] = "approve"
    weak_spots: list[str] = Field(default_factory=list)
    revisions: list[dict[str, Any]] = Field(default_factory=list)
    notes: str = ""


class TextStyleSpec(BaseModel):
    role: Literal["title", "highlight", "body", "caption", "kicker"]
    y: float | None = None
    size: int | None = None
    color: str | None = None
    uppercase: bool | None = None
    align: Literal["left", "center", "right"] | None = None
    max_chars_per_line: int | None = None


class TextElementSpec(BaseModel):
    id: str
    text: str
    style: TextStyleSpec
    inFrame: int | None = None
    outFrame: int | None = None


class AnimationSpec(BaseModel):
    preset: Literal["popIn", "slideUp", "wordByWord", "wipeIn", "countUp", "fadeIn"] = "fadeIn"
    durationInFrames: int | None = None
    intensity: float | None = None


class TransitionSpec(BaseModel):
    type: Literal["none", "fade", "slideUp", "wipe", "zoom"] = "fade"
    durationInFrames: int | None = 10


class SceneSpec(BaseModel):
    sceneId: str
    template: TemplateId
    segment: str
    assetRefs: list[str] = Field(default_factory=list)
    text: list[TextElementSpec] = Field(default_factory=list)
    animation: AnimationSpec = Field(default_factory=AnimationSpec)
    transition: TransitionSpec = Field(default_factory=TransitionSpec)
    audio: dict[str, Any] | None = None
    startFrame: int = 0
    durationInFrames: int = Field(ge=30, le=3000, default=300)
    data: dict[str, Any] | None = None

    @field_validator("data")
    @classmethod
    def _template_data(cls, value: dict[str, Any] | None, info: Any) -> dict[str, Any] | None:
        if value is not None:
            from .media.scene_data import validate_scene_data
            validate_scene_data(info.data.get("template", ""), value)
        return value

    @field_validator("audio")
    @classmethod
    def _scene_audio(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is not None:
            from .media.scene_data import SceneAudioSpec
            SceneAudioSpec.model_validate(value)
        return value

    @field_validator("template")
    @classmethod
    def _known_template(cls, v: str) -> str:
        if v not in ALLOWED_TEMPLATES:
            raise ValueError(f"unknown template {v!r}; allowed: {sorted(ALLOWED_TEMPLATES)}")
        return v


class SubtitleCue(BaseModel):
    id: str
    text: str
    startMs: int = Field(ge=0)
    endMs: int = Field(ge=0)

    @field_validator("endMs")
    @classmethod
    def _after_start(cls, v: int, info: Any) -> int:
        start = info.data.get("startMs")
        if start is not None and v <= start:
            raise ValueError("endMs must be greater than startMs")
        return v


class ThemeSpec(BaseModel):
    id: str = "midnight"
    background: str | None = None
    backgroundAccent: str | None = None
    primary: str | None = None
    secondary: str | None = None
    accent: str | None = None
    fontHeading: str | None = None
    fontBody: str | None = None


class Storyboard(BaseModel):
    id: str
    language: str = "id-ID"
    width: int = 1080
    height: int = 1920
    fps: int = 30
    theme: ThemeSpec = Field(default_factory=ThemeSpec)
    scenes: list[SceneSpec]
    subtitles: list[SubtitleCue] = Field(default_factory=list)
    narration: dict[str, Any] | None = None
    backgroundMusic: dict[str, Any] | None = None
    watermark: dict[str, Any] | None = None

    @field_validator("scenes")
    @classmethod
    def _contiguous_timing(cls, v: list[SceneSpec]) -> list[SceneSpec]:
        ordered = sorted(v, key=lambda s: s.startFrame)
        cursor = 0
        for scene in ordered:
            if scene.startFrame != cursor:
                raise ValueError(f"non-contiguous timing before {scene.sceneId}")
            cursor += scene.durationInFrames
        if not ordered or len({scene.sceneId for scene in ordered}) != len(ordered):
            raise ValueError("storyboard must contain scenes with unique ids")
        return v

    @property
    def total_frames(self) -> int:
        if not self.scenes:
            return 0
        return max(s.startFrame + s.durationInFrames for s in self.scenes)


class QCFinding(BaseModel):
    severity: Literal["info", "warn", "blocker"]
    code: str
    message: str
    scene_id: str | None = None


class QCReport(BaseModel):
    technical_pass: bool = False
    editorial_pass: bool = False
    factual_pass: bool = False
    findings: list[QCFinding] = Field(default_factory=list)
    overall: Literal["pass", "warn", "fail"] = "fail"

    @property
    def blocked(self) -> bool:
        return any(f.severity == "blocker" for f in self.findings) or self.overall == "fail"


class VideoMetadata(BaseModel):
    title: str
    description: str
    tags: list[str] = Field(default_factory=list)
    thumbnail: dict[str, Any] = Field(default_factory=dict)
