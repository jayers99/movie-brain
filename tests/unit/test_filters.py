from datetime import date

import pytest

from movie_brain.domain.filters import (
    CHIPS,
    MIN_LISTS,
    NEW_ARRIVAL_DAYS,
    canon_score,
    is_canon,
    matches,
    reachable,
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
    # URL state encodes these keys; the ones that predate the 2026-09-07 bar redesign keep
    # their names so saved links still resolve.
    assert CHIPS == (
        "reachable",
        "unreachable",
        "unrated",
        "mine",
        "criterion",
        "leaving",
        "criterion_new",
        "not_criterion",
        "watchlist",
        "owned",
        "not_owned",
        "multi_list",
    )


SVOD = {"name": "MUBI", "subscribed": False, "kind": "svod", "quality": 1, "has_apple_app": False}
STORE = {"name": "Apple TV Store (iTunes)", "subscribed": True, "kind": "store", "quality": 1, "has_apple_app": True}


@pytest.mark.parametrize(
    "chip,yes,no",
    [
        ("leaving", view(leaving_date="Aug 31"), view()),
        ("unrated", view(my_rating=None), view(my_rating=0)),
        ("mine", view(my_rating=1), view(my_rating=0)),
        ("criterion", view(criterion=True, departed=False), view(criterion=True, departed=True)),
        ("criterion", view(criterion=True), view(criterion=False)),
        ("not_criterion", view(criterion=False), view(criterion=True, departed=False)),
        ("not_criterion", view(criterion=True, departed=True), view(criterion=True)),  # departed = not on the Channel now
        ("reachable", view(criterion=True, departed=False), view(criterion=False)),
        ("reachable", view(criterion=False, services=[SVOD]), view(criterion=False, services=[])),
        ("reachable", view(criterion=False, services=[STORE]), view(criterion=True, departed=True)),
        ("unreachable", view(criterion=False, services=[]), view(criterion=False, services=[SVOD])),
    ],
)
def test_single_chip(chip, yes, no):
    assert matches(yes, [chip], TODAY)
    assert not matches(no, [chip], TODAY)


def test_reachable_counts_owned_but_not_a_judgement():
    """Owned IS watchable (and proof of an Apple store presence TMDB missed); rated and
    watchlisted are judgements, not ways to watch. An unsubscribed service still counts."""
    assert reachable(view(criterion=False, services=[], owned=True)) is True
    judged = view(criterion=False, services=[], owned=False, my_rating=9, watchlisted=True)
    assert reachable(judged) is False
    assert matches(judged, ["unreachable"], TODAY)
    assert reachable(view(criterion=False, services=[SVOD])) is True


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
        "new_arrival_days": NEW_ARRIVAL_DAYS,
        "multi_list": MIN_LISTS,
    }


def test_criterion_new_chip_counts_only_criterion_arrivals_this_month(today):
    fresh = view(new_on=[{"source": "criterion", "name": "Criterion Channel", "appeared_on": today.isoformat()}])
    other = view(new_on=[{"source": "max", "name": "HBO Max", "appeared_on": today.isoformat()}])
    stale = view(new_on=[{"source": "criterion", "name": "Criterion Channel", "appeared_on": "2026-06-01"}])
    assert matches(fresh, ["criterion_new"], today)
    assert not matches(other, ["criterion_new"], today)  # an arrival elsewhere is not Criterion-new
    assert not matches(stale, ["criterion_new"], today)  # older than the 30-day window
    assert not matches(view(), ["criterion_new"], today)


def test_watchlist_chip(today):
    assert matches(view(watchlisted=True), ["watchlist"], today)
    assert not matches(view(), ["watchlist"], today)


def test_thresholds_expose_new_arrival_days():
    assert thresholds()["new_arrival_days"] == 30  # "new" means this month


def test_owned_chip_matches_owned_views():
    assert matches(view(owned=True), ["owned"], TODAY)
    assert not matches(view(owned=False), ["owned"], TODAY)


def test_not_owned_chip_excludes_owned_views():
    assert matches(view(owned=False), ["not_owned"], TODAY)
    assert not matches(view(owned=True), ["not_owned"], TODAY)


def test_on_a_list_chip_matches_one_or_more_lists():
    # The chip KEY stays `multi_list` (URL state), but the question it asks is now "on a list".
    two = view(lists=[{"slug": "a"}, {"slug": "b"}])
    one = view(lists=[{"slug": "a"}])
    none = view()
    assert matches(two, ["multi_list"], TODAY)
    assert matches(one, ["multi_list"], TODAY)
    assert not matches(none, ["multi_list"], TODAY)


def test_canon_score_gives_a_list_leader_the_full_trust():
    v = view(lists=[{"trust": 10, "rank": 1, "rank_label": None, "size": 100, "ordered": True}])
    assert canon_score(v) == pytest.approx(10.0)


def test_canon_score_decays_to_near_zero_at_the_end_of_a_list():
    v = view(lists=[{"trust": 10, "rank": 100, "rank_label": None, "size": 100, "ordered": True}])
    assert canon_score(v) == pytest.approx(0.1)


def test_canon_score_sums_across_lists():
    v = view(
        lists=[
            {"trust": 10, "rank": 1, "rank_label": None, "size": 100, "ordered": True},
            {"trust": 8, "rank": 1, "rank_label": None, "size": 10, "ordered": True},
        ]
    )
    assert canon_score(v) == pytest.approx(18.0)


def test_canon_score_reads_a_tied_rank_label_not_the_line_position():
    v = view(lists=[{"trust": 8, "rank": 8, "rank_label": "=6", "size": 10, "ordered": True}])
    assert canon_score(v) == pytest.approx(8 * (1 - 5 / 10))


def test_an_unordered_list_contributes_its_full_trust():
    v = view(lists=[{"trust": 5, "rank": 40, "rank_label": None, "size": 50, "ordered": False}])
    assert canon_score(v) == pytest.approx(5.0)


def test_a_film_on_no_list_scores_zero_and_is_not_canon():
    v = view(lists=[])
    assert canon_score(v) == 0.0
    assert is_canon(v) is False


