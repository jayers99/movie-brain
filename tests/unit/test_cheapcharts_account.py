from __future__ import annotations

from decimal import Decimal

import pytest
import responses

from movie_brain.infrastructure.cheapcharts import (
    DETAIL_URL,
    CheapChartsClient,
    Pacer,
    RateLimited,
    parse_evolution,
)

# Do the Right Thing's real shape, shortened: $2.99 exactly once, $4.99 again and again.
DTRT_HD = "2026-08-12:+14.99~2026-08-04:-4.99~2025-08-26:+7.99~2025-08-26:-2.99~2025-08-20:+14.99~2019-02-19:9.99"


def _detail(hd: str | None, sd: str | None = None) -> dict:
    movie: dict[str, object] = {"title": "Do the Right Thing", "priceHd": 14.99, "priceHdIsLowest": 0}
    if hd is not None:
        movie["priceHdEvolution"] = hd
    if sd is not None:
        movie["priceSdEvolution"] = sd
    return {"results": {"movies": movie}}


def test_parse_evolution_reads_every_price_whatever_its_direction_sign():
    assert parse_evolution(DTRT_HD) == [Decimal(p) for p in ("14.99", "4.99", "7.99", "2.99", "14.99", "9.99")]
    assert parse_evolution("") == []
    assert parse_evolution("garbage~2020-01-01:~2020-01-02:+x") == []


@responses.activate
def test_lowest_price_is_computed_from_the_hd_history_and_a_one_off_low_counts():
    responses.get(DETAIL_URL, json=_detail(DTRT_HD, sd="2020-01-01:0.99"))
    assert CheapChartsClient().lowest_price("282538466") == Decimal("2.99")
    sent = responses.calls[0].request
    assert "idInStore=282538466" in sent.url and "itemType=movies" in sent.url
    assert sent.headers["Referer"] == "https://www.cheapcharts.com/"


@responses.activate
def test_lowest_price_falls_back_to_the_sd_history_when_there_is_no_hd_one():
    responses.get(DETAIL_URL, json=_detail(hd="", sd="2024-03-01:+9.99~2023-01-01:5.99"))
    assert CheapChartsClient().lowest_price("1") == Decimal("5.99")


@responses.activate
def test_lowest_price_is_none_with_no_history_at_all_or_no_such_product():
    responses.get(DETAIL_URL, json=_detail(hd=None))
    responses.get(DETAIL_URL, json={"results": {"movies": []}})
    client = CheapChartsClient(delay_s=0)
    assert client.lowest_price("1") is None
    assert client.lowest_price("2") is None


@responses.activate
def test_lowest_price_stops_on_a_429():
    responses.get(DETAIL_URL, status=429)
    with pytest.raises(RateLimited):
        CheapChartsClient().lowest_price("1")


def test_pacer_waits_only_the_remainder_since_the_last_call():
    now, slept = [100.0], []

    def sleep(s: float) -> None:
        slept.append(s)
        now[0] += s

    pacer = Pacer(1.5, sleep=sleep, clock=lambda: now[0])
    pacer.wait()  # first call: no wait
    now[0] += 0.5
    pacer.wait()  # 0.5 s later: waits the other 1.0
    now[0] += 60
    pacer.wait()  # a dashboard idle for a minute does not wait at all
    assert slept == [1.0]


@responses.activate
def test_a_client_given_a_pacer_paces_through_it():
    waits = []

    class Spy(Pacer):
        def wait(self) -> None:
            waits.append(1)

    responses.get(DETAIL_URL, json=_detail(DTRT_HD))
    CheapChartsClient(pacer=Spy()).lowest_price("1")
    assert waits == [1]
