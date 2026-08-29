"""The curated-list verbs: phase 1 links what the catalog already holds and asks about the
rest; phase 2 is the only path that creates, and re-runs every gate at the moment it does.

Driven by an injected candidate pool rather than HTTP mocks — what matters here is which
gate answered and, in the idempotence scenario, that the resolver was not asked at all.
Creation assertions read the DATABASE, never the report: a report can say `created 0` while
a row was written.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from lists_fakes import RecordingFetcher, StubTmdb, candidate
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.lists import AUTHORITY, create_films, import_list, scorecard
from movie_brain.domain.models import Film, ListEntry, ListMeta, film_key

scenarios("../features/lists.feature")

TODAY = date(2026, 8, 28)
EVAL_CSV = Path(__file__).resolve().parents[2] / "scripts" / "eval" / "thumbprint_eval_v1.csv"


@pytest.fixture
def ctx(repo):
    return {
        "repo": repo,
        "films": {},
        "entries": [],
        "fetcher": RecordingFetcher(),
        "tmdb": StubTmdb(),
        "log": [],
        "asked_before": [],
        "eval_digest": hashlib.sha256(EVAL_CSV.read_bytes()).hexdigest(),
    }


def _q(ctx, sql, *args):
    conn = sqlite3.connect(ctx["repo"].db_path)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def _run(ctx, *, apply: bool):
    ctx["asked_before"] = list(ctx["fetcher"].queried)
    report = import_list(
        ctx["repo"],
        ctx["meta"],
        ctx["entries"],
        TODAY,
        fetcher=ctx["fetcher"],
        tmdb=ctx["tmdb"],
        apply=apply,
        log=ctx["log"].append,
    )
    ctx["report"] = report
    ctx["scorecard"] = scorecard(report.rows)
    return report


def _create(ctx, *, apply: bool):
    report = create_films(
        ctx["repo"],
        ctx["meta"].slug,
        TODAY,
        fetcher=ctx["fetcher"],
        tmdb=ctx["tmdb"],
        apply=apply,
        log=ctx["log"].append,
    )
    ctx["report"] = report
    ctx["scorecard"] = scorecard(report.rows)
    return report


def _film_id(ctx, title):
    """The film's id — from the given-step bookkeeping, or from the DB when phase 2 made it."""
    if title in ctx["films"]:
        return ctx["films"][title]
    rows = _q(ctx, "SELECT id FROM films WHERE title = ?", title)
    assert len(rows) == 1, f"{title!r}: {rows}"
    return rows[0][0]


# --- given -----------------------------------------------------------------------------


@given(parsers.parse('the list "{slug}" curated by "{curator}" ({year:d})'))
def a_list(ctx, slug, curator, year):
    ctx["meta"] = ListMeta(slug, "100 Films for an Ideal Cinematheque", curator, year, "https://example/x", True)


def _film(ctx, title, year, director=None):
    fid = ctx["repo"].create_film(Film(title, year, director, ""))
    ctx["films"][title] = fid
    return fid


@given(parsers.parse('a film "{title}" ({year:d})'))
def plain_film(ctx, title, year):
    _film(ctx, title, year)


@given(parsers.parse('a film "{title}" ({year:d}) holding imdb "{tt}"'))
def film_with_imdb(ctx, title, year, tt):
    ctx["repo"].set_external_id(_film(ctx, title, year), "imdb", tt, TODAY)


@given(parsers.parse('a film "{title}" ({year:d}) directed by "{director}" holding imdb "{tt}"'))
def film_with_director_and_imdb(ctx, title, year, director, tt):
    ctx["repo"].set_external_id(_film(ctx, title, year, director), "imdb", tt, TODAY)


@given(parsers.parse('a film "{title}" ({year:d}) holding tmdb "{tid}"'))
def film_with_tmdb(ctx, title, year, tid):
    ctx["repo"].set_external_id(_film(ctx, title, year), "tmdb", tid, TODAY)


@given(parsers.parse('the film "{title}" is tombstoned'))
def tombstoned(ctx, title):
    ctx["repo"].tombstone_film(ctx["films"][title], TODAY)


@given(parsers.parse('the candidate pool has "{form}" → {tt}/{tid:d} {year:d} by "{director}"'))
def pool_one(ctx, form, tt, tid, year, director):
    ctx["fetcher"].by_title[form] = [candidate(tt, tid, form, year, director)]


@given(parsers.parse('the candidate pool has "{form}" → {tt} {year:d} by "{director}" known only to OMDb'))
def pool_omdb_only(ctx, form, tt, year, director):
    ctx["fetcher"].by_title[form] = [candidate(tt, None, form, year, director, in_tmdb=False)]


@given(parsers.parse('the candidate pool has "{form}" → {tta}/{ida:d} {ya:d} and {ttb}/{idb:d} {yb:d}'))
def pool_two(ctx, form, tta, ida, ya, ttb, idb, yb):
    # Two same-titled works with no director evidence: the resolver refuses to pick one.
    ctx["fetcher"].by_title[form] = [
        candidate(tta, ida, form, ya, "", votes=50),
        candidate(ttb, idb, form, yb, "", votes=60),
    ]


@given(parsers.parse('the candidate pool has "{form}" → {tt}/{tid:d} {year:d} by "{director}" titled "{name}"'))
def pool_one_named(ctx, form, tt, tid, year, director, name):
    """The winner's OWN title differs from the listed one — what phase 2 must mint the film under.

    It is also known by the listed title (TMDB's `title` vs `original_title`), which is what
    lets the resolver match the curator's wording at all."""
    ctx["fetcher"].by_title[form] = [candidate(tt, tid, (name, form), year, director)]
    ctx["tmdb"].years[tid] = year


@given(parsers.parse('the candidate pool is offline for "{form}"'))
def pool_offline(ctx, form):
    ctx["fetcher"].offline.add(form)


@given(parsers.parse('the candidate pool blows up for "{form}"'))
def pool_blows_up(ctx, form):
    ctx["fetcher"].broken.add(form)


@given("tmdb lookups fail")
def tmdb_offline(ctx):
    ctx["tmdb"].raises = True


@given(parsers.parse('tmdb maps "{tt}" to {tid:d}'))
def tmdb_map(ctx, tt, tid):
    ctx["tmdb"].by_imdb[tt] = tid


@given(parsers.parse('the list entry {rank:d} is "{title}" by "{director}"'))
def an_entry(ctx, rank, title, director):
    ctx["entries"].append(ListEntry(rank, title, director))


@given("I imported the list with --apply")
def imported_once(ctx):
    _run(ctx, apply=True)


@given(parsers.parse('I imported the list with --apply for entry {rank:d} "{title}" by "{director}"'))
def imported_with_entry(ctx, rank, title, director):
    ctx["entries"].append(ListEntry(rank, title, director))
    _run(ctx, apply=True)


@given(parsers.parse('the "{value}" review row is resolved'))
def resolve_row(ctx, value):
    row = next(r for r in ctx["repo"].open_reviews(AUTHORITY) if r["value"] == value)
    ctx["repo"].resolve_review(int(str(row["id"])), " [dismissed]")


# --- when ------------------------------------------------------------------------------


@when("I import the list with --apply")
def import_apply(ctx):
    _run(ctx, apply=True)


@when("I import the list without --apply")
def import_dry(ctx):
    _run(ctx, apply=False)


@when("I create films with --apply")
def create_apply(ctx):
    _create(ctx, apply=True)


@when("I create films without --apply")
def create_dry(ctx):
    _create(ctx, apply=False)


@when(parsers.parse('I create films for "{slug}"'))
def create_unknown_list(ctx, slug):
    ctx["report"] = create_films(
        ctx["repo"], slug, TODAY, fetcher=ctx["fetcher"], tmdb=ctx["tmdb"], apply=True, log=ctx["log"].append
    )
    ctx["scorecard"] = scorecard(ctx["report"].rows)


# --- then ------------------------------------------------------------------------------


@then(
    parsers.parse(
        "the report says linked {linked:d}, would-create {create:d}, review {review:d}, "
        "blocked {blocked:d}, error {error:d}"
    )
)
def report_says(ctx, linked, create, review, blocked, error):
    r = ctx["report"]
    assert (r.linked, r.would_create, r.review, r.blocked, r.errors) == (linked, create, review, blocked, error)
    assert r.total == len(ctx["entries"])
    assert len(r.rows) == len(ctx["entries"])


@then(parsers.parse('entry {rank:d} is linked to "{title}"'))
def entry_linked(ctx, rank, title):
    row = next(e for e in ctx["repo"].list_entries(ctx["meta"].slug) if e.rank == rank)
    assert row.film_id == _film_id(ctx, title)
    assert next(o for o in ctx["report"].rows if o.rank == rank).kind in ("linked", "created")


@then(parsers.parse("entry {rank:d} is unlinked"))
def entry_unlinked(ctx, rank):
    rows = [e for e in ctx["repo"].list_entries(ctx["meta"].slug) if e.rank == rank]
    assert rows == [] or rows[0].film_id is None


@then(parsers.parse('the film "{title}" carries a list claim "{value}" ingested as "{ingested}"'))
def claim_recorded(ctx, title, value, ingested):
    claims = [c for c in ctx["repo"].claims_for_film(_film_id(ctx, title)) if c.authority == AUTHORITY]
    assert [(c.value, c.title_ingested) for c in claims] == [(value, ingested)]


@then(parsers.parse('there is one open list review row for "{value}" with reason "{reason}"'))
def one_open_row(ctx, value, reason):
    rows = [r for r in ctx["repo"].open_reviews(AUTHORITY) if r["value"] == value]
    assert len(rows) == 1, rows
    assert rows[0]["reason"] == reason
    assert rows[0]["film_id"] is None
    ctx["row"] = rows[0]


@then(parsers.parse("there are {n:d} open list review rows"))
def n_open_rows(ctx, n):
    assert len(ctx["repo"].open_reviews(AUTHORITY)) == n


@then("there are no open list review rows")
def no_open_rows(ctx):
    assert ctx["repo"].open_reviews(AUTHORITY) == []


@then(parsers.parse('that review detail mentions "{text}"'))
def detail_mentions(ctx, text):
    assert text in str(ctx["row"]["detail"]), ctx["row"]["detail"]


@then(parsers.parse('the scorecard line for entry {rank:d} contains "{text}"'))
def scorecard_contains(ctx, rank, text):
    lines = ctx["scorecard"].splitlines()
    head = next(i for i, line in enumerate(lines) if line.startswith(f"#{rank} "))
    assert text in lines[head + 1], lines[head + 1]


@then("no film was created")
def no_new_film(ctx):
    assert _q(ctx, "SELECT COUNT(*) FROM films")[0][0] == len(ctx["films"])


@then("the list registry is empty")
def no_registry(ctx):
    assert ctx["repo"].film_list(ctx["meta"].slug) is None


@then("there are no list entries")
def no_entries(ctx):
    assert ctx["repo"].list_entries(ctx["meta"].slug) == []


@then("there are no list claims")
def no_claims(ctx):
    assert _q(ctx, "SELECT COUNT(*) FROM claim WHERE authority = ?", AUTHORITY)[0][0] == 0


@then(parsers.parse('the resolver was not asked about "{title}" on the second run'))
def not_asked_again(ctx, title):
    second_run = ctx["fetcher"].queried[len(ctx["asked_before"]) :]
    assert title not in second_run, second_run
    assert second_run, "the second run should still have asked about the unlinked entries"


@then(
    parsers.parse(
        "the create report says created {created:d}, keyed {keyed:d}, linked {linked:d}, "
        "blocked {blocked:d}, error {error:d}"
    )
)
def create_report_says(ctx, created, keyed, linked, blocked, error):
    r = ctx["report"]
    assert (r.created, r.keyed, r.linked, r.blocked, r.errors) == (created, keyed, linked, blocked, error)
    assert r.exit_code == 0
    assert len(r.rows) == r.total


@then(parsers.re(r"the create report considered (?P<n>\d+) entr(?:y|ies)"))
def create_report_total(ctx, n):
    assert ctx["report"].total == int(n)


@then(parsers.re(r"exactly (?P<n>\d+) films? exists?"))
def exactly_n_films(ctx, n):
    assert _q(ctx, "SELECT COUNT(*) FROM films")[0][0] == int(n)


@then(parsers.parse('the film "{title}" is dated {year:d} and directed by "{director}"'))
def film_row_is(ctx, title, year, director):
    rows = _q(ctx, "SELECT year, director, key, guid FROM films WHERE title = ?", title)
    assert len(rows) == 1, rows
    assert (rows[0][0], rows[0][1]) == (year, director)
    assert rows[0][2] == film_key(title, year)
    assert rows[0][3], "a created film carries its own guid"


@then(parsers.parse('the film "{title}" holds no imdb id'))
def film_unkeyed(ctx, title):
    film_id = _film_id(ctx, title)
    assert _q(ctx, "SELECT COUNT(*) FROM external_ids WHERE film_id = ? AND authority = 'imdb'", film_id)[0][0] == 0


@then("the create report exits 1")
def create_report_exits_one(ctx):
    assert ctx["report"].exit_code == 1
    assert ctx["report"].rows == []


@then(parsers.parse('the film "{title}" holds imdb "{tt}" and tmdb "{tid}"'))
def film_holds_ids(ctx, title, tt, tid):
    film_id = _film_id(ctx, title)
    assert ctx["repo"].film_id_for_external("imdb", tt) == film_id
    assert ctx["repo"].film_id_for_external("tmdb", tid) == film_id


@then("the eval CSV is byte-identical")
def eval_csv_untouched(ctx):
    # Auto matches are never ratified — the benchmark must not score itself.
    assert hashlib.sha256(EVAL_CSV.read_bytes()).hexdigest() == ctx["eval_digest"]
