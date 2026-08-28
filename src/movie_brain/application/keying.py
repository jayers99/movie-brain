"""The identity write path (thumbprint T5): one function keys one film, everywhere.

`key_film` is the verbatim apply loop T4's `repair nomatch` proved on 99 live films, lifted
out so the sync keying step, the repair verbs and `review resolve` cannot drift apart. Holder
checks run BEFORE any write, so a film is either fully keyed or untouched — except a
post-`record_tmdb_match` failure, the one case that logs `[partial]` and raises.
"""

from __future__ import annotations

import sqlite3
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import requests

from movie_brain.application.availability import TMDB_AUTHORITY, record_tmdb_match
from movie_brain.infrastructure.database import Repository
from movie_brain.infrastructure.tmdb import AuthError, TmdbClient

# record_tmdb_match results that leave the film fully keyed; anything else is a [partial].
KEYED_OK = ("matched", "adopted", "collision")


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
    writes the imdb id alone, instead of repeating the lookup."""
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
