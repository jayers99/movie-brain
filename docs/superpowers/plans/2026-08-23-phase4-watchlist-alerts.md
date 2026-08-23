# Phase 4: Watchlist + Availability Alerts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A ~50-film watchlist with a drawer toggle, sync-time availability-transition detection, a macOS notification for watchlist arrivals from the nightly sync, and a "New arrivals" dashboard chip.

**Architecture:** Hexagonal (dependencies point inward: `domain` ← `application`/`infrastructure` ← `web`/`cli`). Two new tables (`watchlist`, append-only `availability_transitions`). Transition detection lives in the SQLite Repository at listing-write time using a pre-batch "currency frontier"; the TMDB step gains a nightly watchlist provider pass; sync gains an injected notifier callable; the dashboard gains two chips, two `FilmView` fields, and a drawer star toggle.

**Tech Stack:** Python 3.12, uv, SQLite, Flask, Typer, pytest + pytest-bdd + responses + Playwright, ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-08-23-phase4-watchlist-alerts-design.md`

## Global Constraints

- Collectors never delete — sync/crawl writes are append-and-update only. (`watchlist` rows are user-response data, like `my_ratings`; the toggle may delete its own row.)
- Schema changes are new migrations only (`migrations/006_watchlist.sql`), wrapped in `BEGIN;`/`COMMIT;`, inserting their own `schema_version` row. Never edit an applied migration.
- Film identity = `films.guid`; integer `id` is an internal join key only.
- TMDB/notification failures must never affect the sync exit code or other steps.
- All commands run via `uv run …`. Full gate = `uv run pytest && uv run ruff check . && uv run mypy`.
- Canned-filter thresholds/chip names live ONLY in `domain/filters.py`; JS reads thresholds from `/api/config`; keep `CHIP_PREDICATES` in `app.js` and chip buttons in `index.html` in lockstep with `_PREDICATES`.
- Run the whole suite before every commit; every commit message is a brief single line focused on why.

## Codebase Orientation (read once)

- `src/movie_brain/infrastructure/database.py` — `Repository` (all SQL lives here), `_VIEW_SQL`, `_SERVICES_SQL`, `_row_to_view`.
- `src/movie_brain/application/availability.py` — `tmdb_step` (match pass → weekly-gated provider refresh).
- `src/movie_brain/application/sync.py` — `sync()` orchestrator: Criterion walk → OMDb loop → TMDB step.
- `src/movie_brain/domain/models.py` — `Film`, `FilmView` (frozen dataclasses). `src/movie_brain/domain/filters.py` — chip predicates + `thresholds()`.
- `src/movie_brain/web/app.py` — Flask routes; `src/movie_brain/web/static/app.js` + `templates/index.html` — all client logic.
- Tests: `tests/conftest.py` provides `repo` (tmp-dir Repository, migrations applied) and `today` (= `date(2026, 8, 19)`). BDD: `tests/features/*.feature` + `tests/step_defs/test_*.py` (HTTP mocked with `responses`). Web: `tests/web/conftest.py` seeds a session-scoped repo + live server for Playwright.
- `movie_service` registry and `service_provider` (TMDB provider id → slug) are seeded by migration 003; slugs include `criterion`, `max`, `mubi`, `peacock`, `prime-video`, `apple-tv-plus`, `apple-tv-store`.

---

### Task 1: Migration 006 + watchlist repository methods

**Files:**
- Create: `migrations/006_watchlist.sql`
- Modify: `src/movie_brain/infrastructure/database.py` (add methods at the end of the "ratings" section)
- Test: `tests/unit/test_database.py` (append)

**Interfaces:**
- Produces: `Repository.toggle_watchlist(film_id: int, today: date) -> bool | None` (None = unknown film, else new membership state); `Repository.watchlist_film_ids() -> set[int]`. Tables `watchlist(film_id, added_on)`, `availability_transitions(id, film_id, source, appeared_on)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_database.py`:

```python
# ---- Phase 4: watchlist -------------------------------------------------


def test_toggle_watchlist_round_trip(repo, today):
    fid = repo.upsert_film(Film("Tokyo Story", 1953, "Ozu", "https://c/tokyo-story"))
    assert repo.watchlist_film_ids() == set()
    assert repo.toggle_watchlist(fid, today) is True
    assert repo.watchlist_film_ids() == {fid}
    assert repo.toggle_watchlist(fid, today) is False
    assert repo.watchlist_film_ids() == set()


def test_toggle_watchlist_unknown_film_returns_none(repo, today):
    assert repo.toggle_watchlist(9999, today) is None
    assert repo.watchlist_film_ids() == set()
```

(`Film` is already imported at the top of `test_database.py`; check and reuse existing imports.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_database.py -k watchlist -v`
Expected: FAIL — `no such table: watchlist` or `AttributeError: toggle_watchlist`.

- [ ] **Step 3: Write the migration**

Create `migrations/006_watchlist.sql`:

```sql
-- Phase 4: watchlist + availability transitions
-- (spec: docs/superpowers/specs/2026-08-23-phase4-watchlist-alerts-design.md).
-- Additive only. watchlist is my-response data (like my_ratings), not collector data.
-- availability_transitions is append-only: one row per time a film newly appears
-- (insert or reappearance) on a service; collectors never delete. No backfill —
-- existing listings rows are upserts, not inserts, so migration causes no event flood.
BEGIN;
CREATE TABLE watchlist (
    film_id  INTEGER PRIMARY KEY REFERENCES films(id),
    added_on TEXT NOT NULL
);
CREATE TABLE availability_transitions (
    id          INTEGER PRIMARY KEY,
    film_id     INTEGER NOT NULL REFERENCES films(id),
    source      TEXT NOT NULL,
    appeared_on TEXT NOT NULL
);
CREATE INDEX idx_transitions_appeared ON availability_transitions(appeared_on);
INSERT INTO schema_version (version) VALUES (6);
COMMIT;
```

- [ ] **Step 4: Add the repository methods**

In `database.py`, after `all_my_ratings` (end of the `# ratings` section):

```python
    # watchlist --------------------------------------------------------
    def toggle_watchlist(self, film_id: int, today: date) -> bool | None:
        with self._conn() as c:
            if c.execute("SELECT 1 FROM films WHERE id = ?", (film_id,)).fetchone() is None:
                return None
            if c.execute("SELECT 1 FROM watchlist WHERE film_id = ?", (film_id,)).fetchone() is None:
                c.execute("INSERT INTO watchlist (film_id, added_on) VALUES (?, ?)", (film_id, today.isoformat()))
                return True
            c.execute("DELETE FROM watchlist WHERE film_id = ?", (film_id,))
            return False

    def watchlist_film_ids(self) -> set[int]:
        with self._conn() as c:
            return {int(r["film_id"]) for r in c.execute("SELECT film_id FROM watchlist")}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_database.py -k watchlist -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Full gate, then commit**

Run: `uv run pytest && uv run ruff check . && uv run mypy`
Expected: all green (migration must not break existing tests — it's additive).

```bash
git add migrations/006_watchlist.sql src/movie_brain/infrastructure/database.py tests/unit/test_database.py
git commit -m "Watchlist + transitions schema: the alert data lives in its own tables"
```

---

### Task 2: Transition detection at listing-write time

**Files:**
- Modify: `src/movie_brain/infrastructure/database.py` (`record_catalog`, new `_write_listing` helper, new public methods; new module constant `TMDB_REFRESH_STAMP`)
- Modify: `src/movie_brain/application/availability.py` (`META_REFRESHED_AT` now imports the constant)
- Test: `tests/unit/test_database.py` (append)

**Interfaces:**
- Consumes: `availability_transitions` table (Task 1).
- Produces: `TMDB_REFRESH_STAMP = "tmdb_providers_refreshed_at"` (module constant in `database.py`); `Repository.record_listing_with_transition(film_id: int, source: str, url: str, seen: date) -> bool`; `Repository.watchlist_transitions_on(day: date) -> list[tuple[str, str]]` (film title, service display name); `record_catalog` now records transitions internally.

**Semantics (from the spec):** a transition = a listings **insert**, or an upsert onto a row that was **not current** before the write batch began. "Before the batch" matters: `record_catalog` runs on every sync and re-stamps every current row, so the criterion frontier is captured as `MAX(last_seen)` **before** any write; for TMDB-fed sources the frontier is the `tmdb_providers_refreshed_at` meta stamp (written only after a completed full pass, so it is always pre-batch). A row with `last_seen` strictly older than the frontier was displayed as departed → its return is a transition. ISO date strings compare correctly as strings.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_database.py`:

```python
def _transitions(repo):
    import sqlite3

    with sqlite3.connect(repo.db_path) as c:
        return c.execute(
            "SELECT film_id, source, appeared_on FROM availability_transitions ORDER BY id"
        ).fetchall()


def test_record_listing_with_transition_insert_fires(repo, today):
    fid = repo.upsert_film(Film("Playtime", 1967, "Tati", "https://c/playtime"))
    assert repo.record_listing_with_transition(fid, "max", "https://tmdb/w/1", today) is True
    assert _transitions(repo) == [(fid, "max", today.isoformat())]


def test_record_listing_with_transition_current_row_is_quiet(repo, today):
    fid = repo.upsert_film(Film("Playtime", 1967, "Tati", "https://c/playtime"))
    repo.record_listing_with_transition(fid, "max", "https://tmdb/w/1", today)
    repo.set_meta("tmdb_providers_refreshed_at", today.isoformat())
    # Next nightly write: row (today) is not older than the stamp (today) → no new event.
    assert repo.record_listing_with_transition(fid, "max", "https://tmdb/w/1", today) is False
    assert len(_transitions(repo)) == 1


def test_record_listing_with_transition_reappearance_past_stamp_fires(repo, today):
    from datetime import timedelta

    fid = repo.upsert_film(Film("Playtime", 1967, "Tati", "https://c/playtime"))
    repo.record_listing_with_transition(fid, "max", "https://tmdb/w/1", today - timedelta(days=10))
    # A completed full refresh moved the stamp past the row → it displayed as departed.
    repo.set_meta("tmdb_providers_refreshed_at", (today - timedelta(days=3)).isoformat())
    assert repo.record_listing_with_transition(fid, "max", "https://tmdb/w/1", today) is True
    assert len(_transitions(repo)) == 2


def test_record_catalog_reupsert_of_current_rows_is_quiet(repo, today):
    films = [Film("Alpha", 1950, "Ann", "https://c/alpha")]
    repo.record_catalog("criterion", films, today)  # fresh DB: insert → 1 event
    repo.record_catalog("criterion", films, today)  # cheap-check path re-upsert → quiet
    assert len(_transitions(repo)) == 1


def test_record_catalog_reappearance_fires(repo, today):
    from datetime import timedelta

    alpha = Film("Alpha", 1950, "Ann", "https://c/alpha")
    bravo = Film("Bravo", 1960, "Bob", "https://c/bravo")
    repo.record_catalog("criterion", [alpha, bravo], today - timedelta(days=30))
    repo.record_catalog("criterion", [bravo], today - timedelta(days=7))  # alpha departs
    repo.record_catalog("criterion", [alpha, bravo], today)  # alpha returns
    events = _transitions(repo)
    alpha_id = repo.film_id_by_key(alpha.key)
    assert (alpha_id, "criterion", today.isoformat()) in events
    assert len(events) == 3  # 2 initial inserts + 1 reappearance; bravo re-upserts stay quiet


def test_watchlist_transitions_on_filters_day_and_membership(repo, today):
    from datetime import timedelta

    wanted = repo.upsert_film(Film("Playtime", 1967, "Tati", "https://c/playtime"))
    other = repo.upsert_film(Film("Alpha", 1950, "Ann", "https://c/alpha"))
    repo.toggle_watchlist(wanted, today)
    repo.record_listing_with_transition(wanted, "max", "https://tmdb/w/1", today)
    repo.record_listing_with_transition(other, "max", "https://tmdb/w/2", today)  # not watchlisted
    repo.record_listing_with_transition(wanted, "mubi", "https://tmdb/w/1", today - timedelta(days=1))
    assert repo.watchlist_transitions_on(today) == [("Playtime", "HBO Max")]
```

(The service display name comes from `movie_service.name`; verify the seeded name for slug `max` via `grep -A12 "INSERT INTO movie_service" migrations/003_multi_service.sql` and use it in the assertion — the tests below assume "HBO Max".)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_database.py -k "transition or reappearance" -v`
Expected: FAIL — `AttributeError: record_listing_with_transition`.

- [ ] **Step 3: Implement in `database.py`**

Add near the top (after `MIGRATIONS_DIR`):

```python
TMDB_REFRESH_STAMP = "tmdb_providers_refreshed_at"
```

Add a private helper inside `Repository` (below `record_listing`) and the public methods:

```python
    @staticmethod
    def _write_listing(
        c: sqlite3.Connection, film_id: int, source: str, url: str, day: str, frontier: str | None
    ) -> bool:
        """Upsert one listing row; append an availability transition on insert or reappearance.

        frontier = the source's currency cutoff captured BEFORE this write batch began
        (per-source MAX(last_seen) for criterion, the tmdb refresh stamp for TMDB-fed
        sources). A row strictly older than it was displayed as departed, so going
        current again is a transition; None (fresh DB) means only true inserts fire.
        """
        row = c.execute(
            "SELECT last_seen FROM listings WHERE film_id = ? AND source = ?", (film_id, source)
        ).fetchone()
        is_transition = row is None or (frontier is not None and row["last_seen"] < frontier)
        c.execute(
            "INSERT INTO listings (film_id, source, url, first_seen, last_seen) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(film_id, source) DO UPDATE SET url=excluded.url, last_seen=excluded.last_seen",
            (film_id, source, url, day, day),
        )
        if is_transition:
            c.execute(
                "INSERT INTO availability_transitions (film_id, source, appeared_on) VALUES (?, ?, ?)",
                (film_id, source, day),
            )
        return is_transition

    def record_listing_with_transition(self, film_id: int, source: str, url: str, seen: date) -> bool:
        with self._conn() as c:
            row = c.execute("SELECT value FROM meta WHERE key = ?", (TMDB_REFRESH_STAMP,)).fetchone()
            frontier = None if row is None else str(row["value"])
            return self._write_listing(c, film_id, source, url, seen.isoformat(), frontier)

    def watchlist_transitions_on(self, day: date) -> list[tuple[str, str]]:
        with self._conn() as c:
            rows = c.execute(
                # svod only: a film becoming *purchasable* (apple-tv-store) is recorded
                # as a transition but is never an arrival worth alerting on.
                "SELECT f.title, s.name AS service "
                "FROM availability_transitions t "
                "JOIN watchlist w ON w.film_id = t.film_id "
                "JOIN films f ON f.id = t.film_id "
                "JOIN movie_service s ON s.slug = t.source AND s.kind = 'svod' "
                "WHERE t.appeared_on = ? ORDER BY t.id",
                (day.isoformat(),),
            ).fetchall()
            return [(str(r["title"]), str(r["service"])) for r in rows]
```

Rework `record_catalog`: capture the frontier before the loop, then replace its inline listings INSERT with the helper (films + external_ids writes unchanged):

```python
    def record_catalog(self, source: str, films: list[Film], seen: date) -> None:
        day = seen.isoformat()
        with self._conn() as c:
            # Currency frontier BEFORE any write: record_catalog runs on every sync and
            # re-stamps current rows, so comparing against a mid-batch MAX would misread
            # every untouched-yet row as a reappearance.
            row = c.execute("SELECT MAX(last_seen) AS m FROM listings WHERE source = ?", (source,)).fetchone()
            frontier = None if row["m"] is None else str(row["m"])
            for film in films:
                c.execute(
                    "INSERT INTO films (guid, title, year, director, key) VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET title=excluded.title, year=excluded.year, "
                    "director=excluded.director",
                    (str(uuid.uuid4()), film.title, film.year, film.director, film.key),
                )
                film_id = int(c.execute("SELECT id FROM films WHERE key = ?", (film.key,)).fetchone()["id"])
                self._write_listing(c, film_id, source, film.url, day, frontier)
                try:
                    ...  # external_ids block UNCHANGED — keep the existing INSERT + IntegrityError containment
```

(Keep the existing external_ids `try/except sqlite3.IntegrityError` block exactly as it is today, but it may now use `film_id` directly instead of the `(SELECT id FROM films WHERE key = ?)` subquery.)

In `application/availability.py`, replace the literal constant:

```python
from movie_brain.infrastructure.database import TMDB_REFRESH_STAMP

META_REFRESHED_AT = TMDB_REFRESH_STAMP
```

(Keep the `META_REFRESHED_AT` name — `tests/step_defs/test_tmdb.py` imports it.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_database.py -v`
Expected: PASS, including all pre-existing tests.

- [ ] **Step 5: Full gate, then commit**

Run: `uv run pytest && uv run ruff check . && uv run mypy`
Expected: green — `record_catalog` behavior is unchanged except the new quiet event writes.

```bash
git add src/movie_brain/infrastructure/database.py src/movie_brain/application/availability.py tests/unit/test_database.py
git commit -m "Detect availability transitions at listing-write time via a pre-batch frontier"
```

---

### Task 3: Zero-film frontier fix for TMDB-fed services

**Files:**
- Modify: `src/movie_brain/infrastructure/database.py` (`_SERVICES_SQL`)
- Test: `tests/unit/test_database.py` (append)

**Interfaces:**
- Consumes: `TMDB_REFRESH_STAMP` (Task 2), meta table.
- Produces: services currency for non-criterion sources keyed off the refresh stamp, with a per-source-MAX fallback when the stamp is absent.

- [ ] **Step 1: Write the failing test**

```python
def test_services_currency_follows_refresh_stamp_not_frozen_max(repo, today):
    from datetime import timedelta

    # get_view reads through the criterion-joined _VIEW_SQL, so the film needs a
    # criterion listing to be viewable at all.
    repo.record_catalog("criterion", [Film("Oppenheimer", 2023, "Nolan", "https://c/opp")], today)
    fid = repo.film_id_by_key("oppenheimer (2023)")
    repo.record_listing_with_transition(fid, "peacock", "https://tmdb/w/1", today - timedelta(days=10))
    # Peacock dropped to zero films; a completed full refresh moved the stamp past the row.
    repo.set_meta("tmdb_providers_refreshed_at", today.isoformat())
    view = repo.get_view(fid)
    assert view.services == []


def test_services_currency_falls_back_to_max_without_stamp(repo, today):
    repo.record_catalog("criterion", [Film("Oppenheimer", 2023, "Nolan", "https://c/opp")], today)
    fid = repo.film_id_by_key("oppenheimer (2023)")
    repo.record_listing_with_transition(fid, "peacock", "https://tmdb/w/1", today)
    view = repo.get_view(fid)  # no stamp set (fresh DB) — MAX rule keeps the row current
    assert [s["name"] for s in view.services] == ["Peacock"]
```

(Use the actual `movie_service.name` for slug `peacock` from migration 003 — check it in Step 1 of Task 2.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_database.py -k currency -v`
Expected: the stamp test FAILS (row wrongly current under the frozen-MAX rule); the fallback test passes.

- [ ] **Step 3: Change `_SERVICES_SQL`**

```python
_SERVICES_SQL = """
SELECT l.film_id, s.name, s.subscribed FROM listings l
JOIN movie_service s ON s.slug = l.source
WHERE s.kind = 'svod' AND l.source != 'criterion'
  AND l.last_seen >= COALESCE(
      (SELECT value FROM meta WHERE key = 'tmdb_providers_refreshed_at'),
      (SELECT MAX(last_seen) FROM listings l2 WHERE l2.source = l.source))
ORDER BY l.film_id, s.subscribed DESC, s.name
"""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_database.py tests/web -v`
Expected: PASS — the web seed sets no stamp, so the fallback keeps its `max`/`mubi` rows current.

- [ ] **Step 5: Full gate, then commit**

```bash
git add src/movie_brain/infrastructure/database.py tests/unit/test_database.py
git commit -m "Key TMDB-source currency off the refresh stamp so zero-film services can empty"
```

---

### Task 4: FilmView fields, chip predicates, view assembly

**Files:**
- Modify: `src/movie_brain/domain/models.py` (`FilmView`), `src/movie_brain/domain/filters.py`, `src/movie_brain/infrastructure/database.py` (`_row_to_view`, `list_views`, `get_view`, new `_new_on_by_film` + `_watchlist_ids` helpers), `src/movie_brain/application/ratings.py` (thread `today` into `get_view`)
- Test: `tests/unit/test_filters.py`, `tests/unit/test_database.py` (append)

**Interfaces:**
- Consumes: `availability_transitions`, `watchlist` (Tasks 1–2).
- Produces: `FilmView.watchlisted: bool = False`; `FilmView.new_on: list[dict[str, object]]` (items `{"source": slug, "name": display, "appeared_on": iso}`, svod sources only, windowed to `NEW_ARRIVAL_DAYS`, latest event per (film, source)); `filters.NEW_ARRIVAL_DAYS = 14`; chips `new_arrivals` and `watchlist`; `thresholds()["new_arrival_days"]`; `Repository.list_views(source, today: date | None = None)` and `Repository.get_view(film_id, today: date | None = None)` (None → `date.today()`).

- [ ] **Step 1: Write the failing filter tests**

Append to `tests/unit/test_filters.py` (mirror the file's existing view-builder helper — read it first and reuse its `make_view`-style factory, adding the new fields as kwargs):

```python
def test_new_arrivals_chip_windows_on_appeared_date(today):
    fresh = _view(new_on=[{"source": "max", "name": "HBO Max", "appeared_on": today.isoformat()}])
    stale = _view(new_on=[{"source": "max", "name": "HBO Max", "appeared_on": "2026-08-01"}])
    empty = _view()
    assert matches(fresh, ["new_arrivals"], today)
    assert not matches(stale, ["new_arrivals"], today)  # 18 days > 14-day window
    assert not matches(empty, ["new_arrivals"], today)


def test_watchlist_chip(today):
    assert matches(_view(watchlisted=True), ["watchlist"], today)
    assert not matches(_view(), ["watchlist"], today)


def test_thresholds_expose_new_arrival_days():
    assert thresholds()["new_arrival_days"] == 14
```

(`_view` = whatever the existing factory in `test_filters.py` is named; extend it to pass through `new_on`/`watchlisted`.)

- [ ] **Step 2: Write the failing repository tests**

Append to `tests/unit/test_database.py`:

```python
def test_views_carry_new_on_and_watchlisted(repo, today):
    from datetime import timedelta

    films = [Film("Alpha", 1950, "Ann", "https://c/alpha")]
    repo.record_catalog("criterion", films, today - timedelta(days=30))  # insert event, outside window
    fid = repo.film_id_by_key("alpha (1950)")
    repo.toggle_watchlist(fid, today)
    repo.record_listing_with_transition(fid, "max", "https://tmdb/w/1", today - timedelta(days=3))
    view = repo.get_view(fid, today)
    assert view.watchlisted is True
    assert view.new_on == [
        {"source": "max", "name": "HBO Max", "appeared_on": (today - timedelta(days=3)).isoformat()}
    ]
    (listed,) = [v for v in repo.list_views("criterion", today) if v.id == fid]
    assert listed.new_on == view.new_on and listed.watchlisted is True
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_filters.py tests/unit/test_database.py -k "new_on or new_arrival or watchlist_chip or thresholds" -v`
Expected: FAIL — unknown fields / chips.

- [ ] **Step 4: Implement**

`domain/models.py`, `FilmView` — add after `services`:

```python
    watchlisted: bool = False
    new_on: list[dict[str, object]] = field(default_factory=list)  # [{source, name, appeared_on}], arrivals window only
```

`domain/filters.py`:

```python
NEW_ARRIVAL_DAYS = 14


def _new_arrivals(v: FilmView, today: date) -> bool:
    cutoff = today - timedelta(days=NEW_ARRIVAL_DAYS)
    return any(date.fromisoformat(str(t["appeared_on"])) >= cutoff for t in v.new_on)
```

In `_PREDICATES`, after `"departed"`:

```python
    "new_arrivals": _new_arrivals,
    "watchlist": lambda v, _: v.watchlisted,
```

In `thresholds()`:

```python
        "new_arrival_days": NEW_ARRIVAL_DAYS,
```

`infrastructure/database.py` — import `NEW_ARRIVAL_DAYS` from `movie_brain.domain.filters`; add helpers next to `_services_by_film`:

```python
_NEW_ON_SQL = """
SELECT t.film_id, t.source, s.name, MAX(t.appeared_on) AS appeared_on
FROM availability_transitions t
JOIN movie_service s ON s.slug = t.source AND s.kind = 'svod'
WHERE t.appeared_on >= ?
GROUP BY t.film_id, t.source
ORDER BY t.film_id, t.source
"""


def _new_on_by_film(c: sqlite3.Connection, cutoff_iso: str) -> dict[int, list[dict[str, object]]]:
    out: dict[int, list[dict[str, object]]] = {}
    for r in c.execute(_NEW_ON_SQL, (cutoff_iso,)):
        out.setdefault(int(r["film_id"]), []).append(
            {"source": str(r["source"]), "name": str(r["name"]), "appeared_on": str(r["appeared_on"])}
        )
    return out


def _watchlist_ids(c: sqlite3.Connection) -> set[int]:
    return {int(r["film_id"]) for r in c.execute("SELECT film_id FROM watchlist")}
```

Extend `_row_to_view(row, services=None, *, watchlisted=False, new_on=None)` to set the two fields, and rework the view methods:

```python
    def list_views(self, source: str, today: date | None = None) -> list[FilmView]:
        cutoff = ((today or date.today()) - timedelta(days=NEW_ARRIVAL_DAYS)).isoformat()
        with self._conn() as c:
            rows = c.execute(... unchanged ...).fetchall()
            services = _services_by_film(c)
            new_on = _new_on_by_film(c, cutoff)
            wl = _watchlist_ids(c)
            return [
                _row_to_view(r, services.get(r["id"]), watchlisted=r["id"] in wl, new_on=new_on.get(r["id"]))
                for r in rows
            ]

    def get_view(self, film_id: int, today: date | None = None) -> FilmView | None:
        cutoff = ((today or date.today()) - timedelta(days=NEW_ARRIVAL_DAYS)).isoformat()
        with self._conn() as c:
            row = c.execute(_VIEW_SQL + "WHERE f.id = ?", ("criterion", film_id)).fetchone()
            if row is None:
                return None
            return _row_to_view(
                row,
                _services_by_film(c).get(row["id"]),
                watchlisted=row["id"] in _watchlist_ids(c),
                new_on=_new_on_by_film(c, cutoff).get(row["id"]),
            )
```

`application/ratings.py`: `rate_film` already receives `today` — make its final `repo.get_view(film_id)` call pass it: `repo.get_view(film_id, today)`. (Read the file; keep everything else unchanged.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit -v`
Expected: PASS.

- [ ] **Step 6: Full gate, then commit**

Run: `uv run pytest && uv run ruff check . && uv run mypy`
(Existing `tests/web/test_api.py` payload assertions may enumerate keys — if one fails, extend its expected payload with `watchlisted`/`new_on`; that is this task's change, not scope creep.)

```bash
git add src/movie_brain/domain src/movie_brain/infrastructure/database.py src/movie_brain/application/ratings.py tests/unit
git commit -m "FilmView learns new_on + watchlisted; chips and thresholds follow"
```

---

### Task 5: Nightly watchlist provider pass in the TMDB step

**Files:**
- Modify: `src/movie_brain/application/availability.py` (extract `_refresh_pass`, add watchlist pass, `TmdbStepResult.watchlist_refreshed`), `src/movie_brain/infrastructure/database.py` (`films_for_watchlist_refresh`, `films_for_provider_refresh(skip_checked_on=...)`)
- Create: `tests/features/watchlist.feature`, `tests/step_defs/test_watchlist.py`
- Test: also `tests/unit/test_database.py` (append)

**Interfaces:**
- Consumes: `record_listing_with_transition` (Task 2), `watchlist_film_ids` (Task 1).
- Produces: `TmdbStepResult(matched, missed, refreshed, watchlist_refreshed)` (new 4th field, default 0); `Repository.films_for_watchlist_refresh() -> list[tuple[int, str]]`; `Repository.films_for_provider_refresh(skip_checked_on: date | None = None)`. The TMDB provider loops now write listings via `record_listing_with_transition`.

- [ ] **Step 1: Write the failing repository tests**

Append to `tests/unit/test_database.py`:

```python
def test_films_for_watchlist_refresh_is_watchlist_and_matched_only(repo, today):
    a = repo.upsert_film(Film("Alpha", 1950, "Ann", "https://c/alpha"))
    b = repo.upsert_film(Film("Bravo", 1960, "Bob", "https://c/bravo"))
    for fid, tid in ((a, 11), (b, 22)):
        repo.set_external_id(fid, "tmdb", str(tid), today)
        repo.upsert_tmdb(fid, found=True, looked_up=today)
    repo.toggle_watchlist(a, today)
    assert repo.films_for_watchlist_refresh() == [(a, "11")]


def test_films_for_provider_refresh_can_skip_films_checked_today(repo, today):
    a = repo.upsert_film(Film("Alpha", 1950, "Ann", "https://c/alpha"))
    repo.set_external_id(a, "tmdb", "11", today)
    repo.upsert_tmdb(a, found=True, looked_up=today)
    repo.record_tmdb_providers(a, today, "{}")
    assert repo.films_for_provider_refresh() == [(a, "11")]
    assert repo.films_for_provider_refresh(skip_checked_on=today) == []
```

- [ ] **Step 2: Write the failing BDD scenarios**

Create `tests/features/watchlist.feature`:

```gherkin
Feature: Watchlist films are refreshed nightly and arrivals are detected

  Background:
    Given a fresh repository
    And the Criterion browse page exposes a token
    And the Criterion catalog has films "Alpha (1950)" and "Bravo (1960)"
    And OMDb knows every film

  Scenario: Watchlist films get a provider refresh even inside the weekly gate
    Given TMDB knows "Alpha (1950)" as id 11
    And TMDB knows "Bravo (1960)" as id 22
    And TMDB streams id 11 on providers 1899 and 11
    And the provider refresh ran 2 days ago
    And "Alpha (1950)" is on the watchlist
    When I sync with a TMDB token
    Then TMDB providers were called exactly 1 times
    And the sync refreshed 1 watchlist films
    And "Alpha (1950)" has an availability transition on "max"

  Scenario: A full-refresh night does not fetch watchlist films twice
    Given TMDB knows "Alpha (1950)" as id 11
    And TMDB knows "Bravo (1960)" as id 22
    And TMDB streams id 11 on providers 1899 and 11
    And "Alpha (1950)" is on the watchlist
    When I sync with a TMDB token
    Then TMDB providers were called exactly 2 times

  Scenario: A re-upsert of still-current service listings records no new transitions
    Given TMDB knows "Alpha (1950)" as id 11
    And TMDB knows "Bravo (1960)" as id 22
    And TMDB streams id 11 on providers 1899 and 11
    And "Alpha (1950)" is on the watchlist
    When I sync with a TMDB token
    And I sync with a TMDB token again the next day
    Then "Alpha (1950)" has 2 availability transitions
```

(Provider 1899 = HBO Max → slug `max`; provider 11 = MUBI → slug `mubi`, per migration 003's `service_provider` seed. In the last scenario Alpha lands on both `max` and `mubi` on night one — 2 transitions — and night two's re-upserts stay quiet.)

Create `tests/step_defs/test_watchlist.py` — copy the fixture/step scaffolding from `tests/step_defs/test_tmdb.py` verbatim (`ctx`, `tmdb`, `parse_titles`, `movie_item`, catalog/token/OMDb givens, the `I sync with a TMDB token` whens, `TMDB providers were called exactly N times` then), change the `scenarios(...)` line to `scenarios("../features/watchlist.feature")`, and add:

```python
@given(parsers.parse('"{title} ({year:d})" is on the watchlist'))
def on_watchlist(ctx, title, year):
    # The film must exist before it can be watchlisted: record it the way sync would.
    fid = ctx["repo"].film_id_by_key(f"{title.lower()} ({year})")
    if fid is None:
        ctx["repo"].record_catalog(SOURCE, parse_titles(f'"{title} ({year})"'), TODAY - timedelta(days=30))
        fid = ctx["repo"].film_id_by_key(f"{title.lower()} ({year})")
    ctx["repo"].toggle_watchlist(fid, TODAY)


@then(parsers.parse("the sync refreshed {n:d} watchlist films"))
def wl_refreshed(ctx, n):
    assert ctx["result"].tmdb_watchlist_refreshed == n


@then(parsers.parse('"{title} ({year:d})" has an availability transition on "{slug}"'))
def has_transition(ctx, title, year, slug):
    fid = ctx["repo"].film_id_by_key(f"{title.lower()} ({year})")
    with sqlite3.connect(ctx["repo"].db_path) as c:
        rows = c.execute(
            "SELECT 1 FROM availability_transitions WHERE film_id = ? AND source = ?", (fid, slug)
        ).fetchall()
    assert rows


@then(parsers.parse('"{title} ({year:d})" has {n:d} availability transitions'))
def transition_count(ctx, title, year, n):
    fid = ctx["repo"].film_id_by_key(f"{title.lower()} ({year})")
    with sqlite3.connect(ctx["repo"].db_path) as c:
        got = c.execute(
            "SELECT COUNT(*) FROM availability_transitions WHERE film_id = ? AND source != 'criterion'",
            (fid,),
        ).fetchone()[0]
    assert got == n
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_database.py -k refresh -v && uv run pytest tests/step_defs/test_watchlist.py -v`
Expected: FAIL — missing repository methods / step errors.

- [ ] **Step 4: Implement**

`database.py` (tmdb section):

```python
    def films_for_watchlist_refresh(self) -> list[tuple[int, str]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT t.film_id, x.value FROM tmdb t "
                "JOIN external_ids x ON x.film_id = t.film_id AND x.authority = 'tmdb' "
                "JOIN watchlist w ON w.film_id = t.film_id "
                "WHERE t.found = 1 ORDER BY t.film_id"
            ).fetchall()
            return [(int(r["film_id"]), str(r["value"])) for r in rows]
```

Change `films_for_provider_refresh` to:

```python
    def films_for_provider_refresh(self, skip_checked_on: date | None = None) -> list[tuple[int, str]]:
        where = "" if skip_checked_on is None else "AND COALESCE(t.providers_checked_at, '') != ? "
        params: tuple[object, ...] = () if skip_checked_on is None else (skip_checked_on.isoformat(),)
        with self._conn() as c:
            rows = c.execute(
                "SELECT t.film_id, x.value FROM tmdb t "
                "JOIN external_ids x ON x.film_id = t.film_id AND x.authority = 'tmdb' "
                "WHERE t.found = 1 " + where + "ORDER BY (t.providers_checked_at IS NOT NULL), t.providers_checked_at, t.film_id",
                params,
            ).fetchall()
            return [(int(r["film_id"]), str(r["value"])) for r in rows]
```

`availability.py`: add `watchlist_refreshed: int = 0` to `TmdbStepResult`; extract the provider-refresh loop body into a helper and wire two passes. The helper (module-level, below `tmdb_step`):

```python
def _refresh_pass(
    repo: Repository,
    client: TmdbClient,
    films: list[tuple[int, str]],
    pmap: dict[int, str],
    today: date,
    log: Callable[[str], None],
) -> tuple[int, bool]:
    """Fetch + write providers for films; returns (refreshed, aborted)."""
    refreshed = 0
    consecutive = 0
    for film_id, tmdb_id in films:
        if consecutive >= MAX_CONSECUTIVE_FAILURES:
            log("TMDB provider lookups failing repeatedly — stopping; next run resumes.")
            return refreshed, True
        try:
            numeric_tmdb_id = int(tmdb_id)
        except ValueError:
            log(f"invalid tmdb id {tmdb_id!r} for film {film_id}")
            continue
        try:
            providers = client.watch_providers(numeric_tmdb_id)
        except AuthError as exc:
            log(f"TMDB rejected the token: {exc}")
            return refreshed, True
        except requests.RequestException as exc:
            log(f"TMDB providers failed for film {film_id}: {exc}")
            consecutive += 1
            continue
        consecutive = 0
        slugs = {pmap[p] for p in providers.flatrate if p in pmap and pmap[p] != "criterion"}
        if STORE_PROVIDER_ID in pmap and STORE_PROVIDER_ID in (*providers.rent, *providers.buy):
            slugs.add(pmap[STORE_PROVIDER_ID])
        url = providers.link or watch_link(numeric_tmdb_id)
        for slug in sorted(slugs):
            repo.record_listing_with_transition(film_id, slug, url, today)
        repo.record_tmdb_providers(film_id, today, providers.payload)
        refreshed += 1
    return refreshed, False
```

Replace everything in `tmdb_step` after the `if aborted: return …` line with:

```python
    pmap = repo.provider_map()
    # Watchlist pass — every run, gate or no gate: the whole point is ≤1-day lag
    # for the ~50 films worth alerting on. Never touches the weekly stamp.
    wl_refreshed, wl_aborted = _refresh_pass(repo, client, repo.films_for_watchlist_refresh(), pmap, today, log)
    if wl_aborted:
        return TmdbStepResult(matched, missed, refreshed, wl_refreshed)
    stamp = repo.get_meta(META_REFRESHED_AT)
    if stamp is not None and 0 <= (today - date.fromisoformat(stamp)).days <= REFRESH_DAYS:
        return TmdbStepResult(matched, missed, refreshed, wl_refreshed)
    refreshed, full_aborted = _refresh_pass(
        repo, client, repo.films_for_provider_refresh(skip_checked_on=today), pmap, today, log
    )
    if full_aborted:
        return TmdbStepResult(matched, missed, refreshed, wl_refreshed)
    repo.set_meta(META_REFRESHED_AT, today.isoformat())
    return TmdbStepResult(matched, missed, refreshed, wl_refreshed)
```

`sync.py`: add `tmdb_watchlist_refreshed: int = 0` to `SyncResult` and pass `tmdb.watchlist_refreshed` as its value in the final `SyncResult(...)` construction.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/step_defs/test_watchlist.py tests/step_defs/test_tmdb.py tests/unit -v`
Expected: PASS — including the pre-existing tmdb scenarios (no watchlist there → watchlist pass is a no-op and call counts are unchanged).

- [ ] **Step 6: Full gate, then commit**

```bash
git add src/movie_brain/application src/movie_brain/infrastructure/database.py tests
git commit -m "Nightly watchlist provider pass: 1-day lag where alerting matters"
```

---

### Task 6: macOS notification from the nightly sync

**Files:**
- Create: `src/movie_brain/infrastructure/notify.py`, `tests/unit/test_notify.py`
- Modify: `src/movie_brain/application/sync.py` (notifier param + summary message), `src/movie_brain/cli.py` (wire the real notifier)
- Test: `tests/features/watchlist.feature` + `tests/step_defs/test_watchlist.py` (append)

**Interfaces:**
- Consumes: `watchlist_transitions_on` (Task 2).
- Produces: `notify(title: str, body: str) -> None` (osascript, all failures swallowed); `sync(..., notifier: Callable[[str, str], None] | None = None)`.

- [ ] **Step 1: Write the failing unit tests**

Create `tests/unit/test_notify.py`:

```python
from __future__ import annotations

from unittest.mock import patch

from movie_brain.infrastructure.notify import notify


def test_notify_shells_out_to_osascript():
    with patch("movie_brain.infrastructure.notify.subprocess.run") as run:
        notify("movie-brain", 'Alpha on HBO Max — brief "window"')
    args = run.call_args.args[0]
    assert args[0] == "osascript" and args[1] == "-e"
    assert 'with title "movie-brain"' in args[2]
    assert "Alpha on HBO Max" in args[2]


def test_notify_swallows_failure():
    with patch("movie_brain.infrastructure.notify.subprocess.run", side_effect=OSError("no osascript")):
        notify("movie-brain", "body")  # must not raise
```

- [ ] **Step 2: Write the failing BDD scenarios**

Append to `tests/features/watchlist.feature`:

```gherkin
  Scenario: A watchlist arrival produces one summary notification
    Given TMDB knows "Alpha (1950)" as id 11
    And TMDB knows "Bravo (1960)" as id 22
    And TMDB streams id 11 on providers 1899 and 11
    And TMDB streams id 22 on providers 1899 and 386
    And "Alpha (1950)" is on the watchlist
    When I sync with a TMDB token and a notifier
    Then one notification was sent
    And the notification mentions "Alpha" and "HBO Max"
    And the notification does not mention "Bravo"

  Scenario: No watchlist arrivals means no notification
    Given TMDB knows "Alpha (1950)" as id 11
    And TMDB knows "Bravo (1960)" as id 22
    And TMDB streams id 11 on providers 1899 and 11
    When I sync with a TMDB token and a notifier
    Then no notification was sent
```

Append to `tests/step_defs/test_watchlist.py`:

```python
@when("I sync with a TMDB token and a notifier")
def do_sync_notify(ctx, tmdb):
    sent: list[tuple[str, str]] = []
    ctx["sent"] = sent
    ctx["result"] = sync(
        ctx["repo"], "omdb-key", TODAY, tmdb_token="tok", notifier=lambda t, b: sent.append((t, b))
    )


@then("one notification was sent")
def one_sent(ctx):
    assert len(ctx["sent"]) == 1


@then("no notification was sent")
def none_sent(ctx):
    assert ctx["sent"] == []


@then(parsers.parse('the notification mentions "{a}" and "{b}"'))
def mentions(ctx, a, b):
    (_, notification_body) = ctx["sent"][0]
    assert a in notification_body and b in notification_body


@then(parsers.parse('the notification does not mention "{a}"'))
def not_mentions(ctx, a):
    (_, notification_body) = ctx["sent"][0]
    assert a not in notification_body
```

(Note: the "no arrivals" scenario has no watchlist member, so `watchlist_transitions_on` is empty even though Alpha newly appears on services.)

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_notify.py tests/step_defs/test_watchlist.py -v`
Expected: FAIL — no `notify` module; `sync()` has no `notifier` param.

- [ ] **Step 4: Implement**

Create `src/movie_brain/infrastructure/notify.py`:

```python
from __future__ import annotations

import json
import subprocess


def notify(title: str, body: str) -> None:
    """Post a macOS notification via osascript (works from the user LaunchAgent).

    json.dumps produces a double-quoted, escaped literal that AppleScript accepts.
    All failures are swallowed: an alert must never affect the sync outcome.
    """
    script = f"display notification {json.dumps(body)} with title {json.dumps(title)}"
    try:
        subprocess.run(["osascript", "-e", script], check=False, capture_output=True, timeout=10)
    except Exception:  # noqa: BLE001 — notification failure must never affect the sync
        pass
```

`sync.py`: add the parameter `notifier: Callable[[str, str], None] | None = None` to `sync()` (after `tmdb_token`). After the TMDB-step block and before the final `SyncResult(...)`:

```python
    if notifier is not None:
        arrivals = repo.watchlist_transitions_on(today)
        if arrivals:
            listed = " · ".join(f"{title} on {service}" for title, service in arrivals[:4])
            if len(arrivals) > 4:
                listed += f" · … and {len(arrivals) - 4} more"
            noun = "arrival" if len(arrivals) == 1 else "arrivals"
            try:
                notifier("movie-brain", f"{len(arrivals)} watchlist {noun}: {listed}")
            except Exception as exc:  # noqa: BLE001 — alerts must never affect the sync outcome
                log(f"notification failed: {exc}")
```

`cli.py`, in `sync_cmd`: import `from movie_brain.infrastructure.notify import notify` (top of file, with the other infrastructure imports) and add `notifier=notify` to the `sync(...)` call.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_notify.py tests/step_defs/test_watchlist.py tests/unit/test_cli.py -v`
Expected: PASS.

- [ ] **Step 6: Full gate, then commit**

```bash
git add src/movie_brain/infrastructure/notify.py src/movie_brain/application/sync.py src/movie_brain/cli.py tests
git commit -m "One summary macOS notification per sync for watchlist arrivals"
```

---

### Task 7: Web API — watchlist toggle, today threading, config

**Files:**
- Modify: `src/movie_brain/web/app.py`
- Test: `tests/web/test_api.py` (append)

**Interfaces:**
- Consumes: `toggle_watchlist` (Task 1), `list_views/get_view(source_or_id, today)` (Task 4), `thresholds()` (Task 4).
- Produces: `POST /api/films/<id>/watchlist` → `{"watchlisted": bool}` (404 unknown film); both film endpoints serve `watchlisted` + `new_on`; `/api/config` carries `new_arrival_days` and the two new chips (automatic via `CHIPS`/`thresholds()`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/web/test_api.py` (reuse the file's existing Flask `client` fixture — read the file first and match its fixture names):

```python
def test_watchlist_toggle_round_trip(client):
    films = client.get("/api/films").get_json()
    fid = films[0]["id"]
    assert client.post(f"/api/films/{fid}/watchlist").get_json() == {"watchlisted": True}
    assert client.get(f"/api/films/{fid}").get_json()["watchlisted"] is True
    assert client.post(f"/api/films/{fid}/watchlist").get_json() == {"watchlisted": False}


def test_watchlist_toggle_unknown_film_404s(client):
    r = client.post("/api/films/999999/watchlist")
    assert r.status_code == 404


def test_films_payload_carries_new_on_and_watchlisted(client):
    film = client.get("/api/films").get_json()[0]
    assert "new_on" in film and "watchlisted" in film


def test_config_carries_new_arrival_days_and_chips(client):
    cfg = client.get("/api/config").get_json()
    assert cfg["canned_thresholds"]["new_arrival_days"] == 14
    assert "new_arrivals" in cfg["chips"] and "watchlist" in cfg["chips"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/web/test_api.py -k "watchlist or new_on or new_arrival" -v`
Expected: FAIL — 405/404 on POST; config missing threshold only if Task 4 skipped (it shouldn't be — then this one passes, fine).

- [ ] **Step 3: Implement in `web/app.py`**

Thread `today` into the read endpoints and add the toggle route:

```python
    @app.get("/api/films")
    def list_films() -> Response:
        return jsonify([v.to_dict() for v in repo.list_views(SOURCE, today())])
```

In `film_detail`, change `repo.get_view(film_id)` → `repo.get_view(film_id, today())`. Then:

```python
    @app.post("/api/films/<int:film_id>/watchlist")
    def toggle_watchlist(film_id: int) -> tuple[Response, int]:
        watchlisted = repo.toggle_watchlist(film_id, today())
        if watchlisted is None:
            return jsonify({"error": "not found"}), 404
        return jsonify({"watchlisted": watchlisted}), 200
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/web/test_api.py -v`
Expected: PASS.

- [ ] **Step 5: Full gate, then commit**

```bash
git add src/movie_brain/web/app.py tests/web/test_api.py
git commit -m "Watchlist toggle endpoint; film payloads gain new_on/watchlisted"
```

---

### Task 8: Frontend — chips, drawer star, "New on" line

**Files:**
- Modify: `src/movie_brain/web/static/app.js`, `src/movie_brain/web/templates/index.html`, `tests/web/conftest.py` (seed), `src/movie_brain/web/static/style.css` (only if a `.watch-toggle` rule is needed for sane rendering)
- Test: `tests/web/test_dashboard.py` (append)

**Interfaces:**
- Consumes: `/api/films` `new_on`/`watchlisted`, `POST /api/films/<id>/watchlist`, config `new_arrival_days` (Task 7).
- Produces: chips `new_arrivals` ("New arrivals") and `watchlist` ("Watchlist") in `index.html` + `CHIP_PREDICATES`; drawer star toggle + "New on:" line.

- [ ] **Step 1: Extend the Playwright seed**

In `tests/web/conftest.py` `seed()`, replace Alpha's three `record_listing` calls with `record_listing_with_transition` (same arguments) — Alpha's `max`/`mubi`/`apple-tv-store` rows become insert transitions dated TODAY, making Alpha the one "new arrival". Then add:

```python
    # Bravo is the one seeded watchlist film (Charlie stays free for the toggle test).
    repo.toggle_watchlist(ids["bravo (1960)"], TODAY)
```

- [ ] **Step 2: Write the failing Playwright tests**

Append to `tests/web/test_dashboard.py` (match the file's existing test style — it uses the `dash` fixture and `data-count` attribute; read a neighboring chip test first and mirror it):

```python
def test_new_arrivals_chip_filters_to_alpha(dash):
    dash.click('button[data-chip="new_arrivals"]')
    dash.wait_for_selector('#films tbody[data-count="1"]')
    assert dash.locator("#films tbody tr").first.inner_text().startswith("Alpha")


def test_watchlist_chip_filters_to_bravo(dash):
    dash.click('button[data-chip="watchlist"]')
    dash.wait_for_selector('#films tbody[data-count="1"]')
    assert dash.locator("#films tbody tr").first.inner_text().startswith("Bravo")


def test_drawer_shows_new_on_line(dash):
    dash.locator("#films tbody tr", has_text="Alpha").first.click()
    dash.wait_for_selector("#drawer:not([hidden])")
    assert "New on" in dash.locator("#drawer-body").inner_text()


def test_drawer_star_toggles_watchlist(dash):
    dash.locator("#films tbody tr", has_text="Charlie").first.click()
    dash.wait_for_selector("#drawer:not([hidden])")
    star = dash.locator(".watch-toggle")
    assert star.inner_text() == "☆"
    star.click()
    dash.wait_for_selector('.watch-toggle:has-text("★")')
    star.click()  # leave the session-scoped seed as we found it
    dash.wait_for_selector('.watch-toggle:has-text("☆")')
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/web/test_dashboard.py -k "new_arrivals or watchlist or new_on or star" -v`
Expected: FAIL — no such chip buttons / selectors.

- [ ] **Step 4: Implement**

`index.html` — add before the Clear button, keeping lockstep order with `_PREDICATES`:

```html
      <button class="chip" data-chip="new_arrivals">New arrivals</button>
      <button class="chip" data-chip="watchlist">Watchlist</button>
```

`app.js` — in `CHIP_PREDICATES`, after `departed`:

```js
    new_arrivals: (f) => (f.new_on || []).some((t) => daysBetween(t.appeared_on, state.cfg.today) <= state.cfg.canned_thresholds.new_arrival_days),
    watchlist: (f) => f.watchlisted,
```

In `detailHtml`, change the `<h2>` line and add the "New on" line next to the existing streaming line:

```js
    const newOn = (d.new_on || []).map((t) => `${esc(t.name)} since ${esc(t.appeared_on)}`).join(', ');
    return `<h2>${esc(d.title)} <button class="watch-toggle" data-id="${d.id}" title="Toggle watchlist" aria-label="Toggle watchlist">${d.watchlisted ? '★' : '☆'}</button></h2>
      ...
      ${newOn ? `<p class="meta new-on">New on: ${newOn}</p>` : ''}
      ${streaming ? `<p class="meta">Also streaming on: ${streaming}</p>` : ''}
```

(Everything between stays exactly as it is; only the h2 opening and the inserted `new-on` line change.)

Add a delegated click handler next to the drawer's other handlers (after the `backdrop.addEventListener` line):

```js
  body.addEventListener('click', async (e) => {
    const b = e.target.closest('.watch-toggle'); if (!b) return;
    const r = await fetch(`/api/films/${b.dataset.id}/watchlist`, { method: 'POST' });
    if (!r.ok) { toast('Could not update watchlist'); return; }
    const { watchlisted } = await r.json();
    b.textContent = watchlisted ? '★' : '☆';
    const film = state.films.find((f) => f.id === +b.dataset.id);
    if (film) { film.watchlisted = watchlisted; applyFilters(); }
  });
```

`style.css` — a minimal rule so the star reads as a control (match the file's existing button styling conventions):

```css
.watch-toggle { background: none; border: none; font-size: 1.1em; cursor: pointer; vertical-align: middle; }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/web -v`
Expected: PASS — including all pre-existing dashboard tests (seed changes add a transition + a watchlist row but change no ratings/languages/counts the old tests assert on; if a pre-existing count assertion trips, inspect whether the new chips shifted a `data-count` and fix the seed, not the old test).

- [ ] **Step 6: Full gate, then commit**

```bash
git add src/movie_brain/web tests/web
git commit -m "Dashboard surfaces arrivals and the watchlist: chips, drawer star, New-on line"
```

---

### Task 9: Docs, roadmap, final gate

**Files:**
- Modify: `CLAUDE.md`, `docs/multiple-movie-services.md`, `docs/superpowers/handoffs/2026-08-23-phase4-handoff.md` (status note at top)

- [ ] **Step 1: Update CLAUDE.md**

- Sync flow section: extend step 5's description — nightly watchlist provider pass + weekly full refresh; transitions recorded on insert/reappearance; watchlist arrivals fire one macOS notification.
- Rules section: add — "Availability transitions are append-only events recorded at listing-write time against the pre-batch currency frontier; `watchlist` is user-response data (drawer toggle is the only writer). 'Current' for TMDB-fed sources = `last_seen >= tmdb_providers_refreshed_at` (criterion keeps MAX(last_seen))."

- [ ] **Step 2: Mark Phase 4 done**

In `docs/multiple-movie-services.md`: phase table row 4 → `Watchlist + availability alerts — **done**`; phase 4 list entry gets `**Done (2026-08-23).**` prefix with a one-line landing note (mirror how phases 1–3 are marked). Add a one-line "Superseded: Phase 4 landed" note at the top of the Phase 4 handoff doc.

- [ ] **Step 3: Full gate**

Run: `uv run pytest && uv run ruff check . && uv run mypy`
Expected: everything green. Report the counts.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md docs
git commit -m "Docs: Phase 4 (watchlist + availability alerts) landed"
```
