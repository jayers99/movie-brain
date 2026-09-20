from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
import requests

from movie_brain.application.wishlist import (
    NotForSale,
    RefreshReport,
    WishlistError,
    WishlistGateway,
    refresh_wishlist,
    wishlist_film,
)
from movie_brain.domain.models import Film
from movie_brain.domain.wishlist import target_price
from movie_brain.infrastructure.cheapcharts import CheapChartsError, RateLimited

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


def test_replace_wishlist_is_wholesale_and_keeps_the_date_of_a_film_that_stays(repo):
    stays, goes, arrives = _film(repo, "A", 1950, "1"), _film(repo, "B", 1951, "2"), _film(repo, "C", 1952, "3")
    repo.replace_wishlist(["1", "2", "999"], date(2026, 9, 1))  # 999: on CheapCharts, unknown here
    assert repo.wishlisted_film_ids() == {stays, goes}
    assert repo.replace_wishlist(["1", "3"], D) == 2  # B was bought or removed on CheapCharts
    assert repo.wishlisted_film_ids() == {stays, arrives}
    with repo._conn() as c:
        rows = dict(c.execute("SELECT film_id, added_on FROM cheapcharts_wishlist").fetchall())
    assert rows == {stays: "2026-09-01", arrives: "2026-09-19"}


def test_a_film_holding_two_store_ids_is_hearted_by_either(repo):
    fid = _film(repo, "A", 1950, "1")
    repo.set_external_id(fid, "itunes", "2", D)
    assert repo.replace_wishlist(["2"], D) == 1 and repo.wishlisted_film_ids() == {fid}


def test_refresh_reads_the_wishlist_and_reports_how_much_of_it_we_know(repo):
    known = _film(repo, "The Leopard", 1963, "273058482")
    report = refresh_wishlist(repo, FakeAccount(listed=["273058482", "555", "556"]), D)
    assert report == RefreshReport(on_cheapcharts=3, known=1) and repo.wishlisted_film_ids() == {known}


def test_a_failed_refresh_keeps_the_last_known_hearts(repo):
    fid = _film(repo, "The Leopard", 1963, "273058482")
    repo.mark_wishlisted(fid, D)

    class Down(FakeAccount):
        def wishlist_ids(self):
            raise requests.ConnectionError("offline")

    with pytest.raises(WishlistError):
        refresh_wishlist(repo, Down(), D)
    assert repo.wishlisted_film_ids() == {fid}


def test_a_click_reads_the_wishlist_back_and_replaces_every_heart(repo):
    dtrt = _film(repo, "Do the Right Thing", 1989, "282538466")
    stale = _film(repo, "Bought Since", 1990, "777")
    leopard = _film(repo, "The Leopard", 1963, "273058482")
    repo.mark_wishlisted(stale, D)
    account = FakeAccount(listed=["273058482"])
    wishlist_film(repo, WishlistGateway(FakePrices({"282538466": Decimal("2.99")}), account), dtrt, D)
    assert [c[0] for c in account.calls] == ["add", "target", "read"]
    assert repo.wishlisted_film_ids() == {dtrt, leopard}


def test_a_refused_add_still_sets_the_target_and_the_read_back_decides(repo):
    """A half-finished earlier click (added, target never set) is repaired by Try again."""
    fid = _film(repo, "Do the Right Thing", 1989, "282538466")

    class AlreadyThere(FakeAccount):
        def add_item(self, itunes_id):
            self.calls.append(("add", itunes_id))
            return False

    there = AlreadyThere(listed=["282538466"])
    wishlist_film(repo, WishlistGateway(FakePrices({"282538466": Decimal("2.99")}), there), fid, D)
    assert ("target", "282538466", Decimal("3.99")) in there.calls and repo.wishlisted_film_ids() == {fid}

    other = _film(repo, "Mulholland Dr.", 2001, "1753833311")
    absent = AlreadyThere(listed=[])  # refused for some other reason: the read-back does not hold it
    with pytest.raises(WishlistError):
        wishlist_film(repo, WishlistGateway(FakePrices({"1753833311": Decimal("7.99")}), absent), other, D)
    assert other not in repo.wishlisted_film_ids()


def test_when_the_read_back_fails_an_accepted_add_is_believed_and_a_refused_one_is_not(repo):
    fid = _film(repo, "Do the Right Thing", 1989, "282538466")
    prices = FakePrices({"282538466": Decimal("2.99")})

    class NoRead(FakeAccount):
        def wishlist_ids(self):
            raise CheapChartsError("read")

    wishlist_film(repo, WishlistGateway(prices, NoRead()), fid, D)
    assert repo.wishlisted_film_ids() == {fid}

    class RefusedNoRead(NoRead):
        def add_item(self, itunes_id):
            return False

    other = _film(repo, "Mulholland Dr.", 2001, "1753833311")
    with pytest.raises(WishlistError):
        wishlist_film(repo, WishlistGateway(FakePrices({"1753833311": Decimal("7.99")}), RefusedNoRead()), other, D)
    assert other not in repo.wishlisted_film_ids()


@pytest.mark.parametrize("boom", [requests.ConnectionError("x"), RateLimited("x"), CheapChartsError("x")])
def test_every_remote_failure_becomes_the_one_wishlist_error_and_marks_nothing(repo, boom):
    fid = _film(repo, "Do the Right Thing", 1989, "282538466")

    class Failing(FakeAccount):
        def set_target(self, itunes_id, target):
            raise boom

    with pytest.raises(WishlistError) as exc:
        wishlist_film(repo, WishlistGateway(FakePrices({"282538466": Decimal("2.99")}), Failing()), fid, D)
    assert repo.wishlisted_film_ids() == set()
    assert str(exc.value) == type(boom).__name__  # the class name only — never a message that could carry a secret
