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
DEFAULT_LIST_NAME: dict[str, str] = {"owned": "My Ranked"}


def tier_for_score(score: int) -> int:
    """Seed mapping (ranking-pool spec P4): 10→1, 9→2, 8→3, 7→4, 6→5. A score below 6 is not a
    ranker film at all (5 = watched, indifferent; 1–4 disliked; 0 not interested) and raises."""
    if score >= 10:
        return 1
    if score == 9:
        return 2
    if score == 8:
        return 3
    if score == 7:
        return 4
    if score == 6:
        return 5
    raise ValueError(f"a score of {score} does not seed a tier")


ORDER_TIERS: tuple[int, ...] = (1, 2)  # the tiers the order mode exposes (ranking-pool spec P5)


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


@dataclass(frozen=True)
class Probe:
    """Show the candidate against this ordered film (order spec §4.1)."""

    film_id: int


@dataclass(frozen=True)
class Insert:
    """The candidate's slot is pinned: 0-based gap in the order (0 = before everything)."""

    slot: int


def order_step(order: Sequence[int], verdicts: Iterable[tuple[int, str]]) -> Probe | Insert:
    """Binary insertion with bounds derived from the log (order spec §4.1, O5).

    `order` is the tier's film ids by position; `verdicts` the candidate's logged
    (other_film_id, verdict) pairs. `better` caps the slot at that film's index, `worse`
    floors it at index + 1. A verdict against a film no longer in the order is ignored
    (§4.3 says why one can only exist transiently). Crossed bounds cannot arise by
    construction; if they do, the log is corrupt and this raises like `next_step`.
    """
    index = {fid: i for i, fid in enumerate(order)}
    lo, hi = 0, len(order)
    for other, verdict in verdicts:
        i = index.get(other)
        if i is None:
            continue
        if verdict == "better":
            hi = min(hi, i)
        elif verdict == "worse":
            lo = max(lo, i + 1)
        else:
            raise ValueError(f"illegal order verdict {verdict!r}")
    if lo > hi:
        raise ValueError(f"crossed order bounds lo={lo} hi={hi}")
    if lo == hi:
        return Insert(lo)
    return Probe(order[(lo + hi) // 2])


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


def tiered_entries(placed: Iterable[Placed], order: Mapping[int, int] | None = None) -> list[TieredEntry]:
    """The saved list's lines (tier spec §7, order spec §4.5): tier asc; inside a tier the
    ordered films first by position with bare labels, then the rest by title tied at the
    first unordered line (`=N`) when two or more, bare when one. With no order this is
    byte-for-byte the tiering's own output."""
    positions = dict(order or {})
    by_tier: dict[int, list[Placed]] = {}
    for p in placed:
        by_tier.setdefault(p.tier, []).append(p)
    out: list[TieredEntry] = []
    line = 0
    for tier in sorted(by_tier):
        members = by_tier[tier]
        ordered = sorted((p for p in members if p.film_id in positions), key=lambda p: positions[p.film_id])
        rest = sorted(
            (p for p in members if p.film_id not in positions), key=lambda p: (p.title.casefold(), p.film_id)
        )
        for p in ordered:
            line += 1
            out.append(TieredEntry(line, p.film_id, p.title, p.director, None))
        first_rest = line + 1
        for p in rest:
            line += 1
            out.append(TieredEntry(line, p.film_id, p.title, p.director, f"={first_rest}" if len(rest) > 1 else None))
    return out
