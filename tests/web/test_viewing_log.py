"""The viewing log's read side (brief 2.2 stories 1, 5, 9, 10 and the panel): the drawer's Watched
block, the Watched chip and column, the heartbeat and the focus refresh. Own server, own seed;
the log is written through the repository, as the verb does — no test dictates."""

import socket
import tempfile
import threading
import time
from collections.abc import Generator
from datetime import date
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from movie_brain.domain.models import Film, OldRating, OmdbRating
from movie_brain.infrastructure.database import Repository
from movie_brain.web.app import create_app

TODAY = date(2026, 9, 27)
IDS: dict[str, int] = {}


def seed(repo: Repository) -> None:
    def film(title, year, mc, director="Dir"):
        fid = repo.create_film(Film(title, year, director, ""))
        repo.upsert_omdb(fid, OmdbRating(7.0, 90, True, "English", "{}", metacritic=mc), TODAY)
        IDS[title] = fid
        return fid

    repo.register_provider(1899, "Kino Film Collection")
    blue = film("The Blue Angel", 1930, 90)
    repo.upsert_old_rating("ntc", OldRating(154, "The Blue Angel", 1930, 4, "2006-12-26"))
    repo.link_old_rating("ntc", 154, blue, "hand", TODAY)
    cuba = film("I Am Cuba", 1964, 91)
    repo.set_rating(cuba, 9, TODAY)
    repo.upsert_old_rating("ntc", OldRating(3, "I Am Cuba", 1964, 5, "2005-01-12"))
    repo.link_old_rating("ntc", 3, cuba, "hand", TODAY)
    love = film("Love and Anarchy", 1973, 80)
    repo.upsert_old_rating("ntc", OldRating(28, "Love & Anarchy", 1973, 5, "2004-06-22"))
    repo.upsert_old_rating("ntc", OldRating(29, "Love and Anarchy", 1973, 5, "2004-06-22"))
    repo.link_old_rating("ntc", 28, love, "hand", TODAY)
    repo.link_old_rating("ntc", 29, love, "hand", TODAY)
    dragon = film("Dragon Inn", 1967, 100)
    repo.set_rating(dragon, 9, TODAY)
    film("Solaris", 1972, 93)
    # Logged already: Blue Angel on the 27th (two notes) and the 21st; Cuba today.
    repo.add_viewing(blue, date(2026, 9, 21), "kino-film-collection", "Pretty good — bottom of tier one.", None, TODAY)
    repo.add_viewing(blue, TODAY, "kino-film-collection", "I just watched The Blue Angel. It's an early German sound film.", 6, TODAY)
    repo.add_viewing(blue, TODAY, None, "One more thing — the Dietrich songs are the best part.", 7, TODAY)
    repo.add_viewing(cuba, TODAY, None, "Still astonishing, the camera work.", None, TODAY)


@pytest.fixture
def server() -> Generator[tuple[str, Repository], None, None]:
    sock = socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]; sock.close()
    with tempfile.TemporaryDirectory() as tmp:
        repo = Repository(Path(tmp) / "viewing-log.db")
        seed(repo)
        app = create_app(repo, today=lambda: TODAY)
        threading.Thread(target=lambda: app.run(host="127.0.0.1", port=port, use_reloader=False), daemon=True).start()
        time.sleep(0.5)
        yield f"http://127.0.0.1:{port}", repo


@pytest.fixture
def dash(page: Page, server) -> Page:
    page.set_viewport_size({"width": 1440, "height": 800})
    page.goto(server[0])
    page.wait_for_selector("#films tbody[data-count]")
    return page


def open_film(page: Page, title: str) -> None:
    page.locator("#films tbody tr[data-id]", has_text=title).locator(".c-year").click()
    expect(page.locator("#drawer h2")).to_contain_text(title)


def titles(page: Page) -> list[str]:
    return [t.strip() for t in page.locator("#films tbody tr[data-id] td.c-title").evaluate_all("els => els.map(e => e.firstChild.textContent)")]


def test_story_1_the_drawer_reads_the_line_newest_first_with_the_rental_below(dash: Page):
    open_film(dash, "The Blue Angel")
    lines = dash.locator("#drawer .ratings .watched li")
    expect(lines).to_have_count(3)
    expect(lines.nth(0)).to_contain_text("2026-09-27")
    expect(lines.nth(0)).to_contain_text("Kino Film Collection")
    expect(lines.nth(0)).to_contain_text("2 notes")
    expect(lines.nth(1)).to_contain_text("2026-09-21")
    expect(lines.nth(2)).to_have_class("rental")
    expect(lines.nth(2)).to_contain_text("2006-12-26")
    expect(lines.nth(2)).to_contain_text("★★★★☆")
    expect(dash.locator("#drawer .ratings input.rating")).to_have_value("7")
    expect(dash.locator("#drawer .ratings .old-rating")).to_have_count(0)  # the "Me, 2004–08" line is gone
    lines.nth(0).locator("details summary").click()
    expect(lines.nth(0)).to_contain_text("early German sound film")
    expect(lines.nth(0)).to_contain_text("Dietrich songs")


def test_story_10_a_rated_film_never_logged_says_so(dash: Page):
    open_film(dash, "Dragon Inn")
    expect(dash.locator("#drawer .ratings .watched")).to_contain_text("Never logged.")
    expect(dash.locator("#drawer .ratings input.rating")).to_have_value("9")


def test_a_duplicate_rental_row_shows_once(dash: Page):
    open_film(dash, "Love and Anarchy")
    expect(dash.locator("#drawer .ratings .watched li.rental")).to_have_count(1)


def test_story_9_the_watched_chip_and_column(dash: Page):
    chip = dash.locator('#chips .chip[data-chip="watched"]')
    expect(chip).to_have_text("Watched")
    assert dash.locator('#films thead th.sortable[data-col="last_watched"]').inner_text().strip() == "Watched"
    chip.click()
    expect(chip).to_have_class("chip active")
    assert "chips=watched" in dash.url
    assert titles(dash) == ["The Blue Angel", "I Am Cuba"]  # newest viewing first; Cuba's rental does not count for Love and Anarchy
    dash.locator("#films tbody tr[data-id]", has_text="I Am Cuba").locator("td.c-watched").wait_for()
    assert dash.locator("#films tbody tr[data-id]", has_text="I Am Cuba").locator("td.c-watched").inner_text().strip() == "2026-09-27"
    chip.click()
    dash.locator('#films thead th[data-col="last_watched"]').click()  # asc: logged films first by date, never-logged last
    t = titles(dash)
    assert t[:2] in (["The Blue Angel", "I Am Cuba"], ["I Am Cuba", "The Blue Angel"]) and t[-1] in ("Dragon Inn", "Solaris", "Love and Anarchy")
    dash.locator('#films thead th[data-col="last_watched"]').click()  # desc: still never-logged last
    assert titles(dash)[-1] in ("Dragon Inn", "Solaris", "Love and Anarchy")


def test_the_empty_state_under_watched_reads_no_viewing_logged_yet(page: Page, server):
    base, repo = server
    for v in repo.list_viewings():
        repo.remove_viewing(int(v["id"]))
    page.goto(base); page.wait_for_selector("#films tbody[data-count]")
    page.locator('#chips .chip[data-chip="watched"]').click()
    expect(page.locator("#films tbody tr.empty-state")).to_contain_text("No viewing logged yet.")


def test_the_drawer_reports_its_open_film_and_clears_it_on_close(dash: Page, server):
    from datetime import datetime
    _, repo = server
    open_film(dash, "Solaris")
    dash.wait_for_timeout(300)
    assert repo.drawer_film(datetime.now()) == IDS["Solaris"]
    dash.locator("#drawer-close").click()
    dash.wait_for_timeout(300)
    assert repo.drawer_film(datetime.now()) is None


def test_the_drawer_refreshes_itself_when_the_window_regains_focus(dash: Page, server):
    _, repo = server
    open_film(dash, "Dragon Inn")
    expect(dash.locator("#drawer .ratings .watched")).to_contain_text("Never logged.")
    repo.add_viewing(IDS["Dragon Inn"], date(2026, 9, 24), None, "last Thursday", None, TODAY)  # what the verb does, out of the page's sight
    dash.evaluate("window.dispatchEvent(new Event('focus'))")
    expect(dash.locator("#drawer .ratings .watched li").first).to_contain_text("2026-09-24")
    expect(dash.locator("#films tbody tr[data-id]", has_text="Dragon Inn").locator("td.c-watched")).to_have_text("2026-09-24")
