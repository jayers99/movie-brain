# Handoff: Phase 2 done → Phase 3 (TMDB availability adapter)

**Written:** 2026-08-23, end of the Phase 2 session. Read this alongside
`docs/multiple-movie-services.md` (Implementation phases + dated decisions) and
`docs/vision.md` before any Phase 3 work.

## Status

- **Phase 2 (Metacritic Mode A) is fully landed**: merged to `main` (`699f2ed`), full gate
  green (177 tests incl. Playwright, ruff, mypy strict). Spec:
  `docs/superpowers/specs/2026-08-23-phase2-metacritic-mode-a-design.md` (implemented).
  Plan: `docs/superpowers/plans/2026-08-23-phase2-metacritic-mode-a.md`.
- **Live DB is at schema v4** (auto-migrated with pre-backup) and Phase 2 has run for real:
  the archive holds **200 pages ≈ 4,783 staged titles** (score floor 71), **423 films
  linked** to Metacritic slugs (~14% of 3,051 — near the ceiling for a floor-71 walk),
  **89 open `match_review` rows** (mostly expected-miss; a human-review surface for later,
  not a blocker). Extending the archive is just `metacritic crawl --pages N` + `match`.
- `main` may be ahead of `origin/main` — check and push before branching if desired.

## What Phase 3 builds on (new since Phase 2)

- **`domain/matching.py`** — the spike's 98% rules as pure functions: `clean_title`,
  `norm_title`, `match_film(mc_title, mc_year, candidates) -> MatchResult` (winner/tied).
  Built for Metacritic→films, but the normalization + year-tolerance rules are exactly what
  TMDB title-search matching needs too.
- **`external_ids`** — Phase 3 writes `authority='tmdb'` (and can also record `imdb`) rows;
  `UNIQUE(authority, value)` is the dedup guard; `IntegrityError` is caught/logged, never
  crashes (see `application/metacritic.py` for the pattern).
- **`match_review`** — the durable anomaly queue with `resolved` flag; reuse it for TMDB
  match anomalies (`replace_unresolved_reviews` / `open_reviews` are authority-scoped).
- **`service_provider`** — 8 TMDB provider ids already seeded and grouped per service
  (Criterion 258, Apple TV+ 350, Apple TV Store 2, HBO Max 1899, Peacock 386/387,
  Prime 9, MUBI 11; Amazon-channel ids deliberately excluded — dated decision).
- **`listings(film_id, source, url, first_seen, last_seen, leaving_date)`** — the
  availability join; `source` is an FK into `movie_service`. "Current" = max `last_seen`
  per source. Phase 3's spec decides whether TMDB availability lands as `listings` rows
  per service or a separate table — note `url` is NOT NULL and TMDB gives no per-service
  deep link, and the Criterion cheap-check computes MAX(last_seen) per source.
- **Cheap TMDB id shortcut:** ~2,500 OMDb payloads on disk carry `imdbID` —
  `/find/{imdb_id}` resolves those to TMDB ids with no title matching at all. Title-search
  matching (via `domain/matching.py`) is only needed for the remainder.

## Phase 3 scope (from the roadmap)

TMDB availability adapter: `infrastructure/tmdb.py`; a `tmdb` cache table on the `omdb`
pattern (raw payload + extracted fields, re-derivable); watch-providers for my services;
a sync step with its own tripwires (one source failing must not break the others); drawer
shows "Also streaming on: …". **Done when:** cross-service availability is visible for
Criterion films.

## Dated decisions that bind Phase 3 (do not relitigate)

- **Availability-kind rule (2026-08-23):** `kind='svod'` services count TMDB **`flatrate`**
  entries only; `rent`/`buy` arrays are read only for `kind='store'` services (Apple TV
  Store, provider 2). Purchasable-from-Amazon is never availability.
- **Amazon channel ids excluded (2026-08-23):** accepted consequence — BFI Player Classics
  availability is knowingly invisible on TMDB.
- **Availability is a snapshot, not a fact** (sources drift; refreshed by sync).
- **Collectors never delete; films are immutable; GUID identity** — all standing rules.

## Assets

- **TMDB credentials (verified 2026-08-24):** `~/.config/movie-brain/tmdb-read-token.txt`
  (v4 bearer — use this) and `tmdb-api-key.txt` (v3). Free tier, ~40 req/s rate limit; a
  full 3,051-film pass is minutes, not days — but be polite and tripwired anyway.
- `scripts/discovery/providers_spike.py` — the watch-providers probe (per-film
  `/movie/{id}/watch/providers`, US region, flatrate/rent/buy arrays).
- `scripts/discovery/match_spike2.py` — original TMDB-search matcher spike (its rules now
  live in `domain/matching.py`; the TMDB API call shapes are still a useful reference).
- OMDb quota lesson: unlike OMDb there is no daily-quota backlog, but keep the
  stop-and-keep-progress tripwire philosophy (5 consecutive failures pattern in `sync.py`).

## Parked / deferred (none blocking)

- 89 open `match_review` rows await the Phase 8 review UI; outcome rules stand (match /
  alias / tombstone, never silent deletion).
- Playwright doesn't assert the drawer's "Open on Metacritic" anchor (deferred: needs web
  seed changes). Phase 3's drawer work ("Also streaming on:") is a natural moment to add
  drawer-link coverage for both.
- `parse_page`'s `json.loads` is unguarded against a non-JSON `__NUXT_DATA__` island;
  same-slug metadata drift keeps the last occurrence (warning-only). Metacritic-side nits,
  not Phase 3 concerns.

## Process (per the standing workflow)

One phase per fresh session. Superpowers flow: brainstorm → spec → written plan →
subagent-driven TDD execution, in a git worktree; dated decisions are settled — don't
relitigate. Specs/plans under `docs/superpowers/`.
