# Thumbprint T4 handoff — memo step 4: rerun the 201 open `no-match` rows through `resolve()`

**Written:** 2026-08-27, end of the T3 session. **For:** a fresh session. **Repo:** `main` @ `c689b31`
(T3 merged + pushed, clean). **Live DB:** schema v12; snapshot `movie-brain.db.bak-pre-t3` (pre-T3
state); post-T3 `sync` clean (0 `external id conflict for`).

## Read first (in this order)
1. `CLAUDE.md` + `.claude/rules/thumbprint.md` (resolver DARK for ingesters; gate baseline
   **n=528 / 0 wrong / 92.0 %**; `migrate --apply` is the only schema path; `key-disagreement`
   contract; article rule).
2. Memo `docs/superpowers/research/2026-08-25-thumbprint-design.md` — §3 evidence model, §4 A/B/C
   contract, **§7 step 4**, §8.
3. T3 spec + plan: `docs/superpowers/specs/2026-08-26-thumbprint-t3-disagreements-design.md`,
   `docs/superpowers/plans/2026-08-26-thumbprint-t3-disagreements.md`; T3 handoff status block
   (`2026-08-26-thumbprint-t3-handoff.md`) for the live numbers and rulings.

## What T3 delivered (don't rebuild)
- `movie-brain migrate [--apply]`: `init_db(apply=)` raises `PendingMigrations` on a behind DB;
  every verb exits 2 with the hint; fresh DBs bootstrap. **Subagents can no longer migrate the live
  DB by accident — but still export `MOVIE_BRAIN_CONFIG_DIR` before ANY command in rehearsal.**
- `repair disagreements [--apply] [--yes] [--limit N]` (`application/repair.py`): group-D contract,
  verdicts `refetch/relink/adopt/review/pending/review-open/conflict`, holder + error checks before
  every write, durable `key-disagreement` reviews (`review_detail(verdict, query)` from the fixture
  read-only + live clients, never saved). `--limit` slices ACTIONABLE groups only. Steady state
  today: `groups: 1 · review-open: 1` (Marrow #338, verified unkeyed) — that is correct, not work.
- Repo: `key_disagreements()`, `omdb_imdb_id()`, `omdb_needs_refresh()`; `resolve_review` refreshes a
  found-but-wrong OMDb stub after `--pick/--tt`; `eval_log.ratify` is idempotent on an already-verified
  row. `domain/thumbprint.article_norm` + `title_level(article_ok=)`; fetcher `plausible()` widened.
- Live: 94 disagreements applied (28 refetch · 17 relink · 3 adopt), 45 rows ratified by the owner
  (`--pick/--tt/--none`) → eval CSV has **0 proposed rows**; fixture refreshed (+53 keys). The Cup
  #1018 relinked (TMDB 14521); Birdman #3940 merged into #3552.

## Live numbers today (read-only, 2026-08-27)
| what | count |
|---|---|
| open reviews | tmdb `no-match` **201** (156 Criterion-listed · 28 owned · 54 director-less) · metacritic `expected-miss` 114 · apple-tv `year-drift` 51 · MC small reasons 14 |
| films (undisposed) / dispositions | 4,549 / 117 |
| external ids imdb / tmdb · claims | 661 / 4,347 · 5,419 |
| eval CSV | 529 rows, 0 proposed; gate n=528 / 0 / 92.0 % |
| audit_flags / verdicts | 996 / 0 (human verdict pass still pending — separate track) |

## T4 scope (memo §7 step 4)
Rerun the 201 open `tmdb no-match` films through `resolve()` and key the auto matches; the rest
become A/B/C reviews. Evidence: the T3 article measurement resolved **22 of 31** article films
(20 `director corroborated`); the memo estimated ≈104 auto of the original 299.

Shape: ONE verb, `repair nomatch [--apply] [--yes] [--limit N]` (or `review rerun`), same protocol:
- **Worklist** = open `tmdb/no-match` rows (undisposed films). Query = `make_query(title, year,
  source, director=films.director)` — source from the film's claims (`criterion` / `metacritic` /
  `apple`), runtime shown never deciding (Q3).
- **Candidates**: `CandidateFetcher(CandidateCache(fixture data, path=None), tmdb, omdb)` exactly as
  `repair disagreements` does — nothing saved to the fixture from the verb.
- **Verdicts**: `match` (kind `match`, tt not held elsewhere, tmdb id via candidate or
  `find_by_imdb`) → `set_external_id(imdb)` + `record_tmdb_match` (commerce guard = Criterion films
  keep year/key) + `mark_omdb_refresh` if OMDb's tt differs + resolve the no-match row (note
  `repair nomatch <reason> <date>`); `review` → rewrite the no-match row's `detail` with
  `review_detail(verdict, query)` so `review list` shows A/B/C (the row already exists — UPDATE, don't
  queue a second one; `rebuild_no_match_queue` wipes/rebuilds `no-match` rows each sync, so decide
  whether the A/B/C detail must survive that: probably promote them to a durable reason, e.g.
  `no-match-reviewed`); `conflict` (tt/tmdb held, TMDB error) → skip loudly.
- **Guards**: `external_id_holders` for tt/tmdb; `film_id_for_external` live pre-write check
  (T3 lesson); errors caught before any write; `[partial]` + raise only after `record_tmdb_match`
  returns `collision`/`id-conflict`.
- **Eval**: every auto match is NOT ratified (it's the algorithm's own verdict — the gate would score
  itself); every human `--pick/--tt/--none` on a review row IS (existing `ratify`). Consider an
  `F-auto` sample (e.g. 30 random auto matches) verified by the owner as a spot check.
- **After**: one `sync` + grep `external id conflict for`; `thumbprint_benchmark.py --refresh`
  after a ratification batch only.

## Small follow-ups to fold into the T4 plan
- `review resolve --pick` should fall back to `TmdbClient.find_by_imdb(tt)` when the picked candidate
  is OMDb-only (`tmdb_id None`) — The Cup was left mislinked by this in T3.
- Article rule: measured identical on/off on the 31 live article films; kept behind the gate. T4's
  rerun is the real test — revert `92efefc`+`d672da3` if it ever produces a WRONG.
- `DisagreementsReport` has no `skipped` counter (held tt/tmdb, TMDB error, no client are log-only);
  copy the better shape into the new verb's report (count skips).
- `repair.py` is ~1,100 lines; the new verb is a good moment to split `repair_disagreements` +
  `repair_nomatch` into `application/repair_keys.py` (chore, separate commit).

## Traps
- `rebuild_no_match_queue` (sync) REPLACES all unresolved `no-match` rows every run: any detail you
  write on a `no-match` row is lost at the next sync unless the reason is durable.
- `queue_review_once` dedupes open rows on (reason, film_id) and resolved on (reason, film_id, value).
- `_resolve_imdb_id` in sync prefers the stored `imdb` external id — write it before
  `mark_omdb_refresh`, or the refetch uses the TMDB link's tt.
- `tmdb_step` never retries a `tmdb.found = 0` film; `repair links --film` + sync + `--tmdb-id` is
  the manual relink path (used for The Cup).
- `--limit` must slice actionable groups only, or batches re-hit the head (T3 rehearsal finding).
- Never run `repair disagreements --apply` expecting work; never edit the eval CSV by hand.
- A subagent that runs `git checkout .` wipes every agent's uncommitted edits — tell implementers to
  revert by path only.

## Process rules that held (keep them)
Spec → plan → subagent-driven TDD with per-task review → final whole-branch review → scratch
rehearsal (`cp` live DB + key files + `appletv/`; `MOVIE_BRAIN_CONFIG_DIR=$SCRATCH`) including a
simulated next `sync` → paste the dry run → owner **yes** → `--apply --yes --limit N` batches →
before/after counts → one `sync` → drain reviews one batch at a time with a recommended verdict per
row → ask before merging.

## Paste-ready entry prompt
> T4 of the thumbprint work (memo step 4): read
> `docs/superpowers/handoffs/2026-08-27-thumbprint-t4-handoff.md`, the memo
> `docs/superpowers/research/2026-08-25-thumbprint-design.md` (§3, §4, §7 step 4, §8), CLAUDE.md and
> `.claude/rules/thumbprint.md`. Deliver: (1) T4 spec — `repair nomatch` reruns the 201 open tmdb
> `no-match` films through `resolve()`: auto matches keyed through `record_tmdb_match` (Criterion
> films never re-keyed), non-matches become durable A/B/C review rows I drain with `review resolve
> --pick/--tt/--none`; plus the `--pick` `find_by_imdb` fallback and a `skipped` counter; (2) plan →
> subagent-driven TDD; gates green at every step (`uv run pytest`, ruff, mypy,
> `scripts/thumbprint_benchmark.py --assert` n=528/0/92.0 %, `scripts/matching_benchmark.py
> --assert-dominance`); never edit the eval CSV by hand; (3) rehearse every live verb on a scratch
> copy (`MOVIE_BRAIN_CONFIG_DIR` before any command, subagents too) including a simulated next
> `sync`, show me the numbers, then batches after my yes. Resolver stays dark for ingesters (step 5
> is next). Branch `feature/T4-thumbprint-nomatch`; don't merge without asking. Short, scannable
> answers; push back where the handoff or memo looks wrong.
