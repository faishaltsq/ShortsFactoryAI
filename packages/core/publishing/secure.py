"""Atomic local secret storage: protected DACL on Windows, 0700/0600 on POSIX."""
from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .errors import PublishingError

REPOSITORY = Path(__file__).resolve().parents[3]


def default_config_root() -> Path:
    base = os.environ.get("LOCALAPPDATA") if os.name == "nt" else os.environ.get("XDG_CONFIG_HOME")
    return (Path(base) if base else Path.home() / ".config") / "ShortsFactoryAI" / "youtube"


def _windows_acl(path: Path, *, apply: bool) -> None:
    import ctypes
    from ctypes import wintypes

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    pointer = ctypes.c_void_p
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, pointer, wintypes.DWORD,
                                          ctypes.POINTER(wintypes.DWORD)]
    advapi.ConvertSidToStringSidW.argtypes = [pointer, ctypes.POINTER(wintypes.LPWSTR)]
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                                                           ctypes.POINTER(pointer), pointer]
    advapi.SetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, pointer]
    advapi.GetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, pointer, wintypes.DWORD,
                                       ctypes.POINTER(wintypes.DWORD)]
    advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [pointer, wintypes.DWORD,
                                                                           wintypes.DWORD,
                                                                           ctypes.POINTER(wintypes.LPWSTR), pointer]
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.LocalFree.argtypes = [pointer]
    handle = wintypes.HANDLE()
    sid_text, descriptor, actual_text = wintypes.LPWSTR(), pointer(), wintypes.LPWSTR()
    try:
        if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(handle)):
            raise OSError
        length = wintypes.DWORD()
        advapi.GetTokenInformation(handle, 1, None, 0, ctypes.byref(length))
        buffer = ctypes.create_string_buffer(length.value)
        if not advapi.GetTokenInformation(handle, 1, buffer, length, ctypes.byref(length)):
            raise OSError
        sid = ctypes.cast(buffer, ctypes.POINTER(pointer))[0]
        if not advapi.ConvertSidToStringSidW(sid, ctypes.byref(sid_text)):
            raise OSError
        # Directories propagate only these two ACEs to newly created children.
        flags = "OICI" if path.is_dir() else ""
        sddl = f"D:P(A;{flags};FA;;;{sid_text.value})(A;{flags};FA;;;SY)"
        if apply:
            if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1,
                                                                               ctypes.byref(descriptor), None):
                raise OSError
            if not advapi.SetFileSecurityW(str(path), 0x80000004, descriptor):
                raise OSError
        needed = wintypes.DWORD()
        advapi.GetFileSecurityW(str(path), 4, None, 0, ctypes.byref(needed))
        existing = ctypes.create_string_buffer(needed.value)
        if not advapi.GetFileSecurityW(str(path), 4, existing, needed, ctypes.byref(needed)):
            raise OSError
        if not advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW(existing, 1, 4,
                                                                           ctypes.byref(actual_text), None):
            raise OSError
        actual = actual_text.value or ""
        entries = re.findall(r"\(([^)]+)\)", actual)
        expected = {f"A;{flags};FA;;;{sid_text.value}", f"A;{flags};FA;;;SY"}
        if not actual.startswith("D:P") or set(entries) != expected or len(entries) != 2:
            raise OSError
    except (OSError, ValueError, TypeError):
        raise PublishingError("protected_permissions_failed") from None
    finally:
        if handle:
            kernel.CloseHandle(handle)
        for memory in (sid_text, descriptor, actual_text):
            if memory:
                kernel.LocalFree(ctypes.cast(memory, pointer))


class ProtectedStore:
    def __init__(self, root: Path | None = None, *, repository: Path = REPOSITORY) -> None:
        raw = Path(root if root is not None else default_config_root()).absolute()
        if any(p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()) for p in (raw, *raw.parents)):
            raise PublishingError("protected_path_unsafe")
        self.root = raw.resolve()
        if self.root.is_relative_to(repository.resolve()):
            raise ValueError("protected_config_must_be_outside_repository")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._protect(self.root)

    def _path(self, name: str) -> Path:
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,80}", name):
            raise ValueError("invalid_secret_name")
        path = self.root / f"{name}.json"
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise PublishingError("protected_path_unsafe")
        return path

    def _protect(self, path: Path) -> None:
        if os.name == "nt":
            _windows_acl(path, apply=True)
        else:
            path.chmod(0o700 if path.is_dir() else 0o600)
            self.verify_permissions(path)

    def verify_permissions(self, path: Path) -> None:
        if os.name == "nt":
            _windows_acl(path, apply=False)
        elif stat.S_IMODE(path.stat().st_mode) != (0o700 if path.is_dir() else 0o600):
            raise PublishingError("protected_permissions_failed")

    def read(self, name: str) -> dict[str, Any] | None:
        path = self._path(name)
        if not path.exists():
            return None
        self._protect(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError
            return data
        except (OSError, ValueError):
            raise PublishingError("protected_data_invalid") from None

    def write(self, name: str, data: dict[str, Any]) -> None:
        path = self._path(name)
        temporary: Path | None = None
        try:
            fd, raw = tempfile.mkstemp(prefix=".atomic-", dir=self.root)
            temporary = Path(raw)
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                self._protect(temporary)
                json.dump(data, output, allow_nan=False, separators=(",", ":"))
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
            self.verify_permissions(path)
        except (OSError, ValueError):
            raise PublishingError("protected_write_failed") from None
        finally:
            if temporary and temporary.exists():
                temporary.unlink()

    def delete(self, name: str) -> None:
        self._path(name).unlink(missing_ok=True)

    @contextmanager
    def locked(self, name: str) -> Iterator[None]:
        """OS-held lock is released on process exit, including abrupt termination."""
        path = self._path(f"lock-{name}")
        stream = path.open("a+b")
        try:
            self._protect(path)
            stream.seek(0, 2)
            if not stream.tell():
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise PublishingError("protected_store_busy") from None
            try:
                yield
            finally:
                stream.seek(0)
                if os.name == "nt":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()
