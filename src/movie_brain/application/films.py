"""Add one film by its IMDb id — the hand path for a film no source has brought in yet — and
the creating gates every caller shares.

Nothing in `add_by_id` resolves a title: the owner supplies the id, and the id settles WHICH
work is meant. It never settles whether the catalog already holds that work, so `gate_ladder`
decides that (`find_holder` for gates 1/2b, `corpus_veto` for gate 3, the tombstone and
`films.key` checks), exactly as `oldratings create --line --tt` does it. The film is minted
under TMDB's own title and year and is born keyed; a keying failure never undoes the creation,
the next sync retries. Dry run by default, and a dry run writes nothing. No claim row: there is
no ingester here whose title the resolver should later read back.

`gate_ladder` has three callers (spec 2026-10-01 D5/D9): `films add`, the Criterion walk
(`criterion_walk.py`, where a resolver verdict supplies the id) and `review resolve --tt` on a
criterion row (`criterion_review.py`, where the owner does). On a human path gate 3 is passed
`veto=False`: its hits are reported, not a refusal — a human choosing is what gate 3 exists to
summon (Plan B ledger L1).
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable, Sequence
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
from movie_brain.domain.matching import CandidateIndex, build_candidate_index
from movie_brain.domain.models import Film
from movie_brain.domain.thumbprint import Verdict
from movie_brain.infrastructure.database import Repository
from movie_brain.infrastructure.tmdb import AuthError, TmdbClient

_TT = re.compile(r"tt\d{7,}")

# Review reasons a `blocked` ladder names (the Criterion walk queues them verbatim).
CORPUS_VETO = "corpus-veto"
TOMBSTONED_HOLDER = "tombstoned-holder"
KEY_COLLISION = "key-collision"
NOT_A_FILM = "not-a-film"


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


@dataclass(frozen=True)
class Ladder:
    """What the creating gates say about one work.

    `held` — a film already holds it (`holder`); `clear` — every gate passed: mint under
    `title`/`year`, born keyed to `tmdb_id`; `blocked` — a durable refusal, `reason` is the
    review reason; `weather` — a TMDB call failed, so the holder is unknown, not disproved:
    ask again later, never a review row. `vetoed` carries gate 3's hits when `veto=False` let
    them through."""

    kind: str
    detail: str
    reason: str = ""
    holder: int | None = None
    tmdb_id: int | None = None
    title: str = ""
    year: int | None = None
    vetoed: str = ""


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


def gate_ladder(
    repo: Repository,
    tmdb: TmdbClient,
    verdict: Verdict,
    *,
    index: CandidateIndex,
    catalog: dict[int, tuple[str, int | None, str | None]],
    extra_forms: Sequence[str] = (),
    veto: bool = True,
    log: Callable[[str], None] = _stderr,
) -> Ladder:
    """Gates 1/2/2b, then TMDB's own title and year, gate 3, the tombstoned key and the
    `films.key` collision — in that order, writing nothing. `extra_forms` widens gate 3 with the
    caller's own titles for the work (Criterion's printed and original titles)."""
    tt = verdict.tt
    if verdict.kind != "match" or tt is None:
        raise ValueError("the gate ladder starts from a matched IMDb id")
    holder, label = find_holder(repo, tmdb, verdict, log)
    if label == "tmdb lookup failed":
        return Ladder("weather", "gate 2b: tmdb lookup failed — holder unknown")
    if holder is None and label.startswith("tombstoned"):
        return Ladder("blocked", f"tombstoned-holder  {label}", TOMBSTONED_HOLDER)
    if holder is not None:
        return Ladder("held", f"{_film_label(catalog, holder)} already holds {tt}  via {label}", holder=holder)

    try:
        tmdb_id = tmdb.find_by_imdb(tt)
        facts = tmdb.movie_facts(tmdb_id) if tmdb_id is not None else None
    except (requests.RequestException, AuthError) as exc:
        return Ladder("weather", f"tmdb lookup failed for {tt}: {exc}")
    if tmdb_id is None or facts is None:
        return Ladder("blocked", f"TMDB does not know {tt} as a film", NOT_A_FILM)
    film = Film(facts.title, facts.year, None, "")
    wanted = f"{tt} {facts.title!r} ({facts.year or '-'})"
    forms = list(dict.fromkeys(t for t in (facts.title, facts.original_title, *extra_forms) if t))
    hits = corpus_veto(index, forms)
    vetoed = ""
    if hits:
        if veto:
            return Ladder("blocked", f"corpus-veto  {_veto_label(hits)}  wanted {wanted}", CORPUS_VETO)
        vetoed = _veto_label(hits)
    if film.key in repo.tombstoned_keys():
        return Ladder("blocked", f"tombstoned-holder  key {film.key!r} is tombstoned", TOMBSTONED_HOLDER)
    clash = repo.film_id_by_key(film.key)
    if clash is not None:
        clash = repo.canonical_film_id(clash)
        return Ladder(
            "blocked", f"key-collision  {film.key!r} is held by {_film_label(catalog, clash)}", KEY_COLLISION,
            holder=clash,
        )
    return Ladder("clear", wanted, tmdb_id=tmdb_id, title=facts.title, year=facts.year, vetoed=vetoed)


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
    lad = gate_ladder(
        repo, tmdb, Verdict("match", tt, "id supplied by hand", ()),
        index=build_candidate_index(film_rows), catalog=_catalog(repo, film_rows), log=log,
    )
    if lad.kind == "weather":
        return AddOutcome("error", lad.detail)
    if lad.kind == "held":
        return AddOutcome("held", lad.detail, lad.holder)
    if lad.kind == "blocked":
        return AddOutcome("blocked", lad.detail)
    if not apply:
        return AddOutcome("would-create", lad.detail)

    film = Film(lad.title, lad.year, None, "")
    film_id = repo.create_film(film)
    if film_id is None:  # the key appeared between the gate and the write
        return AddOutcome("blocked", f"key-collision  {film.key!r} appeared during the add")
    status = _key_new_film(repo, tmdb, film_id, tt, lad.tmdb_id, today, log)
    keyed = status if status in KEYED_OK else f"{status} (the next sync retries)"
    return AddOutcome("created", f"#{film_id} {lad.detail}  {keyed}", film_id)
