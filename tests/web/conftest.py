from __future__ import annotations

import socket
import threading
import time
from collections.abc import Generator
from datetime import date
from decimal import Decimal

import pytest
from playwright.sync_api import Page

from movie_brain.application.wishlist import WishlistError, WishlistGateway
from movie_brain.domain.models import CastRow, CrewRow, Film, ListEntry, ListMeta, McTitle, OmdbRating, TmdbCredits
from movie_brain.infrastructure.cheapcharts import WishlistItem
from movie_brain.infrastructure.database import Repository
from movie_brain.web.app import create_app

TODAY = date(2026, 8, 19)

# "Wishlist it": the live server is driven by fakes — no test run can reach a real account.
CHARLIE_ITUNES, DELTA_ITUNES, ECHO_ITUNES = "273058482", "366474905", "495816081"
# Un-wishlist (brief 1.2): Kilo and November are two brand-new Criterion-current, unrated films
# — reusing Foxtrot (departed) or Golf (no listing) would flip them into the "reachable" bucket
# and gut test_reachable_chip_is_the_market_test's own proof that a rating and a bare discovery
# listing do NOT count; reusing Alpha/Bravo/Hotel would break their own pinned "no button"/"no
# itunes id" assertions; Echo/Charlie/Delta are excluded by the brief itself. Both hold a
# CURRENT Criterion listing (like Charlie/Delta) so the extra itunes id changes no reachability
# bucket, and both are seeded in the OLD walk too so neither counts as a new arrival.
KILO_ITUNES, NOVEMBER_ITUNES = "111000111", "222000222"


class FakePrices:
    def lowest_price(self, itunes_id: str) -> Decimal | None:
        return Decimal("2.99")


class FakeAccount:
    """Delta's product always fails to ADD, so the add-failure line has a film of its own and
    the two add-click tests never depend on each other's order. November's product always fails
    to REMOVE, the same way, for the un-wishlist failure test (brief 1.2). `listed` is what the
    account holds and `targets` which of those carry a custom price — the two things the read
    reports, and what every click now consults BEFORE writing anything (brief 1.3)."""

    def __init__(self) -> None:
        self.targets: dict[str, Decimal] = {
            ECHO_ITUNES: Decimal("5.99"),
            KILO_ITUNES: Decimal("2.99"),
            NOVEMBER_ITUNES: Decimal("2.99"),
        }
        self.listed: list[str] = list(self.targets)

    def add_item(self, itunes_id: str) -> bool:
        time.sleep(1.0)  # long enough for "Reaching CheapCharts…" to be seen under load (2026-09-19 flake)
        if itunes_id == DELTA_ITUNES:
            raise WishlistError("down")
        if itunes_id not in self.listed:
            self.listed.append(itunes_id)
        return True

    def set_target(self, itunes_id: str, target: Decimal) -> None:
        self.targets[itunes_id] = target

    def wishlist_items(self) -> list[WishlistItem]:
        return [WishlistItem(i, custom_target=i in self.targets) for i in self.listed]

    def remove_item(self, itunes_id: str) -> bool:
        time.sleep(1.0)  # same busy window as add_item, for the same reason
        if itunes_id == NOVEMBER_ITUNES:
            raise WishlistError("down")
        if itunes_id in self.listed:
            self.listed.remove(itunes_id)
        self.targets.pop(itunes_id, None)
        return True


FAKE_ACCOUNT = FakeAccount()


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

# Un-wishlist (brief 1.2): two brand-new, unrated films, current on Criterion in BOTH walks below
# (like Charlie/Echo, never a new arrival like Delta) — reusing Foxtrot (departed) or Golf (no
# listing) for a store id would flip them into the "reachable" bucket and gut
# test_reachable_chip_is_the_market_test's own proof that a rating and a bare discovery listing
# do NOT count; Alpha/Bravo/Hotel each carry their own pinned "no button"/"no itunes id"
# assertion; Echo/Charlie/Delta are excluded by the brief itself.
KILO = Film("Kilo", 2010, "Kip", "https://c/kilo")
NOVEMBER = Film("November", 2011, "Nora", "https://c/november")


def seed(repo: Repository) -> None:
    films = FILMS
    # Old walk without Delta, then today's walk with all five → only Delta has first_seen = today.
    repo.record_catalog("criterion", [f for f in films if f.title != "Delta"] + [FOXTROT, KILO, NOVEMBER], date(2026, 1, 1))
    repo.record_catalog("criterion", films + [KILO, NOVEMBER], TODAY)
    ids = {f.key: repo.film_id_by_key(f.key) for f in films + [FOXTROT, KILO, NOVEMBER]}
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
    # Echo is never enriched: the drawer's OMDb fallbacks (plot, bare-query cast and writer links) are proved on it.
    repo.upsert_omdb(
        ids["echo (1990)"],
        OmdbRating(7.0, 60, True, "English, Spanish",
                   '{"Title":"Echo","Plot":"An echo.","Actors":"Ed Actor, Flo Actor","Writer":"Gus Writer (screenplay)"}',
                   metacritic=70),
        TODAY,
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
    # Bravo's best source is Apple TV+ (name tiebreak); its template makes the drawer's watch link
    # a real title search. `criterion` deliberately gets none, so Charlie proves the listing-URL fallback.
    repo.set_service_search_url("apple-tv-plus", "https://tv.apple.com/search?term={title}")
    # Old ratings (2004-08 stars, invented): Bravo 5★ and unrated — the one Rewatch film; Alpha 5★
    # but rated 9 today, so its request is served; Charlie 1★ — the avoid badge; Echo 3★ — drawer only.
    from movie_brain.domain.models import OldRating

    for line, (key, stars, rented) in enumerate(
        [("bravo (1960)", 5, "2005-03-02"), ("alpha (1950)", 5, None), ("charlie (1970)", 1, "2004-06-01"),
         ("echo (1990)", 3, "2006-01-10")],
        start=1,
    ):
        repo.upsert_old_rating("ntc", OldRating(line, key, None, stars, rented))
        repo.link_old_rating("ntc", line, ids[key], "resolver", TODAY)
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
    # Charlie sits ABOVE Alpha on cahiers-100 (#1 vs #3) while sorting BELOW it alphabetically —
    # the only seeded arrangement that lets the list picker's rank ordering be proved rather than
    # mistaken for the title fallback. cahiers-100 is left at the default trust 1 (see below), so
    # this does not disturb Charlie's drawer line, which Sight & Sound still leads.
    repo.upsert_list_entry(list_meta.slug, ListEntry(1, "Charlie", "Cy"))
    repo.link_list_entry(list_meta.slug, 1, ids["charlie (1970)"])
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
    # A SECOND Sight & Sound 2022 list: same curator, same year, different poll — the live
    # catalogue has exactly this collision (the 1992 critics' and directors' polls), and it is the
    # only seed that proves the picker falls back to the full name instead of printing a duplicate.
    ss_dir_meta = ListMeta("sight-sound-2022-directors", "Sight & Sound 2022 Directors", "Sight & Sound", 2022, None, True)
    repo.upsert_film_list(ss_dir_meta, TODAY)
    # Linked to DELTA, not Charlie: the drawer labels a list by its NAME (as does the picker), so hanging a
    # second "Sight & Sound 2022" off Charlie would make its "On lists:" line print that name twice
    # and blunt test_drawer_shows_tied_rank_label_not_position's guard against the line position.
    repo.upsert_list_entry(ss_dir_meta.slug, ListEntry(1, "Delta", "Dee"))
    repo.link_list_entry(ss_dir_meta.slug, 1, ids["delta (1980)"])
    repo.set_list_trust(ss_dir_meta.slug, 4)
    repo.set_list_trust(backlog_meta.slug, 7)
    repo.set_list_trust(ss_meta.slug, 5)
    repo.upsert_list_entry(backlog_meta.slug, ListEntry(1, "Alpha", "Ann"))
    repo.link_list_entry(backlog_meta.slug, 1, ids["alpha (1950)"])
    repo.upsert_list_entry(ss_meta.slug, ListEntry(2, "Alpha", "Ann"))
    repo.link_list_entry(ss_meta.slug, 2, ids["alpha (1950)"])
    # Alpha's CheapCharts product page is resolved (external id `itunes`), so its drawer links
    # straight to the page; Hotel's is not, so Hotel keeps the title-search fallback.
    repo.set_external_id(ids["alpha (1950)"], "itunes", "284815525", TODAY)
    # Power search (Plan B): Alpha and Bravo carry credits. Bogart plays Marlowe on Alpha (the
    # spec's own example query); Jane Bogart on Bravo is the near-name that makes the
    # correction's tiebreak real; Bravo's overview says "alpha" so a freeform 'alpha' search
    # ranks Alpha (title) above Bravo (overview). Hawks directs both.
    def _credits(tmdb_id: int, title: str, overview: str, cast: tuple[CastRow, ...],
                 crew: tuple[CrewRow, ...] = (CrewRow(2636, "Howard Hawks", "Director", "Directing"),)) -> TmdbCredits:
        return TmdbCredits(
            tmdb_id=tmdb_id, imdb_id=None, title=title, original_title=title, year=None, runtime_min=None,
            alt_titles=(), overview=overview, tagline=None, genres=("Mystery",), keywords=("film noir",),
            cast=cast, crew=crew,
        )

    repo.set_external_id(ids["alpha (1950)"], "tmdb", "910", TODAY)
    repo.set_external_id(ids["bravo (1960)"], "tmdb", "911", TODAY)
    # Alpha carries eight billed actors (the drawer shows six, then "⋯ 2 more" with roles) and a
    # screenwriter plus a novelist (the writer label branch). No new name shares a trigram with
    # `bogrt`/`bogxrtq` or contains alpha/hawks/marlowe, so every search count above stays put.
    repo.write_credits(ids["alpha (1950)"], _credits(910, "Alpha", "A private eye in the Sternwood house.", (
        CastRow(4110, "Humphrey Bogart", "Philip Marlowe", 0),
        CastRow(4201, "Lauren Bacall", "Vivian Rutledge", 1),
        CastRow(4202, "John Ridgely", "Eddie Mars", 2),
        CastRow(4203, "Martha Vickers", "Carmen", 3),
        CastRow(4204, "Louis Jean Heydt", "Joe Brody", 4),
        CastRow(4205, "Charles Waldron", "The General", 5),
        CastRow(4206, "Regis Toomey", "Bernie Ohls", 6),
        CastRow(4207, "Sonia Darrin", "Agnes (uncredited)", 7),
    ), crew=(
        CrewRow(2636, "Howard Hawks", "Director", "Directing"),
        CrewRow(4301, "Leigh Brackett", "Screenplay", "Writing"),
        CrewRow(4302, "Raymond Chandler", "Novel", "Writing"),
    )), TODAY)
    # Ke$1ha (I3): a cast name carrying a literal "$1" — the one thing that can turn the note-click
    # handler's suggestion/correction replace into a String.replace backreference if it ever
    # regresses to a template-string replacement instead of a replacer function.
    repo.write_credits(ids["bravo (1960)"], _credits(911, "Bravo", "A holiday in the alpha quadrant.",
                                                     (CastRow(77, "Jane Bogart", "Nurse", 0),
                                                      CastRow(78, "Ke$1ha", "Singer", 1))), TODAY)
    # Hotel: a discovery film with no Criterion listing but buyable on the Apple TV store —
    # reachable (default scope) shows it, criterion scope hides it. Hungarian + no scores keep it
    # out of the default-English counts and at the tail of the default sort.
    hid = repo.create_film(Film("Hotel", 2021, None, ""))
    repo.upsert_omdb(hid, OmdbRating(None, None, True, "Hungarian", '{"Title":"Hotel"}'), TODAY)
    repo.record_listing_with_transition(hid, "apple-tv-store", "https://tmdb/w/2", TODAY)
    # "Wishlist it": Charlie is for sale and not wishlisted (the click film); Delta is for sale
    # and its add always fails (the failure line); Echo is already wishlisted and also carries a
    # list badge (the heart-comes-last film). All three hold a current Criterion listing, so the
    # store id changes nobody's reachability. Alpha stays owned + unwishlisted: no heart, no button.
    repo.set_external_id(ids["charlie (1970)"], "itunes", CHARLIE_ITUNES, TODAY)
    repo.set_external_id(ids["delta (1980)"], "itunes", DELTA_ITUNES, TODAY)
    repo.set_external_id(ids["echo (1990)"], "itunes", ECHO_ITUNES, TODAY)
    repo.mark_wishlisted(ids["echo (1990)"], TODAY)
    # Un-wishlist (brief 1.2): Kilo is already wishlisted and comes off cleanly (the un-wishlist
    # click film); November is already wishlisted and its removal always fails (the un-wishlist
    # failure film).
    repo.upsert_omdb(ids["kilo (2010)"], OmdbRating(None, None, False), TODAY)
    repo.upsert_omdb(ids["november (2011)"], OmdbRating(None, None, False), TODAY)
    repo.set_external_id(ids["kilo (2010)"], "itunes", KILO_ITUNES, TODAY)
    repo.set_external_id(ids["november (2011)"], "itunes", NOVEMBER_ITUNES, TODAY)
    repo.mark_wishlisted(ids["kilo (2010)"], TODAY)
    repo.mark_wishlisted(ids["november (2011)"], TODAY)


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
    app = create_app(seeded_repo, today=lambda: TODAY, wishlist=WishlistGateway(FakePrices(), FAKE_ACCOUNT))
    threading.Thread(target=lambda: app.run(host="127.0.0.1", port=port, use_reloader=False), daemon=True).start()
    time.sleep(0.5)
    yield f"http://127.0.0.1:{port}"


@pytest.fixture
def dash(page: Page, server: str) -> Page:
    page.goto(server)
    page.wait_for_selector("#films tbody[data-count]")
    return page
