import packages.core.config as config
from packages.core.config import get_settings
from packages.core.studio import BudgetOverride, ProductionOverride, StudioConfig, save_studio


def test_studio_budget_overrides_env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setenv("MAX_DAILY_TOKEN_BUDGET", "1000000")
    monkeypatch.setenv("STUDIO_CONFIG", str(tmp_path / "studio.json"))
    save_studio(StudioConfig(budget=BudgetOverride(max_daily_tokens=12345)))
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.budget.max_daily_tokens == 12345
    assert settings.budget.max_daily_cost_usd == 2.0  # tidak tersentuh


def test_env_dipakai_ketika_studio_kosong(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setenv("MAX_DAILY_TOKEN_BUDGET", "1000000")
    monkeypatch.setenv("STUDIO_CONFIG", str(tmp_path / "belum-ada.json"))
    get_settings.cache_clear()
    assert get_settings().budget.max_daily_tokens == 1000000


def test_file_rusak_jangan_crash_cli(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "JOBS_DIR", tmp_path / "jobs")
    bad = tmp_path / "studio.json"
    bad.write_text("{rusak", encoding="utf-8")
    monkeypatch.setenv("STUDIO_CONFIG", str(bad))
    monkeypatch.setenv("MAX_DAILY_TOKEN_BUDGET", "1000000")
    get_settings.cache_clear()
    assert get_settings().budget.max_daily_tokens == 1000000  # fallback, bukan traceback


def test_studio_production_override(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setenv("STUDIO_CONFIG", str(tmp_path / "studio.json"))
    save_studio(StudioConfig(production=ProductionOverride(tts_rate="-10%", fps=24, tts_voice="id-ID-GadisNeural")))
    get_settings.cache_clear()
    production = get_settings().production
    assert (production.tts_rate, production.fps, production.tts_voice) == ("-10%", 24, "id-ID-GadisNeural")
