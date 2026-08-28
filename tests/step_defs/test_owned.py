from __future__ import annotations

import re
import sqlite3
from datetime import date

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.owned import AUTHORITY, import_owned
from movie_brain.domain.models import Film, OwnedTitle
from movie_brain.domain.thumbprint import Candidate, parse_title
from movie_brain.infrastructure.appletv import AppleTvError

scenarios("../features/owned.feature")

TODAY = date(2026, 8, 19)


@pytest.fixture
def ctx(repo, config_dir):
    return {"repo": repo, "config_dir": config_dir, "library": [], "fail": False, "report": None}


class PoolFetcher:
    """Stands in for CandidateFetcher: canned candidates per (parsed) query title."""

    def __init__(self):
        self.pool: dict[str, list[Candidate]] = {}

    def fetch(self, q):
        return self.pool.get(q.title, [])


class FakeTmdb:
    """`key_film` reads TMDB's own release year through `movie_year` before writing."""

    def __init__(self):
        self.years: dict[int, int] = {}

    def movie_year(self, tid):
        return self.years.get(tid)


@pytest.fixture
def pool(ctx):
    ctx["pool"] = PoolFetcher()
    return ctx["pool"]


@pytest.fixture
def tmdb(ctx):
    ctx["tmdb"] = FakeTmdb()
    return ctx["tmdb"]


def _film(title_year: str) -> Film:
    m = re.match(r"(.+) \((\d{4})\)$", title_year)
    assert m
    return Film(m.group(1), int(m.group(2)), "Someone", f"https://c/{m.group(1).lower()}")


@given(parsers.re(r'the repository holds the film "(?P<title_year>[^"]+)"$'))
def holds_film(ctx, title_year):
    ctx["repo"].upsert_film(_film(title_year))


@given(parsers.re(r'my Apple TV library has "(?P<title>[^"]+)" \((?P<year>\d+)\)'))
def library_has(ctx, title, year):
    ctx["library"].append(OwnedTitle(title, int(year)))


@given(
    parsers.re(
        r'the repository holds the film "(?P<title_year>[^"]+)" keyed imdb "(?P<tt>tt\d+)" tmdb "(?P<tid>\d+)"$'
    )
)
def holds_film_keyed(ctx, title_year, tt, tid):
    fid = ctx["repo"].create_film(_film(title_year))
    ctx["repo"].set_external_id(fid, "imdb", tt, TODAY)
    ctx["repo"].set_external_id(fid, "tmdb", tid, TODAY)


@given(parsers.re(r'the resolver pool has "(?P<title>[^"]+)" → (?P<tt>tt\d+)/(?P<tid>\d+) (?P<year>\d{4})'))
def pool_seed(ctx, pool, tmdb, title, tt, tid, year):
    key = parse_title(title).title
    pool.pool[key] = [Candidate(tt, int(tid), (key,), int(year), "", 100, 5000, "movie", True, True)]
    tmdb.years[int(tid)] = int(year)


@given(parsers.parse('"{title_year}" is tombstoned'))
def tombstoned(ctx, title_year):
    fid = ctx["repo"].film_id_by_key(_film(title_year).key)
    ctx["repo"].tombstone_film(fid, TODAY, note="test")


@given(parsers.parse('the resolver pool has "{title}" ambiguous'))
def pool_seed_ambiguous(ctx, pool, title):
    key = parse_title(title).title
    pool.pool[key] = []


@given(parsers.re(r'my Apple TV library has "(?P<title>[^"]+)" \((?P<year>\d+)\) running (?P<mins>\d+) minutes'))
def library_has_runtime(ctx, title, year, mins):
    ctx["library"].append(OwnedTitle(title, int(year), int(mins)))


@given("my Apple TV library export fails")
def library_fails(ctx):
    ctx["fail"] = True


@when("I import owned films")
def run_import(ctx):
    def fetch():
        if ctx["fail"]:
            raise AppleTvError("boom")
        return list(ctx["library"])

    ctx["report"] = import_owned(
        ctx["repo"],
        ctx["config_dir"],
        TODAY,
        fetch=fetch,
        fetcher=ctx.get("pool"),
        tmdb=ctx.get("tmdb"),
        log=lambda m: None,
    )


@when("I import owned films without a resolver")
def run_import_no_resolver(ctx):
    def fetch():
        if ctx["fail"]:
            raise AppleTvError("boom")
        return list(ctx["library"])

    ctx["report"] = import_owned(
        ctx["repo"], ctx["config_dir"], TODAY, fetch=fetch, fetcher=None, tmdb=None, log=lambda m: None
    )


@then(parsers.parse('"{title_year}" is owned'))
def film_is_owned(ctx, title_year):
    fid = ctx["repo"].film_id_by_key(_film(title_year).key)
    assert fid in ctx["repo"].owned_film_ids()


@then(parsers.parse('"{title_year}" is not owned'))
def film_is_not_owned(ctx, title_year):
    fid = ctx["repo"].film_id_by_key(_film(title_year).key)
    assert fid not in ctx["repo"].owned_film_ids()


@then(parsers.parse('the film "{title_year}" exists with a guid'))
def film_exists_with_guid(ctx, title_year):
    fid = ctx["repo"].film_id_by_key(_film(title_year).key)
    assert fid is not None
    conn = sqlite3.connect(ctx["repo"].db_path)
    guid = conn.execute("SELECT guid FROM films WHERE id = ?", (fid,)).fetchone()[0]
    conn.close()
    assert guid


@then(parsers.parse("the repository holds {n:d} films"))
def film_count(ctx, n):
    assert len(ctx["repo"].films_for_matching()) == n


@then(parsers.parse("the owned report says {m:d} matched and {c:d} created"))
def report_counts(ctx, m, c):
    assert (ctx["report"].matched, ctx["report"].created) == (m, c)


@then(parsers.parse("the owned report says {n:d} already owned"))
def report_already(ctx, n):
    assert ctx["report"].already_owned == n


@then(parsers.parse("the owned report says {c:d} created and {r:d} resolved to existing"))
def report_resolved(ctx, c, r):
    assert (ctx["report"].created, ctx["report"].resolved_to_existing) == (c, r)


@then(parsers.parse("the owned report says {c:d} created and {k:d} keyed"))
def report_keyed(ctx, c, k):
    assert (ctx["report"].created, ctx["report"].keyed) == (c, k)


@then(parsers.re(r'"(?P<title_year>.+)" holds imdb "(?P<tt>tt\d+)" and tmdb id "(?P<tid>\d+)"'))
def holds_ids(ctx, title_year, tt, tid):
    fid = ctx["repo"].film_id_by_key(_film(title_year).key)
    ids = ctx["repo"].external_ids_for(fid)
    assert (ids.get("imdb"), ids.get("tmdb")) == (tt, tid)


@then(parsers.re(r'the owned review queue has an? "(?P<reason>[^"]+)" entry'))
def review_entry(ctx, reason):
    assert any(r["reason"] == reason for r in ctx["repo"].open_reviews(AUTHORITY))


@then(parsers.re(r'the review queue has an? "(?P<reason>[^"]+)" entry'))
def review_entry_plain(ctx, reason):
    assert any(r["reason"] == reason for r in ctx["repo"].open_reviews(AUTHORITY))


@then("no film is owned")
def nothing_owned(ctx):
    assert ctx["repo"].owned_film_ids() == set()


@then(parsers.parse("the owned import exit code is {code:d}"))
def import_exit(ctx, code):
    assert ctx["report"].exit_code == code


@then(
    parsers.re(
        r'"(?P<title_year>.+)" has an? "(?P<authority>[^"]+)" claim titled "(?P<ingested>[^"]+)" '
        r"for year (?P<year>\d+)"
    ),
    converters={"year": int},
)
def has_claim(ctx, title_year, authority, ingested, year):
    fid = ctx["repo"].film_id_by_key(_film(title_year).key)
    claims = [c for c in ctx["repo"].claims_for_film(fid) if c.authority == authority]
    assert claims, f"no {authority} claim on #{fid}"
    assert (claims[0].title_ingested, claims[0].year_claimed) == (ingested, year)
    ctx["claim"] = claims[0]


@then(parsers.parse('that claim has runtime {mins:d} and edition label "{label}"'))
def claim_runtime(ctx, mins, label):
    assert (ctx["claim"].runtime_min, ctx["claim"].edition_label) == (mins, label)
