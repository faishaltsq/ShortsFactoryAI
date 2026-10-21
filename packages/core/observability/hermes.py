"""Opt-in observation of native Hermes outbound metadata, never production work.

Contract verified against the official Hermes hooks documentation: a POSTed JSON
body carries hook_event_name / delivery_id / timestamp plus opaque tool context,
and is authenticated with X-Hermes-Signature-256 (sha256=<hex> HMAC-SHA256 of the
raw body). Tool payloads are deliberately dropped: only allow-listed event names,
pseudonymous references and receipt times are persisted.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from collections.abc import Callable, Mapping
from datetime import datetime

from .store import StudioEventStore

ALLOWED_EVENTS = frozenset({
    "on_session_start", "pre_tool_call", "post_tool_call", "on_session_end",
    "on_session_finalize", "on_session_reset", "subagent_start", "subagent_stop",
    "pre_approval_request", "post_approval_response",
})
DELIVERY_PATTERN = re.compile(r"^[0-9a-f]{8,64}$")


class ObserverDisabled(RuntimeError):
    """No explicit server-side signing secret was supplied."""


class InvalidDelivery(ValueError):
    """A delivery failed verification; status_code is the HTTP answer to return."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class HermesObserver:
    def __init__(self, events: StudioEventStore, secret: str | None = None,
                 *, now: Callable[[], float] | None = None,
                 capacity: int = 2048, window_s: float = 300.0, max_body: int = 65_536) -> None:
        self.events = events
        self._secret = secret.encode("utf-8") if secret and secret.strip() else None
        self._now = now or time.time
        self.capacity, self.window_s, self.max_body = capacity, window_s, max_body

    @property
    def configured(self) -> bool:
        return self._secret is not None

    @staticmethod
    def _header(headers: Mapping[str, str], name: str) -> str | None:
        target = name.lower()
        for key, value in headers.items():
            if key.lower() == target:
                return value
        return None

    def _fingerprint(self, *parts: str) -> str:
        assert self._secret is not None
        return hmac.new(self._secret, "|".join(parts).encode("utf-8"), hashlib.sha256).hexdigest()

    def _verify(self, raw: bytes, headers: Mapping[str, str]) -> dict:
        if not self.configured:
            raise ObserverDisabled("Hermes observer is disabled")
        if len(raw) > self.max_body:
            raise InvalidDelivery("delivery body is too large", 413)
        presented = self._header(headers, "X-Hermes-Signature-256")
        if not presented:
            raise InvalidDelivery("signature header is required", 401)
        expected = "sha256=" + hmac.new(self._secret, raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, presented):
            raise InvalidDelivery("signature does not match the raw body", 401)
        header_event = self._header(headers, "X-Hermes-Event")
        header_delivery = self._header(headers, "X-Hermes-Delivery")
        if not header_event or not header_delivery:
            raise InvalidDelivery("event and delivery headers are required", 400)
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InvalidDelivery("body is not valid UTF-8 JSON", 400) from exc
        if not isinstance(body, dict):
            raise InvalidDelivery("body must be a JSON object", 400)

        event = body.get("hook_event_name")
        if not isinstance(event, str) or event not in ALLOWED_EVENTS or header_event != event:
            raise InvalidDelivery("event name is not observable or does not match the header", 400)
        delivery = body.get("delivery_id")
        if not isinstance(delivery, str) or not DELIVERY_PATTERN.fullmatch(delivery) or header_delivery != delivery:
            raise InvalidDelivery("delivery identifier is malformed or does not match the header", 400)

        stamp = body.get("timestamp")
        if not isinstance(stamp, str):
            raise InvalidDelivery("timestamp is missing", 400)
        try:
            moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise InvalidDelivery("timestamp is not ISO 8601", 400) from exc
        if moment.tzinfo is None:
            raise InvalidDelivery("timestamp must be timezone aware", 400)
        if abs(self._now() - moment.timestamp()) > self.window_s:
            raise InvalidDelivery("timestamp is outside the freshness window", 400)

        session = body.get("session_id") if isinstance(body.get("session_id"), str) else ""
        return {"event": event, "delivery_ref": hashlib.sha256(delivery.encode()).hexdigest(),
                "session_ref": self._fingerprint("session", session)[:16]}

    def _ensure_table(self) -> None:
        with self.events.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS hermes_deliveries (
                    delivery_ref TEXT PRIMARY KEY,
                    event_name TEXT NOT NULL,
                    session_ref TEXT NOT NULL,
                    received_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_hermes_received ON hermes_deliveries(received_at DESC);
                INSERT OR IGNORE INTO studio_migrations(version) VALUES (2);
            """)

    def _record(self, metadata: dict) -> dict:
        now = self._now()
        self._ensure_table()
        with self.events.connect() as conn:
            recent = conn.execute("SELECT COUNT(*) FROM hermes_deliveries WHERE received_at>?",
                                  (now - self.window_s,)).fetchone()[0]
            if recent >= self.capacity:
                raise InvalidDelivery("observer capacity is exhausted", 503)
            cursor = conn.execute(
                "INSERT INTO hermes_deliveries (delivery_ref, event_name, session_ref, received_at) "
                "VALUES (?,?,?,?) ON CONFLICT(delivery_ref) DO NOTHING",
                (metadata["delivery_ref"], metadata["event"], metadata["session_ref"], now),
            )
            recorded = cursor.rowcount == 1
        if not recorded:
            return {**metadata, "status": "duplicate"}
        return {**metadata, "status": "recorded"}

    def accept(self, raw: bytes, headers: Mapping[str, str]) -> dict:
        return self._record(self._verify(raw, headers))
