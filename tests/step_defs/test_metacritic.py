from __future__ import annotations

import json
from collections import defaultdict
from datetime import date

import pytest
import requests
import responses
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.metacritic import crawl_archive, match_archive, promote_top_n
from movie_brain.domain.models import Film, OmdbRating
from movie_brain.infrastructure.metacritic import BROWSE_URL, archive_dir, archived_pages, page_path

scenarios("../features/metacritic.feature")

TODAY = date(2026, 8, 19)


@pytest.fixture
def ctx(repo, config_dir, nuxt_page):
    rs = responses.RequestsMock(assert_all_requests_are_fired=False)
    rs.start()
    yield {
        "repo": repo,
        "config_dir": config_dir,
        "rs": rs,
        "nuxt_page": nuxt_page,
        "crawl": None,
        "report": None,
        "cards": [],
        "pages": defaultdict(list),
    }
    rs.stop()
    rs.reset()


def _page_cards(page: int) -> list[tuple[str, str, int | None, int | None]]:
    # Deterministic distinct cards per page; scores descend with page number.
    return [(f"Film P{page}", f"film-p{page}", 2000 + page, 99 - page)]


@given(parsers.parse("Metacritic serves {n:d} browse pages"))
def mc_pages(ctx, n):
    def cb(request):
        page = int(request.params.get("page", "1"))
        if page > n:
            return (404, {}, "not found")
        return (200, {}, ctx["nuxt_page"](_page_cards(page)))

    ctx["rs"].add_callback(responses.GET, BROWSE_URL, callback=cb)


@given("Metacritic serves page 1 then errors")
def mc_then_errors(ctx):
    def cb(request):
        page = int(request.params.get("page", "1"))
        if page == 1:
            return (200, {}, ctx["nuxt_page"](_page_cards(1)))
        return (500, {}, "boom")

    ctx["rs"].add_callback(responses.GET, BROWSE_URL, callback=cb)


@given("Metacritic serves pages without title cards")
def mc_botwall(ctx):
    ctx["rs"].add_callback(responses.GET, BROWSE_URL, callback=lambda r: (200, {}, "<html>captcha</html>"))


@given("pages 1 and 2 are already archived")
def pre_archived(ctx):
    archive = archive_dir(ctx["config_dir"])
    for page in (1, 2):
        p = page_path(archive, page)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(ctx["nuxt_page"](_page_cards(page)))


@when(parsers.parse("I crawl {n:d} pages"))
def run_crawl(ctx, n):
    ctx["crawl"] = crawl_archive(
        ctx["config_dir"], n, session=requests.Session(), delay_s=0, log=lambda m: None
    )


@then(parsers.parse("the crawl exit code is {code:d}"))
def crawl_exit(ctx, code):
    assert ctx["crawl"].exit_code == code


@then(parsers.parse("{n:d} pages are archived"))
def n_archived(ctx, n):
    assert len(archived_pages(archive_dir(ctx["config_dir"]))) == n


@then(parsers.parse("the fetch log records {n:d} fetches"))
def fetch_log(ctx, n):
    log = archive_dir(ctx["config_dir"]) / "fetch-log.jsonl"
    entries = [json.loads(line) for line in log.read_text().splitlines()]
    assert len(entries) == n
    assert all({"page", "url", "fetched_at", "status"} <= e.keys() for e in entries)


@then("only page 3 was fetched from the network")
def only_page_three(ctx):
    calls = [c for c in ctx["rs"].calls if c.request.url.startswith(BROWSE_URL)]
    assert len(calls) == 1 and "page=3" in calls[0].request.url


def _film(title_year: str) -> Film:
    # "Seven Samurai (1954)" → Film
    import re as _re

    m = _re.match(r"(.+) \((\d{4})\)$", title_year)
    assert m
    return Film(m.group(1), int(m.group(2)), "Someone", f"https://c/{m.group(1).lower()}")


@given(parsers.parse('the repository holds the film "{title_year}"'))
def holds_film(ctx, title_year):
    ctx["repo"].upsert_film(_film(title_year))


@given(parsers.parse('the repository holds the film "{title_year}" with OMDb metascore {score:d}'))
def holds_film_with_mc(ctx, title_year, score):
    f = _film(title_year)
    fid = ctx["repo"].upsert_film(f)
    ctx["repo"].upsert_omdb(fid, OmdbRating(None, None, True, metacritic=score), TODAY)


@given(parsers.parse('the film "{title_year}" already claims metacritic slug "{slug}"'))
def film_claims_slug(ctx, title_year, slug):
    fid = ctx["repo"].upsert_film(_film(title_year))
    ctx["repo"].set_external_id(fid, "metacritic", slug, TODAY)


@given(parsers.re(r'the archive holds "(?P<title>[^"]+)" \((?P<year>\d+)\) scored (?P<score>\d+) as "(?P<slug>[^"]+)"$'))
def archive_holds(ctx, title, year, score, slug):
    ctx["cards"].append((title, slug, int(year), int(score)))


@given(
    parsers.re(
        r'the archive holds "(?P<title>[^"]+)" \((?P<year>\d+)\) scored (?P<score>\d+) '
        r'as "(?P<slug>[^"]+)" on page (?P<page>\d+)'
    )
)
def archive_holds_on_page(ctx, title, year, score, slug, page):
    ctx["pages"][int(page)].append((title, slug, int(year), int(score)))


@given(
    parsers.re(
        r'the archive page (?P<page>\d+) has "(?P<title>[^"]+)" slug "(?P<slug>[^"]+)" '
        r"(?P<year>\d+) score (?P<score>\d+)"
    )
)
def archive_page_has(ctx, page, title, slug, year, score):
    ctx["pages"][int(page)].append((title, slug, int(year), int(score)))


def _write_archive(ctx):
    archive = archive_dir(ctx["config_dir"])
    if ctx["cards"]:
        p = page_path(archive, 1)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(ctx["nuxt_page"](ctx["cards"]))
    for page, cards in ctx["pages"].items():
        p = page_path(archive, page)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(ctx["nuxt_page"](cards))


@when("I match")
def run_match(ctx):
    _write_archive(ctx)
    ctx["report"] = match_archive(ctx["repo"], ctx["config_dir"], TODAY, log=lambda m: None)


@when(parsers.parse("I promote the top {n:d}"))
def run_promote(ctx, n):
    _write_archive(ctx)
    ctx["report"] = promote_top_n(ctx["repo"], ctx["config_dir"], TODAY, n, log=lambda m: None)


@then(parsers.parse('"{title_year}" has metacritic slug "{slug}"'))
def has_slug(ctx, title_year, slug):
    fid = ctx["repo"].film_id_by_key(_film(title_year).key)
    assert ctx["repo"].external_ids_for(fid).get("metacritic") == slug


@then(parsers.parse('"{title_year}" has no metacritic slug'))
def has_no_slug(ctx, title_year):
    fid = ctx["repo"].film_id_by_key(_film(title_year).key)
    assert "metacritic" not in ctx["repo"].external_ids_for(fid)


@then(parsers.parse("the coverage report says {matched:d} of {films:d} films matched"))
def report_coverage(ctx, matched, films):
    assert ctx["report"].matched == matched and ctx["report"].films == films


@then(parsers.re(r'the review queue has an? "(?P<reason>[^"]+)" entry(?: for "(?P<title_year>[^"]+)")?'))
def review_entry(ctx, reason, title_year):
    rows = ctx["repo"].open_reviews("metacritic")
    hits = [r for r in rows if r["reason"] == reason]
    assert hits, f"no {reason!r} in {rows}"
    if title_year:
        fid = ctx["repo"].film_id_by_key(_film(title_year).key)
        assert any(r["film_id"] == fid for r in hits)


@then(parsers.parse("the review queue has {n:d} open entries"))
def review_count(ctx, n):
    assert len(ctx["repo"].open_reviews("metacritic")) == n


@then("no film was deleted")
def nothing_deleted(ctx):
    assert len(ctx["repo"].films_for_matching()) == 2


@then(parsers.parse("the match exit code is {code:d}"))
def match_exit(ctx, code):
    assert ctx["report"].exit_code == code


@then(parsers.parse('the film "{title_year}" exists with a guid'))
def film_exists_with_guid(ctx, title_year):
    import sqlite3 as _sqlite3

    fid = ctx["repo"].film_id_by_key(_film(title_year).key)
    assert fid is not None
    conn = _sqlite3.connect(ctx["repo"].db_path)
    guid = conn.execute("SELECT guid FROM films WHERE id = ?", (fid,)).fetchone()[0]
    conn.close()
    assert guid


@then(parsers.parse("the repository holds {n:d} films"))
def repository_film_count(ctx, n):
    assert len(ctx["repo"].films_for_matching()) == n


@then(parsers.parse("the promote report says {n:d} promoted"))
def promote_count(ctx, n):
    assert ctx["report"].promoted == n


@then(parsers.parse('"{title_year}" has a "{authority}" claim titled "{ingested}" for year {year:d}'))
def has_claim(ctx, title_year, authority, ingested, year):
    fid = ctx["repo"].film_id_by_key(_film(title_year).key)
    claims = [c for c in ctx["repo"].claims_for_film(fid) if c.authority == authority]
    assert claims, f"no {authority} claim on #{fid}"
    assert (claims[0].title_ingested, claims[0].year_claimed) == (ingested, year)
    ctx["claim"] = claims[0]
