from __future__ import annotations

import pytest

from movie_brain.domain.models import Placed, SeedFilm
from movie_brain.domain.rank import (
    DEFAULT_LIST_NAME,
    ORDER_TIERS,
    RANKER_LIST_SLUGS,
    TIERS,
    Ask,
    Insert,
    Place,
    Probe,
    next_step,
    order_queue,
    order_step,
    propose_anchors,
    queue_key,
    tier_for_score,
    tiered_entries,
)


@pytest.mark.parametrize("score,tier", [(10, 1), (9, 2), (8, 3), (7, 4), (6, 5)])
def test_seed_mapping(score, tier):
    assert tier_for_score(score) == tier


@pytest.mark.parametrize("score", [5, 4, 0])
def test_scores_below_six_do_not_seed(score):
    with pytest.raises(ValueError):
        tier_for_score(score)


def test_order_tiers_and_default_name():
    assert ORDER_TIERS == (1, 2)
    assert DEFAULT_LIST_NAME["owned"] == "My Ranked"


@pytest.mark.parametrize(
    "verdicts,expected",
    [
        ((), Ask(3)),
        (("better",), Ask(2)),
        (("better", "better"), Place(1)),
        (("better", "worse"), Place(2)),
        (("worse",), Ask(4)),
        (("worse", "better"), Place(3)),
        (("worse", "worse"), Ask(5)),
        (("worse", "worse", "better"), Place(4)),
        (("worse", "worse", "worse"), Place(5)),
    ],
)
def test_search_table(verdicts, expected):
    assert next_step(list(verdicts)) == expected


@pytest.mark.parametrize("bad", [("same",), ("better", "better", "better"), ("worse", "worse", "worse", "worse")])
def test_illegal_sequences_raise(bad):
    with pytest.raises(ValueError):
        next_step(list(bad))


def test_propose_anchors_picks_nearest_middle_then_imdb_then_title():
    seeded = [
        SeedFilm(1, 10, 8.0, "Zed", 1950),
        SeedFilm(2, 10, 9.0, "Alpha", 1951),  # tier 1: both score 10, imdb breaks the tie
        SeedFilm(3, 6, 7.0, "Six", 1960),
        SeedFilm(4, 6, 7.0, "Zix", 1961),  # tier 5: both score 6, imdb ties, title breaks it
        SeedFilm(5, 8, None, "Eight", 1970),
    ]
    got = propose_anchors(seeded)
    assert got[1].film_id == 2
    assert got[3].film_id == 5
    assert got[5].film_id == 3
    assert got[2] is None and got[4] is None
    assert set(got) == set(range(1, TIERS + 1))


def test_propose_anchors_prefers_any_real_imdb_over_none():
    # Same score, same tier: imdb=0.0 with later title vs imdb=None with earlier title.
    # IMDb tiebreak should win over title.
    seeded = [
        SeedFilm(1, 7, 0.0, "Zebra", 1950),  # tier 4, imdb=0.0, later title
        SeedFilm(2, 7, None, "Alpha", 1951),  # tier 4, imdb=None, earlier title
    ]
    got = propose_anchors(seeded)
    assert got[4].film_id == 1  # 0.0 rating wins despite "Zebra" > "Alpha"

    # Same score, same tier, both imdb=None: title tiebreak decides.
    seeded_both_none = [
        SeedFilm(3, 7, None, "Bravo", 1952),
        SeedFilm(4, 7, None, "Alpha", 1953),
    ]
    got_none = propose_anchors(seeded_both_none)
    assert got_none[4].film_id == 4  # "Alpha" < "Bravo" on title


def test_queue_key_is_stable_per_seed_and_film():
    assert queue_key(7, 10) == queue_key(7, 10)
    assert queue_key(7, 10) != queue_key(8, 10)


def test_order_queue_shuffles_by_key_and_puts_deferred_last():
    ids = [1, 2, 3, 4, 5]
    base = order_queue(42, ids, {})
    assert sorted(base) == ids
    assert base == sorted(ids, key=lambda i: (queue_key(42, i), i))
    deferred = order_queue(42, ids, {base[0]: "2026-09-13", base[1]: "2026-09-12"})
    assert deferred[-2:] == [base[1], base[0]]  # older deferral first
    assert deferred[:3] == base[2:]


def test_order_queue_is_stable_when_a_film_joins():
    before = order_queue(42, [1, 2, 3], {})
    after = order_queue(42, [1, 2, 3, 4], {})
    assert [i for i in after if i != 4] == before


def test_tiered_entries_label_ties_and_leave_singletons_bare():
    placed = [
        Placed(10, 2, "Bravo", "B"),
        Placed(11, 1, "Zulu", "Z"),
        Placed(12, 1, "Alpha", "A"),
        Placed(13, 5, "Solo", None),
    ]
    got = tiered_entries(placed)
    assert [(e.rank, e.film_id, e.rank_label) for e in got] == [
        (1, 12, "=1"),
        (2, 11, "=1"),
        (3, 10, None),
        (4, 13, None),
    ]
    assert got[0].title == "Alpha" and got[0].director == "A"


def test_ranker_owns_the_owned_slug():
    assert "my-owned-tiers" in RANKER_LIST_SLUGS


def test_order_step_inserts_the_first_film_without_a_click():
    assert order_step([], []) == Insert(0)


def test_order_step_probes_the_only_film_then_inserts_either_side():
    assert order_step([10], []) == Probe(10)
    assert order_step([10], [(10, "better")]) == Insert(0)
    assert order_step([10], [(10, "worse")]) == Insert(1)


def test_order_step_halves_the_slot_range_each_verdict():
    order = [1, 2, 3, 4, 5]                       # slots 0..5
    assert order_step(order, []) == Probe(3)      # (0+5)//2 = 2 → film 3
    assert order_step(order, [(3, "worse")]) == Probe(5)            # lo=3, hi=5 → index 4
    assert order_step(order, [(3, "worse"), (5, "better")]) == Probe(4)   # lo=3, hi=4 → index 3
    assert order_step(order, [(3, "worse"), (5, "better"), (4, "worse")]) == Insert(4)
    assert order_step(order, [(3, "better")]) == Probe(2)           # lo=0, hi=2 → index 1
    assert order_step(order, [(3, "better"), (2, "better"), (1, "better")]) == Insert(0)


def test_order_step_ignores_a_verdict_against_a_film_no_longer_in_the_order():
    assert order_step([1, 2], [(99, "better")]) == Probe(2)


def test_order_step_raises_on_crossed_bounds_or_an_unknown_verdict():
    assert order_step([1, 2, 3], [(3, "better"), (1, "worse")]) == Probe(2)   # hi=2, lo=1: not crossed
    with pytest.raises(ValueError):
        order_step([1, 2, 3], [(1, "better"), (3, "worse")])   # hi=0, lo=3: crossed
    with pytest.raises(ValueError):
        order_step([1], [(1, "same")])


def test_tiered_entries_with_an_order_ranks_tier_1_bare_then_ties_the_rest():
    placed = [
        Placed(11, 1, "Zulu", "Z"),
        Placed(12, 1, "Alpha", "A"),
        Placed(13, 1, "Mike", "M"),
        Placed(14, 1, "Bravo", "B"),
        Placed(20, 2, "Two", None),
        Placed(50, 5, "Solo", None),
    ]
    got = tiered_entries(placed, {13: 1, 11: 2})
    assert [(e.rank, e.film_id, e.rank_label) for e in got] == [
        (1, 13, None),      # ordered: Mike at position 1
        (2, 11, None),      # ordered: Zulu at position 2
        (3, 12, "=3"),      # unordered tier 1, by title, tied at the first unordered line
        (4, 14, "=3"),
        (5, 20, None),
        (6, 50, None),
    ]


def test_tiered_entries_with_a_lone_unordered_film_leaves_it_bare():
    placed = [Placed(11, 1, "Zulu", None), Placed(12, 1, "Alpha", None)]
    got = tiered_entries(placed, {11: 1})
    assert [(e.rank, e.film_id, e.rank_label) for e in got] == [(1, 11, None), (2, 12, None)]


def test_tiered_entries_without_an_order_is_unchanged():
    placed = [Placed(11, 1, "Zulu", None), Placed(12, 1, "Alpha", None)]
    assert tiered_entries(placed) == tiered_entries(placed, {})
    assert [e.rank_label for e in tiered_entries(placed)] == ["=1", "=1"]
