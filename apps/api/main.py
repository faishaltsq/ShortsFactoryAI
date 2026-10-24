"""Pixel Production Studio HTTP surface: read-only, local, credential-free."""
from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field, field_validator
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from packages.core.approval import ApprovalRejected, approve, reject
from packages.core.config import JOBS_DIR, get_settings
from packages.core.orchestration import JobStore
from packages.core.observability.hermes import HermesObserver, InvalidDelivery, ObserverDisabled
from packages.core.observability.projection import StudioService
from packages.core.observability.schedule import ScheduleService
from packages.core.studio import studio_path

from .streaming import stream_events
from .studio_routes import attach_studio_routes

JOB_PATTERN = r"^[0-9a-f]{16}$"
MODE_PATTERN = r"^(production|demo)$"
RANGE_PATTERN = r"^bytes=(\d*)-(\d*)$"

OPERATOR_MAX = 80
REASON_MAX = 500


class DecisionBody(BaseModel):
    """Who decided. The verdict itself never travels in the request."""

    operator: str = Field(min_length=1, max_length=OPERATOR_MAX)

    @field_validator("operator", mode="before")
    @classmethod
    def _normalise_operator(cls, value: object) -> object:
        # Stripped before the length check, not after it: a body of spaces is
        # length 3, so validating the raw value would pass and leave "" for
        # approval.operator_name(), which silently substitutes the default.
        return value.strip() if isinstance(value, str) else value


class RejectionBody(DecisionBody):
    """A rejection must say why, or the operator re-runs the same job blind."""

    reason: str = Field(min_length=1, max_length=REASON_MAX)

    @field_validator("reason", mode="before")
    @classmethod
    def _normalise_reason(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


def _csv(name: str, default: str) -> list[str]:
    return [part.strip() for part in os.environ.get(name, default).split(",") if part.strip()]


def _canonical_host(hostname: str) -> str:
    """Treat the two names for this machine as one origin.

    The dashboard on http://localhost:3018 proxies its API calls to
    http://127.0.0.1:8018, so a browser POST carries Origin: localhost while the
    request itself arrives addressed to 127.0.0.1. Comparing them literally
    refused every mutating request; both spellings name this same loopback
    machine, while an external host still differs and is still refused.
    """
    return "127.0.0.1" if hostname in {"localhost", "127.0.0.1", "::1", "[::1]"} else hostname


class SameOriginMiddleware(BaseHTTPMiddleware):
    """Reject cross-site browser requests; the studio is a single local origin."""

    def __init__(self, app, allowed_origins: list[str]) -> None:
        super().__init__(app)
        self.allowed = {_canonical_host(urlsplit(origin).hostname)
                        for origin in allowed_origins if urlsplit(origin).hostname}

    async def dispatch(self, request: Request, call_next):  # noqa: ANN201 - Starlette signature
        expected_token = os.environ.get("STUDIO_TOKEN", "")
        if expected_token and request.url.path.startswith("/api/"):
            if request.headers.get("authorization") != f"Bearer {expected_token}":
                return JSONResponse({"detail": "token tidak valid"}, status_code=401)
        origin = request.headers.get("origin")
        if origin:
            host = _canonical_host(urlsplit(origin).hostname or "")
            if host not in self.allowed and host != _canonical_host(request.url.hostname or ""):
                return JSONResponse({"detail": "cross-origin request refused"}, status_code=403)
        return await call_next(request)


def _parse_range(header: str, size: int) -> tuple[int, int] | None:
    import re

    match = re.match(RANGE_PATTERN, header.strip())
    if not match or not match[1] and not match[2]:
        return None
    start = int(match[1]) if match[1] else None
    end = int(match[2]) if match[2] else None
    if start is None:
        if end is None or end <= 0:
            return None
        start = max(0, size - end)
        end = size - 1
    else:
        if start >= size:
            raise HTTPException(416, "requested range is outside the file")
        end = min(size - 1, end) if end is not None else size - 1
        if end < start:
            raise HTTPException(416, "requested range is outside the file")
    return start, end


def create_app(store: JobStore | None = None) -> FastAPI:
    settings = get_settings()
    job_store = store or JobStore(settings.db_path, JOBS_DIR)
    service = StudioService(job_store)
    schedule = ScheduleService(job_store)

    app = FastAPI(title="Shorts Factory Studio API", version="1.0.0", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(SameOriginMiddleware, allowed_origins=_csv("SHORTS_API_ALLOWED_ORIGINS", ""))
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=_csv("SHORTS_API_ALLOWED_HOSTS", "localhost,127.0.0.1"))

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        settings = get_settings()
        return {
            "ok": True,
            "status": "ok",
            "api": "studio",
            "db": str(settings.db_path),
            "studio_exists": studio_path().exists(),
            "observers": {"hermes": "configured" if _hermes_secret() else "disabled"},
        }

    @app.get("/api/studio/snapshot")
    def snapshot(job_id: str | None = Query(default=None, pattern=JOB_PATTERN),
                 mode: str = Query(default="production", pattern=MODE_PATTERN)) -> dict[str, Any]:
        try:
            return service.snapshot(job_id=job_id, mode=mode)
        except (ValueError, KeyError) as exc:
            raise HTTPException(404, "job is unavailable") from exc

    @app.get("/api/studio/schedule")
    def studio_schedule() -> dict[str, Any]:
        """What is in production, queued, or next. Read-only: it cannot dispatch a job."""
        return schedule.entries()

    @app.get("/api/events")
    def events(after: int = Query(default=0, ge=0), limit: int = Query(default=100, ge=1, le=500),
               job_id: str | None = Query(default=None, pattern=JOB_PATTERN)) -> dict[str, Any]:
        try:
            page = service.events.page(after=after, limit=limit, job_id=job_id)
        except ValueError as exc:
            raise HTTPException(422, "invalid event cursor") from exc
        rows = [event.model_dump(mode="json") for event in page]
        return {"cursor": rows[-1]["event_id"] if rows else after, "events": rows}

    @app.get("/api/studio/stream")
    async def stream(request: Request, after: int = Query(default=0, ge=0)) -> StreamingResponse:
        return StreamingResponse(
            stream_events(service, request, after=after),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-transform", "Connection": "keep-alive",
                     "X-Accel-Buffering": "no"},
        )

    @app.get("/api/jobs/{job_id}/video")
    def video(job_id: str, range_header: str | None = Header(default=None, alias="Range")) -> Response:
        try:
            path = service.video_path(job_id)
        except (ValueError, KeyError) as exc:
            raise HTTPException(404, "validated video is unavailable") from exc
        size = path.stat().st_size
        headers = {"Accept-Ranges": "bytes", "Content-Disposition": 'inline; filename="output.mp4"'}
        if range_header:
            bounds = _parse_range(range_header, size)
            if bounds:
                start, end = bounds
                headers["Content-Range"] = f"bytes {start}-{end}/{size}"
                with path.open("rb") as stream:
                    stream.seek(start)
                    body = stream.read(end - start + 1)
                return Response(content=body, status_code=206, media_type="video/mp4", headers=headers)
        return Response(content=path.read_bytes(), status_code=200, media_type="video/mp4", headers=headers)

    @app.get("/api/jobs/{job_id}/thumbnail")
    def thumbnail(job_id: str) -> Response:
        try:
            path = service.thumbnail_path(job_id)
        except (ValueError, KeyError) as exc:
            raise HTTPException(404, "validated thumbnail is unavailable") from exc
        return Response(content=path.read_bytes(), status_code=200, media_type="image/png",
                        headers={"Cache-Control": "no-store",
                                 "Content-Disposition": 'inline; filename="thumbnail.png"'})

    @app.post("/api/jobs/{job_id}/approve", status_code=200)
    def approve_job(job_id: str, body: DecisionBody) -> JSONResponse:
        """Operator decision, wired straight to the gate that verifies it.

        The body carries only who decided; eligibility is re-read from disk by
        approve(), so a browser can never assert that a job is publishable.
        """
        _require_job(job_id)
        try:
            gate = approve(job_store, job_id, operator=body.operator)
        except ApprovalRejected as exc:
            raise HTTPException(409, str(exc)) from exc
        return JSONResponse({"job_id": job_id, "state": "APPROVED", "gate": gate.as_dict()})

    @app.post("/api/jobs/{job_id}/reject", status_code=200)
    def reject_job(job_id: str, body: RejectionBody) -> JSONResponse:
        """Rejection is cheap to record and costly to fake: reason is mandatory."""
        _require_job(job_id)
        reason = body.reason.strip()
        if not reason:
            raise HTTPException(422, "reason is required")
        try:
            reject(job_store, job_id, reason=reason, operator=body.operator)
        except ApprovalRejected as exc:
            raise HTTPException(409, str(exc)) from exc
        return JSONResponse({"job_id": job_id, "state": "REJECTED", "reason": reason})

    def _require_job(job_id: str) -> None:
        try:
            job_store.get(job_id)
        except KeyError as exc:
            raise HTTPException(404, "job is unknown") from exc

    @app.post("/api/integrations/hermes/events")
    async def hermes_events(request: Request) -> JSONResponse:
        secret = _hermes_secret()
        if not secret:
            raise HTTPException(503, "Hermes observer is disabled")
        observer = HermesObserver(service.events, secret=secret)
        try:
            metadata = observer.accept(await request.body(), request.headers)
        except ObserverDisabled as exc:
            raise HTTPException(503, "Hermes observer is disabled") from exc
        except InvalidDelivery as exc:
            raise HTTPException(exc.status_code, "delivery refused") from exc
        return JSONResponse(metadata, status_code=202)

    attach_studio_routes(app, job_store)
    return app


def _hermes_secret() -> str | None:
    value = os.environ.get("SHORTS_HERMES_WEBHOOK_SECRET", "")
    return value if value.strip() else None
