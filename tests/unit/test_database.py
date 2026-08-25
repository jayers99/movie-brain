import json
import re
import sqlite3
from datetime import date

import pytest

from movie_brain.domain.models import Film, McTitle, OmdbRating, ReviewEntry
from movie_brain.infrastructure.database import MIGRATIONS_DIR, FilmRow, Repository, TmdbMatchTarget, init_db

TRIO = Film("Trio", 1950, "Ken Annakin", "https://c/trio")
QUARTET = Film("Quartet", 1948, "Ken Annakin", "https://c/quartet")
D1, D2 = date(2026, 8, 1), date(2026, 8, 19)

UUID4_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def _v2_db_with_criterion_data(p):
    conn = sqlite3.connect(p)
    conn.executescript((MIGRATIONS_DIR / "001_init.sql").read_text())
    conn.executescript((MIGRATIONS_DIR / "002_metacritic.sql").read_text())
    conn.execute("INSERT INTO films (id, title, year, key) VALUES (1, 'Trio', 1950, 'trio (1950)')")
    conn.execute("INSERT INTO films (id, title, year, key) VALUES (2, 'Quartet', 1948, 'quartet (1948)')")
    conn.execute(
        "INSERT INTO listings VALUES (1, 'criterion', 'https://c/trio', '2026-08-01', '2026-08-19', NULL)"
    )
    conn.execute(
        "INSERT INTO listings VALUES (2, 'criterion', 'https://c/quartet', '2026-08-01', '2026-08-19', 'August 31')"
    )
    conn.execute("INSERT INTO omdb (film_id, found, looked_up, payload) VALUES (1, 1, '2026-08-01', '{}')")
    conn.execute("INSERT INTO my_ratings VALUES (1, 8, '2026-08-01')")
    conn.commit()
    conn.close()


def test_migration_003_assigns_guids_and_preserves_data(tmp_path):
    p = tmp_path / "old.db"
    _v2_db_with_criterion_data(p)
    init_db(p)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    guids = [r["guid"] for r in conn.execute("SELECT guid FROM films ORDER BY id")]
    assert len(guids) == 2 and len(set(guids)) == 2
    assert all(UUID4_RE.match(g) for g in guids)
    listings = {
        r["film_id"]: (r["url"], r["first_seen"], r["last_seen"], r["leaving_date"])
        for r in conn.execute("SELECT * FROM listings")
    }
    assert listings == {
        1: ("https://c/trio", "2026-08-01", "2026-08-19", None),
        2: ("https://c/quartet", "2026-08-01", "2026-08-19", "August 31"),
    }
    assert conn.execute("SELECT payload FROM omdb WHERE film_id = 1").fetchone()[0] == "{}"
    assert conn.execute("SELECT score FROM my_ratings WHERE film_id = 1").fetchone()[0] == 8
    conn.close()


def test_migration_003_backfills_criterion_external_ids(tmp_path):
    p = tmp_path / "old.db"
    _v2_db_with_criterion_data(p)
    init_db(p)
    conn = sqlite3.connect(p)
    ext = dict(conn.execute("SELECT film_id, value FROM external_ids WHERE authority = 'criterion'"))
    assert ext == {1: "https://c/trio", 2: "https://c/quartet"}
    assert conn.execute("SELECT first_seen FROM external_ids WHERE film_id = 1").fetchone()[0] == "2026-08-01"
    conn.close()


def test_migration_003_seeds_service_registry(repo):
    conn = sqlite3.connect(repo.db_path)
    services = dict(conn.execute("SELECT slug, subscribed FROM movie_service"))
    assert services == {
        "criterion": 1,
        "apple-tv-plus": 1,
        "apple-tv-store": 1,
        "max": 1,
        "peacock": 1,
        "prime-video": 1,
        "mubi": 0,
        "bfi-player-classics": 0,
    }
    kinds = dict(conn.execute("SELECT slug, kind FROM movie_service"))
    assert kinds["apple-tv-store"] == "store" and kinds["criterion"] == "svod"
    providers = dict(conn.execute("SELECT tmdb_provider_id, service_slug FROM service_provider"))
    assert providers == {
        258: "criterion",
        350: "apple-tv-plus",
        2: "apple-tv-store",
        1899: "max",
        386: "peacock",
        387: "peacock",
        9: "prime-video",
        11: "mubi",
    }
    conn.close()


def test_guid_is_stable_across_repeated_catalog_walks(repo):
    def guid():
        conn = sqlite3.connect(repo.db_path)
        g = conn.execute("SELECT guid FROM films WHERE key = 'trio (1950)'").fetchone()[0]
        conn.close()
        return g

    repo.record_catalog("criterion", [TRIO], D1)
    first = guid()
    assert UUID4_RE.match(first)
    repo.record_catalog("criterion", [TRIO], D2)
    repo.upsert_film(TRIO)
    assert guid() == first


def test_init_db_is_idempotent(tmp_path):
    p = tmp_path / "x.db"
    init_db(p)
    init_db(p)
    repo = Repository(p)
    assert repo.summary("criterion") == {
        "films": 0,
        "rated": 0,
        "pending": 0,
        "unmatched": 0,
        "leaving": 0,
        "mine": 0,
        "departed": 0,
        "discovery": 0,
        "owned": 0,
    }


def test_migration_backfills_metacritic_from_stored_payloads(tmp_path):
    p = tmp_path / "old.db"
    conn = sqlite3.connect(p)
    conn.executescript((MIGRATIONS_DIR / "001_init.sql").read_text())
    for fid, title, payload in (
        (1, "A", '{"Metascore": "74"}'),
        (2, "B", '{"Metascore": "N/A"}'),
        (3, "C", None),
    ):
        conn.execute("INSERT INTO films (id, title, year, key) VALUES (?, ?, 2000, ?)", (fid, title, f"{title} (2000)"))
        conn.execute(
            "INSERT INTO omdb (film_id, found, looked_up, payload) VALUES (?, 1, '2026-08-01', ?)", (fid, payload)
        )
    conn.commit()
    conn.close()
    init_db(p)
    conn = sqlite3.connect(p)
    assert dict(conn.execute("SELECT film_id, metacritic FROM omdb")) == {1: 74, 2: None, 3: None}
    conn.close()


def test_upsert_film_returns_stable_id_and_updates_fields(repo):
    fid = repo.upsert_film(TRIO)
    assert repo.upsert_film(Film("Trio", 1950, "K. Annakin & H. French", "https://c/trio2")) == fid
    assert repo.film_id_by_key("trio (1950)") == fid
    assert repo.film_id_by_key("nope (1)") is None


def test_record_listing_sets_first_seen_once_and_bumps_last_seen(repo):
    fid = repo.upsert_film(TRIO)
    repo.record_listing(fid, "criterion", TRIO.url, D1)
    repo.record_listing(fid, "criterion", "https://c/trio-new", D2)
    v = repo.get_view(fid)
    assert v is not None and v.first_seen == "2026-08-01" and v.url == "https://c/trio-new"


def test_current_films_is_latest_walk_only(repo):
    a = repo.upsert_film(TRIO)
    b = repo.upsert_film(QUARTET)
    repo.record_listing(a, "criterion", TRIO.url, D1)
    repo.record_listing(b, "criterion", QUARTET.url, D1)
    repo.record_listing(a, "criterion", TRIO.url, D2)  # Quartet dropped off the channel
    assert [f.key for _, f in repo.current_films("criterion")] == ["trio (1950)"]
    assert [v.title for v in repo.list_views("criterion")] == ["Trio"]


def test_set_leaving_replaces_previous(repo):
    a = repo.upsert_film(TRIO)
    b = repo.upsert_film(QUARTET)
    for fid, f in ((a, TRIO), (b, QUARTET)):
        repo.record_listing(fid, "criterion", f.url, D1)
    repo.set_leaving("criterion", {"trio (1950)": "August 31"})
    repo.set_leaving("criterion", {"quartet (1948)": "September 30"})
    views = {v.title: v.leaving_date for v in repo.list_views("criterion")}
    assert views == {"Trio": None, "Quartet": "September 30"}


def test_films_needing_lookup_rules(repo):
    ids = []
    for f in (TRIO, QUARTET, Film("Third", 1960, None, "u3"), Film("Fourth", 1970, None, "u4")):
        fid = repo.upsert_film(f)
        repo.record_listing(fid, "criterion", f.url, D2)
        ids.append(fid)
    repo.upsert_omdb(ids[0], OmdbRating(7.0, 80, True, "English", "{}"), D1)  # found → never again
    repo.upsert_omdb(ids[1], OmdbRating(None, None, False), date(2026, 7, 1))  # miss, 49 days old → retry
    repo.upsert_omdb(ids[2], OmdbRating(None, None, False), date(2026, 8, 10))  # miss, 9 days old → wait
    # ids[3] has no row → lookup
    need = sorted(fid for fid, _ in repo.films_needing_lookup("criterion", D2))
    assert need == sorted([ids[1], ids[3]])


def test_needs_refresh_and_legacy_miss_without_fallback_are_relooked(repo):
    a = repo.upsert_film(TRIO)
    b = repo.upsert_film(QUARTET)
    repo.record_listing(a, "criterion", TRIO.url, D2)
    repo.record_listing(b, "criterion", QUARTET.url, D2)
    repo.upsert_omdb(a, OmdbRating(7.0, None, True, None), D1, needs_refresh=True)
    repo.upsert_omdb(b, OmdbRating(None, None, False), D2, year_fallback=False)
    assert sorted(fid for fid, _ in repo.films_needing_lookup("criterion", D2)) == sorted([a, b])


def test_set_rating_and_unrate(repo):
    fid = repo.upsert_film(TRIO)
    repo.record_listing(fid, "criterion", TRIO.url, D2)
    assert repo.set_rating(fid, 8, D2) is True
    assert repo.get_view(fid).my_rating == 8
    assert repo.set_rating(fid, None, D2) is True
    assert repo.get_view(fid).my_rating is None
    assert repo.set_rating(999, 5, D2) is False
    assert repo.all_my_ratings() == {}


def test_views_and_summary(repo):
    a = repo.upsert_film(TRIO)
    b = repo.upsert_film(QUARTET)
    c = repo.upsert_film(Film("Third", 1960, None, "u3"))
    for fid, f in ((a, TRIO), (b, QUARTET), (c, Film("Third", 1960, None, "u3"))):
        repo.record_listing(fid, "criterion", f.url, D2)
    repo.upsert_omdb(a, OmdbRating(7.5, 91, True, "English", '{"Title":"Trio"}', metacritic=88), D2)
    repo.upsert_omdb(b, OmdbRating(None, None, False), D2)
    repo.set_leaving("criterion", {"trio (1950)": "August 31"})
    repo.set_rating(a, 0, D2)
    va = repo.get_view(a)
    assert (va.imdb, va.rt, va.metacritic, va.found, va.pending, va.leaving_date, va.my_rating) == (
        7.5,
        91,
        88,
        True,
        False,
        "August 31",
        0,
    )
    vc = repo.get_view(c)
    assert (vc.found, vc.pending) == (None, True)
    assert repo.get_payload(a) == '{"Title":"Trio"}' and repo.get_payload(c) is None
    assert repo.summary("criterion") == {
        "films": 3,
        "rated": 1,
        "pending": 1,
        "unmatched": 1,
        "leaving": 1,
        "mine": 1,
        "departed": 0,
        "discovery": 0,
        "owned": 0,
    }


def test_rated_departed_film_stays_visible_and_flagged(repo):
    a = repo.upsert_film(TRIO)
    b = repo.upsert_film(QUARTET)
    repo.record_listing(a, "criterion", TRIO.url, D1)
    repo.record_listing(b, "criterion", QUARTET.url, D1)
    repo.set_rating(a, 8, D1)
    repo.record_listing(b, "criterion", QUARTET.url, D2)  # Trio dropped off the channel
    views = {v.title: v.departed for v in repo.list_views("criterion")}
    assert views == {"Trio": True, "Quartet": False}
    assert repo.get_view(a).departed is True
    assert repo.summary("criterion")["departed"] == 1


def test_unrated_departed_film_is_kept_but_hidden(repo):
    a = repo.upsert_film(TRIO)
    b = repo.upsert_film(QUARTET)
    repo.record_listing(a, "criterion", TRIO.url, D1)  # 18 days stale — past the old grace window
    repo.record_listing(b, "criterion", QUARTET.url, D2)
    assert [v.title for v in repo.list_views("criterion")] == ["Quartet"]
    assert repo.film_id_by_key("trio (1950)") == a


def test_record_catalog_bulk_matches_per_film_calls(repo):
    repo.record_catalog("criterion", [TRIO, QUARTET], D1)
    repo.record_catalog("criterion", [TRIO], D2)
    assert [f.key for _, f in repo.current_films("criterion")] == ["trio (1950)"]
    assert repo.get_view(repo.film_id_by_key("trio (1950)")).first_seen == "2026-08-01"


def test_meta(repo):
    assert repo.get_meta("films_fetched_at") is None
    repo.set_meta("films_fetched_at", "2026-08-19")
    repo.set_meta("films_fetched_at", "2026-08-20")
    assert repo.get_meta("films_fetched_at") == "2026-08-20"


def test_external_id_roundtrip_update_and_uniqueness(repo):
    a = repo.upsert_film(TRIO)
    b = repo.upsert_film(QUARTET)
    repo.set_external_id(a, "tmdb", "603", D1)
    repo.set_external_id(a, "tmdb", "604", D2)  # same film+authority: value updates
    repo.set_external_id(a, "imdb", "tt0042980", D2)
    assert repo.external_ids_for(a) == {"tmdb": "604", "imdb": "tt0042980"}
    assert repo.external_ids_for(b) == {}
    with pytest.raises(sqlite3.IntegrityError):  # two films can't claim one external id
        repo.set_external_id(b, "tmdb", "604", D2)


def test_record_catalog_records_criterion_external_ids(repo):
    repo.record_catalog("criterion", [TRIO], D1)
    fid = repo.film_id_by_key("trio (1950)")
    assert fid is not None
    assert repo.external_ids_for(fid) == {"criterion": "https://c/trio"}


def test_record_catalog_contains_external_id_uniqueness_conflicts(repo):
    repo.record_catalog("criterion", [TRIO], D1)
    trio_fid = repo.film_id_by_key("trio (1950)")
    assert trio_fid is not None

    # Criterion corrects the year: new key, same URL. The external_ids UNIQUE(authority,
    # value) conflict must not escape record_catalog or roll back the films/listings writes.
    corrected = Film("Trio", 1951, None, TRIO.url)
    repo.record_catalog("criterion", [corrected], D2)

    corrected_fid = repo.film_id_by_key("trio (1951)")
    assert corrected_fid is not None
    assert corrected_fid != trio_fid

    # Both films exist and both got their listing recorded.
    assert repo.get_view(trio_fid) is not None
    assert repo.get_view(corrected_fid) is not None
    assert repo.get_view(corrected_fid).url == TRIO.url

    # The external id for the URL still maps to the original film — first writer wins.
    assert repo.external_ids_for(trio_fid) == {"criterion": TRIO.url}
    assert repo.external_ids_for(corrected_fid) == {}


def test_services_registry_accessor(repo):
    services = {s["slug"]: s for s in repo.services()}
    assert len(services) == 8
    assert services["criterion"]["subscribed"] == 1
    assert services["mubi"]["subscribed"] == 0
    assert services["apple-tv-store"]["kind"] == "store"
    assert services["prime-video"]["region"] == "US"


def test_init_db_backs_up_before_applying_pending_migrations(tmp_path):
    p = tmp_path / "x.db"
    conn = sqlite3.connect(p)
    conn.executescript((MIGRATIONS_DIR / "001_init.sql").read_text())
    conn.execute("INSERT INTO films (id, title, year, key) VALUES (1, 'Trio', 1950, 'trio (1950)')")
    conn.commit()
    conn.close()
    init_db(p)  # later migrations are pending → snapshot the v1 state first
    backups = list((tmp_path / "backups").glob("x-v1-*.db"))
    assert len(backups) == 1
    b = sqlite3.connect(backups[0])
    assert b.execute("SELECT title FROM films").fetchone()[0] == "Trio"
    assert b.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == 1  # pre-migration state
    b.close()


def test_init_db_makes_no_backup_for_fresh_or_up_to_date_dbs(tmp_path):
    p = tmp_path / "x.db"
    init_db(p)  # fresh DB: nothing to protect
    init_db(p)  # up to date: nothing pending
    assert not (tmp_path / "backups").exists()


def test_init_db_never_overwrites_an_existing_backup_snapshot(tmp_path):
    p = tmp_path / "x.db"
    conn = sqlite3.connect(p)
    conn.executescript((MIGRATIONS_DIR / "001_init.sql").read_text())
    conn.execute("INSERT INTO films (id, title, year, key) VALUES (1, 'Trio', 1950, 'trio (1950)')")
    conn.commit()
    conn.close()

    backups_dir = tmp_path / "backups"
    backups_dir.mkdir()
    dest_path = backups_dir / f"x-v1-{date.today().isoformat()}.db"
    sentinel = b"not a real sqlite file - pre-existing snapshot must survive byte-identical"
    dest_path.write_bytes(sentinel)

    init_db(p)  # a same-day re-run must never clobber the existing snapshot

    assert dest_path.read_bytes() == sentinel


def test_migration_004_creates_metacritic_tables(repo):
    conn = sqlite3.connect(repo.db_path)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"metacritic", "match_review"} <= tables
        assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == 10
    finally:
        conn.close()


def test_upsert_mc_titles_is_an_upsert(repo, today):
    t1 = McTitle("seven-samurai-1954", "Seven Samurai", 1956, 98, 1, 1)
    repo.upsert_mc_titles([t1], today)
    # a re-crawl updates the same slug in place
    t2 = McTitle("seven-samurai-1954", "Seven Samurai", 1956, 99, 2, 1)
    repo.upsert_mc_titles([t2], today)
    conn = sqlite3.connect(repo.db_path)
    try:
        rows = conn.execute("SELECT slug, score, rank FROM metacritic").fetchall()
        assert rows == [("seven-samurai-1954", 99, 2)]
    finally:
        conn.close()


def test_films_for_matching_includes_omdb_metascore(repo, today):
    fid = repo.upsert_film(Film("Alpha", 1950, "Ann", "https://c/alpha"))
    repo.upsert_omdb(fid, OmdbRating(None, None, True, metacritic=85), today)
    fid2 = repo.upsert_film(Film("Beta", 1960, "Bob", "https://c/beta"))
    rows = repo.films_for_matching()
    assert FilmRow(fid, "Alpha", 1950, "Ann", None, 85) in rows
    assert FilmRow(fid2, "Beta", 1960, "Bob", None, None) in rows


def test_films_for_matching_reads_director_and_runtime_from_omdb_payload(repo, today):
    # NULL films.director falls back to the OMDb payload; "91 min" parses to 91.
    fid = repo.upsert_film(Film("Gamma", 1970, None, "https://c/gamma"))
    payload = json.dumps({"Director": "Jane Doe", "Runtime": "91 min"})
    repo.upsert_omdb(fid, OmdbRating(None, None, True, payload=payload), today)
    row = next(r for r in repo.films_for_matching() if r.id == fid)
    assert (row.director, row.runtime_min) == ("Jane Doe", 91)


def test_films_for_matching_treats_omdb_na_as_missing(repo, today):
    fid = repo.upsert_film(Film("Delta", 1980, None, "https://c/delta"))
    payload = json.dumps({"Director": "N/A", "Runtime": "N/A"})
    repo.upsert_omdb(fid, OmdbRating(None, None, True, payload=payload), today)
    row = next(r for r in repo.films_for_matching() if r.id == fid)
    assert (row.director, row.runtime_min) == (None, None)


def test_film_ids_with_external(repo, today):
    fid = repo.upsert_film(Film("Alpha", 1950, "Ann", "https://c/alpha"))
    assert repo.film_ids_with_external("metacritic") == set()
    repo.set_external_id(fid, "metacritic", "alpha-1950", today)
    assert repo.film_ids_with_external("metacritic") == {fid}


def test_review_queue_replaces_unresolved_and_keeps_resolved(repo, today):
    repo.replace_unresolved_reviews("metacritic", [ReviewEntry("ambiguous-title", value="twin-1979")], today)
    (row,) = repo.open_reviews("metacritic")
    # a human resolves it (Phase 8 tooling will do this; raw SQL stands in for it here)
    conn = sqlite3.connect(repo.db_path)
    try:
        conn.execute("UPDATE match_review SET resolved = 1 WHERE id = ?", (row["id"],))
        conn.commit()
    finally:
        conn.close()
    # the next match run replaces unresolved rows but never touches resolved ones
    repo.replace_unresolved_reviews("metacritic", [ReviewEntry("expected-miss", film_id=None, detail="x")], today)
    assert [r["reason"] for r in repo.open_reviews("metacritic")] == ["expected-miss"]
    conn = sqlite3.connect(repo.db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM match_review WHERE resolved = 1").fetchone()[0] == 1
    finally:
        conn.close()


class TestTmdbPrimitives:
    def seed_two(self, repo):
        repo.record_catalog("criterion", [Film("Trio", 1950, None, "https://c/trio"),
                                          Film("Quartet", 1948, None, "https://c/quartet")], date(2026, 8, 19))
        return repo.film_id_by_key("trio (1950)"), repo.film_id_by_key("quartet (1948)")

    def test_films_needing_tmdb_match_excludes_any_tmdb_row(self, repo):
        trio, quartet = self.seed_two(repo)
        repo.upsert_tmdb(trio, found=True, looked_up=date(2026, 8, 19))
        assert repo.films_needing_tmdb_match() == [TmdbMatchTarget(quartet, "Quartet", 1948, False)]
        repo.upsert_tmdb(quartet, found=False, looked_up=date(2026, 8, 19))
        assert repo.films_needing_tmdb_match() == []  # found=0 is not retried

    def test_provider_refresh_order_is_stalest_first(self, repo):
        trio, quartet = self.seed_two(repo)
        for fid, tid in ((trio, "11"), (quartet, "22")):
            repo.upsert_tmdb(fid, found=True, looked_up=date(2026, 8, 19))
            repo.set_external_id(fid, "tmdb", tid, date(2026, 8, 19))
        repo.record_tmdb_providers(trio, date(2026, 8, 19), "{}")
        assert repo.films_for_provider_refresh() == [
            (quartet, "22", True),
            (trio, "11", False),
        ]  # NULL checked_at first

    def test_missed_films_and_provider_map(self, repo):
        trio, _ = self.seed_two(repo)
        repo.upsert_tmdb(trio, found=False, looked_up=date(2026, 8, 19))
        assert repo.films_tmdb_missed() == [(trio, "Trio", 1950)]
        pmap = repo.provider_map()
        assert pmap[258] == "criterion" and pmap[1899] == "max" and pmap[2] == "apple-tv-store"


# ---- Phase 4: watchlist -------------------------------------------------


def test_toggle_watchlist_round_trip(repo, today):
    fid = repo.upsert_film(Film("Tokyo Story", 1953, "Ozu", "https://c/tokyo-story"))
    assert repo.watchlist_film_ids() == set()
    assert repo.toggle_watchlist(fid, today) is True
    assert repo.watchlist_film_ids() == {fid}
    assert repo.toggle_watchlist(fid, today) is False
    assert repo.watchlist_film_ids() == set()


def test_toggle_watchlist_unknown_film_returns_none(repo, today):
    assert repo.toggle_watchlist(9999, today) is None
    assert repo.watchlist_film_ids() == set()


# ---- Phase 4: transition detection --------------------------------------


def _transitions(repo):
    import sqlite3

    with sqlite3.connect(repo.db_path) as c:
        return c.execute(
            "SELECT film_id, source, appeared_on FROM availability_transitions ORDER BY id"
        ).fetchall()


def test_record_listing_with_transition_insert_fires(repo, today):
    fid = repo.upsert_film(Film("Playtime", 1967, "Tati", "https://c/playtime"))
    assert repo.record_listing_with_transition(fid, "max", "https://tmdb/w/1", today) is True
    assert _transitions(repo) == [(fid, "max", today.isoformat())]


def test_record_listing_with_transition_current_row_is_quiet(repo, today):
    fid = repo.upsert_film(Film("Playtime", 1967, "Tati", "https://c/playtime"))
    repo.record_listing_with_transition(fid, "max", "https://tmdb/w/1", today)
    repo.set_meta("tmdb_providers_refreshed_at", today.isoformat())
    # Next nightly write: row (today) is not older than the stamp (today) → no new event.
    assert repo.record_listing_with_transition(fid, "max", "https://tmdb/w/1", today) is False
    assert len(_transitions(repo)) == 1


def test_record_listing_with_transition_reappearance_past_stamp_fires(repo, today):
    from datetime import timedelta

    fid = repo.upsert_film(Film("Playtime", 1967, "Tati", "https://c/playtime"))
    repo.record_listing_with_transition(fid, "max", "https://tmdb/w/1", today - timedelta(days=10))
    # A completed full refresh moved the stamp past the row → it displayed as departed.
    repo.set_meta("tmdb_providers_refreshed_at", (today - timedelta(days=3)).isoformat())
    assert repo.record_listing_with_transition(fid, "max", "https://tmdb/w/1", today) is True
    assert len(_transitions(repo)) == 2


def test_record_catalog_reupsert_of_current_rows_is_quiet(repo, today):
    films = [Film("Alpha", 1950, "Ann", "https://c/alpha")]
    repo.record_catalog("criterion", films, today)  # fresh DB: insert → 1 event
    repo.record_catalog("criterion", films, today)  # cheap-check path re-upsert → quiet
    assert len(_transitions(repo)) == 1


def test_record_catalog_reappearance_fires(repo, today):
    from datetime import timedelta

    alpha = Film("Alpha", 1950, "Ann", "https://c/alpha")
    bravo = Film("Bravo", 1960, "Bob", "https://c/bravo")
    repo.record_catalog("criterion", [alpha, bravo], today - timedelta(days=30))
    repo.record_catalog("criterion", [bravo], today - timedelta(days=7))  # alpha departs
    repo.record_catalog("criterion", [alpha, bravo], today)  # alpha returns
    events = _transitions(repo)
    alpha_id = repo.film_id_by_key(alpha.key)
    assert (alpha_id, "criterion", today.isoformat()) in events
    assert len(events) == 3  # 2 initial inserts + 1 reappearance; bravo re-upserts stay quiet


def test_watchlist_transitions_on_filters_day_and_membership(repo, today):
    from datetime import timedelta

    wanted = repo.upsert_film(Film("Playtime", 1967, "Tati", "https://c/playtime"))
    other = repo.upsert_film(Film("Alpha", 1950, "Ann", "https://c/alpha"))
    repo.toggle_watchlist(wanted, today)
    repo.record_listing_with_transition(wanted, "max", "https://tmdb/w/1", today)
    repo.record_listing_with_transition(other, "max", "https://tmdb/w/2", today)  # not watchlisted
    repo.record_listing_with_transition(wanted, "mubi", "https://tmdb/w/1", today - timedelta(days=1))
    assert repo.watchlist_transitions_on(today) == [("Playtime", "HBO Max")]


# ---- Phase 4: services currency with refresh stamp -------------------------


def test_services_currency_follows_refresh_stamp_not_frozen_max(repo, today):
    from datetime import timedelta

    # get_view reads through the criterion-joined _VIEW_SQL, so the film needs a
    # criterion listing to be viewable at all.
    repo.record_catalog("criterion", [Film("Oppenheimer", 2023, "Nolan", "https://c/opp")], today)
    fid = repo.film_id_by_key("oppenheimer (2023)")
    repo.record_listing_with_transition(fid, "peacock", "https://tmdb/w/1", today - timedelta(days=10))
    # Peacock dropped to zero films; a completed full refresh moved the stamp past the row.
    repo.set_meta("tmdb_providers_refreshed_at", today.isoformat())
    view = repo.get_view(fid)
    assert view.services == []


def test_services_currency_falls_back_to_max_without_stamp(repo, today):
    repo.record_catalog("criterion", [Film("Oppenheimer", 2023, "Nolan", "https://c/opp")], today)
    fid = repo.film_id_by_key("oppenheimer (2023)")
    repo.record_listing_with_transition(fid, "peacock", "https://tmdb/w/1", today)
    view = repo.get_view(fid)  # no stamp set (fresh DB) — MAX rule keeps the row current
    assert [s["name"] for s in view.services] == ["Peacock"]


# ---- Phase 4: FilmView new_on + watchlisted ------------------------------


def test_views_carry_new_on_and_watchlisted(repo, today):
    from datetime import timedelta

    films = [Film("Alpha", 1950, "Ann", "https://c/alpha")]
    repo.record_catalog("criterion", films, today - timedelta(days=30))  # insert event, outside window
    fid = repo.film_id_by_key("alpha (1950)")
    repo.toggle_watchlist(fid, today)
    repo.record_listing_with_transition(fid, "max", "https://tmdb/w/1", today - timedelta(days=3))
    view = repo.get_view(fid, today)
    assert view.watchlisted is True
    assert view.new_on == [
        {"source": "max", "name": "HBO Max", "appeared_on": (today - timedelta(days=3)).isoformat()}
    ]
    (listed,) = [v for v in repo.list_views("criterion", today) if v.id == fid]
    assert listed.new_on == view.new_on and listed.watchlisted is True


# ---- Phase 4: nightly watchlist provider pass -----------------------------


def test_films_for_watchlist_refresh_is_watchlist_and_matched_only(repo, today):
    a = repo.upsert_film(Film("Alpha", 1950, "Ann", "https://c/alpha"))
    b = repo.upsert_film(Film("Bravo", 1960, "Bob", "https://c/bravo"))
    for fid, tid in ((a, 11), (b, 22)):
        repo.set_external_id(fid, "tmdb", str(tid), today)
        repo.upsert_tmdb(fid, found=True, looked_up=today)
    repo.toggle_watchlist(a, today)
    assert repo.films_for_watchlist_refresh() == [(a, "11", True)]


def test_films_for_provider_refresh_can_skip_films_checked_today(repo, today):
    a = repo.upsert_film(Film("Alpha", 1950, "Ann", "https://c/alpha"))
    repo.set_external_id(a, "tmdb", "11", today)
    repo.upsert_tmdb(a, found=True, looked_up=today)
    repo.record_tmdb_providers(a, today, "{}")
    assert repo.films_for_provider_refresh() == [(a, "11", False)]
    assert repo.films_for_provider_refresh(skip_checked_on=today) == []


# ---- Phase 5: metacritic mode-b promotion primitives ----------------------


def test_create_film_inserts_with_guid_and_never_updates(repo):
    fid = repo.create_film(Film("Fresh Find", 2020, None, ""))
    assert fid is not None
    # Same key again: no insert, no update, None back.
    assert repo.create_film(Film("Fresh Find", 2020, "Someone", "")) is None
    import sqlite3

    conn = sqlite3.connect(repo.db_path)
    row = conn.execute("SELECT guid, director FROM films WHERE id = ?", (fid,)).fetchone()
    conn.close()
    assert row[0] and row[1] is None  # guid assigned; director untouched by the second call


def test_claimed_values_lists_an_authoritys_ids(repo):
    fid = repo.create_film(Film("Fresh Find", 2020, None, ""))
    repo.set_external_id(fid, "metacritic", "fresh-find", date(2026, 8, 19))
    assert repo.claimed_values("metacritic") == {"fresh-find"}
    assert repo.claimed_values("tmdb") == set()


def test_append_reviews_adds_without_deleting(repo):
    day = date(2026, 8, 19)
    repo.replace_unresolved_reviews("metacritic", [ReviewEntry("ambiguous-title", value="a")], day)
    repo.append_reviews("metacritic", [ReviewEntry("key-conflict", value="b")], day)
    reasons = {r["reason"] for r in repo.open_reviews("metacritic")}
    assert reasons == {"ambiguous-title", "key-conflict"}


def test_top_staged_titles_bounds_by_rank(repo):
    day = date(2026, 8, 19)
    repo.upsert_mc_titles(
        [
            McTitle("first", "First", 2020, 99, 1, 1),
            McTitle("second", "Second", 2021, 98, 2, 1),
            McTitle("third", "Third", 2022, 97, 3, 1),
        ],
        day,
    )
    assert [t.slug for t in repo.top_staged_titles(2)] == ["first", "second"]
    assert repo.staged_title_count() == 3


def test_list_views_includes_discovery_films_and_keeps_criterion_parity(repo):
    day = date(2026, 8, 19)
    # Criterion: Alpha current; Bravo departed-unrated (hidden); Echo departed-rated (shown).
    repo.record_catalog("criterion", [Film("Alpha", 1950, "Ann", "https://c/alpha"),
                                      Film("Bravo", 1960, "Bob", "https://c/bravo"),
                                      Film("Echo", 1990, "Eve", "https://c/echo")], date(2026, 1, 1))
    repo.record_catalog("criterion", [Film("Alpha", 1950, "Ann", "https://c/alpha")], day)
    repo.set_rating(repo.film_id_by_key("echo (1990)"), 8, day)
    # Discovery: Golf, no criterion listing, scraped metascore 88.
    gid = repo.create_film(Film("Golf", 2020, None, ""))
    repo.set_external_id(gid, "metacritic", "golf-2020", day)
    repo.upsert_mc_titles([McTitle("golf-2020", "Golf", 2020, 88, 1, 1)], day)

    views = {v.title: v for v in repo.list_views("criterion", day)}
    assert set(views) == {"Alpha", "Echo", "Golf"}  # Bravo (departed, unrated) stays hidden
    assert views["Alpha"].criterion is True and views["Alpha"].departed is False
    assert views["Echo"].criterion is True and views["Echo"].departed is True
    golf = views["Golf"]
    assert golf.criterion is False and golf.url is None and golf.departed is False
    assert golf.metacritic == 88 and golf.metacritic_url == "https://www.metacritic.com/movie/golf-2020/"
    assert repo.get_view(gid, day).title == "Golf"

    s = repo.summary("criterion")
    assert s["films"] == 2 and s["discovery"] == 1


def test_director_falls_back_to_omdb_payload(repo):
    day = date(2026, 8, 19)
    # Criterion's director always wins over OMDb's, even when both are present.
    repo.record_catalog("criterion", [Film("Alpha", 1950, "Ann", "https://c/alpha")], day)
    aid = repo.film_id_by_key("alpha (1950)")
    repo.upsert_omdb(aid, OmdbRating(8.0, 90, True, "English", '{"Director":"Somebody Else"}'), day)
    # Discovery films have no collected director; the OMDb payload fills the view.
    gid = repo.create_film(Film("Golf", 2020, None, ""))
    repo.upsert_omdb(gid, OmdbRating(7.0, None, True, "English", '{"Director":"Alfred Hitchcock"}'), day)
    # OMDb's "N/A" placeholder must stay blank, not display literally.
    hid = repo.create_film(Film("Hotel", 2021, None, ""))
    repo.upsert_omdb(hid, OmdbRating(None, None, True, "English", '{"Director":"N/A"}'), day)

    views = {v.title: v for v in repo.list_views("criterion", day)}
    assert views["Alpha"].director == "Ann"
    assert views["Golf"].director == "Alfred Hitchcock"
    assert views["Hotel"].director is None


def test_mark_owned_is_idempotent_and_views_expose_it(repo):
    day = date(2026, 8, 19)
    repo.record_catalog("criterion", [Film("Alpha", 1950, "Ann", "https://c/alpha")], day)
    aid = repo.film_id_by_key("alpha (1950)")
    gid = repo.create_film(Film("Golf", 2020, None, ""))

    assert repo.mark_owned(aid, day) is True
    assert repo.mark_owned(aid, day) is False  # second call: already owned, no error
    assert repo.mark_owned(gid, day) is True
    assert repo.owned_film_ids() == {aid, gid}

    views = {v.title: v for v in repo.list_views("criterion", day)}
    assert views["Alpha"].owned is True and views["Golf"].owned is True
    assert repo.get_view(aid, day).owned is True
    # owned counts across all views — the discovery film Golf is included.
    assert repo.summary("criterion")["owned"] == 2


# ---- M3: film_disposition (merge/tombstone) ---------------------------------

D = date(2026, 8, 19)


def _two_films(repo):
    repo.record_catalog("criterion", [Film("Alpha", 1950, "Ann", "https://c/alpha")], D)
    a = repo.film_id_by_key("alpha (1950)")
    b = repo.create_film(Film("Alpha", 1951, None, ""))  # commerce twin, off-by-one year
    return a, b


def test_merge_moves_every_fk_and_records_disposition(repo):
    a, b = _two_films(repo)
    repo.set_external_id(b, "metacritic", "alpha-slug", D)
    repo.set_external_id(b, "tmdb", "77", D)
    repo.upsert_tmdb(b, found=True, looked_up=D)
    repo.upsert_omdb(b, OmdbRating(7.0, 80, True, "English", '{"Title": "Alpha"}'), D)
    repo.set_rating(b, 8, D)
    repo.toggle_watchlist(b, D)
    repo.mark_owned(b, D)
    repo.record_listing_with_transition(b, "max", "https://m/alpha", D)
    repo.append_reviews("tmdb", [ReviewEntry("id-conflict", film_id=b, value="77")], D)

    report = repo.merge_film(b, a, D, note="twin")

    assert repo.disposition_of(b) == ("merged", a)
    assert repo.canonical_film_id(b) == a and repo.canonical_film_id(a) == a
    assert repo.external_ids_for(a) == {"criterion": "https://c/alpha", "metacritic": "alpha-slug", "tmdb": "77"}
    assert repo.external_ids_for(b) == {}
    assert a in repo.owned_film_ids() and a in repo.watchlist_film_ids()
    assert repo.all_my_ratings() == {"alpha (1950)": 8}
    assert repo.get_payload(a) == '{"Title": "Alpha"}'
    assert [t for t in repo.films_for_provider_refresh() if t[0] == a] == [(a, "77", True)]
    assert report.moved["listings"] == 1 and report.reviews_resolved == 1
    assert repo.open_reviews("tmdb") == []
    with sqlite3.connect(repo.db_path) as c:
        # record_catalog's baseline criterion walk already fired one transition for `a`
        # before the merge; merge_film re-points b's `max` transition onto a rather than
        # collapsing history, so both rows land on the survivor.
        rows = c.execute("SELECT film_id FROM availability_transitions").fetchall()
        assert {r[0] for r in rows} == {a} and len(rows) == 2
        assert c.execute("SELECT COUNT(*) FROM films").fetchone()[0] == 2  # loser row kept


def test_merge_resolves_survivor_reviews_that_name_the_loser(repo):
    a, b = _two_films(repo)
    repo.append_reviews(
        "tmdb",
        [
            ReviewEntry("id-conflict", film_id=a, value=str(b)),  # names the loser → resolved
            ReviewEntry("no-match", film_id=a, value=None),  # unrelated → stays open
        ],
        D,
    )

    report = repo.merge_film(b, a, D)

    assert report.reviews_resolved == 1
    assert [(r["film_id"], r["reason"]) for r in repo.open_reviews("tmdb")] == [(a, "no-match")]
    with sqlite3.connect(repo.db_path) as c:
        detail = c.execute("SELECT detail FROM match_review WHERE reason = 'id-conflict'").fetchone()[0]
    assert f"counterpart film {b} merged into this film" in detail


def test_merge_keeps_survivor_rows_on_conflict_and_notes_dropped(repo):
    a, b = _two_films(repo)
    repo.set_external_id(a, "tmdb", "1", D)
    repo.set_external_id(b, "tmdb", "2", D)
    repo.set_rating(a, 9, D)
    repo.set_rating(b, 3, D)
    report = repo.merge_film(b, a, D)
    assert repo.external_ids_for(a)["tmdb"] == "1"
    assert repo.all_my_ratings() == {"alpha (1950)": 9}
    assert report.dropped == {"external_ids": 1, "my_ratings": 1}
    with sqlite3.connect(repo.db_path) as c:
        c.row_factory = sqlite3.Row
        note = c.execute("SELECT note FROM film_disposition WHERE film_id = ?", (b,)).fetchone()["note"]
    dropped = json.loads(note)["dropped"]
    assert dropped["my_ratings"]["score"] == 3
    assert dropped["my_ratings"]["rated_at"] == D.isoformat()


def test_merge_listing_conflict_widens_seen_window(repo):
    a, b = _two_films(repo)
    repo.record_listing(a, "max", "https://m/a", date(2026, 8, 10))
    repo.record_listing(b, "max", "https://m/b", date(2026, 8, 1))
    repo.record_listing(b, "max", "https://m/b", date(2026, 8, 19))
    repo.merge_film(b, a, D)
    with sqlite3.connect(repo.db_path) as c:
        row = c.execute(
            "SELECT first_seen, last_seen, url FROM listings WHERE film_id = ? AND source='max'", (a,)
        ).fetchone()
    assert row == ("2026-08-01", "2026-08-19", "https://m/a")


def test_merge_rejects_self_disposed_and_unknown(repo):
    a, b = _two_films(repo)
    with pytest.raises(ValueError):
        repo.merge_film(a, a, D)
    with pytest.raises(ValueError):
        repo.merge_film(999, a, D)
    repo.tombstone_film(b, D, note="junk")
    assert repo.disposition_of(b) == ("tombstoned", None)
    assert repo.tombstoned_keys() == {"alpha (1951)"}
    assert repo.disposed_film_ids() == {b}
    with pytest.raises(ValueError):
        repo.merge_film(b, a, D)
    with pytest.raises(ValueError):
        repo.merge_film(a, b, D)


def test_tombstoning_a_flagged_film_clears_the_revisit_flag_and_worklist(repo):
    a, b = _two_films(repo)
    repo.toggle_revisit(b, D, note="wrong film")
    assert [r[0] for r in repo.revisits()] == [b]
    repo.tombstone_film(b, D, note="junk")
    assert repo.revisits() == []
    with sqlite3.connect(repo.db_path) as c:
        assert c.execute("SELECT 1 FROM needs_revisit WHERE film_id = ?", (b,)).fetchone() is None


def test_films_needing_tmdb_match_flags_commerce(repo):
    a = repo.upsert_film(Film("Trio", 1950, None, "https://c/trio"))
    repo.record_listing(a, "criterion", "https://c/trio", date(2026, 8, 24))
    b = repo.upsert_film(Film("Stop Making Sense", 2023, None, "https://mc/sms"))
    targets = {t.film_id: t for t in repo.films_needing_tmdb_match()}
    assert targets[a].commerce is False
    assert targets[b].commerce is True


def test_update_film_year_recomputes_key(repo):
    fid = repo.upsert_film(Film("Stop Making Sense", 2023, None, "u"))
    assert repo.update_film_year(fid, 1984) is None
    assert repo.film_id_by_key("stop making sense (1984)") == fid
    assert repo.film_id_by_key("stop making sense (2023)") is None


def test_update_film_year_collision_returns_twin_and_writes_nothing(repo):
    orig = repo.upsert_film(Film("Nosferatu", 1922, None, "u1"))
    twin = repo.upsert_film(Film("Nosferatu", 1979, None, "u2"))
    assert repo.update_film_year(twin, 1922) == orig
    assert repo.film_id_by_key("nosferatu (1979)") == twin  # untouched


def test_update_film_year_ignores_merged_away_key_holder(repo):
    """A merge must not block its own survivor from adopting the loser's year.

    The loser's films row is deliberately never deleted, so it keeps its key.
    That key is not a live identity: it is retired in place and the survivor
    takes it.
    """
    d = date(2026, 8, 24)
    a = repo.upsert_film(Film("Alpha", 1950, None, "u1"))
    b = repo.upsert_film(Film("Alpha", 1951, None, "u2"))
    repo.merge_film(b, a, d)

    assert repo.update_film_year(a, 1951) is None
    assert repo.film_id_by_key("alpha (1951)") == a
    assert repo.film_id_by_key(f"alpha (1951) #{b}") == b  # loser's key retired, not deleted
    assert repo.disposition_of(b) == ("merged", a)


def test_update_film_year_merged_key_of_another_survivor_blocks(repo):
    """Only THIS film's own loser may have its key retired.

    C (Alpha 1970) was merged into D. An unrelated commerce film A (Alpha 1971)
    must not steal 'alpha (1970)': that key belongs to D's identity now, so the
    clash is reported under D and a durable year-collision review follows.
    """
    d = date(2026, 8, 24)
    c_id = repo.upsert_film(Film("Alpha", 1970, None, "u1"))
    d_id = repo.upsert_film(Film("Delta", 1980, None, "u2"))
    repo.merge_film(c_id, d_id, d)
    a_id = repo.upsert_film(Film("Alpha", 1971, None, "u3"))

    assert repo.update_film_year(a_id, 1970) == d_id
    assert repo.film_id_by_key("alpha (1971)") == a_id  # untouched
    assert repo.film_id_by_key("alpha (1970)") == c_id  # loser's key untouched


def test_update_film_year_collision_with_live_film_writes_nothing(repo):
    a = repo.upsert_film(Film("Alpha", 1950, None, "u1"))
    b = repo.upsert_film(Film("Alpha", 1951, None, "u2"))

    assert repo.update_film_year(a, 1951) == b
    assert repo.film_id_by_key("alpha (1950)") == a  # untouched
    assert repo.film_id_by_key("alpha (1951)") == b


def test_update_film_year_tombstoned_key_holder_still_blocks(repo):
    """A tombstone's key IS the re-creation guard (tombstoned_keys) — never hand it away."""
    d = date(2026, 8, 24)
    a = repo.upsert_film(Film("Alpha", 1950, None, "u1"))
    b = repo.upsert_film(Film("Alpha", 1951, None, "u2"))
    repo.tombstone_film(b, d)

    assert repo.update_film_year(a, 1951) == b
    assert repo.film_id_by_key("alpha (1950)") == a  # untouched
    assert repo.tombstoned_keys() == {"alpha (1951)"}


def test_replace_unresolved_reviews_reason_scope(repo):
    d = date(2026, 8, 24)
    a = repo.upsert_film(Film("Trio", 1950, None, "u1"))
    b = repo.upsert_film(Film("Stop Making Sense", 2023, None, "u2"))
    repo.append_reviews("tmdb", [ReviewEntry("year-collision", film_id=a)], d)
    repo.replace_unresolved_reviews("tmdb", [ReviewEntry("no-match", film_id=b)], d, reason="no-match")
    reasons = sorted(r["reason"] for r in repo.open_reviews("tmdb"))
    assert reasons == ["no-match", "year-collision"]


def test_commerce_films_with_tmdb_excludes_criterion(repo):
    d = date(2026, 8, 24)
    a = repo.upsert_film(Film("Trio", 1950, None, "u1"))
    repo.record_listing(a, "criterion", "u1", d)
    repo.set_external_id(a, "tmdb", "11", d)
    b = repo.upsert_film(Film("Stop Making Sense", 2023, None, "u2"))
    repo.set_external_id(b, "tmdb", "606", d)
    assert repo.commerce_films_with_tmdb() == [(b, "Stop Making Sense", 2023, "606")]
    assert repo.film_id_for_external("tmdb", "606") == b
    assert repo.film_id_for_external("tmdb", "999") is None


def test_update_film_year_unknown_id_raises(repo):
    import pytest

    with pytest.raises(LookupError):
        repo.update_film_year(999, 1950)


def test_stale_omdb_years_excludes_non_numeric_payload_year(repo):
    d = date(2026, 8, 24)
    na = repo.upsert_film(Film("Nine A", 1951, None, "u1"))
    repo.upsert_omdb(na, OmdbRating(None, None, False, None, json.dumps({"Year": "N/A"})), d)
    stale = repo.upsert_film(Film("Stale One", 1951, None, "u2"))
    repo.upsert_omdb(stale, OmdbRating(6.0, 50, True, "English", json.dumps({"Year": "1953"})), d)
    ids = {row[0] for row in repo.stale_omdb_years()}
    assert na not in ids
    assert stale in ids


def test_tmdb_facts_needed_and_upsert(repo):
    from datetime import date

    from movie_brain.domain.models import Film
    from movie_brain.infrastructure.database import TmdbFactsRow

    d = date(2026, 8, 24)
    a = repo.create_film(Film("Alpha", 1950, None, ""))
    b = repo.create_film(Film("Bravo", 1960, None, ""))
    repo.set_external_id(a, "tmdb", "11", d)
    repo.set_external_id(b, "tmdb", "12", d)
    assert repo.tmdb_facts_needed() == [(a, 11), (b, 12)]

    repo.upsert_tmdb_facts(a, TmdbFactsRow(11, "tt0000011", "Alpha", "Alpha", ("Alfa",), 1950, 90), d)
    assert repo.tmdb_facts_needed() == [(b, 12)]

    # link changed → stale row must be refetched
    repo.set_external_id(a, "tmdb", "99", d)
    assert repo.tmdb_facts_needed() == [(a, 99), (b, 12)]
