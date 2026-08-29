from datetime import date

import pytest

from movie_brain.domain.filters import (
    CHIPS,
    MULTI_LIST,
    NEW_ARRIVAL_DAYS,
    RECENT_DAYS,
    TOP_IMDB,
    TOP_MC,
    TOP_RT,
    acquisition_candidate,
    canon_score,
    is_canon,
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
        "owned",
        "not_owned",
        "needs_revisit",
        "suspect",
        "multi_list",
        "acquire",
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
        "multi_list": MULTI_LIST,
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


def test_owned_chip_matches_owned_views():
    assert matches(view(owned=True), ["owned"], TODAY)
    assert not matches(view(owned=False), ["owned"], TODAY)


def test_not_owned_chip_excludes_owned_views():
    assert matches(view(owned=False), ["not_owned"], TODAY)
    assert not matches(view(owned=True), ["not_owned"], TODAY)


def test_multi_list_chip_matches_two_or_more_lists():
    two = view(lists=[{"slug": "a"}, {"slug": "b"}])
    one = view(lists=[{"slug": "a"}])
    none = view()
    assert matches(two, ["multi_list"], TODAY)
    assert not matches(one, ["multi_list"], TODAY)
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


def test_a_film_streaming_on_a_subscribed_svod_is_not_a_candidate(today):
    v = view(
        lists=[{"trust": 10, "rank": 1, "rank_label": None, "size": 100, "ordered": True}],
        services=[{"name": "HBO Max", "subscribed": True, "kind": "svod"}],
        criterion=False,
    )
    assert acquisition_candidate(v, today) is False


def test_a_subscribed_STORE_does_not_suppress_a_candidate(today):
    v = view(
        lists=[{"trust": 10, "rank": 1, "rank_label": None, "size": 100, "ordered": True}],
        services=[{"name": "Apple TV Store", "subscribed": True, "kind": "store"}],
        criterion=False,
    )
    assert acquisition_candidate(v, today) is True


def test_a_film_on_the_criterion_channel_right_now_is_not_a_candidate(today):
    v = view(
        lists=[{"trust": 10, "rank": 1, "rank_label": None, "size": 100, "ordered": True}],
        criterion=True,
        departed=False,
    )
    assert acquisition_candidate(v, today) is False


def test_a_DEPARTED_criterion_film_is_a_candidate_again(today):
    v = view(
        lists=[{"trust": 10, "rank": 1, "rank_label": None, "size": 100, "ordered": True}],
        criterion=True,
        departed=True,
    )
    assert acquisition_candidate(v, today) is True


def test_owned_and_rated_films_are_not_candidates(today):
    base = {
        "lists": [{"trust": 10, "rank": 1, "rank_label": None, "size": 100, "ordered": True}],
        "criterion": False,
    }
    assert acquisition_candidate(view(**base, owned=True), today) is False
    assert acquisition_candidate(view(**base, my_rating=7), today) is False


def test_a_high_metacritic_film_on_no_list_is_a_candidate(today):
    assert acquisition_candidate(view(lists=[], metacritic=93, criterion=False), today) is True


def test_a_mediocre_film_on_no_list_is_not_a_candidate(today):
    assert acquisition_candidate(view(lists=[], metacritic=72, criterion=False), today) is False


def test_acquire_is_a_registered_chip():
    assert "acquire" in CHIPS


def test_needs_revisit_chip():
    from dataclasses import replace

    from movie_brain.domain.filters import CHIPS, matches
    from movie_brain.domain.models import FilmView

    v = FilmView(1, "A", 1950, None, None, None, None, None, None, False, None, None, None)
    assert "needs_revisit" in CHIPS
    assert not matches(v, ["needs_revisit"], date(2026, 8, 19))
    assert matches(replace(v, needs_revisit=True), ["needs_revisit"], date(2026, 8, 19))
