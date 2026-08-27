import gzip
import json

import pytest

from movie_brain.domain.thumbprint import make_query
from movie_brain.infrastructure.thumbprint_fetch import CacheMiss, CandidateCache, CandidateFetcher, k_o


def test_read_only_cache_raises_on_miss():
    with pytest.raises(CacheMiss):
        CandidateCache({}, read_only=True).get("ts:x|None", lambda: None)


def test_cache_round_trip_gz(tmp_path):
    p = tmp_path / "c.json.gz"
    c = CandidateCache({}, p)
    assert c.get("k", lambda: {"v": 1}) == {"v": 1} and c.misses == 1
    c.save()
    with gzip.open(p, "rt") as f:
        assert json.load(f)["k"] == {"v": 1}
    assert CandidateCache.load(p, read_only=True).get("k", lambda: None) == {"v": 1}


def test_omdb_keys_never_carry_apikey_or_t():
    assert k_o(i="tt1") == 'o:{"i": "tt1"}'


def test_fetcher_unifies_on_tt_from_cache():
    data = {
        "ts:Rear Window|None": [{"id": 567, "title": "Rear Window"}],
        "ts:Rear Window|1954": [],
        "tsy:Rear Window|1954": [],
        "td:567": {
            "id": 567,
            "title": "Rear Window",
            "original_title": "Rear Window",
            "release_date": "1954-08-01",
            "runtime": 112,
            "external_ids": {"imdb_id": "tt0047396"},
            "credits": {"crew": [{"job": "Director", "name": "Alfred Hitchcock"}]},
            "alternative_titles": {"titles": []},
        },
        'o:{"s": "Rear Window"}': {"Search": [{"imdbID": "tt0047396"}]},
        'o:{"s": "Rear Window", "y": "1954"}': {"Search": []},
        'o:{"i": "tt0047396"}': {
            "imdbID": "tt0047396",
            "Title": "Rear Window",
            "Year": "1954",
            "Director": "Alfred Hitchcock",
            "imdbVotes": "500,000",
            "Type": "movie",
            "Runtime": "112 min",
        },
    }
    cands = CandidateFetcher(CandidateCache(data, read_only=True), None, None).fetch(
        make_query("Rear Window", 1954, "criterion")
    )
    assert [c.tt for c in cands] == ["tt0047396"]
    c = cands[0]
    assert c.in_tmdb and c.in_omdb and c.votes == 500000 and c.directors == "Alfred Hitchcock" and c.runtime_min == 112


def test_fetcher_without_clients_raises_on_miss():
    with pytest.raises(CacheMiss):
        CandidateFetcher(CandidateCache({}, read_only=True), None, None).fetch(make_query("X", 2000, "criterion"))


def test_fetcher_fetches_article_folded_hit_beyond_top_three():
    # TMDB search for "The Bride of Frankenstein" returns four irrelevant hits before the
    # real (article-folded) match at position 4 (j=3) — plausible() must widen past j < 3.
    data = {
        "ts:The Bride of Frankenstein|None": [
            {"id": 1, "title": "Something Else Entirely"},
            {"id": 2, "title": "Another Movie"},
            {"id": 3, "title": "Random Title"},
            {"id": 4, "title": "Fourth Filler"},
            {"id": 999, "title": "Bride of Frankenstein", "original_title": "Bride of Frankenstein"},
        ],
        "td:999": {
            "id": 999,
            "title": "Bride of Frankenstein",
            "original_title": "Bride of Frankenstein",
            "release_date": "1935-04-22",
            "runtime": 75,
            "external_ids": {"imdb_id": "tt0026138"},
            "credits": {"crew": [{"job": "Director", "name": "James Whale"}]},
            "alternative_titles": {"titles": []},
        },
        'o:{"s": "The Bride of Frankenstein"}': {"Search": []},
    }
    cands = CandidateFetcher(CandidateCache(data, read_only=True), None, None).fetch(
        make_query("The Bride of Frankenstein", None, "criterion")
    )
    assert any(c.tt == "tt0026138" and c.in_tmdb for c in cands)
