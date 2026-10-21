import json
from types import SimpleNamespace

import pytest

from packages.core.config import CodexCliConfig, Settings
from packages.core.providers.base import ProviderError
from packages.core.providers.codex_cli import CodexCliProvider
from packages.core.providers.router import build_router


def test_strategist_falls_back_to_codex_before_mock(tmp_path):
    settings = Settings(codex_cli=CodexCliConfig(binary="codex", model="gpt-6.1-sol"))
    router = build_router(settings, db_path=tmp_path / "usage.sqlite")
    assert [p.name for p in router.strategist_chain] == ["claude-cli", "codex-cli", "mock"]
    assert router.strategist_chain[1].model == "gpt-6.1-sol"
    mock_router = build_router(settings, db_path=tmp_path / "mock.sqlite", mock_only=True)
    assert [p.name for p in mock_router.strategist_chain] == ["mock"]


def test_codex_fallback_can_be_switched_off(tmp_path):
    settings = Settings(codex_cli=CodexCliConfig(binary="codex", model="gpt-6.1-sol", enabled=False))
    router = build_router(settings, db_path=tmp_path / "usage.sqlite")
    assert [p.name for p in router.strategist_chain] == ["claude-cli", "mock"]


def test_codex_cli_passes_prompt_over_stdin_without_tools_or_session(tmp_path, monkeypatch):
    import packages.core.providers.codex_cli as cli

    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        if "--version" in args:
            return SimpleNamespace(returncode=0, stdout="codex-cli 0.145.0", stderr="")
        lines = [
            {"type": "thread.started", "thread_id": "thread"},
            {"type": "item.completed", "item": {"type": "agent_message", "text": '{"ok": true}'}},
            {"type": "turn.completed", "usage": {"input_tokens": 12, "output_tokens": 4}},
        ]
        return SimpleNamespace(returncode=0, stdout="\n".join(json.dumps(x) for x in lines), stderr="")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    provider = CodexCliProvider(binary="codex", model="gpt-6.1-sol", workdir=tmp_path)
    assert provider.healthy()
    result = provider.complete(task="review", system="Only JSON.", user="Untrusted source text.")
    args, kwargs = calls[1]
    assert args[args.index("-m") + 1] == "gpt-6.1-sol"
    assert "--sandbox" in args and args[args.index("--sandbox") + 1] == "read-only"
    assert "--ephemeral" in args and "--ignore-user-config" in args
    assert "--disable" in args and "shell_tool" in args
    assert "--json" in args
    assert kwargs["input"].endswith("Untrusted source text.\n</user_input>")
    assert "Only JSON." in kwargs["input"]
    assert result.content == '{"ok": true}'
    assert result.prompt_tokens == 12 and result.completion_tokens == 4
    assert result.raw == {"task": "review"}
    assert result.provider == "codex-cli"


def test_codex_cli_rejects_failed_turn_without_leaking_stderr(tmp_path, monkeypatch):
    import packages.core.providers.codex_cli as cli

    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda *args, **kw: SimpleNamespace(
            returncode=1,
            stdout=json.dumps({"type": "turn.failed", "error": {"message": "sk-secret-value"}}),
            stderr="sk-secret-value",
        ),
    )
    provider = CodexCliProvider(binary="codex", model="gpt-6.1-sol", workdir=tmp_path)
    with pytest.raises(ProviderError, match="codex cli exit 1") as caught:
        provider.complete(task="review", system="s", user="u")
    assert "sk-secret-value" not in str(caught.value)


def test_codex_cli_rejects_non_json_or_missing_final_answer(tmp_path, monkeypatch):
    import packages.core.providers.codex_cli as cli

    monkeypatch.setattr(cli.subprocess, "run", lambda *args, **kw: SimpleNamespace(returncode=0, stdout="junk", stderr=""))
    with pytest.raises(ProviderError, match="missing completed turn"):
        CodexCliProvider(binary="codex", model="gpt-6.1-sol", workdir=tmp_path).complete(
            task="review", system="s", user="u"
        )


def test_live_fallback_after_claude_error_is_codex_not_mock(tmp_path, monkeypatch):
    from packages.core.providers.base import ProviderResult

    router = build_router(Settings(codex_cli=CodexCliConfig(binary="codex", model="gpt-6.1-sol")), db_path=tmp_path / "usage.sqlite")
    claude, codex, _mock = router.strategist_chain
    monkeypatch.setattr(claude, "healthy", lambda: True)
    monkeypatch.setattr(claude, "complete", lambda **kwargs: (_ for _ in ()).throw(ProviderError("down", provider="claude-cli")))
    monkeypatch.setattr(codex, "healthy", lambda: True)
    monkeypatch.setattr(codex, "complete", lambda **kwargs: ProviderResult(content="real", provider="codex-cli", model="gpt-6.1-sol"))
    result = router.call(agent="CreativeDirectorAgent", tier="strategist", task="review", system="s", user="u", allow_mock=False)
    assert result.provider == "codex-cli"
    assert any("claude-cli" in note for note in result.raw["fallback_notes"])
