from __future__ import annotations

from datetime import date

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.search import run_search
from movie_brain.domain.models import CastRow, CrewRow, Film, OmdbRating, TmdbCredits

scenarios("../features/search.feature")

DAY = date(2026, 9, 6)


def _credits(tmdb_id, title, overview, keywords, cast, crew, genres=("Mystery",)):
    return TmdbCredits(
        tmdb_id=tmdb_id, imdb_id=None, title=title, original_title=title, year=None, runtime_min=None,
        alt_titles=(), overview=overview, tagline=None, genres=genres, keywords=keywords, cast=cast, crew=crew,
    )


@pytest.fixture
def films() -> dict[str, int]:
    return {}


@pytest.fixture
def result() -> dict:
    return {}


@given("the search corpus of Alpha, Beta and Gamma")
def corpus(repo, films):
    a = repo.create_film(Film("Alpha", 1946, None, ""))
    b = repo.create_film(Film("Beta", 1950, None, ""))
    g = repo.create_film(Film("Gamma", 1960, None, ""))
    repo.set_external_id(a, "tmdb", "910", DAY)
    repo.set_external_id(b, "tmdb", "911", DAY)
    repo.upsert_omdb(a, OmdbRating(8.0, 97, True, "English", '{"Genre": "Crime, Film-Noir", "Plot": "Sternwood."}'), DAY)
    repo.write_credits(a, _credits(910, "Alpha", "A private eye.", ("film noir",),
                                   (CastRow(4110, "Humphrey Bogart", "Philip Marlowe", 0),),
                                   (CrewRow(2636, "Howard Hawks", "Director", "Directing"),)), DAY)
    repo.write_credits(b, _credits(911, "Beta", "A nurse in the alpha ward.", ("hospital",),
                                   (CastRow(77, "Jane Bogart", "Nurse", 0),),
                                   (CrewRow(2636, "Howard Hawks", "Director", "Directing"),)), DAY)
    films.update(Alpha=a, Beta=b, Gamma=g)


@given("a catalogue with no credits at all")
def no_credits(repo, films):
    import sqlite3

    with sqlite3.connect(repo.db_path) as c:
        c.execute("DELETE FROM film_credit")
        c.execute("DELETE FROM person")
        c.execute("UPDATE tmdb_facts SET credits_fetched_on = NULL")


@when(parsers.parse('I search for "{text}"'))
def search(repo, result, text):
    result["r"] = run_search(repo, text.replace('\\"', '"'))


@then(parsers.parse("the result ids are {names}"))
def ids_are(result, films, names):
    expected = [films[n.strip()] for n in names.replace(" then ", ",").split(",")]
    assert list(result["r"].ids) == expected


@then("the result is empty")
def empty(result):
    assert result["r"].ids == ()


@then("the result is ranked")
def ranked(result):
    assert result["r"].ranked is True


@then("the result is not ranked")
def not_ranked(result):
    assert result["r"].ranked is False


@then("there are no corrections")
def no_corrections(result):
    assert result["r"].corrections == ()


@then("there are no suggestions")
def no_suggestions(result):
    assert result["r"].suggestions == ()


@then(parsers.parse('the correction for "{field}" reads {typed} → {used}'))
def correction(result, field, typed, used):
    assert {"field": field, "typed": typed, "used": used} in result["r"].corrections


@then(parsers.parse('the suggestions for "{field}" include {name}'))
def suggestion(result, field, name):
    assert any(s["field"] == field and name in s["options"] for s in result["r"].suggestions), result["r"].suggestions


@then(parsers.parse('the hints include "{hint}"'))
def hint(result, hint):
    assert hint in result["r"].hints, result["r"].hints
