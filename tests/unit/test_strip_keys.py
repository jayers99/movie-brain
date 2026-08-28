"""Rehearsal harness (scripts/rehearsal/strip_keys.py): strips known-good identity ids from a
stratified sample on a SCRATCH copy of the database, and scores the ingester's re-key against
what was removed. See docs/superpowers/.../task-10-brief.md for the interface contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from movie_brain.domain.models import Film


def test_strip_keys_refuses_the_live_database(tmp_path, monkeypatch):
    monkeypatch.delenv("MOVIE_BRAIN_CONFIG_DIR", raising=False)
    from scripts.rehearsal.strip_keys import guard_scratch_only

    with pytest.raises(SystemExit):
        guard_scratch_only(Path.home() / ".config" / "movie-brain" / "movie-brain.db")


def test_strip_and_compare_round_trip(repo, today, tmp_path):
    from scripts.rehearsal.strip_keys import compare, strip

    fid = repo.create_film(Film("Bound", 1996, "The Wachowskis", ""))
    repo.set_external_id(fid, "imdb", "tt0116367", today)
    repo.set_external_id(fid, "tmdb", "9081", today)
    repo.upsert_tmdb(fid, found=True, looked_up=today)
    manifest = strip(repo, count=10, manifest_path=tmp_path / "m.json")
    assert manifest[0]["imdb"] == "tt0116367"
    assert repo.external_ids_for(fid) == {}
    repo.set_external_id(fid, "imdb", "tt0116367", today)
    repo.set_external_id(fid, "tmdb", "9081", today)
    assert compare(tmp_path / "m.json", repo)["agree"] == 1
