# Criterion relaunch — design

*2026-10-01. Backlog 50, branch `feature/STORY-50-criterion-relaunch`. Owner ask: "The Criterion Collection has changed their website design this month. We need to fix everything so we can run an update of the new arrivals and the leaving movies." Seed and discovery: `2026-10-01-criterion-relaunch-seed.md`; real captures and probe scripts: `../research/2026-10-01-criterion-relaunch/`. Stories: `../briefs/2026-10-01-criterion-relaunch/brief.md`. Design sections 1 and 2 were each reviewed by Codex and Fable before owner approval; every accepted finding is folded in below.*

## 1. Outcome

Sync works again for the Criterion Channel, with true new arrivals and true leaving dates, and **without** twin films, false arrivals or departures, a wiped director, or a rating or viewing moved off its film.

Today `sync` exits 1 at step 1 (`no window.TOKEN on browse page`): the site left VHX for a Next.js + JW Player build on 2026-10-01. The last good walk was 2026-09-20 (3,013 current films).

## 2. What the new site gives (verified 2026-10-01)

| Need | Call | Shape (capture in the research folder) |
|---|---|---|
| Catalog | `GET www.criterionchannel.com/api/all-films/results?page_limit=200[&pagination_key=K]` | `{items, paging.next_pagination_key, total}`; item `{title, release_date, mediaid, duration, contentType}`; `page_limit` caps at 200 → 16 pages for `total` 3,042 (3,009 `film`, 33 `series`); `release_date` always `YYYY-01-01`; no director, no slug, no date-added sort; the LAST page's `paging` is `{page_limit}` only — the key is absent; junk years `0-01-01` (4 items) and `2915-01-01` (1) (`all-films-results.page1.trimmed.json`, `all-films-results.lastpage.json`, the whole walk in `catalog-2026-10-01.json`) |
| Film detail | `GET cdn.jwplayer.com/v2/media/<mediaid>` | `playlist[0]` carries `director`, `country`, `language`, `starring` as JSON-encoded STRINGS, `title_original`, `release_date` (sometimes full), `criterion_id`, `license_start_date_time`, `license_end_date_time` (`jw-media.L5Z3RaiC.json`) |
| Leaving | home page → `/discover/leaving-<month>-<day>` → its RSC payload names a JW playlist → `GET cdn.jwplayer.com/v2/playlists/<id>?page_limit=500` | the home page links one DATED leaving page, `/discover/leaving-october-31`, plus the undated editorial `/discover/leaving-soon` (themed subsets, ignored); its RSC payload carries `\"playlistID\":\"0WbeKrrA\"`; the playlist holds 28 films (`home-2026-10-01.html`, `leaving-october-31.html` — cut to the parser's tokens, verbatim and in order, by `strip_descriptions.py`; `jw-playlist.0WbeKrrA.full.json`) |
| Old URL → id | `HEAD criterionchannel.com/<old-slug>` (no redirect follow) | `307` with `Location: /films/<mediaid>/<slug>`, or `/supplements/<id>/<slug>`, or `404` (`old-url-redirects.tsv`, 293 rows; joined to the catalog in `drift.tsv` by `probe_drift.py`) |
| Film page | `GET criterionchannel.com/films/<mediaid>` | `308` → `/films/<mediaid>/<slug>` → `200` (`probe-captures-output.txt`, Test Pattern `gpRRkq27`) |
| Unknown id at JW | `GET cdn.jwplayer.com/v2/media/<bad id>` | `404` `{"message": "['…']: id not found in index."}` (`probe-captures-output.txt`) |

Prose (descriptions) is blanked in every saved JW capture and cut from the HTML (owner ruling 2026-10-01: public repo; `strip_descriptions.py`). Calls exercised: every row above, by the probe scripts in the research folder (`probe_walk.py`, `probe_redirects.py`, `probe_unexplained.py`, `probe_captures.py`), 2026-10-01; every count in this spec and the brief re-derives from the saved files (`probe_match.py`, `probe_drift.py`). Not exercised: a 429 from either host, two leaving pages linked at once, a playlist above 500 items. `/search?q=` returns 200 but renders its results client-side, so it was not adopted (D10).

Owner ruling (D1 below): `robots.txt` disallows `/api/`; the owner ruled his personal agent is not a robot. The adapter stays polite regardless.

## 3. Decisions

**D1 — Catalog source.** `/api/all-films/results`, `page_limit=200`, ≥1 s between calls, the existing `USER_AGENT`, exponential backoff on 429 (three tries, then the walk fails). Follow `next_pagination_key` until absent; a repeated key or an empty page aborts; the RAW item count (before the `film` filter and dedupe) must equal `total`, else abort. Only `contentType == "film"`; repeated mediaids within one walk are dropped after the first (Criterion lists *Bad Timing* (1982, Savoca) twice under `2hBeeBd5` — #283 and #1682 are two different works and are never merged). A year outside 1880–(this year + 2) becomes `None` (seen: `0`, `2915`).

**D2 — Identity is the mediaid.** Stored as `external_ids (film_id, 'criterion', <mediaid>)` beside the old URL rows, which stay (a catalog source is a claim authority; several values per film are legal). No schema change. A walk matches a catalog item to a film by mediaid FIRST; `film_key` is never used to match a Criterion item again.

**D3 — `criterion bridge [--apply] [--retry]`** (`application/criterion_bridge.py`, a new CLI verb). First it walks the catalog once (D1, 16 calls) so the drift table can name Criterion's title and year for each mediaid. Then, for every stored `criterion` external id whose value is an old URL: `HEAD` without following, 0.4 s apart (3,095 → about 25–30 minutes with each request's own time). Outcomes, each checkpointed in `<config_dir>/criterion-bridge.jsonl` (one line per old URL, so a rerun skips what it has already settled):
- `done` — `307` to `/films/<mediaid>/<slug>`: write the mediaid on that film (canonical id via `film_disposition`), and remember the Location path as the film's new listing URL.
- `held` — that mediaid already belongs to a DIFFERENT canonical film: write nothing; queue an `id-conflict` review (authority `criterion`, value = mediaid).
- `supplement` — `307` to `/supplements/…`: write nothing (the film leaves the catalog).
- `gone` — `404`: write nothing.
- `retry` — network error or any other status: write nothing; only `--retry` asks again.
Dry run by default: prints the outcome counts and the drift table (title and/or year that differ between our film and the catalog item the mediaid names — on 2026-10-01: 97 year, 72 title, 9 both, `drift.tsv`). Two old URLs on one film that land on the same mediaid are a no-op the second time.

**D4 — Our title and year stay.** Criterion's printed title and year go into a `claim` row `(authority 'criterion', value <mediaid>)` — `INSERT OR IGNORE`, so the claim records the FIRST title/year seen for that mediaid. `films.title`, `films.year` are never written by the walk. `films.director` is written only when it is NULL (D8). The resolver keeps reading a film's first Criterion claim (`claims_for_film` order), which is the old-URL claim for bridged films — intended: our year is the truth-holder (`identity.md`).

**D5 — An unknown mediaid goes through the same gates as `films add`.** For each catalog item whose mediaid no film holds: fetch its JW record; build a `film_query` from Criterion's title, year, director and runtime; run the thumbprint resolver; then:
- resolver `match` with an IMDb id → the `films add` ladder (`application/films.py::add_by_id`, factored into one shared function): `find_holder` 1/2b, `corpus_veto` 3, tombstoned keys, `films.key` collision. A holder → the listing, mediaid and claim join THAT film. No holder and every gate clear → create the film (our guid; TMDB's title and year as `films add` does; Criterion's director), born with its mediaid.
- resolver non-match, ambiguous, a gate refusal, a tombstone or a key collision → a `match_review` row (authority `criterion`, value = mediaid), never a film.
- no TMDB token → the item is skipped and logged, with NO review row, so it is resolved on the first night the token is back; nothing is created.
- JW answers `404` for the mediaid → an answer, not weather: the item becomes a review row (reason `no-record`) and the walk carries on.
- Every criterion review row's `detail` carries what Criterion showed: the catalog title, year and duration, and — when JW answered — director, original title and `criterion_id`; it is what the owner reads to pick `--film X`, and what `--create` mints from.
- a mediaid whose review row was DISMISSED → skipped without a JW call, every night (a standing decision); a mediaid with an OPEN row → skipped likewise until resolved.
The resolver runs BEFORE `find_holder` (the ladder starts from an id). Newly created films are keyed after the write transaction, as `films add` does ("a keying failure never undoes the creation"), and get the enrichment-on-add tail.

**D6 — One write transaction.** Steps: (1) walk the catalog; (2) for every unknown mediaid, JW lookup + resolver + gates — all network work done here, nothing written; (3) fetch leaving labels; (4) ONE new repository method, `record_criterion_walk(staged, today)`, writes inside a single `with self._conn()`: new films, mediaid external ids, claims, listings (with the pre-batch currency frontier, exactly as `record_catalog` does), review rows (the open/resolved check is done in staging; the insert happens here, never through `queue_review_once`'s own transaction), director fills, leaving labels, `films_fetched_at`. A Criterion listing NOT stamped by this walk has its `leaving_date` cleared in the same transaction, so a departed film never keeps a Leaving label. A failure anywhere in (1)–(4) → nothing written FOR CRITERION; the sync carries on with steps 4–8 (Metacritic promotion, keying, OMDb, providers, the catch-up chain, the notification) and exits 1 at the end so the failure is seen. Owner ruling 2026-10-01: one source's weather never breaks another — today's early `return SyncResult(1, …)` at the catalog step goes. A JW lookup that fails after retries in (2) — a network error or 5xx, never a 404 — fails the walk (the Criterion source's own weather) — carry-forward cannot apply: an unknown mediaid has no listing to carry, and a skipped known film would read departed today and arrive falsely tomorrow.

**D7 — Leaving.** The label comes from the leaving page's slug (`leaving-october-31` → `"October 31"`), the stored shape unchanged, so the dashboard's chip and drawer line (`app.js:747`) need no change. `license_end_date_time` is a cross-check only: Criterion sets some expiries at EST midnight regardless of daylight time (Zabriskie Point `2026-11-01T04:59:59Z` beside Eve's Bayou `03:59:59Z`, both "October 31"); a disagreement beyond that one hour is logged. Only DATED leaving pages count (`/discover/leaving-<month>-<day>`); `/discover/leaving-soon` and any other undated `leaving-*` page are editorial and ignored. Home page loaded but NO dated leaving link → an authoritative empty set: all labels cleared. The home page, a leaving page or a playlist call FAILS → last-known labels kept, warning logged. Labels are keyed by mediaid.

**D8 — Directors.** The dashboard shows `COALESCE(films.director, OMDb Director)`, so a NULL `films.director` is usually not a blank on screen: of the 124 current Criterion films with NULL `films.director`, 117 already show OMDb's. A new catch-up-chain step, `criterion directors`, fills `films.director` from the JW record ONLY for films holding a Criterion mediaid, a NULL `films.director` AND no OMDb director (7 such films today; 3 are in the new catalog and qualify — #735, #1766, #1777 — and 4 depart on the first walk) — so no director the owner already sees ever changes. Fill-only, one JW call per film, stamped so a film Criterion has no director for is not asked nightly; its own tripwire. A film the walk CREATES takes Criterion's director at birth (D5), as the VHX walk did.

**D9 — Review resolution.** `review resolve` accepts `criterion` rows (value = mediaid): `--film X` writes the mediaid external id and the claim on film X (canonical), so the next walk treats it as known and lists it; `--create` mints from the row's `detail` (never a refetch — a `no-record` row's JW lookup would 404 again) under Criterion's title, year and director, born with its mediaid, after the SAME gate ladder as D5 (`find_holder` 1/2b when a resolver id exists, `corpus_veto` 3, tombstone, `films.key` collision — a refusal names the holder and leaves the row open), then keys it as `films add` does (`key_films`; a keying failure never undoes the creation) and runs the enrichment-on-add tail; `--dismiss` closes the row and the walk skips that mediaid for good (D5). The walk's staging dedupes by (reason, value) for rows with no film, so two unknown mediaids are two rows.

**D10 — Listing URL.** A bridged film's listing URL is its redirect Location (`https://www.criterionchannel.com/films/<mediaid>/<slug>`); a new film's is `https://www.criterionchannel.com/films/<mediaid>`, which the site 308-redirects to the slugged page (captured). Criterion's `search_url` stays unset: every Criterion listing now has a working film URL, and the site's `/search?q=` renders its results client-side.

**D11 — Removed and kept.** Removed: the VHX adapter (`fetch_token`, `fetch_films`, `fetch_leaving`, `page_one_matches`), the cheap check and its `films_raw_total` meta, the sync's use of `merge_yearless` (the domain function stays; its unit tests stay). Kept: `record_catalog` and key-based `set_leaving` signatures (the legacy import and ~60 test fixtures call them). `--full` stays an accepted flag with no effect (help text: "kept for habit — every sync walks the whole catalog"); `SyncResult.full_walk` and the CLI's "full walk" line go. `SyncResult` gains `criterion_arrived`, `criterion_departed`, `criterion_reviews`, and the CLI prints them on one line (`criterion — arrived N · left N · to review N`). Steps 4–8 of the sync contract are untouched.

**D12 — Lifted blocker.** `repair.py:743` refuses edition re-keys of Criterion-listed films ("re-key deferred to the ingester switch") because the `ON CONFLICT(key)` upsert would twin them. Mediaid matching removes that hazard, so the blocker and its pin (`test_thumbprint.py:343`) go in this change.

**D13 — First run.** Real arrivals fire transitions and the normal watchlist notification; departures are a display state as today (`_LISTING_CURRENT`), never an event. Measured expectation for the first walk after the bridge: ~67 films whose licence started in October; UP TO ~115 departures (43 bridged to a mediaid no longer listed — the 39 "September 30" films among them — 68 old URLs now 404, 4 now supplements). Fewer in practice: some 404 films are still listed under a NEW mediaid (Grey Gardens #1817, Mirror #2476, Being Frank #3076, Factory #1689, Fanny and Alexander #3091, K-ON! #142) and rejoin their film through D5 when the resolver matches them. Multi-part works Criterion now lists as ONE item (Agnès de ci de là Varda episodes #1368–1372 → `kWE7uBRe`; Four Journeys into Mystic Time #1579–1582 → `WPriMSZJ`; Lone Wolf and Cub #1720, #2067–2071 → `rLiSVzkD`) are bridged to the same mediaid on several films: the bridge's `held` rule lists the FIRST and queues the rest as `id-conflict` reviews, never a merge.

## 4. Failure table

| Failure | Result |
|---|---|
| Catalog HTTP error, 429 after three tries, repeated/empty cursor, raw count ≠ `total` | nothing written for Criterion; steps 4–8 run; exit 1 |
| JW lookup for an unknown mediaid fails after retries (network / 5xx) | nothing written for Criterion; steps 4–8 run; exit 1 |
| JW answers 404 for a mediaid | review row `no-record`; the walk carries on |
| A mediaid's review row is open or dismissed | skipped, no JW call |
| Resolver non-match / ambiguous / gate refusal / tombstone / held / key collision | one review row per mediaid, never a film |
| No TMDB token | unknown items skipped + logged (no review row); known mediaids refresh |
| No OMDb key | unchanged: the CLI refuses to sync (`cli.py:230`) |
| Home page loads, no leaving link | labels cleared |
| Any leaving call fails | labels kept, warning |
| Write transaction raises | nothing written for Criterion (one transaction); steps 4–8 run; exit 1 |
| Bridge request fails | `retry` outcome; `--retry` asks again |
| Directors step fails | logged, swallowed (chain tripwire) |

## 5. Tests

Outside-in, pytest-bdd scenarios; fixtures cut from the real captures (shapes never invented; synthetic only where no real answer exists: half-walk failure, held-by-other, resume, 429).

- **Adapter:** pagination to the end; repeated cursor / empty page / count ≠ total abort; raw count includes series; junk years → None; JSON-string lists decoded; repeated mediaid dropped; leaving slug → label; EST/EDT cross-check logged not trusted.
- **Sync:** known mediaid with drifted title/year → same film, no twin, no transition, claim written (Nadja #3057, ours 1994, Criterion 1995, rating 5 kept); unknown mediaid matching a held film → listing joins it (Barry Lyndon #3433); unknown, resolver finds an id no film holds → born with its mediaid; resolver non-match → review row; two ambiguous mediaids → two rows, rerun → none new; JW failure → no Criterion row changed AND the OMDb/provider steps still ran, exit 1 (replaces today's "catalog failure leaves the database untouched" scenario); a write failure injected late in the transaction → films, ids, claims, listings, reviews, ratings and viewings all unchanged; real departure (Some Came Running #33, watchlisted) and real arrival → transition + notification; leaving link absent → cleared; leaving call fails → kept; director filled once, only where neither ours nor OMDb's exists, never overwritten; a departed film loses its Leaving label in the same walk; JW 404 → review row and the walk completes; a dismissed mediaid is skipped with no JW call; `--create` on a criterion row mints under Criterion's title and the next walk lists it.
- **Bridge:** 307 film, 307 supplement, 404, held-by-other → review, rerun skips settled rows, `--retry` re-asks only `retry` rows, dry run writes nothing.
- **Review:** `criterion` row resolved `--film` → next walk lists it.
- **Retired deliberately (named in the plan):** `tests/unit/test_criterion.py`; the sync.feature cheap-check, year-less and "--full always walks" scenarios; the `test_thumbprint.py:343` blocker pin.

## 6. Rollout (each step only on the owner's yes, one at a time)

1. Dated copy of the live DB (`backups/pre-criterion-bridge-<date>.db`).
2. `criterion bridge` dry run (~21 min, in the builder's background shell) → outcome counts + drift table to the owner.
3. `criterion bridge --apply` → before/after counts.
4. Dated copy again; `sync` in the background (it also runs the weekly TMDB refresh, 11 days overdue on 2026-10-01) → Criterion arrivals / departures / reviews opened / directors filled reported apart from TMDB counts.

Gap check per `checks/README.md`: point A on this spec + the brief before the owner reads it; point C (two lineages if the pilot is still running) on the branch head with a migrated copy before the live rollout. No mock-up: nothing visible changes.

## 7. Out of scope

Series and supplements (excluded as before); Criterion's editorial shelves (`/new`, themed playlists); per-film licence-end refresh for every film (D7 reads the playlists only); any change to the dashboard; Criterion 24/7 live channel.
