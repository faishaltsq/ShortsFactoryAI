#!/usr/bin/env python3
"""Jalankan Pixel Studio API (lokal, tanpa Docker)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402


def main() -> int:
    host = os.environ.get("STUDIO_HOST", "127.0.0.1")
    port = int(os.environ.get("STUDIO_PORT", "8000"))
    uvicorn.run("apps.api.app:app", host=host, port=port, reload=False, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
