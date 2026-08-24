# Apple TV Owned Films Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import the user's Apple TV movie library via AppleScript, mark/create the owned films (guid identity), and surface ownership as a table badge, drawer link, Owned chip, and counts.

**Architecture:** Hexagonal, mirroring the Metacritic Mode-B shape: domain gets a title-cleaner and an owned-matcher; a new `infrastructure/appletv.py` adapter runs osascript and archives raw output first; `application/owned.py` orchestrates match-or-create through the Repository; migration 007 adds the `owned` table (watchlist pattern — possession data, no `listings` interaction); web layer exposes `FilmView.owned` with lockstep chip wiring.

**Tech Stack:** Python 3.12, SQLite, osascript/AppleScript (subprocess), Flask + vanilla JS, Typer, pytest + pytest-bdd + Playwright, uv, ruff, mypy.

**Spec:** docs/superpowers/specs/2026-08-23-apple-tv-owned-design.md

## Global Constraints

- Collectors/importers never delete and never unmark; anomalies → `match_review` (authority `apple-tv`), never guessed.
- Film identity = `films.guid`; created films get one via `Repository.create_film`; integer id never leaks.
- Import is a deliberate CLI verb (`movie-brain owned import`) — NEVER runs in sync; no HTTP.
- Raw osascript output is archived to `<config_dir>/appletv/owned-<YYYY-MM-DD>.txt` BEFORE parsing.
- New migration `007_owned.sql` only; never edit applied migrations; wrap in BEGIN/COMMIT + `schema_version` row.
- Chip lockstep: the `owned` predicate lands in `domain/filters.py` `_PREDICATES`, `app.js` `CHIP_PREDICATES`, and the `index.html` chip row together.
- `owned` table never touches `listings`/`availability_transitions` — no arrivals flood possible.
- Gate after every task: `uv run pytest` + `uv run ruff check .` + `uv run mypy` all green. All commands via `uv run …`.
- TDD; worktree via superpowers:using-git-worktrees.

---

### Task 1: Domain — `clean_apple_title` and `match_owned`

**Files:**
- Modify: `src/movie_brain/domain/matching.py`, `src/movie_brain/domain/models.py`
- Test: `tests/unit/test_matching.py`, `tests/unit/test_models.py`

**Interfaces:**
- Consumes: existing `norm_title`, `MatchResult` (in `matching.py`).
- Produces (Tasks 3–4 rely on these):
  - `OwnedTitle(title: str, year: int | None)` frozen dataclass in `models.py`
  - `clean_apple_title(title: str) -> str`
  - `match_owned(title: str, year: int | None, candidates: list[tuple[int, str, int | None]]) -> MatchResult` — candidates are `(film_id, title, year)` rows sharing the normalized title.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_matching.py`:

```python
from movie_brain.domain.matching import clean_apple_title, match_owned


@pytest.mark.parametrize(
    ("raw", "cleaned"),
    [
        ("Anchorman 2: The Legend Continues (Unrated)", "Anchorman 2: The Legend Continues"),
        ("Blade Runner (Director's Cut)", "Blade Runner"),
        ("Apocalypse Now (Extended Edition)", "Apocalypse Now"),
        ("Dune (Theatrical Version)", "Dune"),
        ("Alien (Special Edition)", "Alien"),
        ("Trainspotting (Uncut)", "Trainspotting"),
        ("Jaws (Remastered)", "Jaws"),
        ("Lawrence of Arabia (4K)", "Lawrence of Arabia"),
        ("Parasite (Subtitled)", "Parasite"),
        ("Spirited Away (Dubbed)", "Spirited Away"),
        ("Amelie (English Subtitles)", "Amelie"),
        ("Shaun of the Dead", "Shaun of the Dead"),  # no annotation
        ("Notting Hill (1999)", "Notting Hill (1999)"),  # unknown parenthetical kept
    ],
)
def test_clean_apple_title(raw, cleaned):
    assert clean_apple_title(raw) == cleaned


def test_match_owned_exact_year_wins():
    cands = [(1, "Solaris", 1972), (2, "Solaris", 2002)]
    assert match_owned("Solaris", 2002, cands).winner == 2


def test_match_owned_accepts_one_year_drift():
    assert match_owned("Alpha", 1951, [(1, "Alpha", 1950)]).winner == 1


def test_match_owned_rejects_two_year_drift():
    r = match_owned("Alpha", 1952, [(1, "Alpha", 1950)])
    assert r.winner is None and r.tied == ()


def test_match_owned_tie_is_ambiguous():
    r = match_owned("Twin", 1979, [(1, "Twin", 1978), (2, "Twin", 1980)])
    assert r.winner is None and set(r.tied) == {1, 2}


def test_match_owned_yearless_needs_unique_candidate():
    assert match_owned("Solo", None, [(1, "Solo", 1996)]).winner == 1
    r = match_owned("Twin", None, [(1, "Twin", 1978), (2, "Twin", 1980)])
    assert r.winner is None and set(r.tied) == {1, 2}
```

Append to `tests/unit/test_models.py`:

```python
def test_owned_title_holds_title_and_optional_year():
    from movie_brain.domain.models import OwnedTitle

    t = OwnedTitle("Step Brothers", 2008)
    assert (t.title, t.year) == ("Step Brothers", 2008)
    assert OwnedTitle("Unknown", None).year is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_matching.py -k "apple or owned" tests/unit/test_models.py -v`
Expected: FAIL — `ImportError` on `clean_apple_title` / `OwnedTitle`.

- [ ] **Step 3: Implement**

In `models.py` (after `McTitle`):

```python
@dataclass(frozen=True)
class OwnedTitle:
    """One movie from the user's Apple TV library export."""

    title: str
    year: int | None
```

In `matching.py` (after `clean_title`):

```python
_APPLE_ANNOTATIONS = (
    "unrated",
    "director's cut",
    "extended edition",
    "extended cut",
    "theatrical version",
    "theatrical cut",
    "special edition",
    "uncut",
    "remastered",
    "4k",
    "subtitled",
    "dubbed",
    "english subtitles",
)
_APPLE_ANNOTATION = re.compile(
    r"\s*\((?:" + "|".join(re.escape(a) for a in _APPLE_ANNOTATIONS) + r")\)\s*$",
    re.IGNORECASE,
)


def clean_apple_title(title: str) -> str:
    """Strip one trailing edition annotation the Apple TV library appends."""
    return _APPLE_ANNOTATION.sub("", title).strip()


def match_owned(
    title: str, year: int | None, candidates: list[tuple[int, str, int | None]]
) -> MatchResult:
    """Pick the film an owned Apple title refers to.

    Apple years are release years, so drift is small: exact year wins, else the
    unique candidate within +/-1; a year-less side needs a unique candidate.
    Ties are ambiguous and go to review, never guessed.
    """
    if year is None:
        if len(candidates) == 1:
            return MatchResult(winner=candidates[0][0])
        return MatchResult(winner=None, tied=tuple(c[0] for c in candidates)) if candidates else MatchResult(None)
    viable = [c for c in candidates if c[2] is None or abs(c[2] - year) <= 1]
    if not viable:
        return MatchResult(winner=None)

    def sort_key(c: tuple[int, str, int | None]) -> tuple[int, int]:
        return (1, _FAR) if c[2] is None else (0 if c[2] == year else 1, abs(c[2] - year))

    ranked = sorted(viable, key=sort_key)
    if len(ranked) > 1 and sort_key(ranked[0]) == sort_key(ranked[1]):
        return MatchResult(winner=None, tied=tuple(c[0] for c in ranked if sort_key(c) == sort_key(ranked[0])))
    return MatchResult(winner=ranked[0][0])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_matching.py tests/unit/test_models.py -v`
Expected: PASS.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run mypy
git add src/movie_brain/domain tests/unit/test_matching.py tests/unit/test_models.py
git commit -m "Domain: Apple title cleaner and owned matcher (exact year, ±1 drift, ties to review)"
```

---

### Task 2: Migration 007 + Repository owned methods + view field

**Files:**
- Create: `migrations/007_owned.sql`
- Modify: `src/movie_brain/infrastructure/database.py`, `src/movie_brain/domain/models.py`
- Test: `tests/unit/test_database.py`

**Interfaces:**
- Consumes: existing view plumbing (`_row_to_view`, `list_views`, `get_view`, `summary`), `_watchlist_ids` pattern.
- Produces (Tasks 4 and 6 rely on these):
  - `Repository.mark_owned(film_id: int, today: date, source: str = "apple-tv") -> bool` — True if newly inserted, False if already owned. Never raises for an existing row.
  - `Repository.owned_film_ids() -> set[int]`
  - `FilmView.owned: bool = False` (last dataclass field, appears in `to_dict()`)
  - `summary()` gains `"owned"` = owned count across ALL views (not criterion-scoped).

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_database.py`:

```python
def test_mark_owned_is_idempotent_and_views_expose_it(repo):
    day = date(2026, 8, 19)
    repo.record_catalog("criterion", [Film("Alpha", 1950, "Ann", "https://c/alpha")], day)
    aid = repo.film_id_by_key("alpha (1950)")
    gid = repo.create_film(Film("Golf", 2020, None, ""))

    assert repo.mark_owned(aid, day) is True
    assert repo.mark_owned(aid, day) is False  # second call: already owned, no error
    assert repo.mark_owned(gid, day) is True
    assert repo.owned_film_ids() == {aid, gid}

    views = {v.title: v for v in repo.list_views("criterion", day)}
    assert views["Alpha"].owned is True and views["Golf"].owned is True
    assert repo.get_view(aid, day).owned is True
    # owned counts across all views — the discovery film Golf is included.
    assert repo.summary("criterion")["owned"] == 2
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_database.py -k mark_owned -v`
Expected: FAIL — no `mark_owned` attribute.

- [ ] **Step 3: Implement**

Create `migrations/007_owned.sql`:

```sql
-- Apple TV owned films (spec: docs/superpowers/specs/2026-08-23-apple-tv-owned-design.md).
-- Additive only. owned is possession data on the watchlist pattern — written only by
-- `movie-brain owned import`, never by sync; rows are permanent (never unmarked).
BEGIN;
CREATE TABLE owned (
    film_id        INTEGER PRIMARY KEY REFERENCES films(id),
    source         TEXT NOT NULL DEFAULT 'apple-tv',
    first_imported TEXT NOT NULL
);
INSERT INTO schema_version (version) VALUES (7);
COMMIT;
```

In `models.py`, append to `FilmView` after `criterion`:

```python
    owned: bool = False  # in my Apple TV library (owned table); import is the only writer
```

In `database.py`:

- Next to `_watchlist_ids`:

```python
def _owned_ids(c: sqlite3.Connection) -> set[int]:
    return {int(r["film_id"]) for r in c.execute("SELECT film_id FROM owned")}
```

- `_row_to_view` gains a keyword param `owned: bool = False` passed through to `FilmView(owned=owned)`.
- In `list_views`, alongside `wl = _watchlist_ids(c)` add `ow = _owned_ids(c)` and pass `owned=r["id"] in ow` in the comprehension; in `get_view` pass `owned=row["id"] in _owned_ids(c)`.
- New section after the watchlist methods:

```python
    # owned -------------------------------------------------------------
    def mark_owned(self, film_id: int, today: date, source: str = "apple-tv") -> bool:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO owned (film_id, source, first_imported) VALUES (?, ?, ?) "
                "ON CONFLICT(film_id) DO NOTHING",
                (film_id, source, today.isoformat()),
            )
            return cur.rowcount > 0

    def owned_film_ids(self) -> set[int]:
        with self._conn() as c:
            return {int(r["film_id"]) for r in c.execute("SELECT film_id FROM owned")}
```

- In `summary()`, add `"owned": sum(1 for v in views if v.owned),` (note: `views`, not the criterion-scoped `crit`).

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest`
Expected: PASS — tests asserting exact summary dicts need `"owned": 0` added (same drill as Phase 5's `discovery` key; do not weaken anything else).

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run mypy
git add -A migrations src tests
git commit -m "Migration 007 + owned table: possession data on the watchlist pattern, exposed on FilmView"
```

---

### Task 3: AppleScript adapter — `infrastructure/appletv.py`

**Files:**
- Create: `src/movie_brain/infrastructure/appletv.py`
- Test: `tests/unit/test_appletv.py`

**Interfaces:**
- Consumes: `OwnedTitle` from Task 1.
- Produces (Task 4 relies on these):
  - `class AppleTvError(Exception)`
  - `fetch_owned(config_dir: Path, *, runner: Callable[[], str] | None = None, today: date | None = None) -> list[OwnedTitle]` — archives the raw text, then parses. `runner` (test seam) returns the raw osascript stdout; default runs the real osascript.
  - `parse_export(text: str) -> list[OwnedTitle]`
  - `archive_path(config_dir: Path, today: date) -> Path` = `<config_dir>/appletv/owned-<YYYY-MM-DD>.txt`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_appletv.py`:

```python
from __future__ import annotations

from datetime import date

import pytest

from movie_brain.infrastructure.appletv import AppleTvError, archive_path, fetch_owned, parse_export

TODAY = date(2026, 8, 19)


def test_parse_export_reads_tab_lines():
    text = "Step Brothers\t2008\nThe Other Guys\t2010\n"
    titles = parse_export(text)
    assert [(t.title, t.year) for t in titles] == [("Step Brothers", 2008), ("The Other Guys", 2010)]


def test_parse_export_missing_or_zero_year_becomes_none():
    titles = parse_export("Mystery Film\t0\nNo Year Film\t\nBlank Skipped\n\n")
    assert [(t.title, t.year) for t in titles] == [("Mystery Film", None), ("No Year Film", None)]


def test_fetch_owned_archives_raw_before_parsing(config_dir):
    raw = "Step Brothers\t2008\n"
    titles = fetch_owned(config_dir, runner=lambda: raw, today=TODAY)
    assert len(titles) == 1
    assert archive_path(config_dir, TODAY).read_text() == raw


def test_fetch_owned_runner_failure_raises_and_archives_nothing(config_dir):
    def boom() -> str:
        raise AppleTvError("osascript failed")

    with pytest.raises(AppleTvError):
        fetch_owned(config_dir, runner=boom, today=TODAY)
    assert not archive_path(config_dir, TODAY).exists()


def test_fetch_owned_empty_library_is_an_error(config_dir):
    with pytest.raises(AppleTvError):
        fetch_owned(config_dir, runner=lambda: "", today=TODAY)
```

(`config_dir` is the existing fixture from `tests/conftest.py`. `parse_export` skips lines with no tab — the "Blank Skipped" line and empty lines.)

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_appletv.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement**

Create `src/movie_brain/infrastructure/appletv.py`:

```python
"""Apple TV app adapter: export the owned-movie library via AppleScript.

The raw osascript output is archived before parsing (re-derivability rule):
a parser fix replays the archive without touching the TV app again. macOS-only;
never runs in sync — `movie-brain owned import` is the only caller.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from datetime import date
from pathlib import Path

from movie_brain.domain.models import OwnedTitle

_SCRIPT = """
tell application "TV"
    set ns to name of (every track of library playlist 1 whose media kind is movie)
    set ys to year of (every track of library playlist 1 whose media kind is movie)
end tell
set out to ""
repeat with i from 1 to count of ns
    set out to out & item i of ns & tab & item i of ys & linefeed
end repeat
return out
"""


class AppleTvError(Exception):
    pass


def archive_path(config_dir: Path, today: date) -> Path:
    return config_dir / "appletv" / f"owned-{today.isoformat()}.txt"


def _run_osascript() -> str:
    result = subprocess.run(["osascript", "-e", _SCRIPT], capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise AppleTvError(f"osascript failed: {result.stderr.strip() or result.returncode}")
    return result.stdout


def parse_export(text: str) -> list[OwnedTitle]:
    titles: list[OwnedTitle] = []
    for line in text.splitlines():
        if "\t" not in line:
            continue
        raw_title, _, raw_year = line.partition("\t")
        title = raw_title.strip()
        if not title:
            continue
        year = int(raw_year) if raw_year.strip().isdigit() and int(raw_year) > 0 else None
        titles.append(OwnedTitle(title, year))
    return titles


def fetch_owned(
    config_dir: Path,
    *,
    runner: Callable[[], str] | None = None,
    today: date | None = None,
) -> list[OwnedTitle]:
    raw = (runner or _run_osascript)()
    if not raw.strip():
        raise AppleTvError("TV app returned no movies — is the library empty or automation consent denied?")
    dest = archive_path(config_dir, today or date.today())
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(raw)
    return parse_export(raw)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_appletv.py -v`
Expected: PASS.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run mypy
git add src/movie_brain/infrastructure/appletv.py tests/unit/test_appletv.py
git commit -m "Apple TV adapter: osascript library export, archived raw before parsing"
```

---

### Task 4: Import use case — `application/owned.py` + BDD

**Files:**
- Create: `src/movie_brain/application/owned.py`, `tests/features/owned.feature`, `tests/step_defs/test_owned.py`

**Interfaces:**
- Consumes: `clean_apple_title`, `match_owned`, `norm_title`, `OwnedTitle` (Task 1); `mark_owned`, `create_film`, `films_for_matching`, `film_id_by_key`, `replace_unresolved_reviews`, `open_reviews` (Task 2 / existing); `fetch_owned`, `AppleTvError` (Task 3).
- Produces (Task 5 relies on these):
  - `AUTHORITY = "apple-tv"`
  - `OwnedReport(exit_code: int, total: int, matched: int, created: int, already_owned: int, review_open: int)` frozen dataclass
  - `import_owned(repo: Repository, config_dir: Path, today: date, *, fetch: Callable[[], list[OwnedTitle]] | None = None, log: Callable[[str], None] = _stderr) -> OwnedReport`

- [ ] **Step 1: Write the failing scenarios**

Create `tests/features/owned.feature`:

```gherkin
Feature: Apple TV owned films
  One AppleScript export, matched into the database; owned movies missing from
  the catalog become real films. Nothing is deleted, nothing is guessed.

  Scenario: An owned title marks its matching film
    Given the repository holds the film "Seven Samurai (1954)"
    And my Apple TV library has "Seven Samurai (Unrated)" (1954)
    When I import owned films
    Then "Seven Samurai (1954)" is owned
    And the repository holds 1 films
    And the owned report says 1 matched and 0 created

  Scenario: An owned title missing from the catalog becomes a real film
    Given my Apple TV library has "Step Brothers" (2008)
    When I import owned films
    Then the film "Step Brothers (2008)" exists with a guid
    And "Step Brothers (2008)" is owned
    And the owned report says 0 matched and 1 created

  Scenario: One year of drift still matches
    Given the repository holds the film "Alpha (1950)"
    And my Apple TV library has "Alpha" (1951)
    When I import owned films
    Then "Alpha (1950)" is owned
    And the repository holds 1 films

  Scenario: An ambiguous title goes to review, not a guess
    Given the repository holds the film "Twin (1978)"
    And the repository holds the film "Twin (1980)"
    And my Apple TV library has "Twin" (1979)
    When I import owned films
    Then the owned review queue has an "ambiguous-owned" entry
    And no film is owned

  Scenario: Re-running the import is idempotent
    Given my Apple TV library has "Step Brothers" (2008)
    When I import owned films
    And I import owned films
    Then the repository holds 1 films
    And the owned report says 1 already owned

  Scenario: Two editions of one movie own a single film
    Given my Apple TV library has "Blade Runner" (1982)
    And my Apple TV library has "Blade Runner (Director's Cut)" (1982)
    When I import owned films
    Then the repository holds 1 films
    And "Blade Runner (1982)" is owned

  Scenario: An export failure changes nothing
    Given my Apple TV library export fails
    When I import owned films
    Then the owned import exit code is 1
    And the repository holds 0 films
```

Create `tests/step_defs/test_owned.py`:

```python
from __future__ import annotations

import re
import sqlite3
from datetime import date

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.owned import AUTHORITY, import_owned
from movie_brain.domain.models import Film, OwnedTitle
from movie_brain.infrastructure.appletv import AppleTvError

scenarios("../features/owned.feature")

TODAY = date(2026, 8, 19)


@pytest.fixture
def ctx(repo, config_dir):
    return {"repo": repo, "config_dir": config_dir, "library": [], "fail": False, "report": None}


def _film(title_year: str) -> Film:
    m = re.match(r"(.+) \((\d{4})\)$", title_year)
    assert m
    return Film(m.group(1), int(m.group(2)), "Someone", f"https://c/{m.group(1).lower()}")


@given(parsers.parse('the repository holds the film "{title_year}"'))
def holds_film(ctx, title_year):
    ctx["repo"].upsert_film(_film(title_year))


@given(parsers.re(r'my Apple TV library has "(?P<title>[^"]+)" \((?P<year>\d+)\)'))
def library_has(ctx, title, year):
    ctx["library"].append(OwnedTitle(title, int(year)))


@given("my Apple TV library export fails")
def library_fails(ctx):
    ctx["fail"] = True


@when("I import owned films")
def run_import(ctx):
    def fetch():
        if ctx["fail"]:
            raise AppleTvError("boom")
        return list(ctx["library"])

    ctx["report"] = import_owned(ctx["repo"], ctx["config_dir"], TODAY, fetch=fetch, log=lambda m: None)


@then(parsers.parse('"{title_year}" is owned'))
def film_is_owned(ctx, title_year):
    fid = ctx["repo"].film_id_by_key(_film(title_year).key)
    assert fid in ctx["repo"].owned_film_ids()


@then(parsers.parse('the film "{title_year}" exists with a guid'))
def film_exists_with_guid(ctx, title_year):
    fid = ctx["repo"].film_id_by_key(_film(title_year).key)
    assert fid is not None
    conn = sqlite3.connect(ctx["repo"].db_path)
    guid = conn.execute("SELECT guid FROM films WHERE id = ?", (fid,)).fetchone()[0]
    conn.close()
    assert guid


@then(parsers.parse("the repository holds {n:d} films"))
def film_count(ctx, n):
    assert len(ctx["repo"].films_for_matching()) == n


@then(parsers.parse("the owned report says {m:d} matched and {c:d} created"))
def report_counts(ctx, m, c):
    assert (ctx["report"].matched, ctx["report"].created) == (m, c)


@then(parsers.parse("the owned report says {n:d} already owned"))
def report_already(ctx, n):
    assert ctx["report"].already_owned == n


@then(parsers.parse('the owned review queue has an "{reason}" entry'))
def review_entry(ctx, reason):
    assert any(r["reason"] == reason for r in ctx["repo"].open_reviews(AUTHORITY))


@then("no film is owned")
def nothing_owned(ctx):
    assert ctx["repo"].owned_film_ids() == set()


@then(parsers.parse("the owned import exit code is {code:d}"))
def import_exit(ctx, code):
    assert ctx["report"].exit_code == code
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/step_defs/test_owned.py -v`
Expected: FAIL — `ImportError` on `movie_brain.application.owned`.

- [ ] **Step 3: Implement**

Create `src/movie_brain/application/owned.py`:

```python
from __future__ import annotations

import sys
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from movie_brain.domain.matching import clean_apple_title, match_owned, norm_title
from movie_brain.domain.models import Film, OwnedTitle, ReviewEntry
from movie_brain.infrastructure import appletv
from movie_brain.infrastructure.database import Repository

AUTHORITY = "apple-tv"


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


@dataclass(frozen=True)
class OwnedReport:
    exit_code: int
    total: int
    matched: int
    created: int
    already_owned: int
    review_open: int


def import_owned(
    repo: Repository,
    config_dir: Path,
    today: date,
    *,
    fetch: Callable[[], list[OwnedTitle]] | None = None,
    log: Callable[[str], None] = _stderr,
) -> OwnedReport:
    """Mark or create every movie in the Apple TV library (idempotent, never deletes).

    Matched films are marked owned; misses become real films (generated guid) and
    are marked; ambiguous ties queue for review, never guessed. Ownership is
    permanent — a title vanishing from the library never unmarks anything.
    """
    try:
        titles = (fetch or (lambda: appletv.fetch_owned(config_dir, today=today)))()
    except appletv.AppleTvError as exc:
        log(f"Apple TV export failed, database unchanged: {exc}")
        return OwnedReport(1, 0, 0, 0, 0, 0)

    by_norm: dict[str, list[tuple[int, str, int | None]]] = defaultdict(list)
    for film_id, title, year, _ in repo.films_for_matching():
        by_norm[norm_title(title)].append((film_id, title, year))

    matched = created = already = 0
    reviews: list[ReviewEntry] = []
    for t in titles:
        cleaned = clean_apple_title(t.title)
        result = match_owned(cleaned, t.year, by_norm.get(norm_title(cleaned), []))
        if result.tied:
            detail = f"films {sorted(result.tied)} tie for {t.title!r} ({t.year})"
            reviews.append(ReviewEntry("ambiguous-owned", value=t.title, detail=detail))
            continue
        if result.winner is not None:
            film_id = result.winner
            matched += 1
        else:
            film = Film(cleaned, t.year, None, "")
            new_id = repo.create_film(film)
            if new_id is None:
                # Exact film_key collision: that IS the film (same title+year).
                film_id = repo.film_id_by_key(film.key) or 0
                matched += 1
            else:
                film_id = new_id
                by_norm[norm_title(cleaned)].append((film_id, cleaned, t.year))
                created += 1
        if not repo.mark_owned(film_id, today):
            already += 1

    repo.replace_unresolved_reviews(AUTHORITY, reviews, today)
    return OwnedReport(0, len(titles), matched, created, already, len(repo.open_reviews(AUTHORITY)))
```

Counting note: a second edition of an already-processed movie takes the matched path (it now matches the film created moments ago via `by_norm`) and increments `already` when `mark_owned` returns False — so the idempotency scenario's `already_owned == 1` and the two-editions scenario both fall out naturally.

- [ ] **Step 4: Run the owned suite, then everything**

Run: `uv run pytest tests/step_defs/test_owned.py -v && uv run pytest`
Expected: PASS.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run mypy
git add src/movie_brain/application/owned.py tests/features/owned.feature tests/step_defs/test_owned.py
git commit -m "Owned import: match-or-create against the Apple TV library, ties to review"
```

---

### Task 5: CLI — `movie-brain owned import`

**Files:**
- Modify: `src/movie_brain/cli.py`
- Test: `tests/unit/test_cli.py`

**Interfaces:**
- Consumes: `import_owned`, `OwnedReport` (Task 4).
- Produces: `movie-brain owned import` verb.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_cli.py`:

```python
def test_owned_import_reports_and_propagates_exit(config_dir, monkeypatch):
    import movie_brain.cli as cli
    from movie_brain.application.owned import OwnedReport

    monkeypatch.setattr(cli, "import_owned", lambda repo, cfg, today, **kw: OwnedReport(0, 870, 600, 250, 20, 3))
    r = runner.invoke(app, ["owned", "import"])
    assert r.exit_code == 0
    assert "870" in r.output and "600" in r.output and "250" in r.output

    monkeypatch.setattr(cli, "import_owned", lambda repo, cfg, today, **kw: OwnedReport(1, 0, 0, 0, 0, 0))
    r = runner.invoke(app, ["owned", "import"])
    assert r.exit_code == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_cli.py -k owned -v`
Expected: FAIL — no such command.

- [ ] **Step 3: Implement**

In `cli.py`: import `from movie_brain.application.owned import import_owned`; register the sub-app next to the others:

```python
owned_app = typer.Typer(help="Apple TV owned films: import the library, mark ownership.")
app.add_typer(owned_app, name="owned")
```

And the command (matching the file's existing style):

```python
@owned_app.command("import")
def owned_import() -> None:
    """Export the Apple TV library via AppleScript and mark/create owned films."""
    cfg = load_config()
    cfg.config_dir.mkdir(parents=True, exist_ok=True)
    report = import_owned(_repo(), cfg.config_dir, date.today())
    console.print(
        f"owned: {report.total} · matched: {report.matched} · created: {report.created} · "
        f"already: {report.already_owned} · review: {report.review_open}"
    )
    raise typer.Exit(report.exit_code)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_cli.py -v`
Expected: PASS.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run mypy
git add src/movie_brain/cli.py tests/unit/test_cli.py
git commit -m "CLI: movie-brain owned import"
```

---

### Task 6: UI — badge, drawer link, Owned chip, counts

**Files:**
- Modify: `src/movie_brain/domain/filters.py`, `src/movie_brain/web/static/app.js`, `src/movie_brain/web/templates/index.html`, `tests/web/conftest.py`
- Test: `tests/web/test_api.py`, `tests/web/test_dashboard.py`, `tests/unit/test_filters.py`

**Interfaces:**
- Consumes: `FilmView.owned` in film JSON (Task 2); `repo.mark_owned` for seeding.
- Produces: `owned` chip in `_PREDICATES`/`CHIP_PREDICATES`/chip row (lockstep); `badge-owned` span in the title cell; drawer "Owned on Apple TV ↗" line; `#count-owned` in the header.

- [ ] **Step 1: Seed and write failing tests**

`tests/web/conftest.py` — at the end of `seed(...)` (Alpha is English, so it stays visible under the default language filter):

```python
    # Alpha is the one owned film — English keeps it visible in the default view.
    repo.mark_owned(ids["alpha (1950)"], TODAY)
```

Append to `tests/unit/test_filters.py` (mirror its existing FilmView-construction style):

```python
def test_owned_chip_matches_owned_views():
    from movie_brain.domain.filters import matches

    owned = _view(owned=True)
    assert matches(owned, ["owned"], date(2026, 8, 19)) is True
    assert matches(_view(owned=False), ["owned"], date(2026, 8, 19)) is False
```

(If that file has no `_view` helper, construct `FilmView` the way its other tests do, overriding `owned`.)

`tests/web/test_api.py`:

```python
def test_films_expose_owned(client):
    films = {f["title"]: f for f in client.get("/api/films").get_json()}
    assert films["Alpha"]["owned"] is True
    assert films["Bravo"]["owned"] is False
```

`tests/web/test_dashboard.py`:

```python
def test_owned_badge_and_chip(dash):
    row = dash.locator("tr[data-id]", has_text="Alpha")
    assert row.locator(".badge-owned").count() == 1
    dash.click('[data-chip="owned"]')
    dash.wait_for_selector("#films tbody[data-count='1']")
    assert dash.locator("tr[data-id]").count() == 1


def test_drawer_shows_owned_link(dash):
    dash.locator("tr[data-id]", has_text="Alpha").click()
    link = dash.locator("#drawer-body a.owned-link")
    link.wait_for()
    assert "tv.apple.com/search" in link.get_attribute("href")
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_filters.py tests/web -v`
Expected: filters test FAILS (`owned` not a chip); API test PASSES already (Task 2 exposed the field — confirm it does); Playwright tests FAIL.

- [ ] **Step 3: Implement**

`domain/filters.py` — add to `_PREDICATES` (before the closing brace, keeping insertion order = chip order):

```python
    "owned": lambda v, _: v.owned,
```

`index.html`:
- Chip row, after the watchlist chip: `<button class="chip" data-chip="owned">Owned</button>`
- Summary spans, after `count-discovery`: `<span><b id="count-owned">–</b> owned</span>`

`app.js`:
- `CHIP_PREDICATES`: `owned: (f) => f.owned,` (same position as in `_PREDICATES`).
- `renderCounts`: `$('#count-owned').textContent = state.films.filter((x) => x.owned).length;` (all films, not criterion-scoped — matches `summary()`).
- `rowHtml` title cell: after the departed badge concatenation, add
  `+ (f.owned ? ' <span class="badge-owned" title="Owned on Apple TV">owned</span>' : '')`.
- `detailHtml`: alongside the Criterion/Metacritic links add
  `${d.owned ? ` <a class="criterion owned-link" href="https://tv.apple.com/search?term=${encodeURIComponent(d.title)}" target="_blank" rel="noopener">Owned on Apple TV ↗</a>` : ''}`.
- CSS: wherever `.badge-gone` is styled (index.html `<style>` block or the css file), add `.badge-owned` with the same shape but a distinct color (e.g. the accent/blue used elsewhere), so the two badges are visually distinct.

Update the existing chip-labels/order test (it gained "All films" in Phase 5) to include "Owned" at the end.

- [ ] **Step 4: Run the web suite + full gate**

Run: `uv run pytest`
Expected: PASS — adjust any "Showing X of Y" or summary-dict assertions ONLY if the seed change moved them (marking Alpha owned adds no film, so counts should be stable except the new owned ones).

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run mypy
git add -A src tests
git commit -m "Owned in the UI: title badge, drawer Apple TV link, Owned chip (lockstep), counts"
```

---

### Task 7: Docs + gate

**Files:**
- Modify: `CLAUDE.md`, `docs/multiple-movie-services.md`

- [ ] **Step 1: Update CLAUDE.md**

- Commands block: `uv run movie-brain owned import` — "AppleScript export of the Apple TV library → mark/create owned films (macOS, never in sync)".
- Rules: `owned` is possession data on the watchlist pattern — `owned import` is the only writer, rows are permanent, no `listings`/transition interaction; ambiguous matches → `match_review` authority `apple-tv`; unmatched owned titles become real films (guid).
- Data section: Apple TV archive at `<config_dir>/appletv/owned-<date>.txt`.

- [ ] **Step 2: Update the roadmap**

In `docs/multiple-movie-services.md`: mark the ownership-model spike decided — "Decision (2026-08-23): dedicated `owned` table (watchlist pattern), AppleScript export as acquisition (870 cloud purchases visible); privacy-portal export remains the completeness backstop" — in the Data model section's ownership bullets, and check off the iTunes-export spike with the AppleScript answer.

- [ ] **Step 3: Full gate**

Run: `uv run pytest && uv run ruff check . && uv run mypy`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md docs
git commit -m "Docs: Apple TV owned films landed; ownership model decided"
```

---

## Self-review notes

- Spec coverage: §1 acquisition → Task 3; §2 matching/creation → Tasks 1+4; §3 data model → Task 2; §4 CLI → Task 5; §5 UI → Task 6; error handling embedded; landing checklist → Task 7 (migration applies on first live run with auto-backup).
- Type consistency: `OwnedTitle`/`match_owned`/`fetch_owned`/`mark_owned`/`import_owned` signatures used identically across Tasks 1–5; `MatchResult` reused from existing code.
- The real-osascript path (`_run_osascript`) is untested by design (no TV app in CI) — the `runner` seam covers everything else; the live UAT after merge exercises it.
