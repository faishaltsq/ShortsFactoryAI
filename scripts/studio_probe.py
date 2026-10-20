"""Measure the studio's live path while a real render is running.

Runs one pipeline job (mock LLM providers, real Remotion + FFmpeg render) and,
while it runs, records:

- API snapshot latency (`/api/studio/snapshot` polled every 200 ms),
- the lag between an event being written to SQLite and the same event arriving
  on the SSE stream the dashboard consumes.

Prints the metrics and writes `evidence/studio-probe.json`. No assertions live
here: numbers are evidence, and the thresholds belong to whoever reads them.

Usage: uv run python scripts/studio_probe.py [--port 8018] [--poll-ms 200]
"""

from __future__ import annotations

import argparse
import http.client
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
EVIDENCE = PROJECT_ROOT / "evidence"


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return round(ordered[index], 2)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8018)
    parser.add_argument("--poll-ms", type=int, default=200)
    args = parser.parse_args()

    from packages.core.config import JOBS_DIR, get_settings
    from packages.core.observability.store import StudioEventStore
    from packages.core.orchestration import JobState, JobStore
    from packages.core.pipeline import PipelineRunner

    settings = get_settings()
    store = JobStore(settings.db_path, JOBS_DIR)
    events = StudioEventStore(store.db_path)
    job = store.create(title="Studio probe: real render measured while the console is open")

    host, port = "127.0.0.1", args.port
    stop = threading.Event()
    api_latency: list[float] = []
    sse_lag: list[float] = []
    seen: dict[int, float] = {}
    delivered: set[int] = set()
    api_failures = 0
    cursor: list[int] = [0]

    def poll_api() -> None:
        nonlocal api_failures
        url = f"http://{host}:{port}/api/studio/snapshot"
        while not stop.is_set():
            started = time.perf_counter()
            try:
                with urllib.request.urlopen(url, timeout=5) as response:
                    response.read()
                api_latency.append((time.perf_counter() - started) * 1000)
            except OSError:
                api_failures += 1
            stop.wait(args.poll_ms / 1000)

    def watch_writes() -> None:
        while not stop.is_set():
            for row in events.page(after=cursor[0], limit=100):
                cursor[0] = row.event_id
                seen.setdefault(row.event_id, time.perf_counter())
            stop.wait(0.005)

    def follow_sse() -> None:
        connection = http.client.HTTPConnection(host, port, timeout=20)
        connection.request("GET", "/api/studio/stream?after=0")
        response = connection.getresponse()
        buffer = b""
        while not stop.is_set():
            chunk = response.read1(4096)
            if not chunk:
                return
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                line = line.strip()
                if not line.startswith(b"data: "):
                    continue
                try:
                    payload = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
                if "event_id" not in payload:
                    continue
                delivered.add(payload["event_id"])
                written = seen.get(payload["event_id"])
                if written is not None:
                    sse_lag.append((time.perf_counter() - written) * 1000)
        connection.close()

    threads = [
        threading.Thread(target=poll_api, name="api-poll", daemon=True),
        threading.Thread(target=watch_writes, name="db-watch", daemon=True),
        threading.Thread(target=follow_sse, name="sse", daemon=True),
    ]
    for thread in threads:
        thread.start()

    wall_start = time.perf_counter()
    # stop_at defaults to STORYBOARD_READY in PipelineRunner; the probe wants the
    # whole path, so it runs assets -> audio -> render -> technical QC.
    result = PipelineRunner(store, settings, force_mock=True).run(
        job.id, stop_at=JobState.TECHNICAL_QC)
    wall = time.perf_counter() - wall_start

    time.sleep(1.0)  # let the tail of the log reach the connected stream
    stop.set()
    for thread in threads:
        thread.join(timeout=3)

    metrics = {
        "job_id": job.id,
        "ok": bool(result.ok),
        "final_state": result.final_state,
        "blocked_reason": result.blocked_reason,
        "run_wall_seconds": round(wall, 3),
        "stages": [{"state": s.state, "ok": s.ok, "elapsed_ms": s.elapsed_ms,
                    "detail": (s.detail or "")[:120]} for s in result.stages],
        "api_snapshot_poll_ms": {
            "samples": len(api_latency),
            "p50": _pct(api_latency, 0.5),
            "p95": _pct(api_latency, 0.95),
            "max": round(max(api_latency), 2) if api_latency else 0.0,
            "failures": api_failures,
        },
        "sse_delivery_lag_ms": {
            "samples": len(sse_lag),
            "p50": _pct(sse_lag, 0.5),
            "p95": _pct(sse_lag, 0.95),
            "max": round(max(sse_lag), 2) if sse_lag else 0.0,
        },
        "events_written": len(seen),
        "events_delivered": len(delivered),
    }
    EVIDENCE.mkdir(exist_ok=True)
    (EVIDENCE / "studio-probe.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
