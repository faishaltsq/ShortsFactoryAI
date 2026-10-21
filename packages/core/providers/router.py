"""Provider routing + daily budget enforcement.

Routing is explicit: agents declare a tier, the router returns the first
healthy provider in that tier's chain, else MockProvider. Nothing in the
system may reach a provider outside this module.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from ..config import Settings, get_settings
from .base import BudgetExceededError, Provider, ProviderError, ProviderResult
from .claude_cli import ClaudeCliProvider
from .codex_cli import CodexCliProvider
from .mock import MockProvider
from .openai_compat import OpenAICompatProvider

# Rough USD per 1M tokens. Overridable per deployment; used for budget math only.
PRICE_TABLE = {"worker": (0.14, 0.28), "strategist": (2.5, 12.0)}


def _utc_day() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")


class UsageTracker:
    """Persists per-call usage and enforces daily token/cost limits."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS usage_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    day TEXT NOT NULL,
                    job_id TEXT,
                    agent TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt_tokens INTEGER NOT NULL,
                    completion_tokens INTEGER NOT NULL,
                    est_cost_usd REAL NOT NULL,
                    elapsed_ms INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_usage_day ON usage_log(day)"
            )

    def record(self, *, job_id: str | None, agent: str, result: ProviderResult, tier: str) -> float:
        price_in, price_out = PRICE_TABLE.get(tier, PRICE_TABLE["worker"])
        cost = 0.0 if result.provider == "mock" else (result.prompt_tokens * price_in + result.completion_tokens * price_out) / 1_000_000
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO usage_log
                    (day, job_id, agent, provider, model, prompt_tokens, completion_tokens, est_cost_usd, elapsed_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _utc_day(),
                    job_id,
                    agent,
                    result.provider,
                    result.model,
                    result.prompt_tokens,
                    result.completion_tokens,
                    round(cost, 6),
                    result.elapsed_ms,
                ),
            )
        return cost

    def daily_totals(self, day: str | None = None) -> dict[str, float]:
        day = day or _utc_day()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(prompt_tokens + completion_tokens), 0) AS tokens, "
                "COALESCE(SUM(est_cost_usd), 0) AS cost, COUNT(*) AS calls "
                "FROM usage_log WHERE day = ?",
                (day,),
            ).fetchone()
        return {"tokens": float(row["tokens"]), "cost": float(row["cost"]), "calls": float(row["calls"])}


@dataclass
class ProviderRouter:
    worker_chain: list[Provider] = field(default_factory=list)
    strategist_chain: list[Provider] = field(default_factory=list)
    tracker: UsageTracker | None = None
    job_id: str | None = None
    # Live runs must not silently accept mock content: agents read this.
    allow_mock_default: bool = True
    # Notes from the most recent call (fallback reasons). Surfaced in stage detail.
    last_notes: list[str] = field(default_factory=list)
    _health_cache: dict[str, bool] = field(default_factory=dict)
    _failures: dict[str, int] = field(default_factory=dict)

    def health(self) -> dict[str, dict[str, object]]:
        report: dict[str, dict[str, object]] = {}
        for tier, chain in (("worker", self.worker_chain), ("strategist", self.strategist_chain)):
            for p in chain:
                if p.name not in self._health_cache:
                    try:
                        self._health_cache[p.name] = bool(p.healthy())
                    except Exception:
                        self._health_cache[p.name] = False
                report[f"{tier}:{p.name}"] = {
                    "healthy": self._health_cache[p.name],
                    "model": getattr(p, "model", "-"),
                }
        return report

    def refresh_health(self) -> dict[str, dict[str, object]]:
        self._health_cache.clear()
        return self.health()

    def _chain(self, tier: str) -> list[Provider]:
        return self.strategist_chain if tier == "strategist" else self.worker_chain

    def _check_budget(self) -> None:
        if self.tracker is None:
            return
        settings = get_settings()
        totals = self.tracker.daily_totals()
        if totals["tokens"] >= settings.budget.max_daily_tokens:
            raise BudgetExceededError(
                f"daily token budget spent: {int(totals['tokens'])}/{settings.budget.max_daily_tokens}"
            )
        if totals["cost"] >= settings.budget.max_daily_cost_usd:
            raise BudgetExceededError(
                f"daily cost budget spent: ${totals['cost']:.4f}/${settings.budget.max_daily_cost_usd:.2f}"
            )

    _FAILURE_COOLDOWN = 3  # consecutive failures before a provider is benched

    def _mark_failure(self, name: str) -> None:
        """One bad response must not bench a provider for the whole process."""
        self._failures[name] = self._failures.get(name, 0) + 1
        if self._failures[name] >= self._FAILURE_COOLDOWN:
            self._health_cache[name] = False

    def call(
        self,
        *,
        agent: str,
        tier: str,
        task: str,
        system: str,
        user: str,
        allow_mock: bool | None = None,
    ) -> ProviderResult:
        """Bounded call: budget check -> first healthy provider -> mock fallback.

        `allow_mock=None` reads the router default so live runs fail loudly
        instead of silently producing fixture content.
        """
        if allow_mock is None:
            allow_mock = self.allow_mock_default
        self._check_budget()
        errors: list[str] = []
        chain = self._chain(tier)
        for provider in chain:
            if provider.name == "mock" and not allow_mock:
                continue
            if provider.name not in self._health_cache:
                try:
                    self._health_cache[provider.name] = bool(provider.healthy())
                except Exception:
                    self._health_cache[provider.name] = False
            if provider.name in self._health_cache and not self._health_cache[provider.name]:
                errors.append(f"{provider.name}: unhealthy")
                continue
            try:
                result = provider.complete(task=task, system=system, user=user)
            except ProviderError as exc:
                errors.append(f"{provider.name}: {exc}")
                self._mark_failure(provider.name)
                continue
            except Exception as exc:  # noqa: BLE001 - adapter boundary
                errors.append(f"{provider.name}: {type(exc).__name__}: {exc}")
                self._mark_failure(provider.name)
                continue
            self._failures.pop(provider.name, None)
            if self.tracker is not None:
                self.tracker.record(job_id=self.job_id, agent=agent, result=result, tier=tier)
            result.raw.setdefault("fallback_notes", errors)
            self.last_notes = list(errors)
            return result

        if allow_mock:
            mock = MockProvider()
            result = mock.complete(task=task, system=system, user=user)
            result.raw["fallback_notes"] = errors + ["mock-fallback"]
            self.last_notes = list(errors) + ["mock-fallback"]
            if self.tracker is not None:
                self.tracker.record(job_id=self.job_id, agent=agent, result=result, tier=tier)
            return result

        self.last_notes = list(errors)
        raise ProviderError("all providers failed: " + "; ".join(errors), provider="router")


def build_router(settings: Settings | None = None, *, job_id: str | None = None, db_path: Path | None = None, mock_only: bool = False) -> ProviderRouter:
    settings = settings or get_settings()
    tracker = UsageTracker(db_path or settings.db_path)
    if mock_only:
        return ProviderRouter(worker_chain=[MockProvider()], strategist_chain=[MockProvider()], tracker=tracker, job_id=job_id)

    worker_chain: list[Provider] = []
    if settings.deepseek.configured:
        worker_chain.append(
            OpenAICompatProvider(
                name="deepseek",
                base_url=settings.deepseek.base_url,
                api_key=settings.deepseek.api_key,
                model=settings.deepseek.model,
                tier="worker",
                timeout_s=settings.budget.request_timeout_s,
            )
        )
    worker_chain.append(MockProvider())

    strategist_chain: list[Provider] = [
        ClaudeCliProvider(
            binary=settings.claude_cli.binary,
            model=settings.claude_cli.model,
            tier="strategist",
            timeout_s=settings.claude_cli.timeout_s,
        ),
    ]
    if settings.codex_cli.enabled:
        strategist_chain.append(
            CodexCliProvider(
                binary=settings.codex_cli.binary,
                model=settings.codex_cli.model,
                tier="strategist",
                timeout_s=settings.codex_cli.timeout_s,
            )
        )
    strategist_chain.append(MockProvider())

    router = ProviderRouter(
        worker_chain=worker_chain,
        strategist_chain=strategist_chain,
        tracker=tracker,
        job_id=job_id,
    )
    # Prime health lazily on first call; expose for dashboard.
    return router
