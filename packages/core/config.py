"""Runtime configuration. Secrets come from environment / .env only."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

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


@dataclass(frozen=True)
class BudgetConfig:
    max_daily_tokens: int = field(default_factory=lambda: _int("MAX_DAILY_TOKEN_BUDGET", 400_000))
    max_daily_cost_usd: float = field(default_factory=lambda: _float("MAX_DAILY_COST_USD", 2.0))
    max_retries: int = field(default_factory=lambda: _int("MAX_RETRIES", 5))
    request_timeout_s: int = field(default_factory=lambda: _int("PROVIDER_TIMEOUT_S", 120))


def _deepseek_key() -> str:
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if key:
        return key
    base = urlsplit(os.environ.get("DEEPSEEK_BASE_URL", ""))
    if base.scheme == "http" and base.hostname == "localhost" and base.port == 20128 and not base.username and not base.password:
        # Local router shares the Hermes-managed key. Never read it anywhere else.
        return os.environ.get("HERMES_CUSTOM_LOCALHOST_20128_API_KEY", "")
    return ""


@dataclass(frozen=True)
class DeepSeekConfig:
    base_url: str = field(default_factory=lambda: os.environ.get("DEEPSEEK_BASE_URL", ""))
    api_key: str = field(default_factory=_deepseek_key, repr=False)
    model: str = field(default_factory=lambda: os.environ.get("DEEPSEEK_MODEL", ""))

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.model)


@dataclass(frozen=True)
class ClaudeCliConfig:
    binary: str = field(default_factory=lambda: os.environ.get("CLAUDE_CLI_BIN", "claude"))
    model: str = field(default_factory=lambda: os.environ.get("CLAUDE_CLI_MODEL", "opus"))
    timeout_s: int = field(default_factory=lambda: _int("CLAUDE_CLI_TIMEOUT_S", 300))


@dataclass(frozen=True)
class ProductionConfig:
    language: str = field(default_factory=lambda: os.environ.get("VIDEO_LANGUAGE", "id-ID"))
    width: int = field(default_factory=lambda: _int("VIDEO_WIDTH", 1080))
    height: int = field(default_factory=lambda: _int("VIDEO_HEIGHT", 1920))
    fps: int = field(default_factory=lambda: _int("VIDEO_FPS", 30))
    target_duration_s: int = field(default_factory=lambda: _int("VIDEO_DURATION_SEC", 40))
    videos_per_day: int = field(default_factory=lambda: _int("VIDEOS_PER_DAY", 1))
    plan_days: int = field(default_factory=lambda: _int("PLAN_DAYS", 7))
    tts_voice: str = field(default_factory=lambda: os.environ.get("TTS_VOICE", "id-ID-ArdiNeural"))
    tts_rate: str = field(default_factory=lambda: os.environ.get("TTS_RATE", "+0%"))


@dataclass(frozen=True)
class Settings:
    budget: BudgetConfig = field(default_factory=BudgetConfig)
    deepseek: DeepSeekConfig = field(default_factory=DeepSeekConfig)
    claude_cli: ClaudeCliConfig = field(default_factory=ClaudeCliConfig)
    production: ProductionConfig = field(default_factory=ProductionConfig)
    db_path: Path = field(default_factory=lambda: JOBS_DIR / "factory.db")

    def ensure_dirs(self) -> None:
        for d in (DATA_DIR, JOBS_DIR, RENDERS_DIR, ASSETS_DIR):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
