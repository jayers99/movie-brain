from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pytest
import requests
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.trailers import TrailerReport, enrich_trailers
from movie_brain.domain.models import Film

scenarios("../features/trailers.feature")

D = date(2026, 9, 20)


def _video(name: str, type_: str, lang: str = "en") -> dict[str, Any]:
    key = ("k" + "".join(ch for ch in name.lower() if ch.isalnum()))[:11].ljust(11, "0")
    return {"key": key, "name": name, "type": type_, "official": True, "size": 1080, "iso_639_1": lang, "site": "YouTube"}


@dataclass
class FakeTmdb:
    """Only the one call the verb may make. `videos[(tmdb_id, languages)]`."""

    videos: dict[tuple[int, str], list[dict[str, Any]]] = field(default_factory=dict)
    language: dict[int, str] = field(default_factory=dict)
    failing: set[int] = field(default_factory=set)
    missing: set[int] = field(default_factory=set)
    asked: list[tuple[int, str]] = field(default_factory=list)

    def movie_videos(self, tmdb_id: int, languages: str = "en,null") -> tuple[str | None, list[dict[str, Any]]]:
        self.asked.append((tmdb_id, languages))
        if tmdb_id in self.failing:
            raise requests.ConnectionError("tmdb down")
        if tmdb_id in self.missing:
            response = requests.Response()
            response.status_code = 404
            raise requests.HTTPError("404 Client Error", response=response)
        return self.language.get(tmdb_id, "en"), self.videos.get((tmdb_id, languages), [])


@dataclass
class FakeItunes:
    urls: dict[str, str] = field(default_factory=dict)
    down: bool = False
    asked: list[list[str]] = field(default_factory=list)

    def previews(self, itunes_ids: list[str]) -> dict[str, str]:
        self.asked.append(list(itunes_ids))
        if self.down:
            raise requests.ConnectionError("apple down")
        return {i: self.urls[i] for i in itunes_ids if i in self.urls}


@pytest.fixture
def tmdb() -> FakeTmdb:
    return FakeTmdb()


@pytest.fixture
def itunes() -> FakeItunes:
    return FakeItunes()


@pytest.fixture
def films() -> dict[str, int]:
    return {}


@pytest.fixture
def result() -> dict[str, TrailerReport]:
    return {}


def _run(repo, tmdb, itunes, **kw) -> TrailerReport:
    return enrich_trailers(repo, tmdb, itunes, D, sleep=lambda s: None, log=lambda m: None, **kw)


def _add(repo, films, title, year, tmdb_id, store_id=None):
    fid = repo.create_film(Film(title, year, "Dir", ""))
    assert fid is not None
    repo.set_external_id(fid, "tmdb", str(tmdb_id), D)
    if store_id:
        repo.set_external_id(fid, "itunes", store_id, D)
    films[title] = fid


# Given ---------------------------------------------------------------------
@given(parsers.parse('a film "{title}" ({year:d}) holding tmdb id {tmdb_id:d} and store id "{store_id}"'))
def film_with_store(repo, films, title, year, tmdb_id, store_id):
    _add(repo, films, title, year, tmdb_id, store_id)


@given(parsers.parse('a film "{title}" ({year:d}) holding tmdb id {tmdb_id:d} and no store id'))
def film_without_store(repo, films, title, year, tmdb_id):
    _add(repo, films, title, year, tmdb_id)


@given(parsers.parse('TMDB files for tmdb id {tmdb_id:d} a "{type_a}" "{name_a}" and a "{type_b}" "{name_b}"'))
def tmdb_files_two(tmdb, tmdb_id, type_a, name_a, type_b, name_b):
    tmdb.videos[(tmdb_id, "en,null")] = [_video(name_a, type_a), _video(name_b, type_b)]


@given(parsers.parse("TMDB files no videos for tmdb id {tmdb_id:d}"))
def tmdb_files_nothing(tmdb, tmdb_id):
    tmdb.videos[(tmdb_id, "en,null")] = []


@given(parsers.parse(
    'TMDB files no English videos for the "{lang}" film with tmdb id {tmdb_id:d} but a "{vlang}" "{type_}" "{name}"'
))
def tmdb_files_own_language(tmdb, lang, tmdb_id, vlang, type_, name):
    tmdb.language[tmdb_id] = lang
    tmdb.videos[(tmdb_id, lang)] = [_video(name, type_, vlang)]


@given(parsers.parse(
    'TMDB files for the "{lang}" film with tmdb id {tmdb_id:d} an English "{type_a}" "{name_a}" and a "{vlang}" "{type_b}" "{name_b}"'
))
def tmdb_files_teaser_and_own_trailer(tmdb, lang, tmdb_id, type_a, name_a, vlang, type_b, name_b):
    tmdb.language[tmdb_id] = lang
    tmdb.videos[(tmdb_id, "en,null")] = [_video(name_a, type_a)]
    tmdb.videos[(tmdb_id, lang)] = [_video(name_b, type_b, vlang)]


@given(parsers.parse("TMDB answers 404 for tmdb id {tmdb_id:d}"))
def tmdb_404(tmdb, tmdb_id):
    tmdb.missing.add(tmdb_id)


@given(parsers.parse('the film "{title}" also holds store id "{store_id}"'))
def second_store_id(repo, films, title, store_id):
    repo.set_external_id(films[title], "itunes", store_id, D)


@given(parsers.parse("{n:d} more films holding tmdb ids that TMDB cannot serve"))
def many_failing(repo, films, tmdb, n):
    for k in range(n):
        _add(repo, films, f"Broken {k}", 1990, 7000 + k)
        tmdb.failing.add(7000 + k)


@given(parsers.parse("TMDB cannot serve tmdb id {tmdb_id:d}"))
def tmdb_fails(tmdb, tmdb_id):
    tmdb.failing.add(tmdb_id)


@given(parsers.parse('Apple publishes a preview for store id "{store_id}"'))
def apple_preview(itunes, store_id):
    itunes.urls[store_id] = f"https://video-ssl.itunes.apple.com/itunes-assets/{store_id}.m4v"


@given("Apple's lookup is down")
def apple_down(itunes):
    itunes.down = True


@given("trailers were already looked up")
def already_looked_up(repo, tmdb, itunes):
    _run(repo, tmdb, itunes, apply=True)


# When ----------------------------------------------------------------------
@when("I look up trailers without applying")
def dry_run(repo, tmdb, itunes, result):
    result["report"] = _run(repo, tmdb, itunes)


@when("I look up trailers with apply")
def apply_run(repo, tmdb, itunes, result):
    result["report"] = _run(repo, tmdb, itunes, apply=True)


@when("I refresh trailers with apply")
def refresh_run(repo, tmdb, itunes, result):
    result["report"] = _run(repo, tmdb, itunes, apply=True, refresh=True)


# Then ----------------------------------------------------------------------
@then(parsers.parse("the trailer report counts {scanned:d} scanned and {youtube:d} with a YouTube trailer"))
def report_scanned(result, scanned, youtube):
    assert (result["report"].scanned, result["report"].with_youtube) == (scanned, youtube)


@then(parsers.parse("the trailer report counts {apple:d} Apple-only and {nothing:d} with nothing"))
def report_apple(result, apple, nothing):
    assert (result["report"].apple_only, result["report"].nothing) == (apple, nothing)


@then(parsers.parse("the trailer report counts {failed:d} failed"))
def report_failed(result, failed):
    assert result["report"].failed == failed


@then("the trailer report is marked aborted")
def report_aborted(result):
    assert result["report"].aborted


@then(parsers.parse('the film "{title}" has no stored trailers'))
def no_trailers(repo, films, title):
    assert repo.film_trailers(films[title]) == []


@then(parsers.parse('the film "{title}" plays "{name}" from "{source}" first'))
def plays_first(repo, films, title, name, source):
    first = repo.film_trailers(films[title])[0]
    assert (first["name"], first["source"]) == (name, source)


@then(parsers.parse('the film "{title}" plays "{name}" from "{source}" last'))
def plays_last(repo, films, title, name, source):
    last = repo.film_trailers(films[title])[-1]
    assert (last["name"], last["source"]) == (name, source)


@then(parsers.parse('the film "{title}" never plays "{name}"'))
def never_plays(repo, films, title, name):
    assert name not in [t["name"] for t in repo.film_trailers(films[title])]


@then(parsers.parse("TMDB was asked for videos {n:d} time"))
def tmdb_asked(tmdb, n):
    assert len(tmdb.asked) == n


@then(parsers.parse("looking up trailers again scans {n:d} films"))
def again(repo, itunes, n):
    itunes.down = False
    assert _run(repo, FakeTmdb(), itunes).scanned == n
