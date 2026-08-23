# Phase 2: Metacritic adapter — Mode A (enrich what we have)

**Date:** 2026-08-23 · **Status:** approved design
**Parent plan:** [multiple-movie-services.md](../../multiple-movie-services.md) — Phase 2.
**Handoff:** [2026-08-23-phase2-handoff.md](../handoffs/2026-08-23-phase2-handoff.md).
**Success bar:** first 10 browse pages crawled and archived; match run reports coverage %;
unmatched films logged to a durable review surface (never deleted, never blocking); full
suite + ruff + mypy green; dashboard and the 3 AM sync keep working unchanged.

## Decisions this spec implements (settled, dated — do not relitigate)

- **Scrape contract (2026-08-24):** polite one-and-done crawl — honest UA, ~1 req/3 s,
  raw-archive-then-parse, page cap as a parameter with checkpoint/resume, bounded retries,
  stop-and-keep-progress.
- **Immutable films / collectors never delete (2026-08-24):** unmatched ids are logged to a
  review queue, never dropped; nothing here deletes anything.
- **GUID identity (2026-08-24):** the Metacritic slug is a per-authority native id hanging
  off the film; it lives in `external_ids`, never as film identity.
- **Matcher rules (2026-08-24 spike, 98%):** strip `(re-release)`/`(NNNN)` annotations;
  punctuation/case-insensitive title compare (`$`→`s`); accept a title match whose original
  year ≤ MC year + 2 (MC stamps US re-release years). From
  `scripts/discovery/match_spike2.py`.

Decisions made during this brainstorm (2026-08-23):

- **Lookup method: browse-walk archive**, not per-title search. One sorted walk
  (metascore descending, unfiltered) is the source; films not in the archive are simply
  below the current walk floor.
- **Incremental dial, verified by hand:** start with **10 pages** (~240 titles), verify the
  join against the Criterion collection, then extend (110, 300, …) by re-running the crawl
  with a bigger cap. The archive never re-fetches a page it already has, so each extension
  costs only the new pages.
- **Score authority: scraped first, OMDb fallback.** `FilmView.metacritic =
  COALESCE(scraped score, omdb.metacritic)`. The ~96 films whose only Metascore is OMDb's
  (below any near-term walk floor) keep displaying it; nothing regresses.
- **No scraping in the nightly sync, ever.** Crawl and match are manual commands; sync is
  untouched this phase. (Cheap offline auto re-match of new Criterion films is a possible
  later follow-up, not built now.)

Live-DB context (2026-08-23): 3,051 films; 553 have an OMDb Metascore (266 ≥ 80, 191 in
68–79, 96 below 68). Mode A's realistic coverage ceiling is therefore ~18% of the
collection; the design optimizes reaching it cheaply, not inflating it.

## CLI — new `metacritic` sub-app

```bash
uv run movie-brain metacritic crawl --pages 10   # walk browse pages 1..N; archived pages skipped
uv run movie-brain metacritic match              # offline: parse archive → stage → match → report
```

- `crawl --pages N`: N is the **target page count, not an increment** — `--pages 110` later
  extends a 10-page archive by fetching pages 11–110. Default: 10.
- `match` is idempotent and re-runnable (after every archive extension, or after a parser
  fix). It touches no network.

## Crawl (`infrastructure/metacritic.py`)

- URL: `https://www.metacritic.com/browse/movie/?page=N` — server-rendered, sorted by
  metascore descending (probed 2026-08-23; 17,313 titles ≈ 722 pages).
- **Politeness:** honest User-Agent (`movie-brain/<version> (personal project)`), one
  request per ~3 s, timeout 30 s.
- **Archive = checkpoint.** Raw HTML saved to
  `<config_dir>/metacritic/pages/page-NNNN.html`; a page file on disk is never re-fetched.
  A sidecar `<config_dir>/metacritic/fetch-log.jsonl` records `{page, url, fetched_at,
  status}` per fetch (the contract's timestamp rule).
- **Tripwires (Criterion-sync philosophy):** bounded retries; after 3 consecutive failures
  (network, non-200, or a page that yields no cards) stop and keep progress — everything
  archived so far stays; the next `crawl` resumes at the first missing page. Failures never
  touch the DB.

## Parse + stage (part of `match`, archive-only)

Parsing reads **only the archive** — a parser fix means re-running `match`, never
re-fetching. Primary parse target: the `__NUXT_DATA__` JSON island (per the spike); the raw
HTML archive is the insurance if that structure shifts. Fields per card: title, year
(`premiereYear`), metascore, slug, rank (position in the walk).

Staged into a new table (also the Phase 5 Mode B foundation):

```sql
CREATE TABLE metacritic (
    slug TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    year INTEGER,
    score INTEGER,
    rank INTEGER NOT NULL,
    page INTEGER NOT NULL,
    fetched_at TEXT NOT NULL
);
```

Upsert by slug (re-parses and wider walks update in place). Contract verification runs
here and reports warnings: ~24 cards per page, scores monotonically non-increasing across
the walk, no duplicate slugs.

## Match (`domain/matching.py` + `application/metacritic.py`)

Pure normalization/matching rules move from the spike into `domain/matching.py`
(spike script stays untouched in `scripts/discovery/`):

- `clean_title` — strip trailing `(re-release)` / `(NNNN)` annotations.
- `norm` — casefold, `$`→`s`, drop non-alphanumerics.
- Match rule: archive title ↔ film where `norm(clean_title(mc.title)) == norm(film.title)`
  and `film.year ≤ mc.year + 2` (year-less films match on title alone). Tie-break among
  multiple candidate films: exact year match first, then nearest year. OMDb's Metascore,
  where present, is a logged cross-check — not a match criterion.

Match direction is archive → films (at 10 pages most films simply aren't in the archive
yet; that is coverage, not an anomaly). Outcomes:

- **Hit:** `Repository.set_external_id(film_id, 'metacritic', slug, today)`. Score is NOT
  copied onto the film — display joins through `external_ids` to the `metacritic` table,
  so a re-crawl updates scores with no re-match.
- **Anomaly → review queue** (durable table, Phase 8's UI reads it): one archive title
  matching ≥ 2 films; one film matching ≥ 2 slugs; `sqlite3.IntegrityError` (slug already
  claimed by a different film — caught and logged, like `record_catalog`); a film whose
  `omdb.metacritic` ≥ the archive's current score floor but that matched nothing (a matcher
  miss, not a coverage gap).
- **Not in archive:** counted in the coverage report only — no review row, nothing blocked,
  nothing deleted.

```sql
CREATE TABLE match_review (
    id INTEGER PRIMARY KEY,
    authority TEXT NOT NULL,
    film_id INTEGER REFERENCES films(id),
    value TEXT,
    reason TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL,
    resolved INTEGER NOT NULL DEFAULT 0
);
```

`match` recomputes the queue each run: unresolved `authority='metacritic'` rows are
replaced (derived state, not collected data — the immutability rule binds films, not this
queue); `resolved=1` rows persist for Phase 8.

**Coverage report** (printed by `match`, the phase's done-when):

```
archive: 10 pages · 240 titles · score floor 94
matched: 57/3051 films (1.9%)
expected-but-missed: 3 (omdb score ≥ floor, no match) → review queue
review queue: 5 open
below floor / unscored: 2994
```

## Migration `migrations/004_metacritic.sql`

Creates `metacritic` + `match_review`, inserts `schema_version` 4. Additive only — no
rebuilds. Wrapped in `BEGIN`/`COMMIT` per the standing rule; `init_db`'s automatic
pre-migration backup applies.

## Display: score becomes first-class

`Repository.list_views` (the `FilmView` query) joins
`external_ids (authority='metacritic') → metacritic` and selects
`COALESCE(mc.score, o.metacritic) AS metacritic`, plus a new `metacritic_url` (from the
slug: `https://www.metacritic.com/movie/<slug>/`, NULL when unmatched). Filters, sorts,
canned chips, and export all read the same `metacritic` field as today — no threshold or
JS logic changes. The drawer gains an "Open on Metacritic" link when `metacritic_url` is
present (the slug's visible payoff; `app.js` + `index.html`, same pattern as the Criterion
link).

## Unchanged on purpose

`application/sync.py`, `criterion.py`, `omdb.py` (still fetches/stores its Metascore —
fallback + cross-check), `domain/filters.py` thresholds, legacy import, launchd job.

## Testing (mirrors the layers)

- **Unit, domain:** `clean_title` / `norm` / match-rule cases from the spike's verified
  set — annotations (`Dekalog (1988)`), punctuation (`Forbidden Lie$`), US re-release year
  drift (Tokyo Story 1972-vs-1953), tie-breaks, year-less films.
- **Unit, infrastructure:** parser against a fixture `page-NNNN.html` (trimmed real
  `__NUXT_DATA__` structure); migration 004 on a populated v3 DB and fresh (001→004);
  staging upsert; review-queue replace-unresolved/keep-resolved semantics.
- **BDD (`tests/features/metacritic.feature` + step_defs, HTTP mocked with `responses`):**
  crawl archives N pages and skips existing ones; crawl resumes after a mid-walk failure
  keeping progress; 3-failure tripwire stops without touching the DB; match links films,
  fills the review queue on ambiguity/IntegrityError, reports coverage; re-running match is
  idempotent.
- **Web:** API test asserts `metacritic` prefers scraped over OMDb and `metacritic_url`
  appears; existing Playwright suite stays green (drawer link addition covered by the
  seeded live-server test).
- **Gate:** `uv run pytest`, `uv run ruff check .`, `uv run mypy` all green.

## Documentation (when it lands)

- **CLAUDE.md:** add the `metacritic crawl` / `match` commands; note the score-authority
  rule (scraped first, OMDb fallback), the archive-as-checkpoint location, and that the
  review queue is the logging surface for unmatched anomalies.
- **docs/multiple-movie-services.md:** mark Phase 2 done; note the incremental-dial
  decision (10 → 110 → 300 pages, user-driven).

## Out of scope (later phases)

Mode B top-N ingestion (staged unmatched Metacritic titles just sit in `metacritic` until
Phase 5 turns them into films), review-queue UI and resolution verbs (Phase 8), ratings
sync, TMDB availability (Phase 3), auto re-match in the nightly sync.
