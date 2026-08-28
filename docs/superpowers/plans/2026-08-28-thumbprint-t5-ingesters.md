# Thumbprint T5 — ingester switch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every film that reaches the keying point is keyed by `domain/thumbprint.resolve()` — auto matches through `record_tmdb_match`, non-matches as durable `no-match-reviewed` A/B/C rows — and `owned import` / Mode-B promotion look an existing work up by its IMDb id before creating a film, so no new twins are minted.

**Architecture:** One new application module, `application/keying.py`, holds the two shared entry points: `key_film()` (the single identity write path, extracted verbatim from T4's `repair nomatch` apply loop) and `key_films()` (the sync step that replaces `pick_tmdb_match`). Every other change is a caller switching to those two functions, plus claims written at ingest so the resolver has an ingested title to work from. The resolver itself (`domain/thumbprint.py`) and the eval fixture are NOT touched by this plan.

**Tech Stack:** Python 3.12, uv, pytest + pytest-bdd, `responses` for HTTP mocks, Typer CLI, SQLite via `infrastructure/database.Repository`, ruff + mypy.

**Spec:** `docs/superpowers/specs/2026-08-28-thumbprint-t5-ingesters-design.md`

## Global Constraints

- **Gates after every task** (all five must pass before the task is committed): `uv run pytest` · `uv run ruff check .` · `uv run mypy` · `uv run python scripts/thumbprint_benchmark.py --assert` (baseline **n=557 / 0 wrong / 92.0 % auto over 526 non-`F-human` rows** — this plan edits neither `domain/thumbprint.py` nor the fixture, so any movement here is a bug in the task) · `uv run python scripts/matching_benchmark.py --assert-dominance`.
- **NEVER edit `scripts/eval/thumbprint_eval_v1.csv` by hand**, and never edit `scripts/eval/fixtures/cand_cache.json.gz`. `application/eval_log.py::ratify` is the only writer.
- **Never run any command against the live database.** Every manual/CLI check in this plan runs with `MOVIE_BRAIN_CONFIG_DIR` pointing at a scratch directory. Tests set it via the autouse `_isolate_env` fixture in `tests/conftest.py`.
- Reason strings produced by `resolve()` are contract — never reword them.
- Markdown written by this plan (docs, rules) is **never hard-wrapped**: one unbroken line per paragraph and list item.
- Commit messages: brief single line, focused on *why*. Branch is `feature/T5-thumbprint-ingesters`; do not merge.

## Deviation from the spec (approved rationale, applies to Tasks 2 and 5)

The spec places `key_film` in `application/thumbprint.py` and `key_films` in `application/availability.py`. That is a circular import: `key_film` needs `record_tmdb_match`/`queue_review_once` from `availability`, while `key_films` needs `review_detail`/`film_query` from `thumbprint`. Both therefore live in a **new module `application/keying.py`**, which imports from `availability` and `thumbprint` and is imported by `sync`, `repair_keys`, `review`, `owned` and `metacritic`. No other module imports `keying`, so no cycle exists.

---

### Task 1: Share the resolver query builder

Promote T4's private `_nomatch_query` to a public `film_query` in `application/thumbprint.py` so sync, owned import and promotion build the same Query the repair verb builds.

**Files:**
- Modify: `src/movie_brain/application/thumbprint.py` (add `film_query`, `_CLAIM_PRECEDENCE`, `_CLAIM_SOURCE`)
- Modify: `src/movie_brain/application/repair_keys.py:355-375` (delete `_nomatch_query`, import and call `film_query`)
- Test: `tests/unit/test_thumbprint_app.py` (new file)
- Modify: `tests/unit/test_repair_nomatch.py` (its `_nomatch_query` import)

**Interfaces:**
- Consumes: `Repository.claims_for_film(film_id) -> list[ClaimRow]` (fields `authority`, `title_ingested`, `year_claimed`, `runtime_min`); `domain.thumbprint.make_query(raw_title, year, source, director=None, runtime_min=None) -> Query`.
- Produces: `application.thumbprint.film_query(repo: Repository, film_id: int, title: str, year: int | None, director: str | None) -> Query`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_thumbprint_app.py`:

```python
from __future__ import annotations

from movie_brain.application.thumbprint import film_query
from movie_brain.domain.models import Film


def _film(repo, today, title, year, director=None, claims=()):
    fid = repo.create_film(Film(title, year, director, ""))
    for authority, ctitle, cyear, runtime in claims:
        repo.add_claim(
            fid, authority, f"{authority}:{title}", ctitle,
            year_claimed=cyear, runtime_min=runtime, first_seen=today.isoformat(),
        )
    return fid


def test_film_query_prefers_criterion_then_metacritic_then_apple(repo, today):
    fid = _film(repo, today, "Bound", 1996, "The Wachowskis", claims=(
        ("apple-tv", "Bound (Unrated)", 1997, 108),
        ("metacritic", "Bound", 1996, None),
        ("criterion", "Bound", 1996, None),
    ))
    q = film_query(repo, fid, "Bound", 1996, "The Wachowskis")
    assert (q.raw_title, q.year, q.source) == ("Bound", 1996, "criterion")


def test_film_query_carries_apple_runtime_even_from_another_source(repo, today):
    fid = _film(repo, today, "Bound", 1996, None, claims=(
        ("apple-tv", "Bound (Unrated)", 1997, 108),
        ("metacritic", "Bound", 1996, None),
    ))
    q = film_query(repo, fid, "Bound", 1996, None)
    assert (q.source, q.runtime_min) == ("metacritic", 108)


def test_film_query_without_claims_falls_back_to_the_film_row(repo, today):
    fid = _film(repo, today, "Bound", 1996, "The Wachowskis")
    q = film_query(repo, fid, "Bound", 1996, "The Wachowskis")
    assert (q.raw_title, q.year, q.source, q.director) == ("Bound", 1996, "unknown", "The Wachowskis")


def test_film_query_apple_claim_maps_to_source_apple(repo, today):
    fid = _film(repo, today, "Bound", 1996, None, claims=(("apple-tv", "Bound (Unrated)", 1997, 108),))
    q = film_query(repo, fid, "Bound", 1996, None)
    assert (q.raw_title, q.year, q.source) == ("Bound (Unrated)", 1997, "apple")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_thumbprint_app.py -v` Expected: FAIL with `ImportError: cannot import name 'film_query'`.

- [ ] **Step 3: Write the implementation**

In `src/movie_brain/application/thumbprint.py`, add near the top (after the existing imports; `make_query` joins the existing `from movie_brain.domain.thumbprint import ...` line):

```python
_CLAIM_PRECEDENCE = ("criterion", "metacritic", "apple-tv")
_CLAIM_SOURCE = {"criterion": "criterion", "metacritic": "metacritic", "apple-tv": "apple"}


def film_query(repo: Repository, film_id: int, title: str, year: int | None, director: str | None) -> Query:
    """What the ingester saw: the film's highest-precedence claim (criterion > metacritic >
    apple-tv), title/year from the claim (year falls back to the film's), director from the
    film row, the apple runtime carried for display and never scored (owner Q3)."""
    claims = repo.claims_for_film(film_id)
    by_auth = {a: next((c for c in claims if c.authority == a), None) for a in _CLAIM_PRECEDENCE}
    chosen = next((by_auth[a] for a in _CLAIM_PRECEDENCE if by_auth[a] is not None), None)
    apple = by_auth["apple-tv"]
    runtime = apple.runtime_min if apple is not None else None
    if chosen is None:
        return make_query(title, year, "unknown", director=director, runtime_min=runtime)
    return make_query(
        chosen.title_ingested or title,
        chosen.year_claimed or year,
        _CLAIM_SOURCE[chosen.authority],
        director=director,
        runtime_min=runtime,
    )
```

In `src/movie_brain/application/repair_keys.py`: delete `_nomatch_query` and the now-unused `_CLAIM_PRECEDENCE`/`_CLAIM_SOURCE` constants, add `film_query` to the existing `from movie_brain.application.thumbprint import review_detail` line, and in `audit_nomatch` replace `q = _nomatch_query(repo, f)` with:

```python
        q = film_query(repo, f.film_id, f.title, f.year, f.director)
```

In `tests/unit/test_repair_nomatch.py`, change the local import `from movie_brain.application.repair_keys import _nomatch_query` to `from movie_brain.application.thumbprint import film_query` and update that test's call site to `film_query(repo, fid, title, year, director)` with the film's own values.

- [ ] **Step 4: Run the gates**

Run: `uv run pytest && uv run ruff check . && uv run mypy && uv run python scripts/thumbprint_benchmark.py --assert && uv run python scripts/matching_benchmark.py --assert-dominance` Expected: all pass; benchmark prints n=557 / 0 wrong / 92.0 %.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "thumbprint: share the resolver query builder across verbs"
```

---

### Task 2: Extract the single identity write path (`key_film`)

**Files:**
- Create: `src/movie_brain/application/keying.py`
- Modify: `src/movie_brain/application/repair_keys.py` (the `repair_nomatch` apply loop calls `key_film`)
- Test: `tests/unit/test_keying.py` (new file)

**Interfaces:**
- Consumes: `film_query` (Task 1); `availability.record_tmdb_match(repo, target, winner_id, winner_year, today, log) -> str`; `Repository.film_id_for_external`, `.tmdb_target`, `.set_external_id`, `.omdb_imdb_id`, `.mark_omdb_refresh`.
- Produces: `application.keying.KeyResult(status: str, tmdb_id: int | None, detail: str)` with `status ∈ {"keyed", "unlinked", "held", "error"}`, and `application.keying.key_film(repo, tmdb, film_id, tt, today, log, *, tmdb_id=None) -> KeyResult`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_keying.py`:

```python
from __future__ import annotations

from datetime import date

import pytest
import requests

from movie_brain.application.keying import key_film
from movie_brain.domain.models import Film, OmdbRating


class FakeTmdb:
    def __init__(self, by_imdb=None, years=None, boom=False):
        self.by_imdb, self.years, self.boom = by_imdb or {}, years or {}, boom

    def find_by_imdb(self, tt):
        if self.boom:
            raise requests.ConnectionError("offline")
        return self.by_imdb.get(tt)

    def movie_year(self, tid):
        if self.boom:
            raise requests.ConnectionError("offline")
        return self.years.get(tid)


def _film(repo, today, title, year, *, commerce=True):
    fid = repo.create_film(Film(title, year, None, ""))
    repo.upsert_omdb(fid, OmdbRating(None, None, False, None, None), today)
    if not commerce:
        repo.record_listing(fid, "criterion", f"https://c/{title.lower()}", today)
    return fid


def test_key_film_writes_both_ids_and_queues_an_omdb_refresh(repo, today):
    fid = _film(repo, today, "Bound", 1996)
    r = key_film(repo, FakeTmdb(by_imdb={"tt0116367": 9081}, years={9081: 1996}), fid, "tt0116367", today, print)
    assert (r.status, r.tmdb_id) == ("keyed", 9081)
    ids = repo.external_ids_for(fid)
    assert (ids["imdb"], ids["tmdb"]) == ("tt0116367", "9081")
    assert repo.tmdb_found(fid) is True


def test_key_film_without_a_tmdb_record_is_unlinked_but_keeps_the_imdb_id(repo, today):
    fid = _film(repo, today, "Solfatara", 1990)
    r = key_film(repo, FakeTmdb(), fid, "tt9999999", today, print)
    assert r.status == "unlinked"
    assert repo.external_ids_for(fid)["imdb"] == "tt9999999"
    assert repo.external_ids_for(fid).get("tmdb") is None


def test_key_film_refuses_a_tt_another_film_holds_and_writes_nothing(repo, today):
    holder = _film(repo, today, "Bound", 1996)
    repo.set_external_id(holder, "imdb", "tt0116367", today)
    other = _film(repo, today, "Bound", 1997)
    r = key_film(repo, FakeTmdb(), other, "tt0116367", today, print)
    assert r.status == "held" and f"#{holder}" in r.detail
    assert repo.external_ids_for(other) == {}


def test_key_film_refuses_a_tmdb_id_another_film_holds(repo, today):
    holder = _film(repo, today, "Bound", 1996)
    repo.set_external_id(holder, "tmdb", "9081", today)
    other = _film(repo, today, "Bound", 1997)
    r = key_film(repo, FakeTmdb(by_imdb={"tt0116367": 9081}), other, "tt0116367", today, print)
    assert r.status == "held" and r.tmdb_id == 9081
    assert repo.external_ids_for(other) == {}


def test_key_film_reports_tmdb_weather_as_error_without_writing(repo, today):
    fid = _film(repo, today, "Bound", 1996)
    r = key_film(repo, FakeTmdb(boom=True), fid, "tt0116367", today, print)
    assert r.status == "error"
    assert repo.external_ids_for(fid) == {}


def test_key_film_canonicalizes_a_commerce_film_year_to_tmdb(repo, today):
    fid = _film(repo, today, "Stop Making Sense", 2023)
    key_film(repo, FakeTmdb(by_imdb={"tt0088178": 606}, years={606: 1984}), fid, "tt0088178", today, print)
    assert repo.get_view(fid, today).year == 1984


def test_key_film_leaves_a_criterion_film_year_alone(repo, today):
    fid = _film(repo, today, "Trio", 1950, commerce=False)
    key_film(repo, FakeTmdb(by_imdb={"tt0037800": 11}, years={11: 1949}), fid, "tt0037800", today, print)
    assert repo.get_view(fid, today).year == 1950
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_keying.py -v` Expected: FAIL with `ModuleNotFoundError: No module named 'movie_brain.application.keying'`.

- [ ] **Step 3: Write the implementation**

Create `src/movie_brain/application/keying.py`:

```python
"""The identity write path (thumbprint T5): one function keys one film, everywhere.

`key_film` is the verbatim apply loop T4's `repair nomatch` proved on 99 live films, lifted
out so the sync keying step, the repair verbs and `review resolve` cannot drift apart. Holder
checks run BEFORE any write, so a film is either fully keyed or untouched — except a
post-`record_tmdb_match` failure, the one case that logs `[partial]` and raises.
"""

from __future__ import annotations

import sqlite3
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import requests

from movie_brain.application.availability import TMDB_AUTHORITY, record_tmdb_match
from movie_brain.infrastructure.database import Repository
from movie_brain.infrastructure.tmdb import AuthError, TmdbClient

# record_tmdb_match results that leave the film fully keyed; anything else is a [partial].
KEYED_OK = ("matched", "adopted", "collision")


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


@dataclass(frozen=True)
class KeyResult:
    status: str  # "keyed" | "unlinked" | "held" | "error"
    tmdb_id: int | None = None
    detail: str = ""


def key_film(
    repo: Repository,
    tmdb: TmdbClient | None,
    film_id: int,
    tt: str,
    today: date,
    log: Callable[[str], None] = _stderr,
    *,
    tmdb_id: int | None = None,
) -> KeyResult:
    """Key one film to an IMDb id (plus its TMDB id when one exists). Nothing is written
    unless every holder check passes, so `held` and `error` leave the film untouched."""
    holder = repo.film_id_for_external("imdb", tt)
    if holder is not None and holder != film_id:
        return KeyResult("held", tmdb_id, f"{tt} already held by #{holder}")
    tid = tmdb_id
    winner_year: int | None = None
    try:
        if tid is None and tmdb is not None:
            tid = tmdb.find_by_imdb(tt)
        if tid is not None:
            th = repo.film_id_for_external(TMDB_AUTHORITY, str(tid))
            if th is not None and th != film_id:
                return KeyResult("held", tid, f"tmdb {tid} already held by #{th}")
            winner_year = tmdb.movie_year(tid) if tmdb is not None else None
    except (requests.RequestException, AuthError) as exc:
        return KeyResult("error", tid, str(exc))
    try:
        repo.set_external_id(film_id, "imdb", tt, today)
    except sqlite3.IntegrityError:
        return KeyResult("held", tid, f"{tt} already held")
    detail = "no TMDB record"
    if tid is not None:
        target = repo.tmdb_target(film_id)
        if target is None:
            raise RuntimeError(f"[partial] #{film_id} vanished after its imdb id was written")
        res = record_tmdb_match(repo, target, tid, winner_year, today, log)
        if res not in KEYED_OK:
            partial = f"[partial] #{film_id} PARTIAL: imdb {tt} written but tmdb {tid} {res}"
            log(partial)
            raise RuntimeError(partial)
        detail = res
    if repo.omdb_imdb_id(film_id) != tt:
        repo.mark_omdb_refresh(film_id)
    return KeyResult("keyed" if tid is not None else "unlinked", tid, detail)
```

- [ ] **Step 4: Run the new test**

Run: `uv run pytest tests/unit/test_keying.py -v` Expected: PASS (7 tests).

- [ ] **Step 5: Switch `repair_nomatch` onto `key_film`**

In `src/movie_brain/application/repair_keys.py`, import `from movie_brain.application.keying import key_film` and replace the body of the apply loop from `assert g.tt is not None` down to `applied += 1` with:

```python
        assert g.tt is not None
        if tmdb is None:
            log("  no TMDB client — skipped")
            skipped += 1
            continue
        r = key_film(repo, tmdb, g.film_id, g.tt, today, log, tmdb_id=g.tmdb_id)
        if r.status == "held":
            log(f"  {r.detail} — skipped")
            skipped += 1
            continue
        if r.status == "error":
            log(f"  TMDB error: {r.detail} — skipped")
            skipped += 1
            continue
        if r.tmdb_id is None:
            log(f"  keyed imdb {g.tt} (no TMDB record)")
        elif r.detail == "collision":
            log(f"  keyed imdb {g.tt} tmdb {r.tmdb_id} (collision → year-collision review queued)")
        else:
            log(f"  keyed imdb {g.tt} tmdb {r.tmdb_id} ({r.detail})")
        applied += 1
```

Delete the now-unused `NOMATCH_SUCCESS` constant from `repair_keys.py` (its role moved to `keying.KEYED_OK`) and drop any import left unused (`sqlite3` stays only if still referenced — run ruff to find out). The `omdb refresh queued` log line moves inside `key_film`, so its `repair nomatch` counterpart is deleted; the behaviour is unchanged.

- [ ] **Step 6: Run the gates**

Run: `uv run pytest && uv run ruff check . && uv run mypy && uv run python scripts/thumbprint_benchmark.py --assert && uv run python scripts/matching_benchmark.py --assert-dominance` Expected: all pass. If a `repair nomatch` step-def asserts on the removed "omdb refresh queued" line, update the expectation to the surviving log line rather than restoring the old code.

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "thumbprint: one identity write path shared by every keying caller"
```

---

### Task 3: One session fetcher for every resolver caller

**Files:**
- Modify: `src/movie_brain/infrastructure/thumbprint_fetch.py` (add `FIXTURE_PATH`, `session_fetcher`)
- Modify: `src/movie_brain/cli.py:420-445` (`repair nomatch` uses it)
- Test: `tests/unit/test_thumbprint_fetch.py` (add cases)

**Interfaces:**
- Produces: `infrastructure.thumbprint_fetch.session_fetcher(config_dir: Path, tmdb: TmdbClient | None, omdb: OmdbClient | None) -> tuple[CandidateFetcher | None, CandidateCache | None]` — `(None, None)` when either client is missing; otherwise a fetcher over the read-only eval fixture data merged with `<config_dir>/nomatch-cache.json.gz`, and the writable session cache to `save()` in a `finally`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_thumbprint_fetch.py`:

```python
def test_session_fetcher_needs_both_clients(tmp_path):
    from movie_brain.infrastructure.thumbprint_fetch import session_fetcher

    assert session_fetcher(tmp_path, None, None) == (None, None)
    assert session_fetcher(tmp_path, object(), None) == (None, None)


def test_session_fetcher_seeds_from_the_fixture_and_saves_only_the_session_cache(tmp_path):
    import gzip
    import json

    from movie_brain.infrastructure.thumbprint_fetch import FIXTURE_PATH, session_fetcher

    session = tmp_path / "nomatch-cache.json.gz"
    with gzip.open(session, "wt", encoding="utf-8") as f:
        json.dump({"ts:Local|1999": []}, f)
    before = FIXTURE_PATH.read_bytes()
    fetcher, cache = session_fetcher(tmp_path, object(), object())
    assert fetcher is not None and cache is not None
    assert "ts:Local|1999" in cache.data  # session entry survives
    assert len(cache.data) > 1  # fixture data merged in
    cache.data["ts:New|2000"] = []
    cache.save()
    assert FIXTURE_PATH.read_bytes() == before  # the fixture is never written
    with gzip.open(session, "rt", encoding="utf-8") as f:
        assert "ts:New|2000" in json.load(f)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_thumbprint_fetch.py -k session_fetcher -v` Expected: FAIL with `ImportError: cannot import name 'session_fetcher'`.

- [ ] **Step 3: Write the implementation**

In `src/movie_brain/infrastructure/thumbprint_fetch.py`, after the imports:

```python
# Same parents[3] convention as database.MIGRATIONS_DIR: <repo root>/scripts/eval/fixtures/…
FIXTURE_PATH = Path(__file__).resolve().parents[3] / "scripts" / "eval" / "fixtures" / "cand_cache.json.gz"
SESSION_CACHE_NAME = "nomatch-cache.json.gz"
```

and at the end of the module:

```python
def session_fetcher(
    config_dir: Path, tmdb: TmdbClient | None, omdb: OmdbClient | None
) -> tuple[CandidateFetcher | None, CandidateCache | None]:
    """The live resolver's candidate source: fixture hits are free, misses hit the clients and
    are saved to the per-config session cache. The eval fixture is NEVER written — the gate
    would otherwise score itself on data the resolver just produced."""
    if tmdb is None or omdb is None:
        return None, None
    data = dict(CandidateCache.load(FIXTURE_PATH, read_only=True).data)
    session_path = config_dir / SESSION_CACHE_NAME
    if session_path.exists():
        data.update(CandidateCache.load(session_path).data)
    cache = CandidateCache(data, session_path)
    return CandidateFetcher(cache, tmdb, omdb), cache
```

In `src/movie_brain/cli.py`, replace the hand-rolled cache construction inside `repair_nomatch_cmd` with:

```python
    fetcher, cache = session_fetcher(cfg.config_dir, tmdb, OmdbClient(key) if key else None)
```

keeping the existing `finally: if cache is not None: cache.save()`. Import `session_fetcher` alongside the existing `CandidateCache`/`CandidateFetcher` local imports; drop those two imports if ruff reports them unused.

- [ ] **Step 4: Run the gates**

Run: `uv run pytest && uv run ruff check . && uv run mypy && uv run python scripts/thumbprint_benchmark.py --assert && uv run python scripts/matching_benchmark.py --assert-dominance` Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "thumbprint: one session-cache fetcher for every resolver caller"
```

---

### Task 4: Ingesters write their claims

Without this the resolver has no ingested title for a film created tonight. `add_claim` is `INSERT OR IGNORE` on `UNIQUE(authority, value)`, so every writer here is idempotent and re-running a sync writes nothing new.

**Files:**
- Modify: `src/movie_brain/domain/thumbprint.py` (add `edition_label`)
- Modify: `src/movie_brain/application/thumbprint.py` (`_edition_label` delegates to the domain function)
- Modify: `src/movie_brain/infrastructure/database.py` (`record_catalog` writes the criterion claim inline)
- Modify: `src/movie_brain/application/metacritic.py` (`match_archive` slug link, `create_from_staged`, `promote_top_n`)
- Modify: `src/movie_brain/application/owned.py` (`import_owned`)
- Test: `tests/features/tmdb.feature`, `tests/features/metacritic.feature`, `tests/features/owned.feature` + their step defs

**Interfaces:**
- Produces: `domain.thumbprint.edition_label(raw: str) -> str | None` (`" / "`-joined editions, `None` when the title carries none).
- Claim rows written: criterion `(value=listing url, title_ingested=Criterion title, year_claimed=Criterion year)`; metacritic `(value=slug, title_ingested=raw MC title, year_claimed=MC year)`; apple-tv `(value=raw Apple title, title_ingested=raw Apple title, year_claimed=Apple field year, runtime_min=Apple runtime)`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/features/tmdb.feature`:

```gherkin
  Scenario: The Criterion walk records a claim for every film it lists
    When I sync
    Then "Trio (1950)" has a "criterion" claim titled "Trio" for year 1950
```

Add to `tests/features/metacritic.feature` (inside the promotion block):

```gherkin
  Scenario: Promotion records a metacritic claim for the film it creates
    Given the archive page 1 has "Fresh Find" slug "fresh-find" 2020 score 90
    When I promote the top 10
    Then "Fresh Find (2020)" has a "metacritic" claim titled "Fresh Find" for year 2020
```

Add to `tests/features/owned.feature`:

```gherkin
  Scenario: The Apple import records a claim carrying the raw title and runtime
    Given the repository holds the film "Seven Samurai (1954)"
    And my Apple TV library has "Seven Samurai (Unrated)" (1954) running 207 minutes
    When I import owned films
    Then "Seven Samurai (1954)" has an "apple-tv" claim titled "Seven Samurai (Unrated)" for year 1954
    And that claim has runtime 207 and edition label "unrated"
```

Add this shared step to `tests/step_defs/test_tmdb.py`, `tests/step_defs/test_metacritic.py` and `tests/step_defs/test_owned.py` (each file already has a `_film`/key helper — reuse it for the film id):

```python
@then(parsers.parse('"{title_year}" has a "{authority}" claim titled "{ingested}" for year {year:d}'))
def has_claim(ctx, title_year, authority, ingested, year):
    fid = ctx["repo"].film_id_by_key(_film(title_year).key)
    claims = [c for c in ctx["repo"].claims_for_film(fid) if c.authority == authority]
    assert claims, f"no {authority} claim on #{fid}"
    assert (claims[0].title_ingested, claims[0].year_claimed) == (ingested, year)
    ctx["claim"] = claims[0]
```

and in `tests/step_defs/test_owned.py` only:

```python
@given(parsers.re(r'my Apple TV library has "(?P<title>[^"]+)" \((?P<year>\d+)\) running (?P<mins>\d+) minutes'))
def library_has_runtime(ctx, title, year, mins):
    ctx["library"].append(OwnedTitle(title, int(year), int(mins)))


@then(parsers.parse('that claim has runtime {mins:d} and edition label "{label}"'))
def claim_runtime(ctx, mins, label):
    assert (ctx["claim"].runtime_min, ctx["claim"].edition_label) == (mins, label)
```

In `tests/step_defs/test_tmdb.py`, `_film` does not exist — add `then` using the existing key convention: `fid = ctx["repo"].film_id_by_key(title_year.lower().replace(" (", " (")` is fragile, so instead reuse the pattern already in that file: `fid = ctx["repo"].film_id_by_key(f"{title.lower()} ({year})")` by parsing `title_year` with `re.fullmatch(r"(.+) \((\d{4})\)", title_year)`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/step_defs/test_tmdb.py tests/step_defs/test_metacritic.py tests/step_defs/test_owned.py -k claim -v` Expected: FAIL — `no criterion claim on #1` (and the metacritic/apple equivalents).

- [ ] **Step 3: Write the implementation**

In `src/movie_brain/domain/thumbprint.py`, after `title_norm`:

```python
def edition_label(raw: str) -> str | None:
    """The edition annotations a title carries, joined — `None` when it carries none."""
    eds = parse_title(raw).editions
    return " / ".join(eds) if eds else None
```

In `src/movie_brain/application/thumbprint.py`, delete the private `_edition_label` and import the domain one, updating its call sites in `backfill_claims`.

In `src/movie_brain/infrastructure/database.py`, add `edition_label` to the domain imports and, inside `record_catalog`'s per-film loop after `self._write_listing(...)`:

```python
                # The resolver reads the claim, not films.title: the ingested title and the
                # claimed year are what the ingester actually saw (thumbprint T5).
                c.execute(
                    "INSERT OR IGNORE INTO claim (film_id, authority, value, title_ingested, "
                    "year_claimed, edition_label, first_seen) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (film_id, source, film.url, film.title, film.year, edition_label(film.title), day),
                )
```

(Written inline against the open cursor rather than through `add_claim`, which would open a second connection inside this transaction.)

In `src/movie_brain/application/metacritic.py`:
- in `match_archive`, after the successful `repo.set_external_id(film_id, AUTHORITY, slugs[0], today)`, add `repo.add_claim(film_id, AUTHORITY, slugs[0], t_by_slug[slugs[0]].title, year_claimed=t_by_slug[slugs[0]].year, first_seen=today.isoformat())` where `t_by_slug = {t.slug: t for t in deduped_titles}` is built next to `slugs_by_film`.
- in `create_from_staged`, after its `set_external_id`: `repo.add_claim(film_id, AUTHORITY, t.slug, t.title, year_claimed=t.year, first_seen=today.isoformat())`.
- in `promote_top_n`, after its `set_external_id`: the same call with the loop's `t`.

In `src/movie_brain/application/owned.py`, immediately before `if not repo.mark_owned(film_id, today):`:

```python
        repo.add_claim(
            film_id, AUTHORITY, t.title, t.title,
            year_claimed=t.year, edition_label=edition_label(t.title),
            runtime_min=t.runtime_min, first_seen=today.isoformat(),
        )
```

with `from movie_brain.domain.thumbprint import edition_label` added to its imports. (`t.title` is the raw Apple title — the claim's value and its ingested title are the same string by design, so a re-import is a no-op.)

- [ ] **Step 4: Run the gates**

Run: `uv run pytest && uv run ruff check . && uv run mypy && uv run python scripts/thumbprint_benchmark.py --assert && uv run python scripts/matching_benchmark.py --assert-dominance` Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "thumbprint: every ingester records what it actually saw as a claim"
```

---

### Task 5: The keying step replaces `pick_tmdb_match` in sync

The heart of T5. After this task the resolver is live.

**Files:**
- Modify: `src/movie_brain/infrastructure/database.py` (`TmdbMatchTarget` gains `director`; `_TMDB_TARGET_SELECT` selects it)
- Modify: `src/movie_brain/application/keying.py` (add `key_films`, `KeyStepResult`)
- Modify: `src/movie_brain/application/availability.py` (`tmdb_step` drops its match loop and its `arbiter` parameter)
- Modify: `src/movie_brain/application/sync.py` (build the fetcher, run keying BEFORE the OMDb loop, new `SyncResult` fields)
- Modify: `src/movie_brain/cli.py` (sync summary line)
- Test: `tests/features/tmdb.feature` + `tests/step_defs/test_tmdb.py` (search mocks → injected fetcher)

**Interfaces:**
- Consumes: `key_film` (Task 2), `film_query` (Task 1), `session_fetcher` (Task 3), `review_detail(verdict, query) -> str`, `queue_review_once`, `rebuild_no_match_queue`, `NO_MATCH_REVIEWED`.
- Produces: `keying.KeyStepResult(keyed: int, reviewed: int, held: int, failed: int, aborted: bool)`; `keying.key_films(repo, fetcher, tmdb, today, log=_stderr) -> KeyStepResult`; `sync(..., fetcher=None)` injection point; `SyncResult.tmdb_reviewed`, `SyncResult.omdb_unkeyed`.
- `TmdbMatchTarget` becomes `(film_id, title, year, commerce, director)` — `director` defaults to `None` so existing positional constructions keep working.

- [ ] **Step 1: Write the failing tests**

Replace the search-mocked scenarios in `tests/features/tmdb.feature` with resolver-pool ones (keep every provider/refresh scenario exactly as it is):

```gherkin
  Scenario: A new film is keyed by the resolver and its ids stored
    Given the resolver pool has "Trio" → tt0037800/11 1950 by "Someone"
    And TMDB streams id 11 on providers 1899 and 258
    When I sync with a TMDB token
    Then "Trio (1950)" has external id "11" for authority "tmdb"
    And "Trio (1950)" has external id "tt0037800" for authority "imdb"
    And the sync matched 1 TMDB films
    And the tmdb review queue holds 0 entries

  Scenario: An ambiguous film becomes a durable A/B/C review row, never a guess
    Given the resolver pool has "Trio" ambiguous between tt0037800/11 1950 and tt0037801/12 1952
    When I sync with a TMDB token
    Then the tmdb review queue holds a "no-match-reviewed" entry
    And the review detail offers candidates "tt0037800" and "tt0037801"
    When I sync with a TMDB token again the next day
    Then the tmdb review queue holds 1 "no-match-reviewed" entries

  Scenario: A film the resolver cannot key at all still gets one durable row
    Given the resolver pool is empty
    When I sync with a TMDB token
    Then the tmdb review queue holds a "no-match-reviewed" entry
    And the tmdb review queue holds 0 "no-match" entries

  Scenario: A commerce film adopts TMDB's original year through the resolver
    Given a commerce film "Stop Making Sense" from 2023
    And the resolver pool has "Stop Making Sense" → tt0088178/606 1984 by ""
    When I sync with a TMDB token
    Then the film "Stop Making Sense" has year 1984 and key "stop making sense (1984)"

  Scenario: A tt another film already holds queues id-conflict, never a second claim
    Given a commerce film "Trio" from 1952
    And the film "Trio (1952)" already holds imdb "tt0037800"
    And the resolver pool has "Trio" → tt0037800/11 1950 by "Someone"
    When I sync with a TMDB token
    Then the tmdb review queue holds a "id-conflict" entry
```

Rewrite the TMDB fixture in `tests/step_defs/test_tmdb.py`: keep the `responses` mocks for `/movie/{id}/watch/providers`, delete `do_search`/`/search/movie` registration and the `TMDB search was called N times` step (and every feature line using it), and add:

```python
class PoolFetcher:
    """Stands in for CandidateFetcher: canned candidates per query title."""

    def __init__(self):
        self.pool: dict[str, list[Candidate]] = {}
        self.empty = False

    def fetch(self, q):
        if self.empty:
            return []
        return self.pool.get(q.title, [])


@pytest.fixture
def pool(ctx):
    ctx["pool"] = PoolFetcher()
    return ctx["pool"]


@given(parsers.re(
    r'the resolver pool has "(?P<title>[^"]+)" → (?P<tt>tt\d+)/(?P<tid>\d+) (?P<year>\d{4}) by "(?P<director>[^"]*)"'
))
def pool_one(pool, title, tt, tid, year, director):
    pool.pool[title] = [
        Candidate(tt, int(tid), (title,), int(year), director, 100, 5000, "movie", True, True)
    ]


@given(parsers.re(
    r'the resolver pool has "(?P<title>[^"]+)" ambiguous between (?P<a>tt\d+)/(?P<ida>\d+) (?P<ya>\d{4}) '
    r'and (?P<b>tt\d+)/(?P<idb>\d+) (?P<yb>\d{4})'
))
def pool_two(pool, title, a, ida, ya, b, idb, yb):
    pool.pool[title] = [
        Candidate(a, int(ida), (title,), int(ya), "", 100, 50, "movie", True, True),
        Candidate(b, int(idb), (title,), int(yb), "", 100, 60, "movie", True, True),
    ]


@given("the resolver pool is empty")
def pool_empty(pool):
    pool.empty = True


@given(parsers.parse('the film "{title} ({year:d})" already holds imdb "{tt}"'))
def already_holds(ctx, title, year, tt):
    fid = ctx["repo"].film_id_by_key(f"{title.lower()} ({year})")
    ctx["repo"].set_external_id(fid, "imdb", tt, TODAY)


@then(parsers.parse('the review detail offers candidates "{a}" and "{b}"'))
def detail_candidates(ctx):
    from movie_brain.application.thumbprint import parse_review_detail

    rows = [r for r in ctx["repo"].open_reviews("tmdb") if r["reason"] == "no-match-reviewed"]
    tts = {c["tt"] for c in parse_review_detail(str(rows[0]["detail"])).candidates}
    assert {a, b} <= tts
```

Every `When I sync…` step passes the pool through: `sync(ctx["repo"], "omdb-key", TODAY, tmdb_token="tok", fetcher=ctx.get("pool"))`. Also seed `/find/{tt}` and `/movie/{id}` responses for the ids the pool serves, since `key_film` calls `movie_year` (the pool supplies `tmdb_id`, so `find_by_imdb` is not called):

```python
def register_movie(ctx, tid, year):
    ctx["rs"].add(responses.GET, f"{TMDB_API}/movie/{tid}", json={"id": tid, "release_date": f"{year}-01-01"})
```

called from `pool_one`/`pool_two` via `ctx`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/step_defs/test_tmdb.py -v` Expected: FAIL — `sync() got an unexpected keyword argument 'fetcher'`.

- [ ] **Step 3: Widen `TmdbMatchTarget` with the director**

In `src/movie_brain/infrastructure/database.py`:

```python
class TmdbMatchTarget(NamedTuple):
    """One film awaiting a TMDB match, with the policy bit the wrapper needs."""

    film_id: int
    title: str
    year: int | None
    commerce: bool  # no criterion listing → commerce-created; year is COMMERCE band
    director: str | None = None  # the resolver's strongest search key (thumbprint T5)
```

and `_TMDB_TARGET_SELECT` becomes `"SELECT f.id, f.title, f.year, f.director, " + …`. Update the three `TmdbMatchTarget(...)` constructions (`films_needing_tmdb_match`, `films_tmdb_missed_targets`, `tmdb_target`) to pass `r["director"]` as the fifth argument.

- [ ] **Step 4: Write `key_films`**

Append to `src/movie_brain/application/keying.py` (extending its imports with `Verdict`-free names only: `resolve`, `film_query`, `review_detail`, `queue_review_once`, `rebuild_no_match_queue`, `NO_MATCH_REVIEWED`, `ReviewEntry`, `CacheMiss`, `QuotaExceeded`):

```python
MAX_CONSECUTIVE_FAILURES = 5


@dataclass(frozen=True)
class KeyStepResult:
    keyed: int = 0
    reviewed: int = 0
    held: int = 0
    failed: int = 0
    aborted: bool = False


def key_films(
    repo: Repository,
    fetcher: CandidateFetcher | None,
    tmdb: TmdbClient | None,
    today: date,
    log: Callable[[str], None] = _stderr,
) -> KeyStepResult:
    """Key every film that has never been looked up (thumbprint T5, memo step 5).

    A `match` is written through `key_film`; anything else becomes ONE durable
    `no-match-reviewed` row carrying the resolver's A/B/C candidates, so the next sync
    never re-resolves a film a human is already looking at.
    """
    if fetcher is None:
        log("no resolver fetcher (needs both a TMDB token and an OMDb key) — skipping keying")
        return KeyStepResult()
    keyed = reviewed = held = failed = 0
    consecutive = 0
    aborted = False
    for target in repo.films_needing_tmdb_match():
        if consecutive >= MAX_CONSECUTIVE_FAILURES:
            log("resolver lookups failing repeatedly — stopping keying; next run resumes.")
            aborted = True
            break
        q = film_query(repo, target.film_id, target.title, target.year, target.director)
        try:
            verdict = resolve(q, fetcher.fetch(q))
        except (CacheMiss, requests.RequestException, AuthError, QuotaExceeded) as exc:
            log(f"resolver lookup failed for {target.title!r}: {exc}")
            consecutive += 1
            failed += 1
            continue
        consecutive = 0
        if verdict.kind != "match" or verdict.tt is None:
            repo.upsert_tmdb(target.film_id, found=False, looked_up=today)
            queue_review_once(
                repo,
                TMDB_AUTHORITY,
                ReviewEntry(NO_MATCH_REVIEWED, film_id=target.film_id, detail=review_detail(verdict, q)),
                today,
            )
            reviewed += 1
            continue
        winner = next((s.candidate for s in verdict.ranked if s.candidate.tt == verdict.tt), None)
        result = key_film(
            repo, tmdb, target.film_id, verdict.tt, today, log,
            tmdb_id=winner.tmdb_id if winner is not None else None,
        )
        if result.status in ("keyed", "unlinked"):
            keyed += 1
            continue
        if result.status == "error":
            log(f"TMDB error keying {target.title!r}: {result.detail}")
            consecutive += 1
            failed += 1
            continue
        # held: the id belongs to another film — a twin. Durable row, never a silent overwrite.
        repo.upsert_tmdb(target.film_id, found=False, looked_up=today)
        queue_review_once(
            repo,
            TMDB_AUTHORITY,
            ReviewEntry(
                "id-conflict",
                film_id=target.film_id,
                value=str(result.tmdb_id) if result.tmdb_id is not None else verdict.tt,
                detail=f"{target.title!r} ({target.year}) — {result.detail}, likely twins",
            ),
            today,
        )
        held += 1
    rebuild_no_match_queue(repo, today)
    return KeyStepResult(keyed, reviewed, held, failed, aborted)
```

- [ ] **Step 5: Strip the old match loop out of `tmdb_step`**

In `src/movie_brain/application/availability.py`, delete the `for target in repo.films_needing_tmdb_match():` loop, the `arbiter` parameter and the `rebuild_no_match_queue(repo, today)` call that followed the loop (it now lives in `key_films`). `tmdb_step` starts at `pmap = repo.provider_map()` and returns `TmdbStepResult(...)` with `matched`/`missed` supplied by its caller:

```python
def tmdb_step(
    repo: Repository,
    client: TmdbClient,
    today: date,
    *,
    log: Callable[[str], None] = _stderr,
) -> TmdbStepResult:
    """Provider passes only — keying moved to `application.keying.key_films` (thumbprint T5)."""
    refreshed = 0
    pmap = repo.provider_map()
    ...
```

Remove the now-unused `pick_tmdb_match` and `TmdbArbiter` imports from `availability.py` (they stay in `domain/matching.py` and `infrastructure/tmdb.py` for `rematch` and `match_archive`).

- [ ] **Step 6: Rewire `sync`**

In `src/movie_brain/application/sync.py`: add `fetcher: CandidateFetcher | None = None` to the signature, drop the `arbiter` construction, and place the keying step between Mode-B promotion and the OMDb loop:

```python
    tmdb_client = TmdbClient(tmdb_token, session=session) if tmdb_token else None
    omdb_client = OmdbClient(api_key, session=session)
    cache = None
    if fetcher is None and config_dir is not None:
        fetcher, cache = session_fetcher(config_dir, tmdb_client, omdb_client)

    # … Mode-B promotion block unchanged, minus `arbiter=arbiter` …

    keyed = KeyStepResult()
    if not ratings_only:
        try:
            keyed = key_films(repo, fetcher, tmdb_client, today, log)
        except Exception as exc:  # noqa: BLE001 — keying must never break the rest of the sync
            log(f"keying step failed: {exc}")
    if cache is not None:
        cache.save()
```

The OMDb loop then uses `omdb_client` and calls `tmdb_step(repo, tmdb_client, today, log=log)`. `SyncResult` gains `tmdb_reviewed: int = 0` and `omdb_unkeyed: int = 0`; return `keyed.keyed` as `tmdb_matched`, `keyed.reviewed + keyed.held + keyed.failed` as `tmdb_missed`, and `keyed.reviewed` as `tmdb_reviewed`. Update `cli.py`'s sync summary to add `· keyed: {result.tmdb_matched} · review: {result.tmdb_reviewed}`.

- [ ] **Step 7: Run the gates**

Run: `uv run pytest && uv run ruff check . && uv run mypy && uv run python scripts/thumbprint_benchmark.py --assert && uv run python scripts/matching_benchmark.py --assert-dominance` Expected: all pass. `tests/step_defs/test_rematch.py` and `tests/unit/test_availability.py` may reference the removed `arbiter` parameter — update those call sites; do NOT reintroduce the parameter.

- [ ] **Step 8: Commit**

```bash
git add -A && git commit -m "thumbprint: sync keys new films through the resolver, not the title matcher"
```

---

### Task 6: OMDb by IMDb id only

**Consequence to state plainly in the commit body:** with no TMDB token (or no resolver fetcher) nothing gets keyed, so nothing gets an OMDb record. The OMDb step is now downstream of identity by design (memo §1: an unkeyed work is never enriched by title search).

**Files:**
- Modify: `src/movie_brain/application/sync.py` (OMDb loop)
- Modify: `src/movie_brain/infrastructure/omdb.py` (delete `lookup` and `_query`)
- Modify: `tests/unit/test_omdb.py` (delete the `lookup`-by-title tests, keep quota/auth coverage via `lookup_by_imdb`)
- Modify: `tests/features/sync.feature` + `tests/step_defs/test_sync.py` (ratings scenarios need a keyed film)

**Interfaces:**
- Consumes: `_resolve_imdb_id(repo, tmdb, film_id, today, log) -> str | None` (already in `sync.py`).
- Produces: `SyncResult.omdb_unkeyed` — films skipped because they hold no IMDb id.

- [ ] **Step 1: Write the failing test**

Add to `tests/features/tmdb.feature`:

```gherkin
  Scenario: An unkeyed film is never looked up by title
    Given the resolver pool is empty
    And OMDb answers only lookups by IMDb id
    When I sync with a TMDB token
    Then "Trio (1950)" has no OMDb rating
    And OMDb was never asked by title

  Scenario: A film keyed tonight gets its OMDb record tonight
    Given the resolver pool has "Trio" → tt0037800/11 1950 by "Someone"
    And OMDb answers only lookups by IMDb id
    When I sync with a TMDB token
    Then "Trio (1950)" has an OMDb rating
```

with this step in `tests/step_defs/test_tmdb.py` (the `OMDb answers only lookups by IMDb id` given already exists — extend its callback to record the params it saw):

```python
@then("OMDb was never asked by title")
def omdb_never_by_title(ctx):
    assert ctx["omdb_title_calls"] == 0, f"{ctx['omdb_title_calls']} title lookups"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/step_defs/test_tmdb.py -k "unkeyed or tonight" -v` Expected: FAIL — the second scenario fails because the OMDb loop runs before keying (`no OMDb rating`), the first because a title lookup still happens.

- [ ] **Step 3: Write the implementation**

In `src/movie_brain/application/sync.py`'s OMDb loop:

```python
        try:
            imdb_id = _resolve_imdb_id(repo, tmdb_client, film_id, today, log)
            if imdb_id is None:
                # An unkeyed work is never enriched by title search (memo §1): OMDb's `t=`
                # accepted stubs for films it did not have. The film re-enters this queue
                # every run at zero API cost until the resolver keys it.
                unkeyed += 1
                continue
            rating = client.lookup_by_imdb(imdb_id)
```

with `unkeyed = 0` initialised beside `looked_up` and returned as `SyncResult.omdb_unkeyed`.

In `src/movie_brain/infrastructure/omdb.py`, delete `lookup` and `_query` (keep `_fetch`, `lookup_by_imdb`, `search`, `by_id`, `_raw`).

In `tests/features/sync.feature`, every scenario asserting `N films have OMDb ratings` gains `And the resolver keys every film` after its `And OMDb knows every film` line, backed by this step in `tests/step_defs/test_sync.py`:

```python
@given("the resolver keys every film")
def resolver_keys_all(ctx):
    """A pool that answers any query with a synthetic keyed candidate, so the OMDb loop
    has an IMDb id to look up (T5: no id, no OMDb record)."""

    class AllFetcher:
        def fetch(self, q):
            tt = f"tt{abs(hash(q.title)) % 9000000:07d}"
            tid = abs(hash(q.title)) % 90000
            ctx["rs"].add(responses.GET, f"{TMDB_API}/movie/{tid}", json={"id": tid, "release_date": "1950-01-01"})
            return [Candidate(tt, tid, (q.title,), q.year, "Someone", 100, 5000, "movie", True, True)]

    ctx["pool"] = AllFetcher()
```

and each `When I sync…` step in that file passes `fetcher=ctx.get("pool")` and `tmdb_token="tok" if ctx.get("pool") else None`. Scenarios that deliberately have no ratings (quota, auth failure, `--ratings-only` without a catalog) keep their current expectations.

- [ ] **Step 4: Run the gates**

Run: `uv run pytest && uv run ruff check . && uv run mypy && uv run python scripts/thumbprint_benchmark.py --assert && uv run python scripts/matching_benchmark.py --assert-dominance` Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "thumbprint: OMDb is fetched by IMDb id only; an unkeyed work is never title-searched"
```

---

### Task 7: Series are works with `kind = series`, keyed by their IMDb id

**Files:**
- Modify: `src/movie_brain/infrastructure/tmdb.py` (`FindResult`, `find_by_imdb_any`)
- Modify: `src/movie_brain/infrastructure/database.py` (`set_film_kind`, `film_kind`, `kind = 'movie'` filters)
- Modify: `src/movie_brain/application/review.py` (`resolve_review(..., series=False)`)
- Modify: `src/movie_brain/cli.py` (`--series` flag; `review list` shows a non-movie kind)
- Test: `tests/unit/test_tmdb.py`, `tests/features/review.feature`, `tests/step_defs/test_review.py`

**Interfaces:**
- Produces: `TmdbClient.find_by_imdb_any(tt: str) -> FindResult(movie_id: int | None, tv: bool)`; `Repository.set_film_kind(film_id: int, kind: str) -> None`; `Repository.film_kind(film_id: int) -> str`; `resolve_review(..., series: bool = False)`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_tmdb.py`:

```python
@responses.activate
def test_find_by_imdb_any_reports_a_tv_only_hit():
    responses.get(
        f"{TMDB_API}/find/tt0092337",
        json={"movie_results": [], "tv_results": [{"id": 2001}], "tv_episode_results": []},
    )
    assert TmdbClient("tok").find_by_imdb_any("tt0092337") == FindResult(None, True)


@responses.activate
def test_find_by_imdb_any_prefers_the_movie_hit():
    responses.get(
        f"{TMDB_API}/find/tt0037800",
        json={"movie_results": [{"id": 11}], "tv_results": [], "tv_episode_results": []},
    )
    assert TmdbClient("tok").find_by_imdb_any("tt0037800") == FindResult(11, False)
```

`tests/features/review.feature`:

```gherkin
  Scenario: --tt on a series keys it by IMDb id alone and marks the kind
    Given an open tmdb "no-match-reviewed" review for "Dekalog (1988)"
    And TMDB finds "tt0092337" only as a series
    When I resolve it with tt "tt0092337"
    Then "Dekalog (1988)" holds imdb "tt0092337" and no tmdb id
    And the film "Dekalog (1988)" has kind "series"
    And the film "Dekalog (1988)" is not a keying target

  Scenario: --series forces the kind when TMDB knows nothing at all
    Given an open tmdb "no-match-reviewed" review for "Dekalog (1988)"
    And TMDB finds nothing for "tt0092337"
    When I resolve it with tt "tt0092337" and --series
    Then the film "Dekalog (1988)" has kind "series"

  Scenario: --series is refused when TMDB says the id is a movie
    Given an open tmdb "no-match-reviewed" review for "King Kong (1933)"
    And TMDB finds "tt0024216" as id 244 released in 1933
    When I resolve it with tt "tt0024216" and --series it is refused
    Then the error mentions "TMDB has a movie"
```

with the matching step defs in `tests/step_defs/test_review.py`:

```python
@given(parsers.parse('TMDB finds "{tt}" only as a series'))
def tmdb_find_series(ctx, tt):
    ctx["rs"].add(responses.GET, f"{TMDB_API}/find/{tt}",
                  json={"movie_results": [], "tv_results": [{"id": 2001}], "tv_episode_results": []})
    ctx["client"] = TmdbClient("tok")


@given(parsers.parse('TMDB finds nothing for "{tt}"'))
def tmdb_find_nothing(ctx, tt):
    ctx["rs"].add(responses.GET, f"{TMDB_API}/find/{tt}",
                  json={"movie_results": [], "tv_results": [], "tv_episode_results": []})
    ctx["client"] = TmdbClient("tok")


@when(parsers.parse('I resolve it with tt "{tt}" and --series'))
def do_tt_series(ctx, tt):
    _resolve(ctx, tt=tt, series=True)


@when(parsers.parse('I resolve it with tt "{tt}" and --series it is refused'))
def do_tt_series_refused(ctx, tt):
    with pytest.raises(ValueError) as exc:
        _resolve(ctx, tt=tt, series=True)
    ctx["error"] = str(exc.value)


@then(parsers.parse('the film "{spec}" has kind "{kind}"'))
def film_kind(ctx, spec, kind):
    assert ctx["repo"].film_kind(_id(ctx["repo"], spec)) == kind


@then(parsers.parse('the film "{spec}" is not a keying target'))
def not_a_target(ctx, spec):
    fid = _id(ctx["repo"], spec)
    assert fid not in [t.film_id for t in ctx["repo"].films_needing_tmdb_match()]
    assert fid not in [f for f, _, _ in ctx["repo"].films_tmdb_missed()]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_tmdb.py -k find_by_imdb_any tests/step_defs/test_review.py -k series -v` Expected: FAIL with `ImportError: cannot import name 'FindResult'`.

- [ ] **Step 3: Write the implementation**

`src/movie_brain/infrastructure/tmdb.py`:

```python
class FindResult(NamedTuple):
    """What `/find` knows about an IMDb id: TMDB movie id, and whether TV knows it."""

    movie_id: int | None
    tv: bool
```

```python
    def find_by_imdb_any(self, tt: str) -> FindResult:
        """One `/find` call reporting BOTH namespaces. A series holds no `external_ids.tmdb`
        (TMDB movie and TV ids share one integer namespace and the providers endpoint is
        movie-only), so the caller keys a tv-only hit by IMDb id alone."""
        d = self._get(f"/find/{tt}", external_source="imdb_id").json()
        movies = d.get("movie_results") or []
        tv = bool(d.get("tv_results") or d.get("tv_episode_results"))
        return FindResult(int(movies[0]["id"]) if movies else None, tv)

    def find_by_imdb(self, tt: str) -> int | None:
        """TMDB movie id for an IMDb id (one call) — the reverse of imdb_id()."""
        return self.find_by_imdb_any(tt).movie_id
```

`src/movie_brain/infrastructure/database.py`:

```python
    def set_film_kind(self, film_id: int, kind: str) -> None:
        """`movie` | `series` — a series is keyed by its IMDb id alone (memo Q2)."""
        with self._conn() as c:
            c.execute("UPDATE films SET kind = ? WHERE id = ?", (kind, film_id))

    def film_kind(self, film_id: int) -> str:
        with self._conn() as c:
            row = c.execute("SELECT kind FROM films WHERE id = ?", (film_id,)).fetchone()
            return "movie" if row is None else str(row["kind"])
```

Add `AND f.kind = 'movie'` to the WHERE clauses of `films_needing_tmdb_match`, `films_tmdb_missed`, `films_tmdb_missed_targets` and `nomatch_worklist`.

`src/movie_brain/application/review.py` — add `series: bool = False` to `resolve_review`, reject it outside `--tt` (`if series and tt is None: raise ValueError("--series applies only to --tt")`), and in the `--tt` branch:

```python
        elif tt is not None:
            chosen_tt = tt
            found = client.find_by_imdb_any(tt) if client is not None else None
            is_series = series or (found is not None and found.movie_id is None and found.tv)
            if series and found is not None and found.movie_id is not None:
                raise ValueError(f"TMDB has a movie for {tt} (id {found.movie_id}) — drop --series")
            chosen_tmdb = None if is_series else (found.movie_id if found is not None else None)
            if chosen_tmdb is None and not is_series:
                warn(f"tmdb id not resolved for {tt} (no client or no TMDB record); imdb only")
```

and, after the id writes, `if is_series: repo.set_film_kind(rid, "series")` with the outcome string `f"keyed series imdb {chosen_tt}"`. Initialise `is_series = False` next to `chosen_tmdb` so the `--pick`/`--none` paths are unaffected.

`src/movie_brain/cli.py` — add the flag and pass it through:

```python
    series: Annotated[bool, typer.Option("--series", help="With --tt: this work is a series (IMDb id only).")] = False,
```

and in `review_list`, render the film cell as `f"#{r['film_id']} {r['title']} ({r['year']})"` plus `f" [{kind}]"` when the row's film kind is not `movie` (add `f.kind` to `list_reviews`' SELECT).

- [ ] **Step 4: Run the gates**

Run: `uv run pytest && uv run ruff check . && uv run mypy && uv run python scripts/thumbprint_benchmark.py --assert && uv run python scripts/matching_benchmark.py --assert-dominance` Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "thumbprint: a series is a work keyed by its IMDb id, never a TMDB movie id"
```

---

### Task 8: `owned import` resolves to the existing work before creating one

**Files:**
- Modify: `src/movie_brain/application/owned.py`
- Modify: `src/movie_brain/cli.py` (`owned import` builds the fetcher)
- Test: `tests/features/owned.feature`, `tests/step_defs/test_owned.py`

**Interfaces:**
- Consumes: `key_film`, `session_fetcher`, `make_query`, `resolve`, `Repository.film_id_for_external`, `Repository.canonical_film_id`.
- Produces: `import_owned(repo, config_dir, today, *, fetch=None, fetcher=None, tmdb=None, log=_stderr) -> OwnedReport`; `OwnedReport` gains `resolved_to_existing: int` and `keyed: int`.

- [ ] **Step 1: Write the failing tests**

```gherkin
  Scenario: An owned edition lands on the keyed work instead of twinning it
    Given the repository holds the film "Blade Runner (1982)" keyed imdb "tt0083658" tmdb "78"
    And my Apple TV library has "Blade Runner (The Final Cut)" (2007)
    And the resolver pool has "Blade Runner (The Final Cut)" → tt0083658/78 1982
    When I import owned films
    Then "Blade Runner (1982)" is owned
    And the repository holds 1 films
    And the owned report says 0 created and 1 resolved to existing

  Scenario: An owned film nobody holds is created and keyed in one pass
    Given my Apple TV library has "Step Brothers" (2008)
    And the resolver pool has "Step Brothers" → tt1023111/12133 2008
    When I import owned films
    Then the film "Step Brothers (2008)" exists with a guid
    And "Step Brothers (2008)" holds imdb "tt1023111" and tmdb id "12133"
    And the owned report says 1 created and 1 keyed

  Scenario: An ambiguous owned title falls back to the corpus path, never a guess
    Given the repository holds the film "Nosferatu (1922)"
    And my Apple TV library has "Nosferatu" (2024)
    And the resolver pool has "Nosferatu" ambiguous
    When I import owned films
    Then the review queue has a "year-drift" entry
    And the repository holds 1 films

  Scenario: With no resolver the import behaves exactly as before
    Given my Apple TV library has "Step Brothers" (2008)
    When I import owned films without a resolver
    Then the film "Step Brothers (2008)" exists with a guid
    And the owned report says 1 created and 0 keyed
```

Step defs mirror Task 5's pool fixture (a `PoolFetcher` seeded per raw title) plus a `FakeTmdb` supplying `movie_year`; `run_import` passes `fetcher=ctx.get("pool")` and `tmdb=ctx.get("tmdb")`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/step_defs/test_owned.py -v` Expected: FAIL — `import_owned() got an unexpected keyword argument 'fetcher'`.

- [ ] **Step 3: Write the implementation**

In `src/movie_brain/application/owned.py`, add the parameters and, at the top of the per-title loop (before `result = match_owned(...)`):

```python
        verdict = None
        if fetcher is not None:
            q = make_query(t.title, year, "apple", runtime_min=t.runtime_min)
            try:
                verdict = resolve(q, fetcher.fetch(q))
            except (CacheMiss, requests.RequestException, AuthError, QuotaExceeded) as exc:
                log(f"resolver lookup failed for {t.title!r}: {exc}")
        if verdict is not None and verdict.kind == "match" and verdict.tt is not None:
            # The work this edition belongs to may already be in the DB under its own
            # title — landing on it is what stops the import minting a twin (T5b).
            holder = repo.film_id_for_external("imdb", verdict.tt)
            if holder is None:
                winner = next((s.candidate for s in verdict.ranked if s.candidate.tt == verdict.tt), None)
                if winner is not None and winner.tmdb_id is not None:
                    holder = repo.film_id_for_external("tmdb", str(winner.tmdb_id))
            if holder is not None:
                film_id = repo.canonical_film_id(holder)
                resolved += 1
                _claim_and_mark(repo, film_id, t, today)   # the Task 4 claim + mark_owned block
                continue
```

and, in the branch that creates a film (`new_id = repo.create_film(film)` succeeded), immediately after `created += 1`:

```python
                if verdict is not None and verdict.kind == "match" and verdict.tt is not None:
                    winner = next((s.candidate for s in verdict.ranked if s.candidate.tt == verdict.tt), None)
                    r = key_film(
                        repo, tmdb, film_id, verdict.tt, today, log,
                        tmdb_id=winner.tmdb_id if winner is not None else None,
                    )
                    if r.status in ("keyed", "unlinked"):
                        keyed += 1
                    else:
                        log(f"created #{film_id} unkeyed ({r.status}: {r.detail}); the next sync will retry")
```

Extract the trailing claim + `mark_owned` lines into a small module-level `_claim_and_mark(repo, film_id, t, today) -> bool` (returns `mark_owned`'s value) so both paths share it. `OwnedReport` gains `resolved_to_existing` and `keyed`; `cli.py`'s `owned import` builds `session_fetcher(cfg.config_dir, tmdb, omdb)` (saving the cache in a `finally`) and prints the two new counters.

- [ ] **Step 4: Run the gates**

Run: `uv run pytest && uv run ruff check . && uv run mypy && uv run python scripts/thumbprint_benchmark.py --assert && uv run python scripts/matching_benchmark.py --assert-dominance` Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "owned import: land an edition on the work it belongs to instead of twinning it"
```

---

### Task 9: Mode-B promotion resolves before it creates

**Files:**
- Modify: `src/movie_brain/application/metacritic.py` (`promote_top_n`)
- Modify: `src/movie_brain/application/sync.py` (pass fetcher/tmdb into promotion)
- Test: `tests/features/metacritic.feature`, `tests/step_defs/test_metacritic.py`

**Interfaces:**
- Produces: `promote_top_n(repo, config_dir, today, n, *, arbiter=None, fetcher=None, tmdb=None, log=_stderr)`; `PromoteReport` gains `linked_by_key: int` and `keyed: int`.

- [ ] **Step 1: Write the failing tests**

```gherkin
  Scenario: A staged title whose work is already keyed claims the slug instead of twinning
    Given the repository holds the film "Bound (1996)" keyed imdb "tt0116367" tmdb "9081"
    And the archive page 1 has "Bound" slug "bound" 1996 score 90
    And the resolver pool has "Bound" → tt0116367/9081 1996
    When I promote the top 10 with a resolver
    Then "Bound (1996)" has metacritic slug "bound"
    And the repository holds 1 films
    And the promote report says 0 promoted and 1 linked by key

  Scenario: A staged title nobody holds is promoted and keyed in one pass
    Given the archive page 1 has "Fresh Find" slug "fresh-find" 2020 score 90
    And the resolver pool has "Fresh Find" → tt5000000/50000 2020
    When I promote the top 10 with a resolver
    Then "Fresh Find (2020)" holds imdb "tt5000000" and tmdb id "50000"
    And the promote report says 1 promoted and 1 keyed
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/step_defs/test_metacritic.py -k resolver -v` Expected: FAIL — `promote_top_n() got an unexpected keyword argument 'fetcher'`.

- [ ] **Step 3: Write the implementation**

In `promote_top_n`, immediately before `film_id = repo.create_film(film)`:

```python
        verdict = None
        if fetcher is not None:
            q = make_query(t.title, t.year, "metacritic")
            try:
                verdict = resolve(q, fetcher.fetch(q))
            except (CacheMiss, requests.RequestException, AuthError, QuotaExceeded) as exc:
                log(f"resolver lookup failed for {t.title!r}: {exc}")
        if verdict is not None and verdict.kind == "match" and verdict.tt is not None:
            holder = repo.film_id_for_external("imdb", verdict.tt)
            if holder is not None:
                # The work is already here under its own title — claim the slug, don't twin it.
                holder = repo.canonical_film_id(holder)
                try:
                    repo.set_external_id(holder, AUTHORITY, t.slug, today)
                    repo.add_claim(holder, AUTHORITY, t.slug, t.title, year_claimed=t.year,
                                   first_seen=today.isoformat())
                    claimed.add(t.slug)
                    linked_by_key += 1
                except sqlite3.IntegrityError:
                    reviews.append(ReviewEntry("slug-conflict", film_id=holder, value=t.slug,
                                               detail="slug already claimed by another film"))
                continue
```

and after a successful creation + slug claim, key the new film exactly as Task 8 does (`key_film(...)`, counting `keyed`). `sync.py` passes `fetcher=fetcher, tmdb=tmdb_client` into `promote_top_n`.

- [ ] **Step 4: Run the gates**

Run: `uv run pytest && uv run ruff check . && uv run mypy && uv run python scripts/thumbprint_benchmark.py --assert && uv run python scripts/matching_benchmark.py --assert-dominance` Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "mode-B promotion: claim the slug on the work we already hold"
```

---

### Task 10: The rehearsal harness

A scratch-only script that manufactures keying work so the switch can be measured against known-good answers (the live DB has zero films awaiting keying).

**Files:**
- Create: `scripts/rehearsal/strip_keys.py`
- Test: `tests/unit/test_strip_keys.py`

**Interfaces:**
- Produces: CLI `uv run python scripts/rehearsal/strip_keys.py --count 300 [--manifest PATH]` — refuses to run unless `MOVIE_BRAIN_CONFIG_DIR` is set AND the resolved db path is not `~/.config/movie-brain/movie-brain.db`; writes `<config_dir>/strip-manifest.json` as `[{"film_id", "title", "year", "stratum", "imdb", "tmdb"}]`; and `compare(manifest_path, db_path) -> dict` reporting per-stratum `agree / disagree / reviewed / unkeyed`.

- [ ] **Step 1: Write the failing test**

```python
def test_strip_keys_refuses_the_live_database(tmp_path, monkeypatch):
    monkeypatch.delenv("MOVIE_BRAIN_CONFIG_DIR", raising=False)
    from scripts.rehearsal.strip_keys import guard_scratch_only

    with pytest.raises(SystemExit):
        guard_scratch_only(Path.home() / ".config" / "movie-brain" / "movie-brain.db")


def test_strip_and_compare_round_trip(repo, today, tmp_path):
    from scripts.rehearsal.strip_keys import compare, strip

    fid = repo.create_film(Film("Bound", 1996, "The Wachowskis", ""))
    repo.set_external_id(fid, "imdb", "tt0116367", today)
    repo.set_external_id(fid, "tmdb", "9081", today)
    repo.upsert_tmdb(fid, found=True, looked_up=today)
    manifest = strip(repo, count=10, manifest_path=tmp_path / "m.json")
    assert manifest[0]["imdb"] == "tt0116367"
    assert repo.external_ids_for(fid) == {}
    repo.set_external_id(fid, "imdb", "tt0116367", today)
    repo.set_external_id(fid, "tmdb", "9081", today)
    assert compare(tmp_path / "m.json", repo)["agree"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_strip_keys.py -v` Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.rehearsal'`.

- [ ] **Step 3: Write the implementation**

Create `scripts/rehearsal/__init__.py` (empty) and `scripts/rehearsal/strip_keys.py` with `guard_scratch_only(db_path)`, `strip(repo, count, manifest_path)` (stratified: films holding both ids with `tmdb.found=1`, `count//3` each from criterion-listed-with-director, metacritic-claimed, apple-claimed; deletes the two `external_ids` rows and the `tmdb` row per film), `compare(manifest_path, repo)`, and a `main()` wiring them with `argparse`.

- [ ] **Step 4: Run the gates**

Run: `uv run pytest && uv run ruff check . && uv run mypy && uv run python scripts/thumbprint_benchmark.py --assert && uv run python scripts/matching_benchmark.py --assert-dominance` Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "rehearsal: manufacture keying work on a scratch DB and score the re-key"
```

---

### Task 11: Documentation and rules

**Files:**
- Modify: `CLAUDE.md`, `.claude/rules/thumbprint.md`, `.claude/rules/sync-flow.md`, `docs/multiple-movie-services.md`
- Create: `docs/superpowers/handoffs/2026-08-29-thumbprint-t6-handoff.md` (written at the end of the rehearsal, with real numbers)

- [ ] **Step 1: Update `.claude/rules/sync-flow.md`**

Rewrite the numbered contract as seven steps: cheap check → `merge_yearless` → `record_catalog` (+ criterion claims) → Mode-B promotion (resolve-first, + metacritic claims) → **keying (`key_films`)** → OMDb **by IMDb id only** → TMDB provider passes + notifications. State that an unkeyed film gets no OMDb record, and that a keying failure is caught by sync so one step's weather never breaks the others.

- [ ] **Step 2: Update `.claude/rules/thumbprint.md`**

Replace the DARK bullet with the live contract: `application/keying.py` holds `key_film` (the one identity write path — holder checks before any write, `[partial]` raises) and `key_films` (the sync step); `film_query` builds every resolver query from the highest-precedence claim; `session_fetcher` is the one candidate source and NEVER writes the eval fixture; every ingester writes its claim at ingest; a `review` verdict becomes ONE durable `no-match-reviewed` row (sync no longer mints plain `no-match` rows); series are `kind='series'`, IMDb id only, excluded from every keying and no-match query. Add `src/movie_brain/application/keying.py` and `src/movie_brain/application/owned.py` to the rule's `paths:` frontmatter.

- [ ] **Step 3: Update `CLAUDE.md`**

Sync line: note keying runs before the OMDb loop and OMDb is fetched by IMDb id only. `review resolve` line: add `--series`. Year-precedence bullet: TMDB > embedded year > Criterion (±2) > Apple field > Metacritic (memo §6). Same precedence correction in `docs/multiple-movie-services.md`.

- [ ] **Step 4: Run the gates and commit**

```bash
uv run pytest && uv run ruff check . && uv run mypy
~/code/praxis-workspace/praxis-halo/bin/unwrap-md CLAUDE.md .claude/rules/thumbprint.md .claude/rules/sync-flow.md
git add -A && git commit -m "docs: the resolver is live — sync order, keying contract, series kind"
```

---

## Rehearsal (after Task 11, before any live run)

Every command below runs with `MOVIE_BRAIN_CONFIG_DIR` exported to the scratch directory — subagents included. Nothing here touches `~/.config/movie-brain/`.

- [ ] **R1: Build the scratch copy**

```bash
export MOVIE_BRAIN_CONFIG_DIR=/private/tmp/claude-501/-Users-jayers-code-movie-brain/5dde7615-bc43-4b89-809c-8ca90852dcde/scratchpad/t5-scratch
mkdir -p "$MOVIE_BRAIN_CONFIG_DIR"
rsync -a ~/.config/movie-brain/ "$MOVIE_BRAIN_CONFIG_DIR/"
uv run movie-brain status
```

- [ ] **R2: Plain sync** — `uv run movie-brain sync 2>&1 | tail -20`. Expected: 0 keying targets, 0 title lookups, exit 0.

- [ ] **R3: Re-key 300** — `uv run python scripts/rehearsal/strip_keys.py --count 300`, then `uv run movie-brain sync`, then the comparison. Report the per-stratum table. **Bar: 0 disagreements.** A disagreement is investigated on its evidence and reported — never patched into the eval CSV.

- [ ] **R4: Owned import replay** — `uv run movie-brain owned import` against the newest `appletv/owned-*.txt`. Report matched / resolved-to-existing / created / keyed / review, and name every created film.

- [ ] **R5: Series drain** — resolve the Dekalog `no-match-reviewed` row with `review resolve <id> --tt tt0092337`; confirm `kind='series'`, imdb only, no tmdb id, and that a following `sync` leaves it alone.

- [ ] **R6: Report every number to the owner and STOP.** Live application (merge, one sync, the remaining series rows one at a time) happens only after an explicit yes.

---

## Self-review notes

- **Spec coverage:** §4.1 → Tasks 1–3; §4.2 → Task 5; §4.3 → Tasks 5, 6, 11; §4.4 → Task 5 (`fetcher is None` log) and Task 6; §4.5 → Task 4; §5.1 → Task 8; §5.2 → Task 9; §6 → Task 7; §7 → tests inside each task; §8 → Task 10 + the rehearsal block; §9 → Task 11.
- **Known deviation:** `key_film`/`key_films` live in `application/keying.py`, not `thumbprint.py`/`availability.py` (import cycle — see the note above the tasks).
- **Deferred, unchanged by this plan:** `rematch`, `pick_tmdb_match`, `TmdbArbiter`, `match_archive`'s arbiter, `edition_year` at ingest, series providers/dashboard, and the T4 leftovers.
