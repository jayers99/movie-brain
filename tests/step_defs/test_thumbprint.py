from __future__ import annotations

import json
import sqlite3
from datetime import date

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.repair import repair_twins
from movie_brain.application.thumbprint import backfill_claims
from movie_brain.domain.models import Film, OmdbRating

scenarios("../features/thumbprint.feature")

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
    ctx["report"] = backfill_claims(ctx["repo"], ctx["config_dir"], apply=False, log=ctx["log"].append)


@when("I run the claims backfill with --apply")
def backfill_apply(ctx):
    ctx["report"] = backfill_claims(ctx["repo"], ctx["config_dir"], apply=True, log=ctx["log"].append)


@when("I run the claims backfill with --apply twice")
def backfill_twice(ctx):
    backfill_apply(ctx)
    backfill_apply(ctx)


@then("the claim table is empty")
def claim_empty(ctx):
    assert _q(ctx, "SELECT COUNT(*) FROM claim")[0][0] == 0


@then(parsers.parse("the backfill report says criterion {c:d}, metacritic {m:d}, apple {a:d}, editions {e:d}"))
def report_counts(ctx, c, m, a, e):
    r = ctx["report"]
    assert (r.criterion, r.metacritic, r.apple, r.editions) == (c, m, a, e)


@then(parsers.parse("there are exactly {n:d} claim rows"))
def claim_rows(ctx, n):
    assert _q(ctx, "SELECT COUNT(*) FROM claim")[0][0] == n


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
