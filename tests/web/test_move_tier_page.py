"""Move a film to another tier (spec docs/superpowers/specs/2026-09-14-move-tier-design.md):
the drawer's tier row on the dashboard, and the rank page recovering when the pair it shows
was moved out from under it. Its own module-scoped server: the shared dashboard server holds
no rank session, and the rank-page server's tiers have nothing to order."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Generator
from datetime import date

import pytest
from playwright.sync_api import Page, expect

from movie_brain.domain.models import Film, ListEntry, ListMeta
from movie_brain.infrastructure.database import Repository
from movie_brain.web.app import create_app

TODAY = date(2026, 9, 14)


def seed(repo: Repository) -> dict[str, int]:
    ids = {}
    # Three tens so tier 1's order has a real pair; a second nine so tier 2 holds a non-anchor.
    for title, score in (("Ten", 10), ("Ten-b", 10), ("Ten-c", 10), ("Nine", 9), ("Nine-b", 9), ("Eight", 8), ("Seven", 7), ("Six", 6)):
        fid = repo.create_film(Film(title, 1950, "Dir", ""))
        repo.mark_owned(fid, TODAY)
        repo.set_rating(fid, score, TODAY)
        ids[title] = fid
    fid = repo.create_film(Film("Uno", 1960, "Dir", ""))
    repo.mark_owned(fid, TODAY)
    ids["Uno"] = fid
    return ids


@pytest.fixture(scope="module")
def move_server(tmp_path_factory: pytest.TempPathFactory) -> Generator[tuple[str, dict[str, int]], None, None]:
    root = tmp_path_factory.mktemp("move")
    repo = Repository(root / "movie-brain.db")
    ids = seed(repo)
    app = create_app(repo, today=lambda: TODAY, lists_dir=root / "lists")
    with app.test_client() as c:   # start the session before the server thread: seeds every rated film
        p = c.get("/api/rank/proposal").get_json()["proposal"]
        assert c.post("/api/rank/session", json={"anchors": {t: p[str(t)]["film_id"] for t in range(1, 6)}}).status_code == 201
        assert p["1"]["film_id"] == ids["Ten"] and p["2"]["film_id"] == ids["Nine"]
        assert c.post("/api/rank/save", json={}).status_code == 200   # "My Ranking" (curator "me") exists in the picker
    # A curated list that would lead the picker on BOTH trust and name, so "My Ranking" leading proves the rule.
    canon = ListMeta("aaa-canon", "AAA Canon", "Someone", 2020, None, True)
    repo.upsert_film_list(canon, TODAY)
    repo.set_list_trust("aaa-canon", 9)
    repo.upsert_list_entry("aaa-canon", ListEntry(1, "Ten", "Dir"))
    repo.link_list_entry("aaa-canon", 1, ids["Ten"])
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    threading.Thread(target=lambda: app.run(host="127.0.0.1", port=port, use_reloader=False), daemon=True).start()
    time.sleep(0.5)
    yield f"http://127.0.0.1:{port}", ids


def test_order_pair_recovers_after_its_candidate_is_moved_from_the_drawer(page: Page, move_server):
    url, _ = move_server
    page.goto(url + "/rank#order-1")
    page.wait_for_selector('#rank[data-state="order"]')
    old_title = page.locator(".side.candidate .title").inner_text()
    pair = page.request.get(url + "/api/rank/order?tier=1").json()["pair"]
    assert page.request.post(url + "/api/rank/move", data={"film_id": pair["candidate"]["film_id"], "tier": 3}).ok
    page.click(".side.candidate button.better")   # the pair on screen is stale: 409, then a fresh pair (M10)
    expect(page.locator("#note")).to_contain_text("no longer current")
    expect(page.locator(".side.candidate .title")).not_to_have_text(old_title)
    page.wait_for_selector('#rank[data-state="order"]')


def test_drawer_tier_row_moves_the_film_and_lights_rank_this(page: Page, move_server):
    url, ids = move_server
    # Order tier 2 first (one verdict orders its two films) so Nine-b starts NOT awaiting.
    pair = page.request.get(url + "/api/rank/order?tier=2").json()["pair"]
    body = {"tier": 2, "film_id": pair["candidate"]["film_id"], "other_film_id": pair["other"]["film_id"], "verdict": "better"}
    assert page.request.post(url + "/api/rank/order/verdict", data=body).ok
    page.goto(f"{url}/?film={ids['Nine-b']}")   # boot reopens the drawer on the URL's film
    body = page.locator("#drawer-body")
    expect(body).to_contain_text("Nine-b")
    picks = body.locator("button.tier-pick")
    expect(picks).to_have_count(5)
    expect(picks.nth(1)).to_have_attribute("aria-current", "true")
    rank = body.locator("button.rank-toggle")
    expect(rank).to_have_attribute("aria-pressed", "false")
    expect(rank).to_be_enabled()
    picks.nth(0).click()
    expect(picks.nth(0)).to_have_attribute("aria-current", "true")
    expect(picks.nth(1)).not_to_have_attribute("aria-current", "true")
    expect(rank).to_have_attribute("aria-pressed", "true")
    expect(rank).to_be_disabled()
    expect(rank).to_have_attribute("title", "Waiting for Order tier 1")
    page.reload()
    page.wait_for_selector("#films tbody[data-count]")
    body = page.locator("#drawer-body")
    expect(body).to_contain_text("Nine-b")
    expect(body.locator("button.tier-pick").nth(0)).to_have_attribute("aria-current", "true")
    expect(body.locator("button.rank-toggle")).to_be_disabled()


def test_drawer_tier_row_is_absent_for_an_unplaced_film_and_toasts_on_an_anchor(page: Page, move_server):
    url, ids = move_server
    page.goto(f"{url}/?film={ids['Uno']}")
    body = page.locator("#drawer-body")
    expect(body).to_contain_text("Uno")
    expect(body.locator(".tier-row")).to_have_count(0)
    page.goto(f"{url}/?film={ids['Ten']}")   # tier 1's anchor
    body = page.locator("#drawer-body")
    expect(body).to_contain_text("Ten")
    picks = body.locator("button.tier-pick")
    picks.nth(1).click()
    expect(page.locator("#toast")).to_contain_text("swap the anchor first")
    expect(picks.nth(0)).to_have_attribute("aria-current", "true")
    expect(picks.nth(1)).not_to_have_attribute("aria-current", "true")


def test_list_picker_leads_with_the_owners_own_list(page: Page, move_server):
    url, _ = move_server
    page.goto(url + "/")
    page.wait_for_selector("#films tbody[data-count]")
    labels = page.locator("#list-picker option").all_inner_texts()
    assert labels[:3] == ["— all films —", "My Ranking (8)", "AAA Canon (1)"]


def test_drawer_rank_this_on_a_placed_film_re_ranks_it(page: Page, move_server):
    url, ids = move_server
    # Order tier 1's current candidate through the API so a placed AND ordered non-anchor exists.
    pair = page.request.get(url + "/api/rank/order?tier=1").json()["pair"]
    fid = pair["candidate"]["film_id"]
    body = {"tier": 1, "film_id": fid, "other_film_id": pair["other"]["film_id"], "verdict": "worse"}
    assert page.request.post(url + "/api/rank/order/verdict", data=body).ok
    order = page.request.get(url + "/api/rank/order?tier=1").json()
    assert not page.request.get(f"{url}/api/films/{fid}").json()["awaiting_order"]
    page.goto(f"{url}/?film={fid}")
    body = page.locator("#drawer-body")
    rank = body.locator("button.rank-toggle")
    expect(rank).to_have_attribute("aria-pressed", "false")
    expect(rank).to_have_attribute("title", "Re-rank this film (the ranker asks you again)")
    expect(body.locator(".tier-row")).to_have_count(1)
    rank.click()
    expect(rank).to_have_attribute("aria-pressed", "true")
    expect(body.locator(".tier-row")).to_have_count(0)
    d = page.request.get(f"{url}/api/films/{fid}").json()
    assert d["rank_tier"] is None and d["rank_marked"] is True
    assert order["ordered"] - 1 == page.request.get(url + "/api/rank/order?tier=1").json()["ordered"]
