from __future__ import annotations

import csv
from pathlib import Path

from movie_brain.application.eval_log import EvalEntry, ratify

HEADER = "group,film_id,source,title_ingested,year_ingested,expected_tt,expected_tmdb,verified_by,note,status,director,runtime_min\n"


def _rows(p: Path):
    with p.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_ratify_appends_human_row(tmp_path: Path):
    p = tmp_path / "e.csv"
    p.write_text(HEADER)
    assert ratify(p, EvalEntry(1, "apple", "Blade Runner (The Final Cut)", 2007, "tt0083658", "78", "review 9 --tt")) == "appended"
    r = _rows(p)[0]
    assert (r["group"], r["status"], r["verified_by"], r["expected_tt"], r["expected_tmdb"]) == ("F-human", "verified", "human", "tt0083658", "78")


def test_ratify_rewrites_matching_proposed_row(tmp_path: Path):
    p = tmp_path / "e.csv"
    p.write_text(HEADER + "D-disagree,7,criterion,Tiger,2020,tt1,5,x,old note,proposed,Dir,90\n")
    assert ratify(p, EvalEntry(7, "criterion", "Tiger", 2020, "tt2", "6", "review 3 --tt")) == "rewrote proposed row"
    r = _rows(p)
    assert len(r) == 1
    assert (r[0]["status"], r[0]["verified_by"], r[0]["expected_tt"], r[0]["expected_tmdb"]) == ("verified", "human", "tt2", "6")
    assert "human: was tt1" in r[0]["note"] and r[0]["director"] == "Dir"


def test_ratify_none_marks_verified_unkeyed(tmp_path: Path):
    p = tmp_path / "e.csv"
    p.write_text(HEADER)
    ratify(p, EvalEntry(2, "criterion", "Short", None, "NONE", "", "review 4 --none"))
    assert _rows(p)[0]["expected_tt"] == "NONE"
