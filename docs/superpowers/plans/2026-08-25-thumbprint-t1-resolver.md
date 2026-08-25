# Thumbprint T1 — resolver + migration steps 0–1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the thumbprint resolver dark (benchmark-gated, unused by sync), the `claim` schema with a reversible backfill, and a `repair twins` verb that retires the 82 `Title (YYYY)` films one group at a time.

**Architecture:** Hexagonal, unchanged. `domain/thumbprint.py` = pure grammar + `resolve()` (ALG3 ported verbatim from `scripts/eval/thumbprint_score_prototype.py`). `infrastructure/thumbprint_fetch.py` = candidate pool builder over a key→JSON `CandidateCache` so the same code serves the offline fixture and live clients. `application/thumbprint.py` = backfill + review-detail serializer; `application/repair.py` gains `repair_twins`. Migration 011 adds `claim`, `films.title_norm`, `films.kind`.

**Tech Stack:** Python 3.12, uv, SQLite, Typer/Rich; pytest + pytest-bdd + `responses`; ruff + mypy.

**Spec:** `docs/superpowers/specs/2026-08-25-thumbprint-resolver-design.md` (this plan) ← `docs/superpowers/research/2026-08-25-thumbprint-design.md` (binding memo).

## Global Constraints

- No live-DB write except through Tasks 9–10's announce → approve → diff loop; every other task uses test DBs / read-only queries only.
- New code never calls OMDb `t=`; OMDb by `i=` and `s=` only.
- `scripts/thumbprint_benchmark.py --assert` must exit 0 (0 wrong on verified+believed, auto ≥ 90%) at the end of every task touching `domain/thumbprint.py` or the fixture; `scripts/matching_benchmark.py --assert-dominance` must stay green (`domain/matching.py` is not touched).
- Apple runtime is stored and displayed, never scored (owner decision Q3). `resolve()` has no runtime parameter.
- Schema change → `migrations/011_claims.sql` inserting its own `schema_version` row, wrapped in BEGIN/COMMIT.
- `uv run pytest && uv run ruff check . && uv run mypy` green at the end of every task.
- Branch `feature/T1-thumbprint-resolver` (git worktree). One commit per task "Commit" step.
- The scratch inputs from the research session are already copied to this session's scratchpad: `cand_cache.json` (47 MB, contains the OMDb key in its `o:` keys) and `eval_set_v1.csv` (504 rows). If missing, `cand_cache.json` must be rebuilt with `--refresh` (~8.9k requests, ~10 min) — say so rather than skipping the fixture.

---

## File map

| File | Responsibility |
|---|---|
| `scripts/eval/thumbprint_eval_v1.csv` (modify) | contract: +6 proposed rows, +`director`, +`runtime_min` columns |
| `scripts/eval/fixtures/cand_cache.json.gz` (create) | offline candidate cache, key-stripped |
| `scripts/eval/build_fixture.py` (create) | one-shot: strip apikey, gzip; add columns from live DB read-only |
| `scripts/thumbprint_benchmark.py` (create) | the gate |
| `src/movie_brain/domain/thumbprint.py` (create) | `parse_title`, `Query`, `Candidate`, `Verdict`, `resolve` |
| `src/movie_brain/infrastructure/thumbprint_fetch.py` (create) | `CandidateCache`, `CandidateFetcher` |
| `src/movie_brain/infrastructure/tmdb.py` (modify) | `search_any_year`, `search_person`, `person_movie_credits`, `movie_detail` |
| `src/movie_brain/infrastructure/omdb.py` (modify) | `search`, `by_id` (raw dict) |
| `migrations/011_claims.sql` (create) | `claim`, `films.title_norm`, `films.kind` |
| `src/movie_brain/infrastructure/database.py` (modify) | `add_claim`, `claims_for_film`, `set_title_norm`, `title_year_films`, `key_film_directly` |
| `src/movie_brain/application/thumbprint.py` (create) | `backfill_claims`, `review_detail` |
| `src/movie_brain/application/repair.py` (modify) | `audit_twins`, `repair_twins` |
| `src/movie_brain/cli.py` (modify) | `thumbprint backfill`, `repair twins` |
| `tests/unit/test_thumbprint.py`, `tests/unit/test_thumbprint_benchmark.py`, `tests/unit/test_thumbprint_fetch.py`, `tests/features/thumbprint.feature`, `tests/step_defs/test_thumbprint.py` (create) | |
| `.claude/rules/thumbprint.md` (create), `CLAUDE.md` (modify) | contract + commands |
| `scripts/eval/eval_lib.py`, `scripts/eval/*prototype.py` (delete in Task 8) | superseded |

---

### Task 1: Eval contract + offline fixture

**Files:**
- Create: `scripts/eval/build_fixture.py`, `scripts/eval/fixtures/cand_cache.json.gz`
- Modify: `scripts/eval/thumbprint_eval_v1.csv`
- Test: `tests/unit/test_thumbprint_benchmark.py` (fixture-shape tests only, gate test lands in Task 4)

**Interfaces:**
- Produces: CSV columns `group,film_id,source,title_ingested,year_ingested,expected_tt,expected_tmdb,verified_by,note,status,director,runtime_min`; fixture keys `ts:{title}|{year|None}`, `tsy:{title}|{year}`, `td:{tmdb_id}`, `person:{name}`, `credits:{person_id}`, `o:{"i": tt}` / `o:{"s": title[, "y": year]}` (JSON, sorted keys, **no apikey**).

- [ ] **Step 1: Failing fixture-shape test**

```python
# tests/unit/test_thumbprint_benchmark.py
import csv, gzip, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]

def test_eval_csv_has_director_and_runtime_columns():
    rows = list(csv.DictReader((ROOT / "scripts/eval/thumbprint_eval_v1.csv").open()))
    assert {"director", "runtime_min"} <= set(rows[0])
    assert len(rows) >= 504
    assert sum(1 for r in rows if r["director"]) >= 150

def test_fixture_has_no_api_key():
    cache = json.load(gzip.open(ROOT / "scripts/eval/fixtures/cand_cache.json.gz", "rt"))
    assert not any("apikey" in k for k in cache)
    assert sum(1 for k in cache if k.startswith("td:")) > 1900
```

- [ ] **Step 2: Run, expect FAIL** — `uv run pytest tests/unit/test_thumbprint_benchmark.py -v` (KeyError / FileNotFoundError).

- [ ] **Step 3: Write `scripts/eval/build_fixture.py`** (one-shot, read-only DB access)

```python
"""One-shot: turn the research-session scratch cache + eval set into the checked-in contract.
Usage: uv run python scripts/eval/build_fixture.py SCRATCH_DIR   (reads the live DB read-only)"""
import csv, gzip, json, os, sqlite3, sys
from pathlib import Path
SP = Path(sys.argv[1]); ROOT = Path(__file__).resolve().parents[2]
CFG = Path(os.environ.get("MOVIE_BRAIN_CONFIG_DIR", Path.home() / ".config/movie-brain"))
# 1. cache: strip the apikey from OMDb keys
raw = json.load(open(SP / "cand_cache.json")); out = {}
for k, v in raw.items():
    if k.startswith("o:"):
        p = json.loads(k[2:]); p.pop("apikey", None); k = "o:" + json.dumps(p, sort_keys=True)
    out[k] = v
(ROOT / "scripts/eval/fixtures").mkdir(exist_ok=True)
with gzip.open(ROOT / "scripts/eval/fixtures/cand_cache.json.gz", "wt") as f: json.dump(out, f, ensure_ascii=False)
# 2. eval csv: union of checked-in + scratch rows (by film_id,source,title), + director/runtime
db = sqlite3.connect(f"file:{CFG}/movie-brain.db?mode=ro", uri=True)
rt = {}
for fn in sorted((CFG / "appletv").glob("owned-*.txt")):
    for line in fn.read_text().splitlines():
        p = line.split("\t")
        if len(p) >= 3:
            try: rt[p[0]] = round(float(p[2]) / 60)
            except ValueError: pass
seen, rows = set(), []
for src in (ROOT / "scripts/eval/thumbprint_eval_v1.csv", SP / "eval_set_v1.csv"):
    for r in csv.DictReader(open(src)):
        k = (r["film_id"], r["source"], r["title_ingested"])
        if k in seen: continue
        seen.add(k)
        d = db.execute("select director from films where id=?", (r["film_id"],)).fetchone() if r["film_id"] else None
        r["director"] = (d[0] if d else None) or ""
        r["runtime_min"] = str(rt.get(r["title_ingested"], "")) if r["source"] == "apple" else ""
        rows.append(r)
cols = ["group","film_id","source","title_ingested","year_ingested","expected_tt","expected_tmdb","verified_by","note","status","director","runtime_min"]
with open(ROOT / "scripts/eval/thumbprint_eval_v1.csv", "w", newline="") as f:
    w = csv.DictWriter(f, cols); w.writeheader(); w.writerows(rows)
print(len(rows), "rows;", len(out), "cache keys")
```

- [ ] **Step 4: Run it** — `uv run python scripts/eval/build_fixture.py "$SCRATCHPAD"`; expect `504 rows; 8869 cache keys`; `ls -la scripts/eval/fixtures/` ≈ 8 MB. `git diff --stat scripts/eval/thumbprint_eval_v1.csv` must show only added columns/6 rows (spot-check 3 rows with `git diff | head`).

- [ ] **Step 5: Run tests, expect PASS.** Also `grep -c apikey scripts/eval/fixtures/*` → 0 after `gunzip -c`.

- [ ] **Step 6: Commit** — `git add scripts/eval tests/unit/test_thumbprint_benchmark.py && git commit -m "eval: check in thumbprint contract (504 rows + director/runtime) and key-stripped offline candidate fixture"`

---

### Task 2: Title grammar — `parse_title`

**Files:**
- Create: `src/movie_brain/domain/thumbprint.py`
- Test: `tests/unit/test_thumbprint.py`

**Interfaces:**
- Produces: `ParsedTitle(title: str, editions: tuple[str, ...], embedded_year: int | None, alt_titles: tuple[str, ...])`, `parse_title(raw: str) -> ParsedTitle`, `VOCAB: str` (regex fragment), `title_norm(raw: str) -> str` = `norm_title(parse_title(raw).title)`.

- [ ] **Step 1: Failing tests**

```python
# tests/unit/test_thumbprint.py
import pytest
from movie_brain.domain.thumbprint import parse_title, title_norm

@pytest.mark.parametrize("raw,title,eds,year,alts", [
    ("Rear Window (1954)", "Rear Window", (), 1954, ()),
    ("Blade Runner (The Final Cut)", "Blade Runner", ("the final cut",), None, ()),
    ("Straight Outta Compton (Unrated) [2015]", "Straight Outta Compton", ("unrated",), 2015, ()),
    ("Apocalypse Now Redux", "Apocalypse Now", ("redux",), None, ()),
    ("Donnie Darko: The Director's Cut", "Donnie Darko", ("the director's cut",), None, ()),
    ("Band of Outsiders [re-release]", "Band of Outsiders", ("re-release",), None, ()),
    ("(500) Days of Summer", "(500) Days of Summer", (), None, ()),
    ("Caché (Hidden)", "Caché", (), None, ("Hidden",)),
    ("LYNCH (one)", "LYNCH", (), None, ("one",)),
    ("Egungun (Ancestor Can't Find Me)", "Egungun", (), None, ("Ancestor Can't Find Me",)),
    ("(2019)", "(2019)", (), None, ()),                       # never strip to empty
    ("The Exorcist (Extended Director's Cut) (1973)", "The Exorcist", ("extended director's cut",), 1973, ()),
])
def test_parse_title(raw, title, eds, year, alts):
    p = parse_title(raw)
    assert (p.title, p.editions, p.embedded_year, p.alt_titles) == (title, eds, year, alts)

def test_title_norm_strips_edition_then_normalizes():
    assert title_norm("Blade Runner (The Final Cut)") == "bladerunner"
```

- [ ] **Step 2: Run, expect FAIL** (ImportError).

- [ ] **Step 3: Implement** — port `VOCAB`/`_TRAIL`/`_YEAR` from `scripts/eval/eval_lib.py` verbatim, add alt-title capture:

```python
# src/movie_brain/domain/thumbprint.py
"""Thumbprint: the work-identity resolver (memo 2026-08-25). Pure; imports only norm_title."""
from __future__ import annotations
import re
from dataclasses import dataclass
from movie_brain.domain.matching import norm_title

VOCAB = (r"(?:the |a )?(?:director'?s cut|director'?s edition|final cut|extended (?:director'?s )?cut|"
         r"extended edition|uncut(?: version)?|unrated(?: (?:director'?s cut|version|edition))?|"
         r"theatrical (?:version|cut)|ultimate edition|(?:\d+(?:st|nd|rd|th) )?anniversary (?:special )?edition|"
         r"special edition|collector'?s edition|definitive edition|re-?released?|restored(?: version)?|"
         r"in color & restored|remastered(?: feature)?|4k(?: restoration| remaster)?|redux|"
         r"english[- ]dubbed version|english version|german version|dubbed|subtitled|imax|3d)")
_TRAIL = re.compile(r"\s*(?:\((?P<p>" + VOCAB + r")\)|\[(?P<b>" + VOCAB + r")\]|[:–—-]\s*(?P<c>" + VOCAB + r")|\s(?P<w>redux))\s*$", re.I)
_YEAR = re.compile(r"\s*[\(\[](\d{4})[\)\]]\s*$")
_ALT = re.compile(r"\s*\((?P<a>[^()]+)\)\s*$")

@dataclass(frozen=True)
class ParsedTitle:
    title: str
    editions: tuple[str, ...]
    embedded_year: int | None
    alt_titles: tuple[str, ...]

def parse_title(raw: str) -> ParsedTitle:
    t = raw.strip(); eds: list[str] = []; alts: list[str] = []; year: int | None = None
    while True:
        m = _YEAR.search(t)
        if m and t[: m.start()].strip():
            year = int(m.group(1)); t = t[: m.start()].strip(); continue
        m = _TRAIL.search(t)
        if m and t[: m.start()].strip():
            eds.append(next(g for g in m.groups() if g).casefold()); t = t[: m.start()].strip(); continue
        m = _ALT.search(t)
        if m and t[: m.start()].strip():
            alts.append(m.group("a").strip()); t = t[: m.start()].strip(); continue
        break
    return ParsedTitle(t, tuple(eds), year, tuple(alts))

def title_norm(raw: str) -> str:
    return norm_title(parse_title(raw).title)
```

- [ ] **Step 4: Run, expect PASS.** Then verify against the live catalog read-only (no writes): `uv run python -c "import sqlite3;from movie_brain.domain.thumbprint import parse_title as p;db=sqlite3.connect('file:$HOME/.config/movie-brain/movie-brain.db?mode=ro',uri=True);print(sum(1 for (t,) in db.execute('select title from films') if p(t).editions or p(t).embedded_year))"` — expect ≈ 82 + 21.

- [ ] **Step 5: Commit** — `git commit -am "thumbprint: title grammar (editions, embedded year, alt titles) as the one parse function"`

---

### Task 3: `resolve()` — ALG3 port

**Files:**
- Modify: `src/movie_brain/domain/thumbprint.py`
- Test: `tests/unit/test_thumbprint.py`

**Interfaces:**
- Produces:
```python
class YearClass(StrEnum): DATABASE = "database"; MC = "mc"; APPLE_FIELD = "apple-field"
@dataclass(frozen=True)
class Query: raw_title: str; year: int | None; year_class: YearClass; source: str; director: str | None = None; runtime_min: int | None = None
@dataclass(frozen=True)
class Candidate: tt: str; tmdb_id: int | None; titles: tuple[str, ...]; year: int | None; directors: str; runtime_min: int | None; votes: int; kind: str; in_tmdb: bool; in_omdb: bool
@dataclass(frozen=True)
class Scored: candidate: Candidate; title_level: int; year_points: int; director_points: int; agreement: bool; older: bool
@dataclass(frozen=True)
class Verdict: kind: str; tt: str | None; reason: str; ranked: tuple[Scored, ...]
def make_query(raw_title: str, year: int | None, source: str, director: str | None = None, runtime_min: int | None = None) -> Query   # applies parse_title + year_class rule
def resolve(query: Query, candidates: Sequence[Candidate]) -> Verdict
```
`Query.title` (property) = `parse_title(raw_title).title`; `Query.editions` likewise.

- [ ] **Step 1: Failing tests** — one per verdict rule, hand-built candidates:

```python
from movie_brain.domain.thumbprint import Candidate, YearClass, make_query, resolve

def cand(tt, title, year, director="", votes=0, tmdb=1, in_omdb=True, kind="movie", titles=()):
    return Candidate(tt, tmdb, (title, *titles), year, director, None, votes, kind, tmdb is not None, in_omdb)

def test_director_corroborated_beats_year():
    q = make_query("Die Insel", 1974, "criterion", director="Wim Wenders")
    v = resolve(q, [cand("tt1", "Die Insel", 1974, "Wim Wenders", kind="episode"), cand("tt2", "Die Insel", 2001, "Someone Else")])
    assert (v.kind, v.tt, v.reason) == ("match", "tt1", "director corroborated")

def test_director_conflict_disqualifies():
    q = make_query("Revenge", 1989, "criterion", director="Yermek Shinarbayev")
    v = resolve(q, [cand("tt2", "Revenge", 1990, "Tony Scott", votes=50000)])
    assert v.kind == "review" and v.reason == "director conflicts only"

def test_exact_title_drops_longer_titles():
    q = make_query("Friday the 13th", 1980, "metacritic")
    v = resolve(q, [cand("tt1", "Friday the 13th", 1980, votes=200), cand("tt2", "Friday the 13th Part 2", 1981, votes=300)])
    assert v.tt == "tt1"

def test_rerelease_ambiguous_apple_field_year():
    q = make_query("The Boston Strangler", 2004, "apple")
    v = resolve(q, [cand("tt1", "The Boston Strangler", 2006), cand("tt2", "The Boston Strangler", 1968, votes=9000)])
    assert (v.kind, v.reason) == ("review", "rerelease-ambiguous")

def test_commerce_year_is_rerelease_when_nothing_near():
    q = make_query("Mafioso", 2007, "metacritic")
    v = resolve(q, [cand("tt1", "Mafioso", 1962)])
    assert v.kind == "match" and v.reason.startswith("unique older exact title")

def test_votes_dominance():
    q = make_query("Under the Skin", 2014, "metacritic")
    v = resolve(q, [cand("tt1", "Under the Skin", 2013, votes=165354), cand("tt2", "Under the Skin", 2014, votes=0)])
    assert v.tt == "tt1"

def test_generic_title_single_near_hit_without_agreement_is_review():
    q = make_query("Once", 2007, "criterion")
    v = resolve(q, [cand("tt1", "Once", 2007, votes=5, tmdb=None)])
    assert v.kind == "review" and v.reason == "weak"

def test_imdb_duplicate_dropped():
    q = make_query("Muhammad Ali, the Greatest", 1974, "criterion")
    v = resolve(q, [cand("tt1", "Muhammad Ali, the Greatest", 1974, votes=500), cand("tt2", "Muhammad Ali, the Greatest", 1974, votes=3, tmdb=None)])
    assert v.tt == "tt1"

def test_junk_shape_dropped_unless_director_corroborated():
    q = make_query("Masculin Féminin", 1966, "criterion")
    v = resolve(q, [cand("tt1", "Bande-annonce de 'Masculin féminin'", 1966, "Jean-Luc Godard", titles=("Masculin Féminin",)), cand("tt2", "Masculine Feminine", 1966, "Jean-Luc Godard", votes=18000, titles=("Masculin Féminin",))])
    assert v.tt == "tt2"

def test_dateless_unique_exact_with_agreement():
    q = make_query("Savage/Love", None, "criterion")
    v = resolve(q, [cand("tt1", "Savage/Love", 1981)])
    assert v.kind == "match" and "dateless" in v.reason

def test_ranked_carries_top_three():
    q = make_query("Passenger", 2005, "criterion")
    v = resolve(q, [cand(f"tt{i}", "Passenger", 2005, votes=i) for i in range(5)])
    assert v.kind == "review" and len(v.ranked) == 3

def test_year_class_rule():
    assert make_query("X (1999)", 2011, "apple").year_class is YearClass.DATABASE
    assert make_query("X", 2011, "apple").year_class is YearClass.APPLE_FIELD
    assert make_query("X", 2011, "metacritic").year_class is YearClass.MC
```
(Adjust expected reason strings to the prototype's literals in `alg3()` — they are the contract; do not invent new wording. Where a hand-built test disagrees with the prototype, the prototype wins and the test is fixed.)

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement** — port `title_level`, `name_tokens`, `dir_match`, `JUNK`, and `alg3()` from `scripts/eval/thumbprint_score_prototype.py` lines ~150–215 into `resolve()`, replacing dict candidates with `Candidate`, removing every `use_runtime`/`qrt`/`rm` branch, and building `ranked` as the surviving scored list sorted by score desc, capped at 3. Keep every reason string byte-identical. `sim` uses `difflib.SequenceMatcher` on `norm_title`.

- [ ] **Step 4: Run, expect PASS.** `uv run ruff check . && uv run mypy`.

- [ ] **Step 5: Commit** — `git commit -am "thumbprint: resolve() — ALG3 evidence model and verdict order ported from the eval prototype"`

---

### Task 4: Candidate cache/fetcher + benchmark gate (baseline reproduced)

**Files:**
- Create: `src/movie_brain/infrastructure/thumbprint_fetch.py`, `scripts/thumbprint_benchmark.py`
- Modify: `src/movie_brain/infrastructure/tmdb.py`, `src/movie_brain/infrastructure/omdb.py`
- Test: `tests/unit/test_thumbprint_fetch.py`, `tests/unit/test_thumbprint_benchmark.py`

**Interfaces:**
- Produces:
```python
class CandidateCache:            # infrastructure/thumbprint_fetch.py
    def __init__(self, data: dict[str, Any], path: Path | None = None, read_only: bool = False)
    @classmethod
    def load(cls, path: Path, read_only: bool = False) -> CandidateCache   # .json or .json.gz
    def get(self, key: str, fetch: Callable[[], Any]) -> Any   # miss + read_only → raises CacheMiss
    def save(self) -> None
class CandidateFetcher:
    def __init__(self, cache: CandidateCache, tmdb: TmdbClient | None, omdb: OmdbClient | None)
    def fetch(self, q: Query) -> list[Candidate]
# tmdb.py
def search_raw(self, title: str, year: int | None = None, any_release_year: bool = False) -> list[dict]  # raw results[:10]
def search_person(self, name: str) -> list[dict]           # results[:2]
def person_movie_credits(self, person_id: int) -> list[dict]  # crew
def movie_detail(self, tmdb_id: int) -> dict                # append_to_response=external_ids,credits,alternative_titles
# omdb.py
def search(self, title: str, year: int | None = None) -> list[dict]   # s= ; returns Search list
def by_id(self, imdb_id: str) -> dict                                 # i= ; raw payload ({} when not found)
```
Cache keys exactly as in Task 1. `fetch()` reproduces `pool()` + `pool3()` from the prototype (TMDB `ts`/`tsy`, OMDb `s`/`s+y`, person→credits with the prototype's filter, `td` detail, `o:i` for every tt; TMDB candidates without `imdb_id` dropped).

- [ ] **Step 1: Failing tests**

```python
# tests/unit/test_thumbprint_fetch.py
import pytest
from movie_brain.domain.thumbprint import make_query
from movie_brain.infrastructure.thumbprint_fetch import CandidateCache, CandidateFetcher, CacheMiss

def test_read_only_cache_raises_on_miss():
    with pytest.raises(CacheMiss):
        CandidateCache({}, read_only=True).get("ts:x|None", lambda: None)

def test_fetcher_unifies_on_tt_from_cache():
    data = {
        "ts:Rear Window|None": [{"id": 567, "title": "Rear Window"}],
        "tsy:Rear Window|1954": [],
        "ts:Rear Window|1954": [],
        "td:567": {"id": 567, "title": "Rear Window", "original_title": "Rear Window", "release_date": "1954-08-01",
                   "runtime": 112, "external_ids": {"imdb_id": "tt0047396"},
                   "credits": {"crew": [{"job": "Director", "name": "Alfred Hitchcock"}]}, "alternative_titles": {"titles": []}},
        'o:{"s": "Rear Window"}': {"Search": [{"imdbID": "tt0047396"}]},
        'o:{"s": "Rear Window", "y": "1954"}': {"Search": []},
        'o:{"i": "tt0047396"}': {"imdbID": "tt0047396", "Title": "Rear Window", "Year": "1954", "Director": "Alfred Hitchcock", "imdbVotes": "500,000", "Type": "movie", "Runtime": "112 min"},
    }
    cands = CandidateFetcher(CandidateCache(data, read_only=True), None, None).fetch(make_query("Rear Window", 1954, "criterion"))
    assert [c.tt for c in cands] == ["tt0047396"] and cands[0].in_tmdb and cands[0].in_omdb and cands[0].votes == 500000
```
Plus `responses`-mocked tests in `tests/unit/test_tmdb.py` / `test_omdb.py` for each new client method (URL + params asserted; `omdb.by_id` asserts `"t"` is absent from the query string).

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement** clients + `thumbprint_fetch.py`. Cache key builders live in one place:

```python
def k_ts(t, y): return f"ts:{t}|{y}"
def k_tsy(t, y): return f"tsy:{t}|{y}"
def k_td(i): return f"td:{i}"
def k_person(n): return f"person:{n}"
def k_credits(i): return f"credits:{i}"
def k_o(**p): return "o:" + json.dumps(p, sort_keys=True)
```
Live calls: `cache.get(k_ts(t, None), lambda: tmdb.search_raw(t))` etc.; when `tmdb`/`omdb` is `None` and the key is missing, `CacheMiss` propagates (the gate reports it as `no candidates (cache miss)` and counts it as review — this must be 0 on the checked-in fixture).

- [ ] **Step 4: Write `scripts/thumbprint_benchmark.py`**

```python
"""Thumbprint resolver gate. Offline by default (scripts/eval/fixtures/cand_cache.json.gz).
  uv run python scripts/thumbprint_benchmark.py [--assert] [--status S] [--group G] [--refresh] [--limit N]"""
import argparse, csv, sys
from collections import Counter, defaultdict
from pathlib import Path
sys.path.insert(0, "src")
from movie_brain.domain.thumbprint import make_query, resolve
from movie_brain.infrastructure.thumbprint_fetch import CandidateCache, CandidateFetcher, CacheMiss
ROOT = Path(__file__).resolve().parents[1]
CSV = ROOT / "scripts/eval/thumbprint_eval_v1.csv"; FIX = ROOT / "scripts/eval/fixtures/cand_cache.json.gz"
SCORED = {"verified", "believed"}

def run(rows, fetcher):
    tally, wrong, reasons, bygroup = Counter(), [], defaultdict(list), defaultdict(Counter)
    for r in rows:
        q = make_query(r["title_ingested"], int(r["year_ingested"]) if r["year_ingested"] else None, r["source"],
                       director=r["director"] or None, runtime_min=int(r["runtime_min"]) if r["runtime_min"] else None)
        try: v = resolve(q, fetcher.fetch(q))
        except CacheMiss as e: v = type("V", (), {"kind": "review", "tt": None, "reason": f"cache miss {e}"})()
        exp = r["expected_tt"]
        res = ("correct" if v.tt == exp else "WRONG") if v.kind == "match" else ("review-none-ok" if exp == "NONE" else "review")
        tally[res] += 1; bygroup[r["group"]][res] += 1
        if res == "WRONG": wrong.append((r["group"], r["source"], r["title_ingested"], r["year_ingested"], exp, v.tt, v.reason, r["status"]))
        elif res == "review": reasons[v.reason].append(r["title_ingested"])
    return tally, wrong, reasons, bygroup

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--assert", dest="gate", action="store_true")
    ap.add_argument("--status"); ap.add_argument("--group"); ap.add_argument("--refresh", action="store_true"); ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    rows = [r for r in csv.DictReader(CSV.open()) if r["expected_tt"]]
    if a.group: rows = [r for r in rows if r["group"].startswith(a.group)]
    scored = [r for r in rows if r["status"] in SCORED and (not a.status or r["status"] == a.status)]
    proposed = [r for r in rows if r["status"] == "proposed"]
    if a.limit: scored = scored[: a.limit]
    if a.refresh:
        from movie_brain.infrastructure.config import load_config  # real clients, appends to fixture
        cfg = load_config(); cache = CandidateCache.load(FIX)
        from movie_brain.infrastructure.tmdb import TmdbClient; from movie_brain.infrastructure.omdb import OmdbClient
        fetcher = CandidateFetcher(cache, TmdbClient(cfg.tmdb_token), OmdbClient(cfg.omdb_key))
    else:
        cache = CandidateCache.load(FIX, read_only=True); fetcher = CandidateFetcher(cache, None, None)
    tally, wrong, reasons, bygroup = run(scored, fetcher)
    if a.refresh: cache.save()
    n = sum(tally.values()); auto = tally["correct"] / n if n else 0
    rev = tally["review"] + tally["review-none-ok"]
    print(f"thumbprint gate  n={n}  WRONG={tally['WRONG']}  auto-correct={tally['correct']} ({100*auto:.1f}%)  review={rev} ({100*rev/n:.1f}%)")
    for g, t in sorted(bygroup.items()): print(f"   {g:22} {dict(t)}")
    print("   review reasons:", {k: len(v) for k, v in reasons.items()})
    for w in wrong: print("   WRONG:", w)
    pt, pw, *_ = run(proposed, fetcher)
    print(f"proposed (not scored): n={sum(pt.values())} agree={pt['correct']} disagree={pt['WRONG']} review={pt['review']}")
    if a.gate and (tally["WRONG"] or auto < 0.90):
        print("GATE FAILED"); sys.exit(1)

if __name__ == "__main__": main()
```
(Check `infrastructure/config.py` for the real loader name/fields and use those; the snippet's `load_config`/`tmdb_token`/`omdb_key` are placeholders for whatever `cli._repo`/`_config` already use.)

- [ ] **Step 5: Reproduce the baseline** — `uv run python scripts/thumbprint_benchmark.py --assert`. Expected: `WRONG=0`, auto ≥ 93%, `cache miss` count 0. If WRONG > 0, the port diverged from `alg3()`: diff `resolve()` against the prototype rule by rule (run the prototype on the same rows via `uv run python scripts/eval/thumbprint_score_prototype.py "$SCRATCHPAD" verified` for comparison) — do not "fix" by editing the CSV. Record the exact baseline line in this plan under Task 4 when done: `baseline: n=… WRONG=0 auto=…%`.

- [ ] **Step 6: Gate slice test** (append to `tests/unit/test_thumbprint_benchmark.py`):

```python
def test_gate_slice_zero_wrong():
    import importlib.util
    spec = importlib.util.spec_from_file_location("bench", ROOT / "scripts/thumbprint_benchmark.py"); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    rows = [r for r in csv.DictReader(m.CSV.open()) if r["status"] in m.SCORED and r["expected_tt"]][:20]
    fetcher = m.CandidateFetcher(m.CandidateCache.load(m.FIX, read_only=True), None, None)
    tally, wrong, *_ = m.run(rows, fetcher)
    assert wrong == [] and tally["correct"] >= 16
```

- [ ] **Step 7: Full checks** — `uv run pytest && uv run ruff check . && uv run mypy && uv run python scripts/matching_benchmark.py --assert-dominance`.

- [ ] **Step 8: Commit** — `git commit -am "thumbprint: candidate fetcher + offline benchmark gate; baseline 0 wrong reproduced on the checked-in contract"`

---

### Task 5: Migration 011 + Repository claim primitives

**Files:**
- Create: `migrations/011_claims.sql`
- Modify: `src/movie_brain/infrastructure/database.py`
- Test: `tests/unit/test_database.py`

**Interfaces:**
- Produces:
```python
class ClaimRow(NamedTuple): id: int; film_id: int; authority: str; value: str; title_ingested: str; year_claimed: int | None; edition_label: str | None; edition_year: int | None; runtime_min: int | None; first_seen: str
def add_claim(self, film_id, authority, value, title_ingested, *, year_claimed=None, edition_label=None, runtime_min=None, first_seen) -> bool   # INSERT OR IGNORE; False when (authority,value) exists
def claims_for_film(self, film_id: int) -> list[ClaimRow]
def claim_counts(self) -> dict[str, int]                 # authority → rows
def set_title_norm(self, film_id: int, title_norm: str) -> None
def films_missing_title_norm(self) -> list[tuple[int, str]]   # (id, title) where title_norm IS NULL, undisposed
```

- [ ] **Step 1: Failing tests**

```python
def test_migration_011_adds_claim_and_film_columns(tmp_path):
    repo = make_repo(tmp_path)   # existing helper in test_database.py
    fid = repo.create_film(Film("Blade Runner", 1982, "Ridley Scott", ""))
    assert repo.add_claim(fid, "apple-tv", "Blade Runner (The Final Cut)", "Blade Runner (The Final Cut)", year_claimed=2007, edition_label="the final cut", runtime_min=117, first_seen="2026-08-23")
    assert not repo.add_claim(fid, "apple-tv", "Blade Runner (The Final Cut)", "x", first_seen="2026-08-24")  # UNIQUE guard
    (c,) = repo.claims_for_film(fid)
    assert (c.edition_label, c.edition_year, c.runtime_min) == ("the final cut", None, 117)
    assert repo.claim_counts() == {"apple-tv": 1}
    assert repo.films_missing_title_norm() == [(fid, "Blade Runner")]
    repo.set_title_norm(fid, "bladerunner"); assert repo.films_missing_title_norm() == []

def test_migration_011_applies_over_v10_backup(tmp_path):
    # copy tests/fixtures/v10.db if present else build at v10 by running init_db with migrations ≤ 10 (see existing migration tests for the pattern)
    ...
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Write the migration** (SQL exactly as spec §3) and the five Repository methods next to the `owned` block (~line 1124). `films.kind` and `title_norm` are also read into `FilmRow` only if an existing NamedTuple already selects `films.*` — otherwise leave read models untouched (T1 shows no badge).

- [ ] **Step 4: Run, expect PASS.** Confirm `init_db` on a fresh DB reports version 11; confirm `_backup_pre_migration` would fire (existing test pattern).

- [ ] **Step 5: Commit** — `git commit -am "schema 011: claim table + films.title_norm/kind (pure additive, reversible)"`

---

### Task 6: `thumbprint backfill` use case + CLI

**Files:**
- Create: `src/movie_brain/application/thumbprint.py`
- Modify: `src/movie_brain/cli.py`, `src/movie_brain/infrastructure/database.py` (read helpers below)
- Test: `tests/features/thumbprint.feature`, `tests/step_defs/test_thumbprint.py`

**Interfaces:**
- Consumes: `add_claim`, `set_title_norm`, `films_missing_title_norm`, `parse_title`, `title_norm`, `parse_apple_title`, `film_key`, `film_id_by_key`, `canonical_film_id`.
- Produces:
```python
@dataclass(frozen=True)
class BackfillReport: criterion: int; metacritic: int; apple: int; apple_unrecovered: int; title_norms: int; editions: int
def backfill_claims(repo: Repository, config_dir: Path, *, apply: bool, log=_stderr) -> BackfillReport
def review_detail(verdict: Verdict) -> str      # JSON per spec §5, ≤3 candidates, letters A/B/C
# database.py read helpers
def criterion_listing_rows(self) -> list[tuple[int, str, str, str, int | None]]   # (film_id, url, title, first_seen, year), undisposed
def metacritic_claim_rows(self) -> list[tuple[int, str, str, int | None, str]]     # (film_id, slug, mc_title, mc_year, first_seen) via external_ids
def owned_rows(self) -> list[tuple[int, str]]                                     # (film_id, first_imported)
```

- [ ] **Step 1: Failing scenarios**

```gherkin
# tests/features/thumbprint.feature
Feature: Thumbprint claims backfill
  Scenario: dry run writes nothing and reports counts
    Given a film "Blade Runner" (1982) with a criterion listing and a metacritic slug "blade-runner"
    And an owned film "Blade Runner (The Final Cut)" imported from an archive line "Blade Runner (The Final Cut)\t2007\t7020"
    When I run the claims backfill without --apply
    Then the claim table is empty
    And the report says criterion 1, metacritic 1, apple 1, editions 1

  Scenario: apply is idempotent and fills title_norm
    Given the same seed
    When I run the claims backfill with --apply twice
    Then there are exactly 3 claim rows
    And the apple claim has edition_label "the final cut", year_claimed 2007 and runtime_min 117
    And every film has a title_norm

  Scenario: an owned film whose archive line cannot be recovered still gets a claim
    Given an owned film "Orphan" (2001) with no archive line
    When I run the claims backfill with --apply
    Then the apple claim for "Orphan" has value "Orphan" and the report says apple_unrecovered 1
```
Step defs seed via `Repository` + a temp `config_dir/appletv/owned-2026-08-23.txt`.

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement `backfill_claims`** — Apple recovery: for every archive line (all `owned-*.txt`, newest last so the latest wins), `cleaned, emb = parse_apple_title(title)`; `year = emb or line_year`; `fid = repo.canonical_film_id(repo.film_id_by_key(film_key(cleaned, year)) or 0)`; if `fid` is owned → claim `(apple-tv, value=raw title, title_ingested=raw, year_claimed=line_year, edition_label=' / '.join(parse_title(raw).editions) or None, runtime_min=round(secs/60), first_seen=archive date)`. Owned films never reached get `value=title_ingested=films.title`, `first_seen=owned.first_imported`, counted as `apple_unrecovered`. Criterion/Metacritic per spec §3. Dry run logs counts + first 20 rows per authority + every edition row; `--apply` calls `add_claim` (idempotent) then `set_title_norm` for `films_missing_title_norm()`.

- [ ] **Step 4: CLI** — `thumbprint_app = typer.Typer(help="Thumbprint identity: claims backfill (T1); resolver stays dark until the ingester switch.")`, command `backfill --apply`. Print the report as a Rich table.

- [ ] **Step 5: Run, expect PASS**; full checks.

- [ ] **Step 6: Commit** — `git commit -am "thumbprint backfill: copy owned/criterion/metacritic evidence into claim rows (dry-run first, idempotent)"`

---

### Task 7: `repair twins`

**Files:**
- Modify: `src/movie_brain/application/repair.py`, `src/movie_brain/infrastructure/database.py`, `src/movie_brain/cli.py`
- Test: `tests/features/repair.feature`, `tests/step_defs/test_repair.py`

**Interfaces:**
- Consumes: `parse_title`, `title_norm`, `merge_film`, `update_film_year`, eval CSV group B rows (`film_id`, note `twin NNNN`).
- Produces:
```python
@dataclass(frozen=True)
class TwinGroup: raw_id: int; raw_title: str; embedded_year: int; verdict: str  # "twin" | "no-twin" | "conflict" | "csv-mismatch"
                 twin_id: int | None; detail: str; year_fix: int | None       # year_fix = embedded_year when films.year != embedded_year (Rear Window)
def audit_twins(repo: Repository, expected: dict[int, int]) -> list[TwinGroup]   # expected = {raw film_id: twin id} from the CSV
def repair_twins(repo, today, *, apply: bool, confirm: Callable[[TwinGroup], bool], expected: dict[int, int], eval_append: Callable[[TwinGroup], None], log=_stderr) -> TwinsReport
def load_expected_twins(csv_path: Path) -> dict[int, int]
# database.py
def embedded_year_films(self) -> list[tuple[int, str, int | None, str | None]]   # (id, title, year, omdb imdbID) for undisposed films with a trailing (YYYY)
def films_by_title_norm_year(self, title_norm: str, year: int) -> list[tuple[int, str | None]]  # (id, tmdb imdb_id) undisposed
def key_film_directly(self, film_id: int, *, new_title: str, tmdb_id: int | None, imdb_id: str, today: date) -> None  # retitle + external_ids; used for NO-TWIN
```

- [ ] **Step 1: Failing scenarios** (append to `repair.feature`)

```gherkin
  Scenario: a raw Title (YYYY) film with one same-year twin whose keys agree is merged
    Given film 10 "Rear Window (1954)" year 2013 with OMDb imdbID tt0047396 and an owned row
    And film 11 "Rear Window" year 1954 with TMDB imdb_id tt0047396
    And the eval contract expects film 10 → twin 11
    When I run repair twins --apply answering yes
    Then film 10 is merged into film 11, film 11 is owned, and film 10's year was set to 1954 before the merge
    And an eval row for film 10 was appended once

  Scenario: keys disagree → conflict, nothing written
    Given film 10 "Vertigo (1958)" with OMDb imdbID tt0052357 and film 11 "Vertigo" 1958 with TMDB imdb_id tt0000001
    When I run repair twins --apply answering yes
    Then the group verdict is "conflict" and no disposition exists

  Scenario: contract disagrees with the computed twin → csv-mismatch, skipped loudly
    Given film 10 "Hamlet (1996)" and twin 11, and the eval contract expects film 10 → 12
    When I run repair twins --apply answering yes
    Then the group verdict is "csv-mismatch" and no disposition exists

  Scenario: no twin → keyed directly
    Given film 10 "Doctor Strange (2016)" with OMDb imdbID tt1211837 and no other film titled Doctor Strange in 2016
    When I run repair twins --apply answering yes
    Then film 10 is titled "Doctor Strange" with external id imdb tt1211837 and no disposition exists
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement** mirroring `repair_dupes` (lines 113–142). Per group, in order: `log(format)`; skip unless `apply` and verdict in `{"twin","no-twin"}` and `confirm(g)`; if `g.year_fix`: `repo.update_film_year(g.raw_id, g.year_fix)`; twin → `repo.merge_film(g.raw_id, g.twin_id, today, note=f"repair twins {g.raw_title!r}")` and log `moved/dropped/reviews_resolved`; no-twin → `key_film_directly`. Then `eval_append(g)`. `eval_append` (CLI-side) appends `B-apple-year-title,<raw_id>,apple,<raw_title>,<year>,<tt>,<tmdb>,human,twin <twin_id>,verified,,` only when `(film_id, source, title)` is absent.

- [ ] **Step 4: CLI** — `repair twins [--apply] [--yes] [--limit N]`; `--limit` caps the number of groups shown/applied per run (the batch size the owner picks). Prompt text: `merge #{raw} "{title}" → #{twin}? [y/N]`.

- [ ] **Step 5: Run, expect PASS**; full checks.

- [ ] **Step 6: Commit** — `git commit -am "repair twins: retire Title (YYYY) films into their same-year twins, contract-checked, one group at a time"`

---

### Task 8: Docs, rules, prototype cleanup

**Files:**
- Create: `.claude/rules/thumbprint.md`
- Modify: `CLAUDE.md`
- Delete: `scripts/eval/eval_lib.py`, `scripts/eval/thumbprint_score_prototype.py`, `scripts/eval/fetch_candidates_prototype.py`, `scripts/eval/fetch2_prototype.py`

- [ ] **Step 1:** `.claude/rules/thumbprint.md` with `paths:` = the four thumbprint files + the gate; body: gate-before-change (`--assert` must be green; never edit the CSV to make it green — a wrong expectation is corrected with a note and `verified_by`), no OMDb `t=`, runtime dark, fixture key scheme, `proposed` rows never scored, `review_detail` JSON is the only review-row format.
- [ ] **Step 2:** CLAUDE.md Commands: add `uv run movie-brain thumbprint backfill [--apply]`, `uv run movie-brain repair twins [--apply] [--yes] [--limit N]`, `uv run python scripts/thumbprint_benchmark.py --assert`. Rules: one bullet pointing at `thumbprint.md` and stating "the resolver is dark until the ingester switch (memo step 5)".
- [ ] **Step 3:** delete the prototypes (the gate + tests now cover them); `uv run pytest` still green.
- [ ] **Step 4: Commit** — `git commit -am "docs: thumbprint rules + commands; retire eval prototypes now that the gate reproduces them"`

---

### Task 9: LIVE — migration 011 + backfill (announce → approve → diff)

No code. Runbook, executed only with the owner present.

- [ ] **Step 1:** `uv run movie-brain status` (triggers no migration? — check `init_db` is only called by commands; if `status` migrates, take the pre-migration backup path as the announcement). Announce: "Migration 011 will add `claim`, `films.title_norm`, `films.kind` to `~/.config/movie-brain/movie-brain.db`; a pre-migration backup lands in `backups/`. No row in any existing table changes." Wait for yes.
- [ ] **Step 2:** Apply (any command); verify `select version from schema_version` = 11 and the backup file exists.
- [ ] **Step 3:** `uv run movie-brain thumbprint backfill` (dry run). Expected ≈ criterion 3,050 / metacritic 1,511 / apple 935 (report `apple_unrecovered`) / editions ≈ 54. Paste the report; wait for yes.
- [ ] **Step 4:** `--apply`; re-run dry run → all zero new; `select authority,count(*) from claim group by 1`. Paste before/after.
- [ ] **Step 5:** Commit nothing (live data); write the numbers into this plan under Task 9.

### Task 10: LIVE — the 82 twins, in batches

- [ ] **Step 1:** `uv run movie-brain repair twins` (dry run, full list). Expected: 81 twin + 1 no-twin; **0 conflict, 0 csv-mismatch**. Any non-zero → stop, report, do not apply that group.
- [ ] **Step 2:** Owner picks batch size N. `uv run movie-brain repair twins --apply --limit N` (no `--yes`); answer each prompt only after the owner sees the group line. After each batch paste: `select count(*) from films f where f.title glob '* ([12][0-9][0-9][0-9])' and not exists(select 1 from film_disposition d where d.film_id=f.id)`, `select count(*) from match_review where resolved=0 and reason='no-match'`.
- [ ] **Step 3:** Repeat until the first count is 0. Expected no-match open rows: 299 → ≈227.
- [ ] **Step 4:** `git diff scripts/eval/thumbprint_eval_v1.csv` shows only appended `verified_by=human` rows → `uv run python scripts/thumbprint_benchmark.py --assert` still green → commit the CSV: `git commit -am "eval: ratify 82 Title (YYYY) twin merges (human-verified via repair twins)"`.
- [ ] **Step 5:** `uv run movie-brain audit run --no-tmdb`; paste the tally delta.

---

## Self-review

- Spec coverage: §1 → T1/T4; §2 → T2–T4; §3 → T5/T6/T9; §4 → T7/T10; §5 → T6 (`review_detail`); §6 tests → each task; §7 → T8. Not built (by spec): `review resolve --pick`, ingester switch, `external_ids` PK change.
- Known soft spot: T6 Apple raw-title recovery via `film_key` replay will miss films whose title was later merged/renamed; that is why `apple_unrecovered` is reported and those rows still get a claim.
- Baseline number for T4 step 5 is to be filled in by the executor (memo's 93.0% was on the scratch set).
