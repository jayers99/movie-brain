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
    BASE,
    CATALOG_URL,
    CatalogItem,
    CriterionError,
    JW_MEDIA_URL,
    JW_PLAYLIST_URL,
    JwMedia,
    Leaving,
    fetch_catalog,
    fetch_leaving,
    fetch_media,
    label_from_slug,
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


@responses.activate
def test_media_record_decodes_its_json_string_lists():
    responses.get(JW_MEDIA_URL.format("L5Z3RaiC"), json=_load("jw-media.L5Z3RaiC.json"))
    m = fetch_media(requests.Session(), "L5Z3RaiC", sleep=_no_sleep)
    assert m == JwMedia(
        mediaid="L5Z3RaiC",
        title="2 or 3 Things I Know About Her",
        title_original="2 ou 3 choses que je sais d'elle",
        release_date="1967-03-17",
        directors=("Jean-Luc Godard",),
        criterion_id="1333",
        license_start="2019-04-08T04:00:00Z",
        license_end=None,
        content_type="film",
    )


@responses.activate
def test_media_404_is_an_answer_not_an_error():
    responses.get(JW_MEDIA_URL.format("ZZZZZZZZ"), status=404, json={"message": "['ZZZZZZZZ']: id not found in index."})
    assert fetch_media(requests.Session(), "ZZZZZZZZ", sleep=_no_sleep) is None


@responses.activate
def test_media_5xx_is_weather():
    responses.get(JW_MEDIA_URL.format("L5Z3RaiC"), status=503)
    with pytest.raises(CriterionError):
        fetch_media(requests.Session(), "L5Z3RaiC", sleep=_no_sleep)


@responses.activate
def test_media_with_a_broken_director_string_has_no_directors():
    body = _load("jw-media.L5Z3RaiC.json")
    body["playlist"][0]["director"] = "not json"
    responses.get(JW_MEDIA_URL.format("L5Z3RaiC"), json=body)
    assert fetch_media(requests.Session(), "L5Z3RaiC", sleep=_no_sleep).directors == ()


def test_label_from_slug_reads_dated_pages_only():
    assert label_from_slug("leaving-october-31") == "October 31"
    assert label_from_slug("leaving-november-1") == "November 1"
    assert label_from_slug("leaving-soon") is None
    assert label_from_slug("leaving-octember-31") is None


def _leaving_mocks(home=None):
    responses.get(BASE + "/", body=home if home is not None else (FIX / "home-2026-10-01.html").read_text())
    responses.get(BASE + "/discover/leaving-october-31", body=(FIX / "leaving-october-31.html").read_text())
    responses.get(JW_PLAYLIST_URL.format("0WbeKrrA"), json=_load("jw-playlist.0WbeKrrA.full.json"))


@responses.activate
def test_leaving_reads_the_dated_page_and_ignores_leaving_soon():
    _leaving_mocks()
    result = fetch_leaving(requests.Session(), sleep=_no_sleep)
    assert len(result.labels) == 28
    assert set(result.labels.values()) == {"October 31"}
    assert result.mismatches == ()  # EST-midnight expiries (04:59:59Z) still read October 31
    assert not any("leaving-soon" in c.request.url for c in responses.calls)


@responses.activate
def test_home_page_without_a_dated_link_is_an_authoritative_empty():
    responses.get(BASE + "/", body='<html><a href="/discover/leaving-soon"></a></html>')
    assert fetch_leaving(requests.Session(), sleep=_no_sleep).labels == {}


@responses.activate
def test_a_failed_leaving_page_raises():
    responses.get(BASE + "/", body=(FIX / "home-2026-10-01.html").read_text())
    responses.get(BASE + "/discover/leaving-october-31", status=500)
    with pytest.raises(CriterionError):
        fetch_leaving(requests.Session(), sleep=_no_sleep)


@responses.activate
def test_an_expiry_on_another_day_is_reported_not_trusted():
    playlist = _load("jw-playlist.0WbeKrrA.full.json")
    playlist["playlist"][0]["license_end_date_time"] = "2026-12-01T04:59:59Z"
    responses.get(BASE + "/", body=(FIX / "home-2026-10-01.html").read_text())
    responses.get(BASE + "/discover/leaving-october-31", body=(FIX / "leaving-october-31.html").read_text())
    responses.get(JW_PLAYLIST_URL.format("0WbeKrrA"), json=playlist)
    result = fetch_leaving(requests.Session(), sleep=_no_sleep)
    first = playlist["playlist"][0]["mediaid"]
    assert result.labels[first] == "October 31"
    assert len(result.mismatches) == 1 and first in result.mismatches[0]
