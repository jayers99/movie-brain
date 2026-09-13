from __future__ import annotations

from datetime import date

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.rank import (
    _queue,  # the derived tiering queue; asserting on it directly beats replaying pair-by-pair
    order_state,
    proposal,
    session_state,
    start_session,
)
from movie_brain.domain.models import Film

scenarios("../features/rank_pool.feature")
TODAY = date(2026, 9, 13)
SRC = "owned"


@pytest.fixture
def ctx(repo):
    return {"repo": repo, "ids": {}}


def _id(ctx, title):
    return ctx["ids"][title]


def _session(ctx):
    s = ctx["repo"].open_rank_session(SRC)
    assert s is not None
    return s


def _new_film(ctx, title, year=1960):
    fid = ctx["repo"].create_film(Film(title, year, "Dir", ""))
    ctx["ids"][title] = fid
    return fid


def _queue_ids(ctx):
    # Seed on read happens in `session_state`, so read the state first, then the queue.
    session_state(ctx["repo"], SRC, TODAY)
    return _queue(ctx["repo"], _session(ctx))


@given(parsers.parse('owned films rated "Ten" {a:d}, "Nine" {b:d}, "Eight" {c:d}, "Seven" {d:d}, "Six" {e:d}'))
def rated(ctx, a, b, c, d, e):
    for title, score in (("Ten", a), ("Nine", b), ("Eight", c), ("Seven", d), ("Six", e)):
        fid = _new_film(ctx, title, 1950)
        ctx["repo"].mark_owned(fid, TODAY)
        ctx["repo"].set_rating(fid, score, TODAY)


@given(parsers.parse('an owned unrated film "{title}"'))
def owned_unrated(ctx, title):
    ctx["repo"].mark_owned(_new_film(ctx, title), TODAY)


@given(parsers.parse('an owned film "{title}" rated {score:d}'))
def owned_rated(ctx, title, score):
    fid = _new_film(ctx, title)
    ctx["repo"].mark_owned(fid, TODAY)
    ctx["repo"].set_rating(fid, score, TODAY)


@given(parsers.parse('a film "{title}" rated {score:d}, not owned'))
def unowned_rated(ctx, title, score):
    ctx["repo"].set_rating(_new_film(ctx, title), score, TODAY)


@given(parsers.parse('a film "{title}" not owned'))
def unowned_unrated(ctx, title):
    _new_film(ctx, title)


@given(parsers.parse('"{title}" is re-rated {score:d}'))
def re_rate(ctx, title, score):
    ctx["repo"].set_rating(_id(ctx, title), score, TODAY)


def _start(ctx):
    p = proposal(ctx["repo"], SRC)["proposal"]
    start_session(ctx["repo"], SRC, {t: p[t]["film_id"] for t in range(1, 6)}, TODAY)


@given("a started tiering session")
def start_given(ctx):
    _start(ctx)


@when("I start a tiering session")
def start_when(ctx):
    _start(ctx)


@when(parsers.parse('"{title}" is rated {score:d}'))
def rate_now(ctx, title, score):
    ctx["repo"].set_rating(_id(ctx, title), score, TODAY)


@when(parsers.parse('"{title}" is marked Rank this'))
def mark(ctx, title):
    ctx["repo"].set_rank_mark(_id(ctx, title), True, TODAY)


@when(parsers.parse('"{title}" is unmarked'))
def unmark(ctx, title):
    ctx["repo"].set_rank_mark(_id(ctx, title), False, TODAY)


@then(parsers.parse('"{title}" is placed in tier {tier:d} as a seed'))
def placed_as_seed(ctx, title, tier):
    session_state(ctx["repo"], SRC, TODAY)  # seed on read
    assert ctx["repo"].rank_placements(_session(ctx).id).get(_id(ctx, title)) == (tier, "seed")


@then(parsers.parse('"{title}" is not in the queue'))
def not_queued(ctx, title):
    assert _id(ctx, title) not in _queue_ids(ctx)


@then(parsers.parse('"{title}" is in the queue'))
def queued(ctx, title):
    assert _id(ctx, title) in _queue_ids(ctx)


@then(parsers.parse('none of "{a}", "{b}", "{c}" is placed or queued'))
def none_placed_or_queued(ctx, a, b, c):
    queue = _queue_ids(ctx)
    placed = ctx["repo"].rank_placements(_session(ctx).id)
    for title in (a, b, c):
        assert _id(ctx, title) not in placed, f"{title} was placed"
        assert _id(ctx, title) not in queue, f"{title} was queued"


@then("the proposal still reads")
def proposal_reads(ctx):
    assert proposal(ctx["repo"], SRC)["proposal"][1] is not None


@then(parsers.parse('tier {tier:d}\'s choices include "{title}"'))
def choices_include(ctx, tier, title):
    got = proposal(ctx["repo"], SRC)["choices"][tier]
    assert _id(ctx, title) in {c["film_id"] for c in got}


@then(parsers.parse("the tier {tier:d} order has {n:d} film and {m:d} remaining"))
@then(parsers.parse("the tier {tier:d} order has {n:d} films and {m:d} remaining"))
def order_counts(ctx, tier, n, m):
    s = order_state(ctx["repo"], SRC, tier, TODAY)
    assert (s["tier"], s["ordered"], s["remaining"]) == (tier, n, m)
