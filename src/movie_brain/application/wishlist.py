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

from movie_brain.application.cheapcharts import ITUNES_AUTHORITY
from movie_brain.domain.wishlist import target_price
from movie_brain.infrastructure.cheapcharts import CheapChartsError, RateLimited, WishlistItem
from movie_brain.infrastructure.database import Repository


class PriceSource(Protocol):
    def lowest_price(self, itunes_id: str) -> Decimal | None: ...

    def imdb_id_for(self, itunes_id: str) -> str | None: ...


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


@dataclass(frozen=True)
class ResolvedFilm:
    film_id: int
    title: str
    year: int | None
    itunes_id: str


@dataclass(frozen=True)
class ResolveUnknownReport:
    on_cheapcharts: int  # films on the wishlist
    unknown: int  # of those, store ids no film held before this run
    resolved: tuple[ResolvedFilm, ...]  # an IMDb-id join found the film
    not_in_catalogue: int  # CheapCharts names an IMDb id no live film holds
    no_imdb: int  # CheapCharts has no IMDb id for the product
    rate_limited: bool  # stopped early; re-running with --apply resumes (a stored id already
    # applied is never asked again) — a dry run stores nothing, so re-running it starts over
    known: int  # hearts after the run (after a dry run: as they would be WITHOUT the new ids)


def resolve_unknown_wishlist(
    repo: Repository, gateway: WishlistGateway, today: date, *, apply: bool
) -> ResolveUnknownReport:
    """Give the films on the wishlist that movie-brain cannot place their store id (amendment
    1.4). A film the store lookup has never reached holds no `itunes` id, so the wishlist read
    matches nothing and it shows no heart and no button — silently, which is how Scarlet Street
    was found by hand. The wishlist itself names the store ids, and CheapCharts will say which
    IMDb id each product carries: an exact id join, at most one paced call per unplaced film.

    The run finishes with the ordinary wholesale refresh, so the ids stored here become hearts
    immediately; a dry run stores nothing and therefore hearts nothing.
    """
    try:
        items = gateway.account.wishlist_items()
    except _REMOTE_ERRORS as exc:
        raise _failed(exc) from exc
    ids = [i.itunes_id for i in items]
    held = repo.itunes_ids_held()
    # A hidden film keeps its `external_ids` row, and `UNIQUE(authority, value)` is blind to
    # dispositions: a product it holds cannot be claimed by anyone, so it is refused here rather
    # than raised at the write — the application layer never sees sqlite3.
    spoken_for = repo.claimed_values(ITUNES_AUTHORITY) - held
    unknown = sorted(set(ids) - held)
    resolved: list[ResolvedFilm] = []
    not_in_catalogue = no_imdb = 0
    rate_limited = False
    for itunes_id in unknown:
        try:
            tt = gateway.prices.imdb_id_for(itunes_id)
        except RateLimited:
            rate_limited = True
            break
        except _REMOTE_ERRORS as exc:
            raise _failed(exc) from exc
        if tt is None:
            no_imdb += 1
            continue
        film_id = repo.film_id_for_external("imdb", tt)
        # The whole feature's guard against handing a hidden film a store id: `film_title_year`
        # answers None for a disposed (tombstoned/merged-away) film exactly as it does for a
        # missing one, so it must stay disposition-aware — never "optimised" to a bare id lookup.
        named = None if film_id is None else repo.film_title_year(film_id)
        if film_id is None or named is None or itunes_id in spoken_for:
            not_in_catalogue += 1
            continue
        if apply:
            repo.set_external_id(film_id, ITUNES_AUTHORITY, itunes_id, today)
        resolved.append(ResolvedFilm(film_id, named[0], named[1], itunes_id))
    return ResolveUnknownReport(
        on_cheapcharts=len(ids),
        unknown=len(unknown),
        resolved=tuple(resolved),
        not_in_catalogue=not_in_catalogue,
        no_imdb=no_imdb,
        rate_limited=rate_limited,
        known=repo.replace_wishlist(ids, today),
    )


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
    itunes_id = repo.itunes_id_for(film_id)  # a fresh add's product: the one the drawer links to
    if view.owned or itunes_id is None:
        raise NotForSale(film_id)
    items = _read(repo, gateway.account, today)
    listed = film_id in repo.wishlisted_film_ids()
    if listed:
        # The heart can have come through ANY of the film's store ids — since amendment 1.4 the
        # wishlist's own product and the store lookup's can be two ids of one film — so this
        # film's item is the first of them the read actually holds.
        item = next((items[i] for i in repo.itunes_ids_for(film_id) if i in items), None)
        # Already there with a target — set by hand on CheapCharts or by an earlier click of
        # ours. It gets its heart (the read just wrote it) and its target is never touched.
        if item is None or item.custom_target:
            return
        # There WITHOUT a target: a half-finished earlier click, repaired by setting it alone —
        # on THAT product, never on the drawer's pick.
        itunes_id = item.itunes_id
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
    if not view.wishlisted:
        return  # a stale page: nothing to remove, and CheapCharts is asked nothing
    mine = repo.itunes_ids_for(film_id)
    if not mine:
        # Hearted locally with no store id to remove it by (unreachable today — the button never
        # shows on such a film). There is nothing CheapCharts can be asked, so answering success
        # while leaving the row in place would just bring the heart back on the next reload.
        repo.unmark_wishlisted(film_id)
        return
    items = _read(repo, gateway.account, today)
    if film_id not in repo.wishlisted_film_ids():
        return  # already gone on CheapCharts: the read has taken the heart off
    try:
        # EVERY product of this film that is on the wishlist, not just the one the drawer links
        # to: a film left on under its other store id is still on, and the next click would read
        # it back and refuse forever.
        for itunes_id in (i for i in mine if i in items):
            if not gateway.account.remove_item(itunes_id):
                raise WishlistError("remove refused")
    except _REMOTE_ERRORS as exc:
        raise _failed(exc) from exc
    repo.unmark_wishlisted(film_id)
