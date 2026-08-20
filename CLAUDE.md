# movie-brain

Personal film brain: Criterion Channel listings + OMDb ratings + my ratings in SQLite, with a local Flask dashboard. Successor to criterion-ratings; Apple Movies etc. may be added as further `listings.source` values.

## Commands
uv run movie-brain sync [--full|--ratings-only] · dashboard [--port 5556] · import-legacy [--from DIR] · export csv PATH · status

## Architecture (hexagonal)
- `domain/` — models (`Film`, `OmdbRating`, `FilmView`), canned-filter predicates. Imports nothing else.
- `application/` — sync, ratings, export, legacy_import. Talk to `Repository`.
- `infrastructure/` — config, SQLite `Repository` + `migrations/`, Criterion + OMDb HTTP adapters.
- `web/` — Flask `create_app(repo)`, one template, vanilla JS (`static/app.js`) does filter/sort client-side.

## Rules
- Canned-filter thresholds live ONLY in `domain/filters.py`; JS reads them from `/api/config`. Keep `CHIP_PREDICATES` in app.js in lockstep with `_PREDICATES`.
- Film identity = `film_key(title, year)`; never derive ids any other way.
- Never delete from `listings`; "current" = latest `last_seen` per source.
- New schema change → new `migrations/NNN_*.sql` that also inserts its `schema_version` row.
- Tests: `uv run pytest` (unit + pytest-bdd + Flask client + Playwright; `uv run playwright install chromium` once). Lint: `uv run ruff check . && uv run mypy`.

## Data
`~/.config/movie-brain/movie-brain.db` (override with `MOVIE_BRAIN_CONFIG_DIR`). OMDb key: `OMDB_API_KEY` or `<config_dir>/omdb-api-key.txt`. Logs: `<config_dir>/sync.log`.
