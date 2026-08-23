from __future__ import annotations

import csv
import os
from pathlib import Path

from movie_brain.domain.models import FilmView
from movie_brain.infrastructure.database import Repository

COLUMNS = ["title", "year", "director", "language", "metacritic", "rt", "imdb", "status", "leaving", "url", "my-rating"]


def _status(v: FilmView) -> str:
    if v.pending:
        return "pending"
    return "rated" if v.found else "unmatched"


def _rating_key(v: FilmView) -> tuple[bool, float, bool, float, bool, float, str]:
    """Dashboard-default sort hierarchy: metacritic, ties broken by rt, then imdb — each
    descending with missing values after present ones — and finally title."""
    return (
        v.metacritic is None,
        -(v.metacritic or 0),
        v.rt is None,
        -(v.rt or 0),
        v.imdb is None,
        -(v.imdb or 0.0),
        v.title.lower(),
    )


def write_csv(repo: Repository, path: Path, source: str = "criterion") -> int:
    views = sorted(repo.list_views(source), key=_rating_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(COLUMNS)
        for v in views:
            w.writerow(
                [
                    v.title,
                    v.year if v.year is not None else "",
                    v.director or "",
                    v.language or "",
                    v.metacritic if v.metacritic is not None else "",
                    v.rt if v.rt is not None else "",
                    v.imdb if v.imdb is not None else "",
                    _status(v),
                    v.leaving_date or "",
                    v.url,
                    v.my_rating if v.my_rating is not None else "",
                ]
            )
    os.replace(tmp, path)
    return len(views)
