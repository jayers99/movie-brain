# movie-brain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `movie-brain`, a SQLite-backed successor to criterion-ratings with a Flask dashboard (stacking canned filters, column filters, sort, detail drawer, inline rating entry), a daily `sync`, and a one-shot legacy import.

**Architecture:** Hexagonal, mirroring yt-brain: `domain/` (pure models + filter predicates), `application/` (sync, ratings, export, legacy import), `infrastructure/` (config, SQLite repository, Criterion + OMDb HTTP adapters), `web/` (Flask app serving one page + JSON API; all filter/sort happens client-side in vanilla JS), `cli.py` (Typer). Criterion-ratings code is **ported** (copied + adapted), not imported.

**Tech Stack:** Python ≥3.12, uv, Typer + Rich, Flask, sqlite3 stdlib, requests, pytest + pytest-bdd + `responses` + pytest-playwright, ruff + mypy strict, hatchling, MIT.

**Spec:** `docs/superpowers/specs/2026-08-19-movie-brain-design.md`

## Global Constraints

- Repo root: `~/code/movie-brain` (already `git init`ed with the spec committed). Package: `src/movie_brain/`, script name `movie-brain`.
- Python `>=3.12`; `uv` with in-project `.venv/`; run everything as `uv run …`. Never bare `python`/`pytest`.
- Config dir: `~/.config/movie-brain/` overridable via env `MOVIE_BRAIN_CONFIG_DIR`. DB file: `<config_dir>/movie-brain.db`. OMDb key: env `OMDB_API_KEY` or `<config_dir>/omdb-api-key.txt`.
- Film identity key: `f"{title.strip().lower()} ({year})"` — identical to legacy (year `None` renders as `None`).
- `my_ratings.score` is an int 0–10; `0` = not interested; absent row = unrated.
- Canned filter thresholds: Top RT ≥ 90, Top IMDb ≥ 8.0, Recently added = `first_seen` within last 30 days. These constants live in `domain/filters.py` and are served to JS via `GET /api/config` — never hard-coded in JS.
- Only source for now: `'criterion'`. Nothing in `listings` is ever deleted.
- Markdown report is **not** ported. CSV export is.
- Dependency direction: `web`/`cli` → `application` → `domain`; `infrastructure` implements what `application` needs; `domain` imports nothing from other layers.
- Domain models use stdlib `dataclasses` (the spec's "pydantic/dataclasses" — pydantic adds nothing here; YAGNI).
- Dashboard default port `5556`. launchd label `com.jayers.movie-brain`, 03:00 daily, logs to `<config_dir>/sync.log`.
- Commit after every task (brief single-line messages focused on why). Lint/type-check before committing: `uv run ruff check . && uv run ruff format --check . && uv run mypy`.

---

## File Structure

| Path | Responsibility |
|---|---|
| `pyproject.toml`, `.gitignore`, `.pre-commit-config.yaml`, `README.md`, `CLAUDE.md`, `LICENSE` | project scaffolding |
| `migrations/001_init.sql` | schema (films, listings, omdb, my_ratings, meta, schema_version) |
| `src/movie_brain/domain/models.py` | `film_key`, `Film`, `OmdbRating`, `FilmView` |
| `src/movie_brain/domain/filters.py` | canned-filter constants + predicates |
| `src/movie_brain/infrastructure/config.py` | `Config`, `load_config`, `load_api_key` |
| `src/movie_brain/infrastructure/database.py` | `init_db`, `Repository` |
| `src/movie_brain/infrastructure/criterion.py` | Criterion/VHX HTTP adapter |
| `src/movie_brain/infrastructure/omdb.py` | OMDb HTTP adapter |
| `src/movie_brain/application/sync.py` | catalog walk + OMDb fill orchestration |
| `src/movie_brain/application/legacy_import.py` | import from criterion-ratings JSON |
| `src/movie_brain/application/ratings.py` | `rate_film` |
| `src/movie_brain/application/export.py` | `write_csv` |
| `src/movie_brain/cli.py` | Typer commands |
| `src/movie_brain/web/app.py` | `create_app`, routes, JSON API |
| `src/movie_brain/web/templates/index.html` | page shell |
| `src/movie_brain/web/static/app.js`, `app.css` | table, filters, sort, drawer, rating input |
| `launchd/com.jayers.movie-brain.plist.template`, `scripts/install-launch-agent.sh` | scheduling |
| `tests/conftest.py` | shared fixtures (`config_dir`, `repo`, `today`) |
| `tests/unit/test_*.py` | domain, config, repository, adapters |
| `tests/features/*.feature` + `tests/step_defs/test_*.py` | BDD for application services |
| `tests/web/conftest.py`, `tests/web/test_api.py`, `tests/web/test_dashboard.py` | Flask client + Playwright |

---

### Task 1: Project scaffold + config

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.pre-commit-config.yaml`, `LICENSE`, `src/movie_brain/__init__.py`, `src/movie_brain/{domain,application,infrastructure,web}/__init__.py`, `src/movie_brain/infrastructure/config.py`, `tests/conftest.py`, `tests/unit/test_config.py`

**Interfaces:**
- Produces: `Config(config_dir: Path)` with `.db_path`, `.key_file`; `load_config() -> Config`; `load_api_key(config: Config) -> str | None`.

- [ ] **Step 1: Write pyproject.toml**

```toml
[project]
name = "movie-brain"
version = "0.1.0"
description = "Personal film brain — Criterion listings, OMDb ratings, my ratings, in SQLite with a local dashboard"
readme = "README.md"
license = { text = "MIT" }
requires-python = ">=3.12"
dependencies = [
    "typer>=0.15.1",
    "rich>=13.9.4",
    "flask>=3.1.3",
    "requests>=2.32",
]

[project.scripts]
movie-brain = "movie_brain.cli:app"

[dependency-groups]
dev = [
    "pytest>=8.3.4",
    "pytest-bdd>=8.1.0",
    "responses>=0.25",
    "pytest-playwright>=0.7.2",
    "ruff>=0.8.4",
    "mypy>=1.14.1",
    "types-requests>=2.32",
    "pre-commit>=4.5.1",
]

[tool.ruff]
line-length = 120
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.ruff.lint.per-file-ignores]
"tests/*" = ["E501"]

[tool.mypy]
python_version = "3.12"
strict = true
files = ["src"]

[[tool.mypy.overrides]]
module = ["responses", "responses.*"]
ignore_missing_imports = true

[tool.pytest.ini_options]
testpaths = ["tests"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/movie_brain"]
```

- [ ] **Step 2: .gitignore, LICENSE, pre-commit, package inits**

`.gitignore`:
```
.venv/
__pycache__/
*.pyc
.pytest_cache/
.mypy_cache/
.ruff_cache/
dist/
*.egg-info/
.playwright/
```
`LICENSE`: MIT, copyright 2026 John Ayers (standard text).
`.pre-commit-config.yaml`:
```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.9.10
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
```
Create empty `src/movie_brain/__init__.py` and `__init__.py` in `domain/`, `application/`, `infrastructure/`, `web/`. Create `README.md` with just `# movie-brain` for now (filled in Task 13).

- [ ] **Step 3: Write the failing config test** — `tests/unit/test_config.py`

```python
from pathlib import Path

from movie_brain.infrastructure.config import Config, load_api_key, load_config


def test_load_config_uses_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("MOVIE_BRAIN_CONFIG_DIR", str(tmp_path))
    cfg = load_config()
    assert cfg.config_dir == tmp_path
    assert cfg.db_path == tmp_path / "movie-brain.db"


def test_load_config_defaults_to_home(monkeypatch):
    monkeypatch.delenv("MOVIE_BRAIN_CONFIG_DIR", raising=False)
    assert load_config().config_dir == Path.home() / ".config" / "movie-brain"


def test_api_key_prefers_env(monkeypatch, tmp_path):
    monkeypatch.setenv("OMDB_API_KEY", " envkey ")
    (tmp_path / "omdb-api-key.txt").write_text("filekey\n")
    assert load_api_key(Config(tmp_path)) == "envkey"


def test_api_key_falls_back_to_file(monkeypatch, tmp_path):
    monkeypatch.delenv("OMDB_API_KEY", raising=False)
    (tmp_path / "omdb-api-key.txt").write_text("filekey\n")
    assert load_api_key(Config(tmp_path)) == "filekey"


def test_api_key_missing_is_none(monkeypatch, tmp_path):
    monkeypatch.delenv("OMDB_API_KEY", raising=False)
    assert load_api_key(Config(tmp_path)) is None
```

`tests/conftest.py`:
```python
from datetime import date
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MOVIE_BRAIN_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.delenv("OMDB_API_KEY", raising=False)


@pytest.fixture
def config_dir(tmp_path) -> Path:
    d = tmp_path / "cfg"
    d.mkdir(exist_ok=True)
    return d


@pytest.fixture
def today() -> date:
    return date(2026, 8, 19)
```

- [ ] **Step 4: Run, expect ImportError**

`cd ~/code/movie-brain && uv sync && uv run pytest tests/unit/test_config.py -v` → FAIL (`ModuleNotFoundError: movie_brain.infrastructure.config`).

- [ ] **Step 5: Implement `infrastructure/config.py`**

```python
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "movie-brain"
CONFIG_DIR_ENV = "MOVIE_BRAIN_CONFIG_DIR"
API_KEY_ENV = "OMDB_API_KEY"


@dataclass(frozen=True)
class Config:
    config_dir: Path

    @property
    def db_path(self) -> Path:
        return self.config_dir / "movie-brain.db"

    @property
    def key_file(self) -> Path:
        return self.config_dir / "omdb-api-key.txt"


def load_config() -> Config:
    env = os.environ.get(CONFIG_DIR_ENV)
    return Config(Path(env) if env else DEFAULT_CONFIG_DIR)


def load_api_key(config: Config) -> str | None:
    if key := os.environ.get(API_KEY_ENV):
        return key.strip()
    if config.key_file.exists():
        return config.key_file.read_text().strip() or None
    return None
```

- [ ] **Step 6: Run tests + lint → PASS**

`uv run pytest tests/unit/test_config.py -v && uv run ruff check . && uv run mypy`

- [ ] **Step 7: Commit**

`git add -A && git commit -m "Scaffold movie-brain with config loading"`

---

### Task 2: Domain models + canned-filter predicates

**Files:**
- Create: `src/movie_brain/domain/models.py`, `src/movie_brain/domain/filters.py`, `tests/unit/test_models.py`, `tests/unit/test_filters.py`

**Interfaces:**
- Produces:
  - `film_key(title: str, year: int | None) -> str`
  - `Film(title, year, director, url)` frozen dataclass, `.key` property
  - `OmdbRating(imdb: float|None, rt: int|None, found: bool, language: str|None=None, payload: str|None=None)`
  - `FilmView(id:int, title, year, director, url, language, imdb, rt, found: bool|None, pending: bool, leaving_date: str|None, first_seen: str|None, my_rating: int|None)` with `.to_dict() -> dict[str, object]`
  - `filters.TOP_RT = 90`, `TOP_IMDB = 8.0`, `RECENT_DAYS = 30`, `CHIPS: tuple[str, ...]`, `matches(view: FilmView, chips: Iterable[str], today: date) -> bool`, `thresholds() -> dict[str, object]`

- [ ] **Step 1: Failing tests**

`tests/unit/test_models.py`:
```python
from movie_brain.domain.models import Film, FilmView, film_key


def test_film_key_matches_legacy_scheme():
    assert film_key("  Seven Samurai ", 1954) == "seven samurai (1954)"
    assert film_key("God is Good", None) == "god is good (None)"


def test_film_key_property():
    assert Film("Trio", 1950, "Ken Annakin", "https://c/trio").key == "trio (1950)"


def test_film_view_to_dict_round_trips_fields():
    v = FilmView(1, "Trio", 1950, "Ken Annakin", "https://c/trio", "English", 7.1, 90, True, False, None, "2026-08-01", 8)
    d = v.to_dict()
    assert d["id"] == 1 and d["imdb"] == 7.1 and d["my_rating"] == 8 and d["pending"] is False
```

`tests/unit/test_filters.py`:
```python
from datetime import date

import pytest

from movie_brain.domain.filters import CHIPS, RECENT_DAYS, TOP_IMDB, TOP_RT, matches, thresholds
from movie_brain.domain.models import FilmView

TODAY = date(2026, 8, 19)


def view(**kw) -> FilmView:
    base = dict(id=1, title="T", year=2000, director="D", url="u", language="English", imdb=7.0, rt=80,
                found=True, pending=False, leaving_date=None, first_seen="2026-01-01", my_rating=None)
    base.update(kw)
    return FilmView(**base)


def test_chip_names_are_stable():
    assert CHIPS == ("leaving", "unrated", "mine", "not_interested", "pending", "top_rt", "top_imdb", "recent")


@pytest.mark.parametrize("chip,yes,no", [
    ("leaving", view(leaving_date="Aug 31"), view()),
    ("unrated", view(my_rating=None), view(my_rating=0)),
    ("mine", view(my_rating=1), view(my_rating=0)),
    ("not_interested", view(my_rating=0), view(my_rating=5)),
    ("pending", view(pending=True, found=None), view()),
    ("pending", view(found=False), view()),
    ("top_rt", view(rt=TOP_RT), view(rt=TOP_RT - 1)),
    ("top_imdb", view(imdb=TOP_IMDB), view(imdb=7.9)),
    ("recent", view(first_seen="2026-08-01"), view(first_seen="2026-01-01")),
])
def test_single_chip(chip, yes, no):
    assert matches(yes, [chip], TODAY)
    assert not matches(no, [chip], TODAY)


def test_null_ratings_never_match_top_chips():
    assert not matches(view(rt=None), ["top_rt"], TODAY)
    assert not matches(view(imdb=None), ["top_imdb"], TODAY)


def test_chips_stack_with_and():
    v = view(leaving_date="Aug 31", my_rating=None)
    assert matches(v, ["leaving", "unrated"], TODAY)
    assert not matches(v, ["leaving", "mine"], TODAY)


def test_no_chips_matches_everything():
    assert matches(view(), [], TODAY)


def test_unknown_chip_raises():
    with pytest.raises(KeyError):
        matches(view(), ["bogus"], TODAY)


def test_thresholds_exposes_constants():
    assert thresholds() == {"top_rt": TOP_RT, "top_imdb": TOP_IMDB, "recent_days": RECENT_DAYS}
```

- [ ] **Step 2: Run → FAIL** `uv run pytest tests/unit/test_models.py tests/unit/test_filters.py -q`

- [ ] **Step 3: Implement `domain/models.py`**

```python
from __future__ import annotations

from dataclasses import asdict, dataclass


def film_key(title: str, year: int | None) -> str:
    return f"{title.strip().lower()} ({year})"


@dataclass(frozen=True)
class Film:
    title: str
    year: int | None
    director: str | None
    url: str

    @property
    def key(self) -> str:
        return film_key(self.title, self.year)


@dataclass(frozen=True)
class OmdbRating:
    imdb: float | None
    rt: int | None
    found: bool
    language: str | None = None
    payload: str | None = None  # raw OMDb JSON text; None when not found


@dataclass(frozen=True)
class FilmView:
    id: int
    title: str
    year: int | None
    director: str | None
    url: str
    language: str | None
    imdb: float | None
    rt: int | None
    found: bool | None  # None = no OMDb row yet
    pending: bool
    leaving_date: str | None
    first_seen: str | None
    my_rating: int | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
```

- [ ] **Step 4: Implement `domain/filters.py`**

```python
from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date, timedelta

from .models import FilmView

TOP_RT = 90
TOP_IMDB = 8.0
RECENT_DAYS = 30

Predicate = Callable[[FilmView, date], bool]


def _recent(v: FilmView, today: date) -> bool:
    return v.first_seen is not None and date.fromisoformat(v.first_seen) >= today - timedelta(days=RECENT_DAYS)


_PREDICATES: dict[str, Predicate] = {
    "leaving": lambda v, _: v.leaving_date is not None,
    "unrated": lambda v, _: v.my_rating is None,
    "mine": lambda v, _: v.my_rating is not None and v.my_rating >= 1,
    "not_interested": lambda v, _: v.my_rating == 0,
    "pending": lambda v, _: v.pending or v.found is False,
    "top_rt": lambda v, _: v.rt is not None and v.rt >= TOP_RT,
    "top_imdb": lambda v, _: v.imdb is not None and v.imdb >= TOP_IMDB,
    "recent": _recent,
}

CHIPS: tuple[str, ...] = tuple(_PREDICATES)


def matches(view: FilmView, chips: Iterable[str], today: date) -> bool:
    return all(_PREDICATES[c](view, today) for c in chips)


def thresholds() -> dict[str, object]:
    return {"top_rt": TOP_RT, "top_imdb": TOP_IMDB, "recent_days": RECENT_DAYS}
```

- [ ] **Step 5: Run → PASS; lint; commit**

`uv run pytest tests/unit -q && uv run ruff check . && uv run mypy`
`git add -A && git commit -m "Add domain models and canned-filter predicates"`

---

### Task 3: SQLite schema + Repository

**Files:**
- Create: `migrations/001_init.sql`, `src/movie_brain/infrastructure/database.py`, `tests/unit/test_database.py`
- Modify: `tests/conftest.py` (add `repo` fixture)

**Interfaces:**
- Consumes: `Film`, `OmdbRating`, `FilmView` from Task 2.
- Produces: `init_db(db_path: Path) -> None` and `class Repository(db_path: Path)` with:
  - `upsert_film(film: Film) -> int` — returns film id; updates title/year/director on conflict by `key`.
  - `film_id_by_key(key: str) -> int | None`
  - `record_listing(film_id: int, source: str, url: str, seen: date) -> None` — inserts with `first_seen=last_seen=seen`; on conflict updates `url`, `last_seen`.
  - `set_leaving(source: str, leaving: dict[str, str]) -> None` — NULLs every `leaving_date` for `source`, then sets by film key.
  - `current_films(source: str) -> list[tuple[int, Film]]` — listings whose `last_seen` equals the max `last_seen` for that source (= the latest catalog walk). Empty list if none.
  - `get_meta(key: str) -> str | None`, `set_meta(key: str, value: str) -> None`
  - `films_needing_lookup(source: str, today: date) -> list[tuple[int, Film]]` — current films with no `omdb` row, or `found=0 AND (year_fallback=0 OR looked_up <= today-30d)`, or `needs_refresh=1`.
  - `upsert_omdb(film_id: int, rating: OmdbRating, looked_up: date, *, year_fallback: bool = True, needs_refresh: bool = False) -> None`
  - `set_rating(film_id: int, score: int | None, rated_at: date) -> bool` — `None` deletes; returns False if film id unknown.
  - `list_views(source: str) -> list[FilmView]` — one per *current* film; `pending` = no omdb row.
  - `get_view(film_id: int) -> FilmView | None`, `get_payload(film_id: int) -> str | None`
  - `summary(source: str) -> dict[str, int]` with keys `films, rated, pending, unmatched, leaving, mine`.
  - `all_my_ratings() -> dict[str, int]` (key → score; used by tests/export)

- [ ] **Step 1: Write `migrations/001_init.sql`**

```sql
CREATE TABLE schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE films (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    year INTEGER,
    director TEXT,
    key TEXT NOT NULL UNIQUE
);
CREATE TABLE listings (
    film_id INTEGER NOT NULL REFERENCES films(id),
    source TEXT NOT NULL,
    url TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    leaving_date TEXT,
    PRIMARY KEY (film_id, source)
);
CREATE INDEX listings_source_last_seen ON listings(source, last_seen);
CREATE TABLE omdb (
    film_id INTEGER PRIMARY KEY REFERENCES films(id),
    found INTEGER NOT NULL,
    imdb REAL,
    rt INTEGER,
    language TEXT,
    looked_up TEXT NOT NULL,
    year_fallback INTEGER NOT NULL DEFAULT 1,
    needs_refresh INTEGER NOT NULL DEFAULT 0,
    payload TEXT
);
CREATE TABLE my_ratings (
    film_id INTEGER PRIMARY KEY REFERENCES films(id),
    score INTEGER NOT NULL CHECK (score BETWEEN 0 AND 10),
    rated_at TEXT NOT NULL
);
CREATE TABLE meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT INTO schema_version (version) VALUES (1);
```

- [ ] **Step 2: Failing tests** — `tests/unit/test_database.py`

```python
from datetime import date

from movie_brain.domain.models import Film, OmdbRating
from movie_brain.infrastructure.database import Repository, init_db

TRIO = Film("Trio", 1950, "Ken Annakin", "https://c/trio")
QUARTET = Film("Quartet", 1948, "Ken Annakin", "https://c/quartet")
D1, D2 = date(2026, 8, 1), date(2026, 8, 19)


def test_init_db_is_idempotent(tmp_path):
    p = tmp_path / "x.db"
    init_db(p)
    init_db(p)
    repo = Repository(p)
    assert repo.summary("criterion") == {"films": 0, "rated": 0, "pending": 0, "unmatched": 0, "leaving": 0, "mine": 0}


def test_upsert_film_returns_stable_id_and_updates_fields(repo):
    fid = repo.upsert_film(TRIO)
    assert repo.upsert_film(Film("Trio", 1950, "K. Annakin & H. French", "https://c/trio2")) == fid
    assert repo.film_id_by_key("trio (1950)") == fid
    assert repo.film_id_by_key("nope (1)") is None


def test_record_listing_sets_first_seen_once_and_bumps_last_seen(repo):
    fid = repo.upsert_film(TRIO)
    repo.record_listing(fid, "criterion", TRIO.url, D1)
    repo.record_listing(fid, "criterion", "https://c/trio-new", D2)
    v = repo.get_view(fid)
    assert v is not None and v.first_seen == "2026-08-01" and v.url == "https://c/trio-new"


def test_current_films_is_latest_walk_only(repo):
    a = repo.upsert_film(TRIO)
    b = repo.upsert_film(QUARTET)
    repo.record_listing(a, "criterion", TRIO.url, D1)
    repo.record_listing(b, "criterion", QUARTET.url, D1)
    repo.record_listing(a, "criterion", TRIO.url, D2)  # Quartet dropped off the channel
    assert [f.key for _, f in repo.current_films("criterion")] == ["trio (1950)"]
    assert [v.title for v in repo.list_views("criterion")] == ["Trio"]


def test_set_leaving_replaces_previous(repo):
    a = repo.upsert_film(TRIO)
    b = repo.upsert_film(QUARTET)
    for fid, f in ((a, TRIO), (b, QUARTET)):
        repo.record_listing(fid, "criterion", f.url, D1)
    repo.set_leaving("criterion", {"trio (1950)": "August 31"})
    repo.set_leaving("criterion", {"quartet (1948)": "September 30"})
    views = {v.title: v.leaving_date for v in repo.list_views("criterion")}
    assert views == {"Trio": None, "Quartet": "September 30"}


def test_films_needing_lookup_rules(repo):
    ids = []
    for f in (TRIO, QUARTET, Film("Third", 1960, None, "u3"), Film("Fourth", 1970, None, "u4")):
        fid = repo.upsert_film(f)
        repo.record_listing(fid, "criterion", f.url, D2)
        ids.append(fid)
    repo.upsert_omdb(ids[0], OmdbRating(7.0, 80, True, "English", "{}"), D1)            # found → never again
    repo.upsert_omdb(ids[1], OmdbRating(None, None, False), date(2026, 7, 1))             # miss, 49 days old → retry
    repo.upsert_omdb(ids[2], OmdbRating(None, None, False), date(2026, 8, 10))            # miss, 9 days old → wait
    # ids[3] has no row → lookup
    need = sorted(fid for fid, _ in repo.films_needing_lookup("criterion", D2))
    assert need == sorted([ids[1], ids[3]])


def test_needs_refresh_and_legacy_miss_without_fallback_are_relooked(repo):
    a = repo.upsert_film(TRIO)
    b = repo.upsert_film(QUARTET)
    repo.record_listing(a, "criterion", TRIO.url, D2)
    repo.record_listing(b, "criterion", QUARTET.url, D2)
    repo.upsert_omdb(a, OmdbRating(7.0, None, True, None), D1, needs_refresh=True)
    repo.upsert_omdb(b, OmdbRating(None, None, False), D2, year_fallback=False)
    assert sorted(fid for fid, _ in repo.films_needing_lookup("criterion", D2)) == sorted([a, b])


def test_set_rating_and_unrate(repo):
    fid = repo.upsert_film(TRIO)
    repo.record_listing(fid, "criterion", TRIO.url, D2)
    assert repo.set_rating(fid, 8, D2) is True
    assert repo.get_view(fid).my_rating == 8
    assert repo.set_rating(fid, None, D2) is True
    assert repo.get_view(fid).my_rating is None
    assert repo.set_rating(999, 5, D2) is False
    assert repo.all_my_ratings() == {}


def test_views_and_summary(repo):
    a = repo.upsert_film(TRIO)
    b = repo.upsert_film(QUARTET)
    c = repo.upsert_film(Film("Third", 1960, None, "u3"))
    for fid, f in ((a, TRIO), (b, QUARTET), (c, Film("Third", 1960, None, "u3"))):
        repo.record_listing(fid, "criterion", f.url, D2)
    repo.upsert_omdb(a, OmdbRating(7.5, 91, True, "English", '{"Title":"Trio"}'), D2)
    repo.upsert_omdb(b, OmdbRating(None, None, False), D2)
    repo.set_leaving("criterion", {"trio (1950)": "August 31"})
    repo.set_rating(a, 0, D2)
    va = repo.get_view(a)
    assert (va.imdb, va.rt, va.found, va.pending, va.leaving_date, va.my_rating) == (7.5, 91, True, False, "August 31", 0)
    vc = repo.get_view(c)
    assert (vc.found, vc.pending) == (None, True)
    assert repo.get_payload(a) == '{"Title":"Trio"}' and repo.get_payload(c) is None
    assert repo.summary("criterion") == {"films": 3, "rated": 1, "pending": 1, "unmatched": 1, "leaving": 1, "mine": 1}


def test_meta(repo):
    assert repo.get_meta("films_fetched_at") is None
    repo.set_meta("films_fetched_at", "2026-08-19")
    repo.set_meta("films_fetched_at", "2026-08-20")
    assert repo.get_meta("films_fetched_at") == "2026-08-20"
```

Add to `tests/conftest.py`:
```python
@pytest.fixture
def repo(config_dir):
    from movie_brain.infrastructure.database import Repository
    return Repository(config_dir / "movie-brain.db")
```

- [ ] **Step 3: Run → FAIL** `uv run pytest tests/unit/test_database.py -q`

- [ ] **Step 4: Implement `infrastructure/database.py`**

```python
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

from movie_brain.domain.models import Film, FilmView, OmdbRating

MISS_RETRY_DAYS = 30
MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "migrations"


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        has_versions = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_version'"
        ).fetchone()
        applied = {r[0] for r in conn.execute("SELECT version FROM schema_version")} if has_versions else set()
        for mig in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = int(mig.name.split("_")[0])
            if version not in applied:
                conn.executescript(mig.read_text())
        conn.commit()
    finally:
        conn.close()


_VIEW_SQL = """
SELECT f.id, f.title, f.year, f.director, l.url, o.language, o.imdb, o.rt, o.found,
       (o.film_id IS NULL) AS pending, l.leaving_date, l.first_seen, r.score
FROM films f
JOIN listings l ON l.film_id = f.id AND l.source = ?
LEFT JOIN omdb o ON o.film_id = f.id
LEFT JOIN my_ratings r ON r.film_id = f.id
"""


def _row_to_view(row: sqlite3.Row) -> FilmView:
    return FilmView(
        id=row["id"], title=row["title"], year=row["year"], director=row["director"], url=row["url"],
        language=row["language"], imdb=row["imdb"], rt=row["rt"],
        found=None if row["found"] is None else bool(row["found"]),
        pending=bool(row["pending"]), leaving_date=row["leaving_date"], first_seen=row["first_seen"],
        my_rating=row["score"],
    )


class Repository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        init_db(db_path)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # films / listings -------------------------------------------------
    def upsert_film(self, film: Film) -> int:
        with self._conn() as c:
            c.execute(
                "INSERT INTO films (title, year, director, key) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET title=excluded.title, year=excluded.year, director=excluded.director",
                (film.title, film.year, film.director, film.key),
            )
            row = c.execute("SELECT id FROM films WHERE key = ?", (film.key,)).fetchone()
            return int(row["id"])

    def film_id_by_key(self, key: str) -> int | None:
        with self._conn() as c:
            row = c.execute("SELECT id FROM films WHERE key = ?", (key,)).fetchone()
            return None if row is None else int(row["id"])

    def record_listing(self, film_id: int, source: str, url: str, seen: date) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO listings (film_id, source, url, first_seen, last_seen) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(film_id, source) DO UPDATE SET url=excluded.url, last_seen=excluded.last_seen",
                (film_id, source, url, seen.isoformat(), seen.isoformat()),
            )

    def set_leaving(self, source: str, leaving: dict[str, str]) -> None:
        with self._conn() as c:
            c.execute("UPDATE listings SET leaving_date = NULL WHERE source = ?", (source,))
            for key, label in leaving.items():
                c.execute(
                    "UPDATE listings SET leaving_date = ? WHERE source = ? AND film_id = (SELECT id FROM films WHERE key = ?)",
                    (label, source, key),
                )

    def _current_rows(self, c: sqlite3.Connection, source: str, extra_where: str = "", params: tuple[object, ...] = ()) -> list[sqlite3.Row]:
        sql = (
            "SELECT f.id, f.title, f.year, f.director, l.url FROM films f JOIN listings l ON l.film_id = f.id "
            "WHERE l.source = ? AND l.last_seen = (SELECT MAX(last_seen) FROM listings WHERE source = ?) " + extra_where +
            " ORDER BY f.id"
        )
        return c.execute(sql, (source, source, *params)).fetchall()

    def current_films(self, source: str) -> list[tuple[int, Film]]:
        with self._conn() as c:
            return [(r["id"], Film(r["title"], r["year"], r["director"], r["url"])) for r in self._current_rows(c, source)]

    # meta -------------------------------------------------------------
    def get_meta(self, key: str) -> str | None:
        with self._conn() as c:
            row = c.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
            return None if row is None else str(row["value"])

    def set_meta(self, key: str, value: str) -> None:
        with self._conn() as c:
            c.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    # omdb -------------------------------------------------------------
    def films_needing_lookup(self, source: str, today: date) -> list[tuple[int, Film]]:
        cutoff = (today - timedelta(days=MISS_RETRY_DAYS)).isoformat()
        where = (
            "AND (NOT EXISTS (SELECT 1 FROM omdb o WHERE o.film_id = f.id) "
            "OR EXISTS (SELECT 1 FROM omdb o WHERE o.film_id = f.id AND "
            "(o.needs_refresh = 1 OR (o.found = 0 AND (o.year_fallback = 0 OR o.looked_up <= ?)))))"
        )
        with self._conn() as c:
            return [(r["id"], Film(r["title"], r["year"], r["director"], r["url"])) for r in self._current_rows(c, source, where, (cutoff,))]

    def upsert_omdb(self, film_id: int, rating: OmdbRating, looked_up: date, *, year_fallback: bool = True, needs_refresh: bool = False) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO omdb (film_id, found, imdb, rt, language, looked_up, year_fallback, needs_refresh, payload) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(film_id) DO UPDATE SET found=excluded.found, imdb=excluded.imdb, "
                "rt=excluded.rt, language=excluded.language, looked_up=excluded.looked_up, year_fallback=excluded.year_fallback, "
                "needs_refresh=excluded.needs_refresh, payload=COALESCE(excluded.payload, omdb.payload)",
                (film_id, int(rating.found), rating.imdb, rating.rt, rating.language, looked_up.isoformat(),
                 int(year_fallback), int(needs_refresh), rating.payload),
            )

    # ratings ----------------------------------------------------------
    def set_rating(self, film_id: int, score: int | None, rated_at: date) -> bool:
        with self._conn() as c:
            if c.execute("SELECT 1 FROM films WHERE id = ?", (film_id,)).fetchone() is None:
                return False
            if score is None:
                c.execute("DELETE FROM my_ratings WHERE film_id = ?", (film_id,))
            else:
                c.execute(
                    "INSERT INTO my_ratings (film_id, score, rated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(film_id) DO UPDATE SET score=excluded.score, rated_at=excluded.rated_at",
                    (film_id, score, rated_at.isoformat()),
                )
            return True

    def all_my_ratings(self) -> dict[str, int]:
        with self._conn() as c:
            rows = c.execute("SELECT f.key, r.score FROM my_ratings r JOIN films f ON f.id = r.film_id").fetchall()
            return {str(r["key"]): int(r["score"]) for r in rows}

    # views ------------------------------------------------------------
    def list_views(self, source: str) -> list[FilmView]:
        with self._conn() as c:
            rows = c.execute(
                _VIEW_SQL + "WHERE l.last_seen = (SELECT MAX(last_seen) FROM listings WHERE source = ?) ORDER BY f.id",
                (source, source),
            ).fetchall()
            return [_row_to_view(r) for r in rows]

    def get_view(self, film_id: int) -> FilmView | None:
        with self._conn() as c:
            row = c.execute(_VIEW_SQL + "WHERE f.id = ?", ("criterion", film_id)).fetchone()
            return None if row is None else _row_to_view(row)

    def get_payload(self, film_id: int) -> str | None:
        with self._conn() as c:
            row = c.execute("SELECT payload FROM omdb WHERE film_id = ?", (film_id,)).fetchone()
            return None if row is None or row["payload"] is None else str(row["payload"])

    def summary(self, source: str) -> dict[str, int]:
        views = self.list_views(source)
        return {
            "films": len(views),
            "rated": sum(1 for v in views if v.found is True),
            "pending": sum(1 for v in views if v.pending),
            "unmatched": sum(1 for v in views if v.found is False),
            "leaving": sum(1 for v in views if v.leaving_date is not None),
            "mine": sum(1 for v in views if v.my_rating is not None),
        }
```

Note `get_view` hard-codes `'criterion'` for the listing join — acceptable until a second source exists; `list_views`/`summary` take `source` so the API can pass it through.

- [ ] **Step 5: Run → PASS; lint; commit**

`uv run pytest tests/unit -q && uv run ruff check . && uv run mypy`
`git add -A && git commit -m "Add SQLite schema and repository"`

---

### Task 4: Criterion adapter (port of catalog.py)

**Files:**
- Create: `src/movie_brain/infrastructure/criterion.py`, `tests/unit/test_criterion.py`

**Interfaces:**
- Produces: `CatalogError`, `fetch_token(session) -> str`, `fetch_films(session, token, delay_s=0.25) -> list[Film]`, `fetch_leaving(session, token, delay_s=0.25) -> dict[str, str]` (film key → label like `"August 31"`), `page_one_matches(session, token, known: list[Film]) -> bool`. Constants `BROWSE_URL`, `API_URL`, `PRODUCT`, `USER_AGENT`.

The JSON snapshot functions (`load_snapshot`/`save_snapshot`/`fetch_films_cached`) are **not** ported — the DB is the snapshot (Task 6).

- [ ] **Step 1: Failing tests** — `tests/unit/test_criterion.py`

```python
import pytest
import requests
import responses

from movie_brain.domain.models import Film
from movie_brain.infrastructure.criterion import (
    API_URL, BROWSE_URL, CatalogError, fetch_films, fetch_leaving, fetch_token, page_one_matches,
)

BROWSE_HTML = '<html><script>window.TOKEN = "tok-abc123";</script></html>'


def movie(name, year, director, page_url):
    return {"name": name, "type": "movie", "metadata": {"director": director, "year_released": year},
            "_links": {"collection_page": {"href": page_url}}}


def api_page(collections, page, last_page, total=None):
    nxt = None if page >= last_page else f"{API_URL}?page={page + 1}"
    body = {"_links": {"next": {"href": nxt}}, "_embedded": {"collections": collections}}
    if total is not None:
        body["total"] = total
    return body


def category(cid, name):
    return {"id": cid, "type": "category", "name": name, "_links": {}}


@responses.activate
def test_fetch_token_extracts_window_token():
    responses.get(BROWSE_URL, body=BROWSE_HTML)
    assert fetch_token(requests.Session()) == "tok-abc123"


@responses.activate
def test_fetch_token_raises_when_missing():
    responses.get(BROWSE_URL, body="<html></html>")
    with pytest.raises(CatalogError):
        fetch_token(requests.Session())


@responses.activate
def test_fetch_films_walks_pages_until_next_is_null():
    responses.get(API_URL, json=api_page([movie("Trio", 1950, "Ken Annakin", "https://c/trio")], 1, 2))
    responses.get(API_URL, json=api_page([movie("Quartet", 1948, None, "https://c/quartet")], 2, 2))
    films = fetch_films(requests.Session(), "tok", delay_s=0)
    assert films == [Film("Trio", 1950, "Ken Annakin", "https://c/trio"), Film("Quartet", 1948, None, "https://c/quartet")]
    assert responses.calls[0].request.headers["Authorization"] == "Bearer tok"
    assert responses.calls[0].request.params["type[]"] == "movie"


@responses.activate
def test_fetch_films_raises_on_empty_catalog():
    responses.get(API_URL, json=api_page([], 1, 1))
    with pytest.raises(CatalogError):
        fetch_films(requests.Session(), "tok", delay_s=0)


@responses.activate
def test_fetch_leaving_maps_keys_to_label():
    responses.get(API_URL, json=api_page([category(7, "Leaving August 31"), category(8, "Comedies")], 1, 1))
    responses.get(f"{API_URL}/7/items", json={"_links": {"next": {"href": None}},
                                              "_embedded": {"items": [{"name": "Trio", "metadata": {"year_released": 1950}}]}})
    assert fetch_leaving(requests.Session(), "tok", delay_s=0) == {"trio (1950)": "August 31"}
    assert len(responses.calls) == 2  # non-leaving category not walked


@responses.activate
def test_page_one_matches_true_when_total_and_first_page_agree():
    known = [Film("Trio", 1950, "K", "u1"), Film("Quartet", 1948, "K", "u2")]
    responses.get(API_URL, json=api_page([movie("Trio", 1950, "K", "u1")], 1, 1, total=2))
    assert page_one_matches(requests.Session(), "tok", known) is True


@responses.activate
def test_page_one_matches_false_on_total_change_or_unknown_film():
    known = [Film("Trio", 1950, "K", "u1")]
    responses.get(API_URL, json=api_page([movie("Trio", 1950, "K", "u1")], 1, 1, total=2))
    assert page_one_matches(requests.Session(), "tok", known) is False
    responses.get(API_URL, json=api_page([movie("New", 2020, "K", "u9")], 1, 1, total=1))
    assert page_one_matches(requests.Session(), "tok", known) is False
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement `infrastructure/criterion.py`** (port; `page_one_matches` takes `list[Film]` instead of a snapshot dict)

```python
from __future__ import annotations

import json
import re
import time
from typing import Any

import requests

from movie_brain.domain.models import Film, film_key

BROWSE_URL = "https://www.criterionchannel.com/browse"
API_URL = "https://api.vhx.tv/collections"
PRODUCT = "https://api.vhx.tv/products/39621"
USER_AGENT = "movie-brain/0.1 (personal watchlist tool)"
_TOKEN_RE = re.compile(r'window\.TOKEN = "([^"]+)"')
_LEAVING_RE = re.compile(r"^Leaving\s+(.+)$")


class CatalogError(Exception):
    pass


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT}


def fetch_token(session: requests.Session) -> str:
    resp = session.get(BROWSE_URL, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    match = _TOKEN_RE.search(resp.text)
    if not match:
        raise CatalogError("no window.TOKEN on browse page — site markup changed?")
    return match.group(1)


def _to_film(item: dict[str, Any]) -> Film:
    meta = item.get("metadata") or {}
    return Film(
        title=item["name"], year=meta.get("year_released"), director=meta.get("director"),
        url=item.get("_links", {}).get("collection_page", {}).get("href") or "",
    )


def _has_next(payload: dict[str, Any]) -> bool:
    return bool((payload.get("_links", {}).get("next") or {}).get("href"))


def fetch_films(session: requests.Session, token: str, delay_s: float = 0.25) -> list[Film]:
    films: list[Film] = []
    page = 1
    while True:
        resp = session.get(API_URL, params={"product": PRODUCT, "type[]": "movie", "per_page": 100, "page": page},
                           headers=_headers(token), timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        batch = payload.get("_embedded", {}).get("collections", [])
        if not batch:
            break
        films.extend(_to_film(item) for item in batch)
        if not _has_next(payload):
            break
        page += 1
        time.sleep(delay_s)
    if not films:
        raise CatalogError("catalog returned zero films — API shape changed?")
    return films


def fetch_leaving(session: requests.Session, token: str, delay_s: float = 0.25) -> dict[str, str]:
    categories: list[dict[str, Any]] = []
    page = 1
    while True:
        resp = session.get(API_URL, params={"product": PRODUCT, "type[]": "category", "per_page": 100, "page": page},
                           headers=_headers(token), timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        categories += payload.get("_embedded", {}).get("collections", [])
        if not _has_next(payload):
            break
        page += 1
        time.sleep(delay_s)

    leaving: dict[str, str] = {}
    for cat in categories:
        match = _LEAVING_RE.match(cat.get("name") or "")
        if not match:
            continue
        label = match.group(1)
        page = 1
        while True:
            resp = session.get(f"{API_URL}/{cat['id']}/items",
                               params={"product": PRODUCT, "include_embedded": "true", "per_page": 100, "page": page},
                               headers=_headers(token), timeout=30)
            resp.raise_for_status()
            payload = resp.json()
            for item in payload.get("_embedded", {}).get("items", []):
                meta = item.get("metadata") or {}
                if name := item.get("name"):
                    leaving[film_key(name, meta.get("year_released"))] = label
            if not _has_next(payload):
                break
            page += 1
            time.sleep(delay_s)
    return leaving


def page_one_matches(session: requests.Session, token: str, known: list[Film]) -> bool:
    resp = session.get(API_URL, params={"product": PRODUCT, "type[]": "movie", "per_page": 100, "page": 1},
                       headers=_headers(token), timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("total") != len(known):
        return False
    collections = payload.get("_embedded", {}).get("collections", [])
    if not collections:
        return False
    keys = {f.key for f in known}
    for item in collections:
        meta = item.get("metadata") or {}
        if film_key(item.get("name") or "", meta.get("year_released")) not in keys:
            return False
    return True
```

- [ ] **Step 4: Run → PASS; lint; commit** — `git commit -am "Port Criterion catalog adapter"` (use `git add -A` first)

---

### Task 5: OMDb adapter (port of ratings.py)

**Files:**
- Create: `src/movie_brain/infrastructure/omdb.py`, `tests/unit/test_omdb.py`

**Interfaces:**
- Produces: `OMDB_URL`, `QuotaExceeded`, `AuthError`, `OmdbClient(api_key: str, session: requests.Session | None = None)` with `lookup(title: str, year: int | None) -> OmdbRating` (tries `year, year-1, year+1`; `payload` = raw response text of the matching query; `payload=None` when not found).

- [ ] **Step 1: Failing tests** — `tests/unit/test_omdb.py`

```python
import json

import pytest
import responses

from movie_brain.domain.models import OmdbRating
from movie_brain.infrastructure.omdb import OMDB_URL, AuthError, OmdbClient, QuotaExceeded

FOUND = {"Response": "True", "imdbRating": "8.6", "Language": "Japanese",
         "Ratings": [{"Source": "Internet Movie Database", "Value": "8.6/10"}, {"Source": "Rotten Tomatoes", "Value": "100%"}]}
NOT_FOUND = {"Response": "False", "Error": "Movie not found!"}


@responses.activate
def test_lookup_parses_imdb_rt_language_and_keeps_payload():
    responses.get(OMDB_URL, json=FOUND)
    r = OmdbClient("k").lookup("Seven Samurai", 1954)
    assert (r.imdb, r.rt, r.found, r.language) == (8.6, 100, True, "Japanese")
    assert json.loads(r.payload)["imdbRating"] == "8.6"
    assert responses.calls[0].request.params["t"] == "Seven Samurai"
    assert responses.calls[0].request.params["y"] == "1954"


@responses.activate
def test_lookup_handles_na_values():
    responses.get(OMDB_URL, json={"Response": "True", "imdbRating": "N/A", "Language": "N/A", "Ratings": []})
    r = OmdbClient("k").lookup("Obscurity", None)
    assert (r.imdb, r.rt, r.found, r.language) == (None, None, True, None)
    assert len(responses.calls) == 1  # no year → no fallback attempts


@responses.activate
def test_lookup_year_fallback_tries_minus_then_plus_one():
    responses.get(OMDB_URL, json=NOT_FOUND)
    responses.get(OMDB_URL, json=NOT_FOUND)
    responses.get(OMDB_URL, json=FOUND)
    r = OmdbClient("k").lookup("Late", 1990)
    assert r.found is True
    assert [c.request.params["y"] for c in responses.calls] == ["1990", "1989", "1991"]


@responses.activate
def test_lookup_not_found_after_fallbacks():
    for _ in range(3):
        responses.get(OMDB_URL, json=NOT_FOUND)
    assert OmdbClient("k").lookup("Nope", 1990) == OmdbRating(None, None, False, None, None)


@responses.activate
def test_quota_exceeded_from_401_and_from_body():
    responses.get(OMDB_URL, json={"Response": "False", "Error": "Request limit reached!"}, status=401)
    with pytest.raises(QuotaExceeded):
        OmdbClient("k").lookup("X", None)
    responses.get(OMDB_URL, json={"Response": "False", "Error": "Request limit reached!"})
    with pytest.raises(QuotaExceeded):
        OmdbClient("k").lookup("X", None)


@responses.activate
def test_auth_error_on_401_without_limit():
    responses.get(OMDB_URL, json={"Response": "False", "Error": "Invalid API key!"}, status=401)
    with pytest.raises(AuthError):
        OmdbClient("k").lookup("X", None)
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement `infrastructure/omdb.py`**

```python
from __future__ import annotations

import requests

from movie_brain.domain.models import OmdbRating

OMDB_URL = "https://www.omdbapi.com/"


class QuotaExceeded(Exception):
    pass


class AuthError(Exception):
    pass


class OmdbClient:
    def __init__(self, api_key: str, session: requests.Session | None = None) -> None:
        self.api_key = api_key
        self.session = session or requests.Session()

    def lookup(self, title: str, year: int | None) -> OmdbRating:
        candidates = [year] if year is None else [year, year - 1, year + 1]
        rating = OmdbRating(None, None, False)
        for candidate in candidates:
            rating = self._query(title, candidate)
            if rating.found:
                return rating
        return rating

    def _query(self, title: str, year: int | None) -> OmdbRating:
        params = {"t": title, "type": "movie", "apikey": self.api_key}
        if year:
            params["y"] = str(year)
        resp = self.session.get(OMDB_URL, params=params, timeout=30)
        if resp.status_code == 401:
            error = resp.json().get("Error") or ""
            if "limit" in error.lower():
                raise QuotaExceeded(title)
            raise AuthError(error or "invalid API key")
        resp.raise_for_status()
        data = resp.json()
        if data.get("Response") != "True":
            if "limit" in (data.get("Error") or "").lower():
                raise QuotaExceeded(title)
            return OmdbRating(None, None, False)
        imdb = float(data["imdbRating"]) if data.get("imdbRating") and data["imdbRating"] != "N/A" else None
        rt = None
        for entry in data.get("Ratings", []):
            if entry.get("Source") == "Rotten Tomatoes":
                rt = int(entry["Value"].rstrip("%"))
        language = data.get("Language")
        if not language or language == "N/A":
            language = None
        return OmdbRating(imdb=imdb, rt=rt, found=True, language=language, payload=resp.text)
```

- [ ] **Step 4: Run → PASS; lint; commit** — `git add -A && git commit -m "Port OMDb client, keeping raw payload on the rating"`

---

### Task 6: Sync service (catalog walk + OMDb fill)

**Files:**
- Create: `src/movie_brain/application/sync.py`, `tests/features/sync.feature`, `tests/step_defs/test_sync.py`
- Modify: `src/movie_brain/infrastructure/database.py` (add `record_catalog`), `tests/unit/test_database.py`

**Interfaces:**
- Consumes: `Repository` (Task 3), `criterion.*` (Task 4), `OmdbClient` (Task 5).
- Produces:
  - `Repository.record_catalog(source: str, films: list[Film], seen: date) -> None` — upsert every film + listing in one transaction (same semantics as `upsert_film` + `record_listing` per film).
  - `SyncResult(exit_code: int, full_walk: bool, films: int, looked_up: int, quota_hit: bool, failing: bool)` dataclass.
  - `sync(repo: Repository, api_key: str, today: date, *, session: requests.Session | None = None, delay_s: float = 0.25, force_full: bool = False, ratings_only: bool = False, max_age_days: int = 7, log: Callable[[str], None] = _stderr) -> SyncResult`
  - `SOURCE = "criterion"`

Exit codes (match legacy): `0` ok (possibly partial), `1` catalog unavailable / no snapshot for `--ratings-only`, `2` OMDb rejected key.

- [ ] **Step 1: Add `record_catalog` test to `tests/unit/test_database.py`**

```python
def test_record_catalog_bulk_matches_per_film_calls(repo):
    repo.record_catalog("criterion", [TRIO, QUARTET], D1)
    repo.record_catalog("criterion", [TRIO], D2)
    assert [f.key for _, f in repo.current_films("criterion")] == ["trio (1950)"]
    assert repo.get_view(repo.film_id_by_key("trio (1950)")).first_seen == "2026-08-01"
```

- [ ] **Step 2: Implement `record_catalog` in `database.py`** (inside `Repository`)

```python
    def record_catalog(self, source: str, films: list[Film], seen: date) -> None:
        day = seen.isoformat()
        with self._conn() as c:
            for film in films:
                c.execute(
                    "INSERT INTO films (title, year, director, key) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET title=excluded.title, year=excluded.year, director=excluded.director",
                    (film.title, film.year, film.director, film.key),
                )
                c.execute(
                    "INSERT INTO listings (film_id, source, url, first_seen, last_seen) "
                    "VALUES ((SELECT id FROM films WHERE key = ?), ?, ?, ?, ?) "
                    "ON CONFLICT(film_id, source) DO UPDATE SET url=excluded.url, last_seen=excluded.last_seen",
                    (film.key, source, film.url, day, day),
                )
```
Run `uv run pytest tests/unit/test_database.py -q` → PASS.

- [ ] **Step 3: Write `tests/features/sync.feature`**

```gherkin
Feature: Daily sync
  Keep the catalog and OMDb ratings in SQLite up to date, cheaply when nothing changed.

  Background:
    Given a fresh repository
    And the Criterion browse page exposes a token

  Scenario: First run does a full walk and fills ratings
    Given the Criterion catalog has films "Trio (1950)" and "Quartet (1948)"
    And OMDb knows every film
    When I sync
    Then the exit code is 0
    And the catalog walk was full
    And 2 films are current
    And 2 films have OMDb ratings
    And films_fetched_at is today

  Scenario: Unchanged page 1 within 7 days reuses the stored catalog
    Given the repository already holds "Trio (1950)" walked 2 days ago
    And the Criterion catalog has films "Trio (1950)"
    And OMDb knows every film
    When I sync
    Then the catalog walk was cheap
    And only page 1 of the movie catalog was requested
    And films_fetched_at is 2 days ago

  Scenario: A changed page 1 forces a full walk
    Given the repository already holds "Trio (1950)" walked 2 days ago
    And the Criterion catalog has films "Trio (1950)" and "New (2020)"
    And OMDb knows every film
    When I sync
    Then the catalog walk was full
    And 2 films are current

  Scenario: --full always walks
    Given the repository already holds "Trio (1950)" walked 2 days ago
    And the Criterion catalog has films "Trio (1950)"
    And OMDb knows every film
    When I sync with --full
    Then the catalog walk was full

  Scenario: --ratings-only skips Criterion
    Given the repository already holds "Trio (1950)" walked 2 days ago
    And OMDb knows every film
    When I sync with --ratings-only
    Then the exit code is 0
    And Criterion was never contacted
    And 1 films have OMDb ratings

  Scenario: --ratings-only without a stored catalog fails
    When I sync with --ratings-only
    Then the exit code is 1

  Scenario: Catalog failure leaves the database untouched
    Given the repository already holds "Trio (1950)" walked 2 days ago
    And the Criterion API returns 500
    When I sync
    Then the exit code is 1
    And 1 films are current
    And 0 films have OMDb ratings

  Scenario: Leaving-soon failure keeps last-known departures
    Given the repository already holds "Trio (1950)" walked 2 days ago leaving "August 31"
    And the Criterion catalog has films "Trio (1950)"
    And the leaving-soon categories endpoint returns 500
    And OMDb knows every film
    When I sync
    Then the exit code is 0
    And "Trio (1950)" is leaving "August 31"

  Scenario: OMDb quota stops lookups but keeps what was fetched
    Given the Criterion catalog has films "Trio (1950)" and "Quartet (1948)"
    And OMDb answers once then reports the request limit
    When I sync
    Then the exit code is 0
    And the quota flag is set
    And 1 films have OMDb ratings

  Scenario: OMDb rejects the key
    Given the Criterion catalog has films "Trio (1950)"
    And OMDb rejects the API key
    When I sync
    Then the exit code is 2
```

- [ ] **Step 4: Write `tests/step_defs/test_sync.py`**

```python
from __future__ import annotations

import json
import re
from datetime import date, timedelta

import pytest
import requests
import responses
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.sync import SOURCE, SyncResult, sync
from movie_brain.domain.models import Film, film_key
from movie_brain.infrastructure.criterion import API_URL, BROWSE_URL
from movie_brain.infrastructure.omdb import OMDB_URL

scenarios("../features/sync.feature")

TODAY = date(2026, 8, 19)
FOUND = {"Response": "True", "imdbRating": "7.0", "Language": "English", "Ratings": []}
LIMIT = {"Response": "False", "Error": "Request limit reached!"}


def parse_titles(text: str) -> list[Film]:
    films = []
    for m in re.finditer(r'"([^"(]+) \((\d{4})\)"', text):
        title, year = m.group(1), int(m.group(2))
        films.append(Film(title, year, "Someone", f"https://c/{title.lower()}"))
    return films


def movie_item(f: Film) -> dict:
    return {"name": f.title, "metadata": {"year_released": f.year, "director": f.director},
            "_links": {"collection_page": {"href": f.url}}}


@pytest.fixture
def ctx(repo):
    rs = responses.RequestsMock(assert_all_requests_are_fired=False)
    rs.start()
    yield {"repo": repo, "rs": rs, "result": None, "flags": {}}
    rs.stop()
    rs.reset()


@given("a fresh repository")
def fresh(ctx):
    pass


@given("the Criterion browse page exposes a token")
def token(ctx):
    ctx["rs"].get(BROWSE_URL, body='<script>window.TOKEN = "tok";</script>')


@given(parsers.re(r'the repository already holds (?P<films>.+?) walked (?P<days>\d+) days ago(?: leaving "(?P<label>[^"]+)")?'))
def preloaded(ctx, films, days, label):
    flist = parse_titles(films)
    walked = TODAY - timedelta(days=int(days))
    ctx["repo"].record_catalog(SOURCE, flist, walked)
    ctx["repo"].set_meta("films_fetched_at", walked.isoformat())
    if label:
        ctx["repo"].set_leaving(SOURCE, {f.key: label for f in flist})


@given(parsers.parse("the Criterion catalog has films {films}"))
def catalog(ctx, films):
    flist = parse_titles(films)
    ctx["catalog_films"] = flist

    def movies(request):
        return (200, {}, json.dumps({
            "total": len(flist), "_links": {"next": {"href": None}},
            "_embedded": {"collections": [movie_item(f) for f in flist]}}))

    def categories(request):
        return (200, {}, '{"_links": {"next": {"href": null}}, "_embedded": {"collections": []}}')

    ctx["rs"].add_callback(responses.GET, API_URL, callback=lambda r: movies(r) if "type%5B%5D=movie" in r.url else categories(r))


@given("the Criterion API returns 500")
def api_down(ctx):
    ctx["rs"].get(API_URL, status=500)


@given("the leaving-soon categories endpoint returns 500")
def leaving_down(ctx):
    # Replace the callback registered by `catalog` with one that fails for categories only.
    ctx["rs"].remove(responses.GET, API_URL)
    flist = ctx.setdefault("catalog_films", [])

    def cb(request):
        if "type%5B%5D=movie" in request.url:
            return (200, {}, json.dumps({
                "total": len(flist), "_links": {"next": {"href": None}},
                "_embedded": {"collections": [movie_item(f) for f in flist]}}))
        return (500, {}, "boom")

    ctx["rs"].add_callback(responses.GET, API_URL, callback=cb)


@given("OMDb knows every film")
def omdb_ok(ctx):
    ctx["rs"].get(OMDB_URL, json=FOUND)


@given("OMDb answers once then reports the request limit")
def omdb_quota(ctx):
    ctx["rs"].get(OMDB_URL, json=FOUND)
    ctx["rs"].get(OMDB_URL, json=LIMIT, status=401)


@given("OMDb rejects the API key")
def omdb_auth(ctx):
    ctx["rs"].get(OMDB_URL, json={"Response": "False", "Error": "Invalid API key!"}, status=401)


def _run(ctx, **kw):
    ctx["result"] = sync(ctx["repo"], "key", TODAY, session=requests.Session(), delay_s=0, log=lambda m: None, **kw)


@when("I sync")
def run_sync(ctx):
    _run(ctx)


@when("I sync with --full")
def run_full(ctx):
    _run(ctx, force_full=True)


@when("I sync with --ratings-only")
def run_ro(ctx):
    _run(ctx, ratings_only=True)


@then(parsers.parse("the exit code is {code:d}"))
def exit_code(ctx, code):
    assert isinstance(ctx["result"], SyncResult)
    assert ctx["result"].exit_code == code


@then("the catalog walk was full")
def walk_full(ctx):
    assert ctx["result"].full_walk is True


@then("the catalog walk was cheap")
def walk_cheap(ctx):
    assert ctx["result"].full_walk is False


@then("only page 1 of the movie catalog was requested")
def only_page_one(ctx):
    movie_calls = [c for c in ctx["rs"].calls if c.request.url.startswith(API_URL) and "type%5B%5D=movie" in c.request.url]
    assert len(movie_calls) == 1 and "page=1" in movie_calls[0].request.url


@then("Criterion was never contacted")
def no_criterion(ctx):
    assert not any(c.request.url.startswith((BROWSE_URL, API_URL)) for c in ctx["rs"].calls)


@then(parsers.parse("{n:d} films are current"))
def n_current(ctx, n):
    assert len(ctx["repo"].current_films(SOURCE)) == n


@then(parsers.parse("{n:d} films have OMDb ratings"))
def n_rated(ctx, n):
    assert sum(1 for v in ctx["repo"].list_views(SOURCE) if v.found is True) == n


@then("films_fetched_at is today")
def fetched_today(ctx):
    assert ctx["repo"].get_meta("films_fetched_at") == TODAY.isoformat()


@then(parsers.parse("films_fetched_at is {days:d} days ago"))
def fetched_days_ago(ctx, days):
    assert ctx["repo"].get_meta("films_fetched_at") == (TODAY - timedelta(days=days)).isoformat()


@then(parsers.parse('"{title}" is leaving "{label}"'))
def is_leaving(ctx, title, label):
    f = parse_titles(f'"{title}"')[0]
    view = ctx["repo"].get_view(ctx["repo"].film_id_by_key(f.key))
    assert view.leaving_date == label


@then("the quota flag is set")
def quota_flag(ctx):
    assert ctx["result"].quota_hit is True
```

- [ ] **Step 5: Run → FAIL** `uv run pytest tests/step_defs/test_sync.py -q` (import error).

- [ ] **Step 6: Implement `application/sync.py`**

```python
from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import requests

from movie_brain.infrastructure.criterion import CatalogError, fetch_films, fetch_leaving, fetch_token, page_one_matches
from movie_brain.infrastructure.database import Repository
from movie_brain.infrastructure.omdb import AuthError, OmdbClient, QuotaExceeded

SOURCE = "criterion"
MAX_CONSECUTIVE_FAILURES = 5


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


@dataclass(frozen=True)
class SyncResult:
    exit_code: int
    full_walk: bool
    films: int
    looked_up: int
    quota_hit: bool
    failing: bool


def sync(
    repo: Repository,
    api_key: str,
    today: date,
    *,
    session: requests.Session | None = None,
    delay_s: float = 0.25,
    force_full: bool = False,
    ratings_only: bool = False,
    max_age_days: int = 7,
    log: Callable[[str], None] = _stderr,
) -> SyncResult:
    session = session or requests.Session()
    known = [f for _, f in repo.current_films(SOURCE)]
    full_walk = False

    if ratings_only:
        if not known:
            log("no stored catalog — run once without --ratings-only first")
            return SyncResult(1, False, 0, 0, False, False)
    else:
        try:
            token = fetch_token(session)
            fetched_at = repo.get_meta("films_fetched_at")
            reuse = False
            if not force_full and known and fetched_at:
                age = (today - date.fromisoformat(fetched_at)).days
                reuse = 0 <= age <= max_age_days and page_one_matches(session, token, known)
            if reuse:
                films = known
            else:
                films = fetch_films(session, token, delay_s=delay_s)
                full_walk = True
        except (CatalogError, requests.RequestException) as exc:
            log(f"catalog fetch failed, database unchanged: {exc}")
            return SyncResult(1, False, 0, 0, False, False)

        repo.record_catalog(SOURCE, films, today)
        if full_walk:
            repo.set_meta("films_fetched_at", today.isoformat())
        try:
            repo.set_leaving(SOURCE, fetch_leaving(session, token, delay_s=delay_s))
        except Exception as exc:  # noqa: BLE001 — any failure here must not abort the run
            log(f"leaving-soon fetch failed, keeping last-known departures: {exc}")

    client = OmdbClient(api_key, session=session)
    looked_up = 0
    quota_hit = False
    consecutive = 0
    for film_id, film in repo.films_needing_lookup(SOURCE, today):
        if quota_hit or consecutive >= MAX_CONSECUTIVE_FAILURES:
            break
        try:
            rating = client.lookup(film.title, film.year)
        except QuotaExceeded:
            quota_hit = True
            continue
        except AuthError as exc:
            log(f"OMDb rejected the API key: {exc}")
            return SyncResult(2, full_walk, len(repo.current_films(SOURCE)), looked_up, False, False)
        except requests.RequestException as exc:
            log(f"lookup failed for {film.title!r}: {exc}")
            consecutive += 1
            continue
        repo.upsert_omdb(film_id, rating, today)
        looked_up += 1
        consecutive = 0

    failing = consecutive >= MAX_CONSECUTIVE_FAILURES
    if quota_hit:
        log("OMDb daily quota reached — partial ratings saved; next run resumes.")
    if failing:
        log("OMDb lookups failing repeatedly — partial ratings saved; next run resumes.")
    return SyncResult(0, full_walk, len(repo.current_films(SOURCE)), looked_up, quota_hit, failing)
```

- [ ] **Step 7: Run → PASS; lint; commit** — `uv run pytest -q && uv run ruff check . && uv run mypy` then `git add -A && git commit -m "Add sync service with cheap/full/ratings-only modes and tripwires"`

---

### Task 7: Legacy import

**Files:**
- Create: `src/movie_brain/application/legacy_import.py`, `tests/features/legacy_import.feature`, `tests/step_defs/test_legacy_import.py`

**Interfaces:**
- Produces: `ImportReport(films: int, omdb: int, payloads: int, ratings: int, unmatched_keys: list[str])`, `import_legacy(repo: Repository, legacy_dir: Path, today: date) -> ImportReport`. Raises `FileNotFoundError` if `catalog.json` is missing.

- [ ] **Step 1: Feature file** — `tests/features/legacy_import.feature`

```gherkin
Feature: Import criterion-ratings data
  Bring catalog, ratings cache, payloads and my ratings into SQLite once.

  Background:
    Given a legacy data dir with catalog "Trio (1950)" and "Quartet (1948)" fetched 2026-08-10 leaving Trio "August 31"
    And the legacy cache rates Trio 7.1/90 English and marks Quartet not found
    And a legacy payload file exists for Trio
    And legacy annotations rate Trio 8 and "Ghost (1999)" 5

  Scenario: Everything maps over
    When I import the legacy dir
    Then the report counts 2 films, 2 omdb rows, 1 payloads, 1 ratings
    And the report lists unmatched key "ghost (1999)"
    And Trio's view shows imdb 7.1, rt 90, leaving "August 31", first_seen 2026-08-10, my rating 8
    And Trio's payload contains "Trio"
    And Quartet is unmatched and not pending
    And films_fetched_at is 2026-08-10

  Scenario: Import is idempotent
    When I import the legacy dir
    And I import the legacy dir
    Then the report counts 2 films, 2 omdb rows, 1 payloads, 1 ratings
    And 2 films are current

  Scenario: Found rows without a language key are flagged for refresh
    Given the legacy cache entry for Trio has no language key
    When I import the legacy dir
    Then Trio needs an OMDb lookup

  Scenario: Missing catalog fails loudly
    Given the legacy catalog file is removed
    Then importing raises FileNotFoundError
```

- [ ] **Step 2: Step defs** — `tests/step_defs/test_legacy_import.py`

```python
from __future__ import annotations

import json
from datetime import date

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.legacy_import import ImportReport, import_legacy
from movie_brain.application.sync import SOURCE

scenarios("../features/legacy_import.feature")
TODAY = date(2026, 8, 19)


@pytest.fixture
def legacy(tmp_path):
    d = tmp_path / "legacy"
    (d / "payloads").mkdir(parents=True)
    return d


@pytest.fixture
def ctx(repo, legacy):
    return {"repo": repo, "legacy": legacy, "report": None}


@given(parsers.parse('a legacy data dir with catalog "{a}" and "{b}" fetched {fetched} leaving Trio "{label}"'))
def catalog(ctx, a, b, fetched, label):
    def film(s):
        title, year = s.rsplit(" (", 1)
        return {"title": title, "year": int(year[:-1]), "director": "Someone", "url": f"https://c/{title.lower()}"}
    films = [film(a), film(b)]
    (ctx["legacy"] / "catalog.json").write_text(json.dumps(
        {"films_fetched_at": fetched, "films": films, "leaving": {"trio (1950)": label}}))


@given("the legacy cache rates Trio 7.1/90 English and marks Quartet not found")
def cache(ctx):
    ctx["cache"] = {
        "trio (1950)": {"found": True, "imdb": 7.1, "rt": 90, "language": "English", "looked_up": "2026-08-10", "year_fallback": True},
        "quartet (1948)": {"found": False, "imdb": None, "rt": None, "language": None, "looked_up": "2026-08-10", "year_fallback": True},
    }
    (ctx["legacy"] / "cache.json").write_text(json.dumps(ctx["cache"]))


@given("the legacy cache entry for Trio has no language key")
def cache_no_language(ctx):
    del ctx["cache"]["trio (1950)"]["language"]
    (ctx["legacy"] / "cache.json").write_text(json.dumps(ctx["cache"]))


@given("a legacy payload file exists for Trio")
def payload(ctx):
    (ctx["legacy"] / "payloads" / "trio (1950).json").write_text('{"Title": "Trio", "Response": "True"}')


@given(parsers.parse('legacy annotations rate Trio {a:d} and "{other}" {b:d}'))
def annotations(ctx, a, other, b):
    (ctx["legacy"] / "annotations.json").write_text(json.dumps({"trio (1950)": a, other.lower(): b}))


@given("the legacy catalog file is removed")
def remove_catalog(ctx):
    (ctx["legacy"] / "catalog.json").unlink()


@when("I import the legacy dir")
def do_import(ctx):
    ctx["report"] = import_legacy(ctx["repo"], ctx["legacy"], TODAY)


@then(parsers.parse("the report counts {f:d} films, {o:d} omdb rows, {p:d} payloads, {r:d} ratings"))
def counts(ctx, f, o, p, r):
    rep: ImportReport = ctx["report"]
    assert (rep.films, rep.omdb, rep.payloads, rep.ratings) == (f, o, p, r)


@then(parsers.parse('the report lists unmatched key "{key}"'))
def unmatched(ctx, key):
    assert key in ctx["report"].unmatched_keys


@then(parsers.parse('Trio\'s view shows imdb {imdb:g}, rt {rt:d}, leaving "{label}", first_seen {fs}, my rating {score:d}'))
def trio_view(ctx, imdb, rt, label, fs, score):
    v = ctx["repo"].get_view(ctx["repo"].film_id_by_key("trio (1950)"))
    assert (v.imdb, v.rt, v.leaving_date, v.first_seen, v.my_rating) == (imdb, rt, label, fs, score)


@then(parsers.parse('Trio\'s payload contains "{text}"'))
def trio_payload(ctx, text):
    assert text in ctx["repo"].get_payload(ctx["repo"].film_id_by_key("trio (1950)"))


@then("Quartet is unmatched and not pending")
def quartet(ctx):
    v = ctx["repo"].get_view(ctx["repo"].film_id_by_key("quartet (1948)"))
    assert (v.found, v.pending) == (False, False)


@then(parsers.parse("films_fetched_at is {day}"))
def fetched(ctx, day):
    assert ctx["repo"].get_meta("films_fetched_at") == day


@then(parsers.parse("{n:d} films are current"))
def current(ctx, n):
    assert len(ctx["repo"].current_films(SOURCE)) == n


@then("Trio needs an OMDb lookup")
def trio_needs(ctx):
    assert "trio (1950)" in {f.key for _, f in ctx["repo"].films_needing_lookup(SOURCE, TODAY)}


@then("importing raises FileNotFoundError")
def raises(ctx):
    with pytest.raises(FileNotFoundError):
        import_legacy(ctx["repo"], ctx["legacy"], TODAY)
```

- [ ] **Step 3: Run → FAIL**

- [ ] **Step 4: Implement `application/legacy_import.py`**

```python
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from movie_brain.domain.models import Film, OmdbRating
from movie_brain.infrastructure.database import Repository

SOURCE = "criterion"


@dataclass
class ImportReport:
    films: int = 0
    omdb: int = 0
    payloads: int = 0
    ratings: int = 0
    unmatched_keys: list[str] = field(default_factory=list)


def _payload_path(legacy_dir: Path, key: str) -> Path:
    return legacy_dir / "payloads" / (key.replace("/", "_") + ".json")


def import_legacy(repo: Repository, legacy_dir: Path, today: date) -> ImportReport:
    report = ImportReport()
    catalog_path = legacy_dir / "catalog.json"
    if not catalog_path.exists():
        raise FileNotFoundError(catalog_path)
    catalog = json.loads(catalog_path.read_text())
    fetched_at = date.fromisoformat(catalog["films_fetched_at"])
    films = [Film(f["title"], f["year"], f["director"], f["url"]) for f in catalog["films"]]
    repo.record_catalog(SOURCE, films, fetched_at)
    repo.set_meta("films_fetched_at", fetched_at.isoformat())
    repo.set_leaving(SOURCE, catalog.get("leaving") or {})
    report.films = len(films)

    cache_path = legacy_dir / "cache.json"
    cache: dict[str, dict[str, object]] = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    for key, entry in cache.items():
        film_id = repo.film_id_by_key(key)
        if film_id is None:
            report.unmatched_keys.append(key)
            continue
        found = bool(entry["found"])
        payload_file = _payload_path(legacy_dir, key)
        payload = payload_file.read_text(encoding="utf-8") if found and payload_file.exists() else None
        if payload is not None:
            report.payloads += 1
        imdb = entry.get("imdb")
        rt = entry.get("rt")
        language = entry.get("language")
        repo.upsert_omdb(
            film_id,
            OmdbRating(
                imdb=float(imdb) if isinstance(imdb, int | float) else None,
                rt=int(rt) if isinstance(rt, int) else None,
                found=found,
                language=str(language) if isinstance(language, str) else None,
                payload=payload,
            ),
            date.fromisoformat(str(entry["looked_up"])),
            year_fallback=bool(entry.get("year_fallback", False)),
            needs_refresh=found and "language" not in entry,
        )
        report.omdb += 1

    ann_path = legacy_dir / "annotations.json"
    annotations: dict[str, int] = json.loads(ann_path.read_text()) if ann_path.exists() else {}
    for key, score in annotations.items():
        film_id = repo.film_id_by_key(key)
        if film_id is None:
            report.unmatched_keys.append(key)
            continue
        repo.set_rating(film_id, int(score), today)
        report.ratings += 1
    return report
```

- [ ] **Step 5: Run → PASS; lint; commit** — `git add -A && git commit -m "Add one-shot import of criterion-ratings data"`

---

### Task 8: Ratings service + CSV export

**Files:**
- Create: `src/movie_brain/application/ratings.py`, `src/movie_brain/application/export.py`, `tests/features/ratings.feature`, `tests/step_defs/test_ratings.py`, `tests/unit/test_export.py`

**Interfaces:**
- Produces:
  - `rate_film(repo: Repository, film_id: int, score: int | None, today: date) -> FilmView` — raises `ValueError("score must be an integer 0–10")` when out of range / not int / bool, `LookupError(film_id)` when unknown. `None` un-rates.
  - `write_csv(repo: Repository, path: Path, source: str = "criterion") -> int` — returns row count. Columns exactly: `title,year,director,language,imdb,rt,status,leaving,url,my-rating`; `status` ∈ `rated|unmatched|pending`; rows ordered imdb desc (nulls last), then title. Atomic write via `.tmp` + `os.replace`.

- [ ] **Step 1: Feature + steps** — `tests/features/ratings.feature`

```gherkin
Feature: My ratings
  Scenario Outline: Valid scores are stored
    Given a current film "Trio (1950)"
    When I rate it <score>
    Then its view shows my rating <score>
    Examples:
      | score |
      | 0     |
      | 7     |
      | 10    |

  Scenario: Blank un-rates
    Given a current film "Trio (1950)"
    When I rate it 7
    And I clear its rating
    Then its view shows no rating

  Scenario Outline: Out-of-range scores are rejected
    Given a current film "Trio (1950)"
    Then rating it <score> raises ValueError
    Examples:
      | score |
      | -1    |
      | 11    |

  Scenario: Unknown film is rejected
    Then rating film 999 raises LookupError
```

`tests/step_defs/test_ratings.py`:
```python
from datetime import date

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.ratings import rate_film
from movie_brain.domain.models import Film

scenarios("../features/ratings.feature")
TODAY = date(2026, 8, 19)


@pytest.fixture
def ctx(repo):
    return {"repo": repo, "fid": None}


@given(parsers.parse('a current film "{title} ({year:d})"'))
def film(ctx, title, year):
    f = Film(title, year, "D", "u")
    ctx["repo"].record_catalog("criterion", [f], TODAY)
    ctx["fid"] = ctx["repo"].film_id_by_key(f.key)


@when(parsers.parse("I rate it {score:d}"))
def rate(ctx, score):
    rate_film(ctx["repo"], ctx["fid"], score, TODAY)


@when("I clear its rating")
def clear(ctx):
    rate_film(ctx["repo"], ctx["fid"], None, TODAY)


@then(parsers.parse("its view shows my rating {score:d}"))
def shows(ctx, score):
    assert ctx["repo"].get_view(ctx["fid"]).my_rating == score


@then("its view shows no rating")
def shows_none(ctx):
    assert ctx["repo"].get_view(ctx["fid"]).my_rating is None


@then(parsers.parse("rating it {score:d} raises ValueError"))
def bad_score(ctx, score):
    with pytest.raises(ValueError):
        rate_film(ctx["repo"], ctx["fid"], score, TODAY)


@then(parsers.parse("rating film {fid:d} raises LookupError"))
def unknown(ctx, fid):
    with pytest.raises(LookupError):
        rate_film(ctx["repo"], fid, 5, TODAY)
```

`tests/unit/test_export.py`:
```python
import csv
from datetime import date

from movie_brain.application.export import write_csv
from movie_brain.domain.models import Film, OmdbRating

D = date(2026, 8, 19)


def test_csv_columns_order_and_status(repo, tmp_path):
    films = [Film("Low", 2000, "A", "u1"), Film("High", 2001, "B", "u2"), Film("Miss", 2002, None, "u3"), Film("Wait", 2003, None, "u4")]
    repo.record_catalog("criterion", films, D)
    ids = {f.key: repo.film_id_by_key(f.key) for f in films}
    repo.upsert_omdb(ids["low (2000)"], OmdbRating(6.0, 50, True, "English"), D)
    repo.upsert_omdb(ids["high (2001)"], OmdbRating(9.0, None, True, "French"), D)
    repo.upsert_omdb(ids["miss (2002)"], OmdbRating(None, None, False), D)
    repo.set_leaving("criterion", {"high (2001)": "August 31"})
    repo.set_rating(ids["low (2000)"], 3, D)
    out = tmp_path / "w.csv"
    assert write_csv(repo, out) == 4
    rows = list(csv.DictReader(out.open()))
    assert list(rows[0].keys()) == ["title", "year", "director", "language", "imdb", "rt", "status", "leaving", "url", "my-rating"]
    assert [r["title"] for r in rows] == ["High", "Low", "Miss", "Wait"]
    assert rows[0]["leaving"] == "August 31" and rows[0]["rt"] == ""
    assert rows[1]["my-rating"] == "3" and rows[1]["status"] == "rated"
    assert rows[2]["status"] == "unmatched" and rows[3]["status"] == "pending"
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement**

`application/ratings.py`:
```python
from __future__ import annotations

from datetime import date

from movie_brain.domain.models import FilmView
from movie_brain.infrastructure.database import Repository


def rate_film(repo: Repository, film_id: int, score: int | None, today: date) -> FilmView:
    if score is not None and (isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 10):
        raise ValueError("score must be an integer 0–10")
    if not repo.set_rating(film_id, score, today):
        raise LookupError(film_id)
    view = repo.get_view(film_id)
    assert view is not None
    return view
```

`application/export.py`:
```python
from __future__ import annotations

import csv
import os
from pathlib import Path

from movie_brain.domain.models import FilmView
from movie_brain.infrastructure.database import Repository

COLUMNS = ["title", "year", "director", "language", "imdb", "rt", "status", "leaving", "url", "my-rating"]


def _status(v: FilmView) -> str:
    if v.pending:
        return "pending"
    return "rated" if v.found else "unmatched"


def write_csv(repo: Repository, path: Path, source: str = "criterion") -> int:
    views = sorted(repo.list_views(source), key=lambda v: (v.imdb is None, -(v.imdb or 0.0), v.title.lower()))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(COLUMNS)
        for v in views:
            w.writerow([
                v.title, v.year if v.year is not None else "", v.director or "", v.language or "",
                v.imdb if v.imdb is not None else "", v.rt if v.rt is not None else "",
                _status(v), v.leaving_date or "", v.url, v.my_rating if v.my_rating is not None else "",
            ])
    os.replace(tmp, path)
    return len(views)
```

- [ ] **Step 4: Run → PASS; lint; commit** — `git add -A && git commit -m "Add rating service and CSV export"`

---

### Task 9: Typer CLI

**Files:**
- Create: `src/movie_brain/cli.py`, `tests/unit/test_cli.py`

**Interfaces:**
- Produces: `app: typer.Typer` with commands `sync [--full] [--ratings-only]`, `dashboard [--port 5556] [--host 127.0.0.1]`, `import-legacy [--from DIR]`, `export csv PATH`, `status`. Exit codes propagate from `sync`. `dashboard` imports `movie_brain.web.app.create_app` lazily (Task 10 supplies it).

- [ ] **Step 1: Failing tests** — `tests/unit/test_cli.py`

```python
import json
from datetime import date

from typer.testing import CliRunner

from movie_brain.application.sync import SyncResult
from movie_brain.cli import app

runner = CliRunner()


def test_sync_flags_are_mutually_exclusive(config_dir):
    (config_dir / "omdb-api-key.txt").write_text("k")
    r = runner.invoke(app, ["sync", "--full", "--ratings-only"])
    assert r.exit_code == 2
    assert "mutually exclusive" in r.output


def test_sync_requires_api_key(config_dir):
    r = runner.invoke(app, ["sync"])
    assert r.exit_code == 2
    assert "OMDB_API_KEY" in r.output


def test_sync_propagates_exit_code(config_dir, monkeypatch):
    (config_dir / "omdb-api-key.txt").write_text("k")
    calls = {}

    def fake_sync(repo, api_key, today, **kw):
        calls.update(kw, api_key=api_key)
        return SyncResult(1, False, 0, 0, False, False)

    monkeypatch.setattr("movie_brain.cli.sync", fake_sync)
    r = runner.invoke(app, ["sync", "--full"])
    assert r.exit_code == 1
    assert calls["force_full"] is True and calls["ratings_only"] is False and calls["api_key"] == "k"


def test_import_legacy_and_status(config_dir, tmp_path):
    legacy = tmp_path / "legacy"
    (legacy / "payloads").mkdir(parents=True)
    (legacy / "catalog.json").write_text(json.dumps({"films_fetched_at": "2026-08-10", "leaving": {},
        "films": [{"title": "Trio", "year": 1950, "director": "D", "url": "u"}]}))
    r = runner.invoke(app, ["import-legacy", "--from", str(legacy)])
    assert r.exit_code == 0 and "films: 1" in r.output
    r = runner.invoke(app, ["status"])
    assert r.exit_code == 0 and "1" in r.output


def test_export_csv(config_dir, tmp_path):
    out = tmp_path / "x.csv"
    r = runner.invoke(app, ["export", "csv", str(out)])
    assert r.exit_code == 0 and out.exists()
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement `cli.py`**

```python
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from movie_brain.application.export import write_csv
from movie_brain.application.legacy_import import import_legacy
from movie_brain.application.sync import SOURCE, sync
from movie_brain.infrastructure.config import load_api_key, load_config
from movie_brain.infrastructure.database import Repository

app = typer.Typer(name="movie-brain", help="Personal film brain: Criterion listings, OMDb ratings, my ratings.", no_args_is_help=True)
export_app = typer.Typer(help="Export data.")
app.add_typer(export_app, name="export")
console = Console()
err = Console(stderr=True)

LEGACY_DEFAULT = Path.home() / ".local" / "share" / "criterion-ratings"


def _repo() -> Repository:
    cfg = load_config()
    cfg.config_dir.mkdir(parents=True, exist_ok=True)
    return Repository(cfg.db_path)


@app.command("sync")
def sync_cmd(
    full: Annotated[bool, typer.Option("--full", help="Force a complete catalog re-walk.")] = False,
    ratings_only: Annotated[bool, typer.Option("--ratings-only", help="Skip Criterion; refresh OMDb ratings only.")] = False,
) -> None:
    """Refresh the catalog and OMDb ratings."""
    if full and ratings_only:
        err.print("--full and --ratings-only are mutually exclusive")
        raise typer.Exit(2)
    cfg = load_config()
    api_key = load_api_key(cfg)
    if not api_key:
        err.print(f"no OMDb key: set OMDB_API_KEY or write {cfg.key_file}")
        raise typer.Exit(2)
    result = sync(_repo(), api_key, date.today(), force_full=full, ratings_only=ratings_only)
    console.print(f"films: {result.films} · looked up: {result.looked_up} · full walk: {result.full_walk}")
    raise typer.Exit(result.exit_code)


@app.command()
def dashboard(
    port: Annotated[int, typer.Option(help="Port to listen on.")] = 5556,
    host: Annotated[str, typer.Option(help="Interface to bind.")] = "127.0.0.1",
) -> None:
    """Run the local web dashboard."""
    from movie_brain.web.app import create_app

    console.print(f"movie-brain dashboard → http://{host}:{port}")
    create_app(_repo()).run(host=host, port=port, debug=False)


@app.command("import-legacy")
def import_legacy_cmd(
    from_dir: Annotated[Path, typer.Option("--from", help="criterion-ratings data dir.")] = LEGACY_DEFAULT,
) -> None:
    """One-shot import of criterion-ratings JSON data (idempotent)."""
    try:
        report = import_legacy(_repo(), from_dir, date.today())
    except FileNotFoundError as exc:
        err.print(f"missing {exc}")
        raise typer.Exit(1) from exc
    console.print(f"films: {report.films} · omdb: {report.omdb} · payloads: {report.payloads} · ratings: {report.ratings}")
    if report.unmatched_keys:
        console.print(f"unmatched keys ({len(report.unmatched_keys)}): " + ", ".join(report.unmatched_keys))


@export_app.command("csv")
def export_csv(path: Annotated[Path, typer.Argument(help="Output CSV path.")]) -> None:
    """Write the watchlist as CSV."""
    n = write_csv(_repo(), path)
    console.print(f"wrote {n} rows to {path}")


@app.command()
def status() -> None:
    """Show counts."""
    s = _repo().summary(SOURCE)
    table = Table(title="movie-brain")
    table.add_column("metric")
    table.add_column("count", justify="right")
    for k, v in s.items():
        table.add_row(k, str(v))
    console.print(table)
```

- [ ] **Step 4: Run → PASS; lint; commit** — `git add -A && git commit -m "Add Typer CLI"`

---

### Task 10: Flask app + JSON API

**Files:**
- Create: `src/movie_brain/web/app.py`, `src/movie_brain/web/templates/index.html` (minimal shell; filled in Task 11), `tests/web/__init__.py`, `tests/web/test_api.py`

**Interfaces:**
- Consumes: `Repository`, `rate_film`, `filters.thresholds`, `filters.CHIPS`, `SOURCE`.
- Produces: `create_app(repo: Repository, today: Callable[[], date] = date.today) -> Flask` with routes:
  - `GET /` → `index.html`
  - `GET /api/films` → `[FilmView.to_dict()]`
  - `GET /api/films/<int:id>` → `FilmView.to_dict() | {"payload": dict|None}`; 404 `{"error": "not found"}`
  - `PUT /api/films/<int:id>/rating` body `{"score": int|null}` → updated view; 400 `{"error": ...}` on bad body/score; 404 unknown id
  - `GET /api/summary` → `repo.summary(SOURCE)`
  - `GET /api/config` → `{"canned_thresholds": {"top_rt", "top_imdb", "recent_days"}, "chips": [...], "today": "YYYY-MM-DD"}` (the spec's `recent_days` lives inside `canned_thresholds`; `today` is served so the JS "recent" predicate is deterministic in tests)

- [ ] **Step 1: Failing tests** — `tests/web/test_api.py`

```python
from datetime import date

import pytest

from movie_brain.domain.models import Film, OmdbRating
from movie_brain.web.app import create_app

D = date(2026, 8, 19)


@pytest.fixture
def client(repo):
    films = [Film("Trio", 1950, "Ken", "https://c/trio"), Film("Quartet", 1948, None, "https://c/quartet")]
    repo.record_catalog("criterion", films, D)
    a = repo.film_id_by_key("trio (1950)")
    repo.upsert_omdb(a, OmdbRating(7.5, 91, True, "English", '{"Title": "Trio", "Plot": "Three tales."}'), D)
    app = create_app(repo, today=lambda: D)
    app.testing = True
    return app.test_client()


def test_index_serves_html(client):
    r = client.get("/")
    assert r.status_code == 200 and b"<table" in r.data


def test_list_films(client):
    r = client.get("/api/films")
    assert r.status_code == 200
    rows = r.get_json()
    assert {x["title"] for x in rows} == {"Trio", "Quartet"}
    trio = next(x for x in rows if x["title"] == "Trio")
    assert trio["imdb"] == 7.5 and trio["pending"] is False and trio["my_rating"] is None
    assert "payload" not in trio


def test_detail_includes_parsed_payload(client):
    fid = client.get("/api/films").get_json()[0]["id"]
    r = client.get(f"/api/films/{fid}")
    assert r.status_code == 200
    body = r.get_json()
    assert body["title"] == "Trio" and body["payload"]["Plot"] == "Three tales."
    assert client.get("/api/films/999").status_code == 404


def test_detail_without_payload_is_null(client):
    fid = next(x["id"] for x in client.get("/api/films").get_json() if x["title"] == "Quartet")
    assert client.get(f"/api/films/{fid}").get_json()["payload"] is None


def test_rate_and_unrate(client):
    fid = client.get("/api/films").get_json()[0]["id"]
    r = client.put(f"/api/films/{fid}/rating", json={"score": 8})
    assert r.status_code == 200 and r.get_json()["my_rating"] == 8
    assert client.get("/api/summary").get_json()["mine"] == 1
    r = client.put(f"/api/films/{fid}/rating", json={"score": None})
    assert r.status_code == 200 and r.get_json()["my_rating"] is None


@pytest.mark.parametrize("body", [{"score": 11}, {"score": -1}, {"score": "7"}, {"score": 7.5}, {}, None])
def test_rate_rejects_bad_input(client, body):
    fid = client.get("/api/films").get_json()[0]["id"]
    r = client.put(f"/api/films/{fid}/rating", json=body) if body is not None else client.put(f"/api/films/{fid}/rating", data="nope")
    assert r.status_code == 400 and "error" in r.get_json()


def test_rate_unknown_film_404(client):
    assert client.put("/api/films/999/rating", json={"score": 5}).status_code == 404


def test_summary_and_config(client):
    assert client.get("/api/summary").get_json() == {"films": 2, "rated": 1, "pending": 1, "unmatched": 0, "leaving": 0, "mine": 0}
    cfg = client.get("/api/config").get_json()
    assert cfg["canned_thresholds"] == {"top_rt": 90, "top_imdb": 8.0, "recent_days": 30}
    assert cfg["today"] == "2026-08-19" and "leaving" in cfg["chips"]
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement `web/app.py`** and a stub `templates/index.html` containing `<table id="films"></table>`

```python
from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date

from flask import Flask, Response, jsonify, render_template, request

from movie_brain.application.ratings import rate_film
from movie_brain.application.sync import SOURCE
from movie_brain.domain.filters import CHIPS, thresholds
from movie_brain.infrastructure.database import Repository


def create_app(repo: Repository, today: Callable[[], date] = date.today) -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index() -> str:
        return render_template("index.html")

    @app.get("/api/films")
    def list_films() -> Response:
        return jsonify([v.to_dict() for v in repo.list_views(SOURCE)])

    @app.get("/api/films/<int:film_id>")
    def film_detail(film_id: int) -> tuple[Response, int]:
        view = repo.get_view(film_id)
        if view is None:
            return jsonify({"error": "not found"}), 404
        raw = repo.get_payload(film_id)
        payload: object = None
        if raw is not None:
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"_raw": raw}
        return jsonify({**view.to_dict(), "payload": payload}), 200

    @app.put("/api/films/<int:film_id>/rating")
    def put_rating(film_id: int) -> tuple[Response, int]:
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or "score" not in body:
            return jsonify({"error": "body must be JSON {\"score\": 0-10 | null}"}), 400
        score = body["score"]
        if score is not None and not isinstance(score, int):
            return jsonify({"error": "score must be an integer 0–10"}), 400
        try:
            view = rate_film(repo, film_id, score, today())
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except LookupError:
            return jsonify({"error": "not found"}), 404
        return jsonify(view.to_dict()), 200

    @app.get("/api/summary")
    def summary() -> Response:
        return jsonify(repo.summary(SOURCE))

    @app.get("/api/config")
    def config() -> Response:
        return jsonify({"canned_thresholds": thresholds(), "chips": list(CHIPS), "today": today().isoformat()})

    return app
```

The `isinstance` guard keeps mypy happy (JSON values are `object`); `rate_film` still rejects bools and out-of-range ints via `ValueError`.

- [ ] **Step 4: Run → PASS; lint; commit** — `git add -A && git commit -m "Add Flask app with films, rating, summary and config API"`

---

### Task 11: Dashboard page — table, chips, column filters, sort, URL state

**Files:**
- Create: `src/movie_brain/web/templates/index.html` (replace stub), `src/movie_brain/web/static/app.css`, `src/movie_brain/web/static/app.js`, `tests/web/conftest.py`, `tests/web/test_dashboard.py`

**Interfaces:**
- Consumes: API from Task 10.
- Produces: DOM contract used by tests and Task 12:
  - `#counts` header with spans `#count-films #count-rated #count-pending #count-unmatched #count-leaving #count-mine` and `#count-showing` ("Showing N of M")
  - `.chip[data-chip=<name>]` buttons with `.active` when on; `#chips-clear`
  - `th.sortable[data-col=<field>]` with `data-dir="asc|desc"` attribute when active
  - column filter inputs: `#f-title #f-director #f-lang (select multiple) #f-year-min #f-year-max #f-imdb-min #f-imdb-max #f-rt-min #f-rt-max`
  - `#films tbody tr[data-id=<id>]` with cells `.c-title a`, `.c-year .c-director .c-language .c-imdb .c-rt .c-leaving`, `.c-rating input.rating`, `.c-info button.info`
  - `tbody[data-count]` = filtered row count (virtual scroll renders only a window; tests assert `data-count`, not `tr` count)
  - global `window.MB` = `{state, applyFilters(), render()}` for debugging only.

- [ ] **Step 1: Playwright setup + failing tests**

Run once: `uv run playwright install chromium`.

`tests/web/conftest.py`:
```python
from __future__ import annotations

import socket
import threading
import time
from collections.abc import Generator
from datetime import date
from pathlib import Path

import pytest
from playwright.sync_api import Page

from movie_brain.domain.models import Film, OmdbRating
from movie_brain.infrastructure.database import Repository
from movie_brain.web.app import create_app

TODAY = date(2026, 8, 19)


FILMS = [
    Film("Alpha", 1950, "Ann", "https://c/alpha"),       # imdb 8.5 rt 95 English, leaving, rated by me 9
    Film("Bravo", 1960, "Bob", "https://c/bravo"),       # imdb 6.0 rt None French
    Film("Charlie", 1970, "Cy", "https://c/charlie"),    # unmatched
    Film("Delta", 1980, "Dee", "https://c/delta"),       # pending (no omdb row), the only "recently added"
    Film("Echo", 1990, "Ann", "https://c/echo"),         # imdb 7.0 rt 60 "English, Spanish", my rating 0
]


def seed(repo: Repository) -> None:
    films = FILMS
    # Old walk without Delta, then today's walk with all five → only Delta has first_seen = today.
    repo.record_catalog("criterion", [f for f in films if f.title != "Delta"], date(2026, 1, 1))
    repo.record_catalog("criterion", films, TODAY)
    ids = {f.key: repo.film_id_by_key(f.key) for f in films}
    repo.upsert_omdb(ids["alpha (1950)"], OmdbRating(8.5, 95, True, "English", '{"Title":"Alpha","Plot":"A plot.","Poster":"N/A","Ratings":[{"Source":"Internet Movie Database","Value":"8.5/10"}]}'), TODAY)
    repo.upsert_omdb(ids["bravo (1960)"], OmdbRating(6.0, None, True, "French", '{"Title":"Bravo"}'), TODAY)
    repo.upsert_omdb(ids["charlie (1970)"], OmdbRating(None, None, False), TODAY)
    repo.upsert_omdb(ids["echo (1990)"], OmdbRating(7.0, 60, True, "English, Spanish", '{"Title":"Echo"}'), TODAY)
    repo.set_leaving("criterion", {"alpha (1950)": "August 31"})
    repo.set_rating(ids["alpha (1950)"], 9, TODAY)
    repo.set_rating(ids["echo (1990)"], 0, TODAY)


@pytest.fixture(scope="session")
def seeded_repo(tmp_path_factory: pytest.TempPathFactory) -> Repository:
    db = tmp_path_factory.mktemp("web") / "movie-brain.db"
    repo = Repository(db)
    seed(repo)
    return repo


@pytest.fixture(scope="session")
def server(seeded_repo: Repository) -> Generator[str, None, None]:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    app = create_app(seeded_repo, today=lambda: TODAY)
    threading.Thread(target=lambda: app.run(host="127.0.0.1", port=port, use_reloader=False), daemon=True).start()
    time.sleep(0.5)
    yield f"http://127.0.0.1:{port}"


@pytest.fixture
def dash(page: Page, server: str) -> Page:
    page.goto(server)
    page.wait_for_selector("#films tbody[data-count]")
    return page
```
`tests/web/test_dashboard.py`:
```python
import re

from playwright.sync_api import Page, expect


def count(page: Page) -> int:
    return int(page.locator("#films tbody").get_attribute("data-count"))


def first_titles(page: Page, n: int) -> list[str]:
    return page.locator("#films tbody tr .c-title a").all_inner_texts()[:n]


def test_loads_all_films_default_sort_imdb_desc_nulls_last(dash: Page):
    assert count(dash) == 5
    assert first_titles(dash, 5) == ["Alpha", "Echo", "Bravo", "Charlie", "Delta"]
    expect(dash.locator("#count-films")).to_have_text("5")
    expect(dash.locator("#count-showing")).to_have_text("Showing 5 of 5")
    expect(dash.locator("#films tbody tr").first.locator(".c-title a")).to_have_attribute("href", "https://c/alpha")


def test_chips_stack_with_and(dash: Page):
    dash.click(".chip[data-chip=unrated]")
    assert count(dash) == 3  # Bravo, Charlie, Delta
    dash.click(".chip[data-chip=pending]")
    assert count(dash) == 2  # Charlie (unmatched), Delta (pending)
    expect(dash.locator(".chip[data-chip=unrated]")).to_have_class(re.compile("active"))
    dash.click("#chips-clear")
    assert count(dash) == 5


def test_each_chip_alone(dash: Page):
    expected = {"leaving": 1, "unrated": 3, "mine": 1, "not_interested": 1, "pending": 2, "top_rt": 1, "top_imdb": 1, "recent": 1}
    for chip, n in expected.items():
        dash.click(f".chip[data-chip={chip}]")
        assert count(dash) == n, chip
        dash.click(f".chip[data-chip={chip}]")


def test_sort_cycles_and_keeps_nulls_last(dash: Page):
    dash.click("th.sortable[data-col=rt]")
    assert first_titles(dash, 5) == ["Echo", "Alpha", "Bravo", "Charlie", "Delta"]  # asc: 60, 95, then nulls
    expect(dash.locator("th.sortable[data-col=rt]")).to_have_attribute("data-dir", "asc")
    dash.click("th.sortable[data-col=rt]")
    assert first_titles(dash, 2) == ["Alpha", "Echo"]
    dash.click("th.sortable[data-col=rt]")
    assert first_titles(dash, 2) == ["Alpha", "Echo"]  # back to default imdb desc
    expect(dash.locator("th.sortable[data-col=rt]")).not_to_have_attribute("data-dir", re.compile(".+"))


def test_column_filters_combine_with_chips(dash: Page):
    dash.fill("#f-director", "ann")
    assert count(dash) == 2  # Alpha, Echo
    dash.click(".chip[data-chip=not_interested]")
    assert count(dash) == 1
    assert first_titles(dash, 1) == ["Echo"]
    dash.click(".chip[data-chip=not_interested]")
    dash.fill("#f-director", "")
    dash.select_option("#f-lang", ["Spanish"])
    assert count(dash) == 1
    dash.select_option("#f-lang", [])
    dash.fill("#f-imdb-min", "7")
    assert count(dash) == 2  # Alpha 8.5, Echo 7.0; nulls excluded
    dash.fill("#f-year-max", "1955")
    assert count(dash) == 1


def test_url_state_round_trips(dash: Page, server: str):
    dash.click(".chip[data-chip=unrated]")
    dash.fill("#f-title", "a")
    dash.click("th.sortable[data-col=year]")
    url = dash.url
    assert "chips=unrated" in url and "title=a" in url
    assert ("sort=year%3Aasc" in url) or ("sort=year:asc" in url)
    dash.goto(url)
    dash.wait_for_selector("#films tbody[data-count]")
    expect(dash.locator(".chip[data-chip=unrated]")).to_have_class(re.compile("active"))
    expect(dash.locator("#f-title")).to_have_value("a")
    expect(dash.locator("th.sortable[data-col=year]")).to_have_attribute("data-dir", "asc")
    assert count(dash) == 3  # Bravo, Charlie, Delta contain "a"
```

- [ ] **Step 2: Run → FAIL** `uv run pytest tests/web/test_dashboard.py -q`

- [ ] **Step 3: Write `templates/index.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>movie-brain</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='app.css') }}">
</head>
<body>
  <header class="top">
    <h1>movie-brain</h1>
    <div id="counts">
      <span><b id="count-films">–</b> films</span>
      <span><b id="count-rated">–</b> rated</span>
      <span><b id="count-pending">–</b> pending</span>
      <span><b id="count-unmatched">–</b> unmatched</span>
      <span><b id="count-leaving">–</b> leaving soon</span>
      <span><b id="count-mine">–</b> rated by me</span>
      <span id="count-showing" class="showing"></span>
    </div>
    <div id="chips">
      <button class="chip" data-chip="leaving">Leaving soon</button>
      <button class="chip" data-chip="unrated">Unrated by me</button>
      <button class="chip" data-chip="mine">My ratings</button>
      <button class="chip" data-chip="not_interested">Not interested</button>
      <button class="chip" data-chip="pending">Pending / unmatched</button>
      <button class="chip" data-chip="top_rt">Top RT</button>
      <button class="chip" data-chip="top_imdb">Top IMDb</button>
      <button class="chip" data-chip="recent">Recently added</button>
      <button id="chips-clear" class="chip clear">Clear</button>
    </div>
  </header>

  <div class="table-wrap" id="table-wrap">
    <table id="films">
      <thead>
        <tr class="labels">
          <th class="sortable" data-col="title">Title</th>
          <th class="sortable" data-col="year">Year</th>
          <th class="sortable" data-col="director">Director</th>
          <th class="sortable" data-col="language">Language</th>
          <th class="sortable num" data-col="imdb">IMDb</th>
          <th class="sortable num" data-col="rt">RT</th>
          <th class="sortable" data-col="leaving_date">Leaving</th>
          <th class="sortable num" data-col="my_rating">My Rating</th>
          <th></th>
        </tr>
        <tr class="filters">
          <th><input id="f-title" type="search" placeholder="filter…"></th>
          <th><input id="f-year-min" type="number" placeholder="min" class="half"><input id="f-year-max" type="number" placeholder="max" class="half"></th>
          <th><input id="f-director" type="search" placeholder="filter…"></th>
          <th><select id="f-lang" multiple size="1"></select></th>
          <th><input id="f-imdb-min" type="number" step="0.1" placeholder="min" class="half"><input id="f-imdb-max" type="number" step="0.1" placeholder="max" class="half"></th>
          <th><input id="f-rt-min" type="number" placeholder="min" class="half"><input id="f-rt-max" type="number" placeholder="max" class="half"></th>
          <th></th><th></th><th></th>
        </tr>
      </thead>
      <tbody></tbody>
    </table>
  </div>

  <div id="drawer-backdrop" hidden></div>
  <aside id="drawer" hidden aria-label="Film details">
    <button id="drawer-close" aria-label="Close">✕</button>
    <div id="drawer-body"></div>
  </aside>
  <div id="toast" hidden></div>

  <script src="{{ url_for('static', filename='app.js') }}"></script>
</body>
</html>
```

- [ ] **Step 4: Write `static/app.css`**

```css
:root { --bg:#fff; --fg:#1b1b1b; --muted:#6b6b6b; --line:#e3e3e3; --accent:#b3261e; --chip:#f2f2f2; --chip-on:#1b1b1b; }
* { box-sizing: border-box; }
body { margin:0; font: 14px/1.4 -apple-system, system-ui, "Segoe UI", sans-serif; color:var(--fg); background:var(--bg); }
.top { position: sticky; top:0; background:var(--bg); border-bottom:1px solid var(--line); padding:10px 16px; z-index:2; }
.top h1 { margin:0 0 4px; font-size:18px; }
#counts span { margin-right:14px; color:var(--muted); }
#counts b { color:var(--fg); }
.showing { float:right; }
#chips { margin-top:8px; display:flex; flex-wrap:wrap; gap:6px; }
.chip { border:1px solid var(--line); background:var(--chip); border-radius:999px; padding:4px 10px; cursor:pointer; font:inherit; }
.chip.active { background:var(--chip-on); color:#fff; border-color:var(--chip-on); }
.chip.clear { background:transparent; }
.table-wrap { height: calc(100vh - 120px); overflow:auto; }
table { border-collapse:collapse; width:100%; }
thead th { position:sticky; background:var(--bg); text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); font-weight:600; white-space:nowrap; }
thead tr.labels th { top:0; }
thead tr.filters th { top:31px; padding:4px 8px; font-weight:normal; }
th.sortable { cursor:pointer; user-select:none; }
th.sortable[data-dir="asc"]::after { content:" ▲"; }
th.sortable[data-dir="desc"]::after { content:" ▼"; }
th.num, td.num { text-align:right; }
thead input, thead select { width:100%; font:inherit; padding:2px 4px; border:1px solid var(--line); border-radius:4px; }
thead input.half { width:48%; }
thead input.half + input.half { margin-left:4%; }
tbody tr { height:36px; cursor:pointer; }
tbody tr:hover { background:#fafafa; }
tbody td { padding:0 8px; border-bottom:1px solid var(--line); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:320px; }
tbody tr.spacer td { padding:0; border:0; }
td a { color:inherit; }
input.rating { width:3em; text-align:center; font:inherit; padding:2px; border:1px solid var(--line); border-radius:4px; }
input.rating.invalid { border-color:var(--accent); background:#fdecea; }
button.info { border:0; background:none; cursor:pointer; font-size:16px; }
#drawer-backdrop { position:fixed; inset:0; background:rgba(0,0,0,.3); z-index:3; }
#drawer { position:fixed; top:0; right:0; height:100vh; width:min(560px, 100vw); overflow:auto; background:var(--bg); z-index:4; box-shadow:-4px 0 16px rgba(0,0,0,.15); padding:16px 20px; }
#drawer-close { position:absolute; top:10px; right:12px; border:0; background:none; font-size:18px; cursor:pointer; }
#drawer img.poster { max-width:200px; float:right; margin:0 0 12px 12px; }
#drawer h2 { margin:0 0 4px; }
#drawer .meta { color:var(--muted); margin-bottom:10px; }
#drawer dl { display:grid; grid-template-columns:max-content 1fr; gap:4px 12px; margin:12px 0; }
#drawer dt { color:var(--muted); }
#drawer details pre { font-size:12px; background:#f6f6f6; padding:8px; overflow:auto; }
#toast { position:fixed; bottom:16px; left:50%; transform:translateX(-50%); background:var(--accent); color:#fff; padding:8px 14px; border-radius:6px; z-index:5; }
```

- [ ] **Step 5: Write `static/app.js`** (Task 12 adds the drawer and rating-commit pieces; leave the marked hooks in place)

```javascript
(() => {
  'use strict';
  const ROW_H = 36, OVERSCAN = 10;
  const COLS = ['title', 'year', 'director', 'language', 'imdb', 'rt', 'leaving_date', 'my_rating'];
  const state = {
    films: [], cfg: null, chips: new Set(),
    cols: { title: '', director: '', languages: new Set(), yearMin: null, yearMax: null, imdbMin: null, imdbMax: null, rtMin: null, rtMax: null },
    sort: null,            // {col, dir} or null = default
    filtered: [], openFilm: null,
  };
  const $ = (s) => document.querySelector(s);
  const tbody = $('#films tbody'), wrap = $('#table-wrap');

  // ---- canned predicates (mirror domain/filters.py; thresholds come from /api/config) ----
  const daysBetween = (a, b) => Math.round((new Date(b) - new Date(a)) / 86400000);
  const CHIP_PREDICATES = {
    leaving: (f) => f.leaving_date != null,
    unrated: (f) => f.my_rating == null,
    mine: (f) => f.my_rating != null && f.my_rating >= 1,
    not_interested: (f) => f.my_rating === 0,
    pending: (f) => f.pending || f.found === false,
    top_rt: (f) => f.rt != null && f.rt >= state.cfg.canned_thresholds.top_rt,
    top_imdb: (f) => f.imdb != null && f.imdb >= state.cfg.canned_thresholds.top_imdb,
    recent: (f) => f.first_seen != null && daysBetween(f.first_seen, state.cfg.today) <= state.cfg.canned_thresholds.recent_days,
  };

  // ---- filtering / sorting ----
  const inRange = (v, lo, hi) => v != null && (lo == null || v >= lo) && (hi == null || v <= hi);
  function rowMatches(f) {
    for (const c of state.chips) if (!CHIP_PREDICATES[c](f)) return false;
    const k = state.cols;
    if (k.title && !f.title.toLowerCase().includes(k.title)) return false;
    if (k.director && !(f.director || '').toLowerCase().includes(k.director)) return false;
    if (k.languages.size) {
      const langs = (f.language || '').split(',').map((s) => s.trim());
      if (![...k.languages].some((l) => langs.includes(l))) return false;
    }
    if ((k.yearMin != null || k.yearMax != null) && !inRange(f.year, k.yearMin, k.yearMax)) return false;
    if ((k.imdbMin != null || k.imdbMax != null) && !inRange(f.imdb, k.imdbMin, k.imdbMax)) return false;
    if ((k.rtMin != null || k.rtMax != null) && !inRange(f.rt, k.rtMin, k.rtMax)) return false;
    return true;
  }
  const byTitle = (a, b) => a.title.localeCompare(b.title, undefined, { sensitivity: 'base' });
  function compare(a, b) {
    if (!state.sort) {  // default: imdb desc, nulls last, then title
      if (a.imdb == null !== (b.imdb == null)) return a.imdb == null ? 1 : -1;
      if (a.imdb != null && a.imdb !== b.imdb) return b.imdb - a.imdb;
      return byTitle(a, b);
    }
    const { col, dir } = state.sort, va = a[col], vb = b[col];
    if (va == null || vb == null) return va == null && vb == null ? byTitle(a, b) : va == null ? 1 : -1;
    let c = typeof va === 'number' ? va - vb : String(va).localeCompare(String(vb), undefined, { sensitivity: 'base' });
    if (c === 0) c = byTitle(a, b);
    return dir === 'asc' ? c : -c;
  }
  function applyFilters() {
    state.filtered = state.films.filter(rowMatches).sort(compare);
    tbody.dataset.count = state.filtered.length;
    $('#count-showing').textContent = `Showing ${state.filtered.length} of ${state.films.length}`;
    renderRows();
    syncUrl();
  }

  // ---- summary (mirrors Repository.summary) ----
  function renderCounts() {
    const f = state.films;
    const n = (p) => f.filter(p).length;
    $('#count-films').textContent = f.length;
    $('#count-rated').textContent = n((x) => x.found === true);
    $('#count-pending').textContent = n((x) => x.pending);
    $('#count-unmatched').textContent = n((x) => x.found === false);
    $('#count-leaving').textContent = n((x) => x.leaving_date != null);
    $('#count-mine').textContent = n((x) => x.my_rating != null);
  }

  // ---- virtual-scrolled rows ----
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fmt = (v, suffix = '') => (v == null ? '—' : `${v}${suffix}`);
  function rowHtml(f) {
    const title = f.url ? `<a href="${esc(f.url)}" target="_blank" rel="noopener">${esc(f.title)}</a>` : esc(f.title);
    return `<tr data-id="${f.id}">
      <td class="c-title">${title}</td><td class="c-year">${fmt(f.year)}</td><td class="c-director">${esc(f.director) || '—'}</td>
      <td class="c-language">${esc(f.language) || '—'}</td><td class="c-imdb num">${f.imdb == null ? '—' : f.imdb.toFixed(1)}</td>
      <td class="c-rt num">${fmt(f.rt, '%')}</td><td class="c-leaving">${esc(f.leaving_date) || ''}</td>
      <td class="c-rating num"><input class="rating" maxlength="2" data-id="${f.id}" value="${f.my_rating ?? ''}" aria-label="My rating"></td>
      <td class="c-info"><button class="info" data-id="${f.id}" aria-label="Details">ⓘ</button></td></tr>`;
  }
  function renderRows() {
    const total = state.filtered.length;
    const start = Math.max(0, Math.floor(wrap.scrollTop / ROW_H) - OVERSCAN);
    const end = Math.min(total, Math.ceil((wrap.scrollTop + wrap.clientHeight) / ROW_H) + OVERSCAN);
    const top = start * ROW_H, bottom = (total - end) * ROW_H;
    tbody.innerHTML =
      (top ? `<tr class="spacer"><td colspan="9" style="height:${top}px"></td></tr>` : '') +
      state.filtered.slice(start, end).map(rowHtml).join('') +
      (bottom ? `<tr class="spacer"><td colspan="9" style="height:${bottom}px"></td></tr>` : '');
  }
  wrap.addEventListener('scroll', () => requestAnimationFrame(renderRows));

  // ---- URL state ----
  function syncUrl(push = false) {
    const p = new URLSearchParams();
    if (state.chips.size) p.set('chips', [...state.chips].join(','));
    const k = state.cols;
    if (k.title) p.set('title', k.title);
    if (k.director) p.set('director', k.director);
    if (k.languages.size) p.set('lang', [...k.languages].join('|'));
    for (const [name, lo, hi] of [['year', k.yearMin, k.yearMax], ['imdb', k.imdbMin, k.imdbMax], ['rt', k.rtMin, k.rtMax]]) {
      if (lo != null || hi != null) p.set(name, `${lo ?? ''}-${hi ?? ''}`);
    }
    if (state.sort) p.set('sort', `${state.sort.col}:${state.sort.dir}`);
    if (state.openFilm != null) p.set('film', state.openFilm);
    const qs = p.toString();
    history[push ? 'pushState' : 'replaceState'](null, '', qs ? `?${qs}` : location.pathname);
  }
  function readUrl() {
    const p = new URLSearchParams(location.search);
    state.chips = new Set((p.get('chips') || '').split(',').filter((c) => c in CHIP_PREDICATES));
    const k = state.cols;
    k.title = (p.get('title') || '').toLowerCase();
    k.director = (p.get('director') || '').toLowerCase();
    k.languages = new Set((p.get('lang') || '').split('|').filter(Boolean));
    const range = (name) => { const v = p.get(name); if (!v) return [null, null]; const [lo, hi] = v.split('-'); return [lo === '' ? null : +lo, hi === '' || hi == null ? null : +hi]; };
    [k.yearMin, k.yearMax] = range('year'); [k.imdbMin, k.imdbMax] = range('imdb'); [k.rtMin, k.rtMax] = range('rt');
    const s = p.get('sort');
    state.sort = s && COLS.includes(s.split(':')[0]) && ['asc', 'desc'].includes(s.split(':')[1]) ? { col: s.split(':')[0], dir: s.split(':')[1] } : null;
    const film = p.get('film');
    state.openFilm = film ? +film : null;
  }
  function writeControlsFromState() {
    document.querySelectorAll('.chip[data-chip]').forEach((b) => b.classList.toggle('active', state.chips.has(b.dataset.chip)));
    const k = state.cols;
    $('#f-title').value = k.title; $('#f-director').value = k.director;
    for (const o of $('#f-lang').options) o.selected = k.languages.has(o.value);
    const set = (id, v) => { $(id).value = v == null ? '' : v; };
    set('#f-year-min', k.yearMin); set('#f-year-max', k.yearMax); set('#f-imdb-min', k.imdbMin); set('#f-imdb-max', k.imdbMax); set('#f-rt-min', k.rtMin); set('#f-rt-max', k.rtMax);
    document.querySelectorAll('th.sortable').forEach((th) => {
      if (state.sort && th.dataset.col === state.sort.col) th.dataset.dir = state.sort.dir; else delete th.dataset.dir;
    });
  }

  // ---- controls ----
  $('#chips').addEventListener('click', (e) => {
    const b = e.target.closest('.chip'); if (!b) return;
    if (b.id === 'chips-clear') state.chips.clear();
    else if (state.chips.has(b.dataset.chip)) state.chips.delete(b.dataset.chip); else state.chips.add(b.dataset.chip);
    writeControlsFromState(); applyFilters();
  });
  document.querySelectorAll('th.sortable').forEach((th) => th.addEventListener('click', () => {
    const col = th.dataset.col;
    if (!state.sort || state.sort.col !== col) state.sort = { col, dir: 'asc' };
    else if (state.sort.dir === 'asc') state.sort = { col, dir: 'desc' };
    else state.sort = null;
    writeControlsFromState(); applyFilters();
  }));
  const num = (id) => { const v = $(id).value.trim(); return v === '' ? null : Number(v); };
  function readControls() {
    const k = state.cols;
    k.title = $('#f-title').value.trim().toLowerCase();
    k.director = $('#f-director').value.trim().toLowerCase();
    k.languages = new Set([...$('#f-lang').selectedOptions].map((o) => o.value));
    k.yearMin = num('#f-year-min'); k.yearMax = num('#f-year-max');
    k.imdbMin = num('#f-imdb-min'); k.imdbMax = num('#f-imdb-max');
    k.rtMin = num('#f-rt-min'); k.rtMax = num('#f-rt-max');
    applyFilters();
  }
  document.querySelectorAll('thead tr.filters input, thead tr.filters select').forEach((el) => {
    el.addEventListener('input', readControls);
    el.addEventListener('change', readControls);
  });
  function populateLanguages() {
    const langs = new Set();
    state.films.forEach((f) => (f.language || '').split(',').map((s) => s.trim()).filter(Boolean).forEach((l) => langs.add(l)));
    $('#f-lang').innerHTML = [...langs].sort().map((l) => `<option value="${esc(l)}">${esc(l)}</option>`).join('');
  }

  // ---- rating + drawer hooks (implemented in Task 12) ----
  window.MB = { state, applyFilters, render: renderRows, renderCounts, rowHtml };

  // ---- boot ----
  async function boot() {
    const [cfg, films] = await Promise.all([fetch('/api/config').then((r) => r.json()), fetch('/api/films').then((r) => r.json())]);
    state.cfg = cfg; state.films = films;
    populateLanguages();
    readUrl();
    writeControlsFromState();
    renderCounts();
    applyFilters();
    if (window.MB.onBoot) window.MB.onBoot();
  }
  boot();
})();
```

- [ ] **Step 6: Run → PASS** `uv run pytest tests/web -q`. If the `#f-lang` multi-select is awkward to drive, `select_option` with a list works on `<select multiple>`; keep `size="1"` so it reads as a compact dropdown. `uv run ruff check . && uv run mypy` (JS not linted).

- [ ] **Step 7: Commit** — `git add -A && git commit -m "Add dashboard table with stacking chips, column filters, sort and URL state"`

---

### Task 12: Detail drawer + inline rating entry

**Files:**
- Modify: `src/movie_brain/web/static/app.js` (append the drawer/rating section before `// ---- boot ----`), `tests/web/test_dashboard.py` (append tests)

**Interfaces:**
- Consumes: `GET /api/films/<id>`, `PUT /api/films/<id>/rating`, DOM contract from Task 11.
- Produces: `#drawer` (shown when open) with `#drawer-body h2`, `.meta`, `img.poster` (when poster URL not `N/A`), `dl` of detail fields, `ul.sources`, `a.criterion`, `input.rating[data-id]`, `details > pre.raw`; `?film=<id>` URL param; `#toast` for errors.

- [ ] **Step 1: Failing tests** — append to `tests/web/test_dashboard.py`

```python
def test_drawer_opens_from_info_button_and_restores_url(dash: Page):
    dash.click("#films tbody tr[data-id] .info >> nth=0")
    drawer = dash.locator("#drawer")
    expect(drawer).to_be_visible()
    expect(drawer.locator("h2")).to_have_text("Alpha")
    expect(drawer.locator("pre.raw")).to_contain_text('"Plot": "A plot."')
    expect(drawer.locator("a.criterion")).to_have_attribute("href", "https://c/alpha")
    assert "film=" in dash.url
    dash.keyboard.press("Escape")
    expect(drawer).to_be_hidden()
    assert "film=" not in dash.url


def test_drawer_opens_on_load_from_url(dash: Page, server: str):
    fid = dash.locator("#films tbody tr[data-id]").first.get_attribute("data-id")
    dash.goto(f"{server}/?film={fid}")
    expect(dash.locator("#drawer h2")).to_have_text("Alpha")
    dash.click("#drawer-backdrop", position={"x": 10, "y": 10})
    expect(dash.locator("#drawer")).to_be_hidden()


def test_row_click_opens_drawer_but_title_link_does_not(dash: Page):
    dash.click("#films tbody tr[data-id] .c-year >> nth=1")
    expect(dash.locator("#drawer h2")).to_have_text("Echo")
    dash.click("#drawer-close")
    expect(dash.locator("#drawer")).to_be_hidden()


def test_rating_round_trip_updates_counts_and_persists(dash: Page, server: str):
    row = dash.locator("#films tbody tr[data-id]").filter(has_text="Bravo")
    expect(dash.locator("#count-mine")).to_have_text("2")
    row.locator("input.rating").fill("7")
    row.locator("input.rating").press("Enter")
    expect(dash.locator("#count-mine")).to_have_text("3")
    dash.reload()
    dash.wait_for_selector("#films tbody[data-count]")
    expect(dash.locator("#films tbody tr[data-id]").filter(has_text="Bravo").locator("input.rating")).to_have_value("7")
    # blank un-rates
    row = dash.locator("#films tbody tr[data-id]").filter(has_text="Bravo")
    row.locator("input.rating").fill("")
    row.locator("input.rating").press("Enter")
    expect(dash.locator("#count-mine")).to_have_text("2")


def test_invalid_rating_reverts(dash: Page):
    row = dash.locator("#films tbody tr[data-id]").filter(has_text="Alpha")
    inp = row.locator("input.rating")
    inp.fill("12")
    inp.press("Enter")
    expect(inp).to_have_value("9")
    expect(dash.locator("#count-mine")).to_have_text("2")


def test_drawer_rating_input_also_works(dash: Page):
    dash.click("#films tbody tr[data-id] .info >> nth=0")  # Alpha
    inp = dash.locator("#drawer input.rating")
    inp.fill("10")
    inp.press("Enter")
    expect(dash.locator("#films tbody tr[data-id]").filter(has_text="Alpha").locator("input.rating")).to_have_value("10")
    inp.fill("9")
    inp.press("Enter")  # restore seed value for other tests
```

Ordering note: Playwright tests share one seeded server; each rating test restores the seed value it changed. `test_rating_round_trip…` leaves Bravo unrated (as seeded).

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement in `app.js`** (insert before `// ---- boot ----`, replacing the `window.MB = …` line with the one at the end of this block)

```javascript
  // ---- toast ----
  let toastTimer;
  function toast(msg) {
    const t = $('#toast'); t.textContent = msg; t.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, 3000);
  }

  // ---- rating entry ----
  function parseScore(text) {
    const s = text.trim();
    if (s === '') return { ok: true, score: null };
    if (!/^\d{1,2}$/.test(s)) return { ok: false };
    const n = Number(s);
    return n >= 0 && n <= 10 ? { ok: true, score: n } : { ok: false };
  }
  function updateFilmLocal(updated) {
    const i = state.films.findIndex((f) => f.id === updated.id);
    if (i >= 0) state.films[i] = updated;
    renderCounts(); applyFilters();
    document.querySelectorAll(`input.rating[data-id="${updated.id}"]`).forEach((el) => { el.value = updated.my_rating ?? ''; });
  }
  async function commitRating(input) {
    const id = +input.dataset.id;
    const film = state.films.find((f) => f.id === id);
    const current = film && film.my_rating != null ? String(film.my_rating) : '';
    const parsed = parseScore(input.value);
    if (!parsed.ok) {
      input.classList.add('invalid'); input.value = current;
      setTimeout(() => input.classList.remove('invalid'), 800);
      return;
    }
    if (input.value.trim() === current) return;
    try {
      const r = await fetch(`/api/films/${id}/rating`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ score: parsed.score }) });
      if (!r.ok) throw new Error((await r.json()).error || r.statusText);
      updateFilmLocal(await r.json());
    } catch (err) {
      input.value = current; toast(`Could not save rating: ${err.message}`);
    }
  }
  document.addEventListener('keydown', (e) => { if (e.key === 'Enter' && e.target.matches('input.rating')) e.target.blur(); });
  document.addEventListener('focusout', (e) => { if (e.target.matches('input.rating')) commitRating(e.target); });

  // ---- drawer ----
  const drawer = $('#drawer'), backdrop = $('#drawer-backdrop'), body = $('#drawer-body');
  function detailHtml(d) {
    const p = d.payload || {};
    const poster = p.Poster && p.Poster !== 'N/A' ? `<img class="poster" src="${esc(p.Poster)}" alt="">` : '';
    const fields = [['Genre', p.Genre], ['Runtime', p.Runtime], ['Rated', p.Rated], ['Country', p.Country], ['Language', d.language], ['Awards', p.Awards], ['Cast', p.Actors], ['Writer', p.Writer]]
      .filter(([, v]) => v && v !== 'N/A').map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join('');
    const sources = (p.Ratings || []).map((r) => `<li>${esc(r.Source)}: ${esc(r.Value)}</li>`).join('');
    return `${poster}<h2>${esc(d.title)}</h2>
      <div class="meta">${fmt(d.year)} · ${esc(d.director) || '—'}${d.leaving_date ? ` · <b>Leaving ${esc(d.leaving_date)}</b>` : ''}</div>
      ${p.Plot && p.Plot !== 'N/A' ? `<p>${esc(p.Plot)}</p>` : ''}
      <dl>${fields}</dl>
      ${sources ? `<ul class="sources">${sources}</ul>` : d.pending ? '<p class="meta">OMDb lookup pending.</p>' : d.found === false ? '<p class="meta">No OMDb match.</p>' : ''}
      <p>${d.url ? `<a class="criterion" href="${esc(d.url)}" target="_blank" rel="noopener">Open on Criterion ↗</a>` : ''}
        &nbsp; My rating: <input class="rating" maxlength="2" data-id="${d.id}" value="${d.my_rating ?? ''}" aria-label="My rating"></p>
      <details><summary>Raw OMDb payload</summary><pre class="raw">${esc(d.payload ? JSON.stringify(d.payload, null, 2) : 'null')}</pre></details>`;
  }
  async function openDrawer(id) {
    const r = await fetch(`/api/films/${id}`);
    if (!r.ok) { toast('Film not found'); return; }
    body.innerHTML = detailHtml(await r.json());
    drawer.hidden = false; backdrop.hidden = false;
    state.openFilm = id; syncUrl(true);
  }
  function closeDrawer() {
    if (drawer.hidden) return;
    drawer.hidden = true; backdrop.hidden = true; body.innerHTML = '';
    state.openFilm = null; syncUrl(true);
  }
  tbody.addEventListener('click', (e) => {
    if (e.target.closest('a, input')) return;
    const tr = e.target.closest('tr[data-id]'); if (tr) openDrawer(+tr.dataset.id);
  });
  $('#drawer-close').addEventListener('click', closeDrawer);
  backdrop.addEventListener('click', closeDrawer);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeDrawer(); });
  window.addEventListener('popstate', () => { readUrl(); writeControlsFromState(); applyFilters(); if (state.openFilm != null) openDrawer(state.openFilm); else closeDrawer(); });

  window.MB = { state, applyFilters, render: renderRows, renderCounts, rowHtml, onBoot: () => { if (state.openFilm != null) openDrawer(state.openFilm); } };
```

Filter/sort changes use `replaceState` (no history spam); opening/closing the drawer uses `pushState` (`syncUrl(true)`) so the browser Back button closes/reopens it via the `popstate` handler.

- [ ] **Step 4: Run → PASS** `uv run pytest tests/web -q`, then full suite `uv run pytest -q && uv run ruff check . && uv run mypy`.

- [ ] **Step 5: Commit** — `git add -A && git commit -m "Add film detail drawer and typed inline rating entry"`

---

### Task 13: launchd schedule, README, CLAUDE.md, legacy hand-off

**Files:**
- Create: `launchd/com.jayers.movie-brain.plist.template`, `scripts/install-launch-agent.sh`, `CLAUDE.md`
- Modify: `README.md`
- Test: `tests/unit/test_schedule.py`

- [ ] **Step 1: Failing test** — `tests/unit/test_schedule.py`

```python
import plistlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_plist_template_runs_sync_at_3am():
    text = (ROOT / "launchd" / "com.jayers.movie-brain.plist.template").read_text()
    data = plistlib.loads(text.replace("__REPO__", "/r").replace("__CONFIG_DIR__", "/c").encode())
    assert data["Label"] == "com.jayers.movie-brain"
    assert data["ProgramArguments"] == ["/r/.venv/bin/movie-brain", "sync"]
    assert data["StartCalendarInterval"] == {"Hour": 3, "Minute": 0}
    assert data["StandardOutPath"] == "/c/sync.log" and data["StandardErrorPath"] == "/c/sync.log"


def test_install_script_is_executable_and_uses_config_dir():
    script = ROOT / "scripts" / "install-launch-agent.sh"
    assert script.stat().st_mode & 0o111
    body = script.read_text()
    assert "MOVIE_BRAIN_CONFIG_DIR" in body and "com.jayers.movie-brain.plist" in body
```

- [ ] **Step 2: Write the template and script**

`launchd/com.jayers.movie-brain.plist.template`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.jayers.movie-brain</string>
  <key>ProgramArguments</key>
  <array>
    <string>__REPO__/.venv/bin/movie-brain</string>
    <string>sync</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>3</integer>
    <key>Minute</key><integer>0</integer>
  </dict>
  <key>StandardOutPath</key><string>__CONFIG_DIR__/sync.log</string>
  <key>StandardErrorPath</key><string>__CONFIG_DIR__/sync.log</string>
</dict>
</plist>
```

`scripts/install-launch-agent.sh` (then `chmod +x`):
```bash
#!/usr/bin/env bash
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG_DIR="${MOVIE_BRAIN_CONFIG_DIR:-$HOME/.config/movie-brain}"
PLIST="$HOME/Library/LaunchAgents/com.jayers.movie-brain.plist"
mkdir -p "$CONFIG_DIR" "$HOME/Library/LaunchAgents"
if [ ! -f "$CONFIG_DIR/omdb-api-key.txt" ] && [ -z "${OMDB_API_KEY:-}" ]; then
  echo "First: put your OMDb API key in $CONFIG_DIR/omdb-api-key.txt (free at omdbapi.com/apikey.aspx)" >&2
  exit 1
fi
sed -e "s|__REPO__|$REPO|g" -e "s|__CONFIG_DIR__|$CONFIG_DIR|g" \
  "$REPO/launchd/com.jayers.movie-brain.plist.template" > "$PLIST"
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "Loaded. Daily sync: 3:00 AM. Log: $CONFIG_DIR/sync.log"
```

- [ ] **Step 3: README.md**

Sections: what it is (one paragraph), Setup (`uv sync`, OMDb key to `~/.config/movie-brain/omdb-api-key.txt` or `OMDB_API_KEY`, `uv run movie-brain import-legacy` if migrating from criterion-ratings, `scripts/install-launch-agent.sh`), Commands table (`sync [--full|--ratings-only]`, `dashboard [--port 5556]`, `import-legacy [--from DIR]`, `export csv PATH`, `status`), Dashboard (chips stack with AND; column filters; click header to sort; type 0–10 in My Rating, blank to un-rate, 0 = not interested; click a row for the detail drawer; URL is shareable), Data (`~/.config/movie-brain/movie-brain.db`, tables one line each), Tripwires (ported text from criterion-ratings README), Migrating from criterion-ratings (run `import-legacy`, verify counts against `status`, then `launchctl unload` the old `com.jayers.criterion-ratings` agent — **do not** delete the old data dir until you're satisfied), Development (`uv run pytest`, `uv run playwright install chromium` once, `uv run ruff check . && uv run mypy`).

- [ ] **Step 4: CLAUDE.md** (project-level, mirrors yt-brain's shape)

```markdown
# movie-brain

Personal film brain: Criterion Channel listings + OMDb ratings + my ratings in SQLite, with a local Flask dashboard. Successor to criterion-ratings; Apple Movies etc. may be added as further `listings.source` values.

## Commands
uv run movie-brain sync [--full|--ratings-only] · dashboard [--port 5556] · import-legacy [--from DIR] · export csv PATH · status

## Architecture (hexagonal)
- `domain/` — models (`Film`, `OmdbRating`, `FilmView`), canned-filter predicates. Imports nothing else.
- `application/` — sync, ratings, export, legacy_import. Talk to `Repository`.
- `infrastructure/` — config, SQLite `Repository` + `migrations/`, Criterion + OMDb HTTP adapters.
- `web/` — Flask `create_app(repo)`, one template, vanilla JS (`static/app.js`) does filter/sort client-side.

## Rules
- Canned-filter thresholds live ONLY in `domain/filters.py`; JS reads them from `/api/config`. Keep `CHIP_PREDICATES` in app.js in lockstep with `_PREDICATES`.
- Film identity = `film_key(title, year)`; never derive ids any other way.
- Never delete from `listings`; "current" = latest `last_seen` per source.
- New schema change → new `migrations/NNN_*.sql` that also inserts its `schema_version` row.
- Tests: `uv run pytest` (unit + pytest-bdd + Flask client + Playwright; `uv run playwright install chromium` once). Lint: `uv run ruff check . && uv run mypy`.

## Data
`~/.config/movie-brain/movie-brain.db` (override with `MOVIE_BRAIN_CONFIG_DIR`). OMDb key: `OMDB_API_KEY` or `<config_dir>/omdb-api-key.txt`. Logs: `<config_dir>/sync.log`.
```

- [ ] **Step 5: Run tests → PASS; commit** — `uv run pytest -q && uv run ruff check . && uv run mypy` then `git add -A && git commit -m "Add launchd schedule, README and CLAUDE.md"`

- [ ] **Step 6: Real-data smoke (manual, not automated)**

```bash
cd ~/code/movie-brain
uv run movie-brain import-legacy          # expect ~3000 films, ~2500 payloads, your annotations
uv run movie-brain status
uv run movie-brain dashboard               # open http://127.0.0.1:5556, try chips/sort/drawer/rate
```
Report the counts. Do **not** unload the old launch agent or touch the legacy data dir — that hand-off is the user's call.

---

## Self-review notes

- **Spec coverage:** layout/CLI (T1, T9), data model + import (T3, T7), sync incl. tripwires + `first_seen`/`last_seen`/leaving (T6), chips + column filters + sort + URL state + virtual scroll (T11), typed rating input in table and drawer, drawer with poster/plot/fields/sources/Criterion link/raw JSON, `pushState` (T12), API incl. `/api/config` (T10), CSV export (T8), launchd/README/CLAUDE.md (T13), testing pyramid (every task). Markdown report intentionally absent.
- **Deviations from spec, called out:** domain uses dataclasses not pydantic; `/api/config` nests `recent_days` inside `canned_thresholds` and adds `today`; `list_views` returns only *current* films (latest walk) — departed films keep their rows but aren't shown.
- **Type consistency check:** `Repository` method names used in T6–T12 match T3 (+`record_catalog` added in T6). `SyncResult` fields match between T6 impl and T9 test. `FilmView` field names match `to_dict()` keys used by `app.js` (`leaving_date`, `first_seen`, `my_rating`, `pending`, `found`).
