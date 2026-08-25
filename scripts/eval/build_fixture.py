"""One-shot: turn the research-session scratch cache + eval set into the checked-in contract.

Usage: uv run python scripts/eval/build_fixture.py SCRATCH_DIR
Reads the live DB read-only (director column) and the Apple archives (runtime column).
"""

import contextlib
import csv
import gzip
import json
import os
import sqlite3
import sys
from pathlib import Path

SP = Path(sys.argv[1])
ROOT = Path(__file__).resolve().parents[2]
CFG = Path(os.environ.get("MOVIE_BRAIN_CONFIG_DIR", Path.home() / ".config/movie-brain"))
COLS = [
    "group",
    "film_id",
    "source",
    "title_ingested",
    "year_ingested",
    "expected_tt",
    "expected_tmdb",
    "verified_by",
    "note",
    "status",
    "director",
    "runtime_min",
]

with open(SP / "cand_cache.json", encoding="utf-8") as f:
    raw = json.load(f)
out = {}
for k, v in raw.items():
    if k.startswith("o:"):
        p = json.loads(k[2:])
        p.pop("apikey", None)
        k = "o:" + json.dumps(p, sort_keys=True)
    out[k] = v
(ROOT / "scripts/eval/fixtures").mkdir(exist_ok=True)
with gzip.open(ROOT / "scripts/eval/fixtures/cand_cache.json.gz", "wt") as f:
    json.dump(out, f, ensure_ascii=False)

db = sqlite3.connect(f"file:{CFG}/movie-brain.db?mode=ro", uri=True)
rt: dict[str, int] = {}
for fn in sorted((CFG / "appletv").glob("owned-*.txt")):
    for line in fn.read_text().splitlines():
        p = line.split("\t")
        if len(p) >= 3:
            with contextlib.suppress(ValueError):
                rt[p[0]] = round(float(p[2]) / 60)
seen: set[tuple[str, str, str]] = set()
rows = []
for src in (ROOT / "scripts/eval/thumbprint_eval_v1.csv", SP / "eval_set_v1.csv"):
    with open(src, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            k = (r["film_id"], r["source"], r["title_ingested"])
            if k in seen:
                continue
            seen.add(k)
            d = (
                db.execute("select director from films where id=?", (r["film_id"],)).fetchone()
                if r["film_id"]
                else None
            )
            r["director"] = (d[0] if d else None) or ""
            r["runtime_min"] = str(rt.get(r["title_ingested"], "")) if r["source"] == "apple" else ""
            rows.append({c: r.get(c, "") for c in COLS})
with open(ROOT / "scripts/eval/thumbprint_eval_v1.csv", "w", newline="") as f:
    w = csv.DictWriter(f, COLS, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
print(len(rows), "rows;", len(out), "cache keys")
