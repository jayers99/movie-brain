from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
import requests
import responses

from movie_brain.domain.models import TmdbCandidate
from movie_brain.infrastructure.tmdb import TMDB_API, AuthError, FindResult, TmdbClient, watch_link


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


def test_watch_providers_reads_free_and_ads_and_carries_names(rs):
    body = {
        "results": {
            "US": {
                "link": "https://www.themoviedb.org/movie/1/watch",
                "flatrate": [{"provider_id": 258, "provider_name": "Criterion Channel"}],
                "free": [{"provider_id": 191, "provider_name": "Kanopy"}],
                "ads": [{"provider_id": 73, "provider_name": "Tubi TV"}],
                "rent": [{"provider_id": 2, "provider_name": "Apple TV"}],
            }
        }
    }
    rs.get(f"{TMDB_API}/movie/1/watch/providers", json=body)
    p = TmdbClient("tok").watch_providers(1)
    assert p.flatrate == (258,)
    assert p.free == (191,)
    assert p.ads == (73,)
    assert p.names[191] == "Kanopy"
    assert p.names[73] == "Tubi TV"
    assert p.names[258] == "Criterion Channel"


def test_watch_providers_tolerates_missing_buckets(rs):
    rs.get(f"{TMDB_API}/movie/2/watch/providers", json={"results": {}})
    p = TmdbClient("tok").watch_providers(2)
    assert p.flatrate == () and p.free == () and p.ads == ()
    assert p.names == {}


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


def test_imdb_id_reads_external_ids(rs):
    rs.get(f"{TMDB_API}/movie/11/external_ids", json={"id": 11, "imdb_id": "tt0037800"})
    assert TmdbClient("tok").imdb_id(11) == "tt0037800"


def test_imdb_id_missing_is_none(rs):
    rs.get(f"{TMDB_API}/movie/11/external_ids", json={"id": 11, "imdb_id": None})
    assert TmdbClient("tok").imdb_id(11) is None


def test_movie_facts_is_one_call_with_alts_and_external_ids(rs):
    rs.get(
        f"{TMDB_API}/movie/424",
        json={
            "title": "Schindler's List",
            "original_title": "Schindler's List",
            "release_date": "1993-12-15",
            "runtime": 195,
            "alternative_titles": {"titles": [{"title": "La liste de Schindler"}, {"title": ""}]},
            "external_ids": {"imdb_id": "tt0108052"},
        },
    )
    f = TmdbClient("tok").movie_facts(424)
    assert f.imdb_id == "tt0108052"
    assert (f.title, f.original_title, f.year, f.runtime_min) == ("Schindler's List", "Schindler's List", 1993, 195)
    assert f.alternatives == ("La liste de Schindler",)
    assert len(rs.calls) == 1
    assert parse_qs(urlparse(rs.calls[0].request.url).query)["append_to_response"] == [
        "alternative_titles,external_ids"
    ]


def test_movie_facts_tolerates_missing_fields(rs):
    rs.get(f"{TMDB_API}/movie/5", json={"title": "X", "original_title": "X"})
    f = TmdbClient("tok").movie_facts(5)
    assert (f.imdb_id, f.year, f.runtime_min, f.alternatives) == (None, None, None, ())


@responses.activate
def test_find_by_imdb_returns_first_movie_id():
    responses.add(responses.GET, f"{TMDB_API}/find/tt0083658", json={"movie_results": [{"id": 78}], "tv_results": []})
    assert TmdbClient("tok").find_by_imdb("tt0083658") == 78


@responses.activate
def test_find_by_imdb_none_when_empty():
    responses.add(responses.GET, f"{TMDB_API}/find/tt1", json={"movie_results": [], "tv_results": []})
    assert TmdbClient("tok").find_by_imdb("tt1") is None


@responses.activate
def test_find_by_imdb_any_reports_a_tv_only_hit():
    responses.get(
        f"{TMDB_API}/find/tt0092337",
        json={"movie_results": [], "tv_results": [{"id": 2001}], "tv_episode_results": []},
    )
    assert TmdbClient("tok").find_by_imdb_any("tt0092337") == FindResult(None, True)


@responses.activate
def test_find_by_imdb_any_prefers_the_movie_hit():
    responses.get(
        f"{TMDB_API}/find/tt0037800",
        json={"movie_results": [{"id": 11}], "tv_results": [], "tv_episode_results": []},
    )
    assert TmdbClient("tok").find_by_imdb_any("tt0037800") == FindResult(11, False)


def test_thumbprint_raw_methods_hit_the_right_endpoints(rs):
    rs.get(f"{TMDB_API}/search/movie", json={"results": [{"id": 1}]})
    rs.get(f"{TMDB_API}/search/person", json={"results": [{"id": 7}, {"id": 8}, {"id": 9}]})
    rs.get(f"{TMDB_API}/person/7/movie_credits", json={"crew": [{"job": "Director", "id": 1}]})
    rs.get(f"{TMDB_API}/movie/1", json={"id": 1, "external_ids": {"imdb_id": "tt1"}})
    c = TmdbClient("tok")
    assert c.search_raw("x", 1999, any_release_year=True) == [{"id": 1}]
    assert parse_qs(urlparse(rs.calls[0].request.url).query)["year"] == ["1999"]
    assert [p["id"] for p in c.search_person("n")] == [7, 8]
    assert c.person_movie_credits(7)[0]["job"] == "Director"
    assert c.movie_detail(1)["external_ids"]["imdb_id"] == "tt1"
    assert "append_to_response" in rs.calls[-1].request.url
