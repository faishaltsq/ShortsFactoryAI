import pytest
import httpx

from packages.core.providers.base import ProviderError
from packages.core.providers.openai_compat import OpenAICompatProvider


def _provider():
    return OpenAICompatProvider(name="test", base_url="https://test.invalid/v1", api_key="unit-test-credential", model="test-model", max_retries=1)


def test_http_errors_do_not_echo_untrusted_provider_body(monkeypatch):
    import packages.core.providers.openai_compat as adapter

    body = "upstream reflected token: unit-test-credential"
    monkeypatch.setattr(adapter.httpx, "post", lambda *a, **kw: httpx.Response(401, text=body))
    with pytest.raises(ProviderError) as caught:
        _provider().complete(task="script", system="s", user="u")
    assert "unit-test-credential" not in str(caught.value)
    assert "401" in str(caught.value)


def test_local_router_key_is_never_forwarded_to_lookalike_origin(monkeypatch):
    from packages.core.config import _deepseek_key
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.setenv("HERMES_CUSTOM_LOCALHOST_20128_API_KEY", "unit-test-credential")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "http://localhost:20128@attacker.invalid/v1")
    assert _deepseek_key() == ""


def test_health_rejects_unauthorized_endpoint(monkeypatch):
    import packages.core.providers.openai_compat as adapter

    monkeypatch.setattr(adapter.httpx, "get", lambda *a, **kw: httpx.Response(401))
    assert _provider().healthy() is False


def test_health_requires_configured_model_in_catalog(monkeypatch):
    import packages.core.providers.openai_compat as adapter

    monkeypatch.setattr(adapter.httpx, "get", lambda *a, **kw: httpx.Response(200, json={"data": [{"id": "other-model"}]}))
    assert _provider().healthy() is False


def test_pesan_error_menyebut_apakah_kunci_terkirim(monkeypatch):
    """401 harus bisa dibedakan: kunci salah vs kunci tidak terkirim.

    Kasus nyata: base_url sudah benar, model sudah benar, tapi kunci kosong
    karena env tidak diwariskan. Pesan lama hanya "HTTP 401 from deepseek"
    sehingga tidak ada petunjuk ke arah mana pun.
    """
    import packages.core.providers.openai_compat as adapter

    monkeypatch.setattr(adapter.httpx, "post", lambda *a, **kw: httpx.Response(401))
    without_key = OpenAICompatProvider(
        name="worker-http", base_url="http://localhost:20128/v1",
        api_key="", model="m", max_retries=1,
    )
    with pytest.raises(ProviderError) as caught:
        without_key.complete(task="script", system="s", user="u")
    assert "tanpa api key" in str(caught.value)
    assert "localhost:20128" in str(caught.value)

    with_key = OpenAICompatProvider(
        name="worker-http", base_url="http://localhost:20128/v1",
        api_key="unit-test-credential", model="m", max_retries=1,
    )
    with pytest.raises(ProviderError) as caught2:
        with_key.complete(task="script", system="s", user="u")
    assert "api key terkirim" in str(caught2.value)
    # Kunci tetap tidak boleh ikut tercetak.
    assert "unit-test-credential" not in str(caught2.value)
