# movie-brain — design

**Date:** 2026-08-19 · **Status:** approved design, pre-plan

## Purpose

Successor to `criterion-ratings`. A personal film brain: ingest film listings from sources (Criterion Channel first; Apple Movies etc. later), enrich with OMDb ratings, store everything in SQLite, and explore/rate through a local web dashboard. Replaces the Markdown report as the user interface; the web UI owns "my rating" entry.

Tech stack mirrors `yt-brain`: Python 3.12, `uv`, Typer + Rich CLI, pydantic, Flask, SQLite with auto-applied migrations, hexagonal layout, pytest-bdd + Playwright, ruff + mypy strict, hatchling, MIT.

## Scope

In:
- New repo `movie-brain`; criterion-ratings code ported (not shared).
- SQLite data store under `~/.config/movie-brain/`.
- One-shot `import-legacy` from the criterion-ratings data dir.
- Daily `sync` (launchd) with the same cheap/`--full`/`--ratings-only` modes and tripwires as today.
- Flask dashboard: filterable/sortable table, stacking canned filters, column filters, film detail drawer, inline rating entry.
- CSV export.

Out (explicitly):
- Markdown report and its rating-harvest loop (dropped).
- Apple Movies or any second source (schema leaves room; no code).
- Auth/multi-user; remote hosting. Local only.

## Repo layout

```
src/movie_brain/
  cli.py                        # typer app: sync, dashboard, import-legacy, export, status
  domain/models.py              # Film, Listing, OmdbRating, MyRating, FilmView
  domain/filters.py             # pure canned-filter predicates over FilmView
  application/sync.py           # catalog walk + OMDb fill (port of criterion-ratings cli.run)
  application/ratings.py        # rate / unrate
  application/export.py         # CSV
  application/legacy_import.py  # orchestrates import from old JSON files
  infrastructure/config.py      # config dir (~/.config/movie-brain, MOVIE_BRAIN_CONFIG_DIR), OMDb key (file or OMDB_API_KEY)
  infrastructure/database.py    # sqlite repository + migration runner
  infrastructure/criterion.py   # port of catalog.py (token, walk, leaving, snapshot delta check)
  infrastructure/omdb.py        # port of ratings.py client (quota/auth errors, year fallback)
  web/app.py                    # Flask factory, routes, JSON API
  web/templates/index.html
  web/static/app.js, app.css
migrations/0001_init.sql …
scripts/install-launch-agent.sh, launchd plist (runs `movie-brain sync` at 03:00)
tests/features/*.feature, tests/step_defs/, tests/web/ (Playwright), tests/unit/
```

Dependency direction: `web`/`cli` → `application` → `domain`; `infrastructure` implements what `application` needs. `domain` imports nothing from the other layers.

## Data model

SQLite, one DB at `<config_dir>/movie-brain.db`.

| table | columns | notes |
|---|---|---|
| `films` | `id PK`, `title`, `year NULL`, `director NULL`, `key UNIQUE` | `key` = `"<title.strip().lower()> (<year>)"`, identical to the legacy scheme, so legacy data maps 1:1. Future sources may add their own ID columns. |
| `listings` | `film_id FK`, `source`, `url`, `first_seen`, `last_seen`, `leaving_date NULL`; PK `(film_id, source)` | `source='criterion'` only for now. `first_seen` drives "recently added". Films absent from the latest full walk keep their row with a stale `last_seen`; nothing is deleted. |
| `omdb` | `film_id PK FK`, `found`, `imdb NULL`, `rt NULL`, `language NULL`, `looked_up`, `year_fallback`, `payload JSON NULL` | `payload` is the full raw OMDb response (the old `payloads/*.json`). |
| `my_ratings` | `film_id PK FK`, `score 0–10`, `rated_at` | `0` = not interested. Row absent = unrated. |
| `meta` | `key PK`, `value` | e.g. `films_fetched_at`, `schema_version`. |

`FilmView` (domain) is the joined read model the API serves:
`id, title, year, director, url, language, imdb, rt, found, pending, leaving_date, first_seen, my_rating`.
`pending` = no `omdb` row yet; `unmatched` = `omdb.found = 0`.

### Legacy import

`movie-brain import-legacy [--from DIR]` (default `~/.local/share/criterion-ratings`):
- `catalog.json` → `films` + `listings` (`first_seen` = `last_seen` = `films_fetched_at`; `leaving_date` from `leaving` map).
- `cache.json` → `omdb` (found/imdb/rt/language/looked_up/year_fallback).
- `payloads/<key>.json` → `omdb.payload` where key matches.
- `annotations.json` → `my_ratings` (`rated_at` = import date).
- Idempotent (upserts); prints counts per table and a list of legacy keys that matched nothing. Never writes to the legacy dir.

## Sync

`movie-brain sync [--full | --ratings-only]` — behaviour ported unchanged from criterion-ratings:
- cheap mode: page-1 delta check against the stored catalog; full walk only on change or `--full`.
- OMDb fill for films lacking an `omdb` row; quota/auth/5-consecutive-failure tripwires; catalog fetch failure leaves the DB untouched and exits 1.
- Each run updates `listings.last_seen` for films present, inserts new films with `first_seen = today`, refreshes `leaving_date`.
- No report file is written; the web UI reads the DB live.

## Web UI

Single page at `/`, served by `movie-brain dashboard [--port 5556]`.

**Header:** counts — films · rated · pending · unmatched · leaving soon · rated by me (from `/api/summary`).

**Canned filter chips** (toggle buttons, AND-stacked, "Clear" resets):
| chip | predicate |
|---|---|
| Leaving soon | `leaving_date` not null |
| Unrated by me | no `my_rating` |
| My ratings | `my_rating` ≥ 1 |
| Not interested | `my_rating` = 0 |
| Pending / unmatched | `pending` or not `found` |
| Top RT | `rt` ≥ 90 |
| Top IMDb | `imdb` ≥ 8.0 |
| Recently added | `first_seen` within last 30 days |

Predicates live in `domain/filters.py` (Python, unit-tested) **and** are mirrored in `app.js`; the Python copy is the reference and a test asserts the JS thresholds match (constants served in the page, not duplicated by hand).

**Table columns:** Title (link → Criterion URL, new tab) · Year · Director · Language · IMDb · RT · Leaving · My Rating · ⓘ.
- **Column filters** (second header row): substring inputs under Title and Director; multi-select under Language (split on `, `); min/max numeric pairs under Year, IMDb, RT. AND-combined with chips.
- **Sort:** click header cycles asc → desc → off; one active sort column; nulls always last. Default: IMDb desc, then title.
- **My Rating:** a 2-char text input per row. Type `0–10`, Enter/blur → `PUT /api/films/<id>/rating`; blank → unrate. Invalid input flashes red and reverts. Row and header counts update in place; no reload.
- **Drawer:** row click or ⓘ opens a right-side drawer: poster, title/year/director, plot, genre · runtime · rated · country · awards, cast, all OMDb rating sources, Criterion link, the same rating input, then a collapsible pretty-printed `<pre>` of the raw payload. `history.pushState` sets `?film=<id>`; Esc / backdrop / ✕ closes and pops. Loading `/?film=<id>` opens it on load.
- **URL state:** chips, column filters, sort and open film are mirrored into the query string and restored on load.
- **Rendering:** `/api/films` fetched once (~3k rows); filter/sort in memory; virtual-scrolled `<tbody>` as in yt-brain.

## API

| method + path | returns |
|---|---|
| `GET /api/films` | `[FilmView]` |
| `GET /api/films/<id>` | `FilmView` + `payload` (parsed JSON or null) |
| `PUT /api/films/<id>/rating` body `{"score": 0–10 \| null}` | updated `FilmView`; 400 on out-of-range/non-int; 404 unknown id |
| `GET /api/summary` | `{films, rated, pending, unmatched, leaving, mine}` |
| `GET /api/config` | `{canned_thresholds: {...}, recent_days: 30}` (so JS and Python share constants) |

## Error handling

- Sync: same tripwires as criterion-ratings (catalog failure → exit 1, DB unchanged; OMDb quota/auth/failures → partial fill, rerun next day). All writes in one transaction per phase.
- Web: API errors return JSON `{error}` with proper status; UI shows a non-blocking toast and reverts optimistic edits.
- DB missing/empty: dashboard still loads with an empty table and a hint to run `import-legacy` or `sync`.

## Testing

- `tests/features/`: `sync.feature` (cheap/full/ratings-only, tripwires), `ratings.feature`, `legacy_import.feature` (idempotency, counts, unmatched keys), `export.feature`.
- `tests/unit/`: `domain/filters.py` predicates; repository CRUD and migrations against a tmp DB; OMDb/Criterion adapters with `responses`.
- Flask test client: every API route incl. 400/404 paths.
- Playwright `tests/web/`: chips stack (Leaving + Unrated narrows), sort cycles with nulls last, column filter + chip combine, drawer opens/closes and restores URL, rating input round-trips and updates counts, invalid rating reverts.
- ruff + mypy strict in pre-commit, as in yt-brain.

## Open questions

None blocking. Deferred: second-source schema details; optional Markdown export if missed.
