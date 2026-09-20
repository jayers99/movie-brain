"""Look up each film's trailer ahead of time — what the drawer's "▶ Trailer" link plays
(brief docs/superpowers/briefs/2026-09-20-trailer-link/brief.md).

Nothing is fetched when the drawer opens: the link exists only for a film this verb found a trailer
for. Per batch of films, ONE iTunes lookup answers every store id's preview, then one paced TMDB
call per film (a few films at a time) answers its typed videos (`domain/trailers.py` chooses among them); a film whose
English list holds no trailer is asked once more for its own language. Dry-run by default: the calls
are made and logged, nothing is written. `--apply` writes each film through `write_trailers`, which
stamps it even when nothing was found, so an interrupted run resumes where it stopped. A film TMDB
cannot serve is left unstamped for the next run; Apple being down stops the run before its batch is
stamped, because a film stamped without its preview would never be asked again. Never called from
`sync`.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

import requests

from movie_brain.application.keying import MAX_CONSECUTIVE_FAILURES
from movie_brain.domain.trailers import APPLE, APPLE_NAME, Trailer, pick_youtube
from movie_brain.infrastructure.database import Repository
from movie_brain.infrastructure.itunes import BATCH
from movie_brain.infrastructure.tmdb import AuthError

DELAY_S = 0.1  # per worker, before each call
WORKERS = 4    # TMDB answers a videos call in about half a second, and a foreign film takes two: one
#                at a time the catalogue's ~5,000 films took over an hour (measured 2026-09-20). Four
#                workers stay near 8 calls a second, far under TMDB's ceiling of about 50.
ENGLISH = "en,null"


class VideoSource(Protocol):
    def movie_videos(self, tmdb_id: int, languages: str = ...) -> tuple[str | None, list[dict[str, Any]]]: ...


class PreviewSource(Protocol):
    def previews(self, itunes_ids: Sequence[str]) -> Mapping[str, str]: ...


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


@dataclass(frozen=True)
class TrailerReport:
    scanned: int = 0
    with_youtube: int = 0
    apple_only: int = 0
    nothing: int = 0
    failed: int = 0
    aborted: bool = False


def _youtube(tmdb: VideoSource, tmdb_id: int, pause: Callable[[], None]) -> list[Trailer]:
    """English first. A foreign film whose English list holds no TRAILER (a teaser does not count) is
    asked once more for its own language, and the pick is made over both answers. A TMDB id that no
    longer exists is "no videos", not a failure: the film is still stamped, and keeps Apple's preview."""
    pause()
    try:
        language, videos = tmdb.movie_videos(tmdb_id, ENGLISH)
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return []
        raise
    english = pick_youtube(videos, language)
    has_trailer = bool(pick_youtube([v for v in videos if v.get("type") == "Trailer"], language))
    if has_trailer or not language or language == "en":
        return english
    pause()
    _, own = tmdb.movie_videos(tmdb_id, language)
    return pick_youtube([*videos, *own], language)


def _ask(tmdb: VideoSource, tmdb_id: int | None, pause: Callable[[], None]) -> list[Trailer] | Exception:
    """One film's YouTube picks, or the failure itself — it runs on a worker, the counting does not."""
    if tmdb_id is None:
        return []
    try:
        return _youtube(tmdb, tmdb_id, pause)
    except (requests.RequestException, AuthError) as exc:
        return exc


def enrich_trailers(
    repo: Repository,
    tmdb: VideoSource,
    itunes: PreviewSource,
    today: date,
    *,
    apply: bool = False,
    limit: int | None = None,
    refresh: bool = False,
    delay_s: float = DELAY_S,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = _stderr,
) -> TrailerReport:
    scanned = with_youtube = apple_only = nothing = failed = consecutive = 0
    requested = False

    def pause() -> None:
        nonlocal requested
        if requested:
            sleep(delay_s)
        requested = True

    def report(aborted: bool = False) -> TrailerReport:
        return TrailerReport(scanned, with_youtube, apple_only, nothing, failed, aborted)

    targets = repo.films_needing_trailers(limit, refresh=refresh)
    for start in range(0, len(targets), BATCH):
        batch = targets[start : start + BATCH]
        store_ids = [i for t in batch for i in t.itunes_ids]
        try:
            previews = itunes.previews(store_ids) if store_ids else {}
        except requests.RequestException as exc:
            log(f"Apple's lookup failed ({type(exc).__name__}) — stopping; the next run resumes.")
            return report(aborted=True)
        # TMDB is asked a few films at a time; everything else — counting, the abort, the writes —
        # happens here, in worklist order, one slice after another.
        for at in range(0, len(batch), WORKERS):
            if consecutive >= MAX_CONSECUTIVE_FAILURES:
                log("TMDB video lookups failing repeatedly — stopping; the next run resumes.")
                return report(aborted=True)
            chunk = batch[at : at + WORKERS]
            with ThreadPoolExecutor(max_workers=WORKERS) as pool:
                answers = list(pool.map(lambda t: _ask(tmdb, t.tmdb_id, pause), chunk))
            for target, answer in zip(chunk, answers, strict=True):
                scanned += 1
                if isinstance(answer, Exception):
                    log(f"  #{target.film_id} {target.title!r}: TMDB videos failed: {answer}")
                    consecutive += 1
                    failed += 1
                    continue
                consecutive = 0
                trailers = answer
                preview = next((previews[i] for i in target.itunes_ids if i in previews), None)
                if trailers:
                    with_youtube += 1
                elif preview:
                    apple_only += 1
                else:
                    nothing += 1
                log(
                    f"  #{target.film_id} {target.title!r}: "
                    + (trailers[0].name if trailers else "no YouTube trailer")
                    + (" · Apple preview" if preview else "")
                )
                if preview:
                    trailers.append(Trailer(APPLE, preview, APPLE_NAME))
                if apply:
                    repo.write_trailers(target.film_id, target.tmdb_id, target.itunes_id, trailers, today)
    return report()
