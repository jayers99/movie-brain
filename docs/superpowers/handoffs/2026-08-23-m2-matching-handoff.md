# Handoff: M1 (matching overhaul) landed → M2 (authority canonicalization + rematch)

**Written:** 2026-08-23, end of the M1 session. Read this alongside
`docs/superpowers/specs/2026-08-23-matching-overhaul-design.md` (binding spec for M1–M3,
M1's Done line now filled in) and CLAUDE.md before any M2 work.

## Status — M1 is code-complete on `feature/M1-matching-overhaul` (not yet merged to `main`)

Worktree: `.claude/worktrees/M1-matching-overhaul`. Commits `5077c69..d87cfb5` (Tasks 1–6),
plus this docs commit closing Task 7. superpowers:finishing-a-development-branch runs next
to integrate the branch.

**Files landed:**
- `scripts/matching_baseline.py` — frozen pre-M1 matchers (exempt from DRY; duplication is
  its job) + `scripts/matching_benchmark.py` — 25 ground-truth cases, Metacritic + Apple
  archive replays, `--assert-dominance` gate. Run: `uv run python scripts/matching_benchmark.py [--assert-dominance]`.
- `src/movie_brain/domain/matching.py` — the shared evidence-scored core: `norm_title`
  (NFKD diacritic fold, `&`→`and`, `vol`→`volume`), `split_annotations`/`EDITION_ANNOTATIONS`
  (one annotation grammar for parens/brackets/dash-suffix editions), evidence types
  (`YearKind`, `Candidate`, `MatchQuery`, `MatchVerdict`, `CandidateIndex` with L0/L1/L2
  levels), `match_candidates`, and the `Arbiter` hook (interface only — nothing wires a
  real arbiter yet; stub-tested). `match_film`/`match_owned`/`pick_tmdb_match` are now thin
  policy shells over `match_candidates`, signatures kept; `match_owned` gained
  keyword-only `embedded_year`/`runtime_min`/`rerelease_hint`; `MatchResult` gained `reason`.
  `pick_tmdb_match`'s old title-blind top-3 fallback (the Lawrence→731627 wrong-match
  vector) is removed.
- `Repository.films_for_matching()` → `FilmRow` NamedTuple carrying director (COALESCE
  `films.director`, OMDb payload) and runtime (parsed from OMDb `"91 min"`). No schema
  change anywhere in M1.
- `application/metacritic.py` — non-tie review verdicts queue a new reason `year-gap` under
  authority `metacritic`, so `promote_top_n` skips them (prevents twin-creation of
  review-band titles like Tokyo Story 1972).
- `application/owned.py` — computes a rerelease hint from the original Apple title; passes
  `embedded_year`/`rerelease_hint`/`runtime_min` into `match_owned`.
- Apple export v2: AppleScript now exports duration (3rd tab column, seconds); parser
  accepts both 2-column (old archives replay) and 3-column; `OwnedTitle.runtime_min`.

**Benchmark numbers (final, reviewer-verified by live re-run 2026-08-23):**
Ground truth — baseline 14/25 pass, 11 fail, 1 wrong-match (`lawrence-tmdb→731627`) vs new
matcher 25/25 pass, 0 wrong-match. Archive replays (live DB snapshot 2026-08-23): Metacritic
n=4,800 — baseline 31.5% match / 0.0% review / 68.5% create → new 2.9% review; Apple n=870 —
baseline 99.2% match / 0.8% review → new 0.8% review. `--assert-dominance` (new wrong==0
AND review%<5 both corpora) exits 0 — no tuning knobs were needed.

**Intentional behavior changes (spec consequences, do not "fix" back):** a commerce-year
gap without corroboration now queues review as `year-gap` (Tokyo-Story class — was an
auto-match under the old matchers; M2's arbiter wiring is what auto-resolves it correctly);
diacritics fold in `norm_title`; the TMDB title-blind fallback is removed.

## M2 scope (from the binding spec — do not re-decide)

- **TMDB match step adopts the shared matcher**: year-tolerant for commerce-created films;
  arbitration search per principle 4 (single title-candidate + big year gap + no
  director/runtime evidence → one cached TMDB search asks "does a same-titled film exist
  near the claimed year?" — hit means a remake exists, so review/create; no hit means
  re-release, so match the original). This is where the `Arbiter` interface — landed but
  unwired in M1, stub-tested only — gets a real implementation.
- **Year write-back**: on a successful TMDB match for a film with no Criterion listing,
  adopt TMDB's original year when it differs — update `films.year` + recompute `key`; a
  key collision queues a `year-collision` merge candidate in `match_review`, never an
  overwrite.
- **Rematch pass** (CLI verb, one-shot, idempotent): clear + rematch the 232 TMDB misses
  and every non-Criterion film whose year disagrees with a fresh TMDB check; quiet
  first-check semantics (baseline listing write, no transition event) still apply to any
  provider fetches that follow.
- Done when: Lawrence-class contamination is gone from the live DB — audit query returns
  zero uncorrected non-Criterion year mismatches outside the merge queue.

## Live finding to open with

**Film 3086 (Lawrence of Arabia, 1962) still has NO tmdb external id in the live DB** —
only `metacritic|lawrence-of-arabia-re-release`. The M1 handoff's first-run check hoped the
nightly 3 AM sync would rematch it after the one-off year/link repair; it never fired (the
old sync's TMDB step only does a one-shot match of *new* films — a film with a cleared link
isn't "new", so it silently sat unmatched). M2's rematch pass is what covers it; verify it
lands a correct tmdb id (expect near id 947, Lawrence of Arabia 1962) as an early smoke
check once the rematch CLI exists.

## Pickup items (final review)

- **T3 disqualification-ordering comment**: `_score`'s `_Disqualify.COMMERCE_EARLY` vs
  `.OTHER` split in `domain/matching.py` needs a comment explaining why the split matters
  for the all-disqualified verdict step (COMMERCE_EARLY-only → `create`, any OTHER →
  `review("conflict")`) — not yet documented at the call site.
- **Owned `year-drift` detail strings lost their candidate film ids** in the T4
  policy-shell refactor (`application/owned.py`, the `result.reason is not None` branch) —
  restore them, `ambiguous-owned`'s tied-id detail is the model to match.
- ~~`dominates()` test duplicate~~ — fixed by this fix-wave commit
  (`tests/unit/test_benchmark.py`).

## Carried data debt (M1 found it, M1 did not touch it — M2/M3 territory)

- **49 dup norm-title groups** (24 involve owned films) — merges need M3's alias/tombstone
  machinery; not an M2 concern beyond not making the count worse.
- **232 created films with TMDB misses** — this is exactly what M2's rematch CLI targets.
- **481 open tmdb `match_review` rows** — M2's year write-back and arbiter wiring should
  shrink this via correct auto-resolution; full draining is M3's review-resolution verb.
- **7 apple-tv `year-drift` remakes** awaiting M3 resolution: King Kong '76, The Fly '58,
  Nosferatu '24, Scarface '83, Hamlet '96, Anna Karenina '12, The Mummy '32.
- **26 re-release-slug promotions with suspect years** — candidates for M2's year
  write-back once each gets a TMDB match; some may turn out to be legitimate re-releases
  rather than errors, don't assume all 26 need correction.

## Testing carried into M2

BDD: wrapper policies per source already covered by M1's unit/step tests; M2 adds year
write-back incl. collision, rematch idempotency. Web: unchanged surfaces stay
regression-checked (Playwright, `tests/web`). The benchmark harness
(`scripts/matching_benchmark.py --assert-dominance`) should stay green throughout M2 — it's
the regression gate for wrong-match rate, not a one-time M1 artifact.

## Entry-point prompt (paste into a fresh session for M2)

> M2 of the movie-brain matching overhaul. Read
> docs/superpowers/specs/2026-08-23-matching-overhaul-design.md (binding for M1–M3, M1's
> Done line filled in), docs/superpowers/handoffs/2026-08-23-m2-matching-handoff.md, and
> CLAUDE.md first. M1 landed the shared evidence-scored matcher
> (`domain/matching.py`), the `Arbiter` interface (unwired), and the benchmark harness —
> all offline, no live-DB behavior change. Build M2 in this order: (1) wire a real
> `Arbiter` implementation and adopt the shared matcher in the TMDB step
> (year-tolerant for commerce-created films, arbitration search per principle 4); (2) year
> write-back on TMDB match (update `films.year` + recompute `key`; key collision →
> `year-collision` queue in `match_review`, never overwrite); (3) a one-shot idempotent
> rematch CLI verb covering the 232 TMDB misses and any non-Criterion year disagreement.
> Start by confirming film 3086 (Lawrence of Arabia) still has no tmdb external id — it's
> the canonical smoke test for the rematch pass. Constraints: collectors never delete;
> keep `scripts/matching_benchmark.py --assert-dominance` green throughout; suite/ruff/mypy
> green; use the superpowers flow — the spec exists, go straight to writing-plans, then
> subagent-driven TDD in a fresh git worktree.
