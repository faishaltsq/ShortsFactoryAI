import json

from fastapi.testclient import TestClient

from packages.core import prompts
from packages.core.config import get_settings
from packages.core.studio import AGENT_KEYS, StudioConfig, save_studio


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDIO_CONFIG", str(tmp_path / "studio.json"))
    monkeypatch.delenv("STUDIO_TOKEN", raising=False)
    get_settings.cache_clear()
    from apps.api.main import create_app
    from packages.core.orchestration import JobStore
    from packages.core.providers.router import ProviderRouter

    monkeypatch.setattr(ProviderRouter, "refresh_health", lambda self: {})
    store = JobStore(tmp_path / "jobs" / "factory.db", tmp_path / "jobs")
    app = create_app(store=store)
    return TestClient(app, base_url="http://localhost"), tmp_path / "studio.json"


def test_health(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["studio_exists"] is False


def test_configured_token_protects_every_api_route(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    monkeypatch.setenv("STUDIO_TOKEN", "api-test-token")
    assert client.get("/api/health").status_code == 401
    response = client.get("/api/health", headers={"Authorization": "Bearer api-test-token"})
    assert response.status_code == 200


def test_get_studio_returns_saved_effective_defaults_and_agent_keys(tmp_path, monkeypatch):
    client, path = _client(tmp_path, monkeypatch)
    save_studio(StudioConfig.model_validate({"agents": {"ScriptAgent": {"model": "tig/x"}}}), path)
    body = client.get("/api/studio").json()
    assert body["saved"]["agents"]["ScriptAgent"]["model"] == "tig/x"
    assert body["effective"]["budget"]["max_daily_tokens"] == 1000000   # conftest env
    assert set(body["agent_keys"]) == set(AGENT_KEYS)
    assert body["default_prompts"]["ScriptAgent"] == prompts.SCRIPT_SYSTEM
    assert body["runner_stops"] == ["research", "script", "creative", "storyboard", "audio", "render", "editorial", "approval"]
    # Roster persona: UI merender tiap agent sebagai orang, bukan identifier telanjang.
    assert set(body["personas"]) == set(AGENT_KEYS)
    assert body["personas"]["ScriptAgent"]["tier"] == "worker"
    assert body["personas"]["CreativeDirectorAgent"]["tier"] == "strategist"
    assert body["personas"]["ScriptAgent"]["stage"] == "SCRIPT_GENERATED"
    # Roster lengkap: 12 peran, termasuk tahap deterministik tanpa prompt yang bisa diedit.
    assert body["team"]["RenderAgent"]["editable"] is False
    assert body["team"]["PublishAgent"]["available"] is False
    assert body["team"]["ScriptAgent"]["persona"] == "Sora"
    assert set(body["team"]) - set(body["agent_keys"]) == {
        "FactoryOrchestrator", "AssetAgent", "AudioAgent", "RenderAgent", "PublishAgent"
    }


def test_put_studio_validates_and_persists(tmp_path, monkeypatch):
    client, path = _client(tmp_path, monkeypatch)
    ok = client.put("/api/studio", json={"agents": {"ScriptAgent": {"temperature": 0.3}}})
    assert ok.status_code == 200
    assert json.loads(path.read_text(encoding="utf-8"))["agents"]["ScriptAgent"]["temperature"] == 0.3

    bad = client.put("/api/studio", json={"agents": {"TypoAgent": {"model": "x"}}})
    assert bad.status_code == 422
    assert "unknown agent keys" in bad.text
    assert json.loads(path.read_text(encoding="utf-8"))["agents"]["ScriptAgent"]["temperature"] == 0.3


def test_put_studio_field_error_shape_untuk_ui(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    resp = client.put("/api/studio", json={"agents": {"ScriptAgent": {"temperature": 9}}})
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert any(item["loc"] == ["body", "agents", "ScriptAgent", "temperature"] for item in detail)


def test_jobs_list_empty_and_create_job(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    assert client.get("/api/jobs").json()["jobs"] == []
    created = client.post("/api/jobs", json={"title": "Judul uji", "mode": "mock", "stop": "storyboard"})
    assert created.status_code == 202
    job_id = created.json()["job_id"]
    detail = client.get(f"/api/jobs/{job_id}").json()
    assert detail["record"]["title"] == "Judul uji"
    # Run berjalan di thread background: hanya bentuk respons yang dicek supaya
    # test tidak flaky terhadap timing.
    assert "running" in detail["run"]


def test_run_endpoint_rejects_bad_stop(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    job_id = client.post("/api/jobs", json={"title": "judul valid", "mode": "mock", "stop": "storyboard"}).json()["job_id"]
    resp = client.post(f"/api/jobs/{job_id}/run", json={"mode": "mock", "stop": "publish"})
    assert resp.status_code == 422


def _wait_idle(client, job_id: str, tries: int = 100) -> None:
    """Tunggu run yang dimulai otomatis oleh POST /api/jobs benar-benar selesai.

    POST /api/jobs memulai run di thread background; ada jeda sebelum entri RUNS
    terbentuk. Membaca sekali bisa melihat `running: false` padahal run belum
    sempat terdaftar, sehingga run berikutnya ditolak 409.
    """
    import time

    seen = False
    for _ in range(tries):
        run = client.get(f"/api/jobs/{job_id}").json()["run"]
        if run.get("running"):
            seen = True
        elif seen:
            return
        time.sleep(0.1)


def test_mode_terkunci_pada_job(tmp_path, monkeypatch):
    """Job yang lahir mock tetap mock walau UI mengirim live.

    Menjalankan job mock dengan model asli mencampur artifact palsu dan asli
    dalam satu video, jadi runner menolaknya. Lebih baik server mengabaikan
    pilihan yang bertentangan daripada menggagalkan run di tengah jalan.
    """
    client, _ = _client(tmp_path, monkeypatch)
    job_id = client.post("/api/jobs", json={"title": "mode terkunci", "mode": "mock",
                                            "stop": "research"}).json()["job_id"]
    _wait_idle(client, job_id)
    resp = client.post(f"/api/jobs/{job_id}/run", json={"mode": "live", "stop": "research"})
    assert resp.status_code == 202
    assert resp.json()["mode"] == "mock", "mode job tidak boleh ditimpa UI"


def test_run_tanpa_mode_memakai_mode_job(tmp_path, monkeypatch):
    """UI tidak perlu mengirim mode sama sekali."""
    client, _ = _client(tmp_path, monkeypatch)
    job_id = client.post("/api/jobs", json={"title": "tanpa mode", "mode": "mock",
                                            "stop": "research"}).json()["job_id"]
    _wait_idle(client, job_id)
    resp = client.post(f"/api/jobs/{job_id}/run", json={"stop": "research"})
    assert resp.status_code == 202
    assert resp.json()["mode"] == "mock"


def test_resolusi_mode_mengutamakan_mode_job(monkeypatch, tmp_path):
    """Mode job menang atas argumen dan atas default Studio."""
    client, _ = _client(tmp_path, monkeypatch)
    from types import SimpleNamespace

    from packages.core.pipeline import PipelineRunner

    monkeypatch.setattr(PipelineRunner, "run", lambda *args, **kwargs: SimpleNamespace(as_dict=lambda: {}))
    job = client.app.state.job_store.create(title="mode job live", payload={"provider_mode": "live"})
    response = client.post(f"/api/jobs/{job.id}/run",
                           json={"mode": "mock", "stop": "research"})
    assert response.status_code == 202
    assert response.json()["mode"] == "live"


def test_usage_endpoint(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    body = client.get("/api/usage/today").json()
    assert body["tokens"] == 0.0
    assert body["budget"]["max_daily_tokens"] > 0
    assert body["by_agent"] == []


def test_default_prompts_cover_every_agent():
    assert set(prompts.DEFAULT_SYSTEM) == set(AGENT_KEYS)
    for agent, text in prompts.DEFAULT_SYSTEM.items():
        assert len(text) > 80, agent


def test_history_dan_rollback_lewat_api(tmp_path, monkeypatch):
    client, path = _client(tmp_path, monkeypatch)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "agents": {}, "budget": {"max_daily_tokens": 100},
                                "production": {}, "runner": {"default_mode": "mock",
                                                             "default_stop": "storyboard"}}), encoding="utf-8")
    updated = client.put("/api/studio", json={"budget": {"max_daily_tokens": 200}})
    assert updated.status_code == 200
    history = client.get("/api/studio/history").json()["history"]
    assert history and history[0]["config"]["budget"]["max_daily_tokens"] == 100
    restored = client.post("/api/studio/rollback", json={"name": history[0]["name"]})
    assert restored.status_code == 200
    assert restored.json()["restored"]["budget"]["max_daily_tokens"] == 100
    bad = client.post("/api/studio/rollback", json={"name": "../evil.json"})
    assert bad.status_code == 409


def test_cancel_run_lewat_api(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    created = client.post("/api/jobs", json={"title": "cancel uji", "mode": "mock", "stop": "storyboard"}).json()
    res = client.post(f"/api/jobs/{created['job_id']}/cancel")
    assert res.status_code == 200
    assert res.json()["status"] in {"running", "idle"}


def test_detail_preserves_activity_but_does_not_invent_liveness_after_restart(tmp_path, monkeypatch):
    from packages.core.activity import ActivityReporter

    client, _ = _client(tmp_path, monkeypatch)
    store = client.app.state.job_store
    runtime = client.app.state.studio_runtime
    job = store.create(title="restart")
    ActivityReporter(store, job.id, "d" * 32).begin("ScriptAgent", "SCRIPT_GENERATED")
    with runtime["run_lock"]:
        runtime["runs"].pop(job.id, None)
    body = client.get(f"/api/jobs/{job.id}").json()
    assert body["record"]["payload"]["studio_activity"]["agent"] == "ScriptAgent"
    assert body["run"]["running"] is False
    assert "activity_token" not in body["run"]


def test_running_state_comes_from_the_lease_after_an_api_restart(tmp_path, monkeypatch):
    """The in-memory run table is process-local; a live worker is proven by its lease.

    Reproduces the seam: a worker holds the job lease, the API process restarts and
    its `runtime["runs"]` is empty, so `/api/jobs` used to report the job as idle
    while it was still rendering.
    """
    client, _ = _client(tmp_path, monkeypatch)
    store = client.app.state.job_store
    runtime = client.app.state.studio_runtime
    job = store.create(title="pekerjaan berjalan")
    token = store.acquire_lease(job.id)
    assert token is not None
    with runtime["run_lock"]:
        runtime["runs"].pop(job.id, None)

    listed = client.get("/api/jobs").json()
    assert listed["running"][job.id] is True

    detail = client.get(f"/api/jobs/{job.id}").json()
    assert detail["run"]["running"] is True

    cancelled = client.post(f"/api/jobs/{job.id}/cancel").json()
    assert cancelled["status"] == "running", "a leased job is still running after a cancel request"

    assert store.release_lease(job.id, token)
    assert client.get("/api/jobs").json()["running"].get(job.id) is not True
    assert client.get(f"/api/jobs/{job.id}").json()["run"]["running"] is False


def test_expired_lease_is_not_reported_as_running(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone

    client, _ = _client(tmp_path, monkeypatch)
    store = client.app.state.job_store
    job = store.create(title="lease kedaluwarsa")
    token = store.acquire_lease(job.id, ttl_s=60)
    assert token is not None
    with store._connect() as conn:
        conn.execute("UPDATE jobs SET lease_expires_at=? WHERE id=?",
                     ((datetime.now(timezone.utc) - timedelta(seconds=1)).timestamp(), job.id))

    assert client.get("/api/jobs").json()["running"].get(job.id) is not True
    assert client.get(f"/api/jobs/{job.id}").json()["run"]["running"] is False
