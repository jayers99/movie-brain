from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.repair import repair_years_from_tmdb
from movie_brain.domain.models import Film, OmdbRating

scenarios("../features/repair_years_from_tmdb.feature")


@dataclass
class FakeTmdb:
    """Only the one call the backfill is allowed to make."""

    years: dict[int, int | None] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def movie_year(self, tmdb_id: int) -> int | None:
        self.calls.append(f"movie_year({tmdb_id})")
        return self.years.get(tmdb_id)


@pytest.fixture
def tmdb() -> FakeTmdb:
    return FakeTmdb()


@pytest.fixture
def films() -> dict[str, int]:
    """Title (or tracked-as label) as written in the feature file -> the film id created for it."""
    return {}


@pytest.fixture
def result() -> dict:
    return {}


# Given -----------------------------------------------------------------


@given(parsers.parse('a film "{title}" with no year, holding tmdb id {tid:d}'))
def seed_no_year_film(repo, today, films, title, tid):
    film_id = repo.create_film(Film(title, None, None, ""))
    assert film_id is not None
    repo.set_external_id(film_id, "tmdb", str(tid), today)
    films[title] = film_id


@given(parsers.parse('a film "{title}" ({year:d}) holding tmdb id {tid:d}'))
def seed_film_with_year(repo, today, films, title, year, tid):
    film_id = repo.create_film(Film(title, year, None, ""))
    assert film_id is not None
    repo.set_external_id(film_id, "tmdb", str(tid), today)
    films[title] = film_id


@given(
    parsers.parse('a film titled "{title}" with no year, holding tmdb id {tid:d}, tracked as "{key}"')
)
def seed_titled_no_year(repo, today, films, title, tid, key):
    film_id = repo.create_film(Film(title, None, None, ""))
    assert film_id is not None
    repo.set_external_id(film_id, "tmdb", str(tid), today)
    films[key] = film_id


@given(parsers.parse("TMDB reports the year {year:d} for tmdb id {tid:d}"))
def reports_year(tmdb, year, tid):
    tmdb.years[tid] = year


@given(parsers.parse("TMDB publishes no year for tmdb id {tid:d}"))
def publishes_no_year(tmdb, tid):
    tmdb.years[tid] = None


@given(parsers.parse('the film "{title}" has an OMDb miss on record'))
def has_omdb_miss(repo, today, films, title):
    repo.upsert_omdb(films[title], OmdbRating(None, None, False), today)


# When --------------------------------------------------------------------


@when("I fill years from tmdb without applying")
def run_dry_run(repo, tmdb, today, result):
    result["report"] = repair_years_from_tmdb(repo, tmdb, today, apply=False, log=lambda _m: None)


@when("I fill years from tmdb with apply")
def run_apply(repo, tmdb, today, result):
    result["report"] = repair_years_from_tmdb(repo, tmdb, today, apply=True, log=lambda _m: None)


# Then --------------------------------------------------------------------


@then(parsers.parse("the report counts {n:d} filled"))
def counts_filled(result, n):
    assert result["report"].filled == n


@then(parsers.parse("the report counts {n:d} no-year"))
def counts_no_year(result, n):
    assert result["report"].no_year == n


@then(parsers.parse("the report counts {n:d} collision"))
def counts_collision(result, n):
    assert result["report"].collision == n


@then(parsers.parse('the film "{title}" still has no year'))
def still_no_year(repo, films, title):
    view = repo.get_view(films[title])
    assert view is not None
    assert view.year is None


@then(parsers.parse('the film "{title}" now has year {year:d}'))
def now_has_year(repo, films, title, year):
    view = repo.get_view(films[title])
    assert view is not None
    assert view.year == year


@then(parsers.parse('the film "{title}" still has year {year:d}'))
def still_has_year(repo, films, title, year):
    view = repo.get_view(films[title])
    assert view is not None
    assert view.year == year


@then(parsers.parse('the film "{title}" is marked for an OMDb refresh'))
def marked_for_refresh(repo, films, title):
    assert repo.omdb_needs_refresh(films[title])


@then(parsers.parse("TMDB was never asked for the year of tmdb id {tid:d}"))
def year_never_asked(tmdb, tid):
    assert f"movie_year({tid})" not in tmdb.calls, tmdb.calls


@then(parsers.parse('an open tmdb review row exists for "{title}" with reason "{reason}"'))
def review_row_exists(repo, films, title, reason):
    film_id = films[title]
    rows = repo.open_reviews("tmdb")
    assert any(r["film_id"] == film_id and r["reason"] == reason for r in rows), rows
