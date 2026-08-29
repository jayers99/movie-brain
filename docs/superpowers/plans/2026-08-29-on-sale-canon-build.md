# On Sale — canon queue build (items 0, 1, 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the owner a canon-ranked acquisition queue in the dashboard, and fill the IMDb-id gap that blocks every identity join the queue depends on.

**Architecture:** Three independent increments in a fixed order. (1) A quiet IMDb backfill — a new `repair imdb` verb that reads each film's own TMDB id, asks TMDB for the IMDb id it publishes, and writes it through `key_film` with the TMDB half deliberately untouched, so no year moves. (0) Two ten-entry Sight & Sound 1992 list files imported through the existing two-verb list flow, which will link every entry and create nothing. (2) A `canon_score` computed from `FilmView.lists` and an `acquire` chip carrying the §2 gate, both defined canonically in `domain/filters.py` and mirrored in `static/app.js`, with no schema change anywhere.

**Tech Stack:** Python 3.12 · Typer CLI · SQLite (`Repository`) · Flask + vanilla JS dashboard · pytest, pytest-bdd, Playwright · `uv` for everything.

**Spec:** `docs/superpowers/specs/2026-08-29-on-sale-canon-acquisition-design.md`

## Global Constraints

- **Gates after every task, all five, all green:** `uv run pytest` · `uv run ruff check .` · `uv run mypy` · `uv run python scripts/thumbprint_benchmark.py --assert` (baseline **n=571 / WRONG=0 / 92.0% over 526**) · `uv run python scripts/matching_benchmark.py --assert-dominance`.
- **Never write `scripts/eval/thumbprint_eval_v1.csv` or the resolver fixture.** A backfilled id is TMDB's assertion, not resolver ground truth.
- **`application/keying.py::key_film` is the ONE identity write path.** Never call `repo.set_external_id(..., "imdb", ...)` directly from new code.
- **No schema change in this plan.** The live DB stays at schema v16; migration 017 remains unwritten. If a task appears to need a migration, stop and report — it means the plan is wrong.
- **Films are immutable.** Nothing here deletes a film, and nothing merges one.
- **Every command that touches a database in rehearsal sets `MOVIE_BRAIN_CONFIG_DIR` to the scratch directory — subagents included.** No exceptions, no "just this one read".
- **Live DB facts (verified 2026-08-29):** 4,735 films · 4,538 hold a TMDB id · 850 hold an IMDb id · **3,699 hold TMDB and no IMDb** · 1,236 of those are commerce-created (no Criterion listing).
- **Markdown is never hard-wrapped.** One unbroken line per paragraph, list item and blockquote.
- **Commit messages are a brief single line about *why*, not what.**

---

## File Structure

**Item 1 — the backfill**

| file | responsibility |
|---|---|
| `src/movie_brain/domain/models.py` | add `ImdbBackfillTarget` — the worklist row (film_id, title, year, tmdb_id) |
| `src/movie_brain/infrastructure/database.py` | add `Repository.films_needing_imdb_backfill(limit)` — the one query that defines the worklist |
| `src/movie_brain/application/backfill_imdb.py` | **new file.** The use case: one film at a time, `tmdb.imdb_id` then `key_film`. Nothing else lives here |
| `src/movie_brain/cli.py` | wire `repair imdb` |
| `tests/features/backfill_imdb.feature` + `tests/step_defs/test_backfill_imdb.py` | the application scenarios (outside-in, written first) |
| `tests/unit/test_database.py` | the worklist query's own tests |
| `tests/unit/test_cli.py` | the verb's wiring test |

**Item 0 — the 1992 lists**

| file | responsibility |
|---|---|
| `lists/sight-and-sound-1992-critics.tsv` | checked-in artifact, 10 entries, trust 8 |
| `lists/sight-and-sound-1992-directors.tsv` | checked-in artifact, 12 entries, trust 6 |
| `tests/unit/test_listfile.py` | parse assertions for both files, including the tie labels |

**Item 2 — the ranked queue**

| file | responsibility |
|---|---|
| `src/movie_brain/infrastructure/database.py` | add `size` to `_LISTS_SQL` / `_lists_by_film` |
| `src/movie_brain/domain/models.py` | document `size` in the `FilmView.lists` comment |
| `src/movie_brain/domain/filters.py` | **canonical** `canon_score`, `acquisition_candidate`, the `acquire` chip |
| `src/movie_brain/web/static/app.js` | the JS mirror of both, plus the acquire-chip sort lead |
| `src/movie_brain/web/templates/index.html` | the chip button |
| `tests/unit/test_filters.py` | score + predicate tests, and the Python/JS parity test |
| `tests/web/test_dashboard.py` | the chip end to end |

---

# Item 1 — the quiet IMDb backfill

### Task 1: The worklist scenarios (outside-in, failing first)

**Files:**
- Create: `tests/features/backfill_imdb.feature`
- Create: `tests/step_defs/test_backfill_imdb.py`

**Interfaces:**
- Consumes: nothing.
- Produces: the behavioural contract every later task in item 1 satisfies. Names fixed here and used by Tasks 2–4: `movie_brain.application.backfill_imdb.backfill_imdb(repo, tmdb, today, *, apply=False, limit=None, log=...) -> BackfillReport`, and `BackfillReport(scanned: int, backfilled: int, no_imdb: int, held: int, failed: int, aborted: bool)`.

- [ ] **Step 1: Write the feature file**

```gherkin
Feature: Backfilling IMDb ids from the TMDB ids we already hold

  A film holding a TMDB id and no IMDb id cannot be joined to any external
  authority. The backfill asks TMDB for the id it publishes for that exact
  TMDB id and writes it through key_film — writing the IMDb id ALONE, so no
  film's year moves as a side effect of filling in a missing id.

  Background:
    Given a film "Rio Bravo" (1959) holding tmdb id 10767 and no imdb id
    And TMDB publishes imdb id "tt0053221" for tmdb id 10767

  Scenario: A dry run writes nothing
    When I back fill imdb ids without applying
    Then the report counts 1 scanned and 1 backfilled
    And the film "Rio Bravo" still holds no imdb id

  Scenario: Applying writes the imdb id and leaves the tmdb id alone
    When I back fill imdb ids with apply
    Then the film "Rio Bravo" holds imdb id "tt0053221"
    And the film "Rio Bravo" still holds tmdb id 10767

  Scenario: A commerce film's year is never moved by the backfill
    Given the film "Rio Bravo" has no criterion listing
    And TMDB reports the year 1958 for tmdb id 10767
    When I back fill imdb ids with apply
    Then the film "Rio Bravo" still has year 1959

  Scenario: An id already held by another film queues a review row instead of overwriting
    Given a film "Rio Bravo (1959)" already holds imdb id "tt0053221"
    When I back fill imdb ids with apply
    Then the report counts 1 held
    And an open tmdb review row exists for "Rio Bravo" with reason "id-conflict"
    And the film "Rio Bravo" still holds no imdb id

  Scenario: TMDB publishing no imdb id is counted, not written
    Given TMDB publishes no imdb id for tmdb id 10767
    When I back fill imdb ids with apply
    Then the report counts 1 no-imdb
    And the film "Rio Bravo" still holds no imdb id

  Scenario: An OMDb refetch is queued so the next sync fills in director and ratings
    When I back fill imdb ids with apply
    Then the film "Rio Bravo" is marked for an OMDb refresh
```

- [ ] **Step 2: Write the step definitions**

Model the file on `tests/step_defs/test_thumbprint_nomatch.py`'s structure (scenario loading, `repo` and `today` fixtures from `tests/conftest.py`). The fake TMDB client is the only new machinery:

```python
from dataclasses import dataclass, field

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.backfill_imdb import backfill_imdb

scenarios("../features/backfill_imdb.feature")


@dataclass
class FakeTmdb:
    """Only the two calls the backfill is allowed to make."""

    imdb_ids: dict[int, str | None] = field(default_factory=dict)
    years: dict[int, int] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def imdb_id(self, tmdb_id: int) -> str | None:
        self.calls.append(f"imdb_id({tmdb_id})")
        return self.imdb_ids.get(tmdb_id)

    def movie_year(self, tmdb_id: int) -> int | None:
        self.calls.append(f"movie_year({tmdb_id})")
        return self.years.get(tmdb_id)


@pytest.fixture
def tmdb() -> FakeTmdb:
    return FakeTmdb()


@pytest.fixture
def result() -> dict:
    return {}
```

Write one `@given`/`@when`/`@then` per line of the feature above. Create films with `repo.create_film(...)` and ids with `repo.set_external_id(film_id, "tmdb", "10767", today)` — direct `set_external_id` is fine **in test setup**; the production rule forbids it only in `src/`.

- [ ] **Step 3: Run the scenarios to verify they fail**

Run: `uv run pytest tests/step_defs/test_backfill_imdb.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'movie_brain.application.backfill_imdb'`

- [ ] **Step 4: Commit the failing scenarios**

```bash
git add tests/features/backfill_imdb.feature tests/step_defs/test_backfill_imdb.py
git commit -m "the backfill's contract, written before the backfill"
```

---

### Task 2: The worklist query

**Files:**
- Modify: `src/movie_brain/domain/models.py`
- Modify: `src/movie_brain/infrastructure/database.py`
- Test: `tests/unit/test_database.py`

**Interfaces:**
- Consumes: `_NOT_DISPOSED`, `_IS_MOVIE` (module constants already in `database.py`).
- Produces: `ImdbBackfillTarget(film_id: int, title: str, year: int | None, tmdb_id: int)` and `Repository.films_needing_imdb_backfill(limit: int | None = None) -> list[ImdbBackfillTarget]`, ordered by `f.id`.

- [ ] **Step 1: Write the failing tests**

```python
def test_films_needing_imdb_backfill_finds_tmdb_only_films(repo, today):
    fid = repo.create_film("Rio Bravo", 1959)
    repo.set_external_id(fid, "tmdb", "10767", today)
    targets = repo.films_needing_imdb_backfill()
    assert [(t.film_id, t.tmdb_id, t.title) for t in targets] == [(fid, 10767, "Rio Bravo")]


def test_films_needing_imdb_backfill_skips_films_that_already_have_one(repo, today):
    fid = repo.create_film("Rio Bravo", 1959)
    repo.set_external_id(fid, "tmdb", "10767", today)
    repo.set_external_id(fid, "imdb", "tt0053221", today)
    assert repo.films_needing_imdb_backfill() == []


def test_films_needing_imdb_backfill_skips_disposed_films(repo, today):
    fid = repo.create_film("Rio Bravo", 1959)
    repo.set_external_id(fid, "tmdb", "10767", today)
    survivor = repo.create_film("Rio Bravo", 1959, key_suffix="b")
    repo.record_disposition(fid, "merged", survivor, "test")
    assert repo.films_needing_imdb_backfill() == []


def test_films_needing_imdb_backfill_respects_limit(repo, today):
    for i, title in enumerate(("A", "B", "C")):
        fid = repo.create_film(title, 1959 + i)
        repo.set_external_id(fid, "tmdb", str(100 + i), today)
    assert len(repo.films_needing_imdb_backfill(limit=2)) == 2
```

Check the exact signatures of `create_film` and `record_disposition` in `database.py` before writing, and match them; the shapes above are illustrative of intent, not copied from the source.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_database.py -k imdb_backfill -v`
Expected: FAIL with `AttributeError: 'Repository' object has no attribute 'films_needing_imdb_backfill'`

- [ ] **Step 3: Add the dataclass**

In `domain/models.py`, beside `TmdbMatchTarget`:

```python
@dataclass(frozen=True)
class ImdbBackfillTarget:
    """A film holding a TMDB id and no IMDb id — the whole worklist of `repair imdb`."""

    film_id: int
    title: str
    year: int | None
    tmdb_id: int
```

- [ ] **Step 4: Add the query**

In `database.py`, beside `films_needing_tmdb_match`:

```python
    def films_needing_imdb_backfill(self, limit: int | None = None) -> list[ImdbBackfillTarget]:
        """Films holding a TMDB id and no IMDb id. A series is excluded for the same reason
        the TMDB keying worklist excludes one: its integer id is not a movie id."""
        sql = (
            "SELECT f.id, f.title, f.year, x.value AS tmdb_id FROM films f "
            "JOIN external_ids x ON x.film_id = f.id AND x.authority = 'tmdb' "
            "WHERE " + _NOT_DISPOSED + _IS_MOVIE +
            " AND NOT EXISTS (SELECT 1 FROM external_ids i WHERE i.film_id = f.id AND i.authority = 'imdb')"
            " ORDER BY f.id"
        )
        if limit is not None:
            sql += " LIMIT ?"
        with self._conn() as c:
            rows = c.execute(sql, (limit,) if limit is not None else ()).fetchall()
        return [
            ImdbBackfillTarget(int(r["id"]), str(r["title"]), r["year"], int(r["tmdb_id"]))
            for r in rows
        ]
```

- [ ] **Step 5: Run to verify the tests pass**

Run: `uv run pytest tests/unit/test_database.py -k imdb_backfill -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Run the full gates**

```bash
uv run pytest && uv run ruff check . && uv run mypy \
  && uv run python scripts/thumbprint_benchmark.py --assert \
  && uv run python scripts/matching_benchmark.py --assert-dominance
```

- [ ] **Step 7: Commit**

```bash
git add src/movie_brain/domain/models.py src/movie_brain/infrastructure/database.py tests/unit/test_database.py
git commit -m "the films that can't be joined to anything are now a query"
```

---

### Task 3: The backfill use case

**Files:**
- Create: `src/movie_brain/application/backfill_imdb.py`
- Test: `tests/step_defs/test_backfill_imdb.py` (from Task 1 — it should go green here)

**Interfaces:**
- Consumes: `Repository.films_needing_imdb_backfill` (Task 2), `key_film` and `MAX_CONSECUTIVE_FAILURES` from `application/keying.py`, `queue_review_once` and `TMDB_AUTHORITY` from `application/availability.py`, `ReviewEntry` from `domain/models.py`.
- Produces: `BackfillReport(scanned, backfilled, no_imdb, held, failed, aborted)` and `backfill_imdb(repo, tmdb, today, *, apply=False, limit=None, log=_stderr) -> BackfillReport`.

- [ ] **Step 1: Run the Task 1 scenarios to confirm they still fail**

Run: `uv run pytest tests/step_defs/test_backfill_imdb.py -v`
Expected: FAIL — module not found.

- [ ] **Step 2: Write the module**

```python
"""Fill in the IMDb id TMDB already knows, for films that hold a TMDB id and no IMDb one.

The write goes through `key_film` — the one identity write path — with `tmdb_id=None` and
`resolve_tmdb_id=False`. That pair is deliberate and is the whole point of the verb (spec D10):
the film's TMDB link already exists, so `record_tmdb_match` must not run again. If it did, it
would canonicalize `films.year` on every commerce-created film whose TMDB year differs — 1,236
films — turning "write a missing id" into a year migration nobody asked for.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import requests

from movie_brain.application.availability import TMDB_AUTHORITY, queue_review_once
from movie_brain.application.keying import MAX_CONSECUTIVE_FAILURES, key_film
from movie_brain.domain.models import ReviewEntry
from movie_brain.infrastructure.database import Repository
from movie_brain.infrastructure.tmdb import AuthError, TmdbClient


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


@dataclass(frozen=True)
class BackfillReport:
    scanned: int = 0
    backfilled: int = 0
    no_imdb: int = 0
    held: int = 0
    failed: int = 0
    aborted: bool = False


def backfill_imdb(
    repo: Repository,
    tmdb: TmdbClient,
    today: date,
    *,
    apply: bool = False,
    limit: int | None = None,
    log: Callable[[str], None] = _stderr,
) -> BackfillReport:
    scanned = backfilled = no_imdb = held = failed = 0
    consecutive = 0
    aborted = False
    for target in repo.films_needing_imdb_backfill(limit):
        if consecutive >= MAX_CONSECUTIVE_FAILURES:
            log("TMDB lookups failing repeatedly — stopping; the next run resumes.")
            aborted = True
            break
        scanned += 1
        try:
            tt = tmdb.imdb_id(target.tmdb_id)
        except (requests.RequestException, AuthError) as exc:
            log(f"  #{target.film_id} {target.title!r}: TMDB lookup failed: {exc}")
            consecutive += 1
            failed += 1
            continue
        consecutive = 0
        if not tt:
            log(f"  #{target.film_id} {target.title!r}: TMDB publishes no imdb id for {target.tmdb_id}")
            no_imdb += 1
            continue
        if not apply:
            log(f"  #{target.film_id} {target.title!r} ({target.year}) → {tt}")
            backfilled += 1
            continue
        result = key_film(
            repo, tmdb, target.film_id, tt, today, log, tmdb_id=None, resolve_tmdb_id=False
        )
        if result.status in ("keyed", "unlinked"):
            log(f"  #{target.film_id} {target.title!r} ({target.year}) → {tt}")
            backfilled += 1
            continue
        if result.status == "error":
            log(f"  #{target.film_id} {target.title!r}: {result.detail}")
            consecutive += 1
            failed += 1
            continue
        # held: the id belongs to another film. A twin, and never a silent overwrite.
        queue_review_once(
            repo,
            TMDB_AUTHORITY,
            ReviewEntry(
                "id-conflict",
                film_id=target.film_id,
                value=tt,
                detail=f"{target.title!r} ({target.year}) — {result.detail}, likely twins",
            ),
            today,
        )
        held += 1
    return BackfillReport(scanned, backfilled, no_imdb, held, failed, aborted)
```

- [ ] **Step 3: Run the scenarios**

Run: `uv run pytest tests/step_defs/test_backfill_imdb.py -v`
Expected: PASS — all six scenarios.

If the "year is never moved" scenario passes trivially, prove it can fail: temporarily change the `key_film` call to `tmdb_id=target.tmdb_id, resolve_tmdb_id=False`, re-run, and confirm that scenario now FAILS with the year moved to 1958. Revert the change before continuing. **This is the single most important assertion in the plan — a test that cannot fail is not protecting anything.**

- [ ] **Step 4: Run the full gates**

```bash
uv run pytest && uv run ruff check . && uv run mypy \
  && uv run python scripts/thumbprint_benchmark.py --assert \
  && uv run python scripts/matching_benchmark.py --assert-dominance
```

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/application/backfill_imdb.py tests/
git commit -m "a missing id is filled in without becoming a year migration"
```

---

### Task 4: The `repair imdb` verb

**Files:**
- Modify: `src/movie_brain/cli.py`
- Modify: `CLAUDE.md` (the Commands block)
- Test: `tests/unit/test_cli.py`

**Interfaces:**
- Consumes: `backfill_imdb`, `BackfillReport` (Task 3).
- Produces: `movie-brain repair imdb [--apply] [--limit N]`.

- [ ] **Step 1: Write the failing CLI test**

Model it on the existing `repair links` test in `tests/unit/test_cli.py` (Typer's `CliRunner`, `TmdbClient` monkeypatched). Assert: the verb exists; with no TMDB token it exits 2 and says so; a dry run reports counts and writes nothing.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_cli.py -k repair_imdb -v`
Expected: FAIL — no such command.

- [ ] **Step 3: Wire the verb**

Place it beside `repair_links_cmd` in `cli.py`:

```python
@repair_app.command("imdb")
def repair_imdb_cmd(
    apply: Annotated[bool, typer.Option("--apply", help="Write the imdb ids (default: dry-run).")] = False,
    limit: Annotated[int | None, typer.Option("--limit", help="Batch size over the worklist.")] = None,
) -> None:
    """Fill in the IMDb id TMDB already publishes, for films holding a TMDB id and no IMDb one.

    The IMDb id is written ALONE: the film's existing TMDB link is left exactly as it is, so no
    film's year moves. One TMDB call per film; dry-run by default.
    """
    cfg = load_config()
    token = load_tmdb_token(cfg)
    if not token:
        err.print(f"no TMDB token: set MOVIE_BRAIN_TMDB_TOKEN or write {cfg.tmdb_token_file}")
        raise typer.Exit(2)
    report = backfill_imdb(_repo(), TmdbClient(token), date.today(), apply=apply, limit=limit, log=_plain)
    console.print(
        f"scanned: {report.scanned} · backfilled: {report.backfilled} · no imdb id: {report.no_imdb} · "
        f"held: {report.held} · failed: {report.failed}" + (" · ABORTED" if report.aborted else "")
    )
```

Add the import at the top of `cli.py` alongside the other application imports.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_cli.py -k repair_imdb -v`
Expected: PASS

- [ ] **Step 5: Document the verb in CLAUDE.md**

Add one line to the Commands block, immediately after the `repair links` line, matching the existing density and style:

```
uv run movie-brain repair imdb [--apply] [--limit N]  # fill in the IMDb id TMDB already publishes for films holding a TMDB id and no IMDb one; writes the imdb id ALONE through `key_film` (tmdb_id=None, resolve_tmdb_id=False) so no film's year moves; dry run by default, one TMDB call per film, `held` ids queue an `id-conflict` review row
```

- [ ] **Step 6: Full gates, then commit**

```bash
uv run pytest && uv run ruff check . && uv run mypy \
  && uv run python scripts/thumbprint_benchmark.py --assert \
  && uv run python scripts/matching_benchmark.py --assert-dominance
git add src/movie_brain/cli.py tests/unit/test_cli.py CLAUDE.md
git commit -m "the backfill gets a verb a human can run in batches"
```

---

### Task 5: Rehearsal on a scratch copy — **owner gate, no code**

**Files:** none. This task writes nothing to `src/` and nothing to the live DB.

- [ ] **Step 1: Make the scratch copy**

```bash
SCRATCH=/private/tmp/claude-501/-Users-jayers-code-movie-brain/d5fe9cfe-62c5-4cf7-86c7-bf76eeb89124/scratchpad/rehearsal
mkdir -p "$SCRATCH"
cp ~/.config/movie-brain/movie-brain.db "$SCRATCH/movie-brain.db"
cp ~/.config/movie-brain/tmdb-read-token.txt "$SCRATCH/" 2>/dev/null || true
cp ~/.config/movie-brain/omdb-api-key.txt "$SCRATCH/" 2>/dev/null || true
sqlite3 "$SCRATCH/movie-brain.db" "select count(*) from films;"
```

- [ ] **Step 2: Snapshot every year before the run**

```bash
sqlite3 "$SCRATCH/movie-brain.db" "select id, year from films order by id;" > "$SCRATCH/years-before.txt"
wc -l "$SCRATCH/years-before.txt"
```

- [ ] **Step 3: Dry run the whole worklist**

```bash
MOVIE_BRAIN_CONFIG_DIR="$SCRATCH" uv run movie-brain repair imdb 2>&1 | tail -30
```

Expected: `scanned: 3699` and a backfilled count close to it. Note the `no imdb id` count — those are real absences.

- [ ] **Step 4: Apply on the scratch copy, in one batch**

```bash
MOVIE_BRAIN_CONFIG_DIR="$SCRATCH" uv run movie-brain repair imdb --apply 2>&1 | tail -40
```

This makes ~3,700 TMDB calls and takes a while. Run it in the background and report the final counts.

- [ ] **Step 5: Prove no year moved**

```bash
sqlite3 "$SCRATCH/movie-brain.db" "select id, year from films order by id;" > "$SCRATCH/years-after.txt"
diff "$SCRATCH/years-before.txt" "$SCRATCH/years-after.txt" && echo "NO YEAR CHANGED"
```

Expected: `NO YEAR CHANGED`. **If any year moved, STOP** — the verb is wrong, not the rehearsal. Report the diff and do not proceed.

- [ ] **Step 6: Report to the owner and WAIT**

Report: scanned / backfilled / no-imdb / held / failed counts; the year diff (expected: empty); the number of new `id-conflict` review rows and the films they name; the new IMDb-id total (`select count(*) from external_ids where authority='imdb'`).

**Do not run the live apply without an explicit yes.** One approval covers one run.

- [ ] **Step 7: On the owner's yes — the live apply**

```bash
uv run movie-brain repair imdb --apply 2>&1 | tail -40
sqlite3 ~/.config/movie-brain/movie-brain.db "select count(*) from external_ids where authority='imdb';"
```

Then report the same figures for the live run.

---

# Item 0 — the two 1992 Sight & Sound lists

### Task 6: The list files

**Files:**
- Create: `lists/sight-and-sound-1992-critics.tsv`
- Create: `lists/sight-and-sound-1992-directors.tsv`
- Test: `tests/unit/test_listfile.py`

**Interfaces:**
- Consumes: `infrastructure/listfile.py::parse_list_file` (unchanged — no parser work in this task).
- Produces: two checked-in artifacts the `lists import` verb reads.

Source: `https://www.bfi.org.uk/sight-and-sound/polls/greatest-films-all-time/1992`. Titles and directors are kept **byte-for-byte as the page prints them** — the lists contract forbids tidying a curator's spelling. Column one is the rank AS PRINTED, so ties keep their printed form; `film_list_entry.rank` will be line order, and `rank_label` stores the printed cell only where it differs.

- [ ] **Step 1: Write the critics' file**

```
# slug: sight-and-sound-1992-critics
# name: The Greatest Films of All Time (Critics' Poll)
# curator: Sight & Sound
# published: 1992
# source_url: https://www.bfi.org.uk/sight-and-sound/polls/greatest-films-all-time/1992
# ordered: true
1	Citizen Kane	Orson Welles
2	La Règle du jeu	Jean Renoir
3	Tokyo Story	Ozu Yasujiro
4	Vertigo	Alfred Hitchcock
5	The Searchers	John Ford
=6	L'Atalante	Jean Vigo
=6	Battleship Potemkin	Sergei Eisenstein
=6	The Passion of Joan of Arc	Carl Dreyer
=6	Pather Panchali	Satyajit Ray
10	2001: A Space Odyssey	Stanley Kubrick
```

Separators are **tabs**, not spaces. Before writing, re-read the live page and confirm every title, director spelling and tie marker against it — the block above is transcribed from a fetch and the page is the authority. Check the header keys against `parse_list_file`'s accepted set in `infrastructure/listfile.py` and use exactly those.

- [ ] **Step 2: Write the directors' file**

```
# slug: sight-and-sound-1992-directors
# name: The Greatest Films of All Time (Directors' Poll)
# curator: Sight & Sound
# published: 1992
# source_url: https://www.bfi.org.uk/sight-and-sound/polls/greatest-films-all-time/1992
# ordered: true
1	Citizen Kane	Orson Welles
=2	8½	Federico Fellini
=2	Raging Bull	Martin Scorsese
4	La strada	Federico Fellini
5	L'Atalante	Jean Vigo
=6	The Godfather	Francis Ford Coppola
=6	Modern Times	Charles Chaplin
=6	Vertigo	Alfred Hitchcock
=9	The Godfather Part II	Francis Ford Coppola
=9	The Passion of Joan of Arc	Carl Dreyer
=9	Rashomon	Kurosawa Akira
=9	Seven Samurai	Kurosawa Akira
```

- [ ] **Step 3: Write the parse tests**

```python
def test_parses_the_1992_critics_list():
    meta, entries = parse_list_file(Path("lists/sight-and-sound-1992-critics.tsv").read_text(encoding="utf-8"))
    assert meta.slug == "sight-and-sound-1992-critics"
    assert meta.ordered is True
    assert len(entries) == 10
    assert entries[0].title_listed == "Citizen Kane"
    assert entries[5].rank_label == "=6"       # four-way tie, printed form preserved
    assert entries[5].rank == 6                 # line order is what stays addressable
    assert entries[9].rank == 10


def test_parses_the_1992_directors_list():
    meta, entries = parse_list_file(Path("lists/sight-and-sound-1992-directors.tsv").read_text(encoding="utf-8"))
    assert meta.slug == "sight-and-sound-1992-directors"
    assert len(entries) == 12
    assert entries[1].rank_label == "=2"
    assert entries[11].title_listed == "Seven Samurai"
```

Match `parse_list_file`'s real return shape and attribute names before writing — read the function first.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_listfile.py -k 1992 -v`
Expected: PASS

- [ ] **Step 5: Full gates, then commit**

```bash
uv run pytest && uv run ruff check . && uv run mypy \
  && uv run python scripts/thumbprint_benchmark.py --assert \
  && uv run python scripts/matching_benchmark.py --assert-dominance
git add lists/ tests/unit/test_listfile.py
git commit -m "the 1992 poll is the canon the owner trusts, in two electorates"
```

---

### Task 7: Import the 1992 lists — **owner gate**

**Files:** none in `src/`. This is a data operation with a rehearsal.

- [ ] **Step 1: Rehearse both imports on a fresh scratch copy**

Take a **new** copy of the live DB (post-backfill, so gate 1 has the ids it needs):

```bash
SCRATCH=/private/tmp/claude-501/-Users-jayers-code-movie-brain/d5fe9cfe-62c5-4cf7-86c7-bf76eeb89124/scratchpad/lists-rehearsal
mkdir -p "$SCRATCH" && cp ~/.config/movie-brain/movie-brain.db "$SCRATCH/movie-brain.db"
cp ~/.config/movie-brain/tmdb-read-token.txt ~/.config/movie-brain/omdb-api-key.txt "$SCRATCH/"
MOVIE_BRAIN_CONFIG_DIR="$SCRATCH" uv run movie-brain lists import lists/sight-and-sound-1992-critics.tsv 2>&1 | tail -40
MOVIE_BRAIN_CONFIG_DIR="$SCRATCH" uv run movie-brain lists import lists/sight-and-sound-1992-directors.tsv 2>&1 | tail -45
```

- [ ] **Step 2: Read the full scorecard and check the expectation**

**Every one of the 19 distinct films is already in the catalogue** (verified 2026-08-29, spec §11), so the expected outcome is `linked` for all 22 entries and **zero would-create**. A `would-create` row means either the resolver missed a film we hold or the list file has a typo — investigate before proceeding; do not let `lists create` mint anything. `La strada` (film #1812) carries no year and is the likeliest to need a review row.

- [ ] **Step 3: Report the scorecard to the owner and WAIT for a yes**

- [ ] **Step 4: On the owner's yes — apply live, one verb at a time**

```bash
uv run movie-brain lists import lists/sight-and-sound-1992-critics.tsv --apply 2>&1 | tail -40
uv run movie-brain lists import lists/sight-and-sound-1992-directors.tsv --apply 2>&1 | tail -45
```

- [ ] **Step 5: Set the trust values**

```bash
uv run movie-brain lists trust sight-and-sound-1992-critics 8
uv run movie-brain lists trust sight-and-sound-1992-directors 6
uv run movie-brain lists trust
```

Expected final state: `cahiers-100` 10 · `bergan-100` 9 · `sight-and-sound-1992-critics` 8 · `sight-and-sound-2022` 7 · `sight-and-sound-1992-directors` 6.

- [ ] **Step 6: Drain any review rows the import queued**

```bash
uv run movie-brain review list --authority list
```

Resolve each with `review resolve <id> --film <film_id>`, reporting each decision to the owner. **`--create` is not to be used here** — every film already exists, so a create would be a duplicate.

---

# Item 2 — the canon-ranked acquisition queue

### Task 8: `size` on each list entry

**Files:**
- Modify: `src/movie_brain/infrastructure/database.py` (`_LISTS_SQL`, `_lists_by_film`)
- Modify: `src/movie_brain/domain/models.py` (the `FilmView.lists` comment)
- Test: `tests/unit/test_repository_lists.py`

**Interfaces:**
- Consumes: existing `_LISTS_SQL`.
- Produces: each `FilmView.lists` entry gains `"size": int` — the number of entries on that list. Tasks 9 and 10 both read it.

- [ ] **Step 1: Write the failing test**

```python
def test_list_entries_carry_their_list_size(repo, today):
    fid = repo.create_film("Citizen Kane", 1941)
    other = repo.create_film("The Rules of the Game", 1939)
    repo.upsert_film_list(ListMeta(slug="poll", name="A Poll", curator=None, published_year=1992,
                                   source_url=None, ordered=True, trust=1))
    repo.upsert_list_entry("poll", rank=1, title_listed="Citizen Kane",
                           director_listed="Orson Welles", film_id=fid)
    repo.upsert_list_entry("poll", rank=2, title_listed="The Rules of the Game",
                           director_listed="Jean Renoir", film_id=other)
    entry = next(v for v in repo.list_views() if v.id == fid).lists[0]
    assert entry["size"] == 2          # the list's length, not our coverage of it
    assert entry["rank"] == 1


def test_list_size_counts_entries_that_are_not_linked_yet(repo, today):
    fid = repo.create_film("Citizen Kane", 1941)
    repo.upsert_film_list(ListMeta(slug="poll", name="A Poll", curator=None, published_year=1992,
                                   source_url=None, ordered=True, trust=1))
    repo.upsert_list_entry("poll", rank=1, title_listed="Citizen Kane",
                           director_listed="Orson Welles", film_id=fid)
    repo.upsert_list_entry("poll", rank=2, title_listed="Something Unlinked",
                           director_listed=None, film_id=None)
    assert next(v for v in repo.list_views() if v.id == fid).lists[0]["size"] == 2
```

`upsert_film_list` and `upsert_list_entry` are the existing seeding helpers used throughout this file — read their real signatures first and match them exactly; the calls above show intent, not copied source. `ListMeta` comes from `domain/models.py`.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_repository_lists.py -k list_size -v`
Expected: FAIL with `KeyError: 'size'`

- [ ] **Step 3: Add the column**

`_LISTS_SQL` gains a correlated count. Keep the existing `ORDER BY` exactly as it is — it is the only place list trust is visible in the UI:

```sql
SELECT e.film_id, e.list_slug, l.name, l.curator, l.published_year, l.ordered, l.trust,
       e.rank, e.rank_label,
       (SELECT COUNT(*) FROM film_list_entry e2 WHERE e2.list_slug = e.list_slug) AS size
FROM film_list_entry e JOIN film_list l ON l.slug = e.list_slug
WHERE e.film_id IS NOT NULL
ORDER BY e.film_id, l.trust DESC, l.name, e.rank
```

and `_lists_by_film` adds `"size": int(r["size"])` to the dict it builds.

Note `size` counts **every** entry on the list, including entries not yet linked to a film — that is correct: the denominator is the poll's length, not our coverage of it.

- [ ] **Step 4: Update the `FilmView.lists` comment in `domain/models.py`**

Add `size` to the documented key list and one clause explaining it is the list's entry count, the `canon_score` denominator.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/unit/test_repository_lists.py -v`
Expected: PASS

- [ ] **Step 6: Full gates, then commit**

```bash
uv run pytest && uv run ruff check . && uv run mypy \
  && uv run python scripts/thumbprint_benchmark.py --assert \
  && uv run python scripts/matching_benchmark.py --assert-dominance
git add src/movie_brain/infrastructure/database.py src/movie_brain/domain/models.py tests/unit/test_repository_lists.py
git commit -m "a rank means nothing without the length of the list it is on"
```

---

### Task 9: `canon_score` and the `acquire` gate, in the domain

**Files:**
- Modify: `src/movie_brain/domain/filters.py`
- Test: `tests/unit/test_filters.py`

**Interfaces:**
- Consumes: `FilmView` (with `size` from Task 8).
- Produces: `canon_score(view: FilmView) -> float`, `is_canon(view) -> bool`, `acquisition_candidate(view: FilmView, today: date) -> bool`, and a new `"acquire"` key in `_PREDICATES` (so it appears in `CHIPS` and reaches `/api/config` automatically).

**The formula (spec §3, D12 — no membership floor):**

```
canon_score = Σ over the film's lists ( trust × (1 − (printed_rank − 1) / size) )
```

`printed_rank` is `rank_label` with a leading `=` stripped, falling back to `rank`. An **unordered** list has no meaningful position and contributes its full `trust`.

**The gate (spec §2):** not owned · not rated · not currently on a subscribed SVOD · **not currently on the Criterion Channel** · and either on at least one list or Metacritic ≥ 90. The Criterion clause is separate because `_SERVICES_SQL` excludes `criterion`, so a Criterion film never appears in `FilmView.services`.

- [ ] **Step 1: Write the failing tests**

```python
from movie_brain.domain.filters import acquisition_candidate, canon_score, is_canon


def _view(**kw) -> FilmView:
    """A FilmView with only the fields these tests care about set; every other field takes a
    harmless default, so each test reads as the one condition it is about."""
    base = dict(
        id=1, title="A Film", year=1959, director=None, url=None, language=None,
        imdb=None, rt=None, found=True, pending=False, leaving_date=None,
        first_seen="2026-01-01", my_rating=None, metacritic=None, lists=[], services=[],
        criterion=False, departed=False, owned=False,
    )
    base.update(kw)
    return FilmView(**base)


def test_canon_score_gives_a_list_leader_the_full_trust():
    v = _view(lists=[{"trust": 10, "rank": 1, "rank_label": None, "size": 100, "ordered": True}])
    assert canon_score(v) == pytest.approx(10.0)


def test_canon_score_decays_to_near_zero_at_the_end_of_a_list():
    v = _view(lists=[{"trust": 10, "rank": 100, "rank_label": None, "size": 100, "ordered": True}])
    assert canon_score(v) == pytest.approx(0.1)


def test_canon_score_sums_across_lists():
    v = _view(lists=[
        {"trust": 10, "rank": 1, "rank_label": None, "size": 100, "ordered": True},
        {"trust": 8, "rank": 1, "rank_label": None, "size": 10, "ordered": True},
    ])
    assert canon_score(v) == pytest.approx(18.0)


def test_canon_score_reads_a_tied_rank_label_not_the_line_position():
    v = _view(lists=[{"trust": 8, "rank": 8, "rank_label": "=6", "size": 10, "ordered": True}])
    assert canon_score(v) == pytest.approx(8 * (1 - 5 / 10))


def test_an_unordered_list_contributes_its_full_trust():
    v = _view(lists=[{"trust": 5, "rank": 40, "rank_label": None, "size": 50, "ordered": False}])
    assert canon_score(v) == pytest.approx(5.0)


def test_a_film_on_no_list_scores_zero_and_is_not_canon():
    v = _view(lists=[])
    assert canon_score(v) == 0.0
    assert is_canon(v) is False


def test_a_film_streaming_on_a_subscribed_svod_is_not_a_candidate(today):
    v = _view(lists=[{"trust": 10, "rank": 1, "rank_label": None, "size": 100, "ordered": True}],
              services=[{"name": "HBO Max", "subscribed": True, "kind": "svod"}])
    assert acquisition_candidate(v, today) is False


def test_a_subscribed_STORE_does_not_suppress_a_candidate(today):
    v = _view(lists=[{"trust": 10, "rank": 1, "rank_label": None, "size": 100, "ordered": True}],
              services=[{"name": "Apple TV Store", "subscribed": True, "kind": "store"}])
    assert acquisition_candidate(v, today) is True


def test_a_film_on_the_criterion_channel_right_now_is_not_a_candidate(today):
    v = _view(lists=[{"trust": 10, "rank": 1, "rank_label": None, "size": 100, "ordered": True}],
              criterion=True, departed=False)
    assert acquisition_candidate(v, today) is False


def test_a_DEPARTED_criterion_film_is_a_candidate_again(today):
    v = _view(lists=[{"trust": 10, "rank": 1, "rank_label": None, "size": 100, "ordered": True}],
              criterion=True, departed=True)
    assert acquisition_candidate(v, today) is True


def test_owned_and_rated_films_are_not_candidates(today):
    base = {"lists": [{"trust": 10, "rank": 1, "rank_label": None, "size": 100, "ordered": True}]}
    assert acquisition_candidate(_view(**base, owned=True), today) is False
    assert acquisition_candidate(_view(**base, my_rating=7), today) is False


def test_a_high_metacritic_film_on_no_list_is_a_candidate(today):
    assert acquisition_candidate(_view(lists=[], metacritic=93), today) is True


def test_a_mediocre_film_on_no_list_is_not_a_candidate(today):
    assert acquisition_candidate(_view(lists=[], metacritic=72), today) is False


def test_acquire_is_a_registered_chip():
    from movie_brain.domain.filters import CHIPS
    assert "acquire" in CHIPS
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_filters.py -k "canon or acquisition or acquire" -v`
Expected: FAIL — `ImportError: cannot import name 'canon_score'`

- [ ] **Step 3: Implement in `domain/filters.py`**

```python
_TIE = re.compile(r"^=?(\d+)$")


def _printed_rank(entry: dict[str, object]) -> int:
    """The rank AS PRINTED — a tie label like "=6" means sixth, not its line position."""
    label = entry.get("rank_label")
    if label is not None:
        m = _TIE.match(str(label))
        if m:
            return int(m.group(1))
    return int(entry["rank"])  # type: ignore[arg-type]


def canon_score(view: FilmView) -> float:
    """Weighted standing in the curated canon: each list contributes its trust, scaled by how
    high the film sits on it. #1 contributes the full trust, the last entry contributes ~0.

    There is deliberately NO membership floor (design D12): adding one was measured over the
    live catalogue and changed 1 of the top 10 while lifting films at POOR ranks on two lists
    70-85 places — rewarding mediocre placement twice over strong placement once.
    """
    total = 0.0
    for e in view.lists:
        trust = float(e["trust"])  # type: ignore[arg-type]
        if not e.get("ordered"):
            total += trust
            continue
        size = int(e["size"])  # type: ignore[arg-type]
        if size <= 0:
            total += trust
            continue
        total += trust * (1 - (_printed_rank(e) - 1) / size)
    return total


def is_canon(view: FilmView) -> bool:
    """Tier 1: on at least one curated list. Tier 2 films (Metacritic only) rank below all of these."""
    return bool(view.lists)


def acquisition_candidate(view: FilmView, _today: date) -> bool:
    """Worth buying: unreachable on anything I pay for, unseen, unowned, and canon-adjacent.

    The Criterion clause is separate from the `services` test on purpose: `criterion` IS a
    subscribed svod row, but _SERVICES_SQL filters it out of FilmView.services, so testing
    services alone would offer to sell a film that is streaming on the Channel right now.
    """
    if view.owned or view.my_rating is not None:
        return False
    if view.criterion and not view.departed:
        return False
    if any(s.get("subscribed") and s.get("kind") == "svod" for s in view.services):
        return False
    return is_canon(view) or (view.metacritic is not None and view.metacritic >= TOP_MC)
```

Register it: `"acquire": acquisition_candidate,` in `_PREDICATES`. It takes `(view, today)` like every other predicate, so it needs no special casing, and adding it there is what puts it in `CHIPS` and therefore in `/api/config`.

Add `import re` at the top of `filters.py` — the module does not import it today. `canon_score` and `is_canon` are exported for the tests and to keep Python the canonical definition of the formula; nothing in `src/` calls them at runtime, exactly as `_PREDICATES` itself is mirrored by `app.js` rather than executed by the dashboard.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_filters.py -v`
Expected: PASS

- [ ] **Step 5: Full gates, then commit**

```bash
uv run pytest && uv run ruff check . && uv run mypy \
  && uv run python scripts/thumbprint_benchmark.py --assert \
  && uv run python scripts/matching_benchmark.py --assert-dominance
git add src/movie_brain/domain/filters.py tests/unit/test_filters.py
git commit -m "the canon gets a number, and the queue gets a gate"
```

---

### Task 10: The dashboard chip and the canon-rank sort

**Files:**
- Modify: `src/movie_brain/web/static/app.js`
- Modify: `src/movie_brain/web/templates/index.html`
- Test: `tests/web/test_dashboard.py`

**Interfaces:**
- Consumes: `f.lists[].{trust, rank, rank_label, size, ordered}`, `f.services[].{subscribed, kind}`, `f.criterion`, `f.departed`, `f.owned`, `f.my_rating`, `f.metacritic`; `state.cfg.canned_thresholds.top_mc`.
- Produces: the `acquire` chip and a canon-rank ordering that leads the default sort while that chip is active.

- [ ] **Step 1: Mirror the predicate in `CHIP_PREDICATES`**

Add to `app.js`, keeping the Python file as the canonical definition:

```javascript
  const printedRank = (e) => {
    const m = /^=?(\d+)$/.exec(e.rank_label ?? '');
    return m ? Number(m[1]) : e.rank;
  };
  // mirrors domain/filters.py::canon_score — no membership floor (design D12)
  const canonScore = (f) => (f.lists || []).reduce((t, e) => {
    if (!e.ordered || !e.size) return t + e.trust;
    return t + e.trust * (1 - (printedRank(e) - 1) / e.size);
  }, 0);
  const isCanon = (f) => (f.lists || []).length > 0;
```

and inside `CHIP_PREDICATES`:

```javascript
    acquire: (f) => !f.owned && f.my_rating == null
      && !(f.criterion && !f.departed)
      && !(f.services || []).some((s) => s.subscribed && s.kind === 'svod')
      && (isCanon(f) || (f.metacritic != null && f.metacritic >= state.cfg.canned_thresholds.top_mc)),
```

- [ ] **Step 2: Lead the default sort with canon rank while the chip is active**

In `compare()`, inside the `if (!state.sort)` branch and **before** the existing `suspect` clause, following that clause's established shape:

```javascript
      if (state.chips.has('acquire')) {  // tier 1 (on a list) above tier 2 (metacritic only), then canon score desc
        const ta = isCanon(a) ? 1 : 0, tb = isCanon(b) ? 1 : 0;
        if (ta !== tb) return tb - ta;
        const c = canonScore(b) - canonScore(a);
        if (c !== 0) return c;
      }
```

An explicit column sort still wins — `state.sort` being set skips this branch entirely, exactly as it does for `suspect`.

- [ ] **Step 3: Add the chip button**

In `index.html`, immediately after the `multi_list` button:

```html
      <button class="chip" data-chip="acquire">Worth buying</button>
```

- [ ] **Step 4: Write the dashboard test**

In `tests/web/test_dashboard.py`, following the existing chip tests: seed a film on a list with no subscribed-svod listing and assert it appears under the `acquire` chip; seed one currently on the Criterion Channel and assert it does not.

- [ ] **Step 5: Run the web tests**

Run: `uv run pytest tests/web/test_dashboard.py -v`
Expected: PASS (needs `uv run playwright install chromium` once)

- [ ] **Step 6: Verify the Python/JS parity test still passes**

Run: `uv run pytest tests/unit/test_filters.py -v`
Expected: PASS — `CHIPS` and `CHIP_PREDICATES` must agree; a chip in one and not the other is a dead control.

- [ ] **Step 7: Full gates, then commit**

```bash
uv run pytest && uv run ruff check . && uv run mypy \
  && uv run python scripts/thumbprint_benchmark.py --assert \
  && uv run python scripts/matching_benchmark.py --assert-dominance
git add src/movie_brain/web/ tests/web/test_dashboard.py
git commit -m "the queue is a chip, and the canon is what orders it"
```

---

### Task 11: Documentation

**Files:**
- Modify: `CLAUDE.md`
- Modify: `.claude/rules/lists.md`

- [ ] **Step 1: Add the canon-queue bullet to CLAUDE.md**

One line in the architecture bullets, beside the `multi_list` sentence:

```
- `acquire` ("Worth buying") is the acquisition gate: not owned, not rated, not on a current Criterion listing, not on any subscribed `svod` in `services` (the Criterion clause is separate BECAUSE `_SERVICES_SQL` excludes criterion), and either on a curated list or Metacritic ≥ 90. While that chip is active the default sort leads with tier (on a list beats Metacritic-only) then `canon_score` — `Σ trust × (1 − (printed_rank − 1) / size)`, no membership floor (design D12), defined canonically in `domain/filters.py` and mirrored in `app.js`.
```

- [ ] **Step 2: Add the `size` and 1992 notes to `.claude/rules/lists.md`**

Record two facts: `FilmView.lists` entries now carry `size` (the list's full entry count, the `canon_score` denominator, counting entries not yet linked); and the two 1992 lists are ten- and twelve-entry polls whose trust is 8 and 6.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md .claude/rules/lists.md
git commit -m "record where the canon score lives and why the Criterion clause is separate"
```

---

## Not in this plan (and why)

- **Item 3 — price fetch, the `prices` table, `prices refresh` / `prices dial`, every CheapCharts HTTP call, and all browser automation.** Deferred by decision D9. Do not build any of it, even if a task seems to invite it.
- **BFI Player as a suppressing service.** Shelved by D13. Its provider findings are recorded in spec §11 so nobody re-derives them.
- **Films #4763 (`Histoire(s) du Cinéma`, `tt6677224`) and #4764 (`Twin Peaks: The Return`, `tt4093826`).** Deliberately unkeyed, awaiting a manual sync then `review resolve <row> --tt <id> --series`. Neither holds a TMDB id, so the backfill does not touch them; both will show in the queue with no year until keyed. Syncs are manual by the owner's choice — never schedule one, and never run one as part of a task.


## Done means

- `uv run movie-brain repair imdb` exists, is rehearsed, and has been applied live with a proven-empty year diff.
- Both 1992 lists are imported, linked, and carry trust 8 and 6; `lists trust` shows all five lists.
- The dashboard has a "Worth buying" chip that orders the canon by `canon_score`.
- All five gates green.
- The live DB is still schema **v16**. If it is not, something went wrong.
