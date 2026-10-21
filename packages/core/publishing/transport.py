"""Small injectable HTTP boundary with fixed errors and capped safe retries."""
from __future__ import annotations

import logging
import time
from typing import Any, Callable

import httpx

from .errors import PublishingError, RemoteError


class _NoTransportLog(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return False


_FILTER = _NoTransportLog()


def silence_sensitive_transport_logs() -> None:
    # httpx INFO includes full signed upload URLs. Transport debug is not an audit log.
    names = {"httpx", "httpcore", *logging.Logger.manager.loggerDict.keys()}
    for name in names:
        if name == "httpx" or name == "httpcore" or name.startswith(("httpx.", "httpcore.")):
            logger = logging.getLogger(name)
            if _FILTER not in logger.filters:
                logger.addFilter(_FILTER)


class SafeHTTP:
    def __init__(self, http: httpx.Client, *, max_attempts: int = 3, timeout_s: float = 20,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        if not 1 <= max_attempts <= 5 or not 0 < timeout_s <= 30:
            raise ValueError("invalid_http_bounds")
        self.http, self.max_attempts, self.timeout_s, self.sleep = http, max_attempts, timeout_s, sleep

    def request(self, method: str, url: str, *, retry_safe: bool, accepted: tuple[int, ...],
                **kwargs: Any) -> httpx.Response:
        count = self.max_attempts if retry_safe else 1
        for attempt in range(count):
            silence_sensitive_transport_logs()
            try:
                response = self.http.request(method, url, timeout=self.timeout_s, follow_redirects=False, **kwargs)
            except (httpx.HTTPError, OSError):
                if attempt + 1 == count:
                    raise RemoteError("remote_transport_error", retryable=True) from None
            else:
                if response.status_code in accepted:
                    return response
                retryable = response.status_code in (408, 429, 500, 502, 503, 504)
                code = "remote_session_expired" if response.status_code in (404, 410) else "remote_request_rejected"
                if not retryable or attempt + 1 == count:
                    raise RemoteError(code, retryable=retryable) from None
            self.sleep(min(2 ** attempt, 8))
        raise PublishingError("remote_attempt_cap")


def safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        value = response.json()
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (ValueError, UnicodeError):
        raise RemoteError("remote_response_invalid") from None
