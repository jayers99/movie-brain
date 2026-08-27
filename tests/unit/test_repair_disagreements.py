import json
import sqlite3

import pytest
import requests

from movie_brain.application.repair import (
    DisagreementContract,
    audit_disagreements,
    format_disagreement,
    load_disagreement_contract,
)
from movie_brain.application.thumbprint import parse_review_detail
from movie_brain.domain.models import Film
from movie_brain.domain.thumbprint import Candidate
from movie_brain.infrastructure.database import OmdbRating, TmdbFactsRow
from movie_brain.infrastructure.tmdb import AuthError

HEADER = "group,film_id,source,title_ingested,year_ingested,expected_tt,expected_tmdb,verified_by,note,status,director,runtime_min\n"


def _csv(tmp_path, *rows):
    p = tmp_path / "eval.csv"
    p.write_text(HEADER + "".join(r + "\n" for r in rows), encoding="utf-8")
    return p


def _found_rating(tt: str) -> OmdbRating:
    return OmdbRating(7.0, 80, True, "English", json.dumps({"imdbID": tt, "Title": "x"}))


def _facts(tmdb_id: int, tt: str) -> TmdbFactsRow:
    return TmdbFactsRow(tmdb_id, tt, "T", "T", (), 2000, None)


def test_load_contract_keeps_every_d_row(tmp_path):
    p = _csv(
        tmp_path,
        "D-disagree,7,criterion,Bound,1995,tt0112565,,x,note,verified,Kimi Takesue,",
        "D-disagree,8,criterion,Resurrection,,,,?,note,proposed,,",
        "C-edition,9,apple,Blade Runner (Final Cut),2007,tt1,2,x,work='Blade Runner' 1982,verified,,",
    )
    c = load_disagreement_contract(p)
    assert set(c) == {7, 8}
    assert c[7] == DisagreementContract(7, "verified", "tt0112565", None, "Bound", 1995, "criterion", "Kimi Takesue")
    assert c[8].status == "proposed" and c[8].year_ingested is None and c[8].director is None


def _split(repo, today, title, omdb_tt, tmdb_tt, tmdb_id):
    fid = repo.create_film(Film(title, 2000, None, ""))
    repo.upsert_omdb(fid, _found_rating(omdb_tt), today)      # same helpers as test_database Task 3
    repo.set_external_id(fid, "tmdb", str(tmdb_id), today)
    repo.upsert_tmdb_facts(fid, _facts(tmdb_id, tmdb_tt), today)
    return fid


def _contract(fid, tt, tmdb=None, status="verified"):
    return DisagreementContract(fid, status, tt, tmdb, "T", 2000, "criterion", None)


def test_verdicts_follow_the_contract_row(repo, today):
    refetch = _split(repo, today, "Refetch", "ttA", "ttB", 1)
    relink = _split(repo, today, "Relink", "ttC", "ttD", 2)
    adopt = _split(repo, today, "Adopt", "ttE", "ttF", 3)
    adopt_no_tmdb = _split(repo, today, "Adopt2", "ttG", "ttH", 4)
    proposed = _split(repo, today, "Proposed", "ttI", "ttJ", 5)
    none = _split(repo, today, "None", "ttK", "ttL", 6)
    orphan = _split(repo, today, "Orphan", "ttM", "ttN", 7)
    held = _split(repo, today, "Held", "ttO", "ttP", 8)
    other = repo.create_film(Film("Other", 1999, None, ""))
    repo.set_external_id(other, "imdb", "ttQ", today)
    contract = {
        refetch: _contract(refetch, "ttB"),
        relink: _contract(relink, "ttC"),
        adopt: _contract(adopt, "ttZ", "99"),
        adopt_no_tmdb: _contract(adopt_no_tmdb, "ttY"),
        proposed: _contract(proposed, "ttJ", status="proposed"),
        none: _contract(none, "NONE"),
        held: _contract(held, "ttQ"),
    }
    got = {g.film_id: g.verdict for g in audit_disagreements(repo, contract)}
    assert got == {
        refetch: "refetch", relink: "relink", adopt: "adopt", adopt_no_tmdb: "conflict",
        proposed: "review", none: "review", orphan: "conflict", held: "conflict",
    }
    line = format_disagreement(next(g for g in audit_disagreements(repo, contract) if g.film_id == held))
    assert line.startswith("[conflict]") and f"held by #{other}" in line


def test_expected_tmdb_held_by_another_film_is_a_conflict(repo, today):
    fid = _split(repo, today, "Adopt", "ttE", "ttF", 3)
    other = repo.create_film(Film("Other", 1999, None, ""))
    repo.set_external_id(other, "tmdb", "99", today)
    contract = {fid: _contract(fid, "ttZ", "99")}
    g = next(g for g in audit_disagreements(repo, contract) if g.film_id == fid)
    assert g.verdict == "conflict" and g.detail == f"tmdb 99 held by #{other}"
    assert f"tmdb 99 held by #{other}" in format_disagreement(g)


# --- apply paths (Task 5) ------------------------------------------------------------------


class FakeTmdb:
    def __init__(self, by_imdb=None, years=None):
        self.by_imdb, self.years = by_imdb or {}, years or {}

    def find_by_imdb(self, tt):
        return self.by_imdb.get(tt)

    def movie_year(self, tid):
        return self.years.get(tid)


def _needs_refresh(repo, film_id) -> bool:
    with sqlite3.connect(repo.db_path) as c:
        row = c.execute("SELECT needs_refresh FROM omdb WHERE film_id = ?", (film_id,)).fetchone()
    return bool(row and row[0])


def _run(repo, today, contract, tmdb=None, apply=True, limit=None):
    from movie_brain.application.repair import repair_disagreements

    lines = []
    rep = repair_disagreements(
        repo, today, apply=apply, confirm=lambda g: True, contract=contract, tmdb=tmdb, fetcher=None, limit=limit,
        log=lines.append,
    )
    return rep, lines


def test_refetch_writes_imdb_and_marks_refresh(repo, today):
    fid = _split(repo, today, "Refetch", "ttA", "ttB", 1)
    rep, _ = _run(repo, today, {fid: _contract(fid, "ttB")})
    assert (rep.refetch, rep.applied) == (1, 1)
    assert repo.external_ids_for(fid)["imdb"] == "ttB"
    assert _needs_refresh(repo, fid)
    # OMDb still names ttA until the next sync refetches by id, so the film stays on the worklist.
    assert [f.id for f in repo.key_disagreements()] == [fid]


def test_refetch_is_idempotent(repo, today):
    fid = _split(repo, today, "Refetch", "ttA", "ttB", 1)
    c = {fid: _contract(fid, "ttB")}
    _run(repo, today, c)
    rep, _ = _run(repo, today, c)
    # The second run re-lists the film as pending (the OMDb payload only changes on the next
    # sync) and writes nothing more.
    assert (rep.refetch, rep.pending, rep.applied) == (0, 1, 0)
    assert repo.external_ids_for(fid)["imdb"] == "ttB"


def test_relink_uses_find_by_imdb_and_moves_tmdb(repo, today):
    fid = _split(repo, today, "Relink", "ttC", "ttD", 2)
    rep, lines = _run(repo, today, {fid: _contract(fid, "ttC")}, tmdb=FakeTmdb({"ttC": 77}, {77: 2000}))
    ids = repo.external_ids_for(fid)
    assert (ids["imdb"], ids["tmdb"]) == ("ttC", "77")
    assert rep.applied == 1 and any("relinked" in ln for ln in lines)


def test_relink_without_tmdb_record_clears_and_keys_imdb(repo, today):
    fid = _split(repo, today, "Relink", "ttC", "ttD", 2)
    _, lines = _run(repo, today, {fid: _contract(fid, "ttC")}, tmdb=FakeTmdb({}))
    ids = repo.external_ids_for(fid)
    assert ids["imdb"] == "ttC" and "tmdb" not in ids
    assert any("unlinked tmdb" in ln for ln in lines)


def test_adopt_records_both_ids_and_refreshes(repo, today):
    fid = _split(repo, today, "Adopt", "ttE", "ttF", 3)
    _run(repo, today, {fid: _contract(fid, "ttZ", "99")}, tmdb=FakeTmdb({}, {99: 2000}))
    ids = repo.external_ids_for(fid)
    assert (ids["imdb"], ids["tmdb"]) == ("ttZ", "99") and _needs_refresh(repo, fid)


def test_criterion_listed_adopt_never_rekeys(repo, today):
    # record_tmdb_match's commerce guard: a Criterion-listed film keeps its year/key even when TMDB's year differs
    fid = _split(repo, today, "Listed", "ttE", "ttF", 3)
    repo.record_catalog("criterion", [Film("Listed", 2000, None, "https://x/listed")], today)
    view = repo.get_view(fid, today)
    assert view is not None and view.criterion
    before = view.year
    _run(repo, today, {fid: _contract(fid, "ttZ", "99")}, tmdb=FakeTmdb({}, {99: 1950}))
    after = repo.get_view(fid, today)
    assert after is not None and after.year == before == 2000


def test_proposed_row_becomes_durable_review_once(repo, today):
    fid = _split(repo, today, "Proposed", "ttI", "ttJ", 5)
    c = {fid: _contract(fid, "ttJ", status="proposed")}
    _run(repo, today, c)
    _run(repo, today, c)
    rows = [r for r in repo.open_reviews("tmdb") if r["reason"] == "key-disagreement"]
    assert len(rows) == 1 and rows[0]["film_id"] == fid and rows[0]["value"] == "ttJ"
    from movie_brain.application.thumbprint import parse_review_detail

    parsed = parse_review_detail(str(rows[0]["detail"]))
    assert parsed is not None and parsed.query["title"] == "T" and parsed.reason == "no candidates"
    assert repo.external_ids_for(fid).get("imdb") is None  # never keyed


def test_verified_none_review_records_none_as_its_value(repo, today):
    fid = _split(repo, today, "None", "ttK", "ttL", 6)
    _run(repo, today, {fid: _contract(fid, "NONE")})
    rows = [r for r in repo.open_reviews("tmdb") if r["reason"] == "key-disagreement"]
    assert len(rows) == 1 and rows[0]["value"] == "NONE"


def test_dry_run_writes_nothing(repo, today):
    fid = _split(repo, today, "Refetch", "ttA", "ttB", 1)
    rep, lines = _run(repo, today, {fid: _contract(fid, "ttB")}, apply=False)
    assert rep.applied == 0 and "imdb" not in repo.external_ids_for(fid) and lines[0].startswith("[refetch]")


def test_dry_run_never_queues_a_review(repo, today):
    fid = _split(repo, today, "Proposed", "ttI", "ttJ", 5)
    _run(repo, today, {fid: _contract(fid, "ttJ", status="proposed")}, apply=False)
    assert [r for r in repo.open_reviews("tmdb") if r["reason"] == "key-disagreement"] == []


def test_relink_needs_a_client(repo, today):
    fid = _split(repo, today, "Relink", "ttC", "ttD", 2)
    rep, lines = _run(repo, today, {fid: _contract(fid, "ttC")}, tmdb=None)
    assert rep.applied == 0 and any("no TMDB client" in ln for ln in lines) and "imdb" not in repo.external_ids_for(fid)


def test_conflict_is_never_touched_and_limit_trims(repo, today):
    a = _split(repo, today, "Refetch", "ttA", "ttB", 1)
    b = _split(repo, today, "Orphan", "ttM", "ttN", 7)
    rep, _ = _run(repo, today, {a: _contract(a, "ttB")})
    assert (rep.groups, rep.conflict, rep.applied) == (2, 1, 1)
    assert "imdb" not in repo.external_ids_for(b)
    c = _split(repo, today, "Second", "ttC", "ttD", 9)
    d = _split(repo, today, "Third", "ttE", "ttF", 10)
    contract = {a: _contract(a, "ttB"), c: _contract(c, "ttD"), d: _contract(d, "ttF")}
    limited, lines = _run(repo, today, contract, apply=False, limit=1)
    # one actionable group past the two non-actionable ones (conflict + the applied pending)
    assert (limited.groups, limited.refetch) == (3, 1) and len(lines) == 3


def test_declined_groups_are_counted_not_applied(repo, today):
    from movie_brain.application.repair import repair_disagreements

    fid = _split(repo, today, "Refetch", "ttA", "ttB", 1)
    rep = repair_disagreements(
        repo, today, apply=True, confirm=lambda g: False, contract={fid: _contract(fid, "ttB")},
        tmdb=None, fetcher=None, log=lambda m: None,
    )
    assert (rep.applied, rep.declined) == (0, 1) and "imdb" not in repo.external_ids_for(fid)


# --- fix round 1: nothing-written skips, the [partial] half-state, live-resolver evidence -----


class BoomTmdb(FakeTmdb):
    """A client whose calls fail the way a dead token / dead network does."""

    def __init__(self, exc, *, on="find"):
        super().__init__({}, {})
        self.exc, self.on = exc, on

    def find_by_imdb(self, tt):
        if self.on == "find":
            raise self.exc
        return 77

    def movie_year(self, tid):
        if self.on == "year":
            raise self.exc
        return 2000


def test_relink_never_writes_into_a_held_tmdb_id(repo, today):
    fid = _split(repo, today, "Relink", "ttC", "ttD", 2)
    other = repo.create_film(Film("Other", 1999, None, ""))
    repo.set_external_id(other, "tmdb", "77", today)
    rep, lines = _run(repo, today, {fid: _contract(fid, "ttC")}, tmdb=FakeTmdb({"ttC": 77}, {77: 2000}))
    assert rep.applied == 0 and any(f"tmdb 77 held by #{other} — skipped (conflict)" in ln for ln in lines)
    ids = repo.external_ids_for(fid)
    assert "imdb" not in ids and ids["tmdb"] == "2"           # nothing written at all
    assert [f.id for f in repo.key_disagreements()] == [fid]  # still visible as a disagreement


def test_tmdb_errors_are_a_skip_not_a_half_apply(repo, today):
    for on, exc in (("find", requests.ConnectionError("boom")), ("year", AuthError("bad token"))):
        fid = _split(repo, today, f"Relink-{on}", "ttC" + on, "ttD" + on, 20 if on == "find" else 21)
        rep, lines = _run(repo, today, {fid: _contract(fid, "ttC" + on)}, tmdb=BoomTmdb(exc, on=on))
        assert rep.applied == 0 and any("TMDB error" in ln and "skipped" in ln for ln in lines)
        ids = repo.external_ids_for(fid)
        assert "imdb" not in ids and ids["tmdb"] == str(20 if on == "find" else 21)


def test_fetcher_failure_still_writes_an_evidence_free_review(repo, today):
    class Boom:
        def fetch(self, q):
            raise requests.ConnectionError("boom")

    fid = _split(repo, today, "Proposed", "ttI", "ttJ", 5)
    from movie_brain.application.repair import repair_disagreements

    repair_disagreements(
        repo, today, apply=True, confirm=lambda g: True,
        contract={fid: _contract(fid, "ttJ", status="proposed")}, tmdb=None, fetcher=Boom(), log=lambda m: None,
    )
    rows = [r for r in repo.open_reviews("tmdb") if r["reason"] == "key-disagreement"]
    parsed = parse_review_detail(str(rows[0]["detail"]))
    assert len(rows) == 1 and parsed is not None and parsed.reason.startswith("no candidates (")


def test_partial_tmdb_write_raises_after_the_imdb_id_landed(repo, today):
    # adopt on a commerce film whose TMDB year (1950) collides with another film's key →
    # record_tmdb_match returns "collision" AFTER claiming the tmdb id: a real half-state.
    fid = _split(repo, today, "Adopt", "ttE", "ttF", 3)
    repo.create_film(Film("Adopt", 1950, None, ""))
    with pytest.raises(RuntimeError) as exc:
        _run(repo, today, {fid: _contract(fid, "ttZ", "99")}, tmdb=FakeTmdb({}, {99: 1950}))
    assert str(exc.value).startswith("[partial]") and "collision" in str(exc.value)
    assert repo.external_ids_for(fid)["imdb"] == "ttZ"  # the documented half-state


def test_two_rows_wanting_one_tt_skip_the_loser(repo, today):
    a = _split(repo, today, "A", "ttA", "ttSHARED", 1)
    b = _split(repo, today, "B", "ttB", "ttSHARED", 2)
    rep, lines = _run(repo, today, {a: _contract(a, "ttSHARED"), b: _contract(b, "ttSHARED")})
    assert rep.applied == 1 and any("ttSHARED already held — skipped (conflict)" in ln for ln in lines)
    assert repo.external_ids_for(a)["imdb"] == "ttSHARED" and "imdb" not in repo.external_ids_for(b)


def test_verified_row_with_a_blank_tt_is_a_conflict(repo, today):
    fid = _split(repo, today, "Blank", "ttE", "ttF", 3)
    g = next(g for g in audit_disagreements(repo, {fid: _contract(fid, "", "99")}) if g.film_id == fid)
    assert (g.verdict, g.detail) == ("conflict", "no expected_tt")
    _run(repo, today, {fid: _contract(fid, "", "99")}, tmdb=FakeTmdb({}, {99: 2000}))
    assert "imdb" not in repo.external_ids_for(fid)


def _cand(tt, tmdb_id, title, year):
    return Candidate(tt, tmdb_id, (title,), year, "Dir", 100, 500, "movie", True, True, title)


def test_review_detail_carries_the_live_resolver_ranking(repo, today):
    class TwoHits:
        def fetch(self, q):
            return [_cand("tt1", 11, "T", 2000), _cand("tt2", 22, "T", 2001)]

    fid = _split(repo, today, "Proposed", "ttI", "ttJ", 5)
    from movie_brain.application.repair import repair_disagreements

    repair_disagreements(
        repo, today, apply=True, confirm=lambda g: True,
        contract={fid: _contract(fid, "ttJ", status="proposed")}, tmdb=None, fetcher=TwoHits(), log=lambda m: None,
    )
    row = next(r for r in repo.open_reviews("tmdb") if r["reason"] == "key-disagreement")
    parsed = parse_review_detail(str(row["detail"]))
    assert parsed is not None
    assert [c["letter"] for c in parsed.candidates] == ["A", "B"]
    assert {c["tt"] for c in parsed.candidates} == {"tt1", "tt2"}
    assert parsed.query == {"title": "T", "year": 2000, "source": "criterion", "director": None, "runtime": None}
    assert parsed.reason != "no candidates"  # the live resolver's own reason, not the CSV's note
    assert row["value"] == "ttJ"  # the proposed tt lives in `value`, never in the detail


# --- fix round 2: non-actionable verdicts so --limit batches advance -------------------------


def test_applied_refetch_becomes_pending_and_is_never_re_applied(repo, today):
    fid = _split(repo, today, "Refetch", "ttA", "ttB", 1)
    c = {fid: _contract(fid, "ttB")}
    _run(repo, today, c)
    rep, lines = _run(repo, today, c, apply=False)
    assert (rep.pending, rep.refetch, rep.applied) == (1, 0, 0)
    assert lines[0].startswith("[pending]") and "next sync" in lines[0]
    rep2, lines2 = _run(repo, today, c)
    assert (rep2.pending, rep2.applied) == (1, 0)
    assert lines2 == lines                                   # listed only, nothing written
    assert repo.external_ids_for(fid)["imdb"] == "ttB"


def test_open_review_makes_the_film_review_open_and_never_re_queues(repo, today, monkeypatch):
    import movie_brain.application.repair as mod

    fid = _split(repo, today, "Proposed", "ttI", "ttJ", 5)
    c = {fid: _contract(fid, "ttJ", status="proposed")}
    _run(repo, today, c)
    calls = []
    real = mod.queue_review_once
    monkeypatch.setattr(mod, "queue_review_once", lambda *a, **k: calls.append(a) or real(*a, **k))
    rep, lines = _run(repo, today, c)
    assert (rep.review_open, rep.review, rep.applied) == (1, 0, 0)
    assert calls == [] and lines[0].startswith("[review-open]")
    assert len([r for r in repo.open_reviews("tmdb") if r["reason"] == "key-disagreement"]) == 1


def test_limit_batches_advance_through_the_actionable_groups(repo, today):
    ids = [_split(repo, today, f"R{i}", f"ttA{i}", f"ttB{i}", 30 + i) for i in range(3)]
    c = {fid: _contract(fid, f"ttB{i}") for i, fid in enumerate(ids)}
    keyed = []
    for _ in range(3):
        _run(repo, today, c, limit=1)
        keyed.append({fid for fid in ids if "imdb" in repo.external_ids_for(fid)})
    assert [len(k) for k in keyed] == [1, 2, 3]              # one NEW film per batch
    rep, _ = _run(repo, today, c, apply=False)
    assert (rep.pending, rep.groups, rep.applied) == (3, 3, 0)


def test_limit_never_hides_the_non_actionable_groups(repo, today):
    orphan = _split(repo, today, "Orphan", "ttM", "ttN", 7)
    a = _split(repo, today, "A", "ttA", "ttB", 8)
    b = _split(repo, today, "B", "ttC", "ttD", 9)
    c = {a: _contract(a, "ttB"), b: _contract(b, "ttD")}
    rep, lines = _run(repo, today, c, apply=False, limit=1)
    assert (rep.groups, rep.conflict, rep.refetch) == (2, 1, 1)
    assert [ln.split()[1] for ln in lines] == [f"#{orphan}", f"#{a}"]
