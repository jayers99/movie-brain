from __future__ import annotations

from datetime import date

from movie_brain.domain.models import Film, ListMeta, OmdbRating, TieredEntry

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
    got = {s.film_id: s for s in repo.owned_seed_films()}
    assert set(got) == {a, b}
    assert got[a].score == 10 and got[a].imdb == 8.1 and got[a].title == "Alpha" and got[a].year == 1950
    assert got[b].imdb is None


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
