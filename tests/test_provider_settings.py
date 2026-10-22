"""Setelan provider dari web: override non-rahasia, dan kunci yang tidak bocor.

Dua hal yang dijaga di sini:

1. Operator bisa mengganti base_url/model/temperature/nyala-mati tanpa edit .env.
2. Kunci API yang tersimpan di env tidak pernah ikut terkirim ke host lain saat
   base_url diarahkan ulang lewat UI. Ini yang membuat fitur ini aman dibuka.
"""
import packages.core.config as config
from packages.core.config import get_settings
from packages.core.providers import MockProvider, ProviderRouter
from packages.core.providers.router import build_router
from packages.core.studio import (
    ProviderOverride,
    ProvidersOverride,
    StudioConfig,
    StudioConfigError,
    save_studio,
)


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setenv("STUDIO_CONFIG", str(tmp_path / "studio.json"))
    get_settings.cache_clear()


def test_override_model_dan_base_url_dipakai_dari_studio(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "http://localhost:20128/v1")
    monkeypatch.setenv("DEEPSEEK_MODEL", "model-dari-env")
    save_studio(StudioConfig(providers=ProvidersOverride(
        worker=ProviderOverride(base_url="https://api.example.com/v1", model="model-dari-ui")
    )))
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.deepseek.base_url == "https://api.example.com/v1"
    assert settings.deepseek.model == "model-dari-ui"


def test_tanpa_override_env_tetap_dipakai(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://env.example.com/v1")
    monkeypatch.setenv("DEEPSEEK_MODEL", "model-env")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.deepseek.base_url == "https://env.example.com/v1"
    assert settings.deepseek.model == "model-env"


def test_kunci_tidak_ikut_pindah_host(tmp_path, monkeypatch):
    """Mengarahkan base_url ke host lain tidak boleh membawa kunci asli."""
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://env.example.com/v1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "kunci-asli-yang-tidak-boleh-bocor")
    save_studio(StudioConfig(providers=ProvidersOverride(
        worker=ProviderOverride(base_url="https://attacker.example.net/v1")
    )))
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.deepseek.api_key == ""
    # Mismatch harus terlihat, bukan senyap: provider tampak sehat lalu gagal 401.
    assert settings.deepseek.key_origin_mismatch is True


def test_host_sama_tidak_dianggap_mismatch(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://env.example.com/v1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "kunci-asli")
    save_studio(StudioConfig(providers=ProvidersOverride(
        worker=ProviderOverride(base_url="https://env.example.com/v2")
    )))
    get_settings.cache_clear()
    assert get_settings().deepseek.key_origin_mismatch is False


def test_localhost_dan_127_0_0_1_dianggap_beda_origin(tmp_path, monkeypatch):
    """Ini kasus nyata: .env pakai localhost, operator mengetik 127.0.0.1."""
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "http://localhost:20128/v1")
    monkeypatch.setenv("HERMES_CUSTOM_LOCALHOST_20128_API_KEY", "kunci-router")
    save_studio(StudioConfig(providers=ProvidersOverride(
        worker=ProviderOverride(base_url="http://127.0.0.1:20128/v1")
    )))
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.deepseek.api_key == ""
    assert settings.deepseek.key_origin_mismatch is True


def test_kunci_tetap_dipakai_saat_host_sama(tmp_path, monkeypatch):
    """Ganti path di host yang sama tetap membawa kunci: itu bukan eskalasi."""
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://env.example.com/v1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "kunci-asli")
    save_studio(StudioConfig(providers=ProvidersOverride(
        worker=ProviderOverride(base_url="https://env.example.com/v2")
    )))
    get_settings.cache_clear()
    assert get_settings().deepseek.api_key == "kunci-asli"


def test_base_url_dengan_kredensial_ditolak():
    """user:pass@ di URL akan bocor ke log, jadi ditolak saat validasi."""
    import pytest

    with pytest.raises(ValueError):
        ProviderOverride(base_url="https://user:rahasia@example.com/v1")


def test_enabled_false_mengeluarkan_provider_dari_chain(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "http://localhost:20128/v1")
    monkeypatch.setenv("DEEPSEEK_MODEL", "eg/elf/deepseek-v4.1-flash")
    monkeypatch.setenv("STRATEGIST_BASE_URL", "http://localhost:20128/v1")
    monkeypatch.setenv("STRATEGIST_MODEL", "eg/elf/deepseek-v4.1-flash")
    save_studio(StudioConfig(providers=ProvidersOverride(
        worker=ProviderOverride(enabled=False),
        strategist_http=ProviderOverride(enabled=False),
    )))
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.deepseek.configured is False
    assert settings.strategist.configured is False
    router = build_router(settings, mock_only=False)
    assert "deepseek" not in [p.name for p in router.worker_chain]
    assert "strategist-http" not in [p.name for p in router.strategist_chain]


def test_strategist_chain_hanya_http_dan_mock(tmp_path, monkeypatch):
    """Tier strategist tidak lagi punya jalur CLI: satu provider nyata + mock."""
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("STRATEGIST_BASE_URL", "http://localhost:20128/v1")
    monkeypatch.setenv("STRATEGIST_MODEL", "eg/elf/deepseek-v4.1-flash")
    get_settings.cache_clear()
    router = build_router(get_settings(), mock_only=False)
    assert [p.name for p in router.strategist_chain] == ["strategist-http", "mock"]


def test_temperature_provider_dipakai_sebagai_default(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "http://localhost:20128/v1")
    monkeypatch.setenv("DEEPSEEK_MODEL", "eg/elf/deepseek-v4.1-flash")
    save_studio(StudioConfig(providers=ProvidersOverride(
        worker=ProviderOverride(temperature=0.15)
    )))
    get_settings.cache_clear()
    router = build_router(get_settings(), mock_only=False)
    worker = next(p for p in router.worker_chain if p.name == "deepseek")
    assert worker.temperature == 0.15


def test_studio_rusak_jangan_bikin_settings_crash(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    (tmp_path / "studio.json").write_text("{rusak", encoding="utf-8")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://env.example.com/v1")
    get_settings.cache_clear()
    assert get_settings().deepseek.base_url == "https://env.example.com/v1"


def test_override_tidak_menyimpan_rahasia(tmp_path, monkeypatch):
    """File config tidak boleh pernah memuat kunci, walau operator mengisinya."""
    _isolate(tmp_path, monkeypatch)
    save_studio(StudioConfig(providers=ProvidersOverride(
        worker=ProviderOverride(base_url="https://example.com/v1", model="m")
    )))
    raw = (tmp_path / "studio.json").read_text(encoding="utf-8")
    assert "api_key" not in raw and "API_KEY" not in raw
