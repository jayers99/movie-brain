"""`record_criterion_walk` and its neighbours (spec 2026-10-01 D2, D4, D6, D7, D10). Films are
seeded as the bridge leaves them: holding their mediaid, listed on the last VHX walk (LAST)."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import pytest

from movie_brain.domain.models import CriterionWalk, Film, NewFilm, ReviewEntry, WalkListing
from movie_brain.infrastructure.database import Repository

LAST = date(2026, 9, 20)  # the last VHX walk: every seeded listing's last_seen, so the frontier
TODAY = date(2026, 10, 3)
SITE = "https://www.criterionchannel.com"
TABLES = ("films", "listings", "external_ids", "claim", "match_review", "availability_transitions", "meta")


def _q(repo, sql, *args):
    conn = sqlite3.connect(repo.db_path)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def _dump(repo):
    return {t: _q(repo, f"SELECT * FROM {t} ORDER BY rowid") for t in TABLES}


def _listed(repo, title, year, mediaids, *, on=LAST, url=None):
    fid = repo.create_film(Film(title, year, None, ""))
    for m in mediaids:
        repo.set_external_id(fid, "criterion", m, on)
    repo.record_listing(fid, "criterion", url or f"{SITE}/films/{mediaids[0]}/x", on)
    return fid


def _label(repo, fid, label):
    conn = sqlite3.connect(repo.db_path)
    conn.execute("UPDATE listings SET leaving_date = ? WHERE film_id = ? AND source = 'criterion'", (label, fid))
    conn.commit()
    conn.close()


def _labels(repo):
    return dict(_q(repo, "SELECT film_id, leaving_date FROM listings WHERE source = 'criterion'"))


def _item(fid, mediaid, title="T", year=None):
    return WalkListing(mediaid, title, year, film_id=fid)


def _walk(*listings, created=(), reviews=(), leaving=None):
    return CriterionWalk(tuple(listings), tuple(created), tuple(reviews), leaving)


def test_one_film_under_two_mediaids_is_one_listing_two_claims_and_no_arrival(repo):
    # Eve's Bayou #1150: theatrical 6tfyfj2f and director's cut gOkSarah, both bound by the bridge.
    fid = _listed(repo, "Eve's Bayou", 1997, ["6tfyfj2f", "gOkSarah"], url=f"{SITE}/films/6tfyfj2f/eves-bayou")
    wrote = repo.record_criterion_walk(
        _walk(_item(fid, "gOkSarah", "EVE'S BAYOU: Director's Cut", 2022), _item(fid, "6tfyfj2f", "Eve's Bayou", 1997)),
        TODAY,
    )
    assert (wrote.arrived, wrote.departed) == (0, 0)  # listed on LAST = the frontier: still current
    assert _q(repo, "SELECT url, last_seen FROM listings WHERE film_id = ?", fid) == [
        (f"{SITE}/films/6tfyfj2f/eves-bayou", "2026-10-03")
    ]
    assert sorted(_q(repo, "SELECT value, title_ingested, year_claimed FROM claim WHERE film_id = ?", fid)) == [
        ("6tfyfj2f", "Eve's Bayou", 1997),
        ("gOkSarah", "EVE'S BAYOU: Director's Cut", 2022),
    ]
    assert _q(repo, "SELECT COUNT(*) FROM availability_transitions") == [(0,)]


def test_a_listing_older_than_the_frontier_arrives_again(repo):
    old = _listed(repo, "Old Friend", 1960, ["OldFrnd1"], on=date(2026, 9, 1))  # departed before LAST
    cur = _listed(repo, "Current", 1970, ["Current1"])
    wrote = repo.record_criterion_walk(_walk(_item(old, "OldFrnd1"), _item(cur, "Current1")), TODAY)
    assert (wrote.arrived, wrote.departed) == (1, 0)
    assert _q(repo, "SELECT film_id, source, appeared_on FROM availability_transitions") == [
        (old, "criterion", "2026-10-03")
    ]


def test_a_new_film_is_born_holding_its_mediaid_its_claim_and_the_bare_link(repo):
    nf = NewFilm("Two or Three Things I Know About Her", 1967, "Jean-Luc Godard", "tt9000304", 8072)
    wrote = repo.record_criterion_walk(
        _walk(WalkListing("L5Z3RaiC", "2 or 3 Things I Know About Her", 1967, new=0, bind=True), created=(nf,)),
        TODAY,
    )
    ((fid, made),) = wrote.created
    assert made == nf and wrote.arrived == 1  # no listing before: an insert is an arrival
    assert _q(repo, "SELECT title, year, director FROM films WHERE id = ?", fid) == [
        ("Two or Three Things I Know About Her", 1967, "Jean-Luc Godard")
    ]
    assert ("criterion", "L5Z3RaiC") in repo.external_ids_all(fid)
    assert _q(repo, "SELECT film_id, title_ingested, year_claimed FROM claim WHERE value = 'L5Z3RaiC'") == [
        (fid, "2 or 3 Things I Know About Her", 1967)
    ]
    assert _q(repo, "SELECT url FROM listings WHERE film_id = ?", fid) == [(f"{SITE}/films/L5Z3RaiC",)]


def test_departures_are_current_listings_left_unstamped_and_a_same_day_walk_moves_nothing(repo):
    nadja = _listed(repo, "Nadja", 1994, ["7xCZH5br"])
    gone = _listed(repo, "Some Came Running", 1958, ["SmCmRn58"])
    first = repo.record_criterion_walk(_walk(_item(nadja, "7xCZH5br")), TODAY)
    assert (first.arrived, first.departed) == (0, 1)
    assert _q(repo, "SELECT last_seen FROM listings WHERE film_id = ?", gone) == [("2026-09-20",)]
    again = repo.record_criterion_walk(_walk(_item(nadja, "7xCZH5br")), TODAY)
    assert (again.arrived, again.departed) == (0, 0)  # Review Focus 2: currency is date-grained
    assert _q(repo, "SELECT COUNT(*) FROM films WHERE id = ?", gone) == [(1,)]  # departed is display, not delete


def test_leaving_labels_are_keyed_by_mediaid_and_replace_old_ones(repo):
    z = _listed(repo, "Zabriskie Point", 1970, ["Tg73fdO2"])
    n = _listed(repo, "Nadja", 1994, ["7xCZH5br"])
    _label(repo, n, "September 30")
    leaving = {"Tg73fdO2": "October 31", "NoOne001": "October 31"}  # Review Focus 4: nobody holds NoOne001
    repo.record_criterion_walk(_walk(_item(z, "Tg73fdO2"), _item(n, "7xCZH5br"), leaving=leaving), TODAY)
    assert _labels(repo) == {z: "October 31", n: None}


def test_unreadable_leaving_pages_keep_listed_labels_and_clear_departed_ones(repo):
    z = _listed(repo, "Zabriskie Point", 1970, ["Tg73fdO2"])
    s = _listed(repo, "Some Came Running", 1958, ["SmCmRn58"])
    _label(repo, z, "October 31")
    _label(repo, s, "September 30")
    repo.record_criterion_walk(_walk(_item(z, "Tg73fdO2"), leaving=None), TODAY)
    assert _labels(repo) == {z: "October 31", s: None}  # story 11: a film that left loses its label tonight


@pytest.mark.parametrize("stored", [f"{SITE}/nadja", f"{SITE}/films/Other001/nadja"])
def test_a_link_not_on_tonights_mediaid_becomes_the_bare_film_page(repo, stored):
    fid = _listed(repo, "Nadja", 1994, ["7xCZH5br"], url=stored)
    repo.record_criterion_walk(_walk(_item(fid, "7xCZH5br")), TODAY)
    assert _q(repo, "SELECT url FROM listings WHERE film_id = ?", fid) == [(f"{SITE}/films/7xCZH5br",)]


def test_review_rows_and_the_fetch_stamp_land_in_the_same_write(repo):
    repo.record_criterion_walk(_walk(reviews=(ReviewEntry("no-record", None, "Gh0stEnt", "{}"),)), TODAY)
    assert [(r["reason"], r["film_id"], r["value"]) for r in repo.open_reviews("criterion")] == [
        ("no-record", None, "Gh0stEnt")
    ]
    assert repo.criterion_review_values() == {"Gh0stEnt"}
    assert repo.get_meta("films_fetched_at") == "2026-10-03"


def test_a_failure_late_in_the_write_rolls_everything_back(repo, monkeypatch):
    fid = _listed(repo, "Nadja", 1994, ["7xCZH5br"])
    before = _dump(repo)

    def boom(c, leaving, day):
        raise RuntimeError("disk full")

    monkeypatch.setattr(Repository, "_walk_leaving", staticmethod(boom))
    walk = _walk(
        _item(fid, "7xCZH5br", "Nadja", 1995),
        WalkListing("L5Z3RaiC", "2 or 3 Things I Know About Her", 1967, new=0, bind=True),
        created=(NewFilm("Two or Three Things I Know About Her", 1967, None, "tt9000304", 8072),),
        reviews=(ReviewEntry("no-record", None, "Gh0stEnt", "{}"),),
    )
    with pytest.raises(RuntimeError, match="disk full"):
        repo.record_criterion_walk(walk, TODAY)
    assert _dump(repo) == before


def test_holders_are_canonical_and_ignore_old_links(repo):
    # Review Focus 3: a mediaid left on a merged-away film is listed on its survivor.
    survivor = repo.create_film(Film("Mirror", 1975, None, ""))
    loser = repo.create_film(Film("Zerkalo", 1975, None, ""))
    repo.set_external_id(loser, "criterion", "Mirr0r75", LAST)
    repo.set_external_id(loser, "criterion", f"{SITE}/mirror", LAST)
    conn = sqlite3.connect(repo.db_path)
    conn.execute(
        "INSERT INTO film_disposition (film_id, kind, survivor_id, note, created_at) "
        "VALUES (?, 'merged', ?, 'test', '2026-10-01')",
        (loser, survivor),
    )
    conn.commit()
    conn.close()
    assert repo.criterion_mediaid_holders() == {"Mirr0r75": survivor}


def test_binding_and_creating_by_hand_respect_the_one_holder_rule(repo):
    _listed(repo, "Nadja", 1994, ["7xCZH5br"])
    other = repo.create_film(Film("Nadja Twin", 1994, None, ""))
    with pytest.raises(sqlite3.IntegrityError):
        repo.bind_criterion_mediaid(other, "7xCZH5br", "Nadja", 1995, TODAY)
    new = repo.create_criterion_film(
        Film("K-ON! The Movie", 2011, "Naoko Yamada", ""), "VBLiQBrA", "K-ON! The Movie", 2011, TODAY
    )
    assert new is not None and ("criterion", "VBLiQBrA") in repo.external_ids_all(new)
    assert repo.create_criterion_film(Film("K-ON! The Movie", 2011, None, ""), "Other001", "x", 2011, TODAY) is None
    assert repo.film_id_for_external("criterion", "Other001") is None  # a refused create writes nothing


# Review finding 1: a film Criterion carried all along whose new mediaid did not bind on the first
# walk departs that night (D13); when it binds within the relaunch grace window it rejoins quietly.
def _two_nights(repo, second):
    a = _listed(repo, "Nadja", 1994, ["7xCZH5br"])
    b = _listed(repo, "K-ON! The Movie", 2011, ["VBLiQBrA"])
    first = repo.record_criterion_walk(_walk(_item(a, "7xCZH5br")), TODAY)
    assert (first.arrived, first.departed) == (0, 1)
    return b, repo.record_criterion_walk(_walk(_item(a, "7xCZH5br"), _item(b, "VBLiQBrA")), second)


def test_a_film_held_all_along_rejoins_quietly_inside_the_grace_window(repo):
    b, second = _two_nights(repo, TODAY + timedelta(days=1))
    assert second.arrived == 0
    assert _q(repo, "SELECT COUNT(*) FROM availability_transitions") == [(0,)]
    assert _q(repo, "SELECT last_seen FROM listings WHERE film_id = ?", b) == [("2026-10-04",)]


def test_a_return_after_the_grace_window_is_an_arrival(repo):
    b, second = _two_nights(repo, TODAY + timedelta(days=31))
    assert second.arrived == 1
    assert _q(repo, "SELECT film_id, appeared_on FROM availability_transitions") == [(b, "2026-11-03")]


def test_a_film_gone_before_the_relaunch_still_arrives_inside_the_window(repo):
    a = _listed(repo, "Nadja", 1994, ["7xCZH5br"])
    old = _listed(repo, "Old Friend", 1960, ["OldFrnd1"], on=date(2026, 9, 1))
    repo.record_criterion_walk(_walk(_item(a, "7xCZH5br")), TODAY)
    second = repo.record_criterion_walk(_walk(_item(a, "7xCZH5br"), _item(old, "OldFrnd1")), TODAY + timedelta(days=1))
    assert second.arrived == 1
    assert _q(repo, "SELECT film_id, appeared_on FROM availability_transitions") == [(old, "2026-10-04")]


def test_the_relaunch_metas_are_written_once_by_the_first_walk(repo):
    a = _listed(repo, "Nadja", 1994, ["7xCZH5br"])
    repo.record_criterion_walk(_walk(_item(a, "7xCZH5br")), TODAY)
    repo.record_criterion_walk(_walk(_item(a, "7xCZH5br")), TODAY + timedelta(days=2))
    assert repo.get_meta("criterion_relaunch_frontier") == "2026-09-20"
    assert repo.get_meta("criterion_relaunch_first_walk") == "2026-10-03"
