from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from movie_brain.domain.matching import (
    Candidate,
    build_candidate_index,
    match_owned,
    parse_apple_title,
    split_annotations,
)
from movie_brain.domain.models import Film, OwnedTitle, ReviewEntry
from movie_brain.infrastructure import appletv
from movie_brain.infrastructure.database import Repository

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


def import_owned(
    repo: Repository,
    config_dir: Path,
    today: date,
    *,
    fetch: Callable[[], list[OwnedTitle]] | None = None,
    log: Callable[[str], None] = _stderr,
) -> OwnedReport:
    """Mark or create every movie in the Apple TV library (idempotent, never deletes).

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

    matched = created = already = 0
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
            new_id = repo.create_film(film)
            if new_id is None:
                # Exact film_key collision: that IS the film (same title+year).
                film_id = repo.film_id_by_key(film.key) or 0
                matched += 1
            else:
                film_id = new_id
                index.add(Candidate(id=film_id, title=cleaned, year=year))
                created += 1
        if not repo.mark_owned(film_id, today):
            already += 1

    repo.replace_unresolved_reviews(AUTHORITY, reviews, today)
    return OwnedReport(0, len(titles), matched, created, already, len(repo.open_reviews(AUTHORITY)))
