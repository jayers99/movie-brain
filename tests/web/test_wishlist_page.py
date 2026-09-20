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
