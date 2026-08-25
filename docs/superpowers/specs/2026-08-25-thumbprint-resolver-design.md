# Thumbprint T1 — resolver spec + migration steps 0–1

**Date:** 2026-08-25 · **Status:** spec (T1). Binding inputs: the design memo
`docs/superpowers/research/2026-08-25-thumbprint-design.md` (identity model §1, grammar §2,
ALG3 §3, review contract §4, owner decisions §8) and CLAUDE.md. This spec does not re-open
any memo decision; where the memo left a shape open ("claims … or carry these columns") it
picks one and says why.

**Scope of T1:** (a) the benchmark gate, (b) the resolver as a pure domain module with an
infrastructure candidate fetcher, (c) migration step 0 (claims schema + backfill), (d)
migration step 1 (the 82 `Title (YYYY)` films). **Out of scope:** switching any ingester to
the resolver (memo step 5), steps 2–4, the A/B/C `review resolve --pick` UI, dashboard
edition badges. The resolver ships *dark* in T1: callable, benchmarked, unused by sync.

## 0. Non-negotiables

- No live-DB write without announce → approve → diff, one group at a time (memory:
  one-at-a-time). Step 0's migration is the single exception where "one at a time" means one
  migration, previewed as a full dry-run diff first.
- `OMDb t=` is never called by new code. New code fetches OMDb by `i=` only.
- The gate is offline: no network unless `--refresh`.
- Films are immutable; collectors never delete. Step 1 uses `merge_film` only.

## 1. Benchmark gate (`scripts/thumbprint_benchmark.py`)

### 1.1 Contract file
`scripts/eval/thumbprint_eval_v1.csv` is the contract. **State after T1 Task 1 (done):
527 rows** = the 498 that were checked in ∪ the research session's scratch set (which held
group E's 23 benchmark rows and 6 more `proposed` D rows the check-in had lost). Scored
population 482 (`verified`+`believed` with an expected key); 38 `proposed`; 7 unresolved
(empty `expected_tt`); one `NONE`.

Two columns are added, both derived once, read-only, from the live DB:
- `director` — `films.director` at eval-build time (152/498 non-empty). The prototype read
  this live; the gate must not. It is the *query's* director, i.e. what the ingest source
  supplied (Criterion) or what the film row already held.
- `runtime_min` — Apple archive runtime for `apple` rows (stored, shown, never decides).

### 1.2 Fixture
`scripts/eval/fixtures/cand_cache.json.gz` — the 8.9k-entry candidate cache from the
prototype run (o: 4,907 OMDb-by-id/search, td: 1,930 TMDB details, ts/tsy: 1,722 searches,
person/credits: 310). Before check-in: **strip the OMDb API key from the `o:` keys** (the
prototype embedded it in the JSON key), gzip. Expected ≈8 MB. `--refresh` re-fetches only
missing keys using the real clients and rewrites the fixture.

### 1.3 Gate rules
```
uv run python scripts/thumbprint_benchmark.py [--assert] [--status verified|believed|proposed] [--group X] [--refresh]
```
- Scored population: rows with `status ∈ {verified, believed}` and non-empty `expected_tt`.
  `proposed` rows are reported in a separate line, never scored.
- **Wrong = 0** on the scored population, then **auto ≥ 90%** (`--assert` exits 1 otherwise).
  A match on an `expected_tt = NONE` row is wrong.
- Prints the memo's scoreboard shape (n / WRONG / auto-correct % / review %), per-group
  breakdown, review reasons, and every WRONG row. **Baseline (T1, reproduced offline):
  n=482, WRONG=0, auto 457 (94.8%), review 25 (5.2%), 0 fixture misses; proposed rows: 26
  agree / 0 disagree / 12 review.** The lift over the memo's 93.0% comes from alt-title forms
  and group E.
- `scripts/matching_benchmark.py` is untouched and still gates `domain/matching.py`.
- A pytest (`tests/unit/test_thumbprint_benchmark.py`) runs the gate on a 20-row slice of
  the fixture so `uv run pytest` catches resolver regressions without the full 498.

## 2. Resolver — domain module `domain/thumbprint.py`

Pure: no I/O, no SQL. Imports only `domain/matching.norm_title` (kept, 300/300).

### 2.1 Title grammar
```python
@dataclass(frozen=True)
class ParsedTitle:
    title: str                 # what to search / normalize
    editions: tuple[str, ...]  # casefolded vocabulary labels, outermost first
    embedded_year: int | None  # (YYYY) / [YYYY], DATABASE-class
    alt_titles: tuple[str, ...]  # trailing non-vocabulary parentheticals, kept for matching

def parse_title(raw: str) -> ParsedTitle
```
Behaviour = memo §2, lifted from the prototype's `eval_lib.parse` plus alt-title capture:
trailing-only, bracket-aware, iterated; leading parens are title; never strip to empty.
`title` keeps a trailing non-vocabulary parenthetical (`Caché (Hidden)`) because that is the
search form the fixture was fetched with; `base` drops it (`Caché`); `forms()` = title, base
and the alt itself, and an exact hit on any form is title level 3. `films.title_norm` =
`norm_title(parse_title(title).base)`. The prototypes are deleted (done in T1); the domain
module is the single source of the vocabulary.

### 2.2 Query and candidates
```python
class YearClass(StrEnum): DATABASE="database"; MC="mc"; APPLE_FIELD="apple-field"

@dataclass(frozen=True)
class Query:
    raw_title: str
    year: int | None          # after embedded-year override
    year_class: YearClass
    source: str               # "criterion" | "metacritic" | "apple" | "benchmark"
    director: str | None
    runtime_min: int | None   # carried, never scored (owner Q3)

@dataclass(frozen=True)
class Candidate:
    tt: str                   # unify key; TMDB-only candidates without imdb_id are dropped
    tmdb_id: int | None
    titles: tuple[str, ...]   # TMDB title/original/alternative + OMDb title
    year: int | None
    directors: str            # comma-joined
    runtime_min: int | None
    votes: int
    kind: str                 # OMDb Type or "movie"
    in_tmdb: bool
    in_omdb: bool
```
`Query.year_class`: `criterion`/`benchmark` or an embedded year → `DATABASE`; `metacritic`
→ `MC`; `apple` field year → `APPLE_FIELD`.

### 2.3 Verdict
```python
@dataclass(frozen=True)
class Scored:  # one per surviving candidate, in rank order
    candidate: Candidate; title_level: int; year_points: int; director_points: int
    agreement: bool; older: bool; why_not: str | None

@dataclass(frozen=True)
class Verdict:
    kind: Literal["match", "review"]
    tt: str | None
    reason: str               # memo §3 reasons, verbatim strings from the prototype
    ranked: tuple[Scored, ...]  # top 3 become the A/B/C review rows

def resolve(query: Query, candidates: Sequence[Candidate]) -> Verdict
```
Signals and verdict order are memo §3 exactly, ported from `alg3()` in the prototype with
`use_runtime=False` hard-wired (no runtime parameter exists in the domain API — ALG4 is not
a flag, it is absent). `dir_match` name-token rule, junk regex, `generic` definition, the
IMDb-duplicate drop, `rerelease-ambiguous`, dominance (≥1,000 and ≥20×) all carry over
unchanged. Port fidelity is proven by the gate reproducing the baseline.

### 2.4 Candidate fetcher — `infrastructure/thumbprint_fetch.py`
```python
class CandidateFetcher:
    def __init__(self, tmdb: TmdbClient, omdb: OmdbClient, cache: CandidateCache): ...
    def fetch(self, q: Query) -> list[Candidate]
```
Pool per memo §3: TMDB `search(title)` ∪ `search(title, year=)` ∪ (director → `search/person`
top-2 → `movie_credits` Director jobs filtered exact-title or ±2 y + containment) ; OMDb
`s=title` and `s=title&y=`; TMDB detail with `external_ids,credits,alternative_titles` for
every candidate; OMDb `i=` for every tt. `CandidateCache` is a key→JSON dict with the
fixture's key scheme (`ts:`, `tsy:`, `td:`, `person:`, `credits:`, `o:` **without** apikey) so
one fetcher serves the gate (fixture-backed, read-only) and live use (config-dir cache
`<config_dir>/thumbprint/cand_cache.json`, append-only). New `TmdbClient` methods:
`search_any_year(title, year)`, `search_person(name)`, `person_movie_credits(id)`,
`movie_detail(id)`; new `OmdbClient.search(title, year=None)` and `by_id(tt)`. No `t=`.

## 3. Migration step 0 — claims schema (`migrations/011_claims.sql`)

**Shape decision: one `claim` table, not columns on three tables.** Reasons: (i) a work may
hold several claims from one authority, which `owned`'s `film_id` PK and `external_ids`'s
`(film_id, authority)` PK forbid; (ii) the A/B/C reviewer and the dashboard badge need one
query, not three; (iii) pure-copy backfill is reversible (drop table) without touching the
source tables. The source tables stay as they are in T1 — they remain the writers' targets
until the ingester switch (step 5), when they either shrink to claims or are dropped.

```sql
BEGIN;
CREATE TABLE claim (
    id              INTEGER PRIMARY KEY,
    film_id         INTEGER NOT NULL REFERENCES films(id),
    authority       TEXT    NOT NULL,   -- 'criterion' | 'metacritic' | 'apple-tv'
    value           TEXT    NOT NULL,   -- criterion url | metacritic slug | apple raw title
    title_ingested  TEXT    NOT NULL,
    year_claimed    INTEGER,
    edition_label   TEXT,               -- parse_title().editions joined by ' / ', NULL if none
    edition_year    INTEGER,            -- NULL in step 0; step 2 fills for group C
    runtime_min     INTEGER,            -- apple archive only
    first_seen      TEXT    NOT NULL,
    UNIQUE (authority, value)
);
CREATE INDEX claim_film ON claim(film_id);
ALTER TABLE films ADD COLUMN title_norm TEXT;   -- derived; backfilled by the app, not SQL
ALTER TABLE films ADD COLUMN kind TEXT NOT NULL DEFAULT 'movie' CHECK (kind IN ('movie','series'));
INSERT INTO schema_version (version) VALUES (11);
COMMIT;
```
`external_ids` PK is **not** loosened in T1 — nothing in steps 0–1 inserts a second
`(film_id, authority)` row; that DDL rides with step 2 (edition claims) where it is first
needed. Recorded here so it is not forgotten.

**Backfill** (`movie-brain thumbprint backfill [--apply]`, application/thumbprint.py):
- `owned` (935) → `claim(apple-tv, value = raw title from the latest archive line that
  matched the film, title_ingested = same, year_claimed = archive year, runtime_min)`. The
  raw-title link is recovered by replaying the archives through the existing `parse_apple_title`
  → film match already recorded; rows whose raw line cannot be recovered get `value =
  films.title` and a `note`-less first_seen = `owned.first_imported`.
- `listings` where `source='criterion'` (3,050) → `claim(criterion, value = url,
  title_ingested = films.title, year_claimed = films.year, first_seen = listings.first_seen)`.
- `external_ids` authority `metacritic` (1,511) joined to `metacritic` → `claim(metacritic,
  value = slug, title_ingested = metacritic.title, year_claimed = metacritic.year, first_seen =
  external_ids.first_seen)`.
- `edition_label` from `parse_title(title_ingested)` for every row.
- `films.title_norm` for every film. `films.kind` stays `movie` (series keying is step 3+).
Dry run prints counts per authority + the first 20 rows per authority + every row whose
`edition_label` is non-NULL (expected ≈54). `--apply` is idempotent (`INSERT OR IGNORE`).
Reversibility: `DROP TABLE claim` + the two columns are nullable/defaulted; no source row is
modified.

## 4. Migration step 1 — the 82 `Title (YYYY)` films

Live state today (read-only): **82 undisposed** `Title (YYYY)` films, 6 already disposed, 28
dispositions total, 299 open `no-match` rows.

New verb: `movie-brain repair twins [--apply] [--yes]` in `application/repair.py`, same shape
as `repair dupes`:
1. Worklist = undisposed films whose `parse_title(title).embedded_year` is set.
2. For each, candidate twin = undisposed film with equal `title_norm` and `year ==
   embedded_year`, and (guard) the twin's TMDB `imdb_id` equals the raw row's OMDb `imdbID`
   when both exist. Eval group B is consulted: a worklist row whose `film_id` appears in the
   CSV with a `twin NNNN` note must agree with the computed twin or the group is **skipped
   with a loud mismatch line** — the CSV is the contract, the query is the check.
3. Classification: `TWIN` (exactly one twin, guard passes) → `merge_film(raw → twin)`;
   `NO-TWIN` (Doctor Strange 2016) → key directly: write `external_ids tmdb/imdb` from the
   OMDb-by-id record already stored, retitle to the parsed title, year stays; `CONFLICT`
   (guard fails or several twins) → print, skip, never guess.
4. *Rear Window (1954)* (`films.year = 2013`): handled inside its group as `update_film_year`
   → 1954 before the merge, because the twin lookup keys on `embedded_year`, not `films.year`.
5. Every applied group appends an eval row (group B, `verified_by=human`, `status=verified`)
   if not already present, and prints before/after: the two film rows, moved
   owned/listing/external_ids counts, resolved review rows.
6. `--apply` without `--yes` prompts per group; the plan runs it **without `--yes`**, in
   batches the owner sizes, with the announce → approve → diff loop around each batch.

Expected end state: 81 merges + 1 direct key, 82 fewer open `no-match` rows (the 72 Apple
`(YYYY)` no-match rows resolve as loser rows in `merge_film`), `Title (YYYY)` count 0.

## 5. Review contract (data only in T1)

`match_review.detail` for resolver-produced rows is JSON: `{"reason": …, "candidates":
[{"letter":"A","tt":…,"tmdb_id":…,"title":…,"year":…,"director":…,"runtime":…,"votes":…,
"in_tmdb":…,"in_omdb":…,"why_not":…}, …]}` (≤3). T1 writes none (no ingester switch) but the
`Verdict → detail` serializer lives in `application/thumbprint.py` and is unit-tested so the
step-4/5 phases don't invent a second format. `review resolve --pick/--tt/--none` is **not**
built in T1.

## 6. Tests

- `tests/unit/test_thumbprint.py`: grammar table (all 54 annotated live titles from the
  annotations research + the memo's edge cases: `(500) Days of Summer`, `Caché (Hidden)`,
  `LYNCH (one)`, `Redux`, `(Unrated) [2011]`); `resolve()` unit cases for each verdict rule
  (one fixture per rule, hand-built candidates, no cache).
- `tests/unit/test_thumbprint_benchmark.py`: 20-row fixture slice, asserts 0 wrong.
- `tests/unit/test_database.py`: migration 011 applies on a fresh DB and on a DB at v10;
  `claim` UNIQUE guard.
- `tests/features/thumbprint.feature` + step defs: backfill dry-run/apply idempotence;
  `repair twins` TWIN / NO-TWIN / CONFLICT / CSV-mismatch scenarios with `merge_film`
  side-effects asserted (owned + listings moved, review resolved).
- Gate: `scripts/thumbprint_benchmark.py --assert` green; `scripts/matching_benchmark.py
  --assert-dominance` still green (matching.py untouched).

## 7. CLAUDE.md / rules edits (in T1)

- Add `thumbprint backfill`, `repair twins`, `scripts/thumbprint_benchmark.py --assert` to
  Commands.
- New `.claude/rules/thumbprint.md` scoped to `domain/thumbprint.py`,
  `infrastructure/thumbprint_fetch.py`, `application/thumbprint.py`,
  `scripts/thumbprint_benchmark.py`: gate-before-change, no `t=`, runtime dark, fixture
  key scheme. Year-precedence rewrite in CLAUDE.md waits for step 2 (when `films.year` actually
  starts moving).

## 8. Open items carried forward (not blocking T1)

- `external_ids` PK loosening (step 2). Transliteration folding for directors (Shinarbaev).
- Whether `owned`/`listings`/`metacritic` shrink to views over `claim` after step 5.
- Memo count 533 vs contract 498 (+6 scratch) — reconcile when ratifying via A/B/C.
