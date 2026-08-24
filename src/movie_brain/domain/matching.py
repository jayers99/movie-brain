from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from movie_brain.domain.models import TmdbCandidate

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


def _clean_title_and_hint(title: str) -> tuple[str, bool]:
    """Strip trailing "(1988)" year parens and edition annotations Metacritic appends.

    Also reports whether any edition annotation was found along the way — the
    wrapper-policy ``rerelease_hint`` signal (an annotation means the source's year
    describes that edition, not the original release).
    """
    t = title
    hint = False
    while True:
        m = _TRAILING_YEAR.search(t)
        if m and t[: m.start()].strip():
            t = t[: m.start()].strip()
            continue
        t, found = split_annotations(t)
        if not found:
            return t, hint
        hint = True


def clean_title(title: str) -> str:
    """Strip trailing "(1988)" year parens and edition annotations Metacritic appends."""
    return _clean_title_and_hint(title)[0]


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


class YearKind(Enum):
    """Which trust band a query's year comes from — governs the year-disagreement rule."""

    DATABASE = "database"  # Criterion, TMDB, embedded-title years: tight +/-1
    COMMERCE = "commerce"  # Metacritic, Apple's field year: trail originals, never precede


@dataclass(frozen=True)
class Candidate:
    id: int
    title: str
    year: int | None
    director: str | None = None
    runtime_min: int | None = None
    popularity: float | None = None


@dataclass(frozen=True)
class MatchQuery:
    title: str  # RAW title; the index/core normalizes
    year: int | None
    year_kind: YearKind
    director: str | None = None
    runtime_min: int | None = None


@dataclass(frozen=True)
class MatchVerdict:
    kind: str  # "match" | "review" | "create"
    film_id: int | None = None  # set iff kind == "match"
    reason: str | None = None  # set iff kind == "review"
    tied: tuple[int, ...] = ()  # set for reason == "ambiguous"


# (title, claimed_year) -> same-titled film exists near claimed_year.
# M1: interface only — nothing wires a real one.
Arbiter = Callable[[str, int], bool]

_TITLE_POINTS: dict[int, int] = {0: 3, 1: 2, 2: 1}


def _colon_prefix(title: str) -> str | None:
    """The part of ``title`` before its first colon, when it is >=2 words — else None."""
    if ":" not in title:
        return None
    prefix = title.split(":", 1)[0].strip()
    return prefix if len(prefix.split()) >= 2 else None


def _dedupe(candidates: list[Candidate]) -> list[Candidate]:
    seen: set[int] = set()
    out: list[Candidate] = []
    for c in candidates:
        if c.id not in seen:
            seen.add(c.id)
            out.append(c)
    return out


class CandidateIndex:
    """Three-level lookup over a film corpus: exact, annotation-stripped, subtitle-prefix."""

    def __init__(self, candidates: Iterable[Candidate] = ()) -> None:
        self._buckets: tuple[dict[str, list[Candidate]], dict[str, list[Candidate]], dict[str, list[Candidate]]] = (
            {},
            {},
            {},
        )
        for c in candidates:
            self.add(c)

    def add(self, c: Candidate) -> None:
        self._buckets[0].setdefault(norm_title(c.title), []).append(c)
        self._buckets[1].setdefault(norm_title(split_annotations(c.title)[0]), []).append(c)
        prefix = _colon_prefix(c.title)
        if prefix is not None:
            self._buckets[2].setdefault(norm_title(prefix), []).append(c)

    def lookup(self, title: str) -> tuple[int, list[Candidate]]:
        transforms: list[tuple[int, str]] = [(0, norm_title(title)), (1, norm_title(split_annotations(title)[0]))]
        prefix = _colon_prefix(title)
        if prefix is not None:
            transforms.append((2, norm_title(prefix)))

        for t_level, key in transforms:
            for b_level, bucket in enumerate(self._buckets):
                hits = bucket.get(key)
                if hits:
                    return max(t_level, b_level), _dedupe(hits)
        return -1, []


class _Disqualify(Enum):
    COMMERCE_EARLY = "commerce_early"  # COMMERCE query year impossibly earlier than the candidate
    OTHER = "other"  # DATABASE-year, director, or runtime conflict


@dataclass(frozen=True)
class _ScoreResult:
    score: int
    gap: bool  # COMMERCE year trails the candidate by >1 (neutral, not disqualifying)
    year_points: int  # 0 or 2 — year support actually earned
    corroborated: bool  # director +3 or runtime +2 actually earned


def _score(query: MatchQuery, cand: Candidate, level: int) -> _ScoreResult | _Disqualify:
    score = _TITLE_POINTS[level]
    gap = False
    year_points = 0

    if query.year is not None and cand.year is not None:
        delta = query.year - cand.year
        if abs(delta) <= 1:
            year_points = 2
        elif query.year_kind is YearKind.DATABASE:
            return _Disqualify.OTHER
        elif delta < -1:
            return _Disqualify.COMMERCE_EARLY
        else:  # COMMERCE, delta > 1
            gap = True
    score += year_points

    corroborated = False

    if query.director and cand.director:
        q_names = {n.strip().casefold() for n in query.director.split(",")}
        c_names = {n.strip().casefold() for n in cand.director.split(",")}
        if q_names & c_names:
            score += 3
            corroborated = True
        else:
            return _Disqualify.OTHER

    if query.runtime_min is not None and cand.runtime_min is not None:
        delta_rt = abs(query.runtime_min - cand.runtime_min)
        if delta_rt <= max(2, 0.05 * cand.runtime_min):
            score += 2
            corroborated = True
        elif delta_rt > 0.15 * cand.runtime_min:
            return _Disqualify.OTHER

    return _ScoreResult(score=score, gap=gap, year_points=year_points, corroborated=corroborated)


def match_candidates(
    query: MatchQuery,
    index: CandidateIndex,
    *,
    rerelease_hint: bool = False,
    popularity_tiebreak: bool = False,
    arbiter: Arbiter | None = None,
) -> MatchVerdict:
    """Evidence-scored core: rank candidates, weigh year/director/runtime, arbitrate ties.

    See the M1 evidence model doc for the normative scoring table and the six verdict
    rules this implements in order.
    """
    level, hits = index.lookup(query.title)
    if level == -1 or not hits:
        return MatchVerdict(kind="create")

    survivors: list[tuple[Candidate, _ScoreResult]] = []
    disqualifications: list[_Disqualify] = []
    for cand in hits:
        result = _score(query, cand, level)
        if isinstance(result, _Disqualify):
            disqualifications.append(result)
        else:
            survivors.append((cand, result))

    if not survivors:
        if all(reason is _Disqualify.COMMERCE_EARLY for reason in disqualifications):
            return MatchVerdict(kind="create")
        return MatchVerdict(kind="review", reason="conflict")

    top_score = max(result.score for _, result in survivors)
    top = [(cand, result) for cand, result in survivors if result.score == top_score]

    if len(top) > 1:
        winner_pair = _resolve_tie(top, popularity_tiebreak)
        if winner_pair is None:
            tied_ids = tuple(sorted(cand.id for cand, _ in top))
            return MatchVerdict(kind="review", reason="ambiguous", tied=tied_ids)
        winner, result = winner_pair
    else:
        winner, result = top[0]

    if result.gap and not (rerelease_hint or result.corroborated):
        if arbiter is not None:
            claimed_year = query.year if query.year is not None else 0
            if arbiter(query.title, claimed_year):
                return MatchVerdict(kind="review", reason="remake-suspected")
            return MatchVerdict(kind="match", film_id=winner.id)
        return MatchVerdict(kind="review", reason="year-gap")

    if level == 2 and result.year_points == 0 and not result.corroborated:
        return MatchVerdict(kind="review", reason="weak-title")

    return MatchVerdict(kind="match", film_id=winner.id)


def _resolve_tie(
    top: list[tuple[Candidate, _ScoreResult]], popularity_tiebreak: bool
) -> tuple[Candidate, _ScoreResult] | None:
    """None means still ambiguous; otherwise the single popularity-tiebreak winner."""
    if not popularity_tiebreak:
        return None

    def pop_key(item: tuple[Candidate, _ScoreResult]) -> float:
        popularity = item[0].popularity
        return popularity if popularity is not None else float("-inf")

    max_pop = max(pop_key(item) for item in top)
    winners_at_max = [item for item in top if pop_key(item) == max_pop]
    return winners_at_max[0] if len(winners_at_max) == 1 else None


@dataclass(frozen=True)
class MatchResult:
    winner: int | None
    tied: tuple[int, ...] = ()
    reason: str | None = None


class FilmRowLike(Protocol):
    """Structural shape of a matching-candidate row — satisfied by database.FilmRow
    without domain importing infrastructure (dependencies point inward).

    Properties, not plain attributes: a NamedTuple's fields are read-only, and mypy
    treats a Protocol's plain attribute as read-write — read-only properties are what
    structurally matches a NamedTuple's fields.
    """

    @property
    def id(self) -> int: ...
    @property
    def title(self) -> str: ...
    @property
    def year(self) -> int | None: ...
    @property
    def director(self) -> str | None: ...
    @property
    def runtime_min(self) -> int | None: ...


def build_candidate_index(rows: Iterable[FilmRowLike]) -> CandidateIndex:
    """Build a CandidateIndex from film rows carrying director/runtime evidence."""
    index = CandidateIndex()
    for r in rows:
        index.add(Candidate(id=r.id, title=r.title, year=r.year, director=r.director, runtime_min=r.runtime_min))
    return index


_OldCandidate = tuple[int, str, int | None]


def _coerce_index(candidates: list[_OldCandidate] | list[Candidate] | CandidateIndex) -> CandidateIndex:
    """Old-style 3-tuple candidate lists, Candidate lists, and CandidateIndex all still work."""
    if isinstance(candidates, CandidateIndex):
        return candidates
    index = CandidateIndex()
    for c in candidates:
        index.add(c if isinstance(c, Candidate) else Candidate(id=c[0], title=c[1], year=c[2]))
    return index


def _to_match_result(verdict: MatchVerdict) -> MatchResult:
    if verdict.kind == "match":
        return MatchResult(winner=verdict.film_id)
    if verdict.reason == "ambiguous":
        return MatchResult(winner=None, tied=verdict.tied)
    if verdict.kind == "review":
        return MatchResult(winner=None, reason=verdict.reason)
    return MatchResult(winner=None)


def match_film(
    mc_title: str,
    mc_year: int | None,
    candidates: list[_OldCandidate] | list[Candidate] | CandidateIndex,
) -> MatchResult:
    """Pick the film a Metacritic title refers to — a policy shell over match_candidates.

    Metacritic stamps US re-release years, so a film's original year may trail the MC
    year by decades: ``year_kind=COMMERCE`` lets the core treat that trailing drift as
    a neutral gap rather than a conflict, needing edition-annotation corroboration (or
    the M2 arbiter) to avoid a review. ``candidates`` accepts the old 3-tuple rows, a
    plain Candidate list, or a prebuilt CandidateIndex.
    """
    cleaned, hint = _clean_title_and_hint(mc_title)
    query = MatchQuery(title=cleaned, year=mc_year, year_kind=YearKind.COMMERCE)
    verdict = match_candidates(query, _coerce_index(candidates), rerelease_hint=hint)
    return _to_match_result(verdict)


def match_owned(
    title: str,
    year: int | None,
    candidates: list[_OldCandidate] | list[Candidate] | CandidateIndex,
    *,
    embedded_year: bool = False,
    runtime_min: int | None = None,
    rerelease_hint: bool = False,
) -> MatchResult:
    """Pick the film an owned Apple title refers to — a policy shell over match_candidates.

    A year embedded in the Apple title is the original release year (tight
    ``DATABASE`` band); the track's year field can be a remaster/re-release year
    (looser ``COMMERCE`` band, same trailing-drift-is-neutral treatment as Metacritic).
    ``candidates`` accepts the old 3-tuple rows, a plain Candidate list, or a prebuilt
    CandidateIndex.

    ``title`` is stripped of any edition annotations it still carries (matching
    match_film's own-title-stripping policy), OR'd with the caller-supplied
    ``rerelease_hint``: callers such as owned.py that pre-strip the title before
    calling (e.g. via ``parse_apple_title``) must detect the annotation themselves
    against the ORIGINAL title and pass it through here — otherwise the hint is
    always False and the rerelease-corroboration path is dead for them.
    """
    cleaned, hint = split_annotations(title)
    query = MatchQuery(
        title=cleaned,
        year=year,
        year_kind=YearKind.DATABASE if embedded_year else YearKind.COMMERCE,
        runtime_min=runtime_min,
    )
    verdict = match_candidates(query, _coerce_index(candidates), rerelease_hint=rerelease_hint or bool(hint))
    return _to_match_result(verdict)


def pick_tmdb_match(title: str, year: int | None, candidates: list[TmdbCandidate]) -> int | None:
    """Pick the TMDB movie a film refers to, or None for the review queue.

    Our years are original years (``DATABASE`` band); each TMDB result is indexed
    under both its title and original_title so either can earn the title score.
    Popularity breaks ties among equally-scored candidates. The old title-blind
    "first of top-3 within ±1 year" fallback is deliberately gone — it was the
    Lawrence-of-Arabia-to-731627 wrong-match vector.
    """
    index = CandidateIndex()
    for c in candidates:
        index.add(Candidate(id=c.tmdb_id, title=c.title, year=c.year, popularity=c.popularity))
        index.add(Candidate(id=c.tmdb_id, title=c.original_title, year=c.year, popularity=c.popularity))
    query = MatchQuery(title=title, year=year, year_kind=YearKind.DATABASE)
    verdict = match_candidates(query, index, popularity_tiebreak=True)
    return verdict.film_id if verdict.kind == "match" else None
