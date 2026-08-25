from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
import responses
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.availability import META_REFRESHED_AT
from movie_brain.application.sync import SOURCE, sync
from movie_brain.domain.models import Film
from movie_brain.infrastructure.criterion import API_URL, BROWSE_URL
from movie_brain.infrastructure.omdb import OMDB_URL
from movie_brain.infrastructure.tmdb import TMDB_API

scenarios("../features/tmdb.feature")

TODAY = date(2026, 8, 19)
FOUND = {"Response": "True", "imdbRating": "7.0", "Language": "English", "Ratings": []}


def parse_titles(text: str) -> list[Film]:
    films = []
    for m in re.finditer(r'"([^"(]+) \((\d{4})\)"', text):
        title, year = m.group(1), int(m.group(2))
        films.append(Film(title, year, "Someone", f"https://c/{title.lower()}"))
    return films


def movie_item(f: Film) -> dict:
    return {
        "name": f.title,
        "metadata": {"year_released": f.year, "director": f.director},
        "_links": {"collection_page": {"href": f.url}},
    }


@pytest.fixture
def ctx(repo):
    rs = responses.RequestsMock(assert_all_requests_are_fired=False)
    rs.start()
    yield {"repo": repo, "rs": rs, "result": None, "flags": {}}
    rs.stop()
    rs.reset()


@given("a fresh repository")
def fresh(ctx):
    pass


@given("the Criterion browse page exposes a token")
def token(ctx):
    ctx["rs"].get(BROWSE_URL, body='<script>window.TOKEN = "tok";</script>')


@given(parsers.parse("the Criterion catalog has films {films}"))
def catalog(ctx, films):
    flist = parse_titles(films)
    ctx["catalog_films"] = flist
    if ctx["flags"].get("catalog_registered"):
        # A scenario-level line replaces the Background's films; the callback below
        # reads ctx["catalog_films"] at request time, so it must be registered once.
        return
    ctx["flags"]["catalog_registered"] = True

    def movies(request):
        current = ctx["catalog_films"]
        return (
            200,
            {},
            json.dumps(
                {
                    "total": len(current),
                    "_links": {"next": {"href": None}},
                    "_embedded": {"collections": [movie_item(f) for f in current]},
                }
            ),
        )

    def categories(request):
        return (200, {}, '{"_links": {"next": {"href": null}}, "_embedded": {"collections": []}}')

    ctx["rs"].add_callback(
        responses.GET,
        API_URL,
        callback=lambda r: movies(r) if "type%5B%5D=movie" in r.url else categories(r),
    )


@given("OMDb knows every film")
def omdb_ok(ctx):
    ctx["rs"].get(OMDB_URL, json=FOUND)


@given(parsers.parse('the repository already holds {films} walked {days:d} days ago'))
def preloaded(ctx, films, days):
    flist = parse_titles(films)
    walked = TODAY - timedelta(days=days)
    ctx["repo"].record_catalog(SOURCE, flist, walked)
    ctx["repo"].set_meta("films_fetched_at", walked.isoformat())


@pytest.fixture
def tmdb(ctx):
    """One mutable TMDB world: search index, per-id providers, call counters."""
    world = {
        "search": {},
        "providers": {},
        "search_calls": 0,
        "provider_calls": 0,
        "search_mode": "index",
        "reject": False,
    }

    def do_search(request):
        world["search_calls"] += 1
        if world["reject"]:
            return (401, {}, json.dumps({"status_message": "bad token"}))
        if world["search_mode"] == "error":
            return (500, {}, "boom")
        title = parse_qs(urlparse(request.url).query)["query"][0]
        hit = world["search"].get(title)
        results = [hit] if hit else []
        return (200, {}, json.dumps({"results": results}))

    ctx["rs"].add_callback(responses.GET, f"{TMDB_API}/search/movie", callback=do_search)

    def provider_callback(tmdb_id):
        def cb(request):
            world["provider_calls"] += 1
            return (200, {}, json.dumps({"results": {"US": world["providers"].get(tmdb_id, {})}}))

        return cb

    registered_providers: set[int] = set()

    def register_providers(tid):
        # Two films can resolve to the same id (a match conflict) — register once per id,
        # not once per "TMDB knows ... as id N" given, or responses stacks two matchers.
        if tid in registered_providers:
            return
        registered_providers.add(tid)
        ctx["rs"].add_callback(responses.GET, f"{TMDB_API}/movie/{tid}/watch/providers", callback=provider_callback(tid))

    world["register_providers"] = register_providers
    return world


@given(parsers.parse('TMDB knows "{title} ({year:d})" as id {tid:d}'))
def tmdb_knows(tmdb, title, year, tid):
    tmdb["search"][title] = {
        "id": tid,
        "title": title,
        "original_title": title,
        "release_date": f"{year}-01-01",
        "popularity": 5.0,
    }
    tmdb["register_providers"](tid)


@given(parsers.parse('TMDB knows "{title}" as id {tid:d} released {year:d}'))
def tmdb_knows_released(tmdb, title, tid, year):
    """Same as above, but the search-result year can differ from the film's stored
    year — the write-back/arbiter scenarios need to seed a TMDB release year that
    disagrees with the film's own year."""
    tmdb["search"][title] = {
        "id": tid,
        "title": title,
        "original_title": title,
        "release_date": f"{year}-01-01",
        "popularity": 5.0,
    }
    tmdb["register_providers"](tid)


@given(parsers.parse('a commerce film "{title}" from {year:d}'))
def commerce_film(ctx, title, year):
    """No criterion listing → the match loop treats this as commerce-created, per
    TmdbMatchTarget.commerce (year is COMMERCE band, eligible for year write-back)."""
    ctx["repo"].upsert_film(Film(title, year, None, f"https://mc/{title.lower()}"))


@given(parsers.parse("TMDB streams id {tid:d} on providers {a:d} and {b:d}"))
def tmdb_streams(tmdb, tid, a, b):
    tmdb["providers"][tid] = {"link": f"https://tmdb/w/{tid}", "flatrate": [{"provider_id": a}, {"provider_id": b}]}


@given(parsers.parse("TMDB offers id {tid:d} to buy on providers {a:d} and {b:d}"))
def tmdb_buys(tmdb, tid, a, b):
    tmdb["providers"][tid] = {"link": f"https://tmdb/w/{tid}", "buy": [{"provider_id": a}, {"provider_id": b}]}


@given("TMDB has no results for any search")
def tmdb_empty(tmdb):
    pass  # empty search index → every search returns no results


@given("TMDB rejects the token")
def tmdb_reject(tmdb):
    tmdb["reject"] = True


@given("TMDB errors on every search")
def tmdb_errors(tmdb):
    tmdb["search_mode"] = "error"


@given(parsers.parse("the provider refresh ran {days:d} days ago"))
def stamp(ctx, days):
    ctx["repo"].set_meta(META_REFRESHED_AT, (TODAY - timedelta(days=days)).isoformat())


@when("TMDB stops streaming id 11 anywhere")
def tmdb_stops(tmdb):
    tmdb["providers"][11] = {}


@when("I sync")
def do_sync(ctx, tmdb):
    ctx["result"] = sync(ctx["repo"], "omdb-key", TODAY)


@when("I sync with a TMDB token")
def do_sync_tok(ctx, tmdb):
    ctx["result"] = sync(ctx["repo"], "omdb-key", TODAY, tmdb_token="tok")


@when("I sync with a TMDB token and --ratings-only")
def do_sync_tok_ratings_only(ctx, tmdb):
    ctx["result"] = sync(ctx["repo"], "omdb-key", TODAY, tmdb_token="tok", ratings_only=True)


@when("I sync with a TMDB token again the next day")
def do_sync_next(ctx, tmdb):
    ctx["result"] = sync(ctx["repo"], "omdb-key", TODAY + timedelta(days=1), tmdb_token="tok")


@when("I sync with a TMDB token 8 days later")
def do_sync_later(ctx, tmdb):
    ctx["result"] = sync(ctx["repo"], "omdb-key", TODAY + timedelta(days=8), tmdb_token="tok")


@then(parsers.parse("the exit code is {code:d}"))
def exit_code(ctx, code):
    assert ctx["result"].exit_code == code


@then(parsers.parse("{n:d} films have OMDb ratings"))
def omdb_count(ctx, n):
    with sqlite3.connect(ctx["repo"].db_path) as c:
        assert c.execute("SELECT COUNT(*) FROM omdb WHERE found = 1").fetchone()[0] == n


@then(parsers.parse('"{title} ({year:d})" has external id "{value}" for authority "{authority}"'))
def has_external(ctx, title, year, value, authority):
    fid = ctx["repo"].film_id_by_key(f"{title.lower()} ({year})")
    assert ctx["repo"].external_ids_for(fid).get(authority) == value


@then(parsers.parse("the sync matched {n:d} TMDB films"))
def matched_n(ctx, n):
    assert ctx["result"].tmdb_matched == n


@then(parsers.parse("TMDB search was called exactly {n:d} times"))
def search_calls(tmdb, n):
    assert tmdb["search_calls"] == n


@then(parsers.parse("TMDB providers were called exactly {n:d} times"))
def provider_calls(tmdb, n):
    assert tmdb["provider_calls"] == n


@then(parsers.parse("the tmdb review queue holds {n:d} entries"))
def review_n(ctx, n):
    assert len(ctx["repo"].open_reviews("tmdb")) == n


@then(parsers.parse('the tmdb review queue holds a "{reason}" entry'))
def review_has_reason(ctx, reason):
    reasons = [r["reason"] for r in ctx["repo"].open_reviews("tmdb")]
    assert reason in reasons, f"no {reason!r} entry in {reasons}"


@then(parsers.parse('the tmdb review queue holds {n:d} "{reason}" entries'))
def review_reason_count(ctx, n, reason):
    got = sum(1 for r in ctx["repo"].open_reviews("tmdb") if r["reason"] == reason)
    assert got == n


@then(parsers.parse('the film "{title}" has year {year:d} and key "{key}"'))
def film_year_and_key(ctx, title, year, key):
    with sqlite3.connect(ctx["repo"].db_path) as c:
        row = c.execute("SELECT year, key FROM films WHERE key = ?", (key,)).fetchone()
    assert row is not None, f"no film with key {key!r}"
    assert row[0] == year


@then(parsers.parse('the film "{title}" from {orig_year:d} still has year {year:d}'))
def film_still_has_year(ctx, title, orig_year, year):
    fid = ctx["repo"].film_id_by_key(f"{title.lower()} ({orig_year})")
    assert fid is not None, f"no film with key {title.lower()} ({orig_year})"
    with sqlite3.connect(ctx["repo"].db_path) as c:
        row = c.execute("SELECT year FROM films WHERE id = ?", (fid,)).fetchone()
    assert row[0] == year


@then(parsers.parse('"{title} ({year:d})" is currently listed on "{slug}"'))
def currently_listed(ctx, title, year, slug):
    fid = ctx["repo"].film_id_by_key(f"{title.lower()} ({year})")
    assert fid in {i for i, _ in ctx["repo"].current_films(slug)}


@then(parsers.parse('"{title} ({year:d})" has {n:d} non-criterion listings'))
def listing_count(ctx, title, year, n):
    fid = ctx["repo"].film_id_by_key(f"{title.lower()} ({year})")
    with sqlite3.connect(ctx["repo"].db_path) as c:
        got = c.execute(
            "SELECT COUNT(*) FROM listings WHERE film_id = ? AND source != 'criterion'", (fid,)
        ).fetchone()[0]
    assert got == n


@then(parsers.parse('"{title} ({year:d})" still has a listing row for "{slug}"'))
def listing_survives(ctx, title, year, slug):
    fid = ctx["repo"].film_id_by_key(f"{title.lower()} ({year})")
    with sqlite3.connect(ctx["repo"].db_path) as c:
        assert (
            c.execute("SELECT 1 FROM listings WHERE film_id = ? AND source = ?", (fid, slug)).fetchone() is not None
        )


@then("the provider refresh stamp is unset")
def stamp_unset(ctx):
    assert ctx["repo"].get_meta(META_REFRESHED_AT) is None


@then("no availability transition is recorded")
def no_transitions(ctx):
    with sqlite3.connect(ctx["repo"].db_path) as c:
        # criterion catalog inserts are an untouched, separate concern (Task 5 only
        # changes TMDB-sourced writes) — scope to non-criterion sources.
        count = c.execute(
            "SELECT COUNT(*) FROM availability_transitions WHERE source != 'criterion'"
        ).fetchone()[0]
    assert count == 0


@then(parsers.parse('an availability transition for "{slug}" is recorded'))
def transition_for_slug(ctx, slug):
    with sqlite3.connect(ctx["repo"].db_path) as c:
        rows = c.execute("SELECT 1 FROM availability_transitions WHERE source = ?", (slug,)).fetchall()
    assert rows


@given(parsers.parse('TMDB already checked "{title} ({year:d})" as id {tid:d} once'))
def already_checked(ctx, title, year, tid):
    # Pre-match and pre-check (dated well before TODAY) so the sync under test is neither the
    # film's TMDB match nor its first-ever provider check.
    prior = date(2026, 1, 1)
    fid = ctx["repo"].film_id_by_key(f"{title.lower()} ({year})")
    if fid is None:  # the Background only declares the catalog; the film is recorded by sync
        ctx["repo"].record_catalog(SOURCE, parse_titles(f'"{title} ({year})"'), prior)
        fid = ctx["repo"].film_id_by_key(f"{title.lower()} ({year})")
    ctx["repo"].set_external_id(fid, "tmdb", str(tid), prior)
    ctx["repo"].upsert_tmdb(fid, found=True, looked_up=prior)
    ctx["repo"].record_tmdb_providers(fid, prior, "{}")


@given("OMDb answers only lookups by IMDb id")
def omdb_by_id_only(ctx):
    ctx["rs"].remove(responses.GET, OMDB_URL)

    def cb(request):
        q = parse_qs(urlparse(request.url).query)
        if "i" in q:
            return (200, {}, json.dumps(FOUND))
        return (200, {}, json.dumps({"Response": "False", "Error": "Movie not found!"}))

    ctx["rs"].add_callback(responses.GET, OMDB_URL, callback=cb)


@given(parsers.parse('TMDB reports id {tid:d} as IMDb "{imdb}"'))
def tmdb_imdb(ctx, tmdb, tid, imdb):
    ctx["rs"].get(f"{TMDB_API}/movie/{tid}/external_ids", json={"id": tid, "imdb_id": imdb})


@given(parsers.parse("TMDB reports id {tid:d} as having no IMDb id"))
def tmdb_no_imdb(ctx, tmdb, tid):
    ctx["rs"].get(f"{TMDB_API}/movie/{tid}/external_ids", json={"id": tid, "imdb_id": None})


def _omdb_found(ctx, title, year):
    fid = ctx["repo"].film_id_by_key(f"{title.lower()} ({year})")
    assert fid is not None
    conn = sqlite3.connect(ctx["repo"].db_path)
    row = conn.execute("SELECT found FROM omdb WHERE film_id = ?", (fid,)).fetchone()
    conn.close()
    return row is not None and row[0] == 1


@then(parsers.parse('"{title} ({year:d})" has an OMDb rating'))
def has_omdb(ctx, title, year):
    assert _omdb_found(ctx, title, year)


@then(parsers.parse('"{title} ({year:d})" has no OMDb rating'))
def has_no_omdb(ctx, title, year):
    assert not _omdb_found(ctx, title, year)


@then(parsers.parse('"{title} ({year:d})" has no external id for authority "{authority}"'))
def no_external_id(ctx, title, year, authority):
    fid = ctx["repo"].film_id_by_key(f"{title.lower()} ({year})")
    assert authority not in ctx["repo"].external_ids_for(fid)
