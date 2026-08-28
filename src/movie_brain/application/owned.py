from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import requests

from movie_brain.application.keying import key_film
from movie_brain.application.review import suppress_resolved
from movie_brain.domain.matching import (
    Candidate,
    build_candidate_index,
    match_owned,
    parse_apple_title,
    split_annotations,
)
from movie_brain.domain.models import Film, OwnedTitle, ReviewEntry
from movie_brain.domain.thumbprint import edition_label, make_query, resolve
from movie_brain.infrastructure import appletv
from movie_brain.infrastructure.database import Repository
from movie_brain.infrastructure.omdb import QuotaExceeded
from movie_brain.infrastructure.thumbprint_fetch import CacheMiss, CandidateFetcher
from movie_brain.infrastructure.tmdb import AuthError, TmdbClient

AUTHORITY = "apple-tv"


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


@dataclass(frozen=True)
class OwnedReport:
    exit_code: int
    total: int
    matched: int
    created: int
    already_owned: int
    review_open: int
    resolved_to_existing: int = 0
    keyed: int = 0


def _claim_and_mark(repo: Repository, film_id: int, t: OwnedTitle, today: date) -> bool:
    """Record the raw-title claim and mark ownership (Task 4's block, lifted so every path
    that lands on a film — matched, created, or resolved straight to an existing holder —
    shares one write instead of three chances to drift or double-write."""
    repo.add_claim(
        film_id, AUTHORITY, t.title, t.title,
        year_claimed=t.year, edition_label=edition_label(t.title),
        runtime_min=t.runtime_min, first_seen=today.isoformat(),
    )
    return repo.mark_owned(film_id, today)


def import_owned(
    repo: Repository,
    config_dir: Path,
    today: date,
    *,
    fetch: Callable[[], list[OwnedTitle]] | None = None,
    fetcher: CandidateFetcher | None = None,
    tmdb: TmdbClient | None = None,
    log: Callable[[str], None] = _stderr,
) -> OwnedReport:
    """Mark or create every movie in the Apple TV library (idempotent, never deletes).

    With a resolver `fetcher`, each raw title is resolved through the thumbprint
    algorithm FIRST: a `match` whose tt (or tmdb id) some existing film already holds
    marks THAT film owned instead of minting a twin under the edition's own title/year
    (T5b). A resolver match nobody holds falls through to the corpus path exactly as
    before; only when that also misses is a film created — and then keyed immediately
    with the resolver's verdict, so it isn't born unidentified. With no `fetcher` (no
    TMDB token or no OMDb key), behavior is unchanged from before this resolver existed.

    Matched films are marked owned; misses become real films (generated guid) and
    are marked; ambiguous ties queue for review, never guessed. Ownership is
    permanent — a title vanishing from the library never unmarks anything.
    """
    try:
        titles = (fetch or (lambda: appletv.fetch_owned(config_dir, today=today)))()
    except appletv.AppleTvError as exc:
        log(f"Apple TV export failed, database unchanged: {exc}")
        return OwnedReport(1, 0, 0, 0, 0, 0)

    index = build_candidate_index(repo.films_for_matching())
    tombstoned = repo.tombstoned_keys()

    matched = created = already = resolved = keyed = 0
    reviews: list[ReviewEntry] = []
    for t in titles:
        cleaned, embedded_year = parse_apple_title(t.title)
        # A year embedded in the title is the original release year; the track's
        # year field can be a remaster/re-release year (truth-holder rule).
        year = embedded_year if embedded_year is not None else t.year
        # parse_apple_title already stripped any edition annotation from `cleaned` —
        # detect it against the ORIGINAL title so match_owned's rerelease corroboration
        # (a re-release/restored-version annotation excusing a commerce-year gap) isn't
        # dead code for this caller.
        rerelease_hint = bool(split_annotations(t.title)[1])

        verdict = None
        if fetcher is not None:
            q = make_query(t.title, year, "apple", runtime_min=t.runtime_min)
            try:
                verdict = resolve(q, fetcher.fetch(q))
            except (CacheMiss, requests.RequestException, AuthError, QuotaExceeded) as exc:
                log(f"resolver lookup failed for {t.title!r}: {exc}")
        if verdict is not None and verdict.kind == "match" and verdict.tt is not None:
            # The work this edition belongs to may already be in the DB under its own
            # title — landing on it is what stops the import minting a twin (T5b).
            holder = repo.film_id_for_external("imdb", verdict.tt)
            if holder is None:
                winner = next((s.candidate for s in verdict.ranked if s.candidate.tt == verdict.tt), None)
                if winner is not None and winner.tmdb_id is not None:
                    holder = repo.film_id_for_external("tmdb", str(winner.tmdb_id))
            if holder is not None:
                film_id = repo.canonical_film_id(holder)
                resolved += 1
                _claim_and_mark(repo, film_id, t, today)  # the Task 4 claim + mark_owned block
                continue

        result = match_owned(
            cleaned,
            year,
            index,
            embedded_year=embedded_year is not None,
            rerelease_hint=rerelease_hint,
            runtime_min=t.runtime_min,
        )
        if result.tied:
            detail = f"films {sorted(result.tied)} tie for {t.title!r} ({year})"
            reviews.append(ReviewEntry("ambiguous-owned", value=t.title, detail=detail))
            continue
        if result.winner is not None:
            film_id = result.winner
            matched += 1
        elif result.reason is not None:
            # The title exists but the evidence conflicts — a re-release year, a
            # remake, or a hard-evidence mismatch. Without more to arbitrate, ask;
            # never twin.
            detail = f"{cleaned!r} ({year}) — review reason {result.reason!r}"
            reviews.append(ReviewEntry("year-drift", value=t.title, detail=detail))
            continue
        else:
            film = Film(cleaned, year, None, "")
            if film.key in tombstoned:
                log(f"skipping tombstoned film {film.key!r} from the Apple library")
                continue
            new_id = repo.create_film(film)
            if new_id is None:
                # Exact film_key collision: that IS the film (same title+year) — or its alias.
                film_id = repo.canonical_film_id(repo.film_id_by_key(film.key) or 0)
                matched += 1
            else:
                film_id = new_id
                index.add(Candidate(id=film_id, title=cleaned, year=year))
                created += 1
                if verdict is not None and verdict.kind == "match" and verdict.tt is not None:
                    winner = next((s.candidate for s in verdict.ranked if s.candidate.tt == verdict.tt), None)
                    r = key_film(
                        repo, tmdb, film_id, verdict.tt, today, log,
                        tmdb_id=winner.tmdb_id if winner is not None else None,
                    )
                    if r.status in ("keyed", "unlinked"):
                        keyed += 1
                    else:
                        log(f"created #{film_id} unkeyed ({r.status}: {r.detail}); the next sync will retry")
        if not _claim_and_mark(repo, film_id, t, today):
            already += 1

    repo.replace_unresolved_reviews(AUTHORITY, suppress_resolved(repo, AUTHORITY, reviews), today)
    return OwnedReport(
        0, len(titles), matched, created, already, len(repo.open_reviews(AUTHORITY)), resolved, keyed
    )
