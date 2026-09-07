# Power Search — Plan C: semantic search over prose

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `hard boiled San Francisco private investigator` return The Maltese Falcon and The Big Sleep — a fourth search stage that ranks and, when the lexical set is empty, supplies films by the meaning of their prose — behind an optional extra, with the `/api/search` contract unchanged.

**Architecture:** Migration 019 adds `film_embedding`, one 384-float BLOB per film. `movie-brain embed --apply` encodes overview + plot + tagline (never the title) through an injected `Embedder`, resumable by stamp, never in sync. `infrastructure/embeddings.py` holds the `Embedder` protocol, the lazy sentence-transformers adapter, blob packing and a `VectorIndex` that brute-forces cosine over a numpy matrix loaded once (0.08 ms per query, measured). `run_search` gains stage 4 in two modes: re-rank as one more summed signal when the lexical set has members; supply candidates within `MAX_DISTANCE`, intersected with the exact field set, when it is empty. Without the extra, everything is exactly today plus one install hint.

**Tech Stack:** Python 3.12, SQLite (stdlib), Flask, Typer, pytest + pytest-bdd. Optional extra `semantic`: `sentence-transformers` (all-MiniLM-L6-v2, already cached from yt-brain) + `numpy`. `numpy` also joins the dev group so the `VectorIndex` is tested by the normal suite with a fake embedder; torch is never imported by the suite.

**Spec:** `docs/superpowers/specs/2026-09-06-power-search-c-semantic-design.md` (D14–D21, §3–§9). Parent: `docs/superpowers/specs/2026-09-06-power-search-design.md` (§8, D6, D13).

## Global Constraints

- **No new REQUIRED runtime dependency.** `[project] dependencies` stays `typer`, `rich`, `flask`, `requests`. `sentence-transformers` and `numpy` live under `[project.optional-dependencies] semantic`; `numpy` also under the `dev` group (spec D19).
- **Schema change = new numbered migration** `migrations/019_embeddings.sql` wrapped in `BEGIN/COMMIT`, inserting its own `schema_version` row exactly as `018_credits.sql` does (`INSERT INTO schema_version (version) VALUES (19);`). Never edit an applied migration. `movie-brain migrate --apply` is the only path that advances the live DB (CLAUDE.md).
- **Nothing here is identity.** No `KEY_AUTHORITY`, no `external_ids`, no change to keying, matching, the thumbprint resolver, `films.guid` (spec §3, §11).
- **Every film read model carries the `_NOT_DISPOSED` guard** — the worklist and `all_embeddings` use it exactly as `films_needing_credits` does.
- **`merge_film` must move every film-scoped table** — `film_embedding` joins `_ONE_ROW_TABLES` (survivor wins, loser's `film_id` noted) (spec §3).
- **The title is never embedded** (D15). `embedding_text` takes overview, plot, tagline and nothing else.
- **Field filters are exact filters over the whole catalogue, never a post-filter over a semantic top-N** (parent D6). Supply mode intersects with `search_films(filters, "")`, the exact set.
- **The `/api/search` response shape does not change** (parent D13): `{q, ids, ranked, corrections, suggestions, hints, total}`. `app.js` is not touched.
- **Dry run writes nothing.** `embed` without `--apply` never calls the embedder and the database is byte-identical afterwards (spec §7).
- **Embedding is never run by `sync`** (D21; memory: syncs are manual by choice).
- **The suite never imports torch.** Only the one `@pytest.mark.semantic` test does, and it skips when the extra is absent (spec §9).
- **Constants live in `domain/search.py`:** `EMBED_MODEL = "all-MiniLM-L6-v2"`, `EMBED_DIM = 384`, `MAX_DISTANCE = 0.6`, `SEMANTIC_WEIGHT = 5.0` (D18). Hint copy, verbatim: `no exact match — showing the {n} closest by meaning` and `semantic search is not installed — uv sync --extra semantic`.
- **Markdown prose is never hard-wrapped** (owner's global rule) — applies to Task 7's doc edits.
- **Commit messages:** one line, the *why*, plus the two trailers used on this branch (`Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_017AZb57CHEGYwXATffrFjBR`).
- **`uv run` only.** Never bare `python`/`pytest`.
- Work on branch `feature/power-search-c-semantic` off `main`. Never stage `scripts/eval/thumbprint_eval_v1.csv` or `docs/raw/` if they show as dirty.
- **Every live-DB step is a separate owner yes** (`one-at-a-time`): `migrate --apply` and `embed --apply` in Task 7 each wait for one.

---

## The fake embedder — read this before any task that searches

Every plan defect the parent session found was a test fixture that could not exercise the band it claimed, so the fixture is designed here, once, and its arithmetic is shown. `FakeEmbedder` (Task 3, in `tests/conftest.py`) is a bag-of-concepts embedder: a word listed in `CONCEPTS` adds 1.0 to its concept's dimension, any other word adds 1.0 to a `crc32`-chosen dimension of its own, stopwords are dropped, the vector is L2-normalised to `EMBED_DIM`. Distance is `1 − dot`.

The search corpus (`tests/step_defs/test_search.py`) after Task 5's one change (Beta gains an OMDb plot):

| Film | Embedded text | Vector (concept dim: count) | Norm |
|---|---|---|---|
| Alpha | `A private eye. Sternwood.` | detective:2 (private, eye), sternwood:1 | √5 |
| Beta | `A nurse in the alpha ward. Alpha shift.` | care:2 (nurse, ward), alpha:2, shift:1 | 3 |
| Gamma | no `film_text` row | never embedded | — |

Queries the scenarios use, with the distances the fake produces:

| Query | Alpha | Beta | Why it is chosen |
|---|---|---|---|
| `gumshoe sleuth` | 1 − 4/(√5·2) = **0.106** | 1.0 | lexically empty (no word in any title/prose/name/keyword); near Alpha only |
| `gumshoe caregiver` | 1 − 2/(√5·√2) = **0.368** | 1 − 2/(3·√2) = **0.529** | both inside 0.6, distinct, Alpha first — proves ordering by distance |
| `alpha` | 1.0 (no bonus) | 1 − 2/3 = **0.333** → bonus 5 × 0.667 = 3.33 | lexical: Alpha by title (10+), Beta by prose (~3). A pure re-order would put Beta first; a summed signal keeps Alpha first. This is the test that bites |

`hospital` is Beta's keyword and `alpha`/`private`/`eye` appear in prose, so none of them may appear in a query that must be lexically empty.

## File structure

| File | Responsibility |
|---|---|
| `migrations/019_embeddings.sql` *(new)* | `film_embedding` table |
| `src/movie_brain/domain/search.py` | `EMBED_MODEL`, `EMBED_DIM`, `MAX_DISTANCE`, `SEMANTIC_WEIGHT`, `embedding_text` — pure |
| `src/movie_brain/domain/models.py` | `EmbedTarget` — the worklist row |
| `src/movie_brain/infrastructure/embeddings.py` *(new)* | `Embedder` protocol, `SemanticUnavailable`, `pack`/`unpack`, `SentenceTransformerEmbedder` (lazy), `VectorIndex` (numpy, lazy) |
| `src/movie_brain/infrastructure/database.py` | `films_needing_embedding`, `write_embeddings`, `all_embeddings`, `embedding_summary`; `summary()` gains `embeddings` + `prose`; `_ONE_ROW_TABLES` gains `film_embedding` |
| `src/movie_brain/application/embed.py` *(new)* | `embed_films(...) -> EmbedReport` — the verb's logic |
| `src/movie_brain/application/search.py` | `run_search(repo, text, index=None)` — stage 4 |
| `src/movie_brain/web/app.py` | `create_app(repo, today, embedder=None)` builds the index |
| `src/movie_brain/cli.py` | `embed` command; `dashboard` passes the embedder when the extra is importable |
| `pyproject.toml` | extra `semantic`, `numpy` in dev, mypy override, pytest marker |
| `tests/conftest.py` | `FakeEmbedder` + `fake_embedder` fixture |
| `tests/unit/test_search.py`, `tests/unit/test_embeddings.py` *(new)*, `tests/unit/test_database.py`, `tests/unit/test_cli.py`, `tests/unit/test_embeddings_real.py` *(new)* | unit coverage per layer |
| `tests/features/embed.feature` + `tests/step_defs/test_embed.py` *(new)*, `tests/features/search.feature` + `tests/step_defs/test_search.py` | BDD |
| `tests/web/test_api.py` | contract unchanged with and without an embedder |
| `CLAUDE.md`, the spec, the handoff | docs |

---

### Task 0: Branch

- [ ] **Step 1: Create the branch off a clean, current `main`**

```bash
git status -sb          # expect: ## main...origin/main, clean
git checkout -b feature/power-search-c-semantic
```

---

### Task 1: Pure domain — constants and `embedding_text`

**Files:**
- Modify: `src/movie_brain/domain/search.py` (constants block near line 25; new function after `trigram_query`)
- Test: `tests/unit/test_search.py`

**Interfaces:**
- Produces: `EMBED_MODEL: str`, `EMBED_DIM: int`, `MAX_DISTANCE: float`, `SEMANTIC_WEIGHT: float`, `embedding_text(overview: str | None, plot: str | None, tagline: str | None) -> str | None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_search.py` (extend the existing import block with `EMBED_DIM, EMBED_MODEL, MAX_DISTANCE, SEMANTIC_WEIGHT, embedding_text`):

```python
def test_embedding_text_joins_the_three_prose_fields_in_order_and_strips():
    assert embedding_text("  An overview. ", "A plot.", " Tag line ") == "An overview. A plot. Tag line"


def test_embedding_text_skips_empty_fields_and_never_takes_a_title():
    assert embedding_text(None, "Only a plot.", "") == "Only a plot."
    assert embedding_text("", None, "   ") is None


def test_semantic_constants_are_the_spec_values():
    assert EMBED_MODEL == "all-MiniLM-L6-v2" and EMBED_DIM == 384
    assert MAX_DISTANCE == 0.6 and SEMANTIC_WEIGHT == 5.0
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_search.py -k "embedding_text or semantic_constants" -q`
Expected: FAIL — `ImportError: cannot import name 'embedding_text'`.

- [ ] **Step 3: Implement**

In `src/movie_brain/domain/search.py`, after the `LENGTH_PENALTY_EXPONENT` line add:

```python
# Semantic search (Plan C, spec D14–D18). The vector is over PROSE ONLY: the title is the
# heaviest lexical signal already, and inside the vector it rewards string coincidence —
# measured: title-in-vector put "Hard Boiled" (1992) first on the owner's own query.
EMBED_MODEL = "all-MiniLM-L6-v2"
EMBED_DIM = 384
MAX_DISTANCE = 0.6  # cosine distance floor; one constant, no slider (owner decision, D18)
SEMANTIC_WEIGHT = 5.0  # re-rank mode: one more SUMMED signal, 5 × (1 − distance), so a title hit (10) stays first
```

After `trigram_query` add:

```python
def embedding_text(overview: str | None, plot: str | None, tagline: str | None) -> str | None:
    """The text one film is embedded from: overview, plot, tagline — stripped, non-empty ones
    joined by a single space in that order. `None` when all three are empty: such a film is never
    embedded (D15) and stays reachable lexically and by every field."""
    parts = [p.strip() for p in (overview, plot, tagline) if p and p.strip()]
    return " ".join(parts) if parts else None
```

- [ ] **Step 4: Run to verify they pass, then the whole search unit file**

Run: `uv run pytest tests/unit/test_search.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/domain/search.py tests/unit/test_search.py
git commit -m "the title is already the heaviest lexical signal, so the vector is over prose alone

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017AZb57CHEGYwXATffrFjBR"
```

---

### Task 2: Migration 019 and the repository

**Files:**
- Create: `migrations/019_embeddings.sql`
- Modify: `src/movie_brain/domain/models.py` (near `CreditsTarget`)
- Modify: `src/movie_brain/infrastructure/database.py` — `_ONE_ROW_TABLES` (line ~179), the `kept[...]` branch in `merge_film` (line ~2330), new methods after `credits_summary` (line ~1290), `summary()` (line ~2642)
- Test: `tests/unit/test_database.py`

**Interfaces:**
- Produces: `EmbedTarget(film_id: int, title: str, overview: str | None, plot: str | None, tagline: str | None)`; `Repository.films_needing_embedding(model: str, limit: int | None = None) -> list[EmbedTarget]`; `Repository.write_embeddings(rows: Sequence[tuple[int, bytes]], today: date, *, model: str, dim: int) -> None`; `Repository.all_embeddings(model: str) -> list[tuple[int, bytes]]`; `Repository.embedding_summary(model: str) -> tuple[int, str]` (count, max `embedded_on` or `""`); `summary()` gains keys `embeddings` and `prose`.

- [ ] **Step 1: Write the migration**

`migrations/019_embeddings.sql`:

```sql
-- Power search, Plan C (design docs/superpowers/specs/2026-09-06-power-search-c-semantic-design.md §3, D14).
-- One vector per film over its PROSE (overview + plot + tagline, never the title), stored as a
-- plain BLOB of `dim` little-endian float32 values, L2-normalised so cosine is a dot product.
-- No sqlite-vec: brute-force cosine over the whole catalogue measured 0.08 ms per query with
-- numpy, so a virtual table that must be loaded on every connection buys nothing.
-- `model` is a column, not part of the key: a model change is a full re-embed and two models
-- never coexist. Byte layout is yt-brain's `_to_blob` (struct '384f'), so vectors read across.
-- Nothing here is identity — `film_embedding` is search data, moved by merge_film survivor-wins.
BEGIN;
CREATE TABLE film_embedding (
    film_id     INTEGER PRIMARY KEY REFERENCES films(id),
    model       TEXT    NOT NULL,
    dim         INTEGER NOT NULL,
    vector      BLOB    NOT NULL,
    embedded_on TEXT    NOT NULL
);
INSERT INTO schema_version (version) VALUES (19);
COMMIT;
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/unit/test_database.py` (it already imports `sqlite3`, `Film`, `OmdbRating`, `CastRow`, `CrewRow`, `TmdbCredits`, `D`; add any missing to its import block):

```python
def _prose_film(repo, title, year, tmdb_id, overview, plot=None, tagline=None, day=D):
    fid = repo.create_film(Film(title, year, None, ""))
    repo.set_external_id(fid, "tmdb", str(tmdb_id), day)
    if plot is not None:
        repo.upsert_omdb(fid, OmdbRating(7.0, 80, True, "English", '{"Plot": "%s"}' % plot), day)
    repo.write_credits(
        fid,
        TmdbCredits(
            tmdb_id=tmdb_id, imdb_id=None, title=title, original_title=title, year=None, runtime_min=None,
            alt_titles=(), overview=overview, tagline=tagline, genres=(), keywords=(), cast=(), crew=(),
        ),
        day,
    )
    return fid


def test_embedding_worklist_is_prose_films_without_a_row_for_this_model(repo):
    a = _prose_film(repo, "Alpha", 1946, 910, "A private eye.", plot="Sternwood.", tagline=None)
    b = _prose_film(repo, "Beta", 1950, 911, None)  # a film_text row exists (title only), prose is all None
    repo.create_film(Film("Gamma", 1960, None, ""))  # no film_text row at all
    targets = repo.films_needing_embedding("m1")
    assert [(t.film_id, t.title, t.overview, t.plot, t.tagline) for t in targets] == [
        (a, "Alpha", "A private eye.", "Sternwood.", None),
        (b, "Beta", None, None, None),
    ]
    assert repo.films_needing_embedding("m1", limit=1)[0].film_id == a


def test_write_embeddings_stamps_and_removes_from_the_worklist_until_the_prose_changes(repo):
    a = _prose_film(repo, "Alpha", 1946, 910, "A private eye.")
    repo.write_embeddings([(a, b"\x00" * 8)], D, model="m1", dim=2)
    assert repo.films_needing_embedding("m1") == []
    assert repo.films_needing_embedding("m2")[0].film_id == a  # another model: everything is due
    assert repo.all_embeddings("m1") == [(a, b"\x00" * 8)]
    assert repo.embedding_summary("m1") == (1, D.isoformat())
    # Re-enriched later than embedded → the prose may have changed → back on the worklist.
    later = date(2026, 8, 20)
    repo.write_credits(
        a,
        TmdbCredits(
            tmdb_id=910, imdb_id=None, title="Alpha", original_title="Alpha", year=None, runtime_min=None,
            alt_titles=(), overview="A new overview.", tagline=None, genres=(), keywords=(), cast=(), crew=(),
        ),
        later,
    )
    assert [t.overview for t in repo.films_needing_embedding("m1")] == ["A new overview."]
    repo.write_embeddings([(a, b"\x01" * 8)], later, model="m1", dim=2)  # overwrite, PRIMARY KEY
    assert repo.all_embeddings("m1") == [(a, b"\x01" * 8)]
    assert repo.embedding_summary("m1") == (1, later.isoformat())
    assert repo.embedding_summary("m9") == (0, "")


def test_summary_counts_embeddings_and_prose(repo):
    a = _prose_film(repo, "Alpha", 1946, 910, "A private eye.")
    repo.write_embeddings([(a, b"\x00" * 8)], D, model="m1", dim=2)
    s = repo.summary("criterion")
    assert s["embeddings"] == 1 and s["prose"] == 1


def test_merge_moves_the_embedding_survivor_wins(repo):
    a = _prose_film(repo, "Alpha", 1946, 910, "A private eye.")
    b = _prose_film(repo, "Alpha", 1947, 911, "A private eye again.")
    repo.write_embeddings([(b, b"\x02" * 8)], D, model="m1", dim=2)
    report = repo.merge_film(b, a, D)
    assert report.moved["film_embedding"] == 1
    assert repo.all_embeddings("m1") == [(a, b"\x02" * 8)]
    # And when both hold one, the survivor's stays and the loser's film_id is noted.
    c = _prose_film(repo, "Alpha", 1948, 912, "Third.")
    repo.write_embeddings([(a, b"\x0a" * 8), (c, b"\x0c" * 8)], D, model="m1", dim=2)
    report = repo.merge_film(c, a, D)
    assert report.dropped["film_embedding"] == 1
    assert repo.all_embeddings("m1") == [(a, b"\x0a" * 8)]
    with sqlite3.connect(repo.db_path) as conn:
        note = conn.execute("SELECT note FROM film_disposition WHERE film_id = ?", (c,)).fetchone()[0]
    assert "film_embedding" in note
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/unit/test_database.py -k "embedding or summary_counts" -q`
Expected: FAIL — `AttributeError: 'Repository' object has no attribute 'films_needing_embedding'` (the migration applies on the fresh test DB automatically; if it errors, fix the SQL first).

- [ ] **Step 4: Implement the model row**

In `src/movie_brain/domain/models.py`, next to `CreditsTarget`:

```python
@dataclass(frozen=True)
class EmbedTarget:
    """One worklist row for `movie-brain embed`: the film and the three prose fields it is embedded from."""

    film_id: int
    title: str
    overview: str | None
    plot: str | None
    tagline: str | None
```

- [ ] **Step 5: Implement the repository**

In `src/movie_brain/infrastructure/database.py`:

Change line ~179 to:

```python
_ONE_ROW_TABLES = ("omdb", "tmdb", "my_ratings", "watchlist", "owned", "film_embedding")  # film_id PRIMARY KEY tables
```

In `merge_film`'s `kept[...]` chain, after the `owned` branch add:

```python
                    elif table == "film_embedding":
                        kept[table] = {"film_id": loser_id}
```

After `credits_summary` add (import `EmbedTarget` from `movie_brain.domain.models`):

```python
    # embeddings (power search, Plan C) --------------------------------------
    def films_needing_embedding(self, model: str, limit: int | None = None) -> list[EmbedTarget]:
        """Live films holding a `film_text` row whose embedding is missing, made by a different
        model, or older than the film's last enrichment (the prose may have changed). Whether the
        prose is actually non-empty is `embedding_text`'s call, not SQL's."""
        sql = (
            "SELECT f.id, f.title, t.overview, t.plot, x.tagline FROM films f "
            "JOIN film_text t ON t.film_id = f.id "
            "LEFT JOIN tmdb_facts x ON x.film_id = f.id "
            "LEFT JOIN film_embedding e ON e.film_id = f.id "
            "WHERE (e.film_id IS NULL OR e.model != ? "
            "       OR (x.credits_fetched_on IS NOT NULL AND x.credits_fetched_on > e.embedded_on)) AND "
            + _NOT_DISPOSED + " ORDER BY f.id"
        )
        params: list[object] = [model]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        with self._conn() as c:
            rows = c.execute(sql, params).fetchall()
        return [EmbedTarget(int(r["id"]), str(r["title"]), r["overview"], r["plot"], r["tagline"]) for r in rows]

    def write_embeddings(self, rows: Sequence[tuple[int, bytes]], today: date, *, model: str, dim: int) -> None:
        """One batch, one transaction; a film's row is replaced whole (PRIMARY KEY on film_id)."""
        with self._conn() as c:
            c.executemany(
                "INSERT INTO film_embedding (film_id, model, dim, vector, embedded_on) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(film_id) DO UPDATE SET model = excluded.model, dim = excluded.dim, "
                "vector = excluded.vector, embedded_on = excluded.embedded_on",
                [(film_id, model, dim, vector, today.isoformat()) for film_id, vector in rows],
            )

    def all_embeddings(self, model: str) -> list[tuple[int, bytes]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT e.film_id, e.vector FROM film_embedding e JOIN films f ON f.id = e.film_id "
                "WHERE e.model = ? AND " + _NOT_DISPOSED + " ORDER BY e.film_id",
                (model,),
            ).fetchall()
            return [(int(r["film_id"]), bytes(r["vector"])) for r in rows]

    def embedding_summary(self, model: str) -> tuple[int, str]:
        """(count, latest embedded_on or '') — the cheap stamp `VectorIndex` compares to know when to rebuild."""
        with self._conn() as c:
            r = c.execute(
                "SELECT COUNT(*) AS n, COALESCE(MAX(embedded_on), '') AS latest FROM film_embedding WHERE model = ?",
                (model,),
            ).fetchone()
            return int(r["n"]), str(r["latest"])
```

In `summary()`, after the `"credits"` entry add two entries (the `EMBED_MODEL` import comes from `movie_brain.domain.search`, which `database.py` already imports `Filter` from):

```python
            "embeddings": self.embedding_summary(EMBED_MODEL)[0],
            "prose": self.prose_count(),
```

and add beside `embedding_summary`:

```python
    def prose_count(self) -> int:
        with self._conn() as c:
            return int(c.execute("SELECT COUNT(*) FROM film_text").fetchone()[0])
```

- [ ] **Step 6: Run to verify they pass, then the whole unit file**

Run: `uv run pytest tests/unit/test_database.py -q`
Expected: all PASS (the existing merge tests still pass: `_ONE_ROW_TABLES` is iterated generically).

- [ ] **Step 7: Lint, types, commit**

```bash
uv run ruff check . && uv run mypy
git add migrations/019_embeddings.sql src/movie_brain/domain/models.py src/movie_brain/infrastructure/database.py tests/unit/test_database.py
git commit -m "a tenth of a millisecond of brute force needs no extension loaded on every connection, so the vector is a plain blob

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017AZb57CHEGYwXATffrFjBR"
```

---

### Task 3: `infrastructure/embeddings.py`, the extra, and the fake

**Files:**
- Create: `src/movie_brain/infrastructure/embeddings.py`
- Modify: `pyproject.toml`
- Modify: `tests/conftest.py`
- Test: `tests/unit/test_embeddings.py` *(new)*, `tests/unit/test_embeddings_real.py` *(new)*

**Interfaces:**
- Consumes: `EMBED_MODEL`, `EMBED_DIM`, `MAX_DISTANCE` (Task 1); `Repository.all_embeddings`, `embedding_summary` (Task 2).
- Produces: `class Embedder(Protocol): def encode(self, texts: Sequence[str]) -> list[list[float]]` (each vector L2-normalised, length `EMBED_DIM`); `class SemanticUnavailable(RuntimeError)`; `pack(vector: Sequence[float]) -> bytes`; `unpack(blob: bytes) -> list[float]`; `class SentenceTransformerEmbedder(Embedder)` with `@staticmethod available() -> bool` and lazy `encode`; `class VectorIndex` with `__init__(repo, embedder, model=EMBED_MODEL)`, `embed_query(text) -> list[float]`, `nearest(vector, floor) -> list[tuple[int, float]]` (ascending distance, ties by film id), `distances(vector, ids) -> dict[int, float]`, `__len__`.
- Test fixture: `fake_embedder` → `FakeEmbedder` with `.asked: list[str]`.

- [ ] **Step 1: Dependencies**

```bash
uv add --optional semantic "sentence-transformers>=3.4" "numpy>=1.26"
uv add --dev "numpy>=1.26"
```

Then in `pyproject.toml` add, under `[[tool.mypy.overrides]]` as a second override block, and under `[tool.pytest.ini_options]`:

```toml
[[tool.mypy.overrides]]
module = ["sentence_transformers", "sentence_transformers.*"]
ignore_missing_imports = true

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["semantic: exercises the real sentence-transformers model; skipped when the optional extra is not installed"]
```

Verify `[project] dependencies` is unchanged (four entries) and `uv run python -c "import numpy"` succeeds while `uv run python -c "import sentence_transformers"` fails (the extra is not synced by default).

- [ ] **Step 2: The fake embedder fixture**

Append to `tests/conftest.py`:

```python
import math
import re
import zlib
from collections.abc import Sequence

from movie_brain.domain.search import EMBED_DIM

# Concept groups for the fake: words in one group share a dimension, so "gumshoe" is near
# "private eye" the way the real model makes them near — see the plan's fixture table.
_CONCEPTS = {
    "private": 0, "eye": 0, "detective": 0, "gumshoe": 0, "sleuth": 0, "investigator": 0,
    "nurse": 1, "ward": 1, "caregiver": 1, "medic": 1,
    "alpha": 2,
    "sternwood": 3,
}
_STOPWORDS = {"a", "an", "the", "in", "of", "on", "and", "at", "to"}
_FIRST_FREE_DIM = 8


class FakeEmbedder:
    """Deterministic bag-of-concepts vectors, L2-normalised to EMBED_DIM. Records every text it is asked to encode."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        out = []
        for text in texts:
            self.asked.append(text)
            v = [0.0] * EMBED_DIM
            for word in re.findall(r"[a-z0-9$]+", text.lower()):
                if word in _STOPWORDS:
                    continue
                dim = _CONCEPTS.get(word)
                if dim is None:
                    dim = _FIRST_FREE_DIM + zlib.crc32(word.encode()) % (EMBED_DIM - _FIRST_FREE_DIM)
                v[dim] += 1.0
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / norm for x in v])
        return out


@pytest.fixture
def fake_embedder() -> FakeEmbedder:
    return FakeEmbedder()
```

- [ ] **Step 3: Write the failing unit tests**

`tests/unit/test_embeddings.py`:

```python
from __future__ import annotations

import struct
from datetime import date

import pytest

from movie_brain.domain.models import Film
from movie_brain.domain.search import EMBED_DIM, MAX_DISTANCE
from movie_brain.infrastructure.embeddings import SemanticUnavailable, VectorIndex, pack, unpack

D = date(2026, 8, 19)


def test_pack_is_yt_brain_bytes_and_unpack_inverts_it():
    v = [0.0] * EMBED_DIM
    v[0], v[5] = 0.6, 0.8
    blob = pack(v)
    assert blob == struct.pack(f"{EMBED_DIM}f", *v) and len(blob) == EMBED_DIM * 4
    assert unpack(blob) == pytest.approx(v)


def test_pack_refuses_the_wrong_dimension():
    with pytest.raises(ValueError):
        pack([1.0, 0.0])


def _unit(*dims: int) -> list[float]:
    v = [0.0] * EMBED_DIM
    for d in dims:
        v[d] = 1.0
    n = sum(x * x for x in v) ** 0.5
    return [x / n for x in v]


def _films(repo, n):
    return [repo.create_film(Film(f"F{i}", 1950 + i, None, "")) for i in range(n)]


def test_nearest_orders_by_distance_inside_the_floor_and_ties_by_id(repo, fake_embedder):
    a, b, c = _films(repo, 3)
    repo.write_embeddings([(a, pack(_unit(0))), (b, pack(_unit(0, 1))), (c, pack(_unit(2)))], D, model="m", dim=EMBED_DIM)
    idx = VectorIndex(repo, fake_embedder, model="m")
    q = _unit(0)
    assert idx.nearest(q, MAX_DISTANCE) == [(a, pytest.approx(0.0)), (b, pytest.approx(1 - 2 ** -0.5))]
    assert idx.nearest(q, 2.0)[-1] == (c, pytest.approx(1.0))  # a wide floor admits everything, farthest last
    assert len(idx) == 3


def test_distances_reports_only_the_films_that_hold_a_vector(repo, fake_embedder):
    a, b = _films(repo, 2)
    repo.write_embeddings([(a, pack(_unit(0)))], D, model="m", dim=EMBED_DIM)
    idx = VectorIndex(repo, fake_embedder, model="m")
    assert idx.distances(_unit(0), [a, b, 999]) == {a: pytest.approx(0.0)}


def test_index_rebuilds_when_the_table_changes(repo, fake_embedder):
    a, b = _films(repo, 2)
    repo.write_embeddings([(a, pack(_unit(0)))], D, model="m", dim=EMBED_DIM)
    idx = VectorIndex(repo, fake_embedder, model="m")
    assert [i for i, _ in idx.nearest(_unit(0), 2.0)] == [a]
    repo.write_embeddings([(b, pack(_unit(0)))], date(2026, 8, 20), model="m", dim=EMBED_DIM)
    assert [i for i, _ in idx.nearest(_unit(0), 2.0)] == [a, b]


def test_embed_query_goes_through_the_embedder_once(repo, fake_embedder):
    idx = VectorIndex(repo, fake_embedder, model="m")
    v = idx.embed_query("gumshoe sleuth")
    assert fake_embedder.asked == ["gumshoe sleuth"] and len(v) == EMBED_DIM
    assert sum(x * x for x in v) == pytest.approx(1.0)


def test_an_empty_index_answers_nothing_without_error(repo, fake_embedder):
    idx = VectorIndex(repo, fake_embedder, model="m")
    assert idx.nearest(_unit(0), 2.0) == [] and idx.distances(_unit(0), [1]) == {} and len(idx) == 0


def test_sentence_transformer_adapter_reports_availability_and_raises_when_absent(monkeypatch):
    from movie_brain.infrastructure import embeddings

    monkeypatch.setattr(embeddings.importlib.util, "find_spec", lambda name: None)
    assert embeddings.SentenceTransformerEmbedder.available() is False
    with pytest.raises(SemanticUnavailable):
        embeddings.SentenceTransformerEmbedder().encode(["x"])
```

`tests/unit/test_embeddings_real.py`:

```python
"""The one test that loads the real model. Skipped unless `uv sync --extra semantic` has run."""

from __future__ import annotations

import pytest

pytest.importorskip("sentence_transformers")

from movie_brain.domain.search import EMBED_DIM  # noqa: E402
from movie_brain.infrastructure.embeddings import SentenceTransformerEmbedder  # noqa: E402


@pytest.mark.semantic
def test_real_model_puts_two_detective_sentences_closer_than_a_third():
    e = SentenceTransformerEmbedder()
    a, b, c = e.encode([
        "A private detective takes on a case in San Francisco.",
        "A hard-boiled private investigator is hired by a wealthy general.",
        "A nurse works the night shift in a hospital ward.",
    ])
    assert len(a) == EMBED_DIM
    dot = lambda x, y: sum(p * q for p, q in zip(x, y, strict=True))  # noqa: E731
    assert dot(a, b) > dot(a, c) and dot(a, b) > dot(b, c)
```

- [ ] **Step 4: Run to verify they fail**

Run: `uv run pytest tests/unit/test_embeddings.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'movie_brain.infrastructure.embeddings'`. And `uv run pytest tests/unit/test_embeddings_real.py -q` → 1 skipped.

- [ ] **Step 5: Implement**

`src/movie_brain/infrastructure/embeddings.py`:

```python
"""Embeddings adapter for semantic search (Plan C, spec D14, D19, D20).

`Embedder` is the one port: texts in, unit vectors out. `SentenceTransformerEmbedder` is the
real adapter and imports torch LAZILY on the first `encode`, because import-plus-load measured
4.9 s and would otherwise tax every dashboard start and every test that builds the app.
`VectorIndex` is the whole search index: the catalogue's vectors as one numpy matrix, loaded on
first use and rebuilt when the table's (count, latest stamp) changes; cosine over 4,645 × 384
measured 0.08 ms per query, which is why there is no sqlite-vec here. numpy is imported inside
the class so a core install without the `semantic` extra never fails to import this module.
"""

from __future__ import annotations

import importlib.util
import logging
import struct
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Any, Protocol

from movie_brain.domain.search import EMBED_DIM, EMBED_MODEL
from movie_brain.infrastructure.database import Repository

if TYPE_CHECKING:
    import numpy as np

log = logging.getLogger(__name__)

_FORMAT = f"<{EMBED_DIM}f"  # yt-brain's `_to_blob`, byte for byte


class SemanticUnavailable(RuntimeError):
    """The optional extra is missing, or the model cannot be loaded (not cached, offline)."""


class Embedder(Protocol):
    def encode(self, texts: Sequence[str]) -> list[list[float]]: ...


def pack(vector: Sequence[float]) -> bytes:
    if len(vector) != EMBED_DIM:
        raise ValueError(f"expected {EMBED_DIM} floats, got {len(vector)}")
    return struct.pack(_FORMAT, *vector)


def unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(_FORMAT, blob))


class SentenceTransformerEmbedder:
    """all-MiniLM-L6-v2 through sentence-transformers; normalised output; lazy load."""

    def __init__(self, model_name: str = EMBED_MODEL) -> None:
        self.model_name = model_name
        self._model: Any = None

    @staticmethod
    def available() -> bool:
        """Cheap: is the extra importable? Never imports torch."""
        return importlib.util.find_spec("sentence_transformers") is not None

    def _load(self) -> Any:
        if self._model is None:
            if not self.available():
                raise SemanticUnavailable("semantic search is not installed — uv sync --extra semantic")
            try:
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer(self.model_name)
            except Exception as exc:  # model not cached and offline, broken install, …
                raise SemanticUnavailable(f"could not load {self.model_name}: {exc}") from exc
        return self._model

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        model = self._load()
        vectors = model.encode(list(texts), batch_size=128, normalize_embeddings=True, show_progress_bar=False)
        return [[float(x) for x in v] for v in vectors]


class VectorIndex:
    """Brute-force cosine over every stored vector for one model. Vectors are stored normalised,
    so distance = 1 − dot. Rebuilt lazily whenever `embedding_summary` changes."""

    def __init__(self, repo: Repository, embedder: Embedder, model: str = EMBED_MODEL) -> None:
        self.repo = repo
        self.embedder = embedder
        self.model = model
        self._stamp: tuple[int, str] | None = None
        self._ids: list[int] = []
        self._matrix: np.ndarray | None = None
        self._warned = False

    def _ensure(self) -> None:
        stamp = self.repo.embedding_summary(self.model)
        if stamp == self._stamp:
            return
        import numpy as np

        rows = self.repo.all_embeddings(self.model)
        self._ids = [film_id for film_id, _ in rows]
        blob = b"".join(vector for _, vector in rows)
        self._matrix = np.frombuffer(blob, dtype="<f4").reshape(len(rows), EMBED_DIM) if rows else None
        self._stamp = stamp

    def __len__(self) -> int:
        self._ensure()
        return len(self._ids)

    def embed_query(self, text: str) -> list[float]:
        try:
            return self.embedder.encode([text])[0]
        except SemanticUnavailable as exc:
            if not self._warned:
                log.warning("semantic search off: %s", exc)
                self._warned = True
            raise

    def _scores(self, vector: Sequence[float]) -> np.ndarray | None:
        self._ensure()
        if self._matrix is None:
            return None
        import numpy as np

        return self._matrix @ np.asarray(vector, dtype="<f4")

    def nearest(self, vector: Sequence[float], floor: float) -> list[tuple[int, float]]:
        scores = self._scores(vector)
        if scores is None:
            return []
        hits = [(self._ids[i], float(1.0 - s)) for i, s in enumerate(scores) if 1.0 - s <= floor]
        hits.sort(key=lambda t: (t[1], t[0]))
        return hits

    def distances(self, vector: Sequence[float], ids: Iterable[int]) -> dict[int, float]:
        scores = self._scores(vector)
        if scores is None:
            return {}
        pos = {film_id: i for i, film_id in enumerate(self._ids)}
        return {film_id: float(1.0 - scores[pos[film_id]]) for film_id in ids if film_id in pos}
```

- [ ] **Step 6: Run to verify they pass**

Run: `uv run pytest tests/unit/test_embeddings.py tests/unit/test_embeddings_real.py -q`
Expected: 8 passed, 1 skipped. Then `uv run ruff check . && uv run mypy` clean (if mypy complains about `np.ndarray` under `TYPE_CHECKING`, annotate `_matrix: Any` and `_scores -> Any`).

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock src/movie_brain/infrastructure/embeddings.py tests/conftest.py tests/unit/test_embeddings.py tests/unit/test_embeddings_real.py
git commit -m "five seconds of torch import belong to the first semantic query, not to every dashboard start and every test

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017AZb57CHEGYwXATffrFjBR"
```

---

### Task 4: The verb — `application/embed.py` (BDD)

**Files:**
- Create: `src/movie_brain/application/embed.py`
- Create: `tests/features/embed.feature`, `tests/step_defs/test_embed.py`

**Interfaces:**
- Consumes: `embedding_text`, `EMBED_MODEL`, `EMBED_DIM` (Task 1); `films_needing_embedding`, `write_embeddings` (Task 2); `Embedder`, `pack` (Task 3).
- Produces: `EmbedReport(scanned: int, embedded: int, skipped_no_prose: int)`; `embed_films(repo, embedder, today, *, apply=False, limit=None, batch_size=128, log=_stderr) -> EmbedReport`.

- [ ] **Step 1: Write the feature**

`tests/features/embed.feature`:

```gherkin
Feature: Embedding films for semantic search

  A film is embedded from its prose — overview, plot, tagline — and never its title.
  The verb walks every live film holding prose and no vector for the current model,
  encodes in batches, and stamps each film so the next run resumes where this one
  stopped. Dry-run by default, it never touches the model; it never runs inside sync.

  Background:
    Given a prose film "Alpha" (1946) with overview "A private eye." and plot "Sternwood."
    And a prose film "Beta" (1950) with overview "A nurse in the alpha ward." and plot "Alpha shift."
    And a film "Gamma" (1960) enriched with no overview, plot or tagline

  Scenario: A dry run reports the worklist and touches neither the model nor the database
    When I embed without applying
    Then the embed report counts 2 scanned, 0 embedded, 1 skipped for no prose
    And the embedder was asked nothing
    And no film holds a vector

  Scenario: Applying embeds the prose alone and stamps each film
    When I embed with apply
    Then the embed report counts 2 scanned, 2 embedded, 1 skipped for no prose
    And the embedder was asked "A private eye. Sternwood." and "A nurse in the alpha ward. Alpha shift."
    And the films holding a vector are Alpha and Beta

  Scenario: A stamped film is never encoded again
    Given the corpus is already embedded
    When I embed with apply
    Then the embed report counts 0 scanned, 0 embedded, 1 skipped for no prose
    And the embedder was asked nothing

  Scenario: A film re-enriched after embedding is embedded again
    Given the corpus is already embedded
    And "Alpha" is re-enriched the next day with overview "A private detective."
    When I embed with apply
    Then the embed report counts 1 scanned, 1 embedded, 1 skipped for no prose
    And the embedder was asked "A private detective. Sternwood."

  Scenario: The batch size bounds one encode call
    When I embed with apply in batches of 1
    Then the embedder was called 2 times
```

The "skipped for no prose" count is 1 in every scenario: Gamma holds a title-only `film_text` row (enriched with `overview=None` and no OMDb plot), so it is on the worklist and `embedding_text` returns `None` for it. A film with no `film_text` row at all would not be on the worklist and would count nowhere.

- [ ] **Step 2: Write the step definitions**

`tests/step_defs/test_embed.py`:

```python
from __future__ import annotations

from datetime import date, timedelta

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.embed import embed_films
from movie_brain.domain.models import Film, OmdbRating, TmdbCredits
from movie_brain.domain.search import EMBED_MODEL

scenarios("../features/embed.feature")


def _credits(tmdb_id: int, title: str, overview: str | None) -> TmdbCredits:
    return TmdbCredits(
        tmdb_id=tmdb_id, imdb_id=None, title=title, original_title=title, year=None, runtime_min=None,
        alt_titles=(), overview=overview, tagline=None, genres=(), keywords=(), cast=(), crew=(),
    )


@pytest.fixture
def films() -> dict[str, int]:
    return {}


@pytest.fixture
def result() -> dict:
    return {}


@given(parsers.parse('a prose film "{title}" ({year:d}) with overview "{overview}" and plot "{plot}"'))
def prose_film(repo, today, films, title, year, overview, plot):
    fid = repo.create_film(Film(title, year, None, ""))
    tmdb_id = 900 + len(films)
    repo.set_external_id(fid, "tmdb", str(tmdb_id), today)
    repo.upsert_omdb(fid, OmdbRating(7.0, 80, True, "English", '{"Plot": "%s"}' % plot), today)
    repo.write_credits(fid, _credits(tmdb_id, title, overview), today)
    films[title] = fid


@given(parsers.parse('a film "{title}" ({year:d}) enriched with no overview, plot or tagline'))
def bare_film(repo, today, films, title, year):
    fid = repo.create_film(Film(title, year, None, ""))
    tmdb_id = 900 + len(films)
    repo.set_external_id(fid, "tmdb", str(tmdb_id), today)
    repo.write_credits(fid, _credits(tmdb_id, title, None), today)
    films[title] = fid


@given("the corpus is already embedded")
def already(repo, today, fake_embedder):
    embed_films(repo, fake_embedder, today, apply=True)
    fake_embedder.asked.clear()


@given(parsers.parse('"{title}" is re-enriched the next day with overview "{overview}"'))
def reenriched(repo, today, films, title, overview):
    tmdb_id = int(repo.external_ids_for(films[title])["tmdb"])
    repo.write_credits(films[title], _credits(tmdb_id, title, overview), today + timedelta(days=1))


@when("I embed without applying")
def dry(repo, today, fake_embedder, result):
    result["r"] = embed_films(repo, fake_embedder, today, apply=False, log=lambda _m: None)


@when("I embed with apply")
def apply(repo, today, fake_embedder, result):
    result["r"] = embed_films(repo, fake_embedder, today + timedelta(days=1), apply=True, log=lambda _m: None)


@when(parsers.parse("I embed with apply in batches of {n:d}"))
def apply_batched(repo, today, fake_embedder, result, n):
    result["r"] = embed_films(repo, fake_embedder, today, apply=True, batch_size=n, log=lambda _m: None)


@then(parsers.parse("the embed report counts {scanned:d} scanned, {embedded:d} embedded, {skipped:d} skipped for no prose"))
def counts(result, scanned, embedded, skipped):
    r = result["r"]
    assert (r.scanned, r.embedded, r.skipped_no_prose) == (scanned, embedded, skipped), r


@then("the embedder was asked nothing")
def asked_nothing(fake_embedder):
    assert fake_embedder.asked == []


@then(parsers.parse('the embedder was asked "{a}" and "{b}"'))
def asked_two(fake_embedder, a, b):
    assert fake_embedder.asked == [a, b]


@then(parsers.parse('the embedder was asked "{a}"'))
def asked_one(fake_embedder, a):
    assert fake_embedder.asked == [a]


@then(parsers.parse("the embedder was called {n:d} times"))
def called(fake_embedder, n):
    assert fake_embedder.calls == n


@then("no film holds a vector")
def none_held(repo):
    assert repo.all_embeddings(EMBED_MODEL) == []


@then(parsers.parse("the films holding a vector are {names}"))
def held(repo, films, names):
    expected = sorted(films[n.strip()] for n in names.replace(" and ", ",").split(","))
    assert [i for i, _ in repo.all_embeddings(EMBED_MODEL)] == expected
```

`FakeEmbedder` needs a `calls` counter: in `tests/conftest.py` add `self.calls = 0` in `__init__` and `self.calls += 1` at the top of `encode`. Note the "apply" step embeds on `today + 1 day` so that the re-enrichment scenario's `credits_fetched_on` (today + 1) is compared against an `embedded_on` of today from the Given — keep the Given's embed at `today` and the When at `today + 1`, exactly as written above. Add `external_ids_for` usage only if it exists on `Repository` (it does — `test_merge_moves_every_fk_and_records_disposition` calls it).

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/step_defs/test_embed.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'movie_brain.application.embed'`.

- [ ] **Step 4: Implement**

`src/movie_brain/application/embed.py`:

```python
"""Embed every film's prose for semantic search — the data under stage 4 of the bar (Plan C, D21).

Dry-run by default: the worklist is counted and logged and the embedder is never touched (the
model load is the slow part, and a dry run has nothing to encode for). `--apply` encodes in
batches and writes each batch in one transaction, stamping `embedded_on`; stamped films leave
the worklist, so an interrupted run resumes at the next batch. A film re-enriched after it was
embedded returns to the worklist (`films_needing_embedding`). Never called from `sync`.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from movie_brain.domain.search import EMBED_DIM, EMBED_MODEL, embedding_text
from movie_brain.infrastructure.database import Repository
from movie_brain.infrastructure.embeddings import Embedder, pack

BATCH_SIZE = 128


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


@dataclass(frozen=True)
class EmbedReport:
    scanned: int = 0  # films on the worklist that hold prose
    embedded: int = 0  # written (apply) — equals scanned on a completed apply run
    skipped_no_prose: int = 0  # worklist films whose three prose fields are all empty; never embedded


def embed_films(
    repo: Repository,
    embedder: Embedder,
    today: date,
    *,
    apply: bool = False,
    limit: int | None = None,
    batch_size: int = BATCH_SIZE,
    log: Callable[[str], None] = _stderr,
) -> EmbedReport:
    scanned = embedded = skipped = 0
    batch: list[tuple[int, str]] = []

    def flush() -> None:
        nonlocal embedded
        if not batch:
            return
        vectors = embedder.encode([text for _, text in batch])
        repo.write_embeddings(
            [(film_id, pack(v)) for (film_id, _), v in zip(batch, vectors, strict=True)],
            today, model=EMBED_MODEL, dim=EMBED_DIM,
        )
        embedded += len(batch)
        log(f"  embedded {len(batch)} (through #{batch[-1][0]})")
        batch.clear()

    for target in repo.films_needing_embedding(EMBED_MODEL, limit):
        text = embedding_text(target.overview, target.plot, target.tagline)
        if text is None:
            skipped += 1
            continue
        scanned += 1
        if not apply:
            continue
        batch.append((target.film_id, text))
        if len(batch) >= batch_size:
            flush()
    flush()
    log(f"worklist: {scanned} to embed · {skipped} with no prose (never embedded)")
    return EmbedReport(scanned, embedded, skipped)
```

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest tests/step_defs/test_embed.py -q`
Expected: 5 passed. Then `uv run ruff check . && uv run mypy`.

- [ ] **Step 6: Commit**

```bash
git add src/movie_brain/application/embed.py tests/features/embed.feature tests/step_defs/test_embed.py tests/conftest.py
git commit -m "a dry run has nothing to encode for, so it never pays for the model

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017AZb57CHEGYwXATffrFjBR"
```

---

### Task 5: Stage 4 in `run_search` (BDD)

**Files:**
- Modify: `src/movie_brain/application/search.py` (`run_search`, lines ~150–180)
- Modify: `tests/features/search.feature`, `tests/step_defs/test_search.py`

**Interfaces:**
- Consumes: `VectorIndex` (Task 3), `embed_films` (Task 4, in the Given step), `MAX_DISTANCE`, `SEMANTIC_WEIGHT` (Task 1), `Repository.search_films(filters, "")` (exists).
- Produces: `run_search(repo: Repository, text: str, index: VectorIndex | None = None) -> SearchResult`. Hint constants `SEMANTIC_HINT = "no exact match — showing the {n} closest by meaning"`, `NO_SEMANTIC_HINT = "semantic search is not installed — uv sync --extra semantic"`.

- [ ] **Step 1: Give Beta a plot (one corpus change) and add the steps**

In `tests/step_defs/test_search.py::corpus`, immediately BEFORE the `repo.write_credits(b, ...)` line, add:

```python
    repo.upsert_omdb(b, OmdbRating(6.0, 50, True, "English", '{"Genre": "Drama", "Plot": "Alpha shift."}'), DAY)
```

(`write_credits` copies the OMDb plot into `film_text` at write time, so the order matters.) Run `uv run pytest tests/step_defs/test_search.py -q` — the 16 existing scenarios must still pass before going on; if `alpha director: hawks` changes order, stop and report, do not adjust the scenario.

Then add to `tests/step_defs/test_search.py`:

```python
from movie_brain.application.embed import embed_films
from movie_brain.infrastructure.embeddings import VectorIndex


@given("the corpus is embedded by meaning")
def embedded(repo, fake_embedder):
    embed_films(repo, fake_embedder, DAY, apply=True, log=lambda _m: None)
    fake_embedder.asked.clear()


@when(parsers.parse('I search by meaning for "{text}"'))
def search_semantic(repo, result, fake_embedder, text):
    result["r"] = run_search(repo, text.replace('\\"', '"'), index=VectorIndex(repo, fake_embedder))


@then("the model was asked nothing")
def model_idle(fake_embedder):
    assert fake_embedder.asked == []
```

- [ ] **Step 2: Write the failing scenarios**

Append to `tests/features/search.feature`:

```gherkin
  Scenario: Meaning supplies candidates when nothing matches by string
    Given the corpus is embedded by meaning
    When I search by meaning for "gumshoe sleuth"
    Then the result ids are Alpha
    And the result is ranked
    And the hints include "no exact match — showing the 1 closest by meaning"

  Scenario: Meaning-supplied candidates are ordered by distance
    Given the corpus is embedded by meaning
    When I search by meaning for "gumshoe caregiver"
    Then the result ids are Alpha then Beta
    And the hints include "no exact match — showing the 2 closest by meaning"

  Scenario: A field still filters a meaning-supplied result over the whole catalogue
    Given the corpus is embedded by meaning
    When I search by meaning for "gumshoe caregiver actor: jane bogart"
    Then the result ids are Beta
    And the hints include "no exact match — showing the 1 closest by meaning"

  Scenario: A field that excludes every near film leaves the result empty, not widened
    Given the corpus is embedded by meaning
    When I search by meaning for "gumshoe sleuth actor: jane bogart"
    Then the result is empty
    And the hints do not include "no exact match — showing the 1 closest by meaning"

  Scenario: A title hit stays first when meaning re-ranks a lexical result
    Given the corpus is embedded by meaning
    When I search by meaning for "alpha"
    Then the result ids are Alpha then Beta
    And the result is ranked
    And the hints do not include "no exact match — showing the 2 closest by meaning"

  Scenario: Fields alone are never sent to the model
    Given the corpus is embedded by meaning
    When I search by meaning for "actor: humphrey bogart"
    Then the result ids are Alpha
    And the result is not ranked
    And the model was asked nothing

  Scenario: Without the extra, an empty freeform result says what the bar could have done
    When I search for "gumshoe sleuth"
    Then the result is empty
    And the hints include "semantic search is not installed — uv sync --extra semantic"

  Scenario: The install hint is not shown when a field emptied the result
    When I search for "actor: bacalllzz"
    Then the result is empty
    And the hints do not include "semantic search is not installed — uv sync --extra semantic"
```

The re-rank scenario bites only because a pure re-order would put Beta (distance 0.333) ahead of Alpha (no bonus); confirm by temporarily replacing the summed score with the distance during development if in doubt, then restore.

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/step_defs/test_search.py -q`
Expected: the 8 new scenarios FAIL (`TypeError: run_search() got an unexpected keyword argument 'index'`, then hint assertions); the 16 old ones PASS.

- [ ] **Step 4: Implement stage 4**

In `src/movie_brain/application/search.py`: extend the imports with `MAX_DISTANCE, SEMANTIC_WEIGHT` from `movie_brain.domain.search` and add `from movie_brain.infrastructure.embeddings import SemanticUnavailable, VectorIndex`. Add after `NO_CREDITS_HINT`:

```python
SEMANTIC_HINT = "no exact match — showing the {n} closest by meaning"
NO_SEMANTIC_HINT = "semantic search is not installed — uv sync --extra semantic"
```

Replace the tail of `run_search` from `ids = repo.search_films(...)` to the end with:

```python
    free = parsed.free.strip()
    ids = repo.search_films(resolver.filters, parsed.free)
    if free and index is not None:
        ids, semantic_hint = _semantic_stage(repo, index, free, ids, resolver.filters)
        if semantic_hint:
            hints.append(semantic_hint)
    elif free and index is None and not ids and not parsed.terms:
        hints.append(NO_SEMANTIC_HINT)
    # Only when the freeform words stood alone: a field term that emptied the result is
    # its own explanation (a correction, a suggestion or a too-short hint), and blaming the
    # words would send the user to fix the wrong thing.
    if not ids and not parsed.terms and len(free.split()) >= 2:
        n = len(free.split())
        hints.append(f"no film matches all {n} words — try fewer, or quote a phrase")
    return SearchResult(
        ids=tuple(i for i, _ in ids),
        ranked=bool(free) and bool(ids),
        corrections=tuple(resolver.corrections),
        suggestions=tuple(resolver.suggestions),
        hints=tuple(hints),
    )


def _semantic_stage(
    repo: Repository,
    index: VectorIndex,
    free: str,
    ids: list[tuple[int, float]],
    filters: list[Filter],
) -> tuple[list[tuple[int, float]], str | None]:
    """Stage 4 (spec D16, D17). Re-rank mode when the lexical set has members: semantic is one
    more SUMMED signal, never a replacement order, so a title hit stays first. Supply mode when
    it is empty: the films within MAX_DISTANCE, intersected with the exact set every field
    filter produces over the whole catalogue (parent D6), ordered by distance, and said so in
    the hint. A model that cannot load leaves the lexical result untouched."""
    try:
        query = index.embed_query(free)
    except SemanticUnavailable:
        return ids, None
    if ids:
        dist = index.distances(query, [i for i, _ in ids])
        rescored = [
            (i, s + (SEMANTIC_WEIGHT * (1.0 - dist[i]) if i in dist and dist[i] <= MAX_DISTANCE else 0.0))
            for i, s in ids
        ]
        rescored.sort(key=lambda t: -t[1])  # stable: ties keep search_films' title order
        return rescored, None
    near = index.nearest(query, MAX_DISTANCE)
    if near and filters:
        allowed = {i for i, _ in repo.search_films(filters, "")}
        near = [(i, d) for i, d in near if i in allowed]
    if not near:
        return [], None
    return [(i, 1.0 - d) for i, d in near], SEMANTIC_HINT.format(n=len(near))
```

And change the signature to `def run_search(repo: Repository, text: str, index: VectorIndex | None = None) -> SearchResult:`. Update the module docstring's first line to say four stages, the fourth semantic and optional.

- [ ] **Step 5: Run to verify they pass, then the whole suite**

Run: `uv run pytest tests/step_defs/test_search.py -q` → 24 passed. Then `uv run pytest -q` → all pass (the web API tests still call `run_search(repo, q)` with the default). `uv run ruff check . && uv run mypy`.

- [ ] **Step 6: Commit**

```bash
git add src/movie_brain/application/search.py tests/features/search.feature tests/step_defs/test_search.py
git commit -m "the owner's own query has an empty lexical set, so meaning must supply candidates and not only re-order them

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017AZb57CHEGYwXATffrFjBR"
```

---

### Task 6: Wiring — `create_app`, `dashboard`, `embed` verb, `status`

**Files:**
- Modify: `src/movie_brain/web/app.py` (`create_app` signature line 17, the `/api/search` route ~line 109)
- Modify: `src/movie_brain/cli.py` (`dashboard` ~line 136; new `embed` command after `enrich_credits_cmd`; imports)
- Test: `tests/web/test_api.py`, `tests/unit/test_cli.py`

**Interfaces:**
- Consumes: `VectorIndex`, `SentenceTransformerEmbedder`, `SemanticUnavailable`, `Embedder` (Task 3); `embed_films` (Task 4); `run_search(..., index=)` (Task 5).
- Produces: `create_app(repo, today=date.today, embedder: Embedder | None = None) -> Flask`; CLI `movie-brain embed [--apply] [--limit N]`.

- [ ] **Step 1: Write the failing web tests**

Append to `tests/web/test_api.py` (it has a `client` fixture seeding Trio with Plot "Three tales." and `_enrich_trio`):

```python
@pytest.fixture
def semantic_client(repo, fake_embedder):
    _enrich_trio(repo)
    from movie_brain.application.embed import embed_films

    embed_films(repo, fake_embedder, D, apply=True, log=lambda _m: None)
    app = create_app(repo, today=lambda: D, embedder=fake_embedder)
    app.testing = True
    return app.test_client()


def test_search_contract_is_unchanged_when_meaning_supplies_the_result(semantic_client, repo):
    # Shape only (parent D13): a field query (unranked, never sent to the model) and a freeform
    # query that re-ranks a lexical hit ("three tales" is Trio's OMDb plot) both return the same keys.
    body = semantic_client.get("/api/search?q=actor:%20bogrt").get_json()
    assert set(body) == {"q", "ids", "ranked", "corrections", "suggestions", "hints", "total"}
    body = semantic_client.get("/api/search?q=three%20tales").get_json()
    assert set(body) == {"q", "ids", "ranked", "corrections", "suggestions", "hints", "total"}
    assert body["ids"] == [repo.film_id_by_key("trio (1950)")] and body["ranked"] is True


def test_search_without_an_embedder_offers_the_install_hint_on_an_empty_freeform_result(client):
    body = client.get("/api/search?q=gumshoe%20sleuth").get_json()
    assert body["ids"] == [] and "semantic search is not installed — uv sync --extra semantic" in body["hints"]
```

- [ ] **Step 2: Write the failing CLI tests**

Append to `tests/unit/test_cli.py`:

```python
def test_embed_dry_run_needs_no_extra_and_writes_nothing(config_dir, monkeypatch):
    monkeypatch.setattr("movie_brain.cli.SentenceTransformerEmbedder.available", staticmethod(lambda: False))
    r = runner.invoke(app, ["embed"])
    assert r.exit_code == 0, r.output
    assert "dry run" in r.output


def test_embed_apply_without_the_extra_exits_2_with_the_install_line(config_dir, monkeypatch):
    monkeypatch.setattr("movie_brain.cli.SentenceTransformerEmbedder.available", staticmethod(lambda: False))
    r = runner.invoke(app, ["embed", "--apply"])
    assert r.exit_code == 2
    assert "uv sync --extra semantic" in r.output


def test_embed_apply_reports_counts(config_dir, monkeypatch):
    from movie_brain.application.embed import EmbedReport

    monkeypatch.setattr("movie_brain.cli.SentenceTransformerEmbedder.available", staticmethod(lambda: True))
    monkeypatch.setattr("movie_brain.cli.embed_films", lambda *a, **kw: EmbedReport(3, 3, 1))
    r = runner.invoke(app, ["embed", "--apply", "--limit", "3"])
    assert r.exit_code == 0, r.output
    assert "embedded: 3" in r.output and "no prose: 1" in r.output
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/web/test_api.py tests/unit/test_cli.py -k "semantic or embed or install_hint" -q`
Expected: FAIL — `TypeError: create_app() got an unexpected keyword argument 'embedder'`; the CLI tests fail on `No such command 'embed'` / missing attribute.

- [ ] **Step 4: Implement `create_app`**

In `src/movie_brain/web/app.py`:

```python
from movie_brain.infrastructure.embeddings import Embedder, VectorIndex


def create_app(repo: Repository, today: Callable[[], date] = date.today, embedder: Embedder | None = None) -> Flask:
    app = Flask(__name__)
    # Stage 4 of the bar (Plan C). The index is built lazily on the first semantic query and
    # refreshed when `film_embedding` changes; with no embedder the bar is exactly Phase 1.
    index = VectorIndex(repo, embedder) if embedder is not None else None
```

and in the `/api/search` route: `result = run_search(repo, q, index=index)`.

- [ ] **Step 5: Implement the CLI**

In `src/movie_brain/cli.py` imports add:

```python
from movie_brain.application.embed import embed_films
from movie_brain.infrastructure.embeddings import SemanticUnavailable, SentenceTransformerEmbedder
```

Change `dashboard`:

```python
    from movie_brain.web.app import create_app

    embedder = SentenceTransformerEmbedder() if SentenceTransformerEmbedder.available() else None
    console.print(f"movie-brain dashboard → http://{host}:{port}")
    console.print("semantic search: " + ("on (loads the model on the first meaning query)" if embedder else "off — uv sync --extra semantic"))
    create_app(_repo(), embedder=embedder).run(host=host, port=port, debug=False)
```

Add after `enrich_credits_cmd`:

```python
@app.command("embed")
def embed_cmd(
    apply: Annotated[bool, typer.Option("--apply", help="Write the vectors (default: dry-run).")] = False,
    limit: Annotated[int | None, typer.Option("--limit", help="Batch size over the worklist.")] = None,
) -> None:
    """Embed every film's prose (overview, plot, tagline — never the title) for the bar's
    semantic stage. Stamped films are never re-encoded unless re-enriched, so the run can be
    interrupted and resumed. Never part of sync. Dry-run by default; needs `uv sync --extra semantic` to apply.
    """
    if apply and not SentenceTransformerEmbedder.available():
        err.print("semantic search is not installed — uv sync --extra semantic")
        raise typer.Exit(2)
    try:
        report = embed_films(_repo(), SentenceTransformerEmbedder(), date.today(), apply=apply, limit=limit, log=_plain)
    except SemanticUnavailable as exc:
        err.print(str(exc))
        raise typer.Exit(2) from exc
    console.print(
        f"scanned: {report.scanned} · embedded: {report.embedded} · no prose: {report.skipped_no_prose}"
        + ("" if apply else "   (dry run — nothing written)")
    )
```

- [ ] **Step 6: Run to verify they pass, then the whole suite**

Run: `uv run pytest tests/web/test_api.py tests/unit/test_cli.py -q`, then `uv run pytest -q`, then `uv run ruff check . && uv run mypy`.
Expected: all PASS. Also `uv run playwright install chromium` must already have run for `tests/web/test_dashboard.py`; those tests build `create_app(seeded_repo, today=...)` with no embedder and must be unchanged.

- [ ] **Step 7: Commit**

```bash
git add src/movie_brain/web/app.py src/movie_brain/cli.py tests/web/test_api.py tests/unit/test_cli.py
git commit -m "the dashboard should say whether the bar can search by meaning before the first query finds out

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017AZb57CHEGYwXATffrFjBR"
```

---

### Task 7: Docs, spec corrections, the live steps

**Files:**
- Modify: `CLAUDE.md` (Commands block after the `enrich credits` line; the "Power search (Plan B)" bullet gets a sibling "Semantic search (Plan C)" bullet)
- Modify: `docs/superpowers/specs/2026-09-06-power-search-c-semantic-design.md` (§3 SQL, §6 mypy line)
- Modify: `docs/superpowers/handoffs/2026-09-06-power-search-phase-2-semantic-handoff.md` (a "Status" line at the top)

- [ ] **Step 1: CLAUDE.md**

Add to the Commands block, after the `enrich credits` line (one line, no wrap):

```
uv run movie-brain embed [--apply] [--limit N]              # vectors for the bar's semantic stage: overview + plot + tagline per film (NEVER the title), all-MiniLM-L6-v2 via the optional extra (`uv sync --extra semantic`); stamped + resumable, re-embeds a film re-enriched since; never in sync; dry run by default and needs no extra (power-search Plan C spec §7)
```

Add a bullet after the "Power search (Plan B)" bullet, one paragraph, no hard wraps, covering: migration 019 `film_embedding` (plain BLOB, D14, no sqlite-vec — 0.08 ms brute force measured); `embedding_text` is prose only (D15); stage 4's two modes (D16) with the summed re-rank signal `SEMANTIC_WEIGHT` 5 × (1 − distance) so a title hit stays first (D17); `MAX_DISTANCE` 0.6 constant, no control (D18); the two hint strings verbatim; the extra `semantic`, `numpy` in dev, torch never imported by the suite, the one `@pytest.mark.semantic` test; `create_app(repo, today, embedder=None)` and `VectorIndex` lazy load + refresh on `embedding_summary`; `SentenceTransformerEmbedder.available()` decides whether `dashboard` passes an embedder at all (so the install hint is real when the extra is absent, and `SemanticUnavailable` covers only a model that cannot load); `merge_film` moves `film_embedding` survivor-wins; the known limit that the model rewards specific nouns over genre slang (`hard boiled private eye` ranks The Maltese Falcon 30th). Also append to the "Data" section: `Model cache: ~/.cache/huggingface/hub/models--sentence-transformers--all-MiniLM-L6-v2 (88 MB, shared with yt-brain).`

- [ ] **Step 2: Spec corrections**

In the spec's §3, change `INSERT INTO schema_version (version, applied_on) VALUES (19, date('now'));` to `INSERT INTO schema_version (version) VALUES (19);` (the real column set). In §6's `pyproject.toml` bullet, replace "mypy already has `ignore_missing_imports = true`" with "a `[[tool.mypy.overrides]]` block for `sentence_transformers` with `ignore_missing_imports = true` (the existing override covers only `responses`)". In §5 add one sentence to the "Without the extra" paragraph: "`dashboard` passes an embedder only when `SentenceTransformerEmbedder.available()` is true, so the install hint is the real path when the extra is absent." Add the same to §8's first row.

- [ ] **Step 3: Handoff status line**

At the top of the handoff, under the title, add: `**Status 2026-09-06 (later):** the parked hint defect is fixed (2d2bfaa); Phase 2 is specced (docs/superpowers/specs/2026-09-06-power-search-c-semantic-design.md) and built by docs/superpowers/plans/2026-09-06-power-search-c-semantic.md — the six open questions below are answered there as D14–D21.`

- [ ] **Step 4: Verify prose is unwrapped, run everything, commit**

```bash
~/code/praxis-workspace/praxis-halo/bin/unwrap-md CLAUDE.md docs/superpowers/specs/2026-09-06-power-search-c-semantic-design.md docs/superpowers/handoffs/2026-09-06-power-search-phase-2-semantic-handoff.md
uv run pytest -q && uv run ruff check . && uv run mypy
git add CLAUDE.md docs/superpowers/specs/2026-09-06-power-search-c-semantic-design.md docs/superpowers/handoffs/2026-09-06-power-search-phase-2-semantic-handoff.md
git commit -m "the rules should say which stage searches by meaning and why it never widens a result that had members

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017AZb57CHEGYwXATffrFjBR"
```

- [ ] **Step 5: Live steps — each one waits for its own owner yes (`one-at-a-time`)**

These run on the owner's machine against `~/.config/movie-brain/movie-brain.db`. Announce each before running; never run two on one yes.

1. `uv sync --extra semantic` — installs the extra into `.venv` (torch is large; the model itself is already cached). **Verify afterwards** that a plain `uv run movie-brain status` does not uninstall the extra: `uv run` performs an inexact sync by default and should keep it; if it does not, the owner runs `uv sync --extra semantic` after every `uv sync`, and CLAUDE.md's Data section says so.
2. `uv run movie-brain migrate` (dry run, lists `019_embeddings.sql`) then, on a yes, `uv run movie-brain migrate --apply` — a backup lands in `<config_dir>/backups/` first.
3. `uv run movie-brain embed` (dry run; expect the worklist at about 4,569 with a handful of no-prose films) then, on a yes, `uv run movie-brain embed --apply` — expected under a minute including model load.
4. `uv run movie-brain status` shows `embeddings` ≈ `prose`. `uv run pytest -q -m semantic` runs the one real-model test.
5. UAT in the dashboard, owner-driven: `hard boiled San Francisco private investigator` (expect The Maltese Falcon and The Big Sleep at the top with the "closest by meaning" hint), `big sleep` (The Big Sleep still first), `genre: film noir` (unchanged, unranked), `lonely samurai wanders japan`. Record what the owner says under the spec's §1 table as a UAT line, as Plan B did.

Then invoke `superpowers:finishing-a-development-branch`.

---

## Self-review

**Spec coverage.** §3 data model → Task 2. §4 `embedding_text` → Task 1. §5 stage 4, both modes, the two hints, the contract unchanged → Task 5 + Task 6's web test. §6 code placement → Tasks 1–6 file for file; `status` line → Task 2's `summary()` keys. §7 verb → Task 4 + Task 6. §8 degradation: extra absent → Task 5 scenario + Task 6 CLI tests + `available()` gating; model cannot load → `SemanticUnavailable` caught in `_semantic_stage` and logged once by `VectorIndex.embed_query`; empty table → `test_an_empty_index_answers_nothing_without_error`; no prose → Task 4 scenario; re-enriched → Task 2 unit + Task 4 scenario; model changed → Task 2 unit (`m2`). §9 tests → the `FakeEmbedder` table above, each scenario named. D14–D21 each appear in a task. Two spec inaccuracies found while planning (the `schema_version` column set, the mypy override) are corrected in Task 7 rather than silently diverged from.

**Placeholders.** None: every step carries its code. Helper names were checked against the repository while planning (`external_ids_for` exists; there is no `disposition_note` or `_count`, so the plan reads `film_disposition.note` directly and adds `prose_count`).

**Type consistency.** `run_search(repo, text, index=None)` (Task 5) matches `create_app`'s call (Task 6); `VectorIndex(repo, embedder, model=EMBED_MODEL)` (Task 3) matches Tasks 5–6; `write_embeddings(rows, today, *, model, dim)` (Task 2) matches Task 4's `flush` and every test; `embedding_summary -> tuple[int, str]` (Task 2) matches the `_stamp` comparison (Task 3); `EmbedReport(scanned, embedded, skipped_no_prose)` (Task 4) matches Task 6's CLI test; `FakeEmbedder.asked` / `.calls` (Tasks 3–4) match every step that reads them.
