"""Smoke tests for the offline matching benchmark (scripts/matching_benchmark.py).

Loaded via importlib.util.spec_from_file_location since scripts/ is not a package.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Dataclasses with `from __future__ import annotations` resolve field types via
    # sys.modules[cls.__module__] — register before exec_module or that lookup is None.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def bench() -> Any:
    return _load("matching_benchmark", SCRIPTS_DIR / "matching_benchmark.py")


class _Owned:
    """Minimal stand-in for infrastructure.appletv.OwnedTitle (title, year)."""

    def __init__(self, title: str, year: int | None) -> None:
        self.title = title
        self.year = year


def test_case_names_are_unique(bench: Any) -> None:
    names = [c.name for c in bench.GROUND_TRUTHS]
    assert len(names) == len(set(names))
    assert len(names) > 0


def test_strangelove_control_matches(bench: Any) -> None:
    case = next(c for c in bench.GROUND_TRUTHS if c.name == "strangelove-control")
    result = bench.run_case(case, bench.baseline_matcher_set())
    assert result.observed == "match:1"
    assert result.passed


def test_lawrence_tmdb_reproduces_banked_wrong_match(bench: Any) -> None:
    """The baseline's title-blind top-3 fallback is expected to pick the wrong film —
    that's the documented, banked failure this benchmark exists to catch."""
    case = next(c for c in bench.GROUND_TRUTHS if c.name == "lawrence-tmdb")
    result = bench.run_case(case, bench.baseline_matcher_set())
    assert result.observed == "match:731627"
    assert result.expect == "none"
    assert not result.passed
    assert result.wrong_match


def test_lawrence_tmdb_new_matcher_returns_none(bench: Any) -> None:
    """New pick_tmdb_match drops the title-blind top-3 fallback: no title match, no result."""
    case = next(c for c in bench.GROUND_TRUTHS if c.name == "lawrence-tmdb")
    result = bench.run_case(case, bench.new_matcher_set())
    assert result.observed == "none"
    assert result.expect == "none"
    assert result.passed


def test_kill_bill_vol_1_new_matcher_matches(bench: Any) -> None:
    case = next(c for c in bench.GROUND_TRUTHS if c.name == "kill-bill-vol-1")
    result = bench.run_case(case, bench.new_matcher_set())
    assert result.observed == "match:1"
    assert result.passed


def test_diacritic_fold_new_matcher_matches(bench: Any) -> None:
    case = next(c for c in bench.GROUND_TRUTHS if c.name == "diacritic-fold")
    result = bench.run_case(case, bench.new_matcher_set())
    assert result.observed == "match:1"
    assert result.passed


def test_stop_making_sense_runtime_new_matcher_matches(bench: Any) -> None:
    case = next(c for c in bench.GROUND_TRUTHS if c.name == "stop-making-sense-runtime")
    result = bench.run_case(case, bench.new_matcher_set())
    assert result.observed == "match:1"
    assert result.passed


def test_dominates_true_iff_new_wrong_is_zero_and_le_baseline(bench: Any) -> None:
    zero = bench.GtSummary(passed=10, failed=0, wrong=0)
    one = bench.GtSummary(passed=9, failed=1, wrong=1)
    two = bench.GtSummary(passed=8, failed=2, wrong=2)
    # New has zero wrong-matches and baseline has some -> dominates.
    assert bench.dominates(one, zero) is True
    # New still zero, baseline also zero -> dominates (0 <= 0).
    assert bench.dominates(zero, zero) is True
    # New has a wrong-match even though it's <= baseline's -> does not dominate.
    assert bench.dominates(two, one) is False
    # New has fewer wrong-matches than baseline but not zero -> does not dominate.
    assert bench.dominates(two, one) is False


def test_replay_apple_rate_math(bench: Any) -> None:
    pool = [
        bench.PoolFilm(1, "Alpha", 1950, None, None),
        bench.PoolFilm(2, "Twin", 1978, None, None),
        bench.PoolFilm(3, "Twin", 1980, None, None),
    ]
    lines = [
        _Owned("Alpha", 1950),  # exact-year match -> film 1
        _Owned("Alpha", 1950),  # exact-year match -> film 1
        _Owned("Twin", 1979),  # equidistant tie between films 2 and 3 -> review
        _Owned("Nothing Here", 2000),  # no candidates at all -> create
    ]
    rates = bench.replay_apple(bench.baseline_matcher_set(), pool, lines)
    assert rates.n == 4
    assert rates.match_pct == 50.0
    assert rates.review_pct == 25.0
    assert rates.create_pct == 25.0
