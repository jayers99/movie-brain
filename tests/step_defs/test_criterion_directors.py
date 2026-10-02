"""Criterion's directors (spec 2026-10-01 D8, story 9). Assertions read the DATABASE; JW is the
`FakeSite` carrying the real captured records, OMDb's payloads are real ones from the live DB."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest
from criterion_fakes import FakeSite, captured, media_like
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.criterion_directors import fill_criterion_directors
from movie_brain.domain.models import Film, OmdbRating

scenarios("../features/criterion_directors.feature")

OMDB = Path(__file__).parent.parent / "fixtures" / "omdb"
DAY = date(2026, 10, 3)
TIMES = {"once": 1, "twice": 2}


@pytest.fixture
def ctx(repo):
    return {"repo": repo, "site": FakeSite(), "films": {}, "reports": [], "logs": []}


def _seed(ctx, title, year, director, mediaid):
    fid = ctx["repo"].create_film(Film(title, year, director, ""))
    assert fid is not None
    ctx["repo"].set_external_id(fid, "criterion", mediaid, DAY)
    ctx["films"][title] = fid


def _director(ctx, title):
    with sqlite3.connect(ctx["repo"].db_path) as c:
        return c.execute("SELECT director FROM films WHERE id = ?", (ctx["films"][title],)).fetchone()[0]


# Given ---------------------------------------------------------------------


@given(parsers.parse('the film "{title}" ({year:d}) holds Criterion id "{mediaid}"'))
def film_holding(ctx, title, year, mediaid):
    _seed(ctx, title, year, None, mediaid)


@given(parsers.parse('the film "{title}" ({year:d}) directed by "{director}" holds Criterion id "{mediaid}"'))
def film_directed_holding(ctx, title, year, director, mediaid):
    _seed(ctx, title, year, director, mediaid)


@given(parsers.parse('OMDb found nothing for "{title}"'))
def omdb_not_found(ctx, title):
    ctx["repo"].upsert_omdb(ctx["films"][title], OmdbRating(None, None, False), DAY)


@given(parsers.parse('OMDb\'s record for "{title}" is the captured "{name}"'))
def omdb_captured(ctx, title, name):
    ctx["repo"].upsert_omdb(ctx["films"][title], OmdbRating(5.3, None, True, payload=(OMDB / name).read_text()), DAY)


@given(parsers.parse('JW answers for "{mediaid}" as captured on 2026-10-02'))
def jw_captured(ctx, mediaid):
    ctx["site"].media_by_id[mediaid] = captured(mediaid)


@given(parsers.parse('JW lists "{mediaid}" with director "{director}"'))
def jw_lists_director(ctx, mediaid, director):
    ctx["site"].media_by_id[mediaid] = media_like(mediaid, "Any Title", directors=(director,))


@given(parsers.parse('JW lists "{mediaid}" with no director'))
def jw_lists_none(ctx, mediaid):
    ctx["site"].media_by_id[mediaid] = media_like(mediaid, "Any Title", directors=())


@given(parsers.parse('JW has no record of "{mediaid}"'))
def jw_404(ctx, mediaid):
    ctx["site"].media_by_id.pop(mediaid, None)  # FakeSite answers an absent id like JW's 404


@given(parsers.parse('JW fails for "{mediaid}"'))
def jw_fails(ctx, mediaid):
    ctx["site"].media_fails.add(mediaid)


# When ----------------------------------------------------------------------


def _run(ctx, apply):
    report = fill_criterion_directors(ctx["repo"], ctx["site"], apply=apply, log=ctx["logs"].append)
    ctx["reports"].append(report)


@when("I fill Criterion directors with apply")
def fill_apply(ctx):
    _run(ctx, True)


@when("I fill Criterion directors without applying")
def fill_dry(ctx):
    _run(ctx, False)


# Then ----------------------------------------------------------------------


@then(parsers.parse('the director of "{title}" is "{director}"'))
def director_is(ctx, title, director):
    assert _director(ctx, title) == director


@then(parsers.parse('"{title}" has no director of its own'))
def no_director(ctx, title):
    assert _director(ctx, title) is None


@then("JW was asked about nothing")
def asked_nothing(ctx):
    assert ctx["site"].media_calls == []


@then(parsers.re(r'JW was asked about "(?P<mediaid>[^"]+)" (?P<times>once|twice)$'))
def asked_times(ctx, mediaid, times):
    assert ctx["site"].media_calls == [mediaid] * TIMES[times]


@then(parsers.parse('JW was asked about "{a}", "{b}", "{c}" in that order'))
def asked_in_order(ctx, a, b, c):
    assert ctx["site"].media_calls == [a, b, c]


@then(parsers.parse(
    "the report reads {scanned:d} scanned, {filled:d} filled, {none:d} without a director, "
    "{gone:d} not on JW, {failed:d} failed"
))
def report_reads(ctx, scanned, filled, none, gone, failed):
    r = ctx["reports"][-1]
    assert (r.scanned, r.filled, r.no_director, r.gone, r.failed) == (scanned, filled, none, gone, failed)


@then(parsers.parse('the log names "{a}" and "{b}"'))
def log_names(ctx, a, b):
    assert any(a in m for m in ctx["logs"]) and any(b in m for m in ctx["logs"])
