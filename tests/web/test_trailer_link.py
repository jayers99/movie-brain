"""The drawer's trailer link (brief docs/superpowers/briefs/2026-09-20-trailer-link/brief.md, version 1.0).

The seven story tests carry the brief's story titles. They run on their own server (the shared seed
holds no trailers) and NO test reaches YouTube or Apple: YouTube's IFrame API script is routed to a
stub that records every player the page builds (`window.__yt`) and lets a test fire its callbacks,
and Apple's preview file is routed to a request that never answers (so it "plays") or is aborted
(so it fails). The trailers themselves are rows written by `write_trailers`, as `enrich trailers`
would have left them.
"""

import re
import socket
import tempfile
import threading
import time
from collections.abc import Generator
from datetime import date
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from movie_brain.domain.models import Film, OmdbRating
from movie_brain.domain.trailers import APPLE, APPLE_NAME, YOUTUBE, Trailer
from movie_brain.infrastructure.database import Repository
from movie_brain.web.app import create_app

TODAY = date(2026, 9, 20)
APPLE_HOST = "https://video-ssl.itunes.apple.com"
YT_API = "https://www.youtube.com/iframe_api"

YT_STUB = """
window.__yt = [];
window.YT = { Player: function (el, opts) {
  const p = this; p.el = el; p.opts = opts; p.destroyed = false;
  p.destroy = () => { p.destroyed = true; };
  p.playVideo = () => { p.played = true; };
  window.__yt.push(p);
  if (!window.__ytSilent) setTimeout(() => opts.events.onReady({ target: p }), 0);
} };
if (window.onYouTubeIframeAPIReady) window.onYouTubeIframeAPIReady();
"""


def yt(key: str, name: str) -> Trailer:
    return Trailer(YOUTUBE, key, name)


def apple(slug: str) -> Trailer:
    return Trailer(APPLE, f"{APPLE_HOST}/itunes-assets/{slug}.m4v", APPLE_NAME)


# (title, year, metacritic, rt, trailers) — the default sort is Metacritic then RT, so this IS the order.
# `None` = never looked up (no row at all); `[]` = looked up, nothing found.
FILMS: list[tuple[str, int, int, int, list[Trailer] | None]] = [
    ("Army of Shadows", 1969, 99, 97, [yt("aos00000001", "Official 4K Restoration Trailer [Subtitled]"), yt("aos00000002", "Trailer"), apple("aos")]),
    ("Pan's Labyrinth", 2006, 98, 95, [yt("pan00000001", "Official 4K Trailer")]),
    ("The Big Sleep", 1946, 86, 96, [yt("tbs00000001", "The Big Sleep Official Trailer #1"), apple("tbs")]),
    ("To Die For", 1995, 86, 88, [apple("tdf")]),
    ("Memories of Murder", 2003, 82, 90, [yt("mom00000001", "MEMORIES OF MURDER Trailer"), apple("mom")]),
    ("The Hitch-Hiker", 1953, 60, 94, []),
    ("Never Asked", 1950, 50, 50, None),
    ("Basic Instinct", 1992, 43, 56, [yt("bas00000001", "Official 4K Restoration Trailer"), yt("bas00000002", "Official Trailer"), yt("bas00000003", "Basic Instinct Theatrical Trailer (1992) [4K]"), apple("bas")]),
]


def seed(repo: Repository) -> None:
    for title, year, mc, rt, trailers in FILMS:
        fid = repo.create_film(Film(title, year, "Dir", ""))
        assert fid is not None
        repo.upsert_omdb(fid, OmdbRating(7.0, rt, True, "English", "{}", metacritic=mc), TODAY)
        repo.set_external_id(fid, "tmdb", str(1000 + fid), TODAY)
        if title not in ("The Hitch-Hiker", "Never Asked"):  # Apple sells the rest: CheapCharts + ♡ Wishlist it
            repo.set_external_id(fid, "itunes", str(910000000 + fid), TODAY)
        if title == "The Big Sleep":
            repo.mark_owned(fid, TODAY)
        if trailers is not None:
            repo.write_trailers(fid, 1000 + fid, None, trailers, TODAY)
    repo.record_catalog("criterion", [Film("M", 1931, "Fritz Lang", "https://c/m")], TODAY)
    m = repo.film_id_by_key("m (1931)")
    assert m is not None
    repo.upsert_omdb(m, OmdbRating(8.3, 100, True, "German", "{}", metacritic=40), TODAY)
    repo.set_external_id(m, "tmdb", "832", TODAY)
    repo.set_external_id(m, "itunes", "920000001", TODAY)
    repo.write_trailers(m, 832, "920000001", [yt("mmm00000001", "Trailer"), apple("m")], TODAY)


@pytest.fixture(scope="module")
def trailer_server() -> Generator[str, None, None]:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    with tempfile.TemporaryDirectory() as tmp:
        repo = Repository(Path(tmp) / "trailer-movie-brain.db")
        seed(repo)
        app = create_app(repo, today=lambda: TODAY)
        threading.Thread(target=lambda: app.run(host="127.0.0.1", port=port, use_reloader=False), daemon=True).start()
        time.sleep(0.5)
        yield f"http://127.0.0.1:{port}"


@pytest.fixture
def dash(page: Page, trailer_server: str) -> Page:
    page.set_viewport_size({"width": 1440, "height": 800})
    page.route(YT_API, lambda route: route.fulfill(content_type="text/javascript", body=YT_STUB))
    page.route(f"{APPLE_HOST}/**", lambda route: None)  # never answers: the preview "plays" for ever
    page.route("https://www.youtube-nocookie.com/**", lambda route: route.abort())
    page.goto(trailer_server)
    page.wait_for_selector("#films tbody[data-count]")
    return page


# ---- helpers ----

LINK = "#drawer p.links button.trailer-link"
SEARCH = "#drawer p.links a.trailer-search"


def open_film(page: Page, title: str) -> None:
    exact = re.compile(rf"^{re.escape(title)}( |$)")  # "M" is also how Memories of Murder starts
    page.locator("#films tbody tr[data-id]").filter(has=page.locator("td.c-title", has_text=exact)).locator(".c-year").click()
    expect(page.locator("#drawer h2")).to_contain_text(title)


def players(page: Page) -> list[dict]:
    return page.evaluate(
        "() => (window.__yt || []).map((p) => ({ key: p.opts.videoId, host: p.opts.host, vars: p.opts.playerVars,"
        " destroyed: p.destroyed, played: !!p.played }))"
    )


def wait_players(page: Page, n: int) -> list[dict]:
    page.wait_for_function("n => (window.__yt || []).length >= n", arg=n)
    return players(page)


def fail_player(page: Page, index: int, code: int = 150) -> None:
    page.evaluate("([i, code]) => window.__yt[i].opts.events.onError({ data: code })", [index, code])


def drawer_title(page: Page) -> str:
    return page.locator("#drawer h2").inner_text()


# ---- the seven stories ----


def test_story_1_one_click_and_the_trailer_is_playing(dash: Page):
    open_film(dash, "Army of Shadows")
    expect(dash.locator("#trailer")).to_be_hidden()
    expect(dash.locator(LINK)).to_have_text("▶ Trailer")
    dash.click(LINK)
    expect(dash.locator("#trailer")).to_be_visible()
    (player,) = wait_players(dash, 1)
    assert player["key"] == "aos00000001" and player["vars"]["autoplay"] == 1
    assert player["host"] == "https://www.youtube-nocookie.com"
    dash.wait_for_function("() => window.__yt[0].played")  # started by itself once the player was ready
    # Over the WHOLE browser window, the player centred in it.
    box = dash.locator("#trailer").bounding_box()
    assert box is not None and (box["x"], box["y"], box["width"], box["height"]) == (0, 0, 1440, 800)
    screen = dash.locator("#trailer-screen").bounding_box()
    assert screen is not None and abs((screen["x"] + screen["width"] / 2) - 720) <= 1
    expect(dash.locator("#trailer-caption")).to_contain_text("Army of Shadows (1969)")
    expect(dash.locator("#trailer-caption")).to_contain_text("Official 4K Restoration Trailer [Subtitled] · YouTube")
    assert "trailer" not in dash.url  # never in the URL or history

    dash.keyboard.press("Escape")
    expect(dash.locator("#trailer")).to_be_hidden()
    assert players(dash)[0]["destroyed"]
    # The drawer closes through history.back(), which lands LATER: only a wait can show it did not.
    dash.wait_for_timeout(300)
    expect(dash.locator("#drawer")).to_be_visible()  # the drawer is still open on the film
    assert "Army of Shadows" in drawer_title(dash) and "film=" in dash.url
    dash.keyboard.press("Escape")
    expect(dash.locator("#drawer")).to_be_hidden()  # a second Esc closes the drawer, as always


def test_story_1_the_cross_and_a_click_outside_close_it_too(dash: Page):
    open_film(dash, "Army of Shadows")
    dash.click(LINK)
    dash.click("#trailer-close")
    expect(dash.locator("#trailer")).to_be_hidden()
    expect(dash.locator("#drawer")).to_be_visible()
    dash.click(LINK)
    dash.mouse.click(10, 400)  # the dark area, far from the player — and above a dimmed row
    expect(dash.locator("#trailer")).to_be_hidden()
    expect(dash.locator("#drawer")).to_be_visible()
    assert "Army of Shadows" in drawer_title(dash)  # the click did not fall through to the row beneath


def test_story_2_the_real_trailer_not_a_clip_not_a_review(dash: Page):
    # The choosing is `pick_youtube`'s (tests/unit/test_trailers.py, same story name): the page plays
    # the FIRST stored trailer and nothing else.
    open_film(dash, "Memories of Murder")
    dash.click(LINK)
    (player,) = wait_players(dash, 1)
    assert player["key"] == "mom00000001"
    expect(dash.locator("#trailer-caption")).to_contain_text("MEMORIES OF MURDER Trailer · YouTube")


def test_story_3_browsing_by_trailer_hands_on_the_keyboard(dash: Page):
    open_film(dash, "Army of Shadows")
    expect(dash.locator("#drawer .step-hint")).to_have_text("↑ ↓ previous / next film · T trailer")
    dash.keyboard.press("t")
    assert wait_players(dash, 1)[0]["key"] == "aos00000001"
    dash.keyboard.press("ArrowDown")  # ↑ ↓ do nothing while a trailer is up
    dash.wait_for_timeout(300)
    expect(dash.locator("#trailer")).to_be_visible()
    assert "Army of Shadows" in drawer_title(dash)
    dash.keyboard.press("Escape")
    dash.keyboard.press("ArrowDown")
    expect(dash.locator("#drawer h2")).to_contain_text("Pan's Labyrinth")
    dash.keyboard.press("T")
    assert wait_players(dash, 2)[1]["key"] == "pan00000001"
    dash.keyboard.press("Escape")
    dash.keyboard.press("ArrowDown")
    expect(dash.locator("#drawer h2")).to_contain_text("The Big Sleep")
    expect(dash.locator("#trailer")).to_be_hidden()


def test_story_3_t_is_a_letter_when_i_am_typing_and_nothing_without_a_drawer(dash: Page):
    dash.keyboard.press("t")  # no drawer open
    expect(dash.locator("#trailer")).to_be_hidden()
    open_film(dash, "Army of Shadows")
    dash.locator("#drawer input.rating").click()
    dash.keyboard.press("t")
    expect(dash.locator("#trailer")).to_be_hidden()
    dash.locator("#drawer h2").click()
    dash.keyboard.press("Meta+t")
    dash.keyboard.press("Control+t")
    expect(dash.locator("#trailer")).to_be_hidden()


def test_story_4_no_youtube_trailer_so_apples_preview_stands_in(dash: Page):
    open_film(dash, "To Die For")
    dash.click(LINK)
    video = dash.locator("#trailer-screen video")
    expect(video).to_have_attribute("src", f"{APPLE_HOST}/itunes-assets/tdf.m4v")
    assert video.evaluate("v => v.autoplay && v.controls")
    expect(dash.locator("#trailer-frame")).to_have_class("apple")  # a smaller window for a smaller picture
    expect(dash.locator("#trailer-caption")).to_contain_text("To Die For (1995)")
    expect(dash.locator("#trailer-caption")).to_contain_text("Apple's store preview")
    expect(dash.locator("#trailer-sources button")).to_have_count(0)  # nothing to switch to
    assert dash.evaluate("() => window.YT === undefined")  # YouTube was never even loaded
    dash.keyboard.press("Escape")
    expect(dash.locator("#trailer-screen video")).to_have_count(0)  # closing stops it


def test_story_5_the_link_is_where_i_expect_it_film_after_film(dash: Page):
    first = "#drawer p.links > :first-child"
    open_film(dash, "M")
    expect(dash.locator("#drawer p.links a.criterion-link")).to_have_count(1)
    expect(dash.locator(first)).to_have_text("▶ Trailer")
    dash.keyboard.press("Escape")
    open_film(dash, "The Big Sleep")  # owned: no ♡ Wishlist it
    expect(dash.locator("#drawer p.links .wish")).to_have_count(0)
    expect(dash.locator(first)).to_have_text("▶ Trailer")
    dash.keyboard.press("Escape")
    open_film(dash, "Army of Shadows")
    expect(dash.locator("#drawer p.links .wish-button")).to_have_count(1)
    expect(dash.locator(first)).to_have_text("▶ Trailer")
    links = dash.locator("#drawer p.links > *").all_inner_texts()
    assert [t.strip() for t in links] == ["▶ Trailer", "TMDB ↗", "CheapCharts ↗", "♡ Wishlist it"]


def test_story_5_a_film_with_both_offers_the_youtube_apple_switch(dash: Page):
    open_film(dash, "The Big Sleep")
    dash.click(LINK)
    wait_players(dash, 1)
    expect(dash.locator("#trailer-sources button")).to_have_text(["YouTube", "Apple"])
    expect(dash.locator("#trailer-sources button.on")).to_have_text("YouTube")
    dash.locator("#trailer-sources button", has_text="Apple").click()
    expect(dash.locator("#trailer-screen video")).to_have_attribute("src", f"{APPLE_HOST}/itunes-assets/tbs.m4v")
    expect(dash.locator("#trailer-sources button.on")).to_have_text("Apple")
    assert players(dash)[0]["destroyed"]
    dash.locator("#trailer-sources button", has_text="YouTube").click()
    assert wait_players(dash, 2)[1]["key"] == "tbs00000001"
    expect(dash.locator("#trailer-screen video")).to_have_count(0)


def test_story_6_the_awkward_one_no_trailer_anywhere(dash: Page):
    for title, year in (("The Hitch-Hiker", 1953), ("Never Asked", 1950)):  # looked up and empty · never looked up
        open_film(dash, title)
        expect(dash.locator(LINK)).to_have_count(0)
        search = dash.locator(SEARCH)
        expect(search).to_have_text("Find a trailer on YouTube ↗")
        expect(dash.locator("#drawer p.links > :first-child")).to_have_class("criterion trailer-search")
        query = f"{title} {year} trailer".replace(" ", "%20")
        expect(search).to_have_attribute("href", f"https://www.youtube.com/results?search_query={query}")
        expect(search).to_have_attribute("target", "_blank")
        dash.keyboard.press("t")  # nothing to play
        expect(dash.locator("#trailer")).to_be_hidden()
        dash.keyboard.press("Escape")


def test_story_7_youtube_says_no(dash: Page):
    open_film(dash, "Basic Instinct")
    dash.click(LINK)
    assert wait_players(dash, 1)[0]["key"] == "bas00000001"
    fail_player(dash, 0)  # embedding refused: the next trailer on the list
    second = wait_players(dash, 2)
    assert second[0]["destroyed"] and second[1]["key"] == "bas00000002"
    expect(dash.locator("#trailer-caption")).to_contain_text("Official Trailer · YouTube")
    fail_player(dash, 1, code=100)  # removed
    assert wait_players(dash, 3)[2]["key"] == "bas00000003"
    fail_player(dash, 2)
    expect(dash.locator("#trailer-screen video")).to_have_attribute("src", f"{APPLE_HOST}/itunes-assets/bas.m4v")
    expect(dash.locator("#trailer-caption")).to_contain_text("Apple's store preview")


def test_story_7_when_everything_fails_the_window_says_so(dash: Page):
    dash.unroute(f"{APPLE_HOST}/**")
    dash.route(f"{APPLE_HOST}/**", lambda route: route.abort())
    open_film(dash, "The Big Sleep")
    dash.click(LINK)
    wait_players(dash, 1)
    fail_player(dash, 0)
    sorry = dash.locator("#trailer-screen .trailer-sorry")
    expect(sorry).to_contain_text("This trailer won't play here.")
    expect(sorry.locator("a")).to_have_text("Find a trailer on YouTube ↗")
    expect(sorry.locator("a")).to_have_attribute(
        "href", "https://www.youtube.com/results?search_query=The%20Big%20Sleep%201946%20trailer"
    )
    dash.keyboard.press("Escape")
    expect(dash.locator("#trailer")).to_be_hidden()


def test_story_7_a_player_that_never_becomes_ready_is_given_up_on(dash: Page):
    # Seen in rehearsal: YouTube sat on a broken video and reported nothing. An advert plays AFTER
    # ready, so it cannot trip this.
    dash.evaluate("() => { window.__ytSilent = true; window.MB.trailer.readyMs = 150; }")
    open_film(dash, "Army of Shadows")
    dash.click(LINK)
    after = wait_players(dash, 2)
    assert [p["key"] for p in after] == ["aos00000001", "aos00000002"] and after[0]["destroyed"]


def test_story_7_a_ready_player_is_never_given_up_on(dash: Page):
    dash.evaluate("() => { window.MB.trailer.readyMs = 150; }")
    open_film(dash, "Army of Shadows")
    dash.click(LINK)
    wait_players(dash, 1)
    dash.wait_for_timeout(500)
    assert len(players(dash)) == 1


def test_story_7_youtube_itself_unreachable_goes_straight_to_apple(dash: Page):
    dash.unroute(YT_API)
    dash.route(YT_API, lambda route: route.abort())
    open_film(dash, "The Big Sleep")
    dash.click(LINK)
    expect(dash.locator("#trailer-screen video")).to_have_attribute("src", f"{APPLE_HOST}/itunes-assets/tbs.m4v")


# ---- the brief's named defaults ----


def test_t_right_after_a_step_never_plays_the_previous_films_trailer(dash: Page):
    # ↓ moves the white row at once; the new film's details (and trailers) arrive later.
    open_film(dash, "Army of Shadows")
    pan = dash.locator("#films tbody tr[data-id]", has_text="Pan's Labyrinth").get_attribute("data-id")

    dash.evaluate(
        """pan => { const f = window.fetch; window.fetch = (u, o) => String(u).endsWith('/api/films/' + pan)
            ? new Promise((r) => setTimeout(() => r(f(u, o)), 600)) : f(u, o); }""",
        pan,
    )
    dash.keyboard.press("ArrowDown")
    dash.keyboard.press("t")
    assert dash.locator("#trailer").is_hidden()  # not a retrying expect: the redraw would close it and hide the bug
    expect(dash.locator("#drawer h2")).to_contain_text("Pan's Labyrinth")
    dash.keyboard.press("t")
    assert [p["key"] for p in wait_players(dash, 1)] == ["pan00000001"]


def test_apple_failing_after_a_hand_made_switch_goes_back_to_youtube(dash: Page):
    dash.unroute(f"{APPLE_HOST}/**")
    dash.route(f"{APPLE_HOST}/**", lambda route: route.abort())
    open_film(dash, "The Big Sleep")
    dash.click(LINK)
    wait_players(dash, 1)
    dash.locator("#trailer-sources button", has_text="Apple").click()
    assert wait_players(dash, 2)[1]["key"] == "tbs00000001"  # not "won't play here": YouTube works
    expect(dash.locator("#trailer-sources button")).to_have_count(0)  # Apple is known dead: nothing to switch to


def test_a_youtube_script_that_never_gets_going_skips_every_youtube_trailer(dash: Page):
    dash.unroute(YT_API)
    dash.route(YT_API, lambda route: route.fulfill(content_type="text/javascript", body="/* the loader arrived, the player script never does */"))
    dash.evaluate("() => { window.MB.trailer.readyMs = 150; }")
    open_film(dash, "Basic Instinct")  # three YouTube trailers: one wait, not three
    dash.click(LINK)
    expect(dash.locator("#trailer-screen video")).to_have_attribute("src", f"{APPLE_HOST}/itunes-assets/bas.m4v")


def test_closing_the_trailer_cancels_what_was_pending(dash: Page):
    dash.evaluate("() => { window.__ytSilent = true; window.MB.trailer.readyMs = 150; }")
    open_film(dash, "Army of Shadows")
    dash.click(LINK)
    wait_players(dash, 1)
    dash.keyboard.press("Escape")
    dash.wait_for_timeout(400)
    assert len(players(dash)) == 1  # the give-up timer died with the window
    expect(dash.locator("#trailer")).to_be_hidden()


def test_back_while_a_trailer_is_up_closes_it_with_the_drawer(dash: Page):
    open_film(dash, "Army of Shadows")
    dash.click(LINK)
    wait_players(dash, 1)
    dash.go_back()
    expect(dash.locator("#drawer")).to_be_hidden()
    expect(dash.locator("#trailer")).to_be_hidden()
    assert players(dash)[0]["destroyed"]


def test_the_dashboard_never_loads_youtube_until_a_trailer_is_asked_for(dash: Page):
    open_film(dash, "Army of Shadows")
    assert dash.evaluate("() => window.YT === undefined && !document.querySelector('script[src*=\"youtube\"]')")


def test_a_long_title_does_not_run_under_the_longer_hint(dash: Page):
    open_film(dash, "Memories of Murder")
    h2 = dash.locator("#drawer h2")
    h2.evaluate("el => { el.firstChild.textContent = 'A Very Long Title That Would Otherwise Run Right Under The Hint '.repeat(3); }")
    text_right = h2.evaluate("el => { const r = document.createRange(); r.selectNodeContents(el); return Math.max(...[...r.getClientRects()].map(b => b.right)); }")
    hint = dash.locator("#drawer .step-hint").bounding_box()
    assert hint is not None and text_right <= hint["x"]
