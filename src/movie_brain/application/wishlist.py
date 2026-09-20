""""Wishlist it" (brief 2026-09-19-price-watch): put a film on the owner's CheapCharts wishlist at
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

from movie_brain.domain.wishlist import target_price
from movie_brain.infrastructure.database import Repository


class PriceSource(Protocol):
    def lowest_price(self, itunes_id: str) -> Decimal | None: ...


class WishlistAccount(Protocol):
    def add_item(self, itunes_id: str) -> bool: ...

    def set_target(self, itunes_id: str, target: Decimal) -> None: ...

    def wishlist_ids(self) -> list[str]: ...


@dataclass(frozen=True)
class WishlistGateway:
    prices: PriceSource
    account: WishlistAccount


class WishlistError(Exception):
    """Anything that ends as the drawer's "Couldn't reach CheapCharts." — nothing was marked."""


class NotForSale(Exception):
    """Owned, or no store id: the button never shows on such a film, so this is a stale page."""


def wishlist_film(repo: Repository, gateway: WishlistGateway, film_id: int, today: date) -> None:
    view = repo.get_view(film_id, today)
    if view is None:
        raise LookupError(film_id)
    if view.wishlisted:
        return  # never re-target a film the last read already holds: an old hand-set target stays
    itunes_id = repo.itunes_id_for(film_id)
    if view.owned or itunes_id is None:
        raise NotForSale(film_id)
    low = gateway.prices.lowest_price(itunes_id)
    if low is None:
        raise WishlistError("no price history")
    gateway.account.add_item(itunes_id)
    gateway.account.set_target(itunes_id, target_price(low))
    repo.mark_wishlisted(film_id, today)
