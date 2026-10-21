"""Worker -> event store -> SSE: a connected client sees real work as it happens.

These tests drive the real ``PipelineRunner`` (mock providers, no network) so the
stream is fed by worker-owned lifecycle events rather than a fixture, and they
pin the one-way Hermes boundary at the HTTP surface.
"""

import asyncio
import json

import pytest

from packages.core.config import get_settings
from packages.core.orchestration import JobStore


class ConnectedRequest:
    async def is_disconnected(self) -> bool:
        return False


async def _read_until_snapshot(stream) -> dict:
    for _ in range(5):
        frame = await asyncio.wait_for(anext(stream), 5)
        if frame.startswith("id:") and "event: snapshot\n" in frame:
            return json.loads(frame.split("data: ", 1)[1].strip())
    raise AssertionError("no snapshot frame was restored for the client")


async def _next_frame(stream, timeout: float) -> str | None:
    """None means "still silent"; an exhausted stream raises StopAsyncIteration."""
    try:
        return await asyncio.wait_for(anext(stream), timeout)
    except asyncio.TimeoutError:
        return None


def _split_frames(chunk: str) -> list[str]:
    """One yield can carry several SSE frames back to back; split them apart."""
    return [part + "\n\n" for part in chunk.split("\n\n") if part.strip()]


@pytest.mark.asyncio
async def test_sse_delivers_worker_events_produced_after_the_client_connected(tmp_path):
    from apps.api.streaming import stream_events
    from packages.core.observability.projection import StudioService
    from packages.core.pipeline import PipelineRunner

    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    job = store.create(title="Live worker fixture, mock providers only")
    service = StudioService(store)

    stream = stream_events(service, ConnectedRequest(), after=0, poll_s=0, heartbeat_s=0)
    snapshot = await _read_until_snapshot(stream)
    assert snapshot["cursor"] == 0 and all(agent["status"] == "idle" for agent in snapshot["agents"])

    async def run_worker() -> None:
        await asyncio.to_thread(PipelineRunner(store, get_settings(), force_mock=True).run, job.id)

    worker = asyncio.create_task(run_worker())
    frames: list[str] = []
    try:
        while not worker.done():
            frame = await _next_frame(stream, 5)
            if frame is not None:
                frames.extend(f for f in _split_frames(frame) if "event: studio" in f)
        await worker
        # The lifecycle projection keeps writing for a moment after the worker
        # returns, so wait for the log to go quiet before draining the stream.
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 10
        last_cursor_seen = -1
        quiet_since = loop.time()
        while loop.time() < deadline:
            cursor_now = service.snapshot()["cursor"]
            if cursor_now != last_cursor_seen:
                last_cursor_seen, quiet_since = cursor_now, loop.time()
            elif loop.time() - quiet_since >= 0.6:
                break
            await asyncio.sleep(0.1)
        while True:  # then drain whatever the worker published
            frame = await _next_frame(stream, 0.5)
            if frame is None:
                break
            frames.extend(f for f in _split_frames(frame) if "event: studio" in f)
    except StopAsyncIteration:
        await worker
    await stream.aclose()

    studio = [frame for frame in frames if "event: studio" in frame]
    payload = json.loads(studio[0].split("data: ", 1)[1].strip())
    assert payload["job_id"] == job.id
    assert payload["agent_id"] and payload["description"]
    assert payload["source"] == "mock"
    assert all(frame.startswith("id:") for frame in studio)

    # Every delivered frame carries a monotonic cursor, so a reconnecting client
    # never has to ask the server to rewind.
    cursor = [int(frame.split("\n", 1)[0].split(": ", 1)[1]) for frame in studio]
    assert cursor == sorted(cursor)
    assert service.snapshot()["cursor"] == cursor[-1]
    assert all("api_key" not in frame and "secret" not in frame.lower() for frame in frames)


@pytest.mark.asyncio
async def test_projection_reflects_the_worker_run_instead_of_faking_progress(tmp_path):
    from apps.api.streaming import stream_events
    from packages.core.observability.projection import StudioService
    from packages.core.pipeline import PipelineRunner

    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    job = store.create(title="Projection reflects worker output")
    service = StudioService(store)
    stream = stream_events(service, ConnectedRequest(), after=0, poll_s=0, heartbeat_s=0)
    await _read_until_snapshot(stream)
    await stream.aclose()

    await asyncio.to_thread(PipelineRunner(store, get_settings(), force_mock=True).run, job.id)

    data = service.snapshot(job_id=job.id, mode="production")
    stages = {agent["agent_id"]: agent for agent in data["agents"]}
    for agent_id in ("ResearchAgent", "ScriptAgent", "StoryboardAgent", "QualityAgent", "MetadataAgent"):
        assert stages[agent_id]["status"] != "idle"
        assert stages[agent_id]["event_id"] > 0
        assert stages[agent_id]["job_id"] == job.id
    render = stages["RenderAgent"]
    assert render["progress"] is None or 0 <= render["progress"] <= 100


def test_api_exposes_hermes_as_one_way_ingest_only(tmp_path):
    from apps.api.main import create_app

    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    app = create_app(store)
    routes = [r for r in app.routes if "hermes" in getattr(r, "path", "")]
    assert [(sorted(r.methods), r.path) for r in routes] == [(["POST"], "/api/integrations/hermes/events")]
