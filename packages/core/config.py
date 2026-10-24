"""Runtime configuration. Secrets come from environment / .env only."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from .studio import StudioConfig, StudioConfigError, load_studio

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # .../ShortsFactoryAI
DATA_DIR = PROJECT_ROOT / "data"
JOBS_DIR = DATA_DIR / "jobs"
RENDERS_DIR = DATA_DIR / "renders"
ASSETS_DIR = DATA_DIR / "assets"


def _load_dotenv(path: Path) -> None:
    """Minimal .env reader. No third-party dependency, never overrides real env."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


_load_dotenv(PROJECT_ROOT / ".env")


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default



def _studio() -> StudioConfig | None:
    try:
        return load_studio()
    except StudioConfigError:
        # File rusak tidak boleh membuat CLI crash; API yang menampilkannya.
        return None


def _sget(section: str, key: str, fallback):
    """studio.json > env > default bawaan. Rahasia tidak pernah lewat sini."""
    cfg = _studio()
    if cfg is None:
        return fallback
    value = getattr(getattr(cfg, section), key)
    return fallback if value is None else value


def _budget_limit(section: str, key: str, env_fallback):
    """Batas harian, dengan `unlimited: true` di studio.json mematikan batas itu.

    Mengembalikan None berarti tanpa batas. Flag dibaca lebih dulu supaya angka
    env tidak diam-diam tetap berlaku saat operator sudah memilih tanpa batas.
    """
    cfg = _studio()
    if cfg is not None and getattr(cfg.budget, "unlimited", None) is True:
        return None
    return _sget(section, key, env_fallback)


@dataclass(frozen=True)
class BudgetConfig:
    # None berarti tanpa batas: _check_budget melewati pemeriksaan itu.
    max_daily_tokens: int | None = field(default_factory=lambda: _budget_limit("budget", "max_daily_tokens", _int("MAX_DAILY_TOKEN_BUDGET", 400_000)))
    max_daily_cost_usd: float | None = field(default_factory=lambda: _budget_limit("budget", "max_daily_cost_usd", _float("MAX_DAILY_COST_USD", 2.0)))
    max_retries: int = field(default_factory=lambda: int(_sget("budget", "max_retries", _int("MAX_RETRIES", 5))))
    request_timeout_s: int = field(default_factory=lambda: _int("PROVIDER_TIMEOUT_S", 120))

    @property
    def unlimited(self) -> bool:
        return self.max_daily_tokens is None and self.max_daily_cost_usd is None


def _read_env_value(path: Path, name: str) -> str:
    """Baca satu nilai dari file .env tanpa menyentuh os.environ."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    return ""


def _is_local_router(parts) -> bool:
    """Router LLM lokal: http://localhost:20128, tanpa kredensial di URL."""
    return (
        parts.scheme == "http"
        and parts.hostname == "localhost"
        and parts.port == 20128
        and not parts.username
        and not parts.password
    )


def _hermes_router_key() -> str:
    """Kunci router lokal milik Hermes.

    `HERMES_CUSTOM_LOCALHOST_20128_API_KEY` hanya ada di environment sesi
    Hermes. Proses yang dijalankan operator sendiri (scripts/run_studio_api.py
    lewat start-all-servers.bat) tidak mewarisinya, jadi kunci kosong dan setiap
    panggilan berakhir 401 — sementara katalog model tetap terbaca karena
    /models tidak butuh auth. Karena itu env dibaca lebih dulu, lalu file .env
    Hermes dibaca langsung sebagai fallback.

    Hanya dipakai untuk origin router lokal yang persis (lihat _key_status),
    sehingga kunci ini tidak pernah ikut ke host lain.
    """
    key = os.environ.get("HERMES_CUSTOM_LOCALHOST_20128_API_KEY", "")
    if key:
        return key
    candidates: list[Path] = []
    explicit = os.environ.get("HERMES_ENV_FILE", "")
    if explicit:
        candidates.append(Path(explicit))
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    if local_appdata:
        candidates.append(Path(local_appdata) / "hermes" / ".env")
    candidates.append(Path.home() / ".hermes" / ".env")
    for candidate in candidates:
        value = _read_env_value(candidate, "HERMES_CUSTOM_LOCALHOST_20128_API_KEY")
        if value:
            return value
    return ""


def _prov(section: str, key: str, fallback):
    """Override provider dari studio.json, kalau ada. Non-rahasia saja."""
    cfg = _studio()
    if cfg is None:
        return fallback
    group = getattr(cfg.providers, section, None)
    if group is None:
        return fallback
    value = getattr(group, key, None)
    return fallback if value is None else value


def _key_status(env_prefix: str, base_url: str) -> tuple[str, bool]:
    """(api_key, origin_mismatch) untuk sebuah base_url.

    Kunci dari env hanya dipakai kalau host tujuannya masih sama dengan host yang
    terdaftar di env. Tanpa ini, siapa pun yang bisa menekan Simpan di UI bisa
    mengarahkan base_url ke host lain dan membuat kunci asli ikut terkirim.

    Mismatch dikembalikan terpisah, bukan sekadar menghasilkan kunci kosong:
    kunci kosong yang senyap membuat provider tampak sehat (katalog model tidak
    butuh auth) lalu gagal 401 saat benar-benar dipanggil.
    """
    if not base_url:
        return "", False
    explicit = os.environ.get(f"{env_prefix}_API_KEY", "")
    configured = os.environ.get(f"{env_prefix}_BASE_URL", "")
    if configured:
        target, origin = urlsplit(base_url), urlsplit(configured)
        if (target.scheme, target.hostname, target.port) != (origin.scheme, origin.hostname, origin.port):
            return "", True
    if explicit:
        return explicit, False
    # Router lokal memakai kunci milik Hermes. Hanya untuk origin yang persis itu.
    target = urlsplit(base_url)
    if _is_local_router(target):
        return _hermes_router_key(), False
    return "", False


def _key_for(env_prefix: str, base_url: str) -> str:
    return _key_status(env_prefix, base_url)[0]


def _key_mismatch(env_prefix: str, base_url: str) -> bool:
    return _key_status(env_prefix, base_url)[1]


def _deepseek_key() -> str:
    return _key_for("DEEPSEEK", os.environ.get("DEEPSEEK_BASE_URL", ""))


def _strategist_key() -> str:
    return _key_for("STRATEGIST", os.environ.get("STRATEGIST_BASE_URL", ""))


@dataclass(frozen=True)
class DeepSeekConfig:
    base_url: str = field(default_factory=lambda: _prov("worker", "base_url", os.environ.get("DEEPSEEK_BASE_URL", "")))
    api_key: str = field(default_factory=lambda: _key_for("DEEPSEEK", _prov("worker", "base_url", os.environ.get("DEEPSEEK_BASE_URL", ""))), repr=False)
    model: str = field(default_factory=lambda: _prov("worker", "model", os.environ.get("DEEPSEEK_MODEL", "")))
    enabled: bool = field(default_factory=lambda: bool(_prov("worker", "enabled", True)))
    key_origin_mismatch: bool = field(
        default_factory=lambda: _key_mismatch("DEEPSEEK", _prov("worker", "base_url", os.environ.get("DEEPSEEK_BASE_URL", "")))
    )

    @property
    def configured(self) -> bool:
        return bool(self.enabled and self.base_url and self.model)


@dataclass(frozen=True)
class StrategistConfig:
    """Provider strategist lewat endpoint OpenAI-compatible.

    Satu-satunya jalur untuk tier strategist. Dulu ada adapter CLI sebagai jalur
    utama, tapi CLI hanya melaporkan sehat saat binary-nya jalan, bukan saat
    model di baliknya hidup: model mati tetap tampil hijau lalu gagal setiap
    panggilan. Endpoint HTTP memberi satu titik kegagalan yang bisa dilihat dan
    diganti operator sendiri dari web.
    """

    base_url: str = field(default_factory=lambda: _prov("strategist_http", "base_url", os.environ.get("STRATEGIST_BASE_URL", "")))
    api_key: str = field(default_factory=lambda: _key_for("STRATEGIST", _prov("strategist_http", "base_url", os.environ.get("STRATEGIST_BASE_URL", ""))), repr=False)
    model: str = field(default_factory=lambda: _prov("strategist_http", "model", os.environ.get("STRATEGIST_MODEL", "")))
    enabled: bool = field(default_factory=lambda: bool(_prov("strategist_http", "enabled", True)))
    key_origin_mismatch: bool = field(
        default_factory=lambda: _key_mismatch("STRATEGIST", _prov("strategist_http", "base_url", os.environ.get("STRATEGIST_BASE_URL", "")))
    )

    @property
    def configured(self) -> bool:
        return bool(self.enabled and self.base_url and self.model)


@dataclass(frozen=True)
class ProductionConfig:
    language: str = field(default_factory=lambda: os.environ.get("VIDEO_LANGUAGE", "id-ID"))
    width: int = field(default_factory=lambda: _int("VIDEO_WIDTH", 1080))
    height: int = field(default_factory=lambda: _int("VIDEO_HEIGHT", 1920))
    fps: int = field(default_factory=lambda: int(_sget("production", "fps", _int("VIDEO_FPS", 30))))
    target_duration_s: int = field(default_factory=lambda: int(_sget("production", "target_duration_s", _int("VIDEO_DURATION_SEC", 40))))
    videos_per_day: int = field(default_factory=lambda: int(_sget("production", "videos_per_day", _int("VIDEOS_PER_DAY", 1))))
    plan_days: int = field(default_factory=lambda: _int("PLAN_DAYS", 7))
    tts_voice: str = field(default_factory=lambda: str(_sget("production", "tts_voice", os.environ.get("TTS_VOICE", "id-ID-ArdiNeural"))))
    tts_rate: str = field(default_factory=lambda: str(_sget("production", "tts_rate", os.environ.get("TTS_RATE", "+0%"))))


@dataclass(frozen=True)
class Settings:
    budget: BudgetConfig = field(default_factory=BudgetConfig)
    deepseek: DeepSeekConfig = field(default_factory=DeepSeekConfig)
    strategist: StrategistConfig = field(default_factory=StrategistConfig)
    production: ProductionConfig = field(default_factory=ProductionConfig)
    db_path: Path = field(default_factory=lambda: JOBS_DIR / "factory.db")
    #: Bounded content revision budget per job; exhaustion blocks the job for an operator decision.
    max_repairs: int = field(default_factory=lambda: max(1, min(5, _int("MAX_REPAIRS", 2))))
    #: Hard cap on failed runs before the job is blocked instead of retried.
    max_job_attempts: int = field(default_factory=lambda: max(1, _int("MAX_JOB_ATTEMPTS", 3)))

    def ensure_dirs(self) -> None:
        for d in (DATA_DIR, JOBS_DIR, RENDERS_DIR, ASSETS_DIR):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
