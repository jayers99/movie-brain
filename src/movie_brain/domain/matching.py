from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from movie_brain.domain.models import TmdbCandidate

_FAR = 10_000  # sort key for year-less candidates: after any real year distance

EDITION_ANNOTATIONS: tuple[str, ...] = (
    "re-release",
    "rerelease",
    "unrated",
    "director's cut",
    "director's edition",
    "extended edition",
    "extended cut",
    "theatrical version",
    "theatrical cut",
    "special edition",
    "collector's edition",
    "uncut",
    "remastered",
    "restored",
    "restored version",
    "4k",
    "4k restoration",
    "4k remaster",
    "subtitled",
    "dubbed",
    "english subtitles",
)
_EDITION_ALT = "|".join(re.escape(a) for a in EDITION_ANNOTATIONS)
_EDITION_RE = re.compile(
    r"\s*(?:\((?:the\s+)?(" + _EDITION_ALT + r")\)"
    r"|\[(?:the\s+)?(" + _EDITION_ALT + r")\]"
    r"|[–—-]\s+(?:the\s+)?(" + _EDITION_ALT + r"))\s*$",
    re.IGNORECASE,
)


def split_annotations(title: str) -> tuple[str, tuple[str, ...]]:
    """Peel trailing edition annotations — "(Director's Cut)", "[4K]", "– Special Edition" —
    one at a time, in any of the sources' bracket/dash conventions. Stacked annotations
    (multiple trailing parens) are all collected; never strips the title down to empty."""
    found: list[str] = []
    t = title
    while (m := _EDITION_RE.search(t)) and t[: m.start()].strip():
        found.append(next(g for g in m.groups() if g).casefold())
        t = t[: m.start()].strip()
    return t, tuple(found)


_TRAILING_YEAR = re.compile(r"\s*\((\d{4})\)\s*$")


def clean_title(title: str) -> str:
    """Strip trailing "(1988)" year parens and edition annotations Metacritic appends."""
    t = title
    while True:
        m = _TRAILING_YEAR.search(t)
        if m and t[: m.start()].strip():
            t = t[: m.start()].strip()
            continue
        t, found = split_annotations(t)
        if not found:
            return t


def clean_apple_title(title: str) -> str:
    """Strip trailing edition annotations the Apple TV library appends."""
    return split_annotations(title)[0]


def parse_apple_title(title: str) -> tuple[str, int | None]:
    """Split an Apple library title into (title, embedded year).

    Apple embeds the original release year in the title ("Rear Window (1954)")
    while the track's year field may carry a remaster/re-release year — so an
    embedded year outranks the field. Edition annotations may wrap the year;
    both are stripped, but never down to an empty title.
    """
    t = clean_apple_title(title)
    year = None
    m = _TRAILING_YEAR.search(t)
    if m and t[: m.start()].strip():
        year = int(m.group(1))
        t = clean_apple_title(t[: m.start()].strip())
    return t, year


_VOL = re.compile(r"\bvol\b\.?")


def norm_title(title: str) -> str:
    """Punctuation/case/diacritic-insensitive comparison key.

    Folds diacritics ("Tête" == "Tete"), "&" to "and", "$" to "s", and "vol[.]" to
    "volume" (word-bounded, so "Volcano" is untouched) before dropping every kind of
    punctuation — including curly quotes, which a character-class regex would silently
    keep. str.isalnum keeps unicode letters/digits.
    """
    t = unicodedata.normalize("NFKD", title.casefold())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = t.replace("&", " and ").replace("$", "s")
    t = _VOL.sub("volume", t)
    return "".join(ch for ch in t if ch.isalnum())


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


def match_owned(
    title: str, year: int | None, candidates: list[tuple[int, str, int | None]]
) -> MatchResult:
    """Pick the film an owned Apple title refers to.

    Apple years are release years, so drift is small: exact year wins, else the
    unique candidate within +/-1; a year-less side needs a unique candidate.
    Ties are ambiguous and go to review, never guessed.
    """
    if year is None:
        if len(candidates) == 1:
            return MatchResult(winner=candidates[0][0])
        return MatchResult(winner=None, tied=tuple(c[0] for c in candidates)) if candidates else MatchResult(None)
    viable = [c for c in candidates if c[2] is None or abs(c[2] - year) <= 1]
    if not viable:
        return MatchResult(winner=None)

    def sort_key(c: tuple[int, str, int | None]) -> tuple[int, int]:
        return (1, _FAR) if c[2] is None else (0 if c[2] == year else 1, abs(c[2] - year))

    ranked = sorted(viable, key=sort_key)
    if len(ranked) > 1 and sort_key(ranked[0]) == sort_key(ranked[1]):
        return MatchResult(winner=None, tied=tuple(c[0] for c in ranked if sort_key(c) == sort_key(ranked[0])))
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
