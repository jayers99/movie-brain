"""Wishlist it (brief 2026-09-19-price-watch): put a film on the owner's CheapCharts wishlist at
its lowest price ever plus one dollar, and mirror which films are there so the row can show a
heart. The wishlist itself stays on CheapCharts — it alerts his phone and makes buying easy.

The two Protocols are the seam: `infrastructure/cheapcharts.py` implements them over HTTP, and
the web tests drive the routes with fakes, so nothing in a test run can reach a real account.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

import requests

from movie_brain.domain.wishlist import target_price
from movie_brain.infrastructure.cheapcharts import CheapChartsError, RateLimited, WishlistItem
from movie_brain.infrastructure.database import Repository


class PriceSource(Protocol):
    def lowest_price(self, itunes_id: str) -> Decimal | None: ...


class WishlistAccount(Protocol):
    def add_item(self, itunes_id: str) -> bool: ...

    def set_target(self, itunes_id: str, target: Decimal) -> None: ...

    def wishlist_items(self) -> list[WishlistItem]: ...

    def remove_item(self, itunes_id: str) -> bool: ...


@dataclass(frozen=True)
class WishlistGateway:
    prices: PriceSource
    account: WishlistAccount


class WishlistError(Exception):
    """Anything that ends as the drawer's "Couldn't reach CheapCharts." — nothing was marked."""


class NotForSale(Exception):
    """Owned, or no store id: the button never shows on such a film, so this is a stale page."""


# Everything the adapters can raise, re-raised as the one WishlistError by `_failed`.
_REMOTE_ERRORS = (requests.RequestException, RateLimited, CheapChartsError)


def _failed(exc: Exception) -> WishlistError:
    """The one error, carrying the REASON in our own words (brief amendment 1.3) — it reaches
    the terminal, never the screen. A `CheapChartsError`'s message is our wording by
    construction; a `requests` exception is named by its CLASS, because its text holds the URL."""
    if isinstance(exc, CheapChartsError):
        return WishlistError(str(exc))
    if isinstance(exc, RateLimited):
        return WishlistError("rate limited")
    return WishlistError(type(exc).__name__)


@dataclass(frozen=True)
class RefreshReport:
    on_cheapcharts: int  # films on the CheapCharts wishlist
    known: int  # of those, films movie-brain holds — the hearts


def refresh_wishlist(repo: Repository, account: WishlistAccount, today: date) -> RefreshReport:
    """Read the wishlist and replace the local hearts wholesale. On any failure nothing is
    written — the dashboard keeps the last known hearts."""
    try:
        items = account.wishlist_items()
    except _REMOTE_ERRORS as exc:
        raise _failed(exc) from exc
    ids = [i.itunes_id for i in items]
    return RefreshReport(on_cheapcharts=len(ids), known=repo.replace_wishlist(ids, today))


def _read(repo: Repository, account: WishlistAccount, today: date) -> dict[str, WishlistItem]:
    """Read the wishlist and replace the local hearts from it. Every click starts here: if the
    wishlist cannot be read, nothing is written — to CheapCharts or locally."""
    try:
        items = account.wishlist_items()
    except _REMOTE_ERRORS as exc:
        raise _failed(exc) from exc
    repo.replace_wishlist([i.itunes_id for i in items], today)
    return {i.itunes_id: i for i in items}


def wishlist_film(repo: Repository, gateway: WishlistGateway, film_id: int, today: date) -> None:
    view = repo.get_view(film_id, today)
    if view is None:
        raise LookupError(film_id)
    if view.wishlisted:
        return  # never re-target a film the last read already holds: an old hand-set target stays
    itunes_id = repo.itunes_id_for(film_id)
    if view.owned or itunes_id is None:
        raise NotForSale(film_id)
    items = _read(repo, gateway.account, today)
    listed = film_id in repo.wishlisted_film_ids()
    if listed:
        item = items.get(itunes_id)
        # Already there with a target — set by hand on CheapCharts or by an earlier click of
        # ours. It gets its heart (the read just wrote it) and its target is never touched.
        # A missing item means the heart came from another of the film's store ids: same rule.
        if item is None or item.custom_target:
            return
        # There WITHOUT a target: a half-finished earlier click, repaired by setting it alone.
    try:
        low = gateway.prices.lowest_price(itunes_id)
        if low is None:
            raise WishlistError("no price history")
        if not listed and not gateway.account.add_item(itunes_id):
            raise WishlistError("add refused")  # nothing is believed without the API's yes
        gateway.account.set_target(itunes_id, target_price(low))
    except _REMOTE_ERRORS as exc:
        raise _failed(exc) from exc
    repo.mark_wishlisted(film_id, today)


def unwishlist_film(repo: Repository, gateway: WishlistGateway, film_id: int, today: date) -> None:
    """The click is reversible (owner ruling at delivery, brief 1.2). The add's mirror image:
    read the wishlist first — the read IS the truth — then remove. An owned film can be taken
    off too: that is the likeliest reason to want it gone."""
    view = repo.get_view(film_id, today)
    if view is None:
        raise LookupError(film_id)
    itunes_id = repo.itunes_id_for(film_id)
    if not view.wishlisted or itunes_id is None:
        return  # a stale page: nothing to remove, and CheapCharts is asked nothing
    _read(repo, gateway.account, today)
    if film_id not in repo.wishlisted_film_ids():
        return  # already gone on CheapCharts: the read has taken the heart off
    try:
        if not gateway.account.remove_item(itunes_id):
            raise WishlistError("remove refused")
    except _REMOTE_ERRORS as exc:
        raise _failed(exc) from exc
    repo.unmark_wishlisted(film_id)
