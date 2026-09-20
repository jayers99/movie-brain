from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from datetime import date, timedelta

from .models import FilmView

NEW_ARRIVAL_DAYS = 30  # "new" means this month: the drawer's "New on:" window and the Criterion-new chip
MIN_LISTS = 1  # cross-list tally chip, labelled "On a list" (design 2026-08-29 §7, widened
# from 2 to 1 on 2026-08-30 at the owner's request). The chip KEY stays `multi_list`: it is
# encoded in dashboard URL state, so renaming it would drop the chip from saved links.
CRITERION = "criterion"  # the listings/transitions source whose arrivals the Criterion-new chip counts

Predicate = Callable[[FilmView, date], bool]


def reachable(v: FilmView) -> bool:
    """Somewhere to watch it today: a current Criterion listing, ANY current listing on a
    streaming service (subscribed or not) or the Apple store, the film is owned, or it holds an
    iTunes id. Owned counts because it IS watchable, and because ownership on Apple is proof of
    an Apple store presence TMDB's patchy US data missed (2026-09-07: 18 of 28 owned
    "unreachable" films). An iTunes id counts for the same reason from the other side: CheapCharts
    keys a product page only for a title the Apple store sells, and TMDB's feed lags new digital
    releases by weeks (The Odyssey, 2026 — buyable on Apple, no provider anywhere on TMDB; 23 of
    163 unreachable films held one). Rated and watchlisted do not count — a judgement is not a
    way to watch. Mirrored by `reachable` in app.js; the header's count and the chip share it."""
    return (v.criterion and not v.departed) or bool(v.services) or v.owned or v.cheapcharts_url is not None


OLD_LOVED = 5  # the old 1-5★ scale's top mark: what the Rewatch chip asks about
OLD_AVOID = 1  # and its bottom: the row's red badge


def rewatch(v: FilmView) -> bool:
    """Loved then, not judged since (old-ratings spec O7): an old 5★ with no rating today. A
    PENDING REQUEST, not a label — rating the film today serves it, exactly as the "Rank this"
    mark comes off once served. Mirrored by `rewatch` in app.js."""
    return v.old_rating is not None and v.old_rating["stars"] == OLD_LOVED and v.my_rating is None


def shop(v: FilmView) -> bool:
    """A film worth buying (brief 2026-09-20-shop-chip): not owned, not rated today (0 is a
    rating; the 2004-08 stars are not), on no streaming service I have, for sale on Apple, and
    not already on my CheapCharts wishlist — a wishlisted film is DECIDED (owner's choice, variant
    B), so it leaves the list the moment it is wishlisted.

    "For sale on Apple" is the `itunes` store id (`cheapcharts_url`), never TMDB's store listing:
    it is exactly what the drawer's Wishlist-it button needs, so the list and the button cannot
    disagree. "A service I have" is read from the RAW fields, never from `best_source`: the Apple
    store row is itself `subscribed`, so the `svod` check is load-bearing, and `best_source` is
    what an owned film answers with. Mirrored by `shop` in app.js."""
    on_mine = (v.criterion and not v.departed) or any(s["kind"] == "svod" and s["subscribed"] for s in v.services)
    return not v.owned and v.my_rating is None and not on_mine and v.cheapcharts_url is not None and not v.wishlisted


def _criterion_new(v: FilmView, today: date) -> bool:
    cutoff = today - timedelta(days=NEW_ARRIVAL_DAYS)
    return any(
        t.get("source") == CRITERION and date.fromisoformat(str(t["appeared_on"])) >= cutoff for t in v.new_on
    )


_TIE = re.compile(r"^=?(\d+)$")


def _printed_rank(entry: dict[str, object]) -> int:
    """The rank AS PRINTED — a tie label like "=6" means sixth, not its line position."""
    label = entry.get("rank_label")
    if label is not None:
        m = _TIE.match(str(label))
        if m:
            return int(m.group(1))
    return int(entry["rank"])  # type: ignore[call-overload,no-any-return]


def canon_score(view: FilmView) -> float:
    """Weighted standing in the curated canon: each list contributes its trust, scaled by how
    high the film sits on it. #1 contributes the full trust, the last entry contributes ~0.

    There is deliberately NO membership floor (design D12): adding one was measured over the
    live catalogue and changed 1 of the top 10 while lifting films sitting at POOR ranks on two
    lists 70-85 places — rewarding mediocre placement twice over strong placement once. Do not
    re-propose it.
    """
    total = 0.0
    for e in view.lists:
        trust = float(e["trust"])  # type: ignore[arg-type]
        if not e.get("ordered"):
            total += trust
            continue
        size = int(e["size"])  # type: ignore[call-overload]
        if size <= 0:
            total += trust
            continue
        total += trust * (1 - (_printed_rank(e) - 1) / size)
    return total


def is_canon(view: FilmView) -> bool:
    """Tier 1: on at least one curated list. Tier 2 films (Metacritic only) rank below all of these."""
    return bool(view.lists)


# The chip bar (2026-09-07 redesign): four three-way groups plus plain chips (a third, `rewatch`,
# since 2026-09-19; a fourth, `shop`, since 2026-09-20), everything off
# by default. A group's keys are mutually exclusive in the UI (the chip cycles off → A → B → off),
# but each key is an ordinary predicate here so `matches` and the URL's `chips=` list need no
# group logic. Keys already encoded in saved URLs (`unrated`, `mine`, `leaving`, `watchlist`,
# `owned`, `not_owned`, `multi_list`) keep their names. The removed keys (`top_ratings`,
# `recent`, `pending`, `departed`, `new_arrivals`, `needs_revisit`, `suspect`, `acquire`) are
# simply unknown now — app.js drops unknown keys when it reads a URL.
_PREDICATES: dict[str, Predicate] = {
    "reachable": lambda v, _: reachable(v),
    "unreachable": lambda v, _: not reachable(v),
    "unrated": lambda v, _: v.my_rating is None,
    "mine": lambda v, _: v.my_rating is not None and v.my_rating >= 1,
    "criterion": lambda v, _: v.criterion and not v.departed,
    "leaving": lambda v, _: v.leaving_date is not None,
    "criterion_new": _criterion_new,
    "not_criterion": lambda v, _: not (v.criterion and not v.departed),  # nothing on the Channel now
    "watchlist": lambda v, _: v.watchlisted,
    "owned": lambda v, _: v.owned,
    "not_owned": lambda v, _: not v.owned,
    "multi_list": lambda v, _: len(v.lists) >= MIN_LISTS,
    "rewatch": lambda v, _: rewatch(v),
    "shop": lambda v, _: shop(v),
}

CHIPS: tuple[str, ...] = tuple(_PREDICATES)


def matches(view: FilmView, chips: Iterable[str], today: date) -> bool:
    return all(_PREDICATES[c](view, today) for c in chips)


def thresholds() -> dict[str, object]:
    return {
        "new_arrival_days": NEW_ARRIVAL_DAYS,
        "multi_list": MIN_LISTS,
    }
