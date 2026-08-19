import pytest
import requests
import responses

from movie_brain.domain.models import Film
from movie_brain.infrastructure.criterion import (
    API_URL,
    BROWSE_URL,
    CatalogError,
    fetch_films,
    fetch_leaving,
    fetch_token,
    page_one_matches,
)

BROWSE_HTML = '<html><script>window.TOKEN = "tok-abc123";</script></html>'


def movie(name, year, director, page_url):
    return {
        "name": name,
        "type": "movie",
        "metadata": {"director": director, "year_released": year},
        "_links": {"collection_page": {"href": page_url}},
    }


def api_page(collections, page, last_page, total=None):
    nxt = None if page >= last_page else f"{API_URL}?page={page + 1}"
    body = {"_links": {"next": {"href": nxt}}, "_embedded": {"collections": collections}}
    if total is not None:
        body["total"] = total
    return body


def category(cid, name):
    return {"id": cid, "type": "category", "name": name, "_links": {}}


@responses.activate
def test_fetch_token_extracts_window_token():
    responses.get(BROWSE_URL, body=BROWSE_HTML)
    assert fetch_token(requests.Session()) == "tok-abc123"


@responses.activate
def test_fetch_token_raises_when_missing():
    responses.get(BROWSE_URL, body="<html></html>")
    with pytest.raises(CatalogError):
        fetch_token(requests.Session())


@responses.activate
def test_fetch_films_walks_pages_until_next_is_null():
    responses.get(API_URL, json=api_page([movie("Trio", 1950, "Ken Annakin", "https://c/trio")], 1, 2))
    responses.get(API_URL, json=api_page([movie("Quartet", 1948, None, "https://c/quartet")], 2, 2))
    films = fetch_films(requests.Session(), "tok", delay_s=0)
    assert films == [
        Film("Trio", 1950, "Ken Annakin", "https://c/trio"),
        Film("Quartet", 1948, None, "https://c/quartet"),
    ]
    assert responses.calls[0].request.headers["Authorization"] == "Bearer tok"
    assert responses.calls[0].request.params["type[]"] == "movie"


@responses.activate
def test_fetch_films_raises_on_empty_catalog():
    responses.get(API_URL, json=api_page([], 1, 1))
    with pytest.raises(CatalogError):
        fetch_films(requests.Session(), "tok", delay_s=0)


@responses.activate
def test_fetch_leaving_maps_keys_to_label():
    responses.get(API_URL, json=api_page([category(7, "Leaving August 31"), category(8, "Comedies")], 1, 1))
    responses.get(
        f"{API_URL}/7/items",
        json={
            "_links": {"next": {"href": None}},
            "_embedded": {"items": [{"name": "Trio", "metadata": {"year_released": 1950}}]},
        },
    )
    assert fetch_leaving(requests.Session(), "tok", delay_s=0) == {"trio (1950)": "August 31"}
    assert len(responses.calls) == 2  # non-leaving category not walked


@responses.activate
def test_page_one_matches_true_when_total_and_first_page_agree():
    known = [Film("Trio", 1950, "K", "u1"), Film("Quartet", 1948, "K", "u2")]
    responses.get(API_URL, json=api_page([movie("Trio", 1950, "K", "u1")], 1, 1, total=2))
    assert page_one_matches(requests.Session(), "tok", known) is True


@responses.activate
def test_page_one_matches_false_on_total_change_or_unknown_film():
    known = [Film("Trio", 1950, "K", "u1")]
    responses.get(API_URL, json=api_page([movie("Trio", 1950, "K", "u1")], 1, 1, total=2))
    assert page_one_matches(requests.Session(), "tok", known) is False
    responses.get(API_URL, json=api_page([movie("New", 2020, "K", "u9")], 1, 1, total=1))
    assert page_one_matches(requests.Session(), "tok", known) is False
