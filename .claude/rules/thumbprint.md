---
paths:
  - src/movie_brain/domain/thumbprint.py
  - src/movie_brain/infrastructure/thumbprint_fetch.py
  - src/movie_brain/application/thumbprint.py
  - src/movie_brain/application/repair.py
  - src/movie_brain/application/eval_log.py
  - scripts/thumbprint_benchmark.py
  - scripts/eval/**
---

# Thumbprint contract (spec `docs/superpowers/specs/2026-08-25-thumbprint-resolver-design.md`)

- The resolver is DARK: `domain/thumbprint.resolve()` is benchmarked and callable, but no
  ingester (Criterion walk, Mode-B promotion, `owned import`) uses it until the ingester switch
  (memo step 5). Don't wire it into sync as a side effect of other work.
- Gate before change: `uv run python scripts/thumbprint_benchmark.py --assert` must exit 0
  (0 wrong on `verified`+`believed`, auto ≥ 90%; baseline n=482 / 0 / 94.8%) after ANY edit to
  `domain/thumbprint.py`, `thumbprint_fetch.py`, or the fixture. Never edit
  `scripts/eval/thumbprint_eval_v1.csv` to make the gate green — a wrong expectation is
  corrected with a `note` and `verified_by`; `proposed` rows are reported, never scored.
- Reason strings in `resolve()` are part of the contract (they key the review reasons and the
  A/B/C `review_detail` JSON); don't reword them.
- No OMDb `t=` anywhere in thumbprint code: `OmdbClient.search` (`s=`) and `by_id` (`i=`) only.
- Apple runtime is stored on the claim / query and shown in review rows; it never decides
  (`resolve()` has no runtime parameter — owner decision Q3).
- Fixture key scheme (`ts:` `tsy:` `td:` `person:` `credits:` `o:{json, no apikey}`) is shared by
  the offline gate and live use; `td:`/`o:{"i":…}` misses are soft in read-only mode (the
  prototype fetched details for top-3 + exact-title hits only), everything else is a hard miss.
  Rebuild with `scripts/thumbprint_benchmark.py --refresh` (needs both keys).
- `review_detail(verdict, query=None)` is the ONLY `match_review.detail` format for resolver
  rows; `query` (`{title, year, source, director, runtime}`) is optional but every
  resolver-written row should pass it — `parse_review_detail(detail)` returns
  `(reason, candidates, query)`, or `None` for legacy non-JSON details.
- Claims (`claim` table, migration 011) are a pure copy of owned/criterion/metacritic evidence
  in T1: `thumbprint backfill --apply` is the only writer and is idempotent; `merge_film`
  re-points them. `films.title_norm` is derived from `title_norm()` — never hand-edited.
- `movie-brain repair editions [--apply] [--yes] [--limit N]` folds `Title (edition)` films
  into their same-year work: the contract is eval group `C-edition` OR `F-human`
  (`load_edition_contract`) — a human-ratified `F-human` row joins on the same terms, its
  `work='…' YYYY` note IS the ratification, so one without that note is not a contract —
  keyed by film id with an expected tt/tmdb and the work's title+year parsed from the row's
  note. Idempotence is title-shaped, not year-shaped: a contract film is skipped when it is
  disposed, or when `films.year == work_year` AND its title no longer parses with editions (it
  already IS the work). A SAME-YEAR edition ("Apocalypse Now (Final Cut)" 1979 beside the work
  at 1979) is therefore listed and folded through the ordinary twin / no-twin paths, with
  `edition_year` NULL — only a year strictly LATER than the work's is an edition year. Both
  outcomes are self-idempotent: a twin loser ends disposed, a no-twin ends retitled to a
  marker-free base. A survivor that is itself a contract row is folded BY the twin group naming
  it and never gets a second group of its own (a twin always sits at the work year, so its own
  group could only be the re-key the twin path already performs). A twin is exactly one
  same-norm-title/same-work-year candidate agreeing on tmdb id (or,
  when neither side has a tmdb id, a fellow contract row sharing the same tt); `_edition_blockers`
  pre-checks tt/tmdb/key holders (over EVERY film, disposed included — the UNIQUE guard is blind to disposed rows too) on
  both the twin-merge and no-twin-keying paths and downgrades to `conflict` rather than write
  into a held identity, as it does for a twin already holding a DIFFERENT imdb id. A film that
  carries a Criterion listing is never re-keyed: `record_catalog` upserts
  `ON CONFLICT(films.key)`, so the next walk would mint a duplicate under the old key — that
  group is a `conflict` deferred to the ingester switch. `edition_year` is the film's old
  `films.year` only when that year is strictly LATER than the work's — NULL at or before it (an
  edition can't be older than the work it's an edition of, and the work's OWN year is not an
  edition year). `repair_editions` never touches
  `omdb`/`owned`/`listings` and never appends an eval row itself — a survivor-keying refusal
  after its merge already committed logs `[partial]` and raises (CLI exits 1) rather than report
  a half-done fold as a success.
- `external_ids` policy (migration 012, PK `(film_id, authority, value)`): `KEY_AUTHORITIES =
  {tmdb, imdb}` are single-per-film — `set_external_id` (and `key_work`) replaces the value on
  the film's existing row for a key authority, an UPDATE-then-INSERT that KEEPS the original
  `first_seen` — while every other authority is a repeatable claim authority (`INSERT OR
  IGNORE`, never an UPDATE: `record_catalog` adds a changed catalog URL alongside the old one
  rather than collapsing every row the film holds for that source); `UNIQUE(authority, value)`
  still guards cross-film collisions on both kinds. `merge_film` moves a loser's claim-authority ids onto the
  survivor and moves a key-authority id too UNLESS the survivor already holds that authority, in
  which case the loser's is dropped (today's behaviour, recorded in the disposition note). Read
  models that join `external_ids` for metacritic must pick exactly one slug per film via the
  `_MC_SLUG_SQL` derived table (earliest `first_seen`, then smallest `value`) to avoid fanning
  out a multi-edition film into duplicate rows; `metacritic_claim_rows` is the one exception and
  must keep returning every slug a film holds.
- `review resolve --pick A|B|C | --tt ttNNN | --none` keys a `tmdb`-authority review row (A/B/C
  picks require the row's `review_detail` to carry `candidates`) and, on every path, ratifies an
  eval-CSV row through `application/eval_log.py::ratify` — the ONLY programmatic writer of
  `scripts/eval/thumbprint_eval_v1.csv`. It rewrites a matching `proposed` row (same film_id +
  source) to `verified`/`human`, appending what changed to the note, or else appends a new
  `F-human` row; `--none` writes `expected_tt = NONE`. Run
  `scripts/thumbprint_benchmark.py --refresh` after a ratification batch so the fixture catches
  up — until then, cache-miss rows on the freshly-ratified fixture score as `review`, never a
  gate failure.
