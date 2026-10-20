"""Read-only Server-Sent Events stream driven by the persisted event log."""
from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, AsyncIterator

if TYPE_CHECKING:  # pragma: no cover - typing only
    from packages.core.observability.projection import StudioService

POLL_S = 0.5
HEARTBEAT_S = 15.0


def _event_frame(event: dict) -> str:
    return f"id: {event['event_id']}\nevent: studio\ndata: {json.dumps(event, ensure_ascii=False, allow_nan=False)}\n\n"


def _events_frame(events: list[dict]) -> str:
    return "".join(_event_frame(event) for event in events)


def _snapshot_frame(snapshot: dict, cursor: int) -> str:
    payload = dict(snapshot)
    payload["cursor"] = min(cursor, int(payload.get("cursor", cursor)))
    return f"id: {payload['cursor']}\nevent: snapshot\ndata: {json.dumps(payload, ensure_ascii=False, allow_nan=False)}\n\n"


async def stream_events(service: "StudioService", request, *, after: int = 0,
                        poll_s: float | None = None, heartbeat_s: float | None = None) -> AsyncIterator[str]:
    """Replay from a cursor, restore a full snapshot, then follow the log until disconnect."""
    poll = POLL_S if poll_s is None else max(0.0, poll_s)
    beat = HEARTBEAT_S if heartbeat_s is None else max(0.0, heartbeat_s)
    cursor = max(0, after)

    replay = service.events.page(after=cursor, limit=500)
    if replay:
        cursor = replay[-1].event_id
        yield _events_frame([event.model_dump(mode="json") for event in replay])
    yield _snapshot_frame(service.snapshot(), cursor)

    last_beat = time.monotonic()
    while not await request.is_disconnected():
        events = service.events.page(after=cursor, limit=100)
        if events:
            cursor = events[-1].event_id
            last_beat = time.monotonic()
            yield _events_frame([event.model_dump(mode="json") for event in events])
            continue
        now = time.monotonic()
        if beat > 0 and now - last_beat >= beat:
            last_beat = now
            yield ": keep-alive\n\n"
        await asyncio.sleep(poll)
