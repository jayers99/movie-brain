from __future__ import annotations

import sqlite3
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import requests

from movie_brain.domain.matching import pick_tmdb_match
from movie_brain.domain.models import ReviewEntry
from movie_brain.infrastructure.database import TMDB_REFRESH_STAMP, Repository, TmdbMatchTarget
from movie_brain.infrastructure.tmdb import AuthError, TmdbArbiter, TmdbClient, watch_link

TMDB_AUTHORITY = "tmdb"
STORE_PROVIDER_ID = 2  # Apple TV Store (iTunes) — the only rent/buy id we record
REFRESH_DAYS = 7
META_REFRESHED_AT = TMDB_REFRESH_STAMP
MAX_CONSECUTIVE_FAILURES = 5


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


@dataclass(frozen=True)
class TmdbStepResult:
    matched: int = 0
    missed: int = 0
    refreshed: int = 0
    watchlist_refreshed: int = 0


def queue_review_once(repo: Repository, authority: str, entry: ReviewEntry, today: date) -> bool:
    """Append a durable review row unless an open one with the same reason+film already exists.

    Durable reasons (year-collision, id-conflict) survive the per-run no-match rebuild,
    so idempotent passes must not stack duplicates.
    """
    for r in repo.open_reviews(authority):
        if r["reason"] == entry.reason and r["film_id"] == entry.film_id:
            return False
    repo.append_reviews(authority, [entry], today)
    return True


def record_tmdb_match(
    repo: Repository,
    target: TmdbMatchTarget,
    winner_id: int,
    winner_year: int | None,
    today: date,
    log: Callable[[str], None],
) -> str:
    """The one TMDB match write path: claim the id, flag found, canonicalize the year.

    Commerce-created films adopt TMDB's original year (spec principle 5) — a key
    collision is a detected twin and queues year-collision instead of overwriting.
    Returns "matched" (id claimed, no write-back needed), "adopted" (id claimed and
    the year write-back succeeded), "collision" (id claimed but the write-back
    collided — year-collision queued), or "id-conflict" (the id itself was already
    claimed by another film).
    """
    try:
        repo.set_external_id(target.film_id, TMDB_AUTHORITY, str(winner_id), today)
    except sqlite3.IntegrityError:
        holder = repo.film_id_for_external(TMDB_AUTHORITY, str(winner_id))
        log(f"tmdb id conflict for {target.title!r}: id {winner_id} already claimed by film {holder}")
        repo.upsert_tmdb(target.film_id, found=False, looked_up=today)
        queue_review_once(
            repo,
            TMDB_AUTHORITY,
            ReviewEntry(
                "id-conflict",
                film_id=target.film_id,
                value=str(winner_id),
                detail=f"{target.title!r} ({target.year}) vs film {holder} — same tmdb id, likely twins",
            ),
            today,
        )
        return "id-conflict"
    repo.upsert_tmdb(target.film_id, found=True, looked_up=today)
    if target.commerce and winner_year is not None and winner_year != target.year:
        clash = repo.update_film_year(target.film_id, winner_year)
        if clash is not None:
            queue_review_once(
                repo,
                TMDB_AUTHORITY,
                ReviewEntry(
                    "year-collision",
                    film_id=target.film_id,
                    value=str(clash),
                    detail=f"{target.title!r}: adopting {winner_year} over {target.year} "
                    f"collides with film {clash} — merge candidate",
                ),
                today,
            )
            return "collision"
        log(f"adopted TMDB year {winner_year} for {target.title!r} (was {target.year})")
        return "adopted"
    return "matched"


def tmdb_step(
    repo: Repository,
    client: TmdbClient,
    today: date,
    *,
    arbiter: TmdbArbiter | None = None,
    log: Callable[[str], None] = _stderr,
) -> TmdbStepResult:
    matched = missed = refreshed = 0
    consecutive = 0
    aborted = False
    arbiter = arbiter if arbiter is not None else TmdbArbiter(client)
    for target in repo.films_needing_tmdb_match():
        if consecutive >= MAX_CONSECUTIVE_FAILURES:
            log("TMDB searches failing repeatedly — stopping; next run resumes.")
            aborted = True
            break
        try:
            candidates = client.search(target.title)
        except AuthError as exc:
            log(f"TMDB rejected the token: {exc}")
            return TmdbStepResult(matched, missed, refreshed)
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
            missed += 1
        else:
            winner_year = next((c.year for c in candidates if c.tmdb_id == winner), None)
            if record_tmdb_match(repo, target, winner, winner_year, today, log) != "id-conflict":
                matched += 1
            else:
                missed += 1

    # Recomputed from found=0 rows each run, so a tripwired match pass never loses entries.
    # Scoped to reason="no-match" so it never wipes the durable year-collision/id-conflict
    # rows record_tmdb_match queues above — and a film already holding one of those durable
    # rows (also found=0, since it couldn't claim its id) is excluded here too, so it isn't
    # double-queued under both reasons.
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

    # A tripwired match pass means TMDB is unhealthy right now — don't start (or stamp) a
    # refresh pass that would then gate for a week having refreshed nothing.
    if aborted:
        return TmdbStepResult(matched, missed, refreshed)
    pmap = repo.provider_map()
    # Watchlist pass — every run, gate or no gate: the whole point is ≤1-day lag
    # for the ~50 films worth alerting on. Never touches the weekly stamp.
    wl_refreshed, wl_aborted = _refresh_pass(repo, client, repo.films_for_watchlist_refresh(), pmap, today, log)
    if wl_aborted:
        return TmdbStepResult(matched, missed, refreshed, wl_refreshed)
    stamp = repo.get_meta(META_REFRESHED_AT)
    if stamp is not None and 0 <= (today - date.fromisoformat(stamp)).days <= REFRESH_DAYS:
        return TmdbStepResult(matched, missed, refreshed, wl_refreshed)
    refreshed, full_aborted = _refresh_pass(
        repo, client, repo.films_for_provider_refresh(skip_checked_on=today), pmap, today, log
    )
    if full_aborted:
        return TmdbStepResult(matched, missed, refreshed, wl_refreshed)
    repo.set_meta(META_REFRESHED_AT, today.isoformat())
    return TmdbStepResult(matched, missed, refreshed, wl_refreshed)


def _refresh_pass(
    repo: Repository,
    client: TmdbClient,
    films: list[tuple[int, str, bool]],
    pmap: dict[int, str],
    today: date,
    log: Callable[[str], None],
) -> tuple[int, bool]:
    """Fetch + write providers for films; returns (refreshed, aborted)."""
    refreshed = 0
    consecutive = 0
    for film_id, tmdb_id, first_check in films:
        if consecutive >= MAX_CONSECUTIVE_FAILURES:
            log("TMDB provider lookups failing repeatedly — stopping; next run resumes.")
            return refreshed, True
        try:
            numeric_tmdb_id = int(tmdb_id)
        except ValueError:
            log(f"invalid tmdb id {tmdb_id!r} for film {film_id}")
            continue
        try:
            providers = client.watch_providers(numeric_tmdb_id)
        except AuthError as exc:
            log(f"TMDB rejected the token: {exc}")
            return refreshed, True
        except requests.RequestException as exc:
            log(f"TMDB providers failed for film {film_id}: {exc}")
            consecutive += 1
            continue
        consecutive = 0
        slugs = {pmap[p] for p in providers.flatrate if p in pmap and pmap[p] != "criterion"}
        if STORE_PROVIDER_ID in pmap and STORE_PROVIDER_ID in (*providers.rent, *providers.buy):
            slugs.add(pmap[STORE_PROVIDER_ID])
        url = providers.link or watch_link(numeric_tmdb_id)
        for slug in sorted(slugs):
            if first_check:
                # First-ever observation of this film's providers: baseline, not a
                # transition — you can't detect an *arrival* without a prior look.
                repo.record_listing(film_id, slug, url, today)
            else:
                repo.record_listing_with_transition(film_id, slug, url, today)
        repo.record_tmdb_providers(film_id, today, providers.payload)
        refreshed += 1
    return refreshed, False
