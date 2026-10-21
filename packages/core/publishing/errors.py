"""Fixed error codes only; upstream messages and signed URLs must never escape."""
from __future__ import annotations


class PublishingError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class RemoteError(PublishingError):
    def __init__(self, code: str, *, retryable: bool = False) -> None:
        self.retryable = retryable
        super().__init__(code)
