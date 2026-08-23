from __future__ import annotations

import pytest
import responses

from movie_brain.infrastructure.tmdb import TMDB_API, AuthError, TmdbClient, watch_link


@pytest.fixture
def rs():
    with responses.RequestsMock() as r:
        yield r


def test_search_parses_top_candidates(rs):
    rs.get(f"{TMDB_API}/search/movie", json={"results": [
        {"id": 11, "title": "Trio", "original_title": "Le Trio", "release_date": "1950-02-01", "popularity": 3.5},
        {"id": 12, "title": "Trio II", "original_title": "Trio II", "release_date": "", "popularity": 1.0},
    ]})
    got = TmdbClient("tok").search("Trio")
    assert [(c.tmdb_id, c.year) for c in got] == [(11, 1950), (12, None)]
    assert got[0].original_title == "Le Trio"
    assert rs.calls[0].request.headers["Authorization"] == "Bearer tok"


def test_search_401_raises_autherror(rs):
    rs.get(f"{TMDB_API}/search/movie", status=401, json={"status_message": "bad token"})
    with pytest.raises(AuthError):
        TmdbClient("tok").search("Trio")


def test_watch_providers_splits_kinds_and_keeps_payload(rs):
    body = {"results": {"US": {"link": "https://tmdb/w/11",
                               "flatrate": [{"provider_id": 1899}, {"provider_id": 258}],
                               "rent": [{"provider_id": 2}], "buy": [{"provider_id": 2}, {"provider_id": 10}]}}}
    rs.get(f"{TMDB_API}/movie/11/watch/providers", json=body)
    got = TmdbClient("tok").watch_providers(11)
    assert got.flatrate == (1899, 258) and got.rent == (2,) and got.buy == (2, 10)
    assert got.link == "https://tmdb/w/11" and '"US"' in got.payload


def test_watch_providers_no_us_region_is_empty(rs):
    rs.get(f"{TMDB_API}/movie/11/watch/providers", json={"results": {"GB": {"flatrate": []}}})
    got = TmdbClient("tok").watch_providers(11)
    assert got.flatrate == () and got.link is None


def test_watch_link():
    assert watch_link(11) == "https://www.themoviedb.org/movie/11/watch?locale=US"
