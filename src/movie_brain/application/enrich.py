"""Enrich films with TMDB credits, keywords, overview and tagline — the data under the search bar.

One call per film (`TmdbClient.movie_credits`, spec D11). Dry-run by default: the calls are
made and logged, nothing is written. `--apply` writes each film through `write_credits`, which
replaces that film's rows in one transaction and stamps `tmdb_facts.credits_fetched_on`; the
worklist excludes stamped films, so an interrupted run resumes where it stopped. The
consecutive-failure abort is `application/keying.py`'s — the same shape as `repair imdb`.
Never called from `sync` (spec §5).
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import requests

from movie_brain.application.keying import MAX_CONSECUTIVE_FAILURES
from movie_brain.infrastructure.database import Repository
from movie_brain.infrastructure.tmdb import AuthError, TmdbClient

DELAY_S = 0.25  # TMDB advertises no limit; a quarter second keeps ~4,600 calls polite


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


@dataclass(frozen=True)
class EnrichReport:
    scanned: int = 0
    enriched: int = 0
    failed: int = 0
    aborted: bool = False


def enrich_credits(
    repo: Repository,
    tmdb: TmdbClient,
    today: date,
    *,
    apply: bool = False,
    limit: int | None = None,
    delay_s: float = DELAY_S,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = _stderr,
) -> EnrichReport:
    scanned = enriched = failed = consecutive = 0
    requested = False
    for target in repo.films_needing_credits(limit):
        if consecutive >= MAX_CONSECUTIVE_FAILURES:
            log("TMDB credit lookups failing repeatedly — stopping; the next run resumes.")
            return EnrichReport(scanned, enriched, failed, aborted=True)
        if requested:
            sleep(delay_s)
        requested = True
        scanned += 1
        try:
            credits = tmdb.movie_credits(target.tmdb_id)
        except (requests.RequestException, AuthError) as exc:
            log(f"  #{target.film_id} {target.title!r}: TMDB credits failed: {exc}")
            consecutive += 1
            failed += 1
            continue
        consecutive = 0
        log(
            f"  #{target.film_id} {target.title!r}: {len(credits.cast)} cast · {len(credits.crew)} crew · "
            f"{len(credits.keywords)} keywords" + ("" if credits.overview else " · no overview")
        )
        if apply:
            repo.write_credits(target.film_id, credits, today)
        enriched += 1
    return EnrichReport(scanned, enriched, failed)
