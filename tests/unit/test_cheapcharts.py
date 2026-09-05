import pytest
import responses

from movie_brain.infrastructure.cheapcharts import (
    PRICES_URL,
    SEARCH_URL,
    CheapChartsClient,
    RateLimited,
)

VERTIGO = {
    "title": "Vertigo (1958)",
    "artist": "Alfred Hitchcock",
    "cheapChartsProductPageUrl": (
        "https://www.cheapcharts.com/us/itunes/movies/284815525"
        "?utm_source=api2-gptapi&utm_medium=api&utm_campaign=gptapi"
    ),
    "releaseDate": "1958-05-09",
    "price": 12.99,
    "imdbId": "tt0052357",
}


@responses.activate
def test_products_by_imdb_keys_the_itunes_id_out_of_the_product_page_url():
    responses.get(PRICES_URL, json={"status": "success", "results": {"buymovies": [VERTIGO]}})
    found = CheapChartsClient().products_by_imdb(["tt0052357"])
    assert list(found) == ["tt0052357"]
    product = found["tt0052357"]
    assert product.itunes_id == "284815525"
    assert product.title == "Vertigo (1958)"
    assert product.year == 1958
    assert product.director == "Alfred Hitchcock"  # CheapCharts calls the field `artist`


@responses.activate
def test_products_by_imdb_returns_nothing_when_cheapcharts_has_no_mapping():
    """Amour's page exists at /us/itunes/movies/675010277 and the IMDb index still misses it."""
    responses.get(PRICES_URL, json={"status": "success", "results": {"buymovies": []}})
    assert CheapChartsClient().products_by_imdb(["tt2318097"]) == {}


def test_products_by_imdb_refuses_more_ids_than_the_api_accepts():
    with pytest.raises(ValueError, match="at most 5"):
        CheapChartsClient().products_by_imdb(["tt1", "tt2", "tt3", "tt4", "tt5", "tt6"])


@responses.activate
def test_products_by_imdb_asks_the_us_itunes_store_for_all_ids_at_once():
    responses.get(PRICES_URL, json={"status": "success", "results": {"buymovies": []}})
    CheapChartsClient().products_by_imdb(["tt0052357", "tt2318097"])
    request = responses.calls[0].request
    assert request.params["imdbIDs"] == "tt0052357,tt2318097"
    assert (request.params["store"], request.params["country"]) == ("itunes", "us")
    assert request.headers["Referer"] == "https://www.cheapcharts.com/"


AMOUR = {
    "title": "Amour",
    "cheapChartsProductPageUrl": (
        "https://www.cheapcharts.com/us/itunes/movies/675010277?utm_source=api2-gptapi"
    ),
    "mediaType": "movies",
    "itemType": "movies",
    "releaseYear": "2012",
    "idInStore": "675010277",
}
AMOUR_SERIES = dict(AMOUR, title="Amour", itemType="tvSeasons", idInStore="999")


@responses.activate
def test_search_reads_the_itunes_id_the_results_state_directly():
    responses.get(SEARCH_URL, json={"status": "success", "results": [AMOUR]})
    found = CheapChartsClient().search("Amour")
    assert [(p.itunes_id, p.title, p.year, p.imdb_id) for p in found] == [
        ("675010277", "Amour", 2012, None)
    ]


@responses.activate
def test_search_ignores_results_that_are_not_movies():
    responses.get(SEARCH_URL, json={"status": "success", "results": [AMOUR_SERIES, AMOUR]})
    assert [p.itunes_id for p in CheapChartsClient().search("Amour")] == ["675010277"]


@responses.activate
def test_a_429_becomes_rate_limited_rather_than_a_generic_http_error():
    """CheapCharts' llms.txt promises no rate limiting and the API disagrees, so the resolver
    has to recognise the refusal and stop rather than burn the rest of the worklist on it."""
    responses.get(PRICES_URL, status=429)
    with pytest.raises(RateLimited):
        CheapChartsClient().products_by_imdb(["tt0052357"])


@responses.activate
def test_calls_are_paced_but_the_first_one_never_waits():
    responses.get(PRICES_URL, json={"status": "success", "results": {"buymovies": []}})
    waits: list[float] = []
    client = CheapChartsClient(delay_s=3.0, sleep=waits.append)
    client.products_by_imdb(["tt1"])
    client.products_by_imdb(["tt2"])
    assert waits == [3.0]
