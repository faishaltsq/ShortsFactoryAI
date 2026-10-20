"""Edge neural TTS adapter with real word timestamps and bounded retries."""
from __future__ import annotations
import asyncio
import time
from pathlib import Path


class EdgeTTSProvider:
    def __init__(self, *, voice: str, rate: str, attempts: int = 3, timeout_s: float = 90) -> None:
        self.voice, self.rate = voice, rate
        self.attempts = max(1, min(attempts, 3))
        self.timeout_s = timeout_s

    async def _stream(self, text: str, output: Path) -> list[dict]:
        import edge_tts

        words = []
        communicate = edge_tts.Communicate(text, self.voice, rate=self.rate, boundary="WordBoundary")
        with output.open("wb") as stream:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    stream.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    words.append({"text": chunk["text"], "startMs": round(chunk["offset"] / 10000),
                                  "endMs": round((chunk["offset"] + chunk["duration"]) / 10000)})
        if not words or output.stat().st_size == 0:
            raise RuntimeError("TTS returned no audio or word boundaries")
        return words

    def synthesize(self, text: str, output: Path) -> list[dict]:
        for attempt in range(self.attempts):
            try:
                return asyncio.run(asyncio.wait_for(self._stream(text, output), timeout=self.timeout_s))
            except Exception as exc:
                if attempt + 1 == self.attempts:
                    raise RuntimeError(f"TTS failed after {self.attempts} attempts ({type(exc).__name__})") from exc
                time.sleep(2 ** (attempt + 1))
        raise RuntimeError("TTS retry cap exhausted")
