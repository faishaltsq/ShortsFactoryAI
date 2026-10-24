"""Credential-free domain contracts; remote data is reduced to known status fields."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class UploadOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    category_id: str = Field(pattern="^[1-9][0-9]{0,3}$")
    made_for_kids: bool
    contains_synthetic_media: bool


class PublishingArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    phase: Literal["initiating", "uploading", "verifying", "private", "uncertain",
                   "scheduling", "scheduled", "publishing", "published"]
    media_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    approved_inputs_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    total_bytes: int = Field(gt=0)
    offset: int = Field(ge=0, default=0)
    options: UploadOptions
    video_id: str | None = Field(default=None, pattern="^[A-Za-z0-9_-]{11}$")
    privacy_status: Literal["private", "public", "unlisted"] | None = None
    publish_at: datetime | None = None
    requested_publish_at: datetime | None = None
    authorized_by: str | None = Field(default=None, min_length=1, max_length=100)
    authorized_at: datetime | None = None
    checked_at: datetime | None = None
    retry_count: int = Field(ge=0, le=5, default=0)
    error_code: str | None = Field(default=None, pattern="^[a-z_]{1,64}$")
    thumbnail_sha256: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")
    thumbnail_uploaded_at: datetime | None = None

    @model_validator(mode="after")
    def consistent(self) -> PublishingArtifact:
        if self.offset > self.total_bytes:
            raise ValueError("offset_out_of_bounds")
        for stamp in (self.publish_at, self.requested_publish_at, self.authorized_at, self.checked_at,
                      self.thumbnail_uploaded_at):
            if stamp is not None and (stamp.tzinfo is None or stamp.utcoffset() is None):
                raise ValueError("timezone_required")
        if self.phase in ("private", "scheduled", "published") and (not self.video_id or not self.checked_at):
            raise ValueError("remote_confirmation_required")
        if self.phase == "private" and (self.privacy_status != "private" or self.publish_at is not None):
            raise ValueError("private_status_required")
        if self.phase == "scheduled" and (self.privacy_status != "private" or self.publish_at is None):
            raise ValueError("schedule_required")
        if self.phase == "published" and self.privacy_status != "public":
            raise ValueError("public_status_required")
        return self


@dataclass(frozen=True)
class UploadProgress:
    offset: int
    video_id: str | None = None


class RemoteVideo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    video_id: str = Field(pattern="^[A-Za-z0-9_-]{11}$")
    privacy_status: Literal["private", "public", "unlisted"]
    upload_status: Literal["uploaded", "processed", "failed", "rejected", "deleted"]
    publish_at: datetime | None = None
    embeddable: bool | None = None
    license: Literal["youtube", "creativeCommon"] | None = None
    public_stats_viewable: bool | None = None
    made_for_kids: bool | None = None
    contains_synthetic_media: bool | None = None

    def writable_status(self) -> dict[str, object]:
        names = {"embeddable": "embeddable", "license": "license", "public_stats_viewable": "publicStatsViewable",
                 "made_for_kids": "selfDeclaredMadeForKids", "contains_synthetic_media": "containsSyntheticMedia"}
        return {remote: getattr(self, local) for local, remote in names.items() if getattr(self, local) is not None}
