"""YouTube v3 HTTP adapter. Only this boundary understands HTTP or signed URIs."""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import parse_qs, urlsplit

import httpx
from pydantic import ValidationError

from ..schemas import VideoMetadata
from .contracts import RemoteVideo, UploadOptions, UploadProgress
from .errors import PublishingError, RemoteError
from .oauth import TokenManager
from .transport import SafeHTTP, safe_json

UPLOAD_ENDPOINT = "https://www.googleapis.com/upload/youtube/v3/videos"
VIDEOS_ENDPOINT = "https://www.googleapis.com/youtube/v3/videos"
THUMBNAIL_ENDPOINT = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"
CHANNEL_ENDPOINT = "https://www.googleapis.com/youtube/v3/channels"
THUMBNAIL_MAX_BYTES = 2 * 1024 * 1024
CHUNK_UNIT = 256 * 1024


def validate_session_uri(uri: str) -> None:
    try:
        parsed = urlsplit(uri)
        query = parse_qs(parsed.query, max_num_fields=32)
        valid = (parsed.scheme == "https" and parsed.hostname == "www.googleapis.com"
                 and parsed.port in (None, 443) and not parsed.username and not parsed.password
                 and parsed.path == "/upload/youtube/v3/videos" and not parsed.fragment
                 and len(query.get("upload_id", [])) == 1 and bool(query["upload_id"][0]))
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise PublishingError("session_uri_invalid")


def _video_id(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        raise RemoteError("remote_video_id_invalid")
    return value


class YouTubeHTTPAdapter:
    def __init__(self, http: httpx.Client, tokens: TokenManager, *, allow_network: bool,
                 max_attempts: int = 3, timeout_s: float = 20,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.transport = SafeHTTP(http, max_attempts=max_attempts, timeout_s=timeout_s, sleep=sleep)
        self.tokens, self.allow_network = tokens, allow_network

    def _headers(self) -> dict[str, str]:
        if self.allow_network is not True:
            raise PublishingError("network_permission_required")
        return {"Authorization": "Bearer " + self.tokens.access_token(allow_refresh=True)}

    def initiate_private(self, metadata: VideoMetadata, total_bytes: int, options: UploadOptions, *,
                         allow_upload: bool) -> str:
        if allow_upload is not True:
            raise PublishingError("upload_permission_required")
        if total_bytes <= 0 or not 0 < len(metadata.title) <= 100 or len(metadata.description) > 5000:
            raise PublishingError("upload_metadata_invalid")
        headers = {**self._headers(), "X-Upload-Content-Length": str(total_bytes),
                   "X-Upload-Content-Type": "video/mp4"}
        body = {"snippet": {"title": metadata.title, "description": metadata.description,
                            "tags": metadata.tags, "categoryId": options.category_id},
                "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": options.made_for_kids,
                           "containsSyntheticMedia": options.contains_synthetic_media}}
        response = self.transport.request("POST", UPLOAD_ENDPOINT, retry_safe=False, accepted=(200, 201),
                                          params={"uploadType": "resumable", "part": "snippet,status"},
                                          headers=headers, json=body)
        uri = response.headers.get("Location", "")
        validate_session_uri(uri)
        return uri

    def query_upload(self, session_uri: str, *, total: int, allow_read: bool) -> UploadProgress:
        if allow_read is not True:
            raise PublishingError("read_permission_required")
        validate_session_uri(session_uri)
        if total <= 0:
            raise PublishingError("upload_size_invalid")
        response = self.transport.request("PUT", session_uri, retry_safe=True, accepted=(200, 201, 308),
                                          headers={**self._headers(), "Content-Length": "0",
                                                   "Content-Range": f"bytes */{total}"}, content=b"")
        return self._progress(response, total)

    def upload_chunk(self, session_uri: str, content: bytes, *, offset: int, total: int,
                     allow_upload: bool) -> UploadProgress:
        if allow_upload is not True:
            raise PublishingError("upload_permission_required")
        validate_session_uri(session_uri)
        end = offset + len(content)
        if offset < 0 or not content or end > total or (end < total and len(content) % CHUNK_UNIT):
            raise PublishingError("upload_chunk_invalid")
        response = self.transport.request("PUT", session_uri, retry_safe=False, accepted=(200, 201, 308),
                                          headers={**self._headers(), "Content-Type": "video/mp4",
                                                   "Content-Length": str(len(content)),
                                                   "Content-Range": f"bytes {offset}-{end - 1}/{total}"}, content=content)
        return self._progress(response, total)

    @staticmethod
    def _progress(response: httpx.Response, total: int) -> UploadProgress:
        if response.status_code != 308:
            return UploadProgress(total, _video_id(safe_json(response).get("id")))
        raw = response.headers.get("Range")
        if raw is None:
            return UploadProgress(0)
        match = re.fullmatch(r"bytes=0-([0-9]+)", raw)
        if match is None or not 0 <= int(match[1]) < total:
            raise RemoteError("remote_offset_invalid")
        return UploadProgress(int(match[1]) + 1)

    def read_video(self, video_id: str, *, allow_read: bool) -> RemoteVideo:
        if allow_read is not True:
            raise PublishingError("read_permission_required")
        _video_id(video_id)
        response = self.transport.request("GET", VIDEOS_ENDPOINT, retry_safe=True, accepted=(200,),
                                          params={"part": "status", "id": video_id}, headers=self._headers())
        items = safe_json(response).get("items")
        if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict) or items[0].get("id") != video_id:
            raise RemoteError("remote_video_mismatch")
        status = items[0].get("status")
        if not isinstance(status, dict):
            raise RemoteError("remote_status_invalid")
        mapping = {"privacyStatus": "privacy_status", "uploadStatus": "upload_status", "publishAt": "publish_at",
                   "embeddable": "embeddable", "license": "license", "publicStatsViewable": "public_stats_viewable",
                   "selfDeclaredMadeForKids": "made_for_kids", "containsSyntheticMedia": "contains_synthetic_media"}
        try:
            result = RemoteVideo(video_id=video_id, **{v: status[k] for k, v in mapping.items() if k in status})
            if result.publish_at is not None and result.publish_at.tzinfo is None:
                raise ValueError
            return result
        except (ValueError, ValidationError):
            raise RemoteError("remote_status_invalid") from None

    def update_status(self, video: RemoteVideo, *, privacy_status: str, publish_at: datetime | None,
                      allow_change: bool) -> None:
        if allow_change is not True:
            raise PublishingError("publication_permission_required")
        if privacy_status not in ("private", "public"):
            raise PublishingError("publication_status_invalid")
        status = {**video.writable_status(), "privacyStatus": privacy_status}
        if publish_at is not None:
            if privacy_status != "private" or publish_at.tzinfo is None:
                raise PublishingError("schedule_invalid")
            status["publishAt"] = publish_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        self.transport.request("PUT", VIDEOS_ENDPOINT, retry_safe=False, accepted=(200,),
                               params={"part": "status"}, headers=self._headers(),
                               json={"id": video.video_id, "status": status})

    def set_thumbnail(self, video_id: str, image: bytes, *, allow_upload: bool) -> None:
        if allow_upload is not True:
            raise PublishingError("upload_permission_required")
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            raise RemoteError("remote_video_id_invalid")
        if not image or len(image) > THUMBNAIL_MAX_BYTES:
            raise PublishingError("thumbnail_too_large")
        mime = ("image/png" if image[:8] == b"\x89PNG\r\n\x1a\n"
                else "image/jpeg" if image[:3] == b"\xff\xd8\xff" else "")
        if not mime:
            raise PublishingError("thumbnail_type_invalid")
        # Ambiguous media writes are never blindly replayed; a lost response needs operator
        # reconciliation, exactly like the resumable video initiation above.
        self.transport.request("POST", THUMBNAIL_ENDPOINT, retry_safe=False, accepted=(200, 201),
                               params={"videoId": video_id, "uploadType": "media"},
                               headers={**self._headers(), "Content-Type": mime}, content=image)

    def read_channel(self, *, allow_read: bool) -> dict[str, str]:
        if allow_read is not True:
            raise PublishingError("read_permission_required")
        response = self.transport.request("GET", CHANNEL_ENDPOINT, retry_safe=True, accepted=(200,),
                                          params={"part": "snippet", "mine": "true"},
                                          headers=self._headers())
        items = safe_json(response).get("items")
        if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
            raise RemoteError("remote_channel_invalid")
        channel = items[0]
        snippet = channel.get("snippet") or {}
        if not isinstance(channel.get("id"), str) or not isinstance(snippet.get("title"), str):
            raise RemoteError("remote_channel_invalid")
        return {"id": channel["id"], "title": snippet["title"]}
