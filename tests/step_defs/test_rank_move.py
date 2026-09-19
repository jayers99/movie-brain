from __future__ import annotations

from datetime import date

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.rank import (
    RankError,
    move_film,
    order_state,
    order_verdict,
    pass_film,
    proposal,
    rank_status,
    record_verdict,
    rerank_film,
    session_state,
    start_session,
    undo,
)
from movie_brain.domain.models import Film

scenarios("../features/rank_move.feature")
TODAY = date(2026, 9, 14)
SRC = "owned"


@pytest.fixture
def ctx(repo):
    return {"repo": repo, "ids": {}}


def _id(ctx, title):
    return ctx["ids"][title]


def _sid(ctx):
    return ctx["repo"].open_rank_session(SRC).id


def _order(ctx, tier=1):
    return order_state(ctx["repo"], SRC, tier, TODAY)


def _move(ctx, fid, tier):
    ctx["moved"] = fid
    ctx["result"] = move_film(ctx["repo"], SRC, fid, tier, TODAY)


@given(parsers.parse('owned films rated "Alpha" {a:d}, "Beta" {b:d}, "Gamma" {c:d}, "Delta" {d:d}, "Nine" {e:d}, "Eight" {f:d}, "Seven" {g:d}, "Six" {h:d}'))
def rated(ctx, a, b, c, d, e, f, g, h):
    for title, score in (("Alpha", a), ("Beta", b), ("Gamma", c), ("Delta", d), ("Nine", e), ("Eight", f), ("Seven", g), ("Six", h)):
        fid = ctx["repo"].create_film(Film(title, 1950, "Dir", ""))
        ctx["repo"].mark_owned(fid, TODAY)
        ctx["repo"].set_rating(fid, score, TODAY)
        ctx["ids"][title] = fid


@given(parsers.parse('an owned unrated film "{title}"'))
def unrated(ctx, title):
    fid = ctx["repo"].create_film(Film(title, 1960, "Dir", ""))
    ctx["repo"].mark_owned(fid, TODAY)
    ctx["ids"][title] = fid


@given("a started tiering session")
def start(ctx):
    p = proposal(ctx["repo"], SRC)["proposal"]
    start_session(ctx["repo"], SRC, {t: p[t]["film_id"] for t in range(1, 6)}, TODAY)


@when(parsers.parse("I answer {verdict} in order mode until the candidate is inserted"))
def answer_until_inserted(ctx, verdict):
    cand = _order(ctx)["pair"]["candidate"]["film_id"]
    for _ in range(10):
        pair = _order(ctx)["pair"]
        order_verdict(ctx["repo"], SRC, 1, pair["candidate"]["film_id"], pair["other"]["film_id"], verdict, TODAY)
        if cand in ctx["repo"].rank_order(_sid(ctx), 1):
            return
    raise AssertionError("ten verdicts and still not inserted")


@when(parsers.parse('"{title}" is tiered into tier 1'))
def tier_into_1(ctx, title):
    for _ in range(2):
        s = session_state(ctx["repo"], SRC, TODAY)
        assert s["pair"]["candidate"]["film_id"] == _id(ctx, title)
        record_verdict(ctx["repo"], SRC, _id(ctx, title), s["pair"]["tier"], "better", TODAY)
    assert ctx["repo"].rank_placements(_sid(ctx))[_id(ctx, title)][0] == 1


@when(parsers.parse("the film at position {p:d} is moved to tier {tier:d} from the drawer"))
def move_at_position(ctx, p, tier):
    _move(ctx, ctx["repo"].rank_order(_sid(ctx), 1)[p - 1], tier)


@when(parsers.parse('"{title}" is moved to tier {tier:d} from the drawer'))
def move_title(ctx, title, tier):
    _move(ctx, _id(ctx, title), tier)


@when(parsers.parse("the tier 1 order candidate is moved to tier {tier:d} from the drawer"))
def move_candidate(ctx, tier):
    ctx["old_pair"] = _order(ctx)["pair"]
    _move(ctx, ctx["old_pair"]["candidate"]["film_id"], tier)


@when(parsers.parse('"{ordered}" is joined in tier {tier:d} by "{title}" rated {score:d}, not owned'))
def joined_in_tier(ctx, ordered, tier, title, score):
    """A rated film the owner does not own: the pool holds it, so the next read seeds it (P3)."""
    fid = ctx["repo"].create_film(Film(title, 1970, "Dir", ""))
    ctx["repo"].set_rating(fid, score, TODAY)
    ctx["ids"][title] = fid
    session_state(ctx["repo"], SRC, TODAY)
    assert ctx["repo"].rank_placements(_sid(ctx))[fid][0] == tier


@when(parsers.parse("the tier {tier:d} order is read"))
def read_tier(ctx, tier):
    _order(ctx, tier)


@when(parsers.parse("I answer {verdict} in tier {tier:d} order mode"))
def answer_once_tier(ctx, verdict, tier):
    pair = _order(ctx, tier)["pair"]
    order_verdict(ctx["repo"], SRC, tier, pair["candidate"]["film_id"], pair["other"]["film_id"], verdict, TODAY)


@then(parsers.parse('the moved film is placed in tier {tier:d} as "{how}"'))
def moved_placed(ctx, tier, how):
    assert ctx["repo"].rank_placements(_sid(ctx))[ctx["moved"]] == (tier, how)


@then(parsers.parse("the move reported from tier {t:d} and awaiting order"))
def reported_awaiting(ctx, t):
    assert ctx["result"] == {"film_id": ctx["moved"], "tier": ctx["result"]["tier"], "from_tier": t, "awaiting_order": True}


@then(parsers.parse("the move reported from tier {t:d} and not awaiting order"))
def reported_not_awaiting(ctx, t):
    assert ctx["result"]["from_tier"] == t and ctx["result"]["awaiting_order"] is False


@then(parsers.parse("{n:d} film is ordered and {m:d} remain to order"))
@then(parsers.parse("{n:d} films are ordered and {m:d} remain to order"))
def ordered_and_remaining(ctx, n, m):
    s = _order(ctx)
    assert (s["ordered"], s["remaining"]) == (n, m)


@then(parsers.parse("the tier {tier:d} order has {n:d} film and {m:d} remaining"))
@then(parsers.parse("the tier {tier:d} order has {n:d} films and {m:d} remaining"))
def tier_order_counts(ctx, tier, n, m):
    s = _order(ctx, tier)
    assert (s["ordered"], s["remaining"]) == (n, m)


@then("the moved film is the tier 2 order candidate")
def moved_is_candidate(ctx):
    assert _order(ctx, 2)["pair"]["candidate"]["film_id"] == ctx["moved"]


@then("the next reads do not re-seed the moved film")
def not_reseeded(ctx):
    before = ctx["repo"].rank_placements(_sid(ctx))[ctx["moved"]]
    session_state(ctx["repo"], SRC, TODAY)
    _order(ctx, 1)
    _order(ctx, 2)
    assert ctx["repo"].rank_placements(_sid(ctx))[ctx["moved"]] == before


@then(parsers.parse('rank status for "{title}" is tier {tier:d} "{how}" and awaiting order'))
def status_awaiting(ctx, title, tier, how):
    assert rank_status(ctx["repo"], SRC, _id(ctx, title)) == {"tier": tier, "how": how, "awaiting_order": True}


@then(parsers.parse('rank status for "{title}" is tier {tier:d} "{how}" and not awaiting order'))
def status_not_awaiting(ctx, title, tier, how):
    assert rank_status(ctx["repo"], SRC, _id(ctx, title)) == {"tier": tier, "how": how, "awaiting_order": False}


@then(parsers.parse('rank status for "{title}" reports no tier'))
def status_none(ctx, title):
    assert rank_status(ctx["repo"], SRC, _id(ctx, title)) == {"tier": None, "how": None, "awaiting_order": False}


@then("undo is available")
def undo_available(ctx):
    assert session_state(ctx["repo"], SRC, TODAY)["can_undo"] is True


@then("undo is not available")
def undo_unavailable(ctx):
    assert session_state(ctx["repo"], SRC, TODAY)["can_undo"] is False


@then(parsers.parse("undoing is refused with {status:d}"))
def undo_refused(ctx, status):
    with pytest.raises(RankError) as e:
        undo(ctx["repo"], SRC, TODAY)
    assert e.value.status == status


def _refused(ctx, fid, tier, status, fragment):
    with pytest.raises(RankError) as e:
        move_film(ctx["repo"], SRC, fid, tier, TODAY)
    assert e.value.status == status and fragment in e.value.message


@then(parsers.parse('moving "{title}" to tier {tier:d} is refused with {status:d} "{fragment}"'))
def refused_title(ctx, title, tier, status, fragment):
    _refused(ctx, _id(ctx, title), tier, status, fragment)


@then(parsers.parse('moving the tier 1 anchor to tier {tier:d} is refused with {status:d} "{fragment}"'))
def refused_anchor(ctx, tier, status, fragment):
    _refused(ctx, ctx["repo"].rank_anchors(_sid(ctx))[1], tier, status, fragment)


@then(parsers.parse("answering the old order pair is refused with {status:d}"))
def old_pair_refused(ctx, status):
    old = ctx["old_pair"]
    with pytest.raises(RankError) as e:
        order_verdict(ctx["repo"], SRC, 1, old["candidate"]["film_id"], old["other"]["film_id"], "better", TODAY)
    assert e.value.status == status


def _rerank(ctx, fid):
    ctx["moved"] = fid
    ctx["result"] = rerank_film(ctx["repo"], SRC, fid, TODAY)


@when(parsers.parse("the film at position {p:d} is re-ranked from the drawer"))
def rerank_at_position(ctx, p):
    _rerank(ctx, ctx["repo"].rank_order(_sid(ctx), 1)[p - 1])


@when(parsers.parse('"{title}" is re-ranked from the drawer'))
def rerank_title(ctx, title):
    _rerank(ctx, _id(ctx, title))


@when(parsers.parse('"{title}" is answered worse than every anchor'))
def worse_than_every_anchor(ctx, title):
    fid = _id(ctx, title)
    for _ in range(8):
        s = session_state(ctx["repo"], SRC, TODAY)
        if fid in ctx["repo"].rank_placements(_sid(ctx)):
            return
        cand = s["pair"]["candidate"]["film_id"]
        if cand != fid:   # another unplaced pool film (Uno) leads the shuffle: defer it, keep it unplaced
            pass_film(ctx["repo"], SRC, cand, False, False, TODAY)
            continue
        record_verdict(ctx["repo"], SRC, fid, s["pair"]["tier"], "worse", TODAY)
    assert fid in ctx["repo"].rank_placements(_sid(ctx))


@when(parsers.parse('"{title}" is inserted into the tier 1 order'))
def insert_into_order(ctx, title):
    fid = _id(ctx, title)
    for _ in range(10):
        pair = _order(ctx)["pair"]   # an empty order free-inserts the first film with no click (O7)
        if fid in ctx["repo"].rank_order(_sid(ctx), 1):
            return
        assert pair is not None and pair["candidate"]["film_id"] == fid
        order_verdict(ctx["repo"], SRC, 1, fid, pair["other"]["film_id"], "worse", TODAY)
    raise AssertionError("ten verdicts and still not inserted")


@then("the re-ranked film is not placed and is marked")
def reranked_state(ctx):
    assert ctx["moved"] not in ctx["repo"].rank_placements(_sid(ctx))
    assert ctx["moved"] in ctx["repo"].rank_mark_film_ids()


@then(parsers.parse("the re-rank reported from tier {t:d}"))
def rerank_reported(ctx, t):
    assert ctx["result"] == {"film_id": ctx["moved"], "from_tier": t, "marked": True}


@then("the next reads do not re-seed the re-ranked film")
def not_reseeded_after_rerank(ctx):
    session_state(ctx["repo"], SRC, TODAY)
    _order(ctx, 1)
    assert ctx["moved"] not in ctx["repo"].rank_placements(_sid(ctx))
    assert ctx["moved"] in ctx["repo"].rank_mark_film_ids()


@then("the re-ranked film is in the tiering queue")
def in_tiering_queue(ctx):
    s = session_state(ctx["repo"], SRC, TODAY)
    assert s["remaining"] >= 1 and s["pair"] is not None
    # Uno is the other unplaced pool film; answer whichever leads until the re-ranked film is asked.
    for _ in range(6):
        s = session_state(ctx["repo"], SRC, TODAY)
        if s["pair"]["candidate"]["film_id"] == ctx["moved"]:
            return
        record_verdict(ctx["repo"], SRC, s["pair"]["candidate"]["film_id"], s["pair"]["tier"], "worse", TODAY)
    raise AssertionError("the re-ranked film was never asked")


@then(parsers.parse('"{title}" is placed in tier {tier:d} and its mark is gone'))
def placed_mark_gone(ctx, title, tier):
    fid = _id(ctx, title)
    session_state(ctx["repo"], SRC, TODAY)   # the sweep runs on read
    assert ctx["repo"].rank_placements(_sid(ctx))[fid][0] == tier
    assert fid not in ctx["repo"].rank_mark_film_ids()


@then(parsers.parse('"{title}" is placed in tier {tier:d} and still marked'))
def placed_still_marked(ctx, title, tier):
    fid = _id(ctx, title)
    session_state(ctx["repo"], SRC, TODAY)
    assert ctx["repo"].rank_placements(_sid(ctx))[fid][0] == tier
    assert fid in ctx["repo"].rank_mark_film_ids()


@then(parsers.parse('re-ranking "{title}" is refused with {status:d} "{fragment}"'))
def rerank_refused(ctx, title, status, fragment):
    with pytest.raises(RankError) as e:
        rerank_film(ctx["repo"], SRC, _id(ctx, title), TODAY)
    assert e.value.status == status and fragment in e.value.message
