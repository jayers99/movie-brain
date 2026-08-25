"""Cross-source consistency checks (spec 2026-08-24-data-audit-design.md §2).

Pure: takes one AuditSubject per film, returns flags. Never fixes anything. A check fires
only when evidence is present on BOTH sides — absence is not inconsistency.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .matching import split_annotations

VERDICTS: tuple[str, ...] = ("fine", "omdb-wrong", "tmdb-wrong", "film-wrong", "twin")

WEIGHTS: dict[str, int] = {
    "mc-score": 3,
    "imdb-id": 3,
    "tmdb-title": 3,
    "omdb-title": 2,
    "director": 2,
    "runtime": 2,
    "shared-imdb": 2,
    "year": 1,
    "stub": 1,
}

RUNTIME_GAP_MIN = 10
YEAR_GAP = 1
_ARTICLES = frozenset({"the", "a", "an", "le", "la", "les", "il", "lo", "der", "die", "das", "el", "los", "las"})
_NON_ALNUM = re.compile(r"[^0-9a-z]+")


@dataclass(frozen=True)
class AuditSubject:
    film_id: int
    title: str
    year: int | None
    criterion_director: str | None
    mc_score: int | None
    omdb_title: str | None
    omdb_year: int | None
    omdb_director: str | None
    omdb_runtime_min: int | None
    omdb_imdb_id: str | None
    omdb_type: str | None
    omdb_imdb_rating: str | None
    omdb_metascore: int | None
    tmdb_imdb_id: str | None
    tmdb_title: str | None
    tmdb_original_title: str | None
    tmdb_alt_titles: tuple[str, ...]
    tmdb_runtime_min: int | None
    shared_imdb_film_ids: tuple[int, ...]


@dataclass(frozen=True)
class AuditFlag:
    code: str
    detail: str
    score: int


def normalize_title(title: str) -> str:
    t = split_annotations(title)[0]
    t = unicodedata.normalize("NFKD", t)
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    words = _NON_ALNUM.sub(" ", t.casefold()).split()
    if len(words) > 1 and words[0] in _ARTICLES:
        words = words[1:]
    return " ".join(words)


def _surnames(name: str) -> set[str]:
    out: set[str] = set()
    for person in re.split(r",|&| and ", name):
        parts = normalize_title(person).split()
        if parts:
            out.add(parts[-1])
    return out


def _flag(code: str, detail: str) -> AuditFlag:
    return AuditFlag(code, detail, WEIGHTS[code])


def run_checks(s: AuditSubject) -> list[AuditFlag]:
    flags: list[AuditFlag] = []
    if s.mc_score is not None and s.omdb_metascore is not None and s.mc_score != s.omdb_metascore:
        flags.append(_flag("mc-score", f"OMDb Metascore {s.omdb_metascore} vs Metacritic {s.mc_score}"))
    if s.omdb_imdb_id and s.tmdb_imdb_id and s.omdb_imdb_id != s.tmdb_imdb_id:
        flags.append(_flag("imdb-id", f"OMDb imdbID {s.omdb_imdb_id} vs TMDB {s.tmdb_imdb_id}"))
    if s.tmdb_title is not None:
        mine = normalize_title(s.title)
        theirs = {normalize_title(t) for t in (s.tmdb_title, s.tmdb_original_title or "", *s.tmdb_alt_titles) if t}
        if mine not in theirs:
            detail = (
                f"{s.title!r} matches none of TMDB {s.tmdb_title!r} / "
                f"{s.tmdb_original_title!r} / {len(s.tmdb_alt_titles)} alts"
            )
            flags.append(_flag("tmdb-title", detail))
    if s.omdb_title is not None and normalize_title(s.title) != normalize_title(s.omdb_title):
        flags.append(_flag("omdb-title", f"OMDb title {s.omdb_title!r} vs {s.title!r}"))
    if (
        s.criterion_director
        and s.omdb_director
        and s.omdb_director != "N/A"
        and not (_surnames(s.criterion_director) & _surnames(s.omdb_director))
    ):
        flags.append(_flag("director", f"OMDb director {s.omdb_director!r} vs Criterion {s.criterion_director!r}"))
    if (
        s.omdb_runtime_min is not None
        and s.tmdb_runtime_min is not None
        and abs(s.omdb_runtime_min - s.tmdb_runtime_min) > RUNTIME_GAP_MIN
    ):
        flags.append(_flag("runtime", f"OMDb runtime {s.omdb_runtime_min} min vs TMDB {s.tmdb_runtime_min} min"))
    if s.omdb_imdb_id and s.shared_imdb_film_ids:
        others = ", ".join(f"#{i}" for i in s.shared_imdb_film_ids)
        flags.append(_flag("shared-imdb", f"OMDb imdbID {s.omdb_imdb_id} also held by {others}"))
    if s.year is not None and s.omdb_year is not None and abs(s.year - s.omdb_year) > YEAR_GAP:
        flags.append(_flag("year", f"OMDb year {s.omdb_year} vs film year {s.year}"))
    stub_type = s.omdb_type is not None and s.omdb_type != "movie"
    stub_na = s.omdb_director == "N/A" and s.omdb_imdb_rating == "N/A"
    if s.omdb_title is not None and (stub_type or stub_na):
        why = f"OMDb type {s.omdb_type!r}" if stub_type else "OMDb has no director and no rating"
        flags.append(_flag("stub", why))
    return sorted(flags, key=lambda f: f.code)


def total_score(flags: list[AuditFlag]) -> int:
    return sum(f.score for f in flags)
