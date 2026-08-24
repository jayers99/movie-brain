"""Offline benchmark: score matchers (frozen baseline today, the new evidence-scored
core later) against a banked ground-truth suite and a replay of the real archives.

Read-only: opens movie-brain.db with ``mode=ro`` and never touches the DB or config
dir. ``MatcherSet`` is the plug point Task 6 uses to run the new matchers through the
same ``run_case``/``replay_*`` machinery, side by side with this frozen baseline.
"""

from __future__ import annotations

import importlib.util
import re
import sqlite3
import sys
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NamedTuple, Protocol

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
    ) -> None:
        self.norm_title = norm_title
        self.clean_title = clean_title
        self.match_film = match_film
        self.match_owned = match_owned
        self.pick_tmdb_match = pick_tmdb_match
        self.parse_apple_title = parse_apple_title
        self.supports_runtime = supports_runtime


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
]


# --------------------------------------------------------------------------- #
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


def _is_wrong_match(observed: str, expect: str) -> bool:
    return observed.startswith("match:") and observed != expect


def run_case(case: Case, matcher_set: MatcherSet) -> CaseResult:
    """Dispatch by source, mapping the raw matcher return onto the verdict vocabulary
    exactly as the live callers (match_archive / import_owned / the tmdb step) do."""
    if case.source == "metacritic":
        cleaned = matcher_set.clean_title(case.title)
        key = matcher_set.norm_title(cleaned)
        candidates = _pool_candidates(case.pool, matcher_set.norm_title, key)
        result = matcher_set.match_film(cleaned, case.year, candidates)
        observed = _map_verdict(result, candidates, review_on_no_winner=False)
    elif case.source == "apple":
        cleaned, embedded_year = matcher_set.parse_apple_title(case.title)
        year = embedded_year if embedded_year is not None else case.year
        key = matcher_set.norm_title(cleaned)
        candidates = _pool_candidates(case.pool, matcher_set.norm_title, key)
        if matcher_set.supports_runtime:
            result = matcher_set.match_owned(
                cleaned, year, candidates, runtime_min=case.runtime_min, embedded_year=embedded_year
            )
        else:
            result = matcher_set.match_owned(cleaned, year, candidates)
        observed = _map_verdict(result, candidates, review_on_no_winner=True)
    elif case.source == "tmdb":
        winner = matcher_set.pick_tmdb_match(case.title, case.year, list(case.tmdb))
        observed = f"match:{winner}" if winner is not None else "none"
    else:
        raise ValueError(f"unknown case source {case.source!r}")
    return CaseResult(
        name=case.name,
        expect=case.expect,
        observed=observed,
        passed=observed == case.expect,
        wrong_match=_is_wrong_match(observed, case.expect),
    )


def _rates(n: int, match: int, review: int, create: int) -> Rates:
    if n == 0:
        return Rates(0, 0.0, 0.0, 0.0)
    return Rates(n, round(100 * match / n, 1), round(100 * review / n, 1), round(100 * create / n, 1))


def replay_metacritic(matcher_set: MatcherSet, films: list[PoolFilm], titles: list[Any]) -> Rates:
    """Replay every parsed Metacritic archive title through the metacritic path,
    replicating match_archive's by-norm-title candidate bucket."""
    by_norm: dict[str, list[tuple[int, str, int | None]]] = defaultdict(list)
    for f in films:
        by_norm[matcher_set.norm_title(f.title)].append((f.id, f.title, f.year))
    match = review = create = 0
    for t in titles:
        cleaned = matcher_set.clean_title(t.title)
        candidates = by_norm.get(matcher_set.norm_title(cleaned), [])
        result = matcher_set.match_film(cleaned, t.year, candidates)
        verdict = _map_verdict(result, candidates, review_on_no_winner=False)
        if verdict.startswith("match:"):
            match += 1
        elif verdict == "review":
            review += 1
        else:
            create += 1
    return _rates(len(titles), match, review, create)


def replay_apple(matcher_set: MatcherSet, films: list[PoolFilm], lines: list[Any]) -> Rates:
    """Replay every Apple archive line through the apple path, replicating
    import_owned's by-norm-title candidate bucket."""
    by_norm: dict[str, list[tuple[int, str, int | None]]] = defaultdict(list)
    for f in films:
        by_norm[matcher_set.norm_title(f.title)].append((f.id, f.title, f.year))
    match = review = create = 0
    for t in lines:
        cleaned, embedded_year = matcher_set.parse_apple_title(t.title)
        year = embedded_year if embedded_year is not None else t.year
        candidates = by_norm.get(matcher_set.norm_title(cleaned), [])
        if matcher_set.supports_runtime:
            result = matcher_set.match_owned(cleaned, year, candidates, runtime_min=None, embedded_year=embedded_year)
        else:
            result = matcher_set.match_owned(cleaned, year, candidates)
        verdict = _map_verdict(result, candidates, review_on_no_winner=True)
        if verdict.startswith("match:"):
            match += 1
        elif verdict == "review":
            review += 1
        else:
            create += 1
    return _rates(len(lines), match, review, create)


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
            "SELECT f.id, f.title, f.year, COALESCE(f.director, json_extract(o.payload,'$.Director')), "
            "json_extract(o.payload,'$.Runtime') FROM films f LEFT JOIN omdb o ON o.film_id=f.id"
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


def _print_case_table(results: list[CaseResult]) -> None:
    print(f"{'case':<32} {'expect':<12} {'observed':<14} {'result'}")
    for r in results:
        status = "PASS" if r.passed else ("WRONG-MATCH" if r.wrong_match else "FAIL")
        print(f"{r.name:<32} {r.expect:<12} {r.observed:<14} {status}")


def _print_summary(results: list[CaseResult]) -> None:
    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed
    wrong = sum(1 for r in results if r.wrong_match)
    print(
        f"\nbaseline: {passed} gt-pass / {failed} gt-fail; "
        f"wrong-matches (matched a different id than expected): {wrong}"
    )


def _print_rates(label: str, rates: Rates) -> None:
    print(
        f"{label}: n={rates.n} match={rates.match_pct}% review={rates.review_pct}% create={rates.create_pct}%"
    )


def main() -> int:
    config = load_config()
    matcher_set = baseline_matcher_set()

    results = [run_case(case, matcher_set) for case in GROUND_TRUTHS]
    _print_case_table(results)
    _print_summary(results)

    films = load_films(config.db_path)

    archive = metacritic.archive_dir(config.config_dir)
    mc_titles = metacritic.parse_archive(archive)
    mc_rates = replay_metacritic(matcher_set, films, mc_titles)

    apple_lines = load_latest_apple_export(config.config_dir)
    apple_rates = replay_apple(matcher_set, films, apple_lines)

    print()
    _print_rates("metacritic archive replay", mc_rates)
    _print_rates("apple archive replay", apple_rates)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
