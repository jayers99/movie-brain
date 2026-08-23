from datetime import date

import pytest

from movie_brain.domain.filters import (
    CHIPS,
    NEW_ARRIVAL_DAYS,
    RECENT_DAYS,
    TOP_IMDB,
    TOP_MC,
    TOP_RT,
    matches,
    thresholds,
)
from movie_brain.domain.models import FilmView

TODAY = date(2026, 8, 19)


def view(**kw) -> FilmView:
    base = dict(
        id=1,
        title="T",
        year=2000,
        director="D",
        url="u",
        language="English",
        imdb=7.0,
        rt=80,
        found=True,
        pending=False,
        leaving_date=None,
        first_seen="2026-01-01",
        my_rating=None,
    )
    base.update(kw)
    return FilmView(**base)


def test_chip_names_are_stable():
    assert CHIPS == (
        "leaving",
        "unrated",
        "mine",
        "pending",
        "top_ratings",
        "recent",
        "departed",
        "new_arrivals",
        "watchlist",
    )


@pytest.mark.parametrize(
    "chip,yes,no",
    [
        ("leaving", view(leaving_date="Aug 31"), view()),
        ("unrated", view(my_rating=None), view(my_rating=0)),
        ("mine", view(my_rating=1), view(my_rating=0)),
        ("pending", view(pending=True, found=None), view()),
        ("pending", view(found=False), view()),
        # any one qualifying score is enough; the `no` views miss on every axis
        # (the view() base is rt 80, imdb 7.0, metacritic None — below every threshold)
        ("top_ratings", view(metacritic=TOP_MC), view(metacritic=TOP_MC - 1)),
        ("top_ratings", view(rt=TOP_RT), view(rt=TOP_RT - 1)),
        ("top_ratings", view(imdb=TOP_IMDB), view(imdb=TOP_IMDB - 0.1)),
        ("recent", view(first_seen="2026-08-01"), view(first_seen="2026-01-01")),
        ("departed", view(departed=True), view()),
    ],
)
def test_single_chip(chip, yes, no):
    assert matches(yes, [chip], TODAY)
    assert not matches(no, [chip], TODAY)


def test_all_null_ratings_never_match_top_ratings():
    assert not matches(view(metacritic=None, rt=None, imdb=None), ["top_ratings"], TODAY)


def test_chips_stack_with_and():
    v = view(leaving_date="Aug 31", my_rating=None)
    assert matches(v, ["leaving", "unrated"], TODAY)
    assert not matches(v, ["leaving", "mine"], TODAY)


def test_no_chips_matches_everything():
    assert matches(view(), [], TODAY)


def test_unknown_chip_raises():
    with pytest.raises(KeyError):
        matches(view(), ["bogus"], TODAY)


def test_thresholds_exposes_constants():
    assert thresholds() == {
        "top_mc": TOP_MC,
        "top_rt": TOP_RT,
        "top_imdb": TOP_IMDB,
        "recent_days": RECENT_DAYS,
        "new_arrival_days": NEW_ARRIVAL_DAYS,
    }


def test_new_arrivals_chip_windows_on_appeared_date(today):
    fresh = view(new_on=[{"source": "max", "name": "HBO Max", "appeared_on": today.isoformat()}])
    stale = view(new_on=[{"source": "max", "name": "HBO Max", "appeared_on": "2026-08-01"}])
    empty = view()
    assert matches(fresh, ["new_arrivals"], today)
    assert not matches(stale, ["new_arrivals"], today)  # 18 days > 14-day window
    assert not matches(empty, ["new_arrivals"], today)


def test_watchlist_chip(today):
    assert matches(view(watchlisted=True), ["watchlist"], today)
    assert not matches(view(), ["watchlist"], today)


def test_thresholds_expose_new_arrival_days():
    assert thresholds()["new_arrival_days"] == 14
