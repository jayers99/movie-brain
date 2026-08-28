# Thumbprint T5 — the ingester switch (memo step 5) design

**Date:** 2026-08-28 · **Branch:** `feature/T5-thumbprint-ingesters` · **Base:** `main` @ `8195c67` **Inputs:** memo `2026-08-25-thumbprint-design.md` §3/§4/§7 step 5/§8; T5 handoff `2026-08-28-thumbprint-t5-handoff.md`; `.claude/rules/thumbprint.md`; `.claude/rules/sync-flow.md`.

## 1. Goal

Turn the resolver on: every film that reaches the keying point — a new Criterion listing, a Mode-B promotion, an owned Apple title — is keyed by `domain/thumbprint.resolve()` (auto matches through `record_tmdb_match`, non-matches as durable `no-match-reviewed` A/B/C rows), and owned import / Mode-B look an existing work up by its tt BEFORE creating a film, so no new twins are minted. Series get a home (`films.kind = 'series'`, IMDb id only). `pick_tmdb_match` / `TmdbArbiter` leave `sync`.

## 2. What the code actually looks like today (findings that shaped this spec)

1. **One keying point, not three.** Criterion, Mode-B and owned films are all *created* by title and *keyed* in one place: `availability.tmdb_step` → `pick_tmdb_match` over `films_needing_tmdb_match()` (films with no `tmdb` row). The switch is therefore one replacement there (T5a) plus tt-first lookup in the two creators (T5b).
2. **Claims are dead at ingest.** `Repository.add_claim` has one caller, `thumbprint backfill`. No ingester writes claims, so a film created after the T1 backfill has no `title_ingested` / runtime for the resolver's query. T5 makes every ingester write its claim.
3. **The live effect on existing data is ~0.** Live (2026-08-28, read-only): 4,548 undisposed films, **0** without a `tmdb` row, 81 `tmdb.found=0` (T4's residue: 10 open `no-match`, 48 open `no-match-reviewed`, the rest resolved standing decisions), 23 director-less by the strict definition. Switching the keying point changes nothing for films already keyed; the rehearsal has to *manufacture* work (§8).
4. **A series cannot hold a `tmdb` id.** TMDB movie and TV ids share one integer namespace and `external_ids.tmdb` drives `/movie/{id}/watch/providers`. `find_by_imdb` reads `movie_results` only, so today `review resolve --tt tt0092337` (Dekalog) keys it imdb-only as `kind='movie'` and nobody notices. Q2 ("keyed by the IMDb series id") = imdb id only.
5. **OMDb `t=` still runs** for any film without an imdb id (`sync.py` OMDb loop). Memo §1: an unkeyed work is never enriched by title search.

## 3. Decisions (owner, 2026-08-28)

| # | decision | choice |
|---|---|---|
| D1 | scope | **both phases in one branch**: T5a keying point + claims at ingest; T5b tt-first in owned import and Mode-B promotion. Each phase gated and rehearsed on its own. |
| D2 | OMDb `t=` | **drop for new films**: the sync loop fetches by imdb id only; unkeyed films are skipped and counted. Existing `t=`-fetched records are left alone. |
| D3 | series | **auto-detect + `--series` override** on `review resolve --tt`: a TMDB `/find` tv / tv-episode hit with no movie hit ⇒ `kind='series'`, imdb only, no tmdb id; `--series` forces it when TMDB knows nothing. The resolver is untouched (`Type=series` candidates keep falling to review). |
| D4 | rehearsal | **re-key ~300 known films** on the scratch copy (strip ids + `tmdb` row, stratified), bar = 0 disagreements with the stored keys; plus a plain sync, an owned-import archive replay and one worked series drain. |
| D5 | keying order | the keying step moves **before** the OMDb loop, so a film keyed tonight gets its OMDb record by id tonight (today: next night). Providers stay last. `.claude/rules/sync-flow.md` is rewritten accordingly. |

Deferred (listed, not T5): retiring `rematch`, `pick_tmdb_match`, `TmdbArbiter` and `match_archive`'s year arbitration; `edition_year` at ingest (T2's verb owns it); series providers/dashboard; the T4 leftovers (twin `conflict`s #142/#421 etc., #180, #2355 colon-form edition merge).

## 4. T5a — the keying point

### 4.1 Shared pieces (application/thumbprint.py)

- `film_query(repo, film_id, title, year, director) -> Query` — T4's `_nomatch_query` promoted and shared: highest-precedence claim (criterion > metacritic > apple-tv → source `apple`), title/year from the claim (year falls back to `films.year`), director from `films.director`, apple runtime carried never scored. No claim → source `unknown` on the film's own title/year.
- `key_film(repo, tmdb, film_id, tt, tmdb_id, today, log) -> KeyResult` — the ONE write path extracted from `repair_nomatch`'s apply loop, verbatim semantics:
  1. live holder checks: `film_id_for_external('imdb', tt)` and, when `tmdb_id` is known, `film_id_for_external('tmdb', tmdb_id)` — another holder ⇒ `held` (nothing written);
  2. `tmdb_id` unknown ⇒ `tmdb.find_by_imdb(tt)`; `winner_year = tmdb.movie_year(tmdb_id)` when a tmdb id exists; TMDB weather ⇒ `error` (nothing written);
  3. `set_external_id(film_id, 'imdb', tt)` (IntegrityError ⇒ `held`);
  4. tmdb id ⇒ `record_tmdb_match(repo, tmdb_target(film_id), tmdb_id, winner_year)`; a result outside `matched/adopted/collision` is `[partial]` — logged and raised (CLI exit 1), the same loud-stop rule as T3/T4; no tmdb id ⇒ `upsert_tmdb(found=0)` is NOT written (an imdb-only film is `unlinked`, exactly T4's verdict);
  5. `omdb_imdb_id(film_id) != tt` ⇒ `mark_omdb_refresh`. Callers: `key_films` (sync), `repair_nomatch` (`match`/`keyed`), `resolve_review` (`--pick`/`--tt`), `import_owned` and `promote_top_n` (T5b). `repair_nomatch` and `resolve_review` keep their current CLI contracts and log lines; only their bodies change.
- `resolver_fetcher(cfg, root) -> tuple[CandidateFetcher | None, CandidateCache | None]` — the fetcher `repair nomatch` builds in `cli.py` (fixture read-only + `<config_dir>/nomatch-cache.json.gz` session cache, saved in a `finally`), shared by `sync`, `owned import`, `repair nomatch`. Needs BOTH a TMDB token and an OMDb key; otherwise `None` and the caller degrades (§4.4).

### 4.2 `key_films(repo, fetcher, tmdb, today, log) -> KeyStepResult` (availability.py)

Replaces the match loop at the top of `tmdb_step`. For each `films_needing_tmdb_match()` target (undisposed, no `tmdb` row, **`kind = 'movie'`**):

| verdict | write |
|---|---|
| `resolve()` → `match` | `key_film(...)`; `held` ⇒ `upsert_tmdb(found=0)` + durable `id-conflict` row (`value` = the held id, imdb or tmdb; detail names the holder) via `queue_review_once` — the same row `record_tmdb_match` queues today for a tmdb clash; `error` ⇒ counts a consecutive failure, film left without a `tmdb` row (retried next sync) |
| `resolve()` → `review` | `upsert_tmdb(found=0)` + `queue_review_once(tmdb, ReviewEntry(NO_MATCH_REVIEWED, film_id, detail=review_detail(v, q)))` — durable, idempotent, the same row shape T4 promotes to |
| `CacheMiss` / TMDB / OMDb weather | consecutive failure (5 ⇒ stop, `aborted=True`), film untouched |

Sync no longer mints plain `no-match` rows: `rebuild_no_match_queue` still runs (it drops rows of films that became `found=1` and honours resolved standing decisions) but only ever sees `found=0` films that already hold a durable row. `kind='series'` films are excluded from both `films_needing_tmdb_match` and `films_tmdb_missed` (§6).

`tmdb_step` keeps everything after the match loop (watchlist pass, first-check, weekly refresh) and loses its `arbiter` parameter. `TmdbStepResult.matched/missed` are fed from `KeyStepResult(keyed, reviewed, held, failed)`; `SyncResult` gains `tmdb_reviewed`.

### 4.3 Sync order (D5) — the new contract for `.claude/rules/sync-flow.md`

1. cheap check → 2. `merge_yearless` → 3. `record_catalog` (+ criterion claims) → 4. Mode-B promotion (+ metacritic claims; T5b resolve-first) → **5. keying (`key_films`)** → 6. OMDb by imdb id only → 7. TMDB providers (watchlist / first-check / weekly) + notifications.

The OMDb loop iterates `films_needing_lookup` + `films_needing_lookup_discovery` as today but resolves the imdb id through `_resolve_imdb_id` only; a film with no imdb id is **skipped** (no `omdb` row written, counted as `omdb_unkeyed` in `SyncResult`) — a skipped film re-enters the queue each run at zero API cost. `OmdbClient.lookup` (`t=`) loses its last caller and is deleted with its tests; `upsert_omdb`'s `year_fallback` column stays (schema is untouched).

### 4.4 Degradation

- No TMDB token ⇒ keying step skipped (log line), OMDb skipped for unkeyed films — same as today minus the title lookups.
- TMDB token but no OMDb key ⇒ `fetcher is None` ⇒ keying step skipped with a log line naming the missing key (the resolver's candidate pool needs OMDb `s=`/`i=`; the owner pays for OMDb, so this is a misconfiguration, not a mode).

### 4.5 Claims at ingest

`add_claim` (INSERT OR IGNORE on `UNIQUE(authority, value)`, `edition_label` from `parse_title(title).editions`, `edition_year` NULL) is called by:

| ingester | authority | value | title_ingested | year_claimed | runtime |
|---|---|---|---|---|---|
| `record_catalog` (criterion) | `criterion` | listing url | Criterion title | Criterion year | — |
| `create_from_staged` / `promote_top_n` | `metacritic` | slug | raw MC title | MC year | — |
| `match_archive` slug link | `metacritic` | slug | raw MC title | MC year | — |
| `import_owned` (match, create, key-collision) | `apple-tv` | raw Apple title | raw Apple title | field year | runtime_min |

`record_catalog` writes the claim inside its existing transaction against the SURVIVOR id (it already follows merged aliases). A claim that already exists (T1 backfill, prior sync) is a no-op.

## 5. T5b — tt-first in the two creators

### 5.1 `import_owned`

Gains `fetcher`/`tmdb` parameters (CLI wires `resolver_fetcher`; tests inject a cache-backed fake). Per Apple title, in order:

1. `q = make_query(raw title, field year, "apple", runtime_min=…)` (no director — Apple has none); `v = resolve(q, fetcher.fetch(q))`. Weather ⇒ this title falls through to step 3 with a log line (never aborts the import).
2. `v.kind == 'match'`: holder = `film_id_for_external('imdb', v.tt)` or, via the candidate's tmdb id, `film_id_for_external('tmdb', …)` — canonicalized. Holder ⇒ mark owned + apple claim, `matched += 1`. Done. (This is the twin killer: *Blade Runner (The Final Cut)* lands on `tmdb:78`.)
3. No holder, or `review`, or no fetcher: today's corpus path (`match_owned` tie/winner/ year-drift/create) unchanged, plus the apple claim on whichever film it marks.
4. A film **created** in step 3 while step 1 produced a `match`: `key_film()` immediately with `v.tt` / candidate tmdb id — the created film is born keyed and canonicalized to TMDB's year by `record_tmdb_match` (commerce guard). `held`/`error` ⇒ the film stays unkeyed and `key_films` picks it up at the next sync. A created film with a `review` verdict is likewise left for `key_films` (one resolver, one A/B/C row, next sync).

`OwnedReport` gains `keyed` and `resolved_to_existing`.

### 5.2 `promote_top_n`

Before `create_film` for an unclaimed, non-anomalous, non-tombstoned slug: `q = make_query(t.title, t.year, "metacritic")`, `v = resolve(...)`. `match` with a holder ⇒ `set_external_id(holder, 'metacritic', slug)` + metacritic claim on the holder, counted `linked_by_key` (no film created). `match` without a holder ⇒ create as today, then `key_film()` inline (born keyed). `review`, weather or no fetcher ⇒ create as today; `key_films` runs later in the same sync. `promote_top_n` loses `arbiter` from `sync`'s call (the `metacritic match` CLI verb and `match_archive` keep theirs — deferred).

`PromoteReport` gains `linked_by_key` and `keyed`.

## 6. Series (D3)

- `TmdbClient.find_by_imdb_any(tt) -> FindResult(movie_id: int | None, tv: bool)` — one `/find` call, `tv` true when `tv_results` or `tv_episode_results` is non-empty. `find_by_imdb` stays.
- `Repository.set_film_kind(film_id, kind)`; `films_needing_tmdb_match`, `films_tmdb_missed`, `films_tmdb_missed_targets` and `nomatch_worklist` add `AND f.kind = 'movie'`.
- `review resolve --tt X [--series]`: `--series`, or `FindResult.tv and movie_id is None` ⇒ `set_film_kind(rid, 'series')`, imdb id written, no tmdb id, outcome `keyed series imdb X`; the eval row is ratified as today (`expected_tmdb` empty). `--series` is rejected with `--pick`/`--none`/`--dismiss` and with a tt whose `/find` returns a movie (the human is contradicting TMDB — say so, don't write).
- `review list` shows `kind` after the film id when it is not `movie`.
- `merge_film`: the survivor keeps its own `kind`; a loser's differing kind is recorded in the disposition note (no automatic promotion of kind).
- The 22 open series/episode rows in the handoff drain by hand, one per call, after the live merge — NOT in T5's apply.

## 7. Tests (mirror the layers)

- `tests/unit/test_thumbprint_app.py`: `film_query` precedence, `key_film` results (`keyed`, `unlinked`, `held` on imdb, `held` on tmdb, `error`, `[partial]` raise, OMDb refresh mark).
- `tests/unit/test_tmdb.py`: `find_by_imdb_any` movie / tv / episode / none.
- `tests/features/tmdb.feature`: the search-mock scenarios (match once, no-match → review, id conflict, commerce re-release year adopt, year-collision, criterion no write-back, imdb-id OMDb lookup) rewritten against an injected `CandidateFetcher` over an in-memory `CandidateCache` built with the fixture key scheme (`ts:` `td:` `o:{…}`); provider scenarios keep `responses`. New: `review` → durable `no-match-reviewed` row with A/B/C detail; a `kind=series` film is never a keying target; no OMDb key ⇒ keying skipped; unkeyed film ⇒ no OMDb call.
- `tests/features/sync.feature`: step order (keyed film gets OMDb by id in the same run); criterion claim written; `t=` never called.
- `tests/features/owned.feature`: resolve-to-existing (edition title lands on the keyed work, no twin); created film born keyed; review verdict falls back to the corpus path; no fetcher ⇒ today's behaviour; apple claim written.
- `tests/features/metacritic.feature`: promotion links a slug to the existing keyed work; created film born keyed; metacritic claim written.
- `tests/features/review.feature`: `--tt` auto-detects a series; `--series` forces it; `--series` rejected on a movie tt; series film excluded from the no-match rebuild.
- `tests/step_defs/test_thumbprint.py` (nomatch): `repair nomatch` unchanged behaviour through `key_film`.
- Gates at every task: `uv run pytest`, `uv run ruff check .`, `uv run mypy`, `scripts/thumbprint_benchmark.py --assert` (n=557 / 0 / 92.0 % over 526 — the resolver and fixture are not edited, so this cannot move), `scripts/matching_benchmark.py --assert-dominance`. The eval CSV is never edited by hand.

## 8. Rehearsal (scratch copy, `MOVIE_BRAIN_CONFIG_DIR` set before every command, subagents too)

Scratch = a copy of `~/.config/movie-brain/` (db + keys + `metacritic/` + `appletv/` archives + `nomatch-cache.json.gz`). Every number is reported before the live yes.

1. **Plain sync** on the copy: expect 0 keying targets, 0 title lookups, exit 0 — proves the contract, not the resolver.
2. **Re-key 300** (`scripts/rehearsal/strip_keys.py`, scratch-only, refuses to run without `MOVIE_BRAIN_CONFIG_DIR` and writes `strip-manifest.json` with the stripped ids): stratified 100 criterion-with-director / 100 Mode-B / 100 apple-only films that hold both ids with `tmdb.found=1`; delete their `imdb`/`tmdb` external ids and `tmdb` rows; run `sync`; compare to the manifest. Report: keyed-agree / keyed-DISAGREE / reviewed / held / failed per stratum. **Bar: 0 disagree.** A disagreement is examined on the numbers, never patched into the CSV.
3. **Owned import replay**: `owned import` with `fetch` reading the newest `appletv/owned-*.txt` archive — report matched / resolved-to-existing / created / keyed / review-open, and every created film by name (the twin check).
4. **One series drain**: `review resolve <Dekalog row> --tt tt0092337` on the copy → shows `keyed series`, `kind='series'`, no tmdb id, rebuild leaves it alone.
5. Live, after the owner's yes: merge → one `sync` → the series rows one at a time. No live repair sweep is part of T5.

## 9. Docs to update in-branch

`CLAUDE.md` (sync command line, review resolve `--series`, the resolver is live), `.claude/rules/ thumbprint.md` (DARK bullet → live; `key_film` / `film_query` / `resolver_fetcher` contracts; series), `.claude/rules/sync-flow.md` (§4.3 order), `docs/multiple-movie-services.md` year precedence line (memo §6: TMDB > embedded year > Criterion ±2 > Apple field > Metacritic), handoff for the next step.
