import sqlite3
from datetime import date

from movie_brain.domain.models import Film, ListEntry, ListMeta
from movie_brain.infrastructure.database import _LISTS_SQL, _lists_by_film

CAHIERS = ListMeta(
    slug="cahiers-100",
    name="100 Films for an Ideal Cinematheque",
    curator="Cahiers du Cinéma",
    published_year=2008,
    source_url="https://www.filmdetail.com/2008/11/23/cahiers-du-cinemas-100-greatest-films/",
    ordered=True,
)

BACKLOG = ListMeta(
    slug="backlog-10",
    name="Backlog Ten",
    curator=None,
    published_year=None,
    source_url=None,
    ordered=False,
)


def test_upsert_film_list_creates_then_refreshes_metadata(repo, today):
    repo.upsert_film_list(CAHIERS, today)
    assert repo.film_list("cahiers-100") == CAHIERS

    refreshed = ListMeta(
        slug="cahiers-100",
        name="100 Films for an Ideal Cinematheque (renamed)",
        curator="Cahiers du Cinéma",
        published_year=2008,
        source_url=CAHIERS.source_url,
        ordered=True,
    )
    later = date(2026, 8, 20)
    repo.upsert_film_list(refreshed, later)
    assert repo.film_list("cahiers-100") == refreshed
    with sqlite3.connect(repo.db_path) as c:
        imported_at = c.execute("SELECT imported_at FROM film_list WHERE slug = 'cahiers-100'").fetchone()[0]
    assert imported_at == later.isoformat()


def test_film_list_returns_none_when_missing(repo):
    assert repo.film_list("nope") is None


def test_upsert_list_entry_is_idempotent_and_never_clears_film_id(repo, today):
    repo.upsert_film_list(CAHIERS, today)
    repo.upsert_list_entry("cahiers-100", ListEntry(1, "Citizen Kane", "Orson Welles"))
    fid = repo.create_film(Film("Citizen Kane", 1941, "Orson Welles", ""))
    assert fid is not None
    repo.link_list_entry("cahiers-100", 1, fid)

    entries = repo.list_entries("cahiers-100")
    assert entries == [(1, fid, "Citizen Kane", "Orson Welles", None, None)]

    # Re-importing the same file (e.g. a corrected director spelling) must update the
    # verbatim text but must NOT clear the film_id a human already linked.
    repo.upsert_list_entry("cahiers-100", ListEntry(1, "Citizen Kane", "Orson Wells"))
    entries = repo.list_entries("cahiers-100")
    assert entries == [(1, fid, "Citizen Kane", "Orson Wells", None, None)]


def test_upsert_list_entry_creates_unlinked_entry(repo, today):
    repo.upsert_film_list(CAHIERS, today)
    repo.upsert_list_entry("cahiers-100", ListEntry(2, "The Night of the Hunter", "Charles Laughton"))
    entries = repo.list_entries("cahiers-100")
    assert entries == [(2, None, "The Night of the Hunter", "Charles Laughton", None, None)]


def test_upsert_list_entry_persists_tt_listed(repo, today):
    repo.upsert_film_list(CAHIERS, today)
    repo.upsert_list_entry("cahiers-100", ListEntry(1, "Citizen Kane", "Orson Welles", "tt0033467"))
    entries = repo.list_entries("cahiers-100")
    assert entries == [(1, None, "Citizen Kane", "Orson Welles", "tt0033467", None)]


def test_upsert_list_entry_updates_tt_listed_without_clearing_film_id(repo, today):
    repo.upsert_film_list(CAHIERS, today)
    repo.upsert_list_entry("cahiers-100", ListEntry(1, "Citizen Kane", "Orson Welles"))
    fid = repo.create_film(Film("Citizen Kane", 1941, "Orson Welles", ""))
    assert fid is not None
    repo.link_list_entry("cahiers-100", 1, fid)

    # A re-import that now supplies an id (e.g. a source added a fourth column) must
    # update tt_listed but still must NOT clear the film_id a human already linked.
    repo.upsert_list_entry("cahiers-100", ListEntry(1, "Citizen Kane", "Orson Welles", "tt0033467"))
    entries = repo.list_entries("cahiers-100")
    assert entries == [(1, fid, "Citizen Kane", "Orson Welles", "tt0033467", None)]


def test_upsert_list_entry_persists_rank_label(repo, today):
    repo.upsert_film_list(CAHIERS, today)
    repo.upsert_list_entry("cahiers-100", ListEntry(3, "Born in Flames", "Lizzie Borden", rank_label="=243"))
    entries = repo.list_entries("cahiers-100")
    assert entries == [(3, None, "Born in Flames", "Lizzie Borden", None, "=243")]


def test_upsert_list_entry_updates_rank_label_without_clearing_film_id(repo, today):
    repo.upsert_film_list(CAHIERS, today)
    repo.upsert_list_entry("cahiers-100", ListEntry(1, "Citizen Kane", "Orson Welles", rank_label="=1"))
    fid = repo.create_film(Film("Citizen Kane", 1941, "Orson Welles", ""))
    assert fid is not None
    repo.link_list_entry("cahiers-100", 1, fid)

    # A re-import that resolves a tie (e.g. a corrected extraction) must update rank_label
    # but still must NOT clear the film_id a human already linked.
    repo.upsert_list_entry("cahiers-100", ListEntry(1, "Citizen Kane", "Orson Welles"))
    entries = repo.list_entries("cahiers-100")
    assert entries == [(1, fid, "Citizen Kane", "Orson Welles", None, None)]


def test_list_entries_ordered_by_rank(repo, today):
    repo.upsert_film_list(CAHIERS, today)
    repo.upsert_list_entry("cahiers-100", ListEntry(3, "Third", None))
    repo.upsert_list_entry("cahiers-100", ListEntry(1, "First", None))
    repo.upsert_list_entry("cahiers-100", ListEntry(2, "Second", None))
    assert [e.rank for e in repo.list_entries("cahiers-100")] == [1, 2, 3]


def test_film_rank_on_list_finds_and_misses(repo, today):
    repo.upsert_film_list(CAHIERS, today)
    repo.upsert_list_entry("cahiers-100", ListEntry(7, "Vertigo", "Alfred Hitchcock"))
    fid = repo.create_film(Film("Vertigo", 1958, "Alfred Hitchcock", ""))
    assert fid is not None
    assert repo.film_rank_on_list("cahiers-100", fid) is None  # not linked yet
    repo.link_list_entry("cahiers-100", 7, fid)
    assert repo.film_rank_on_list("cahiers-100", fid) == 7

    other = repo.create_film(Film("Rear Window", 1954, "Alfred Hitchcock", ""))
    assert other is not None
    assert repo.film_rank_on_list("cahiers-100", other) is None


def test_lists_by_film_issues_exactly_one_query(repo, today):
    assert "film_list_entry" in _LISTS_SQL and "ORDER BY e.film_id" in _LISTS_SQL
    repo.upsert_film_list(CAHIERS, today)
    repo.upsert_film_list(BACKLOG, today)
    repo.upsert_list_entry("cahiers-100", ListEntry(1, "Citizen Kane", "Orson Welles"))
    repo.upsert_list_entry("backlog-10", ListEntry(5, "Citizen Kane", "Orson Welles"))
    fid = repo.create_film(Film("Citizen Kane", 1941, "Orson Welles", ""))
    assert fid is not None
    repo.link_list_entry("cahiers-100", 1, fid)
    repo.link_list_entry("backlog-10", 5, fid)

    conn = sqlite3.connect(repo.db_path)
    conn.row_factory = sqlite3.Row
    seen: list[str] = []
    conn.set_trace_callback(seen.append)
    result = _lists_by_film(conn)
    conn.set_trace_callback(None)
    conn.close()

    # Nothing else runs on this connection, so exactly one statement proves
    # _lists_by_film fetches list membership for the whole view in one query.
    assert len(seen) == 1, f"expected exactly one query, got {seen}"
    assert "film_list_entry" in seen[0]
    assert result == {
        # both at default trust 1 — tie-broken by l.name: "100 Films..." sorts before
        # "Backlog Ten" (ASCII '1' < 'B')
        fid: [
            {
                "slug": "cahiers-100",
                "name": "100 Films for an Ideal Cinematheque",
                "curator": "Cahiers du Cinéma",
                "published": 2008,
                "ordered": True,
                "trust": 1,
                "rank": 1,
                "rank_label": None,
                "size": 1,
            },
            {
                "slug": "backlog-10",
                "name": "Backlog Ten",
                "curator": None,
                "published": None,
                "ordered": False,
                "trust": 1,
                "rank": 5,
                "rank_label": None,
                "size": 1,
            },
        ]
    }


def test_lists_by_film_carries_trust_and_orders_by_trust_desc_then_name(repo, today):
    """The read model's own ordering — trust descending, then name — is the ONLY place trust
    is visible in the UI (the drawer renders `d.lists` verbatim, in this order)."""
    repo.upsert_film_list(CAHIERS, today)  # name "100 Films..." sorts alphabetically first
    repo.upsert_film_list(BACKLOG, today)  # name "Backlog Ten"
    repo.set_list_trust("backlog-10", 9)  # lower-trust list nonetheless is named ("100 Films...")
    repo.upsert_list_entry("cahiers-100", ListEntry(1, "Vertigo", "Alfred Hitchcock"))
    repo.upsert_list_entry("backlog-10", ListEntry(1, "Vertigo", "Alfred Hitchcock"))
    fid = repo.create_film(Film("Vertigo", 1958, "Alfred Hitchcock", ""))
    assert fid is not None
    repo.link_list_entry("cahiers-100", 1, fid)
    repo.link_list_entry("backlog-10", 1, fid)

    conn = sqlite3.connect(repo.db_path)
    conn.row_factory = sqlite3.Row
    result = _lists_by_film(conn)
    conn.close()

    slugs = [entry["slug"] for entry in result[fid]]
    trusts = [entry["trust"] for entry in result[fid]]
    # backlog-10 (trust 9) sorts ahead of cahiers-100 (trust 1) despite naming alphabetically last.
    assert slugs == ["backlog-10", "cahiers-100"]
    assert trusts == [9, 1]


def test_lists_by_film_carries_rank_label(repo, today):
    """A tied rank must reach the read model as the printed label, not just the position."""
    repo.upsert_film_list(CAHIERS, today)
    repo.upsert_list_entry("cahiers-100", ListEntry(3, "Born in Flames", "Lizzie Borden", rank_label="=243"))
    fid = repo.create_film(Film("Born in Flames", 1983, "Lizzie Borden", ""))
    assert fid is not None
    repo.link_list_entry("cahiers-100", 3, fid)

    conn = sqlite3.connect(repo.db_path)
    conn.row_factory = sqlite3.Row
    result = _lists_by_film(conn)
    conn.close()
    assert result[fid][0]["rank"] == 3
    assert result[fid][0]["rank_label"] == "=243"


def test_list_views_populates_lists(repo, today):
    repo.record_catalog("criterion", [Film("Citizen Kane", 1941, "Orson Welles", "https://c/kane")], today)
    fid = repo.film_id_by_key("citizen kane (1941)")
    repo.upsert_film_list(CAHIERS, today)
    repo.upsert_list_entry("cahiers-100", ListEntry(1, "Citizen Kane", "Orson Welles"))
    repo.link_list_entry("cahiers-100", 1, fid)

    views = {v.title: v for v in repo.list_views("criterion", today)}
    assert views["Citizen Kane"].lists == [
        {
            "slug": "cahiers-100",
            "name": "100 Films for an Ideal Cinematheque",
            "curator": "Cahiers du Cinéma",
            "published": 2008,
            "ordered": True,
            "trust": 1,
            "rank": 1,
            "rank_label": None,
            "size": 1,
        }
    ]


def test_get_view_populates_lists(repo, today):
    fid = repo.create_film(Film("Citizen Kane", 1941, "Orson Welles", ""))
    assert fid is not None
    repo.upsert_film_list(CAHIERS, today)
    repo.upsert_list_entry("cahiers-100", ListEntry(1, "Citizen Kane", "Orson Welles"))
    repo.link_list_entry("cahiers-100", 1, fid)

    view = repo.get_view(fid, today)
    assert view is not None
    assert view.lists == [
        {
            "slug": "cahiers-100",
            "name": "100 Films for an Ideal Cinematheque",
            "curator": "Cahiers du Cinéma",
            "published": 2008,
            "ordered": True,
            "trust": 1,
            "rank": 1,
            "rank_label": None,
            "size": 1,
        }
    ]


def test_get_view_film_with_no_lists_is_empty(repo, today):
    fid = repo.create_film(Film("Unlisted", 2020, None, ""))
    assert fid is not None
    view = repo.get_view(fid, today)
    assert view is not None
    assert view.lists == []


def test_list_entries_carry_their_list_size(repo, today):
    fid = repo.create_film(Film("Citizen Kane", 1941, "Orson Welles", ""))
    other = repo.create_film(Film("The Rules of the Game", 1939, "Jean Renoir", ""))
    assert fid is not None and other is not None
    repo.upsert_film_list(CAHIERS, today)
    repo.upsert_list_entry("cahiers-100", ListEntry(1, "Citizen Kane", "Orson Welles"))
    repo.upsert_list_entry("cahiers-100", ListEntry(2, "The Rules of the Game", "Jean Renoir"))
    repo.link_list_entry("cahiers-100", 1, fid)
    repo.link_list_entry("cahiers-100", 2, other)

    entry = next(v for v in repo.list_views("criterion", today) if v.id == fid).lists[0]
    assert entry["size"] == 2  # the list's length, not our coverage of it
    assert entry["rank"] == 1


def test_list_size_counts_entries_that_are_not_linked_yet(repo, today):
    fid = repo.create_film(Film("Citizen Kane", 1941, "Orson Welles", ""))
    assert fid is not None
    repo.upsert_film_list(CAHIERS, today)
    repo.upsert_list_entry("cahiers-100", ListEntry(1, "Citizen Kane", "Orson Welles"))
    repo.upsert_list_entry("cahiers-100", ListEntry(2, "Something Unlinked", None))
    repo.link_list_entry("cahiers-100", 1, fid)

    entry = next(v for v in repo.list_views("criterion", today) if v.id == fid).lists[0]
    # rank 2 is deliberately never linked to a film — size must still count it.
    assert entry["size"] == 2


def test_merge_film_moves_film_list_entry_to_survivor(repo, today):
    loser = repo.create_film(Film("Vertigo (1958)", 1958, None, ""))
    survivor = repo.create_film(Film("Vertigo", 1958, "Alfred Hitchcock", ""))
    assert loser is not None and survivor is not None
    repo.upsert_film_list(CAHIERS, today)
    repo.upsert_list_entry("cahiers-100", ListEntry(7, "Vertigo", "Alfred Hitchcock"))
    repo.link_list_entry("cahiers-100", 7, loser)

    report = repo.merge_film(loser, survivor, today)
    assert report.moved.get("film_list_entry") == 1
    assert repo.film_rank_on_list("cahiers-100", survivor) == 7
    assert repo.film_rank_on_list("cahiers-100", loser) is None


# trust (design docs/superpowers/specs/2026-08-29-list-trust-and-tally-design.md) -----------


def test_new_list_defaults_to_trust_1(repo, today):
    repo.upsert_film_list(CAHIERS, today)
    assert repo.film_list("cahiers-100").trust == 1


def test_set_list_trust_updates_and_returns_true(repo, today):
    repo.upsert_film_list(CAHIERS, today)
    assert repo.set_list_trust("cahiers-100", 9) is True
    assert repo.film_list("cahiers-100").trust == 9


def test_set_list_trust_accepts_zero(repo, today):
    repo.upsert_film_list(CAHIERS, today)
    assert repo.set_list_trust("cahiers-100", 0) is True
    assert repo.film_list("cahiers-100").trust == 0


def test_set_list_trust_returns_false_for_unknown_slug(repo):
    assert repo.set_list_trust("nope", 9) is False


def test_film_lists_orders_by_trust_desc_then_slug(repo, today):
    repo.upsert_film_list(CAHIERS, today)  # slug "cahiers-100"
    repo.upsert_film_list(BACKLOG, today)  # slug "backlog-10"
    repo.set_list_trust("cahiers-100", 5)
    # both still at default trust 1: backlog-10 sorts before cahiers-100 by slug...
    repo.upsert_film_list(
        ListMeta(
            slug="alpha-list",
            name="Alpha",
            curator=None,
            published_year=None,
            source_url=None,
            ordered=False,
        ),
        today,
    )
    slugs = [m.slug for m in repo.film_lists()]
    # trust 5 first (cahiers-100), then the two trust-1 lists ordered by slug
    assert slugs == ["cahiers-100", "alpha-list", "backlog-10"]


def test_reimporting_a_list_preserves_a_previously_set_trust(repo, today):
    """The trap this task exists to close: `upsert_film_list` runs on every `lists import`,
    and a re-import (e.g. to pick up newly created films) must never reset the owner's
    trust judgement back to the default."""
    repo.upsert_film_list(CAHIERS, today)
    assert repo.set_list_trust("cahiers-100", 9) is True

    later = date(2026, 8, 20)
    refreshed = ListMeta(
        slug="cahiers-100",
        name=CAHIERS.name,
        curator=CAHIERS.curator,
        published_year=CAHIERS.published_year,
        source_url=CAHIERS.source_url,
        ordered=CAHIERS.ordered,
    )
    repo.upsert_film_list(refreshed, later)

    assert repo.film_list("cahiers-100").trust == 9
