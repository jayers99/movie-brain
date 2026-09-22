"""`films add`: the hand path for one film named by its IMDb id. Assertions read the DATABASE."""

from __future__ import annotations

import sqlite3
from datetime import date

import pytest
from lists_fakes import StubTmdb
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.films import AddError, add_by_id
from movie_brain.domain.models import Film
from movie_brain.infrastructure.tmdb import TmdbFacts

scenarios("../features/films.feature")

TODAY = date(2026, 9, 22)


@pytest.fixture
def ctx(repo):
    return {"repo": repo, "tmdb": StubTmdb(), "log": [], "seeded": 0}


def _q(ctx, sql, *args):
    conn = sqlite3.connect(ctx["repo"].db_path)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def _film(ctx, title, year, tt=None):
    fid = ctx["repo"].create_film(Film(title, year, None, ""))
    assert fid is not None
    if tt is not None:
        ctx["repo"].set_external_id(fid, "imdb", tt, TODAY)
    ctx["seeded"] += 1


@given(parsers.parse('a film "{title}" ({year:d}) holding imdb "{tt}"'))
def film_with_imdb(ctx, title, year, tt):
    _film(ctx, title, year, tt)


@given(parsers.parse('a film "{title}" ({year:d}) holding no ids'))
def film_without_ids(ctx, title, year):
    _film(ctx, title, year)


@given(parsers.parse('TMDB knows "{tt}" as film {tmdb_id:d} "{title}" ({year:d})'))
def tmdb_knows(ctx, tt, tmdb_id, title, year):
    ctx["tmdb"].by_imdb[tt] = tmdb_id
    ctx["tmdb"].years[tmdb_id] = year
    ctx["tmdb"].facts[tmdb_id] = TmdbFacts(tt, title, title, (), year, 90)


def _add(ctx, tt, apply):
    ctx["add"] = add_by_id(ctx["repo"], tt, TODAY, tmdb=ctx["tmdb"], apply=apply, log=ctx["log"].append)


@when(parsers.parse('I add "{tt}"'))
def add_dry(ctx, tt):
    _add(ctx, tt, False)


@when(parsers.parse('I add "{tt}" with apply'))
def add_apply(ctx, tt):
    _add(ctx, tt, True)


@then(parsers.parse('the add says "{kind}"'))
def add_says(ctx, kind):
    assert ctx["add"].kind == kind, ctx["add"]


@then(parsers.parse('adding "{tt}" is refused'))
def add_refused(ctx, tt):
    with pytest.raises(AddError):
        _add(ctx, tt, True)


@then(parsers.parse('the film "{title}" holds imdb "{tt}"'))
def film_holds_imdb(ctx, title, tt):
    rows = _q(
        ctx,
        "SELECT e.value FROM external_ids e JOIN films f ON f.id = e.film_id "
        "WHERE f.title = ? AND e.authority = 'imdb'",
        title,
    )
    assert rows == [(tt,)], rows


@then(parsers.parse("{n:d} film was created"))
def films_created(ctx, n):
    assert _q(ctx, "SELECT COUNT(*) FROM films")[0][0] == ctx["seeded"] + n


@then("no film was created")
def no_film_created(ctx):
    films_created(ctx, 0)
