# Power search — one bar, three kinds of match, and the data that makes them answerable

**Status:** design approved in conversation 2026-09-06; awaiting owner review of this written form. Backlog item 8.
**Prior art:** yt-brain (`src/yt_brain/web/dashboard.py`, `application/embed.py`, `infrastructure/database.py::search_similar`), read from a clone at commit of 2026-05-09.
**Sibling docs:** `docs/cinema-companion.md` (seed), `docs/backlog.md` items 4 and 8.

## 0. What this is, and the finding that reframed it

The request was a search bar: freeform text searches everything; `attribute: value` narrows to one field; names and concepts both work; and — the owner's own constraint — it has to survive bad spelling. yt-brain has most of this and was to be the starting point.

The first thing measuring the catalogue showed is that **the ceiling of this feature is set by the data, not the query language.** Of the three example queries, `genre: film noir` works today (OMDb's `Genre` carries `Film-Noir` on 45 films); `Humphrey Bogart` works but thinly (OMDb caps `Actors` at about four names, so 12 films); and `Philip Marlowe` finds six incidental plot mentions, because no character data exists anywhere in the database. No parser and no embedding fixes the third one. So this spec is two things in a fixed order: **first the data** (a TMDB credits enrichment, §4–§6), **then the search** (§7–§10) built on it.

The second finding is that the Marlowe query, which everyone including the author assumed needed semantic search, is an **exact match** once the data exists — TMDB's cast rows carry `character`, and all four Marlowe films in the catalogue hit on it by string. Semantic search is real and wanted, but for prose fields (overview, plot), and it is Phase 2 (§12). Phase 1 ships with zero new runtime dependencies.

## 1. Decisions

| # | Decision | Why |
|---|---|---|
| D1 | **TMDB is the primary metadata source; OMDb is retained for `Genre` only; IMDb bulk datasets rejected** | Measured, §2. TMDB: 24 cast/film with characters. IMDb dataset: 7.9. OMDb: 4. TMDB's genre list has no "film noir"; OMDb's does |
| D2 | **Phase 1 = people (cast, crew, character) + keywords + overview; Phase 2 = semantic over prose** | Every example query is answerable exactly once the data exists. Embeddings cost ~2 GB of dependencies on a four-dependency project — deferred until a query needs them |
| D3 | **Names stored as rows in a `person` table, never inside a JSON payload** | The owner's spelling requirement: 60k names must be trigram-indexable so a misspelling can be corrected *before* the query runs. A blob forecloses it |
| D4 | **Search executes server-side and returns a film-id set; every existing client-side filter stays exactly where it is** | 111k credit rows cannot ride in the films payload, and FTS5 lives in SQLite. The id-set contract is yt-brain's `semanticMatchIds` pattern — chips, scope and list picker intersect with it unchanged |
| D5 | **Field syntax is bare, run-to-next-field: `genre: film noir`** | The owner typed it that way. yt-brain requires quotes (`title:"x"`); quotes stay legal here, never required |
| D6 | **Field filters are exact filters over the whole catalogue, never a post-filter over a top-N** | yt-brain post-filters its semantic top 5×limit, so `channel:"x"` silently misses videos of that channel that didn't rank. Copied deliberately NOT |
| D7 | **Spelling correction is exact-first, then offered and visible; never silent** | "Showing results for Humphrey Bogart" with one-click undo. A wrong guess the owner can't see is worse than zero results |
| D8 | **Correction runs over closed name vocabularies only (person, character, title), never over prose** | "Nearest match" is meaningful in a name list and nonsense in plot text |
| D9 | **Store every crew row with its job and department; expose a curated set as field names, `crew:` as the catch-all** | Owner decision 2026-09-06. ~40 jobs stored; `director:` `writer:` `cinematographer:` `editor:` `composer:` `producer:` exposed |
| D10 | **TMDB keywords are stored but never load-bearing** | 12 of 40 sampled films have none. Any feature that assumes them looks broken a third of the time |
| D11 | **One TMDB call per film via `append_to_response=credits,keywords`** | Verified: credits, keywords, genres, overview, runtime in a single response. 4,569 calls for the whole catalogue |
| D12 | **The `/person` endpoint (biography, birthday, aliases) is out of scope** | ~60k additional calls for fields marked out in §3. `person.tmdb_person_id` is stored so it is a later backfill, not a redesign |
| D13 | **Semantic search, when it comes, is a fourth stage that re-orders the surviving id set** | The `/api/search` contract (§8) does not change for Phase 2 |

## 2. Source grading — measured on the catalogue

Criteria the owner set: completeness, accuracy, ease of joining to our films, storage and indexing, and whether a field supports exact or fuzzy matching. Figures below are from the live database (4,645 live films) on 2026-09-06.

| | OMDb (held) | IMDb bulk datasets | TMDB |
|---|---|---|---|
| Actors per film | **~4**, hard cap | **7.9** (17.1 principals incl. crew) | **24.0** mean, 12 median, 133 max |
| Character names | none | 8.4/film | 22.6/film |
| Keywords | none | none | 5.4/film, **30% of films have zero** |
| Plot / overview | short `Plot` | none | overview on 39/40 |
| Genre | includes `Film-Noir` (45 films) | in `title.basics`, no noir | 19 standard genres, **no noir**; 'film noir' only as a patchy keyword |
| Join to our films | 4,517 / 4,645 | **4,449 / 4,456 tt ids (99.8%)** | 4,569 / 4,645 tmdb ids (98.4%); 63 films hold neither id |
| Cost | paid, already fetched | free, offline, ~1 GB download to refresh | free API, 1 call/film, no advertised rate limit |
| Shape for fuzzy names | JSON blob — no | TSV rows — yes | JSON rows — yes |

TMDB sample: 40 random catalogue films. IMDb: full scan of `title.principals.tsv.gz` (782 MB) against every tt id we hold. Marlowe test: TMDB returned `character = "Philip Marlowe"` on all four Marlowe films in the catalogue (*The Big Sleep*, *The Long Goodbye*, *Farewell, My Lovely*, *Murder, My Sweet*); the IMDb dataset also carries characters but at a third of the cast depth.

**Verdict (D1).** TMDB primary. OMDb kept for `Genre` — the owner's own example query depends on the source we would otherwise have retired. IMDb datasets rejected for cast depth, but recorded here as the free, offline, no-API fallback should TMDB ever close: the join is the `tt` id we already hold.

## 3. Attribute catalogue

Every field TMDB returns for a film (with `credits,keywords,release_dates,alternative_titles,translations,external_ids,reviews` appended) and for a person, classified by how a query can match it. "Phase" says when it becomes searchable; "held" means the database already stores it.

### 3.1 Exact — closed vocabulary or number; an index hit, no interpretation

| Field | Source | Phase |
|---|---|---|
| genre | OMDb `Genre` (held) + TMDB `genres` | **1** |
| crew job / department (Director, Screenplay, Director of Photography, Editor, Original Music Composer, Producer… 10 departments, ~40 jobs) | TMDB `credits.crew` | **1** (D9) |
| year, runtime | held (`films.year`, `tmdb_facts.runtime_min`) | **1** |
| keyword | TMDB `keywords` | **1**, non-load-bearing (D10) |
| vote_average, vote_count, popularity, budget, revenue | TMDB | later |
| production country, spoken language, original language, US certification, status, collection, production company | TMDB (`release_dates` for certification) | later |
| imdb_id, wikidata_id | TMDB `external_ids` | imdb held; wikidata later |

### 3.2 Fuzzy — open text over a bounded name list, where "nearest" is meaningful

| Field | Source | Phase |
|---|---|---|
| **person name** (~60k distinct) | TMDB `credits` | **1** |
| **character** | TMDB `credits.cast` | **1** |
| title, original_title | held | **1** |
| alternative titles (35 languages on *The Big Sleep*) | `tmdb_facts.alt_titles` (held) | later |
| keyword as typed | TMDB | 1, corrected to exact |
| also_known_as ("Bogie"), place_of_birth | TMDB `/person` | **out** (D12) |

### 3.3 Semantic — prose; meaning, not string

| Field | Source | Phase |
|---|---|---|
| **overview** | TMDB | stored in **1**, searched semantically in **2** |
| **plot** | OMDb (held) | **2** |
| tagline | TMDB | stored in 1, searched in 2 |
| reviews, foreign-language overviews (`translations`) | TMDB | out |
| person biography | TMDB `/person` | out (D12) |

### 3.4 Display-only, never searched

poster_path, backdrop_path, profile_path, homepage, adult, video, softcore, gender.

### 3.5 How the classes combine

Exact filters **narrow**. Fuzzy fields are **corrected to an exact value, then narrow** — `actor: bogrt` becomes `person_id = 4110` and is an index hit from there. Semantic **ranks** whatever survives. The order is fixed: exact ∩ fuzzy-corrected first, semantic last and only within that set. `hard boiled San Francisco private investigator genre: film noir` therefore filters to the 45 noir films exactly and, in Phase 2, orders them by overview similarity; in Phase 1 the same query filters identically and ranks the freeform words by FTS5 (§8). This ordering is why Phase 1 ships without Phase 2 changing any interface (D13).

## 4. Data model — migration 018

```sql
CREATE TABLE person (
    id              INTEGER PRIMARY KEY,
    tmdb_person_id  INTEGER NOT NULL UNIQUE,
    name            TEXT    NOT NULL,
    first_seen      TEXT    NOT NULL
);

CREATE TABLE film_credit (
    film_id     INTEGER NOT NULL REFERENCES films(id),
    person_id   INTEGER NOT NULL REFERENCES person(id),
    kind        TEXT    NOT NULL CHECK (kind IN ('cast','crew')),
    job         TEXT    NOT NULL DEFAULT '',   -- crew: TMDB job ('Director', 'Screenplay', …); '' for cast
    department  TEXT    NOT NULL DEFAULT '',   -- crew: TMDB department; '' for cast
    character   TEXT    NOT NULL DEFAULT '',   -- cast: as credited; '' for crew
    ord         INTEGER NOT NULL,              -- TMDB `order` for cast; row order for crew
    UNIQUE (film_id, person_id, kind, job, character)
);
CREATE INDEX film_credit_person ON film_credit(person_id);
CREATE INDEX film_credit_film   ON film_credit(film_id);

CREATE TABLE film_keyword (
    film_id  INTEGER NOT NULL REFERENCES films(id),
    keyword  TEXT    NOT NULL,
    PRIMARY KEY (film_id, keyword)
);

ALTER TABLE tmdb_facts ADD COLUMN overview           TEXT;
ALTER TABLE tmdb_facts ADD COLUMN tagline            TEXT;
ALTER TABLE tmdb_facts ADD COLUMN genres             TEXT;   -- JSON list of TMDB genre names
ALTER TABLE tmdb_facts ADD COLUMN credits_fetched_on TEXT;   -- the enrichment stamp

-- FTS5 with the trigram tokenizer (verified available in the stdlib sqlite3, 3.50.4):
CREATE VIRTUAL TABLE person_fts    USING fts5(name,      content='person',      content_rowid='id', tokenize='trigram');
CREATE VIRTUAL TABLE character_fts USING fts5(character, content='film_credit', content_rowid='rowid', tokenize='trigram');
CREATE VIRTUAL TABLE film_text_fts USING fts5(title, overview, plot, content='', tokenize='unicode61');
```

Notes. `job`, `department` and `character` are `NOT NULL DEFAULT ''` rather than nullable so that the `UNIQUE` constraint actually dedups (SQLite treats two NULLs as distinct in a unique index, so a nullable `character` would let the same cast row in twice). `film_credit` keeps the default `rowid`, which is what `character_fts` is keyed on. `film_text` is a small content table (`film_id`, `title`, `overview`, `plot`) that exists only because an external-content FTS5 index needs one content table and these columns come from three; all three FTS indexes are external-content tables kept in step by triggers, so the base tables stay the truth. **A bare trigram `MATCH` is a substring test** (verified: `bogrt` finds nothing); misspelling lookups are an OR of the query's trigrams (`domain/search.py::trigram_query`), which returns every name sharing a window for the resolver to rank. Migration wrapped in `BEGIN/COMMIT`; migration 018 inserts its own `schema_version` row; `movie-brain migrate --apply` is the only path that applies it.

Volume: ~4,645 films × 24 cast ≈ 111k credit rows, ~60k persons. Trivial for SQLite; the trigram indexes will be a few tens of MB.

`person` is NOT an identity in the `films.guid` sense and `tmdb_person_id` is NOT a `KEY_AUTHORITY`. `merge_film` must move `film_credit` and `film_keyword` rows to the survivor like every other film-scoped table (the same rule `lists.md` states for `film_list_entry`), and the plan must add that.

## 5. Enrichment verb

`movie-brain enrich credits [--apply] [--limit N]`

Worklist: live, non-disposed films holding a `tmdb` external id and no `credits_fetched_on` (or one older than a `--refresh-days` the plan may add later; not in scope now). One call per film (D11). For each: upsert `person` rows by `tmdb_person_id`, replace the film's `film_credit` and `film_keyword` rows, write `overview`, `tagline`, `genres` and the stamp on `tmdb_facts`, and delete-and-reinsert the film's `film_text_fts` row — all inside one transaction per film. Dry-run by default; `--limit` batches; the same consecutive-failure abort and resume-by-stamp pattern as `cheapcharts resolve` and `repair imdb`. Pacing: TMDB advertises no limit; keep the existing `TmdbClient` session and a modest delay.

`movie-brain status` gains a line: films enriched / with a tmdb id.

Not in sync. The owner runs syncs by hand and this is a one-time backfill plus occasional refresh.

## 6. What Phase 1 stores from the credits call

From `credits.cast`: `id` → `tmdb_person_id`, `name`, `character`, `order`. From `credits.crew`: `id`, `name`, `job`, `department`. From `keywords.keywords[].name`. From the movie body: `overview`, `tagline`, `genres[].name`. Everything else in §3 marked "later" or "out" is not written — including `gender`, `popularity`, `profile_path`, which are display or ranking niceties with no query attached to them.

## 7. Query language

### 7.1 Grammar (D5)

A **field token** is an identifier followed by a colon: `actor:`. Its **value** runs from the first non-space after the colon to the next field token or end of input. Text before the first field token, or between the last value and end, that is not part of a value is **freeform**. Double quotes group a value that would otherwise be split by a following field-looking word; they are never required.

```
film noir                                → freeform
genre: film noir                         → genre only
actor: bogart genre: film noir           → both, ANDed
character: philip marlowe                → the four Marlowe films
director: hawks year: 1940-1949          → ranged
"crew: catering" title: brazil           → the quoted text is freeform, not a field
```

Multiple fields are ANDed. The same field twice is ORed (`actor: bogart actor: bacall` = either). A value may not be empty; `actor:` alone is freeform text `actor:` and produces a hint.

### 7.2 Fields

| Field | Aliases | Class | Resolves against |
|---|---|---|---|
| `title` | | fuzzy | `films.title`, `tmdb_facts.original_title` |
| `actor` | `cast` | fuzzy → exact | `person.name` where `kind='cast'` |
| `character` | `role` | fuzzy | `film_credit.character` |
| `director` | | fuzzy → exact | `person.name` where `job='Director'` |
| `writer` | | fuzzy → exact | `job IN ('Screenplay','Writer','Novel','Story','Author')` |
| `cinematographer` | `dp` | fuzzy → exact | `job='Director of Photography'` |
| `editor` | | fuzzy → exact | `job='Editor'` |
| `composer` | `music` | fuzzy → exact | `job='Original Music Composer'` |
| `producer` | | fuzzy → exact | `job IN ('Producer','Executive Producer')` |
| `crew` | | fuzzy → exact | any crew row, all ~40 jobs (D9) |
| `genre` | | exact | OMDb `Genre` ∪ TMDB `genres`, case-insensitive, hyphen/space-insensitive (`film noir` = `Film-Noir`) |
| `keyword` | `kw` | exact, corrected | `film_keyword.keyword` |
| `year` | | exact / range | `films.year`; `1946`, `1940-1949`, `1940-`, `-1949` |
| `plot` | `overview` | freeform-in-field | FTS5 over overview + plot only |

The job sets above are the plan's to verify against the live crew-job vocabulary after enrichment; they are the current best reading of TMDB's job names on *The Big Sleep*.

An unknown field name is not an error: `foo: bar` is treated as the freeform text `foo: bar` and the response carries `hint: "unknown field 'foo'"`.

### 7.3 Spelling (D7, D8)

For a fuzzy field: try an exact (case-insensitive) match first. If none, query the field's trigram FTS index and take the top candidate above a fixed similarity floor (the plan sets it and pins it with a test on a deliberate misspelling). The response records `{field, typed, used}` in `corrections`; the bar renders "Showing results for **Humphrey Bogart**" with an undo that re-runs the query with the typed text quoted, which forces exact. If no candidate clears the floor, the result is empty and the response carries the nearest three as `suggestions`, which the bar offers as clickable chips. Freeform text is never corrected.

## 8. Execution and ranking

`GET /api/search?q=…` → `{ ids: [film_id, …], corrections: [...], suggestions: [...], hint: str|null, total: int }`

Three stages, always in this order:

1. **Parse** — `domain/search.py`, pure: query string → `ParsedQuery(fields=[(name, value)…], free=str)`. No SQL, no I/O; fully unit-testable.
2. **Resolve** — `application/search.py`: each fuzzy field value → an exact id or value via the repository (`resolve_person(name, job_filter)`, `resolve_character(text)`, `resolve_title(text)`), producing corrections and suggestions.
3. **Filter and rank** — one repository call builds one SQL statement: exact and resolved fields become an `AND` of `EXISTS` subqueries against `film_credit` / `film_keyword` / genre / year; freeform text becomes an FTS5 `MATCH` over `film_text_fts` plus the person and character indexes, unioned and weighted.

**Ranking.** A query with no freeform text returns its set unranked; the dashboard's current sort applies. A query with freeform text ranks by where the text hit, using FTS5's built-in `bm25()` with per-column weights — title highest, then person name, character, genre/keyword, plot lowest — and the client sorts by that rank while the search is active. No scoring code of our own.

**Limits.** The endpoint returns every matching id (the dashboard is a client-side table over the whole catalogue; an id list of a few thousand integers is small). No `limit` parameter in Phase 1.

## 9. The client

`app.js` gains a search bar above the chips. On input (300 ms debounce) it calls `/api/search`, stores `searchMatchIds: Set` and `searchRank: Map`, and the existing filter pipeline intersects with the set when it is non-null — chips, the scope toggle and the list picker all keep working mid-search, none of their logic moves (D4). While `searchRank` is non-null and the query had freeform text, sort leads with rank. URL state carries `q=`; clearing the bar restores the previous sort and removes `q`. Corrections render as a line under the bar; suggestions as clickable chips that replace the field value.

The bar's `<input>` carries a class of its own, NOT `chip` — the `#chips` click handler matches `.chip` and would add `undefined` to the chip set (the same trap `lists.md` records for the list picker).

## 10. Degradation

- **Enrichment not run yet.** Search works on what is stored — title, `films.director`, OMDb genre and plot. `actor:` and `character:` match nothing and the response `hint` says "no credits loaded — run `movie-brain enrich credits --apply`". `status` shows the count.
- **TMDB unreachable during enrichment.** Consecutive-failure abort, stamp-based resume. Nothing partial is left: a film's credit rows are replaced inside one transaction.
- **A film with no tmdb id** (63 today). Not on the worklist; searchable on its held fields only.
- **FTS5 trigram unavailable** (a Python built against an old SQLite). Migration 018 fails loudly at `migrate --apply` rather than creating a table that cannot be queried; the message names the required SQLite version.

## 11. Testing

- **Parser:** `tests/unit/test_search_parser.py` — every grammar line in §7.1, quotes, unknown field, empty value, repeated field, ranges.
- **Resolution and ranking:** `tests/unit/test_database.py` against a seeded repo — exact hit, a deliberate misspelling → correction, no candidate → suggestions, `director:` excludes an actor of the same name, genre hyphen/space equivalence, `bm25` weighting puts a title hit above a plot hit.
- **Enrichment:** `tests/features/enrich.feature` + step defs with a fake TMDB — dry run writes nothing; apply writes persons/credits/keywords/overview/stamp; a second run skips stamped films; abort on repeated failure; re-run replaces (never duplicates) a film's rows.
- **Migration:** the existing migration tests plus one asserting the trigram tables exist and answer a `MATCH`.
- **Bar:** `tests/web/test_dashboard.py` — a field query, a freeform query ranked, a correction offered and undone, a chip staying active mid-search, `q=` round-tripping through the URL.
- **`merge_film`:** an added scenario asserting credit and keyword rows move to the survivor.

## 12. Phase 2 — semantic search (not in this spec, shape fixed here)

When a query's freeform text is conceptual ("hard boiled San Francisco private investigator") rather than lexical, FTS5 ranking is weak. Phase 2 embeds `overview + plot + tagline` per film (yt-brain's `all-MiniLM-L6-v2` via sentence-transformers is the proven choice; sqlite-vec for storage) and adds a **fourth stage** to §8 that re-orders the surviving id set by cosine distance, gated by a distance floor the way yt-brain's slider is. The `/api/search` contract does not change (D13). It brings ~2 GB of dependencies and must be an optional extra (`uv sync --extra semantic`) with the LIKE-style degradation yt-brain already has. Its own spec.

## 13. Out of scope

`/person` fields (biography, birthday, aliases) · reviews · translations · images · TV · any change to matching or identity (`person` is not an identity; nothing here touches `key_film`, the thumbprint resolver or `films.guid`) · running enrichment inside `sync` · a `limit`/pagination on the endpoint · natural-language query parsing ("films where Bogart plays a detective") · search-as-you-type suggestions beyond the correction line.

## 14. What was taken from yt-brain and what was deliberately not

**Taken:** the one-bar UX; the server-returns-an-id-set / client-intersects pattern (`semanticMatchIds`, `semanticRankMap`); the 300 ms debounce; graceful degradation when a capability is absent; the embedding model and storage choice, held for Phase 2.

**Not taken, on purpose:** quoted-only field syntax (D5); field filters as a post-filter over a semantic top-N (D6 — it silently drops matches); a distance slider in Phase 1 (nothing to slide yet); search living in an inline `<script>` inside a 1,759-line `dashboard.py` — here the parser is a pure domain module and the bar's JS lives in `app.js` with the rest of the dashboard's client logic.
