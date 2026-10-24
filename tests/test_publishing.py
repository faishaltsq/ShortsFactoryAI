"""Offline publishing tests. Synthetic bytes never stand in for production media QC."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from packages.core.publishing.errors import PublishingError


def test_secret_store_is_atomic_private_and_outside_repository(tmp_path):
    from packages.core.publishing.secure import ProtectedStore

    root = tmp_path / "operator-config"
    store = ProtectedStore(root, repository=Path(__file__).resolve().parents[1])
    store.write("tokens", {"access_token": "offline-access", "refresh_token": "offline-refresh"})
    assert store.read("tokens")["refresh_token"] == "offline-refresh"
    assert [p.name for p in root.iterdir()] == ["tokens.json"]
    store.verify_permissions(root / "tokens.json")
    assert "offline-access" not in repr(store)
    with pytest.raises(ValueError, match="outside_repository"):
        ProtectedStore(Path(__file__).resolve().parents[1] / "data" / "credentials")
    with pytest.raises(ValueError, match="invalid_secret_name"):
        store.write("../escape", {})


def test_secret_store_rejects_symlink_and_malformed_json(tmp_path):
    from packages.core.publishing.secure import ProtectedStore
    from packages.core.publishing.errors import PublishingError

    store = ProtectedStore(tmp_path / "secrets")
    store.write("tokens", {})
    (store.root / "tokens.json").write_text('{"access_token":"offline-raw",', encoding="utf-8")
    with pytest.raises(PublishingError, match="protected_data_invalid") as error:
        store.read("tokens")
    assert "offline-raw" not in str(error.value)
    assert error.value.__cause__ is None
    assert store.read("absent") is None
    store.delete("tokens")
    assert store.read("tokens") is None


def _oauth(tmp_path, handler, **kwargs):
    import httpx
    from packages.core.publishing.oauth import InstalledClient, OAuthFlow, TokenManager
    from packages.core.publishing.secure import ProtectedStore

    secret = ProtectedStore(tmp_path / "protected")
    http = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    client = InstalledClient.from_data({"installed": {"client_id": "offline-client", "client_secret": "offline-secret"}})
    flow = OAuthFlow(client, secret, http, clock=lambda: 1000.0, sleep=lambda _: None, **kwargs)
    tokens = TokenManager(client, secret, http, clock=lambda: 1000.0, sleep=lambda _: None, **kwargs)
    return flow, tokens, secret


def test_installed_oauth_uses_state_s256_loopback_and_protected_tokens(tmp_path):
    import base64
    import hashlib
    import httpx
    from urllib.parse import parse_qs, urlsplit

    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"access_token": "offline-access", "refresh_token": "offline-refresh",
                                          "expires_in": 3600, "token_type": "Bearer"})

    flow, tokens, secret = _oauth(tmp_path, handler)
    with pytest.raises(PublishingError, match="connect_permission_required"):
        flow.begin("http://127.0.0.1:49152/oauth2/callback", allow_connect=False)
    auth = flow.begin("http://127.0.0.1:49152/oauth2/callback", allow_connect=True)
    params = parse_qs(urlsplit(auth.authorization_url).query)
    assert params["code_challenge_method"] == ["S256"]
    assert params["access_type"] == ["offline"]
    assert params["state"] == [auth.state]
    assert params["code_challenge"] == [base64.urlsafe_b64encode(hashlib.sha256(auth.verifier.encode()).digest()).rstrip(b"=").decode()]
    assert "offline-secret" not in auth.authorization_url
    assert "offline-secret" not in repr(auth)
    flow.complete(auth, f"{auth.redirect_uri}?state={auth.state}&code=offline-code", allow_connect=True)
    body = parse_qs(calls[0].content.decode())
    assert body["code_verifier"] == [auth.verifier]
    assert body["redirect_uri"] == [auth.redirect_uri]
    assert tokens.access_token(allow_refresh=False) == "offline-access"
    assert secret.read("tokens")["expires_at"] == 4600.0
    assert len(calls) == 1


@pytest.mark.parametrize("kind", ["state", "pkce", "expired", "duplicate", "host", "error"])
def test_oauth_rejects_invalid_callback_without_http(tmp_path, kind):
    from dataclasses import replace

    calls = []
    flow, _, _ = _oauth(tmp_path, lambda request: calls.append(request))
    auth = flow.begin("http://127.0.0.1:49152/oauth2/callback", allow_connect=True)
    callback = f"{auth.redirect_uri}?state={auth.state}&code=offline-code"
    if kind == "state":
        callback = f"{auth.redirect_uri}?state=wrong&code=offline-code"
    elif kind == "pkce":
        auth = replace(auth, verifier="x" * 43)
    elif kind == "expired":
        auth = replace(auth, expires_at=999.0)
    elif kind == "duplicate":
        callback += "&state=duplicate"
    elif kind == "host":
        callback = callback.replace("127.0.0.1", "localhost.attacker.invalid")
    else:
        callback = f"{auth.redirect_uri}?state={auth.state}&error=access_denied"
    with pytest.raises(PublishingError, match="oauth_"):
        flow.complete(auth, callback, allow_connect=True)
    assert calls == []


def test_expired_token_refresh_is_bounded_preserves_refresh_and_redacts(tmp_path, caplog):
    import httpx
    import logging

    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) < 3:
            return httpx.Response(503, text="offline-secret offline-refresh")
        return httpx.Response(200, json={"access_token": "new-offline-access", "expires_in": 3600,
                                          "token_type": "Bearer"})

    _, tokens, secret = _oauth(tmp_path, handler)
    secret.write("tokens", {"access_token": "expired-offline", "refresh_token": "offline-refresh", "expires_at": 999.0})
    with caplog.at_level(logging.DEBUG):
        assert tokens.access_token(allow_refresh=True) == "new-offline-access"
    assert len(requests) == 3
    assert secret.read("tokens")["refresh_token"] == "offline-refresh"
    assert "offline-refresh" not in caplog.text
    assert "new-offline-access" not in repr(tokens)


@pytest.mark.parametrize("status,expected_calls", [(400, 1), (401, 1), (429, 3), (503, 3)])
def test_refresh_failure_has_hard_cap_and_no_upstream_secret(tmp_path, status, expected_calls):
    import httpx
    from packages.core.publishing.errors import PublishingError

    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, text="offline-refresh offline-secret")

    _, tokens, secret = _oauth(tmp_path, handler)
    secret.write("tokens", {"access_token": "expired", "refresh_token": "offline-refresh", "expires_at": 1.0})
    with pytest.raises(PublishingError) as error:
        tokens.access_token(allow_refresh=True)
    assert "offline-refresh" not in str(error.value)
    assert "offline-secret" not in str(error.value)
    assert error.value.__cause__ is None
    assert len(calls) == expected_calls


def test_oauth_requires_installed_client_and_loopback(tmp_path):
    from packages.core.publishing.oauth import InstalledClient

    with pytest.raises(PublishingError, match="installed_client_required"):
        InstalledClient.from_data({"web": {"client_id": "offline"}})
    flow, _, _ = _oauth(tmp_path, lambda _: pytest.fail("no HTTP"))
    for redirect in ("http://localhost:49152/callback", "http://127.0.0.1/callback", "https://example.invalid/callback"):
        with pytest.raises(PublishingError, match="loopback_redirect_required"):
            flow.begin(redirect, allow_connect=True)


def _adapter(tmp_path, handler, *, allow_network=True):
    from packages.core.publishing.youtube import YouTubeHTTPAdapter
    import httpx

    _, tokens, secret = _oauth(tmp_path, handler)
    secret.write("tokens", {"access_token": "offline-access", "refresh_token": "offline-refresh", "expires_at": 4600.0})
    return YouTubeHTTPAdapter(httpx.Client(transport=httpx.MockTransport(handler)), tokens,
                              allow_network=allow_network, sleep=lambda _: None), secret


def test_private_insert_payload_and_exact_readback(tmp_path):
    import httpx
    from packages.core.publishing.contracts import UploadOptions
    from packages.core.schemas import VideoMetadata

    requests = []
    session = "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=offline-session"

    def handler(request):
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(200, headers={"Location": session})
        if request.method == "PUT":
            return httpx.Response(201, json={"id": "testvid0001"})
        return httpx.Response(200, json={"items": [{"id": "testvid0001", "status": {
            "privacyStatus": "private", "uploadStatus": "uploaded", "selfDeclaredMadeForKids": False}}]})

    adapter, _ = _adapter(tmp_path, handler)
    options = UploadOptions(category_id="22", made_for_kids=False, contains_synthetic_media=True)
    uri = adapter.initiate_private(VideoMetadata(title="Offline test", description="No real upload"), 3, options,
                                   allow_upload=True)
    body = json.loads(requests[0].content)
    assert body["status"] == {"privacyStatus": "private", "selfDeclaredMadeForKids": False,
                               "containsSyntheticMedia": True}
    assert "publishAt" not in body["status"]
    assert requests[0].url.params["uploadType"] == "resumable"
    assert requests[0].url.params["part"] == "snippet,status"
    progress = adapter.upload_chunk(uri, b"abc", offset=0, total=3, allow_upload=True)
    assert progress.video_id == "testvid0001"
    assert requests[1].headers["Content-Range"] == "bytes 0-2/3"
    video = adapter.read_video(progress.video_id, allow_read=True)
    assert video.privacy_status == "private"
    assert requests[-1].url.params["id"] == "testvid0001"


@pytest.mark.parametrize("offset", [0, 262144])
def test_resumable_probe_parses_authoritative_offset(tmp_path, offset):
    import httpx

    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(308, headers={"Range": f"bytes=0-{offset - 1}"} if offset else {})

    adapter, _ = _adapter(tmp_path, handler)
    result = adapter.query_upload("https://www.googleapis.com/upload/youtube/v3/videos?upload_id=offline",
                                  total=524288, allow_read=True)
    assert result.offset == offset
    assert requests[0].headers["Content-Range"] == "bytes */524288"
    assert requests[0].content == b""


@pytest.mark.parametrize("url", ["http://www.googleapis.com/upload/youtube/v3/videos?upload_id=x",
                                  "https://evil.invalid/upload/youtube/v3/videos?upload_id=x",
                                  "https://www.googleapis.com@evil.invalid/upload/youtube/v3/videos?upload_id=x"])
def test_signed_session_uri_is_origin_restricted_before_auth(tmp_path, url):
    adapter, _ = _adapter(tmp_path, lambda _: pytest.fail("no HTTP"))
    with pytest.raises(PublishingError, match="session_uri_invalid"):
        adapter.query_upload(url, total=3, allow_read=True)


def test_adapter_refuses_network_and_redacts_signed_url_on_error(tmp_path, caplog):
    import httpx
    import logging
    from packages.core.publishing.contracts import UploadOptions
    from packages.core.schemas import VideoMetadata

    requests = []
    session = "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=offline-signed-secret"

    def handler(request):
        requests.append(request)
        raise httpx.ReadTimeout(str(request.url))

    adapter, _ = _adapter(tmp_path, handler, allow_network=False)
    with pytest.raises(PublishingError, match="network_permission_required"):
        adapter.read_video("testvid0001", allow_read=True)
    assert not requests
    adapter.allow_network = True
    with caplog.at_level(logging.DEBUG), pytest.raises(PublishingError) as error:
        adapter.upload_chunk(session, b"abc", offset=0, total=3, allow_upload=True)
    assert len(requests) == 1, "ambiguous writes are not blindly retried"
    assert "offline-signed-secret" not in str(error.value) + caplog.text
    with pytest.raises(PublishingError, match="upload_permission_required"):
        adapter.initiate_private(VideoMetadata(title="x", description="y"), 3,
                                 UploadOptions(category_id="22", made_for_kids=False, contains_synthetic_media=True),
                                 allow_upload=False)


def test_readback_rejects_another_id_and_malformed_status(tmp_path):
    import httpx

    adapter, _ = _adapter(tmp_path, lambda _: httpx.Response(200, json={"items": [
        {"id": "othervid001", "status": {"privacyStatus": "private", "uploadStatus": "uploaded"}}]}))
    with pytest.raises(PublishingError, match="remote_video_mismatch"):
        adapter.read_video("testvid0001", allow_read=True)



def _service(tmp_path, monkeypatch, handler, *, content=b"offline media test bytes", db_path=None, **kwargs):
    import hashlib
    from packages.core.artifacts import ARTIFACT_MODELS
    from packages.core.orchestration import JobState, JobStore
    from packages.core.publishing.contracts import PublishingArtifact, UploadOptions
    from packages.core.publishing.service import PublishingService

    # Deliberately replace the FFprobe/editorial boundary, not the publisher's
    # own approval, on-disk bytes, hash, lease or state checks.
    monkeypatch.setitem(ARTIFACT_MODELS, "publishing.json", PublishingArtifact)
    store = JobStore(db_path or tmp_path / "factory.db", tmp_path / "jobs")
    job = store.create(title="Offline publishing boundary test", state=JobState.APPROVED, payload={
        "provider_mode": "live", "approved_by": "offline-test", "approved_at": "2026-01-01T00:00:00Z",
        "approved_inputs_sha256": "a" * 64})
    path = store.artifact_dir(job.id) / "output.mp4"
    path.write_bytes(content)
    store.write_artifact(job.id, "render.json", {"output_path": "output.mp4", "sha256": hashlib.sha256(content).hexdigest(),
        "storyboard_sha256": "b" * 64, "audio_sha256": "c" * 64, "duration_ms": 30000.0,
        "frame_count": 900, "probe": {}, "composition": "Short"})
    store.write_artifact(job.id, "metadata.json", {"title": "Uji offline", "description": "Not uploaded", "tags": [],
                                                "script_sha256": "b" * 64})
    adapter, secret = _adapter(tmp_path, handler)
    service = PublishingService(store, adapter, secret, eligibility=lambda *_: None,
                                fingerprint=lambda *_: "a" * 64, **kwargs)
    options = UploadOptions(category_id="22", made_for_kids=False, contains_synthetic_media=True)
    return service, store, job.id, options, secret


def _successful_http(request):
    import httpx
    if request.method == "POST":
        return httpx.Response(200, headers={"Location": "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=offline-session"})
    if request.method == "PUT":
        return httpx.Response(201, json={"id": "testvid0001"})
    return httpx.Response(200, json={"items": [{"id": "testvid0001", "status": {
        "privacyStatus": "private", "uploadStatus": "uploaded"}}]})


def test_service_uploads_private_persists_and_never_reinserts(tmp_path, monkeypatch):
    from packages.core.orchestration import JobState

    requests = []

    def handler(request):
        requests.append(request)
        return _successful_http(request)

    service, store, job_id, options, secret = _service(tmp_path, monkeypatch, handler)
    result = service.upload_private(job_id, options, allow_upload=True)
    assert result.phase == "private"
    assert store.get(job_id).state is JobState.PRIVATE_UPLOAD
    assert store.read_artifact(job_id, "publishing.json")["video_id"] == "testvid0001"
    assert store.get(job_id).payload["youtube_video_id"] == "testvid0001"
    assert secret.read(f"session-{job_id}") is None
    assert service.upload_private(job_id, options, allow_upload=True).phase == "private"
    assert sum(request.method == "POST" for request in requests) == 1
    assert sum(e["to_state"] == "PRIVATE_UPLOAD" for e in store.events(job_id)) == 1
    assert "offline-session" not in json.dumps(store.read_artifact(job_id, "publishing.json"))


@pytest.mark.parametrize("field,value", [("selfDeclaredMadeForKids", True), ("containsSyntheticMedia", False)])
def test_private_readback_rejects_conflicting_operator_disclosures(tmp_path, monkeypatch, field, value):
    import httpx
    from packages.core.orchestration import JobState

    def handler(request):
        response = _successful_http(request)
        if request.method != "GET":
            return response
        body = response.json()
        body["items"][0]["status"][field] = value
        return httpx.Response(200, json=body)

    service, store, job_id, options, _ = _service(tmp_path, monkeypatch, handler)
    with pytest.raises(PublishingError, match="remote_status_mismatch"):
        service.upload_private(job_id, options, allow_upload=True)
    assert store.get(job_id).state is JobState.APPROVED


@pytest.mark.parametrize("reason", ["permission", "unapproved", "mock", "missing_actor", "missing_stamp", "stale_fingerprint",
                                     "missing_file", "changed_media", "lease"])
def test_service_gates_refuse_before_any_http(tmp_path, monkeypatch, reason):
    from packages.core.orchestration import JobState

    service, store, job_id, options, _ = _service(tmp_path, monkeypatch, lambda _: pytest.fail("no HTTP"))
    record = store.get(job_id)
    if reason == "unapproved":
        store.transition(job_id, JobState.CANCELLED)
    elif reason == "mock":
        store.transition(job_id, record.state, payload_patch={"provider_mode": "mock"})
    elif reason == "missing_actor":
        store.transition(job_id, record.state, payload_patch={"approved_by": ""})
    elif reason == "missing_stamp":
        store.transition(job_id, record.state, payload_patch={"approved_at": ""})
    elif reason == "stale_fingerprint":
        store.transition(job_id, record.state, payload_patch={"approved_inputs_sha256": "d" * 64})
    elif reason == "missing_file":
        (store.artifact_root(job_id) / "output.mp4").unlink()
    elif reason == "changed_media":
        (store.artifact_root(job_id) / "output.mp4").write_bytes(b"tampered media")
    elif reason == "lease":
        assert store.acquire_lease(job_id, ttl_s=300)
    with pytest.raises(PublishingError):
        service.upload_private(job_id, options, allow_upload=reason != "permission")
    assert not (store.artifact_root(job_id) / "publishing.json").exists()


def test_lost_initiation_response_requires_manual_reconciliation_no_reinsert(tmp_path, monkeypatch):
    import httpx

    requests = []

    def handler(request):
        requests.append(request)
        raise httpx.ReadTimeout("offline upstream secret")

    service, store, job_id, options, _ = _service(tmp_path, monkeypatch, handler)
    with pytest.raises(PublishingError, match="manual_reconciliation_required"):
        service.upload_private(job_id, options, allow_upload=True)
    assert store.read_artifact(job_id, "publishing.json")["phase"] == "uncertain"
    with pytest.raises(PublishingError, match="manual_reconciliation_required"):
        service.upload_private(job_id, options, allow_upload=True)
    assert len(requests) == 1


def test_resumable_restart_reopens_at_server_offset_without_insert(tmp_path, monkeypatch):
    import httpx
    from packages.core.publishing.service import PublishingService

    requests = []
    interrupted = [False]

    def handler(request):
        requests.append(request)
        if request.method in ("POST", "GET"):
            return _successful_http(request)
        if request.headers["Content-Range"].startswith("bytes */"):
            return httpx.Response(308, headers={"Range": "bytes=0-262143"})
        if request.headers["Content-Range"].startswith("bytes 0-"):
            return httpx.Response(308, headers={"Range": "bytes=0-262143"})
        if not interrupted[0]:
            interrupted[0] = True
            raise KeyboardInterrupt
        return httpx.Response(201, json={"id": "testvid0001"})

    content = b"a" * (262144 + 101)
    service, store, job_id, options, secret = _service(tmp_path, monkeypatch, handler, content=content, chunk_size=262144)
    with pytest.raises(KeyboardInterrupt):
        service.upload_private(job_id, options, allow_upload=True)
    assert store.read_artifact(job_id, "publishing.json")["offset"] == 262144
    reopened = PublishingService(store, service.gateway, secret, eligibility=lambda *_: None,
                                 fingerprint=lambda *_: "a" * 64, chunk_size=262144)
    result = reopened.upload_private(job_id, options, allow_upload=True)
    assert result.phase == "private"
    assert result.retry_count == 0, "a successful restart probe is not a failed upload attempt"
    assert sum(request.method == "POST" for request in requests) == 1
    assert requests[-2].content == content[262144:]


@pytest.mark.parametrize("status", ["public", "unlisted", "missing"])
def test_readback_mismatch_never_claims_private_upload(tmp_path, monkeypatch, status):
    import httpx
    from packages.core.orchestration import JobState

    requests = []

    def handler(request):
        requests.append(request)
        if request.method != "GET":
            return _successful_http(request)
        return httpx.Response(200, json={"items": [] if status == "missing" else [{"id": "testvid0001", "status": {
            "privacyStatus": status, "uploadStatus": "uploaded"}}]})

    service, store, job_id, options, _ = _service(tmp_path, monkeypatch, handler)
    for _ in range(2):
        with pytest.raises(PublishingError):
            service.upload_private(job_id, options, allow_upload=True)
    assert store.get(job_id).state is JobState.APPROVED
    assert store.read_artifact(job_id, "publishing.json")["video_id"] == "testvid0001"
    assert sum(r.method == "POST" for r in requests) == 1


def _mutable_remote():
    import httpx

    requests = []
    status = {"privacyStatus": "private", "uploadStatus": "uploaded", "selfDeclaredMadeForKids": False,
              "license": "youtube", "embeddable": False, "publicStatsViewable": False,
              "containsSyntheticMedia": True}

    def handler(request):
        requests.append(request)
        if request.url.path == "/youtube/v3/videos" and request.method == "PUT":
            replacement = json.loads(request.content)["status"]
            status.clear()
            status.update({**replacement, "uploadStatus": "uploaded"})
            return httpx.Response(200, json={"id": "testvid0001", "status": status})
        if request.method == "GET":
            return httpx.Response(200, json={"items": [{"id": "testvid0001", "status": status}]})
        return _successful_http(request)
    return handler, requests, status


@pytest.mark.parametrize("reason", ["confirm", "permission", "operator", "naive", "past", "too_soon"])
def test_scheduling_requires_separate_permission_and_future_timezone(tmp_path, monkeypatch, reason):
    from datetime import datetime, timedelta, timezone

    handler, requests, _ = _mutable_remote()
    service, _, job_id, options, _ = _service(tmp_path, monkeypatch, handler)
    service.upload_private(job_id, options, allow_upload=True)
    count = len(requests)
    future = datetime.now(timezone.utc) + timedelta(days=10)
    if reason == "naive":
        future = future.replace(tzinfo=None)
    elif reason == "past":
        future -= timedelta(days=11)
    elif reason == "too_soon":
        future = datetime.now(timezone.utc) + timedelta(seconds=30)
    with pytest.raises(PublishingError):
        service.schedule(job_id, publish_at=future, confirm=reason != "confirm", operator="" if reason == "operator" else "operator",
                         allow_schedule=reason != "permission")
    assert len(requests) == count


def test_scheduling_is_private_explicit_exact_readback_and_idempotent(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from packages.core.orchestration import JobState

    handler, requests, status = _mutable_remote()
    service, store, job_id, options, _ = _service(tmp_path, monkeypatch, handler)
    service.upload_private(job_id, options, allow_upload=True)
    future = (datetime.now(timezone(timedelta(hours=7))) + timedelta(days=10)).replace(microsecond=0)
    result = service.schedule(job_id, publish_at=future, confirm=True, operator="operator", allow_schedule=True)
    assert result.phase == "scheduled"
    assert result.publish_at == future
    assert result.authorized_by == "operator"
    assert store.get(job_id).state is JobState.SCHEDULED
    assert status["privacyStatus"] == "private"
    assert status["publishAt"].endswith("Z")
    assert status["embeddable"] is False and status["selfDeclaredMadeForKids"] is False
    assert requests[-1].method == "GET", "an update response alone is not verification"
    service.schedule(job_id, publish_at=future, confirm=True, operator="operator", allow_schedule=True)
    updates = [r for r in requests if r.method == "PUT" and r.url.path == "/youtube/v3/videos"]
    assert len(updates) == 1


@pytest.mark.parametrize("confirm,permission", [(False, True), (True, False)])
def test_publish_now_requires_explicit_confirmation(tmp_path, monkeypatch, confirm, permission):
    handler, requests, _ = _mutable_remote()
    service, _, job_id, options, _ = _service(tmp_path, monkeypatch, handler)
    service.upload_private(job_id, options, allow_upload=True)
    count = len(requests)
    with pytest.raises(PublishingError):
        service.publish_now(job_id, confirm=confirm, operator="operator", allow_publish=permission)
    assert len(requests) == count


def test_publish_now_checks_state_integration_before_remote_mutation(tmp_path, monkeypatch):
    from packages.core.orchestration.states import TRANSITIONS, JobState

    handler, requests, _ = _mutable_remote()
    service, _, job_id, options, _ = _service(tmp_path, monkeypatch, handler)
    service.upload_private(job_id, options, allow_upload=True)
    monkeypatch.setitem(TRANSITIONS, JobState.PRIVATE_UPLOAD, TRANSITIONS[JobState.PRIVATE_UPLOAD] - {JobState.PUBLISHED})
    count = len(requests)
    with pytest.raises(PublishingError, match="publication_transition_missing"):
        service.publish_now(job_id, confirm=True, operator="operator", allow_publish=True)
    assert len(requests) == count


def test_publish_now_direct_transition_public_readback_no_fake_schedule(tmp_path, monkeypatch):
    from packages.core.orchestration.states import JobState

    handler, requests, status = _mutable_remote()
    service, store, job_id, options, _ = _service(tmp_path, monkeypatch, handler)
    service.upload_private(job_id, options, allow_upload=True)
    result = service.publish_now(job_id, confirm=True, operator="operator", allow_publish=True)
    assert result.phase == "published"
    assert store.get(job_id).state is JobState.PUBLISHED
    assert status["privacyStatus"] == "public" and "publishAt" not in status
    assert not any(e["to_state"] == "SCHEDULED" for e in store.events(job_id))
    assert requests[-1].method == "GET"
    assert service.publish_now(job_id, confirm=True, operator="operator", allow_publish=True).phase == "published"
    assert sum(r.method == "PUT" and r.url.path == "/youtube/v3/videos" for r in requests) == 1


def test_schedule_lost_response_reconciles_without_replaying_update(tmp_path, monkeypatch):
    import httpx
    from datetime import datetime, timedelta, timezone
    from packages.core.orchestration import JobState

    normal, requests, status = _mutable_remote()

    def handler(request):
        response = normal(request)
        if request.method == "PUT" and request.url.path == "/youtube/v3/videos":
            raise httpx.ReadTimeout("signed upstream secret")
        return response

    service, store, job_id, options, _ = _service(tmp_path, monkeypatch, handler)
    service.upload_private(job_id, options, allow_upload=True)
    future = (datetime.now(timezone.utc) + timedelta(days=10)).replace(microsecond=0)
    with pytest.raises(PublishingError, match="manual_reconciliation_required"):
        service.schedule(job_id, publish_at=future, confirm=True, operator="operator", allow_schedule=True)
    assert store.get(job_id).state is JobState.PRIVATE_UPLOAD
    assert store.read_artifact(job_id, "publishing.json")["phase"] == "scheduling"
    with pytest.raises(PublishingError, match="manual_reconciliation_required"):
        service.schedule(job_id, publish_at=future, confirm=True, operator="operator", allow_schedule=True)
    result = service.reconcile(job_id, video_id=None, confirm=True, operator="operator", allow_read=True)
    assert result.phase == "scheduled" and result.publish_at == future
    assert store.get(job_id).state is JobState.SCHEDULED
    assert sum(r.method == "PUT" and r.url.path == "/youtube/v3/videos" for r in requests) == 1


def test_manual_unknown_upload_reconciliation_requires_explicit_video_confirmation(tmp_path, monkeypatch):
    import httpx

    allow_read = [False]
    requests = []

    def handler(request):
        requests.append(request)
        if not allow_read[0]:
            raise httpx.ReadTimeout("offline secret")
        assert request.method == "GET"
        return _successful_http(request)

    service, _, job_id, options, _ = _service(tmp_path, monkeypatch, handler)
    with pytest.raises(PublishingError):
        service.upload_private(job_id, options, allow_upload=True)
    count = len(requests)
    with pytest.raises(PublishingError):
        service.reconcile(job_id, video_id="testvid0001", confirm=False, operator="operator", allow_read=True)
    assert len(requests) == count
    allow_read[0] = True
    result = service.reconcile(job_id, video_id="testvid0001", confirm=True, operator="operator", allow_read=True)
    assert result.phase == "private"
    assert len(requests) == count + 1


def test_chunk_lost_response_probes_completion_instead_of_reupload(tmp_path, monkeypatch):
    import httpx

    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "PUT" and not request.headers["Content-Range"].startswith("bytes */"):
            raise httpx.ReadTimeout("offline signed secret")
        return _successful_http(request)

    service, _, job_id, options, _ = _service(tmp_path, monkeypatch, handler)
    assert service.upload_private(job_id, options, allow_upload=True).phase == "private"
    assert sum(r.method == "POST" for r in requests) == 1
    assert sum(r.method == "PUT" for r in requests) == 2


def test_no_progress_upload_has_durable_retry_cap(tmp_path, monkeypatch):
    import httpx

    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(308) if request.method == "PUT" else _successful_http(request)

    service, store, job_id, options, _ = _service(tmp_path, monkeypatch, handler)
    for _ in range(2):
        with pytest.raises(PublishingError, match="manual_reconciliation_required"):
            service.upload_private(job_id, options, allow_upload=True)
    assert len(requests) == 4, "one insert plus three non-progressing chunk attempts, no restart replay"
    artifact = store.read_artifact(job_id, "publishing.json")
    assert artifact["phase"] == "uncertain"
    assert artifact["retry_count"] == 3


def test_cli_local_status_never_loads_credentials_or_calls_http(tmp_path, monkeypatch, capsys):
    from packages.core.orchestration import JobState, JobStore
    from scripts.publish import main

    data = tmp_path / "data"
    store = JobStore(data / "jobs" / "factory.db", data / "jobs")
    job = store.create(title="offline status", state=JobState.APPROVED, payload={"provider_mode": "mock"})
    result = main(["--status", job.id, "--data-root", str(data)],
                  http_factory=lambda: pytest.fail("status must not create HTTP client"))
    assert result == 0
    output = json.loads(capsys.readouterr().out)
    assert output["state"] == "APPROVED" and output["job_id"] == job.id
    assert output["publishing"] is None


@pytest.mark.parametrize("args", [[], ["--schedule", "a" * 16, "--publish-at", "2027-01-01T00:00:00+07:00"],
                                  ["--publish-now", "a" * 16], ["--upload", "a" * 16],
                                  ["--status", "../invalid"]])
def test_cli_invalid_or_unconfirmed_commands_have_no_connection(tmp_path, args):
    from scripts.publish import main

    with pytest.raises(SystemExit) as error:
        main([*args, "--data-root", str(tmp_path / "data")],
             http_factory=lambda: pytest.fail("unconfirmed command must not construct HTTP"))
    assert error.value.code == 2


def test_loopback_connect_is_injectable_bounded_and_silent(tmp_path, caplog):
    import io
    import httpx
    from urllib.parse import parse_qs, urlsplit
    from packages.core.publishing.loopback import run_loopback

    opened = []
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"access_token": "offline-access", "refresh_token": "offline-refresh",
                                         "token_type": "Bearer", "expires_in": 3600})

    flow, _, secret = _oauth(tmp_path, handler)

    class FakeServer:
        def __init__(self, address, handler_type):
            assert address == ("127.0.0.1", 0)
            self.server_address = ("127.0.0.1", 49152)
            self.handler_type = handler_type
            self.closed = False

        def handle_request(self):
            query = parse_qs(urlsplit(opened[0]).query)
            receiver = object.__new__(self.handler_type)
            receiver.path = "/oauth2/callback?state=" + query["state"][0] + "&code=offline-code"
            receiver.headers = {"Host": "127.0.0.1:49152"}
            receiver.wfile = io.BytesIO()
            receiver.send_response = lambda *_: None
            receiver.send_header = lambda *_: None
            receiver.end_headers = lambda: None
            receiver.do_GET()

        def server_close(self):
            self.closed = True

    with pytest.raises(PublishingError, match="connect_permission_required"):
        run_loopback(flow, allow_connect=False, browser_open=lambda _: pytest.fail("no browser"), server_factory=FakeServer)
    run_loopback(flow, allow_connect=True, browser_open=lambda url: opened.append(url) or True,
                 server_factory=FakeServer)
    assert len(opened) == 1 and len(calls) == 1
    assert secret.read("tokens") is not None
    assert "offline-code" not in caplog.text


def test_stale_approval_after_initiation_stops_before_media_put(tmp_path, monkeypatch):
    changed = [False]
    requests = []

    def handler(request):
        requests.append(request)
        response = _successful_http(request)
        if request.method == "POST":
            changed[0] = True
        return response

    service, _, job_id, options, _ = _service(tmp_path, monkeypatch, handler)
    service.fingerprint = lambda *_: ("d" if changed[0] else "a") * 64
    with pytest.raises(PublishingError, match="approval_inputs_changed"):
        service.upload_private(job_id, options, allow_upload=True)
    assert [r.method for r in requests] == ["POST"]


def test_stale_approval_after_preflight_read_stops_status_update(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone

    changed = [False]
    checking = [False]
    normal, requests, _ = _mutable_remote()

    def handler(request):
        response = normal(request)
        if checking[0] and request.method == "GET":
            changed[0] = True
        return response

    service, _, job_id, options, _ = _service(tmp_path, monkeypatch, handler)
    service.upload_private(job_id, options, allow_upload=True)
    service.fingerprint = lambda *_: ("d" if changed[0] else "a") * 64
    checking[0] = True
    with pytest.raises(PublishingError, match="approval_inputs_changed"):
        service.schedule(job_id, publish_at=datetime.now(timezone.utc) + timedelta(days=10),
                         confirm=True, operator="operator", allow_schedule=True)
    assert not any(r.method == "PUT" and r.url.path == "/youtube/v3/videos" for r in requests)


def test_default_service_keeps_real_approval_gate_no_production_opt_out(tmp_path, monkeypatch):
    from packages.core.publishing.service import PublishingService

    service, store, job_id, options, secret = _service(tmp_path, monkeypatch, lambda _: pytest.fail("no HTTP"))
    production = PublishingService(store, service.gateway, secret)
    with pytest.raises(PublishingError, match="approval_eligibility_failed"):
        production.upload_private(job_id, options, allow_upload=True)
    assert not (store.artifact_root(job_id) / "publishing.json").exists()


@pytest.mark.parametrize("phase", ["schedule", "publish"])
def test_status_update_response_without_matching_readback_is_not_success(tmp_path, monkeypatch, phase):
    import httpx
    from datetime import datetime, timedelta, timezone
    from packages.core.orchestration.states import TRANSITIONS, JobState

    normal, requests, status = _mutable_remote()

    def handler(request):
        if request.method == "PUT" and request.url.path == "/youtube/v3/videos":
            requests.append(request)
            return httpx.Response(200, json={"id": "testvid0001", "status": {"privacyStatus": "public"}})
        return normal(request)

    service, store, job_id, options, _ = _service(tmp_path, monkeypatch, handler)
    service.upload_private(job_id, options, allow_upload=True)
    monkeypatch.setitem(TRANSITIONS, JobState.PRIVATE_UPLOAD, TRANSITIONS[JobState.PRIVATE_UPLOAD] | {JobState.PUBLISHED})
    with pytest.raises(PublishingError, match="manual_reconciliation_required"):
        if phase == "schedule":
            service.schedule(job_id, publish_at=datetime.now(timezone.utc) + timedelta(days=10),
                             confirm=True, operator="operator", allow_schedule=True)
        else:
            service.publish_now(job_id, confirm=True, operator="operator", allow_publish=True)
    assert store.get(job_id).state is JobState.PRIVATE_UPLOAD
    assert store.read_artifact(job_id, "publishing.json")["phase"] == ("scheduling" if phase == "schedule" else "publishing")
    assert status["privacyStatus"] == "private"


def test_expired_session_never_starts_another_insert(tmp_path, monkeypatch):
    import httpx

    requests = []
    resumed = [False]

    def handler(request):
        requests.append(request)
        if request.method == "POST":
            return _successful_http(request)
        if resumed[0]:
            return httpx.Response(404, text="offline-signed-secret")
        raise KeyboardInterrupt

    service, store, job_id, options, _ = _service(tmp_path, monkeypatch, handler)
    with pytest.raises(KeyboardInterrupt):
        service.upload_private(job_id, options, allow_upload=True)
    resumed[0] = True
    for _ in range(2):
        with pytest.raises(PublishingError, match="manual_reconciliation_required"):
            service.upload_private(job_id, options, allow_upload=True)
    assert sum(r.method == "POST" for r in requests) == 1
    assert store.read_artifact(job_id, "publishing.json")["phase"] == "uncertain"


def test_schedule_due_remote_public_is_verified_read_only(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from packages.core.orchestration import JobState

    normal, requests, status = _mutable_remote()
    service, store, job_id, options, _ = _service(tmp_path, monkeypatch, normal)
    service.upload_private(job_id, options, allow_upload=True)
    future = (datetime.now(timezone.utc) + timedelta(days=10)).replace(microsecond=0)
    service.schedule(job_id, publish_at=future, confirm=True, operator="operator", allow_schedule=True)
    service.clock = lambda: future + timedelta(seconds=1)
    status.pop("publishAt")
    status["privacyStatus"] = "public"
    count = len(requests)
    result = service.reconcile(job_id, video_id=None, confirm=True, operator="operator", allow_read=True)
    assert result.phase == "published"
    assert store.get(job_id).state is JobState.PUBLISHED
    assert [r.method for r in requests[count:]] == ["GET"]


@pytest.mark.parametrize("bad", [{"token_type": 123}, {"expires_in": -1}, {"expires_in": float("inf")},
                                 {"access_token": "bad\r\ntoken"}, {"scope": "wrong-scope"}])
def test_malformed_oauth_token_response_is_redacted_and_not_persisted(tmp_path, bad):
    import httpx

    response = {"access_token": "offline-access", "refresh_token": "offline-refresh",
                "token_type": "Bearer", "expires_in": 3600, **bad}
    # Construct bytes because JSON serializers correctly refuse Infinity by default.
    flow, _, secret = _oauth(tmp_path, lambda _: httpx.Response(200, content=json.dumps(response)))
    auth = flow.begin("http://127.0.0.1:49152/oauth2/callback", allow_connect=True)
    with pytest.raises(PublishingError):
        flow.complete(auth, f"{auth.redirect_uri}?state={auth.state}&code=offline-code", allow_connect=True)
    assert secret.read("tokens") is None


def test_loopback_deadline_and_browser_failure_do_not_exchange_tokens(tmp_path):
    from packages.core.publishing.loopback import run_loopback

    flow, _, secret = _oauth(tmp_path, lambda _: pytest.fail("no HTTP"))
    now = [0.0]

    class IdleServer:
        def __init__(self, *_):
            self.server_address = ("127.0.0.1", 49152)
            self.closed = False

        def handle_request(self):
            now[0] += 1

        def server_close(self):
            self.closed = True

    with pytest.raises(PublishingError, match="oauth_callback_timeout"):
        run_loopback(flow, allow_connect=True, browser_open=lambda _: True, timeout_s=1,
                     server_factory=IdleServer, monotonic=lambda: now[0])
    with pytest.raises(PublishingError, match="oauth_browser_open_failed"):
        run_loopback(flow, allow_connect=True, browser_open=lambda _: False, server_factory=IdleServer)
    assert secret.read("tokens") is None


def test_cli_upload_exercises_domain_with_injected_http_only(tmp_path, monkeypatch, capsys):
    import httpx
    import time
    from packages.core import approval
    from packages.core.orchestration import JobState
    from scripts.publish import main

    requests = []

    def handler(request):
        requests.append(request)
        return _successful_http(request)

    _, store, job_id, _, secret = _service(tmp_path, monkeypatch, handler,
                                          db_path=tmp_path / "jobs" / "factory.db")
    secret.write("client", {"installed": {"client_id": "offline-client", "client_secret": "offline-secret"}})
    secret.write("tokens", {"access_token": "offline-access", "refresh_token": "offline-refresh",
                             "expires_at": time.time() + 3600})
    monkeypatch.setattr(approval, "require_eligible", lambda *_: None)
    monkeypatch.setattr(approval, "approval_fingerprint", lambda *_: "a" * 64)
    result = main(["--upload", job_id, "--data-root", str(tmp_path), "--config-dir", str(secret.root),
                   "--category-id", "22", "--not-made-for-kids", "--synthetic-media"],
                  http_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
                  browser_open=lambda _: pytest.fail("upload must never initiate OAuth"))
    assert result == 0
    assert json.loads(capsys.readouterr().out)["phase"] == "private"
    assert store.get(job_id).state is JobState.PRIVATE_UPLOAD
    assert len(requests) == 3
    assert all(r.url.host == "www.googleapis.com" for r in requests)


def test_unicode_state_is_rejected_without_transport_or_raw_exception(tmp_path):
    flow, _, _ = _oauth(tmp_path, lambda _: pytest.fail("no HTTP"))
    auth = flow.begin("http://127.0.0.1:49152/oauth2/callback", allow_connect=True)
    with pytest.raises(PublishingError, match="oauth_state_mismatch"):
        flow.complete(auth, f"{auth.redirect_uri}?state=%C3%A9&code=offline-code", allow_connect=True)


def test_lease_loss_after_initiation_prevents_media_request(tmp_path, monkeypatch):
    requests = []
    holder = []

    def handler(request):
        requests.append(request)
        response = _successful_http(request)
        monkeypatch.setattr(holder[0], "renew_lease", lambda *args, **kwargs: False)
        return response

    service, store, job_id, options, _ = _service(tmp_path, monkeypatch, handler)
    holder.append(store)
    with pytest.raises(PublishingError, match="job_lease_lost"):
        service.upload_private(job_id, options, allow_upload=True)
    assert [r.method for r in requests] == ["POST"]


def test_media_mutation_after_session_initiation_prevents_transfer(tmp_path, monkeypatch):
    requests = []
    path = []

    def handler(request):
        requests.append(request)
        response = _successful_http(request)
        path[0].write_bytes(b"mutated offline media")
        return response

    service, store, job_id, options, _ = _service(tmp_path, monkeypatch, handler)
    path.append(store.artifact_root(job_id) / "output.mp4")
    with pytest.raises(PublishingError, match="manual_reconciliation_required"):
        service.upload_private(job_id, options, allow_upload=True)
    assert [r.method for r in requests] == ["POST"]


def _png_bytes(width=1, height=1):
    import struct
    import zlib

    def chunk(kind, payload):
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + bytes((10, 20, 30)) * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


def _thumbnail_service(tmp_path, monkeypatch, handler, *, wide=None, **kwargs):
    """_service plus a valid thumbnail.json so the publishing boundary can find one."""
    import hashlib
    from packages.core.media.contracts import ThumbnailArtifact
    from packages.core.publishing import service as module

    image = wide or _png_bytes(2, 2)
    service, store, job_id, options, secret = _service(tmp_path, monkeypatch, handler, **kwargs)
    source = store.artifact_root(job_id) / "thumbnail.png"
    source.write_bytes(_png_bytes(1, 1))
    store.write_artifact(job_id, "thumbnail.json", ThumbnailArtifact(
        output_path="thumbnail.png", sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        storyboard_sha256="b" * 64, metadata_sha256="c" * 64, assets_sha256="d" * 64,
        scene_id="scene-1", frame=1).model_dump(mode="json"))
    # FFmpeg is a real external boundary; the unit test replaces only the transcode.
    monkeypatch.setattr(module, "wide_thumbnail", lambda _source, target: target.write_bytes(image) or target)
    return service, store, job_id, options, secret, image


def test_thumbnail_adapter_rejects_bad_input_before_any_http(tmp_path):
    import httpx
    from packages.core.publishing.errors import RemoteError

    requests = []
    adapter, _ = _adapter(tmp_path, lambda request: requests.append(request) or httpx.Response(200))
    with pytest.raises(PublishingError, match="thumbnail_too_large"):
        adapter.set_thumbnail("testvid0001", b"x" * (2 * 1024 * 1024 + 1), allow_upload=True)
    with pytest.raises(PublishingError, match="thumbnail_type_invalid"):
        adapter.set_thumbnail("testvid0001", b"not-an-image", allow_upload=True)
    with pytest.raises(PublishingError, match="upload_permission_required"):
        adapter.set_thumbnail("testvid0001", _png_bytes(), allow_upload=False)
    with pytest.raises(RemoteError, match="remote_video_id_invalid"):
        adapter.set_thumbnail("short", _png_bytes(), allow_upload=True)
    assert requests == []


def test_thumbnail_adapter_posts_png_media_once(tmp_path):
    import httpx

    requests = []
    adapter, _ = _adapter(tmp_path, lambda request: requests.append(request) or httpx.Response(200))
    adapter.set_thumbnail("testvid0001", _png_bytes(), allow_upload=True)
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert "/upload/youtube/v3/thumbnails/set" in str(request.url)
    assert request.url.params["videoId"] == "testvid0001"
    assert request.url.params["uploadType"] == "media"
    assert request.headers["Content-Type"] == "image/png"
    assert request.headers["Authorization"].startswith("Bearer ")


def test_thumbnail_adapter_rejects_channel_that_is_not_exactly_one(tmp_path):
    import httpx
    from packages.core.publishing.errors import RemoteError

    adapter, _ = _adapter(tmp_path, lambda _: httpx.Response(200, json={"items": []}))
    with pytest.raises(RemoteError, match="remote_channel_invalid"):
        adapter.read_channel(allow_read=True)
    adapter, _ = _adapter(tmp_path, lambda _: httpx.Response(200, json={"items": [
        {"id": "c1", "snippet": {"title": "a"}}, {"id": "c2", "snippet": {"title": "b"}}]}))
    with pytest.raises(RemoteError, match="remote_channel_invalid"):
        adapter.read_channel(allow_read=True)


def test_private_upload_sets_thumbnail_once_and_is_idempotent(tmp_path, monkeypatch):
    import hashlib
    import httpx
    from packages.core.orchestration import JobState

    requests = []

    def handler(request):
        requests.append(request)
        if "/thumbnails/set" in str(request.url):
            return httpx.Response(200)
        return _successful_http(request)

    service, store, job_id, options, _, image = _thumbnail_service(tmp_path, monkeypatch, handler)
    result = service.upload_private(job_id, options, allow_upload=True)
    assert result.phase == "private"
    assert store.get(job_id).state is JobState.PRIVATE_UPLOAD
    stored = store.read_artifact(job_id, "publishing.json")
    assert stored["thumbnail_sha256"] == hashlib.sha256(image).hexdigest()
    assert stored["thumbnail_uploaded_at"]
    assert "error_code" not in stored
    assert service.upload_private(job_id, options, allow_upload=True).phase == "private"
    assert sum("/thumbnails/set" in str(request.url) for request in requests) == 1
    assert sum(request.method == "POST" and "/upload/youtube/v3/videos" in str(request.url)
               for request in requests) == 1


def test_thumbnail_failure_does_not_fail_the_private_upload(tmp_path, monkeypatch):
    import httpx
    from packages.core.orchestration import JobState

    def handler(request):
        if "/thumbnails/set" in str(request.url):
            return httpx.Response(403, json={"error": "forbidden"})
        return _successful_http(request)

    service, store, job_id, options, _, _ = _thumbnail_service(tmp_path, monkeypatch, handler)
    result = service.upload_private(job_id, options, allow_upload=True)
    assert result.phase == "private"
    assert store.get(job_id).state is JobState.PRIVATE_UPLOAD
    stored = store.read_artifact(job_id, "publishing.json")
    assert stored.get("thumbnail_sha256") is None
    assert "thumbnail_uploaded_at" not in stored
    assert stored["error_code"] == "thumbnail_upload_failed"
    # A retry only re-runs the thumbnail step; the video is never inserted again.
    retried = service.upload_thumbnail(job_id, allow_upload=True)
    assert retried.error_code == "thumbnail_upload_failed"


def test_upload_thumbnail_requires_a_verified_private_upload(tmp_path, monkeypatch):
    service, _, job_id, options, _, _ = _thumbnail_service(
        tmp_path, monkeypatch, lambda _: pytest.fail("no HTTP"))
    with pytest.raises(PublishingError, match="verified_private_upload_required"):
        service.upload_thumbnail(job_id, allow_upload=True)
    with pytest.raises(PublishingError, match="upload_permission_required"):
        service.upload_thumbnail(job_id, allow_upload=False)


def test_cli_check_reports_channel_and_scope_without_writing(tmp_path, monkeypatch, capsys):
    import httpx
    import time
    from scripts.publish import main

    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"items": [{"id": "UCoffline", "snippet": {"title": "Kanal Offline"}}]})

    _, _, _, _, secret = _service(tmp_path, monkeypatch, handler, db_path=tmp_path / "jobs" / "factory.db")
    secret.write("client", {"installed": {"client_id": "offline-client", "client_secret": "offline-secret"}})
    secret.write("tokens", {"access_token": "offline-access", "refresh_token": "offline-refresh",
                             "expires_at": time.time() + 3600})
    result = main(["--check", "--data-root", str(tmp_path), "--config-dir", str(secret.root)],
                  http_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
                  browser_open=lambda _: pytest.fail("--check must never start OAuth"))
    assert result == 0
    body = json.loads(capsys.readouterr().out)
    assert body == {"client": "ok", "channel": {"id": "UCoffline", "title": "Kanal Offline"},
                    "scope": "https://www.googleapis.com/auth/youtube.force-ssl"}
    assert [request.method for request in requests] == ["GET"]
    assert all("thumbnails" not in str(request.url) for request in requests)


def test_cli_check_without_client_fails_before_any_http(tmp_path, capsys):
    import httpx
    from scripts.publish import main

    result = main(["--check", "--data-root", str(tmp_path), "--config-dir", str(tmp_path / "config")],
                  http_factory=lambda: httpx.Client(transport=httpx.MockTransport(
                      lambda _: pytest.fail("no HTTP without a client"))),
                  browser_open=lambda _: pytest.fail("no browser"))
    assert result == 1
    assert json.loads(capsys.readouterr().err) == {"error": "installed_client_not_configured"}


def test_cli_thumbnail_only_retries_the_image_upload(tmp_path, monkeypatch, capsys):
    import httpx
    import time
    from packages.core import approval
    from scripts.publish import main

    requests = []

    def handler(request):
        requests.append(request)
        if "/thumbnails/set" in str(request.url):
            return httpx.Response(200)
        return _successful_http(request)

    service, store, job_id, options, secret, _ = _thumbnail_service(
        tmp_path, monkeypatch, handler, db_path=tmp_path / "jobs" / "factory.db")
    service.upload_private(job_id, options, allow_upload=True)
    requests.clear()
    monkeypatch.setattr(approval, "require_eligible", lambda *_: None)
    monkeypatch.setattr(approval, "approval_fingerprint", lambda *_: "a" * 64)
    secret.write("client", {"installed": {"client_id": "offline-client", "client_secret": "offline-secret"}})
    secret.write("tokens", {"access_token": "offline-access", "refresh_token": "offline-refresh",
                             "expires_at": time.time() + 3600})
    result = main(["--thumbnail", job_id, "--data-root", str(tmp_path), "--config-dir", str(secret.root)],
                  http_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
                  browser_open=lambda _: pytest.fail("thumbnail retry must never start OAuth"))
    assert result == 0
    assert json.loads(capsys.readouterr().out)["thumbnail_sha256"]
    assert [request.method for request in requests] == ["POST"]
    assert "/thumbnails/set" in str(requests[0].url)


def test_tampered_thumbnail_never_fails_the_verified_video_upload(tmp_path, monkeypatch):
    from packages.core.orchestration import JobState

    requests = []

    def handler(request):
        requests.append(request)
        return _successful_http(request)

    service, store, job_id, options, _, _ = _thumbnail_service(tmp_path, monkeypatch, handler)
    (store.artifact_root(job_id) / "thumbnail.png").write_bytes(_png_bytes(3, 3))
    result = service.upload_private(job_id, options, allow_upload=True)
    assert result.phase == "private"
    assert store.get(job_id).state is JobState.PRIVATE_UPLOAD
    stored = store.read_artifact(job_id, "publishing.json")
    assert stored.get("thumbnail_sha256") is None
    assert stored["error_code"] == "thumbnail_upload_failed"
    assert all("/thumbnails/set" not in str(request.url) for request in requests)


def test_thumbnail_artifact_pointing_outside_the_job_is_recorded_not_raised(tmp_path, monkeypatch):
    import hashlib
    from packages.core.media.contracts import ThumbnailArtifact
    from packages.core.orchestration import JobState

    def handler(request):
        return _successful_http(request)

    service, store, job_id, options, _, _ = _thumbnail_service(tmp_path, monkeypatch, handler)
    store.write_artifact(job_id, "thumbnail.json", ThumbnailArtifact(
        output_path="../escape.png", sha256=hashlib.sha256(b"x").hexdigest(),
        storyboard_sha256="b" * 64, metadata_sha256="c" * 64, assets_sha256="d" * 64,
        scene_id="scene-1", frame=1).model_dump(mode="json"))
    result = service.upload_private(job_id, options, allow_upload=True)
    assert result.phase == "private"
    assert store.get(job_id).state is JobState.PRIVATE_UPLOAD
    assert store.read_artifact(job_id, "publishing.json")["error_code"] == "thumbnail_upload_failed"


def test_cli_thumbnail_reports_failure_instead_of_claiming_success(tmp_path, monkeypatch, capsys):
    import httpx
    import time
    from packages.core import approval
    from scripts.publish import main

    def handler(request):
        if "/thumbnails/set" in str(request.url):
            return httpx.Response(403, json={"error": "forbidden"})
        return _successful_http(request)

    service, store, job_id, options, secret, _ = _thumbnail_service(
        tmp_path, monkeypatch, handler, db_path=tmp_path / "jobs" / "factory.db")
    service.upload_private(job_id, options, allow_upload=True)
    monkeypatch.setattr(approval, "require_eligible", lambda *_: None)
    monkeypatch.setattr(approval, "approval_fingerprint", lambda *_: "a" * 64)
    secret.write("client", {"installed": {"client_id": "offline-client", "client_secret": "offline-secret"}})
    secret.write("tokens", {"access_token": "offline-access", "refresh_token": "offline-refresh",
                             "expires_at": time.time() + 3600})
    result = main(["--thumbnail", job_id, "--data-root", str(tmp_path), "--config-dir", str(secret.root)],
                  http_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
                  browser_open=lambda _: pytest.fail("no OAuth"))
    assert result == 1
    assert json.loads(capsys.readouterr().err) == {"error": "thumbnail_upload_failed"}


def test_installed_client_accepts_the_official_v1_authorization_uri(tmp_path):
    """Downloaded Google client secrets still carry the v1 consent URI."""
    from packages.core.publishing.oauth import AUTHORIZATION_ENDPOINT, InstalledClient

    client = InstalledClient.from_data({"installed": {
        "client_id": "offline-client", "client_secret": "offline-secret",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"]}})
    assert client.client_id == "offline-client"
    # The flow always builds its own v2 URL, never the file's auth_uri.
    flow, _, _ = _oauth(tmp_path, lambda _: pytest.fail("no HTTP"))
    auth = flow.begin("http://127.0.0.1:49152/oauth2/callback", allow_connect=True)
    assert auth.authorization_url.startswith(AUTHORIZATION_ENDPOINT + "?")


def test_installed_client_rejects_foreign_authorization_or_token_endpoint(tmp_path):
    from packages.core.publishing.oauth import InstalledClient

    base = {"client_id": "offline-client", "client_secret": "offline-secret",
            "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_uri": "https://oauth2.googleapis.com/token"}
    for override in ({"auth_uri": "https://evil.invalid/o/oauth2/auth"},
                     {"auth_uri": "http://accounts.google.com/o/oauth2/auth"},
                     {"token_uri": "https://evil.invalid/token"}):
        with pytest.raises(PublishingError, match="installed_client_endpoint_invalid"):
            InstalledClient.from_data({"installed": base | override})


def _drop_tokens(secret) -> None:
    """Simulasikan OAuth yang belum pernah tersambung.

    `_service` menanam token supaya tes lain bisa bicara HTTP. Pre-flight justru
    perlu keadaan sebaliknya, jadi token dihapus dari protected store.
    """
    path = secret.root / "tokens.json"
    path.unlink(missing_ok=True)


def test_missing_oauth_does_not_lock_the_job_permanently(tmp_path, monkeypatch):
    """Gagal karena OAuth belum tersambung bukan alasan mengunci job.

    Kasus nyata: operator menjalankan --upload sebelum --connect. Nol request
    keluar dari mesin ini, jadi tidak ada sesi remote yang perlu direkonsiliasi.
    Perilaku lama menandai record `uncertain`, dan `uncertain` menolak semua
    percobaan berikutnya — job mustahil diunggah walau OAuth kemudian
    disambungkan. Kode error aslinya juga tertelan menjadi
    manual_reconciliation_required sehingga penyebabnya tidak terlihat.
    """
    service, store, job_id, options, secret = _service(tmp_path, monkeypatch, _successful_http)
    _drop_tokens(secret)

    with pytest.raises(PublishingError) as caught:
        service.upload_private(job_id, options, allow_upload=True)
    assert caught.value.code == "oauth_not_connected"

    record = store.read_artifact(job_id, "publishing.json")
    assert record["phase"] != "uncertain", "pre-flight failure must not lock the job"
    assert record["error_code"] == "oauth_not_connected"


def test_preflight_failure_allows_retry_after_oauth_is_connected(tmp_path, monkeypatch):
    """Setelah OAuth tersambung, job yang gagal pre-flight bisa diunggah."""
    service, store, job_id, options, secret = _service(tmp_path, monkeypatch, _successful_http)
    _drop_tokens(secret)

    with pytest.raises(PublishingError) as caught:
        service.upload_private(job_id, options, allow_upload=True)
    assert caught.value.code == "oauth_not_connected"

    # Operator menyambungkan OAuth, lalu mengulang perintah yang sama.
    secret.write("tokens", {"access_token": "offline-access", "refresh_token": "offline-refresh",
                            "expires_at": 4600.0})
    result = service.upload_private(job_id, options, allow_upload=True)
    assert result.video_id == "testvid0001"


def test_ambiguous_initiation_still_requires_reconciliation(tmp_path, monkeypatch):
    """Kegagalan ambigu tetap wajib rekonsiliasi: itu perilaku yang benar.

    Timeout setelah request terkirim bisa berarti sesi sudah tercipta di remote.
    Mengulanginya buta akan membuat video ganda, jadi `uncertain` harus tetap.
    """
    import httpx

    def handler(request):
        raise httpx.ReadTimeout("upstream silent")

    service, store, job_id, options, _ = _service(tmp_path, monkeypatch, handler)

    with pytest.raises(PublishingError, match="manual_reconciliation_required"):
        service.upload_private(job_id, options, allow_upload=True)
    assert store.read_artifact(job_id, "publishing.json")["phase"] == "uncertain"
