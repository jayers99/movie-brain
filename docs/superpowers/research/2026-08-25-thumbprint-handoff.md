# Movie thumbprint / identity resolution — HANDOFF PACKAGE

**Date:** 2026-08-25 · **Purpose:** everything a fresh agent needs to design the best possible
algorithm for *reliable movie identity* ("thumbprinting") in movie-brain. This package collects
pointers and evidence; it does NOT contain or prescribe the algorithm. Designing it is the
receiving agent's job; implementing it is a later, separate, spec-driven phase.

## 0. The problem, in the owner's words

- Goal: a film database where each movie has **one reliable, clean, full record**: a rich set of
  attributes plus keys into every external service — a *thumbprint* strong enough that any new
  source can be matched to it.
- Two sources are ingested today (Criterion Channel, Metacritic top-rated) plus the owner's Apple
  TV library. **Many more lists are coming**: individual critics' top-100s, cult classics,
  Broadway musicals, Tin Pan Alley musicals, film noir, sub-genre lists. They arrive as
  **title + year**, and we have learned how unreliable both fields are.
- The matching we built (M1–M4, 2026-08-23/24) produced plainly wrong matches at scale; the owner
  wants it rethought from evidence, not patched. Every live-DB write is now one-at-a-time,
  announced and approved (see `memory: one-at-a-time`).

## 1. What actually happened (timeline from the migration backups)

Director-less films is the proxy metric the owner watches. Reconstructed from
`~/.config/movie-brain/backups/` (each file = the DB immediately before one migration):

| backup | taken | schema | films | director-less | what happened next |
|---|---|---|---|---|---|
| `movie-brain-v5-2026-08-23.db` | 08-23 16:11 | 5 | 3,051 | **18** | Phase 5 Mode-B promotions + Apple owned import (934 owned) |
| `movie-brain-v6-2026-08-23.db` | 08-23 19:16 | 6 | — | — | (no `owned` table yet in v6 query; see v8) |
| `movie-brain-pre-lawrence-fix-2026-08-23.db` | 08-23 19:47 | — | — | — | manual snapshot before a hand fix |
| `movie-brain-v7-2026-08-24.db` | 08-24 10:37 | 7 | — | — | M2/M3 (no `film_disposition` yet) |
| `movie-brain-v8-2026-08-24.db` | 08-24 10:58 | 8 | 4,643 | **295** | M3 repair surface; rematch run created 306 `no-match` rows |
| `movie-brain-v9-2026-08-24.db` | 08-24 19:51 | 9 | 4,666 | **163** (441 imdb keys) | OMDb-by-IMDb-id refetch (509 misses) already applied |
| live now | — | 10 | 4,639 visible | **60** (549 imdb keys) | 27 hand-approved + 83 auto-cured OMDb replacements, 1 merge |

Reading: **the step from 18 → 295 is ingestion of ~1,600 new films with raw, annotated titles**
(Apple `Title (YYYY)` / `(Unrated) [YYYY]`, Metacritic `[re-release]`), searched verbatim against
TMDB and OMDb. The audit phase (2026-08-24) is read-only and changed nothing. Every OMDb fix
since is re-fetchable by id; the one identity change was merge #4607→#4672 (disposition ledger).
`v5` is the last "clean" state; `v8` is the peak of the damage; `v9` is pre-today.

## 2. Documents to read, in this order

### 2.1 Fresh evidence (start here)
1. `docs/superpowers/specs/2026-08-24-title-resolution-seed.md` — root-cause hypotheses H1–H4,
   research questions R1–R6 (all read-only), the **evidence order that never picked wrong on
   110 hand-verified cases**, resolver design goals, open owner questions.
2. `docs/superpowers/research/2026-08-25-title-annotations.md` — every annotation in the live
   title column bucketed (139 titles; vocabulary; `(500) Days of Summer`; parenthesized
   translations are alt-titles not junk; 15/28 edition titles carry the edition's year as
   `films.year`); owner preferences (original year wins; normalized title as its own attribute;
   edition is data); candidate edition models M1/M2/M3 (undecided; Blade Runner problem).
3. `docs/superpowers/specs/2026-08-24-data-audit-design.md` (+ plan `…/plans/2026-08-24-data-audit.md`)
   — the nine cross-source consistency checks, weights, Suspect chip, append-only `audit_verdict`
   ledger. Implemented and merged (`bff9485`); `audit run` has NOT been executed live yet.

### 2.2 The matching we already built (what to keep, what failed)
4. `docs/superpowers/specs/2026-08-23-matching-overhaul-design.md` — the binding spec for M1–M3:
   failure inventory of 08-23, design principles (one matcher / evidence scoring / source-aware
   years / remake hazard), per-phase Done criteria. **Its principles are still right; its title
   grammar and its trust in title search were not enough.**
5. Plans: `docs/superpowers/plans/2026-08-23-m1-matching-overhaul.md`,
   `…/2026-08-24-m2-authority-canonicalization.md`, `…/2026-08-24-m3-repair-surface.md`.
   M4 has no plan doc — see commit `9e7e5b1` (repair links --film, TMDB alt-title acceptance).
   M5 `582b8e7` (reachable scope), M6 `ddd8ac6` (year retry on TMDB search; Intolerance rule).
6. `docs/superpowers/specs/2026-08-23-apple-tv-owned-design.md` + plan — the import that created
   the `Title (YYYY)` films (H1 in the seed: verify where the raw title is persisted).
7. `docs/superpowers/specs/2026-08-23-phase5-metacritic-mode-b-design.md` + plan — Mode-B
   promotion of top-N Metacritic titles into real films (`clean_title` only strips `(YYYY)`).
8. `docs/superpowers/specs/2026-08-23-phase2-metacritic-mode-a-design.md` — archive/match rules.
9. `docs/multiple-movie-services.md` (roadmap + dated decisions: GUID identity, immutable films,
   `external_ids` as the per-authority key map), `docs/vision.md`, `docs/backlog.md`.

### 2.3 Code that embodies the current behaviour
- `src/movie_brain/domain/matching.py` (502 lines) — `match_candidates` core, `norm_title`,
  `split_annotations` / `clean_title` / `clean_apple_title` / `parse_apple_title`, `Arbiter`.
- Wrappers: `application/metacritic.py` (`match_film`, `promote_top_n`), `application/owned.py`
  (`match_owned`, create-unmatched path), `application/availability.py` (`pick_tmdb_match`,
  `record_tmdb_match`, `tmdb_step`), `application/rematch.py`, `application/repair.py`,
  `application/review.py`, `application/audit.py`, `domain/audit.py`.
- Adapters: `infrastructure/omdb.py` (`lookup` = `t=`+`y=` title search, **the path that accepted
  junk**; `lookup_by_imdb` added 08-24), `infrastructure/tmdb.py` (`search` w/ year retry,
  `movie_titles`, `movie_facts`, `imdb_id`), `infrastructure/metacritic.py` (`_CARD_KEYS` —
  cards carry `duration`, `genres`, `description`, `releaseDate` we don't keep),
  `infrastructure/appletv.py`.
- Schema: `migrations/001…010_*.sql`; identity = `films.guid`; `external_ids(authority, value)`
  UNIQUE; `film_disposition` (merged/tombstoned); `audit_flags`, `audit_verdict`, `tmdb_facts`.
- Benchmark: `scripts/matching_benchmark.py` — 27 `GROUND_TRUTHS` cases + archive replays,
  `--assert-dominance` (zero wrong matches, no worse than `scripts/matching_baseline.py`).
  **None of the 110 cases from 08-24 are in it yet** (seed R5).
- Spikes: `scripts/discovery/match_spike2.py` (the original 98% Metacritic→TMDB spike).

### 2.4 Raw archives (re-derivable inputs)
- Metacritic browse pages: `~/.config/movie-brain/metacritic/pages/page-0001…0200.html` +
  `fetch-log.jsonl` (never re-fetched; parse only).
- Apple TV library exports: `~/.config/movie-brain/appletv/owned-2026-08-23.txt`,
  `owned-2026-08-24.txt` (3-column since v2: title, year, runtime seconds).
- Live DB: `~/.config/movie-brain/movie-brain.db` (schema 10). Read-only unless approved.

### 2.5 Standing rules (memory, `~/.claude/projects/-Users-jayers-code-movie-brain/memory/`)
`one-at-a-time.md` (no sweeps; announce → approve → do only that → before/after),
`title-resolution-seed.md`, `data-audit-phase.md`, `phased-implementation-workflow.md`,
`manual-syncs-by-choice.md`, `omdb-paid-tier.md` (quota is not a constraint).

## 3. Evidence the algorithm must respect (condensed; details in the seed §0.2)

From 110 verified cases (27 manual, 83 auto with identical rule, 0 wrong):
1. **Parent key agreement wins outright**: OMDb `imdbID` == TMDB `imdb_id` → correct, even if thin.
2. **Completeness + `imdbVotes`, compared between candidates** — 25/25 when it disagreed with title distance.
3. **Title Levenshtein on the *normalized* title** — good, but loses to official longer titles
   (`Episode VII - …`) and to our own dirty titles; tie → completeness.
4. **Junk shapes** (reject): `Title (YYYY)` + Director N/A; runtime < 30 min vs card duration;
   `Making of / Q&A / Panel / w/ / on POV / Reviews / Sing-Along / Timelapse`; `Type != movie`
   unless the source says so (Dekalog, Small Axe are series/anthology).
5. **Year ±2 as a filter, never the chooser**; commerce years (Metacritic, Apple field,
   `[re-release]`) are re-release-prone; OMDb `Year` is US-release-prone.
6. ~10% need a human → A/B/C table (title · year · director · runtime · votes · id). Every verdict
   must become a benchmark case.
7. Sources that carry the key: TMDB, OMDb, Wikidata, Letterboxd, JustWatch. Sources that don't:
   Criterion, Metacritic, Apple, and every future list. So title+year → `tt` happens exactly
   once per film, then everything keys by `tt`/`tmdb_id`.
8. Metacritic cards give free discriminators (runtime, genres, plot); director needs a
   movie-page crawl (separate polite archive).

## 4. Recommendations on how to proceed (the current agent's view; not binding)

1. **Answer the seed's R1–R6 first, read-only, with numbers.** Especially R4 (per-day director-less
   from the backups — table above gives the anchors) and R5 (benchmark contains none of the new
   cases). Don't design until the failure is fully characterized.
2. **Make the benchmark the contract.** Bank all 110 verified cases + the 28 edition titles + the
   A/B/C leftovers as ground truth (`title as ingested, year as ingested, source → tt`). The
   dominance gate should be "zero wrong on ground truth" *before* "auto-match rate".
3. **Decide the identity model before the matcher.** Work vs edition (Blade Runner), normalized
   title as an attribute, original year as `films.year` with edition year as data. The matcher's
   output type depends on this; don't let it be implicit.
4. **One title grammar, two uses.** Applied at ingest (store clean + evidence) and at search time.
   Trailing-only, bracket-aware, parenthesized translations → alt-titles, vocabulary from the
   annotations doc §3, plus undelimited forms (`Redux`).
5. **TMDB brokers the key; OMDb by id only.** Title search of OMDb (`s=`) is a ranked fallback
   for films TMDB lacks, never `t=`. Every auto-accept requires ≥2 agreeing signals; otherwise
   queue with the evidence attached.
6. **Repair is a batch diff, not a sweep.** Any fix verb prints the full before/after table and
   applies only after approval; each approved row lands in the benchmark.
7. Keep the dispositions ledger and `external_ids` as-is — they're the right substrate. The gap is
   the resolver, not the schema.

## 5. What the receiving agent should deliver

- A design (spec) for the thumbprint/resolver: identity model decision (with the Blade Runner
  case worked), the title grammar, the evidence model and thresholds, the human-review contract,
  the benchmark plan, and a migration path for the existing 4.6k films (including the 88
  `Title (YYYY)` identities and the 15 edition-year films) — one-at-a-time compatible.
- Explicitly: what from M1–M4 is kept, what is replaced, and why, citing the evidence above.
- No implementation, no live-DB writes.
