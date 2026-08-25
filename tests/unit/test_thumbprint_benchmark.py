import csv
import gzip
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_eval_csv_has_director_and_runtime_columns():
    rows = list(csv.DictReader((ROOT / "scripts/eval/thumbprint_eval_v1.csv").open(encoding="utf-8")))
    assert {"director", "runtime_min"} <= set(rows[0])
    assert len(rows) >= 504
    assert sum(1 for r in rows if r["director"]) >= 150


def test_fixture_has_no_api_key():
    with gzip.open(ROOT / "scripts/eval/fixtures/cand_cache.json.gz", "rt", encoding="utf-8") as f:
        cache = json.load(f)
    assert not any("apikey" in k for k in cache)
    assert sum(1 for k in cache if k.startswith("td:")) > 1900


def test_gate_slice_zero_wrong():
    spec = importlib.util.spec_from_file_location("bench", ROOT / "scripts/thumbprint_benchmark.py")
    assert spec and spec.loader
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    rows = [r for r in csv.DictReader(m.CSV.open(encoding="utf-8")) if r["status"] in m.SCORED and r["expected_tt"]][
        :20
    ]
    fetcher = m.CandidateFetcher(m.CandidateCache.load(m.FIX, read_only=True), None, None)
    tally, wrong, *_ = m.run(rows, fetcher)
    assert wrong == [] and tally["correct"] >= 16
