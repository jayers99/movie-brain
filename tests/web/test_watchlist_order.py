"""Watchlist order (brief docs/superpowers/briefs/2026-10-02-watchlist-order/brief.md, amendment 1.1).

Each story test carries the brief's story number and title. They run on their OWN server seeded
with the owner's real watchlist as it stood on 2026-10-02 (same titles, same default order, same
ratings and list memberships that the stories name), plus fillers, so the brief's counts hold:
8 starred films showing, 9 in the table (Some Came Running is starred, departed and unrated).
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

from movie_brain.domain.models import CastRow, CrewRow, Film, ListEntry, ListMeta, OmdbRating, TmdbCredits
from movie_brain.infrastructure.database import Repository
from movie_brain.web.app import create_app

TODAY = date(2026, 10, 2)
OLD = date(2026, 9, 20)
# (title, year, director, mc, rt, imdb, my_rating, starred, lists) — the starred rows are in the
# real default order, which is also the seeded hand order.
NAMED = [
    ("Intolerance", 1916, "D.W. Griffith", 99, 98, 7.7, 2, True, 3),
    ("Moonlight", 2016, "Barry Jenkins", 99, 98, 7.4, None, True, 1),
    ("The Shop Around the Corner", 1940, "Ernst Lubitsch", 96, 99, 8.0, None, True, 0),
    ("Capturing the Friedmans", 2003, "Andrew Jarecki", 90, 97, 7.6, None, True, 1),
    ("The Wonderful Story of Henry Sugar", 2023, "Wes Anderson", 85, 95, 7.4, None, True, 0),
    ("Out of the Past", 1947, "Jacques Tourneur", 85, 87, 8.0, None, True, 6),
    ("Young Frankenstein", 1974, "Mel Brooks", 83, 95, 8.0, 9, True, 3),
    ("Lord of the Flies", 1963, "Peter Brook", 67, 92, 6.9, None, True, 0),
    ("Ugetsu", 1953, "Kenji Mizoguchi", None, 100, 8.1, None, False, 2),
]
WATCHLIST = [t[0] for t in NAMED if t[7]]
FILLERS = 20


def seed_order(repo: Repository) -> dict[str, int]:
    ids: dict[str, int] = {}
    for title, year, director, mc, rt, imdb, rating, _starred, _lists in NAMED:
        fid = repo.create_film(Film(title, year, director, ""))
        assert fid is not None
        ids[title] = fid
        repo.upsert_omdb(fid, OmdbRating(imdb, rt, True, "English", "{}", metacritic=mc), TODAY)
        if rating is not None:
            repo.set_rating(fid, rating, TODAY)
    # Some Came Running: on the Criterion Channel at the old walk, gone from today's — departed,
    # unrated, never viewed, so the catalogue hides it everywhere (story 21).
    repo.record_catalog("criterion", [Film("Some Came Running", 1958, "Vincente Minnelli", "https://c/scr")], OLD)
    # Ugetsu is unstarred, unrated and unviewed: it shows only while it is on today's walk (story 8).
    repo.record_catalog("criterion", [Film("Filler Current", 1960, "Dir", "https://c/fc"),
                                      Film("Ugetsu", 1953, "Kenji Mizoguchi", "https://c/ug")], TODAY)
    scr = repo.film_id_by_key("some came running (1958)")
    assert scr is not None
    ids["Some Came Running"] = scr
    # Out of the Past carries a director credit so `director:tourneur` (story 13) has someone to find.
    repo.set_external_id(ids["Out of the Past"], "tmdb", "910", TODAY)
    repo.write_credits(ids["Out of the Past"], TmdbCredits(
        tmdb_id=910, imdb_id=None, title="Out of the Past", original_title="Out of the Past", year=None,
        runtime_min=None, alt_titles=(), overview="A private eye is pulled back.", tagline=None, genres=("Crime",),
        keywords=(), cast=(CastRow(4110, "Robert Mitchum", "Jeff", 0),),
        crew=(CrewRow(2636, "Jacques Tourneur", "Director", "Directing"),)), TODAY)
    repo.upsert_omdb(scr, OmdbRating(7.2, 78, True, "English", "{}", metacritic=68), TODAY)
    for n in range(1, FILLERS + 1):
        fid = repo.create_film(Film(f"Shadow {n:02d}", 1930 + n, "Dir", ""))
        assert fid is not None
        repo.upsert_omdb(fid, OmdbRating(6.0, 50, True, "English", "{}", metacritic=10 + n), TODAY)
    # Star bottom-first so the fresh-star-at-top rule leaves the real order; the hidden film sits
    # between Young Frankenstein and Lord of the Flies, where the migration's seed put it.
    order = WATCHLIST[:7] + ["Some Came Running"] + WATCHLIST[7:]
    for title in reversed(order):
        repo.toggle_watchlist(ids[title], TODAY)
    # List memberships the stories count (On a list: 5 starred films) — one list per needed count.
    for k in range(1, 7):
        repo.upsert_film_list(ListMeta(f"l{k}", f"List {k}", None, None, None, False), TODAY)
    for title, *_rest, lists in NAMED:
        for k in range(1, lists + 1):
            rank = ids[title]
            repo.upsert_list_entry(f"l{k}", ListEntry(rank, title, "Dir"))
            repo.link_list_entry(f"l{k}", rank, ids[title])
    # My Ranking (story 12): Out of the Past 123rd, Young Frankenstein 142nd — ordered.
    repo.upsert_film_list(ListMeta("my-owned-tiers", "My Ranking", "me", 2026, None, True), TODAY)
    repo.upsert_list_entry("my-owned-tiers", ListEntry(123, "Out of the Past", "Dir"))
    repo.link_list_entry("my-owned-tiers", 123, ids["Out of the Past"])
    repo.upsert_list_entry("my-owned-tiers", ListEntry(142, "Young Frankenstein", "Dir"))
    repo.link_list_entry("my-owned-tiers", 142, ids["Young Frankenstein"])
    return ids


@pytest.fixture
def order_server() -> Generator[tuple[str, dict[str, int], Repository], None, None]:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    with tempfile.TemporaryDirectory() as tmp:
        repo = Repository(Path(tmp) / "order-movie-brain.db")
        ids = seed_order(repo)
        app = create_app(repo, today=lambda: TODAY)
        threading.Thread(target=lambda: app.run(host="127.0.0.1", port=port, use_reloader=False), daemon=True).start()
        time.sleep(0.5)
        yield f"http://127.0.0.1:{port}", ids, repo


@pytest.fixture
def dash(page: Page, order_server) -> Page:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(order_server[0] + "/?chips=watchlist")
    page.wait_for_selector("#films tbody[data-count]")
    return page


WATCHLIST_CHIP = '#chips .chip[data-chip="watchlist"]'
RATED_CHIP = '#chips .chip[data-group="rated"]'
ONLIST_CHIP = '#chips .chip[data-chip="multi_list"]'
WATCHED_CHIP = '#chips .chip[data-group="watched"]'


def titles(page: Page) -> list[str]:
    return [t.strip() for t in page.locator("#films tbody tr[data-id] td.c-title").evaluate_all("els => els.map(e => e.firstChild.textContent)")]


def row(page: Page, title: str):
    return page.locator("#films tbody tr[data-id]").filter(has=page.locator(f'td.c-title:text-is("{title}"), td.c-title > a:text-is("{title}")'))


def press(page: Page, title: str, arrow: str, times: int = 1) -> None:
    for _ in range(times):
        row(page, title).locator(f"td.c-move button.{arrow}").click()


def saved(order_server) -> list[str]:
    _url, ids, repo = order_server
    names = {v: k for k, v in ids.items()}
    return [names[i] for i in repo.watchlist_order()]


def test_story_1_my_watchlist_in_my_order(dash: Page):
    expect(dash.locator("#films tbody tr[data-id]")).to_have_count(8)
    assert titles(dash) == WATCHLIST
    expect(row(dash, "Intolerance").locator("button.up")).to_be_disabled()
    expect(row(dash, "Lord of the Flies").locator("button.down")).to_be_disabled()
    expect(row(dash, "Moonlight").locator("button.up")).to_be_enabled()


def test_story_2_out_of_the_past_goes_first(dash: Page, order_server):
    press(dash, "Out of the Past", "up", 5)
    expect(dash.locator("#films tbody tr[data-id]").first).to_contain_text("Out of the Past")
    assert titles(dash)[:3] == ["Out of the Past", "Intolerance", "Moonlight"]
    expect(row(dash, "Out of the Past")).to_have_class("marked")
    dash.wait_for_timeout(300)
    assert saved(order_server)[0] == "Out of the Past"


def test_story_3_one_too_far(dash: Page, order_server):
    press(dash, "Out of the Past", "up", 5)          # to the top; one press too many is impossible: ▲ greys there
    expect(row(dash, "Out of the Past").locator("button.up")).to_be_disabled()
    press(dash, "Out of the Past", "down", 1)
    assert titles(dash)[:2] == ["Intolerance", "Out of the Past"]


def test_story_4_with_a_chip_on_it_steps_past_what_i_can_see(dash: Page, order_server):
    dash.locator(RATED_CHIP).click()                 # Unrated by me
    expect(dash.locator("#films tbody tr[data-id]")).to_have_count(6)
    press(dash, "Out of the Past", "down")
    dash.locator(RATED_CHIP).click(); dash.locator(RATED_CHIP).click()   # off
    assert titles(dash)[-4:] == ["The Wonderful Story of Henry Sugar", "Young Frankenstein", "Lord of the Flies", "Out of the Past"]
    dash.wait_for_timeout(300)
    assert saved(order_server)[-5:] == ["The Wonderful Story of Henry Sugar", "Young Frankenstein", "Some Came Running", "Lord of the Flies", "Out of the Past"]


def test_story_5_on_a_list_keeps_my_order(dash: Page):
    dash.locator(ONLIST_CHIP).click()
    assert titles(dash) == ["Intolerance", "Moonlight", "Capturing the Friedmans", "Out of the Past", "Young Frankenstein"]
    expect(dash.locator("td.c-move button.up").first).to_be_visible()


def test_story_6_a_column_sort_hides_the_arrows(dash: Page):
    mc = dash.locator('th.sortable[data-col="metacritic"]')
    mc.click()
    expect(dash.locator("td.c-move:visible")).to_have_count(0)
    mc.click(); mc.click()
    expect(dash.locator("td.c-move:visible")).to_have_count(8)
    assert titles(dash) == WATCHLIST


def test_story_8_a_new_star_goes_to_the_top(dash: Page):
    dash.locator(WATCHLIST_CHIP).click()             # off
    dash.locator("#f-title").fill("ugetsu")
    dash.locator("#f-title").press("Tab")            # commit the filter now: a blur on the click would re-render under it
    row(dash, "Ugetsu").locator(".c-year").click()
    dash.locator("#drawer .watch-toggle").click()
    expect(dash.locator("#drawer .watch-toggle")).to_have_text("★")
    dash.locator("#drawer-close").click()
    dash.locator("#f-title").fill("")
    dash.locator(WATCHLIST_CHIP).click()
    assert titles(dash)[:2] == ["Ugetsu", "Intolerance"]


def test_story_12_a_picked_list_hides_the_arrows(dash: Page):
    dash.locator("#list-picker").select_option("my-owned-tiers")
    assert titles(dash) == ["Out of the Past", "Young Frankenstein"]
    expect(dash.locator("td.c-move:visible")).to_have_count(0)
    dash.locator("#list-picker").select_option("")
    expect(dash.locator("td.c-move:visible")).to_have_count(8)


def test_story_13_a_word_search_hides_them_director_does_not(dash: Page):
    bar = dash.locator("#search")
    bar.fill("out of the past"); bar.press("Enter")
    expect(dash.locator("td.c-move:visible")).to_have_count(0)
    bar.fill(""); bar.press("Enter")
    expect(dash.locator("td.c-move:visible")).to_have_count(8)
    bar.fill("director:tourneur"); bar.press("Enter")
    expect(dash.locator("#films tbody tr[data-id]")).to_have_count(1)
    expect(row(dash, "Out of the Past").locator("button.up")).to_be_disabled()
    expect(row(dash, "Out of the Past").locator("button.down")).to_be_disabled()


def test_story_15_a_move_that_does_not_save(dash: Page):
    dash.route("**/api/watchlist/move", lambda r: r.fulfill(status=500, body="{}"))
    press(dash, "Out of the Past", "up")
    expect(dash.locator("#toast")).to_contain_text("Could not save the order")
    dash.wait_for_timeout(300)
    assert titles(dash) == WATCHLIST


def test_story_16_watched_and_watchlist_together(dash: Page):
    dash.locator(WATCHED_CHIP).click()
    expect(dash.locator("#films tbody tr.empty-state")).to_be_visible()
    dash.locator(WATCHED_CHIP).click(); dash.locator(WATCHED_CHIP).click()
    assert titles(dash) == WATCHLIST


def test_story_17_i_try_to_drag_a_row(dash: Page):
    src = row(dash, "Out of the Past").locator(".c-year")
    dst = row(dash, "Intolerance").locator(".c-year")
    src.drag_to(dst)
    if dash.locator("#drawer").is_visible():
        dash.locator("#drawer-close").click()
    assert titles(dash) == WATCHLIST


def test_story_18_straight_to_the_top(dash: Page):
    press(dash, "Lord of the Flies", "up", 7)
    assert titles(dash)[0] == "Lord of the Flies"
    expect(row(dash, "Lord of the Flies").locator("button.up")).to_be_disabled()


def test_story_21_the_starred_film_i_cannot_see(dash: Page, order_server):
    dash.locator("#f-title").fill("some")
    expect(dash.locator("#films tbody tr[data-id]")).to_have_count(0)
    dash.locator("#f-title").fill("")
    press(dash, "Lord of the Flies", "up")
    dash.wait_for_timeout(300)
    assert saved(order_server)[-3:] == ["Lord of the Flies", "Young Frankenstein", "Some Came Running"]


def test_fast_presses_reach_the_server_in_order(dash: Page, order_server):
    """Two quick ▲ presses with the FIRST request held back: the second must wait its turn, so the
    saved order has the film two places up (unqueued, the second would be handled first)."""
    held, seen = [], []

    def handler(route):
        seen.append(route.request.post_data)
        if not held:
            held.append(route)       # hold the first request until released below
        else:
            route.continue_()

    dash.route("**/api/watchlist/move", handler)
    press(dash, "Capturing the Friedmans", "up", 2)
    dash.wait_for_timeout(500)
    assert len(seen) == 1            # the second press is queued behind the first
    held[0].continue_()
    dash.wait_for_timeout(1500)
    assert len(seen) == 2
    assert titles(dash)[:3] == ["Intolerance", "Capturing the Friedmans", "Moonlight"]
    assert saved(order_server)[:3] == ["Intolerance", "Capturing the Friedmans", "Moonlight"]


def test_story_16_hand_order_beats_last_watched(order_server, dash: Page):
    _url, ids, repo = order_server
    repo.add_viewing(ids["Moonlight"], date(2026, 9, 1), None, None, None, TODAY)
    repo.add_viewing(ids["Lord of the Flies"], date(2026, 9, 20), None, None, None, TODAY)
    dash.reload()
    dash.wait_for_selector("#films tbody[data-count]")
    dash.locator(WATCHED_CHIP).click()               # Watched: last-watched-first would put Lord of the Flies on top
    expect(dash.locator("#films tbody tr[data-id]")).to_have_count(2)
    assert titles(dash) == ["Moonlight", "Lord of the Flies"]


def close_drawer_on_grey(page: Page) -> None:
    box = page.locator("#table-wrap").bounding_box()
    page.mouse.click(box["x"] + 30, box["y"] + box["height"] - 10)   # below the last row: no row there
    expect(page.locator("#drawer")).to_be_hidden()


def test_story_9_the_drawer_is_open_keys_step_they_do_not_move(dash: Page):
    row(dash, "Intolerance").locator(".c-year").click()
    expect(dash.locator("#drawer h2")).to_contain_text("Intolerance")   # open (it fills async) before the key
    dash.keyboard.press("ArrowDown")
    expect(dash.locator("#drawer h2")).to_contain_text("Moonlight")
    row(dash, "The Shop Around the Corner").locator(".c-year").click(force=True)
    expect(dash.locator("#drawer h2")).to_contain_text("The Shop Around the Corner")
    close_drawer_on_grey(dash)
    expect(row(dash, "The Shop Around the Corner")).to_have_class("marked")
    assert titles(dash) == WATCHLIST


def test_story_10_keys_move_the_marked_film(dash: Page):
    row(dash, "Out of the Past").locator(".c-year").click()
    dash.locator("#drawer-close").click()
    for _ in range(3):
        dash.keyboard.press("ArrowUp")
    assert titles(dash)[2] == "Out of the Past"
    expect(row(dash, "Out of the Past")).to_have_class("marked")
    press(dash, "Moonlight", "down")
    dash.keyboard.press("ArrowDown")
    assert titles(dash).index("Moonlight") == 3


def test_three_fast_presses_land_three_places(dash: Page, order_server):
    dash.route("**/api/watchlist/move", lambda r: (time.sleep(0.3), r.continue_()))
    row(dash, "Out of the Past").locator(".c-year").click()
    dash.locator("#drawer-close").click()
    for _ in range(3):
        dash.keyboard.press("ArrowUp")
    dash.wait_for_timeout(1500)
    assert titles(dash)[2] == "Out of the Past"
    assert saved(order_server)[2] == "Out of the Past"


def test_story_19_the_next_morning(dash: Page, order_server):
    press(dash, "Out of the Past", "up", 5)
    dash.wait_for_timeout(300)
    dash.reload(); dash.wait_for_selector("#films tbody[data-count]")
    assert titles(dash)[0] == "Out of the Past"
    expect(dash.locator("#films tbody tr.marked")).to_have_count(0)
    dash.keyboard.press("ArrowDown")
    assert titles(dash)[0] == "Out of the Past"


def test_story_20_typing_a_rating_rating_the_marked_film(dash: Page):
    dash.locator(RATED_CHIP).click()                      # Unrated by me
    press(dash, "Out of the Past", "up")                  # marks it (story 10's rule) and moves it
    before = titles(dash)
    box = row(dash, "Out of the Past").locator("input.rating")
    box.click(); dash.keyboard.press("ArrowUp"); dash.keyboard.press("ArrowDown")
    assert titles(dash) == before
    box.fill("8"); box.press("Enter")
    expect(row(dash, "Out of the Past")).to_have_count(0)
    dash.locator(RATED_CHIP).click(); dash.locator(RATED_CHIP).click()
    expect(row(dash, "Out of the Past")).to_have_class("marked")
    dash.locator("body").click(position={"x": 5, "y": 5})
    i = titles(dash).index("Out of the Past")
    dash.keyboard.press("ArrowUp")
    assert titles(dash).index("Out of the Past") == i - 1
