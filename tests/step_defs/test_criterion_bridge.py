"""`criterion bridge`: assertions read the DATABASE and the observation file."""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, timedelta

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.criterion_bridge import BRIDGE_FILE, load_observations, run_bridge
from movie_brain.domain.models import Film
from movie_brain.infrastructure.criterion_site import CatalogItem, Forward, classify_forward

scenarios("../features/criterion_bridge.feature")

SITE = "https://www.criterionchannel.com/"
NOW = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)


class Interrupted(Exception):
    pass


@pytest.fixture
def ctx(repo, config_dir):
    return {"repo": repo, "dir": config_dir, "answers": {}, "catalog": [], "asks": 0, "stop_after": None}


def _fid(ctx, title):
    conn = sqlite3.connect(ctx["repo"].db_path)
    try:
        return conn.execute("SELECT id FROM films WHERE title = ?", (title,)).fetchone()[0]
    finally:
        conn.close()


def _ask(ctx):
    def ask(url: str) -> Forward:
        if ctx["stop_after"] is not None and ctx["asks"] >= ctx["stop_after"]:
            raise Interrupted
        ctx["asks"] += 1
        status, location = ctx["answers"][url]
        return classify_forward(status, location)

    return ask


def _run(ctx, apply=False, retry=False, now=NOW):
    ctx["report"] = run_bridge(ctx["repo"], ctx["dir"], ctx["catalog"], _ask(ctx), now, apply=apply, retry=retry)


@given(parsers.parse('a Criterion film "{title}" ({year:d}) at old link "{slug}"'))
def crit_film(ctx, title, year, slug):
    ctx["repo"].record_catalog("criterion", [Film(title, year, None, SITE + slug)], date(2026, 9, 20))


@given(parsers.parse('the film "{title}" also holds old link "{slug}"'))
def second_link(ctx, title, slug):
    ctx["repo"].set_external_id(_fid(ctx, title), "criterion", SITE + slug, date(2026, 9, 20))


@given(parsers.parse('the old link "{slug}" forwards to "{location}"'))
@when(parsers.parse('the old link "{slug}" forwards to "{location}"'))
def forwards(ctx, slug, location):
    ctx["answers"][SITE + slug] = (307, location)


@given(parsers.parse('the old link "{slug}" answers 404'))
def answers_404(ctx, slug):
    ctx["answers"][SITE + slug] = (404, None)


@given(parsers.parse('the old link "{slug}" fails'))
def fails(ctx, slug):
    ctx["answers"][SITE + slug] = (None, None)


@given(parsers.parse('the catalog lists "{mediaid}" as "{title}" ({year:d})'))
def catalog_lists(ctx, mediaid, title, year):
    ctx["catalog"].append(CatalogItem(mediaid, title, year, 5000))


@given(parsers.parse("the first run is interrupted after {n:d} answer"))
def interrupted(ctx, n):
    ctx["stop_after"] = n
    with pytest.raises(Interrupted):
        _run(ctx)
    ctx["stop_after"] = None


@given(parsers.parse('the film "{title}" is tombstoned'))
def tombstoned(ctx, title):
    ctx["repo"].tombstone_film(_fid(ctx, title), date(2026, 9, 21), note="hidden by hand")


@when("I run the bridge")
def run_dry(ctx):
    _run(ctx)


@when("I run the bridge with apply")
def run_apply(ctx):
    _run(ctx, apply=True)


@when("I run the bridge with apply but the answers cannot be marked")
def run_apply_crash(ctx):
    from movie_brain.application import criterion_bridge

    def boom(path, observations):
        raise RuntimeError("killed before the answers were marked")

    mp = pytest.MonkeyPatch()
    mp.setattr(criterion_bridge, "rewrite_observations", boom)
    try:
        with pytest.raises(RuntimeError):
            _run(ctx, apply=True)
    finally:
        mp.undo()


@when("I run the bridge with apply a day later")
def run_apply_later(ctx):
    _run(ctx, apply=True, now=NOW + timedelta(hours=25))


@when("I run the bridge with retry")
def run_retry(ctx):
    _run(ctx, retry=True)


@when(parsers.parse('the database loses the criterion id "{mediaid}"'))
def loses_id(ctx, mediaid):
    conn = sqlite3.connect(ctx["repo"].db_path)
    conn.execute("DELETE FROM external_ids WHERE authority = 'criterion' AND value = ?", (mediaid,))
    conn.commit()
    conn.close()


@then(parsers.parse('the bridge counted {n:d} "{kind}"'))
def counted(ctx, n, kind):
    assert ctx["report"].counts.get(kind, 0) == n, ctx["report"].counts


@then(parsers.parse('the drift shows "{title}" {old:d} → {new:d} as "{kind}"'))
def drift(ctx, title, old, new, kind):
    assert [(d.title, d.year, d.cat_year, d.kind) for d in ctx["report"].drift] == [(title, old, new, kind)]


@then(parsers.parse('the film "{title}" holds no criterion id'))
def no_id(ctx, title):
    ids = ctx["repo"].external_ids_all(_fid(ctx, title))
    assert not [v for a, v in ids if a == "criterion" and not v.startswith("http")]


@then(parsers.parse('the film "{title}" holds criterion id "{mediaid}"'))
def holds_id(ctx, title, mediaid):
    assert ("criterion", mediaid) in ctx["repo"].external_ids_all(_fid(ctx, title))


@then(parsers.parse('the film "{title}" is listed at "{url}"'))
def listed_at(ctx, title, url):
    conn = sqlite3.connect(ctx["repo"].db_path)
    got = conn.execute(
        "SELECT url FROM listings WHERE film_id = ? AND source = 'criterion'", (_fid(ctx, title),)
    ).fetchone()[0]
    conn.close()
    assert got == url


@then(parsers.parse('the film "{title}" is still {year:d}'))
def still_year(ctx, title, year):
    conn = sqlite3.connect(ctx["repo"].db_path)
    got = conn.execute("SELECT year FROM films WHERE id = ?", (_fid(ctx, title),)).fetchone()[0]
    conn.close()
    assert got == year


@then(parsers.parse("the observation file has {n:d} line"))
def file_lines(ctx, n):
    assert len(load_observations(ctx["dir"] / BRIDGE_FILE)) == n


@then(parsers.parse("the site was asked {n:d} time"))
@then(parsers.parse("the site was asked {n:d} times"))
def asked(ctx, n):
    assert ctx["asks"] == n


@then(parsers.parse('there is {n:d} open criterion "{reason}" review'))
@then(parsers.parse('there are {n:d} open criterion "{reason}" reviews'))
def open_reviews(ctx, n, reason):
    assert len([r for r in ctx["repo"].open_reviews("criterion") if r["reason"] == reason]) == n


@then(parsers.parse("the bridge reopened {n:d} line"))
def reopened(ctx, n):
    assert ctx["report"].reopened == n


@then(parsers.parse('the observation for "{slug}" is applied'))
def obs_applied(ctx, slug):
    assert load_observations(ctx["dir"] / BRIDGE_FILE)[SITE + slug].applied is True


@then(parsers.parse('the observation for "{slug}" is not applied'))
def obs_not_applied(ctx, slug):
    assert load_observations(ctx["dir"] / BRIDGE_FILE)[SITE + slug].applied is False


@then(parsers.parse('the film "{title}" is the claimant of the open criterion "{reason}" review'))
def claimant(ctx, title, reason):
    rows = [r for r in ctx["repo"].open_reviews("criterion") if r["reason"] == reason]
    assert [r["film_id"] for r in rows] == [_fid(ctx, title)]


@then(parsers.parse("the bridge bound {n:d} ids on {m:d} film"))
def multi(ctx, n, m):
    assert ctx["report"].multi == m


@then(parsers.parse('the report names "{title}" with ids "{ids}"'))
def names_two_ids(ctx, title, ids):
    assert [(m.film_id, m.title, m.mediaids) for m in ctx["report"].multi_films] == [
        (_fid(ctx, title), title, ids.split(", "))
    ]
