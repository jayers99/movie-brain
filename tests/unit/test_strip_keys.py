"""Rehearsal harness (scripts/rehearsal/strip_keys.py): strips known-good identity ids from a
stratified sample on a SCRATCH copy of the database, and scores the ingester's re-key against
what was removed. See .superpowers/sdd/2026-08-28-thumbprint-t5-ingesters/task-10-brief.md for
the interface contract.

Loaded via importlib.util.spec_from_file_location since scripts/ is not a package — same
pattern as tests/unit/test_benchmark.py (scripts/matching_benchmark.py).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

from movie_brain.domain.models import Film

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
LIVE_CONFIG_DIR = Path.home() / ".config" / "movie-brain"


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def strip_keys() -> Any:
    return _load("strip_keys", SCRIPTS_DIR / "rehearsal" / "strip_keys.py")


def test_strip_keys_refuses_the_live_database(strip_keys, tmp_path, monkeypatch):
    monkeypatch.delenv("MOVIE_BRAIN_CONFIG_DIR", raising=False)

    with pytest.raises(SystemExit):
        strip_keys.guard_scratch_only(LIVE_CONFIG_DIR / "movie-brain.db")


def test_guard_refuses_when_config_dir_points_at_the_live_directory(strip_keys, monkeypatch):
    # The likeliest real operator mistake: MOVIE_BRAIN_CONFIG_DIR IS set, but set to the
    # live directory itself — not unset, not a scratch dir. No filesystem writes happen here;
    # guard_scratch_only only reads the env var and resolves paths.
    monkeypatch.setenv("MOVIE_BRAIN_CONFIG_DIR", str(LIVE_CONFIG_DIR))

    with pytest.raises(SystemExit):
        strip_keys.guard_scratch_only(LIVE_CONFIG_DIR / "movie-brain.db")


def test_strip_and_compare_round_trip(strip_keys, repo, today, tmp_path):
    fid = repo.create_film(Film("Bound", 1996, "The Wachowskis", ""))
    repo.set_external_id(fid, "imdb", "tt0116367", today)
    repo.set_external_id(fid, "tmdb", "9081", today)
    repo.upsert_tmdb(fid, found=True, looked_up=today)
    manifest = strip_keys.strip(repo, count=10, manifest_path=tmp_path / "m.json")
    assert manifest[0]["imdb"] == "tt0116367"
    assert repo.external_ids_for(fid) == {}
    repo.set_external_id(fid, "imdb", "tt0116367", today)
    repo.set_external_id(fid, "tmdb", "9081", today)
    assert strip_keys.compare(tmp_path / "m.json", repo)["agree"] == 1
