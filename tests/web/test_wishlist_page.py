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
    expect(body.locator("p.links .wish-done")).to_have_text("♥ Wishlisted")
    expect(body.locator("p.links button.wish-button")).to_have_count(0)
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
    expect(body.locator("p.links .wish-done")).to_have_text("♥ Wishlisted")
    expect(body.locator("p.links button.wish-button")).to_have_count(0)


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


def test_only_wishlisted_rows_carry_anything_new(dash: Page):
    # Echo is seeded; Charlie joins it only if the click test already ran in this session — so
    # every hearted row must be one of the two, and Echo must always be among them.
    hearted_rows = dash.locator("#films tbody .icon-wish").locator("xpath=ancestor::tr[1]")
    texts = hearted_rows.all_text_contents()
    assert texts and all(("Echo" in t) or ("Charlie" in t) for t in texts)
    assert any("Echo" in t for t in texts)
    expect(_row(dash, "Bravo").locator(".icon-wish")).to_have_count(0)
