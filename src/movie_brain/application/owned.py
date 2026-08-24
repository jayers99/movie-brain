from __future__ import annotations

import sys
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from movie_brain.domain.matching import match_owned, norm_title, parse_apple_title
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

    by_norm: dict[str, list[tuple[int, str, int | None]]] = defaultdict(list)
    for film_id, title, year, _ in repo.films_for_matching():
        by_norm[norm_title(title)].append((film_id, title, year))

    matched = created = already = 0
    reviews: list[ReviewEntry] = []
    for t in titles:
        cleaned, embedded_year = parse_apple_title(t.title)
        # A year embedded in the title is the original release year; the track's
        # year field can be a remaster/re-release year (truth-holder rule).
        year = embedded_year if embedded_year is not None else t.year
        candidates = by_norm.get(norm_title(cleaned), [])
        result = match_owned(cleaned, year, candidates)
        if result.tied:
            detail = f"films {sorted(result.tied)} tie for {t.title!r} ({year})"
            reviews.append(ReviewEntry("ambiguous-owned", value=t.title, detail=detail))
            continue
        if result.winner is not None:
            film_id = result.winner
            matched += 1
        elif candidates:
            # The title exists but every candidate's year is too far off — a re-release
            # year or a remake. Without director data to arbitrate, ask; never twin.
            detail = f"{cleaned!r} ({year}) vs films {sorted(c[0] for c in candidates)}"
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
                by_norm[norm_title(cleaned)].append((film_id, cleaned, year))
                created += 1
        if not repo.mark_owned(film_id, today):
            already += 1

    repo.replace_unresolved_reviews(AUTHORITY, reviews, today)
    return OwnedReport(0, len(titles), matched, created, already, len(repo.open_reviews(AUTHORITY)))
