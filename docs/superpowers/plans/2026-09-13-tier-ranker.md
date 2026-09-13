# Tier Ranker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `/rank` page that places every owned film into one of five tiers by side-by-side comparison against five anchor films, with a durable `unseen` bucket, and saves the result as a tied-rank `film_list`.

**Architecture:** Pure placement logic in `domain/rank.py` (search table, seed mapping, queue order, tie labels); session state in six new tables (migration 022) behind `Repository` methods; one use-case module `application/rank.py` that derives the current pair from the click log on every request; nine Flask routes and a second page (`rank.html`, `rank.js`, `rank.css`) that never loads `app.js`. Dashboard grows a `Rank` link and an `Unseen` drawer toggle.

**Tech Stack:** Python 3.12, Flask, SQLite, Typer, pytest + pytest-bdd + Playwright, vanilla JS. Run everything with `uv run`.

**Spec:** `docs/superpowers/specs/2026-09-13-tier-ranker-design.md` — the plan argues from the spec; read both.

## Global Constraints

- Tiers: exactly `5`; seed mapping `10→1, 9→2, 8→3, 7→4, 0–6→5`; tier middles `1:10, 2:9, 3:8, 4:7, 5:5` (spec §3).
- Search table is the nine rows of spec §4.1; any other verdict sequence raises.
- `my_ratings` is never written by this feature (D2). `films`, keying, matching and sync are untouched.
- The queue is derived at request time, never stored (§4.3). No client-side session state (§4.2).
- Verdict vocabulary on the wire and in the log: `better` / `worse`, meaning the CANDIDATE is better/worse than the anchor. There is no `same` (D9).
- Output list slug for source `owned` is `my-owned-tiers`, default name `My owned films, tiered`, `curator = 'me'`, `ordered = 1`, trust never written (§7).
- `lists import` refuses a ranker slug (exit 2); `POST /api/rank/save` refuses (409) when `lists/<slug>.tsv` exists (§7).
- Two deliberate concretisations of the spec, both recorded here so the spec's reader is not surprised: (a) §4.4's "tiny ordered action log" is ONE nullable JSON column, `rank_session.last_action`, giving one level of undo; (b) `rank_placement.how` gains a third value `anchor`, for a film swapped in as a tier's anchor while unplaced (the only way an empty tier can get an anchor at all, §4.5). Update the spec's §3 SQL comment for both in Task 8.
- Markdown written by this plan (`CLAUDE.md`, `docs/backlog.md`, `.claude/rules/lists.md`, the spec) is never hard-wrapped: one paragraph per line.
- Every task ends green on `uv run pytest -q` (the suite is ~40 s), `uv run ruff check .` and `uv run mypy`. Commit messages: one line, the "why".

---

## File structure

| File | Responsibility |
|---|---|
| `migrations/022_tier_ranker.sql` | The six tables (spec §3) plus `rank_session.last_action`. |
| `src/movie_brain/domain/rank.py` | Pure: constants, `tier_for_score`, `next_step`, `propose_anchors`, `order_queue`, `tiered_entries`, slug registry. |
| `src/movie_brain/domain/models.py` | `FilmView.unseen`; `RankSession`, `SeedFilm`, `Placed`, `TieredEntry` dataclasses. |
| `src/movie_brain/infrastructure/database.py` | `unseen` methods, rank-session methods, `replace_list_entries`, `merge_film` moves, `FilmView.unseen` wiring. |
| `src/movie_brain/infrastructure/listfile.py` | `LISTS_DIR` constant (where `lists/<slug>.tsv` lives). |
| `src/movie_brain/application/rank.py` | The use case: proposal, start, state, verdict, pass, undo, swap, save. `RankError(status, message)`. |
| `src/movie_brain/web/app.py` | `/rank`, the eight `/api/rank/*` routes, `PUT /api/films/<id>/unseen`. |
| `src/movie_brain/web/templates/rank.html`, `static/rank.js`, `static/rank.css` | The page. |
| `src/movie_brain/web/templates/index.html`, `static/app.js`, `static/app.css` | `Rank` header link; drawer `Unseen` toggle. |
| `src/movie_brain/cli.py` | `lists import` slug guard. |
| `tests/unit/test_rank.py` | Domain tests. |
| `tests/unit/test_rank_repository.py` | Repository tests (unseen, sessions, merge, replace entries). |
| `tests/features/rank.feature`, `tests/step_defs/test_rank.py` | Use-case scenarios. |
| `tests/web/test_api.py` | Route tests (appended). |
| `tests/web/test_rank_page.py` | Playwright flow on its own seeded server. |
| `tests/web/test_dashboard.py` | Header link + drawer toggle (appended). |
| `tests/unit/test_cli.py` | `lists import` guard (appended). |

---

### Task 1: Migration 022 and the `unseen` fact

**Files:**
- Create: `migrations/022_tier_ranker.sql`
- Modify: `src/movie_brain/domain/models.py` (FilmView, after `needs_revisit`/`revisit_note` ~line 332)
- Modify: `src/movie_brain/infrastructure/database.py` (`_ONE_ROW_TABLES` line 184; helpers near `_revisit_by_film` line 471; `_row_to_view` line 506; `list_views` ~2790; `get_view` ~2812; `merge_film` ~2510; new methods after `revisits` ~2465)
- Test: `tests/unit/test_rank_repository.py`

**Interfaces:**
- Produces: `Repository.unseen_film_ids() -> set[int]`; `Repository.set_unseen(film_id: int, unseen: bool, today: date, note: str | None = None) -> bool | None` (None = no such film; deletes the film's `rank_placement` rows in every session when `unseen=True`, spec §4.6); `FilmView.unseen: bool`.

- [ ] **Step 1: Write the migration**

```sql
-- Tier ranker (spec docs/superpowers/specs/2026-09-13-tier-ranker-design.md §3). Six tables:
-- a session per source, its five anchors, one placement per film (the whole result), an
-- append-only click log that is never read to compute a tier, a "not now" deferral, and the
-- durable `unseen` bucket on the watchlist pattern (drawer toggle + the page's pass are its
-- only writers). `last_action` is the one-level undo record (§4.4). `how = 'anchor'` marks a
-- film swapped in as an anchor while unplaced (§4.5).
BEGIN;
CREATE TABLE rank_session (
    id          INTEGER PRIMARY KEY,
    source      TEXT    NOT NULL,
    seed        INTEGER NOT NULL,
    started_on  TEXT    NOT NULL,
    finished_on TEXT,
    list_slug   TEXT REFERENCES film_list(slug),
    last_action TEXT
);
CREATE UNIQUE INDEX rank_session_open ON rank_session(source) WHERE finished_on IS NULL;

CREATE TABLE rank_anchor (
    session_id INTEGER NOT NULL REFERENCES rank_session(id),
    tier       INTEGER NOT NULL CHECK (tier BETWEEN 1 AND 5),
    film_id    INTEGER REFERENCES films(id),
    set_on     TEXT    NOT NULL,
    PRIMARY KEY (session_id, tier)
);

CREATE TABLE rank_placement (
    session_id INTEGER NOT NULL REFERENCES rank_session(id),
    film_id    INTEGER NOT NULL REFERENCES films(id),
    tier       INTEGER NOT NULL CHECK (tier BETWEEN 1 AND 5),
    how        TEXT    NOT NULL CHECK (how IN ('seed', 'compared', 'anchor')),
    placed_on  TEXT    NOT NULL,
    PRIMARY KEY (session_id, film_id)
);

CREATE TABLE rank_comparison (
    id              INTEGER PRIMARY KEY,
    session_id      INTEGER NOT NULL REFERENCES rank_session(id),
    film_id         INTEGER NOT NULL REFERENCES films(id),
    anchor_film_id  INTEGER NOT NULL REFERENCES films(id),
    anchor_tier     INTEGER NOT NULL,
    verdict         TEXT    NOT NULL CHECK (verdict IN ('better', 'worse')),
    decided_on      TEXT    NOT NULL
);
CREATE INDEX rank_comparison_film ON rank_comparison(session_id, film_id, id);

CREATE TABLE rank_deferral (
    session_id  INTEGER NOT NULL REFERENCES rank_session(id),
    film_id     INTEGER NOT NULL REFERENCES films(id),
    deferred_on TEXT    NOT NULL,
    PRIMARY KEY (session_id, film_id)
);

CREATE TABLE unseen (
    film_id   INTEGER PRIMARY KEY REFERENCES films(id),
    marked_on TEXT NOT NULL,
    note      TEXT
);
INSERT INTO schema_version (version) VALUES (22);
COMMIT;
```

- [ ] **Step 2: Write the failing repository tests**

`tests/unit/test_rank_repository.py`:

```python
from __future__ import annotations

from datetime import date

from movie_brain.domain.models import Film

D = date(2026, 9, 13)


def _film(repo, title, year):
    fid = repo.create_film(Film(title, year, "Dir", ""))
    assert fid is not None
    return fid


def test_set_unseen_marks_unmarks_and_reports_missing(repo):
    a = _film(repo, "Alpha", 1950)
    assert repo.set_unseen(a, True, D, note="never saw it") is True
    assert repo.unseen_film_ids() == {a}
    assert repo.get_view(a, D).unseen is True
    assert repo.set_unseen(a, True, D) is True  # idempotent
    assert repo.set_unseen(a, False, D) is False
    assert repo.unseen_film_ids() == set()
    assert repo.set_unseen(999, True, D) is None


def test_merge_moves_unseen_survivor_wins(repo):
    a = _film(repo, "Alpha", 1950)
    b = _film(repo, "Alpha", 1951)
    repo.set_unseen(b, True, D)
    repo.merge_film(b, a, D)
    assert repo.unseen_film_ids() == {a}
    c = _film(repo, "Beta", 1960)
    d = _film(repo, "Beta", 1961)
    repo.set_unseen(c, True, D, note="keep")
    repo.set_unseen(d, True, D, note="drop")
    report = repo.merge_film(d, c, D)
    assert report.dropped.get("unseen") == 1
    assert repo.unseen_film_ids() == {a, c}
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/unit/test_rank_repository.py -q`
Expected: FAIL — `AttributeError: 'Repository' object has no attribute 'set_unseen'`.

- [ ] **Step 4: Implement**

`models.py`, inside `FilmView` after `revisit_note`:

```python
    unseen: bool = False  # the ranker's durable pass bucket (spec D5); drawer toggle + the /rank page are the only writers
```

`database.py`:

```python
_ONE_ROW_TABLES = ("omdb", "tmdb", "my_ratings", "watchlist", "owned", "film_embedding", "unseen")  # film_id PRIMARY KEY tables
```

Helper beside `_owned_ids`:

```python
def _unseen_ids(c: sqlite3.Connection) -> set[int]:
    return {int(r["film_id"]) for r in c.execute("SELECT film_id FROM unseen")}
```

`_row_to_view`: add keyword parameter `unseen: bool = False` after `owned` and pass `unseen=unseen` into the `FilmView(...)` constructor. In `list_views`, read `un = _unseen_ids(c)` beside `ow = _owned_ids(c)` and pass `unseen=r["id"] in un`; in `get_view` pass `unseen=row["id"] in _unseen_ids(c)`.

In `merge_film`'s `kept` branch add:

```python
                    elif table == "unseen":
                        kept[table] = {"marked_on": loser_row["marked_on"], "note": loser_row["note"]}
```

New section after `revisits`:

```python
    # unseen (the ranker's pass bucket, spec D5 / §4.6) ----------------------
    def unseen_film_ids(self) -> set[int]:
        with self._conn() as c:
            return _unseen_ids(c)

    def set_unseen(self, film_id: int, unseen: bool, today: date, note: str | None = None) -> bool | None:
        """Idempotent set/clear. None when the film does not exist. Marking a film unseen also
        deletes its `rank_placement` rows in EVERY session (§4.6): an unseen film is out of any
        later save, and unmarking returns it to the queue, never to its old tier."""
        with self._conn() as c:
            if c.execute("SELECT 1 FROM films WHERE id = ?", (film_id,)).fetchone() is None:
                return None
            if unseen:
                c.execute(
                    "INSERT INTO unseen (film_id, marked_on, note) VALUES (?, ?, ?) "
                    "ON CONFLICT(film_id) DO UPDATE SET note = COALESCE(excluded.note, unseen.note)",
                    (film_id, today.isoformat(), note),
                )
                c.execute("DELETE FROM rank_placement WHERE film_id = ?", (film_id,))
                return True
            c.execute("DELETE FROM unseen WHERE film_id = ?", (film_id,))
            return False
```

- [ ] **Step 5: Run the tests and the whole suite**

Run: `uv run pytest tests/unit/test_rank_repository.py -q && uv run pytest -q -x --ignore=tests/web/test_dashboard.py`
Expected: PASS. (A fresh DB bootstraps every migration on open, so 022 is applied in tests automatically.)

- [ ] **Step 6: Lint, types, commit**

```bash
uv run ruff check . && uv run mypy
git add migrations/022_tier_ranker.sql src/movie_brain/domain/models.py src/movie_brain/infrastructure/database.py tests/unit/test_rank_repository.py
git commit -m "the ranker needs its six tables and a durable unseen bucket before it can place anything"
```

---

### Task 2: The pure placement logic (`domain/rank.py`)

**Files:**
- Create: `src/movie_brain/domain/rank.py`
- Modify: `src/movie_brain/domain/models.py` (append four dataclasses)
- Test: `tests/unit/test_rank.py`

**Interfaces:**
- Produces (all in `domain/rank.py`): `TIERS = 5`; `TIER_MIDDLE: dict[int, int]`; `RANKER_SLUGS = {"owned": "my-owned-tiers"}`; `RANKER_LIST_SLUGS: frozenset[str]`; `DEFAULT_LIST_NAME = {"owned": "My owned films, tiered"}`; `VERDICTS = ("better", "worse")`; `tier_for_score(score: int) -> int`; `Ask(tier)`, `Place(tier)` frozen dataclasses; `next_step(verdicts: Sequence[str]) -> Ask | Place`; `propose_anchors(seeded: Iterable[SeedFilm]) -> dict[int, SeedFilm | None]`; `queue_key(seed: int, film_id: int) -> int`; `order_queue(seed: int, film_ids: Iterable[int], deferred: Mapping[int, str]) -> list[int]`; `tiered_entries(placed: Iterable[Placed]) -> list[TieredEntry]`.
- Produces (in `models.py`): `SeedFilm(film_id: int, score: int, imdb: float | None, title: str, year: int | None)`; `Placed(film_id: int, tier: int, title: str, director: str | None)`; `TieredEntry(rank: int, film_id: int, title: str, director: str | None, rank_label: str | None)`; `RankSession(id: int, source: str, seed: int, started_on: str, finished_on: str | None, list_slug: str | None, last_action: dict[str, object] | None)`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_rank.py`:

```python
from __future__ import annotations

import pytest

from movie_brain.domain.models import Placed, SeedFilm
from movie_brain.domain.rank import (
    RANKER_LIST_SLUGS,
    TIERS,
    Ask,
    Place,
    next_step,
    order_queue,
    propose_anchors,
    queue_key,
    tier_for_score,
    tiered_entries,
)


@pytest.mark.parametrize("score,tier", [(10, 1), (9, 2), (8, 3), (7, 4), (6, 5), (4, 5), (0, 5)])
def test_seed_mapping(score, tier):
    assert tier_for_score(score) == tier


@pytest.mark.parametrize(
    "verdicts,expected",
    [
        ((), Ask(3)),
        (("better",), Ask(2)),
        (("better", "better"), Place(1)),
        (("better", "worse"), Place(2)),
        (("worse",), Ask(4)),
        (("worse", "better"), Place(3)),
        (("worse", "worse"), Ask(5)),
        (("worse", "worse", "better"), Place(4)),
        (("worse", "worse", "worse"), Place(5)),
    ],
)
def test_search_table(verdicts, expected):
    assert next_step(list(verdicts)) == expected


@pytest.mark.parametrize("bad", [("same",), ("better", "better", "better"), ("worse", "worse", "worse", "worse")])
def test_illegal_sequences_raise(bad):
    with pytest.raises(ValueError):
        next_step(list(bad))


def test_propose_anchors_picks_nearest_middle_then_imdb_then_title():
    seeded = [
        SeedFilm(1, 10, 8.0, "Zed", 1950),
        SeedFilm(2, 10, 9.0, "Alpha", 1951),  # tier 1: both score 10, imdb breaks the tie
        SeedFilm(3, 6, 7.0, "Six", 1960),
        SeedFilm(4, 4, 7.0, "Four", 1961),  # tier 5: middle is 5, both distance 1, imdb ties, title breaks it
        SeedFilm(5, 8, None, "Eight", 1970),
    ]
    got = propose_anchors(seeded)
    assert got[1].film_id == 2
    assert got[3].film_id == 5
    assert got[5].film_id == 4
    assert got[2] is None and got[4] is None
    assert set(got) == set(range(1, TIERS + 1))


def test_queue_key_is_stable_per_seed_and_film():
    assert queue_key(7, 10) == queue_key(7, 10)
    assert queue_key(7, 10) != queue_key(8, 10)


def test_order_queue_shuffles_by_key_and_puts_deferred_last():
    ids = [1, 2, 3, 4, 5]
    base = order_queue(42, ids, {})
    assert sorted(base) == ids
    assert base == sorted(ids, key=lambda i: (queue_key(42, i), i))
    deferred = order_queue(42, ids, {base[0]: "2026-09-13", base[1]: "2026-09-12"})
    assert deferred[-2:] == [base[1], base[0]]  # older deferral first
    assert deferred[:3] == base[2:]


def test_order_queue_is_stable_when_a_film_joins():
    before = order_queue(42, [1, 2, 3], {})
    after = order_queue(42, [1, 2, 3, 4], {})
    assert [i for i in after if i != 4] == before


def test_tiered_entries_label_ties_and_leave_singletons_bare():
    placed = [
        Placed(10, 2, "Bravo", "B"),
        Placed(11, 1, "Zulu", "Z"),
        Placed(12, 1, "Alpha", "A"),
        Placed(13, 5, "Solo", None),
    ]
    got = tiered_entries(placed)
    assert [(e.rank, e.film_id, e.rank_label) for e in got] == [
        (1, 12, "=1"),
        (2, 11, "=1"),
        (3, 10, None),
        (4, 13, None),
    ]
    assert got[0].title == "Alpha" and got[0].director == "A"


def test_ranker_owns_the_owned_slug():
    assert "my-owned-tiers" in RANKER_LIST_SLUGS
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_rank.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'movie_brain.domain.rank'`.

- [ ] **Step 3: Implement**

Append to `models.py`:

```python
@dataclass(frozen=True)
class SeedFilm:
    """An owned film carrying a rating: the ranker's seed (spec D2) and anchor pool (D4)."""

    film_id: int
    score: int
    imdb: float | None
    title: str
    year: int | None


@dataclass(frozen=True)
class Placed:
    """One placement, as the save reads it (spec §7)."""

    film_id: int
    tier: int
    title: str
    director: str | None


@dataclass(frozen=True)
class TieredEntry:
    """One line of the saved list: `rank` is line order, `rank_label` the tie marker or None."""

    rank: int
    film_id: int
    title: str
    director: str | None
    rank_label: str | None


@dataclass(frozen=True)
class RankSession:
    id: int
    source: str
    seed: int
    started_on: str
    finished_on: str | None
    list_slug: str | None
    last_action: dict[str, object] | None  # the one-level undo record (spec §4.4)
```

`src/movie_brain/domain/rank.py`:

```python
"""Tier ranker: the pure placement logic (spec docs/superpowers/specs/2026-09-13-tier-ranker-design.md).

Five tiers, each defined by one anchor film; a candidate is placed by a binary search over the
anchors (§4.1). Everything here is a function of values the caller passes in — no I/O, no clock.
"""

from __future__ import annotations

import zlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from .models import Placed, SeedFilm, TieredEntry

TIERS = 5
# The score each tier is "about" — the anchor proposal picks the seeded film nearest it (§4.5).
TIER_MIDDLE: dict[int, int] = {1: 10, 2: 9, 3: 8, 4: 7, 5: 5}
VERDICTS = ("better", "worse")  # the CANDIDATE is better/worse than the anchor (D9: no `same`)

# The ranker's own lists: not backed by lists/<slug>.tsv, refused by `lists import` (§7).
RANKER_SLUGS: dict[str, str] = {"owned": "my-owned-tiers"}
RANKER_LIST_SLUGS: frozenset[str] = frozenset(RANKER_SLUGS.values())
DEFAULT_LIST_NAME: dict[str, str] = {"owned": "My owned films, tiered"}


def tier_for_score(score: int) -> int:
    """Seed mapping (spec §3): 10→1, 9→2, 8→3, 7→4, everything 6 and below→5."""
    if score >= 10:
        return 1
    if score == 9:
        return 2
    if score == 8:
        return 3
    if score == 7:
        return 4
    return 5


@dataclass(frozen=True)
class Ask:
    tier: int


@dataclass(frozen=True)
class Place:
    tier: int


_STEPS: dict[tuple[str, ...], Ask | Place] = {
    (): Ask(3),
    ("better",): Ask(2),
    ("better", "better"): Place(1),
    ("better", "worse"): Place(2),
    ("worse",): Ask(4),
    ("worse", "better"): Place(3),
    ("worse", "worse"): Ask(5),
    ("worse", "worse", "better"): Place(4),
    ("worse", "worse", "worse"): Place(5),
}


def next_step(verdicts: Sequence[str]) -> Ask | Place:
    """The search table (spec §4.1). Any sequence outside it is a corrupt log and raises."""
    try:
        return _STEPS[tuple(verdicts)]
    except KeyError:
        raise ValueError(f"illegal verdict sequence {list(verdicts)!r}") from None


def propose_anchors(seeded: Iterable[SeedFilm]) -> dict[int, SeedFilm | None]:
    """One proposed anchor per tier (D4): the seeded film whose score is nearest the tier's
    middle, ties broken by IMDb rating desc then title. None for a tier with no seeded film."""
    by_tier: dict[int, list[SeedFilm]] = {t: [] for t in range(1, TIERS + 1)}
    for f in seeded:
        by_tier[tier_for_score(f.score)].append(f)
    out: dict[int, SeedFilm | None] = {}
    for tier, films in by_tier.items():
        if not films:
            out[tier] = None
            continue
        out[tier] = min(
            films, key=lambda f: (abs(f.score - TIER_MIDDLE[tier]), -(f.imdb if f.imdb is not None else -1.0), f.title)
        )
    return out


def queue_key(seed: int, film_id: int) -> int:
    """A film's fixed position in a session's shuffle. Keyed per film (not a shuffle of the
    whole list) so a film bought mid-session slots in without reordering everything (§4.3)."""
    return zlib.crc32(f"{seed}:{film_id}".encode())


def order_queue(seed: int, film_ids: Iterable[int], deferred: Mapping[int, str]) -> list[int]:
    """Unplaced films in seeded-shuffle order, deferred ones last by (deferred_on, film_id)."""
    ids = list(film_ids)
    fresh = sorted((i for i in ids if i not in deferred), key=lambda i: (queue_key(seed, i), i))
    later = sorted((i for i in ids if i in deferred), key=lambda i: (deferred[i], i))
    return fresh + later


def tiered_entries(placed: Iterable[Placed]) -> list[TieredEntry]:
    """The saved list's lines (spec §7): tier asc then title; `=<first line>` labels a tier of
    two or more, a tier of one stays bare."""
    ordered = sorted(placed, key=lambda p: (p.tier, p.title.casefold(), p.film_id))
    sizes: dict[int, int] = {}
    for p in ordered:
        sizes[p.tier] = sizes.get(p.tier, 0) + 1
    out: list[TieredEntry] = []
    first_line: dict[int, int] = {}
    for line, p in enumerate(ordered, start=1):
        first_line.setdefault(p.tier, line)
        label = f"={first_line[p.tier]}" if sizes[p.tier] > 1 else None
        out.append(TieredEntry(line, p.film_id, p.title, p.director, label))
    return out
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/unit/test_rank.py -q`
Expected: PASS (17 tests).

- [ ] **Step 5: Lint, types, commit**

```bash
uv run ruff check . && uv run mypy
git add src/movie_brain/domain/rank.py src/movie_brain/domain/models.py tests/unit/test_rank.py
git commit -m "placement is a lookup in a nine-row table, so the search lives in the domain with no clock and no I/O"
```

---

### Task 3: Repository session methods

**Files:**
- Modify: `src/movie_brain/infrastructure/database.py` (new section after the `unseen` one from Task 1; `merge_film`; `upsert_film_list` region for `replace_list_entries`)
- Modify: `src/movie_brain/infrastructure/listfile.py` (append `LISTS_DIR`)
- Test: `tests/unit/test_rank_repository.py` (append)

**Interfaces:**
- Consumes: `RankSession`, `SeedFilm`, `TieredEntry` from Task 2.
- Produces on `Repository`:
  - `owned_seed_films() -> list[SeedFilm]` — owned ∩ `my_ratings`, not unseen, not disposed.
  - `film_facts(film_ids: Iterable[int]) -> dict[int, tuple[str, int | None, str | None]]` — `(title, year, director)`.
  - `open_rank_session(source: str) -> RankSession | None`
  - `create_rank_session(source, seed, anchors: Mapping[int, int], placements: Mapping[int, int], today) -> int` — writes the session, five anchor rows (a missing tier writes `film_id NULL`), one `seed` placement per entry of `placements` (film_id → tier).
  - `rank_anchors(session_id) -> dict[int, int | None]`
  - `set_rank_anchor(session_id, tier, film_id: int | None, today) -> None`
  - `rank_placements(session_id) -> dict[int, tuple[int, str]]` — film_id → (tier, how)
  - `place_film(session_id, film_id, tier, how, today) -> None` (INSERT OR REPLACE)
  - `unplace_film(session_id, film_id) -> None`
  - `append_comparison(session_id, film_id, anchor_film_id, anchor_tier, verdict, today) -> int`
  - `verdicts_for(session_id, film_id) -> list[str]` (by `id`)
  - `delete_comparison(comparison_id: int) -> None`
  - `defer_film(session_id, film_id, stamp: str) -> None`; `undefer_film(session_id, film_id) -> None`; `rank_deferrals(session_id) -> dict[int, str]`
  - `set_last_action(session_id, action: dict[str, object] | None) -> None`
  - `set_rank_session_list(session_id, slug) -> None`
  - `replace_list_entries(slug: str, entries: Iterable[TieredEntry]) -> None` — DELETE the slug's rows, INSERT each with `film_id` set.
- Produces in `listfile.py`: `LISTS_DIR = Path(__file__).resolve().parents[3] / "lists"`.

- [ ] **Step 1: Write the failing tests** (append to `tests/unit/test_rank_repository.py`)

```python
from movie_brain.domain.models import ListMeta, OmdbRating, TieredEntry


def _owned_rated(repo, title, year, score, imdb=None):
    fid = _film(repo, title, year)
    repo.mark_owned(fid, D)
    repo.set_rating(fid, score, D)
    if imdb is not None:
        repo.upsert_omdb(fid, OmdbRating(imdb, None, True, "English", '{"Title":"x"}'), D)
    return fid


def test_owned_seed_films_is_owned_and_rated_minus_unseen(repo):
    a = _owned_rated(repo, "Alpha", 1950, 10, imdb=8.1)
    b = _owned_rated(repo, "Bravo", 1960, 8)
    _film(repo, "Charlie", 1970)  # neither owned nor rated
    c = _owned_rated(repo, "Delta", 1980, 7)
    repo.set_unseen(c, True, D)
    got = {s.film_id: s for s in repo.owned_seed_films()}
    assert set(got) == {a, b}
    assert got[a].score == 10 and got[a].imdb == 8.1 and got[a].title == "Alpha" and got[a].year == 1950
    assert got[b].imdb is None


def test_session_round_trip(repo):
    ids = [_owned_rated(repo, t, 1950 + i, 10 - i) for i, t in enumerate(["A", "B", "C", "D", "E"])]
    assert repo.open_rank_session("owned") is None
    sid = repo.create_rank_session("owned", 42, {t: ids[t - 1] for t in range(1, 6)}, {ids[0]: 1, ids[1]: 2}, D)
    s = repo.open_rank_session("owned")
    assert s is not None and s.id == sid and s.seed == 42 and s.last_action is None and s.list_slug is None
    assert repo.rank_anchors(sid) == {t: ids[t - 1] for t in range(1, 6)}
    assert repo.rank_placements(sid) == {ids[0]: (1, "seed"), ids[1]: (2, "seed")}
    repo.set_rank_anchor(sid, 3, None, D)
    assert repo.rank_anchors(sid)[3] is None
    x = _film(repo, "X", 2000)
    cid = repo.append_comparison(sid, x, ids[2], 3, "worse", D)
    repo.append_comparison(sid, x, ids[3], 4, "better", D)
    assert repo.verdicts_for(sid, x) == ["worse", "better"]
    repo.delete_comparison(cid)
    assert repo.verdicts_for(sid, x) == ["better"]
    repo.place_film(sid, x, 3, "compared", D)
    assert repo.rank_placements(sid)[x] == (3, "compared")
    repo.unplace_film(sid, x)
    assert x not in repo.rank_placements(sid)
    repo.defer_film(sid, x, "2026-09-13")
    assert repo.rank_deferrals(sid) == {x: "2026-09-13"}
    repo.undefer_film(sid, x)
    assert repo.rank_deferrals(sid) == {}
    repo.set_last_action(sid, {"kind": "verdict", "film_id": x, "comparison_id": 2})
    assert repo.open_rank_session("owned").last_action == {"kind": "verdict", "film_id": x, "comparison_id": 2}
    repo.set_last_action(sid, None)
    assert repo.open_rank_session("owned").last_action is None
    assert repo.film_facts([x, ids[0]]) == {x: ("X", 2000, "Dir"), ids[0]: ("A", 1950, "Dir")}


def test_one_open_session_per_source(repo):
    import sqlite3

    import pytest

    repo.create_rank_session("owned", 1, {}, {}, D)
    with pytest.raises(sqlite3.IntegrityError):
        repo.create_rank_session("owned", 2, {}, {}, D)


def test_marking_unseen_drops_placements_in_every_session(repo):
    x = _owned_rated(repo, "X", 2000, 8)
    sid = repo.create_rank_session("owned", 1, {}, {x: 3}, D)
    repo.set_unseen(x, True, D)
    assert repo.rank_placements(sid) == {}


def test_replace_list_entries_rewrites_the_slug_with_links(repo):
    a, b = _film(repo, "A", 1950), _film(repo, "B", 1960)
    repo.upsert_film_list(ListMeta("my-owned-tiers", "Mine", "me", 2026, None, True), D)
    repo.set_list_trust("my-owned-tiers", 3)
    repo.replace_list_entries("my-owned-tiers", [TieredEntry(1, a, "A", "Dir", "=1"), TieredEntry(2, b, "B", "Dir", "=1")])
    repo.replace_list_entries("my-owned-tiers", [TieredEntry(1, b, "B", "Dir", None)])
    rows = repo.list_entries("my-owned-tiers")
    assert [(r.rank, r.film_id, r.rank_label) for r in rows] == [(1, b, None)]
    repo.upsert_film_list(ListMeta("my-owned-tiers", "Mine again", "me", 2026, None, True), D)
    assert repo.film_list("my-owned-tiers").trust == 3


def test_merge_moves_rank_rows_survivor_wins(repo):
    a, b = _film(repo, "Alpha", 1950), _film(repo, "Alpha", 1951)
    sid = repo.create_rank_session("owned", 1, {3: b}, {a: 2, b: 4}, D)
    repo.append_comparison(sid, b, a, 3, "worse", D)
    repo.defer_film(sid, b, "2026-09-13")
    repo.merge_film(b, a, D)
    assert repo.rank_placements(sid) == {a: (2, "seed")}  # survivor's row wins, loser's dropped
    assert repo.rank_anchors(sid)[3] == a
    assert repo.rank_deferrals(sid) == {a: "2026-09-13"}
    with repo._conn() as c:
        row = c.execute("SELECT film_id, anchor_film_id FROM rank_comparison WHERE session_id = ?", (sid,)).fetchone()
    assert (row["film_id"], row["anchor_film_id"]) == (a, a)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_rank_repository.py -q`
Expected: FAIL on `owned_seed_films` and the rest with `AttributeError`.

- [ ] **Step 3: Implement**

`listfile.py`, after the imports:

```python
LISTS_DIR = Path(__file__).resolve().parents[3] / "lists"  # the checked-in list files; the ranker's save guard reads it (spec §7)
```

`database.py`: import `RankSession, SeedFilm, TieredEntry` from `movie_brain.domain.models`, then the new section:

```python
    # tier ranker (spec 2026-09-13 §3) ----------------------------------------
    def owned_seed_films(self) -> list[SeedFilm]:
        """Owned ∩ rated, minus unseen and disposed: the seed placements and anchor pool."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT f.id, f.title, f.year, r.score, o2.imdb FROM owned o "
                "JOIN films f ON f.id = o.film_id JOIN my_ratings r ON r.film_id = f.id "
                "LEFT JOIN omdb o2 ON o2.film_id = f.id "
                "WHERE " + _NOT_DISPOSED + " AND NOT EXISTS (SELECT 1 FROM unseen u WHERE u.film_id = f.id) "
                "ORDER BY f.id"
            ).fetchall()
            return [SeedFilm(int(r["id"]), int(r["score"]), r["imdb"], str(r["title"]), r["year"]) for r in rows]

    def film_facts(self, film_ids: Iterable[int]) -> dict[int, tuple[str, int | None, str | None]]:
        ids = list(film_ids)
        if not ids:
            return {}
        with self._conn() as c:
            marks = ",".join("?" * len(ids))
            rows = c.execute(f"SELECT id, title, year, director FROM films WHERE id IN ({marks})", ids).fetchall()
            return {int(r["id"]): (str(r["title"]), r["year"], r["director"]) for r in rows}

    def open_rank_session(self, source: str) -> RankSession | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM rank_session WHERE source = ? AND finished_on IS NULL", (source,)).fetchone()
            if row is None:
                return None
            action = json.loads(row["last_action"]) if row["last_action"] else None
            return RankSession(
                int(row["id"]), str(row["source"]), int(row["seed"]), str(row["started_on"]),
                row["finished_on"], row["list_slug"], action,
            )

    def create_rank_session(
        self, source: str, seed: int, anchors: Mapping[int, int], placements: Mapping[int, int], today: date
    ) -> int:
        """Raises sqlite3.IntegrityError when a session for `source` is already open."""
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO rank_session (source, seed, started_on) VALUES (?, ?, ?)", (source, seed, today.isoformat())
            )
            sid = int(cur.lastrowid)
            for tier in range(1, TIERS + 1):
                c.execute(
                    "INSERT INTO rank_anchor (session_id, tier, film_id, set_on) VALUES (?, ?, ?, ?)",
                    (sid, tier, anchors.get(tier), today.isoformat()),
                )
            c.executemany(
                "INSERT INTO rank_placement (session_id, film_id, tier, how, placed_on) VALUES (?, ?, ?, 'seed', ?)",
                [(sid, fid, tier, today.isoformat()) for fid, tier in placements.items()],
            )
            return sid

    def rank_anchors(self, session_id: int) -> dict[int, int | None]:
        with self._conn() as c:
            rows = c.execute("SELECT tier, film_id FROM rank_anchor WHERE session_id = ?", (session_id,)).fetchall()
            return {int(r["tier"]): (None if r["film_id"] is None else int(r["film_id"])) for r in rows}

    def set_rank_anchor(self, session_id: int, tier: int, film_id: int | None, today: date) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE rank_anchor SET film_id = ?, set_on = ? WHERE session_id = ? AND tier = ?",
                (film_id, today.isoformat(), session_id, tier),
            )

    def rank_placements(self, session_id: int) -> dict[int, tuple[int, str]]:
        with self._conn() as c:
            rows = c.execute("SELECT film_id, tier, how FROM rank_placement WHERE session_id = ?", (session_id,)).fetchall()
            return {int(r["film_id"]): (int(r["tier"]), str(r["how"])) for r in rows}

    def place_film(self, session_id: int, film_id: int, tier: int, how: str, today: date) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO rank_placement (session_id, film_id, tier, how, placed_on) VALUES (?, ?, ?, ?, ?)",
                (session_id, film_id, tier, how, today.isoformat()),
            )

    def unplace_film(self, session_id: int, film_id: int) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM rank_placement WHERE session_id = ? AND film_id = ?", (session_id, film_id))

    def append_comparison(
        self, session_id: int, film_id: int, anchor_film_id: int, anchor_tier: int, verdict: str, today: date
    ) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO rank_comparison (session_id, film_id, anchor_film_id, anchor_tier, verdict, decided_on) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, film_id, anchor_film_id, anchor_tier, verdict, today.isoformat()),
            )
            return int(cur.lastrowid)

    def verdicts_for(self, session_id: int, film_id: int) -> list[str]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT verdict FROM rank_comparison WHERE session_id = ? AND film_id = ? ORDER BY id", (session_id, film_id)
            ).fetchall()
            return [str(r["verdict"]) for r in rows]

    def delete_comparison(self, comparison_id: int) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM rank_comparison WHERE id = ?", (comparison_id,))

    def defer_film(self, session_id: int, film_id: int, stamp: str) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO rank_deferral (session_id, film_id, deferred_on) VALUES (?, ?, ?)",
                (session_id, film_id, stamp),
            )

    def undefer_film(self, session_id: int, film_id: int) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM rank_deferral WHERE session_id = ? AND film_id = ?", (session_id, film_id))

    def rank_deferrals(self, session_id: int) -> dict[int, str]:
        with self._conn() as c:
            rows = c.execute("SELECT film_id, deferred_on FROM rank_deferral WHERE session_id = ?", (session_id,)).fetchall()
            return {int(r["film_id"]): str(r["deferred_on"]) for r in rows}

    def set_last_action(self, session_id: int, action: dict[str, object] | None) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE rank_session SET last_action = ? WHERE id = ?",
                (None if action is None else json.dumps(action), session_id),
            )

    def set_rank_session_list(self, session_id: int, slug: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE rank_session SET list_slug = ? WHERE id = ?", (slug, session_id))

    def replace_list_entries(self, slug: str, entries: Iterable[TieredEntry]) -> None:
        """The ranker's save (spec §7): the slug's entries are rewritten whole, linked at write
        time. Never used by `lists import`, whose entries are append-only and link separately."""
        with self._conn() as c:
            c.execute("DELETE FROM film_list_entry WHERE list_slug = ?", (slug,))
            c.executemany(
                "INSERT INTO film_list_entry (list_slug, rank, film_id, title_listed, director_listed, rank_label) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [(slug, e.rank, e.film_id, e.title, e.director, e.rank_label) for e in entries],
            )
```

`TIERS` import: `from movie_brain.domain.rank import TIERS`.

In `merge_film`, after the `film_list_entry` move, add:

```python
            # Ranker rows (spec §3): per-session one-row tables survivor-wins; the log re-points.
            for table in ("rank_placement", "rank_deferral"):
                for row in c.execute(f"SELECT session_id FROM {table} WHERE film_id = ?", (loser_id,)).fetchall():
                    sid = int(row["session_id"])
                    if c.execute(f"SELECT 1 FROM {table} WHERE session_id = ? AND film_id = ?", (sid, survivor_id)).fetchone():
                        c.execute(f"DELETE FROM {table} WHERE session_id = ? AND film_id = ?", (sid, loser_id))
                        dropped[table] = dropped.get(table, 0) + 1
                    else:
                        c.execute(
                            f"UPDATE {table} SET film_id = ? WHERE session_id = ? AND film_id = ?", (survivor_id, sid, loser_id)
                        )
                        moved[table] = moved.get(table, 0) + 1
            n = c.execute("UPDATE rank_anchor SET film_id = ? WHERE film_id = ?", (survivor_id, loser_id)).rowcount
            if n:
                moved["rank_anchor"] = n
            n = c.execute(
                "UPDATE rank_comparison SET film_id = CASE WHEN film_id = ? THEN ? ELSE film_id END, "
                "anchor_film_id = CASE WHEN anchor_film_id = ? THEN ? ELSE anchor_film_id END "
                "WHERE film_id = ? OR anchor_film_id = ?",
                (loser_id, survivor_id, loser_id, survivor_id, loser_id, loser_id),
            ).rowcount
            if n:
                moved["rank_comparison"] = n
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/unit/test_rank_repository.py -q`
Expected: PASS (8 tests).

- [ ] **Step 5: Lint, types, whole suite (minus Playwright), commit**

```bash
uv run ruff check . && uv run mypy && uv run pytest -q --ignore=tests/web/test_dashboard.py
git add src/movie_brain/infrastructure/database.py src/movie_brain/infrastructure/listfile.py tests/unit/test_rank_repository.py
git commit -m "the session's state is rows the repository owns, so a refresh or a merge never loses a click"
```

---

### Task 4: The use case (`application/rank.py`) with pytest-bdd scenarios

**Files:**
- Create: `src/movie_brain/application/rank.py`
- Create: `tests/features/rank.feature`, `tests/step_defs/test_rank.py`

**Interfaces:**
- Consumes: everything from Tasks 2 and 3.
- Produces (all take `repo: Repository` first, `source: str` second unless noted, `today: date` last):
  - `class RankError(Exception)` with `.status: int` and `.message: str`.
  - `proposal(repo, source) -> dict` → `{"proposal": {tier: film|None}, "choices": {tier: [film...]}}`, film = `{"film_id", "title", "year", "score"}`. `choices[t]` is the seeded films of tier `t`, or, when there are none, every owned non-unseen film (any placement state) — the fallback that lets an empty tier get an anchor.
  - `start_session(repo, source, anchors: Mapping[int, int], today) -> int` — 400 if a tier is missing or an anchor is unseen/not owned; 409 if open. Seeds every `owned_seed_films()` entry at `tier_for_score`. An anchor with no seed placement is placed at its tier with `how='anchor'`. Seed = `int(today.strftime('%Y%m%d'))`.
  - `session_state(repo, source, today) -> dict` — the §6 shape: `{"session": {...}|None, "anchors": {tier: {"film_id","title","year"}|None}, "tally": {tier: n}, "placed": n, "remaining": n, "unseen": n, "pair": {"candidate": {...}, "anchor": {...}, "tier": t, "asked": [...]}|None, "needs_anchor": [tiers], "done": bool, "can_undo": bool}`.
  - `record_verdict(repo, source, film_id, anchor_tier, verdict, today) -> dict` (state after). 400 on a verdict outside `VERDICTS`; 404 with no session; 409 when `(film_id, anchor_tier)` is not the current pair.
  - `pass_film(repo, source, film_id, candidate_unseen: bool, anchor_unseen: bool, today) -> dict`. 409 when `film_id` is not the current candidate.
  - `undo(repo, source, today) -> dict`. 409 when nothing to undo.
  - `swap_anchor(repo, source, tier, film_id, today) -> dict`. 409 when the film is placed in another tier or unseen; 400 when not owned.
  - `save_list(repo, source, name: str | None, today, lists_dir: Path) -> dict` → `{"slug", "name", "entries": n}`. 409 when `lists_dir / f"{slug}.tsv"` exists.

- [ ] **Step 1: Write the feature file**

`tests/features/rank.feature`:

```gherkin
Feature: Tier ranker — place owned films into five tiers against anchors

  Background:
    Given owned films rated "Ten" 10, "Nine" 9, "Eight" 8, "Seven" 7, "Four" 4
    And owned unrated films "Uno", "Dos", "Tres"

  Scenario: The proposal names one seeded anchor per tier
    Then the proposal is Ten, Nine, Eight, Seven, Four

  Scenario: Starting seeds the rated films and asks the first candidate against tier 3
    When I start a session with the proposed anchors
    Then the tally is 1, 1, 1, 1, 1
    And the pair asks the candidate against tier 3 "Eight"
    And 3 films remain

  Scenario Outline: Every verdict path lands in the tier the table says
    Given a started session
    When I answer <verdicts>
    Then the current candidate was placed in tier <tier>
    And the next candidate is asked against tier 3

    Examples:
      | verdicts              | tier |
      | better, better        | 1    |
      | better, worse         | 2    |
      | worse, better         | 3    |
      | worse, worse, better  | 4    |
      | worse, worse, worse   | 5    |

  Scenario: A stale verdict is refused
    Given a started session
    When I answer better
    Then answering "worse" against tier 3 is refused with 409

  Scenario: Pass with nothing marked defers the candidate to the back
    Given a started session
    When I pass with nothing marked
    Then the deferred film comes last in the queue
    And 3 films remain

  Scenario: Pass with the candidate marked sends it to the unseen bucket
    Given a started session
    When I pass with the candidate marked unseen
    Then that film is unseen
    And 2 films remain

  Scenario: Pass with the anchor marked empties the tier and asks for a new anchor
    Given a started session
    When I pass with the anchor marked unseen
    Then "Eight" is unseen
    And the session needs an anchor for tier 3
    And there is no pair
    When I swap tier 3's anchor to "Uno"
    Then the tally is 1, 1, 1, 1, 1
    And the pair asks the candidate against tier 3 "Uno"

  Scenario: A swap across tiers is refused
    Given a started session
    Then swapping tier 3's anchor to "Ten" is refused with 409

  Scenario: Undo reverts a placement, a deferral and a candidate-unseen, one level deep
    Given a started session
    When I answer better, better
    And I undo
    Then the current candidate has 1 verdict and is unplaced
    When I pass with nothing marked
    And I undo
    Then nothing is deferred
    When I pass with the candidate marked unseen
    And I undo
    Then nothing is unseen
    And undoing again is refused with 409

  Scenario: Saving writes a tied-rank list and re-saving replaces it
    Given a started session
    When I answer better, better
    And I save the list as "Mine"
    Then the list "my-owned-tiers" has 6 entries
    And its tier 1 entries carry label "=1"
    And its tier 5 entry carries no label
    When I answer worse, worse, worse
    And I save the list as "Mine"
    Then the list "my-owned-tiers" has 7 entries

  Scenario: Saving refuses a slug a list file owns
    Given a started session
    And a list file "my-owned-tiers.tsv" exists
    Then saving is refused with 409

  Scenario: Reopening resumes the same pair
    Given a started session
    When I answer worse
    Then reopening the session shows the same candidate asked against tier 4

  Scenario: Marking a placed film unseen from the drawer drops its placement
    Given a started session
    When I answer better, better
    And that film is marked unseen from the drawer
    Then the tally is 1, 1, 1, 1, 1
```

- [ ] **Step 2: Write the step definitions**

`tests/step_defs/test_rank.py`:

```python
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.rank import (
    RankError,
    pass_film,
    proposal,
    record_verdict,
    save_list,
    session_state,
    start_session,
    swap_anchor,
    undo,
)
from movie_brain.domain.models import Film
from movie_brain.domain.rank import order_queue

scenarios("../features/rank.feature")
TODAY = date(2026, 9, 13)
SRC = "owned"


@pytest.fixture
def ctx(repo, tmp_path):
    return {"repo": repo, "ids": {}, "lists_dir": tmp_path / "lists", "state": None}


def _id(ctx, title):
    return ctx["ids"][title]


def _title(ctx, fid):
    return next(t for t, i in ctx["ids"].items() if i == fid)


def _state(ctx):
    ctx["state"] = session_state(ctx["repo"], SRC, TODAY)
    return ctx["state"]


@given(parsers.parse('owned films rated "Ten" {a:d}, "Nine" {b:d}, "Eight" {c:d}, "Seven" {d:d}, "Four" {e:d}'))
def rated(ctx, a, b, c, d, e):
    for title, score in (("Ten", a), ("Nine", b), ("Eight", c), ("Seven", d), ("Four", e)):
        fid = ctx["repo"].create_film(Film(title, 1950, "Dir", ""))
        ctx["repo"].mark_owned(fid, TODAY)
        ctx["repo"].set_rating(fid, score, TODAY)
        ctx["ids"][title] = fid


@given(parsers.parse('owned unrated films "Uno", "Dos", "Tres"'))
def unrated(ctx):
    for title in ("Uno", "Dos", "Tres"):
        fid = ctx["repo"].create_film(Film(title, 1960, "Dir", ""))
        ctx["repo"].mark_owned(fid, TODAY)
        ctx["ids"][title] = fid


@then(parsers.parse("the proposal is {names}"))
def proposal_is(ctx, names):
    got = proposal(ctx["repo"], SRC)["proposal"]
    assert [got[t]["title"] for t in range(1, 6)] == [n.strip() for n in names.split(",")]


@when("I start a session with the proposed anchors")
@given("a started session")
def start(ctx):
    p = proposal(ctx["repo"], SRC)["proposal"]
    start_session(ctx["repo"], SRC, {t: p[t]["film_id"] for t in range(1, 6)}, TODAY)
    _state(ctx)


@then(parsers.parse("the tally is {a:d}, {b:d}, {c:d}, {d:d}, {e:d}"))
def tally(ctx, a, b, c, d, e):
    assert [_state(ctx)["tally"][t] for t in range(1, 6)] == [a, b, c, d, e]


@then(parsers.parse('the pair asks the candidate against tier {tier:d} "{anchor}"'))
def pair_asks(ctx, tier, anchor):
    s = _state(ctx)
    assert s["pair"]["tier"] == tier and s["pair"]["anchor"]["title"] == anchor
    assert s["pair"]["candidate"]["title"] in ("Uno", "Dos", "Tres")


@then(parsers.parse("{n:d} films remain"))
def remain(ctx, n):
    assert _state(ctx)["remaining"] == n


@when(parsers.parse("I answer {verdicts}"))
def answer(ctx, verdicts):
    for v in [x.strip() for x in verdicts.split(",")]:
        s = _state(ctx)
        ctx["last_candidate"] = s["pair"]["candidate"]["film_id"]
        record_verdict(ctx["repo"], SRC, s["pair"]["candidate"]["film_id"], s["pair"]["tier"], v, TODAY)


@then(parsers.parse("the current candidate was placed in tier {tier:d}"))
def placed_in(ctx, tier):
    sid = ctx["repo"].open_rank_session(SRC).id
    assert ctx["repo"].rank_placements(sid)[ctx["last_candidate"]] == (tier, "compared")


@then(parsers.parse("the next candidate is asked against tier {tier:d}"))
def next_asked(ctx, tier):
    s = _state(ctx)
    assert s["pair"]["tier"] == tier and s["pair"]["candidate"]["film_id"] != ctx["last_candidate"]


@then(parsers.parse('answering "{v}" against tier {tier:d} is refused with {status:d}'))
def stale(ctx, v, tier, status):
    s = _state(ctx)
    with pytest.raises(RankError) as e:
        record_verdict(ctx["repo"], SRC, s["pair"]["candidate"]["film_id"], tier, v, TODAY)
    assert e.value.status == status


@when("I pass with nothing marked")
def pass_plain(ctx):
    s = _state(ctx)
    ctx["last_candidate"] = s["pair"]["candidate"]["film_id"]
    pass_film(ctx["repo"], SRC, ctx["last_candidate"], False, False, TODAY)


@when("I pass with the candidate marked unseen")
def pass_candidate(ctx):
    s = _state(ctx)
    ctx["last_candidate"] = s["pair"]["candidate"]["film_id"]
    pass_film(ctx["repo"], SRC, ctx["last_candidate"], True, False, TODAY)


@when("I pass with the anchor marked unseen")
def pass_anchor(ctx):
    s = _state(ctx)
    pass_film(ctx["repo"], SRC, s["pair"]["candidate"]["film_id"], False, True, TODAY)


@then("the deferred film comes last in the queue")
def deferred_last(ctx):
    repo = ctx["repo"]
    sess = repo.open_rank_session(SRC)
    unplaced = [i for t, i in ctx["ids"].items() if t in ("Uno", "Dos", "Tres")]
    q = order_queue(sess.seed, unplaced, repo.rank_deferrals(sess.id))
    assert q[-1] == ctx["last_candidate"] and _state(ctx)["pair"]["candidate"]["film_id"] != ctx["last_candidate"]


@then("that film is unseen")
def that_unseen(ctx):
    assert ctx["last_candidate"] in ctx["repo"].unseen_film_ids()


@then(parsers.parse('"{title}" is unseen'))
def title_unseen(ctx, title):
    assert _id(ctx, title) in ctx["repo"].unseen_film_ids()


@then(parsers.parse("the session needs an anchor for tier {tier:d}"))
def needs_anchor(ctx, tier):
    assert _state(ctx)["needs_anchor"] == [tier]


@then("there is no pair")
def no_pair(ctx):
    assert _state(ctx)["pair"] is None


@when(parsers.parse("I swap tier {tier:d}'s anchor to \"{title}\""))
def swap(ctx, tier, title):
    swap_anchor(ctx["repo"], SRC, tier, _id(ctx, title), TODAY)


@then(parsers.parse("swapping tier {tier:d}'s anchor to \"{title}\" is refused with {status:d}"))
def swap_refused(ctx, tier, title, status):
    with pytest.raises(RankError) as e:
        swap_anchor(ctx["repo"], SRC, tier, _id(ctx, title), TODAY)
    assert e.value.status == status


@when("I undo")
def do_undo(ctx):
    undo(ctx["repo"], SRC, TODAY)


@then(parsers.parse("the current candidate has {n:d} verdict and is unplaced"))
def verdict_count(ctx, n):
    repo = ctx["repo"]
    sid = repo.open_rank_session(SRC).id
    assert len(repo.verdicts_for(sid, ctx["last_candidate"])) == n
    assert ctx["last_candidate"] not in repo.rank_placements(sid)
    assert _state(ctx)["pair"]["candidate"]["film_id"] == ctx["last_candidate"]


@then("nothing is deferred")
def nothing_deferred(ctx):
    assert ctx["repo"].rank_deferrals(ctx["repo"].open_rank_session(SRC).id) == {}


@then("nothing is unseen")
def nothing_unseen(ctx):
    assert ctx["repo"].unseen_film_ids() == set()


@then(parsers.parse("undoing again is refused with {status:d}"))
def undo_refused(ctx, status):
    with pytest.raises(RankError) as e:
        undo(ctx["repo"], SRC, TODAY)
    assert e.value.status == status


@when(parsers.parse('I save the list as "{name}"'))
def save(ctx, name):
    ctx["lists_dir"].mkdir(exist_ok=True)
    save_list(ctx["repo"], SRC, name, TODAY, ctx["lists_dir"])


@then(parsers.parse('the list "{slug}" has {n:d} entries'))
def list_has(ctx, slug, n):
    assert len(ctx["repo"].list_entries(slug)) == n


@then(parsers.parse('its tier 1 entries carry label "{label}"'))
def tier1_label(ctx, label):
    rows = ctx["repo"].list_entries("my-owned-tiers")
    assert [r.rank_label for r in rows[:2]] == [label, label]  # Ten + the film just placed in tier 1


@then("its tier 5 entry carries no label")
def tier5_bare(ctx):
    rows = ctx["repo"].list_entries("my-owned-tiers")
    assert rows[-1].film_id == _id(ctx, "Four") and rows[-1].rank_label is None


@given(parsers.parse('a list file "{name}" exists'))
def list_file(ctx, name):
    ctx["lists_dir"].mkdir(exist_ok=True)
    (ctx["lists_dir"] / name).write_text("# slug: my-owned-tiers\n")


@then(parsers.parse("saving is refused with {status:d}"))
def save_refused(ctx, status):
    with pytest.raises(RankError) as e:
        save_list(ctx["repo"], SRC, None, TODAY, ctx["lists_dir"])
    assert e.value.status == status


@then(parsers.parse("reopening the session shows the same candidate asked against tier {tier:d}"))
def reopen(ctx, tier):
    s = _state(ctx)
    assert s["pair"]["candidate"]["film_id"] == ctx["last_candidate"] and s["pair"]["tier"] == tier


@when("that film is marked unseen from the drawer")
def drawer_unseen(ctx):
    ctx["repo"].set_unseen(ctx["last_candidate"], True, TODAY)
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/step_defs/test_rank.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'movie_brain.application.rank'`.

- [ ] **Step 4: Implement the use case**

`src/movie_brain/application/rank.py`:

```python
"""Tier ranker use case (spec docs/superpowers/specs/2026-09-13-tier-ranker-design.md §4–§7).

The server stores clicks; this module derives the state from them on every call (§4.2). Every
function takes the repository and the source and returns the state the page renders next.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from datetime import date
from pathlib import Path

from movie_brain.domain.models import ListMeta, Placed, RankSession
from movie_brain.domain.rank import (
    DEFAULT_LIST_NAME,
    RANKER_SLUGS,
    TIERS,
    VERDICTS,
    Ask,
    Place,
    next_step,
    order_queue,
    propose_anchors,
    tier_for_score,
    tiered_entries,
)
from movie_brain.infrastructure.database import Repository


class RankError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _film(repo: Repository, film_id: int) -> dict[str, object]:
    title, year, _ = repo.film_facts([film_id]).get(film_id, ("?", None, None))
    return {"film_id": film_id, "title": title, "year": year}


def proposal(repo: Repository, source: str) -> dict[str, object]:
    _check_source(source)
    seeded = repo.owned_seed_films()
    proposed = propose_anchors(seeded)
    choices: dict[int, list[dict[str, object]]] = {t: [] for t in range(1, TIERS + 1)}
    for f in seeded:
        choices[tier_for_score(f.score)].append({"film_id": f.film_id, "title": f.title, "year": f.year, "score": f.score})
    unseen = repo.unseen_film_ids()
    fallback = None
    for t in range(1, TIERS + 1):
        if not choices[t]:
            if fallback is None:
                facts = repo.film_facts(i for i in repo.owned_film_ids() if i not in unseen)
                fallback = [{"film_id": i, "title": f[0], "year": f[1], "score": None} for i, f in sorted(facts.items(), key=lambda kv: kv[1][0])]
            choices[t] = fallback
    out_prop = {
        t: None if p is None else {"film_id": p.film_id, "title": p.title, "year": p.year, "score": p.score}
        for t, p in proposed.items()
    }
    return {"proposal": out_prop, "choices": choices}


def _check_source(source: str) -> None:
    if source not in RANKER_SLUGS:
        raise RankError(400, f"unknown source {source!r}; v1 ranks 'owned' only")


def start_session(repo: Repository, source: str, anchors: Mapping[int, int], today: date) -> int:
    _check_source(source)
    if set(anchors) != set(range(1, TIERS + 1)):
        raise RankError(400, "an anchor is required for every tier 1–5")
    owned, unseen = repo.owned_film_ids(), repo.unseen_film_ids()
    for tier, fid in anchors.items():
        if fid not in owned or fid in unseen:
            raise RankError(400, f"tier {tier} anchor {fid} is not an owned, seen film")
    placements = {f.film_id: tier_for_score(f.score) for f in repo.owned_seed_films()}
    seed = int(today.strftime("%Y%m%d"))
    try:
        sid = repo.create_rank_session(source, seed, dict(anchors), placements, today)
    except sqlite3.IntegrityError:
        raise RankError(409, "a session is already open for this source") from None
    for tier, fid in anchors.items():
        if fid not in placements:
            repo.place_film(sid, fid, tier, "anchor", today)
    return sid


def _session(repo: Repository, source: str) -> RankSession:
    _check_source(source)
    s = repo.open_rank_session(source)
    if s is None:
        raise RankError(404, "no open session")
    return s


def _queue(repo: Repository, s: RankSession) -> list[int]:
    placed = repo.rank_placements(s.id)
    unseen = repo.unseen_film_ids()
    anchors = {fid for fid in repo.rank_anchors(s.id).values() if fid is not None}
    disposed = repo.disposed_film_ids()
    ids = [i for i in repo.owned_film_ids() if i not in placed and i not in unseen and i not in anchors and i not in disposed]
    ordered = order_queue(s.seed, ids, repo.rank_deferrals(s.id))
    # A film mid-search (verdicts logged, not yet placed) leads UNLESS it was deferred — a pass
    # on a mid-search film means "not now" and its logged verdicts wait with it at the back:
    # A film mid-search (verdicts logged, not yet placed) leads: after an undo the same candidate
    # must come straight back (§4.4), and a crash between click and placement resumes it (§4.2).
    # One small query per queued film (~640 live) — fine for a one-user local app; if it ever
    # matters, add `films_with_verdicts(session_id) -> set[int]` to the repository.
    deferred = repo.rank_deferrals(s.id)
    in_progress = [i for i in ordered if i not in deferred and repo.verdicts_for(s.id, i)]
    return in_progress + [i for i in ordered if i not in in_progress]


def session_state(repo: Repository, source: str, today: date) -> dict[str, object]:
    _check_source(source)
    s = repo.open_rank_session(source)
    if s is None:
        return {"session": None}
    anchors = repo.rank_anchors(s.id)
    placed = repo.rank_placements(s.id)
    tally = {t: sum(1 for tier, _ in placed.values() if tier == t) for t in range(1, TIERS + 1)}
    queue = _queue(repo, s)
    needs = [t for t in range(1, TIERS + 1) if anchors[t] is None]
    pair: dict[str, object] | None = None
    if queue and not needs:
        cand = queue[0]
        verdicts = repo.verdicts_for(s.id, cand)
        step = next_step(verdicts)
        assert isinstance(step, Ask)  # a Place is applied the moment its verdict lands
        anchor_id = anchors[step.tier]
        assert anchor_id is not None
        pair = {"candidate": _film(repo, cand), "anchor": _film(repo, anchor_id), "tier": step.tier, "asked": verdicts}
    return {
        "session": {"id": s.id, "source": s.source, "started_on": s.started_on, "list_slug": s.list_slug},
        "anchors": {t: (None if fid is None else _film(repo, fid)) for t, fid in anchors.items()},
        "tally": tally,
        "placed": len(placed),
        "remaining": len(queue),
        "unseen": len(repo.unseen_film_ids() & repo.owned_film_ids()),
        "pair": pair,
        "needs_anchor": needs,
        "done": not queue and not needs,
        "can_undo": s.last_action is not None,
    }


def _current_pair(repo: Repository, source: str, today: date) -> tuple[RankSession, dict[str, object]]:
    s = _session(repo, source)
    state = session_state(repo, source, today)
    pair = state["pair"]
    if not isinstance(pair, dict):
        raise RankError(409, "no current pair")
    return s, pair


def record_verdict(
    repo: Repository, source: str, film_id: int, anchor_tier: int, verdict: str, today: date
) -> dict[str, object]:
    if verdict not in VERDICTS:
        raise RankError(400, f"verdict must be one of {', '.join(VERDICTS)}")
    s, pair = _current_pair(repo, source, today)
    cand = pair["candidate"]
    anchor = pair["anchor"]
    assert isinstance(cand, dict) and isinstance(anchor, dict)
    if cand["film_id"] != film_id or pair["tier"] != anchor_tier:
        raise RankError(409, "that pair is no longer current")
    cid = repo.append_comparison(s.id, film_id, int(anchor["film_id"]), anchor_tier, verdict, today)
    step = next_step(repo.verdicts_for(s.id, film_id))
    placed_tier = None
    if isinstance(step, Place):
        repo.place_film(s.id, film_id, step.tier, "compared", today)
        placed_tier = step.tier
    repo.set_last_action(s.id, {"kind": "verdict", "film_id": film_id, "comparison_id": cid, "placed_tier": placed_tier})
    return session_state(repo, source, today)


def pass_film(
    repo: Repository, source: str, film_id: int, candidate_unseen: bool, anchor_unseen: bool, today: date
) -> dict[str, object]:
    s, pair = _current_pair(repo, source, today)
    cand = pair["candidate"]
    anchor = pair["anchor"]
    assert isinstance(cand, dict) and isinstance(anchor, dict)
    if cand["film_id"] != film_id:
        raise RankError(409, "that candidate is no longer current")
    if anchor_unseen:
        # D10: a bad anchor. Placement rows go with the unseen mark (set_unseen deletes them).
        repo.set_unseen(int(anchor["film_id"]), True, today)
        repo.set_rank_anchor(s.id, int(pair["tier"]), None, today)
    if candidate_unseen:
        repo.set_unseen(film_id, True, today)
        repo.set_last_action(s.id, {"kind": "unseen", "film_id": film_id} if not anchor_unseen else None)
    else:
        repo.defer_film(s.id, film_id, today.isoformat())
        repo.set_last_action(s.id, {"kind": "defer", "film_id": film_id} if not anchor_unseen else None)
    return session_state(repo, source, today)


def undo(repo: Repository, source: str, today: date) -> dict[str, object]:
    s = _session(repo, source)
    action = s.last_action
    if action is None:
        raise RankError(409, "nothing to undo")
    fid = int(action["film_id"])  # type: ignore[arg-type]
    kind = action["kind"]
    if kind == "verdict":
        # Deleting the row shortens a valid sequence to a valid sequence (§4.1); with verdicts
        # still logged the film leads `_queue`, so it is the current candidate again at once.
        repo.delete_comparison(int(action["comparison_id"]))  # type: ignore[arg-type]
        if action.get("placed_tier") is not None:
            repo.unplace_film(s.id, fid)
    elif kind == "defer":
        repo.undefer_film(s.id, fid)
    elif kind == "unseen":
        repo.set_unseen(fid, False, today)
    repo.set_last_action(s.id, None)
    return session_state(repo, source, today)


def swap_anchor(repo: Repository, source: str, tier: int, film_id: int, today: date) -> dict[str, object]:
    s = _session(repo, source)
    if tier not in range(1, TIERS + 1):
        raise RankError(400, "tier must be 1–5")
    if film_id not in repo.owned_film_ids():
        raise RankError(400, "anchor must be an owned film")
    if film_id in repo.unseen_film_ids():
        raise RankError(409, "an unseen film cannot anchor a tier")
    placed = repo.rank_placements(s.id)
    if film_id in placed and placed[film_id][0] != tier:
        raise RankError(409, f"that film is placed in tier {placed[film_id][0]}, not {tier}")
    if film_id not in placed:
        repo.place_film(s.id, film_id, tier, "anchor", today)
    repo.set_rank_anchor(s.id, tier, film_id, today)
    return session_state(repo, source, today)


def save_list(repo: Repository, source: str, name: str | None, today: date, lists_dir: Path) -> dict[str, object]:
    s = _session(repo, source)
    slug = RANKER_SLUGS[source]
    if (lists_dir / f"{slug}.tsv").exists():
        raise RankError(409, f"lists/{slug}.tsv exists — that slug belongs to a checked-in list")
    placed = repo.rank_placements(s.id)
    facts = repo.film_facts(placed)
    entries = tiered_entries(Placed(fid, tier, facts[fid][0], facts[fid][2]) for fid, (tier, _) in placed.items() if fid in facts)
    list_name = (name or "").strip() or DEFAULT_LIST_NAME[source]
    repo.upsert_film_list(ListMeta(slug, list_name, "me", today.year, None, True), today)
    repo.replace_list_entries(slug, entries)
    repo.set_rank_session_list(s.id, slug)
    return {"slug": slug, "name": list_name, "entries": len(entries)}
```

`owned_film_ids()` (database.py line 2142) and `disposed_film_ids()` (line 2429) already exist; nothing else is needed from the repository.

- [ ] **Step 5: Run the scenarios**

Run: `uv run pytest tests/step_defs/test_rank.py -q`
Expected: PASS (17 scenarios: 12 plus the 5-row outline). Undo is one level deep (Global Constraints), which is why the undo scenario never undoes twice in a row without a new click between.

If the undo scenario fails on "the current candidate has 1 verdict and is unplaced", `_queue`'s in-progress rule is missing.

- [ ] **Step 6: Lint, types, commit**

```bash
uv run ruff check . && uv run mypy
git add src/movie_brain/application/rank.py tests/features/rank.feature tests/step_defs/test_rank.py
git commit -m "the ranker derives its next pair from the click log on every call, so nothing lives in the browser"
```

---

### Task 5: The API routes

**Files:**
- Modify: `src/movie_brain/web/app.py`
- Test: `tests/web/test_api.py` (append)

**Interfaces:**
- Consumes: `application/rank.py` (Task 4), `Repository.set_unseen` (Task 1), `LISTS_DIR` (Task 3).
- Produces the routes of spec §6. `create_app` gains a keyword `lists_dir: Path = LISTS_DIR` so tests point the save guard at a temp dir.

- [ ] **Step 1: Write the failing tests** (append to `tests/web/test_api.py`)

```python
from movie_brain.domain.models import Film as _Film


@pytest.fixture
def rank_client(repo, tmp_path):
    ids = {}
    for title, score in (("Ten", 10), ("Nine", 9), ("Eight", 8), ("Seven", 7), ("Four", 4)):
        fid = repo.create_film(_Film(title, 1950, "Dir", ""))
        repo.mark_owned(fid, D)
        repo.set_rating(fid, score, D)
        ids[title] = fid
    for title in ("Uno", "Dos"):
        fid = repo.create_film(_Film(title, 1960, "Dir", ""))
        repo.mark_owned(fid, D)
        ids[title] = fid
    app = create_app(repo, today=lambda: D, lists_dir=tmp_path / "lists")
    app.testing = True
    return app.test_client(), ids


def _start(client):
    p = client.get("/api/rank/proposal").get_json()["proposal"]
    r = client.post("/api/rank/session", json={"anchors": {t: p[str(t)]["film_id"] for t in range(1, 6)}})
    assert r.status_code == 201, r.get_json()
    return client.get("/api/rank/session").get_json()


def test_rank_page_serves_html(rank_client):
    client, _ = rank_client
    r = client.get("/rank")
    assert r.status_code == 200 and b"rank.js" in r.data


def test_rank_session_is_null_before_start_and_409_on_a_second_start(rank_client):
    client, _ = rank_client
    assert client.get("/api/rank/session").get_json() == {"session": None}
    state = _start(client)
    assert state["pair"]["tier"] == 3 and state["remaining"] == 2 and state["tally"] == {str(t): 1 for t in range(1, 6)}
    p = client.get("/api/rank/proposal").get_json()["proposal"]
    r = client.post("/api/rank/session", json={"anchors": {t: p[str(t)]["film_id"] for t in range(1, 6)}})
    assert r.status_code == 409


def test_rank_verdict_places_and_refuses_stale(rank_client):
    client, _ = rank_client
    state = _start(client)
    cand = state["pair"]["candidate"]["film_id"]
    r = client.post("/api/rank/verdict", json={"film_id": cand, "anchor_tier": 3, "verdict": "better"})
    assert r.status_code == 200 and r.get_json()["pair"]["tier"] == 2
    r = client.post("/api/rank/verdict", json={"film_id": cand, "anchor_tier": 3, "verdict": "better"})
    assert r.status_code == 409
    r = client.post("/api/rank/verdict", json={"film_id": cand, "anchor_tier": 2, "verdict": "same"})
    assert r.status_code == 400
    r = client.post("/api/rank/verdict", json={"film_id": cand, "anchor_tier": 2, "verdict": "better"})
    assert r.get_json()["tally"]["1"] == 2 and r.get_json()["can_undo"] is True
    r = client.post("/api/rank/undo")
    assert r.status_code == 200 and r.get_json()["tally"]["1"] == 1 and r.get_json()["pair"]["candidate"]["film_id"] == cand


def test_rank_pass_anchor_unseen_then_swap_then_save(rank_client, repo):
    client, ids = rank_client
    state = _start(client)
    cand = state["pair"]["candidate"]["film_id"]
    r = client.post("/api/rank/pass", json={"film_id": cand, "candidate_unseen": False, "anchor_unseen": True})
    body = r.get_json()
    assert r.status_code == 200 and body["needs_anchor"] == [3] and body["pair"] is None
    assert ids["Eight"] in repo.unseen_film_ids()
    r = client.put("/api/rank/anchor", json={"tier": 3, "film_id": ids["Ten"]})
    assert r.status_code == 409
    r = client.put("/api/rank/anchor", json={"tier": 3, "film_id": ids["Dos"]})
    assert r.status_code == 200 and r.get_json()["anchors"]["3"]["film_id"] == ids["Dos"]
    r = client.post("/api/rank/save", json={"name": ""})
    assert r.status_code == 200 and r.get_json() == {"slug": "my-owned-tiers", "name": "My owned films, tiered", "entries": 5}
    films = {f["title"]: f for f in client.get("/api/films").get_json()}
    assert films["Ten"]["lists"][0]["slug"] == "my-owned-tiers" and films["Ten"]["lists"][0]["rank_label"] is None


def test_rank_save_refuses_a_file_backed_slug(rank_client, tmp_path):
    client, _ = rank_client
    _start(client)
    (tmp_path / "lists").mkdir()
    (tmp_path / "lists" / "my-owned-tiers.tsv").write_text("# slug: my-owned-tiers\n")
    assert client.post("/api/rank/save", json={}).status_code == 409


def test_rank_routes_404_without_a_session(rank_client):
    client, _ = rank_client
    assert client.post("/api/rank/verdict", json={"film_id": 1, "anchor_tier": 3, "verdict": "better"}).status_code == 404
    assert client.post("/api/rank/undo").status_code == 404
    assert client.post("/api/rank/save", json={}).status_code == 404


def test_unseen_toggle_route(client, repo):
    trio = repo.film_id_by_key("trio (1950)")
    r = client.put(f"/api/films/{trio}/unseen", json={"unseen": True})
    assert r.status_code == 200 and r.get_json() == {"unseen": True}
    assert client.get(f"/api/films/{trio}").get_json()["unseen"] is True
    assert client.put(f"/api/films/{trio}/unseen", json={"unseen": False}).get_json() == {"unseen": False}
    assert client.put(f"/api/films/{trio}/unseen", json={}).status_code == 400
    assert client.put("/api/films/999/unseen", json={"unseen": True}).status_code == 404
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/web/test_api.py -q -k "rank or unseen"`
Expected: FAIL — `TypeError: create_app() got an unexpected keyword argument 'lists_dir'`.

- [ ] **Step 3: Implement**

In `app.py`: add imports

```python
from pathlib import Path

from movie_brain.application import rank as ranker
from movie_brain.application.rank import RankError
from movie_brain.infrastructure.listfile import LISTS_DIR
```

Change the signature to `def create_app(repo: Repository, today: Callable[[], date] = date.today, embedder: Embedder | None = None, lists_dir: Path = LISTS_DIR) -> Flask:` and add, before `return app`:

```python
    RANK_SOURCE = "owned"  # v1 (spec D7)

    @app.errorhandler(RankError)
    def rank_error(exc: RankError) -> tuple[Response, int]:
        return jsonify({"error": exc.message}), exc.status

    @app.get("/rank")
    def rank_page() -> str:
        return render_template("rank.html")

    @app.get("/api/rank/proposal")
    def rank_proposal() -> Response:
        return jsonify(ranker.proposal(repo, RANK_SOURCE))

    @app.get("/api/rank/session")
    def rank_session() -> Response:
        return jsonify(ranker.session_state(repo, RANK_SOURCE, today()))

    @app.post("/api/rank/session")
    def rank_start() -> tuple[Response, int]:
        body = request.get_json(silent=True)
        anchors = body.get("anchors") if isinstance(body, dict) else None
        if not isinstance(anchors, dict):
            return jsonify({"error": 'body must be JSON {"anchors": {"1": film_id, …, "5": film_id}}'}), 400
        try:
            parsed = {int(k): int(v) for k, v in anchors.items()}
        except (TypeError, ValueError):
            return jsonify({"error": "anchors must map tier → film_id"}), 400
        sid = ranker.start_session(repo, RANK_SOURCE, parsed, today())
        return jsonify({"session_id": sid, **ranker.session_state(repo, RANK_SOURCE, today())}), 201

    @app.post("/api/rank/verdict")
    def rank_verdict() -> Response:
        body = request.get_json(silent=True) or {}
        if not isinstance(body.get("film_id"), int) or not isinstance(body.get("anchor_tier"), int):
            raise RankError(400, 'body must be JSON {"film_id": int, "anchor_tier": int, "verdict": "better"|"worse"}')
        return jsonify(ranker.record_verdict(repo, RANK_SOURCE, body["film_id"], body["anchor_tier"], str(body.get("verdict")), today()))

    @app.post("/api/rank/pass")
    def rank_pass() -> Response:
        body = request.get_json(silent=True) or {}
        if not isinstance(body.get("film_id"), int):
            raise RankError(400, 'body must be JSON {"film_id": int, "candidate_unseen": bool, "anchor_unseen": bool}')
        return jsonify(ranker.pass_film(
            repo, RANK_SOURCE, body["film_id"], bool(body.get("candidate_unseen")), bool(body.get("anchor_unseen")), today()
        ))

    @app.post("/api/rank/undo")
    def rank_undo() -> Response:
        return jsonify(ranker.undo(repo, RANK_SOURCE, today()))

    @app.put("/api/rank/anchor")
    def rank_anchor() -> Response:
        body = request.get_json(silent=True) or {}
        if not isinstance(body.get("tier"), int) or not isinstance(body.get("film_id"), int):
            raise RankError(400, 'body must be JSON {"tier": int, "film_id": int}')
        return jsonify(ranker.swap_anchor(repo, RANK_SOURCE, body["tier"], body["film_id"], today()))

    @app.post("/api/rank/save")
    def rank_save() -> Response:
        body = request.get_json(silent=True) or {}
        name = body.get("name") if isinstance(body.get("name"), str) else None
        return jsonify(ranker.save_list(repo, RANK_SOURCE, name, today(), lists_dir))

    @app.put("/api/films/<int:film_id>/unseen")
    def put_unseen(film_id: int) -> tuple[Response, int]:
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not isinstance(body.get("unseen"), bool):
            return jsonify({"error": 'body must be JSON {"unseen": bool, "note"?: str}'}), 400
        note = body.get("note") if isinstance(body.get("note"), str) else None
        result = repo.set_unseen(film_id, body["unseen"], today(), note=note)
        if result is None:
            return jsonify({"error": "not found"}), 404
        return jsonify({"unseen": result}), 200
```

Note: `ranker.session_state` returns tier keys as ints; `jsonify` writes them as strings, which is why the tests index with `"3"`. Create a stub `rank.html` now so `/rank` renders (Task 6 fills it):

```html
<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>movie-brain · rank</title>
<link rel="stylesheet" href="{{ url_for('static', filename='rank.css') }}"></head>
<body><main id="rank"></main><script src="{{ url_for('static', filename='rank.js') }}"></script></body></html>
```

with empty `static/rank.css` and `static/rank.js` files.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/web/test_api.py -q`
Expected: PASS.

- [ ] **Step 5: Lint, types, commit**

```bash
uv run ruff check . && uv run mypy
git add src/movie_brain/web/app.py src/movie_brain/web/templates/rank.html src/movie_brain/web/static/rank.js src/movie_brain/web/static/rank.css tests/web/test_api.py
git commit -m "nine routes expose the ranker; a stale pair is a 409 so a second tab can never misfile a click"
```

---

### Task 6: The `/rank` page

**Files:**
- Modify: `src/movie_brain/web/templates/rank.html`, `static/rank.js`, `static/rank.css`
- Create: `tests/web/test_rank_page.py`

**Interfaces:**
- Consumes: the §6 routes (Task 5) and `GET /api/films/<id>` (existing: `payload.Poster/Runtime/Actors/Plot`, `credits.cast`, `overview`, `imdb`, `metacritic`, `my_rating`, `director`, `year`).
- Produces: DOM contract the Playwright test pins — `#setup` with `.anchor-card[data-tier]` each holding `.anchor-title`, a `select.anchor-swap` and `#start`; `#pair` with `.side.candidate` / `.side.anchor`, each holding `button.better`, `button.unseen[aria-pressed]`, `img.poster|.poster.placeholder`, `.title`, `.meta`, `.prompt`; `#pass`; `#undo`; `#progress` with `#placed`, `#remaining`, `#unseen-count`, `.tally span[data-tier]`; `#save` + `#list-name`; `#done`; `main#rank[data-state]` = `setup|pair|needs_anchor|done` set after every render (tests wait on it).

- [ ] **Step 1: Write the failing Playwright test**

`tests/web/test_rank_page.py`:

```python
from __future__ import annotations

import socket
import threading
import time
from collections.abc import Generator
from datetime import date

import pytest
from playwright.sync_api import Page, expect

from movie_brain.domain.models import Film, OmdbRating
from movie_brain.infrastructure.database import Repository
from movie_brain.web.app import create_app

TODAY = date(2026, 9, 13)
POSTER = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


def seed(repo: Repository) -> None:
    # Five rated owned films, one per tier, plus three unrated: the queue has three candidates.
    for title, score in (("Ten", 10), ("Nine", 9), ("Eight", 8), ("Seven", 7), ("Four", 4)):
        fid = repo.create_film(Film(title, 1950, "Dir", ""))
        repo.mark_owned(fid, TODAY)
        repo.set_rating(fid, score, TODAY)
        repo.upsert_omdb(fid, OmdbRating(7.0, None, True, "English", f'{{"Title":"{title}","Poster":"{POSTER}","Runtime":"90 min","Plot":"Plot of {title}."}}'), TODAY)
    for title in ("Uno", "Dos", "Tres"):
        fid = repo.create_film(Film(title, 1960, "Dir", ""))
        repo.mark_owned(fid, TODAY)


@pytest.fixture(scope="module")
def rank_server(tmp_path_factory: pytest.TempPathFactory) -> Generator[str, None, None]:
    root = tmp_path_factory.mktemp("rank")
    repo = Repository(root / "movie-brain.db")
    seed(repo)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    app = create_app(repo, today=lambda: TODAY, lists_dir=root / "lists")
    threading.Thread(target=lambda: app.run(host="127.0.0.1", port=port, use_reloader=False), daemon=True).start()
    time.sleep(0.5)
    yield f"http://127.0.0.1:{port}"


def test_rank_flow(page: Page, rank_server: str):
    page.goto(rank_server + "/rank")
    page.wait_for_selector('#rank[data-state="setup"]')
    cards = page.locator(".anchor-card")
    expect(cards).to_have_count(5)
    expect(cards.nth(2).locator(".anchor-title")).to_have_text("Eight")
    page.click("#start")
    page.wait_for_selector('#rank[data-state="pair"]')
    expect(page.locator(".side.anchor .title")).to_have_text("Eight")
    expect(page.locator(".side.anchor .prompt")).to_contain_text("Plot of Eight.")
    expect(page.locator(".side.anchor img.poster")).to_have_count(1)
    expect(page.locator(".side.candidate .poster.placeholder")).to_have_count(1)  # unrated seeds have no OMDb row
    first = page.locator(".side.candidate .title").inner_text()
    # ← ← : better than tier 3, better than tier 2 → tier 1.
    page.keyboard.press("ArrowLeft")
    expect(page.locator(".side.anchor .title")).to_have_text("Nine")
    page.keyboard.press("ArrowLeft")
    expect(page.locator('#progress .tally span[data-tier="1"]')).to_have_text("2")
    expect(page.locator(".side.candidate .title")).not_to_have_text(first)
    expect(page.locator("#remaining")).to_have_text("2")
    # Undo brings the first candidate straight back, mid-search.
    page.keyboard.press("u")
    expect(page.locator(".side.candidate .title")).to_have_text(first)
    expect(page.locator(".side.anchor .title")).to_have_text("Nine")
    page.keyboard.press("ArrowLeft")
    # Mark the anchor unseen; the page stays put; Pass empties tier 3 and shows its setup card.
    page.click(".side.anchor button.unseen")
    expect(page.locator(".side.anchor button.unseen")).to_have_attribute("aria-pressed", "true")
    expect(page.locator('#rank[data-state="pair"]')).to_have_count(1)
    page.keyboard.press("Space")
    page.wait_for_selector('#rank[data-state="needs_anchor"]')
    expect(page.locator(".anchor-card")).to_have_count(1)
    expect(page.locator(".anchor-card")).to_have_attribute("data-tier", "3")
    page.select_option(".anchor-card select.anchor-swap", label="Dos")
    page.click("#start")
    page.wait_for_selector('#rank[data-state="pair"]')
    # Pass also deferred the candidate (nothing was marked on it), so the third unrated film
    # comes up now, against the tier-3 slot's new anchor.
    expect(page.locator(".side.anchor .title")).to_have_text("Dos")
    expect(page.locator("#unseen-count")).to_have_text("1")
    # Save, then the dashboard's picker lists it.
    page.fill("#list-name", "Mine")
    page.click("#save")
    expect(page.locator("#save-note")).to_contain_text("saved")
    page.goto(rank_server + "/")
    page.wait_for_selector("#films tbody[data-count]")
    expect(page.locator("#list-picker option", has_text="Mine (")).to_have_count(1)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/web/test_rank_page.py -q`
Expected: FAIL — timeout waiting for `#rank[data-state="setup"]`.

- [ ] **Step 3: Write the template**

`rank.html`:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>movie-brain · rank</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="stylesheet" href="{{ url_for('static', filename='rank.css') }}">
</head>
<body>
  <header class="top">
    <h1><a href="/">movie-brain</a> · rank</h1>
    <div id="progress" hidden>
      <span><b id="placed">–</b> placed</span>
      <span><b id="remaining">–</b> remaining</span>
      <span><b id="unseen-count">–</b> unseen</span>
      <span class="tally"><span data-tier="1">–</span><span data-tier="2">–</span><span data-tier="3">–</span><span data-tier="4">–</span><span data-tier="5">–</span></span>
      <button id="undo" class="chip" title="Undo the last click (U)">Undo</button>
      <span class="save-row"><input id="list-name" placeholder="My owned films, tiered"><button id="save" class="chip">Save as list</button><span id="save-note"></span></span>
    </div>
  </header>
  <main id="rank" data-state="">
    <section id="setup" hidden>
      <p id="setup-lead"></p>
      <div id="anchor-cards"></div>
      <button id="start" class="chip primary">Start</button>
    </section>
    <section id="pair" hidden>
      <div class="pass-row"><button id="pass" class="chip primary" title="Next matchup (space)">Pass</button></div>
      <div class="sides">
        <div class="side candidate" data-side="candidate"></div>
        <div class="side anchor" data-side="anchor"></div>
      </div>
    </section>
    <section id="done" hidden><p>Every owned film is placed. Save the list above.</p></section>
  </main>
  <script src="{{ url_for('static', filename='rank.js') }}"></script>
</body>
</html>
```

- [ ] **Step 4: Write the stylesheet**

`rank.css`:

```css
:root { --bg:#fff; --fg:#1b1b1b; --muted:#6b6b6b; --line:#e3e3e3; --accent:#b3261e; --chip:#f2f2f2; --chip-on:#1b1b1b; }
* { box-sizing: border-box; }
body { margin:0; font: 14px/1.4 -apple-system, system-ui, "Segoe UI", sans-serif; color:var(--fg); background:var(--bg); }
.top { position: sticky; top:0; background:var(--bg); border-bottom:1px solid var(--line); padding:10px 16px; z-index:2; }
.top h1 { margin:0 0 4px; font-size:18px; }
.top h1 a { color:inherit; text-decoration:none; }
#progress span { margin-right:14px; color:var(--muted); }
#progress b { color:var(--fg); }
.tally span { display:inline-block; min-width:22px; text-align:center; border:1px solid var(--line); border-radius:4px; margin-right:2px; color:var(--fg); }
.tally span::before { content: attr(data-tier) " · "; color:var(--muted); }
.chip { border:1px solid var(--line); background:var(--chip); border-radius:999px; padding:4px 10px; cursor:pointer; font:inherit; }
.chip.primary { background:var(--chip-on); color:#fff; border-color:var(--chip-on); }
.chip[aria-pressed="true"] { background:var(--accent); color:#fff; border-color:var(--accent); }
.save-row input { border:1px solid var(--line); border-radius:4px; padding:4px 8px; font:inherit; margin-right:6px; }
main { padding:16px; max-width:1100px; margin:0 auto; }
#anchor-cards { display:flex; gap:12px; flex-wrap:wrap; margin:12px 0; }
.anchor-card { border:1px solid var(--line); border-radius:8px; padding:10px; width:200px; }
.anchor-card .tier { color:var(--muted); font-size:12px; }
.anchor-card .anchor-title { font-weight:600; }
.anchor-card select { width:100%; margin-top:6px; font:inherit; }
.pass-row { text-align:center; margin-bottom:12px; }
.pass-row .chip { font-size:16px; padding:8px 22px; }
.sides { display:flex; gap:24px; }
.side { flex:1; border:1px solid var(--line); border-radius:8px; padding:12px; }
.side .buttons { display:flex; gap:8px; justify-content:center; margin-bottom:10px; }
.side .buttons .chip { font-size:15px; padding:8px 18px; }
.side .heading { color:var(--muted); font-size:12px; text-align:center; margin-bottom:6px; }
.side .poster { display:block; margin:0 auto 10px; max-height:360px; max-width:100%; }
.side .poster.placeholder { width:240px; height:360px; background:var(--chip); border-radius:4px; }
.side .title { font-size:20px; font-weight:600; text-align:center; }
.side .title button { all:unset; cursor:pointer; }
.side .meta { text-align:center; color:var(--muted); margin-bottom:8px; }
.side .prompt { font-size:13px; }
.side .prompt dt { color:var(--muted); display:inline; }
.side .prompt dd { display:inline; margin:0 0 0 4px; }
.side .prompt div { margin-bottom:4px; }
```

- [ ] **Step 5: Write the script**

`rank.js`:

```javascript
(() => {
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const $ = (sel) => document.querySelector(sel);
  const main = $('#rank');
  const state = { session: null, marked: { candidate: false, anchor: false }, details: {} };

  const api = async (method, url, body) => {
    const r = await fetch(url, { method, headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined });
    const json = await r.json().catch(() => ({}));
    if (!r.ok) { note(json.error || `${method} ${url} failed`); throw new Error(json.error || r.status); }
    return json;
  };
  const note = (text) => { const n = $('#save-note'); n.textContent = text; setTimeout(() => { if (n.textContent === text) n.textContent = ''; }, 4000); };

  const show = (which) => {
    for (const id of ['setup', 'pair', 'done']) $('#' + id).hidden = id !== which;
    $('#progress').hidden = !state.session || !state.session.session;
  };

  // --- setup / needs-anchor -------------------------------------------------
  const renderSetup = async (tiers, lead) => {
    const prop = await api('GET', '/api/rank/proposal');
    $('#setup-lead').textContent = lead;
    $('#anchor-cards').innerHTML = tiers.map((t) => {
      const p = prop.proposal[t];
      const choices = prop.choices[t] || [];
      const opts = choices.map((c) => `<option value="${c.film_id}" ${p && c.film_id === p.film_id ? 'selected' : ''}>${esc(c.title)}${c.year ? ` (${c.year})` : ''}${c.score != null ? ` · ${c.score}` : ''}</option>`).join('');
      return `<div class="anchor-card" data-tier="${t}"><div class="tier">Tier ${t} anchor</div><div class="anchor-title">${p ? esc(p.title) : '— choose —'}</div><select class="anchor-swap" data-tier="${t}"><option value="">choose…</option>${opts}</select></div>`;
    }).join('');
    show('setup');
    main.dataset.state = tiers.length === 5 ? 'setup' : 'needs_anchor';
  };

  $('#anchor-cards').addEventListener('change', (e) => {
    const sel = e.target.closest('select.anchor-swap'); if (!sel) return;
    const card = sel.closest('.anchor-card');
    card.querySelector('.anchor-title').textContent = sel.selectedOptions[0]?.textContent.replace(/ · \d+$/, '') || '— choose —';
  });

  $('#start').addEventListener('click', async () => {
    const cards = [...document.querySelectorAll('.anchor-card')];
    const chosen = Object.fromEntries(cards.map((c) => [c.dataset.tier, Number(c.querySelector('select').value) || null]));
    if (Object.values(chosen).some((v) => !v)) { note('Choose an anchor for every tier shown'); return; }
    if (!state.session || !state.session.session) {
      await api('POST', '/api/rank/session', { anchors: chosen });
    } else {
      for (const [tier, film_id] of Object.entries(chosen)) await api('PUT', '/api/rank/anchor', { tier: Number(tier), film_id });
    }
    await refresh();
  });

  // --- the pair -------------------------------------------------------------
  const detail = async (id) => {
    if (!state.details[id]) state.details[id] = await fetch(`/api/films/${id}`).then((r) => r.json());
    return state.details[id];
  };

  const sideHtml = (side, d, heading, marked) => {
    const p = d.payload || {};
    const poster = p.Poster && p.Poster !== 'N/A' ? `<img class="poster" src="${esc(p.Poster)}" alt="">` : '<div class="poster placeholder"></div>';
    const cast = d.credits && d.credits.cast && d.credits.cast.length ? d.credits.cast.slice(0, 4).map((c) => c.name).join(', ') : (p.Actors && p.Actors !== 'N/A' ? p.Actors : '');
    const blurb = d.overview || (p.Plot && p.Plot !== 'N/A' ? p.Plot : '');
    const prompts = [
      blurb ? `<div>${esc(blurb)}</div>` : '',
      cast ? `<div><dt>Cast</dt><dd>${esc(cast)}</dd></div>` : '',
      p.Runtime && p.Runtime !== 'N/A' ? `<div><dt>Runtime</dt><dd>${esc(p.Runtime)}</dd></div>` : '',
      d.imdb != null || d.metacritic != null ? `<div><dt>IMDb</dt><dd>${d.imdb ?? '–'}</dd> · <dt>Metacritic</dt><dd>${d.metacritic ?? '–'}</dd></div>` : '',
      d.my_rating != null ? `<div><dt>My rating</dt><dd>${d.my_rating}</dd></div>` : '',
    ].join('');
    const dirYear = [d.year, d.director].filter(Boolean).join(' · ');
    return `<div class="heading">${esc(heading)}</div>
      <div class="buttons"><button class="chip primary better" data-side="${side}" title="${side === 'candidate' ? '←' : '→'}">Better</button><button class="chip unseen" data-side="${side}" aria-pressed="${marked}" title="${side === 'candidate' ? '1' : '2'}">Have not seen</button></div>
      ${poster}
      <div class="title"><button class="title-unseen" data-side="${side}">${esc(d.title)}</button></div>
      <div class="meta">${esc(dirYear)}</div>
      <dl class="prompt">${prompts}</dl>`;
  };

  const renderPair = async () => {
    const s = state.session;
    const [c, a] = await Promise.all([detail(s.pair.candidate.film_id), detail(s.pair.anchor.film_id)]);
    $('.side.candidate').innerHTML = sideHtml('candidate', c, 'Candidate', state.marked.candidate);
    $('.side.anchor').innerHTML = sideHtml('anchor', a, `Tier ${s.pair.tier} anchor`, state.marked.anchor);
    show('pair');
    main.dataset.state = 'pair';
  };

  const renderProgress = () => {
    const s = state.session;
    if (!s || !s.session) return;
    $('#placed').textContent = s.placed; $('#remaining').textContent = s.remaining; $('#unseen-count').textContent = s.unseen;
    for (const [t, n] of Object.entries(s.tally)) $(`#progress .tally span[data-tier="${t}"]`).textContent = n;
    $('#undo').disabled = !s.can_undo;
  };

  const refresh = async () => {
    state.session = await api('GET', '/api/rank/session');
    state.marked = { candidate: false, anchor: false };
    renderProgress();
    const s = state.session;
    if (!s.session) return renderSetup([1, 2, 3, 4, 5], 'Confirm or swap the five anchors, then start.');
    if (s.needs_anchor.length) return renderSetup(s.needs_anchor, 'That anchor is out. Pick a replacement for the tier.');
    if (s.done) { show('done'); main.dataset.state = 'done'; return; }
    return renderPair();
  };

  const verdict = async (side) => {
    const s = state.session; if (!s || !s.pair) return;
    await api('POST', '/api/rank/verdict', { film_id: s.pair.candidate.film_id, anchor_tier: s.pair.tier, verdict: side === 'candidate' ? 'better' : 'worse' });
    await refresh();
  };
  const toggleMark = (side) => {
    state.marked[side] = !state.marked[side];
    const b = document.querySelector(`.side.${side} button.unseen`); if (b) b.setAttribute('aria-pressed', String(state.marked[side]));
  };
  const pass = async () => {
    const s = state.session; if (!s || !s.pair) return;
    await api('POST', '/api/rank/pass', { film_id: s.pair.candidate.film_id, candidate_unseen: state.marked.candidate, anchor_unseen: state.marked.anchor });
    await refresh();
  };
  const undo = async () => { if ($('#undo').disabled) return; await api('POST', '/api/rank/undo'); await refresh(); };

  $('#pair').addEventListener('click', (e) => {
    const better = e.target.closest('button.better'); if (better) return verdict(better.dataset.side);
    const un = e.target.closest('button.unseen, button.title-unseen'); if (un) return toggleMark(un.dataset.side);
  });
  $('#pass').addEventListener('click', pass);
  $('#undo').addEventListener('click', undo);
  $('#save').addEventListener('click', async () => {
    const r = await api('POST', '/api/rank/save', { name: $('#list-name').value });
    note(`saved ${r.entries} films as “${r.name}”`);
  });

  document.addEventListener('keydown', (e) => {
    if (e.target.matches('input, select, textarea') || main.dataset.state !== 'pair') return;
    const k = e.key;
    if (k === 'ArrowLeft') { e.preventDefault(); verdict('candidate'); }
    else if (k === 'ArrowRight') { e.preventDefault(); verdict('anchor'); }
    else if (k === '1') toggleMark('candidate');
    else if (k === '2') toggleMark('anchor');
    else if (k === ' ') { e.preventDefault(); pass(); }
    else if (k === 'u' || k === 'U') undo();
  });

  refresh();
})();
```

- [ ] **Step 6: Run the Playwright test**

Run: `uv run pytest tests/web/test_rank_page.py -q`
Expected: PASS. If `select_option(label="Dos")` fails, the option label is `Dos (1960)` — use `label="Dos (1960)"`.

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check . && uv run mypy
git add src/movie_brain/web/templates/rank.html src/movie_brain/web/static/rank.js src/movie_brain/web/static/rank.css tests/web/test_rank_page.py
git commit -m "the rank page is two posters and three buttons, with every click a request and no state of its own"
```

---

### Task 7: Dashboard hooks and the `lists import` guard

**Files:**
- Modify: `src/movie_brain/web/templates/index.html` (header, line 11), `static/app.js` (drawer `<h2>` line 574 and the toggle handlers ~660–678), `static/app.css`
- Modify: `src/movie_brain/cli.py` (`lists_import_cmd`, after `read_list_file`)
- Test: `tests/web/test_dashboard.py` (append), `tests/unit/test_cli.py` (append)

**Interfaces:**
- Consumes: `PUT /api/films/<id>/unseen` (Task 5), `FilmView.unseen` (Task 1), `RANKER_LIST_SLUGS` (Task 2).

- [ ] **Step 1: Write the failing tests**

Append to `tests/web/test_dashboard.py`:

```python
def test_header_links_to_the_rank_page(dash: Page):
    expect(dash.locator("header a.rank-link")).to_have_attribute("href", "/rank")


def test_drawer_unseen_toggle_round_trips(dash: Page):
    body = _open(dash, "Charlie")
    toggle = body.locator("button.unseen-toggle")
    expect(toggle).to_have_attribute("aria-pressed", "false")
    toggle.click()
    expect(toggle).to_have_attribute("aria-pressed", "true")
    dash.reload()
    dash.wait_for_selector("#films tbody[data-count]")
    body = _open(dash, "Charlie")
    expect(body.locator("button.unseen-toggle")).to_have_attribute("aria-pressed", "true")
    body.locator("button.unseen-toggle").click()
    expect(body.locator("button.unseen-toggle")).to_have_attribute("aria-pressed", "false")
```

Append to `tests/unit/test_cli.py`:

```python
def test_lists_import_refuses_a_ranker_slug(config_dir, tmp_path):
    f = tmp_path / "my-owned-tiers.tsv"
    f.write_text("# slug: my-owned-tiers\n# name: Mine\n1\tAlpha\tAnn\n")
    r = runner.invoke(app, ["lists", "import", str(f)])
    assert r.exit_code == 2
    assert "ranker" in r.output
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/web/test_dashboard.py -q -k "rank_page or unseen_toggle" && uv run pytest tests/unit/test_cli.py -q -k ranker`
Expected: both FAIL.

- [ ] **Step 3: Implement**

`index.html` line 11: `<h1>movie-brain <a class="rank-link" href="/rank" title="Rank owned films into tiers">Rank</a></h1>`.

`app.css`, after `.top h1`: `.top h1 a.rank-link { font-size:13px; font-weight:normal; margin-left:10px; color:var(--muted); }`.

`app.js` line 574: append to the `<h2>` a third button after the revisit toggle:

```javascript
<button class="unseen-toggle" data-id="${d.id}" aria-pressed="${d.unseen ? 'true' : 'false'}" title="Toggle unseen (the ranker skips it)">Unseen</button>
```

Next to the revisit handler (~line 670) add:

```javascript
  body.addEventListener('click', async (e) => {
    const b = e.target.closest('.unseen-toggle'); if (!b) return;
    const next = b.getAttribute('aria-pressed') !== 'true';
    const r = await fetch(`/api/films/${b.dataset.id}/unseen`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ unseen: next }) });
    if (!r.ok) { toast('Could not update unseen'); return; }
    const { unseen } = await r.json();
    b.setAttribute('aria-pressed', String(unseen));
    const film = state.films.find((f) => f.id === Number(b.dataset.id));
    if (film) film.unseen = unseen;
  });
```

(Use the same `body` element the revisit handler is attached to — read those lines first and mirror their variable names exactly; `state.films` is the loaded list — confirm the name at the top of `app.js` and adjust.) Add `.unseen-toggle { margin-left:6px; font-size:12px; }` and `.unseen-toggle[aria-pressed="true"] { background:var(--accent); color:#fff; border-color:var(--accent); }` to `app.css` beside the drawer rules.

`cli.py`, in `lists_import_cmd` right after `parsed = read_list_file(path)` succeeds:

```python
    from movie_brain.domain.rank import RANKER_LIST_SLUGS

    if parsed.meta.slug in RANKER_LIST_SLUGS:
        err.print(f"{parsed.meta.slug!r} belongs to the tier ranker (saved from /rank), not to a list file — refusing")
        raise typer.Exit(2)
```

- [ ] **Step 4: Run to verify they pass, then the whole suite**

Run: `uv run pytest -q`
Expected: PASS across the board (the dashboard's existing drawer-order test still passes because the new button sits in the `<h2>`, before every mark it checks).

- [ ] **Step 5: Lint, types, commit**

```bash
uv run ruff check . && uv run mypy
git add src/movie_brain/web/templates/index.html src/movie_brain/web/static/app.js src/movie_brain/web/static/app.css src/movie_brain/cli.py tests/web/test_dashboard.py tests/unit/test_cli.py
git commit -m "the dashboard reaches the ranker and can mark a film unseen; a list file can never claim the ranker's slug"
```

---

### Task 8: Documentation

**Files:**
- Modify: `CLAUDE.md` (Commands block: none — no new CLI verb; Rules: one new bullet after the `needs_revisit` bullet; the `web/` architecture line), `docs/backlog.md` (one new numbered item), `.claude/rules/lists.md` (one bullet), `docs/superpowers/specs/2026-09-13-tier-ranker-design.md` (§3 note)

- [ ] **Step 1: CLAUDE.md**

In the `web/` architecture bullet, after "the id set is the whole interface, and no chip, scope, list or column logic moved." append: ` A second page, \`/rank\` (\`rank.html\` + \`static/rank.js\` + \`rank.css\`, never \`app.js\`), is the tier ranker.`

New rules bullet (one line, no hard wraps), placed after the `needs_revisit` bullet:

> - **Tier ranker** (spec `docs/superpowers/specs/2026-09-13-tier-ranker-design.md`, migration 022): `/rank` places owned films into five tiers by binary search against one anchor film per tier (`domain/rank.py::next_step`, nine legal verdict sequences, `better`/`worse` only — no `same`); seeded from `my_ratings` (`tier_for_score`: 10→1, 9→2, 8→3, 7→4, ≤6→5) which it NEVER writes; tables `rank_session` (one open per source, `last_action` = one-level undo), `rank_anchor`, `rank_placement` (the result; `how` ∈ seed/compared/anchor), `rank_comparison` (append-only log, never read to compute a tier), `rank_deferral`, and `unseen` (durable pass bucket on the watchlist pattern — `set_unseen` and the drawer's toggle are the only writers; marking a film unseen deletes its placements in every session). The queue is derived per request (owned − placed − unseen − anchors, seeded shuffle by `queue_key`, films mid-search first, deferrals last) and never stored. Save writes `film_list` slug `my-owned-tiers` (`RANKER_SLUGS`, `curator = 'me'`, tied `rank_label`s per tier, trust untouched) through `replace_list_entries`; `lists import` refuses a ranker slug and the save refuses a slug with a `lists/<slug>.tsv`. `merge_film` moves all six tables survivor-wins.

- [ ] **Step 2: backlog.md** — add item:

> 16. [ ] **Strict-order the top tier** — the ranker (2026-09-13) stops at five tiers by design (spec D6). Once the top tier's size is known from a saved `my-owned-tiers`, binary-insert its members among themselves (log₂ of the tier size per film) and write proper ranks for that tier only. Second source (`film_list` slug) is the other deferred half (D7).

- [ ] **Step 3: lists.md** — add bullet:

> - `my-owned-tiers` (and every slug in `domain/rank.py::RANKER_LIST_SLUGS`) is written by the tier ranker's save, not by a list file: no `lists/<slug>.tsv` exists, `lists import` exits 2 on such a slug, and `Repository.replace_list_entries` (its writer) rewrites the slug's entries whole and linked — the one list whose entries are NOT append-only. `trust` is still owned by `lists trust` alone.

- [ ] **Step 4: spec §3** — after the SQL block add one paragraph: "Implementation note (plan 2026-09-13): `rank_session` also carries `last_action TEXT` (JSON), the concrete form of §4.4's action log, giving one level of undo; and `rank_placement.how` admits `anchor` for a film swapped in as a tier's anchor while unplaced, which is the only way an empty tier gets one (§4.5)."

- [ ] **Step 5: Verify markdown has no hard wraps, commit**

Run: `~/code/praxis-workspace/praxis-halo/bin/unwrap-md CLAUDE.md docs/backlog.md .claude/rules/lists.md docs/superpowers/specs/2026-09-13-tier-ranker-design.md` then `git diff --stat`.

```bash
git add CLAUDE.md docs/backlog.md .claude/rules/lists.md docs/superpowers/specs/2026-09-13-tier-ranker-design.md
git commit -m "the ranker's contract is written where the next session will look for it"
```

---

### Task 9: Apply live and hand off

**Files:** none in the repo (live DB only).

- [ ] **Step 1: Migrate the live DB** — `uv run movie-brain migrate` (dry run, expect `022_tier_ranker.sql` pending), then `uv run movie-brain migrate --apply` (a backup lands in `<config_dir>/backups/`).
- [ ] **Step 2: Smoke** — `uv run movie-brain dashboard`, open `http://127.0.0.1:5556/rank`, confirm the five proposed anchors are films the owner rated 10 / 9 / 8 / 7 / ≤6, click through three candidates, press Undo once, open `/` and toggle Unseen on one film in the drawer, return to `/rank` and confirm that film is not offered.
- [ ] **Step 3: Report** the proposed anchors and the first three pairs to the owner before any real session; the owner runs the session themselves.
