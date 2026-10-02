"""The creating gates, shared by `films add`, the Criterion walk and `review resolve` on a
criterion row (spec 2026-10-01 D5/D9). TMDB is the list tests' StubTmdb; ids are synthetic."""

from __future__ import annotations

from datetime import date

from lists_fakes import StubTmdb

from movie_brain.application.films import (
    CORPUS_VETO,
    KEY_COLLISION,
    NOT_A_FILM,
    TOMBSTONED_HOLDER,
    gate_ladder,
)
from movie_brain.application.lists import _catalog
from movie_brain.domain.matching import build_candidate_index
from movie_brain.domain.models import Film
from movie_brain.domain.thumbprint import Verdict
from movie_brain.infrastructure.tmdb import TmdbFacts

DAY = date(2026, 10, 3)


def _tmdb(tt="tt9000009", tid=909, title="The Glass Orchard", year=1961):
    t = StubTmdb(by_imdb={tt: tid})
    t.facts[tid] = TmdbFacts(tt, title, title, (), year, 90)
    return t


def _ladder(repo, tmdb, tt, **kw):
    rows = repo.films_for_matching()
    return gate_ladder(
        repo, tmdb, Verdict("match", tt, "test", ()),
        index=build_candidate_index(rows), catalog=_catalog(repo, rows), log=lambda _m: None, **kw,
    )


def test_a_film_holding_the_id_is_the_holder(repo):
    fid = repo.create_film(Film("Harbour Lights", 1972, None, ""))
    repo.set_external_id(fid, "imdb", "tt9000002", DAY)
    lad = _ladder(repo, _tmdb(), "tt9000002")
    assert (lad.kind, lad.holder) == ("held", fid)


def test_a_failed_gate_2b_is_weather_not_a_verdict(repo):
    assert _ladder(repo, StubTmdb(raises=True), "tt9000009").kind == "weather"


def test_an_id_tmdb_does_not_know_as_a_film_is_refused(repo):
    lad = _ladder(repo, StubTmdb(), "tt9000010")
    assert (lad.kind, lad.reason) == ("blocked", NOT_A_FILM)


def test_every_gate_clear_names_tmdbs_title_and_year(repo):
    lad = _ladder(repo, _tmdb(), "tt9000009")
    assert (lad.kind, lad.title, lad.year, lad.tmdb_id, lad.vetoed) == ("clear", "The Glass Orchard", 1961, 909, "")


def test_an_extra_form_widens_gate_3(repo):
    repo.create_film(Film("Le Verger de verre", 1961, None, ""))
    assert _ladder(repo, _tmdb(), "tt9000009").kind == "clear"
    lad = _ladder(repo, _tmdb(), "tt9000009", extra_forms=("Le Verger de verre",))
    assert (lad.kind, lad.reason) == ("blocked", CORPUS_VETO)


def test_with_the_veto_off_a_resemblance_is_reported_not_refused(repo):
    repo.create_film(Film("The Glass Orchard", 1999, None, ""))  # a remake: same title, other year
    lad = _ladder(repo, _tmdb(), "tt9000009", veto=False)
    assert lad.kind == "clear" and "'The Glass Orchard' (1999)" in lad.vetoed


def test_a_key_another_film_holds_is_a_collision_naming_it(repo):
    fid = repo.create_film(Film("The Glass Orchard", 1961, None, ""))
    lad = _ladder(repo, _tmdb(), "tt9000009", veto=False)
    assert (lad.kind, lad.reason, lad.holder) == ("blocked", KEY_COLLISION, fid)


def test_a_tombstoned_key_is_refused(repo):
    fid = repo.create_film(Film("The Glass Orchard", 1961, None, ""))
    repo.tombstone_film(fid, DAY, note="hidden by hand")
    lad = _ladder(repo, _tmdb(), "tt9000009")
    assert (lad.kind, lad.reason) == ("blocked", TOMBSTONED_HOLDER)
