from __future__ import annotations

import sqlite3
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import requests

from movie_brain.domain.matching import pick_tmdb_match
from movie_brain.domain.models import ReviewEntry
from movie_brain.infrastructure.database import TMDB_REFRESH_STAMP, Repository
from movie_brain.infrastructure.tmdb import AuthError, TmdbClient, watch_link

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


def tmdb_step(
    repo: Repository, client: TmdbClient, today: date, log: Callable[[str], None] = _stderr
) -> TmdbStepResult:
    matched = missed = refreshed = 0
    consecutive = 0
    aborted = False
    for film_id, title, year in repo.films_needing_tmdb_match():
        if consecutive >= MAX_CONSECUTIVE_FAILURES:
            log("TMDB searches failing repeatedly — stopping; next run resumes.")
            aborted = True
            break
        try:
            candidates = client.search(title)
        except AuthError as exc:
            log(f"TMDB rejected the token: {exc}")
            return TmdbStepResult(matched, missed, refreshed)
        except requests.RequestException as exc:
            log(f"TMDB search failed for {title!r}: {exc}")
            consecutive += 1
            continue
        consecutive = 0
        winner = pick_tmdb_match(title, year, candidates)
        if winner is None:
            repo.upsert_tmdb(film_id, found=False, looked_up=today)
            missed += 1
        else:
            try:
                repo.set_external_id(film_id, TMDB_AUTHORITY, str(winner), today)
            except sqlite3.IntegrityError:
                # UNIQUE(authority, value): another film already claimed this tmdb id.
                # Contain it here — one bad match must never block the whole step; queue
                # this film for review and move on, same as an ordinary no-match.
                log(f"tmdb id conflict for {title!r}: id {winner} already claimed")
                repo.upsert_tmdb(film_id, found=False, looked_up=today)
                missed += 1
                continue
            repo.upsert_tmdb(film_id, found=True, looked_up=today)
            matched += 1

    # Recomputed from found=0 rows each run, so a tripwired match pass never loses entries.
    repo.replace_unresolved_reviews(
        TMDB_AUTHORITY,
        [ReviewEntry("no-match", film_id=fid, detail=f"{t} ({y})") for fid, t, y in repo.films_tmdb_missed()],
        today,
    )

    # A tripwired match pass means TMDB is unhealthy right now — don't start (or stamp) a
    # refresh pass that would then gate for a week having refreshed nothing.
    if aborted:
        return TmdbStepResult(matched, missed, refreshed)
    stamp = repo.get_meta(META_REFRESHED_AT)
    if stamp is not None and 0 <= (today - date.fromisoformat(stamp)).days <= REFRESH_DAYS:
        return TmdbStepResult(matched, missed, refreshed)
    pmap = repo.provider_map()
    consecutive = 0
    for film_id, tmdb_id in repo.films_for_provider_refresh():
        if consecutive >= MAX_CONSECUTIVE_FAILURES:
            log("TMDB provider lookups failing repeatedly — stopping; next run resumes.")
            return TmdbStepResult(matched, missed, refreshed)
        try:
            numeric_tmdb_id = int(tmdb_id)
        except ValueError:
            log(f"invalid tmdb id {tmdb_id!r} for film {film_id}")
            continue
        try:
            providers = client.watch_providers(numeric_tmdb_id)
        except AuthError as exc:
            log(f"TMDB rejected the token: {exc}")
            return TmdbStepResult(matched, missed, refreshed)
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
            repo.record_listing(film_id, slug, url, today)
        repo.record_tmdb_providers(film_id, today, providers.payload)
        refreshed += 1
    repo.set_meta(META_REFRESHED_AT, today.isoformat())
    return TmdbStepResult(matched, missed, refreshed)
