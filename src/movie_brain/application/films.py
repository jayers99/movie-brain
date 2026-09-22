"""Add one film by its IMDb id — the hand path for a film no source has brought in yet.

Nothing here resolves a title: the owner supplies the id, and the id settles WHICH work is
meant. It never settles whether the catalog already holds that work, so the same gates every
creating path runs decide that (`find_holder` for gates 1/2b, `corpus_veto` for gate 3, the
tombstone and `films.key` checks), exactly as `oldratings create --line --tt` does it. The film
is minted under TMDB's own title and year and is born keyed; a keying failure never undoes the
creation, the next sync retries. Dry run by default, and a dry run writes nothing. No claim
row: there is no ingester here whose title the resolver should later read back.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import requests

from movie_brain.application.lists import (
    KEYED_OK,
    _catalog,
    _film_label,
    _key_new_film,
    _veto_label,
    corpus_veto,
    find_holder,
)
from movie_brain.domain.matching import build_candidate_index
from movie_brain.domain.models import Film
from movie_brain.domain.thumbprint import Verdict
from movie_brain.infrastructure.database import Repository
from movie_brain.infrastructure.tmdb import AuthError, TmdbClient

_TT = re.compile(r"tt\d{7,}")


class AddError(Exception):
    """A refusal to even try — nothing was asked, nothing was touched."""


@dataclass(frozen=True)
class AddOutcome:
    kind: str  # "created" | "would-create" | "held" | "blocked" | "error"
    detail: str
    film_id: int | None = None

    @property
    def exit_code(self) -> int:
        return 1 if self.kind == "error" else 0


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


def add_by_id(
    repo: Repository,
    tt: str,
    today: date,
    *,
    tmdb: TmdbClient | None,
    apply: bool = False,
    log: Callable[[str], None] = _stderr,
) -> AddOutcome:
    if not _TT.fullmatch(tt):
        raise AddError(f"{tt!r} is not an IMDb id (tt1234567)")
    if tmdb is None:
        raise AddError("no TMDB client — gate 2b cannot run, so creation would be unguarded")

    film_rows = repo.films_for_matching()
    catalog = _catalog(repo, film_rows)
    holder, label = find_holder(repo, tmdb, Verdict("match", tt, "id supplied by hand", ()), log)
    if label == "tmdb lookup failed":
        return AddOutcome("error", "gate 2b: tmdb lookup failed — holder unknown")
    if holder is None and label.startswith("tombstoned"):
        return AddOutcome("blocked", f"tombstoned-holder  {label}")
    if holder is not None:
        return AddOutcome("held", f"{_film_label(catalog, holder)} already holds {tt}  via {label}", holder)

    try:
        tmdb_id = tmdb.find_by_imdb(tt)
        facts = tmdb.movie_facts(tmdb_id) if tmdb_id is not None else None
    except (requests.RequestException, AuthError) as exc:
        return AddOutcome("error", f"tmdb lookup failed for {tt}: {exc}")
    if tmdb_id is None or facts is None:
        return AddOutcome("blocked", f"TMDB does not know {tt} as a film")
    film = Film(facts.title, facts.year, None, "")
    wanted = f"{tt} {facts.title!r} ({facts.year or '-'})"
    titles = [t for t in (facts.title, facts.original_title) if t]
    hits = corpus_veto(build_candidate_index(film_rows), titles)
    if hits:
        return AddOutcome("blocked", f"corpus-veto  {_veto_label(hits)}  wanted {wanted}")
    if film.key in repo.tombstoned_keys():
        return AddOutcome("blocked", f"tombstoned-holder  key {film.key!r} is tombstoned")
    if not apply:
        return AddOutcome("would-create", wanted)

    film_id = repo.create_film(film)
    if film_id is None:
        clash = repo.canonical_film_id(repo.film_id_by_key(film.key) or 0)
        return AddOutcome("blocked", f"key-collision  {film.key!r} is held by {_film_label(catalog, clash)}")
    status = _key_new_film(repo, tmdb, film_id, tt, tmdb_id, today, log)
    keyed = status if status in KEYED_OK else f"{status} (the next sync retries)"
    return AddOutcome("created", f"#{film_id} {wanted}  {keyed}", film_id)
