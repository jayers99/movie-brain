"""Sync over HTTP with the real capture shapes (tests/fixtures/criterion/): the catalog, the
home page, the leaving page, the JW playlist and the JW media record are served by `responses`
and read by the real `HttpCriterionSite` (no pacing sleeps)."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest
import requests
import responses
from criterion_fakes import mediaid_for
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application import sync as sync_module
from movie_brain.application.sync import SOURCE, SyncResult, sync
from movie_brain.domain.models import Film
from movie_brain.domain.thumbprint import Candidate
from movie_brain.infrastructure.criterion_site import (
    BASE,
    CATALOG_URL,
    JW_PLAYLIST_URL,
    HttpCriterionSite,
)
from movie_brain.infrastructure.database import Repository
from movie_brain.infrastructure.omdb import OMDB_URL
from movie_brain.infrastructure.tmdb import TMDB_API

scenarios("../features/sync.feature")

TODAY = date(2026, 8, 19)
FOUND = {"Response": "True", "imdbRating": "7.0", "Language": "English", "Ratings": []}
LIMIT = {"Response": "False", "Error": "Request limit reached!"}
FIX = Path(__file__).parent.parent / "fixtures" / "criterion"
HOME_NO_DATED = '<html><a href="/discover/leaving-soon">Leaving soon</a></html>'
JW_MEDIA = re.compile(r"https://cdn\.jwplayer\.com/v2/media/(\w+)")
TABLES = ("films", "listings", "external_ids", "claim", "match_review", "availability_transitions")


def _load(name):
    return json.loads((FIX / name).read_text())


def parse_titles(text: str) -> list[Film]:
    films = []
    for m in re.finditer(r'"([^"(]+) \((\d{4})\)"', text):
        title, year = m.group(1), int(m.group(2))
        films.append(Film(title, year, "Someone", f"https://www.criterionchannel.com/{title.lower()}"))
    return films


def _q(ctx, sql, *args):
    conn = sqlite3.connect(ctx["repo"].db_path)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def _snapshot(ctx):
    return {t: _q(ctx, f"SELECT * FROM {t} ORDER BY rowid") for t in TABLES}


@pytest.fixture
def ctx(repo, config_dir, nuxt_page, monkeypatch):
    rs = responses.RequestsMock(assert_all_requests_are_fired=False)
    rs.start()
    world = {
        "items": [],  # dicts in the captured catalog-item shape
        "catalog_status": 200,
        "home": HOME_NO_DATED,
        "home_status": 200,
        "jw": {},  # mediaid → captured-shape body
        "jw_status": {},
        "jw_calls": [],
    }

    def catalog_cb(request):
        if world["catalog_status"] != 200:
            return (world["catalog_status"], {}, "boom")
        body = _load("all-films-results.lastpage.json")  # the real last page: no next key
        body["items"] = list(world["items"])
        body["total"] = len(body["items"])
        return (200, {}, json.dumps(body))

    def jw_cb(request):
        mediaid = JW_MEDIA.match(request.url).group(1)
        world["jw_calls"].append(mediaid)
        if mediaid in world["jw_status"]:
            return (world["jw_status"][mediaid], {}, "boom")
        if mediaid not in world["jw"]:
            return (404, {}, json.dumps({"message": f"['{mediaid}']: id not found in index."}))
        return (200, {}, json.dumps(world["jw"][mediaid]))

    rs.add_callback(responses.GET, CATALOG_URL, callback=catalog_cb)
    rs.add_callback(responses.GET, BASE + "/", callback=lambda r: (world["home_status"], {}, world["home"]))
    rs.add_callback(responses.GET, JW_MEDIA, callback=jw_cb)
    yield {
        "repo": repo, "rs": rs, "result": None, "config_dir": config_dir, "nuxt_page": nuxt_page,
        "mc_cards": [], "world": world, "ids": {}, "monkeypatch": monkeypatch, "day": TODAY,
    }
    rs.stop()
    rs.reset()


def _mediaid(ctx, title):
    return ctx["ids"].get(title) or mediaid_for(title)


def _item(mediaid, title, year):
    return {"contentType": "film", "duration": 5400, "mediaid": mediaid, "release_date": f"{year}-01-01", "title": title}


def _fid(ctx, title_year):
    f = parse_titles(f'"{title_year}"')[0]
    return ctx["repo"].film_id_by_key(f.key)


@given("a fresh repository")
def fresh(ctx):
    pass


@given("the Criterion home page links no dated leaving page")
def home_no_dated(ctx):
    ctx["world"]["home"] = HOME_NO_DATED


@given("the Criterion home page links the October 31 leaving page")
def home_dated(ctx):
    ctx["world"]["home"] = (FIX / "home-2026-10-01.html").read_text()
    ctx["rs"].get(BASE + "/discover/leaving-october-31", body=(FIX / "leaving-october-31.html").read_text())
    ctx["rs"].get(JW_PLAYLIST_URL.format("0WbeKrrA"), json=_load("jw-playlist.0WbeKrrA.full.json"))


@given("the Criterion home page answers 500")
def home_500(ctx):
    ctx["world"]["home_status"] = 500


@given("the Criterion catalog answers 500")
def catalog_500(ctx):
    ctx["world"]["catalog_status"] = 500


@given(parsers.parse('Criterion calls "{title_year}" "{mediaid}"'))
def criterion_calls(ctx, title_year, mediaid):
    ctx["ids"][parse_titles(f'"{title_year}"')[0].title] = mediaid


def _seed(ctx, films):
    """As `criterion bridge --apply` leaves them: each film holds its mediaid."""
    for f in films:
        fid = ctx["repo"].upsert_film(f)
        ctx["repo"].set_external_id(fid, "criterion", _mediaid(ctx, f.title), TODAY - timedelta(days=30))


@given(parsers.re(r"the last walk listed (?P<films>.+?) (?P<days>\d+) days ago(?P<old> under its old link)?$"))
def last_walk(ctx, films, days, old):
    flist = parse_titles(films)
    walked = TODAY - timedelta(days=int(days))
    if old:
        ctx["repo"].record_catalog(SOURCE, flist, walked)  # the VHX-era shape: old link, no mediaid
    else:
        _seed(ctx, flist)
        for f in flist:
            m = _mediaid(ctx, f.title)
            ctx["repo"].record_listing(_fid(ctx, f"{f.title} ({f.year})"), SOURCE, f"{BASE}/films/{m}/x", walked)
    ctx["repo"].set_meta("films_fetched_at", walked.isoformat())


@given(parsers.parse("Criterion lists my films {films}"))
def lists_my_films(ctx, films):
    flist = parse_titles(films)
    _seed(ctx, flist)
    ctx["world"]["items"] = [_item(_mediaid(ctx, f.title), f.title, f.year) for f in flist]


@given(parsers.parse('Criterion also lists a new film "{title}" ({year:d}) as "{mediaid}"'))
def lists_new(ctx, title, year, mediaid):
    ctx["world"]["items"].append(_item(mediaid, title, year))


@given(parsers.parse('the catalog also carries the series "{title}" as "{mediaid}"'))
def lists_series(ctx, title, mediaid):
    ctx["world"]["items"].append(
        {"contentType": "series", "duration": 0, "mediaid": mediaid, "release_date": "1972-01-01", "title": title}
    )


@given(parsers.parse('JW Player serves its captured record for "{mediaid}"'))
def jw_captured(ctx, mediaid):
    ctx["world"]["jw"][mediaid] = _load(f"jw-media.{mediaid}.json")


@given(parsers.parse('JW Player answers 500 for "{mediaid}"'))
def jw_500(ctx, mediaid):
    ctx["world"]["jw_status"][mediaid] = 500


@given(parsers.parse('"{title_year}" is leaving "{label}"'))
def is_leaving_given(ctx, title_year, label):
    conn = sqlite3.connect(ctx["repo"].db_path)
    conn.execute("UPDATE listings SET leaving_date = ? WHERE film_id = ? AND source = 'criterion'",
                 (label, _fid(ctx, title_year)))
    conn.commit()
    conn.close()


@given(parsers.parse('"{title_year}" is on the watchlist'))
def on_watchlist(ctx, title_year):
    f = parse_titles(f'"{title_year}"')[0]
    fid = ctx["repo"].film_id_by_key(f.key) or ctx["repo"].create_film(f)
    ctx["repo"].toggle_watchlist(fid, TODAY)


@given(parsers.parse('I have rated "{title}"'))
def rated(ctx, title):
    assert ctx["repo"].set_rating(_fid(ctx, title), 7, TODAY) is True


@given("OMDb knows every film")
def omdb_ok(ctx):
    ctx["rs"].get(OMDB_URL, json=FOUND)


@given("the resolver keys every film")
def resolver_keys_all(ctx):
    """A pool that answers any query with a synthetic keyed candidate, so the OMDb loop
    has an IMDb id to look up (T5: no id, no OMDb record)."""

    class AllFetcher:
        def fetch(self, q):
            tt = f"tt{abs(hash(q.title)) % 9000000:07d}"
            tid = abs(hash(q.title)) % 90000
            # release_date echoes the query's own year — a commerce (no-listing) film like a
            # Metacritic promotion gets its year adopted from this TMDB response (key_film →
            # movie_year), so a mismatched hardcoded year here would rename its key underfoot.
            ctx["rs"].add(
                responses.GET, f"{TMDB_API}/movie/{tid}", json={"id": tid, "release_date": f"{q.year or 1900}-01-01"}
            )
            return [Candidate(tt, tid, (q.title,), q.year, "Someone", 100, 5000, "movie", True, True)]

    ctx["pool"] = AllFetcher()


@given("the resolver finds nothing")
def resolver_nothing(ctx):
    class EmptyFetcher:
        def fetch(self, q):
            return []

    ctx["pool"] = EmptyFetcher()


@given(parsers.parse('"{title_year}" is already keyed to imdb "{tt}"'))
def already_keyed(ctx, title_year, tt):
    """A film keyed on a prior night — `--ratings-only` never keys, so a ratings-only scenario
    needs its film pre-keyed to have anything for the OMDb-by-id loop to look up."""
    ctx["repo"].set_external_id(_fid(ctx, title_year), "imdb", tt, TODAY)


@given("OMDb answers once then reports the request limit")
def omdb_quota(ctx):
    ctx["rs"].get(OMDB_URL, json=FOUND)
    ctx["rs"].get(OMDB_URL, json=LIMIT, status=401)


@given("OMDb rejects the API key")
def omdb_auth(ctx):
    ctx["rs"].get(OMDB_URL, json={"Response": "False", "Error": "Invalid API key!"}, status=401)


@given("OMDb answers once then errors repeatedly")
def omdb_repeated_failures(ctx):
    calls = {"n": 0}

    def cb(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return (200, {}, json.dumps(FOUND))
        return (500, {}, "boom")

    ctx["rs"].add_callback(responses.GET, OMDB_URL, callback=cb)


@given(
    parsers.re(
        r'the metacritic archive holds "(?P<title>[^"]+)" \((?P<year>\d+)\) scored (?P<score>\d+) as "(?P<slug>[^"]+)"'
    )
)
def metacritic_archive(ctx, title, year, score, slug):
    from movie_brain.infrastructure.metacritic import archive_dir, page_path

    ctx["mc_cards"].append((title, slug, int(year), int(score)))
    p = page_path(archive_dir(ctx["config_dir"]), 1)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(ctx["nuxt_page"](ctx["mc_cards"]))


@given("the walk's write fails at its last step")
def write_fails(ctx):
    def boom(c, leaving, day):
        raise RuntimeError("disk full")

    ctx["monkeypatch"].setattr(Repository, "_walk_leaving", staticmethod(boom))
    real_key_films = sync_module.key_films

    def watching_key_films(*args, **kwargs):
        ctx["at_keying"] = _snapshot(ctx)
        return real_key_films(*args, **kwargs)

    ctx["monkeypatch"].setattr(sync_module, "key_films", watching_key_films)


def _run(ctx, **kw):
    ctx["before"] = _snapshot(ctx)
    ctx["result"] = sync(
        ctx["repo"],
        "key",
        ctx["day"],
        session=requests.Session(),
        site=HttpCriterionSite(requests.Session(), sleep=lambda _s: None),
        log=lambda m: None,
        fetcher=ctx.get("pool"),
        tmdb_token="tok" if ctx.get("pool") else None,
        **kw,
    )


@when("I sync")
def run_sync(ctx):
    _run(ctx)


@when("I sync again the next day")
def run_sync_next_day(ctx):
    ctx["day"] = ctx["day"] + timedelta(days=1)
    _run(ctx)


@when("I sync with a metacritic archive")
def run_sync_with_archive(ctx):
    _run(ctx, config_dir=ctx["config_dir"])


@when("I sync with a notifier")
def run_sync_notify(ctx):
    ctx["sent"] = []
    _run(ctx, notifier=lambda t, b: ctx["sent"].append((t, b)))


def _chain(ctx, fail=False):
    from movie_brain.application.catch_up import CatchUpReport

    def chain(repo, tmdb):
        ctx.setdefault("chain_runs", []).append(repo.summary("criterion")["rated"])
        if fail:
            raise RuntimeError("chain exploded")
        return CatchUpReport()

    return chain


@when("I sync with a catch-up chain")
def run_with_chain(ctx):
    _run(ctx, catch_up=_chain(ctx))


@when("I sync with a catch-up chain that fails")
def run_with_failing_chain(ctx):
    _run(ctx, catch_up=_chain(ctx, fail=True))


@when("I sync with --ratings-only and a catch-up chain")
def run_ro_with_chain(ctx):
    _run(ctx, ratings_only=True, catch_up=_chain(ctx))


@when("I run the after-add enrichment with a catch-up chain")
def run_after_add(ctx):
    _run(ctx, skip_catalog=True, catch_up=_chain(ctx))


@when("I sync with --ratings-only")
def run_ro(ctx):
    _run(ctx, ratings_only=True)


@then(parsers.parse("the catch-up chain ran once, after {n:d} films had OMDb ratings"))
def chain_ran(ctx, n):
    assert ctx.get("chain_runs") == [n]


@then("the catch-up chain never ran")
def chain_never(ctx):
    assert "chain_runs" not in ctx


@then("the sync result carries the catch-up report")
def result_carries(ctx):
    assert ctx["result"].catch_up is not None


@then(parsers.parse("the exit code is {code:d}"))
def exit_code(ctx, code):
    assert isinstance(ctx["result"], SyncResult)
    assert ctx["result"].exit_code == code


@then(parsers.parse("the sync reports criterion arrived {a:d}, left {d:d}, to review {r:d}"))
def criterion_counts(ctx, a, d, r):
    res = ctx["result"]
    assert res.criterion_walked is True
    assert (res.criterion_arrived, res.criterion_departed, res.criterion_reviews) == (a, d, r)


@then("the sync reports the Criterion walk failed")
def criterion_failed(ctx):
    assert ctx["result"].criterion_failed is True and ctx["result"].criterion_walked is False


@then("Criterion was never contacted")
def no_criterion(ctx):
    assert not any(
        c.request.url.startswith((BASE, "https://cdn.jwplayer.com")) for c in ctx["rs"].calls
    )


@then(parsers.parse("{n:d} films are current"))
def n_current(ctx, n):
    assert len(ctx["repo"].current_films(SOURCE)) == n


@then(parsers.parse("{n:d} films have OMDb ratings"))
def n_rated(ctx, n):
    assert sum(1 for v in ctx["repo"].list_views(SOURCE) if v.found is True) == n


@then("films_fetched_at is today")
def fetched_today(ctx):
    assert ctx["repo"].get_meta("films_fetched_at") == TODAY.isoformat()


@then(parsers.parse('"{title_year}" is leaving "{label}"'))
def is_leaving(ctx, title_year, label):
    assert ctx["repo"].get_view(_fid(ctx, title_year)).leaving_date == label


@then(parsers.parse('"{title_year}" is not leaving'))
def not_leaving(ctx, title_year):
    assert _q(ctx, "SELECT leaving_date FROM listings WHERE film_id = ? AND source = 'criterion'",
              _fid(ctx, title_year)) == [(None,)]


@then(parsers.parse('"{title_year}" is still in the database'))
def film_kept(ctx, title_year):
    assert _fid(ctx, title_year) is not None


@then(parsers.parse('"{title_year}" is in the dashboard marked departed'))
def film_departed(ctx, title_year):
    f = parse_titles(f'"{title_year}"')[0]
    views = {v.title: v.departed for v in ctx["repo"].list_views(SOURCE)}
    assert views.get(f.title) is True


@then(parsers.parse('one notification was sent naming "{text}"'))
def one_notification(ctx, text):
    assert len(ctx["sent"]) == 1 and text in ctx["sent"][0][1]


@then(parsers.parse("there are {n:d} open criterion reviews"))
def n_open_criterion(ctx, n):
    assert len(ctx["repo"].open_reviews("criterion")) == n


@then(parsers.parse('there is {n:d} open criterion "{reason}" review for "{mediaid}"'))
def n_open_reason(ctx, n, reason, mediaid):
    rows = [r for r in ctx["repo"].open_reviews("criterion") if r["reason"] == reason and r["value"] == mediaid]
    assert len(rows) == n


@then(parsers.parse('the Criterion listing of "{title_year}" was last seen {days:d} days ago'))
def last_seen(ctx, title_year, days):
    assert _q(ctx, "SELECT last_seen FROM listings WHERE film_id = ? AND source = 'criterion'",
              _fid(ctx, title_year)) == [((TODAY - timedelta(days=days)).isoformat(),)]


@then("when the keying step began, Criterion was exactly as it was before the sync")
def unchanged_at_keying(ctx):
    assert ctx["at_keying"] == ctx["before"]


@then(parsers.parse('no film is titled "{title}"'))
def no_film_titled(ctx, title):
    assert _q(ctx, "SELECT COUNT(*) FROM films WHERE title = ?", title) == [(0,)]


@then(parsers.parse('JW Player was asked about "{mediaid}" {n:d} time'))
def jw_asked(ctx, mediaid, n):
    assert ctx["world"]["jw_calls"].count(mediaid) == n


@then("the quota flag is set")
def quota_flag(ctx):
    assert ctx["result"].quota_hit is True


@then("the failing flag is set")
def failing_flag(ctx):
    assert ctx["result"].failing is True


@then(parsers.parse('the repository holds a film for key "{key}"'))
def holds_film_key(ctx, key):
    assert ctx["repo"].film_id_by_key(key) is not None


@then(parsers.parse('the film for key "{key}" has an OMDb rating'))
def film_has_omdb(ctx, key):
    fid = ctx["repo"].film_id_by_key(key)
    assert fid is not None
    assert _q(ctx, "SELECT found FROM omdb WHERE film_id = ?", fid) == [(1,)]
