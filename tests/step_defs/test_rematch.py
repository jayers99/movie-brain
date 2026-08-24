from __future__ import annotations

import json
import re
import sqlite3
from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest
import responses
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.domain.models import Film
from movie_brain.infrastructure.tmdb import TMDB_API

scenarios("../features/rematch.feature")

TODAY = date(2026, 8, 24)

_DETAIL_RE = re.compile(rf"^{re.escape(TMDB_API)}/movie/\d+$")


@pytest.fixture
def ctx(repo):
    rs = responses.RequestsMock(assert_all_requests_are_fired=False)
    rs.start()
    yield {"repo": repo, "rs": rs, "reports": []}
    rs.stop()
    rs.reset()


@pytest.fixture
def tmdb(ctx):
    """A minimal TMDB world: search index + movie-detail years, with call counters."""
    world = {"search": {}, "movies": {}, "search_calls": 0, "detail_calls": 0}

    def do_search(request):
        world["search_calls"] += 1
        title = parse_qs(urlparse(request.url).query)["query"][0]
        hit = world["search"].get(title)
        results = [hit] if hit else []
        return (200, {}, json.dumps({"results": results}))

    def do_detail(request):
        world["detail_calls"] += 1
        tid = int(request.url.rsplit("/", 1)[-1])
        year = world["movies"].get(tid)
        release_date = f"{year}-01-01" if year else ""
        return (200, {}, json.dumps({"id": tid, "release_date": release_date}))

    ctx["rs"].add_callback(responses.GET, f"{TMDB_API}/search/movie", callback=do_search)
    ctx["rs"].add_callback(responses.GET, _DETAIL_RE, callback=do_detail)
    return world


@given("a fresh repository")
def fresh(ctx):
    pass


@given(parsers.parse('a commerce film "{title}" from {year:d} marked as a TMDB miss'))
def commerce_miss(ctx, title, year):
    fid = ctx["repo"].upsert_film(Film(title, year, None, f"https://mc/{title.lower()}"))
    ctx["repo"].upsert_tmdb(fid, found=False, looked_up=TODAY)


@given(parsers.parse('a commerce film "{title}" from {year:d} already matched to TMDB id {tid:d}'))
def commerce_matched(ctx, title, year, tid):
    fid = ctx["repo"].upsert_film(Film(title, year, None, f"https://mc/{title.lower()}"))
    ctx["repo"].set_external_id(fid, "tmdb", str(tid), TODAY)
    ctx["repo"].upsert_tmdb(fid, found=True, looked_up=TODAY)


@given(parsers.parse('a criterion film "{title}" from {year:d} already matched to TMDB id {tid:d}'))
def criterion_matched(ctx, title, year, tid):
    url = f"https://c/{title.lower()}"
    fid = ctx["repo"].upsert_film(Film(title, year, None, url))
    ctx["repo"].record_listing(fid, "criterion", url, TODAY)
    ctx["repo"].set_external_id(fid, "tmdb", str(tid), TODAY)
    ctx["repo"].upsert_tmdb(fid, found=True, looked_up=TODAY)


@given(parsers.parse('a film "{title}" from {year:d} exists'))
def film_exists(ctx, title, year):
    ctx["repo"].upsert_film(Film(title, year, None, f"https://mc/{title.lower()}-{year}"))


@given(parsers.parse('TMDB knows "{title}" as id {tid:d} released {year:d}'))
def tmdb_knows_released(tmdb, title, tid, year):
    tmdb["search"][title] = {
        "id": tid,
        "title": title,
        "original_title": title,
        "release_date": f"{year}-01-01",
        "popularity": 5.0,
    }
    tmdb["movies"][tid] = year


@given(parsers.parse("TMDB movie {tid:d} was released in {year:d}"))
def tmdb_movie_year(tmdb, tid, year):
    tmdb["movies"][tid] = year


@given("TMDB has no results for any search")
def tmdb_empty(tmdb):
    pass  # empty search index → every search returns no results


@when("I run rematch")
@when("I run rematch again")
def run_rematch(ctx, tmdb):
    from movie_brain.application.rematch import rematch
    from movie_brain.infrastructure.tmdb import TmdbClient

    ctx["reports"].append(rematch(ctx["repo"], TmdbClient("tok"), TODAY))


@then(parsers.parse('"{title} ({year:d})" has external id "{value}" for authority "{authority}"'))
def has_external(ctx, title, year, value, authority):
    fid = ctx["repo"].film_id_by_key(f"{title.lower()} ({year})")
    assert fid is not None, f"no film with key {title.lower()} ({year})"
    assert ctx["repo"].external_ids_for(fid).get(authority) == value


@then(parsers.parse('the film "{title}" has year {year:d}'))
def film_has_year(ctx, title, year):
    with sqlite3.connect(ctx["repo"].db_path) as c:
        row = c.execute("SELECT year FROM films WHERE title = ?", (title,)).fetchone()
    assert row is not None, f"no film titled {title!r}"
    assert row[0] == year


@then(parsers.parse('the film "{title}" from {orig_year:d} still has year {year:d}'))
def film_still_has_year(ctx, title, orig_year, year):
    fid = ctx["repo"].film_id_by_key(f"{title.lower()} ({orig_year})")
    assert fid is not None, f"no film with key {title.lower()} ({orig_year})"
    with sqlite3.connect(ctx["repo"].db_path) as c:
        row = c.execute("SELECT year FROM films WHERE id = ?", (fid,)).fetchone()
    assert row[0] == year


@then(parsers.parse("the rematch report says {rematched:d} rematched and {adopted:d} year adopted"))
def report_rematched_adopted(ctx, rematched, adopted):
    r = ctx["reports"][-1]
    assert r.rematched == rematched
    assert r.years_adopted == adopted


@then(parsers.parse("the rematch report says {checked:d} checked and {adopted:d} year adopted"))
def report_checked_adopted(ctx, checked, adopted):
    r = ctx["reports"][-1]
    assert r.checked == checked
    assert r.years_adopted == adopted


@then(parsers.parse("the rematch report says {checked:d} checked"))
def report_checked(ctx, checked):
    r = ctx["reports"][-1]
    assert r.checked == checked


@then(parsers.parse("the rematch report says {rematched:d} rematched and {missed:d} still missed"))
def report_rematched_missed(ctx, rematched, missed):
    r = ctx["reports"][-1]
    assert r.rematched == rematched
    assert r.still_missed == missed


@then(parsers.parse("the second report says {rematched:d} rematched and {adopted:d} years adopted"))
def second_report(ctx, rematched, adopted):
    r = ctx["reports"][-1]
    assert r.rematched == rematched
    assert r.years_adopted == adopted


@then(parsers.parse('the tmdb review queue holds {n:d} "{reason}" entries'))
def review_reason_count(ctx, n, reason):
    got = sum(1 for r in ctx["repo"].open_reviews("tmdb") if r["reason"] == reason)
    assert got == n


@then(parsers.parse("TMDB movie details were fetched {n:d} times"))
def detail_calls(tmdb, n):
    assert tmdb["detail_calls"] == n
