from __future__ import annotations

import re
from datetime import date

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.metacritic import promote_top_n
from movie_brain.application.owned import import_owned
from movie_brain.domain.matching import build_candidate_index, match_film
from movie_brain.domain.models import Film, McTitle, OwnedTitle

scenarios("../features/repair.feature")

TODAY = date(2026, 8, 19)


def _key(spec: str) -> str:
    m = re.fullmatch(r"(.+) \((\d{4})\)", spec)
    assert m
    return f"{m.group(1).lower()} ({m.group(2)})"


@pytest.fixture
def ctx(repo, config_dir):
    return {"repo": repo, "config_dir": config_dir, "promote": None}


@given(parsers.parse('a repository with films "{crit}" on Criterion and "{comm}" from commerce'))
def seed(ctx, crit, comm):
    cm = re.fullmatch(r"(.+) \((\d{4})\)", crit)
    ctx["repo"].record_catalog("criterion", [Film(cm.group(1), int(cm.group(2)), "Ann", "https://c/alpha")], TODAY)
    mm = re.fullmatch(r"(.+) \((\d{4})\)", comm)
    ctx["repo"].create_film(Film(mm.group(1), int(mm.group(2)), None, ""))


@given(parsers.parse('"{spec}" is tombstoned'))
def tombstone(ctx, spec):
    ctx["repo"].tombstone_film(ctx["repo"].film_id_by_key(_key(spec)), TODAY, note="test")


@given(parsers.parse('the repository also has film "{spec}"'))
def also_has(ctx, spec):
    m = re.fullmatch(r"(.+) \((\d{4})\)", spec)
    ctx["repo"].create_film(Film(m.group(1), int(m.group(2)), None, ""))


@given(parsers.parse('a tombstoned film "{spec}"'))
def fresh_tombstoned(ctx, spec):
    # A film unrelated to the Alpha/Alpha background pair: title/year far enough from
    # "Alpha (1950)" that the ±1-year matcher tolerance can't coincidentally attribute
    # the staged archive title to it — isolates the promote-time tombstoned-key guard
    # from match_archive's own (unrelated) year-tolerance matching.
    m = re.fullmatch(r"(.+) \((\d{4})\)", spec)
    film_id = ctx["repo"].create_film(Film(m.group(1), int(m.group(2)), None, ""))
    ctx["repo"].tombstone_film(film_id, TODAY, note="test")


@when(parsers.parse('I merge "{loser}" into "{survivor}"'))
def merge(ctx, loser, survivor):
    r = ctx["repo"]
    r.merge_film(r.film_id_by_key(_key(loser)), r.film_id_by_key(_key(survivor)), TODAY)


@when(parsers.parse('Criterion lists "{spec}" again'))
def rewalk(ctx, spec):
    m = re.fullmatch(r"(.+) \((\d{4})\)", spec)
    ctx["repo"].record_catalog("criterion", [Film(m.group(1), int(m.group(2)), "Ann", "https://c/alpha-1")], TODAY)


@when(parsers.parse('the Metacritic archive stages "{title}" ({year:d}) as slug "{slug}"'))
def stage(ctx, title, year, slug):
    ctx["repo"].upsert_mc_titles([McTitle(slug, title, year, 90, 1, 1)], TODAY)


@when(parsers.parse("the top {n:d} staged titles are promoted"))
def promote(ctx, n, monkeypatch):
    # Archive parsing is bypassed: match_archive reads the staged table through the parser
    # mock below, exactly like tests/step_defs/test_metacritic.py does.
    from movie_brain.infrastructure import metacritic as mc

    staged = ctx["repo"].top_staged_titles(n)
    monkeypatch.setattr(mc, "archived_pages", lambda _archive: ["p1"])
    monkeypatch.setattr(mc, "parse_archive", lambda _archive: staged)
    ctx["promote"] = promote_top_n(ctx["repo"], ctx["config_dir"], TODAY, n)


@when(parsers.parse('the Apple library contains "{title}" from {year:d}'))
def apple(ctx, title, year):
    import_owned(ctx["repo"], ctx["config_dir"], TODAY, fetch=lambda: [OwnedTitle(title, year)])


@then(parsers.parse('the dashboard lists {n:d} film titled "{title}"'))
def dashboard(ctx, n, title):
    assert sum(1 for v in ctx["repo"].list_views("criterion", TODAY) if v.title == title) == n


@then(parsers.parse('matching the Metacritic title "{title}" year {year:d} resolves to "{spec}"'))
def resolves(ctx, title, year, spec):
    index = build_candidate_index(ctx["repo"].films_for_matching())
    assert match_film(title, year, index).winner == ctx["repo"].film_id_by_key(_key(spec))


@then(parsers.parse('"{a}" has a criterion listing and "{b}" has none'))
def listing_moved(ctx, a, b):
    r = ctx["repo"]
    ids = {fid for fid, _ in r.current_films("criterion")}
    assert r.film_id_by_key(_key(a)) in ids and r.film_id_by_key(_key(b)) not in ids


@then(parsers.parse('no film was promoted and slug "{slug}" is unclaimed'))
def not_promoted(ctx, slug):
    assert ctx["promote"].promoted == 0
    assert slug not in ctx["repo"].claimed_values("metacritic")


@then(parsers.parse('"{a}" is owned and "{b}" is not'))
def owned(ctx, a, b):
    r = ctx["repo"]
    assert r.film_id_by_key(_key(a)) in r.owned_film_ids()
    assert r.film_id_by_key(_key(b)) not in r.owned_film_ids()


@then("no discovery film needs an OMDb lookup")
def no_discovery(ctx):
    assert ctx["repo"].films_needing_lookup_discovery("criterion", TODAY) == []


@then(parsers.parse('no film needs a TMDB match except "{spec}"'))
def only_one_tmdb(ctx, spec):
    assert [t.film_id for t in ctx["repo"].films_needing_tmdb_match()] == [ctx["repo"].film_id_by_key(_key(spec))]
