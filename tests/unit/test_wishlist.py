from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
import requests
import responses

from movie_brain.application.wishlist import (
    NotForSale,
    RefreshReport,
    ResolvedFilm,
    ResolveUnknownReport,
    WishlistError,
    WishlistGateway,
    refresh_wishlist,
    resolve_unknown_wishlist,
    unwishlist_film,
    wishlist_film,
)
from movie_brain.domain.models import Film
from movie_brain.domain.wishlist import target_price
from movie_brain.infrastructure.cheapcharts import (
    DETAIL_URL,
    CheapChartsClient,
    CheapChartsError,
    RateLimited,
    WishlistItem,
)

D = date(2026, 9, 19)


def _film(repo, title, year, itunes=None):
    fid = repo.create_film(Film(title, year, "Dir", ""))
    assert fid is not None
    if itunes:
        repo.set_external_id(fid, "itunes", itunes, D)
    return fid


class FakePrices:
    def __init__(self, lows, imdb=None):
        self.lows = lows
        self.imdb = dict(imdb or {})  # store id → the IMDb id CheapCharts files the product under
        self.asked = []

    def lowest_price(self, itunes_id):
        return self.lows.get(itunes_id)

    def imdb_id_for(self, itunes_id):
        self.asked.append(itunes_id)
        return self.imdb.get(itunes_id)


class FakeAccount:
    """`listed` is what CheapCharts holds; `targeted` is which of those carry a custom price —
    the two things the real read reports, and the two the click now decides on."""

    def __init__(self, listed=(), targeted=()):
        self.calls = []
        self.listed = list(listed)
        self.targeted = set(targeted)

    def add_item(self, itunes_id):
        self.calls.append(("add", itunes_id))
        if itunes_id not in self.listed:
            self.listed.append(itunes_id)
        return True

    def set_target(self, itunes_id, target):
        self.calls.append(("target", itunes_id, target))
        self.targeted.add(itunes_id)

    def wishlist_items(self):
        self.calls.append(("read",))
        return [WishlistItem(i, custom_target=i in self.targeted) for i in self.listed]

    def remove_item(self, itunes_id):
        self.calls.append(("remove", itunes_id))
        if itunes_id in self.listed:
            self.listed.remove(itunes_id)
        self.targeted.discard(itunes_id)
        return True


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


def test_itunes_id_for_and_the_drawer_link_name_the_same_id_when_a_film_holds_two(repo):
    """`itunes_id_for` and `_VIEW_SQL`'s `itunes_id` subquery must be the same deterministic
    scalar pick, or the wishlisted product and the drawer's link could silently disagree."""
    from movie_brain.infrastructure.cheapcharts import product_url

    fid = _film(repo, "A", 1950, "9")
    repo.set_external_id(fid, "itunes", "10", D)
    picked = repo.itunes_id_for(fid)
    assert picked is not None
    assert repo.get_view(fid, D).cheapcharts_url == product_url(picked)


def test_a_click_adds_the_film_at_lowest_plus_one_and_marks_it(repo):
    dtrt = _film(repo, "Do the Right Thing", 1989, "282538466")
    account = FakeAccount()
    wishlist_film(repo, WishlistGateway(FakePrices({"282538466": Decimal("2.99")}), account), dtrt, D)
    assert account.calls == [("read",), ("add", "282538466"), ("target", "282538466", Decimal("3.99"))]
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
    assert account.calls == [("read",)] and repo.wishlisted_film_ids() == set()


@responses.activate
def test_a_reshaped_detaildata_answer_ends_as_wishlist_error_not_a_crash(repo):
    """`lowest_price` swallows a `results` shape it has never seen and returns None (F2b) —
    proving here that the click still ends as the ONE WishlistError, through the ordinary
    no-price-history path, and marks nothing."""
    fid = _film(repo, "Do the Right Thing", 1989, "282538466")
    responses.get(DETAIL_URL, json={"results": ["not", "a", "dict"]})
    account = FakeAccount()
    with pytest.raises(WishlistError):
        wishlist_film(repo, WishlistGateway(CheapChartsClient(delay_s=0), account), fid, D)
    assert account.calls == [("read",)] and repo.wishlisted_film_ids() == set()


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


def test_replace_wishlist_never_hearts_a_tombstoned_film(repo):
    """A tombstoned film keeps its external_ids row (collectors never delete) but must never be
    hearted or counted — it has no read model of its own to show a heart on."""
    gone = _film(repo, "Ghost", 1958, "42")
    repo.tombstone_film(gone, D)
    assert repo.replace_wishlist(["42"], D) == 0
    assert repo.wishlisted_film_ids() == set()


def test_a_film_holding_two_store_ids_is_hearted_by_either(repo):
    fid = _film(repo, "A", 1950, "1")
    repo.set_external_id(fid, "itunes", "2", D)
    assert repo.replace_wishlist(["2"], D) == 1 and repo.wishlisted_film_ids() == {fid}


def test_itunes_ids_for_lists_them_all_while_itunes_id_for_keeps_its_single_pick(repo):
    """`itunes` is a claim authority and may repeat, and since amendment 1.4 it really does: the
    wishlist names one product and the store lookup another. The click verbs act on every one of
    them; the drawer's link is still the MIN pick."""
    fid = _film(repo, "A", 1950, "20")
    repo.set_external_id(fid, "itunes", "3", D)
    assert repo.itunes_ids_for(fid) == ["20", "3"] and repo.itunes_id_for(fid) == "20"
    assert repo.itunes_ids_for(_film(repo, "B", 1960)) == []


def test_itunes_ids_held_is_every_live_films_store_id(repo):
    """What the resolver already knows. A tombstoned film keeps its `external_ids` row but shows
    no heart, so its id is NOT held here — the wishlist entry behind it is genuinely unplaced."""
    _film(repo, "A", 1950, "1")
    _film(repo, "B", 1960)
    gone = _film(repo, "Ghost", 1958, "42")
    repo.tombstone_film(gone, D)
    assert repo.itunes_ids_held() == {"1"}


def test_film_title_year_answers_for_a_live_film_only(repo):
    fid = _film(repo, "A", 1950)
    yearless = _film(repo, "B", None)
    gone = _film(repo, "Ghost", 1958)
    repo.tombstone_film(gone, D)
    assert repo.film_title_year(fid) == ("A", 1950) and repo.film_title_year(yearless) == ("B", None)
    assert repo.film_title_year(gone) is None and repo.film_title_year(999) is None


def test_refresh_reads_the_wishlist_and_reports_how_much_of_it_we_know(repo):
    known = _film(repo, "The Leopard", 1963, "273058482")
    report = refresh_wishlist(repo, FakeAccount(listed=["273058482", "555", "556"]), D)
    assert report == RefreshReport(on_cheapcharts=3, known=1) and repo.wishlisted_film_ids() == {known}


def test_a_failed_refresh_keeps_the_last_known_hearts(repo):
    fid = _film(repo, "The Leopard", 1963, "273058482")
    repo.mark_wishlisted(fid, D)

    class Down(FakeAccount):
        def wishlist_items(self):
            raise requests.ConnectionError("offline")

    with pytest.raises(WishlistError):
        refresh_wishlist(repo, Down(), D)
    assert repo.wishlisted_film_ids() == {fid}


def _unplaced(repo, title="Scarlet Street", year=1945, tt="tt9000001"):
    """A film movie-brain knows by its IMDb id and holds no store id for — the second hands-on
    finding: on the wishlist, and so no heart and no button."""
    fid = _film(repo, title, year)
    repo.set_external_id(fid, "imdb", tt, D)
    return fid


def test_resolve_unknown_joins_the_wishlists_own_store_id_by_imdb_id_and_hearts_the_film(repo):
    fid = _unplaced(repo)
    prices = FakePrices({}, imdb={"555": "tt9000001"})
    report = resolve_unknown_wishlist(repo, WishlistGateway(prices, FakeAccount(listed=["555"])), D, apply=True)
    assert report == ResolveUnknownReport(
        on_cheapcharts=1,
        unknown=1,
        resolved=(ResolvedFilm(fid, "Scarlet Street", 1945, "555"),),
        not_in_catalogue=0,
        no_imdb=0,
        rate_limited=False,
        known=1,
    )
    assert repo.itunes_ids_for(fid) == ["555"] and repo.wishlisted_film_ids() == {fid}


def test_a_dry_run_names_the_film_it_would_place_and_stores_nothing(repo):
    fid = _unplaced(repo)
    prices = FakePrices({}, imdb={"555": "tt9000001"})
    report = resolve_unknown_wishlist(repo, WishlistGateway(prices, FakeAccount(listed=["555"])), D, apply=False)
    assert report.resolved == (ResolvedFilm(fid, "Scarlet Street", 1945, "555"),)
    assert report.known == 0  # the hearts as they would be WITHOUT the new ids
    assert repo.itunes_ids_for(fid) == [] and repo.wishlisted_film_ids() == set()


def test_a_store_id_a_film_already_holds_is_never_asked_about(repo):
    placed = _film(repo, "Placed", 1950, "111")
    prices = FakePrices({}, imdb={})
    report = resolve_unknown_wishlist(repo, WishlistGateway(prices, FakeAccount(listed=["111"])), D, apply=True)
    assert prices.asked == [] and report.unknown == 0 and report.known == 1
    assert repo.wishlisted_film_ids() == {placed}


def test_a_product_cheapcharts_cannot_place_here_is_counted_not_resolved(repo):
    """Two ways of staying unplaced: CheapCharts has no IMDb id for the product (a hole in their
    index), and it names one no film here holds (the film is simply not in movie-brain)."""
    prices = FakePrices({}, imdb={"2": "tt9000404"})
    report = resolve_unknown_wishlist(repo, WishlistGateway(prices, FakeAccount(listed=["1", "2"])), D, apply=True)
    assert (report.no_imdb, report.not_in_catalogue, report.resolved) == (1, 1, ())
    assert report.unknown == 2 and report.known == 0


def test_a_film_that_already_holds_a_store_id_gains_the_second_and_is_hearted(repo):
    """The wishlist names one product of a film and the store lookup another — `itunes` is a
    claim authority, so the film simply holds both."""
    fid = _unplaced(repo, "Two Products", 1960, "tt9000002")
    repo.set_external_id(fid, "itunes", "111", D)
    prices = FakePrices({}, imdb={"555": "tt9000002"})
    report = resolve_unknown_wishlist(repo, WishlistGateway(prices, FakeAccount(listed=["555"])), D, apply=True)
    assert report.resolved == (ResolvedFilm(fid, "Two Products", 1960, "555"),)
    assert repo.itunes_ids_for(fid) == ["111", "555"] and repo.wishlisted_film_ids() == {fid}


def test_a_rate_limit_stops_the_run_early_and_keeps_what_it_stored(repo):
    """Nothing is lost: a stored id is never asked about again, so re-running resumes."""
    first, second = _unplaced(repo, "First", 1950, "tt9000003"), _unplaced(repo, "Second", 1960, "tt9000004")

    class Limited(FakePrices):
        def imdb_id_for(self, itunes_id):
            self.asked.append(itunes_id)
            if itunes_id == "2":
                raise RateLimited("https://secret")
            return self.imdb.get(itunes_id)

    prices = Limited({}, imdb={"1": "tt9000003", "2": "tt9000004"})
    report = resolve_unknown_wishlist(repo, WishlistGateway(prices, FakeAccount(listed=["1", "2"])), D, apply=True)
    assert report.rate_limited is True and prices.asked == ["1", "2"]
    assert report.resolved == (ResolvedFilm(first, "First", 1950, "1"),)
    assert repo.itunes_ids_for(first) == ["1"] and repo.itunes_ids_for(second) == []
    assert repo.wishlisted_film_ids() == {first}  # the read still replaced the hearts


def test_a_film_a_human_hid_is_never_given_a_store_id(repo):
    gone = _unplaced(repo, "Ghost", 1958, "tt9000005")
    repo.tombstone_film(gone, D)
    prices = FakePrices({}, imdb={"555": "tt9000005"})
    report = resolve_unknown_wishlist(repo, WishlistGateway(prices, FakeAccount(listed=["555"])), D, apply=True)
    assert report.resolved == () and report.not_in_catalogue == 1
    assert repo.itunes_ids_for(gone) == []


def test_a_product_a_hidden_film_already_holds_is_left_alone(repo):
    """`external_ids` is UNIQUE on (authority, value) and a tombstoned film keeps its rows, so
    the live film cannot take that product's id — refused here rather than raised at the write."""
    gone = _film(repo, "Ghost", 1958, "555")
    repo.tombstone_film(gone, D)
    live = _unplaced(repo, "Live", 1960, "tt9000006")
    prices = FakePrices({}, imdb={"555": "tt9000006"})
    report = resolve_unknown_wishlist(repo, WishlistGateway(prices, FakeAccount(listed=["555"])), D, apply=True)
    assert report.resolved == () and report.not_in_catalogue == 1
    assert repo.itunes_ids_for(live) == []


def test_a_failed_read_resolves_nothing_and_asks_cheapcharts_nothing(repo):
    _unplaced(repo)

    class Down(FakeAccount):
        def wishlist_items(self):
            raise CheapChartsError("unexpected answer shape")

    prices = FakePrices({}, imdb={"555": "tt9000001"})
    with pytest.raises(WishlistError, match="unexpected answer shape"):
        resolve_unknown_wishlist(repo, WishlistGateway(prices, Down(listed=["555"])), D, apply=True)
    assert prices.asked == []


def test_a_remote_failure_mid_run_becomes_the_one_wishlist_error(repo):
    _unplaced(repo)

    class Down(FakePrices):
        def imdb_id_for(self, itunes_id):
            raise requests.ConnectionError("https://secret")

    with pytest.raises(WishlistError) as exc:
        resolve_unknown_wishlist(repo, WishlistGateway(Down({}), FakeAccount(listed=["555"])), D, apply=True)
    assert str(exc.value) == "ConnectionError" and "secret" not in str(exc.value)


def test_a_click_reads_the_wishlist_first_and_replaces_every_heart(repo):
    dtrt = _film(repo, "Do the Right Thing", 1989, "282538466")
    stale = _film(repo, "Bought Since", 1990, "777")
    leopard = _film(repo, "The Leopard", 1963, "273058482")
    repo.mark_wishlisted(stale, D)
    account = FakeAccount(listed=["273058482"])
    wishlist_film(repo, WishlistGateway(FakePrices({"282538466": Decimal("2.99")}), account), dtrt, D)
    assert [c[0] for c in account.calls] == ["read", "add", "target"]
    assert repo.wishlisted_film_ids() == {dtrt, leopard}


def test_a_failed_read_writes_nothing_to_cheapcharts_or_locally(repo):
    """Amendment 1.3's rule: the read is the first thing every click does, and a click that
    cannot read the wishlist writes nowhere — no add, no target, no heart."""
    fid = _film(repo, "Do the Right Thing", 1989, "282538466")
    other = _film(repo, "Bought Since", 1990, "777")
    repo.mark_wishlisted(other, D)

    class NoRead(FakeAccount):
        def wishlist_items(self):
            self.calls.append(("read",))
            raise CheapChartsError("unexpected answer shape")

    account = NoRead()
    with pytest.raises(WishlistError):
        wishlist_film(repo, WishlistGateway(FakePrices({"282538466": Decimal("2.99")}), account), fid, D)
    assert account.calls == [("read",)]
    assert repo.wishlisted_film_ids() == {other}  # the stale heart is kept, not replaced


def test_a_film_already_on_the_wishlist_with_a_hand_set_target_keeps_it_untouched(repo):
    """The invariant 1.0 promised and only the pre-read can enforce: the local hearts may be
    stale, so "already there" is decided by what CheapCharts says at the moment of the click."""
    fid = _film(repo, "The Leopard", 1963, "273058482")
    account = FakeAccount(listed=["273058482"], targeted=["273058482"])
    wishlist_film(repo, WishlistGateway(FakePrices({"273058482": Decimal("4.99")}), account), fid, D)
    assert account.calls == [("read",)]  # no add, and above all no target
    assert repo.wishlisted_film_ids() == {fid}  # it still gets its heart


def test_a_film_on_the_wishlist_without_a_target_gets_the_target_and_nothing_else(repo):
    """A half-finished earlier click (added, target never set) is repaired by clicking again."""
    fid = _film(repo, "Do the Right Thing", 1989, "282538466")
    account = FakeAccount(listed=["282538466"])
    wishlist_film(repo, WishlistGateway(FakePrices({"282538466": Decimal("2.99")}), account), fid, D)
    assert account.calls == [("read",), ("target", "282538466", Decimal("3.99"))]
    assert repo.wishlisted_film_ids() == {fid}


def test_a_film_with_two_store_ids_repairs_the_product_that_is_actually_on_the_wishlist(repo):
    """Amendment 1.4's consequence: a film can hold two store ids — the wishlist's own product
    and the store lookup's — so "which item is this film's?" is the first of them the read holds,
    never the one the drawer happens to link to."""
    fid = _film(repo, "Two Products", 1960, "111")  # the drawer's pick (MIN)
    repo.set_external_id(fid, "itunes", "555", D)  # the product the wishlist names
    account = FakeAccount(listed=["555"])
    wishlist_film(repo, WishlistGateway(FakePrices({"555": Decimal("2.99")}), account), fid, D)
    assert account.calls == [("read",), ("target", "555", Decimal("3.99"))]
    assert repo.wishlisted_film_ids() == {fid}


def test_a_film_with_two_store_ids_keeps_the_hand_set_target_on_whichever_one_carries_it(repo):
    fid = _film(repo, "Two Products", 1960, "111")
    repo.set_external_id(fid, "itunes", "555", D)
    account = FakeAccount(listed=["555"], targeted=["555"])
    wishlist_film(repo, WishlistGateway(FakePrices({"555": Decimal("2.99")}), account), fid, D)
    assert account.calls == [("read",)]  # no add, and above all no target
    assert repo.wishlisted_film_ids() == {fid}


def test_a_refused_add_is_a_failure_and_marks_nothing(repo):
    """No fallback believes a write without proof: the API said no, so the click failed."""
    fid = _film(repo, "Do the Right Thing", 1989, "282538466")

    class Refusing(FakeAccount):
        def add_item(self, itunes_id):
            self.calls.append(("add", itunes_id))
            return False

    account = Refusing()
    with pytest.raises(WishlistError, match="add refused"):
        wishlist_film(repo, WishlistGateway(FakePrices({"282538466": Decimal("2.99")}), account), fid, D)
    assert [c[0] for c in account.calls] == ["read", "add"]  # the target is never set
    assert repo.wishlisted_film_ids() == set()


@pytest.mark.parametrize(
    ("boom", "reason"),
    [
        (requests.ConnectionError("https://secret"), "ConnectionError"),
        (RateLimited("https://secret"), "rate limited"),
        (CheapChartsError("unexpected answer shape"), "unexpected answer shape"),
    ],
)
def test_every_remote_failure_becomes_the_one_wishlist_error_and_marks_nothing(repo, boom, reason):
    """The reason is NAMED (amendment 1.3) so a failure is diagnosable off-screen, but only in
    OUR words: a CheapChartsError's message is our own wording by construction, while anything
    from `requests` is named by its class, because its text carries the URL."""
    fid = _film(repo, "Do the Right Thing", 1989, "282538466")

    class Failing(FakeAccount):
        def set_target(self, itunes_id, target):
            raise boom

    with pytest.raises(WishlistError) as exc:
        wishlist_film(repo, WishlistGateway(FakePrices({"282538466": Decimal("2.99")}), Failing()), fid, D)
    assert repo.wishlisted_film_ids() == set()
    assert str(exc.value) == reason and "secret" not in str(exc.value)


def test_merge_moves_the_heart_survivor_wins(repo):
    a, b = _film(repo, "Alpha", 1950), _film(repo, "Alpha", 1951)
    repo.mark_wishlisted(b, D)
    repo.merge_film(b, a, D)
    assert repo.wishlisted_film_ids() == {a}
    c, d = _film(repo, "Beta", 1960), _film(repo, "Beta", 1961)
    repo.mark_wishlisted(c, D)
    repo.mark_wishlisted(d, D)
    report = repo.merge_film(d, c, D)
    assert report.dropped.get("cheapcharts_wishlist") == 1 and repo.wishlisted_film_ids() == {a, c}


def test_unmark_wishlisted_is_idempotent(repo):
    fid = _film(repo, "Nashville", 1975, "366474905")
    repo.mark_wishlisted(fid, D)
    repo.unmark_wishlisted(fid)
    repo.unmark_wishlisted(fid)
    assert repo.wishlisted_film_ids() == set() and repo.get_view(fid, D).wishlisted is False


def test_un_wishlisting_reads_the_wishlist_first_and_replaces_every_heart(repo):
    nashville = _film(repo, "Nashville", 1975, "366474905")
    leopard = _film(repo, "The Leopard", 1963, "273058482")
    stale = _film(repo, "Bought Since", 1990, "777")
    for fid in (nashville, stale):
        repo.mark_wishlisted(fid, D)
    account = FakeAccount(listed=["366474905", "273058482"])
    unwishlist_film(repo, WishlistGateway(FakePrices({}), account), nashville, D)
    assert [c[0] for c in account.calls] == ["read", "remove"]
    assert repo.wishlisted_film_ids() == {leopard}


def test_an_owned_wishlisted_film_can_be_un_wishlisted(repo):
    fid = _film(repo, "The Big Sleep", 1946, "290555722")
    repo.mark_owned(fid, D)
    repo.mark_wishlisted(fid, D)
    unwishlist_film(repo, WishlistGateway(FakePrices({}), FakeAccount(listed=["290555722"])), fid, D)
    assert repo.wishlisted_film_ids() == set()


def test_un_wishlisting_a_film_that_is_not_wishlisted_asks_cheapcharts_nothing(repo):
    fid = _film(repo, "Nashville", 1975, "366474905")
    account = FakeAccount(listed=["366474905"])
    unwishlist_film(repo, WishlistGateway(FakePrices({}), account), fid, D)
    assert account.calls == []
    with pytest.raises(LookupError):
        unwishlist_film(repo, WishlistGateway(FakePrices({}), account), 999, D)


def test_un_wishlisting_a_locally_hearted_film_with_no_store_id_drops_the_heart_with_no_account_call(repo):
    """Unreachable today (the button never shows without a store id), but honest: the early
    return used to answer success while the `cheapcharts_wishlist` row stayed, so the heart came
    back on reload. It must take the heart off itself instead of pretending nothing is wrong."""
    fid = _film(repo, "No Store Id", 1970)
    repo.mark_wishlisted(fid, D)
    account = FakeAccount()
    unwishlist_film(repo, WishlistGateway(FakePrices({}), account), fid, D)
    assert account.calls == [] and repo.wishlisted_film_ids() == set()


def test_un_wishlisting_a_film_cheapcharts_no_longer_holds_removes_nothing_and_drops_the_heart(repo):
    """The local heart was stale — somebody took it off on CheapCharts. The pre-read says so,
    the heart goes, and no removal is sent for a film that is already gone."""
    fid = _film(repo, "Nashville", 1975, "366474905")
    repo.mark_wishlisted(fid, D)
    account = FakeAccount(listed=[])
    unwishlist_film(repo, WishlistGateway(FakePrices({}), account), fid, D)
    assert account.calls == [("read",)] and repo.wishlisted_film_ids() == set()


def test_a_refused_remove_is_a_failure_and_the_heart_stays(repo):
    fid = _film(repo, "Nashville", 1975, "366474905")
    repo.mark_wishlisted(fid, D)

    class Sticky(FakeAccount):
        def remove_item(self, itunes_id):
            self.calls.append(("remove", itunes_id))
            return False

    with pytest.raises(WishlistError, match="remove refused"):
        unwishlist_film(repo, WishlistGateway(FakePrices({}), Sticky(listed=["366474905"])), fid, D)
    assert repo.wishlisted_film_ids() == {fid}


def test_un_wishlisting_a_film_with_two_store_ids_removes_the_product_the_wishlist_holds(repo):
    """Task 9's deferred finding, real since amendment 1.4: the heart can come through a store
    id the drawer does not link to, and removing only the drawer's pick left the film on
    CheapCharts — so the next click read it back and refused, forever."""
    fid = _film(repo, "Two Products", 1960, "111")
    repo.set_external_id(fid, "itunes", "555", D)
    repo.mark_wishlisted(fid, D)
    account = FakeAccount(listed=["555"])
    unwishlist_film(repo, WishlistGateway(FakePrices({}), account), fid, D)
    assert account.calls == [("read",), ("remove", "555")]
    assert account.listed == [] and repo.wishlisted_film_ids() == set()


def test_un_wishlisting_a_film_with_two_store_ids_removes_both_when_both_are_listed(repo):
    fid = _film(repo, "Two Products", 1960, "111")
    repo.set_external_id(fid, "itunes", "555", D)
    repo.mark_wishlisted(fid, D)
    account = FakeAccount(listed=["111", "555"])
    unwishlist_film(repo, WishlistGateway(FakePrices({}), account), fid, D)
    assert account.calls == [("read",), ("remove", "111"), ("remove", "555")]
    assert account.listed == [] and repo.wishlisted_film_ids() == set()


def test_a_second_product_the_api_refuses_to_remove_is_a_failure_and_the_heart_stays(repo):
    """Each removal must be accepted: a film still on the wishlist under its other product is
    still on the wishlist."""
    fid = _film(repo, "Two Products", 1960, "111")
    repo.set_external_id(fid, "itunes", "555", D)
    repo.mark_wishlisted(fid, D)

    class Sticky(FakeAccount):
        def remove_item(self, itunes_id):
            self.calls.append(("remove", itunes_id))
            return itunes_id != "555"

    with pytest.raises(WishlistError, match="remove refused"):
        unwishlist_film(repo, WishlistGateway(FakePrices({}), Sticky(listed=["111", "555"])), fid, D)
    assert repo.wishlisted_film_ids() == {fid}


def test_a_failed_read_sends_no_removal_and_keeps_the_heart(repo):
    fid = _film(repo, "Nashville", 1975, "366474905")
    repo.mark_wishlisted(fid, D)

    class NoRead(FakeAccount):
        def wishlist_items(self):
            self.calls.append(("read",))
            raise CheapChartsError("unexpected answer shape")

    account = NoRead(listed=["366474905"])
    with pytest.raises(WishlistError):
        unwishlist_film(repo, WishlistGateway(FakePrices({}), account), fid, D)
    assert account.calls == [("read",)] and repo.wishlisted_film_ids() == {fid}


def test_a_remote_failure_while_removing_becomes_the_one_wishlist_error(repo):
    fid = _film(repo, "Nashville", 1975, "366474905")
    repo.mark_wishlisted(fid, D)

    class Down(FakeAccount):
        def remove_item(self, itunes_id):
            raise requests.ConnectionError("offline")

    with pytest.raises(WishlistError) as exc:
        unwishlist_film(repo, WishlistGateway(FakePrices({}), Down(listed=["366474905"])), fid, D)
    assert str(exc.value) == "ConnectionError" and repo.wishlisted_film_ids() == {fid}
