# Handoff: Phase 5 + Apple-owned landed → M1 (matching overhaul)

**Written:** 2026-08-23, end of a long session. Read this alongside
`docs/superpowers/specs/2026-08-23-matching-overhaul-design.md` (binding spec for M1–M3)
and CLAUDE.md before any M1 work. Roadmap context: `docs/multiple-movie-services.md`.

## Status — everything below is merged to `main` and pushed (through `1e68f68`)

- **Phase 5 (Metacritic Mode B top-N dial): done** and exercised live — dial at **1,000**,
  770 promoted films, OMDb/TMDB enriched, availability fetched. Spec/plan under
  `docs/superpowers/{specs,plans}/2026-08-23-phase5-*`.
- **Apple TV owned films: done** and exercised live — `movie-brain owned import` ran twice
  against the real TV app (870 tracks): 812 matched / 51 created / 7 `year-drift` reviews
  after the embedded-year fix. `owned` table (migration 007), owned badge, drawer
  tv.apple.com link, **Owned** + **Not owned** chips. Spec/plan:
  `2026-08-23-apple-tv-owned*`.
- **Matcher hardening already landed** (commit `b3fe325`): `parse_apple_title` (embedded
  title year outranks Apple's field year), year-drift → review instead of twin-creation,
  truth-holder precedence written into CLAUDE.md.
- **Live DB state** (~4,643 films): dial 1000 · 864+ owned · watchlist alerts active ·
  paid OMDb plan (no 1,000/day constraint — see CLAUDE.md).
- **One-off repair applied by hand** (user-authorized): Lawrence of Arabia #3086 year
  2002→1962, key recomputed, bad TMDB link cleared (rematches on next sync), owned mark
  added. Backup: `<config_dir>/backups/movie-brain-pre-lawrence-fix-2026-08-23.db`.

## M1 scope (from the binding spec — do not re-decide)

Shared evidence-scored matcher + normalization fixes (NFKD diacritic fold, `&`→`and`,
`vol`→`volume`, one annotation grammar for parens/brackets/dash-suffix editions) +
three-level candidate index + source-aware year policy + TMDB arbitration hook (interface
only in M1) + **Apple export v2 with a runtime column** (parser accepts old 2-column
archives) + the **benchmark harness first** (`scripts/matching_benchmark.py`) over the
Metacritic archive (4,783 staged titles), Apple archives (870 lines), and the banked
ground truths. Wrong-match rate ≈ 0 is the target; review load < 5%; no live-DB behavior
changes in M1. Existing wrappers (`match_film`, `match_owned`, `pick_tmdb_match`) keep
their public signatures as policy shells.

## Ground truths banked this session (feed the benchmark)

Vertigo (1958), Rear Window (1954, Apple field said 2013), Lawrence of Arabia (1962, MC
said 2002), Kill Bill Vol 1/2 (correct as two films), Dr. Strangelove (correct control),
Stop Making Sense (1984, Apple said 2023 — pre-fix twin #4252 exists), the 49 norm-title
dup groups (24 involve owned; mix of true twins and legitimate remakes — A Star Is Born,
Body Snatchers ×2 both owned correctly, Dune, Overlord, Grandma's Boy are NOT twins).

## Known data debt M1 must not "fix" silently (M2/M3 territory)

- 49 dup groups incl. pre-fix twins (Stop Making Sense #4252, Rear Window #3945,
  Vertigo #3946, Lawrence #4048…) — merges need M3's alias/tombstone machinery.
- 232 created films with TMDB misses; 481 open tmdb `match_review` rows; 7 apple-tv
  `year-drift` remakes (King Kong '76, The Fly '58, Nosferatu '24, Scarface '83, Hamlet
  '96, Anna Karenina '12, The Mummy '32) awaiting M3 resolution verbs.
- 26 re-release-slug promotions with suspect years; 7 films with `[re-release]` in title.
- Metacritic archive holds 999 of top-1000 (deduped slug) — harmless, logged nightly.

## Parked / open questions (not blocking M1)

- **Default dashboard scope = Criterion + owned?** User leaned yes but hasn't decided —
  small filters/app.js change, its own approval.
- iTunes Search API adapter (director-confirmed matching, store ids, deep links) —
  roadmap parallel track, after M-phases.
- AppleScript export sees 870 of the user's 1,000+ purchases (Family Sharing gap);
  privacy-portal export is the documented backstop.
- Deferred minors from Phase 5 + owned final reviews live in those specs/plans' history;
  notable: `_refresh_pass` docstring, `.badge-owned` CSS duplication, `mark_owned` FK
  crash on bogus id (unreachable), reorder-blind AppleScript count guard.
- Phase 6 (full-service import) and Phase 7 (subscription advisor) queue behind M1–M3 by
  the user's choice; the practice-loop track (vision.md) remains the flagged novel core.

## First-run checks for the next session (2 minutes, before building)

`movie-brain status` (expect ~owned 860+, discovery ~850+); confirm tonight's 3 AM sync
rematched Lawrence (external_ids tmdb for film 3086 ≈ id 947) and fired no arrivals flood.

## Entry-point prompt (paste into a fresh session)

> M1 of the movie-brain matching overhaul. Read
> docs/superpowers/specs/2026-08-23-matching-overhaul-design.md (binding for M1–M3),
> docs/superpowers/handoffs/2026-08-23-m1-matching-handoff.md, and CLAUDE.md first.
> Build in this order: (1) the offline benchmark harness over the Metacritic + Apple
> archives and the handoff's banked ground truths, scoring the CURRENT matchers as
> baseline; (2) the shared evidence-scored matcher with the normalization fixes
> (diacritics, &/and, vol/volume, unified annotation grammar), three-level candidate
> index, and source-aware year policy; (3) Apple export v2 (runtime column,
> backward-compatible parser). Keep match_film / match_owned / pick_tmdb_match public
> signatures as policy wrappers. No live-DB behavior changes in M1 — prove dominance on
> the benchmark (wrong-match ≈ 0, review < 5%) before M2 touches the pipeline.
> Constraints: collectors never delete; suite/ruff/mypy green; update the spec's M1 Done
> line and write the M2 handoff when it lands. Use the superpowers flow: the spec exists —
> go straight to writing-plans, then subagent-driven TDD in a git worktree.
