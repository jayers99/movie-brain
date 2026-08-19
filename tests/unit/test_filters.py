from datetime import date

import pytest

from movie_brain.domain.filters import CHIPS, RECENT_DAYS, TOP_IMDB, TOP_RT, matches, thresholds
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
    assert CHIPS == ("leaving", "unrated", "mine", "not_interested", "pending", "top_rt", "top_imdb", "recent")


@pytest.mark.parametrize(
    "chip,yes,no",
    [
        ("leaving", view(leaving_date="Aug 31"), view()),
        ("unrated", view(my_rating=None), view(my_rating=0)),
        ("mine", view(my_rating=1), view(my_rating=0)),
        ("not_interested", view(my_rating=0), view(my_rating=5)),
        ("pending", view(pending=True, found=None), view()),
        ("pending", view(found=False), view()),
        ("top_rt", view(rt=TOP_RT), view(rt=TOP_RT - 1)),
        ("top_imdb", view(imdb=TOP_IMDB), view(imdb=7.9)),
        ("recent", view(first_seen="2026-08-01"), view(first_seen="2026-01-01")),
    ],
)
def test_single_chip(chip, yes, no):
    assert matches(yes, [chip], TODAY)
    assert not matches(no, [chip], TODAY)


def test_null_ratings_never_match_top_chips():
    assert not matches(view(rt=None), ["top_rt"], TODAY)
    assert not matches(view(imdb=None), ["top_imdb"], TODAY)


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
    assert thresholds() == {"top_rt": TOP_RT, "top_imdb": TOP_IMDB, "recent_days": RECENT_DAYS}
