"""Repository writes and reads for the viewing log (brief 2.2, migration 031)."""

from __future__ import annotations

import sqlite3
from datetime import date

import pytest

from movie_brain.domain.models import Film, OldRating

TODAY = date(2026, 9, 27)


def _q(repo, sql, *args):
    conn = sqlite3.connect(repo.db_path)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


@pytest.fixture
def blue(repo):
    fid = repo.create_film(Film("The Blue Angel", 1930, None, ""))
    assert fid is not None
    repo.register_provider(1899, "Kino Film Collection")  # slug kino-film-collection
    return fid


def test_add_viewing_writes_viewing_artefact_rating_and_clears_unseen(repo, blue):
    repo.set_unseen(blue, True, TODAY)
    w = repo.add_viewing(blue, TODAY, "kino-film-collection", "pretty good", 6, TODAY)
    assert w.created is True and w.note_count == 1
    assert _q(repo, "SELECT film_id, watched_on, service, logged_on FROM viewing") == [(blue, "2026-09-27", "kino-film-collection", "2026-09-27")]
    assert _q(repo, "SELECT kind, text FROM artefact WHERE viewing_id = ?", w.viewing_id) == [("dictation", "pretty good")]
    assert _q(repo, "SELECT score FROM my_ratings WHERE film_id = ?", blue) == [(6,)]
    assert _q(repo, "SELECT 1 FROM unseen WHERE film_id = ?", blue) == []


def test_second_add_same_day_appends_and_never_overwrites_the_service(repo, blue):
    repo.register_provider(8, "Kanopy")
    first = repo.add_viewing(blue, TODAY, "kino-film-collection", "first", None, TODAY)
    second = repo.add_viewing(blue, TODAY, "kanopy", "second", 7, TODAY)
    assert second.viewing_id == first.viewing_id and second.created is False and second.note_count == 2
    assert _q(repo, "SELECT service FROM viewing") == [("kino-film-collection",)]
    assert _q(repo, "SELECT score FROM my_ratings WHERE film_id = ?", blue) == [(7,)]


def test_second_add_fills_a_service_the_line_had_none_of(repo, blue):
    repo.add_viewing(blue, TODAY, None, "first", None, TODAY)
    repo.add_viewing(blue, TODAY, "kino-film-collection", "second", None, TODAY)
    assert _q(repo, "SELECT service FROM viewing") == [("kino-film-collection",)]


def test_no_rate_leaves_the_standing_rating_alone(repo, blue):
    repo.set_rating(blue, 9, TODAY)
    repo.add_viewing(blue, TODAY, None, "still good", None, TODAY)
    assert _q(repo, "SELECT score FROM my_ratings WHERE film_id = ?", blue) == [(9,)]


def test_viewings_for_is_newest_first_with_artefacts(repo, blue):
    repo.add_viewing(blue, date(2026, 9, 21), "kino-film-collection", "monday", None, TODAY)
    repo.add_viewing(blue, TODAY, None, "today a", None, TODAY)
    repo.add_viewing(blue, TODAY, None, "today b", None, TODAY)
    vs = repo.viewings_for(blue)
    assert [v["watched_on"] for v in vs] == ["2026-09-27", "2026-09-21"]
    assert vs[1]["service_name"] == "Kino Film Collection"
    assert [a["text"] for a in vs[0]["artefacts"]] == ["today a", "today b"]
    assert vs[0]["service"] is None and vs[0]["service_name"] is None


def test_remove_viewing_takes_its_artefacts_and_leaves_rating_and_unseen(repo, blue):
    w = repo.add_viewing(blue, TODAY, None, "oops", 5, TODAY)
    gone = repo.remove_viewing(w.viewing_id)
    assert gone == {"film_id": blue, "watched_on": "2026-09-27", "notes": 1}
    assert _q(repo, "SELECT COUNT(*) FROM viewing")[0][0] == 0
    assert _q(repo, "SELECT COUNT(*) FROM artefact")[0][0] == 0
    assert _q(repo, "SELECT score FROM my_ratings WHERE film_id = ?", blue) == [(5,)]
    assert repo.remove_viewing(w.viewing_id) is None


def test_remove_artefact_drops_one_note_and_keeps_the_viewing(repo, blue):
    w = repo.add_viewing(blue, TODAY, None, "one", None, TODAY)
    repo.add_viewing(blue, TODAY, None, "two", None, TODAY)
    repo.add_viewing(blue, TODAY, None, "three", None, TODAY)
    assert repo.remove_artefact(w.viewing_id, 2) == {"film_id": blue, "watched_on": "2026-09-27", "notes_left": 2}
    assert [a["text"] for a in repo.viewings_for(blue)[0]["artefacts"]] == ["one", "three"]
    assert repo.remove_artefact(w.viewing_id, 5) is None
    assert repo.remove_artefact(999, 1) is None


def test_list_viewings_since_and_for_a_film(repo, blue):
    cuba = repo.create_film(Film("I Am Cuba", 1964, None, ""))
    repo.set_rating(cuba, 9, TODAY)
    repo.add_viewing(blue, date(2026, 8, 30), None, "august", None, TODAY)
    repo.add_viewing(blue, date(2026, 9, 21), None, "monday", None, TODAY)
    repo.add_viewing(cuba, TODAY, None, "cuba", None, TODAY)
    rows = repo.list_viewings(since=date(2026, 9, 1))
    assert [(r["title"], r["watched_on"], r["notes"], r["my_rating"]) for r in rows] == [("I Am Cuba", "2026-09-27", 1, 9), ("The Blue Angel", "2026-09-21", 1, None)]
    assert [r["watched_on"] for r in repo.list_viewings(film_id=blue)] == ["2026-09-21", "2026-08-30"]
    assert repo.list_viewings(since=date(2027, 1, 1)) == []


def test_old_ratings_for_collapses_a_duplicate_row_and_is_newest_first(repo, blue):
    repo.upsert_old_rating("ntc", OldRating(28, "Love & Anarchy", 1973, 5, "2004-06-22"))
    repo.upsert_old_rating("ntc", OldRating(29, "Love and Anarchy", 1973, 5, "2004-06-22"))
    repo.upsert_old_rating("ntc", OldRating(30, "Love and Anarchy", 1973, 4, "2006-01-05"))
    for line in (28, 29, 30):
        repo.link_old_rating("ntc", line, blue, "hand", TODAY)
    assert repo.old_ratings_for(blue) == [{"stars": 4, "rented_on": "2006-01-05"}, {"stars": 5, "rented_on": "2004-06-22"}]


def test_merge_repoints_viewings_and_folds_a_same_date_collision(repo):
    survivor = repo.create_film(Film("Godzilla", 1954, None, ""))
    loser = repo.create_film(Film("Gojira", 1954, None, ""))
    repo.add_viewing(loser, date(2026, 9, 20), None, "loser only", None, TODAY)
    repo.add_viewing(loser, TODAY, None, "loser today", None, TODAY)
    repo.add_viewing(survivor, TODAY, None, "survivor today", None, TODAY)
    report = repo.merge_film(loser, survivor, TODAY)
    vs = repo.viewings_for(survivor)
    assert [v["watched_on"] for v in vs] == ["2026-09-27", "2026-09-20"]
    # Artefacts on the same viewing sort by added_on, id; both TODAY so order is by id.
    assert [a["text"] for a in vs[0]["artefacts"]] == ["loser today", "survivor today"]
    # added_on is immutable: preserved from original insertion (never rewritten by merge).
    assert [a["added_on"] for a in vs[0]["artefacts"]] == ["2026-09-27", "2026-09-27"]
    assert repo.viewings_for(loser) == []
    assert report.moved.get("viewing") == 1 and report.moved.get("artefact") == 1


def test_service_name_and_canonical_titles(repo, blue):
    assert repo.service_name("kino-film-collection") == "Kino Film Collection"
    assert repo.service_name("criterion-channel") is None
    ghost = repo.create_film(Film("Ghost Row", 1999, None, ""))
    repo.tombstone_film(ghost, TODAY)
    ids = {row[0] for row in repo.canonical_titles()}
    assert blue in ids and ghost not in ids
    assert next(row for row in repo.canonical_titles() if row[0] == blue) == (blue, "The Blue Angel", 1930, None)


from datetime import datetime, timedelta


def test_view_carries_last_watched_and_viewing_count(repo, blue):
    assert repo.get_view(blue, TODAY).viewing_count == 0 and repo.get_view(blue, TODAY).last_watched is None
    repo.add_viewing(blue, date(2026, 9, 21), None, "monday", None, TODAY)
    repo.add_viewing(blue, TODAY, None, "today", None, TODAY)
    v = repo.get_view(blue, TODAY)
    assert (v.last_watched, v.viewing_count) == ("2026-09-27", 2)
    listed = {x.id: x for x in repo.list_views("criterion", TODAY)}
    assert (listed[blue].last_watched, listed[blue].viewing_count) == ("2026-09-27", 2)


def test_a_viewed_film_is_visible_even_when_unrated_and_departed(repo):
    """The current-or-rated filter widens to current-or-rated-or-viewed (finding 14)."""
    repo.record_catalog("criterion", [Film("Cool Hand Luke", 1967, "Stuart Rosenberg", "https://c/luke"), Film("Stay", 1970, "S", "https://c/stay")], date(2026, 8, 1))
    repo.record_catalog("criterion", [Film("Stay", 1970, "S", "https://c/stay")], TODAY)  # Luke departs
    luke = repo.film_id_by_key("cool hand luke (1967)")
    assert luke not in {v.id for v in repo.list_views("criterion", TODAY)}
    repo.add_viewing(luke, TODAY, None, "watched it anyway", None, TODAY)
    assert luke in {v.id for v in repo.list_views("criterion", TODAY)}


def test_drawer_signal_is_trusted_for_two_minutes(repo, blue):
    now = datetime(2026, 9, 27, 21, 0, 0)
    assert repo.drawer_film(now) is None
    repo.set_drawer_film(blue, now)
    assert repo.drawer_film(now + timedelta(seconds=119)) == blue
    assert repo.drawer_film(now + timedelta(seconds=121)) is None
    repo.set_drawer_film(None, now)
    assert repo.drawer_film(now) is None
