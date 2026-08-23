# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# movie-brain

Personal film brain: Criterion Channel listings + OMDb ratings + my 0–10 ratings in SQLite, served by a local Flask dashboard. Successor to criterion-ratings; more `listings.source` values (Apple Movies, …) may be added later.

**Roadmap:** a phased multi-service expansion is planned — before feature work, read `docs/multiple-movie-services.md` (Implementation phases + Data model decisions: GUID identity, immutable films/no purge, Metacritic top-N dial) and `docs/vision.md`. Discovery spike scripts live in `scripts/discovery/`. Sibling project to converge with: yt-brain (see `docs/cinema-companion.md`).

## Commands

```bash
uv run movie-brain sync [--full|--ratings-only]      # refresh catalog + OMDb ratings; nightly sync now also matches films to TMDB and refreshes weekly availability
uv run movie-brain metacritic crawl [--pages 10]     # extend the raw browse-page archive (polite, checkpointed)
uv run movie-brain metacritic match                  # offline: match archive → films, report coverage
uv run movie-brain dashboard [--port 5556]
uv run movie-brain import-legacy [--from DIR]        # one-shot criterion-ratings import
uv run movie-brain export csv PATH
uv run movie-brain status

uv run pytest                                        # whole suite (~5s)
uv run pytest tests/step_defs/test_sync.py -k kept   # single test / scenario by keyword
uv run playwright install chromium                   # once, for tests/web/test_dashboard.py
uv run ruff check . && uv run mypy                   # lint + types (mypy also runs as a pre-commit hook)
```

## Architecture (hexagonal — dependencies point inward)

- `domain/` — pure, imports nothing else: `Film`, `FilmView`, `film_key`, `merge_yearless`, canned-filter predicates in `filters.py`.
- `application/` — use cases (`sync`, `ratings`, `export`, `legacy_import`) orchestrating through `Repository`; no SQL or HTTP here.
- `infrastructure/` — `config` (env / key file), SQLite `Repository` + `migrations/*.sql`, `criterion.py` (VHX API adapter), `omdb.py`, `tmdb.py` (watch-providers adapter).
- `web/` — Flask `create_app(repo)`, one template; ALL filter/sort logic is client-side vanilla JS in `static/app.js` (virtual-scrolled table, state encoded in the URL).
- `cli.py` — Typer entry point wiring config → `Repository` → use cases.

### Sync flow (`application/sync.py`)

1. Fetch browse-page token, then the cheap check: reuse the stored catalog if the last full walk is ≤7 days old, the API `total` equals the `films_raw_total` meta, and every page-1 key matches; otherwise full walk.
2. A full walk runs `merge_yearless()` first — Criterion publishes duplicate year-less pages (`…/film-title-1`) that must fold into their titled twin, or dupes resurrect every walk.
3. `record_catalog` upserts films (generating a `guid` for new ones), records each film's
   `criterion` external id, and bumps listings `last_seen`; `set_leaving` maps
   "Leaving <date>" categories.
4. OMDb loop over `films_needing_lookup`. Tripwires: a catalog failure leaves the DB untouched; OMDb quota exhaustion or 5 consecutive failures stops lookups but keeps progress (free tier is 1,000/day — the backlog drains across daily runs).
5. TMDB step (token at `<config_dir>/tmdb-read-token.txt`, else skipped): one-shot match of new films (misses → `match_review`, never retried by sync), then a weekly full US watch-providers refresh writing `listings` rows per service (never `criterion`); own tripwires — TMDB failures never affect exit code or other steps.

## Rules

- Film identity = `films.guid` (generated UUIDv4, immutable once assigned); the integer `id`
  is an internal join key that must never leak as identity. `film_key(title, year)` is a
  matching aid and the Criterion upsert conflict target — not the identity.
- Films are immutable: collectors never delete. "Current" = latest `last_seen` per source;
  "departed" is a pure display state. Unrated departed films stay in the DB, hidden by the
  current-or-rated view filter; rated departed films are shown as departed.
- `movie_service` is the service registry (slug PK; kind `svod`|`store`; `subscribed`/`region`
  are data). `service_provider` groups TMDB provider ids per service; `external_ids` maps
  films to per-authority native ids with `UNIQUE(authority, value)` as the dedup guard.
- Metascores are scraped-first: the FilmView `metacritic` value COALESCEs the scraped
  `metacritic` table (joined via `external_ids` authority `metacritic` = slug) over
  `omdb.metacritic`. The raw page archive under `<config_dir>/metacritic/` is the crawl
  checkpoint — archived pages are never re-fetched; parsing reads only the archive. Match
  anomalies land in `match_review` (never deleted, never blocking); no scraping in sync.
- Availability lives in `listings`: TMDB writes svod sources from `flatrate` only (plus
  `apple-tv-store` from rent/buy provider 2); Amazon-channel ids are excluded; the weekly
  refresh is gated by meta `tmdb_providers_refreshed_at`.
- Canned-filter thresholds and chip names live ONLY in `domain/filters.py`; JS reads thresholds from `/api/config`. Keep `CHIP_PREDICATES` in `app.js` and the chip buttons in `index.html` in lockstep with `_PREDICATES`.
- Schema change → new `migrations/NNN_*.sql` that also inserts its `schema_version` row; never edit an applied migration. Wrap risky multi-statement migrations in BEGIN/COMMIT (executescript is not atomic); pre-migration backups are the last-resort net, not a license to skip it.
- Tests mirror the layers: `tests/unit` (domain + infrastructure), `tests/features` + `tests/step_defs` (pytest-bdd application scenarios, HTTP mocked with `responses`), `tests/web` (Flask client API tests + Playwright against a seeded live server).

## Data

DB: `~/.config/movie-brain/movie-brain.db` (`MOVIE_BRAIN_CONFIG_DIR` overrides the directory). OMDb key: `OMDB_API_KEY` or `<config_dir>/omdb-api-key.txt`. TMDB token: `MOVIE_BRAIN_TMDB_TOKEN` or `<config_dir>/tmdb-read-token.txt`. Sync log: `<config_dir>/sync.log`. Daily 3 AM launchd job: `scripts/install-launch-agent.sh`.

Pre-migration backups land in `<config_dir>/backups/` automatically whenever `init_db` is
about to apply a new migration — each file is the rollback point for one schema change.

Metacritic archive: `<config_dir>/metacritic/pages/page-NNNN.html` + `fetch-log.jsonl`.
