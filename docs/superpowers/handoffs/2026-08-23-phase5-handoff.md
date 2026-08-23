# Handoff: Phase 4 done → Phase 5 (Metacritic Mode B: the top-N dial)

**Written:** 2026-08-23, end of the Phase 4 session. Read this alongside
`docs/multiple-movie-services.md` (Implementation phases + dated decisions) and
`docs/vision.md` before any Phase 5 work.

## Status

- **Phase 4 (watchlist + availability alerts) is fully landed**: merged to `main`
  fast-forward and pushed (`e7e7591`). Full gate green: 240 tests (incl.
  Playwright), ruff, mypy.
- **The live DB has NOT yet run migration 006** — it applies automatically on the
  next sync or dashboard start (pre-migration backup lands in
  `<config_dir>/backups/` first). Verified: no transition-event flood on existing
  data (upserts of current rows are quiet by design).
- **First-run UAT still pending** (do this before trusting the alerts):
  star a few films in the drawer so the nightly pass has a watchlist; approve the
  one-time macOS prompt allowing notifications from osascript (until approved, the
  3 AM notification won't display); optionally fire a manual sync to see the path
  end to end.
- Spec: `docs/superpowers/specs/2026-08-23-phase4-watchlist-alerts-design.md`.
  Plan: `docs/superpowers/plans/2026-08-23-phase4-watchlist-alerts.md`.

## What Phase 5 builds on (new since Phase 3)

- **`watchlist`** (film_id, added_on — user-response data; drawer toggle is the
  only writer) and **`availability_transitions`** (append-only event log: one row
  per insert-or-reappearance of a listing, written by BOTH collectors at
  listing-write time against a pre-batch currency frontier). Store-kind sources
  are recorded but never surfaced.
- **TMDB step order:** match pass → nightly watchlist provider pass (~50 calls,
  every sync, never touches the stamp) → weekly-gated full pass
  (`films_for_provider_refresh(skip_checked_on=today)` avoids double fetches;
  stamp written only on completion).
- **Currency for TMDB-fed sources** = `last_seen >= meta
  tmdb_providers_refreshed_at` (MAX fallback when no stamp); criterion keeps
  `MAX(last_seen)`. Constant: `TMDB_REFRESH_STAMP` in `infrastructure/database.py`.
- **Notification:** `infrastructure/notify.py` (osascript, `ensure_ascii=False` —
  UTF-8 required, ASCII-escaped scripts are rejected), injected into `sync()` as
  `notifier`; the whole notifier block is inside one try — alerts can never touch
  the exit code.
- **Web:** `FilmView.new_on` (`[{source, name, appeared_on}]`, svod only, 14-day
  window) + `FilmView.watchlisted`; chips `new_arrivals` + `watchlist`;
  `POST /api/films/<id>/watchlist`; `list_views`/`get_view` take an optional
  `today`.

## Phase 5 scope (from the roadmap)

**Metacritic Mode B — the top-N discovery dial, N as config starting at 100.**
Crawler already exists from Phase 2 (`metacritic crawl --pages N`: polite,
checkpointed, archive-first — archived pages are never re-fetched; ~24 titles/page,
so N=100 needs ~5 pages). New in Mode B: promote the top-N staged `metacritic`
rows into **real films** (generated guid; unmatched-to-existing only — Mode A
already linked the Criterion overlap), and give the dashboard the **minimum
source-awareness to stay usable as N grows** (default view = my services /
Criterion parity). Done when: top-100 lives in the app, the model is validated,
and N=1,000 is a config change, not a project.

## Decisions Phase 5 must make (flagged during Phase 4)

- **The criterion-joined view.** `_VIEW_SQL` inner-joins `listings` on
  `source='criterion'`, so a Mode-B film with no Criterion listing is invisible to
  `list_views`/`get_view` today (this exact trap bit Phase 4's plan pre-flight).
  "Minimum source-awareness" has to rework the main view's driving join — the
  central design question of the phase.
- **First-import transition flood.** Newly created films that then gain TMDB
  availability fire *insert* transitions — up to N films × services hitting the
  "New arrivals" chip (14-day window) in one week. Decide: accept (they ARE new to
  the app), suppress events during initial import, or exclude first-ever listings
  of brand-new films from `new_on`. (Watchlist notifications are safe either way —
  new films can't be watchlisted yet.)
- **OMDb coverage.** The OMDb loop is criterion-driven
  (`films_needing_lookup(SOURCE)`); Mode-B films won't get IMDb/RT ratings unless
  the loop is widened. They arrive WITH a metascore (scraped-first COALESCE
  already handles that), so decide whether OMDb backfill is in-scope (free tier:
  1,000/day — N=100 is trivial, N=10,000 is a week).
- **Where N lives** (config file? `meta`? CLI flag with persisted default?) and
  what "top-N" means when scores tie at the boundary.
- **Dedup guard.** Staging → films must run the matcher against *existing* films
  first so a Criterion film never gets a twin (film_key conflict is the tripwire;
  unmatched anomalies → `match_review`, never deleted — standing rule).

## Parked / deferred from Phase 4 (none blocking)

- No direct tests: svod-exclusion in `watchlist_transitions_on`/`_NEW_ON_SQL`,
  watchlist-pass tripwire skipping the full pass (verified by inspection),
  notification truncation/plural paths (>4 arrivals).
- Same-day re-syncs (incl. `--ratings-only`) re-send that day's notification —
  accepted as harmless.
- CLI sync summary omits the watchlist-refresh count; `test_migration_004…` name
  has outgrown its MAX(version) assertion; two Playwright tests depend on Alpha
  being English without a comment.
- 249 open `match_review` rows still await Phase 8 tooling.

## Phase 5 entry-point prompt (paste into a fresh session)

> Phase 5 of movie-brain's multi-service roadmap: Metacritic Mode B — the top-N
> discovery dial. Read docs/multiple-movie-services.md (phases + dated
> decisions), docs/vision.md, and
> docs/superpowers/handoffs/2026-08-23-phase5-handoff.md first. Scope: promote
> the top-N staged Metacritic titles (N as config, start 100) into real films
> with generated guids, matched against existing films first (dedup guard;
> misses → match_review); extend the crawl archive only as far as N needs;
> dashboard gains minimum source-awareness so Mode-B films are visible while the
> default view keeps Criterion parity. Must decide: the criterion-joined
> _VIEW_SQL rework (Mode-B films are invisible to it today), the first-import
> "New arrivals" flood, OMDb backfill scope, and where N lives. Constraints:
> collectors never delete; new migrations only; dashboard + 3 AM sync + Phase 4
> alerts keep working; suite/ruff/mypy green; update CLAUDE.md and mark Phase 5
> done when it lands. Use the superpowers flow: brainstorm → spec → plan →
> subagent-driven TDD in a git worktree.
