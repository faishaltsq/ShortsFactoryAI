"""Safe projections of persisted production truth; no HTTP or provider calls."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from ..artifacts import validate_artifact
from ..media.process import checked_path, sha256_file
from ..orchestration.jobstore import JobStore
from .events import AGENT_IDS, safe_text, utc_now
from .store import StudioEventStore


def job_source(payload: dict) -> str:
    if payload.get("studio_fixture") is True:
        return "demo_fixture"
    return "mock" if payload.get("provider_mode") == "mock" else "production"


class StudioService:
    def __init__(self, store: JobStore) -> None:
        self.store = store
        self.events = StudioEventStore(store.db_path)

    def job_root(self, job_id: str) -> Path:
        root = self.store.artifact_root(job_id).resolve()
        if not root.is_relative_to(self.store.artifacts_root.resolve()):
            raise ValueError("job directory escaped artifact root")
        return root

    def _artifact(self, job_id: str, name: str) -> dict | None:
        try:
            path = checked_path(self.job_root(job_id), name)
            if not path.is_file() or path.stat().st_size > 2_000_000:
                return None
            return validate_artifact(name, json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError):
            return None

    def video_path(self, job_id: str) -> Path:
        self.store.get(job_id)
        render = self._artifact(job_id, "render.json")
        if not render:
            raise ValueError("validated video is unavailable")
        path = checked_path(self.job_root(job_id), render["output_path"])
        if not path.is_file() or path.stat().st_size == 0 or sha256_file(path) != render["sha256"]:
            raise ValueError("validated video is unavailable")
        return path

    def _job_view(self, row: dict, mode: str) -> dict:
        render = self._artifact(row["id"], "render.json")
        qc = self._artifact(row["id"], "qc.json")
        script = self._artifact(row["id"], "script.json")
        available = False
        if render:
            try:
                path = checked_path(self.job_root(row["id"]), render["output_path"])
                available = path.is_file() and path.stat().st_size > 0
            except (OSError, ValueError):
                available = False
        suffix = "?demo=true" if mode == "demo" else ""
        technical = qc["technical_pass"] if qc and render and qc["render_sha256"] == render["sha256"] else None
        return {
            "id": row["id"], "title": safe_text(row["title"], 160), "state": row["state"],
            "source": job_source(row["payload"]), "created_at": row["created_at"], "updated_at": row["updated_at"],
            "approval_required": row["state"] == "READY_FOR_APPROVAL",
            "video": {"available": available, "url": f"/api/jobs/{row['id']}/video{suffix}" if available else None,
                      "duration_ms": render["duration_ms"] if render and available else None},
            "quality": {"technical": technical, "editorial": None,
                        "verification": script.get("verification_status", "unverified") if script else "unverified",
                        "checks": qc["checks"] if qc and technical is not None else {}},
        }

    def _hermes_health(self) -> dict:
        with self.events.connect() as conn:
            exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hermes_deliveries'").fetchone()
            received = conn.execute("SELECT MAX(received_at) FROM hermes_deliveries").fetchone()[0] if exists else None
        return {
            "database": "ok", "hermes": ("connected" if time.time() - received < 60 else "stale") if received else "not_connected",
            "hermes_last_seen": datetime.fromtimestamp(received, timezone.utc).isoformat() if received else None,
        }

    def snapshot(self, *, job_id: str | None = None, mode: str = "production") -> dict:
        state = self.events.raw_snapshot(job_id=job_id)
        timestamp = utc_now().isoformat()
        projected: dict[str, list[dict]] = {agent: [] for agent in AGENT_IDS}
        now = time.time()
        for event in state["latest"]:
            view = event.model_dump(mode="json")
            lease = state["leases"].get(event.job_id)
            stale = (event.status == "working" and event.source != "demo_fixture" and
                     (not lease or lease["run_id"] != event.run_id or lease["expires_at"] <= now))
            view["stale"] = stale
            if stale:
                view["status"] = "waiting"
                view["description"] = "Worker tidak aktif; menunggu resume tervalidasi."
            projected[event.agent_id].append(view)
        agents = []
        for agent_id in AGENT_IDS:
            candidates = projected[agent_id]
            if candidates:
                agents.append(max(candidates, key=lambda e: (e["status"] == "working", e["event_id"])))
            else:
                agents.append({
                    "event_id": 0, "job_id": "", "agent_id": agent_id, "event_type": "idle", "status": "idle",
                    "timestamp": timestamp, "description": "Belum ada aktivitas yang direkam.", "progress": None,
                    "model": None, "stage": None, "run_id": None,
                    "source": "demo_fixture" if mode == "demo" else "production", "stale": False,
                })
        return {
            "cursor": state["cursor"], "timestamp": timestamp, "mode": mode, "agents": agents,
            "jobs": [self._job_view(row, mode) for row in state["jobs"]],
            "events": [event.model_dump(mode="json") for event in state["events"]], "health": self._hermes_health(),
        }
