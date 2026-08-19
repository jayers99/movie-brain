from datetime import date
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MOVIE_BRAIN_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.delenv("OMDB_API_KEY", raising=False)


@pytest.fixture
def config_dir(tmp_path) -> Path:
    d = tmp_path / "cfg"
    d.mkdir(exist_ok=True)
    return d


@pytest.fixture
def today() -> date:
    return date(2026, 8, 19)
