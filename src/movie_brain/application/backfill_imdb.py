"""Fill in the IMDb id TMDB already knows, for films that hold a TMDB id and no IMDb one.

The write goes through `key_film` — the one identity write path — with `tmdb_id=None` and
`resolve_tmdb_id=False`. That pair is deliberate and is the whole point of the verb (spec D10):
the film's TMDB link already exists, so `record_tmdb_match` must not run again. If it did, it
would canonicalize `films.year` on every commerce-created film whose TMDB year differs — 1,236
films — turning "write a missing id" into a year migration nobody asked for.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import requests

from movie_brain.application.availability import TMDB_AUTHORITY, queue_review_once
from movie_brain.application.keying import MAX_CONSECUTIVE_FAILURES, key_film
from movie_brain.domain.models import ReviewEntry
from movie_brain.infrastructure.database import Repository
from movie_brain.infrastructure.tmdb import AuthError, TmdbClient


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


@dataclass(frozen=True)
class BackfillReport:
    scanned: int = 0
    backfilled: int = 0
    no_imdb: int = 0
    held: int = 0
    failed: int = 0
    aborted: bool = False


def backfill_imdb(
    repo: Repository,
    tmdb: TmdbClient,
    today: date,
    *,
    apply: bool = False,
    limit: int | None = None,
    log: Callable[[str], None] = _stderr,
) -> BackfillReport:
    scanned = backfilled = no_imdb = held = failed = 0
    consecutive = 0
    aborted = False
    for target in repo.films_needing_imdb_backfill(limit):
        if consecutive >= MAX_CONSECUTIVE_FAILURES:
            log("TMDB lookups failing repeatedly — stopping; the next run resumes.")
            aborted = True
            break
        scanned += 1
        try:
            tt = tmdb.imdb_id(target.tmdb_id)
        except (requests.RequestException, AuthError) as exc:
            log(f"  #{target.film_id} {target.title!r}: TMDB lookup failed: {exc}")
            consecutive += 1
            failed += 1
            continue
        consecutive = 0
        if not tt:
            log(f"  #{target.film_id} {target.title!r}: TMDB publishes no imdb id for {target.tmdb_id}")
            no_imdb += 1
            continue
        if not apply:
            log(f"  #{target.film_id} {target.title!r} ({target.year}) → {tt}")
            backfilled += 1
            continue
        result = key_film(
            repo, tmdb, target.film_id, tt, today, log, tmdb_id=None, resolve_tmdb_id=False
        )
        if result.status in ("keyed", "unlinked"):
            log(f"  #{target.film_id} {target.title!r} ({target.year}) → {tt}")
            backfilled += 1
            continue
        if result.status == "error":
            log(f"  #{target.film_id} {target.title!r}: {result.detail}")
            consecutive += 1
            failed += 1
            continue
        # held: the id belongs to another film. A twin, and never a silent overwrite.
        queue_review_once(
            repo,
            TMDB_AUTHORITY,
            ReviewEntry(
                "id-conflict",
                film_id=target.film_id,
                value=tt,
                detail=f"{target.title!r} ({target.year}) — {result.detail}, likely twins",
            ),
            today,
        )
        held += 1
    return BackfillReport(scanned, backfilled, no_imdb, held, failed, aborted)
