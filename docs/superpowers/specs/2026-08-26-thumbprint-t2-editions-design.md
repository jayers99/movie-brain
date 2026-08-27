# Thumbprint T2 — edition-year films, external_ids loosening, A/B/C review flow

**Date:** 2026-08-26 · **Status:** approved design (owner answered the five decisions in
`docs/superpowers/research/2026-08-26-thumbprint-t2-decisions.md`: all five = recommended).
**Inputs:** handoff `docs/superpowers/handoffs/2026-08-25-thumbprint-t2-handoff.md`, binding memo
`docs/superpowers/research/2026-08-25-thumbprint-design.md` (§1, §4, §7 step 2, §8), T1 spec
`2026-08-25-thumbprint-resolver-design.md`. **Branch:** `feature/T2-thumbprint-editions`.

## 0. Scope

| in | out |
|---|---|
| A. `repair editions` — the 16 edition-year films → work identity | wiring `resolve()` into any ingester (resolver stays DARK) |
| B. migration 012 — `external_ids` PK `(film_id, authority)` → `(film_id, authority, value)`; fan-out guards; merge policy | memo step 3 (94 disagreements) and step 4 (no-match rerun) |
| C. `review resolve --pick / --tt / --none`, A/B/C rendering in `review list`, eval-row append | any live resolution of the 225 `no-match` rows (rehearsal on scratch only) |
| rules/docs updates (`thumbprint.md`, CLAUDE.md commands + external_ids bullet) | dashboard edition badges (later) |

Gate at every step: `uv run pytest`, `ruff`, `mypy`, `scripts/thumbprint_benchmark.py --assert`
(baseline n=482 / 0 wrong / 94.8 %), `scripts/matching_benchmark.py --assert-dominance`. The
eval CSV is never edited to make the gate green.

## 1. Live facts the design rests on (verified read-only 2026-08-26)

- Schema v11; films 4,666 · dispositions 102 · claims with `edition_year` 0 · `imdb` ids 549.
- The 16 films (`films.year` ≠ work year in eval group C): undisposed, `kind=movie`, no
  `imdb`/`tmdb` id, one claim each (edition_label set), one open `tmdb no-match` row each.
  8 Apple ones are `owned`; none rated/watchlisted.
- 10 twins hold `tmdb` = the row's `expected_tmdb` and OMDb `imdbID` = `expected_tt`.
  #4269 Overlord (2018) holds tmdb 438799 ≠ 55343 → rejected by the contract check.
- No series row for Scenes from a Marriage; no film holds any target key
  (`blade runner (1982)`, `donnie darko (2001)`, `scenes from a marriage (1974)`, …).
- Eval CSV: 4 `proposed` rows (all D-disagree), none with an open review row.
- No film today holds two claims of one authority, and none of the 10 merges puts two
  metacritic slugs on one film.

## 2. A — `repair editions`

### 2.1 Worklist and contract
`load_edition_contract(csv)` → rows with `group == "C-edition"`, `status == "verified"`,
non-empty `expected_tt`, parsed from `note` `work='…' YYYY` → `work_year`, and only where
`films.year != work_year` (16 today). The row's `expected_tt` / `expected_tmdb` / `work_year`
ARE the contract; the verb never computes a target year or key from the network.

### 2.2 Audit (pure, read-only) → `EditionGroup`
```
EditionGroup(film_id, title, old_year, work_title, work_year, tt, tmdb_id,
             verdict: twin|no-twin|conflict|csv-mismatch, twin_id, edition_year, detail)
```
- `work_title = parse_title(title).base` (Donnie Darko: "Donnie Darko"; Quai des Orfèvres
  keeps its French title — TMDB's "Jenny Lamour" is an alt title, not a retitle).
- `edition_year = old_year` **except when `old_year < work_year`** → `None` (#1909 Scenes
  from a Marriage: 1973 is the series year, not an edition release year — owner decision 2).
- Twin search over undisposed films (excluding the film itself): `title_norm(work_title)`
  equal AND `films.year == work_year`. A candidate **agrees** with the contract when its
  `tmdb` external id == `expected_tmdb`, OR it has no `tmdb` id and is itself a C-edition
  contract row with the same `expected_tt` (two editions of one work — Donnie Darko #3517 →
  #4404). Verdicts:
  - exactly one agreeing candidate → `twin` (other, non-agreeing candidates such as Overlord
    #4269 are ignored — they are different works)
  - two or more agreeing candidates → `conflict`
  - none → `no-twin`, downgraded to `conflict` when `film_key(work_title, work_year)` is held
    by another live identity, or `expected_tt` / `expected_tmdb` is held by another film
- Not listed at all (idempotence — a second `--apply` reports 0 groups): a disposed film, or
  one whose `films.year` already equals `work_year` (#4404 Donnie Darko Anniversary, 2001).
- `csv-mismatch`: the film's current title no longer parses to the `work='…'` named in the
  note (hand-edited since the CSV was written) — skipped loudly.
- When a `twin` survivor's own title still parses with editions (#4404), the twin action
  also applies the no-twin retitle/key step to the survivor after the merge.

### 2.3 Apply (per confirmed group, one transaction each)
`twin`:
1. `merge_film(film_id → twin_id, note="repair editions '<title>'")` (moves the claim,
   resolves the loser's open reviews, keeps the loser's `films` row).
2. `set_claim_edition_year(claim_id, edition_year)` on the moved claim (skip when `None`).
3. `ensure_external_id(twin_id, 'imdb', tt)` if the twin has no imdb id (tmdb already there).
4. If the twin's title still parses with editions (Donnie Darko) → `key_work(twin_id, …)`
   as in no-twin steps 1–3.

`no-twin` (the row becomes the work) — `Repository.key_work(film_id, *, title, year, tt,
tmdb_id, today) -> bool`, one transaction, False + nothing written on any holder clash:
1. `films.title = work_title`, `films.year = work_year`, `key = film_key(work_title,
   work_year)`, `title_norm` recomputed (same own-loser dead-key rule as `update_film_year`).
2. `external_ids imdb = tt`, `tmdb = tmdb_id` (owner decision 1).
3. resolve the film's open `tmdb no-match` row with note `repair editions keyed tmdb N`.
4. `set_claim_edition_year` on the film's edition claim.
5. `clear_revisit(film_id)`.

Neither path touches `omdb` (the by-title stub stays; `needs_refresh=1` is set so the next
sync refetches by id — `repair years --apply` precedent), `owned`, `listings`, `my_ratings`.

### 2.4 CLI
`movie-brain repair editions [--apply] [--yes] [--limit N]` — same confirm/limit/log shape
as `repair twins`; `[verdict]` lines via `_plain`. Summary line:
`groups G · twin T · no-twin N · conflict C · csv-mismatch M · applied A · declined D`.
No eval-row append (every film is already a group-C row; T1 precedent).

## 3. B — migration 012 + policy

### 3.1 `migrations/012_external_ids_multi.sql`
```sql
BEGIN;
CREATE TABLE external_ids_new (
    film_id INTEGER NOT NULL REFERENCES films(id),
    authority TEXT NOT NULL,
    value TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    PRIMARY KEY (film_id, authority, value),
    UNIQUE (authority, value)
);
INSERT INTO external_ids_new SELECT film_id, authority, value, first_seen FROM external_ids;
DROP TABLE external_ids;
ALTER TABLE external_ids_new RENAME TO external_ids;
INSERT INTO schema_version (version) VALUES (12);
COMMIT;
```
Row count asserted equal before/after in the rehearsal (and in a unit test on a seeded DB).

### 3.2 Authority classes (`domain/identity.py` or a constant in `database.py`)
`KEY_AUTHORITIES = {"tmdb", "imdb"}` — one per work. Everything else is a claim authority.

- `set_external_id(film_id, authority, value)`: key authority → replace the film's row for
  that authority (`DELETE … WHERE film_id, authority` then INSERT); claim authority →
  `INSERT OR IGNORE`. `UNIQUE(authority, value)` still raises when another film holds it.
- `key_film_directly`, `key_work`, `record_tmdb_match`'s writer: same replace semantics.
- `merge_film`: key authority held by both → drop loser's (recorded in `kept`, today's
  behaviour); claim authority → **move** (owner decision 3). `MergeReport` unchanged.

### 3.3 Fan-out guards (one metacritic slug per film)
`_VIEW_SQL`, `audit_subjects`, the Mode-B promotion query, and `metacritic_claim_rows`
currently `LEFT JOIN external_ids x … authority='metacritic'`. Each becomes a join on a
derived table `(SELECT film_id, MIN(value) … GROUP BY film_id)` ordered by
`first_seen, value` — deterministic, one row per film. `metacritic_claim_rows` is the one
exception: it must return EVERY slug (claims are per slug) — it already does; unchanged.
Test: a film with two slugs → `list_views` returns one row, `audit_subjects` one row.

### 3.4 Docs
CLAUDE.md `external_ids` bullet: "PK `(film_id, authority, value)`; `UNIQUE(authority,
value)` remains the dedup guard; tmdb/imdb are single per work by policy, claim authorities
may repeat". `.claude/rules/thumbprint.md`: add the policy line and `repair editions`.

## 4. C — A/B/C review flow

### 4.1 Detail format
`review_detail(verdict, query=None)` gains an optional `query` object
`{title, year, source, director, runtime}` serialized alongside `reason`/`candidates`. Still
the ONLY resolver-row format; the benchmark doesn't call it. `parse_review_detail(detail)`
returns `(reason, candidates, query)` or `None` for non-JSON legacy details.

### 4.2 `review list`
Rows whose detail parses with `candidates` render, under the row, one line per candidate:
`A tt0083658 · Blade Runner (1982) · Ridley Scott · 117m · score …/why_not`. Legacy rows
unchanged. `--authority`/`--reason` filters unchanged.

### 4.3 `review resolve` new options (mutually exclusive with the existing four)
| option | accepted on | writes |
|---|---|---|
| `--pick A\|B\|C` | rows with `candidates` | `imdb = cand.tt`; `tmdb = cand.tmdb_id` via `record_tmdb_match` (year adoption + collision review reuse the sync path); `id-conflict` result → ValueError "held by another film — merge instead" |
| `--tt tt…` | any `tmdb` row | `imdb = tt`; `tmdb` via `TmdbClient.find_by_imdb(tt)` (`/find/{tt}?external_source=imdb_id`, first `movie_results`) when a client is given, else imdb only + warning line |
| `--none` | any `tmdb` row | nothing; note `verified unkeyed` |
All three: `resolve_review(id, note)`, `clear_revisit`, then eval append (4.4).

### 4.4 Eval append — `application/eval_log.py::ratify(csv_path, entry)`
`EvalEntry(film_id, source, title_ingested, year_ingested, expected_tt, expected_tmdb,
note)`. Source/title/year come from `query` when present, else `films.title/year` and the
film's first claim authority (`criterion` > `metacritic` > `apple`; `unknown` if none).
- existing row with same `film_id` **and** `source` and `status == proposed` → rewrite that
  row: `status=verified`, `verified_by=human`, `expected_tt/expected_tmdb` from the
  resolution, note appended `human: was <old tt>` when it differed;
- otherwise append `group=F-human, status=verified, verified_by=human`;
- `--none` → `expected_tt = NONE`, `expected_tmdb` empty.
The CSV is rewritten atomically (temp file + rename). The gate scores the new rows; missing
fixture keys score as `review` (never wrong) — accepted (owner decision 5); rules doc says
"run `thumbprint_benchmark.py --refresh` after a ratification batch".

## 5. Testing
- unit: `load_edition_contract` (note parsing, filtering), `audit_editions` verdict table
  (twin / no-twin / conflict / Donnie-Darko agreement rule / Scenes `edition_year=None`),
  `key_work` holder clashes, migration 012 rebuild preserves rows, `set_external_id`
  replace-vs-ignore, `merge_film` key-drop vs claim-move, fan-out guard (two slugs → one
  view row), `parse_review_detail`, `ratify` (append vs rewrite-proposed, NONE, atomic).
- pytest-bdd `repair.feature`: "An edition-year film merges into its work twin and keeps the
  edition year on its claim", "An edition-year film without a twin becomes the work".
  `review.feature`: `--pick B`, `--tt`, `--none`, invalid combos.
- `tests/web`: the dashboard shows Blade Runner once after a two-slug film exists.

## 6. Rehearsal + live protocol (unchanged from T1)
`cp` live DB (+`appletv/`) to scratch; `MOVIE_BRAIN_CONFIG_DIR=$SCRATCH`:
1. `status` (triggers 012; backup lands in `$SCRATCH/backups/`), assert `external_ids`
   count unchanged.
2. `repair editions` dry run → expect 10 twin / 6 no-twin / 0 conflict / 0 csv-mismatch.
3. `--apply --yes` in batches → expect edition_year 15 (Scenes NULL), dispositions
   102 → 112, imdb ids 549 → 565, open no-match 225 → 209, films 4,666 (never deleted).
4. `review resolve <id> --tt … / --none` on scratch rows, with `--eval-csv $SCRATCH/eval.csv`
   (hidden option, default = the repo CSV) so the rehearsal never touches the real contract.
Live: migration first (its own approval), then editions in batches of ~8, before/after
counts pasted; no live `review resolve` in T2.
