from packages.core.providers.base import ProviderResult
from packages.core.providers.router import ProviderRouter
from packages.core.studio import AgentOverride, StudioConfig, save_studio


class RecordingProvider:
    name = "rec"
    tier = "worker"
    model = "base-model"
    temperature = 0.7

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def healthy(self) -> bool:
        return True

    def complete(self, *, task: str, system: str, user: str) -> ProviderResult:
        self.calls.append({"system": system, "model": self.model, "temperature": self.temperature})
        return ProviderResult(content="{}", provider=self.name, model=self.model)


def _router(provider) -> ProviderRouter:
    return ProviderRouter(worker_chain=[provider], strategist_chain=[provider], allow_mock_default=False)


def test_prompt_override_dikirim_ke_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDIO_CONFIG", str(tmp_path / "studio.json"))
    save_studio(StudioConfig(agents={"ScriptAgent": AgentOverride(prompt="PROMPT KUSTOM")}))
    provider = RecordingProvider()
    _router(provider).call(agent="ScriptAgent", tier="worker", task="script", system="PROMPT ASLI", user="u")
    assert provider.calls[0]["system"] == "PROMPT KUSTOM"


def test_tanpa_override_prompt_asli_dipakai(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDIO_CONFIG", str(tmp_path / "studio.json"))
    provider = RecordingProvider()
    _router(provider).call(agent="ScriptAgent", tier="worker", task="script", system="PROMPT ASLI", user="u")
    assert provider.calls[0]["system"] == "PROMPT ASLI"


def test_model_dan_temperature_override_pakai_salinan(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDIO_CONFIG", str(tmp_path / "studio.json"))
    save_studio(StudioConfig(agents={"ResearchAgent": AgentOverride(model="tig/gemini-3-flash", temperature=0.1)}))
    provider = RecordingProvider()
    _router(provider).call(agent="ResearchAgent", tier="worker", task="research", system="s", user="u")
    assert provider.calls[0] == {"system": "s", "model": "tig/gemini-3-flash", "temperature": 0.1}
    assert provider.model == "base-model"        # instance asli tidak berubah
    assert provider.temperature == 0.7           # tidak bocor ke agent lain


def test_override_hanya_berlaku_untuk_agent_bersangkutan(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDIO_CONFIG", str(tmp_path / "studio.json"))
    save_studio(StudioConfig(agents={"ResearchAgent": AgentOverride(model="tig/other")}))
    provider = RecordingProvider()
    _router(provider).call(agent="QualityAgent", tier="worker", task="quality", system="s", user="u")
    assert provider.calls[0]["model"] == "base-model"
