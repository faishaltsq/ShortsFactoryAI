"""Renew an owned job lease while a synchronous stage is blocked."""
from __future__ import annotations

import math
from threading import Event, Thread

from .jobstore import JobStore, _validate_ttl


class LeaseLostError(RuntimeError):
    """The caller must stop work because its lease is no longer owned."""


class LeaseKeeper:
    def __init__(self, store: JobStore, job_id: str, token: str, *, ttl_s: float = 1800,
                 interval_s: float | None = None) -> None:
        _validate_ttl(ttl_s)
        interval = ttl_s / 3 if interval_s is None else interval_s
        if not math.isfinite(interval) or not 0 < interval < ttl_s:
            raise ValueError("heartbeat interval must be positive and shorter than lease TTL")
        self.store, self.job_id, self.token = store, job_id, token
        self.ttl_s, self.interval_s = ttl_s, interval
        self._stop = Event()
        self._lost = Event()
        self._thread: Thread | None = None

    def heartbeat(self) -> bool:
        if self._lost.is_set():
            return False
        try:
            renewed = self.store.renew_lease(self.job_id, self.token, ttl_s=self.ttl_s)
        except Exception:
            renewed = False
        if not renewed:
            self._lost.set()
        return renewed

    def check(self) -> None:
        if not self.heartbeat():
            raise LeaseLostError("job lease ownership lost")

    def _keep_alive(self) -> None:
        while not self._stop.wait(self.interval_s):
            if not self.heartbeat():
                break

    def __enter__(self) -> LeaseKeeper:
        self.check()
        self._thread = Thread(target=self._keep_alive, name="job-lease-heartbeat", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
        if exc_type is None:
            self.heartbeat()
        self.store.release_lease(self.job_id, self.token)
        if exc_type is None and self._lost.is_set():
            raise LeaseLostError("job lease ownership lost")
