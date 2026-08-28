# Thumbprint T4 — `repair nomatch` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `movie-brain repair nomatch [--apply] [--yes] [--limit N]` that reruns open `tmdb/no-match` films through `domain/thumbprint.resolve()`, keys auto matches via `record_tmdb_match`, and promotes non-matches in place to durable `no-match-reviewed` A/B/C rows; plus the `--pick` `find_by_imdb` fallback.

**Architecture:** New `application/repair_keys.py` holds the two key-repair verbs (`repair_disagreements` moves there in Task 1; `repair_nomatch` is new). The verb follows the T3 shape: an `audit_*` pass computes a verdict per film with holder checks BEFORE any write, `--apply` acts per verdict, `--limit` slices actionable verdicts only, the report counts everything including `skipped`. Durability comes from renaming the row's reason (`Repository.promote_review`) and from a one-line guard in `rebuild_no_match_queue`.

**Tech Stack:** Python 3.12, Typer CLI, SQLite `Repository`, pytest + pytest-bdd, `responses` for HTTP mocks, ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-08-27-thumbprint-t4-nomatch-design.md`

## Global Constraints

- Branch `feature/T4-thumbprint-nomatch`; never merge without the owner's yes.
- Gates after EVERY task: `uv run pytest -q`, `uv run ruff check .`, `uv run mypy`, `uv run python scripts/thumbprint_benchmark.py --assert` (must print n=528 / 0 wrong / auto ≥ 90 %), `uv run python scripts/matching_benchmark.py --assert-dominance`.
- NEVER edit `scripts/eval/thumbprint_eval_v1.csv` or `scripts/eval/fixtures/cand_cache.json.gz` by hand or from the verb.
- NEVER run any `movie-brain` command against the live DB: tests use the `repo`/`config_dir` fixtures (tmp dirs); `MOVIE_BRAIN_CONFIG_DIR` is set by `tests/conftest.py`. No manual CLI runs are needed in any task.
- Revert only by path (`git checkout -- <file>`), never `git checkout .`.
- The resolver stays DARK for ingesters: do not touch `application/sync.py`'s TMDB step beyond the `rebuild_no_match_queue` guard in `availability.py`.
- `resolve()` reason strings are contract — never reword. `review_detail(verdict, query)` is the only detail format for resolver rows.
- Commit after each task with a one-line "why" message.

---

### Task 1: Chore — move the disagreements verb into `application/repair_keys.py`

**Files:**
- Create: `src/movie_brain/application/repair_keys.py`
- Modify: `src/movie_brain/application/repair.py` (delete lines from `@dataclass(frozen=True)\nclass DisagreementContract` through the end of `repair_disagreements`, ≈ lines 806–1098)
- Modify: `src/movie_brain/cli.py:18-33` (imports)
- Modify: `tests/unit/test_repair_disagreements.py` (imports), `tests/unit/test_cli.py:233` (monkeypatch target)

**Interfaces:**
- Produces: `movie_brain.application.repair_keys` exporting unchanged `DisagreementContract`, `load_disagreement_contract`, `DisagreementGroup`, `DisagreementsReport`, `NON_ACTIONABLE`, `KEY_DISAGREEMENT`, `audit_disagreements`, `format_disagreement`, `repair_disagreements`, and the module-private `_disagreement_review`, `_stderr`.

- [ ] **Step 1: Create the new module with the moved code**

Cut everything from `class DisagreementContract` (with its `@dataclass(frozen=True)` decorator) to the end of `repair.py` and paste it into `repair_keys.py` under this header:

```python
"""Key-repair verbs (thumbprint T3/T4): films whose identity keys disagree or are missing.

`repair disagreements` (T3) and `repair nomatch` (T4) share one shape: an audit pass that
computes a verdict per film with holder checks BEFORE any write, an --apply loop acting per
verdict, `--limit` slicing the ACTIONABLE verdicts only, and a report that counts every verdict.
"""

from __future__ import annotations

import csv
import sqlite3
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import requests

from movie_brain.application.availability import TMDB_AUTHORITY, queue_review_once, record_tmdb_match
from movie_brain.application.thumbprint import review_detail
from movie_brain.domain.models import ReviewEntry
from movie_brain.domain.thumbprint import Verdict, make_query, resolve
from movie_brain.infrastructure.database import DisagreementFilm, Repository
from movie_brain.infrastructure.thumbprint_fetch import CacheMiss, CandidateFetcher
from movie_brain.infrastructure.tmdb import AuthError, TmdbClient


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)
```

Then in `repair.py` remove now-unused imports (`ruff check .` reports them: likely `csv` stays for twins/editions; `DisagreementFilm`, `Verdict`, `make_query`, `resolve`, `review_detail`, `CacheMiss`, `CandidateFetcher`, `AuthError`, `queue_review_once`, `requests` — remove only what ruff flags as unused).

- [ ] **Step 2: Update the import sites**

`src/movie_brain/cli.py`: remove `load_disagreement_contract`, `repair_disagreements`, `DisagreementGroup` (if imported) from the `movie_brain.application.repair` import and add:

```python
from movie_brain.application.repair_keys import DisagreementGroup, load_disagreement_contract, repair_disagreements
```

`tests/unit/test_repair_disagreements.py`: change every `from movie_brain.application.repair import` to `from movie_brain.application.repair_keys import` (top-level block and the four in-function `repair_disagreements` imports).

`tests/unit/test_cli.py:233`: `monkeypatch.setattr("movie_brain.cli.repair_disagreements", fake)` stays valid (cli re-binds the name) — verify the test passes; no change expected.

- [ ] **Step 3: Run the gates**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy`
Expected: all pass, same test count as before.

- [ ] **Step 4: Commit**

```bash
git add src/movie_brain/application/repair.py src/movie_brain/application/repair_keys.py src/movie_brain/cli.py tests/unit/test_repair_disagreements.py
git commit -m "chore: key-repair verbs get their own module ahead of repair nomatch"
```

---

### Task 2: `Repository.promote_review` — rename a row's reason/detail in place

**Files:**
- Modify: `src/movie_brain/infrastructure/database.py` (next to `resolve_review`, ≈ line 915)
- Test: `tests/unit/test_database.py`

**Interfaces:**
- Produces: `Repository.promote_review(self, review_id: int, *, reason: str, detail: str, value: str | None = None) -> None` — UPDATE of an OPEN row's `reason`, `detail`, `value`; `id` and `created_at` unchanged; raises `ValueError` when the row is missing or already resolved.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_database.py`:

```python
def test_promote_review_rewrites_reason_and_detail_in_place(repo, today):
    from movie_brain.domain.models import Film, ReviewEntry

    fid = repo.create_film(Film("Bound", 1996, None, ""))
    repo.append_reviews("tmdb", [ReviewEntry("no-match", film_id=fid, detail="Bound (1996)")], today)
    row = repo.open_reviews("tmdb")[0]
    repo.promote_review(int(row["id"]), reason="no-match-reviewed", detail='{"reason": "weak"}', value=None)
    after = repo.review(int(row["id"]))
    assert after is not None
    assert (after["reason"], after["detail"], after["resolved"]) == ("no-match-reviewed", '{"reason": "weak"}', 0)
    assert after["created_at"] == row["created_at"]
    assert [r["id"] for r in repo.open_reviews("tmdb")] == [row["id"]]  # no second row


def test_promote_review_refuses_a_resolved_row(repo, today):
    import pytest

    from movie_brain.domain.models import Film, ReviewEntry

    fid = repo.create_film(Film("Bound", 1996, None, ""))
    repo.append_reviews("tmdb", [ReviewEntry("no-match", film_id=fid, detail="x")], today)
    rid = int(repo.open_reviews("tmdb")[0]["id"])
    repo.resolve_review(rid, "dismissed")
    with pytest.raises(ValueError):
        repo.promote_review(rid, reason="no-match-reviewed", detail="y")
    with pytest.raises(ValueError):
        repo.promote_review(rid + 999, reason="no-match-reviewed", detail="y")
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_database.py -k promote_review -q`
Expected: FAIL — `AttributeError: 'Repository' object has no attribute 'promote_review'`

- [ ] **Step 3: Implement**

Add after `resolve_review` in `database.py`:

```python
    def promote_review(self, review_id: int, *, reason: str, detail: str, value: str | None = None) -> None:
        """Rewrite an OPEN row's reason/detail/value in place — `id` and `created_at` survive.

        The one way a per-run `no-match` row becomes durable: `repair nomatch` promotes it to
        `no-match-reviewed` with the resolver's A/B/C detail instead of queueing a second row
        the next sync's rebuild would then orphan."""
        with self._conn() as c:
            n = c.execute(
                "UPDATE match_review SET reason = ?, detail = ?, value = ? WHERE id = ? AND resolved = 0",
                (reason, detail, value, review_id),
            ).rowcount
        if n != 1:
            raise ValueError(f"review {review_id} is not open")
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_database.py -k promote_review -q`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/infrastructure/database.py tests/unit/test_database.py
git commit -m "repo: promote_review rewrites an open review row in place (durable promotion)"
```

---

### Task 3: `rebuild_no_match_queue` honours resolved `no-match-reviewed` rows

**Files:**
- Modify: `src/movie_brain/application/availability.py:55-75`
- Test: `tests/unit/test_availability.py`

**Interfaces:**
- Produces: `NO_MATCH_REVIEWED = "no-match-reviewed"` constant in `availability.py` (imported by Task 5/6 and `review.py`).

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_availability.py`:

```python
def test_rebuild_skips_a_film_whose_reviewed_row_was_resolved(repo, today):
    from movie_brain.application.availability import NO_MATCH_REVIEWED, rebuild_no_match_queue
    from movie_brain.domain.models import Film, ReviewEntry

    fid = repo.create_film(Film("Bound", 1996, None, ""))
    repo.upsert_tmdb(fid, found=False, looked_up=today)
    repo.append_reviews("tmdb", [ReviewEntry(NO_MATCH_REVIEWED, film_id=fid, detail="{}")], today)
    rid = int(repo.open_reviews("tmdb")[0]["id"])
    repo.resolve_review(rid, "verified unkeyed")  # --none: a standing decision
    rebuild_no_match_queue(repo, today)
    assert repo.open_reviews("tmdb") == []


def test_rebuild_leaves_an_open_reviewed_row_alone_and_does_not_double_queue(repo, today):
    from movie_brain.application.availability import NO_MATCH_REVIEWED, rebuild_no_match_queue
    from movie_brain.domain.models import Film, ReviewEntry

    fid = repo.create_film(Film("Bound", 1996, None, ""))
    repo.upsert_tmdb(fid, found=False, looked_up=today)
    repo.append_reviews("tmdb", [ReviewEntry(NO_MATCH_REVIEWED, film_id=fid, detail="{}")], today)
    rebuild_no_match_queue(repo, today)
    rows = repo.open_reviews("tmdb")
    assert [r["reason"] for r in rows] == [NO_MATCH_REVIEWED]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_availability.py -k reviewed -q`
Expected: first test FAILS (ImportError for `NO_MATCH_REVIEWED`).

- [ ] **Step 3: Implement**

In `availability.py`, near `TMDB_AUTHORITY`, add `NO_MATCH_REVIEWED = "no-match-reviewed"`. In `rebuild_no_match_queue` change the `dismissed` line to:

```python
    dismissed = {
        k[1] for k in repo.resolved_review_keys(TMDB_AUTHORITY) if k[0] in ("no-match", NO_MATCH_REVIEWED)
    }
```

and extend the docstring: "A resolved `no-match-reviewed` row (T4 promotion drained with --pick/--tt/--none) is the same standing decision — `--none` leaves the film found=0, and re-queueing it would rerun the resolver on a verdict a human already gave."

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_availability.py -k reviewed -q`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/application/availability.py tests/unit/test_availability.py
git commit -m "rebuild: a resolved no-match-reviewed row is a standing decision like no-match"
```

---

### Task 4: `--pick` falls back to `find_by_imdb` for an OMDb-only candidate

**Files:**
- Modify: `src/movie_brain/application/review.py:100-115`
- Test: `tests/features/review.feature`, `tests/step_defs/test_review.py`

**Interfaces:**
- Consumes: `TmdbClient.find_by_imdb(tt) -> int | None`, `TmdbClient.movie_year(tmdb_id) -> int | None`.

- [ ] **Step 1: Write the failing BDD scenario**

Append to `tests/features/review.feature` (inside the existing Feature, after the "Picking candidate B" scenario):

```gherkin
  Scenario: --pick on an OMDb-only candidate finds the tmdb id through TMDB
    Given an open tmdb resolver review for "King Kong (1933)" with candidates A "tt0024216"/0 and B "tt0000001"/1
    And TMDB finds "tt0024216" as id 244 released in 1933
    When I resolve it with pick "A"
    Then "King Kong (1933)" holds imdb "tt0024216" and tmdb id "244"
```

In `tests/step_defs/test_review.py`, change `open_resolver_row` so a `0` id means OMDb-only:

```python
    cands = [
        Candidate(tta, ida or None, (t,), y, "A Dir", 90, 10, "movie", bool(ida), True),
        Candidate(ttb, idb or None, (t,), y, "B Dir", 100, 20, "movie", bool(idb), True),
    ]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/step_defs/test_review.py -k "omdb_only" -q`
Expected: FAIL — film holds imdb but no tmdb id (assertion on `tmdb id "244"`).

- [ ] **Step 3: Implement**

In `resolve_review`, replace the `--pick` branch body:

```python
        if pick is not None:
            if parsed is None:
                raise ValueError(f"review {review_id} has no A/B/C candidates — use --tt or --none")
            cand = next((c for c in parsed.candidates if c["letter"] == pick.upper()), None)
            if cand is None:
                raise ValueError(f"no candidate {pick!r} on review {review_id}")
            chosen_tt, chosen_tmdb, chosen_year = str(cand["tt"]), cand.get("tmdb_id"), cand.get("year")
            if chosen_tmdb is None and client is not None:
                # An OMDb-only candidate (The Cup, T3) still usually has a TMDB record under its tt.
                chosen_tmdb = client.find_by_imdb(chosen_tt)
                chosen_year = client.movie_year(chosen_tmdb) if chosen_tmdb is not None else None
            if chosen_tmdb is None:
                warn(f"tmdb id not resolved for {chosen_tt} (no client or no TMDB record); imdb only")
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/step_defs/test_review.py -q`
Expected: all pass (the existing "pick B" scenario unaffected).

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/application/review.py tests/features/review.feature tests/step_defs/test_review.py
git commit -m "review --pick: an OMDb-only candidate still gets its tmdb id through find_by_imdb"
```

---

### Task 5: `audit_nomatch` — worklist, query, verdict table (no writes)

**Files:**
- Modify: `src/movie_brain/infrastructure/database.py` (add `nomatch_worklist`)
- Modify: `src/movie_brain/application/repair_keys.py` (append)
- Test: `tests/unit/test_repair_nomatch.py` (new)

**Interfaces:**
- Produces:
  - `Repository.nomatch_worklist(self) -> list[NomatchFilm]` with `NomatchFilm(NamedTuple): review_id: int; film_id: int; title: str; year: int | None; director: str | None` — open `tmdb`/`no-match` rows whose film is undisposed, ordered by film id.
  - `NomatchGroup` dataclass: `review_id, film_id, title, year, verdict, reason, tt, tmdb_id, query: Query | None, verdict_obj: Verdict | None, detail: str`.
  - `NOMATCH_ACTIONABLE = ("keyed", "match", "review")`.
  - `audit_nomatch(repo, fetcher: CandidateFetcher | None, tmdb: TmdbClient | None) -> list[NomatchGroup]`.
  - `format_nomatch(g: NomatchGroup) -> str`.
  - `_nomatch_query(repo, film: NomatchFilm) -> Query`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_repair_nomatch.py`:

```python
from __future__ import annotations

import json

import requests

from movie_brain.application.availability import NO_MATCH_REVIEWED
from movie_brain.application.repair_keys import NOMATCH_ACTIONABLE, audit_nomatch, format_nomatch
from movie_brain.domain.models import Film, ReviewEntry
from movie_brain.domain.thumbprint import Candidate
from movie_brain.infrastructure.database import OmdbRating


def _cand(tt, tid, title, year, director="", votes=5000, in_tmdb=True, in_omdb=True):
    return Candidate(tt, tid, (title,), year, director, 100, votes, "movie", in_tmdb, in_omdb)


class FakeFetcher:
    """`fetch(q)` returns the canned candidates for q.title; unknown titles raise like a network failure."""

    def __init__(self, by_title):
        self.by_title = by_title

    def fetch(self, q):
        if q.title not in self.by_title:
            raise requests.ConnectionError("offline")
        return self.by_title[q.title]


class FakeTmdb:
    def __init__(self, by_imdb=None, years=None):
        self.by_imdb, self.years = by_imdb or {}, years or {}

    def find_by_imdb(self, tt):
        return self.by_imdb.get(tt)

    def movie_year(self, tid):
        return self.years.get(tid)


def _nomatch(repo, today, title, year, director=None, source=None):
    """A found=0 film with an open no-match row; `source` adds a claim of that authority."""
    fid = repo.create_film(Film(title, year, director, ""))
    repo.upsert_tmdb(fid, found=False, looked_up=today)
    repo.upsert_omdb(fid, OmdbRating(None, None, False, None, None), today)
    repo.append_reviews("tmdb", [ReviewEntry("no-match", film_id=fid, detail=f"{title} ({year})")], today)
    if source:
        repo.add_claim(fid, source, f"{source}:{title}", title, year_claimed=year, first_seen=today.isoformat())
    return fid


def test_worklist_is_open_no_match_rows_of_undisposed_films(repo, today):
    a = _nomatch(repo, today, "Bound", 1996)
    b = _nomatch(repo, today, "Gone", 2000)
    repo.tombstone_film(b, today, note="test")
    wl = repo.nomatch_worklist()
    assert [w.film_id for w in wl] == [a] and wl[0].title == "Bound" and wl[0].year == 1996


def test_query_prefers_criterion_claim_then_metacritic_then_apple(repo, today):
    from movie_brain.application.repair_keys import _nomatch_query

    fid = _nomatch(repo, today, "Bound", 1996, director="Lana Wachowski", source="apple-tv")
    repo.add_claim(fid, "metacritic", "bound", "Bound", year_claimed=1997, first_seen="2026-08-01")
    repo.add_claim(fid, "criterion", "https://c/bound", "Bound", year_claimed=1996, first_seen="2026-08-01")
    q = _nomatch_query(repo, repo.nomatch_worklist()[0])
    assert (q.source, q.year, q.director, str(q.year_class)) == ("criterion", 1996, "Lana Wachowski", "database")


def test_apple_claim_maps_to_source_apple_and_carries_runtime(repo, today):
    from movie_brain.application.repair_keys import _nomatch_query

    fid = _nomatch(repo, today, "Bound", 1996)
    repo.add_claim(fid, "apple-tv", "Bound", "Bound", year_claimed=None, runtime_min=108, first_seen="2026-08-01")
    q = _nomatch_query(repo, repo.nomatch_worklist()[0])
    assert (q.source, q.year, q.runtime_min) == ("apple", 1996, 108)  # year falls back to films.year


def test_verdict_table(repo, today):
    match = _nomatch(repo, today, "Bound", 1996, director="Lana Wachowski")
    review = _nomatch(repo, today, "Love", 2024)
    err = _nomatch(repo, today, "Offline", 2001)
    keyed = _nomatch(repo, today, "Scarface", 1983)
    repo.set_external_id(keyed, "imdb", "tt0086250", today)
    unlinked = _nomatch(repo, today, "Ghost", 1990)
    repo.set_external_id(unlinked, "imdb", "tt0000099", today)
    held = _nomatch(repo, today, "Held", 1999, director="Some One")
    other = repo.create_film(Film("Other", 1999, None, ""))
    repo.set_external_id(other, "imdb", "tt0000777", today)
    fetcher = FakeFetcher(
        {
            "Bound": [_cand("tt0115736", 9081, "Bound", 1996, "Lana Wachowski, Lilly Wachowski")],
            "Love": [_cand("tt1", 1, "Love", 2024, votes=50), _cand("tt2", 2, "Love", 2024, votes=60)],
            "Held": [_cand("tt0000777", 777, "Held", 1999, "Some One")],
        }
    )
    got = {g.film_id: g for g in audit_nomatch(repo, fetcher, FakeTmdb({"tt0086250": 111}, {111: 1983}))}
    assert {f: g.verdict for f, g in got.items()} == {
        match: "match", review: "review", err: "conflict", keyed: "keyed", unlinked: "unlinked", held: "conflict",
    }
    assert (got[match].tt, got[match].tmdb_id) == ("tt0115736", 9081)
    assert (got[keyed].tt, got[keyed].tmdb_id) == ("tt0086250", 111)
    assert got[review].verdict_obj is not None and got[review].query is not None
    assert f"held by #{other}" in got[held].detail
    assert "offline" in got[err].detail
    assert format_nomatch(got[match]).startswith("[match]") and "Bound" in format_nomatch(got[match])


def test_open_reviewed_row_is_review_open_and_no_fetcher_is_conflict(repo, today):
    fid = _nomatch(repo, today, "Bound", 1996)
    repo.append_reviews("tmdb", [ReviewEntry(NO_MATCH_REVIEWED, film_id=fid, detail="{}")], today)
    g = audit_nomatch(repo, None, None)
    assert [x.verdict for x in g] == ["review-open"]
    other = _nomatch(repo, today, "Love", 2024)
    g2 = {x.film_id: x.verdict for x in audit_nomatch(repo, None, None)}
    assert g2[other] == "conflict" and set(NOMATCH_ACTIONABLE) == {"keyed", "match", "review"}
```

Check `repo.tombstone_film`'s real name/signature with `grep -n "def tombstone" src/movie_brain/infrastructure/database.py` and adjust the call in the first test.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_repair_nomatch.py -q`
Expected: ImportError on `audit_nomatch`.

- [ ] **Step 3: Implement `nomatch_worklist` in `database.py`**

Add `NomatchFilm` near `DisagreementFilm`:

```python
class NomatchFilm(NamedTuple):
    """One open tmdb `no-match` row with its undisposed film — the T4 worklist."""

    review_id: int
    film_id: int
    title: str
    year: int | None
    director: str | None
```

and the method next to `key_disagreements`:

```python
    def nomatch_worklist(self) -> list[NomatchFilm]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT m.id AS review_id, f.id, f.title, f.year, f.director FROM match_review m "
                "JOIN films f ON f.id = m.film_id "
                "WHERE m.authority = 'tmdb' AND m.reason = 'no-match' AND m.resolved = 0 AND "
                + _NOT_DISPOSED
                + " ORDER BY f.id"
            ).fetchall()
            return [
                NomatchFilm(int(r["review_id"]), int(r["id"]), str(r["title"]), r["year"], r["director"] or None)
                for r in rows
            ]
```

- [ ] **Step 4: Implement the audit in `repair_keys.py`**

Append (add `NomatchFilm` to the database import, `Query` to the thumbprint import, `NO_MATCH_REVIEWED` to the availability import):

```python
# --- repair nomatch (T4, memo step 4) ------------------------------------------------------

NOMATCH_ACTIONABLE = ("keyed", "match", "review")
_CLAIM_PRECEDENCE = ("criterion", "metacritic", "apple-tv")
_CLAIM_SOURCE = {"criterion": "criterion", "metacritic": "metacritic", "apple-tv": "apple"}


@dataclass(frozen=True)
class NomatchGroup:
    review_id: int
    film_id: int
    title: str
    year: int | None
    verdict: str  # "keyed" | "unlinked" | "match" | "review" | "review-open" | "conflict"
    reason: str
    tt: str | None
    tmdb_id: int | None
    query: Query | None
    verdict_obj: Verdict | None
    detail: str


def _nomatch_query(repo: Repository, film: NomatchFilm) -> Query:
    """What the ingester saw: the film's highest-precedence claim (criterion > metacritic >
    apple-tv), title/year from the claim (year falls back to films.year), director from
    films.director, the apple runtime shown but never scored (Q3)."""
    claims = repo.claims_for_film(film.film_id)
    by_auth = {a: next((c for c in claims if c.authority == a), None) for a in _CLAIM_PRECEDENCE}
    chosen = next((by_auth[a] for a in _CLAIM_PRECEDENCE if by_auth[a] is not None), None)
    apple = by_auth["apple-tv"]
    runtime = apple.runtime_min if apple is not None else None
    if chosen is None:
        return make_query(film.title, film.year, "unknown", director=film.director, runtime_min=runtime)
    return make_query(
        chosen.title_ingested or film.title,
        chosen.year_claimed or film.year,
        _CLAIM_SOURCE[chosen.authority],
        director=film.director,
        runtime_min=runtime,
    )


def audit_nomatch(
    repo: Repository, fetcher: CandidateFetcher | None, tmdb: TmdbClient | None
) -> list[NomatchGroup]:
    """One verdict per open no-match film, every holder check done here, nothing written."""
    imdb_holders = repo.external_id_holders("imdb")
    tmdb_holders = repo.external_id_holders(TMDB_AUTHORITY)
    reviewed_open = {
        int(str(r["film_id"])) for r in repo.open_reviews(TMDB_AUTHORITY) if r["reason"] == NO_MATCH_REVIEWED
    }
    out: list[NomatchGroup] = []
    for f in repo.nomatch_worklist():
        base = dict(review_id=f.review_id, film_id=f.film_id, title=f.title, year=f.year)

        def mk(verdict: str, reason: str, detail: str = "", tt: str | None = None, tid: int | None = None,
               q: Query | None = None, v: Verdict | None = None) -> NomatchGroup:
            return NomatchGroup(**base, verdict=verdict, reason=reason, tt=tt, tmdb_id=tid, query=q,
                                verdict_obj=v, detail=detail)  # type: ignore[arg-type]

        if f.film_id in reviewed_open:
            out.append(mk("review-open", "already promoted"))
            continue
        own_tt = repo.external_ids_for(f.film_id).get("imdb")
        if own_tt is not None:
            if tmdb is None:
                out.append(mk("conflict", "no client", "holds imdb but no TMDB client to look it up", tt=own_tt))
                continue
            try:
                tid = tmdb.find_by_imdb(own_tt)
            except (requests.RequestException, AuthError) as exc:
                out.append(mk("conflict", "TMDB error", str(exc), tt=own_tt))
                continue
            if tid is None:
                out.append(mk("unlinked", "no TMDB record", f"imdb {own_tt} has no TMDB movie", tt=own_tt))
            elif tmdb_holders.get(str(tid), f.film_id) != f.film_id:
                out.append(mk("conflict", "tmdb held", f"tmdb {tid} held by #{tmdb_holders[str(tid)]}", tt=own_tt, tid=tid))
            else:
                out.append(mk("keyed", "imdb already keyed", tt=own_tt, tid=tid))
            continue
        q = _nomatch_query(repo, f)
        if fetcher is None:
            out.append(mk("conflict", "no client", "no TMDB/OMDb clients", q=q))
            continue
        try:
            v = resolve(q, fetcher.fetch(q))
        except (CacheMiss, requests.RequestException, AuthError) as exc:
            out.append(mk("conflict", "TMDB error", str(exc), q=q))
            continue
        if v.kind != "match" or v.tt is None:
            out.append(mk("review", v.reason, review_detail(v, q), q=q, v=v))
            continue
        holder = imdb_holders.get(v.tt)
        if holder is not None and holder != f.film_id:
            out.append(mk("conflict", "imdb held", f"{v.tt} held by #{holder}", tt=v.tt, q=q, v=v))
            continue
        winner = next((s.candidate for s in v.ranked if s.candidate.tt == v.tt), None)
        tid = winner.tmdb_id if winner is not None else None
        if tid is None and tmdb is not None:
            try:
                tid = tmdb.find_by_imdb(v.tt)
            except (requests.RequestException, AuthError) as exc:
                out.append(mk("conflict", "TMDB error", str(exc), tt=v.tt, q=q, v=v))
                continue
        if tid is not None and tmdb_holders.get(str(tid), f.film_id) != f.film_id:
            out.append(mk("conflict", "tmdb held", f"tmdb {tid} held by #{tmdb_holders[str(tid)]}", tt=v.tt, tid=tid, q=q, v=v))
            continue
        out.append(mk("match", v.reason, tt=v.tt, tid=tid, q=q, v=v))
    return out


def format_nomatch(g: NomatchGroup) -> str:
    src = f" src={g.query.source} dir={g.query.director or '-'}" if g.query else ""
    head = f"[{g.verdict}] #{g.film_id} {g.title!r} ({g.year or '-'}){src} → {g.tt or '-'} ({g.tmdb_id or '-'}): {g.reason}"
    if g.verdict == "review" and g.verdict_obj is not None:
        cands = " / ".join(
            f"{letter} {s.candidate.tt} {s.candidate.titles[0] if s.candidate.titles else ''!r} "
            f"{s.candidate.year or '-'} {s.candidate.directors or '-'}"
            for letter, s in zip("ABC", g.verdict_obj.ranked, strict=False)
        )
        return f"{head} [{cands}]"
    return f"{head} {g.detail}".rstrip()
```

Replace the `# type: ignore` shortcut with a plain keyword construction if mypy complains — the point is one `NomatchGroup(...)` per branch; do not weaken types.

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/unit/test_repair_nomatch.py -q && uv run ruff check . && uv run mypy`
Expected: 5 passed, ruff/mypy clean.

- [ ] **Step 6: Commit**

```bash
git add src/movie_brain/infrastructure/database.py src/movie_brain/application/repair_keys.py tests/unit/test_repair_nomatch.py
git commit -m "repair nomatch: audit pass — worklist, ingested query, verdict table with holder checks"
```

---

### Task 6: `repair_nomatch` — apply paths, report, `--limit`, rebuild

**Files:**
- Modify: `src/movie_brain/application/repair_keys.py` (append)
- Test: `tests/unit/test_repair_nomatch.py` (append)

**Interfaces:**
- Produces: `NomatchReport(groups, keyed, unlinked, match, review, review_open, conflict, applied, declined, skipped)` frozen dataclass; `repair_nomatch(repo, today, *, apply, confirm: Callable[[NomatchGroup], bool], tmdb, fetcher, limit=None, log=_stderr) -> NomatchReport`.
- Consumes: `record_tmdb_match`, `rebuild_no_match_queue`, `Repository.promote_review` (Task 2), `NO_MATCH_REVIEWED` (Task 3).

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_repair_nomatch.py`:

```python
def _run(repo, today, fetcher, tmdb=None, apply=True, limit=None):
    from movie_brain.application.repair_keys import repair_nomatch

    lines = []
    rep = repair_nomatch(repo, today, apply=apply, confirm=lambda g: True, tmdb=tmdb, fetcher=fetcher, limit=limit,
                         log=lines.append)
    return rep, lines


def _tmdb_found(repo, fid):
    import sqlite3

    with sqlite3.connect(repo.db_path) as c:
        row = c.execute("SELECT found FROM tmdb WHERE film_id = ?", (fid,)).fetchone()
    return bool(row and row[0])


BOUND = {"Bound": [_cand("tt0115736", 9081, "Bound", 1996, "Lana Wachowski, Lilly Wachowski")]}
LOVE = {"Love": [_cand("tt1", 1, "Love", 2024, votes=50), _cand("tt2", 2, "Love", 2024, votes=60)]}


def test_dry_run_writes_nothing(repo, today):
    fid = _nomatch(repo, today, "Bound", 1996, director="Lana Wachowski")
    rep, lines = _run(repo, today, FakeFetcher(BOUND), FakeTmdb({}, {9081: 1996}), apply=False)
    assert rep.match == 1 and rep.applied == 0
    assert repo.external_ids_for(fid) == {} and not _tmdb_found(repo, fid)
    assert repo.open_reviews("tmdb")[0]["reason"] == "no-match"


def test_match_keys_both_ids_refreshes_omdb_and_drops_the_row(repo, today):
    fid = _nomatch(repo, today, "Bound", 1996, director="Lana Wachowski")
    rep, _ = _run(repo, today, FakeFetcher(BOUND), FakeTmdb({}, {9081: 1996}))
    ids = repo.external_ids_for(fid)
    assert (ids["imdb"], ids["tmdb"]) == ("tt0115736", "9081") and _tmdb_found(repo, fid)
    assert repo.omdb_needs_refresh(fid)
    assert repo.open_reviews("tmdb") == []  # the rebuild dropped the now-matched film's row
    assert (rep.match, rep.applied, rep.skipped) == (1, 1, 0)


def test_criterion_film_keeps_its_year_on_match(repo, today):
    fid = _nomatch(repo, today, "Bound", 1996, director="Lana Wachowski")
    repo.record_catalog("criterion", [Film("Bound", 1996, "Lana Wachowski", "https://c/bound")], today)
    _run(repo, today, FakeFetcher(BOUND), FakeTmdb({}, {9081: 1950}))
    view = repo.get_view(fid, today)
    assert view is not None and view.year == 1996 and repo.external_ids_for(fid)["tmdb"] == "9081"


def test_review_promotes_the_row_in_place(repo, today):
    from movie_brain.application.thumbprint import parse_review_detail

    fid = _nomatch(repo, today, "Love", 2024)
    before = repo.open_reviews("tmdb")[0]
    rep, _ = _run(repo, today, FakeFetcher(LOVE), FakeTmdb())
    rows = repo.open_reviews("tmdb")
    assert len(rows) == 1 and rows[0]["id"] == before["id"] and rows[0]["reason"] == NO_MATCH_REVIEWED
    parsed = parse_review_detail(str(rows[0]["detail"]))
    assert parsed is not None and [c["letter"] for c in parsed.candidates] == ["A", "B"]
    assert parsed.query is not None and parsed.query["title"] == "Love"
    assert rep.review == 1 and rep.applied == 1
    # idempotent: the second run lists it as review-open and writes nothing
    rep2, _ = _run(repo, today, FakeFetcher(LOVE), FakeTmdb())
    assert (rep2.review_open, rep2.applied) == (1, 0)
    assert repo.external_ids_for(fid) == {}


def test_keyed_film_links_tmdb_without_the_resolver(repo, today):
    fid = _nomatch(repo, today, "Scarface", 1983)
    repo.set_external_id(fid, "imdb", "tt0086250", today)
    rep, _ = _run(repo, today, FakeFetcher({}), FakeTmdb({"tt0086250": 111}, {111: 1983}))
    assert repo.external_ids_for(fid)["tmdb"] == "111" and rep.keyed == 1 and rep.applied == 1


def test_limit_slices_actionable_only(repo, today):
    _nomatch(repo, today, "Offline", 2001)  # conflict — always listed, free
    a = _nomatch(repo, today, "Bound", 1996, director="Lana Wachowski")
    b = _nomatch(repo, today, "Love", 2024)
    rep, _ = _run(repo, today, FakeFetcher({**BOUND, **LOVE}), FakeTmdb({}, {9081: 1996}), limit=1)
    assert (rep.groups, rep.conflict, rep.applied) == (2, 1, 1)
    assert "tmdb" in repo.external_ids_for(a) and repo.external_ids_for(b) == {}
    rep2, _ = _run(repo, today, FakeFetcher({**BOUND, **LOVE}), FakeTmdb({}, {9081: 1996}), limit=1)
    assert rep2.applied == 1 and repo.open_reviews("tmdb")[-1]["reason"] == NO_MATCH_REVIEWED


def test_batch_local_holder_is_skipped_not_written(repo, today):
    # two films resolve to the same tt: the first wins, the second is skipped (counted), never half-written
    a = _nomatch(repo, today, "Bound", 1996, director="Lana Wachowski")
    b = _nomatch(repo, today, "Bound", 1997, director="Lana Wachowski")
    rep, lines = _run(repo, today, FakeFetcher(BOUND), FakeTmdb({}, {9081: 1996}))
    assert (rep.match, rep.applied, rep.skipped) == (2, 1, 1)
    assert "tmdb" in repo.external_ids_for(a) and repo.external_ids_for(b) == {}
    assert any("already held" in ln for ln in lines)


def test_partial_after_record_tmdb_match_raises(repo, today, monkeypatch):
    import pytest

    _nomatch(repo, today, "Bound", 1996, director="Lana Wachowski")
    monkeypatch.setattr("movie_brain.application.repair_keys.record_tmdb_match", lambda *a, **k: "id-conflict")
    with pytest.raises(RuntimeError, match=r"\[partial\]"):
        _run(repo, today, FakeFetcher(BOUND), FakeTmdb({}, {9081: 1996}))


def test_declined_is_counted_and_untouched(repo, today):
    from movie_brain.application.repair_keys import repair_nomatch

    fid = _nomatch(repo, today, "Bound", 1996, director="Lana Wachowski")
    rep = repair_nomatch(repo, today, apply=True, confirm=lambda g: False, tmdb=FakeTmdb({}, {9081: 1996}),
                         fetcher=FakeFetcher(BOUND), log=lambda _m: None)
    assert (rep.declined, rep.applied) == (1, 0) and repo.external_ids_for(fid) == {}
```

Check `repo.omdb_needs_refresh` exists (`grep -n "def omdb_needs_refresh" src/movie_brain/infrastructure/database.py`); if its signature differs, use the `_needs_refresh` SQL helper from `test_repair_disagreements.py` instead.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_repair_nomatch.py -q`
Expected: new tests fail with ImportError on `repair_nomatch`.

- [ ] **Step 3: Implement**

Append to `repair_keys.py` (add `rebuild_no_match_queue` to the availability import):

```python
@dataclass(frozen=True)
class NomatchReport:
    groups: int
    keyed: int
    unlinked: int
    match: int
    review: int
    review_open: int
    conflict: int
    applied: int
    declined: int
    skipped: int  # actionable groups NOT written on --apply for a runtime reason (held id, TMDB error)


def repair_nomatch(
    repo: Repository,
    today: date,
    *,
    apply: bool,
    confirm: Callable[[NomatchGroup], bool],
    tmdb: TmdbClient | None,
    fetcher: CandidateFetcher | None,
    limit: int | None = None,
    log: Callable[[str], None] = _stderr,
) -> NomatchReport:
    """Rerun the open no-match films through the resolver (spec §4). `match`/`keyed` key the
    film through the sync's own write path; `review` promotes the existing row in place to the
    durable `no-match-reviewed` reason; nothing else is written. `--limit N` slices the
    ACTIONABLE verdicts only. On --apply the run ends with the sync's own no-match rebuild, so
    matched films' rows drop now rather than at the next sync — and NO no-match row is ever
    resolved by this verb (a resolved no-match row would block a later manual relink)."""
    audited = audit_nomatch(repo, fetcher, tmdb)
    groups = [g for g in audited if g.verdict not in NOMATCH_ACTIONABLE]
    actionable = [g for g in audited if g.verdict in NOMATCH_ACTIONABLE]
    groups += actionable if limit is None else actionable[:limit]
    applied = declined = skipped = 0
    for g in groups:
        log(format_nomatch(g))
        if not apply or g.verdict not in NOMATCH_ACTIONABLE:
            continue
        if not confirm(g):
            declined += 1
            continue
        if g.verdict == "review":
            repo.promote_review(g.review_id, reason=NO_MATCH_REVIEWED, detail=g.detail, value=None)
            log(f"  promoted review {g.review_id} → {NO_MATCH_REVIEWED}")
            applied += 1
            continue
        assert g.tt is not None
        if tmdb is None:
            log("  no TMDB client — skipped")
            skipped += 1
            continue
        # Live pre-write checks: the audit's holder maps predate this batch's own writes.
        holder = repo.film_id_for_external("imdb", g.tt)
        if holder is not None and holder != g.film_id:
            log(f"  {g.tt} already held by #{holder} — skipped")
            skipped += 1
            continue
        tid = g.tmdb_id
        winner_year: int | None = None
        try:
            if tid is not None:
                th = repo.film_id_for_external(TMDB_AUTHORITY, str(tid))
                if th is not None and th != g.film_id:
                    log(f"  tmdb {tid} already held by #{th} — skipped")
                    skipped += 1
                    continue
                winner_year = tmdb.movie_year(tid)
        except (requests.RequestException, AuthError) as exc:
            log(f"  TMDB error: {exc} — skipped")
            skipped += 1
            continue
        try:
            repo.set_external_id(g.film_id, "imdb", g.tt, today)
        except sqlite3.IntegrityError:
            log(f"  {g.tt} already held — skipped")
            skipped += 1
            continue
        if tid is not None:
            target = repo.tmdb_target(g.film_id)
            if target is None:
                raise RuntimeError(f"[partial] #{g.film_id} vanished after its imdb id was written")
            res = record_tmdb_match(repo, target, tid, winner_year, today, log)
            if res not in ("matched", "adopted"):
                partial = f"[partial] #{g.film_id} PARTIAL: imdb {g.tt} written but tmdb {tid} {res}"
                log(partial)
                raise RuntimeError(partial)
            log(f"  keyed imdb {g.tt} tmdb {tid} ({res})")
        else:
            log(f"  keyed imdb {g.tt} (no TMDB record)")
        if repo.omdb_imdb_id(g.film_id) != g.tt:
            repo.mark_omdb_refresh(g.film_id)
            log(f"  omdb refresh queued (by id {g.tt})")
        applied += 1
    if apply:
        rebuild_no_match_queue(repo, today)
    counts = {
        v: sum(1 for g in groups if g.verdict == v)
        for v in ("keyed", "unlinked", "match", "review", "review-open", "conflict")
    }
    return NomatchReport(
        len(groups), counts["keyed"], counts["unlinked"], counts["match"], counts["review"], counts["review-open"],
        counts["conflict"], applied, declined, skipped,
    )
```

Note on `test_batch_local_holder_is_skipped_not_written`: both films get verdict `match` in the audit (the holder map is empty before the batch); the second is caught by the live `film_id_for_external` check — that is the T3 lesson under test.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_repair_nomatch.py -q && uv run ruff check . && uv run mypy`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/application/repair_keys.py tests/unit/test_repair_nomatch.py
git commit -m "repair nomatch: apply paths key matches, promote reviews in place, rebuild the queue"
```

---

### Task 7: CLI wiring with the session candidate cache

**Files:**
- Modify: `src/movie_brain/cli.py` (after `repair_disagreements_cmd`)
- Test: `tests/unit/test_cli.py`

**Interfaces:**
- Consumes: `repair_nomatch`, `NomatchGroup` (Task 6); `CandidateCache.load(path, read_only=True).data`, `CandidateCache(data, path)`, `.save()`.
- Produces: `movie-brain repair nomatch [--apply] [--yes] [--limit N]`; session cache at `<config_dir>/nomatch-cache.json.gz`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cli.py`:

```python
def test_repair_nomatch_dry_run_on_empty_db(config_dir):
    r = runner.invoke(app, ["repair", "nomatch"])
    assert r.exit_code == 0 and "groups: 0" in r.output and "skipped: 0" in r.output


def test_repair_nomatch_partial_exits_1(monkeypatch):
    def fake(repo, today, *, apply, confirm, tmdb, fetcher, limit, log):
        raise RuntimeError("[partial] #1 PARTIAL: imdb tt1 written but tmdb 2 id-conflict")

    monkeypatch.setattr("movie_brain.cli.repair_nomatch", fake)
    r = runner.invoke(app, ["repair", "nomatch", "--apply", "--yes"])
    assert r.exit_code == 1 and "PARTIAL" in r.output


def test_repair_nomatch_session_cache_is_not_the_fixture(config_dir, monkeypatch, tmp_path):
    seen = {}

    def fake(repo, today, *, apply, confirm, tmdb, fetcher, limit, log):
        seen["fetcher"] = fetcher
        from movie_brain.application.repair_keys import NomatchReport

        return NomatchReport(0, 0, 0, 0, 0, 0, 0, 0, 0, 0)

    monkeypatch.setattr("movie_brain.cli.repair_nomatch", fake)
    (config_dir / "tmdb-read-token.txt").write_text("tok")
    (config_dir / "omdb-api-key.txt").write_text("key")
    r = runner.invoke(app, ["repair", "nomatch"])
    assert r.exit_code == 0
    cache = seen["fetcher"].cache
    assert cache.path == config_dir / "nomatch-cache.json.gz" and not cache.read_only
```

Also add `["repair", "nomatch"]` to the argv tuple in the migrate-guard test at `tests/unit/test_cli.py:321`.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_cli.py -k nomatch -q`
Expected: FAIL — "No such command 'nomatch'".

- [ ] **Step 3: Implement**

Add to the `repair_keys` import in `cli.py`: `NomatchGroup, repair_nomatch`. Then after `repair_disagreements_cmd`:

```python
@repair_app.command("nomatch")
def repair_nomatch_cmd(
    apply: Annotated[bool, typer.Option("--apply", help="Act on confirmed films (default: dry-run).")] = False,
    yes: Annotated[bool, typer.Option("--yes", help="With --apply: confirm every film without prompting.")] = False,
    limit: Annotated[int | None, typer.Option("--limit", help="Batch size over the actionable films only.")] = None,
) -> None:
    """Rerun the open tmdb no-match films through the thumbprint resolver: auto matches are
    keyed, non-matches become durable A/B/C `no-match-reviewed` rows for `review resolve
    --pick/--tt/--none`. Candidates are cached per session in <config_dir>/nomatch-cache.json.gz
    (the eval fixture is never written)."""
    from movie_brain.infrastructure.omdb import OmdbClient
    from movie_brain.infrastructure.thumbprint_fetch import CandidateCache, CandidateFetcher

    root = Path(__file__).resolve().parents[2]
    repo = _repo()
    cfg = load_config()
    token, key = load_tmdb_token(cfg), load_api_key(cfg)
    tmdb = TmdbClient(token) if token else None
    fetcher = None
    cache = None
    if tmdb is not None and key:
        session_path = cfg.config_dir / "nomatch-cache.json.gz"
        fixture = root / "scripts" / "eval" / "fixtures" / "cand_cache.json.gz"
        data = dict(CandidateCache.load(fixture, read_only=True).data)
        if session_path.exists():
            data.update(CandidateCache.load(session_path).data)
        cache = CandidateCache(data, session_path)
        fetcher = CandidateFetcher(cache, tmdb, OmdbClient(key))

    def confirm(g: NomatchGroup) -> bool:
        prompt = f"#{g.film_id} {g.title!r} [{g.verdict}] → {g.tt or 'review'}?"
        return yes or typer.confirm(prompt, default=False)

    try:
        report = repair_nomatch(
            repo, date.today(), apply=apply, confirm=confirm, tmdb=tmdb, fetcher=fetcher, limit=limit, log=_plain
        )
    except RuntimeError as exc:
        err.print(str(exc))
        raise typer.Exit(1) from exc
    finally:
        if cache is not None:
            cache.save()  # the session cache, never the fixture
    console.print(
        f"groups: {report.groups} · keyed: {report.keyed} · match: {report.match} · review: {report.review} · "
        f"unlinked: {report.unlinked} · review-open: {report.review_open} · conflict: {report.conflict} · "
        f"applied: {report.applied} · declined: {report.declined} · skipped: {report.skipped}"
    )
```

`typer.Exit` subclasses `RuntimeError`? — it does NOT in current Typer (it subclasses `click.exceptions.Exit`); the migrate guard in `_repo()` runs before the `try` anyway, matching `repair_disagreements_cmd`.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_cli.py -q && uv run ruff check . && uv run mypy`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/cli.py tests/unit/test_cli.py
git commit -m "cli: repair nomatch with a per-session candidate cache separate from the eval fixture"
```

---

### Task 8: BDD scenarios — end-to-end through a simulated sync

**Files:**
- Create: `tests/features/thumbprint_nomatch.feature`
- Modify: `tests/step_defs/test_thumbprint.py` (add `scenarios(...)` + steps)

**Interfaces:**
- Consumes: `repair_nomatch`, `resolve_review(... none=True)`, `rebuild_no_match_queue`, `NO_MATCH_REVIEWED`.

- [ ] **Step 1: Write the failing scenarios**

`tests/features/thumbprint_nomatch.feature`:

```gherkin
Feature: Thumbprint T4 — repair nomatch reruns open no-match films through the resolver

  Background:
    Given a no-match film "Bound" (1996) directed by "Lana Wachowski" with a criterion claim
    And a no-match film "Love" (2024) with a metacritic claim
    And the candidate pool has "Bound" → tt0115736/9081 1996 by "Lana Wachowski, Lilly Wachowski"
    And the candidate pool has "Love" → tt1/1 2024 and tt2/2 2024

  Scenario: dry run lists both verdicts and writes nothing
    When I run repair nomatch without --apply
    Then the nomatch report says match 1, review 1, applied 0
    And no film holds an imdb id
    And both no-match rows are still open as "no-match"

  Scenario: apply keys the match and promotes the review in place
    When I run repair nomatch --apply answering yes
    Then "Bound" holds imdb "tt0115736" and tmdb "9081" and is found
    And the only open tmdb row is for "Love" with reason "no-match-reviewed" and candidates A, B
    And the "Love" row keeps its original id

  Scenario: --none on the promoted row survives the next sync's rebuild
    Given I ran repair nomatch --apply answering yes
    When I resolve the "Love" row with --none
    And the tmdb no-match queue is rebuilt as sync would
    Then there are no open tmdb rows
    And the eval log has a verified human row for "Love" expecting "NONE"
```

Steps in `tests/step_defs/test_thumbprint.py` (add `scenarios("../features/thumbprint_nomatch.feature")` after the existing two, and these steps; reuse `ctx`, `_q`, `TODAY`):

```python
from movie_brain.application import review as rv
from movie_brain.application.availability import NO_MATCH_REVIEWED, rebuild_no_match_queue
from movie_brain.application.repair_keys import repair_nomatch
from movie_brain.domain.models import ReviewEntry
from movie_brain.domain.thumbprint import Candidate


class _PoolFetcher:
    def __init__(self):
        self.pool = {}

    def fetch(self, q):
        return self.pool.get(q.title, [])


class _StubTmdb:
    def find_by_imdb(self, tt):
        return None

    def movie_year(self, tid):
        return {9081: 1996}.get(tid)


def _nomatch_film(ctx, title, year, director, authority):
    repo = ctx["repo"]
    fid = repo.create_film(Film(title, year, director, ""))
    repo.upsert_tmdb(fid, found=False, looked_up=TODAY)
    repo.upsert_omdb(fid, OmdbRating(None, None, False, None, None), TODAY)
    repo.append_reviews("tmdb", [ReviewEntry("no-match", film_id=fid, detail=f"{title} ({year})")], TODAY)
    repo.add_claim(fid, authority, f"{authority}:{title}", title, year_claimed=year, first_seen=TODAY.isoformat())
    ctx.setdefault("films", {})[title] = fid
    ctx.setdefault("pool", _PoolFetcher())


@given(parsers.parse('a no-match film "{title}" ({year:d}) directed by "{director}" with a criterion claim'))
def nomatch_crit(ctx, title, year, director):
    _nomatch_film(ctx, title, year, director, "criterion")


@given(parsers.parse('a no-match film "{title}" ({year:d}) with a metacritic claim'))
def nomatch_mc(ctx, title, year):
    _nomatch_film(ctx, title, year, None, "metacritic")


@given(parsers.parse('the candidate pool has "{title}" → {tt}/{tid:d} {year:d} by "{director}"'))
def pool_one(ctx, title, tt, tid, year, director):
    ctx["pool"].pool[title] = [Candidate(tt, tid, (title,), year, director, 100, 5000, "movie", True, True)]


@given(parsers.parse('the candidate pool has "{title}" → {tta}/{ida:d} {ya:d} and {ttb}/{idb:d} {yb:d}'))
def pool_two(ctx, title, tta, ida, ya, ttb, idb, yb):
    ctx["pool"].pool[title] = [
        Candidate(tta, ida, (title,), ya, "", 100, 50, "movie", True, True),
        Candidate(ttb, idb, (title,), yb, "", 100, 60, "movie", True, True),
    ]


def _run_nomatch(ctx, apply):
    ctx["nomatch_report"] = repair_nomatch(
        ctx["repo"], TODAY, apply=apply, confirm=lambda g: True, tmdb=_StubTmdb(), fetcher=ctx["pool"],
        log=ctx["log"].append,
    )


@when("I run repair nomatch without --apply")
def nomatch_dry(ctx):
    _run_nomatch(ctx, False)


@when("I run repair nomatch --apply answering yes")
@given("I ran repair nomatch --apply answering yes")
def nomatch_apply(ctx):
    _run_nomatch(ctx, True)


@then(parsers.parse("the nomatch report says match {m:d}, review {r:d}, applied {a:d}"))
def nomatch_report(ctx, m, r, a):
    rep = ctx["nomatch_report"]
    assert (rep.match, rep.review, rep.applied) == (m, r, a)


@then("no film holds an imdb id")
def no_imdb(ctx):
    assert _q(ctx, "SELECT COUNT(*) FROM external_ids WHERE authority = 'imdb'")[0][0] == 0


@then(parsers.parse('both no-match rows are still open as "{reason}"'))
def both_open(ctx, reason):
    assert [r["reason"] for r in ctx["repo"].open_reviews("tmdb")] == [reason, reason]


@then(parsers.parse('"{title}" holds imdb "{tt}" and tmdb "{tid}" and is found'))
def holds_both(ctx, title, tt, tid):
    fid = ctx["films"][title]
    ids = ctx["repo"].external_ids_for(fid)
    assert (ids["imdb"], ids["tmdb"]) == (tt, tid)
    assert _q(ctx, "SELECT found FROM tmdb WHERE film_id = ?", fid)[0][0] == 1


@then(parsers.parse('the only open tmdb row is for "{title}" with reason "{reason}" and candidates A, B'))
def only_open(ctx, title, reason):
    from movie_brain.application.thumbprint import parse_review_detail

    rows = ctx["repo"].open_reviews("tmdb")
    assert len(rows) == 1 and rows[0]["film_id"] == ctx["films"][title] and rows[0]["reason"] == reason
    parsed = parse_review_detail(str(rows[0]["detail"]))
    assert parsed is not None and [c["letter"] for c in parsed.candidates] == ["A", "B"]
    ctx["review_id"] = rows[0]["id"]


@then(parsers.parse('the "{title}" row keeps its original id'))
def keeps_id(ctx, title):
    ids = _q(ctx, "SELECT id FROM match_review WHERE film_id = ?", ctx["films"][title])
    assert len(ids) == 1 and ids[0][0] == ctx["review_id"]


@when(parsers.parse('I resolve the "{title}" row with --none'))
def resolve_none(ctx, title):
    row = next(r for r in ctx["repo"].open_reviews("tmdb") if r["film_id"] == ctx["films"][title])
    rv.resolve_review(ctx["repo"], int(row["id"]), today=TODAY, none=True, eval_csv=ctx["config_dir"] / "eval.csv")


@when("the tmdb no-match queue is rebuilt as sync would")
def rebuild_queue(ctx):
    rebuild_no_match_queue(ctx["repo"], TODAY)


@then("there are no open tmdb rows")
def no_open(ctx):
    assert ctx["repo"].open_reviews("tmdb") == []


@then(parsers.parse('the eval log has a verified human row for "{title}" expecting "{tt}"'))
def eval_row(ctx, title, tt):
    import csv

    with (ctx["config_dir"] / "eval.csv").open(encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["title_ingested"] == title]
    assert rows and rows[-1]["expected_tt"] == tt and rows[-1]["status"] == "verified"
```

If `OmdbRating` needs a different positional arity (check `grep -n "class OmdbRating" -A8 src/movie_brain/domain/models.py`), match it — the intent is an OMDb row with `found=0`.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/step_defs/test_thumbprint.py -k nomatch -q`
Expected: the 3 new scenarios fail (missing steps → then behaviour).

- [ ] **Step 3: Make them pass**

No production change is expected; fix step wording/arity until green. If a scenario exposes a real defect in Task 5/6 code, fix it in `repair_keys.py` and add a unit test for it in `tests/unit/test_repair_nomatch.py`.

- [ ] **Step 4: Run the full gates**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy && uv run python scripts/thumbprint_benchmark.py --assert && uv run python scripts/matching_benchmark.py --assert-dominance`
Expected: all green; benchmark prints n=528 / 0 wrong / auto ≥ 90 %.

- [ ] **Step 5: Commit**

```bash
git add tests/features/thumbprint_nomatch.feature tests/step_defs/test_thumbprint.py
git commit -m "bdd: repair nomatch end to end, including --none surviving the sync rebuild"
```

---

### Task 9: Docs — CLAUDE.md, thumbprint rule, sync-flow note

**Files:**
- Modify: `CLAUDE.md` (Commands block, after the `repair disagreements` line; Review resolution bullet)
- Modify: `.claude/rules/thumbprint.md` (new bullet; `paths:` add `src/movie_brain/application/repair_keys.py`)
- Modify: `.claude/rules/sync-flow.md` step 6 (one clause)

- [ ] **Step 1: CLAUDE.md**

Add to the Commands block after the `repair disagreements` line:

```
uv run movie-brain repair nomatch [--apply] [--yes] [--limit N]  # rerun open tmdb no-match films through the thumbprint resolver: matches keyed via record_tmdb_match, non-matches promoted IN PLACE to durable `no-match-reviewed` A/B/C rows (drain with `review resolve --pick/--tt/--none`); --limit batches actionable films only; candidates cached in <config_dir>/nomatch-cache.json.gz (eval fixture never written)
```

Extend the "Review resolution" bullet with: "`no-match-reviewed` rows (written only by `repair nomatch`) accept `--pick/--tt/--none/--dismiss`; a resolved one is excluded from the no-match rebuild exactly like a resolved `no-match` row."

- [ ] **Step 2: `.claude/rules/thumbprint.md`**

Add `src/movie_brain/application/repair_keys.py` to `paths:` and append this bullet:

```
- `movie-brain repair nomatch [--apply] [--yes] [--limit N]` (`application/repair_keys.py`, T4 /
  memo step 4): worklist = open `tmdb/no-match` rows on undisposed films; query = the film's
  highest-precedence claim (criterion > metacritic > apple-tv → source `apple`) with
  `films.director`, apple runtime shown never scored. Verdicts, all holder-checked BEFORE any
  write: `keyed` (film already holds an imdb tt → `find_by_imdb` + `record_tmdb_match`),
  `unlinked` (holds tt, TMDB has no record — listed, not work), `match` (`resolve()` match →
  `set_external_id(imdb)` THEN `record_tmdb_match` — commerce guard keeps Criterion years —
  then `mark_omdb_refresh` when OMDb's tt differs), `review` (`promote_review` rewrites the
  SAME row to reason `no-match-reviewed` with `review_detail(verdict, query)` — id and
  created_at kept; never a second row), `review-open`, `conflict` (held tt/tmdb, TMDB error,
  no client). `--limit` slices actionable (`keyed`/`match`/`review`) only. The verb NEVER
  resolves a `no-match` row (a resolved one blocks the manual `repair links --film` relink
  path); on `--apply` it ends with `rebuild_no_match_queue`, which drops matched films' rows
  as the next sync would. `rebuild_no_match_queue` treats a RESOLVED `no-match-reviewed` row as
  a standing decision (so `--none` does not loop). Auto matches are never ratified into the
  eval CSV (the gate would score itself); human `--pick/--tt/--none` ratify as before, and
  `--pick` on an OMDb-only candidate now resolves the tmdb id via `find_by_imdb`. Candidates
  come from `<config_dir>/nomatch-cache.json.gz` (seeded from the fixture, saved per run) —
  the eval fixture is never written by the verb. A post-`record_tmdb_match` failure logs
  `[partial]` and raises (CLI exit 1).
```

- [ ] **Step 3: `.claude/rules/sync-flow.md`**

In step 6, after "misses → `match_review` reason `no-match`, never retried by sync", add: "(a `no-match-reviewed` row — T4's durable promotion — and a film whose `no-match`/`no-match-reviewed` row a human resolved are both left alone by the per-run rebuild)".

- [ ] **Step 4: Gates + commit**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy`

```bash
git add CLAUDE.md .claude/rules/thumbprint.md .claude/rules/sync-flow.md
git commit -m "docs: repair nomatch contract, durable no-match-reviewed reason"
```

---

## After the plan: rehearsal (owner-driven, not a subagent task)

Not part of the code tasks — run by the main session with the owner watching, per spec §9:

1. `SCRATCH=<scratchpad>/t4-rehearsal`; `cp` live DB + `tmdb-read-token.txt` + `omdb-api-key.txt` + `appletv/`; `export MOVIE_BRAIN_CONFIG_DIR=$SCRATCH` before EVERY command.
2. `movie-brain repair nomatch` (dry run) → paste counts + the full `[match]` list for the owner's eyeball.
3. Owner yes → `--apply --yes --limit 50` batches → `movie-brain sync` → `grep -c 'external id conflict for' "$SCRATCH/sync.log"` must be 0 → before/after counts (open reviews by reason, external ids imdb/tmdb, tmdb found=0).
4. Owner yes → the same on live, batched; one live `sync`; then drain `no-match-reviewed` rows one batch at a time with a recommended verdict per row; `scripts/thumbprint_benchmark.py --refresh` after a ratification batch.
