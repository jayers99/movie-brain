"""Offline benchmark: score matchers (frozen baseline today, the new evidence-scored
core later) against a banked ground-truth suite and a replay of the real archives.

Read-only: opens movie-brain.db with ``mode=ro`` and never touches the DB or config
dir. ``MatcherSet`` is the plug point Task 6 uses to run the new matchers through the
same ``run_case``/``replay_*`` machinery, side by side with this frozen baseline.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sqlite3
import sys
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NamedTuple, Protocol

from movie_brain.domain import matching as new_matching
from movie_brain.infrastructure import appletv, metacritic
from movie_brain.infrastructure.config import load_config

SCRIPT_DIR = Path(__file__).resolve().parent


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    # Dataclasses with `from __future__ import annotations` resolve field types via
    # sys.modules[cls.__module__] — register before exec_module or that lookup is None.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


baseline = _load_module("matching_baseline", SCRIPT_DIR / "matching_baseline.py")


# --------------------------------------------------------------------------- #
# Shapes shared by ground-truth cases and the archive replay.
# --------------------------------------------------------------------------- #


class PoolFilm(NamedTuple):
    """One synthetic (or real, for archive replay) corpus row."""

    id: int
    title: str
    year: int | None
    director: str | None
    runtime_min: int | None


class TmdbCand(NamedTuple):
    """One synthetic TMDB search result — field names match TmdbCandidate."""

    tmdb_id: int
    title: str
    original_title: str
    year: int | None
    popularity: float


class MatchResultLike(Protocol):
    winner: int | None
    tied: tuple[int, ...]


class MatcherSet:
    """The matcher functions under test, as a namespace Task 6 can swap out.

    ``supports_runtime`` gates whether ``run_case``/``replay_apple`` pass the v2
    ``runtime_min``/``embedded_year`` evidence kwargs into ``match_owned`` — the
    frozen baseline (this task) ignores runtime, so it stays False here.
    """

    def __init__(
        self,
        *,
        norm_title: Callable[[str], str],
        clean_title: Callable[[str], str],
        match_film: Callable[..., MatchResultLike],
        match_owned: Callable[..., MatchResultLike],
        pick_tmdb_match: Callable[..., int | None],
        parse_apple_title: Callable[[str], tuple[str, int | None]],
        supports_runtime: bool = False,
        split_annotations: Callable[[str], tuple[str, tuple[str, ...]]] | None = None,
    ) -> None:
        self.norm_title = norm_title
        self.clean_title = clean_title
        self.match_film = match_film
        self.match_owned = match_owned
        self.pick_tmdb_match = pick_tmdb_match
        self.parse_apple_title = parse_apple_title
        self.supports_runtime = supports_runtime
        # Only the new (evidence-scored) set needs this: owned.py detects the
        # rerelease hint against the ORIGINAL apple title before parse_apple_title
        # strips it, so the benchmark must replicate that live-caller step exactly.
        self.split_annotations = split_annotations


def baseline_matcher_set() -> MatcherSet:
    return MatcherSet(
        norm_title=baseline.norm_title,
        clean_title=baseline.clean_title,
        match_film=baseline.match_film,
        match_owned=baseline.match_owned,
        pick_tmdb_match=baseline.pick_tmdb_match,
        parse_apple_title=baseline.parse_apple_title,
        supports_runtime=False,
    )


def new_matcher_set() -> MatcherSet:
    """The M1 evidence-scored matchers (movie_brain.domain.matching), wired to mirror
    the LIVE callers exactly: application/owned.py and application/metacritic.py."""
    return MatcherSet(
        norm_title=new_matching.norm_title,
        clean_title=new_matching.clean_title,
        match_film=new_matching.match_film,
        match_owned=new_matching.match_owned,
        pick_tmdb_match=new_matching.pick_tmdb_match,
        parse_apple_title=new_matching.parse_apple_title,
        supports_runtime=True,
        split_annotations=new_matching.split_annotations,
    )


@dataclass(frozen=True)
class Case:
    name: str
    source: str  # "metacritic" | "apple" | "tmdb"
    title: str  # raw query title as the source shows it
    year: int | None  # the source's year field
    pool: tuple[PoolFilm, ...]  # synthetic corpus: (id, title, year, director, runtime_min)
    expect: str  # CORRECT verdict, e.g. "match:1"
    runtime_min: int | None = None  # apple v2 evidence (baseline ignores)
    tmdb: tuple[TmdbCand, ...] = field(default_factory=tuple)  # tmdb candidates


@dataclass(frozen=True)
class CaseResult:
    name: str
    expect: str
    observed: str
    passed: bool
    wrong_match: bool


@dataclass(frozen=True)
class Rates:
    n: int
    match_pct: float
    review_pct: float
    create_pct: float
    review_samples: tuple[str, ...] = ()  # up to ~10 raw titles that landed in review


@dataclass(frozen=True)
class GtSummary:
    passed: int
    failed: int
    wrong: int


def summarize(results: list[CaseResult]) -> GtSummary:
    passed = sum(1 for r in results if r.passed)
    return GtSummary(passed=passed, failed=len(results) - passed, wrong=sum(1 for r in results if r.wrong_match))


def dominates(baseline_summary: GtSummary, new_summary: GtSummary) -> bool:
    """True iff the new matcher has zero wrong-matches and is no worse than baseline."""
    return new_summary.wrong == 0 and new_summary.wrong <= baseline_summary.wrong


# --------------------------------------------------------------------------- #
# Ground-truth suite — banked per the M1 plan; `expect` is CORRECT behavior.
# The baseline is expected to fail several of these (that's the point).
# --------------------------------------------------------------------------- #

GROUND_TRUTHS: list[Case] = [
    Case(
        name="lawrence-mc-rerelease",
        source="metacritic",
        title="Lawrence of Arabia (re-release)",
        year=2002,
        pool=(PoolFilm(1, "Lawrence of Arabia", 1962, None, None),),
        expect="match:1",
    ),
    Case(
        name="lawrence-tmdb",
        source="tmdb",
        title="Lawrence of Arabia",
        year=2002,
        pool=(),
        expect="none",
        tmdb=(
            TmdbCand(947, "Lawrence of Arabia", "Lawrence of Arabia", 1962, 40.0),
            # 2002 on purpose: the baseline's title-blind "first of top-3 within +/-1
            # year" fallback must reproduce this banked wrong match.
            TmdbCand(731627, "Lawrence: After Arabia", "Lawrence: After Arabia", 2002, 2.0),
            TmdbCand(99, "Arabia", "Arabia", 1990, 1.0),
        ),
    ),
    Case(
        # Live 2026-08-24: Criterion's "Intolerance" (1916) was linked to 1216137, a dateless
        # 4-minute short — every dated same-title result failed the 1916 band and the one
        # dateless survivor inherited the match by elimination. A dateless candidate among
        # year-disqualified twins is a review, never a link. The feature itself (found only via
        # the search year retry) carries the full subtitled string as BOTH title and
        # original_title, and a one-word colon prefix never indexes (banked rule) → an honest
        # miss for the review queue, resolved by hand with --tmdb-id 3059.
        name="intolerance-dateless-short",
        source="tmdb",
        title="Intolerance",
        year=1916,
        pool=(),
        expect="none",
        tmdb=(
            TmdbCand(48684, "Intolerance", "Intolerance", 2000, 0.56),
            TmdbCand(879617, "Intolerance", "Intolerance", 2020, 1.25),
            TmdbCand(1216137, "Intolerance", "Intolerance", None, 1.08),
            TmdbCand(732929, "Intolerance", "Intolerance", None, 0.4),
            TmdbCand(
                3059,
                "Intolerance: Love's Struggle Throughout the Ages",
                "Intolerance: Love's Struggle Throughout the Ages",
                1916,
                3.46,
            ),
        ),
    ),
    Case(
        name="stop-making-sense-no-runtime",
        source="apple",
        title="Stop Making Sense",
        year=2023,
        pool=(PoolFilm(1, "Stop Making Sense", 1984, None, 88),),
        expect="review",
    ),
    Case(
        name="stop-making-sense-runtime",
        source="apple",
        title="Stop Making Sense",
        year=2023,
        pool=(PoolFilm(1, "Stop Making Sense", 1984, None, 88),),
        expect="match:1",
        runtime_min=88,
    ),
    Case(
        name="rear-window-embedded",
        source="apple",
        title="Rear Window (1954)",
        year=2013,
        pool=(PoolFilm(1, "Rear Window", 1954, "Alfred Hitchcock", 112),),
        expect="match:1",
    ),
    Case(
        name="vertigo-control",
        source="apple",
        title="Vertigo (1958)",
        year=1958,
        pool=(PoolFilm(1, "Vertigo", 1958, None, None),),
        expect="match:1",
    ),
    Case(
        name="strangelove-control",
        source="metacritic",
        title="Dr. Strangelove",
        year=1964,
        pool=(PoolFilm(1, "Dr. Strangelove", 1964, None, None),),
        expect="match:1",
    ),
    Case(
        name="kill-bill-vol-1",
        source="metacritic",
        title="Kill Bill: Vol. 1",
        year=2003,
        pool=(
            PoolFilm(1, "Kill Bill: Volume 1", 2003, None, None),
            PoolFilm(2, "Kill Bill: Volume 2", 2004, None, None),
        ),
        expect="match:1",
    ),
    Case(
        name="kill-bill-stay-distinct",
        source="metacritic",
        title="Kill Bill: Vol. 2",
        year=2004,
        pool=(
            PoolFilm(1, "Kill Bill: Volume 1", 2003, None, None),
            PoolFilm(2, "Kill Bill: Volume 2", 2004, None, None),
        ),
        expect="match:2",
    ),
    Case(
        name="diacritic-fold",
        source="metacritic",
        title="Tête",
        year=2007,
        pool=(PoolFilm(1, "Tete", 2007, None, None),),
        expect="match:1",
    ),
    Case(
        name="ampersand",
        source="apple",
        title="Willy Wonka & the Chocolate Factory",
        year=1971,
        pool=(PoolFilm(1, "Willy Wonka and the Chocolate Factory", 1971, None, None),),
        expect="match:1",
    ),
    Case(
        name="bracket-rerelease",
        source="metacritic",
        title="The Red Shoes [re-release]",
        year=2023,
        pool=(PoolFilm(1, "The Red Shoes", 1948, None, None),),
        expect="match:1",
    ),
    Case(
        name="restored-version",
        source="apple",
        title="The Leopard (Restored Version)",
        year=2004,
        pool=(PoolFilm(1, "The Leopard", 1963, None, None),),
        expect="match:1",
    ),
    Case(
        name="directors-edition-dash",
        source="apple",
        title="Star Trek: The Motion Picture – The Director's Edition",
        year=2022,
        pool=(PoolFilm(1, "Star Trek: The Motion Picture", 1979, None, None),),
        expect="match:1",
    ),
    Case(
        name="nosferatu-remake-missing",
        source="apple",
        title="Nosferatu",
        year=2024,
        pool=(PoolFilm(1, "Nosferatu", 1922, None, 94),),
        expect="review",
        runtime_min=132,
    ),
    Case(
        name="nosferatu-remake-present",
        source="apple",
        title="Nosferatu",
        year=2024,
        pool=(PoolFilm(1, "Nosferatu", 1922, None, None), PoolFilm(2, "Nosferatu", 2024, None, None)),
        expect="match:2",
    ),
    Case(
        name="star-is-born-2018",
        source="apple",
        title="A Star Is Born",
        year=2018,
        pool=(
            PoolFilm(1, "A Star Is Born", 1937, None, None),
            PoolFilm(2, "A Star Is Born", 1954, None, None),
            PoolFilm(3, "A Star Is Born", 1976, None, None),
            PoolFilm(4, "A Star Is Born", 2018, None, None),
        ),
        expect="match:4",
    ),
    Case(
        name="body-snatchers-78",
        source="apple",
        title="Invasion of the Body Snatchers",
        year=1978,
        pool=(
            PoolFilm(1, "Invasion of the Body Snatchers", 1956, None, None),
            PoolFilm(2, "Invasion of the Body Snatchers", 1978, None, None),
        ),
        expect="match:2",
    ),
    Case(
        name="subtitle-prefix",
        source="apple",
        title="Hearts of Darkness",
        year=1991,
        pool=(PoolFilm(1, "Hearts of Darkness: A Filmmaker's Apocalypse", 1991, None, None),),
        expect="match:1",
    ),
    Case(
        name="subtitle-weak-no-year",
        source="apple",
        title="Hearts of Darkness",
        year=None,
        pool=(PoolFilm(1, "Hearts of Darkness: A Filmmaker's Apocalypse", 1991, None, None),),
        expect="review",
    ),
    Case(
        name="solaris-popularity-tie",
        source="tmdb",
        title="Solaris",
        year=1972,
        pool=(),
        expect="match:3",
        tmdb=(
            TmdbCand(1, "Solaris", "Solaris", 2002, 9.0),
            TmdbCand(2, "Solaris", "Solaris", 1972, 5.0),
            TmdbCand(3, "Solaris", "Solaris", 1972, 8.0),
        ),
    ),
    Case(
        name="solaris-mc-wrong-era",
        source="metacritic",
        title="Solaris",
        year=1972,
        pool=(PoolFilm(9, "Solaris", 2002, None, None),),
        expect="create",
    ),
    Case(
        name="yearless-candidate",
        source="metacritic",
        title="Trio",
        year=1950,
        pool=(PoolFilm(3, "Trio", None, None, None),),
        expect="match:3",
    ),
    Case(
        name="yearless-query",
        source="metacritic",
        title="Trio",
        year=None,
        pool=(PoolFilm(3, "Trio", 1950, None, None),),
        expect="match:3",
    ),
    Case(
        name="owned-tie",
        source="apple",
        title="Twin",
        year=1979,
        pool=(PoolFilm(1, "Twin", 1978, None, None), PoolFilm(2, "Twin", 1980, None, None)),
        expect="review",
    ),
    Case(
        # Live 2026-08-24: MC slug metropolis-re-release (Lang 1927, 2002 restoration) carried
        # commerce year 2001; the 2001 anime "Metropolis" matched on year evidence with no gap,
        # so neither review nor arbitration fired. The annotation says 2001 is an EDITION year,
        # so a same-year twin next to an older same-title film must go to review.
        name="metropolis-rerelease-same-year-twin",
        source="metacritic",
        title="Metropolis (re-release)",
        year=2001,
        pool=(
            PoolFilm(1, "Metropolis", 1927, "Fritz Lang", 153),
            PoolFilm(2, "Metropolis", 2001, "Rintaro", 108),
        ),
        expect="review",
    ),
]


# --------------------------------------------------------------------------- #
# --assert-dominance ceilings. The apple ceiling is 6.0 rather than 5.0 because this replay
# reads the LIVE catalogue, so filling in a MISSING year raises review% rather than lowering it:
# Apple's export carries its own store year (`La Strada 1956`, a US re-release), which CLAUDE.md's
# year precedence ranks below the original release year as remaster-prone. Once films.year is
# populated the matcher can finally SEE that disagreement and flags it — correctly. Measured
# 2026-08-29: apple review% went 4.9 -> 5.1 on a single film (#1812 La strada, no year -> 1954),
# on both the baseline and the new replay, while ground-truth wrong-matches went 2 -> 0. The gate's
# load-bearing half is `wrong == 0`; these percentages are a drift alarm, and the alarm must not
# fire every time the catalogue gets more correct.
MAX_MC_REVIEW_PCT = 5.0
MAX_APPLE_REVIEW_PCT = 6.0


# Case runner + archive replay — mirrors the live callers' verdict mapping.
# --------------------------------------------------------------------------- #


def _pool_candidates(
    pool: tuple[PoolFilm, ...], norm_title: Callable[[str], str], key: str
) -> list[tuple[int, str, int | None]]:
    return [(f.id, f.title, f.year) for f in pool if norm_title(f.title) == key]


def _map_verdict(result: MatchResultLike, candidates: list[Any], *, review_on_no_winner: bool) -> str:
    if result.tied:
        return "review"
    if result.winner is not None:
        return f"match:{result.winner}"
    if review_on_no_winner and candidates:
        return "review"
    return "create"


def _map_verdict_new(result: MatchResultLike) -> str:
    """Verdict mapping for the new evidence-scored set, exactly as the live callers
    (import_owned / match_archive) interpret a MatchResult: winner -> match; tied ->
    review; a non-tie review reason -> review; a bare MatchResult(None) -> create."""
    if result.tied:
        return "review"
    if result.winner is not None:
        return f"match:{result.winner}"
    if getattr(result, "reason", None) is not None:
        return "review"
    return "create"


def _pool_index(pool: tuple[PoolFilm, ...]) -> new_matching.CandidateIndex:
    return new_matching.build_candidate_index(pool)


def _is_wrong_match(observed: str, expect: str) -> bool:
    return observed.startswith("match:") and observed != expect


def _make_result(case: Case, observed: str) -> CaseResult:
    return CaseResult(
        name=case.name,
        expect=case.expect,
        observed=observed,
        passed=observed == case.expect,
        wrong_match=_is_wrong_match(observed, case.expect),
    )


def run_case(case: Case, matcher_set: MatcherSet) -> CaseResult:
    """Dispatch by source, mapping the raw matcher return onto the verdict vocabulary
    exactly as the live callers (match_archive / import_owned / the tmdb step) do."""
    if case.source == "metacritic":
        cleaned = matcher_set.clean_title(case.title)
        if matcher_set.supports_runtime:
            index = _pool_index(case.pool)
            # match_film does its own clean_title/split_annotations on the RAW title —
            # application/metacritic.py passes the raw MC title, not `cleaned`.
            result = matcher_set.match_film(case.title, case.year, index)
            observed = _map_verdict_new(result)
        else:
            key = matcher_set.norm_title(cleaned)
            candidates = _pool_candidates(case.pool, matcher_set.norm_title, key)
            result = matcher_set.match_film(cleaned, case.year, candidates)
            observed = _map_verdict(result, candidates, review_on_no_winner=False)
    elif case.source == "apple":
        cleaned, embedded_year = matcher_set.parse_apple_title(case.title)
        year = embedded_year if embedded_year is not None else case.year
        if matcher_set.supports_runtime:
            assert matcher_set.split_annotations is not None
            # application/owned.py detects the rerelease hint against the ORIGINAL
            # title (parse_apple_title already stripped it out of `cleaned`).
            rerelease_hint = bool(matcher_set.split_annotations(case.title)[1])
            index = _pool_index(case.pool)
            result = matcher_set.match_owned(
                cleaned,
                year,
                index,
                embedded_year=embedded_year is not None,
                rerelease_hint=rerelease_hint,
                runtime_min=case.runtime_min,
            )
            observed = _map_verdict_new(result)
        else:
            key = matcher_set.norm_title(cleaned)
            candidates = _pool_candidates(case.pool, matcher_set.norm_title, key)
            result = matcher_set.match_owned(cleaned, year, candidates)
            observed = _map_verdict(result, candidates, review_on_no_winner=True)
    elif case.source == "tmdb":
        winner = matcher_set.pick_tmdb_match(case.title, case.year, list(case.tmdb))
        observed = f"match:{winner}" if winner is not None else "none"
    else:
        raise ValueError(f"unknown case source {case.source!r}")
    return _make_result(case, observed)


_SAMPLE_CAP = 10


def _rates(n: int, match: int, review: int, create: int, samples: tuple[str, ...] = ()) -> Rates:
    if n == 0:
        return Rates(0, 0.0, 0.0, 0.0, ())
    return Rates(
        n, round(100 * match / n, 1), round(100 * review / n, 1), round(100 * create / n, 1), samples
    )


def replay_metacritic(matcher_set: MatcherSet, films: list[PoolFilm], titles: list[Any]) -> Rates:
    """Replay every parsed Metacritic archive title through the metacritic path,
    replicating match_archive's by-norm-title candidate bucket (baseline) or a full
    CandidateIndex over the corpus (new set — its own lookup does the bucketing)."""
    by_norm: dict[str, list[tuple[int, str, int | None]]] = defaultdict(list)
    index: new_matching.CandidateIndex | None = None
    if matcher_set.supports_runtime:
        index = new_matching.build_candidate_index(films)
    else:
        for f in films:
            by_norm[matcher_set.norm_title(f.title)].append((f.id, f.title, f.year))
    match = review = create = 0
    samples: list[str] = []
    for t in titles:
        if matcher_set.supports_runtime:
            assert index is not None
            # match_film does its own clean_title/split_annotations on the RAW title.
            result = matcher_set.match_film(t.title, t.year, index)
            verdict = _map_verdict_new(result)
        else:
            cleaned = matcher_set.clean_title(t.title)
            candidates = by_norm.get(matcher_set.norm_title(cleaned), [])
            result = matcher_set.match_film(cleaned, t.year, candidates)
            verdict = _map_verdict(result, candidates, review_on_no_winner=False)
        if verdict.startswith("match:"):
            match += 1
        elif verdict == "review":
            review += 1
            if len(samples) < _SAMPLE_CAP:
                samples.append(t.title)
        else:
            create += 1
    return _rates(len(titles), match, review, create, tuple(samples))


def replay_apple(matcher_set: MatcherSet, films: list[PoolFilm], lines: list[Any]) -> Rates:
    """Replay every Apple archive line through the apple path, replicating
    import_owned's by-norm-title candidate bucket (baseline) or a full CandidateIndex
    over the corpus (new set). The Apple archive is 2-column — no per-title runtime,
    so runtime_min is always None here (director/runtime evidence still flows from
    the corpus side via the enriched `films` rows)."""
    by_norm: dict[str, list[tuple[int, str, int | None]]] = defaultdict(list)
    index: new_matching.CandidateIndex | None = None
    if matcher_set.supports_runtime:
        index = new_matching.build_candidate_index(films)
    else:
        for f in films:
            by_norm[matcher_set.norm_title(f.title)].append((f.id, f.title, f.year))
    match = review = create = 0
    samples: list[str] = []
    for t in lines:
        cleaned, embedded_year = matcher_set.parse_apple_title(t.title)
        year = embedded_year if embedded_year is not None else t.year
        if matcher_set.supports_runtime:
            assert index is not None and matcher_set.split_annotations is not None
            rerelease_hint = bool(matcher_set.split_annotations(t.title)[1])
            result = matcher_set.match_owned(
                cleaned,
                year,
                index,
                embedded_year=embedded_year is not None,
                rerelease_hint=rerelease_hint,
                runtime_min=None,
            )
            verdict = _map_verdict_new(result)
        else:
            candidates = by_norm.get(matcher_set.norm_title(cleaned), [])
            result = matcher_set.match_owned(cleaned, year, candidates)
            verdict = _map_verdict(result, candidates, review_on_no_winner=True)
        if verdict.startswith("match:"):
            match += 1
        elif verdict == "review":
            review += 1
            if len(samples) < _SAMPLE_CAP:
                samples.append(t.title)
        else:
            create += 1
    return _rates(len(lines), match, review, create, tuple(samples))


# --------------------------------------------------------------------------- #
# Live data loading (read-only) + report.
# --------------------------------------------------------------------------- #

_RUNTIME_MIN = re.compile(r"(\d+)")


def _parse_runtime(raw: str | None) -> int | None:
    if not raw or raw == "N/A":
        return None
    m = _RUNTIME_MIN.match(raw)
    return int(m.group(1)) if m else None


def _parse_director(raw: str | None) -> str | None:
    if not raw or raw == "N/A":
        return None
    return raw


def load_films(db_path: Path) -> list[PoolFilm]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT f.id, f.title, f.year, "
            "COALESCE(f.director, NULLIF(json_extract(o.payload,'$.Director'), 'N/A')), "
            "NULLIF(json_extract(o.payload,'$.Runtime'), 'N/A') "
            "FROM films f LEFT JOIN omdb o ON o.film_id=f.id"
        ).fetchall()
    finally:
        conn.close()
    return [
        PoolFilm(int(r[0]), str(r[1]), r[2], _parse_director(r[3]), _parse_runtime(r[4])) for r in rows
    ]


def load_latest_apple_export(config_dir: Path) -> list[Any]:
    archive = config_dir / "appletv"
    files = sorted(archive.glob("owned-*.txt"))
    if not files:
        return []
    return appletv.parse_export(files[-1].read_text())


def _status(r: CaseResult) -> str:
    return "PASS" if r.passed else ("WRONG-MATCH" if r.wrong_match else "FAIL")


def _delta(baseline_r: CaseResult, new_r: CaseResult) -> str:
    if new_r.passed and not baseline_r.passed:
        return "FIXED"
    if baseline_r.passed and not new_r.passed:
        return "REGRESSED"
    return ""


def _print_case_table(baseline_results: list[CaseResult], new_results: list[CaseResult]) -> None:
    print(f"{'case':<32} {'expect':<12} {'baseline':<24} {'new':<24} {'delta'}")
    for b, n in zip(baseline_results, new_results, strict=True):
        assert b.name == n.name
        baseline_col = f"{b.observed} [{_status(b)}]"
        new_col = f"{n.observed} [{_status(n)}]"
        print(f"{b.name:<32} {b.expect:<12} {baseline_col:<24} {new_col:<24} {_delta(b, n)}")


def _print_summary(label: str, summary: GtSummary) -> None:
    print(
        f"\n{label}: {summary.passed} gt-pass / {summary.failed} gt-fail; "
        f"wrong-matches (matched a different id than expected): {summary.wrong}"
    )


def _print_rates(label: str, rates: Rates) -> None:
    print(
        f"{label}: n={rates.n} match={rates.match_pct}% review={rates.review_pct}% create={rates.create_pct}%"
    )
    if rates.review_samples:
        print(f"    review sample ({len(rates.review_samples)} of {rates.n}): {list(rates.review_samples)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--assert-dominance",
        action="store_true",
        help="exit 1 unless the new matcher has zero gt wrong-matches and each replay's review%% is under its ceiling",
    )
    args = parser.parse_args(argv)

    config = load_config()
    baseline_set = baseline_matcher_set()
    new_set = new_matcher_set()

    baseline_results = [run_case(case, baseline_set) for case in GROUND_TRUTHS]
    new_results = [run_case(case, new_set) for case in GROUND_TRUTHS]
    baseline_summary = summarize(baseline_results)
    new_summary = summarize(new_results)

    _print_case_table(baseline_results, new_results)
    _print_summary("baseline", baseline_summary)
    _print_summary("new", new_summary)
    print(f"\ndominates(baseline, new): {dominates(baseline_summary, new_summary)}")

    films = load_films(config.db_path)

    archive = metacritic.archive_dir(config.config_dir)
    mc_titles = metacritic.parse_archive(archive)
    baseline_mc_rates = replay_metacritic(baseline_set, films, mc_titles)
    new_mc_rates = replay_metacritic(new_set, films, mc_titles)

    apple_lines = load_latest_apple_export(config.config_dir)
    baseline_apple_rates = replay_apple(baseline_set, films, apple_lines)
    new_apple_rates = replay_apple(new_set, films, apple_lines)

    print("\nmetacritic archive replay:")
    _print_rates("  baseline", baseline_mc_rates)
    _print_rates("  new     ", new_mc_rates)
    print("\napple archive replay:")
    _print_rates("  baseline", baseline_apple_rates)
    _print_rates("  new     ", new_apple_rates)

    gate_ok = (
        new_summary.wrong == 0
        and new_mc_rates.review_pct < MAX_MC_REVIEW_PCT
        and new_apple_rates.review_pct < MAX_APPLE_REVIEW_PCT
    )
    if args.assert_dominance:
        print(
            f"\n--assert-dominance: {'PASS' if gate_ok else 'FAIL'} "
            f"(new gt-wrong={new_summary.wrong}, mc review%={new_mc_rates.review_pct}, "
            f"apple review%={new_apple_rates.review_pct})"
        )
        return 0 if gate_ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
