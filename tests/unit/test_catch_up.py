"""The catch-up chain (owner ruling 2026-09-20): every film gets its FULL enrichment when it is
added — credits, the search vector, the store id, the trailer — instead of waiting for someone to
run four verbs by hand. Each step is the verb's own use case, run with apply; the order matters."""

from __future__ import annotations

from datetime import date

import pytest

from movie_brain.application import catch_up as module
from movie_brain.application.catch_up import catch_up
from movie_brain.application.cheapcharts import ResolveReport
from movie_brain.application.embed import EmbedReport
from movie_brain.application.enrich import EnrichReport
from movie_brain.application.trailers import TrailerReport

D = date(2026, 9, 20)


@pytest.fixture
def calls(monkeypatch):
    seen: list[tuple[str, dict]] = []

    def fake(name, report):
        def run(*args, **kw):
            seen.append((name, kw))
            return report
        return run

    monkeypatch.setattr(module, "enrich_credits", fake("credits", EnrichReport(scanned=3, enriched=3)))
    monkeypatch.setattr(module, "embed_films", fake("embed", EmbedReport(scanned=3, embedded=2, skipped_no_prose=1)))
    monkeypatch.setattr(module, "resolve_itunes_ids", fake("store", ResolveReport(scanned=3, resolved=1)))
    monkeypatch.setattr(module, "enrich_trailers", fake("trailers", TrailerReport(scanned=3, with_youtube=2, nothing=1)))
    return seen


def test_the_full_boat_runs_in_order_and_applies(repo, calls):
    report = catch_up(repo, D, tmdb=object(), cheapcharts=object(), itunes=object(), embedder=object(), log=lambda m: None)
    # The store id comes BEFORE the trailer (Apple's preview is found by store id), credits before
    # the vector (the vector is made from the prose credits bring).
    assert [name for name, _ in calls] == ["credits", "embed", "store", "trailers"]
    assert all(kw["apply"] is True for _, kw in calls)
    assert (report.credits.enriched, report.embedded.embedded, report.store.resolved, report.trailers.with_youtube) == (3, 2, 1, 2)
    assert report.line() == "credits: 3 · vectors: 2 · store ids: 1 of 3 · trailers: 2 of 3"


def test_a_missing_dependency_skips_its_steps_and_says_so(repo, calls):
    logged: list[str] = []
    report = catch_up(repo, D, tmdb=None, cheapcharts=object(), itunes=object(), embedder=None, log=logged.append)
    assert [name for name, _ in calls] == ["store"]
    assert report.credits is None and report.embedded is None and report.trailers is None
    assert any("no TMDB token" in m for m in logged) and any("semantic" in m for m in logged)
    assert report.line() == "credits: skipped · vectors: skipped · store ids: 1 of 3 · trailers: skipped"


def test_one_step_failing_never_stops_the_others(repo, calls, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("cheapcharts exploded")

    monkeypatch.setattr(module, "resolve_itunes_ids", boom)
    logged: list[str] = []
    report = catch_up(repo, D, tmdb=object(), cheapcharts=object(), itunes=object(), embedder=object(), log=logged.append)
    assert [name for name, _ in calls] == ["credits", "embed", "trailers"]
    assert report.store is None and any("store ids failed" in m and "exploded" in m for m in logged)
