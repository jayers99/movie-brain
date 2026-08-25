# Data audit: consistency checks, Suspect chip, human verdicts

**Date:** 2026-08-24 · **Status:** approved
**Context:** two verified wrong OMDb records surfaced on 2026-08-24 — *The Deer Hunter*
(#3403, OMDb returned a junk "The Deer Hunter (1978)" stub, tt24735970) and *Schindler's
List* (#3164, OMDb returned *The Making of 'Schindler's List'*, tt2709758). Both were stored
as `found=1` and never revisited. ~3,800 of 4,268 TMDB-linked films still carry a
title+year-matched OMDb payload; the true wrong-hit rate is unknown. The user's direction:
**no more blind sweeps** — measure first, surface suspects to a human, classify verdicts,
then derive fixes and a hierarchy of truth from the evidence.

## Goal

A read-only audit that scores every film against cross-source consistency checks, a
**Suspect** chip in the dashboard that surfaces the ranked worklist, and a drawer verdict
control so the human decides what is actually wrong. Verdicts are append-only data that
later phases mine for patterns.

**Out of scope (this phase):** any automatic fix (refetch, merge, year edit), weight tuning,
the hierarchy-of-truth document (written *after* the first verdict pass), running the audit
inside sync.

## Decisions (user-approved 2026-08-24)

| Decision | Choice |
|---|---|
| Where checks run | `movie-brain audit` verb, run by hand (user syncs manually; no launchd) |
| TMDB in the audit | **Included** — one read-only call per linked film, cached in `tmdb_facts`, never repeated |
| Where the human reviews | Dashboard: Suspect chip + drawer verdict buttons (revisit pattern) |
| Verdict vocabulary | `fine` · `omdb-wrong` · `tmdb-wrong` · `film-wrong` · `twin` |
| `fine` semantics | Suppresses the chip only for the reason set present when marked; a new reason re-flags |
| Verdict storage | Append-only (like `match_review`); latest row drives display; history is analysis data |
| Verdict side effects | **None.** A verdict changes nothing else in this phase |

## 1. Schema — `migrations/010_audit.sql`

```sql
CREATE TABLE audit_flags (
    film_id INTEGER NOT NULL REFERENCES films(id),
    reason  TEXT    NOT NULL,          -- code, see §2
    detail  TEXT    NOT NULL,          -- human-readable evidence
    score   INTEGER NOT NULL,          -- the reason's weight
    run_on  TEXT    NOT NULL,
    PRIMARY KEY (film_id, reason)
);
CREATE TABLE audit_verdict (
    id        INTEGER PRIMARY KEY,
    film_id   INTEGER NOT NULL REFERENCES films(id),
    verdict   TEXT    NOT NULL,        -- fine|omdb-wrong|tmdb-wrong|film-wrong|twin
    reasons   TEXT    NOT NULL,        -- sorted reason codes at marking time, comma-joined
    note      TEXT,
    marked_on TEXT    NOT NULL
);
CREATE TABLE tmdb_facts (
    film_id        INTEGER PRIMARY KEY REFERENCES films(id),
    tmdb_id        INTEGER NOT NULL,
    imdb_id        TEXT,
    title          TEXT    NOT NULL,
    original_title TEXT    NOT NULL,
    alt_titles     TEXT    NOT NULL,   -- JSON array
    release_year   INTEGER,
    runtime_min    INTEGER,
    fetched_on     TEXT    NOT NULL
);
```

- `audit_flags` is replaced wholesale on every run (DELETE then INSERT inside one
  transaction) — it is a derived report, not a ledger.
- `audit_verdict` is never updated or deleted. Never touched by sync or repair verbs.
- `tmdb_facts` is filled only for films with a `tmdb` external id and no row yet
  (`fetched_on` is informational; a `--refresh-tmdb` flag is deferred). If the film's
  `tmdb` external id later changes (repair links / review resolve), the stale row is
  detected by `tmdb_facts.tmdb_id != external_ids.value` and re-fetched.
- Migration inserts its own `schema_version` row; wrapped in BEGIN/COMMIT.

## 2. Checks — `domain/audit.py` (pure)

Input: one `AuditSubject` dataclass per film, assembled by the repository read model:
film title/year/director, Criterion director, Metacritic score, OMDb payload fields
(`Title`, `Year`, `Director`, `Runtime`, `imdbID`, `Type`, `imdbRating`, `Metascore`),
`tmdb_facts` row, and the set of other film ids sharing its OMDb
`imdbID`. Output: `list[AuditFlag(code, detail, score)]`.

| code | fires when | wt |
|---|---|---|
| `mc-score` | OMDb `Metascore` and scraped Metacritic score both present and differ | 3 |
| `imdb-id` | OMDb `imdbID` and `tmdb_facts.imdb_id` both present and differ | 3 |
| `tmdb-title` | normalized film title matches none of TMDB title / original_title / alt_titles | 3 |
| `omdb-title` | normalized film title ≠ normalized OMDb `Title` | 2 |
| `director` | Criterion director and OMDb `Director` both present, no surname in common | 2 |
| `runtime` | OMDb `Runtime` vs `tmdb_facts.runtime_min` differ by > 10 min (Apple runtime is not stored in the DB — deferred) | 2 |
| `shared-imdb` | ≥ 1 other non-disposed film holds the same OMDb `imdbID` | 2 |
| `year` | OMDb `Year` vs `films.year` gap > 1 | 1 |
| `stub` | OMDb `Type` ≠ `movie`, or `Director` and `imdbRating` both `N/A` | 1 |

- Score = sum of weights. A film is a **suspect** when score ≥ 1 and not suppressed (§4).
- Checks only fire on evidence that is present on both sides; a missing side never fires
  (absence is not inconsistency — that is what the `stub` check is for).
- Normalization (`normalize_title`): NFKD + strip diacritics, casefold, strip punctuation,
  collapse whitespace, drop one leading article (`the a an le la les il lo der die das el
  los las`), and strip trailing annotations via the existing `clean_title` /
  `split_annotations`. `omdb-title` is an **equality** check, not containment —
  "Schindler's List" is a substring of "The Making of 'Schindler's List'", and that case
  must fire.
- Weights are a first guess. They are named constants in `domain/audit.py` so the verdict
  set can recalibrate them in a later phase.

## 3. Verb — `movie-brain audit [--no-tmdb]` (`application/audit.py`)

1. **TMDB facts fill** (skipped with `--no-tmdb`): for each linked film missing a fresh
   `tmdb_facts` row, one call `GET /movie/{id}?append_to_response=alternative_titles,external_ids`
   (`TmdbClient.movie_facts(tmdb_id) -> TmdbFacts`). Polite delay reuses the sync default.
   Own tripwire: any per-film failure is logged and skipped; `AuthError` stops the fill but
   the offline checks still run; the verb's exit code is 0 unless the checks themselves fail.
2. **Checks**: `repo.audit_subjects()` → `run_checks(subject)` per film → flags.
3. **Write**: replace `audit_flags` in one transaction.
4. **Report**: tally per reason code, count of suspects, top-20 by score with reasons.

`movie-brain audit verdicts [--verdict V]` prints the verdict history (film, verdict,
reasons, note, marked_on) — the pattern-analysis export. `export csv` is untouched.

## 4. Dashboard

- `FilmView.audit: AuditView | None` — `{score, reasons: [{code, detail}]}` joined in
  `_VIEW_SQL` from `audit_flags`, `None` when the film has no flags.
- **Suppression** is resolved in the read model: the film's latest `audit_verdict` row with
  `verdict='fine'` suppresses when its `reasons` equals the current sorted reason set.
  Any other verdict does not suppress (the film stays a suspect until the data is fixed in
  a later phase and the flags stop firing). `FilmView.verdict` carries the latest verdict
  (or `None`) so the drawer can show it.
- **Suspect chip**: `suspect` predicate in `domain/filters.py` `_PREDICATES` (`v.audit is
  not None`), mirrored in `CHIP_PREDICATES` and the `index.html` chip button (lockstep
  rule). When the chip is active the default sort is score desc.
- **Drawer**: an "Audit" block listing each reason's `detail`, the latest verdict if any,
  five verdict buttons, and a note field. `POST /api/films/<id>/verdict` with
  `{verdict, note}` → `repo.add_verdict(film_id, verdict, reasons=current codes, note,
  today)`; returns the new latest verdict. This endpoint is the **only writer** of
  `audit_verdict`. Invalid verdict → 400.

## 5. Tests

- `tests/unit/test_audit.py`: every check red/green on `AuditSubject` fixtures, with the
  three real cases named — *Deer Hunter* (`stub` + `imdb-id`), *Schindler's List*
  (`omdb-title` + `imdb-id`), *Army of Shadows* pre-fix (`year` only, no stub). Normalizer
  cases: diacritics, articles in three languages, `[re-release]` annotation.
- `tests/unit/test_tmdb.py`: `movie_facts` parses title/original/alts/imdb_id/runtime/year.
- `tests/features/audit.feature` + `tests/step_defs/test_audit.py`: verb writes flags and
  replaces them on re-run; `--no-tmdb` makes no TMDB calls; TMDB 500 on one film skips it
  and still audits; `fine` suppresses; a new reason on the next run re-flags; `verdicts`
  lists history in order.
- `tests/web/test_api.py`: Suspect chip predicate parity; verdict endpoint appends, rejects
  unknown verdicts, and returns the latest.
- `tests/web/test_dashboard.py`: one Playwright scenario — open a suspect, click
  `omdb-wrong`, the drawer shows it.
- Existing gates: `uv run pytest`, `ruff`, `mypy`, and `scripts/matching_benchmark.py
  --assert-dominance` must stay green (this phase never touches `domain/matching.py`).

## 6. What comes after (not this phase)

1. First human pass over the Suspect worklist.
2. Analyse `audit verdicts` by reason code → precision per check → recalibrate weights.
3. Write `docs/hierarchy-of-truth.md` from the evidence (expected shape: TMDB id, human-
   verified → IMDb id derived → OMDb by id only; OMDb title search never authoritative).
4. Only then: targeted fix verbs driven by verdict, each idempotent, each with its own spec.
