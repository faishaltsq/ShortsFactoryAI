"""Endpoint jadwal: status terbaca, tick hanya saat aktif, setelan tersimpan."""
from __future__ import annotations


from tests.test_api_studio import _client
from packages.core.config import get_settings


def test_status_jadwal_terbaca_dan_mati_secara_default(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    body = client.get("/api/schedule").json()
    assert body["enabled"] is False
    assert body["running"] is False
    # Default aman: satu video sehari, mode live, berhenti di render.
    assert body["max_per_day"] == 1
    assert body["interval_hours"] == 24


def test_tick_ditolak_saat_scheduler_mati(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    res = client.post("/api/schedule/tick")
    assert res.status_code == 409
    assert "tidak aktif" in res.text


def test_setelan_jadwal_tersimpan_lewat_api(tmp_path, monkeypatch):
    client, path = _client(tmp_path, monkeypatch)
    payload = client.get("/api/studio").json()["saved"]
    payload["schedule"] = {
        "enabled": True,
        "interval_hours": 168,
        "max_per_day": 1,
        "mode": "mock",
        "stop": "storyboard",
        "topics": ["Lubang hitam", "Sinyal alien"],
    }
    res = client.put("/api/studio", json=payload)
    assert res.status_code == 200, res.text
    saved = res.json()["saved"]["schedule"]
    assert saved["enabled"] is True
    assert saved["interval_hours"] == 168
    assert saved["topics"] == ["Lubang hitam", "Sinyal alien"]


def test_interval_di_luar_batas_ditolak(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    payload = client.get("/api/studio").json()["saved"]
    payload["schedule"] = {"enabled": True, "interval_hours": 999}
    res = client.put("/api/studio", json=payload)
    assert res.status_code == 422


def test_apply_menyalakan_lalu_mematikan_scheduler(tmp_path, monkeypatch):
    """Setelah setelan disimpan, apply menyalakan thread tanpa restart API."""
    from apps.api import app as api_module

    client, path = _client(tmp_path, monkeypatch)
    payload = client.get("/api/studio").json()["saved"]
    payload["schedule"] = {"enabled": True, "mode": "mock", "stop": "storyboard", "max_per_day": 0}
    client.put("/api/studio", json=payload)
    get_settings.cache_clear()

    res = client.post("/api/schedule/apply")
    assert res.status_code == 200, res.text
    assert res.json()["running"] is True

    # max_per_day=0: tidak akan pernah membuat job, jadi aman dinyalakan.
    tick = client.post("/api/schedule/tick")
    assert tick.status_code == 200
    assert tick.json()["due"] is False

    # Matikan lagi.
    payload["schedule"] = {"enabled": False}
    client.put("/api/studio", json=payload)
    get_settings.cache_clear()
    res = client.post("/api/schedule/apply")
    assert res.status_code == 200
    assert res.json()["running"] is False
    api_module.SCHEDULER = None
