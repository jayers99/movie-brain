from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

import pytest
import requests
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.enrich import enrich_credits
from movie_brain.domain.models import CastRow, Film, TmdbCredits

scenarios("../features/enrich.feature")


def _credits(tmdb_id: int, title: str, cast: tuple[CastRow, ...]) -> TmdbCredits:
    return TmdbCredits(
        tmdb_id=tmdb_id, imdb_id=None, title=title, original_title=title, year=None, runtime_min=None,
        alt_titles=(), overview=None, tagline=None, genres=(), keywords=(), cast=cast, crew=(),
    )


@dataclass
class FakeTmdb:
    """Only the one call the verb may make."""

    credits: dict[int, TmdbCredits] = field(default_factory=dict)
    failing: set[int] = field(default_factory=set)
    asked: list[int] = field(default_factory=list)

    def movie_credits(self, tmdb_id: int) -> TmdbCredits:
        self.asked.append(tmdb_id)
        if tmdb_id in self.failing:
            raise requests.ConnectionError("tmdb down")
        return self.credits[tmdb_id]


@pytest.fixture
def tmdb() -> FakeTmdb:
    return FakeTmdb()


@pytest.fixture
def films() -> dict[str, int]:
    return {}


@pytest.fixture
def result() -> dict:
    return {}


@pytest.fixture
def pauses() -> list[float]:
    return []


# Given ---------------------------------------------------------------------


@given(parsers.parse('a film "{title}" ({year:d}) holding tmdb id {tid:d}'))
def seed_film(repo, today, films, title, year, tid):
    film_id = repo.create_film(Film(title, year, None, ""))
    assert film_id is not None
    repo.set_external_id(film_id, "tmdb", str(tid), today)
    films[title] = film_id


@given(parsers.parse('a film "{title}" ({year:d}) holding no tmdb id'))
def seed_orphan(repo, films, title, year):
    film_id = repo.create_film(Film(title, year, None, ""))
    assert film_id is not None
    films[title] = film_id


@given(parsers.parse('TMDB publishes credits for tmdb id {tid:d} with cast "{name}" as "{character}"'))
def publishes_credits(tmdb, tid, name, character):
    tmdb.credits[tid] = _credits(tid, "The Big Sleep", (CastRow(4110, name, character, 0),))


@given(parsers.parse('the film "{title}" is already enriched'))
def already_enriched(repo, today, tmdb, films, title):
    repo.write_credits(films[title], tmdb.credits[910], today)


@given(parsers.parse("{n:d} more films holding tmdb ids that TMDB cannot serve"))
def failing_films(repo, today, tmdb, films, n):
    for i in range(n):
        tid = 9000 + i
        film_id = repo.create_film(Film(f"Broken {i}", 1960 + i, None, ""))
        assert film_id is not None
        repo.set_external_id(film_id, "tmdb", str(tid), today)
        tmdb.failing.add(tid)
        films[f"Broken {i}"] = film_id


@given(parsers.parse("{n:d} more films holding tmdb ids with empty credits"))
def empty_films(repo, today, tmdb, films, n):
    for i in range(n):
        tid = 8000 + i
        film_id = repo.create_film(Film(f"Empty {i}", 1970 + i, None, ""))
        assert film_id is not None
        repo.set_external_id(film_id, "tmdb", str(tid), today)
        tmdb.credits[tid] = _credits(tid, f"Empty {i}", ())
        films[f"Empty {i}"] = film_id


# When ----------------------------------------------------------------------


@when("I enrich credits without applying")
def run_dry(repo, tmdb, today, result, pauses):
    result["report"] = enrich_credits(repo, tmdb, today, apply=False, sleep=pauses.append, log=lambda _m: None)


@when("I enrich credits with apply")
def run_apply(repo, tmdb, today, result, pauses):
    result["report"] = enrich_credits(repo, tmdb, today, apply=True, sleep=pauses.append, log=lambda _m: None)


# Then ----------------------------------------------------------------------


@then(parsers.parse("the report counts {scanned:d} scanned and {enriched:d} enriched"))
def counts(result, scanned, enriched):
    assert (result["report"].scanned, result["report"].enriched) == (scanned, enriched)


@then("the report is marked aborted")
def aborted(result):
    assert result["report"].aborted is True


@then(parsers.parse('the film "{title}" still has no credits'))
def no_credits(repo, films, title):
    assert repo.credits_for(films[title]) == []


@then(parsers.parse('the film "{title}" credits "{name}" as "{character}"'))
def has_credit(repo, films, title, name, character):
    assert ("cast", name, character, "") in repo.credits_for(films[title])


@then(parsers.parse('the film "{title}" is stamped as enriched'))
def stamped(repo, films, title):
    with sqlite3.connect(repo.db_path) as c:
        row = c.execute("SELECT credits_fetched_on FROM tmdb_facts WHERE film_id = ?", (films[title],)).fetchone()
    assert row is not None and row[0] is not None


@then(parsers.parse("TMDB was never asked for credits of tmdb id {tid:d}"))
def never_asked(tmdb, tid):
    assert tid not in tmdb.asked


@then(parsers.parse("TMDB was paced with {n:d} pauses"))
def paced(pauses, n):
    assert len(pauses) == n
