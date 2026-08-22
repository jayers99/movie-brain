# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# movie-brain

Personal film brain: Criterion Channel listings + OMDb ratings + my 0–10 ratings in SQLite, served by a local Flask dashboard. Successor to criterion-ratings; more `listings.source` values (Apple Movies, …) may be added later.

## Commands

```bash
uv run movie-brain sync [--full|--ratings-only]      # refresh catalog + OMDb ratings
uv run movie-brain dashboard [--port 5556]
uv run movie-brain import-legacy [--from DIR]        # one-shot criterion-ratings import
uv run movie-brain export csv PATH
uv run movie-brain status

uv run pytest                                        # whole suite (~5s)
uv run pytest tests/step_defs/test_sync.py -k grace  # single test / scenario by keyword
uv run playwright install chromium                   # once, for tests/web/test_dashboard.py
uv run ruff check . && uv run mypy                   # lint + types (mypy also runs as a pre-commit hook)
```

## Architecture (hexagonal — dependencies point inward)

- `domain/` — pure, imports nothing else: `Film`, `FilmView`, `film_key`, `merge_yearless`, canned-filter predicates in `filters.py`.
- `application/` — use cases (`sync`, `ratings`, `export`, `legacy_import`) orchestrating through `Repository`; no SQL or HTTP here.
- `infrastructure/` — `config` (env / key file), SQLite `Repository` + `migrations/*.sql`, `criterion.py` (VHX API adapter), `omdb.py`.
- `web/` — Flask `create_app(repo)`, one template; ALL filter/sort logic is client-side vanilla JS in `static/app.js` (virtual-scrolled table, state encoded in the URL).
- `cli.py` — Typer entry point wiring config → `Repository` → use cases.

### Sync flow (`application/sync.py`)

1. Fetch browse-page token, then the cheap check: reuse the stored catalog if the last full walk is ≤7 days old, the API `total` equals the `films_raw_total` meta, and every page-1 key matches; otherwise full walk.
2. A full walk runs `merge_yearless()` first — Criterion publishes duplicate year-less pages (`…/film-title-1`) that must fold into their titled twin, or dupes resurrect every walk.
3. `record_catalog` upserts films and bumps listings `last_seen`; `set_leaving` maps "Leaving <date>" categories; `purge_departed` then applies retention (below).
4. OMDb loop over `films_needing_lookup`. Tripwires: a catalog failure leaves the DB untouched; OMDb quota exhaustion or 5 consecutive failures stops lookups but keeps progress (free tier is 1,000/day — the backlog drains across daily runs).

## Rules

- Film identity = `film_key(title, year)`; never derive ids any other way.
- "Current" = latest `last_seen` per source. Retention: rated films are kept forever and shown as departed once off the channel; unrated films absent 7+ days are purged completely by `purge_departed`.
- Canned-filter thresholds and chip names live ONLY in `domain/filters.py`; JS reads thresholds from `/api/config`. Keep `CHIP_PREDICATES` in `app.js` and the chip buttons in `index.html` in lockstep with `_PREDICATES`.
- Schema change → new `migrations/NNN_*.sql` that also inserts its `schema_version` row; never edit an applied migration.
- Tests mirror the layers: `tests/unit` (domain + infrastructure), `tests/features` + `tests/step_defs` (pytest-bdd application scenarios, HTTP mocked with `responses`), `tests/web` (Flask client API tests + Playwright against a seeded live server).

## Data

DB: `~/.config/movie-brain/movie-brain.db` (`MOVIE_BRAIN_CONFIG_DIR` overrides the directory). OMDb key: `OMDB_API_KEY` or `<config_dir>/omdb-api-key.txt`. Sync log: `<config_dir>/sync.log`. Daily 3 AM launchd job: `scripts/install-launch-agent.sh`.
