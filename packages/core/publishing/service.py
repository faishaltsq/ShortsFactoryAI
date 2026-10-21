"""Private-first publishing domain. No HTTP imports and no unattended entry point."""
from __future__ import annotations

import hashlib
import hmac
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Protocol

from pydantic import ValidationError

from ..media.contracts import RenderArtifact
from ..orchestration.jobstore import JobStore
from ..orchestration.states import JobState, can_transition
from ..schemas import VideoMetadata
from .contracts import PublishingArtifact, RemoteVideo, UploadOptions, UploadProgress
from .errors import PublishingError, RemoteError

CHUNK_UNIT = 256 * 1024


class YouTubeGateway(Protocol):
    def initiate_private(self, metadata: VideoMetadata, total_bytes: int, options: UploadOptions, *,
                         allow_upload: bool) -> str: ...
    def query_upload(self, session_uri: str, *, total: int, allow_read: bool) -> UploadProgress: ...
    def upload_chunk(self, session_uri: str, content: bytes, *, offset: int, total: int,
                     allow_upload: bool) -> UploadProgress: ...
    def read_video(self, video_id: str, *, allow_read: bool) -> RemoteVideo: ...
    def update_status(self, video: RemoteVideo, *, privacy_status: str, publish_at: datetime | None,
                      allow_change: bool) -> None: ...


class SessionStore(Protocol):
    def read(self, name: str) -> dict[str, Any] | None: ...
    def write(self, name: str, data: dict[str, Any]) -> None: ...
    def delete(self, name: str) -> None: ...


def _production_eligible(store: JobStore, job_id: str) -> None:
    from ..approval import require_eligible
    require_eligible(store, job_id)


def _production_fingerprint(store: JobStore, job_id: str) -> str:
    from ..approval import approval_fingerprint
    return approval_fingerprint(store, job_id)


class PublishingService:
    def __init__(self, store: JobStore, gateway: YouTubeGateway, sessions: SessionStore, *,
                 eligibility: Callable[[JobStore, str], Any] | None = None,
                 fingerprint: Callable[[JobStore, str], str] | None = None,
                 clock: Callable[[], datetime] | None = None,
                 chunk_size: int = 8 * CHUNK_UNIT, max_recoveries: int = 3) -> None:
        if chunk_size < CHUNK_UNIT or chunk_size > 32 * CHUNK_UNIT or chunk_size % CHUNK_UNIT:
            raise ValueError("invalid_chunk_size")
        if not 1 <= max_recoveries <= 5:
            raise ValueError("invalid_recovery_cap")
        self.store, self.gateway, self.sessions = store, gateway, sessions
        self.eligibility = eligibility or _production_eligible
        self.fingerprint = fingerprint or _production_fingerprint
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.chunk_size, self.max_recoveries = chunk_size, max_recoveries

    @contextmanager
    def _lease(self, job_id: str) -> Iterator[str]:
        token = self.store.acquire_lease(job_id, ttl_s=600)
        if not token:
            raise PublishingError("job_lease_busy")
        try:
            yield token
        finally:
            self.store.release_lease(job_id, token)

    def _touch(self, job_id: str, token: str) -> None:
        if not self.store.renew_lease(job_id, token, ttl_s=600):
            raise PublishingError("job_lease_lost")

    def _authorize(self, job_id: str) -> str:
        record = self.store.get(job_id)
        if record.state not in (JobState.APPROVED, JobState.PRIVATE_UPLOAD, JobState.SCHEDULED, JobState.PUBLISHED):
            raise PublishingError("approved_job_required")
        if record.payload.get("provider_mode") != "live":
            raise PublishingError("live_job_required")
        actor = record.payload.get("approved_by")
        stamp = record.payload.get("approved_at")
        if not isinstance(actor, str) or not actor.strip() or not isinstance(stamp, str):
            raise PublishingError("operator_approval_required")
        try:
            approved_at = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            if approved_at.tzinfo is None or approved_at > self.clock():
                raise ValueError
        except ValueError:
            raise PublishingError("operator_approval_required") from None
        expected = record.payload.get("approved_inputs_sha256")
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise PublishingError("approval_fingerprint_required")
        try:
            self.eligibility(self.store, job_id)
            actual = self.fingerprint(self.store, job_id)
        except (ValueError, OSError, KeyError):
            raise PublishingError("approval_eligibility_failed") from None
        if not isinstance(actual, str) or not hmac.compare_digest(expected, actual):
            raise PublishingError("approval_inputs_changed")
        return expected

    def _receipt(self, job_id: str, expected: str) -> None:
        record = self.store.get(job_id)
        if record.state not in (JobState.APPROVED, JobState.PRIVATE_UPLOAD, JobState.SCHEDULED, JobState.PUBLISHED):
            raise PublishingError("approved_job_required")
        if (record.payload.get("provider_mode") != "live" or not record.payload.get("approved_by")
                or not record.payload.get("approved_at") or record.payload.get("approved_inputs_sha256") != expected):
            raise PublishingError("approval_inputs_changed")
        try:
            actual = self.fingerprint(self.store, job_id)
        except (ValueError, OSError, KeyError):
            raise PublishingError("approval_inputs_changed") from None
        if not isinstance(actual, str) or not hmac.compare_digest(expected, actual):
            raise PublishingError("approval_inputs_changed")

    def _media(self, job_id: str, token: str) -> tuple[Path, int, str, tuple[int, int, int]]:
        self._touch(job_id, token)
        try:
            artifact = RenderArtifact.model_validate(self.store.read_artifact(job_id, "render.json"))
            root = self.store.artifact_root(job_id).resolve()
            path = root / artifact.output_path
            if path.is_symlink() or not path.resolve().is_relative_to(root) or not path.is_file():
                raise ValueError
            before = path.stat()
            digest = hashlib.sha256()
            with path.open("rb") as source:
                blocks = 0
                while block := source.read(1024 * 1024):
                    digest.update(block)
                    blocks += 1
                    if blocks % 32 == 0:
                        self._touch(job_id, token)
            after = path.stat()
            signature = (after.st_size, after.st_mtime_ns, after.st_ino)
            if not after.st_size or (before.st_size, before.st_mtime_ns, before.st_ino) != signature:
                raise ValueError
            if digest.hexdigest() != artifact.sha256:
                raise ValueError
            return path, after.st_size, artifact.sha256, signature
        except (OSError, ValueError, ValidationError, KeyError):
            raise PublishingError("approved_media_invalid") from None

    def _save(self, job_id: str, token: str, artifact: PublishingArtifact, **changes: Any) -> PublishingArtifact:
        self._touch(job_id, token)
        data = artifact.model_dump()
        data.update(changes)
        result = PublishingArtifact.model_validate(data)
        self.store.write_artifact(job_id, "publishing.json", result.model_dump(mode="json", exclude_none=True))
        return result

    def _load(self, job_id: str) -> PublishingArtifact | None:
        try:
            raw = self.store.read_artifact(job_id, "publishing.json")
        except FileNotFoundError:
            return None
        try:
            return PublishingArtifact.model_validate(raw)
        except ValueError:
            raise PublishingError("publishing_record_invalid") from None

    def _uncertain(self, job_id: str, token: str, artifact: PublishingArtifact) -> None:
        self._save(job_id, token, artifact, phase="uncertain", error_code="manual_reconciliation_required")
        raise PublishingError("manual_reconciliation_required")

    def _recovery(self, job_id: str, token: str, artifact: PublishingArtifact) -> PublishingArtifact:
        artifact = self._save(job_id, token, artifact, retry_count=artifact.retry_count + 1)
        if artifact.retry_count >= self.max_recoveries:
            # The consumed attempt must be on disk before the cap closes.
            self._uncertain(job_id, token, artifact)
        return artifact

    def _accept(self, job_id: str, token: str, artifact: PublishingArtifact,
                progress: UploadProgress, *, upper_bound: int, require_progress: bool = True) -> PublishingArtifact:
        if not artifact.offset <= progress.offset <= upper_bound:
            self._uncertain(job_id, token, artifact)
        if progress.video_id:
            if progress.offset != artifact.total_bytes or upper_bound != artifact.total_bytes:
                self._uncertain(job_id, token, artifact)
            return self._save(job_id, token, artifact, phase="verifying", offset=progress.offset,
                              video_id=progress.video_id, error_code=None)
        if require_progress and progress.offset == artifact.offset:
            artifact = self._recovery(job_id, token, artifact)
        return self._save(job_id, token, artifact, phase="uploading", offset=progress.offset)

    def upload_private(self, job_id: str, options: UploadOptions, *, allow_upload: bool) -> PublishingArtifact:
        if allow_upload is not True:
            raise PublishingError("upload_permission_required")
        with self._lease(job_id) as token:
            approved = self._authorize(job_id)
            if self.store.get(job_id).state not in (JobState.APPROVED, JobState.PRIVATE_UPLOAD):
                raise PublishingError("private_upload_state_required")
            path, total, checksum, signature = self._media(job_id, token)
            artifact = self._load(job_id)
            if artifact is not None:
                if (artifact.media_sha256 != checksum or artifact.total_bytes != total
                        or artifact.approved_inputs_sha256 != approved or artifact.options != options):
                    raise PublishingError("publishing_inputs_changed")
                if artifact.phase not in ("initiating", "uploading", "verifying", "private", "uncertain"):
                    raise PublishingError("private_upload_state_required")
                if artifact.video_id:
                    return self._complete_private(job_id, token, artifact)
            session = self.sessions.read(f"session-{job_id}")
            if artifact is None:
                if session is not None or self.store.get(job_id).payload.get("youtube_video_id"):
                    raise PublishingError("manual_reconciliation_required")
                if self.store.get(job_id).state is not JobState.APPROVED:
                    raise PublishingError("publishing_record_required")
                artifact = PublishingArtifact(phase="initiating", media_sha256=checksum,
                                               approved_inputs_sha256=approved, total_bytes=total, options=options)
                artifact = self._save(job_id, token, artifact)
                try:
                    self._touch(job_id, token)
                    metadata = VideoMetadata.model_validate(self.store.read_artifact(job_id, "metadata.json"))
                    self._receipt(job_id, approved)
                    uri = self.gateway.initiate_private(metadata, total, options, allow_upload=True)
                    session = {"session_uri": uri, "media_sha256": checksum, "total_bytes": total}
                    self.sessions.write(f"session-{job_id}", session)
                except (PublishingError, ValueError, OSError):
                    self._uncertain(job_id, token, artifact)
                artifact = self._save(job_id, token, artifact, phase="uploading")
            else:
                if artifact.phase == "uncertain" or session is None:
                    self._uncertain(job_id, token, artifact)
                if (session.get("media_sha256") != checksum or session.get("total_bytes") != total
                        or not isinstance(session.get("session_uri"), str)):
                    self._uncertain(job_id, token, artifact)
                self._touch(job_id, token)
                try:
                    progress = self.gateway.query_upload(session["session_uri"], total=total, allow_read=True)
                except PublishingError:
                    self._uncertain(job_id, token, artifact)
                artifact = self._accept(job_id, token, artifact, progress, upper_bound=total, require_progress=False)
            with path.open("rb") as source:
                while not artifact.video_id:
                    self._touch(job_id, token)
                    self._receipt(job_id, approved)
                    current = path.stat()
                    if (current.st_size, current.st_mtime_ns, current.st_ino) != signature:
                        self._uncertain(job_id, token, artifact)
                    if artifact.offset >= total:
                        artifact = self._recovery(job_id, token, artifact)
                        try:
                            progress = self.gateway.query_upload(session["session_uri"], total=total, allow_read=True)
                        except PublishingError:
                            self._uncertain(job_id, token, artifact)
                        artifact = self._accept(job_id, token, artifact, progress, upper_bound=total)
                        continue
                    source.seek(artifact.offset)
                    chunk = source.read(self.chunk_size)
                    end = artifact.offset + len(chunk)
                    try:
                        progress = self.gateway.upload_chunk(session["session_uri"], chunk,
                                                              offset=artifact.offset, total=total, allow_upload=True)
                    except RemoteError as error:
                        if not error.retryable:
                            self._uncertain(job_id, token, artifact)
                        artifact = self._recovery(job_id, token, artifact)
                        self._touch(job_id, token)
                        try:
                            progress = self.gateway.query_upload(session["session_uri"], total=total, allow_read=True)
                        except PublishingError:
                            self._uncertain(job_id, token, artifact)
                    artifact = self._accept(job_id, token, artifact, progress, upper_bound=end)
            return self._complete_private(job_id, token, artifact)

    @staticmethod
    def _disclosures_match(video: RemoteVideo, options: UploadOptions) -> bool:
        return ((video.made_for_kids is None or video.made_for_kids == options.made_for_kids)
                and (video.contains_synthetic_media is None
                     or video.contains_synthetic_media == options.contains_synthetic_media))

    def _complete_private(self, job_id: str, token: str, artifact: PublishingArtifact,
                          video: RemoteVideo | None = None) -> PublishingArtifact:
        self._touch(job_id, token)
        video = video if video is not None else self.gateway.read_video(artifact.video_id, allow_read=True)
        if (video.video_id != artifact.video_id or video.privacy_status != "private" or video.publish_at is not None
                or video.upload_status not in ("uploaded", "processed")
                or not self._disclosures_match(video, artifact.options)):
            raise PublishingError("remote_status_mismatch")
        if self._authorize(job_id) != artifact.approved_inputs_sha256 or self._media(job_id, token)[2] != artifact.media_sha256:
            raise PublishingError("publishing_inputs_changed")
        result = self._save(job_id, token, artifact, phase="private", privacy_status="private",
                            checked_at=self.clock(), publish_at=None, error_code=None)
        self._transition(job_id, token, JobState.PRIVATE_UPLOAD, result)
        self.sessions.delete(f"session-{job_id}")
        return result

    def _transition(self, job_id: str, token: str, state: JobState, artifact: PublishingArtifact) -> None:
        self._touch(job_id, token)
        current = self.store.get(job_id).state
        if current is state:
            return
        self.store.transition(job_id, state, expected_state=current,
                              detail="YouTube exact video readback verified",
                              payload_patch={"youtube_video_id": artifact.video_id})

    @staticmethod
    def _confirmation(*, permission: bool, confirm: bool, operator: str) -> None:
        if permission is not True or confirm is not True:
            raise PublishingError("explicit_publication_confirmation_required")
        if not isinstance(operator, str) or not operator.strip() or len(operator) > 100 or not operator.isprintable():
            raise PublishingError("publication_operator_required")

    def _publication_base(self, job_id: str, token: str, target: JobState) -> PublishingArtifact:
        approved = self._authorize(job_id)
        current = self.store.get(job_id).state
        if current not in (JobState.PRIVATE_UPLOAD, JobState.SCHEDULED, JobState.PUBLISHED):
            raise PublishingError("verified_private_upload_required")
        if current is not target and not can_transition(current, target):
            raise PublishingError("publication_transition_missing")
        artifact = self._load(job_id)
        if artifact is None or not artifact.video_id:
            raise PublishingError("verified_private_upload_required")
        if artifact.approved_inputs_sha256 != approved or self._media(job_id, token)[2] != artifact.media_sha256:
            raise PublishingError("publishing_inputs_changed")
        return artifact

    def _future(self, publish_at: datetime) -> datetime:
        if (not isinstance(publish_at, datetime) or publish_at.tzinfo is None or publish_at.utcoffset() is None
                or publish_at <= self.clock() + timedelta(minutes=2)):
            raise PublishingError("future_timezone_schedule_required")
        return publish_at.astimezone(timezone.utc)

    def schedule(self, job_id: str, *, publish_at: datetime, confirm: bool, operator: str,
                 allow_schedule: bool) -> PublishingArtifact:
        self._confirmation(permission=allow_schedule, confirm=confirm, operator=operator)
        publish_at = self._future(publish_at)
        with self._lease(job_id) as token:
            artifact = self._publication_base(job_id, token, JobState.SCHEDULED)
            if artifact.phase == "scheduled" and artifact.publish_at == publish_at:
                return self._finish_publication(job_id, token, artifact, scheduled=True)
            if artifact.phase != "private":
                raise PublishingError("manual_reconciliation_required")
            self._touch(job_id, token)
            video = self.gateway.read_video(artifact.video_id, allow_read=True)
            if (video.privacy_status != "private" or video.publish_at is not None
                    or video.upload_status not in ("uploaded", "processed")
                    or not self._disclosures_match(video, artifact.options)):
                raise PublishingError("remote_status_mismatch")
            self._future(publish_at)
            self._receipt(job_id, artifact.approved_inputs_sha256)
            artifact = self._save(job_id, token, artifact, phase="scheduling", requested_publish_at=publish_at,
                                  authorized_by=operator, authorized_at=self.clock(), error_code=None)
            try:
                self._touch(job_id, token)
                self.gateway.update_status(video, privacy_status="private", publish_at=publish_at, allow_change=True)
                return self._finish_publication(job_id, token, artifact, scheduled=True)
            except PublishingError:
                self._save(job_id, token, artifact, error_code="manual_reconciliation_required")
                raise PublishingError("manual_reconciliation_required") from None

    def publish_now(self, job_id: str, *, confirm: bool, operator: str, allow_publish: bool) -> PublishingArtifact:
        self._confirmation(permission=allow_publish, confirm=confirm, operator=operator)
        with self._lease(job_id) as token:
            artifact = self._publication_base(job_id, token, JobState.PUBLISHED)
            if artifact.phase == "published":
                return self._finish_publication(job_id, token, artifact, scheduled=False)
            if artifact.phase not in ("private", "scheduled"):
                raise PublishingError("manual_reconciliation_required")
            self._touch(job_id, token)
            video = self.gateway.read_video(artifact.video_id, allow_read=True)
            if (video.privacy_status != "private" or video.publish_at != artifact.publish_at
                    or video.upload_status not in ("uploaded", "processed")
                    or not self._disclosures_match(video, artifact.options)):
                raise PublishingError("remote_status_mismatch")
            self._receipt(job_id, artifact.approved_inputs_sha256)
            artifact = self._save(job_id, token, artifact, phase="publishing", requested_publish_at=None,
                                  authorized_by=operator, authorized_at=self.clock(), error_code=None)
            try:
                self._touch(job_id, token)
                self.gateway.update_status(video, privacy_status="public", publish_at=None, allow_change=True)
                return self._finish_publication(job_id, token, artifact, scheduled=False)
            except PublishingError:
                self._save(job_id, token, artifact, error_code="manual_reconciliation_required")
                raise PublishingError("manual_reconciliation_required") from None

    def _finish_publication(self, job_id: str, token: str, artifact: PublishingArtifact, *,
                            scheduled: bool, video: RemoteVideo | None = None) -> PublishingArtifact:
        self._touch(job_id, token)
        video = video if video is not None else self.gateway.read_video(artifact.video_id, allow_read=True)
        expected_time = artifact.requested_publish_at if scheduled else None
        if (video.video_id != artifact.video_id or video.privacy_status != ("private" if scheduled else "public")
                or video.publish_at != expected_time or video.upload_status not in ("uploaded", "processed")
                or not self._disclosures_match(video, artifact.options)
                or not artifact.authorized_by or not artifact.authorized_at or (scheduled and expected_time is None)):
            raise PublishingError("remote_status_mismatch")
        if self._authorize(job_id) != artifact.approved_inputs_sha256 or self._media(job_id, token)[2] != artifact.media_sha256:
            raise PublishingError("publishing_inputs_changed")
        result = self._save(job_id, token, artifact, phase="scheduled" if scheduled else "published",
                            privacy_status=video.privacy_status, publish_at=video.publish_at,
                            checked_at=self.clock(), error_code=None)
        self._transition(job_id, token, JobState.SCHEDULED if scheduled else JobState.PUBLISHED, result)
        return result

    def reconcile(self, job_id: str, *, video_id: str | None, confirm: bool, operator: str,
                  allow_read: bool) -> PublishingArtifact:
        self._confirmation(permission=allow_read, confirm=confirm, operator=operator)
        if video_id is not None and not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            raise PublishingError("remote_video_id_invalid")
        with self._lease(job_id) as token:
            approved = self._authorize(job_id)
            artifact = self._load(job_id)
            if artifact is None or artifact.approved_inputs_sha256 != approved:
                raise PublishingError("publishing_record_required")
            if self._media(job_id, token)[2] != artifact.media_sha256:
                raise PublishingError("publishing_inputs_changed")
            if artifact.video_id and video_id and artifact.video_id != video_id:
                raise PublishingError("remote_video_mismatch")
            actual_id = artifact.video_id or video_id
            if actual_id is None:
                raise PublishingError("manual_video_id_required")
            self._touch(job_id, token)
            video = self.gateway.read_video(actual_id, allow_read=True)
            if artifact.phase in ("scheduling", "scheduled", "publishing", "published"):
                scheduled = artifact.phase in ("scheduling", "scheduled")
                if (artifact.phase == "scheduled" and artifact.publish_at is not None and self.clock() >= artifact.publish_at
                        and video.privacy_status == "public"):
                    scheduled = False
                return self._finish_publication(job_id, token, artifact, scheduled=scheduled, video=video)
            if artifact.video_id is None:
                if video.privacy_status != "private" or video.publish_at is not None:
                    raise PublishingError("remote_status_mismatch")
                artifact = self._save(job_id, token, artifact, phase="verifying", video_id=actual_id,
                                      offset=artifact.total_bytes, authorized_by=operator, authorized_at=self.clock())
            return self._complete_private(job_id, token, artifact, video=video)
