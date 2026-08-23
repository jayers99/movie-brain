from __future__ import annotations

import re
from dataclasses import dataclass

from movie_brain.domain.models import TmdbCandidate

_ANNOTATION = re.compile(r"\s*\((?:re-release|\d{4})\)\s*$", re.IGNORECASE)
_FAR = 10_000  # sort key for year-less candidates: after any real year distance


def clean_title(title: str) -> str:
    """Strip trailing "(1988)" / "(re-release)" annotations Metacritic appends."""
    return _ANNOTATION.sub("", title).strip()


def norm_title(title: str) -> str:
    """Punctuation/case-insensitive comparison key ("Forbidden Lie$" == "Forbidden Lies").

    str.isalnum keeps unicode letters/digits and drops every kind of punctuation —
    including curly quotes, which a character-class regex would silently keep.
    """
    return "".join(ch for ch in title.casefold().replace("$", "s") if ch.isalnum())


@dataclass(frozen=True)
class MatchResult:
    winner: int | None
    tied: tuple[int, ...] = ()


def match_film(mc_title: str, mc_year: int | None, candidates: list[tuple[int, str, int | None]]) -> MatchResult:
    """Pick the film a Metacritic title refers to.

    ``candidates`` are (film_id, title, year) rows whose normalized title already equals
    ``norm_title(clean_title(mc_title))``. Metacritic stamps US re-release years, so a
    film's original year may trail the MC year by decades: accept year <= mc_year + 2;
    a missing year on either side matches on title alone. Best candidate: exact year
    first, then nearest; a tie for best is ambiguous and goes to review.
    """
    viable = [c for c in candidates if mc_year is None or c[2] is None or c[2] <= mc_year + 2]
    if not viable:
        return MatchResult(winner=None)

    def sort_key(c: tuple[int, str, int | None]) -> tuple[int, int]:
        year = c[2]
        if mc_year is None or year is None:
            return (1, _FAR)
        return (0 if year == mc_year else 1, abs(year - mc_year))

    ranked = sorted(viable, key=sort_key)
    if len(ranked) > 1 and sort_key(ranked[0]) == sort_key(ranked[1]):
        tied = tuple(c[0] for c in ranked if sort_key(c) == sort_key(ranked[0]))
        return MatchResult(winner=None, tied=tied)
    return MatchResult(winner=ranked[0][0])


def pick_tmdb_match(title: str, year: int | None, candidates: list[TmdbCandidate]) -> int | None:
    """Pick the TMDB movie a film refers to, or None for the review queue.

    Unlike Metacritic (US re-release years), our years are original years: exact
    normalized-title matches within ±1 year win on popularity; otherwise the first
    of the top-3 results within ±1 year; a year-less film matches on title alone.
    """
    key = norm_title(title)
    exact = [c for c in candidates if norm_title(c.title) == key or norm_title(c.original_title) == key]
    if year is None:
        return max(exact, key=lambda c: c.popularity).tmdb_id if exact else None
    exact_year = [c for c in exact if c.year is not None and abs(c.year - year) <= 1]
    if exact_year:
        return max(exact_year, key=lambda c: c.popularity).tmdb_id
    for c in candidates[:3]:
        if c.year is not None and abs(c.year - year) <= 1:
            return c.tmdb_id
    return None
