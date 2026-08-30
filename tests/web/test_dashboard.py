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

from movie_brain.domain.models import Film, ListEntry, ListMeta, OmdbRating
from movie_brain.infrastructure.database import Repository
from movie_brain.web.app import create_app


def count(page: Page) -> int:
    return int(page.locator("#films tbody").get_attribute("data-count"))


def first_titles(page: Page, n: int) -> list[str]:
    return page.locator("#films tbody tr .c-title a").all_inner_texts()[:n]


def set_langs(page: Page, langs: list[str]) -> None:
    """Open the language dropdown, check exactly `langs`, close the panel."""
    page.click("#f-lang-input")
    if not langs:
        page.locator("#f-lang-any").check()
    else:
        for cb in page.locator("#f-lang-panel input[type=checkbox]:not(#f-lang-any)").all():
            if (cb.get_attribute("value") in langs) != cb.is_checked():
                cb.click()
    page.click("header h1")


def clear_lang(page: Page) -> None:
    set_langs(page, [])


def test_language_filter_defaults_to_english(dash: Page):
    expect(dash.locator("#f-lang-input")).to_have_value("English")
    assert count(dash) == 2  # Alpha (English), Echo (English, Spanish)
    assert first_titles(dash, 2) == ["Alpha", "Echo"]
    assert "lang=" not in dash.url  # the default is implicit, not encoded
    set_langs(dash, ["Spanish"])
    assert count(dash) == 1
    assert "lang=Spanish" in dash.url
    dash.goto(dash.url)
    dash.wait_for_selector("#films tbody[data-count]")
    expect(dash.locator("#f-lang-input")).to_have_value("Spanish")
    assert count(dash) == 1
    clear_lang(dash)
    expect(dash.locator("#f-lang-input")).to_have_value("Any")
    assert count(dash) == 7  # + buyable discovery film Hotel
    assert "lang=any" in dash.url


def test_english_heads_the_list_then_any_language(dash: Page):
    dash.click("#f-lang-input")
    labels = [t.strip() for t in dash.locator("#f-lang-panel label").all_inner_texts()]
    assert labels[0] == "English"
    assert labels[1] == "Any language"
    assert labels[2:] == sorted(labels[2:]) and "English" not in labels[2:]
    expect(dash.locator("#f-lang-any")).not_to_be_checked()  # English is the default selection
    dash.locator("#f-lang-any").check()  # picking Any clears every language
    assert count(dash) == 7
    dash.click("header h1")  # close the panel so the input shows the selection again
    expect(dash.locator("#f-lang-input")).to_have_value("Any")
    dash.click("#f-lang-input")  # reopen
    expect(dash.locator("#f-lang-panel input[type=checkbox]:not(#f-lang-any):checked")).to_have_count(0)
    dash.locator('#f-lang-panel input[value="French"]').check()  # picking a language unchecks Any
    expect(dash.locator("#f-lang-any")).not_to_be_checked()
    assert count(dash) == 1  # Bravo


def test_language_typeahead_filters_options_and_builds_up_selection(dash: Page):
    inp = dash.locator("#f-lang-input")
    expect(inp).to_have_value("English")  # default selection shown while closed
    inp.click()  # focusing opens the panel and clears the box for typing
    expect(dash.locator("#f-lang-panel")).to_be_visible()
    expect(inp).to_have_value("")
    inp.fill("spa")  # case-insensitive fragment → only Spanish remains
    visible = [t.strip() for t in dash.locator("#f-lang-panel label:visible").all_inner_texts()]
    assert visible == ["Spanish"]
    dash.locator('#f-lang-panel input[value="Spanish"]').check()
    expect(dash.locator("#f-lang-panel")).to_be_visible()  # stays open for the next language
    expect(inp).to_have_value("")  # search cleared, ready to type again
    inp.fill("FRE")
    dash.locator('#f-lang-panel input[value="French"]').check()
    dash.click("header h1")  # close
    expect(inp).to_have_value("English, Spanish, French")  # builds up in selection order
    assert count(dash) == 3  # Alpha + Echo (English/Spanish) + Bravo (French)
    dash.goto(dash.url)  # selection round-trips through the URL
    dash.wait_for_selector("#films tbody[data-count]")
    expect(dash.locator("#f-lang-input")).to_have_value("English, Spanish, French")
    assert count(dash) == 3


def test_rating_columns_show_metacritic_then_rt_then_imdb(dash: Page):
    cols = [th.get_attribute("data-col") for th in dash.locator("thead tr.labels th.sortable").all()]
    assert cols == ["title", "year", "director", "language", "metacritic", "rt", "imdb", "my_rating"]
    row = dash.locator("#films tbody tr[data-id]").filter(has_text="Alpha")
    expect(row.locator(".c-metacritic")).to_have_text("92")
    expect(row.locator(".c-rt")).to_have_text("95%")
    expect(row.locator(".c-imdb")).to_have_text("8.5")


def test_default_sort_hierarchy_metacritic_then_rt_then_imdb_then_title(dash: Page):
    clear_lang(dash)
    assert count(dash) == 7
    # mc desc: Alpha 92, then the Echo/Bravo mc-70 tie breaks on rt (60 vs 50, against title
    # order); missing values sort after present ones at each level, so imdb-only Foxtrot
    # follows, then the unrated Charlie/Delta by title.
    assert first_titles(dash, 6) == ["Alpha", "Echo", "Bravo", "Foxtrot", "Charlie", "Delta"]
    expect(dash.locator("#count-films")).to_have_text("6")
    expect(dash.locator("#count-showing")).to_have_text("Showing 7 of 7")  # reachable: 6 Criterion + buyable Hotel; Golf excluded
    expect(dash.locator("#films tbody tr").first.locator(".c-title a")).to_have_attribute("href", "https://c/alpha")


def test_chip_labels_and_order(dash: Page):
    labels = [t.strip() for t in dash.locator("#chips .chip").all_inner_texts()]
    assert labels == [
        "Reachable",
        "Top Ratings",
        "Unrated by me",
        "My ratings",
        "Leaving soon",
        "Recently added",
        "Pending",
        "Departed",
        "New arrivals",
        "Watchlist",
        "Owned",
        "Not owned",
        "Needs revisit",
        "Suspect",
        "On a list",
        "Canon, not owned",
        "Clear",
    ]


def test_chips_stack_with_and(dash: Page):
    clear_lang(dash)
    dash.click(".chip[data-chip=unrated]")
    assert count(dash) == 4  # Bravo, Charlie, Delta, Hotel
    dash.click(".chip[data-chip=pending]")
    assert count(dash) == 2  # Charlie (unmatched), Delta (pending)
    expect(dash.locator(".chip[data-chip=unrated]")).to_have_class(re.compile("active"))
    dash.click("#chips-clear")
    assert count(dash) == 7


def test_each_chip_alone(dash: Page):
    clear_lang(dash)
    expected = {
        "leaving": 1,
        "unrated": 4,  # Bravo, Charlie, Delta, Hotel
        "mine": 2,
        "pending": 2,
        "top_ratings": 1,  # only Alpha (92 / 95% / 8.5) clears any threshold
        "recent": 1,
        "departed": 1,
        "suspect": 2,  # Bravo, Echo
    }
    for chip, n in expected.items():
        dash.click(f".chip[data-chip={chip}]")
        assert count(dash) == n, chip
        dash.click(f".chip[data-chip={chip}]")


def test_departed_film_is_marked_in_table_and_counts(dash: Page):
    clear_lang(dash)
    row = dash.locator("#films tbody tr[data-id]").filter(has_text="Foxtrot")
    expect(row).to_have_class(re.compile("departed"))
    expect(row.locator(".c-title")).to_contain_text("gone")
    expect(dash.locator("#count-departed")).to_have_text("1")


def test_departed_chip_filters_to_departed_films(dash: Page):
    clear_lang(dash)
    dash.click(".chip[data-chip=departed]")
    assert count(dash) == 1
    assert first_titles(dash, 1) == ["Foxtrot"]
    dash.click("#chips-clear")


def test_sort_cycles_and_keeps_nulls_last(dash: Page):
    clear_lang(dash)
    dash.click("th.sortable[data-col=rt]")
    assert first_titles(dash, 5) == ["Bravo", "Echo", "Alpha", "Charlie", "Delta"]  # asc: 50, 60, 95, then nulls
    expect(dash.locator("th.sortable[data-col=rt]")).to_have_attribute("data-dir", "asc")
    dash.click("th.sortable[data-col=rt]")
    assert first_titles(dash, 2) == ["Alpha", "Echo"]
    dash.click("th.sortable[data-col=rt]")
    assert first_titles(dash, 2) == ["Alpha", "Echo"]  # back to default metacritic desc
    expect(dash.locator("th.sortable[data-col=rt]")).not_to_have_attribute("data-dir", re.compile(".+"))


def test_column_filters_combine_with_chips(dash: Page):
    clear_lang(dash)
    dash.fill("#f-director", "ann")
    assert count(dash) == 2  # Alpha, Echo
    dash.click(".chip[data-chip=mine]")
    assert count(dash) == 1  # Alpha (rated 9); Echo's 0 doesn't count as mine
    assert first_titles(dash, 1) == ["Alpha"]
    dash.click(".chip[data-chip=mine]")
    dash.fill("#f-director", "")
    set_langs(dash, ["Spanish"])
    assert count(dash) == 1
    clear_lang(dash)
    dash.fill("#f-imdb-min", "7")
    assert count(dash) == 2  # Alpha 8.5, Echo 7.0; nulls excluded
    dash.fill("#f-year-max", "1955")
    assert count(dash) == 1
    dash.fill("#f-imdb-min", "")
    dash.fill("#f-year-max", "")
    dash.fill("#f-mc-min", "72")
    assert count(dash) == 1  # Alpha 88; Echo 70 misses, nulls excluded
    dash.fill("#f-mc-min", "")


def test_url_state_round_trips(dash: Page, server: str):
    clear_lang(dash)
    dash.click(".chip[data-chip=unrated]")
    dash.fill("#f-title", "a")
    dash.click("th.sortable[data-col=year]")
    url = dash.url
    assert "chips=unrated" in url and "title=a" in url and "lang=any" in url
    assert ("sort=year%3Aasc" in url) or ("sort=year:asc" in url)
    dash.goto(url)
    dash.wait_for_selector("#films tbody[data-count]")
    expect(dash.locator(".chip[data-chip=unrated]")).to_have_class(re.compile("active"))
    expect(dash.locator("#f-title")).to_have_value("a")
    expect(dash.locator("#f-lang-input")).to_have_value("Any")
    expect(dash.locator("th.sortable[data-col=year]")).to_have_attribute("data-dir", "asc")
    assert count(dash) == 3  # Bravo, Charlie, Delta contain "a"


def test_drawer_opens_from_info_button_and_restores_url(dash: Page):
    dash.click("#films tbody tr[data-id] .info >> nth=0")
    drawer = dash.locator("#drawer")
    expect(drawer).to_be_visible()
    expect(drawer.locator("h2")).to_have_text("Alpha ☆⚐")  # star + flag buttons: Alpha isn't watchlisted/flagged
    expect(drawer.locator("pre.raw")).to_contain_text('"Plot": "A plot."')
    expect(drawer.locator("a.criterion:not(.owned-link):not(.cheapcharts-link)")).to_have_attribute(
        "href", "https://c/alpha"
    )
    expect(drawer.locator("div.meta")).not_to_contain_text("Leaving")  # moved to the bottom
    expect(drawer.locator("#drawer-body > :last-child")).to_have_text("Leaving August 31")
    assert "film=" in dash.url
    dash.keyboard.press("Escape")
    expect(drawer).to_be_hidden()
    assert "film=" not in dash.url


def test_drawer_poster_sits_below_meta_top_aligned_with_plot(dash: Page):
    dash.click("#films tbody tr[data-id] .info >> nth=0")  # Alpha, the seeded film with a poster
    drawer = dash.locator("#drawer")
    expect(drawer).to_be_visible()
    poster = drawer.locator("img.poster")
    expect(poster).to_be_visible()
    meta = drawer.locator("div.meta").bounding_box()
    plot = drawer.locator("#drawer-body p").first.bounding_box()
    box = poster.bounding_box()
    assert box["y"] >= meta["y"] + meta["height"]  # below the "year · director" line
    assert abs(box["y"] - plot["y"]) <= 1  # top edge aligned with the description text
    assert box["x"] > plot["x"] + plot["width"] - 220  # on the right side (max-width 200 + margin)
    dash.keyboard.press("Escape")


def test_drawer_opens_on_load_from_url(dash: Page, server: str):
    fid = dash.locator("#films tbody tr[data-id]").first.get_attribute("data-id")
    dash.goto(f"{server}/?film={fid}")
    expect(dash.locator("#drawer h2")).to_have_text("Alpha ☆⚐")
    dash.click("#drawer-backdrop", position={"x": 10, "y": 10})
    expect(dash.locator("#drawer")).to_be_hidden()


def test_row_click_opens_drawer_but_title_link_does_not(dash: Page):
    dash.click("#films tbody tr[data-id] .c-year >> nth=1")
    expect(dash.locator("#drawer h2")).to_have_text("Echo ☆⚐")
    dash.click("#drawer-close")
    expect(dash.locator("#drawer")).to_be_hidden()


def test_rating_round_trip_updates_counts_and_persists(dash: Page, server: str):
    clear_lang(dash)
    row = dash.locator("#films tbody tr[data-id]").filter(has_text="Bravo")
    expect(dash.locator("#count-mine")).to_have_text("3")
    row.locator("input.rating").fill("7")
    row.locator("input.rating").press("Enter")
    expect(dash.locator("#count-mine")).to_have_text("4")
    dash.reload()
    dash.wait_for_selector("#films tbody[data-count]")
    clear_lang(dash)  # reload restores the English default, which hides Bravo
    expect(dash.locator("#films tbody tr[data-id]").filter(has_text="Bravo").locator("input.rating")).to_have_value("7")
    # blank un-rates
    row = dash.locator("#films tbody tr[data-id]").filter(has_text="Bravo")
    row.locator("input.rating").fill("")
    row.locator("input.rating").press("Enter")
    expect(dash.locator("#count-mine")).to_have_text("3")


def test_invalid_rating_reverts(dash: Page):
    row = dash.locator("#films tbody tr[data-id]").filter(has_text="Alpha")
    inp = row.locator("input.rating")
    inp.fill("12")
    inp.press("Enter")
    expect(inp).to_have_value("9")
    expect(dash.locator("#count-mine")).to_have_text("3")


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
    expect(dash.locator("#drawer h2")).to_have_text("Echo ☆⚐")
    dash.wait_for_timeout(400)  # let the superseded, slow Alpha response land and confirm it's a no-op
    expect(dash.locator("#drawer h2")).to_have_text("Echo ☆⚐")


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


# ---- acquire chip: another separate repo/server/page so the shared seed above (whose acquire
# results none of the tests below examine) stays untouched. ----

ACQUIRE_TODAY = date(2026, 8, 19)


def seed_acquire(repo: Repository) -> None:
    # Yankee and Xray: unowned, unrated, no listings anywhere (unreachable discovery films),
    # both on one ordered 3-entry list at ranks 1 and 3 — Yankee's #1 gives it the higher
    # canonScore (10.0 vs 3.33), proving the tier-1 canon-score-desc ordering.
    yankee = repo.create_film(Film("Yankee", 2001, "Yolanda", ""))
    xray = repo.create_film(Film("Xray", 2002, "Xena", ""))
    assert yankee is not None and xray is not None
    # Whiskey: same list (rank 2, so it scores BETWEEN Yankee and Xray) and currently on the
    # Criterion Channel — proves a current Criterion listing no longer suppresses the chip
    # (D1, reversed): streaming availability is not a reason to hide a canon film.
    repo.record_catalog("criterion", [Film("Whiskey", 2003, "Walt", "https://c/whiskey")], ACQUIRE_TODAY)
    whiskey = repo.film_id_by_key("whiskey (2003)")
    assert whiskey is not None
    # Zulu: unowned, unrated, no listing, no list membership at all — qualifies for the chip on
    # Metacritic alone (91 >= top_mc). Tier 1 (on a list) must still outrank tier 2
    # (Metacritic-only) even though Zulu's raw Metascore (91) dwarfs Xray's canon_score (3.33) —
    # this is the ordering check the tier-then-canon_score `compare()` clause promises.
    zulu = repo.create_film(Film("Zulu", 2004, "Zora", ""))
    assert zulu is not None
    repo.upsert_omdb(zulu, OmdbRating(8.0, 90, True, "English", '{"Title":"Zulu"}', metacritic=91), ACQUIRE_TODAY)

    # Victor: unowned, unrated, no listing, no Metacritic — its ONLY qualification for the chip
    # is membership on a list whose trust the owner has set to 0 ("visible, scores nothing"),
    # so canon_score(Victor) == 0.0, exactly TIED with canon_score(Zulu) == 0.0 (Zulu carries no
    # list at all). A score-only comparator would leave this tie to the metacritic/rt/imdb
    # fallback below, where Zulu's 91 would wrongly sort it ahead of listless Victor — only the
    # tier check (isCanon) breaks the tie correctly in Victor's favor.
    victor = repo.create_film(Film("Victor", 2005, "Vera", ""))
    assert victor is not None

    meta = ListMeta("acquire-test", "Acquire Test List", None, None, None, True)
    repo.upsert_film_list(meta, ACQUIRE_TODAY)
    repo.upsert_list_entry("acquire-test", ListEntry(1, "Yankee", "Yolanda"))
    repo.link_list_entry("acquire-test", 1, yankee)
    repo.upsert_list_entry("acquire-test", ListEntry(2, "Whiskey", "Walt"))
    repo.link_list_entry("acquire-test", 2, whiskey)
    repo.upsert_list_entry("acquire-test", ListEntry(3, "Xray", "Xena"))
    repo.link_list_entry("acquire-test", 3, xray)
    repo.set_list_trust("acquire-test", 10)

    victor_meta = ListMeta("victor-test", "Victor Test List", None, None, None, True)
    repo.upsert_film_list(victor_meta, ACQUIRE_TODAY)
    repo.upsert_list_entry("victor-test", ListEntry(1, "Victor", "Vera"))
    repo.link_list_entry("victor-test", 1, victor)
    repo.set_list_trust("victor-test", 0)


@pytest.fixture
def acquire_server() -> Generator[str, None, None]:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    with tempfile.TemporaryDirectory() as tmp:
        repo = Repository(Path(tmp) / "acquire-movie-brain.db")
        seed_acquire(repo)
        app = create_app(repo, today=lambda: ACQUIRE_TODAY)
        threading.Thread(target=lambda: app.run(host="127.0.0.1", port=port, use_reloader=False), daemon=True).start()
        time.sleep(0.5)
        yield f"http://127.0.0.1:{port}"


@pytest.fixture
def acquire_dash(page: Page, acquire_server: str) -> Page:
    # scope=all: none of these films are "reachable" (list membership alone doesn't count),
    # and lang=any: none carry OMDb language metadata, so the default English filter would
    # hide every one of them.
    page.goto(f"{acquire_server}/?scope=all&lang=any")
    page.wait_for_selector("#films tbody[data-count]")
    return page


def test_acquire_chip_shows_canon_film_with_no_subscribed_listing(acquire_dash: Page):
    acquire_dash.click('.chip[data-chip="acquire"]')
    assert acquire_dash.locator("tr[data-id]", has_text="Yankee").count() == 1


def test_acquire_chip_includes_film_currently_on_criterion(acquire_dash: Page):
    acquire_dash.click('.chip[data-chip="acquire"]')
    assert count(acquire_dash) == 5  # Yankee, Whiskey, Xray, Victor, Zulu — all unowned and canon-adjacent
    assert acquire_dash.locator("tr[data-id]", has_text="Whiskey").count() == 1


def test_acquire_chip_orders_by_canon_score_desc(acquire_dash: Page):
    # Yankee/Xray have no listing anywhere, so `f.url` is None and `.c-title` renders no <a>
    # (first_titles assumes one) — read the plain title text instead.
    acquire_dash.click('.chip[data-chip="acquire"]')
    titles = [t.split(" ")[0] for t in acquire_dash.locator("#films tbody tr .c-title").all_inner_texts()[:3]]
    assert titles == ["Yankee", "Whiskey", "Xray"]  # #1/3 (10.0), #2/3 (6.67), #3/3 (3.33)


def test_acquire_chip_tier_1_outranks_tier_2_even_with_a_lower_raw_score(acquire_dash: Page):
    # Zulu is Metacritic-only (91, no list membership) — its raw score dwarfs Xray's
    # canon_score (3.33), but tier 1 (on a curated list) must still sort above tier 2
    # (Metacritic-only) per the spec: on-a-list beats Metacritic-only, full stop. Victor sits
    # on a trust-0 list, so canon_score(Victor) == 0.0 exactly TIES canon_score(Zulu) == 0.0 —
    # only the tier check (not a score-magnitude comparison) can break that tie correctly, so
    # this also proves the tier check is load-bearing, not merely a shortcut a nonneg
    # canon_score comparison would already have produced on its own.
    acquire_dash.click('.chip[data-chip="acquire"]')
    titles = [t.split(" ")[0] for t in acquire_dash.locator("#films tbody tr .c-title").all_inner_texts()]
    assert titles == ["Yankee", "Whiskey", "Xray", "Victor", "Zulu"]


def test_drawer_shows_also_streaming(dash):
    dash.locator("tbody tr", has_text="Alpha").first.click()
    expect(dash.locator("#drawer-body")).to_contain_text("Also streaming on: HBO Max, MUBI (not subscribed)")


def test_drawer_without_services_hides_the_line(dash):
    # Echo, not Bravo: Bravo now carries five services to exercise the overflow disclosure.
    dash.locator("tbody tr", has_text="Echo").first.click()
    body = dash.locator("#drawer-body")
    # Wait for the drawer to actually POPULATE before asserting an absence. A negative
    # Playwright assertion passes the instant it holds, so on an empty drawer it passes
    # before the fetch returns — which would make this test green no matter what renders.
    expect(body).to_contain_text("Echo")
    expect(body).not_to_contain_text("Also streaming on")


def test_drawer_collapses_services_past_the_cap(dash):
    """Five svod services, ranked: the best three show, the rest hide behind a disclosure."""
    clear_lang(dash)  # Bravo is French; the default English filter hides its row
    dash.locator("tbody tr", has_text="Bravo").first.click()
    body = dash.locator("#drawer-body")
    expect(body).to_contain_text("Also streaming on: Apple TV+, HBO Max, Peacock")
    expect(body.locator(".svc-more summary")).to_have_text("⋯ 2 more")
    # Collapsed by default. The overflow names are in the DOM either way — a closed <details>
    # still holds its text — so this asserts VISIBILITY, which is the thing that matters.
    expect(body.locator(".svc-rest")).not_to_be_visible()
    body.locator(".svc-more summary").click()
    expect(body.locator(".svc-rest")).to_be_visible()
    expect(body.locator(".svc-rest")).to_contain_text("MUBI (not subscribed)")


def test_drawer_names_the_best_source(dash: Page):
    # Bravo is UNOWNED and carries five svod services, all subscribed except MUBI, all at the
    # default quality — so the name tiebreak picks Apple TV+. Named here so the assertion
    # proves the real ranking rather than merely that some line rendered. Alpha can no longer
    # serve this test: it is the seed's owned film, and possession short-circuits the ranking.
    clear_lang(dash)  # Bravo is French; the default English filter hides its row
    dash.locator("tbody tr", has_text="Bravo").first.click()
    expect(dash.locator("#drawer .best-source")).to_contain_text("Best source: Apple TV+")


def test_an_owned_film_answers_with_the_store_it_was_bought_from(dash: Page):
    """Possession short-circuits the ranking: Alpha streams on Criterion and HBO Max, and
    still answers iTunes, because the owner already has it."""
    dash.locator("tbody tr", has_text="Alpha").first.click()
    expect(dash.locator("#drawer .best-source")).to_contain_text("Best source: Apple TV Store (iTunes)")


def test_a_reachable_film_carries_a_watch_badge(dash: Page):
    clear_lang(dash)
    row = dash.locator('tr[data-id]', has_text="Bravo")
    expect(row.locator(".badge-watch")).to_have_text("Apple TV+")


def test_row_badges_read_lists_then_owned(dash: Page):
    """Owner preference (2026-08-29): the list tally comes BEFORE the owned flag. Alpha carries
    both, so the order is observable — asserted on rendered text, since each badge's own
    presence is already covered elsewhere and only the SEQUENCE is at stake here."""
    row = dash.locator('tr[data-id]', has_text="Alpha").locator("td.c-title")
    text = row.inner_text()
    assert text.index("3 lists") < text.index("owned"), text


def test_an_owned_row_is_not_badged_with_its_source(dash: Page):
    """The row already says "owned"; badging the purchase again states it twice."""
    row = dash.locator('tr[data-id]', has_text="Alpha")
    expect(row.locator(".badge-owned")).to_be_visible()
    expect(row.locator(".badge-watch")).to_have_count(0)


def test_empty_db_shows_import_hint(empty_dash: Page):
    assert count(empty_dash) == 0
    expect(empty_dash.locator("#films tbody")).to_contain_text("movie-brain import-legacy")
    expect(empty_dash.locator("#films tbody")).to_contain_text("movie-brain sync")
    expect(empty_dash.locator("tr.empty-state")).to_be_visible()


def test_new_arrivals_chip_filters_to_alpha(dash):
    dash.click('button[data-chip="new_arrivals"]')
    dash.wait_for_selector('#films tbody[data-count="1"]')
    assert dash.locator("#films tbody tr").first.inner_text().startswith("Alpha")


def test_watchlist_chip_filters_to_bravo(dash):
    clear_lang(dash)  # Bravo is French; the default English filter would hide its row
    dash.click('button[data-chip="watchlist"]')
    dash.wait_for_selector('#films tbody[data-count="1"]')
    assert dash.locator("#films tbody tr").first.inner_text().startswith("Bravo")


def test_drawer_shows_new_on_line(dash):
    dash.locator("#films tbody tr", has_text="Alpha").first.click()
    dash.wait_for_selector("#drawer:not([hidden])")
    assert "New on" in dash.locator("#drawer-body").inner_text()


def test_drawer_shows_on_lists_line(dash):
    # Alpha is on three lists at unequal trust (backlog-10 7, sight-sound-2022 5, cahiers-100
    # the default 1) — the line leads with Backlog Ten, not the alphabetically-first Cahiers,
    # because it orders by trust descending. See test_drawer_on_lists_line_orders_by_trust for
    # the full-order assertion; this one is deliberately updated from its earlier
    # name-order-only expectation.
    dash.locator("#films tbody tr", has_text="Alpha").first.click()
    dash.wait_for_selector("#drawer:not([hidden])")
    expect(dash.locator("#drawer-body")).to_contain_text("On lists: Backlog Ten")


def test_drawer_on_lists_line_orders_by_trust_descending(dash):
    # Trust order (backlog-10 7, sight-sound-2022 5, cahiers-100 1) disagrees with name order
    # (cahiers-100's "100 Films..." would sort first alphabetically) — this is the only seed
    # arrangement that lets the rendered page prove trust-desc ordering rather than a name
    # fallback that happens to look the same.
    dash.locator("#films tbody tr", has_text="Alpha").first.click()
    dash.wait_for_selector("#drawer:not([hidden])")
    expect(dash.locator("#drawer-body")).to_contain_text(
        "On lists: Backlog Ten, Sight & Sound 2022 #2, Cahiers du Cinéma 2008 #3"
    )


def test_drawer_without_lists_hides_the_line(dash):
    clear_lang(dash)  # Bravo is French; the default English filter hides its row
    dash.locator("tbody tr", has_text="Bravo").first.click()
    expect(dash.locator("#drawer-body")).not_to_contain_text("On lists")


def test_drawer_shows_unordered_list_without_rank(dash):
    dash.locator("#films tbody tr", has_text="Echo").first.click()
    dash.wait_for_selector("#drawer:not([hidden])")
    expect(dash.locator("#drawer-body")).to_contain_text("On lists: Backlog Ten")
    expect(dash.locator("#drawer-body")).not_to_contain_text("Backlog Ten #5")


def test_card_badge_shows_lists_count(dash):
    # Alpha is on three seeded lists (cahiers-100, backlog-10, sight-sound-2022).
    row = dash.locator("#films tbody tr[data-id]", has_text="Alpha")
    expect(row.locator(".badge-lists")).to_have_text("3 lists")


def test_card_badge_absent_when_no_lists(dash):
    clear_lang(dash)  # Bravo is French; the default English filter would hide its row
    row = dash.locator("#films tbody tr[data-id]", has_text="Bravo")
    expect(row.locator(".badge-lists")).to_have_count(0)


def test_card_badge_shows_singular_for_one_list(dash):
    # Echo is on exactly one list (backlog-10) — pins the "1 list" singular against a
    # regression to "1 lists".
    row = dash.locator("#films tbody tr[data-id]", has_text="Echo")
    expect(row.locator(".badge-lists")).to_have_text("1 list")


def test_on_a_list_chip_keeps_films_on_a_single_list(dash):
    # Alpha is on three lists, Echo and Charlie on one each. A single-list film must survive the
    # chip — that is the whole difference from the old "on 2+ lists" behaviour, which kept Alpha
    # alone. clear_lang because Charlie has no language on file.
    clear_lang(dash)
    dash.click('button[data-chip="multi_list"]')
    dash.wait_for_selector('#films tbody[data-count="3"]')
    # A row's first cell carries badges after the title ("Alpha 3 lists owned"), so compare the
    # leading word rather than the whole cell.
    rows = dash.locator("#films tbody tr").all_inner_texts()
    assert sorted(r.split()[0] for r in rows) == ["Alpha", "Charlie", "Echo"]


def test_drawer_shows_tied_rank_label_not_position(dash):
    clear_lang(dash)  # Charlie has no language on file; the default English filter would hide its row
    dash.locator("#films tbody tr", has_text="Charlie").first.click()
    dash.wait_for_selector("#drawer:not([hidden])")
    expect(dash.locator("#drawer-body")).to_contain_text("On lists: Sight & Sound 2022 #243")
    expect(dash.locator("#drawer-body")).not_to_contain_text("Sight & Sound 2022 #1")


def test_default_scope_is_reachable_hides_unreachable_discovery(dash):
    clear_lang(dash)  # Hotel is Hungarian
    assert dash.locator("tr[data-id]", has_text="Golf").count() == 0  # no listing, unowned, unrated
    assert dash.locator("tr[data-id]", has_text="Hotel").count() == 1  # buyable on the Apple TV store
    expect(dash.locator("#scope-toggle")).to_have_text("Reachable")


def test_criterion_scope_hides_buyable_discovery(page, server):
    page.goto(f"{server}/?scope=criterion&lang=any")
    page.wait_for_selector("#films tbody[data-count]")
    assert page.locator("tr[data-id]", has_text="Hotel").count() == 0
    expect(page.locator("#scope-toggle")).to_have_text("Criterion only")


def test_all_scope_reveals_discovery(page, server):
    page.goto(f"{server}/?scope=all&lang=any")
    page.wait_for_selector("#films tbody[data-count]")
    assert page.locator("tr[data-id]", has_text="Golf").count() == 1
    expect(page.locator("#scope-toggle")).to_have_text("All films")


def test_scope_toggle_cycles_reachable_criterion_all(dash):
    toggle = dash.locator("#scope-toggle")
    toggle.click()
    expect(toggle).to_have_text("Criterion only")
    assert "scope=criterion" in dash.url
    toggle.click()
    expect(toggle).to_have_text("All films")
    assert "scope=all" in dash.url
    toggle.click()
    expect(toggle).to_have_text("Reachable")
    assert "scope=" not in dash.url


def test_drawer_shows_buy_on_and_cheapcharts_link(dash):
    clear_lang(dash)  # Hotel is Hungarian
    dash.locator("tbody tr", has_text="Hotel").first.click()
    body = dash.locator("#drawer-body")
    expect(body).to_contain_text("Buy on: Apple TV Store (iTunes)")
    expect(body).not_to_contain_text("Also streaming on")
    expect(body.locator("a.cheapcharts-link")).to_have_attribute(
        "href", "https://www.cheapcharts.com/us/search;q=Hotel;t=all"  # matrix params — `?q=` is ignored by the site
    )


def test_drawer_without_store_listing_has_no_cheapcharts_link(dash):
    clear_lang(dash)
    dash.locator("tbody tr", has_text="Bravo").first.click()
    dash.wait_for_selector("#drawer:not([hidden])")
    assert dash.locator("#drawer-body a.cheapcharts-link").count() == 0


def test_drawer_star_toggles_watchlist(dash):
    clear_lang(dash)  # Charlie has no language on file; the default English filter would hide its row
    dash.locator("#films tbody tr", has_text="Charlie").first.click()
    dash.wait_for_selector("#drawer:not([hidden])")
    star = dash.locator(".watch-toggle")
    assert star.inner_text() == "☆"
    star.click()
    dash.wait_for_selector('.watch-toggle:has-text("★")')
    star.click()  # leave the session-scoped seed as we found it
    dash.wait_for_selector('.watch-toggle:has-text("☆")')


def test_owned_badge_and_chip(dash):
    row = dash.locator("tr[data-id]", has_text="Alpha")
    assert row.locator(".badge-owned").count() == 1
    dash.click('[data-chip="owned"]')
    dash.wait_for_selector("#films tbody[data-count='1']")
    assert dash.locator("tr[data-id]").count() == 1


def test_drawer_shows_owned_link(dash):
    dash.locator("tr[data-id]", has_text="Alpha").click()
    link = dash.locator("#drawer-body a.owned-link")
    link.wait_for()
    assert "tv.apple.com/search" in link.get_attribute("href")


def test_not_owned_chip_hides_owned_films(dash: Page):
    dash.click('[data-chip="not_owned"]')
    dash.wait_for_selector("#films tbody[data-count]")
    assert dash.locator("tr[data-id]", has_text="Alpha").count() == 0  # Alpha is the owned seed
    dash.click('[data-chip="not_owned"]')


def test_suspect_chip_sorts_by_score_desc(dash: Page):
    # Bravo (score 4: imdb-id 3 + year 1) outranks Echo (score 2: omdb-title) — even though
    # under the old metacritic/rt/imdb hierarchy Echo (rt 60) would sort before Bravo (rt 50).
    clear_lang(dash)
    dash.click(".chip[data-chip=suspect]")
    assert first_titles(dash, 2) == ["Bravo", "Echo"]
    dash.click(".chip[data-chip=suspect]")


def test_drawer_shows_audit_reasons_and_records_a_verdict(dash: Page):
    clear_lang(dash)
    dash.click(".chip[data-chip=suspect]")
    assert count(dash) == 2  # Bravo, Echo
    dash.locator("#films tbody tr[data-id]").filter(has_text="Echo").click()
    block = dash.locator(".audit-block")
    expect(block.locator("li[data-code=omdb-title]")).to_contain_text("Bravo Two")
    expect(block.locator(".audit-verdict")).to_have_text("")
    block.locator("input.verdict-note").fill("wrong record")
    block.locator("button.verdict-btn[data-verdict=omdb-wrong]").click()
    expect(block.locator(".audit-verdict")).to_contain_text("omdb-wrong")
    assert count(dash) == 2  # a non-fine verdict keeps the film a suspect
    block.locator("button.verdict-btn[data-verdict=fine]").click()
    expect(dash.locator("#films tbody")).to_have_attribute("data-count", "1")  # fine hides Echo; Bravo remains
