from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from datetime import date, timedelta

from .models import FilmView

TOP_MC = 90
TOP_RT = 90
TOP_IMDB = 7.5
RECENT_DAYS = 30
NEW_ARRIVAL_DAYS = 14
MULTI_LIST = 2  # cross-list tally chip: "on 2+ lists" (design 2026-08-29 §7)

Predicate = Callable[[FilmView, date], bool]


def _recent(v: FilmView, today: date) -> bool:
    return v.first_seen is not None and date.fromisoformat(v.first_seen) >= today - timedelta(days=RECENT_DAYS)


def _new_arrivals(v: FilmView, today: date) -> bool:
    cutoff = today - timedelta(days=NEW_ARRIVAL_DAYS)
    return any(date.fromisoformat(str(t["appeared_on"])) >= cutoff for t in v.new_on)


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


def acquisition_candidate(view: FilmView, _today: date) -> bool:
    """Worth buying: unreachable on anything I pay for, unseen, unowned, and canon-adjacent.

    The Criterion clause is separate from the `services` test on purpose: `criterion` IS a
    subscribed svod row in `movie_service`, but `_SERVICES_SQL` filters it out of
    `FilmView.services` (`l.source != 'criterion'`), so testing `services` alone would offer to
    sell a film that is streaming on the Channel right now. Only `kind == 'svod'` suppresses —
    a subscribed `store` (e.g. `apple-tv-store`) is a shop, not access, and must never suppress.
    """
    if view.owned or view.my_rating is not None:
        return False
    if view.criterion and not view.departed:
        return False
    if any(s.get("subscribed") and s.get("kind") == "svod" for s in view.services):
        return False
    return is_canon(view) or (view.metacritic is not None and view.metacritic >= TOP_MC)


_PREDICATES: dict[str, Predicate] = {
    "leaving": lambda v, _: v.leaving_date is not None,
    "unrated": lambda v, _: v.my_rating is None,
    "mine": lambda v, _: v.my_rating is not None and v.my_rating >= 1,
    "pending": lambda v, _: v.pending or v.found is False,
    "top_ratings": lambda v, _: (
        (v.metacritic is not None and v.metacritic >= TOP_MC)
        or (v.rt is not None and v.rt >= TOP_RT)
        or (v.imdb is not None and v.imdb >= TOP_IMDB)
    ),
    "recent": _recent,
    "departed": lambda v, _: v.departed,
    "new_arrivals": _new_arrivals,
    "watchlist": lambda v, _: v.watchlisted,
    "owned": lambda v, _: v.owned,
    "not_owned": lambda v, _: not v.owned,
    "needs_revisit": lambda v, _: v.needs_revisit,
    "suspect": lambda v, _: v.audit is not None,
    "multi_list": lambda v, _: len(v.lists) >= MULTI_LIST,
    "acquire": acquisition_candidate,
}

CHIPS: tuple[str, ...] = tuple(_PREDICATES)


def matches(view: FilmView, chips: Iterable[str], today: date) -> bool:
    return all(_PREDICATES[c](view, today) for c in chips)


def thresholds() -> dict[str, object]:
    return {
        "top_mc": TOP_MC,
        "top_rt": TOP_RT,
        "top_imdb": TOP_IMDB,
        "recent_days": RECENT_DAYS,
        "new_arrival_days": NEW_ARRIVAL_DAYS,
        "multi_list": MULTI_LIST,
    }
