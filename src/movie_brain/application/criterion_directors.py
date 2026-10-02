"""Criterion's directors (spec 2026-10-01 D8, story 9): a film that holds a Criterion mediaid and
shows the owner NO director — no `films.director` and no OMDb director, the two the dashboard's
COALESCE reads — takes the director Criterion's own JW Player record names. Nothing anyone can
already see ever changes: the worklist excludes it and the write is guarded again in the UPDATE.

One JW call per film per run, no stamp: the worklist is a handful (3 when measured on 2026-10-02),
and a film whose record names nobody is simply asked again next run. A JW 404 or failure for one
film never stops the others. It runs last in the catch-up chain (`catch_up.py`) under its own
tripwire, and by hand as `movie-brain enrich criterion-directors`."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from movie_brain.infrastructure.criterion_site import CriterionError, JwMedia
from movie_brain.infrastructure.database import Repository


class MediaSource(Protocol):
    """What the step needs of `HttpCriterionSite`: one film's JW record, None on JW's 404."""

    def media(self, mediaid: str) -> JwMedia | None: ...


@dataclass(frozen=True)
class DirectorsReport:
    scanned: int = 0
    filled: int = 0  # on a dry run: would be filled
    no_director: int = 0  # JW answered and names nobody: asked again next run
    gone: int = 0  # JW answered 404
    failed: int = 0  # JW did not answer usably: asked again next run


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


def fill_criterion_directors(
    repo: Repository, site: MediaSource, *, apply: bool = False, log: Callable[[str], None] = _stderr
) -> DirectorsReport:
    scanned = filled = no_director = gone = failed = 0
    for t in repo.films_needing_criterion_director():
        scanned += 1
        try:
            media = site.media(t.mediaid)
        except CriterionError as exc:
            log(f"  #{t.film_id} {t.title!r} ({t.mediaid}): JW lookup failed, asked again next run: {exc}")
            failed += 1
            continue
        if media is None:
            log(f"  #{t.film_id} {t.title!r} ({t.mediaid}): JW has no record of it")
            gone += 1
            continue
        # The join the walk uses for a film it creates (`criterion_walk._director`): never "".
        director = ", ".join(media.directors)
        if not director:
            log(f"  #{t.film_id} {t.title!r} ({t.mediaid}): JW names no director, asked again next run")
            no_director += 1
            continue
        if apply and not repo.fill_criterion_director(t.film_id, director):
            log(f"  #{t.film_id} {t.title!r}: gained a director since the worklist was read — left as it is")
            continue
        log(f"  #{t.film_id} {t.title!r}: {director}")
        filled += 1
    return DirectorsReport(scanned, filled, no_director, gone, failed)
