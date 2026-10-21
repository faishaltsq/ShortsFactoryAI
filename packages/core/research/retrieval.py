"""Fetch bounded, plain-text copies of the cited sources.

The page body is untrusted input: it is size-capped before it is read in full,
stripped of markup and control characters, and stored as evidence text. Nothing
here executes, evaluates or interprets page content.
"""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlparse

DEFAULT_MAX_BYTES = 512 * 1024
DEFAULT_TIMEOUT_S = 15.0
DEFAULT_MAX_SOURCES = 5
MAX_TEXT_CHARS = 200_000

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MARKUP = re.compile(r"<[^>]{0,400}>")
_SCRIPT = re.compile(r"(?is)<(script|style)[^>]*>.*?</\1>")
_WHITESPACE = re.compile(r"\s+")

Fetcher = Callable[[str, float, int], "tuple[int, bytes]"]


class RetrievalError(ValueError):
    """A source could not be retrieved or was not eligible for retrieval."""


@dataclass(frozen=True)
class FetchedSource:
    url: str
    status: str
    chars: int = 0
    sha256: str = ""
    fetched_at: str = ""
    text: str = ""
    error: str | None = None

    def as_dict(self, *, include_text: bool = False) -> dict[str, object]:
        data: dict[str, object] = {
            "url": self.url,
            "status": self.status,
            "chars": self.chars,
            "sha256": self.sha256,
            "fetched_at": self.fetched_at,
        }
        if self.error:
            data["error"] = self.error
        if include_text:
            data["text"] = self.text
        return data


def http_fetch(url: str, timeout: float = DEFAULT_TIMEOUT_S, max_bytes: int = DEFAULT_MAX_BYTES) -> tuple[int, bytes]:
    """GET one http(s) URL. Reads at most ``max_bytes`` so a hostile server cannot pin memory."""
    import urllib.error
    import urllib.request

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "shorts-factory/0.1 (+source verification)",
            "Accept": "text/html,text/plain;q=0.9,*/*;q=0.1",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - scheme checked by caller
        status = getattr(response, "status", 200) or 200
        body = response.read(max_bytes + 1)
    if len(body) > max_bytes:
        body = body[:max_bytes]
    return int(status), body


def eligible_url(url: str) -> bool:
    scheme = urlparse(url).scheme.lower()
    return scheme in {"http", "https"} and bool(urlparse(url).netloc)


def clean_text(body: bytes) -> str:
    """Decode to plain, single-spaced text. Markup is evidence noise, not content."""
    raw = body.decode("utf-8", errors="replace")
    raw = _SCRIPT.sub(" ", raw)
    raw = _MARKUP.sub(" ", raw)
    raw = _CONTROL.sub(" ", raw)
    return _WHITESPACE.sub(" ", raw).strip()[:MAX_TEXT_CHARS]


def fetch_sources(
    urls: list[str],
    *,
    fetcher: Fetcher | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    timeout: float = DEFAULT_TIMEOUT_S,
    max_sources: int = DEFAULT_MAX_SOURCES,
) -> list[FetchedSource]:
    """Retrieve up to ``max_sources`` distinct http(s) URLs, recording failures honestly."""
    do_fetch = fetcher or http_fetch
    results: list[FetchedSource] = []
    seen: set[str] = set()
    for url in urls:
        if len(results) >= max_sources:
            break
        if not url or url in seen:
            continue
        seen.add(url)
        if not eligible_url(url):
            results.append(FetchedSource(url=url, status="skipped", error="scheme or host is not http(s)"))
            continue
        try:
            status, body = do_fetch(url, timeout, max_bytes)
        except Exception as exc:  # network failure must not kill the job; it must be recorded
            results.append(FetchedSource(url=url, status="error", error=f"{type(exc).__name__}: {exc}"[:200]))
            continue
        text = clean_text(body)
        results.append(
            FetchedSource(
                url=url,
                status="ok" if 200 <= status < 400 else f"http_{status}",
                chars=len(text),
                sha256=hashlib.sha256(body).hexdigest(),
                fetched_at=timestamp(),
                text=text,
            )
        )
    return results


def retrieve_or_raise(urls: list[str], **kwargs: object) -> list[FetchedSource]:
    """Fetch sources and fail loudly when none could be read.

    Used by the pipeline for factual scripts: a factual script whose sources
    cannot be read cannot be verified, so it must not quietly pass as verified.
    """
    sources = fetch_sources(urls, **kwargs)
    if any(source.status == "ok" and source.text for source in sources):
        return sources
    raise RetrievalError(
        "no source could be retrieved for verification: "
        + "; ".join(f"{source.url} -> {source.status}" for source in sources or [])
    )


def timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
