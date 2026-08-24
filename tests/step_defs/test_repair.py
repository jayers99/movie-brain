from __future__ import annotations

import json
import re
import sqlite3
from datetime import date

import pytest
import responses
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application import repair
from movie_brain.application.metacritic import promote_top_n
from movie_brain.application.owned import import_owned
from movie_brain.domain.matching import build_candidate_index, match_film
from movie_brain.domain.models import Film, McTitle, OwnedTitle, ReviewEntry
from movie_brain.infrastructure.tmdb import TMDB_API, TmdbClient

scenarios("../features/repair.feature")

TODAY = date(2026, 8, 19)


def _omdb_needs_refresh(ctx, film_id: int) -> bool:
    conn = sqlite3.connect(ctx["repo"].db_path)
    try:
        row = conn.execute("SELECT needs_refresh FROM omdb WHERE film_id = ?", (film_id,)).fetchone()
    finally:
        conn.close()
    assert row is not None, f"no omdb row for film {film_id}"
    return bool(row[0])


def _key(spec: str) -> str:
    m = re.fullmatch(r"(.+) \((\d{4})\)", spec)
    assert m
    return f"{m.group(1).lower()} ({m.group(2)})"


@pytest.fixture
def ctx(repo, config_dir):
    rs = responses.RequestsMock(assert_all_requests_are_fired=False)
    rs.start()
    yield {"repo": repo, "config_dir": config_dir, "promote": None, "rs": rs}
    rs.stop()
    rs.reset()


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


@given(parsers.parse('"{spec}" holds tmdb id "{tid}"'))
def holds(ctx, spec, tid):
    fid = ctx["repo"].film_id_by_key(_key(spec))
    ctx["repo"].set_external_id(fid, "tmdb", tid, TODAY)
    ctx["repo"].upsert_tmdb(fid, found=True, looked_up=TODAY)


@given(parsers.parse('"{spec}" has an open id-conflict review claiming tmdb id "{tid}"'))
def conflict(ctx, spec, tid):
    fid = ctx["repo"].film_id_by_key(_key(spec))
    ctx["repo"].upsert_tmdb(fid, found=False, looked_up=TODAY)
    ctx["repo"].append_reviews("tmdb", [ReviewEntry("id-conflict", film_id=fid, value=tid, detail=spec)], TODAY)


@when("I audit dupes")
def audit(ctx):
    ctx["groups"] = repair.audit_dupes(ctx["repo"])


@when(parsers.parse("I apply dupes {mode} every group"))
def apply(ctx, mode):
    ctx["dupes"] = repair.repair_dupes(
        ctx["repo"], TODAY, apply=True, confirm=lambda _g: mode == "confirming", log=lambda _m: None
    )


@then(parsers.parse('the group "{key}" is a twin with survivor "{spec}" from source "{source}"'))
def is_twin(ctx, key, spec, source):
    g = next(g for g in ctx["groups"] if g.key == key)
    assert g.verdict == "twin" and g.survivor == ctx["repo"].film_id_by_key(_key(spec)) and g.source == source


# Anchored to a bare verdict word (not parsers.parse) so this never also matches the more
# specific "is a twin with survivor ... from source ..." step text above — parsers.parse's
# {verdict} is a greedy wildcard and would otherwise collide with it.
@then(parsers.re(r'the group "(?P<key>[^"]+)" is (?P<verdict>twin|distinct|undecided)$'))
def has_verdict(ctx, key, verdict):
    assert next(g for g in ctx["groups"] if g.key == key).verdict == verdict


@then(parsers.parse('"{loser}" is merged into "{survivor}"'))
def merged_into(ctx, loser, survivor):
    r = ctx["repo"]
    assert r.disposition_of(r.film_id_by_key(_key(loser))) == ("merged", r.film_id_by_key(_key(survivor)))


@then("the id-conflict review is resolved")
def conflict_resolved(ctx):
    assert ctx["repo"].open_reviews("tmdb") == []


@then("nothing was merged")
def nothing_merged(ctx):
    assert ctx["dupes"].merged == 0 and ctx["repo"].disposed_film_ids() == set()


@then(parsers.parse('exactly {n:d} group is keyed "{key}"'))
def exactly_n_groups_keyed(ctx, n, key):
    assert sum(1 for g in ctx["groups"] if g.key == key) == n


@then(parsers.parse('the group "{key}" is undecided from source "{source}"'))
def is_undecided_from_source(ctx, key, source):
    g = next(g for g in ctx["groups"] if g.key == key and g.source == source)
    assert g.verdict == "undecided"


@given(parsers.parse('TMDB describes id {tid:d} as "{title}" / "{orig}" from {year:d}'))
def describe(ctx, tid, title, orig, year):
    ctx["rs"].get(f"{TMDB_API}/movie/{tid}", json={"title": title, "original_title": orig, "release_date": f"{year}-01-01"})


@when("I audit links")
def audit_links(ctx):
    ctx["suspects"], _, _ = repair.audit_links(ctx["repo"], TmdbClient("tok"), log=lambda _m: None)


@when("I apply links")
def apply_links(ctx):
    ctx["links"] = repair.repair_links(ctx["repo"], TmdbClient("tok"), TODAY, apply=True, log=lambda _m: None)


@then(parsers.parse('the only link suspect is "{spec}"'))
def only_suspect(ctx, spec):
    assert [s.film_id for s in ctx["suspects"]] == [ctx["repo"].film_id_by_key(_key(spec))]


@then("there are no link suspects")
def no_suspects(ctx):
    assert ctx["suspects"] == []


@then(parsers.parse('"{spec}" has no tmdb id and is a TMDB miss'))
def cleared(ctx, spec):
    fid = ctx["repo"].film_id_by_key(_key(spec))
    assert "tmdb" not in ctx["repo"].external_ids_for(fid)
    assert fid in {t.film_id for t in ctx["repo"].films_tmdb_missed_targets()}


@then(parsers.parse('"{spec}" still holds tmdb id "{tid}"'))
def still_holds(ctx, spec, tid):
    assert ctx["repo"].external_ids_for(ctx["repo"].film_id_by_key(_key(spec)))["tmdb"] == tid


@given(parsers.parse('"{spec}" has an OMDb payload fetched for year {year:d}'))
def stale_payload(ctx, spec, year):
    from movie_brain.domain.models import OmdbRating

    fid = ctx["repo"].film_id_by_key(_key(spec))
    ctx["repo"].upsert_omdb(fid, OmdbRating(6.0, 50, True, "English", json.dumps({"Year": str(year)})), TODAY)


@when("I audit years")
def audit_years(ctx):
    ctx["years_audit"] = repair.audit_years(ctx["repo"])


@when("I apply years")
def apply_years(ctx):
    ctx["years"] = repair.repair_years(ctx["repo"], TODAY, apply=True, log=lambda _m: None)


@when(parsers.parse('I {mode} setting "{spec}" to {year:d}'))
def set_year(ctx, mode, spec, year):
    fid = ctx["repo"].film_id_by_key(_key(spec))
    ctx["years"] = repair.repair_years(ctx["repo"], TODAY, film_id=fid, year=year, apply=(mode == "apply"), log=lambda _m: None)


@then(parsers.parse('the stale OMDb list is exactly "{spec}"'))
def stale_is(ctx, spec):
    assert [s[0] for s in ctx["years_audit"].stale] == [ctx["repo"].film_id_by_key(_key(spec))]


@then(parsers.parse('"{spec}" needs an OMDb refresh'))
def needs_refresh(ctx, spec):
    fid = ctx["repo"].film_id_by_key(_key(spec))
    assert _omdb_needs_refresh(ctx, fid)


@then(parsers.parse('"{spec}" still has year {year:d}'))
def still_year(ctx, spec, year):
    assert ctx["repo"].film_id_by_key(_key(spec)) is not None


@then(parsers.parse('a film "{spec}" exists and its OMDb row is marked for refresh'))
def exists_refresh(ctx, spec):
    fid = ctx["repo"].film_id_by_key(_key(spec))
    assert fid is not None
    assert _omdb_needs_refresh(ctx, fid)


@then(parsers.parse('an open tmdb year-collision review names "{spec}"'))
def collision_named(ctx, spec):
    rows = [r for r in ctx["repo"].open_reviews("tmdb") if r["reason"] == "year-collision"]
    assert rows and rows[0]["value"] == str(ctx["repo"].film_id_by_key(_key(spec)))
