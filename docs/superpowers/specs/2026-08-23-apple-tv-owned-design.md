# Apple TV owned films: import, designation, and display

**Date:** 2026-08-23 · **Status:** approved
**Context:** the iTunes-ownership parallel track from `docs/multiple-movie-services.md`
(working sketch + export spike), prioritized by the user ahead of Phase 7. Probed live
2026-08-23: AppleScript against the TV app sees **870 movie tracks of class `shared track`
(cloud purchases)** with usable `name` and `year` fields; titles carry edition annotations
("(Unrated)", "(Director's Cut)", …).

## Goal

Every movie the user owns on iTunes/Apple TV lives in the database as a real film and is
visibly marked as owned — in the table, the drawer (with an Apple TV link), and an Owned
chip. Import is one re-runnable CLI command driven by AppleScript.

**Out of scope:** the "not owned" exclusion chip (user chose Owned chip only), the Apple
privacy-portal export (later completeness backstop for the ~130+ purchases AppleScript may
not see — Family Sharing, cloud-visibility settings), price tracking, and any unmark/merge
tooling (Phase 8).

## Decisions (user-approved 2026-08-23)

| Decision | Choice |
|---|---|
| Acquisition | AppleScript export from the TV app, run by the CLI itself; raw output archived first |
| Scale | 870 visible now (user owns 1,000+); privacy export deferred as backstop |
| Unmatched owned titles | **Created as real films** (guid) — the user wants owned movies in the database |
| Ownership storage | Dedicated `owned` table mirroring `watchlist` (possession = my-response-style data; `listings` currency/transitions untouched) |
| Filtering | Owned chip only (both `_PREDICATES` and `CHIP_PREDICATES`, lockstep rule) |
| Manual marking | None — import is the only writer this phase |

## 1. Acquisition — `infrastructure/appletv.py`

- One osascript invocation (subprocess) batch-reads `name of every track …` and
  `year of every track of library playlist 1 whose media kind is movie` from application
  "TV", zips them, and emits one `title<TAB>year` line per movie.
- The raw osascript output is archived to `<config_dir>/appletv/owned-<YYYY-MM-DD>.txt`
  **before** parsing (re-derivability rule); the adapter's parse reads that text, so a
  future parser fix replays the archive without re-running AppleScript.
- Adapter contract: `fetch_owned() -> list[OwnedTitle]` where `OwnedTitle(title: str,
  year: int | None)`; a missing/0 year becomes None. Failure modes (TV app not present,
  automation consent denied, osascript non-zero) raise a typed error the CLI reports as
  exit 1 with a human hint; the DB is untouched on any failure before matching begins.
- macOS-only by nature; no HTTP, no scraping, never runs in sync — import is a deliberate
  CLI verb only.

## 2. Matching and creation — `application/owned.py`

Per title, in order:

1. **Clean:** new `clean_apple_title` in `domain/matching.py` strips ONE trailing
   parenthetical edition annotation from a case-insensitive known list — Unrated,
   Director's Cut, Extended (Edition/Cut), Theatrical (Version/Cut), Special Edition,
   Uncut, Remastered, 4K, Subtitled, Dubbed, English Subtitles — extendable constant.
   Unknown trailing parentheticals are kept (they may be part of the title).
2. **Match** against all films by `norm_title` candidates: exact year wins; else nearest
   within ±1 year; a tie for best → `match_review` (authority `apple-tv`), skipped.
   A year-less side matches on title alone (unique candidate required, else review).
3. **Miss → create:** `create_film` (generated guid, cleaned title, Apple year, director
   NULL). If `create_film` returns None (exact `film_key` collision), that IS the film —
   mark it owned. Created films have no criterion listing, so the existing discovery
   machinery enriches them automatically (OMDb same night on the paid plan; TMDB match
   next sync; providers at the weekly refresh, quiet-first-check = no arrivals flood).
4. **Mark owned:** upsert into `owned` — never unmark, never delete (a title vanishing
   from the Apple library is invisible to us; possession records are permanent).

Idempotent: re-running re-matches deterministically and re-upserts; review entries are
recomputed per run via `replace_unresolved_reviews('apple-tv', …)`. Known residue: US-lag
year drift beyond ±1 can create a twin of an existing film — accepted, merges are
Phase 8's job. Report: total titles, matched-existing, created, already-owned, review count.

## 3. Data model — migration 007

```sql
CREATE TABLE owned (
    film_id        INTEGER PRIMARY KEY REFERENCES films(id),
    source         TEXT NOT NULL DEFAULT 'apple-tv',
    first_imported TEXT NOT NULL
);
```

Additive only; no changes to `listings`, no transition interactions. `FilmView` gains
`owned: bool = False` (populated via a LEFT JOIN or id-set, matching the watchlist
pattern). No external_ids row this phase — AppleScript exposes no stable store id for
shared tracks; title+year matching is the identity bridge (documented limitation).

## 4. CLI — `movie-brain owned import`

New `owned` sub-app. `import` runs acquisition + matching, prints the report line
(`owned: N · matched: X · created: Y · review: Z`), exit 1 only when acquisition itself
fails. A bare `movie-brain owned` lists nothing extra this phase (sub-app help).

## 5. UI

- **Table:** a small `owned` badge after the title, same visual treatment as the `gone`
  badge (title cell, `badge-owned` class), tooltip "Owned on Apple TV".
- **Drawer:** an "Owned on Apple TV ↗" line linking to
  `https://tv.apple.com/search?term=<urlencoded title>` — always the search link, because
  the stored `apple-tv-store` listing URLs are TMDB watch pages, not Apple pages
  (amended 2026-08-23 during planning).
- **Owned chip:** `owned` predicate added to `domain/filters.py` `_PREDICATES` AND
  `app.js` `CHIP_PREDICATES` AND the `index.html` chip row (lockstep rule).
- **Counts:** `summary()` and the header gain `owned` = total owned across all views
  (ownership spans scopes; it is not criterion-scoped).

## Error handling summary

- Acquisition failure → exit 1, DB untouched, raw archive kept if written.
- Ambiguous matches → `match_review` authority `apple-tv`, never guessed.
- `create_film` key collision → treated as the same film, marked owned.
- Import never deletes, never unmarks, never touches `listings` or transitions.

## Testing

- **Unit:** `clean_apple_title` (each annotation, unknown parenthetical kept, plain title
  untouched); appletv parser (tab lines → OwnedTitle, blank/zero year → None); `owned`
  repository methods; view exposes `owned`.
- **BDD:** import happy path (match + create + mark), idempotent re-run, ambiguous tie →
  review, key-collision → same film owned, acquisition failure → exit 1 DB untouched
  (osascript faked at the adapter seam).
- **Web:** film JSON carries `owned`; Playwright: badge visible, Owned chip filters.

## Landing checklist

Migration 007 applied cleanly (auto-backup fires); suite/ruff/mypy green; CLAUDE.md
(commands, rules, data section) updated; roadmap's ownership sketch marked decided;
handoff note appended for the privacy-export backstop.
