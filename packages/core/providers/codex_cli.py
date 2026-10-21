"""Non-interactive Codex CLI adapter for strategist fallback."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .base import ProviderError, ProviderResult, Tier


class CodexCliProvider:
    def __init__(
        self,
        *,
        binary: str,
        model: str,
        tier: Tier = "strategist",
        timeout_s: int = 300,
        workdir: Path | None = None,
    ) -> None:
        self.name = "codex-cli"
        self.binary = binary
        self.model = model
        self.tier = tier
        self.timeout_s = timeout_s
        self.workdir = workdir

    def _executable(self) -> str:
        # Windows npm installs .cmd and a POSIX shim; CreateProcess needs .cmd.
        if os.name == "nt" and not Path(self.binary).suffix:
            return shutil.which(f"{self.binary}.cmd") or f"{self.binary}.cmd"
        return shutil.which(self.binary) or self.binary

    def healthy(self) -> bool:
        try:
            proc = subprocess.run(
                [self._executable(), "--version"], capture_output=True, text=True, timeout=20
            )
            return proc.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def complete(self, *, task: str, system: str, user: str) -> ProviderResult:
        if not re.fullmatch(r"[A-Za-z0-9._/-]+", self.model):
            raise ProviderError("invalid codex model id", provider=self.name)
        prompt = f"<system_role>\n{system}\n</system_role>\n<task name={task!r}>\n<user_input>\n{user}\n</user_input>"
        started = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="shorts-codex-", dir=self.workdir or os.environ.get("TMPDIR")) as cwd:
            args = [
                self._executable(), "exec", "--json", "-m", self.model,
                "--sandbox", "read-only", "--ephemeral", "--ignore-user-config",
                "--skip-git-repo-check", "-C", cwd,
                "--disable", "shell_tool", "--disable", "code_mode_host",
                "--disable", "browser_use", "--disable", "computer_use",
                "--disable", "apps", "--disable", "plugins",
                "--disable", "hooks", "--disable", "multi_agent",
                "--disable", "image_generation", "--disable", "goals", "-",
            ]
            try:
                proc = subprocess.run(
                    args, input=prompt, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=self.timeout_s,
                )
            except subprocess.TimeoutExpired:
                raise ProviderError("codex cli timed out", provider=self.name, retryable=True) from None
            except OSError:
                raise ProviderError("codex cli unavailable", provider=self.name) from None

        # CLI diagnostics may reflect credentials. Never surface stdout/stderr on failure.
        if proc.returncode != 0:
            raise ProviderError(f"codex cli exit {proc.returncode}", provider=self.name)
        answer = ""
        usage: dict[str, int] | None = None
        for line in proc.stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("type") in ("error", "turn.failed"):
                raise ProviderError("codex cli turn failed", provider=self.name)
            if event.get("type") == "item.completed":
                item = event.get("item")
                if isinstance(item, dict) and item.get("type") == "agent_message":
                    answer = item.get("text", "")
            if event.get("type") == "turn.completed":
                usage = event.get("usage")
        if not isinstance(answer, str) or not answer.strip() or not isinstance(usage, dict):
            raise ProviderError("codex cli missing completed turn", provider=self.name)
        try:
            prompt_tokens = int(usage["input_tokens"])
            completion_tokens = int(usage["output_tokens"])
            if prompt_tokens < 0 or completion_tokens < 0:
                raise ValueError("negative token usage")
        except (KeyError, TypeError, ValueError):
            raise ProviderError("codex cli missing token usage", provider=self.name) from None
        return ProviderResult(
            content=answer,
            provider=self.name,
            model=self.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            raw={"task": task},
        )
