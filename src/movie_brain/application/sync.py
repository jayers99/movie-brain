from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import requests

from movie_brain.application.availability import TmdbStepResult, tmdb_step
from movie_brain.application.metacritic import DEFAULT_TOP_N, MC_TOP_N_KEY, promote_top_n
from movie_brain.domain.models import merge_yearless
from movie_brain.infrastructure.criterion import CatalogError, fetch_films, fetch_leaving, fetch_token, page_one_matches
from movie_brain.infrastructure.database import Repository
from movie_brain.infrastructure.metacritic import CARDS_PER_PAGE
from movie_brain.infrastructure.omdb import AuthError, OmdbClient, QuotaExceeded
from movie_brain.infrastructure.tmdb import TmdbArbiter, TmdbClient

SOURCE = "criterion"
MAX_CONSECUTIVE_FAILURES = 5


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


@dataclass(frozen=True)
class SyncResult:
    exit_code: int
    full_walk: bool
    films: int
    looked_up: int
    quota_hit: bool
    failing: bool
    tmdb_matched: int = 0
    tmdb_missed: int = 0
    tmdb_refreshed: int = 0
    tmdb_watchlist_refreshed: int = 0
    mc_promoted: int = 0


def sync(
    repo: Repository,
    api_key: str,
    today: date,
    *,
    session: requests.Session | None = None,
    delay_s: float = 0.25,
    force_full: bool = False,
    ratings_only: bool = False,
    max_age_days: int = 7,
    tmdb_token: str | None = None,
    config_dir: Path | None = None,
    notifier: Callable[[str, str], None] | None = None,
    log: Callable[[str], None] = _stderr,
) -> SyncResult:
    session = session or requests.Session()
    known = [f for _, f in repo.current_films(SOURCE)]
    full_walk = False

    if ratings_only:
        if not known:
            log("no stored catalog — run once without --ratings-only first")
            return SyncResult(1, False, 0, 0, False, False)
    else:
        try:
            token = fetch_token(session)
            fetched_at = repo.get_meta("films_fetched_at")
            raw_total_meta = repo.get_meta("films_raw_total")
            reuse = False
            if not force_full and known and fetched_at:
                age = (today - date.fromisoformat(fetched_at)).days
                expected_total = int(raw_total_meta) if raw_total_meta else None
                reuse = 0 <= age <= max_age_days and page_one_matches(session, token, known, expected_total)
            if reuse:
                films = known
                raw_total = None
            else:
                fetched = fetch_films(session, token, delay_s=delay_s)
                films = merge_yearless(fetched, known)
                raw_total = len(fetched)
                full_walk = True
        except (CatalogError, requests.RequestException) as exc:
            log(f"catalog fetch failed, database unchanged: {exc}")
            return SyncResult(1, False, 0, 0, False, False)

        repo.record_catalog(SOURCE, films, today)
        if full_walk and raw_total is not None:
            repo.set_meta("films_fetched_at", today.isoformat())
            repo.set_meta("films_raw_total", str(raw_total))
        try:
            repo.set_leaving(SOURCE, fetch_leaving(session, token, delay_s=delay_s))
        except Exception as exc:  # noqa: BLE001 — any failure here must not abort the run
            log(f"leaving-soon fetch failed, keeping last-known departures: {exc}")

    tmdb_client = TmdbClient(tmdb_token, session=session) if tmdb_token else None
    arbiter = TmdbArbiter(tmdb_client) if tmdb_client is not None else None

    mc_promoted = 0
    if not ratings_only and config_dir is not None:
        try:
            n = int(repo.get_meta(MC_TOP_N_KEY) or DEFAULT_TOP_N)
            promote = promote_top_n(repo, config_dir, today, n, arbiter=arbiter, log=log)
            mc_promoted = promote.promoted
            if promote.exit_code == 0 and promote.available < promote.n:
                pages = -(-promote.n // CARDS_PER_PAGE)
                log(
                    f"metacritic archive holds {promote.available} of top-{promote.n} titles — "
                    f"run: movie-brain metacritic crawl --pages {pages}"
                )
        except Exception as exc:  # noqa: BLE001 — the dial must never break the sync
            log(f"metacritic promotion failed: {exc}")

    client = OmdbClient(api_key, session=session)
    looked_up = 0
    quota_hit = False
    consecutive = 0
    lookup_queue = repo.films_needing_lookup(SOURCE, today) + repo.films_needing_lookup_discovery(SOURCE, today)
    for film_id, film in lookup_queue:
        if quota_hit or consecutive >= MAX_CONSECUTIVE_FAILURES:
            break
        try:
            rating = client.lookup(film.title, film.year)
        except QuotaExceeded:
            quota_hit = True
            continue
        except AuthError as exc:
            log(f"OMDb rejected the API key: {exc}")
            return SyncResult(
                2, full_walk, len(repo.current_films(SOURCE)), looked_up, False, False, mc_promoted=mc_promoted
            )
        except requests.RequestException as exc:
            log(f"lookup failed for {film.title!r}: {exc}")
            consecutive += 1
            continue
        repo.upsert_omdb(film_id, rating, today)
        looked_up += 1
        consecutive = 0

    failing = consecutive >= MAX_CONSECUTIVE_FAILURES
    if quota_hit:
        log("OMDb daily quota reached — partial ratings saved; next run resumes.")
    if failing:
        log("OMDb lookups failing repeatedly — partial ratings saved; next run resumes.")

    tmdb = TmdbStepResult()
    if ratings_only:
        log("ratings-only run — skipping TMDB availability step")
    elif tmdb_client is None:
        log("no TMDB token — skipping availability step")
    else:
        try:
            tmdb = tmdb_step(repo, tmdb_client, today, arbiter=arbiter, log=log)
        except Exception as exc:  # noqa: BLE001 — one source failing must never break the others
            log(f"TMDB availability step failed: {exc}")

    if notifier is not None:
        try:
            arrivals = repo.watchlist_transitions_on(today)
            if arrivals:
                listed = " · ".join(f"{title} on {service}" for title, service in arrivals[:4])
                if len(arrivals) > 4:
                    listed += f" · … and {len(arrivals) - 4} more"
                noun = "arrival" if len(arrivals) == 1 else "arrivals"
                notifier("movie-brain", f"{len(arrivals)} watchlist {noun}: {listed}")
        except Exception as exc:  # noqa: BLE001 — alerts must never affect the sync outcome
            log(f"notification failed: {exc}")

    return SyncResult(
        0,
        full_walk,
        len(repo.current_films(SOURCE)),
        looked_up,
        quota_hit,
        failing,
        tmdb.matched,
        tmdb.missed,
        tmdb.refreshed,
        tmdb.watchlist_refreshed,
        mc_promoted,
    )
