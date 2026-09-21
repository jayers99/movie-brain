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


def test_film_json_carries_best_source(client):
    films = client.get("/api/films").get_json()
    assert "best_source" in films[0]


def test_list_payload_carries_the_watch_url_only_on_best_source(client, repo):
    trio = repo.film_id_by_key("trio (1950)")
    repo.record_listing(trio, "max", "https://tmdb/w/trio", D)
    repo.set_service_search_url("max", "https://play.max.com/search?q={title}")
    # Trio also carries a live Criterion listing; unsubscribe it so Max (subscribed by
    # default) wins the ranking outright rather than tying and taking it on the
    # "Criterion Channel" < "HBO Max" name tiebreak — a ranking question watch.md already
    # settles and this test isn't about.
    repo.set_service_subscribed("criterion", False)
    films = {x["title"]: x for x in client.get("/api/films").get_json()}
    assert films["Trio"]["best_source"]["url"] == "https://play.max.com/search?q=Trio"
    assert all("listing_url" not in s and "search_url" not in s for s in films["Trio"]["services"])


def test_film_json_carries_the_apple_tv_app_link_derived_from_the_itunes_id(client, repo):
    trio = repo.film_id_by_key("trio (1950)")
    repo.set_external_id(trio, "itunes", "284815525", D)
    films = {x["title"]: x for x in client.get("/api/films").get_json()}
    assert films["Trio"]["apple_tv_url"] == "com.apple.tv://itunes.apple.com/us/movie/id284815525"
    # Quartet holds no itunes id — the JS falls back to best_source's url or the tv.apple.com search.
    assert films["Quartet"]["apple_tv_url"] is None


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
        "discovery": 0,
        "owned": 0,
        "credits": 0,
        "embeddings": 0,
        "prose": 0,
        "old_ratings_linked": 0,
        "old_ratings": 0,
        "trailers": 0,
    }
    cfg = client.get("/api/config").get_json()
    assert cfg["canned_thresholds"] == {
        "new_arrival_days": 30,
        "multi_list": 1,
    }
    assert cfg["today"] == "2026-08-19" and "leaving" in cfg["chips"]


def test_config_exposes_multi_list_threshold_and_chip(client):
    cfg = client.get("/api/config").get_json()
    assert cfg["canned_thresholds"]["multi_list"] == 1
    assert "multi_list" in cfg["chips"]


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
    expected = [
        # Both max and apple-tv-store tie on subscribed(True)/quality(1)/has_apple_app(False), so
        # the ORDER BY's now-dropped `kind` key no longer separates them — name decides, and
        # "Apple TV Store (iTunes)" sorts before "HBO Max".
        {"name": "Apple TV Store (iTunes)", "subscribed": True, "kind": "store", "quality": 1, "has_apple_app": False},
        {"name": "HBO Max", "subscribed": True, "kind": "svod", "quality": 1, "has_apple_app": False},
        {"name": "MUBI", "subscribed": False, "kind": "svod", "quality": 1, "has_apple_app": False},
    ]
    assert tc.get(f"/api/films/{fid}").get_json()["services"] == expected  # store rows surfaced with their kind
    assert tc.get("/api/films").get_json()[0]["services"] == expected


def test_lists_in_payloads(repo):
    from movie_brain.domain.models import ListEntry, ListMeta

    films = [Film("Trio", 1950, "Ken", "https://c/trio")]
    repo.record_catalog("criterion", films, D)
    fid = repo.film_id_by_key("trio (1950)")
    meta = ListMeta("cahiers-100", "100 Films for an Ideal Cinematheque", "Cahiers du Cinéma", 2008, None, True)
    repo.upsert_film_list(meta, D)
    repo.upsert_list_entry(meta.slug, ListEntry(3, "Trio", "Ken"))
    repo.link_list_entry(meta.slug, 3, fid)
    app = create_app(repo, today=lambda: D)
    app.testing = True
    tc = app.test_client()
    expected = [
        {"slug": "cahiers-100", "name": "100 Films for an Ideal Cinematheque", "curator": "Cahiers du Cinéma",
         "published": 2008, "ordered": True, "trust": 1, "rank": 3, "rank_label": None, "size": 1}
    ]
    assert tc.get(f"/api/films/{fid}").get_json()["lists"] == expected
    assert tc.get("/api/films").get_json()[0]["lists"] == expected


def test_lists_in_payloads_carries_rank_label(repo):
    from movie_brain.domain.models import ListEntry, ListMeta

    films = [Film("Quartet", 1948, None, "https://c/quartet")]
    repo.record_catalog("criterion", films, D)
    fid = repo.film_id_by_key("quartet (1948)")
    meta = ListMeta("sight-sound-2022", "Sight & Sound 2022", "BFI", 2022, None, True)
    repo.upsert_film_list(meta, D)
    repo.upsert_list_entry(meta.slug, ListEntry(3, "Quartet", None, rank_label="=243"))
    repo.link_list_entry(meta.slug, 3, fid)
    app = create_app(repo, today=lambda: D)
    app.testing = True
    tc = app.test_client()
    lists = tc.get(f"/api/films/{fid}").get_json()["lists"]
    assert lists[0]["rank"] == 3
    assert lists[0]["rank_label"] == "=243"


def test_stale_service_listing_is_not_current(repo):
    films = [Film("Trio", 1950, "Ken", "https://c/trio"), Film("Quartet", 1948, None, "https://c/quartet")]
    repo.record_catalog("criterion", films, D)
    trio, quartet = repo.film_id_by_key("trio (1950)"), repo.film_id_by_key("quartet (1948)")
    repo.record_listing(trio, "max", "https://tmdb/w/11", date(2026, 1, 1))  # stale
    repo.record_listing(quartet, "max", "https://tmdb/w/22", D)  # current — defines max's frontier
    app = create_app(repo, today=lambda: D)
    app.testing = True
    body = {v["title"]: v["services"] for v in app.test_client().get("/api/films").get_json()}
    assert body["Trio"] == [] and body["Quartet"] == [
        {"name": "HBO Max", "subscribed": True, "kind": "svod", "quality": 1, "has_apple_app": False}
    ]


def test_watchlist_toggle_round_trip(client):
    films = client.get("/api/films").get_json()
    fid = films[0]["id"]
    assert client.post(f"/api/films/{fid}/watchlist").get_json() == {"watchlisted": True}
    assert client.get(f"/api/films/{fid}").get_json()["watchlisted"] is True
    assert client.post(f"/api/films/{fid}/watchlist").get_json() == {"watchlisted": False}


def test_watchlist_toggle_unknown_film_404s(client):
    r = client.post("/api/films/999999/watchlist")
    assert r.status_code == 404


def test_films_payload_carries_new_on_and_watchlisted(client):
    film = client.get("/api/films").get_json()[0]
    assert "new_on" in film and "watchlisted" in film


def test_config_carries_new_arrival_days_and_chips(client):
    cfg = client.get("/api/config").get_json()
    assert cfg["canned_thresholds"]["new_arrival_days"] == 30
    assert "criterion_new" in cfg["chips"] and "watchlist" in cfg["chips"]


def test_films_include_discovery_with_null_url(seeded_repo):
    app = create_app(seeded_repo, today=lambda: D)
    app.testing = True
    films = {f["title"]: f for f in app.test_client().get("/api/films").get_json()}
    golf = films["Golf"]
    assert golf["criterion"] is False and golf["url"] is None and golf["metacritic"] == 88
    assert films["Alpha"]["criterion"] is True


def test_films_expose_owned(seeded_repo):
    app = create_app(seeded_repo, today=lambda: D)
    app.testing = True
    films = {f["title"]: f for f in app.test_client().get("/api/films").get_json()}
    assert films["Alpha"]["owned"] is True
    assert films["Bravo"]["owned"] is False


def test_revisit_toggle_and_note(client):
    fid = client.get("/api/films").get_json()[0]["id"]
    r = client.post(f"/api/films/{fid}/revisit", json={"note": "wrong film"})
    assert r.status_code == 200 and r.get_json() == {"needs_revisit": True}
    d = client.get(f"/api/films/{fid}").get_json()
    assert d["needs_revisit"] is True and d["revisit_note"] == "wrong film"
    assert client.put(f"/api/films/{fid}/revisit", json={"note": "year suspect"}).status_code == 200
    assert client.get(f"/api/films/{fid}").get_json()["revisit_note"] == "year suspect"
    assert client.put(f"/api/films/{fid}/revisit", json={}).status_code == 400
    r = client.post(f"/api/films/{fid}/revisit")
    assert r.get_json() == {"needs_revisit": False}
    assert client.put(f"/api/films/{fid}/revisit", json={"note": "too late"}).status_code == 404
    assert client.post("/api/films/999/revisit").status_code == 404


def test_suspect_chip_and_verdict_endpoint(client, repo):
    from movie_brain.domain.audit import AuditFlag

    fid = next(x["id"] for x in client.get("/api/films").get_json() if x["title"] == "Trio")
    repo.replace_audit_flags({fid: [AuditFlag("omdb-title", "OMDb title 'Trio Redux' vs 'Trio'", 2)]}, D)
    trio = client.get(f"/api/films/{fid}").get_json()
    assert trio["audit"] == {"score": 2, "reasons": [{"code": "omdb-title", "detail": "OMDb title 'Trio Redux' vs 'Trio'"}]}

    r = client.post(f"/api/films/{fid}/verdict", json={"verdict": "omdb-wrong", "note": "wrong record"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["verdict"] == "omdb-wrong" and body["reasons"] == "omdb-title" and body["audit"] is not None
    assert client.get(f"/api/films/{fid}").get_json()["verdict"]["note"] == "wrong record"

    r = client.post(f"/api/films/{fid}/verdict", json={"verdict": "fine"})
    assert r.status_code == 200 and r.get_json()["audit"] is None

    assert client.post(f"/api/films/{fid}/verdict", json={"verdict": "meh"}).status_code == 400
    assert client.post(f"/api/films/{fid}/verdict", json={}).status_code == 400
    assert client.post("/api/films/999/verdict", json={"verdict": "fine"}).status_code == 404
    assert len(repo.verdict_history()) == 2  # append-only: nothing overwritten


def _enrich_trio(repo):
    from movie_brain.domain.models import CastRow, CrewRow, TmdbCredits

    trio = repo.film_id_by_key("trio (1950)")
    repo.set_external_id(trio, "tmdb", "3", D)
    repo.write_credits(trio, TmdbCredits(
        tmdb_id=3, imdb_id=None, title="Trio", original_title="Trio", year=1950, runtime_min=None, alt_titles=(),
        overview="Three tales of a private eye.", tagline=None, genres=("Drama",), keywords=("anthology",),
        cast=(CastRow(4110, "Humphrey Bogart", "Philip Marlowe", 0),), crew=(CrewRow(1, "Ken", "Director", "Directing"),),
    ), D)
    return trio


def test_detail_carries_credits_overview_and_the_tmdb_link(client, repo):
    trio = _enrich_trio(repo)
    body = client.get(f"/api/films/{trio}").get_json()
    assert body["overview"] == "Three tales of a private eye."
    assert body["tmdb_url"] == "https://www.themoviedb.org/movie/3"
    assert body["credits"] == {
        "director": "Ken",
        "cast": [{"name": "Humphrey Bogart", "character": "Philip Marlowe"}],
        "writers": [],
    }
    assert "credits" not in client.get("/api/films").get_json()[0]  # detail-only (spec D10)


def test_detail_carries_the_stored_trailers_and_the_list_does_not(client, repo):
    from movie_brain.domain.trailers import APPLE, APPLE_NAME, YOUTUBE, Trailer

    fid = client.get("/api/films").get_json()[0]["id"]
    assert client.get(f"/api/films/{fid}").get_json()["trailers"] == []  # never looked up
    picks = [Trailer(YOUTUBE, "trlr0000001", "Official Trailer"), Trailer(APPLE, "https://video-ssl.itunes.apple.com/x.m4v", APPLE_NAME)]
    repo.write_trailers(fid, 1, "900000001", picks, date(2026, 9, 20))
    assert client.get(f"/api/films/{fid}").get_json()["trailers"] == [t.to_dict() for t in picks]
    assert "trailers" not in client.get("/api/films").get_json()[0]  # detail-only


def test_detail_of_an_unenriched_film_has_null_credits(client):
    fid = next(x["id"] for x in client.get("/api/films").get_json() if x["title"] == "Quartet")
    body = client.get(f"/api/films/{fid}").get_json()
    assert body["credits"] is None and body["overview"] is None and body["tmdb_url"] is None


def test_search_requires_q(client):
    assert client.get("/api/search").status_code == 400
    assert client.get("/api/search?q=%20").status_code == 400


def test_search_field_query_returns_ids_and_correction(client, repo):
    trio = _enrich_trio(repo)
    r = client.get("/api/search?q=actor:%20bogrt")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ids"] == [trio] and body["ranked"] is False and body["total"] == 1
    assert body["corrections"] == [{"field": "actor", "typed": "bogrt", "used": "Humphrey Bogart"}]
    assert body["q"] == "actor: bogrt"


def test_search_freeform_is_ranked_and_reaches_titles_without_credits(client, repo):
    _enrich_trio(repo)
    body = client.get("/api/search?q=quartet").get_json()
    quartet = repo.film_id_by_key("quartet (1948)")
    assert body["ids"] == [quartet] and body["ranked"] is True


@pytest.mark.parametrize("q", ["***", "NOT AND OR", "{}", "^", "%", '""', "plot: (", 'actor: "'])
def test_search_survives_hostile_fts_syntax(client, q):
    assert client.get("/api/search", query_string={"q": q}).status_code == 200


@pytest.fixture
def semantic_client(client, repo, fake_embedder):
    # `client` seeds Trio/Quartet via record_catalog; _enrich_trio only enriches an existing film.
    _enrich_trio(repo)
    from movie_brain.application.embed import embed_films

    embed_films(repo, fake_embedder, D, apply=True, log=lambda _m: None)
    app = create_app(repo, today=lambda: D, embedder=fake_embedder)
    app.testing = True
    return app.test_client()


def test_search_contract_is_unchanged_when_meaning_supplies_the_result(semantic_client, repo):
    # Shape only (parent D13): a field query (unranked, never sent to the model) and a freeform
    # query that re-ranks a lexical hit ("three tales" is Trio's OMDb plot) both return the same keys.
    body = semantic_client.get("/api/search?q=actor:%20bogrt").get_json()
    assert set(body) == {"q", "ids", "ranked", "corrections", "suggestions", "hints", "total"}
    body = semantic_client.get("/api/search?q=three%20tales").get_json()
    assert set(body) == {"q", "ids", "ranked", "corrections", "suggestions", "hints", "total"}
    assert body["ids"] == [repo.film_id_by_key("trio (1950)")] and body["ranked"] is True


def test_search_without_an_embedder_offers_the_install_hint_on_an_empty_freeform_result(client):
    body = client.get("/api/search?q=gumshoe%20sleuth").get_json()
    assert body["ids"] == [] and "semantic search is not installed — uv sync --extra semantic" in body["hints"]


@pytest.fixture
def rank_client(repo, tmp_path):
    ids = {}
    for title, score in (("Ten", 10), ("Nine", 9), ("Eight", 8), ("Seven", 7), ("Six", 6)):
        fid = repo.create_film(Film(title, 1950, "Dir", ""))
        repo.mark_owned(fid, D)
        repo.set_rating(fid, score, D)
        ids[title] = fid
    for title in ("Uno", "Dos"):
        fid = repo.create_film(Film(title, 1960, "Dir", ""))
        repo.mark_owned(fid, D)
        ids[title] = fid
    app = create_app(repo, today=lambda: D, lists_dir=tmp_path / "lists")
    app.testing = True
    return app.test_client(), ids


def _start(client):
    p = client.get("/api/rank/proposal").get_json()["proposal"]
    r = client.post("/api/rank/session", json={"anchors": {t: p[str(t)]["film_id"] for t in range(1, 6)}})
    assert r.status_code == 201, r.get_json()
    return client.get("/api/rank/session").get_json()


def test_rank_page_serves_html(rank_client):
    client, _ = rank_client
    r = client.get("/rank")
    assert r.status_code == 200 and b"rank.js" in r.data


def test_rank_session_is_null_before_start_and_409_on_a_second_start(rank_client):
    client, _ = rank_client
    assert client.get("/api/rank/session").get_json() == {"session": None}
    state = _start(client)
    assert state["pair"]["tier"] == 3 and state["remaining"] == 2 and state["tally"] == {str(t): 1 for t in range(1, 6)}
    p = client.get("/api/rank/proposal").get_json()["proposal"]
    r = client.post("/api/rank/session", json={"anchors": {t: p[str(t)]["film_id"] for t in range(1, 6)}})
    assert r.status_code == 409


def test_rank_verdict_places_and_refuses_stale(rank_client):
    client, _ = rank_client
    state = _start(client)
    cand = state["pair"]["candidate"]["film_id"]
    r = client.post("/api/rank/verdict", json={"film_id": cand, "anchor_tier": 3, "verdict": "better"})
    assert r.status_code == 200 and r.get_json()["pair"]["tier"] == 2
    r = client.post("/api/rank/verdict", json={"film_id": cand, "anchor_tier": 3, "verdict": "better"})
    assert r.status_code == 409
    r = client.post("/api/rank/verdict", json={"film_id": cand, "anchor_tier": 2, "verdict": "same"})
    assert r.status_code == 400
    r = client.post("/api/rank/verdict", json={"film_id": cand, "anchor_tier": 2, "verdict": "better"})
    assert r.get_json()["tally"]["1"] == 2 and r.get_json()["can_undo"] is True
    r = client.post("/api/rank/undo")
    assert r.status_code == 200 and r.get_json()["tally"]["1"] == 1 and r.get_json()["pair"]["candidate"]["film_id"] == cand


def test_rank_pass_anchor_unseen_then_swap_then_save(rank_client, repo):
    client, ids = rank_client
    state = _start(client)
    cand = state["pair"]["candidate"]["film_id"]
    r = client.post("/api/rank/pass", json={"film_id": cand, "candidate_unseen": False, "anchor_unseen": True})
    body = r.get_json()
    assert r.status_code == 200 and body["needs_anchor"] == [3] and body["pair"] is None
    assert ids["Eight"] in repo.unseen_film_ids()
    r = client.put("/api/rank/anchor", json={"tier": 3, "film_id": ids["Ten"]})
    assert r.status_code == 409
    r = client.put("/api/rank/anchor", json={"tier": 3, "film_id": ids["Dos"]})
    assert r.status_code == 200 and r.get_json()["anchors"]["3"]["film_id"] == ids["Dos"]
    r = client.post("/api/rank/save", json={"name": ""})
    assert r.status_code == 200 and r.get_json() == {"slug": "my-owned-tiers", "name": "My Ranking", "entries": 5}
    films = {f["title"]: f for f in client.get("/api/films").get_json()}
    assert films["Ten"]["lists"][0]["slug"] == "my-owned-tiers" and films["Ten"]["lists"][0]["rank_label"] is None


def test_rank_save_refuses_a_file_backed_slug(rank_client, tmp_path):
    client, _ = rank_client
    _start(client)
    (tmp_path / "lists").mkdir()
    (tmp_path / "lists" / "my-owned-tiers.tsv").write_text("# slug: my-owned-tiers\n")
    assert client.post("/api/rank/save", json={}).status_code == 409


def test_rank_routes_404_without_a_session(rank_client):
    client, _ = rank_client
    assert client.post("/api/rank/verdict", json={"film_id": 1, "anchor_tier": 3, "verdict": "better"}).status_code == 404
    assert client.post("/api/rank/undo").status_code == 404
    assert client.post("/api/rank/save", json={}).status_code == 404
    assert client.post("/api/rank/move", json={"film_id": 1, "tier": 2}).status_code == 404
    assert client.post("/api/rank/rerank", json={"film_id": 1}).status_code == 404


def test_unseen_toggle_route(client, repo):
    trio = repo.film_id_by_key("trio (1950)")
    r = client.put(f"/api/films/{trio}/unseen", json={"unseen": True})
    assert r.status_code == 200 and r.get_json() == {"unseen": True}
    assert client.get(f"/api/films/{trio}").get_json()["unseen"] is True
    assert client.put(f"/api/films/{trio}/unseen", json={"unseen": False}).get_json() == {"unseen": False}
    assert client.put(f"/api/films/{trio}/unseen", json={}).status_code == 400
    assert client.put("/api/films/999/unseen", json={"unseen": True}).status_code == 404


@pytest.mark.parametrize(
    "method,url",
    [
        ("post", "/api/rank/session"),
        ("post", "/api/rank/verdict"),
        ("post", "/api/rank/pass"),
        ("put", "/api/rank/anchor"),
        ("post", "/api/rank/save"),
        ("post", "/api/rank/move"),
        ("post", "/api/rank/rerank"),
    ],
)
def test_rank_routes_reject_a_non_object_body(rank_client, method, url):
    client, _ = rank_client
    r = getattr(client, method)(url, json=[1, 2, 3])
    assert r.status_code == 400 and "JSON object" in r.get_json()["error"]


@pytest.mark.parametrize(
    "method,url,body",
    [
        ("post", "/api/rank/verdict", {"film_id": True, "anchor_tier": 3, "verdict": "better"}),
        ("post", "/api/rank/verdict", {"film_id": 1, "anchor_tier": True, "verdict": "better"}),
        ("post", "/api/rank/pass", {"film_id": True}),
        ("put", "/api/rank/anchor", {"tier": True, "film_id": 1}),
        ("post", "/api/rank/move", {"film_id": True, "tier": 2}),
        ("post", "/api/rank/rerank", {"film_id": True}),
        ("post", "/api/rank/order/verdict", {"tier": 1, "film_id": True, "other_film_id": 2, "verdict": "better"}),
        ("post", "/api/rank/order/pass", {"tier": True, "film_id": 1}),
    ],
)
def test_rank_routes_refuse_a_boolean_where_an_id_or_tier_belongs(rank_client, method, url, body):
    """`True` is an `int` to Python, so `isinstance(x, int)` let it through as film 1 / tier 1."""
    client, _ = rank_client
    assert getattr(client, method)(url, json=body).status_code == 400


def test_rank_order_needs_a_session_then_serves_the_first_pair_after_a_tier_1_placement(rank_client):
    client, ids = rank_client
    assert client.get("/api/rank/order?tier=1").status_code == 404
    assert client.get("/api/rank/order?tier=6").status_code == 400
    state = _start(client)
    # Seeds put one film (Ten) in tier 1: ordered free at position 1, nothing to ask.
    o = client.get("/api/rank/order?tier=1").get_json()
    assert (o["tier"], o["ordered"], o["remaining"], o["done"], o["pair"]) == (1, 1, 0, True, None)
    cand = state["pair"]["candidate"]["film_id"]
    client.post("/api/rank/verdict", json={"film_id": cand, "anchor_tier": 3, "verdict": "better"})
    client.post("/api/rank/verdict", json={"film_id": cand, "anchor_tier": 2, "verdict": "better"})
    o = client.get("/api/rank/order?tier=1").get_json()
    assert o["pair"]["candidate"]["film_id"] == cand and o["pair"]["other"]["film_id"] == ids["Ten"]
    assert (o["pair"]["position"], o["pair"]["of"], o["remaining"]) == (1, 1, 1)
    assert client.get("/api/rank/order?tier=6").status_code == 400
    assert client.get("/api/rank/order").status_code == 400


def test_rank_order_verdict_inserts_refuses_stale_and_undo_returns_order_state(rank_client):
    client, ids = rank_client
    state = _start(client)
    cand = state["pair"]["candidate"]["film_id"]
    client.post("/api/rank/verdict", json={"film_id": cand, "anchor_tier": 3, "verdict": "better"})
    client.post("/api/rank/verdict", json={"film_id": cand, "anchor_tier": 2, "verdict": "better"})
    r = client.post(
        "/api/rank/order/verdict", json={"tier": 1, "film_id": cand, "other_film_id": ids["Nine"], "verdict": "better"}
    )
    assert r.status_code == 409
    r = client.post(
        "/api/rank/order/verdict", json={"tier": 1, "film_id": cand, "other_film_id": ids["Ten"], "verdict": "same"}
    )
    assert r.status_code == 400
    r = client.post("/api/rank/order/verdict", json={"film_id": "x"})
    assert r.status_code == 400
    r = client.post(
        "/api/rank/order/verdict", json={"tier": 1, "film_id": cand, "other_film_id": ids["Ten"], "verdict": "better"}
    )
    body = r.get_json()
    assert r.status_code == 200 and body["ordered"] == 2 and body["done"] is True and body["can_undo"] is True
    r = client.post("/api/rank/undo")
    body = r.get_json()
    assert r.status_code == 200 and body["ordered"] == 1 and body["pair"]["candidate"]["film_id"] == cand


def test_rank_order_pass_defers_and_checks_its_shape(rank_client):
    client, ids = rank_client
    state = _start(client)
    cand = state["pair"]["candidate"]["film_id"]
    client.post("/api/rank/verdict", json={"film_id": cand, "anchor_tier": 3, "verdict": "better"})
    client.post("/api/rank/verdict", json={"film_id": cand, "anchor_tier": 2, "verdict": "better"})
    assert client.post("/api/rank/order/pass", json={"nope": 1}).status_code == 400
    assert client.post("/api/rank/order/pass", json={"tier": 1, "film_id": ids["Ten"]}).status_code == 409
    r = client.post("/api/rank/order/pass", json={"tier": 1, "film_id": cand})
    # The deferred film is the only one left, so it comes straight back — but it IS deferred.
    assert r.status_code == 200 and r.get_json()["pair"]["candidate"]["film_id"] == cand
    assert r.get_json()["can_undo"] is True


def test_rank_mark_toggle_route(client, repo):
    trio = repo.film_id_by_key("trio (1950)")
    r = client.put(f"/api/films/{trio}/rank-mark", json={"marked": True})
    assert r.status_code == 200 and r.get_json() == {"marked": True}
    assert client.get(f"/api/films/{trio}").get_json()["rank_marked"] is True
    assert client.put(f"/api/films/{trio}/rank-mark", json={"marked": False}).get_json() == {"marked": False}
    assert client.put(f"/api/films/{trio}/rank-mark", json={}).status_code == 400
    assert client.put("/api/films/999/rank-mark", json={"marked": True}).status_code == 404


def _tier_into_1(client, fid):
    for _ in range(2):
        s = client.get("/api/rank/session").get_json()
        assert s["pair"]["candidate"]["film_id"] == fid
        client.post("/api/rank/verdict", json={"film_id": fid, "anchor_tier": s["pair"]["tier"], "verdict": "better"})


def test_rank_move_route_moves_and_the_detail_route_reports_it(rank_client):
    client, ids = rank_client
    _start(client)
    uno = ids["Uno"]
    _tier_into_1(client, uno)
    assert client.get(f"/api/films/{uno}").get_json()["rank_tier"] == 1
    r = client.post("/api/rank/move", json={"film_id": uno, "tier": 2})
    assert r.status_code == 200, r.get_json()
    assert r.get_json() == {"film_id": uno, "tier": 2, "from_tier": 1, "awaiting_order": True}
    detail = client.get(f"/api/films/{uno}").get_json()
    assert (detail["rank_tier"], detail["rank_how"], detail["awaiting_order"]) == (2, "moved", True)
    assert client.get("/api/rank/session").get_json()["can_undo"] is False   # M6
    # Detail-only (M7): the list payload never carries the three keys.
    row = next(f for f in client.get("/api/films").get_json() if f["id"] == uno)
    assert not {"rank_tier", "rank_how", "awaiting_order"} & row.keys()
    # Tier 2's order was empty, so the first read inserts one of its two films with no click
    # (O7) and asks the other against it; one verdict orders both, and awaiting clears.
    pair = client.get("/api/rank/order?tier=2").get_json()["pair"]
    assert uno in {pair["candidate"]["film_id"], pair["other"]["film_id"]}
    body = {"tier": 2, "film_id": pair["candidate"]["film_id"], "other_film_id": pair["other"]["film_id"], "verdict": "better"}
    assert client.post("/api/rank/order/verdict", json=body).status_code == 200
    assert client.get(f"/api/films/{uno}").get_json()["awaiting_order"] is False


def test_rank_move_route_shape_and_refusals(rank_client):
    client, ids = rank_client
    _start(client)
    r = client.post("/api/rank/move", json={"film_id": "x", "tier": 2})
    assert r.status_code == 400 and '"film_id": int, "tier": int' in r.get_json()["error"]
    assert client.post("/api/rank/move", json={"film_id": ids["Ten"], "tier": 6}).status_code == 400
    r = client.post("/api/rank/move", json={"film_id": 999, "tier": 2})
    assert r.status_code == 409 and "not placed" in r.get_json()["error"]
    r = client.post("/api/rank/move", json={"film_id": ids["Ten"], "tier": 2})   # tier 1's anchor
    assert r.status_code == 409 and "swap the anchor first" in r.get_json()["error"]


def test_film_detail_rank_keys_are_null_without_a_session(client, repo):
    trio = repo.film_id_by_key("trio (1950)")
    d = client.get(f"/api/films/{trio}").get_json()
    assert (d["rank_tier"], d["rank_how"], d["awaiting_order"]) == (None, None, False)


def test_rank_rerank_route_unplaces_marks_and_the_mark_clears_once_served(rank_client):
    client, ids = rank_client
    _start(client)
    uno = ids["Uno"]
    _tier_into_1(client, uno)
    assert client.post("/api/rank/rerank", json={"film_id": "x"}).status_code == 400
    r = client.post("/api/rank/rerank", json={"film_id": uno})
    assert r.status_code == 200 and r.get_json() == {"film_id": uno, "from_tier": 1, "marked": True}
    d = client.get(f"/api/films/{uno}").get_json()
    assert (d["rank_tier"], d["rank_marked"]) == (None, True)
    assert client.get("/api/rank/session").get_json()["can_undo"] is False
    assert client.post("/api/rank/rerank", json={"film_id": uno}).status_code == 409           # not placed now
    assert client.post("/api/rank/rerank", json={"film_id": ids["Ten"]}).status_code == 409    # tier 1's anchor
    # Asked again from scratch, never re-seeded; the mark stays until placed AND ordered.
    _tier_into_1(client, uno)
    d = client.get(f"/api/films/{uno}").get_json()
    assert (d["rank_tier"], d["rank_how"], d["awaiting_order"], d["rank_marked"]) == (1, "compared", True, True)
    pair = client.get("/api/rank/order?tier=1").get_json()["pair"]
    body = {"tier": 1, "film_id": pair["candidate"]["film_id"], "other_film_id": pair["other"]["film_id"], "verdict": "worse"}
    assert client.post("/api/rank/order/verdict", json=body).status_code == 200
    d = client.get(f"/api/films/{uno}").get_json()
    assert (d["awaiting_order"], d["rank_marked"]) == (False, False)


def test_films_payload_carries_the_old_rating(client, repo):
    from movie_brain.domain.models import OldRating

    trio = repo.film_id_by_key("trio (1950)")
    repo.upsert_old_rating("ntc", OldRating(1, "Trio", 1950, 5, "2005-03-02"))
    repo.link_old_rating("ntc", 1, trio, "resolver", D)
    films = {f["title"]: f for f in client.get("/api/films").get_json()}
    assert films["Trio"]["old_rating"] == {"stars": 5, "rented_on": "2005-03-02"}
    assert films["Quartet"]["old_rating"] is None
    assert client.get(f"/api/films/{trio}").get_json()["old_rating"]["stars"] == 5
