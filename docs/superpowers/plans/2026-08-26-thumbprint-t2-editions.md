# Thumbprint T2 — editions, external_ids 012, A/B/C review flow — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fold the 16 edition-year films into their work identity (edition year kept on the claim), loosen `external_ids` to one-row-per-value with a single-key policy for tmdb/imdb, and ship `review resolve --pick/--tt/--none` with A/B/C rendering and eval-row ratification — resolver still dark.

**Architecture:** Hexagonal, unchanged. Schema + policy in `infrastructure/database.py` (+ `migrations/012_external_ids_multi.sql`); the editions verb in `application/repair.py` next to `repair_twins`; review verbs in `application/review.py`; eval CSV writer in a new `application/eval_log.py`; Typer wiring in `cli.py`. Every live write goes through existing repo primitives (`merge_film`, `update_film_year`-style key rules, `record_tmdb_match`).

**Tech Stack:** Python 3.12, uv, SQLite, Typer/Rich, pytest + pytest-bdd + `responses`, ruff + mypy.

**Spec:** `docs/superpowers/specs/2026-08-26-thumbprint-t2-editions-design.md` ← memo `docs/superpowers/research/2026-08-25-thumbprint-design.md`, decisions `docs/superpowers/research/2026-08-26-thumbprint-t2-decisions.md`.

> **Status 2026-08-26:** Tasks 1–10 DONE on `feature/T2-thumbprint-editions` (subagent-driven, per-task
> reviews + final whole-branch review + one fix wave `768283e`). Gate: 591 passed, ruff/mypy clean,
> thumbprint n=482 / 0 wrong / 94.8 %, matching dominance PASS. Deviations from the plan text: editions
> scenarios live in `tests/features/thumbprint_editions.feature`; `_work_title` adopts the CSV note's
> casing on casefold equality only; csv-mismatch = "no longer parses as an edition AND title_norm ≠ note";
> `_edition_blockers` pre-checks tt/tmdb/key holders (all films) on BOTH paths, a twin holding a
> different imdb id is `conflict`, and a film with ANY Criterion listing is never re-keyed (Criterion
> re-ingests by `films.key`) → **#1909 Scenes from a Marriage is deferred to the ingester switch**;
> `record_catalog` is INSERT-only for the criterion id (claim authority); a post-merge keying refusal logs
> `[partial]` and raises (CLI exit 1). Task 11 rehearsed twice on scratch copies: dry run 16 groups →
> 10 twin / 5 no-twin / 1 conflict; apply (8+7) → films 4,666 =, dispositions 102→112, edition_year
> 0→15, imdb 549→564, tmdb 4,338→4,344, open no-match 225→209, owned 861→859, second apply 0 applied;
> simulated Criterion re-walk creates 0 films. **INCIDENT:** migration 012 reached the LIVE DB on
> 2026-08-26 19:06 via a subagent CLI call without `MOVIE_BRAIN_CONFIG_DIR` (schema-only, 9,448
> external_ids rows before/after, integrity ok, backup `backups/movie-brain-v11-2026-08-26.db`) — Task 12
> starts at the dry run. **LIVE (2026-08-26, done):** snapshot `movie-brain.db.bak-pre-t2`; dry run identical to
> rehearsal; owner "apply" → batches 8 + 8 (`--apply --yes --limit 8`, then the rest): 15 applied (10 merges,
> 5 direct keys), #1909 conflict skipped. End state: films 4,666 = · dispositions 102→112 · edition_year
> 0→15 · imdb 549→564 · tmdb 4,338→4,344 · open no-match 225→209 · owned 861→859; second apply 0 applied.
> Retitled works: Quai des Orfèvres 1947, How the Grinch Stole Christmas 2000, Phantasm 1979, Ghost in the
> Shell 1995, Donnie Darko 2001, Blade Runner 1982.
> **T2b (same day, branch `feature/T2b-same-year-editions`):** `repair editions` now folds SAME-YEAR
> editions (idempotence = year == work year AND no edition markers; `edition_year` only when older;
> F-human contract rows accepted; tmdb-holding twin preferred over unkeyed fellow rows; survivor
> de-dup + mutual-pair tie-break). Live 2026-08-26 (snapshot `.bak-pre-t2b`): 8 applied — merges
> #2416→#3091 Fanny and Alexander, #3264 Redux + #4098 Final Cut → #3190 Apocalypse Now (owned row
> moved), #4094→#4093 Straight Outta Compton; keyed #3414 Investigation of a Citizen…, #4133 My Man
> Godfrey, #4304 American Psycho, #4532 Van Wilder. Counts 4,666 | disp 116 | edition_year 16 | imdb
> 570 | tmdb 4,348 | open no-match 201 | owned 858; second apply 0 (#1909 conflict only).

## Global Constraints

- Branch `feature/T2-thumbprint-editions`; one commit per task; never merge to main without the owner's yes.
- No live-DB write except Tasks 11–12 (scratch rehearsal → announce → owner yes → batches → before/after counts). All other tasks: test DBs / read-only queries only.
- Resolver stays DARK — nothing in this plan calls `resolve()` from an ingester.
- `uv run pytest && uv run ruff check . && uv run mypy` green at the end of every task; `uv run python scripts/thumbprint_benchmark.py --assert` (n=482 / 0 wrong / 94.8 %) and `uv run python scripts/matching_benchmark.py --assert-dominance` green at the end of every task (they don't touch `domain/thumbprint.py` or `domain/matching.py`, so they must not move).
- Never edit `scripts/eval/thumbprint_eval_v1.csv` by hand; the only writer is Task 8's `ratify`, and rehearsals point it at a scratch copy.
- Key authorities `{"tmdb", "imdb"}` are single per film; every other authority may repeat. `UNIQUE(authority, value)` is never relaxed.
- No OMDb `t=` anywhere. Log lines beginning `[verdict]` go through `_plain`.
- Schema change = `migrations/012_external_ids_multi.sql`, BEGIN/COMMIT, inserts its own `schema_version` row.

---

## File map

| File | Responsibility |
|---|---|
| `migrations/012_external_ids_multi.sql` | rebuild `external_ids` with PK `(film_id, authority, value)` |
| `src/movie_brain/infrastructure/database.py` | `KEY_AUTHORITIES`; `set_external_id` policy; fan-out-safe metacritic joins; `merge_film` move/drop policy; `set_claim_edition_year`, `films_for_editions`, `key_work`, `claim_for_film_authority` |
| `src/movie_brain/application/repair.py` | `EditionContract`, `EditionGroup`, `EditionsReport`, `load_edition_contract`, `audit_editions`, `repair_editions`, `format_edition` |
| `src/movie_brain/application/thumbprint.py` | `review_detail(verdict, query=None)`, `parse_review_detail` |
| `src/movie_brain/application/eval_log.py` | `EvalEntry`, `ratify(csv_path, entry)` |
| `src/movie_brain/application/review.py` | `resolve_review(... pick=, tt=, none=, eval_csv=)` |
| `src/movie_brain/infrastructure/tmdb.py` | `TmdbClient.find_by_imdb` |
| `src/movie_brain/cli.py` | `repair editions`; `review list` A/B/C lines; `review resolve` new options |
| `tests/unit/test_database.py`, `tests/unit/test_eval_log.py`, `tests/unit/test_thumbprint.py`, `tests/unit/test_tmdb.py` | unit coverage |
| `tests/features/thumbprint.feature` + `tests/step_defs/test_thumbprint.py` | editions scenarios |
| `tests/features/review.feature` + `tests/step_defs/test_review.py` | pick / tt / none scenarios |
| `.claude/rules/thumbprint.md`, `CLAUDE.md` | contract + commands |

---

### Task 1: Migration 012 + `set_external_id` policy

**Files:**
- Create: `migrations/012_external_ids_multi.sql`
- Modify: `src/movie_brain/infrastructure/database.py` (`set_external_id` ~L471, `key_film_directly` ~L1265)
- Test: `tests/unit/test_database.py`

**Interfaces:**
- Produces: `KEY_AUTHORITIES: frozenset[str] = frozenset({"tmdb", "imdb"})` (module constant in `database.py`); `Repository.set_external_id(film_id, authority, value, seen)` — key authority replaces the film's row for that authority, claim authority inserts (ignore if same row exists); raises `sqlite3.IntegrityError` when another film holds `(authority, value)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_database.py (append)
import sqlite3
from datetime import date

import pytest

from movie_brain.domain.models import Film
from movie_brain.infrastructure.database import KEY_AUTHORITIES, Repository

T = date(2026, 8, 26)


def _film(repo: Repository, title: str, year: int) -> int:
    fid = repo.create_film(Film(title, year, None, ""))
    assert fid is not None
    return fid


def test_migration_012_allows_two_claim_values_per_authority(repo):
    fid = _film(repo, "Apocalypse Now", 1979)
    repo.set_external_id(fid, "metacritic", "apocalypse-now", T)
    repo.set_external_id(fid, "metacritic", "apocalypse-now-redux", T)
    conn = sqlite3.connect(repo.db_path)
    rows = conn.execute("SELECT value FROM external_ids WHERE film_id = ? ORDER BY value", (fid,)).fetchall()
    assert [r[0] for r in rows] == ["apocalypse-now", "apocalypse-now-redux"]
    assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] >= 12


def test_key_authorities_stay_single_per_film(repo):
    fid = _film(repo, "Blade Runner", 1982)
    for auth in KEY_AUTHORITIES:
        repo.set_external_id(fid, auth, "1", T)
        repo.set_external_id(fid, auth, "2", T)
        assert repo.external_ids_for(fid)[auth] == "2"
    conn = sqlite3.connect(repo.db_path)
    assert conn.execute("SELECT COUNT(*) FROM external_ids WHERE film_id = ?", (fid,)).fetchone()[0] == 2


def test_unique_authority_value_still_guards_across_films(repo):
    a, b = _film(repo, "A", 1950), _film(repo, "B", 1951)
    repo.set_external_id(a, "metacritic", "shared", T)
    with pytest.raises(sqlite3.IntegrityError):
        repo.set_external_id(b, "metacritic", "shared", T)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_database.py -k "012 or key_authorities or still_guards" -v`
Expected: FAIL — `ImportError: KEY_AUTHORITIES`, then (after a stub) `IntegrityError` on the second metacritic insert.

- [ ] **Step 3: Write the migration**

```sql
-- migrations/012_external_ids_multi.sql
-- Thumbprint T2 (spec 2026-08-26-thumbprint-t2-editions-design.md §3): a work may hold several
-- native ids from one CLAIM authority (metacritic slugs for each cut, apple titles for each
-- edition). tmdb/imdb stay single per film BY POLICY (Repository.set_external_id), not by
-- schema. UNIQUE(authority, value) — the dedup guard — is unchanged. SQLite cannot drop a
-- PK, so this is a table rebuild inside one transaction.
BEGIN;
CREATE TABLE external_ids_new (
    film_id INTEGER NOT NULL REFERENCES films(id),
    authority TEXT NOT NULL,
    value TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    PRIMARY KEY (film_id, authority, value),
    UNIQUE (authority, value)
);
INSERT INTO external_ids_new (film_id, authority, value, first_seen)
    SELECT film_id, authority, value, first_seen FROM external_ids;
DROP TABLE external_ids;
ALTER TABLE external_ids_new RENAME TO external_ids;
CREATE INDEX external_ids_film ON external_ids(film_id);
INSERT INTO schema_version (version) VALUES (12);
COMMIT;
```

- [ ] **Step 4: Policy in the repository**

```python
# database.py, near _NOT_DISPOSED
# One id per film for identity authorities; claim authorities may repeat (migration 012).
KEY_AUTHORITIES: frozenset[str] = frozenset({"tmdb", "imdb"})
```

```python
    def set_external_id(self, film_id: int, authority: str, value: str, seen: date) -> None:
        """Key authority (tmdb/imdb): replace this film's single row. Claim authority:
        add the row (no-op if this film already has it). Raises IntegrityError when another
        film holds (authority, value)."""
        with self._conn() as c:
            if authority in KEY_AUTHORITIES:
                c.execute(
                    "DELETE FROM external_ids WHERE film_id = ? AND authority = ? AND value != ?",
                    (film_id, authority, value),
                )
            c.execute(
                "INSERT INTO external_ids (film_id, authority, value, first_seen) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(film_id, authority, value) DO NOTHING",
                (film_id, authority, value, seen.isoformat()),
            )
```

In `key_film_directly` replace the `ON CONFLICT(film_id, authority) DO UPDATE …` insert with:

```python
            c.execute("DELETE FROM external_ids WHERE film_id = ? AND authority = 'imdb'", (film_id,))
            c.execute(
                "INSERT INTO external_ids (film_id, authority, value, first_seen) VALUES (?, 'imdb', ?, ?)",
                (film_id, imdb_id, today.isoformat()),
            )
```

Grep for every other `ON CONFLICT(film_id, authority)` (Criterion upsert ~L425/L474 use `OR IGNORE` — leave) and fix any remaining one the same way.

- [ ] **Step 5: Run tests, lint, types, both benchmarks**

Run: `uv run pytest && uv run ruff check . && uv run mypy && uv run python scripts/thumbprint_benchmark.py --assert && uv run python scripts/matching_benchmark.py --assert-dominance`
Expected: all green; benchmark prints `n=482 WRONG=0 … 94.8%`.

- [ ] **Step 6: Commit**

```bash
git add migrations/012_external_ids_multi.sql src/movie_brain/infrastructure/database.py tests/unit/test_database.py
git commit -m "migration 012: external_ids one row per value; tmdb/imdb single by policy"
```

---

### Task 2: Fan-out guards — one metacritic slug per film in the read models

**Files:**
- Modify: `src/movie_brain/infrastructure/database.py` (`_VIEW_SQL` ~L160-166, `audit_subjects` ~L530-536, `films_needing_lookup_discovery` ~L1048-1052)
- Test: `tests/unit/test_database.py`

**Interfaces:**
- Produces: a shared SQL fragment `_MC_SLUG_SQL` = one deterministic metacritic slug per film (earliest `first_seen`, then smallest value).

- [ ] **Step 1: Failing tests**

```python
def test_two_metacritic_slugs_do_not_duplicate_read_models(repo):
    fid = _film(repo, "Apocalypse Now", 1979)
    repo.set_external_id(fid, "metacritic", "apocalypse-now-redux", date(2026, 8, 2))
    repo.set_external_id(fid, "metacritic", "apocalypse-now", date(2026, 8, 1))
    views = [v for v in repo.list_views(T) if v.title == "Apocalypse Now"]
    assert len(views) == 1
    assert views[0].metacritic_url == "https://www.metacritic.com/movie/apocalypse-now/"  # earliest first_seen wins
    assert len([s for s in repo.audit_subjects() if s.film_id == fid]) == 1
    assert len([f for f, _ in repo.films_needing_lookup_discovery("criterion", T) if f == fid]) == 1
```

(Check `AuditSubject`'s field name for the id — grep `class AuditSubject`; use whatever it is.)

- [ ] **Step 2: Run → FAIL** (`len(views) == 2`).

- [ ] **Step 3: Implement the fragment and use it in all three sites**

```python
# database.py, module level
_MC_SLUG_SQL = (
    "(SELECT e.film_id, e.value FROM external_ids e WHERE e.authority = 'metacritic' "
    " AND NOT EXISTS (SELECT 1 FROM external_ids e2 WHERE e2.film_id = e.film_id AND e2.authority = 'metacritic' "
    "   AND (e2.first_seen < e.first_seen OR (e2.first_seen = e.first_seen AND e2.value < e.value))))"
)
```

Replace `LEFT JOIN external_ids x ON x.film_id = f.id AND x.authority = 'metacritic'` with
`LEFT JOIN {_MC_SLUG_SQL} x ON x.film_id = f.id` in `_VIEW_SQL` (make it an f-string), `audit_subjects`, and `films_needing_lookup_discovery`. Leave `metacritic_claim_rows` alone — it must return every slug.

- [ ] **Step 4: Full gate** (same command as Task 1 Step 5). Expected green.

- [ ] **Step 5: Commit** — `git commit -am "one metacritic slug per film in the read models (012 fan-out guard)"`

---

### Task 3: `merge_film` — move claim-authority ids, drop key-authority duplicates

**Files:**
- Modify: `src/movie_brain/infrastructure/database.py` (`merge_film` external_ids loop ~L1417-1432)
- Test: `tests/unit/test_database.py`

- [ ] **Step 1: Failing test**

```python
def test_merge_moves_claim_ids_and_drops_duplicate_key_ids(repo):
    loser, surv = _film(repo, "Blade Runner (The Final Cut)", 2007), _film(repo, "Blade Runner", 1982)
    repo.set_external_id(surv, "tmdb", "78", T)
    repo.set_external_id(surv, "metacritic", "blade-runner", T)
    repo.set_external_id(loser, "tmdb", "999", T)
    repo.set_external_id(loser, "metacritic", "blade-runner-the-final-cut", T)
    report = repo.merge_film(loser, surv, T, note="t")
    ids = repo.external_ids_all(surv)
    assert ("metacritic", "blade-runner-the-final-cut") in ids and ("metacritic", "blade-runner") in ids
    assert ("tmdb", "78") in ids and ("tmdb", "999") not in ids
    assert report.moved["external_ids"] == 1 and report.dropped["external_ids"] == 1
```

Add `Repository.external_ids_all(film_id) -> list[tuple[str, str]]` (every `(authority, value)` row, ordered) — `external_ids_for` keeps returning a dict (last value wins; only key authorities are read through it).

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement**

```python
            for row in c.execute("SELECT authority, value FROM external_ids WHERE film_id = ?", (loser_id,)).fetchall():
                auth, val = str(row["authority"]), str(row["value"])
                held = (
                    c.execute(
                        "SELECT 1 FROM external_ids WHERE film_id = ? AND authority = ?", (survivor_id, auth)
                    ).fetchone()
                    if auth in KEY_AUTHORITIES
                    else None
                )
                if held is None:
                    c.execute(
                        "UPDATE external_ids SET film_id = ? WHERE film_id = ? AND authority = ? AND value = ?",
                        (survivor_id, loser_id, auth, val),
                    )
                    moved["external_ids"] = moved.get("external_ids", 0) + 1
                else:
                    c.execute(
                        "DELETE FROM external_ids WHERE film_id = ? AND authority = ? AND value = ?",
                        (loser_id, auth, val),
                    )
                    dropped["external_ids"] = dropped.get("external_ids", 0) + 1
                    kept.setdefault("external_ids", []).append({auth: val})
```

- [ ] **Step 4: Full gate. Step 5: Commit** — `"merge_film: claim-authority ids move, key-authority duplicates drop"`

---

### Task 4: Repository primitives for editions

**Files:**
- Modify: `src/movie_brain/infrastructure/database.py` (claims section ~L1153; after `key_film_directly`)
- Test: `tests/unit/test_database.py`

**Interfaces (Produces):**
```python
class EditionFilm(NamedTuple):
    id: int; title: str; year: int | None; title_norm: str | None; tmdb_id: str | None; imdb_id: str | None
Repository.films_for_editions() -> list[EditionFilm]        # undisposed films, with tmdb/imdb external ids
Repository.set_claim_edition_year(claim_id: int, year: int | None) -> None
Repository.claim_for_film_authority(film_id: int, authority: str) -> ClaimRow | None   # the film's claim from one authority (lowest id)
Repository.key_work(film_id: int, *, title: str, year: int, tt: str, tmdb_id: str | None, today: date) -> bool
```

- [ ] **Step 1: Failing tests**

```python
def test_set_claim_edition_year_and_lookup(repo):
    fid = _film(repo, "Blade Runner (The Final Cut)", 2007)
    repo.add_claim(fid, "apple-tv", "Blade Runner (The Final Cut)", "Blade Runner (The Final Cut)",
                   year_claimed=2007, edition_label="the final cut", runtime_min=117, first_seen="2026-08-23")
    claim = repo.claim_for_film_authority(fid, "apple-tv")
    assert claim is not None and claim.edition_year is None
    repo.set_claim_edition_year(claim.id, 2007)
    assert repo.claim_for_film_authority(fid, "apple-tv").edition_year == 2007


def test_key_work_retitles_reyears_and_keys(repo):
    fid = _film(repo, "Blade Runner (The Final Cut)", 2007)
    repo.set_title_norm(fid, "blade runner the final cut")
    assert repo.key_work(fid, title="Blade Runner", year=1982, tt="tt0083658", tmdb_id="78", today=T)
    conn = sqlite3.connect(repo.db_path)
    title, year, key, norm = conn.execute("SELECT title, year, key, title_norm FROM films WHERE id = ?", (fid,)).fetchone()
    assert (title, year, key, norm) == ("Blade Runner", 1982, "blade runner (1982)", "blade runner")
    assert repo.external_ids_for(fid) == {"imdb": "tt0083658", "tmdb": "78"}


def test_key_work_refuses_when_key_or_tt_is_held_elsewhere(repo):
    fid = _film(repo, "Blade Runner (The Final Cut)", 2007)
    other = _film(repo, "Blade Runner", 1982)
    assert not repo.key_work(fid, title="Blade Runner", year=1982, tt="tt0083658", tmdb_id="78", today=T)
    repo.update_film_year(other, 1983)  # frees the key
    repo.set_external_id(other, "imdb", "tt0083658", T)
    assert not repo.key_work(fid, title="Blade Runner", year=1982, tt="tt0083658", tmdb_id="78", today=T)
    assert repo.external_ids_for(fid) == {}


def test_key_work_retires_its_own_losers_dead_key(repo):
    surv = _film(repo, "Donnie Darko: Anniversary Special Edition", 2001)
    loser = _film(repo, "Donnie Darko", 2001)
    repo.merge_film(loser, surv, T, note="t")
    assert repo.key_work(surv, title="Donnie Darko", year=2001, tt="tt0246578", tmdb_id="141", today=T)
    conn = sqlite3.connect(repo.db_path)
    assert conn.execute("SELECT key FROM films WHERE id = ?", (surv,)).fetchone()[0] == "donnie darko (2001)"
    assert conn.execute("SELECT key FROM films WHERE id = ?", (loser,)).fetchone()[0] == f"donnie darko (2001) #{loser}"
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement**

```python
class EditionFilm(NamedTuple):
    id: int
    title: str
    year: int | None
    title_norm: str | None
    tmdb_id: str | None
    imdb_id: str | None
```

```python
    def films_for_editions(self) -> list[EditionFilm]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT f.id, f.title, f.year, f.title_norm, "
                "(SELECT value FROM external_ids e WHERE e.film_id = f.id AND e.authority = 'tmdb') AS t_id, "
                "(SELECT value FROM external_ids e WHERE e.film_id = f.id AND e.authority = 'imdb') AS i_id "
                f"FROM films f WHERE {_NOT_DISPOSED} ORDER BY f.id"
            ).fetchall()
            return [EditionFilm(int(r["id"]), str(r["title"]), r["year"], r["title_norm"], r["t_id"], r["i_id"]) for r in rows]

    def set_claim_edition_year(self, claim_id: int, year: int | None) -> None:
        with self._conn() as c:
            c.execute("UPDATE claim SET edition_year = ? WHERE id = ?", (year, claim_id))

    def claim_for_film_authority(self, film_id: int, authority: str) -> ClaimRow | None:
        rows = [r for r in self.claims_for_film(film_id) if r.authority == authority]
        return rows[0] if rows else None

    def key_work(self, film_id: int, *, title: str, year: int, tt: str, tmdb_id: str | None, today: date) -> bool:
        """An edition row becomes its work (repair editions NO-TWIN): retitle, re-year, recompute
        key + title_norm, record imdb (+ tmdb). False, nothing written, when the new key is held
        by another live identity or tt / tmdb_id is held by another film. This film's own
        merged-away loser holding the key is retired in place (update_film_year rule)."""
        from movie_brain.domain.thumbprint import title_norm as _tn

        with self._conn() as c:
            if c.execute("SELECT 1 FROM films WHERE id = ?", (film_id,)).fetchone() is None:
                raise LookupError(f"unknown film {film_id}")
            new_key = film_key(title, year)
            holder = c.execute("SELECT id FROM films WHERE key = ? AND id != ?", (new_key, film_id)).fetchone()
            if holder is not None:
                if self._canonical_in(c, int(holder["id"])) != film_id:
                    return False
                c.execute("UPDATE films SET key = key || ' #' || id WHERE id = ?", (holder["id"],))
            for auth, val in (("imdb", tt), ("tmdb", tmdb_id)):
                if val and c.execute(
                    "SELECT 1 FROM external_ids WHERE authority = ? AND value = ? AND film_id != ?", (auth, val, film_id)
                ).fetchone():
                    return False
            c.execute(
                "UPDATE films SET title = ?, year = ?, key = ?, title_norm = ? WHERE id = ?",
                (title, year, new_key, _tn(title), film_id),
            )
            for auth, val in (("imdb", tt), ("tmdb", tmdb_id)):
                if val:
                    c.execute("DELETE FROM external_ids WHERE film_id = ? AND authority = ?", (film_id, auth))
                    c.execute(
                        "INSERT INTO external_ids (film_id, authority, value, first_seen) VALUES (?, ?, ?, ?)",
                        (film_id, auth, val, today.isoformat()),
                    )
            return True
```

Check `_canonical_in` handles a non-disposed holder (returns the holder itself → `!= film_id` → False). If it raises for undisposed ids, guard with the same `film_disposition` check `update_film_year` uses.

- [ ] **Step 4: Full gate. Step 5: Commit** — `"repo: films_for_editions, set_claim_edition_year, key_work"`

---

### Task 5: `load_edition_contract` + `audit_editions` + `repair_editions`

**Files:**
- Modify: `src/movie_brain/application/repair.py` (append after `repair_twins`)
- Test: `tests/features/thumbprint.feature`, `tests/step_defs/test_thumbprint.py`, `tests/unit/test_thumbprint.py` (contract parser)

**Interfaces (Produces):**
```python
@dataclass(frozen=True)
class EditionContract: film_id: int; work_title_note: str; work_year: int; tt: str; tmdb_id: str | None
def load_edition_contract(csv_path: Path) -> dict[int, EditionContract]     # verified C-edition rows with a tt
@dataclass(frozen=True)
class EditionGroup: film_id: int; title: str; old_year: int | None; work_title: str; work_year: int; tt: str; tmdb_id: str | None; verdict: str; twin_id: int | None; edition_year: int | None; detail: str
@dataclass(frozen=True)
class EditionsReport: groups: int; twins: int; no_twin: int; conflict: int; csv_mismatch: int; applied: int; declined: int
def audit_editions(repo, contract) -> list[EditionGroup]
def format_edition(g) -> str
def repair_editions(repo, today, *, apply, confirm, contract, limit=None, log=_stderr) -> EditionsReport
```

- [ ] **Step 1: Failing unit test for the parser**

```python
# tests/unit/test_thumbprint.py (append)
from pathlib import Path
from movie_brain.application.repair import load_edition_contract

def test_load_edition_contract_reads_verified_c_rows(tmp_path: Path):
    csv = tmp_path / "eval.csv"
    csv.write_text(
        "group,film_id,source,title_ingested,year_ingested,expected_tt,expected_tmdb,verified_by,note,status,director,runtime_min\n"
        "C-edition,4409,apple,Blade Runner (The Final Cut),2007,tt0083658,78,x,work='Blade Runner' 1982; edition=['the final cut']; films.year=2007,verified,,117\n"
        "C-edition,4503,apple,Moonwalk One (The Director's Cut),2009,,,x,NEEDS HUMAN,proposed,,108\n"
        "B-apple-year-title,1,apple,X (1999),1999,tt1,2,x,twin 3,verified,,\n"
    )
    c = load_edition_contract(csv)
    assert set(c) == {4409}
    assert c[4409].work_title_note == "Blade Runner" and c[4409].work_year == 1982
    assert c[4409].tt == "tt0083658" and c[4409].tmdb_id == "78"
```

- [ ] **Step 2: Failing BDD scenarios** (append to `tests/features/thumbprint.feature`)

```gherkin
  Scenario: an edition-year film with a clean twin merges into the work and keeps its edition year on the claim
    Given an edition film "Eyes Without a Face [re-release]" year 2003 from "metacritic" slug "eyes-without-a-face-re-release"
    And a work film "Eyes Without a Face" (1960) with tmdb id "31417"
    And the edition contract says the work is "Eyes Without a Face" 1960 tt "tt0053459" tmdb "31417"
    When I run repair editions --apply answering yes
    Then the edition film is merged into the work film
    And the work film holds imdb "tt0053459" and its metacritic claim has edition_year 2003
    And the editions report says twin 1, no-twin 0, conflict 0, csv-mismatch 0, applied 1

  Scenario: a same-title film with the wrong tmdb id is not a twin (Overlord 2018)
    Given an edition film "Overlord [re-release]" year 2006 from "metacritic" slug "overlord-re-release"
    And a work film "Overlord" (2018) with tmdb id "438799"
    And a work film "Overlord" (1975) with tmdb id "55343"
    And the edition contract says the work is "Overlord" 1975 tt "tt0073502" tmdb "55343"
    When I run repair editions --apply answering yes
    Then the edition film is merged into the work film "Overlord" (1975)

  Scenario: an edition-year film without a twin becomes the work
    Given an edition film "Blade Runner (The Final Cut)" year 2007 from "apple-tv" slug "Blade Runner (The Final Cut)"
    And the edition contract says the work is "Blade Runner" 1982 tt "tt0083658" tmdb "78"
    And the edition film has an open tmdb no-match review
    When I run repair editions --apply answering yes
    Then the edition film is titled "Blade Runner" year 1982 with imdb "tt0083658" and tmdb "78" and no disposition
    And its apple-tv claim has edition_year 2007
    And its tmdb no-match review is resolved

  Scenario: two editions of one work — the loser merges and the survivor is keyed as the work
    Given an edition film "Donnie Darko: The Director's Cut" year 2004 from "metacritic" slug "donnie-darko-the-directors-cut"
    And an edition film "Donnie Darko: Anniversary Special Edition" year 2001 from "apple-tv" slug "Donnie Darko: Anniversary Special Edition"
    And the edition contract says the work is "Donnie Darko" 2001 tt "tt0246578" tmdb "141" for both
    When I run repair editions --apply answering yes
    Then the film "Donnie Darko: The Director's Cut" is merged into the film now titled "Donnie Darko" (2001) holding tmdb "141"
    And the editions report says twin 1, no-twin 0, conflict 0, csv-mismatch 0, applied 1

  Scenario: an old year before the work year is not an edition year (Scenes from a Marriage)
    Given an edition film "SCENES FROM A MARRIAGE: Theatrical Version" year 1973 from "criterion" slug "https://c/sfam-theatrical"
    And the edition contract says the work is "Scenes from a Marriage" 1974 tt "tt6725014" tmdb "133919"
    When I run repair editions --apply answering yes
    Then the edition film is titled "Scenes from a Marriage" year 1974 with imdb "tt6725014" and tmdb "133919" and no disposition
    And its criterion claim has no edition_year

  Scenario: the target key is held by another live film → conflict, nothing written
    Given an edition film "Phantasm: Remastered" year 2016 from "apple-tv" slug "Phantasm: Remastered"
    And a work film "Phantasm" (1979) with tmdb id "1"
    And the edition contract says the work is "Phantasm" 1979 tt "tt0079714" tmdb "9638"
    When I run repair editions --apply answering yes
    Then the edition film's verdict is "conflict" and it has no disposition and year 2016

  Scenario: a second apply is a no-op
    Given an edition film "Blade Runner (The Final Cut)" year 2007 from "apple-tv" slug "Blade Runner (The Final Cut)"
    And the edition contract says the work is "Blade Runner" 1982 tt "tt0083658" tmdb "78"
    When I run repair editions --apply answering yes
    And I run repair editions --apply answering yes
    Then the editions report says twin 0, no-twin 0, conflict 0, csv-mismatch 0, applied 0
```

Step definitions (append to `tests/step_defs/test_thumbprint.py`):

```python
from movie_brain.application.repair import EditionContract, repair_editions


@given(parsers.parse('an edition film "{title}" year {year:d} from "{authority}" slug "{value}"'))
def edition_film(ctx, title, year, authority, value):
    from movie_brain.domain.thumbprint import parse_title, title_norm

    repo = ctx["repo"]
    fid = repo.create_film(Film(title, year, None, ""))
    assert fid is not None
    repo.set_title_norm(fid, title_norm(title))
    if authority != "apple-tv":
        repo.set_external_id(fid, authority, value, TODAY)
    repo.add_claim(fid, authority, value, title, year_claimed=year,
                   edition_label=" ".join(parse_title(title).editions) or None, first_seen=TODAY.isoformat())
    ctx.setdefault("editions", []).append(fid)
    ctx["edition"] = fid


@given(parsers.parse('a work film "{title}" ({year:d}) with tmdb id "{tid}"'))
def work_film(ctx, title, year, tid):
    from movie_brain.domain.thumbprint import title_norm

    repo = ctx["repo"]
    fid = repo.create_film(Film(title, year, "Dir", ""))
    assert fid is not None
    repo.set_title_norm(fid, title_norm(title))
    repo.set_external_id(fid, "tmdb", tid, TODAY)
    ctx.setdefault("works", {})[(title, year)] = fid
    ctx["work"] = fid


@given(parsers.parse('the edition contract says the work is "{work}" {year:d} tt "{tt}" tmdb "{tid}"'))
def contract_one(ctx, work, year, tt, tid):
    ctx["contract"] = {ctx["edition"]: EditionContract(ctx["edition"], work, year, tt, tid)}


@given(parsers.parse('the edition contract says the work is "{work}" {year:d} tt "{tt}" tmdb "{tid}" for both'))
def contract_both(ctx, work, year, tt, tid):
    ctx["contract"] = {fid: EditionContract(fid, work, year, tt, tid) for fid in ctx["editions"]}


@given("the edition film has an open tmdb no-match review")
def edition_review(ctx):
    from movie_brain.domain.models import ReviewEntry

    ctx["repo"].append_reviews("tmdb", [ReviewEntry("no-match", film_id=ctx["edition"], detail="x")], TODAY)


@when("I run repair editions --apply answering yes")
def run_editions(ctx):
    ctx["report"] = repair_editions(
        ctx["repo"], TODAY, apply=True, confirm=lambda g: True, contract=ctx["contract"], log=ctx["log"].append
    )


@then("the edition film is merged into the work film")
def edition_merged(ctx):
    assert ctx["repo"].disposition_of(ctx["edition"]) == ("merged", ctx["work"])


@then(parsers.parse('the edition film is merged into the work film "{title}" ({year:d})'))
def edition_merged_into(ctx, title, year):
    assert ctx["repo"].disposition_of(ctx["edition"]) == ("merged", ctx["works"][(title, year)])


@then(parsers.parse('the work film holds imdb "{tt}" and its metacritic claim has edition_year {y:d}'))
def work_keyed(ctx, tt, y):
    repo = ctx["repo"]
    assert repo.external_ids_for(ctx["work"])["imdb"] == tt
    assert repo.claim_for_film_authority(ctx["work"], "metacritic").edition_year == y


@then(parsers.parse("the editions report says twin {t:d}, no-twin {n:d}, conflict {c:d}, csv-mismatch {m:d}, applied {a:d}"))
def editions_report(ctx, t, n, c, m, a):
    r = ctx["report"]
    assert (r.twins, r.no_twin, r.conflict, r.csv_mismatch, r.applied) == (t, n, c, m, a)


@then(parsers.parse('the edition film is titled "{title}" year {year:d} with imdb "{tt}" and tmdb "{tid}" and no disposition'))
def edition_became_work(ctx, title, year, tt, tid):
    repo = ctx["repo"]
    row = _q(ctx, "SELECT title, year FROM films WHERE id = ?", ctx["edition"])[0]
    assert tuple(row) == (title, year)
    assert repo.external_ids_for(ctx["edition"]) == {"imdb": tt, "tmdb": tid}
    assert repo.disposition_of(ctx["edition"]) is None


@then(parsers.parse("its {authority} claim has edition_year {y:d}"))
def claim_year(ctx, authority, y):
    assert ctx["repo"].claim_for_film_authority(ctx["edition"], authority).edition_year == y


@then(parsers.parse("its {authority} claim has no edition_year"))
def claim_no_year(ctx, authority):
    assert ctx["repo"].claim_for_film_authority(ctx["edition"], authority).edition_year is None


@then("its tmdb no-match review is resolved")
def review_resolved(ctx):
    assert not [r for r in ctx["repo"].open_reviews("tmdb") if r["film_id"] == ctx["edition"]]


@then(parsers.parse('the film "{loser}" is merged into the film now titled "{title}" ({year:d}) holding tmdb "{tid}"'))
def darko(ctx, loser, title, year, tid):
    repo = ctx["repo"]
    lid = next(f for f in ctx["editions"] if _q(ctx, "SELECT title FROM films WHERE id = ?", f)[0][0] == loser)
    sid = next(f for f in ctx["editions"] if f != lid)
    assert repo.disposition_of(lid) == ("merged", sid)
    assert tuple(_q(ctx, "SELECT title, year FROM films WHERE id = ?", sid)[0]) == (title, year)
    assert repo.external_ids_for(sid)["tmdb"] == tid


@then(parsers.parse('the edition film\'s verdict is "{verdict}" and it has no disposition and year {year:d}'))
def edition_verdict(ctx, verdict, year):
    assert any(f"[{verdict}] #{ctx['edition']} " in line for line in ctx["log"]), ctx["log"]
    assert ctx["repo"].disposition_of(ctx["edition"]) is None
    assert _q(ctx, "SELECT year FROM films WHERE id = ?", ctx["edition"])[0][0] == year
```

Note the Donnie Darko scenario needs the audit to visit #3517 (2004 ≠ 2001) but skip #4404 (2001 == 2001); the "for both" contract makes #4404 a contract row so the agreement rule (no tmdb id + same tt) fires.

- [ ] **Step 3: Run → FAIL** (`ImportError`).

- [ ] **Step 4: Implement in `repair.py`**

```python
# --- editions: edition-year films → their work (thumbprint step 2) ------------------------

_WORK_NOTE = re.compile(r"work='(?P<title>.+?)' (?P<year>\d{4})")


@dataclass(frozen=True)
class EditionContract:
    film_id: int
    work_title_note: str  # informational (the CSV's TMDB title); the retitle uses parse_title().base
    work_year: int
    tt: str
    tmdb_id: str | None


@dataclass(frozen=True)
class EditionGroup:
    film_id: int
    title: str
    old_year: int | None
    work_title: str
    work_year: int
    tt: str
    tmdb_id: str | None
    verdict: str  # "twin" | "no-twin" | "conflict" | "csv-mismatch"
    twin_id: int | None
    edition_year: int | None
    detail: str


@dataclass(frozen=True)
class EditionsReport:
    groups: int
    twins: int
    no_twin: int
    conflict: int
    csv_mismatch: int
    applied: int
    declined: int


def load_edition_contract(csv_path: Path) -> dict[int, EditionContract]:
    """Verified group-C rows with an expected tt, keyed by film id; the note's `work='…' YYYY`
    is the work year."""
    out: dict[int, EditionContract] = {}
    if not csv_path.exists():
        return out
    with csv_path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            m = _WORK_NOTE.search(r.get("note") or "")
            if r["group"] != "C-edition" or r["status"] != "verified" or not r["expected_tt"] or not m:
                continue
            if not r["film_id"].isdigit():
                continue
            out[int(r["film_id"])] = EditionContract(
                int(r["film_id"]), m["title"], int(m["year"]), r["expected_tt"], r.get("expected_tmdb") or None
            )
    return out


def audit_editions(repo: Repository, contract: dict[int, EditionContract]) -> list[EditionGroup]:
    films = {f.id: f for f in repo.films_for_editions()}
    by_norm_year: dict[tuple[str, int | None], list[EditionFilm]] = defaultdict(list)
    for f in films.values():
        by_norm_year[(f.title_norm or title_norm(f.title), f.year)].append(f)
    tt_holders = {f.imdb_id: f.id for f in films.values() if f.imdb_id}
    tmdb_holders = {f.tmdb_id: f.id for f in films.values() if f.tmdb_id}
    groups: list[EditionGroup] = []
    for fid, c in sorted(contract.items()):
        f = films.get(fid)
        if f is None or f.year == c.work_year:
            continue  # disposed, or already at the work year (idempotence)
        p = parse_title(f.title)
        work_title = p.base
        edition_year = f.year if f.year is not None and f.year >= c.work_year else None
        base = (fid, f.title, f.year, work_title, c.work_year, c.tt, c.tmdb_id)
        if norm_title(work_title) != norm_title(c.work_title_note) and title_norm(work_title) != title_norm(c.work_title_note):
            groups.append(EditionGroup(*base, "csv-mismatch", None, edition_year,
                                       f"title parses to {work_title!r}, contract names {c.work_title_note!r}"))
            continue
        cands = [t for t in by_norm_year[(title_norm(work_title), c.work_year)] if t.id != fid]
        agreeing = [
            t for t in cands
            if (t.tmdb_id is not None and t.tmdb_id == c.tmdb_id)
            or (t.tmdb_id is None and t.id in contract and contract[t.id].tt == c.tt)
        ]
        if len(agreeing) == 1:
            t = agreeing[0]
            groups.append(EditionGroup(*base, "twin", t.id, edition_year,
                                       f"twin #{t.id} {t.title!r} ({t.year}) tmdb {t.tmdb_id or '-'}"))
        elif agreeing:
            groups.append(EditionGroup(*base, "conflict", None, edition_year,
                                       f"several agreeing twins {[t.id for t in agreeing]}"))
        else:
            key = film_key(work_title, c.work_year)
            key_holder = repo.film_id_by_key(key)
            blockers = []
            if key_holder is not None and repo.canonical_film_id(key_holder) != fid:
                blockers.append(f"key {key!r} held by #{key_holder}")
            if tt_holders.get(c.tt, fid) != fid:
                blockers.append(f"{c.tt} held by #{tt_holders[c.tt]}")
            if c.tmdb_id and tmdb_holders.get(c.tmdb_id, fid) != fid:
                blockers.append(f"tmdb {c.tmdb_id} held by #{tmdb_holders[c.tmdb_id]}")
            if blockers:
                groups.append(EditionGroup(*base, "conflict", None, edition_year, "; ".join(blockers)))
            else:
                groups.append(EditionGroup(*base, "no-twin", None, edition_year,
                                           f"becomes {work_title!r} ({c.work_year}) {c.tt}/{c.tmdb_id or '-'}"))
    return groups


def format_edition(g: EditionGroup) -> str:
    ey = f" edition_year {g.edition_year}" if g.edition_year else " edition_year NULL"
    return f"[{g.verdict}] #{g.film_id} {g.title!r} ({g.old_year}) → {g.work_title!r} ({g.work_year}){ey}: {g.detail}"


def _key_as_work(repo: Repository, fid: int, g: EditionGroup, today: date, log: Callable[[str], None]) -> bool:
    if not repo.key_work(fid, title=g.work_title, year=g.work_year, tt=g.tt, tmdb_id=g.tmdb_id, today=today):
        log("  key blocked (key/tt/tmdb held elsewhere); skipped")
        return False
    for r in repo.open_reviews("tmdb"):
        if r["film_id"] == fid and r["reason"] == "no-match":
            repo.resolve_review(int(r["id"]), f"repair editions keyed tmdb {g.tmdb_id or '-'} {today.isoformat()}")
    repo.mark_omdb_refresh(fid)
    repo.clear_revisit(fid)
    return True


def repair_editions(
    repo: Repository,
    today: date,
    *,
    apply: bool,
    confirm: Callable[[EditionGroup], bool],
    contract: dict[int, EditionContract],
    limit: int | None = None,
    log: Callable[[str], None] = _stderr,
) -> EditionsReport:
    """Dry-run lists every group; --apply merges each confirmed `twin` into its work and keys
    each confirmed `no-twin` as the work. `conflict` / `csv-mismatch` are never touched."""
    groups = audit_editions(repo, contract)
    if limit is not None:
        groups = groups[:limit]
    applied = declined = 0
    for g in groups:
        log(format_edition(g))
        if not apply or g.verdict not in ("twin", "no-twin"):
            continue
        if not confirm(g):
            declined += 1
            continue
        claim = None
        for auth in ("metacritic", "apple-tv", "criterion"):
            claim = claim or repo.claim_for_film_authority(g.film_id, auth)
        if g.verdict == "twin" and g.twin_id is not None:
            report = repo.merge_film(g.film_id, g.twin_id, today, note=f"repair editions {g.title!r}")
            log(f"  merged #{g.film_id} → #{g.twin_id}: moved {report.moved} dropped {report.dropped}")
            if claim is not None:
                repo.set_claim_edition_year(claim.id, g.edition_year)
            ids = repo.external_ids_for(g.twin_id)
            if "imdb" not in ids:
                repo.set_external_id(g.twin_id, "imdb", g.tt, today)
            twin_title = next(f.title for f in repo.films_for_editions() if f.id == g.twin_id)
            if parse_title(twin_title).editions and not _key_as_work(repo, g.twin_id, g, today, log):
                continue
        else:
            if not _key_as_work(repo, g.film_id, g, today, log):
                continue
            if claim is not None:
                repo.set_claim_edition_year(claim.id, g.edition_year)
            log(f"  keyed #{g.film_id} as {g.work_title!r} ({g.work_year}) {g.tt}/{g.tmdb_id or '-'}")
        applied += 1
    counts = {v: sum(1 for g in groups if g.verdict == v) for v in ("twin", "no-twin", "conflict", "csv-mismatch")}
    return EditionsReport(len(groups), counts["twin"], counts["no-twin"], counts["conflict"], counts["csv-mismatch"], applied, declined)
```

Imports needed at the top of `repair.py`: `EditionFilm` from `database`, `parse_title`, `title_norm` from `domain.thumbprint`, `film_key`, `norm_title` from `domain` (check existing imports — `parse_title`/`title_norm`/`norm_title` are already used by `audit_twins`). Ruff will flag the long lines — wrap them.

- [ ] **Step 5: Full gate; Step 6: Commit** — `"repair editions: contract-checked twin/no-twin fold of edition-year films"`

---

### Task 6: CLI `repair editions`

**Files:**
- Modify: `src/movie_brain/cli.py` (after `repair_twins_cmd`)
- Test: `tests/unit/test_cli.py`

- [ ] **Step 1: Failing test**

```python
def test_repair_editions_dry_run_lists_zero_groups(runner, config_dir):
    result = runner.invoke(app, ["repair", "editions"])
    assert result.exit_code == 0
    assert "groups: 0" in result.output
```

(Use the same `runner`/`app` fixture pattern the file already uses for `repair twins`; if none exists, copy the twins test's invocation.)

- [ ] **Step 2: Run → FAIL** (`No such command 'editions'`).

- [ ] **Step 3: Implement**

```python
@repair_app.command("editions")
def repair_editions_cmd(
    apply: Annotated[bool, typer.Option("--apply", help="Merge/key confirmed groups (default: dry-run).")] = False,
    yes: Annotated[bool, typer.Option("--yes", help="With --apply: confirm every group without prompting.")] = False,
    limit: Annotated[int | None, typer.Option("--limit", help="Only the first N groups (batch size).")] = None,
) -> None:
    """Fold edition-year films into their work (eval group C is the contract); old year → claim.edition_year."""
    from pathlib import Path

    eval_csv = Path(__file__).resolve().parents[2] / "scripts" / "eval" / "thumbprint_eval_v1.csv"
    contract = load_edition_contract(eval_csv)

    def confirm(g: EditionGroup) -> bool:
        target = f"merge → #{g.twin_id}" if g.verdict == "twin" else f"become {g.work_title!r} ({g.work_year})"
        return yes or typer.confirm(f"#{g.film_id} {g.title!r} {target}?", default=False)

    report = repair_editions(_repo(), date.today(), apply=apply, confirm=confirm, contract=contract, limit=limit, log=_plain)
    console.print(
        f"groups: {report.groups} · twin: {report.twins} · no-twin: {report.no_twin} · conflict: {report.conflict} · "
        f"csv-mismatch: {report.csv_mismatch} · applied: {report.applied} · declined: {report.declined}"
    )
```

- [ ] **Step 4: Full gate; Step 5: Commit** — `"cli: repair editions"`

---

### Task 7: `review_detail` query + `parse_review_detail` + A/B/C lines in `review list`

**Files:**
- Modify: `src/movie_brain/application/thumbprint.py` (`review_detail` ~L148), `src/movie_brain/cli.py` (`review_list`)
- Test: `tests/unit/test_thumbprint.py`, `tests/unit/test_cli.py`

**Interfaces (Produces):**
```python
def review_detail(verdict: Verdict, query: Query | None = None) -> str    # adds "query": {title, year, source, director, runtime} when given
class ReviewCandidate(TypedDict): letter: str; tt: str; tmdb_id: int | None; title: str; year: int | None; director: str; runtime: int | None; votes: int; in_tmdb: bool; in_omdb: bool; why_not: str | None
class ReviewDetail(NamedTuple): reason: str; candidates: list[ReviewCandidate]; query: dict[str, Any] | None
def parse_review_detail(detail: str | None) -> ReviewDetail | None            # None for legacy/non-JSON details
```

- [ ] **Step 1: Failing tests**

```python
def test_review_detail_round_trips_with_query():
    q = make_query("Blade Runner (The Final Cut)", 2007, "apple", director=None, runtime_min=117)
    c = Candidate("tt0083658", 78, ("Blade Runner",), 1982, "Ridley Scott", 117, 10000, "movie", True, True)
    v = Verdict("review", None, "rerelease-ambiguous", (Scored(c, 5, 3, 0, 0, False, False),))
    d = parse_review_detail(review_detail(v, q))
    assert d is not None and d.reason == "rerelease-ambiguous"
    assert d.candidates[0]["letter"] == "A" and d.candidates[0]["tt"] == "tt0083658"
    assert d.query == {"title": "Blade Runner (The Final Cut)", "year": 2007, "source": "apple", "director": None, "runtime": 117}


def test_parse_review_detail_returns_none_for_legacy_text():
    assert parse_review_detail("King Kong (1933)") is None
    assert parse_review_detail(None) is None
```

(Check `Scored`'s real field order in `domain/thumbprint.py` before writing the constructor call.)

- [ ] **Step 2: Run → FAIL. Step 3: Implement**

```python
def review_detail(verdict: Verdict, query: Query | None = None) -> str:
    ...  # existing body builds `cands`
    payload: dict[str, Any] = {"reason": verdict.reason, "candidates": cands}
    if query is not None:
        payload["query"] = {"title": query.raw_title, "year": query.year, "source": query.source,
                            "director": query.director, "runtime": query.runtime_min}
    return json.dumps(payload, ensure_ascii=False)


class ReviewDetail(NamedTuple):
    reason: str
    candidates: list[dict[str, Any]]
    query: dict[str, Any] | None


def parse_review_detail(detail: str | None) -> ReviewDetail | None:
    if not detail or not detail.lstrip().startswith("{"):
        return None
    body = detail[: detail.rfind("}") + 1]  # resolve_review appends " [note]" after the JSON
    try:
        obj = json.loads(body)
    except ValueError:
        return None
    if not isinstance(obj, dict) or "candidates" not in obj:
        return None
    return ReviewDetail(str(obj.get("reason", "")), list(obj["candidates"]), obj.get("query"))
```

`review list` in `cli.py`: after `table.add_row(...)` for a row, if `parse_review_detail(r["detail"])` is not None, replace the `detail` cell with `d.reason` and print, under the table, one line per candidate:
`console.print(f"  {r['id']} {c['letter']} {c['tt']} · {c['title']} ({c['year']}) · {c['director']} · {c['runtime'] or '-'}m · {c['why_not'] or 'best'}")`.
Unit test: seed a review row whose detail is `review_detail(v, q)` and assert `"A tt0083658"` appears in `runner.invoke(app, ["review", "list"]).output`.

- [ ] **Step 4: Full gate (thumbprint benchmark especially — `review_detail` signature change must not break `scripts/thumbprint_benchmark.py`; it doesn't call it). Step 5: Commit** — `"review detail: query object + parser; A/B/C lines in review list"`

---

### Task 8: `TmdbClient.find_by_imdb` + `eval_log.ratify`

**Files:**
- Modify: `src/movie_brain/infrastructure/tmdb.py`
- Create: `src/movie_brain/application/eval_log.py`
- Test: `tests/unit/test_tmdb.py`, `tests/unit/test_eval_log.py`

**Interfaces (Produces):**
```python
TmdbClient.find_by_imdb(tt: str) -> int | None      # GET /find/{tt}?external_source=imdb_id → first movie_results id
@dataclass(frozen=True)
class EvalEntry: film_id: int; source: str; title_ingested: str; year_ingested: int | None; expected_tt: str; expected_tmdb: str; note: str
def ratify(csv_path: Path, entry: EvalEntry) -> str    # "rewrote proposed row" | "appended"
```

- [ ] **Step 1: Failing tests**

```python
# tests/unit/test_tmdb.py (append; follow the file's `responses` pattern)
@responses.activate
def test_find_by_imdb_returns_first_movie_id():
    responses.add(responses.GET, f"{TMDB_API}/find/tt0083658", json={"movie_results": [{"id": 78}], "tv_results": []})
    assert TmdbClient("tok").find_by_imdb("tt0083658") == 78

@responses.activate
def test_find_by_imdb_none_when_empty():
    responses.add(responses.GET, f"{TMDB_API}/find/tt1", json={"movie_results": [], "tv_results": []})
    assert TmdbClient("tok").find_by_imdb("tt1") is None
```

```python
# tests/unit/test_eval_log.py
import csv
from pathlib import Path

from movie_brain.application.eval_log import EvalEntry, ratify

HEADER = "group,film_id,source,title_ingested,year_ingested,expected_tt,expected_tmdb,verified_by,note,status,director,runtime_min\n"


def _rows(p: Path):
    with p.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_ratify_appends_human_row(tmp_path: Path):
    p = tmp_path / "e.csv"
    p.write_text(HEADER)
    assert ratify(p, EvalEntry(1, "apple", "Blade Runner (The Final Cut)", 2007, "tt0083658", "78", "review 9 --tt")) == "appended"
    r = _rows(p)[0]
    assert (r["group"], r["status"], r["verified_by"], r["expected_tt"], r["expected_tmdb"]) == ("F-human", "verified", "human", "tt0083658", "78")


def test_ratify_rewrites_matching_proposed_row(tmp_path: Path):
    p = tmp_path / "e.csv"
    p.write_text(HEADER + "D-disagree,7,criterion,Tiger,2020,tt1,5,x,old note,proposed,Dir,90\n")
    assert ratify(p, EvalEntry(7, "criterion", "Tiger", 2020, "tt2", "6", "review 3 --tt")) == "rewrote proposed row"
    r = _rows(p)
    assert len(r) == 1
    assert (r[0]["status"], r[0]["verified_by"], r[0]["expected_tt"], r[0]["expected_tmdb"]) == ("verified", "human", "tt2", "6")
    assert "human: was tt1" in r[0]["note"] and r[0]["director"] == "Dir"


def test_ratify_none_marks_verified_unkeyed(tmp_path: Path):
    p = tmp_path / "e.csv"
    p.write_text(HEADER)
    ratify(p, EvalEntry(2, "criterion", "Short", None, "NONE", "", "review 4 --none"))
    assert _rows(p)[0]["expected_tt"] == "NONE"
```

- [ ] **Step 2: Run → FAIL. Step 3: Implement**

```python
# tmdb.py
    def find_by_imdb(self, tt: str) -> int | None:
        """TMDB movie id for an IMDb id (one call) — the reverse of imdb_id()."""
        hits = self._get(f"/find/{tt}", external_source="imdb_id").json().get("movie_results") or []
        return int(hits[0]["id"]) if hits else None
```

```python
# application/eval_log.py
"""The eval CSV is the resolver's contract; a human resolution is evidence and lands here.

`ratify` is the ONLY programmatic writer of `scripts/eval/thumbprint_eval_v1.csv`
(rules: never edit the CSV to make the gate green). It rewrites a `proposed` row for the same
film + source, else appends a `F-human` row. Atomic: temp file + os.replace."""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from pathlib import Path

FIELDS = ["group", "film_id", "source", "title_ingested", "year_ingested", "expected_tt", "expected_tmdb",
          "verified_by", "note", "status", "director", "runtime_min"]


@dataclass(frozen=True)
class EvalEntry:
    film_id: int
    source: str
    title_ingested: str
    year_ingested: int | None
    expected_tt: str  # "NONE" = verified unkeyed
    expected_tmdb: str
    note: str


def ratify(csv_path: Path, entry: EvalEntry) -> str:
    rows: list[dict[str, str]] = []
    if csv_path.exists():
        with csv_path.open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
    outcome = "appended"
    for r in rows:
        if r["film_id"] == str(entry.film_id) and r["source"] == entry.source and r["status"] == "proposed":
            was = f"; human: was {r['expected_tt'] or '-'}" if r["expected_tt"] != entry.expected_tt else ""
            r.update(expected_tt=entry.expected_tt, expected_tmdb=entry.expected_tmdb, verified_by="human",
                     status="verified", note=f"{r['note']}{was}; {entry.note}")
            outcome = "rewrote proposed row"
            break
    else:
        rows.append({
            "group": "F-human", "film_id": str(entry.film_id), "source": entry.source,
            "title_ingested": entry.title_ingested, "year_ingested": "" if entry.year_ingested is None else str(entry.year_ingested),
            "expected_tt": entry.expected_tt, "expected_tmdb": entry.expected_tmdb, "verified_by": "human",
            "note": entry.note, "status": "verified", "director": "", "runtime_min": "",
        })
    tmp = csv_path.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, csv_path)
    return outcome
```

- [ ] **Step 4: Full gate; Step 5: Commit** — `"eval_log.ratify + TmdbClient.find_by_imdb"`

---

### Task 9: `review resolve --pick / --tt / --none`

**Files:**
- Modify: `src/movie_brain/application/review.py`, `src/movie_brain/cli.py` (`review_resolve`)
- Test: `tests/features/review.feature`, `tests/step_defs/test_review.py`

**Interfaces:**
- Consumes: `parse_review_detail`, `ratify`/`EvalEntry`, `TmdbClient.find_by_imdb`, `record_tmdb_match`, `repo.tmdb_target`, `repo.claims_for_film`.
- Produces: `resolve_review(..., pick: str | None = None, tt: str | None = None, none: bool = False, eval_csv: Path | None = None, warn: Callable[[str], None] = lambda _m: None)`.

- [ ] **Step 1: Failing scenarios** (append to `review.feature`)

```gherkin
  Scenario: Picking candidate B keys the film to its tt and tmdb id and ratifies an eval row
    Given an open tmdb resolver review for "King Kong (1933)" with candidates A "tt0000001"/1 and B "tt0024216"/244
    And TMDB says id 244 was released in 1933
    When I resolve it with pick "B"
    Then "King Kong (1933)" holds imdb "tt0024216" and tmdb id "244"
    And the eval log has a verified human row for "King Kong (1933)" expecting "tt0024216"

  Scenario: --tt keys any tmdb no-match row, finding the tmdb id through TMDB
    Given an open tmdb "no-match" review for "King Kong (1933)"
    And TMDB finds "tt0024216" as id 244 released in 1933
    When I resolve it with tt "tt0024216"
    Then "King Kong (1933)" holds imdb "tt0024216" and tmdb id "244"
    And the eval log has a verified human row for "King Kong (1933)" expecting "tt0024216"

  Scenario: --tt without a TMDB client writes only the imdb id and warns
    Given an open tmdb "no-match" review for "King Kong (1933)"
    When I resolve it offline with tt "tt0024216"
    Then "King Kong (1933)" holds imdb "tt0024216" and no tmdb id
    And a warning mentions "tmdb id not resolved"

  Scenario: --none is a standing verified-unkeyed decision
    Given an open tmdb "no-match" review for "King Kong (1933)"
    When I resolve it with none
    Then the review is resolved
    And the eval log has a verified human row for "King Kong (1933)" expecting "NONE"
    And rebuilding the tmdb no-match queue queues nothing for "King Kong (1933)"

  Scenario: --pick on a row without candidates is refused
    Given an open tmdb "no-match" review for "King Kong (1933)"
    Then resolving it with pick "A" fails
```

Step defs (append to `test_review.py`; reuse `ctx`, `_id`, existing "the review is resolved" / "rebuilding … queues nothing" steps):

```python
import csv
from movie_brain.application.thumbprint import review_detail
from movie_brain.domain.thumbprint import Candidate, Scored, Verdict, make_query


@given(parsers.parse('an open tmdb resolver review for "{spec}" with candidates A "{tta}"/{ida:d} and B "{ttb}"/{idb:d}'))
def open_resolver_row(ctx, spec, tta, ida, ttb, idb):
    t, y = _split(spec)
    fid = _id(ctx["repo"], spec)
    ctx["repo"].upsert_tmdb(fid, found=False, looked_up=TODAY)
    cands = [Candidate(tta, ida, (t,), y, "A Dir", 90, 10, "movie", True, True),
             Candidate(ttb, idb, (t,), y, "B Dir", 100, 20, "movie", True, True)]
    v = Verdict("review", None, "ambiguous", tuple(Scored(c, 1, 3, 0, 0, False, False) for c in cands))
    detail = review_detail(v, make_query(t, y, "criterion"))
    ctx["repo"].append_reviews("tmdb", [ReviewEntry("no-match", film_id=fid, detail=detail)], TODAY)
    ctx["review_id"] = ctx["repo"].open_reviews("tmdb")[-1]["id"]


@given(parsers.parse('TMDB finds "{tt}" as id {tid:d} released in {year:d}'))
def tmdb_find(ctx, tt, tid, year):
    ctx["rs"].add(responses.GET, f"{TMDB_API}/find/{tt}", json={"movie_results": [{"id": tid}]})
    ctx["rs"].add(responses.GET, f"{TMDB_API}/movie/{tid}", json={"id": tid, "release_date": f"{year}-01-01"})
    ctx["client"] = TmdbClient("tok")


def _resolve(ctx, **kw):
    ctx["warnings"] = []
    return rv.resolve_review(ctx["repo"], ctx["review_id"], today=TODAY, client=ctx["client"],
                             eval_csv=ctx["config_dir"] / "eval.csv", warn=ctx["warnings"].append, **kw)


@when(parsers.parse('I resolve it with pick "{letter}"'))
def do_pick(ctx, letter):
    _resolve(ctx, pick=letter)


@when(parsers.parse('I resolve it with tt "{tt}"'))
def do_tt(ctx, tt):
    _resolve(ctx, tt=tt)


@when(parsers.parse('I resolve it offline with tt "{tt}"'))
def do_tt_offline(ctx, tt):
    ctx["client"] = None
    _resolve(ctx, tt=tt)


@when("I resolve it with none")
def do_none(ctx):
    _resolve(ctx, none=True)


@then(parsers.parse('"{spec}" holds imdb "{tt}" and tmdb id "{tid}"'))
def holds_both(ctx, spec, tt, tid):
    assert ctx["repo"].external_ids_for(_id(ctx["repo"], spec)) == {"imdb": tt, "tmdb": tid}


@then(parsers.parse('"{spec}" holds imdb "{tt}" and no tmdb id'))
def holds_imdb_only(ctx, spec, tt):
    assert ctx["repo"].external_ids_for(_id(ctx["repo"], spec)) == {"imdb": tt}


@then(parsers.parse('a warning mentions "{text}"'))
def warned(ctx, text):
    assert any(text in w for w in ctx["warnings"]), ctx["warnings"]


@then(parsers.parse('the eval log has a verified human row for "{spec}" expecting "{tt}"'))
def eval_row(ctx, spec, tt):
    fid = _id(ctx["repo"], spec)
    with (ctx["config_dir"] / "eval.csv").open(encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["film_id"] == str(fid)]
    assert rows and rows[-1]["expected_tt"] == tt and rows[-1]["status"] == "verified" and rows[-1]["verified_by"] == "human"


@then(parsers.parse('resolving it with pick "{letter}" fails'))
def pick_fails(ctx, letter):
    with pytest.raises(ValueError):
        _resolve(ctx, pick=letter)
```

- [ ] **Step 2: Run → FAIL. Step 3: Implement in `review.py`**

Extend the signature and the exclusivity check:

```python
    pick: str | None = None,
    tt: str | None = None,
    none: bool = False,
    eval_csv: Path | None = None,
    warn: Callable[[str], None] = lambda _m: None,
...
    chosen = [x for x in (film_id is not None, tmdb_id is not None, create, dismiss, pick is not None, tt is not None, none) if x]
    if len(chosen) != 1:
        raise ValueError("choose exactly one of --film, --tmdb-id, --create, --dismiss, --pick, --tt, --none")
```

New branch, placed BEFORE the existing `elif authority == TMDB_AUTHORITY` so it wins for tmdb rows:

```python
    elif pick is not None or tt is not None or none:
        if authority != TMDB_AUTHORITY or rid is None:
            raise ValueError("--pick/--tt/--none apply to tmdb rows for a film")
        parsed = parse_review_detail(str(row["detail"]) if row["detail"] else None)
        chosen_tt: str
        chosen_tmdb: int | None = None
        if pick is not None:
            if parsed is None:
                raise ValueError(f"review {review_id} has no A/B/C candidates — use --tt or --none")
            cand = next((c for c in parsed.candidates if c["letter"] == pick.upper()), None)
            if cand is None:
                raise ValueError(f"no candidate {pick!r} on review {review_id}")
            chosen_tt, chosen_tmdb = str(cand["tt"]), cand.get("tmdb_id")
        elif tt is not None:
            chosen_tt = tt
            chosen_tmdb = client.find_by_imdb(tt) if client is not None else None
            if chosen_tmdb is None:
                warn(f"tmdb id not resolved for {tt} (no client or no TMDB record); imdb only")
        else:
            chosen_tt = "NONE"
        if chosen_tt != "NONE":
            try:
                repo.set_external_id(rid, "imdb", chosen_tt, today)
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"{chosen_tt} is already held by film {repo.film_id_for_external('imdb', chosen_tt)}") from exc
            if chosen_tmdb is not None:
                target = repo.tmdb_target(rid)
                if target is None:
                    raise ValueError(f"film {rid} not found")
                year = client.movie_year(chosen_tmdb) if client is not None else None
                result = record_tmdb_match(repo, target, chosen_tmdb, year, today, lambda _m: None)
                if result == "id-conflict":
                    raise ValueError(f"tmdb id {chosen_tmdb} is already held by another film — merge instead")
            outcome = f"keyed imdb {chosen_tt} tmdb {chosen_tmdb or '-'}"
        else:
            outcome = "verified unkeyed"
        if eval_csv is not None:
            q = parsed.query if parsed is not None and parsed.query else None
            film = repo.get_view(rid, today)
            claims = repo.claims_for_film(rid)
            source = str(q["source"]) if q else (
                next((c.authority for c in claims if c.authority == "criterion"), None)
                or next((c.authority for c in claims if c.authority == "metacritic"), None)
                or ("apple" if any(c.authority == "apple-tv" for c in claims) else "unknown"))
            entry = EvalEntry(rid, source,
                              str(q["title"]) if q else (film.title if film else ""),
                              int(q["year"]) if q and q["year"] else (film.year if film else None),
                              chosen_tt, "" if chosen_tmdb is None else str(chosen_tmdb),
                              f"review {review_id} {'--pick ' + pick if pick else '--tt' if tt else '--none'}")
            ratify(eval_csv, entry)
```

Imports: `from pathlib import Path`, `from collections.abc import Callable`, `from movie_brain.application.eval_log import EvalEntry, ratify`, `from movie_brain.application.thumbprint import parse_review_detail` (thumbprint.py must not import review.py — check; it doesn't).

CLI: add `--pick`, `--tt`, `--none` options and a hidden `--eval-csv` (`typer.Option(None, "--eval-csv", hidden=True)`, default = repo `scripts/eval/thumbprint_eval_v1.csv`); pass `warn=err.print`.

- [ ] **Step 4: Full gate (the real eval CSV must be byte-identical: `git diff --stat scripts/eval/` empty). Step 5: Commit** — `"review resolve --pick/--tt/--none: key the film, ratify an eval row"`

---

### Task 10: Rules + docs

**Files:**
- Modify: `.claude/rules/thumbprint.md`, `CLAUDE.md`

- [ ] **Step 1: `thumbprint.md`** — add:
  - `repair editions` line: eval group C is the contract; twin = agreeing tmdb id (or a fellow C-row with the same tt); `edition_year = old films.year` unless older than the work year; never touches `omdb`/`owned`/`listings`.
  - external_ids policy: PK `(film_id, authority, value)` since 012; `KEY_AUTHORITIES` single per film; claim authorities repeat; read models pick one metacritic slug (`_MC_SLUG_SQL`).
  - `review resolve --pick/--tt/--none` ratifies through `eval_log.ratify` (the only programmatic CSV writer); run `thumbprint_benchmark.py --refresh` after a ratification batch — cache-miss rows score as `review`, never a gate failure.
  - `review_detail(verdict, query)` — `query` is optional but every resolver-written row should pass it.
- [ ] **Step 2: `CLAUDE.md`** — commands block: add `repair editions`, extend `review resolve` line with `--pick A|B|C | --tt X | --none`; `external_ids` bullet per spec §3.4.
- [ ] **Step 3: Commit** — `"docs: T2 rules — editions verb, external_ids policy, A/B/C resolve"`

---

### Task 11: Scratch rehearsal (no live writes)

- [ ] **Step 1: Copy**

```bash
S=/private/tmp/claude-501/-Users-jayers-code-movie-brain/6166484e-a253-4b8a-aeb3-e9ef5b018505/scratchpad/t2
mkdir -p "$S" && cp ~/.config/movie-brain/movie-brain.db "$S/" && cp -r ~/.config/movie-brain/appletv "$S/" && cp ~/.config/movie-brain/*.txt "$S/"
cp scripts/eval/thumbprint_eval_v1.csv "$S/eval.csv"
sqlite3 "$S/movie-brain.db" "SELECT count(*) FROM external_ids"   # A
```

- [ ] **Step 2: Migration** — `MOVIE_BRAIN_CONFIG_DIR=$S uv run movie-brain status`; then `sqlite3 "$S/movie-brain.db" "SELECT max(version) FROM schema_version; SELECT count(*) FROM external_ids"` → 12 and A. `ls $S/backups/` shows the v11 backup.
- [ ] **Step 3: Dry run** — `MOVIE_BRAIN_CONFIG_DIR=$S uv run movie-brain repair editions` → expect `groups: 16 · twin: 10 · no-twin: 6 · conflict: 0 · csv-mismatch: 0`; paste all 16 `[verdict]` lines to the owner.
- [ ] **Step 4: Apply** — `… repair editions --apply --yes`; then counts:
  `SELECT count(*) FROM film_disposition` (102 → 112), `SELECT count(*) FROM claim WHERE edition_year IS NOT NULL` (0 → 15), `SELECT count(*) FROM external_ids WHERE authority='imdb'` (549 → 565), open tmdb no-match (225 → 209), `SELECT count(*) FROM films` (4,666), `SELECT id,title,year FROM films WHERE id IN (4404,4409,3461,3999,4070,4293,1909)` (retitled works). Second `--apply --yes` → `groups: 0`.
- [ ] **Step 5: Review verbs** — pick one open no-match row on scratch; `… review resolve ID --tt ttXXXX --eval-csv $S/eval.csv` and another with `--none --eval-csv $S/eval.csv`; show the two new CSV rows; `git diff --stat scripts/eval/` empty.
- [ ] **Step 6: Dashboard smoke** — `MOVIE_BRAIN_CONFIG_DIR=$S uv run movie-brain dashboard --port 5599` in background, `curl -s localhost:5599/api/films | python3 -c 'import json,sys; v=json.load(sys.stdin); print(len(v), sum(1 for f in v if f["title"]=="Blade Runner"))'` → one Blade Runner. Kill it.
- [ ] **Step 7: Report numbers to the owner; wait for yes.**

---

### Task 12: Live apply (owner-gated, batches)

- [ ] **Step 1: Snapshot** — `cp ~/.config/movie-brain/movie-brain.db ~/.config/movie-brain/movie-brain.db.bak-pre-t2`.
- [ ] **Step 2: Migration 012** — `uv run movie-brain status` (auto-backup to `backups/movie-brain-v11-<date>.db`); verify version 12 and unchanged `external_ids` count. Report.
- [ ] **Step 3: Dry run** — `uv run movie-brain repair editions`; paste the 16 lines; wait for yes.
- [ ] **Step 4: Batches** — `uv run movie-brain repair editions --apply --yes --limit 8` twice (owner yes before each); paste before/after counts from Task 11 Step 4 after each batch.
- [ ] **Step 5: Verify** — second apply → `groups: 0`; `uv run movie-brain audit run --no-tmdb` tally unchanged or better; full gate green.
- [ ] **Step 6: Handoff** — status note at the top of this plan (live numbers), update memory `thumbprint-t2-entry` → T2 done / T3 = memo step 3; ask before merging the branch.
