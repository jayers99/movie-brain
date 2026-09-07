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


def cycle(page: Page, group: str, times: int = 1) -> None:
    """Click a three-way chip `times` times: off → first key → second key (→ third) → off."""
    for _ in range(times):
        page.click(f'.chip[data-group="{group}"]')


def clear_lang(page: Page) -> None:
    set_langs(page, [])


def test_language_filter_defaults_to_any(dash: Page):
    expect(dash.locator("#f-lang-input")).to_have_value("Any")
    assert count(dash) == 8  # every seeded film: nothing is filtered by default
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
    assert count(dash) == 8
    assert "lang=" not in dash.url


def test_legacy_lang_any_url_still_reads_as_any(page, server):
    page.goto(f"{server}/?lang=any")
    page.wait_for_selector("#films tbody[data-count]")
    expect(page.locator("#f-lang-input")).to_have_value("Any")
    assert "lang=" not in page.url


def test_clear_resets_every_control(dash: Page):
    cycle(dash, "owned")
    dash.fill("#f-title", "a")
    dash.fill("#f-imdb-min", "7")
    set_langs(dash, ["Spanish"])
    dash.click("th.sortable[data-col=year]")
    dash.select_option("#list-picker", "cahiers-100")
    _search(dash, "director: hawks")
    url = dash.url
    assert all(k in url for k in ("chips=owned", "title=a", "imdb=7-", "lang=Spanish", "sort=year", "list=cahiers-100", "q="))

    dash.click("#chips-clear")

    assert dash.url.split("?")[-1] in ("", dash.url)  # nothing left to encode
    assert count(dash) == 8
    expect(dash.locator('.chip[data-group="owned"]')).to_have_text("Owned")
    expect(dash.locator("#f-title")).to_have_value("")
    expect(dash.locator("#f-imdb-min")).to_have_value("")
    expect(dash.locator("#f-lang-input")).to_have_value("Any")
    expect(dash.locator("#search")).to_have_value("")
    expect(dash.locator("#list-picker")).to_have_value("")
    expect(dash.locator("th.sortable[data-col=year]")).not_to_have_attribute("data-dir", re.compile(".+"))


def test_any_heads_the_list_then_english(dash: Page):
    dash.click("#f-lang-input")
    labels = [t.strip() for t in dash.locator("#f-lang-panel label").all_inner_texts()]
    assert labels[0] == "Any language"  # the default leads
    assert labels[1] == "English"  # the owner's own language pinned just under it
    assert labels[2:] == sorted(labels[2:]) and "English" not in labels[2:]
    expect(dash.locator("#f-lang-any")).to_be_checked()  # Any is the default selection
    assert count(dash) == 8
    dash.click("header h1")  # close the panel so the input shows the selection again
    expect(dash.locator("#f-lang-input")).to_have_value("Any")
    dash.click("#f-lang-input")  # reopen
    expect(dash.locator("#f-lang-panel input[type=checkbox]:not(#f-lang-any):checked")).to_have_count(0)
    dash.locator('#f-lang-panel input[value="French"]').check()  # picking a language unchecks Any
    expect(dash.locator("#f-lang-any")).not_to_be_checked()
    assert count(dash) == 1  # Bravo


def test_language_typeahead_filters_options_and_builds_up_selection(dash: Page):
    inp = dash.locator("#f-lang-input")
    expect(inp).to_have_value("Any")  # default selection shown while closed
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
    expect(inp).to_have_value("Spanish, French")  # builds up in selection order
    assert count(dash) == 2  # Echo (English/Spanish) + Bravo (French)
    dash.goto(dash.url)  # selection round-trips through the URL
    dash.wait_for_selector("#films tbody[data-count]")
    expect(dash.locator("#f-lang-input")).to_have_value("Spanish, French")
    assert count(dash) == 2


def test_rating_columns_show_metacritic_then_rt_then_imdb(dash: Page):
    cols = [th.get_attribute("data-col") for th in dash.locator("thead tr.labels th.sortable").all()]
    assert cols == ["title", "year", "director", "language", "metacritic", "rt", "imdb", "my_rating"]
    row = dash.locator("#films tbody tr[data-id]").filter(has_text="Alpha")
    expect(row.locator(".c-metacritic")).to_have_text("92")
    expect(row.locator(".c-rt")).to_have_text("95%")
    expect(row.locator(".c-imdb")).to_have_text("8.5")


def test_default_sort_hierarchy_metacritic_then_rt_then_imdb_then_title(dash: Page):
    clear_lang(dash)
    assert count(dash) == 8  # everything off by default: all eight seeded films, Golf included
    # mc desc: Alpha 92, then the Echo/Bravo mc-70 tie breaks on rt (60 vs 50, against title
    # order); missing values sort after present ones at each level, so imdb-only Foxtrot
    # follows, then the unrated Charlie/Delta by title.
    assert first_titles(dash, 6) == ["Alpha", "Echo", "Bravo", "Foxtrot", "Charlie", "Delta"]
    # the header counts the whole catalogue (8 seeded films); "reachable" is the market test —
    # 5 on Criterion now + buyable Hotel; departed Foxtrot and listing-less Golf are not
    expect(dash.locator("#count-films")).to_have_text("8")
    expect(dash.locator("#count-reachable")).to_have_text("6")
    expect(dash.locator("#count-owned")).to_have_text("1")
    expect(dash.locator("#count-showing")).to_have_text("Showing 8 of 8")
    expect(dash.locator("#films tbody tr").first.locator(".c-title a")).to_have_attribute("href", "https://c/alpha")


def test_chip_labels_and_order(dash: Page):
    # Everything off by default: every cycle chip shows its off label.
    labels = [t.strip() for t in dash.locator("#chips .chip").all_inner_texts()]
    assert labels == ["Reachable", "Rated", "Criterion", "Watchlist", "Owned", "On a list", "Clear"]


def test_cycle_chip_walks_off_a_b_off_and_encodes_one_key(dash: Page):
    owned = dash.locator('.chip[data-group="owned"]')
    cycle(dash, "owned")
    expect(owned).to_have_text("Owned")  # the yes-state keeps the plain word; the fill says it is on
    expect(owned).to_have_class(re.compile("active"))
    assert "chips=owned" in dash.url and "not_owned" not in dash.url
    cycle(dash, "owned")
    expect(owned).to_have_text("Not owned")
    assert "chips=not_owned" in dash.url
    cycle(dash, "owned")
    expect(owned).to_have_text("Owned")
    expect(owned).not_to_have_class(re.compile("active"))
    assert "chips=" not in dash.url


def test_criterion_chip_has_four_on_states(dash: Page):
    crit = dash.locator('.chip[data-group="criterion"]')
    for label, key in [("Criterion", "criterion"), ("Criterion leaving", "leaving"), ("Criterion new", "criterion_new"), ("Not Criterion", "not_criterion")]:
        cycle(dash, "criterion")
        expect(crit).to_have_text(label)
        assert f"chips={key}" in dash.url
    cycle(dash, "criterion")
    expect(crit).to_have_text("Criterion")


def test_chips_stack_with_and(dash: Page):
    clear_lang(dash)
    cycle(dash, "rated")  # Unrated by me
    assert count(dash) == 5  # Bravo, Charlie, Delta, Golf, Hotel
    cycle(dash, "criterion")  # Criterion (on)
    assert count(dash) == 3  # Bravo, Charlie, Delta — Golf and Hotel have no Criterion listing
    expect(dash.locator('.chip[data-group="rated"]')).to_have_class(re.compile("active"))
    dash.click("#chips-clear")
    assert count(dash) == 8


def test_each_chip_alone(dash: Page):
    clear_lang(dash)
    expected = {
        "reachable": ("reach", 1, 6),  # 5 on Criterion now + buyable Hotel
        "unreachable": ("reach", 2, 2),  # departed Foxtrot, listing-less Golf
        "unrated": ("rated", 1, 5),  # Bravo, Charlie, Delta, Golf, Hotel
        "mine": ("rated", 2, 2),  # Alpha 9, Foxtrot 7 (Echo's 0 is not "mine")
        "criterion": ("criterion", 1, 5),
        "leaving": ("criterion", 2, 1),  # Alpha
        "criterion_new": ("criterion", 3, 1),  # Delta, first seen on the Channel today
        "not_criterion": ("criterion", 4, 3),  # departed Foxtrot, discovery Golf, buyable Hotel
        "owned": ("owned", 1, 1),
        "not_owned": ("owned", 2, 7),
    }
    for key, (group, clicks, n) in expected.items():
        dash.click("#chips-clear")
        cycle(dash, group, clicks)
        assert f"chips={key}" in dash.url, key
        assert count(dash) == n, key
    dash.click("#chips-clear")


def test_departed_film_is_marked_in_table(dash: Page):
    clear_lang(dash)
    row = dash.locator("#films tbody tr[data-id]").filter(has_text="Foxtrot")
    expect(row).to_have_class(re.compile("departed"))
    expect(row.locator(".c-title")).to_contain_text("gone")


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
    cycle(dash, "rated", 2)  # Rated by me
    assert count(dash) == 1  # Alpha (rated 9); Echo's 0 doesn't count as mine
    assert first_titles(dash, 1) == ["Alpha"]
    cycle(dash, "rated")  # off
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
    assert count(dash) == 2  # Alpha 88 and discovery film Golf 88 (visible now nothing is off by default); Echo 70 misses
    dash.fill("#f-mc-min", "")


def test_url_state_round_trips(dash: Page, server: str):
    clear_lang(dash)
    cycle(dash, "rated")  # Unrated by me
    dash.fill("#f-title", "a")
    dash.click("th.sortable[data-col=year]")
    url = dash.url
    assert "chips=unrated" in url and "title=a" in url and "lang=" not in url
    assert ("sort=year%3Aasc" in url) or ("sort=year:asc" in url)
    dash.goto(url)
    dash.wait_for_selector("#films tbody[data-count]")
    expect(dash.locator('.chip[data-group="rated"]')).to_have_text("Unrated by me")
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
    expect(drawer.locator("a.criterion-link")).to_have_attribute(
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
    expect(dash.locator("#drawer h2")).to_have_text("Golf ☆⚐")  # second under the default sort: Alpha 92, Golf 88
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
    # lang=any: none of these films carry OMDb language metadata, so the default English
    # filter would hide every one of them. (Everything else is off by default now.)
    page.goto(f"{acquire_server}/?lang=any")
    page.wait_for_selector("#films tbody[data-count]")
    return page


def test_on_a_list_chip_keeps_only_listed_films(acquire_dash: Page):
    # Zulu is Metacritic-only (91, no list): the retired acquire chip kept it, On a list does not.
    acquire_dash.click('.chip[data-chip="multi_list"]')
    assert count(acquire_dash) == 4  # Yankee, Whiskey, Xray, Victor
    assert acquire_dash.locator("tr[data-id]", has_text="Zulu").count() == 0
    assert acquire_dash.locator("tr[data-id]", has_text="Whiskey").count() == 1  # on Criterion now, still listed


def test_on_a_list_chip_orders_by_canon_score_desc(acquire_dash: Page):
    # The canon-score sort the acquire chip carried now rides on On a list. Yankee/Xray have no
    # listing anywhere, so `.c-title` renders no <a> — read the plain title text.
    acquire_dash.click('.chip[data-chip="multi_list"]')
    titles = [t.split(" ")[0] for t in acquire_dash.locator("#films tbody tr .c-title").all_inner_texts()]
    assert titles == ["Yankee", "Whiskey", "Xray", "Victor"]  # 10.0, 6.67, 3.33, then trust-0 Victor at 0.0


def test_on_a_list_plus_not_owned_is_the_old_acquisition_shortlist(acquire_dash: Page):
    acquire_dash.click('.chip[data-chip="multi_list"]')
    cycle(acquire_dash, "owned", 2)  # Not owned
    assert count(acquire_dash) == 4  # none of the four is owned
    assert "chips=multi_list%2Cnot_owned" in acquire_dash.url or "chips=multi_list,not_owned" in acquire_dash.url


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
    expect(dash.locator("#drawer .best-source")).to_contain_text("Watch on Apple TV+")


def test_an_owned_film_answers_with_the_store_it_was_bought_from(dash: Page):
    """Possession short-circuits the ranking: Alpha streams on Criterion and HBO Max, and
    still answers with the Apple TV library link, because the owner already has it."""
    dash.locator("tbody tr", has_text="Alpha").first.click()
    expect(dash.locator("#drawer .best-source")).to_contain_text("Owned on Apple TV")


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


def test_criterion_new_chip_filters_to_the_channels_arrivals(dash):
    # Alpha arrived on HBO Max (a subscribed service) today — that is NOT Criterion-new. Delta
    # is the one film whose Criterion listing first appeared today.
    clear_lang(dash)  # Delta has no language on file
    cycle(dash, "criterion", 3)  # Criterion new
    dash.wait_for_selector('#films tbody[data-count="1"]')
    assert dash.locator("#films tbody tr").first.inner_text().startswith("Delta")


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
        "On lists: Backlog Ten, Sight & Sound 2022 #2, 100 Films for an Ideal Cinematheque #3"
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
    # Alpha is on three lists, Charlie on two, Echo and Delta on one each. The single-list films
    # must survive the chip — that is the whole difference from the old "on 2+ lists" behaviour,
    # which kept Alpha alone. clear_lang because Charlie and Delta have no language on file.
    clear_lang(dash)
    dash.click('button[data-chip="multi_list"]')
    dash.wait_for_selector('#films tbody[data-count="4"]')
    # A row's first cell carries badges after the title ("Alpha 3 lists owned"), so compare the
    # leading word rather than the whole cell.
    rows = dash.locator("#films tbody tr").all_inner_texts()
    assert sorted(r.split()[0] for r in rows) == ["Alpha", "Charlie", "Delta", "Echo"]


def test_drawer_shows_tied_rank_label_not_position(dash):
    clear_lang(dash)  # Charlie has no language on file; the default English filter would hide its row
    dash.locator("#films tbody tr", has_text="Charlie").first.click()
    dash.wait_for_selector("#drawer:not([hidden])")
    expect(dash.locator("#drawer-body")).to_contain_text("On lists: Sight & Sound 2022 #243")
    expect(dash.locator("#drawer-body")).not_to_contain_text("Sight & Sound 2022 #1")


def test_everything_is_off_by_default_so_discovery_shows(dash):
    clear_lang(dash)  # Hotel is Hungarian
    assert dash.locator("tr[data-id]", has_text="Golf").count() == 1  # no listing anywhere, yet visible
    assert dash.locator("tr[data-id]", has_text="Hotel").count() == 1
    assert "chips=" not in dash.url


def test_reachable_chip_is_the_market_test(dash):
    clear_lang(dash)  # Hotel is Hungarian
    cycle(dash, "reach")  # Reachable (on)
    assert dash.locator("tr[data-id]", has_text="Hotel").count() == 1  # buyable on the Apple TV store
    assert dash.locator("tr[data-id]", has_text="Golf").count() == 0  # nothing to stream, nothing to buy
    assert dash.locator("tr[data-id]", has_text="Foxtrot").count() == 0  # departed, rated — a rating is not a listing
    cycle(dash, "reach")  # Not reachable
    assert sorted(t.split()[0] for t in dash.locator("#films tbody tr").all_inner_texts()) == ["Foxtrot", "Golf"]
    cycle(dash, "reach")  # off
    assert count(dash) == 8


def test_legacy_scope_criterion_url_maps_onto_the_criterion_chip(page, server):
    page.goto(f"{server}/?scope=criterion&lang=any")
    page.wait_for_selector("#films tbody[data-count]")
    assert page.locator("tr[data-id]", has_text="Hotel").count() == 0
    expect(page.locator('.chip[data-group="criterion"]')).to_have_text("Criterion")
    expect(page.locator('.chip[data-group="criterion"]')).to_have_class(re.compile("active"))
    assert "chips=criterion" in page.url and "scope=" not in page.url


def test_legacy_scope_all_url_is_just_the_default(page, server):
    page.goto(f"{server}/?scope=all&lang=any")
    page.wait_for_selector("#films tbody[data-count]")
    assert page.locator("tr[data-id]", has_text="Golf").count() == 1
    assert "scope=" not in page.url


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
    cycle(dash, "owned")  # Owned (on)
    dash.wait_for_selector("#films tbody[data-count='1']")
    assert dash.locator("tr[data-id]").count() == 1


def test_drawer_shows_owned_link(dash):
    dash.locator("tr[data-id]", has_text="Alpha").click()
    link = dash.locator("#drawer-body a.owned-link")
    link.wait_for()
    assert "tv.apple.com/search" in link.get_attribute("href")


def test_not_owned_chip_hides_owned_films(dash: Page):
    cycle(dash, "owned", 2)  # Not owned
    dash.wait_for_selector("#films tbody[data-count]")
    assert dash.locator("tr[data-id]", has_text="Alpha").count() == 0  # Alpha is the owned seed
    cycle(dash, "owned")  # off


def test_drawer_shows_audit_reasons_and_records_a_verdict(dash: Page):
    clear_lang(dash)
    dash.locator("#films tbody tr[data-id]").filter(has_text="Echo").click()
    block = dash.locator(".audit-block")
    expect(block.locator("li[data-code=omdb-title]")).to_contain_text("Bravo Two")
    expect(block.locator(".audit-verdict")).to_have_text("")
    block.locator("input.verdict-note").fill("wrong record")
    block.locator("button.verdict-btn[data-verdict=omdb-wrong]").click()
    expect(block.locator(".audit-verdict")).to_contain_text("omdb-wrong")
    block.locator("button.verdict-btn[data-verdict=fine]").click()
    expect(block.locator(".audit-verdict")).to_contain_text("fine")  # the verdict round-trips; no chip hides the film any more


def test_list_picker_offers_every_seeded_list_by_trust(dash):
    # Trust order (backlog-10 7, sight-sound-2022 5, cahiers-100 1) disagrees with name order,
    # so this proves the picker sorts by trust rather than falling back to the label.
    # Every label is the list's NAME plus its size — the owner writes the name to read well here,
    # and it is unique where "curator published" was not (the two Sight & Sound polls collide).
    labels = dash.locator("#list-picker option").all_inner_texts()
    assert labels == [
        "— all films —",
        "Backlog Ten (2)",
        "Sight & Sound 2022 (2)",
        "Sight & Sound 2022 Directors (1)",
        "100 Films for an Ideal Cinematheque (2)",
    ]


def test_list_picker_filters_to_the_list_and_orders_by_printed_rank(dash):
    # cahiers-100 holds Charlie (#1) and Alpha (#3). Rank order is the REVERSE of alphabetical,
    # so a title fallback would fail this.
    clear_lang(dash)  # Charlie has no language on file
    dash.select_option("#list-picker", "cahiers-100")
    dash.wait_for_selector('#films tbody[data-count="2"]')
    rows = dash.locator("#films tbody tr").all_inner_texts()
    assert [r.split()[0] for r in rows] == ["Charlie", "Alpha"]


def test_list_picker_leaves_the_reachable_chip_alone(dash):
    # A chip the owner set stays set: picking a list narrows within it rather than resetting it.
    cycle(dash, "reach")
    expect(dash.locator('.chip[data-group="reach"]')).to_have_class(re.compile("active"))
    dash.select_option("#list-picker", "cahiers-100")
    expect(dash.locator('.chip[data-group="reach"]')).to_have_class(re.compile("active"))
    assert "chips=reachable" in dash.url and "list=cahiers-100" in dash.url


def test_list_picker_is_encoded_in_the_url(dash):
    dash.select_option("#list-picker", "cahiers-100")
    dash.wait_for_function("() => location.search.includes('list=cahiers-100')")


def test_clear_chip_clears_the_list_picker(dash):
    dash.select_option("#list-picker", "cahiers-100")
    dash.wait_for_selector('#films tbody[data-count="2"]')  # Charlie and Alpha, no language filter by default
    dash.click("#chips-clear")
    expect(dash.locator("#list-picker")).to_have_value("")


def test_unordered_list_does_not_sort_by_a_meaningless_rank(dash):
    # backlog-10 is unordered (ordered=False): Alpha #1 and Echo #5 are line positions, not a
    # ranking, so the default hierarchy decides. Alpha (mc 92) leads Echo (mc 70).
    dash.select_option("#list-picker", "backlog-10")
    dash.wait_for_selector('#films tbody[data-count="2"]')
    rows = dash.locator("#films tbody tr").all_inner_texts()
    assert [r.split()[0] for r in rows] == ["Alpha", "Echo"]


def test_drawer_links_straight_to_the_resolved_cheapcharts_page(dash):
    """Alpha's iTunes id is resolved, so the drawer skips the search list entirely — and it
    does so without a store listing, since the resolved id is itself proof Apple sells it."""
    clear_lang(dash)
    dash.locator("#films tbody tr", has_text="Alpha").first.click()
    dash.wait_for_selector("#drawer:not([hidden])")
    link = dash.locator("#drawer-body a.cheapcharts-link")
    expect(link).to_have_attribute("href", "https://www.cheapcharts.com/us/itunes/movies/284815525")
    expect(link).to_have_text("CheapCharts ↗")


def _search(dash: Page, text: str) -> None:
    dash.fill("#search", text)
    dash.wait_for_function("document.querySelector('#search').dataset.settled === document.querySelector('#search').value")


def test_search_field_query_narrows_to_the_exact_set(dash: Page):
    clear_lang(dash)
    _search(dash, "character: philip marlowe")
    assert count(dash) == 1
    expect(dash.locator("#films tbody tr[data-id]").first).to_contain_text("Alpha")
    assert "q=character" in dash.url


def test_search_freeform_ranks_a_title_hit_first_and_sort_restores_on_clear(dash: Page):
    clear_lang(dash)
    _search(dash, "alpha")
    rows = dash.locator("#films tbody tr[data-id]")
    assert count(dash) == 2
    expect(rows.nth(0)).to_contain_text("Alpha")   # title hit (10) above Bravo's overview hit (2)
    expect(rows.nth(1)).to_contain_text("Bravo")
    _search(dash, "")
    assert count(dash) > 2 and "q=" not in dash.url


def test_search_correction_is_shown_and_undo_forces_exact(dash: Page):
    clear_lang(dash)
    _search(dash, "actor: bogrt")
    note = dash.locator("#search-note")
    expect(note).to_contain_text("Showing results for Humphrey Bogart")
    assert count(dash) == 1
    note.locator("button.undo").click()
    expect(dash.locator("#search")).to_have_value('actor: "bogrt"')
    dash.wait_for_function("document.querySelector('#search').dataset.settled === document.querySelector('#search').value")
    assert count(dash) == 0


def test_search_suggestion_chip_replaces_the_value(dash: Page):
    clear_lang(dash)
    _search(dash, "actor: bogxrtq")   # shares 'bog' with Bogart; similarity 0.77 — suggestion band, not correction
    assert count(dash) == 0
    dash.locator("#search-note button.suggest", has_text="Humphrey Bogart").click()
    expect(dash.locator("#search")).to_have_value('actor: "Humphrey Bogart"')
    dash.wait_for_function("document.querySelector('#search').dataset.settled === document.querySelector('#search').value")
    assert count(dash) == 1


def test_chips_keep_working_mid_search(dash: Page):
    clear_lang(dash)
    _search(dash, "director: hawks")
    assert count(dash) == 2   # Alpha and Bravo
    cycle(dash, "owned")  # Owned (on)
    assert count(dash) == 1   # only Alpha is owned
    cycle(dash, "owned", 2)  # Not owned, then off
    assert count(dash) == 2


def test_search_round_trips_through_the_url(dash: Page, server: str):
    dash.goto(f"{server}/?q=character%3A+philip+marlowe&lang=any")
    dash.wait_for_function("document.querySelector('#search').dataset.settled === document.querySelector('#search').value")
    expect(dash.locator("#search")).to_have_value("character: philip marlowe")
    assert count(dash) == 1


def test_search_input_is_not_a_chip(dash: Page):
    assert dash.locator("#search.chip").count() == 0
    assert dash.locator("#chips #search").count() == 0


def test_search_correction_undo_targets_the_right_field(dash: Page):
    # "bogrt" appears twice, under two different fields: a bare `.replace` would quote the
    # FIRST textual occurrence (the title term) instead of the one the correction is actually
    # about (the actor term). Row count is 0 either way (`title: bogrt` matches nothing), so
    # this pins the input value, not the result set.
    clear_lang(dash)
    _search(dash, "title: bogrt actor: bogrt")
    note = dash.locator("#search-note")
    expect(note).to_contain_text("Showing results for Humphrey Bogart")
    note.locator("button.undo").click()
    expect(dash.locator("#search")).to_have_value('title: bogrt actor: "bogrt"')


def test_search_note_click_replace_survives_a_dollar_sign_in_the_value(dash: Page):
    # "Ke$1ha" carries a literal "$1": a `.replace(regex, "$1\"...\"")` template-string
    # replacement re-interprets that embedded "$1" as a second backreference and corrupts
    # the rewritten query (I3) — the fix is a replacer FUNCTION, whose return value is never
    # re-scanned for "$" patterns.
    clear_lang(dash)
    _search(dash, "actor: e$1z")   # shares the 'e$1' trigram window with Ke$1ha; similarity 0.6 — a suggestion, not a correction
    dash.locator("#search-note button.suggest", has_text="Ke$1ha").click()
    expect(dash.locator("#search")).to_have_value('actor: "Ke$1ha"')


# ---- drawer redesign (spec docs/superpowers/specs/2026-09-07-drawer-redesign-design.md) ----


def _open(dash: Page, title: str):
    dash.locator("tbody tr", has_text=title).first.click()
    body = dash.locator("#drawer-body")
    expect(body).to_contain_text(title)  # populated — a negative assertion on an empty drawer passes vacuously
    return body


def test_drawer_is_760_wide(dash: Page):
    _open(dash, "Alpha")
    assert dash.locator("#drawer").bounding_box()["width"] == 760


def test_drawer_summary_prefers_the_tmdb_overview(dash: Page):
    body = _open(dash, "Alpha")
    expect(body.locator("p").first).to_have_text("A private eye in the Sternwood house.")  # TMDB, not OMDb's "A plot."
    expect(body.locator("pre.raw")).to_contain_text('"Plot": "A plot."')  # OMDb still in the raw payload


def test_drawer_summary_falls_back_to_the_omdb_plot(dash: Page):
    body = _open(dash, "Echo")  # never enriched
    expect(body.locator("p").first).to_have_text("An echo.")


def test_drawer_sections_run_facts_cast_writer_ratings_then_watch(dash: Page):
    body = _open(dash, "Alpha")
    expect(body).to_contain_text("Owned on Apple TV")
    text = body.inner_text()
    marks = ["Language", "Cast", "Writer", "My rating", "IMDb 8.5 · Metacritic 92 · Rotten Tomatoes 95%",
             "On lists: Backlog Ten", "Owned on Apple TV", "Also streaming on", "Open on Criterion", "Raw OMDb payload"]
    positions = [text.index(m) for m in marks]
    assert positions == sorted(positions), list(zip(marks, positions, strict=True))


def test_drawer_on_lists_line_ends_with_the_canon_score(dash: Page):
    body = _open(dash, "Alpha")
    # Backlog Ten unordered, trust 7 → 7. Sight & Sound 2022: 2 entries, Alpha #2, trust 5 → 5 × (1 − 1/2) = 2.5.
    # cahiers-100: 2 entries, Alpha #3, trust 1 → 1 × (1 − 2/2) = 0. Total 9.5.
    expect(body.locator(".canon-score")).to_have_text("· canon score 9.5")


def test_drawer_ratings_block_notes_a_pending_lookup(dash: Page):
    body = _open(dash, "Delta")  # no OMDb row
    expect(body.locator(".ratings")).to_contain_text("OMDb lookup pending.")
    assert body.locator(".ratings .critics").count() == 0


def test_watch_link_fills_the_services_template(dash: Page):
    clear_lang(dash)
    body = _open(dash, "Bravo")
    link = body.locator(".best-source a.watch-link")
    expect(link).to_have_text("Watch on Apple TV+ ↗")
    expect(link).to_have_attribute("href", "https://tv.apple.com/search?term=Bravo")


def test_watch_link_falls_back_to_the_criterion_page(dash: Page):
    body = _open(dash, "Charlie")
    link = body.locator(".best-source a.watch-link")
    expect(link).to_have_text("Watch on Criterion Channel ↗")
    expect(link).to_have_attribute("href", "https://c/charlie")


def test_owned_film_links_to_the_apple_tv_library_search(dash: Page):
    body = _open(dash, "Alpha")
    link = body.locator(".best-source a.owned-link")
    expect(link).to_have_text("Owned on Apple TV ↗")
    expect(link).to_have_attribute("href", "https://tv.apple.com/search?term=Alpha")


def test_discovery_film_without_listings_has_no_watch_line(dash: Page):
    body = _open(dash, "Golf")
    assert body.locator(".best-source").count() == 0


def test_drawer_links_row_has_tmdb_and_no_metacritic(dash: Page):
    body = _open(dash, "Alpha")
    expect(body.locator("a.tmdb-link")).to_have_text("TMDB ↗")
    expect(body.locator("a.tmdb-link")).to_have_attribute("href", "https://www.themoviedb.org/movie/910")
    dash.keyboard.press("Escape")
    body = _open(dash, "Golf")  # holds a metacritic slug and no tmdb id
    expect(body).not_to_contain_text("Metacritic ↗")
    assert body.locator("a.tmdb-link").count() == 0
