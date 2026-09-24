"""Keyword benchmark for the search bar (search-recall spec D8). Read-only over a COPY of the
database, never the live one.

  uv run python scripts/search_benchmark.py --db <copy.db> [--sample 300] [--seed 7] [--min 3]
      [--max 30] [--model all-MiniLM-L6-v2 --dim 384] [--embed] [--label baseline] [--json out.json]

Queries are TMDB keywords held by --min..--max films (the tagged films are the answers), run
verbatim and as a plural variant (last word + "s") through `run_search`, plus two named rows:
"time loops" → Groundhog Day (#4850) and "dystopian" → every film tagged `dystopia`. Scores:
hit rate (at least one tagged film anywhere in the result) and recall@10 (tagged films in the
top ten over min(10, tagged)). --embed re-embeds the copy with --model first (a model trial).
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sqlite3
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from movie_brain.application.embed import embed_films  # noqa: E402
from movie_brain.application.search import run_search  # noqa: E402
from movie_brain.domain.search import EMBED_DIM, EMBED_MODEL  # noqa: E402
from movie_brain.infrastructure.database import Repository  # noqa: E402
from movie_brain.infrastructure.embeddings import SentenceTransformerEmbedder, VectorIndex  # noqa: E402

GROUNDHOG_DAY = 4850


@dataclass(frozen=True)
class Row:
    query: str
    expected_n: int
    hit: bool
    recall10: float
    size: int


@dataclass(frozen=True)
class Report:
    rows: list[Row]
    hit_rate: float
    recall10: float
    mean_size: float


def pick_keywords(rows: Sequence[tuple[str, frozenset[int]]], sample: int, seed: int, lo: int, hi: int) -> list[tuple[str, frozenset[int]]]:
    eligible = sorted((k, ids) for k, ids in rows if lo <= len(ids) <= hi)
    rng = random.Random(seed)
    return eligible if len(eligible) <= sample else sorted(rng.sample(eligible, sample))


def plural(query: str) -> str | None:
    words = query.split()
    if not words or words[-1].endswith("s"):
        return None
    return " ".join(words[:-1] + [words[-1] + "s"])


def score(expected: frozenset[int], ids: Sequence[int]) -> tuple[bool, float]:
    top = set(ids[:10]) & expected
    return bool(expected & set(ids)), len(top) / min(10, len(expected)) if expected else 0.0


def run_benchmark(repo: Repository, index: VectorIndex | None, queries: list[tuple[str, frozenset[int]]]) -> Report:
    rows = []
    for q, expected in queries:
        ids = run_search(repo, q, index=index).ids
        hit, r10 = score(expected, ids)
        rows.append(Row(q, len(expected), hit, r10, len(ids)))
    n = len(rows) or 1
    return Report(rows, sum(r.hit for r in rows) / n, sum(r.recall10 for r in rows) / n, sum(r.size for r in rows) / n)


def _keyword_rows(db_path: Path) -> dict[str, frozenset[int]]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        out: dict[str, set[int]] = {}
        for r in conn.execute("SELECT keyword, film_id FROM film_keyword"):
            out.setdefault(str(r[0]), set()).add(int(r[1]))
    finally:
        conn.close()
    return {k: frozenset(v) for k, v in out.items()}


def _live_db() -> Path:
    cfg = os.environ.get("MOVIE_BRAIN_CONFIG_DIR")
    return (Path(cfg) if cfg else Path.home() / ".config" / "movie-brain") / "movie-brain.db"


def main(argv: Sequence[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True, type=Path)
    ap.add_argument("--sample", type=int, default=300)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--min", type=int, default=3)
    ap.add_argument("--max", type=int, default=30)
    ap.add_argument("--model", default=EMBED_MODEL)
    ap.add_argument("--dim", type=int, default=EMBED_DIM)
    ap.add_argument(
        "--embed",
        action="store_true",
        help="re-embed the copy with --model before scoring",
    )
    ap.add_argument("--label", default="run")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)
    if args.db.resolve() == _live_db().resolve():
        sys.exit("refusing to run on the live database; copy it first")
    repo = Repository(args.db, migrate=True)
    embedder = SentenceTransformerEmbedder(args.model)
    if args.embed:
        t0 = time.perf_counter()
        report = embed_films(
            repo, embedder, date.today(), apply=True, model=args.model, dim=args.dim,
            log=lambda m: print(m, file=sys.stderr),
        )
        print(f"embedded {report.embedded} with {args.model} in {time.perf_counter() - t0:.0f}s", file=sys.stderr)
    index = VectorIndex(repo, embedder, model=args.model, dim=args.dim)
    kw = _keyword_rows(args.db)
    picked = pick_keywords(list(kw.items()), args.sample, args.seed, args.min, args.max)
    verbatim = run_benchmark(repo, index, picked)
    variants = [(p, ids) for q, ids in picked if (p := plural(q))]
    plurals = run_benchmark(repo, index, variants)
    named = run_benchmark(repo, index, [("time loops", frozenset({GROUNDHOG_DAY})), ("dystopian", kw.get("dystopia", frozenset()))])
    t0 = time.perf_counter()
    embedder.encode(["a short query"])
    warm_ms = (time.perf_counter() - t0) * 1000
    print(f"{args.label}: model={args.model} keywords={len(picked)} warm-encode={warm_ms:.0f}ms")
    print(f"{'set':<10}{'n':>6}{'hit rate':>10}{'recall@10':>11}{'mean size':>11}")
    for name, rep in (("verbatim", verbatim), ("plural", plurals)):
        print(f"{name:<10}{len(rep.rows):>6}{rep.hit_rate:>10.3f}{rep.recall10:>11.3f}{rep.mean_size:>11.1f}")
    for r in named.rows:
        print(f"  {r.query!r}: expected {r.expected_n}, hit={r.hit}, recall@10={r.recall10:.2f}, size={r.size}")
    if args.json:
        args.json.write_text(json.dumps({"label": args.label, "model": args.model, "warm_ms": warm_ms,
                                         "verbatim": asdict(verbatim), "plural": asdict(plurals), "named": asdict(named)}, indent=1))


if __name__ == "__main__":
    main()
