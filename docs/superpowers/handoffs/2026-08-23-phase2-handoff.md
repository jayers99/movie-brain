# Handoff: Phase 1 done → Phase 2 (Metacritic Mode A)

**Written:** 2026-08-23, end of the Phase 1 session. Read this alongside
`docs/multiple-movie-services.md` (Implementation phases + dated decisions) and
`docs/vision.md` before any Phase 2 work.

## Status

- **Phase 1 (schema redesign) is fully landed**: merged to `main`, pushed (`f53127c`),
  and the **live DB has already migrated** to schema v3 (3,051 films, all with GUIDs;
  pre-migration snapshot at `~/.config/movie-brain/backups/movie-brain-v2-2026-08-23.db`).
  Full gate green: 138 tests (incl. Playwright), ruff, mypy.
- Spec: `docs/superpowers/specs/2026-08-23-phase1-schema-redesign-design.md` (status:
  implemented). Plan: `docs/superpowers/plans/2026-08-23-phase1-schema-redesign.md`.

## What Phase 2 builds on (new since Phase 1)

- **Identity:** `films.guid` (UUIDv4, immutable) is canonical; integer `id` is internal;
  `film_key` is a matching aid only.
- **`external_ids(film_id, authority, value, first_seen)`** — PK `(film_id, authority)`,
  `UNIQUE(authority, value)`. Phase 2 writes `authority='metacritic'` rows (value = the
  Metacritic slug, e.g. `seven-samurai-1954`). API: `Repository.set_external_id(film_id,
  authority, value, seen)` / `external_ids_for(film_id)`. A duplicate `(authority, value)`
  raises `sqlite3.IntegrityError` — in `record_catalog` this is caught/logged; a new
  adapter should do the same (log to review queue, never delete, never crash the sync).
- **`movie_service` / `service_provider`** seeded (8 services, 8 TMDB provider ids; no
  Amazon-channel ids — dated decision). `Repository.services()` reads the registry.
- **Films are immutable** — `purge_departed` no longer exists; collectors never delete;
  unmatched ids get logged, not dropped.
- **Pre-migration backups** are automatic in `init_db` (never overwrites an existing
  snapshot). Any Phase 2 migration (e.g. a `metacritic` table) inherits this; wrap risky
  multi-statement migrations in `BEGIN`/`COMMIT` (see CLAUDE.md migration rule).

## Phase 2 scope (from the roadmap — Mode A: enrich what we have)

Find the Metacritic record (metascore, slug) for **each film already in the DB** (= the
Criterion ~3,000). The movie↔Metacritic join goes live; metascores become first-class
instead of OMDb-payload backfill (`omdb.metacritic`, backfilled by migration 002, is the
current source — decide in the spec which is authoritative and how they coexist).
**Done when:** coverage % reported; unmatched films logged (not deleted, not blocking).

## Assets to reuse

- `scripts/discovery/match_spike2.py` — the 98%-accurate matcher rules (strip
  `(re-release)`/`(NNNN)` annotations, punctuation/case-insensitive compare, year ≤ MC+2).
  Built for Metacritic→TMDB, but the normalization rules are the reusable part.
- "Scrape contract — one-and-done" section of `docs/multiple-movie-services.md`: polite
  crawl parameters, raw-archive rule, checkpoint/resume. Mode A may or may not need the
  browse walk (spec decides how films→Metacritic lookup works: browse-walk archive vs.
  per-title search) — the contract binds any scraping either way.
- OMDb payloads already on disk carry a `Metascore` field — a cheap first-pass source /
  cross-check for the matcher.

## Parked / deferred (none blocking)

- IntegrityError catch in `record_catalog` is slightly broader than the exact UNIQUE
  conflict (unreachable today; noted in final review).
- `scripts/discovery` is excluded from ruff (`pyproject.toml` extend-exclude) — spike
  scripts stay unlinted by choice.

## Process (per the standing workflow)

One phase per fresh session. Superpowers flow: brainstorm → spec → written plan →
subagent-driven TDD execution, in a git worktree, dated decisions are settled — don't
relitigate. Specs/plans under `docs/superpowers/`.
