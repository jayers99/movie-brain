# tests/unit/test_watchlist_order.py
"""Backlog 46 — the watchlist's hand order (brief 2026-10-02-watchlist-order, amendment 1.1)."""
import sqlite3
from datetime import date

from movie_brain.domain.models import Film, OmdbRating
from movie_brain.infrastructure.database import Repository

TODAY = date(2026, 10, 2)


def _film(repo: Repository, title: str, mc: int | None = None, rt: int | None = None, imdb: float | None = None) -> int:
    fid = repo.create_film(Film(title, 1950, "Dir", ""))
    assert fid is not None
    repo.upsert_omdb(fid, OmdbRating(imdb, rt, True, "English", "{}", metacritic=mc), TODAY)
    return fid


def _star_all(repo: Repository, *ids: int) -> None:
    for fid in reversed(ids):          # each fresh star goes to the top, so star bottom-first
        assert repo.toggle_watchlist(fid, TODAY).watchlisted


def test_a_fresh_star_goes_to_the_top(repo):
    a, b = _film(repo, "A"), _film(repo, "B")
    repo.toggle_watchlist(a, TODAY)
    repo.toggle_watchlist(b, TODAY)
    assert repo.watchlist_order() == [b, a]


def test_an_unstar_closes_the_gap_and_names_the_film_below(repo):
    a, b, c = _film(repo, "A"), _film(repo, "B"), _film(repo, "C")
    _star_all(repo, a, b, c)
    res = repo.toggle_watchlist(b, TODAY)
    assert (res.watchlisted, res.below) == (False, c)
    assert repo.watchlist_order() == [a, c]
    assert [v.watchlist_position for v in repo.list_views("criterion", TODAY) if v.watchlisted] == [1, 2]
    assert repo.toggle_watchlist(c, TODAY).below is None   # it was last


def test_a_put_back_returns_above_its_neighbour_even_after_other_stars(repo):
    a, b, c, d = (_film(repo, t) for t in "ABCD")
    _star_all(repo, a, b, c)
    below = repo.toggle_watchlist(b, TODAY).below            # b sat above c
    repo.toggle_watchlist(d, TODAY)                          # a fresh star in between: d goes first
    repo.toggle_watchlist(b, TODAY, put_back=True, before=below)
    assert repo.watchlist_order() == [d, a, b, c]


def test_put_back_above_a_vanished_neighbour_goes_last(repo):
    a, b, c = (_film(repo, t) for t in "ABC")
    _star_all(repo, a, b, c)
    below = repo.toggle_watchlist(b, TODAY).below            # c
    repo.toggle_watchlist(c, TODAY)                          # c leaves too
    repo.toggle_watchlist(b, TODAY, put_back=True, before=below)
    assert repo.watchlist_order() == [a, b]


def test_move_steps_past_one_neighbour_and_nothing_else_changes_places(repo):
    ids = [_film(repo, t) for t in ("Henry", "OotP", "YF", "SomeCame", "LotF")]
    _star_all(repo, *ids)
    henry, ootp, yf, some, lotf = ids
    # Under a chip YF and SomeCame are hidden: OotP's visible neighbour below is LotF.
    assert repo.move_watchlist(ootp, lotf, "down") == [henry, yf, some, lotf, ootp]
    assert repo.move_watchlist(ootp, henry, "up") == [ootp, henry, yf, some, lotf]


def test_move_steps_over_a_film_the_client_cannot_see(repo):
    ids = [_film(repo, t) for t in ("YF", "SomeCame", "LotF")]
    _star_all(repo, *ids)
    yf, some, lotf = ids
    assert repo.move_watchlist(lotf, yf, "up") == [lotf, yf, some]


def test_move_refuses_a_film_off_the_watchlist(repo):
    a, b, c = (_film(repo, t) for t in "ABC")
    _star_all(repo, a, b)
    assert repo.move_watchlist(a, c, "down") is None
    assert repo.move_watchlist(c, a, "up") is None
    assert repo.move_watchlist(a, a, "up") is None
    assert repo.watchlist_order() == [a, b]


def test_merge_keeps_the_order_dense(repo):
    a, b, c = (_film(repo, t) for t in "ABC")
    _star_all(repo, a, b, c)
    d = _film(repo, "D")                       # unstarred survivor takes the loser's place
    repo.merge_film(b, d, TODAY)
    assert repo.watchlist_order() == [a, d, c]
    repo.merge_film(a, c, TODAY)               # starred survivor keeps its own place; the gap closes
    assert repo.watchlist_order() == [d, c]
    with sqlite3.connect(repo.db_path) as conn:
        assert [r[0] for r in conn.execute("SELECT position FROM watchlist ORDER BY position")] == [1, 2]


def test_migration_033_seeds_todays_default_order(tmp_path):
    db = tmp_path / "movie-brain.db"
    repo = Repository(db)
    lotf = _film(repo, "Lord of the Flies", mc=67, rt=92, imdb=6.9)
    intol = _film(repo, "Intolerance", mc=99, rt=98, imdb=7.7)
    moon = _film(repo, "Moonlight", mc=99, rt=98, imdb=7.4)
    henry = _film(repo, "The Wonderful Story of Henry Sugar", mc=85, rt=95, imdb=7.4)
    ootp = _film(repo, "Out of the Past", mc=85, rt=87, imdb=8.0)
    nomc = _film(repo, "Ugetsu", mc=None, rt=100, imdb=8.1)
    for fid in (lotf, intol, moon, henry, ootp, nomc):
        repo.toggle_watchlist(fid, TODAY)
    with sqlite3.connect(db) as conn:          # rewind to schema 32: drop the column, forget 033
        conn.execute("ALTER TABLE watchlist DROP COLUMN position")
        conn.execute("DELETE FROM schema_version WHERE version = 33")
    Repository(db, migrate=True)
    assert Repository(db).watchlist_order() == [intol, moon, henry, ootp, lotf, nomc]
