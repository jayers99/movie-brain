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

**Done 2026-08-24:** merged to main (`ba72e94`; 388 tests, ruff, mypy, dominance gate all
green). Live rematch run 1: 486 misses → 88 rematched / 368 still missed (no-match queue) /
28 id-conflicts queued as durable merge candidates; 1,421 non-Criterion films year-checked,
266 years adopted (201 off-by-one commerce corrections, 62 re-release-class multi-year
moves, 0 collisions); **audit = 0** uncorrected mismatches outside the merge queue — the
Done criterion. Run 2 confirms convergence (2 residual matches from TMDB search jitter,
queue rows stable under the dedup guard, audit 0 again). Promotion arbiter live: the 25
metacritic `year-gap` rows resolved to 23 `remake-suspected` refusals (King Kong '05,
Manchurian Candidate '04, Invisible Man '20 … genuine remakes, correctly NOT matched to our
originals — M3 resolution fodder) with the true re-release cases auto-matched. One-off
repair (Lawrence precedent): film 4492 "Rambo: First Blood" carried a pre-M1 wrong link
(tmdb 62518, Vahşi Kan 1983) whose year pass B then adopted; link cleared, year restored to
1982, film now in the no-match queue. Stale-wrong-link re-validation is M3 scope.

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

**Done 2026-08-24:** live repair run on the worktree branch against the real DB (backup
`movie-brain.db.bak-pre-m3`). `repair dupes` found **68 groups** (28 id-conflict + 40
norm-title) — 28 twins, 24 distinct, 16 undecided. Three of the 28 "twins" were read as
stale pre-M1 claims rather than real twins (film 4307 Willy Wonka vs 1689 *Factory*
holding tmdb 252; 4280 Nymphomaniac Vol. II vs 4279 holding Vol. II's id 249397; 2163 THE
AMPUTEE Version 1 vs 2162 Version 2) and were dismissed with a note — a dismissal is a
standing decision, and the rematch that followed confirmed it: the three re-detections
printed but no row came back. `repair dupes --apply --yes` then merged the remaining
**25 twin groups** (25 `merged` dispositions, 0 tombstones, 0 declined). `repair years
--apply` marked **151 stale OMDb payloads** for refetch (0 open year-collisions).
`repair links` found **134 suspects but cleared 0**: the set is a mixed bag, not the
uniform wrong-film class the plan pre-authorized — ~124 are legitimate alternate-title
matches (English retitlings, translated titles, subtitle variants) and only ~6 are truly
wrong films (#341→World War Z, #2939→House by the River, #4257→US Tour, #4462→Django,
#4488→West Side Story doc, #1689 *Factory*→Willy Wonka), so the whole list went to the
user's worklist instead. All **23 metacritic `year-gap` remake-suspected rows** resolved
`--create` (films 4673–4695); the sync that followed OMDb-looked-up 174 films and
TMDB-matched all 23, adopting 7 original years off the Metacritic re-release years.
`rematch` run 1: 383 misses → 11 rematched / 369 still missed, 1,445 years re-checked, **0
adopted** with **5 year-collisions queued** (the CLI counter printed 10 — re-detections,
not rows; the dedup guard kept 5), **audit = 0**. Those 5 exposed the run's one
genuine defect: pass B tried to correct the five merge survivors that kept an Apple remaster
year (Woodstock 2014→1970, Monty Python 1999→1975, The Last Picture Show 2014→1971, Dog
Day Afternoon 2014→1975, Ben-Hur 2001→1959) and was blocked every time by that survivor's
*own merged-away loser* — `update_film_year`'s collision probe treated any key-holder as a
live identity, and a merged loser's `films` row is deliberately never deleted, so it kept
the key its survivor was entitled to. **Fixed in this milestone**: exactly one holder of
the target key no longer blocks — this film's OWN merged-away loser, whose dead key is
retired in place (`key || ' #' || id`) so the UNIQUE constraint lets its survivor take it.
Every other holder still blocks, and blocks under its CANONICAL id: a loser merged into some
*other* survivor reports that survivor, so the year-collision review names the live identity
a human must reconcile rather than a hidden row. A *tombstoned* holder blocks as itself by
design — `tombstoned_keys()` is the guard that stops collectors re-creating a tombstoned film
and that guard IS the key, so handing it away would silently disarm it. `rematch` run 2
after the fix: **adopted 5, collisions queued 0, audit 0** — all five survivor years are now
canonical. Done criteria: **owned-on-disposed = 0** (owned marks all sit on canonical rows);
a second `repair dupes` dry-run reports **twins: 0** (42 distinct, 20 undecided — the 20
need a TMDB backfill before they can be classified, the 42 grew from 24 as the created
remakes legitimately joined their originals' title groups); open reviews **544 → 494**,
every one decidable by `review list`/`review resolve` rather than accumulating. Queue
hygiene closed both merge-artifact classes outright: the 5 now-satisfied `year-collision`
rows and the 11 stale `id-conflict` rows (each naming a counterpart already merged into that
same film — they survived because `merge_film` resolves only the *loser's* reviews and these
were filed against the film that became the *survivor*) were dismissed, leaving **zero open
`tmdb/id-conflict` and zero `tmdb/year-collision`**.
Benchmark: ground truth **26/26 pass, 0 wrong-match** (baseline 14/26, 2 wrong-match)
including the newly banked `metropolis-rerelease-same-year-twin` case, `--assert-dominance`
exit 0 (mc review 3.1%, apple review 4.8%); 439 tests, ruff, and mypy green. Residual for
the user, not blockers: 7 apple-tv `year-drift`, 372 tmdb `no-match`, the 134 link suspects,
and the 20 undecided dup groups. Riding note: `merge_film` still resolves only the loser's
reviews, so a future merge can leave the same stale-review-on-survivor artifact. **Backlog item 9 (needs-revisit drawer flag)
shipped inside M3.**

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
