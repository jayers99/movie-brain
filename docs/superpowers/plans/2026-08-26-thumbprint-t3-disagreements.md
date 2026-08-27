# Thumbprint T3 — migrate guard + repair disagreements + article-insensitive titles — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** No verb migrates the live DB implicitly; the 94 OMDb/TMDB key disagreements are repaired from eval group D (verified rows applied, proposed rows queued as A/B/C reviews); an article-insensitive title level is measured before adoption.

**Architecture:** Hexagonal — SQL only in `infrastructure/database.py`, verdict logic in `application/repair.py` (same dry-run/apply/confirm protocol as `repair editions`), Typer wiring in `cli.py`, resolver signal change in `domain/thumbprint.py`. The resolver stays DARK (no ingester calls it); `repair disagreements` calls it only to render review candidates.

**Tech Stack:** Python 3.12, uv, sqlite3, Typer, pytest (+pytest-bdd for step_defs), ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-08-26-thumbprint-t3-disagreements-design.md`

## Global Constraints

- Gates after EVERY task: `uv run pytest`, `uv run ruff check .`, `uv run mypy`, `uv run python scripts/thumbprint_benchmark.py --assert` (baseline **n=484 / 0 wrong / 94.8 %**), `uv run python scripts/matching_benchmark.py --assert-dominance`.
- `scripts/eval/thumbprint_eval_v1.csv` is never edited by hand; `eval_log.ratify` is the only writer.
- Resolver stays dark: nothing in `application/sync.py`, `availability.py`, `metacritic.py`, `owned.py` may call `resolve()`.
- Reason strings in `domain/thumbprint.resolve()` are contract — never reword; C adds none.
- **`MOVIE_BRAIN_CONFIG_DIR` must be exported before ANY `movie-brain` command outside pytest** (subagents included). Tests use `config_dir`/`tmp_path` fixtures only.
- The verb never writes `films.year` / `films.key` / `films.title` itself; year changes go only through `record_tmdb_match` (commerce guard).
- Commits: brief single line, "why" over "what". Branch: `feature/T3-thumbprint-disagreements`.
- Log every `[verdict]` line through the injected `log` (CLI passes `_plain`), never `print`.

---

## File map

| file | responsibility |
|---|---|
| `src/movie_brain/infrastructure/database.py` | `PendingMigrations`, `init_db(path, *, apply=False)`, `Repository(path, *, migrate=False)`, `pending_migrations(path)`, `DisagreementFilm` + `key_disagreements()`, `omdb_imdb_id()` |
| `src/movie_brain/application/repair.py` | `DisagreementContract`, `load_disagreement_contract`, `DisagreementGroup`, `DisagreementsReport`, `audit_disagreements`, `format_disagreement`, `repair_disagreements` |
| `src/movie_brain/application/review.py` | refresh a found-but-wrong OMDb stub after `--pick/--tt` |
| `src/movie_brain/domain/thumbprint.py` | `strip_article`, article-insensitive tier in `title_level` |
| `src/movie_brain/infrastructure/thumbprint_fetch.py` | `plausible()` treats article-stripped forms as exact |
| `src/movie_brain/cli.py` | `migrate [--apply]`, `_repo()` guard, `repair disagreements` |
| tests | `tests/unit/test_database.py`, `tests/unit/test_repair_disagreements.py` (new), `tests/unit/test_cli.py`, `tests/unit/test_thumbprint.py`, `tests/unit/test_thumbprint_fetch.py`, `tests/step_defs/test_review.py` + `tests/features/review.feature` |
| docs | `CLAUDE.md`, `.claude/rules/thumbprint.md`, handoff status note |

---

### Task 1: migrate guard — `init_db` refuses pending migrations unless asked

**Files:**
- Modify: `src/movie_brain/infrastructure/database.py:131-147` (`init_db`), `:317-319` (`Repository.__init__`)
- Test: `tests/unit/test_database.py`

**Interfaces:**
- Produces: `class PendingMigrations(RuntimeError)` with `.pending: list[str]` (file names); `def pending_migrations(db_path: Path) -> list[str]`; `def init_db(db_path: Path, *, apply: bool = False) -> None`; `Repository(db_path, *, migrate: bool = False)`.
- Rule: a DB whose file does not exist or has no `schema_version` table bootstraps fully regardless of `apply` (creation is not migration). An existing versioned DB with pending files raises unless `apply=True`.

- [ ] **Step 1: Write the failing tests** (append to `tests/unit/test_database.py`)

```python
def _pretend_one_behind(tmp_path, monkeypatch):
    """Point MIGRATIONS_DIR at a copy with one extra migration so the DB is 'behind'."""
    import shutil

    from movie_brain.infrastructure import database as dbmod

    src = dbmod.MIGRATIONS_DIR
    copy = tmp_path / "migrations"
    shutil.copytree(src, copy)
    n = max(int(p.name.split("_")[0]) for p in copy.glob("*.sql")) + 1
    (copy / f"{n:03d}_t3_probe.sql").write_text(
        f"CREATE TABLE t3_probe (x INTEGER); INSERT INTO schema_version (version) VALUES ({n});"
    )
    monkeypatch.setattr(dbmod, "MIGRATIONS_DIR", copy)
    return n


def test_fresh_db_bootstraps_without_apply(tmp_path):
    p = tmp_path / "fresh.db"
    init_db(p)  # no flag: creation is allowed
    assert Repository(p).summary("criterion")["films"] == 0


def test_existing_db_with_pending_migration_raises(tmp_path, monkeypatch):
    from movie_brain.infrastructure.database import PendingMigrations, pending_migrations

    p = tmp_path / "live.db"
    init_db(p)
    n = _pretend_one_behind(tmp_path, monkeypatch)
    assert pending_migrations(p) == [f"{n:03d}_t3_probe.sql"]
    with pytest.raises(PendingMigrations) as exc:
        Repository(p)
    assert exc.value.pending == [f"{n:03d}_t3_probe.sql"]
    # nothing was written
    with sqlite3.connect(p) as c:
        assert c.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == n - 1


def test_apply_migrates_and_backs_up(tmp_path, monkeypatch):
    p = tmp_path / "live.db"
    init_db(p)
    n = _pretend_one_behind(tmp_path, monkeypatch)
    init_db(p, apply=True)
    with sqlite3.connect(p) as c:
        assert c.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == n
    assert list((tmp_path / "backups").glob(f"live-v{n - 1}-*.db"))
    assert Repository(p, migrate=True) is not None  # idempotent
```

(`sqlite3` and `pytest` are already imported at the top of that test module — check with `grep -n "^import" tests/unit/test_database.py`; add if missing.)

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_database.py -k "bootstraps or pending_migration or backs_up" -v`
Expected: FAIL — `ImportError: cannot import name 'PendingMigrations'` / `TypeError: init_db() got an unexpected keyword argument 'apply'`.

- [ ] **Step 3: Implement**

Replace `init_db` in `database.py`:

```python
class PendingMigrations(RuntimeError):
    """An existing DB is behind the checked-in migrations; only `migrate --apply` may advance it."""

    def __init__(self, pending: list[str]) -> None:
        self.pending = pending
        super().__init__("pending migrations: " + ", ".join(pending) + " — run 'movie-brain migrate --apply'")


def _applied_versions(conn: sqlite3.Connection) -> set[int] | None:
    """Applied schema versions, or None when the DB has never been initialised."""
    has_versions = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_version'"
    ).fetchone()
    if not has_versions:
        return None
    return {int(r[0]) for r in conn.execute("SELECT version FROM schema_version")}


def _pending_files(applied: set[int]) -> list[Path]:
    return [m for m in sorted(MIGRATIONS_DIR.glob("*.sql")) if int(m.name.split("_")[0]) not in applied]


def pending_migrations(db_path: Path) -> list[str]:
    """Migration file names an existing DB still lacks (empty for a fresh or current DB)."""
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        applied = _applied_versions(conn)
        return [] if applied is None else [m.name for m in _pending_files(applied)]
    finally:
        conn.close()


def init_db(db_path: Path, *, apply: bool = False) -> None:
    """Create a fresh DB in full, or bring an existing one up to date ONLY when `apply` is set.

    Creation is not migration: a DB with no `schema_version` table (first run, tests, a
    scratch copy) bootstraps regardless. An existing DB behind the checked-in migrations
    raises `PendingMigrations` so no ordinary verb can advance the live schema as a side
    effect of merely opening the repository (a T2 subagent did exactly that)."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        applied = _applied_versions(conn)
        pending = _pending_files(applied or set())
        if applied is not None and pending and not apply:
            raise PendingMigrations([m.name for m in pending])
        if pending and applied:
            _backup_pre_migration(conn, db_path, max(applied))
        for mig in pending:
            conn.executescript(mig.read_text())
        conn.commit()
    finally:
        conn.close()
```

And `Repository.__init__`:

```python
    def __init__(self, db_path: Path, *, migrate: bool = False) -> None:
        self.db_path = db_path
        init_db(db_path, apply=migrate)
```

- [ ] **Step 4: Run the whole suite** — `uv run pytest -q` (every fixture creates fresh DBs → still green). Then ruff + mypy.

- [ ] **Step 5: Commit** — `git commit -am "init_db: an existing DB never migrates implicitly — PendingMigrations unless apply=True"`

---

### Task 2: CLI `migrate [--apply]` and the guard in `_repo()`

**Files:**
- Modify: `src/movie_brain/cli.py:69-72` (`_repo`), add `migrate` command near `status`
- Test: `tests/unit/test_cli.py`

**Interfaces:**
- Consumes: `PendingMigrations`, `pending_migrations`, `init_db(apply=True)` from Task 1.
- Produces: `movie-brain migrate` (dry: prints applied max + pending names, exit 0) / `movie-brain migrate --apply`; every other verb exits 2 with the hint when behind.

- [ ] **Step 1: Failing tests** (append to `tests/unit/test_cli.py`; reuse `runner`, `app`, `config_dir` already there; `_pretend_one_behind` — copy the helper from Task 1 into this module or import it from `tests.unit.test_database` if the tests package allows; copy is fine)

```python
def test_status_refuses_a_db_that_is_behind(config_dir, tmp_path, monkeypatch):
    from movie_brain.infrastructure.database import init_db

    init_db(config_dir / "movie-brain.db")
    _pretend_one_behind(tmp_path, monkeypatch)
    r = runner.invoke(app, ["status"])
    assert r.exit_code == 2
    assert "movie-brain migrate --apply" in r.output


def test_migrate_dry_run_lists_pending_then_apply(config_dir, tmp_path, monkeypatch):
    from movie_brain.infrastructure.database import init_db, pending_migrations

    init_db(config_dir / "movie-brain.db")
    n = _pretend_one_behind(tmp_path, monkeypatch)
    r = runner.invoke(app, ["migrate"])
    assert r.exit_code == 0 and f"{n:03d}_t3_probe.sql" in r.output and "--apply" in r.output
    assert pending_migrations(config_dir / "movie-brain.db")  # dry run wrote nothing
    r = runner.invoke(app, ["migrate", "--apply"])
    assert r.exit_code == 0 and pending_migrations(config_dir / "movie-brain.db") == []
    assert runner.invoke(app, ["status"]).exit_code == 0


def test_migrate_on_current_db_says_so(config_dir):
    r = runner.invoke(app, ["migrate"])
    assert r.exit_code == 0 and "up to date" in r.output
```

- [ ] **Step 2: Run** — `uv run pytest tests/unit/test_cli.py -k "behind or migrate" -v` → FAIL (`No such command 'migrate'`; status exits 1 with a traceback).

- [ ] **Step 3: Implement** in `cli.py`

```python
from movie_brain.infrastructure.database import PendingMigrations, Repository, init_db, pending_migrations


def _repo() -> Repository:
    cfg = load_config()
    cfg.config_dir.mkdir(parents=True, exist_ok=True)
    try:
        return Repository(cfg.db_path)
    except PendingMigrations as exc:
        err.print(str(exc))
        raise typer.Exit(2) from exc


@app.command("migrate")
def migrate_cmd(
    apply: Annotated[bool, typer.Option("--apply", help="Apply pending migrations (backs up first).")] = False,
) -> None:
    """The ONLY path that advances an existing DB's schema; without --apply it just lists what is pending."""
    cfg = load_config()
    pending = pending_migrations(cfg.db_path)
    if not pending:
        console.print("schema up to date")
        return
    for name in pending:
        console.print(f"pending: {name}")
    if not apply:
        console.print("dry run — re-run with --apply to migrate (a backup lands in backups/ first)")
        return
    init_db(cfg.db_path, apply=True)
    console.print(f"applied {len(pending)} migration(s)")
```

- [ ] **Step 4: Run** the three tests, then full gates.

- [ ] **Step 5: Commit** — `git commit -am "migrate verb: the one explicit path to advance the live schema; every other verb refuses when behind"`

---

### Task 3: Repository — `key_disagreements()` and `omdb_imdb_id()`

**Files:**
- Modify: `src/movie_brain/infrastructure/database.py` (NamedTuple near `TwinFilm`/`EditionFilm`; methods near `films_for_editions`)
- Test: `tests/unit/test_database.py`

**Interfaces (Produces):**

```python
class DisagreementFilm(NamedTuple):
    id: int
    title: str
    year: int | None
    omdb_tt: str          # OMDb payload imdbID (found=1 only)
    tmdb_tt: str          # COALESCE(external imdb, tmdb_facts.imdb_id)
    tmdb_id: str | None   # external tmdb
    imdb_ext: str | None  # external imdb (raw, may be None)
    criterion: bool       # has any criterion listing

Repository.key_disagreements() -> list[DisagreementFilm]   # undisposed, OMDb found, omdb_tt != tmdb_tt, ordered by id
Repository.omdb_imdb_id(film_id) -> str | None              # payload imdbID when found=1, else None
```

- [ ] **Step 1: Failing test**

```python
def test_key_disagreements_lists_only_split_keys(repo, today):
    from movie_brain.domain.models import Film

    agree = repo.create_film(Film("Agree", 2000, None, ""))
    split = repo.create_film(Film("Split", 2001, None, ""))
    nostub = repo.create_film(Film("No Stub", 2002, None, ""))
    for fid, tt in ((agree, "tt1"), (split, "tt2")):
        repo.upsert_omdb(fid, _found_rating(tt), today)  # helper below
    repo.set_external_id(agree, "tmdb", "10", today)
    repo.set_external_id(split, "tmdb", "20", today)
    repo.upsert_tmdb_facts(agree, _facts(10, "tt1"), today)
    repo.upsert_tmdb_facts(split, _facts(20, "tt9"), today)
    repo.upsert_tmdb_facts(nostub, _facts(30, "tt3"), today)
    rows = repo.key_disagreements()
    assert [(r.id, r.omdb_tt, r.tmdb_tt, r.tmdb_id, r.criterion) for r in rows] == [(split, "tt2", "tt9", "20", False)]
    assert repo.omdb_imdb_id(split) == "tt2" and repo.omdb_imdb_id(nostub) is None
    # an external imdb id wins over tmdb_facts
    repo.set_external_id(split, "imdb", "tt2", today)
    assert repo.key_disagreements() == []
```

Look at how existing tests in `tests/unit/test_database.py` build an OMDb `Rating`/payload and a `TmdbFactsRow` (`grep -n "upsert_omdb(\|TmdbFactsRow(" tests/unit/test_database.py | head`) and write `_found_rating(tt)` / `_facts(tmdb_id, tt)` helpers that mirror those calls exactly — the payload must carry `imdbID`, and `found=True`.

- [ ] **Step 2: Run** → FAIL (`AttributeError: key_disagreements`).

- [ ] **Step 3: Implement**

```python
class DisagreementFilm(NamedTuple):
    id: int
    title: str
    year: int | None
    omdb_tt: str
    tmdb_tt: str
    tmdb_id: str | None
    imdb_ext: str | None
    criterion: bool
```

```python
    def key_disagreements(self) -> list[DisagreementFilm]:
        """Undisposed films whose found OMDb record names a different IMDb id than their TMDB
        side (external `imdb`, else `tmdb_facts.imdb_id`) — memo §7 step 3's worklist."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT f.id, f.title, f.year, json_extract(o.payload, '$.imdbID') AS o_tt, "
                "COALESCE((SELECT value FROM external_ids e WHERE e.film_id = f.id AND e.authority = 'imdb'), "
                "         (SELECT imdb_id FROM tmdb_facts t WHERE t.film_id = f.id)) AS t_tt, "
                "(SELECT value FROM external_ids e WHERE e.film_id = f.id AND e.authority = 'tmdb') AS t_id, "
                "(SELECT value FROM external_ids e WHERE e.film_id = f.id AND e.authority = 'imdb') AS i_ext, "
                "EXISTS (SELECT 1 FROM listings l WHERE l.film_id = f.id AND l.source = 'criterion') AS crit "
                "FROM films f JOIN omdb o ON o.film_id = f.id AND o.found = 1 "
                f"WHERE {_NOT_DISPOSED} AND o_tt IS NOT NULL AND t_tt IS NOT NULL AND o_tt != t_tt ORDER BY f.id"
            ).fetchall()
            return [
                DisagreementFilm(
                    int(r["id"]), str(r["title"]), r["year"], str(r["o_tt"]), str(r["t_tt"]), r["t_id"], r["i_ext"],
                    bool(r["crit"]),
                )
                for r in rows
            ]

    def omdb_imdb_id(self, film_id: int) -> str | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT json_extract(payload, '$.imdbID') AS tt FROM omdb WHERE film_id = ? AND found = 1", (film_id,)
            ).fetchone()
            return None if row is None or row["tt"] is None else str(row["tt"])
```

(SQLite allows column aliases in WHERE; if it complains, repeat the expressions.)

- [ ] **Step 4: Run** test + gates. **Step 5: Commit** — `git commit -am "repo: key_disagreements worklist + omdb_imdb_id (memo step 3)"`

---

### Task 4: contract loader + pure verdicts (`audit_disagreements`)

**Files:**
- Modify: `src/movie_brain/application/repair.py` (append after `repair_editions`)
- Create: `tests/unit/test_repair_disagreements.py`

**Interfaces (Produces):**

```python
@dataclass(frozen=True)
class DisagreementContract:
    film_id: int; status: str; expected_tt: str; expected_tmdb: str | None
    title_ingested: str; year_ingested: int | None; source: str; director: str | None

def load_disagreement_contract(csv_path: Path) -> dict[int, DisagreementContract]   # every D-disagree row with a numeric film_id

@dataclass(frozen=True)
class DisagreementGroup:
    film_id: int; title: str; year: int | None; omdb_tt: str; tmdb_tt: str; tmdb_id: str | None
    verdict: str          # refetch | relink | adopt | review | conflict
    expected_tt: str      # "" when no contract row
    expected_tmdb: str | None
    detail: str
    contract: DisagreementContract | None

def audit_disagreements(repo: Repository, contract: dict[int, DisagreementContract]) -> list[DisagreementGroup]
def format_disagreement(g: DisagreementGroup) -> str   # "[verdict] #id 'title' (year) omdb tt… / tmdb tt… → expected …: detail"
```

Verdict rules (pure; holders from `repo.external_id_holders("imdb"|"tmdb")` computed once):
1. no contract row → `conflict` "no D-disagree row".
2. `status != "verified"` → `review` "proposed …" (value = expected_tt or "").
3. `expected_tt == "NONE"` → `review` "verified NONE — human decides".
4. tt holder of `expected_tt` exists and ≠ film → `conflict` "tt held by #N". Same for `expected_tmdb` via tmdb holders.
5. `expected_tt == tmdb_tt` → `refetch`. `== omdb_tt` → `relink`. else: `adopt` if `expected_tmdb` else `conflict` "adopt needs expected_tmdb".

- [ ] **Step 1: Failing tests**

```python
from datetime import date
from pathlib import Path

from movie_brain.application.repair import (
    DisagreementContract,
    audit_disagreements,
    format_disagreement,
    load_disagreement_contract,
)
from movie_brain.domain.models import Film

HEADER = "group,film_id,source,title_ingested,year_ingested,expected_tt,expected_tmdb,verified_by,note,status,director,runtime_min\n"


def _csv(tmp_path, *rows):
    p = tmp_path / "eval.csv"
    p.write_text(HEADER + "".join(r + "\n" for r in rows), encoding="utf-8")
    return p


def test_load_contract_keeps_every_d_row(tmp_path):
    p = _csv(
        tmp_path,
        "D-disagree,7,criterion,Bound,1995,tt0112565,,x,note,verified,Kimi Takesue,",
        "D-disagree,8,criterion,Resurrection,,,,?,note,proposed,,",
        "C-edition,9,apple,Blade Runner (Final Cut),2007,tt1,2,x,work='Blade Runner' 1982,verified,,",
    )
    c = load_disagreement_contract(p)
    assert set(c) == {7, 8}
    assert c[7] == DisagreementContract(7, "verified", "tt0112565", None, "Bound", 1995, "criterion", "Kimi Takesue")
    assert c[8].status == "proposed" and c[8].year_ingested is None and c[8].director is None


def _split(repo, today, title, omdb_tt, tmdb_tt, tmdb_id):
    fid = repo.create_film(Film(title, 2000, None, ""))
    repo.upsert_omdb(fid, _found_rating(omdb_tt), today)      # same helpers as test_database Task 3
    repo.set_external_id(fid, "tmdb", str(tmdb_id), today)
    repo.upsert_tmdb_facts(fid, _facts(tmdb_id, tmdb_tt), today)
    return fid


def _contract(fid, tt, tmdb=None, status="verified"):
    return DisagreementContract(fid, status, tt, tmdb, "T", 2000, "criterion", None)


def test_verdicts_follow_the_contract_row(repo, today):
    refetch = _split(repo, today, "Refetch", "ttA", "ttB", 1)
    relink = _split(repo, today, "Relink", "ttC", "ttD", 2)
    adopt = _split(repo, today, "Adopt", "ttE", "ttF", 3)
    adopt_no_tmdb = _split(repo, today, "Adopt2", "ttG", "ttH", 4)
    proposed = _split(repo, today, "Proposed", "ttI", "ttJ", 5)
    none = _split(repo, today, "None", "ttK", "ttL", 6)
    orphan = _split(repo, today, "Orphan", "ttM", "ttN", 7)
    held = _split(repo, today, "Held", "ttO", "ttP", 8)
    other = repo.create_film(Film("Other", 1999, None, ""))
    repo.set_external_id(other, "imdb", "ttQ", today)
    contract = {
        refetch: _contract(refetch, "ttB"),
        relink: _contract(relink, "ttC"),
        adopt: _contract(adopt, "ttZ", "99"),
        adopt_no_tmdb: _contract(adopt_no_tmdb, "ttY"),
        proposed: _contract(proposed, "ttJ", status="proposed"),
        none: _contract(none, "NONE"),
        held: _contract(held, "ttQ"),
    }
    got = {g.film_id: g.verdict for g in audit_disagreements(repo, contract)}
    assert got == {
        refetch: "refetch", relink: "relink", adopt: "adopt", adopt_no_tmdb: "conflict",
        proposed: "review", none: "review", orphan: "conflict", held: "conflict",
    }
    line = format_disagreement(next(g for g in audit_disagreements(repo, contract) if g.film_id == held))
    assert line.startswith("[conflict]") and f"held by #{other}" in line
```

- [ ] **Step 2: Run** → FAIL (ImportError).

- [ ] **Step 3: Implement** (append to `repair.py`; `csv`, `Path`, `dataclass`, `Repository` are already imported there — check the top of the file)

```python
@dataclass(frozen=True)
class DisagreementContract:
    film_id: int
    status: str
    expected_tt: str
    expected_tmdb: str | None
    title_ingested: str
    year_ingested: int | None
    source: str
    director: str | None


def load_disagreement_contract(csv_path: Path) -> dict[int, DisagreementContract]:
    """Every group-D row keyed by film id — `verified` rows are the contract, `proposed`
    rows are rendered as reviews and never applied."""
    out: dict[int, DisagreementContract] = {}
    if not csv_path.exists():
        return out
    with csv_path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["group"] != "D-disagree" or not r["film_id"].isdigit():
                continue
            fid = int(r["film_id"])
            out[fid] = DisagreementContract(
                fid,
                r["status"],
                r["expected_tt"],
                r.get("expected_tmdb") or None,
                r["title_ingested"],
                int(r["year_ingested"]) if r["year_ingested"] else None,
                r["source"],
                r.get("director") or None,
            )
    return out


@dataclass(frozen=True)
class DisagreementGroup:
    film_id: int
    title: str
    year: int | None
    omdb_tt: str
    tmdb_tt: str
    tmdb_id: str | None
    verdict: str  # "refetch" | "relink" | "adopt" | "review" | "conflict"
    expected_tt: str
    expected_tmdb: str | None
    detail: str
    contract: DisagreementContract | None


@dataclass(frozen=True)
class DisagreementsReport:
    groups: int
    refetch: int
    relink: int
    adopt: int
    review: int
    conflict: int
    applied: int
    declined: int


def audit_disagreements(repo: Repository, contract: dict[int, DisagreementContract]) -> list[DisagreementGroup]:
    """Live disagreements ∩ group D → one verdict each. Holders are read once, before any write,
    over EVERY film (disposed included — the UNIQUE guard is blind to dispositions too)."""
    tt_holders = repo.external_id_holders("imdb")
    tmdb_holders = repo.external_id_holders("tmdb")
    groups: list[DisagreementGroup] = []
    for f in repo.key_disagreements():
        c = contract.get(f.id)

        def mk(verdict: str, detail: str) -> DisagreementGroup:
            return DisagreementGroup(
                f.id, f.title, f.year, f.omdb_tt, f.tmdb_tt, f.tmdb_id, verdict,
                c.expected_tt if c else "", c.expected_tmdb if c else None, detail, c,
            )

        if c is None:
            groups.append(mk("conflict", "no D-disagree row"))
            continue
        if c.status != "verified":
            groups.append(mk("review", f"{c.status} {c.expected_tt or '?'} — A/B/C review"))
            continue
        if c.expected_tt == "NONE":
            groups.append(mk("review", "verified NONE — human decides"))
            continue
        holder = tt_holders.get(c.expected_tt)
        if holder is not None and holder != f.id:
            groups.append(mk("conflict", f"{c.expected_tt} held by #{holder}"))
            continue
        th = tmdb_holders.get(c.expected_tmdb) if c.expected_tmdb else None
        if th is not None and th != f.id:
            groups.append(mk("conflict", f"tmdb {c.expected_tmdb} held by #{th}"))
            continue
        if c.expected_tt == f.tmdb_tt:
            groups.append(mk("refetch", "OMDb stub is the wrong work — refetch by id"))
        elif c.expected_tt == f.omdb_tt:
            groups.append(mk("relink", "TMDB link is the wrong work — relink via find_by_imdb"))
        elif c.expected_tmdb:
            groups.append(mk("adopt", f"neither side — adopt {c.expected_tt}/{c.expected_tmdb}"))
        else:
            groups.append(mk("conflict", "adopt needs expected_tmdb"))
    return groups


def format_disagreement(g: DisagreementGroup) -> str:
    exp = f"{g.expected_tt or '?'}/{g.expected_tmdb or '-'}"
    return (
        f"[{g.verdict}] #{g.film_id} {g.title!r} ({g.year}) omdb {g.omdb_tt} / tmdb {g.tmdb_tt}"
        f"({g.tmdb_id or '-'}) → {exp}: {g.detail}"
    )
```

- [ ] **Step 4: Run** tests + gates. **Step 5: Commit** — `git commit -am "repair disagreements: group D contract + pure verdicts (nothing applied yet)"`

---

### Task 5: `repair_disagreements` — apply paths + the `key-disagreement` review row

**Files:**
- Modify: `src/movie_brain/application/repair.py`
- Test: `tests/unit/test_repair_disagreements.py`

**Interfaces:**
- Consumes: Task 3/4; `record_tmdb_match(repo, target, winner_id, winner_year, today, log)` (`application/availability.py:78`); `queue_review_once(repo, "tmdb", ReviewEntry(...), today)` (`availability.py:37`); `review_detail(verdict, query)` (`application/thumbprint.py:169`); `make_query`, `resolve`, `Verdict` (`domain/thumbprint.py`); `CandidateFetcher`, `CandidateCache` (`infrastructure/thumbprint_fetch.py`).
- Produces:

```python
KEY_DISAGREEMENT = "key-disagreement"   # durable tmdb review reason

def repair_disagreements(
    repo: Repository, today: date, *, apply: bool,
    confirm: Callable[[DisagreementGroup], bool],
    contract: dict[int, DisagreementContract],
    tmdb: TmdbClient | None,                 # relink/adopt need it; None → those groups log "no TMDB client" and count as conflict at apply time
    fetcher: CandidateFetcher | None,        # review rows; None → "no candidates" detail
    limit: int | None = None,
    log: Callable[[str], None] = _stderr,
) -> DisagreementsReport
```

Apply semantics per verdict (spec §3):
- `refetch`: `repo.set_external_id(fid, "imdb", expected_tt, today)`; `repo.mark_omdb_refresh(fid)`.
- `relink`: `tid = tmdb.find_by_imdb(expected_tt)`; if `tid is None`: `repo.clear_tmdb_link(fid, today)` + `set_external_id(imdb)`; log `unlinked`. Else `set_external_id(imdb)`, `target = repo.tmdb_target(fid)`, `res = record_tmdb_match(repo, target, tid, tmdb.movie_year(tid), today, log)`; `res` not in `("matched","adopted")` → log `[partial]` and `raise RuntimeError`. Then `mark_omdb_refresh` only if `repo.omdb_imdb_id(fid) != expected_tt` (never true here, but keep the rule uniform).
- `adopt`: same as relink's found branch with `tid = int(expected_tmdb)`, then `mark_omdb_refresh(fid)` unconditionally.
- `review`: build the row (below) via `queue_review_once`; counted as `applied` when queued (dry run never queues). **Review rows are written on `--apply` only** — dry run just lists them.
- `conflict`: never touched.

Review row builder:

```python
def _disagreement_review(g: DisagreementGroup, fetcher: CandidateFetcher | None) -> ReviewEntry:
    c = g.contract
    assert c is not None
    q = make_query(c.title_ingested or g.title, c.year_ingested if c.year_ingested else g.year, c.source, director=c.director)
    if fetcher is None:
        v = Verdict("review", None, "no candidates", ())
    else:
        try:
            v = resolve(q, fetcher.fetch(q))
        except CacheMiss as exc:  # no clients for a miss
            v = Verdict("review", None, f"no candidates ({exc})", ())
    value = c.expected_tt or "NONE" if c.status != "verified" or c.expected_tt == "NONE" else c.expected_tt
    return ReviewEntry(KEY_DISAGREEMENT, film_id=g.film_id, value=value or None, detail=review_detail(v, q))
```

(The CSV's own `A=…|B=…` note is NOT copied — the live resolver's ranking is the review's evidence; the proposed tt lives in `value`.)

- [ ] **Step 1: Failing tests** (extend the new test module; `FakeTmdb` with `find_by_imdb`/`movie_year` dicts; `fetcher=None` for review rows; assert DB state after apply)

```python
class FakeTmdb:
    def __init__(self, by_imdb=None, years=None):
        self.by_imdb, self.years = by_imdb or {}, years or {}

    def find_by_imdb(self, tt):
        return self.by_imdb.get(tt)

    def movie_year(self, tid):
        return self.years.get(tid)


def _run(repo, today, contract, tmdb=None, apply=True, limit=None):
    from movie_brain.application.repair import repair_disagreements

    lines = []
    rep = repair_disagreements(
        repo, today, apply=apply, confirm=lambda g: True, contract=contract, tmdb=tmdb, fetcher=None, limit=limit,
        log=lines.append,
    )
    return rep, lines


def test_refetch_writes_imdb_and_marks_refresh(repo, today):
    fid = _split(repo, today, "Refetch", "ttA", "ttB", 1)
    rep, _ = _run(repo, today, {fid: _contract(fid, "ttB")})
    assert (rep.refetch, rep.applied) == (1, 1)
    assert repo.external_ids_for(fid)["imdb"] == "ttB"
    assert _needs_refresh(repo, fid)          # SELECT needs_refresh FROM omdb
    assert repo.key_disagreements() == []     # imdb ext now equals OMDb? no: OMDb still ttA → still listed until sync
```

Careful: after `refetch`, `omdb_tt` (ttA) ≠ external imdb (ttB) → **still a disagreement until the sync refetches**. So the last assert must be `assert [g.film_id for g in repo.key_disagreements()] == [fid]` and idempotence is asserted differently: a second dry run reports the group as `refetch` again but `--apply` must not re-queue anything harmful (set_external_id + mark_omdb_refresh are idempotent). Document this in the verb docstring and in the CLAUDE.md bullet: *the disagreement count drops after the next sync, not after `--apply`.*

```python
def test_relink_uses_find_by_imdb_and_moves_tmdb(repo, today):
    fid = _split(repo, today, "Relink", "ttC", "ttD", 2)
    rep, lines = _run(repo, today, {fid: _contract(fid, "ttC")}, tmdb=FakeTmdb({"ttC": 77}, {77: 2000}))
    ids = repo.external_ids_for(fid)
    assert (ids["imdb"], ids["tmdb"]) == ("ttC", "77")
    assert rep.applied == 1 and any("relinked" in ln for ln in lines)


def test_relink_without_tmdb_record_clears_and_keys_imdb(repo, today):
    fid = _split(repo, today, "Relink", "ttC", "ttD", 2)
    _run(repo, today, {fid: _contract(fid, "ttC")}, tmdb=FakeTmdb({}))
    ids = repo.external_ids_for(fid)
    assert ids["imdb"] == "ttC" and "tmdb" not in ids


def test_adopt_records_both_ids_and_refreshes(repo, today):
    fid = _split(repo, today, "Adopt", "ttE", "ttF", 3)
    _run(repo, today, {fid: _contract(fid, "ttZ", "99")}, tmdb=FakeTmdb({}, {99: 2000}))
    ids = repo.external_ids_for(fid)
    assert (ids["imdb"], ids["tmdb"]) == ("ttZ", "99") and _needs_refresh(repo, fid)


def test_criterion_listed_adopt_never_rekeys(repo, today):
    # record_tmdb_match's commerce guard: a Criterion-listed film keeps its year/key even when TMDB's year differs
    fid = _split(repo, today, "Listed", "ttE", "ttF", 3)
    repo.record_catalog("criterion", [Film("Listed", 2000, None, "https://x/listed")], today)
    before = repo.get_view(fid, today).year
    _run(repo, today, {fid: _contract(fid, "ttZ", "99")}, tmdb=FakeTmdb({}, {99: 1950}))
    assert repo.get_view(fid, today).year == before == 2000


def test_proposed_row_becomes_durable_review_once(repo, today):
    fid = _split(repo, today, "Proposed", "ttI", "ttJ", 5)
    c = {fid: _contract(fid, "ttJ", status="proposed")}
    _run(repo, today, c)
    _run(repo, today, c)
    rows = [r for r in repo.open_reviews("tmdb") if r["reason"] == "key-disagreement"]
    assert len(rows) == 1 and rows[0]["film_id"] == fid and rows[0]["value"] == "ttJ"
    from movie_brain.application.thumbprint import parse_review_detail
    parsed = parse_review_detail(str(rows[0]["detail"]))
    assert parsed is not None and parsed.query["title"] == "T" and parsed.reason == "no candidates"
    assert repo.external_ids_for(fid).get("imdb") is None  # never keyed


def test_dry_run_writes_nothing(repo, today):
    fid = _split(repo, today, "Refetch", "ttA", "ttB", 1)
    rep, lines = _run(repo, today, {fid: _contract(fid, "ttB")}, apply=False)
    assert rep.applied == 0 and "imdb" not in repo.external_ids_for(fid) and lines[0].startswith("[refetch]")


def test_relink_needs_a_client(repo, today):
    fid = _split(repo, today, "Relink", "ttC", "ttD", 2)
    rep, lines = _run(repo, today, {fid: _contract(fid, "ttC")}, tmdb=None)
    assert rep.applied == 0 and any("no TMDB client" in ln for ln in lines) and "imdb" not in repo.external_ids_for(fid)
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**

```python
KEY_DISAGREEMENT = "key-disagreement"


def _disagreement_review(g: DisagreementGroup, fetcher: CandidateFetcher | None) -> ReviewEntry:
    ...  # as in Interfaces above


def repair_disagreements(
    repo: Repository,
    today: date,
    *,
    apply: bool,
    confirm: Callable[[DisagreementGroup], bool],
    contract: dict[int, DisagreementContract],
    tmdb: TmdbClient | None,
    fetcher: CandidateFetcher | None,
    limit: int | None = None,
    log: Callable[[str], None] = _stderr,
) -> DisagreementsReport:
    """Dry run lists every group; --apply acts per verdict (spec §3). A `refetch` film stays in
    the worklist until the next sync refetches its OMDb record by the id written here — the
    disagreement count drops after `sync`, not after `--apply`. `review` rows are queued on
    --apply only and are durable + idempotent (`queue_review_once`)."""
    groups = audit_disagreements(repo, contract)
    if limit is not None:
        groups = groups[:limit]
    applied = declined = 0
    for g in groups:
        log(format_disagreement(g))
        if not apply or g.verdict == "conflict":
            continue
        if not confirm(g):
            declined += 1
            continue
        if g.verdict == "review":
            if queue_review_once(repo, TMDB_AUTHORITY, _disagreement_review(g, fetcher), today):
                log(f"  queued {KEY_DISAGREEMENT} review for #{g.film_id}")
                applied += 1
            else:
                log("  review already open")
            continue
        if g.verdict in ("relink", "adopt") and tmdb is None:
            log("  no TMDB client — skipped (needs the TMDB token)")
            continue
        tid: int | None
        if g.verdict == "refetch":
            tid = None
        elif g.verdict == "relink":
            tid = tmdb.find_by_imdb(g.expected_tt)  # type: ignore[union-attr]
        else:
            tid = int(str(g.expected_tmdb))
        repo.set_external_id(g.film_id, "imdb", g.expected_tt, today)
        if g.verdict == "relink" and tid is None:
            repo.clear_tmdb_link(g.film_id, today)
            log(f"  unlinked tmdb (no TMDB record for {g.expected_tt}); imdb {g.expected_tt} keyed")
        elif tid is not None:
            target = repo.tmdb_target(g.film_id)
            if target is None:
                raise RuntimeError(f"[partial] #{g.film_id} vanished after its imdb id was written")
            res = record_tmdb_match(repo, target, tid, tmdb.movie_year(tid), today, log)  # type: ignore[union-attr]
            if res not in ("matched", "adopted"):
                partial = f"[partial] #{g.film_id} PARTIAL: imdb {g.expected_tt} written but tmdb {tid} {res}"
                log(partial)
                raise RuntimeError(partial)
            log(f"  relinked tmdb {tid} ({res})")
        if repo.omdb_imdb_id(g.film_id) != g.expected_tt:
            repo.mark_omdb_refresh(g.film_id)
            log(f"  omdb refresh queued (by id {g.expected_tt})")
        applied += 1
    counts = {v: sum(1 for g in groups if g.verdict == v) for v in ("refetch", "relink", "adopt", "review", "conflict")}
    return DisagreementsReport(
        len(groups), counts["refetch"], counts["relink"], counts["adopt"], counts["review"], counts["conflict"],
        applied, declined,
    )
```

Imports to add at the top of `repair.py`: `from movie_brain.application.availability import TMDB_AUTHORITY, queue_review_once, record_tmdb_match`, `from movie_brain.application.thumbprint import review_detail`, `from movie_brain.domain.models import ReviewEntry`, `from movie_brain.domain.thumbprint import Verdict, make_query, resolve`, `from movie_brain.infrastructure.thumbprint_fetch import CacheMiss, CandidateFetcher`, `from movie_brain.infrastructure.tmdb import TmdbClient`. Check for import cycles (`availability` imports nothing from `repair`; `thumbprint` application module imports `review`? verify with `grep -n "^from movie_brain" src/movie_brain/application/thumbprint.py`). If a cycle appears, import inside the function as `review.py` does.

- [ ] **Step 4: Run** all tests + gates (mypy will want the `# type: ignore` or an explicit `assert tmdb is not None` — prefer the assert). **Step 5: Commit** — `git commit -am "repair disagreements: apply refetch/relink/adopt from the contract; proposed rows become durable key-disagreement reviews"`

---

### Task 6: CLI `repair disagreements`

**Files:**
- Modify: `src/movie_brain/cli.py` (after `repair_editions_cmd`; extend the `from movie_brain.application.repair import (...)` block)
- Test: `tests/unit/test_cli.py`

- [ ] **Step 1: Failing tests**

```python
def test_repair_disagreements_dry_run_on_empty_db(config_dir):
    r = runner.invoke(app, ["repair", "disagreements"])
    assert r.exit_code == 0 and "groups: 0" in r.output


def test_repair_disagreements_partial_exits_1(monkeypatch):
    def fake(repo, today, *, apply, confirm, contract, tmdb, fetcher, limit, log):
        raise RuntimeError("[partial] #1 PARTIAL: imdb tt1 written but tmdb 2 id-conflict")

    monkeypatch.setattr("movie_brain.cli.repair_disagreements", fake)
    r = runner.invoke(app, ["repair", "disagreements", "--apply", "--yes"])
    assert r.exit_code == 1 and "PARTIAL" in r.output
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**

```python
@repair_app.command("disagreements")
def repair_disagreements_cmd(
    apply: Annotated[bool, typer.Option("--apply", help="Act on confirmed groups (default: dry-run).")] = False,
    yes: Annotated[bool, typer.Option("--yes", help="With --apply: confirm every group without prompting.")] = False,
    limit: Annotated[int | None, typer.Option("--limit", help="Only the first N groups (batch size).")] = None,
) -> None:
    """Repair films whose OMDb imdbID ≠ TMDB imdb_id from eval group D (verified rows applied, proposed rows → A/B/C review)."""
    from movie_brain.infrastructure.omdb import OmdbClient
    from movie_brain.infrastructure.thumbprint_fetch import CandidateCache, CandidateFetcher

    root = Path(__file__).resolve().parents[2]
    contract = load_disagreement_contract(root / "scripts" / "eval" / "thumbprint_eval_v1.csv")
    cfg = load_config()
    token, key = load_tmdb_token(cfg), load_api_key(cfg)
    tmdb = TmdbClient(token) if token else None
    fetcher = None
    if tmdb is not None and key:
        # fixture hits are free; misses hit the live clients; NOTHING is saved back (path=None)
        data = CandidateCache.load(root / "scripts" / "eval" / "fixtures" / "cand_cache.json.gz", read_only=True).data
        fetcher = CandidateFetcher(CandidateCache(data, None), tmdb, OmdbClient(key))

    def confirm(g: DisagreementGroup) -> bool:
        return yes or typer.confirm(f"#{g.film_id} {g.title!r} [{g.verdict}] → {g.expected_tt or 'review'}?", default=False)

    try:
        report = repair_disagreements(
            _repo(), date.today(), apply=apply, confirm=confirm, contract=contract, tmdb=tmdb, fetcher=fetcher,
            limit=limit, log=_plain,
        )
    except RuntimeError as exc:
        err.print(str(exc))
        raise typer.Exit(1) from exc
    console.print(
        f"groups: {report.groups} · refetch: {report.refetch} · relink: {report.relink} · adopt: {report.adopt} · "
        f"review: {report.review} · conflict: {report.conflict} · applied: {report.applied} · declined: {report.declined}"
    )
```

- [ ] **Step 4: Run** tests + gates. **Step 5: Commit** — `git commit -am "cli: repair disagreements verb (same protocol as twins/editions)"`

---

### Task 7: `resolve_review` refreshes a found-but-wrong OMDb stub

**Files:**
- Modify: `src/movie_brain/application/review.py` (inside the `--pick/--tt` branch, after the key writes)
- Test: `tests/step_defs/test_review.py` + `tests/features/review.feature` (follow the existing `--pick`/`--tt` scenarios; `grep -n "pick\|--tt" tests/features/review.feature`)

- [ ] **Step 1: Failing scenario** — seed a film with a found OMDb payload `imdbID=ttOLD` and an open `tmdb` review row (`key-disagreement` or `no-match`, either works), resolve with `--tt ttNEW` (no client), then assert `omdb.needs_refresh = 1`. Also the negative: `--tt ttOLD` leaves `needs_refresh = 0`.

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** — right after the `if chosen_tmdb is not None:` block inside `if chosen_tt != "NONE":`:

```python
            if repo.omdb_imdb_id(rid) not in (None, chosen_tt):
                repo.mark_omdb_refresh(rid)  # a found-but-WRONG stub must be refetched by the new id
```

- [ ] **Step 4: Run** + gates. **Step 5: Commit** — `git commit -am "review resolve: a keyed film whose OMDb record names another work is refetched by id"`

---

### Task 8: article-insensitive title level (behind the gate) + fetcher plausibility

**Files:**
- Modify: `src/movie_brain/domain/thumbprint.py:200-208` (`title_level`), `src/movie_brain/infrastructure/thumbprint_fetch.py:222-227` (`plausible`)
- Test: `tests/unit/test_thumbprint.py`, `tests/unit/test_thumbprint_fetch.py`

**Interfaces (Produces):** `def strip_article(norm: str) -> str` in `domain/thumbprint.py` — strips a leading `the|a|an` from an already-`norm_title`'d string (`"thething" → "thing"`, `"astarisborn" → "starisborn"`, `"thing"` unchanged, `"a"` unchanged — never strip to empty). Because `norm_title` removes spaces, use a word-boundary-free rule on the ORIGINAL title: `re.sub(r"^(the|an|a)\s+", "", title, flags=re.I)` BEFORE `norm_title` — so define `def article_norm(title: str) -> str: return norm_title(re.sub(r"^(the|an|a)\s+", "", title.strip(), flags=re.I))` instead and use that everywhere (rename accordingly; the plan's `strip_article` name is replaced by `article_norm`).

`title_level` rule: after the exact check fails and BEFORE the longer-title check: `if any(article_norm(x) in aforms for x in c.titles if x): return 3` where `aforms = {article_norm(f) for f in q.parsed.forms()}` — **but only when no candidate in the pool is article-exact**. `title_level(q, c)` sees one candidate; so compute the pool flag in `resolve()`: `has_exact = any(title_level(q, c) == 3 for c in candidates)` with the old function, and pass `article_ok=not has_exact` into `title_level(q, c, article_ok=...)`. Signature: `def title_level(q: Query, c: Candidate, *, article_ok: bool = False) -> int`.

- [ ] **Step 1: Failing tests**

```python
def test_article_norm():
    assert article_norm("The Bride of Frankenstein") == article_norm("Bride of Frankenstein")
    assert article_norm("A Star Is Born") == "starisborn"
    assert article_norm("Thing") == "thing" and article_norm("A") == "a"
    assert article_norm("Theatre of Blood") == "theatreofblood"  # no false prefix


def test_article_insensitive_match_when_no_exact_candidate():
    q = make_query("The Bride of Frankenstein", 1935, "criterion")
    v = resolve(q, [cand("tt0026138", "Bride of Frankenstein", 1935, votes=50000, in_omdb=True)])
    assert (v.kind, v.tt, v.reason) == ("match", "tt0026138", "exact title + year + agreement")


def test_article_exact_candidate_outranks_article_folded_rival():
    q = make_query("The Thing", 1982, "criterion")
    v = resolve(q, [cand("ttthing", "The Thing", 1982, votes=400000), cand("ttother", "Thing", 1982, votes=5000)])
    assert (v.kind, v.tt) == ("match", "ttthing")
    # the folded rival never reaches tier 3 while an article-exact candidate exists
    assert [s.title_level for s in v.ranked] == [3] or v.ranked[0].candidate.tt == "ttthing"


def test_star_is_born_year_still_decides():
    q = make_query("A Star Is Born", 1937, "criterion")
    v = resolve(q, [cand("tt1937", "A Star Is Born", 1937, votes=9000), cand("tt1954", "A Star Is Born", 1954, votes=30000)])
    assert (v.kind, v.tt) == ("match", "tt1937")
```

Fetcher test (`tests/unit/test_thumbprint_fetch.py`, follow the existing fake-cache pattern there): a TMDB search returning `Bride of Frankenstein` in position 4 for query `The Bride of Frankenstein` gets its detail fetched (was skipped by `j < 3`).

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**

```python
_ARTICLE = re.compile(r"^(the|an|a)\s+", re.I)


def article_norm(title: str) -> str:
    """`norm_title` after dropping one leading English article — *The Bride of Frankenstein*
    vs TMDB's *Bride of Frankenstein*. English only on purpose (*La Strada* is not *Strada*)."""
    return norm_title(_ARTICLE.sub("", title.strip(), count=1))


def title_level(q: Query, c: Candidate, *, article_ok: bool = False) -> int:
    forms = {norm_title(f) for f in q.parsed.forms()}
    nt = norm_title(q.title)
    if any(norm_title(x) in forms for x in c.titles if x):
        return 3
    if article_ok:
        aforms = {article_norm(f) for f in q.parsed.forms()}
        if any(article_norm(x) in aforms for x in c.titles if x):
            return 3
    if any(norm_title(x).startswith(nt) and len(nt) >= 8 for x in c.titles if x):
        return 2
    return 1 if max((_sim(q.title, x) for x in c.titles if x), default=0.0) >= 0.85 else 0
```

In `resolve()`: before the loop, `article_ok = not any(title_level(q, c) == 3 for c in candidates)`; in the loop `lvl = title_level(q, c, article_ok=article_ok)`. In `thumbprint_fetch.plausible`: add `or article_norm(x.get("title") or "") in aforms or article_norm(x.get("original_title") or "") in aforms` with `aforms = {article_norm(f) for f in q.parsed.forms()}` (import `article_norm`).

- [ ] **Step 4: Run** `uv run pytest`, then **the gate: `uv run python scripts/thumbprint_benchmark.py --assert`** — must print `WRONG=0` and auto ≥ 94.8 %. If auto drops or a WRONG appears, the rule is NOT adopted: revert `resolve()`'s `article_ok` computation to `False` (keep the helper + tests marked xfail) and report the WRONG rows to the owner. Also `--assert-dominance`.

- [ ] **Step 5: Commit** — `git commit -am "resolve: a leading English article is not title evidence when no article-exact candidate exists (gate: n=484/0/…)"` (fill in the real auto %).

---

### Task 9: docs + rules

**Files:** `CLAUDE.md` (commands block: `migrate`, `repair disagreements`; migration bullet: "no verb applies migrations implicitly — `movie-brain migrate --apply` is the only path; fresh DBs bootstrap"), `.claude/rules/thumbprint.md` (one bullet: D contract, verdict table, `key-disagreement` durable reason, count drops after sync, article rule status), handoff file: prepend a **Status** section with the live numbers once rehearsal/live batches run.

- [ ] Write the bullets; run `uv run pytest -q` (some tests grep CLAUDE.md? `grep -rn "CLAUDE.md" tests | head`); commit — `git commit -am "docs: migrate guard + repair disagreements contract"`.

---

### Task 10 (manual, this session — not a subagent task): rehearsal on scratch, then live

Checklist (spec §5), every command with `MOVIE_BRAIN_CONFIG_DIR=$SCRATCH` exported:
1. `SCRATCH=<scratchpad>/cfg; mkdir -p $SCRATCH; cp ~/.config/movie-brain/movie-brain.db $SCRATCH/; cp ~/.config/movie-brain/*.txt $SCRATCH/; cp -R ~/.config/movie-brain/appletv $SCRATCH/`.
2. `movie-brain migrate` → "schema up to date". Copy the DB again to `$SCRATCH2`, drop the last `schema_version` row with sqlite3 (`DELETE FROM schema_version WHERE version = 12`) → `movie-brain status` exits 2; `movie-brain migrate` lists `012…`; `--apply` → backup file + status OK. (012 re-applies on a v12 body — if it is not idempotent, use a throwaway DB at v11 from `backups/` instead.)
3. `movie-brain repair disagreements` (dry) → expect `groups: 94 · refetch: 28 · relink: 17 · adopt: 4 · review: 45 · conflict: 0`.
4. `--apply --yes --limit 20` ×5 → after: `review list --reason key-disagreement` = 45 rows with A/B/C lines; imdb ids +49.
5. `cp scripts/eval/thumbprint_eval_v1.csv $SCRATCH/eval.csv`; `review resolve <id> --pick A --eval-csv $SCRATCH/eval.csv` on one proposed row → CSV row flipped to verified/human; `omdb.needs_refresh=1` for that film.
6. `movie-brain sync` → `grep -c 'external id conflict for' $SCRATCH/sync.log` = 0; disagreement query → expect ≤ 45 (the 44 proposed + Marrow) once OMDb refetches land (OMDb-paid, no quota).
7. `audit run --no-tmdb` tally vs pre-run.
8. Article measurement: `uv run python - <<EOF` script resolving the 32 open article no-match films with `CandidateFetcher(CandidateCache(fixture data, None), TmdbClient, OmdbClient)`, once with `article_ok` forced off, once on; print match/review per film + reasons. Present the table; owner decides.
9. Present all numbers → owner yes → repeat 3–7 on the live config → commit the eval CSV changes made by `ratify` (if any) → ask before merging.

---

## Self-review

- Spec coverage: §2 → Tasks 1–2; §3 → Tasks 3–6 (+7 for the drain gap); §4 → Task 8; §5 → Task 10; §6 → Task 9. ✔
- Placeholders: none (Task 7's scenario text follows the existing feature file's step vocabulary — the implementer reads it first). ✔
- Type consistency: `DisagreementGroup.contract`, `expected_tt: str` ("" when absent), `tmdb: TmdbClient | None`, `fetcher: CandidateFetcher | None`, `title_level(..., *, article_ok=False)`, `article_norm` (replaces the earlier `strip_article` name everywhere). ✔
