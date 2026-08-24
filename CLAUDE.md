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
uv run movie-brain metacritic dial [N]                # show/set the Mode-B top-N; promotion runs in nightly sync
uv run movie-brain owned import                       # AppleScript export of the Apple TV library → mark/create owned films (macOS, never in sync)
uv run movie-brain dashboard [--port 5556]
uv run movie-brain import-legacy [--from DIR]        # one-shot criterion-ratings import
uv run movie-brain export csv PATH
uv run movie-brain status

uv run pytest                                        # whole suite (~5s)
uv run pytest tests/step_defs/test_sync.py -k kept   # single test / scenario by keyword
uv run playwright install chromium                   # once, for tests/web/test_dashboard.py
uv run ruff check . && uv run mypy                   # lint + types (mypy also runs as a pre-commit hook)
uv run python scripts/matching_benchmark.py [--assert-dominance]  # matcher regression gate: ground truth + archive replays
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
4. Offline Mode-B promotion (`promote_top_n`, meta `mc_top_n` — default 100): `match_archive` runs first as the dedup guard (staged Metacritic titles claimed by an existing film are skipped), then the remaining top-N staged titles become real films (generated guid, `clean_title`, MC year, director `NULL`); key-conflict and slug-conflict anomalies queue to `match_review` (never overwrite); archive shortfall (fewer staged titles than N) is logged with a crawl-more-pages hint; own tripwire — never affects exit code or later steps; no scraping (archive-only, offline).
5. OMDb loop over `films_needing_lookup` plus `films_needing_lookup_discovery` (Mode-B films with no Criterion listing, queued after criterion-current films; their `Film.url` is the Metacritic movie URL). Tripwires: a catalog failure leaves the DB untouched; OMDb quota exhaustion or 5 consecutive failures stops lookups but keeps progress (paid OMDb plan — quota exhaustion is a safety net, not an expected path).
6. TMDB step (token at `<config_dir>/tmdb-read-token.txt`, else skipped): one-shot match of new films (misses → `match_review`, never retried by sync), then a nightly watchlist provider pass (~50 films, every sync, never touches the weekly stamp), then a weekly full US watch-providers refresh writing `listings` rows per service (never `criterion`), skipping films already checked that day, stamp written only on completion; own tripwires — TMDB failures never affect exit code or other steps. Listing writes (both the Criterion walk and TMDB provider passes) record `availability_transitions` against the pre-batch currency frontier — an insert or a stale-row reappearance fires an event, a current-row re-upsert stays quiet; a film's first-ever TMDB provider check writes listings WITHOUT a transition event (baseline, not arrival) — later checks fire transitions as normal; store-kind sources are recorded but never surfaced. If ≥1 watchlist film transitioned today, one summary macOS notification fires at the end of sync (`infrastructure/notify.py`, injected as `notifier`; failures never affect exit code).

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
- Availability transitions are append-only events recorded at listing-write time against the
  pre-batch currency frontier; `watchlist` is user-response data (drawer toggle is the only
  writer). "Current" for TMDB-fed sources = `last_seen >= tmdb_providers_refreshed_at`
  (MAX fallback when no stamp; criterion keeps MAX(last_seen)).
- `_VIEW_SQL` drives from `films` with a LEFT JOIN on the criterion listing (not an inner join) so Mode-B films with no Criterion listing are visible; `list_views` keeps Criterion parity by filtering to no-listing OR current OR rated (unrated departed still hidden). `FilmView.url` is nullable (populated only from a Criterion listing; Mode-B/discovery films are always `None` here — their link is `FilmView.metacritic_url`, set at match/promotion time) and `FilmView.criterion` is a bool. `summary()` stays criterion-scoped plus a `discovery` count. The dashboard's scope toggle (client-side URL state, default `criterion`; `all` reveals discovery films) is app.js-only — the server always returns the full view. `export csv` writes `list_views` unfiltered, so it also includes discovery films (empty `url` cell) — this is intended, not a bug.
- Canned-filter thresholds and chip names live ONLY in `domain/filters.py`; JS reads thresholds from `/api/config`. Keep `CHIP_PREDICATES` in `app.js` and the chip buttons in `index.html` in lockstep with `_PREDICATES`.
- `owned` is possession data on the watchlist pattern: `owned import` is the only writer, rows
  are permanent (never unmarked), and there's no `listings`/`availability_transitions`
  interaction. Ambiguous matches (candidate ties) and big year disagreements (`year-drift`)
  queue to `match_review` under authority `apple-tv`, never guessed and never twinned;
  unmatched owned titles become real films (generated guid) that the existing discovery
  machinery (OMDb/TMDB) enriches like any other film.
- Year truth-holder: `films.year` is the original release year and importers never edit it on
  matched films. Precedence when sources disagree: Criterion/TMDB > a year embedded in an
  Apple title (`parse_apple_title`) > Apple's track year field (remaster-prone) > Metacritic
  year (US-re-release-prone). Director-confirmed matching via the iTunes Search API is the
  planned upgrade (roadmap parallel track).
- Matching is one evidence-scored core: `domain/matching.py`'s `match_candidates` (three-level
  candidate index, source-aware year policy, director/runtime/popularity evidence, `Arbiter`
  hook) is the only matcher; `match_film` (Metacritic), `match_owned` (Apple), and
  `pick_tmdb_match` (TMDB) are thin per-source policy wrappers over it — never re-implement
  matching logic in a wrapper. `scripts/matching_benchmark.py` (ground truth + Metacritic/Apple
  archive replays, `--assert-dominance` gate) is the regression check before touching matching.
- Schema change → new `migrations/NNN_*.sql` that also inserts its `schema_version` row; never edit an applied migration. Wrap risky multi-statement migrations in BEGIN/COMMIT (executescript is not atomic); pre-migration backups are the last-resort net, not a license to skip it.
- Tests mirror the layers: `tests/unit` (domain + infrastructure), `tests/features` + `tests/step_defs` (pytest-bdd application scenarios, HTTP mocked with `responses`), `tests/web` (Flask client API tests + Playwright against a seeded live server).

## Data

DB: `~/.config/movie-brain/movie-brain.db` (`MOVIE_BRAIN_CONFIG_DIR` overrides the directory). OMDb key: `OMDB_API_KEY` or `<config_dir>/omdb-api-key.txt`. TMDB token: `MOVIE_BRAIN_TMDB_TOKEN` or `<config_dir>/tmdb-read-token.txt`. Sync log: `<config_dir>/sync.log`. Daily 3 AM launchd job: `scripts/install-launch-agent.sh`.

Pre-migration backups land in `<config_dir>/backups/` automatically whenever `init_db` is
about to apply a new migration — each file is the rollback point for one schema change.

Metacritic archive: `<config_dir>/metacritic/pages/page-NNNN.html` + `fetch-log.jsonl`.

Apple TV archive: `<config_dir>/appletv/owned-<YYYY-MM-DD>.txt` (raw osascript export,
archived before parsing — one file per `owned import` run). 3-column since export v2 (adds
runtime seconds); old 2-column archives still replay.

On first use, macOS asks once to allow notifications from osascript; until approved, the
nightly sync's watchlist notification won't display.
