# Data Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A read-only `movie-brain audit` verb that scores every film against cross-source consistency checks, a **Suspect** chip that surfaces the ranked worklist in the dashboard, and an append-only drawer verdict so the human decides what is actually wrong.

**Architecture:** Hexagonal, like the rest of the repo. Pure checks live in `domain/audit.py` over an `AuditSubject` dataclass; the repository assembles subjects and stores flags/verdicts/TMDB facts; `application/audit.py` orchestrates (TMDB facts fill → checks → replace flags → report); the Flask app exposes the verdict endpoint; `app.js`/`index.html` add the chip and drawer block on the existing revisit pattern. **No automatic fixes anywhere.**

**Tech Stack:** Python 3.12, SQLite, Flask, Typer, pytest + pytest-bdd + `responses`, Playwright (`uv run playwright install chromium` once), ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-08-24-data-audit-design.md`

## Global Constraints

- Schema change → new `migrations/010_audit.sql` that inserts its own `schema_version` row, wrapped in `BEGIN;`/`COMMIT;`. Never edit an applied migration.
- Verdict vocabulary is exactly: `fine`, `omdb-wrong`, `tmdb-wrong`, `film-wrong`, `twin`.
- `audit_verdict` is append-only; the `POST /api/films/<id>/verdict` endpoint is its **only** writer. Sync, repair, and review verbs never touch it.
- `audit_flags` is replaced wholesale on each run inside one transaction.
- `fine` suppresses the chip only when the verdict's `reasons` equals the film's current sorted reason set.
- Chip lockstep: a new predicate goes in `domain/filters.py` `_PREDICATES`, `static/app.js` `CHIP_PREDICATES`, and `templates/index.html` in the same task.
- Every film read model keeps the `_NOT_DISPOSED` guard.
- Gates after every task: `uv run pytest`, `uv run ruff check .`, `uv run mypy`. `domain/matching.py` is never touched (benchmark stays untouched).
- Commit messages: brief single line, "why" not "what"; end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Use `uv run` for every command. Tests use the shared `repo` fixture from `tests/conftest.py` (fresh SQLite DB in a tmp config dir).

---

## File map

| File | Responsibility |
|---|---|
| `migrations/010_audit.sql` | `audit_flags`, `audit_verdict`, `tmdb_facts` tables |
| `src/movie_brain/domain/audit.py` (new) | `AuditSubject`, `AuditFlag`, `normalize_title`, `run_checks`, weights, `VERDICTS` |
| `src/movie_brain/infrastructure/tmdb.py` | `TmdbFacts` + `TmdbClient.movie_facts` |
| `src/movie_brain/infrastructure/database.py` | tmdb_facts / flags / verdict repo methods, `audit_subjects`, view join + suppression |
| `src/movie_brain/domain/models.py` | `FilmView.audit`, `FilmView.verdict` |
| `src/movie_brain/application/audit.py` (new) | `run_audit`, `AuditReport` |
| `src/movie_brain/cli.py` | `audit` verb group: `audit run`, `audit verdicts` |
| `src/movie_brain/domain/filters.py`, `web/static/app.js`, `web/templates/index.html` | Suspect chip |
| `src/movie_brain/web/app.py` | `POST /api/films/<id>/verdict` |
| `tests/unit/test_audit.py`, `tests/unit/test_tmdb.py`, `tests/unit/test_database.py` | unit |
| `tests/features/audit.feature`, `tests/step_defs/test_audit.py` | BDD |
| `tests/web/test_api.py`, `tests/web/test_dashboard.py`, `tests/web/conftest.py` | web |
| `CLAUDE.md` | commands + rules |

---

### Task 1: Migration + TMDB facts storage

**Files:**
- Create: `migrations/010_audit.sql`
- Modify: `src/movie_brain/infrastructure/database.py` (Repository, near `set_external_id` at ~line 404)
- Test: `tests/unit/test_database.py`

**Interfaces:**
- Produces: `Repository.tmdb_facts_needed() -> list[tuple[int, int]]` (film_id, tmdb_id) for linked, non-disposed films with no `tmdb_facts` row or a row whose `tmdb_id` differs from the current `tmdb` external id.
- Produces: `Repository.upsert_tmdb_facts(film_id, facts: TmdbFactsRow, fetched_on: date) -> None` where `TmdbFactsRow` is a dataclass in `database.py`: `tmdb_id: int, imdb_id: str | None, title: str, original_title: str, alt_titles: tuple[str, ...], release_year: int | None, runtime_min: int | None`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_database.py`:

```python
def test_tmdb_facts_needed_and_upsert(repo):
    from datetime import date
    from movie_brain.domain.models import Film
    from movie_brain.infrastructure.database import TmdbFactsRow

    d = date(2026, 8, 24)
    a = repo.create_film(Film("Alpha", 1950, None, ""))
    b = repo.create_film(Film("Bravo", 1960, None, ""))
    repo.set_external_id(a, "tmdb", "11", d)
    repo.set_external_id(b, "tmdb", "12", d)
    assert repo.tmdb_facts_needed() == [(a, 11), (b, 12)]

    repo.upsert_tmdb_facts(a, TmdbFactsRow(11, "tt0000011", "Alpha", "Alpha", ("Alfa",), 1950, 90), d)
    assert repo.tmdb_facts_needed() == [(b, 12)]

    # link changed → stale row must be refetched
    repo.set_external_id(a, "tmdb", "99", d)
    assert repo.tmdb_facts_needed() == [(a, 99), (b, 12)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_database.py -k tmdb_facts -v`
Expected: FAIL — `ImportError: cannot import name 'TmdbFactsRow'`

- [ ] **Step 3: Write the migration**

Create `migrations/010_audit.sql`:

```sql
-- Data audit (spec 2026-08-24-data-audit-design.md): read-only consistency flags, an
-- append-only human verdict ledger, and a cache of the TMDB facts the checks compare against.
-- audit_flags is a derived report (replaced each run); audit_verdict is never updated/deleted
-- and the dashboard verdict endpoint is its only writer; sync/repair never touch either.
BEGIN;
CREATE TABLE audit_flags (
    film_id INTEGER NOT NULL REFERENCES films(id),
    reason  TEXT    NOT NULL,
    detail  TEXT    NOT NULL,
    score   INTEGER NOT NULL,
    run_on  TEXT    NOT NULL,
    PRIMARY KEY (film_id, reason)
);
CREATE TABLE audit_verdict (
    id        INTEGER PRIMARY KEY,
    film_id   INTEGER NOT NULL REFERENCES films(id),
    verdict   TEXT    NOT NULL,
    reasons   TEXT    NOT NULL,
    note      TEXT,
    marked_on TEXT    NOT NULL
);
CREATE INDEX audit_verdict_film ON audit_verdict(film_id, id);
CREATE TABLE tmdb_facts (
    film_id        INTEGER PRIMARY KEY REFERENCES films(id),
    tmdb_id        INTEGER NOT NULL,
    imdb_id        TEXT,
    title          TEXT    NOT NULL,
    original_title TEXT    NOT NULL,
    alt_titles     TEXT    NOT NULL,
    release_year   INTEGER,
    runtime_min    INTEGER,
    fetched_on     TEXT    NOT NULL
);
INSERT INTO schema_version (version) VALUES (10);
COMMIT;
```

- [ ] **Step 4: Add the dataclass and repo methods**

In `src/movie_brain/infrastructure/database.py`, next to the other module-level dataclasses (near `FilmRow`, ~line 25):

```python
@dataclass(frozen=True)
class TmdbFactsRow:
    tmdb_id: int
    imdb_id: str | None
    title: str
    original_title: str
    alt_titles: tuple[str, ...]
    release_year: int | None
    runtime_min: int | None
```

In `Repository`, after `claimed_values`:

```python
    def tmdb_facts_needed(self) -> list[tuple[int, int]]:
        """Linked films with no tmdb_facts row, or a row fetched for a different tmdb id."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT x.film_id, x.value FROM external_ids x JOIN films f ON f.id = x.film_id "
                "LEFT JOIN tmdb_facts t ON t.film_id = x.film_id "
                "WHERE x.authority = 'tmdb' AND (t.film_id IS NULL OR t.tmdb_id != CAST(x.value AS INTEGER)) "
                "AND " + _NOT_DISPOSED + " ORDER BY x.film_id"
            ).fetchall()
            return [(int(r["film_id"]), int(r["value"])) for r in rows]

    def upsert_tmdb_facts(self, film_id: int, facts: TmdbFactsRow, fetched_on: date) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO tmdb_facts (film_id, tmdb_id, imdb_id, title, original_title, alt_titles, "
                "release_year, runtime_min, fetched_on) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(film_id) DO UPDATE SET tmdb_id=excluded.tmdb_id, imdb_id=excluded.imdb_id, "
                "title=excluded.title, original_title=excluded.original_title, alt_titles=excluded.alt_titles, "
                "release_year=excluded.release_year, runtime_min=excluded.runtime_min, fetched_on=excluded.fetched_on",
                (
                    film_id,
                    facts.tmdb_id,
                    facts.imdb_id,
                    facts.title,
                    facts.original_title,
                    json.dumps(list(facts.alt_titles)),
                    facts.release_year,
                    facts.runtime_min,
                    fetched_on.isoformat(),
                ),
            )
```

(`json` is already imported in `database.py`; verify with `grep -n "^import json" src/movie_brain/infrastructure/database.py` and add it if not.)

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_database.py -k tmdb_facts -v`
Expected: PASS. Then `uv run pytest` — all green (the migration applies on every fresh repo).

- [ ] **Step 6: Commit**

```bash
git add migrations/010_audit.sql src/movie_brain/infrastructure/database.py tests/unit/test_database.py
git commit -m "audit: schema + TMDB facts cache so checks can compare against TMDB offline

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: `TmdbClient.movie_facts`

**Files:**
- Modify: `src/movie_brain/infrastructure/tmdb.py` (next to `movie_titles`, ~line 88)
- Test: `tests/unit/test_tmdb.py`

**Interfaces:**
- Produces: `TmdbFacts(NamedTuple)`: `imdb_id: str | None, title: str, original_title: str, alternatives: tuple[str, ...], year: int | None, runtime_min: int | None`; `TmdbClient.movie_facts(tmdb_id: int) -> TmdbFacts` — ONE call: `GET /movie/{id}?append_to_response=alternative_titles,external_ids`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_tmdb.py`:

```python
def test_movie_facts_is_one_call_with_alts_and_external_ids(rs):
    rs.get(
        f"{TMDB_API}/movie/424",
        json={
            "title": "Schindler's List",
            "original_title": "Schindler's List",
            "release_date": "1993-12-15",
            "runtime": 195,
            "alternative_titles": {"titles": [{"title": "La liste de Schindler"}, {"title": ""}]},
            "external_ids": {"imdb_id": "tt0108052"},
        },
    )
    f = TmdbClient("tok").movie_facts(424)
    assert f.imdb_id == "tt0108052"
    assert (f.title, f.original_title, f.year, f.runtime_min) == ("Schindler's List", "Schindler's List", 1993, 195)
    assert f.alternatives == ("La liste de Schindler",)
    assert len(rs.calls) == 1
    assert "alternative_titles,external_ids" in rs.calls[0].request.url


def test_movie_facts_tolerates_missing_fields(rs):
    rs.get(f"{TMDB_API}/movie/5", json={"title": "X", "original_title": "X"})
    f = TmdbClient("tok").movie_facts(5)
    assert (f.imdb_id, f.year, f.runtime_min, f.alternatives) == (None, None, None, ())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_tmdb.py -k movie_facts -v`
Expected: FAIL — `AttributeError: 'TmdbClient' object has no attribute 'movie_facts'`

- [ ] **Step 3: Implement**

In `src/movie_brain/infrastructure/tmdb.py`, after `TmdbTitles`:

```python
class TmdbFacts(NamedTuple):
    imdb_id: str | None
    title: str
    original_title: str
    alternatives: tuple[str, ...]
    year: int | None
    runtime_min: int | None
```

In `TmdbClient`, after `movie_titles`:

```python
    def movie_facts(self, tmdb_id: int) -> TmdbFacts:
        """Everything the audit compares against, in ONE call (alt titles + external ids appended)."""
        d = self._get(f"/movie/{tmdb_id}", append_to_response="alternative_titles,external_ids").json()
        rd = d.get("release_date") or ""
        year = int(rd[:4]) if len(rd) >= 4 and rd[:4].isdigit() else None
        alts = tuple(
            str(t["title"]) for t in (d.get("alternative_titles") or {}).get("titles") or [] if t.get("title")
        )
        runtime = d.get("runtime")
        imdb = (d.get("external_ids") or {}).get("imdb_id")
        return TmdbFacts(
            imdb_id=str(imdb) if imdb else None,
            title=d.get("title") or "",
            original_title=d.get("original_title") or "",
            alternatives=alts,
            year=year,
            runtime_min=int(runtime) if isinstance(runtime, int) and runtime > 0 else None,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_tmdb.py -v` — all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/infrastructure/tmdb.py tests/unit/test_tmdb.py
git commit -m "audit: TmdbClient.movie_facts — titles, alts, imdb id, runtime in one call

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Pure checks — `domain/audit.py`

**Files:**
- Create: `src/movie_brain/domain/audit.py`
- Test: `tests/unit/test_audit.py`

**Interfaces:**
- Produces:
  - `VERDICTS: tuple[str, ...] = ("fine", "omdb-wrong", "tmdb-wrong", "film-wrong", "twin")`
  - `WEIGHTS: dict[str, int]` (reason code → weight; the spec table)
  - `@dataclass(frozen=True) AuditSubject(film_id, title, year, criterion_director, mc_score, omdb_title, omdb_year, omdb_director, omdb_runtime_min, omdb_imdb_id, omdb_type, omdb_imdb_rating, omdb_metascore, tmdb_imdb_id, tmdb_title, tmdb_original_title, tmdb_alt_titles, tmdb_runtime_min, shared_imdb_film_ids)` — every field `| None` except `film_id: int`, `title: str`, `tmdb_alt_titles: tuple[str, ...]`, `shared_imdb_film_ids: tuple[int, ...]`. `omdb_*` are `None` when there is no found OMDb payload; `tmdb_*` are `None`/empty when there is no `tmdb_facts` row.
  - `@dataclass(frozen=True) AuditFlag(code: str, detail: str, score: int)`
  - `normalize_title(title: str) -> str`
  - `run_checks(s: AuditSubject) -> list[AuditFlag]` (sorted by code)
  - `total_score(flags) -> int`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_audit.py`:

```python
from movie_brain.domain.audit import VERDICTS, WEIGHTS, AuditSubject, normalize_title, run_checks, total_score


def subject(**kw) -> AuditSubject:
    base = dict(
        film_id=1, title="Alpha", year=1950, criterion_director=None, mc_score=None,
        omdb_title=None, omdb_year=None, omdb_director=None, omdb_runtime_min=None, omdb_imdb_id=None,
        omdb_type=None, omdb_imdb_rating=None, omdb_metascore=None,
        tmdb_imdb_id=None, tmdb_title=None, tmdb_original_title=None, tmdb_alt_titles=(), tmdb_runtime_min=None,
        shared_imdb_film_ids=(),
    )
    base.update(kw)
    return AuditSubject(**base)


def codes(s: AuditSubject) -> list[str]:
    return [f.code for f in run_checks(s)]


def test_vocabulary_and_weights():
    assert VERDICTS == ("fine", "omdb-wrong", "tmdb-wrong", "film-wrong", "twin")
    assert WEIGHTS == {
        "mc-score": 3, "imdb-id": 3, "tmdb-title": 3, "omdb-title": 2, "director": 2,
        "runtime": 2, "shared-imdb": 2, "year": 1, "stub": 1,
    }


def test_normalize_title_strips_diacritics_punctuation_articles_and_annotations():
    assert normalize_title("The Deer Hunter") == "deer hunter"
    assert normalize_title("L'Armée des ombres") == "l armee des ombres"
    assert normalize_title("La piscine") == "piscine"
    assert normalize_title("Investigation of a Citizen Above Suspicion [re-release]") == "investigation of a citizen above suspicion"
    assert normalize_title("Schindler's List") == "schindler s list"


def test_no_evidence_no_flags():
    assert codes(subject()) == []


def test_deer_hunter_stub_and_imdb_id():
    s = subject(
        title="The Deer Hunter", year=1978,
        omdb_title="The Deer Hunter (1978)", omdb_year=1978, omdb_director="N/A", omdb_imdb_rating="N/A",
        omdb_imdb_id="tt24735970", omdb_type="movie", tmdb_imdb_id="tt0077416",
    )
    got = codes(s)
    assert "stub" in got and "imdb-id" in got
    assert "omdb-title" in got  # "The Deer Hunter (1978)" normalizes to "deer hunter 1978" ≠ "deer hunter"
    assert "year" not in got


def test_schindler_omdb_title_is_equality_not_containment():
    s = subject(
        title="Schindler's List", year=1993,
        omdb_title="The Making of 'Schindler's List'", omdb_year=1993, omdb_imdb_id="tt2709758",
        tmdb_imdb_id="tt0108052", omdb_type="movie",
    )
    got = codes(s)
    assert got == ["imdb-id", "omdb-title"]
    assert total_score(run_checks(s)) == 5


def test_army_of_shadows_prefix_year_only():
    s = subject(
        title="Army of Shadows", year=1969,
        omdb_title="Army of Shadows", omdb_year=2006, omdb_imdb_id="tt0064040", tmdb_imdb_id="tt0064040",
        omdb_type="movie", omdb_director="Jean-Pierre Melville", omdb_imdb_rating="8.1",
    )
    assert codes(s) == ["year"]


def test_year_within_one_does_not_fire():
    assert codes(subject(year=1978, omdb_year=1979, omdb_title="Alpha")) == []


def test_mc_score_disagreement():
    assert codes(subject(mc_score=95, omdb_metascore=61, omdb_title="Alpha")) == ["mc-score"]
    assert codes(subject(mc_score=95, omdb_metascore=95, omdb_title="Alpha")) == []


def test_director_shares_no_surname():
    assert codes(subject(criterion_director="Powell & Pressburger", omdb_director="Michael Powell, Emeric Pressburger", omdb_title="Alpha")) == []
    assert codes(subject(criterion_director="Jean Renoir", omdb_director="Michael Curtiz", omdb_title="Alpha")) == ["director"]


def test_runtime_gap_over_ten_minutes():
    assert codes(subject(omdb_runtime_min=90, tmdb_runtime_min=105, omdb_title="Alpha")) == ["runtime"]
    assert codes(subject(omdb_runtime_min=90, tmdb_runtime_min=99, omdb_title="Alpha")) == []


def test_tmdb_title_matches_any_of_title_original_or_alts():
    assert codes(subject(title="Harakiri", tmdb_title="Harakiri", tmdb_original_title="切腹")) == []
    assert codes(subject(title="Harakiri", tmdb_title="Seppuku", tmdb_original_title="切腹", tmdb_alt_titles=("Harakiri",))) == []
    assert codes(subject(title="Harakiri", tmdb_title="Seppuku", tmdb_original_title="切腹")) == ["tmdb-title"]


def test_shared_imdb_and_type():
    assert codes(subject(omdb_title="Alpha", omdb_imdb_id="tt1", shared_imdb_film_ids=(7,))) == ["shared-imdb"]
    assert codes(subject(omdb_title="Alpha", omdb_type="series")) == ["stub"]


def test_flag_detail_is_human_readable():
    s = subject(mc_score=95, omdb_metascore=61, omdb_title="Alpha")
    (f,) = run_checks(s)
    assert f.detail == "OMDb Metascore 61 vs Metacritic 95"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_audit.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'movie_brain.domain.audit'`

- [ ] **Step 3: Implement**

Create `src/movie_brain/domain/audit.py`:

```python
"""Cross-source consistency checks (spec 2026-08-24-data-audit-design.md §2).

Pure: takes one AuditSubject per film, returns flags. Never fixes anything. A check fires
only when evidence is present on BOTH sides — absence is not inconsistency.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .matching import split_annotations

VERDICTS: tuple[str, ...] = ("fine", "omdb-wrong", "tmdb-wrong", "film-wrong", "twin")

WEIGHTS: dict[str, int] = {
    "mc-score": 3,
    "imdb-id": 3,
    "tmdb-title": 3,
    "omdb-title": 2,
    "director": 2,
    "runtime": 2,
    "shared-imdb": 2,
    "year": 1,
    "stub": 1,
}

RUNTIME_GAP_MIN = 10
YEAR_GAP = 1
_ARTICLES = frozenset({"the", "a", "an", "le", "la", "les", "il", "lo", "der", "die", "das", "el", "los", "las"})
_NON_ALNUM = re.compile(r"[^0-9a-z]+")


@dataclass(frozen=True)
class AuditSubject:
    film_id: int
    title: str
    year: int | None
    criterion_director: str | None
    mc_score: int | None
    omdb_title: str | None
    omdb_year: int | None
    omdb_director: str | None
    omdb_runtime_min: int | None
    omdb_imdb_id: str | None
    omdb_type: str | None
    omdb_imdb_rating: str | None
    omdb_metascore: int | None
    tmdb_imdb_id: str | None
    tmdb_title: str | None
    tmdb_original_title: str | None
    tmdb_alt_titles: tuple[str, ...]
    tmdb_runtime_min: int | None
    shared_imdb_film_ids: tuple[int, ...]


@dataclass(frozen=True)
class AuditFlag:
    code: str
    detail: str
    score: int


def normalize_title(title: str) -> str:
    t = split_annotations(title)[0]
    t = unicodedata.normalize("NFKD", t)
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    words = _NON_ALNUM.sub(" ", t.casefold()).split()
    if len(words) > 1 and words[0] in _ARTICLES:
        words = words[1:]
    return " ".join(words)


def _surnames(name: str) -> set[str]:
    out: set[str] = set()
    for person in re.split(r",|&| and ", name):
        parts = normalize_title(person).split()
        if parts:
            out.add(parts[-1])
    return out


def _flag(code: str, detail: str) -> AuditFlag:
    return AuditFlag(code, detail, WEIGHTS[code])


def run_checks(s: AuditSubject) -> list[AuditFlag]:
    flags: list[AuditFlag] = []
    if s.mc_score is not None and s.omdb_metascore is not None and s.mc_score != s.omdb_metascore:
        flags.append(_flag("mc-score", f"OMDb Metascore {s.omdb_metascore} vs Metacritic {s.mc_score}"))
    if s.omdb_imdb_id and s.tmdb_imdb_id and s.omdb_imdb_id != s.tmdb_imdb_id:
        flags.append(_flag("imdb-id", f"OMDb imdbID {s.omdb_imdb_id} vs TMDB {s.tmdb_imdb_id}"))
    if s.tmdb_title is not None:
        mine = normalize_title(s.title)
        theirs = {normalize_title(t) for t in (s.tmdb_title, s.tmdb_original_title or "", *s.tmdb_alt_titles) if t}
        if mine not in theirs:
            flags.append(_flag("tmdb-title", f"{s.title!r} matches none of TMDB {s.tmdb_title!r} / {s.tmdb_original_title!r} / {len(s.tmdb_alt_titles)} alts"))
    if s.omdb_title is not None and normalize_title(s.title) != normalize_title(s.omdb_title):
        flags.append(_flag("omdb-title", f"OMDb title {s.omdb_title!r} vs {s.title!r}"))
    if s.criterion_director and s.omdb_director and s.omdb_director != "N/A":
        if not (_surnames(s.criterion_director) & _surnames(s.omdb_director)):
            flags.append(_flag("director", f"OMDb director {s.omdb_director!r} vs Criterion {s.criterion_director!r}"))
    if s.omdb_runtime_min is not None and s.tmdb_runtime_min is not None:
        if abs(s.omdb_runtime_min - s.tmdb_runtime_min) > RUNTIME_GAP_MIN:
            flags.append(_flag("runtime", f"OMDb runtime {s.omdb_runtime_min} min vs TMDB {s.tmdb_runtime_min} min"))
    if s.omdb_imdb_id and s.shared_imdb_film_ids:
        others = ", ".join(f"#{i}" for i in s.shared_imdb_film_ids)
        flags.append(_flag("shared-imdb", f"OMDb imdbID {s.omdb_imdb_id} also held by {others}"))
    if s.year is not None and s.omdb_year is not None and abs(s.year - s.omdb_year) > YEAR_GAP:
        flags.append(_flag("year", f"OMDb year {s.omdb_year} vs film year {s.year}"))
    stub_type = s.omdb_type is not None and s.omdb_type != "movie"
    stub_na = s.omdb_director == "N/A" and s.omdb_imdb_rating == "N/A"
    if s.omdb_title is not None and (stub_type or stub_na):
        why = f"OMDb type {s.omdb_type!r}" if stub_type else "OMDb has no director and no rating"
        flags.append(_flag("stub", why))
    return sorted(flags, key=lambda f: f.code)


def total_score(flags: list[AuditFlag]) -> int:
    return sum(f.score for f in flags)
```

Note on `test_deer_hunter_stub_and_imdb_id`: the `stub` check requires `omdb_title is not None` so a film with no OMDb payload never reads as a stub; the test supplies `omdb_title`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_audit.py -v` — all PASS. If `normalize_title("Schindler's List")` yields `"schindler s list"` as asserted, good; if `split_annotations` alters an input unexpectedly, fix the normalizer, not the test.

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/domain/audit.py tests/unit/test_audit.py
git commit -m "audit: pure cross-source checks with the Deer Hunter / Schindler / Army of Shadows cases as ground truth

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Repository — subjects, flags, verdicts

**Files:**
- Modify: `src/movie_brain/infrastructure/database.py` (Repository, after `upsert_tmdb_facts`)
- Test: `tests/unit/test_database.py`

**Interfaces:**
- Produces:
  - `Repository.audit_subjects() -> list[AuditSubject]` — one per non-disposed film.
  - `Repository.replace_audit_flags(flags: dict[int, list[AuditFlag]], run_on: date) -> None` — DELETE all + INSERT in one transaction.
  - `Repository.add_verdict(film_id, verdict, reasons: list[str], note: str | None, today: date) -> dict[str, object] | None` — returns `{verdict, reasons, note, marked_on}` or `None` when the film is unknown/disposed. Raises `ValueError` for a verdict not in `VERDICTS`.
  - `Repository.current_reasons(film_id) -> list[str]` — sorted reason codes from `audit_flags`.
  - `Repository.verdict_history(verdict: str | None = None) -> list[tuple[int, str, int | None, str, str, str | None, str]]` — (film_id, title, year, verdict, reasons, note, marked_on), oldest first.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_database.py`:

```python
def test_audit_subjects_assemble_all_sources(repo):
    from datetime import date
    from movie_brain.domain.models import Film, McTitle, OmdbRating
    from movie_brain.infrastructure.database import TmdbFactsRow

    d = date(2026, 8, 24)
    repo.record_catalog("criterion", [Film("Alpha", 1950, "Ann Author", "https://c/alpha")], d)
    a = repo.film_id_by_key("alpha (1950)")
    repo.upsert_omdb(
        a,
        OmdbRating(7.0, 80, True, "English",
                   '{"Title":"Alpha Beta","Year":"1952","Director":"Bob Builder","Runtime":"100 min",'
                   '"imdbID":"tt1","Type":"movie","imdbRating":"7.0","Metascore":"61"}', metacritic=61),
        d,
    )
    repo.set_external_id(a, "tmdb", "11", d)
    repo.upsert_tmdb_facts(a, TmdbFactsRow(11, "tt2", "Alpha", "Alpha", ("Alfa",), 1950, 90), d)
    repo.stage_mc_titles([McTitle("Alpha", "alpha", 1950, 95, 1, 1)], d) if hasattr(repo, "stage_mc_titles") else None
    b = repo.create_film(Film("Beta", 1960, None, ""))
    repo.upsert_omdb(b, OmdbRating(None, None, True, None, '{"Title":"Beta","imdbID":"tt1"}'), d)

    subjects = {s.film_id: s for s in repo.audit_subjects()}
    s = subjects[a]
    assert (s.title, s.year, s.criterion_director) == ("Alpha", 1950, "Ann Author")
    assert (s.omdb_title, s.omdb_year, s.omdb_director, s.omdb_runtime_min) == ("Alpha Beta", 1952, "Bob Builder", 100)
    assert (s.omdb_imdb_id, s.omdb_type, s.omdb_imdb_rating, s.omdb_metascore) == ("tt1", "movie", "7.0", 61)
    assert (s.tmdb_imdb_id, s.tmdb_title, s.tmdb_alt_titles, s.tmdb_runtime_min) == ("tt2", "Alpha", ("Alfa",), 90)
    assert s.shared_imdb_film_ids == (b,)
    assert subjects[b].tmdb_title is None and subjects[b].shared_imdb_film_ids == (a,)


def test_audit_flags_replace_and_verdicts_append(repo):
    from datetime import date
    from movie_brain.domain.audit import AuditFlag
    from movie_brain.domain.models import Film
    import pytest

    d = date(2026, 8, 24)
    a = repo.create_film(Film("Alpha", 1950, None, ""))
    repo.replace_audit_flags({a: [AuditFlag("year", "OMDb year 1952 vs film year 1950", 1)]}, d)
    assert repo.current_reasons(a) == ["year"]
    repo.replace_audit_flags({a: [AuditFlag("stub", "x", 1), AuditFlag("imdb-id", "y", 3)]}, d)
    assert repo.current_reasons(a) == ["imdb-id", "stub"]
    repo.replace_audit_flags({}, d)
    assert repo.current_reasons(a) == []

    v = repo.add_verdict(a, "omdb-wrong", ["imdb-id", "stub"], "doc, not the feature", d)
    assert v == {"verdict": "omdb-wrong", "reasons": "imdb-id,stub", "note": "doc, not the feature", "marked_on": "2026-08-24"}
    repo.add_verdict(a, "fine", [], None, d)
    assert [r[3] for r in repo.verdict_history()] == ["omdb-wrong", "fine"]
    assert [r[3] for r in repo.verdict_history("fine")] == ["fine"]
    with pytest.raises(ValueError):
        repo.add_verdict(a, "meh", [], None, d)
    assert repo.add_verdict(999, "fine", [], None, d) is None
```

Before running, check whether the Metacritic staging helper is named `stage_mc_titles`: `grep -n "def stage_mc\|def upsert_mc\|def record_mc" src/movie_brain/infrastructure/database.py`. Use the real name and drop the `hasattr` guard; the `mc_score` assertion is optional — add `assert s.mc_score == 95` if staging plus `set_external_id(a, "metacritic", "alpha", d)` is straightforward, otherwise leave `mc_score` untested here (it's exercised in Task 8's BDD scenario).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_database.py -k "audit" -v`
Expected: FAIL — `AttributeError: 'Repository' object has no attribute 'audit_subjects'`

- [ ] **Step 3: Implement**

Add imports at the top of `database.py`: `from movie_brain.domain.audit import VERDICTS, AuditFlag, AuditSubject`. Then in `Repository`:

```python
    def audit_subjects(self) -> list[AuditSubject]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT f.id, f.title, f.year, f.director, mc.score AS mc_score, o.found, "
                "json_extract(o.payload, '$.Title') AS o_title, json_extract(o.payload, '$.Year') AS o_year, "
                "json_extract(o.payload, '$.Director') AS o_dir, json_extract(o.payload, '$.Runtime') AS o_rt, "
                "json_extract(o.payload, '$.imdbID') AS o_imdb, json_extract(o.payload, '$.Type') AS o_type, "
                "json_extract(o.payload, '$.imdbRating') AS o_rating, json_extract(o.payload, '$.Metascore') AS o_ms, "
                "t.imdb_id AS t_imdb, t.title AS t_title, t.original_title AS t_orig, t.alt_titles AS t_alts, "
                "t.runtime_min AS t_rt "
                "FROM films f "
                "LEFT JOIN omdb o ON o.film_id = f.id AND o.found = 1 AND o.payload IS NOT NULL "
                "LEFT JOIN external_ids x ON x.film_id = f.id AND x.authority = 'metacritic' "
                "LEFT JOIN metacritic mc ON mc.slug = x.value "
                "LEFT JOIN tmdb_facts t ON t.film_id = f.id "
                "WHERE " + _NOT_DISPOSED + " ORDER BY f.id"
            ).fetchall()
            by_imdb: dict[str, list[int]] = {}
            for r in rows:
                if r["o_imdb"]:
                    by_imdb.setdefault(str(r["o_imdb"]), []).append(int(r["id"]))
            out: list[AuditSubject] = []
            for r in rows:
                fid = int(r["id"])
                o_year = str(r["o_year"] or "")[:4]
                rt_m = _RUNTIME_MIN.match(str(r["o_rt"])) if r["o_rt"] else None
                ms = r["o_ms"]
                out.append(
                    AuditSubject(
                        film_id=fid,
                        title=str(r["title"]),
                        year=r["year"],
                        criterion_director=r["director"],
                        mc_score=r["mc_score"],
                        omdb_title=r["o_title"],
                        omdb_year=int(o_year) if o_year.isdigit() else None,
                        omdb_director=r["o_dir"],
                        omdb_runtime_min=int(rt_m.group(1)) if rt_m else None,
                        omdb_imdb_id=r["o_imdb"],
                        omdb_type=r["o_type"],
                        omdb_imdb_rating=r["o_rating"],
                        omdb_metascore=int(ms) if isinstance(ms, str) and ms.isdigit() else None,
                        tmdb_imdb_id=r["t_imdb"],
                        tmdb_title=r["t_title"],
                        tmdb_original_title=r["t_orig"],
                        tmdb_alt_titles=tuple(json.loads(r["t_alts"])) if r["t_alts"] else (),
                        tmdb_runtime_min=r["t_rt"],
                        shared_imdb_film_ids=tuple(i for i in by_imdb.get(str(r["o_imdb"] or ""), []) if i != fid),
                    )
                )
            return out

    def replace_audit_flags(self, flags: dict[int, list[AuditFlag]], run_on: date) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM audit_flags")
            c.executemany(
                "INSERT INTO audit_flags (film_id, reason, detail, score, run_on) VALUES (?, ?, ?, ?, ?)",
                [(fid, f.code, f.detail, f.score, run_on.isoformat()) for fid, fl in flags.items() for f in fl],
            )

    def current_reasons(self, film_id: int) -> list[str]:
        with self._conn() as c:
            rows = c.execute("SELECT reason FROM audit_flags WHERE film_id = ? ORDER BY reason", (film_id,)).fetchall()
            return [str(r["reason"]) for r in rows]

    def add_verdict(
        self, film_id: int, verdict: str, reasons: list[str], note: str | None, today: date
    ) -> dict[str, object] | None:
        if verdict not in VERDICTS:
            raise ValueError(f"unknown verdict {verdict!r}; expected one of {', '.join(VERDICTS)}")
        with self._conn() as c:
            if c.execute("SELECT 1 FROM films f WHERE f.id = ? AND " + _NOT_DISPOSED, (film_id,)).fetchone() is None:
                return None
            joined = ",".join(sorted(reasons))
            c.execute(
                "INSERT INTO audit_verdict (film_id, verdict, reasons, note, marked_on) VALUES (?, ?, ?, ?, ?)",
                (film_id, verdict, joined, note, today.isoformat()),
            )
            return {"verdict": verdict, "reasons": joined, "note": note, "marked_on": today.isoformat()}

    def verdict_history(
        self, verdict: str | None = None
    ) -> list[tuple[int, str, int | None, str, str, str | None, str]]:
        with self._conn() as c:
            sql = (
                "SELECT v.film_id, f.title, f.year, v.verdict, v.reasons, v.note, v.marked_on "
                "FROM audit_verdict v JOIN films f ON f.id = v.film_id "
            )
            params: tuple[object, ...] = ()
            if verdict is not None:
                sql += "WHERE v.verdict = ? "
                params = (verdict,)
            rows = c.execute(sql + "ORDER BY v.id", params).fetchall()
            return [
                (int(r["film_id"]), str(r["title"]), r["year"], str(r["verdict"]), str(r["reasons"]), r["note"], str(r["marked_on"]))
                for r in rows
            ]
```

`_NOT_DISPOSED` references the `films` alias `f` — confirm with `grep -n "^_NOT_DISPOSED" src/movie_brain/infrastructure/database.py` and match the alias in `add_verdict`'s query.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_database.py -k audit -v` then `uv run pytest && uv run ruff check . && uv run mypy`. All green.

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/infrastructure/database.py tests/unit/test_database.py
git commit -m "audit: repository assembles subjects, replaces flags, appends verdicts

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: `run_audit` use case + `audit run` verb (BDD)

**Files:**
- Create: `src/movie_brain/application/audit.py`
- Create: `tests/features/audit.feature`, `tests/step_defs/test_audit.py`
- Modify: `src/movie_brain/cli.py`

**Interfaces:**
- Produces: `run_audit(repo, today, *, tmdb: TmdbClient | None, delay_s: float = 0.25, log=...) -> AuditReport` with `AuditReport(facts_fetched: int, facts_failed: int, films: int, suspects: int, by_reason: dict[str, int], top: list[tuple[int, str, int, list[str]]], exit_code: int)`. `tmdb=None` means skip the facts fill (the `--no-tmdb` flag or no token).

- [ ] **Step 1: Write the feature**

Create `tests/features/audit.feature`:

```gherkin
Feature: Data audit
  A read-only pass that scores every film against cross-source consistency checks and
  records the human's verdicts without ever fixing anything itself.

  Background:
    Given a fresh repository
    And a Criterion film "Alpha (1950)" directed by "Ann Author" linked to TMDB id 11
    And "Alpha (1950)" has an OMDb payload titled "Alpha" year 1950 imdb "tt1" director "Ann Author"

  Scenario: The verb caches TMDB facts once and writes flags
    Given TMDB facts for id 11 are title "Alpha" imdb "tt2" runtime 90
    When I run the audit
    Then the audit fetched 1 TMDB facts
    And "Alpha (1950)" is flagged with reasons "imdb-id"
    When I run the audit again
    Then the audit fetched 0 TMDB facts
    And "Alpha (1950)" is flagged with reasons "imdb-id"

  Scenario: --no-tmdb makes no TMDB calls and still runs the offline checks
    Given "Alpha (1950)" has an OMDb payload titled "Alpha Beta" year 1950 imdb "tt1" director "Ann Author"
    When I run the audit without TMDB
    Then no TMDB request was made
    And "Alpha (1950)" is flagged with reasons "omdb-title"

  Scenario: A TMDB failure on one film skips it and the audit still completes
    Given TMDB facts for id 11 fail with a server error
    When I run the audit
    Then the audit fetched 0 TMDB facts and 1 failed
    And "Alpha (1950)" is flagged with reasons ""
    And the audit exit code is 0

  Scenario: Flags are replaced, not accumulated
    Given "Alpha (1950)" has an OMDb payload titled "Alpha Beta" year 1950 imdb "tt1" director "Ann Author"
    When I run the audit without TMDB
    Then "Alpha (1950)" is flagged with reasons "omdb-title"
    Given "Alpha (1950)" has an OMDb payload titled "Alpha" year 1950 imdb "tt1" director "Ann Author"
    When I run the audit without TMDB
    Then "Alpha (1950)" is flagged with reasons ""

  Scenario: Verdict history lists in order and never changes the flags
    Given "Alpha (1950)" has an OMDb payload titled "Alpha Beta" year 1950 imdb "tt1" director "Ann Author"
    When I run the audit without TMDB
    And I mark "Alpha (1950)" as "omdb-wrong" with note "wrong record"
    And I mark "Alpha (1950)" as "fine" with note ""
    Then the verdict history is "omdb-wrong, fine"
    And "Alpha (1950)" is flagged with reasons "omdb-title"
```

- [ ] **Step 2: Write the step definitions**

Create `tests/step_defs/test_audit.py`:

```python
from __future__ import annotations

import json
import re
from datetime import date

import pytest
import requests
import responses
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.audit import run_audit
from movie_brain.domain.models import Film, OmdbRating
from movie_brain.infrastructure.tmdb import TMDB_API, TmdbClient

scenarios("../features/audit.feature")
TODAY = date(2026, 8, 24)


def _key(spec: str) -> str:
    m = re.fullmatch(r"(.+) \((\d{4})\)", spec)
    assert m
    return f"{m.group(1).lower()} ({m.group(2)})"


@pytest.fixture
def ctx(repo):
    rs = responses.RequestsMock(assert_all_requests_are_fired=False)
    rs.start()
    yield {"repo": repo, "rs": rs, "report": None}
    rs.stop()
    rs.reset()


@given("a fresh repository")
def fresh(ctx):
    pass


@given(parsers.parse('a Criterion film "{spec}" directed by "{director}" linked to TMDB id {tid:d}'))
def crit_film(ctx, spec, director, tid):
    m = re.fullmatch(r"(.+) \((\d{4})\)", spec)
    ctx["repo"].record_catalog("criterion", [Film(m.group(1), int(m.group(2)), director, "https://c/x")], TODAY)
    ctx["repo"].set_external_id(ctx["repo"].film_id_by_key(_key(spec)), "tmdb", str(tid), TODAY)


@given(parsers.parse('"{spec}" has an OMDb payload titled "{title}" year {year:d} imdb "{imdb}" director "{director}"'))
def omdb_payload(ctx, spec, title, year, imdb, director):
    payload = json.dumps({"Title": title, "Year": str(year), "imdbID": imdb, "Director": director, "Type": "movie", "imdbRating": "7.0"})
    ctx["repo"].upsert_omdb(ctx["repo"].film_id_by_key(_key(spec)), OmdbRating(7.0, None, True, "English", payload), TODAY)


@given(parsers.parse('TMDB facts for id {tid:d} are title "{title}" imdb "{imdb}" runtime {rt:d}'))
def tmdb_facts(ctx, tid, title, imdb, rt):
    ctx["rs"].get(
        f"{TMDB_API}/movie/{tid}",
        json={"title": title, "original_title": title, "release_date": "1950-01-01", "runtime": rt,
              "alternative_titles": {"titles": []}, "external_ids": {"imdb_id": imdb}},
    )


@given(parsers.parse("TMDB facts for id {tid:d} fail with a server error"))
def tmdb_fail(ctx, tid):
    ctx["rs"].get(f"{TMDB_API}/movie/{tid}", status=500, body="boom")


def _run(ctx, with_tmdb: bool):
    client = TmdbClient("tok", session=requests.Session()) if with_tmdb else None
    ctx["report"] = run_audit(ctx["repo"], TODAY, tmdb=client, delay_s=0, log=lambda m: None)


@when("I run the audit")
@when("I run the audit again")
def run_with(ctx):
    _run(ctx, True)


@when("I run the audit without TMDB")
def run_without(ctx):
    _run(ctx, False)


@when(parsers.re(r'I mark "(?P<spec>[^"]+)" as "(?P<verdict>[^"]+)" with note "(?P<note>[^"]*)"'))
def mark(ctx, spec, verdict, note):
    r = ctx["repo"]
    fid = r.film_id_by_key(_key(spec))
    r.add_verdict(fid, verdict, r.current_reasons(fid), note or None, TODAY)


@then(parsers.parse("the audit fetched {n:d} TMDB facts"))
def fetched(ctx, n):
    assert ctx["report"].facts_fetched == n


@then(parsers.parse("the audit fetched {n:d} TMDB facts and {m:d} failed"))
def fetched_failed(ctx, n, m):
    assert (ctx["report"].facts_fetched, ctx["report"].facts_failed) == (n, m)


@then("no TMDB request was made")
def no_tmdb(ctx):
    assert not any(TMDB_API in c.request.url for c in ctx["rs"].calls)


@then(parsers.re(r'"(?P<spec>[^"]+)" is flagged with reasons "(?P<reasons>[^"]*)"'))
def flagged(ctx, spec, reasons):
    got = ctx["repo"].current_reasons(ctx["repo"].film_id_by_key(_key(spec)))
    assert got == ([r.strip() for r in reasons.split(",")] if reasons else [])


@then(parsers.parse("the audit exit code is {code:d}"))
def exit_code(ctx, code):
    assert ctx["report"].exit_code == code


@then(parsers.parse('the verdict history is "{expected}"'))
def history(ctx, expected):
    assert [r[3] for r in ctx["repo"].verdict_history()] == [v.strip() for v in expected.split(",")]
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/step_defs/test_audit.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'movie_brain.application.audit'`

- [ ] **Step 4: Implement the use case**

Create `src/movie_brain/application/audit.py`:

```python
"""Data audit (spec 2026-08-24-data-audit-design.md §3): fill TMDB facts, run the pure
checks, replace the flags, report. Read-only with respect to every other table."""

from __future__ import annotations

import sys
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

import requests

from movie_brain.domain.audit import AuditFlag, run_checks, total_score
from movie_brain.infrastructure.database import Repository, TmdbFactsRow
from movie_brain.infrastructure.tmdb import AuthError, TmdbClient

TOP_N = 20


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


@dataclass
class AuditReport:
    facts_fetched: int = 0
    facts_failed: int = 0
    films: int = 0
    suspects: int = 0
    by_reason: dict[str, int] = field(default_factory=dict)
    top: list[tuple[int, str, int, list[str]]] = field(default_factory=list)  # (film_id, title, score, codes)
    exit_code: int = 0


def _fill_facts(repo: Repository, tmdb: TmdbClient, today: date, delay_s: float, log: Callable[[str], None], report: AuditReport) -> None:
    for film_id, tmdb_id in repo.tmdb_facts_needed():
        try:
            f = tmdb.movie_facts(tmdb_id)
        except AuthError as exc:
            log(f"TMDB rejected the token: {exc} — facts fill stopped, offline checks continue")
            return
        except (requests.RequestException, ValueError) as exc:
            log(f"tmdb facts failed for film {film_id} (id {tmdb_id}): {exc}")
            report.facts_failed += 1
            continue
        repo.upsert_tmdb_facts(
            film_id,
            TmdbFactsRow(tmdb_id, f.imdb_id, f.title, f.original_title, f.alternatives, f.year, f.runtime_min),
            today,
        )
        report.facts_fetched += 1
        if delay_s:
            time.sleep(delay_s)


def run_audit(
    repo: Repository,
    today: date,
    *,
    tmdb: TmdbClient | None,
    delay_s: float = 0.25,
    log: Callable[[str], None] = _stderr,
) -> AuditReport:
    report = AuditReport()
    if tmdb is not None:
        _fill_facts(repo, tmdb, today, delay_s, log, report)
    subjects = repo.audit_subjects()
    flags: dict[int, list[AuditFlag]] = {}
    titles: dict[int, str] = {}
    for s in subjects:
        fl = run_checks(s)
        if fl:
            flags[s.film_id] = fl
            titles[s.film_id] = s.title
    repo.replace_audit_flags(flags, today)
    report.films = len(subjects)
    report.suspects = len(flags)
    report.by_reason = dict(Counter(f.code for fl in flags.values() for f in fl))
    ranked = sorted(flags.items(), key=lambda kv: (-total_score(kv[1]), kv[0]))
    report.top = [(fid, titles[fid], total_score(fl), [f.code for f in fl]) for fid, fl in ranked[:TOP_N]]
    return report
```

Check `requests.HTTPError` is a `RequestException` subclass (it is) — a 500 from `_get`'s `raise_for_status` lands in the per-film branch.

- [ ] **Step 5: Run BDD to verify it passes**

Run: `uv run pytest tests/step_defs/test_audit.py -v` — all PASS.

- [ ] **Step 6: Wire the CLI verbs**

In `src/movie_brain/cli.py`, add after `review_app` is registered:

```python
audit_app = typer.Typer(help="Data audit: read-only consistency checks; the human records verdicts in the dashboard.")
app.add_typer(audit_app, name="audit")
```

and the commands (imports: `from movie_brain.application.audit import run_audit`):

```python
@audit_app.command("run")
def audit_run(
    no_tmdb: Annotated[bool, typer.Option("--no-tmdb", help="Skip the TMDB facts fill; offline checks only.")] = False,
) -> None:
    """Score every film against cross-source consistency checks and replace audit_flags."""
    cfg = load_config()
    token = None if no_tmdb else load_tmdb_token(cfg)
    if not no_tmdb and not token:
        err.print(f"no TMDB token (set MOVIE_BRAIN_TMDB_TOKEN or write {cfg.tmdb_token_file}); running offline checks only")
    client = TmdbClient(token) if token else None
    report = run_audit(_repo(), date.today(), tmdb=client)
    console.print(
        f"films: {report.films} · suspects: {report.suspects} · tmdb facts fetched: {report.facts_fetched} · failed: {report.facts_failed}"
    )
    table = Table(title="flags by reason")
    table.add_column("reason")
    table.add_column("films", justify="right")
    for code, n in sorted(report.by_reason.items(), key=lambda kv: -kv[1]):
        table.add_row(code, str(n))
    console.print(table)
    top = Table(title=f"top {len(report.top)} suspects")
    for col in ("film", "title", "score", "reasons"):
        top.add_column(col)
    for fid, title, score, codes in report.top:
        top.add_row(f"#{fid}", title, str(score), ", ".join(codes))
    console.print(top)
    raise typer.Exit(report.exit_code)


@audit_app.command("verdicts")
def audit_verdicts(
    verdict: Annotated[str | None, typer.Option("--verdict", help="Only this verdict.")] = None,
) -> None:
    """Verdict history — the pattern-analysis export (oldest first)."""
    rows = _repo().verdict_history(verdict)
    table = Table(title=f"verdicts ({len(rows)})")
    for col in ("film", "title", "year", "verdict", "reasons", "note", "marked"):
        table.add_column(col)
    for fid, title, year, v, reasons, note, marked in rows:
        table.add_row(f"#{fid}", title, str(year or ""), v, reasons, note or "", marked)
    console.print(table)
```

Smoke: `uv run movie-brain audit --help` shows `run` and `verdicts`.

- [ ] **Step 7: Gates + commit**

Run: `uv run pytest && uv run ruff check . && uv run mypy`

```bash
git add src/movie_brain/application/audit.py src/movie_brain/cli.py tests/features/audit.feature tests/step_defs/test_audit.py
git commit -m "audit run / audit verdicts: read-only consistency pass with its own TMDB tripwire

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: `FilmView.audit` / `FilmView.verdict` with `fine` suppression

**Files:**
- Modify: `src/movie_brain/domain/models.py` (`FilmView`, ~line 114)
- Modify: `src/movie_brain/infrastructure/database.py` (`_row_to_view`, `list_views`, `get_view`, a new `_audit_by_film` helper)
- Test: `tests/unit/test_database.py`

**Interfaces:**
- Produces: `FilmView.audit: dict[str, object] | None` = `{"score": int, "reasons": [{"code", "detail"}, ...]}`; `FilmView.verdict: dict[str, object] | None` = the latest verdict row `{verdict, reasons, note, marked_on}`.
- Suppression rule: `audit` is `None` when the latest verdict is `fine` AND its `reasons` == the current sorted codes joined by `,`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_database.py`:

```python
def test_view_carries_audit_and_fine_suppresses_only_the_same_reason_set(repo):
    from datetime import date
    from movie_brain.domain.audit import AuditFlag
    from movie_brain.domain.models import Film

    d = date(2026, 8, 24)
    a = repo.create_film(Film("Alpha", 1950, None, ""))
    repo.replace_audit_flags({a: [AuditFlag("stub", "no director and no rating", 1), AuditFlag("imdb-id", "tt1 vs tt2", 3)]}, d)
    v = repo.get_view(a, d)
    assert v.audit == {"score": 4, "reasons": [{"code": "imdb-id", "detail": "tt1 vs tt2"}, {"code": "stub", "detail": "no director and no rating"}]}
    assert v.verdict is None

    repo.add_verdict(a, "omdb-wrong", ["imdb-id", "stub"], None, d)
    v = repo.get_view(a, d)
    assert v.audit is not None and v.verdict["verdict"] == "omdb-wrong"

    repo.add_verdict(a, "fine", ["imdb-id", "stub"], "checked", d)
    assert repo.get_view(a, d).audit is None
    assert [x.audit for x in repo.list_views("criterion", d) if x.id == a] == [None]

    repo.replace_audit_flags({a: [AuditFlag("stub", "x", 1), AuditFlag("imdb-id", "y", 3), AuditFlag("year", "z", 1)]}, d)
    assert repo.get_view(a, d).audit["score"] == 5  # new reason → re-flagged
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_database.py -k fine_suppresses -v`
Expected: FAIL — `AttributeError: 'FilmView' object has no attribute 'audit'`

- [ ] **Step 3: Implement**

`src/movie_brain/domain/models.py`, add to `FilmView` after `revisit_note`:

```python
    audit: dict[str, object] | None = None  # {score, reasons:[{code, detail}]} from audit_flags; None = not a suspect
    verdict: dict[str, object] | None = None  # latest audit_verdict row; the dashboard endpoint is its only writer
```

`src/movie_brain/infrastructure/database.py`, helper next to `_revisit_by_film`:

```python
def _audit_by_film(c: sqlite3.Connection) -> dict[int, tuple[dict[str, object] | None, dict[str, object] | None]]:
    """(audit, verdict) per film. `fine` suppresses audit only for the identical reason set."""
    flags: dict[int, list[dict[str, object]]] = {}
    scores: dict[int, int] = {}
    for r in c.execute("SELECT film_id, reason, detail, score FROM audit_flags ORDER BY film_id, reason"):
        fid = int(r["film_id"])
        flags.setdefault(fid, []).append({"code": str(r["reason"]), "detail": str(r["detail"])})
        scores[fid] = scores.get(fid, 0) + int(r["score"])
    latest: dict[int, dict[str, object]] = {}
    for r in c.execute(
        "SELECT v.film_id, v.verdict, v.reasons, v.note, v.marked_on FROM audit_verdict v "
        "WHERE v.id = (SELECT MAX(id) FROM audit_verdict WHERE film_id = v.film_id)"
    ):
        latest[int(r["film_id"])] = {
            "verdict": str(r["verdict"]), "reasons": str(r["reasons"]), "note": r["note"], "marked_on": str(r["marked_on"]),
        }
    out: dict[int, tuple[dict[str, object] | None, dict[str, object] | None]] = {}
    for fid in set(flags) | set(latest):
        audit: dict[str, object] | None = None
        if fid in flags:
            codes = ",".join(str(f["code"]) for f in flags[fid])
            v = latest.get(fid)
            if not (v and v["verdict"] == "fine" and v["reasons"] == codes):
                audit = {"score": scores[fid], "reasons": flags[fid]}
        out[fid] = (audit, latest.get(fid))
    return out
```

Thread it through: `_row_to_view` gains `audit: tuple[dict[str, object] | None, dict[str, object] | None] = (None, None)` and sets `audit=audit[0], verdict=audit[1]`; `list_views` computes `au = _audit_by_film(c)` once and passes `audit=au.get(r["id"], (None, None))`; `get_view` does the same for its single row.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_database.py -k fine_suppresses -v`, then the full gates. `tests/web/test_api.py::test_list_films` asserts `"payload" not in trio` only — the two new keys are fine.

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/domain/models.py src/movie_brain/infrastructure/database.py tests/unit/test_database.py
git commit -m "audit: FilmView carries flags + latest verdict; fine suppresses only the same reason set

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Suspect chip (lockstep) + verdict endpoint

**Files:**
- Modify: `src/movie_brain/domain/filters.py`, `src/movie_brain/web/static/app.js` (CHIP_PREDICATES ~line 17), `src/movie_brain/web/templates/index.html` (chips ~line 37), `src/movie_brain/web/app.py`
- Test: `tests/web/test_api.py`, `tests/web/test_dashboard.py` (`test_chip_labels_and_order`, `test_each_chip_alone`)

**Interfaces:**
- Produces: chip key `suspect`; `POST /api/films/<id>/verdict` body `{"verdict": str, "note": str|null}` → 200 `{verdict, reasons, note, marked_on, audit}` (`audit` = the film's post-verdict `FilmView.audit`, so the client can drop the chip after a `fine`); 400 on bad body/verdict; 404 unknown film.

- [ ] **Step 1: Write the failing tests**

Append to `tests/web/test_api.py`:

```python
def test_suspect_chip_and_verdict_endpoint(client, repo):
    from movie_brain.domain.audit import AuditFlag

    fid = next(x["id"] for x in client.get("/api/films").get_json() if x["title"] == "Trio")
    repo.replace_audit_flags({fid: [AuditFlag("omdb-title", "OMDb title 'Trio Redux' vs 'Trio'", 2)]}, D)
    assert "suspect" in client.get("/api/config").get_json()["chips"]
    trio = client.get(f"/api/films/{fid}").get_json()
    assert trio["audit"] == {"score": 2, "reasons": [{"code": "omdb-title", "detail": "OMDb title 'Trio Redux' vs 'Trio'"}]}

    r = client.post(f"/api/films/{fid}/verdict", json={"verdict": "omdb-wrong", "note": "wrong record"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["verdict"] == "omdb-wrong" and body["reasons"] == "omdb-title" and body["audit"] is not None
    assert client.get(f"/api/films/{fid}").get_json()["verdict"]["note"] == "wrong record"

    r = client.post(f"/api/films/{fid}/verdict", json={"verdict": "fine"})
    assert r.status_code == 200 and r.get_json()["audit"] is None

    assert client.post(f"/api/films/{fid}/verdict", json={"verdict": "meh"}).status_code == 400
    assert client.post(f"/api/films/{fid}/verdict", json={}).status_code == 400
    assert client.post("/api/films/999/verdict", json={"verdict": "fine"}).status_code == 404
    assert len(repo.verdict_history()) == 2  # append-only: nothing overwritten
```

In `tests/web/test_dashboard.py::test_chip_labels_and_order` insert `"Suspect",` after `"Needs revisit",`. In `test_each_chip_alone` add `"suspect": 1,` (Task 8 seeds one suspect — Bravo — in `tests/web/conftest.py`; add the seed now so this passes: after the watchlist toggle line in `seed()`:

```python
    # Bravo is also the one seeded audit suspect (an OMDb title disagreement) for the Suspect chip + drawer verdict tests.
    from movie_brain.domain.audit import AuditFlag

    repo.replace_audit_flags({ids["bravo (1960)"]: [AuditFlag("omdb-title", "OMDb title 'Bravo Two' vs 'Bravo'", 2)]}, TODAY)
```
)

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/web/test_api.py -k suspect -v`
Expected: FAIL — `"suspect" in chips` assertion.

- [ ] **Step 3: Implement (lockstep)**

`domain/filters.py` `_PREDICATES`: add `"suspect": lambda v, _: v.audit is not None,`.

`static/app.js` `CHIP_PREDICATES`: add `suspect: (f) => f.audit != null,`.

`templates/index.html`: add `<button class="chip" data-chip="suspect">Suspect</button>` after the Needs revisit chip.

`web/app.py`, after `put_revisit_note` (import `VERDICTS` from `movie_brain.domain.audit`):

```python
    @app.post("/api/films/<int:film_id>/verdict")
    def post_verdict(film_id: int) -> tuple[Response, int]:
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or body.get("verdict") not in VERDICTS:
            return jsonify({"error": f"body must be JSON {{\"verdict\": one of {', '.join(VERDICTS)}, \"note\"?: str}}"}), 400
        note = body.get("note")
        if note is not None and not isinstance(note, str):
            return jsonify({"error": "note must be a string"}), 400
        reasons = repo.current_reasons(film_id)
        result = repo.add_verdict(film_id, body["verdict"], reasons, note or None, today())
        if result is None:
            return jsonify({"error": "not found"}), 404
        view = repo.get_view(film_id, today())
        return jsonify({**result, "audit": view.audit if view else None}), 200
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/web -v` (Playwright needs chromium installed) — all PASS, including the chip label/count tests.

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/domain/filters.py src/movie_brain/web/static/app.js src/movie_brain/web/templates/index.html src/movie_brain/web/app.py tests/web/test_api.py tests/web/test_dashboard.py tests/web/conftest.py
git commit -m "Suspect chip + append-only verdict endpoint (the only audit_verdict writer)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: Drawer audit block + verdict buttons (Playwright)

**Files:**
- Modify: `src/movie_brain/web/static/app.js` (drawer render ~line 325; event handlers ~line 398), `src/movie_brain/web/static/style.css` if present (`ls src/movie_brain/web/static`)
- Test: `tests/web/test_dashboard.py`

**Interfaces:**
- Consumes: `f.audit`, `f.verdict`, `POST /api/films/<id>/verdict`.
- DOM: `.audit-block` containing `ul.audit-reasons > li[data-code]`, `.audit-verdict` (latest verdict text or empty), `button.verdict-btn[data-verdict]` ×5, `input.verdict-note`.

- [ ] **Step 1: Write the failing Playwright test**

Append to `tests/web/test_dashboard.py`:

```python
def test_drawer_shows_audit_reasons_and_records_a_verdict(dash: Page):
    clear_lang(dash)
    dash.click(".chip[data-chip=suspect]")
    assert count(dash) == 1  # Bravo
    dash.locator("#films tbody tr[data-id]").filter(has_text="Bravo").click()
    block = dash.locator(".audit-block")
    expect(block.locator("li[data-code=omdb-title]")).to_contain_text("Bravo Two")
    expect(block.locator(".audit-verdict")).to_have_text("")
    block.locator("input.verdict-note").fill("wrong record")
    block.locator("button.verdict-btn[data-verdict=omdb-wrong]").click()
    expect(block.locator(".audit-verdict")).to_contain_text("omdb-wrong")
    assert count(dash) == 1  # a non-fine verdict keeps the film a suspect
    block.locator("button.verdict-btn[data-verdict=fine]").click()
    expect(dash.locator("#films tbody")).to_have_attribute("data-count", "0")  # fine on the same reason set hides it
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/web/test_dashboard.py -k audit_reasons -v`
Expected: FAIL — `.audit-block` not found (timeout).

- [ ] **Step 3: Implement**

In `app.js`, in the drawer HTML builder (the function returning the `<h2>…` template at ~line 325), append after the revisit note input:

```js
      ${renderAudit(d)}
```

and add the helper near the other render helpers:

```js
  const VERDICTS = ['fine', 'omdb-wrong', 'tmdb-wrong', 'film-wrong', 'twin'];
  function renderAudit(d) {
    if (!d.audit && !d.verdict) return '';
    const reasons = d.audit ? d.audit.reasons.map((r) => `<li data-code="${esc(r.code)}"><b>${esc(r.code)}</b> — ${esc(r.detail)}</li>`).join('') : '';
    const verdict = d.verdict ? `${esc(d.verdict.verdict)} (${esc(d.verdict.marked_on)})${d.verdict.note ? ' — ' + esc(d.verdict.note) : ''}` : '';
    const buttons = VERDICTS.map((v) => `<button class="verdict-btn" data-id="${d.id}" data-verdict="${v}">${v}</button>`).join('');
    return `<div class="audit-block" data-id="${d.id}">
      <h3>Audit${d.audit ? ` · score ${d.audit.score}` : ''}</h3>
      <ul class="audit-reasons">${reasons}</ul>
      <div class="audit-verdict">${verdict}</div>
      <input class="verdict-note" placeholder="note (optional)">
      <div class="verdict-buttons">${buttons}</div>
    </div>`;
  }
```

Event handler next to the revisit-toggle handler:

```js
  document.addEventListener('click', async (e) => {
    const b = e.target.closest('.verdict-btn'); if (!b) return;
    const id = Number(b.dataset.id);
    const block = b.closest('.audit-block');
    const note = block.querySelector('.verdict-note').value.trim();
    const r = await fetch(`/api/films/${id}/verdict`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ verdict: b.dataset.verdict, note: note || null }) });
    if (!r.ok) { toast('Could not record verdict'); return; }
    const res = await r.json();
    const film = state.films.find((f) => f.id === id);
    if (film) { film.verdict = { verdict: res.verdict, reasons: res.reasons, note: res.note, marked_on: res.marked_on }; film.audit = res.audit; applyFilters(); }
    block.querySelector('.audit-verdict').textContent = `${res.verdict} (${res.marked_on})${res.note ? ' — ' + res.note : ''}`;
    if (!res.audit) block.querySelector('.audit-reasons').innerHTML = '';
  });
```

Confirm the names `state.films`, `applyFilters`, `toast`, `esc` match what `app.js` already uses (`grep -n "function applyFilters\|function toast\|const esc\|state.films" src/movie_brain/web/static/app.js`) and adapt if the list is held under a different key. Minimal CSS (in the existing stylesheet or `<style>` block in `index.html`): `.audit-block{margin-top:1rem;border-top:1px solid var(--border,#ccc);padding-top:.5rem}.verdict-buttons button{margin-right:.25rem}`.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/web -v` — all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/web/static src/movie_brain/web/templates tests/web/test_dashboard.py
git commit -m "drawer: audit reasons + five verdict buttons; fine on the same reason set drops the chip

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 9: Docs + final gates

**Files:**
- Modify: `CLAUDE.md` (Commands block + Rules)

- [ ] **Step 1: Document the verbs and rules**

In the `## Commands` block add:

```
uv run movie-brain audit run [--no-tmdb]              # read-only consistency checks → audit_flags (+ one-time TMDB facts cache); prints tally + top suspects
uv run movie-brain audit verdicts [--verdict V]       # append-only human verdict history (pattern-analysis export)
```

In `## Rules` add one bullet:

```
- Data audit (`docs/superpowers/specs/2026-08-24-data-audit-design.md`): `audit_flags` is a derived
  report replaced by every `audit run`; `tmdb_facts` is a one-call-per-film cache refetched only when
  the film's `tmdb` link changes; `audit_verdict` is append-only user-response data — the drawer's
  verdict endpoint is its ONLY writer, sync/repair/review never touch it, and a `fine` verdict
  suppresses the Suspect chip only while the film's reason set is unchanged. Checks live in
  `domain/audit.py` (weights are named constants); the verb never fixes anything.
```

- [ ] **Step 2: Full gates**

Run: `uv run pytest && uv run ruff check . && uv run mypy && uv run python scripts/matching_benchmark.py --assert-dominance`
Expected: all green (the benchmark is untouched by this work).

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: audit verbs + audit data rules

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Self-review (done while writing)

- **Spec coverage:** §1 schema → Task 1; §2 checks + normalizer + weights → Task 3 (runtime uses TMDB runtime per the spec patch); §3 verb (facts fill, tripwire, `--no-tmdb`, tally/top-20, `audit verdicts`) → Tasks 2, 5; §4 view/suppression/chip/drawer/endpoint → Tasks 6–8; §5 tests → each task; §6 is explicitly not built.
- **Type consistency:** `TmdbFactsRow` (database) vs `TmdbFacts` (tmdb adapter) are distinct on purpose — the adapter never imports the repository. `add_verdict` returns the same dict shape `_audit_by_film` produces for `FilmView.verdict`. `current_reasons` feeds both the endpoint and the BDD `mark` step.
- **Placeholders:** none; every step has code. The one lookup the implementer must do is the Metacritic staging helper name in Task 4 Step 1 and the `app.js` state names in Task 8 Step 3 — both are `grep` instructions with the exact command.
