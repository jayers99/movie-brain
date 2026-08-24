from __future__ import annotations

import re
from datetime import date

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.review import resolve_review
from movie_brain.domain.models import Film, ReviewEntry

# pytest-bdd registers a @given/@when/@then step as a fixture in the DECORATING module's own
# namespace (see pytest_bdd.steps.step: it injects into the caller frame's locals under a
# mangled fixture name, not the plain function name) — importing the plain function object from
# tests.step_defs.test_repair does NOT re-register the step here, and `import *` would also drag
# in test_repair's own `scenarios(...)` call, duplicating every repair.feature scenario in this
# module's collection. So per the brief's fallback, _key/seed/merge/rewalk are duplicated locally
# (kept byte-for-byte identical to tests/step_defs/test_repair.py) rather than imported.
scenarios("../features/revisit.feature")
TODAY = date(2026, 8, 19)


def _key(spec: str) -> str:
    m = re.fullmatch(r"(.+) \((\d{4})\)", spec)
    assert m
    return f"{m.group(1).lower()} ({m.group(2)})"


@pytest.fixture
def ctx(repo, config_dir):
    return {"repo": repo, "config_dir": config_dir, "review_id": None}


@given(parsers.parse('a repository with films "{crit}" on Criterion and "{comm}" from commerce'))
def seed(ctx, crit, comm):
    cm = re.fullmatch(r"(.+) \((\d{4})\)", crit)
    ctx["repo"].record_catalog("criterion", [Film(cm.group(1), int(cm.group(2)), "Ann", "https://c/alpha")], TODAY)
    mm = re.fullmatch(r"(.+) \((\d{4})\)", comm)
    ctx["repo"].create_film(Film(mm.group(1), int(mm.group(2)), None, ""))


@when(parsers.parse('I merge "{loser}" into "{survivor}"'))
def merge(ctx, loser, survivor):
    r = ctx["repo"]
    r.merge_film(r.film_id_by_key(_key(loser)), r.film_id_by_key(_key(survivor)), TODAY)


@when(parsers.parse('Criterion lists "{spec}" again'))
def rewalk(ctx, spec):
    m = re.fullmatch(r"(.+) \((\d{4})\)", spec)
    ctx["repo"].record_catalog("criterion", [Film(m.group(1), int(m.group(2)), "Ann", "https://c/alpha-1")], TODAY)


@given(parsers.parse('"{spec}" is flagged for revisit'))
def flagged(ctx, spec):
    ctx["repo"].toggle_revisit(ctx["repo"].film_id_by_key(_key(spec)), TODAY)


@given(parsers.parse('an open tmdb "no-match" review for "{spec}"'))
def open_review(ctx, spec):
    fid = ctx["repo"].film_id_by_key(_key(spec))
    ctx["repo"].upsert_tmdb(fid, found=False, looked_up=TODAY)
    ctx["repo"].append_reviews("tmdb", [ReviewEntry("no-match", film_id=fid)], TODAY)
    ctx["review_id"] = ctx["repo"].open_reviews("tmdb")[-1]["id"]


@when(parsers.re(r'I flag "(?P<spec>[^"]+)" for revisit with note "(?P<note>[^"]*)"'))
def toggle(ctx, spec, note):
    ctx["repo"].toggle_revisit(ctx["repo"].film_id_by_key(_key(spec)), TODAY, note=note or None)


@when("that review is dismissed")
def dismissed(ctx):
    resolve_review(ctx["repo"], ctx["review_id"], dismiss=True, today=TODAY)


@then(parsers.re(r'"(?P<spec>[^"]+)" is flagged with note "(?P<note>[^"]*)"'))
def is_flagged(ctx, spec, note):
    v = ctx["repo"].get_view(ctx["repo"].film_id_by_key(_key(spec)), TODAY)
    assert v.needs_revisit and (v.revisit_note or "") == note


@then(parsers.parse('"{spec}" is not flagged'))
def not_flagged(ctx, spec):
    assert not ctx["repo"].get_view(ctx["repo"].film_id_by_key(_key(spec)), TODAY).needs_revisit


@then(parsers.parse('the revisit worklist lists only "{spec}"'))
def worklist(ctx, spec):
    assert [r[0] for r in ctx["repo"].revisits()] == [ctx["repo"].film_id_by_key(_key(spec))]
