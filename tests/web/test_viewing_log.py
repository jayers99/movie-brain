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
    # Logged already: Blue Angel on the 27th (two notes) and the 21st; Cuba on the 25th — an
    # earlier day, so the Watched column and sort have a real order to pin, not a same-day tie.
    # Love and Anarchy has only the old 2004-08 rentals above — no viewing was ever logged for
    # it, so it stays out of the Watched chip.
    # The 21st's line is marked for study (backlog 48): the word on the line, the chip's second state.
    repo.add_viewing(blue, date(2026, 9, 21), "kino-film-collection", "Pretty good — bottom of tier one.", None, TODAY, study=True)
    repo.add_viewing(blue, TODAY, "kino-film-collection", "I just watched The Blue Angel. It's an early German sound film.", 6, TODAY)
    repo.add_viewing(blue, TODAY, None, "One more thing — the Dietrich songs are the best part.", 7, TODAY)
    repo.add_viewing(cuba, date(2026, 9, 25), None, "Still astonishing, the camera work.", None, TODAY)


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
    chip = dash.locator('#chips .chip[data-group="watched"]')
    expect(chip).to_have_text("Watched")
    assert dash.locator('#films thead th.sortable[data-col="last_watched"]').inner_text().strip() == "Watched"
    chip.click()
    expect(chip).to_have_class("chip active")
    assert "chips=watched" in dash.url
    # Newest viewing first: Blue Angel logged on the 27th, Cuba on the 25th. Love and Anarchy
    # has only the old 2004-08 rentals — no viewing — so it never appears under this chip.
    assert titles(dash) == ["The Blue Angel", "I Am Cuba"]
    dash.locator("#films tbody tr[data-id]", has_text="I Am Cuba").locator("td.c-watched").wait_for()
    assert dash.locator("#films tbody tr[data-id]", has_text="I Am Cuba").locator("td.c-watched").inner_text().strip() == "2026-09-25"
    chip.click(); chip.click()  # a cycle chip since the study mark: Watched → To study → off
    expect(chip).not_to_have_class("chip active")
    dash.locator('#films thead th[data-col="last_watched"]').click()  # asc: earliest logged first, never-logged last
    assert titles(dash)[:2] == ["I Am Cuba", "The Blue Angel"]
    assert titles(dash)[-1] in ("Dragon Inn", "Solaris", "Love and Anarchy")
    dash.locator('#films thead th[data-col="last_watched"]').click()  # desc: newest logged first, still never-logged last
    assert titles(dash)[:2] == ["The Blue Angel", "I Am Cuba"]
    assert titles(dash)[-1] in ("Dragon Inn", "Solaris", "Love and Anarchy")


def test_the_empty_state_under_watched_reads_no_viewing_logged_yet(page: Page, server):
    base, repo = server
    for v in repo.list_viewings():
        repo.remove_viewing(int(v["id"]))
    page.goto(base); page.wait_for_selector("#films tbody[data-count]")
    page.locator('#chips .chip[data-group="watched"]').click()
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


def test_a_focus_refresh_with_nothing_changed_leaves_an_open_note_and_the_scroll_alone(dash: Page, server):
    """Point-C gap check finding 5: the redraw must be skipped when nothing moved, or every
    alt-tab (not just one that followed a dictation) would collapse a note the owner had open
    and reset the drawer's scroll."""
    _, repo = server
    dash.set_viewport_size({"width": 1440, "height": 300})  # short enough that the drawer must scroll
    open_film(dash, "The Blue Angel")
    note = dash.locator("#drawer .ratings .watched li").first.locator("details.note")
    note.locator("summary").click()
    expect(note).to_have_js_property("open", True)
    dash.evaluate("document.querySelector('#drawer').scrollTop = 40")
    dash.evaluate("window.dispatchEvent(new Event('focus'))")
    dash.wait_for_timeout(200)
    expect(note).to_have_js_property("open", True)
    assert dash.evaluate("document.querySelector('#drawer').scrollTop") == 40
    # Now something DOES change out of the page's sight: the block must update.
    repo.add_viewing(IDS["The Blue Angel"], date(2026, 9, 26), None, "another night", None, TODAY)
    dash.evaluate("window.dispatchEvent(new Event('focus'))")
    lines = dash.locator("#drawer .ratings .watched li")
    expect(lines).to_have_count(4)
    expect(lines.nth(1)).to_contain_text("2026-09-26")


# ---- the study mark (backlog 48, brief 2026-09-29-study-mark) ------------------------------


def study_chip(page: Page):
    return page.locator('#chips .chip[data-group="watched"]')


def test_study_story_1_a_marked_line_carries_the_word_and_an_unmarked_one_does_not(dash: Page):
    open_film(dash, "The Blue Angel")
    lines = dash.locator("#drawer .ratings .watched li")
    expect(lines.nth(1)).to_contain_text("2026-09-21")
    expect(lines.nth(1).locator(".study")).to_have_text("study")
    expect(lines.nth(0)).to_contain_text("2026-09-27")
    expect(lines.nth(0).locator(".study")).to_have_count(0)
    # The word sits between the service and the note, never as a button.
    assert lines.nth(1).locator("button").count() == 0
    assert "Kino Film Collection · study ·" in " ".join(lines.nth(1).inner_text().split())


def test_study_story_4_the_watched_chip_cycles_off_watched_to_study_off(dash: Page):
    chip = study_chip(dash)
    expect(chip).to_have_text("Watched")
    chip.click()
    expect(chip).to_have_text("Watched")
    expect(chip).to_have_class("chip active")
    assert "chips=watched" in dash.url
    assert titles(dash) == ["The Blue Angel", "I Am Cuba"]
    chip.click()
    expect(chip).to_have_text("To study")
    expect(chip).to_have_class("chip active")
    assert "chips=study" in dash.url and "chips=watched" not in dash.url
    assert titles(dash) == ["The Blue Angel"]  # any line marked; Cuba has none
    chip.click()
    expect(chip).to_have_text("Watched")
    expect(chip).not_to_have_class("chip active")
    assert "chips=" not in dash.url


def test_study_story_4_newest_viewing_first_under_to_study(dash: Page, server):
    _, repo = server
    cuba = [v for v in repo.list_viewings(film_id=IDS["I Am Cuba"])][0]
    repo.set_study(int(cuba["id"]), True)  # Cuba's 25th is now marked; Blue Angel's last viewing is the 27th
    dash.goto(dash.url.split("?")[0] + "?chips=study"); dash.wait_for_selector("#films tbody[data-count]")
    expect(study_chip(dash)).to_have_text("To study")
    assert titles(dash) == ["The Blue Angel", "I Am Cuba"]


def test_study_the_empty_state_under_to_study_reads_nothing_marked_yet(page: Page, server):
    base, repo = server
    for v in repo.list_viewings(study_only=True):
        repo.set_study(int(v["id"]), False)
    page.goto(base); page.wait_for_selector("#films tbody[data-count]")
    study_chip(page).click(); study_chip(page).click()
    expect(study_chip(page)).to_have_text("To study")
    expect(page.locator("#films tbody tr.empty-state")).to_contain_text("Nothing marked for study yet.")


def test_study_a_mark_set_behind_the_pages_back_shows_on_focus(dash: Page, server):
    _, repo = server
    open_film(dash, "I Am Cuba")
    expect(dash.locator("#drawer .ratings .watched li").first.locator(".study")).to_have_count(0)
    cuba = repo.list_viewings(film_id=IDS["I Am Cuba"])[0]
    repo.set_study(int(cuba["id"]), True)  # `viewings study N`, out of the page's sight
    dash.evaluate("window.dispatchEvent(new Event('focus'))")
    expect(dash.locator("#drawer .ratings .watched li").first.locator(".study")).to_have_text("study")


def test_study_story_9_a_removed_line_leaves_to_study_and_the_drawer_stays_open(dash: Page, server):
    _, repo = server
    dash.goto(dash.url.split("?")[0] + "?chips=study"); dash.wait_for_selector("#films tbody[data-count]")
    assert titles(dash) == ["The Blue Angel"]
    open_film(dash, "The Blue Angel")
    marked = repo.list_viewings(study_only=True)[0]
    repo.remove_viewing(int(marked["id"]))  # `viewings remove N`: the mark goes with the line
    dash.evaluate("window.dispatchEvent(new Event('focus'))")
    expect(dash.locator("#films tbody tr[data-id]")).to_have_count(0)
    expect(dash.locator("#drawer")).to_be_visible()
    expect(dash.locator("#drawer h2")).to_contain_text("The Blue Angel")
    expect(dash.locator("#drawer .ratings input.rating")).to_have_value("7")
