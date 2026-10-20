"""Provider contract. Every model backend implements this and nothing else."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

Tier = Literal["worker", "strategist"]


class ProviderError(RuntimeError):
    """Raised when a provider call fails permanently (after bounded retries)."""

    def __init__(self, message: str, *, provider: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.provider = provider
        self.retryable = retryable


class BudgetExceededError(RuntimeError):
    """Raised before a call when the daily token/cost budget is spent."""


@dataclass
class ProviderResult:
    content: str
    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    elapsed_ms: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@runtime_checkable
class Provider(Protocol):
    name: str
    tier: Tier

    def healthy(self) -> bool:
        """Cheap liveness probe. False means the router must fall back."""
        ...

    def complete(self, *, task: str, system: str, user: str) -> ProviderResult:
        """Run one completion. Raises ProviderError on failure."""
        ...


def now_ms() -> int:
    return int(time.time() * 1000)
