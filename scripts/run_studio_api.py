#!/usr/bin/env python3
"""Run the local studio API without Docker."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402


def main() -> int:
    host = os.environ.get("STUDIO_HOST", "127.0.0.1")
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("STUDIO_HOST must be a loopback address")
    port = int(os.environ.get("STUDIO_PORT", "8018"))
    if not 1 <= port <= 65535:
        raise ValueError("STUDIO_PORT must be between 1 and 65535")
    uvicorn.run("apps.api.server:app", host=host, port=port, reload=False, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
