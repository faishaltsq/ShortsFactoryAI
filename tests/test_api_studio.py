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
