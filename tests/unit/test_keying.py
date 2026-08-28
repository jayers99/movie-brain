from __future__ import annotations

import requests

from movie_brain.application.keying import key_film
from movie_brain.domain.models import Film, OmdbRating


class FakeTmdb:
    def __init__(self, by_imdb=None, years=None, boom=False):
        self.by_imdb, self.years, self.boom = by_imdb or {}, years or {}, boom

    def find_by_imdb(self, tt):
        if self.boom:
            raise requests.ConnectionError("offline")
        return self.by_imdb.get(tt)

    def movie_year(self, tid):
        if self.boom:
            raise requests.ConnectionError("offline")
        return self.years.get(tid)


def _film(repo, today, title, year, *, commerce=True):
    fid = repo.create_film(Film(title, year, None, ""))
    repo.upsert_omdb(fid, OmdbRating(None, None, False, None, None), today)
    if not commerce:
        repo.record_listing(fid, "criterion", f"https://c/{title.lower()}", today)
    return fid


def test_key_film_writes_both_ids_and_queues_an_omdb_refresh(repo, today):
    fid = _film(repo, today, "Bound", 1996)
    r = key_film(repo, FakeTmdb(by_imdb={"tt0116367": 9081}, years={9081: 1996}), fid, "tt0116367", today, print)
    assert (r.status, r.tmdb_id) == ("keyed", 9081)
    ids = repo.external_ids_for(fid)
    assert (ids["imdb"], ids["tmdb"]) == ("tt0116367", "9081")
    assert repo.tmdb_found(fid) is True


def test_key_film_without_a_tmdb_record_is_unlinked_but_keeps_the_imdb_id(repo, today):
    fid = _film(repo, today, "Solfatara", 1990)
    r = key_film(repo, FakeTmdb(), fid, "tt9999999", today, print)
    assert r.status == "unlinked"
    assert repo.external_ids_for(fid)["imdb"] == "tt9999999"
    assert repo.external_ids_for(fid).get("tmdb") is None


def test_key_film_refuses_a_tt_another_film_holds_and_writes_nothing(repo, today):
    holder = _film(repo, today, "Bound", 1996)
    repo.set_external_id(holder, "imdb", "tt0116367", today)
    other = _film(repo, today, "Bound", 1997)
    r = key_film(repo, FakeTmdb(), other, "tt0116367", today, print)
    assert r.status == "held" and f"#{holder}" in r.detail
    assert repo.external_ids_for(other) == {}


def test_key_film_refuses_a_tmdb_id_another_film_holds(repo, today):
    holder = _film(repo, today, "Bound", 1996)
    repo.set_external_id(holder, "tmdb", "9081", today)
    other = _film(repo, today, "Bound", 1997)
    r = key_film(repo, FakeTmdb(by_imdb={"tt0116367": 9081}), other, "tt0116367", today, print)
    assert r.status == "held" and r.tmdb_id == 9081
    assert repo.external_ids_for(other) == {}


def test_key_film_reports_tmdb_weather_as_error_without_writing(repo, today):
    fid = _film(repo, today, "Bound", 1996)
    r = key_film(repo, FakeTmdb(boom=True), fid, "tt0116367", today, print)
    assert r.status == "error"
    assert repo.external_ids_for(fid) == {}


def test_key_film_canonicalizes_a_commerce_film_year_to_tmdb(repo, today):
    fid = _film(repo, today, "Stop Making Sense", 2023)
    key_film(repo, FakeTmdb(by_imdb={"tt0088178": 606}, years={606: 1984}), fid, "tt0088178", today, print)
    assert repo.get_view(fid, today).year == 1984


def test_key_film_leaves_a_criterion_film_year_alone(repo, today):
    fid = _film(repo, today, "Trio", 1950, commerce=False)
    key_film(repo, FakeTmdb(by_imdb={"tt0037800": 11}, years={11: 1949}), fid, "tt0037800", today, print)
    assert repo.get_view(fid, today).year == 1950


class FindByImdbForbidden(FakeTmdb):
    """find_by_imdb raises if called — proves resolve_tmdb_id=False skips the lookup."""

    def find_by_imdb(self, tt):
        raise AssertionError("find_by_imdb should not be called when resolve_tmdb_id=False")


def test_key_film_with_resolve_tmdb_id_false_trusts_none_and_skips_the_lookup(repo, today):
    fid = _film(repo, today, "Bound", 1996)
    r = key_film(
        repo, FindByImdbForbidden(), fid, "tt0116367", today, print, tmdb_id=None, resolve_tmdb_id=False
    )
    assert r.status == "unlinked"
    ids = repo.external_ids_for(fid)
    assert ids["imdb"] == "tt0116367"
    assert ids.get("tmdb") is None
