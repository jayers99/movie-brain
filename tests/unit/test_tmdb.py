from __future__ import annotations

import pytest
import requests
import responses

from movie_brain.domain.models import TmdbCandidate
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


def make_result(tmdb_id, title, year, popularity=1.0):
    return {"id": tmdb_id, "title": title, "original_title": title,
            "release_date": f"{year}-01-01", "popularity": popularity}


@responses.activate
def test_arbiter_hit_when_same_title_near_claimed_year():
    responses.get(f"{TMDB_API}/search/movie",
                  json={"results": [make_result(653, "Nosferatu", 1922), make_result(426063, "Nosferatu", 2024)]})
    from movie_brain.infrastructure.tmdb import TmdbArbiter
    arbiter = TmdbArbiter(TmdbClient("tok"))
    assert arbiter("Nosferatu", 2024) is True
    assert arbiter("Nosferatu", 1970) is False  # cached: still exactly 1 HTTP call
    assert len(responses.calls) == 1


@responses.activate
def test_arbiter_seed_avoids_network():
    from movie_brain.infrastructure.tmdb import TmdbArbiter
    arbiter = TmdbArbiter(TmdbClient("tok"))
    arbiter.seed("Stop Making Sense", [TmdbCandidate(606, "Stop Making Sense", "Stop Making Sense", 1984, 5.0)])
    assert arbiter("Stop Making Sense", 2023) is False
    assert len(responses.calls) == 0


@responses.activate
def test_arbiter_network_failure_returns_none():
    responses.get(f"{TMDB_API}/search/movie", body=requests.ConnectionError("boom"))
    from movie_brain.infrastructure.tmdb import TmdbArbiter
    arbiter = TmdbArbiter(TmdbClient("tok"))
    assert arbiter("Vertigo", 1996) is None


@responses.activate
def test_movie_year_parses_release_date():
    responses.get(f"{TMDB_API}/movie/947", json={"id": 947, "release_date": "1962-12-11"})
    assert TmdbClient("tok").movie_year(947) == 1962


@responses.activate
def test_movie_year_missing_date_is_none():
    responses.get(f"{TMDB_API}/movie/947", json={"id": 947, "release_date": ""})
    assert TmdbClient("tok").movie_year(947) is None


@responses.activate
def test_movie_titles():
    responses.get(
        f"{TMDB_API}/movie/62518",
        json={"title": "Wild Blood", "original_title": "Vahşi Kan", "release_date": "1983-01-01"},
    )
    assert TmdbClient("t").movie_titles(62518) == ("Wild Blood", "Vahşi Kan", 1983, ())


@responses.activate
def test_movie_titles_folds_alternative_titles_into_the_same_call():
    responses.get(
        f"{TMDB_API}/movie/1",
        json={
            "title": "The World of Apu",
            "original_title": "Apur Sansar",
            "release_date": "1959-01-01",
            "alternative_titles": {
                "titles": [
                    {"iso_3166_1": "IN", "title": "Apur Sansar"},
                    {"iso_3166_1": "GB", "title": "The World of Apu (Apu Trilogy 3)"},
                ]
            },
        },
    )
    titles = TmdbClient("t").movie_titles(1)
    assert titles.alternatives == ("Apur Sansar", "The World of Apu (Apu Trilogy 3)")
    assert len(responses.calls) == 1
    assert "append_to_response=alternative_titles" in responses.calls[0].request.url


def _hit(tid, title, date, orig=None, pop=1.0):
    return {"id": tid, "title": title, "original_title": orig or title, "release_date": date, "popularity": pop}


@responses.activate
def test_search_retries_with_year_when_no_result_is_near_the_known_year():
    # Intolerance (1916): the title-only page is later same-titled films plus a dateless
    # short; the Griffith feature only surfaces when the year is passed along.
    plain = [_hit(48684, "Intolerance", "2000-01-01"), _hit(1216137, "Intolerance", "")]
    dated = [_hit(3059, "Intolerance: Love's Struggle Throughout the Ages", "1916-09-05", "Intolerance", 3.0)]
    q = responses.matchers.query_param_matcher
    responses.get(
        f"{TMDB_API}/search/movie", json={"results": plain}, match=[q({"query": "Intolerance", "include_adult": "false"})]
    )
    responses.get(
        f"{TMDB_API}/search/movie",
        json={"results": dated},
        match=[q({"query": "Intolerance", "include_adult": "false", "primary_release_year": "1916"})],
    )
    ids = [c.tmdb_id for c in TmdbClient("t").search("Intolerance", 1916)]
    assert ids == [48684, 1216137, 3059]
    assert len(responses.calls) == 2


@responses.activate
def test_search_skips_the_year_retry_when_a_near_year_result_exists():
    responses.get(f"{TMDB_API}/search/movie", json={"results": [_hit(947, "Lawrence of Arabia", "1962-12-11")]})
    assert [c.tmdb_id for c in TmdbClient("t").search("Lawrence of Arabia", 1962)] == [947]
    assert len(responses.calls) == 1
