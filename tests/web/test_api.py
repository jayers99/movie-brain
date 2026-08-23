from datetime import date

import pytest

from movie_brain.domain.models import Film, OmdbRating
from movie_brain.web.app import create_app

D = date(2026, 8, 19)


@pytest.fixture
def client(repo):
    films = [Film("Trio", 1950, "Ken", "https://c/trio"), Film("Quartet", 1948, None, "https://c/quartet")]
    repo.record_catalog("criterion", films, D)
    a = repo.film_id_by_key("trio (1950)")
    repo.upsert_omdb(
        a, OmdbRating(7.5, 91, True, "English", '{"Title": "Trio", "Plot": "Three tales."}', metacritic=88), D
    )
    app = create_app(repo, today=lambda: D)
    app.testing = True
    return app.test_client()


def test_index_serves_html(client):
    r = client.get("/")
    assert r.status_code == 200 and b"<table" in r.data


def test_list_films(client):
    r = client.get("/api/films")
    assert r.status_code == 200
    rows = r.get_json()
    assert {x["title"] for x in rows} == {"Trio", "Quartet"}
    trio = next(x for x in rows if x["title"] == "Trio")
    assert trio["imdb"] == 7.5 and trio["metacritic"] == 88 and trio["pending"] is False
    assert trio["my_rating"] is None
    assert "payload" not in trio


def test_detail_includes_parsed_payload(client):
    fid = client.get("/api/films").get_json()[0]["id"]
    r = client.get(f"/api/films/{fid}")
    assert r.status_code == 200
    body = r.get_json()
    assert body["title"] == "Trio" and body["payload"]["Plot"] == "Three tales."
    assert client.get("/api/films/999").status_code == 404


def test_detail_without_payload_is_null(client):
    fid = next(x["id"] for x in client.get("/api/films").get_json() if x["title"] == "Quartet")
    assert client.get(f"/api/films/{fid}").get_json()["payload"] is None


def test_rate_and_unrate(client):
    fid = client.get("/api/films").get_json()[0]["id"]
    r = client.put(f"/api/films/{fid}/rating", json={"score": 8})
    assert r.status_code == 200 and r.get_json()["my_rating"] == 8
    assert client.get("/api/summary").get_json()["mine"] == 1
    r = client.put(f"/api/films/{fid}/rating", json={"score": None})
    assert r.status_code == 200 and r.get_json()["my_rating"] is None


@pytest.mark.parametrize("body", [{"score": 11}, {"score": -1}, {"score": "7"}, {"score": 7.5}, {}, None])
def test_rate_rejects_bad_input(client, body):
    fid = client.get("/api/films").get_json()[0]["id"]
    r = (
        client.put(f"/api/films/{fid}/rating", json=body)
        if body is not None
        else client.put(f"/api/films/{fid}/rating", data="nope")
    )
    assert r.status_code == 400 and "error" in r.get_json()


def test_rate_unknown_film_404(client):
    assert client.put("/api/films/999/rating", json={"score": 5}).status_code == 404


def test_summary_and_config(client):
    assert client.get("/api/summary").get_json() == {
        "films": 2,
        "rated": 1,
        "pending": 1,
        "unmatched": 0,
        "leaving": 0,
        "mine": 0,
        "departed": 0,
    }
    cfg = client.get("/api/config").get_json()
    assert cfg["canned_thresholds"] == {
        "top_mc": 90,
        "top_rt": 90,
        "top_imdb": 7.5,
        "recent_days": 30,
        "new_arrival_days": 14,
    }
    assert cfg["today"] == "2026-08-19" and "leaving" in cfg["chips"]


def test_scraped_metascore_is_authoritative_with_omdb_fallback(tmp_path):
    from datetime import date

    from movie_brain.domain.models import Film, McTitle, OmdbRating
    from movie_brain.infrastructure.database import Repository
    from movie_brain.web.app import create_app

    day = date(2026, 8, 19)
    repo = Repository(tmp_path / "t.db")
    repo.record_catalog(
        "criterion",
        [Film("Linked", 1950, "Ann", "https://c/linked"), Film("Fallback", 1960, "Bob", "https://c/fallback")],
        day,
    )
    linked_id = repo.film_id_by_key("linked (1950)")
    fallback_id = repo.film_id_by_key("fallback (1960)")
    repo.upsert_omdb(linked_id, OmdbRating(None, None, True, metacritic=90), day)
    repo.upsert_omdb(fallback_id, OmdbRating(None, None, True, metacritic=70), day)
    repo.upsert_mc_titles([McTitle("linked-1950", "Linked", 1950, 93, 1, 1)], day)
    repo.set_external_id(linked_id, "metacritic", "linked-1950", day)

    films = {f["title"]: f for f in create_app(repo).test_client().get("/api/films").get_json()}
    assert films["Linked"]["metacritic"] == 93  # scraped beats the OMDb relay
    assert films["Linked"]["metacritic_url"] == "https://www.metacritic.com/movie/linked-1950/"
    assert films["Fallback"]["metacritic"] == 70  # OMDb fallback keeps unlinked films scored
    assert films["Fallback"]["metacritic_url"] is None


def test_services_in_payloads(repo):
    films = [Film("Trio", 1950, "Ken", "https://c/trio")]
    repo.record_catalog("criterion", films, D)
    fid = repo.film_id_by_key("trio (1950)")
    for slug in ("max", "mubi", "apple-tv-store"):
        repo.record_listing(fid, slug, "https://tmdb/w/11", D)
    app = create_app(repo, today=lambda: D)
    app.testing = True
    tc = app.test_client()
    expected = [{"name": "HBO Max", "subscribed": True}, {"name": "MUBI", "subscribed": False}]
    assert tc.get(f"/api/films/{fid}").get_json()["services"] == expected  # store row hidden
    assert tc.get("/api/films").get_json()[0]["services"] == expected


def test_stale_service_listing_is_not_current(repo):
    films = [Film("Trio", 1950, "Ken", "https://c/trio"), Film("Quartet", 1948, None, "https://c/quartet")]
    repo.record_catalog("criterion", films, D)
    trio, quartet = repo.film_id_by_key("trio (1950)"), repo.film_id_by_key("quartet (1948)")
    repo.record_listing(trio, "max", "https://tmdb/w/11", date(2026, 1, 1))  # stale
    repo.record_listing(quartet, "max", "https://tmdb/w/22", D)  # current — defines max's frontier
    app = create_app(repo, today=lambda: D)
    app.testing = True
    body = {v["title"]: v["services"] for v in app.test_client().get("/api/films").get_json()}
    assert body["Trio"] == [] and body["Quartet"] == [{"name": "HBO Max", "subscribed": True}]
