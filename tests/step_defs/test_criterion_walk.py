"""The Criterion walk (spec 2026-10-01 D2, D4–D7, D10) and, from Task 6, review resolution of
criterion rows (D9). Assertions read the DATABASE; the site, the resolver and TMDB are fakes."""

from __future__ import annotations

import re
import sqlite3
from datetime import date, timedelta

import pytest
from criterion_fakes import FakeSite, captured_media, media_like
from lists_fakes import RecordingFetcher, StubTmdb, candidate
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.criterion_walk import parse_criterion_detail, walk_criterion
from movie_brain.application.review import resolve_review
from movie_brain.domain.models import Film, ReviewEntry
from movie_brain.domain.thumbprint import parse_title
from movie_brain.infrastructure.criterion_site import CatalogItem
from movie_brain.infrastructure.database import Repository
from movie_brain.infrastructure.tmdb import TmdbFacts

scenarios("../features/criterion_walk.feature")

LAST = date(2026, 9, 20)  # the last VHX walk: every seeded listing's last_seen
TODAY = date(2026, 10, 3)
SITE = "https://www.criterionchannel.com"
TABLES = (
    "films", "listings", "external_ids", "claim", "match_review",
    "availability_transitions", "meta", "my_ratings", "watchlist",
)


@pytest.fixture
def ctx(repo, monkeypatch):
    return {
        "repo": repo, "site": FakeSite(), "fetcher": RecordingFetcher(), "tmdb": StubTmdb(),
        "day": TODAY, "monkeypatch": monkeypatch, "reports": [], "error": None, "before": None,
        "logs": [], "refusal": None,
    }


def _q(ctx, sql, *args):
    conn = sqlite3.connect(ctx["repo"].db_path)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def _fid(ctx, title, year=None):
    rows = _q(ctx, "SELECT id FROM films WHERE title = ?" + (" AND year = ?" if year else ""), title,
              *([year] if year else []))
    assert len(rows) == 1, f"{len(rows)} films titled {title!r}"
    return rows[0][0]


def _snapshot(ctx):
    return {t: _q(ctx, f"SELECT * FROM {t} ORDER BY rowid") for t in TABLES}


def _open_rows(ctx, mediaid, reason=None):
    return [
        r for r in ctx["repo"].open_reviews("criterion")
        if r["value"] == mediaid and (reason is None or r["reason"] == reason)
    ]


# --- the catalog as we hold it -------------------------------------------------------------


@given(parsers.re(
    r'the last walk listed "(?P<title>[^"]+)" \((?P<year>\d{4})\) as "(?P<mediaid>\w{8})"'
    r'(?: at "(?P<url>[^"]+)")?'
))
def last_walk_listed(ctx, title, year, mediaid, url):
    repo = ctx["repo"]
    fid = repo.create_film(Film(title, int(year), None, ""))
    repo.set_external_id(fid, "criterion", mediaid, LAST)
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    repo.record_listing(fid, "criterion", url or f"{SITE}/films/{mediaid}/{slug}", LAST)


@given(parsers.parse('the last walk listed "{title}" ({year:d}) under its old link only'))
def last_walk_old_link(ctx, title, year):
    repo = ctx["repo"]
    fid = repo.create_film(Film(title, year, None, ""))
    old = f"{SITE}/{title.lower()}"
    repo.set_external_id(fid, "criterion", old, LAST)
    repo.record_listing(fid, "criterion", old, LAST)


@given(parsers.parse('a film "{title}" ({year:d}) holding imdb "{tt}"'))
def film_with_imdb(ctx, title, year, tt):
    fid = ctx["repo"].create_film(Film(title, year, None, ""))
    ctx["repo"].set_external_id(fid, "imdb", tt, LAST)


@given(parsers.parse('a film "{title}" ({year:d}) holding no ids'))
def film_bare(ctx, title, year):
    ctx["repo"].create_film(Film(title, year, None, ""))


@given(parsers.parse('the film "{title}" also holds criterion id "{mediaid}"'))
def also_mediaid(ctx, title, mediaid):
    ctx["repo"].set_external_id(_fid(ctx, title), "criterion", mediaid, LAST)


@given(parsers.parse('the film "{title}" also holds imdb "{tt}"'))
def also_imdb(ctx, title, tt):
    ctx["repo"].set_external_id(_fid(ctx, title), "imdb", tt, LAST)


@given(parsers.parse('the film "{title}" is rated {score:d}'))
def rated(ctx, title, score):
    ctx["repo"].set_rating(_fid(ctx, title), score, LAST)


@given(parsers.parse('the film "{title}" is on the watchlist'))
def watchlisted(ctx, title):
    ctx["repo"].toggle_watchlist(_fid(ctx, title), LAST)


@given(parsers.parse('the film "{title}" is leaving "{label}"'))
def leaving(ctx, title, label):
    conn = sqlite3.connect(ctx["repo"].db_path)
    conn.execute(
        "UPDATE listings SET leaving_date = ? WHERE film_id = ? AND source = 'criterion'", (label, _fid(ctx, title))
    )
    conn.commit()
    conn.close()


@given(parsers.parse('the film "{title}" is tombstoned'))
def tombstoned(ctx, title):
    ctx["repo"].tombstone_film(_fid(ctx, title), LAST, note="hidden by hand")


@given(parsers.parse('an open criterion "{reason}" review names "{mediaid}" for "{title}"'))
def open_row(ctx, reason, mediaid, title):
    ctx["repo"].append_reviews("criterion", [ReviewEntry(reason, _fid(ctx, title), mediaid, "{}")], LAST)


# --- the site, the resolver, TMDB ---------------------------------------------------------


@given(parsers.parse('Criterion lists "{title}" ({year:d}) as "{mediaid}"'))
def lists_item(ctx, title, year, mediaid):
    ctx["site"].items.append(CatalogItem(mediaid, title, year, 5400))


@given(parsers.parse('JW knows "{mediaid}" as captured'))
def jw_captured(ctx, mediaid):
    ctx["site"].media_by_id[mediaid] = captured_media()


@given(parsers.parse('JW knows "{mediaid}" as "{title}" directed by "{director}"'))
def jw_knows(ctx, mediaid, title, director):
    ctx["site"].media_by_id[mediaid] = media_like(mediaid, title, (director,))


@given(parsers.parse('JW knows "{mediaid}" as "{title}" with no director'))
def jw_knows_no_director(ctx, mediaid, title):
    ctx["site"].media_by_id[mediaid] = media_like(mediaid, title, ())


@given(parsers.parse('JW fails for "{mediaid}"'))
def jw_fails(ctx, mediaid):
    ctx["site"].media_fails.add(mediaid)


@given(parsers.parse('the leaving page lists "{mediaid}" for "{label}"'))
def leaving_page(ctx, mediaid, label):
    ctx["site"].leaving_labels[mediaid] = label


@given("the leaving pages cannot be read")
def leaving_down(ctx):
    ctx["site"].leaving_labels = None


def _q_title(title):
    """The title the resolver is asked about: `make_query` parses the printed title first."""
    return parse_title(title).title


@given(parsers.parse('the resolver matches "{title}" to "{tt}" (tmdb {tid:d}) directed by "{director}"'))
def resolver_matches(ctx, title, tt, tid, director):
    ctx["fetcher"].by_title[_q_title(title)] = [candidate(tt, tid, _q_title(title), None, director)]


@given(parsers.parse('the resolver matches "{title}" ({year:d}) to "{tt}" (tmdb {tid:d}) with no director'))
def resolver_matches_no_director(ctx, title, year, tt, tid):
    ctx["fetcher"].by_title[_q_title(title)] = [candidate(tt, tid, _q_title(title), year, "")]


@given(parsers.parse('the resolver finds two works named "{title}" ({year:d})'))
def resolver_two(ctx, title, year):
    t = _q_title(title)
    ctx["fetcher"].by_title[t] = [candidate("tt9000401", 9401, t, year, ""), candidate("tt9000402", 9402, t, year, "")]


@given(parsers.parse('the resolver finds nothing for "{title}"'))
def resolver_nothing(ctx, title):
    ctx["fetcher"].by_title.pop(_q_title(title), None)


@given(parsers.parse('the resolver is offline for "{title}"'))
def resolver_offline(ctx, title):
    ctx["fetcher"].offline.add(_q_title(title))


@given(parsers.parse('TMDB knows "{tt}" as film {tid:d} "{title}" ({year:d})'))
def tmdb_knows(ctx, tt, tid, title, year):
    ctx["tmdb"].by_imdb[tt] = tid
    ctx["tmdb"].facts[tid] = TmdbFacts(tt, title, title, (), year, 90)


@given("the walk's write fails at its last step")
def write_fails(ctx):
    def boom(c, leaving, day):
        raise RuntimeError("disk full")

    ctx["monkeypatch"].setattr(Repository, "_walk_leaving", staticmethod(boom))


# --- running it ----------------------------------------------------------------------------


def _walk(ctx, *, token=True):
    ctx["reports"].append(
        walk_criterion(
            ctx["repo"], ctx["site"], ctx["fetcher"] if token else None, ctx["tmdb"] if token else None,
            ctx["day"], log=ctx["logs"].append,
        )
    )


@when("the walk runs")
def walk_runs(ctx):
    _walk(ctx)


@when("the walk runs again the next day")
def walk_next_day(ctx):
    ctx["day"] = ctx["day"] + timedelta(days=1)
    _walk(ctx)


@when("the walk runs without a TMDB token")
def walk_no_token(ctx):
    _walk(ctx, token=False)


@when("the walk runs and fails")
def walk_fails(ctx):
    ctx["before"] = _snapshot(ctx)
    with pytest.raises(Exception) as caught:  # noqa: PT011 — any failure: the point is what it left behind
        _walk(ctx)
    ctx["error"] = caught.value


@when("the resolver comes back")
def resolver_back(ctx):
    ctx["fetcher"].offline.clear()


@when(parsers.parse('the owner dismisses the criterion review for "{mediaid}"'))
def owner_dismisses(ctx, mediaid):
    (row,) = _open_rows(ctx, mediaid)
    resolve_review(ctx["repo"], int(row["id"]), today=ctx["day"], dismiss=True)


# --- outcomes ------------------------------------------------------------------------------


def _report(ctx):
    return ctx["reports"][-1]


@then(parsers.parse("the walk reports arrived {a:d}, left {d:d}, to review {r:d}"))
def reports(ctx, a, d, r):
    rep = _report(ctx)
    assert (rep.arrived, rep.departed, rep.reviews) == (a, d, r), rep


@then(parsers.parse("the walk created {n:d} film"))
def created_n(ctx, n):
    assert _report(ctx).created == n


@then("no film was created")
def created_none(ctx):
    assert _report(ctx).created == 0


@then(parsers.parse("the walk did not ask about {n:d} film tonight"))
def skipped_n(ctx, n):
    assert _report(ctx).skipped == n


@then(parsers.parse('there is {n:d} film titled "{title}"'))
def n_titled(ctx, n, title):
    assert _q(ctx, "SELECT COUNT(*) FROM films WHERE title = ?", title) == [(n,)]


@then(parsers.parse('the film "{title}" has year {year:d} and rating {score:d}'))
def year_and_rating(ctx, title, year, score):
    fid = _fid(ctx, title)
    assert _q(ctx, "SELECT year FROM films WHERE id = ?", fid) == [(year,)]
    assert _q(ctx, "SELECT score FROM my_ratings WHERE film_id = ?", fid) == [(score,)]


@then(parsers.parse('the film "{title}" has year {year:d} and director "{director}"'))
def year_and_director(ctx, title, year, director):
    assert _q(ctx, "SELECT year, director FROM films WHERE id = ?", _fid(ctx, title)) == [(year, director)]


@then(parsers.parse('the film "{title}" has no director'))
def no_director(ctx, title):
    assert _q(ctx, "SELECT director FROM films WHERE id = ?", _fid(ctx, title)) == [(None,)]


@then(parsers.parse('the film "{title}" is current on Criterion'))
def current(ctx, title):
    assert _fid(ctx, title) in {i for i, _ in ctx["repo"].current_films("criterion")}


@then(parsers.parse('the film "{title}" is not current on Criterion'))
def not_current(ctx, title):
    assert _fid(ctx, title) not in {i for i, _ in ctx["repo"].current_films("criterion")}


@then(parsers.parse('the film "{title}" holds criterion id "{mediaid}"'))
def holds_mediaid(ctx, title, mediaid):
    assert ("criterion", mediaid) in ctx["repo"].external_ids_all(_fid(ctx, title))


@then(parsers.parse('the film "{title}" holds criterion ids "{a}" and "{b}"'))
def holds_two(ctx, title, a, b):
    ids = ctx["repo"].external_ids_all(_fid(ctx, title))
    assert ("criterion", a) in ids and ("criterion", b) in ids


@then(parsers.parse('the film "{title}" holds no criterion id'))
def holds_none(ctx, title):
    assert not [v for a, v in ctx["repo"].external_ids_all(_fid(ctx, title)) if a == "criterion"]


@then(parsers.parse('the film "{title}" holds imdb "{tt}"'))
def holds_imdb(ctx, title, tt):
    assert ctx["repo"].external_ids_for(_fid(ctx, title)).get("imdb") == tt


@then(parsers.parse('the film "{title}" has a criterion claim "{mediaid}" titled "{claimed}" for {year:d}'))
def has_claim(ctx, title, mediaid, claimed, year):
    assert _q(ctx, "SELECT film_id, title_ingested, year_claimed FROM claim WHERE authority = 'criterion' "
                   "AND value = ?", mediaid) == [(_fid(ctx, title), claimed, year)]


@then(parsers.parse('the film "{title}" has {n:d} criterion claims'))
def n_claims(ctx, title, n):
    assert _q(ctx, "SELECT COUNT(*) FROM claim WHERE authority = 'criterion' AND film_id = ?", _fid(ctx, title)) == [(n,)]


@then(parsers.parse('the film "{title}" has {n:d} Criterion listing'))
def n_listings(ctx, title, n):
    assert _q(ctx, "SELECT COUNT(*) FROM listings WHERE source = 'criterion' AND film_id = ?", _fid(ctx, title)) == [(n,)]


@then(parsers.parse('the film "{title}" is listed at "{url}"'))
def listed_at(ctx, title, url):
    assert _q(ctx, "SELECT url FROM listings WHERE source = 'criterion' AND film_id = ?", _fid(ctx, title)) == [(url,)]


@then(parsers.parse('the film "{title}" arrived on Criterion today'))
def arrived_today(ctx, title):
    assert _q(ctx, "SELECT COUNT(*) FROM availability_transitions WHERE film_id = ? AND source = 'criterion' "
                   "AND appeared_on = ?", _fid(ctx, title), ctx["day"].isoformat()) == [(1,)]


@then("no film arrived on Criterion today")
def none_arrived(ctx):
    assert _q(ctx, "SELECT COUNT(*) FROM availability_transitions WHERE appeared_on = ?", ctx["day"].isoformat()) == [(0,)]


@then(parsers.parse('the film "{title}" is leaving "{label}"'))
def is_leaving(ctx, title, label):
    assert _q(ctx, "SELECT leaving_date FROM listings WHERE source = 'criterion' AND film_id = ?", _fid(ctx, title)) == [(label,)]


@then(parsers.parse('the film "{title}" is not leaving'))
def not_leaving(ctx, title):
    assert _q(ctx, "SELECT leaving_date FROM listings WHERE source = 'criterion' AND film_id = ?", _fid(ctx, title)) == [(None,)]


@then(parsers.parse('the film "{title}" is still on the watchlist'))
def still_watchlisted(ctx, title):
    assert _fid(ctx, title) in ctx["repo"].watchlist_film_ids()


@then(parsers.parse('there is {n:d} open criterion "{reason}" review for "{mediaid}"'))
def n_open(ctx, n, reason, mediaid):
    assert len(_open_rows(ctx, mediaid, reason)) == n


@then(parsers.parse('there is no open criterion review for "{mediaid}"'))
def none_open(ctx, mediaid):
    assert _open_rows(ctx, mediaid) == []


@then(parsers.parse("that review shows Criterion's title \"{title}\", year {year:d} and director \"{director}\""))
def review_shows(ctx, title, year, director):
    (row,) = ctx["repo"].open_reviews("criterion")
    crit = parse_criterion_detail(str(row["detail"]))
    assert crit is not None
    assert (crit["title"], crit["year"], crit["director"]) == (title, year, [director])


@then(parsers.re(r"JW Player was asked (?P<n>\d+) times? in all"))
def jw_asked(ctx, n):
    assert len(ctx["site"].media_calls) == int(n), ctx["site"].media_calls


@then("Criterion was never asked for its catalog")
def no_catalog_call(ctx):
    assert "catalog" not in ctx["site"].calls


@then(parsers.parse('the walk failure names "{text}"'))
def failure_names(ctx, text):
    assert text in str(ctx["error"])


@then("Criterion is exactly as it was before the walk")
def unchanged(ctx):
    assert _snapshot(ctx) == ctx["before"]


@then(parsers.parse('the resolver was asked about "{title}" with no director'))
def asked_no_director(ctx, title):
    q = next(q for q in ctx["fetcher"].queries if q.title == _q_title(title))
    assert q.director is None
