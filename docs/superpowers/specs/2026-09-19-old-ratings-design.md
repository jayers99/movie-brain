# Old ratings — a private record of what I thought in 2004–08

**Date:** 2026-09-19 · **Status:** implemented 2026-09-19 on `feature/STORY-21-old-ratings` (O1–O9 all ruled); rehearsed end to end against a copy of the live DB · **Extends:** the thumbprint resolver and the curated-list pipeline's resolve → gate → create functions (`application/lists.py`), the watchlist pattern for user-response data. **Opens:** a private `old_rating` table with a real foreign key to `films`, an importer that links through the resolver, a second verb that mints the missing 4★/5★ films, a drawer line, a row badge and a Rewatch chip.

## 1. Goal

The owner recovered 203 rows of 1–5★ film ratings he kept on a personal site between 2004-04 and 2008-04 (a partial recovery, about 17% of the original; the CSV, its README and the raw archive captures live in a PRIVATE repo outside this one). The ratings are twenty years old, so they are not ratings any more — they are a **watching signal**: a film he gave 5★ is worth rewatching, a film he gave 1★ is worth avoiding, and every row is an interesting fact in the drawer.

A read-only comparison on 2026-09-19 (title + year ±1, then a fuzzy pass) found about 110 of the 203 already in the catalogue (54%): 33 of 41 five-star rows, 7 of 25 one-star rows. About 26 four- and five-star rows name a film the catalogue does not hold.

## 2. Decisions (owner rulings, 2026-09-19)

| # | Ruling | Evidence / cost if wrong |
|---|--------|--------------------------|
| O1 | **A separate private table, not curated lists and not `my_ratings`.** | This repo is public and `lists/<slug>.tsv` is checked in — two lists would publish the ratings; the "On a list" chip counts membership, not trust, so 1★ films would land on the shortlist. Converting to `my_ratings` would seed ranker tier 1 from a 2005 opinion (`tier_for_score`: 10 → 1) and Phase B would later treat it as a real rating. |
| O2 | **Every row is imported, whatever its rating.** | Same cost as importing two star values; a 2★ is a mild warning, a 4★ a mild nudge, and the drawer line is interesting for all of them. Only 1★ and 5★ drive UI beyond the drawer. |
| O3 | **One row per source line, `film_id` a nullable but ENFORCED foreign key.** `film_id INTEGER REFERENCES films(id)`, with `PRAGMA foreign_keys = ON` already set on every connection (`database.py`). NULL means exactly one thing: "the resolver has not placed this row yet". | O2 and O5 together leave roughly 60 rows (1–3★, film not in the catalogue) with no film to point at. The alternatives are to drop them (loses the avoid signal the day the film arrives via sync or a list) or to create all of them (60 films minted from a 2★ opinion). This is `film_list_entry`'s shape exactly, and a re-run of the import links a row the moment its film exists. Accepted cost: "every old rating has a film" is never literally true — `status` shows the linked/total gap rather than hiding it. |
| O4 | **The foreign key is assigned by the thumbprint resolver, never by a title join.** Each row goes through `resolve_entry` (the list pipeline's fallback-only form ladder) with the row's year passed as the listed year — the path migration 020 opened for title-and-year sources with no director. A `match` is then run through `find_holder` (gates 1, 2, 2b) to find the catalogue film holding that work. | The quick title match used for the stats is not good enough to write a key with: it needed a fuzzy pass for five of the owner's own typos, mis-paired three same-title different-film rows (a 1957 film onto a 1972 one), and cannot see a film held under a foreign title. The resolver's gate is 0 wrong; a refusal costs one hand-link, a wrong link silently hangs a 1★ warning on the wrong film. |
| O5 | **Missing films rated 4★ or 5★ are created; 1–3★ never are.** Creation is its own confirmed verb, not a side effect of the import (the lists' two-verb split), and it re-resolves and re-gates every row: gate 1, 2, 2b via `find_holder`, gate 3 via `corpus_veto`, born keyed via `_key_new_film`. | A film worth rewatching has to exist to be queued; a film to avoid does not need to exist until something else brings it in. Re-gating at creation time is the project's standing rule (refusing costs a hand-link, a twin costs a merge). |
| O6 | **No `match_review` rows.** A row the resolver refuses, a row whose gates block, and a row whose typed year is simply wrong all stay `film_id NULL` and are printed on the scorecard's worklist; `oldratings link` is the hand path. | 203 rows, once. Review rows would need a new authority and a new set of per-authority `review resolve` actions for a worklist of perhaps fifteen. If a second old-ratings source ever appears, revisit. |
| O7 | **Rewatch is a pending request, not a label:** the chip shows old 5★ AND not rated today. Rating the film today serves the request. | The same ruling as the "Rank this" mark (move-tier M13). 6 of the 33 in-catalogue 5★ films are already re-rated, so 27 qualify on day one. |
| O8 | **No "hide old 1★" filter in v1.** The red badge on the row is the avoid signal. | Seven films of 5,134 today. Revisit when the 1★ count in the catalogue makes a filter worth a chip slot. |
| O9 | **Nothing from the source file enters this repo.** Tests use invented rows; the spec and docs name no (title, rating) pair; the importer takes a PATH and archives the raw file under `<config_dir>/oldratings/` before parsing, as `owned import` does. | The repo is public (see `tutor-cartridge`'s scrub rule for the same concern). |

## 3. Data model (migration 026)

```sql
CREATE TABLE old_rating (
    source      TEXT    NOT NULL,              -- 'ntc' — the one source there is; a column, not a framework
    line        INTEGER NOT NULL,              -- 1-based data-row number in the source file: the addressable key
    title       TEXT    NOT NULL,              -- verbatim, typos kept
    year        INTEGER,                       -- as typed; may be wrong
    stars       INTEGER NOT NULL CHECK (stars BETWEEN 1 AND 5),
    rented_on   TEXT,                          -- ISO date as shown on the site
    film_id     INTEGER REFERENCES films(id),  -- NULL = not yet resolved (O3)
    linked_by   TEXT CHECK (linked_by IN ('resolver', 'created', 'hand')),
    linked_on   TEXT,
    PRIMARY KEY (source, line),
    CHECK ((film_id IS NULL) = (linked_by IS NULL))
);
CREATE INDEX old_rating_film ON old_rating(film_id);
```

`film_id` is deliberately NOT unique: the source lists one film twice under two spellings, and both rows must link. The read model takes the row with the latest `rented_on` per film (ties: highest `line`).

`merge_film` re-points `old_rating.film_id` from loser to survivor (a plain UPDATE, as it does for `film_list_entry`; it is not a one-row table so there is no survivor-wins conflict). A tombstoned film keeps its rows; every read model already carries `_NOT_DISPOSED`.

## 4. Behaviour

### 4.1 `movie-brain oldratings import PATH [--apply]`

Dry run by default. Archives the raw file, parses it (`rented,rating,title,year,…` CSV; extra columns ignored), upserts every row on `(source, line)` — title, year, stars, rented_on refreshed, an existing `film_id` NEVER cleared or re-pointed — then resolves each row with `film_id IS NULL` per O4. Outcomes, one per row on the scorecard: `linked` (resolver match + a holder found), `would-create` (match, no holder, stars ≥ 4), `absent` (match, no holder, stars ≤ 3), `unresolved` (no match — typed year wrong, not a film, ambiguous), `blocked` (tombstoned holder, TMDB lookup failed). The import NEVER creates a film on any path. Idempotent: a re-run only ever links rows that were NULL, which is how an `absent` 1★ film picks up its warning after sync or a list brings it in.

### 4.2 `movie-brain oldratings create [--apply] [--yes]`

The only creating path. Worklist: rows with `film_id IS NULL` and `stars >= 4`. Each is re-resolved and re-gated (O5); a `match` with `no holder` and an empty `corpus_veto` mints the film (born keyed) and links the row `linked_by = 'created'`; a holder that has appeared since is linked instead of twinned. Two rows naming the same work: the first mints, the second links to it through gate 1 — the run processes rows in line order and re-reads holders per row for exactly this. Dry run prints the would-create list with the winning candidate's title, year and tt so the owner can eyeball roughly 26 films before confirming.

### 4.3 `movie-brain oldratings link LINE (--film ID | --none)`

The hand path (O6): `--film` sets `film_id` with `linked_by = 'hand'` (the film must exist and not be disposed; a merged-away id is followed to its survivor); `--none` clears a wrong link. `movie-brain oldratings list [--unlinked]` prints the rows.

### 4.4 Read model and UI

- `FilmView.old_rating` = `{stars, rented_on}` or `None`, fetched in ONE query for the whole view (the sibling of `_lists_by_film`), never stored on `films`.
- **Drawer**, ratings block, directly under My rating: `Me, 2004–08: ★★★★★ · rented 2005-03-02`.
- **Row badge** beside the title: 5★ in the accent green, 1★ in the warning red, nothing for 2–4★.
- **Chip `rewatch`** (plain, labelled "Rewatch", after Owned): `old_rating.stars == 5 and my_rating is None`. Defined in `domain/filters.py::_PREDICATES`, mirrored in `app.js`'s `CHIP_PREDICATES`, one button in `index.html` — the three stay in lockstep. URL state is the ordinary `chips=`.
- `status` gains one line: old ratings `N linked / M total`.

## 5. Tests

- **BDD** (`tests/features/old_ratings.feature`, invented rows only): import links a typo'd title through the resolver; a same-title different-year film is NOT linked; import never creates even with `--apply`; a re-run links a row whose film arrived since and never moves an existing link; `create` mints a 5★, refuses a 3★, links instead of twinning when a holder appeared, and handles two rows naming one work; `link --film` / `--none`; a merge re-points the row.
- **Unit:** the parser; the latest-rented-row rule; the `rewatch` predicate (5★ unrated → in, 5★ rated today → out, 4★ → out).
- **Web:** `/api/films` carries `old_rating`; Playwright: the drawer line, the two badge colours, the Rewatch chip filters and survives a reload.
- **Gates unchanged:** `scripts/thumbprint_benchmark.py --assert` and `matching_benchmark.py` must still pass — this feature calls the resolver and changes nothing in it.

## 6. Out of scope

A hide-1★ filter (O8); review rows (O6); writing `my_ratings` or seeding the ranker from old stars (O1); a generic multi-source "legacy ratings" framework — `source` is a column so a second file costs nothing, but nothing is abstracted until a second source exists; minting 1–3★ films; a hand `create --tt` for a 4–5★ row the resolver refuses (link it by hand after the film arrives some other way, or add the verb if the worklist shows it is needed).

## 7. Documentation

`CLAUDE.md`: the three `oldratings` verbs in Commands; one Rules bullet (single writer, nullable enforced FK and what NULL means, import never creates, create re-gates, Rewatch is a pending request, nothing from the source in the repo). `docs/backlog.md` item 20.

## 8. As built (2026-09-19)

Two departures from §4, both in the refusing direction. A gate 2b failure is an `error` row, not `blocked` (the list verbs' own rule: the holder is unknown, not disproved). No `claim` rows are written — `old_rating` keeps the typed title itself. Rehearsal on a copy of the live DB: import 99 linked · 23 would-create · 57 absent · 23 unresolved · 1 blocked · 0 errors of 203; create 22 minted, all born keyed, 1 linked to a film the same run minted. Every one of the eight links whose catalog title differs from the typed one was checked by hand and is right — including three no title join could have made (an English title onto its original-language film, a short title onto its full one, a retitled release). The unresolved rows are the owner's typos the search APIs cannot find, wrong typed years, and genuine ambiguities: the hand-link worklist, as designed.
