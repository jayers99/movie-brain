# Phase 3: TMDB availability adapter

**Date:** 2026-08-23 · **Status:** approved
**Parent plan:** [multiple-movie-services.md](../../multiple-movie-services.md) — Phase 3.
**Success bar:** cross-service availability visible for Criterion films in the dashboard
drawer ("Also streaming on: …"); a TMDB sync step with its own tripwires that can never
break the Criterion or OMDb steps; unmatched films logged to `match_review` (never deleted,
never blocking); full suite + ruff + mypy green; dashboard and the 3 AM sync keep working.

## Decisions this spec implements (settled, dated — do not relitigate)

- **svod availability = TMDB `flatrate` only (2026-08-23):** `rent`/`buy` arrays are read
  only for store-kind services (Apple TV Store, provider 2 — the future owned-films hook).
  Purchasable-from-Amazon is never availability.
- **Amazon-channel provider ids stay excluded (2026-08-23):** HBO Max 1825, MUBI 201,
  BFI Player 287 are not in `service_provider` and are ignored if seen; TMDB availability
  for BFI Player Classics is knowingly invisible.
- **GUID identity (2026-08-24):** the TMDB id is a per-authority native id in
  `external_ids` (authority `tmdb`), never film identity.
- **Immutable films / collectors never delete (2026-08-24):** availability churn moves
  `last_seen`; nothing is ever deleted. Unmatched films go to `match_review`.
- **Matcher rules (2026-08-24 spike, 98%):** punctuation/case-insensitive title compare,
  exact-title preference, popularity tiebreak — from `scripts/discovery/match_spike2.py`,
  adapted here for original-year data (below).

Decisions made during this brainstorm (2026-08-23):

- **Availability lives in `listings`.** TMDB writes rows with `source` = service slug
  (`max`, `peacock`, `prime-video`, `apple-tv-plus`, `mubi`, `apple-tv-store`), reusing the
  existing `first_seen`/`last_seen`/departed mechanics. The `criterion` source is owned by
  the native adapter; the TMDB step never writes it (provider 258 is ignored on write).
- **Weekly full provider refresh.** Watch-provider data is re-queried for all matched films
  only when the last full refresh is > 7 days old (meta key). Worst-case staleness: 7 days.
  *Flagged:* Phase 4 (availability-transition alerts for brief windows) should revisit this
  dial; day-level freshness may be wanted there.
- **Matching is incremental and one-shot per film.** Films are searched once; hits cache
  the TMDB id in `external_ids`, misses record `found=0` + a `match_review` row and are not
  retried nightly (a future maintenance verb can re-run them).
- **UI is drawer-only.** "Also streaming on: <svod services beyond Criterion>", with
  unsubscribed services marked ("MUBI (not subscribed)"). No table column, no new chips —
  Phase 5 owns broader dashboard source-awareness.
- **Store rows are recorded, not shown.** Provider 2 in `rent`/`buy` writes an
  `apple-tv-store` listing; the drawer ignores store-kind rows for now.
- **Missing token degrades gracefully.** No TMDB token → the TMDB step logs one line and
  skips; sync exit code and other steps are unaffected.

## Architecture

Hexagonal, same shape as OMDb:

- `domain/matching.py` — gains a pure TMDB candidate-pick function (no HTTP).
- `infrastructure/tmdb.py` — `TmdbClient` (search + watch providers), the only file that
  knows TMDB's URLs/JSON.
- `infrastructure/config.py` — reads the v4 bearer token from
  `MOVIE_BRAIN_TMDB_TOKEN` or `<config_dir>/tmdb-read-token.txt`; `None` if absent.
- `application/sync.py` — a TMDB step after the OMDb loop, with its own tripwires.
- `web/app.py` + `static/app.js` — per-film services in the films payload; drawer line.

## Schema — migration `005_tmdb.sql` (additive, BEGIN/COMMIT)

```sql
CREATE TABLE tmdb (
    film_id INTEGER PRIMARY KEY REFERENCES films(id),
    found INTEGER NOT NULL,              -- 0 = searched, no match (not retried)
    looked_up TEXT NOT NULL,             -- match date
    providers_checked_at TEXT,           -- last watch-providers query for this film
    payload TEXT                         -- raw US watch-providers JSON, re-parseable
);
INSERT INTO schema_version (version) VALUES (5);
```

- TMDB numeric id → `external_ids (authority 'tmdb', value = str(id))`.
- Meta key `tmdb_providers_refreshed_at` marks the last *completed* full refresh.
- `init_db` auto-backup covers the migration as usual.

## Matching (domain rules)

Input: our film (`title`, `year` — original years, unlike Metacritic's US re-release
years) and TMDB search results (title, original_title, release-date year, popularity).

1. Exact normalized-title matches (`norm_title` on either title or original_title) with
   |year − ours| ≤ 1 → pick highest popularity.
2. Fallback: any of the top 3 results with |year − ours| ≤ 1 → pick the first.
3. Otherwise no match → `match_review` (authority `tmdb`, reason `no-match`), `found=0`.
4. Year-less films (ours or theirs): exact-title only, popularity tiebreak; ambiguity is
   acceptable here because misses land in the review queue, not the trash.

## Sync step (runs after OMDb; failures never propagate)

1. **Match pass (nightly, incremental):** for films with no `tmdb` external id and no
   `tmdb.found` row: `search_film(title, year)` → apply domain rules → store external id
   (+ `found=1`) or `found=0` + `match_review`. Tripwires: 401 → log and abort the TMDB
   step only; 5 consecutive request failures → stop the step, keep progress.
2. **Provider refresh (weekly full):** if `tmdb_providers_refreshed_at` is absent or
   > 7 days old: for every film with a `tmdb` external id, `watch_providers(id)` (US):
   - map `flatrate` provider ids through `service_provider` → slugs; drop `criterion`;
   - provider 2 in `rent`/`buy` → `apple-tv-store`;
   - upsert each mapped slug into `listings` (`url` = TMDB's US watch link; insert sets
     `first_seen`, always bumps `last_seen` to today);
   - store raw payload + `providers_checked_at` in `tmdb`.
   The meta stamp is written only when the pass completes; a tripwired abort keeps
   progress (`providers_checked_at` guides resume order next night: stalest first).
3. A film a service dropped simply stops getting `last_seen` bumps for that source —
   per-source departed is a display state, uniform with Criterion.
4. `SyncResult` gains TMDB counters (matched, missed, providers refreshed) for the log;
   exit code 0 is unaffected by TMDB-only failures.

## Web

- Films payload: each film gains `services`: current (per-source `last_seen` = that
  source's max) svod listings excluding `criterion`, as `[{name, subscribed}]`, ordered
  subscribed-first then alphabetically. Store-kind rows excluded.
- Drawer: after the Criterion link, `Also streaming on: HBO Max, MUBI (not subscribed)`;
  line omitted when empty. No filter/sort logic touches services this phase.

## Testing

- **Unit:** TMDB candidate-pick rules (exact/fallback/year-less/ambiguous); `TmdbClient`
  parsing (flatrate/rent/buy/link, excluded providers) with `responses`.
- **BDD (application):** match pass stores ids and review rows; weekly gate (fresh stamp →
  no provider calls); refresh writes/bumps listings and skips criterion; store rows
  recorded; tripwire stops TMDB step but sync still exits 0 with Criterion+OMDb intact;
  no token → step skipped; dropped service → listing goes stale, not deleted.
- **Web:** payload includes `services`; Playwright drawer shows/hides the line.
- CLAUDE.md updated (rules + data sections); roadmap Phase 3 marked done.

## Out of scope (later phases)

Watchlist/alerts and transition detection (4); dashboard source-awareness, chips, columns
(5); ownership/prices beyond recording store rows (iTunes track); refresh-cadence dial
revisit (4); re-match maintenance verbs (8).
