"""Claude Code CLI adapter.

Uses the documented non-interactive invocation:
    <bin> -p <prompt> --output-format json --model <model>

No API key handling: the CLI carries its own credentials. Output JSON is parsed
for assistant text plus token usage.
"""

from __future__ import annotations

import json
import subprocess
import time

from .base import ProviderError, ProviderResult, Tier


class ClaudeCliProvider:
    def __init__(
        self,
        *,
        name: str = "claude-cli",
        binary: str,
        model: str,
        tier: Tier = "strategist",
        timeout_s: int = 300,
        max_retries: int = 2,
    ) -> None:
        self.name = name
        self.binary = binary
        self.model = model
        self.tier = tier
        self.timeout_s = timeout_s
        self.max_retries = max_retries

    def healthy(self) -> bool:
        try:
            proc = subprocess.run(
                [self.binary, "--version"],
                capture_output=True,
                text=True,
                timeout=20,
            )
            return proc.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def _run(self, prompt: str) -> tuple[str, int, int]:
        proc = subprocess.run(
            [self.binary, "-p", "--output-format", "json", "--model", self.model,
             "--tools", "", "--strict-mcp-config", "--no-session-persistence"],
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=self.timeout_s,
        )
        if proc.returncode != 0:
            raise ProviderError(
                f"claude cli exit {proc.returncode}",
                provider=self.name,
                retryable=proc.returncode != 1,
            )
        out = (proc.stdout or "").strip()
        if not out:
            raise ProviderError("claude cli returned empty output", provider=self.name, retryable=True)
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return out, 0, 0
        if not isinstance(data, dict) or data.get("is_error"):
            raise ProviderError("claude cli returned an error result", provider=self.name)
        text = data.get("result") or data.get("content") or ""
        usage = data.get("usage") or {}
        return (
            text,
            int(usage.get("input_tokens", 0) or 0),
            int(usage.get("output_tokens", 0) or 0),
        )

    def complete(self, *, task: str, system: str, user: str) -> ProviderResult:
        prompt = f"<system_role>\n{system}\n</system_role>\n\n<task name={task!r}>\n{user}\n</task>"
        started = time.perf_counter()
        last_error = ""
        for attempt in range(1, self.max_retries + 1):
            try:
                text, p_tok, c_tok = self._run(prompt)
            except ProviderError as exc:
                last_error = str(exc)
                if attempt < self.max_retries and exc.retryable:
                    time.sleep(5 * attempt)
                    continue
                raise
            if not text.strip():
                last_error = "empty assistant text"
                if attempt < self.max_retries:
                    time.sleep(5 * attempt)
                    continue
                raise ProviderError(last_error, provider=self.name, retryable=True)
            return ProviderResult(
                content=text,
                provider=self.name,
                model=self.model,
                prompt_tokens=p_tok,
                completion_tokens=c_tok,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                raw={"task": task},
            )
        raise ProviderError(last_error or "exhausted retries", provider=self.name, retryable=True)
