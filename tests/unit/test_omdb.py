import json

import pytest
import responses

from movie_brain.domain.models import OmdbRating
from movie_brain.infrastructure.omdb import OMDB_URL, AuthError, OmdbClient, QuotaExceeded

FOUND = {
    "Response": "True",
    "imdbRating": "8.6",
    "Metascore": "98",
    "Language": "Japanese",
    "Ratings": [
        {"Source": "Internet Movie Database", "Value": "8.6/10"},
        {"Source": "Rotten Tomatoes", "Value": "100%"},
    ],
}
NOT_FOUND = {"Response": "False", "Error": "Movie not found!"}


@responses.activate
def test_lookup_by_imdb_parses_imdb_rt_metacritic_language_and_keeps_payload():
    responses.get(OMDB_URL, json=FOUND)
    r = OmdbClient("k").lookup_by_imdb("tt0037800")
    assert (r.imdb, r.rt, r.metacritic, r.found, r.language) == (8.6, 100, 98, True, "Japanese")
    assert json.loads(r.payload)["imdbRating"] == "8.6"
    params = responses.calls[0].request.params
    assert params["i"] == "tt0037800"
    assert "t" not in params and "y" not in params


@responses.activate
def test_lookup_by_imdb_handles_na_values():
    responses.get(
        OMDB_URL, json={"Response": "True", "imdbRating": "N/A", "Metascore": "N/A", "Language": "N/A", "Ratings": []}
    )
    r = OmdbClient("k").lookup_by_imdb("tt0000000")
    assert (r.imdb, r.rt, r.metacritic, r.found, r.language) == (None, None, None, True, None)


@responses.activate
def test_lookup_by_imdb_not_found():
    responses.get(OMDB_URL, json=NOT_FOUND)
    assert OmdbClient("k").lookup_by_imdb("tt9999999") == OmdbRating(None, None, False, None, None)


@responses.activate
def test_quota_exceeded_from_401_and_from_body():
    responses.get(OMDB_URL, json={"Response": "False", "Error": "Request limit reached!"}, status=401)
    with pytest.raises(QuotaExceeded):
        OmdbClient("k").lookup_by_imdb("tt0000000")
    responses.get(OMDB_URL, json={"Response": "False", "Error": "Request limit reached!"})
    with pytest.raises(QuotaExceeded):
        OmdbClient("k").lookup_by_imdb("tt0000000")


@responses.activate
def test_auth_error_on_401_without_limit():
    responses.get(OMDB_URL, json={"Response": "False", "Error": "Invalid API key!"}, status=401)
    with pytest.raises(AuthError):
        OmdbClient("k").lookup_by_imdb("tt0000000")


def test_thumbprint_search_and_by_id_never_use_t():
    from urllib.parse import parse_qs, urlparse

    import responses

    from movie_brain.infrastructure.omdb import OMDB_URL, OmdbClient

    with responses.RequestsMock() as rs:
        rs.get(OMDB_URL, json={"Response": "True", "Search": [{"imdbID": "tt1"}]})
        rs.get(OMDB_URL, json={"Response": "True", "imdbID": "tt1", "Title": "X"})
        rs.get(OMDB_URL, json={"Response": "False", "Error": "Incorrect IMDb ID."})
        c = OmdbClient("k")
        assert c.search("x", 1999) == [{"imdbID": "tt1"}]
        assert c.by_id("tt1")["Title"] == "X"
        assert c.by_id("tt0") == {}
        for call in rs.calls:
            assert "t" not in parse_qs(urlparse(call.request.url).query)
