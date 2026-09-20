"""`film_trailer` (migration 028): the worklist, the writer, the read and the merge."""

from __future__ import annotations

from datetime import date

from movie_brain.domain.models import Film
from movie_brain.domain.trailers import APPLE, APPLE_NAME, YOUTUBE, Trailer

D = date(2026, 9, 20)
PICK = [Trailer(YOUTUBE, "trlr0000001", "Official Trailer"), Trailer(APPLE, "https://video-ssl.itunes.apple.com/x.m4v", APPLE_NAME)]


def _film(repo, title, *, tmdb=None, itunes=None):
    fid = repo.create_film(Film(title, 1969, "Dir", ""))
    assert fid is not None
    if tmdb:
        repo.set_external_id(fid, "tmdb", tmdb, D)
    for value in itunes or []:
        repo.set_external_id(fid, "itunes", value, D)
    return fid


def _worklist(repo, **kw):
    return [(t.film_id, t.tmdb_id, t.itunes_id) for t in repo.films_needing_trailers(**kw)]


def test_refresh_asks_the_longest_unasked_first_so_a_limited_refresh_makes_progress(repo):
    old, new, never = _film(repo, "Asked Long Ago", tmdb="1"), _film(repo, "Asked Today", tmdb="2"), _film(repo, "Never", tmdb="3")
    repo.write_trailers(new, 2, None, [], D)
    repo.write_trailers(old, 1, None, [], date(2026, 1, 1))
    assert [t.film_id for t in repo.films_needing_trailers(refresh=True)] == [never, old, new]
    assert [t.film_id for t in repo.films_needing_trailers(2, refresh=True)] == [never, old]


def test_worklist_is_every_live_film_holding_a_tmdb_or_a_store_id(repo):
    both = _film(repo, "Army of Shadows", tmdb="15383", itunes=["900000001"])
    tmdb_only = _film(repo, "The Hitch-Hiker", tmdb="41462")
    store_only = _film(repo, "Store Only", itunes=["900000002"])
    _film(repo, "No Ids")
    gone = _film(repo, "Tombstoned", tmdb="7")
    repo.tombstone_film(gone, D)
    assert _worklist(repo) == [(both, 15383, "900000001"), (tmdb_only, 41462, None), (store_only, None, "900000002")]
    assert len(repo.films_needing_trailers(limit=2)) == 2


def test_a_looked_up_film_leaves_the_worklist_even_when_nothing_was_found(repo):
    found = _film(repo, "Army of Shadows", tmdb="15383", itunes=["900000001"])
    nothing = _film(repo, "The Hitch-Hiker", tmdb="41462")  # no store id: the NULL must compare equal
    repo.write_trailers(found, 15383, "900000001", PICK, D)
    repo.write_trailers(nothing, 41462, None, [], D)
    assert _worklist(repo) == []
    assert repo.film_trailers(found) == [t.to_dict() for t in PICK]
    assert repo.film_trailers(nothing) == []
    assert _worklist(repo, refresh=True) == [(found, 15383, "900000001"), (nothing, 41462, None)]


def test_a_rekey_or_a_store_id_gained_later_asks_again(repo):
    rekeyed = _film(repo, "Re-keyed", tmdb="1")
    gained = _film(repo, "Gained A Store Id", tmdb="2")
    repo.write_trailers(rekeyed, 99, None, PICK[:1], D)   # looked up under the work it no longer holds
    repo.write_trailers(gained, 2, None, [], D)
    repo.set_external_id(gained, "itunes", "900000009", D)
    assert _worklist(repo) == [(rekeyed, 1, None), (gained, 2, "900000009")]


def test_a_film_with_two_store_ids_is_asked_under_the_one_the_drawer_links(repo):
    fid = _film(repo, "Two Products", tmdb="3", itunes=["900000020", "900000010"])
    assert _worklist(repo) == [(fid, 3, "900000010")]  # MIN(value), as `cheapcharts_url` picks
    assert repo.films_needing_trailers()[0].itunes_ids == ("900000010", "900000020")  # …but every product is asked
    repo.write_trailers(fid, 3, "900000010", [], D)
    assert _worklist(repo) == []


def test_write_trailers_replaces_the_row(repo):
    fid = _film(repo, "Army of Shadows", tmdb="15383")
    repo.write_trailers(fid, 15383, None, PICK, D)
    repo.write_trailers(fid, 15383, None, PICK[:1], D)
    assert repo.film_trailers(fid) == [PICK[0].to_dict()]


def test_a_film_never_looked_up_has_no_trailers(repo):
    assert repo.film_trailers(_film(repo, "Never Asked", tmdb="5")) == []


def test_merge_moves_the_trailers_survivor_wins(repo):
    loser, survivor = _film(repo, "Loser", tmdb="10"), _film(repo, "Survivor")
    repo.write_trailers(loser, 10, None, PICK, D)
    repo.merge_film(loser, survivor, D)
    assert repo.film_trailers(survivor) == [t.to_dict() for t in PICK]

    loser2, survivor2 = _film(repo, "Loser Two", tmdb="11"), _film(repo, "Survivor Two", tmdb="12")
    repo.write_trailers(loser2, 11, None, PICK, D)
    repo.write_trailers(survivor2, 12, None, PICK[:1], D)
    report = repo.merge_film(loser2, survivor2, D)
    assert repo.film_trailers(survivor2) == [PICK[0].to_dict()]
    assert report.dropped.get("film_trailer") == 1


def test_summary_counts_films_holding_a_trailer(repo):
    repo.write_trailers(_film(repo, "Has One", tmdb="1"), 1, None, PICK, D)
    repo.write_trailers(_film(repo, "Has None", tmdb="2"), 2, None, [], D)
    assert repo.summary("criterion")["trailers"] == 1
