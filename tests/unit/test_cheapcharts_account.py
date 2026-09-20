from __future__ import annotations

import hashlib
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import pytest
import responses

from movie_brain.infrastructure.cheapcharts import (
    ACCOUNT_URL,
    DETAIL_URL,
    WISHLIST_URL,
    CheapChartsAccount,
    CheapChartsClient,
    CheapChartsError,
    Pacer,
    RateLimited,
    parse_evolution,
)
from movie_brain.infrastructure.config import Config
from movie_brain.infrastructure.credentials import load_credentials

# Do the Right Thing's real shape, SHORTENED for the test: $2.99 appears exactly once.
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


@responses.activate
def test_get_raises_our_own_wording_on_a_non_json_or_non_object_answer():
    """An unexpected JSON shape must raise a CheapChartsError, never an AttributeError or
    TypeError — either of which would abort dashboard startup (only WishlistError is caught
    there)."""
    responses.get(DETAIL_URL, body="<html>maintenance</html>", status=200)
    with pytest.raises(CheapChartsError, match="not JSON"):
        CheapChartsClient(delay_s=0).lowest_price("1")
    responses.replace(responses.GET, DETAIL_URL, json=["not", "an", "object"], status=200)
    with pytest.raises(CheapChartsError, match="not a JSON object"):
        CheapChartsClient(delay_s=0).lowest_price("1")


@responses.activate
def test_lowest_price_returns_none_rather_than_raising_on_a_reshaped_results():
    responses.get(DETAIL_URL, json={"results": ["not", "a", "dict"]})
    assert CheapChartsClient(delay_s=0).lowest_price("1") is None


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


USER, PASSWORD = "someone@example.test", "hunter2"  # invented — never a real account
LOGIN_OK = {
    "status": "success",
    "message": "already logged in",  # seen live: still a success
    "additionalInfo": {"sessionToken": "tok-1", "email": USER, "customerId": 42},
}
BAD_TOKEN = {"status": "error", "message": "Couldn't load user. DeviceId or sessionToken unknown"}


def _account() -> CheapChartsAccount:
    return CheapChartsAccount(USER, PASSWORD, pacer=Pacer(0))


def _action(call) -> str:
    return parse_qs(urlsplit(call.request.url).query)["action"][0]


def _body(call) -> dict[str, list[str]]:
    return parse_qs(call.request.body)


def test_credentials_are_read_from_the_one_toml_file_keyed_by_site(config_dir):
    config = Config(config_dir)
    assert load_credentials(config, "cheapcharts") is None  # no file
    config.credentials_file.write_text('[cheapcharts]\nusername = "someone@example.test"\npassword = "hunter2"\n')
    assert load_credentials(config, "cheapcharts") == (USER, PASSWORD)
    assert load_credentials(config, "othersite") is None  # no such section


def test_placeholder_or_half_filled_credentials_count_as_missing(config_dir):
    config = Config(config_dir)
    config.credentials_file.write_text('[cheapcharts]\nusername = "PUT-YOUR-EMAIL-HERE"\npassword = "x"\n')
    assert load_credentials(config, "cheapcharts") is None
    config.credentials_file.write_text('[cheapcharts]\nusername = "someone@example.test"\n')
    assert load_credentials(config, "cheapcharts") is None
    config.credentials_file.write_text("not toml [")
    assert load_credentials(config, "cheapcharts") is None
    config.credentials_file.write_bytes(b"\xff\xfe not valid utf-8")  # UnicodeDecodeError, a ValueError subclass
    assert load_credentials(config, "cheapcharts") is None


@responses.activate
def test_login_sends_the_sha256_digest_never_the_plain_password_and_reads_the_wishlist():
    responses.post(ACCOUNT_URL, json=LOGIN_OK)
    responses.post(
        WISHLIST_URL,
        json={"status": "success", "results": {"movies": [
            {"idInStore": 273058482, "initialPriceValue": 5.99, "initialHdPriceValue": 5.99, "customPrice": True},
            {"idInStore": "366474905", "initialPriceValue": 5.99, "initialHdPriceValue": 5.99},
        ]}},
    )
    assert _account().wishlist_ids() == ["273058482", "366474905"]
    login, read = responses.calls
    sent = _body(login)
    assert sent["password"] == [hashlib.sha256(PASSWORD.encode()).hexdigest()]
    assert PASSWORD not in login.request.body
    assert sent["email"] == [USER] and sent["action"] == ["login"] and sent["country"] == ["us"]
    assert sent["origin"] == ["website"] and sent["appEntity"] == ["cc_main_website"]
    assert _action(read) == "getShortItemList_v2" and _body(read)["sessionToken"] == ["tok-1"]
    assert login.request.headers["Referer"] == "https://www.cheapcharts.com/"


@responses.activate
def test_an_empty_wishlist_reads_as_no_films():
    responses.post(ACCOUNT_URL, json=LOGIN_OK)
    responses.post(WISHLIST_URL, json={"status": "success", "results": {"movies": []}})
    assert _account().wishlist_ids() == []


@responses.activate
def test_a_wishlist_read_with_no_movies_key_is_refused_not_read_as_empty():
    """A wholesale replace on `wishlist_ids() == []` would wipe every heart — so a `results`
    with no `movies` list inside it must be a refusal, never a silent empty wishlist."""
    responses.post(ACCOUNT_URL, json=LOGIN_OK)
    responses.post(WISHLIST_URL, json={"status": "success", "results": {}})
    with pytest.raises(CheapChartsError, match="unexpected answer shape"):
        _account().wishlist_ids()


@responses.activate
def test_a_wishlist_read_with_a_non_object_results_is_refused():
    responses.post(ACCOUNT_URL, json=LOGIN_OK)
    responses.post(WISHLIST_URL, json={"status": "success", "results": ["not", "a", "dict"]})
    with pytest.raises(CheapChartsError, match="unexpected answer shape"):
        _account().wishlist_ids()


@responses.activate
def test_a_login_with_a_non_object_additional_info_is_refused():
    responses.post(ACCOUNT_URL, json={"status": "success", "additionalInfo": ["not", "a", "dict"]})
    with pytest.raises(CheapChartsError, match="unexpected answer shape"):
        _account().wishlist_ids()


@responses.activate
def test_add_and_set_target_send_buymovies_and_the_same_price_for_sd_and_hd():
    responses.post(ACCOUNT_URL, json=LOGIN_OK)
    responses.post(WISHLIST_URL, json={"status": "success", "message": "Item added"})
    responses.post(WISHLIST_URL, json={"status": "success", "message": "init price was changed to 3.99"})
    account = _account()
    assert account.add_item("282538466") is True
    account.set_target("282538466", Decimal("3.99"))
    _, add, target = responses.calls
    q = parse_qs(urlsplit(add.request.url).query)
    assert q["action"] == ["addItem"] and q["itemType"] == ["buymovies"] and q["idInStore"] == ["282538466"]
    assert q["country"] == ["us"] and q["store"] == ["itunes"]
    q = parse_qs(urlsplit(target.request.url).query)
    assert q["action"] == ["changeInitPrice"] and q["itemType"] == ["buymovies"]
    assert q["customPrice"] == ["3.99"] and q["customPriceHd"] == ["3.99"]
    assert len([c for c in responses.calls if c.request.url.startswith(ACCOUNT_URL)]) == 1  # one login, token reused


@responses.activate
def test_a_refused_add_is_reported_not_raised_so_set_target_can_still_run():
    """The API's exact answer for a film already on the wishlist was never observed; whatever it
    is, the caller goes on to set the target and lets the read-back decide."""
    responses.post(ACCOUNT_URL, json=LOGIN_OK)
    responses.post(WISHLIST_URL, json={"status": "error", "message": "whatever it says"})
    assert _account().add_item("1") is False


@responses.activate
def test_a_refused_set_target_raises():
    responses.post(ACCOUNT_URL, json=LOGIN_OK)
    responses.post(WISHLIST_URL, json={"status": "error", "message": "no such item"})
    with pytest.raises(CheapChartsError):
        _account().set_target("1", Decimal("3.99"))


@responses.activate
def test_an_expired_token_triggers_one_fresh_login_and_a_retry():
    responses.post(ACCOUNT_URL, json=LOGIN_OK)
    responses.post(WISHLIST_URL, json=BAD_TOKEN)
    responses.post(ACCOUNT_URL, json={**LOGIN_OK, "additionalInfo": {"sessionToken": "tok-2"}})
    responses.post(WISHLIST_URL, json={"status": "success", "results": {"movies": []}})
    assert _account().wishlist_ids() == []
    assert _body(responses.calls[-1])["sessionToken"] == ["tok-2"]


@responses.activate
def test_a_token_refused_twice_is_an_error_even_for_add():
    responses.post(ACCOUNT_URL, json=LOGIN_OK)
    responses.post(WISHLIST_URL, json=BAD_TOKEN)
    with pytest.raises(CheapChartsError):
        _account().add_item("1")


@responses.activate
def test_a_failed_login_raises_without_echoing_anything_the_api_said():
    responses.post(ACCOUNT_URL, json={"status": "error", "message": f"wrong password for {USER}"})
    with pytest.raises(CheapChartsError) as exc:
        _account().wishlist_ids()
    assert USER not in str(exc.value) and PASSWORD not in str(exc.value) and "wrong password" not in str(exc.value)


@responses.activate
def test_a_429_and_a_non_json_answer_both_stop_the_call():
    responses.post(ACCOUNT_URL, status=429)
    with pytest.raises(RateLimited):
        _account().wishlist_ids()
    responses.replace(responses.POST, ACCOUNT_URL, body="<html>maintenance</html>", status=200)
    with pytest.raises(CheapChartsError):
        _account().wishlist_ids()


@responses.activate
def test_remove_item_sends_buymovies_and_reports_a_refusal_instead_of_raising():
    responses.post(ACCOUNT_URL, json=LOGIN_OK)
    responses.post(WISHLIST_URL, json={"status": "success", "message": "Item removed"})
    responses.post(WISHLIST_URL, json={"status": "error", "message": "whatever it says"})
    account = _account()
    assert account.remove_item("282538466") is True
    q = parse_qs(urlsplit(responses.calls[1].request.url).query)
    assert q["action"] == ["removeItem"] and q["itemType"] == ["buymovies"] and q["idInStore"] == ["282538466"]
    assert q["country"] == ["us"] and q["store"] == ["itunes"]
    assert account.remove_item("282538466") is False  # e.g. already gone: the read-back decides
