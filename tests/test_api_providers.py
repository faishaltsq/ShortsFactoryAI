"""Endpoint setelan provider: bisa dibaca, bisa diubah, dan tidak membocorkan kunci."""
import pytest

from tests.test_api_studio import _client
from packages.core.config import get_settings
from packages.core.studio import ProviderOverride, ProvidersOverride, StudioConfig, save_studio


def test_providers_menyertakan_setelan_yang_bisa_diedit(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    body = client.get("/api/providers").json()
    assert set(body["editable"]) == {"worker", "strategist_cli", "strategist_http"}
    assert "api_key" not in body["editable"]["worker"]
    # Hanya status ada/tidak, bukan nilainya.
    assert isinstance(body["editable"]["worker"]["has_key"], bool)


def test_kunci_tidak_pernah_muncul_di_response(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://env.example.com/v1")
    monkeypatch.setenv("DEEPSEEK_MODEL", "m")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "kunci-sangat-rahasia")
    get_settings.cache_clear()
    client, _ = _client(tmp_path, monkeypatch)
    raw = client.get("/api/providers").text
    assert "kunci-sangat-rahasia" not in raw


def test_setelan_tersimpan_dibaca_kembali_lewat_api(tmp_path, monkeypatch):
    client, path = _client(tmp_path, monkeypatch)
    save_studio(
        StudioConfig(providers=ProvidersOverride(
            worker=ProviderOverride(enabled=True, base_url="https://api.example.com/v1",
                                    model="model-baru", temperature=0.25)
        )),
        path,
    )
    get_settings.cache_clear()
    body = client.get("/api/providers").json()
    worker = body["editable"]["worker"]
    assert worker["base_url"] == "https://api.example.com/v1"
    assert worker["model"] == "model-baru"
    assert worker["temperature"] == 0.25
    assert worker["effective_model"] == "model-baru"


def test_put_studio_menyimpan_setelan_provider(tmp_path, monkeypatch):
    client, path = _client(tmp_path, monkeypatch)
    payload = client.get("/api/studio").json()["saved"]
    payload["providers"] = {
        "worker": {"base_url": "https://api.example.com/v1", "model": "m", "enabled": True},
        "strategist_cli": {"enabled": False},
        "strategist_http": {"model": "s"},
    }
    res = client.put("/api/studio", json=payload)
    assert res.status_code == 200, res.text
    saved = res.json()["saved"]["providers"]
    assert saved["worker"]["model"] == "m"
    assert saved["strategist_cli"]["enabled"] is False


def test_base_url_dengan_kredensial_ditolak_api(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    payload = client.get("/api/studio").json()["saved"]
    payload["providers"] = {"worker": {"base_url": "https://user:pass@example.com/v1"}}
    res = client.put("/api/studio", json=payload)
    assert res.status_code == 422
    assert "kredensial" in res.text


def test_model_katalog_tanpa_base_url_tidak_error(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    monkeypatch.delenv("STRATEGIST_BASE_URL", raising=False)
    get_settings.cache_clear()
    client, _ = _client(tmp_path, monkeypatch)
    body = client.get("/api/providers/models?target=worker").json()
    assert body["models"] == []
    assert body["error"]


def test_target_model_tidak_dikenal_ditolak(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    assert client.get("/api/providers/models?target=ngawur").status_code == 422
