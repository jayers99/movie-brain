"""Move on (brief docs/superpowers/briefs/2026-09-24-move-on/brief.md, version 1.0, variant B).

The nine story tests carry the brief's story titles. They run on their OWN 80-film server
(function-scoped, a fresh FakeAccount each: stories 1, 6 and 9 wishlist and un-wishlist for
real against the fake). The brief's real numbers (320 / 4862 / 21) are re-cast on this seed;
the real film names and their real relative order are kept where the seed can hold them.
"""

import socket
import tempfile
import threading
import time
from collections.abc import Generator
from datetime import date
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from movie_brain.application.wishlist import WishlistGateway
from movie_brain.domain.models import Film, ListEntry, ListMeta, OmdbRating
from movie_brain.infrastructure.database import Repository
from movie_brain.web.app import create_app
from web.conftest import DELTA_ITUNES, NOVEMBER_ITUNES, FakeAccount, FakePrices

TODAY = date(2026, 9, 24)
FILLERS = 63  # "Shadow 01" … "Shadow 63": unrated, no store id, Metascores 11–73, so every named film leads

# (title, year, imdb, rt, metacritic, my_rating, store, watchlisted) — the default sort is Metacritic
# desc, then RT, then IMDb, so the tuples below ARE each chip's order.
NAMED = [
    ("Three Colors: Red", 1994, 8.2, 100, 100, None, None, False),   # Unrated by me: 1st
    ("The Leopard", 1963, 7.9, 100, 100, None, None, False),         # Unrated by me: 2nd
    ("Fanny and Alexander", 1982, 8.1, 100, 100, 9, None, True),     # Watchlist: 1st
    ("Tokyo Story", 1953, 8.0, 100, 100, 8, None, True),             # Watchlist: 2nd
    ("The Conformist", 1971, 7.9, 98, 100, 10, None, True),          # Watchlist: 3rd
    ("Army of Shadows", 1969, 8.1, 97, 99, None, "store", False),    # Shop: 1st
    ("Pan's Labyrinth", 2006, 8.2, 95, 98, None, "store", False),    # Shop: 2nd
    ("Summer of Soul", 2021, 8.0, 99, 97, None, "store", False),     # Shop: 3rd
    ("Nashville", 1975, 7.6, 89, 96, None, "store", False),          # Shop: 4th
    ("Aftersun", 2022, 7.6, 95, 95, None, NOVEMBER_ITUNES, False),   # Shop: 5th — its REMOVE fails (FakeAccount)
    ("Seven Chances", 1925, 7.8, 94, 94, 7, None, True),             # Watchlist: 4th
    ("Sherlock Jr.", 1924, 8.2, 87, 93, 8, None, True),              # Watchlist: 5th and last
    ("Do the Right Thing", 1989, 8.0, 93, 90, None, DELTA_ITUNES, False),  # Shop: 6th and last — its ADD fails
    ("The Big Sleep", 1946, 7.9, 96, 86, 8, None, False),            # owned, on the noir list
    ("Out of the Past", 1947, 8.0, 87, 85, None, None, False),       # owned, on the noir list
    ("Pursued", 1947, 7.2, 100, None, None, None, False),            # NOT owned, on the noir list (story 5)
]
SHOP = ["Army of Shadows", "Pan's Labyrinth", "Summer of Soul", "Nashville", "Aftersun", "Do the Right Thing"]
WATCHLIST = ["Fanny and Alexander", "Tokyo Story", "The Conformist", "Seven Chances", "Sherlock Jr."]
NOIR = ["The Big Sleep", "Out of the Past", "Pursued"]


def seed_move_on(repo: Repository, account: FakeAccount) -> dict[str, int]:
    ids: dict[str, int] = {}
    for title, year, imdb, rt, mc, rating, store, watch in NAMED:
        fid = repo.create_film(Film(title, year, "Dir", ""))
        assert fid is not None
        ids[title] = fid
        repo.upsert_omdb(fid, OmdbRating(imdb, rt, True, "English", "{}", metacritic=mc), TODAY)
        if rating is not None:
            repo.set_rating(fid, rating, TODAY)
        if store is not None:
            repo.set_external_id(fid, "itunes", str(910000000 + fid) if store == "store" else store, TODAY)
            repo.record_listing(fid, "apple-tv-store", "https://tmdb/w", TODAY)
        if watch:
            repo.toggle_watchlist(fid, TODAY)
    for n in range(1, FILLERS + 1):
        fid = repo.create_film(Film(f"Shadow {n:02d}", 1930 + n, "Dir", ""))
        assert fid is not None
        repo.upsert_omdb(fid, OmdbRating(6.0, 50, True, "English", "{}", metacritic=10 + n), TODAY)
    # M: on the Criterion Channel AND for sale on Apple — never in the Shop list (story 7).
    repo.record_catalog("criterion", [Film("M", 1931, "Fritz Lang", "https://c/m")], TODAY)
    m = repo.film_id_by_key("m (1931)")
    assert m is not None
    ids["M"] = m
    repo.upsert_omdb(m, OmdbRating(8.3, 100, True, "German", "{}", metacritic=94), TODAY)
    repo.set_external_id(m, "itunes", "920000001", TODAY)
    repo.mark_owned(ids["The Big Sleep"], TODAY)
    repo.mark_owned(ids["Out of the Past"], TODAY)
    # An UNORDERED list, as the real BFI: Film Noir is, so it sorts by Metacritic and Pursued is last.
    repo.upsert_film_list(ListMeta("noir-test", "BFI: Film Noir", None, None, None, False), TODAY)
    for rank, title in enumerate(NOIR, start=1):
        repo.upsert_list_entry("noir-test", ListEntry(rank, title, "Dir"))
        repo.link_list_entry("noir-test", rank, ids[title])
    # The fake account lists November's product by default; Aftersun must start OFF the wishlist.
    account.listed.remove(NOVEMBER_ITUNES)
    account.targets.pop(NOVEMBER_ITUNES, None)
    return ids


@pytest.fixture
def move_on_server() -> Generator[tuple[str, dict[str, int]], None, None]:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    with tempfile.TemporaryDirectory() as tmp:
        repo, account = Repository(Path(tmp) / "move-on-movie-brain.db"), FakeAccount()
        ids = seed_move_on(repo, account)
        app = create_app(repo, today=lambda: TODAY, wishlist=WishlistGateway(FakePrices(), account))
        threading.Thread(target=lambda: app.run(host="127.0.0.1", port=port, use_reloader=False), daemon=True).start()
        time.sleep(0.5)
        yield f"http://127.0.0.1:{port}", ids


@pytest.fixture
def dash(page: Page, move_on_server: tuple[str, dict[str, int]]) -> Page:
    page.set_viewport_size({"width": 1440, "height": 800})
    page.goto(move_on_server[0])
    page.wait_for_selector("#films tbody[data-count]")
    return page


# ---- helpers ----

SHOP_CHIP = '#chips .chip[data-chip="shop"]'
WATCHLIST_CHIP = '#chips .chip[data-chip="watchlist"]'
RATED_CHIP = '#chips .chip[data-group="rated"]'   # one click: Unrated by me; two: Rated by me
OWNED_CHIP = '#chips .chip[data-group="owned"]'   # one click: Owned; two: Not owned; three: off


def titles(page: Page) -> list[str]:
    return [t.strip() for t in page.locator("#films tbody tr[data-id] td.c-title").evaluate_all("els => els.map(e => e.firstChild.textContent)")]


def row(page: Page, title: str):
    return page.locator("#films tbody tr[data-id]").filter(has=page.locator(f'td.c-title:text-is("{title}")'))


def drawer_title(page: Page):
    return page.locator("#drawer h2")


def open_film(page: Page, title: str) -> None:
    row(page, title).locator(".c-year").click()
    expect(drawer_title(page)).to_contain_text(title)


def star(page: Page) -> None:
    page.locator("#drawer .watch-toggle").click()


def rate(page: Page, score: str) -> None:
    box = page.locator("#drawer input.rating")
    box.fill(score)
    box.press("Enter")


def wishlist_it(page: Page) -> None:
    page.locator("#drawer p.links button.wish-button").click()


def undo_line(page: Page):
    return page.locator("#drawer .moved-on")


# ---- the stories (their numbers and titles are the brief's) ----


def test_story_1_i_wishlist_under_shop_and_the_drawer_moves_on(dash: Page):
    dash.click(SHOP_CHIP)
    assert titles(dash) == SHOP
    open_film(dash, "Army of Shadows")
    dash.keyboard.press("ArrowDown")
    expect(drawer_title(dash)).to_contain_text("Pan's Labyrinth")
    wishlist_it(dash)
    expect(drawer_title(dash)).to_contain_text("Summer of Soul")   # the fake answers after a second; then it moves
    expect(row(dash, "Pan's Labyrinth")).to_have_count(0)
    expect(row(dash, "Summer of Soul")).to_have_class("lit edge")
    expect(dash.locator("#count-showing")).to_have_text("Showing 5 of 80")
    dash.keyboard.press("ArrowDown")
    expect(drawer_title(dash)).to_contain_text("Nashville")


def test_story_2_i_rate_under_unrated_and_the_drawer_moves_on(dash: Page):
    dash.click(RATED_CHIP)  # Unrated by me
    assert titles(dash)[:3] == ["Three Colors: Red", "The Leopard", "Army of Shadows"]
    open_film(dash, "Three Colors: Red")
    rate(dash, "9")
    expect(drawer_title(dash)).to_contain_text("The Leopard")
    expect(row(dash, "Three Colors: Red")).to_have_count(0)
    expect(row(dash, "The Leopard")).to_have_class("lit edge")


def test_story_3_i_un_star_under_watchlist_and_the_drawer_moves_on(dash: Page):
    dash.click(WATCHLIST_CHIP)
    assert titles(dash) == WATCHLIST
    open_film(dash, "Tokyo Story")
    star(dash)
    expect(drawer_title(dash)).to_contain_text("The Conformist")
    expect(row(dash, "Tokyo Story")).to_have_count(0)
    expect(row(dash, "The Conformist")).to_have_class("lit edge")
    expect(dash.locator("#count-showing")).to_have_text("Showing 4 of 80")


def test_story_4_the_last_film_in_the_list(dash: Page):
    dash.click(WATCHLIST_CHIP)
    open_film(dash, "Sherlock Jr.")
    star(dash)
    expect(drawer_title(dash)).to_contain_text("Seven Chances")   # nothing slid into its place: the film before
    expect(row(dash, "Sherlock Jr.")).to_have_count(0)
    expect(row(dash, "Seven Chances")).to_have_class("lit edge")


def test_story_7_a_film_that_was_never_in_the_list_stays_put(dash: Page, move_on_server: tuple[str, dict[str, int]]):
    base, ids = move_on_server
    dash.goto(f"{base}/?chips=shop&film={ids['M']}")
    expect(drawer_title(dash)).to_contain_text("M")
    expect(dash.locator("#films tbody tr.lit")).to_have_count(0)
    star(dash)
    expect(dash.locator("#drawer .watch-toggle")).to_have_text("★")
    expect(drawer_title(dash)).to_contain_text("M")                # stays put
    dash.keyboard.press("ArrowDown")
    dash.wait_for_timeout(200)
    expect(drawer_title(dash)).to_contain_text("M")                # the arrows stay quiet


def test_story_8_the_list_runs_out(dash: Page):
    dash.click(WATCHLIST_CHIP)
    dash.fill("#f-title", "sherlock")
    dash.keyboard.press("Tab")  # commits the filter's `change` re-render before the row click, or the
    # mousedown-triggered re-render swaps the row out from under the click (pre-existing, not this feature's)
    expect(dash.locator("#count-showing")).to_have_text("Showing 1 of 80")
    open_film(dash, "Sherlock Jr.")
    star(dash)
    expect(dash.locator("#count-showing")).to_have_text("Showing 0 of 80")
    expect(drawer_title(dash)).to_contain_text("Sherlock Jr.")     # nowhere to move: the drawer stays
    expect(dash.locator("#drawer")).to_be_visible()
    expect(dash.locator("#films tbody tr.lit")).to_have_count(0)
    dash.keyboard.press("ArrowDown")
    dash.wait_for_timeout(200)
    expect(drawer_title(dash)).to_contain_text("Sherlock Jr.")
    star(dash)                                                     # its ★ is right there if I change my mind
    expect(dash.locator("#count-showing")).to_have_text("Showing 1 of 80")
    expect(row(dash, "Sherlock Jr.")).to_have_class("lit edge")


# ---- the brief's defaults ----


def test_a_rating_typed_in_a_row_moves_nothing(dash: Page):
    dash.click(RATED_CHIP)  # Unrated by me
    box = row(dash, "Three Colors: Red").locator("input.rating")
    box.fill("6")
    box.press("Enter")
    expect(row(dash, "Three Colors: Red")).to_have_count(0)
    expect(dash.locator("#drawer")).to_be_hidden()                 # no drawer, so nothing to move
    expect(dash.locator("#films tbody tr.marked")).to_have_count(0)


def test_one_back_closes_the_drawer_after_a_move_on(dash: Page):
    dash.click(WATCHLIST_CHIP)
    open_film(dash, "Tokyo Story")
    star(dash)
    expect(drawer_title(dash)).to_contain_text("The Conformist")
    dash.go_back()
    expect(dash.locator("#drawer")).to_be_hidden()
    assert "film=" not in dash.url


def test_stepping_on_before_the_wishlist_lands_moves_nothing_more(dash: Page):
    dash.click(SHOP_CHIP)
    open_film(dash, "Pan's Labyrinth")
    wishlist_it(dash)
    expect(dash.locator("#drawer p.links button.wish-button")).to_have_text("Reaching CheapCharts…")
    dash.keyboard.press("ArrowDown")
    expect(drawer_title(dash)).to_contain_text("Summer of Soul")
    expect(row(dash, "Pan's Labyrinth")).to_have_count(0)          # the earlier click lands
    expect(drawer_title(dash)).to_contain_text("Summer of Soul")   # the film now open is still in the list
    expect(row(dash, "Summer of Soul")).to_have_class("lit edge")


def test_story_6_i_change_my_mind(dash: Page):
    dash.click(SHOP_CHIP)
    open_film(dash, "Pan's Labyrinth")
    wishlist_it(dash)
    expect(drawer_title(dash)).to_contain_text("Summer of Soul")
    expect(undo_line(dash)).to_have_text("Wishlisted Pan's Labyrinth · Undo")
    undo_line(dash).locator("button.undo").click()
    expect(undo_line(dash).locator("button.undo")).to_have_text("Reaching CheapCharts…")
    expect(drawer_title(dash)).to_contain_text("Pan's Labyrinth")            # back to the film
    expect(row(dash, "Pan's Labyrinth")).to_have_class("lit edge")             # back in its place, white
    assert titles(dash)[1] == "Pan's Labyrinth"
    expect(dash.locator("#drawer p.links button.wish-button")).to_have_text("♡ Wishlist it")
    expect(undo_line(dash)).to_have_count(0)


def test_story_9_i_wishlist_two_in_a_row_and_change_my_mind_about_the_first(dash: Page):
    dash.click(SHOP_CHIP)
    open_film(dash, "Pan's Labyrinth")
    wishlist_it(dash)
    expect(drawer_title(dash)).to_contain_text("Summer of Soul")
    expect(undo_line(dash)).to_have_text("Wishlisted Pan's Labyrinth · Undo")
    wishlist_it(dash)
    expect(drawer_title(dash)).to_contain_text("Nashville")
    expect(undo_line(dash)).to_have_count(1)
    expect(undo_line(dash)).to_have_text("Wishlisted Summer of Soul · Undo")  # Pan's Labyrinth's Undo is gone
    # The way back to Pan's Labyrinth is the chip-off route.
    dash.keyboard.press("Escape")
    expect(dash.locator("#drawer")).to_be_hidden()
    dash.click(SHOP_CHIP)
    open_film(dash, "Pan's Labyrinth")
    expect(dash.locator("#drawer p.links .wish-done")).to_have_text("♥ Wishlisted")


def test_the_line_serves_a_star_and_a_rating_too(dash: Page):
    dash.click(WATCHLIST_CHIP)
    open_film(dash, "Tokyo Story")
    star(dash)
    expect(drawer_title(dash)).to_contain_text("The Conformist")
    expect(undo_line(dash)).to_have_text("Took Tokyo Story off your watchlist · Undo")
    undo_line(dash).locator("button.undo").click()
    expect(drawer_title(dash)).to_contain_text("Tokyo Story")
    expect(row(dash, "Tokyo Story")).to_have_class("lit edge")
    expect(dash.locator("#drawer .watch-toggle")).to_have_text("★")
    dash.keyboard.press("Escape")
    dash.click(WATCHLIST_CHIP)  # off
    dash.click(RATED_CHIP)      # Unrated by me
    open_film(dash, "Three Colors: Red")
    rate(dash, "9")
    expect(drawer_title(dash)).to_contain_text("The Leopard")
    expect(undo_line(dash)).to_have_text("Rated Three Colors: Red 9 · Undo")
    undo_line(dash).locator("button.undo").click()
    expect(drawer_title(dash)).to_contain_text("Three Colors: Red")
    expect(dash.locator("#drawer input.rating")).to_have_value("")


def test_clearing_a_rating_under_rated_by_me_moves_on_and_undo_restores_it(dash: Page):
    dash.click(RATED_CHIP)
    dash.click(RATED_CHIP)  # Rated by me
    assert titles(dash)[:2] == ["Fanny and Alexander", "Tokyo Story"]
    open_film(dash, "Fanny and Alexander")
    rate(dash, "")
    expect(drawer_title(dash)).to_contain_text("Tokyo Story")
    expect(undo_line(dash)).to_have_text("Cleared Fanny and Alexander's rating · Undo")
    undo_line(dash).locator("button.undo").click()
    expect(drawer_title(dash)).to_contain_text("Fanny and Alexander")
    expect(dash.locator("#drawer input.rating")).to_have_value("9")


def test_the_line_lasts_only_until_that_drawer_is_redrawn(dash: Page):
    dash.click(WATCHLIST_CHIP)
    open_film(dash, "Tokyo Story")
    star(dash)
    expect(undo_line(dash)).to_have_count(1)
    dash.keyboard.press("ArrowDown")   # a step redraws: the line is gone
    expect(drawer_title(dash)).to_contain_text("Seven Chances")
    expect(undo_line(dash)).to_have_count(0)
    dash.keyboard.press("ArrowUp")     # …and does not come back
    expect(drawer_title(dash)).to_contain_text("The Conformist")
    expect(undo_line(dash)).to_have_count(0)


def test_undo_landing_after_a_step_brings_the_row_back_but_not_the_drawer(dash: Page):
    dash.click(SHOP_CHIP)
    open_film(dash, "Pan's Labyrinth")
    wishlist_it(dash)
    expect(drawer_title(dash)).to_contain_text("Summer of Soul")
    undo_line(dash).locator("button.undo").click()
    dash.keyboard.press("ArrowDown")   # stepped away while CheapCharts is slow
    expect(drawer_title(dash)).to_contain_text("Nashville")
    expect(row(dash, "Pan's Labyrinth")).to_have_count(1)   # the reverse lands: the row is back…
    expect(drawer_title(dash)).to_contain_text("Nashville")  # …the drawer stays where I am
    expect(row(dash, "Nashville")).to_have_class("lit edge")
    expect(undo_line(dash)).to_have_count(0)


def test_undo_landing_after_a_close_reopens_nothing(dash: Page):
    dash.click(SHOP_CHIP)
    open_film(dash, "Pan's Labyrinth")
    wishlist_it(dash)
    expect(drawer_title(dash)).to_contain_text("Summer of Soul")
    undo_line(dash).locator("button.undo").click()
    dash.keyboard.press("Escape")
    expect(dash.locator("#drawer")).to_be_hidden()
    expect(row(dash, "Pan's Labyrinth")).to_have_count(1)   # the reverse lands
    dash.wait_for_timeout(300)
    expect(dash.locator("#drawer")).to_be_hidden()           # nothing reopens


def test_a_failed_wishlist_undo_keeps_the_words_and_offers_try_again(dash: Page):
    dash.click(SHOP_CHIP)
    open_film(dash, "Aftersun")   # November's product: the fake's REMOVE always fails
    wishlist_it(dash)
    expect(drawer_title(dash)).to_contain_text("Do the Right Thing")
    expect(undo_line(dash)).to_have_text("Wishlisted Aftersun · Undo")
    undo_line(dash).locator("button.undo").click()
    expect(undo_line(dash).locator("button.undo")).to_have_text("Try again")
    expect(undo_line(dash)).to_contain_text("Wishlisted Aftersun")
    expect(undo_line(dash).locator(".wish-failed")).to_have_text("Couldn't reach CheapCharts.")
    expect(row(dash, "Aftersun")).to_have_count(0)                     # still out
    expect(drawer_title(dash)).to_contain_text("Do the Right Thing")   # still here
    undo_line(dash).locator("button.undo").click()                     # Try again repeats the reverse call
    expect(undo_line(dash).locator("button.undo")).to_have_text("Reaching CheapCharts…")
    expect(undo_line(dash).locator("button.undo")).to_have_text("Try again")


def test_undo_is_disabled_while_it_runs(dash: Page):
    dash.click(SHOP_CHIP)
    open_film(dash, "Pan's Labyrinth")
    wishlist_it(dash)
    expect(drawer_title(dash)).to_contain_text("Summer of Soul")
    undo_line(dash).locator("button.undo").click()
    expect(undo_line(dash).locator("button.undo")).to_be_disabled()


def test_a_failed_wishlist_click_moves_nothing(dash: Page):
    dash.click(SHOP_CHIP)
    open_film(dash, "Do the Right Thing")   # Delta's product: the fake's ADD always fails
    wishlist_it(dash)
    expect(dash.locator("#drawer p.links .wish-failed")).to_contain_text("Couldn't reach CheapCharts.")
    expect(drawer_title(dash)).to_contain_text("Do the Right Thing")
    expect(row(dash, "Do the Right Thing")).to_have_class("lit edge")
    expect(undo_line(dash)).to_have_count(0)


def test_story_5_the_awkward_one_re_pinned_a_chip_press_moves_nothing(dash: Page, move_on_server: tuple[str, dict[str, int]]):
    base, _ = move_on_server
    dash.goto(f"{base}/?list=noir-test")
    dash.wait_for_selector("#films tbody[data-count]")
    assert titles(dash) == NOIR                       # unordered list: Metacritic order, Pursued (no score) last
    open_film(dash, "Pursued")
    dash.keyboard.press("Escape")
    expect(row(dash, "Pursued")).to_have_class("marked")
    dash.click(OWNED_CHIP)                            # Owned
    expect(row(dash, "Pursued")).to_have_count(0)
    expect(dash.locator("#films tbody tr.marked")).to_have_count(0)
    expect(dash.locator("#drawer")).to_be_hidden()    # nothing jumps, nothing opens
    dash.click(OWNED_CHIP)                            # Not owned
    dash.click(OWNED_CHIP)                            # round to off
    expect(row(dash, "Pursued")).to_have_class("marked")
    # With the drawer open a chip cannot be pressed at all: the click lands on the grey and closes.
    open_film(dash, "Pursued")
    box = dash.locator(OWNED_CHIP).bounding_box()
    assert box is not None
    dash.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    expect(dash.locator("#drawer")).to_be_hidden()
    expect(dash.locator("#count-showing")).to_have_text("Showing 3 of 80")   # Owned was NOT pressed
    expect(row(dash, "Pursued")).to_have_class("marked")
