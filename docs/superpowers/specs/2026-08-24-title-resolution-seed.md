# Title resolution: what went wrong, and a resolver we can trust — SPEC SEED

**Date:** 2026-08-24 · **Status:** seed (research first; nothing approved for implementation)
**Owner's direction (verbatim intent):** the director-less count was never ~163 before; something
we built on 2026-08-23/24 made up matches that were plainly wrong. Research the root cause first,
then design a title→parent-key resolver good enough that OUR data stays clean even though the paid
sources (OMDb title search, TMDB search ranking) are sloppy. Fix one thing at a time; every live-DB
write is announced, approved, and shown before/after (see memory `one-at-a-time`).

## 0. What we know tonight (evidence, not theory)

Counts are from the live DB (`~/.config/movie-brain/movie-brain.db`, 4,639 non-disposed films).

| when | director-less | note |
|---|---|---|
| start of 2026-08-24 session | **253** | first measured |
| after OMDb-by-IMDb-id refetch of 509 misses | 163 | |
| after 27 hand-approved fixes + 83 auto-cured (this doc's evidence set) | **60** | |

### 0.1 Where the bad rows came from (provenance queries, read-only)

- **88 films titled `Title (YYYY)`** — 82 are `owned`, ids 3934–4607, all `first_imported`
  2026-08-23 → created by the **Apple TV owned import** (`owned import`, commits 41ac208…b3fe325).
  `parse_apple_title` exists to strip the embedded year, yet the *created* film kept the raw title.
  → Hypothesis H1: the create-unmatched path used the raw title, not the cleaned one.
- **15 films with `[re-release]` / `(Unrated…)` / `Director's Cut` / `(Restored Version)`** —
  8 Metacritic Mode-B promotions, 7 Apple. `[re-release]` is not in `split_annotations`'
  vocabulary; Metacritic's `clean_title` handles `(YYYY)` but not `[…]`.
  → Hypothesis H2: annotation grammar is incomplete and applied inconsistently per source.
- **306 TMDB `no-match` review rows created 2026-08-24** (plus 30 id-conflict, 5 year-collision) —
  the M2 `rematch` run (c450937…4705800) and the sync TMDB step searched those raw titles verbatim
  and (by policy) never used the year for commerce films. `no-match` is never retried by sync.
  → Hypothesis H3: raw title in → guaranteed miss → no TMDB id → no IMDb key → OMDb title search
  as the only path → wrong derivative record accepted because `Response:True` was terminal.
- **OMDb title search accepted whatever came back** (`OmdbClient.lookup`, `t=` + `y=`):
  a stub `"The Deer Hunter (1978)"`, `"The Making of 'Schindler's List'"`, a Cast Q&A, a podcast
  episode, a 2002 World Cup broadcast. No candidate comparison ever happened.
  → Hypothesis H4: the enrichment design trusted a fuzzy search as an exact lookup.

### 0.2 What separated right from wrong (110 hand-verified cases today)

Evidence order that never picked wrong across 27 manual + 83 auto cases:

1. **Parent-key agreement** — OMDb `imdbID` == TMDB `external_ids.imdb_id` → correct, stop.
   A thin-but-keyed record (unreleased film, Criterion short) is *fine* (Harlem, Dark Matter).
2. **Record completeness + `imdbVotes`**, compared *between candidates* (never absolute):
   25/25 right when signals disagreed with title distance.
3. **Title Levenshtein** to the *cleaned* ingested title: 3/4 alone; fails on official longer
   titles (`Episode VII - …`) and on our own dirty titles; distance tie → completeness decides.
4. **Junk shapes, reject outright**: OMDb title ending in bare `(YYYY)` with Director N/A;
   runtime < 30 min against Metacritic card `duration`; tokens `Making of`, `Q&A`, `Panel`,
   `w/`, `on POV`, `Reviews`, `Sing-Along`, `Timelapse`; `Type != movie` unless source says so.
5. **Year band ±2** as a *filter* (kills 40-years-apart remakes), never as the chooser
   (derivatives share the film's year; OMDb `Year` drifts to US release).
6. **Disagreement → human**, shown as an A/B/C table (title · year · director · runtime · votes).
   ~10% of cases today (two Star Wars, "300", Muhammad Ali).

Dry run on the 143 remaining director-less films with rules 2–5: **83 clear / 4 ambiguous / 56
nothing in OMDb** (about half of the 56 are genuine Criterion-only shorts; the rest need a
leading-"The" retry and `series`/`episode` acceptance for Dekalog / Small Axe).

### 0.3 Metacritic cards carry more than we parse
`releaseDate`, `duration`, `genres`, `description`, `rating` are on every archived browse card
(`_CARD_KEYS` keeps only title/slug/year/score). Runtime and genre are free discriminators.
Director is NOT on cards (movie-page crawl would be a separate, polite archive).

## 1. Research questions (do these BEFORE any design; all read-only)

R1. Confirm H1: read `application/owned.py` create-unmatched path and `parse_apple_title`; show
    the exact line where the raw title is persisted. Count owned-created films whose `title`
    ≠ `parse_apple_title(title)[0]`.
R2. Confirm H2: diff `split_annotations` / `clean_title` / `clean_apple_title` vocabularies;
    list every live title that survives all three with an annotation still attached.
R3. Confirm H3: for the 306 `no-match` rows, how many resolve on TMDB when searched with the
    cleaned title + `primary_release_year` retry ±2 (dry run, count only)?
R4. Timeline: from `owned` `first_imported`, `omdb.looked_up`, `match_review.created_at`, and
    `git log`, reconstruct director-less count per day (2026-08-22 → 24). Was it ever < 100?
    (The user's memory says yes.) If the Apple import is the step change, say so plainly.
R5. Benchmark honesty: does `scripts/matching_benchmark.py` contain ANY of today's 110 cases?
    If not, the "dominance gate" was measuring the wrong thing. Add them (title-as-ingested,
    year, → tt) as ground truth before touching the matcher.
R6. Which of today's fixes are reversible if wrong? (OMDb rows are re-fetchable by id; the one
    merge #4607→#4672 is a disposition; nothing else touched identity.)

## 2. Design goals for the resolver (to be specified after R1–R6)

- One function of record: `resolve(title_as_ingested, year_hint, source) → tt | review`.
  Ingesters (Criterion, Metacritic, Apple, future lists) call it; nothing else searches by title.
- Title cleaning is one grammar for all sources (H2), applied at ingest AND at search time;
  `films.title` stores the clean title; annotations are kept as evidence, not identity.
- TMDB is the key broker (title → tmdb_id → imdb_id); OMDb is fetched **by id only**. OMDb `s=`
  search is a fallback for films TMDB lacks, ranked by §0.2 — never `t=`.
- Every decision carries its evidence (scores per signal) into `match_review`/A-B-C review so the
  human sees *why*, and every human verdict lands in the benchmark.
- Auto-accept only when signals agree; anything else queues. Target from today's data:
  ≥ 90% auto, ≤ 10% human, 0 silent wrong picks on the benchmark.

## 3. Explicitly out of scope for the first phase
- Cleaning the 88 `Title (YYYY)` identities (touches `films.key`; own step with before/after).
- Metacritic movie-page crawl for directors.
- Any sweep. The 60 remaining director-less films are worked through the A/B/C table.

## 4. Open questions for the owner
- Is a `Title (YYYY)` film that matches a clean-titled twin a merge (Dalmatians case) — always?
- Should `Type: series` (Dekalog) be a film here, or excluded from the brain?
- Retitle policy: rewrite `films.title` to the clean form, or keep the ingested string and add a
  display title?
