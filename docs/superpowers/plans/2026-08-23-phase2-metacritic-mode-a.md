# Phase 2: Metacritic Mode A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enrich the existing ~3,000 Criterion films with Metacritic identities (slug → `external_ids`) and first-class metascores via one polite, archived browse walk (10 pages first, extendable), with an offline re-runnable matcher, a durable review queue, and a coverage report.

**Architecture:** Hexagonal, mirroring the OMDb/Criterion pattern: pure matching rules in `domain/matching.py`; crawler + `__NUXT_DATA__` parser in `infrastructure/metacritic.py` (archive on disk = checkpoint); orchestration in `application/metacritic.py`; migration 004 adds a `metacritic` staging table (slug PK) and `match_review` queue; the FilmView query COALESCEs scraped score over OMDb's.

**Tech Stack:** Python 3.12, uv, Typer, requests, SQLite, pytest + pytest-bdd + responses, ruff, mypy (strict, `files=["src"]`).

**Spec:** `docs/superpowers/specs/2026-08-23-phase2-metacritic-mode-a-design.md`

## Global Constraints

- New migration only (`migrations/004_metacritic.sql`); never edit applied migrations; wrap in `BEGIN`/`COMMIT`; migration must insert its own `schema_version` row (version 4).
- Collectors never delete: no film row is ever deleted; anomalies go to `match_review`; a slug `sqlite3.IntegrityError` is caught and logged, never crashes.
- Scrape contract: honest User-Agent, ~1 request / 3 s (parameterized `delay_s`, 0 in tests), raw HTML archived before any parsing depends on it, archived pages never re-fetched, 3 consecutive failures stop the crawl keeping progress, crawl never touches the DB.
- No scraping in the nightly sync: `application/sync.py`, `criterion.py`, `omdb.py`, `domain/filters.py` are NOT modified.
- Gate for every task: the commands shown in each task; final task runs `uv run pytest && uv run ruff check . && uv run mypy`.
- All commands run via `uv run`. Line length 120. mypy strict applies to everything under `src/`.
- Commit style: brief single line, focused on "why".

## File Structure

- `src/movie_brain/domain/models.py` — add `McTitle`, `ReviewEntry` dataclasses; `FilmView.metacritic_url` field.
- `src/movie_brain/domain/matching.py` (new) — `clean_title`, `norm_title`, `MatchResult`, `match_film` (pure, imports nothing outside stdlib).
- `src/movie_brain/infrastructure/metacritic.py` (new) — crawl, archive layout, `__NUXT_DATA__` parser.
- `src/movie_brain/application/metacritic.py` (new) — `crawl_archive`, `match_archive`, report dataclasses.
- `src/movie_brain/infrastructure/database.py` — migration-004 consumers: staging upsert, matching query, review-queue methods, view SQL COALESCE.
- `migrations/004_metacritic.sql` (new).
- `src/movie_brain/cli.py` — `metacritic` sub-app (`crawl`, `match`).
- `src/movie_brain/web/static/app.js` — drawer "Open on Metacritic" link.
- Tests: `tests/unit/test_matching.py` (new), `tests/unit/test_metacritic.py` (new), `tests/unit/test_database.py` (extend), `tests/features/metacritic.feature` + `tests/step_defs/test_metacritic.py` (new), `tests/web/test_api.py` (extend), `tests/unit/test_cli.py` (extend), `tests/conftest.py` (add `nuxt_page` fixture).

---

### Task 1: Domain — models and matching rules

**Files:**
- Modify: `src/movie_brain/domain/models.py`
- Create: `src/movie_brain/domain/matching.py`
- Test: `tests/unit/test_matching.py`

**Interfaces:**
- Consumes: nothing new.
- Produces (later tasks import these exactly):
  - `movie_brain.domain.models.McTitle(slug: str, title: str, year: int | None, score: int | None, rank: int, page: int)` — frozen dataclass.
  - `movie_brain.domain.models.ReviewEntry(reason: str, film_id: int | None = None, value: str | None = None, detail: str | None = None)` — frozen dataclass.
  - `movie_brain.domain.matching.clean_title(title: str) -> str`
  - `movie_brain.domain.matching.norm_title(title: str) -> str`
  - `movie_brain.domain.matching.MatchResult(winner: int | None, tied: tuple[int, ...] = ())` — frozen dataclass.
  - `movie_brain.domain.matching.match_film(mc_title: str, mc_year: int | None, candidates: list[tuple[int, str, int | None]]) -> MatchResult` — candidates are `(film_id, title, year)` rows whose normalized title already equals the MC title's.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_matching.py`:

```python
from movie_brain.domain.matching import MatchResult, clean_title, match_film, norm_title


def test_clean_title_strips_annotations():
    assert clean_title("Dekalog (1988)") == "Dekalog"
    assert clean_title("The Leopard (re-release)") == "The Leopard"
    assert clean_title("The Leopard (RE-RELEASE)") == "The Leopard"
    assert clean_title("Seven Samurai") == "Seven Samurai"
    # a parenthetical that is part of the title (not year/re-release) survives
    assert clean_title("Fanny (Part One)") == "Fanny (Part One)"


def test_norm_title_is_punctuation_and_case_insensitive():
    assert norm_title("Forbidden Lie$") == norm_title("Forbidden Lies")
    assert norm_title("PlayTime") == norm_title("playtime")
    assert norm_title("Léon") == "léon"  # unicode letters survive; only punctuation/space drop
    assert norm_title("W.R.: Mysteries of the Organism") == norm_title("WR Mysteries of the Organism")


def test_match_exact_year_wins():
    candidates = [(1, "Nosferatu", 1922), (2, "Nosferatu", 1979)]
    assert match_film("Nosferatu", 1979, candidates) == MatchResult(winner=2)


def test_match_us_rerelease_year_drift():
    # MC stamps the US release year: Tokyo Story 1972 must still match the 1953 film.
    assert match_film("Tokyo Story", 1972, [(5, "Tokyo Story", 1953)]) == MatchResult(winner=5)


def test_match_rejects_film_far_newer_than_mc_year():
    # original year > mc_year + 2 → a different film, not a match
    assert match_film("Solaris", 1972, [(9, "Solaris", 2002)]) == MatchResult(winner=None)


def test_match_yearless_film_matches_on_title():
    assert match_film("Trio", 1950, [(3, "Trio", None)]) == MatchResult(winner=3)


def test_match_yearless_mc_title_matches_on_title():
    assert match_film("Trio", None, [(3, "Trio", 1950)]) == MatchResult(winner=3)


def test_match_no_candidates():
    assert match_film("Anything", 2000, []) == MatchResult(winner=None)


def test_match_tie_is_ambiguous():
    # 1978 and 1980 are equidistant from 1979 and both pass the year rule → review, not a guess
    candidates = [(1, "Twin", 1978), (2, "Twin", 1980)]
    result = match_film("Twin", 1979, candidates)
    assert result.winner is None
    assert set(result.tied) == {1, 2}


def test_match_nearest_year_beats_farther():
    candidates = [(1, "Twin", 1950), (2, "Twin", 1978)]
    assert match_film("Twin", 1979, candidates) == MatchResult(winner=2)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_matching.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'movie_brain.domain.matching'`

- [ ] **Step 3: Implement**

Add to `src/movie_brain/domain/models.py` (after `OmdbRating`):

```python
@dataclass(frozen=True)
class McTitle:
    """One title card from Metacritic's sorted browse walk (staged, not a film)."""

    slug: str
    title: str
    year: int | None
    score: int | None
    rank: int  # position in the sorted walk
    page: int


@dataclass(frozen=True)
class ReviewEntry:
    """A match anomaly queued for human review — never a deletion."""

    reason: str
    film_id: int | None = None
    value: str | None = None
    detail: str | None = None
```

Create `src/movie_brain/domain/matching.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass

_ANNOTATION = re.compile(r"\s*\((?:re-release|\d{4})\)\s*$", re.IGNORECASE)
_FAR = 10_000  # sort key for year-less candidates: after any real year distance


def clean_title(title: str) -> str:
    """Strip trailing "(1988)" / "(re-release)" annotations Metacritic appends."""
    return _ANNOTATION.sub("", title).strip()


def norm_title(title: str) -> str:
    """Punctuation/case-insensitive comparison key ("Forbidden Lie$" == "Forbidden Lies").

    str.isalnum keeps unicode letters/digits and drops every kind of punctuation —
    including curly quotes, which a character-class regex would silently keep.
    """
    return "".join(ch for ch in title.casefold().replace("$", "s") if ch.isalnum())


@dataclass(frozen=True)
class MatchResult:
    winner: int | None
    tied: tuple[int, ...] = ()


def match_film(mc_title: str, mc_year: int | None, candidates: list[tuple[int, str, int | None]]) -> MatchResult:
    """Pick the film a Metacritic title refers to.

    ``candidates`` are (film_id, title, year) rows whose normalized title already equals
    ``norm_title(clean_title(mc_title))``. Metacritic stamps US re-release years, so a
    film's original year may trail the MC year by decades: accept year <= mc_year + 2;
    a missing year on either side matches on title alone. Best candidate: exact year
    first, then nearest; a tie for best is ambiguous and goes to review.
    """
    viable = [c for c in candidates if mc_year is None or c[2] is None or c[2] <= mc_year + 2]
    if not viable:
        return MatchResult(winner=None)

    def sort_key(c: tuple[int, str, int | None]) -> tuple[int, int]:
        year = c[2]
        if mc_year is None or year is None:
            return (1, _FAR)
        return (0 if year == mc_year else 1, abs(year - mc_year))

    ranked = sorted(viable, key=sort_key)
    if len(ranked) > 1 and sort_key(ranked[0]) == sort_key(ranked[1]):
        tied = tuple(c[0] for c in ranked if sort_key(c) == sort_key(ranked[0]))
        return MatchResult(winner=None, tied=tied)
    return MatchResult(winner=ranked[0][0])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_matching.py -v`
Expected: all PASS

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run mypy
git add src/movie_brain/domain/models.py src/movie_brain/domain/matching.py tests/unit/test_matching.py
git commit -m "Fold the spike's 98% matcher rules into the domain as pure functions"
```

---

### Task 2: Migration 004 + Repository staging/review methods

**Files:**
- Create: `migrations/004_metacritic.sql`
- Modify: `src/movie_brain/infrastructure/database.py`
- Test: `tests/unit/test_database.py` (append)

**Interfaces:**
- Consumes: `McTitle`, `ReviewEntry` from Task 1.
- Produces (Task 5 and 6 rely on these exactly):
  - `Repository.upsert_mc_titles(titles: list[McTitle], fetched_at: date) -> None`
  - `Repository.films_for_matching() -> list[tuple[int, str, int | None, int | None]]` — `(film_id, title, year, omdb_metacritic)` for ALL films.
  - `Repository.film_ids_with_external(authority: str) -> set[int]`
  - `Repository.replace_unresolved_reviews(authority: str, entries: list[ReviewEntry], created: date) -> None`
  - `Repository.open_reviews(authority: str) -> list[dict[str, object]]` — unresolved rows, keys `id, film_id, value, reason, detail, created_at`.
  - Tables `metacritic` and `match_review` as in the SQL below.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_database.py`:

```python
from movie_brain.domain.models import McTitle, ReviewEntry


def test_migration_004_creates_metacritic_tables(repo):
    import sqlite3

    conn = sqlite3.connect(repo.db_path)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"metacritic", "match_review"} <= tables
        assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == 4
    finally:
        conn.close()


def test_upsert_mc_titles_is_an_upsert(repo, today):
    t1 = McTitle("seven-samurai-1954", "Seven Samurai", 1956, 98, 1, 1)
    repo.upsert_mc_titles([t1], today)
    # a re-crawl updates the same slug in place
    t2 = McTitle("seven-samurai-1954", "Seven Samurai", 1956, 99, 2, 1)
    repo.upsert_mc_titles([t2], today)
    import sqlite3

    conn = sqlite3.connect(repo.db_path)
    try:
        rows = conn.execute("SELECT slug, score, rank FROM metacritic").fetchall()
        assert rows == [("seven-samurai-1954", 99, 2)]
    finally:
        conn.close()


def test_films_for_matching_includes_omdb_metascore(repo, today):
    from movie_brain.domain.models import Film, OmdbRating

    fid = repo.upsert_film(Film("Alpha", 1950, "Ann", "https://c/alpha"))
    repo.upsert_omdb(fid, OmdbRating(None, None, True, metacritic=85), today)
    fid2 = repo.upsert_film(Film("Beta", 1960, "Bob", "https://c/beta"))
    rows = repo.films_for_matching()
    assert (fid, "Alpha", 1950, 85) in rows
    assert (fid2, "Beta", 1960, None) in rows


def test_film_ids_with_external(repo, today):
    from movie_brain.domain.models import Film

    fid = repo.upsert_film(Film("Alpha", 1950, "Ann", "https://c/alpha"))
    assert repo.film_ids_with_external("metacritic") == set()
    repo.set_external_id(fid, "metacritic", "alpha-1950", today)
    assert repo.film_ids_with_external("metacritic") == {fid}


def test_review_queue_replaces_unresolved_and_keeps_resolved(repo, today):
    repo.replace_unresolved_reviews("metacritic", [ReviewEntry("ambiguous-title", value="twin-1979")], today)
    (row,) = repo.open_reviews("metacritic")
    # a human resolves it (Phase 8 tooling will do this; raw SQL stands in for it here)
    import sqlite3

    conn = sqlite3.connect(repo.db_path)
    try:
        conn.execute("UPDATE match_review SET resolved = 1 WHERE id = ?", (row["id"],))
        conn.commit()
    finally:
        conn.close()
    # the next match run replaces unresolved rows but never touches resolved ones
    repo.replace_unresolved_reviews("metacritic", [ReviewEntry("expected-miss", film_id=None, detail="x")], today)
    assert [r["reason"] for r in repo.open_reviews("metacritic")] == ["expected-miss"]
    conn = sqlite3.connect(repo.db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM match_review WHERE resolved = 1").fetchone()[0] == 1
    finally:
        conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_database.py -k "metacritic or mc_titles or matching or external or review" -v`
Expected: FAIL — `metacritic` table missing / `Repository` has no attribute `upsert_mc_titles`

- [ ] **Step 3: Create the migration**

Create `migrations/004_metacritic.sql`:

```sql
-- Phase 2: Metacritic Mode A (spec: docs/superpowers/specs/2026-08-23-phase2-metacritic-mode-a-design.md).
-- Additive only. metacritic stages parsed browse-walk cards (slug = Metacritic's native id;
-- also the Phase 5 Mode B foundation). match_review is the durable review queue for match
-- anomalies — collectors never delete; unresolved rows are recomputed by each match run.
BEGIN;
CREATE TABLE metacritic (
    slug TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    year INTEGER,
    score INTEGER,
    rank INTEGER NOT NULL,
    page INTEGER NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE TABLE match_review (
    id INTEGER PRIMARY KEY,
    authority TEXT NOT NULL,
    film_id INTEGER REFERENCES films(id),
    value TEXT,
    reason TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL,
    resolved INTEGER NOT NULL DEFAULT 0
);
INSERT INTO schema_version (version) VALUES (4);
COMMIT;
```

- [ ] **Step 4: Add the Repository methods**

In `src/movie_brain/infrastructure/database.py`, extend the models import to include `McTitle` and `ReviewEntry`, then add after the `services()` method:

```python
    # metacritic -------------------------------------------------------
    def upsert_mc_titles(self, titles: list[McTitle], fetched_at: date) -> None:
        day = fetched_at.isoformat()
        with self._conn() as c:
            for t in titles:
                c.execute(
                    "INSERT INTO metacritic (slug, title, year, score, rank, page, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(slug) DO UPDATE SET title=excluded.title, year=excluded.year, "
                    "score=excluded.score, rank=excluded.rank, page=excluded.page, fetched_at=excluded.fetched_at",
                    (t.slug, t.title, t.year, t.score, t.rank, t.page, day),
                )

    def films_for_matching(self) -> list[tuple[int, str, int | None, int | None]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT f.id, f.title, f.year, o.metacritic FROM films f "
                "LEFT JOIN omdb o ON o.film_id = f.id ORDER BY f.id"
            ).fetchall()
            return [(int(r["id"]), str(r["title"]), r["year"], r["metacritic"]) for r in rows]

    def film_ids_with_external(self, authority: str) -> set[int]:
        with self._conn() as c:
            rows = c.execute("SELECT film_id FROM external_ids WHERE authority = ?", (authority,)).fetchall()
            return {int(r["film_id"]) for r in rows}

    def replace_unresolved_reviews(self, authority: str, entries: list[ReviewEntry], created: date) -> None:
        # Derived state, recomputed per match run — the immutability rule binds films, not this queue.
        with self._conn() as c:
            c.execute("DELETE FROM match_review WHERE authority = ? AND resolved = 0", (authority,))
            for e in entries:
                c.execute(
                    "INSERT INTO match_review (authority, film_id, value, reason, detail, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (authority, e.film_id, e.value, e.reason, e.detail, created.isoformat()),
                )

    def open_reviews(self, authority: str) -> list[dict[str, object]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT id, film_id, value, reason, detail, created_at FROM match_review "
                "WHERE authority = ? AND resolved = 0 ORDER BY id",
                (authority,),
            ).fetchall()
            return [dict(r) for r in rows]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_database.py -v`
Expected: all PASS (new and pre-existing — migration 004 must not break the v3 migration tests)

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff check . && uv run mypy
git add migrations/004_metacritic.sql src/movie_brain/infrastructure/database.py tests/unit/test_database.py
git commit -m "Stage Metacritic titles and queue match anomalies in SQLite (migration 004)"
```

---

### Task 3: Parser + archive layout (infrastructure, no network)

**Files:**
- Create: `src/movie_brain/infrastructure/metacritic.py`
- Modify: `tests/conftest.py` (add the `nuxt_page` fixture)
- Test: `tests/unit/test_metacritic.py`

**Interfaces:**
- Consumes: `McTitle` from Task 1.
- Produces (Tasks 4–5 rely on these exactly):
  - `movie_brain.infrastructure.metacritic.BROWSE_URL = "https://www.metacritic.com/browse/movie/"`
  - `USER_AGENT`, `CARDS_PER_PAGE = 24`, `MAX_CONSECUTIVE_FAILURES = 3`
  - `class CrawlError(Exception)`
  - `archive_dir(config_dir: Path) -> Path` — `config_dir / "metacritic"`
  - `page_path(archive: Path, page: int) -> Path` — `archive / "pages" / f"page-{page:04d}.html"`
  - `archived_pages(archive: Path) -> list[int]`
  - `parse_page(html: str, page: int) -> list[McTitle]`
  - `parse_archive(archive: Path) -> list[McTitle]`
  - Test fixture `nuxt_page(cards: list[tuple[str, str, int | None, int | None]]) -> str` where a card is `(title, slug, year, score)`.

- [ ] **Step 1: Add the shared fixture**

Append to `tests/conftest.py`:

```python
@pytest.fixture
def nuxt_page():
    """Build a browse-page HTML body in the __NUXT_DATA__ shape the parser reads.

    Nuxt serializes a flat array where dict values are indices into the same array;
    a title card is a dict holding indices for title, slug, premiereYear, and
    criticScoreSummary (itself a dict whose "score" key indexes the int score).
    Cards are (title, slug, year, score) tuples.
    """
    import json

    def build(cards):
        data = ["root"]

        def add(value):
            data.append(value)
            return len(data) - 1

        for title, slug, year, score in cards:
            summary_idx = add({"score": add(score)})
            data.append(
                {
                    "title": add(title),
                    "slug": add(slug),
                    "premiereYear": add(year),
                    "criticScoreSummary": summary_idx,
                }
            )
        payload = json.dumps(data)
        return f'<html><body><script type="application/json" id="__NUXT_DATA__">{payload}</script></body></html>'

    return build
```

- [ ] **Step 2: Write the failing tests**

Create `tests/unit/test_metacritic.py`:

```python
from movie_brain.domain.models import McTitle
from movie_brain.infrastructure.metacritic import (
    archive_dir,
    archived_pages,
    page_path,
    parse_archive,
    parse_page,
)


def test_parse_page_extracts_cards_in_order(nuxt_page):
    html = nuxt_page([("Seven Samurai", "seven-samurai-1954", 1956, 98), ("Tokyo Story", "tokyo-story", 1972, 97)])
    assert parse_page(html, page=1) == [
        McTitle("seven-samurai-1954", "Seven Samurai", 1956, 98, rank=1, page=1),
        McTitle("tokyo-story", "Tokyo Story", 1972, 97, rank=2, page=1),
    ]


def test_parse_page_rank_offsets_by_page(nuxt_page):
    html = nuxt_page([("Late Spring", "late-spring", 1949, 96)])
    (t,) = parse_page(html, page=3)
    assert t.rank == 2 * 24 + 1  # (page-1) * CARDS_PER_PAGE + position


def test_parse_page_tolerates_missing_year_and_score(nuxt_page):
    html = nuxt_page([("Mystery", "mystery", None, None)])
    (t,) = parse_page(html, page=1)
    assert t.year is None and t.score is None and t.slug == "mystery"


def test_parse_page_without_nuxt_island_yields_nothing():
    assert parse_page("<html><body>bot wall</body></html>", page=1) == []


def test_archive_roundtrip(tmp_path, nuxt_page):
    archive = archive_dir(tmp_path)
    for page, cards in [(1, [("A", "a", 2000, 90)]), (2, [("B", "b", 2001, 89)])]:
        p = page_path(archive, page)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(nuxt_page(cards))
    assert archived_pages(archive) == [1, 2]
    titles = parse_archive(archive)
    assert [t.slug for t in titles] == ["a", "b"]
    assert [t.page for t in titles] == [1, 2]


def test_archived_pages_empty_when_no_archive(tmp_path):
    assert archived_pages(archive_dir(tmp_path)) == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_metacritic.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'movie_brain.infrastructure.metacritic'`

- [ ] **Step 4: Implement the module (parser + layout only; crawl comes in Task 4)**

Create `src/movie_brain/infrastructure/metacritic.py`:

```python
from __future__ import annotations

import json
import re
from pathlib import Path

from movie_brain.domain.models import McTitle

BROWSE_URL = "https://www.metacritic.com/browse/movie/"
USER_AGENT = "movie-brain/0.1 (personal project)"
CARDS_PER_PAGE = 24
MAX_CONSECUTIVE_FAILURES = 3

_NUXT = re.compile(r'<script type="application/json"[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>', re.S)
_CARD_KEYS = {"title", "slug", "premiereYear", "criticScoreSummary"}


class CrawlError(Exception):
    pass


def archive_dir(config_dir: Path) -> Path:
    return config_dir / "metacritic"


def page_path(archive: Path, page: int) -> Path:
    return archive / "pages" / f"page-{page:04d}.html"


def archived_pages(archive: Path) -> list[int]:
    pages = archive / "pages"
    if not pages.exists():
        return []
    return sorted(int(p.stem.split("-")[1]) for p in pages.glob("page-*.html"))


def parse_page(html: str, page: int) -> list[McTitle]:
    """Extract title cards from a browse page's __NUXT_DATA__ JSON island.

    The island is a flat array whose dict values hold indices into the same array;
    a card is any dict carrying all of _CARD_KEYS. Parsing reads the archive only —
    a parser fix means re-running match, never re-fetching.
    """
    m = _NUXT.search(html)
    if not m:
        return []
    data = json.loads(m.group(1))
    titles: list[McTitle] = []
    for node in data:
        if not (isinstance(node, dict) and _CARD_KEYS <= node.keys()):
            continue
        title, slug, year = data[node["title"]], data[node["slug"]], data[node["premiereYear"]]
        if not (isinstance(title, str) and isinstance(slug, str)):
            continue
        summary = data[node["criticScoreSummary"]]
        score = None
        if isinstance(summary, dict) and "score" in summary:
            raw = data[summary["score"]]
            if isinstance(raw, int):
                score = raw
        rank = (page - 1) * CARDS_PER_PAGE + len(titles) + 1
        titles.append(McTitle(slug=slug, title=title, year=year if isinstance(year, int) else None, score=score, rank=rank, page=page))
    return titles


def parse_archive(archive: Path) -> list[McTitle]:
    titles: list[McTitle] = []
    for page in archived_pages(archive):
        titles.extend(parse_page(page_path(archive, page).read_text(), page))
    return titles
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_metacritic.py -v`
Expected: all PASS

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff check . && uv run mypy
git add src/movie_brain/infrastructure/metacritic.py tests/unit/test_metacritic.py tests/conftest.py
git commit -m "Parse Metacritic browse cards from the raw archive, never the network"
```

---

### Task 4: Crawler + BDD crawl scenarios

**Files:**
- Modify: `src/movie_brain/infrastructure/metacritic.py`
- Create: `src/movie_brain/application/metacritic.py` (crawl half)
- Create: `tests/features/metacritic.feature` (crawl scenarios)
- Create: `tests/step_defs/test_metacritic.py` (crawl steps)

**Interfaces:**
- Consumes: Task 3's `archive_dir`, `page_path`, `archived_pages`, `parse_page`, `BROWSE_URL`, `USER_AGENT`, `MAX_CONSECUTIVE_FAILURES`, `CrawlError`.
- Produces:
  - `movie_brain.infrastructure.metacritic.CrawlResult(fetched: int, skipped: int, failed: bool)` — frozen dataclass.
  - `movie_brain.infrastructure.metacritic.crawl(archive: Path, pages: int, session: requests.Session, *, delay_s: float = 3.0, log: Callable[[str], None] = _stderr) -> CrawlResult`
  - `movie_brain.application.metacritic.CrawlReport(exit_code: int, fetched: int, skipped: int, archived: int)` — frozen dataclass.
  - `movie_brain.application.metacritic.crawl_archive(config_dir: Path, pages: int, *, session: requests.Session | None = None, delay_s: float = 3.0, log: Callable[[str], None] = _stderr) -> CrawlReport`

- [ ] **Step 1: Write the failing feature + steps (crawl scenarios only)**

Create `tests/features/metacritic.feature`:

```gherkin
Feature: Metacritic archive
  One polite browse walk, archived raw with checkpoint/resume; matching enriches
  existing films and never deletes anything.

  Scenario: Crawl archives the requested pages
    Given Metacritic serves 3 browse pages
    When I crawl 3 pages
    Then the crawl exit code is 0
    And 3 pages are archived
    And the fetch log records 3 fetches

  Scenario: Crawl skips pages already archived
    Given Metacritic serves 3 browse pages
    And pages 1 and 2 are already archived
    When I crawl 3 pages
    Then only page 3 was fetched from the network
    And 3 pages are archived

  Scenario: Repeated failures stop the crawl but keep progress
    Given Metacritic serves page 1 then errors
    When I crawl 9 pages
    Then the crawl exit code is 1
    And 1 pages are archived

  Scenario: A bot wall page is a failure, not an archive entry
    Given Metacritic serves pages without title cards
    When I crawl 5 pages
    Then the crawl exit code is 1
    And 0 pages are archived
```

Create `tests/step_defs/test_metacritic.py`:

```python
from __future__ import annotations

import json
from datetime import date

import pytest
import requests
import responses
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.metacritic import crawl_archive
from movie_brain.infrastructure.metacritic import BROWSE_URL, archive_dir, archived_pages, page_path

scenarios("../features/metacritic.feature")

TODAY = date(2026, 8, 19)


@pytest.fixture
def ctx(repo, config_dir, nuxt_page):
    rs = responses.RequestsMock(assert_all_requests_are_fired=False)
    rs.start()
    yield {
        "repo": repo,
        "config_dir": config_dir,
        "rs": rs,
        "nuxt_page": nuxt_page,
        "crawl": None,
        "report": None,
        "cards": [],
    }
    rs.stop()
    rs.reset()


def _page_cards(page: int) -> list[tuple[str, str, int | None, int | None]]:
    # Deterministic distinct cards per page; scores descend with page number.
    return [(f"Film P{page}", f"film-p{page}", 2000 + page, 99 - page)]


@given(parsers.parse("Metacritic serves {n:d} browse pages"))
def mc_pages(ctx, n):
    def cb(request):
        page = int(request.params.get("page", "1"))
        if page > n:
            return (404, {}, "not found")
        return (200, {}, ctx["nuxt_page"](_page_cards(page)))

    ctx["rs"].add_callback(responses.GET, BROWSE_URL, callback=cb)


@given("Metacritic serves page 1 then errors")
def mc_then_errors(ctx):
    def cb(request):
        page = int(request.params.get("page", "1"))
        if page == 1:
            return (200, {}, ctx["nuxt_page"](_page_cards(1)))
        return (500, {}, "boom")

    ctx["rs"].add_callback(responses.GET, BROWSE_URL, callback=cb)


@given("Metacritic serves pages without title cards")
def mc_botwall(ctx):
    ctx["rs"].add_callback(responses.GET, BROWSE_URL, callback=lambda r: (200, {}, "<html>captcha</html>"))


@given("pages 1 and 2 are already archived")
def pre_archived(ctx):
    archive = archive_dir(ctx["config_dir"])
    for page in (1, 2):
        p = page_path(archive, page)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(ctx["nuxt_page"](_page_cards(page)))


@when(parsers.parse("I crawl {n:d} pages"))
def run_crawl(ctx, n):
    ctx["crawl"] = crawl_archive(
        ctx["config_dir"], n, session=requests.Session(), delay_s=0, log=lambda m: None
    )


@then(parsers.parse("the crawl exit code is {code:d}"))
def crawl_exit(ctx, code):
    assert ctx["crawl"].exit_code == code


@then(parsers.parse("{n:d} pages are archived"))
def n_archived(ctx, n):
    assert len(archived_pages(archive_dir(ctx["config_dir"]))) == n


@then(parsers.parse("the fetch log records {n:d} fetches"))
def fetch_log(ctx, n):
    log = archive_dir(ctx["config_dir"]) / "fetch-log.jsonl"
    entries = [json.loads(line) for line in log.read_text().splitlines()]
    assert len(entries) == n
    assert all({"page", "url", "fetched_at", "status"} <= e.keys() for e in entries)


@then("only page 3 was fetched from the network")
def only_page_three(ctx):
    calls = [c for c in ctx["rs"].calls if c.request.url.startswith(BROWSE_URL)]
    assert len(calls) == 1 and "page=3" in calls[0].request.url
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/step_defs/test_metacritic.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'movie_brain.application.metacritic'`

- [ ] **Step 3: Implement `crawl` in the infrastructure module**

Append to `src/movie_brain/infrastructure/metacritic.py` (extend the imports with `sys`, `time`, `dataclass`, `Callable`, `datetime`/`UTC`, and `requests`):

```python
def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


@dataclass(frozen=True)
class CrawlResult:
    fetched: int
    skipped: int
    failed: bool


def crawl(
    archive: Path,
    pages: int,
    session: requests.Session,
    *,
    delay_s: float = 3.0,
    log: Callable[[str], None] = _stderr,
) -> CrawlResult:
    """Politely walk browse pages 1..pages into the raw archive.

    An archived page is never re-fetched, so the archive is its own checkpoint: a
    later call with a bigger ``pages`` extends it, and a mid-walk stop loses nothing.
    Never touches the database. A page with no parseable cards (bot wall) is a
    failure — archiving it would poison the parse step.
    """
    (archive / "pages").mkdir(parents=True, exist_ok=True)
    fetched = skipped = consecutive = 0
    requested = False
    for page in range(1, pages + 1):
        target = page_path(archive, page)
        if target.exists():
            skipped += 1
            continue
        if requested:
            time.sleep(delay_s)
        requested = True
        try:
            resp = session.get(BROWSE_URL, params={"page": page}, headers={"User-Agent": USER_AGENT}, timeout=30)
            resp.raise_for_status()
            if not parse_page(resp.text, page):
                raise CrawlError(f"page {page}: no title cards in response")
        except (requests.RequestException, CrawlError) as exc:
            consecutive += 1
            log(f"fetch failed ({consecutive}/{MAX_CONSECUTIVE_FAILURES}): {exc}")
            if consecutive >= MAX_CONSECUTIVE_FAILURES:
                log("stopping — archived pages kept; the next crawl resumes here")
                return CrawlResult(fetched, skipped, True)
            continue
        target.write_text(resp.text)
        entry = {"page": page, "url": resp.url, "fetched_at": datetime.now(UTC).isoformat(), "status": resp.status_code}
        with (archive / "fetch-log.jsonl").open("a") as fh:
            fh.write(json.dumps(entry) + "\n")
        fetched += 1
        consecutive = 0
    return CrawlResult(fetched, skipped, False)
```

- [ ] **Step 4: Implement the application crawl wrapper**

Create `src/movie_brain/application/metacritic.py`:

```python
from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import requests

from movie_brain.infrastructure import metacritic as mc

AUTHORITY = "metacritic"


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


@dataclass(frozen=True)
class CrawlReport:
    exit_code: int
    fetched: int
    skipped: int
    archived: int  # pages now in the archive


def crawl_archive(
    config_dir: Path,
    pages: int,
    *,
    session: requests.Session | None = None,
    delay_s: float = 3.0,
    log: Callable[[str], None] = _stderr,
) -> CrawlReport:
    archive = mc.archive_dir(config_dir)
    result = mc.crawl(archive, pages, session or requests.Session(), delay_s=delay_s, log=log)
    return CrawlReport(1 if result.failed else 0, result.fetched, result.skipped, len(mc.archived_pages(archive)))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/step_defs/test_metacritic.py tests/unit/test_metacritic.py -v`
Expected: all PASS

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff check . && uv run mypy
git add src/movie_brain/infrastructure/metacritic.py src/movie_brain/application/metacritic.py tests/features/metacritic.feature tests/step_defs/test_metacritic.py
git commit -m "Polite checkpointed Metacritic crawl: the archive is the resume point"
```

---

### Task 5: Match use case + BDD match scenarios

**Files:**
- Modify: `src/movie_brain/application/metacritic.py`
- Modify: `tests/features/metacritic.feature` (append scenarios)
- Modify: `tests/step_defs/test_metacritic.py` (append steps)

**Interfaces:**
- Consumes: Task 1 matching functions, Task 2 Repository methods, Task 3 parse functions, Task 4 module skeleton.
- Produces (Task 7's CLI relies on this exactly):
  - `movie_brain.application.metacritic.MatchReport(exit_code: int, pages: int, titles: int, floor: int | None, films: int, matched: int, expected_missed: int, review_open: int, warnings: tuple[str, ...] = ())` — frozen dataclass with property `unmatched -> int` returning `films - matched`.
  - `movie_brain.application.metacritic.match_archive(repo: Repository, config_dir: Path, today: date, *, log: Callable[[str], None] = _stderr) -> MatchReport`
  - Review reasons written: `"ambiguous-title"`, `"film-multiple-slugs"`, `"slug-conflict"`, `"expected-miss"`.

- [ ] **Step 1: Append the failing scenarios**

Append to `tests/features/metacritic.feature`:

```gherkin
  Scenario: Match links an archived title to its film
    Given the repository holds the film "Seven Samurai (1954)"
    And the archive holds "Seven Samurai" (1956) scored 98 as "seven-samurai-1954"
    When I match
    Then "Seven Samurai (1954)" has metacritic slug "seven-samurai-1954"
    And the coverage report says 1 of 1 films matched

  Scenario: Matching strips annotations and punctuation
    Given the repository holds the film "Forbidden Lies (2007)"
    And the archive holds "Forbidden Lie$ (re-release)" (2009) scored 80 as "forbidden-lies"
    When I match
    Then "Forbidden Lies (2007)" has metacritic slug "forbidden-lies"

  Scenario: An ambiguous title goes to the review queue, not a guess
    Given the repository holds the film "Twin (1978)"
    And the repository holds the film "Twin (1980)"
    And the archive holds "Twin" (1979) scored 90 as "twin-1979"
    When I match
    Then the review queue has an "ambiguous-title" entry
    And the coverage report says 0 of 2 films matched

  Scenario: A slug already claimed by another film is contained and queued
    Given the repository holds the film "Twin (1950)"
    And the film "Other (1960)" already claims metacritic slug "twin-1950"
    And the archive holds "Twin" (1950) scored 85 as "twin-1950"
    When I match
    Then the review queue has a "slug-conflict" entry
    And "Twin (1950)" has no metacritic slug

  Scenario: A film with an OMDb metascore above the floor that matched nothing is flagged
    Given the repository holds the film "Obscure (1950)" with OMDb metascore 85
    And the archive holds "Unrelated" (2000) scored 80 as "unrelated-2000"
    When I match
    Then the review queue has an "expected-miss" entry for "Obscure (1950)"

  Scenario: Re-running match is idempotent
    Given the repository holds the film "Twin (1978)"
    And the repository holds the film "Twin (1980)"
    And the archive holds "Twin" (1979) scored 90 as "twin-1979"
    When I match
    And I match
    Then the review queue has 1 open entries
    And no film was deleted

  Scenario: Match without an archive fails cleanly
    When I match
    Then the match exit code is 1
```

- [ ] **Step 2: Append the step definitions**

Append to `tests/step_defs/test_metacritic.py` (extend the imports with `from movie_brain.application.metacritic import match_archive`, `from movie_brain.domain.models import Film, OmdbRating`):

```python
def _film(title_year: str) -> Film:
    # "Seven Samurai (1954)" → Film
    import re as _re

    m = _re.match(r"(.+) \((\d{4})\)$", title_year)
    assert m
    return Film(m.group(1), int(m.group(2)), "Someone", f"https://c/{m.group(1).lower()}")


@given(parsers.parse('the repository holds the film "{title_year}"'))
def holds_film(ctx, title_year):
    ctx["repo"].upsert_film(_film(title_year))


@given(parsers.parse('the repository holds the film "{title_year}" with OMDb metascore {score:d}'))
def holds_film_with_mc(ctx, title_year, score):
    f = _film(title_year)
    fid = ctx["repo"].upsert_film(f)
    ctx["repo"].upsert_omdb(fid, OmdbRating(None, None, True, metacritic=score), TODAY)


@given(parsers.parse('the film "{title_year}" already claims metacritic slug "{slug}"'))
def film_claims_slug(ctx, title_year, slug):
    fid = ctx["repo"].upsert_film(_film(title_year))
    ctx["repo"].set_external_id(fid, "metacritic", slug, TODAY)


@given(parsers.re(r'the archive holds "(?P<title>[^"]+)" \((?P<year>\d+)\) scored (?P<score>\d+) as "(?P<slug>[^"]+)"'))
def archive_holds(ctx, title, year, score, slug):
    ctx["cards"].append((title, slug, int(year), int(score)))


@when("I match")
def run_match(ctx):
    if ctx["cards"]:
        archive = archive_dir(ctx["config_dir"])
        p = page_path(archive, 1)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(ctx["nuxt_page"](ctx["cards"]))
    ctx["report"] = match_archive(ctx["repo"], ctx["config_dir"], TODAY, log=lambda m: None)


@then(parsers.parse('"{title_year}" has metacritic slug "{slug}"'))
def has_slug(ctx, title_year, slug):
    fid = ctx["repo"].film_id_by_key(_film(title_year).key)
    assert ctx["repo"].external_ids_for(fid).get("metacritic") == slug


@then(parsers.parse('"{title_year}" has no metacritic slug'))
def has_no_slug(ctx, title_year):
    fid = ctx["repo"].film_id_by_key(_film(title_year).key)
    assert "metacritic" not in ctx["repo"].external_ids_for(fid)


@then(parsers.parse("the coverage report says {matched:d} of {films:d} films matched"))
def report_coverage(ctx, matched, films):
    assert ctx["report"].matched == matched and ctx["report"].films == films


@then(parsers.re(r'the review queue has an? "(?P<reason>[^"]+)" entry(?: for "(?P<title_year>[^"]+)")?'))
def review_entry(ctx, reason, title_year):
    rows = ctx["repo"].open_reviews("metacritic")
    hits = [r for r in rows if r["reason"] == reason]
    assert hits, f"no {reason!r} in {rows}"
    if title_year:
        fid = ctx["repo"].film_id_by_key(_film(title_year).key)
        assert any(r["film_id"] == fid for r in hits)


@then(parsers.parse("the review queue has {n:d} open entries"))
def review_count(ctx, n):
    assert len(ctx["repo"].open_reviews("metacritic")) == n


@then("no film was deleted")
def nothing_deleted(ctx):
    assert len(ctx["repo"].films_for_matching()) == 2


@then(parsers.parse("the match exit code is {code:d}"))
def match_exit(ctx, code):
    assert ctx["report"].exit_code == code
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/step_defs/test_metacritic.py -v`
Expected: crawl scenarios PASS; match scenarios FAIL — `cannot import name 'match_archive'`

- [ ] **Step 4: Implement `match_archive`**

Append to `src/movie_brain/application/metacritic.py` (extend the imports: `sqlite3`, `defaultdict` from `collections`, `date` from `datetime`, `clean_title, match_film, norm_title` from `movie_brain.domain.matching`, `McTitle, ReviewEntry` from `movie_brain.domain.models`, `Repository` from `movie_brain.infrastructure.database`):

```python
@dataclass(frozen=True)
class MatchReport:
    exit_code: int
    pages: int
    titles: int
    floor: int | None
    films: int
    matched: int
    expected_missed: int
    review_open: int
    warnings: tuple[str, ...] = ()

    @property
    def unmatched(self) -> int:
        return self.films - self.matched


def _verify(titles: list[McTitle]) -> list[str]:
    """Post-crawl contract checks — warnings, never failures."""
    warnings: list[str] = []
    by_page: dict[int, int] = defaultdict(int)
    for t in titles:
        by_page[t.page] += 1
    last_page = max(by_page) if by_page else 0
    for page, count in sorted(by_page.items()):
        if count != mc.CARDS_PER_PAGE and page != last_page:
            warnings.append(f"page {page}: {count} cards (expected {mc.CARDS_PER_PAGE})")
    scores_in_rank = [t.score for t in sorted(titles, key=lambda t: t.rank) if t.score is not None]
    if any(a < b for a, b in zip(scores_in_rank, scores_in_rank[1:], strict=False)):
        warnings.append("scores are not monotonically non-increasing through the walk")
    slugs = [t.slug for t in titles]
    if len(set(slugs)) != len(slugs):
        warnings.append("duplicate slugs across pages (walk shifted between fetches)")
    return warnings


def match_archive(
    repo: Repository,
    config_dir: Path,
    today: date,
    *,
    log: Callable[[str], None] = _stderr,
) -> MatchReport:
    """Offline and idempotent: parse the archive, stage titles, link films, report coverage.

    Direction is archive → films: a film absent from the archive is coverage, not an
    anomaly. Only genuine anomalies queue for review. Nothing is ever deleted.
    """
    archive = mc.archive_dir(config_dir)
    titles = mc.parse_archive(archive)
    if not titles:
        log("no archive — run `movie-brain metacritic crawl` first")
        return MatchReport(1, 0, 0, None, 0, 0, 0, 0)
    warnings = _verify(titles)
    for w in warnings:
        log(f"warning: {w}")
    repo.upsert_mc_titles(titles, today)

    films = repo.films_for_matching()
    by_norm: dict[str, list[tuple[int, str, int | None]]] = defaultdict(list)
    for film_id, title, year, _ in films:
        by_norm[norm_title(title)].append((film_id, title, year))

    reviews: list[ReviewEntry] = []
    slugs_by_film: dict[int, list[str]] = defaultdict(list)
    for t in titles:
        cleaned = clean_title(t.title)
        result = match_film(cleaned, t.year, by_norm.get(norm_title(cleaned), []))
        if result.tied:
            detail = f"films {sorted(result.tied)} tie for {t.title!r} ({t.year})"
            reviews.append(ReviewEntry("ambiguous-title", value=t.slug, detail=detail))
        elif result.winner is not None:
            slugs_by_film[result.winner].append(t.slug)

    for film_id, slugs in sorted(slugs_by_film.items()):
        if len(slugs) > 1:
            reviews.append(ReviewEntry("film-multiple-slugs", film_id=film_id, detail=", ".join(sorted(slugs))))
            continue
        try:
            repo.set_external_id(film_id, AUTHORITY, slugs[0], today)
        except sqlite3.IntegrityError:
            # UNIQUE(authority, value): the slug is already another film's id. Contain and
            # queue — one conflict must never abort the run (same posture as record_catalog).
            reviews.append(ReviewEntry("slug-conflict", film_id=film_id, value=slugs[0], detail="slug already claimed by another film"))

    linked = repo.film_ids_with_external(AUTHORITY)
    scores = [t.score for t in titles if t.score is not None]
    floor = min(scores) if scores else None
    expected_missed = 0
    for film_id, title, year, omdb_mc in films:
        if omdb_mc is not None and floor is not None and omdb_mc >= floor and film_id not in linked:
            expected_missed += 1
            detail = f"omdb metascore {omdb_mc} >= floor {floor}, no archive match for {title!r} ({year})"
            reviews.append(ReviewEntry("expected-miss", film_id=film_id, detail=detail))

    repo.replace_unresolved_reviews(AUTHORITY, reviews, today)
    return MatchReport(
        exit_code=0,
        pages=len(mc.archived_pages(archive)),
        titles=len(titles),
        floor=floor,
        films=len(films),
        matched=len(linked),
        expected_missed=expected_missed,
        review_open=len(repo.open_reviews(AUTHORITY)),
        warnings=tuple(warnings),
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/step_defs/test_metacritic.py -v`
Expected: all PASS. Reasoning checks for the tricky ones: the slug-conflict scenario has "Other (1960)" holding `twin-1950`, so "Twin (1950)"'s insert raises IntegrityError → queued, and `matched` counts Other (already linked) — the scenario asserts the queue and Twin's missing slug only. The expected-miss scenario: floor is 80, Obscure has omdb 85 and no match → flagged.

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff check . && uv run mypy
git add src/movie_brain/application/metacritic.py tests/features/metacritic.feature tests/step_defs/test_metacritic.py
git commit -m "Match archive titles to films: anomalies queue for review, coverage is a report"
```

---

### Task 6: First-class metascore in the view + drawer link

**Files:**
- Modify: `src/movie_brain/domain/models.py` (FilmView field)
- Modify: `src/movie_brain/infrastructure/database.py` (`_VIEW_SQL`, `_row_to_view`)
- Modify: `src/movie_brain/web/static/app.js` (drawer link)
- Test: `tests/web/test_api.py` (append)

**Interfaces:**
- Consumes: `metacritic` table + `external_ids` rows from Tasks 2/5.
- Produces: `FilmView.metacritic_url: str | None = None`; `/api/films` and `/api/films/<id>` payloads gain `metacritic_url`; `metacritic` value = scraped score when linked, else OMDb's.

- [ ] **Step 1: Write the failing test**

Append to `tests/web/test_api.py`:

```python
def test_scraped_metascore_is_authoritative_with_omdb_fallback(tmp_path):
    from datetime import date

    from movie_brain.domain.models import Film, McTitle, OmdbRating
    from movie_brain.infrastructure.database import Repository
    from movie_brain.web.app import create_app

    day = date(2026, 8, 19)
    repo = Repository(tmp_path / "t.db")
    repo.record_catalog(
        "criterion",
        [Film("Linked", 1950, "Ann", "https://c/linked"), Film("Fallback", 1960, "Bob", "https://c/fallback")],
        day,
    )
    linked_id = repo.film_id_by_key("linked (1950)")
    fallback_id = repo.film_id_by_key("fallback (1960)")
    repo.upsert_omdb(linked_id, OmdbRating(None, None, True, metacritic=90), day)
    repo.upsert_omdb(fallback_id, OmdbRating(None, None, True, metacritic=70), day)
    repo.upsert_mc_titles([McTitle("linked-1950", "Linked", 1950, 93, 1, 1)], day)
    repo.set_external_id(linked_id, "metacritic", "linked-1950", day)

    films = {f["title"]: f for f in create_app(repo).test_client().get("/api/films").get_json()}
    assert films["Linked"]["metacritic"] == 93  # scraped beats the OMDb relay
    assert films["Linked"]["metacritic_url"] == "https://www.metacritic.com/movie/linked-1950/"
    assert films["Fallback"]["metacritic"] == 70  # OMDb fallback keeps unlinked films scored
    assert films["Fallback"]["metacritic_url"] is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/web/test_api.py -k scraped -v`
Expected: FAIL — `KeyError: 'metacritic_url'` (or metacritic == 90)

- [ ] **Step 3: Implement**

In `src/movie_brain/domain/models.py`, add to `FilmView` after `metacritic`:

```python
    metacritic_url: str | None = None
```

In `src/movie_brain/infrastructure/database.py`, replace `_VIEW_SQL` with:

```python
_VIEW_SQL = """
SELECT f.id, f.title, f.year, f.director, l.url, o.language, o.imdb, o.rt,
       COALESCE(mc.score, o.metacritic) AS metacritic, x.value AS mc_slug, o.found,
       (o.film_id IS NULL) AS pending, l.leaving_date, l.first_seen, r.score,
       (l.last_seen < (SELECT MAX(last_seen) FROM listings WHERE source = l.source)) AS departed
FROM films f
JOIN listings l ON l.film_id = f.id AND l.source = ?
LEFT JOIN omdb o ON o.film_id = f.id
LEFT JOIN my_ratings r ON r.film_id = f.id
LEFT JOIN external_ids x ON x.film_id = f.id AND x.authority = 'metacritic'
LEFT JOIN metacritic mc ON mc.slug = x.value
"""
```

and in `_row_to_view`, after the `metacritic=` line add:

```python
        metacritic_url=f"https://www.metacritic.com/movie/{row['mc_slug']}/" if row["mc_slug"] else None,
```

In `src/movie_brain/web/static/app.js`, in `detailHtml`, replace the line

```javascript
      <p>${d.url ? `<a class="criterion" href="${esc(d.url)}" target="_blank" rel="noopener">Open on Criterion ↗</a>` : ''}
```

with

```javascript
      <p>${d.url ? `<a class="criterion" href="${esc(d.url)}" target="_blank" rel="noopener">Open on Criterion ↗</a>` : ''}
        ${d.metacritic_url ? ` <a class="criterion" href="${esc(d.metacritic_url)}" target="_blank" rel="noopener">Open on Metacritic ↗</a>` : ''}
```

(the `.criterion` class is the existing external-link style; reusing it keeps CSS untouched).

- [ ] **Step 4: Run the full web + unit suites**

Run: `uv run pytest tests/web tests/unit -v`
Expected: all PASS — the seeded Playwright dashboard has no metacritic links or scraped rows, so every existing assertion is unchanged (`external_ids` has no `metacritic` rows in that seed; COALESCE falls through to the OMDb values it always showed).

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run mypy
git add src/movie_brain/domain/models.py src/movie_brain/infrastructure/database.py src/movie_brain/web/static/app.js tests/web/test_api.py
git commit -m "Metascore reads scraped-first with OMDb fallback; drawer links to Metacritic"
```

---

### Task 7: CLI — `movie-brain metacritic crawl|match`

**Files:**
- Modify: `src/movie_brain/cli.py`
- Test: `tests/unit/test_cli.py` (append)

**Interfaces:**
- Consumes: `crawl_archive`, `match_archive`, `CrawlReport`, `MatchReport` from Tasks 4–5.
- Produces: `movie-brain metacritic crawl --pages N` (default 10) and `movie-brain metacritic match`, exit codes propagated from the reports.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cli.py`:

```python
def test_metacritic_crawl_reports_and_propagates_exit(config_dir, monkeypatch):
    from movie_brain.application.metacritic import CrawlReport

    calls = {}

    def fake_crawl(cfg_dir, pages, **kw):
        calls["pages"] = pages
        return CrawlReport(0, fetched=8, skipped=2, archived=10)

    monkeypatch.setattr("movie_brain.cli.crawl_archive", fake_crawl)
    r = runner.invoke(app, ["metacritic", "crawl"])
    assert r.exit_code == 0 and calls["pages"] == 10
    assert "fetched: 8" in r.output and "archived: 10" in r.output

    def failing_crawl(cfg_dir, pages, **kw):
        return CrawlReport(1, fetched=1, skipped=0, archived=1)

    monkeypatch.setattr("movie_brain.cli.crawl_archive", failing_crawl)
    r = runner.invoke(app, ["metacritic", "crawl", "--pages", "5"])
    assert r.exit_code == 1


def test_metacritic_match_prints_coverage_report(config_dir, monkeypatch):
    from movie_brain.application.metacritic import MatchReport

    report = MatchReport(0, pages=10, titles=240, floor=94, films=3051, matched=57, expected_missed=3, review_open=5)
    monkeypatch.setattr("movie_brain.cli.match_archive", lambda repo, cfg_dir, today: report)
    r = runner.invoke(app, ["metacritic", "match"])
    assert r.exit_code == 0
    assert "10 pages" in r.output and "240 titles" in r.output and "floor 94" in r.output
    assert "57/3051" in r.output and "1.9%" in r.output
    assert "expected-but-missed: 3" in r.output and "5 open" in r.output


def test_metacritic_match_fails_without_archive(config_dir, monkeypatch):
    from movie_brain.application.metacritic import MatchReport

    empty = MatchReport(1, 0, 0, None, 0, 0, 0, 0)
    monkeypatch.setattr("movie_brain.cli.match_archive", lambda repo, cfg_dir, today: empty)
    r = runner.invoke(app, ["metacritic", "match"])
    assert r.exit_code == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_cli.py -k metacritic -v`
Expected: FAIL — exit code 2 (unknown command `metacritic`)

- [ ] **Step 3: Implement**

In `src/movie_brain/cli.py`, add to the imports:

```python
from movie_brain.application.metacritic import crawl_archive, match_archive
```

after the `export_app` wiring add:

```python
metacritic_app = typer.Typer(help="Metacritic browse archive: crawl pages, match films.")
app.add_typer(metacritic_app, name="metacritic")
```

and add the commands (near the other commands):

```python
@metacritic_app.command("crawl")
def metacritic_crawl(
    pages: Annotated[
        int, typer.Option("--pages", help="Target page count for the archive; already-archived pages are skipped.")
    ] = 10,
) -> None:
    """Politely walk Metacritic's score-sorted browse pages into the local raw archive."""
    cfg = load_config()
    cfg.config_dir.mkdir(parents=True, exist_ok=True)
    report = crawl_archive(cfg.config_dir, pages)
    console.print(f"fetched: {report.fetched} · skipped: {report.skipped} · archived: {report.archived} pages")
    raise typer.Exit(report.exit_code)


@metacritic_app.command("match")
def metacritic_match() -> None:
    """Match archived Metacritic titles to films (offline, re-runnable) and report coverage."""
    report = match_archive(_repo(), load_config().config_dir, date.today())
    if report.exit_code != 0:
        raise typer.Exit(report.exit_code)
    pct = 100 * report.matched / report.films if report.films else 0.0
    console.print(f"archive: {report.pages} pages · {report.titles} titles · score floor {report.floor}")
    console.print(f"matched: {report.matched}/{report.films} films ({pct:.1f}%)")
    console.print(f"expected-but-missed: {report.expected_missed} → review queue")
    console.print(f"review queue: {report.review_open} open")
    console.print(f"below floor / unscored: {report.unmatched - report.expected_missed}")
    raise typer.Exit(0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_cli.py -v`
Expected: all PASS

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run mypy
git add src/movie_brain/cli.py tests/unit/test_cli.py
git commit -m "CLI verbs for the Metacritic archive: crawl is manual, match is offline"
```

---

### Task 8: Docs, roadmap, full gate

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/multiple-movie-services.md`
- Modify: `docs/superpowers/specs/2026-08-23-phase2-metacritic-mode-a-design.md` (status line)

- [ ] **Step 1: Update CLAUDE.md**

In the Commands block, after the `sync` line add:

```bash
uv run movie-brain metacritic crawl [--pages 10]     # extend the raw browse-page archive (polite, checkpointed)
uv run movie-brain metacritic match                  # offline: match archive → films, report coverage
```

In the Rules section add one bullet:

```markdown
- Metascores are scraped-first: the FilmView `metacritic` value COALESCEs the scraped
  `metacritic` table (joined via `external_ids` authority `metacritic` = slug) over
  `omdb.metacritic`. The raw page archive under `<config_dir>/metacritic/` is the crawl
  checkpoint — archived pages are never re-fetched; parsing reads only the archive. Match
  anomalies land in `match_review` (never deleted, never blocking); no scraping in sync.
```

In the Data section, append to the backups paragraph area:

```markdown
Metacritic archive: `<config_dir>/metacritic/pages/page-NNNN.html` + `fetch-log.jsonl`.
```

- [ ] **Step 2: Update the roadmap and spec status**

In `docs/multiple-movie-services.md`:
- Phase table row 2 → `Metacritic adapter, Mode A (enrich Criterion) — **done**`.
- Numbered list item 2: prefix with `**Done (2026-08-23).**` and append: `Landed as an incremental dial: \`metacritic crawl --pages N\` (10 first, extend by re-running with a bigger cap), offline \`match\`, scraped-first score with OMDb fallback, anomalies in \`match_review\`.`

In the spec, change `**Status:** approved design` → `**Status:** implemented`.

- [ ] **Step 3: Full gate**

Run: `uv run pytest && uv run ruff check . && uv run mypy`
Expected: all green (~150 tests incl. Playwright; run `uv run playwright install chromium` first if the browser is missing).

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md docs/multiple-movie-services.md docs/superpowers/specs/2026-08-23-phase2-metacritic-mode-a-design.md
git commit -m "Docs: Phase 2 (Metacritic Mode A) landed; scraped-first metascore rule"
```

---

## After the plan: first real run (manual, user-driven)

Not a task for the executor — the user runs, on `main` after merge:

```bash
uv run movie-brain metacritic crawl --pages 10   # ~30 s at 3 s/page
uv run movie-brain metacritic match              # coverage report on real data
```

Verify the join looks right (spot-check a few linked films in the dashboard drawer), then extend the dial (`--pages 110`, later 300) and re-run `match`.
