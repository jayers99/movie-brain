# Curated top-N lists — design (backlog item 10, v1)

**Date:** 2026-08-28 · **Status:** ratified. Supersedes §5 of [2026-08-28-curated-lists-seed.md](2026-08-28-curated-lists-seed.md), whose §0 (the point), §4 (D1–D4), §5.5 (three-gate guard), §5.6 (two-phase create + scorecard), §5.7 (tally constraints), §6 (out of scope), §7 (risks) and §8 (gates) remain binding. The seed's appendix is the first list's source data.

**Governing constraint (seed §0, unchanged):** this import is an accuracy test of the T1–T5 identity stack, and duplicate films are the failure it must not produce. Refusing to create is always cheaper than minting a twin.

## 1. What changed from the seed, and why

Four amendments. Three came out of a live read-only probe of all 100 Cahiers entries against a scratch copy of the catalog on 2026-08-28 (`probe_100.py`, never written to the repo — the real dry run is `lists import` itself).

### A1 — `list` review rows drain with `--film` / `--create` / `--dismiss`, not `--pick/--tt/--none` (owner-confirmed)

The seed said ambiguous entries drain with `review resolve --pick/--tt/--none`. Those three are gated in `application/review.py` on `authority == TMDB_AUTHORITY` **and** a non-null `film_id`, because each one *keys a film*. A list entry that matched nothing has no film to key, so that path cannot work. `list` rows therefore accept exactly what the metacritic-slug and apple-tv precedents accept:

| verb | effect on a `list` row |
|---|---|
| `--film ID` | link the entry to that film; write the `list` claim |
| `--create` | create a film from `title_listed` + `director_listed` (year NULL, unkeyed) and link the entry; the next `sync` keying step keys it, exactly as an apple-tv `--create` film is keyed |
| `--dismiss` | permanent: the entry stays unlinked and is never re-queued |

**Consequence, stated plainly:** the seed's §5.6 claim that draining this list's residue grows the benchmark corpus is **false for unlinked entries**. `application/eval_log.py::ratify` needs a film id, and an unlinked list entry has none. No list-row resolution writes to `scripts/eval/thumbprint_eval_v1.csv`. (Nothing is lost — a created film's own keying still flows through the ordinary sync/`repair nomatch` paths, which ratify as they always did.)

### A2 — form ladder, fallback-only (owner-confirmed)

`ParsedTitle.title` keeps an alt-title parenthetical, and `CandidateFetcher.fetch` searches `q.title` verbatim. 16 of the 100 Cahiers entries carry a parenthetical. The probe showed the director-credit search rescues most of them anyway — but not all.

So: when the primary form's verdict is **not** `match`, retry with `parsed.base`, then each `parsed.alt_titles` entry, stopping at the first `match`. Fallback-only, so an already-corroborated match is never overridden by a later form.

Measured payoff on Cahiers: 2 links recovered.

```
#33  Diamond Earrings (Madame de…) / Max Ophüls
     'Diamond Earrings (Madame de…)' → review 'director conflicts only'
     'Diamond Earrings'              → review 'director conflicts only'
     'Madame de…'                    → MATCH tt0046022 'director corroborated'
#51  Beauty and the Beast (La Belle et la Bête) → matched via base form 'Beauty and the Beast'
```

The resolver, the fetcher and the fixture are untouched, so the thumbprint gate is unaffected. Reason strings are contract text and are never reworded; the form actually used is recorded separately (`[via form 'X']` in the scorecard, and in the entry's claim).

### A3 — creation is its own verb (owner-confirmed)

`lists import FILE [--apply]` links, records and queues; it **creates nothing, ever**. `lists create SLUG [--apply] [--yes]` mints films for the entries phase 1 reported as would-create — re-resolving and re-running all three gates at creation time rather than trusting phase 1's stored verdict, the same re-derive-at-resolution-time rule the repair verbs follow.

### A4 — gate 2 gets a `find_by_imdb` fallback (gate 2b) — new, adopted

The probe found the seed's gate 2 is blind in a case that occurs on the very first list. Gate 2 reads `winner.tmdb_id` off the resolver's candidate. An **OMDb-only winner carries no TMDB id**, so gate 2 asks nothing.

Live example, #69 *Intolerance* / D. W. Griffith:

- resolver → `tt0006864`, director corroborated
- gate 1: no film holds `tt0006864` → miss
- gate 2: the winning candidate is OMDb-only, `tmdb_id is None` → **asks nothing**
- gate 3 (seed design): film #3096 `'Intolerance' (1916)` vetoes → review row for a human

But #3096 *does* hold `tmdb=3059`, and `TmdbClient.find_by_imdb('tt0006864')` returns **3059**. The right answer was one call away.

**Gate 2b:** when the winning candidate carries no TMDB id, ask TMDB for the mapping — exactly what `key_film` already does on every keying path — and check that holder too. This converts #69 from a review row into a correct link.

Note the direction of travel: gate 2b can only *find more holders*, so it strictly **reduces** creations and blocks. That is the direction seed §0 demands. The residual risk is the known one — a TMDB record carrying a wrong `imdb_id` (the *Summer of Soul* shape) would map to the wrong film — and it is the same trust `key_film` already places in this call. The scorecard is what surfaces such a link.

Gate 3 keeps its place even though it fired zero times after 2b: it is the only gate covering the 61 films that hold neither id, and the true `ttA`/`ttB` case where TMDB's own mapping does not reunite the two records.

## 2. Probe result — the expected shape of the Cahiers import

Full 100 entries, live resolver + live catalog copy, read-only, gates as specified above:

| outcome | n |
|---|---|
| **linked** to an existing film | **75** |
| **would-create** (all three gates miss) | **20** |
| **review** (resolver `review` verdict) | **5** |
| blocked (gate 3 veto / tombstoned holder) | 0 |
| error | 0 |

The five reviews: #27 *The Box of Pandora (Loulou)* `no candidates` · #34 *Pleasure* and #36 *The Adventure* and #82 *Tabu* `director conflicts only` · #94 *Mulholland Dr.* `ambiguous (several director hits)` (tt0166924 vs tt1619856).

All 20 would-creates were checked against the catalog by fuzzy title and are genuinely absent — there is no *Greed*, no *Contempt*, no *Grand Illusion* in the DB today. This corrects two things the seed asserted from its naive probe: `La Grande Illusion` is **not** held as *Grand Illusion*, and *Greed* — §5.5's marquee `ttA`/`ttB` example — is not in the catalog at all. The real live example of that shape is #69 *Intolerance*, above.

20 creations sits inside seed §7's tripwire ("well under 33"); nothing here says to stop.

## 3. Data model — migration 013

```sql
BEGIN;
CREATE TABLE film_list (
    slug           TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    curator        TEXT,
    published_year INTEGER,
    source_url     TEXT,
    ordered        INTEGER NOT NULL DEFAULT 1,
    imported_at    TEXT NOT NULL
);
CREATE TABLE film_list_entry (
    list_slug       TEXT NOT NULL REFERENCES film_list(slug),
    rank            INTEGER NOT NULL,
    film_id         INTEGER REFERENCES films(id),
    title_listed    TEXT NOT NULL,
    director_listed TEXT,
    PRIMARY KEY (list_slug, rank)
);
CREATE INDEX film_list_entry_film ON film_list_entry(film_id);
INSERT INTO schema_version (version) VALUES (13);
COMMIT;
```

- Naming `film_list` / `film_list_entry` (not the backlog's `lists` / `list_entries`) because `Repository.list_views()` already exists and means something else; `repo.lists()` beside it would read badly.
- `title_listed` / `director_listed` are verbatim forever — a list is a historical artifact, and the resolver's later re-readings must see what the curator actually wrote. Typos included (`Howard Hawkes`, `Joseph Mankiewitz`, `Ernst Shoedsack`).
- `film_id` nullable: an unlinked entry is a first-class state, not an error.
- The `film_list_entry_film` index exists for §5.7 constraint 1 (one query for the whole view).
- No `trusted` / weight / tag column (D4). §5.7 constraint 4 keeps that purely additive later, because the tally is computed, never stored.

**`merge_film` gains one statement:** `UPDATE film_list_entry SET film_id = ? WHERE film_id = ?`. No conflict handling is possible or needed — the PK is `(list_slug, rank)` and nothing is unique on `film_id`. Reported in `MergeReport.moved` as `film_list_entry`.

## 4. The list file (D1)

One checked-in file per list at `lists/<slug>.tsv`. Claude extracts it once; a CLI verb imports it. No scraper, no per-site selectors.

```
# slug: cahiers-100
# name: 100 Films for an Ideal Cinematheque
# curator: Cahiers du Cinéma
# published: 2008
# source: https://www.filmdetail.com/2008/11/23/cahiers-du-cinemas-100-greatest-films/
# ordered: true
1	Citizen Kane	Orson Welles
2	The Night of the Hunter	Charles Laughton
```

`infrastructure/listfile.py`:

- `parse_list_file(text) -> ParsedList` — pure. Header block is `# key: value` lines before the first data row; `slug` and `name` required, the rest optional (`ordered` defaults true). Data rows are `rank<TAB>title<TAB>director`, director optional (an empty third column or a two-column row both mean "no director"). Blank lines and `#` lines after the header block are skipped. Raises `ListFileError` on: a missing required header, a non-integer rank, a duplicate rank, an empty title.
- `read_list_file(path) -> ParsedList` — the one I/O function.
- Titles are kept byte-for-byte, curly apostrophes and `…` included. No normalization at parse time.

Domain dataclasses in `domain/models.py`: `ListMeta(slug, name, curator, published_year, source_url, ordered)` and `ListEntry(rank, title_listed, director_listed)`.

## 5. Phase 1 — `movie-brain lists import PATH [--apply]`

`application/lists.py::import_list`. Dry run by default. A third sibling of `owned.py::import_owned` and `metacritic.py::promote_top_n`, and it should read like them.

```
upsert film_list ← the file's header
build_candidate_index(repo.films_for_matching())          # once, never per entry
for each entry:
    if the entry already carries a film_id (re-import):   → skip, unchanged, no API call
    verdict, form = resolve_entry(fetcher, entry)         # form ladder, fallback-only
    if verdict is not match:                              → REVIEW  (film_id NULL, queue a row)
    holder = find_holder(repo, tmdb, verdict)             # gates 1, 2, 2b + canonicalize
    if holder is tombstoned:                              → BLOCKED (queue a row)
    if holder is not None:
        if holder already sits at another rank on this list: → BLOCKED duplicate-entry (queue a row)
        link the entry, add_claim(holder, 'list', f'{slug}#{rank}', title_listed)
                                                          → LINKED
    if corpus_veto(index, forms) is non-empty:            → BLOCKED gate 3 (queue a row)
    else:                                                 → WOULD-CREATE (film_id NULL, no row)
```

- `make_query(form, None, "list", director=entry.director_listed)`. **Year is always `None`** — the list has none, and a wrong year actively misleads the resolver. Source `"list"` lands on `YearClass.APPLE_FIELD`, which is inert when `q.year is None` (`older` is only set for a non-None year), so the year class never decides anything here.
- **Gate 3** is `CandidateIndex.lookup(form)` returning **any** hit, for **any** form in the ladder. It is a veto, not a matcher: a weak or ambiguous hit is reason enough to stop. This deliberately inverts `owned import`, where the corpus matcher is a fallback.
- **Duplicate-entry guard:** two ranks resolving to the same film is the list-shaped mirror of the duplicate-film risk. The second one blocks and queues; it never silently double-links.
- **Never creates a film.** Not on any path, not with `--apply`.
- A resolver/API failure for one entry logs and counts as `error`; it does not abort the run.

### Review rows

Authority `list`, `value = f"{slug}#{rank}"`, `film_id` NULL, reasons `unresolved` (resolver `review`), `corpus-veto`, `duplicate-entry`, `tombstoned-holder`. `detail` carries the listed title/director, the resolver reason, the form used, and the A/B/C candidates or vetoing films.

**Idempotence uses a list-local helper, not `queue_review_once`.** `queue_review_once` dedups on `reason + film_id`; every list row has `film_id` NULL, so the first open row of a given reason would suppress every later one. `application/lists.py::queue_list_review_once` dedups on `reason + value` instead and consults `repo.resolved_review_keys('list')`, so a `--dismiss` is permanent exactly as elsewhere.

### Idempotence of the import itself

Re-running `lists import` on the same file: the registry row is upserted (metadata refreshed, `imported_at` bumped), entries are upserted by `(list_slug, rank)`, entries that already carry a `film_id` are **skipped without an API call**, and no review row is duplicated. Nothing is created twice. Ranks change if the file changes; links do not move on their own.

## 6. Phase 2 — `movie-brain lists create SLUG [--apply] [--yes]`

`application/lists.py::create_films`. Worklist = entries on that list with `film_id IS NULL` and **no** `list` review row (open or resolved) for their `slug#rank` — a row means a human owns that entry.

Per entry: re-resolve (same ladder), re-run gates 1/2/2b/3. Then

- a holder now exists → **link** it, no creation (the world moved since phase 1);
- gate 3 vetoes now → **block** and queue, no creation;
- verdict is no longer a `match` → **block** and queue;
- otherwise → `create_film` + `key_film`.

The created film's `title` and `year` come from the **winning candidate** (TMDB's own title/year), not the listed title, so the row looks like the rest of the catalog and lands on the right year; `director` is `director_listed`; `url` is empty. If the winner carries neither, fall back to `title_listed` with year `None`. `films.key` is checked against `repo.tombstoned_keys()` first and a `create_film` returning `None` (key collision) blocks and queues rather than adopting the colliding film. Then:

```python
key_film(repo, tmdb, film_id, verdict.tt, today, log, tmdb_id=winner.tmdb_id)
```

so the film is **born keyed**, exactly like Mode-B promotion. A `held`/`error` result leaves the film unkeyed and is logged; the next `sync` keying step retries it.

Auto matches are **never** ratified into the eval CSV — same rule as `repair nomatch`; the gate must not score itself.

## 7. The scorecard (seed §5.6 — the actual deliverable)

Both verbs print one two-line block per entry, every entry, eyeballable in one pass. A wrong *link* is silent in a way a duplicate is not, so links are as inspectable as creations. The resolver's reason string appears verbatim.

```
#3    The Rules of the Game (La Règle du jeu) / Jean Renoir
      → LINKED  #1207 'The Rules of the Game' (1939) dir Jean Renoir  via imdb tt0031885  [director corroborated]
#33   Diamond Earrings (Madame de…) / Max Ophüls
      → LINKED  #2973 'The Earrings of Madame de . . .' (1953) dir Max Ophuls  via tmdb tt0046022  [director corroborated]  [via form 'Madame de…']
#36   The Adventure / Michelangelo Antonioni
      → REVIEW  resolver 'director conflicts only'  cands: none
#68   La Grande Illusion / Jean Renoir
      → WOULD-CREATE tt0028950 'Grand Illusion' (1937)  [director corroborated]
```

Followed by the tally: `linked · would-create · review · blocked · error`.

## 8. Read model + drawer

`FilmView.lists: list[dict]` = `[{slug, name, curator, published, rank}]`, `field(default_factory=list)`.

Fetched by **one query for the whole view**, `_LISTS_SQL` + `_lists_by_film`, copied verbatim in shape from `_SERVICES_SQL` + `_services_by_film` (§5.7 constraint 1 — the table renders ~4,600 films at once; a per-film query is a 4,600-query page load):

```sql
SELECT e.film_id, e.list_slug, l.name, l.curator, l.published_year, e.rank
FROM film_list_entry e JOIN film_list l ON l.slug = e.list_slug
WHERE e.film_id IS NOT NULL
ORDER BY e.film_id, l.name, e.rank
```

Wired into both `list_views` and `get_view`, alongside `services`/`new_on`/`owned`.

Drawer gains one line beside "Also streaming on:", rendered from `d.lists`:

```
On lists:  Cahiers du Cinéma 2008 #3
```

An unordered list renders without the `#rank`. No new endpoint, no server-side filtering: `app.js` already receives the full view JSON.

`export csv` uses an explicit `COLUMNS` list, so the new field is inert there. No `/api/config` change (no threshold).

## 9. Explicitly out of v1

Everything in seed §6, plus: `--pick/--tt/--none` on list rows (A1), a `--refresh` mode that re-resolves already-linked entries, and re-fetching a list from its source URL. The cross-list tally (§5.7) stays designed-for and unbuilt; its four constraints are honoured by §3 (no denormalized count, an index for the one-query fetch) and §8 (`lists` is a list of dicts, so `len(f.lists)` is the tally client-side).

## 10. Testing

Mirrors the layers, per CLAUDE.md.

- `tests/unit/test_listfile.py` — the parser: full header block, missing required header, `ordered: false`, two-column rows, empty director cell, blank/comment lines, curly apostrophes and `…`, non-integer rank, duplicate rank, empty title.
- `tests/unit/test_lists_ladder.py` — the form ladder: single-form title queries once; a parenthetical title falls back base-then-alt; the ladder stops at the first `match`; a primary `match` is never overridden.
- `tests/features/lists.feature` + `tests/step_defs/test_lists.py` — an injected `_PoolFetcher`-style fake (not HTTP mocks), following `tests/step_defs/test_thumbprint.py`: link via gate 1, link via gate 2, link via gate 2b (OMDb-only winner), gate-3 veto blocks, duplicate-entry blocks, tombstoned holder blocks, resolver `review` queues, would-create is reported and **nothing is created**, dry run writes nothing at all, re-import is idempotent and makes no API call for linked entries, `lists create` creates + keys, `lists create` links instead when a holder appeared, `review resolve --film/--create/--dismiss` on a list row, `merge_film` re-points entries.
- `tests/web/` — `/api/films/<id>` carries `lists`; a Playwright assertion that the drawer's "On lists:" row renders.

## 11. Gates (seed §8, unchanged)

`uv run pytest` · `uv run ruff check .` · `uv run mypy` · `uv run python scripts/thumbprint_benchmark.py --assert` (baseline **n=571 / WRONG=0 / 92.0% over 526**) · `uv run python scripts/matching_benchmark.py --assert-dominance`. Green at every step. The eval CSV and the fixture are never hand-edited. Nothing in this design touches `domain/thumbprint.py`, `thumbprint_fetch.py` or the fixture, so the thumbprint gate should be bit-identical throughout — if it moves, something is wrong.

## 12. Rehearsal before live

Branch `feature/curated-lists`. The Cahiers import is rehearsed end to end on a scratch copy of the live DB (`MOVIE_BRAIN_CONFIG_DIR` set on every command, subagents included), full scorecard reviewed by the owner, and only then run live — `lists import --apply` first, `lists create --apply` as a separate confirmed step.
