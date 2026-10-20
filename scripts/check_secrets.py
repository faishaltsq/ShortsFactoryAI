#!/usr/bin/env python3
"""Scan version-control candidates for credential formats without printing values."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{24,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{30,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r'''(?:api_key|api_secret|access_token|refresh_token|password)\s*[:=]\s*["'][A-Za-z0-9_./+-]{24,}["']''', re.IGNORECASE),
]


def main() -> int:
    result = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                            cwd=ROOT, capture_output=True, check=True)
    findings, count = [], 0
    for raw_path in result.stdout.decode("utf-8").split("\0"):
        if not raw_path:
            continue
        path = ROOT / raw_path
        if path.name.startswith(".env") and path.name != ".env.example":
            findings.append((raw_path, 0, "credential file is a git candidate"))
            continue
        if path.suffix.lower() not in {".py", ".tsx", ".ts", ".json", ".toml", ".md", ".yml", ".yaml", ".example"}:
            continue
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        count += 1
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if any(pattern.search(line) for pattern in PATTERNS):
                findings.append((raw_path, number, "possible embedded credential"))
    for path, number, reason in findings:
        print(f"{path}:{number}: {reason}")
    print(f"Secret scan: {len(findings)} findings across {count} text files")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
