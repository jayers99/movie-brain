from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date, timedelta

from .models import FilmView

TOP_RT = 90
TOP_IMDB = 8.0
RECENT_DAYS = 30

Predicate = Callable[[FilmView, date], bool]


def _recent(v: FilmView, today: date) -> bool:
    return v.first_seen is not None and date.fromisoformat(v.first_seen) >= today - timedelta(days=RECENT_DAYS)


_PREDICATES: dict[str, Predicate] = {
    "leaving": lambda v, _: v.leaving_date is not None,
    "unrated": lambda v, _: v.my_rating is None,
    "mine": lambda v, _: v.my_rating is not None and v.my_rating >= 1,
    "not_interested": lambda v, _: v.my_rating == 0,
    "pending": lambda v, _: v.pending or v.found is False,
    "top_rt": lambda v, _: v.rt is not None and v.rt >= TOP_RT,
    "top_imdb": lambda v, _: v.imdb is not None and v.imdb >= TOP_IMDB,
    "recent": _recent,
    "departed": lambda v, _: v.departed,
}

CHIPS: tuple[str, ...] = tuple(_PREDICATES)


def matches(view: FilmView, chips: Iterable[str], today: date) -> bool:
    return all(_PREDICATES[c](view, today) for c in chips)


def thresholds() -> dict[str, object]:
    return {"top_rt": TOP_RT, "top_imdb": TOP_IMDB, "recent_days": RECENT_DAYS}
