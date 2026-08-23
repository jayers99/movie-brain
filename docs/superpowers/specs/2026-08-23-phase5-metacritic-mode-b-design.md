# Phase 5: Metacritic Mode B — the top-N discovery dial

**Date:** 2026-08-23 · **Status:** approved
**Context:** `docs/multiple-movie-services.md` (Implementation phases, dated decisions),
`docs/superpowers/handoffs/2026-08-23-phase5-handoff.md`.

## Goal

Promote the top-N staged Metacritic titles into real films (generated guids, dedup-guarded),
integrated into sync as an offline archive step, with the dashboard gaining minimum
source-awareness: Mode-B films visible behind a scope control while the default view keeps
exact Criterion parity. Done when top-100 lives in the app and N=1,000 is a config change
(`metacritic dial 1000` + one bigger crawl), not a project.

**Out of scope:** new crawling (the Phase 2 archive's ~10 pages ≈ 240 titles already cover
N=100), match-review tooling (Phase 8), full-service import (Phase 6), subscription advisor
(Phase 7).

## Decisions (user-approved 2026-08-23)

| Decision | Choice |
|---|---|
| Dashboard surfacing | **Scope toggle** — source-agnostic view; JS scope defaults to `criterion` (parity), `all` reveals Mode-B; composes with existing chips |
| New-arrivals flood | **Quiet first check** — a film's first-ever TMDB provider check writes listings without transition events (for all films, not just Mode-B) |
| OMDb backfill | **In scope** — films without a Criterion listing enter the OMDb loop after Criterion-current films |
| Where N lives / promotion runs | **meta key `mc_top_n`** (code default 100), set via `movie-brain metacritic dial [N]`; promotion runs inside nightly sync as an offline archive step |
| Top-N boundary semantics | `rank <= N` on the staged `metacritic.rank` (crawl-walk order; deterministic, score-monotonic) |

## 1. Promotion (application layer)

New function in `application/metacritic.py` (e.g. `promote_top_n`), called with repo,
config_dir, today, N. Offline and idempotent:

1. Run the existing `match_archive` first — existing films claim their slugs. This is the
   dedup guard: promotion only ever sees slugs no existing film owns.
2. Candidates: staged `metacritic` rows with `rank <= N`, deduped by slug (last wins,
   matching Mode A), excluding slugs already present in `external_ids` authority
   `metacritic` and slugs queued as anomalies by the match run just executed.
3. For each candidate: create a film — generated guid, `clean_title(t.title)`, `t.year`,
   director NULL, `key = film_key(title, year)` — via a new `Repository.create_film` using
   `INSERT ... ON CONFLICT(key) DO NOTHING`, returning the new id or None on conflict.
   - **Key conflict** (key exists but matcher didn't link it): no insert, no update of the
     existing film; append `match_review` entry, reason `key-conflict`, value = slug.
   - On successful insert: `set_external_id(film_id, 'metacritic', slug)`; an
     IntegrityError (slug claimed mid-run) becomes a review entry, same posture as Mode A.
4. Report: promoted / already-linked / skipped-anomalous counts, archive shortfall
   (titles available vs N).

Collectors never delete; nothing here updates existing films. Review entries from promotion
are appended alongside the match run's entries (still via `replace_unresolved_reviews`
semantics — unresolved rows are recomputed per run, resolved rows never touched).

Promoted films flow downstream with no further wiring: `films_needing_tmdb_match` and
`films_for_matching` already drive from all films.

## 2. Sync integration

New step in `application/sync.py` immediately after the Criterion catalog step (so OMDb and
TMDB cover the new films the same night):

- Read N from meta `mc_top_n`; absent → default 100 (constant in code).
- Run match + promote from the archive. **No scraping** — the no-scraping-in-sync rule
  holds; the archive is the only input. Side effect: Mode-A matching now refreshes nightly.
- Tripwire: the whole step in one try; failures log and never affect exit code or other
  steps (same posture as TMDB).
- If archive titles < N: log `archive has X titles < top-N M — run: movie-brain metacritic
  crawl --pages P` (P = ceil(M / 24)).
- Skipped on `--ratings-only`. `sync()` gains `config_dir: Path | None = None`; None skips
  the step (existing callers/tests unchanged).
- `SyncResult` gains a promoted-count field; CLI summary line reports it.

CLI: `movie-brain metacritic dial [N]` — no argument prints current N plus archive coverage
(titles archived, pages); with N writes meta. No migration required (meta needs no schema).

## 3. Quiet first provider check

`films_for_provider_refresh` and `films_for_watchlist_refresh` additionally return whether
this is the film's first-ever provider check (`providers_checked_at IS NULL`). In
`application/availability.py`, first-check films write listings via plain `record_listing`
(no transition events) — you can't observe a *transition* without a prior observation.
Subsequent checks use `record_listing_with_transition` as today. The Criterion walk's
transition behavior is untouched. This also removes the existing smaller flood when a new
Criterion film's providers are first fetched.

## 4. OMDb widening

New repository query (e.g. `films_needing_lookup_discovery(today)`): films with **no
Criterion listing at all** (the durable Mode-B trait) needing OMDb, same
missing/needs-refresh/miss-retry clause as `films_needing_lookup`. The sync OMDb loop
iterates Criterion-current films first, then discovery films, under the same quota/failure
tripwires. `Film.url` for these is the film's Metacritic URL if available, else `""` (the
OMDb client only uses title/year).

## 5. View + dashboard

**`_VIEW_SQL`** drives from `films` with `LEFT JOIN listings l ON l.film_id = f.id AND
l.source = ?`. `list_views` inclusion becomes: current-criterion OR rated OR
`l.film_id IS NULL` — exact parity for Criterion films (unrated departed stay hidden),
Mode-B films added. `departed` is false when there is no listing. `get_view` keeps
`WHERE f.id = ?` (LEFT JOIN makes Mode-B films resolvable).

**`FilmView`:** `url` becomes `str | None`; new field `criterion: bool`
(= has any criterion listing row). `first_seen`/`leaving_date` stay NULL for Mode-B films
(the `recent` chip simply won't match them — accepted).

**Web/JS:** drawer renders the Criterion link only when `url` is present (Metacritic link
already exists). New **scope** control near the chips: URL param `scope`, default
`criterion`, option `all`; checked in `rowMatches` before chips — same default-encoding
pattern as the English-language filter. `/api/config` unchanged except any constant JS
needs. Keep `CHIP_PREDICATES`/chip buttons untouched.

**`summary()`:** gains a `discovery` count (views with `criterion == False`); `films` and
the other counts stay Criterion-scoped so `movie-brain status` stays comparable.

**Known quirk (documented, accepted):** until OMDb backfills language, the default English
language filter hides discovery films even in `scope=all`; `lang=any` shows them
immediately, and N=100 drains in one nightly sync.

## Error handling summary

- Promotion failures: logged, sync exit code untouched (step-level tripwire).
- Key conflicts and slug conflicts: `match_review` entries, never deletes/overwrites.
- Archive shorter than N: logged instruction, promotion proceeds with what exists.
- Dashboard with zero Mode-B films: scope control still renders; `all` == today's view.

## Testing

Mirrors the layers:

- **BDD (features + step_defs):** promotion happy path (film created with guid + external
  id), dedup guard (matched slug not re-promoted), key-conflict → review entry, top-N
  boundary by rank, dial default + meta override, archive-shortfall logging, sync-step
  tripwire (promotion failure leaves exit 0), OMDb widening (discovery film looked up after
  criterion films), quiet first provider check (no transitions on first check, transitions
  on later insert).
- **Unit:** `create_film` conflict semantics; view SQL inclusion/parity (unrated departed
  hidden, Mode-B included, departed false without listing).
- **Web:** `/api/films` includes Mode-B films with `criterion: false` and null `url`;
  Playwright: scope toggle hides/reveals a seeded Mode-B film, default scope keeps parity.

## Landing checklist

Suite + ruff + mypy green; CLAUDE.md updated (sync flow, rules, commands); roadmap marks
Phase 5 done; Phase 6 handoff written; dashboard, 3 AM sync, and Phase 4 alerts verified
working.
