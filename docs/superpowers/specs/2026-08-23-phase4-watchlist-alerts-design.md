# Phase 4: Watchlist + availability alerts — design

**Date:** 2026-08-23. Phase 4 of the multi-service roadmap
(`docs/multiple-movie-services.md`) — the brief-window catcher. Rare films surface
on a service for two weeks and vanish; the point is to catch those windows for the
~50 films I actually want to see.

**Done when:** a watchlist film newly appearing on one of my services produces a
macOS notification from the nightly sync, and the dashboard surfaces all new
arrivals for 14 days.

## Decisions (settled in brainstorming, 2026-08-23)

1. **Refresh dial: watchlist nightly + weekly full.** Every sync refreshes TMDB
   providers for watchlist films (~50 calls); the full ~2,800-film refresh stays
   weekly. Max 1-day lag where it matters.
2. **Zero-film frontier fix: refresh-stamp frontier.** For TMDB-fed sources,
   "current" = `last_seen >= meta tmdb_providers_refreshed_at` (replacing per-source
   `MAX(last_seen)`, which freezes forever if a service drops to zero films —
   realistic for peacock=3, mubi=16). Criterion keeps its native `MAX(last_seen)`
   rule.
3. **Alert scope: notify watchlist, dashboard shows all.** The macOS notification
   fires only for watchlist films; the dashboard "New arrivals" surface shows every
   film that newly appeared on a subscribed service.
4. **Dashboard form: filter chip + 14-day window.** A "New arrivals" canned-filter
   chip in the existing chip system; a film counts as new for 14 days after its
   transition. No dismissal state.
5. **Transition storage: event table.** Append-only `availability_transitions`
   written by the collectors at listing-write time (approach chosen over deriving
   from `listings.first_seen`, which cannot represent reappearances, and over an
   in-memory diff, which is not durable or queryable).

## Data model — migration `006_watchlist.sql`

```sql
CREATE TABLE watchlist (
    film_id  INTEGER PRIMARY KEY REFERENCES films(id),
    added_on TEXT NOT NULL
);

CREATE TABLE availability_transitions (
    id          INTEGER PRIMARY KEY,
    film_id     INTEGER NOT NULL REFERENCES films(id),
    source      TEXT NOT NULL,
    appeared_on TEXT NOT NULL
);
CREATE INDEX idx_transitions_appeared ON availability_transitions(appeared_on);
```

- `watchlist` is my-response data (like `ratings`), separate from immutable films.
- `availability_transitions` is append-only; collectors never delete. Multiple
  events per (film, source) over time are expected — that's the history.
- No backfill: existing listings rows produce no events (upserts on existing
  current rows are not transitions), so the migration causes no event flood.
- Migration includes its own `schema_version` row (v6), per the standing rule.

## Transition detection (repository + collectors)

New repository method (used by both collectors, replacing their plain
`record_listing`/inline listing upsert):

```python
def record_listing_with_transition(
    self, film_id: int, source: str, url: str, seen: date
) -> bool:  # True = insert or reappearance; appends the transition row in the same txn
```

Detection rule, evaluated before the upsert, inside the same connection:

- **Insert** — no `(film_id, source)` row exists → transition.
- **Reappearance** — the row exists but was **not current** at write time:
  - TMDB-fed sources: `last_seen < meta tmdb_providers_refreshed_at` (no stamp yet
    → treat existing rows as current; only true inserts fire).
  - `criterion`: `last_seen < MAX(last_seen) over criterion listings`.
- Otherwise (row exists and is current) → ordinary upsert, no event.

Call sites:

- **TMDB provider loops** (`application/availability.py`): both the nightly
  watchlist pass and the weekly full pass record transitions per slug written.
- **Criterion walk** (`record_catalog` in `infrastructure/database.py`): a film
  newly inserted into the criterion listing, or a departed film returning to the
  rotation, is a transition too — Criterion is a subscribed service and its monthly
  rotation is exactly a brief-window source.

Known edge (accepted): a watchlist film that flickers off/on a TMDB service within
one weekly-stamp period produces no event — its row never went stale relative to
the stamp. If it never looked departed, it effectively never left.

Sync-loop guard (accepted risk, made explicit): the Criterion **cheap check** path
reuses the stored catalog without writing listings — no false transitions. Only the
full walk writes.

## Refresh dial (application/availability.py)

`tmdb_step` gains a **watchlist pass** between the match pass and the weekly-gated
full pass:

1. Match pass — unchanged.
2. **Watchlist pass (new, every run):** for each watchlist film with a TMDB id,
   fetch watch providers, write listings (with transition detection), update
   `tmdb.providers_checked_at`. Same tripwires as the full pass (AuthError → stop
   step; 5 consecutive failures → stop, keep progress). Does **not** touch the
   weekly stamp.
3. Full pass — unchanged weekly gate on `tmdb_providers_refreshed_at`; skips films
   whose `providers_checked_at` is already `today` (avoids double-fetching
   watchlist films on full-refresh nights). Stamp written only on completion, as
   today.

`--ratings-only` still skips the whole TMDB step. TMDB failures still never affect
exit code or other steps.

## Frontier fix (infrastructure/database.py)

`_SERVICES_SQL` changes its currency clause for non-criterion sources from
`l.last_seen = (SELECT MAX(last_seen) …)` to
`l.last_seen >= (SELECT value FROM meta WHERE key = 'tmdb_providers_refreshed_at')`
(when the stamp is absent — fresh DB — fall back to the MAX rule so nothing
spuriously departs). The main table view (`list_views`) is criterion-driven and
keeps the criterion MAX rule; `departed` semantics are unchanged.

Consequence to verify in tests: a service whose provider refresh returns zero films
correctly shows no current listings after the next completed full refresh, and a
missed week of syncs (stamp stale everywhere) leaves currency exactly as of the
last completed refresh — nothing flaps.

## Alerts

### macOS notification (nightly sync)

- New adapter `infrastructure/notify.py`: `notify(title: str, body: str) -> None`
  shelling to `osascript -e 'display notification …'` (works from the user
  LaunchAgent). Failures are logged and swallowed — never affect exit code.
- `application/sync.py` receives the notifier as an injected callable (tests pass a
  fake). After the TMDB step, if this run recorded ≥1 transition for a
  **watchlisted** film, send **one summary notification**:
  `movie-brain — 2 watchlist arrivals: Tokyo Story on Max · Playtime on MUBI`
  (truncate the list past ~4 films: `… and 3 more`).
- "This run's transitions" = transitions with `appeared_on = today` for watchlist
  films, queried after the step — no in-memory threading through the loops.

### Dashboard: New arrivals chip + drawer

- `domain/filters.py`: `NEW_ARRIVAL_DAYS = 14`; new predicate `new_arrivals` —
  true when the film has a transition within the window. Threshold served via
  `/api/config`, like the others.
- `FilmView` gains:
  - `new_on: list[dict]` — `[{source, appeared_on}]` within the window (empty
    otherwise), computed in the repository alongside `_services_by_film`.
  - `watchlisted: bool`.
- `web/static/app.js`: `CHIP_PREDICATES` gains `new_arrivals` (client-side check on
  `new_on`, window from config); `index.html` gains the chip button — lockstep rule
  per CLAUDE.md. Also a **Watchlist chip** (`watchlist` predicate: `v.watchlisted`).
- Drawer: "New on Max since Aug 20" line when `new_on` is non-empty; star toggle
  (below).

### Watchlist toggle (drawer)

- `POST /api/films/<id>/watchlist` — toggles membership, returns
  `{"watchlisted": bool}`. 404 on unknown film.
- Drawer renders ☆/★ next to the title; click calls the endpoint and updates the
  row's `watchlisted` client-side (mirrors the existing rating-edit pattern).
- No CLI verbs, no import/export — YAGNI; the drawer is the only writer.

## Testing

- **Unit (tests/unit):** transition detection (insert / reappearance-past-stamp /
  current-row-no-event / criterion variants); frontier SQL (zero-film service
  empties after refresh; missing stamp falls back to MAX); notifier adapter
  (subprocess mocked; failure swallowed); `new_arrivals` + `watchlist` predicates
  and thresholds.
- **BDD (tests/features + step_defs):**
  - watchlist film newly appears on a service → transition row + notification text
    with the film and service; non-watchlist arrival → transition row, no
    notification.
  - nightly watchlist pass runs without the weekly gate; full-refresh night does
    not double-fetch watchlist films; tripwires keep progress.
  - reappearance after going stale past the stamp fires; same-week flicker does
    not.
- **Web (tests/web):** toggle endpoint round-trip + 404; `new_on`/`watchlisted` in
  both film payloads; `/api/config` carries the new threshold. Playwright: chip
  filters, drawer star toggle, "New on …" line.

## Constraints (standing)

Collectors never delete; new migrations only (never edit applied ones);
dashboard + 3 AM sync keep working; suite, ruff, mypy green. On landing: update
CLAUDE.md (commands/rules deltas) and mark Phase 4 done in
`docs/multiple-movie-services.md`.

## Out of scope

Leaving-date alerts, alert acknowledgment/inbox, CLI watchlist verbs, per-service
deep links beyond the existing TMDB watch link, review-queue tooling (Phase 8),
subscription advisor (Phase 7 — the watchlist built here is its input).
