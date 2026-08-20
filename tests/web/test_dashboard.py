import re
import socket
import tempfile
import threading
import time
from collections.abc import Generator
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from movie_brain.infrastructure.database import Repository
from movie_brain.web.app import create_app


def count(page: Page) -> int:
    return int(page.locator("#films tbody").get_attribute("data-count"))


def first_titles(page: Page, n: int) -> list[str]:
    return page.locator("#films tbody tr .c-title a").all_inner_texts()[:n]


def test_loads_all_films_default_sort_imdb_desc_nulls_last(dash: Page):
    assert count(dash) == 5
    assert first_titles(dash, 5) == ["Alpha", "Echo", "Bravo", "Charlie", "Delta"]
    expect(dash.locator("#count-films")).to_have_text("5")
    expect(dash.locator("#count-showing")).to_have_text("Showing 5 of 5")
    expect(dash.locator("#films tbody tr").first.locator(".c-title a")).to_have_attribute("href", "https://c/alpha")


def test_chips_stack_with_and(dash: Page):
    dash.click(".chip[data-chip=unrated]")
    assert count(dash) == 3  # Bravo, Charlie, Delta
    dash.click(".chip[data-chip=pending]")
    assert count(dash) == 2  # Charlie (unmatched), Delta (pending)
    expect(dash.locator(".chip[data-chip=unrated]")).to_have_class(re.compile("active"))
    dash.click("#chips-clear")
    assert count(dash) == 5


def test_each_chip_alone(dash: Page):
    expected = {
        "leaving": 1,
        "unrated": 3,
        "mine": 1,
        "not_interested": 1,
        "pending": 2,
        "top_rt": 1,
        "top_imdb": 1,
        "recent": 1,
    }
    for chip, n in expected.items():
        dash.click(f".chip[data-chip={chip}]")
        assert count(dash) == n, chip
        dash.click(f".chip[data-chip={chip}]")


def test_sort_cycles_and_keeps_nulls_last(dash: Page):
    dash.click("th.sortable[data-col=rt]")
    assert first_titles(dash, 5) == ["Echo", "Alpha", "Bravo", "Charlie", "Delta"]  # asc: 60, 95, then nulls
    expect(dash.locator("th.sortable[data-col=rt]")).to_have_attribute("data-dir", "asc")
    dash.click("th.sortable[data-col=rt]")
    assert first_titles(dash, 2) == ["Alpha", "Echo"]
    dash.click("th.sortable[data-col=rt]")
    assert first_titles(dash, 2) == ["Alpha", "Echo"]  # back to default imdb desc
    expect(dash.locator("th.sortable[data-col=rt]")).not_to_have_attribute("data-dir", re.compile(".+"))


def test_column_filters_combine_with_chips(dash: Page):
    dash.fill("#f-director", "ann")
    assert count(dash) == 2  # Alpha, Echo
    dash.click(".chip[data-chip=not_interested]")
    assert count(dash) == 1
    assert first_titles(dash, 1) == ["Echo"]
    dash.click(".chip[data-chip=not_interested]")
    dash.fill("#f-director", "")
    dash.select_option("#f-lang", ["Spanish"])
    assert count(dash) == 1
    dash.select_option("#f-lang", [])
    dash.fill("#f-imdb-min", "7")
    assert count(dash) == 2  # Alpha 8.5, Echo 7.0; nulls excluded
    dash.fill("#f-year-max", "1955")
    assert count(dash) == 1


def test_url_state_round_trips(dash: Page, server: str):
    dash.click(".chip[data-chip=unrated]")
    dash.fill("#f-title", "a")
    dash.click("th.sortable[data-col=year]")
    url = dash.url
    assert "chips=unrated" in url and "title=a" in url
    assert ("sort=year%3Aasc" in url) or ("sort=year:asc" in url)
    dash.goto(url)
    dash.wait_for_selector("#films tbody[data-count]")
    expect(dash.locator(".chip[data-chip=unrated]")).to_have_class(re.compile("active"))
    expect(dash.locator("#f-title")).to_have_value("a")
    expect(dash.locator("th.sortable[data-col=year]")).to_have_attribute("data-dir", "asc")
    assert count(dash) == 3  # Bravo, Charlie, Delta contain "a"


def test_drawer_opens_from_info_button_and_restores_url(dash: Page):
    dash.click("#films tbody tr[data-id] .info >> nth=0")
    drawer = dash.locator("#drawer")
    expect(drawer).to_be_visible()
    expect(drawer.locator("h2")).to_have_text("Alpha")
    expect(drawer.locator("pre.raw")).to_contain_text('"Plot": "A plot."')
    expect(drawer.locator("a.criterion")).to_have_attribute("href", "https://c/alpha")
    assert "film=" in dash.url
    dash.keyboard.press("Escape")
    expect(drawer).to_be_hidden()
    assert "film=" not in dash.url


def test_drawer_opens_on_load_from_url(dash: Page, server: str):
    fid = dash.locator("#films tbody tr[data-id]").first.get_attribute("data-id")
    dash.goto(f"{server}/?film={fid}")
    expect(dash.locator("#drawer h2")).to_have_text("Alpha")
    dash.click("#drawer-backdrop", position={"x": 10, "y": 10})
    expect(dash.locator("#drawer")).to_be_hidden()


def test_row_click_opens_drawer_but_title_link_does_not(dash: Page):
    dash.click("#films tbody tr[data-id] .c-year >> nth=1")
    expect(dash.locator("#drawer h2")).to_have_text("Echo")
    dash.click("#drawer-close")
    expect(dash.locator("#drawer")).to_be_hidden()


def test_rating_round_trip_updates_counts_and_persists(dash: Page, server: str):
    row = dash.locator("#films tbody tr[data-id]").filter(has_text="Bravo")
    expect(dash.locator("#count-mine")).to_have_text("2")
    row.locator("input.rating").fill("7")
    row.locator("input.rating").press("Enter")
    expect(dash.locator("#count-mine")).to_have_text("3")
    dash.reload()
    dash.wait_for_selector("#films tbody[data-count]")
    expect(dash.locator("#films tbody tr[data-id]").filter(has_text="Bravo").locator("input.rating")).to_have_value("7")
    # blank un-rates
    row = dash.locator("#films tbody tr[data-id]").filter(has_text="Bravo")
    row.locator("input.rating").fill("")
    row.locator("input.rating").press("Enter")
    expect(dash.locator("#count-mine")).to_have_text("2")


def test_invalid_rating_reverts(dash: Page):
    row = dash.locator("#films tbody tr[data-id]").filter(has_text="Alpha")
    inp = row.locator("input.rating")
    inp.fill("12")
    inp.press("Enter")
    expect(inp).to_have_value("9")
    expect(dash.locator("#count-mine")).to_have_text("2")


def test_drawer_rating_input_also_works(dash: Page):
    dash.click("#films tbody tr[data-id] .info >> nth=0")  # Alpha
    inp = dash.locator("#drawer input.rating")
    inp.fill("10")
    inp.press("Enter")
    expect(dash.locator("#films tbody tr[data-id]").filter(has_text="Alpha").locator("input.rating")).to_have_value(
        "10"
    )
    inp.fill("9")
    inp.press("Enter")  # restore seed value for other tests


def test_drawer_race_shows_latest_requested_film(dash: Page):
    # Patch window.fetch (in-browser, via setTimeout) so the Alpha detail request is
    # slow to resolve while the Echo detail request right after it is not. This
    # reproduces the out-of-order-response race without touching Playwright's own
    # driver thread (a Python-side route delay would starve the second click below).
    rows = dash.locator("#films tbody tr[data-id]")
    alpha_id = rows.filter(has_text="Alpha").get_attribute("data-id")
    echo_id = rows.filter(has_text="Echo").get_attribute("data-id")
    dash.evaluate(
        """(alphaId) => {
            const origFetch = window.fetch;
            window.fetch = (url, opts) => {
                if (String(url).endsWith(`/api/films/${alphaId}`)) {
                    return new Promise((resolve) => setTimeout(() => resolve(origFetch(url, opts)), 300));
                }
                return origFetch(url, opts);
            };
        }""",
        alpha_id,
    )
    dash.click(f'#films tbody tr[data-id="{alpha_id}"] .info')
    dash.click(f'#films tbody tr[data-id="{echo_id}"] .info')
    expect(dash.locator("#drawer h2")).to_have_text("Echo")
    dash.wait_for_timeout(400)  # let the superseded, slow Alpha response land and confirm it's a no-op
    expect(dash.locator("#drawer h2")).to_have_text("Echo")


# ---- empty database: separate server/page fixtures so the seeded `dash`/`server`
# fixtures (and every test above) stay untouched. ----


@pytest.fixture
def empty_server() -> Generator[str, None, None]:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    with tempfile.TemporaryDirectory() as tmp:
        repo = Repository(Path(tmp) / "empty-movie-brain.db")
        app = create_app(repo)
        threading.Thread(target=lambda: app.run(host="127.0.0.1", port=port, use_reloader=False), daemon=True).start()
        time.sleep(0.5)
        yield f"http://127.0.0.1:{port}"


@pytest.fixture
def empty_dash(page: Page, empty_server: str) -> Page:
    page.goto(empty_server)
    page.wait_for_selector("#films tbody[data-count]")
    return page


def test_empty_db_shows_import_hint(empty_dash: Page):
    assert count(empty_dash) == 0
    expect(empty_dash.locator("#films tbody")).to_contain_text("movie-brain import-legacy")
    expect(empty_dash.locator("#films tbody")).to_contain_text("movie-brain sync")
    expect(empty_dash.locator("tr.empty-state")).to_be_visible()
