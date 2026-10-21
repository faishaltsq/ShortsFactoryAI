"""Monotonic progress exclusively from real Remotion CLI frame counters."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class RenderProgress:
    phase: Literal["rendered", "encoded"]
    completed: int
    total: int
    percent: float


class RemotionProgress:
    def __init__(self, total_frames: int) -> None:
        if total_frames <= 0:
            raise ValueError("frame count must be positive")
        self.total = total_frames
        self._buffer = ""
        self._percent = 0.0

    def feed(self, chunk: str) -> list[RenderProgress]:
        text = self._buffer + re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", chunk)
        lines = re.split(r"[\r\n]+", text)
        self._buffer = lines.pop()[-4096:]
        newest = None
        for line in lines:
            match = re.search(r"\b(Rendered|Encoded)\s+(\d+)/(\d+)", line)
            if not match:
                continue
            count, total = int(match[2]), int(match[3])
            if total != self.total or not 0 <= count <= total:
                continue
            encoded = match[1] == "Encoded"
            percent = round(90 + 9 * count / total if encoded else 90 * count / total, 2)
            if percent > self._percent:
                self._percent = percent
                newest = RenderProgress("encoded" if encoded else "rendered", count, total, percent)
        return [newest] if newest else []
