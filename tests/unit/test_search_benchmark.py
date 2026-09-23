"""scripts/search_benchmark.py is loaded by path, like tests/unit/test_benchmark.py does for the
matching benchmark: scripts/ is not a package."""
from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from movie_brain.application.embed import embed_films
from movie_brain.domain.models import CastRow, Film, TmdbCredits
from movie_brain.infrastructure.embeddings import VectorIndex

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
DAY = date(2026, 9, 23)


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def bench() -> Any:
    return _load("search_benchmark", SCRIPTS_DIR / "search_benchmark.py")


def _credits(tmdb_id, title, overview, keywords):
    return TmdbCredits(
        tmdb_id=tmdb_id, imdb_id=None, title=title, original_title=title, year=None, runtime_min=None,
        alt_titles=(), overview=overview, tagline=None, genres=("Drama",), keywords=keywords,
        cast=(CastRow(1, "Someone", "Lead", 0),), crew=(),
    )


def test_pick_keywords_is_deterministic_and_bounded(bench):
    rows = [("one", frozenset({1})), ("mid", frozenset({1, 2, 3})), ("big", frozenset(range(40)))]
    picked = bench.pick_keywords(rows, sample=5, seed=7, lo=3, hi=30)
    assert picked == [("mid", frozenset({1, 2, 3}))]           # only the in-range keyword survives
    assert bench.pick_keywords(rows, sample=5, seed=7, lo=3, hi=30) == picked  # same seed, same pick


def test_plural_adds_an_s_to_the_last_word_unless_it_already_ends_in_s(bench):
    assert bench.plural("time loop") == "time loops"
    assert bench.plural("dystopia") == "dystopias"
    assert bench.plural("robots") is None


def test_score_is_hit_and_capped_recall_at_ten(bench):
    expected = frozenset({1, 2, 3})
    assert bench.score(expected, [9, 2, 8]) == (True, pytest.approx(1 / 3))
    assert bench.score(expected, [9, 8]) == (False, 0.0)
    wide = frozenset(range(30))
    assert bench.score(wide, list(range(10))) == (True, pytest.approx(1.0))  # 10 of 30 in the top ten is a full score


def test_run_benchmark_scores_a_corpus_through_the_real_pipeline(repo, fake_embedder, bench):
    a = repo.create_film(Film("Alpha", 1946, None, ""))
    b = repo.create_film(Film("Beta", 1950, None, ""))
    repo.write_credits(a, _credits(1, "Alpha", "A private eye.", ("film noir",)), DAY)
    repo.write_credits(b, _credits(2, "Beta", "A nurse in the ward.", ("hospital",)), DAY)
    embed_films(repo, fake_embedder, DAY, apply=True, log=lambda _: None)
    index = VectorIndex(repo, fake_embedder)
    report = bench.run_benchmark(repo, index, [("film noir", frozenset({a})), ("hospital", frozenset({b})), ("nothing here", frozenset({a}))])
    assert [r.query for r in report.rows] == ["film noir", "hospital", "nothing here"]
    assert [r.hit for r in report.rows] == [True, True, False]
    assert report.hit_rate == pytest.approx(2 / 3)


def test_the_script_refuses_the_live_database(bench, tmp_path, monkeypatch):
    monkeypatch.setenv("MOVIE_BRAIN_CONFIG_DIR", str(tmp_path))
    live = tmp_path / "movie-brain.db"
    live.write_bytes(b"")
    with pytest.raises(SystemExit) as exc:
        bench.main(["--db", str(live)])
    assert "live database" in str(exc.value)
