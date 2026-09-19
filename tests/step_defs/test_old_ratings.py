"""Old ratings: the import links through the resolver and never creates; the create verb is the
only minting path and re-gates every row. Invented rows only — nothing from the owner's real
file may enter this public repo (spec O9). Assertions read the DATABASE, never the report.
"""

from __future__ import annotations

import sqlite3
from datetime import date

import pytest
from lists_fakes import RecordingFetcher, StubTmdb, candidate
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.old_ratings import (
    LinkError,
    create_films,
    import_old_ratings,
    link_row,
    scorecard,
)
from movie_brain.domain.models import Film, OldRating

scenarios("../features/old_ratings.feature")

TODAY = date(2026, 9, 19)
SRC = "ntc"


@pytest.fixture
def ctx(repo):
    return {"repo": repo, "films": {}, "rows": [], "fetcher": RecordingFetcher(), "tmdb": StubTmdb(), "log": []}


def _q(ctx, sql, *args):
    conn = sqlite3.connect(ctx["repo"].db_path)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def _film_id(ctx, title):
    if title in ctx["films"]:
        return ctx["films"][title]
    rows = _q(ctx, "SELECT id FROM films WHERE title = ?", title)
    assert len(rows) == 1, f"{title!r}: {rows}"
    return rows[0][0]


def _stored(ctx, line):
    rows = _q(ctx, "SELECT film_id, linked_by, linked_on FROM old_rating WHERE source = ? AND line = ?", SRC, line)
    assert len(rows) == 1, f"row {line}: {rows}"
    return rows[0]


def _film(ctx, title, year, tt=None):
    fid = ctx["repo"].create_film(Film(title, year, None, ""))
    assert fid is not None
    ctx["films"][title] = fid
    if tt is not None:
        ctx["repo"].set_external_id(fid, "imdb", tt, TODAY)
    return fid


@given(parsers.parse('a film "{title}" ({year:d}) holding imdb "{tt}"'))
@when(parsers.parse('a film "{title}" ({year:d}) holding imdb "{tt}" arrives'))
def film_with_imdb(ctx, title, year, tt):
    ctx.setdefault("seeded", 0)
    _film(ctx, title, year, tt)
    ctx["seeded"] += 1


@when(parsers.parse('a film "{title}" ({year:d}) holding no ids arrives'))
def film_without_ids(ctx, title, year):
    _film(ctx, title, year)
    ctx["seeded"] += 1


@given(parsers.parse('the resolver knows "{asked}" as "{tt}" "{title}" ({year:d})'))
def resolver_knows(ctx, asked, tt, title, year):
    ctx["fetcher"].by_title[asked] = [candidate(tt, int(tt[2:]), title, year)]


@given("the old ratings")
def the_old_ratings(ctx, datatable):
    header, *body = datatable
    for line, cells in enumerate(body, start=1):
        r = dict(zip(header, cells, strict=True))
        ctx["rows"].append(OldRating(line, r["title"], int(r["year"]), int(r["stars"]), r["rented"]))


def _import(ctx, apply):
    ctx["asked_before"] = list(ctx["fetcher"].queried)
    report = import_old_ratings(
        ctx["repo"], SRC, ctx["rows"], TODAY, fetcher=ctx["fetcher"], tmdb=ctx["tmdb"], apply=apply,
        log=ctx["log"].append,
    )
    ctx["card"] = scorecard(report.rows)
    ctx["outcomes"] = {r.row.line: r.kind for r in report.rows}


@when("I import the old ratings")
def import_dry(ctx):
    _import(ctx, False)


@when("I import the old ratings with apply")
def import_apply(ctx):
    _import(ctx, True)


def _create(ctx, apply):
    report = create_films(
        ctx["repo"], SRC, TODAY, fetcher=ctx["fetcher"], tmdb=ctx["tmdb"], apply=apply, log=ctx["log"].append
    )
    assert report.exit_code == 0
    ctx["card"] = scorecard(report.rows)
    ctx["outcomes"] = {r.row.line: r.kind for r in report.rows}


@when("I create the missing films")
def create_dry(ctx):
    _create(ctx, False)


@when("I create the missing films with apply")
def create_apply(ctx):
    _create(ctx, True)


@when(parsers.parse('I hand-link row {line:d} to "{title}"'))
def hand_link(ctx, line, title):
    link_row(ctx["repo"], SRC, line, _film_id(ctx, title), TODAY)


@when(parsers.parse("I clear the link of row {line:d}"))
def clear_link(ctx, line):
    link_row(ctx["repo"], SRC, line, None, TODAY)


@when(parsers.parse('"{loser}" is merged into "{survivor}"'))
def merged(ctx, loser, survivor):
    ctx["repo"].merge_film(_film_id(ctx, loser), _film_id(ctx, survivor), TODAY)


@then(parsers.parse('row {line:d} is linked to "{title}" by "{how}"'))
def row_linked(ctx, line, title, how):
    film_id, linked_by, linked_on = _stored(ctx, line)
    assert (film_id, linked_by, linked_on) == (_film_id(ctx, title), how, TODAY.isoformat())


@then(parsers.parse("row {line:d} is stored unlinked"))
def row_unlinked(ctx, line):
    assert _stored(ctx, line) == (None, None, None)


@then("no old rating is stored")
def nothing_stored(ctx):
    assert _q(ctx, "SELECT COUNT(*) FROM old_rating") == [(0,)]


@then(parsers.parse('the scorecard says row {line:d} is "{kind}"'))
def card_says(ctx, line, kind):
    assert ctx["outcomes"][line].upper() == kind
    assert kind in ctx["card"]


@then("no film was created")
def none_created(ctx):
    assert _q(ctx, "SELECT COUNT(*) FROM films") == [(ctx["seeded"],)]


@then(parsers.parse("{n:d} film was created"))
def n_created(ctx, n):
    """Counts films beyond the ones the steps themselves seeded — so 'arrives' films don't count."""
    assert _q(ctx, "SELECT COUNT(*) FROM films")[0][0] - ctx["seeded"] == n


@then("no review row was queued")
def no_reviews(ctx):
    assert _q(ctx, "SELECT COUNT(*) FROM match_review") == [(0,)]


@then(parsers.parse('the resolver was not asked about "{title}" on the second run'))
def not_asked_again(ctx, title):
    assert title not in ctx["fetcher"].queried[len(ctx["asked_before"]):]


@then(parsers.parse('the film "{title}" holds imdb "{tt}"'))
def holds_imdb(ctx, title, tt):
    assert ctx["repo"].film_id_for_external("imdb", tt) == _film_id(ctx, title)


@then(parsers.parse('"{title}" has no rating of mine'))
def no_my_rating(ctx, title):
    assert _q(ctx, "SELECT COUNT(*) FROM my_ratings") == [(0,)]


@then(parsers.parse('the view of "{title}" carries an old rating of {stars:d} stars'))
def view_carries(ctx, title, stars):
    view = ctx["repo"].get_view(_film_id(ctx, title))
    assert view is not None and view.old_rating is not None
    assert view.old_rating["stars"] == stars


@then(parsers.parse("hand-linking row {line:d} to film {film_id:d} is refused"))
def link_refused_film(ctx, line, film_id):
    with pytest.raises(LinkError):
        link_row(ctx["repo"], SRC, line, film_id, TODAY)


@then(parsers.parse('hand-linking row {line:d} to "{title}" is refused'))
def link_refused_row(ctx, line, title):
    with pytest.raises(LinkError):
        link_row(ctx["repo"], SRC, line, _film_id(ctx, title), TODAY)
