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
  marker-free base. A post-pass (`_dedup_survivor_groups`) then reconciles a survivor that is
  itself a contract row: its NON-twin group (`no-twin`, `conflict` and `csv-mismatch` alike) is
  DROPPED when the twin group naming it will do that very work — same `(work_title, work_year,
  tt)` and a survivor title that still parses with editions, which is the re-key the twin path
  performs; any other group stays listed, because it is a different fold. Two same-year editions
  with no keyed work are each other's fellow-contract twin — a MUTUAL pair whose second merge
  would hit an already-dispositioned film and raise after the first merge committed — so the pair
  is broken deterministically toward the LOWER id: the higher id's group survives and merges into
  the lower, which the twin path re-keys as the work. A twin is exactly one
  same-norm-title/same-work-year candidate agreeing on tmdb id. The fellow-contract fallback (an
  unkeyed candidate that is itself a contract row sharing the same tt) applies ONLY when NO
  candidate holds the tmdb id — once one does, an unkeyed fellow edition beside the real work is
  not a rival reading, and counting it made a one-pass fold report `several agreeing twins`;
  `_edition_blockers`
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
- `movie-brain repair disagreements [--apply] [--yes] [--limit N]` repairs films whose OMDb
  `imdbID` ≠ TMDB `imdb_id`: the worklist is `Repository.key_disagreements()` ∩ eval group
  `D-disagree` (`load_disagreement_contract` keeps EVERY D row keyed by film id — `verified`
  rows are the contract, `proposed`/verified-`NONE` rows render as review, never applied).
  Verdicts: `refetch` (expected tt = TMDB's side → `set_external_id(imdb)` + `mark_omdb_refresh`,
  so the disagreement count drops after the NEXT `sync`, not after `--apply`); `relink`
  (expected tt = OMDb's side → `find_by_imdb` then `set_external_id` + `record_tmdb_match`, or
  `clear_tmdb_link` + `set_external_id` when TMDB has no record); `adopt` (matches neither, but
  `expected_tmdb` is given → `set_external_id` + `record_tmdb_match` + `mark_omdb_refresh`);
  `review` (`proposed`, or verified `NONE`) queues a durable `key-disagreement` `match_review`
  row (authority `tmdb`, `queue_review_once`-idempotent) — `value` is the CSV's proposed tt (or
  `NONE`), `detail` = `review_detail(verdict, query)` where `verdict = resolve(query, candidates)`
  runs the LIVE resolver (fixture hits free, misses hit the live TMDB/OMDb clients, nothing is
  ever saved back to the fixture — `CandidateCache(..., path=None)`); `conflict` (no D row,
  expected id held by another film, `record_tmdb_match` returned anything but
  `matched`/`adopted`, or a verified row with no `expected_tt`) is logged and skipped, never
  written. Two verdicts mark work already done and are computed FIRST: `pending` (keyed to
  `expected_tt` with an OMDb refetch queued) and `review-open` (its `key-disagreement` review is
  already open — or already RESOLVED: a resolution is a standing decision, so the film is not
  work again even though it keeps disagreeing until the next `sync`). Both are listed, never re-applied, and — like `conflict` — are exempt from
  `--limit`, which is a batch size over the ACTIONABLE groups only, so repeated batches advance
  through the worklist instead of re-hitting its head. Holder checks (`external_id_holders`, over EVERY film including disposed) run BEFORE
  any write on every verdict, so a film is either fully repaired or untouched — except a
  post-`record_tmdb_match` failure, which is the one case that logs `[partial]` and raises
  (same loud-stop rule as `repair editions`). `resolve_review` now refreshes a found-but-wrong
  OMDb stub too: after `--pick`/`--tt` keys a film whose stored OMDb `imdbID` ≠ the chosen tt,
  it calls `mark_omdb_refresh`; `--none` on a `key-disagreement` row leaves ids alone.
- Article-insensitive title level (`domain/thumbprint.py`): `article_norm` folds one leading
  English article (`the|a|an`, ASCII, after `norm_title`-style folding — `La Strada` stays
  distinct from `Strada` on purpose) and never returns empty. `title_level(..., article_ok=)`
  scores an article-folded match as level 3 ONLY when no candidate matches article-exactly for
  that query (`article_ok = not any(title_level(q, c) == 3 for c in candidates)`), so an
  article-exact hit always outranks an article-only one; no new reason strings — it's a
  per-candidate signal only. `infrastructure/thumbprint_fetch.py`'s `plausible()` is widened to
  fetch an article-folded exact title hit too. Adopted behind the gate (n=484/0/94.8% unchanged
  with the rule on); live measurement of the 32 open article `no-match` films (rule on vs. off)
  is evaluated but NOT yet adopted — that's a separate owner decision on the numbers.
