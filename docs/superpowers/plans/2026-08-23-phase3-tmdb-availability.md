# Phase 3: TMDB Availability Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cross-service streaming availability (TMDB watch providers) for every film, visible in the dashboard drawer as "Also streaming on: …".

**Architecture:** Hexagonal, mirroring the OMDb integration: pure match rules in `domain/matching.py`, a `TmdbClient` in `infrastructure/tmdb.py`, a `tmdb` cache table + Repository primitives, and a tripwired TMDB step in the sync that writes availability into the existing `listings` table (source = service slug). Drawer-only UI.

**Tech Stack:** Python 3.12, sqlite3, requests, Flask, Typer; pytest + pytest-bdd + responses + Playwright; uv, ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-08-23-phase3-tmdb-availability-design.md` — read it first; it carries the settled, dated decisions.

## Global Constraints

- svod availability = TMDB `flatrate` only; `rent`/`buy` read only for provider 2 → `apple-tv-store` rows.
- The TMDB step NEVER writes `listings` rows with source `criterion` (provider 258 ignored on write).
- Amazon-channel provider ids (1825, 201, 287) are not in `service_provider` — anything absent from the map is silently ignored.
- Collectors never delete: a dropped service just stops `last_seen` bumps; unmatched films go to `match_review` (authority `tmdb`).
- New migration only (`migrations/005_tmdb.sql`); never edit applied migrations; wrap in BEGIN/COMMIT.
- A TMDB failure must never change the sync exit code or affect the Criterion/OMDb steps.
- Missing TMDB token → step skipped with one log line, sync otherwise normal.
- Weekly full provider refresh gated on meta key `tmdb_providers_refreshed_at`, written only when the pass completes.
- Every file starts with `from __future__ import annotations`; match existing comment density and idiom.
- After each task: `uv run pytest` green, then commit. `uv run ruff check .` and `uv run mypy` must be green at least at Tasks 4, 5, 6.
- Execute in a git worktree (superpowers:using-git-worktrees), branch `feature/STORY-P3-tmdb-availability`.

---

### Task 1: Migration 005 + Repository TMDB primitives

**Files:**
- Create: `migrations/005_tmdb.sql`
- Modify: `src/movie_brain/infrastructure/database.py` (add methods after the `# metacritic` section, before `# meta`)
- Test: `tests/unit/test_database.py` (append)

**Interfaces:**
- Consumes: existing `Repository` (`set_external_id`, `record_listing`, `replace_unresolved_reviews`), `external_ids` table, `service_provider` table (seeded in migration 003).
- Produces (Task 4 relies on these exact signatures):
  - `Repository.films_needing_tmdb_match() -> list[tuple[int, str, int | None]]` — `(film_id, title, year)` for films with no `tmdb` row, ordered by id.
  - `Repository.upsert_tmdb(film_id: int, *, found: bool, looked_up: date) -> None`
  - `Repository.record_tmdb_providers(film_id: int, checked: date, payload: str) -> None`
  - `Repository.films_for_provider_refresh() -> list[tuple[int, str]]` — `(film_id, tmdb_id_value)` for `found=1` films, stalest `providers_checked_at` first (NULLs first).
  - `Repository.films_tmdb_missed() -> list[tuple[int, str, int | None]]` — `(film_id, title, year)` where `found=0`.
  - `Repository.provider_map() -> dict[int, str]` — `tmdb_provider_id -> service_slug` from `service_provider`.

- [ ] **Step 1: Write the migration**

```sql
-- Phase 3: TMDB availability (spec: docs/superpowers/specs/2026-08-23-phase3-tmdb-availability-design.md).
-- Additive only. tmdb caches the one-shot match verdict (found=0 is never retried by sync)
-- and the latest raw US watch-providers payload; the TMDB numeric id itself lives in
-- external_ids (authority 'tmdb'), never here.
BEGIN;
CREATE TABLE tmdb (
    film_id INTEGER PRIMARY KEY REFERENCES films(id),
    found INTEGER NOT NULL,
    looked_up TEXT NOT NULL,
    providers_checked_at TEXT,
    payload TEXT
);
INSERT INTO schema_version (version) VALUES (5);
COMMIT;
```

- [ ] **Step 2: Write failing unit tests**

Append to `tests/unit/test_database.py` (it already has a `repo` fixture from `tests/conftest.py` and imports `date`; reuse the file's existing helpers/imports — add `from movie_brain.domain.models import Film` only if not already imported):

```python
class TestTmdbPrimitives:
    def seed_two(self, repo):
        repo.record_catalog("criterion", [Film("Trio", 1950, None, "https://c/trio"),
                                          Film("Quartet", 1948, None, "https://c/quartet")], date(2026, 8, 19))
        return repo.film_id_by_key("trio (1950)"), repo.film_id_by_key("quartet (1948)")

    def test_films_needing_tmdb_match_excludes_any_tmdb_row(self, repo):
        trio, quartet = self.seed_two(repo)
        repo.upsert_tmdb(trio, found=True, looked_up=date(2026, 8, 19))
        assert repo.films_needing_tmdb_match() == [(quartet, "Quartet", 1948)]
        repo.upsert_tmdb(quartet, found=False, looked_up=date(2026, 8, 19))
        assert repo.films_needing_tmdb_match() == []  # found=0 is not retried

    def test_provider_refresh_order_is_stalest_first(self, repo):
        trio, quartet = self.seed_two(repo)
        for fid, tid in ((trio, "11"), (quartet, "22")):
            repo.upsert_tmdb(fid, found=True, looked_up=date(2026, 8, 19))
            repo.set_external_id(fid, "tmdb", tid, date(2026, 8, 19))
        repo.record_tmdb_providers(trio, date(2026, 8, 19), "{}")
        assert repo.films_for_provider_refresh() == [(quartet, "22"), (trio, "11")]  # NULL checked_at first

    def test_missed_films_and_provider_map(self, repo):
        trio, _ = self.seed_two(repo)
        repo.upsert_tmdb(trio, found=False, looked_up=date(2026, 8, 19))
        assert repo.films_tmdb_missed() == [(trio, "Trio", 1950)]
        pmap = repo.provider_map()
        assert pmap[258] == "criterion" and pmap[1899] == "max" and pmap[2] == "apple-tv-store"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_database.py -k Tmdb -v`
Expected: FAIL — `AttributeError: 'Repository' object has no attribute 'upsert_tmdb'` (the migration alone won't fix this).

- [ ] **Step 4: Implement the Repository methods**

Add a `# tmdb` section to `database.py` (style-match the `# metacritic` section):

```python
    # tmdb --------------------------------------------------------------
    def films_needing_tmdb_match(self) -> list[tuple[int, str, int | None]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT f.id, f.title, f.year FROM films f "
                "WHERE NOT EXISTS (SELECT 1 FROM tmdb t WHERE t.film_id = f.id) ORDER BY f.id"
            ).fetchall()
            return [(int(r["id"]), str(r["title"]), r["year"]) for r in rows]

    def upsert_tmdb(self, film_id: int, *, found: bool, looked_up: date) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO tmdb (film_id, found, looked_up) VALUES (?, ?, ?) "
                "ON CONFLICT(film_id) DO UPDATE SET found=excluded.found, looked_up=excluded.looked_up",
                (film_id, int(found), looked_up.isoformat()),
            )

    def record_tmdb_providers(self, film_id: int, checked: date, payload: str) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE tmdb SET providers_checked_at = ?, payload = ? WHERE film_id = ?",
                (checked.isoformat(), payload, film_id),
            )

    def films_for_provider_refresh(self) -> list[tuple[int, str]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT t.film_id, x.value FROM tmdb t "
                "JOIN external_ids x ON x.film_id = t.film_id AND x.authority = 'tmdb' "
                "WHERE t.found = 1 "
                "ORDER BY (t.providers_checked_at IS NOT NULL), t.providers_checked_at, t.film_id"
            ).fetchall()
            return [(int(r["film_id"]), str(r["value"])) for r in rows]

    def films_tmdb_missed(self) -> list[tuple[int, str, int | None]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT f.id, f.title, f.year FROM films f JOIN tmdb t ON t.film_id = f.id "
                "WHERE t.found = 0 ORDER BY f.id"
            ).fetchall()
            return [(int(r["id"]), str(r["title"]), r["year"]) for r in rows]

    def provider_map(self) -> dict[int, str]:
        with self._conn() as c:
            rows = c.execute("SELECT tmdb_provider_id, service_slug FROM service_provider").fetchall()
            return {int(r["tmdb_provider_id"]): str(r["service_slug"]) for r in rows}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_database.py -v`
Expected: all PASS (old tests included — the migration is additive).

- [ ] **Step 6: Commit**

```bash
git add migrations/005_tmdb.sql src/movie_brain/infrastructure/database.py tests/unit/test_database.py
git commit -m "TMDB cache table + repository primitives for the availability adapter"
```

---

### Task 2: Domain match rules — `pick_tmdb_match`

**Files:**
- Modify: `src/movie_brain/domain/models.py` (add `TmdbCandidate` after `McTitle`)
- Modify: `src/movie_brain/domain/matching.py` (append; reuse `norm_title`)
- Test: `tests/unit/test_matching.py` (append)

**Interfaces:**
- Produces (Tasks 3–4 rely on these exactly):

```python
@dataclass(frozen=True)
class TmdbCandidate:
    """One TMDB search result, reduced to what matching needs."""
    tmdb_id: int
    title: str
    original_title: str
    year: int | None
    popularity: float
```

- `pick_tmdb_match(title: str, year: int | None, candidates: list[TmdbCandidate]) -> int | None`

**Rules (spec §Matching — our years are original years, unlike the Metacritic mc_year+2 rule):**
1. Exact `norm_title` match (against `title` OR `original_title`) with |candidate year − ours| ≤ 1 → highest popularity wins.
2. Fallback: first of the top 3 candidates with |year − ours| ≤ 1 (any title).
3. Our film year-less: exact-title only, highest popularity; candidates' missing years never satisfy a year window.
4. Otherwise `None`.

- [ ] **Step 1: Write failing unit tests**

```python
from movie_brain.domain.matching import pick_tmdb_match
from movie_brain.domain.models import TmdbCandidate


def c(tmdb_id, title, year, pop=1.0, original=None):
    return TmdbCandidate(tmdb_id, title, original or title, year, pop)


class TestPickTmdbMatch:
    def test_exact_title_within_a_year_highest_popularity(self):
        cands = [c(1, "Solaris", 2002, pop=9.0), c(2, "Solaris", 1972, pop=5.0), c(3, "Solaris", 1972, pop=8.0)]
        assert pick_tmdb_match("Solaris", 1972, cands) == 3

    def test_original_title_and_punctuation_match(self):
        cands = [c(4, "Forbidden Lies", 2007, original="Forbidden Lie$")]
        assert pick_tmdb_match("Forbidden Lie$", 2007, cands) == 4

    def test_near_year_fallback_takes_first_of_top_three(self):
        cands = [c(5, "Something Else", 1961), c(6, "Other", 1990), c(7, "Another", 1960)]
        assert pick_tmdb_match("The Original Title", 1960, cands) == 5

    def test_fallback_never_reaches_past_top_three(self):
        cands = [c(1, "A", 1990), c(2, "B", 1990), c(3, "C", 1990), c(4, "D", 1960)]
        assert pick_tmdb_match("Missing Film", 1960, cands) is None

    def test_yearless_film_matches_exact_title_only_by_popularity(self):
        # norm_title keeps unicode letters ("Sanshō" != "Sansho"), so use identical titles here.
        cands = [c(8, "Sansho the Bailiff", 1954, pop=3.0), c(9, "Sansho the Bailiff", 1980, pop=1.0)]
        assert pick_tmdb_match("Sansho the Bailiff", None, cands) == 8
        assert pick_tmdb_match("Nothing Like It", None, cands) is None

    def test_no_candidates(self):
        assert pick_tmdb_match("Anything", 2000, []) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_matching.py -k Tmdb -v`
Expected: FAIL with ImportError (`pick_tmdb_match` not defined).

- [ ] **Step 3: Implement**

`domain/models.py` — add the `TmdbCandidate` dataclass exactly as in Interfaces. `domain/matching.py` — append:

```python
def pick_tmdb_match(title: str, year: int | None, candidates: list[TmdbCandidate]) -> int | None:
    """Pick the TMDB movie a film refers to, or None for the review queue.

    Unlike Metacritic (US re-release years), our years are original years: exact
    normalized-title matches within ±1 year win on popularity; otherwise the first
    of the top-3 results within ±1 year; a year-less film matches on title alone.
    """
    key = norm_title(title)
    exact = [c for c in candidates if norm_title(c.title) == key or norm_title(c.original_title) == key]
    if year is None:
        return max(exact, key=lambda c: c.popularity).tmdb_id if exact else None
    exact_year = [c for c in exact if c.year is not None and abs(c.year - year) <= 1]
    if exact_year:
        return max(exact_year, key=lambda c: c.popularity).tmdb_id
    for c in candidates[:3]:
        if c.year is not None and abs(c.year - year) <= 1:
            return c.tmdb_id
    return None
```

Add `from movie_brain.domain.models import TmdbCandidate` to `matching.py` imports.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_matching.py tests/unit/test_models.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/domain/models.py src/movie_brain/domain/matching.py tests/unit/test_matching.py
git commit -m "TMDB candidate-pick rules: original-year window, popularity tiebreak"
```

---

### Task 3: Config token + TmdbClient

**Files:**
- Modify: `src/movie_brain/infrastructure/config.py`
- Create: `src/movie_brain/infrastructure/tmdb.py`
- Modify: `src/movie_brain/domain/models.py` (add `TmdbProviders`)
- Test: `tests/unit/test_config.py`, create `tests/unit/test_tmdb.py`

**Interfaces:**
- Consumes: `TmdbCandidate` (Task 2).
- Produces (Task 4 relies on these exactly):
  - `config.TMDB_TOKEN_ENV = "MOVIE_BRAIN_TMDB_TOKEN"`; `Config.tmdb_token_file` property (`<config_dir>/tmdb-read-token.txt`); `load_tmdb_token(config: Config) -> str | None` (env first, then file, `None` if absent/empty).
  - In `domain/models.py`:

```python
@dataclass(frozen=True)
class TmdbProviders:
    """US watch-provider snapshot for one film; payload is the raw response text."""
    flatrate: tuple[int, ...]
    rent: tuple[int, ...]
    buy: tuple[int, ...]
    link: str | None
    payload: str
```

  - In `infrastructure/tmdb.py`: `TMDB_API = "https://api.themoviedb.org/3"`; `class AuthError(Exception)`; `def watch_link(tmdb_id: int) -> str` returning `f"https://www.themoviedb.org/movie/{tmdb_id}/watch?locale=US"`; `class TmdbClient` with `__init__(self, token: str, session: requests.Session | None = None)`, `search(self, title: str) -> list[TmdbCandidate]` (top 10 results), `watch_providers(self, tmdb_id: int) -> TmdbProviders`. 401 → `AuthError`; other HTTP errors → `resp.raise_for_status()`.

- [ ] **Step 1: Write failing tests**

`tests/unit/test_config.py` — append (mirror the file's existing style; the autouse `_isolate_env` fixture already points `MOVIE_BRAIN_CONFIG_DIR` at tmp):

```python
def test_tmdb_token_env_wins(monkeypatch):
    from movie_brain.infrastructure.config import load_config, load_tmdb_token

    monkeypatch.setenv("MOVIE_BRAIN_TMDB_TOKEN", " tok ")
    assert load_tmdb_token(load_config()) == "tok"


def test_tmdb_token_from_file(config_dir):
    from movie_brain.infrastructure.config import load_config, load_tmdb_token

    cfg = load_config()
    assert load_tmdb_token(cfg) is None
    cfg.tmdb_token_file.write_text("filetok\n")
    assert load_tmdb_token(cfg) == "filetok"
```

`tests/unit/test_tmdb.py` — create:

```python
from __future__ import annotations

import pytest
import responses

from movie_brain.infrastructure.tmdb import TMDB_API, AuthError, TmdbClient, watch_link


@pytest.fixture
def rs():
    with responses.RequestsMock() as r:
        yield r


def test_search_parses_top_candidates(rs):
    rs.get(f"{TMDB_API}/search/movie", json={"results": [
        {"id": 11, "title": "Trio", "original_title": "Le Trio", "release_date": "1950-02-01", "popularity": 3.5},
        {"id": 12, "title": "Trio II", "original_title": "Trio II", "release_date": "", "popularity": 1.0},
    ]})
    got = TmdbClient("tok").search("Trio")
    assert [(c.tmdb_id, c.year) for c in got] == [(11, 1950), (12, None)]
    assert got[0].original_title == "Le Trio"
    assert rs.calls[0].request.headers["Authorization"] == "Bearer tok"


def test_search_401_raises_autherror(rs):
    rs.get(f"{TMDB_API}/search/movie", status=401, json={"status_message": "bad token"})
    with pytest.raises(AuthError):
        TmdbClient("tok").search("Trio")


def test_watch_providers_splits_kinds_and_keeps_payload(rs):
    body = {"results": {"US": {"link": "https://tmdb/w/11",
                               "flatrate": [{"provider_id": 1899}, {"provider_id": 258}],
                               "rent": [{"provider_id": 2}], "buy": [{"provider_id": 2}, {"provider_id": 10}]}}}
    rs.get(f"{TMDB_API}/movie/11/watch/providers", json=body)
    got = TmdbClient("tok").watch_providers(11)
    assert got.flatrate == (1899, 258) and got.rent == (2,) and got.buy == (2, 10)
    assert got.link == "https://tmdb/w/11" and '"US"' in got.payload


def test_watch_providers_no_us_region_is_empty(rs):
    rs.get(f"{TMDB_API}/movie/11/watch/providers", json={"results": {"GB": {"flatrate": []}}})
    got = TmdbClient("tok").watch_providers(11)
    assert got.flatrate == () and got.link is None


def test_watch_link():
    assert watch_link(11) == "https://www.themoviedb.org/movie/11/watch?locale=US"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_tmdb.py tests/unit/test_config.py -v`
Expected: FAIL — module `movie_brain.infrastructure.tmdb` and `load_tmdb_token` don't exist.

- [ ] **Step 3: Implement**

`config.py` — add `TMDB_TOKEN_ENV = "MOVIE_BRAIN_TMDB_TOKEN"` beside `API_KEY_ENV`, a `tmdb_token_file` property beside `key_file`, and `load_tmdb_token` mirroring `load_api_key`:

```python
    @property
    def tmdb_token_file(self) -> Path:
        return self.config_dir / "tmdb-read-token.txt"


def load_tmdb_token(config: Config) -> str | None:
    if token := os.environ.get(TMDB_TOKEN_ENV):
        return token.strip()
    if config.tmdb_token_file.exists():
        return config.tmdb_token_file.read_text().strip() or None
    return None
```

`infrastructure/tmdb.py` — create (style-match `omdb.py`):

```python
from __future__ import annotations

import requests

from movie_brain.domain.models import TmdbCandidate, TmdbProviders

TMDB_API = "https://api.themoviedb.org/3"


class AuthError(Exception):
    pass


def watch_link(tmdb_id: int) -> str:
    return f"https://www.themoviedb.org/movie/{tmdb_id}/watch?locale=US"


class TmdbClient:
    def __init__(self, token: str, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.headers = {"Authorization": f"Bearer {token}"}

    def _get(self, path: str, **params: str) -> requests.Response:
        resp = self.session.get(f"{TMDB_API}{path}", params=params, headers=self.headers, timeout=30)
        if resp.status_code == 401:
            raise AuthError(resp.json().get("status_message") or "invalid bearer token")
        resp.raise_for_status()
        return resp

    def search(self, title: str) -> list[TmdbCandidate]:
        results = self._get("/search/movie", query=title, include_adult="false").json().get("results", [])
        out = []
        for r in results[:10]:
            d = r.get("release_date") or ""
            year = int(d[:4]) if len(d) >= 4 and d[:4].isdigit() else None
            out.append(
                TmdbCandidate(
                    int(r["id"]), r.get("title") or "", r.get("original_title") or "",
                    year, float(r.get("popularity") or 0.0),
                )
            )
        return out

    def watch_providers(self, tmdb_id: int) -> TmdbProviders:
        resp = self._get(f"/movie/{tmdb_id}/watch/providers")
        us = resp.json().get("results", {}).get("US", {})

        def ids(kind: str) -> tuple[int, ...]:
            return tuple(int(p["provider_id"]) for p in us.get(kind, []))

        return TmdbProviders(flatrate=ids("flatrate"), rent=ids("rent"), buy=ids("buy"),
                             link=us.get("link"), payload=resp.text)
```

`domain/models.py` — add `TmdbProviders` after `TmdbCandidate`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/infrastructure/config.py src/movie_brain/infrastructure/tmdb.py src/movie_brain/domain/models.py tests/unit/test_config.py tests/unit/test_tmdb.py
git commit -m "TmdbClient (search + US watch providers) and bearer-token config"
```

---

### Task 4: Availability step in sync, CLI counters (BDD)

**Files:**
- Create: `src/movie_brain/application/availability.py`
- Modify: `src/movie_brain/application/sync.py`, `src/movie_brain/cli.py:37-55`
- Create: `tests/features/tmdb.feature`, `tests/step_defs/test_tmdb.py`

**Interfaces:**
- Consumes: Task 1 Repository primitives, Task 2 `pick_tmdb_match`, Task 3 `TmdbClient`/`AuthError`/`watch_link`/`load_tmdb_token`, existing `Repository.record_listing` / `set_external_id` / `replace_unresolved_reviews` / `get_meta` / `set_meta`, `ReviewEntry`.
- Produces:
  - `application/availability.py`: `TMDB_AUTHORITY = "tmdb"`, `STORE_PROVIDER_ID = 2`, `REFRESH_DAYS = 7`, `META_REFRESHED_AT = "tmdb_providers_refreshed_at"`, `MAX_CONSECUTIVE_FAILURES = 5`, `@dataclass(frozen=True) TmdbStepResult(matched: int = 0, missed: int = 0, refreshed: int = 0)`, and `tmdb_step(repo: Repository, client: TmdbClient, today: date, log: Callable[[str], None]) -> TmdbStepResult`.
  - `sync()` gains keyword param `tmdb_token: str | None = None`; `SyncResult` gains trailing fields `tmdb_matched: int = 0`, `tmdb_missed: int = 0`, `tmdb_refreshed: int = 0`.

- [ ] **Step 1: Write the feature file**

`tests/features/tmdb.feature`:

```gherkin
Feature: TMDB availability
  A tripwired sync step: match films to TMDB once, refresh US watch providers weekly
  into listings, and never let a TMDB failure touch the Criterion or OMDb results.

  Background:
    Given a fresh repository
    And the Criterion browse page exposes a token
    And the Criterion catalog has films "Trio (1950)"
    And OMDb knows every film

  Scenario: A new film is matched once and its TMDB id cached
    Given TMDB knows "Trio (1950)" as id 11
    And TMDB streams id 11 on providers 1899 and 258
    When I sync with a TMDB token
    Then "Trio (1950)" has external id "11" for authority "tmdb"
    And the sync matched 1 TMDB films
    When I sync with a TMDB token again the next day
    Then TMDB search was called exactly 1 times

  Scenario: An unmatched film goes to the review queue and is not retried
    Given TMDB has no results for any search
    When I sync with a TMDB token
    Then the tmdb review queue holds 1 entries
    And the exit code is 0
    When I sync with a TMDB token again the next day
    Then TMDB search was called exactly 1 times

  Scenario: Provider refresh writes listings but never the criterion source
    Given TMDB knows "Trio (1950)" as id 11
    And TMDB streams id 11 on providers 1899 and 258
    When I sync with a TMDB token
    Then "Trio (1950)" is currently listed on "max"
    And "Trio (1950)" has 1 non-criterion listings

  Scenario: Provider 2 in buy records an Apple TV Store row, unknown ids are ignored
    Given TMDB knows "Trio (1950)" as id 11
    And TMDB offers id 11 to buy on providers 2 and 1825
    When I sync with a TMDB token
    Then "Trio (1950)" is currently listed on "apple-tv-store"
    And "Trio (1950)" has 1 non-criterion listings

  Scenario: A fresh weekly stamp skips the provider refresh
    Given TMDB knows "Trio (1950)" as id 11
    And TMDB streams id 11 on providers 1899 and 258
    And the provider refresh ran 2 days ago
    When I sync with a TMDB token
    Then TMDB providers were called exactly 0 times

  Scenario: A dropped service goes stale, never deleted
    Given TMDB knows "Trio (1950)" as id 11
    And TMDB streams id 11 on providers 1899 and 258
    When I sync with a TMDB token
    And TMDB stops streaming id 11 anywhere
    And I sync with a TMDB token 8 days later
    Then "Trio (1950)" still has a listing row for "max"

  Scenario: No TMDB token skips the step
    When I sync
    Then the exit code is 0
    And TMDB search was called exactly 0 times

  Scenario: TMDB auth failure leaves the rest of the sync intact
    Given TMDB rejects the token
    When I sync with a TMDB token
    Then the exit code is 0
    And 1 films have OMDb ratings
    And the sync matched 0 TMDB films

  Scenario: Repeated TMDB search failures stop the step and keep the stamp unwritten
    Given the Criterion catalog has films "Trio (1950)" and "Quartet (1948)" and "Third (1960)" and "Fourth (1970)" and "Fifth (1980)" and "Sixth (1990)"
    And TMDB errors on every search
    When I sync with a TMDB token
    Then the exit code is 0
    And the provider refresh stamp is unset
```

- [ ] **Step 2: Write the step definitions**

`tests/step_defs/test_tmdb.py` — reuse the fixtures/step-shapes of `tests/step_defs/test_sync.py` (same `ctx` fixture pattern, `parse_titles`, criterion/OMDb givens). Import the shared givens instead of copying where pytest-bdd allows (`from tests.step_defs.test_sync import ...` is NOT how pytest-bdd shares steps — copy the needed given/when/then functions into this file; they are short):

```python
from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
import responses
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.availability import META_REFRESHED_AT
from movie_brain.application.sync import SOURCE, sync
from movie_brain.infrastructure.criterion import API_URL, BROWSE_URL
from movie_brain.infrastructure.omdb import OMDB_URL
from movie_brain.infrastructure.tmdb import TMDB_API

scenarios("../features/tmdb.feature")

TODAY = date(2026, 8, 19)
FOUND = {"Response": "True", "imdbRating": "7.0", "Language": "English", "Ratings": []}
```

Then copy `parse_titles`, `movie_item`, the `ctx` fixture, and the givens `fresh`, `token`, `catalog` from `test_sync.py` verbatim, plus `@given("OMDb knows every film")` (in `test_sync.py` — copy it too). New TMDB steps:

```python
@pytest.fixture
def tmdb(ctx):
    """One mutable TMDB world: search index, per-id providers, call counters."""
    world = {"search": {}, "providers": {}, "search_calls": 0, "provider_calls": 0,
             "search_mode": "index", "reject": False}

    def do_search(request):
        world["search_calls"] += 1
        if world["reject"]:
            return (401, {}, json.dumps({"status_message": "bad token"}))
        if world["search_mode"] == "error":
            return (500, {}, "boom")
        title = parse_qs(urlparse(request.url).query)["query"][0]
        hit = world["search"].get(title)
        results = [hit] if hit else []
        return (200, {}, json.dumps({"results": results}))

    ctx["rs"].add_callback(responses.GET, f"{TMDB_API}/search/movie", callback=do_search)

    def provider_callback(tmdb_id):
        def cb(request):
            world["provider_calls"] += 1
            return (200, {}, json.dumps({"results": {"US": world["providers"].get(tmdb_id, {})}}))
        return cb

    world["register_providers"] = lambda tid: ctx["rs"].add_callback(
        responses.GET, f"{TMDB_API}/movie/{tid}/watch/providers", callback=provider_callback(tid))
    return world


@given(parsers.parse('TMDB knows "{title} ({year:d})" as id {tid:d}'))
def tmdb_knows(tmdb, title, year, tid):
    tmdb["search"][title] = {"id": tid, "title": title, "original_title": title,
                            "release_date": f"{year}-01-01", "popularity": 5.0}
    tmdb["register_providers"](tid)


@given(parsers.parse("TMDB streams id {tid:d} on providers {a:d} and {b:d}"))
def tmdb_streams(tmdb, tid, a, b):
    tmdb["providers"][tid] = {"link": f"https://tmdb/w/{tid}",
                              "flatrate": [{"provider_id": a}, {"provider_id": b}]}


@given(parsers.parse("TMDB offers id {tid:d} to buy on providers {a:d} and {b:d}"))
def tmdb_buys(tmdb, tid, a, b):
    tmdb["providers"][tid] = {"link": f"https://tmdb/w/{tid}",
                              "buy": [{"provider_id": a}, {"provider_id": b}]}


@given("TMDB has no results for any search")
def tmdb_empty(tmdb):
    pass  # empty search index → every search returns no results


@given("TMDB rejects the token")
def tmdb_reject(tmdb):
    tmdb["reject"] = True


@given("TMDB errors on every search")
def tmdb_errors(tmdb):
    tmdb["search_mode"] = "error"


@given(parsers.parse("the provider refresh ran {days:d} days ago"))
def stamp(ctx, days):
    ctx["repo"].set_meta(META_REFRESHED_AT, (TODAY - timedelta(days=days)).isoformat())


@when("TMDB stops streaming id 11 anywhere")
def tmdb_stops(tmdb):
    tmdb["providers"][11] = {}


@when("I sync")
def do_sync(ctx, tmdb):
    ctx["result"] = sync(ctx["repo"], "omdb-key", TODAY)


@when("I sync with a TMDB token")
def do_sync_tok(ctx, tmdb):
    ctx["result"] = sync(ctx["repo"], "omdb-key", TODAY, tmdb_token="tok")


@when("I sync with a TMDB token again the next day")
def do_sync_next(ctx, tmdb):
    ctx["result"] = sync(ctx["repo"], "omdb-key", TODAY + timedelta(days=1), tmdb_token="tok")


@when("I sync with a TMDB token 8 days later")
def do_sync_later(ctx, tmdb):
    ctx["result"] = sync(ctx["repo"], "omdb-key", TODAY + timedelta(days=8), tmdb_token="tok")


@then(parsers.parse("the exit code is {code:d}"))
def exit_code(ctx, code):
    assert ctx["result"].exit_code == code


@then(parsers.parse("{n:d} films have OMDb ratings"))
def omdb_count(ctx, n):
    with sqlite3.connect(ctx["repo"].db_path) as c:
        assert c.execute("SELECT COUNT(*) FROM omdb WHERE found = 1").fetchone()[0] == n


@then(parsers.parse('"{title} ({year:d})" has external id "{value}" for authority "{authority}"'))
def has_external(ctx, title, year, value, authority):
    fid = ctx["repo"].film_id_by_key(f"{title.lower()} ({year})")
    assert ctx["repo"].external_ids_for(fid).get(authority) == value


@then(parsers.parse("the sync matched {n:d} TMDB films"))
def matched_n(ctx, n):
    assert ctx["result"].tmdb_matched == n


@then(parsers.parse("TMDB search was called exactly {n:d} times"))
def search_calls(tmdb, n):
    assert tmdb["search_calls"] == n


@then(parsers.parse("TMDB providers were called exactly {n:d} times"))
def provider_calls(tmdb, n):
    assert tmdb["provider_calls"] == n


@then(parsers.parse("the tmdb review queue holds {n:d} entries"))
def review_n(ctx, n):
    assert len(ctx["repo"].open_reviews("tmdb")) == n


@then(parsers.parse('"{title} ({year:d})" is currently listed on "{slug}"'))
def currently_listed(ctx, title, year, slug):
    fid = ctx["repo"].film_id_by_key(f"{title.lower()} ({year})")
    assert fid in {i for i, _ in ctx["repo"].current_films(slug)}


@then(parsers.parse('"{title} ({year:d})" has {n:d} non-criterion listings'))
def listing_count(ctx, title, year, n):
    fid = ctx["repo"].film_id_by_key(f"{title.lower()} ({year})")
    with sqlite3.connect(ctx["repo"].db_path) as c:
        got = c.execute(
            "SELECT COUNT(*) FROM listings WHERE film_id = ? AND source != 'criterion'", (fid,)
        ).fetchone()[0]
    assert got == n


@then(parsers.parse('"{title} ({year:d})" still has a listing row for "{slug}"'))
def listing_survives(ctx, title, year, slug):
    fid = ctx["repo"].film_id_by_key(f"{title.lower()} ({year})")
    with sqlite3.connect(ctx["repo"].db_path) as c:
        assert c.execute(
            "SELECT 1 FROM listings WHERE film_id = ? AND source = ?", (fid, slug)
        ).fetchone() is not None


@then("the provider refresh stamp is unset")
def stamp_unset(ctx):
    assert ctx["repo"].get_meta(META_REFRESHED_AT) is None
```

Two wiring notes for the implementer: (1) every `When I sync…` step takes the `tmdb` fixture so the callbacks are registered even in the no-token scenario; (2) the second sync in re-run scenarios hits the Criterion cheap check (walked yesterday, page 1 unchanged) — the copied `catalog` given serves both walks, so no extra mocks are needed. In the "8 days later" scenario the Criterion walk is full again; that's fine.

- [ ] **Step 3: Run the feature to verify it fails**

Run: `uv run pytest tests/step_defs/test_tmdb.py -v`
Expected: FAIL — `movie_brain.application.availability` does not exist; `sync()` has no `tmdb_token` param.

- [ ] **Step 4: Implement `application/availability.py`**

```python
from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import requests

from movie_brain.domain.matching import pick_tmdb_match
from movie_brain.domain.models import ReviewEntry
from movie_brain.infrastructure.database import Repository
from movie_brain.infrastructure.tmdb import AuthError, TmdbClient, watch_link

TMDB_AUTHORITY = "tmdb"
STORE_PROVIDER_ID = 2  # Apple TV Store (iTunes) — the only rent/buy id we record
REFRESH_DAYS = 7
META_REFRESHED_AT = "tmdb_providers_refreshed_at"
MAX_CONSECUTIVE_FAILURES = 5


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


@dataclass(frozen=True)
class TmdbStepResult:
    matched: int = 0
    missed: int = 0
    refreshed: int = 0


def tmdb_step(
    repo: Repository, client: TmdbClient, today: date, log: Callable[[str], None] = _stderr
) -> TmdbStepResult:
    matched = missed = refreshed = 0
    consecutive = 0
    aborted = False
    for film_id, title, year in repo.films_needing_tmdb_match():
        if consecutive >= MAX_CONSECUTIVE_FAILURES:
            log("TMDB searches failing repeatedly — stopping; next run resumes.")
            aborted = True
            break
        try:
            candidates = client.search(title)
        except AuthError as exc:
            log(f"TMDB rejected the token: {exc}")
            return TmdbStepResult(matched, missed, refreshed)
        except requests.RequestException as exc:
            log(f"TMDB search failed for {title!r}: {exc}")
            consecutive += 1
            continue
        consecutive = 0
        winner = pick_tmdb_match(title, year, candidates)
        if winner is None:
            repo.upsert_tmdb(film_id, found=False, looked_up=today)
            missed += 1
        else:
            repo.set_external_id(film_id, TMDB_AUTHORITY, str(winner), today)
            repo.upsert_tmdb(film_id, found=True, looked_up=today)
            matched += 1

    # Recomputed from found=0 rows each run, so a tripwired match pass never loses entries.
    repo.replace_unresolved_reviews(
        TMDB_AUTHORITY,
        [ReviewEntry("no-match", film_id=fid, detail=f"{t} ({y})") for fid, t, y in repo.films_tmdb_missed()],
        today,
    )

    # A tripwired match pass means TMDB is unhealthy right now — don't start (or stamp) a
    # refresh pass that would then gate for a week having refreshed nothing.
    if aborted:
        return TmdbStepResult(matched, missed, refreshed)
    stamp = repo.get_meta(META_REFRESHED_AT)
    if stamp is not None and 0 <= (today - date.fromisoformat(stamp)).days <= REFRESH_DAYS:
        return TmdbStepResult(matched, missed, refreshed)
    pmap = repo.provider_map()
    consecutive = 0
    for film_id, tmdb_id in repo.films_for_provider_refresh():
        if consecutive >= MAX_CONSECUTIVE_FAILURES:
            log("TMDB provider lookups failing repeatedly — stopping; next run resumes.")
            return TmdbStepResult(matched, missed, refreshed)
        try:
            providers = client.watch_providers(int(tmdb_id))
        except AuthError as exc:
            log(f"TMDB rejected the token: {exc}")
            return TmdbStepResult(matched, missed, refreshed)
        except requests.RequestException as exc:
            log(f"TMDB providers failed for film {film_id}: {exc}")
            consecutive += 1
            continue
        consecutive = 0
        slugs = {pmap[p] for p in providers.flatrate if p in pmap and pmap[p] != "criterion"}
        if STORE_PROVIDER_ID in (*providers.rent, *providers.buy):
            slugs.add(pmap[STORE_PROVIDER_ID])
        url = providers.link or watch_link(int(tmdb_id))
        for slug in sorted(slugs):
            repo.record_listing(film_id, slug, url, today)
        repo.record_tmdb_providers(film_id, today, providers.payload)
        refreshed += 1
    repo.set_meta(META_REFRESHED_AT, today.isoformat())
    return TmdbStepResult(matched, missed, refreshed)
```

- [ ] **Step 5: Wire into `sync.py` and the CLI**

`sync.py`: add `tmdb_token: str | None = None` keyword param; add trailing `SyncResult` fields `tmdb_matched: int = 0`, `tmdb_missed: int = 0`, `tmdb_refreshed: int = 0`; after the OMDb loop (before building the final result):

```python
    tmdb = TmdbStepResult()
    if tmdb_token is None:
        log("no TMDB token — skipping availability step")
    else:
        try:
            tmdb = tmdb_step(repo, TmdbClient(tmdb_token, session=session), today, log=log)
        except Exception as exc:  # noqa: BLE001 — one source failing must never break the others
            log(f"TMDB availability step failed: {exc}")
```

and extend the final return: `SyncResult(0, full_walk, len(repo.current_films(SOURCE)), looked_up, quota_hit, failing, tmdb.matched, tmdb.missed, tmdb.refreshed)`. Imports: `from movie_brain.application.availability import TmdbStepResult, tmdb_step` and `from movie_brain.infrastructure.tmdb import TmdbClient`.

`cli.py` `sync_cmd`: `from movie_brain.infrastructure.config import load_api_key, load_config, load_tmdb_token`; pass `tmdb_token=load_tmdb_token(cfg)` to `sync(...)`; extend the summary print to
`f"films: {result.films} · looked up: {result.looked_up} · full walk: {result.full_walk} · tmdb matched: {result.tmdb_matched} · availability refreshed: {result.tmdb_refreshed}"`.

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest && uv run ruff check . && uv run mypy`
Expected: all green — existing sync scenarios pass unchanged (no token → step skipped).

- [ ] **Step 7: Commit**

```bash
git add src/movie_brain/application/availability.py src/movie_brain/application/sync.py src/movie_brain/cli.py tests/features/tmdb.feature tests/step_defs/test_tmdb.py
git commit -m "TMDB availability step: one-shot match, weekly provider refresh, own tripwires"
```

---

### Task 5: Services in the film payload + drawer line

**Files:**
- Modify: `src/movie_brain/infrastructure/database.py` (`_VIEW_SQL` area: `_row_to_view`, `list_views`, `get_view`; new `_SERVICES_SQL` + helper)
- Modify: `src/movie_brain/domain/models.py` (`FilmView`)
- Modify: `src/movie_brain/web/static/app.js` (`detailHtml`, `app.js:289-305`)
- Modify: `tests/web/conftest.py` (`seed`)
- Test: `tests/web/test_api.py`, `tests/web/test_dashboard.py`

**Interfaces:**
- Consumes: `listings` rows written by Task 4; `movie_service` registry.
- Produces: `FilmView.services: list[dict[str, object]]` (default `[]`), each entry `{"name": str, "subscribed": bool}`, current non-criterion svod listings, subscribed first then by name. Store-kind rows excluded. Served by both `/api/films` and `/api/films/<id>`.

- [ ] **Step 1: Write failing API tests**

Append to `tests/web/test_api.py`:

```python
def test_services_in_payloads(repo):
    films = [Film("Trio", 1950, "Ken", "https://c/trio")]
    repo.record_catalog("criterion", films, D)
    fid = repo.film_id_by_key("trio (1950)")
    for slug in ("max", "mubi", "apple-tv-store"):
        repo.record_listing(fid, slug, "https://tmdb/w/11", D)
    app = create_app(repo, today=lambda: D)
    app.testing = True
    tc = app.test_client()
    expected = [{"name": "HBO Max", "subscribed": True}, {"name": "MUBI", "subscribed": False}]
    assert tc.get(f"/api/films/{fid}").get_json()["services"] == expected  # store row hidden
    assert tc.get("/api/films").get_json()[0]["services"] == expected


def test_stale_service_listing_is_not_current(repo):
    films = [Film("Trio", 1950, "Ken", "https://c/trio"), Film("Quartet", 1948, None, "https://c/quartet")]
    repo.record_catalog("criterion", films, D)
    trio, quartet = repo.film_id_by_key("trio (1950)"), repo.film_id_by_key("quartet (1948)")
    repo.record_listing(trio, "max", "https://tmdb/w/11", date(2026, 1, 1))  # stale
    repo.record_listing(quartet, "max", "https://tmdb/w/22", D)  # current — defines max's frontier
    app = create_app(repo, today=lambda: D)
    app.testing = True
    body = {v["title"]: v["services"] for v in app.test_client().get("/api/films").get_json()}
    assert body["Trio"] == [] and body["Quartet"] == [{"name": "HBO Max", "subscribed": True}]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/web/test_api.py -k services -v`
Expected: FAIL — `KeyError: 'services'`.

- [ ] **Step 3: Implement**

`domain/models.py`: `from dataclasses import ..., field`; add to `FilmView` (after `metacritic_url`):

```python
    services: list[dict[str, object]] = field(default_factory=list)
```

`database.py`: add beside `_VIEW_SQL`:

```python
_SERVICES_SQL = """
SELECT l.film_id, s.name, s.subscribed FROM listings l
JOIN movie_service s ON s.slug = l.source
WHERE s.kind = 'svod' AND l.source != 'criterion'
  AND l.last_seen = (SELECT MAX(last_seen) FROM listings WHERE source = l.source)
ORDER BY l.film_id, s.subscribed DESC, s.name
"""


def _services_by_film(c: sqlite3.Connection) -> dict[int, list[dict[str, object]]]:
    out: dict[int, list[dict[str, object]]] = {}
    for r in c.execute(_SERVICES_SQL):
        out.setdefault(int(r["film_id"]), []).append({"name": str(r["name"]), "subscribed": bool(r["subscribed"])})
    return out
```

Change `_row_to_view(row)` → `_row_to_view(row, services=None)` passing `services=services or []` into `FilmView`; in `list_views` compute `services = _services_by_film(c)` once and call `_row_to_view(r, services.get(r["id"]))`; in `get_view` likewise (`_services_by_film(c).get(row["id"])`).

`app.js` `detailHtml`: before the `<details>` line add:

```js
    const streaming = (d.services || [])
      .map((s) => s.subscribed ? esc(s.name) : `${esc(s.name)} (not subscribed)`).join(', ');
```

and inject `${streaming ? `<p class="meta">Also streaming on: ${streaming}</p>` : ''}` between the ratings `</p>` paragraph and the `<details>` element.

- [ ] **Step 4: Seed and test the drawer (Playwright)**

`tests/web/conftest.py` `seed()`, after the `set_rating` lines:

```python
    # Alpha also streams on Max (subscribed) and MUBI (not) — the drawer's "Also streaming on" line.
    repo.record_listing(ids["alpha (1950)"], "max", "https://tmdb/w/1", TODAY)
    repo.record_listing(ids["alpha (1950)"], "mubi", "https://tmdb/w/1", TODAY)
    repo.record_listing(ids["alpha (1950)"], "apple-tv-store", "https://tmdb/w/1", TODAY)
```

Append to `tests/web/test_dashboard.py` (mirror the file's existing drawer-opening test for the exact open gesture — row click on the title cell — and its `expect` import):

```python
def test_drawer_shows_also_streaming(dash):
    dash.locator("tbody tr", has_text="Alpha").first.click()
    expect(dash.locator("#drawer-body")).to_contain_text("Also streaming on: HBO Max, MUBI (not subscribed)")


def test_drawer_without_services_hides_the_line(dash):
    dash.locator("tbody tr", has_text="Bravo").first.click()
    expect(dash.locator("#drawer-body")).not_to_contain_text("Also streaming on")
```

- [ ] **Step 5: Run web tests**

Run: `uv run pytest tests/web -v`
Expected: PASS (existing dashboard tests must stay green — the seed adds no criterion rows, so counts are unchanged).

- [ ] **Step 6: Commit**

```bash
git add src/movie_brain/domain/models.py src/movie_brain/infrastructure/database.py src/movie_brain/web/static/app.js tests/web/conftest.py tests/web/test_api.py tests/web/test_dashboard.py
git commit -m "Drawer shows cross-service availability: services join in the film payload"
```

---

### Task 6: Docs + final verification

**Files:**
- Modify: `CLAUDE.md`, `docs/multiple-movie-services.md`

**Interfaces:** none — documentation and the completion gate.

- [ ] **Step 1: Update CLAUDE.md**

- Commands block: add `# nightly sync now also matches films to TMDB and refreshes weekly availability` note to the sync line (keep it one line).
- Architecture bullet for `infrastructure/` — add `tmdb.py` (watch-providers adapter) alongside `omdb.py`.
- Sync flow: add step 5: "TMDB step (token at `<config_dir>/tmdb-read-token.txt`, else skipped): one-shot match of new films (misses → `match_review`, never retried by sync), then a weekly full US watch-providers refresh writing `listings` rows per service (never `criterion`); own tripwires — TMDB failures never affect exit code or other steps."
- Rules: add "Availability lives in `listings`: TMDB writes svod sources from `flatrate` only (plus `apple-tv-store` from rent/buy provider 2); Amazon-channel ids are excluded; the weekly refresh is gated by meta `tmdb_providers_refreshed_at`."
- Data section: add the token file path.

- [ ] **Step 2: Mark Phase 3 done in the roadmap**

In `docs/multiple-movie-services.md`: phase table row 3 → `TMDB availability adapter — **done**`; numbered item 3 gains `**Done (<today's date>).**` prefix and a one-line summary of what landed (mirror how phases 1–2 are marked).

- [ ] **Step 3: Full verification**

Run: `uv run pytest && uv run ruff check . && uv run mypy`
Expected: everything green. Then a live smoke test against a COPY of the real DB:

```bash
cp ~/.config/movie-brain/movie-brain.db /tmp/p3-smoke/movie-brain.db  # after mkdir -p /tmp/p3-smoke
cp ~/.config/movie-brain/*.txt /tmp/p3-smoke/ 2>/dev/null || true
MOVIE_BRAIN_CONFIG_DIR=/tmp/p3-smoke uv run movie-brain sync 2>&1 | tail -5
```

Expected: sync completes; tmdb matched count > 0; no exceptions. (First live run does ~3,000 searches + ~3,000 provider calls — several minutes; that's the known one-time cost. Do NOT run against the real config dir from the worktree.)

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md docs/multiple-movie-services.md
git commit -m "Docs: Phase 3 (TMDB availability) landed"
```

Then follow superpowers:finishing-a-development-branch (merge to main, delete worktree).
