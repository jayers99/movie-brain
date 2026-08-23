import sqlite3
from datetime import date

from movie_brain.domain.models import Film, OmdbRating
from movie_brain.infrastructure.database import MIGRATIONS_DIR, Repository, init_db

TRIO = Film("Trio", 1950, "Ken Annakin", "https://c/trio")
QUARTET = Film("Quartet", 1948, "Ken Annakin", "https://c/quartet")
D1, D2 = date(2026, 8, 1), date(2026, 8, 19)


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


def test_unrated_departed_film_is_hidden_but_kept_inside_grace(repo):
    a = repo.upsert_film(TRIO)
    b = repo.upsert_film(QUARTET)
    repo.record_listing(a, "criterion", TRIO.url, date(2026, 8, 16))
    repo.record_listing(b, "criterion", QUARTET.url, D2)
    assert repo.purge_departed("criterion", D2) == 0
    assert [v.title for v in repo.list_views("criterion")] == ["Quartet"]
    assert repo.film_id_by_key("trio (1950)") == a


def test_purge_departed_removes_unrated_films_past_grace(repo):
    a = repo.upsert_film(TRIO)
    b = repo.upsert_film(QUARTET)
    repo.record_listing(a, "criterion", TRIO.url, D1)  # 18 days stale
    repo.record_listing(b, "criterion", QUARTET.url, D2)
    repo.upsert_omdb(a, OmdbRating(7.0, 80, True, "English", "{}"), D1)
    assert repo.purge_departed("criterion", D2) == 1
    assert repo.film_id_by_key("trio (1950)") is None
    assert repo.get_payload(a) is None
    assert [v.title for v in repo.list_views("criterion")] == ["Quartet"]


def test_purge_departed_never_touches_rated_films(repo):
    a = repo.upsert_film(TRIO)
    b = repo.upsert_film(QUARTET)
    repo.record_listing(a, "criterion", TRIO.url, D1)  # 18 days stale but rated
    repo.record_listing(b, "criterion", QUARTET.url, D2)
    repo.set_rating(a, 0, D1)
    assert repo.purge_departed("criterion", D2) == 0
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
