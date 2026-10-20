import asyncio
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from packages.core.orchestration import JobStore


def client_for(store):
    from apps.api.main import create_app
    return TestClient(create_app(store=store), base_url="http://localhost", client=("127.0.0.1", 45000))


def test_snapshot_is_readonly_safe_and_has_twelve_idle_roles(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDIO_TEST_API_KEY", "secret-must-not-be-reflected")
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    job = store.create(title="Video secret-must-not-be-reflected")
    client = client_for(store)
    response = client.get("/api/studio/snapshot")
    assert response.status_code == 200
    data = response.json()
    assert len(data["agents"]) == 12
    assert all(agent["status"] == "idle" for agent in data["agents"])
    assert data["jobs"][0]["id"] == job.id
    assert data["mode"] == "production" and data["health"]["hermes"] == "not_connected"
    assert "secret-must-not-be-reflected" not in response.text
    assert "api_key" not in response.text and "payload" not in response.text
    assert client.get("/api/studio/snapshot", headers={"Origin": "https://foreign.invalid"}).status_code == 403
    assert client.get("/api/studio/snapshot", headers={"Host": "foreign.invalid"}).status_code == 400
    assert client.get("/api/events?after=-1").status_code == 422
    assert client.get("/api/studio/snapshot?job_id=bad").status_code == 422
    assert client.post("/api/integrations/hermes/events", json={}).status_code == 503


def test_video_is_confined_hash_checked_and_supports_ranges(tmp_path):
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    job = store.create(title="Range response fixture, not a real rendered MP4")
    payload = b"explicit-test-bytes-not-a-real-mp4" * 10
    root = store.artifact_dir(job.id)
    (root / "output.mp4").write_bytes(payload)
    artifact = {"output_path": "output.mp4", "sha256": hashlib.sha256(payload).hexdigest(),
                "storyboard_sha256": "a" * 64, "audio_sha256": "b" * 64,
                "duration_ms": 34000, "frame_count": 1020, "probe": {}}
    store.write_artifact(job.id, "render.json", artifact)
    client = client_for(store)
    response = client.get(f"/api/jobs/{job.id}/video", headers={"Range": "bytes=0-15"})
    assert response.status_code == 206
    assert response.content == payload[:16]
    assert response.headers["content-range"] == f"bytes 0-15/{len(payload)}"
    (root / "output.mp4").write_bytes(b"changed")
    assert client.get(f"/api/jobs/{job.id}/video").status_code == 404
    artifact["output_path"] = "../outside.mp4"
    store.write_artifact(job.id, "render.json", artifact)
    assert client.get(f"/api/jobs/{job.id}/video").status_code == 404


@pytest.mark.asyncio
async def test_sse_replays_after_cursor_and_restores_snapshot(tmp_path):
    from apps.api.streaming import stream_events
    from packages.core.observability.projection import StudioService

    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    job = store.create(title="SSE")
    service = StudioService(store)
    first = service.events.emit(job_id=job.id, agent_id="ScriptAgent", event_type="stage_completed",
                                status="completed", description="script validated")
    second = service.events.emit(job_id=job.id, agent_id="RenderAgent", event_type="stage_completed",
                                 status="completed", description="render validated")

    class ConnectedRequest:
        async def is_disconnected(self):
            return False

    stream = stream_events(service, ConnectedRequest(), after=first.event_id, poll_s=0, heartbeat_s=0)
    replay = await asyncio.wait_for(anext(stream), 2)
    assert f"id: {second.event_id}\n" in replay and "event: studio\n" in replay
    snapshot = await asyncio.wait_for(anext(stream), 2)
    assert "event: snapshot\n" in snapshot
    data = json.loads(snapshot.split("data: ", 1)[1].strip())
    assert data["cursor"] == second.event_id
    await stream.aclose()
