# Handoff: M2 (authority canonicalization + rematch) landed → M3 (repair & merge surface)

**Written:** 2026-08-24, end of the M2 session. Read this alongside
`docs/superpowers/specs/2026-08-23-matching-overhaul-design.md` (binding spec for M1–M3,
M1 and M2 Done lines filled in) and CLAUDE.md (updated on the M2 branch) before any M3 work.

## Status — M2 is MERGED to `main` and pushed (through `ba72e94`)

Commits `a0317a4..ba72e94` (plan + Tasks 1–7) fast-forwarded onto `main` 2026-08-24 and
pushed; post-merge docs/repair commits through `d36203b` (M2 Done line, this handoff, the
Metropolis banking, backlog item 9). Merged result verified: 388 tests, ruff, mypy, and
`scripts/matching_benchmark.py --assert-dominance` all green. Worktree and branch deleted.
Final whole-branch review verdict: ready to merge, zero Critical/Important findings.

**What landed:**
- `infrastructure/tmdb.py` — `TmdbArbiter` (principle 4: one cached TMDB search per
  normalized title, `seed()` lets a step donate its own search; tri-state — `None` on
  network failure degrades to the year-gap review, never an exception) and
  `TmdbClient.movie_year(tmdb_id)`.
- `domain/matching.py` — `Arbiter = Callable[[str, int], bool | None]`;
  `pick_tmdb_match(..., *, commerce_year=False, arbiter=None)`;
  `match_film(..., *, arbiter=None)`.
- `infrastructure/database.py` — `TmdbMatchTarget(film_id, title, year, commerce)`
  (commerce = no criterion listing); `films_needing_tmdb_match()` returns it;
  `films_tmdb_missed_targets()`; `commerce_films_with_tmdb()`;
  `update_film_year(film_id, year) -> int | None` (returns colliding film id, writes
  NOTHING on collision); `film_id_for_external()`;
  `replace_unresolved_reviews(..., *, reason=None)` (reason-scoped delete).
- `application/availability.py` — `record_tmdb_match` (the ONE TMDB match write path,
  contract `"matched"|"adopted"|"collision"|"id-conflict"`), `queue_review_once` (dedup
  guard on reason+film_id), tmdb_step adoption of the shared matcher (commerce band +
  seeded arbiter for commerce films), durable `year-collision`/`id-conflict` review rows,
  no-match rebuild scoped to `reason="no-match"` with films holding an open durable review
  excluded.
- `application/metacritic.py` + `application/sync.py` — sync builds one TmdbClient +
  TmdbArbiter when a token exists and threads the arbiter through
  `promote_top_n → match_archive → match_film` and into `tmdb_step` (shared cache). The
  `metacritic match` CLI verb stays fully offline.
- `application/rematch.py` + CLI `movie-brain rematch` — one-shot, idempotent; pass A
  re-matches every `tmdb.found=0` film (commerce-aware, arbitrated), pass B fresh-checks
  TMDB's year for every non-Criterion film with a tmdb id and adopts disagreements through
  the same write-back primitives; no provider fetches (quiet first-check semantics
  preserved); exit 0 ok / 1 tripwired (safe re-run) / 2 auth; prints the audit line.

## Live numbers (2026-08-24 runs, backups in `~/.config/movie-brain/`)

- Rematch run 1: misses 486 → **88 rematched**, 368 still missed, **28 id-conflicts**;
  year-checked 1,421 → **266 adopted** (201 off-by-one, 62 re-release-class, 0 collisions);
  **audit: 0** uncorrected non-criterion year mismatches outside the merge queue (M2 Done
  criterion met). Run 2 (after a sync): 2 residual matches/adoptions (TMDB search jitter),
  queues stable, audit 0 again — convergent.
- Promotion arbiter first live sync: metacritic `year-gap` 25 → **23 `remake-suspected`**
  (all verified-real remakes: King Kong 2005, Manchurian Candidate 2004, Invisible Man
  2020, Frankenstein 2025, …) — correct refusals, awaiting M3 resolution; the 2 true
  re-release cases auto-matched.
- Open review queues now: tmdb `no-match` 371 · tmdb `id-conflict` 28 · metacritic
  `year-gap` 23 (all remake-suspected) · `expected-miss` 102 · `ambiguous-title` 8 ·
  `slug-conflict` 5 · `film-multiple-slugs` 2 · apple-tv `year-drift` 7. Films: 4,643
  (1,592 non-Criterion).
- DB backups: `movie-brain.db.bak-2026-08-23-pre-m2` (pre-first-M1-live-sync),
  `movie-brain.db.bak-pre-rematch` (pre-rematch, the year-adoption rollback point).

## Live findings from this session (M3 must know)

1. **Stale-wrong-link class is real and survives M2.** Film 4492 "Rambo: First Blood"
   (1982) carried tmdb id 62518 — *Vahşi Kan* (1983), the Turkish Rambo — linked by the
   pre-M1 title-blind fallback during the M1-day sync. M2's pass B trusted the link and
   adopted 1983. One-off repair applied (Lawrence precedent): link cleared, year restored
   to 1982; the new matcher correctly refuses the match, so 4492 now sits in the no-match
   queue. A backup-diff audit found **zero** other >1-year-later adoptions, but link
   validity was never systematically checked: **M3's repair verb should re-validate every
   pre-M1 tmdb link (norm-title of film vs TMDB title/original_title) — wrong links poison
   year write-back and provider data.**
2. **The 28 `id-conflict` rows are twin evidence** (Planet of the Apes, Doctor Strange,
   The Wolf Man, Romeo & Juliet, …): two DB films resolving to one TMDB movie — exactly
   the merge candidates `repair dupes` needs; each row's `detail` names both film ids
   (note: `value`/detail reflect the FIRST detection — re-derive at resolution time).
3. **Syncs are manual by choice** — the launchd agent is deliberately not installed (user
   decision, 2026-08-24: "i will run those manual for now"). Don't flag it or wait on a
   nightly job; if a check needs a sync, run `uv run movie-brain sync` by hand.
4. **Same-title-at-claimed-year is a wrong-match shape the evidence model can't catch**
   (found live 2026-08-24, user report): film 3105 "Metropolis" — the MC re-release slug
   (2002 restoration of Lang's 1927 silent) promoted with commerce year 2001, and the 2001
   anime Metropolis matched on year evidence with no gap, so no review and no arbitration
   ever fired. One-off repair applied (year 1927, tmdb 19, Fritz Lang, OMDb refetched;
   backup `movie-brain.db.bak-pre-metropolis-fix`). **Bank this as a benchmark ground-truth
   case in M3**, and note `*-re-release` MC slugs deserve a suspicious eye toward
   same-titled candidates AT the commerce year — the slug itself is evidence the year is
   not an original year.
5. **OMDb payloads on year-adopted films were fetched under the old (wrong) years** —
   266 films whose ratings/director/runtime may be for the wrong lookup. An OMDb refetch
   pass for adopted films is M3 triage material.

## Riding minors (final-review triage: all safe to ride; queue-hygiene candidates for M3)

- rematch pass-A tripwire early-returns before the no-match rebuild (pass-B breaks and
  rebuilds) — self-healing next run, but asymmetric (`application/rematch.py`).
- `collisions_queued`/`id_conflicts` count re-detections per run (queue rows stay correct
  via the dedup guard); CLI wording reads as "newly queued".
- `TmdbArbiter` has no negative caching — a TMDB outage retries each gap-band title once
  per promotion run.
- `queue_review_once` dedup key is (reason, film_id) — a standing row keeps its original
  `value`; resolution should re-derive, not trust `value`.
- Cosmetics: test-helper duplication (`_tc` vs `c()`, twin `tmdb_knows` steps), local
  `TmdbArbiter` imports in 3 tests, field-by-field `RematchReport` tripwire returns,
  unguarded `row["title"]` in `update_film_year` for unknown ids.

## M3 scope (from the binding spec — do not re-decide)

- **`movie-brain repair dupes`**: norm-title audit as a verb; groups classified by TMDB id
  equality (same id → twin; distinct → keep both); interactive/batch confirmation; merge
  moves owned/watchlist/my_ratings/external_ids/listings/omdb/tmdb rows to the survivor,
  records an alias, tombstones the loser (migration adds the identity-disposition table;
  every ingester checks it). The 28 id-conflict rows + 49 dup norm-title groups feed this.
- **`movie-brain repair years`**: dry-run list → apply, for residual manual cases.
- **Review resolution CLI**: resolve `match_review` rows (match to X / create / dismiss) —
  drains the 7 apple-tv year-drifts, 371 no-match, 23 remake-suspected, 28 id-conflict.
- Done when: the 49 dup groups are dispositioned, owned marks sit on canonical rows, and
  open `match_review` counts are decidable by CLI instead of accumulating.
- Session finding to fold in: pre-M1 tmdb-link re-validation (finding 1 above) belongs in
  `repair dupes`/`repair years` scope.
- **Planning decision for the M3 session (user-requested, decide at brainstorm/plan time,
  don't silently drop):** backlog item 9 (`docs/backlog.md`) — a user-set "needs revisit"
  drawer flag for factually suspect films (watchlist pattern: own table with film_id +
  marked_on + optional note, drawer toggle the only writer, filter chip, never touched by
  sync). It feeds exactly the review-resolution surface M3 builds, so the user wants it
  considered for inclusion in M3 rather than left in the backlog; resolving a film via the
  M3 CLI should clear its flag. If it stays out of M3, say why in the M3 Done line.

## First-run checks for the M3 session (2 minutes, before building)

- `sqlite3 ~/.config/movie-brain/movie-brain.db "SELECT reason, COUNT(*) FROM match_review
  WHERE authority='tmdb' AND resolved=0 GROUP BY 1;"` → expect no-match ≈371,
  id-conflict = 28 (28 only — the dedup guard must have held through any interim syncs).
- If a sync has run since 2026-08-24: metacritic year-gap should still be ≈23 (all
  remake-suspected) — a jump means the arbiter stopped resolving (check TMDB token).
- Film 4492 should still have NO tmdb external id (or a correct 1368 one if manually
  resolved) — a reappearing 62518 means something re-linked it (should be impossible;
  investigate).

## Entry-point prompt (paste into a fresh session for M3)

> M3 of the movie-brain matching overhaul. Read
> docs/superpowers/specs/2026-08-23-matching-overhaul-design.md (binding, M1/M2 Done lines
> filled), docs/superpowers/handoffs/2026-08-24-m3-matching-handoff.md, and CLAUDE.md
> first, and run the handoff's first-run checks before building (syncs are manual by
> choice — run one yourself if a check needs fresh data). M2 landed authority
> canonicalization live (year write-back, durable year-collision/id-conflict queues, the
> rematch verb, promotion arbitration). Build M3: (1) the identity-disposition migration +
> `repair dupes` (merge/alias/tombstone, ingesters check dispositions — the 28 id-conflict
> rows and 49 dup norm-title groups are the worklist); (2) `repair years` (dry-run →
> apply); (3) the match_review resolution CLI (match to X / create / dismiss), draining
> 371 no-match, 23 remake-suspected, 7 apple-tv year-drifts. Fold in: re-validation of
> pre-M1 tmdb links (Rambo/Vahşi Kan class), banking the Metropolis same-title-at-claimed-
> year case as benchmark ground truth, and decide explicitly whether backlog item 9 (the
> "needs revisit" drawer flag, which feeds this same review surface) ships inside M3 — see
> the handoff's live findings and planning-decision bullet. Constraints: collectors never
> delete outside human-confirmed repair verbs; keep
> scripts/matching_benchmark.py --assert-dominance green; suite/ruff/mypy green; update
> the spec's M3 Done line and write the next handoff when it lands. Use the superpowers
> flow: the spec exists — go straight to writing-plans, then subagent-driven TDD in a
> fresh git worktree.
