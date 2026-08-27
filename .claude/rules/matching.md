---
paths:
  - src/movie_brain/domain/matching.py
  - src/movie_brain/application/metacritic.py
  - src/movie_brain/application/owned.py
  - src/movie_brain/application/availability.py
  - src/movie_brain/application/rematch.py
  - src/movie_brain/application/repair.py
  - src/movie_brain/application/repair_keys.py
  - src/movie_brain/application/review.py
  - scripts/matching_benchmark.py
---

# Matching contract (moved from CLAUDE.md)

- Matching is one evidence-scored core: `domain/matching.py`'s `match_candidates` (three-level
  candidate index, source-aware year policy, director/runtime/popularity evidence, `Arbiter`
  hook) is the only matcher; `match_film` (Metacritic), `match_owned` (Apple), and
  `pick_tmdb_match` (TMDB) are thin per-source policy wrappers over it — never re-implement
  matching logic in a wrapper. `scripts/matching_benchmark.py` (ground truth + Metacritic/Apple
  archive replays, `--assert-dominance` gate) is the regression check before touching matching.
  `movie-brain rematch` is the one-shot, idempotent repair verb: re-matches every TMDB miss and
  fresh-checks TMDB's release year for every non-Criterion matched film, adopting disagreements
  through the same write-back path as sync. A rerelease-annotated commerce year (a `*-re-release`
  / restoration-slug year) is NOT year evidence: when the winning candidate sits exactly at that
  annotated year AND any other surviving candidate carries a year gap, the matcher refuses and
  queues a `rerelease-ambiguous` review rather than guess between a re-release of the gapped film
  and a genuinely same-titled film at the claimed year (the Metropolis case; benchmark ground
  truth). The gapped candidate need not be the older one — any surviving gap arms the rule.
  A DATELESS candidate that survives only because every dated same-title rival was
  year-disqualified is a `yearless-among-dated` review, never a match (the Intolerance case: a
  dateless 4-minute short inherited the 1916 feature's link by elimination); a lone dateless
  candidate with no disqualified rivals still matches (the yearless-Criterion-page case).
  `TmdbClient.search(title, year)` retries with `primary_release_year` when nothing on the
  popularity-ranked title page lands within ±1 of a TRUSTED year (one extra call, only then) —
  callers pass the year only for non-commerce films, since a commerce year may be a re-release.
