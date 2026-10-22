"""Operator decisions reach the same gate the CLI uses, through the HTTP surface."""
import pytest
from fastapi.testclient import TestClient

import test_approval as approval_helpers
from packages.core.orchestration import JobState
# Imported into this namespace so pytest can discover it as a fixture here; the
# signature below is what actually requests it.
from test_approval import _only_approval_stages, _pending_job, _store
from test_approval import labelled_media  # noqa: F401


@pytest.fixture(scope="module", autouse=True)
def _use_approval_media(labelled_media):  # noqa: F811 - pytest fixture, not a shadowing redefinition
    """Borrow the offline media helper.

    _seed() asserts on a module-global that test_approval's own autouse fixture
    populates, and that fixture only runs inside its module. Pointing it here by
    hand is what lets these tests build the same eligible job. Assigned directly
    rather than through monkeypatch, which is function-scoped and cannot back a
    module-scoped fixture.
    """
    previous = approval_helpers._MEDIA
    approval_helpers._MEDIA = labelled_media
    yield
    approval_helpers._MEDIA = previous


def _client(store):
    from apps.api.main import create_app
    return TestClient(create_app(store=store), base_url="http://localhost", client=("127.0.0.1", 45000))


def _ready(tmp_path):
    """A job parked on READY_FOR_APPROVAL with a gate that already passed."""
    from packages.core.config import get_settings
    from packages.core.pipeline import PipelineRunner

    store = _store(tmp_path)
    job = _pending_job(store)
    runner = PipelineRunner(store, get_settings(), force_mock=True)
    _only_approval_stages(runner)
    report = runner.run(job.id, stop_at=JobState.READY_FOR_APPROVAL)
    assert report.ok, report.blocked_reason
    return store, job


def test_approve_endpoint_moves_the_job_and_records_the_operator(tmp_path):
    store, job = _ready(tmp_path)
    client = _client(store)

    response = client.post(f"/api/jobs/{job.id}/approve", json={"operator": "lo"})

    assert response.status_code == 200, response.text
    assert response.json()["state"] == "APPROVED"
    assert response.json()["gate"]["eligible"] is True
    record = store.get(job.id)
    assert record.state is JobState.APPROVED
    assert record.payload["approved_by"] == "lo"


def test_approve_endpoint_is_409_not_200_when_the_gate_no_longer_passes(tmp_path):
    """A stale verdict must not be approvable from a browser either."""
    store, job = _ready(tmp_path)
    client = _client(store)
    # Same trick as the CLI test: the artifact changes after the gate ran, so the
    # recorded verdict no longer describes the job sitting on disk.
    contradicted = store.read_artifact(job.id, "verification.json")
    contradicted["status"] = "unsupported"
    store.write_artifact(job.id, "verification.json", contradicted)

    response = client.post(f"/api/jobs/{job.id}/approve", json={"operator": "lo"})

    assert response.status_code == 409
    assert "source_verification" in response.json()["detail"]
    assert store.get(job.id).state is JobState.READY_FOR_APPROVAL, "a refusal must not move the job"


def test_reject_endpoint_records_the_reason_and_is_404_for_an_unknown_job(tmp_path):
    store, job = _ready(tmp_path)
    client = _client(store)

    response = client.post(f"/api/jobs/{job.id}/reject", json={"operator": "lo", "reason": "judul kurang tajam"})

    assert response.status_code == 200, response.text
    assert store.get(job.id).state is JobState.REJECTED
    assert store.get(job.id).payload["reject_reason"] == "judul kurang tajam"
    assert store.get(job.id).payload["rejected_by"] == "lo"

    missing = client.post("/api/jobs/0000000000000000/reject", json={"operator": "lo", "reason": "x"})
    assert missing.status_code == 404


def test_decision_endpoints_are_refused_across_origin_and_require_a_reason(tmp_path):
    store, job = _ready(tmp_path)
    client = _client(store)

    foreign = client.post(f"/api/jobs/{job.id}/approve", headers={"Origin": "https://evil.invalid"},
                          json={"operator": "lo"})
    assert foreign.status_code == 403

    blank_reason = client.post(f"/api/jobs/{job.id}/reject", json={"operator": "lo", "reason": "   "})
    assert blank_reason.status_code == 422
    assert store.get(job.id).state is JobState.READY_FOR_APPROVAL

    blank_operator = client.post(f"/api/jobs/{job.id}/approve", json={"operator": "  "})
    assert blank_operator.status_code == 422

    no_body = client.post(f"/api/jobs/{job.id}/approve")
    assert no_body.status_code == 422


def test_dashboard_origin_is_accepted_because_it_names_this_same_machine(tmp_path):
    """The Next.js dev server proxies to 127.0.0.1 while the browser says localhost."""
    store, job = _ready(tmp_path)
    client = _client(store)

    proxied = client.post(f"/api/jobs/{job.id}/approve", headers={"Origin": "http://localhost:3018"},
                          json={"operator": "lo"})

    assert proxied.status_code == 200, proxied.text
    assert store.get(job.id).state is JobState.APPROVED
