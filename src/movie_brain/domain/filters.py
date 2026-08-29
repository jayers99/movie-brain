from __future__ import annotations

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
