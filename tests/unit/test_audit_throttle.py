"""Finding 3 (2026-08-24 data-audit final-review): the per-film TMDB facts fetch must throttle
after a failure exactly like it throttles after a success, or a run of 500s hammers the API."""

from __future__ import annotations

from datetime import date

import requests
import responses

from movie_brain.application.audit import run_audit
from movie_brain.domain.models import Film
from movie_brain.infrastructure.tmdb import TMDB_API, TmdbClient

TODAY = date(2026, 8, 19)


def _linked_film(repo, title: str, tmdb_id: int) -> None:
    repo.record_catalog("criterion", [Film(title, 1950, None, f"https://c/{title.lower()}")], TODAY)
    fid = repo.film_id_by_key(f"{title.lower()} (1950)")
    repo.set_external_id(fid, "tmdb", str(tmdb_id), TODAY)


def test_sleep_runs_after_both_a_success_and_a_failed_fetch(repo, monkeypatch):
    _linked_film(repo, "Alpha", 1)
    _linked_film(repo, "Bravo", 2)

    calls: list[float] = []
    monkeypatch.setattr("movie_brain.application.audit.time.sleep", lambda s: calls.append(s))

    with responses.RequestsMock(assert_all_requests_are_fired=True) as rs:
        rs.get(
            f"{TMDB_API}/movie/1",
            json={
                "title": "Alpha", "original_title": "Alpha", "release_date": "1950-01-01",
                "runtime": 90, "alternative_titles": {"titles": []}, "external_ids": {"imdb_id": "tt1"},
            },
        )
        rs.get(f"{TMDB_API}/movie/2", status=500, body="boom")
        client = TmdbClient("tok", session=requests.Session())
        report = run_audit(repo, TODAY, tmdb=client, delay_s=0.01, log=lambda m: None)

    assert (report.facts_fetched, report.facts_failed) == (1, 1)
    assert calls == [0.01, 0.01]  # throttled after the success AND after the failure
