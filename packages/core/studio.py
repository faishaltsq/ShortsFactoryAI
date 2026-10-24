"""Operator-editable studio configuration (config/studio.json).

Hanya nilai non-rahasia: model/prompt/suhu per agent, budget, parameter produksi
dan default runner untuk UI web. Rahasia tetap di environment dan tidak pernah
dibaca maupun ditulis di sini.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import time
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .orchestration.states import STOP_POINTS

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STUDIO_PATH = PROJECT_ROOT / "config" / "studio.json"

AGENT_KEYS = (
    "ResearchAgent",
    "TopicSelectionAgent",
    "ScriptAgent",
    "CreativeDirectorAgent",
    "StoryboardAgent",
    "QualityAgent",
    "MetadataAgent",
)

RUNNER_STOPS = tuple(STOP_POINTS)   # single source of truth; see orchestration/states.py


class StudioConfigError(ValueError):
    """config/studio.json ada tapi tidak bisa dibaca atau divalidasi."""


class AgentOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str | None = Field(None, min_length=1)
    temperature: float | None = Field(None, ge=0.0, le=2.0)
    prompt: str | None = Field(None, min_length=1)


class BudgetOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Batas keras per hari. `unlimited=True` mematikan keduanya sekaligus supaya
    # operator tidak perlu mengarang angka besar yang seolah-olah batas nyata.
    unlimited: bool | None = None
    max_daily_tokens: int | None = Field(None, ge=0)
    max_daily_cost_usd: float | None = Field(None, ge=0)
    max_retries: int | None = Field(None, ge=0, le=10)


class ProductionOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fps: int | None = Field(None, ge=1, le=60)
    target_duration_s: int | None = Field(None, ge=10, le=90)
    videos_per_day: int | None = Field(None, ge=0, le=50)
    tts_voice: str | None = Field(None, min_length=1)
    tts_rate: str | None = Field(None, pattern=r"^[+-]\d+%$")


class RunnerOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_mode: Literal["mock", "live"] = "live"
    default_stop: str = "storyboard"

    @field_validator("default_stop")
    @classmethod
    def _stop_known(cls, value: str) -> str:
        if value not in RUNNER_STOPS:
            raise ValueError(f"default_stop must be one of {RUNNER_STOPS}")
        return value


class ProviderOverride(BaseModel):
    """Setelan provider yang boleh diedit operator lewat web.

    Tidak ada field rahasia di sini dengan sengaja: API key tetap di environment
    dan hanya dikirim ke endpoint yang cocok (lihat config._resolve_key). Yang
    bisa diubah dari UI hanya hal non-rahasia yang memang sering berganti.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    base_url: str | None = Field(None, min_length=1, max_length=500)
    model: str | None = Field(None, min_length=1, max_length=200)
    temperature: float | None = Field(None, ge=0.0, le=2.0)

    @field_validator("base_url")
    @classmethod
    def _plain_http_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parts = urlsplit(value.strip())
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError("base_url harus berbentuk http(s)://host[/path]")
        if parts.username or parts.password:
            # Kredensial di URL akan lolos ke log dan ke pesan error. Tolak.
            raise ValueError("base_url tidak boleh memuat kredensial")
        return value.strip().rstrip("/")


class ProvidersOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    worker: ProviderOverride = Field(default_factory=ProviderOverride)
    strategist_http: ProviderOverride = Field(default_factory=ProviderOverride)

    @model_validator(mode="before")
    @classmethod
    def _drop_retired_cli(cls, value):
        """Buang `strategist_cli` dari dokumen lama.

        Adapter CLI sudah dihapus, tapi snapshot riwayat dan file studio yang
        ditulis versi sebelumnya masih memuat kuncinya. Tanpa ini, `extra=forbid`
        membuat rollback ke snapshot lama gagal total — padahal justru rollback
        yang dibutuhkan saat sesuatu salah.
        """
        if isinstance(value, dict) and "strategist_cli" in value:
            value = {k: v for k, v in value.items() if k != "strategist_cli"}
        return value


class ScheduleOverride(BaseModel):
    """Produksi otomatis berulang.

    Default mati. Scheduler yang menyala sendiri akan menghabiskan kuota dan
    membuat video tanpa ada yang memutuskan — jadi operator harus menyalakannya
    secara eksplisit, dan bisa mematikannya kapan saja.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    # Interval antar-job. Harian sampai mingguan menutup kebutuhan normal;
    # nilai di luar itu ditolak supaya tidak jadi alat penguras kuota.
    interval_hours: int | None = Field(None, ge=1, le=168)
    max_per_day: int | None = Field(None, ge=0, le=24)
    # Jeda antar-job di dalam satu hari, supaya tidak menembak beruntun.
    gap_minutes: int | None = Field(None, ge=0, le=720)
    mode: Literal["mock", "live"] | None = None
    stop: str | None = None
    # Topik diputar dari daftar ini supaya tidak mengarang arah setiap kali.
    topics: list[str] | None = Field(None, max_length=200)
    # Lewati jam-jam sepi; kosong = kapan saja.
    quiet_hours: list[int] | None = Field(None, max_length=24)
    # Jam tayang tetap: job hanya dibuat pada jam-jam ini; kosong = kapan saja.
    posting_hours: list[int] | None = Field(None, max_length=24)
    # Backpressure: berhenti membuat job baru bila sudah sebanyak ini menunggu review.
    max_pending_approval: int | None = Field(None, ge=0, le=100)

    @field_validator("stop")
    @classmethod
    def _stop_known(cls, value: str | None) -> str | None:
        if value is not None and value not in RUNNER_STOPS:
            raise ValueError(f"stop must be one of {RUNNER_STOPS}")
        return value

    @field_validator("quiet_hours")
    @classmethod
    def _hours_valid(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        if any(h < 0 or h > 23 for h in value):
            raise ValueError("quiet_hours harus jam 0-23")
        return sorted(set(value))

    @field_validator("posting_hours")
    @classmethod
    def _posting_hours_valid(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        if any(h < 0 or h > 23 for h in value):
            raise ValueError("posting_hours harus jam 0-23")
        return sorted(set(value))


class StudioConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    agents: dict[str, AgentOverride] = Field(default_factory=dict)
    budget: BudgetOverride = Field(default_factory=BudgetOverride)
    production: ProductionOverride = Field(default_factory=ProductionOverride)
    providers: ProvidersOverride = Field(default_factory=ProvidersOverride)
    runner: RunnerOverride = Field(default_factory=RunnerOverride)
    schedule: ScheduleOverride = Field(default_factory=ScheduleOverride)

    @field_validator("agents")
    @classmethod
    def _known_agents(cls, value: dict[str, AgentOverride]) -> dict[str, AgentOverride]:
        unknown = sorted(set(value) - set(AGENT_KEYS))
        if unknown:
            raise ValueError(f"unknown agent keys: {unknown}; allowed: {list(AGENT_KEYS)}")
        return value

    def agent(self, name: str) -> AgentOverride:
        return self.agents.get(name, AgentOverride())

    def prompt_for(self, name: str) -> str | None:
        return self.agents[name].prompt if name in self.agents else None


def studio_path() -> Path:
    override = os.environ.get("STUDIO_CONFIG", "")
    return Path(override) if override else DEFAULT_STUDIO_PATH


def load_studio(path: Path | None = None) -> StudioConfig:
    """Baca file setiap dipanggil (tanpa cache) supaya perubahan dari API langsung terasa."""
    target = path or studio_path()
    if not target.exists():
        return StudioConfig()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StudioConfigError(f"cannot read {target}: {exc}") from exc
    try:
        return StudioConfig.model_validate(raw)
    except ValueError as exc:
        raise StudioConfigError(f"invalid studio config: {exc}") from exc


HISTORY_LIMIT = 50
_NAME_RE = re.compile(r"^studio-\d{8}T\d{6}Z\.json$")


def history_dir(path: Path | None = None) -> Path:
    return (path or studio_path()).parent / "studio-history"


def load_history(path: Path | None = None) -> list[dict[str, object]]:
    """Snapshot versi sebelumnya, terbaru dulu, dipakai tombol rollback di UI."""
    target = path or studio_path()
    directory = history_dir(target)
    if not directory.exists():
        return []
    entries: list[dict[str, object]] = []
    for item in sorted(directory.glob("studio-*.json"), reverse=True)[:HISTORY_LIMIT]:
        try:
            data = json.loads(item.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        entries.append({"name": item.name, "mtime": item.stat().st_mtime, "config": data})
    return entries


def rollback_studio(name: str, path: Path | None = None) -> StudioConfig:
    """Muat snapshot valid dari riwayat, lalu jadikan konfigurasi aktif (atomik)."""
    if not _NAME_RE.match(name):
        raise ValueError(f"invalid history name: {name!r}")
    target = path or studio_path()
    snapshot = history_dir(target) / name
    if not snapshot.exists():
        raise ValueError(f"snapshot not found: {name}")
    config = load_studio(snapshot)  # melempar StudioConfigError bila snapshot rusak
    save_studio(config, target)
    return config


def save_studio(config: StudioConfig, path: Path | None = None) -> Path:
    """Validasi model, salin versi lama ke riwayat, lalu tulis atomik."""
    target = path or studio_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = config.model_dump_json(indent=2, exclude_none=True) + "\n"
    if target.exists():
        current = target.read_text(encoding="utf-8")
        if current.strip() == payload.strip():
            return target  # tidak ada perubahan: jangan buang-buang riwayat
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        directory = history_dir(target)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"studio-{stamp}.json").write_text(current, encoding="utf-8")
        for old in sorted(directory.glob("studio-*.json"))[:-HISTORY_LIMIT]:
            old.unlink(missing_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    # Windows menahan handle baca sesaat (runner yang sedang memanggil load_studio,
    # indexer, AV), jadi replace diulang dalam jendela ~1 detik.
    for attempt in range(20):
        try:
            tmp.replace(target)
            break
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.05)
    return target
