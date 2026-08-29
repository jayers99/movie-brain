from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field

import pytest
from movie_brain.application.backfill_imdb import backfill_imdb
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.domain.models import Film, OmdbRating

scenarios("../features/backfill_imdb.feature")


@dataclass
class FakeTmdb:
    """Only the two calls the backfill is allowed to make."""

    imdb_ids: dict[int, str | None] = field(default_factory=dict)
    years: dict[int, int] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def imdb_id(self, tmdb_id: int) -> str | None:
        self.calls.append(f"imdb_id({tmdb_id})")
        return self.imdb_ids.get(tmdb_id)

    def movie_year(self, tmdb_id: int) -> int | None:
        self.calls.append(f"movie_year({tmdb_id})")
        return self.years.get(tmdb_id)


@pytest.fixture
def tmdb() -> FakeTmdb:
    return FakeTmdb()


@pytest.fixture
def films() -> dict[str, int]:
    """Title as written in the feature file -> the film id created for it."""
    return {}


@pytest.fixture
def result() -> dict:
    return {}


def _film_year(repo, film_id: int) -> int | None:
    conn = sqlite3.connect(repo.db_path)
    try:
        row = conn.execute("SELECT year FROM films WHERE id = ?", (film_id,)).fetchone()
    finally:
        conn.close()
    assert row is not None, f"no film row for id {film_id}"
    return row[0]


# Given ---------------------------------------------------------------------


@given(parsers.parse('a film "{title}" ({year:d}) holding tmdb id {tid:d} and no imdb id'))
def seed_film(repo, today, films, title, year, tid):
    film_id = repo.create_film(Film(title, year, None, ""))
    assert film_id is not None
    repo.set_external_id(film_id, "tmdb", str(tid), today)
    films[title] = film_id


@given(parsers.parse('TMDB publishes imdb id "{tt}" for tmdb id {tid:d}'))
def publishes_imdb(tmdb, tt, tid):
    tmdb.imdb_ids[tid] = tt


@given(parsers.parse("TMDB publishes no imdb id for tmdb id {tid:d}"))
def publishes_no_imdb(tmdb, tid):
    tmdb.imdb_ids[tid] = None


@given(parsers.parse('the film "{title}" has no criterion listing'))
def no_criterion_listing(repo, films, title):
    film_id = films[title]
    current_ids = {fid for fid, _ in repo.current_films("criterion")}
    assert film_id not in current_ids


@given(parsers.parse("TMDB reports the year {year:d} for tmdb id {tid:d}"))
def reports_year(tmdb, year, tid):
    tmdb.years[tid] = year


@given(parsers.parse('a film "{title}" already holds imdb id "{tt}"'))
def already_holds_imdb(repo, today, films, title, tt):
    # Deliberately a distinct film from the Background's "Rio Bravo" — its title
    # is the literal string "Rio Bravo (1959)", which keys differently, so this
    # is a genuine second film already claiming the id, not a duplicate write.
    film_id = repo.create_film(Film(title, None, None, ""))
    assert film_id is not None
    repo.set_external_id(film_id, "imdb", tt, today)
    films[title] = film_id


@given(parsers.parse('the film "{title}" has an OMDb record under imdb id "{tt}"'))
def has_omdb_record_under(repo, today, films, title, tt):
    # A stale OMDb payload fetched under a DIFFERENT imdb id than the one the
    # backfill is about to write — the real-world case key_film's own
    # omdb_imdb_id(film_id) != tt comparison exists for. Mirrors the pattern
    # in tests/step_defs/test_repair.py's omdb_payload_for step.
    film_id = films[title]
    repo.upsert_omdb(film_id, OmdbRating(6.0, 50, True, "English", json.dumps({"imdbID": tt})), today)


# When ------------------------------------------------------------------


@when("I back fill imdb ids without applying")
def run_dry_run(repo, tmdb, today, result):
    result["report"] = backfill_imdb(repo, tmdb, today, apply=False, log=lambda _m: None)


@when("I back fill imdb ids with apply")
def run_apply(repo, tmdb, today, result):
    result["report"] = backfill_imdb(repo, tmdb, today, apply=True, log=lambda _m: None)


# Then --------------------------------------------------------------------


@then(parsers.parse("the report counts {scanned:d} scanned and {backfilled:d} backfilled"))
def counts_scanned_backfilled(result, scanned, backfilled):
    report = result["report"]
    assert report.scanned == scanned
    assert report.backfilled == backfilled


@then(parsers.parse("the report counts {n:d} held"))
def counts_held(result, n):
    assert result["report"].held == n


@then(parsers.parse("the report counts {n:d} no-imdb"))
def counts_no_imdb(result, n):
    assert result["report"].no_imdb == n


@then(parsers.parse('the film "{title}" still holds no imdb id'))
def still_no_imdb(repo, films, title):
    film_id = films[title]
    assert "imdb" not in repo.external_ids_for(film_id)


@then(parsers.parse('the film "{title}" holds imdb id "{tt}"'))
def holds_imdb(repo, films, title, tt):
    film_id = films[title]
    assert repo.external_ids_for(film_id).get("imdb") == tt


@then(parsers.parse('the film "{title}" still holds tmdb id {tid:d}'))
def still_holds_tmdb(repo, films, title, tid):
    film_id = films[title]
    assert repo.external_ids_for(film_id).get("tmdb") == str(tid)


@then(parsers.parse('the film "{title}" still has year {year:d}'))
def still_has_year(repo, films, title, year):
    film_id = films[title]
    assert _film_year(repo, film_id) == year


@then(parsers.parse("TMDB was never asked for the year of tmdb id {tid:d}"))
def year_never_asked(tmdb, tid):
    assert f"movie_year({tid})" not in tmdb.calls, tmdb.calls


@then(parsers.parse('an open tmdb review row exists for "{title}" with reason "{reason}"'))
def review_row_exists(repo, films, title, reason):
    film_id = films[title]
    rows = repo.open_reviews("tmdb")
    assert any(r["film_id"] == film_id and r["reason"] == reason for r in rows), rows


@then(parsers.parse('the film "{title}" is marked for an OMDb refresh'))
def marked_for_refresh(repo, films, title):
    film_id = films[title]
    assert repo.omdb_needs_refresh(film_id)
