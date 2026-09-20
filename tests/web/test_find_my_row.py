"""Find my row (brief docs/superpowers/briefs/2026-09-20-find-my-row/brief.md, version 1.0).

The six story tests carry the brief's story titles. They run on their own 80-film server — the
shared 10-film seed cannot evict a row from the virtual-scrolled DOM, so a mark that survives
scrolling would pass vacuously there.
"""

import socket
import struct
import tempfile
import threading
import time
import zlib
from collections.abc import Generator
from datetime import date
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from movie_brain.domain.models import Film, ListEntry, ListMeta
from movie_brain.infrastructure.database import Repository
from movie_brain.web.app import create_app

NOIR_TODAY = date(2026, 9, 20)
NOIR_SIZE = 80
OOTP_RANK, PURSUED_RANK = 36, 37  # deep enough (index >= 30) to leave the DOM when the list is at its top


def noir_titles() -> list[str]:
    titles = [f"Shadow {n:02d}" for n in range(1, NOIR_SIZE + 1)]
    titles[0] = "M"
    titles[OOTP_RANK - 1] = "Out of the Past"
    titles[PURSUED_RANK - 1] = "Pursued"
    return titles


def seed_noir(repo: Repository) -> None:
    repo.upsert_film_list(ListMeta("noir-test", "BFI: Film Noir", None, None, None, True), NOIR_TODAY)
    for rank, title in enumerate(noir_titles(), start=1):
        fid = repo.create_film(Film(title, 1930 + rank, "Dir", ""))
        assert fid is not None
        repo.upsert_list_entry("noir-test", ListEntry(rank, title, "Dir"))
        repo.link_list_entry("noir-test", rank, fid)
        if title == "Out of the Past":
            repo.mark_owned(fid, NOIR_TODAY)  # Pursued is NOT owned — story 6 turns on it


@pytest.fixture(scope="module")
def noir_server() -> Generator[str, None, None]:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    with tempfile.TemporaryDirectory() as tmp:
        repo = Repository(Path(tmp) / "noir-movie-brain.db")
        seed_noir(repo)
        app = create_app(repo, today=lambda: NOIR_TODAY)
        threading.Thread(target=lambda: app.run(host="127.0.0.1", port=port, use_reloader=False), daemon=True).start()
        time.sleep(0.5)
        yield f"http://127.0.0.1:{port}"


@pytest.fixture
def noir(page: Page, noir_server: str) -> Page:
    page.set_viewport_size({"width": 1440, "height": 800})
    page.goto(f"{noir_server}/?list=noir-test")
    page.wait_for_selector("#films tbody[data-count]")
    return page


# ---- helpers ----


def row(page: Page, title: str):
    return page.locator("#films tbody tr[data-id]").filter(has=page.locator(f'td.c-title:text-is("{title}")'))


def scroll_list(page: Page, top: int) -> None:
    page.evaluate("(t) => { document.querySelector('#table-wrap').scrollTop = t; }", top)
    page.wait_for_timeout(80)  # renderRows runs in a requestAnimationFrame


def show(page: Page, title: str) -> None:
    """Scroll the list so the film's row is comfortably inside the window."""
    index = noir_titles().index(title)
    scroll_list(page, max(0, index * 36 - 200))
    expect(row(page, title)).to_be_visible()


def open_film(page: Page, title: str) -> None:
    show(page, title)
    row(page, title).locator(".c-year").click()
    expect(page.locator("#drawer h2")).to_contain_text(title)


def pixel(png: bytes, x: int, y: int) -> tuple[int, int, int]:
    """One pixel of a Playwright screenshot (8-bit RGB/RGBA PNG) — the suite carries no imaging library."""
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, width, bpp = 8, b"", 0, 0
    while pos < len(png):
        (length,), kind = struct.unpack(">I", png[pos : pos + 4]), png[pos + 4 : pos + 8]
        data = png[pos + 8 : pos + 8 + length]
        if kind == b"IHDR":
            width, _h, depth, colour = struct.unpack(">IIBB", data[:10])
            assert depth == 8 and colour in (2, 6)
            bpp = 3 if colour == 2 else 4
        elif kind == b"IDAT":
            idat += data
        pos += 12 + length
    raw, stride = zlib.decompress(idat), width * bpp
    prev = bytearray(stride)
    for line_no in range(y + 1):
        start = line_no * (stride + 1)
        ftype, line = raw[start], bytearray(raw[start + 1 : start + 1 + stride])
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b, c = prev[i], (prev[i - bpp] if i >= bpp else 0)
            if ftype == 1:
                line[i] = (line[i] + a) & 255
            elif ftype == 2:
                line[i] = (line[i] + b) & 255
            elif ftype == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif ftype == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        prev = line
    return prev[x * bpp], prev[x * bpp + 1], prev[x * bpp + 2]


def row_pixel(page: Page, title: str) -> tuple[int, int, int]:
    """The colour actually PAINTED near the right end of the row's title cell, left of the drawer."""
    box = row(page, title).locator("td.c-title").bounding_box()
    assert box is not None
    x, y = int(box["x"] + box["width"] - 12), int(box["y"] + box["height"] / 2)
    page.mouse.move(0, 0)  # a hovered row paints its hover colour
    assert x < 1440 - 760  # left of the drawer
    return pixel(page.screenshot(), x, y)


# ---- the six stories ----


def test_story_1_i_can_see_my_row_while_the_drawer_is_open(noir: Page):
    open_film(noir, "Out of the Past")
    expect(noir.locator("#films tbody tr.lit")).to_have_count(1)
    expect(row(noir, "Out of the Past")).to_have_class("lit edge")
    assert row_pixel(noir, "Out of the Past") == (255, 255, 255)  # white: lifted above the dim
    dimmed = row_pixel(noir, "Pursued")
    assert max(dimmed) < 200 and len(set(dimmed)) == 1  # its neighbour is grey under the 30% black


def test_story_2_i_can_get_back_to_where_i_was(noir: Page):
    open_film(noir, "Out of the Past")
    noir.keyboard.press("Escape")
    expect(noir.locator("#drawer")).to_be_hidden()
    expect(row(noir, "Out of the Past")).to_have_class("marked")
    expect(noir.locator("#films tbody tr.lit")).to_have_count(0)
    assert row_pixel(noir, "Out of the Past") == (242, 242, 242)  # the chip grey, #f2f2f2
    assert row_pixel(noir, "Pursued") == (255, 255, 255)
    assert "film=" not in noir.url and "mark" not in noir.url  # a bookmark in memory, never in the address


def test_story_3_there_is_one_mark_and_it_moves(noir: Page):
    open_film(noir, "Out of the Past")
    noir.click("#drawer-close")
    open_film(noir, "Pursued")
    noir.click("#drawer-close")
    expect(noir.locator("#films tbody tr.marked")).to_have_count(1)
    expect(row(noir, "Pursued")).to_have_class("marked")
    expect(row(noir, "Out of the Past")).not_to_have_class("marked")


def test_story_4_i_scroll_away_and_come_back(noir: Page):
    open_film(noir, "Out of the Past")
    noir.keyboard.press("Escape")
    scroll_list(noir, 0)
    expect(row(noir, "M")).to_be_visible()
    expect(row(noir, "Out of the Past")).to_have_count(0)  # really evicted from the DOM — not a vacuous pass
    show(noir, "Out of the Past")
    expect(row(noir, "Out of the Past")).to_have_class("marked")


def test_story_5_i_step_through_films_without_closing(noir: Page):
    open_film(noir, "Out of the Past")
    noir.keyboard.press("ArrowDown")
    expect(noir.locator("#drawer h2")).to_contain_text("Pursued")
    expect(row(noir, "Pursued")).to_have_class("lit edge")
    expect(noir.locator("#films tbody tr.lit")).to_have_count(1)
    noir.keyboard.press("ArrowUp")
    expect(noir.locator("#drawer h2")).to_contain_text("Out of the Past")
    expect(row(noir, "Out of the Past")).to_have_class("lit edge")
    expect(noir.locator("#drawer .step-hint")).to_have_text("↑ ↓ previous / next film · T trailer")


def test_story_5_the_list_scrolls_to_keep_the_white_row_in_view(noir: Page):
    open_film(noir, "Out of the Past")
    for _ in range(30):  # far past the bottom of the window
        noir.keyboard.press("ArrowDown")
    title = noir_titles()[OOTP_RANK - 1 + 30]
    expect(noir.locator("#drawer h2")).to_contain_text(title)
    lit = row(noir, title)
    expect(lit).to_have_class("lit edge")
    box, wrap = lit.bounding_box(), noir.locator("#table-wrap").bounding_box()
    assert box is not None and wrap is not None
    assert box["y"] + box["height"] <= wrap["y"] + wrap["height"] + 1  # wholly inside the window
    head = noir.locator("#films thead tr.filters th").first.bounding_box()  # the th is what sticks, not the thead
    assert head is not None and box["y"] >= head["y"] + head["height"] - 1  # and below the sticky header


def test_story_6_the_awkward_one_my_marked_film_leaves_the_list(noir: Page):
    open_film(noir, "Pursued")
    noir.keyboard.press("Escape")
    before = noir.evaluate("document.querySelector('#table-wrap').scrollTop")
    owned = noir.locator('#chips .chip[data-cycle="owned,not_owned"]')
    owned.click()  # Owned: Pursued is not owned and drops out
    expect(row(noir, "Pursued")).to_have_count(0)
    expect(noir.locator("#films tbody tr.marked")).to_have_count(0)
    owned.click()  # Not owned
    owned.click()  # round to off again
    expect(noir.locator("#films tbody tr[data-id]").first).to_be_visible()
    # movie-brain never moved the list; the browser pulled it to the short list's end and leaves it there
    assert noir.evaluate("document.querySelector('#table-wrap').scrollTop") <= before
    show(noir, "Pursued")
    expect(row(noir, "Pursued")).to_have_class("marked")


# ---- the defaults the brief names ----


def test_one_back_closes_the_drawer_however_many_films_were_stepped_through(noir: Page):
    open_film(noir, "Out of the Past")
    for _ in range(3):
        noir.keyboard.press("ArrowDown")
    title = noir_titles()[OOTP_RANK - 1 + 3]
    expect(noir.locator("#drawer h2")).to_contain_text(title)
    fid = row(noir, title).get_attribute("data-id")
    noir.wait_for_function("(id) => new URLSearchParams(location.search).get('film') === id", arg=fid)
    noir.go_back()
    expect(noir.locator("#drawer")).to_be_hidden()
    assert "film=" not in noir.url
    expect(row(noir, title)).to_have_class("marked")  # the mark is on the last film looked at
    noir.go_forward()  # and the entry it replaced names the film that was on screen
    expect(noir.locator("#drawer h2")).to_contain_text(title)


def test_escape_after_stepping_leaves_no_stale_film_entry_behind(noir: Page):
    open_film(noir, "Out of the Past")
    noir.keyboard.press("ArrowDown")
    expect(noir.locator("#drawer h2")).to_contain_text("Pursued")
    noir.keyboard.press("Escape")
    expect(noir.locator("#drawer")).to_be_hidden()
    noir.go_back()  # past the list page entirely, never back into a drawer
    noir.wait_for_timeout(200)
    assert "film=" not in noir.url


def test_arrows_stop_at_the_ends_of_the_list(noir: Page):
    open_film(noir, "M")
    noir.keyboard.press("ArrowUp")
    noir.wait_for_timeout(150)
    expect(noir.locator("#drawer h2")).to_contain_text("M")
    expect(row(noir, "M")).to_have_class("lit edge")


def test_arrows_are_left_alone_while_typing_in_the_drawer(noir: Page):
    open_film(noir, "Out of the Past")
    noir.locator("#drawer input").first.focus()
    noir.keyboard.press("ArrowDown")
    noir.wait_for_timeout(150)
    expect(noir.locator("#drawer h2")).to_contain_text("Out of the Past")


def test_arrows_with_a_modifier_are_left_alone(noir: Page):
    open_film(noir, "Out of the Past")
    noir.keyboard.press("Alt+ArrowDown")
    noir.wait_for_timeout(150)
    expect(noir.locator("#drawer h2")).to_contain_text("Out of the Past")


def test_arrows_do_nothing_when_the_drawer_is_closed(noir: Page):
    show(noir, "Out of the Past")
    noir.keyboard.press("ArrowDown")
    noir.wait_for_timeout(150)
    expect(noir.locator("#drawer")).to_be_hidden()
    expect(noir.locator("#films tbody tr.marked")).to_have_count(0)


def test_a_click_on_the_white_row_closes_the_drawer(noir: Page):
    open_film(noir, "Out of the Past")
    box = row(noir, "Out of the Past").locator("td.c-title").bounding_box()
    assert box is not None
    noir.mouse.click(box["x"] + 30, box["y"] + 10)
    expect(noir.locator("#drawer")).to_be_hidden()
    expect(row(noir, "Out of the Past")).to_have_class("marked")


def test_a_film_opened_from_a_link_is_marked_and_the_list_stays_put(noir: Page, noir_server: str):
    show(noir, "Out of the Past")
    fid = row(noir, "Out of the Past").get_attribute("data-id")
    noir.goto(f"{noir_server}/?list=noir-test&film={fid}")
    expect(noir.locator("#drawer h2")).to_contain_text("Out of the Past")
    assert noir.evaluate("document.querySelector('#table-wrap').scrollTop") == 0  # never scrolled to it
    noir.keyboard.press("Escape")
    show(noir, "Out of the Past")
    expect(row(noir, "Out of the Past")).to_have_class("marked")


def test_a_row_under_the_sticky_header_is_not_lifted_over_it(noir: Page, noir_server: str):
    show(noir, "Out of the Past")
    fid = row(noir, "Out of the Past").get_attribute("data-id")
    noir.goto(f"{noir_server}/?list=noir-test")
    noir.wait_for_selector("#films tbody[data-count]")
    # Park the row half under the two-row header, then open it by the Back/URL path (no click, no nudge).
    scroll_list(noir, (OOTP_RANK - 1) * 36 + 18)
    noir.evaluate("(id) => { history.pushState(null, '', `?list=noir-test&film=${id}`); dispatchEvent(new PopStateEvent('popstate')); }", fid)
    expect(noir.locator("#drawer h2")).to_contain_text("Out of the Past")
    expect(noir.locator("#films tbody tr.lit")).to_have_count(0)


def test_a_step_that_cannot_load_puts_the_white_row_back(noir: Page):
    open_film(noir, "Out of the Past")
    pursued = row(noir, "Pursued").get_attribute("data-id")
    noir.route(f"**/api/films/{pursued}", lambda r: r.fulfill(status=404, body="{}"))
    noir.keyboard.press("ArrowDown")
    expect(noir.locator("#toast")).to_be_visible()
    expect(noir.locator("#drawer h2")).to_contain_text("Out of the Past")
    expect(row(noir, "Out of the Past")).to_have_class("lit edge")
    fid = row(noir, "Out of the Past").get_attribute("data-id")
    assert f"film={fid}" in noir.url


def test_fast_presses_move_the_white_row_at_once_and_draw_only_the_last_film(noir: Page):
    open_film(noir, "Out of the Past")
    noir.evaluate(
        """() => {
            const origFetch = window.fetch;
            window.fetch = (url, opts) => String(url).includes('/api/films/')
                ? new Promise((resolve) => setTimeout(() => resolve(origFetch(url, opts)), 250))
                : origFetch(url, opts);
        }"""
    )
    noir.keyboard.press("ArrowDown")
    noir.keyboard.press("ArrowDown")
    title = noir_titles()[OOTP_RANK - 1 + 2]
    expect(row(noir, title)).to_have_class("lit edge")  # at once — no detail has landed yet
    expect(noir.locator("#drawer h2")).to_contain_text("Out of the Past")
    expect(noir.locator("#drawer h2")).to_contain_text(title)
    noir.wait_for_timeout(300)
    expect(noir.locator("#drawer h2")).to_contain_text(title)


def test_the_drawer_starts_at_its_top_for_each_film(noir: Page):
    noir.add_style_tag(content="#drawer-body { min-height:3000px; }")  # every film's drawer scrolls
    open_film(noir, "Out of the Past")
    noir.evaluate("document.querySelector('#drawer').scrollTop = 9999")
    assert noir.evaluate("document.querySelector('#drawer').scrollTop") > 0
    noir.keyboard.press("ArrowDown")
    expect(noir.locator("#drawer h2")).to_contain_text("Pursued")
    assert noir.evaluate("document.querySelector('#drawer').scrollTop") == 0


# ---- story 7 (brief amendment 1.1): one click switches films ----


def click_dimmed_row(page: Page, title: str) -> None:
    """A real mouse click on the row's title cell, left of the drawer — it lands on the dim, as the owner's does."""
    box = row(page, title).locator("td.c-title").bounding_box()
    assert box is not None and box["x"] + 30 < 1440 - 760
    page.mouse.click(box["x"] + 30, box["y"] + box["height"] / 2)


def test_story_7_one_click_on_another_row_switches_the_drawer(noir: Page):
    open_film(noir, "Out of the Past")
    click_dimmed_row(noir, "Pursued")
    expect(noir.locator("#drawer h2")).to_contain_text("Pursued")
    expect(noir.locator("#drawer")).to_be_visible()
    expect(row(noir, "Pursued")).to_have_class("lit edge")
    expect(noir.locator("#films tbody tr.lit")).to_have_count(1)


def test_one_back_closes_the_drawer_however_many_films_were_clicked_through(noir: Page):
    open_film(noir, "Out of the Past")
    click_dimmed_row(noir, "Pursued")
    expect(noir.locator("#drawer h2")).to_contain_text("Pursued")
    fid = row(noir, "Pursued").get_attribute("data-id")
    noir.wait_for_function("(id) => new URLSearchParams(location.search).get('film') === id", arg=fid)
    noir.go_back()
    expect(noir.locator("#drawer")).to_be_hidden()
    assert "film=" not in noir.url
    expect(row(noir, "Pursued")).to_have_class("marked")


def test_a_click_on_the_dim_away_from_any_row_still_closes_the_drawer(noir: Page):
    open_film(noir, "Out of the Past")
    head = noir.locator("#films thead tr.filters th").first.bounding_box()  # the th is what sticks, not the thead
    assert head is not None
    noir.mouse.click(head["x"] + 30, head["y"] + 10)  # the sticky header, with rows scrolled beneath it
    expect(noir.locator("#drawer")).to_be_hidden()
    expect(row(noir, "Out of the Past")).to_have_class("marked")


def test_the_dim_shows_a_pointer_over_a_row_and_nowhere_else(noir: Page):
    open_film(noir, "Out of the Past")
    box = row(noir, "Pursued").locator("td.c-title").bounding_box()
    assert box is not None
    noir.mouse.move(box["x"] + 30, box["y"] + 10)
    assert noir.evaluate("getComputedStyle(document.querySelector('#drawer-backdrop')).cursor") == "pointer"
    noir.mouse.move(box["x"] + 30, 10)  # the page header
    assert noir.evaluate("getComputedStyle(document.querySelector('#drawer-backdrop')).cursor") != "pointer"


def test_a_click_on_a_dimmed_title_link_switches_films_and_opens_no_page(dash: Page):
    dash.locator("#films tbody tr", has_text="Bravo").first.locator(".c-year").click()
    expect(dash.locator("#drawer h2")).to_contain_text("Bravo")
    link = dash.locator("#films tbody tr", has_text="Alpha").first.locator("td.c-title a").bounding_box()
    assert link is not None
    pages = len(dash.context.pages)
    dash.mouse.click(link["x"] + 5, link["y"] + link["height"] / 2)
    expect(dash.locator("#drawer h2")).to_contain_text("Alpha")
    assert len(dash.context.pages) == pages
    dash.keyboard.press("Escape")
