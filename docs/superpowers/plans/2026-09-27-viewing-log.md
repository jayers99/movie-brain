# Viewing Log Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One deterministic verb, `movie-brain viewings add`, writes a dated viewing plus the owner's dictated words against a film resolved by title (open drawer → single match → ask), the drawer and a Watched chip/column read the log back, and a project skill tells the agent how to drive it from a dictation.

**Architecture:** Hexagonal, as the rest of the app: migration `031_viewing.sql` adds `viewing` and `artefact`; `Repository` gains the writes, the reads and the drawer-signal helpers; a new `application/viewings.py` holds the title ladder and the outcomes (no SQL, no HTTP); `cli.py` gains a `viewings` typer app (add / remove / list / open); `web/app.py` gains `PUT /api/drawer` and detail-only `viewings` + `old_ratings`; `app.js` / `index.html` / `app.css` gain the read-only Watched block, the Watched chip, the Watched column, the drawer heartbeat and the focus refresh; `.claude/skills/log-viewing/SKILL.md` documents the agent's side. No HTTP write path for viewings.

**Tech Stack:** Python 3.12, typer, Flask, SQLite (migrations dir), pytest + pytest-bdd (`tests/features/*.feature` + `tests/step_defs/`), Playwright for `tests/web/`, vanilla JS in `static/app.js`.

**Spec:** `docs/superpowers/briefs/2026-09-21-viewing-log/brief-2.md` (version 2.2; its Decisions table is the contract), with `shaping.md` §7 (the owner's rulings) and `mockup-2.html` (what he approves). Trial log: `trial-log.md` in the same folder.

## Global Constraints

- Migration number is **031** (`schema_version` 30 is applied live); insert its row as `INSERT INTO schema_version (version) VALUES (31);` inside `BEGIN; … COMMIT;` — never edit an applied migration; `migrate --apply` on the live DB needs the owner's separate yes.
- Registry slugs are the real ones: `criterion` (Criterion Channel), `kino-film-collection`, `apple-tv-store`, `apple-tv-plus`, `max`, `kanopy`. Never `criterion-channel`.
- The ladder never reads the `films.title_norm` column (empty for 764 films). One normaliser, both sides, at query time: `movie_brain.domain.thumbprint.title_norm`.
- Candidates are canonical films only: no row in `film_disposition` (`_NOT_DISPOSED` in `database.py`).
- Every refusal writes nothing: the whole `viewings add` write is one `Repository._conn()` transaction, and validation happens before it.
- Exit codes: `0` written, `2` refused (bad input, unknown service, bad date/rating, unknown viewing/note), `3` unresolved (`AMBIGUOUS` / `NO-FILM`).
- One viewing per film per day (`UNIQUE(film_id, watched_on)`); a second add appends an artefact; a line's `service` is set once and never overwritten.
- The rating is written only through the existing `rate_film` (`application/ratings.py`); the drawer's rating box keeps writing as today. Unseen is cleared through `set_unseen(film_id, False, today)`, which touches nothing else.
- The drawer signal lives in `meta` under key `drawer_film`, JSON `{"film_id": <int|null>, "at": "<ISO seconds>"}`; a reading trusts it for **120 seconds**; the page re-reports every **30 seconds** while a drawer is open.
- Sync, `enrich`, every import verb never write `viewing` or `artefact`; `merge_film` re-points viewings; the page keeps nothing in browser storage.
- Do NOT edit `docs/backlog.md` in this plan: the working tree carries an unrelated uncommitted hunk (item 23); the item-27 line is updated at merge time.
- No hard-wrapped prose in any `.md` you write (one paragraph per line).
- Commit after every task with a one-line "why" message ending in `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Review Focus

1. **A title made only of stop words** ("The", "Versus") → the nearest-title lookup must not crash or call `title_hits("")`; the verb answers `NO-FILM` with no nearest list. (Pinned in Task 4.)
2. **`--film ID` naming a merged-away, tombstoned or nonexistent film** → `REFUSED`, nothing written; the resolver never accepts a non-canonical id even when handed one. (Pinned in Task 4.)
3. **`--rate 11`, `--rate -1`, `--rate 7.5`, blank or whitespace-only text, malformed `--on`** → each is `REFUSED` before the transaction opens; the tables are byte-for-byte unchanged. (Pinned in Task 4 and Task 5.)
4. **The open film carries the dictated title but a different `--year`** → rung 1 is skipped and rung 2 decides (Solaris 1972 open, `--title Solaris --year 2002` logs #5235). (Pinned in Task 4.)
5. **A stale drawer report** (older than 120 s) → `viewings open` says nothing is open and the ladder starts at rung 2; a fresh report on a film whose title differs from the dictation also falls to rung 2. (Pinned in Task 3 and Task 4.)

---

### Task 1: Migration 031 and the repository's viewing writes and reads

**Files:**
- Create: `migrations/031_viewing.sql`
- Modify: `src/movie_brain/infrastructure/database.py` (new section after the `# rank_mark` section, around line 2770; `_ONE_ROW_TABLES` at line 194 is NOT touched)
- Test: `tests/unit/test_viewings_repository.py` (new)

**Interfaces:**
- Consumes: `Repository._conn()`, `Repository.set_rating`, `Repository.set_unseen`, `Film`, `OldRating`.
- Produces (all on `Repository`):
  - `add_viewing(film_id: int, watched_on: date, service: str | None, text: str, rate: int | None, today: date) -> ViewingWrite` where `ViewingWrite` is a frozen dataclass `(viewing_id: int, created: bool, note_count: int)` defined in `domain/models.py`.
  - `viewings_for(film_id: int) -> list[dict[str, object]]` newest first: `{id, watched_on, service, service_name, artefacts: [{id, kind, text, added_on}]}`.
  - `remove_viewing(viewing_id: int) -> dict[str, object] | None` → `{film_id, watched_on, notes}` of the removed row, `None` when absent.
  - `remove_artefact(viewing_id: int, n: int) -> dict[str, object] | None` → `{film_id, watched_on, notes_left}`; `None` when the viewing or note `n` (1-based, in `added_on, id` order) does not exist.
  - `list_viewings(since: date | None = None, film_id: int | None = None) -> list[dict[str, object]]` newest first: `{id, film_id, title, year, watched_on, service, notes, my_rating}`.
  - `old_ratings_for(film_id: int) -> list[dict[str, object]]` newest first, same-date same-stars rows collapsed: `{stars, rented_on}`.
  - `service_name(slug: str) -> str | None`.
  - `canonical_titles() -> list[tuple[int, str, int | None, str | None]]` — `(id, title, year, director)` for every film with no disposition row.

- [ ] **Step 1: Write the migration**

```sql
-- Backlog 27 (viewing log, brief 2.2). A viewing is a dated EVENT against a film, one per film
-- per day; an artefact is something the owner said or wrote about that viewing — v1 knows one
-- kind, `dictation` (his words, whole). The 0–10 stays in my_ratings; nothing here is a rating.
-- Many rows per film (NOT in _ONE_ROW_TABLES): merge_film re-points viewing.film_id and folds a
-- same-date collision's artefacts onto the survivor's viewing. `service` is a registry slug or
-- NULL (a disc, a cinema). Only `movie-brain viewings add` writes here; sync and every import
-- verb never do.
BEGIN;
CREATE TABLE viewing (
    id         INTEGER PRIMARY KEY,
    film_id    INTEGER NOT NULL REFERENCES films(id),
    watched_on TEXT    NOT NULL,
    service    TEXT    REFERENCES movie_service(slug),
    logged_on  TEXT    NOT NULL,
    UNIQUE (film_id, watched_on)
);
CREATE TABLE artefact (
    id         INTEGER PRIMARY KEY,
    viewing_id INTEGER NOT NULL REFERENCES viewing(id) ON DELETE CASCADE,
    kind       TEXT    NOT NULL CHECK (kind IN ('dictation')),
    text       TEXT    NOT NULL CHECK (length(trim(text)) > 0),
    added_on   TEXT    NOT NULL
);
CREATE INDEX artefact_viewing ON artefact(viewing_id);
INSERT INTO schema_version (version) VALUES (31);
COMMIT;
```

- [ ] **Step 2: Add `ViewingWrite` to `domain/models.py`** (after `OldRating`, around line 232)

```python
@dataclass(frozen=True)
class ViewingWrite:
    """What one `viewings add` wrote: the viewing's id, whether it was created by this write
    (False = the day already had a line and the artefact was appended), and the line's note count."""

    viewing_id: int
    created: bool
    note_count: int
```

- [ ] **Step 3: Write the failing repository tests**

```python
"""Repository writes and reads for the viewing log (brief 2.2, migration 031)."""

from __future__ import annotations

import sqlite3
from datetime import date

import pytest

from movie_brain.domain.models import Film, OldRating

TODAY = date(2026, 9, 27)


def _q(repo, sql, *args):
    conn = sqlite3.connect(repo.db_path)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


@pytest.fixture
def blue(repo):
    fid = repo.create_film(Film("The Blue Angel", 1930, None, ""))
    assert fid is not None
    repo.register_provider(1899, "Kino Film Collection")  # slug kino-film-collection
    return fid


def test_add_viewing_writes_viewing_artefact_rating_and_clears_unseen(repo, blue):
    repo.set_unseen(blue, True, TODAY)
    w = repo.add_viewing(blue, TODAY, "kino-film-collection", "pretty good", 6, TODAY)
    assert w.created is True and w.note_count == 1
    assert _q(repo, "SELECT film_id, watched_on, service, logged_on FROM viewing") == [(blue, "2026-09-27", "kino-film-collection", "2026-09-27")]
    assert _q(repo, "SELECT kind, text FROM artefact WHERE viewing_id = ?", w.viewing_id) == [("dictation", "pretty good")]
    assert _q(repo, "SELECT score FROM my_ratings WHERE film_id = ?", blue) == [(6,)]
    assert _q(repo, "SELECT 1 FROM unseen WHERE film_id = ?", blue) == []


def test_second_add_same_day_appends_and_never_overwrites_the_service(repo, blue):
    repo.register_provider(8, "Kanopy")
    first = repo.add_viewing(blue, TODAY, "kino-film-collection", "first", None, TODAY)
    second = repo.add_viewing(blue, TODAY, "kanopy", "second", 7, TODAY)
    assert second.viewing_id == first.viewing_id and second.created is False and second.note_count == 2
    assert _q(repo, "SELECT service FROM viewing") == [("kino-film-collection",)]
    assert _q(repo, "SELECT score FROM my_ratings WHERE film_id = ?", blue) == [(7,)]


def test_second_add_fills_a_service_the_line_had_none_of(repo, blue):
    repo.add_viewing(blue, TODAY, None, "first", None, TODAY)
    repo.add_viewing(blue, TODAY, "kino-film-collection", "second", None, TODAY)
    assert _q(repo, "SELECT service FROM viewing") == [("kino-film-collection",)]


def test_no_rate_leaves_the_standing_rating_alone(repo, blue):
    repo.set_rating(blue, 9, TODAY)
    repo.add_viewing(blue, TODAY, None, "still good", None, TODAY)
    assert _q(repo, "SELECT score FROM my_ratings WHERE film_id = ?", blue) == [(9,)]


def test_viewings_for_is_newest_first_with_artefacts(repo, blue):
    repo.add_viewing(blue, date(2026, 9, 21), "kino-film-collection", "monday", None, TODAY)
    repo.add_viewing(blue, TODAY, None, "today a", None, TODAY)
    repo.add_viewing(blue, TODAY, None, "today b", None, TODAY)
    vs = repo.viewings_for(blue)
    assert [v["watched_on"] for v in vs] == ["2026-09-27", "2026-09-21"]
    assert vs[1]["service_name"] == "Kino Film Collection"
    assert [a["text"] for a in vs[0]["artefacts"]] == ["today a", "today b"]
    assert vs[0]["service"] is None and vs[0]["service_name"] is None


def test_remove_viewing_takes_its_artefacts_and_leaves_rating_and_unseen(repo, blue):
    w = repo.add_viewing(blue, TODAY, None, "oops", 5, TODAY)
    gone = repo.remove_viewing(w.viewing_id)
    assert gone == {"film_id": blue, "watched_on": "2026-09-27", "notes": 1}
    assert _q(repo, "SELECT COUNT(*) FROM viewing")[0][0] == 0
    assert _q(repo, "SELECT COUNT(*) FROM artefact")[0][0] == 0
    assert _q(repo, "SELECT score FROM my_ratings WHERE film_id = ?", blue) == [(5,)]
    assert repo.remove_viewing(w.viewing_id) is None


def test_remove_artefact_drops_one_note_and_keeps_the_viewing(repo, blue):
    w = repo.add_viewing(blue, TODAY, None, "one", None, TODAY)
    repo.add_viewing(blue, TODAY, None, "two", None, TODAY)
    repo.add_viewing(blue, TODAY, None, "three", None, TODAY)
    assert repo.remove_artefact(w.viewing_id, 2) == {"film_id": blue, "watched_on": "2026-09-27", "notes_left": 2}
    assert [a["text"] for a in repo.viewings_for(blue)[0]["artefacts"]] == ["one", "three"]
    assert repo.remove_artefact(w.viewing_id, 5) is None
    assert repo.remove_artefact(999, 1) is None


def test_list_viewings_since_and_for_a_film(repo, blue):
    cuba = repo.create_film(Film("I Am Cuba", 1964, None, ""))
    repo.set_rating(cuba, 9, TODAY)
    repo.add_viewing(blue, date(2026, 8, 30), None, "august", None, TODAY)
    repo.add_viewing(blue, date(2026, 9, 21), None, "monday", None, TODAY)
    repo.add_viewing(cuba, TODAY, None, "cuba", None, TODAY)
    rows = repo.list_viewings(since=date(2026, 9, 1))
    assert [(r["title"], r["watched_on"], r["notes"], r["my_rating"]) for r in rows] == [("I Am Cuba", "2026-09-27", 1, 9), ("The Blue Angel", "2026-09-21", 1, None)]
    assert [r["watched_on"] for r in repo.list_viewings(film_id=blue)] == ["2026-09-21", "2026-08-30"]
    assert repo.list_viewings(since=date(2027, 1, 1)) == []


def test_old_ratings_for_collapses_a_duplicate_row_and_is_newest_first(repo, blue):
    repo.upsert_old_rating("ntc", OldRating(28, "Love & Anarchy", 1973, 5, "2004-06-22"))
    repo.upsert_old_rating("ntc", OldRating(29, "Love and Anarchy", 1973, 5, "2004-06-22"))
    repo.upsert_old_rating("ntc", OldRating(30, "Love and Anarchy", 1973, 4, "2006-01-05"))
    for line in (28, 29, 30):
        repo.link_old_rating("ntc", line, blue, "hand", TODAY)
    assert repo.old_ratings_for(blue) == [{"stars": 4, "rented_on": "2006-01-05"}, {"stars": 5, "rented_on": "2004-06-22"}]


def test_service_name_and_canonical_titles(repo, blue):
    assert repo.service_name("kino-film-collection") == "Kino Film Collection"
    assert repo.service_name("criterion-channel") is None
    ghost = repo.create_film(Film("Ghost Row", 1999, None, ""))
    repo.tombstone_film(ghost, TODAY)
    ids = {row[0] for row in repo.canonical_titles()}
    assert blue in ids and ghost not in ids
    assert next(row for row in repo.canonical_titles() if row[0] == blue) == (blue, "The Blue Angel", 1930, None)
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_viewings_repository.py -q`
Expected: FAIL — `AttributeError: 'Repository' object has no attribute 'add_viewing'` (and the schema has no `viewing` table). Also run `uv run pytest tests/unit/test_database.py -q -k migration` to see how a fresh DB bootstraps every migration; a fresh `Repository(path)` must now reach version 31.

- [ ] **Step 5: Implement the repository section** (insert after `set_rank_mark`, before the `# needs revisit` or wishlist section; import `ViewingWrite` from `movie_brain.domain.models` alongside the other model imports at the top of `database.py`)

```python
    # viewings (brief 2026-09-21-viewing-log/brief-2.md) ------------------------------
    def add_viewing(
        self, film_id: int, watched_on: date, service: str | None, text: str, rate: int | None, today: date
    ) -> ViewingWrite:
        """One transaction: the day's viewing (created, or found), one `dictation` artefact,
        the 0–10 when a number was said, and the Unseen mark cleared. A line's service is set
        once and never overwritten. Validation (film canonical, slug known, text non-blank,
        rate 0–10) is the caller's — application/viewings.py — so nothing here refuses."""
        with self._conn() as c:
            row = c.execute(
                "SELECT id, service FROM viewing WHERE film_id = ? AND watched_on = ?",
                (film_id, watched_on.isoformat()),
            ).fetchone()
            if row is None:
                cur = c.execute(
                    "INSERT INTO viewing (film_id, watched_on, service, logged_on) VALUES (?, ?, ?, ?)",
                    (film_id, watched_on.isoformat(), service, today.isoformat()),
                )
                vid, created = int(cur.lastrowid), True
            else:
                vid, created = int(row["id"]), False
                if service and row["service"] is None:
                    c.execute("UPDATE viewing SET service = ? WHERE id = ?", (service, vid))
            c.execute(
                "INSERT INTO artefact (viewing_id, kind, text, added_on) VALUES (?, 'dictation', ?, ?)",
                (vid, text, today.isoformat()),
            )
            if rate is not None:
                c.execute(
                    "INSERT INTO my_ratings (film_id, score, rated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(film_id) DO UPDATE SET score=excluded.score, rated_at=excluded.rated_at",
                    (film_id, rate, today.isoformat()),
                )
            c.execute("DELETE FROM unseen WHERE film_id = ?", (film_id,))
            n = int(c.execute("SELECT COUNT(*) FROM artefact WHERE viewing_id = ?", (vid,)).fetchone()[0])
            return ViewingWrite(vid, created, n)

    def viewings_for(self, film_id: int) -> list[dict[str, object]]:
        with self._conn() as c:
            out: list[dict[str, object]] = []
            for v in c.execute(
                "SELECT v.id, v.watched_on, v.service, s.name AS service_name FROM viewing v "
                "LEFT JOIN movie_service s ON s.slug = v.service WHERE v.film_id = ? "
                "ORDER BY v.watched_on DESC, v.id DESC",
                (film_id,),
            ).fetchall():
                arts = [
                    {"id": int(a["id"]), "kind": str(a["kind"]), "text": str(a["text"]), "added_on": str(a["added_on"])}
                    for a in c.execute(
                        "SELECT id, kind, text, added_on FROM artefact WHERE viewing_id = ? ORDER BY added_on, id", (v["id"],)
                    )
                ]
                out.append({"id": int(v["id"]), "watched_on": str(v["watched_on"]), "service": v["service"], "service_name": v["service_name"], "artefacts": arts})
            return out

    def remove_viewing(self, viewing_id: int) -> dict[str, object] | None:
        with self._conn() as c:
            row = c.execute("SELECT film_id, watched_on FROM viewing WHERE id = ?", (viewing_id,)).fetchone()
            if row is None:
                return None
            notes = int(c.execute("SELECT COUNT(*) FROM artefact WHERE viewing_id = ?", (viewing_id,)).fetchone()[0])
            c.execute("DELETE FROM artefact WHERE viewing_id = ?", (viewing_id,))  # explicit: PRAGMA foreign_keys cascades too
            c.execute("DELETE FROM viewing WHERE id = ?", (viewing_id,))
            return {"film_id": int(row["film_id"]), "watched_on": str(row["watched_on"]), "notes": notes}

    def remove_artefact(self, viewing_id: int, n: int) -> dict[str, object] | None:
        with self._conn() as c:
            row = c.execute("SELECT film_id, watched_on FROM viewing WHERE id = ?", (viewing_id,)).fetchone()
            if row is None:
                return None
            ids = [int(a["id"]) for a in c.execute("SELECT id FROM artefact WHERE viewing_id = ? ORDER BY added_on, id", (viewing_id,))]
            if n < 1 or n > len(ids):
                return None
            c.execute("DELETE FROM artefact WHERE id = ?", (ids[n - 1],))
            return {"film_id": int(row["film_id"]), "watched_on": str(row["watched_on"]), "notes_left": len(ids) - 1}

    def list_viewings(self, since: date | None = None, film_id: int | None = None) -> list[dict[str, object]]:
        sql = (
            "SELECT v.id, v.film_id, f.title, f.year, v.watched_on, v.service, r.score, "
            "(SELECT COUNT(*) FROM artefact a WHERE a.viewing_id = v.id) AS notes "
            "FROM viewing v JOIN films f ON f.id = v.film_id LEFT JOIN my_ratings r ON r.film_id = v.film_id WHERE 1=1"
        )
        args: list[object] = []
        if since is not None:
            sql += " AND v.watched_on >= ?"; args.append(since.isoformat())
        if film_id is not None:
            sql += " AND v.film_id = ?"; args.append(film_id)
        sql += " ORDER BY v.watched_on DESC, v.id DESC"
        with self._conn() as c:
            return [
                {"id": int(r["id"]), "film_id": int(r["film_id"]), "title": str(r["title"]), "year": r["year"], "watched_on": str(r["watched_on"]), "service": r["service"], "notes": int(r["notes"]), "my_rating": r["score"]}
                for r in c.execute(sql, args)
            ]

    def old_ratings_for(self, film_id: int) -> list[dict[str, object]]:
        """Every real rental, newest first; two rows with the same date and stars are one rental
        listed twice in the source file (Love & Anarchy), shown once (round-1 finding 8)."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT DISTINCT stars, rented_on FROM old_rating WHERE film_id = ? "
                "ORDER BY COALESCE(rented_on, '') DESC, stars DESC",
                (film_id,),
            ).fetchall()
            return [{"stars": int(r["stars"]), "rented_on": r["rented_on"]} for r in rows]

    def service_name(self, slug: str) -> str | None:
        with self._conn() as c:
            row = c.execute("SELECT name FROM movie_service WHERE slug = ?", (slug,)).fetchone()
            return None if row is None else str(row["name"])

    def canonical_titles(self) -> list[tuple[int, str, int | None, str | None]]:
        """(id, title, year, director) for every film with no disposition row — the ladder's
        candidate set. The title is normalised by the CALLER at query time; the `title_norm`
        column is never read (empty for every film created since the backfill)."""
        with self._conn() as c:
            return [
                (int(r["id"]), str(r["title"]), r["year"], r["director"])
                for r in c.execute(f"SELECT f.id, f.title, f.year, f.director FROM films f WHERE {_NOT_DISPOSED} ORDER BY f.id")
            ]
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_viewings_repository.py tests/unit/test_database.py -q`
Expected: all PASS (the fresh-DB bootstrap now applies 031; if a pinned "latest version" assertion exists in `test_database.py`, update it from 30 to 31 in the same commit).

- [ ] **Step 7: Commit**

```bash
git add migrations/031_viewing.sql src/movie_brain/domain/models.py src/movie_brain/infrastructure/database.py tests/unit/test_viewings_repository.py tests/unit/test_database.py
git commit -m "Viewing log: migration 031 (viewing + artefact) and the repository's writes and reads — one viewing per film per day, many notes, a service set once

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: `merge_film` re-points viewings; a same-date collision folds its notes

**Files:**
- Modify: `src/movie_brain/infrastructure/database.py:3315-3330` (inside `merge_film`, after the `old_rating` re-point)
- Test: `tests/unit/test_viewings_repository.py` (append)

**Interfaces:**
- Consumes: `Repository.merge_film(loser_id, survivor_id, today)`, `add_viewing`, `viewings_for` from Task 1.
- Produces: `MergeReport.moved["viewing"]`, `moved["artefact"]` counts (the existing `moved: dict[str, int]`).

- [ ] **Step 1: Write the failing tests**

```python
def test_merge_repoints_viewings_and_folds_a_same_date_collision(repo):
    survivor = repo.create_film(Film("Godzilla", 1954, None, ""))
    loser = repo.create_film(Film("Gojira", 1954, None, ""))
    repo.add_viewing(loser, date(2026, 9, 20), None, "loser only", None, TODAY)
    repo.add_viewing(loser, TODAY, None, "loser today", None, TODAY)
    repo.add_viewing(survivor, TODAY, None, "survivor today", None, TODAY)
    report = repo.merge_film(loser, survivor, TODAY)
    vs = repo.viewings_for(survivor)
    assert [v["watched_on"] for v in vs] == ["2026-09-27", "2026-09-20"]
    assert [a["text"] for a in vs[0]["artefacts"]] == ["survivor today", "loser today"]
    assert repo.viewings_for(loser) == []
    assert report.moved.get("viewing") == 1 and report.moved.get("artefact") == 1
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_viewings_repository.py -q -k merge`
Expected: FAIL — the loser's viewings are still on the loser (or the UNIQUE constraint raises).

- [ ] **Step 3: Implement, right after the `old_rating` re-point in `merge_film`**

```python
            # Viewings (brief 2.2): many rows per film, so a plain re-point — except that the
            # survivor may already hold that day, when the loser's notes join the survivor's line.
            for row in c.execute("SELECT id, watched_on FROM viewing WHERE film_id = ?", (loser_id,)).fetchall():
                twin = c.execute(
                    "SELECT id FROM viewing WHERE film_id = ? AND watched_on = ?", (survivor_id, row["watched_on"])
                ).fetchone()
                if twin is None:
                    c.execute("UPDATE viewing SET film_id = ? WHERE id = ?", (survivor_id, row["id"]))
                    moved["viewing"] = moved.get("viewing", 0) + 1
                else:
                    n_art = c.execute("UPDATE artefact SET viewing_id = ? WHERE viewing_id = ?", (twin["id"], row["id"])).rowcount
                    c.execute("DELETE FROM viewing WHERE id = ?", (row["id"],))
                    moved["artefact"] = moved.get("artefact", 0) + n_art
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_viewings_repository.py tests/unit/test_repository_lists.py tests/step_defs/test_repair.py -q`
Expected: PASS (the repair suite exercises `merge_film` on films without viewings and must be unchanged).

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/infrastructure/database.py tests/unit/test_viewings_repository.py
git commit -m "Viewing log: merge_film re-points viewings and folds a same-date collision's notes onto the survivor's line

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: The read model — `last_watched`, `viewing_count`, viewed films always visible, the `watched` chip, the drawer signal, and the API

**Files:**
- Modify: `src/movie_brain/domain/models.py` (`FilmView`, after `old_rating` at line 368)
- Modify: `src/movie_brain/infrastructure/database.py` (`_row_to_view` line 562; `list_views` line 3693; `get_view` line 3738; a new `_viewing_stats_by_film` helper beside `_old_rating_by_film` line 453; drawer-signal helpers beside `get_meta` line 2278)
- Modify: `src/movie_brain/domain/filters.py:113-130` (`_PREDICATES` gains `watched`)
- Modify: `src/movie_brain/web/app.py:71-95` (detail keys) and a new `PUT /api/drawer` route beside `put_unseen` (line 329)
- Test: `tests/unit/test_filters.py` (the `CHIPS` pin), `tests/unit/test_viewings_repository.py` (append), `tests/web/test_api.py` (append)

**Interfaces:**
- Produces: `FilmView.last_watched: str | None`, `FilmView.viewing_count: int = 0`; predicate key `watched`; `Repository.set_drawer_film(film_id: int | None, now: datetime) -> None`; `Repository.drawer_film(now: datetime, max_age: timedelta = timedelta(seconds=120)) -> int | None`; `DRAWER_FILM_KEY = "drawer_film"`, `DRAWER_MAX_AGE = timedelta(seconds=120)` (module constants in `database.py`); `/api/films/<id>` keys `viewings` and `old_ratings`; `PUT /api/drawer` body `{"film_id": int | null}` → `200 {"film_id": …}`.

- [ ] **Step 1: Failing tests — the view and the chip**

Append to `tests/unit/test_viewings_repository.py`:

```python
from datetime import datetime, timedelta


def test_view_carries_last_watched_and_viewing_count(repo, blue):
    assert repo.get_view(blue, TODAY).viewing_count == 0 and repo.get_view(blue, TODAY).last_watched is None
    repo.add_viewing(blue, date(2026, 9, 21), None, "monday", None, TODAY)
    repo.add_viewing(blue, TODAY, None, "today", None, TODAY)
    v = repo.get_view(blue, TODAY)
    assert (v.last_watched, v.viewing_count) == ("2026-09-27", 2)
    listed = {x.id: x for x in repo.list_views("criterion", TODAY)}
    assert (listed[blue].last_watched, listed[blue].viewing_count) == ("2026-09-27", 2)


def test_a_viewed_film_is_visible_even_when_unrated_and_departed(repo):
    """The current-or-rated filter widens to current-or-rated-or-viewed (finding 14)."""
    repo.record_catalog("criterion", [Film("Cool Hand Luke", 1967, "Stuart Rosenberg", "https://c/luke"), Film("Stay", 1970, "S", "https://c/stay")], date(2026, 8, 1))
    repo.record_catalog("criterion", [Film("Stay", 1970, "S", "https://c/stay")], TODAY)  # Luke departs
    luke = repo.film_id_by_key("cool hand luke (1967)")
    assert luke not in {v.id for v in repo.list_views("criterion", TODAY)}
    repo.add_viewing(luke, TODAY, None, "watched it anyway", None, TODAY)
    assert luke in {v.id for v in repo.list_views("criterion", TODAY)}


def test_drawer_signal_is_trusted_for_two_minutes(repo, blue):
    now = datetime(2026, 9, 27, 21, 0, 0)
    assert repo.drawer_film(now) is None
    repo.set_drawer_film(blue, now)
    assert repo.drawer_film(now + timedelta(seconds=119)) == blue
    assert repo.drawer_film(now + timedelta(seconds=121)) is None
    repo.set_drawer_film(None, now)
    assert repo.drawer_film(now) is None
```

Edit `tests/unit/test_filters.py::test_chip_names_are_stable` to end its tuple with `"shop", "watched",` and add:

```python
def test_watched_chip_is_a_logged_viewing_not_a_rental():
    assert matches(view(viewing_count=1, last_watched="2026-09-27"), ["watched"], date(2026, 9, 27))
    assert not matches(view(old_rating={"stars": 5, "rented_on": "2005-01-12"}), ["watched"], date(2026, 9, 27))
```

(`view(**kw)` and `matches` are the helpers already at the top of that file — check the helper's name at line 30–37 and use it as written there.)

Append to `tests/web/test_api.py`:

```python
def test_detail_carries_viewings_and_all_rentals_and_the_drawer_route_records_the_open_film(client, repo):
    trio = repo.film_id_by_key("trio (1950)")
    repo.add_viewing(trio, D, None, "three tales, again", None, D)
    d = client.get(f"/api/films/{trio}").get_json()
    assert d["viewings"][0]["watched_on"] == "2026-08-19" and d["viewings"][0]["artefacts"][0]["text"] == "three tales, again"
    assert d["old_ratings"] == [] and d["viewing_count"] == 1 and d["last_watched"] == "2026-08-19"
    assert "viewings" not in client.get("/api/films").get_json()[0]  # detail-only
    r = client.put("/api/drawer", json={"film_id": trio})
    assert r.status_code == 200 and r.get_json() == {"film_id": trio}
    from datetime import datetime
    assert repo.drawer_film(datetime.now()) == trio
    assert client.put("/api/drawer", json={"film_id": None}).get_json() == {"film_id": None}
    assert repo.drawer_film(datetime.now()) is None
    assert client.put("/api/drawer", json={"film_id": "x"}).status_code == 400
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/unit/test_viewings_repository.py tests/unit/test_filters.py tests/web/test_api.py -q`
Expected: FAIL on `viewing_count`, on the `CHIPS` tuple, on `/api/drawer` 404.

- [ ] **Step 3: Implement**

`domain/models.py`, after `old_rating`:

```python
    # The viewing log (brief 2026-09-21-viewing-log/brief-2.md): last logged viewing date and how
    # many there are, for the Watched column and chip; the lines themselves are detail-only.
    last_watched: str | None = None
    viewing_count: int = 0
```

`database.py`, beside `_old_rating_by_film`:

```python
def _viewing_stats_by_film(c: sqlite3.Connection) -> dict[int, tuple[str, int]]:
    return {
        int(r["film_id"]): (str(r["last"]), int(r["n"]))
        for r in c.execute("SELECT film_id, MAX(watched_on) AS last, COUNT(*) AS n FROM viewing GROUP BY film_id")
    }
```

`_row_to_view`: add a keyword parameter `viewing: tuple[str, int] | None = None` and pass `last_watched=viewing[0] if viewing else None, viewing_count=viewing[1] if viewing else 0` into the `FilmView(...)` call. In `list_views` compute `vw = _viewing_stats_by_film(c)` once and pass `viewing=vw.get(r["id"])`; in `get_view` pass `viewing=_viewing_stats_by_film(c).get(row["id"])`. Widen the `list_views` WHERE clause:

```python
                + " AND (l.film_id IS NULL "
                + "OR l.last_seen = (SELECT MAX(last_seen) FROM listings WHERE source = ?) "
                + "OR r.score IS NOT NULL "
                + "OR EXISTS (SELECT 1 FROM viewing v WHERE v.film_id = f.id)) ORDER BY f.id",
```

Drawer signal, beside `get_meta` (add `from datetime import datetime, timedelta` to the imports if not present; `json` is already imported):

```python
DRAWER_FILM_KEY = "drawer_film"
DRAWER_MAX_AGE = timedelta(seconds=120)

    def set_drawer_film(self, film_id: int | None, now: datetime) -> None:
        """The dashboard's report of its open drawer (brief 2.2, "the open-film signal"): written on
        open, on close (None) and every 30 s while open; read by `viewings add` and `viewings open`."""
        self.set_meta(DRAWER_FILM_KEY, json.dumps({"film_id": film_id, "at": now.isoformat(timespec="seconds")}))

    def drawer_film(self, now: datetime, max_age: timedelta = DRAWER_MAX_AGE) -> int | None:
        raw = self.get_meta(DRAWER_FILM_KEY)
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            at = datetime.fromisoformat(str(data["at"]))
        except (ValueError, KeyError, TypeError):
            return None
        if data.get("film_id") is None or now - at > max_age or at > now + timedelta(seconds=5):
            return None
        return int(data["film_id"])
```

`domain/filters.py`: add `"watched": lambda v, _: v.viewing_count > 0,` as the LAST entry of `_PREDICATES` (after `shop`).

`web/app.py`: in `film_detail`'s `jsonify({...})` add `"viewings": repo.viewings_for(film_id), "old_ratings": repo.old_ratings_for(film_id),` (detail-only, like credits). Add beside `put_unseen` (import `datetime` from `datetime`):

```python
    @app.put("/api/drawer")
    def put_drawer() -> tuple[Response, int]:
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or "film_id" not in body or not (body["film_id"] is None or _is_int(body["film_id"])):
            return jsonify({"error": 'body must be JSON {"film_id": int | null}'}), 400
        repo.set_drawer_film(body["film_id"], datetime.now())
        return jsonify({"film_id": body["film_id"]}), 200
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit tests/web/test_api.py -q`
Expected: PASS. `tests/web/test_dashboard.py::test_chip_labels_and_order` will fail until Task 6 adds the button — that is expected and is fixed there; do not weaken the test now.

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/domain/models.py src/movie_brain/domain/filters.py src/movie_brain/infrastructure/database.py src/movie_brain/web/app.py tests/unit/test_viewings_repository.py tests/unit/test_filters.py tests/web/test_api.py
git commit -m "Viewing log read model: last_watched + viewing_count on the view, a viewed film is always visible, the watched chip, detail-only viewings and rentals, and the drawer's open-film report (trusted 120 s)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: `application/viewings.py` — the title ladder and the outcomes (BDD)

**Files:**
- Create: `src/movie_brain/application/viewings.py`
- Create: `tests/features/viewings.feature`, `tests/step_defs/test_viewings.py`

**Interfaces:**
- Consumes: `Repository.canonical_titles`, `drawer_film`, `title_hits`, `service_name`, `add_viewing`, `remove_viewing`, `remove_artefact`, `list_viewings`, `get_view`; `movie_brain.domain.thumbprint.title_norm`.
- Produces:

```python
STOP_WORDS = frozenset({"the", "a", "an", "of", "and", "vs", "versus"})

@dataclass(frozen=True)
class Candidate:
    film_id: int; title: str; year: int | None; director: str | None; best_source: str | None

@dataclass(frozen=True)
class Resolution:
    film_id: int | None          # set when the ladder decided
    how: str                     # "matched the open film" | "the one film with that title" | "by id" | "ambiguous" | "no-film"
    candidates: tuple[Candidate, ...] = ()   # AMBIGUOUS: the same-title films; NO-FILM: the nearest titles (≤ 5)

@dataclass(frozen=True)
class Outcome:
    kind: str        # "logged" | "added-to" | "ambiguous" | "no-film" | "refused" | "removed" | "open"
    line: str        # the one line the verb prints (no trailing newline; may hold "\n" for candidate lists)
    exit_code: int   # 0 | 2 | 3
    film_id: int | None = None
    viewing_id: int | None = None

def resolve_title(repo, title: str, *, year: int | None, now: datetime) -> Resolution
def log_viewing(repo, *, title: str | None, film_id: int | None, year: int | None, on: date | None, service: str | None, rate: int | None, text: str, today: date, now: datetime) -> Outcome
def remove(repo, viewing_id: int, note: int | None) -> Outcome
def listing(repo, since: date | None, film_id: int | None) -> str
def open_line(repo, now: datetime) -> str
```

- [ ] **Step 1: Write the feature file** (`tests/features/viewings.feature`)

```gherkin
Feature: Viewings — one dictation becomes one deterministic write against the right film

  Background:
    Given today is 2026-09-27
    And the registry knows "Kino Film Collection" and "Criterion Channel"
    And a film "The Blue Angel" (1930)
    And a film "Solaris" (1972) directed by "Andrei Tarkovsky"
    And a film "Solaris" (2002) directed by "Steven Soderbergh"
    And a film "Pandora’s Box" (1929)
    And a film "Godzilla vs. Gigan" (1972)
    And a film "Godzilla" (1954)
    And a merged-away twin "Godzilla" (1954)

  Scenario: The open film wins when it carries the dictated title
    Given the drawer reported "Solaris" (1972) 30 seconds ago
    When I log "Solaris" on "criterion" saying "tonight"
    Then the outcome is "logged" for "Solaris" (1972) matched "matched the open film"
    And the film "Solaris" (1972) has 1 viewing on 2026-09-27 with service "criterion"

  Scenario: A stale drawer report is ignored and the same title asks
    Given the drawer reported "Solaris" (1972) 200 seconds ago
    When I log "Solaris" saying "tonight"
    Then the outcome is "ambiguous" with exit 3 listing "Solaris (1972)" and "Solaris (2002)"
    And nothing was written

  Scenario: The open film is skipped when the dictation names another year
    Given the drawer reported "Solaris" (1972) 30 seconds ago
    When I log "Solaris" year 2002 saying "the remake"
    Then the outcome is "logged" for "Solaris" (2002) matched "the one film with that title"

  Scenario: Exactly one film with the title logs without a question
    When I log "The Blue Angel" on "kino-film-collection" rating 6 saying "about a six"
    Then the outcome is "logged" for "The Blue Angel" (1930) matched "the one film with that title"
    And the film "The Blue Angel" (1930) is rated 6

  Scenario: Apostrophes, case and accents do not matter
    When I log "pandora's box" saying "silent"
    Then the outcome is "logged" for "Pandora’s Box" (1929) matched "the one film with that title"

  Scenario: A merged-away twin is never a candidate
    When I log "Godzilla" saying "the original"
    Then the outcome is "logged" for "Godzilla" (1954) matched "the one film with that title"

  Scenario: A near-miss title lists the nearest films and writes nothing
    When I log "Blue Angel" saying "dropped the article"
    Then the outcome is "no-film" with exit 3 listing "The Blue Angel (1930)"
    And nothing was written

  Scenario: "versus" for "vs." still finds the film among the nearest
    When I log "Godzilla versus Gigan" saying "dictation writes versus"
    Then the outcome is "no-film" with exit 3 listing "Godzilla vs. Gigan (1972)"

  Scenario: A title of only stop words is no-film with no nearest list and no crash
    When I log "The" saying "nothing to go on"
    Then the outcome is "no-film" with exit 3 listing nothing

  Scenario: An unknown title with nothing close is no-film
    When I log "Mädchen in Uniform" saying "on a Blu-ray"
    Then the outcome is "no-film" with exit 3 listing nothing
    And nothing was written

  Scenario: A film id skips the ladder
    When I log film "Solaris" (2002) saying "by id"
    Then the outcome is "logged" for "Solaris" (2002) matched "by id"

  Scenario: A film id naming a merged-away or unknown film is refused
    When I log the merged twin of "Godzilla" (1954) saying "ghost"
    Then the outcome is "refused" with exit 2
    When I log film id 999999 saying "nobody"
    Then the outcome is "refused" with exit 2
    And nothing was written

  Scenario: The same film the same day appends a note and moves the rating
    When I log "The Blue Angel" on "kino-film-collection" rating 6 saying "first"
    And I log "The Blue Angel" on "criterion" rating 7 saying "second"
    Then the outcome is "added-to" with 2 notes
    And the film "The Blue Angel" (1930) has 1 viewing on 2026-09-27 with service "kino-film-collection"
    And the film "The Blue Angel" (1930) is rated 7

  Scenario: Another date is another viewing
    When I log "The Blue Angel" on 2026-09-21 saying "monday"
    And I log "The Blue Angel" saying "today"
    Then the film "The Blue Angel" (1930) has 2 viewings

  Scenario: Logging clears an Unseen mark and touches nothing else
    Given "Godzilla vs. Gigan" (1972) is marked unseen and on the watchlist
    When I log "Godzilla vs. Gigan" saying "watched it"
    Then "Godzilla vs. Gigan" (1972) is not unseen and is still on the watchlist

  Scenario Outline: Refusals write nothing
    When I log "The Blue Angel" <how>
    Then the outcome is "refused" with exit 2
    And nothing was written

    Examples:
      | how                                        |
      | on "criterion-channel" saying "bad slug"   |
      | on 2027-01-01 saying "future"              |
      | rating 11 saying "too high"                |
      | saying "   "                               |

  Scenario: Remove takes the whole viewing; remove a note takes one
    When I log "The Blue Angel" rating 6 saying "one"
    And I log "The Blue Angel" saying "two"
    And I log "The Blue Angel" saying "three"
    And I remove note 2 of the last viewing
    Then the outcome is "removed" with exit 0
    And the last viewing of "The Blue Angel" (1930) has notes "one" and "three"
    When I remove the last viewing
    Then the film "The Blue Angel" (1930) has 0 viewings
    And the film "The Blue Angel" (1930) is rated 6
    When I remove note 1 of viewing 999
    Then the outcome is "refused" with exit 2

  Scenario: The listing and the open line
    Given the drawer reported "Solaris" (1972) 30 seconds ago
    When I log "The Blue Angel" on 2026-09-21 on "kino-film-collection" rating 6 saying "monday"
    Then the listing since 2026-09-01 reads "2026-09-21" then "The Blue Angel (1930)" then "kino-film-collection" then "1 note" then "rated 6"
    And the open line names "Solaris" (1972)
    Given the drawer reported nothing
    Then the open line says nothing is open
```

- [ ] **Step 2: Write the step definitions** (`tests/step_defs/test_viewings.py`)

```python
"""The viewing log's application layer (brief 2.2): the ladder, the writes, the refusals. Assertions read the DATABASE."""

from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime, timedelta

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application import viewings as vw
from movie_brain.domain.models import Film

scenarios("../features/viewings.feature")

NOW = datetime(2026, 9, 27, 21, 0, 0)


@pytest.fixture
def ctx(repo):
    return {"repo": repo, "today": NOW.date(), "films": {}, "merged": {}, "out": None, "last_vid": None}


def _q(ctx, sql, *args):
    conn = sqlite3.connect(ctx["repo"].db_path)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def _snapshot(ctx):
    return (_q(ctx, "SELECT * FROM viewing"), _q(ctx, "SELECT * FROM artefact"), _q(ctx, "SELECT * FROM my_ratings"), _q(ctx, "SELECT * FROM unseen"))


@given(parsers.parse("today is {d}"))
def today_is(ctx, d):
    ctx["today"] = date.fromisoformat(d)
    ctx["before"] = _snapshot(ctx)


@given(parsers.parse('the registry knows "{a}" and "{b}"'))
def registry(ctx, a, b):
    ctx["repo"].register_provider(1899, a)
    ctx["repo"].register_provider(258, b)


@given(parsers.parse('a film "{title}" ({year:d})'))
def a_film(ctx, title, year):
    fid = ctx["repo"].create_film(Film(title, year, None, ""))
    assert fid is not None
    ctx["films"][(title, year)] = fid
    ctx["before"] = _snapshot(ctx)


@given(parsers.parse('a film "{title}" ({year:d}) directed by "{director}"'))
def a_film_directed(ctx, title, year, director):
    fid = ctx["repo"].create_film(Film(title, year, director, ""))
    assert fid is not None
    ctx["films"][(title, year)] = fid
    ctx["before"] = _snapshot(ctx)


@given(parsers.parse('a merged-away twin "{title}" ({year:d})'))
def merged_twin(ctx, title, year):
    # Created under a different key so create_film accepts it, then given the SAME displayed title
    # and merged away: a retired row that must never be a ladder candidate (finding 5).
    loser = ctx["repo"].create_film(Film(f"{title} twin {year}", year, None, "twin"))
    assert loser is not None
    conn = sqlite3.connect(ctx["repo"].db_path)
    conn.execute("UPDATE films SET title = ? WHERE id = ?", (title, loser))
    conn.commit(); conn.close()
    ctx["repo"].merge_film(loser, ctx["films"][(title, year)], ctx["today"])
    ctx["merged"][(title, year)] = loser
    ctx["before"] = _snapshot(ctx)


@given(parsers.parse('the drawer reported "{title}" ({year:d}) {secs:d} seconds ago'))
def drawer_reported(ctx, title, year, secs):
    ctx["repo"].set_drawer_film(ctx["films"][(title, year)], NOW - timedelta(seconds=secs))


@given("the drawer reported nothing")
def drawer_nothing(ctx):
    ctx["repo"].set_drawer_film(None, NOW)


@given(parsers.parse('"{title}" ({year:d}) is marked unseen and on the watchlist'))
def unseen_and_watchlisted(ctx, title, year):
    fid = ctx["films"][(title, year)]
    ctx["repo"].set_unseen(fid, True, ctx["today"])
    ctx["repo"].toggle_watchlist(fid, ctx["today"])
    ctx["before"] = _snapshot(ctx)


_HOW = re.compile(
    r'^(?:film "(?P<ftitle>[^"]+)" \((?P<fyear>\d{4})\)|film id (?P<fid>\d+)|the merged twin of "(?P<mtitle>[^"]+)" \((?P<myear>\d{4})\)|"(?P<title>[^"]+)")'
    r'(?: year (?P<year>\d{4}))?(?: on (?P<on>\d{4}-\d{2}-\d{2}))?(?: on "(?P<service>[^"]+)")?(?: rating (?P<rate>-?\d+))? saying "(?P<text>[^"]*)"$'
)


@when(parsers.re(r"I log (?P<rest>.+)"))
def i_log(ctx, rest):
    m = _HOW.match(rest.strip())
    assert m, rest
    g = m.groupdict()
    film_id = None
    if g["ftitle"]:
        film_id = ctx["films"][(g["ftitle"], int(g["fyear"]))]
    elif g["fid"]:
        film_id = int(g["fid"])
    elif g["mtitle"]:
        film_id = ctx["merged"][(g["mtitle"], int(g["myear"]))]
    ctx["out"] = vw.log_viewing(
        ctx["repo"], title=g["title"], film_id=film_id, year=int(g["year"]) if g["year"] else None,
        on=date.fromisoformat(g["on"]) if g["on"] else None, service=g["service"],
        rate=int(g["rate"]) if g["rate"] else None, text=g["text"], today=ctx["today"], now=NOW,
    )
    if ctx["out"].viewing_id is not None:
        ctx["last_vid"] = ctx["out"].viewing_id


@when(parsers.parse("I remove note {n:d} of the last viewing"))
def remove_note(ctx, n):
    ctx["out"] = vw.remove(ctx["repo"], ctx["last_vid"], n)


@when(parsers.parse("I remove note {n:d} of viewing {vid:d}"))
def remove_note_of(ctx, n, vid):
    ctx["out"] = vw.remove(ctx["repo"], vid, n)


@when("I remove the last viewing")
def remove_last(ctx):
    ctx["out"] = vw.remove(ctx["repo"], ctx["last_vid"], None)


@then(parsers.parse('the outcome is "{kind}" for "{title}" ({year:d}) matched "{how}"'))
def outcome_for(ctx, kind, title, year, how):
    o = ctx["out"]
    assert (o.kind, o.film_id, o.exit_code) == (kind, ctx["films"][(title, year)], 0), o
    assert how in o.line, o.line


@then(parsers.parse('the outcome is "{kind}" with exit {code:d} listing "{a}" and "{b}"'))
def outcome_listing_two(ctx, kind, code, a, b):
    o = ctx["out"]
    assert (o.kind, o.exit_code) == (kind, code), o
    assert a in o.line and b in o.line, o.line


@then(parsers.parse('the outcome is "{kind}" with exit {code:d} listing "{a}"'))
def outcome_listing_one(ctx, kind, code, a):
    o = ctx["out"]
    assert (o.kind, o.exit_code) == (kind, code) and a in o.line, o


@then(parsers.parse('the outcome is "{kind}" with exit {code:d} listing nothing'))
def outcome_listing_none(ctx, kind, code):
    o = ctx["out"]
    assert (o.kind, o.exit_code) == (kind, code) and "nearest" not in o.line and "#" not in o.line, o


@then(parsers.parse('the outcome is "{kind}" with exit {code:d}'))
def outcome_kind(ctx, kind, code):
    assert (ctx["out"].kind, ctx["out"].exit_code) == (kind, code), ctx["out"]


@then(parsers.parse('the outcome is "{kind}" with {n:d} notes'))
def outcome_notes(ctx, kind, n):
    assert ctx["out"].kind == kind and f"note {n}" in ctx["out"].line, ctx["out"]


@then("nothing was written")
def nothing_written(ctx):
    assert _snapshot(ctx) == ctx["before"]


@then(parsers.parse('the film "{title}" ({year:d}) has {n:d} viewing on {d} with service "{slug}"'))
def has_one_viewing(ctx, title, year, n, d, slug):
    rows = _q(ctx, "SELECT watched_on, service FROM viewing WHERE film_id = ?", ctx["films"][(title, year)])
    assert rows == [(d, slug)] and n == 1, rows


@then(parsers.parse('the film "{title}" ({year:d}) has {n:d} viewings'))
def has_n_viewings(ctx, title, year, n):
    assert _q(ctx, "SELECT COUNT(*) FROM viewing WHERE film_id = ?", ctx["films"][(title, year)])[0][0] == n


@then(parsers.parse('the film "{title}" ({year:d}) is rated {score:d}'))
def is_rated(ctx, title, year, score):
    assert _q(ctx, "SELECT score FROM my_ratings WHERE film_id = ?", ctx["films"][(title, year)]) == [(score,)]


@then(parsers.parse('"{title}" ({year:d}) is not unseen and is still on the watchlist'))
def unseen_cleared(ctx, title, year):
    fid = ctx["films"][(title, year)]
    assert _q(ctx, "SELECT 1 FROM unseen WHERE film_id = ?", fid) == []
    assert _q(ctx, "SELECT 1 FROM watchlist WHERE film_id = ?", fid) == [(1,)]


@then(parsers.parse('the last viewing of "{title}" ({year:d}) has notes "{a}" and "{b}"'))
def last_viewing_notes(ctx, title, year, a, b):
    vs = ctx["repo"].viewings_for(ctx["films"][(title, year)])
    assert [x["text"] for x in vs[0]["artefacts"]] == [a, b]


@then(parsers.parse('the listing since {d} reads "{a}" then "{b}" then "{c}" then "{e}" then "{f}"'))
def listing_reads(ctx, d, a, b, c, e, f):
    text = vw.listing(ctx["repo"], date.fromisoformat(d), None)
    assert re.search(re.escape(a) + r".*" + re.escape(b) + r".*" + re.escape(c) + r".*" + re.escape(e) + r".*" + re.escape(f), text), text


@then(parsers.parse('the open line names "{title}" ({year:d})'))
def open_names(ctx, title, year):
    assert f"#{ctx['films'][(title, year)]} '{title}' ({year})" in vw.open_line(ctx["repo"], NOW)


@then("the open line says nothing is open")
def open_nothing(ctx):
    assert vw.open_line(ctx["repo"], NOW).startswith("OPEN      nothing")
```

- [ ] **Step 3: Run to verify it fails**

Run: `uv run pytest tests/step_defs/test_viewings.py -q`
Expected: FAIL — `ModuleNotFoundError: movie_brain.application.viewings`.

- [ ] **Step 4: Implement `application/viewings.py`**

```python
"""The viewing log's use cases (brief docs/superpowers/briefs/2026-09-21-viewing-log/brief-2.md).

One dictation → one deterministic write. The title ladder is HERE, not in the agent's prompt:
rung 1 the film the dashboard has open (a fresh drawer report) when its normalised title equals
the dictated one; rung 2 exactly one canonical film with that normalised title; rung 3 stop —
AMBIGUOUS with the same-title films, or NO-FILM with the nearest titles — and write nothing.
One normaliser on both sides at query time (domain/thumbprint.py::title_norm); the films.title_norm
column is never read. No SQL, no HTTP.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from movie_brain.domain.thumbprint import title_norm
from movie_brain.infrastructure.database import Repository

STOP_WORDS = frozenset({"the", "a", "an", "of", "and", "vs", "versus"})
NEAREST = 5
_WORD = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class Candidate:
    film_id: int
    title: str
    year: int | None
    director: str | None
    best_source: str | None

    def line(self) -> str:
        parts = [f"#{self.film_id}", f"{self.title} ({self.year or '-'})", self.director or "—"]
        if self.best_source:
            parts.append(self.best_source)
        return "  " + "  ".join(parts)


@dataclass(frozen=True)
class Resolution:
    film_id: int | None
    how: str
    candidates: tuple[Candidate, ...] = ()


@dataclass(frozen=True)
class Outcome:
    kind: str
    line: str
    exit_code: int
    film_id: int | None = None
    viewing_id: int | None = None


def _words(title: str) -> list[str]:
    return [w for w in _WORD.findall(title_norm_words(title)) if w not in STOP_WORDS]


def title_norm_words(title: str) -> str:
    """Lower-cased, accent-folded, apostrophes dropped, but WORDS KEPT APART (title_norm joins them)."""
    import unicodedata

    t = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    return t.replace("'", "").replace("’", "")


def _candidate(repo: Repository, film_id: int, title: str, year: int | None, director: str | None, today: date) -> Candidate:
    view = repo.get_view(film_id, today)
    best = view.best_source["name"] if view is not None and view.best_source else None
    return Candidate(film_id, title, year, director, best)


def resolve_title(repo: Repository, title: str, *, year: int | None, now: datetime, today: date | None = None) -> Resolution:
    today = today or now.date()
    wanted = title_norm(title)
    rows = repo.canonical_titles()
    by_id = {r[0]: r for r in rows}
    open_id = repo.drawer_film(now)
    if open_id in by_id and wanted:
        _, t, y, _d = by_id[open_id]
        if title_norm(t) == wanted and (year is None or y == year):
            return Resolution(open_id, "matched the open film")
    hits = [r for r in rows if wanted and title_norm(r[1]) == wanted and (year is None or r[2] == year)]
    if len(hits) == 1:
        return Resolution(hits[0][0], "the one film with that title")
    if len(hits) > 1:
        return Resolution(None, "ambiguous", tuple(_candidate(repo, *r, today) for r in hits))
    near: list[tuple[int, str, int | None, str | None]] = []
    words = _words(title)
    if words:
        ids = repo.title_hits(" ".join(words))
        near = [r for r in rows if r[0] in ids and (year is None or r[2] == year)]
    if not near and wanted:
        near = [r for r in rows if title_norm(r[1]) and (wanted in title_norm(r[1]) or title_norm(r[1]) in wanted)]
    near = sorted(near, key=lambda r: (r[2] or 0, r[0]))[:NEAREST]
    return Resolution(None, "no-film", tuple(_candidate(repo, *r, today) for r in near))


def _refused(reason: str) -> Outcome:
    return Outcome("refused", f"REFUSED   {reason} — nothing written", 2)


def log_viewing(
    repo: Repository, *, title: str | None, film_id: int | None, year: int | None, on: date | None,
    service: str | None, rate: int | None, text: str, today: date, now: datetime,
) -> Outcome:
    if not text or not text.strip():
        return _refused("the dictation is empty")
    on = on or today
    if on > today:
        return _refused(f"{on.isoformat()} is in the future")
    if rate is not None and (isinstance(rate, bool) or not isinstance(rate, int) or not 0 <= rate <= 10):
        return _refused("a rating is a whole number 0–10")
    service_name = None
    if service is not None:
        service_name = repo.service_name(service)
        if service_name is None:
            return _refused(f"no service '{service}' in the registry (movie-brain services list)")
    canonical = {r[0]: r for r in repo.canonical_titles()}
    if film_id is not None:
        if film_id not in canonical:
            return _refused(f"no film #{film_id} (merged away, tombstoned or unknown)")
        res = Resolution(film_id, "by id")
    else:
        if not title or not title.strip():
            return _refused("say a title or a film id")
        res = resolve_title(repo, title, year=year, now=now, today=today)
    if res.film_id is None:
        if res.how == "ambiguous":
            body = "\n".join(c.line() for c in res.candidates)
            return Outcome("ambiguous", f"AMBIGUOUS {len(res.candidates)} films titled '{title}' — nothing written\n{body}\n  say which: --film ID or --year YYYY", 3)
        if res.candidates:
            body = " · ".join(f"#{c.film_id} {c.title} ({c.year or '-'})" for c in res.candidates)
            return Outcome("no-film", f"NO-FILM   no film titled '{title}' — nothing written\n  nearest: {body}\n  say --film ID if one of these is it; otherwise films add ttNNN mints a new film", 3)
        return Outcome("no-film", f"NO-FILM   no film titled '{title}' — nothing written\n  nothing close by title either; films add ttNNN mints a new film", 3)
    fid, (_, ftitle, fyear, _d) = res.film_id, canonical[res.film_id]
    w = repo.add_viewing(fid, on, service, text.strip(), rate, today)
    rated = f" · rated {rate}" if rate is not None else ""
    if w.created:
        svc = f" · {service}" if service else ""
        return Outcome("logged", f"LOGGED    #{fid} '{ftitle}' ({fyear or '-'}) · {on.isoformat()}{svc} · viewing #{w.viewing_id} · {res.how}{rated}", 0, fid, w.viewing_id)
    return Outcome("added-to", f"ADDED-TO  viewing #{w.viewing_id} (#{fid} '{ftitle}', {on.isoformat()}) · note {w.note_count}{rated}", 0, fid, w.viewing_id)


def remove(repo: Repository, viewing_id: int, note: int | None) -> Outcome:
    if note is None:
        gone = repo.remove_viewing(viewing_id)
        if gone is None:
            return _refused(f"no viewing #{viewing_id}")
        n = int(gone["notes"])
        return Outcome("removed", f"REMOVED   viewing #{viewing_id} (#{gone['film_id']}, {gone['watched_on']}) and its {n} note{'' if n == 1 else 's'} · rating and Unseen untouched", 0, int(gone["film_id"]), viewing_id)
    gone = repo.remove_artefact(viewing_id, note)
    if gone is None:
        return _refused(f"viewing #{viewing_id} has no note {note}")
    left = int(gone["notes_left"])
    return Outcome("removed", f"REMOVED   note {note} of viewing #{viewing_id} (#{gone['film_id']}, {gone['watched_on']}) · {left} note{'' if left == 1 else 's'} left · the viewing, the rating and Unseen untouched", 0, int(gone["film_id"]), viewing_id)


def listing(repo: Repository, since: date | None, film_id: int | None) -> str:
    rows = repo.list_viewings(since=since, film_id=film_id)
    if not rows:
        return f"no viewing{' since ' + since.isoformat() if since else ''}"
    out = []
    for r in rows:
        n = int(r["notes"])
        svc = f"  {r['service']}" if r["service"] else ""
        rated = f"  rated {r['my_rating']}" if r["my_rating"] is not None else ""
        out.append(f"{r['watched_on']}  #{str(r['film_id']).ljust(5)} {r['title']} ({r['year'] or '-'}){svc}  {n} note{'' if n == 1 else 's'}{rated}")
    return "\n".join(out)


def open_line(repo: Repository, now: datetime) -> str:
    fid = repo.drawer_film(now)
    if fid is None:
        return "OPEN      nothing — no drawer has reported in for two minutes (closed, or the dashboard is not running)"
    view = repo.get_view(fid, now.date())
    if view is None:
        return "OPEN      nothing — the reported film is not a film the dashboard can show"
    return f"OPEN      #{fid} '{view.title}' ({view.year or '-'})"
```

Note for the implementer: `_words` must fold accents and drop apostrophes but keep word boundaries, which `title_norm` (it joins words) cannot give — hence `title_norm_words`. `title_hits` runs `fts_words` over the joined words itself.

- [ ] **Step 5: Run the feature**

Run: `uv run pytest tests/step_defs/test_viewings.py -q`
Expected: PASS (22 scenarios incl. the outline's four rows). If "versus" fails, check that `title_hits("godzilla gigan")` reaches the film through `film_text_fts` OR the `films.title LIKE` branch for films with no `film_text` row — the test films have no `film_text` row, so the LIKE branch (`%godzilla gigan%`) will NOT match `Godzilla vs. Gigan`; if so, add to `resolve_title`'s nearest step a word-wise fallback: `[r for r in rows if all(w in _words(r[1]) for w in words)]` before the substring fallback. Keep whichever makes the scenario pass and leave a one-line comment naming the reason.

- [ ] **Step 6: Commit**

```bash
git add src/movie_brain/application/viewings.py tests/features/viewings.feature tests/step_defs/test_viewings.py
git commit -m "Viewing log: the title ladder lives in the verb — open film, one match, else ask; refusals write nothing; nearest titles on a near miss

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: The `viewings` CLI app — add / remove / list / open

**Files:**
- Modify: `src/movie_brain/cli.py` (a `viewings_app = typer.Typer(...)` beside `films_app` at line ~86; commands after `films_add_cmd` at line 640)
- Test: `tests/unit/test_cli.py` (append)

**Interfaces:**
- Consumes: `application.viewings.log_viewing / remove / listing / open_line`, `_repo()`, `console`, `err`.
- Produces the verbs the skill and the brief name:
  - `movie-brain viewings add (--title T [--year Y] | --film ID) [--on YYYY-MM-DD] [--service SLUG] [--rate N] [--text -|FILE]` (default `--text -` reads stdin)
  - `movie-brain viewings remove VID [--note N]`
  - `movie-brain viewings list [--since YYYY-MM-DD] [--film ID]`
  - `movie-brain viewings open`

- [ ] **Step 1: Failing CLI tests** (append to `tests/unit/test_cli.py`; the `repo` fixture and the CLI share `MOVIE_BRAIN_CONFIG_DIR`, so a seeded `repo` is what `_repo()` opens)

```python
from datetime import date as _date
from movie_brain.domain.models import Film as _Film


def test_viewings_add_reads_the_dictation_from_stdin_and_prints_one_line(repo):
    fid = repo.create_film(_Film("The Blue Angel", 1930, None, ""))
    repo.register_provider(1899, "Kino Film Collection")
    r = runner.invoke(app, ["viewings", "add", "--title", "The Blue Angel", "--service", "kino-film-collection", "--rate", "6", "--text", "-"], input="about a six\n")
    assert r.exit_code == 0, r.output
    assert r.output.startswith(f"LOGGED    #{fid} 'The Blue Angel' (1930)") and "rated 6" in r.output
    assert repo.viewings_for(fid)[0]["artefacts"][0]["text"] == "about a six"


def test_viewings_add_refuses_a_bad_date_and_an_unknown_slug_with_exit_2(repo):
    repo.create_film(_Film("The Blue Angel", 1930, None, ""))
    r = runner.invoke(app, ["viewings", "add", "--title", "The Blue Angel", "--on", "2099-01-01", "--text", "-"], input="x")
    assert r.exit_code == 2 and "REFUSED" in r.output
    r = runner.invoke(app, ["viewings", "add", "--title", "The Blue Angel", "--on", "not-a-date", "--text", "-"], input="x")
    assert r.exit_code == 2
    r = runner.invoke(app, ["viewings", "add", "--title", "The Blue Angel", "--service", "criterion-channel", "--text", "-"], input="x")
    assert r.exit_code == 2 and "criterion-channel" in r.output


def test_viewings_add_ambiguous_exits_3_and_lists_the_films(repo):
    a = repo.create_film(_Film("Solaris", 1972, "Andrei Tarkovsky", ""))
    b = repo.create_film(_Film("Solaris", 2002, "Steven Soderbergh", ""))
    r = runner.invoke(app, ["viewings", "add", "--title", "Solaris", "--text", "-"], input="tonight")
    assert r.exit_code == 3 and f"#{a}" in r.output and f"#{b}" in r.output and "AMBIGUOUS" in r.output


def test_viewings_remove_list_and_open(repo):
    fid = repo.create_film(_Film("Dragon Inn", 1967, "King Hu", ""))
    runner.invoke(app, ["viewings", "add", "--film", str(fid), "--on", "2026-09-24", "--text", "-"], input="thursday")
    r = runner.invoke(app, ["viewings", "list", "--since", "2026-09-01"])
    assert r.exit_code == 0 and "Dragon Inn (1967)" in r.output and "1 note" in r.output
    r = runner.invoke(app, ["viewings", "open"])
    assert r.exit_code == 0 and r.output.startswith("OPEN      nothing")
    vid = repo.viewings_for(fid)[0]["id"]
    r = runner.invoke(app, ["viewings", "remove", str(vid), "--note", "1"])
    assert r.exit_code == 0 and "REMOVED   note 1" in r.output
    r = runner.invoke(app, ["viewings", "remove", str(vid)])
    assert r.exit_code == 0 and r.output.startswith("REMOVED   viewing")
    r = runner.invoke(app, ["viewings", "remove", str(vid)])
    assert r.exit_code == 2
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_cli.py -q -k viewings`
Expected: FAIL — `No such command 'viewings'` (exit 2 from typer with usage text; the LOGGED assertion fails).

- [ ] **Step 3: Implement the app** (beside `films_app`, then the commands after `films_add_cmd`)

```python
viewings_app = typer.Typer(help="The viewing log: one dictation → one dated viewing against a film (the skill log-viewing drives it).")
app.add_typer(viewings_app, name="viewings")
```

```python
def _parse_day(raw: str | None, flag: str) -> date | None:
    if raw is None:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        err.print(f"REFUSED   {flag} wants YYYY-MM-DD, not {raw!r} — nothing written")
        raise typer.Exit(2) from exc


@viewings_app.command("add")
def viewings_add_cmd(
    title: Annotated[str | None, typer.Option("--title", help="The title as dictated; the verb runs the ladder.")] = None,
    film: Annotated[int | None, typer.Option("--film", help="A film id, once one is confirmed — skips the ladder.")] = None,
    year: Annotated[int | None, typer.Option("--year", help="Narrows the title to one year (skips the open-film rung when it differs).")] = None,
    on: Annotated[str | None, typer.Option("--on", help="The viewing's date, YYYY-MM-DD (default today).")] = None,
    service: Annotated[str | None, typer.Option("--service", help="A registry slug (movie-brain services list); omit for a disc or a cinema.")] = None,
    rate: Annotated[int | None, typer.Option("--rate", help="The 0–10 the dictation states, if it states one.")] = None,
    text: Annotated[str, typer.Option("--text", help="The dictation: '-' reads standard input, else a file path.")] = "-",
) -> None:
    """Log ONE viewing from a dictation. Writes a viewing, a note, the rating (if said) and clears
    Unseen in one transaction; refuses and writes nothing otherwise (exit 2), or stops to ask
    (exit 3: AMBIGUOUS / NO-FILM)."""
    from movie_brain.application import viewings as vw
    import sys

    body = sys.stdin.read() if text == "-" else Path(text).read_text(encoding="utf-8")
    out = vw.log_viewing(
        _repo(), title=title, film_id=film, year=year, on=_parse_day(on, "--on"), service=service,
        rate=rate, text=body, today=date.today(), now=datetime.now(),
    )
    console.print(out.line, markup=False, highlight=False, soft_wrap=True)
    raise typer.Exit(out.exit_code)


@viewings_app.command("remove")
def viewings_remove_cmd(
    viewing_id: Annotated[int, typer.Argument(help="The viewing number the add printed.")],
    note: Annotated[int | None, typer.Option("--note", help="Remove only this note (1-based) and keep the viewing.")] = None,
) -> None:
    """Remove a viewing and its notes, or one note. The rating and the Unseen mark are untouched."""
    from movie_brain.application import viewings as vw

    out = vw.remove(_repo(), viewing_id, note)
    console.print(out.line, markup=False, highlight=False, soft_wrap=True)
    raise typer.Exit(out.exit_code)


@viewings_app.command("list")
def viewings_list_cmd(
    since: Annotated[str | None, typer.Option("--since", help="Only viewings on or after this date.")] = None,
    film: Annotated[int | None, typer.Option("--film", help="Only this film's viewings.")] = None,
) -> None:
    """Every logged viewing, newest first: date, film, service, notes, rating."""
    from movie_brain.application import viewings as vw

    console.print(vw.listing(_repo(), _parse_day(since, "--since"), film), markup=False, highlight=False, soft_wrap=True)


@viewings_app.command("open")
def viewings_open_cmd() -> None:
    """The film the dashboard has open in its drawer, if it reported in during the last two minutes."""
    from movie_brain.application import viewings as vw

    console.print(vw.open_line(_repo(), datetime.now()), markup=False, highlight=False, soft_wrap=True)
```

Add `from datetime import date, datetime` at the top of `cli.py` (it imports `date` today).

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_cli.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/cli.py tests/unit/test_cli.py
git commit -m "Viewing log: the viewings verbs — add reads the dictation on stdin and prints one line; remove, list, open

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: The dashboard — Watched block, Watched chip, Watched column, drawer heartbeat, focus refresh

**Files:**
- Modify: `src/movie_brain/web/templates/index.html:30-35` (chip after Shop), `:44-72` (colgroup, labels row, filters row)
- Modify: `src/movie_brain/web/static/app.js` — `COLS` (line 7), `CHIP_PREDICATES` (line 49), `compare` (line 93, the chip-on default sort), `rowHtml` (line 175, the new cell), `renderRows` empty states, `detailHtml` ratings block (lines 674–706: the `oldLine` becomes the Watched block), `openDrawer` / `hideDrawer` (heartbeat), a new focus handler near `boot`
- Modify: `src/movie_brain/web/static/app.css` (the block's styles, `col.col-watched`)
- Test: `tests/web/test_dashboard.py::test_chip_labels_and_order` (append `"Watched"` before `"Clear"`), `tests/web/test_viewing_log.py` (new, own server)

**Interfaces:**
- Consumes: list payload `last_watched`, `viewing_count`; detail payload `viewings`, `old_ratings`; `PUT /api/drawer`.
- Produces: chip `button.chip[data-chip="watched"]` labelled `Watched`; column `th.sortable[data-col="last_watched"]` labelled `Watched`, cell `td.c-watched`; drawer block `#drawer .ratings .watched` with `ul.viewings > li.viewing` and `li.rental`, `details.note`; heartbeat every 30 s; focus refresh.

- [ ] **Step 1: Write the failing web tests** (`tests/web/test_viewing_log.py`; the server pattern is `tests/web/test_shop_chip.py`'s `shop_server`)

```python
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
```

Also edit `tests/web/test_dashboard.py::test_chip_labels_and_order` so the expected list is `["Reachable", "Rated", "Criterion", "Watchlist", "Owned", "On a list", "Rewatch", "Shop", "Watched", "Clear"]`.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/web/test_viewing_log.py tests/web/test_dashboard.py -q -k "viewing or chip_labels"`
Expected: FAIL — no Watched chip, no `.watched` block.

- [ ] **Step 3: Implement — `index.html`**

Chip row, after the Shop button:

```html
      <button class="chip" data-chip="watched" title="Films with a logged viewing, most recent first">Watched</button>
```

Colgroup: insert `<col class="col-watched">` between `col-rating` and `col-info`. Labels row: insert `<th class="sortable" data-col="last_watched">Watched</th>` between My Rating and the empty `<th>`. Filters row: insert one more empty `<th></th>` at the same position (the row must keep one cell per column).

- [ ] **Step 4: Implement — `app.js`**

`COLS`: `['title', 'year', 'director', 'language', 'metacritic', 'rt', 'imdb', 'my_rating', 'last_watched']`.

`CHIP_PREDICATES`: add `watched: (f) => (f.viewing_count || 0) > 0,` after `shop` (mirror of `filters.py`).

`compare`, inside the `!state.sort` branch after the `multi_list` block:

```js
      if (state.chips.has('watched')) {  // Watched on: last viewing desc leads (the On-a-list precedent)
        const la = a.last_watched || '', lb = b.last_watched || '';
        if (la !== lb) return lb.localeCompare(la);
      }
```

The column sort already puts `null` last in both directions (the `va == null || vb == null` line) and compares strings, so ISO dates sort correctly with no further change.

`rowHtml`: insert before the `c-info` cell: `` <td class="c-watched">${f.last_watched ? esc(f.last_watched) : ''}</td> `` and raise every `colspan="9"` in `renderRows` to `10`. In the empty-result branch of `renderRows` / `applyFilters` (find where a filtered-empty table is drawn; if today it draws nothing, add a row): when `state.filtered.length === 0` draw `<tr class="empty-state"><td colspan="10">${state.chips.has('watched') && !state.films.some((f) => f.viewing_count > 0) ? 'No viewing logged yet.' : 'No film matches.'}</td></tr>`.

`detailHtml` — replace `oldLine` with the Watched block:

```js
    const notesHtml = (v) => {
      const arts = v.artefacts || [];
      if (!arts.length) return '';
      const first = arts[0].text.replace(/\s+/g, ' ').slice(0, 42).trim();
      const more = arts.length > 1 ? ` (${arts.length} notes)` : '';
      return `<details class="note"><summary>"${esc(first)}…"${more}</summary>${arts.map((a) => `<span class="txt">${esc(a.text)}</span>`).join('')}</details>`;
    };
    const viewingLines = (d.viewings || []).map((v) => `<li class="viewing">${esc(v.watched_on)}${v.service_name ? ` <span class="sep">·</span> ${esc(v.service_name)}` : ''} <span class="sep">·</span> ${notesHtml(v)}</li>`);
    const rentalLines = (d.old_ratings || []).map((o) => `<li class="rental">${esc(o.rented_on || '—')} <span class="sep">·</span> rented <span class="sep">·</span> <span class="old-stars" aria-label="${o.stars} of 5 stars">${'★'.repeat(o.stars)}${'☆'.repeat(5 - o.stars)}</span></li>`);
    const lines = viewingLines.concat(rentalLines);
    const watchedBlock = `<div class="row watched"><span class="lbl">Watched:</span> ${lines.length ? `<ul class="viewings">${lines.join('')}</ul>` : '<span class="none">Never logged.</span>'}</div>`;
```

and in the returned template replace `${oldLine}` with `${watchedBlock}` (delete `oldLine` and `OLD_SPAN`'s use there only; `oldBadge` on the row keeps using `OLD_SPAN`).

Heartbeat — add near `openDrawer`:

```js
  // The open-film report (viewing-log brief 2.2): the verb `viewings add` reads which film the
  // drawer shows, trusting a report under two minutes old; so report on open, on close, and
  // every 30 s while open. Fire-and-forget: a failed report only means the ladder starts at rung 2.
  let heartbeat = null;
  function reportDrawer(id) {
    fetch('/api/drawer', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ film_id: id }) }).catch(() => {});
  }
  function startHeartbeat(id) {
    stopHeartbeat(); reportDrawer(id);
    heartbeat = setInterval(() => reportDrawer(id), 30000);
  }
  function stopHeartbeat() {
    if (heartbeat) { clearInterval(heartbeat); heartbeat = null; }
  }
```

In `openDrawer`, right after `state.openFilm = id; state.mark = id; drawnFilm = id;` add `startHeartbeat(id);`. In `hideDrawer`, first line: `stopHeartbeat(); reportDrawer(null);`.

Focus refresh — add before `boot()`:

```js
  // After a dictation writes (out of the page's sight), the drawer he alt-tabs back to must be
  // current: re-read the open film on focus / visibility and patch its row. Other rows and the
  // Watched chip catch up on the next reload or drawer open (brief 2.2, "the page refreshes on focus").
  async function refreshOpenFilm() {
    if (drawer.hidden || state.openFilm == null) return;
    const id = state.openFilm, seq = ++drawerSeq;
    const r = await fetch(`/api/films/${id}`).catch(() => null);
    if (!r || !r.ok || seq !== drawerSeq || state.openFilm !== id) return;
    const d = await r.json();
    const i = state.films.findIndex((f) => f.id === id);
    if (i >= 0) state.films[i] = { ...state.films[i], my_rating: d.my_rating, unseen: d.unseen, last_watched: d.last_watched, viewing_count: d.viewing_count, watchlisted: d.watchlisted };
    body.innerHTML = detailHtml(d); drawnDetail = d;
    renderCounts(); applyFilters();
  }
  window.addEventListener('focus', refreshOpenFilm);
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') refreshOpenFilm(); });
```

Check that `drawerSeq++` here does not fight `openDrawer`'s own sequencing: `openDrawer` increments and compares `seq !== drawerSeq` after its fetch; the refresh does the same, so whichever finishes second and was superseded gives way. If `applyFilters()` re-renders while the drawer is open, the drawer stays (it does today when `commitRating` calls `updateFilmLocal`).

- [ ] **Step 5: Implement — `app.css`** (after line 129)

```css
col.col-watched { width:104px; }
#drawer .ratings .watched .lbl { color:var(--muted); }
#drawer .ratings .watched ul.viewings { list-style:none; margin:2px 0 0; padding:0; }
#drawer .ratings .watched ul.viewings li { margin:3px 0; }
#drawer .ratings .watched ul.viewings li.rental { color:var(--muted); }
#drawer .ratings .watched details.note { display:inline; }
#drawer .ratings .watched details.note summary { display:inline; cursor:pointer; color:#0000ee; }
#drawer .ratings .watched details.note[open] summary { display:none; }
#drawer .ratings .watched .txt { display:block; margin:4px 0 6px 14px; padding-left:8px; border-left:2px solid var(--line); white-space:pre-wrap; color:#333; }
#drawer .ratings .watched .sep { color:#c0c0c0; }
#drawer .ratings .watched .none { color:var(--muted); }
```

- [ ] **Step 6: Run the web tests**

Run: `uv run pytest tests/web -q`
Expected: PASS, including `test_chip_labels_and_order`, the find-my-row and move-on suites (the extra column changes no row height; if a find-my-row test pins `colspan` or a cell count, update the count to 10).

- [ ] **Step 7: Commit**

```bash
git add src/movie_brain/web/templates/index.html src/movie_brain/web/static/app.js src/movie_brain/web/static/app.css tests/web/test_viewing_log.py tests/web/test_dashboard.py
git commit -m "Viewing log on the dashboard: a read-only Watched block in the drawer, the Watched chip and column, the drawer's 30 s open-film report, and a focus refresh so a dictation shows without a reload

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: The skill and the docs

**Files:**
- Create: `.claude/skills/log-viewing/SKILL.md`
- Create: `.claude/rules/viewings.md`
- Modify: `CLAUDE.md` (Commands block: four lines after the `films add` line; the Rules paragraph names `viewings.md`), `.claude/rules/dashboard.md` (one bullet at the end)
- Modify: `docs/superpowers/briefs/2026-09-21-viewing-log/trial-log.md` (a "Built" line under Round 2)

**Interfaces:** none new; the skill names the verbs of Task 5 exactly.

- [ ] **Step 1: Write the skill** (`.claude/skills/log-viewing/SKILL.md`)

```markdown
---
name: log-viewing
description: Use when the owner says he watched a film ("I just watched…", "watched X last night", "log a viewing", "one more thing about X") — turn the dictation into ONE `movie-brain viewings add` command; never invent a date or a number; ask on AMBIGUOUS / NO-FILM.
---

# Log a viewing from a dictation

The owner dictates in this session; you run `movie-brain viewings add` and show its one line back. The verb runs the title ladder (open drawer → one match → ask), not you. Brief: `docs/superpowers/briefs/2026-09-21-viewing-log/brief-2.md`.

## Extract, from his words

- **Title**, verbatim, one film per command (a double bill is two commands, each with its own words). Pass `--year` only when HE names a year; a director he names is used to answer an AMBIGUOUS list, never to pre-empt it.
- **Date**: today unless he says otherwise; resolve relative words against today ("last Monday", "yesterday", "about last night" → `--on YYYY-MM-DD`). Never invent one.
- **Service** → a registry slug (`movie-brain services list`), mapped THROUGH THE FILM: "Apple TV" for a film he owns is `apple-tv-store`, for one streaming on Apple TV+ it is `apple-tv-plus`; "Max"/"HBO" is `max` when the film lists it; "Criterion" is `criterion`; "Kino" is `kino-film-collection`. Two slugs fit, or none → ask before running. A disc or a cinema → no `--service`.
- **Rating** → `--rate N` only when he offers ONE whole number 0–10 AS a rating, however hedged ("about a six", "a strong seven", "rate it ten"). Two candidates or a fraction ("a 9 or a 10", "seven and a half") → ask. A tier, a year, a count is not a rating. No number → no `--rate`.
- **The text** → everything he said about the film, whole, on stdin (`--text -` with a heredoc). Do not summarise it.
- **A presentation remark** (restoration, transfer quality) → also append a row to `observations/presentation.tsv` (columns `watched_on film_id title year service verdict note`), by hand, as that file is kept today.

## Run

    movie-brain viewings add --title "<title>" [--year Y] [--on YYYY-MM-DD] [--service slug] [--rate N] --text - <<'EOF'
    <his words>
    EOF

Show the verb's one line back and nothing more. Exit 0 = written. Then:

- **`AMBIGUOUS` (exit 3)**: show the candidates it printed; ask which; rerun with `--film ID`.
- **`NO-FILM` (exit 3) with a `nearest:` list**: ask "this one?" for the first; rerun with `--film ID` on yes.
- **`NO-FILM` with nothing close**: propose the IMDb id you believe it is and run `movie-brain films add ttNNN` DRY; show TMDB's title and year; run `--apply` ONLY on his yes (it enriches, then you log with `--film <new id>`). `HELD` means the catalogue has it: log against the named holder. Exit 2 for missing keys: tell him, create nothing.
- **`REFUSED` (exit 2)**: read the reason back and fix the flag; nothing was written.

## Never

- Never write a tier or a rank ("put it in tier 2" → the drawer's Tier row / Rank this; say so). Never write the watchlist (the drawer's ★ is its only writer). Never run `films add --apply` or `migrate --apply` without his yes. Never log a rating without a viewing to hang it on: no title and no open film → ask which film.
- A second sentence about the same film the same day is another `viewings add`: the verb appends the note (`ADDED-TO`). "Scratch that last remark" → `movie-brain viewings remove VID --note N`; the whole evening → `viewings remove VID`.
- "What did I watch this month?" → `movie-brain viewings list --since YYYY-MM-01`. "What's open?" → `movie-brain viewings open`.
```

- [ ] **Step 2: Write the rule** (`.claude/rules/viewings.md`, frontmatter like `cheapcharts.md`)

```markdown
---
paths:
  - src/movie_brain/application/viewings.py
  - migrations/031_viewing.sql
  - .claude/skills/log-viewing/SKILL.md
---
# Viewing log contract (brief `docs/superpowers/briefs/2026-09-21-viewing-log/brief-2.md` v2.2, migration 031, built 2026-09-27)

- A viewing is a dated EVENT against a film (`viewing`: film, `watched_on`, optional registry `service`, `logged_on`; `UNIQUE(film_id, watched_on)`); an `artefact` is what he said about it (kind `dictation` only in v1; the CHECK widens by a later migration). The 0–10 stays in `my_ratings`, written through `rate_film`; nothing on the viewing is a rating.
- `movie-brain viewings add` is the ONLY writer; sync, `enrich` and every import verb never touch these tables; the dashboard reads them (detail-only `viewings`, `old_ratings`; `last_watched` + `viewing_count` on the list payload) and never writes them. The drawer's log has no buttons.
- The title ladder lives in `application/viewings.py::resolve_title`, never in a prompt: rung 1 the film the dashboard reports open (`meta.drawer_film`, a 30 s heartbeat trusted 120 s — `Repository.drawer_film`) when its normalised title equals the dictated one; rung 2 exactly one canonical film (no `film_disposition` row) with that normalised title; rung 3 stop (AMBIGUOUS lists the films, NO-FILM lists the nearest titles via `title_hits` over the words minus articles and vs/versus, then a normalised substring) and write nothing, exit 3. One normaliser, both sides, at query time: `domain/thumbprint.py::title_norm`; the `films.title_norm` column is NEVER read (empty for every film created since the backfill).
- One viewing per film per day; a second add appends an artefact (`ADDED-TO`), moves the rating if given, sets the service only if the line had none — never overwrites one. Refusals (`REFUSED`, exit 2: future date, blank text, unknown slug, rating outside 0–10, unknown viewing/note, non-canonical `--film`) happen before the one transaction and write nothing. Logging clears `unseen` (via `set_unseen(False)`, nothing else moves); removing restores nothing.
- `merge_film` re-points `viewing.film_id`; a same-date collision moves the loser's artefacts onto the survivor's viewing. A viewed film is always visible in `list_views` (current-or-rated-or-viewed).
- The agent's side is `.claude/skills/log-viewing/SKILL.md`: extraction rules (one film per command; date never invented; service mapped through the film; a rating only when ONE whole number is offered as a rating), and what to do on each exit code. `films add --apply` always waits for the owner's yes.
```

- [ ] **Step 3: `CLAUDE.md`** — after the `films add` command line add:

```bash
uv run movie-brain viewings add (--title T [--year Y] | --film ID) [--on DATE] [--service SLUG] [--rate N] --text -   # the viewing log's ONLY writer (backlog 27, brief 2.2, migration 031): one dictation on stdin → one dated viewing + one note against the film the LADDER picks (the film the dashboard reports open → exactly one canonical film with that normalised title → stop and ask: AMBIGUOUS / NO-FILM exit 3, nothing written); --rate writes the 0–10 through rate_film; clears Unseen; same film same day APPENDS a note; refusals exit 2 before the one transaction; driven by the project skill .claude/skills/log-viewing
uv run movie-brain viewings remove VID [--note N]            # the whole viewing and its notes, or one note; rating and Unseen untouched
uv run movie-brain viewings list [--since DATE] [--film ID]  # newest first: date · #id title (year) · service · N notes · rated R
uv run movie-brain viewings open                             # the film the dashboard has open, if it reported in within two minutes (PUT /api/drawer, meta key drawer_film)
```

In the Rules paragraph add `viewings.md` (the viewing log's contract) to the list of path-scoped rules. In the Data paragraph nothing changes.

`.claude/rules/dashboard.md` — append one bullet: `**Viewing log** (brief `docs/superpowers/briefs/2026-09-21-viewing-log/brief-2.md`, contract in `viewings.md`, stories pinned in `tests/web/test_viewing_log.py` on their own server): the ratings block's "Me, 2004–08" line is replaced by the read-only Watched block (every viewing newest first — date · service · the note's first words, a details element for the whole text — then every real rental, duplicates collapsed, `li.rental`); the `watched` chip sits after Shop and leads the default sort with last viewing desc while on; the `last_watched` column ("Watched", after My Rating) sorts through `compare()` with empties last both ways; the page reports its open drawer (`PUT /api/drawer`) on open, close and every 30 s, and re-reads the open film on window focus / visibility so a dictation shows without a reload; a viewed film is always visible.`

- [ ] **Step 4: Trial log** — under "Round 2 (2026-09-27)" add a line: `**Built <date>** on `feature/STORY-27-viewing-log`, plan `docs/superpowers/plans/2026-09-27-viewing-log.md`; point C gap check next, on a migrated copy, before the owner's hands-on test.`

- [ ] **Step 5: Verify the docs build nothing stale**

Run: `uv run pytest tests/unit/test_gap_check_snapshot.py tests/unit/test_cli.py -q` and `grep -n "viewings" CLAUDE.md .claude/rules/viewings.md .claude/rules/dashboard.md | wc -l` (expect > 0 in each).
Expected: PASS; the greps find the lines.

- [ ] **Step 6: Commit**

```bash
git add .claude/skills/log-viewing/SKILL.md .claude/rules/viewings.md .claude/rules/dashboard.md CLAUDE.md docs/superpowers/briefs/2026-09-21-viewing-log/trial-log.md
git commit -m "Viewing log: the log-viewing skill (how a dictation becomes one command), the viewings contract, and the command docs

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Whole-suite run and the hands-on rehearsal on a copy

**Files:** none new; a scratch copy of the live database under the session scratchpad.

- [ ] **Step 1: Run the whole suite**

Run: `uv run pytest -q`
Expected: all PASS (about 2.5 minutes; the semantic test skips or passes).

- [ ] **Step 2: Rehearse the Blue Angel dictation on a COPY** (never the live DB; `migrate --apply` on the copy only)

```bash
S="$CLAUDE_SCRATCHPAD"/viewing-log-c && mkdir -p "$S" && cp ~/.config/movie-brain/movie-brain.db "$S/movie-brain.db" && cp ~/.config/movie-brain/tmdb-read-token.txt ~/.config/movie-brain/omdb-api-key.txt "$S/" 2>/dev/null
MOVIE_BRAIN_CONFIG_DIR="$S" uv run movie-brain migrate --apply
MOVIE_BRAIN_CONFIG_DIR="$S" uv run movie-brain viewings open
MOVIE_BRAIN_CONFIG_DIR="$S" uv run movie-brain viewings add --title "The Blue Angel" --service kino-film-collection --rate 6 --text - <<'EOF'
I just watched The Blue Angel. The restoration job on it is really good, and I'm watching it on Kino Collection. I would say I'll rate this one about a six.
EOF
MOVIE_BRAIN_CONFIG_DIR="$S" uv run movie-brain viewings add --title "Solaris" --text - <<'EOF'
tonight
EOF
MOVIE_BRAIN_CONFIG_DIR="$S" uv run movie-brain viewings add --title "Blue Angel" --text - <<'EOF'
dropped the article
EOF
MOVIE_BRAIN_CONFIG_DIR="$S" uv run movie-brain viewings add --title "pandora's box" --text - <<'EOF'
curly apostrophe in the catalogue
EOF
MOVIE_BRAIN_CONFIG_DIR="$S" uv run movie-brain viewings list --since 2026-09-01
```

Expected, in order: `OPEN      nothing …`; `LOGGED    #3390 'The Blue Angel' (1930) · <today> · kino-film-collection · viewing #1 · the one film with that title · rated 6`; `AMBIGUOUS 2 films titled 'Solaris' …` listing #2979 and #5235, exit 3; `NO-FILM … nearest: #3390 The Blue Angel (1930) …`, exit 3; `LOGGED    #3002 'Pandora’s Box' (1929) …`; a two-row listing. Paste the real lines into the trial log's Round 2 section under **Rehearsal on a copy**.

- [ ] **Step 3: Start the dashboard on the copy and check the drawer** — `MOVIE_BRAIN_CONFIG_DIR="$S" uv run movie-brain dashboard --port 5712`, open `http://127.0.0.1:5712/?film=3390`: the Watched block shows today's line above `2006-12-26 · rented · ★★★★☆`, the rating box says 6, the star is lit; `viewings open` from another shell now prints `OPEN      #3390 'The Blue Angel' (1930)`. Stop the server.

- [ ] **Step 4: Commit the trial-log lines**

```bash
git add docs/superpowers/briefs/2026-09-21-viewing-log/trial-log.md
git commit -m "Viewing log: rehearsal on a migrated copy — the Blue Angel, the two Solarises, the dropped article and the curly apostrophe, as the verb really prints them

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

Then hand back to the session: point C gap check (`scripts/gap_check_snapshot.sh <branch-head> "$S/movie-brain.db" viewing-log-c`, `Point: C`) before the owner's hands-on test; `migrate --apply` on the live database, the merge and the push each need his separate yes.
