from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import pytest
import responses

from movie_brain.application.wishlist import WishlistGateway
from movie_brain.domain.models import Film
from movie_brain.infrastructure.cheapcharts import (
    ACCOUNT_URL,
    DETAIL_URL,
    WISHLIST_URL,
    CheapChartsAccount,
    CheapChartsClient,
    CheapChartsError,
    Pacer,
    WishlistItem,
)
from movie_brain.web.app import create_app

D = date(2026, 9, 19)
DTRT = "282538466"

LOGIN_OK = {"status": "success", "message": "ok", "additionalInfo": {"sessionToken": "tok-1"}}
# The real read answers with no `status` key at all (brief amendment 1.3) — only writes send one.
EMPTY_READ = {"results": {"ebooks": [], "movies": [], "tv": []}, "responseTimestamp": "2026-09-19 18:30:00"}


def _made(call) -> str:
    """One call, as `endpoint:action` — enough to pin the ORDER of a click's calls."""
    parts = urlsplit(call.request.url)
    action = parse_qs(parts.query).get("action") or parse_qs(call.request.body or "").get("action")
    return parts.path.rsplit("/", 1)[-1] + (f":{action[0]}" if action else "")


def _real_client(repo):
    pacer = Pacer(0)
    gateway = WishlistGateway(
        CheapChartsClient(pacer=pacer), CheapChartsAccount("someone@example.test", "hunter2", pacer=pacer)
    )
    app = create_app(repo, today=lambda: D, wishlist=gateway)
    app.testing = True
    return app.test_client()


def _history(hd):
    return {"results": {"movies": {"priceHdEvolution": hd}}}


class FakePrices:
    def lowest_price(self, itunes_id):
        return Decimal("2.99")


class FakeAccount:
    """`listed` is what CheapCharts holds, `targets` which of those carry a custom price — the
    two things the read reports. `down` fails the READ, which is now every click's first call."""

    def __init__(self):
        self.targets = {}
        self.listed = []
        self.down = False

    def _check(self):
        if self.down:
            raise CheapChartsError("unexpected answer shape")

    def add_item(self, itunes_id):
        self._check()
        if itunes_id not in self.listed:
            self.listed.append(itunes_id)
        return True

    def set_target(self, itunes_id, target):
        self.targets[itunes_id] = target

    def wishlist_items(self):
        self._check()
        return [WishlistItem(i, custom_target=i in self.targets) for i in self.listed]

    def remove_item(self, itunes_id):
        self._check()
        if itunes_id in self.listed:
            self.listed.remove(itunes_id)
        self.targets.pop(itunes_id, None)
        return True


@pytest.fixture
def account():
    return FakeAccount()


@pytest.fixture
def client(repo, account):
    app = create_app(repo, today=lambda: D, wishlist=WishlistGateway(FakePrices(), account))
    app.testing = True
    return app.test_client()


def _film(repo, title, year, itunes=None):
    fid = repo.create_film(Film(title, year, "Dir", ""))
    if itunes:
        repo.set_external_id(fid, "itunes", itunes, D)
    return fid


def test_a_click_wishlists_the_film_and_the_payload_carries_the_heart(client, repo, account):
    fid = _film(repo, "Do the Right Thing", 1989, DTRT)
    assert client.get(f"/api/films/{fid}").get_json()["wishlisted"] is False
    r = client.post(f"/api/films/{fid}/wishlist")
    assert r.status_code == 200 and r.get_json() == {"wishlisted": True}
    assert account.targets == {DTRT: Decimal("3.99")}
    assert client.get(f"/api/films/{fid}").get_json()["wishlisted"] is True
    assert [f["wishlisted"] for f in client.get("/api/films").get_json() if f["id"] == fid] == [True]


def test_unknown_owned_and_unsold_films_are_refused(client, repo, account):
    assert client.post("/api/films/999/wishlist").status_code == 404
    unsold = _film(repo, "La Dolce Vita", 1960)
    owned = _film(repo, "The Big Sleep", 1946, "290555722")
    repo.mark_owned(owned, D)
    for fid in (unsold, owned):
        r = client.post(f"/api/films/{fid}/wishlist")
        assert r.status_code == 409 and r.get_json() == {"error": "not for sale"}
    assert account.targets == {}


def test_a_cheapcharts_failure_is_the_one_failure_line_and_marks_nothing(client, repo, account):
    fid = _film(repo, "Do the Right Thing", 1989, DTRT)
    account.down = True
    r = client.post(f"/api/films/{fid}/wishlist")
    assert r.status_code == 502 and r.get_json() == {"error": "Couldn't reach CheapCharts."}
    assert repo.wishlisted_film_ids() == set()


def test_the_terminal_names_the_reason_while_the_screen_line_stays_the_same(client, repo, account, caplog):
    """A failed click must be diagnosable next time (brief amendment 1.3) — but only from our
    own wording: never the API's text, a token, an email or a price."""
    fid = _film(repo, "Do the Right Thing", 1989, DTRT)
    account.down = True
    with caplog.at_level(logging.WARNING):
        r = client.post(f"/api/films/{fid}/wishlist")
    assert r.get_json() == {"error": "Couldn't reach CheapCharts."}  # unchanged on screen
    assert [rec.getMessage() for rec in caplog.records] == ["wishlist click failed: unexpected answer shape"]


def test_with_no_credentials_configured_the_click_fails_the_same_way(repo):
    app = create_app(repo, today=lambda: D)  # wishlist=None: no credentials file
    app.testing = True
    fid = _film(repo, "Do the Right Thing", 1989, DTRT)
    r = app.test_client().post(f"/api/films/{fid}/wishlist")
    assert r.status_code == 502 and r.get_json() == {"error": "Couldn't reach CheapCharts."}


@pytest.mark.parametrize(
    ("title", "year", "itunes", "history", "target"),
    [
        # $2.99 exactly once, $4.99 again and again — the owner's ruling: the one-off low counts.
        ("Do the Right Thing", 1989, "282538466",
         "2026-08-12:+14.99~2026-08-04:-4.99~2025-08-26:+7.99~2025-08-26:-2.99~2025-08-12:-4.99~2019-02-19:9.99", "3.99"),
        ("Mulholland Dr.", 2001, "1753833311", "2026-05-01:+14.99~2026-04-20:-7.99~2024-01-01:14.99", "8.99"),
    ],
)
@responses.activate
def test_acceptance_a_click_adds_the_film_at_its_lowest_price_ever_plus_one_dollar(
    repo, title, year, itunes, history, target
):
    fid = _film(repo, title, year, itunes)
    responses.get(DETAIL_URL, json=_history(history))
    responses.post(ACCOUNT_URL, json=LOGIN_OK)
    responses.post(WISHLIST_URL, json=EMPTY_READ)  # the film is not on the wishlist yet
    responses.post(WISHLIST_URL, json={"status": "success", "message": "Item added"})
    responses.post(WISHLIST_URL, json={"status": "success", "message": f"init price was changed to {target}"})
    r = _real_client(repo).post(f"/api/films/{fid}/wishlist")
    assert r.status_code == 200 and r.get_json() == {"wishlisted": True}
    # The READ comes first, before the public price call, so a wishlist we cannot read costs
    # CheapCharts nothing at all (brief amendment 1.3).
    assert [_made(c) for c in responses.calls] == [
        "Account.php:login",
        "Wishlist.php:getShortItemList_v2",
        "DetailData.php",
        "Wishlist.php:addItem",
        "Wishlist.php:changeInitPrice",
    ]
    set_target = responses.calls[4].request.url
    assert f"customPrice={target}" in set_target and f"customPriceHd={target}" in set_target
    assert f"idInStore={itunes}" in set_target and "itemType=buymovies" in set_target
    assert repo.wishlisted_film_ids() == {fid}


@responses.activate
def test_acceptance_cheapcharts_unreachable_or_password_refused_marks_nothing(repo):
    fid = _film(repo, "Do the Right Thing", 1989, DTRT)
    client = _real_client(repo)
    # unreachable: `responses` raises ConnectionError for the unregistered login call
    r = client.post(f"/api/films/{fid}/wishlist")
    assert r.status_code == 502 and r.get_json() == {"error": "Couldn't reach CheapCharts."}
    # the password no longer works
    responses.get(DETAIL_URL, json=_history("2020-01-01:4.99"))
    responses.post(ACCOUNT_URL, json={"status": "error", "message": "wrong password"})
    r = client.post(f"/api/films/{fid}/wishlist")
    assert r.status_code == 502 and r.get_json() == {"error": "Couldn't reach CheapCharts."}
    assert repo.wishlisted_film_ids() == set()


@responses.activate
def test_acceptance_a_reshaped_detaildata_answer_is_the_one_failure_line(repo):
    """A `DetailData` shape the API has never sent (F2) must not surface as a 500 — it ends as
    the drawer's one ordinary failure line, and marks nothing."""
    fid = _film(repo, "Do the Right Thing", 1989, DTRT)
    responses.post(ACCOUNT_URL, json=LOGIN_OK)
    responses.post(WISHLIST_URL, json=EMPTY_READ)
    responses.get(DETAIL_URL, json={"results": ["not", "a", "dict"]})
    r = _real_client(repo).post(f"/api/films/{fid}/wishlist")
    assert r.status_code == 502 and r.get_json() == {"error": "Couldn't reach CheapCharts."}
    assert repo.wishlisted_film_ids() == set()


@responses.activate
def test_acceptance_owned_and_unsold_films_never_reach_cheapcharts(repo):
    big_sleep = _film(repo, "The Big Sleep", 1946, "290555722")
    repo.mark_owned(big_sleep, D)
    dolce_vita = _film(repo, "La Dolce Vita", 1960)
    client = _real_client(repo)
    assert client.post(f"/api/films/{big_sleep}/wishlist").status_code == 409
    assert client.post(f"/api/films/{dolce_vita}/wishlist").status_code == 409
    assert len(responses.calls) == 0


def test_delete_un_wishlists_the_film(client, repo, account):
    fid = _film(repo, "Do the Right Thing", 1989, DTRT)
    client.post(f"/api/films/{fid}/wishlist")
    r = client.delete(f"/api/films/{fid}/wishlist")
    assert r.status_code == 200 and r.get_json() == {"wishlisted": False}
    assert account.targets == {} and repo.wishlisted_film_ids() == set()
    assert client.get(f"/api/films/{fid}").get_json()["wishlisted"] is False
    assert client.delete("/api/films/999/wishlist").status_code == 404


def test_a_failed_un_wishlist_is_the_same_failure_line_and_the_heart_stays(client, repo, account):
    fid = _film(repo, "Do the Right Thing", 1989, DTRT)
    client.post(f"/api/films/{fid}/wishlist")
    account.down = True
    r = client.delete(f"/api/films/{fid}/wishlist")
    assert r.status_code == 502 and r.get_json() == {"error": "Couldn't reach CheapCharts."}
    assert repo.wishlisted_film_ids() == {fid}


@responses.activate
def test_acceptance_un_wishlisting_reads_first_then_sends_remove_item(repo):
    fid = _film(repo, "Nashville", 1975, "366474905")
    repo.mark_wishlisted(fid, D)
    responses.post(ACCOUNT_URL, json=LOGIN_OK)
    responses.post(WISHLIST_URL, json={"results": {"movies": [{"idInStore": "366474905", "customPrice": True}]}})
    responses.post(WISHLIST_URL, json={"status": "success", "message": "Item removed"})
    r = _real_client(repo).delete(f"/api/films/{fid}/wishlist")
    assert r.status_code == 200 and r.get_json() == {"wishlisted": False}
    assert [_made(c) for c in responses.calls] == [
        "Account.php:login",
        "Wishlist.php:getShortItemList_v2",
        "Wishlist.php:removeItem",
    ]
    remove = responses.calls[2].request.url
    assert "action=removeItem" in remove and "idInStore=366474905" in remove and "itemType=buymovies" in remove
    assert repo.wishlisted_film_ids() == set()
