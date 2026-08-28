# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# movie-brain

Personal film brain: Criterion Channel listings + OMDb ratings + my 0–10 ratings in SQLite, served by a local Flask dashboard. Successor to criterion-ratings; more `listings.source` values (Apple Movies, …) may be added later.

**Roadmap:** a phased multi-service expansion is planned — before feature work, read `docs/multiple-movie-services.md` (Implementation phases + Data model decisions: GUID identity, immutable films/no purge, Metacritic top-N dial) and `docs/vision.md`. Discovery spike scripts live in `scripts/discovery/`. Sibling project to converge with: yt-brain (see `docs/cinema-companion.md`).

## Commands

```bash
uv run movie-brain sync [--full|--ratings-only]      # refresh catalog + OMDb ratings; keys new films via the thumbprint resolver BEFORE the OMDb loop, which fetches by IMDb id only (unkeyed films are skipped, not title-searched); also refreshes weekly availability
uv run movie-brain metacritic crawl [--pages 10]     # extend the raw browse-page archive (polite, checkpointed)
uv run movie-brain metacritic match                  # offline: match archive → films, report coverage
uv run movie-brain metacritic dial [N]                # show/set the Mode-B top-N; promotion runs in nightly sync
uv run movie-brain owned import                       # AppleScript export of the Apple TV library → mark/create owned films (macOS, never in sync)
uv run movie-brain dashboard [--port 5556]
uv run movie-brain import-legacy [--from DIR]        # one-shot criterion-ratings import
uv run movie-brain export csv PATH
uv run movie-brain status
uv run movie-brain migrate [--apply]                  # the ONLY path that advances an existing DB's schema; dry run lists pending, --apply backs up + applies; fresh DBs bootstrap on open
uv run movie-brain rematch                            # one-shot repair: rematch TMDB misses, reconcile non-Criterion years (needs TMDB token; idempotent)

uv run movie-brain repair dupes [--apply] [--yes]     # audit norm-title + id-conflict dup groups; --apply merges TWIN groups only (--yes skips the per-group prompt)
uv run movie-brain repair links [--film ID] [--apply]  # re-validate stored TMDB links against TMDB's title/original_title/alternative titles (one call each); --film audits/clears one link unconditionally; --apply clears suspects
uv run movie-brain repair years [FILM_ID YEAR] [--apply]  # year worklist: open year-collisions + stale OMDb payloads; --apply marks stale rows for OMDb refetch; with FILM_ID YEAR, corrects one film's year
uv run movie-brain review list [--authority A] [--reason R]   # open match_review rows (filterable)
uv run movie-brain review resolve ID (--film X | --tmdb-id X | --create | --dismiss | --pick A|B|C | --tt X [--series] | --none) [--note]  # standing decision on one review row: link to a film, link a TMDB id, create the staged film, dismiss, key to an A/B/C candidate, key to an IMDb id, or verify unkeyed; a --tt TMDB knows only as TV (or forced with --series) is keyed by IMDb id alone and marked kind=series
uv run movie-brain review revisits                    # films the user flagged "needs revisit" in the drawer

uv run movie-brain repair twins [--apply] [--yes] [--limit N]  # retire raw `Title (YYYY)` films into their same-year twin (contract-checked); --limit = batch size
uv run movie-brain repair editions [--apply] [--yes] [--limit N]  # fold `Title (edition)` films into their same-year work (contract-checked); --limit = batch size
uv run movie-brain repair disagreements [--apply] [--yes] [--limit N]  # repair films whose OMDb imdbID ≠ TMDB imdb_id (eval group D): verified rows applied, proposed rows → A/B/C review; already-repaired films list as pending/review-open and --limit batches only the actionable ones
uv run movie-brain repair nomatch [--apply] [--yes] [--limit N]  # rerun open tmdb no-match films through the thumbprint resolver: matches keyed via record_tmdb_match, non-matches promoted IN PLACE to durable `no-match-reviewed` A/B/C rows (drain with `review resolve --pick/--tt/--none`); --limit batches actionable films only; candidates cached in <config_dir>/nomatch-cache.json.gz (eval fixture never written)
uv run movie-brain thumbprint backfill [--apply]      # copy owned/criterion/metacritic evidence into `claim` rows (pure copy, idempotent)
uv run movie-brain audit run [--no-tmdb]              # read-only consistency checks → audit_flags (+ one-time TMDB facts cache); prints tally + top suspects
uv run movie-brain audit verdicts [--verdict V]       # append-only human verdict history (pattern-analysis export)

uv run pytest                                        # whole suite (~5s)
uv run pytest tests/step_defs/test_sync.py -k kept   # single test / scenario by keyword
uv run playwright install chromium                   # once, for tests/web/test_dashboard.py
uv run ruff check . && uv run mypy                   # lint + types (mypy also runs as a pre-commit hook)
uv run python scripts/matching_benchmark.py [--assert-dominance]  # matcher regression gate: ground truth + archive replays
uv run python scripts/thumbprint_benchmark.py --assert  # thumbprint resolver gate (offline fixture): 0 wrong on every row + auto ≥ 90% on non-F-human rows
```

## Architecture (hexagonal — dependencies point inward)

- `domain/` — pure, imports nothing else: `Film`, `FilmView`, `film_key`, `merge_yearless`, canned-filter predicates in `filters.py`.
- `application/` — use cases (`sync`, `ratings`, `export`, `legacy_import`) orchestrating through `Repository`; no SQL or HTTP here.
- `infrastructure/` — `config` (env / key file), SQLite `Repository` + `migrations/*.sql`, `criterion.py` (VHX API adapter), `omdb.py`, `tmdb.py` (watch-providers adapter).
- `web/` — Flask `create_app(repo)`, one template; ALL filter/sort logic is client-side vanilla JS in `static/app.js` (virtual-scrolled table, state encoded in the URL).
- `cli.py` — Typer entry point wiring config → `Repository` → use cases.

### Sync flow

Seven-step contract (cheap check → merge_yearless → record_catalog + criterion claims → Mode-B promotion (resolve-first) + metacritic claims → keying (`key_films`) → OMDb by IMDb id only → TMDB providers/notifications) lives in `.claude/rules/sync-flow.md`, loaded when you work in `application/sync.py`, `availability.py`, or `metacritic.py`. Keying runs before the OMDb loop so a film keyed tonight gets its OMDb record by IMDb id tonight; a film with no IMDb id is skipped and counted in `SyncResult.omdb_unkeyed` rather than looked up by title.

## Rules

Path-scoped contracts in `.claude/rules/`: `matching.md` (the one evidence-scored matcher, wrappers, benchmark gate, rerelease/yearless rules), `audit.md` (audit_flags / tmdb_facts / audit_verdict), `thumbprint.md` (the work-identity resolver — live in sync, `owned import` and Mode-B promotion since T5 — its offline gate, the `claim` table now written by every ingester at ingest). They load when you touch the files they name — read them before changing matching or audit code.

- Film identity = `films.guid` (generated UUIDv4, immutable once assigned); the integer `id` is an internal join key that must never leak as identity. `film_key(title, year)` is a matching aid and the Criterion upsert conflict target — not the identity.
- Films are immutable: collectors never delete. "Current" = latest `last_seen` per source; "departed" is a pure display state. Unrated departed films stay in the DB, hidden by the current-or-rated view filter; rated departed films are shown as departed.
- `movie_service` is the service registry (slug PK; kind `svod`|`store`; `subscribed`/`region` are data). `service_provider` groups TMDB provider ids per service; `external_ids` maps films to per-authority native ids, PK `(film_id, authority, value)`; `UNIQUE(authority, value)` remains the dedup guard; tmdb/imdb are single per work by policy, claim authorities may repeat.
- Metascores are scraped-first: the FilmView `metacritic` value COALESCEs the scraped `metacritic` table (joined via `external_ids` authority `metacritic` = slug) over `omdb.metacritic`. The raw page archive under `<config_dir>/metacritic/` is the crawl checkpoint — archived pages are never re-fetched; parsing reads only the archive. Match anomalies land in `match_review` (never deleted, never blocking); no scraping in sync.
- Availability lives in `listings`: TMDB writes svod sources from `flatrate` only (plus `apple-tv-store` from rent/buy provider 2); Amazon-channel ids are excluded; the weekly refresh is gated by meta `tmdb_providers_refreshed_at`.
- Availability transitions are append-only events recorded at listing-write time against the pre-batch currency frontier; `watchlist` is user-response data (drawer toggle is the only writer). "Current" for TMDB-fed sources = `last_seen >= tmdb_providers_refreshed_at` (MAX fallback when no stamp; criterion keeps MAX(last_seen)).
- `_VIEW_SQL` drives from `films` with a LEFT JOIN on the criterion listing (not an inner join) so Mode-B films with no Criterion listing are visible; `list_views` keeps Criterion parity by filtering to no-listing OR current OR rated (unrated departed still hidden). `FilmView.url` is nullable (populated only from a Criterion listing; Mode-B/discovery films are always `None` here — their link is `FilmView.metacritic_url`, set at match/promotion time) and `FilmView.criterion` is a bool. `summary()` stays criterion-scoped plus a `discovery` count. The dashboard's scope toggle is app.js-only (client-side URL state; the server always returns the full view) and cycles three scopes: `reachable` (default, not encoded in the URL — current Criterion listing OR any subscribed service in `services` (svod or store) OR owned/rated/watchlisted), `criterion` (Criterion listing only), `all` (every film, including unreachable discovery films). `FilmView.services` entries are `{name, subscribed, kind}`; the drawer splits them into "Also streaming on:" (svod) and "Buy on:" (store, which also adds a "Find on CheapCharts" search link). `export csv` writes `list_views` unfiltered, so it also includes discovery films (empty `url` cell) — this is intended, not a bug.
- Canned-filter thresholds and chip names live ONLY in `domain/filters.py`; JS reads thresholds from `/api/config`. Keep `CHIP_PREDICATES` in `app.js` and the chip buttons in `index.html` in lockstep with `_PREDICATES`.
- `owned` is possession data on the watchlist pattern: `owned import` is the only writer, rows are permanent (never unmarked), and there's no `listings`/`availability_transitions` interaction. Ambiguous matches (candidate ties) and big year disagreements (`year-drift`) queue to `match_review` under authority `apple-tv`, never guessed and never twinned; unmatched owned titles become real films (generated guid) that the existing discovery machinery (OMDb/TMDB) enriches like any other film.
- Year truth-holder: `films.year` is the original release year and importers never edit it on matched films. Precedence when sources disagree: TMDB > a year embedded in an Apple title (`parse_apple_title`) > Criterion (±2) > Apple's track year field (remaster-prone) > Metacritic year (US-re-release-prone) (memo §6). Director-confirmed matching via the iTunes Search API is the planned upgrade (roadmap parallel track). Exception: a TMDB match on a commerce-created film (no Criterion listing) canonicalizes `films.year` to TMDB's original year and recomputes `key` (`record_tmdb_match`) — write-back never overwrites on a key collision, it queues a durable `year-collision` row in `match_review` as a merge candidate instead. Exactly one holder of the target key does not block: this film's OWN merged-away loser, whose dead key `update_film_year` retires in place (`key || ' #' || id`, since `films.key` is UNIQUE) so its survivor can adopt the year it was holding. Every other holder blocks, under its CANONICAL id — a loser merged into some *other* survivor reports that survivor, so the review names the live identity a human must reconcile. A TOMBSTONED holder blocks as itself: `tombstoned_keys()` is the guard that stops the ingesters re-creating it, and that guard IS the key.
- Dispositions: `film_disposition` is the identity ledger written ONLY by the repair verbs. `merged` aliases a losing identity to its survivor — `films_for_matching` returns the loser's title under the ultimate survivor's id (multi-hop chains resolve to the final survivor), so an ingester matching the old title lands on the canonical row; `tombstoned` hides the film and blocks re-creation. Every film read model carries the `_NOT_DISPOSED` guard. `merge_film` moves owned/watchlist/my_ratings/external_ids/listings/omdb/tmdb/availability_transitions rows to the survivor (survivor wins every conflict; when a one-row table's loser value is dropped it's recorded in the disposition note — full row for `my_ratings`/`watchlist`/`owned`, just the loser's `film_id` for `omdb`/`tmdb` since those payloads are large), resolves the loser's open `match_review` rows PLUS the survivor's open rows whose `value` names the loser (the `id-conflict`/`year-collision` counterpart — unrelated survivor rows stay open), and KEEPS the loser's `films` row — collectors never delete. A retired key stays retired: `update_film_year` renames a loser's key to `key || ' #' || id` only when that loser's OWN survivor adopts the year, and if the survivor later moves year again the freed key is simply left unowned (harmless; re-claiming it is a deferred edge).
- Review resolution: a resolved `match_review` row is a standing decision, not a closed ticket. `suppress_resolved`, `rebuild_no_match_queue`, and `queue_review_once` all consult resolved rows and never re-queue one — a `--dismiss` is permanent. Actions are per-authority: `--film` matches/merges into an existing film, `--tmdb-id` claims a TMDB id (tmdb `no-match`), `--create` promotes the staged Metacritic title or owned Apple title into a real film, and `--dismiss` closes the row. Resolution re-derives the conflict at resolution time rather than trusting the row's stored `value`. `no-match-reviewed` rows (written only by `repair nomatch`) accept `--pick/--tt/--none/--dismiss`; a resolved one is excluded from the no-match rebuild exactly like a resolved `no-match` row.
- `needs_revisit` is user-response data on the watchlist pattern: own table (film_id, marked_on, optional note), the dashboard drawer toggle / its API is the only UI writer, sync never touches it, and a filter chip surfaces it. It is cleared automatically when the film's review is resolved, when `repair years --apply` fixes the year, when the film is merged away (loser), or when it is tombstoned. `review revisits` prints the flagged worklist.
- Schema change → new `migrations/NNN_*.sql` that also inserts its `schema_version` row; never edit an applied migration. Wrap risky multi-statement migrations in BEGIN/COMMIT (executescript is not atomic); pre-migration backups are the last-resort net, not a license to skip it. No verb applies pending migrations implicitly: `movie-brain migrate --apply` is the one path that advances an existing DB, and `Repository(path)` raises `PendingMigrations` (CLI exits 2) when the DB is behind — a fresh DB with no `schema_version` table still bootstraps on open, since that's creation, not migration.
- Tests mirror the layers: `tests/unit` (domain + infrastructure), `tests/features` + `tests/step_defs` (pytest-bdd application scenarios, HTTP mocked with `responses`), `tests/web` (Flask client API tests + Playwright against a seeded live server).
## Data

DB: `~/.config/movie-brain/movie-brain.db` (`MOVIE_BRAIN_CONFIG_DIR` overrides the directory). OMDb key: `OMDB_API_KEY` or `<config_dir>/omdb-api-key.txt`. TMDB token: `MOVIE_BRAIN_TMDB_TOKEN` or `<config_dir>/tmdb-read-token.txt`. Sync log: `<config_dir>/sync.log`. Daily 3 AM launchd job: `scripts/install-launch-agent.sh`.

Pre-migration backups land in `<config_dir>/backups/` automatically whenever `migrate --apply` applies one — each file is the rollback point for one schema change.

Metacritic archive: `<config_dir>/metacritic/pages/page-NNNN.html` + `fetch-log.jsonl`.

Apple TV archive: `<config_dir>/appletv/owned-<YYYY-MM-DD>.txt` (raw osascript export, archived before parsing — one file per `owned import` run). 3-column since export v2 (adds runtime seconds); old 2-column archives still replay.

On first use, macOS asks once to allow notifications from osascript; until approved, the nightly sync's watchlist notification won't display.
