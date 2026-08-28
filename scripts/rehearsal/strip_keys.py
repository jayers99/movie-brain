"""Rehearsal harness (thumbprint T5, task 10). SCRATCH DATABASES ONLY.

The live database has zero films awaiting keying — every film already holds its imdb/tmdb
ids. To measure the new resolver's re-keying accuracy before it touches real data, this
script strips the identity ids off a stratified sample of KNOWN-GOOD films on a scratch copy
of the database, so the ingester has to re-derive them from scratch. `compare()` then scores
what the resolver produced against what was removed — the bar for the whole T5 project is
zero disagreements.

  uv run python scripts/rehearsal/strip_keys.py --count 300 [--manifest PATH]

Refuses to run unless `MOVIE_BRAIN_CONFIG_DIR` is set AND the resolved db path is not the
owner's live database (~/.config/movie-brain/movie-brain.db) — see `guard_scratch_only`.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from movie_brain.infrastructure.config import CONFIG_DIR_ENV, DEFAULT_CONFIG_DIR, load_config  # noqa: E402
from movie_brain.infrastructure.database import Repository  # noqa: E402

# Single source of truth for "the live database": DEFAULT_CONFIG_DIR is exactly what
# load_config() falls back to when MOVIE_BRAIN_CONFIG_DIR is unset.
LIVE_DB_PATH = DEFAULT_CONFIG_DIR / "movie-brain.db"

# Stratum order matters: it is also the fallback-fill order when a stratum's own criteria
# come up short (see `strip`).
STRATA = ("criterion-director", "metacritic", "apple-tv")


def guard_scratch_only(db_path: Path) -> None:
    """Refuse (SystemExit) unless MOVIE_BRAIN_CONFIG_DIR is set AND db_path does not resolve
    to the owner's live database. Fails CLOSED: an unset env var or an unresolvable comparison
    is treated as unsafe, never as permission."""
    if not os.environ.get(CONFIG_DIR_ENV):
        raise SystemExit(
            f"refusing to run: {CONFIG_DIR_ENV} is not set. "
            "This script strips identity data and must only run against a scratch config dir."
        )
    resolved = Path(db_path).resolve()
    live = LIVE_DB_PATH.resolve()
    if resolved == live:
        raise SystemExit(f"refusing to run: {resolved} is the live database.")


def _base_pool(conn: sqlite3.Connection) -> set[int]:
    """Films holding both an imdb and a tmdb external id, with tmdb.found = 1."""
    rows = conn.execute(
        "SELECT e_imdb.film_id FROM external_ids e_imdb "
        "JOIN external_ids e_tmdb ON e_tmdb.film_id = e_imdb.film_id AND e_tmdb.authority = 'tmdb' "
        "JOIN tmdb t ON t.film_id = e_imdb.film_id AND t.found = 1 "
        "WHERE e_imdb.authority = 'imdb'"
    ).fetchall()
    return {int(r["film_id"]) for r in rows}


def _stratum_pool(conn: sqlite3.Connection, stratum: str) -> set[int]:
    if stratum == "criterion-director":
        rows = conn.execute(
            "SELECT DISTINCT f.id AS film_id FROM films f "
            "JOIN listings l ON l.film_id = f.id AND l.source = 'criterion' "
            "WHERE f.director IS NOT NULL AND f.director != ''"
        ).fetchall()
    elif stratum == "metacritic":
        rows = conn.execute(
            "SELECT film_id FROM external_ids WHERE authority = 'metacritic' "
            "UNION SELECT film_id FROM claim WHERE authority = 'metacritic'"
        ).fetchall()
    elif stratum == "apple-tv":
        rows = conn.execute("SELECT film_id FROM claim WHERE authority = 'apple-tv'").fetchall()
    else:
        raise ValueError(f"unknown stratum {stratum!r}")
    return {int(r["film_id"]) for r in rows}


def strip(repo: Repository, count: int, manifest_path: Path) -> list[dict[str, Any]]:
    """Strip imdb/tmdb identity from a stratified sample of `count//3`-per-group known-good
    films (see module docstring for the strata). A stratum short on films meeting its own
    criteria is backfilled from the residual pool (known-good films matching none of the three
    strata) rather than borrowing another stratum's dedicated candidates — every shortfall,
    narrow or total, is reported to stderr, never silently absorbed.

    Stripping = delete the film's `imdb`/`tmdb` rows from `external_ids` and its `tmdb` table
    row. `films`, `omdb`, `claim`, and `listings` are left untouched — the claim rows are what
    the resolver reads to rebuild its query.
    """
    per_stratum = count // 3
    conn = sqlite3.connect(repo.db_path)
    conn.row_factory = sqlite3.Row
    try:
        base = _base_pool(conn)
        narrow_pools = {s: base & _stratum_pool(conn, s) for s in STRATA}
        classified: set[int] = set()
        for pool in narrow_pools.values():
            classified |= pool
        residual = sorted(base - classified)

        picked_ids: set[int] = set()
        assignments: list[tuple[str, int]] = []
        for stratum in STRATA:
            narrow_available = sorted(narrow_pools[stratum] - picked_ids)
            take = narrow_available[:per_stratum]
            shortfall = per_stratum - len(take)
            if shortfall > 0:
                fill = [fid for fid in residual if fid not in picked_ids][:shortfall]
                if fill:
                    print(
                        f"stratum {stratum!r}: only {len(take)}/{per_stratum} met its own "
                        f"criteria; backfilled {len(fill)} from the unclassified pool",
                        file=sys.stderr,
                    )
                    take = take + fill
                still_short = shortfall - len(fill)
                if still_short > 0:
                    print(
                        f"stratum {stratum!r}: short by {still_short} — no more known-good "
                        "films available",
                        file=sys.stderr,
                    )
            picked_ids.update(take)
            assignments.extend((stratum, fid) for fid in take)

        manifest: list[dict[str, Any]] = []
        for stratum, film_id in assignments:
            film_row = conn.execute("SELECT title, year FROM films WHERE id = ?", (film_id,)).fetchone()
            ids = {
                r["authority"]: r["value"]
                for r in conn.execute(
                    "SELECT authority, value FROM external_ids WHERE film_id = ? AND authority IN ('imdb', 'tmdb')",
                    (film_id,),
                ).fetchall()
            }
            manifest.append(
                {
                    "film_id": film_id,
                    "title": film_row["title"],
                    "year": film_row["year"],
                    "stratum": stratum,
                    "imdb": ids.get("imdb"),
                    "tmdb": ids.get("tmdb"),
                }
            )
            conn.execute(
                "DELETE FROM external_ids WHERE film_id = ? AND authority IN ('imdb', 'tmdb')",
                (film_id,),
            )
            conn.execute("DELETE FROM tmdb WHERE film_id = ?", (film_id,))
        conn.commit()
    finally:
        conn.close()

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return manifest


def compare(manifest_path: Path, repo: Repository) -> dict[str, Any]:
    """Score the re-key against the manifest. Per film: `agree` (holds exactly the ids it held
    before), `disagree` (holds a DIFFERENT id — the number that must be zero), `reviewed` (no
    ids, but an open no-match/no-match-reviewed tmdb review row exists), `unkeyed` (no ids, no
    review row). Returns overall totals plus a `by_stratum` breakdown."""
    manifest = json.loads(Path(manifest_path).read_text())
    totals = {"agree": 0, "disagree": 0, "reviewed": 0, "unkeyed": 0}
    by_stratum: dict[str, dict[str, int]] = {}

    conn = sqlite3.connect(repo.db_path)
    conn.row_factory = sqlite3.Row
    try:
        for entry in manifest:
            film_id = entry["film_id"]
            stratum = entry["stratum"]
            bucket = by_stratum.setdefault(stratum, {"agree": 0, "disagree": 0, "reviewed": 0, "unkeyed": 0})

            ids = {
                r["authority"]: r["value"]
                for r in conn.execute(
                    "SELECT authority, value FROM external_ids WHERE film_id = ? AND authority IN ('imdb', 'tmdb')",
                    (film_id,),
                ).fetchall()
            }
            has_any_id = ids.get("imdb") is not None or ids.get("tmdb") is not None
            if has_any_id:
                exact = ids.get("imdb") == entry.get("imdb") and ids.get("tmdb") == entry.get("tmdb")
                outcome = "agree" if exact else "disagree"
            else:
                has_review = (
                    conn.execute(
                        "SELECT 1 FROM match_review WHERE film_id = ? AND authority = 'tmdb' "
                        "AND resolved = 0 AND reason IN ('no-match', 'no-match-reviewed') LIMIT 1",
                        (film_id,),
                    ).fetchone()
                    is not None
                )
                outcome = "reviewed" if has_review else "unkeyed"

            totals[outcome] += 1
            bucket[outcome] += 1
    finally:
        conn.close()

    return {**totals, "by_stratum": by_stratum}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, required=True, help="total films to strip (split across 3 strata)")
    parser.add_argument(
        "--manifest", type=Path, default=None, help="manifest path (default: <config_dir>/strip-manifest.json)"
    )
    args = parser.parse_args(argv)

    config = load_config()
    guard_scratch_only(config.db_path)

    manifest_path = args.manifest or (config.config_dir / "strip-manifest.json")
    repo = Repository(config.db_path)
    manifest = strip(repo, count=args.count, manifest_path=manifest_path)
    print(f"stripped {len(manifest)} films; manifest written to {manifest_path}")


if __name__ == "__main__":
    main()
