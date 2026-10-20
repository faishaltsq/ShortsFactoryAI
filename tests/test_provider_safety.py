import pytest
import httpx

from packages.core.providers.base import ProviderError
from packages.core.providers.openai_compat import OpenAICompatProvider


def _provider():
    return OpenAICompatProvider(name="test", base_url="https://test.invalid/v1", api_key="unit-test-credential", model="test-model", max_retries=1)


def test_http_errors_do_not_echo_untrusted_provider_body(monkeypatch):
    import packages.core.providers.openai_compat as adapter

    body = "upstream reflected token: unit-test-credential"
    monkeypatch.setattr(adapter.httpx, "post", lambda *a, **kw: httpx.Response(401, text=body))
    with pytest.raises(ProviderError) as caught:
        _provider().complete(task="script", system="s", user="u")
    assert "unit-test-credential" not in str(caught.value)
    assert "401" in str(caught.value)


def test_claude_completion_disables_tools_and_session_storage(monkeypatch):
    import packages.core.providers.claude_cli as adapter
    from types import SimpleNamespace

    calls = []
    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout='{"result":"ok","usage":{"input_tokens":2,"output_tokens":1}}', stderr="")
    monkeypatch.setattr(adapter.subprocess, "run", fake_run)
    result = adapter.ClaudeCliProvider(binary="claude", model="opus").complete(task="review", system="s", user="u")
    args, kwargs = calls[0]
    assert "--tools" in args and args[args.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in args
    assert "--no-session-persistence" in args
    assert kwargs["input"]
    assert result.content == "ok"


def test_local_router_key_is_never_forwarded_to_lookalike_origin(monkeypatch):
    from packages.core.config import _deepseek_key
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.setenv("HERMES_CUSTOM_LOCALHOST_20128_API_KEY", "unit-test-credential")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "http://localhost:20128@attacker.invalid/v1")
    assert _deepseek_key() == ""


def test_health_rejects_unauthorized_endpoint(monkeypatch):
    import packages.core.providers.openai_compat as adapter

    monkeypatch.setattr(adapter.httpx, "get", lambda *a, **kw: httpx.Response(401))
    assert _provider().healthy() is False


def test_health_requires_configured_model_in_catalog(monkeypatch):
    import packages.core.providers.openai_compat as adapter

    monkeypatch.setattr(adapter.httpx, "get", lambda *a, **kw: httpx.Response(200, json={"data": [{"id": "other-model"}]}))
    assert _provider().healthy() is False
