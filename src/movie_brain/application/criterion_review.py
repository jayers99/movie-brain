"""`review resolve` on a `criterion` row (spec 2026-10-01 D9).

A criterion row names a mediaid the walk could not place (`value`) and no film (`film_id`
NULL) — except the bridge's `id-conflict` rows, which name the claimant film and accept
`--dismiss` only. Everything is re-derived at resolution time: the holder is asked again and
the gates run again. `--film X` binds the mediaid and Criterion's claim to X; `--tt` runs the
`films add` ladder from the owner's id (a holder → bound there; clear → created under TMDB's
title and year with Criterion's director, born holding the mediaid, keyed); `--create` mints
under Criterion's own title, year and director, read from the row's detail (never a refetch: a
`no-record` id would 404 again). The next walk lists the film — its mediaid is now known.

On these HUMAN paths gate 3 warns and never refuses (Plan B ledger L1): gate 3 is year-blind, so
a remake would never get past it, and a human choosing is what gate 3 exists to summon. Gates
1/2/2b, the tombstone and the `films.key` collision still refuse, naming the film.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import date
from typing import Any

from movie_brain.application.criterion_walk import AUTHORITY, parse_criterion_detail
from movie_brain.application.films import gate_ladder
from movie_brain.application.lists import _catalog, _key_new_film, _veto_label, corpus_veto, find_holder
from movie_brain.domain.matching import build_candidate_index
from movie_brain.domain.models import Film
from movie_brain.domain.thumbprint import Verdict
from movie_brain.infrastructure.database import Repository
from movie_brain.infrastructure.tmdb import TmdbClient

ID_CONFLICT = "id-conflict"
_GATE3 = "gate 3 (a human is choosing, so not a refusal): resembles "


def _title_year(crit: dict[str, Any], mediaid: str) -> tuple[str, int | None]:
    year = crit.get("year")
    return str(crit.get("title") or mediaid), int(year) if year is not None else None


def _director(crit: dict[str, Any]) -> str | None:
    return ", ".join(str(d) for d in crit.get("director") or []) or None


def _forms(crit: dict[str, Any]) -> list[str]:
    return [str(t) for t in dict.fromkeys((crit.get("title"), crit.get("title_original"))) if t]


def _bind(repo: Repository, film_id: int, mediaid: str, crit: dict[str, Any], today: date) -> None:
    title, year = _title_year(crit, mediaid)
    try:
        repo.bind_criterion_mediaid(film_id, mediaid, title, year, today)
    except sqlite3.IntegrityError as exc:
        holder = repo.film_id_for_external(AUTHORITY, mediaid)
        raise ValueError(f"{mediaid} is already held by film {holder}") from exc


def _from_tt(
    repo: Repository, mediaid: str, crit: dict[str, Any], tt: str, client: TmdbClient | None, today: date,
    warn: Callable[[str], None],
) -> str:
    if client is None:
        raise ValueError("--tt on a criterion row needs a TMDB token (gate 2b)")
    rows = repo.films_for_matching()
    lad = gate_ladder(
        repo, client, Verdict("match", tt, "id supplied by hand", ()),
        index=build_candidate_index(rows), catalog=_catalog(repo, rows), extra_forms=_forms(crit), veto=False,
        log=warn,
    )
    if lad.kind == "weather":
        raise ValueError(f"{lad.detail} — nothing written, try again")
    if lad.kind == "blocked":
        raise ValueError(lad.detail)
    if lad.vetoed:
        warn(_GATE3 + lad.vetoed)
    if lad.kind == "held":
        if lad.holder is None:
            raise ValueError(lad.detail)
        _bind(repo, lad.holder, mediaid, crit, today)
        return f"{mediaid} → film {lad.holder} (holds {tt})"
    title, year = _title_year(crit, mediaid)
    film = Film(lad.title, lad.year, _director(crit), "")
    new_id = repo.create_criterion_film(film, mediaid, title, year, today)
    if new_id is None:
        raise ValueError(f"key {film.key!r} appeared during the resolution — nothing written")
    status = _key_new_film(repo, client, new_id, tt, lad.tmdb_id, today, warn)
    return f"created film {new_id} {lad.title!r} ({lad.year or '-'}) from {mediaid}, {status}"


def _create(
    repo: Repository, mediaid: str, crit: dict[str, Any], client: TmdbClient | None, today: date,
    warn: Callable[[str], None],
) -> str:
    if not crit.get("title"):
        raise ValueError("this row holds no Criterion title to mint from — use --film or --tt")
    title, year = _title_year(crit, mediaid)
    film = Film(title, year, _director(crit), "")
    found = crit.get("tt")
    if found:
        if client is None:
            raise ValueError("--create on a row the resolver keyed needs a TMDB token (gate 2b)")
        holder, label = find_holder(repo, client, Verdict("match", str(found), "resolver", ()), warn)
        if label == "tmdb lookup failed":
            raise ValueError("gate 2b: tmdb lookup failed — nothing written, try again")
        if holder is None and label.startswith("tombstoned"):
            raise ValueError(f"tombstoned-holder  {label}")
        if holder is not None:
            raise ValueError(f"film {holder} already holds {found} — use --film {holder}")
    if film.key in repo.tombstoned_keys():
        raise ValueError(f"tombstoned-holder  key {film.key!r} is tombstoned")
    clash = repo.film_id_by_key(film.key)
    if clash is not None:
        clash = repo.canonical_film_id(clash)
        raise ValueError(f"film {clash} already holds the key {film.key!r} — use --film {clash}")
    hits = corpus_veto(build_candidate_index(repo.films_for_matching()), _forms(crit))
    if hits:
        warn(_GATE3 + _veto_label(hits))
    new_id = repo.create_criterion_film(film, mediaid, title, year, today)
    if new_id is None:
        raise ValueError(f"key {film.key!r} appeared during the resolution — nothing written")
    if found:
        _key_new_film(repo, client, new_id, str(found), None, today, warn)
    return f"created film {new_id} {title!r} ({year or '-'}) from {mediaid}"


def resolve_criterion_row(
    repo: Repository,
    row: dict[str, object],
    *,
    today: date,
    film_id: int | None = None,
    create: bool = False,
    tt: str | None = None,
    client: TmdbClient | None = None,
    warn: Callable[[str], None],
) -> str:
    """One resolution of one open criterion row; raises ValueError on every refusal."""
    mediaid = str(row["value"])
    if str(row["reason"]) == ID_CONFLICT:
        holder = repo.film_id_for_external(AUTHORITY, mediaid)
        raise ValueError(f"{mediaid} is held by film {holder} — an id-conflict row accepts --dismiss only")
    crit = parse_criterion_detail(str(row["detail"]) if row["detail"] else None) or {}
    if film_id is not None:
        _bind(repo, film_id, mediaid, crit, today)
        return f"{mediaid} → film {film_id}"
    if tt is not None:
        return _from_tt(repo, mediaid, crit, tt, client, today, warn)
    if create:
        return _create(repo, mediaid, crit, client, today, warn)
    raise ValueError("criterion rows accept --film, --create, --tt or --dismiss")
