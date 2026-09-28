"""The viewing log's application layer (brief 2.2): the ladder, the writes, the refusals. Assertions read the DATABASE."""

from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime, timedelta

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application import viewings as vw
from movie_brain.domain.models import CrewRow, Film, TmdbCredits

scenarios("../features/viewings.feature")

NOW = datetime(2026, 9, 27, 21, 0, 0)


@pytest.fixture
def ctx(repo):
    return {"repo": repo, "today": NOW.date(), "films": {}, "merged": {}, "out": None, "last_vid": None}


def _q(ctx, sql, *args):
    conn = sqlite3.connect(ctx["repo"].db_path)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def _snapshot(ctx):
    return (
        _q(ctx, "SELECT * FROM viewing"),
        _q(ctx, "SELECT * FROM artefact"),
        _q(ctx, "SELECT * FROM my_ratings"),
        _q(ctx, "SELECT * FROM unseen"),
    )


@given(parsers.parse("today is {d}"))
def today_is(ctx, d):
    ctx["today"] = date.fromisoformat(d)
    ctx["before"] = _snapshot(ctx)


@given(parsers.parse('the registry knows "{a}" and "{b}"'))
def registry(ctx, a, b):
    ctx["repo"].register_provider(1899, a)
    ctx["repo"].register_provider(258, b)


@given(parsers.parse('a film "{title}" ({year:d})'))
def a_film(ctx, title, year):
    fid = ctx["repo"].create_film(Film(title, year, None, ""))
    assert fid is not None
    ctx["films"][(title, year)] = fid
    ctx["before"] = _snapshot(ctx)


@given(parsers.parse('a film "{title}" ({year:d}) directed by "{director}"'))
def a_film_directed(ctx, title, year, director):
    fid = ctx["repo"].create_film(Film(title, year, director, ""))
    assert fid is not None
    ctx["films"][(title, year)] = fid
    ctx["before"] = _snapshot(ctx)


@given(parsers.parse('a film "{title}" ({year:d}) with credits director "{director}" but no stored director'))
def a_film_with_credits_director(ctx, title, year, director):
    fid = ctx["repo"].create_film(Film(title, year, None, ""))
    assert fid is not None
    ctx["repo"].write_credits(
        fid,
        TmdbCredits(
            tmdb_id=900000 + fid, imdb_id=None, title=title, original_title=title, year=year, runtime_min=None,
            alt_titles=(), overview=None, tagline=None, genres=(), keywords=(),
            cast=(), crew=(CrewRow(800000 + fid, director, "Director", "Directing"),),
        ),
        ctx["today"],
    )
    ctx["films"][(title, year)] = fid
    ctx["before"] = _snapshot(ctx)


@given(parsers.parse('a merged-away twin "{title}" ({year:d})'))
def merged_twin(ctx, title, year):
    # Created under a different key so create_film accepts it, then given the SAME displayed title
    # and merged away: a retired row that must never be a ladder candidate (finding 5).
    loser = ctx["repo"].create_film(Film(f"{title} twin {year}", year, None, "twin"))
    assert loser is not None
    conn = sqlite3.connect(ctx["repo"].db_path)
    conn.execute("UPDATE films SET title = ? WHERE id = ?", (title, loser))
    conn.commit()
    conn.close()
    ctx["repo"].merge_film(loser, ctx["films"][(title, year)], ctx["today"])
    ctx["merged"][(title, year)] = loser
    ctx["before"] = _snapshot(ctx)


@given(parsers.parse('the drawer reported "{title}" ({year:d}) {secs:d} seconds ago'))
def drawer_reported(ctx, title, year, secs):
    ctx["repo"].set_drawer_film(ctx["films"][(title, year)], NOW - timedelta(seconds=secs))


@given("the drawer reported nothing")
def drawer_nothing(ctx):
    ctx["repo"].set_drawer_film(None, NOW)


@given(parsers.parse('"{title}" ({year:d}) is marked unseen and on the watchlist'))
def unseen_and_watchlisted(ctx, title, year):
    fid = ctx["films"][(title, year)]
    ctx["repo"].set_unseen(fid, True, ctx["today"])
    ctx["repo"].toggle_watchlist(fid, ctx["today"])
    ctx["before"] = _snapshot(ctx)


_HOW = re.compile(
    r'^(?:film "(?P<ftitle>[^"]+)" \((?P<fyear>\d{4})\)(?: titled "(?P<mismatch_title>[^"]+)")?'
    r'|film id (?P<fid>\d+)|the merged twin of "(?P<mtitle>[^"]+)" \((?P<myear>\d{4})\)|"(?P<title>[^"]+)")'
    r'(?: year (?P<year>\d{4}))?(?: on (?P<on>\d{4}-\d{2}-\d{2}))?(?: on "(?P<service>[^"]+)")?(?: rating (?P<rate>-?\d+))? saying "(?P<text>[^"]*)"$'
)


@when(parsers.re(r"I log (?P<rest>.+)"))
def i_log(ctx, rest):
    m = _HOW.match(rest.strip())
    assert m, rest
    g = m.groupdict()
    film_id = None
    if g["ftitle"]:
        film_id = ctx["films"][(g["ftitle"], int(g["fyear"]))]
    elif g["fid"]:
        film_id = int(g["fid"])
    elif g["mtitle"]:
        film_id = ctx["merged"][(g["mtitle"], int(g["myear"]))]
    title_arg = g["mismatch_title"] if g["mismatch_title"] else g["title"]
    ctx["out"] = vw.log_viewing(
        ctx["repo"],
        title=title_arg,
        film_id=film_id,
        year=int(g["year"]) if g["year"] else None,
        on=date.fromisoformat(g["on"]) if g["on"] else None,
        service=g["service"],
        rate=int(g["rate"]) if g["rate"] else None,
        text=g["text"],
        today=ctx["today"],
        now=NOW,
    )
    if ctx["out"].viewing_id is not None:
        ctx["last_vid"] = ctx["out"].viewing_id


@when(parsers.parse("I remove note {n:d} of the last viewing"))
def remove_note(ctx, n):
    ctx["out"] = vw.remove(ctx["repo"], ctx["last_vid"], n)


@when(parsers.parse("I remove note {n:d} of viewing {vid:d}"))
def remove_note_of(ctx, n, vid):
    ctx["out"] = vw.remove(ctx["repo"], vid, n)


@when("I remove the last viewing")
def remove_last(ctx):
    ctx["out"] = vw.remove(ctx["repo"], ctx["last_vid"], None)


@then(parsers.parse('the outcome is "{kind}" for "{title}" ({year:d}) matched "{how}"'))
def outcome_for(ctx, kind, title, year, how):
    o = ctx["out"]
    assert (o.kind, o.film_id, o.exit_code) == (kind, ctx["films"][(title, year)], 0), o
    assert how in o.line, o.line


@then(parsers.parse('the outcome is "{kind}" with exit {code:d} listing "{a}" and "{b}"'))
def outcome_listing_two(ctx, kind, code, a, b):
    o = ctx["out"]
    assert (o.kind, o.exit_code) == (kind, code), o
    assert a in o.line and b in o.line, o.line


@then(parsers.parse('the outcome is "{kind}" with exit {code:d} listing "{a}"'))
def outcome_listing_one(ctx, kind, code, a):
    o = ctx["out"]
    assert (o.kind, o.exit_code) == (kind, code) and a in o.line, o


@then(parsers.parse('the outcome is "{kind}" with exit {code:d} listing nothing'))
def outcome_listing_none(ctx, kind, code):
    o = ctx["out"]
    assert (o.kind, o.exit_code) == (kind, code) and "nearest" not in o.line and "#" not in o.line, o


@then(parsers.parse('the outcome is "{kind}" with exit {code:d}'))
def outcome_kind(ctx, kind, code):
    assert (ctx["out"].kind, ctx["out"].exit_code) == (kind, code), ctx["out"]


@then(parsers.parse('the outcome is "{kind}" with {n:d} notes'))
def outcome_notes(ctx, kind, n):
    assert ctx["out"].kind == kind and f"note {n}" in ctx["out"].line, ctx["out"]


@then(parsers.parse('the outcome is "{kind}" naming "{text}"'))
def outcome_naming(ctx, kind, text):
    assert ctx["out"].kind == kind and text in ctx["out"].line, ctx["out"]


@then(parsers.parse('the outcome is "{kind}" with exit {code:d} naming "{text}"'))
def outcome_kind_naming(ctx, kind, code, text):
    o = ctx["out"]
    assert (o.kind, o.exit_code) == (kind, code) and text in o.line, o


@then("nothing was written")
def nothing_written(ctx):
    assert _snapshot(ctx) == ctx["before"]


@then(parsers.parse('the film "{title}" ({year:d}) has {n:d} viewing on {d} with service "{slug}"'))
def has_one_viewing(ctx, title, year, n, d, slug):
    rows = _q(ctx, "SELECT watched_on, service FROM viewing WHERE film_id = ?", ctx["films"][(title, year)])
    assert rows == [(d, slug)] and n == 1, rows


@then(parsers.parse('the film "{title}" ({year:d}) has {n:d} viewings'))
def has_n_viewings(ctx, title, year, n):
    assert _q(ctx, "SELECT COUNT(*) FROM viewing WHERE film_id = ?", ctx["films"][(title, year)])[0][0] == n


@then(parsers.parse('the film "{title}" ({year:d}) is rated {score:d}'))
def is_rated(ctx, title, year, score):
    assert _q(ctx, "SELECT score FROM my_ratings WHERE film_id = ?", ctx["films"][(title, year)]) == [(score,)]


@then(parsers.parse('"{title}" ({year:d}) is not unseen and is still on the watchlist'))
def unseen_cleared(ctx, title, year):
    fid = ctx["films"][(title, year)]
    assert _q(ctx, "SELECT 1 FROM unseen WHERE film_id = ?", fid) == []
    assert _q(ctx, "SELECT 1 FROM watchlist WHERE film_id = ?", fid) == [(1,)]


@then(parsers.parse('the last viewing of "{title}" ({year:d}) has notes "{a}" and "{b}"'))
def last_viewing_notes(ctx, title, year, a, b):
    vs = ctx["repo"].viewings_for(ctx["films"][(title, year)])
    assert [x["text"] for x in vs[0]["artefacts"]] == [a, b]


@then(parsers.parse('the listing since {d} reads "{a}" then "{b}" then "{c}" then "{e}" then "{f}"'))
def listing_reads(ctx, d, a, b, c, e, f):
    text = vw.listing(ctx["repo"], date.fromisoformat(d), None)
    assert re.search(
        re.escape(a) + r".*" + re.escape(b) + r".*" + re.escape(c) + r".*" + re.escape(e) + r".*" + re.escape(f), text
    ), text


@then(parsers.parse('the film listing for "{title}" ({year:d}) shows note 1 "{a}" and note 2 "{b}"'))
def film_listing_shows_notes(ctx, title, year, a, b):
    text = vw.listing(ctx["repo"], None, ctx["films"][(title, year)])
    assert re.search(re.escape(f"note 1  {a}") + r".*" + re.escape(f"note 2  {b}"), text, re.S), text


@then(parsers.parse('the open line names "{title}" ({year:d})'))
def open_names(ctx, title, year):
    assert f"#{ctx['films'][(title, year)]} '{title}' ({year})" in vw.open_line(ctx["repo"], NOW)


@then("the open line says nothing is open")
def open_nothing(ctx):
    assert vw.open_line(ctx["repo"], NOW).startswith("OPEN      nothing")


@when(parsers.parse('I mark "{title}" watched on {d} with no note'))
def i_log_no_note(ctx, title, d):
    ctx["out"] = vw.log_viewing(
        ctx["repo"], title=title, film_id=None, year=None, on=date.fromisoformat(d), service=None,
        rate=None, text=None, today=ctx["today"], now=NOW,
    )
    if ctx["out"].viewing_id is not None:
        ctx["last_vid"] = ctx["out"].viewing_id


@then(parsers.parse('the last viewing of "{title}" ({year:d}) has no notes'))
def last_viewing_no_notes(ctx, title, year):
    vs = ctx["repo"].viewings_for(ctx["films"][(title, year)])
    assert vs and vs[0]["artefacts"] == [], vs


@then("the outcome says the line already existed and nothing new was added")
def outcome_nothing_new(ctx):
    o = ctx["out"]
    assert o.kind == "added-to" and "no new note (0 kept)" in o.line, o
