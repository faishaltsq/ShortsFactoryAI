"""Studio, job and provider routes for the operator dashboard."""
from __future__ import annotations

import os
import threading
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from packages.core.config import get_settings
from packages.core.orchestration import JobState, JobStore
from packages.core.orchestration.states import STOP_POINTS
from packages.core.pipeline import PipelineRunner
from packages.core.personas import PERSONAS, TEAM
from packages.core.prompts import DEFAULT_SYSTEM
from packages.core.providers.router import UsageTracker, build_router
from packages.core.scheduler import Scheduler, status_payload
from packages.core.studio import (
    AGENT_KEYS,
    StudioConfig,
    StudioConfigError,
    load_history,
    load_studio,
    rollback_studio,
    save_studio,
    studio_path,
)


class CreateJob(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    mode: str = Field(default="", max_length=16)
    stop: str = Field(default="", max_length=32)


class RunJob(BaseModel):
    mode: str = Field(default="", max_length=16)
    stop: str = Field(default="", max_length=32)


class RollbackIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


def _safe_url(value: str | None) -> str | None:
    if not value:
        return None
    parts = urlsplit(value)
    if not parts.hostname:
        return None
    host = parts.hostname
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, parts.query, ""))


def _safe_error(exc: Exception) -> str:
    message = f"{type(exc).__name__}: {exc}"
    try:
        settings = get_settings()
        for key in (settings.deepseek.api_key, settings.strategist.api_key):
            if key:
                message = message.replace(key, "[redacted]")
    except Exception:
        return type(exc).__name__
    return message[:1000]


def _effective() -> dict[str, Any]:
    settings = get_settings()
    return {
        "budget": {
            "max_daily_tokens": settings.budget.max_daily_tokens,
            "max_daily_cost_usd": settings.budget.max_daily_cost_usd,
            "max_retries": settings.budget.max_retries,
            "unlimited": settings.budget.unlimited,
        },
        "production": {
            "fps": settings.production.fps,
            "target_duration_s": settings.production.target_duration_s,
            "videos_per_day": settings.production.videos_per_day,
            "tts_voice": settings.production.tts_voice,
            "tts_rate": settings.production.tts_rate,
        },
    }


def attach_studio_routes(app: FastAPI, job_store: JobStore) -> None:
    """Attach the Pixel Studio HTTP surface to the injected application store."""
    router = APIRouter()
    runtime: dict[str, Any] = {
        "runs": {}, "run_lock": threading.Lock(), "cancelled": set(),
        "scheduler": None, "scheduler_lock": threading.Lock(),
    }
    app.state.studio_runtime = runtime
    app.state.job_store = job_store

    def require_token(authorization: str | None = Header(default=None)) -> None:
        expected = os.environ.get("STUDIO_TOKEN", "")
        if expected and authorization != f"Bearer {expected}":
            raise HTTPException(status_code=401, detail="token tidak valid")

    def studio_or_409():
        try:
            return load_studio()
        except StudioConfigError as exc:
            raise HTTPException(status_code=409, detail=f"config/studio.json tidak valid: {exc}") from exc

    def resolve_mode_stop(mode: str, stop: str, *, job_mode: str | None = None) -> tuple[str, str]:
        studio = studio_or_409()
        final_mode = job_mode or mode or studio.runner.default_mode
        final_stop = stop or studio.runner.default_stop
        if final_mode not in {"mock", "live"}:
            raise HTTPException(status_code=422, detail="mode harus mock atau live")
        if final_stop not in STOP_POINTS:
            raise HTTPException(status_code=422, detail=f"stop harus salah satu dari {sorted(STOP_POINTS)}")
        return final_mode, final_stop

    def start_run(job_id: str, *, mode: str, stop: str) -> None:
        with runtime["run_lock"]:
            if runtime["runs"].get(job_id, {}).get("running"):
                raise HTTPException(status_code=409, detail="job sedang berjalan")
            activity_token = uuid4().hex
            runtime["runs"][job_id] = {
                "running": True, "mode": mode, "stop": stop, "report": None,
                "error": None, "activity_token": activity_token,
            }
            runtime["cancelled"].discard(job_id)

        def worker() -> None:
            run_data: dict[str, Any]
            try:
                settings = get_settings()
                report = PipelineRunner(job_store, settings, force_mock=(mode == "mock")).run(
                    job_id, stop_at=STOP_POINTS[stop],
                    cancelled=lambda: job_id in runtime["cancelled"],
                    activity_token=activity_token,
                )
                run_data = {
                    "running": False, "mode": mode, "stop": stop,
                    "report": report.as_dict(), "error": None,
                    "activity_token": activity_token,
                }
            except Exception as exc:  # noqa: BLE001 - async request boundary
                run_data = {
                    "running": False, "mode": mode, "stop": stop, "report": None,
                    "error": _safe_error(exc), "activity_token": activity_token,
                }
            finally:
                with runtime["run_lock"]:
                    runtime["cancelled"].discard(job_id)
                    runtime["runs"][job_id] = run_data

        threading.Thread(target=worker, daemon=True, name=f"run-{job_id}").start()

    def create_and_run(title: str, *, mode: str, stop: str, avoid: list[str] | None = None) -> str:
        payload: dict[str, Any] = {"avoid_titles": avoid[:60]} if avoid else {}
        job = job_store.create(title=title, payload=payload or None)
        start_run(job.id, mode=mode, stop=stop)
        return job.id

    def running_ids() -> set[str]:
        """Runs this process owns, merged with durable lease ownership.

        An API restart empties `runtime["runs"]` while a worker keeps rendering, so
        the in-memory flag alone would report a live job as idle.
        """
        with runtime["run_lock"]:
            owned = {job_id for job_id, run in runtime["runs"].items() if run.get("running")}
        return owned | job_store.active_leases()

    def active_run_ids() -> set[str]:
        with runtime["run_lock"]:
            return {job_id for job_id, run in runtime["runs"].items() if run.get("running")}

    def new_scheduler() -> Scheduler:
        return Scheduler(job_store, create_job=lambda **kwargs: create_and_run(**kwargs),
                         active_ids_fn=active_run_ids)

    def start_scheduler() -> None:
        with runtime["scheduler_lock"]:
            current = runtime["scheduler"]
            if current is not None and current.running:
                return
            try:
                studio = load_studio()
            except StudioConfigError:
                return
            if not studio.schedule.enabled:
                return
            current = new_scheduler()
            runtime["scheduler"] = current
            current.start()

    def stop_scheduler() -> None:
        with runtime["scheduler_lock"]:
            current = runtime["scheduler"]
            if current is not None:
                current.stop()
                runtime["scheduler"] = None

    app.router.on_startup.append(start_scheduler)
    app.router.on_shutdown.append(stop_scheduler)

    @router.get("/api/studio")
    def get_studio(authorization: str | None = Depends(require_token)) -> dict[str, Any]:
        saved = studio_or_409()
        return {
            "saved": saved.model_dump(mode="json"), "effective": _effective(),
            "agent_keys": list(AGENT_KEYS), "default_prompts": dict(DEFAULT_SYSTEM),
            "runner_stops": list(STOP_POINTS),
            "personas": {key: dict(value) for key, value in PERSONAS.items()},
            "team": {key: dict(value) for key, value in TEAM.items()},
            "studio_path": str(studio_path()), "studio_exists": studio_path().exists(),
        }

    @router.put("/api/studio")
    def put_studio(payload: StudioConfig, authorization: str | None = Depends(require_token)) -> dict[str, Any]:
        path = save_studio(payload)
        get_settings.cache_clear()
        return {"saved": payload.model_dump(mode="json"), "path": str(path), "effective": _effective()}

    @router.get("/api/studio/history")
    def studio_history(authorization: str | None = Depends(require_token)) -> dict[str, Any]:
        return {"history": load_history()}

    @router.post("/api/studio/rollback")
    def studio_rollback(payload: RollbackIn, authorization: str | None = Depends(require_token)) -> dict[str, Any]:
        try:
            restored = rollback_studio(payload.name)
        except (StudioConfigError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        get_settings.cache_clear()
        return {"restored": restored.model_dump(mode="json"), "effective": _effective()}

    @router.get("/api/studio/models")
    def studio_models(authorization: str | None = Depends(require_token)) -> dict[str, Any]:
        settings = get_settings()
        if not settings.deepseek.configured:
            return {"models": [], "source": None, "error": "DEEPSEEK_BASE_URL / DEEPSEEK_MODEL belum dikonfigurasi"}
        source = _safe_url(settings.deepseek.base_url)
        headers = {"Authorization": f"Bearer {settings.deepseek.api_key}"} if settings.deepseek.api_key else {}
        try:
            response = httpx.get(f"{settings.deepseek.base_url.rstrip('/')}/models", headers=headers, timeout=6.0)
            response.raise_for_status()
            models = sorted({str(item.get("id")) for item in response.json().get("data", []) if item.get("id")})
            return {"models": models, "source": source, "error": None}
        except (httpx.HTTPError, ValueError) as exc:
            return {"models": [], "source": source, "error": _safe_error(exc)}

    @router.get("/api/schedule")
    def schedule_status(authorization: str | None = Depends(require_token)) -> dict[str, Any]:
        return status_payload(runtime["scheduler"], studio_or_409().schedule)

    @router.post("/api/schedule/tick")
    def schedule_tick(authorization: str | None = Depends(require_token)) -> dict[str, Any]:
        scheduler = runtime["scheduler"]
        if scheduler is None:
            raise HTTPException(status_code=409, detail="scheduler tidak aktif; nyalakan di Studio")
        return scheduler.tick().as_dict()

    @router.post("/api/schedule/apply")
    def schedule_apply(authorization: str | None = Depends(require_token)) -> dict[str, Any]:
        with runtime["scheduler_lock"]:
            scheduler = runtime["scheduler"]
            if scheduler is not None:
                scheduler.stop()
                runtime["scheduler"] = None
            studio = studio_or_409()
            if studio.schedule.enabled:
                scheduler = new_scheduler()
                runtime["scheduler"] = scheduler
                scheduler.start()
        return status_payload(runtime["scheduler"], studio.schedule)

    @router.get("/api/jobs")
    def list_jobs(state: str | None = Query(default=None), limit: int = Query(default=100, ge=1, le=500),
                  authorization: str | None = Depends(require_token)) -> dict[str, Any]:
        try:
            parsed = JobState(state) if state else None
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="state tidak dikenal") from exc
        jobs = job_store.list(state=parsed, limit=limit)
        leased = running_ids()
        with runtime["run_lock"]:
            running = {key: bool(value.get("running")) for key, value in runtime["runs"].items()}
        for job_id in leased:
            running[job_id] = True
        return {
            "jobs": [
                {"id": job.id, "title": job.title, "state": job.state.value, "attempts": job.attempts,
                 "created_at": job.created_at, "updated_at": job.updated_at, "last_error": job.last_error}
                for job in jobs
            ],
            "states": [item.value for item in JobState], "running": running,
        }

    @router.post("/api/jobs", status_code=202)
    def create_job(payload: CreateJob, authorization: str | None = Depends(require_token)) -> dict[str, Any]:
        mode, stop = resolve_mode_stop(payload.mode, payload.stop)
        job = job_store.create(title=payload.title)
        start_run(job.id, mode=mode, stop=stop)
        return {"job_id": job.id, "mode": mode, "stop": stop, "running": True}

    @router.get("/api/jobs/{job_id}")
    def get_job(job_id: str, authorization: str | None = Depends(require_token)) -> dict[str, Any]:
        try:
            record = job_store.get(job_id)
            events = job_store.events(job_id)
            root = job_store.artifact_root(job_id)
            artifacts = sorted(path.name for path in root.glob("*.json")) if root.exists() else []
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="job is unavailable") from exc
        with runtime["run_lock"]:
            run = dict(runtime["runs"].get(job_id, {"running": False}))
        if job_id in job_store.active_leases():
            run["running"] = True
        return {
            "record": {"id": record.id, "title": record.title, "state": record.state.value,
                       "attempts": record.attempts, "created_at": record.created_at,
                       "updated_at": record.updated_at, "last_error": record.last_error,
                       "payload": record.payload},
            "events": events, "artifacts": artifacts, "run": run,
        }

    @router.post("/api/jobs/{job_id}/run", status_code=202)
    def run_job(job_id: str, payload: RunJob, authorization: str | None = Depends(require_token)) -> dict[str, Any]:
        try:
            record = job_store.get(job_id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="job is unavailable") from exc
        mode, stop = resolve_mode_stop(payload.mode, payload.stop,
                                       job_mode=record.payload.get("provider_mode"))
        start_run(job_id, mode=mode, stop=stop)
        return {"job_id": job_id, "mode": mode, "stop": stop, "running": True}

    @router.post("/api/jobs/{job_id}/cancel")
    def cancel_run(job_id: str, authorization: str | None = Depends(require_token)) -> dict[str, Any]:
        try:
            job = job_store.get(job_id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="job is unavailable") from exc
        if job.state not in {JobState.CANCELLED, JobState.REJECTED, JobState.PUBLISHED}:
            with runtime["run_lock"]:
                runtime["cancelled"].add(job_id)
        with runtime["run_lock"]:
            status = "running" if runtime["runs"].get(job_id, {}).get("running") else "idle"
        if job_id in job_store.active_leases():
            status = "running"
        return {"ok": True, "status": status}

    @router.get("/api/jobs/{job_id}/artifact/{name}")
    def get_artifact(job_id: str, name: str, authorization: str | None = Depends(require_token)) -> Any:
        try:
            data = job_store.read_artifact(job_id, name)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"artifact {name} belum ada") from exc
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="artifact tidak valid") from exc
        return JSONResponse(content=data)

    @router.get("/api/usage/today")
    def usage_today(authorization: str | None = Depends(require_token)) -> dict[str, Any]:
        settings = get_settings()
        tracker = UsageTracker(job_store.db_path)
        totals = tracker.daily_totals()
        with tracker._connect() as connection:
            rows = connection.execute(
                "SELECT agent, provider, model, COUNT(*) AS calls, "
                "SUM(prompt_tokens + completion_tokens) AS tokens, SUM(est_cost_usd) AS cost "
                "FROM usage_log WHERE day = date('now') "
                "GROUP BY agent, provider, model ORDER BY tokens DESC"
            ).fetchall()
        return {
            "tokens": totals["tokens"], "cost": totals["cost"], "calls": totals["calls"],
            "budget": {"max_daily_tokens": settings.budget.max_daily_tokens,
                       "max_daily_cost_usd": settings.budget.max_daily_cost_usd,
                       "unlimited": settings.budget.unlimited},
            "by_agent": [dict(row) for row in rows],
        }

    @router.get("/api/providers")
    def providers(authorization: str | None = Depends(require_token)) -> dict[str, Any]:
        settings = get_settings()
        provider_router = build_router(settings, db_path=job_store.db_path)
        health_report = provider_router.refresh_health()
        saved = studio_or_409()
        return {
            "health": [{"ref": name, "healthy": bool(info["healthy"]), "model": info["model"]}
                       for name, info in health_report.items()],
            "mode": {"worker_base_url": _safe_url(settings.deepseek.base_url),
                     "worker_configured": settings.deepseek.configured,
                     "strategist_model": settings.strategist.model or None},
            "editable": {
                "worker": {
                    "enabled": saved.providers.worker.enabled, "base_url": saved.providers.worker.base_url,
                    "model": saved.providers.worker.model, "temperature": saved.providers.worker.temperature,
                    "effective_base_url": _safe_url(settings.deepseek.base_url),
                    "effective_model": settings.deepseek.model or None,
                    "has_key": bool(settings.deepseek.api_key),
                    "key_origin_mismatch": settings.deepseek.key_origin_mismatch,
                    "configured": settings.deepseek.configured,
                },
                "strategist_http": {
                    "enabled": saved.providers.strategist_http.enabled,
                    "base_url": saved.providers.strategist_http.base_url,
                    "model": saved.providers.strategist_http.model,
                    "temperature": saved.providers.strategist_http.temperature,
                    "effective_base_url": _safe_url(settings.strategist.base_url),
                    "effective_model": settings.strategist.model or None,
                    "has_key": bool(settings.strategist.api_key),
                    "key_origin_mismatch": settings.strategist.key_origin_mismatch,
                    "configured": settings.strategist.configured,
                },
            },
        }

    @router.get("/api/providers/models")
    def provider_models(
        target: str = Query(default="worker", pattern="^(worker|strategist_http)$"),
        authorization: str | None = Depends(require_token),
    ) -> dict[str, Any]:
        settings = get_settings()
        config = settings.deepseek if target == "worker" else settings.strategist
        source = _safe_url(config.base_url)
        if not config.base_url:
            return {"models": [], "source": None, "error": "base_url belum dikonfigurasi"}
        parts = urlsplit(config.base_url)
        if parts.username or parts.password:
            return {"models": [], "source": source, "error": "base_url tidak boleh memuat kredensial"}
        headers = {"Authorization": f"Bearer {config.api_key}"} if config.api_key else {}
        try:
            response = httpx.get(f"{config.base_url.rstrip('/')}/models", headers=headers, timeout=8.0)
            response.raise_for_status()
            models = sorted({str(item.get("id")) for item in response.json().get("data", []) if item.get("id")})
            return {"models": models, "source": source, "error": None}
        except (httpx.HTTPError, ValueError) as exc:
            return {"models": [], "source": source, "error": _safe_error(exc)}

    app.include_router(router)
