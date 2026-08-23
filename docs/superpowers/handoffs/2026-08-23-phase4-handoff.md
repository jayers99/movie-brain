**Superseded: Phase 4 landed (2026-08-23).**

# Handoff: Phase 3 done → Phase 4 (Watchlist + availability alerts)

**Written:** 2026-08-23, end of the Phase 3 session. Read this alongside
`docs/multiple-movie-services.md` (Implementation phases + dated decisions) and
`docs/vision.md` before any Phase 4 work.

## Status

- **Phase 3 (TMDB availability adapter) is fully landed**: merged to `main`, pushed
  (`f545e1e`), and the **live DB has run it** — schema v5, all 3,051 films through the
  match pass (2,802 matched to TMDB, 249 in the review queue), availability written:
  max 402 · prime-video 80 · mubi 16 · peacock 3 · apple-tv-store 865 (store rows are
  recorded, not shown). UAT verified: drawer "Also streaming on" line, no-line negative
  case, and the weekly gate (second sync fast, stamp `2026-08-23` written).
- Full gate green: 208 tests (incl. Playwright), ruff, mypy.
- Spec: `docs/superpowers/specs/2026-08-23-phase3-tmdb-availability-design.md`.
  Plan: `docs/superpowers/plans/2026-08-23-phase3-tmdb-availability.md`.

## What Phase 4 builds on (new since Phase 2)

- **Availability lives in `listings`** — source = service slug (`max`, `peacock`,
  `prime-video`, `apple-tv-plus`, `mubi`, `apple-tv-store`), written by the TMDB step;
  `criterion` rows stay owned by the native adapter. "Current" per source =
  `last_seen = MAX(last_seen) for that source`; a dropped film just goes stale.
- **`tmdb` table** (`film_id`, `found`, `looked_up`, `providers_checked_at`, `payload`)
  caches the one-shot match verdict + raw US watch-providers JSON. TMDB numeric id is in
  `external_ids` authority `tmdb`. `found=0` is never retried by sync (misses AND
  id-conflicts both land there → review queue, reason `no-match`).
- **Sync order:** Criterion walk → OMDb loop → TMDB step (`application/availability.py`,
  `tmdb_step`): nightly incremental match pass, then a full provider refresh only when
  meta `tmdb_providers_refreshed_at` is >7 days old. Stamp written only on completion;
  tripwires (AuthError, 5 consecutive failures) keep progress and never touch exit code.
  `--ratings-only` skips the step entirely. Token: `MOVIE_BRAIN_TMDB_TOKEN` or
  `<config_dir>/tmdb-read-token.txt`; missing token = skip with a log line.
- **Web:** `FilmView.services` (`[{name, subscribed}]`, current non-criterion svod,
  subscribed-first) in both film endpoints; drawer renders the line client-side.

## Phase 4 scope (from the roadmap — the brief-window catcher)

Watchlist entity + drawer toggle; sync-time **transition detection** (availability
*appearing*, not just existing); alert channel — macOS notification from the nightly
sync + a "newly available" dashboard surface (spec decides the mix). **Done when:** a
watchlist film newly appearing on my services produces an alert I actually see.
Watchlist size ~50 films (see the 2026-08-24 note in multiple-movie-services.md).

## Decisions Phase 4 must make (flagged during Phase 3)

- **Staleness dial:** weekly refresh means up to 7 days of lag — likely too slow for
  catching two-week windows. Options: nightly full refresh (~2,800 calls, ~minutes, no
  quota issue), a rolling slice, or watchlist-films-refreshed-nightly + weekly full.
- **Transition semantics:** "newly available" ≈ a listings row insert (first_seen) or a
  stale row going current again after a gap. `record_listing` currently upserts without
  reporting which happened — the step needs to surface inserts/reappearances.
- **Zero-film frontier stall (final-review finding):** if a service drops to zero films,
  its per-source `MAX(last_seen)` frontier freezes and every stale row stays "current"
  forever. Realistic for peacock (3 rows) / mubi (16). Consider keying "current" off the
  refresh stamp instead of the per-source MAX when the source is TMDB-fed.

## Parked / deferred (none blocking)

- Review-queue rows don't distinguish id-conflict from no-match (log line only; needs a
  persisted reason — Phase 8 territory).
- `sqlite3.IntegrityError` caught in `application/availability.py` (boundary bend,
  accepted; a Repository-level translation would restore it).
- `get_view` computes services for all films to serve one (fine at 3k films).
- Duplicate `_stderr` helper in sync.py/availability.py; assorted small test-coverage
  gaps (±1 year boundary, non-401 HTTP error path).
- 249 open `match_review` rows await Phase 8 tooling; conflicts included (e.g.
  'Swordsman II' vs id 18667 = Swordsman 1990).

## Phase 4 entry-point prompt (paste into a fresh session)

> Phase 4 of movie-brain's multi-service roadmap: watchlist + availability alerts.
> Read docs/multiple-movie-services.md (phases + dated decisions), docs/vision.md, and
> docs/superpowers/handoffs/2026-08-23-phase4-handoff.md first. Scope: watchlist entity
> (~50 films) with a drawer toggle; sync-time availability-transition detection (newly
> appeared on my services, not just currently-on); alert channel = macOS notification
> from the nightly launchd sync + a "newly available" dashboard surface (spec decides
> the mix). Must decide: the refresh-staleness dial (weekly is too slow for brief
> windows) and the zero-film frontier stall. Constraints: collectors never delete; new
> migrations only; dashboard + 3 AM sync keep working; suite/ruff/mypy green; update
> CLAUDE.md and mark Phase 4 done when it lands. Use the superpowers flow: brainstorm →
> spec → plan → subagent-driven TDD in a git worktree.
