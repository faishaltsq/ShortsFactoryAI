import hashlib

import pytest

from packages.core.research import fetch_sources
from packages.core.research.retrieval import clean_text, eligible_url, retrieve_or_raise


def _ok(url: str, timeout: float, max_bytes: int) -> tuple[int, bytes]:
    assert timeout > 0 and max_bytes > 0, "retrieval must pass its bounds to the fetcher"
    return 200, b"<html><body><p>Solar panels convert <b>sunlight</b> into electricity.</p></body></html>"


def test_fetch_cleans_markup_and_records_digest():
    [source] = fetch_sources(["https://example.com/a"], fetcher=_ok)
    assert source.status == "ok"
    assert source.text == "Solar panels convert sunlight into electricity."
    assert source.chars == len(source.text)
    assert source.sha256 == hashlib.sha256(
        b"<html><body><p>Solar panels convert <b>sunlight</b> into electricity.</p></body></html>"
    ).hexdigest()
    assert source.as_dict(include_text=False).keys() == {
        "url", "status", "chars", "sha256", "fetched_at"
    }


def test_only_http_and_https_are_fetched():
    calls: list[str] = []

    def spy(url, timeout, max_bytes):
        calls.append(url)
        return 200, b"page body long enough to keep"

    urls = ["file:///etc/passwd", "ftp://example.com/x", "javascript:alert(1)", "https://example.com/ok"]
    results = fetch_sources(urls, fetcher=spy)
    assert [r.status for r in results] == ["skipped", "skipped", "skipped", "ok"]
    assert calls == ["https://example.com/ok"], "ineligible schemes must never reach the network"


def test_eligible_url_accepts_only_web_schemes():
    assert eligible_url("https://nasa.gov/press")
    assert not eligible_url("http://localhost:8018/x"), "untrusted sources may not target local services"
    assert not eligible_url("data:text/html,<script>x</script>")
    assert not eligible_url("https://")
    assert not eligible_url("")


def test_distinct_urls_are_deduplicated_and_capped():
    urls = [f"https://example.com/{i}" for i in range(10)] + ["https://example.com/0"]
    results = fetch_sources(urls, fetcher=_ok, max_sources=3)
    assert len(results) == 3
    assert len({r.url for r in results}) == 3


def test_fetch_failure_is_recorded_not_raised():
    def boom(url, timeout, max_bytes):
        raise TimeoutError("read timed out")

    [source] = fetch_sources(["https://example.com/slow"], fetcher=boom)
    assert source.status == "error"
    assert "TimeoutError" in source.error
    assert source.chars == 0


def test_http_error_status_is_kept_verbatim():
    def not_found(url, timeout, max_bytes):
        return 404, b"missing"

    [source] = fetch_sources(["https://example.com/gone"], fetcher=not_found)
    assert source.status == "http_404"


def test_clean_text_strips_scripts_and_control_characters():
    raw = b"<style>b{}</style><script>evil()</script>ok\x00\x07   text"
    assert clean_text(raw) == "ok text"


def test_retrieve_or_raise_reports_every_failed_source():
    with pytest.raises(ValueError) as excinfo:
        retrieve_or_raise(["https://example.com/1", "https://example.com/2"], fetcher=lambda u, t, m: (503, b""))
    message = str(excinfo.value)
    assert "https://example.com/1 -> http_503" in message
    assert "https://example.com/2 -> http_503" in message
