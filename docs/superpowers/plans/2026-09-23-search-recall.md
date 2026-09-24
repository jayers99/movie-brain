# Search Recall Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the bar find what the data already holds — `time loops` finds Groundhog Day and `dystopian` finds the 72 films tagged `dystopia` — by stemming both word stages, letting meaning add films instead of only re-ordering them, and measuring a stronger model before adopting it, every step scored on a keyword benchmark built from the catalogue itself.

**Architecture:** Three independent changes behind one benchmark. (1) Migration 030 rebuilds the prose FTS with Porter and adds a Porter index over TMDB keywords; the keyword field and the freeform keyword signal read that index, with the existing fuzzy ladder covering the forms Porter cannot (`dystopian` → `dystopia`). (2) `_semantic_stage` keeps one mode: the nearest N films by meaning always join the result under the word hits, with a count (`SEMANTIC_NEAREST` 10) and a loose ceiling (`SEMANTIC_CEILING` 0.8) replacing the 0.6 floor. (3) `model`/`dim` become parameters everywhere they were globals, so the benchmark can embed a database COPY with `all-mpnet-base-v2` and the constants change only if it wins. `scripts/search_benchmark.py` runs ~300 TMDB keywords as queries (verbatim and a plural variant) through `run_search` against a copy and reports hit rate and recall@10; its numbers go in the trial log at the end of this plan.

**Tech Stack:** Python 3, SQLite FTS5 (`porter unicode61`), sentence-transformers (optional extra), numpy, pytest + pytest-bdd.

**Spec:** `docs/superpowers/specs/2026-09-23-search-recall-design.md` (D1–D8), superseding `2026-09-06-power-search-c-semantic-design.md` on D16 and D18.

## Global Constraints

- The benchmark NEVER runs against the live database (`~/.config/movie-brain/movie-brain.db` or `$MOVIE_BRAIN_CONFIG_DIR/movie-brain.db`): the script refuses that path. Copies live in the session scratchpad.
- The test suite never imports torch and never loads the real model; the one `@pytest.mark.semantic` test stays the sole exception. Every new test uses `FakeEmbedder` from `tests/conftest.py`.
- Migration 030 is a new file; 001–029 are never edited. It is wrapped in `BEGIN; … COMMIT;`.
- `EMBED_MODEL` / `EMBED_DIM` in `domain/search.py` stay the one configured pair; Task 6 changes them only on a benchmark win and the live re-embed runs by hand behind the owner's "proceed" (the catch-up chain would otherwise re-embed 5,052 films at the next sync).
- Hint strings are contract text: `"no exact match — showing the {n} closest by meaning"` and `"semantic search is not installed — uv sync --extra semantic"` stay verbatim; the new one is `"{n} more by meaning"`.
- No hard-wrapped prose in any `.md`. Commit messages: one line, why-focused, ending with the attribution line the session carries.
- The dashboard the owner runs (`movie-brain dashboard`, port 5556) is his process: never restart it; the live check at the end asks him to.

## Review Focus

1. A keyword phrase with a double quote or an FTS operator (`"`, `AND`, `NOT`, `*`) typed in freeform or `keyword:` must not raise from FTS5 — Task 3's `fts_phrase` doubles quotes and wraps the whole value as one phrase; test in Task 3.
2. `write_credits` re-running for a film (its rows are DELETEd then re-INSERTed) must leave `film_keyword_fts` with exactly one row per keyword — no duplicates, no orphans; test in Task 2.
3. `merge_film` moving a loser's keywords onto the survivor must move the FTS rows too (the INSERT OR IGNORE + DELETE path fires the triggers; an IGNOREd insert fires nothing); test in Task 2.
4. A word search whose only hits are far by meaning (every distance above `SEMANTIC_CEILING`) must return the word hits unchanged with NO "more by meaning" hint; and a field that excludes every meaning-only film must leave the result exactly the word hits; tests in Task 4.
5. A vector row written by another model (a half-finished re-embed) must never enter the matrix — `all_embeddings(model)` already filters, and `pack`/`unpack` with the wrong `dim` must raise rather than silently reshape; tests in Task 5.

---

### Task 1: The keyword benchmark and its baseline

**Files:**
- Create: `scripts/search_benchmark.py`
- Test: `tests/unit/test_search_benchmark.py`
- Modify (trial log only): `docs/superpowers/plans/2026-09-23-search-recall.md` (this file, "Trial log" section at the end)

**Interfaces:**
- Consumes: `movie_brain.application.search.run_search(repo, text, index=)`, `movie_brain.infrastructure.embeddings.VectorIndex(repo, embedder, model=)`, `SentenceTransformerEmbedder(model_name)`, `movie_brain.application.embed.embed_films`, `Repository(db_path, migrate=True)`.
- Produces: pure functions `pick_keywords(rows, sample, seed, lo, hi) -> list[tuple[str, frozenset[int]]]`, `plural(query: str) -> str | None`, `score(expected: frozenset[int], ids: Sequence[int]) -> tuple[bool, float]`, and `run_benchmark(repo, index, queries: list[tuple[str, frozenset[int]]]) -> Report` where `Report` is a dataclass `(rows: list[Row], hit_rate: float, recall10: float, mean_size: float)` and `Row = (query, expected_n, hit, recall10, size)`. Task 6 reuses `--model/--dim/--embed`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_search_benchmark.py
"""scripts/search_benchmark.py is loaded by path, like tests/unit/test_benchmark.py does for the
matching benchmark: scripts/ is not a package."""
from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from movie_brain.application.embed import embed_films
from movie_brain.domain.models import CastRow, Film, TmdbCredits
from movie_brain.infrastructure.embeddings import VectorIndex

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
DAY = date(2026, 9, 23)


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def bench() -> Any:
    return _load("search_benchmark", SCRIPTS_DIR / "search_benchmark.py")


def _credits(tmdb_id, title, overview, keywords):
    return TmdbCredits(
        tmdb_id=tmdb_id, imdb_id=None, title=title, original_title=title, year=None, runtime_min=None,
        alt_titles=(), overview=overview, tagline=None, genres=("Drama",), keywords=keywords,
        cast=(CastRow(1, "Someone", "Lead", 0),), crew=(),
    )


def test_pick_keywords_is_deterministic_and_bounded(bench):
    rows = [("one", frozenset({1})), ("mid", frozenset({1, 2, 3})), ("big", frozenset(range(40)))]
    picked = bench.pick_keywords(rows, sample=5, seed=7, lo=3, hi=30)
    assert picked == [("mid", frozenset({1, 2, 3}))]           # only the in-range keyword survives
    assert bench.pick_keywords(rows, sample=5, seed=7, lo=3, hi=30) == picked  # same seed, same pick


def test_plural_adds_an_s_to_the_last_word_unless_it_already_ends_in_s(bench):
    assert bench.plural("time loop") == "time loops"
    assert bench.plural("dystopia") == "dystopias"
    assert bench.plural("robots") is None


def test_score_is_hit_and_capped_recall_at_ten(bench):
    expected = frozenset({1, 2, 3})
    assert bench.score(expected, [9, 2, 8]) == (True, pytest.approx(1 / 3))
    assert bench.score(expected, [9, 8]) == (False, 0.0)
    wide = frozenset(range(30))
    assert bench.score(wide, list(range(10))) == (True, pytest.approx(1.0))  # 10 of 30 in the top ten is a full score


def test_run_benchmark_scores_a_corpus_through_the_real_pipeline(repo, fake_embedder, bench):
    a = repo.create_film(Film("Alpha", 1946, None, ""))
    b = repo.create_film(Film("Beta", 1950, None, ""))
    repo.write_credits(a, _credits(1, "Alpha", "A private eye.", ("film noir",)), DAY)
    repo.write_credits(b, _credits(2, "Beta", "A nurse in the ward.", ("hospital",)), DAY)
    embed_films(repo, fake_embedder, DAY, apply=True, log=lambda _: None)
    index = VectorIndex(repo, fake_embedder)
    report = bench.run_benchmark(repo, index, [("film noir", frozenset({a})), ("hospital", frozenset({b})), ("nothing here", frozenset({a}))])
    assert [r.query for r in report.rows] == ["film noir", "hospital", "nothing here"]
    assert [r.hit for r in report.rows] == [True, True, False]
    assert report.hit_rate == pytest.approx(2 / 3)


def test_the_script_refuses_the_live_database(bench, tmp_path, monkeypatch):
    monkeypatch.setenv("MOVIE_BRAIN_CONFIG_DIR", str(tmp_path))
    live = tmp_path / "movie-brain.db"
    live.write_bytes(b"")
    with pytest.raises(SystemExit) as exc:
        bench.main(["--db", str(live)])
    assert "live database" in str(exc.value)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_search_benchmark.py -q`
Expected: FAIL at the `bench` fixture — `FileNotFoundError` for `scripts/search_benchmark.py`.

- [ ] **Step 3: Write the script**

```python
# scripts/search_benchmark.py
"""Keyword benchmark for the search bar (search-recall spec D8). Read-only over a COPY of the
database, never the live one.

  uv run python scripts/search_benchmark.py --db <copy.db> [--sample 300] [--seed 7] [--min 3]
      [--max 30] [--model all-MiniLM-L6-v2 --dim 384] [--embed] [--label baseline] [--json out.json]

Queries are TMDB keywords held by --min..--max films (the tagged films are the answers), run
verbatim and as a plural variant (last word + "s") through `run_search`, plus two named rows:
"time loops" → Groundhog Day (#4850) and "dystopian" → every film tagged `dystopia`. Scores:
hit rate (at least one tagged film anywhere in the result) and recall@10 (tagged films in the
top ten over min(10, tagged)). --embed re-embeds the copy with --model first (a model trial).
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from movie_brain.application.embed import embed_films  # noqa: E402
from movie_brain.application.search import run_search  # noqa: E402
from movie_brain.domain.search import EMBED_DIM, EMBED_MODEL  # noqa: E402
from movie_brain.infrastructure.database import Repository  # noqa: E402
from movie_brain.infrastructure.embeddings import SentenceTransformerEmbedder, VectorIndex  # noqa: E402

GROUNDHOG_DAY = 4850


@dataclass(frozen=True)
class Row:
    query: str
    expected_n: int
    hit: bool
    recall10: float
    size: int


@dataclass(frozen=True)
class Report:
    rows: list[Row]
    hit_rate: float
    recall10: float
    mean_size: float


def pick_keywords(rows: Sequence[tuple[str, frozenset[int]]], sample: int, seed: int, lo: int, hi: int) -> list[tuple[str, frozenset[int]]]:
    eligible = sorted((k, ids) for k, ids in rows if lo <= len(ids) <= hi)
    rng = random.Random(seed)
    return eligible if len(eligible) <= sample else sorted(rng.sample(eligible, sample))


def plural(query: str) -> str | None:
    words = query.split()
    if not words or words[-1].endswith("s"):
        return None
    return " ".join(words[:-1] + [words[-1] + "s"])


def score(expected: frozenset[int], ids: Sequence[int]) -> tuple[bool, float]:
    top = set(ids[:10]) & expected
    return bool(expected & set(ids)), len(top) / min(10, len(expected)) if expected else 0.0


def run_benchmark(repo: Repository, index: VectorIndex | None, queries: list[tuple[str, frozenset[int]]]) -> Report:
    rows = []
    for q, expected in queries:
        ids = run_search(repo, q, index=index).ids
        hit, r10 = score(expected, ids)
        rows.append(Row(q, len(expected), hit, r10, len(ids)))
    n = len(rows) or 1
    return Report(rows, sum(r.hit for r in rows) / n, sum(r.recall10 for r in rows) / n, sum(r.size for r in rows) / n)


def _keyword_rows(repo: Repository) -> dict[str, frozenset[int]]:
    with repo._conn() as c:  # read-only; the script is a tool beside the repository, not a use case
        out: dict[str, set[int]] = {}
        for r in c.execute("SELECT keyword, film_id FROM film_keyword"):
            out.setdefault(str(r[0]), set()).add(int(r[1]))
    return {k: frozenset(v) for k, v in out.items()}


def _live_db() -> Path:
    cfg = os.environ.get("MOVIE_BRAIN_CONFIG_DIR")
    return (Path(cfg) if cfg else Path.home() / ".config" / "movie-brain") / "movie-brain.db"


def main(argv: Sequence[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True, type=Path)
    ap.add_argument("--sample", type=int, default=300)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--min", type=int, default=3)
    ap.add_argument("--max", type=int, default=30)
    ap.add_argument("--model", default=EMBED_MODEL)
    ap.add_argument("--dim", type=int, default=EMBED_DIM)
    ap.add_argument("--embed", action="store_true", help="re-embed the copy with --model before scoring")
    ap.add_argument("--label", default="run")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)
    if args.db.resolve() == _live_db().resolve():
        sys.exit("refusing to run on the live database; copy it first")
    repo = Repository(args.db, migrate=True)
    embedder = SentenceTransformerEmbedder(args.model)
    if args.embed:
        t0 = time.perf_counter()
        report = embed_films(repo, embedder, date.today(), apply=True, model=args.model, dim=args.dim, log=lambda m: print(m, file=sys.stderr))
        print(f"embedded {report.embedded} with {args.model} in {time.perf_counter() - t0:.0f}s", file=sys.stderr)
    index = VectorIndex(repo, embedder, model=args.model, dim=args.dim)
    kw = _keyword_rows(repo)
    picked = pick_keywords(list(kw.items()), args.sample, args.seed, args.min, args.max)
    verbatim = run_benchmark(repo, index, picked)
    variants = [(p, ids) for q, ids in picked if (p := plural(q))]
    plurals = run_benchmark(repo, index, variants)
    named = run_benchmark(repo, index, [("time loops", frozenset({GROUNDHOG_DAY})), ("dystopian", kw.get("dystopia", frozenset()))])
    t0 = time.perf_counter()
    embedder.encode(["a short query"])
    warm_ms = (time.perf_counter() - t0) * 1000
    print(f"{args.label}: model={args.model} keywords={len(picked)} warm-encode={warm_ms:.0f}ms")
    print(f"{'set':<10}{'n':>6}{'hit rate':>10}{'recall@10':>11}{'mean size':>11}")
    for name, rep in (("verbatim", verbatim), ("plural", plurals)):
        print(f"{name:<10}{len(rep.rows):>6}{rep.hit_rate:>10.3f}{rep.recall10:>11.3f}{rep.mean_size:>11.1f}")
    for r in named.rows:
        print(f"  {r.query!r}: expected {r.expected_n}, hit={r.hit}, recall@10={r.recall10:.2f}, size={r.size}")
    if args.json:
        args.json.write_text(json.dumps({"label": args.label, "model": args.model, "warm_ms": warm_ms,
                                         "verbatim": asdict(verbatim), "plural": asdict(plurals), "named": asdict(named)}, indent=1))


if __name__ == "__main__":
    main()
```

Note for the implementer: `embed_films(..., model=, dim=)` and `VectorIndex(..., dim=)` do not exist until Task 5. For this task pass neither (`embed_films(repo, embedder, date.today(), apply=True, log=…)`, `VectorIndex(repo, embedder, model=args.model)`) and add the two keyword arguments in Task 5's Step 5. `--embed` with a non-default `--dim` is therefore unusable until Task 5 — say so in the `--embed` help text until then.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_search_benchmark.py -q`
Expected: 5 passed.

- [ ] **Step 5: Baseline run on a copy of the live database**

```bash
S=/private/tmp/claude-501/-Users-jayers-code-movie-brain/4c23cb1a-63f1-47f6-9c9c-ae48338dca4d/scratchpad/bench
mkdir -p "$S" && cp ~/.config/movie-brain/movie-brain.db "$S/baseline.db"
uv run python scripts/search_benchmark.py --db "$S/baseline.db" --label baseline --json "$S/baseline.json" 2>"$S/baseline.err" | tee "$S/baseline.txt"
```

Copy the printed table into the "Trial log" section at the end of this file under "Baseline (before Task 2)". Expected shape: `"time loops"` hit=False, `"dystopian"` recall@10 low (9 films returned, few tagged), verbatim hit rate high (keywords match themselves exactly), plural hit rate markedly lower.

- [ ] **Step 6: Commit**

```bash
git add scripts/search_benchmark.py tests/unit/test_search_benchmark.py docs/superpowers/plans/2026-09-23-search-recall.md docs/superpowers/specs/2026-09-23-search-recall-design.md docs/backlog.md
git commit -m "search: a keyword benchmark from the catalogue's own TMDB tags, because the recall work needs a number to beat before it changes anything"
```

---

### Task 2: Migration 030 — Porter on the prose index, a Porter index over keywords

**Files:**
- Create: `migrations/030_search_stemming.sql`
- Test: `tests/unit/test_database.py` (new tests after `test_migration_018_creates_credit_tables_and_trigram_indexes`, line ~1860)

**Interfaces:**
- Produces: FTS5 table `film_keyword_fts(film_id UNINDEXED, keyword)` with `tokenize='porter unicode61'`, kept in step by triggers `film_keyword_ai` / `film_keyword_ad`; `film_text_fts` rebuilt with `tokenize='porter unicode61'` (same columns, same external content). Task 3 reads `film_keyword_fts`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_database.py — after test_migration_018_creates_credit_tables_and_trigram_indexes
def test_migration_030_stems_the_prose_index_and_indexes_keywords_with_porter(repo):
    """The FTS5 tokenizer cannot be altered in place: 030 drops and recreates film_text_fts with
    Porter and rebuilds it from film_text (the base table is the truth), and gives film_keyword
    its own standalone Porter index kept in step by triggers — standalone because film_keyword
    has a composite key and no INTEGER PRIMARY KEY, so its rowids are not VACUUM-stable."""
    with sqlite3.connect(repo.db_path) as c:
        sql = {r[0]: r[1] for r in c.execute("SELECT name, sql FROM sqlite_master WHERE name IN ('film_text_fts', 'film_keyword_fts')")}
        assert "porter" in sql["film_text_fts"] and "porter" in sql["film_keyword_fts"]
        names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")}
        assert {"film_keyword_ai", "film_keyword_ad", "film_text_ai", "film_text_ad", "film_text_au"} <= names
        assert c.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] >= 30
        c.execute("INSERT INTO films (guid, title, year, key) VALUES ('g1', 'Groundhog Day', 1993, 'groundhog day (1993)')")
        fid = c.execute("SELECT id FROM films WHERE title = 'Groundhog Day'").fetchone()[0]
        c.execute("INSERT INTO film_text (film_id, title, overview, plot) VALUES (?, 'Groundhog Day', NULL, 'finds himself in a time loop')", (fid,))
        # the plural reaches the singular through the stem
        assert c.execute("SELECT rowid FROM film_text_fts WHERE film_text_fts MATCH '\"loops\"'").fetchall() == [(fid,)]
        c.execute("INSERT INTO film_keyword (film_id, keyword) VALUES (?, 'time loop')", (fid,))
        assert c.execute("SELECT film_id FROM film_keyword_fts WHERE film_keyword_fts MATCH '\"time loops\"'").fetchall() == [(fid,)]
        c.execute("DELETE FROM film_keyword WHERE film_id = ?", (fid,))
        assert c.execute("SELECT COUNT(*) FROM film_keyword_fts").fetchone()[0] == 0


def test_rewriting_credits_and_merging_keep_one_keyword_fts_row_per_keyword(repo):
    """write_credits DELETEs then re-INSERTs a film's keywords and merge_film moves a loser's
    with INSERT OR IGNORE + DELETE; both must leave film_keyword_fts exact (an IGNOREd insert
    fires no trigger, so a keyword the survivor already holds is neither duplicated nor lost)."""
    day = date(2026, 9, 23)
    a = repo.create_film(Film("Alpha", 1946, None, ""))
    b = repo.create_film(Film("Beta", 1946, None, ""))
    repo.write_credits(a, _credits(keywords=("film noir", "private investigator")), day)
    repo.write_credits(a, _credits(keywords=("film noir", "heist")), day)  # re-enrichment replaces the set
    repo.write_credits(b, _credits(tmdb_id=911, keywords=("film noir", "vampire")), day)
    with sqlite3.connect(repo.db_path) as c:
        rows = lambda: sorted(c.execute("SELECT film_id, keyword FROM film_keyword_fts").fetchall())
        assert rows() == [(a, "film noir"), (a, "heist"), (b, "film noir"), (b, "vampire")]
    repo.merge_film(b, a, day, note="twin")
    with sqlite3.connect(repo.db_path) as c:
        assert rows() == [(a, "film noir"), (a, "heist"), (a, "vampire")]
```

(`_credits(**over)` is the existing helper at line ~1863 of this test file; `merge_film(loser, survivor, day, note=)` is the existing signature used by `test_merge_moves_credits_keywords_and_text_to_the_survivor`. If `films` needs more NOT NULL columns than `guid, title, year, key` in the first test, create the film through `repo.create_film(Film("Groundhog Day", 1993, None, ""))` instead and read its id.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_database.py -k "030 or keyword_fts" -q`
Expected: 2 failed — `KeyError: 'film_keyword_fts'` and `no such table: film_keyword_fts`.

- [ ] **Step 3: Write the migration**

```sql
-- migrations/030_search_stemming.sql
-- Backlog 41 (search-recall spec D1–D2). Two word stages get an English stemmer.
--
-- 1. film_text_fts: an FTS5 tokenizer cannot be changed in place, so the virtual table is
--    dropped and recreated with Porter, then rebuilt from film_text — the base table is the
--    truth (018's own rule). The three triggers on film_text reference the index by name and
--    survive the drop untouched. `time loops` now reaches "finds himself in a time loop".
-- 2. film_keyword_fts: a STANDALONE FTS5 table (film_id unindexed + the keyword), not an
--    external-content index, because film_keyword has a composite PRIMARY KEY and no INTEGER
--    PRIMARY KEY, so its rowids are not stable across VACUUM. 43k short strings cost nothing
--    to duplicate. Two triggers keep it in step: film_keyword is only ever inserted into or
--    deleted from (write_credits, merge_film), never updated in place. An INSERT OR IGNORE
--    that is ignored fires no trigger, which is exactly right.
-- Porter measured 2026-09-23 on SQLite 3.54: loops/loop, vampires/vampire, robots/robot,
-- haunting/haunted unify; dystopian/dystopia do NOT (no -ian rule) — that case is the
-- freeform keyword ladder's job (application code), not this migration's.
BEGIN;
DROP TABLE film_text_fts;
CREATE VIRTUAL TABLE film_text_fts USING fts5(title, overview, plot, content='film_text', content_rowid='film_id', tokenize='porter unicode61');
INSERT INTO film_text_fts(film_text_fts) VALUES ('rebuild');

CREATE VIRTUAL TABLE film_keyword_fts USING fts5(film_id UNINDEXED, keyword, tokenize='porter unicode61');
INSERT INTO film_keyword_fts (film_id, keyword) SELECT film_id, keyword FROM film_keyword;
CREATE TRIGGER film_keyword_ai AFTER INSERT ON film_keyword BEGIN
    INSERT INTO film_keyword_fts (film_id, keyword) VALUES (new.film_id, new.keyword);
END;
CREATE TRIGGER film_keyword_ad AFTER DELETE ON film_keyword BEGIN
    DELETE FROM film_keyword_fts WHERE film_id = old.film_id AND keyword = old.keyword;
END;
INSERT INTO schema_version (version) VALUES (30);
COMMIT;
```

- [ ] **Step 4: Run the tests to verify they pass, then the whole database file**

Run: `uv run pytest tests/unit/test_database.py -q`
Expected: all pass (the 018 test still finds its trigger names; `test_write_credits_indexes_names_and_characters_for_misspellings` still matches `'sternwood'` — Porter leaves it alone).

- [ ] **Step 5: Rehearse the migration on a copy and re-run the benchmark**

```bash
S=/private/tmp/claude-501/-Users-jayers-code-movie-brain/4c23cb1a-63f1-47f6-9c9c-ae48338dca4d/scratchpad/bench
cp ~/.config/movie-brain/movie-brain.db "$S/stem.db"
uv run python scripts/search_benchmark.py --db "$S/stem.db" --label stem-only --json "$S/stem.json" 2>"$S/stem.err" | tee "$S/stem.txt"
```

`Repository(db, migrate=True)` applies 030 to the copy. Record the table in the trial log under "After migration 030 (Task 2, index only — the code still matches keywords by string)". `"time loops"` should now be a lexical hit through the prose; `"dystopian"` unchanged until Task 3.

- [ ] **Step 6: Commit**

```bash
git add migrations/030_search_stemming.sql tests/unit/test_database.py docs/superpowers/plans/2026-09-23-search-recall.md
git commit -m "search: Porter on the prose index and a Porter index over keywords, because a plural hid a film whose plot said the singular"
```

---

### Task 3: The keyword field and the freeform keyword signal read the stemmed index

**Files:**
- Modify: `src/movie_brain/domain/search.py` (constants ~line 38–55; add `fts_phrase` beside `fts_words` ~line 243)
- Modify: `src/movie_brain/infrastructure/database.py` (`keyword_candidates` ~1722; `_filter_sql` keyword branch ~1801; `_freeform_scores` keyword signal ~1880)
- Modify: `src/movie_brain/application/search.py` (`_Resolver.keyword` ~100)
- Modify: `.claude/rules/search.md` (line 3's "Keywords are stored but never load-bearing" and line 4's genre/keyword clause)
- Test: `tests/unit/test_search.py`, `tests/unit/test_database.py`, `tests/features/search.feature`, `tests/step_defs/test_search.py`

**Interfaces:**
- Produces: `fts_phrase(text) -> str` in `domain/search.py` (the whole text as ONE FTS5 phrase, inner quotes doubled: `'"time loops"'`); `FREEFORM_KEYWORD_FLOOR = 0.9`; `Repository.keywords_matching(phrase: str) -> list[str]` (distinct stored keywords whose stemmed form matches the phrase); `Repository.keyword_ladder(free: str) -> str | None` (the top `rank_candidates` keyword at or above `FREEFORM_KEYWORD_FLOOR`, else None). `Filter("keyword", values=(phrase, …))` values are now phrases matched through `film_keyword_fts`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_search.py — beside test_fts_words_quotes_each_word_and_drops_short_ones_when_asked
def test_fts_phrase_wraps_the_whole_value_and_doubles_inner_quotes():
    assert fts_phrase("time loops") == '"time loops"'
    assert fts_phrase('say "cheese" AND NOT run*') == '"say ""cheese"" AND NOT run*"'  # operators are inert inside a phrase
    assert fts_phrase("   ") == ""


def test_freeform_keyword_floor_is_stricter_than_the_field_correction_floor():
    assert FREEFORM_KEYWORD_FLOOR == 0.9 > CORRECTION_FLOOR
```

```python
# tests/unit/test_database.py — after test_search_films_title_keyword_and_plot_filters
def test_keyword_filter_and_freeform_signal_match_through_the_stem(repo):
    """`keyword: loops` reaches the keyword "time loop"; freeform "vampires" scores films tagged
    "vampire" at W_TAG; an FTS operator typed by the user is inert (one phrase, never a syntax
    error); and the ladder covers what Porter cannot: "dystopian" → "dystopia"."""
    a, b, g = _seed_search(repo)
    day = date(2026, 9, 23)
    repo.write_credits(a, _credits(keywords=("time loop", "vampire")), day)
    repo.write_credits(b, _credits(tmdb_id=911, keywords=("dystopia",)), day)
    ids = lambda filters, free="": [i for i, _ in repo.search_films(filters, free)]
    assert ids([Filter("keyword", values=('"loops"',))]) == [a]
    assert ids([Filter("keyword", values=('"time loops"',))]) == [a]
    assert ids([Filter("keyword", values=('"loop AND NOT vampire*"',))]) == []   # a phrase, not a query
    assert repo.keywords_matching('"vampires"') == ["vampire"]
    assert repo.keywords_matching('"dystopian"') == []                            # Porter has no -ian rule
    assert repo.keyword_ladder("dystopian") == "dystopia"
    assert repo.keyword_ladder("dystopian future") is None                       # 0.80 to "distant future" is refused
    assert dict(repo.search_films([], "vampires"))[a] == pytest.approx(W_TAG)
    assert dict(repo.search_films([], "dystopian"))[b] == pytest.approx(W_TAG)
    assert dict(repo.search_films([], "vampire"))[a] == pytest.approx(W_TAG)      # an exact hit is not double-counted by the ladder
```

```gherkin
# tests/features/search.feature — after "A keyword typo is corrected against the keyword vocabulary"
  Scenario: A keyword typed in another form is found through its stem, uncorrected
    When I search for "keyword: hospitals"
    Then the result ids are Beta
    And there are no corrections

  Scenario: A freeform word reaches a keyword Porter cannot stem through the ladder
    Given Alpha is also tagged dystopia
    When I search for "dystopian"
    Then the result ids are Alpha
```

```python
# tests/step_defs/test_search.py — a new Given beside `kino`
@given("Alpha is also tagged dystopia")
def alpha_dystopia(repo, films):
    repo.write_credits(films["Alpha"], _credits(910, "Alpha", "A private eye.", ("film noir", "dystopia"),
                                                 (CastRow(4110, "Humphrey Bogart", "Philip Marlowe", 0),),
                                                 (CrewRow(2636, "Howard Hawks", "Director", "Directing"),)), DAY)
```

Add `fts_phrase`, `FREEFORM_KEYWORD_FLOOR`, `CORRECTION_FLOOR` to the imports at the top of `tests/unit/test_search.py`, and `W_TAG`, `Filter`, `pytest`, `date` to `tests/unit/test_database.py` if not already imported there.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_search.py tests/unit/test_database.py -k "fts_phrase or floor or through_the_stem" -q; uv run pytest tests/step_defs/test_search.py -k "stem or ladder" -q`
Expected: ImportError on `fts_phrase`; `AttributeError: keywords_matching`; the two scenarios fail (`hospitals` corrected or empty; `dystopian` empty).

- [ ] **Step 3: Implement**

`src/movie_brain/domain/search.py` — beside the other thresholds (`CORRECTION_FLOOR` etc.) and beside `fts_words`:

```python
# Freeform keyword ladder (search-recall spec D2): the forms Porter cannot unify (dystopian →
# dystopia) go through the same rank_candidates the `keyword:` field uses, but at a stricter
# floor — measured: dystopian→dystopia 0.94, time loops→time loop 0.95, vampires→vampire 0.93
# pass; "dystopian future"→"distant future" sits at exactly 0.80 and is a wrong match.
FREEFORM_KEYWORD_FLOOR = 0.9


def fts_phrase(text: str) -> str:
    """The whole text as ONE FTS5 phrase, so a user's AND / NOT / * are inert and a keyword of
    several words matches as a sequence. Inner quotes are doubled. Empty for blank text."""
    text = text.strip()
    return '"' + text.replace('"', '""') + '"' if text else ""
```

`src/movie_brain/infrastructure/database.py`:

```python
    def keywords_matching(self, phrase: str) -> list[str]:
        """Distinct stored keywords whose stemmed form matches the FTS phrase (migration 030)."""
        if not phrase:
            return []
        with self._conn() as c:
            rows = c.execute(
                "SELECT DISTINCT keyword FROM film_keyword_fts WHERE film_keyword_fts MATCH ? ORDER BY keyword", (phrase,)
            ).fetchall()
            return [str(r[0]) for r in rows]

    def keyword_ladder(self, free: str) -> str | None:
        """The one keyword the fuzzy ladder would use for a freeform string, at
        FREEFORM_KEYWORD_FLOOR (stricter than the field's CORRECTION_FLOOR), else None."""
        ranked = rank_candidates(free, self.keyword_candidates())
        return str(ranked[0].name) if ranked and ranked[0].score >= FREEFORM_KEYWORD_FLOOR else None
```

`_filter_sql`, replace the keyword branch:

```python
        if flt.kind == "keyword":
            if not flt.values:
                return "0 = 1", []
            parts = ["f.id IN (SELECT film_id FROM film_keyword_fts WHERE film_keyword_fts MATCH ?)"] * len(flt.values)
            return "(" + " OR ".join(parts) + ")", list(flt.values)
```

`_freeform_scores`, replace the `film_keyword` statement inside `if g:` with:

```python
            phrase = fts_phrase(free)
            tagged = c.execute(
                "SELECT DISTINCT film_id FROM film_keyword_fts WHERE film_keyword_fts MATCH ?", (phrase,)
            ).fetchall()
            if not tagged:  # Porter's blind spot: the ladder, never on top of a stem hit (no double count)
                chosen = self.keyword_ladder(free)
                if chosen is not None:
                    tagged = c.execute("SELECT film_id FROM film_keyword WHERE keyword = ?", (chosen,)).fetchall()
            add(tagged, W_TAG)
```

Import `FREEFORM_KEYWORD_FLOOR, fts_phrase, rank_candidates` from `movie_brain.domain.search` at the top of `database.py` (it already imports `fts_words` and the weights from there).

`src/movie_brain/application/search.py`, replace `_Resolver.keyword`:

```python
    def keyword(self, term: Term) -> None:
        # The stemmed index first (`hospitals` finds "hospital", no correction shown), then the
        # ladder for what Porter cannot unify; the filter value is always an FTS phrase.
        phrase = fts_phrase(term.value)
        if phrase and self.repo.keywords_matching(phrase):
            self.filters.append(Filter("keyword", values=(phrase,)))
            return
        values: tuple[str, ...] = ()
        if not term.exact:
            chosen = self._pick(term, self.repo.keyword_candidates())
            if chosen:
                values = (fts_phrase(str(chosen.key)),)
        self.filters.append(Filter("keyword", values=values))
```

(import `fts_phrase` from `movie_brain.domain.search`.) The existing scenario "A keyword typo is corrected against the keyword vocabulary" (`keyword: hospitl` → Beta with a correction) still passes: `hospitl` matches nothing through the stem, the ladder corrects it to `hospital`, and the filter phrase `"hospital"` matches.

- [ ] **Step 4: Run the tests to verify they pass, then the whole suite**

Run: `uv run pytest tests/unit/test_search.py tests/unit/test_database.py tests/step_defs/test_search.py -q`, then `uv run pytest -q`
Expected: all pass. `test_search_films_ors_a_repeated_field_for_every_kind` and `test_search_films_title_keyword_and_plot_filters` pass unchanged because a bare keyword string such as `film noir` is also a valid FTS query (two implicit-AND tokens) — if either asserts on an exact phrase form, wrap its values with `fts_phrase(...)`.

- [ ] **Step 5: Docs**

`.claude/rules/search.md`: in line 3 replace `Keywords are stored but never load-bearing (30% of films have none, spec D10)` with `Keywords are stored and, since 2026-09-23 (search-recall spec D2), matched through their own Porter index `film_keyword_fts` (migration 030) — a standalone FTS5 table, not external-content, because `film_keyword` has no INTEGER PRIMARY KEY; 30% of films still have none (D10)`. In line 4 replace `genre/keyword (3)` with `genre (3), keyword (3, through `film_keyword_fts` as one `fts_phrase`, and when the stem finds nothing the ladder at `FREEFORM_KEYWORD_FLOOR` 0.9 — never both, so a hit is never double-counted)`. Add to line 3's FTS sentence: `film_text_fts` and `film_keyword_fts` tokenize with `porter unicode61` since 030; Porter has no `-ian` rule (`dystopian`/`dystopia` do not unify — the ladder's job).

- [ ] **Step 6: Re-run the benchmark on a fresh copy; record**

```bash
S=/private/tmp/claude-501/-Users-jayers-code-movie-brain/4c23cb1a-63f1-47f6-9c9c-ae48338dca4d/scratchpad/bench
cp ~/.config/movie-brain/movie-brain.db "$S/stem2.db"
uv run python scripts/search_benchmark.py --db "$S/stem2.db" --label stem+ladder --json "$S/stem2.json" 2>"$S/stem2.err" | tee "$S/stem2.txt"
```

Record under "After Task 3". Expected: `"dystopian"` size ≈ 73, `"time loops"` hit; plural hit rate close to verbatim.

- [ ] **Step 7: Commit**

```bash
git add src/movie_brain/domain/search.py src/movie_brain/infrastructure/database.py src/movie_brain/application/search.py .claude/rules/search.md tests/ docs/superpowers/plans/2026-09-23-search-recall.md
git commit -m "search: the keyword field and the freeform keyword signal read the stemmed index, with the ladder for the forms Porter cannot unify"
```

---

### Task 4: Meaning adds films; a count replaces the distance floor

**Files:**
- Modify: `src/movie_brain/domain/search.py:49-55` (constants)
- Modify: `src/movie_brain/infrastructure/embeddings.py:143-149` (`VectorIndex.nearest`)
- Modify: `src/movie_brain/application/search.py:40-42, 197-231` (hints, `_semantic_stage`)
- Modify: `.claude/rules/search.md` line 5; `docs/superpowers/specs/2026-09-06-power-search-c-semantic-design.md` (one superseded note at D16 and D18)
- Test: `tests/unit/test_search.py:204`, `tests/unit/test_embeddings.py:40`, `tests/features/search.feature`, `tests/step_defs/test_search.py`

**Interfaces:**
- Produces: `SEMANTIC_NEAREST = 10`, `SEMANTIC_CEILING = 0.8` in `domain/search.py` (`MAX_DISTANCE` removed); `VectorIndex.nearest(vector, limit: int, ceiling: float) -> list[tuple[int, float]]` (nearest `limit` films with distance ≤ ceiling, by distance then id); `MORE_BY_MEANING_HINT = "{n} more by meaning"` in `application/search.py`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_search.py — replace test_semantic_constants_are_the_spec_values
def test_semantic_constants_are_the_spec_values():
    assert EMBED_MODEL == "all-MiniLM-L6-v2" and EMBED_DIM == 384
    assert SEMANTIC_NEAREST == 10 and SEMANTIC_CEILING == 0.8 and SEMANTIC_WEIGHT == 5.0
```

```python
# tests/unit/test_embeddings.py — replace test_nearest_orders_by_distance_inside_the_floor_and_ties_by_id
def test_nearest_is_a_count_under_a_ceiling_ordered_by_distance_then_id(repo, fake_embedder):
    films = _films(repo, 12)
    rows = [(films[0], pack(_unit(0))), (films[1], pack(_unit(0, 1)))] + [(f, pack(_unit(2))) for f in films[2:]]
    repo.write_embeddings(rows, D, model="m", dim=EMBED_DIM)
    idx = VectorIndex(repo, fake_embedder, model="m")
    q = _unit(0)
    assert idx.nearest(q, limit=10, ceiling=0.8) == [(films[0], pytest.approx(0.0)), (films[1], pytest.approx(1 - 2 ** -0.5))]  # the ten others sit at 1.0, past the ceiling
    wide = idx.nearest(q, limit=10, ceiling=2.0)
    assert len(wide) == 10 and wide[:2] == [(films[0], pytest.approx(0.0)), (films[1], pytest.approx(1 - 2 ** -0.5))]
    assert [i for i, _ in wide[2:]] == sorted(films[2:])[:8]  # ties at 1.0 break by id, and the count caps them
    assert len(idx) == 12
```

```gherkin
# tests/features/search.feature — replace "A title hit stays first when meaning re-ranks a lexical result" with these three
  Scenario: A title hit stays first when meaning re-ranks a lexical result
    Given the corpus is embedded by meaning
    When I search by meaning for "alpha"
    Then the result ids are Alpha then Beta
    And the result is ranked
    And the hints do not include "no exact match — showing the 2 closest by meaning"
    And the hints do not include "0 more by meaning"

  Scenario: Meaning adds films under the word hits and says how many
    Given Delta is a night-shift caregiver drama with no word in common
    And the corpus is embedded by meaning
    When I search by meaning for "ward"
    Then the result ids are Beta then Delta
    And the result is ranked
    And the hints include "1 more by meaning"

  Scenario: A field excludes the films meaning would have added
    Given Delta is a night-shift caregiver drama with no word in common
    And the corpus is embedded by meaning
    When I search by meaning for "ward director: hawks"
    Then the result ids are Beta
    And the hints do not include "1 more by meaning"

  Scenario: Nothing is added when no other film is near by meaning
    Given the corpus is embedded by meaning
    When I search by meaning for "sternwood"
    Then the result ids are Alpha
    And the hints do not include "1 more by meaning"
```

```python
# tests/step_defs/test_search.py — a new Given beside `corpus`
@given("Delta is a night-shift caregiver drama with no word in common")
def delta(repo, films):
    d = repo.create_film(Film("Delta", 1970, None, ""))
    repo.set_external_id(d, "tmdb", "913", DAY)
    repo.write_credits(d, _credits(913, "Delta", "A caregiver on the night shift.", (),
                                   (CastRow(78, "Someone Else", "Orderly", 0),), ()), DAY)
    films["Delta"] = d
```

Arithmetic with `FakeEmbedder` (concept dims: nurse/ward/caregiver → 1; alpha → 2; sternwood → 3; other words hash above dim 8): `ward` embeds to dim 1 alone. Beta's prose "A nurse in the alpha ward. Alpha shift." → dim1 = 2, dim2 = 2, one hashed word; norm 3; distance 1 − 2/3 = 0.333. Delta's prose "A caregiver on the night shift." → dim1 = 1 plus two hashed words; norm √3; distance 1 − 1/√3 = 0.423. Alpha's prose has no dim 1 → distance 1.0, past the 0.8 ceiling. So: Beta is the one word hit (bm25 overview 2 + bonus 5 × 0.667 = 5.33), Delta is meaning-only (5 × 0.577 = 2.89), Alpha is out. `director: hawks` keeps Alpha and Beta only, so Delta is excluded by the field. `sternwood` hits Alpha by plot and character; by meaning Alpha is 0.553 and Beta 1.0, so nothing is added. (`Someone Else` must not share a trigram with `hawks`/`bogart`.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_search.py tests/unit/test_embeddings.py -k "semantic_constants or nearest_is_a_count" -q; uv run pytest tests/step_defs/test_search.py -k "meaning" -q`
Expected: ImportError on `SEMANTIC_NEAREST`; `TypeError: nearest() got an unexpected keyword argument 'limit'`; the two new scenarios fail (Delta missing / hint missing).

- [ ] **Step 3: Implement**

`domain/search.py` lines 49–55 — replace `MAX_DISTANCE` with:

```python
# Semantic search (Plan C D14–D17; search-recall spec D3–D4 supersede D16/D18). The vector is over PROSE ONLY.
EMBED_MODEL = "all-MiniLM-L6-v2"
EMBED_DIM = 384
SEMANTIC_NEAREST = 10  # the net is a COUNT: ten nearest, whatever their distance, so it means the same under every model
SEMANTIC_CEILING = 0.8  # a loose sanity ceiling — only films the model calls unrelated are dropped (short-query distances cluster 0.5–0.7)
SEMANTIC_WEIGHT = 5.0  # one more SUMMED signal, 5 × (1 − distance): a title hit (10) stays above any meaning-only film
```

`embeddings.py` — replace `nearest`:

```python
    def nearest(self, vector: Sequence[float], limit: int, ceiling: float) -> list[tuple[int, float]]:
        """The `limit` nearest films with distance ≤ ceiling, by distance then id (D4)."""
        ids, scores = self._scores(vector)
        if scores is None:
            return []
        hits = [(ids[i], float(1.0 - s)) for i, s in enumerate(scores) if 1.0 - s <= ceiling]
        hits.sort(key=lambda t: (t[1], t[0]))
        return hits[:limit]
```

`application/search.py` — hints and `_semantic_stage`:

```python
SEMANTIC_HINT = "no exact match — showing the {n} closest by meaning"
MORE_BY_MEANING_HINT = "{n} more by meaning"
NO_SEMANTIC_HINT = "semantic search is not installed — uv sync --extra semantic"
```

```python
def _semantic_stage(
    repo: Repository,
    index: VectorIndex,
    free: str,
    ids: list[tuple[int, float]],
    filters: list[Filter],
) -> tuple[list[tuple[int, float]], str | None]:
    """Stage 4 (search-recall spec D3–D5, superseding Plan C D16/D18). ONE mode: the nearest
    SEMANTIC_NEAREST films under SEMANTIC_CEILING always join the result. A word hit keeps its
    lexical score plus the semantic bonus (D17: summed, a title hit stays first); a film reached
    by meaning alone carries the bonus and nothing else, and is APPENDED after every word hit
    rather than merged by score, so meaning never lifts a film past a word. Every meaning-only
    film must pass every field filter over the whole catalogue (D5). The hint names what
    meaning did: how many it added, or that it supplied the whole result. A model that cannot
    load leaves the lexical result untouched."""
    if len(index) == 0:
        return ids, None  # no vectors yet — never load the model for nothing to search
    try:
        query = index.embed_query(free)
    except SemanticUnavailable:
        return ids, None
    near = index.nearest(query, SEMANTIC_NEAREST, SEMANTIC_CEILING)
    dist = dict(near)
    present = {i for i, _ in ids}
    extra = [(i, d) for i, d in near if i not in present]
    if extra and filters:
        allowed = {i for i, _ in repo.search_films(filters, "")}
        extra = [(i, d) for i, d in extra if i in allowed]
    rescored = [(i, s + (SEMANTIC_WEIGHT * (1.0 - dist[i]) if i in dist else 0.0)) for i, s in ids]
    rescored.sort(key=lambda t: -t[1])  # stable: ties keep search_films' title order
    added = [(i, SEMANTIC_WEIGHT * (1.0 - d)) for i, d in extra]
    if not ids:
        return added, (SEMANTIC_HINT.format(n=len(added)) if added else None)
    return rescored + added, (MORE_BY_MEANING_HINT.format(n=len(added)) if added else None)
```

Note the re-rank bonus now applies inside the ceiling only to films that are among the ten nearest — a word hit outside the top ten gets no bonus. That is D4's consequence: `index.distances` is no longer needed by this stage (keep the method; `tests/unit/test_embeddings.py` still covers it).

- [ ] **Step 4: Run the tests to verify they pass, then the whole suite**

Run: `uv run pytest tests/unit/test_search.py tests/unit/test_embeddings.py tests/step_defs/test_search.py tests/web/test_api.py -q`, then `uv run pytest -q`
Expected: all pass. The existing supply-mode scenarios keep their hint: with no word hits, `added` is the whole result and the `SEMANTIC_HINT` wording is unchanged. "A field that excludes every near film leaves the result empty, not widened" still holds (`extra` filtered to nothing → `[]`, no hint).

- [ ] **Step 5: Docs**

`.claude/rules/search.md` line 5: replace the two-mode sentence (from `runs stage 4 in one of two modes (D16)` through `intersected with any field filters`) with: `runs stage 4 in ONE mode (search-recall spec D3–D5, superseding D16/D18): the `SEMANTIC_NEAREST` 10 nearest films under `SEMANTIC_CEILING` 0.8 always join the result — a word hit keeps its lexical score plus `SEMANTIC_WEIGHT` 5 × (1 − distance) (D17 summed, a title hit at 10 stays first), a film reached by meaning alone carries the bonus only and is APPENDED after every word hit, never merged by score, and must pass every field filter over the whole catalogue. The net is a count, not a distance, so it means the same under every model. Three hints are verbatim contract text: `"no exact match — showing the {n} closest by meaning"` (words found nothing), `"{n} more by meaning"` (words found something and meaning added n), and `"semantic search is not installed — uv sync --extra semantic"`.` In `docs/superpowers/specs/2026-09-06-power-search-c-semantic-design.md`, append to D16 and to D18 the one line: `*Superseded 2026-09-23 by `2026-09-23-search-recall-design.md` D3/D4.*`

- [ ] **Step 6: Re-run the benchmark; record**

```bash
S=/private/tmp/claude-501/-Users-jayers-code-movie-brain/4c23cb1a-63f1-47f6-9c9c-ae48338dca4d/scratchpad/bench
cp ~/.config/movie-brain/movie-brain.db "$S/union.db"
uv run python scripts/search_benchmark.py --db "$S/union.db" --label stem+union --json "$S/union.json" 2>"$S/union.err" | tee "$S/union.txt"
```

Record under "After Task 4". Expected: recall@10 up on both sets, mean size up by ≤ 10, hit rate not lower than Task 3's.

- [ ] **Step 7: Commit**

```bash
git add src/ tests/ .claude/rules/search.md docs/superpowers/specs/2026-09-06-power-search-c-semantic-design.md docs/superpowers/plans/2026-09-23-search-recall.md
git commit -m "search: meaning always adds its ten nearest under the word hits, because one literal hit used to switch it off entirely"
```

---

### Task 5: The model and its dimension are parameters, not globals

**Files:**
- Modify: `src/movie_brain/infrastructure/embeddings.py:26-45, 97-125` (`pack`, `unpack`, `VectorIndex.__init__`/`_ensure`)
- Modify: `src/movie_brain/application/embed.py:33-75` (`embed_films`)
- Modify: `scripts/search_benchmark.py` (pass `model=`/`dim=` — the two lines Task 1 deferred)
- Test: `tests/unit/test_embeddings.py`, `tests/step_defs/test_embed.py` or `tests/unit/test_database.py`

**Interfaces:**
- Produces: `pack(vector, dim: int = EMBED_DIM) -> bytes`, `unpack(blob, dim: int = EMBED_DIM) -> list[float]`, `VectorIndex(repo, embedder, model: str = EMBED_MODEL, dim: int = EMBED_DIM)`, `embed_films(..., model: str = EMBED_MODEL, dim: int = EMBED_DIM)`. Defaults keep every existing caller unchanged.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_embeddings.py — beside test_pack_refuses_the_wrong_dimension
def test_pack_and_unpack_take_the_dimension_as_a_parameter():
    v = [0.5, 0.5, 0.5, 0.5]
    assert unpack(pack(v, dim=4), dim=4) == pytest.approx(v)
    with pytest.raises(ValueError):
        pack(v)  # the default is still EMBED_DIM
    with pytest.raises(struct.error):
        unpack(pack(v, dim=4), dim=8)  # a blob of the wrong width never silently reshapes


def test_index_loads_one_models_rows_at_that_models_width(repo, fake_embedder):
    a, b = _films(repo, 2)
    repo.write_embeddings([(a, pack([1.0, 0.0, 0.0, 0.0], dim=4))], D, model="tiny", dim=4)
    repo.write_embeddings([(b, pack(_unit(0)))], D, model=EMBED_MODEL, dim=EMBED_DIM)   # another model's row, wider
    idx = VectorIndex(repo, fake_embedder, model="tiny", dim=4)
    assert len(idx) == 1
    assert idx.nearest([1.0, 0.0, 0.0, 0.0], limit=10, ceiling=2.0) == [(a, pytest.approx(0.0))]
```

```python
# tests/unit/test_database.py — beside test_embedding_worklist_is_prose_films_without_a_row_for_this_model
def test_embed_films_writes_the_model_and_dim_it_is_given(repo, fake_embedder):
    a, b, g = _seed_search(repo)
    class Four:
        def encode(self, texts):
            return [[1.0, 0.0, 0.0, 0.0] for _ in texts]
    report = embed_films(repo, Four(), date(2026, 9, 23), apply=True, model="tiny", dim=4, log=lambda _: None)
    assert report.embedded == 2
    with sqlite3.connect(repo.db_path) as c:
        assert c.execute("SELECT DISTINCT model, dim, length(vector) FROM film_embedding").fetchall() == [("tiny", 4, 16)]
    assert [t.film_id for t in repo.films_needing_embedding(EMBED_MODEL)] == [a, b]   # the configured model still wants them
    assert repo.films_needing_embedding("tiny") == []
```

(`_seed_search` gives Alpha and Beta prose rows and Gamma none; adjust the expected count to what the seed actually holds if it differs. Import `embed_films`, `EMBED_MODEL`, `struct` where needed.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_embeddings.py tests/unit/test_database.py -k "parameter or one_models_rows or model_and_dim" -q`
Expected: `TypeError: pack() got an unexpected keyword argument 'dim'` and the same for `VectorIndex` / `embed_films`.

- [ ] **Step 3: Implement**

`embeddings.py`:

```python
def _fmt(dim: int) -> str:
    return f"<{dim}f"  # yt-brain's `_to_blob`, byte for byte


def pack(vector: Sequence[float], dim: int = EMBED_DIM) -> bytes:
    if len(vector) != dim:
        raise ValueError(f"expected {dim} floats, got {len(vector)}")
    return struct.pack(_fmt(dim), *vector)


def unpack(blob: bytes, dim: int = EMBED_DIM) -> list[float]:
    return list(struct.unpack(_fmt(dim), blob))
```

(remove the module-level `_FORMAT`.) `VectorIndex.__init__` gains `dim: int = EMBED_DIM`, stored as `self.dim`; `_ensure` reshapes with `self.dim` instead of `EMBED_DIM`. Its docstring's "for one model" sentence gains: "and one width — `dim` — so a row written by another model is never reshaped into this matrix".

`embed.py` — `embed_films` signature gains `model: str = EMBED_MODEL, dim: int = EMBED_DIM` after `batch_size`; `flush` packs with `pack(v, dim)` and writes `model=model, dim=dim`; the worklist is `repo.films_needing_embedding(model, limit)`. Update the module docstring's last sentence (it says "Never called from `sync`", which has been false since enrichment-on-add): "Part of the catch-up chain since 2026-09-20, so a change of `EMBED_MODEL` re-embeds the whole catalogue at the next sync — run it by hand first (spec D6)."

`scripts/search_benchmark.py` — pass `model=args.model, dim=args.dim` to `embed_films` and `dim=args.dim` to `VectorIndex`; drop the temporary note from `--embed`'s help.

- [ ] **Step 4: Run the tests to verify they pass, then the whole suite**

Run: `uv run pytest tests/unit/test_embeddings.py tests/unit/test_database.py tests/unit/test_search_benchmark.py tests/step_defs/test_embed.py -q`, then `uv run pytest -q`
Expected: all pass; no behaviour change with the defaults.

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/infrastructure/embeddings.py src/movie_brain/application/embed.py scripts/search_benchmark.py tests/
git commit -m "embeddings: the model and its width are parameters with the configured pair as defaults, so a second model can be measured on a copy without editing code"
```

---

### Task 6: Measure all-mpnet-base-v2; adopt only on the numbers

**Files:**
- Modify (only on a win): `src/movie_brain/domain/search.py:50-51` (`EMBED_MODEL`, `EMBED_DIM`), `tests/unit/test_search.py` (the constants test), `tests/unit/test_embeddings_real.py` (asserts `len(a) == EMBED_DIM` — unchanged in text, re-run), `CLAUDE.md` (the "Model cache" paragraph and the `embed` verb line), `.claude/rules/search.md` line 5 (model name and dims)
- Modify (always): `docs/superpowers/plans/2026-09-23-search-recall.md` (trial log), `docs/backlog.md` (item 43's outcome)

**Interfaces:**
- Consumes: Task 1's `--model/--dim/--embed`, Task 5's parameters.

- [ ] **Step 1: Re-embed a copy with mpnet and run the benchmark (this is the hour-long step — background shell, log to a file, per the owner's long-jobs rule; check `pgrep -fl movie-brain` first)**

```bash
S=/private/tmp/claude-501/-Users-jayers-code-movie-brain/4c23cb1a-63f1-47f6-9c9c-ae48338dca4d/scratchpad/bench
cp ~/.config/movie-brain/movie-brain.db "$S/mpnet.db"
nohup uv run python scripts/search_benchmark.py --db "$S/mpnet.db" --model all-mpnet-base-v2 --dim 768 --embed --label mpnet --json "$S/mpnet.json" > "$S/mpnet.txt" 2> "$S/mpnet.err" &
```

The first run downloads ~420 MB to `~/.cache/huggingface/hub/models--sentence-transformers--all-mpnet-base-v2`. Record the table AND the `warm-encode=…ms` figure under "mpnet (Task 6)" in the trial log, beside Task 4's MiniLM row (same code, same keywords, same seed).

- [ ] **Step 2: Decide by the spec's rule (D7)**

Adopt if BOTH: (a) mpnet's plural-set recall@10 and hit rate are each at least as high as MiniLM's on the Task 4 run, with the named rows not worse; (b) warm encode of one short query < 50 ms. Otherwise decline. Write the decision and the two numbers that decided it in the trial log and in backlog item 43 (check it off with "measured, adopted" or "measured, declined — <numbers>").

- [ ] **Step 3 (adopt only): Change the constants and their tests**

`domain/search.py`: `EMBED_MODEL = "all-mpnet-base-v2"`, `EMBED_DIM = 768`. `tests/unit/test_search.py::test_semantic_constants_are_the_spec_values`: the new values. `CLAUDE.md` "Model cache" paragraph: the new cache directory name and size (~420 MB), and that it is NOT shared with yt-brain; the `embed` verb line: the new model name. `.claude/rules/search.md` line 5: model name and dims. Run `uv run pytest -q` and `uv run pytest -q -m semantic` (the real-model test now loads mpnet; it must still pass its ordering assertion).

- [ ] **Step 4 (adopt only): Live re-embed, behind "proceed"**

Tell the owner the numbers and that the next sync would otherwise do this on its own; on "proceed": `cp ~/.config/movie-brain/movie-brain.db ~/.config/movie-brain/movie-brain.db.bak-pre-mpnet`, then `nohup uv run movie-brain embed --apply > ~/.config/movie-brain/embed-mpnet-$(date +%F).log 2>&1 &` in the background shell; report `movie-brain status`'s `embeddings` count when it equals the `prose` count.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/plans/2026-09-23-search-recall.md docs/backlog.md   # plus the constant/docs files on adopt
git commit -m "search: all-mpnet-base-v2 measured against MiniLM on the keyword benchmark — <adopted|declined>, <the two numbers>"
```

---

### Task 7: Live migration, hands-on check, close-out

**Files:**
- Modify: `docs/backlog.md` (items 41, 42 checked off with one line each), `CLAUDE.md` `migrate` line untouched (030 needs no new verb)

- [ ] **Step 1: Migrate the live database behind "proceed"**

`uv run movie-brain migrate` (dry run, lists 030), then on the owner's "proceed": `uv run movie-brain migrate --apply` (backs up to `<config_dir>/backups/` first). Then `uv run movie-brain status` shows `prose` and `embeddings` unchanged.

- [ ] **Step 2: Ask the owner to restart his dashboard, then check the two test cases through the API**

```bash
for q in 'time loops' 'dystopian' 'time loop' 'dystopia'; do curl -s "http://127.0.0.1:5556/api/search?q=$(python3 -c 'import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))' "$q")" | python3 -c 'import json,sys; r=json.load(sys.stdin); print(r["q"], r["total"], 4850 in r["ids"], r["hints"])'; done
```

Expected: `time loops` → Groundhog Day present; `dystopian` → total ≈ 73 + up to 10 more by meaning; hints as the contract says.

- [ ] **Step 3: Backlog and commit**

Check off items 41 and 42 with the final benchmark numbers (one line each, referencing this plan's trial log). Commit: `git commit -m "search recall shipped: stemmed words, meaning that adds, and a model decision on the numbers — backlog 41–43"`. Push on the owner's word.

---

## Trial log

Numbers from `scripts/search_benchmark.py` against copies of the live database (5,052 vectors on 2026-09-23). Same seed (7), same 300 keywords, same code path except the task under test.

| run | set | n | hit rate | recall@10 | mean size | `time loops` → Groundhog Day | `dystopian` (72 tagged) |
|---|---|---|---|---|---|---|---|
| Baseline (before Task 2) | verbatim | 300 | 1.000 | 0.705 | 37.7 | miss (size=3) | hit, recall@10=0.60 (size=9) |
| | plural | 282 | 0.319 | 0.083 | 11.3 | | |
| After migration 030 (Task 2) | verbatim | 300 | 1.000 | 0.635 | 42.9 | hit, recall@10=1.00 (size=3) | hit, recall@10=0.60 (size=9) |
| | plural | 282 | 0.546 | 0.168 | 18.0 | | |
| After Task 3 (stem + ladder) | verbatim | 300 | 1.000 | 0.623 | 47.8 | hit, recall@10=1.00 (size=4) | hit, recall@10=0.70 (size=75) |
| | plural | 282 | 1.000 | 0.677 | 27.1 | | |
| After Task 4 (meaning adds) | verbatim | 300 | 1.000 | 0.627 | 55.4 | hit, recall@10=1.00 (size=12) | hit, recall@10=0.70 (size=81) |
| | plural | 282 | 1.000 | 0.676 | 35.0 | | |
| mpnet (Task 6) | verbatim | 300 | 1.000 | 0.626 | 55.6 | hit, recall@10=1.00 (size=12) | hit, recall@10=0.70 (size=83) |
| | plural | 282 | 1.000 | 0.677 | 35.2 | | |

Warm encode, one short query: MiniLM 6 ms · mpnet 10 ms. Full re-embed of 5,052 films with mpnet on this machine: 44 s (the plan's "hour of CPU" estimate was wrong by two orders of magnitude). Decision (D7): the keyword benchmark is a TIE (verbatim 0.626 vs 0.627, plural 0.677 vs 0.676, named rows identical) because its queries are keywords that the word stages match directly, so meaning rarely reaches the top ten under either model — the instrument cannot separate the models. A meaning-only probe (cosine rank over the whole catalogue, no word stages) on the owner's own phrasings does separate them: "a man relives the same day over and over" → Groundhog Day rank 1 with mpnet (rank 9 with MiniLM); "stuck repeating the same day" → rank 1 (rank 1); "time loops" → rank 4 (rank 5); "hard boiled private eye" → Lady in the Lake, Chinatown, L.A. Confidential in the top five with mpnet (MiniLM ranked The Maltese Falcon 30th, per `.claude/rules/search.md`). Controller ruling: measured, NOT adopted by the letter of D7 (a tie is not a win), with a recommendation to the owner to adopt on the probe — the constant change and the live re-embed are his "proceed" either way (spec D6).

Precision on prose (final review): verbatim recall@10 fell 0.705 → 0.635 at Task 2 → 0.627 at the end, with 52 queries worse and 15 better. Example `hypnotism`: Porter stems it to `hypnot`, which matches "hypnotic" in prose, and a raw −bm25 prose hit (about 7–12) outranks W_TAG 3, so Captain Underpants, Finding Nemo and The Jungle Book rank above the four tagged films (ranks 11–14); the same shape shows for `film industry`, `poisoning` and `forceful` (8 → 284 results). Left for the owner's decision per spec §5, with options (a) accept, (b) let a tag outrank prose-only hits, (c) Porter on keywords only.

Owner decision 1 (2026-09-23): Porter on keywords only — migration 030 no longer rebuilds `film_text_fts`; measured on a migrated copy with prose Porter reverted, verbatim recall@10 0.686 (0.627 as built, baseline 0.705) and plural 0.855 (0.676), with `time loops` and `dystopian` still hitting through the keyword index and ladder.

Owner decision 2 (2026-09-23): no meaning-only films under a title hit — `_semantic_stage` drops its additions when any word hit reaches its film through the title (`Repository.title_hits`), so "maltese falcon" returns the film alone while "dystopian" and "ward" keep theirs; meaning still re-scores the word hits.
