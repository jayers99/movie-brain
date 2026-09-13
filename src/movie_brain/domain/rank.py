"""Tier ranker: the pure placement logic (spec docs/superpowers/specs/2026-09-13-tier-ranker-design.md).

Five tiers, each defined by one anchor film; a candidate is placed by a binary search over the
anchors (§4.1). Everything here is a function of values the caller passes in — no I/O, no clock.
"""

from __future__ import annotations

import zlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from .models import Placed, SeedFilm, TieredEntry

TIERS = 5
# The score each tier is "about" — the anchor proposal picks the seeded film nearest it (§4.5).
TIER_MIDDLE: dict[int, int] = {1: 10, 2: 9, 3: 8, 4: 7, 5: 5}
VERDICTS = ("better", "worse")  # the CANDIDATE is better/worse than the anchor (D9: no `same`)

# The ranker's own lists: not backed by lists/<slug>.tsv, refused by `lists import` (§7).
RANKER_SLUGS: dict[str, str] = {"owned": "my-owned-tiers"}
RANKER_LIST_SLUGS: frozenset[str] = frozenset(RANKER_SLUGS.values())
DEFAULT_LIST_NAME: dict[str, str] = {"owned": "My owned films, tiered"}


def tier_for_score(score: int) -> int:
    """Seed mapping (spec §3): 10→1, 9→2, 8→3, 7→4, everything 6 and below→5."""
    if score >= 10:
        return 1
    if score == 9:
        return 2
    if score == 8:
        return 3
    if score == 7:
        return 4
    return 5


@dataclass(frozen=True)
class Ask:
    tier: int


@dataclass(frozen=True)
class Place:
    tier: int


_STEPS: dict[tuple[str, ...], Ask | Place] = {
    (): Ask(3),
    ("better",): Ask(2),
    ("better", "better"): Place(1),
    ("better", "worse"): Place(2),
    ("worse",): Ask(4),
    ("worse", "better"): Place(3),
    ("worse", "worse"): Ask(5),
    ("worse", "worse", "better"): Place(4),
    ("worse", "worse", "worse"): Place(5),
}


def next_step(verdicts: Sequence[str]) -> Ask | Place:
    """The search table (spec §4.1). Any sequence outside it is a corrupt log and raises."""
    try:
        return _STEPS[tuple(verdicts)]
    except KeyError:
        raise ValueError(f"illegal verdict sequence {list(verdicts)!r}") from None


def propose_anchors(seeded: Iterable[SeedFilm]) -> dict[int, SeedFilm | None]:
    """One proposed anchor per tier (D4): the seeded film whose score is nearest the tier's
    middle, ties broken by IMDb rating desc then title. None for a tier with no seeded film."""
    by_tier: dict[int, list[SeedFilm]] = {t: [] for t in range(1, TIERS + 1)}
    for f in seeded:
        by_tier[tier_for_score(f.score)].append(f)
    out: dict[int, SeedFilm | None] = {}
    for tier, films in by_tier.items():
        if not films:
            out[tier] = None
            continue
        out[tier] = min(
            films, key=lambda f: (abs(f.score - TIER_MIDDLE[tier]), -(f.imdb if f.imdb is not None else -1.0), f.title)
        )
    return out


def queue_key(seed: int, film_id: int) -> int:
    """A film's fixed position in a session's shuffle. Keyed per film (not a shuffle of the
    whole list) so a film bought mid-session slots in without reordering everything (§4.3)."""
    return zlib.crc32(f"{seed}:{film_id}".encode())


def order_queue(seed: int, film_ids: Iterable[int], deferred: Mapping[int, str]) -> list[int]:
    """Unplaced films in seeded-shuffle order, deferred ones last by (deferred_on, film_id)."""
    ids = list(film_ids)
    fresh = sorted((i for i in ids if i not in deferred), key=lambda i: (queue_key(seed, i), i))
    later = sorted((i for i in ids if i in deferred), key=lambda i: (deferred[i], i))
    return fresh + later


def tiered_entries(placed: Iterable[Placed]) -> list[TieredEntry]:
    """The saved list's lines (spec §7): tier asc then title; `=<first line>` labels a tier of
    two or more, a tier of one stays bare."""
    ordered = sorted(placed, key=lambda p: (p.tier, p.title.casefold(), p.film_id))
    sizes: dict[int, int] = {}
    for p in ordered:
        sizes[p.tier] = sizes.get(p.tier, 0) + 1
    out: list[TieredEntry] = []
    first_line: dict[int, int] = {}
    for line, p in enumerate(ordered, start=1):
        first_line.setdefault(p.tier, line)
        label = f"={first_line[p.tier]}" if sizes[p.tier] > 1 else None
        out.append(TieredEntry(line, p.film_id, p.title, p.director, label))
    return out
