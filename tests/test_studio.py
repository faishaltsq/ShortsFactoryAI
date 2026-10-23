import json

import pytest

from packages.core.studio import (
    AgentOverride,
    BudgetOverride,
    ProductionOverride,
    RunnerOverride,
    StudioConfig,
    StudioConfigError,
    load_history,
    load_studio,
    rollback_studio,
    save_studio,
    studio_path,
)


def test_missing_file_returns_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDIO_CONFIG", str(tmp_path / "studio.json"))
    assert studio_path() == tmp_path / "studio.json"
    cfg = load_studio()
    assert cfg.agents == {}
    assert cfg.budget.max_daily_tokens is None
    assert cfg.runner.default_mode == "live"
    assert cfg.runner.default_stop == "storyboard"


def test_invalid_json_raises_studio_config_error(tmp_path):
    path = tmp_path / "studio.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(StudioConfigError):
        load_studio(path)


def test_unknown_agent_key_rejected(tmp_path):
    with pytest.raises(ValueError):
        StudioConfig.model_validate({"agents": {"TypoAgent": {"model": "x"}}})


def test_prompt_must_not_be_empty_string(tmp_path):
    with pytest.raises(ValueError):
        AgentOverride(prompt="")
    with pytest.raises(ValueError):
        AgentOverride(temperature=3.0)


def test_production_rate_and_stop_validated():
    with pytest.raises(ValueError):
        ProductionOverride(tts_rate="-10")          # harus bentuk +0%
    with pytest.raises(ValueError):
        RunnerOverride(default_stop="publish")      # bukan titik henti pipeline
    assert ProductionOverride(tts_rate="-15%").tts_rate == "-15%"


def test_save_then_load_roundtrip_and_no_tmp_left(tmp_path):
    path = tmp_path / "studio.json"
    cfg = StudioConfig(
        agents={"ScriptAgent": AgentOverride(model="tig/x", temperature=0.2, prompt="PROMPT KUSTOM")}
    )
    save_studio(cfg, path)
    assert load_studio(path) == cfg
    assert not list(tmp_path.glob("*.tmp"))
    assert json.loads(path.read_text(encoding="utf-8"))["agents"]["ScriptAgent"]["model"] == "tig/x"



def _raw(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_history_menyimpan_versi_lama_saat_isi_berubah(tmp_path):
    path = tmp_path / "studio.json"
    save_studio(StudioConfig(), path)
    save_studio(StudioConfig(budget=BudgetOverride(max_daily_tokens=1)), path)
    history = load_history(path)
    assert len(history) == 1
    assert history[0]["name"].startswith("studio-")
    snapshot = tmp_path / "studio-history" / history[0]["name"]
    assert _raw(snapshot) == {"version": 1, "agents": {}, "budget": {}, "production": {},
                              "providers": {"worker": {}, "strategist_http": {}},
                              "runner": {"default_mode": "live", "default_stop": "storyboard"},
                              "schedule": {}}
    assert _raw(path)["budget"]["max_daily_tokens"] == 1


def test_save_identik_tidak_menambah_riwayat(tmp_path):
    path = tmp_path / "studio.json"
    save_studio(StudioConfig(), path)
    save_studio(StudioConfig(), path)
    assert load_history(path) == []


def test_rollback_mengembalikan_isi(tmp_path):
    path = tmp_path / "studio.json"
    save_studio(StudioConfig(budget=BudgetOverride(max_daily_tokens=100)), path)
    save_studio(StudioConfig(budget=BudgetOverride(max_daily_tokens=999)), path)
    name = load_history(path)[0]["name"]
    rollback_studio(name, path)
    assert _raw(path)["budget"]["max_daily_tokens"] == 100


def test_rollback_nama_tidak_valid_ditolak(tmp_path):
    path = tmp_path / "studio.json"
    with pytest.raises(ValueError):
        rollback_studio("../etc/passwd", path)
    with pytest.raises(ValueError):
        rollback_studio("studio-19700101T000000Z.json", path)
