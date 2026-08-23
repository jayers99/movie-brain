from __future__ import annotations

import sqlite3
import sys
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import requests

from movie_brain.domain.matching import clean_title, match_film, norm_title
from movie_brain.domain.models import McTitle, ReviewEntry
from movie_brain.infrastructure import metacritic as mc
from movie_brain.infrastructure.database import Repository

AUTHORITY = "metacritic"


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


@dataclass(frozen=True)
class CrawlReport:
    exit_code: int
    fetched: int
    skipped: int
    archived: int  # pages now in the archive


@dataclass(frozen=True)
class MatchReport:
    exit_code: int
    pages: int
    titles: int
    floor: int | None
    films: int
    matched: int
    expected_missed: int
    review_open: int
    warnings: tuple[str, ...] = ()

    @property
    def unmatched(self) -> int:
        return self.films - self.matched


def crawl_archive(
    config_dir: Path,
    pages: int,
    *,
    session: requests.Session | None = None,
    delay_s: float = 3.0,
    log: Callable[[str], None] = _stderr,
) -> CrawlReport:
    archive = mc.archive_dir(config_dir)
    result = mc.crawl(archive, pages, session or requests.Session(), delay_s=delay_s, log=log)
    return CrawlReport(1 if result.failed else 0, result.fetched, result.skipped, len(mc.archived_pages(archive)))


def _verify(titles: list[McTitle]) -> list[str]:
    """Post-crawl contract checks — warnings, never failures."""
    warnings: list[str] = []
    by_page: dict[int, int] = defaultdict(int)
    for t in titles:
        by_page[t.page] += 1
    last_page = max(by_page) if by_page else 0
    for page, count in sorted(by_page.items()):
        if count != mc.CARDS_PER_PAGE and page != last_page:
            warnings.append(f"page {page}: {count} cards (expected {mc.CARDS_PER_PAGE})")
    scores_in_rank = [t.score for t in sorted(titles, key=lambda t: t.rank) if t.score is not None]
    if any(a < b for a, b in zip(scores_in_rank, scores_in_rank[1:], strict=False)):
        warnings.append("scores are not monotonically non-increasing through the walk")
    slugs = [t.slug for t in titles]
    if len(set(slugs)) != len(slugs):
        warnings.append("duplicate slugs across pages (walk shifted between fetches)")
    return warnings


def match_archive(
    repo: Repository,
    config_dir: Path,
    today: date,
    *,
    log: Callable[[str], None] = _stderr,
) -> MatchReport:
    """Offline and idempotent: parse the archive, stage titles, link films, report coverage.

    Direction is archive → films: a film absent from the archive is coverage, not an
    anomaly. Only genuine anomalies queue for review. Nothing is ever deleted.
    """
    archive = mc.archive_dir(config_dir)
    titles = mc.parse_archive(archive)
    if not titles:
        log("no archive — run `movie-brain metacritic crawl` first")
        return MatchReport(1, 0, 0, None, 0, 0, 0, 0)
    warnings = _verify(titles)
    for w in warnings:
        log(f"warning: {w}")
    repo.upsert_mc_titles(titles, today)

    films = repo.films_for_matching()
    by_norm: dict[str, list[tuple[int, str, int | None]]] = defaultdict(list)
    for film_id, title, year, _ in films:
        by_norm[norm_title(title)].append((film_id, title, year))

    reviews: list[ReviewEntry] = []
    slugs_by_film: dict[int, list[str]] = defaultdict(list)
    for t in titles:
        cleaned = clean_title(t.title)
        result = match_film(cleaned, t.year, by_norm.get(norm_title(cleaned), []))
        if result.tied:
            detail = f"films {sorted(result.tied)} tie for {t.title!r} ({t.year})"
            reviews.append(ReviewEntry("ambiguous-title", value=t.slug, detail=detail))
        elif result.winner is not None:
            slugs_by_film[result.winner].append(t.slug)

    for film_id, slugs in sorted(slugs_by_film.items()):
        if len(slugs) > 1:
            reviews.append(ReviewEntry("film-multiple-slugs", film_id=film_id, detail=", ".join(sorted(slugs))))
            continue
        try:
            repo.set_external_id(film_id, AUTHORITY, slugs[0], today)
        except sqlite3.IntegrityError:
            # UNIQUE(authority, value): the slug is already another film's id. Contain and
            # queue — one conflict must never abort the run (same posture as record_catalog).
            detail = "slug already claimed by another film"
            reviews.append(ReviewEntry("slug-conflict", film_id=film_id, value=slugs[0], detail=detail))

    linked = repo.film_ids_with_external(AUTHORITY)
    scores = [t.score for t in titles if t.score is not None]
    floor = min(scores) if scores else None
    expected_missed = 0
    for film_id, title, year, omdb_mc in films:
        if omdb_mc is not None and floor is not None and omdb_mc >= floor and film_id not in linked:
            expected_missed += 1
            detail = f"omdb metascore {omdb_mc} >= floor {floor}, no archive match for {title!r} ({year})"
            reviews.append(ReviewEntry("expected-miss", film_id=film_id, detail=detail))

    repo.replace_unresolved_reviews(AUTHORITY, reviews, today)
    return MatchReport(
        exit_code=0,
        pages=len(mc.archived_pages(archive)),
        titles=len(titles),
        floor=floor,
        films=len(films),
        matched=len(linked),
        expected_missed=expected_missed,
        review_open=len(repo.open_reviews(AUTHORITY)),
        warnings=tuple(warnings),
    )
