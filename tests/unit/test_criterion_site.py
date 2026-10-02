"""The new Criterion Channel reader (2026-10 relaunch). Fixture shapes are the real captures in
tests/fixtures/criterion/ (copied from docs/superpowers/research/2026-10-01-criterion-relaunch/)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import requests
import responses

from movie_brain.infrastructure.cheapcharts import Pacer
from movie_brain.infrastructure.criterion_site import (
    CATALOG_URL,
    CatalogItem,
    CriterionError,
    fetch_catalog,
)

FIX = Path(__file__).parent.parent / "fixtures" / "criterion"


def _load(name: str):
    return json.loads((FIX / name).read_text())


def _page(items, next_key, total):
    """A catalog page in the captured shape: next key present on every page but the last."""
    first = _load("all-films-results.page1.trimmed.json")
    body = copy.deepcopy(first)
    body["items"] = items
    body["total"] = total
    if next_key is None:
        body["paging"] = {"page_limit": 200}  # the real last page: the key is ABSENT
    else:
        body["paging"] = {"next_pagination_key": next_key, "page_limit": 200}
    return body


def _no_sleep(_s):
    return None


@responses.activate
def test_walks_every_page_until_the_key_is_absent():
    first = _load("all-films-results.page1.trimmed.json")["items"]
    last = _load("all-films-results.lastpage.json")["items"]
    total = len(first) + len(last)
    responses.get(CATALOG_URL, json=_page(first, "2", total))
    responses.get(CATALOG_URL, json=_page(last, None, total))
    items = fetch_catalog(requests.Session(), sleep=_no_sleep)
    assert len(items) == total
    assert items[0] == CatalogItem("L5Z3RaiC", "2 or 3 Things I Know About Her", 1967, 5245)
    assert responses.calls[1].request.params == {"page_limit": "200", "pagination_key": "2"}


@responses.activate
def test_series_count_toward_total_but_are_not_films():
    film = {"contentType": "film", "duration": 100, "mediaid": "AAAAAAAA", "release_date": "1972-01-01", "title": "A"}
    series = {"contentType": "series", "duration": 0, "mediaid": "rLiSVzkD", "release_date": "1972-01-01", "title": "Lone Wolf and Cub"}
    responses.get(CATALOG_URL, json=_page([film, series], None, 2))
    items = fetch_catalog(requests.Session(), sleep=_no_sleep)
    assert [i.mediaid for i in items] == ["AAAAAAAA"]


@responses.activate
def test_a_repeated_mediaid_keeps_the_first():
    bad_timing = {"contentType": "film", "duration": 1439, "mediaid": "2hBeeBd5", "release_date": "1982-01-01", "title": "Bad Timing"}
    responses.get(CATALOG_URL, json=_page([bad_timing, dict(bad_timing)], None, 2))
    assert [i.title for i in fetch_catalog(requests.Session(), sleep=_no_sleep)] == ["Bad Timing"]


@responses.activate
def test_junk_years_become_none():
    items = [
        {"contentType": "film", "duration": 247, "mediaid": "dhNWDlG0", "release_date": "0-01-01", "title": "Another World"},
        {"contentType": "film", "duration": 3308, "mediaid": "olgaplBp", "release_date": "2915-01-01", "title": "The Universe Is Out There"},
    ]
    responses.get(CATALOG_URL, json=_page(items, None, 2))
    assert [i.year for i in fetch_catalog(requests.Session(), sleep=_no_sleep)] == [None, None]


@responses.activate
def test_raw_count_short_of_total_aborts():
    first = _load("all-films-results.page1.trimmed.json")["items"]
    responses.get(CATALOG_URL, json=_page(first, None, 3042))
    with pytest.raises(CriterionError, match="3042"):
        fetch_catalog(requests.Session(), sleep=_no_sleep)


@responses.activate
def test_a_repeated_cursor_aborts():
    first = _load("all-films-results.page1.trimmed.json")["items"]
    responses.get(CATALOG_URL, json=_page(first, "2", 99))
    responses.get(CATALOG_URL, json=_page(first, "2", 99))
    with pytest.raises(CriterionError, match="repeated"):
        fetch_catalog(requests.Session(), sleep=_no_sleep)


@responses.activate
def test_an_empty_page_aborts():
    responses.get(CATALOG_URL, json=_page([], None, 0))
    with pytest.raises(CriterionError, match="empty"):
        fetch_catalog(requests.Session(), sleep=_no_sleep)


@responses.activate
def test_429_backs_off_three_times_then_fails():
    for _ in range(4):
        responses.get(CATALOG_URL, status=429)
    slept: list[float] = []
    with pytest.raises(CriterionError, match="429"):
        fetch_catalog(requests.Session(), pacer=Pacer(0), sleep=slept.append)  # Pacer(0): only back-off sleeps
    assert slept == [2, 4, 8]


@responses.activate
def test_429_then_success_carries_on():
    first = _load("all-films-results.page1.trimmed.json")["items"]
    responses.get(CATALOG_URL, status=429)
    responses.get(CATALOG_URL, json=_page(first, None, len(first)))
    assert len(fetch_catalog(requests.Session(), sleep=_no_sleep)) == len(first)


@responses.activate
def test_sends_the_user_agent():
    first = _load("all-films-results.page1.trimmed.json")["items"]
    responses.get(CATALOG_URL, json=_page(first, None, len(first)))
    fetch_catalog(requests.Session(), sleep=_no_sleep)
    assert responses.calls[0].request.headers["User-Agent"] == "movie-brain/0.1 (personal watchlist tool)"
