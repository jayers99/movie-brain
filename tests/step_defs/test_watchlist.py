from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, timedelta

import pytest
import responses
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.availability import META_REFRESHED_AT
from movie_brain.application.sync import SOURCE, sync
from movie_brain.domain.models import Film
from movie_brain.domain.thumbprint import Candidate
from movie_brain.infrastructure.criterion import API_URL, BROWSE_URL
from movie_brain.infrastructure.omdb import OMDB_URL
from movie_brain.infrastructure.tmdb import TMDB_API

scenarios("../features/watchlist.feature")

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


class PoolFetcher:
    """Stands in for CandidateFetcher: canned candidates per query title."""

    def __init__(self):
        self.pool: dict[str, list[Candidate]] = {}

    def fetch(self, q):
        return self.pool.get(q.title, [])


@pytest.fixture
def pool(ctx):
    ctx["pool"] = PoolFetcher()
    return ctx["pool"]


@pytest.fixture
def tmdb(ctx):
    """One mutable TMDB world: per-id providers and the provider call counter."""
    world = {"providers": {}, "provider_calls": 0}

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
def tmdb_knows(ctx, pool, tmdb, title, year, tid):
    """Shorthand for "the resolver keys this film to id N": one unambiguous candidate in
    the pool (tt synthesized from the id), the `movie_year` lookup `key_film` makes, and
    the provider callback. There is no TMDB title search any more (thumbprint T5)."""
    pool.pool[title] = [Candidate(f"tt{tid:07d}", tid, (title,), year, "Someone", 100, 5000, "movie", True, True)]
    if tid not in ctx["flags"].setdefault("movies_registered", set()):
        ctx["flags"]["movies_registered"].add(tid)
        ctx["rs"].add(responses.GET, f"{TMDB_API}/movie/{tid}", json={"id": tid, "release_date": f"{year}-01-01"})
    tmdb["register_providers"](tid)


@given(parsers.parse("TMDB streams id {tid:d} on providers {a:d} and {b:d}"))
def tmdb_streams(tmdb, tid, a, b):
    tmdb["providers"][tid] = {"link": f"https://tmdb/w/{tid}", "flatrate": [{"provider_id": a}, {"provider_id": b}]}


@given(parsers.parse("the provider refresh ran {days:d} days ago"))
def stamp(ctx, days):
    ctx["repo"].set_meta(META_REFRESHED_AT, (TODAY - timedelta(days=days)).isoformat())


@given(parsers.parse('"{title} ({year:d})" is on the watchlist'))
def on_watchlist(ctx, title, year):
    # The film must exist before it can be watchlisted: record it the way sync would.
    fid = ctx["repo"].film_id_by_key(f"{title.lower()} ({year})")
    if fid is None:
        ctx["repo"].record_catalog(SOURCE, parse_titles(f'"{title} ({year})"'), TODAY - timedelta(days=30))
        fid = ctx["repo"].film_id_by_key(f"{title.lower()} ({year})")
    ctx["repo"].toggle_watchlist(fid, TODAY)


@given(parsers.parse('TMDB already checked "{title} ({year:d})" as id {tid:d} once'))
def already_checked(ctx, tmdb, title, year, tid):
    # A film's FIRST-ever provider check is a quiet baseline (Task 5) — pre-match and
    # pre-check the film (dated well before TODAY) so the sync under test is not that
    # first check, and an arrival can actually be detected as a transition.
    fid = ctx["repo"].film_id_by_key(f"{title.lower()} ({year})")
    if fid is None:
        ctx["repo"].record_catalog(SOURCE, parse_titles(f'"{title} ({year})"'), TODAY - timedelta(days=30))
        fid = ctx["repo"].film_id_by_key(f"{title.lower()} ({year})")
    prior = date(2026, 1, 1)
    ctx["repo"].set_external_id(fid, "tmdb", str(tid), prior)
    ctx["repo"].upsert_tmdb(fid, found=True, looked_up=prior)
    ctx["repo"].record_tmdb_providers(fid, prior, "{}")
    tmdb["register_providers"](tid)


@when("I sync with a TMDB token")
def do_sync_tok(ctx, tmdb):
    ctx["result"] = sync(ctx["repo"], "omdb-key", TODAY, tmdb_token="tok", fetcher=ctx.get("pool"))


@when("I sync with a TMDB token again the next day")
def do_sync_next(ctx, tmdb):
    ctx["result"] = sync(
        ctx["repo"], "omdb-key", TODAY + timedelta(days=1), tmdb_token="tok", fetcher=ctx.get("pool")
    )


@then(parsers.parse("TMDB providers were called exactly {n:d} times"))
def provider_calls(tmdb, n):
    assert tmdb["provider_calls"] == n


@then(parsers.parse("the sync refreshed {n:d} watchlist films"))
def wl_refreshed(ctx, n):
    assert ctx["result"].tmdb_watchlist_refreshed == n


@then(parsers.parse('"{title} ({year:d})" has an availability transition on "{slug}"'))
def has_transition(ctx, title, year, slug):
    fid = ctx["repo"].film_id_by_key(f"{title.lower()} ({year})")
    with sqlite3.connect(ctx["repo"].db_path) as c:
        rows = c.execute(
            "SELECT 1 FROM availability_transitions WHERE film_id = ? AND source = ?", (fid, slug)
        ).fetchall()
    assert rows


@then(parsers.parse('"{title} ({year:d})" has {n:d} availability transitions'))
def transition_count(ctx, title, year, n):
    fid = ctx["repo"].film_id_by_key(f"{title.lower()} ({year})")
    with sqlite3.connect(ctx["repo"].db_path) as c:
        got = c.execute(
            "SELECT COUNT(*) FROM availability_transitions WHERE film_id = ? AND source != 'criterion'",
            (fid,),
        ).fetchone()[0]
    assert got == n


@when("I sync with a TMDB token and a notifier")
def do_sync_notify(ctx, tmdb):
    sent: list[tuple[str, str]] = []
    ctx["sent"] = sent
    ctx["result"] = sync(
        ctx["repo"],
        "omdb-key",
        TODAY,
        tmdb_token="tok",
        notifier=lambda t, b: sent.append((t, b)),
        fetcher=ctx.get("pool"),
    )


@then("one notification was sent")
def one_sent(ctx):
    assert len(ctx["sent"]) == 1


@then("no notification was sent")
def none_sent(ctx):
    assert ctx["sent"] == []


@then(parsers.parse('the notification mentions "{a}" and "{b}"'))
def mentions(ctx, a, b):
    (_, notification_body) = ctx["sent"][0]
    assert a in notification_body and b in notification_body


@then(parsers.parse('the notification does not mention "{a}"'))
def not_mentions(ctx, a):
    (_, notification_body) = ctx["sent"][0]
    assert a not in notification_body


@then(parsers.parse("the sync first-checked {n:d} films"))
def first_checked(ctx, n):
    assert ctx["result"].tmdb_first_checked == n


@then(parsers.parse('"{title} ({year:d})" is listed on "{slug}"'))
def listed_on(ctx, title, year, slug):
    fid = ctx["repo"].film_id_by_key(f"{title.lower()} ({year})")
    with sqlite3.connect(ctx["repo"].db_path) as c:
        assert c.execute("SELECT 1 FROM listings WHERE film_id = ? AND source = ?", (fid, slug)).fetchone()


@then(parsers.parse('no availability transition is recorded for "{slug}"'))
def no_transition_for(ctx, slug):
    with sqlite3.connect(ctx["repo"].db_path) as c:
        assert not c.execute("SELECT 1 FROM availability_transitions WHERE source = ?", (slug,)).fetchall()
