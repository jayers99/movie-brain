from __future__ import annotations

import json
from datetime import date

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.legacy_import import ImportReport, import_legacy
from movie_brain.application.sync import SOURCE

scenarios("../features/legacy_import.feature")
TODAY = date(2026, 8, 19)


@pytest.fixture
def legacy(tmp_path):
    d = tmp_path / "legacy"
    (d / "payloads").mkdir(parents=True)
    return d


@pytest.fixture
def ctx(repo, legacy):
    return {"repo": repo, "legacy": legacy, "report": None}


@given(parsers.parse('a legacy data dir with catalog "{a}" and "{b}" fetched {fetched} leaving Trio "{label}"'))
def catalog(ctx, a, b, fetched, label):
    def film(s):
        title, year = s.rsplit(" (", 1)
        return {"title": title, "year": int(year[:-1]), "director": "Someone", "url": f"https://c/{title.lower()}"}

    films = [film(a), film(b)]
    (ctx["legacy"] / "catalog.json").write_text(
        json.dumps({"films_fetched_at": fetched, "films": films, "leaving": {"trio (1950)": label}})
    )


@given("the legacy cache rates Trio 7.1/90 English and marks Quartet not found")
def cache(ctx):
    ctx["cache"] = {
        "trio (1950)": {
            "found": True,
            "imdb": 7.1,
            "rt": 90,
            "language": "English",
            "looked_up": "2026-08-10",
            "year_fallback": True,
        },
        "quartet (1948)": {
            "found": False,
            "imdb": None,
            "rt": None,
            "language": None,
            "looked_up": "2026-08-10",
            "year_fallback": True,
        },
    }
    (ctx["legacy"] / "cache.json").write_text(json.dumps(ctx["cache"]))


@given("the legacy cache entry for Trio has no language key")
def cache_no_language(ctx):
    del ctx["cache"]["trio (1950)"]["language"]
    (ctx["legacy"] / "cache.json").write_text(json.dumps(ctx["cache"]))


@given("a legacy payload file exists for Trio")
def payload(ctx):
    (ctx["legacy"] / "payloads" / "trio (1950).json").write_text('{"Title": "Trio", "Response": "True"}')


@given(parsers.parse('legacy annotations rate Trio {a:d} and "{other}" {b:d}'))
def annotations(ctx, a, other, b):
    (ctx["legacy"] / "annotations.json").write_text(json.dumps({"trio (1950)": a, other.lower(): b}))


@given("the legacy catalog file is removed")
def remove_catalog(ctx):
    (ctx["legacy"] / "catalog.json").unlink()


@when("I import the legacy dir")
def do_import(ctx):
    ctx["report"] = import_legacy(ctx["repo"], ctx["legacy"], TODAY)


@then(parsers.parse("the report counts {f:d} films, {o:d} omdb rows, {p:d} payloads, {r:d} ratings"))
def counts(ctx, f, o, p, r):
    rep: ImportReport = ctx["report"]
    assert (rep.films, rep.omdb, rep.payloads, rep.ratings) == (f, o, p, r)


@then(parsers.parse('the report lists unmatched key "{key}"'))
def unmatched(ctx, key):
    assert key in ctx["report"].unmatched_keys


@then(
    parsers.parse(
        'Trio\'s view shows imdb {imdb:g}, rt {rt:d}, leaving "{label}", first_seen {fs}, my rating {score:d}'
    )
)
def trio_view(ctx, imdb, rt, label, fs, score):
    v = ctx["repo"].get_view(ctx["repo"].film_id_by_key("trio (1950)"))
    assert (v.imdb, v.rt, v.leaving_date, v.first_seen, v.my_rating) == (imdb, rt, label, fs, score)


@then(parsers.parse('Trio\'s payload contains "{text}"'))
def trio_payload(ctx, text):
    assert text in ctx["repo"].get_payload(ctx["repo"].film_id_by_key("trio (1950)"))


@then("Quartet is unmatched and not pending")
def quartet(ctx):
    v = ctx["repo"].get_view(ctx["repo"].film_id_by_key("quartet (1948)"))
    assert (v.found, v.pending) == (False, False)


@then(parsers.parse("films_fetched_at is {day}"))
def fetched(ctx, day):
    assert ctx["repo"].get_meta("films_fetched_at") == day


@then(parsers.parse("{n:d} films are current"))
def current(ctx, n):
    assert len(ctx["repo"].current_films(SOURCE)) == n


@then("Trio needs an OMDb lookup")
def trio_needs(ctx):
    assert "trio (1950)" in {f.key for _, f in ctx["repo"].films_needing_lookup(SOURCE, TODAY)}


@then("importing raises FileNotFoundError")
def raises(ctx):
    with pytest.raises(FileNotFoundError):
        import_legacy(ctx["repo"], ctx["legacy"], TODAY)
