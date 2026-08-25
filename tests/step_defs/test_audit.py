from __future__ import annotations

import json
import re
from datetime import date

import pytest
import requests
import responses
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.audit import run_audit
from movie_brain.domain.models import Film, OmdbRating
from movie_brain.infrastructure.tmdb import TMDB_API, TmdbClient

scenarios("../features/audit.feature")
TODAY = date(2026, 8, 24)


def _key(spec: str) -> str:
    m = re.fullmatch(r"(.+) \((\d{4})\)", spec)
    assert m
    return f"{m.group(1).lower()} ({m.group(2)})"


@pytest.fixture
def ctx(repo):
    rs = responses.RequestsMock(assert_all_requests_are_fired=False)
    rs.start()
    yield {"repo": repo, "rs": rs, "report": None}
    rs.stop()
    rs.reset()


@given("a fresh repository")
def fresh(ctx):
    pass


@given(parsers.parse('a Criterion film "{spec}" directed by "{director}" linked to TMDB id {tid:d}'))
def crit_film(ctx, spec, director, tid):
    m = re.fullmatch(r"(.+) \((\d{4})\)", spec)
    ctx["repo"].record_catalog("criterion", [Film(m.group(1), int(m.group(2)), director, "https://c/x")], TODAY)
    ctx["repo"].set_external_id(ctx["repo"].film_id_by_key(_key(spec)), "tmdb", str(tid), TODAY)


@given(parsers.parse('"{spec}" has an OMDb payload titled "{title}" year {year:d} imdb "{imdb}" director "{director}"'))
def omdb_payload(ctx, spec, title, year, imdb, director):
    payload = json.dumps({"Title": title, "Year": str(year), "imdbID": imdb, "Director": director, "Type": "movie", "imdbRating": "7.0"})
    ctx["repo"].upsert_omdb(ctx["repo"].film_id_by_key(_key(spec)), OmdbRating(7.0, None, True, "English", payload), TODAY)


@given(parsers.parse('TMDB facts for id {tid:d} are title "{title}" imdb "{imdb}" runtime {rt:d}'))
def tmdb_facts(ctx, tid, title, imdb, rt):
    ctx["rs"].get(
        f"{TMDB_API}/movie/{tid}",
        json={"title": title, "original_title": title, "release_date": "1950-01-01", "runtime": rt,
              "alternative_titles": {"titles": []}, "external_ids": {"imdb_id": imdb}},
    )


@given(parsers.parse("TMDB facts for id {tid:d} fail with a server error"))
def tmdb_fail(ctx, tid):
    ctx["rs"].get(f"{TMDB_API}/movie/{tid}", status=500, body="boom")


def _run(ctx, with_tmdb: bool):
    client = TmdbClient("tok", session=requests.Session()) if with_tmdb else None
    ctx["report"] = run_audit(ctx["repo"], TODAY, tmdb=client, delay_s=0, log=lambda m: None)


@when("I run the audit")
@when("I run the audit again")
def run_with(ctx):
    _run(ctx, True)


@when("I run the audit without TMDB")
def run_without(ctx):
    _run(ctx, False)


@when(parsers.re(r'I mark "(?P<spec>[^"]+)" as "(?P<verdict>[^"]+)" with note "(?P<note>[^"]*)"'))
def mark(ctx, spec, verdict, note):
    r = ctx["repo"]
    fid = r.film_id_by_key(_key(spec))
    r.add_verdict(fid, verdict, r.current_reasons(fid), note or None, TODAY)


@then(parsers.parse("the audit fetched {n:d} TMDB facts"))
def fetched(ctx, n):
    assert ctx["report"].facts_fetched == n


@then(parsers.parse("the audit fetched {n:d} TMDB facts and {m:d} failed"))
def fetched_failed(ctx, n, m):
    assert (ctx["report"].facts_fetched, ctx["report"].facts_failed) == (n, m)


@then("no TMDB request was made")
def no_tmdb(ctx):
    assert not any(TMDB_API in c.request.url for c in ctx["rs"].calls)


@then(parsers.re(r'"(?P<spec>[^"]+)" is flagged with reasons "(?P<reasons>[^"]*)"'))
def flagged(ctx, spec, reasons):
    got = ctx["repo"].current_reasons(ctx["repo"].film_id_by_key(_key(spec)))
    assert got == ([r.strip() for r in reasons.split(",")] if reasons else [])


@then(parsers.parse("the audit exit code is {code:d}"))
def exit_code(ctx, code):
    assert ctx["report"].exit_code == code


@then(parsers.parse('the verdict history is "{expected}"'))
def history(ctx, expected):
    assert [r[3] for r in ctx["repo"].verdict_history()] == [v.strip() for v in expected.split(",")]
