"""Operator CLI argument parsing must not begin an action on ambiguous input."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_approval_cli_rejects_multiple_actions():
    result = subprocess.run([
        sys.executable, str(ROOT / "scripts" / "approve.py"),
        "--approve", "a" * 16, "--reject", "b" * 16,
    ], capture_output=True, text=True, timeout=20)
    assert result.returncode == 2
    assert "not allowed with argument" in result.stderr


def test_approval_cli_help_has_no_runtime_side_effect(tmp_path):
    result = subprocess.run([
        sys.executable, str(ROOT / "scripts" / "approve.py"), "--help",
    ], cwd=tmp_path, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0
    assert "--approve" in result.stdout
    assert list(tmp_path.iterdir()) == []
