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
def test_lookup_parses_imdb_rt_metacritic_language_and_keeps_payload():
    responses.get(OMDB_URL, json=FOUND)
    r = OmdbClient("k").lookup("Seven Samurai", 1954)
    assert (r.imdb, r.rt, r.metacritic, r.found, r.language) == (8.6, 100, 98, True, "Japanese")
    assert json.loads(r.payload)["imdbRating"] == "8.6"
    assert responses.calls[0].request.params["t"] == "Seven Samurai"
    assert responses.calls[0].request.params["y"] == "1954"


@responses.activate
def test_lookup_handles_na_values():
    responses.get(
        OMDB_URL, json={"Response": "True", "imdbRating": "N/A", "Metascore": "N/A", "Language": "N/A", "Ratings": []}
    )
    r = OmdbClient("k").lookup("Obscurity", None)
    assert (r.imdb, r.rt, r.metacritic, r.found, r.language) == (None, None, None, True, None)
    assert len(responses.calls) == 1  # no year → no fallback attempts


@responses.activate
def test_lookup_year_fallback_tries_minus_then_plus_one():
    responses.get(OMDB_URL, json=NOT_FOUND)
    responses.get(OMDB_URL, json=NOT_FOUND)
    responses.get(OMDB_URL, json=FOUND)
    r = OmdbClient("k").lookup("Late", 1990)
    assert r.found is True
    assert [c.request.params["y"] for c in responses.calls] == ["1990", "1989", "1991"]


@responses.activate
def test_lookup_not_found_after_fallbacks():
    for _ in range(3):
        responses.get(OMDB_URL, json=NOT_FOUND)
    assert OmdbClient("k").lookup("Nope", 1990) == OmdbRating(None, None, False, None, None)


@responses.activate
def test_quota_exceeded_from_401_and_from_body():
    responses.get(OMDB_URL, json={"Response": "False", "Error": "Request limit reached!"}, status=401)
    with pytest.raises(QuotaExceeded):
        OmdbClient("k").lookup("X", None)
    responses.get(OMDB_URL, json={"Response": "False", "Error": "Request limit reached!"})
    with pytest.raises(QuotaExceeded):
        OmdbClient("k").lookup("X", None)


@responses.activate
def test_auth_error_on_401_without_limit():
    responses.get(OMDB_URL, json={"Response": "False", "Error": "Invalid API key!"}, status=401)
    with pytest.raises(AuthError):
        OmdbClient("k").lookup("X", None)
