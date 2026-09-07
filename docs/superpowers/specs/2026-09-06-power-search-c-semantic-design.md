# Power search Phase 2 — semantic search over prose

**Status:** design approved in conversation 2026-09-06 (six questions, five sections); awaiting owner review of this written form. Child of `2026-09-06-power-search-design.md` §12, D2, D6, D13.
**Prior art:** yt-brain (`application/embed.py`, `infrastructure/database.py::search_similar`, `web/dashboard.py::api_search`), read from a fresh clone on 2026-09-06. What was taken and what was refused is in §10.
**Evidence:** a throwaway spike run 2026-09-06 against the live catalogue, read-only (§1). Nothing from it is kept.

## 0. What this is

Phase 1 answers every exact and fuzzy query in the parent spec's attribute catalogue. It cannot answer the owner's own example, in the owner's words: "if I do hard boiled San Francisco private investigator, that should do a semantic search on description or plot or more verbose, full concept and sentence fields." Today that query returns nothing, because freeform words are ANDed lexically across `film_text_fts` and no overview contains all five. This spec adds the third search class the parent spec named and left unbuilt: **semantic — prose; meaning, not string** (§3.3 there). It embeds each film's prose once, embeds the query at search time, and uses cosine distance as a fourth stage behind the three that exist. The `/api/search` contract does not change (D13). Without the optional extra installed, search behaves exactly as it does today.

## 1. Measurements the design rests on

All from the live DB at schema 18 on 2026-09-06, `all-MiniLM-L6-v2` via sentence-transformers, prose = overview + plot + tagline.

| Measurement | Value |
|---|---|
| Films (not disposed) | 4,645 |
| Films with a `film_text` row (prose) | 4,569 — 4,561 with an overview, 4,377 with a plot, 2,188 with a tagline |
| Mean / max prose length | 435 / 1,260 characters — every film fits the model's 256-token window in one pass |
| Encode the whole catalogue | 1.6 s on this machine (0.3 ms per film); the model is already in `~/.cache/huggingface` from yt-brain (88 MB) |
| Import sentence-transformers + load model | 4.9 s cold |
| Encode one query, warm | 7 ms |
| Brute-force cosine, 4,645 × 384 float32 | **0.08 ms per query with numpy** (7.1 MB matrix); 43 ms in pure stdlib |
| Owner's query, prose only | The Maltese Falcon #1 (distance 0.527), The Big Sleep #2 (0.565), Chinatown #10; 7 films within 0.6, 67 within 0.7 |
| Same query, title prepended to the prose (yt-brain's text shape) | *Hard Boiled* (1992, a Hong Kong cop film) #1 by string luck; Maltese Falcon drops out of the top eight |
| `hard boiled private eye`, prose only | Farewell, My Lovely #1, Chinatown #2, Maltese Falcon #30, Big Sleep #17 — 2 films within 0.6 |
| `lonely samurai wanders japan`, prose only | Seven Samurai, Samurai I, Three Outlaw Samurai, Samurai Rebellion, Ronin Gai — all within 0.45 |

Three consequences. **sqlite-vec is unnecessary** (D14): a tenth of a millisecond for brute force means a virtual table that must be loaded on every `Repository` open buys nothing and costs a failure mode. **The title is not embedded** (D15): it is already the heaviest lexical signal, and inside the vector it rewards string coincidence. **The model rewards specific nouns over genre slang**: descriptive queries are strong, three-word slang is weak. The spec states the limit rather than tuning around it.

## 2. Decisions

The parent spec's D1–D13 stand. New:

| # | Decision | Why |
|---|---|---|
| D14 | **A plain BLOB table read once into a numpy matrix; no sqlite-vec, no virtual table** | 0.08 ms per query brute force (§1). sqlite-vec would need the extension loaded on every connection and a degradation path when the extra is absent; a BLOB is just a column |
| D15 | **Embed overview + plot + tagline; never the title; films with no prose row are not embedded** | Title-in-vector put *Hard Boiled* (1992) first on the owner's query (§1). A film with no prose stays reachable lexically and by every field; embedding its title alone would be D15's failure with nothing to redeem it |
| D16 | **Two modes, chosen by whether the lexical set is empty** | The parent's "re-orders the surviving id set" cannot answer the owner's own query, whose surviving set is empty. Non-empty: semantic re-ranks and adds nothing. Empty with freeform text: semantic supplies the candidates, still intersected with every field filter over the whole catalogue (D6), and the hint line says so. The bar never quietly widens a result that had members |
| D17 | **In re-rank mode semantic is one more SUMMED signal, not a replacement order** | Parent §8: every signal that matches is summed, title-weighted, never a precedence. A pure re-order by distance would demote the title hit on `big sleep` beneath films about sleeping. `SEMANTIC_WEIGHT` 5 × (1 − distance) inside the floor keeps a title hit (10) first and reorders the prose hits beneath it |
| D18 | **One constant distance floor, `MAX_DISTANCE` 0.6; no slider, no top-N cap** | Owner decision 2026-09-06 (option 1 of 3): fewer controls. yt-brain's default; 7 films on the owner's query. Lives in `domain/search.py` beside the other thresholds; the hint carries the count so the user sees the floor working |
| D19 | **Optional extra `semantic = [sentence-transformers, numpy]`; absence degrades to Phase 1 exactly, plus one install hint** | Four runtime deps today; Plan B added none. The embedder is injected (`create_app(repo, embedder=None)`), so the core never imports torch |
| D20 | **The model loads lazily on the first semantic query; the vector matrix loads lazily on the first query and refreshes when the table changes** | 4.9 s import-plus-load would tax every dashboard start and every test that builds the app. yt-brain preloads; here the first semantic query pays once |
| D21 | **`movie-brain embed [--apply]` on the `enrich credits` pattern; never in sync; a re-enriched film re-enters the worklist** | Manual by choice. Worklist = prose and no row for `EMBED_MODEL`, or `credits_fetched_on` newer than `embedded_on` (the prose changed) |

## 3. Data model — migration 019

```sql
CREATE TABLE film_embedding (
    film_id     INTEGER PRIMARY KEY REFERENCES films(id),
    model       TEXT    NOT NULL,           -- 'all-MiniLM-L6-v2'
    dim         INTEGER NOT NULL,           -- 384
    vector      BLOB    NOT NULL,           -- dim × float32, little-endian, L2-normalised
    embedded_on TEXT    NOT NULL            -- ISO date
);
INSERT INTO schema_version (version, applied_on) VALUES (19, date('now'));
```

One row per film per model — `model` is a column, not part of the key, because a model change is a full re-embed and two models never coexist. Vectors are stored **normalised** so cosine is a dot product. The blob is `struct.pack("384f", …)`, yt-brain's `_to_blob` byte for byte, so a vector from either project reads in the other. `film_embedding` joins `_ONE_ROW_TABLES` in `merge_film`: the survivor's row wins, the loser's is dropped and recorded as `{"film_id": loser}` in the disposition note like `omdb`/`tmdb`. Nothing here is identity: no `KEY_AUTHORITY`, no `external_ids`, no keying or matching code is touched.

## 4. What is embedded

`domain/search.py::embedding_text(overview, plot, tagline) -> str | None` — pure. The three fields, each stripped, non-empty ones joined by a single space in that order; `None` when all three are empty, and a film whose text is `None` is never embedded (D15). No title (D15), no cast, no keywords, no genre — those are exact fields already and would only add string coincidence. The order matters only for determinism; the model reads the whole text in one 256-token window (§1 max 1,260 characters).

## 5. Execution — the fourth stage

Parent §8's three stages stand: parse, resolve, filter-and-rank (`search_films` returns `[(film_id, score)]`). Stage 4 runs in `application/search.py::run_search(repo, text, index=None)` when `index` is given AND `parsed.free.strip()` is non-empty. A query of fields alone (`actor: bogart`) never reaches stage 4: an exact set has nothing to rank by meaning and stays unranked.

**Re-rank mode (lexical set non-empty).** The query is embedded once; `index.distances(query_vector, ids)` returns each surviving film's distance (films without a vector get none). Each film's lexical score gains `SEMANTIC_WEIGHT × (1 − distance)` when `distance ≤ MAX_DISTANCE`, else nothing (D17). Ids are re-sorted by the summed score. Nothing is added, nothing is dropped, `ranked` is true as before, no hint.

**Supply mode (lexical set empty).** The query is embedded once; `index.nearest(query_vector, MAX_DISTANCE)` returns `[(film_id, distance)]` ascending, over the whole catalogue. If the query has field terms, `search_films(filters, free="")` is asked for the exact set those filters alone produce, and the nearest list is intersected with it — the field filter stays a filter over the whole catalogue, never a post-filter over a top-N (D6). Ordered by distance; `ranked` true; hint `no exact match — showing the N closest by meaning` where N is the final count. An empty supply keeps today's hints (`no film matches all N words…`, now gated on `not parsed.terms` since 2d2bfaa).

**Without the extra (`index is None`).** Stages 1–3 exactly as today. One addition: when the lexical set is empty and `parsed.free` is non-empty, the hint `semantic search is not installed — uv sync --extra semantic` is appended so the owner knows the bar could have done more. That hint never appears when the extra is installed but the model or table is absent — those cases are §8.

**Contract.** `GET /api/search?q=` still returns `{q, ids, ranked, corrections, suggestions, hints, total}` (D13). `app.js` changes nothing: it already intersects `ids`, ranks when `ranked`, and prints `hints`. `/api/config` gains nothing — the client does not need the floor.

## 6. Code placement (hexagonal)

- `domain/search.py` — constants `EMBED_MODEL = "all-MiniLM-L6-v2"`, `EMBED_DIM = 384`, `MAX_DISTANCE = 0.6`, `SEMANTIC_WEIGHT = 5.0`; pure `embedding_text`. Imports nothing new; numpy never enters the domain.
- `infrastructure/embeddings.py` — `Embedder` protocol (`encode(texts: Sequence[str]) -> list[list[float]]`, normalised); `SentenceTransformerEmbedder` (lazy: imports and loads on first `encode`, D20; raises `SemanticUnavailable` when the extra is missing); `pack`/`unpack` (struct, `EMBED_DIM` floats); `VectorIndex(repo, embedder)` holding the numpy matrix plus its id list, built on first use from `repo.all_embeddings(EMBED_MODEL)`, refreshed when `repo.embedding_summary()` (count, max `embedded_on`) differs from the one it was built from; `nearest(vector, floor)`, `distances(vector, ids)`. numpy is imported inside this module only.
- `infrastructure/database.py` — `films_needing_embedding(model, limit)` (D21's worklist), `write_embeddings(rows, today)` (one transaction per batch), `all_embeddings(model)`, `embedding_summary()`; `_ONE_ROW_TABLES` gains `film_embedding`.
- `application/embed.py` — `embed_films(repo, embedder, today, *, apply, limit, batch_size=128, log)` → `EmbedReport(scanned, embedded, skipped_no_prose)`; dry run prints the worklist size; mirrors `enrich_credits` minus the network pacing (no network here after the model is cached).
- `application/search.py` — `run_search(repo, text, index=None)`; stage 4 as §5.
- `web/app.py` — `create_app(repo, today=…, embedder=None)`; the app builds a `VectorIndex` when an embedder is given and passes it to `run_search`. `cli.py dashboard` constructs `SentenceTransformerEmbedder()` and passes it always — the lazy adapter makes the missing extra a `None` index at first query, not a start-up failure.
- `cli.py` — `movie-brain embed [--apply] [--limit N]`; `status` gains one line, the `film_embedding` count against the prose count, so the owner can see whether an `embed --apply` is due.
- `pyproject.toml` — `[project.optional-dependencies] semantic = ["sentence-transformers>=3.4", "numpy>=1.26"]`; mypy already has `ignore_missing_imports = true`.

## 7. The verb

```
uv run movie-brain embed [--apply] [--limit N]
```

Dry run by default: prints how many films the worklist holds and how many films have no prose and will never be embedded. `--apply` encodes in batches of 128 (`embedding_text` per film, `embedder.encode`, `write_embeddings`), one transaction per batch, stamping `embedded_on` today; a run interrupted at batch k resumes at k+1 because stamped rows leave the worklist. `--limit` caps the worklist, as `enrich credits` does. The first `--apply` on the live DB is one owner-confirmed step (`one-at-a-time`), expected under a minute including model load. Never in sync (D21).

## 8. Degradation

| Situation | Behaviour |
|---|---|
| Extra not installed | Phase 1 exactly; the install hint on an empty freeform result (§5) |
| Extra installed, model not cached, offline | `SentenceTransformerEmbedder.encode` raises `SemanticUnavailable`; the app logs once and treats the index as `None` for the rest of its life. `embed --apply` exits 2 with the message |
| Extra installed, `film_embedding` empty | `VectorIndex` is empty; stage 4 finds nothing to add or re-rank; result is Phase 1's. No hint — `embed` is the owner's manual step, and `status` reports the count |
| Film without prose | Never embedded; lexical and field search unchanged for it |
| Film re-enriched after embedding | Re-enters the worklist (D21); its old vector serves until the next `embed --apply` |
| `EMBED_MODEL` changed | Every film re-enters the worklist; old rows are overwritten on `--apply` (PRIMARY KEY on `film_id`) |

## 9. Testing

- **`FakeEmbedder`** in `tests/` — deterministic bag-of-words vectors over a fixed vocabulary (each word one dimension, L2-normalised, padded to `EMBED_DIM`), so "private eye" and "private detective" share a dimension and "hospital" shares none. Real code everywhere else: the real `VectorIndex`, the real `run_search`, the real repository.
- **Unit** (`tests/unit`): `embedding_text` (order, stripping, all-empty → `None`); `pack`/`unpack` round trip and yt-brain byte compatibility (a known `struct.pack("384f")` blob); `VectorIndex.nearest` respects the floor and ordering; `distances` returns none for a film without a vector; refresh when the summary changes.
- **Scenarios** (`tests/features/search.feature`, on the Alpha/Beta/Gamma corpus with `FakeEmbedder`): semantic supplies candidates when the lexical set is empty, ordered by distance, with the "closest by meaning" hint; a field filter still narrows that supply (D6); a title hit stays first under re-rank (D17); a query of fields alone is not re-ranked; no index means today's result plus the install hint; a film without prose is never embedded and is still found by its field.
- **Verb** (`tests/step_defs/test_embed.py`): dry run writes nothing; `--apply` stamps and is resumable; a re-enriched film re-enters the worklist; the merge moves the row survivor-wins.
- **Web** (`tests/web`): `/api/search` shape unchanged with and without an embedder.
- **One `@pytest.mark.semantic` test** runs the real model on three sentences and asserts only that the two about detectives are closer to each other than to the third; skipped when the extra is not importable. Nothing else in the suite imports torch, so `uv run pytest` stays at about five seconds.

Carry the parent session's lesson: every plan defect it found was a test fixture that could not exercise the band it claimed. The `FakeEmbedder` vocabulary must be checked against each scenario's words before the plan is cut.

## 10. From yt-brain — taken and refused

**Taken:** the model (`all-MiniLM-L6-v2`), the 384-float `struct` blob, batch encoding, a `_text_search`-style fallback when the model is absent, the 0.6 distance default.

**Refused, on purpose:** sqlite-vec (D14; `_load_sqlite_vec` on every connection plus `_VEC_MIGRATIONS` special-casing, for nothing brute force cannot do at this size); title in the embedded text (D15); post-filtering field terms over a semantic top 5×limit (D6, the parent's founding refusal — here the field set is computed exactly and intersected); the distance slider (D18); preloading the model at app start (D20); regex field parsing inside the route (the parser is Phase 1's pure domain module).

## 11. Out of scope

Person biographies, reviews, translations (parent D12). Hybrid score fusion beyond D17's single summed term. A second model or re-ranker. Embedding the query's field values. Any change to `app.js`, the chips, the scope toggle or the list picker. Any change to keying, matching or the thumbprint resolver.

## 12. Known limits

Prose exists only for enriched films (Phase 1's documented limit, inherited). Three-word genre slang ranks weakly (§1: `hard boiled private eye` puts The Maltese Falcon 30th); descriptive queries rank well. The floor is a constant; if the owner's usage shows it too tight or too loose the change is one number in `domain/search.py` and a re-measure of §1's table, not a control.
