# Power Search — Plan A: credits enrichment (the data layer)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every film its TMDB cast, crew, characters, keywords, overview and tagline, stored as rows and indexed for exact and misspelling-tolerant lookup, behind one resumable dry-run-by-default verb — so that Plan B (the search bar) has something to search.

**Architecture:** Migration 018 adds `person`, `film_credit`, `film_keyword`, `film_text` and three FTS5 tables kept in step by triggers. `TmdbClient.movie_credits` fetches everything for one film in one call. `Repository.write_credits` replaces one film's rows inside one transaction. `application/enrich.py::enrich_credits` walks the worklist with the same pacing / abort / resume-by-stamp shape as `cheapcharts resolve`. Nothing here touches identity, matching, `sync`, or the dashboard.

**Tech Stack:** Python 3.12, SQLite ≥ 3.50 (stdlib `sqlite3`, FTS5 with the `trigram` tokenizer — verified present), `requests`, Typer, pytest + pytest-bdd + `responses`. No new runtime dependency.

**Spec:** `docs/superpowers/specs/2026-09-06-power-search-design.md` (§4–§6, §10–§11, D1–D4, D9–D12). Plan B (parser, resolution, `/api/search`, the bar — spec §7–§9) is a separate plan written after this one has run live, because §7.2's crew-job sets are verified against the enriched vocabulary.

## Global Constraints

- **No new runtime dependency.** `pyproject.toml` dependencies stay `typer`, `rich`, `flask`, `requests`.
- **Schema change = a new numbered migration** that inserts its own `schema_version` row, wrapped in `BEGIN/COMMIT`; never edit an applied migration; `movie-brain migrate --apply` is the only path that advances an existing DB (CLAUDE.md).
- **`person` is not an identity.** `tmdb_person_id` is NOT added to `KEY_AUTHORITIES`; nothing here touches `key_film`, the thumbprint resolver, `films.guid` or matching (spec §13).
- **Every film read model carries the `_NOT_DISPOSED` guard**; the worklist here uses it and `_IS_MOVIE` exactly as `films_needing_imdb_backfill` does.
- **Collectors never delete films.** `write_credits` replaces a film's *credit* rows; it never touches `films`.
- **Enrichment is never run by `sync`** (spec §5; memory: syncs are manual by choice).
- **`merge_film` must move every film-scoped table** — `film_credit`, `film_keyword`, `film_text` join `claim` and `film_list_entry` in that method (spec §4).
- **Dry run writes nothing.** `enrich credits` without `--apply` makes the TMDB calls and logs what it would write, and the database is byte-identical afterwards.
- **Markdown prose is never hard-wrapped** (owner's global rule) — applies to the doc edits in Task 7.
- **Commit messages:** one line, the *why*, plus the attribution trailer already used on this branch.
- Work on a branch: `feature/power-search-a-credits` off `main`.

---

## File structure

| File | Responsibility |
|---|---|
| `migrations/018_credits.sql` *(new)* | The four tables, three FTS5 indexes, six triggers, four `tmdb_facts` columns |
| `src/movie_brain/domain/models.py` | `CastRow`, `CrewRow`, `TmdbCredits`, `CreditsTarget` — pure data |
| `src/movie_brain/domain/search.py` *(new)* | `trigram_query(text)` — the one pure helper Plan B's resolver and this plan's index test share |
| `src/movie_brain/infrastructure/tmdb.py` | `TmdbClient.movie_credits(tmdb_id) -> TmdbCredits` — one call, `append_to_response=credits,keywords` |
| `src/movie_brain/infrastructure/database.py` | `films_needing_credits`, `write_credits`, `credits_for`, `keywords_for`, `credits_summary`, the `merge_film` moves |
| `src/movie_brain/application/enrich.py` *(new)* | `enrich_credits(...) -> EnrichReport` — the verb's logic |
| `src/movie_brain/cli.py` | `enrich` Typer group, `credits` command; `status` gains a `credits` row |
| `tests/unit/test_database.py`, `tests/unit/test_tmdb.py`, `tests/unit/test_search.py` *(new)*, `tests/unit/test_cli.py` | Unit coverage per layer |
| `tests/features/enrich.feature` + `tests/step_defs/test_enrich.py` *(new)* | The verb's scenarios with a fake TMDB |
| `CLAUDE.md`, `docs/backlog.md`, the spec | Task 7 doc edits |

---

### Task 1: Migration 018 — tables, FTS5 indexes, triggers

**Files:**
- Create: `migrations/018_credits.sql`
- Test: `tests/unit/test_database.py`

**Interfaces:**
- Produces: tables `person(id, tmdb_person_id, name, first_seen)`, `film_credit(rowid, film_id, person_id, kind, job, department, character, ord)`, `film_keyword(film_id, keyword)`, `film_text(film_id, title, overview, plot)`; FTS5 `person_fts(name)` keyed on `person.id`, `character_fts(character)` keyed on `film_credit.rowid`, `film_text_fts(title, overview, plot)` keyed on `film_text.film_id`; columns `tmdb_facts.overview`, `.tagline`, `.genres`, `.credits_fetched_on`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_database.py`:

```python
def test_migration_018_creates_credit_tables_and_trigram_indexes(repo):
    """A fresh repo bootstraps 018. The FTS indexes are external-content tables kept in step
    by triggers, so a plain INSERT into the base table must be enough to make a row findable;
    and the trigram tokenizer must be present, or Plan B's misspelling correction is dead."""
    with sqlite3.connect(repo.db_path) as c:
        names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type IN ('table','trigger')")}
        assert {"person", "film_credit", "film_keyword", "film_text", "person_fts", "character_fts", "film_text_fts"} <= names
        assert {"person_ai", "film_credit_ai", "film_credit_ad", "film_text_ai", "film_text_ad", "film_text_au"} <= names
        cols = {r[1] for r in c.execute("PRAGMA table_info(tmdb_facts)")}
        assert {"overview", "tagline", "genres", "credits_fetched_on"} <= cols
        assert c.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] >= 18

        c.execute("INSERT INTO person (tmdb_person_id, name, first_seen) VALUES (4110, 'Humphrey Bogart', '2026-09-06')")
        # trigram phrase MATCH is a substring test — 'Bogart' is found by its middle
        assert c.execute("SELECT rowid FROM person_fts WHERE person_fts MATCH '\"ogar\"'").fetchall() == [(1,)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_database.py -k migration_018 -q`
Expected: FAIL — `assert {'person', ...} <= names` (the tables do not exist).

- [ ] **Step 3: Write the migration**

Create `migrations/018_credits.sql`:

```sql
-- Power search, Plan A (design docs/superpowers/specs/2026-09-06-power-search-design.md §4, D3).
-- Cast, crew, characters and keywords from TMDB, stored as ROWS rather than a payload, because
-- the owner's spelling requirement needs ~60k names to be trigram-indexable: a misspelled
-- name is corrected against `person_fts` BEFORE the query runs, which a JSON blob forecloses.
-- `person` is NOT an identity (no guid, not a KEY_AUTHORITY); `tmdb_person_id` is the join.
-- `job`/`department`/`character` are NOT NULL DEFAULT '' so the UNIQUE actually dedups —
-- SQLite treats two NULLs as distinct in a unique index.
-- The three FTS5 tables are external-content indexes kept in step by triggers; the base
-- tables are the truth and the indexes can be rebuilt with INSERT INTO x(x) VALUES('rebuild').
-- `film_text` exists only because its columns come from three sources (films, tmdb_facts,
-- the OMDb payload) and an external-content FTS index needs ONE content table.
BEGIN;

CREATE TABLE person (
    id              INTEGER PRIMARY KEY,
    tmdb_person_id  INTEGER NOT NULL UNIQUE,
    name            TEXT    NOT NULL,
    first_seen      TEXT    NOT NULL
);

CREATE TABLE film_credit (
    film_id     INTEGER NOT NULL REFERENCES films(id),
    person_id   INTEGER NOT NULL REFERENCES person(id),
    kind        TEXT    NOT NULL CHECK (kind IN ('cast', 'crew')),
    job         TEXT    NOT NULL DEFAULT '',
    department  TEXT    NOT NULL DEFAULT '',
    character   TEXT    NOT NULL DEFAULT '',
    ord         INTEGER NOT NULL,
    UNIQUE (film_id, person_id, kind, job, character)
);
CREATE INDEX film_credit_person ON film_credit(person_id);
CREATE INDEX film_credit_film   ON film_credit(film_id);

CREATE TABLE film_keyword (
    film_id  INTEGER NOT NULL REFERENCES films(id),
    keyword  TEXT    NOT NULL,
    PRIMARY KEY (film_id, keyword)
);

CREATE TABLE film_text (
    film_id   INTEGER PRIMARY KEY REFERENCES films(id),
    title     TEXT NOT NULL,
    overview  TEXT,
    plot      TEXT
);

ALTER TABLE tmdb_facts ADD COLUMN overview           TEXT;
ALTER TABLE tmdb_facts ADD COLUMN tagline            TEXT;
ALTER TABLE tmdb_facts ADD COLUMN genres             TEXT;
ALTER TABLE tmdb_facts ADD COLUMN credits_fetched_on TEXT;

CREATE VIRTUAL TABLE person_fts    USING fts5(name,      content='person',      content_rowid='id',      tokenize='trigram');
CREATE VIRTUAL TABLE character_fts USING fts5(character, content='film_credit', content_rowid='rowid',   tokenize='trigram');
CREATE VIRTUAL TABLE film_text_fts USING fts5(title, overview, plot, content='film_text', content_rowid='film_id', tokenize='unicode61');

CREATE TRIGGER person_ai AFTER INSERT ON person BEGIN
    INSERT INTO person_fts(rowid, name) VALUES (new.id, new.name);
END;
CREATE TRIGGER film_credit_ai AFTER INSERT ON film_credit BEGIN
    INSERT INTO character_fts(rowid, character) VALUES (new.rowid, new.character);
END;
CREATE TRIGGER film_credit_ad AFTER DELETE ON film_credit BEGIN
    INSERT INTO character_fts(character_fts, rowid, character) VALUES ('delete', old.rowid, old.character);
END;
CREATE TRIGGER film_text_ai AFTER INSERT ON film_text BEGIN
    INSERT INTO film_text_fts(rowid, title, overview, plot) VALUES (new.film_id, new.title, new.overview, new.plot);
END;
CREATE TRIGGER film_text_ad AFTER DELETE ON film_text BEGIN
    INSERT INTO film_text_fts(film_text_fts, rowid, title, overview, plot) VALUES ('delete', old.film_id, old.title, old.overview, old.plot);
END;
CREATE TRIGGER film_text_au AFTER UPDATE ON film_text BEGIN
    INSERT INTO film_text_fts(film_text_fts, rowid, title, overview, plot) VALUES ('delete', old.film_id, old.title, old.overview, old.plot);
    INSERT INTO film_text_fts(rowid, title, overview, plot) VALUES (new.film_id, new.title, new.overview, new.plot);
END;

INSERT INTO schema_version (version) VALUES (18);
COMMIT;
```

- [ ] **Step 4: Run test to verify it passes, and the whole suite still passes**

Run: `uv run pytest tests/unit/test_database.py -k migration_018 -q` → PASS.
Run: `uv run pytest -q` → all pass (the migration runs on every fresh test repo, so any breakage shows here).

- [ ] **Step 5: Commit**

```bash
git checkout -b feature/power-search-a-credits
git add migrations/018_credits.sql tests/unit/test_database.py
git commit -m "a misspelled name can only be corrected against names stored as rows, so the credits get tables"
```

---

### Task 2: Domain models + `trigram_query`

**Files:**
- Modify: `src/movie_brain/domain/models.py` (append after `ItunesTarget`)
- Create: `src/movie_brain/domain/search.py`
- Test: `tests/unit/test_search.py` *(new)*, `tests/unit/test_models.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class CastRow:    person_id: int; name: str; character: str; order: int          # person_id = TMDB person id
@dataclass(frozen=True)
class CrewRow:    person_id: int; name: str; job: str; department: str
@dataclass(frozen=True)
class TmdbCredits:
    tmdb_id: int; imdb_id: str | None; title: str; original_title: str; year: int | None; runtime_min: int | None
    overview: str | None; tagline: str | None; genres: tuple[str, ...]; keywords: tuple[str, ...]
    cast: tuple[CastRow, ...]; crew: tuple[CrewRow, ...]
@dataclass(frozen=True)
class CreditsTarget: film_id: int; title: str; tmdb_id: int
def trigram_query(text: str) -> str   # 'bogrt' -> '"bog" OR "ogr" OR "grt"'; '' for text shorter than 3 chars
```

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_search.py`:

```python
from movie_brain.domain.search import trigram_query


def test_trigram_query_ors_every_window_of_three_lowercased():
    assert trigram_query("Bogrt") == '"bog" OR "ogr" OR "grt"'


def test_trigram_query_is_empty_below_three_characters():
    """FTS5's trigram tokenizer cannot match a term shorter than three characters,
    so a caller must treat '' as 'nothing to look up', never send it as MATCH."""
    assert trigram_query("bo") == ""
    assert trigram_query("") == ""


def test_trigram_query_escapes_embedded_double_quotes():
    """Each window is a double-quoted FTS5 string, and FTS5 escapes a quote by doubling it.
    'a"bc' has two windows: a"b and "bc."""
    expected = '"a""b" OR """bc"'
    assert trigram_query('a"bc') == expected
```

Append to `tests/unit/test_models.py`:

```python
from movie_brain.domain.models import CastRow, CreditsTarget, CrewRow, TmdbCredits


def test_tmdb_credits_is_frozen_and_carries_rows_as_tuples():
    credits = TmdbCredits(
        tmdb_id=910, imdb_id="tt0038355", title="The Big Sleep", original_title="The Big Sleep",
        year=1946, runtime_min=114, overview="Private Investigator Philip Marlowe…", tagline="The picture they were born for!",
        genres=("Mystery", "Crime"), keywords=("film noir", "private investigator"),
        cast=(CastRow(4110, "Humphrey Bogart", "Philip Marlowe", 0),),
        crew=(CrewRow(2636, "Howard Hawks", "Director", "Directing"),),
    )
    assert credits.cast[0].character == "Philip Marlowe"
    assert CreditsTarget(1, "The Big Sleep", 910).tmdb_id == 910
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_search.py tests/unit/test_models.py -q`
Expected: FAIL — `ModuleNotFoundError: movie_brain.domain.search` and `ImportError: cannot import name 'CastRow'`.

- [ ] **Step 3: Write the models and the helper**

Append to `src/movie_brain/domain/models.py`, directly after `class ItunesTarget`:

```python
@dataclass(frozen=True)
class CastRow:
    """One TMDB cast credit. `person_id` is TMDB's person id — the join to `person.tmdb_person_id`."""

    person_id: int
    name: str
    character: str
    order: int


@dataclass(frozen=True)
class CrewRow:
    person_id: int
    name: str
    job: str
    department: str


@dataclass(frozen=True)
class TmdbCredits:
    """Everything `TmdbClient.movie_credits` brings back in ONE call (spec D11): the movie
    body's title/year/runtime (so `tmdb_facts` can be upserted for a film that has no row
    yet), plus credits and keywords."""

    tmdb_id: int
    imdb_id: str | None
    title: str
    original_title: str
    year: int | None
    runtime_min: int | None
    overview: str | None
    tagline: str | None
    genres: tuple[str, ...]
    keywords: tuple[str, ...]
    cast: tuple[CastRow, ...]
    crew: tuple[CrewRow, ...]


@dataclass(frozen=True)
class CreditsTarget:
    """A live movie holding a TMDB id and no `credits_fetched_on` — the enrichment worklist."""

    film_id: int
    title: str
    tmdb_id: int
```

Create `src/movie_brain/domain/search.py`:

```python
"""Pure search helpers — no SQL, no I/O. Plan B's parser and resolver grow here.

`trigram_query` is the one thing Plan A needs: the FTS5 `trigram` tokenizer makes a bare
MATCH a SUBSTRING test ('bogrt' finds nothing), so misspelling tolerance is an OR of the
query's own trigrams — every name sharing at least one window comes back as a candidate,
and the resolver ranks those candidates. Verified against the stdlib sqlite3 2026-09-06.
"""

from __future__ import annotations


def trigram_query(text: str) -> str:
    """'Bogrt' → '"bog" OR "ogr" OR "grt"'. Empty when the text has no 3-character window —
    the tokenizer cannot match shorter terms, so the caller must not send MATCH at all."""
    s = text.lower()
    windows = [s[i : i + 3] for i in range(len(s) - 2)]
    return " OR ".join('"' + w.replace('"', '""') + '"' for w in windows)
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/unit/test_search.py tests/unit/test_models.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/domain/models.py src/movie_brain/domain/search.py tests/unit/test_search.py tests/unit/test_models.py
git commit -m "a trigram index answers substrings, not misspellings, so the fuzzy query has to be an OR of windows"
```

---

### Task 3: `TmdbClient.movie_credits`

**Files:**
- Modify: `src/movie_brain/infrastructure/tmdb.py` (add after `movie_facts`, ~line 180)
- Test: `tests/unit/test_tmdb.py`

**Interfaces:**
- Consumes: `TmdbCredits`, `CastRow`, `CrewRow` (Task 2); `TmdbClient._get` (exists).
- Produces: `TmdbClient.movie_credits(self, tmdb_id: int) -> TmdbCredits`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_tmdb.py` (it already imports `responses`, `TMDB_API`, `TmdbClient`; add `from movie_brain.domain.models import CastRow, CrewRow` at the top):

```python
BIG_SLEEP_CREDITS = {
    "id": 910, "imdb_id": "tt0038355", "title": "The Big Sleep", "original_title": "The Big Sleep",
    "release_date": "1946-08-22", "runtime": 114,
    "overview": "Private Investigator Philip Marlowe is hired…", "tagline": "The picture they were born for!",
    "genres": [{"id": 9648, "name": "Mystery"}, {"id": 80, "name": "Crime"}],
    "credits": {
        "cast": [
            {"id": 4110, "name": "Humphrey Bogart", "character": "Philip Marlowe", "order": 0},
            {"id": 3092, "name": "Lauren Bacall", "character": "Vivian Sternwood Rutledge", "order": 1},
            {"id": 9999, "name": "Uncredited Extra", "character": None, "order": 40},
        ],
        "crew": [
            {"id": 2636, "name": "Howard Hawks", "job": "Director", "department": "Directing"},
            {"id": 2637, "name": "William Faulkner", "job": "Screenplay", "department": "Writing"},
        ],
    },
    "keywords": {"keywords": [{"id": 1, "name": "film noir"}, {"id": 2, "name": "private investigator"}]},
}


@responses.activate
def test_movie_credits_reads_cast_crew_keywords_and_body_in_one_call():
    responses.get(f"{TMDB_API}/movie/910", json=BIG_SLEEP_CREDITS)
    c = TmdbClient("tok").movie_credits(910)
    assert responses.calls[0].request.params["append_to_response"] == "credits,keywords"
    assert (c.tmdb_id, c.imdb_id, c.title, c.year, c.runtime_min) == (910, "tt0038355", "The Big Sleep", 1946, 114)
    assert c.genres == ("Mystery", "Crime") and c.keywords == ("film noir", "private investigator")
    assert c.cast[0] == CastRow(4110, "Humphrey Bogart", "Philip Marlowe", 0)
    assert c.cast[2].character == ""  # a null character becomes '' — the column is NOT NULL DEFAULT ''
    assert c.crew[1] == CrewRow(2637, "William Faulkner", "Screenplay", "Writing")
    assert c.overview.startswith("Private Investigator") and c.tagline.startswith("The picture")


@responses.activate
def test_movie_credits_tolerates_a_film_with_no_credits_or_keywords_blocks():
    responses.get(f"{TMDB_API}/movie/1", json={"id": 1, "title": "Bare", "original_title": "Bare", "release_date": "", "genres": []})
    c = TmdbClient("tok").movie_credits(1)
    assert (c.year, c.runtime_min, c.overview, c.tagline) == (None, None, None, None)
    assert c.cast == () and c.crew == () and c.keywords == () and c.genres == ()
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_tmdb.py -k movie_credits -q`
Expected: FAIL — `AttributeError: 'TmdbClient' object has no attribute 'movie_credits'`.

- [ ] **Step 3: Implement**

In `src/movie_brain/infrastructure/tmdb.py`, extend the models import to include `CastRow, CrewRow, TmdbCredits`, and add after `movie_facts`:

```python
    def movie_credits(self, tmdb_id: int) -> TmdbCredits:
        """Cast, crew, keywords and the movie body in ONE call (spec D11). Nulls from TMDB
        become '' for the three credit text columns, which are NOT NULL DEFAULT '' so the
        UNIQUE constraint on `film_credit` actually dedups."""
        d = self._get(f"/movie/{tmdb_id}", append_to_response="credits,keywords").json()
        rd = d.get("release_date") or ""
        year = int(rd[:4]) if len(rd) >= 4 and rd[:4].isdigit() else None
        runtime = d.get("runtime")
        credits = d.get("credits") or {}
        cast = tuple(
            CastRow(int(r["id"]), str(r.get("name") or ""), str(r.get("character") or ""), int(r.get("order") or 0))
            for r in credits.get("cast") or []
            if r.get("id") is not None
        )
        crew = tuple(
            CrewRow(int(r["id"]), str(r.get("name") or ""), str(r.get("job") or ""), str(r.get("department") or ""))
            for r in credits.get("crew") or []
            if r.get("id") is not None
        )
        return TmdbCredits(
            tmdb_id=int(d.get("id") or tmdb_id),
            imdb_id=str(d["imdb_id"]) if d.get("imdb_id") else None,
            title=d.get("title") or "",
            original_title=d.get("original_title") or "",
            year=year,
            runtime_min=int(runtime) if isinstance(runtime, int) and runtime > 0 else None,
            overview=(d.get("overview") or "").strip() or None,
            tagline=(d.get("tagline") or "").strip() or None,
            genres=tuple(str(g["name"]) for g in d.get("genres") or [] if g.get("name")),
            keywords=tuple(str(k["name"]) for k in (d.get("keywords") or {}).get("keywords") or [] if k.get("name")),
            cast=cast,
            crew=crew,
        )
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/unit/test_tmdb.py -q` → PASS (all, not just the new ones).

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/infrastructure/tmdb.py tests/unit/test_tmdb.py
git commit -m "one TMDB call carries cast, crew, keywords and the body, so the client asks once"
```

---

### Task 4: Repository — worklist, `write_credits`, readers, summary

**Files:**
- Modify: `src/movie_brain/infrastructure/database.py` — add a `# credits` section after `films_needing_itunes_id`; import `CreditsTarget, TmdbCredits` from models.
- Test: `tests/unit/test_database.py`

**Interfaces:**
- Consumes: Task 1 tables; `TmdbCredits` etc. (Task 2); `trigram_query` (Task 2).
- Produces:

```python
def films_needing_credits(self, limit: int | None = None) -> list[CreditsTarget]
def write_credits(self, film_id: int, credits: TmdbCredits, today: date) -> None   # one transaction; replaces the film's rows
def credits_for(self, film_id: int) -> list[tuple[str, str, str, str]]            # (kind, name, character, job) ordered cast by ord then crew by ord
def keywords_for(self, film_id: int) -> list[str]
def credits_summary(self) -> dict[str, int]                                       # {"films_with_credits": n, "films_with_tmdb": n, "persons": n}
```

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_database.py` (the file already imports `sqlite3`, `date`, `Film`; add `from movie_brain.domain.models import CastRow, CrewRow, TmdbCredits` and `from movie_brain.domain.search import trigram_query`):

```python
def _credits(**over):
    base = dict(
        tmdb_id=910, imdb_id="tt0038355", title="The Big Sleep", original_title="The Big Sleep", year=1946, runtime_min=114,
        overview="Private Investigator Philip Marlowe is hired by General Sternwood.", tagline="The picture they were born for!",
        genres=("Mystery", "Crime"), keywords=("film noir", "private investigator"),
        cast=(CastRow(4110, "Humphrey Bogart", "Philip Marlowe", 0), CastRow(3092, "Lauren Bacall", "Vivian Sternwood Rutledge", 1)),
        crew=(CrewRow(2636, "Howard Hawks", "Director", "Directing"), CrewRow(4110, "Humphrey Bogart", "Producer", "Production")),
    )
    base.update(over)
    return TmdbCredits(**base)


def test_write_credits_stores_persons_once_and_rows_per_credit(repo):
    day = date(2026, 9, 6)
    fid = repo.create_film(Film("The Big Sleep", 1946, "Howard Hawks", ""))
    repo.set_external_id(fid, "tmdb", "910", day)
    repo.upsert_omdb(fid, OmdbRating(8.0, 97, True, "English", '{"Plot": "A private eye takes a case."}'), day)

    repo.write_credits(fid, _credits(), day)

    assert repo.credits_for(fid) == [
        ("cast", "Humphrey Bogart", "Philip Marlowe", ""),
        ("cast", "Lauren Bacall", "Vivian Sternwood Rutledge", ""),
        ("crew", "Howard Hawks", "", "Director"),
        ("crew", "Humphrey Bogart", "", "Producer"),
    ]
    assert repo.keywords_for(fid) == ["film noir", "private investigator"]
    with sqlite3.connect(repo.db_path) as c:
        # Bogart acts AND produces: one person row, two credit rows
        assert c.execute("SELECT COUNT(*) FROM person WHERE tmdb_person_id = 4110").fetchone()[0] == 1
        row = c.execute("SELECT overview, tagline, genres, credits_fetched_on, title FROM tmdb_facts WHERE film_id = ?", (fid,)).fetchone()
        assert row == (_credits().overview, _credits().tagline, '["Mystery", "Crime"]', "2026-09-06", "The Big Sleep")
        assert c.execute("SELECT plot FROM film_text WHERE film_id = ?", (fid,)).fetchone() == ("A private eye takes a case.",)


def test_write_credits_replaces_a_films_rows_and_never_duplicates(repo):
    day = date(2026, 9, 6)
    fid = repo.create_film(Film("The Big Sleep", 1946, None, ""))
    repo.set_external_id(fid, "tmdb", "910", day)
    repo.write_credits(fid, _credits(), day)
    repo.write_credits(fid, _credits(cast=(CastRow(4110, "Humphrey Bogart", "Philip Marlowe", 0),), keywords=("film noir",)), day)
    assert [r[1] for r in repo.credits_for(fid) if r[0] == "cast"] == ["Humphrey Bogart"]
    assert repo.keywords_for(fid) == ["film noir"]


def test_write_credits_indexes_names_and_characters_for_misspellings(repo):
    """The trigram indexes are what Plan B corrects against. A bare MATCH is a substring
    test, so the misspelling is asked as an OR of its trigrams (domain/search.py)."""
    day = date(2026, 9, 6)
    fid = repo.create_film(Film("The Big Sleep", 1946, None, ""))
    repo.set_external_id(fid, "tmdb", "910", day)
    repo.write_credits(fid, _credits(), day)
    with sqlite3.connect(repo.db_path) as c:
        people = {r[0] for r in c.execute("SELECT name FROM person_fts WHERE person_fts MATCH ?", (trigram_query("bogrt"),))}
        assert "Humphrey Bogart" in people
        chars = {r[0] for r in c.execute("SELECT character FROM character_fts WHERE character_fts MATCH ?", (trigram_query("marlow"),))}
        assert chars == {"Philip Marlowe"}
        assert c.execute("SELECT rowid FROM film_text_fts WHERE film_text_fts MATCH 'sternwood'").fetchall() == [(fid,)]


def test_films_needing_credits_lists_live_movies_with_a_tmdb_id_and_no_stamp(repo):
    day = date(2026, 9, 6)
    a = repo.create_film(Film("A", 1950, None, ""))
    b = repo.create_film(Film("B", 1951, None, ""))
    c_ = repo.create_film(Film("C", 1952, None, ""))
    repo.set_external_id(a, "tmdb", "1", day)
    repo.set_external_id(b, "tmdb", "2", day)
    repo.write_credits(b, _credits(tmdb_id=2, title="B", original_title="B"), day)  # stamped
    targets = repo.films_needing_credits()
    assert [(t.film_id, t.title, t.tmdb_id) for t in targets] == [(a, "A", 1)]
    assert repo.films_needing_credits(limit=0) == []
    assert repo.credits_summary() == {"films_with_credits": 1, "films_with_tmdb": 2, "persons": 3}
    assert c_ not in {t.film_id for t in targets}  # no tmdb id → not on the worklist
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_database.py -k "write_credits or films_needing_credits" -q`
Expected: FAIL — `AttributeError: 'Repository' object has no attribute 'write_credits'`.

- [ ] **Step 3: Implement**

In `src/movie_brain/infrastructure/database.py`, extend the `movie_brain.domain.models` import with `CreditsTarget, TmdbCredits`, and add after `films_needing_itunes_id`:

```python
    # credits (power search, Plan A) -----------------------------------------
    def films_needing_credits(self, limit: int | None = None) -> list[CreditsTarget]:
        """Live movies holding a TMDB id and no `credits_fetched_on`. The stamp is what makes
        the enrichment resumable — a stamped film is never re-fetched by this worklist."""
        sql = (
            "SELECT f.id, f.title, x.value AS tmdb_id FROM films f "
            "JOIN external_ids x ON x.film_id = f.id AND x.authority = 'tmdb' "
            "LEFT JOIN tmdb_facts t ON t.film_id = f.id "
            "WHERE t.credits_fetched_on IS NULL AND " + _NOT_DISPOSED + _IS_MOVIE + " ORDER BY f.id"
        )
        if limit is not None:
            sql += " LIMIT ?"
        with self._conn() as c:
            rows = c.execute(sql, (limit,) if limit is not None else ()).fetchall()
        return [CreditsTarget(int(r["id"]), str(r["title"]), int(r["tmdb_id"])) for r in rows]

    def write_credits(self, film_id: int, credits: TmdbCredits, today: date) -> None:
        """Replace ONE film's credit, keyword and text rows and stamp `tmdb_facts`, in one
        transaction. Persons are inserted once by `tmdb_person_id` and never updated. The
        FTS indexes follow through migration 018's triggers — nothing here touches them."""
        with self._conn() as c:
            c.execute(
                "INSERT INTO tmdb_facts (film_id, tmdb_id, imdb_id, title, original_title, alt_titles, "
                "release_year, runtime_min, fetched_on) VALUES (?, ?, ?, ?, ?, '[]', ?, ?, ?) "
                "ON CONFLICT(film_id) DO NOTHING",
                (film_id, credits.tmdb_id, credits.imdb_id, credits.title, credits.original_title,
                 credits.year, credits.runtime_min, today.isoformat()),
            )
            c.execute(
                "UPDATE tmdb_facts SET overview = ?, tagline = ?, genres = ?, credits_fetched_on = ? WHERE film_id = ?",
                (credits.overview, credits.tagline, json.dumps(list(credits.genres)), today.isoformat(), film_id),
            )
            people = {r.person_id: r.name for r in credits.cast} | {r.person_id: r.name for r in credits.crew}
            c.executemany(
                "INSERT INTO person (tmdb_person_id, name, first_seen) VALUES (?, ?, ?) ON CONFLICT(tmdb_person_id) DO NOTHING",
                [(pid, name, today.isoformat()) for pid, name in people.items()],
            )
            ids = {
                int(r["tmdb_person_id"]): int(r["id"])
                for r in c.execute(
                    f"SELECT id, tmdb_person_id FROM person WHERE tmdb_person_id IN ({','.join('?' * len(people))})",
                    list(people),
                ).fetchall()
            } if people else {}
            c.execute("DELETE FROM film_credit WHERE film_id = ?", (film_id,))
            c.execute("DELETE FROM film_keyword WHERE film_id = ?", (film_id,))
            c.executemany(
                "INSERT OR IGNORE INTO film_credit (film_id, person_id, kind, job, department, character, ord) "
                "VALUES (?, ?, 'cast', '', '', ?, ?)",
                [(film_id, ids[r.person_id], r.character, r.order) for r in credits.cast],
            )
            c.executemany(
                "INSERT OR IGNORE INTO film_credit (film_id, person_id, kind, job, department, character, ord) "
                "VALUES (?, ?, 'crew', ?, ?, '', ?)",
                [(film_id, ids[r.person_id], r.job, r.department, i) for i, r in enumerate(credits.crew)],
            )
            c.executemany(
                "INSERT OR IGNORE INTO film_keyword (film_id, keyword) VALUES (?, ?)",
                [(film_id, k) for k in credits.keywords],
            )
            plot_row = c.execute(
                "SELECT NULLIF(json_extract(payload, '$.Plot'), 'N/A') FROM omdb WHERE film_id = ?", (film_id,)
            ).fetchone()
            title_row = c.execute("SELECT title FROM films WHERE id = ?", (film_id,)).fetchone()
            c.execute(
                "INSERT INTO film_text (film_id, title, overview, plot) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(film_id) DO UPDATE SET title = excluded.title, overview = excluded.overview, plot = excluded.plot",
                (film_id, str(title_row["title"]), credits.overview, plot_row[0] if plot_row else None),
            )

    def credits_for(self, film_id: int) -> list[tuple[str, str, str, str]]:
        """(kind, name, character, job) — cast first by billing order, then crew in TMDB's order."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT fc.kind, p.name, fc.character, fc.job FROM film_credit fc JOIN person p ON p.id = fc.person_id "
                "WHERE fc.film_id = ? ORDER BY fc.kind, fc.ord, p.name",
                (film_id,),
            ).fetchall()
            return [(str(r["kind"]), str(r["name"]), str(r["character"]), str(r["job"])) for r in rows]

    def keywords_for(self, film_id: int) -> list[str]:
        with self._conn() as c:
            rows = c.execute("SELECT keyword FROM film_keyword WHERE film_id = ? ORDER BY keyword", (film_id,)).fetchall()
            return [str(r["keyword"]) for r in rows]

    def credits_summary(self) -> dict[str, int]:
        with self._conn() as c:
            with_credits = c.execute("SELECT COUNT(*) FROM tmdb_facts WHERE credits_fetched_on IS NOT NULL").fetchone()[0]
            with_tmdb = c.execute("SELECT COUNT(*) FROM external_ids WHERE authority = 'tmdb'").fetchone()[0]
            persons = c.execute("SELECT COUNT(*) FROM person").fetchone()[0]
            return {"films_with_credits": int(with_credits), "films_with_tmdb": int(with_tmdb), "persons": int(persons)}
```

Note `ORDER BY fc.kind` sorts `cast` before `crew` alphabetically — that is the order the test asserts.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/unit/test_database.py -k "write_credits or films_needing_credits or migration_018" -q` → PASS.
Run: `uv run mypy` → clean (the dict-merge on `people` and the conditional `ids` need the types shown).

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/infrastructure/database.py tests/unit/test_database.py
git commit -m "a film's credits are replaced whole, in one transaction, so a re-fetch can never leave a half-updated cast"
```

---

### Task 5: `merge_film` moves credit, keyword and text rows

**Files:**
- Modify: `src/movie_brain/infrastructure/database.py::merge_film` (after the `film_list_entry` move, ~line 1976)
- Test: `tests/unit/test_database.py`

**Interfaces:**
- Consumes: Task 4's `write_credits`, `credits_for`, `keywords_for`.
- Produces: `MergeReport.moved` gains keys `film_credit`, `film_keyword`, `film_text` when rows moved.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_database.py`:

```python
def test_merge_moves_credits_keywords_and_text_to_the_survivor(repo):
    a, b = _two_films(repo)
    repo.set_external_id(b, "tmdb", "910", D)
    repo.write_credits(b, _credits(), D)

    report = repo.merge_film(b, a, D, note="twin")

    assert [r[1] for r in repo.credits_for(a)] == ["Humphrey Bogart", "Lauren Bacall", "Howard Hawks", "Humphrey Bogart"]
    assert repo.credits_for(b) == [] and repo.keywords_for(b) == []
    assert repo.keywords_for(a) == ["film noir", "private investigator"]
    assert report.moved["film_credit"] == 4 and report.moved["film_keyword"] == 2 and report.moved["film_text"] == 1
    with sqlite3.connect(repo.db_path) as c:
        assert c.execute("SELECT rowid FROM film_text_fts WHERE film_text_fts MATCH 'sternwood'").fetchall() == [(a,)]


def test_merge_keeps_the_survivors_credits_when_both_films_have_them(repo):
    a, b = _two_films(repo)
    repo.set_external_id(a, "tmdb", "1", D)
    repo.set_external_id(b, "tmdb", "910", D)
    repo.write_credits(a, _credits(tmdb_id=1, cast=(CastRow(1, "Alpha Actor", "Lead", 0),), crew=(), keywords=("kept",)), D)
    repo.write_credits(b, _credits(), D)

    report = repo.merge_film(b, a, D, note="twin")

    assert [r[1] for r in repo.credits_for(a)] == ["Alpha Actor"]  # survivor wins; loser's rows dropped
    assert repo.keywords_for(a) == ["kept"]
    assert report.dropped["film_credit"] == 4 and report.dropped["film_keyword"] == 2 and report.dropped["film_text"] == 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_database.py -k "merge_moves_credits or merge_keeps_the_survivors_credits" -q`
Expected: FAIL — `KeyError: 'film_credit'` on `report.moved`.

- [ ] **Step 3: Implement**

In `merge_film`, directly after the `film_list_entry` block (`if n_list_entries: moved["film_list_entry"] = n_list_entries`), add:

```python
            # Credits follow the survivor-wins rule the one-row tables use: a survivor that
            # already carries credits keeps them and the loser's are dropped; otherwise the
            # loser's rows move. `film_text` moves through DELETE+INSERT rather than UPDATE
            # so migration 018's triggers re-key the FTS row (an UPDATE of the rowid alone
            # would leave the index pointing at the loser).
            survivor_has_credits = c.execute(
                "SELECT 1 FROM film_credit WHERE film_id = ? LIMIT 1", (survivor_id,)
            ).fetchone() is not None
            for table in ("film_credit", "film_keyword"):
                n_loser = c.execute(f"SELECT COUNT(*) FROM {table} WHERE film_id = ?", (loser_id,)).fetchone()[0]
                if not n_loser:
                    continue
                if survivor_has_credits:
                    c.execute(f"DELETE FROM {table} WHERE film_id = ?", (loser_id,))
                    dropped[table] = int(n_loser)
                else:
                    c.execute(f"UPDATE {table} SET film_id = ? WHERE film_id = ?", (survivor_id, loser_id))
                    moved[table] = int(n_loser)
            loser_text = c.execute("SELECT title, overview, plot FROM film_text WHERE film_id = ?", (loser_id,)).fetchone()
            if loser_text is not None:
                c.execute("DELETE FROM film_text WHERE film_id = ?", (loser_id,))
                if survivor_has_credits:
                    dropped["film_text"] = 1
                else:
                    c.execute(
                        "INSERT INTO film_text (film_id, title, overview, plot) VALUES (?, ?, ?, ?) "
                        "ON CONFLICT(film_id) DO UPDATE SET overview = excluded.overview, plot = excluded.plot",
                        (survivor_id, loser_text["title"], loser_text["overview"], loser_text["plot"]),
                    )
                    moved["film_text"] = 1
            if survivor_has_credits:
                c.execute(
                    "UPDATE tmdb_facts SET credits_fetched_on = NULL WHERE film_id = ? AND credits_fetched_on IS NOT NULL", (loser_id,)
                )
```

- [ ] **Step 4: Run to verify they pass, plus every existing merge test**

Run: `uv run pytest tests/unit/test_database.py -k merge -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/infrastructure/database.py tests/unit/test_database.py
git commit -m "a merged-away film's cast belongs to its survivor, like every other row it owned"
```

---

### Task 6: `enrich_credits` use case — feature scenarios

**Files:**
- Create: `src/movie_brain/application/enrich.py`
- Create: `tests/features/enrich.feature`, `tests/step_defs/test_enrich.py`

**Interfaces:**
- Consumes: `Repository.films_needing_credits`, `.write_credits`, `.credits_for` (Task 4); `TmdbClient.movie_credits` (Task 3); `MAX_CONSECUTIVE_FAILURES` from `application/keying.py` (exists); `AuthError` from `infrastructure/tmdb.py` (exists).
- Produces:

```python
@dataclass(frozen=True)
class EnrichReport: scanned: int = 0; enriched: int = 0; failed: int = 0; aborted: bool = False
def enrich_credits(repo, tmdb, today, *, apply=False, limit=None, delay_s=0.25, sleep=time.sleep, log=_stderr) -> EnrichReport
```

- [ ] **Step 1: Write the feature file**

Create `tests/features/enrich.feature`:

```gherkin
Feature: Enriching films with TMDB credits

  The search bar is only as good as the data under it. OMDb caps actors at four and
  holds no characters; TMDB's credits carry the full cast with the character each
  actor played, in one call per film. The verb walks every live movie holding a TMDB
  id and no `credits_fetched_on`, writes what it finds, and stamps the film so the
  next run resumes where this one stopped. It is dry-run by default and never
  runs inside sync.

  Background:
    Given a film "The Big Sleep" (1946) holding tmdb id 910
    And TMDB publishes credits for tmdb id 910 with cast "Humphrey Bogart" as "Philip Marlowe"

  Scenario: A dry run fetches, reports, and writes nothing
    When I enrich credits without applying
    Then the report counts 1 scanned and 1 enriched
    And the film "The Big Sleep" still has no credits

  Scenario: Applying writes the credits and stamps the film
    When I enrich credits with apply
    Then the film "The Big Sleep" credits "Humphrey Bogart" as "Philip Marlowe"
    And the film "The Big Sleep" is stamped as enriched

  Scenario: A stamped film is never asked about again
    Given the film "The Big Sleep" is already enriched
    When I enrich credits with apply
    Then the report counts 0 scanned and 0 enriched
    And TMDB was never asked for credits of tmdb id 910

  Scenario: A film without a tmdb id is not on the worklist
    Given a film "Orphan" (1950) holding no tmdb id
    When I enrich credits with apply
    Then the report counts 1 scanned and 1 enriched

  Scenario: Repeated TMDB failures stop the run so the next one can resume
    Given 6 more films holding tmdb ids that TMDB cannot serve
    When I enrich credits with apply
    Then the report is marked aborted
    And the report counts 6 scanned and 1 enriched
    And the film "The Big Sleep" credits "Humphrey Bogart" as "Philip Marlowe"

  Scenario: The pause between calls is skipped before the first one
    Given 2 more films holding tmdb ids with empty credits
    When I enrich credits with apply
    Then TMDB was paced with 2 pauses
```

- [ ] **Step 2: Write the step definitions**

Create `tests/step_defs/test_enrich.py`:

```python
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

import pytest
import requests
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.enrich import enrich_credits
from movie_brain.domain.models import CastRow, Film, TmdbCredits

scenarios("../features/enrich.feature")


def _credits(tmdb_id: int, title: str, cast: tuple[CastRow, ...]) -> TmdbCredits:
    return TmdbCredits(
        tmdb_id=tmdb_id, imdb_id=None, title=title, original_title=title, year=None, runtime_min=None,
        overview=None, tagline=None, genres=(), keywords=(), cast=cast, crew=(),
    )


@dataclass
class FakeTmdb:
    """Only the one call the verb may make."""

    credits: dict[int, TmdbCredits] = field(default_factory=dict)
    failing: set[int] = field(default_factory=set)
    asked: list[int] = field(default_factory=list)

    def movie_credits(self, tmdb_id: int) -> TmdbCredits:
        self.asked.append(tmdb_id)
        if tmdb_id in self.failing:
            raise requests.ConnectionError("tmdb down")
        return self.credits[tmdb_id]


@pytest.fixture
def tmdb() -> FakeTmdb:
    return FakeTmdb()


@pytest.fixture
def films() -> dict[str, int]:
    return {}


@pytest.fixture
def result() -> dict:
    return {}


@pytest.fixture
def pauses() -> list[float]:
    return []


# Given ---------------------------------------------------------------------


@given(parsers.parse('a film "{title}" ({year:d}) holding tmdb id {tid:d}'))
def seed_film(repo, today, films, title, year, tid):
    film_id = repo.create_film(Film(title, year, None, ""))
    assert film_id is not None
    repo.set_external_id(film_id, "tmdb", str(tid), today)
    films[title] = film_id


@given(parsers.parse('a film "{title}" ({year:d}) holding no tmdb id'))
def seed_orphan(repo, films, title, year):
    film_id = repo.create_film(Film(title, year, None, ""))
    assert film_id is not None
    films[title] = film_id


@given(parsers.parse('TMDB publishes credits for tmdb id {tid:d} with cast "{name}" as "{character}"'))
def publishes_credits(tmdb, tid, name, character):
    tmdb.credits[tid] = _credits(tid, "The Big Sleep", (CastRow(4110, name, character, 0),))


@given(parsers.parse('the film "{title}" is already enriched'))
def already_enriched(repo, today, tmdb, films, title):
    repo.write_credits(films[title], tmdb.credits[910], today)


@given(parsers.parse("{n:d} more films holding tmdb ids that TMDB cannot serve"))
def failing_films(repo, today, tmdb, films, n):
    for i in range(n):
        tid = 9000 + i
        film_id = repo.create_film(Film(f"Broken {i}", 1960 + i, None, ""))
        assert film_id is not None
        repo.set_external_id(film_id, "tmdb", str(tid), today)
        tmdb.failing.add(tid)
        films[f"Broken {i}"] = film_id


@given(parsers.parse("{n:d} more films holding tmdb ids with empty credits"))
def empty_films(repo, today, tmdb, films, n):
    for i in range(n):
        tid = 8000 + i
        film_id = repo.create_film(Film(f"Empty {i}", 1970 + i, None, ""))
        assert film_id is not None
        repo.set_external_id(film_id, "tmdb", str(tid), today)
        tmdb.credits[tid] = _credits(tid, f"Empty {i}", ())
        films[f"Empty {i}"] = film_id


# When ----------------------------------------------------------------------


@when("I enrich credits without applying")
def run_dry(repo, tmdb, today, result, pauses):
    result["report"] = enrich_credits(repo, tmdb, today, apply=False, sleep=pauses.append, log=lambda _m: None)


@when("I enrich credits with apply")
def run_apply(repo, tmdb, today, result, pauses):
    result["report"] = enrich_credits(repo, tmdb, today, apply=True, sleep=pauses.append, log=lambda _m: None)


# Then ----------------------------------------------------------------------


@then(parsers.parse("the report counts {scanned:d} scanned and {enriched:d} enriched"))
def counts(result, scanned, enriched):
    assert (result["report"].scanned, result["report"].enriched) == (scanned, enriched)


@then("the report is marked aborted")
def aborted(result):
    assert result["report"].aborted is True


@then(parsers.parse('the film "{title}" still has no credits'))
def no_credits(repo, films, title):
    assert repo.credits_for(films[title]) == []


@then(parsers.parse('the film "{title}" credits "{name}" as "{character}"'))
def has_credit(repo, films, title, name, character):
    assert ("cast", name, character, "") in repo.credits_for(films[title])


@then(parsers.parse('the film "{title}" is stamped as enriched'))
def stamped(repo, films, title):
    with sqlite3.connect(repo.db_path) as c:
        row = c.execute("SELECT credits_fetched_on FROM tmdb_facts WHERE film_id = ?", (films[title],)).fetchone()
    assert row is not None and row[0] is not None


@then(parsers.parse("TMDB was never asked for credits of tmdb id {tid:d}"))
def never_asked(tmdb, tid):
    assert tid not in tmdb.asked


@then(parsers.parse("TMDB was paced with {n:d} pauses"))
def paced(pauses, n):
    assert len(pauses) == n
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/step_defs/test_enrich.py -q`
Expected: collection ERROR — `ModuleNotFoundError: No module named 'movie_brain.application.enrich'`.

- [ ] **Step 4: Implement the use case**

Create `src/movie_brain/application/enrich.py`:

```python
"""Enrich films with TMDB credits, keywords, overview and tagline — the data under the search bar.

One call per film (`TmdbClient.movie_credits`, spec D11). Dry-run by default: the calls are
made and logged, nothing is written. `--apply` writes each film through `write_credits`, which
replaces that film's rows in one transaction and stamps `tmdb_facts.credits_fetched_on`; the
worklist excludes stamped films, so an interrupted run resumes where it stopped. The
consecutive-failure abort is `application/keying.py`'s — the same shape as `repair imdb`.
Never called from `sync` (spec §5).
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import requests

from movie_brain.application.keying import MAX_CONSECUTIVE_FAILURES
from movie_brain.infrastructure.database import Repository
from movie_brain.infrastructure.tmdb import AuthError, TmdbClient

DELAY_S = 0.25  # TMDB advertises no limit; a quarter second keeps ~4,600 calls polite


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


@dataclass(frozen=True)
class EnrichReport:
    scanned: int = 0
    enriched: int = 0
    failed: int = 0
    aborted: bool = False


def enrich_credits(
    repo: Repository,
    tmdb: TmdbClient,
    today: date,
    *,
    apply: bool = False,
    limit: int | None = None,
    delay_s: float = DELAY_S,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = _stderr,
) -> EnrichReport:
    scanned = enriched = failed = consecutive = 0
    requested = False
    for target in repo.films_needing_credits(limit):
        if consecutive >= MAX_CONSECUTIVE_FAILURES:
            log("TMDB credit lookups failing repeatedly — stopping; the next run resumes.")
            return EnrichReport(scanned, enriched, failed, aborted=True)
        if requested:
            sleep(delay_s)
        requested = True
        scanned += 1
        try:
            credits = tmdb.movie_credits(target.tmdb_id)
        except (requests.RequestException, AuthError) as exc:
            log(f"  #{target.film_id} {target.title!r}: TMDB credits failed: {exc}")
            consecutive += 1
            failed += 1
            continue
        consecutive = 0
        log(
            f"  #{target.film_id} {target.title!r}: {len(credits.cast)} cast · {len(credits.crew)} crew · "
            f"{len(credits.keywords)} keywords" + ("" if credits.overview else " · no overview")
        )
        if apply:
            repo.write_credits(target.film_id, credits, today)
        enriched += 1
    return EnrichReport(scanned, enriched, failed)
```

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest tests/step_defs/test_enrich.py -q` → 6 passed.

The abort scenario's arithmetic: `MAX_CONSECUTIVE_FAILURES` in `application/keying.py` is **5** (verified). The Big Sleep enriches (scanned 1), then five failing films are asked and fail (scanned 6, consecutive 5); the loop's guard fires at the top of the seventh iteration, before the sixth failing film is asked — so `scanned == 6`, `enriched == 1`, `aborted is True`, and the sixth failing film is never in `tmdb.asked`. That is the property worth pinning: the run stops *before* asking again, not after.

- [ ] **Step 6: Commit**

```bash
git add src/movie_brain/application/enrich.py tests/features/enrich.feature tests/step_defs/test_enrich.py
git commit -m "a stamped film is never re-fetched, so the enrichment can be interrupted at any point"
```

---

### Task 7: CLI verb, `status` row, docs

**Files:**
- Modify: `src/movie_brain/cli.py` (imports; new Typer group near the `cheapcharts_app` definition; `status`)
- Modify: `src/movie_brain/infrastructure/database.py::summary` (one key)
- Modify: `CLAUDE.md`, `docs/backlog.md`, `docs/superpowers/specs/2026-09-06-power-search-design.md`
- Test: `tests/unit/test_cli.py`

**Interfaces:**
- Consumes: `enrich_credits`, `EnrichReport` (Task 6); `credits_summary` (Task 4); `load_tmdb_token`, `TmdbClient`, `_repo`, `_plain`, `console`, `err` (exist in `cli.py`).
- Produces: `movie-brain enrich credits [--apply] [--limit N]`; `movie-brain status` prints a `credits` row (`films with credits / films with a tmdb id`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cli.py` (add `from movie_brain.application.enrich import EnrichReport` to the imports):

```python
def test_enrich_credits_needs_a_tmdb_token(config_dir):
    r = runner.invoke(app, ["enrich", "credits"])
    assert r.exit_code == 2 and "TMDB" in r.output


def test_enrich_credits_is_dry_run_by_default_and_prints_the_report(config_dir, monkeypatch):
    (config_dir / "tmdb-read-token.txt").write_text("t")
    calls = {}

    def fake(repo, tmdb, today, **kw):
        calls.update(kw)
        return EnrichReport(scanned=5, enriched=4, failed=1)

    monkeypatch.setattr("movie_brain.cli.enrich_credits", fake)
    r = runner.invoke(app, ["enrich", "credits"])
    assert r.exit_code == 0, r.output
    assert calls["apply"] is False and calls["limit"] is None
    assert "enriched: 4" in r.output and "failed: 1" in r.output


def test_status_reports_credit_coverage(config_dir):
    r = runner.invoke(app, ["status"])
    assert r.exit_code == 0
    assert "credits" in r.output
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_cli.py -k "enrich or status_reports_credit" -q`
Expected: FAIL — `No such command 'enrich'` (exit code 2 with a different message for the first test — check the message assertion fails), `AttributeError ... has no attribute 'enrich_credits'`, and `"credits" in r.output` false.

- [ ] **Step 3: Implement**

In `src/movie_brain/cli.py`:

```python
# imports (alphabetical with the existing application imports)
from movie_brain.application.enrich import enrich_credits

# next to `cheapcharts_app`
enrich_app = typer.Typer(help="Enrich films with metadata the search bar runs on.")
app.add_typer(enrich_app, name="enrich")
```

Append to the end of `cli.py`:

```python
@enrich_app.command("credits")
def enrich_credits_cmd(
    apply: Annotated[bool, typer.Option("--apply", help="Write the credits (default: dry-run).")] = False,
    limit: Annotated[int | None, typer.Option("--limit", help="Batch size over the worklist.")] = None,
) -> None:
    """Fetch TMDB cast, crew, characters, keywords, overview and tagline for every film that
    holds a TMDB id and has not been enriched yet.

    One call per film. A stamped film is never re-fetched, so the run can be interrupted and
    resumed. Never part of sync. Dry-run by default.
    """
    cfg = load_config()
    token = load_tmdb_token(cfg)
    if not token:
        err.print(f"no TMDB token: set MOVIE_BRAIN_TMDB_TOKEN or write {cfg.tmdb_token_file}")
        raise typer.Exit(2)
    report = enrich_credits(_repo(), TmdbClient(token), date.today(), apply=apply, limit=limit, log=_plain)
    console.print(
        f"scanned: {report.scanned} · enriched: {report.enriched} · failed: {report.failed}"
        + (" · ABORTED" if report.aborted else "")
        + ("" if apply else "   (dry run — nothing written)")
    )
```

In `src/movie_brain/infrastructure/database.py::summary`, add one key to the returned dict:

```python
            "credits": self.credits_summary()["films_with_credits"],
```

- [ ] **Step 4: Run to verify they pass, then the whole gate**

Run: `uv run pytest tests/unit/test_cli.py -q` → PASS.
Run: `uv run pytest -q && uv run ruff check . && uv run mypy` → all green.

- [ ] **Step 5: Docs**

`CLAUDE.md` — add to the Commands block, after the `cheapcharts resolve` line:

```
uv run movie-brain enrich credits [--apply] [--limit N]     # TMDB cast/crew/characters/keywords/overview for every film holding a tmdb id and no `credits_fetched_on`; one call per film, stamped and resumable, never in sync; dry run by default (power-search spec §5)
```

`CLAUDE.md` — add one Rules bullet after the CheapCharts bullet (one unbroken line):

```
- Credits (power-search Plan A, migration 018): `person` / `film_credit` / `film_keyword` / `film_text` are the search data, written ONLY by `enrich credits` through `write_credits` (one film, one transaction, rows replaced whole) and moved by `merge_film` on the survivor-wins rule. `person` is NOT an identity — `tmdb_person_id` is a join, not a `KEY_AUTHORITY`, and nothing here touches keying or matching. Names are ROWS, not a payload, because the owner's spelling requirement needs `person_fts` (FTS5 `trigram`) to correct a misspelled name BEFORE the query runs; a bare trigram MATCH is a SUBSTRING test, so misspelling lookups are an OR of the query's trigrams (`domain/search.py::trigram_query`). The three FTS indexes are external-content tables kept in step by migration 018's triggers — never write to them directly; `INSERT INTO x(x) VALUES('rebuild')` rebuilds one. `job`/`department`/`character` are `NOT NULL DEFAULT ''` so the UNIQUE dedups (two NULLs are distinct to SQLite). Keywords are stored but never load-bearing (30% of films have none, spec D10).
```

`docs/backlog.md` item 8 — append (one line): `**Plan A shipped <date>:** migration 018 + `enrich credits`; the search bar itself is Plan B, spec §7–§9.` (fill the date at execution).

Spec `§4` Notes — replace the sentence beginning "`film_text_fts` is a contentless table" with: "`film_text` is a small content table (`film_id`, `title`, `overview`, `plot`) that exists only because an external-content FTS5 index needs one content table and these columns come from three; all three FTS indexes are external-content tables kept in step by triggers, so the base tables stay the truth. **A bare trigram `MATCH` is a substring test** (verified: `bogrt` finds nothing); misspelling lookups are an OR of the query's trigrams (`domain/search.py::trigram_query`), which returns every name sharing a window for the resolver to rank."

Run the owner's unwrap check on the two edited `.md` files if any line was wrapped: `~/code/praxis-workspace/praxis-halo/bin/unwrap-md CLAUDE.md docs/backlog.md docs/superpowers/specs/2026-09-06-power-search-design.md`.

- [ ] **Step 6: Commit**

```bash
git add src/movie_brain/cli.py src/movie_brain/infrastructure/database.py tests/unit/test_cli.py CLAUDE.md docs/backlog.md docs/superpowers/specs/2026-09-06-power-search-design.md
git commit -m "the search data has a verb and a status line, and the rules say who may write it"
```

---

### Task 8: Rehearse on a copy, then hand the live run to the owner

**Files:** none changed. This task is operational and ends with a report, not a commit.

- [ ] **Step 1: Copy the live DB and migrate the copy**

```bash
SP=<scratchpad>/rehearse-credits; mkdir -p "$SP"
cp ~/.config/movie-brain/movie-brain.db "$SP/movie-brain.db"
MOVIE_BRAIN_CONFIG_DIR="$SP" uv run movie-brain migrate            # prints pending: 018_credits.sql
MOVIE_BRAIN_CONFIG_DIR="$SP" uv run movie-brain migrate --apply
```

Expected: `applied: 018_credits.sql`; `sqlite3 "$SP/movie-brain.db" "SELECT MAX(version) FROM schema_version"` → 18.

- [ ] **Step 2: Dry-run then apply 200 films on the copy**

```bash
MOVIE_BRAIN_CONFIG_DIR="$SP" uv run movie-brain enrich credits --limit 200 2>"$SP/dry.log" | tail -2
MOVIE_BRAIN_CONFIG_DIR="$SP" uv run movie-brain enrich credits --limit 200 --apply 2>"$SP/apply.log" | tail -2
MOVIE_BRAIN_CONFIG_DIR="$SP" uv run movie-brain status | grep credits
```

Expected: dry run reports ~200 scanned and writes nothing (`credits` row still 0 before apply); apply reports ~200 enriched; `status` shows `credits 200`.

- [ ] **Step 3: Verify the Marlowe query on the copy**

```bash
sqlite3 -readonly "$SP/movie-brain.db" "
SELECT f.title, f.year, p.name FROM film_credit fc
JOIN person p ON p.id = fc.person_id JOIN films f ON f.id = fc.film_id
WHERE fc.character LIKE '%Marlowe%';"
sqlite3 -readonly "$SP/movie-brain.db" "SELECT name FROM person_fts WHERE person_fts MATCH '\"bog\" OR \"ogr\" OR \"grt\"' LIMIT 5;"
```

Expected: any Marlowe film within the first 200 ids appears with its actor; the second query lists Bogart-like names if any Bogart film is in the batch (it may not be — the batch is by film id; if empty, run the same query for a name known to be in the batch from `apply.log`).

- [ ] **Step 4: Report to the owner and stop**

Print the two `status` lines (before/after), the tail of `apply.log`, the Marlowe rows, and the exact commands for the live run:

```bash
uv run movie-brain migrate --apply                 # backs up first; applies 018
uv run movie-brain enrich credits --apply          # ~4,569 calls, ~20 min at 0.25 s pacing; interruptible
```

**Do not run these against the live DB.** The owner's standing rule for live-DB changes is announce the exact change and rows, wait for yes, do only that (memory `one-at-a-time`). The migration and the enrichment are two separate yeses.

---

## Self-review

**Spec coverage.** §4 data model → Task 1 (with the `film_text` amendment recorded in Task 7). §5 verb → Tasks 6–7. §6 what is stored → Task 3 (parse) + Task 4 (write). §10 degradation: "enrichment not run" is Plan B's endpoint behaviour; "TMDB unreachable" → Task 6 abort; "no tmdb id" → Task 4 worklist; "FTS5 trigram unavailable" → migration 018 fails at `CREATE VIRTUAL TABLE` inside `BEGIN/COMMIT`, so the DB is left untouched and the error names the tokenizer — no extra code. §11 testing: migration ✓, enrichment ✓, `merge_film` ✓; parser/resolution/bar are Plan B. D3, D9 (all crew rows stored), D10, D11, D12 ✓. Not in this plan and on purpose: §7–§9 (Plan B).

**Placeholder scan.** Task 6 step 5 has an "adjust if the constant is 3" instruction — that is a verification step with both outcomes specified, not a placeholder. Task 7's backlog line carries `<date>` to be filled at execution; acceptable for a changelog line.

**Type consistency.** `TmdbCredits` field names match between Task 2 (definition), Task 3 (constructor), Task 4 (`credits.cast`, `.crew`, `.keywords`, `.genres`, `.overview`, `.tagline`, `.year`, `.runtime_min`, `.imdb_id`, `.tmdb_id`, `.title`, `.original_title`) and the test helpers. `CastRow(person_id, name, character, order)` / `CrewRow(person_id, name, job, department)` positional order is the same everywhere. `credits_for` returns `(kind, name, character, job)` and every assertion uses that order. `EnrichReport(scanned, enriched, failed, aborted)` matches the CLI print and the step defs.
