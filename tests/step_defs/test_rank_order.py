from __future__ import annotations

from datetime import date

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.rank import (
    RankError,
    order_pass,
    order_state,
    order_verdict,
    proposal,
    record_verdict,
    save_list,
    session_state,
    start_session,
    undo,
)
from movie_brain.domain.models import Film

scenarios("../features/rank_order.feature")
TODAY = date(2026, 9, 13)
SRC = "owned"


@pytest.fixture
def ctx(repo, tmp_path):
    return {"repo": repo, "ids": {}, "lists_dir": tmp_path / "lists"}


def _id(ctx, title):
    return ctx["ids"][title]


def _sid(ctx):
    return ctx["repo"].open_rank_session(SRC).id


def _order(ctx, tier=1):
    return order_state(ctx["repo"], SRC, tier, TODAY)


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


@then(parsers.parse("{n:d} film is ordered and {m:d} remain to order"))
@then(parsers.parse("{n:d} films are ordered and {m:d} remain to order"))
@then(parsers.parse("{n:d} films are ordered and {m:d} remains to order"))
def ordered_and_remaining(ctx, n, m):
    s = _order(ctx)
    assert (s["ordered"], s["remaining"]) == (n, m)


@then(parsers.parse("{n:d} films are ordered"))
@then(parsers.parse("{n:d} film is ordered"))
def ordered_count(ctx, n):
    assert _order(ctx)["ordered"] == n


@then(parsers.parse("the order pair shows position {p:d} of {k:d}"))
def pair_position(ctx, p, k):
    pair = _order(ctx)["pair"]
    assert (pair["position"], pair["of"]) == (p, k)


def _answer_once(ctx, verdict, tier=1):
    pair = _order(ctx, tier)["pair"]
    assert pair is not None, "no order pair to answer"
    ctx["last_candidate"] = pair["candidate"]["film_id"]
    order_verdict(ctx["repo"], SRC, tier, pair["candidate"]["film_id"], pair["other"]["film_id"], verdict, TODAY)


@when(parsers.parse("I answer {verdict} in order mode until the candidate is inserted"))
def answer_until_inserted(ctx, verdict):
    cand = _order(ctx)["pair"]["candidate"]["film_id"]
    for _ in range(10):
        _answer_once(ctx, verdict)
        if cand in ctx["repo"].rank_order(_sid(ctx), 1):
            return
    raise AssertionError("ten verdicts and still not inserted")


@when(parsers.parse("I answer {verdict} in order mode"))
def answer_once(ctx, verdict):
    _answer_once(ctx, verdict)


@when(parsers.parse("I answer {verdict} in tier {tier:d} order mode"))
def answer_once_tier(ctx, verdict, tier):
    _answer_once(ctx, verdict, tier)


@when(parsers.parse('"{ordered}" is joined in tier {tier:d} by "{title}" rated {score:d}, not owned'))
def joined_in_tier(ctx, ordered, tier, title, score):
    """A rated film the owner does not own: the pool holds it, so the next read seeds it (P3)."""
    fid = ctx["repo"].create_film(Film(title, 1970, "Dir", ""))
    ctx["repo"].set_rating(fid, score, TODAY)
    ctx["ids"][title] = fid


@then(parsers.parse("the tier {tier:d} order has {n:d} film and {m:d} remaining"))
@then(parsers.parse("the tier {tier:d} order has {n:d} films and {m:d} remaining"))
@then(parsers.parse("the tier {tier:d} order still has {n:d} film and {m:d} remaining"))
@then(parsers.parse("the tier {tier:d} order still has {n:d} films and {m:d} remaining"))
def tier_order_counts(ctx, tier, n, m):
    s = _order(ctx, tier)
    assert (s["tier"], s["ordered"], s["remaining"]) == (tier, n, m)


@then(parsers.parse('"{title}" is deferred in tier {tier:d}'))
def deferred_in_tier(ctx, title, tier):
    assert _id(ctx, title) in ctx["repo"].order_deferrals(_sid(ctx))
    assert _id(ctx, title) not in ctx["repo"].rank_order(_sid(ctx), tier)


@then(parsers.parse("reading the tier {tier:d} order is refused with {status:d}"))
def tier_order_refused(ctx, tier, status):
    with pytest.raises(RankError) as e:
        _order(ctx, tier)
    assert e.value.status == status


@then(parsers.parse("the last inserted film is at position {p:d}"))
def inserted_at(ctx, p):
    order = ctx["repo"].rank_order(_sid(ctx), 1)
    assert order.index(ctx["last_candidate"]) + 1 == p


@then(parsers.parse("the order is done with {n:d} films ordered"))
def order_done(ctx, n):
    s = _order(ctx)
    assert s["done"] is True and s["ordered"] == n and s["pair"] is None


@when(parsers.parse('"{title}" is tiered into tier 1'))
def tier_into_1(ctx, title):
    # The tiering's own path: better than tier 3's anchor, better than tier 2's → tier 1.
    for _ in range(2):
        s = session_state(ctx["repo"], SRC, TODAY)
        assert s["pair"]["candidate"]["film_id"] == _id(ctx, title)
        record_verdict(ctx["repo"], SRC, _id(ctx, title), s["pair"]["tier"], "better", TODAY)
    assert ctx["repo"].rank_placements(_sid(ctx))[_id(ctx, title)][0] == 1


@then(parsers.parse("answering better against a film that is not the shown one is refused with {status:d}"))
def stale_order_verdict(ctx, status):
    pair = _order(ctx)["pair"]
    wrong_other = next(i for i in ctx["ids"].values() if i not in (pair["other"]["film_id"], pair["candidate"]["film_id"]))
    with pytest.raises(RankError) as e:
        order_verdict(ctx["repo"], SRC, 1, pair["candidate"]["film_id"], wrong_other, "better", TODAY)
    assert e.value.status == status


def _pass_once(ctx, tier=1):
    pair = _order(ctx, tier)["pair"]
    ctx["last_candidate"] = pair["candidate"]["film_id"]
    order_pass(ctx["repo"], SRC, tier, pair["candidate"]["film_id"], TODAY)


@when("I pass in order mode")
def pass_order(ctx):
    _pass_once(ctx)


@when(parsers.parse("I pass in tier {tier:d} order mode"))
def pass_order_tier(ctx, tier):
    _pass_once(ctx, tier)


@then("the deferred film comes last in the order queue")
def deferred_last(ctx):
    repo = ctx["repo"]
    assert ctx["last_candidate"] in repo.order_deferrals(_sid(ctx))
    s = _order(ctx)
    assert s["pair"]["candidate"]["film_id"] != ctx["last_candidate"]
    # Insert everything else with one click each; the deferred film is the last candidate.
    for _ in range(10):
        s = _order(ctx)
        if s["pair"]["candidate"]["film_id"] == ctx["last_candidate"]:
            break
        order_verdict(repo, SRC, 1, s["pair"]["candidate"]["film_id"], s["pair"]["other"]["film_id"], "better", TODAY)
    assert _order(ctx)["pair"]["candidate"]["film_id"] == ctx["last_candidate"]
    assert _order(ctx)["remaining"] == 1


@when("I undo")
def do_undo(ctx):
    ctx["undo_result"] = undo(ctx["repo"], SRC, TODAY)


@then("the undo returned the order state")
def undo_returned_order(ctx):
    result = ctx["undo_result"]
    assert "ordered" in result and "tally" not in result


@then(parsers.parse("the undo returned the tier {tier:d} order state"))
def undo_returned_tier_order(ctx, tier):
    """The undo's OWN answer, not a re-read: hard-coding a tier in `undo` would pass a re-read."""
    assert ctx["undo_result"]["tier"] == tier


@when("the stored undo action loses its tier, as an old row has")
def strip_action_tier(ctx):
    """Exactly the shape the live DB's row has: an order action written before tier 2 existed."""
    s = ctx["repo"].open_rank_session(SRC)
    assert s.last_action is not None and "tier" in s.last_action
    ctx["repo"].set_last_action(s.id, {k: v for k, v in s.last_action.items() if k != "tier"})


@then("the undo returned the tiering state")
def undo_returned_tiering(ctx):
    result = ctx["undo_result"]
    assert "tally" in result and "ordered" not in result


@then(parsers.parse("{n:d} film is ordered and the same candidate is asked with {v:d} verdicts"))
def same_candidate(ctx, n, v):
    s = _order(ctx)
    assert s["ordered"] == n and s["pair"]["candidate"]["film_id"] == ctx["last_candidate"]
    assert len(s["pair"]["asked"]) == v


@then("nothing is deferred in order mode")
def nothing_deferred(ctx):
    assert ctx["repo"].order_deferrals(_sid(ctx)) == {}


@then(parsers.parse("undoing again is refused with {status:d}"))
def undo_refused(ctx, status):
    with pytest.raises(RankError) as e:
        undo(ctx["repo"], SRC, TODAY)
    assert e.value.status == status


@when(parsers.parse("I answer {verdicts} in tiering mode"))
def answer_tiering(ctx, verdicts):
    for v in [x.strip() for x in verdicts.split(",")]:
        s = session_state(ctx["repo"], SRC, TODAY)
        ctx["tiering_candidate"] = s["pair"]["candidate"]["film_id"]
        record_verdict(ctx["repo"], SRC, s["pair"]["candidate"]["film_id"], s["pair"]["tier"], v, TODAY)


@then("the tiering candidate is unplaced again")
def tiering_unplaced(ctx):
    assert ctx["tiering_candidate"] not in ctx["repo"].rank_placements(_sid(ctx))


@then("the order is empty")
def order_is_empty(ctx):
    assert ctx["repo"].rank_order(_sid(ctx), 1) == []


@then(parsers.parse('"{title}" is not in the order'))
def not_in_order(ctx, title):
    assert _id(ctx, title) not in ctx["repo"].rank_order(_sid(ctx), 1)


@when("the current candidate's order log is made corrupt")
def make_corrupt(ctx):
    pair = _order(ctx)["pair"]
    cand = pair["candidate"]["film_id"]
    ordered_film = ctx["repo"].rank_order(_sid(ctx), 1)[0]
    ctx["corrupt_candidate"] = cand
    ctx["repo"].append_order_comparison(_sid(ctx), 1, cand, ordered_film, "better", TODAY)
    ctx["repo"].append_order_comparison(_sid(ctx), 1, cand, ordered_film, "worse", TODAY)


@when("every remaining candidate's order log is made corrupt")
def corrupt_the_rest(ctx):
    for _ in range(20):   # bounded: the queue is four films long
        pair = _order(ctx)["pair"]
        if pair is None:
            return
        make_corrupt(ctx)
    raise AssertionError("the order queue never drained")


@then("the corrupt film is skipped and the pair asks a different candidate")
def corrupt_skipped(ctx):
    s = _order(ctx)
    assert ctx["corrupt_candidate"] in s["corrupt"]
    if s["pair"] is not None:
        assert s["pair"]["candidate"]["film_id"] != ctx["corrupt_candidate"]


@then(parsers.parse("{n:d} film is corrupt and {m:d} remain to order"))
@then(parsers.parse("{n:d} films are corrupt and {m:d} remain to order"))
def corrupt_and_remaining(ctx, n, m):
    s = _order(ctx)
    assert (len(s["corrupt"]), s["remaining"]) == (n, m)


@then("the order is not done")
def order_not_done(ctx):
    assert _order(ctx)["done"] is False


@when(parsers.parse("the film at position {p:d} is marked unseen from the drawer"))
def unseen_at_position(ctx, p):
    fid = ctx["repo"].rank_order(_sid(ctx), 1)[p - 1]
    ctx["repo"].set_unseen(fid, True, TODAY)


@then(parsers.parse("the current candidate has {n:d} verdicts"))
def candidate_verdicts(ctx, n):
    s = _order(ctx)
    assert len(s["pair"]["asked"]) == n


@when(parsers.parse('I save the list as "{name}"'))
def save(ctx, name):
    ctx["lists_dir"].mkdir(exist_ok=True)
    save_list(ctx["repo"], SRC, name, TODAY, ctx["lists_dir"])


@then(parsers.parse('the list "{slug}" has {n:d} entries'))
def list_has(ctx, slug, n):
    assert len(ctx["repo"].list_entries(slug)) == n


@then(parsers.parse("entries {a:d} and {b:d} carry no label"))
def entries_bare(ctx, a, b):
    rows = ctx["repo"].list_entries("my-owned-tiers")
    assert rows[a - 1].rank_label is None and rows[b - 1].rank_label is None


@then("entry 2 is the last inserted film")
def entry_2_is_last_inserted(ctx):
    row = ctx["repo"].list_entries("my-owned-tiers")[1]
    assert row.film_id == ctx["last_candidate"]


@then(parsers.parse('entries {a:d} and {b:d} carry label "{label}"'))
def entries_tied(ctx, a, b, label):
    rows = ctx["repo"].list_entries("my-owned-tiers")
    assert rows[a - 1].rank_label == label and rows[b - 1].rank_label == label


@then(parsers.parse('entry {n:d} is "{title}" with no label'))
def entry_is(ctx, n, title):
    row = ctx["repo"].list_entries("my-owned-tiers")[n - 1]
    assert row.film_id == _id(ctx, title) and row.rank_label is None


@given("the session is finished")
def finish(ctx):
    with ctx["repo"]._conn() as c:
        c.execute("UPDATE rank_session SET finished_on = ? WHERE id = ?", (TODAY.isoformat(), _sid(ctx)))


@then(parsers.parse("reading the order state is refused with {status:d}"))
def order_refused(ctx, status):
    with pytest.raises(RankError) as e:
        order_state(ctx["repo"], SRC, 1, TODAY)
    assert e.value.status == status
