from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable
from datetime import date
from pathlib import Path

import requests

from movie_brain.application.availability import TMDB_AUTHORITY, record_tmdb_match
from movie_brain.application.eval_log import EvalEntry, ratify
from movie_brain.application.keying import key_film
from movie_brain.application.thumbprint import parse_review_detail
from movie_brain.domain.matching import parse_apple_title
from movie_brain.domain.models import Film, ReviewEntry
from movie_brain.infrastructure.database import Repository
from movie_brain.infrastructure.tmdb import AuthError, TmdbClient


def suppress_resolved(repo: Repository, authority: str, entries: list[ReviewEntry]) -> list[ReviewEntry]:
    """Drop entries a human already resolved (same reason+film+value) — dismiss means dismissed.

    Defined first in this module (ahead of the metacritic/owned imports resolve_review needs)
    so `from movie_brain.application.review import suppress_resolved` works from
    metacritic.py/owned.py even though those two modules are imported (locally, inside
    resolve_review below) by this one — the circular import is broken by keeping this
    module's own top-level imports one-directional.
    """
    done = repo.resolved_review_keys(authority)
    return [e for e in entries if (e.reason, e.film_id, e.value) not in done]


SLUG_REASONS = {"year-gap", "ambiguous-title"}  # metacritic rows keyed by slug, no film_id
MERGE_REASONS = {"id-conflict", "year-collision"}  # tmdb rows whose "match to X" means "X is my twin"
_IMDB_ID = re.compile(r"^tt\d+$")


def resolve_review(
    repo: Repository,
    review_id: int,
    *,
    today: date,
    film_id: int | None = None,
    tmdb_id: int | None = None,
    create: bool = False,
    dismiss: bool = False,
    client: TmdbClient | None = None,
    note: str | None = None,
    pick: str | None = None,
    tt: str | None = None,
    none: bool = False,
    series: bool = False,
    eval_csv: Path | None = None,
    warn: Callable[[str], None] = lambda _m: None,
) -> str:
    """Apply exactly one resolution to one open match_review row; returns a one-line outcome.

    Per authority: tmdb no-match → --tmdb-id claims the id through the sync's own write path
    (year adoption included when a client is given) · tmdb id-conflict/year-collision →
    --film merges this film INTO the named twin · metacritic slug rows → --film links the
    slug, --create promotes the staged title · apple-tv rows → --film marks owned, --create
    creates + marks owned · list rows (no film_id — nothing to key) → --film links the entry,
    --create mints an unkeyed film for the next sync to key · every row accepts --dismiss. The
    row is marked resolved, which also suppresses the same anomaly from being re-queued by
    later runs.

    The three thumbprint verdicts on a tmdb row — --pick A/B/C (a candidate off the resolver's
    own review detail), --tt (any IMDb id, whether or not it was ranked), --none (verified
    unkeyed) — key the film by IMDb id (plus the TMDB id when one is known) and ratify the
    decision into the eval CSV, so a human verdict becomes permanent resolver ground truth.
    `eval_csv=None` skips that append entirely (library callers that don't keep an eval log);
    the CLI always passes a path.

    A --tt whose id TMDB knows only as TV (or one forced with --series) is a series work: it is
    keyed by its IMDb id ALONE and marked `kind = series`, which takes it out of every TMDB
    keying worklist. It can hold no TMDB id — movie and TV ids share one integer namespace and
    the stored id drives the movie-only providers endpoint (memo Q2). TMDB's `/find` sometimes
    answers a tt with BOTH a collection-style movie stub (whose `/movie/{id}` itself 404s) AND
    a tv hit (Dekalog: movie id 37452, tv id 42699) — a human's explicit --series wins whenever
    TMDB knows the tt as TV at all, movie stub or not; automatic detection stays conservative
    (tv-only) so a film that legitimately has both a theatrical cut and a TV cut isn't silently
    mis-kinded. --series is refused only when TMDB knows the tt purely as a movie.

    A `list` row (design §1 A1) carries no `film_id` at all — an entry that matched nothing
    has no film to key, so the thumbprint verdicts (`--pick`/`--tt`/`--none`) are refused here
    exactly like every other film-less row. `--film` links the entry (refusing when that film
    already sits at another rank on the same list); `--create` mints an unkeyed film from the
    entry's own `title_listed`/`director_listed` — the next sync's keying step keys it, the
    same deferred-keying precedent as an apple-tv `--create` film — and a `films.key` collision
    canonicalizes to the existing film and links to it instead, exactly as the apple-tv branch
    does; `--dismiss` leaves the entry unlinked forever. `--film` and `--create` BOTH refuse
    when the entry already carries a link to some other film: one entry can hold two open rows
    (`queue_list_review_once` dedups on reason + value), and resolving the second would move
    the link while `add_claim`'s `INSERT OR IGNORE` left the claim on the first film.

    Imports metacritic/owned/lists locally (not at module top) — metacritic.py and owned.py
    import `suppress_resolved` from this one at their own top level, so a module-level import
    here would be circular depending on which module a caller happens to import first; lists.py
    imports nothing from this module today, but the same local convention is followed anyway
    so a future import there can never introduce that cycle by accident.
    """
    from movie_brain.application.lists import AUTHORITY as LIST_AUTHORITY
    from movie_brain.application.metacritic import AUTHORITY as MC_AUTHORITY
    from movie_brain.application.metacritic import create_from_staged
    from movie_brain.application.owned import AUTHORITY as APPLE_AUTHORITY

    chosen = [
        x
        for x in (film_id is not None, tmdb_id is not None, create, dismiss, pick is not None, tt is not None, none)
        if x
    ]
    if len(chosen) != 1:
        raise ValueError("choose exactly one of --film, --tmdb-id, --create, --dismiss, --pick, --tt, --none")
    if series and tt is None:
        raise ValueError("--series applies only to --tt")
    if film_id is not None:
        # --film targets an id chosen by a human, possibly stale by the time this runs
        # (merged away, tombstoned) — canonicalize to the ultimate survivor and refuse a
        # tombstoned or nonexistent id outright, never bind a slug/ownership to a dead film.
        film_id = repo.canonical_film_id(film_id)
        disposition = repo.disposition_of(film_id)
        if disposition is not None and disposition[0] == "tombstoned":
            raise ValueError(f"film {film_id} is tombstoned")
        if repo.get_view(film_id, today) is None:
            raise ValueError(f"film {film_id} not found")
    row = repo.review(review_id)
    if row is None or row["resolved"]:
        raise ValueError(f"review {review_id} is not open")
    authority, reason = str(row["authority"]), str(row["reason"])
    raw_film_id = row["film_id"]
    rid = int(raw_film_id) if isinstance(raw_film_id, int) else None
    value = None if row["value"] is None else str(row["value"])
    eval_entry: EvalEntry | None = None

    if dismiss:
        outcome = "dismissed"
    elif pick is not None or tt is not None or none:
        if authority != TMDB_AUTHORITY or rid is None:
            raise ValueError("--pick/--tt/--none apply to tmdb rows for a film")
        parsed = parse_review_detail(str(row["detail"]) if row["detail"] else None)
        chosen_tt: str
        chosen_tmdb: int | None = None
        is_series = False
        if pick is not None:
            if parsed is None:
                raise ValueError(f"review {review_id} has no A/B/C candidates — use --tt or --none")
            cand = next((c for c in parsed.candidates if c["letter"] == pick.upper()), None)
            if cand is None:
                raise ValueError(f"no candidate {pick!r} on review {review_id}")
            chosen_tt, chosen_tmdb = str(cand["tt"]), cand.get("tmdb_id")
            if chosen_tmdb is None and client is not None:
                # An OMDb-only candidate (The Cup, T3) still usually has a TMDB record under its tt.
                chosen_tmdb = client.find_by_imdb(chosen_tt)
            if chosen_tmdb is None:
                warn(f"tmdb id not resolved for {chosen_tt} (no client or no TMDB record); imdb only")
        elif tt is not None:
            chosen_tt = tt
            found = None
            tmdb_failed = False
            if client is not None:
                try:
                    found = client.find_by_imdb_any(tt)
                except (requests.RequestException, AuthError) as exc:
                    # A dead /find call must not escape as a raw HTTP error (Dekalog rehearsal
                    # defect): degrade to imdb-only keying, same as the "no client" convention
                    # below, rather than aborting the whole resolution — the human's --series
                    # flag (if given) still applies since `found` stays None either way.
                    tmdb_failed = True
                    warn(f"tmdb lookup failed for {tt} ({exc}); imdb only")
            is_series = series or (found is not None and found.movie_id is None and found.tv)
            if series and found is not None and found.movie_id is not None and not found.tv:
                raise ValueError(f"TMDB has a movie for {tt} (id {found.movie_id}) — drop --series")
            chosen_tmdb = None if is_series else (found.movie_id if found is not None else None)
            if chosen_tmdb is None and not is_series and not tmdb_failed:
                warn(f"tmdb id not resolved for {tt} (no client or no TMDB record); imdb only")
        else:
            chosen_tt = "NONE"
        if chosen_tt != "NONE":
            if repo.tmdb_target(rid) is None:
                raise ValueError(f"film {rid} not found")
            # One identity write path with sync and the repair verbs (spec §4.1). Both branches
            # above already asked TMDB for the id, so key_film never repeats the lookup — and a
            # series arrives with no tmdb id at all, which is exactly how it stays keyed.
            keyed = key_film(
                repo, client, rid, chosen_tt, today, lambda _m: None,
                tmdb_id=chosen_tmdb, resolve_tmdb_id=False,
            )
            if keyed.status == "held":
                holder = repo.film_id_for_external("imdb", chosen_tt)
                if holder is not None and holder != rid:
                    raise ValueError(f"{chosen_tt} is already held by film {holder}")
                raise ValueError(f"tmdb id {chosen_tmdb} is already held by another film — merge instead")
            if keyed.status == "error":
                raise ValueError(keyed.detail)
            if is_series:
                repo.set_film_kind(rid, "series")
                outcome = f"keyed series imdb {chosen_tt}"
            else:
                outcome = f"keyed imdb {chosen_tt} tmdb {chosen_tmdb or '-'}"
        else:
            outcome = "verified unkeyed"
        if eval_csv is not None:
            q = parsed.query if parsed is not None and parsed.query else None
            view = repo.get_view(rid, today)
            claims = repo.claims_for_film(rid)
            authorities = {c.authority for c in claims}
            # Every read of the stored query is a `.get()`: `review_detail`'s query is written by
            # the resolver but the row is human-editable, and a hand-trimmed detail must degrade
            # to the film's own facts rather than KeyError mid-resolution.
            source = (str(q.get("source")) if q and q.get("source") else "") or next(
                (a for a in ("criterion", "metacritic") if a in authorities),
                "apple" if "apple-tv" in authorities else "unknown",
            )
            verb = f"--pick {pick}" if pick else ("--tt" if tt else "--none")
            # The eval row records what the INGESTER saw, not what the film now knows: a query
            # with no year stays yearless here. Falling back to films.year would hand the
            # benchmark a year the real ingestion never had and score those rows optimistically.
            q_year = q.get("year") if q else None
            eval_entry = EvalEntry(
                rid,
                source,
                (str(q.get("title")) if q and q.get("title") else "") or (view.title if view else ""),
                (int(str(q_year)) if q_year else None) if q else (view.year if view else None),
                chosen_tt,
                "" if chosen_tmdb is None else str(chosen_tmdb),
                f"review {review_id} {verb}",
            )
    elif authority == TMDB_AUTHORITY:
        if tmdb_id is not None and rid is not None:
            target = repo.tmdb_target(rid)
            if target is None:
                raise ValueError(f"film {rid} not found")
            year = client.movie_year(tmdb_id) if client is not None else None
            result = record_tmdb_match(repo, target, tmdb_id, year, today, lambda _m: None)
            if result == "id-conflict":
                raise ValueError(f"tmdb id {tmdb_id} is already held by another film — merge instead")
            outcome = f"matched to tmdb {tmdb_id} ({result})"
        elif film_id is not None and reason in MERGE_REASONS and rid is not None:
            if reason == "id-conflict":
                if value is None:
                    raise ValueError(f"id-conflict review {review_id} has no claimed id")
                # The value is whichever id was contested: `key_films` queues a TMDB id,
                # `repair imdb` an IMDb id. Re-derive the holder under the matching authority.
                authority = "imdb" if _IMDB_ID.match(value) else TMDB_AUTHORITY
                holder = repo.film_id_for_external(authority, value)
            else:
                holder = int(value) if value else None
            if holder != film_id:
                raise ValueError(f"the twin for this row is film {holder}, not {film_id} (re-derived)")
            repo.merge_film(rid, film_id, today, note=note or f"review {review_id} {reason}")
            outcome = f"merged film {rid} into {film_id}"
        else:
            raise ValueError(f"tmdb/{reason} accepts --tmdb-id (no-match) or --film (twin) or --dismiss")
    elif authority == MC_AUTHORITY and reason in SLUG_REASONS and value is not None:
        if film_id is not None:
            try:
                repo.set_external_id(film_id, MC_AUTHORITY, value, today)
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"slug {value!r} is already claimed") from exc
            outcome = f"slug {value} → film {film_id}"
        elif create:
            staged = repo.staged_title(value)
            if staged is None:
                raise ValueError(f"slug {value!r} is not in the staged archive")
            if value in repo.claimed_values(MC_AUTHORITY):
                raise ValueError(f"slug {value!r} is already claimed")
            new_id = create_from_staged(repo, staged, today)
            if new_id is None:
                raise ValueError(
                    f"creating {staged.title!r} ({staged.year}) collides with an existing film's key"
                )
            outcome = f"created film {new_id} from slug {value}"
        else:
            raise ValueError("metacritic slug rows accept --film, --create or --dismiss")
    elif authority == LIST_AUTHORITY and value is not None:
        slug, _, rank_s = value.rpartition("#")
        rank = int(rank_s)
        # Re-derive the entry's own listed title/director at resolution time (the standing
        # rule: resolution re-derives, never trusts the row's stored value) rather than the
        # review row's detail text, which is display-only and may have been hand-edited.
        entry = next((e for e in repo.list_entries(slug) if e.rank == rank), None)
        if entry is None:
            raise ValueError(f"list {slug!r} rank {rank} not found")
        # An entry that already carries a link is settled, and ONE entry can hold two open
        # rows: `queue_list_review_once` dedups on reason + value, so an `unresolved` row and
        # a later `corpus-veto` row for the same rank both stay open. Resolving the second
        # would silently MOVE the link — `add_claim` is INSERT OR IGNORE on
        # UNIQUE(authority, value), so the first film keeps the `list` claim for an entry it
        # no longer holds and nothing anywhere records the move. Guards --create too, whose
        # own `film_id` is not bound until after `create_film` below.
        if entry.film_id is not None and entry.film_id != film_id:
            raise ValueError(f"list {slug!r} rank {rank} is already linked to film {entry.film_id}")
        if film_id is not None:
            twin_rank = repo.film_rank_on_list(slug, film_id)
            if twin_rank is not None and twin_rank != rank:
                raise ValueError(f"film {film_id} is already linked at rank {twin_rank} on list {slug!r}")
            repo.link_list_entry(slug, rank, film_id)
            repo.add_claim(film_id, LIST_AUTHORITY, value, entry.title_listed, first_seen=today.isoformat())
            outcome = f"{value} → film {film_id}"
        elif create:
            # Unkeyed on purpose: the next sync's keying step keys it, exactly as an apple-tv
            # --create film is keyed. A films.key collision means the identity already exists
            # under some other title — canonicalize and link to it, never mint a twin.
            film = Film(entry.title_listed, None, entry.director_listed, "")
            new_id = repo.create_film(film)
            if new_id is None:
                new_id = repo.canonical_film_id(repo.film_id_by_key(film.key) or 0)
            repo.link_list_entry(slug, rank, new_id)
            repo.add_claim(new_id, LIST_AUTHORITY, value, entry.title_listed, first_seen=today.isoformat())
            outcome = f"created film {new_id} from list {value}"
        else:
            raise ValueError("list rows accept --film, --create or --dismiss")
    elif authority == APPLE_AUTHORITY and value is not None:
        if film_id is not None:
            repo.mark_owned(film_id, today)
            outcome = f"{value!r} → owned film {film_id}"
        elif create:
            cleaned, embedded = parse_apple_title(value)
            film = Film(cleaned, embedded, None, "")
            new_id = repo.create_film(film)
            if new_id is None:
                new_id = repo.canonical_film_id(repo.film_id_by_key(film.key) or 0)
            repo.mark_owned(new_id, today)
            outcome = f"created owned film {new_id} from {value!r}"
        else:
            raise ValueError("apple-tv rows accept --film, --create or --dismiss")
    else:
        raise ValueError(f"{authority}/{reason} rows accept only --dismiss")

    repo.resolve_review(review_id, f"{outcome} {today.isoformat()}")
    for fid in (rid, film_id):
        if fid is not None:
            repo.clear_revisit(fid)  # Task 9 replaces the no-op stub in Repository
    if eval_entry is not None and eval_csv is not None:
        ratify(eval_csv, eval_entry)  # spec §4.3: ground truth is ratified after the row is closed
    return outcome
