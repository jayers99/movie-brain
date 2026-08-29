"""The identity write path (thumbprint T5): one function keys one film, everywhere.

`key_film` is the verbatim apply loop T4's `repair nomatch` proved on 99 live films, lifted
out so the sync keying step, the repair verbs and `review resolve` cannot drift apart. Holder
checks run BEFORE any write, so a film is either fully keyed or untouched — except a
post-`record_tmdb_match` failure, the one case that logs `[partial]` and raises.

`key_films` is the sync keying step itself: it replaced the popularity-ranked title search
(`pick_tmdb_match`) that used to live in `tmdb_step`.
"""

from __future__ import annotations

import sqlite3
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import requests

from movie_brain.application.availability import (
    NO_MATCH_REVIEWED,
    TMDB_AUTHORITY,
    queue_review_once,
    rebuild_no_match_queue,
    record_tmdb_match,
)
from movie_brain.application.thumbprint import film_query, review_detail
from movie_brain.domain.models import ReviewEntry
from movie_brain.domain.thumbprint import resolve
from movie_brain.infrastructure.database import Repository
from movie_brain.infrastructure.omdb import QuotaExceeded
from movie_brain.infrastructure.thumbprint_fetch import CacheMiss, CandidateFetcher
from movie_brain.infrastructure.tmdb import AuthError, TmdbClient

# record_tmdb_match results that leave the film fully keyed; anything else is a [partial].
KEYED_OK = ("matched", "adopted", "collision")
MAX_CONSECUTIVE_FAILURES = 5


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


@dataclass(frozen=True)
class KeyResult:
    status: str  # "keyed" | "unlinked" | "held" | "error"
    tmdb_id: int | None = None
    detail: str = ""


def key_film(
    repo: Repository,
    tmdb: TmdbClient | None,
    film_id: int,
    tt: str,
    today: date,
    log: Callable[[str], None] = _stderr,
    *,
    tmdb_id: int | None = None,
    resolve_tmdb_id: bool = True,
) -> KeyResult:
    """Key one film to an IMDb id (plus its TMDB id when one exists). Nothing is written
    unless every holder check passes, so `held` and `error` leave the film untouched.

    `resolve_tmdb_id`: False when the caller already attempted the `find_by_imdb` lookup
    itself — `key_film` then trusts `tmdb_id=None` to mean TMDB has no movie for this tt, and
    writes the imdb id alone, instead of repeating the lookup. WARNING: `repair imdb`
    (`backfill_imdb.py`) passes this exact same pair, `tmdb_id=None, resolve_tmdb_id=False`,
    to mean the opposite thing — "the film already holds a working TMDB link, leave it
    alone" — relying on the fact that `tid` then stays `None` throughout this call, so the
    `record_tmdb_match`/`upsert_tmdb` branch below never runs and the film's existing TMDB
    row is untouched. Do not "fix" that caller to match this docstring's meaning."""
    holder = repo.film_id_for_external("imdb", tt)
    if holder is not None and holder != film_id:
        return KeyResult("held", tmdb_id, f"{tt} already held by #{holder}")
    tid = tmdb_id
    winner_year: int | None = None
    try:
        if tid is None and tmdb is not None and resolve_tmdb_id:
            tid = tmdb.find_by_imdb(tt)
        if tid is not None:
            th = repo.film_id_for_external(TMDB_AUTHORITY, str(tid))
            if th is not None and th != film_id:
                return KeyResult("held", tid, f"tmdb {tid} already held by #{th}")
            winner_year = tmdb.movie_year(tid) if tmdb is not None else None
    except (requests.RequestException, AuthError) as exc:
        return KeyResult("error", tid, str(exc))
    try:
        repo.set_external_id(film_id, "imdb", tt, today)
    except sqlite3.IntegrityError:
        return KeyResult("held", tid, f"{tt} already held")
    detail = "no TMDB record"
    if tid is not None:
        target = repo.tmdb_target(film_id)
        if target is None:
            raise RuntimeError(f"[partial] #{film_id} vanished after its imdb id was written")
        res = record_tmdb_match(repo, target, tid, winner_year, today, log)
        if res not in KEYED_OK:
            partial = f"[partial] #{film_id} PARTIAL: imdb {tt} written but tmdb {tid} {res}"
            log(partial)
            raise RuntimeError(partial)
        detail = res
    if repo.omdb_imdb_id(film_id) != tt:
        repo.mark_omdb_refresh(film_id)
        log(f"  omdb refresh queued (by id {tt})")
    return KeyResult("keyed" if tid is not None else "unlinked", tid, detail)


@dataclass(frozen=True)
class KeyStepResult:
    keyed: int = 0
    reviewed: int = 0
    held: int = 0
    failed: int = 0
    aborted: bool = False


def key_films(
    repo: Repository,
    fetcher: CandidateFetcher | None,
    tmdb: TmdbClient | None,
    today: date,
    log: Callable[[str], None] = _stderr,
) -> KeyStepResult:
    """Key every film that has never been looked up (thumbprint T5, memo step 5).

    A `match` is written through `key_film`; anything else becomes ONE durable
    `no-match-reviewed` row carrying the resolver's A/B/C candidates, so the next sync
    never re-resolves a film a human is already looking at.
    """
    if fetcher is None:
        log("no resolver fetcher (needs both a TMDB token and an OMDb key) — skipping keying")
        return KeyStepResult()
    keyed = reviewed = held = failed = 0
    consecutive = 0
    aborted = False
    for target in repo.films_needing_tmdb_match():
        if consecutive >= MAX_CONSECUTIVE_FAILURES:
            log("resolver lookups failing repeatedly — stopping keying; next run resumes.")
            aborted = True
            break
        q = film_query(repo, target.film_id, target.title, target.year, target.director)
        try:
            verdict = resolve(q, fetcher.fetch(q))
        except (CacheMiss, requests.RequestException, AuthError, QuotaExceeded) as exc:
            log(f"resolver lookup failed for {target.title!r}: {exc}")
            consecutive += 1
            failed += 1
            continue
        consecutive = 0
        if verdict.kind != "match" or verdict.tt is None:
            repo.upsert_tmdb(target.film_id, found=False, looked_up=today)
            queue_review_once(
                repo,
                TMDB_AUTHORITY,
                ReviewEntry(NO_MATCH_REVIEWED, film_id=target.film_id, detail=review_detail(verdict, q)),
                today,
            )
            reviewed += 1
            continue
        winner = next((s.candidate for s in verdict.ranked if s.candidate.tt == verdict.tt), None)
        result = key_film(
            repo,
            tmdb,
            target.film_id,
            verdict.tt,
            today,
            log,
            tmdb_id=winner.tmdb_id if winner is not None else None,
        )
        if result.status in ("keyed", "unlinked"):
            keyed += 1
            continue
        if result.status == "error":
            log(f"TMDB error keying {target.title!r}: {result.detail}")
            consecutive += 1
            failed += 1
            continue
        # held: the id belongs to another film — a twin. Durable row, never a silent overwrite.
        repo.upsert_tmdb(target.film_id, found=False, looked_up=today)
        queue_review_once(
            repo,
            TMDB_AUTHORITY,
            ReviewEntry(
                "id-conflict",
                film_id=target.film_id,
                value=str(result.tmdb_id) if result.tmdb_id is not None else verdict.tt,
                detail=f"{target.title!r} ({target.year}) — {result.detail}, likely twins",
            ),
            today,
        )
        held += 1
    rebuild_no_match_queue(repo, today)
    return KeyStepResult(keyed, reviewed, held, failed, aborted)
