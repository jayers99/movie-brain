"""Thumbprint use cases (T1): the claims backfill and the review-row serializer.

The resolver itself stays dark in T1 — nothing here is called by sync.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from movie_brain.domain.matching import parse_apple_title
from movie_brain.domain.models import film_key
from movie_brain.domain.thumbprint import Verdict, parse_title, title_norm
from movie_brain.infrastructure.database import Repository


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


@dataclass(frozen=True)
class BackfillReport:
    criterion: int
    metacritic: int
    apple: int
    apple_unrecovered: int
    title_norms: int
    editions: int


def _edition_label(raw: str) -> str | None:
    eds = parse_title(raw).editions
    return " / ".join(eds) if eds else None


def _apple_archive_lines(config_dir: Path) -> list[tuple[str, str, int | None, int | None]]:
    """(raw title, archive date, year, runtime_min) from every owned-*.txt, oldest first so
    the newest line for a title wins when replayed in order."""
    out: list[tuple[str, str, int | None, int | None]] = []
    for fn in sorted((config_dir / "appletv").glob("owned-*.txt")):
        m = re.search(r"owned-(\d{4}-\d{2}-\d{2})\.txt$", fn.name)
        day = m.group(1) if m else "1970-01-01"
        for line in fn.read_text().splitlines():
            parts = line.split("\t")
            if len(parts) < 2 or not parts[0].strip():
                continue
            year = int(parts[1]) if parts[1].strip().isdigit() and int(parts[1]) > 0 else None
            runtime: int | None = None
            if len(parts) >= 3:
                try:
                    runtime = round(float(parts[2].strip()) / 60)
                except ValueError:
                    runtime = None
            out.append((parts[0].strip(), day, year, runtime))
    return out


def backfill_claims(
    repo: Repository, config_dir: Path, *, apply: bool, log: Callable[[str], None] = _stderr
) -> BackfillReport:
    """Copy owned / Criterion / Metacritic evidence into `claim` rows (spec §3). Pure copy:
    no source row changes. Dry run prints what --apply would write; --apply is idempotent."""
    rows: list[
        tuple[int, str, str, str, int | None, int | None, str]
    ] = []  # film, authority, value, title, year, runtime, seen
    for film_id, url, title, seen, year in repo.criterion_listing_rows():
        rows.append((film_id, "criterion", url, title, year, None, seen))
    n_crit = len(rows)
    for film_id, slug, mc_title, mc_year, seen in repo.metacritic_claim_rows():
        rows.append((film_id, "metacritic", slug, mc_title, mc_year, None, seen))
    n_mc = len(rows) - n_crit
    # Apple: replay the archives through the same title→key path the import used, so the raw
    # title lands on the film it actually marked (or its survivor). Owned films never reached
    # by a line still get a claim under their own title.
    owned = dict(repo.owned_rows())
    titles = {f.id: f.title for f in repo.films_for_twins()}
    owned_by_norm: dict[str, list[int]] = {}
    for oid in owned:
        owned_by_norm.setdefault(title_norm(titles.get(oid, "")), []).append(oid)
    recovered: dict[int, tuple[int, str, str, str, int | None, int | None, str]] = {}
    for raw, day, year, runtime in _apple_archive_lines(config_dir):
        cleaned, embedded = parse_apple_title(raw)
        fid: int | None = repo.film_id_by_key(film_key(cleaned, embedded if embedded is not None else year))
        if fid is not None:
            fid = repo.canonical_film_id(fid)
        if fid is None or fid not in owned:
            # the import matched edition/re-release lines by title with a year gap, not by key
            same = owned_by_norm.get(title_norm(raw), [])
            fid = same[0] if len(same) == 1 else None
        if fid is not None:
            recovered[fid] = (fid, "apple-tv", raw, raw, year, runtime, day)
    unrecovered = 0
    for oid, first_imported in owned.items():
        if oid in recovered:
            rows.append(recovered[oid])
        else:
            unrecovered += 1
            t = titles.get(oid, str(oid))
            rows.append((oid, "apple-tv", t, t, None, None, first_imported))
    n_apple = len(owned)
    editions = [r for r in rows if _edition_label(r[3])]

    shown: dict[str, int] = {}
    for r in rows:
        if shown.get(r[1], 0) < 20 or r in editions:
            log(f"  {r[1]:10} #{r[0]:<5} {r[2]!r} title={r[3]!r} year={r[4]} rt={r[5]} ed={_edition_label(r[3])!r}")
            shown[r[1]] = shown.get(r[1], 0) + 1
    log(
        f"claims: criterion {n_crit} · metacritic {n_mc} · apple {n_apple} "
        f"(unrecovered {unrecovered}) · editions {len(editions)}"
    )
    written = 0
    norms = 0
    if apply:
        for film_id, authority, value, title, year, runtime, seen in rows:
            if repo.add_claim(
                film_id,
                authority,
                value,
                title,
                year_claimed=year,
                edition_label=_edition_label(title),
                runtime_min=runtime,
                first_seen=seen,
            ):
                written += 1
        for film_id, title in repo.films_missing_title_norm():
            repo.set_title_norm(film_id, title_norm(title))
            norms += 1
        log(f"applied: {written} new claim rows · {norms} title_norms filled")
    return BackfillReport(n_crit, n_mc, n_apple, unrecovered, norms, len(editions))


def review_detail(verdict: Verdict) -> str:
    """The one `match_review.detail` format for resolver rows (spec §5): reason + A/B/C."""
    cands = []
    for letter, s in zip("ABC", verdict.ranked, strict=False):
        c = s.candidate
        cands.append(
            {
                "letter": letter,
                "tt": c.tt,
                "tmdb_id": c.tmdb_id,
                "title": c.titles[0] if c.titles else "",
                "year": c.year,
                "director": c.directors,
                "runtime": c.runtime_min,
                "votes": c.votes,
                "in_tmdb": c.in_tmdb,
                "in_omdb": c.in_omdb,
                "why_not": None
                if verdict.tt == c.tt
                else f"score {s.score}: title {s.title_level} year {s.year_points} director {s.director_points}",
            }
        )
    return json.dumps({"reason": verdict.reason, "candidates": cands}, ensure_ascii=False)
