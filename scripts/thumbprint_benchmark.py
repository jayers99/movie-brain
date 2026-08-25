"""Thumbprint resolver gate (memo §5). Offline by default — reads the checked-in fixture.

  uv run python scripts/thumbprint_benchmark.py [--assert] [--status verified|believed] [--group G]
                                                [--refresh] [--limit N]

Scored population = rows with status verified|believed and a non-empty expected_tt.
Gate: WRONG == 0, then auto-correct >= 90%. `proposed` rows are reported, never scored.
--refresh fetches missing cache keys with the real clients and rewrites the fixture.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from movie_brain.domain.thumbprint import Verdict, make_query, resolve  # noqa: E402
from movie_brain.infrastructure.thumbprint_fetch import CacheMiss, CandidateCache, CandidateFetcher  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CSV = ROOT / "scripts/eval/thumbprint_eval_v1.csv"
FIX = ROOT / "scripts/eval/fixtures/cand_cache.json.gz"
SCORED = {"verified", "believed"}


def run(rows, fetcher):
    tally: Counter[str] = Counter()
    wrong = []
    reasons = defaultdict(list)
    bygroup = defaultdict(Counter)
    for r in rows:
        q = make_query(
            r["title_ingested"],
            int(r["year_ingested"]) if r["year_ingested"] else None,
            r["source"],
            director=r.get("director") or None,
            runtime_min=int(r["runtime_min"]) if r.get("runtime_min") else None,
        )
        try:
            v = resolve(q, fetcher.fetch(q))
        except CacheMiss as e:
            v = Verdict("review", None, f"cache miss {e}", ())
        exp = r["expected_tt"]
        if v.kind == "match":
            res = "correct" if v.tt == exp else "WRONG"
        else:
            res = "review-none-ok" if exp == "NONE" else "review"
        tally[res] += 1
        bygroup[r["group"]][res] += 1
        if res == "WRONG":
            wrong.append(
                (
                    r["group"],
                    r["source"],
                    r["title_ingested"],
                    r["year_ingested"],
                    "exp",
                    exp,
                    "got",
                    v.tt,
                    v.reason,
                    r["status"],
                )
            )
        elif res == "review":
            reasons[v.reason].append(r["title_ingested"])
    return tally, wrong, reasons, bygroup


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--assert", dest="gate", action="store_true")
    ap.add_argument("--status")
    ap.add_argument("--group")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    rows = [r for r in csv.DictReader(CSV.open(encoding="utf-8")) if r["expected_tt"]]
    if a.group:
        rows = [r for r in rows if r["group"].startswith(a.group)]
    scored = [r for r in rows if r["status"] in SCORED and (not a.status or r["status"] == a.status)]
    proposed = [r for r in rows if r["status"] == "proposed"]
    if a.limit:
        scored = scored[: a.limit]
    if a.refresh:
        from movie_brain.infrastructure.config import load_api_key, load_config, load_tmdb_token
        from movie_brain.infrastructure.omdb import OmdbClient
        from movie_brain.infrastructure.tmdb import TmdbClient

        cfg = load_config()
        token, key = load_tmdb_token(cfg), load_api_key(cfg)
        if not token or not key:
            sys.exit("--refresh needs both the TMDB token and the OMDb key")
        cache = CandidateCache.load(FIX)
        fetcher = CandidateFetcher(cache, TmdbClient(token), OmdbClient(key))
    else:
        cache = CandidateCache.load(FIX, read_only=True)
        fetcher = CandidateFetcher(cache, None, None)
    tally, wrong, reasons, bygroup = run(scored, fetcher)
    if a.refresh:
        cache.save()
        print(f"fixture refreshed: {cache.misses} new keys")
    print(f"   fixture soft misses (detail/by-id never fetched): {cache.soft_misses}")
    n = sum(tally.values())
    auto = tally["correct"] / n if n else 0.0
    rev = tally["review"] + tally["review-none-ok"]
    print(
        f"thumbprint gate  n={n}  WRONG={tally['WRONG']}  auto-correct={tally['correct']} ({100 * auto:.1f}%)  "
        f"review={rev} ({100 * rev / n if n else 0:.1f}%)"
    )
    for g, t in sorted(bygroup.items()):
        print(f"   {g:22} {dict(t)}")
    print("   review reasons:", {k: len(v) for k, v in reasons.items()})
    for w in wrong:
        print("   WRONG:", w)
    pt, pw, _, _ = run(proposed, fetcher)
    print(
        f"proposed (not scored): n={sum(pt.values())} agree={pt['correct']} "
        f"disagree={pt['WRONG']} review={pt['review']}"
    )
    for w in pw:
        print("   proposed-disagree:", w)
    if a.gate and (tally["WRONG"] or auto < 0.90):
        print("GATE FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
