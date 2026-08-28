from __future__ import annotations

import json
import sqlite3
from datetime import date

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application import review as rv
from movie_brain.application.availability import rebuild_no_match_queue
from movie_brain.application.repair import EditionContract, repair_editions, repair_twins
from movie_brain.application.repair_keys import repair_nomatch
from movie_brain.application.thumbprint import backfill_claims
from movie_brain.domain.models import Film, OmdbRating, ReviewEntry
from movie_brain.domain.thumbprint import Candidate

scenarios("../features/thumbprint.feature")
scenarios("../features/thumbprint_editions.feature")
scenarios("../features/thumbprint_nomatch.feature")

TODAY = date(2026, 8, 25)


@pytest.fixture
def ctx(repo, config_dir):
    (config_dir / "appletv").mkdir()
    return {"repo": repo, "config_dir": config_dir, "expected": {}, "applied": [], "log": []}


def _q(ctx, sql, *args):
    conn = sqlite3.connect(ctx["repo"].db_path)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


@given(parsers.parse('a film "{title}" ({year:d}) with a criterion listing and metacritic slug "{slug}"'))
def crit_film(ctx, title, year, slug):
    repo = ctx["repo"]
    repo.record_catalog("criterion", [Film(title, year, "Ridley Scott", f"https://c/{slug}")], TODAY)
    fid = repo.film_id_by_key(f"{title.lower()} ({year})")
    conn = sqlite3.connect(repo.db_path)
    conn.execute(
        "INSERT INTO metacritic (slug, title, year, score, rank, page, fetched_at) VALUES (?, ?, ?, 89, 1, 1, '2026-08-01')",
        (slug, title, year),
    )
    conn.commit()
    conn.close()
    repo.set_external_id(fid, "metacritic", slug, TODAY)
    ctx["clean"] = fid


@given(parsers.parse('an owned film "{raw}" from archive line "{line}"'))
def owned_from_archive(ctx, raw, line):
    from movie_brain.domain.matching import parse_apple_title

    cleaned, _ = parse_apple_title(raw)
    fid = ctx["repo"].create_film(Film(cleaned, 1982, None, "")) or ctx["repo"].film_id_by_key(
        f"{cleaned.lower()} (1982)"
    )
    ctx["repo"].mark_owned(fid, TODAY)
    (ctx["config_dir"] / "appletv" / "owned-2026-08-23.txt").write_text(line + "\n")


@given(parsers.parse('an owned film "{title}" ({year:d}) with no archive line'))
def owned_no_archive(ctx, title, year):
    fid = ctx["repo"].create_film(Film(title, year, None, ""))
    ctx["repo"].mark_owned(fid, TODAY)


@when("I run the claims backfill without --apply")
def backfill_dry(ctx):
    ctx["claims_before"] = _q(ctx, "SELECT COUNT(*) FROM claim")[0][0]
    ctx["report"] = backfill_claims(ctx["repo"], ctx["config_dir"], apply=False, log=ctx["log"].append)


@when("I run the claims backfill with --apply")
def backfill_apply(ctx):
    ctx["report"] = backfill_claims(ctx["repo"], ctx["config_dir"], apply=True, log=ctx["log"].append)


@when("I run the claims backfill with --apply twice")
def backfill_twice(ctx):
    backfill_apply(ctx)
    backfill_apply(ctx)


@then(parsers.parse("the backfill report says criterion {c:d}, metacritic {m:d}, apple {a:d}, editions {e:d}"))
def report_counts(ctx, c, m, a, e):
    r = ctx["report"]
    assert (r.criterion, r.metacritic, r.apple, r.editions) == (c, m, a, e)


@then(parsers.parse("there are exactly {n:d} claim rows"))
def claim_rows(ctx, n):
    assert _q(ctx, "SELECT COUNT(*) FROM claim")[0][0] == n


@then("the dry run added no claim rows")
def dry_run_added_none(ctx):
    after = _q(ctx, "SELECT COUNT(*) FROM claim")[0][0]
    assert after == ctx["claims_before"]


@then(parsers.parse('the apple claim has edition_label "{label}", year_claimed {y:d} and runtime_min {rt:d}'))
def apple_claim(ctx, label, y, rt):
    rows = _q(ctx, "SELECT edition_label, year_claimed, runtime_min FROM claim WHERE authority = 'apple-tv'")
    assert rows == [(label, y, rt)]


@then("every film has a title_norm")
def norms(ctx):
    assert _q(ctx, "SELECT COUNT(*) FROM films WHERE title_norm IS NULL")[0][0] == 0
    assert _q(ctx, "SELECT title_norm FROM films WHERE title = 'Blade Runner'")[0][0] == "bladerunner"


@then(parsers.parse('the apple claim for "{title}" has value "{value}" and the report says apple_unrecovered {n:d}'))
def unrecovered(ctx, title, value, n):
    rows = _q(
        ctx,
        "SELECT c.value FROM claim c JOIN films f ON f.id = c.film_id WHERE f.title = ? AND c.authority = 'apple-tv'",
        title,
    )
    assert rows == [(value,)]
    assert ctx["report"].apple_unrecovered == n


# --- twins ---------------------------------------------------------------------------------


@given(parsers.parse('a raw film "{raw}" year {year:d} with OMDb imdbID "{tt}" and an owned row'))
def raw_film(ctx, raw, year, tt):
    repo = ctx["repo"]
    fid = repo.create_film(Film(raw, year, None, ""))
    repo.upsert_omdb(fid, OmdbRating(7.0, 90, True, payload=json.dumps({"imdbID": tt, "Title": raw})), TODAY)
    repo.mark_owned(fid, TODAY)
    ctx["raw"] = fid


@given(parsers.parse('a clean film "{title}" ({year:d}) with TMDB imdb "{tt}"'))
def clean_film(ctx, title, year, tt):
    repo = ctx["repo"]
    fid = repo.create_film(Film(title, year, "Someone", ""))
    repo.set_external_id(fid, "imdb", tt, TODAY)
    ctx["twin"] = fid


@given("the contract expects the raw film's twin to be the clean film")
def expect_twin(ctx):
    ctx["expected"] = {ctx["raw"]: ctx["twin"]}


@given(parsers.parse("the contract expects the raw film's twin to be film {n:d}"))
def expect_other(ctx, n):
    ctx["expected"] = {ctx["raw"]: n}


@when("I run repair twins --apply answering yes")
def run_twins(ctx):
    ctx["twins"] = repair_twins(
        ctx["repo"],
        TODAY,
        apply=True,
        confirm=lambda g: True,
        expected=ctx["expected"],
        on_applied=ctx["applied"].append,
        log=ctx["log"].append,
    )


@then("the raw film is merged into the clean film, which is owned, and the raw film's year is 1954")
def merged(ctx):
    assert ctx["repo"].disposition_of(ctx["raw"]) == ("merged", ctx["twin"])
    assert ctx["twin"] in ctx["repo"].owned_film_ids()
    assert _q(ctx, "SELECT year FROM films WHERE id = ?", ctx["raw"])[0][0] == 1954


@then("the applied hook saw the raw film once")
def hook(ctx):
    assert [g.raw_id for g in ctx["applied"]] == [ctx["raw"]]


@then(parsers.parse('the raw film\'s verdict is "{verdict}" and it has no disposition'))
def verdict(ctx, verdict):
    line = next(line for line in ctx["log"] if f"#{ctx['raw']} " in line)
    assert line.startswith(f"[{verdict}]"), line
    assert ctx["repo"].disposition_of(ctx["raw"]) is None
    assert ctx["twins"].applied == 0


@then(parsers.parse('the raw film is titled "{title}" with imdb "{tt}" and has no disposition'))
def keyed(ctx, title, tt):
    assert _q(ctx, "SELECT title FROM films WHERE id = ?", ctx["raw"])[0][0] == title
    assert ctx["repo"].external_ids_for(ctx["raw"]) == {"imdb": tt}
    assert ctx["repo"].disposition_of(ctx["raw"]) is None


@given(parsers.parse('an archive line "{line}"'))
def archive_line(ctx, line):
    p = ctx["config_dir"] / "appletv" / "owned-2026-08-24.txt"
    p.write_text((p.read_text() if p.exists() else "") + line + "\n")


@then("the raw film is merged into the clean film")
def merged_plain(ctx):
    assert ctx["repo"].disposition_of(ctx["raw"]) == ("merged", ctx["twin"])


@then(parsers.parse('the apple claim "{value}" belongs to the film titled "{title}" with runtime_min {rt:d}'))
def claim_owner(ctx, value, title, rt):
    rows = _q(ctx, "SELECT f.title, c.runtime_min FROM claim c JOIN films f ON f.id = c.film_id WHERE c.value = ?", value)
    assert rows == [(title, rt)]


# --- editions ------------------------------------------------------------------------------


@given(parsers.parse('an edition film "{title}" year {year:d} from "{authority}" slug "{value}"'))
def edition_film(ctx, title, year, authority, value):
    from movie_brain.domain.thumbprint import parse_title, title_norm

    repo = ctx["repo"]
    fid = repo.create_film(Film(title, year, None, ""))
    assert fid is not None
    repo.set_title_norm(fid, title_norm(title))
    if authority != "apple-tv":
        repo.set_external_id(fid, authority, value, TODAY)
    repo.add_claim(
        fid,
        authority,
        value,
        title,
        year_claimed=year,
        edition_label=" ".join(parse_title(title).editions) or None,
        first_seen=TODAY.isoformat(),
    )
    ctx.setdefault("editions", []).append(fid)
    ctx["edition"] = fid


@given(parsers.parse('a work film "{title}" ({year:d}) with tmdb id "{tid}"'))
def work_film(ctx, title, year, tid):
    from movie_brain.domain.thumbprint import title_norm

    repo = ctx["repo"]
    fid = repo.create_film(Film(title, year, "Dir", ""))
    assert fid is not None
    repo.set_title_norm(fid, title_norm(title))
    repo.set_external_id(fid, "tmdb", tid, TODAY)
    ctx.setdefault("works", {})[(title, year)] = fid
    ctx["work"] = fid


@given(parsers.parse('the edition contract says the work is "{work}" {year:d} tt "{tt}" tmdb "{tid}"'))
def contract_one(ctx, work, year, tt, tid):
    ctx["contract"] = {ctx["edition"]: EditionContract(ctx["edition"], work, year, tt, tid)}


@given(parsers.parse('the edition contract says the work is "{work}" {year:d} tt "{tt}" tmdb "{tid}" for both'))
def contract_both(ctx, work, year, tt, tid):
    ctx["contract"] = {fid: EditionContract(fid, work, year, tt, tid) for fid in ctx["editions"]}


@given("the edition film has a criterion listing")
def edition_listing(ctx):
    repo = ctx["repo"]
    row = _q(ctx, "SELECT title, year FROM films WHERE id = ?", ctx["edition"])[0]
    url = _q(ctx, "SELECT value FROM external_ids WHERE film_id = ? AND authority = 'criterion'", ctx["edition"])[0][0]
    repo.record_catalog("criterion", [Film(row[0], row[1], None, url)], TODAY)
    assert repo.has_listing(ctx["edition"], "criterion")


@given("the edition film has an open tmdb no-match review")
def edition_review(ctx):
    from movie_brain.domain.models import ReviewEntry

    ctx["repo"].append_reviews("tmdb", [ReviewEntry("no-match", film_id=ctx["edition"], detail="x")], TODAY)


@when("I run repair editions --apply answering yes")
def run_editions(ctx):
    ctx["report"] = repair_editions(
        ctx["repo"], TODAY, apply=True, confirm=lambda g: True, contract=ctx["contract"], log=ctx["log"].append
    )


@then("the edition film is merged into the work film")
def edition_merged(ctx):
    assert ctx["repo"].disposition_of(ctx["edition"]) == ("merged", ctx["work"])


@then("both edition films are merged into the work film")
def both_editions_merged(ctx):
    assert [ctx["repo"].disposition_of(f) for f in ctx["editions"]] == [("merged", ctx["work"])] * 2


@then(
    parsers.parse(
        'the higher-id edition film is merged into the lower-id one, now titled "{title}" ({year:d}) with tmdb "{tid}"'
    )
)
def mutual_twins_break_low(ctx, title, year, tid):
    # two editions that are each other's fellow-contract twin: the pair is broken deterministically
    # toward the LOWER id, which survives and is re-keyed as the work
    lo, hi = sorted(ctx["editions"])
    repo = ctx["repo"]
    assert repo.disposition_of(hi) == ("merged", lo)
    assert repo.disposition_of(lo) is None
    assert tuple(_q(ctx, "SELECT title, year FROM films WHERE id = ?", lo)[0]) == (title, year)
    assert repo.external_ids_for(lo)["tmdb"] == tid


@then(parsers.parse('the edition film is merged into the work film "{title}" ({year:d})'))
def edition_merged_into(ctx, title, year):
    assert ctx["repo"].disposition_of(ctx["edition"]) == ("merged", ctx["works"][(title, year)])


@then(parsers.parse('the work film holds imdb "{tt}" and its metacritic claim has edition_year {y:d}'))
def work_keyed(ctx, tt, y):
    repo = ctx["repo"]
    assert repo.external_ids_for(ctx["work"])["imdb"] == tt
    assert repo.claim_for_film_authority(ctx["work"], "metacritic").edition_year == y


@then(parsers.parse('the work film\'s {authority} claim has edition_label "{label}" and no edition_year'))
def work_claim_label(ctx, authority, label):
    # a same-year fold: `merge_film` re-points the loser's claim onto the survivor, and the
    # label survives while `edition_year` stays NULL (old_year == work_year is not an edition year)
    claim = ctx["repo"].claim_for_film_authority(ctx["work"], authority)
    assert claim is not None and claim.edition_label == label and claim.edition_year is None


@then(parsers.parse("the editions report says twin {t:d}, no-twin {n:d}, conflict {c:d}, csv-mismatch {m:d}, applied {a:d}"))
def editions_report(ctx, t, n, c, m, a):
    r = ctx["report"]
    assert (r.twins, r.no_twin, r.conflict, r.csv_mismatch, r.applied) == (t, n, c, m, a)


@then(parsers.parse('the edition film is titled "{title}" year {year:d} with imdb "{tt}" and tmdb "{tid}" and no disposition'))
def edition_became_work(ctx, title, year, tt, tid):
    repo = ctx["repo"]
    row = _q(ctx, "SELECT title, year FROM films WHERE id = ?", ctx["edition"])[0]
    assert tuple(row) == (title, year)
    # the film keeps its source (claim-authority) id; only the key authorities are asserted
    ids = repo.external_ids_for(ctx["edition"])
    assert {k: v for k, v in ids.items() if k in ("imdb", "tmdb")} == {"imdb": tt, "tmdb": tid}
    assert repo.disposition_of(ctx["edition"]) is None


@then(parsers.parse("its {authority} claim has edition_year {y:d}"))
def claim_year(ctx, authority, y):
    assert ctx["repo"].claim_for_film_authority(ctx["edition"], authority).edition_year == y


@then(parsers.parse("its {authority} claim has no edition_year"))
def claim_no_year(ctx, authority):
    assert ctx["repo"].claim_for_film_authority(ctx["edition"], authority).edition_year is None


@then("its tmdb no-match review is resolved")
def review_resolved(ctx):
    assert not [r for r in ctx["repo"].open_reviews("tmdb") if r["film_id"] == ctx["edition"]]


@then(parsers.parse('the film "{loser}" is merged into the film now titled "{title}" ({year:d}) holding tmdb "{tid}"'))
def darko(ctx, loser, title, year, tid):
    repo = ctx["repo"]
    lid = next(f for f in ctx["editions"] if _q(ctx, "SELECT title FROM films WHERE id = ?", f)[0][0] == loser)
    sid = next(f for f in ctx["editions"] if f != lid)
    assert repo.disposition_of(lid) == ("merged", sid)
    assert tuple(_q(ctx, "SELECT title, year FROM films WHERE id = ?", sid)[0]) == (title, year)
    assert repo.external_ids_for(sid)["tmdb"] == tid


@then(parsers.parse('the edition film is still titled "{title}" and holds no imdb id'))
def edition_untouched(ctx, title):
    assert _q(ctx, "SELECT title FROM films WHERE id = ?", ctx["edition"])[0][0] == title
    assert "imdb" not in ctx["repo"].external_ids_for(ctx["edition"])


@then(parsers.parse('the edition film\'s verdict is "{verdict}" and it has no disposition and year {year:d}'))
def edition_verdict(ctx, verdict, year):
    assert any(f"[{verdict}] #{ctx['edition']} " in line for line in ctx["log"]), ctx["log"]
    assert ctx["repo"].disposition_of(ctx["edition"]) is None
    assert _q(ctx, "SELECT year FROM films WHERE id = ?", ctx["edition"])[0][0] == year


# --- nomatch (T4) ----------------------------------------------------------------------


class _PoolFetcher:
    def __init__(self):
        self.pool = {}

    def fetch(self, q):
        return self.pool.get(q.title, [])


class _StubTmdb:
    def find_by_imdb(self, tt):
        return None

    def movie_year(self, tid):
        return {9081: 1996}.get(tid)


def _nomatch_film(ctx, title, year, director, authority):
    repo = ctx["repo"]
    fid = repo.create_film(Film(title, year, director, ""))
    repo.upsert_tmdb(fid, found=False, looked_up=TODAY)
    repo.upsert_omdb(fid, OmdbRating(None, None, False, None, None), TODAY)
    repo.append_reviews("tmdb", [ReviewEntry("no-match", film_id=fid, detail=f"{title} ({year})")], TODAY)
    repo.add_claim(fid, authority, f"{authority}:{title}", title, year_claimed=year, first_seen=TODAY.isoformat())
    ctx.setdefault("films", {})[title] = fid
    ctx.setdefault("pool", _PoolFetcher())


@given(parsers.parse('a no-match film "{title}" ({year:d}) directed by "{director}" with a criterion claim'))
def nomatch_crit(ctx, title, year, director):
    _nomatch_film(ctx, title, year, director, "criterion")


@given(parsers.parse('a no-match film "{title}" ({year:d}) with a metacritic claim'))
def nomatch_mc(ctx, title, year):
    _nomatch_film(ctx, title, year, None, "metacritic")


@given(parsers.parse('the candidate pool has "{title}" → {tt}/{tid:d} {year:d} by "{director}"'))
def pool_one(ctx, title, tt, tid, year, director):
    ctx["pool"].pool[title] = [Candidate(tt, tid, (title,), year, director, 100, 5000, "movie", True, True)]


@given(parsers.parse('the candidate pool has "{title}" → {tta}/{ida:d} {ya:d} and {ttb}/{idb:d} {yb:d}'))
def pool_two(ctx, title, tta, ida, ya, ttb, idb, yb):
    ctx["pool"].pool[title] = [
        Candidate(tta, ida, (title,), ya, "", 100, 50, "movie", True, True),
        Candidate(ttb, idb, (title,), yb, "", 100, 60, "movie", True, True),
    ]


def _run_nomatch(ctx, apply):
    ctx["nomatch_report"] = repair_nomatch(
        ctx["repo"], TODAY, apply=apply, confirm=lambda g: True, tmdb=_StubTmdb(), fetcher=ctx["pool"],
        log=ctx["log"].append,
    )


@when("I run repair nomatch without --apply")
def nomatch_dry(ctx):
    _run_nomatch(ctx, False)


@when("I run repair nomatch --apply answering yes")
@given("I ran repair nomatch --apply answering yes")
def nomatch_apply(ctx):
    _run_nomatch(ctx, True)


@then(parsers.parse("the nomatch report says match {m:d}, review {r:d}, applied {a:d}"))
def nomatch_report(ctx, m, r, a):
    rep = ctx["nomatch_report"]
    assert (rep.match, rep.review, rep.applied) == (m, r, a)


@then("no film holds an imdb id")
def no_imdb(ctx):
    assert _q(ctx, "SELECT COUNT(*) FROM external_ids WHERE authority = 'imdb'")[0][0] == 0


@then(parsers.parse('both no-match rows are still open as "{reason}"'))
def both_open(ctx, reason):
    assert [r["reason"] for r in ctx["repo"].open_reviews("tmdb")] == [reason, reason]


@then(parsers.parse('"{title}" holds imdb "{tt}" and tmdb "{tid}" and is found'))
def holds_both(ctx, title, tt, tid):
    fid = ctx["films"][title]
    ids = ctx["repo"].external_ids_for(fid)
    assert (ids["imdb"], ids["tmdb"]) == (tt, tid)
    assert _q(ctx, "SELECT found FROM tmdb WHERE film_id = ?", fid)[0][0] == 1


@then(parsers.parse('the only open tmdb row is for "{title}" with reason "{reason}" and candidates A, B'))
def only_open(ctx, title, reason):
    from movie_brain.application.thumbprint import parse_review_detail

    rows = ctx["repo"].open_reviews("tmdb")
    assert len(rows) == 1 and rows[0]["film_id"] == ctx["films"][title] and rows[0]["reason"] == reason
    parsed = parse_review_detail(str(rows[0]["detail"]))
    assert parsed is not None and [c["letter"] for c in parsed.candidates] == ["A", "B"]
    ctx["review_id"] = rows[0]["id"]


@then(parsers.parse('the "{title}" row keeps its original id'))
def keeps_id(ctx, title):
    ids = _q(ctx, "SELECT id FROM match_review WHERE film_id = ?", ctx["films"][title])
    assert len(ids) == 1 and ids[0][0] == ctx["review_id"]


@when(parsers.parse('I resolve the "{title}" row with --none'))
def resolve_none(ctx, title):
    row = next(r for r in ctx["repo"].open_reviews("tmdb") if r["film_id"] == ctx["films"][title])
    rv.resolve_review(ctx["repo"], int(row["id"]), today=TODAY, none=True, eval_csv=ctx["config_dir"] / "eval.csv")


@when("the tmdb no-match queue is rebuilt as sync would")
def rebuild_queue(ctx):
    rebuild_no_match_queue(ctx["repo"], TODAY)


@then("there are no open tmdb rows")
def no_open(ctx):
    assert ctx["repo"].open_reviews("tmdb") == []


@then(parsers.parse('the eval log has a verified human row for "{title}" expecting "{tt}"'))
def eval_row(ctx, title, tt):
    import csv

    with (ctx["config_dir"] / "eval.csv").open(encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["title_ingested"] == title]
    assert rows and rows[-1]["expected_tt"] == tt and rows[-1]["status"] == "verified"
