# Thumbprint T4 — `repair nomatch` (memo step 4) design

**Date:** 2026-08-27 · **Branch:** `feature/T4-thumbprint-nomatch` · **Base:** `main` @ `c689b31`
**Inputs:** memo `2026-08-25-thumbprint-design.md` §3/§4/§7 step 4/§8; T4 handoff; `.claude/rules/thumbprint.md`.

## 1. Goal

Rerun the open `tmdb/no-match` films (201 live today) through `domain/thumbprint.resolve()`:
auto matches are keyed through the sync's own write path (`record_tmdb_match`); non-matches become
DURABLE A/B/C review rows the owner drains with `review resolve --pick/--tt/--none`. The resolver
stays DARK for ingesters (memo step 5 is next). Two small follow-ups ride along: the `--pick`
`find_by_imdb` fallback and a report that counts skips.

## 2. Live profile (read-only, 2026-08-27)

| slice of the 201 open rows | n |
|---|---|
| `films.director` present | 147 (54 director-less) |
| claims criterion / metacritic / apple-tv (12 films hold >1 source) | 156 / 29 / 28 |
| OMDb `found=1` (a title-lookup tt exists — may be wrong) | 89 |
| already hold an `imdb` external id | 9 |
| resolved `no-match` rows (standing decisions) | 107 |

## 3. Decisions that differ from the handoff (approved 2026-08-27)

1. **Auto matches do NOT resolve the `no-match` row.** A resolved `no-match` row is a permanent
   "dismissed" for that film in `rebuild_no_match_queue`, which would break the later
   `repair links --film` + `sync` + `--tmdb-id` relink path. Instead `--apply` ends by calling
   `rebuild_no_match_queue(repo, today)`: a matched film has `tmdb.found=1`, leaves
   `films_tmdb_missed`, and its row drops exactly as the next sync would drop it.
2. **Session candidate cache.** `CandidateCache(path=None)` would refetch ~2k TMDB/OMDb calls on
   every dry run and again on `--apply`. The verb uses `<config_dir>/nomatch-cache.json.gz`
   (seeded from the eval fixture's data, saved after each run). The eval fixture
   `scripts/eval/fixtures/cand_cache.json.gz` is still NEVER written by the verb.
3. **imdb-keyed films skip `resolve()`.** A film already holding an `imdb` external id has its
   identity; verdict `keyed` = `find_by_imdb(tt)` → `record_tmdb_match`. No TMDB record →
   `unlinked` (listed, not work).
4. **Rebuild guard for the durable reason.** `rebuild_no_match_queue` treats a resolved
   `no-match-reviewed` row like a resolved `no-match` row, so `--none` on a promoted row does
   not loop (film still found=0 → re-queued → rerun → promoted again).

## 4. The verb

`movie-brain repair nomatch [--apply] [--yes] [--limit N]` — `application/repair_keys.py`
(`repair_disagreements` moves there in a separate chore commit; `repair.py` keeps the rest).

### 4.1 Worklist and query

Open `tmdb` rows with `reason = 'no-match'` whose film is undisposed, ordered by film id. A film whose row was already promoted to `no-match-reviewed` (and has no `no-match` row) is also listed, so it audits as `review-open` rather than vanishing from the worklist.
Per film, the query is `make_query(title, year, source, director=films.director, runtime_min=rt)`:

- source claim = the film's claim with precedence `criterion` > `metacritic` > `apple-tv`
  (`apple-tv` maps to query source `apple`); title = `claim.title_ingested`, year =
  `claim.year_claimed` falling back to `films.year`; runtime = the apple claim's
  `runtime_min` (shown in the row, never decides — Q3).
- no claim at all → `films.title` / `films.year`, source `unknown` (apple-field class).

### 4.2 Candidates

`CandidateFetcher(CandidateCache(data, path=<config_dir>/nomatch-cache.json.gz), tmdb, omdb)`
where `data` starts as a copy of the eval fixture's data. Cache saved after the audit pass.
`CacheMiss` / `requests.RequestException` / `AuthError` per film → verdict `conflict`
(`TMDB error: …`), never a write.

### 4.3 Verdicts (computed for every film before any write)

| verdict | when | `--apply` action |
|---|---|---|
| `keyed` | film holds `imdb` tt and `find_by_imdb(tt)` → id not held elsewhere | `record_tmdb_match` (+ `mark_omdb_refresh` if OMDb's tt ≠ tt) |
| `unlinked` | holds `imdb` tt, TMDB has no record | none (non-actionable, listed) |
| `match` | `resolve()` kind `match`; tt not held by another film; tmdb id from the candidate or `find_by_imdb` and not held elsewhere | `set_external_id(imdb)` → `record_tmdb_match` → `mark_omdb_refresh` if `omdb_imdb_id ≠ tt` |
| `review` | `resolve()` kind `review` | `repo.promote_review(row_id, reason='no-match-reviewed', detail=review_detail(verdict, query))` — same row, id + `created_at` kept |
| `review-open` | film already has an open `no-match-reviewed` row (the promoted row itself, listed via the worklist) | none |
| `conflict` | tt/tmdb held by another film · TMDB/OMDb error · `record_tmdb_match` returned `collision`/`id-conflict` | none; the post-`record_tmdb_match` case logs `[partial]` and raises (CLI exit 1) |

Holder maps (`external_id_holders('imdb'/'tmdb')`, every film incl. disposed) are read once
before the loop; `film_id_for_external` is re-checked live immediately before each write (T3
lesson: the batch's own writes). `sqlite3.IntegrityError` on `set_external_id` → `conflict`.

`match` writes imdb BEFORE `record_tmdb_match` so sync's `_resolve_imdb_id` refetches OMDb by
the stored tt. Commerce guard: `TmdbMatchTarget.commerce` is false for Criterion-listed films, so
`record_tmdb_match` never re-years/re-keys them.

`--limit N` slices the ACTIONABLE verdicts only (`keyed`, `match`, `review`); `unlinked`,
`review-open`, `conflict` are always listed in full and spend none of the budget.

After the loop on `--apply`: `rebuild_no_match_queue(repo, today)`.

### 4.4 Report

`NomatchReport(groups, keyed, unlinked, match, review, review_open, conflict, applied, declined,
skipped)` — `skipped` counts every actionable group that was NOT written on `--apply` for a
runtime reason (held id discovered live, TMDB error, no client). Dry run prints one line per
film: `#id 'title' (year) dir=… src=… → VERDICT reason [A tt… / B … / C …]`.

### 4.5 CLI

`repair_app.command("nomatch")`, wired like `disagreements`: `_repo()` first (migrate guard),
then TMDB token + OMDb key → `TmdbClient` + `OmdbClient`; no clients → every film `conflict
(no client)`, dry run still lists the worklist. Exit 1 on the `[partial]` raise.

## 5. Durable reason `no-match-reviewed`

- Written only by `repair nomatch` (promotion in place via new `Repository.promote_review`).
- `rebuild_no_match_queue`: a film with an OPEN `no-match-reviewed` row is already excluded
  (`durably_flagged` = any open non-`no-match` row); add RESOLVED `no-match-reviewed` rows to the
  `dismissed` set.
- `review resolve` on it: `--pick/--tt/--none` (existing thumbprint path — authority tmdb,
  film row) and `--dismiss`; `--tmdb-id` stays limited to `no-match`. Each `--pick/--tt/--none`
  ratifies through `eval_log.ratify` as today (`F-human`).
- `review list --reason no-match-reviewed` renders A/B/C (already generic on JSON details).

## 6. `--pick` fallback (`application/review.py`)

When the picked candidate has `tmdb_id None` and a client is given: `chosen_tmdb =
client.find_by_imdb(tt)`, `year = client.movie_year(chosen_tmdb)`; still `None` → warn as
`--tt` does. Existing behaviour otherwise unchanged.

## 7. Eval / gates

- Auto matches are the algorithm's own verdicts → NOT ratified, no new CSV rows (the gate would
  score itself). Human resolutions ratify as today.
- Spot check: the rehearsal shows the full auto-match list (title/year/director → candidate);
  wrong ones are fixed via `repair links --film` + `review resolve --tt`, which ratifies. Undo
  BEFORE the next `sync` — once a film holds both ids with `tmdb.found = 1` it audits `linked`
  and is never re-keyed.
- Article rule: if any auto match is WRONG on an article title, revert `92efefc`+`d672da3`.
- Gates at every step: `uv run pytest`, `ruff check .`, `mypy`,
  `scripts/thumbprint_benchmark.py --assert` (n=528 / 0 / 92.0 %),
  `scripts/matching_benchmark.py --assert-dominance`. Never edit the eval CSV by hand.

## 8. Tests

- unit `tests/unit/test_repair_nomatch.py`: verdict table (keyed/unlinked/match/review/conflict
  incl. held tt, held tmdb, TMDB error, batch-local IntegrityError), `--limit` slices actionable
  only, promote-in-place keeps id/created_at, `[partial]` raise, report counts incl. `skipped`,
  `rebuild_no_match_queue` guard on resolved `no-match-reviewed`.
- unit `tests/unit/test_database.py`: `promote_review`.
- BDD `tests/features/thumbprint.feature`: dry run writes nothing; `--apply` keys a match and
  promotes a review; `--none` on the promoted row survives a sync rebuild.
- `tests/unit/test_cli.py`: wiring + exit codes; `--pick` fallback in `tests/step_defs/test_review.py`.

## 9. Rehearsal + rollout (one at a time)

`SCRATCH` = copy of live DB + key files + `appletv/`; `export MOVIE_BRAIN_CONFIG_DIR=$SCRATCH`
before EVERY command (subagents too). Dry run → numbers → `--apply --yes` in batches → `sync`
+ `grep 'external id conflict for'` → before/after counts → owner **yes** → same on live in
`--limit` batches → one live `sync` → drain `no-match-reviewed` rows one batch at a time with a
recommended verdict per row → `thumbprint_benchmark.py --refresh` after a ratification batch.
Merge only when asked.

## 10. Out of scope

Ingester switch (step 5); Apple runtime as evidence; `expected-miss` / `year-drift` reviews;
audit verdict pass; transliteration folding of director names.
