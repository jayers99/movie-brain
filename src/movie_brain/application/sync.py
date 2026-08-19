from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import requests

from movie_brain.infrastructure.criterion import CatalogError, fetch_films, fetch_leaving, fetch_token, page_one_matches
from movie_brain.infrastructure.database import Repository
from movie_brain.infrastructure.omdb import AuthError, OmdbClient, QuotaExceeded

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
            reuse = False
            if not force_full and known and fetched_at:
                age = (today - date.fromisoformat(fetched_at)).days
                reuse = 0 <= age <= max_age_days and page_one_matches(session, token, known)
            if reuse:
                films = known
            else:
                films = fetch_films(session, token, delay_s=delay_s)
                full_walk = True
        except (CatalogError, requests.RequestException) as exc:
            log(f"catalog fetch failed, database unchanged: {exc}")
            return SyncResult(1, False, 0, 0, False, False)

        repo.record_catalog(SOURCE, films, today)
        if full_walk:
            repo.set_meta("films_fetched_at", today.isoformat())
        try:
            repo.set_leaving(SOURCE, fetch_leaving(session, token, delay_s=delay_s))
        except Exception as exc:  # noqa: BLE001 — any failure here must not abort the run
            log(f"leaving-soon fetch failed, keeping last-known departures: {exc}")

    client = OmdbClient(api_key, session=session)
    looked_up = 0
    quota_hit = False
    consecutive = 0
    for film_id, film in repo.films_needing_lookup(SOURCE, today):
        if quota_hit or consecutive >= MAX_CONSECUTIVE_FAILURES:
            break
        try:
            rating = client.lookup(film.title, film.year)
        except QuotaExceeded:
            quota_hit = True
            continue
        except AuthError as exc:
            log(f"OMDb rejected the API key: {exc}")
            return SyncResult(2, full_walk, len(repo.current_films(SOURCE)), looked_up, False, False)
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
    return SyncResult(0, full_walk, len(repo.current_films(SOURCE)), looked_up, quota_hit, failing)
