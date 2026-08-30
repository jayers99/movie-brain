from __future__ import annotations

import socket
import threading
import time
from collections.abc import Generator
from datetime import date

import pytest
from playwright.sync_api import Page

from movie_brain.domain.models import Film, ListEntry, ListMeta, McTitle, OmdbRating
from movie_brain.infrastructure.database import Repository
from movie_brain.web.app import create_app

TODAY = date(2026, 8, 19)


# The seed exercises the default sort hierarchy (mc desc → rt desc → imdb desc → title):
# Echo and Bravo tie on mc 70 and break on rt (60 vs 50) — against title order, proving the
# rt tie-break; Foxtrot has only imdb; Charlie/Delta have no ratings at all.
FILMS = [
    Film("Alpha", 1950, "Ann", "https://c/alpha"),  # mc 92 imdb 8.5 rt 95 English, leaving, rated by me 9; the one top_ratings film
    Film("Bravo", 1960, "Bob", "https://c/bravo"),  # mc 70 imdb 6.0 rt 50 French
    Film("Charlie", 1970, "Cy", "https://c/charlie"),  # unmatched
    Film("Delta", 1980, "Dee", "https://c/delta"),  # pending (no omdb row), the only "recently added"
    Film("Echo", 1990, "Ann", "https://c/echo"),  # mc 70 imdb 7.0 rt 60 "English, Spanish", my rating 0
]

# Rated in the old walk, missing from today's → the one departed film. German keeps
# the English-default tests untouched; imdb 6.5 (below the 8.0 top_imdb threshold and
# below the imdb-min filter tests' cutoff) keeps the chip/filter counts untouched.
FOXTROT = Film("Foxtrot", 1955, "Fay", "https://c/foxtrot")


def seed(repo: Repository) -> None:
    films = FILMS
    # Old walk without Delta, then today's walk with all five → only Delta has first_seen = today.
    repo.record_catalog("criterion", [f for f in films if f.title != "Delta"] + [FOXTROT], date(2026, 1, 1))
    repo.record_catalog("criterion", films, TODAY)
    ids = {f.key: repo.film_id_by_key(f.key) for f in films + [FOXTROT]}
    repo.upsert_omdb(ids["foxtrot (1955)"], OmdbRating(6.5, None, True, "German", '{"Title":"Foxtrot"}'), TODAY)
    repo.set_rating(ids["foxtrot (1955)"], 7, TODAY)
    repo.upsert_omdb(
        ids["alpha (1950)"],
        OmdbRating(
            8.5,
            95,
            True,
            "English",
            '{"Title":"Alpha","Plot":"A plot.",'
            '"Poster":"data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ'
            'AAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",'
            '"Ratings":[{"Source":"Internet Movie Database","Value":"8.5/10"}]}',
            metacritic=92,
        ),
        TODAY,
    )
    repo.upsert_omdb(
        ids["bravo (1960)"], OmdbRating(6.0, 50, True, "French", '{"Title":"Bravo"}', metacritic=70), TODAY
    )
    repo.upsert_omdb(ids["charlie (1970)"], OmdbRating(None, None, False), TODAY)
    repo.upsert_omdb(
        ids["echo (1990)"], OmdbRating(7.0, 60, True, "English, Spanish", '{"Title":"Echo"}', metacritic=70), TODAY
    )
    repo.set_leaving("criterion", {"alpha (1950)": "August 31"})
    repo.set_rating(ids["alpha (1950)"], 9, TODAY)
    repo.set_rating(ids["echo (1990)"], 0, TODAY)
    # Alpha also streams on Max (subscribed) and MUBI (not) — the drawer's "Also streaming on" line.
    # Recorded as insert transitions dated TODAY, making Alpha a new arrival. The second
    # record_catalog walk above (at TODAY) also inserts Delta, firing a criterion transition
    # (criterion is svod) — so Delta is a new arrival too. test_new_arrivals_chip_filters_to_alpha
    # sees count=1 only because the default English-language filter hides Delta (no OMDb language).
    repo.record_listing_with_transition(ids["alpha (1950)"], "max", "https://tmdb/w/1", TODAY)
    repo.record_listing_with_transition(ids["alpha (1950)"], "mubi", "https://tmdb/w/1", TODAY)
    repo.record_listing_with_transition(ids["alpha (1950)"], "apple-tv-store", "https://tmdb/w/1", TODAY)
    # Bravo carries five svod services so the drawer's "Also streaming on" line overflows the
    # TOP_SERVICES cap and renders the "⋯ N more" disclosure. record_listing (not
    # record_listing_with_transition) on purpose: these must not register as new arrivals, or
    # they would change what the new-arrivals chip counts.
    for slug in ("max", "mubi", "peacock", "prime-video", "apple-tv-plus"):
        repo.record_listing(ids["bravo (1960)"], slug, "https://tmdb/w/2", TODAY)
    # Bravo is the one seeded watchlist film (Charlie stays free for the toggle test).
    repo.toggle_watchlist(ids["bravo (1960)"], TODAY)
    # Two seeded audit suspects for the Suspect chip + drawer verdict + score-sort tests. Bravo
    # carries the higher score (4: imdb-id 3 + year 1) while Echo carries the moved omdb-title
    # flag (score 2) — under the OLD metacritic/rt/imdb hierarchy Echo would already sort before
    # Bravo (mc tie 70, rt 60 vs 50), so putting the higher score on Bravo is the only seed that
    # proves the suspect chip's score-desc sort is real rather than an artifact of that hierarchy.
    from movie_brain.domain.audit import AuditFlag

    repo.replace_audit_flags(
        {
            ids["bravo (1960)"]: [
                AuditFlag("imdb-id", "OMDb imdbID tt1 vs TMDB tt2", 3),
                AuditFlag("year", "OMDb year 1993 vs film year 1990", 1),
            ],
            ids["echo (1990)"]: [AuditFlag("omdb-title", "OMDb title 'Bravo Two' vs 'Bravo'", 2)],
        },
        TODAY,
    )
    # Golf: the one Mode-B discovery film — no Criterion listing, scraped metascore only.
    gid = repo.create_film(Film("Golf", 2020, None, ""))
    repo.set_external_id(gid, "metacritic", "golf-2020", TODAY)
    repo.upsert_mc_titles([McTitle("golf-2020", "Golf", 2020, 88, 1, 1)], TODAY)
    # Alpha is the one owned film — English keeps it visible in the default view.
    repo.mark_owned(ids["alpha (1950)"], TODAY)
    # Alpha is also on one curated (ordered) list — the drawer's "On lists" line shows #rank.
    list_meta = ListMeta("cahiers-100", "100 Films for an Ideal Cinematheque", "Cahiers du Cinéma", 2008, None, True)
    repo.upsert_film_list(list_meta, TODAY)
    repo.upsert_list_entry(list_meta.slug, ListEntry(3, "Alpha", "Ann"))
    repo.link_list_entry(list_meta.slug, 3, ids["alpha (1950)"])
    # Echo is on one unordered list (no curator either) — the drawer must render its name alone,
    # with no #rank, proving the ordered/unordered branch rather than assuming it.
    backlog_meta = ListMeta("backlog-10", "Backlog Ten", None, None, None, False)
    repo.upsert_film_list(backlog_meta, TODAY)
    repo.upsert_list_entry(backlog_meta.slug, ListEntry(5, "Echo", "Ann"))
    repo.link_list_entry(backlog_meta.slug, 5, ids["echo (1990)"])
    # Charlie is on one tied-rank list — the drawer must render the poll's printed label
    # (rank_label), not the counted position, proving `rank_label ?? rank`.
    ss_meta = ListMeta("sight-sound-2022", "Sight & Sound 2022", "Sight & Sound", 2022, None, True)
    repo.upsert_film_list(ss_meta, TODAY)
    repo.upsert_list_entry(ss_meta.slug, ListEntry(1, "Charlie", "Cy", rank_label="=243"))
    repo.link_list_entry(ss_meta.slug, 1, ids["charlie (1970)"])
    # Alpha is ALSO on backlog-10 and sight-sound-2022 — three lists total, the one seeded film
    # the "N lists" card badge and the "On a list" chip (2026-08-29 design §6/§7) exercise.
    # Trust is deliberately UNEQUAL and set so trust order disagrees with name order (cahiers-100
    # would sort first alphabetically at "100 Films...", but is left at the default trust 1, the
    # lowest of the three) — proving the drawer's "On lists:" line orders by trust descending
    # rather than merely falling back to name. This is why test_drawer_shows_on_lists_line was
    # updated to expect Backlog Ten first instead of Cahiers (see that test's comment).
    repo.set_list_trust(backlog_meta.slug, 7)
    repo.set_list_trust(ss_meta.slug, 5)
    repo.upsert_list_entry(backlog_meta.slug, ListEntry(1, "Alpha", "Ann"))
    repo.link_list_entry(backlog_meta.slug, 1, ids["alpha (1950)"])
    repo.upsert_list_entry(ss_meta.slug, ListEntry(2, "Alpha", "Ann"))
    repo.link_list_entry(ss_meta.slug, 2, ids["alpha (1950)"])
    # Hotel: a discovery film with no Criterion listing but buyable on the Apple TV store —
    # reachable (default scope) shows it, criterion scope hides it. Hungarian + no scores keep it
    # out of the default-English counts and at the tail of the default sort.
    hid = repo.create_film(Film("Hotel", 2021, None, ""))
    repo.upsert_omdb(hid, OmdbRating(None, None, True, "Hungarian", '{"Title":"Hotel"}'), TODAY)
    repo.record_listing_with_transition(hid, "apple-tv-store", "https://tmdb/w/2", TODAY)


@pytest.fixture(scope="session")
def seeded_repo(tmp_path_factory: pytest.TempPathFactory) -> Repository:
    db = tmp_path_factory.mktemp("web") / "movie-brain.db"
    repo = Repository(db)
    seed(repo)
    return repo


@pytest.fixture(scope="session")
def server(seeded_repo: Repository) -> Generator[str, None, None]:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    app = create_app(seeded_repo, today=lambda: TODAY)
    threading.Thread(target=lambda: app.run(host="127.0.0.1", port=port, use_reloader=False), daemon=True).start()
    time.sleep(0.5)
    yield f"http://127.0.0.1:{port}"


@pytest.fixture
def dash(page: Page, server: str) -> Page:
    page.goto(server)
    page.wait_for_selector("#films tbody[data-count]")
    return page
