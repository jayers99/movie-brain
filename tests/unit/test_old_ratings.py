"""Old ratings: the file parser, the latest-rental rule, the Rewatch predicate, the summary gap."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from movie_brain.domain.filters import matches
from movie_brain.domain.models import Film, OldRating
from movie_brain.infrastructure.oldratings import OldRatingsFileError, parse_old_ratings

TODAY = date(2026, 9, 19)


def test_parser_keeps_titles_verbatim_and_numbers_rows_from_one():
    rows = parse_old_ratings(
        'rented,rating,title,year,first_capture\n'
        '2005-03-02,3,The Lantren Keeper,1956,20050401\n'
        ',5,"Rivière, La",,\n'
    )
    assert rows == [
        OldRating(1, "The Lantren Keeper", 1956, 3, "2005-03-02"),
        OldRating(2, "Rivière, La", None, 5, None),
    ]


@pytest.mark.parametrize(
    "text",
    [
        "rented,title,year\n2005-03-02,X,1956\n",  # no rating column
        "rating,title\n6,X\n",  # outside 1-5
        "rating,title\n3,\n",  # empty title
        "rating,title,year\n3,X,56\n",  # not four digits
    ],
)
def test_parser_refuses_a_malformed_file(text):
    with pytest.raises(OldRatingsFileError):
        parse_old_ratings(text)


def _film(repo, title, year):
    fid = repo.create_film(Film(title, year, None, ""))
    assert fid is not None
    return fid


def test_a_film_listed_twice_shows_its_latest_rental(repo):
    fid = _film(repo, "Alpha", 1950)
    for row in (OldRating(1, "Alpha", 1950, 5, "2006-02-01"), OldRating(2, "Alfa", 1950, 2, "2004-06-01")):
        repo.upsert_old_rating("ntc", row)
        repo.link_old_rating("ntc", row.line, fid, "resolver", TODAY)
    view = repo.get_view(fid)
    assert view is not None and view.old_rating == {"stars": 5, "rented_on": "2006-02-01"}
    assert [v.old_rating for v in repo.list_views("criterion") if v.id == fid] == [view.old_rating]


def test_a_reimport_refreshes_the_row_and_never_clears_its_link(repo):
    fid = _film(repo, "Alpha", 1950)
    repo.upsert_old_rating("ntc", OldRating(1, "Alpha", 1950, 5, "2006-02-01"))
    repo.link_old_rating("ntc", 1, fid, "hand", TODAY)
    repo.upsert_old_rating("ntc", OldRating(1, "Alpha!", 1951, 4, None))
    assert repo.old_ratings("ntc") == [OldRating(1, "Alpha!", 1951, 4, None, fid, "hand")]


def test_the_foreign_key_is_enforced(repo):
    import sqlite3

    repo.upsert_old_rating("ntc", OldRating(1, "Alpha", 1950, 5, None))
    with pytest.raises(sqlite3.IntegrityError):
        repo.link_old_rating("ntc", 1, 99999, "hand", TODAY)


def test_summary_shows_the_linked_total_gap(repo):
    fid = _film(repo, "Alpha", 1950)
    repo.upsert_old_rating("ntc", OldRating(1, "Alpha", 1950, 5, None))
    repo.upsert_old_rating("ntc", OldRating(2, "Nowhere", 1960, 1, None))
    repo.link_old_rating("ntc", 1, fid, "resolver", TODAY)
    s = repo.summary("criterion")
    assert (s["old_ratings_linked"], s["old_ratings"]) == (1, 2)


def test_rewatch_is_an_old_five_star_with_no_rating_today(repo):
    fid = _film(repo, "Alpha", 1950)
    view = repo.get_view(fid)
    assert view is not None
    loved = replace(view, old_rating={"stars": 5, "rented_on": None})
    assert matches(loved, ["rewatch"], TODAY)
    assert not matches(replace(loved, my_rating=8), ["rewatch"], TODAY)  # served: rated today
    assert not matches(replace(view, old_rating={"stars": 4, "rented_on": None}), ["rewatch"], TODAY)
    assert not matches(view, ["rewatch"], TODAY)
