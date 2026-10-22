"""Bounded subprocesses and confined local artifact paths."""
from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import time
from pathlib import Path
from typing import Callable


def checked_path(root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ":" in relative or ".." in path.parts:
        raise ValueError("media path must stay inside the job directory")
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("media path escaped the job directory")
    return resolved


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def json_hash(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def atomic_json(path: Path, data: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def _stop_tree(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=20, check=False)
    else:
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


def run_checked(args: list[str], *, log_path: Path, cwd: Path | None = None,
                timeout: float = 180, cancelled: Callable[[], bool] | None = None,
                on_output: Callable[[str], None] | None = None) -> None:
    with log_path.open("ab") as output:
        offset = output.tell()
        proc = subprocess.Popen(args, cwd=cwd, stdout=output, stderr=subprocess.STDOUT, shell=False)
        deadline = time.monotonic() + timeout

        def observe() -> None:
            nonlocal offset
            if on_output is not None:
                with log_path.open("rb") as source:
                    source.seek(offset)
                    chunk = source.read(1_048_576)
                    offset = source.tell()
                if chunk:
                    on_output(chunk.decode("utf-8", errors="replace"))

        try:
            while proc.poll() is None:
                observe()
                if cancelled is not None and cancelled():
                    raise RuntimeError("job cancelled by operator")
                if time.monotonic() > deadline:
                    raise TimeoutError(f"media command exceeded {timeout}s; see {log_path.name}")
                time.sleep(0.25)
            observe()
        except BaseException:
            if proc.poll() is None:
                _stop_tree(proc)
            raise
        if proc.returncode:
            raise RuntimeError(f"media command exited {proc.returncode}; see {log_path.name}")


def _port_is_free(port: int) -> bool:
    """True only when nothing already answers on the port and it can be bound exclusively.

    Remotion's own probe only tries to bind, which on Windows succeeds even while another
    process is listening on the same port through a wildcard bind. Chrome then reaches that
    foreign server instead of the bundle and composition lookup fails. A connect check plus
    an exclusive bind is the only combination that rejects such a port.
    """
    for host, family in (("127.0.0.1", socket.AF_INET), ("::1", socket.AF_INET6)):
        probe = socket.socket(family, socket.SOCK_STREAM)
        probe.settimeout(0.25)
        try:
            if probe.connect_ex((host, port)) == 0:
                return False
        except OSError:
            pass
        finally:
            probe.close()
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        holder.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        holder.bind(("127.0.0.1", port))
        holder.listen(1)
        return True
    except OSError:
        return False
    finally:
        holder.close()


def free_remotion_port(*, attempts: int = 40) -> int:
    """Pick a port the Remotion preview server can own exclusively.

    Passing an explicit port makes the renderer fail loudly instead of silently serving on a
    port that a local dev server already occupies.
    """
    for _ in range(attempts):
        candidate = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            candidate.bind(("127.0.0.1", 0))
            port = candidate.getsockname()[1]
        finally:
            candidate.close()
        if port >= 1024 and _port_is_free(port):
            return port
    raise RuntimeError("no free local port available for the Remotion preview server")


def probe_media(path: Path) -> dict:
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("media artifact is missing or empty")
    result = subprocess.run(["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe", "-show_format", "-show_streams", "-of", "json", str(path)],
                            capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
    if result.returncode:
        raise ValueError("ffprobe could not decode media artifact")
    return json.loads(result.stdout)
