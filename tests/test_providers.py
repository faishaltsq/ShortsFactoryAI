import pytest

from packages.core.config import get_settings
from packages.core.providers import BudgetExceededError, MockProvider, ProviderRouter
from packages.core.providers.base import ProviderError
from packages.core.providers.claude_cli import ClaudeCliProvider
from packages.core.providers.router import UsageTracker


class BoomProvider:
    name = "boom"
    tier = "worker"

    def healthy(self):
        return True

    def complete(self, **kwargs):
        raise ProviderError("always down", provider="boom", retryable=True)


def test_mock_returns_valid_json():
    mock = MockProvider()
    result = mock.complete(task="research", system="s", user="u")
    assert result.content.lstrip().startswith("{")


def test_router_falls_back_to_mock_on_failure():
    router = ProviderRouter(worker_chain=[BoomProvider(), MockProvider()], strategist_chain=[MockProvider()])
    result = router.call(agent="ResearchAgent", tier="worker", task="research", system="s", user="u")
    assert result.provider == "mock"
    assert any("boom" in note for note in result.raw["fallback_notes"])


def test_router_no_mock_raises(tmp_path):
    router = ProviderRouter(worker_chain=[BoomProvider()], strategist_chain=[])
    with pytest.raises(ProviderError):
        router.call(
            agent="ResearchAgent", tier="worker", task="research",
            system="s", user="u", allow_mock=False,
        )


def test_budget_blocks_then_releases(tmp_env):
    tracker = UsageTracker(tmp_env["db"])
    router = ProviderRouter(worker_chain=[MockProvider()], strategist_chain=[], tracker=tracker)
    router.call(agent="a", tier="worker", task="research", system="s", user="u")
    totals = tracker.daily_totals()
    assert totals["calls"] == 1
    assert totals["tokens"] > 0

    # Squeeze the budget below what the mock just consumed.
    import packages.core.providers.router as router_mod

    original = get_settings().budget
    try:
        class _Low:
            max_daily_tokens = 1
            max_daily_cost_usd = 100.0

        router_mod.get_settings = lambda: type("S", (), {"budget": _Low()})()
        with pytest.raises(BudgetExceededError):
            router.call(agent="a", tier="worker", task="research", system="s", user="u")
    finally:
        router_mod.get_settings = get_settings
    assert original.max_daily_tokens >= 1


def test_claude_cli_healthy_probe(monkeypatch):
    from types import SimpleNamespace
    import packages.core.providers.claude_cli as cli

    monkeypatch.setattr(cli.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))
    provider = ClaudeCliProvider(binary="claude", model="opus")
    assert provider.healthy() is True
