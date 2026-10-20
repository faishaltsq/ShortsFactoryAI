#!/usr/bin/env python3
"""Verify model access before spending money.

Reports, never fabricates: each adapter is probed live and the real
capability (or the blocker) is printed. Exit code 0 always — this is a
diagnostic, not a gate.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from packages.core.config import get_settings  # noqa: E402
from packages.core.providers import MockProvider, build_router  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe LLM providers")
    parser.add_argument("--live", action="store_true", help="spend one real completion per provider")
    args = parser.parse_args()

    settings = get_settings()
    router = build_router(settings)
    print("== router health ==")
    print(json.dumps(router.health(), indent=2))
    print(f"deepseek configured: {settings.deepseek.configured}")
    print(f"deepseek base_url:   {settings.deepseek.base_url or '(unset)'}")
    print(f"deepseek model:      {settings.deepseek.model or '(unset)'}")
    print(f"claude cli bin:      {settings.claude_cli.binary}")
    print(f"claude cli model:    {settings.claude_cli.model}")

    if not args.live:
        print("dry run (no completions). use --live to send one prompt per provider.")
        return 0

    probe_user = 'Balas hanya dengan JSON: {"ok": true}'
    for tier, chain in (("worker", router.worker_chain), ("strategist", router.strategist_chain)):
        for provider in chain:
            if provider.name == "mock":
                continue
            label = f"{tier}:{provider.name}"
            try:
                healthy = provider.healthy()
                result = provider.complete(task="probe", system="You are a health probe.", user=probe_user)
                print(
                    f"{label}: OK model={result.model} "
                    f"tokens={result.total_tokens} ms={result.elapsed_ms} healthy={healthy}"
                )
            except Exception as exc:  # noqa: BLE001
                print(f"{label}: FAILED {type(exc).__name__}: {str(exc)[:300]}")
    print("mock fallback available:", MockProvider().name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
