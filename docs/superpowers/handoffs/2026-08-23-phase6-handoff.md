# Handoff: Phase 5 done → Phase 6 (full-service import pattern)

**Written:** 2026-08-23, end of the Phase 5 session. Read this alongside
`docs/multiple-movie-services.md` (Implementation phases + dated decisions) and
`docs/vision.md` before any Phase 6 work.

## Status

- **Phase 5 (Metacritic Mode B: top-N dial) is fully landed and gated**: 260
  tests (incl. Playwright), ruff clean, mypy clean.
- Spec: `docs/superpowers/specs/2026-08-23-phase5-metacritic-mode-b-design.md`.
  Plan: `docs/superpowers/plans/2026-08-23-phase5-metacritic-mode-b.md`.
- **First-run UAT still pending** (do this before trusting N=100 discovery):
  run `movie-brain metacritic dial` — should show 100 and the current archive/staged
  counts; run a sync and confirm it promotes up to 100 Metacritic titles into real
  films (watch for the crawl-shortfall hint in the log if the archive is short);
  toggle "All films" in the dashboard and confirm discovery films appear (`scope=all`
  in the URL); note the OMDb backlog for ~100 new discovery films should drain in one
  nightly sync (free tier 1,000/day).

## What Phase 6 builds on (new since Phase 4)

- **Source-agnostic view.** `_VIEW_SQL` (`infrastructure/database.py`) now drives
  from `films` with a LEFT JOIN on the criterion listing, not an inner join —
  `list_views`/`get_view` return every film (no-listing OR current OR rated), and
  `FilmView.criterion` (bool) + `FilmView.url` (nullable) distinguish Criterion
  films from discovery ones. `summary()` stays criterion-scoped and adds a
  `discovery` count. The dashboard's scope toggle (`app.js`, URL-encoded state,
  default `criterion`, `all` reveals discovery films) is a client-side filter
  over the same full payload — the server doesn't scope.
- **`create_film`** (`Repository.create_film`, `infrastructure/database.py:174`):
  generates a guid, inserts a film, returns `None` on a `film_key` collision
  (the dedup tripwire) instead of raising or overwriting — the pattern any new
  full-catalog importer should reuse for "this title already exists under a
  different source."
- **Quiet first-ever TMDB provider check** (`application/availability.py`): a
  film's first provider check writes `listings` without an
  `availability_transitions` event (baseline, not arrival); later checks fire
  transitions normally. This is the fix for Phase 4's parked "first-import
  transition flood" concern (see below) — worth reusing for any importer whose
  films immediately get their first watch-providers check.
- **The `movie_service` registry** (slug PK, `kind` svod|store, `subscribed`/
  `region` as data) and `service_provider` (TMDB provider-id grouping per
  service) are unchanged by Phase 5 but are the natural registration point for
  a new full-service source — see the SOURCE hardcoding note below.
- **Mode-B promotion as a worked example of staging → films**:
  `application/metacritic.py` `promote_top_n` — match existing films first
  (dedup guard), then create films for the unclaimed remainder, anomalies to
  `match_review`, own tripwire, archive-only (no live fetch in the promotion
  path itself). Full-service import is a different acquisition pattern (whole
  catalog, not rank-limited) but the anomaly-handling shape (`match_review`,
  never delete, never overwrite) should carry over directly.
- **OMDb loop now covers non-Criterion films**: `films_needing_lookup_discovery`
  queries films with no Criterion listing, queued after criterion-current films
  in the same loop. A new full-service source's films will already get OMDb
  coverage for free as long as they land as `films` rows the same way.

## Decisions Phase 6 must make

- **The `SOURCE = "criterion"` hardcoding gap.** `cli.py`, `web/app.py`, and
  `application/export.py` (`write_csv(..., source: str = "criterion")`) all
  assume a single primary source string for status/summary/export. Phase 6 is
  explicitly the generalization Phase 5 deferred — decide whether `summary()`/
  `status`/export become multi-source-aware, gain a `--source` parameter, or
  stay Criterion-scoped with new sources only visible via `scope=all` in the
  dashboard (matching Mode-B's current posture).
- **Per-service sync cadence and tripwire isolation.** Criterion's sync step is
  a full walk against a live API; Mode-B's promotion is offline/archive-driven.
  A new full-service import (MUBI, BFI Player Classics) needs its own adapter
  (`infrastructure/<service>.py`, following `criterion.py`'s template) and its
  own tripwire block in `sync()` — decide whether it lives inline in `sync()`
  (like the Mode-B promotion call) or gets pulled into a per-source step list.
- **What "whole catalog" means for a paid small-catalog service** — is
  `listings` the join table (as Criterion uses it today), or does a second
  full-catalog source reuse `listings(film_id, source)` directly? The schema
  already supports multiple `source` values in `listings`; Phase 6 is the first
  time a second source actually populates it as its own catalog (Mode-B/TMDB
  writes are availability, not catalog membership).
- **Dedup against Mode-B and Criterion films.** A new full-catalog import must
  run the same matcher (`domain/matching.py`) against existing films before
  creating new ones, or a title already promoted via Mode-B / synced via
  Criterion gets a duplicate `films` row. `create_film`'s `film_key` collision
  return is the guard; anomalies still go to `match_review`.

## Parked / deferred (carried forward, none blocking)

**From Phase 4:**
- No direct tests: svod-exclusion in `watchlist_transitions_on`/`_NEW_ON_SQL`,
  watchlist-pass tripwire skipping the full pass (verified by inspection),
  notification truncation/plural paths (>4 arrivals).
- Same-day re-syncs (incl. `--ratings-only`) re-send that day's notification —
  accepted as harmless.
- CLI sync summary omits the watchlist-refresh count; `test_migration_004…`
  name has outgrown its MAX(version) assertion; two Playwright tests depend on
  Alpha being English without a comment.
- 249 open `match_review` rows still await Phase 8 tooling.

**New from Phase 5:**
- **Metacritic US-release/re-release years** flow into promoted films' `year`
  (MC stamps the US release year, not always the original) and may cause TMDB
  match misses for those films during the availability step — accepted;
  misses land in `match_review` like any other match anomaly, never block.
- **Departed Criterion films have no OMDb refresh path** — pre-existing gap,
  unrelated to Phase 5, noted here so it doesn't get lost.
- **`SOURCE = "criterion"` hardcoding across `cli.py`/`web/app.py`/
  `export.py`** — the generalization gap Phase 6 exists to close (see
  Decisions above).
- First-run UAT items listed under Status above (dial shows 100, scope toggle
  reveals discovery films, first sync promotes ~100 films and OMDb-drains them
  in one night) — do these before trusting Mode-B in daily use.

## Phase 6 entry-point prompt (paste into a fresh session)

> Phase 6 of movie-brain's multi-service roadmap: the full-service import
> pattern. Read docs/multiple-movie-services.md (phases + dated decisions),
> docs/vision.md, and docs/superpowers/handoffs/2026-08-23-phase6-handoff.md
> first. Scope: generalize "import a service's whole catalog" beyond Criterion
> (candidates: MUBI, BFI Player Classics — small paid catalogs worth having
> whole), reusing the source-agnostic view (`_VIEW_SQL`), `create_film`'s
> dedup-guard return, the quiet-first-check pattern, and the `movie_service`
> registry that Phase 5 left in place. Must decide: how to close the
> `SOURCE = "criterion"` hardcoding gap in cli/web/export, per-service sync
> cadence and tripwire isolation, what "whole catalog" means against the
> existing `listings(film_id, source)` join, and dedup against both Criterion
> and Mode-B films. Constraints: collectors never delete; new migrations only;
> dashboard + 3 AM sync + Phase 4 alerts + Phase 5 promotion keep working;
> suite/ruff/mypy green; update CLAUDE.md and mark Phase 6 done when it lands.
> Use the superpowers flow: brainstorm → spec → plan → subagent-driven TDD in a
> git worktree.
