# Phase 1 Schema Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a generated GUID the canonical movie identity, add the service registry / provider grouping / external-ids tables, remove `purge_departed` (films become immutable), and migrate the live Criterion data — with zero visible change to the dashboard or the 3 AM sync.

**Architecture:** Evolve the SQLite schema in place with one new migration (`003_multi_service.sql`): rebuild `films` with a `NOT NULL UNIQUE guid`, rebuild `listings` so `source` is an FK into a seeded `movie_service` registry, and add `service_provider` + `external_ids`. `Repository` grows guid generation on insert plus three small accessors; `sync` loses its purge call. Nothing in `domain/`, `web/`, or `cli.py` changes.

**Tech Stack:** Python 3 / sqlite3 stdlib, pytest + pytest-bdd, uv, ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-08-23-phase1-schema-redesign-design.md` — read it first; all decisions there are settled.

## Global Constraints

- All commands run via `uv run …` (never bare python/pytest).
- Never edit an applied migration (`001`, `002`); all schema change goes in the new `migrations/003_multi_service.sql`, which must end by inserting its own `schema_version` row.
- Zero visible change: `FilmView`, the web API payload, `web/`, `cli.py`, `domain/` are untouched.
- Guids are immutable once assigned; `ON CONFLICT` clauses must never update `guid`.
- Service seeds are exactly the spec's tables: 8 `movie_service` rows, 8 `service_provider` rows, no Amazon-channel provider ids (1825, 201, 287 excluded), GB BFI Player (224) excluded.
- Gate for every task: the touched tests pass; final task runs the full `uv run pytest`, `uv run ruff check .`, `uv run mypy` — all green.
- Work on branch `feature/PHASE-1-schema-redesign` off `main`.
- Commits: brief single line, why-focused, ending with the Claude co-author trailer.

---

### Task 0: Branch

**Files:** none

- [ ] **Step 1: Create the working branch**

```bash
cd /Users/jayers/code/movie-brain
git checkout -b feature/PHASE-1-schema-redesign main
```

---

### Task 1: Migration 003 + guid generation on insert

The migration and the `Repository` insert changes land together: once `films.guid` is `NOT NULL`, the existing `INSERT INTO films` calls would violate it, so the suite only stays green if both change in one task.

**Files:**
- Create: `migrations/003_multi_service.sql`
- Modify: `src/movie_brain/infrastructure/database.py` (imports; `upsert_film` ~line 80; `record_catalog` ~line 126)
- Test: `tests/unit/test_database.py`

**Interfaces:**
- Consumes: existing `init_db(db_path)`, `Repository`, `MIGRATIONS_DIR` (glob-ordered `NNN_*.sql` runner — no code change needed to pick up 003).
- Produces: tables `movie_service(slug PK, name, kind, subscribed, region)`, `service_provider(tmdb_provider_id PK, service_slug FK, label)`, `external_ids(film_id FK, authority, value, first_seen, PK(film_id, authority), UNIQUE(authority, value))`; `films.guid TEXT NOT NULL UNIQUE`; `listings.source` FK → `movie_service(slug)`. Task 2 relies on `external_ids` existing; Task 2's `services()` reads `movie_service`.

- [ ] **Step 1: Write the failing migration tests**

Append to `tests/unit/test_database.py` (add `import re` next to the existing `import sqlite3`):

```python
UUID4_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def _v2_db_with_criterion_data(p):
    conn = sqlite3.connect(p)
    conn.executescript((MIGRATIONS_DIR / "001_init.sql").read_text())
    conn.executescript((MIGRATIONS_DIR / "002_metacritic.sql").read_text())
    conn.execute("INSERT INTO films (id, title, year, key) VALUES (1, 'Trio', 1950, 'trio (1950)')")
    conn.execute("INSERT INTO films (id, title, year, key) VALUES (2, 'Quartet', 1948, 'quartet (1948)')")
    conn.execute(
        "INSERT INTO listings VALUES (1, 'criterion', 'https://c/trio', '2026-08-01', '2026-08-19', NULL)"
    )
    conn.execute(
        "INSERT INTO listings VALUES (2, 'criterion', 'https://c/quartet', '2026-08-01', '2026-08-19', 'August 31')"
    )
    conn.execute("INSERT INTO omdb (film_id, found, looked_up, payload) VALUES (1, 1, '2026-08-01', '{}')")
    conn.execute("INSERT INTO my_ratings VALUES (1, 8, '2026-08-01')")
    conn.commit()
    conn.close()


def test_migration_003_assigns_guids_and_preserves_data(tmp_path):
    p = tmp_path / "old.db"
    _v2_db_with_criterion_data(p)
    init_db(p)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    guids = [r["guid"] for r in conn.execute("SELECT guid FROM films ORDER BY id")]
    assert len(guids) == 2 and len(set(guids)) == 2
    assert all(UUID4_RE.match(g) for g in guids)
    listings = {
        r["film_id"]: (r["url"], r["first_seen"], r["last_seen"], r["leaving_date"])
        for r in conn.execute("SELECT * FROM listings")
    }
    assert listings == {
        1: ("https://c/trio", "2026-08-01", "2026-08-19", None),
        2: ("https://c/quartet", "2026-08-01", "2026-08-19", "August 31"),
    }
    assert conn.execute("SELECT payload FROM omdb WHERE film_id = 1").fetchone()[0] == "{}"
    assert conn.execute("SELECT score FROM my_ratings WHERE film_id = 1").fetchone()[0] == 8
    conn.close()


def test_migration_003_backfills_criterion_external_ids(tmp_path):
    p = tmp_path / "old.db"
    _v2_db_with_criterion_data(p)
    init_db(p)
    conn = sqlite3.connect(p)
    ext = dict(conn.execute("SELECT film_id, value FROM external_ids WHERE authority = 'criterion'"))
    assert ext == {1: "https://c/trio", 2: "https://c/quartet"}
    assert conn.execute("SELECT first_seen FROM external_ids WHERE film_id = 1").fetchone()[0] == "2026-08-01"
    conn.close()


def test_migration_003_seeds_service_registry(repo):
    conn = sqlite3.connect(repo.db_path)
    services = dict(conn.execute("SELECT slug, subscribed FROM movie_service"))
    assert services == {
        "criterion": 1,
        "apple-tv-plus": 1,
        "apple-tv-store": 1,
        "max": 1,
        "peacock": 1,
        "prime-video": 1,
        "mubi": 0,
        "bfi-player-classics": 0,
    }
    kinds = dict(conn.execute("SELECT slug, kind FROM movie_service"))
    assert kinds["apple-tv-store"] == "store" and kinds["criterion"] == "svod"
    providers = dict(conn.execute("SELECT tmdb_provider_id, service_slug FROM service_provider"))
    assert providers == {
        258: "criterion",
        350: "apple-tv-plus",
        2: "apple-tv-store",
        1899: "max",
        386: "peacock",
        387: "peacock",
        9: "prime-video",
        11: "mubi",
    }
    conn.close()


def test_guid_is_stable_across_repeated_catalog_walks(repo):
    def guid():
        conn = sqlite3.connect(repo.db_path)
        g = conn.execute("SELECT guid FROM films WHERE key = 'trio (1950)'").fetchone()[0]
        conn.close()
        return g

    repo.record_catalog("criterion", [TRIO], D1)
    first = guid()
    assert UUID4_RE.match(first)
    repo.record_catalog("criterion", [TRIO], D2)
    repo.upsert_film(TRIO)
    assert guid() == first
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `uv run pytest tests/unit/test_database.py -k "migration_003 or guid_is_stable" -v`
Expected: FAIL — `sqlite3.OperationalError: no such column: guid` (003 doesn't exist yet).

- [ ] **Step 3: Write the migration**

Create `migrations/003_multi_service.sql` exactly:

```sql
-- Phase 1: GUID identity + services model (spec: docs/superpowers/specs/2026-08-23-phase1-schema-redesign-design.md).
-- Runs on init_db's plain sqlite3 connection, where foreign_keys is OFF — so parent
-- tables can be dropped and recreated while child tables keep referencing them by name.

CREATE TABLE movie_service (
    slug TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('svod', 'store')),
    subscribed INTEGER NOT NULL DEFAULT 0,
    region TEXT NOT NULL DEFAULT 'US'
);
INSERT INTO movie_service (slug, name, kind, subscribed) VALUES
    ('criterion', 'Criterion Channel', 'svod', 1),
    ('apple-tv-plus', 'Apple TV+', 'svod', 1),
    ('apple-tv-store', 'Apple TV Store (iTunes)', 'store', 1),
    ('max', 'HBO Max', 'svod', 1),
    ('peacock', 'Peacock', 'svod', 1),
    ('prime-video', 'Prime Video', 'svod', 1),
    ('mubi', 'MUBI', 'svod', 0),
    ('bfi-player-classics', 'BFI Player Classics', 'svod', 0);

CREATE TABLE service_provider (
    tmdb_provider_id INTEGER PRIMARY KEY,
    service_slug TEXT NOT NULL REFERENCES movie_service(slug),
    label TEXT NOT NULL
);
-- Amazon-channel ids (1825, 201, 287) and GB BFI Player (224) deliberately excluded.
INSERT INTO service_provider (tmdb_provider_id, service_slug, label) VALUES
    (258, 'criterion', 'Criterion Channel'),
    (350, 'apple-tv-plus', 'Apple TV+'),
    (2, 'apple-tv-store', 'Apple TV'),
    (1899, 'max', 'HBO Max'),
    (386, 'peacock', 'Peacock Premium'),
    (387, 'peacock', 'Peacock Premium Plus'),
    (9, 'prime-video', 'Amazon Prime Video'),
    (11, 'mubi', 'MUBI');

-- Rebuild films with a NOT NULL guid; existing rows get a SQL-generated UUIDv4.
CREATE TABLE films_new (
    id INTEGER PRIMARY KEY,
    guid TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    year INTEGER,
    director TEXT,
    key TEXT NOT NULL UNIQUE
);
INSERT INTO films_new (id, guid, title, year, director, key)
SELECT id,
       lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' ||
             substr(hex(randomblob(2)), 2) || '-' ||
             substr('89ab', (abs(random()) % 4) + 1, 1) || substr(hex(randomblob(2)), 2) ||
             '-' || hex(randomblob(6))),
       title, year, director, key
FROM films;
DROP TABLE films;
ALTER TABLE films_new RENAME TO films;

CREATE TABLE external_ids (
    film_id INTEGER NOT NULL REFERENCES films(id),
    authority TEXT NOT NULL,
    value TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    PRIMARY KEY (film_id, authority),
    UNIQUE (authority, value)
);
-- Criterion's native id is its film URL. OR IGNORE: a duplicate URL should skip
-- one row, not abort the whole migration.
INSERT OR IGNORE INTO external_ids (film_id, authority, value, first_seen)
SELECT film_id, 'criterion', url, first_seen FROM listings WHERE source = 'criterion';

-- Rebuild listings so source becomes a foreign key into the registry.
CREATE TABLE listings_new (
    film_id INTEGER NOT NULL REFERENCES films(id),
    source TEXT NOT NULL REFERENCES movie_service(slug),
    url TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    leaving_date TEXT,
    PRIMARY KEY (film_id, source)
);
INSERT INTO listings_new SELECT film_id, source, url, first_seen, last_seen, leaving_date FROM listings;
DROP TABLE listings;
ALTER TABLE listings_new RENAME TO listings;
CREATE INDEX listings_source_last_seen ON listings(source, last_seen);

INSERT INTO schema_version (version) VALUES (3);
```

- [ ] **Step 4: Add guid generation to the two film INSERTs**

In `src/movie_brain/infrastructure/database.py`, add `import uuid` after `import sqlite3`. Then in `upsert_film` change the INSERT to:

```python
            c.execute(
                "INSERT INTO films (guid, title, year, director, key) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET title=excluded.title, year=excluded.year, director=excluded.director",
                (str(uuid.uuid4()), film.title, film.year, film.director, film.key),
            )
```

And in `record_catalog` change the films INSERT to:

```python
                c.execute(
                    "INSERT INTO films (guid, title, year, director, key) VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET title=excluded.title, year=excluded.year, "
                    "director=excluded.director",
                    (str(uuid.uuid4()), film.title, film.year, film.director, film.key),
                )
```

Guids stay immutable because neither `ON CONFLICT` clause touches `guid` (a fresh uuid is generated and discarded on conflict — that's fine).

- [ ] **Step 5: Run the new tests to verify they pass**

Run: `uv run pytest tests/unit/test_database.py -k "migration_003 or guid_is_stable" -v`
Expected: 4 PASS.

- [ ] **Step 6: Run the whole unit file**

Run: `uv run pytest tests/unit/test_database.py -v`
Expected: all PASS (pre-existing tests unaffected — the schema change is additive from their point of view).

- [ ] **Step 7: Commit**

```bash
git add migrations/003_multi_service.sql src/movie_brain/infrastructure/database.py tests/unit/test_database.py
git commit -m "GUID identity + services registry: migration 003 and guid generation on insert

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: External-id and registry access on Repository

**Files:**
- Modify: `src/movie_brain/infrastructure/database.py` (`record_catalog`; new methods after the `# meta` section)
- Test: `tests/unit/test_database.py`

**Interfaces:**
- Consumes: Task 1's `external_ids` and `movie_service` tables.
- Produces (used by Phase 2/3 adapters and tests):
  - `Repository.set_external_id(film_id: int, authority: str, value: str, seen: date) -> None`
  - `Repository.external_ids_for(film_id: int) -> dict[str, str]`
  - `Repository.services() -> list[dict[str, object]]` (keys: slug, name, kind, subscribed, region)
  - `record_catalog` now also upserts each film's `criterion` external id.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_database.py` (add `import pytest` at the top):

```python
def test_external_id_roundtrip_update_and_uniqueness(repo):
    a = repo.upsert_film(TRIO)
    b = repo.upsert_film(QUARTET)
    repo.set_external_id(a, "tmdb", "603", D1)
    repo.set_external_id(a, "tmdb", "604", D2)  # same film+authority: value updates
    repo.set_external_id(a, "imdb", "tt0042980", D2)
    assert repo.external_ids_for(a) == {"tmdb": "604", "imdb": "tt0042980"}
    assert repo.external_ids_for(b) == {}
    with pytest.raises(sqlite3.IntegrityError):  # two films can't claim one external id
        repo.set_external_id(b, "tmdb", "604", D2)


def test_record_catalog_records_criterion_external_ids(repo):
    repo.record_catalog("criterion", [TRIO], D1)
    fid = repo.film_id_by_key("trio (1950)")
    assert fid is not None
    assert repo.external_ids_for(fid) == {"criterion": "https://c/trio"}


def test_services_registry_accessor(repo):
    services = {s["slug"]: s for s in repo.services()}
    assert len(services) == 8
    assert services["criterion"]["subscribed"] == 1
    assert services["mubi"]["subscribed"] == 0
    assert services["apple-tv-store"]["kind"] == "store"
    assert services["prime-video"]["region"] == "US"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/unit/test_database.py -k "external_id or services_registry" -v`
Expected: FAIL — `AttributeError: 'Repository' object has no attribute 'set_external_id'` (and the record_catalog test fails on the empty dict).

- [ ] **Step 3: Implement**

In `src/movie_brain/infrastructure/database.py`, inside `record_catalog`'s per-film loop, after the listings INSERT add:

```python
                c.execute(
                    "INSERT INTO external_ids (film_id, authority, value, first_seen) "
                    "VALUES ((SELECT id FROM films WHERE key = ?), ?, ?, ?) "
                    "ON CONFLICT(film_id, authority) DO UPDATE SET value=excluded.value",
                    (film.key, source, film.url, day),
                )
```

Add a new section before `# meta`:

```python
    # external ids / services ------------------------------------------
    def set_external_id(self, film_id: int, authority: str, value: str, seen: date) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO external_ids (film_id, authority, value, first_seen) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(film_id, authority) DO UPDATE SET value=excluded.value",
                (film_id, authority, value, seen.isoformat()),
            )

    def external_ids_for(self, film_id: int) -> dict[str, str]:
        with self._conn() as c:
            rows = c.execute("SELECT authority, value FROM external_ids WHERE film_id = ?", (film_id,)).fetchall()
            return {str(r["authority"]): str(r["value"]) for r in rows}

    def services(self) -> list[dict[str, object]]:
        with self._conn() as c:
            rows = c.execute("SELECT slug, name, kind, subscribed, region FROM movie_service ORDER BY slug").fetchall()
            return [dict(r) for r in rows]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_database.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/infrastructure/database.py tests/unit/test_database.py
git commit -m "External-id map and service registry accessors; sync records criterion ids

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Remove purge_departed — films are immutable

**Files:**
- Modify: `tests/features/sync.feature` (scenarios at lines 53–59 and 69–75)
- Modify: `tests/step_defs/test_sync.py` (remove the `film_gone` step, lines 251–254)
- Modify: `tests/unit/test_database.py` (two purge tests removed, one rewritten)
- Modify: `src/movie_brain/application/sync.py` (remove lines 84–86)
- Modify: `src/movie_brain/infrastructure/database.py` (delete `purge_departed`, lines 103–124)

**Interfaces:**
- Consumes: nothing new.
- Produces: `Repository` no longer has `purge_departed`; `sync()` never deletes. The BDD step `'"{title}" is still in the database'` (already defined) is the keeper assertion.

- [ ] **Step 1: Rewrite the feature scenarios (the failing test)**

In `tests/features/sync.feature`, replace the scenario `A departed unrated film is purged after the grace period` (lines 53–59) with:

```gherkin
  Scenario: A departed unrated film is kept in the database but hidden
    Given the repository already holds "Trio (1950)" and "Quartet (1948)" walked 9 days ago
    And the Criterion catalog has films "Trio (1950)"
    And OMDb knows every film
    When I sync
    Then "Quartet (1948)" is still in the database
    And 1 films are current
```

Delete the scenario `A recently departed unrated film survives the grace period` (lines 69–75) — with no grace period the 2-day case is now identical to the 9-day case above. Keep `A departed rated film is kept and shown as departed` unchanged.

- [ ] **Step 2: Run the feature to verify the new scenario fails**

Run: `uv run pytest tests/step_defs/test_sync.py -k "kept_in_the_database" -v`
Expected: FAIL — sync still calls `purge_departed`, so Quartet (9 days stale, unrated) is deleted and the `is still in the database` assertion trips.

- [ ] **Step 3: Remove the purge call from sync**

In `src/movie_brain/application/sync.py`, delete these lines (84–86):

```python
        purged = repo.purge_departed(SOURCE, today)
        if purged:
            log(f"purged {purged} unrated films no longer on the channel")
```

- [ ] **Step 4: Run the sync suite to verify it passes**

Run: `uv run pytest tests/step_defs/test_sync.py -v`
Expected: all PASS.

- [ ] **Step 5: Delete the method and retire its unit tests**

- In `src/movie_brain/infrastructure/database.py`, delete the whole `purge_departed` method (lines 103–124) and the now-unused `timedelta`? — **no**: `timedelta` is still used by `films_needing_lookup`; leave imports alone.
- In `tests/step_defs/test_sync.py`, delete the `film_gone` step function (lines 251–254, `'"{title}" is gone from the database'`) — no scenario uses it anymore.
- In `tests/unit/test_database.py`:
  - Delete `test_purge_departed_removes_unrated_films_past_grace` and `test_purge_departed_never_touches_rated_films`.
  - Replace `test_unrated_departed_film_is_hidden_but_kept_inside_grace` with:

```python
def test_unrated_departed_film_is_kept_but_hidden(repo):
    a = repo.upsert_film(TRIO)
    b = repo.upsert_film(QUARTET)
    repo.record_listing(a, "criterion", TRIO.url, D1)  # 18 days stale — past the old grace window
    repo.record_listing(b, "criterion", QUARTET.url, D2)
    assert [v.title for v in repo.list_views("criterion")] == ["Quartet"]
    assert repo.film_id_by_key("trio (1950)") == a
```

- [ ] **Step 6: Run unit + BDD suites**

Run: `uv run pytest tests/unit tests/step_defs -v`
Expected: all PASS; grep proves the concept is gone: `grep -rn purge_departed src tests` → no matches.

- [ ] **Step 7: Commit**

```bash
git add src/movie_brain/application/sync.py src/movie_brain/infrastructure/database.py tests/features/sync.feature tests/step_defs/test_sync.py tests/unit/test_database.py
git commit -m "Films are immutable: remove purge_departed; departed is display state only

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Documentation + full gate + live-DB rehearsal

**Files:**
- Modify: `CLAUDE.md` (Sync flow step 3; Rules bullets 1–2; add registry rule)
- Modify: `docs/multiple-movie-services.md` (Phase 1 row + phase 1 description → done)
- Modify: `docs/superpowers/specs/2026-08-23-phase1-schema-redesign-design.md` (Status line)

**Interfaces:** none — docs and verification only.

- [ ] **Step 1: Update CLAUDE.md**

In the Sync flow section, replace step 3 with:

```markdown
3. `record_catalog` upserts films (generating a `guid` for new ones), records each film's
   `criterion` external id, and bumps listings `last_seen`; `set_leaving` maps
   "Leaving <date>" categories.
```

In Rules, replace the first two bullets (`Film identity = film_key…` and `"Current" = …purged completely by purge_departed`) with:

```markdown
- Film identity = `films.guid` (generated UUIDv4, immutable once assigned); the integer `id`
  is an internal join key that must never leak as identity. `film_key(title, year)` is a
  matching aid and the Criterion upsert conflict target — not the identity.
- Films are immutable: collectors never delete. "Current" = latest `last_seen` per source;
  "departed" is a pure display state. Unrated departed films stay in the DB, hidden by the
  current-or-rated view filter; rated departed films are shown as departed.
- `movie_service` is the service registry (slug PK; kind `svod`|`store`; `subscribed`/`region`
  are data). `service_provider` groups TMDB provider ids per service; `external_ids` maps
  films to per-authority native ids with `UNIQUE(authority, value)` as the dedup guard.
```

- [ ] **Step 2: Mark Phase 1 done in the roadmap**

In `docs/multiple-movie-services.md`: in the phase table change row 1's Phase cell to `Schema redesign: GUID identity + services model — **done**`, and prefix the numbered item 1 description with `**Done (2026-08-23).**`. In the spec file, change the Status line to `**Date:** 2026-08-23 · **Status:** implemented`.

- [ ] **Step 3: Full gate**

```bash
uv run pytest
uv run ruff check .
uv run mypy
```
Expected: all green (Playwright dashboard tests included — they prove the zero-visible-change claim).

- [ ] **Step 4: Rehearse the migration against a copy of the live DB**

```bash
cp ~/.config/movie-brain/movie-brain.db /private/tmp/claude-501/-Users-jayers-code-movie-brain/68a6063e-cf1f-4379-a407-2f4671f70950/scratchpad/live-copy.db
uv run python -c "
from pathlib import Path
import sqlite3
from movie_brain.infrastructure.database import init_db
p = Path('/private/tmp/claude-501/-Users-jayers-code-movie-brain/68a6063e-cf1f-4379-a407-2f4671f70950/scratchpad/live-copy.db')
before = sqlite3.connect(p).execute('SELECT COUNT(*) FROM films').fetchone()[0]
init_db(p)
c = sqlite3.connect(p)
after, guids, ext = (c.execute(q).fetchone()[0] for q in (
    'SELECT COUNT(*) FROM films',
    'SELECT COUNT(*) FROM films WHERE guid IS NOT NULL',
    \"SELECT COUNT(*) FROM external_ids WHERE authority='criterion'\",
))
print(f'films {before}->{after}, guids {guids}, criterion ids {ext}')
assert before == after == guids
"
```
Expected: film count unchanged, every film has a guid, criterion external ids ≈ film count. This is a rehearsal only — the real DB migrates itself on the next command the user runs.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md docs/multiple-movie-services.md docs/superpowers/specs/2026-08-23-phase1-schema-redesign-design.md
git commit -m "Docs: immutable-films and GUID-identity rules; Phase 1 marked done

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

- [ ] **Step 6: Finish the branch**

Use the superpowers:finishing-a-development-branch skill to decide merge/PR with the user.
