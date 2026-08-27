# Thumbprint T3 — migrate guard, the 94 key disagreements, article-insensitive titles

**Date:** 2026-08-26 · **Status:** approved design (owner: relink may call TMDB at apply; Marrow's
NONE becomes a review row; verb name `repair disagreements`).
**Inputs:** handoff `docs/superpowers/handoffs/2026-08-26-thumbprint-t3-handoff.md`, memo
`docs/superpowers/research/2026-08-25-thumbprint-design.md` (§3, §4, §7 step 3, §8), T2 spec
`2026-08-26-thumbprint-t2-editions-design.md`. **Branch:** `feature/T3-thumbprint-disagreements`.

## 0. Scope

| in | out |
|---|---|
| A. `migrate` guard — no verb applies pending migrations implicitly | wiring `resolve()` into any ingester (resolver stays DARK) |
| B. `repair disagreements` — the 94 films whose OMDb `imdbID` ≠ TMDB `imdb_id`, keyed by eval group D | memo step 4 (rerun of the 201 `no-match` rows) — C only *measures* the 32 article films |
| C. article-insensitive title level in `resolve()` — evaluated, adopted only on the numbers | the `audit` check for disagreements (memo §6) — the verb's worklist query is the check |
| `resolve_review`: refresh a found-but-wrong OMDb stub after `--pick/--tt` | dashboard changes |

Gates at every step: `uv run pytest`, `ruff`, `mypy`, `scripts/thumbprint_benchmark.py --assert`
(baseline **n=484 / 0 wrong / 94.8 %**), `scripts/matching_benchmark.py --assert-dominance`.
`scripts/eval/thumbprint_eval_v1.csv` is written only by `eval_log.ratify`.

## 1. Live facts the design rests on (read-only, 2026-08-26)

- Schema v12. Disagreements (undisposed, OMDb found, OMDb tt ≠ COALESCE(external `imdb`,
  `tmdb_facts.imdb_id`)): **94**; every one has a `D-disagree` row and no D row is stale.
- By contract: **28** `expected_tt` = TMDB side (OMDb stub wrong) · **17** = OMDb side (TMDB link
  wrong; none of the 17 carries `expected_tmdb`) · **4** neither (Tiger #276, The Island #667,
  Visitation #1569, Birdman #3940 — all carry `expected_tmdb`) · **1** `NONE` (Marrow #338) ·
  **44** `proposed`. 59 of the 94 carry a Criterion listing; 1 has an `imdb` external id.
- `tmdb_step` searches by **title only** and never retries a `tmdb.found=0` film; a cleared link
  simply re-enters the `no-match` queue (`rebuild_no_match_queue` wipes and rebuilds `no-match`
  rows every sync). Sync's OMDb refetch (`_resolve_imdb_id`) prefers the stored `imdb` external
  id, else resolves it through the TMDB link — so a refetch is by id only once that id is right.
- `resolve_review --pick/--tt` calls `mark_omdb_refresh_if_missed` → a found-but-wrong stub is
  never refetched.
- Open `tmdb no-match` rows whose title starts with The/A/An: **32** (29 Criterion-listed).
  Only one article trap is in the eval CSV (E-benchmark *A Star Is Born* 1937).

## 2. A — migrate guard

- `init_db(db_path, *, apply: bool = False)`. A DB with **no `schema_version` table** bootstraps
  fully (first run, tests, scratch) — that is creation, not migration. A DB with pending
  migrations raises `PendingMigrations(pending=[…])` unless `apply=True`; `apply=True` keeps
  today's pre-migration backup.
- `Repository(db_path, *, migrate: bool = False)` passes through. `cli._repo()` never passes
  `migrate=True`; on `PendingMigrations` every verb (dashboard included) prints
  `pending migrations: 013_x.sql … — run 'movie-brain migrate --apply'` and exits 2.
- New verb `movie-brain migrate [--apply]`: dry run lists applied max + pending files; `--apply`
  is the ONLY code path that applies migrations to an existing DB. Read-only verbs cannot
  touch the schema by construction (there is no second path).
- Tests: fresh-path construction still works; an existing DB one version behind raises;
  `migrate --apply` applies + backs up; `status` on a behind DB exits 2 without writing.

## 3. B — `repair disagreements [--apply] [--yes] [--limit N]`

Same protocol as `repair twins/editions`: dry run lists every group with a `[verdict]` line via
`_plain`; `--apply` acts on confirmed actionable groups only; idempotent (a second run reports
only `conflict`/`review-open` lines).

**Worklist** = `Repository.key_disagreements()` (the §1 query: id, title, year, omdb_tt, tmdb_tt,
tmdb_id, criterion-listed, imdb external id) ∩ `load_disagreement_contract(csv)` = every
`D-disagree` row keyed by film id (status, expected_tt, expected_tmdb, title/year/source/director
as ingested). A disagreement with no D row → `conflict: no contract row`.

**Verdicts** (contract row decides; `tt_holders`/`tmdb_holders` = `external_id_holders`, computed
once before any write; `allowed` = the film itself):

| verdict | when | apply |
|---|---|---|
| `refetch` | verified, `expected_tt == tmdb_tt` | `set_external_id(imdb, expected_tt)`; `mark_omdb_refresh` |
| `relink` | verified, `expected_tt == omdb_tt` | `find_by_imdb(expected_tt)` → id: `set_external_id(imdb)` + `record_tmdb_match(target, id, movie_year)` (commerce guard: a Criterion-listed film keeps its year/key); no TMDB record → `clear_tmdb_link` + `set_external_id(imdb)` (`[relink] … unlinked`) |
| `adopt` | verified, matches neither, `expected_tmdb` present | `set_external_id(imdb)`; `record_tmdb_match(target, expected_tmdb, movie_year)`; `mark_omdb_refresh` |
| `review` | `proposed`, or verified `NONE` | queue durable `key-disagreement` row (below); never keys anything |
| `conflict` | disposed; expected tt/tmdb held by another film; `adopt` without `expected_tmdb`; `record_tmdb_match` returned `id-conflict`/`collision`; TMDB error | logged, skipped, counted |

- Every `record_tmdb_match` outcome other than `matched`/`adopted` is logged as `[partial]` and
  raises (the imdb write is already committed) — same loud-stop rule as T2.
- `has_listing` is honoured through `record_tmdb_match`'s commerce guard: the verb never writes
  `films.year`/`films.key`/`title` itself. The 59 Criterion films therefore never re-key.
- `mark_omdb_refresh` on `relink`/`adopt` too when OMDb's tt ≠ expected (always true for adopt).
- Report: `groups · refetch · relink · adopt · review · conflict · applied · declined`.

**The `key-disagreement` review row** (authority `tmdb`, durable — `rebuild_no_match_queue`
only touches `no-match`; `queue_review_once` makes it idempotent; a resolved one is a standing
decision): `value` = the CSV's proposed tt (or `NONE`), `detail` = `review_detail(verdict, query)`
where `verdict = resolve(query, candidates)` on `make_query(title_ingested, year_ingested, source,
director=…)` and candidates come from `CandidateFetcher(CandidateCache(fixture data, path=None),
tmdb, omdb)` — fixture hits are free, misses go to the live clients, nothing is saved to the
fixture. Without both API keys the row is still written with `review_detail(Verdict("review",
None, "no candidates", ()), query)` so `--tt/--none` remain possible. `review list` already
renders the A/B/C lines. Drain with `review resolve ID --pick A|B|C | --tt X | --none`, which
ratifies the proposed CSV row (`ratify` rewrites the same film_id + source).

**`resolve_review` fix**: after `--pick/--tt` keys a film whose OMDb payload `imdbID` ≠ chosen
tt, `mark_omdb_refresh` (new `Repository.omdb_imdb_id(film_id)`); `--none` on a
`key-disagreement` row leaves ids alone (a human decides later, as for Marrow).

## 4. C — article-insensitive title level (evaluate, then decide)

`title_level`: a candidate whose article-stripped normalized title equals the query's
article-stripped form counts as **3 only when no candidate matches article-exactly**; article
= leading `the|a|an` (ASCII, after `norm_title`-style folding — English articles only, on
purpose: *La Strada*/*Strada* is not the same case). No new reason strings — the level is a
per-candidate signal, and verdict reasons are unchanged. Evaluation, in this order:
1. Unit traps with hand-built candidates: *The Thing* 1982 vs *Thing* 2011 (article-exact wins;
   article-only tier never outranks it), *A Star Is Born* 1937/1954/1976 (year still decides),
   *The Bride of Frankenstein* → *Bride of Frankenstein* (matches).
2. Gate: `thumbprint_benchmark.py --assert` must stay 0 wrong and ≥ 94.8 % auto.
3. Live measurement (read-only network, scratch config): resolve the 32 open article films with
   the rule on and off; report auto/review counts and the reasons. **Adoption is a separate owner
   decision on those numbers**; step 4 of the memo (rerunning them) is not in T3.

## 5. Rehearsal and live protocol

`SCRATCH` = `cp` of live DB + `appletv/` + key files, `MOVIE_BRAIN_CONFIG_DIR=$SCRATCH` exported
before **any** `movie-brain` command (subagents too). Rehearse: `migrate` (dry, and against a
copy with a fake pending migration), `repair disagreements` dry → `--apply --yes --limit N` in
batches → `review list --reason key-disagreement` → one `review resolve --pick` with
`--eval-csv` pointed at a scratch copy of the CSV → `sync` → `grep -c 'external id conflict for'
sync.log` = 0 → `audit run --no-tmdb` tally not larger → before/after counts of the §1 query.
Live: dry run → owner yes → batches → counts → one sync → ask before merge.

## 6. Docs

`CLAUDE.md` (commands: `migrate`, `repair disagreements`; migration bullet), `.claude/rules/
thumbprint.md` (disagreement contract, `key-disagreement` reason, article rule if adopted),
handoff status note.
