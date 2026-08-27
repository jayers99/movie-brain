"""The eval CSV is the resolver's contract; a human resolution is evidence and lands here.

`ratify` is the ONLY programmatic writer of `scripts/eval/thumbprint_eval_v1.csv`
(rules: never edit the CSV to make the gate green). It rewrites a `proposed` row for the same
film + source, else appends a `F-human` row. Atomic: temp file + os.replace."""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from pathlib import Path

FIELDS = ["group", "film_id", "source", "title_ingested", "year_ingested", "expected_tt", "expected_tmdb",
          "verified_by", "note", "status", "director", "runtime_min"]


@dataclass(frozen=True)
class EvalEntry:
    film_id: int
    source: str
    title_ingested: str
    year_ingested: int | None
    expected_tt: str  # "NONE" = verified unkeyed
    expected_tmdb: str
    note: str


def ratify(csv_path: Path, entry: EvalEntry) -> str:
    rows: list[dict[str, str]] = []
    if csv_path.exists():
        with csv_path.open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
    for r in rows:
        if r["film_id"] == str(entry.film_id) and r["source"] == entry.source and r["status"] == "verified" \
                and r["expected_tt"] == entry.expected_tt:
            # The same decision is already on record: a second F-human row would only make the
            # benchmark score this film twice. Nothing is rewritten.
            return "already ratified"
    outcome = "appended"
    for r in rows:
        if r["film_id"] == str(entry.film_id) and r["source"] == entry.source and r["status"] == "proposed":
            was = f"; human: was {r['expected_tt'] or '-'}" if r["expected_tt"] != entry.expected_tt else ""
            r.update(expected_tt=entry.expected_tt, expected_tmdb=entry.expected_tmdb, verified_by="human",
                     status="verified", note=f"{r['note']}{was}; {entry.note}")
            outcome = "rewrote proposed row"
            break
    else:
        rows.append({
            "group": "F-human", "film_id": str(entry.film_id), "source": entry.source,
            "title_ingested": entry.title_ingested,
            "year_ingested": "" if entry.year_ingested is None else str(entry.year_ingested),
            "expected_tt": entry.expected_tt, "expected_tmdb": entry.expected_tmdb, "verified_by": "human",
            "note": entry.note, "status": "verified", "director": "", "runtime_min": "",
        })
    tmp = csv_path.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, csv_path)
    return outcome
