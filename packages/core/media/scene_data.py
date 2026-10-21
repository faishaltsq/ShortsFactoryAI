"""Strict template and audio input data, independent of renderer implementation."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictData(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True, allow_inf_nan=False)


class ComicPanel(StrictData):
    caption: str = Field(min_length=1, max_length=120)
    speaker: str | None = Field(default=None, min_length=1, max_length=32)
    assetRef: str | None = Field(default=None, min_length=1, max_length=200)


class MotionComicData(StrictData):
    title: str | None = Field(default=None, min_length=1, max_length=70)
    panels: list[ComicPanel] = Field(min_length=1, max_length=3)


class TimelineEvent(StrictData):
    date: str = Field(min_length=1, max_length=24)
    label: str = Field(min_length=1, max_length=70)
    detail: str | None = Field(default=None, min_length=1, max_length=100)


class HistoricalTimelineData(StrictData):
    title: str | None = Field(default=None, min_length=1, max_length=70)
    events: list[TimelineEvent] = Field(min_length=2, max_length=4)


class ParallaxLayer(StrictData):
    depth: float = Field(ge=0.1, le=1)
    shape: Literal["ridge", "city", "circle"] | None = None
    assetRef: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def one_visual(self):
        if (self.shape is None) == (self.assetRef is None):
            raise ValueError("parallax layer requires exactly one shape or assetRef")
        return self


class ParallaxStoryData(StrictData):
    title: str = Field(min_length=1, max_length=70)
    caption: str | None = Field(default=None, min_length=1, max_length=160)
    layers: list[ParallaxLayer] = Field(min_length=1, max_length=4)


class InfographicItem(StrictData):
    label: str = Field(min_length=1, max_length=52)
    value: float = Field(ge=0, le=1e12)
    unit: str | None = Field(default=None, max_length=16)


class InfographicMotionData(StrictData):
    title: str = Field(min_length=1, max_length=70)
    items: list[InfographicItem] = Field(min_length=1, max_length=4)
    maxValue: float | None = Field(default=None, gt=0, le=1e12)
    decimals: int = Field(default=0, ge=0, le=2)

    @model_validator(mode="after")
    def correct_scale(self):
        if self.maxValue is not None and any(item.value > self.maxValue for item in self.items):
            raise ValueError("maxValue must cover every infographic value")
        return self


class SFXCueSpec(StrictData):
    assetRef: str = Field(min_length=1)
    frame: int = Field(ge=0, le=3000)
    volume: float = Field(default=0.5, ge=0, le=1)


class SceneAudioSpec(StrictData):
    sfx: list[SFXCueSpec] = Field(min_length=1, max_length=8)


class BackgroundMusicSpec(StrictData):
    assetRef: str = Field(min_length=1)
    volume: float = Field(default=0.15, ge=0, le=1)
    loop: bool = True


class IllustrationActor(StrictData):
    pose: Literal["stand", "point", "reach", "walk", "lookUp", "shrug", "sit"] = "stand"
    x: float = Field(default=0.5, ge=0, le=1)
    ground: float = Field(default=0.72, ge=0, le=1)
    scale: float = Field(default=1.0, ge=0.4, le=1.8)
    facing: Literal["left", "right"] = "right"
    tone: Literal["primary", "secondary", "accent"] = "primary"
    silhouette: bool = False


class IllustrationProp(StrictData):
    kind: Literal[
        "sun", "moon", "planet", "star", "cloud", "mountain", "tree",
        "tower", "gear", "book", "wave", "clock", "bulb", "arrow",
    ]
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    scale: float = Field(default=1.0, ge=0.4, le=2.0)


class IllustrationShot(StrictData):
    framing: Literal["wide", "medium", "close"] = "wide"
    camera: Literal["static", "pushIn", "pullOut", "panLeft", "panRight", "tiltUp", "handheld"] = "pushIn"
    weight: float = Field(default=1.0, ge=0.5, le=3.0)


class IllustrationData(StrictData):
    title: str | None = Field(default=None, min_length=1, max_length=70)
    caption: str | None = Field(default=None, min_length=1, max_length=90)
    setting: Literal["space", "desert", "city", "ocean", "forest", "interior", "abstract"]
    timeOfDay: Literal["dawn", "day", "dusk", "night"] | None = None
    imageRef: str | None = Field(default=None, min_length=1, max_length=200)
    actors: list[IllustrationActor] = Field(default_factory=list, max_length=3)
    props: list[IllustrationProp] = Field(default_factory=list, max_length=5)
    fx: list[Literal["lightRays", "dust", "stars", "speedLines", "impact", "vignette"]] = Field(
        default_factory=list, max_length=4
    )
    shots: list[IllustrationShot] = Field(
        default_factory=lambda: [IllustrationShot()], min_length=1, max_length=4
    )

    @model_validator(mode="after")
    def unique_fx(self):
        if len(set(self.fx)) != len(self.fx):
            raise ValueError("fx entries must be unique")
        return self


SCENE_DATA_MODELS = {
    "MotionComic": MotionComicData,
    "HistoricalTimeline": HistoricalTimelineData,
    "ParallaxStory": ParallaxStoryData,
    "InfographicMotion": InfographicMotionData,
    "IllustratedStory": IllustrationData,
}


def validate_scene_data(template: str, data: dict | None) -> None:
    if model := SCENE_DATA_MODELS.get(template):
        if data is None:
            raise ValueError(f"template not implemented for incomplete scene data: {template} requires data")
        model.model_validate(data)
