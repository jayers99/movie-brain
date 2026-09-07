# Drawer redesign — credits, ratings block, person links, watch link

**Date:** 2026-09-07 · **Status:** approved design, awaiting plan · **Closes:** backlog 14 (person links) and the cast/metadata half of backlog 4 (richer drawer; the trailer and critic-review halves stay open).

## 1. Goal

The film drawer is where the owner decides what to watch tonight. Today it shows OMDb's three-name cast, its 155-character plot, the ratings as a bare list under the external links, and an "Owned on Apple TV" search link that only exists for owned films. This redesign makes the drawer answer four questions in order: what is this film (summary, credits), how good is it (my rating, critics, lists), where do I watch it (one link), and where else is it. Every person named becomes a filter on the table.

Mockup approved 2026-09-07 (`.superpowers/brainstorm/51519-1788804473/content/drawer-layout-v3.html`, git-ignored; The Big Sleep with live data).

## 2. Decisions (owner rulings, 2026-09-07)

| # | Ruling | Evidence / cost if wrong |
|---|--------|--------------------------|
| D1 | Summary is TMDB's overview; OMDb's plot only when the overview is empty. | OMDb plot avg 155 chars, max 238; TMDB median 226, p90 449, max 995. 188 films have an overview and no OMDb plot, 24 the reverse, 193 neither. Reversible: one branch in the template. |
| D2 | Cast comes from `film_credit` in TMDB billing order (`ord`). Inline: the first six names only. Expanded: the whole cast, one per line, "Name as Role", two columns. | OMDb averages 2.9 names; `film_credit` 27.9, and 3,894 films hold six or more. TMDB's `order` is the film's curated billing; person `popularity` was rejected as today's fame, not the film's. |
| D3 | Writers: every `Writing`-department credit, one entry per person, bare name for Screenplay/Writer, other jobs in parentheses ("Raymond Chandler (novel)"). | 4,217 films carry one. |
| D4 | Person links on director, cast, writer: close the drawer, put `director: "Name"` / `actor: "Name"` / `writer: "Name"` in the search bar, run it, touch no other control. Quoted because the name comes from the same `person` table the search resolves against. | The list-picker ruling: a filter the owner set stays set. OMDb-fallback names are bare (unquoted) so the fuzzy stage can bridge spelling drift. |
| D5 | Ratings block sits after Writer and before the watch line: My rating, then IMDb · Metacritic · Rotten Tomatoes on one line, then On lists with the canon score. | Values are `FilmView.imdb` / `metacritic` (scraped-first) / `rt`, the same numbers the table columns show; OMDb's `Ratings` array is no longer rendered. |
| D6 | The watch line is one link, "Watch on <best source> ↗", landing on the service's own title search. Owned films read "Owned on Apple TV ↗" and land on the Apple TV search, as today. | `best_source` already short-circuits to the store for owned films (watch.py). |
| D7 | Per-service search templates live in the registry: migration 021 adds `movie_service.search_url`, written only by `movie-brain services url`. Fallback is the listing's stored URL (Criterion direct, TMDB's watch page for provider-fed services). | TMDB-fed listings hold only `themoviedb.org/movie/<id>/watch`, never a service URL. Alternatives rejected: listing URL only (lands on TMDB, not HBO Max); templates in code (breaks "the registry owns service facts", migration 017's rule). |
| D8 | External links row: Criterion (when a listing URL exists), TMDB (plain "TMDB ↗", when a tmdb id exists), CheapCharts. The Metacritic link leaves the drawer; `FilmView.metacritic_url` stays in the API. | 4,841 films hold a tmdb id. `metacritic_url` is pinned by `test_api.py` and is the discovery film's identity link; only its drawer button goes. |
| D9 | Drawer width 760px, up from 560px. | Fits the poster beside a p90 overview without the text wrapping under it. |
| D10 | Credits and overview are detail-only: `/api/films/<id>` returns them beside `payload`; `/api/films` (the table payload, loaded on every page view) does not grow. `best_source` gains a `url` key; `services` entries do not. | 14,717 listings × ~60-char URL ≈ 1 MB on the list payload if `services` carried URLs. |

## 3. Layout (top to bottom)

1. Title, watchlist ★ and revisit ⚑ toggles, revisit note, audit block — unchanged.
2. `Year · Director` — director is a person link.
3. Poster floated right; summary paragraph (D1).
4. Facts `<dl>`: Genre, Runtime, Rated, Country, Language, Awards (OMDb, as now), then **Cast** and **Writer** rows (D2, D3).
5. **Ratings block** (D5), visually separated (rule above and below):
   - `My rating: [ 9 ]` — the existing `input.rating`, same handler.
   - `IMDb 7.9 · Metacritic 86 · Rotten Tomatoes 96%` — each omitted when null; the line is omitted when all three are null, replaced by the existing "OMDb lookup pending." / "No OMDb match." notes.
   - `On lists: Slant: Film Noir #3, BFI: Film Noir #17 · canon score 9.8` — the existing line, plus the score (one decimal) computed by the `canonScore` already in `app.js`. Omitted when the film is on no list.
6. **Watch line** (D6): `Watch on **HBO Max ↗**` linking to `best_source.url`; "(not subscribed)" suffix as today. Owned: `Owned on Apple TV ↗`. Omitted when `best_source` is null.
7. New on / Also streaming on / Buy on — unchanged.
8. External links (D8): `Open on Criterion ↗` · `TMDB ↗` · `CheapCharts ↗` / `Find on CheapCharts ↗`.
9. Raw OMDb payload disclosure, Leaving line — unchanged.

### Cast row

- Enriched film: six names, comma-separated, each an `a.person` link with `data-field="actor"` and `data-name`. When more than six: `⋯ N more` opens a `<details class="cast-more">` (the `svc-more` pattern) whose body is a `<ul class="cast-full">` of **every** cast entry (including the first six) as `<a.person>Name</a> as Role`, two CSS columns, roles as stored (`(uncredited)` suffixes survive). An empty `character` prints the name alone.
- No credits (never enriched): OMDb's `Actors` split on `, `, each a bare-query link, no disclosure.
- No credits and no OMDb actors: row omitted.

### Writer row

- Enriched film: entries in credit order; one per person. A person whose jobs include Screenplay or Writer prints bare; otherwise `Name (job)` with the job lowercased, multiple jobs joined with `/`. Each name a link with `data-field="writer"`.
- Fallback: OMDb's `Writer` string split on `, `, its parenthetical suffixes kept as text, each name a bare-query link.

### Director link

- The link text stays `FilmView.director` (what the table shows). The query uses the TMDB Director credit's name when one exists (quoted), else the display text bare.

## 4. Data and code changes

### Domain

- `domain/watch.py::watch_url(option, title) -> str | None`: `option["search_url"]` with `{title}` replaced by the URL-encoded title when set and non-empty, else `option["listing_url"]`, else `None`. Pure, unit-tested.
- `domain/models.py`: `ServiceMeta` gains `search_url: str | None`. New `FilmCredits` dataclass: `director: str | None`, `cast: list[CastEntry(name, character)]`, `writers: list[WriterEntry(name, label)]`. The writer label (bare vs parenthesised, D3) is computed once, server-side, by a pure `domain/credits.py::writer_label(name, jobs) -> str`, so there is one implementation; the API ships `{name, label}` and JS renders `label`. Cast ships `{name, character}` raw; the "as" joining is display and lives in JS.
- `FilmView.best_source` dict gains `url` (from `watch_url`). `FilmView.services` entries are unchanged (D10).

### Infrastructure

- Migration `021_service_search_url.sql`: `ALTER TABLE movie_service ADD COLUMN search_url TEXT;` (NULL default, inert), inside BEGIN/COMMIT, inserts `schema_version` 21.
- `_SERVICE_SELECT` and `_SERVICES_SQL` read `search_url`; `_SERVICES_SQL` also reads `l.url AS listing_url`. `_services_by_film` keeps both on the option dicts it hands the ranking; `_row_to_view` strips `search_url` and `listing_url` from the public `services` list after `best_source` is computed. The Criterion option's `listing_url` is the view's own `url`; the store option's is `None` (the owned link is the Apple TV search template, which the owner sets on `apple-tv-store` like any other service; until set, the drawer keeps today's hardcoded `tv.apple.com/search` fallback for owned films).
- `Repository.set_service_search_url(slug, template) -> bool`: the ONLY writer, through `_set_service_column`; empty string stores NULL.
- `Repository.credits_for(film_id) -> FilmCredits | None`: one query over `film_credit JOIN person`, cast ordered by `ord`, writers = `department = 'Writing'` ordered by `ord`, director = first `job = 'Director'` by `ord`. None when the film has no credit rows.
- `Repository.overview_for(film_id) -> str | None` from `film_text`.

### Web

- `GET /api/films/<id>` adds `credits` (dict or null), `overview` (string or null), `tmdb_url` (`https://www.themoviedb.org/movie/<id>` from `external_ids_for(id).get("tmdb")`, or null).
- `app.js::detailHtml` renders §3. A delegated click handler on `#drawer-body a.person`: prevent default, close the drawer through `closeDrawer()`, then set `state.q` to the field query, mirror it into `#search`, clear `data-settled`, `syncUrl`, `runSearch()` — the correction-chip path. **Ordering hazard:** `closeDrawer()` walks history back when the open pushed an entry, and the resulting `popstate` re-reads state from the URL; the query must be applied after that restore completes, or it is wiped. The plan owns this sequencing and a Playwright test pins the final URL (`q=` present, no open film).
- `app.css`: drawer width `min(760px, 100vw)`; `.ratings` block rules; `.cast-full` two columns; `.cast-more` reuses `.svc-more` styling.

### CLI

- `movie-brain services url SLUG [TEMPLATE]`: show one service's template, or set it; a template that does not contain `{title}` exits 2; the literal `-` clears it. `services list` appends the template when set. CLAUDE.md's `services` line gains the verb.

## 5. Tests

- Unit: `watch_url` (template wins, listing fallback, none, encoding of `&` and spaces); `format_writer` cases (Screenplay bare, Novel tagged, both jobs → bare, two non-screenplay jobs joined); `credits_for` ordering and the writer dedup; `set_service_search_url` is the only writer (the sync's `register_provider` leaves it alone).
- API: detail carries `credits`, `overview`, `tmdb_url`; list payload has no `url` key in `services` entries; `best_source.url` follows the template.
- Playwright (`tests/web/test_dashboard.py`): section order (ratings block between Writer and the watch line); inline cast is six names without roles; opening "⋯ N more" lists every entry with roles; clicking a cast name closes the drawer, fills the bar with `actor: "Name"`, filters the table, and leaves a set chip alone; director link; TMDB link present and no Metacritic link; watch link text and href with and without a template; owned film shows the Apple TV link.
- Fixture (`tests/web/conftest.py`): Alpha gains eight cast rows (so the disclosure appears at 6) and two Writing credits (one Screenplay, one Novel); one service gets a `search_url` and one does not. The plan states the exact rows and the expected strings.

## 6. Out of scope

Trailer links and critic-review links (backlog 4's other halves); per-title presentation quality; hand-collecting the templates themselves (the owner runs `services url` once per subscribed service after merge; until then the watch link falls back to the listing URL); any change to the table, chips or list picker.

## 7. Documentation

CLAUDE.md: the drawer paragraph, the `services` command line, the migration count; `.claude/rules/watch.md`: `search_url` as the fourth owner column and `watch_url`; `docs/backlog.md`: close 14, update 4.
