from __future__ import annotations

import csv
import os
from pathlib import Path

from movie_brain.domain.models import FilmView
from movie_brain.infrastructure.database import Repository

COLUMNS = ["title", "year", "director", "language", "imdb", "rt", "status", "leaving", "url", "my-rating"]


def _status(v: FilmView) -> str:
    if v.pending:
        return "pending"
    return "rated" if v.found else "unmatched"


def write_csv(repo: Repository, path: Path, source: str = "criterion") -> int:
    views = sorted(repo.list_views(source), key=lambda v: (v.imdb is None, -(v.imdb or 0.0), v.title.lower()))
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
                    v.imdb if v.imdb is not None else "",
                    v.rt if v.rt is not None else "",
                    _status(v),
                    v.leaving_date or "",
                    v.url,
                    v.my_rating if v.my_rating is not None else "",
                ]
            )
    os.replace(tmp, path)
    return len(views)
