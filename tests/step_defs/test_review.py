from __future__ import annotations

import re
from datetime import date

import pytest
import responses
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application import review as rv
from movie_brain.application.availability import TMDB_AUTHORITY
from movie_brain.application.metacritic import match_archive
from movie_brain.application.owned import import_owned
from movie_brain.domain.models import Film, McTitle, OwnedTitle, ReviewEntry
from movie_brain.infrastructure.tmdb import TMDB_API, TmdbClient

scenarios("../features/review.feature")
TODAY = date(2026, 8, 19)


def _split(spec):
    m = re.fullmatch(r"(.+) \((\d{4})\)", spec)
    return m.group(1), int(m.group(2))


def _id(repo, spec):
    t, y = _split(spec)
    return repo.film_id_by_key(f"{t.lower()} ({y})")


@pytest.fixture
def ctx(repo, config_dir):
    rs = responses.RequestsMock(assert_all_requests_are_fired=False)
    rs.start()
    yield {"repo": repo, "config_dir": config_dir, "rs": rs, "review_id": None, "client": None}
    rs.stop()
    rs.reset()


@given(parsers.parse('films "{crit}" on Criterion and "{comm}" from commerce'))
def seed(ctx, crit, comm):
    t, y = _split(crit)
    ctx["repo"].record_catalog("criterion", [Film(t, y, "Ann", f"https://c/{t.lower()}")], TODAY)
    t, y = _split(comm)
    ctx["repo"].create_film(Film(t, y, None, ""))


@given(parsers.parse('an open tmdb "id-conflict" review for "{spec}" claiming id "{tid}"'))
def open_conflict(ctx, spec, tid):
    fid = _id(ctx["repo"], spec)
    ctx["repo"].upsert_tmdb(fid, found=False, looked_up=TODAY)
    ctx["repo"].append_reviews("tmdb", [ReviewEntry("id-conflict", film_id=fid, value=tid, detail=spec)], TODAY)
    ctx["review_id"] = ctx["repo"].open_reviews("tmdb")[-1]["id"]


@given(parsers.re(r'an open (?P<authority>\S+) "(?P<reason>[^"]+)" review for "(?P<spec>[^"]+)"$'))
def open_for_film(ctx, authority, reason, spec):
    fid = _id(ctx["repo"], spec)
    if authority == "tmdb" and reason == "no-match":
        ctx["repo"].upsert_tmdb(fid, found=False, looked_up=TODAY)
    ctx["repo"].append_reviews(authority, [ReviewEntry(reason, film_id=fid, detail=spec)], TODAY)
    ctx["review_id"] = ctx["repo"].open_reviews(authority)[-1]["id"]


@given(parsers.parse('an open {authority} "{reason}" review for slug "{slug}"'))
def open_for_slug(ctx, authority, reason, slug):
    ctx["repo"].append_reviews(authority, [ReviewEntry(reason, value=slug, detail=slug)], TODAY)
    ctx["review_id"] = ctx["repo"].open_reviews(authority)[-1]["id"]


@given(parsers.parse('an open {authority} "{reason}" review for title "{title}"'))
def open_for_title(ctx, authority, reason, title):
    ctx["repo"].append_reviews(authority, [ReviewEntry(reason, value=title, detail=title)], TODAY)
    ctx["review_id"] = ctx["repo"].open_reviews(authority)[-1]["id"]


@given(parsers.parse('"{spec}" holds tmdb id "{tid}"'))
def holds_tmdb(ctx, spec, tid):
    fid = _id(ctx["repo"], spec)
    ctx["repo"].set_external_id(fid, "tmdb", tid, TODAY)
    ctx["repo"].upsert_tmdb(fid, found=True, looked_up=TODAY)


@given(parsers.parse('"{loser}" is merged into "{survivor}"'))
def merge_before(ctx, loser, survivor):
    ctx["repo"].merge_film(_id(ctx["repo"], loser), _id(ctx["repo"], survivor), TODAY, note="test")


@given(parsers.parse('"{spec}" is tombstoned'))
def tombstoned_before(ctx, spec):
    ctx["repo"].tombstone_film(_id(ctx["repo"], spec), TODAY, note="test")


@given(parsers.parse('the archive staged "{title}" ({year:d}) as slug "{slug}"'))
def staged(ctx, title, year, slug):
    ctx["repo"].upsert_mc_titles([McTitle(slug, title, year, 85, 1, 1)], TODAY)


@given(parsers.parse("TMDB says id {tid:d} was released in {year:d}"))
def tmdb_year(ctx, tid, year):
    ctx["rs"].get(f"{TMDB_API}/movie/{tid}", json={"id": tid, "release_date": f"{year}-03-02"})
    ctx["client"] = TmdbClient("tok")


@when("I resolve it with dismiss")
def dismiss(ctx):
    rv.resolve_review(ctx["repo"], ctx["review_id"], dismiss=True, today=TODAY)


@when(parsers.parse("I resolve it with tmdb id {tid:d}"))
def with_tmdb(ctx, tid):
    rv.resolve_review(ctx["repo"], ctx["review_id"], tmdb_id=tid, today=TODAY, client=ctx["client"])


@when("I resolve it with create")
def with_create(ctx):
    rv.resolve_review(ctx["repo"], ctx["review_id"], create=True, today=TODAY)


@when(parsers.parse('I resolve it with film "{spec}"'))
def with_film(ctx, spec):
    rv.resolve_review(ctx["repo"], ctx["review_id"], film_id=_id(ctx["repo"], spec), today=TODAY)


@then("the review is resolved")
def resolved(ctx):
    assert ctx["repo"].review(ctx["review_id"])["resolved"] == 1


@then(parsers.parse('rebuilding the tmdb no-match queue queues nothing for "{spec}"'))
def rebuild(ctx):
    from movie_brain.application.availability import rebuild_no_match_queue

    rebuild_no_match_queue(ctx["repo"], TODAY)
    assert ctx["repo"].open_reviews(TMDB_AUTHORITY) == []


@then(parsers.parse('"{spec}" has tmdb id "{tid}" and is found'))
def has_tmdb(ctx, spec, tid):
    fid = _id(ctx["repo"], spec)
    assert ctx["repo"].external_ids_for(fid)["tmdb"] == tid
    assert fid not in {t.film_id for t in ctx["repo"].films_tmdb_missed_targets()}


@then(parsers.parse('a film "{spec}" exists holding metacritic slug "{slug}"'))
def created_with_slug(ctx, spec, slug):
    fid = _id(ctx["repo"], spec)
    assert fid is not None and ctx["repo"].external_ids_for(fid)["metacritic"] == slug


@then(parsers.parse('"{spec}" holds metacritic slug "{slug}"'))
def holds_slug(ctx, spec, slug):
    assert ctx["repo"].external_ids_for(_id(ctx["repo"], spec))["metacritic"] == slug


@then(parsers.parse('re-running the archive match queues nothing for slug "{slug}"'))
def rerun_match(ctx, slug, monkeypatch):
    from movie_brain.infrastructure import metacritic as mc

    staged = ctx["repo"].top_staged_titles(100)
    monkeypatch.setattr(mc, "archived_pages", lambda _a: ["p1"])
    monkeypatch.setattr(mc, "parse_archive", lambda _a: staged)
    match_archive(ctx["repo"], ctx["config_dir"], TODAY)
    assert all(r["value"] != slug for r in ctx["repo"].open_reviews("metacritic"))


@then(parsers.parse('"{spec}" is owned'))
def is_owned(ctx, spec):
    assert _id(ctx["repo"], spec) in ctx["repo"].owned_film_ids()


@then(parsers.parse('a later owned import of "{title}" year {year:d} queues nothing'))
def later_import(ctx, title, year):
    import_owned(ctx["repo"], ctx["config_dir"], TODAY, fetch=lambda: [OwnedTitle(title, year)])
    assert ctx["repo"].open_reviews("apple-tv") == []


@then(parsers.parse('a film "{spec}" exists and is owned'))
def exists_owned(ctx, spec):
    fid = _id(ctx["repo"], spec)
    assert fid is not None and fid in ctx["repo"].owned_film_ids()


@then(parsers.parse('"{loser}" is merged into "{survivor}"'))
def merged(ctx, loser, survivor):
    assert ctx["repo"].disposition_of(_id(ctx["repo"], loser)) == ("merged", _id(ctx["repo"], survivor))


@then("resolving it with create fails")
def create_fails(ctx):
    with pytest.raises(ValueError):
        rv.resolve_review(ctx["repo"], ctx["review_id"], create=True, today=TODAY)


@then(parsers.parse('resolving it with both dismiss and film "{spec}" fails'))
def both_fail(ctx, spec):
    with pytest.raises(ValueError):
        rv.resolve_review(ctx["repo"], ctx["review_id"], dismiss=True, film_id=_id(ctx["repo"], spec), today=TODAY)


@then(parsers.parse('resolving it with film "{spec}" fails'))
def with_film_fails(ctx, spec):
    with pytest.raises(ValueError):
        rv.resolve_review(ctx["repo"], ctx["review_id"], film_id=_id(ctx["repo"], spec), today=TODAY)
