from __future__ import annotations

import sqlite3
import sys
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import requests

from movie_brain.domain.matching import Arbiter, build_candidate_index, clean_title, match_film
from movie_brain.domain.models import Film, McTitle, ReviewEntry
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


MC_TOP_N_KEY = "mc_top_n"
DEFAULT_TOP_N = 100
MC_MOVIE_URL = "https://www.metacritic.com/movie/{slug}/"


@dataclass(frozen=True)
class PromoteReport:
    exit_code: int
    n: int
    available: int  # staged titles within rank <= n (short archive → available < n)
    promoted: int
    already_linked: int
    skipped_anomalous: int
    key_conflicts: int
    match: MatchReport | None = None


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
    arbiter: Arbiter | None = None,
    log: Callable[[str], None] = _stderr,
) -> MatchReport:
    """Offline and idempotent: parse the archive, stage titles, link films, report coverage.

    Direction is archive → films: a film absent from the archive is coverage, not an
    anomaly. Only genuine anomalies queue for review. Nothing is ever deleted.
    """
    archive = mc.archive_dir(config_dir)
    archived_page_count = len(mc.archived_pages(archive))
    titles = mc.parse_archive(archive)
    if not titles:
        if archived_page_count:
            log(f"archive has {archived_page_count} pages but no titles parsed — check the parser")
        else:
            log("no archive — run `movie-brain metacritic crawl` first")
        return MatchReport(1, archived_page_count, 0, None, 0, 0, 0, 0)
    warnings = _verify(titles)
    for w in warnings:
        log(f"warning: {w}")
    repo.upsert_mc_titles(titles, today)

    films = repo.films_for_matching()
    index = build_candidate_index(films)

    # Dedupe by slug before matching: the sorted walk can shift between crawl sessions and
    # re-place the same title on a second page. _verify (above) already saw the raw list and
    # warned on genuine duplicates; from here on, a slug is one card. Last occurrence wins,
    # consistent with the staging upsert's last-wins semantics.
    deduped_titles = list({t.slug: t for t in titles}.values())

    # A slug already claimed by a film can never be promoted (promote_top_n checks
    # claimed BEFORE the anomalous-review skip), so a year-gap entry for an already-claimed
    # slug is pure noise that replace_unresolved_reviews would re-add every sync. Only
    # unclaimed slugs — the ones promotion could actually twin — need the review.
    claimed = repo.claimed_values(AUTHORITY)

    reviews: list[ReviewEntry] = []
    slugs_by_film: dict[int, list[str]] = defaultdict(list)
    for t in deduped_titles:
        # match_film does its own clean_title/split_annotations — pass the raw title so
        # it can detect edition annotations itself (rerelease_hint corroborates a
        # trailing year-gap, e.g. a re-release stamped years after the original).
        result = match_film(t.title, t.year, index, arbiter=arbiter)
        if result.tied:
            detail = f"films {sorted(result.tied)} tie for {t.title!r} ({t.year})"
            reviews.append(ReviewEntry("ambiguous-title", value=t.slug, detail=detail))
        elif result.winner is not None:
            slugs_by_film[result.winner].append(t.slug)
        elif result.reason is not None and t.slug not in claimed:
            # A non-tie review verdict (e.g. year-gap): must land in match_review so
            # promote_top_n's anomalous-slug skip prevents a twin being created for
            # this review-band title (Tokyo Story class).
            detail = f"{t.title!r} ({t.year}) vs review reason {result.reason!r}"
            reviews.append(ReviewEntry("year-gap", value=t.slug, detail=detail))

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
    for row in films:
        if row.omdb_mc is not None and floor is not None and row.omdb_mc >= floor and row.id not in linked:
            expected_missed += 1
            detail = f"omdb metascore {row.omdb_mc} >= floor {floor}, no archive match for {row.title!r} ({row.year})"
            reviews.append(ReviewEntry("expected-miss", film_id=row.id, detail=detail))

    repo.replace_unresolved_reviews(AUTHORITY, reviews, today)
    return MatchReport(
        exit_code=0,
        pages=archived_page_count,
        titles=len(titles),
        floor=floor,
        films=len(films),
        matched=len(linked),
        expected_missed=expected_missed,
        review_open=len(repo.open_reviews(AUTHORITY)),
        warnings=tuple(warnings),
    )


def promote_top_n(
    repo: Repository,
    config_dir: Path,
    today: date,
    n: int,
    *,
    arbiter: Arbiter | None = None,
    log: Callable[[str], None] = _stderr,
) -> PromoteReport:
    """Mode B: turn the top-N staged titles into real films (offline, idempotent).

    match_archive runs first so every slug an existing film can claim is claimed —
    the dedup guard. Promotion then only ever creates films for slugs nobody owns;
    a film_key collision is the tripwire and queues for review, never overwrites.
    """
    match_report = match_archive(repo, config_dir, today, arbiter=arbiter, log=log)
    if match_report.exit_code != 0:
        return PromoteReport(1, n, 0, 0, 0, 0, 0, match_report)
    claimed = repo.claimed_values(AUTHORITY)
    anomalous = {str(r["value"]) for r in repo.open_reviews(AUTHORITY) if r["value"]}
    tombstoned = repo.tombstoned_keys()
    candidates = repo.top_staged_titles(n)
    reviews: list[ReviewEntry] = []
    promoted = already_linked = skipped = conflicts = 0
    for t in candidates:
        if t.slug in claimed:
            already_linked += 1
            continue
        if t.slug in anomalous:
            skipped += 1
            continue
        film = Film(clean_title(t.title), t.year, None, MC_MOVIE_URL.format(slug=t.slug))
        if film.key in tombstoned:
            # A human hid this film; the archive re-surfacing its title/year is not a
            # resurrection request. Never overwrite, never re-promote.
            skipped += 1
            continue
        film_id = repo.create_film(film)
        if film_id is None:
            existing = repo.canonical_film_id(repo.film_id_by_key(film.key) or 0)
            conflicts += 1
            detail = f"promotion of {t.title!r} ({t.year}) collides with existing key {film.key!r}"
            reviews.append(ReviewEntry("key-conflict", film_id=existing, value=t.slug, detail=detail))
            continue
        try:
            repo.set_external_id(film_id, AUTHORITY, t.slug, today)
        except sqlite3.IntegrityError:
            reviews.append(
                ReviewEntry(
                    "slug-conflict", film_id=film_id, value=t.slug, detail="slug already claimed by another film"
                )
            )
            continue
        claimed.add(t.slug)
        promoted += 1
    if reviews:
        repo.append_reviews(AUTHORITY, reviews, today)
    return PromoteReport(0, n, len(candidates), promoted, already_linked, skipped, conflicts, match_report)
