# Phase 1: Schema redesign — GUID identity + services model

**Date:** 2026-08-23 · **Status:** approved design, pre-implementation
**Parent plan:** [multiple-movie-services.md](../../multiple-movie-services.md) — Phase 1, the strangle root.
**Success bar:** migration applied, full suite + ruff + mypy green, dashboard and 3 AM sync
behaviorally identical (zero visible change).

## Decisions this spec implements (settled, dated — do not relitigate)

- **GUID identity (2026-08-24):** every movie gets our own generated GUID as its primary
  identity; per-service native ids hang off it one-to-many; `film_key(title, year)` demotes
  to a matching aid.
- **Immutable films (2026-08-24):** the film database is append-only; `purge_departed` is
  removed entirely. What churns is availability; "departed" is a display state, never a
  deletion. Collectors never delete.
- **Provider grouping (2026-08-24 spike):** one logical service maps to several TMDB
  provider ids; region is a real column.

Decisions made during this brainstorm:

- GUID is the **canonical public identity, not the SQL primary key**: `films` keeps its
  `INTEGER PRIMARY KEY` for joins; `guid TEXT NOT NULL UNIQUE` is what external ids, future
  merge/tombstone tooling, and exports reference. The integer id never leaves the app.
- External ids are namespaced by a free-standing **authority string** (`imdb`, `tmdb`,
  `metacritic`, `criterion`, …), not an FK into `movie_service` — id authorities like IMDb
  are not services and never need registry rows.
- The registry is **seeded with all 8 spike-verified services** and their TMDB provider ids,
  so Phase 3 needs no schema/data work and the messy real cases (HBO Max twins, BFI-via-
  Amazon-storefront) validate the model now.
- Migration style: **evolve in place** — keep table names `films`/`listings`; the reshape is
  semantic, not cosmetic.

## Schema — one new migration, `migrations/003_multi_service.sql`

Pure SQL, appended after 002; never edits applied migrations. `init_db` runs it on the next
launch of any command, so the live DB migrates automatically. Runs correctly on both a
populated v2 database and a fresh one (001→002→003).

### `films` (rebuilt)

```sql
CREATE TABLE films (
    id INTEGER PRIMARY KEY,
    guid TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    year INTEGER,
    director TEXT,
    key TEXT NOT NULL UNIQUE
);
```

Rebuild via create-new / copy / drop / rename (the Python `sqlite3` migration connection has
foreign-key enforcement off, so child tables keep pointing at `films` by name). Existing rows
backfill `guid` with a SQL-generated UUIDv4 using the `randomblob`/`hex` idiom:

```sql
lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' ||
      substr(hex(randomblob(2)), 2) || '-' ||
      substr('89ab', (abs(random()) % 4) + 1, 1) || substr(hex(randomblob(2)), 2) ||
      '-' || hex(randomblob(6)))
```

`key` keeps its `UNIQUE` constraint and remains the upsert conflict target for the Criterion
sync; it is a matching aid, no longer the identity.

### `movie_service` (new)

```sql
CREATE TABLE movie_service (
    slug TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('svod', 'store')),
    subscribed INTEGER NOT NULL DEFAULT 0,
    region TEXT NOT NULL DEFAULT 'US'
);
```

Seeds (all `region='US'`; subscribed = the six services in the Metacritic "my services"
browse URL; flags are data, flip anytime):

| slug | name | kind | subscribed |
|---|---|---|---|
| criterion | Criterion Channel | svod | 1 |
| apple-tv-plus | Apple TV+ | svod | 1 |
| apple-tv-store | Apple TV Store (iTunes) | store | 1 |
| max | HBO Max | svod | 1 |
| peacock | Peacock | svod | 1 |
| prime-video | Prime Video | svod | 1 |
| mubi | MUBI | svod | 0 |
| bfi-player-classics | BFI Player Classics | svod | 0 |

`criterion` matches the existing `listings.source` value exactly — no listings data rewrite.

### `service_provider` (new) — TMDB provider-id grouping

```sql
CREATE TABLE service_provider (
    tmdb_provider_id INTEGER PRIMARY KEY,
    service_slug TEXT NOT NULL REFERENCES movie_service(slug),
    label TEXT NOT NULL
);
```

One service ↔ many provider ids; a provider id belongs to exactly one service. Seeds from
the 2026-08-24 spike, minus the Amazon channels (decision below):

| provider id | label | service |
|---|---|---|
| 258 | Criterion Channel | criterion |
| 350 | Apple TV+ | apple-tv-plus |
| 2 | Apple TV | apple-tv-store |
| 1899 | HBO Max | max |
| 386 | Peacock Premium | peacock |
| 387 | Peacock Premium Plus | peacock |
| 9 | Amazon Prime Video | prime-video |
| 11 | MUBI | mubi |

(His Peacock tier via the Xfinity bundle is unknown — and irrelevant: both tiers share one
film catalog, so both ids fold into `peacock` and the distinction never surfaces.)

Deliberately NOT seeded:

- GB "BFI Player" (224) — a different service.
- **Amazon channel ids (decision 2026-08-23): HBO Max Amazon Channel (1825), MUBI Amazon
  Channel (201), and BFI Player Amazon Channel (287) are excluded** — his call; Amazon-billed
  channel storefronts are not how he subscribes. Accepted consequence, raised and decided:
  287 was TMDB's only US provider id for BFI Player Classics, so **TMDB availability for
  bfi-player-classics is knowingly invisible** (the registry row stays; revisit only if TMDB
  ever indexes the service directly).
- Amazon Video (Amazon's purchase/rental store) — never a candidate; see the availability
  rule below.

**Availability-kind rule (decision 2026-08-23, binds the Phase 3 adapter):** a `kind='svod'`
service counts only TMDB **`flatrate`** entries — films included with the subscription. TMDB
`rent`/`buy` arrays are read only for `kind='store'` services (Apple TV Store). Purchasable-
from-Amazon is never availability.

**Apple TV Store (provider 2) is the iTunes movie store** — verified in the 2026-08-24
spike (iTunes purchasability appears via it in the `buy` arrays). It stays seeded as the
future hook for importing his purchased films (owned-films spike, later phase).

### `external_ids` (new)

```sql
CREATE TABLE external_ids (
    film_id INTEGER NOT NULL REFERENCES films(id),
    authority TEXT NOT NULL,
    value TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    PRIMARY KEY (film_id, authority),
    UNIQUE (authority, value)
);
```

- `authority` is a plain string namespace: `criterion`, `imdb`, `tmdb`, `metacritic`, ….
- One id per authority per film (PK); no two films may claim the same external id
  (`UNIQUE(authority, value)`) — the dedup guard until Phase 8's tombstone/alias tooling.
- Migration backfills `authority='criterion'` rows from each Criterion listing's `url`
  (the URL is Criterion's native id per the parent plan), `first_seen` copied from the
  listing.

### `listings` (rebuilt)

Identical columns and index; `source` becomes `REFERENCES movie_service(slug)`. Availability
semantics preserved exactly: per-source `url`, `first_seen`/`last_seen`, `leaving_date`;
"current" = rows with the max `last_seen` per source.

## Code changes

### `infrastructure/database.py`

- **Pre-migration backups (decision 2026-08-23):** `init_db` snapshots the DB (SQLite
  backup API) to `<config_dir>/backups/<name>-v{applied}-{date}.db` before applying any
  pending migration to an existing schema. No backup on fresh DBs or ordinary runs — only
  at schema boundaries, kept indefinitely. Every later phase inherits this insurance.
- `upsert_film` and `record_catalog` supply `guid` (Python `uuid.uuid4()`) on insert; the
  `ON CONFLICT(key)` clause never updates `guid` — **guids are immutable once assigned**.
- `record_catalog` additionally upserts the film's `criterion` external id (`INSERT … ON
  CONFLICT(film_id, authority) DO UPDATE SET value=excluded.value`) so new films keep the
  identity map current.
- **`purge_departed` deleted.**
- New minimal methods (used by tests now, adapters in Phases 2–3):
  - `set_external_id(film_id, authority, value, seen) -> None`
  - `external_ids_for(film_id) -> dict[str, str]`
  - `services() -> list[sqlite3.Row]` (slug, name, kind, subscribed, region)

### `application/sync.py`

- Remove the `purge_departed` call and its log line. Nothing else changes: the cheap-check /
  full-walk logic, `merge_yearless`, leaving-dates, OMDb tripwires all stay as-is.

### Unchanged on purpose

`domain/` (models, filters), `web/` (app, template, `app.js`), `cli.py`, `omdb.py`,
`criterion.py`, export, legacy import. `FilmView` gains no fields — the API payload is
byte-identical, which is the zero-visible-change proof.

## Behavior change (intentional, invisible)

Removing `purge_departed` means unrated films that leave Criterion now **persist in the DB
forever** instead of being deleted after a 7-day grace. The dashboard is unaffected because
`list_views` already filters to current-listings-or-rated; departed unrated films exist but
are not displayed. This is the immutability decision working as intended.

## Testing

- **Migration (unit, `tests/unit/test_database.py`):** build a v2-shape DB with seeded films/
  listings/omdb/ratings, run `init_db`, assert: every film has a unique v4-format guid;
  criterion `external_ids` rows backfilled from listing URLs; listings/omdb/ratings data
  intact; registry has 8 services and exactly 8 provider rows (no Amazon-channel ids); fresh-DB path
  (001→003) also passes.
- **Identity (unit):** guid stable across repeated `record_catalog` runs; `UNIQUE(authority,
  value)` rejects a second film claiming an existing external id; `external_ids_for` /
  `set_external_id` round-trip.
- **Sync (BDD, `tests/features` + `step_defs`):** purge scenarios removed; new scenario —
  an unrated film absent past the old grace window remains in the DB and absent from
  `list_views`; rated-departed display unchanged.
- **Web:** existing API + Playwright tests pass unchanged.
- **Gate:** `uv run pytest`, `uv run ruff check .`, `uv run mypy` all green.

## Documentation

- **CLAUDE.md:** replace the retention rule ("unrated films absent 7+ days are purged") with
  the immutability rule (films are append-only; departed is a display state; collectors
  never delete); add the GUID-identity rule (guid = canonical identity, integer id internal,
  film_key = matching aid) and the registry/external-ids pointers.
- **docs/multiple-movie-services.md:** mark Phase 1 done when it lands.

## Out of scope (later phases)

Ownership/`kind`-on-the-join modeling (open spike), TMDB/Metacritic adapters, watchlist,
tombstones/aliases/dedup tooling (Phase 8), exposing guid or services in the UI or API,
renaming tables to `movies`/`availability`.
