## Status (2026-08-26, T3 build)

Tasks 1–8 landed on `feature/T3-thumbprint-disagreements` (not merged): `migrate [--apply]` guard
(`init_db(apply=)`/`PendingMigrations`, every verb exits 2 when behind); `repair disagreements
[--apply] [--yes] [--limit N]` (group-D contract, five verdicts, durable `key-disagreement`
review); `resolve_review` refresh-on-mismatch fix; article-insensitive `title_level`/`article_norm`
evaluated and adopted BEHIND the gate. Gate: `scripts/thumbprint_benchmark.py --assert` →
n=484 / 0 wrong / 94.8% (unchanged with the article rule on). Scratch rehearsal and live batches
(both `migrate` and `repair disagreements`) have NOT been run yet — do that before merging. Live
measurement of the 32 open article `no-match` films (rule on vs. off) is also still pending;
adoption on live data is a separate owner decision per spec §4.

---

# Thumbprint T3 handoff — the 94 OMDb/TMDB key disagreements (memo step 3)

**Written:** 2026-08-26, end of the T2 session. **For:** a fresh session. **Repo:** `main` @ `d74a31b`
(T2 merged, pushed, clean). **Live DB:** schema v12; 15 edition groups applied; snapshot
`movie-brain.db.bak-pre-t2`; post-apply `sync` clean (0 `external id conflict for`).

## Read first (in this order)
1. `CLAUDE.md` + `.claude/rules/thumbprint.md` (resolver DARK; gate before change; external_ids policy).
2. Memo `docs/superpowers/research/2026-08-25-thumbprint-design.md` — §3 evidence model, §4 A/B/C
   contract, §5 benchmark, **§7 step 3**, §8 owner decisions.
3. T2 spec + plan: `docs/superpowers/specs/2026-08-26-thumbprint-t2-editions-design.md`,
   `docs/superpowers/plans/2026-08-26-thumbprint-t2-editions.md` (status note at the top = every live
   number, the rulings, and the incident).

## What T2 delivered (don't rebuild)
- `repair editions` (`application/repair.py`): contract-checked twin/no-twin fold; `_edition_blockers`
  (tt/tmdb/key holders over ALL films; a film with ANY Criterion listing is never re-keyed);
  `[partial]` + RuntimeError on a post-merge keying refusal. **Idempotent: re-running reports
  `groups: 1 · conflict: 1` (#1909) forever — that is correct, not work.**
- Migration 012: `external_ids` PK `(film_id, authority, value)`; `KEY_AUTHORITIES={tmdb,imdb}` single
  per film by policy (`set_external_id` preserves `first_seen`); claim authorities repeat;
  `merge_film` moves claim ids / drops duplicate key ids; read models take ONE metacritic slug via
  `_MC_SLUG_SQL`; `record_catalog` is INSERT-only for the criterion URL.
- Repo primitives: `key_work`, `films_for_editions`, `external_id_holders(authority)`,
  `has_listing(film_id, source)`, `set_claim_edition_year`, `claim_for_film_authority`, `external_ids_all`.
- `review resolve ID --pick A|B|C | --tt X | --none` (+ hidden `--eval-csv`), `review list` renders
  A/B/C lines from `review_detail(verdict, query)` / `parse_review_detail`; `TmdbClient.find_by_imdb`;
  `application/eval_log.py::ratify` = the ONLY programmatic eval-CSV writer (rewrites a matching
  `proposed` row, else appends `F-human`). **Rehearsed on scratch only — no live ratification yet.**
- Gate: `scripts/thumbprint_benchmark.py --assert` → n=483 / 0 wrong (the 483rd row = the live F-human Bride of Frankenstein; fixture refreshed for it).

## Live numbers today (read-only, 2026-08-26 late)
| what | count |
|---|---|
| OMDb `imdbID` vs TMDB `imdb_id` (undisposed, OMDb found) | **agree 4,136 · disagree 94** · OMDb-only 136 · TMDB-only 2 · neither 186 |
| eval group D (`D-disagree`) | 94 rows: **50 verified · 44 proposed** (1 `NONE` expectation) |
| all `proposed` eval rows | **45** (44 D + `C-edition` #4503 Moonwalk One); the benchmark reports **38** of them (those with a non-empty `expected_tt`) — *the T2 brief said "4"; that was a counting error (awk split on commas inside notes). Owner decision Q1 still stands: ratify through the A/B/C flow.* |
| open reviews | tmdb `no-match` 201 (after T2b + Bride of Frankenstein) · metacritic `expected-miss` 111 (was 96 — sync growth) · apple-tv `year-drift` 51 · MC small reasons 14 |
| dispositions / imdb ids / edition_year claims | 116 / 570 / 16 (after T2b same-year fold) |

## T3 scope (memo §7 step 3)
The 94 films whose OMDb record and TMDB link name different works. Memo's split (pre-T1 numbers,
re-derive live): **17** clear the wrong TMDB link · **27** refetch OMDb by the TMDB tt (the OMDb
stub is the wrong one) · **5** adopt the director-credit-found record (Tiger, Nostos, Visitation,
The Island, Birdman) · **45** go through A/B/C.

Shape it as ONE verb, `repair disagreements` (or `keys`), same protocol as `repair twins/editions`:
- **Worklist** = live disagreement query (above) ∩ eval group D. Group D `verified` rows are the
  contract (`expected_tt`/`expected_tmdb`); `proposed` rows are NOT auto-applied — they render as
  A/B/C `match_review` rows (authority `tmdb`, reason from `resolve()`; `review_detail(verdict, query)`
  with the query!) and the owner drains them with `review resolve --pick/--tt/--none`, which
  ratifies the CSV row (`ratify` flips proposed → verified). That is what C in T2 was built for.
- **Verdicts** (contract row decides which side is right):
  - `expected_tt == TMDB's tt` → OMDb stub wrong → `mark_omdb_refresh` (refetch by id via the TMDB
    link; no OMDb `t=` ever) — the "27".
  - `expected_tt == OMDb's tt` → TMDB link wrong → `clear_tmdb_link` (+ `external_ids imdb` = tt,
    then the sync's TMDB step re-links from the imdb id, or set tmdb via `find_by_imdb`) — the "17".
  - `expected_tt` matches neither → adopt the contract's record: imdb+tmdb from the row via
    `set_external_id` / `record_tmdb_match` (year adoption rules apply), OMDb refresh — the "5".
  - no verified row / holder clash / listing hazard → `review` (A/B/C row) or `conflict`, never guessed.
- **Guards to reuse:** `external_id_holders` for tt/tmdb clashes; `has_listing` before any
  `films.key` change (a Criterion-listed film must NOT be re-keyed — T2's Critical; year changes on
  Criterion films are also key changes → route through `record_tmdb_match`'s commerce guard);
  `_NOT_DISPOSED` everywhere; every `[verdict]` line via `_plain`.
- **After the batch:** `sync` once and grep `external id conflict for`; `audit run --no-tmdb`
  tally must not grow; `scripts/thumbprint_benchmark.py --refresh` ONLY after a ratification
  batch (needs both keys) — cache-miss rows score as `review`, never a gate failure.

## Pattern found after the handoff was written (2026-08-26, late)
**Leading articles.** #3141 *The Bride of Frankenstein* (owned, MC 95) sat in `tmdb no-match` because
TMDB/IMDb/OMDb title it *Bride of Frankenstein*; `norm_title` and the resolver grammar keep the
article, so the exact-title level fails even though TMDB search returns the right film first.
**32 of the 209 open no-match films start with The/A/An.** Resolved live by hand:
`review resolve 6274 --tt tt0026138` → the first live `F-human` eval row (title as ingested keeps
the article, so the gate now carries the case). T3 candidate rule: an article-insensitive title
level in `resolve()` (benchmark it — *The Thing* / *Thing*, *A Star Is Born* traps), reason string
added to the contract, then rerun the 32 through step 4.

## Traps
- **Set `MOVIE_BRAIN_CONFIG_DIR` before ANY `movie-brain` command in rehearsal or in a subagent.**
  `Repository.__init__` migrates on construction — a subagent's `review resolve --help`-era smoke
  test applied 012 to the live DB in T2 (schema-only, backed up, disclosed). Consider a `migrate`
  verb / `init_db` refusing pending migrations without a flag as T3's first small task.
- `clear_tmdb_link` deletes the `tmdb` external id only; check what it does to `tmdb_facts`/
  `listings` from TMDB providers before relying on it (read `database.py:926`).
- `external_ids_for()` returns a dict — read only `imdb`/`tmdb` through it; `external_ids_all` for
  claim authorities.
- `parse_review_detail` slices at the last `}` — a resolution note containing `}` would parse as
  None on a resolved row (unreachable today; use `json.JSONDecoder().raw_decode` if you touch it).
- Deferred from T2: #1909 Scenes from a Marriage (Criterion-listed, waits for the ingester switch).
  (#2416 and the other same-year editions were folded by T2b on 2026-08-26 — `repair editions` now
  handles year == work year; see the plan status note.)
- Never edit `scripts/eval/thumbprint_eval_v1.csv` by hand; `ratify` is the writer. Never run
  `repair twins`/`repair editions --apply` expecting work.

## Process rules that held (keep them)
Spec → plan → subagent-driven TDD with per-task review → final whole-branch review → **scratch
rehearsal** (`cp` the live DB + `appletv/` + key files; `MOVIE_BRAIN_CONFIG_DIR=$SCRATCH`) → paste
the dry run → owner **yes** → `--apply --yes --limit N` in batches → before/after counts → one
`sync` → ask before merging. The rehearsal caught the T2 Critical (#1909) only because the final
reviewer simulated the next sync — do that again.

## Paste-ready entry prompt
> T3 of the thumbprint work: read `docs/superpowers/handoffs/2026-08-26-thumbprint-t3-handoff.md`,
> the memo `docs/superpowers/research/2026-08-25-thumbprint-design.md` (§3–§5, §7 step 3, §8),
> CLAUDE.md and `.claude/rules/thumbprint.md`. Deliver: (1) T3 spec — `repair disagreements`
> for the 94 OMDb/TMDB key disagreements keyed by eval group D (verified rows = contract; proposed
> rows → A/B/C `match_review` rows drained by `review resolve --pick/--tt/--none`, ratified into the
> CSV), plus a `migrate` guard so no CLI command migrates the live DB implicitly; (2) plan → TDD;
> gates green at every step (`uv run pytest`, ruff, mypy, `scripts/thumbprint_benchmark.py --assert`
> n=482/0/94.8 %, `scripts/matching_benchmark.py --assert-dominance`); never edit the eval CSV by
> hand; (3) rehearse every live verb on a scratch copy (`MOVIE_BRAIN_CONFIG_DIR`) including a
> simulated next `sync`, show me the numbers, then batches after my yes. Resolver stays dark. Branch
> `feature/T3-thumbprint-disagreements`; don't merge without asking. Short, scannable answers; push
> back where the handoff or memo looks wrong.
