from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import requests

from movie_brain.application.availability import (
    MAX_CONSECUTIVE_FAILURES,
    TMDB_AUTHORITY,
    queue_review_once,
    record_tmdb_match,
)
from movie_brain.domain.matching import pick_tmdb_match
from movie_brain.domain.models import ReviewEntry
from movie_brain.infrastructure.database import Repository
from movie_brain.infrastructure.tmdb import AuthError, TmdbArbiter, TmdbClient


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


@dataclass(frozen=True)
class RematchReport:
    exit_code: int
    misses: int
    rematched: int
    still_missed: int
    id_conflicts: int
    checked: int
    years_adopted: int
    collisions_queued: int
    uncorrected: int


def rematch(
    repo: Repository, client: TmdbClient, today: date, *, log: Callable[[str], None] = _stderr
) -> RematchReport:
    """One-shot, idempotent: rematch every TMDB miss, reconcile every non-Criterion year.

    Pass A re-runs the shared matcher (commerce-tolerant, arbitrated) over tmdb.found=0
    films. Pass B fresh-checks TMDB's release year for every matched non-Criterion film
    and adopts disagreements through the same write-back path the sync uses. Provider
    fetches are NOT done here — newly matched films keep providers_checked_at NULL, so
    their first nightly provider pass stays a quiet baseline, not a transition storm.
    """
    arbiter = TmdbArbiter(client)
    misses = repo.films_tmdb_missed_targets()
    rematched = still_missed = id_conflicts = 0
    checked = years_adopted = collisions_queued = uncorrected = 0
    consecutive = 0
    for target in misses:
        if consecutive >= MAX_CONSECUTIVE_FAILURES:
            log("TMDB failing repeatedly — stopping; rematch is safe to re-run.")
            return RematchReport(1, len(misses), rematched, still_missed, id_conflicts, 0, 0, 0, 0)
        try:
            candidates = client.search(target.title)
        except AuthError as exc:
            log(f"TMDB rejected the token: {exc}")
            return RematchReport(2, len(misses), rematched, still_missed, id_conflicts, 0, 0, 0, 0)
        except requests.RequestException as exc:
            log(f"TMDB search failed for {target.title!r}: {exc}")
            consecutive += 1
            continue
        consecutive = 0
        arbiter.seed(target.title, candidates)
        winner = pick_tmdb_match(
            target.title,
            target.year,
            candidates,
            commerce_year=target.commerce,
            arbiter=arbiter if target.commerce else None,
        )
        if winner is None:
            repo.upsert_tmdb(target.film_id, found=False, looked_up=today)
            still_missed += 1
            continue
        winner_year = next((c.year for c in candidates if c.tmdb_id == winner), None)
        # record_tmdb_match does its own commerce year write-back on a match (spec
        # principle 5) — a large database-vs-TMDB gap adopts (or collides) right here,
        # before pass B ever sees this film. Its widened return contract tells us
        # directly which happened, so a single rematch() call reports every year fix
        # it made, not just the ones pass B happened to re-discover.
        outcome = record_tmdb_match(repo, target, winner, winner_year, today, log)
        if outcome == "id-conflict":
            id_conflicts += 1
        else:
            rematched += 1
            if outcome == "adopted":
                years_adopted += 1
            elif outcome == "collision":
                collisions_queued += 1

    for film_id, title, year, tmdb_value in repo.commerce_films_with_tmdb():
        if consecutive >= MAX_CONSECUTIVE_FAILURES:
            log("TMDB failing repeatedly — stopping; rematch is safe to re-run.")
            break
        try:
            tmdb_year = client.movie_year(int(tmdb_value))
        except AuthError as exc:
            log(f"TMDB rejected the token: {exc}")
            return RematchReport(
                2,
                len(misses),
                rematched,
                still_missed,
                id_conflicts,
                checked,
                years_adopted,
                collisions_queued,
                uncorrected,
            )
        except requests.RequestException as exc:
            log(f"TMDB details failed for film {film_id}: {exc}")
            consecutive += 1
            uncorrected += 1
            continue
        except ValueError:
            log(f"invalid tmdb id {tmdb_value!r} for film {film_id}")
            uncorrected += 1
            continue
        consecutive = 0
        checked += 1
        if tmdb_year is None or year == tmdb_year:
            continue
        clash = repo.update_film_year(film_id, tmdb_year)
        if clash is None:
            log(f"adopted TMDB year {tmdb_year} for {title!r} (was {year})")
            years_adopted += 1
        else:
            collisions_queued += 1
            queue_review_once(
                repo,
                TMDB_AUTHORITY,
                ReviewEntry(
                    "year-collision",
                    film_id=film_id,
                    value=str(clash),
                    detail=f"{title!r}: adopting {tmdb_year} over {year} collides with film {clash} — merge candidate",
                ),
                today,
            )

    # Recomputed from found=0 rows each run, mirroring tmdb_step's rebuild: a film
    # already holding an open durable review (year-collision, id-conflict) under a
    # non-"no-match" reason is excluded here too, so it isn't double-queued.
    durably_flagged = {r["film_id"] for r in repo.open_reviews(TMDB_AUTHORITY) if r["reason"] != "no-match"}
    repo.replace_unresolved_reviews(
        TMDB_AUTHORITY,
        [
            ReviewEntry("no-match", film_id=fid, detail=f"{t} ({y})")
            for fid, t, y in repo.films_tmdb_missed()
            if fid not in durably_flagged
        ],
        today,
        reason="no-match",
    )
    tripwired = consecutive >= MAX_CONSECUTIVE_FAILURES
    return RematchReport(
        1 if tripwired else 0,
        len(misses),
        rematched,
        still_missed,
        id_conflicts,
        checked,
        years_adopted,
        collisions_queued,
        uncorrected,
    )
