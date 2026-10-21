"""Offline native-outbound receiver contracts, using isolated SQLite files."""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
from datetime import datetime, timezone

import pytest

from packages.core.observability.store import StudioEventStore

SECRET = "studio-signing-secret-0123456789"
BASE = 1_792_500_000.0  # 2026-10-20T12:40:00Z
SENTINEL = "private-sentinel-not-for-ui"


def iso(offset: float = 0.0) -> str:
    return datetime.fromtimestamp(BASE + offset, timezone.utc).isoformat().replace("+00:00", "Z")


def body(*, event: str = "on_session_end", delivery: str = "3f2c9a77b1d24e5a",
         timestamp: str | None = None, session: str = "sess_abc123") -> dict:
    return {
        "hook_event_name": event, "profile": "default",
        "tool_name": "terminal", "tool_input": {"command": f"cat {SENTINEL}"},
        "session_id": session, "cwd": f"C:/Users/cubeb/{SENTINEL}",
        "extra": {"model": SENTINEL, "authorization": SENTINEL},
        "delivery_id": delivery, "timestamp": iso() if timestamp is None else timestamp,
    }


def signed(data: dict, *, secret: str = SECRET) -> tuple[bytes, dict[str, str]]:
    raw = json.dumps(data).encode("utf-8")
    return raw, {"Content-Type": "application/json", "X-Hermes-Event": data["hook_event_name"],
                 "X-Hermes-Delivery": data["delivery_id"],
                 "X-Hermes-Signature-256": "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()}


def observer_for(tmp_path, monkeypatch, *, secret: str | None = SECRET, now=None, **kwargs):
    from packages.core.observability.hermes import HermesObserver

    monkeypatch.delenv("SHORTS_HERMES_WEBHOOK_SECRET", raising=False)
    return HermesObserver(StudioEventStore(tmp_path / "factory.db"), secret=secret,
                          now=now or (lambda: BASE), **kwargs)



@pytest.mark.parametrize("secret", [None, "", " \t\n"])
def test_observer_is_disabled_without_an_explicit_nonempty_secret(tmp_path, monkeypatch, secret):
    from packages.core.observability.hermes import HermesObserver, ObserverDisabled

    monkeypatch.setenv("SHORTS_HERMES_WEBHOOK_SECRET", "environment-must-not-enable-core")
    events = StudioEventStore(tmp_path / "factory.db")
    observer = HermesObserver(events, secret=secret)

    assert observer.configured is False
    with pytest.raises(ObserverDisabled):
        observer.accept(b"{}", {"Authorization": "Bearer environment-must-not-enable-core"})
    with events.connect() as conn:
        assert [row[0] for row in conn.execute("SELECT version FROM studio_migrations")] == [1]
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='hermes_deliveries'").fetchone() is None


def test_valid_delivery_records_metadata_only(tmp_path, monkeypatch):
    observer = observer_for(tmp_path, monkeypatch)
    assert observer.configured is True
    metadata = observer.accept(*signed(body()))
    assert metadata["event"] == "on_session_end" and metadata["status"] == "recorded"
    assert len(metadata["delivery_ref"]) == 64
    assert SENTINEL not in json.dumps(metadata)
    with observer.events.connect() as conn:
        row = conn.execute("SELECT delivery_ref, event_name, received_at, session_ref FROM hermes_deliveries").fetchone()
        assert row[0] == metadata["delivery_ref"] and row[1] == "on_session_end"
        assert isinstance(row[2], float) and len(row[3]) == 16 and SENTINEL not in row[3]


@pytest.mark.parametrize("headers", [
    {},
    {"X-Hermes-Event": "on_session_end", "X-Hermes-Delivery": "3f2c9a77b1d24e5a"},
    {"X-Hermes-Event": "on_session_end", "X-Hermes-Delivery": "3f2c9a77b1d24e5a",
     "Authorization": f"Bearer {SENTINEL}"},
])
def test_unsigned_or_bearer_only_delivery_is_rejected(tmp_path, monkeypatch, headers):
    from packages.core.observability.hermes import InvalidDelivery

    observer = observer_for(tmp_path, monkeypatch)
    with pytest.raises(InvalidDelivery) as exc:
        observer.accept(json.dumps(body()).encode(), headers)
    assert exc.value.status_code == 401
    with observer.events.connect() as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='hermes_deliveries'").fetchone() is None


def test_tampered_body_breaks_the_signature(tmp_path, monkeypatch):
    from packages.core.observability.hermes import InvalidDelivery

    observer = observer_for(tmp_path, monkeypatch)
    raw, headers = signed(body())
    with pytest.raises(InvalidDelivery) as exc:
        observer.accept(raw.replace(b"on_session_end", b"pre_tool_call"), headers)
    assert exc.value.status_code == 401


def test_headers_must_match_the_signed_body(tmp_path, monkeypatch):
    from packages.core.observability.hermes import InvalidDelivery

    observer = observer_for(tmp_path, monkeypatch)
    raw, headers = signed(body())
    for swapped in ({"X-Hermes-Event": "pre_tool_call"}, {"X-Hermes-Delivery": "ffffffffffffffff"}):
        with pytest.raises(InvalidDelivery) as exc:
            observer.accept(raw, dict(headers, **swapped))
        assert exc.value.status_code == 400


@pytest.mark.parametrize("data", [
    body(timestamp=iso(-600)),
    body(timestamp=iso(600)),
    body(timestamp="2026-10-20T12:40:00"),
    body(timestamp="not-a-timestamp"),
    body(event="pre_llm_call"),
    body(delivery="../escape"),
    body(delivery="short"),
])
def test_stale_future_naive_foreign_and_malformed_deliveries_are_rejected(tmp_path, monkeypatch, data):
    from packages.core.observability.hermes import InvalidDelivery

    observer = observer_for(tmp_path, monkeypatch)
    with pytest.raises(InvalidDelivery) as exc:
        observer.accept(*signed(data))
    assert exc.value.status_code == 400
    with observer.events.connect() as conn:
        exists = conn.execute("SELECT name FROM sqlite_master WHERE name='hermes_deliveries'").fetchone()
        assert exists is None or conn.execute("SELECT COUNT(*) FROM hermes_deliveries").fetchone()[0] == 0


def test_malformed_json_and_oversized_body_are_refused(tmp_path, monkeypatch):
    from packages.core.observability.hermes import InvalidDelivery

    observer = observer_for(tmp_path, monkeypatch)
    raw, headers = signed(body())
    with pytest.raises(InvalidDelivery) as exc:
        observer.accept(b"{not json", headers)
    assert exc.value.status_code == 401
    with pytest.raises(InvalidDelivery) as exc:
        observer.accept(b"x" * 65_537, headers)
    assert exc.value.status_code == 413


def test_duplicate_delivery_is_skipped_and_survives_reopen(tmp_path, monkeypatch):
    from packages.core.observability.hermes import HermesObserver

    observer = observer_for(tmp_path, monkeypatch)
    raw, headers = signed(body(delivery="aaaa1111bbbb2222"))
    assert observer.accept(raw, headers)["status"] == "recorded"
    assert observer.accept(raw, headers)["status"] == "duplicate"
    reopened = HermesObserver(observer.events, secret=SECRET, now=lambda: BASE)
    assert reopened.accept(raw, headers)["status"] == "duplicate"
    with observer.events.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM hermes_deliveries").fetchone()[0] == 1


def test_concurrent_duplicate_deliveries_create_exactly_one_row(tmp_path, monkeypatch):
    observer = observer_for(tmp_path, monkeypatch)
    raw, headers = signed(body(delivery="cccc3333dddd4444"))
    results: list[dict] = []
    barrier = threading.Barrier(4)

    def deliver() -> None:
        barrier.wait()
        try:
            results.append(observer.accept(raw, headers))
        except Exception:  # pragma: no cover - counted below
            results.append({"status": "error"})

    workers = [threading.Thread(target=deliver) for _ in range(4)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    assert [row["status"] for row in results].count("recorded") == 1
    with observer.events.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM hermes_deliveries").fetchone()[0] == 1


def test_capacity_fails_closed_until_the_window_expires(tmp_path, monkeypatch):
    from packages.core.observability.hermes import InvalidDelivery

    clock = {"now": BASE}
    observer = observer_for(tmp_path, monkeypatch, now=lambda: clock["now"], capacity=2)
    assert (observer.capacity, observer.window_s, observer.max_body) == (2, 300.0, 65_536)
    for index in range(2):
        assert observer.accept(*signed(body(delivery=f"e{index:015x}")))["status"] == "recorded"
    with pytest.raises(InvalidDelivery) as exc:
        observer.accept(*signed(body(delivery="e2000000000000000")))
    assert exc.value.status_code == 503
    clock["now"] += 3600
    assert observer.accept(*signed(body(delivery="e3000000000000000", timestamp=iso(3600))))["status"] == "recorded"
    with observer.events.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM hermes_deliveries").fetchone()[0] == 3


def test_health_projection_sees_the_last_received_delivery(tmp_path, monkeypatch):
    from packages.core.orchestration import JobStore
    from packages.core.observability.projection import StudioService

    service = StudioService(JobStore(tmp_path / "factory.db", tmp_path / "jobs"))
    assert service.snapshot()["health"]["hermes"] == "not_connected"
    observer_for(tmp_path, monkeypatch).accept(*signed(body()))
    health = service.snapshot()["health"]
    assert health["hermes"] in {"connected", "stale"} and health["hermes_last_seen"]
