"""Pixel Studio HTTP surface.

Tipis dengan sengaja (AGENTS.md §5): hanya validasi request, pemanggilan
`JobStore` / `PipelineRunner` / `load_studio`, dan pemetaan ke HTTP.
Tidak ada business logic di sini.
"""
from __future__ import annotations

import os
import threading
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from packages.core.config import JOBS_DIR, get_settings
from packages.core.orchestration import JobState, JobStore
from packages.core.orchestration.states import STOP_POINTS
from packages.core.pipeline import PipelineRunner
from packages.core.prompts import DEFAULT_SYSTEM
from packages.core.providers.router import UsageTracker, build_router
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

app = FastAPI(title="Pixel Studio API", version="0.1.0")

RUNS: dict[str, dict[str, Any]] = {}
RUN_LOCK = threading.Lock()
CANCELLED_RUNS: set[str] = set()


# --- auth (opsional; lokal tanpa token, remote wajib) -----------------------
def require_token(authorization: str | None = Header(default=None)) -> None:
    expected = os.environ.get("STUDIO_TOKEN", "")
    if not expected:
        return  # dipakai lokal di 127.0.0.1 tanpa token
    if authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="token tidak valid")


def _store() -> JobStore:
    settings = get_settings()
    settings.ensure_dirs()
    return JobStore(settings.db_path, JOBS_DIR)


def _studio_or_409() -> StudioConfig:
    try:
        return load_studio()
    except StudioConfigError as exc:
        raise HTTPException(status_code=409, detail=f"config/studio.json tidak valid: {exc}") from exc


def _effective() -> dict[str, Any]:
    settings = get_settings()
    return {
        "budget": {
            "max_daily_tokens": settings.budget.max_daily_tokens,
            "max_daily_cost_usd": settings.budget.max_daily_cost_usd,
            "max_retries": settings.budget.max_retries,
        },
        "production": {
            "fps": settings.production.fps,
            "target_duration_s": settings.production.target_duration_s,
            "videos_per_day": settings.production.videos_per_day,
            "tts_voice": settings.production.tts_voice,
            "tts_rate": settings.production.tts_rate,
        },
    }


# --- health ----------------------------------------------------------------
@app.get("/api/health")
def health() -> dict[str, Any]:
    settings = get_settings()
    return {"ok": True, "db": str(settings.db_path), "studio_exists": studio_path().exists()}


# --- studio config ---------------------------------------------------------
@app.get("/api/studio")
def get_studio_payload(authorization: str | None = Depends(require_token)) -> dict[str, Any]:
    saved = _studio_or_409()
    return {
        "saved": saved.model_dump(mode="json"),
        "effective": _effective(),
        "agent_keys": list(AGENT_KEYS),
        "default_prompts": dict(DEFAULT_SYSTEM),
        "runner_stops": list(STOP_POINTS),
        "studio_path": str(studio_path()),
        "studio_exists": studio_path().exists(),
    }


@app.put("/api/studio")
def put_studio(payload: StudioConfig, authorization: str | None = Depends(require_token)) -> dict[str, Any]:
    # Pydantic memvalidasi payload sebelum ini (422 + detail per-field), jadi
    # file yang tersimpan di disk tidak pernah rusak.
    path = save_studio(payload)
    get_settings.cache_clear()
    return {"saved": payload.model_dump(mode="json"), "path": str(path), "effective": _effective()}


@app.get("/api/studio/history")
def studio_history(authorization: str | None = Depends(require_token)) -> dict[str, Any]:
    return {"history": load_history()}


class RollbackIn(BaseModel):
    name: str


@app.post("/api/studio/rollback")
def studio_rollback(payload: RollbackIn, authorization: str | None = Depends(require_token)) -> dict[str, Any]:
    try:
        restored = rollback_studio(payload.name)
    except (StudioConfigError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    get_settings.cache_clear()
    return {"restored": restored.model_dump(mode="json"), "effective": _effective()}


@app.get("/api/studio/models")
def list_models(authorization: str | None = Depends(require_token)) -> dict[str, Any]:
    settings = get_settings()
    if not settings.deepseek.configured:
        return {"models": [], "source": None, "error": "DEEPSEEK_BASE_URL / DEEPSEEK_MODEL belum dikonfigurasi"}
    headers = {"Authorization": f"Bearer {settings.deepseek.api_key}"} if settings.deepseek.api_key else {}
    try:
        resp = httpx.get(f"{settings.deepseek.base_url.rstrip('/')}/models", headers=headers, timeout=6.0)
        resp.raise_for_status()
        models = sorted({str(item.get("id")) for item in resp.json().get("data", []) if item.get("id")})
        return {"models": models, "source": settings.deepseek.base_url, "error": None}
    except (httpx.HTTPError, ValueError) as exc:
        return {"models": [], "source": settings.deepseek.base_url, "error": f"{type(exc).__name__}: {exc}"}


# --- jobs ------------------------------------------------------------------
class CreateJob(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    mode: str = Field(default="")      # "" -> ikut runner.default_mode
    stop: str = Field(default="")      # "" -> ikut runner.default_stop


class RunJob(BaseModel):
    mode: str = ""
    stop: str = ""


def _resolve_mode_stop(mode: str, stop: str) -> tuple[str, str]:
    studio = _studio_or_409()
    final_mode = mode or studio.runner.default_mode
    final_stop = stop or studio.runner.default_stop
    if final_mode not in {"mock", "live"}:
        raise HTTPException(status_code=422, detail="mode harus mock atau live")
    if final_stop not in STOP_POINTS:
        raise HTTPException(status_code=422, detail=f"stop harus salah satu dari {sorted(STOP_POINTS)}")
    return final_mode, final_stop


def _start_run(job_id: str, *, mode: str, stop: str) -> None:
    with RUN_LOCK:
        if RUNS.get(job_id, {}).get("running"):
            raise HTTPException(status_code=409, detail="job sedang berjalan")
        RUNS[job_id] = {"running": True, "mode": mode, "stop": stop, "report": None, "error": None}
        CANCELLED_RUNS.discard(job_id)

    def _worker() -> None:
        try:
            settings = get_settings()
            store = JobStore(settings.db_path, JOBS_DIR)
            report = PipelineRunner(store, settings, force_mock=(mode == "mock")).run(
                job_id, stop_at=STOP_POINTS[stop], cancelled=lambda: job_id in CANCELLED_RUNS
            )
            with RUN_LOCK:
                RUNS[job_id] = {"running": False, "mode": mode, "stop": stop,
                                "report": report.as_dict(), "error": None}
        except Exception as exc:  # noqa: BLE001 - batas thread API
            with RUN_LOCK:
                RUNS[job_id] = {"running": False, "mode": mode, "stop": stop, "report": None,
                                "error": f"{type(exc).__name__}: {exc}"}
        finally:
            with RUN_LOCK:
                CANCELLED_RUNS.discard(job_id)

    threading.Thread(target=_worker, daemon=True, name=f"run-{job_id}").start()


@app.get("/api/jobs")
def list_jobs(state: str | None = Query(default=None), limit: int = Query(default=100, le=500),
              authorization: str | None = Depends(require_token)) -> dict[str, Any]:
    store = _store()
    parsed: JobState | None = None
    if state:
        try:
            parsed = JobState(state)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="state tidak dikenal") from exc
    jobs = store.list(state=parsed, limit=limit)
    with RUN_LOCK:
        running = {k: bool(v.get("running")) for k, v in RUNS.items()}
    return {
        "jobs": [
            {"id": j.id, "title": j.title, "state": j.state.value, "attempts": j.attempts,
             "created_at": j.created_at, "updated_at": j.updated_at, "last_error": j.last_error}
            for j in jobs
        ],
        "states": [s.value for s in JobState],
        "running": running,
    }


@app.post("/api/jobs", status_code=202)
def create_job(payload: CreateJob, authorization: str | None = Depends(require_token)) -> dict[str, Any]:
    mode, stop = _resolve_mode_stop(payload.mode, payload.stop)
    job = _store().create(title=payload.title)
    _start_run(job.id, mode=mode, stop=stop)
    return {"job_id": job.id, "mode": mode, "stop": stop, "running": True}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, authorization: str | None = Depends(require_token)) -> dict[str, Any]:
    try:
        store = _store()
        record = store.get(job_id)
        events = store.events(job_id)
        root = store.artifact_root(job_id)
        artifacts = sorted(p.name for p in root.glob("*.json")) if root.exists() else []
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    with RUN_LOCK:
        run = dict(RUNS.get(job_id, {"running": False}))
    return {"record": {"id": record.id, "title": record.title, "state": record.state.value,
                       "attempts": record.attempts, "created_at": record.created_at,
                       "updated_at": record.updated_at, "last_error": record.last_error,
                       "payload": record.payload},
            "events": events, "artifacts": artifacts, "run": run}


@app.post("/api/jobs/{job_id}/run", status_code=202)
def run_job(job_id: str, payload: RunJob, authorization: str | None = Depends(require_token)) -> dict[str, Any]:
    try:
        _store().get(job_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    mode, stop = _resolve_mode_stop(payload.mode, payload.stop)
    _start_run(job_id, mode=mode, stop=stop)
    return {"job_id": job_id, "mode": mode, "stop": stop, "running": True}


@app.post("/api/jobs/{job_id}/cancel")
def cancel_run(job_id: str, authorization: str | None = Depends(require_token)) -> dict[str, Any]:
    try:
        job = _store().get(job_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if job.state not in {JobState.CANCELLED, JobState.REJECTED, JobState.PUBLISHED}:
        with RUN_LOCK:
            CANCELLED_RUNS.add(job_id)   # worker memeriksa flag ini di batas stage
    with RUN_LOCK:
        status = "running" if RUNS.get(job_id, {}).get("running") else "idle"
    return {"ok": True, "status": status}


@app.get("/api/jobs/{job_id}/artifact/{name}")
def get_artifact(job_id: str, name: str, authorization: str | None = Depends(require_token)) -> Any:
    try:
        data = _store().read_artifact(job_id, name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"artifact {name} belum ada") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return JSONResponse(content=data)


# --- usage + providers -----------------------------------------------------
@app.get("/api/usage/today")
def usage_today(authorization: str | None = Depends(require_token)) -> dict[str, Any]:
    settings = get_settings()
    tracker = UsageTracker(settings.db_path)
    totals = tracker.daily_totals()
    with tracker._connect() as conn:
        rows = conn.execute(
            "SELECT agent, provider, model, COUNT(*) AS calls, "
            "SUM(prompt_tokens + completion_tokens) AS tokens, SUM(est_cost_usd) AS cost "
            "FROM usage_log WHERE day = date('now') "
            "GROUP BY agent, provider, model ORDER BY tokens DESC"
        ).fetchall()
    return {"tokens": totals["tokens"], "cost": totals["cost"], "calls": totals["calls"],
            "budget": {"max_daily_tokens": settings.budget.max_daily_tokens,
                       "max_daily_cost_usd": settings.budget.max_daily_cost_usd},
            "by_agent": [dict(r) for r in rows]}


@app.get("/api/providers")
def providers(authorization: str | None = Depends(require_token)) -> dict[str, Any]:
    settings = get_settings()
    router = build_router(settings, db_path=settings.db_path)
    health_report = router.refresh_health()
    return {"health": [{"ref": ref, "healthy": bool(info["healthy"]), "model": info["model"]}
                       for ref, info in health_report.items()],
            "mode": {"worker_base_url": settings.deepseek.base_url or None,
                     "worker_configured": settings.deepseek.configured,
                     "strategist_model": settings.claude_cli.model}}
