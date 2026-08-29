"""Curated-list file adapter: parse the checked-in `lists/<slug>.tsv` format.

One list per file, hand-extracted once (Claude Extracts It, per the design doc) and
checked in under `lists/`. `parse_list_file` is pure; `read_list_file` is the one I/O
function. Titles and directors are kept byte-for-byte — no normalization, stripping,
or case-folding — a list is a historical artifact and later re-readings must see
exactly what the curator wrote.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from movie_brain.domain.models import ListEntry, ListMeta

_TRUE = {"true", "1", "yes"}
_FALSE = {"false", "0", "no"}
_TT_RE = re.compile(r"^tt\d+$")


class ListFileError(Exception):
    pass


@dataclass(frozen=True)
class ParsedList:
    meta: ListMeta
    entries: tuple[ListEntry, ...]


def _parse_ordered(raw: str) -> bool:
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ListFileError(f"ordered: expected true/false, got {raw!r}")


def parse_list_file(text: str) -> ParsedList:
    lines = text.splitlines()

    header: dict[str, str] = {}
    i = 0
    while i < len(lines) and lines[i].startswith("#"):
        line = lines[i][1:].strip()
        i += 1
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        header[key.strip()] = value.strip()

    slug = header.get("slug")
    if not slug:
        raise ListFileError("missing required header: slug")
    name = header.get("name")
    if not name:
        raise ListFileError("missing required header: name")

    published_raw = header.get("published")
    published_year = int(published_raw) if published_raw else None

    meta = ListMeta(
        slug=slug,
        name=name,
        curator=header.get("curator") or None,
        published_year=published_year,
        source_url=header.get("source") or None,
        ordered=_parse_ordered(header.get("ordered", "true")),
    )

    entries: list[ListEntry] = []
    seen_ranks: set[int] = set()
    for line in lines[i:]:
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            raise ListFileError(f"malformed data row (need at least rank and title): {line!r}")
        rank_raw, title_listed = parts[0], parts[1]
        director_listed = parts[2] if len(parts) >= 3 and parts[2] else None
        tt_raw = parts[3] if len(parts) >= 4 and parts[3] else None
        if tt_raw is not None and not _TT_RE.match(tt_raw):
            raise ListFileError(f"malformed tt id: {tt_raw!r}")
        tt_listed = tt_raw

        try:
            rank = int(rank_raw)
        except ValueError as e:
            raise ListFileError(f"non-integer rank: {rank_raw!r}") from e
        if rank in seen_ranks:
            raise ListFileError(f"duplicate rank: {rank}")
        seen_ranks.add(rank)

        if not title_listed:
            raise ListFileError(f"empty title at rank {rank}")

        entries.append(ListEntry(rank, title_listed, director_listed, tt_listed))

    return ParsedList(meta=meta, entries=tuple(entries))


def read_list_file(path: Path) -> ParsedList:
    return parse_list_file(path.read_text())
