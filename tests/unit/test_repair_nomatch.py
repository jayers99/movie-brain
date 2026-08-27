from __future__ import annotations

import requests

from movie_brain.application.availability import NO_MATCH_REVIEWED
from movie_brain.application.repair_keys import NOMATCH_ACTIONABLE, audit_nomatch, format_nomatch
from movie_brain.domain.models import Film, ReviewEntry
from movie_brain.domain.thumbprint import Candidate
from movie_brain.infrastructure.database import OmdbRating


def _cand(tt, tid, title, year, director="", votes=5000, in_tmdb=True, in_omdb=True):
    return Candidate(tt, tid, (title,), year, director, 100, votes, "movie", in_tmdb, in_omdb)


class FakeFetcher:
    """`fetch(q)` returns the canned candidates for q.title; unknown titles raise like a network failure."""

    def __init__(self, by_title):
        self.by_title = by_title

    def fetch(self, q):
        if q.title not in self.by_title:
            raise requests.ConnectionError("offline")
        return self.by_title[q.title]


class FakeTmdb:
    def __init__(self, by_imdb=None, years=None):
        self.by_imdb, self.years = by_imdb or {}, years or {}

    def find_by_imdb(self, tt):
        return self.by_imdb.get(tt)

    def movie_year(self, tid):
        return self.years.get(tid)


def _nomatch(repo, today, title, year, director=None, source=None):
    """A found=0 film with an open no-match row; `source` adds a claim of that authority."""
    fid = repo.create_film(Film(title, year, director, ""))
    repo.upsert_tmdb(fid, found=False, looked_up=today)
    repo.upsert_omdb(fid, OmdbRating(None, None, False, None, None), today)
    repo.append_reviews("tmdb", [ReviewEntry("no-match", film_id=fid, detail=f"{title} ({year})")], today)
    if source:
        repo.add_claim(fid, source, f"{source}:{title}", title, year_claimed=year, first_seen=today.isoformat())
    return fid


def test_worklist_is_open_no_match_rows_of_undisposed_films(repo, today):
    a = _nomatch(repo, today, "Bound", 1996)
    b = _nomatch(repo, today, "Gone", 2000)
    repo.tombstone_film(b, today, note="test")
    wl = repo.nomatch_worklist()
    assert [w.film_id for w in wl] == [a] and wl[0].title == "Bound" and wl[0].year == 1996


def test_query_prefers_criterion_claim_then_metacritic_then_apple(repo, today):
    from movie_brain.application.repair_keys import _nomatch_query

    fid = _nomatch(repo, today, "Bound", 1996, director="Lana Wachowski", source="apple-tv")
    repo.add_claim(fid, "metacritic", "bound", "Bound", year_claimed=1997, first_seen="2026-08-01")
    repo.add_claim(fid, "criterion", "https://c/bound", "Bound", year_claimed=1996, first_seen="2026-08-01")
    q = _nomatch_query(repo, repo.nomatch_worklist()[0])
    assert (q.source, q.year, q.director, str(q.year_class)) == ("criterion", 1996, "Lana Wachowski", "database")


def test_apple_claim_maps_to_source_apple_and_carries_runtime(repo, today):
    from movie_brain.application.repair_keys import _nomatch_query

    fid = _nomatch(repo, today, "Bound", 1996)
    repo.add_claim(fid, "apple-tv", "Bound", "Bound", year_claimed=None, runtime_min=108, first_seen="2026-08-01")
    q = _nomatch_query(repo, repo.nomatch_worklist()[0])
    assert (q.source, q.year, q.runtime_min) == ("apple", 1996, 108)  # year falls back to films.year


def test_verdict_table(repo, today):
    match = _nomatch(repo, today, "Bound", 1996, director="Lana Wachowski")
    review = _nomatch(repo, today, "Love", 2024)
    err = _nomatch(repo, today, "Offline", 2001)
    keyed = _nomatch(repo, today, "Scarface", 1983)
    repo.set_external_id(keyed, "imdb", "tt0086250", today)
    unlinked = _nomatch(repo, today, "Ghost", 1990)
    repo.set_external_id(unlinked, "imdb", "tt0000099", today)
    held = _nomatch(repo, today, "Held", 1999, director="Some One")
    other = repo.create_film(Film("Other", 1999, None, ""))
    repo.set_external_id(other, "imdb", "tt0000777", today)
    fetcher = FakeFetcher(
        {
            "Bound": [_cand("tt0115736", 9081, "Bound", 1996, "Lana Wachowski, Lilly Wachowski")],
            "Love": [_cand("tt1", 1, "Love", 2024, votes=50), _cand("tt2", 2, "Love", 2024, votes=60)],
            "Held": [_cand("tt0000777", 777, "Held", 1999, "Some One")],
        }
    )
    got = {g.film_id: g for g in audit_nomatch(repo, fetcher, FakeTmdb({"tt0086250": 111}, {111: 1983}))}
    assert {f: g.verdict for f, g in got.items()} == {
        match: "match", review: "review", err: "conflict", keyed: "keyed", unlinked: "unlinked", held: "conflict",
    }
    assert (got[match].tt, got[match].tmdb_id) == ("tt0115736", 9081)
    assert (got[keyed].tt, got[keyed].tmdb_id) == ("tt0086250", 111)
    assert got[review].verdict_obj is not None and got[review].query is not None
    assert f"held by #{other}" in got[held].detail
    assert "offline" in got[err].detail
    assert format_nomatch(got[match]).startswith("[match]") and "Bound" in format_nomatch(got[match])


def test_tmdb_held_conflict_via_own_imdb_and_via_resolve(repo, today):
    # Path 1: film already holds an imdb tt; find_by_imdb resolves a tmdb id ANOTHER film holds.
    own_imdb = _nomatch(repo, today, "Rope", 1948)
    repo.set_external_id(own_imdb, "imdb", "tt0040746", today)
    tmdb_holder_a = repo.create_film(Film("OtherA", 1948, None, ""))
    repo.set_external_id(tmdb_holder_a, "tmdb", "222", today)

    # Path 2: film has no own imdb tt; resolve() matches an OMDb-only candidate (tmdb_id=None),
    # so the code calls find_by_imdb itself — and that id is held by ANOTHER film.
    via_resolve = _nomatch(repo, today, "Echo", 2010)
    tmdb_holder_b = repo.create_film(Film("OtherB", 2010, None, ""))
    repo.set_external_id(tmdb_holder_b, "tmdb", "333", today)

    fetcher = FakeFetcher(
        {"Echo": [_cand("tt_echo", None, "Echo", 2010, votes=5000, in_tmdb=False, in_omdb=True)]}
    )
    tmdb = FakeTmdb(by_imdb={"tt0040746": 222, "tt_echo": 333})
    got = {g.film_id: g for g in audit_nomatch(repo, fetcher, tmdb)}

    assert got[own_imdb].verdict == "conflict"
    assert f"tmdb 222 held by #{tmdb_holder_a}" in got[own_imdb].detail
    assert got[via_resolve].verdict == "conflict"
    assert f"tmdb 333 held by #{tmdb_holder_b}" in got[via_resolve].detail


def test_open_reviewed_row_is_review_open_and_no_fetcher_is_conflict(repo, today):
    fid = _nomatch(repo, today, "Bound", 1996)
    repo.append_reviews("tmdb", [ReviewEntry(NO_MATCH_REVIEWED, film_id=fid, detail="{}")], today)
    g = audit_nomatch(repo, None, None)
    assert [x.verdict for x in g] == ["review-open"]
    other = _nomatch(repo, today, "Love", 2024)
    g2 = {x.film_id: x.verdict for x in audit_nomatch(repo, None, None)}
    assert g2[other] == "conflict" and set(NOMATCH_ACTIONABLE) == {"keyed", "match", "review"}
