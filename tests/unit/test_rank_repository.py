from __future__ import annotations

from datetime import date

from movie_brain.domain.models import Film, ListMeta, OmdbRating, TieredEntry
from movie_brain.domain.rank import Insert, Probe, order_step

D = date(2026, 9, 13)


def _film(repo, title, year):
    fid = repo.create_film(Film(title, year, "Dir", ""))
    assert fid is not None
    return fid


def test_set_unseen_marks_unmarks_and_reports_missing(repo):
    a = _film(repo, "Alpha", 1950)
    assert repo.set_unseen(a, True, D, note="never saw it") is True
    assert repo.unseen_film_ids() == {a}
    assert repo.get_view(a, D).unseen is True
    assert repo.set_unseen(a, True, D) is True  # idempotent
    assert repo.set_unseen(a, False, D) is False
    assert repo.unseen_film_ids() == set()
    assert repo.set_unseen(999, True, D) is None


def test_merge_moves_unseen_survivor_wins(repo):
    a = _film(repo, "Alpha", 1950)
    b = _film(repo, "Alpha", 1951)
    anchor = _film(repo, "Anchor", 1960)
    sid = repo.create_rank_session("owned", 1, {3: anchor}, {a: 2}, D)
    repo.append_comparison(sid, a, anchor, 3, "worse", D)
    repo.set_unseen(b, True, D)
    repo.merge_film(b, a, D)
    assert repo.unseen_film_ids() == {a}
    # The survivor was placed and mid-search before the merge; inheriting the loser's unseen
    # mark must purge both, exactly as `set_unseen` itself does (finding 3).
    assert repo.rank_placements(sid) == {}
    assert repo.verdicts_for(sid, a) == []
    c = _film(repo, "Beta", 1960)
    d = _film(repo, "Beta", 1961)
    repo.set_unseen(c, True, D, note="keep")
    repo.set_unseen(d, True, D, note="drop")
    report = repo.merge_film(d, c, D)
    assert report.dropped.get("unseen") == 1
    assert repo.unseen_film_ids() == {a, c}


def _owned_rated(repo, title, year, score, imdb=None):
    fid = _film(repo, title, year)
    repo.mark_owned(fid, D)
    repo.set_rating(fid, score, D)
    if imdb is not None:
        repo.upsert_omdb(fid, OmdbRating(imdb, None, True, "English", '{"Title":"x"}'), D)
    return fid


def test_owned_seed_films_is_owned_and_rated_minus_unseen(repo):
    a = _owned_rated(repo, "Alpha", 1950, 10, imdb=8.1)
    b = _owned_rated(repo, "Bravo", 1960, 8)
    _film(repo, "Charlie", 1970)  # neither owned nor rated
    c = _owned_rated(repo, "Delta", 1980, 7)
    repo.set_unseen(c, True, D)
    got = {s.film_id: s for s in repo.pool_seed_films()}
    assert set(got) == {a, b}
    assert got[a].score == 10 and got[a].imdb == 8.1 and got[a].title == "Alpha" and got[a].year == 1950
    assert got[b].imdb is None


def test_rank_mark_round_trips_and_reports_missing(repo):
    a = _film(repo, "Alpha", 1950)
    assert repo.set_rank_mark(a, True, D) is True
    assert repo.rank_mark_film_ids() == {a}
    assert repo.get_view(a, D).rank_marked is True
    assert repo.set_rank_mark(a, True, D) is True   # idempotent
    assert repo.set_rank_mark(a, False, D) is False
    assert repo.rank_mark_film_ids() == set()
    assert repo.set_rank_mark(999, True, D) is None


def test_rank_pool_is_owned_or_marked_or_rated_6_plus_minus_low_scores_unseen_and_disposed(repo):
    owned = _film(repo, "Owned", 1950)
    repo.mark_owned(owned, D)
    marked = _film(repo, "Marked", 1951)
    repo.set_rank_mark(marked, True, D)
    rated6 = _film(repo, "Rated6", 1952)
    repo.set_rating(rated6, 6, D)
    rated5 = _film(repo, "Rated5", 1953)
    repo.set_rating(rated5, 5, D)
    owned0 = _film(repo, "Owned0", 1954)
    repo.mark_owned(owned0, D)
    repo.set_rating(owned0, 0, D)
    marked4 = _film(repo, "Marked4", 1955)
    repo.set_rank_mark(marked4, True, D)
    repo.set_rating(marked4, 4, D)
    unseen_owned = _film(repo, "UnseenOwned", 1956)
    repo.mark_owned(unseen_owned, D)
    repo.set_unseen(unseen_owned, True, D)
    gone = _film(repo, "Gone", 1957)
    repo.mark_owned(gone, D)
    repo.tombstone_film(gone, D)
    _film(repo, "Nobody", 1958)
    assert repo.rank_pool_film_ids() == {owned, marked, rated6}


def test_pool_seed_films_is_pool_and_rated_6_plus(repo):
    a = _owned_rated(repo, "Alpha", 1950, 10, imdb=8.1)
    b = _film(repo, "Bravo", 1960)
    repo.set_rating(b, 8, D)  # rated, not owned: in
    _owned_rated(repo, "Charlie", 1970, 5)  # owned but 5: out
    d = _film(repo, "Delta", 1980)
    repo.set_rank_mark(d, True, D)  # marked, unrated: not a seed
    e = _owned_rated(repo, "Echo", 1990, 7)
    repo.set_unseen(e, True, D)
    got = {s.film_id: s for s in repo.pool_seed_films()}
    assert set(got) == {a, b}
    assert got[a].score == 10 and got[a].imdb == 8.1 and got[b].imdb is None


def test_merge_moves_rank_mark_survivor_wins(repo):
    a, b = _film(repo, "Alpha", 1950), _film(repo, "Alpha", 1951)
    repo.set_rank_mark(b, True, D)
    repo.merge_film(b, a, D)
    assert repo.rank_mark_film_ids() == {a}
    c, d = _film(repo, "Beta", 1960), _film(repo, "Beta", 1961)
    repo.set_rank_mark(c, True, D)
    repo.set_rank_mark(d, True, D)
    report = repo.merge_film(d, c, D)
    assert report.dropped.get("rank_mark") == 1 and repo.rank_mark_film_ids() == {a, c}


def test_session_round_trip(repo):
    ids = [_owned_rated(repo, t, 1950 + i, 10 - i) for i, t in enumerate(["A", "B", "C", "D", "E"])]
    assert repo.open_rank_session("owned") is None
    sid = repo.create_rank_session("owned", 42, {t: ids[t - 1] for t in range(1, 6)}, {ids[0]: 1, ids[1]: 2}, D)
    s = repo.open_rank_session("owned")
    assert s is not None and s.id == sid and s.seed == 42 and s.last_action is None and s.list_slug is None
    assert repo.rank_anchors(sid) == {t: ids[t - 1] for t in range(1, 6)}
    assert repo.rank_placements(sid) == {ids[0]: (1, "seed"), ids[1]: (2, "seed")}
    repo.set_rank_anchor(sid, 3, None, D)
    assert repo.rank_anchors(sid)[3] is None
    x = _film(repo, "X", 2000)
    cid = repo.append_comparison(sid, x, ids[2], 3, "worse", D)
    repo.append_comparison(sid, x, ids[3], 4, "better", D)
    assert repo.verdicts_for(sid, x) == ["worse", "better"]
    repo.delete_comparison(cid)
    assert repo.verdicts_for(sid, x) == ["better"]
    repo.place_film(sid, x, 3, "compared", D)
    assert repo.rank_placements(sid)[x] == (3, "compared")
    repo.unplace_film(sid, x)
    assert x not in repo.rank_placements(sid)
    repo.defer_film(sid, x, "2026-09-13")
    assert repo.rank_deferrals(sid) == {x: "2026-09-13"}
    repo.undefer_film(sid, x)
    assert repo.rank_deferrals(sid) == {}
    repo.set_last_action(sid, {"kind": "verdict", "film_id": x, "comparison_id": 2})
    assert repo.open_rank_session("owned").last_action == {"kind": "verdict", "film_id": x, "comparison_id": 2}
    repo.set_last_action(sid, None)
    assert repo.open_rank_session("owned").last_action is None
    assert repo.film_facts([x, ids[0]]) == {x: ("X", 2000, "Dir"), ids[0]: ("A", 1950, "Dir")}


def test_one_open_session_per_source(repo):
    import sqlite3

    import pytest

    repo.create_rank_session("owned", 1, {}, {}, D)
    with pytest.raises(sqlite3.IntegrityError):
        repo.create_rank_session("owned", 2, {}, {}, D)


def test_marking_unseen_drops_placements_in_every_session(repo):
    x = _owned_rated(repo, "X", 2000, 8)
    anchor = _owned_rated(repo, "Anchor", 2001, 8)
    sid = repo.create_rank_session("owned", 1, {3: anchor}, {x: 3}, D)
    repo.append_comparison(sid, x, anchor, 3, "better", D)
    repo.set_unseen(x, True, D)
    assert repo.rank_placements(sid) == {}
    assert repo.verdicts_for(sid, x) == []


def test_replace_list_entries_rewrites_the_slug_with_links(repo):
    a, b = _film(repo, "A", 1950), _film(repo, "B", 1960)
    repo.upsert_film_list(ListMeta("my-owned-tiers", "Mine", "me", 2026, None, True), D)
    repo.set_list_trust("my-owned-tiers", 3)
    repo.replace_list_entries("my-owned-tiers", [TieredEntry(1, a, "A", "Dir", "=1"), TieredEntry(2, b, "B", "Dir", "=1")])
    repo.replace_list_entries("my-owned-tiers", [TieredEntry(1, b, "B", "Dir", None)])
    rows = repo.list_entries("my-owned-tiers")
    assert [(r.rank, r.film_id, r.rank_label) for r in rows] == [(1, b, None)]
    repo.upsert_film_list(ListMeta("my-owned-tiers", "Mine again", "me", 2026, None, True), D)
    assert repo.film_list("my-owned-tiers").trust == 3


def test_merge_moves_rank_rows_survivor_wins(repo):
    a, b = _film(repo, "Alpha", 1950), _film(repo, "Alpha", 1951)
    sid = repo.create_rank_session("owned", 1, {3: b}, {a: 2, b: 4}, D)
    repo.append_comparison(sid, b, a, 3, "worse", D)
    repo.defer_film(sid, b, "2026-09-13")
    repo.merge_film(b, a, D)
    assert repo.rank_placements(sid) == {a: (2, "seed")}  # survivor's row wins, loser's dropped
    assert repo.rank_anchors(sid)[3] == a
    assert repo.rank_deferrals(sid) == {a: "2026-09-13"}
    with repo._conn() as c:
        row = c.execute("SELECT film_id, anchor_film_id FROM rank_comparison WHERE session_id = ?", (sid,)).fetchone()
    assert (row["film_id"], row["anchor_film_id"]) == (a, a)


def test_merge_drops_losers_verdicts_when_survivor_is_also_mid_search(repo):
    """Finding 1a: loser and survivor both mid-search (unplaced, with verdicts) in the same
    open session. A concatenated log would make the survivor's next `next_step` call raise."""
    a, b = _film(repo, "Alpha", 1950), _film(repo, "Alpha", 1951)
    anchor = _film(repo, "Anchor", 1960)
    third = _film(repo, "Gamma", 1970)
    sid = repo.create_rank_session("owned", 1, {3: anchor}, {}, D)
    repo.append_comparison(sid, a, anchor, 3, "better", D)
    repo.append_comparison(sid, b, anchor, 3, "worse", D)
    repo.append_comparison(sid, third, b, 3, "worse", D)  # b was also serving as an anchor
    report = repo.merge_film(b, a, D)
    assert repo.verdicts_for(sid, a) == ["better"]  # unchanged, ITS OWN list
    assert repo.verdicts_for(sid, b) == []  # loser's rows gone
    with repo._conn() as c:
        row = c.execute(
            "SELECT anchor_film_id FROM rank_comparison WHERE session_id = ? AND film_id = ?", (sid, third)
        ).fetchone()
    assert row["anchor_film_id"] == a  # anchor_film_id re-points unconditionally
    assert report.dropped.get("rank_comparison") == 1


def test_merge_onto_an_already_unseen_survivor_purges_the_losers_rank_rows(repo):
    # The mirror of test_merge_moves_unseen_survivor_wins: the SURVIVOR is the unseen one and the
    # LOSER is placed and mid-search. The cascade must run after the loser's rank rows have moved,
    # or the unseen survivor comes out of the merge holding a placement a Save would write.
    a = _film(repo, "Alpha", 1950)
    b = _film(repo, "Alpha", 1951)
    anchor = _film(repo, "Anchor", 1960)
    sid = repo.create_rank_session("owned", 1, {3: anchor}, {b: 2}, D)
    repo.append_comparison(sid, b, anchor, 3, "worse", D)
    repo.set_unseen(a, True, D)
    repo.merge_film(b, a, D)
    assert repo.unseen_film_ids() == {a}
    assert repo.rank_placements(sid) == {}
    assert repo.verdicts_for(sid, a) == []


def _order_session(repo, n=4):
    """A session whose tier 1 holds n seeded films; returns (sid, [film ids])."""
    ids = [_film(repo, f"T{i}", 1950 + i) for i in range(n)]
    sid = repo.create_rank_session("owned", 1, {1: ids[0]}, {i: 1 for i in ids}, D)
    return sid, ids


def test_insert_ordered_keeps_positions_dense_and_shifts_later_rows(repo):
    sid, (a, b, c, d) = _order_session(repo)
    repo.insert_ordered(sid, 1, a, 0, D)          # [a]
    repo.insert_ordered(sid, 1, b, 1, D)          # [a, b]  (append)
    repo.insert_ordered(sid, 1, c, 0, D)          # [c, a, b]
    repo.insert_ordered(sid, 1, d, 2, D)          # [c, a, d, b]
    assert repo.rank_order(sid, 1) == [c, a, d, b]
    with repo._conn() as conn:
        rows = conn.execute(
            "SELECT position FROM rank_order WHERE session_id = ? ORDER BY position", (sid,)
        ).fetchall()
    assert [r["position"] for r in rows] == [1, 2, 3, 4]
    assert repo.rank_order(sid, 2) == []


def test_remove_ordered_compacts_and_scopes_to_a_session(repo):
    sid, (a, b, c, _) = _order_session(repo)
    other = repo.create_rank_session("list", 2, {1: a}, {a: 1, b: 1}, D)   # a second source: "owned" allows one open session
    for s in (sid, other):
        repo.insert_ordered(s, 1, a, 0, D)
        repo.insert_ordered(s, 1, b, 1, D)
    repo.insert_ordered(sid, 1, c, 2, D)
    assert repo.remove_ordered(a, sid) == 1
    assert repo.rank_order(sid, 1) == [b, c] and repo.rank_order(other, 1) == [a, b]
    assert repo.remove_ordered(b) == 2   # every session
    assert repo.rank_order(sid, 1) == [c] and repo.rank_order(other, 1) == [a]
    assert repo.remove_ordered(999) == 0


def test_order_comparisons_log_in_order_and_delete_by_id(repo):
    sid, (a, b, c, _) = _order_session(repo)
    i1 = repo.append_order_comparison(sid, 1, c, a, "better", D)
    i2 = repo.append_order_comparison(sid, 1, c, b, "worse", D)
    assert repo.order_verdicts_for(sid, c) == [(a, "better"), (b, "worse")]
    assert repo.films_with_order_verdicts(sid) == {c}
    repo.delete_order_comparison(i2)
    assert repo.order_verdicts_for(sid, c) == [(a, "better")]
    assert i1 < i2


def test_order_deferrals_round_trip(repo):
    sid, (a, b, _, _) = _order_session(repo)
    repo.defer_order_film(sid, a, "2026-09-13")
    repo.defer_order_film(sid, b, "2026-09-14")
    assert repo.order_deferrals(sid) == {a: "2026-09-13", b: "2026-09-14"}
    repo.undefer_order_film(sid, a)
    assert repo.order_deferrals(sid) == {b: "2026-09-14"}
    assert repo.rank_deferrals(sid) == {}   # the tiering's own table is untouched


def test_marking_unseen_removes_the_film_from_the_order_and_every_verdict_naming_it(repo):
    sid, (a, b, c, d) = _order_session(repo)
    repo.insert_ordered(sid, 1, a, 0, D)
    repo.insert_ordered(sid, 1, b, 1, D)
    repo.insert_ordered(sid, 1, c, 2, D)
    repo.append_order_comparison(sid, 1, d, b, "better", D)   # d mid-search, against b
    repo.append_order_comparison(sid, 1, b, a, "worse", D)    # b's own old verdict
    repo.defer_order_film(sid, b, "2026-09-13")
    repo.set_unseen(b, True, D)
    assert repo.rank_order(sid, 1) == [a, c]
    assert repo.order_verdicts_for(sid, d) == []   # the verdict AGAINST b is gone too
    assert repo.order_verdicts_for(sid, b) == []
    assert repo.order_deferrals(sid) == {}


def test_merge_moves_the_order_survivor_wins_and_compacts(repo):
    a, b = _film(repo, "Alpha", 1950), _film(repo, "Alpha", 1951)
    c = _film(repo, "Gamma", 1960)
    sid = repo.create_rank_session("owned", 1, {1: a}, {a: 1, b: 1, c: 1}, D)
    repo.insert_ordered(sid, 1, a, 0, D)
    repo.insert_ordered(sid, 1, b, 1, D)
    repo.insert_ordered(sid, 1, c, 2, D)          # [a, b, c]
    repo.defer_order_film(sid, b, "2026-09-13")
    repo.merge_film(b, a, D)
    assert repo.rank_order(sid, 1) == [a, c]      # survivor's row wins, loser's dropped, gap closed
    assert repo.order_deferrals(sid) == {a: "2026-09-13"}
    other = repo.create_rank_session("list", 2, {1: c}, {c: 1}, D)   # a second session: loser only
    d, e = _film(repo, "Delta", 1970), _film(repo, "Delta", 1971)
    repo.insert_ordered(other, 1, e, 0, D)
    repo.merge_film(e, d, D)
    assert repo.rank_order(other, 1) == [d]       # loser's row moves when the survivor has none


def test_merge_drops_verdicts_naming_the_loser_and_moves_the_losers_own_log_survivor_wins(repo):
    a, b = _film(repo, "Alpha", 1950), _film(repo, "Alpha", 1951)
    c, x = _film(repo, "Gamma", 1960), _film(repo, "Xi", 1970)
    sid = repo.create_rank_session("owned", 1, {1: a}, {a: 1, b: 1, c: 1, x: 1}, D)
    repo.append_order_comparison(sid, 1, c, b, "better", D)   # c judged against the loser → deleted
    repo.append_order_comparison(sid, 1, b, x, "worse", D)    # loser mid-search → survivor-wins on the candidate side
    repo.append_order_comparison(sid, 1, a, b, "worse", D)    # survivor judged against the loser → deleted
    report = repo.merge_film(b, a, D)
    # Three drops, in the order the code applies them: the candidate loop runs first and a
    # already holds a candidate row (a-vs-b), so b's own row (b-vs-x) is DROPPED, not moved
    # (survivor wins per session) — 1. Then every row naming b on the OTHER side goes, which
    # is c-vs-b and a-vs-b — 3. Nothing survives to compare a with itself, so the self-delete
    # adds none.
    assert repo.order_verdicts_for(sid, c) == []
    assert repo.order_verdicts_for(sid, a) == []
    assert repo.order_verdicts_for(sid, b) == []
    assert report.dropped.get("rank_order_comparison") == 3
    assert report.moved.get("rank_order_comparison") is None


def test_merge_drops_losers_order_verdicts_when_survivor_is_also_mid_insertion(repo):
    a, b = _film(repo, "Alpha", 1950), _film(repo, "Alpha", 1951)
    x = _film(repo, "Xi", 1970)
    sid = repo.create_rank_session("owned", 1, {1: x}, {a: 1, b: 1, x: 1}, D)
    repo.append_order_comparison(sid, 1, a, x, "better", D)
    repo.append_order_comparison(sid, 1, b, x, "worse", D)
    repo.merge_film(b, a, D)
    assert repo.order_verdicts_for(sid, a) == [(x, "better")]   # its OWN log, untouched
    assert repo.order_verdicts_for(sid, b) == []


def test_merge_drops_a_third_partys_verdict_against_the_loser_leaving_no_contradiction(repo):
    a, b = _film(repo, "Alpha", 1950), _film(repo, "Alpha", 1951)
    x = _film(repo, "Xi", 1970)
    sid = repo.create_rank_session("owned", 1, {1: a}, {a: 1, b: 1, x: 1}, D)
    repo.insert_ordered(sid, 1, a, 0, D)
    repo.insert_ordered(sid, 1, b, 1, D)          # [a, b]
    repo.append_order_comparison(sid, 1, x, a, "worse", D)    # x already judged against the survivor
    repo.append_order_comparison(sid, 1, x, b, "better", D)   # x also judged against the loser → deleted
    repo.merge_film(b, a, D)
    # Unchanged arithmetic under the delete-everything rule: x's b-row goes either way (before,
    # because x already held an a-row; now, because it names the loser at all), so x keeps only
    # its verdict against the survivor. Re-pointing it would have made x both worse than a and
    # better than a on the collapsed order [a] — crossed bounds, and `order_step` would raise.
    assert repo.order_verdicts_for(sid, x) == [(a, "worse")]
    assert repo.rank_order(sid, 1) == [a]
    assert order_step(repo.rank_order(sid, 1), repo.order_verdicts_for(sid, x)) == Insert(1)


def test_merge_deletes_verdicts_against_the_loser_so_a_bystanders_bounds_cannot_cross(repo):
    s, d = _film(repo, "Sigma", 1950), _film(repo, "Delta", 1951)
    e, lam = _film(repo, "Epsilon", 1952), _film(repo, "Lambda", 1953)
    x = _film(repo, "Xi", 1970)
    sid = repo.create_rank_session("owned", 1, {1: s}, {s: 1, d: 1, e: 1, lam: 1, x: 1}, D)
    for pos, fid in enumerate((s, d, e, lam)):
        repo.insert_ordered(sid, 1, fid, pos, D)               # [s, d, e, lam]
    repo.append_order_comparison(sid, 1, x, d, "worse", D)     # lo = index(d) + 1 = 2
    repo.append_order_comparison(sid, 1, x, lam, "better", D)    # hi = index(lam) = 3 → Probe(e)
    repo.merge_film(lam, s, D)
    # lam leaves the order (s already holds a row, so the loser's is dropped and the gap closed).
    # Re-pointing x's lam-row onto s would move the verdict from index 3 to index 0: x would be
    # worse than d (lo 2) and better than s (hi 0), crossed bounds, and x would be corrupt
    # forever. Deleting it instead costs x one re-probe and keeps the bounds derivable.
    assert repo.rank_order(sid, 1) == [s, d, e]
    assert repo.order_verdicts_for(sid, x) == [(d, "worse")]
    assert order_step(repo.rank_order(sid, 1), repo.order_verdicts_for(sid, x)) == Probe(e)


def test_merge_onto_an_unseen_survivor_purges_the_losers_order_rows(repo):
    a, b = _film(repo, "Alpha", 1950), _film(repo, "Alpha", 1951)
    x = _film(repo, "Xi", 1970)
    sid = repo.create_rank_session("owned", 1, {1: x}, {b: 1, x: 1}, D)
    repo.insert_ordered(sid, 1, x, 0, D)
    repo.insert_ordered(sid, 1, b, 1, D)
    repo.append_order_comparison(sid, 1, b, x, "worse", D)
    repo.set_unseen(a, True, D)
    repo.merge_film(b, a, D)
    assert repo.rank_order(sid, 1) == [x]
    assert repo.order_verdicts_for(sid, a) == [] and repo.order_verdicts_for(sid, b) == []
