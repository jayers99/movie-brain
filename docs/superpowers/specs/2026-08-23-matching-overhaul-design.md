# Matching overhaul: one evidence-scored matcher, authority years, repair surface

**Date:** 2026-08-23 · **Status:** approved (analysis session; "ultrathink" review with user)
**Context:** live failures found during Apple-owned UAT — see the failure inventory below.
Supersedes the parked per-source patches; subsumes the Phase 5/owned deferred minors about
matcher duplication. Delivered as three phases (M1–M3), each its own spec→plan→worktree run;
this document is the binding spec for all three, with per-phase Done criteria.

## Failure inventory (evidence, 2026-08-23 live DB)

| Class | Examples found | Mechanism |
|---|---|---|
| Source-biased years | Lawrence of Arabia 2002→1962; Stop Making Sense 2023→1984; Monty Python "1999"; Beauty and the Beast 2002→1946; Repulsion (MC wrong, Apple right) | Commerce sources stamp commercial dates; matchers use year as a hard gate; creation ossifies the bad year; cascades into wrong TMDB matches (Lawrence→id 731627) |
| Title variance | `Tête`≠`Tete` (diacritics kept by norm_title); `&` dropped vs `and` kept (Willy Wonka); `[re-release]` brackets (7 films); "(Restored Version)"; "– The Director's Edition"; subtitle prefixes (Hearts of Darkness: …) | Three matchers, three ad-hoc normalizers, one shared bug surface |
| Remake hazard | A Star Is Born ×2, Body Snatchers ×2 (both owned, correctly distinct), Nosferatu, Scarface, The Fly, King Kong, Hamlet | Any year-relaxation risks cross-matching remakes; currently handled by luck |
| No authority pass | 232 created films missed TMDB; 49 dup norm-title groups (24 involving owned) | Created films never launder identity through TMDB before it hardens |

Ground-truth cases banked from this session: Vertigo, Rear Window, Lawrence of Arabia,
Kill Bill Vol 1/2, Dr. Strangelove (control: correct), Stop Making Sense, the 49-group audit.

## Design principles

1. **One matcher, per-source policy.** A single `match_candidates(...)` core in
   `domain/matching.py`; the existing `match_film` (Metacritic), `match_owned` (Apple), and
   `pick_tmdb_match` (TMDB) become thin policy wrappers. Verdicts are three-way:
   `match(film_id)` / `review(reason, candidates)` / `create`.
2. **Evidence scoring, not gates.** Signals accumulate; no single field can force a wrong
   match. Wrong-match rate is the optimization target (must be ≈0), review load second,
   auto-match rate third.
3. **Year is source-aware.** Commerce years (Metacritic, Apple's field) are *neutral* when
   `>= candidate_year - 1` (commercial dates trail originals, never precede beyond festival
   slack) and *disqualifying* only when impossibly early. Database years (Criterion, TMDB,
   embedded-title years) keep tight ±1 semantics. The truth-holder precedence in CLAUDE.md
   stands: Criterion/TMDB > embedded title year > Apple field > Metacritic.
4. **Authority arbitration for the undecidable band.** Single title-candidate + big year gap
   + no director/runtime evidence → one cached TMDB search asks "does a same-titled film
   exist near the claimed year?" Hit → remake exists → review/create. No hit → re-release →
   match the original. (Kills the Stop-Making-Sense-vs-Nosferatu ambiguity without local data.)
5. **Canonicalize at creation.** Every film created from a commerce source adopts TMDB's
   original year as soon as its TMDB match lands (year + key recompute; key collision =
   detected twin → merge queue). Commerce years never harden into identity again.
6. **Collectors still never delete.** Merges/tombstones are human-confirmed maintenance
   verbs (M3); the matcher only ever matches, reviews, or creates.

## M1 — shared matcher + normalization + benchmark (offline; no live-DB behavior change)

- **Normalization fixes** in `norm_title`: NFKD-fold diacritics (strip combining marks),
  `&`→`and`, `vol.`/`vol`→`volume`. One shared **annotation grammar** replacing the per-source
  lists: trailing parenthetical/bracketed/dash-suffix editions (re-release, Unrated,
  Director's Cut, Restored Version, 4K…, extendable constants), applied by all wrappers.
- **Candidate index** at three levels: L0 fixed-norm exact; L1 annotation-stripped;
  L2 subtitle-stripped (pre-colon prefix, ≥2 words). Level recorded as evidence strength.
- **Evidence scorer**: title level, source-aware year, director (match strong / conflict
  disqualifying; films now carry director via Criterion + OMDb-payload COALESCE), runtime
  when available (±5% supports; >15% divergence disqualifies), TMDB popularity as
  tiebreaker only. Deterministic thresholds → match/review/create; ties never guessed.
- **Apple export v2**: adapter also reads `duration` (runtime) per track; archive format
  gains a third tab column (parser accepts both formats — old archives replay).
- **Benchmark harness** (`scripts/matching_benchmark.py`, offline, re-runnable): replays the
  Metacritic archive (4,783 staged titles), the Apple archives (870 lines), and the banked
  ground-truth cases against old vs new matchers; reports wrong-match / review / auto-match
  rates. **Benchmark lands before the algorithm** (data-level TDD). Done when: new matcher
  strictly dominates on wrong-match rate, review load stays tolerable (target: <5% of
  inputs), suite green, no live-DB writes yet.

**Done 2026-08-23:** benchmark — ground truth: baseline 14/25 pass, 11 fail, 1 wrong-match
(Lawrence→tmdb 731627) vs new matcher 25/25 pass, 0 wrong-match. Archive replays (live DB
snapshot 2026-08-23): Metacritic n=4,800 — baseline 31.5% match / 0.0% review / 68.5% create
→ new 2.9% review; Apple n=870 — baseline 99.2% match / 0.8% review → new 0.8% review.
`--assert-dominance` gate (wrong==0 AND review%<5 both corpora) exits 0, no tuning knobs
needed. Wrappers (`match_film`, `match_owned`, `pick_tmdb_match`) are thin policy shells over
the shared `match_candidates` core; Apple export v2 (runtime column) live, old 2-column
archives still replay. No pipeline or schema change — offline only, as scoped.

## M2 — authority canonicalization + rematch (live pipeline change)

- TMDB match step adopts the shared matcher (year-tolerant for commerce-created films;
  arbitration search per principle 4).
- **Year write-back**: on a successful TMDB match for a film with no Criterion listing,
  adopt TMDB's original year when it differs — update `films.year` + recompute `key`; a
  key collision queues a `year-collision` merge candidate in `match_review`, no overwrite.
- **Rematch pass** (CLI verb, one-shot, idempotent): clear + rematch the 232 TMDB misses
  and every non-Criterion film whose year disagrees with a fresh TMDB check; quiet
  first-check semantics still apply to any provider fetches that follow.
- Done when: Lawrence-class contamination is gone from the live DB (audit query returns
  zero uncorrected non-Criterion year mismatches outside the merge queue).

## M3 — repair & merge surface (Phase 8 pulled forward, scoped)

- **`movie-brain repair dupes`**: the norm-title audit as a verb; groups classified by TMDB
  id equality (same id → twin; distinct → keep both); interactive/batch confirmation;
  **merge** moves owned/watchlist/my_ratings/external_ids/listings/omdb/tmdb rows to the
  survivor, records an **alias** for the losing identity, and **tombstones** it so no
  collector resurrects it (the identity-disposition table from the data-hygiene principles,
  built here). Migration adds the disposition table; every ingester checks it.
- **`movie-brain repair years`**: dry-run list → apply, for residual manual cases.
- **Review resolution**: minimal CLI to resolve `match_review` rows (match to X / create /
  dismiss), draining the apple-tv year-drift queue (7 remakes) and the 481 tmdb rows.
- Done when: the 49 dup groups are dispositioned, owned marks sit on canonical rows, and
  `match_review` open counts are decidable by CLI instead of accumulating.

## Out of scope (tracked, not here)

iTunes Search API adapter (director-confirmed matching, store ids — roadmap parallel
track); default dashboard scope = Criterion + owned (separate small UI decision); ratings
sync. One-off repair already applied 2026-08-23: Lawrence of Arabia year→1962, bad TMDB
link cleared, owned mark added (DB backup `movie-brain-pre-lawrence-fix-2026-08-23.db`).

## Testing

Benchmark harness is the spine (M1). Unit: normalizer folds, annotation grammar, scorer
verdicts per class (re-release, remake, subtitle, diacritic, &/and). BDD: wrapper policies
per source; year write-back incl. collision; rematch idempotency; merge moves every FK and
tombstone blocks resurrection. Web: unchanged surfaces regression-checked (Playwright).

## Entry-point prompt (paste into a fresh session for M1)

> M1 of the matching overhaul: read docs/superpowers/specs/2026-08-23-matching-overhaul-design.md
> (binding, all phases) and CLAUDE.md. Build the benchmark harness FIRST against the
> Metacritic + Apple archives and banked ground truths, then the shared evidence-scored
> matcher + normalization fixes + Apple export v2 (runtime column), keeping the three
> source wrappers' public signatures. No live-DB behavior changes in M1. Constraints:
> collectors never delete; suite/ruff/mypy green; superpowers flow (spec exists → plan →
> subagent-driven TDD in a worktree).
