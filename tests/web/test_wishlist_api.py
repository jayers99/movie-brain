from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from movie_brain.application.wishlist import WishlistError, WishlistGateway
from movie_brain.domain.models import Film
from movie_brain.web.app import create_app

D = date(2026, 9, 19)
DTRT = "282538466"


class FakePrices:
    def lowest_price(self, itunes_id):
        return Decimal("2.99")


class FakeAccount:
    def __init__(self):
        self.targets = {}
        self.down = False

    def add_item(self, itunes_id):
        if self.down:
            raise WishlistError("down")
        return True

    def set_target(self, itunes_id, target):
        self.targets[itunes_id] = target

    def wishlist_ids(self):
        return list(self.targets)


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


def test_with_no_credentials_configured_the_click_fails_the_same_way(repo):
    app = create_app(repo, today=lambda: D)  # wishlist=None: no credentials file
    app.testing = True
    fid = _film(repo, "Do the Right Thing", 1989, DTRT)
    r = app.test_client().post(f"/api/films/{fid}/wishlist")
    assert r.status_code == 502 and r.get_json() == {"error": "Couldn't reach CheapCharts."}
