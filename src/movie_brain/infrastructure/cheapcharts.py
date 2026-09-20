"""CheapCharts adapter — the public, unauthenticated "GPT API" documented at
https://www.cheapcharts.com/llms.txt, which asks tools to call the API instead of scraping.

Two endpoints matter here. `Prices.php` takes IMDb ids directly, which the on-sale design's
§4 "join problem" assumed impossible — it concluded CheapCharts could only be reached through
an iTunes track id the catalogue does not hold. It can be reached by IMDb id, and 37 of 40
sampled canon films come back. `Search.php` covers the rest: CheapCharts' IMDb index has holes
(Amour has a product page and no IMDb mapping), so a title search is the fallback, and its
answer is confirmed on title and year before anyone believes it.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit

import requests

API_BASE = "https://buster.cheapcharts.de/v1/gptapi/"
PRICES_URL = API_BASE + "Prices.php"
SEARCH_URL = API_BASE + "Search.php"
# The website's own API (one level above the GPT API). DetailData is public — only a Referer.
ACCOUNT_API = "https://buster.cheapcharts.de/v1/"
DETAIL_URL = ACCOUNT_API + "DetailData.php"
TIMEOUT_S = 30
REFERER = "https://www.cheapcharts.com/"
COUNTRY = "us"
STORE = "itunes"
MAX_IMDB_IDS = 5  # the API's own documented cap, echoed in every response's additionalInfo
DELAY_S = 1.5  # llms.txt promises "no rate limiting concerns"; the API answers 429. Pace anyway.
REMOVED_MARKER = "[❌Removed from iTunes]"  # the only signal — the product page itself is a JS
# shell that returns 200 for any id, dead or not


class RateLimited(Exception):
    """CheapCharts refused for rate reasons. A caller should stop, not retry the next film —
    the resolver is self-checkpointing, so stopping costs nothing but the run."""


class Pacer:
    """At least `delay_s` between calls, measured on a clock: a dashboard that last called
    CheapCharts an hour ago does not wait, a click's five calls in a row each do. One Pacer is
    shared by the public client and the account, because they are one host."""

    def __init__(
        self,
        delay_s: float = DELAY_S,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.delay_s = delay_s
        self._sleep = sleep
        self._clock = clock
        self._last: float | None = None

    def wait(self) -> None:
        if self._last is not None:
            remaining = self.delay_s - (self._clock() - self._last)
            if remaining > 0:
                self._sleep(remaining)
        self._last = self._clock()


def parse_evolution(text: str) -> list[Decimal]:
    """Every price in a `priceHdEvolution` string: `~`-joined `YYYY-MM-DD:±price`, newest first.
    The sign is the DIRECTION of the change (`-` a drop, `+` a rise; the oldest entry has none),
    never part of the price. Unreadable entries are skipped, never guessed."""
    prices: list[Decimal] = []
    for entry in text.split("~"):
        _, sep, raw = entry.partition(":")
        if not sep:
            continue
        try:
            price = Decimal(raw.strip().lstrip("+-"))
        except InvalidOperation:
            continue
        if price.is_finite() and price > 0:
            prices.append(price)
    return prices


def product_url(itunes_id: str) -> str:
    """The direct product page. The slug CheapCharts appends in its own links is cosmetic —
    the API returns the slugless form, so that is the form we store and render."""
    return f"https://www.cheapcharts.com/{COUNTRY}/{STORE}/movies/{itunes_id}"


@dataclass(frozen=True)
class Product:
    itunes_id: str
    title: str
    year: int | None
    director: str | None = None  # CheapCharts calls the field `artist`
    imdb_id: str | None = None
    removed: bool = False  # Apple has pulled this product; title has had REMOVED_MARKER stripped


def _itunes_id_from_url(url: str) -> str | None:
    """Last path segment of `.../us/itunes/movies/284815525?utm_source=…` — the utm campaign
    params CheapCharts adds are dropped, never stored."""
    tail = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    return tail if tail.isdigit() else None


class CheapChartsClient:
    def __init__(
        self,
        session: requests.Session | None = None,
        *,
        delay_s: float = DELAY_S,
        sleep: Callable[[float], None] = time.sleep,
        pacer: Pacer | None = None,
    ) -> None:
        self.session = session or requests.Session()
        self.delay_s = delay_s
        self._sleep = sleep
        self._pacer = pacer
        self._requested = False

    def products_by_imdb(self, imdb_ids: Sequence[str]) -> dict[str, Product]:
        """IMDb id → product, for the ids CheapCharts knows. Missing ids are simply absent."""
        if len(imdb_ids) > MAX_IMDB_IDS:
            raise ValueError(f"CheapCharts accepts at most {MAX_IMDB_IDS} IMDb ids per call")
        data = self._get(
            PRICES_URL,
            {
                "action": "getPrices",
                "store": STORE,
                "country": COUNTRY,
                "itemType": "buymovies",
                "imdbIDs": ",".join(imdb_ids),
            },
        )
        results = data.get("results") or {}
        found: dict[str, Product] = {}
        for row in results.get("buymovies") or []:
            imdb_id = row.get("imdbId")
            itunes_id = _itunes_id_from_url(row.get("cheapChartsProductPageUrl") or "")
            if not imdb_id or not itunes_id:
                continue
            title = str(row.get("title") or "").lstrip()
            removed = title.startswith(REMOVED_MARKER)
            if removed:
                title = title[len(REMOVED_MARKER) :].strip()
            found[str(imdb_id)] = Product(
                itunes_id=itunes_id,
                title=title,
                year=_year(row.get("releaseDate")),
                director=str(row.get("artist") or "") or None,
                imdb_id=str(imdb_id),
                removed=removed,
            )
        return found

    def search(self, title: str, limit: int = 5) -> list[Product]:
        """Title search, in CheapCharts' own relevance order. Carries no IMDb id, so every
        answer must be confirmed by the caller before it is believed."""
        data = self._get(
            SEARCH_URL,
            {
                "action": "search",
                "store": STORE,
                "country": COUNTRY,
                "itemType": "all",
                "query": title,
                "limit": str(limit),
            },
        )
        products: list[Product] = []
        for row in data.get("results") or []:
            if row.get("itemType") != "movies":
                continue
            itunes_id = str(row.get("idInStore") or "")
            if not itunes_id.isdigit():
                continue
            products.append(
                Product(
                    itunes_id=itunes_id,
                    title=str(row.get("title") or ""),
                    year=_year(row.get("releaseYear")),
                    director=str(row.get("artist") or "") or None,
                )
            )
        return products

    def lowest_price(self, itunes_id: str) -> Decimal | None:
        """The product's lowest price EVER, computed from its full history — never taken from
        `priceHdIsLowest`, so the number is ours. HD history first; a film with no HD history
        uses the SD one; None when there is no history at all (or no such product)."""
        data = self._get(
            DETAIL_URL, {"store": STORE, "country": COUNTRY, "itemType": "movies", "idInStore": itunes_id}
        )
        movie = (data.get("results") or {}).get("movies")
        if not isinstance(movie, dict):
            return None
        for field in ("priceHdEvolution", "priceSdEvolution"):
            prices = parse_evolution(str(movie.get(field) or ""))
            if prices:
                return min(prices)
        return None

    def _get(self, url: str, params: dict[str, str]) -> dict[str, Any]:
        if self._pacer is not None:
            self._pacer.wait()
        elif self._requested:
            self._sleep(self.delay_s)
        self._requested = True
        resp = self.session.get(url, params=params, headers={"Referer": REFERER}, timeout=TIMEOUT_S)
        if resp.status_code == 429:
            raise RateLimited(url)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        return data


def _year(value: object) -> int | None:
    text = str(value or "")[:4]
    return int(text) if text.isdigit() else None
