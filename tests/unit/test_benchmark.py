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
