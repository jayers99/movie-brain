from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from movie_brain.application.wishlist import NotForSale, WishlistError, WishlistGateway, wishlist_film
from movie_brain.domain.models import Film
from movie_brain.domain.wishlist import target_price

D = date(2026, 9, 19)


def _film(repo, title, year, itunes=None):
    fid = repo.create_film(Film(title, year, "Dir", ""))
    assert fid is not None
    if itunes:
        repo.set_external_id(fid, "itunes", itunes, D)
    return fid


class FakePrices:
    def __init__(self, lows):
        self.lows = lows

    def lowest_price(self, itunes_id):
        return self.lows.get(itunes_id)


class FakeAccount:
    def __init__(self, listed=()):
        self.calls = []
        self.listed = list(listed)

    def add_item(self, itunes_id):
        self.calls.append(("add", itunes_id))
        if itunes_id not in self.listed:
            self.listed.append(itunes_id)
        return True

    def set_target(self, itunes_id, target):
        self.calls.append(("target", itunes_id, target))

    def wishlist_ids(self):
        self.calls.append(("read",))
        return list(self.listed)


def test_target_is_the_lowest_price_ever_plus_one_dollar():
    assert target_price(Decimal("2.99")) == Decimal("3.99")  # Do the Right Thing: a one-off low still counts
    assert target_price(Decimal("7.99")) == Decimal("8.99")  # Mulholland Dr.


def test_mark_wishlisted_round_trips_and_reports_missing(repo):
    a = _film(repo, "Alpha", 1950)
    assert repo.get_view(a, D).wishlisted is False
    assert repo.mark_wishlisted(a, D) is True
    assert repo.mark_wishlisted(a, D) is True  # idempotent
    assert repo.wishlisted_film_ids() == {a}
    assert repo.get_view(a, D).wishlisted is True
    assert [v.wishlisted for v in repo.list_views("criterion", D) if v.id == a] == [True]
    assert repo.mark_wishlisted(999, D) is None


def test_itunes_id_for_reads_the_stored_store_id(repo):
    a, b = _film(repo, "Alpha", 1950, "282538466"), _film(repo, "Beta", 1960)
    assert repo.itunes_id_for(a) == "282538466" and repo.itunes_id_for(b) is None


def test_a_click_adds_the_film_at_lowest_plus_one_and_marks_it(repo):
    dtrt = _film(repo, "Do the Right Thing", 1989, "282538466")
    account = FakeAccount()
    wishlist_film(repo, WishlistGateway(FakePrices({"282538466": Decimal("2.99")}), account), dtrt, D)
    assert ("add", "282538466") in account.calls
    assert ("target", "282538466", Decimal("3.99")) in account.calls
    assert repo.wishlisted_film_ids() == {dtrt}


def test_an_owned_or_unsold_film_is_refused_before_cheapcharts_is_asked(repo):
    owned = _film(repo, "The Big Sleep", 1946, "290555722")
    repo.mark_owned(owned, D)
    unsold = _film(repo, "La Dolce Vita", 1960)
    account = FakeAccount()
    gateway = WishlistGateway(FakePrices({}), account)
    for fid in (owned, unsold):
        with pytest.raises(NotForSale):
            wishlist_film(repo, gateway, fid, D)
    with pytest.raises(LookupError):
        wishlist_film(repo, gateway, 999, D)
    assert account.calls == [] and repo.wishlisted_film_ids() == set()


def test_no_price_history_at_all_fails_and_marks_nothing(repo):
    fid = _film(repo, "Obscure", 1970, "111")
    account = FakeAccount()
    with pytest.raises(WishlistError):
        wishlist_film(repo, WishlistGateway(FakePrices({}), account), fid, D)
    assert account.calls == [] and repo.wishlisted_film_ids() == set()


def test_an_already_wishlisted_film_is_left_alone(repo):
    """The button never shows on it; the route still must not touch a hand-set target."""
    fid = _film(repo, "The Leopard", 1963, "273058482")
    repo.mark_wishlisted(fid, D)
    account = FakeAccount()
    wishlist_film(repo, WishlistGateway(FakePrices({"273058482": Decimal("4.99")}), account), fid, D)
    assert account.calls == []
