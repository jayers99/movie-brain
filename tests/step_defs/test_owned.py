from __future__ import annotations

import re
import sqlite3
from datetime import date

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.owned import AUTHORITY, import_owned
from movie_brain.domain.models import Film, OwnedTitle
from movie_brain.infrastructure.appletv import AppleTvError

scenarios("../features/owned.feature")

TODAY = date(2026, 8, 19)


@pytest.fixture
def ctx(repo, config_dir):
    return {"repo": repo, "config_dir": config_dir, "library": [], "fail": False, "report": None}


def _film(title_year: str) -> Film:
    m = re.match(r"(.+) \((\d{4})\)$", title_year)
    assert m
    return Film(m.group(1), int(m.group(2)), "Someone", f"https://c/{m.group(1).lower()}")


@given(parsers.parse('the repository holds the film "{title_year}"'))
def holds_film(ctx, title_year):
    ctx["repo"].upsert_film(_film(title_year))


@given(parsers.re(r'my Apple TV library has "(?P<title>[^"]+)" \((?P<year>\d+)\)'))
def library_has(ctx, title, year):
    ctx["library"].append(OwnedTitle(title, int(year)))


@given("my Apple TV library export fails")
def library_fails(ctx):
    ctx["fail"] = True


@when("I import owned films")
def run_import(ctx):
    def fetch():
        if ctx["fail"]:
            raise AppleTvError("boom")
        return list(ctx["library"])

    ctx["report"] = import_owned(ctx["repo"], ctx["config_dir"], TODAY, fetch=fetch, log=lambda m: None)


@then(parsers.parse('"{title_year}" is owned'))
def film_is_owned(ctx, title_year):
    fid = ctx["repo"].film_id_by_key(_film(title_year).key)
    assert fid in ctx["repo"].owned_film_ids()


@then(parsers.parse('the film "{title_year}" exists with a guid'))
def film_exists_with_guid(ctx, title_year):
    fid = ctx["repo"].film_id_by_key(_film(title_year).key)
    assert fid is not None
    conn = sqlite3.connect(ctx["repo"].db_path)
    guid = conn.execute("SELECT guid FROM films WHERE id = ?", (fid,)).fetchone()[0]
    conn.close()
    assert guid


@then(parsers.parse("the repository holds {n:d} films"))
def film_count(ctx, n):
    assert len(ctx["repo"].films_for_matching()) == n


@then(parsers.parse("the owned report says {m:d} matched and {c:d} created"))
def report_counts(ctx, m, c):
    assert (ctx["report"].matched, ctx["report"].created) == (m, c)


@then(parsers.parse("the owned report says {n:d} already owned"))
def report_already(ctx, n):
    assert ctx["report"].already_owned == n


@then(parsers.re(r'the owned review queue has an? "(?P<reason>[^"]+)" entry'))
def review_entry(ctx, reason):
    assert any(r["reason"] == reason for r in ctx["repo"].open_reviews(AUTHORITY))


@then("no film is owned")
def nothing_owned(ctx):
    assert ctx["repo"].owned_film_ids() == set()


@then(parsers.parse("the owned import exit code is {code:d}"))
def import_exit(ctx, code):
    assert ctx["report"].exit_code == code
