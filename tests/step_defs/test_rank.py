from __future__ import annotations

from datetime import date

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.rank import (
    RankError,
    pass_film,
    proposal,
    record_verdict,
    save_list,
    session_state,
    start_session,
    swap_anchor,
    undo,
)
from movie_brain.domain.models import Film
from movie_brain.domain.rank import order_queue

scenarios("../features/rank.feature")
TODAY = date(2026, 9, 13)
SRC = "owned"


@pytest.fixture
def ctx(repo, tmp_path):
    return {"repo": repo, "ids": {}, "lists_dir": tmp_path / "lists", "state": None}


def _id(ctx, title):
    return ctx["ids"][title]


def _title(ctx, fid):
    return next(t for t, i in ctx["ids"].items() if i == fid)


def _state(ctx):
    ctx["state"] = session_state(ctx["repo"], SRC, TODAY)
    return ctx["state"]


@given(parsers.parse('owned films rated "Ten" {a:d}, "Nine" {b:d}, "Eight" {c:d}, "Seven" {d:d}, "Four" {e:d}'))
def rated(ctx, a, b, c, d, e):
    for title, score in (("Ten", a), ("Nine", b), ("Eight", c), ("Seven", d), ("Four", e)):
        fid = ctx["repo"].create_film(Film(title, 1950, "Dir", ""))
        ctx["repo"].mark_owned(fid, TODAY)
        ctx["repo"].set_rating(fid, score, TODAY)
        ctx["ids"][title] = fid


@given(parsers.parse('owned unrated films "Uno", "Dos", "Tres"'))
def unrated(ctx):
    for title in ("Uno", "Dos", "Tres"):
        fid = ctx["repo"].create_film(Film(title, 1960, "Dir", ""))
        ctx["repo"].mark_owned(fid, TODAY)
        ctx["ids"][title] = fid


@then(parsers.parse("the proposal is {names}"))
def proposal_is(ctx, names):
    got = proposal(ctx["repo"], SRC)["proposal"]
    assert [got[t]["title"] for t in range(1, 6)] == [n.strip() for n in names.split(",")]


@when("I start a session with the proposed anchors")
@given("a started session")
def start(ctx):
    p = proposal(ctx["repo"], SRC)["proposal"]
    start_session(ctx["repo"], SRC, {t: p[t]["film_id"] for t in range(1, 6)}, TODAY)
    _state(ctx)


@then(parsers.parse("the tally is {a:d}, {b:d}, {c:d}, {d:d}, {e:d}"))
def tally(ctx, a, b, c, d, e):
    assert [_state(ctx)["tally"][t] for t in range(1, 6)] == [a, b, c, d, e]


@then(parsers.parse('the pair asks the candidate against tier {tier:d} "{anchor}"'))
def pair_asks(ctx, tier, anchor):
    s = _state(ctx)
    assert s["pair"]["tier"] == tier and s["pair"]["anchor"]["title"] == anchor
    assert s["pair"]["candidate"]["title"] in ("Uno", "Dos", "Tres")


@then(parsers.parse("{n:d} films remain"))
def remain(ctx, n):
    assert _state(ctx)["remaining"] == n


@when(parsers.parse("I answer {verdicts}"))
def answer(ctx, verdicts):
    for v in [x.strip() for x in verdicts.split(",")]:
        s = _state(ctx)
        ctx["last_candidate"] = s["pair"]["candidate"]["film_id"]
        record_verdict(ctx["repo"], SRC, s["pair"]["candidate"]["film_id"], s["pair"]["tier"], v, TODAY)


@then(parsers.parse("the current candidate was placed in tier {tier:d}"))
def placed_in(ctx, tier):
    sid = ctx["repo"].open_rank_session(SRC).id
    assert ctx["repo"].rank_placements(sid)[ctx["last_candidate"]] == (tier, "compared")


@then(parsers.parse("the next candidate is asked against tier {tier:d}"))
def next_asked(ctx, tier):
    s = _state(ctx)
    assert s["pair"]["tier"] == tier and s["pair"]["candidate"]["film_id"] != ctx["last_candidate"]


@then(parsers.parse('answering "{v}" against tier {tier:d} is refused with {status:d}'))
def stale(ctx, v, tier, status):
    s = _state(ctx)
    with pytest.raises(RankError) as e:
        record_verdict(ctx["repo"], SRC, s["pair"]["candidate"]["film_id"], tier, v, TODAY)
    assert e.value.status == status


@when("I pass with nothing marked")
def pass_plain(ctx):
    s = _state(ctx)
    ctx["last_candidate"] = s["pair"]["candidate"]["film_id"]
    pass_film(ctx["repo"], SRC, ctx["last_candidate"], False, False, TODAY)


@when("I pass with the candidate marked unseen")
def pass_candidate(ctx):
    s = _state(ctx)
    ctx["last_candidate"] = s["pair"]["candidate"]["film_id"]
    pass_film(ctx["repo"], SRC, ctx["last_candidate"], True, False, TODAY)


@when("I pass with the anchor marked unseen")
def pass_anchor(ctx):
    s = _state(ctx)
    pass_film(ctx["repo"], SRC, s["pair"]["candidate"]["film_id"], False, True, TODAY)


@then("the deferred film comes last in the queue")
def deferred_last(ctx):
    repo = ctx["repo"]
    sess = repo.open_rank_session(SRC)
    unplaced = [i for t, i in ctx["ids"].items() if t in ("Uno", "Dos", "Tres")]
    q = order_queue(sess.seed, unplaced, repo.rank_deferrals(sess.id))
    assert q[-1] == ctx["last_candidate"] and _state(ctx)["pair"]["candidate"]["film_id"] != ctx["last_candidate"]


@then("that film is unseen")
def that_unseen(ctx):
    assert ctx["last_candidate"] in ctx["repo"].unseen_film_ids()


@then(parsers.parse('"{title}" is unseen'))
def title_unseen(ctx, title):
    assert _id(ctx, title) in ctx["repo"].unseen_film_ids()


@then(parsers.parse("the session needs an anchor for tier {tier:d}"))
def needs_anchor(ctx, tier):
    assert _state(ctx)["needs_anchor"] == [tier]


@then("there is no pair")
def no_pair(ctx):
    assert _state(ctx)["pair"] is None


@when(parsers.parse("I swap tier {tier:d}'s anchor to \"{title}\""))
def swap(ctx, tier, title):
    swap_anchor(ctx["repo"], SRC, tier, _id(ctx, title), TODAY)


@then(parsers.parse("swapping tier {tier:d}'s anchor to \"{title}\" is refused with {status:d}"))
def swap_refused(ctx, tier, title, status):
    with pytest.raises(RankError) as e:
        swap_anchor(ctx["repo"], SRC, tier, _id(ctx, title), TODAY)
    assert e.value.status == status


@when("I undo")
def do_undo(ctx):
    undo(ctx["repo"], SRC, TODAY)


@then(parsers.parse("the current candidate has {n:d} verdict and is unplaced"))
def verdict_count(ctx, n):
    repo = ctx["repo"]
    sid = repo.open_rank_session(SRC).id
    assert len(repo.verdicts_for(sid, ctx["last_candidate"])) == n
    assert ctx["last_candidate"] not in repo.rank_placements(sid)
    assert _state(ctx)["pair"]["candidate"]["film_id"] == ctx["last_candidate"]


@then("nothing is deferred")
def nothing_deferred(ctx):
    assert ctx["repo"].rank_deferrals(ctx["repo"].open_rank_session(SRC).id) == {}


@then("nothing is unseen")
def nothing_unseen(ctx):
    assert ctx["repo"].unseen_film_ids() == set()


@then(parsers.parse("undoing again is refused with {status:d}"))
def undo_refused(ctx, status):
    with pytest.raises(RankError) as e:
        undo(ctx["repo"], SRC, TODAY)
    assert e.value.status == status


@when(parsers.parse('I save the list as "{name}"'))
def save(ctx, name):
    ctx["lists_dir"].mkdir(exist_ok=True)
    save_list(ctx["repo"], SRC, name, TODAY, ctx["lists_dir"])


@then(parsers.parse('the list "{slug}" has {n:d} entries'))
def list_has(ctx, slug, n):
    assert len(ctx["repo"].list_entries(slug)) == n


@then(parsers.parse('its tier 1 entries carry label "{label}"'))
def tier1_label(ctx, label):
    rows = ctx["repo"].list_entries("my-owned-tiers")
    assert [r.rank_label for r in rows[:2]] == [label, label]  # Ten + the film just placed in tier 1


@then("its tier 5 entry carries no label")
def tier5_bare(ctx):
    rows = ctx["repo"].list_entries("my-owned-tiers")
    assert rows[-1].film_id == _id(ctx, "Four") and rows[-1].rank_label is None


@given(parsers.parse('a list file "{name}" exists'))
def list_file(ctx, name):
    ctx["lists_dir"].mkdir(exist_ok=True)
    (ctx["lists_dir"] / name).write_text("# slug: my-owned-tiers\n")


@then(parsers.parse("saving is refused with {status:d}"))
def save_refused(ctx, status):
    with pytest.raises(RankError) as e:
        save_list(ctx["repo"], SRC, None, TODAY, ctx["lists_dir"])
    assert e.value.status == status


@then(parsers.parse("reopening the session shows the same candidate asked against tier {tier:d}"))
def reopen(ctx, tier):
    s = _state(ctx)
    assert s["pair"]["candidate"]["film_id"] == ctx["last_candidate"] and s["pair"]["tier"] == tier


@when("that film is marked unseen from the drawer")
def drawer_unseen(ctx):
    ctx["repo"].set_unseen(ctx["last_candidate"], True, TODAY)
