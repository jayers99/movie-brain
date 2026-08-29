"""Injected fakes shared by the curated-list tests (unit + pytest-bdd).

The resolver is driven by a *candidate pool* keyed on the query title rather than by HTTP
mocks: the list importer's correctness is about which forms it asks for and which gate
answers, and a recorded call log is the only way to assert "it did not ask at all".
"""

from __future__ import annotations

import requests

from movie_brain.domain.thumbprint import Candidate


def candidate(tt, tmdb_id, title, year=None, director="", votes=5000, in_tmdb=True, in_omdb=True):
    """`title` is one string, or several — a work's own title plus the ones it is also known by,
    primary first, exactly as `titles` carries them off TMDB/OMDb."""
    titles = (title,) if isinstance(title, str) else tuple(title)
    return Candidate(tt, tmdb_id, titles, year, director, None, votes, "movie", in_tmdb, in_omdb)


class RecordingFetcher:
    """`fetch(q)` returns the canned pool for `q.title` and records every query, in order.

    The order is the point: it is what proves the ladder stops at the first match instead
    of quietly asking every form — and what proves a re-import asks nothing at all about an
    entry that already carries a film_id.
    """

    def __init__(self, by_title=None, offline=(), broken=(), on_fetch=None):
        self.by_title = by_title or {}
        # Fired at the top of every fetch — the one hook a test has into the middle of a run,
        # used to model the catalog changing UNDER a verb that read it once before its loop.
        self.on_fetch = on_fetch
        self.offline = set(offline)
        # Titles whose lookup raises something the resolver does NOT catch — the importer's
        # own per-entry guard is the only thing standing between one bad entry and the run.
        self.broken = set(broken)
        self.queries = []

    @property
    def queried(self):
        return [q.title for q in self.queries]

    def fetch(self, q):
        if self.on_fetch is not None:
            self.on_fetch()
        self.queries.append(q)
        if q.title in self.offline:
            raise requests.ConnectionError("offline")
        if q.title in self.broken:
            raise ValueError(f"unexpected failure for {q.title!r}")
        return self.by_title.get(q.title, [])


class StubTmdb:
    def __init__(self, by_imdb=None, raises=False, years=None):
        self.by_imdb = by_imdb or {}
        self.raises = raises
        # `key_film` reads TMDB's own release year through `movie_year` before writing.
        self.years = years or {}
        self.calls = []

    def find_by_imdb(self, tt):
        self.calls.append(tt)
        if self.raises:
            raise requests.ConnectionError("offline")
        return self.by_imdb.get(tt)

    def movie_year(self, tid):
        if self.raises:
            raise requests.ConnectionError("offline")
        return self.years.get(tid)
