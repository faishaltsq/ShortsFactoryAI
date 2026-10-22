import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from packages.core.config import get_settings  # noqa: E402
import packages.core.config as config  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
    data = tmp_path / "data"
    for name, value in {
        "DATA_DIR": data, "JOBS_DIR": data / "jobs",
        "RENDERS_DIR": data / "renders", "ASSETS_DIR": data / "assets",
    }.items():
        monkeypatch.setattr(config, name, value)
    # Tanpa ini, suite membaca config/studio.json milik operator dan hasilnya
    # berubah setiap kali operator mengubah setelan nyata (mis. budget unlimited).
    monkeypatch.setenv("STUDIO_CONFIG", str(tmp_path / "studio.json"))
    monkeypatch.setenv("MAX_DAILY_TOKEN_BUDGET", "1000000")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def tmp_env(tmp_path, monkeypatch):
    """Isolated DB + artifact dirs so tests never touch data/jobs."""
    db = tmp_path / "factory.db"
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    monkeypatch.setenv("MAX_DAILY_TOKEN_BUDGET", "1000000")
    get_settings.cache_clear()
    yield {"db": db, "jobs": jobs}
    get_settings.cache_clear()


@pytest.fixture()
def sample_storyboard():
    path = ROOT / "packages" / "video" / "src" / "sample" / "storyboard.ts"
    return path
