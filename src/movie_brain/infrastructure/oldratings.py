"""The old-ratings source file (spec 2026-09-19-old-ratings §4.1): a CSV the owner keeps OUTSIDE
this public repo. Header row required; `rating`, `title` are required columns, `year` and `rented`
optional, anything else ignored. Titles are kept verbatim — typos are the record, and the resolver
copes with them. `line` is the 1-based data-row number: the addressable key of a row.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from movie_brain.domain.models import OldRating


class OldRatingsFileError(ValueError):
    pass


def parse_old_ratings(text: str) -> list[OldRating]:
    reader = csv.DictReader(io.StringIO(text))
    missing = {"rating", "title"} - set(reader.fieldnames or ())
    if missing:
        raise OldRatingsFileError(f"missing column(s): {', '.join(sorted(missing))}")
    rows: list[OldRating] = []
    for line, raw in enumerate(reader, start=1):
        title = (raw.get("title") or "").strip()
        stars = (raw.get("rating") or "").strip()
        if not title:
            raise OldRatingsFileError(f"row {line}: empty title")
        if stars not in {"1", "2", "3", "4", "5"}:
            raise OldRatingsFileError(f"row {line}: rating {stars!r} is not 1-5")
        year = (raw.get("year") or "").strip()
        if year and not (year.isdigit() and len(year) == 4):
            raise OldRatingsFileError(f"row {line}: year {year!r} is not four digits")
        rented = (raw.get("rented") or "").strip()
        rows.append(OldRating(line, title, int(year) if year else None, int(stars), rented or None))
    return rows


def read_old_ratings(path: Path) -> list[OldRating]:
    return parse_old_ratings(path.read_text(encoding="utf-8"))
