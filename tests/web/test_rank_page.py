from __future__ import annotations

import socket
import threading
import time
from collections.abc import Generator
from datetime import date

import pytest
from playwright.sync_api import Page, expect

from movie_brain.domain.models import Film, OmdbRating
from movie_brain.infrastructure.database import Repository
from movie_brain.web.app import create_app

TODAY = date(2026, 9, 13)
POSTER = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


def seed(repo: Repository) -> None:
    # Five rated owned films, one per tier, plus three unrated: the queue has three candidates.
    for title, score in (("Ten", 10), ("Nine", 9), ("Eight", 8), ("Seven", 7), ("Six", 6)):
        fid = repo.create_film(Film(title, 1950, "Dir", ""))
        repo.mark_owned(fid, TODAY)
        repo.set_rating(fid, score, TODAY)
        repo.upsert_omdb(fid, OmdbRating(7.0, None, True, "English", f'{{"Title":"{title}","Poster":"{POSTER}","Runtime":"90 min","Plot":"Plot of {title}."}}'), TODAY)
    for title in ("Uno", "Dos", "Tres"):
        fid = repo.create_film(Film(title, 1960, "Dir", ""))
        repo.mark_owned(fid, TODAY)


@pytest.fixture(scope="module")
def rank_server(tmp_path_factory: pytest.TempPathFactory) -> Generator[str, None, None]:
    root = tmp_path_factory.mktemp("rank")
    repo = Repository(root / "movie-brain.db")
    seed(repo)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    app = create_app(repo, today=lambda: TODAY, lists_dir=root / "lists")
    threading.Thread(target=lambda: app.run(host="127.0.0.1", port=port, use_reloader=False), daemon=True).start()
    time.sleep(0.5)
    yield f"http://127.0.0.1:{port}"


def test_rank_flow(page: Page, rank_server: str):
    page.goto(rank_server + "/rank")
    page.wait_for_selector('#rank[data-state="setup"]')
    cards = page.locator(".anchor-card")
    expect(cards).to_have_count(5)
    expect(cards.nth(2).locator(".anchor-title")).to_have_text("Eight")
    # Clearing a tier's choice and clicking Start surfaces the guard note — visible even
    # though no session is open yet, so it must live outside the (still-hidden) #progress.
    tier3_select = cards.nth(2).locator("select.anchor-swap")
    eight_value = tier3_select.input_value()
    tier3_select.select_option(value="")
    page.click("#start")
    expect(page.locator("#note")).to_contain_text("Choose an anchor")
    tier3_select.select_option(value=eight_value)
    page.click("#start")
    page.wait_for_selector('#rank[data-state="pair"]')
    expect(page.locator(".side.anchor .title")).to_have_text("Eight")
    expect(page.locator(".side.anchor .prompt")).to_contain_text("Plot of Eight.")
    expect(page.locator(".side.anchor img.poster")).to_have_count(1)
    expect(page.locator(".side.candidate .poster.placeholder")).to_have_count(1)  # unrated seeds have no OMDb row
    first = page.locator(".side.candidate .title").inner_text()
    # Cmd/Ctrl+ArrowLeft is browser back on macOS/Linux, not a verdict — it must be a no-op.
    tally1_before = page.locator('#progress .tally span[data-tier="1"]').inner_text()
    page.keyboard.press("Meta+ArrowLeft")
    page.keyboard.press("Control+ArrowLeft")
    expect(page.locator(".side.candidate .title")).to_have_text(first)
    expect(page.locator('#progress .tally span[data-tier="1"]')).to_have_text(tally1_before)
    # ← ← : better than tier 3, better than tier 2 → tier 1.
    page.keyboard.press("ArrowLeft")
    expect(page.locator(".side.anchor .title")).to_have_text("Nine")
    page.keyboard.press("ArrowLeft")
    expect(page.locator('#progress .tally span[data-tier="1"]')).to_have_text("2")
    expect(page.locator(".side.candidate .title")).not_to_have_text(first)
    expect(page.locator("#remaining")).to_have_text("2")
    # Undo brings the first candidate straight back, mid-search.
    page.keyboard.press("u")
    expect(page.locator(".side.candidate .title")).to_have_text(first)
    expect(page.locator(".side.anchor .title")).to_have_text("Nine")
    page.keyboard.press("ArrowLeft")
    # "Have not seen" on the anchor IS the pass (owner ruling 2026-09-13, overriding D9's
    # mark-then-Pass): one click empties tier 3 and shows its setup card, no Space needed.
    page.click(".side.anchor button.unseen")
    page.wait_for_selector('#rank[data-state="needs_anchor"]')
    expect(page.locator(".anchor-card")).to_have_count(1)
    expect(page.locator(".anchor-card")).to_have_attribute("data-tier", "3")
    page.select_option(".anchor-card select.anchor-swap", label="Dos (1960)")
    page.click("#start")
    page.wait_for_selector('#rank[data-state="pair"]')
    # That pass also deferred the candidate (only the anchor was marked), so the third unrated
    # film comes up now, against the tier-3 slot's new anchor.
    expect(page.locator(".side.anchor .title")).to_have_text("Dos")
    expect(page.locator("#unseen-count")).to_have_text("1")
    # "Have not seen" on the candidate is likewise one click: the film joins the unseen bucket
    # and the next candidate is up, with the plain Pass (a deferral) never touched.
    # It was the last unplaced film, so the session is done.
    page.keyboard.press("1")
    expect(page.locator("#unseen-count")).to_have_text("2")
    page.wait_for_selector('#rank[data-state="done"]')
    # Save, then the dashboard's picker lists it.
    page.fill("#list-name", "Mine")
    page.click("#save")
    expect(page.locator("#note")).to_contain_text("saved")
    page.goto(rank_server + "/")
    page.wait_for_selector("#films tbody[data-count]")
    expect(page.locator("#list-picker option", has_text="Mine (")).to_have_count(1)

    # --- Order tier 1 ------------------------------------------------------------------
    # Tier 1 holds Ten (seed) and `first` (placed above). Switching tabs orders the queue's
    # head for free (O7) and asks the other film against it: "Position 1 of 1".
    page.goto(rank_server + "/rank")
    page.click('.tab[data-mode="order-1"]')
    page.wait_for_selector('#rank[data-state="order"]')
    assert page.url.endswith("#order-1")
    expect(page.locator(".side.anchor .heading")).to_have_text("Position 1 of 1")
    expect(page.locator("#ordered")).to_have_text("1")
    expect(page.locator("#order-remaining")).to_have_text("1")
    expect(page.locator(".side button.unseen")).to_have_count(0)   # no Have-not-seen in order mode
    top = page.locator(".side.candidate .title").inner_text()
    page.keyboard.press("1")   # inert here
    expect(page.locator(".side.candidate .title")).to_have_text(top)
    page.keyboard.press("ArrowLeft")   # candidate better → slot 0
    page.wait_for_selector('#rank[data-state="order_done"]')
    expect(page.locator("#ordered")).to_have_text("2")
    page.keyboard.press("u")
    page.wait_for_selector('#rank[data-state="order"]')
    expect(page.locator(".side.candidate .title")).to_have_text(top)
    page.keyboard.press("ArrowLeft")
    page.wait_for_selector('#rank[data-state="order_done"]')
    page.reload()
    page.wait_for_selector('#rank[data-state="order_done"]')   # the hash keeps the mode
    page.fill("#list-name", "Mine")   # a reload clears the field; keep the same list name
    page.click("#save")
    expect(page.locator("#note")).to_contain_text("saved")
    page.goto(rank_server + "/")
    page.wait_for_selector("#films tbody[data-count]")
    value = page.locator("#list-picker option", has_text="Mine (").get_attribute("value")
    page.select_option("#list-picker", value)
    expect(page.locator("#films tbody tr[data-id]").first).to_contain_text(top)   # bare rank 1 sorts first

    # --- Order tier 2 -------------------------------------------------------------------
    # Nine is alone in tier 2: switching tabs free-inserts it (O7) and there is nothing left
    # to ask, landing straight on order_done.
    page.goto(rank_server + "/rank")
    page.click('.tab[data-mode="order-2"]')
    page.wait_for_selector('#rank[data-state="order"], #rank[data-state="order_done"]')
    expect(page.locator("#ordered")).to_have_text("1")

    # --- Order tier 5 -------------------------------------------------------------------
    # Every tier is orderable (2026-09-15): Six is alone in tier 5, free-inserted like Nine.
    page.click('.tab[data-mode="order-5"]')
    page.wait_for_selector('#rank[data-state="order"], #rank[data-state="order_done"]')
    assert page.url.endswith("#order-5")
    expect(page.locator('.tab[data-mode="order-5"]')).to_have_attribute("aria-current", "true")
    expect(page.locator("#order-tier")).to_have_text("5")
    expect(page.locator("#ordered")).to_have_text("1")

    # A legacy `#order` bookmark reads as tier 1.
    page.goto(rank_server + "/rank#order")
    expect(page.locator('.tab[data-mode="order-1"]')).to_have_attribute("aria-current", "true")


def test_order_tab_with_only_unreadable_logs_left_says_so_instead_of_breaking(page: Page, rank_server: str):
    """When every film still waiting in a tier has a corrupt order log the server answers
    `pair: null, done: false` — unfinished work with nothing to ask. The page must say that,
    not throw on the missing pair and sit on whatever was drawn before."""
    session = {
        "session": {"id": 1}, "placed": 5, "remaining": 0, "unseen": 0, "can_undo": False,
        "tally": {"1": 1, "2": 1, "3": 1, "4": 1, "5": 1}, "needs_anchor": [], "done": True, "pair": None,
    }
    order = {"pair": None, "done": False, "corrupt": [7], "ordered": 3, "remaining": 1, "can_undo": False}
    page.route("**/api/rank/session", lambda r: r.fulfill(json=session))
    page.route("**/api/rank/order?*", lambda r: r.fulfill(json=order))
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(rank_server + "/rank#order-1")
    page.wait_for_selector('#rank[data-state="order_stuck"]')
    expect(page.locator("#order-stuck")).to_be_visible()
    expect(page.locator("#order-stuck")).to_contain_text("1 film")
    expect(page.locator("#order-stuck a")).to_have_attribute("href", "/?film=7")
    expect(page.locator("#pair")).to_be_hidden()
    assert errors == []
