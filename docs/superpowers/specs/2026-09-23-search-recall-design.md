# Search recall — design

*2026-09-23. Owner ask, in three steps in one conversation: "a stemmer is worth doing", then "let's do all three". Backlog 41 (stemmer), 42 (meaning adds films), 43 (stronger model). Follows the power-search spec (`2026-09-06-power-search-design.md`) and its Plan C semantic spec (`2026-09-06-power-search-c-semantic-design.md`, D14–D21), which this supersedes on D16 and D18.*

## 1. The two test cases

The owner typed two things into the bar and got less than the data held.

| query | got | the data held |
|---|---|---|
| `time loops` | 3 films, Groundhog Day absent | Groundhog Day's OMDb plot says "finds himself in a time loop"; its TMDB keywords include `time loop` |
| `dystopian` | 9 films | the TMDB keyword `dystopia` sits on 72 films; `dystopia` typed instead returned 73 |

Measured 2026-09-23 against the live catalogue (5,052 vectors, all-MiniLM-L6-v2):

- `time loops` found no word (the prose index has no stemmer, so "loops" ≠ "loop"), so the semantic stage supplied the result alone under the fixed 0.6 distance cut: three films. Groundhog Day was fifth at 0.647. `time loop` (singular) was a word hit and Groundhog Day came third.
- `dystopian` found nine literal prose hits, and by the Plan C rule (D16) a non-empty word set means meaning only re-orders — it never adds. The 72 tagged films were never considered. "dystopian" does not reach the keyword "dystopia" because the keyword match is an exact string.
- Even "a man relives the same day over and over", nearly the overview's own words, put Groundhog Day ninth at 0.618 behind Dark City and Night Games. The small model embeds the whole paragraph; the weatherman, producer, cameraman and Punxsutawney dilute the loop.

Three gaps, three fixes, ordered by cost. The owner chose all three.

## 2. Decisions

**D1 — Stem both word stages (backlog 41).** The prose index `film_text_fts` is left unchanged on `unicode61`; only the keyword index is Porter (reconsidered per §5 and dropped 2026-09-23, owner ruling): on a migrated copy with prose Porter reverted, verbatim recall@10 was 0.686 (0.627 with it, baseline 0.705) and plural 0.855 (0.676), and `time loops` and `dystopian` still hit through the keyword index and ladder — prose Porter widened prose hits (`hypnotism` → `hypnot` → "hypnotic") and raw −bm25 prose scores (7–12) outrank W_TAG 3. The keyword table gets its own Porter index (D2). Measured before writing this: SQLite's Porter unifies `loops`/`loop`, `vampires`/`vampire`, `robots`/`robot`, `haunting`/`haunted` — but NOT `dystopian`/`dystopia` (nor `utopian`/`utopia`): Porter has no `-ian` rule. So stemming alone fixes the first test case and not the second; D2's second half exists for that.

**D2 — Keywords are matched through their own FTS5 table, plus the ladder the `keyword:` field already has.** `film_keyword_fts` is a standalone FTS5 table `(film_id UNINDEXED, keyword)` with `tokenize = 'porter unicode61'`, filled by migration 030 and kept in step by triggers on `film_keyword` (insert/delete; the table is never updated in place). It is standalone rather than external-content because `film_keyword` has a composite primary key and no `INTEGER PRIMARY KEY`, so its rowids are not stable across VACUUM — the 43k short strings cost nothing to duplicate. The `keyword:` field and the freeform keyword signal both match the typed phrase against it (`MATCH '"…"'`, a stemmed phrase), so `loops` reaches `time loop` and `vampires` reaches `vampire`. For the forms Porter cannot unify, the freeform signal ALSO runs the fuzzy ladder the `keyword:` field runs today (`rank_candidates` over the vocabulary), at a stricter floor `FREEFORM_KEYWORD_FLOOR` = 0.9 rather than `CORRECTION_FLOOR` 0.8: measured, `dystopian` → `dystopia` 0.94, `time loops` → `time loop` 0.95, `vampires` → `vampire` 0.93 pass, while `dystopian future` → `distant future` at exactly 0.80 (a wrong match) is refused. Cost measured at ~125 ms per query over 11,949 keywords; the `keyword:` field pays the same today and the bar debounces 300 ms. Python never stems; SQLite does.

**D3 — Meaning ADDS films; it never only re-orders (backlog 42).** D16's two modes become one: the semantic stage always computes the nearest films and unions them with the word hits. Word hits keep their lexical score plus the semantic bonus as today; a film reached by meaning alone carries `SEMANTIC_WEIGHT × (1 − distance)` and no lexical score, so it always ranks below any word hit (the bonus ≤ 5 cannot pass a title hit at 10, D17 unchanged). The hint changes wording: `"{n} more by meaning"` when words found something, the existing `"no exact match — showing the {n} closest by meaning"` when they did not. Amended 2026-09-23 (owner): additions are suppressed when any word hit is a title hit (`Repository.title_hits`), because ten films by meaning under a title search read as noise and mix in under a column sort (the sort replaces the search order in `app.js`).

**D4 — The net is a count, not a distance.** `MAX_DISTANCE` 0.6 is replaced by `SEMANTIC_NEAREST` = 10: the ten nearest films, whatever their distance, subject to a loose sanity ceiling `SEMANTIC_CEILING` = 0.8 that only excludes films the model calls unrelated. Reason: measured distances for short queries cluster in 0.5–0.7 for the current model and shift with any model change, so an absolute cut is a dial that has to be re-tuned per model, while "ten nearest" means the same thing under every model. No owner-facing control (D18 stands).

**D5 — Field filters still intersect.** A film supplied by meaning must pass every field filter in the query, exactly as supply mode does today (`only: …`, `year: …`, `director: …` narrow the meaning set too).

**D6 — The model is a parameter, and a change re-embeds (backlog 43).** Today `EMBED_MODEL` / `EMBED_DIM` in `domain/search.py` are read as globals by `pack`/`unpack`, `embed_films` and `VectorIndex`'s reshape, so a second model cannot be tried without editing them. They stay the ONE configured pair, but every reader takes `model` and `dim` as parameters defaulting to them, so the benchmark can embed a database COPY with another model without touching code. What already holds and stays: `films_needing_embedding(model)` re-selects every film whose row was written by another model; `all_embeddings(model)` / `embedding_stamp(model)` load one model's rows only, so a half-finished re-embed degrades to fewer neighbours, never wrong distances. Consequence to know: `embed` is in the catch-up chain, so once the constants change the NEXT sync re-embeds all 5,052 films on its own (an hour of CPU) — the live re-embed is therefore run by hand right after the constant change, behind the owner's "proceed", not left to the nightly tail.

**D7 — The candidate model is `all-mpnet-base-v2`** (768 dims, ~420 MB, the same sentence-transformers family, so no new dependency). It is adopted ONLY if the benchmark in §3 shows it beats MiniLM on the keyword benchmark after D1–D5 are in; otherwise the constant stays and the plan's last task is recorded as "measured, declined". A typeahead latency check is part of the decision: encode of one short query must stay under 50 ms warm on the owner's machine (MiniLM measured well under that).

**D8 — The benchmark is data we already hold.** ~300 TMDB keywords held by 3–30 films each (3,358 qualify) are the queries; the tagged films are the answers. Score per setting: hit rate (at least one tagged film in the result) and recall@10 (share of tagged films in the top ten). Two named rows beside the aggregate: `time loops` → Groundhog Day (#4850) and `dystopian` → the 72 `dystopia` films. The benchmark is a script under `scripts/`, run against a COPY of the live database, never the live one, and never in the test suite (it needs the real model).

## 3. Sequence and gates

1. Benchmark script + baseline run (today's code) — the number to beat, recorded in the plan's trial log.
2. D1 + D2 (stemmer, keyword index, freeform keyword ladder) — re-run; expected: `time loops` finds Groundhog Day by the word, `dystopian` goes from 9 to ~73 through the ladder, hit rate rises.
3. D3 + D4 + D5 (meaning adds, ten nearest) — re-run; expected: `time loops` row shows Groundhog Day, recall@10 rises, hit rate not worse.
4. D6 (model as a setting, re-embed on change) — no behaviour change with the constant untouched; tests only.
5. D7 — re-embed a database COPY with mpnet, re-run; adopt or decline on the numbers plus the latency check. Live re-embed only after "proceed".

Each step is its own commit; the benchmark numbers go in the plan's trial log, not the commit message.

## 4. Out of scope

- An owner-facing distance or count control (D18 stands).
- A different tokenizer for names (`person_fts`, `character_fts` stay trigram).
- Stemming languages other than English (Porter is English; original titles are not in the prose index anyway).
- Query expansion by synonyms; the badge-the-searched-service idea from the same conversation; the reverted `only:` field.

## 5. Risks

- Porter over-stems (`organization` → `organ`); the benchmark's hit rate will show whether precision suffers on prose. If it does, the keyword table keeps Porter (short phrases, low risk) and the prose index is reconsidered.
- Union mode puts ten meaning-only films under every word search. They rank last and the hint says so; if the owner finds them noise, `SEMANTIC_NEAREST` is the one dial.
- A model switch is a one-hour re-embed of 5,052 films on CPU and a 420 MB download shared with nothing (MiniLM's cache is shared with yt-brain; mpnet's would not be). Declining it costs nothing.
