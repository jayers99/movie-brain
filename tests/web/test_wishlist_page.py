from __future__ import annotations

from decimal import Decimal

from playwright.sync_api import Page, expect

from web.conftest import CHARLIE_ITUNES, FAKE_ACCOUNT

HEART_TIP = "On your CheapCharts wishlist"


def _open(dash: Page, title: str):
    dash.locator("tbody tr", has_text=title).first.click()
    body = dash.locator("#drawer-body")
    expect(body).to_contain_text(title)
    return body


def _row(dash: Page, title: str):
    return dash.locator("#films tbody tr", has_text=title).first


def test_one_click_wishlists_the_film_and_the_heart_arrives_on_its_row(dash: Page):
    expect(_row(dash, "Charlie").locator(".icon-wish")).to_have_count(0)
    body = _open(dash, "Charlie")
    button = body.locator("p.links button.wish-button")
    expect(button).to_have_text("♡ Wishlist it")
    button.click()
    expect(button).to_have_text("Reaching CheapCharts…")
    expect(button).to_be_disabled()
    mark = body.locator("p.links .wish-done")
    expect(mark).to_have_text("♥ Wishlisted")
    expect(body.locator("p.links button.wish-button:not(.wish-done)")).to_have_count(0)
    heart = _row(dash, "Charlie").locator(".icon-wish")
    expect(heart).to_have_text("♥")
    expect(heart).to_have_attribute("title", HEART_TIP)
    assert FAKE_ACCOUNT.targets[CHARLIE_ITUNES] == Decimal("3.99")  # lowest ever 2.99 + $1
    expect(body).not_to_contain_text("3.99")  # no prices on screen, anywhere


def test_a_failed_click_says_so_offers_try_again_and_marks_nothing(dash: Page):
    body = _open(dash, "Delta")
    body.locator("p.links button.wish-button").click()
    failed = body.locator("p.links .wish-failed")
    expect(failed).to_contain_text("Couldn't reach CheapCharts.")
    retry = failed.locator("button.wish-button")
    expect(retry).to_have_text("Try again")
    expect(_row(dash, "Delta").locator(".icon-wish")).to_have_count(0)
    retry.click()  # the same click again: busy, then the same line (Delta's fake never recovers)
    expect(body.locator("p.links button.wish-button").first).to_have_text("Reaching CheapCharts…")
    expect(body).not_to_contain_text("Couldn't reach CheapCharts.")  # busy: the stale failure text is gone
    expect(body.locator("p.links .wish-failed")).to_contain_text("Couldn't reach CheapCharts.")
    expect(_row(dash, "Delta").locator(".icon-wish")).to_have_count(0)


def test_an_already_wishlisted_film_shows_the_mark_where_the_button_was(dash: Page):
    body = _open(dash, "Echo")
    mark = body.locator("p.links button.wish-button.wish-done")
    expect(mark).to_have_text("♥ Wishlisted")
    expect(mark).to_have_attribute("title", "Remove from your CheapCharts wishlist")
    expect(body.locator("p.links button.wish-button:not(.wish-done)")).to_have_count(0)


def test_the_heart_comes_last_after_the_list_count_and_any_other_badge(dash: Page):
    cell = _row(dash, "Echo").locator("td.c-title")
    expect(cell.locator(".badge-lists")).to_have_count(1)
    last = cell.locator("span").last
    expect(last).to_have_class("icon-wish")
    expect(last).to_have_attribute("title", HEART_TIP)


def test_an_owned_film_and_a_film_apple_does_not_sell_get_no_button_and_no_message(dash: Page):
    body = _open(dash, "Alpha")  # owned, holds a store id, not wishlisted: The Big Sleep
    expect(body.locator("p.links .cheapcharts-link")).to_have_count(1)
    expect(body.locator(".wish")).to_have_count(0)
    expect(_row(dash, "Alpha").locator(".icon-wish")).to_have_count(0)
    dash.keyboard.press("Escape")
    body = _open(dash, "Bravo")  # no store id: La Dolce Vita
    expect(body.locator(".wish")).to_have_count(0)
    expect(body).not_to_contain_text("CheapCharts.")  # nothing said


def test_the_wishlisted_mark_is_a_button_and_one_click_takes_the_film_off_again(dash: Page):
    expect(_row(dash, "Kilo").locator(".icon-wish")).to_have_count(1)
    body = _open(dash, "Kilo")
    mark = body.locator("p.links button.wish-button.wish-done")
    expect(mark).to_have_text("♥ Wishlisted")
    expect(mark).to_have_attribute("title", "Remove from your CheapCharts wishlist")
    mark.click()
    busy = body.locator("p.links button.wish-button")
    expect(busy).to_have_text("Reaching CheapCharts…")
    expect(busy).to_be_disabled()
    expect(body.locator("p.links button.wish-button")).to_have_text("♡ Wishlist it")
    expect(_row(dash, "Kilo").locator(".icon-wish")).to_have_count(0)


def test_a_failed_un_wishlist_says_so_and_try_again_retries_the_removal(dash: Page):
    body = _open(dash, "November")
    body.locator("p.links button.wish-done").click()
    failed = body.locator("p.links .wish-failed")
    expect(failed).to_contain_text("Couldn't reach CheapCharts.")
    expect(_row(dash, "November").locator(".icon-wish")).to_have_count(1)  # nothing changed
    with dash.expect_request(lambda r: r.method == "DELETE" and r.url.endswith("/wishlist")):
        failed.locator("button.wish-button").click()  # Try again repeats the REMOVAL, not an add
    expect(body.locator("p.links .wish-failed")).to_contain_text("Couldn't reach CheapCharts.")


def test_only_wishlisted_rows_carry_anything_new(dash: Page):
    # Echo and November are seeded wishlisted and stay that way (brief 1.2: November's removal
    # always fails); Charlie joins them only if the add-click test already ran this session, and
    # Kilo drops out only if the un-wishlist-click test already ran this session — so every
    # hearted row must be one of the four, and Echo/November must always be among them.
    hearted_rows = dash.locator("#films tbody .icon-wish").locator("xpath=ancestor::tr[1]")
    texts = hearted_rows.all_text_contents()
    assert texts and all(any(name in t for name in ("Echo", "Charlie", "Kilo", "November")) for t in texts)
    assert any("Echo" in t for t in texts) and any("November" in t for t in texts)
    expect(_row(dash, "Bravo").locator(".icon-wish")).to_have_count(0)
