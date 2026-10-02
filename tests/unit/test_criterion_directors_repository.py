"""The directors worklist (spec 2026-10-01 D8): films holding a Criterion mediaid whose director
the owner sees NOWHERE — no `films.director` and no OMDb director (the dashboard shows
`COALESCE(films.director, OMDb's)`). Payload shapes are real: `tests/fixtures/omdb/`."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from movie_brain.domain.models import Film, OmdbRating

OMDB = Path(__file__).parent.parent / "fixtures" / "omdb"
D = date(2026, 10, 3)


def _film(repo, title, mediaids, *, director=None, omdb=None):
    fid = repo.create_film(Film(title, 2000, director, ""))
    assert fid is not None
    for m in mediaids:
        repo.set_external_id(fid, "criterion", m, D)
    if omdb == "not-found":  # Keeping Secrets Will Destroy You #735: found = 0, payload NULL
        repo.upsert_omdb(fid, OmdbRating(None, None, False), D)
    elif omdb is not None:
        repo.upsert_omdb(fid, OmdbRating(5.3, None, True, payload=(OMDB / omdb).read_text()), D)
    return fid


def _director(repo, fid):
    with sqlite3.connect(repo.db_path) as c:
        return c.execute("SELECT director FROM films WHERE id = ?", (fid,)).fetchone()[0]


def test_no_omdb_row_a_not_found_row_and_na_all_show_no_director(repo):
    a = _film(repo, "No Omdb Row", ["aaaaaaa1"])
    b = _film(repo, "Keeping Secrets Will Destroy You", ["3ehCWylD"], omdb="not-found")
    c = _film(repo, "The Horse in Focus", ["5pVD2vhU"], omdb="the-horse-in-focus.json")
    got = repo.films_needing_criterion_director()
    assert [(t.film_id, t.mediaid) for t in got] == [(a, "aaaaaaa1"), (b, "3ehCWylD"), (c, "5pVD2vhU")]
    assert got[1].title == "Keeping Secrets Will Destroy You"


def test_a_director_anyone_can_see_keeps_the_film_off_the_worklist(repo):
    _film(repo, "Nadja", ["nadjaXX1"], director="Michael Almereyda")
    _film(repo, "Mistress Dispeller", ["vuGxAj8b"], omdb="mistress-dispeller.json")
    assert repo.films_needing_criterion_director() == []


def test_an_old_link_is_not_a_mediaid_so_nothing_qualifies_before_the_bridge(repo):
    _film(repo, "Trio", ["https://www.criterionchannel.com/trio"])
    _film(repo, "No Criterion Id", [])
    assert repo.films_needing_criterion_director() == []


def test_a_film_holding_two_mediaids_is_asked_once_by_the_lowest(repo):
    fid = _film(repo, "Two Cuts", ["dYbj5nMq", "5pVD2vhU"])
    got = repo.films_needing_criterion_director()
    assert [(t.film_id, t.mediaid) for t in got] == [(fid, "5pVD2vhU")]


def test_a_hidden_holder_is_never_asked(repo):
    fid = _film(repo, "Hidden", ["hiddenX1"])
    repo.tombstone_film(fid, D)
    assert repo.films_needing_criterion_director() == []


def test_the_write_lands_only_in_a_blank_no_one_fills(repo):
    a = _film(repo, "Keeping Secrets Will Destroy You", ["3ehCWylD"], omdb="not-found")
    e = _film(repo, "Mistress Dispeller", ["vuGxAj8b"], omdb="mistress-dispeller.json")
    assert repo.fill_criterion_director(a, "Ryan Daly, Will Oldham") is True
    assert _director(repo, a) == "Ryan Daly, Will Oldham"
    assert repo.fill_criterion_director(a, "X") is False  # ours now: never overwritten
    assert _director(repo, a) == "Ryan Daly, Will Oldham"
    assert repo.fill_criterion_director(e, "X") is False  # OMDb's shows: never shadowed
    assert _director(repo, e) is None
