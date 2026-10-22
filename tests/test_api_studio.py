import json

from fastapi.testclient import TestClient

import packages.core.config as config
from packages.core import prompts
from packages.core.config import get_settings
from packages.core.studio import AGENT_KEYS, StudioConfig, save_studio


def _client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setenv("STUDIO_CONFIG", str(tmp_path / "studio.json"))
    monkeypatch.delenv("STUDIO_TOKEN", raising=False)
    get_settings.cache_clear()
    from apps.api.app import app

    # `from ... import JOBS_DIR` di modul API mengikat nilai lama, jadi monkeypatch
    # pada packages.core.config saja tidak cukup: fixture ini bisa menulis ke
    # data/jobs operator yang asli.
    import importlib

    api_module = importlib.import_module("apps.api.app")
    monkeypatch.setattr(api_module, "JOBS_DIR", tmp_path / "jobs")
    return TestClient(app), tmp_path / "studio.json"


def test_health(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["studio_exists"] is False


def test_get_studio_returns_saved_effective_defaults_and_agent_keys(tmp_path, monkeypatch):
    client, path = _client(tmp_path, monkeypatch)
    save_studio(StudioConfig.model_validate({"agents": {"ScriptAgent": {"model": "tig/x"}}}), path)
    body = client.get("/api/studio").json()
    assert body["saved"]["agents"]["ScriptAgent"]["model"] == "tig/x"
    assert body["effective"]["budget"]["max_daily_tokens"] == 1000000   # conftest env
    assert set(body["agent_keys"]) == set(AGENT_KEYS)
    assert body["default_prompts"]["ScriptAgent"] == prompts.SCRIPT_SYSTEM
    assert body["runner_stops"] == ["research", "script", "creative", "storyboard", "audio", "render"]
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
    monkeypatch.setenv("STUDIO_CONFIG", str(tmp_path / "studio.json"))
    from apps.api import app as api_module

    # Job yang lahir live tetap live walau pemanggil mengirim mock.
    assert api_module._resolve_mode_stop("mock", "research", job_mode="live") == ("live", "research")
    # Tanpa mode job, argumen dipakai.
    assert api_module._resolve_mode_stop("live", "research")[0] == "live"


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
    import importlib

    from packages.core.activity import ActivityReporter
    from packages.core.orchestration import JobStore

    client, _ = _client(tmp_path, monkeypatch)
    module = importlib.import_module("apps.api.app")
    store = JobStore(tmp_path / "isolated.db", tmp_path / "jobs")
    monkeypatch.setattr(module, "_store", lambda: store)
    job = store.create(title="restart")
    ActivityReporter(store, job.id, "d" * 32).begin("ScriptAgent", "SCRIPT_GENERATED")
    with module.RUN_LOCK:
        module.RUNS.pop(job.id, None)
    body = client.get(f"/api/jobs/{job.id}").json()
    assert body["record"]["payload"]["studio_activity"]["agent"] == "ScriptAgent"
    assert body["run"]["running"] is False
    assert "activity_token" not in body["run"]
