---
paths:
  - src/movie_brain/domain/thumbprint.py
  - src/movie_brain/infrastructure/thumbprint_fetch.py
  - src/movie_brain/application/thumbprint.py
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
- `review_detail(verdict)` is the ONLY `match_review.detail` format for resolver rows.
- Claims (`claim` table, migration 011) are a pure copy of owned/criterion/metacritic evidence
  in T1: `thumbprint backfill --apply` is the only writer and is idempotent; `merge_film`
  re-points them. `films.title_norm` is derived from `title_norm()` — never hand-edited.
