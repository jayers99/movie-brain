# M3 — Repair & Merge Surface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give movie-brain a human-confirmed repair surface — identity dispositions (merge/alias/tombstone) that every ingester honors, `repair dupes|links|years` verbs, a `review` CLI that drains `match_review`, and the "needs revisit" drawer flag that feeds it — so the 49 dup groups, 28 id-conflicts, 23 remake-suspected rows and 7 Apple year-drifts are decidable instead of accumulating.

**Architecture:** Hexagonal, unchanged. A new `film_disposition` table (migration 008) is the identity ledger: a loser film row is never deleted, it gets a `merged`→survivor or `tombstoned` disposition; `Repository` exposes `merge_film`/`tombstone_film`/`canonical_film_id`, excludes disposed films from every read model, and aliases merged titles onto the survivor in the matching corpus so collectors can't resurrect them. New `application/repair.py` (dupes/links/years) and `application/review.py` (resolution + resurrection suppression) are use cases over the Repository; `cli.py` gains `repair` and `review` sub-apps. `needs_revisit` (migration 009) follows the watchlist pattern end to end (repo → FilmView → Flask route → drawer toggle → chip) and is cleared by the CLI when a film is resolved. The matcher gains one rule (rerelease-annotated query year + same-year twin + older same-title survivor → review) so the Metropolis case can be banked as ground truth with the dominance gate still green.

**Tech Stack:** Python 3.12, uv, SQLite, Typer/Rich, Flask, vanilla JS; pytest + pytest-bdd + responses + Playwright; ruff + mypy.

**Spec:** `docs/superpowers/specs/2026-08-23-matching-overhaul-design.md` (M3 section) + `docs/superpowers/handoffs/2026-08-24-m3-matching-handoff.md` (live findings 1–5, planning-decision bullet).

## Global Constraints

- Collectors never delete. Only the human-confirmed repair verbs (`repair dupes --apply`, `repair links --apply`, `review resolve`) may move or drop rows, and a film row itself is never deleted — it is dispositioned.
- Film identity = `films.guid`; the integer `id` is a join key. Dispositions reference `films.id` internally only.
- Schema change → new `migrations/NNN_*.sql` inserting its own `schema_version` row, wrapped in BEGIN/COMMIT. Never edit an applied migration. 008 = disposition, 009 = needs_revisit.
- `scripts/matching_benchmark.py --assert-dominance` must exit 0 at the end of every task that touches `domain/matching.py` or the benchmark.
- `uv run pytest`, `uv run ruff check .`, `uv run mypy` green at the end of every task.
- Canned-filter chip names live only in `domain/filters.py`; `CHIP_PREDICATES` in `app.js` and the chip buttons in `index.html` stay in lockstep.
- No scraping of metacritic.com anywhere; TMDB API calls only from `infrastructure/tmdb.py`.
- All work in a git worktree on branch `feature/M3-repair-surface`; one commit per task step "Commit" line.
- **Planning decision (handoff bullet):** backlog item 9 (needs-revisit flag) SHIPS IN M3 — Task 9. Rationale: the resolution CLI is the drain the flag was designed for; the watchlist pattern already exists twice (watchlist, owned) so the cost is one migration + ~120 lines.

---

## File map

| File | Responsibility |
|---|---|
| `migrations/008_disposition.sql` (create) | `film_disposition` table |
| `migrations/009_needs_revisit.sql` (create) | `needs_revisit` table |
| `src/movie_brain/infrastructure/database.py` (modify) | disposition primitives, `merge_film`, exclusions/aliasing in read models, review helpers, revisit, tmdb link clear, omdb refresh mark |
| `src/movie_brain/infrastructure/tmdb.py` (modify) | `TmdbClient.movie_titles(tmdb_id)` |
| `src/movie_brain/domain/matching.py` (modify) | rerelease-ambiguous rule |
| `src/movie_brain/domain/models.py` (modify) | `FilmView.needs_revisit`, `revisit_note` |
| `src/movie_brain/domain/filters.py` (modify) | `needs_revisit` chip |
| `src/movie_brain/application/review.py` (create) | `suppress_resolved`, `resolve_review` |
| `src/movie_brain/application/repair.py` (create) | `audit_dupes`/`repair_dupes`, `audit_links`/`repair_links`, `audit_years`/`repair_years` |
| `src/movie_brain/application/metacritic.py` (modify) | `create_from_staged`, tombstone guard, suppression |
| `src/movie_brain/application/owned.py` (modify) | canonical redirect, tombstone guard, suppression |
| `src/movie_brain/application/availability.py`, `rematch.py` (modify) | `queue_review_once` + no-match rebuild honour resolved rows |
| `src/movie_brain/cli.py` (modify) | `repair` and `review` sub-apps |
| `src/movie_brain/web/app.py`, `static/app.js`, `templates/index.html` (modify) | revisit route, toggle, chip |
| `scripts/matching_benchmark.py` (modify) | Metropolis ground-truth case |
| `tests/features/repair.feature`, `tests/step_defs/test_repair.py` (create) | merge/tombstone/dupes/links/years BDD |
| `tests/features/review.feature`, `tests/step_defs/test_review.py` (create) | resolution + suppression BDD |
| `tests/features/revisit.feature`, `tests/step_defs/test_revisit.py` (create) | needs-revisit BDD |
| `tests/unit/test_database.py`, `test_matching.py`, `test_filters.py`, `test_tmdb.py`, `test_cli.py`, `tests/web/test_api.py` (modify) | unit/API coverage |
| `docs/superpowers/specs/…design.md`, `docs/superpowers/handoffs/2026-08-25-m3-done-handoff.md`, `CLAUDE.md`, `docs/backlog.md` (modify/create) | Done line, handoff, docs |

Conventions the executor must know: `repo` fixture (`tests/conftest.py`) gives a fresh `Repository` on a tmp config dir; `today` fixture = `date(2026, 8, 19)`; BDD step files live in `tests/step_defs/` and call `scenarios("../features/<name>.feature")`; HTTP is mocked with `responses`; CLI tests use `typer.testing.CliRunner` against `movie_brain.cli.app` with `monkeypatch.setattr("movie_brain.cli.<fn>", fake)`.

---

### Task 1: Migration 008 + disposition primitives + `merge_film`

**Files:**
- Create: `migrations/008_disposition.sql`
- Modify: `src/movie_brain/infrastructure/database.py` (new section "dispositions" after `# owned`)
- Test: `tests/unit/test_database.py`

**Interfaces:**
- Produces:
  - `MergeReport(NamedTuple)`: `moved: dict[str, int]`, `dropped: dict[str, int]`, `reviews_resolved: int`
  - `Repository.disposition_of(film_id) -> tuple[str, int | None] | None` — `(kind, survivor_id)`
  - `Repository.canonical_film_id(film_id) -> int` — follows `merged` chains; tombstoned/undisposed return themselves
  - `Repository.tombstone_film(film_id, today, note=None) -> None`
  - `Repository.merge_film(loser_id, survivor_id, today, note=None) -> MergeReport`
  - `Repository.tombstoned_keys() -> set[str]`
  - `Repository.disposed_film_ids() -> set[int]`

- [ ] **Step 1: Write the migration**

```sql
-- M3: identity dispositions (spec: docs/superpowers/specs/2026-08-23-matching-overhaul-design.md, M3).
-- Films are immutable and never deleted; a duplicate or wrongly-created film gets a
-- disposition row instead. kind='merged' aliases the losing identity onto survivor_id
-- (its title still matches, but resolves to the survivor); kind='tombstoned' hides it and
-- blocks every collector from re-creating it. Only human-confirmed repair verbs write here.
BEGIN;
CREATE TABLE film_disposition (
    film_id     INTEGER PRIMARY KEY REFERENCES films(id),
    kind        TEXT NOT NULL CHECK (kind IN ('merged', 'tombstoned')),
    survivor_id INTEGER REFERENCES films(id),
    note        TEXT,
    created_at  TEXT NOT NULL,
    CHECK ((kind = 'merged') = (survivor_id IS NOT NULL))
);
INSERT INTO schema_version (version) VALUES (8);
COMMIT;
```

- [ ] **Step 2: Write the failing tests** (append to `tests/unit/test_database.py`)

```python
from datetime import date

from movie_brain.domain.models import Film, OmdbRating

D = date(2026, 8, 19)


def _two_films(repo):
    repo.record_catalog("criterion", [Film("Alpha", 1950, "Ann", "https://c/alpha")], D)
    a = repo.film_id_by_key("alpha (1950)")
    b = repo.create_film(Film("Alpha", 1951, None, ""))  # commerce twin, off-by-one year
    return a, b


def test_merge_moves_every_fk_and_records_disposition(repo):
    a, b = _two_films(repo)
    repo.set_external_id(b, "metacritic", "alpha-slug", D)
    repo.set_external_id(b, "tmdb", "77", D)
    repo.upsert_tmdb(b, found=True, looked_up=D)
    repo.upsert_omdb(b, OmdbRating(7.0, 80, True, "English", '{"Title": "Alpha"}'), D)
    repo.set_rating(b, 8, D)
    repo.toggle_watchlist(b, D)
    repo.mark_owned(b, D)
    repo.record_listing_with_transition(b, "max", "https://m/alpha", D)
    repo.append_reviews("tmdb", [__import__("movie_brain.domain.models", fromlist=["ReviewEntry"]).ReviewEntry("id-conflict", film_id=b, value="77")], D)

    report = repo.merge_film(b, a, D, note="twin")

    assert repo.disposition_of(b) == ("merged", a)
    assert repo.canonical_film_id(b) == a and repo.canonical_film_id(a) == a
    assert repo.external_ids_for(a) == {"criterion": "https://c/alpha", "metacritic": "alpha-slug", "tmdb": "77"}
    assert repo.external_ids_for(b) == {}
    assert a in repo.owned_film_ids() and a in repo.watchlist_film_ids()
    assert repo.all_my_ratings() == {"alpha (1950)": 8}
    assert repo.get_payload(a) == '{"Title": "Alpha"}'
    assert [t for t in repo.films_for_provider_refresh() if t[0] == a] == [(a, "77", True)]
    assert report.moved["listings"] == 1 and report.reviews_resolved == 1
    assert repo.open_reviews("tmdb") == []
    with __import__("sqlite3").connect(repo.db_path) as c:
        assert c.execute("SELECT film_id FROM availability_transitions").fetchall() == [(a,)]
        assert c.execute("SELECT COUNT(*) FROM films").fetchone()[0] == 2  # loser row kept


def test_merge_keeps_survivor_rows_on_conflict_and_notes_dropped(repo):
    a, b = _two_films(repo)
    repo.set_external_id(a, "tmdb", "1", D)
    repo.set_external_id(b, "tmdb", "2", D)
    repo.set_rating(a, 9, D)
    repo.set_rating(b, 3, D)
    report = repo.merge_film(b, a, D)
    assert repo.external_ids_for(a)["tmdb"] == "1"
    assert repo.all_my_ratings() == {"alpha (1950)": 9}
    assert report.dropped == {"external_ids": 1, "my_ratings": 1}


def test_merge_listing_conflict_widens_seen_window(repo):
    a, b = _two_films(repo)
    repo.record_listing(a, "max", "https://m/a", date(2026, 8, 10))
    repo.record_listing(b, "max", "https://m/b", date(2026, 8, 1))
    repo.record_listing(b, "max", "https://m/b", date(2026, 8, 19))
    repo.merge_film(b, a, D)
    with __import__("sqlite3").connect(repo.db_path) as c:
        row = c.execute("SELECT first_seen, last_seen, url FROM listings WHERE film_id = ? AND source='max'", (a,)).fetchone()
    assert row == ("2026-08-01", "2026-08-19", "https://m/a")


def test_merge_rejects_self_disposed_and_unknown(repo):
    import pytest

    a, b = _two_films(repo)
    with pytest.raises(ValueError):
        repo.merge_film(a, a, D)
    with pytest.raises(ValueError):
        repo.merge_film(999, a, D)
    repo.tombstone_film(b, D, note="junk")
    assert repo.disposition_of(b) == ("tombstoned", None)
    assert repo.tombstoned_keys() == {"alpha (1951)"}
    assert repo.disposed_film_ids() == {b}
    with pytest.raises(ValueError):
        repo.merge_film(b, a, D)
    with pytest.raises(ValueError):
        repo.merge_film(a, b, D)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_database.py -k "merge or tombstone" -v`
Expected: FAIL with `AttributeError: 'Repository' object has no attribute 'merge_film'`

- [ ] **Step 4: Implement** (append to `database.py`; add `import json` at top; add `MergeReport` next to `TmdbMatchTarget`)

```python
class MergeReport(NamedTuple):
    moved: dict[str, int]
    dropped: dict[str, int]
    reviews_resolved: int


_ONE_ROW_TABLES = ("omdb", "tmdb", "my_ratings", "watchlist", "owned")  # film_id PRIMARY KEY tables
```

```python
    # dispositions -----------------------------------------------------
    def disposition_of(self, film_id: int) -> tuple[str, int | None] | None:
        with self._conn() as c:
            row = c.execute("SELECT kind, survivor_id FROM film_disposition WHERE film_id = ?", (film_id,)).fetchone()
            return None if row is None else (str(row["kind"]), row["survivor_id"])

    def canonical_film_id(self, film_id: int) -> int:
        """Follow merged→survivor chains; tombstoned and undisposed films are their own canon."""
        seen: set[int] = set()
        with self._conn() as c:
            while film_id not in seen:
                seen.add(film_id)
                row = c.execute(
                    "SELECT survivor_id FROM film_disposition WHERE film_id = ? AND kind = 'merged'", (film_id,)
                ).fetchone()
                if row is None:
                    return film_id
                film_id = int(row["survivor_id"])
            return film_id

    def disposed_film_ids(self) -> set[int]:
        with self._conn() as c:
            return {int(r["film_id"]) for r in c.execute("SELECT film_id FROM film_disposition")}

    def tombstoned_keys(self) -> set[str]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT f.key FROM films f JOIN film_disposition d ON d.film_id = f.id WHERE d.kind = 'tombstoned'"
            ).fetchall()
            return {str(r["key"]) for r in rows}

    def _assert_repairable(self, c: sqlite3.Connection, film_id: int) -> None:
        if c.execute("SELECT 1 FROM films WHERE id = ?", (film_id,)).fetchone() is None:
            raise ValueError(f"unknown film {film_id}")
        if c.execute("SELECT 1 FROM film_disposition WHERE film_id = ?", (film_id,)).fetchone() is not None:
            raise ValueError(f"film {film_id} is already dispositioned")

    def tombstone_film(self, film_id: int, today: date, note: str | None = None) -> None:
        with self._conn() as c:
            self._assert_repairable(c, film_id)
            c.execute(
                "INSERT INTO film_disposition (film_id, kind, survivor_id, note, created_at) "
                "VALUES (?, 'tombstoned', NULL, ?, ?)",
                (film_id, note, today.isoformat()),
            )

    def merge_film(self, loser_id: int, survivor_id: int, today: date, note: str | None = None) -> MergeReport:
        """Human-confirmed merge: move every dependent row to the survivor, alias the loser.

        One transaction. Survivor rows win on conflict (the dropped loser values are kept
        in the disposition note); listings widen to the union of both seen windows;
        transitions (append-only history) simply re-point; the loser's open reviews are
        resolved as part of the merge. The loser film row is never deleted.
        """
        if loser_id == survivor_id:
            raise ValueError("loser and survivor are the same film")
        moved: dict[str, int] = {}
        dropped: dict[str, int] = {}
        kept: dict[str, list[object]] = {}
        with self._conn() as c:
            self._assert_repairable(c, loser_id)
            self._assert_repairable(c, survivor_id)
            for table in _ONE_ROW_TABLES:
                if c.execute(f"SELECT 1 FROM {table} WHERE film_id = ?", (loser_id,)).fetchone() is None:
                    continue
                if c.execute(f"SELECT 1 FROM {table} WHERE film_id = ?", (survivor_id,)).fetchone() is None:
                    c.execute(f"UPDATE {table} SET film_id = ? WHERE film_id = ?", (survivor_id, loser_id))
                    moved[table] = 1
                else:
                    c.execute(f"DELETE FROM {table} WHERE film_id = ?", (loser_id,))
                    dropped[table] = 1
            for row in c.execute("SELECT * FROM listings WHERE film_id = ?", (loser_id,)).fetchall():
                twin = c.execute(
                    "SELECT first_seen, last_seen, leaving_date FROM listings WHERE film_id = ? AND source = ?",
                    (survivor_id, row["source"]),
                ).fetchone()
                if twin is None:
                    c.execute(
                        "UPDATE listings SET film_id = ? WHERE film_id = ? AND source = ?",
                        (survivor_id, loser_id, row["source"]),
                    )
                    moved["listings"] = moved.get("listings", 0) + 1
                else:
                    c.execute(
                        "UPDATE listings SET first_seen = MIN(first_seen, ?), last_seen = MAX(last_seen, ?), "
                        "leaving_date = COALESCE(leaving_date, ?) WHERE film_id = ? AND source = ?",
                        (row["first_seen"], row["last_seen"], row["leaving_date"], survivor_id, row["source"]),
                    )
                    c.execute("DELETE FROM listings WHERE film_id = ? AND source = ?", (loser_id, row["source"]))
                    dropped["listings"] = dropped.get("listings", 0) + 1
            for row in c.execute("SELECT authority, value FROM external_ids WHERE film_id = ?", (loser_id,)).fetchall():
                held = c.execute(
                    "SELECT 1 FROM external_ids WHERE film_id = ? AND authority = ?", (survivor_id, row["authority"])
                ).fetchone()
                if held is None:
                    c.execute(
                        "UPDATE external_ids SET film_id = ? WHERE film_id = ? AND authority = ?",
                        (survivor_id, loser_id, row["authority"]),
                    )
                    moved["external_ids"] = moved.get("external_ids", 0) + 1
                else:
                    c.execute(
                        "DELETE FROM external_ids WHERE film_id = ? AND authority = ?", (loser_id, row["authority"])
                    )
                    dropped["external_ids"] = dropped.get("external_ids", 0) + 1
                    kept.setdefault("external_ids", []).append({row["authority"]: row["value"]})
            cur = c.execute(
                "UPDATE availability_transitions SET film_id = ? WHERE film_id = ?", (survivor_id, loser_id)
            )
            if cur.rowcount:
                moved["availability_transitions"] = cur.rowcount
            cur = c.execute(
                "UPDATE match_review SET resolved = 1, detail = COALESCE(detail, '') || ? "
                "WHERE film_id = ? AND resolved = 0",
                (f" [merged into film {survivor_id} {today.isoformat()}]", loser_id),
            )
            full_note = json.dumps({"note": note, "dropped": kept}) if (note or kept) else None
            c.execute(
                "INSERT INTO film_disposition (film_id, kind, survivor_id, note, created_at) "
                "VALUES (?, 'merged', ?, ?, ?)",
                (loser_id, survivor_id, full_note, today.isoformat()),
            )
            return MergeReport(moved, dropped, cur.rowcount)
```

Note `needs_revisit` is added to `_ONE_ROW_TABLES` in Task 9 — but a loser's revisit flag is a resolution, so Task 9 DELETES the loser's row instead of moving it (see Task 9 Step 4).

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_database.py -v && uv run ruff check . && uv run mypy`
Expected: all PASS (existing tests included — migration 008 applies cleanly on the test DB).

- [ ] **Step 6: Commit**

```bash
git add migrations/008_disposition.sql src/movie_brain/infrastructure/database.py tests/unit/test_database.py
git commit -m "M3: film_disposition ledger + merge_film/tombstone primitives (loser rows never deleted)"
```

---

### Task 2: Every ingester and read model honours dispositions

**Files:**
- Modify: `src/movie_brain/infrastructure/database.py` (`_VIEW_SQL` callers, `films_for_matching`, `record_catalog`, `_current_rows`, `films_needing_lookup_discovery`, `_TMDB_TARGET_SELECT` callers, `commerce_films_with_tmdb`, `films_tmdb_missed`, `films_for_provider_refresh`, `films_for_watchlist_refresh`)
- Modify: `src/movie_brain/application/metacritic.py:219-236` (`promote_top_n` loop), `src/movie_brain/application/owned.py:93-102`
- Create: `tests/features/repair.feature`, `tests/step_defs/test_repair.py`

**Interfaces:**
- Consumes: Task 1 primitives.
- Produces: `films_for_matching()` returns alias rows (merged loser title with `id = survivor`), excludes tombstoned; every other film query excludes disposed ids via `_NOT_DISPOSED`.

- [ ] **Step 1: Write the failing BDD scenarios**

`tests/features/repair.feature`:
```gherkin
Feature: Dispositioned films stay out of every collector's way

  Background:
    Given a repository with films "Alpha (1950)" on Criterion and "Alpha (1951)" from commerce

  Scenario: A merged film disappears from the dashboard view but its title still resolves to the survivor
    When I merge "Alpha (1951)" into "Alpha (1950)"
    Then the dashboard lists 1 film titled "Alpha"
    And matching the Metacritic title "Alpha" year 1951 resolves to "Alpha (1950)"

  Scenario: A Criterion re-walk of a merged film's key writes to the survivor
    When I merge "Alpha (1951)" into "Alpha (1950)"
    And Criterion lists "Alpha (1951)" again
    Then "Alpha (1950)" has a criterion listing and "Alpha (1951)" has none

  Scenario: Promotion never resurrects a tombstoned film
    Given "Alpha (1951)" is tombstoned
    When the Metacritic archive stages "Alpha" (1951) as slug "alpha-1951"
    And the top 10 staged titles are promoted
    Then no film was promoted and slug "alpha-1951" is unclaimed

  Scenario: Owned import marks the survivor, never a tombstone or a merged loser
    When I merge "Alpha (1951)" into "Alpha (1950)"
    And the Apple library contains "Alpha" from 1951
    Then "Alpha (1950)" is owned and "Alpha (1951)" is not

  Scenario: Discovery lookups skip dispositioned films
    Given "Alpha (1951)" is tombstoned
    Then no discovery film needs an OMDb lookup
    And no film needs a TMDB match except "Alpha (1950)"
```

`tests/step_defs/test_repair.py` (this file grows in Tasks 4–6; start it here):
```python
from __future__ import annotations

import re
from datetime import date

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.metacritic import promote_top_n
from movie_brain.application.owned import import_owned
from movie_brain.domain.matching import build_candidate_index, match_film
from movie_brain.domain.models import Film, McTitle, OwnedTitle

scenarios("../features/repair.feature")

TODAY = date(2026, 8, 19)


def _key(spec: str) -> str:
    m = re.fullmatch(r"(.+) \((\d{4})\)", spec)
    assert m
    return f"{m.group(1).lower()} ({m.group(2)})"


@pytest.fixture
def ctx(repo, config_dir):
    return {"repo": repo, "config_dir": config_dir, "promote": None}


@given(parsers.parse('a repository with films "{crit}" on Criterion and "{comm}" from commerce'))
def seed(ctx, crit, comm):
    cm = re.fullmatch(r"(.+) \((\d{4})\)", crit)
    ctx["repo"].record_catalog("criterion", [Film(cm.group(1), int(cm.group(2)), "Ann", "https://c/alpha")], TODAY)
    mm = re.fullmatch(r"(.+) \((\d{4})\)", comm)
    ctx["repo"].create_film(Film(mm.group(1), int(mm.group(2)), None, ""))


@given(parsers.parse('"{spec}" is tombstoned'))
def tombstone(ctx, spec):
    ctx["repo"].tombstone_film(ctx["repo"].film_id_by_key(_key(spec)), TODAY, note="test")


@when(parsers.parse('I merge "{loser}" into "{survivor}"'))
def merge(ctx, loser, survivor):
    r = ctx["repo"]
    r.merge_film(r.film_id_by_key(_key(loser)), r.film_id_by_key(_key(survivor)), TODAY)


@when(parsers.parse('Criterion lists "{spec}" again'))
def rewalk(ctx, spec):
    m = re.fullmatch(r"(.+) \((\d{4})\)", spec)
    ctx["repo"].record_catalog("criterion", [Film(m.group(1), int(m.group(2)), "Ann", "https://c/alpha-1")], TODAY)


@when(parsers.parse('the Metacritic archive stages "{title}" ({year:d}) as slug "{slug}"'))
def stage(ctx, title, year, slug):
    ctx["repo"].upsert_mc_titles([McTitle(slug, title, year, 90, 1, 1)], TODAY)


@when(parsers.parse("the top {n:d} staged titles are promoted"))
def promote(ctx, n, monkeypatch):
    # Archive parsing is bypassed: match_archive reads the staged table through the parser
    # mock below, exactly like tests/step_defs/test_metacritic.py does.
    from movie_brain.infrastructure import metacritic as mc

    staged = ctx["repo"].top_staged_titles(n)
    monkeypatch.setattr(mc, "archived_pages", lambda _archive: ["p1"])
    monkeypatch.setattr(mc, "parse_archive", lambda _archive: staged)
    ctx["promote"] = promote_top_n(ctx["repo"], ctx["config_dir"], TODAY, n)


@when(parsers.parse('the Apple library contains "{title}" from {year:d}'))
def apple(ctx, title, year):
    import_owned(ctx["repo"], ctx["config_dir"], TODAY, fetch=lambda: [OwnedTitle(title, year)])


@then(parsers.parse('the dashboard lists {n:d} film titled "{title}"'))
def dashboard(ctx, n, title):
    assert sum(1 for v in ctx["repo"].list_views("criterion", TODAY) if v.title == title) == n


@then(parsers.parse('matching the Metacritic title "{title}" year {year:d} resolves to "{spec}"'))
def resolves(ctx, title, year, spec):
    index = build_candidate_index(ctx["repo"].films_for_matching())
    assert match_film(title, year, index).winner == ctx["repo"].film_id_by_key(_key(spec))


@then(parsers.parse('"{a}" has a criterion listing and "{b}" has none'))
def listing_moved(ctx, a, b):
    r = ctx["repo"]
    ids = {fid for fid, _ in r.current_films("criterion")}
    assert r.film_id_by_key(_key(a)) in ids and r.film_id_by_key(_key(b)) not in ids


@then(parsers.parse('no film was promoted and slug "{slug}" is unclaimed'))
def not_promoted(ctx, slug):
    assert ctx["promote"].promoted == 0
    assert slug not in ctx["repo"].claimed_values("metacritic")


@then(parsers.parse('"{a}" is owned and "{b}" is not'))
def owned(ctx, a, b):
    r = ctx["repo"]
    assert r.film_id_by_key(_key(a)) in r.owned_film_ids()
    assert r.film_id_by_key(_key(b)) not in r.owned_film_ids()


@then("no discovery film needs an OMDb lookup")
def no_discovery(ctx):
    assert ctx["repo"].films_needing_lookup_discovery("criterion", TODAY) == []


@then(parsers.parse('no film needs a TMDB match except "{spec}"'))
def only_one_tmdb(ctx, spec):
    assert [t.film_id for t in ctx["repo"].films_needing_tmdb_match()] == [ctx["repo"].film_id_by_key(_key(spec))]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/step_defs/test_repair.py -v`
Expected: the first scenario fails on `the dashboard lists 1 film` (2 listed), the others fail similarly.

- [ ] **Step 3: Implement the read-model exclusions** in `database.py`

Add after `_TMDB_TARGET_SELECT`:
```python
_NOT_DISPOSED = "NOT EXISTS (SELECT 1 FROM film_disposition d WHERE d.film_id = f.id)"
```
Apply it:
- `list_views`: `_VIEW_SQL + "WHERE " + _NOT_DISPOSED + " AND (l.film_id IS NULL OR l.last_seen = (...) OR r.score IS NOT NULL) ORDER BY f.id"` (wrap the existing three-way OR in parentheses).
- `get_view`: `_VIEW_SQL + "WHERE f.id = ? AND " + _NOT_DISPOSED`.
- `_current_rows`: append `" AND " + _NOT_DISPOSED` before `extra_where`.
- `films_needing_lookup_discovery`: add `"AND " + _NOT_DISPOSED + " "` after the `NOT EXISTS (… listings …)` clause.
- `films_needing_tmdb_match`: `"WHERE " + _NOT_DISPOSED + " AND NOT EXISTS (SELECT 1 FROM tmdb …)"`.
- `films_tmdb_missed_targets`: `"JOIN tmdb t ON t.film_id = f.id WHERE t.found = 0 AND " + _NOT_DISPOSED`.
- `commerce_films_with_tmdb`: add `"AND " + _NOT_DISPOSED + " "`.
- `films_tmdb_missed`: `"WHERE t.found = 0 AND " + _NOT_DISPOSED`.
- `films_for_provider_refresh` / `films_for_watchlist_refresh`: these select from `tmdb t` — add `"AND NOT EXISTS (SELECT 1 FROM film_disposition d WHERE d.film_id = t.film_id) "` after `WHERE t.found = 1 `.

`films_for_matching` — alias merged losers onto their survivor, drop tombstones:
```python
    def films_for_matching(self) -> list[FilmRow]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT COALESCE(d.survivor_id, f.id) AS id, f.title, f.year, "
                "COALESCE(f.director, NULLIF(json_extract(o.payload, '$.Director'), 'N/A')) AS director, "
                "NULLIF(json_extract(o.payload, '$.Runtime'), 'N/A') AS runtime, "
                "o.metacritic "
                "FROM films f LEFT JOIN omdb o ON o.film_id = f.id "
                "LEFT JOIN film_disposition d ON d.film_id = f.id "
                "WHERE d.film_id IS NULL OR d.kind = 'merged' ORDER BY f.id"
            ).fetchall()
```
(the rest of the method is unchanged; the alias row carries the loser's title/year evidence under the survivor's id — that is the "alias" the spec asks for.)

`record_catalog` — redirect writes to the canonical film:
```python
            dispositions = {
                int(r["film_id"]): (str(r["kind"]), r["survivor_id"])
                for r in c.execute("SELECT film_id, kind, survivor_id FROM film_disposition")
            }
            for film in films:
                c.execute(...upsert unchanged...)
                film_id = int(c.execute("SELECT id FROM films WHERE key = ?", (film.key,)).fetchone()["id"])
                while film_id in dispositions and dispositions[film_id][0] == "merged":
                    film_id = int(dispositions[film_id][1])  # alias → survivor (chains allowed)
                self._write_listing(c, film_id, source, film.url, day, frontier)
                ...
```
(A tombstoned film reappearing on Criterion is a real listing for a film the human hid — write it to the tombstone's own id; it stays hidden from the view. Log nothing.)

- [ ] **Step 4: Implement the create-path guards**

`application/metacritic.py` `promote_top_n`, before `film = Film(...)` add `tombstoned = repo.tombstoned_keys()` above the loop and inside:
```python
        film = Film(clean_title(t.title), t.year, None, MC_MOVIE_URL.format(slug=t.slug))
        if film.key in tombstoned:
            skipped += 1
            continue
        film_id = repo.create_film(film)
        if film_id is None:
            existing = repo.canonical_film_id(repo.film_id_by_key(film.key) or 0)
            conflicts += 1
            detail = f"promotion of {t.title!r} ({t.year}) collides with existing key {film.key!r}"
            reviews.append(ReviewEntry("key-conflict", film_id=existing, value=t.slug, detail=detail))
            continue
```

`application/owned.py`, the `else:` create branch:
```python
        else:
            film = Film(cleaned, year, None, "")
            if film.key in tombstoned:
                log(f"skipping tombstoned film {film.key!r} from the Apple library")
                continue
            new_id = repo.create_film(film)
            if new_id is None:
                # Exact film_key collision: that IS the film (same title+year) — or its alias.
                film_id = repo.canonical_film_id(repo.film_id_by_key(film.key) or 0)
                matched += 1
```
with `tombstoned = repo.tombstoned_keys()` computed once before the loop. Matched winners (`result.winner`) already come from the aliased index, so they are canonical.

- [ ] **Step 5: Run everything**

Run: `uv run pytest && uv run ruff check . && uv run mypy`
Expected: all green (388 + new).

- [ ] **Step 6: Commit**

```bash
git add -A src tests
git commit -m "M3: every ingester and read model honours film dispositions (alias merged, hide tombstoned)"
```

---

### Task 3: Bank Metropolis as ground truth + rerelease-ambiguous matcher rule

**Files:**
- Modify: `scripts/matching_benchmark.py` (`GROUND_TRUTHS`), `src/movie_brain/domain/matching.py` (`match_candidates`)
- Test: `tests/unit/test_matching.py`

**Interfaces:**
- Produces: new review reason `"rerelease-ambiguous"` (mapped to a `year-gap` review row by `match_archive`, exactly like other non-tie reasons).

- [ ] **Step 1: Bank the case** (append to `GROUND_TRUTHS`, after the last entry)

```python
    Case(
        # Live 2026-08-24: MC slug metropolis-re-release (Lang 1927, 2002 restoration) carried
        # commerce year 2001; the 2001 anime "Metropolis" matched on year evidence with no gap,
        # so neither review nor arbitration fired. The annotation says 2001 is an EDITION year,
        # so a same-year twin next to an older same-title film must go to review.
        name="metropolis-rerelease-same-year-twin",
        source="metacritic",
        title="Metropolis (re-release)",
        year=2001,
        pool=(
            PoolFilm(1, "Metropolis", 1927, "Fritz Lang", 153),
            PoolFilm(2, "Metropolis", 2001, "Rintaro", 108),
        ),
        expect="review",
    ),
```

- [ ] **Step 2: Unit test the rule** (append to `tests/unit/test_matching.py`)

```python
def test_rerelease_hint_with_same_year_twin_and_older_original_is_review():
    from movie_brain.domain.matching import Candidate, match_film

    pool = [Candidate(1, "Metropolis", 1927), Candidate(2, "Metropolis", 2001)]
    assert match_film("Metropolis (re-release)", 2001, pool).reason == "rerelease-ambiguous"
    # No annotation → the exact-year film is the honest answer.
    assert match_film("Metropolis", 2001, pool).winner == 2
    # Annotation but no same-year twin → hint excuses the gap, original matches (Lawrence class).
    assert match_film("Metropolis (re-release)", 2001, [Candidate(1, "Metropolis", 1927)]).winner == 1
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/unit/test_matching.py -k rerelease_hint -v; uv run python scripts/matching_benchmark.py --assert-dominance`
Expected: test FAILS (winner == 2); benchmark exits non-zero reporting 1 wrong-match on `metropolis-rerelease-same-year-twin`.

- [ ] **Step 4: Implement** — in `match_candidates`, immediately after the winner is chosen (before `if result.gap and not (...)`):

```python
    if rerelease_hint and result.year_points == 2 and any(r.gap for _, r in survivors):
        # The source flagged this as an edition, so its year is an edition year, not
        # evidence — yet an exact-year same-title film sits beside an older one. Either
        # could be right (re-release of the older vs a same-titled newer film): never guess.
        return MatchVerdict(kind="review", reason="rerelease-ambiguous")
```

- [ ] **Step 5: Verify**

Run: `uv run pytest && uv run python scripts/matching_benchmark.py --assert-dominance && uv run ruff check . && uv run mypy`
Expected: suite green; benchmark prints ground truth 26/26 pass, 0 wrong-match, review% unchanged within tolerance (<5%), exit 0.

- [ ] **Step 6: Commit**

```bash
git add scripts/matching_benchmark.py src/movie_brain/domain/matching.py tests/unit/test_matching.py
git commit -m "M3: bank Metropolis same-year-twin case; rerelease-annotated year is not evidence beside an older twin"
```

---

### Task 4: `review` resolution + resurrection suppression

**Files:**
- Create: `src/movie_brain/application/review.py`, `tests/features/review.feature`, `tests/step_defs/test_review.py`
- Modify: `database.py` (review helpers), `application/availability.py` (`queue_review_once`, rebuild), `application/rematch.py` (rebuild), `application/metacritic.py` (`match_archive` suppression + `create_from_staged`), `application/owned.py` (suppression)

**Interfaces:**
- Produces (Repository):
  - `review(review_id) -> dict[str, object] | None` — keys `id, authority, film_id, value, reason, detail, created_at, resolved`
  - `list_reviews(authority=None, reason=None) -> list[dict]` (open rows, with `title`/`year` of `film_id` joined when present)
  - `resolve_review(review_id, note) -> None`
  - `resolved_review_keys(authority) -> set[tuple[str, int | None, str | None]]` — `(reason, film_id, value)` of resolved rows
  - `staged_title(slug) -> McTitle | None`
  - `tmdb_target(film_id) -> TmdbMatchTarget | None`
- Produces (application/review.py):
  - `suppress_resolved(repo, authority, entries) -> list[ReviewEntry]`
  - `resolve_review(repo, review_id, *, film_id=None, tmdb_id=None, create=False, dismiss=False, today, client=None, note=None) -> str` — returns a one-line outcome; raises `ValueError` on invalid combinations
- Produces (application/metacritic.py): `create_from_staged(repo, title: McTitle, today) -> int | None`

- [ ] **Step 1: Write the BDD scenarios**

`tests/features/review.feature`:
```gherkin
Feature: match_review rows are resolved by CLI and never come back

  Background:
    Given films "Alpha (1950)" on Criterion and "King Kong (1933)" from commerce

  Scenario: Dismissing a tmdb no-match keeps it out of the next rebuild
    Given an open tmdb "no-match" review for "King Kong (1933)"
    When I resolve it with dismiss
    Then the review is resolved
    And rebuilding the tmdb no-match queue queues nothing for "King Kong (1933)"

  Scenario: Matching a no-match to a TMDB id claims the id and adopts the year
    Given an open tmdb "no-match" review for "King Kong (1933)"
    And TMDB says id 244 was released in 1933
    When I resolve it with tmdb id 244
    Then "King Kong (1933)" has tmdb id "244" and is found

  Scenario: A metacritic remake-suspected slug is created as its own film
    Given the archive staged "King Kong" (2005) as slug "king-kong-2005"
    And an open metacritic "year-gap" review for slug "king-kong-2005"
    When I resolve it with create
    Then a film "King Kong (2005)" exists holding metacritic slug "king-kong-2005"
    And re-running the archive match queues nothing for slug "king-kong-2005"

  Scenario: A metacritic slug is matched to an existing film
    Given the archive staged "Alpha" (1990) as slug "alpha-rr"
    And an open metacritic "year-gap" review for slug "alpha-rr"
    When I resolve it with film "Alpha (1950)"
    Then "Alpha (1950)" holds metacritic slug "alpha-rr"

  Scenario: An apple-tv year-drift is matched to a film and marks it owned
    Given an open apple-tv "year-drift" review for title "Alpha (Restored Version)"
    When I resolve it with film "Alpha (1950)"
    Then "Alpha (1950)" is owned
    And a later owned import of "Alpha (Restored Version)" year 2020 queues nothing

  Scenario: An apple-tv year-drift creates a new owned film
    Given an open apple-tv "year-drift" review for title "Alpha (2020)"
    When I resolve it with create
    Then a film "Alpha (2020)" exists and is owned

  Scenario: A tmdb id-conflict resolved to the holder merges the twins
    Given "Alpha (1950)" holds tmdb id "5"
    And an open tmdb "id-conflict" review for "King Kong (1933)" claiming id "5"
    When I resolve it with film "Alpha (1950)"
    Then "King Kong (1933)" is merged into "Alpha (1950)"

  Scenario: Invalid combinations are refused
    Given an open tmdb "no-match" review for "King Kong (1933)"
    Then resolving it with create fails
    And resolving it with both dismiss and film "Alpha (1950)" fails
```

`tests/step_defs/test_review.py`:
```python
from __future__ import annotations

import json
import re
from datetime import date

import pytest
import responses
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application import review as rv
from movie_brain.application.availability import TMDB_AUTHORITY
from movie_brain.application.metacritic import match_archive
from movie_brain.application.owned import import_owned
from movie_brain.domain.models import Film, McTitle, OwnedTitle, ReviewEntry
from movie_brain.infrastructure.tmdb import TMDB_API, TmdbClient

scenarios("../features/review.feature")
TODAY = date(2026, 8, 19)


def _split(spec):
    m = re.fullmatch(r"(.+) \((\d{4})\)", spec)
    return m.group(1), int(m.group(2))


def _id(repo, spec):
    t, y = _split(spec)
    return repo.film_id_by_key(f"{t.lower()} ({y})")


@pytest.fixture
def ctx(repo, config_dir):
    rs = responses.RequestsMock(assert_all_requests_are_fired=False)
    rs.start()
    yield {"repo": repo, "config_dir": config_dir, "rs": rs, "review_id": None, "client": None}
    rs.stop()
    rs.reset()


@given(parsers.parse('films "{crit}" on Criterion and "{comm}" from commerce'))
def seed(ctx, crit, comm):
    t, y = _split(crit)
    ctx["repo"].record_catalog("criterion", [Film(t, y, "Ann", f"https://c/{t.lower()}")], TODAY)
    t, y = _split(comm)
    ctx["repo"].create_film(Film(t, y, None, ""))


@given(parsers.parse('an open {authority} "{reason}" review for "{spec}"'))
def open_for_film(ctx, authority, reason, spec):
    fid = _id(ctx["repo"], spec)
    if authority == "tmdb" and reason == "no-match":
        ctx["repo"].upsert_tmdb(fid, found=False, looked_up=TODAY)
    ctx["repo"].append_reviews(authority, [ReviewEntry(reason, film_id=fid, detail=spec)], TODAY)
    ctx["review_id"] = ctx["repo"].open_reviews(authority)[-1]["id"]


@given(parsers.parse('an open {authority} "{reason}" review for slug "{slug}"'))
def open_for_slug(ctx, authority, reason, slug):
    ctx["repo"].append_reviews(authority, [ReviewEntry(reason, value=slug, detail=slug)], TODAY)
    ctx["review_id"] = ctx["repo"].open_reviews(authority)[-1]["id"]


@given(parsers.parse('an open {authority} "{reason}" review for title "{title}"'))
def open_for_title(ctx, authority, reason, title):
    ctx["repo"].append_reviews(authority, [ReviewEntry(reason, value=title, detail=title)], TODAY)
    ctx["review_id"] = ctx["repo"].open_reviews(authority)[-1]["id"]


@given(parsers.parse('an open tmdb "id-conflict" review for "{spec}" claiming id "{tid}"'))
def open_conflict(ctx, spec, tid):
    fid = _id(ctx["repo"], spec)
    ctx["repo"].upsert_tmdb(fid, found=False, looked_up=TODAY)
    ctx["repo"].append_reviews("tmdb", [ReviewEntry("id-conflict", film_id=fid, value=tid, detail=spec)], TODAY)
    ctx["review_id"] = ctx["repo"].open_reviews("tmdb")[-1]["id"]


@given(parsers.parse('"{spec}" holds tmdb id "{tid}"'))
def holds_tmdb(ctx, spec, tid):
    fid = _id(ctx["repo"], spec)
    ctx["repo"].set_external_id(fid, "tmdb", tid, TODAY)
    ctx["repo"].upsert_tmdb(fid, found=True, looked_up=TODAY)


@given(parsers.parse('the archive staged "{title}" ({year:d}) as slug "{slug}"'))
def staged(ctx, title, year, slug):
    ctx["repo"].upsert_mc_titles([McTitle(slug, title, year, 85, 1, 1)], TODAY)


@given(parsers.parse("TMDB says id {tid:d} was released in {year:d}"))
def tmdb_year(ctx, tid, year):
    ctx["rs"].get(f"{TMDB_API}/movie/{tid}", json={"id": tid, "release_date": f"{year}-03-02"})
    ctx["client"] = TmdbClient("tok")


@when("I resolve it with dismiss")
def dismiss(ctx):
    rv.resolve_review(ctx["repo"], ctx["review_id"], dismiss=True, today=TODAY)


@when(parsers.parse("I resolve it with tmdb id {tid:d}"))
def with_tmdb(ctx, tid):
    rv.resolve_review(ctx["repo"], ctx["review_id"], tmdb_id=tid, today=TODAY, client=ctx["client"])


@when("I resolve it with create")
def with_create(ctx):
    rv.resolve_review(ctx["repo"], ctx["review_id"], create=True, today=TODAY)


@when(parsers.parse('I resolve it with film "{spec}"'))
def with_film(ctx, spec):
    rv.resolve_review(ctx["repo"], ctx["review_id"], film_id=_id(ctx["repo"], spec), today=TODAY)


@then("the review is resolved")
def resolved(ctx):
    assert ctx["repo"].review(ctx["review_id"])["resolved"] == 1


@then(parsers.parse('rebuilding the tmdb no-match queue queues nothing for "{spec}"'))
def rebuild(ctx):
    from movie_brain.application.availability import rebuild_no_match_queue

    rebuild_no_match_queue(ctx["repo"], TODAY)
    assert ctx["repo"].open_reviews(TMDB_AUTHORITY) == []


@then(parsers.parse('"{spec}" has tmdb id "{tid}" and is found'))
def has_tmdb(ctx, spec, tid):
    fid = _id(ctx["repo"], spec)
    assert ctx["repo"].external_ids_for(fid)["tmdb"] == tid
    assert fid not in {t.film_id for t in ctx["repo"].films_tmdb_missed_targets()}


@then(parsers.parse('a film "{spec}" exists holding metacritic slug "{slug}"'))
def created_with_slug(ctx, spec, slug):
    fid = _id(ctx["repo"], spec)
    assert fid is not None and ctx["repo"].external_ids_for(fid)["metacritic"] == slug


@then(parsers.parse('"{spec}" holds metacritic slug "{slug}"'))
def holds_slug(ctx, spec, slug):
    assert ctx["repo"].external_ids_for(_id(ctx["repo"], spec))["metacritic"] == slug


@then(parsers.parse('re-running the archive match queues nothing for slug "{slug}"'))
def rerun_match(ctx, slug, monkeypatch):
    from movie_brain.infrastructure import metacritic as mc

    staged = ctx["repo"].top_staged_titles(100)
    monkeypatch.setattr(mc, "archived_pages", lambda _a: ["p1"])
    monkeypatch.setattr(mc, "parse_archive", lambda _a: staged)
    match_archive(ctx["repo"], ctx["config_dir"], TODAY)
    assert all(r["value"] != slug for r in ctx["repo"].open_reviews("metacritic"))


@then(parsers.parse('"{spec}" is owned'))
def is_owned(ctx, spec):
    assert _id(ctx["repo"], spec) in ctx["repo"].owned_film_ids()


@then(parsers.parse('a later owned import of "{title}" year {year:d} queues nothing'))
def later_import(ctx, title, year):
    import_owned(ctx["repo"], ctx["config_dir"], TODAY, fetch=lambda: [OwnedTitle(title, year)])
    assert ctx["repo"].open_reviews("apple-tv") == []


@then(parsers.parse('a film "{spec}" exists and is owned'))
def exists_owned(ctx, spec):
    fid = _id(ctx["repo"], spec)
    assert fid is not None and fid in ctx["repo"].owned_film_ids()


@then(parsers.parse('"{loser}" is merged into "{survivor}"'))
def merged(ctx, loser, survivor):
    assert ctx["repo"].disposition_of(_id(ctx["repo"], loser)) == ("merged", _id(ctx["repo"], survivor))


@then("resolving it with create fails")
def create_fails(ctx):
    with pytest.raises(ValueError):
        rv.resolve_review(ctx["repo"], ctx["review_id"], create=True, today=TODAY)


@then(parsers.parse('resolving it with both dismiss and film "{spec}" fails'))
def both_fail(ctx, spec):
    with pytest.raises(ValueError):
        rv.resolve_review(ctx["repo"], ctx["review_id"], dismiss=True, film_id=_id(ctx["repo"], spec), today=TODAY)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/step_defs/test_review.py -v`
Expected: ImportError on `movie_brain.application.review`.

- [ ] **Step 3: Repository helpers** (append to the `match_review`-related section of `database.py`)

```python
    def review(self, review_id: int) -> dict[str, object] | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM match_review WHERE id = ?", (review_id,)).fetchone()
            return None if row is None else dict(row)

    def list_reviews(self, authority: str | None = None, reason: str | None = None) -> list[dict[str, object]]:
        where = ["m.resolved = 0"]
        params: list[object] = []
        if authority:
            where.append("m.authority = ?")
            params.append(authority)
        if reason:
            where.append("m.reason = ?")
            params.append(reason)
        with self._conn() as c:
            rows = c.execute(
                "SELECT m.id, m.authority, m.film_id, m.value, m.reason, m.detail, m.created_at, "
                "f.title, f.year FROM match_review m LEFT JOIN films f ON f.id = m.film_id "
                "WHERE " + " AND ".join(where) + " ORDER BY m.authority, m.reason, m.id",
                params,
            ).fetchall()
            return [dict(r) for r in rows]

    def resolve_review(self, review_id: int, note: str) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE match_review SET resolved = 1, detail = COALESCE(detail, '') || ? WHERE id = ?",
                (f" [{note}]", review_id),
            )

    def resolved_review_keys(self, authority: str) -> set[tuple[str, int | None, str | None]]:
        """(reason, film_id, value) of every resolved row — a resolution is a standing decision."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT reason, film_id, value FROM match_review WHERE authority = ? AND resolved = 1", (authority,)
            ).fetchall()
            return {(str(r["reason"]), r["film_id"], r["value"]) for r in rows}

    def staged_title(self, slug: str) -> McTitle | None:
        with self._conn() as c:
            r = c.execute("SELECT slug, title, year, score, rank, page FROM metacritic WHERE slug = ?", (slug,)).fetchone()
            return None if r is None else McTitle(str(r["slug"]), str(r["title"]), r["year"], r["score"], int(r["rank"]), int(r["page"]))

    def tmdb_target(self, film_id: int) -> TmdbMatchTarget | None:
        with self._conn() as c:
            r = c.execute(_TMDB_TARGET_SELECT + "WHERE f.id = ?", (film_id,)).fetchone()
            return None if r is None else TmdbMatchTarget(int(r["id"]), str(r["title"]), r["year"], bool(r["commerce"]))
```

- [ ] **Step 4: Suppression in the four queue writers**

`application/review.py` (new; the resolver comes in Step 5):
```python
from __future__ import annotations

from movie_brain.domain.models import ReviewEntry
from movie_brain.infrastructure.database import Repository


def suppress_resolved(repo: Repository, authority: str, entries: list[ReviewEntry]) -> list[ReviewEntry]:
    """Drop entries a human already resolved (same reason+film+value) — dismiss means dismissed."""
    done = repo.resolved_review_keys(authority)
    return [e for e in entries if (e.reason, e.film_id, e.value) not in done]
```

`application/availability.py`: extract the rebuild (used by tmdb_step AND rematch AND the review test) and make `queue_review_once` respect resolved rows:
```python
def queue_review_once(repo: Repository, authority: str, entry: ReviewEntry, today: date) -> bool:
    for r in repo.open_reviews(authority):
        if r["reason"] == entry.reason and r["film_id"] == entry.film_id:
            return False
    if any(k[0] == entry.reason and k[1] == entry.film_id for k in repo.resolved_review_keys(authority)):
        return False  # a human already decided this one
    repo.append_reviews(authority, [entry], today)
    return True


def rebuild_no_match_queue(repo: Repository, today: date) -> None:
    """Recompute tmdb no-match rows from found=0 films; durable and resolved rows are untouched."""
    durably_flagged = {r["film_id"] for r in repo.open_reviews(TMDB_AUTHORITY) if r["reason"] != "no-match"}
    dismissed = {k[1] for k in repo.resolved_review_keys(TMDB_AUTHORITY) if k[0] == "no-match"}
    repo.replace_unresolved_reviews(
        TMDB_AUTHORITY,
        [
            ReviewEntry("no-match", film_id=fid, detail=f"{t} ({y})")
            for fid, t, y in repo.films_tmdb_missed()
            if fid not in durably_flagged and fid not in dismissed
        ],
        today,
        reason="no-match",
    )
```
Replace the inline rebuild blocks in `tmdb_step` (availability.py:155-165) and `rematch` (rematch.py:150-160) with `rebuild_no_match_queue(repo, today)`; drop the now-unused `ReviewEntry` import from rematch.py only if nothing else uses it (year-collision still does — keep it).

`application/metacritic.py` `match_archive`: change `repo.replace_unresolved_reviews(AUTHORITY, reviews, today)` → `repo.replace_unresolved_reviews(AUTHORITY, suppress_resolved(repo, AUTHORITY, reviews), today)` (import from `movie_brain.application.review`). Also extract creation so the resolver reuses it — add above `promote_top_n`:
```python
def create_from_staged(repo: Repository, t: McTitle, today: date) -> int | None:
    """Turn one staged Metacritic title into a real film and claim its slug; None on key/slug conflict."""
    film = Film(clean_title(t.title), t.year, None, MC_MOVIE_URL.format(slug=t.slug))
    film_id = repo.create_film(film)
    if film_id is None:
        return None
    try:
        repo.set_external_id(film_id, AUTHORITY, t.slug, today)
    except sqlite3.IntegrityError:
        return None
    return film_id
```
(Keep `promote_top_n`'s loop as-is — it needs the distinct key-conflict vs slug-conflict reviews; the helper is for the resolver.)

`application/owned.py`: `repo.replace_unresolved_reviews(AUTHORITY, suppress_resolved(repo, AUTHORITY, reviews), today)`.

- [ ] **Step 5: The resolver** (append to `application/review.py`)

```python
import sqlite3
from datetime import date

from movie_brain.application.availability import TMDB_AUTHORITY, record_tmdb_match
from movie_brain.application.metacritic import AUTHORITY as MC_AUTHORITY
from movie_brain.application.metacritic import create_from_staged
from movie_brain.application.owned import AUTHORITY as APPLE_AUTHORITY
from movie_brain.domain.matching import parse_apple_title
from movie_brain.domain.models import Film
from movie_brain.infrastructure.tmdb import TmdbClient

SLUG_REASONS = {"year-gap", "ambiguous-title"}  # metacritic rows keyed by slug, no film_id
MERGE_REASONS = {"id-conflict", "year-collision"}  # tmdb rows whose "match to X" means "X is my twin"


def resolve_review(
    repo: Repository,
    review_id: int,
    *,
    today: date,
    film_id: int | None = None,
    tmdb_id: int | None = None,
    create: bool = False,
    dismiss: bool = False,
    client: TmdbClient | None = None,
    note: str | None = None,
) -> str:
    """Apply exactly one resolution to one open match_review row; returns a one-line outcome.

    Per authority: tmdb no-match → --tmdb-id claims the id through the sync's own write path
    (year adoption included when a client is given) · tmdb id-conflict/year-collision →
    --film merges this film INTO the named twin · metacritic slug rows → --film links the
    slug, --create promotes the staged title · apple-tv rows → --film marks owned, --create
    creates + marks owned · every row accepts --dismiss. The row is marked resolved, which
    also suppresses the same anomaly from being re-queued by later runs.
    """
    chosen = [x for x in (film_id is not None, tmdb_id is not None, create, dismiss) if x]
    if len(chosen) != 1:
        raise ValueError("choose exactly one of --film, --tmdb-id, --create, --dismiss")
    row = repo.review(review_id)
    if row is None or row["resolved"]:
        raise ValueError(f"review {review_id} is not open")
    authority, reason = str(row["authority"]), str(row["reason"])
    rid = int(row["film_id"]) if row["film_id"] is not None else None
    value = None if row["value"] is None else str(row["value"])

    if dismiss:
        outcome = "dismissed"
    elif authority == TMDB_AUTHORITY:
        if tmdb_id is not None and rid is not None:
            target = repo.tmdb_target(rid)
            if target is None:
                raise ValueError(f"film {rid} not found")
            year = client.movie_year(tmdb_id) if client is not None else None
            result = record_tmdb_match(repo, target, tmdb_id, year, today, lambda _m: None)
            if result == "id-conflict":
                raise ValueError(f"tmdb id {tmdb_id} is already held by another film — merge instead")
            outcome = f"matched to tmdb {tmdb_id} ({result})"
        elif film_id is not None and reason in MERGE_REASONS and rid is not None:
            holder = repo.film_id_for_external(TMDB_AUTHORITY, value) if reason == "id-conflict" else (
                int(value) if value else None
            )
            if holder != film_id:
                raise ValueError(f"the twin for this row is film {holder}, not {film_id} (re-derived)")
            repo.merge_film(rid, film_id, today, note=note or f"review {review_id} {reason}")
            outcome = f"merged film {rid} into {film_id}"
        else:
            raise ValueError(f"tmdb/{reason} accepts --tmdb-id (no-match) or --film (twin) or --dismiss")
    elif authority == MC_AUTHORITY and reason in SLUG_REASONS and value is not None:
        if film_id is not None:
            try:
                repo.set_external_id(film_id, MC_AUTHORITY, value, today)
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"slug {value!r} is already claimed") from exc
            outcome = f"slug {value} → film {film_id}"
        elif create:
            staged = repo.staged_title(value)
            if staged is None:
                raise ValueError(f"slug {value!r} is not in the staged archive")
            new_id = create_from_staged(repo, staged, today)
            if new_id is None:
                raise ValueError(f"creating {staged.title!r} ({staged.year}) collides with an existing film")
            outcome = f"created film {new_id} from slug {value}"
        else:
            raise ValueError("metacritic slug rows accept --film, --create or --dismiss")
    elif authority == APPLE_AUTHORITY and value is not None:
        if film_id is not None:
            repo.mark_owned(film_id, today)
            outcome = f"{value!r} → owned film {film_id}"
        elif create:
            cleaned, embedded = parse_apple_title(value)
            film = Film(cleaned, embedded, None, "")
            new_id = repo.create_film(film)
            if new_id is None:
                new_id = repo.canonical_film_id(repo.film_id_by_key(film.key) or 0)
            repo.mark_owned(new_id, today)
            outcome = f"created owned film {new_id} from {value!r}"
        else:
            raise ValueError("apple-tv rows accept --film, --create or --dismiss")
    else:
        raise ValueError(f"{authority}/{reason} rows accept only --dismiss")

    repo.resolve_review(review_id, f"{outcome} {today.isoformat()}")
    for fid in (rid, film_id):
        if fid is not None:
            repo.clear_revisit(fid)  # Task 9 adds this; until then define it as a no-op stub in Repository
    return outcome
```
Add to `Repository` (Task 9 replaces the body): `def clear_revisit(self, film_id: int) -> None: return None`.

Note on the apple `--create` year: `parse_apple_title("Alpha (2020)")` → `("Alpha", 2020)`; for a title without an embedded year the film is created year-less (`None`) — the detail text carries the field year but it is a commerce year we refuse to harden (truth-holder rule); TMDB matching then canonicalizes it.

- [ ] **Step 6: Run everything**

Run: `uv run pytest && uv run ruff check . && uv run mypy`
Expected: green. Existing `tests/step_defs/test_tmdb.py`/`test_rematch.py` rebuild scenarios still pass through `rebuild_no_match_queue`.

- [ ] **Step 7: Commit**

```bash
git add -A src tests
git commit -m "M3: review resolution use case; a resolved anomaly is never re-queued"
```

---

### Task 5: `repair dupes` — audit, classify, merge

**Files:**
- Create: `src/movie_brain/application/repair.py`
- Modify: `database.py` (`films_for_repair`), `tests/features/repair.feature`, `tests/step_defs/test_repair.py`

**Interfaces:**
- Produces (Repository): `films_for_repair() -> list[RepairFilm]` where
  `RepairFilm(NamedTuple)`: `id: int, title: str, year: int | None, tmdb: str | None, criterion: bool, rated: bool, owned: bool, watchlisted: bool, omdb_found: bool`
- Produces (repair.py):
  - `DupGroup(frozen dataclass)`: `key: str, films: tuple[RepairFilm, ...], verdict: str` (`"twin" | "distinct" | "undecided"`), `survivor: int | None`, `losers: tuple[int, ...]`, `source: str` (`"norm-title" | "id-conflict"`)
  - `audit_dupes(repo) -> list[DupGroup]`
  - `DupesReport(frozen dataclass)`: `groups: int, twins: int, distinct: int, undecided: int, merged: int, declined: int`
  - `repair_dupes(repo, today, *, apply: bool, confirm: Callable[[DupGroup], bool], log) -> DupesReport`

- [ ] **Step 1: Scenarios** (append to `repair.feature`)

```gherkin
  Scenario: Same-TMDB-id norm-title twins merge into the Criterion survivor
    Given "Alpha (1950)" holds tmdb id "5"
    And "Alpha (1951)" has an open id-conflict review claiming tmdb id "5"
    When I audit dupes
    Then the group "alpha" is a twin with survivor "Alpha (1950)" from source "id-conflict"
    When I apply dupes confirming every group
    Then "Alpha (1951)" is merged into "Alpha (1950)"
    And the id-conflict review is resolved

  Scenario: Distinct TMDB ids are kept both
    Given "Alpha (1950)" holds tmdb id "5"
    And "Alpha (1951)" holds tmdb id "6"
    When I audit dupes
    Then the group "alpha" is distinct

  Scenario: A group missing TMDB evidence is undecided and never merged in batch
    When I audit dupes
    Then the group "alpha" is undecided
    When I apply dupes confirming every group
    Then nothing was merged

  Scenario: Declining the confirmation merges nothing
    Given "Alpha (1950)" holds tmdb id "5"
    And "Alpha (1951)" has an open id-conflict review claiming tmdb id "5"
    When I apply dupes declining every group
    Then nothing was merged
```

Steps (append to `test_repair.py`):
```python
from movie_brain.application import repair
from movie_brain.domain.models import ReviewEntry


@given(parsers.parse('"{spec}" holds tmdb id "{tid}"'))
def holds(ctx, spec, tid):
    fid = ctx["repo"].film_id_by_key(_key(spec))
    ctx["repo"].set_external_id(fid, "tmdb", tid, TODAY)
    ctx["repo"].upsert_tmdb(fid, found=True, looked_up=TODAY)


@given(parsers.parse('"{spec}" has an open id-conflict review claiming tmdb id "{tid}"'))
def conflict(ctx, spec, tid):
    fid = ctx["repo"].film_id_by_key(_key(spec))
    ctx["repo"].upsert_tmdb(fid, found=False, looked_up=TODAY)
    ctx["repo"].append_reviews("tmdb", [ReviewEntry("id-conflict", film_id=fid, value=tid, detail=spec)], TODAY)


@when("I audit dupes")
def audit(ctx):
    ctx["groups"] = repair.audit_dupes(ctx["repo"])


@when(parsers.parse("I apply dupes {mode} every group"))
def apply(ctx, mode):
    ctx["dupes"] = repair.repair_dupes(
        ctx["repo"], TODAY, apply=True, confirm=lambda _g: mode == "confirming", log=lambda _m: None
    )


@then(parsers.parse('the group "{key}" is a twin with survivor "{spec}" from source "{source}"'))
def is_twin(ctx, key, spec, source):
    g = next(g for g in ctx["groups"] if g.key == key)
    assert g.verdict == "twin" and g.survivor == ctx["repo"].film_id_by_key(_key(spec)) and g.source == source


@then(parsers.parse('the group "{key}" is {verdict}'))
def has_verdict(ctx, key, verdict):
    assert next(g for g in ctx["groups"] if g.key == key).verdict == verdict


@then("the id-conflict review is resolved")
def conflict_resolved(ctx):
    assert ctx["repo"].open_reviews("tmdb") == []


@then("nothing was merged")
def nothing_merged(ctx):
    assert ctx["dupes"].merged == 0 and ctx["repo"].disposed_film_ids() == set()
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/step_defs/test_repair.py -v` → ImportError on `movie_brain.application.repair`.

- [ ] **Step 3: Repository query**

```python
class RepairFilm(NamedTuple):
    id: int
    title: str
    year: int | None
    tmdb: str | None
    criterion: bool
    rated: bool
    owned: bool
    watchlisted: bool
    omdb_found: bool
```
```python
    def films_for_repair(self) -> list[RepairFilm]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT f.id, f.title, f.year, x.value AS tmdb, "
                "EXISTS (SELECT 1 FROM listings l WHERE l.film_id = f.id AND l.source = 'criterion') AS criterion, "
                "EXISTS (SELECT 1 FROM my_ratings r WHERE r.film_id = f.id) AS rated, "
                "EXISTS (SELECT 1 FROM owned w WHERE w.film_id = f.id) AS owned, "
                "EXISTS (SELECT 1 FROM watchlist w WHERE w.film_id = f.id) AS watchlisted, "
                "COALESCE((SELECT o.found FROM omdb o WHERE o.film_id = f.id), 0) AS omdb_found "
                "FROM films f LEFT JOIN external_ids x ON x.film_id = f.id AND x.authority = 'tmdb' "
                "WHERE " + _NOT_DISPOSED + " ORDER BY f.id"
            ).fetchall()
            return [
                RepairFilm(int(r["id"]), str(r["title"]), r["year"], r["tmdb"], bool(r["criterion"]), bool(r["rated"]),
                           bool(r["owned"]), bool(r["watchlisted"]), bool(r["omdb_found"]))
                for r in rows
            ]
```

- [ ] **Step 4: `application/repair.py`** (dupes half; links/years are added in Tasks 6–7)

```python
from __future__ import annotations

import sys
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date

from movie_brain.application.availability import TMDB_AUTHORITY
from movie_brain.domain.matching import norm_title, split_annotations
from movie_brain.infrastructure.database import RepairFilm, Repository


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


@dataclass(frozen=True)
class DupGroup:
    key: str
    films: tuple[RepairFilm, ...]
    verdict: str  # "twin" | "distinct" | "undecided"
    survivor: int | None
    losers: tuple[int, ...]
    source: str  # "norm-title" | "id-conflict"


@dataclass(frozen=True)
class DupesReport:
    groups: int
    twins: int
    distinct: int
    undecided: int
    merged: int
    declined: int


def _rank(f: RepairFilm) -> tuple[int, ...]:
    """Survivor policy: Criterion-listed > rated > owned > watchlisted > OMDb-found > oldest id."""
    return (f.criterion, f.rated, f.owned, f.watchlisted, f.omdb_found, -f.id)


def _classify(key: str, films: tuple[RepairFilm, ...], source: str) -> DupGroup:
    ids = {f.tmdb for f in films}
    if len(films) >= 2 and len(ids) == 1 and None not in ids:
        survivor = max(films, key=_rank)
        return DupGroup(key, films, "twin", survivor.id, tuple(f.id for f in films if f.id != survivor.id), source)
    if None not in ids and len(ids) == len(films):
        return DupGroup(key, films, "distinct", None, (), source)
    return DupGroup(key, films, "undecided", None, (), source)


def audit_dupes(repo: Repository) -> list[DupGroup]:
    """Norm-title groups plus id-conflict pairs, classified by TMDB id equality (re-derived now)."""
    films = {f.id: f for f in repo.films_for_repair()}
    # id-conflict rows: the flagged film could not claim the id its twin holds — lend it the
    # claimed id for classification (value re-derived against the current holder).
    claimed: dict[int, str] = {}
    pairs: list[tuple[int, int]] = []
    for r in repo.open_reviews(TMDB_AUTHORITY):
        if r["reason"] != "id-conflict" or r["film_id"] not in films or not r["value"]:
            continue
        holder = repo.film_id_for_external(TMDB_AUTHORITY, str(r["value"]))
        if holder is None or holder not in films or holder == r["film_id"]:
            continue
        claimed[int(r["film_id"])] = str(r["value"])
        pairs.append((int(r["film_id"]), holder))
    by_key: dict[str, list[RepairFilm]] = defaultdict(list)
    for f in films.values():
        by_key[norm_title(split_annotations(f.title)[0])].append(f)
    groups: list[DupGroup] = []
    paired: set[int] = set()
    for loser, holder in pairs:
        lent = replace(films[loser], tmdb=claimed[loser])
        groups.append(_classify(norm_title(films[holder].title), (films[holder], lent), "id-conflict"))
        paired.update((loser, holder))
    for key, members in sorted(by_key.items()):
        if len(members) < 2 or all(m.id in paired for m in members):
            continue
        groups.append(_classify(key, tuple(replace(m, tmdb=claimed.get(m.id, m.tmdb)) for m in members), "norm-title"))
    return groups


def format_group(g: DupGroup) -> str:
    lines = [f"[{g.verdict}] {g.key!r} ({g.source})"]
    for f in g.films:
        role = "survivor" if f.id == g.survivor else ("loser" if f.id in g.losers else "")
        flags = " ".join(n for n, on in (("criterion", f.criterion), ("rated", f.rated), ("owned", f.owned), ("watchlist", f.watchlisted)) if on)
        lines.append(f"  #{f.id:<5} {f.title!r} ({f.year}) tmdb={f.tmdb or '-'} {flags} {role}")
    return "\n".join(lines)


def repair_dupes(
    repo: Repository,
    today: date,
    *,
    apply: bool,
    confirm: Callable[[DupGroup], bool],
    log: Callable[[str], None] = _stderr,
) -> DupesReport:
    """Dry-run lists every group; --apply merges each TWIN group the confirm callback approves.

    Only twins (same TMDB id) are ever merged here; distinct groups are reported and kept,
    undecided groups need `review resolve` / a manual merge after a human look.
    """
    groups = audit_dupes(repo)
    merged = declined = 0
    for g in groups:
        log(format_group(g))
        if not apply or g.verdict != "twin" or g.survivor is None:
            continue
        if not confirm(g):
            declined += 1
            continue
        for loser in g.losers:
            report = repo.merge_film(loser, g.survivor, today, note=f"repair dupes {g.source} {g.key!r}")
            log(f"  merged #{loser} → #{g.survivor}: moved {report.moved} dropped {report.dropped}")
            merged += 1
    counts = {v: sum(1 for g in groups if g.verdict == v) for v in ("twin", "distinct", "undecided")}
    return DupesReport(len(groups), counts["twin"], counts["distinct"], counts["undecided"], merged, declined)
```

- [ ] **Step 5: Verify** — `uv run pytest && uv run ruff check . && uv run mypy` → green.

- [ ] **Step 6: Commit** — `git add -A src tests && git commit -m "M3: repair dupes — norm-title + id-conflict audit, TMDB-id twin classification, confirmed merges"`

---

### Task 6: `repair links` — re-validate every TMDB link

**Files:**
- Modify: `src/movie_brain/infrastructure/tmdb.py` (`movie_titles`), `database.py` (`films_with_tmdb`, `clear_tmdb_link`), `application/repair.py`, `tests/unit/test_tmdb.py`, `repair.feature`, `test_repair.py`

**Interfaces:**
- `TmdbClient.movie_titles(tmdb_id) -> tuple[str, str, int | None]` — `(title, original_title, year)`
- `Repository.films_with_tmdb() -> list[tuple[int, str, int | None, str]]` — `(film_id, title, year, tmdb_value)`, non-disposed, every film (not only commerce)
- `Repository.clear_tmdb_link(film_id, today) -> None` — deletes the `tmdb` external id row, sets `tmdb.found = 0`
- `LinkSuspect(frozen)`: `film_id, title, year, tmdb_id, tmdb_title, tmdb_original, tmdb_year`
- `audit_links(repo, client, *, log) -> tuple[list[LinkSuspect], int, bool]` — `(suspects, checked, tripwired)`
- `LinksReport(frozen)`: `exit_code, checked, suspects, cleared`
- `repair_links(repo, client, today, *, apply, log) -> LinksReport`

- [ ] **Step 1: Tests**

`tests/unit/test_tmdb.py` (append):
```python
@responses.activate
def test_movie_titles():
    responses.get(f"{TMDB_API}/movie/62518", json={"title": "Wild Blood", "original_title": "Vahşi Kan", "release_date": "1983-01-01"})
    assert TmdbClient("t").movie_titles(62518) == ("Wild Blood", "Vahşi Kan", 1983)
```
`repair.feature` (append):
```gherkin
  Scenario: A TMDB link whose titles disagree with the film is a suspect and can be cleared
    Given "Alpha (1950)" holds tmdb id "5"
    And "Alpha (1951)" holds tmdb id "62518"
    And TMDB describes id 5 as "Alpha" / "Alpha" from 1950
    And TMDB describes id 62518 as "Wild Blood" / "Vahşi Kan" from 1983
    When I audit links
    Then the only link suspect is "Alpha (1951)"
    When I apply links
    Then "Alpha (1951)" has no tmdb id and is a TMDB miss
    And "Alpha (1950)" still holds tmdb id "5"

  Scenario: A film matching TMDB's original title is not a suspect
    Given "Alpha (1950)" holds tmdb id "5"
    And TMDB describes id 5 as "The Alpha Movie" / "Alpha" from 1950
    When I audit links
    Then there are no link suspects
```
Steps (append to `test_repair.py`; add `import json, responses` and `from movie_brain.infrastructure.tmdb import TMDB_API, TmdbClient`; extend the `ctx` fixture to start a `responses.RequestsMock(assert_all_requests_are_fired=False)` exactly as `test_review.py` does and store `ctx["rs"]`):
```python
@given(parsers.parse('TMDB describes id {tid:d} as "{title}" / "{orig}" from {year:d}'))
def describe(ctx, tid, title, orig, year):
    ctx["rs"].get(f"{TMDB_API}/movie/{tid}", json={"title": title, "original_title": orig, "release_date": f"{year}-01-01"})


@when("I audit links")
def audit_links(ctx):
    ctx["suspects"], _, _ = repair.audit_links(ctx["repo"], TmdbClient("tok"), log=lambda _m: None)


@when("I apply links")
def apply_links(ctx):
    ctx["links"] = repair.repair_links(ctx["repo"], TmdbClient("tok"), TODAY, apply=True, log=lambda _m: None)


@then(parsers.parse('the only link suspect is "{spec}"'))
def only_suspect(ctx, spec):
    assert [s.film_id for s in ctx["suspects"]] == [ctx["repo"].film_id_by_key(_key(spec))]


@then("there are no link suspects")
def no_suspects(ctx):
    assert ctx["suspects"] == []


@then(parsers.parse('"{spec}" has no tmdb id and is a TMDB miss'))
def cleared(ctx, spec):
    fid = ctx["repo"].film_id_by_key(_key(spec))
    assert "tmdb" not in ctx["repo"].external_ids_for(fid)
    assert fid in {t.film_id for t in ctx["repo"].films_tmdb_missed_targets()}


@then(parsers.parse('"{spec}" still holds tmdb id "{tid}"'))
def still_holds(ctx, spec, tid):
    assert ctx["repo"].external_ids_for(ctx["repo"].film_id_by_key(_key(spec)))["tmdb"] == tid
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/unit/test_tmdb.py tests/step_defs/test_repair.py -v` → `movie_titles` missing / step errors.

- [ ] **Step 3: Implement**

`tmdb.py`:
```python
    def movie_titles(self, tmdb_id: int) -> tuple[str, str, int | None]:
        d = self._get(f"/movie/{tmdb_id}").json()
        rd = d.get("release_date") or ""
        year = int(rd[:4]) if len(rd) >= 4 and rd[:4].isdigit() else None
        return d.get("title") or "", d.get("original_title") or "", year
```
`database.py`:
```python
    def films_with_tmdb(self) -> list[tuple[int, str, int | None, str]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT f.id, f.title, f.year, x.value FROM films f "
                "JOIN external_ids x ON x.film_id = f.id AND x.authority = 'tmdb' "
                "WHERE " + _NOT_DISPOSED + " ORDER BY f.id"
            ).fetchall()
            return [(int(r["id"]), str(r["title"]), r["year"], str(r["value"])) for r in rows]

    def clear_tmdb_link(self, film_id: int, today: date) -> None:
        """Human-confirmed repair only: drop a wrong TMDB link so the matcher can retry it."""
        with self._conn() as c:
            c.execute("DELETE FROM external_ids WHERE film_id = ? AND authority = 'tmdb'", (film_id,))
            c.execute(
                "INSERT INTO tmdb (film_id, found, looked_up) VALUES (?, 0, ?) "
                "ON CONFLICT(film_id) DO UPDATE SET found = 0, looked_up = excluded.looked_up",
                (film_id, today.isoformat()),
            )
```
`repair.py` (append; add `import requests`, `from movie_brain.application.availability import MAX_CONSECUTIVE_FAILURES`, `from movie_brain.infrastructure.tmdb import AuthError, TmdbClient`):
```python
@dataclass(frozen=True)
class LinkSuspect:
    film_id: int
    title: str
    year: int | None
    tmdb_id: str
    tmdb_title: str
    tmdb_original: str
    tmdb_year: int | None


@dataclass(frozen=True)
class LinksReport:
    exit_code: int
    checked: int
    suspects: int
    cleared: int


def _same_title(ours: str, theirs: str) -> bool:
    return norm_title(split_annotations(ours)[0]) == norm_title(split_annotations(theirs)[0])


def audit_links(
    repo: Repository, client: TmdbClient, *, log: Callable[[str], None] = _stderr
) -> tuple[list[LinkSuspect], int, bool]:
    """Every TMDB link whose title AND original_title both disagree with ours (Rambo/Vahşi Kan class)."""
    suspects: list[LinkSuspect] = []
    checked = consecutive = 0
    for film_id, title, year, value in repo.films_with_tmdb():
        if consecutive >= MAX_CONSECUTIVE_FAILURES:
            log("TMDB failing repeatedly — stopping; repair links is safe to re-run.")
            return suspects, checked, True
        try:
            t_title, t_orig, t_year = client.movie_titles(int(value))
        except AuthError as exc:
            log(f"TMDB rejected the token: {exc}")
            return suspects, checked, True
        except (requests.RequestException, ValueError) as exc:
            log(f"TMDB details failed for film {film_id}: {exc}")
            consecutive += 1
            continue
        consecutive = 0
        checked += 1
        if not (_same_title(title, t_title) or _same_title(title, t_orig)):
            suspects.append(LinkSuspect(film_id, title, year, value, t_title, t_orig, t_year))
    return suspects, checked, False


def repair_links(
    repo: Repository, client: TmdbClient, today: date, *, apply: bool, log: Callable[[str], None] = _stderr
) -> LinksReport:
    suspects, checked, tripwired = audit_links(repo, client, log=log)
    for s in suspects:
        log(f"#{s.film_id:<5} {s.title!r} ({s.year}) → tmdb {s.tmdb_id} {s.tmdb_title!r} / {s.tmdb_original!r} ({s.tmdb_year})")
    cleared = 0
    if apply:
        for s in suspects:
            repo.clear_tmdb_link(s.film_id, today)
            cleared += 1
        if cleared:
            log(f"cleared {cleared} links — run `movie-brain rematch` to re-match them with the current matcher")
    return LinksReport(1 if tripwired else 0, checked, len(suspects), cleared)
```

- [ ] **Step 4: Verify** — `uv run pytest && uv run ruff check . && uv run mypy` → green.
- [ ] **Step 5: Commit** — `git add -A src tests && git commit -m "M3: repair links — re-validate every TMDB link by title, clear confirmed wrong links"`

---

### Task 7: `repair years` — worklist + manual correction + stale-OMDb refetch marks

**Files:**
- Modify: `database.py` (`stale_omdb_years`, `mark_omdb_refresh`, guard `update_film_year`), `application/repair.py`, `repair.feature`, `test_repair.py`, `tests/unit/test_database.py`

**Interfaces:**
- `Repository.stale_omdb_years() -> list[tuple[int, str, int | None, int]]` — `(film_id, title, films.year, omdb payload year)` for non-Criterion, non-disposed films whose OMDb payload `Year` disagrees with `films.year`
- `Repository.mark_omdb_refresh(film_id) -> None` — `UPDATE omdb SET needs_refresh = 1`
- `Repository.update_film_year` raises `LookupError` for an unknown id (riding minor)
- `YearsAudit(frozen)`: `collisions: tuple[dict[str, object], ...]` (open `year-collision` review rows), `stale: tuple[tuple[int, str, int | None, int], ...]`
- `audit_years(repo) -> YearsAudit`
- `YearsReport(frozen)`: `collisions: int, stale: int, refresh_marked: int, changed: bool, collided_with: int | None`
- `repair_years(repo, today, *, film_id=None, year=None, apply, log) -> YearsReport`

- [ ] **Step 1: Tests**

`repair.feature` (append):
```gherkin
  Scenario: The years worklist lists stale OMDb payloads and applying marks them for refetch
    Given "Alpha (1951)" has an OMDb payload fetched for year 1953
    When I audit years
    Then the stale OMDb list is exactly "Alpha (1951)"
    When I apply years
    Then "Alpha (1951)" needs an OMDb refresh

  Scenario: A manual year correction is dry-run first, then applied with a refetch mark
    When I dry-run setting "Alpha (1951)" to 1949
    Then "Alpha (1951)" still has year 1951
    When I apply setting "Alpha (1951)" to 1949
    Then a film "Alpha (1949)" exists and needs an OMDb refresh

  Scenario: A manual year correction that collides queues a merge candidate instead
    When I apply setting "Alpha (1951)" to 1950
    Then "Alpha (1951)" still has year 1951
    And an open tmdb year-collision review names "Alpha (1950)"
```
Steps:
```python
@given(parsers.parse('"{spec}" has an OMDb payload fetched for year {year:d}'))
def stale_payload(ctx, spec, year):
    from movie_brain.domain.models import OmdbRating

    fid = ctx["repo"].film_id_by_key(_key(spec))
    ctx["repo"].upsert_omdb(fid, OmdbRating(6.0, 50, True, "English", json.dumps({"Year": str(year)})), TODAY)


@when("I audit years")
def audit_years(ctx):
    ctx["years_audit"] = repair.audit_years(ctx["repo"])


@when("I apply years")
def apply_years(ctx):
    ctx["years"] = repair.repair_years(ctx["repo"], TODAY, apply=True, log=lambda _m: None)


@when(parsers.parse('I {mode} setting "{spec}" to {year:d}'))
def set_year(ctx, mode, spec, year):
    fid = ctx["repo"].film_id_by_key(_key(spec))
    ctx["years"] = repair.repair_years(ctx["repo"], TODAY, film_id=fid, year=year, apply=(mode == "apply"), log=lambda _m: None)


@then(parsers.parse('the stale OMDb list is exactly "{spec}"'))
def stale_is(ctx, spec):
    assert [s[0] for s in ctx["years_audit"].stale] == [ctx["repo"].film_id_by_key(_key(spec))]


@then(parsers.parse('"{spec}" needs an OMDb refresh'))
def needs_refresh(ctx, spec):
    fid = ctx["repo"].film_id_by_key(_key(spec))
    assert fid in {f for f, _ in ctx["repo"].films_needing_lookup_discovery("criterion", TODAY)}


@then(parsers.parse('"{spec}" still has year {year:d}'))
def still_year(ctx, spec, year):
    assert ctx["repo"].film_id_by_key(_key(spec)) is not None


@then(parsers.parse('a film "{spec}" exists and needs an OMDb refresh'))
def exists_refresh(ctx, spec):
    fid = ctx["repo"].film_id_by_key(_key(spec))
    assert fid is not None
    assert fid in {f for f, _ in ctx["repo"].films_needing_lookup_discovery("criterion", TODAY)}


@then(parsers.parse('an open tmdb year-collision review names "{spec}"'))
def collision_named(ctx, spec):
    rows = [r for r in ctx["repo"].open_reviews("tmdb") if r["reason"] == "year-collision"]
    assert rows and rows[0]["value"] == str(ctx["repo"].film_id_by_key(_key(spec)))
```
(For the "still has year" step the key lookup is the assertion: `alpha (1951)` still resolves.)

`tests/unit/test_database.py` (append):
```python
def test_update_film_year_unknown_id_raises(repo):
    import pytest

    with pytest.raises(LookupError):
        repo.update_film_year(999, 1950)
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/step_defs/test_repair.py tests/unit/test_database.py -v`.

- [ ] **Step 3: Implement**

`database.py`:
```python
    def stale_omdb_years(self) -> list[tuple[int, str, int | None, int]]:
        """Non-Criterion films whose OMDb payload was fetched under a different year than films.year."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT f.id, f.title, f.year, CAST(substr(json_extract(o.payload, '$.Year'), 1, 4) AS INTEGER) AS oy "
                "FROM films f JOIN omdb o ON o.film_id = f.id "
                "WHERE o.payload IS NOT NULL AND o.needs_refresh = 0 AND " + _NOT_DISPOSED + " "
                "AND NOT EXISTS (SELECT 1 FROM listings l WHERE l.film_id = f.id AND l.source = 'criterion') "
                "AND oy IS NOT NULL AND oy != COALESCE(f.year, -1) ORDER BY f.id"
            ).fetchall()
            return [(int(r["id"]), str(r["title"]), r["year"], int(r["oy"])) for r in rows]

    def mark_omdb_refresh(self, film_id: int) -> None:
        with self._conn() as c:
            c.execute("UPDATE omdb SET needs_refresh = 1 WHERE film_id = ?", (film_id,))
```
and in `update_film_year` after the `SELECT title` line: `if row is None: raise LookupError(f"unknown film {film_id}")`.

`repair.py` (append; import `queue_review_once` from availability and `ReviewEntry`):
```python
@dataclass(frozen=True)
class YearsAudit:
    collisions: tuple[dict[str, object], ...]
    stale: tuple[tuple[int, str, int | None, int], ...]


@dataclass(frozen=True)
class YearsReport:
    collisions: int
    stale: int
    refresh_marked: int
    changed: bool = False
    collided_with: int | None = None


def audit_years(repo: Repository) -> YearsAudit:
    collisions = tuple(r for r in repo.list_reviews(TMDB_AUTHORITY, "year-collision"))
    return YearsAudit(collisions, tuple(repo.stale_omdb_years()))


def repair_years(
    repo: Repository,
    today: date,
    *,
    film_id: int | None = None,
    year: int | None = None,
    apply: bool,
    log: Callable[[str], None] = _stderr,
) -> YearsReport:
    """No args: list the worklist (open year-collisions + stale OMDb payloads); --apply marks the
    stale payloads for refetch. With FILM_ID YEAR: dry-run the correction; --apply writes it
    through update_film_year (collision → year-collision review, never an overwrite) and marks
    the film's OMDb row for refetch so ratings/director/runtime are re-fetched under the new year."""
    if (film_id is None) != (year is None):
        raise ValueError("give both FILM_ID and YEAR, or neither")
    audit = audit_years(repo)
    if film_id is not None and year is not None:
        view = repo.get_view(film_id)
        if view is None:
            raise LookupError(f"unknown film {film_id}")
        log(f"#{film_id} {view.title!r}: {view.year} → {year}{'' if apply else ' (dry-run)'}")
        if not apply:
            return YearsReport(len(audit.collisions), len(audit.stale), 0)
        clash = repo.update_film_year(film_id, year)
        if clash is not None:
            queue_review_once(
                repo, TMDB_AUTHORITY,
                ReviewEntry("year-collision", film_id=film_id, value=str(clash),
                            detail=f"{view.title!r}: setting {year} over {view.year} collides with film {clash} — merge candidate"),
                today,
            )
            log(f"collides with film {clash} — queued year-collision, nothing written")
            return YearsReport(len(audit.collisions), len(audit.stale), 0, False, clash)
        repo.mark_omdb_refresh(film_id)
        repo.clear_revisit(film_id)
        return YearsReport(len(audit.collisions), len(audit.stale), 1, True)
    for r in audit.collisions:
        log(f"collision #{r['id']}: film {r['film_id']} {r['title']!r} ({r['year']}) vs film {r['value']} — {r['detail']}")
    for fid, title, fy, oy in audit.stale:
        log(f"stale omdb: #{fid} {title!r} year {fy}, payload fetched for {oy}")
    marked = 0
    if apply:
        for fid, _t, _fy, _oy in audit.stale:
            repo.mark_omdb_refresh(fid)
            marked += 1
    return YearsReport(len(audit.collisions), len(audit.stale), marked)
```

- [ ] **Step 4: Verify** — `uv run pytest && uv run ruff check . && uv run mypy`.
- [ ] **Step 5: Commit** — `git commit -am "M3: repair years — collision/stale-OMDb worklist, manual correction with refetch mark"` (use `git add -A src tests` first).

---

### Task 8: CLI — `repair` and `review` sub-apps

**Files:**
- Modify: `src/movie_brain/cli.py`, `tests/unit/test_cli.py`

**Interfaces:** commands
- `movie-brain repair dupes [--apply] [--yes]` — dry-run prints groups; `--apply` prompts per twin group (`typer.confirm`), `--yes` batch-confirms.
- `movie-brain repair links [--apply]` — needs TMDB token (exit 2 if missing).
- `movie-brain repair years [FILM_ID YEAR] [--apply]`
- `movie-brain review list [--authority A] [--reason R]`
- `movie-brain review resolve ID [--film X | --tmdb-id X | --create | --dismiss] [--note TEXT]` — `--tmdb-id` uses a TmdbClient when a token exists (year adoption), otherwise proceeds without one.

- [ ] **Step 1: CLI tests** (append to `tests/unit/test_cli.py`)

```python
from movie_brain.application.repair import DupesReport, LinksReport, YearsReport


def test_repair_dupes_dry_run_never_confirms(monkeypatch):
    seen = {}

    def fake(repo, today, *, apply, confirm, log):
        seen["apply"] = apply
        return DupesReport(3, 1, 1, 1, 0, 0)

    monkeypatch.setattr("movie_brain.cli.repair_dupes", fake)
    r = runner.invoke(app, ["repair", "dupes"])
    assert r.exit_code == 0 and seen["apply"] is False and "twins: 1" in r.output


def test_repair_links_requires_token(config_dir):
    r = runner.invoke(app, ["repair", "links"])
    assert r.exit_code == 2 and "TMDB" in r.output


def test_repair_years_args_pair(monkeypatch):
    calls = {}

    def fake(repo, today, *, film_id=None, year=None, apply, log):
        calls.update(film_id=film_id, year=year, apply=apply)
        return YearsReport(0, 0, 1, True)

    monkeypatch.setattr("movie_brain.cli.repair_years", fake)
    r = runner.invoke(app, ["repair", "years", "12", "1927", "--apply"])
    assert r.exit_code == 0 and calls == {"film_id": 12, "year": 1927, "apply": True}


def test_review_resolve_reports_value_errors(monkeypatch):
    def fake(repo, review_id, **kw):
        raise ValueError("choose exactly one")

    monkeypatch.setattr("movie_brain.cli.resolve_review", fake)
    r = runner.invoke(app, ["review", "resolve", "7", "--dismiss", "--create"])
    assert r.exit_code == 1 and "choose exactly one" in r.output
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/unit/test_cli.py -v` → ImportError / unknown command.

- [ ] **Step 3: Implement** (add to `cli.py`)

Imports: `from movie_brain.application.repair import DupGroup, format_group, repair_dupes, repair_links, repair_years` and `from movie_brain.application.review import resolve_review`.

```python
repair_app = typer.Typer(help="Human-confirmed repairs: merge dupes, clear wrong TMDB links, fix years.")
app.add_typer(repair_app, name="repair")
review_app = typer.Typer(help="Resolve match_review anomalies: match to a film, create, or dismiss.")
app.add_typer(review_app, name="review")


@repair_app.command("dupes")
def repair_dupes_cmd(
    apply: Annotated[bool, typer.Option("--apply", help="Merge confirmed twin groups (default: dry-run).")] = False,
    yes: Annotated[bool, typer.Option("--yes", help="With --apply: confirm every twin group without prompting.")] = False,
) -> None:
    """Audit duplicate films (norm-title groups + id-conflicts); merge twins after confirmation."""

    def confirm(g: DupGroup) -> bool:
        return yes or typer.confirm(f"merge {g.losers} into #{g.survivor}?", default=False)

    report = repair_dupes(_repo(), date.today(), apply=apply, confirm=confirm, log=err.print)
    console.print(
        f"groups: {report.groups} · twins: {report.twins} · distinct: {report.distinct} · "
        f"undecided: {report.undecided} · merged: {report.merged} · declined: {report.declined}"
    )


@repair_app.command("links")
def repair_links_cmd(
    apply: Annotated[bool, typer.Option("--apply", help="Clear every suspect link (default: dry-run).")] = False,
) -> None:
    """Re-validate every TMDB link by title; suspects are listed, --apply clears them for rematch."""
    cfg = load_config()
    token = load_tmdb_token(cfg)
    if not token:
        err.print(f"no TMDB token: set MOVIE_BRAIN_TMDB_TOKEN or write {cfg.tmdb_token_file}")
        raise typer.Exit(2)
    report = repair_links(_repo(), TmdbClient(token), date.today(), apply=apply, log=err.print)
    console.print(f"checked: {report.checked} · suspects: {report.suspects} · cleared: {report.cleared}")
    raise typer.Exit(report.exit_code)


@repair_app.command("years")
def repair_years_cmd(
    film_id: Annotated[int | None, typer.Argument(help="Film id to correct.")] = None,
    year: Annotated[int | None, typer.Argument(help="New original release year.")] = None,
    apply: Annotated[bool, typer.Option("--apply", help="Write the correction / mark stale OMDb rows.")] = False,
) -> None:
    """List the year worklist, or dry-run/apply one manual year correction."""
    try:
        report = repair_years(_repo(), date.today(), film_id=film_id, year=year, apply=apply, log=err.print)
    except (ValueError, LookupError) as exc:
        err.print(str(exc))
        raise typer.Exit(1) from exc
    console.print(
        f"open collisions: {report.collisions} · stale omdb: {report.stale} · refresh marked: {report.refresh_marked}"
        + (f" · changed: {report.changed}" if film_id is not None else "")
        + (f" · collided with film {report.collided_with}" if report.collided_with else "")
    )


@review_app.command("list")
def review_list(
    authority: Annotated[str | None, typer.Option("--authority", help="tmdb | metacritic | apple-tv")] = None,
    reason: Annotated[str | None, typer.Option("--reason", help="e.g. no-match, id-conflict, year-gap")] = None,
) -> None:
    """Show open match_review rows."""
    rows = _repo().list_reviews(authority, reason)
    table = Table(title=f"open reviews ({len(rows)})")
    for col in ("id", "authority", "reason", "film", "value", "detail"):
        table.add_column(col)
    for r in rows:
        film = f"#{r['film_id']} {r['title']} ({r['year']})" if r["film_id"] is not None else ""
        table.add_row(str(r["id"]), str(r["authority"]), str(r["reason"]), film, str(r["value"] or ""), str(r["detail"] or ""))
    console.print(table)


@review_app.command("resolve")
def review_resolve(
    review_id: Annotated[int, typer.Argument(help="match_review id (see `review list`).")],
    film: Annotated[int | None, typer.Option("--film", help="Match to / merge into this film id.")] = None,
    tmdb_id: Annotated[int | None, typer.Option("--tmdb-id", help="Claim this TMDB id (tmdb no-match rows).")] = None,
    create: Annotated[bool, typer.Option("--create", help="Create a new film from the staged/owned title.")] = False,
    dismiss: Annotated[bool, typer.Option("--dismiss", help="Close the row; it is never re-queued.")] = False,
    note: Annotated[str | None, typer.Option("--note")] = None,
) -> None:
    """Resolve one open review row."""
    token = load_tmdb_token(load_config())
    client = TmdbClient(token) if token else None
    try:
        outcome = resolve_review(
            _repo(), review_id, today=date.today(), film_id=film, tmdb_id=tmdb_id, create=create,
            dismiss=dismiss, client=client, note=note,
        )
    except ValueError as exc:
        err.print(str(exc))
        raise typer.Exit(1) from exc
    console.print(f"review {review_id}: {outcome}")
```

- [ ] **Step 4: Verify** — `uv run pytest && uv run ruff check . && uv run mypy` → green. Also smoke: `uv run movie-brain review list --reason id-conflict | head` against the live DB (read-only) prints 28 rows.
- [ ] **Step 5: Commit** — `git add -A src tests && git commit -m "M3: repair and review CLI verbs"`

---

### Task 9: "Needs revisit" flag (backlog item 9) — migration, repo, API, drawer, chip, CLI drain

**Files:**
- Create: `migrations/009_needs_revisit.sql`, `tests/features/revisit.feature`, `tests/step_defs/test_revisit.py`
- Modify: `database.py`, `domain/models.py`, `domain/filters.py`, `web/app.py`, `web/static/app.js`, `web/templates/index.html`, `cli.py`, `tests/unit/test_filters.py`, `tests/web/test_api.py`, `docs/backlog.md`

**Interfaces:**
- `Repository.toggle_revisit(film_id, today, note=None) -> bool | None` (None = unknown film)
- `Repository.set_revisit_note(film_id, note) -> bool`
- `Repository.clear_revisit(film_id) -> None` (replaces the Task 4 stub)
- `Repository.revisits() -> list[tuple[int, str, int | None, str, str | None]]` — `(film_id, title, year, marked_on, note)`
- `FilmView.needs_revisit: bool = False`, `FilmView.revisit_note: str | None = None`
- chip `needs_revisit`; routes `POST /api/films/<id>/revisit` (optional JSON `{"note": str}`) → `{"needs_revisit": bool}`, `PUT /api/films/<id>/revisit` (`{"note": str}`) → 200/404
- CLI `movie-brain review revisits`

- [ ] **Step 1: Migration**

```sql
-- Backlog item 9 (shipped in M3): user-set "needs revisit" flag for factually suspect films.
-- Watchlist pattern: user-response data, drawer toggle is the only UI writer, never touched
-- by sync/importers; the repair/review CLI clears it when the film is resolved.
BEGIN;
CREATE TABLE needs_revisit (
    film_id   INTEGER PRIMARY KEY REFERENCES films(id),
    marked_on TEXT NOT NULL,
    note      TEXT
);
INSERT INTO schema_version (version) VALUES (9);
COMMIT;
```

- [ ] **Step 2: Tests**

`tests/features/revisit.feature`:
```gherkin
Feature: Needs-revisit flag

  Background:
    Given a repository with films "Alpha (1950)" on Criterion and "Alpha (1951)" from commerce

  Scenario: Toggling marks and unmarks a film with an optional note
    When I flag "Alpha (1951)" for revisit with note "year suspect"
    Then "Alpha (1951)" is flagged with note "year suspect"
    When I flag "Alpha (1951)" for revisit with note ""
    Then "Alpha (1951)" is not flagged

  Scenario: Resolving a review clears the flag
    Given "Alpha (1951)" is flagged for revisit
    And an open tmdb "no-match" review for "Alpha (1951)"
    When that review is dismissed
    Then "Alpha (1951)" is not flagged

  Scenario: Merging drops the loser's flag and keeps the survivor's
    Given "Alpha (1951)" is flagged for revisit
    And "Alpha (1950)" is flagged for revisit
    When I merge "Alpha (1951)" into "Alpha (1950)"
    Then "Alpha (1950)" is flagged with note ""
    And the revisit worklist lists only "Alpha (1950)"

  Scenario: A sync never touches the flag
    Given "Alpha (1951)" is flagged for revisit
    When Criterion lists "Alpha (1951)" again
    Then "Alpha (1951)" is flagged with note ""
```
`tests/step_defs/test_revisit.py` — reuse the seed/merge/rewalk steps by importing them:
```python
from __future__ import annotations

from datetime import date

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.review import resolve_review
from movie_brain.domain.models import ReviewEntry
from tests.step_defs.test_repair import _key, merge, rewalk, seed  # noqa: F401  (registers the shared steps)

scenarios("../features/revisit.feature")
TODAY = date(2026, 8, 19)


@pytest.fixture
def ctx(repo, config_dir):
    return {"repo": repo, "config_dir": config_dir, "review_id": None}


@given(parsers.parse('"{spec}" is flagged for revisit'))
def flagged(ctx, spec):
    ctx["repo"].toggle_revisit(ctx["repo"].film_id_by_key(_key(spec)), TODAY)


@given(parsers.parse('an open tmdb "no-match" review for "{spec}"'))
def open_review(ctx, spec):
    fid = ctx["repo"].film_id_by_key(_key(spec))
    ctx["repo"].upsert_tmdb(fid, found=False, looked_up=TODAY)
    ctx["repo"].append_reviews("tmdb", [ReviewEntry("no-match", film_id=fid)], TODAY)
    ctx["review_id"] = ctx["repo"].open_reviews("tmdb")[-1]["id"]


@when(parsers.parse('I flag "{spec}" for revisit with note "{note}"'))
def toggle(ctx, spec, note):
    ctx["repo"].toggle_revisit(ctx["repo"].film_id_by_key(_key(spec)), TODAY, note=note or None)


@when("that review is dismissed")
def dismissed(ctx):
    resolve_review(ctx["repo"], ctx["review_id"], dismiss=True, today=TODAY)


@then(parsers.parse('"{spec}" is flagged with note "{note}"'))
def is_flagged(ctx, spec, note):
    v = ctx["repo"].get_view(ctx["repo"].film_id_by_key(_key(spec)), TODAY)
    assert v.needs_revisit and (v.revisit_note or "") == note


@then(parsers.parse('"{spec}" is not flagged'))
def not_flagged(ctx, spec):
    assert not ctx["repo"].get_view(ctx["repo"].film_id_by_key(_key(spec)), TODAY).needs_revisit


@then(parsers.parse('the revisit worklist lists only "{spec}"'))
def worklist(ctx, spec):
    assert [r[0] for r in ctx["repo"].revisits()] == [ctx["repo"].film_id_by_key(_key(spec))]
```
`tests/unit/test_filters.py` (append):
```python
def test_needs_revisit_chip():
    from dataclasses import replace

    from movie_brain.domain.filters import CHIPS, matches
    from movie_brain.domain.models import FilmView

    v = FilmView(1, "A", 1950, None, None, None, None, None, None, False, None, None, None)
    assert "needs_revisit" in CHIPS
    assert not matches(v, ["needs_revisit"], date(2026, 8, 19))
    assert matches(replace(v, needs_revisit=True), ["needs_revisit"], date(2026, 8, 19))
```
`tests/web/test_api.py` (append):
```python
def test_revisit_toggle_and_note(client):
    fid = client.get("/api/films").get_json()[0]["id"]
    r = client.post(f"/api/films/{fid}/revisit", json={"note": "wrong film"})
    assert r.status_code == 200 and r.get_json() == {"needs_revisit": True}
    d = client.get(f"/api/films/{fid}").get_json()
    assert d["needs_revisit"] is True and d["revisit_note"] == "wrong film"
    assert client.put(f"/api/films/{fid}/revisit", json={"note": "year suspect"}).status_code == 200
    assert client.get(f"/api/films/{fid}").get_json()["revisit_note"] == "year suspect"
    r = client.post(f"/api/films/{fid}/revisit")
    assert r.get_json() == {"needs_revisit": False}
    assert client.post("/api/films/999/revisit").status_code == 404
    assert "needs_revisit" in client.get("/api/config").get_json()["chips"]
```

- [ ] **Step 3: Run to verify failure** — `uv run pytest tests/step_defs/test_revisit.py tests/unit/test_filters.py tests/web/test_api.py -v`.

- [ ] **Step 4: Implement**

`database.py`:
```python
    # needs revisit -------------------------------------------------------
    def toggle_revisit(self, film_id: int, today: date, note: str | None = None) -> bool | None:
        with self._conn() as c:
            if c.execute("SELECT 1 FROM films WHERE id = ?", (film_id,)).fetchone() is None:
                return None
            if c.execute("SELECT 1 FROM needs_revisit WHERE film_id = ?", (film_id,)).fetchone() is None:
                c.execute(
                    "INSERT INTO needs_revisit (film_id, marked_on, note) VALUES (?, ?, ?)",
                    (film_id, today.isoformat(), note),
                )
                return True
            c.execute("DELETE FROM needs_revisit WHERE film_id = ?", (film_id,))
            return False

    def set_revisit_note(self, film_id: int, note: str | None) -> bool:
        with self._conn() as c:
            return c.execute("UPDATE needs_revisit SET note = ? WHERE film_id = ?", (note, film_id)).rowcount > 0

    def clear_revisit(self, film_id: int) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM needs_revisit WHERE film_id = ?", (film_id,))

    def revisits(self) -> list[tuple[int, str, int | None, str, str | None]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT n.film_id, f.title, f.year, n.marked_on, n.note FROM needs_revisit n "
                "JOIN films f ON f.id = n.film_id ORDER BY n.marked_on, n.film_id"
            ).fetchall()
            return [(int(r["film_id"]), str(r["title"]), r["year"], str(r["marked_on"]), r["note"]) for r in rows]
```
Add `def _revisit_by_film(c) -> dict[int, str | None]` (`SELECT film_id, note FROM needs_revisit`) next to `_watchlist_ids`; thread `revisit: tuple[bool, str | None]` into `_row_to_view` → `needs_revisit=`, `revisit_note=`; call it from `list_views` and `get_view` like `wl`/`ow`. In `merge_film`, before the `_ONE_ROW_TABLES` loop: `c.execute("DELETE FROM needs_revisit WHERE film_id = ?", (loser_id,))` — the merge IS the loser's resolution (do NOT add `needs_revisit` to `_ONE_ROW_TABLES`). Remove the Task 4 stub.

`models.py` `FilmView`: add `needs_revisit: bool = False` and `revisit_note: str | None = None` after `owned`.

`filters.py`: `"needs_revisit": lambda v, _: v.needs_revisit,` at the end of `_PREDICATES`.

`web/app.py`:
```python
    @app.post("/api/films/<int:film_id>/revisit")
    def toggle_revisit(film_id: int) -> tuple[Response, int]:
        body = request.get_json(silent=True)
        note = body.get("note") if isinstance(body, dict) and isinstance(body.get("note"), str) else None
        flagged = repo.toggle_revisit(film_id, today(), note=note or None)
        if flagged is None:
            return jsonify({"error": "not found"}), 404
        return jsonify({"needs_revisit": flagged}), 200

    @app.put("/api/films/<int:film_id>/revisit")
    def put_revisit_note(film_id: int) -> tuple[Response, int]:
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not isinstance(body.get("note"), (str, type(None))):
            return jsonify({"error": 'body must be JSON {"note": str | null}'}), 400
        if not repo.set_revisit_note(film_id, body["note"] or None):
            return jsonify({"error": "not flagged"}), 404
        return jsonify({"ok": True}), 200
```

`index.html`: add `<button class="chip" data-chip="needs_revisit">Needs revisit</button>` after the `not_owned` chip.

`app.js`:
- `CHIP_PREDICATES`: `needs_revisit: (f) => f.needs_revisit,`
- drawer header (line ~311): after the watch-toggle button add
  `<button class="revisit-toggle" data-id="${d.id}" title="Toggle needs-revisit" aria-label="Toggle needs-revisit">${d.needs_revisit ? '⚑' : '⚐'}</button>` and, when flagged, `<input class="revisit-note" data-id="${d.id}" placeholder="what looks wrong?" value="${esc(d.revisit_note || '')}">` right below the `<h2>`.
- handlers next to the watch-toggle handler:
```js
  body.addEventListener('click', async (e) => {
    const b = e.target.closest('.revisit-toggle'); if (!b) return;
    const r = await fetch(`/api/films/${b.dataset.id}/revisit`, { method: 'POST' });
    if (!r.ok) { toast('Could not update revisit flag'); return; }
    const { needs_revisit } = await r.json();
    const film = state.films.find((f) => f.id === Number(b.dataset.id));
    if (film) { film.needs_revisit = needs_revisit; if (!needs_revisit) film.revisit_note = null; applyFilters(); }
    openDrawer(Number(b.dataset.id), false);
  });
  body.addEventListener('change', async (e) => {
    const i = e.target.closest('.revisit-note'); if (!i) return;
    const r = await fetch(`/api/films/${i.dataset.id}/revisit`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ note: i.value }) });
    if (!r.ok) { toast('Could not save note'); return; }
    const film = state.films.find((f) => f.id === Number(i.dataset.id));
    if (film) film.revisit_note = i.value;
  });
```
(`openDrawer(id, push)` and `toast` exist — check their exact names at `app.js:330-345` and adapt.)

`cli.py`:
```python
@review_app.command("revisits")
def review_revisits() -> None:
    """Films flagged 'needs revisit' in the drawer — the human worklist for repair/resolve."""
    rows = _repo().revisits()
    table = Table(title=f"needs revisit ({len(rows)})")
    for col in ("film", "title", "year", "marked", "note"):
        table.add_column(col)
    for fid, title, year, marked, note in rows:
        table.add_row(f"#{fid}", title, str(year or ""), marked, note or "")
    console.print(table)
```

`docs/backlog.md`: change item 9's `[ ]` to `[x]` and append " — shipped in M3 (2026-08-24)".

- [ ] **Step 5: Verify** — `uv run pytest && uv run ruff check . && uv run mypy`; then `uv run pytest tests/web/test_dashboard.py` (Playwright) to confirm the drawer still renders.
- [ ] **Step 6: Commit** — `git add -A && git commit -m "M3: needs-revisit drawer flag (backlog 9) — chip, API, CLI worklist, cleared on resolution"`

---

### Task 10: Live run, docs, Done line, handoff

**Files:**
- Modify: `CLAUDE.md`, `docs/superpowers/specs/2026-08-23-matching-overhaul-design.md` (M3 Done line), create `docs/superpowers/handoffs/2026-08-25-m3-done-handoff.md`

This task runs against the LIVE DB from the worktree (`MOVIE_BRAIN_CONFIG_DIR` default). Every applying step is preceded by a backup.

- [ ] **Step 1: Backup**
```bash
cp ~/.config/movie-brain/movie-brain.db ~/.config/movie-brain/movie-brain.db.bak-pre-m3
```
(init_db also snapshots into `backups/` when 008/009 apply.)

- [ ] **Step 2: Dry-runs, capture to scratchpad**
```bash
S=/private/tmp/claude-501/-Users-jayers-code-movie-brain/8114f6de-60c2-4f75-8853-c7002feeee33/scratchpad
uv run movie-brain repair dupes 2> "$S/dupes-dry.txt"; tail -1 "$S/dupes-dry.txt"
uv run movie-brain repair links 2> "$S/links-dry.txt"; tail -3 "$S/links-dry.txt"
uv run movie-brain repair years 2> "$S/years-dry.txt"; tail -1 "$S/years-dry.txt"
uv run movie-brain review list --reason year-gap > "$S/remakes.txt"
uv run movie-brain review list --authority apple-tv > "$S/apple.txt"
```
Read each file. Expected shape: dupes ≈49 norm-title groups + 28 id-conflict pairs, twins ≈ the id-conflict pairs plus any norm-title pairs sharing a tmdb id; links suspects small (Rambo class); years stale-omdb ≈ up to 266.

- [ ] **Step 3: Apply what the spec pre-authorizes**
  - `uv run movie-brain repair dupes --apply --yes` (only TWIN groups merge — same TMDB id, spec classification). Record counts.
  - `uv run movie-brain repair years --apply` (marks stale OMDb rows for refetch — finding 5).
  - `repair links --apply` ONLY after reading `links-dry.txt`: if every suspect is an obvious wrong film (different-language title, different year), apply; otherwise apply nothing and list the suspects in the handoff for the user.
  - Remake-suspected rows: for each of the 23 `year-gap` rows in `remakes.txt`, `uv run movie-brain review resolve ID --create` — they are verified real remakes (handoff), and promotion would have created them anyway. Skip any row whose staged title looks like a re-release rather than a remake and list it in the handoff.
  - Apple `year-drift` (7) and `no-match` (≈369): DO NOT resolve — list them in the handoff as the user's worklist with the exact `review resolve` commands.
- [ ] **Step 4: Sync + rematch + benchmark**
```bash
uv run movie-brain sync 2>&1 | tail -3
uv run movie-brain rematch 2>&1 | tail -3
uv run python scripts/matching_benchmark.py --assert-dominance | tail -5
uv run movie-brain review list | tail -1
sqlite3 ~/.config/movie-brain/movie-brain.db "SELECT kind, COUNT(*) FROM film_disposition GROUP BY 1; SELECT COUNT(*) FROM owned o JOIN film_disposition d ON d.film_id = o.film_id;"
```
Expected: the last query returns 0 (owned marks sit on canonical rows — Done criterion); audit line 0; dominance exit 0.

- [ ] **Step 5: Docs**
  - `CLAUDE.md` Commands: add `repair dupes|links|years`, `review list|resolve|revisits`. Rules: add a "Dispositions" bullet (film_disposition ledger; merged = alias to survivor, tombstoned = hidden + never re-created; `_NOT_DISPOSED` in every film query; `films_for_matching` aliases merged titles; only repair verbs write it) and a "Review resolution" bullet (a resolved row is a standing decision — `suppress_resolved`/`rebuild_no_match_queue`/`queue_review_once` never re-queue it) and a "needs_revisit" bullet (watchlist pattern; drawer is the UI writer; CLI clears on resolution/merge/year fix).
  - Spec M3 Done line: date, counts (groups dispositioned, merges, links cleared, remakes created, review open counts before/after, owned-on-canonical = 0), and "backlog item 9 shipped inside M3".
  - Handoff `docs/superpowers/handoffs/2026-08-25-m3-done-handoff.md`: status, live numbers, the user's remaining worklist (apple year-drift commands, no-match strategy, undecided dup groups, any un-cleared link suspects), riding minors not taken, next-phase candidates (iTunes Search adapter; default dashboard scope).
- [ ] **Step 6: Final verification + commit**
```bash
uv run pytest && uv run ruff check . && uv run mypy && uv run python scripts/matching_benchmark.py --assert-dominance
git add -A && git commit -m "M3 done: live repair run, docs, handoff"
```
Then follow `superpowers:finishing-a-development-branch` (merge to main, push, delete worktree).

---

## Self-review

- **Spec coverage:** dupes verb + TMDB-id classification + confirmation + merge moving owned/watchlist/my_ratings/external_ids/listings/omdb/tmdb + alias + tombstone + disposition migration + ingesters check (T1, T2, T5); years verb dry-run→apply (T7); review resolution match/create/dismiss draining apple/tmdb/metacritic queues (T4, T8, T10); Done criteria measured in T10 Step 4. Handoff fold-ins: link re-validation (T6), Metropolis ground truth (T3), backlog 9 decided IN (T9), OMDb refetch for adopted films (T7 stale-omdb), re-derive id-conflict at resolution time (T4 `holder` re-derivation, T5 audit), unguarded `update_film_year` (T7).
- **Placeholder scan:** none; the only "adapt" note is the drawer helper names in T9 which the executor reads at the cited lines.
- **Type consistency:** `merge_film(loser_id, survivor_id, today, note)` used identically in T1/T4/T5/T9; `clear_revisit` stubbed in T4, realized in T9; `rebuild_no_match_queue(repo, today)` defined T4 and used by the T4 test; `resolved_review_keys` returns `(reason, film_id, value)` triples everywhere; `RepairFilm` fields match `_rank`/`format_group`/`audit_dupes`; `TmdbClient.movie_titles` returns the 3-tuple `audit_links` unpacks.
