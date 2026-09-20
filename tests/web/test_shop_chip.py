"""The Shop chip (brief docs/superpowers/briefs/2026-09-20-shop-chip/brief.md, version 1.0).

The six story tests carry the brief's story titles. They run on their own server: the shared
10-film seed holds no film that matches the chip, and giving one a store id would break its
reachable counts. The brief's real numbers (5,007 / 310 / 109) are re-cast on this seed; the
wishlist is driven by the same fakes as test_wishlist_page.py — no test can reach a real account.
"""

import socket
import tempfile
import threading
import time
from collections.abc import Generator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from movie_brain.application.wishlist import WishlistGateway
from movie_brain.domain.models import Film, ListEntry, ListMeta, OmdbRating
from movie_brain.infrastructure.database import Repository
from movie_brain.web.app import create_app
from web.conftest import FakeAccount, FakePrices

SHOP_TODAY = date(2026, 9, 20)
LEOPARD_ITUNES = "900000001"

# (title, year, metacritic) — the default sort is Metacritic desc, so this IS the list's order.
CANDIDATES = [
    ("Army of Shadows", 1969, 99),
    ("Pan's Labyrinth", 2006, 98),
    ("Summer of Soul", 2021, 97),
    ("Nashville", 1975, 96),
    ("Schindler's List", 1993, 95),  # on Netflix, which is not one of my services
    ("Do the Right Thing", 1989, 93),
    ("The Narrow Margin", 1952, 80),
]
CANON = ["Do the Right Thing", "Nashville", "The Narrow Margin", "M"]  # an ordered list, in this order


def seed_shop(repo: Repository, account: FakeAccount) -> None:
    ids: dict[str, int] = {}

    def film(title: str, year: int, mc: int, store_id: bool = True) -> int:
        fid = repo.create_film(Film(title, year, "Dir", ""))
        assert fid is not None
        repo.upsert_omdb(fid, OmdbRating(7.0, 90, True, "English", "{}", metacritic=mc), SHOP_TODAY)
        if store_id:
            repo.set_external_id(fid, "itunes", str(910000000 + fid), SHOP_TODAY)
            repo.record_listing(fid, "apple-tv-store", "https://tmdb/w", SHOP_TODAY)  # the store row is itself subscribed
        ids[title] = fid
        return fid

    for title, year, mc in CANDIDATES:
        film(title, year, mc)
    repo.record_listing(ids["Schindler's List"], repo.register_provider(8, "Netflix"), "https://tmdb/w", SHOP_TODAY)

    # The films that must NOT be in the list, one per reason.
    repo.record_catalog("criterion", [Film("M", 1931, "Fritz Lang", "https://c/m")], SHOP_TODAY)
    m = repo.film_id_by_key("m (1931)")
    assert m is not None
    ids["M"] = m
    repo.upsert_omdb(m, OmdbRating(8.3, 100, True, "German", "{}", metacritic=94), SHOP_TODAY)
    repo.set_external_id(m, "itunes", "920000001", SHOP_TODAY)  # for sale on Apple, but on the Criterion Channel
    repo.mark_owned(film("The Big Sleep", 1946, 86), SHOP_TODAY)
    repo.set_rating(film("The Long Goodbye", 1973, 87), 7, SHOP_TODAY)
    repo.record_listing(film("Pursued", 1947, 70), "max", "https://tmdb/w", SHOP_TODAY)  # a service I have
    under = film("Under the Skin", 2014, 78, store_id=False)  # TMDB says the store sells it; no store id held
    repo.record_listing(under, "apple-tv-store", "https://tmdb/w", SHOP_TODAY)
    leopard = film("The Leopard", 1963, 100, store_id=False)  # already on my wishlist: decided
    repo.set_external_id(leopard, "itunes", LEOPARD_ITUNES, SHOP_TODAY)
    repo.mark_wishlisted(leopard, SHOP_TODAY)
    account.listed.append(LEOPARD_ITUNES)
    account.targets[LEOPARD_ITUNES] = Decimal("5.99")

    repo.upsert_film_list(ListMeta("canon-test", "Canon Test", None, None, None, True), SHOP_TODAY)
    for rank, title in enumerate(CANON, start=1):
        repo.upsert_list_entry("canon-test", ListEntry(rank, title, "Dir"))
        repo.link_list_entry("canon-test", rank, ids[title])


@pytest.fixture
def shop_server() -> Generator[str, None, None]:
    # Function-scoped with a FRESH FakeAccount: these tests wishlist and un-wishlist for real
    # (against the fake), and the shared FAKE_ACCOUNT singleton is mutated across the session.
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    with tempfile.TemporaryDirectory() as tmp:
        repo, account = Repository(Path(tmp) / "shop-movie-brain.db"), FakeAccount()
        seed_shop(repo, account)
        app = create_app(repo, today=lambda: SHOP_TODAY, wishlist=WishlistGateway(FakePrices(), account))
        threading.Thread(target=lambda: app.run(host="127.0.0.1", port=port, use_reloader=False), daemon=True).start()
        time.sleep(0.5)
        yield f"http://127.0.0.1:{port}"


@pytest.fixture
def shop(page: Page, shop_server: str) -> Page:
    page.set_viewport_size({"width": 1440, "height": 800})
    page.goto(shop_server)
    page.wait_for_selector("#films tbody[data-count]")
    return page


# ---- helpers ----

SHOP_CHIP = '#chips .chip[data-chip="shop"]'


def titles(page: Page) -> list[str]:
    return [t.strip() for t in page.locator("#films tbody tr[data-id] td.c-title").evaluate_all("els => els.map(e => e.firstChild.textContent)")]


def row(page: Page, title: str):
    return page.locator("#films tbody tr[data-id]", has_text=title)


def open_film(page: Page, title: str) -> None:
    row(page, title).locator(".c-year").click()
    expect(page.locator("#drawer h2")).to_contain_text(title)


def wishlist_it(page: Page) -> None:
    page.locator("#drawer p.links button.wish-button").click()
    expect(page.locator("#drawer p.links .wish-done")).to_have_text("♥ Wishlisted")  # the fake takes about a second


# ---- the six stories ----


def test_story_1_one_press_finds_the_films_worth_buying(shop: Page):
    assert len(titles(shop)) == 13
    shop.click(SHOP_CHIP)
    expect(shop.locator(SHOP_CHIP)).to_have_class("chip active")
    expect(shop.locator(SHOP_CHIP)).to_have_text("Shop")
    assert titles(shop) == [t for t, _y, _mc in CANDIDATES]
    expect(shop.locator("#count-showing")).to_have_text("Showing 7 of 13")
    assert "chips=shop" in shop.url
    expect(row(shop, "Army of Shadows").locator(".badge-owned")).to_have_count(0)


def test_story_2_nothing_i_can_already_watch_nothing_i_have_judged(shop: Page):
    shop.click(SHOP_CHIP)
    shown = titles(shop)
    assert "M" not in shown  # for sale on Apple, but on the Criterion Channel
    assert "The Big Sleep" not in shown  # owned
    assert "The Long Goodbye" not in shown  # rated 7
    assert "Schindler's List" in shown  # on Netflix, which is not one of my services
    open_film(shop, "Schindler's List")
    expect(shop.locator("#drawer-body")).to_contain_text("Netflix")


def test_story_3_i_browse_with_the_arrows_and_wishlist_as_i_go(shop: Page):
    shop.click(SHOP_CHIP)
    open_film(shop, "Army of Shadows")
    shop.keyboard.press("ArrowDown")
    expect(shop.locator("#drawer h2")).to_contain_text("Pan's Labyrinth")
    wishlist_it(shop)
    expect(row(shop, "Pan's Labyrinth")).to_have_count(0)  # its row left the list behind the drawer
    expect(shop.locator("#drawer h2")).to_contain_text("Pan's Labyrinth")  # the drawer stays on it
    expect(shop.locator("#count-showing")).to_have_text("Showing 6 of 13")
    shop.keyboard.press("ArrowDown")
    expect(shop.locator("#drawer h2")).to_contain_text("Summer of Soul")  # the film that took its place
    expect(row(shop, "Summer of Soul")).to_have_class("lit edge")


def test_story_4_i_change_my_mind(shop: Page):
    shop.click(SHOP_CHIP)
    open_film(shop, "Pan's Labyrinth")
    wishlist_it(shop)
    expect(row(shop, "Pan's Labyrinth")).to_have_count(0)
    shop.locator("#drawer p.links .wish-done").click()
    expect(shop.locator("#drawer p.links button.wish-button")).to_have_text("♡ Wishlist it")
    expect(row(shop, "Pan's Labyrinth")).to_have_class("lit edge")  # straight back, white
    assert titles(shop)[1] == "Pan's Labyrinth"  # in its old place


def test_story_5_it_stacks_with_my_other_chips(shop: Page):
    shop.click(SHOP_CHIP)
    shop.click('#chips .chip[data-chip="multi_list"]')
    assert titles(shop) == ["Do the Right Thing", "Nashville", "The Narrow Margin"]  # canon score, best first; M is out


def test_story_6_the_awkward_one_a_film_already_on_my_wishlist(shop: Page):
    expect(row(shop, "The Leopard").locator(".icon-wish")).to_have_text("♥")
    shop.click(SHOP_CHIP)
    expect(row(shop, "The Leopard")).to_have_count(0)  # decided — not a candidate


# ---- the defaults the brief names ----


def test_shop_leaves_out_a_service_i_have_and_a_store_listing_without_a_store_id(shop: Page):
    shop.click(SHOP_CHIP)
    shown = titles(shop)
    assert "Pursued" not in shown  # on HBO Max, one of mine
    assert "Under the Skin" not in shown  # TMDB lists the store; movie-brain holds no store id, so no button either


def test_the_chip_sits_after_rewatch_and_clear_resets_it(shop: Page):
    labels = shop.locator("#chips .chip").all_inner_texts()
    assert labels[labels.index("Rewatch") + 1] == "Shop"
    shop.click(SHOP_CHIP)
    shop.click("#chips-clear")
    expect(shop.locator(SHOP_CHIP)).to_have_class("chip")
    assert "chips=" not in shop.url


def test_up_after_the_open_film_left_goes_to_the_film_before_it(shop: Page):
    shop.click(SHOP_CHIP)
    open_film(shop, "Pan's Labyrinth")
    wishlist_it(shop)
    shop.keyboard.press("ArrowUp")
    expect(shop.locator("#drawer h2")).to_contain_text("Army of Shadows")


def test_stepping_on_while_cheapcharts_is_still_answering(shop: Page):
    shop.click(SHOP_CHIP)
    open_film(shop, "Pan's Labyrinth")
    shop.locator("#drawer p.links button.wish-button").click()
    expect(shop.locator("#drawer p.links button.wish-button")).to_have_text("Reaching CheapCharts…")
    shop.keyboard.press("ArrowDown")
    expect(shop.locator("#drawer h2")).to_contain_text("Summer of Soul")
    expect(row(shop, "Pan's Labyrinth")).to_have_count(0)  # the earlier click lands: that film leaves
    expect(shop.locator("#drawer h2")).to_contain_text("Summer of Soul")
    expect(row(shop, "Summer of Soul")).to_have_class("lit edge")  # the white row stays on the film now open
    expect(shop.locator("#drawer p.links button.wish-button")).to_have_text("♡ Wishlist it")  # Summer of Soul's own


def test_the_arrows_carry_on_for_every_chip_not_only_shop(shop: Page):
    shop.click('#chips .chip[data-group="rated"]')  # Unrated by me
    assert titles(shop)[:3] == ["The Leopard", "Army of Shadows", "Pan's Labyrinth"]
    open_film(shop, "Army of Shadows")
    rating = shop.locator("#drawer input.rating")
    rating.fill("8")
    rating.press("Enter")
    expect(row(shop, "Army of Shadows")).to_have_count(0)  # rated: it left the Unrated list
    shop.keyboard.press("ArrowDown")
    expect(shop.locator("#drawer h2")).to_contain_text("Pan's Labyrinth")


def test_a_film_that_was_never_in_the_list_leaves_the_arrows_quiet(shop: Page, shop_server: str):
    fid = row(shop, "The Leopard").get_attribute("data-id")
    shop.goto(f"{shop_server}/?chips=shop&film={fid}")
    expect(shop.locator("#drawer h2")).to_contain_text("The Leopard")
    shop.keyboard.press("ArrowDown")
    shop.wait_for_timeout(200)
    expect(shop.locator("#drawer h2")).to_contain_text("The Leopard")


def test_closing_on_a_film_that_left_the_list_leaves_no_mark(shop: Page):
    shop.click(SHOP_CHIP)
    open_film(shop, "Pan's Labyrinth")
    wishlist_it(shop)
    shop.keyboard.press("Escape")
    expect(shop.locator("#drawer")).to_be_hidden()
    expect(shop.locator("#films tbody tr.marked")).to_have_count(0)  # the mark rides with its film
    shop.click(SHOP_CHIP)  # Shop off: the film is back, and so is its mark
    expect(row(shop, "Pan's Labyrinth")).to_have_class("marked")
