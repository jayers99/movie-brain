# Thumbprint: reliable movie identity — DESIGN MEMO (evidence-backed, pre-spec)

**Date:** 2026-08-25 · **Status:** design approved in session (owner answered the three open
questions, §8); no implementation, no live-DB writes. Next step is a spec + plan per the phased
workflow. Inputs: the handoff package (`…/research/2026-08-25-thumbprint-handoff.md`), the seed
spec, the annotations research. Evidence artefacts from this session:
`scripts/eval/thumbprint_eval_v1.csv` (533 cases), `scripts/eval/thumbprint_score_prototype.py`
(+ two fetch prototypes), and the appendices below.

## 0. Conclusions first

1. **Identity = the work**, keyed `tmdb_id → tt`. Editions (Final Cut, [re-release], dubbed
   version) are **claims** on a work, never films. TMDB and IMDb key works only; edition-as-film
   is unkeyable (0/28 would have a key).
2. **The 08-23 damage was two ingest failures, not one**: Mode-B promotion (18 → 102 director-less,
   70 of 84 with no OMDb record because a commerce year fed `t=&y=`) then the Apple import
   (102 → 345; 82 raw `Title (YYYY)` films created by `clean_apple_title`, 81 now twinned).
3. **"v5 was clean" is only true for the director-less proxy.** 59 OMDb-vs-TMDB key
   disagreements already existed in v5 with the same OMDb record. A wrong-but-complete record
   has a director. The proxy under-counts wrong matches.
4. **The old benchmark measured the wrong thing** (corpus dedup, 0 `title+year → tt` cases).
   The new eval set is the contract.
5. **A resolver exists that makes 0 wrong matches on 526 cases at 93.0% auto / 7.0% review**
   (ALG3, §3), versus 30 wrong for the current pipeline. The biggest single gain is using the
   director as a *search key* (TMDB person → credits), not just as evidence.

## 1. Identity model (decided)

- **Work**: `films` row; `guid` stays the internal identity; `external_ids` carries `tmdb` and
  `imdb` for every keyed work; `films.year` = TMDB original release year; `films.title_norm` =
  grammar output (derived, not editable); `films.kind ∈ {movie, series}`.
- **Series/anthologies are works with `kind = series`, keyed by the IMDb series id** (owner
  decision, Q2): Dekalog → `tt0092337`; Small Axe parts → their episode tt; Scenes from a
  Marriage TV cut (`tt0070644`) is a distinct work from the theatrical film (`tt6725014`).
- **Claim**: one source's assertion about a work —
  `(work_id, authority, value, title_as_ingested, year_claimed, edition_label, edition_year,
  runtime_min, first_seen)`. `owned`, `listings`, `metacritic` slugs become claims (or carry these
  columns). A work may hold **several claims from one authority** (Apocalypse Now: MC slugs
  `apocalypse-now` 94, `apocalypse-now-redux` 92, `apocalypse-now-final-cut` 92; Apple owns both
  *Straight Outta Compton* and its Unrated cut). `external_ids` UNIQUE(authority, value) stays;
  its PK `(film_id, authority)` loosens.
- **Unkeyed work** is legal: `tt IS NULL`, `review_state = 'unkeyed'` (3/526 eval cases are
  Criterion shorts absent from both authorities). Never enriched by title search.
- Year truth: `films.year` from TMDB. **Criterion's year is a claim year (±2), no longer the
  truth-holder** (Emitaï 1971/1973, Blood of a Poet 1930/1932, Visitation 2011/2013, Take Out
  2004/2008). Metacritic's `[re-release]` year is not reliably the re-release year either
  (`band-of-outsiders-re-release` carries 1966).
- Blade Runner, worked: one work `tmdb:78 / tt0083658`, 1982, `bladerunner`; claim
  `owned(apple, "Blade Runner (The Final Cut)", edition="the final cut", edition_year=2007)`;
  a future Criterion listing of the 1992 cut is a second claim. One dashboard row, edition badges.

## 2. Title grammar (one function, ingest and search)

`parse(s) → (title, editions[], embedded_year, alt_titles[])`, trailing-only, bracket-aware,
iterated until nothing peels:
- `(YYYY)` / `[YYYY]` → `embedded_year` (a DATABASE-class year).
- `(…)`, `[…]`, `: …`, `– …` whose content matches the vocabulary → `editions[]`. Vocabulary =
  annotations doc §3 plus `english/german version`, `english-dubbed version`, `dubbed`,
  `subtitled`, `imax`, `3d`, and the undelimited `redux`.
- A trailing parenthetical that is **not** vocabulary is an **alt title** kept for matching
  (`Caché (Hidden)`, `LYNCH (one)`, `Egungun (Ancestor Can't Find Me)`), never stripped.
- Leading parens are title (`(500) Days of Summer`). Never strip to empty.
- `norm_title` unchanged (NFKD, `&`→and, `$`→s, `vol`→volume, alnum only) — 300/300
  key-agreement cases normalize correctly. Search also indexes TMDB `alternative_titles`
  (Quai des Orfèvres ↔ Jenny Lamour was ALG3's one avoidable review).
Verified: all 54 annotated live titles parse; 27/28 edition titles resolve to their work.

## 3. Evidence model = ALG3 (0 wrong / 489 auto (93.0%) / 37 review (7.0%), n=526)

**Candidate pool** per query `(title, year, source, director?, runtime?)`:
TMDB `search(title)` ∪ `search(title, year=)` (any-release-year) ∪ **`person(director) →
movie_credits` filtered by title/±2 years** (when the source supplies a director) ; OMDb `s=`
on the normalized title ; full records by id for every candidate. **OMDb `t=` is never called.**
Candidates unify on `tt`. Each carries: titles (TMDB title/original/alts + OMDb title), year,
director(s), runtime, `imdbVotes`, `Type`, `in_tmdb`, `in_omdb`.

**Per-candidate signals**
- title level: 3 exact normalized (any title form) · 2 official longer title (candidate title
  starts with the query, query ≥ 8 chars) · 1 fuzzy ≥ 0.85 · 0 drop.
- director: name-token overlap (≥2 tokens, or 1 when a name has ≤2 tokens) → +3; conflict →
  disqualify; absent → 0. (`Jeffrey Lau` = `Jeffrey Lau Chun-Wai`; `Shinarbaev`≠`Shinarbayev`
  is a known miss — add transliteration folding later.)
- year, by **source class**: `database` (Criterion, embedded `(YYYY)`, benchmark): ±1 → +2,
  ±2 → +1, else drop. `mc`: same, and an older exact-title film is a neutral gap. `apple-field`:
  same as `mc`. Any edition label present ⇒ year is not evidence. **Director match ⇒ year ignored.**
- agreement: present in both TMDB and OMDb search → +1.
- junk shape (`making of`, `bande-annonce`, `trailer`, `q&a`, `panel`, `a look at`, `featurette`,
  `w/`, `on POV`, `reviews`, `sing-along`, `timelapse`, `podcast`) and `Type ≠ movie` → drop,
  **unless director-corroborated** (Wenders' *Die Insel* is `episode` on IMDb).

**Verdict order**
1. If any exact-title candidate exists, longer-title candidates are dropped (kills *Daddy's
   Home 2*, *Friday the 13th Part 2* ties).
2. Exactly one director-corroborated candidate ⇒ **match**. Several ⇒ match the one with
   agreement or ≥100 votes if unique, else review `ambiguous (several director hits)`.
3. Drop OMDb-only, vote-less (<10) candidates duplicating a TMDB-keyed candidate at the same
   year (IMDb duplicates, *Muhammad Ali, the Greatest*).
4. **`rerelease-ambiguous`** ⇒ review when an older exact-title film exists AND (source is
   `apple-field` with any near hit) OR (`mc` with only a ±2 hit) OR (edition label with a near
   hit). *The Boston Strangler* 1968 vs 2006 under an Apple field year 2004 is undecidable.
5. Near hits (±2): exactly one, with agreement or ≥1,000 votes or (non-generic title and ±1) ⇒
   match; several ⇒ votes ≥20× dominance (min 1,000) ⇒ match, else review `ambiguous`.
6. No near hit, commerce source, older exact-title candidates: exactly one with agreement ⇒
   match (the claimed year was a re-release date); dominance ⇒ match; else review.
7. Dateless query: one exact candidate with agreement and a non-generic title ⇒ match.
8. Otherwise review `weak`. "Generic" = ≤2 words and no director.

**Apple runtime (ALG4) stays dark** (owner decision, Q3): stored on the claim and shown in the
review table, never decides. It would lift auto to 94.7% but decided *Irezumi* (1966 vs 1982)
against the DB's current record on runtime alone.

## 4. Human-review contract (A/B/C)

Every non-match writes a `match_review` row carrying `reason` and up to three candidates:
`(letter, tt, tmdb_id, title, year, director, runtime, votes, in_tmdb, in_omdb, why_not)`.
`review list` renders the table; `review resolve ID --pick A|B|C | --tt X | --none | --dismiss`.
`--none` = verified unkeyed, a standing decision. **Every resolution appends an eval row**
`(title_as_ingested, year, source → tt, verified_by=human)`. The 38 proposed + 7 undecided eval
rows are ratified through this flow (owner decision, Q1); until then the gate ignores them.
Expected load: ~7% of new ingests; ~40 rows for the current backlog.

## 5. Benchmark plan

- Contract: `scripts/eval/thumbprint_eval_v1.csv` — columns `group, film_id, source,
  title_ingested, year_ingested, expected_tt, expected_tmdb, verified_by, status`.
  Groups: A key-agreement sample (300), B `Title (YYYY)` (82), C editions (28), D the 94
  disagreements, E benchmark/audit ground truths (29). `status ∈ {verified, believed, proposed}`.
- Gate (`scripts/thumbprint_benchmark.py --assert`, to be written from the prototype):
  **0 wrong on verified+believed**, then auto ≥ 90%; `NONE` expectations count a match as wrong.
- Offline fixture: the candidate cache (~8k TMDB/OMDb responses) checked in so the gate needs no
  network; a `--refresh` flag re-fetches.
- `scripts/matching_benchmark.py` stays for corpus-dedup; it is no longer the resolver's gate.
- Five eval corrections were made during scoring; every one was a case where the DB's prior
  record misled the adjudication (OMDb `Director: N/A`, OMDb-only stubs). Keep that habit: an
  algorithm finding a director-corroborated candidate the DB lacks is evidence, not a failure.

## 6. M1–M4: keep / replace

| component | verdict | evidence |
|---|---|---|
| `films.guid`, `external_ids` UNIQUE(authority,value), `film_disposition`, `merge_film` | keep | right substrate; PK `(film_id, authority)` loosens for multi-claim authorities |
| `norm_title` | keep | 300/300 |
| `split_annotations`, `clean_title`, `clean_apple_title`, `parse_apple_title` | replace (§2) | 54 live titles survive them; `(Final Cut)`, `(Unrated) [2011]`, `Redux` unhandled |
| `match_candidates` corpus matcher | keep for twins, demote: ingest resolves to `tt` first, corpus lookup by `tt`; title matching only for unkeyed works | R5 |
| `pick_tmdb_match`, `TmdbClient.search` year retry | replace (§3) | 30 wrong on eval; popularity top-10 misses Criterion shorts |
| `OmdbClient.lookup` (`t=`) | delete | accepted stubs; by-id only |
| `TmdbArbiter` | replace | subsumed by source-class year policy + rerelease-ambiguous |
| `record_tmdb_match` year write-back + key-collision review | keep, re-route through claims | the 5 survivor-year fixes prove it |
| `audit` | keep; add check `OMDb imdbID ≠ TMDB imdb_id` | finds the 94 by itself |
| `repair *`, `review resolve` | keep verbs; feed A/B/C rows | |
| CLAUDE.md "Criterion/TMDB > …" year precedence | rewrite: TMDB > embedded year > Criterion (±2) > Apple field > Metacritic | §1 |

## 7. Migration — one-at-a-time compatible

Each step prints the full before/after diff, waits for approval, applies only that, and appends
its rows to the eval CSV. Backups per migration remain the last-resort net.
0. Schema: claim columns/table; `films.title_norm`, `films.kind`; backfill from `owned`,
   `listings`, `metacritic` (pure copy, reversible, no identity change).
1. **82 `Title (YYYY)` films**: 81 have a same-year clean twin whose TMDB key equals the raw
   row's OMDb-by-id key → `merge_film(raw → twin)`; *Rear Window (1954)* (year 2013) corrected in
   the same step; the 1 without a twin (*Doctor Strange* 2016) keys directly.
2. **15 edition-year films**: `films.year` → TMDB year (eval group C), old year → claim
   `edition_year`.
3. **94 disagreements**: 17 clear the TMDB link; 27 refetch OMDb by the TMDB tt; 5 adopt the
   credit-found record (Tiger, Nostos, Visitation, The Island, Birdman); 45 through A/B/C.
4. **299 open `no-match` rows**: rerun the resolver; ≈104 auto (72 are step 1's twins), rest to
   A/B/C or `--none`.
5. Switch ingesters (Criterion walk, MC promotion, `owned import`) to `resolve()`. Expected
   end state: the 60 director-less become ≈25 verified-unkeyed + ≈35 keyed.

## 8. Owner decisions (2026-08-25)
- Q1 ratification of 45 eval rows: **later, via the A/B/C flow**.
- Q2 series: **works with `kind = series`, keyed by the IMDb series id**.
- Q3 Apple runtime: **ALG3 only; runtime stays dark** (stored, shown, never decides).

## Appendix A — Phase 1 numbers (R1–R6)

| backup | time | films | dir-less | `Title (YYYY)` |
|---|---|---|---|---|
| v5 | 08-23 16:11 | 3,051 | 18 | 0 |
| v6 | 08-23 19:16 | 3,898 | 102 | 0 |
| pre-lawrence | 08-23 19:47 | 4,643 | 345 | 88 |
| v8 | 08-24 10:58 | 4,643 | 295 | 88 |
| v9 | 08-24 19:51 | 4,639 | 163 | 83 |
| live | 08-25 | 4,638 | 60 | 82 |

R1: `91c380e` created films with `clean_apple_title()`; `b3fe325` fixed it after the 82 existed.
R2: 54 titles still annotated after today's grammar (21 editions, ~25 alt-titles, 4 series-in-parens).
R3: 299 open `no-match`: 104 one exact title within ±2 (72 Apple `(YYYY)`), 7 several, 71 exact
title but year off (generic-title traps), 30 fuzzy only, 72 no results, 15 nothing plausible.
R5: benchmark had 0 `title+year → tt` cases. R6: OMDb rows re-fetchable by id; 28 merges only.
Live: OMDb imdbID vs TMDB imdb_id — 4,118 agree, 94 disagree (59 predate 08-23), 223 OMDb-only,
201 neither.

## Appendix B — Phase 3 scoreboard (n=526)

| algorithm | wrong | auto-correct | review |
|---|---|---|---|
| ALG0 current pipeline | 30 | 473 (89.9%) | 23 |
| ALG1 seed order literal | 12 | 455 (86.5%) | 59 |
| ALG2 + director + hazard | 3 | 471 (89.5%) | 52 |
| **ALG3** (§3) | **0** | **489 (93.0%)** | **37** |
| ALG4 + Apple runtime | 1 (Irezumi, disputed) | 498 (94.7%) | 27 |

ALG3 residue (37): 6 dateless Criterion entries, 6 Apple-field-year remake pairs, 3 films newer
than TMDB's index, 2 dual records (Threepenny Opera DE/FR, Godzilla Raids Again dupes),
Apocalypse Now (Final Cut), Quai des Orfèvres (alt title), plus generic-title shorts.

## Appendix C — Phase 4 edition evidence
TMDB: Redux/Final Cut/Director's Cut searches all return the single work; cuts are
`alternative_titles` and annotated `release_dates`. OMDb/IMDb: edition stubs only
(`tt24742930`, `tt6001166`). Live DB: 16 work-groups with an edition row, 14 lone edition rows,
15 carrying the edition year as `films.year`, 32 MC `*-re-release` slugs, 3 Apple double-owned
works, 3 Criterion concurrent version pairs.
