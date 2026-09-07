from __future__ import annotations

from datetime import timedelta

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.embed import embed_films
from movie_brain.domain.models import Film, OmdbRating, TmdbCredits
from movie_brain.domain.search import EMBED_MODEL

scenarios("../features/embed.feature")


def _credits(tmdb_id: int, title: str, overview: str | None) -> TmdbCredits:
    return TmdbCredits(
        tmdb_id=tmdb_id, imdb_id=None, title=title, original_title=title, year=None, runtime_min=None,
        alt_titles=(), overview=overview, tagline=None, genres=(), keywords=(), cast=(), crew=(),
    )


@pytest.fixture
def films() -> dict[str, int]:
    return {}


@pytest.fixture
def result() -> dict:
    return {}


@given(parsers.parse('a prose film "{title}" ({year:d}) with overview "{overview}" and plot "{plot}"'))
def prose_film(repo, today, films, title, year, overview, plot):
    fid = repo.create_film(Film(title, year, None, ""))
    tmdb_id = 900 + len(films)
    repo.set_external_id(fid, "tmdb", str(tmdb_id), today)
    repo.upsert_omdb(fid, OmdbRating(7.0, 80, True, "English", f'{{"Plot": "{plot}"}}'), today)
    repo.write_credits(fid, _credits(tmdb_id, title, overview), today)
    films[title] = fid


@given(parsers.parse('a film "{title}" ({year:d}) enriched with no overview, plot or tagline'))
def bare_film(repo, today, films, title, year):
    fid = repo.create_film(Film(title, year, None, ""))
    tmdb_id = 900 + len(films)
    repo.set_external_id(fid, "tmdb", str(tmdb_id), today)
    repo.write_credits(fid, _credits(tmdb_id, title, None), today)
    films[title] = fid


@given("the corpus is already embedded")
def already(repo, today, fake_embedder):
    embed_films(repo, fake_embedder, today, apply=True)
    fake_embedder.asked.clear()


@given(parsers.parse('"{title}" is re-enriched the next day with overview "{overview}"'))
def reenriched(repo, today, films, title, overview):
    tmdb_id = int(repo.external_ids_for(films[title])["tmdb"])
    repo.write_credits(films[title], _credits(tmdb_id, title, overview), today + timedelta(days=1))


@when("I embed without applying")
def dry(repo, today, fake_embedder, result):
    result["r"] = embed_films(repo, fake_embedder, today, apply=False, log=lambda _m: None)


@when("I embed with apply")
def apply(repo, today, fake_embedder, result):
    result["r"] = embed_films(repo, fake_embedder, today + timedelta(days=1), apply=True, log=lambda _m: None)


@when(parsers.parse("I embed with apply in batches of {n:d}"))
def apply_batched(repo, today, fake_embedder, result, n):
    result["r"] = embed_films(repo, fake_embedder, today, apply=True, batch_size=n, log=lambda _m: None)


@then(parsers.parse("the embed report counts {scanned:d} scanned, {embedded:d} embedded, {skipped:d} skipped for no prose"))
def counts(result, scanned, embedded, skipped):
    r = result["r"]
    assert (r.scanned, r.embedded, r.skipped_no_prose) == (scanned, embedded, skipped), r


@then("the embedder was asked nothing")
def asked_nothing(fake_embedder):
    assert fake_embedder.asked == []


@then(parsers.parse('the embedder was asked "{a}" and "{b}"'))
def asked_two(fake_embedder, a, b):
    assert fake_embedder.asked == [a, b]


@then(parsers.parse('the embedder was asked "{a}"'))
def asked_one(fake_embedder, a):
    assert fake_embedder.asked == [a]


@then(parsers.parse("the embedder was called {n:d} times"))
def called(fake_embedder, n):
    assert fake_embedder.calls == n


@then("no film holds a vector")
def none_held(repo):
    assert repo.all_embeddings(EMBED_MODEL) == []


@then(parsers.parse("the films holding a vector are {names}"))
def held(repo, films, names):
    expected = sorted(films[n.strip()] for n in names.replace(" and ", ",").split(","))
    assert [i for i, _ in repo.all_embeddings(EMBED_MODEL)] == expected
