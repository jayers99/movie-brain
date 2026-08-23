from __future__ import annotations

import json
from datetime import date

import pytest
import requests
import responses
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.metacritic import crawl_archive
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
