from __future__ import annotations

import json
import re
from datetime import date, timedelta

import pytest
import requests
import responses
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.sync import SOURCE, SyncResult, sync
from movie_brain.domain.models import Film
from movie_brain.infrastructure.criterion import API_URL, BROWSE_URL
from movie_brain.infrastructure.omdb import OMDB_URL

scenarios("../features/sync.feature")

TODAY = date(2026, 8, 19)
FOUND = {"Response": "True", "imdbRating": "7.0", "Language": "English", "Ratings": []}
LIMIT = {"Response": "False", "Error": "Request limit reached!"}


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


@given(
    parsers.re(
        r"the repository already holds (?P<films>.+?) walked (?P<days>\d+) days ago"
        r'(?: leaving "(?P<label>[^"]+)")?$'
    )
)
def preloaded(ctx, films, days, label):
    flist = parse_titles(films)
    walked = TODAY - timedelta(days=int(days))
    ctx["repo"].record_catalog(SOURCE, flist, walked)
    ctx["repo"].set_meta("films_fetched_at", walked.isoformat())
    if label:
        ctx["repo"].set_leaving(SOURCE, {f.key: label for f in flist})


@given(parsers.parse("the Criterion catalog has films {films}"))
def catalog(ctx, films):
    flist = parse_titles(films)
    ctx["catalog_films"] = flist

    def movies(request):
        return (
            200,
            {},
            json.dumps(
                {
                    "total": len(flist),
                    "_links": {"next": {"href": None}},
                    "_embedded": {"collections": [movie_item(f) for f in flist]},
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


@given(parsers.parse('the catalog also lists a year-less duplicate of "{title}"'))
def yearless_duplicate(ctx, title):
    ctx["catalog_films"].append(Film(title, None, "Someone", f"https://c/{title.lower()}-1"))


@given(parsers.parse("the raw catalog total is {n:d}"))
def raw_total(ctx, n):
    ctx["repo"].set_meta("films_raw_total", str(n))


@given("the Criterion API returns 500")
def api_down(ctx):
    ctx["rs"].get(API_URL, status=500)


@given("the leaving-soon categories endpoint returns 500")
def leaving_down(ctx):
    # Replace the callback registered by `catalog` with one that fails for categories only.
    ctx["rs"].remove(responses.GET, API_URL)
    flist = ctx.setdefault("catalog_films", [])

    def cb(request):
        if "type%5B%5D=movie" in request.url:
            return (
                200,
                {},
                json.dumps(
                    {
                        "total": len(flist),
                        "_links": {"next": {"href": None}},
                        "_embedded": {"collections": [movie_item(f) for f in flist]},
                    }
                ),
            )
        return (500, {}, "boom")

    ctx["rs"].add_callback(responses.GET, API_URL, callback=cb)


@given("OMDb knows every film")
def omdb_ok(ctx):
    ctx["rs"].get(OMDB_URL, json=FOUND)


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


def _run(ctx, **kw):
    ctx["result"] = sync(ctx["repo"], "key", TODAY, session=requests.Session(), delay_s=0, log=lambda m: None, **kw)


@when("I sync")
def run_sync(ctx):
    _run(ctx)


@when("I sync with --full")
def run_full(ctx):
    _run(ctx, force_full=True)


@when("I sync with --ratings-only")
def run_ro(ctx):
    _run(ctx, ratings_only=True)


@then(parsers.parse("the exit code is {code:d}"))
def exit_code(ctx, code):
    assert isinstance(ctx["result"], SyncResult)
    assert ctx["result"].exit_code == code


@then("the catalog walk was full")
def walk_full(ctx):
    assert ctx["result"].full_walk is True


@then("the catalog walk was cheap")
def walk_cheap(ctx):
    assert ctx["result"].full_walk is False


@then("only page 1 of the movie catalog was requested")
def only_page_one(ctx):
    movie_calls = [
        c for c in ctx["rs"].calls if c.request.url.startswith(API_URL) and "type%5B%5D=movie" in c.request.url
    ]
    assert len(movie_calls) == 1 and "page=1" in movie_calls[0].request.url


@then("Criterion was never contacted")
def no_criterion(ctx):
    assert not any(c.request.url.startswith((BROWSE_URL, API_URL)) for c in ctx["rs"].calls)


@then(parsers.parse("{n:d} films are current"))
def n_current(ctx, n):
    assert len(ctx["repo"].current_films(SOURCE)) == n


@then(parsers.parse("{n:d} films have OMDb ratings"))
def n_rated(ctx, n):
    assert sum(1 for v in ctx["repo"].list_views(SOURCE) if v.found is True) == n


@then("films_fetched_at is today")
def fetched_today(ctx):
    assert ctx["repo"].get_meta("films_fetched_at") == TODAY.isoformat()


@then(parsers.parse("films_fetched_at is {days:d} days ago"))
def fetched_days_ago(ctx, days):
    assert ctx["repo"].get_meta("films_fetched_at") == (TODAY - timedelta(days=days)).isoformat()


@then(parsers.parse('"{title}" is leaving "{label}"'))
def is_leaving(ctx, title, label):
    f = parse_titles(f'"{title}"')[0]
    view = ctx["repo"].get_view(ctx["repo"].film_id_by_key(f.key))
    assert view.leaving_date == label


@then("the quota flag is set")
def quota_flag(ctx):
    assert ctx["result"].quota_hit is True


@then("the failing flag is set")
def failing_flag(ctx):
    assert ctx["result"].failing is True
