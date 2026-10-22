"""Budget tanpa batas: flag di studio.json harus benar-benar mematikan guard."""
import packages.core.config as config
from packages.core.config import get_settings
from packages.core.providers import MockProvider, ProviderRouter
from packages.core.providers.router import UsageTracker
from packages.core.studio import BudgetOverride, StudioConfig, save_studio


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setenv("STUDIO_CONFIG", str(tmp_path / "studio.json"))
    # Env sengaja diisi angka kecil: kalau `unlimited` diabaikan, tes ini gagal.
    monkeypatch.setenv("MAX_DAILY_TOKEN_BUDGET", "1")
    monkeypatch.setenv("MAX_DAILY_COST_USD", "0.01")
    get_settings.cache_clear()


def test_unlimited_mematikan_kedua_batas(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    save_studio(StudioConfig(budget=BudgetOverride(unlimited=True)))
    get_settings.cache_clear()
    budget = get_settings().budget
    assert budget.max_daily_tokens is None
    assert budget.max_daily_cost_usd is None
    assert budget.unlimited is True


def test_unlimited_mengalahkan_env_bukan_sekadar_kosong(tmp_path, monkeypatch):
    """Env berisi angka, jadi None hanya mungkin kalau flag benar-benar dibaca."""
    _isolate(tmp_path, monkeypatch)
    assert get_settings().budget.max_daily_tokens == 1  # tanpa studio.json
    save_studio(StudioConfig(budget=BudgetOverride(unlimited=True)))
    get_settings.cache_clear()
    assert get_settings().budget.max_daily_tokens is None


def test_angka_nol_tetap_batas_nyata_bukan_tanpa_batas(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("MAX_DAILY_TOKEN_BUDGET", "0")
    save_studio(StudioConfig(budget=BudgetOverride(unlimited=False, max_daily_tokens=0)))
    get_settings.cache_clear()
    budget = get_settings().budget
    assert budget.max_daily_tokens == 0
    assert budget.unlimited is False


def test_router_tetap_berjalan_saat_budget_tanpa_batas(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    save_studio(StudioConfig(budget=BudgetOverride(unlimited=True)))
    get_settings.cache_clear()
    tracker = UsageTracker(tmp_path / "factory.db")
    router = ProviderRouter(worker_chain=[MockProvider()], strategist_chain=[], tracker=tracker)
    # Dua panggilan: kalau batas masih aktif (env = 1 token), yang kedua melempar.
    for _ in range(2):
        router.call(agent="a", tier="worker", task="research", system="s", user="u")
    assert tracker.daily_totals()["calls"] == 2
