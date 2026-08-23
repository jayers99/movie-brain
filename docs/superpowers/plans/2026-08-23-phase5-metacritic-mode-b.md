# Phase 5: Metacritic Mode B (top-N dial) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote the top-N staged Metacritic titles into real films (guid identity, dedup-guarded), run promotion nightly inside sync from the offline archive, and give the dashboard a scope toggle so Mode-B films are visible while the default view keeps exact Criterion parity.

**Architecture:** Hexagonal — repository primitives first (`create_film` etc.), then the `promote_top_n` use case built on the existing Mode-A `match_archive` (dedup guard), then sync wiring with its own tripwire. The main view SQL flips from an INNER to a LEFT criterion join; scope filtering stays client-side like every other filter. Quiet-first-provider-check and OMDb widening are independent slices.

**Tech Stack:** Python 3.12, SQLite (raw SQL in `infrastructure/database.py`), Flask + vanilla JS, Typer CLI, pytest + pytest-bdd + responses + Playwright, uv, ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-08-23-phase5-metacritic-mode-b-design.md`

## Global Constraints

- Collectors never delete; anomalies go to `match_review`, never overwrite or drop films.
- Film identity = `films.guid`; integer `id` never leaks as identity; `film_key` is a matching aid and conflict target only.
- No scraping in sync — promotion reads only the local archive.
- Never edit an applied migration. **This phase needs no migration** (meta rows need no schema).
- Chip names/predicates: `CHIP_PREDICATES` in `app.js` stays in lockstep with `_PREDICATES` in `domain/filters.py` (this phase adds no chip — scope is a separate control).
- All commands via `uv run …`. Gate: `uv run pytest` + `uv run ruff check .` + `uv run mypy` green after every task.
- Dashboard, 3 AM sync, and Phase 4 alerts must keep working; default dashboard view keeps exact Criterion parity.
- TDD: failing test first, minimal code, green, commit. Branch per git conventions: `feature/PHASE5-metacritic-mode-b` (worktree via superpowers:using-git-worktrees).

---

### Task 1: Repository primitives for promotion

**Files:**
- Modify: `src/movie_brain/infrastructure/database.py` (after `film_id_by_key`, ~line 170, and in the metacritic section ~line 317)
- Test: `tests/unit/test_database.py`

**Interfaces:**
- Consumes: existing `Repository`, `Film`, `McTitle`, `ReviewEntry` (from `movie_brain.domain.models`).
- Produces (Task 2 relies on these exact signatures):
  - `create_film(self, film: Film) -> int | None` — insert with fresh guid; `None` if the key already exists (no update ever).
  - `claimed_values(self, authority: str) -> set[str]` — all `external_ids.value` for an authority.
  - `append_reviews(self, authority: str, entries: list[ReviewEntry], created: date) -> None` — insert-only (unlike `replace_unresolved_reviews`).
  - `top_staged_titles(self, n: int) -> list[McTitle]` — staged rows with `rank <= n`, ordered by rank.
  - `staged_title_count(self) -> int`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_database.py` (match its existing style — it uses the `repo` fixture from `tests/conftest.py`):

```python
from movie_brain.domain.models import Film, McTitle, ReviewEntry


def test_create_film_inserts_with_guid_and_never_updates(repo):
    fid = repo.create_film(Film("Fresh Find", 2020, None, ""))
    assert fid is not None
    # Same key again: no insert, no update, None back.
    assert repo.create_film(Film("Fresh Find", 2020, "Someone", "")) is None
    import sqlite3

    conn = sqlite3.connect(repo.db_path)
    row = conn.execute("SELECT guid, director FROM films WHERE id = ?", (fid,)).fetchone()
    conn.close()
    assert row[0] and row[1] is None  # guid assigned; director untouched by the second call


def test_claimed_values_lists_an_authoritys_ids(repo):
    fid = repo.create_film(Film("Fresh Find", 2020, None, ""))
    repo.set_external_id(fid, "metacritic", "fresh-find", date(2026, 8, 19))
    assert repo.claimed_values("metacritic") == {"fresh-find"}
    assert repo.claimed_values("tmdb") == set()


def test_append_reviews_adds_without_deleting(repo):
    day = date(2026, 8, 19)
    repo.replace_unresolved_reviews("metacritic", [ReviewEntry("ambiguous-title", value="a")], day)
    repo.append_reviews("metacritic", [ReviewEntry("key-conflict", value="b")], day)
    reasons = {r["reason"] for r in repo.open_reviews("metacritic")}
    assert reasons == {"ambiguous-title", "key-conflict"}


def test_top_staged_titles_bounds_by_rank(repo):
    day = date(2026, 8, 19)
    repo.upsert_mc_titles(
        [
            McTitle("first", "First", 2020, 99, 1, 1),
            McTitle("second", "Second", 2021, 98, 2, 1),
            McTitle("third", "Third", 2022, 97, 3, 1),
        ],
        day,
    )
    assert [t.slug for t in repo.top_staged_titles(2)] == ["first", "second"]
    assert repo.staged_title_count() == 3
```

(`date` is already imported in that file; if not, add `from datetime import date`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_database.py -k "create_film or claimed_values or append_reviews or top_staged" -v`
Expected: FAIL — `AttributeError: 'Repository' object has no attribute 'create_film'` (etc.)

- [ ] **Step 3: Implement the five methods**

In `database.py`, after `film_id_by_key`:

```python
    def create_film(self, film: Film) -> int | None:
        """Insert a brand-new film (fresh guid) — never updates an existing row.

        Returns None on a key collision: promotion's tripwire, handled by the caller
        as a match_review entry, never an overwrite.
        """
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO films (guid, title, year, director, key) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(key) DO NOTHING",
                (str(uuid.uuid4()), film.title, film.year, film.director, film.key),
            )
            if cur.rowcount == 0:
                return None
            return int(c.execute("SELECT id FROM films WHERE key = ?", (film.key,)).fetchone()["id"])
```

After `external_ids_for`:

```python
    def claimed_values(self, authority: str) -> set[str]:
        with self._conn() as c:
            rows = c.execute("SELECT value FROM external_ids WHERE authority = ?", (authority,)).fetchall()
            return {str(r["value"]) for r in rows}
```

After `replace_unresolved_reviews`:

```python
    def append_reviews(self, authority: str, entries: list[ReviewEntry], created: date) -> None:
        with self._conn() as c:
            for e in entries:
                c.execute(
                    "INSERT INTO match_review (authority, film_id, value, reason, detail, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (authority, e.film_id, e.value, e.reason, e.detail, created.isoformat()),
                )
```

After `upsert_mc_titles`:

```python
    def top_staged_titles(self, n: int) -> list[McTitle]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT slug, title, year, score, rank, page FROM metacritic WHERE rank <= ? ORDER BY rank",
                (n,),
            ).fetchall()
            return [
                McTitle(str(r["slug"]), str(r["title"]), r["year"], r["score"], int(r["rank"]), int(r["page"]))
                for r in rows
            ]

    def staged_title_count(self) -> int:
        with self._conn() as c:
            return int(c.execute("SELECT COUNT(*) FROM metacritic").fetchone()[0])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_database.py -v`
Expected: PASS (all, including pre-existing).

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run mypy
git add src/movie_brain/infrastructure/database.py tests/unit/test_database.py
git commit -m "Repository primitives for Mode-B promotion: insert-only film creation, review append, staged top-N"
```

---

### Task 2: `promote_top_n` use case

**Files:**
- Modify: `src/movie_brain/application/metacritic.py`
- Test: `tests/features/metacritic.feature`, `tests/step_defs/test_metacritic.py`

**Interfaces:**
- Consumes: Task 1 methods; existing `match_archive`, `clean_title`, `AUTHORITY`, `Film`, `ReviewEntry`.
- Produces (Task 3 relies on these):
  - `MC_TOP_N_KEY = "mc_top_n"`, `DEFAULT_TOP_N = 100` (module constants in `application/metacritic.py`)
  - `promote_top_n(repo: Repository, config_dir: Path, today: date, n: int, *, log: Callable[[str], None] = _stderr) -> PromoteReport`
  - `PromoteReport` frozen dataclass: `exit_code: int, n: int, available: int, promoted: int, already_linked: int, skipped_anomalous: int, key_conflicts: int, match: MatchReport | None`

- [ ] **Step 1: Write the failing scenarios**

Append to `tests/features/metacritic.feature`:

```gherkin
  Scenario: Promotion creates real films for unmatched top-N titles
    Given the archive holds "Fresh Find" (2020) scored 95 as "fresh-find"
    When I promote the top 10
    Then the film "Fresh Find (2020)" exists with a guid
    And "Fresh Find (2020)" has metacritic slug "fresh-find"
    And the promote report says 1 promoted

  Scenario: Promotion never twins a film the matcher already linked
    Given the repository holds the film "Seven Samurai (1954)"
    And the archive holds "Seven Samurai" (1956) scored 98 as "seven-samurai-1954"
    When I promote the top 10
    Then "Seven Samurai (1954)" has metacritic slug "seven-samurai-1954"
    And the repository holds 1 films
    And the promote report says 0 promoted

  Scenario: The dial bounds promotion by rank
    Given the archive holds "First" (2020) scored 99 as "first"
    And the archive holds "Second" (2021) scored 98 as "second"
    When I promote the top 1
    Then the repository holds 1 films

  Scenario: Two staged titles colliding on one key promote once and queue a review
    Given the archive holds "Solaris" (2002) scored 90 as "solaris"
    And the archive holds "Solaris" (2002) scored 90 as "solaris-2002"
    When I promote the top 10
    Then the repository holds 1 films
    And the review queue has a "key-conflict" entry

  Scenario: An ambiguous staged title is skipped, not promoted
    Given the repository holds the film "Twin (1978)"
    And the repository holds the film "Twin (1980)"
    And the archive holds "Twin" (1979) scored 90 as "twin-1979"
    When I promote the top 10
    Then the repository holds 2 films
    And the review queue has an "ambiguous-title" entry

  Scenario: Re-running promotion is idempotent
    Given the archive holds "Fresh Find" (2020) scored 95 as "fresh-find"
    When I promote the top 10
    And I promote the top 10
    Then the repository holds 1 films
    And the promote report says 0 promoted
```

Append to `tests/step_defs/test_metacritic.py` (imports: add `promote_top_n` to the existing `from movie_brain.application.metacritic import …` line):

```python
def _write_archive(ctx):
    archive = archive_dir(ctx["config_dir"])
    if ctx["cards"]:
        p = page_path(archive, 1)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(ctx["nuxt_page"](ctx["cards"]))
    for page, cards in ctx["pages"].items():
        p = page_path(archive, page)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(ctx["nuxt_page"](cards))


@when(parsers.parse("I promote the top {n:d}"))
def run_promote(ctx, n):
    _write_archive(ctx)
    ctx["report"] = promote_top_n(ctx["repo"], ctx["config_dir"], TODAY, n, log=lambda m: None)


@then(parsers.parse('the film "{title_year}" exists with a guid'))
def film_exists_with_guid(ctx, title_year):
    import sqlite3 as _sqlite3

    fid = ctx["repo"].film_id_by_key(_film(title_year).key)
    assert fid is not None
    conn = _sqlite3.connect(ctx["repo"].db_path)
    guid = conn.execute("SELECT guid FROM films WHERE id = ?", (fid,)).fetchone()[0]
    conn.close()
    assert guid


@then(parsers.parse("the repository holds {n:d} films"))
def repository_film_count(ctx, n):
    assert len(ctx["repo"].films_for_matching()) == n


@then(parsers.parse("the promote report says {n:d} promoted"))
def promote_count(ctx, n):
    assert ctx["report"].promoted == n
```

Also refactor the existing `run_match` step to call the new `_write_archive(ctx)` helper instead of its inline copy of the same loop (behavior unchanged).

- [ ] **Step 2: Run to verify the new scenarios fail**

Run: `uv run pytest tests/step_defs/test_metacritic.py -v`
Expected: new scenarios FAIL with `ImportError`/`NameError` on `promote_top_n`; existing scenarios PASS.

- [ ] **Step 3: Implement `promote_top_n`**

In `src/movie_brain/application/metacritic.py`, after `MatchReport` add:

```python
MC_TOP_N_KEY = "mc_top_n"
DEFAULT_TOP_N = 100
MC_MOVIE_URL = "https://www.metacritic.com/movie/{slug}/"


@dataclass(frozen=True)
class PromoteReport:
    exit_code: int
    n: int
    available: int  # staged titles within rank <= n (short archive → available < n)
    promoted: int
    already_linked: int
    skipped_anomalous: int
    key_conflicts: int
    match: MatchReport | None = None
```

After `match_archive` add:

```python
def promote_top_n(
    repo: Repository,
    config_dir: Path,
    today: date,
    n: int,
    *,
    log: Callable[[str], None] = _stderr,
) -> PromoteReport:
    """Mode B: turn the top-N staged titles into real films (offline, idempotent).

    match_archive runs first so every slug an existing film can claim is claimed —
    the dedup guard. Promotion then only ever creates films for slugs nobody owns;
    a film_key collision is the tripwire and queues for review, never overwrites.
    """
    match_report = match_archive(repo, config_dir, today, log=log)
    if match_report.exit_code != 0:
        return PromoteReport(1, n, 0, 0, 0, 0, 0, match_report)
    claimed = repo.claimed_values(AUTHORITY)
    anomalous = {str(r["value"]) for r in repo.open_reviews(AUTHORITY) if r["value"]}
    candidates = repo.top_staged_titles(n)
    reviews: list[ReviewEntry] = []
    promoted = already_linked = skipped = conflicts = 0
    for t in candidates:
        if t.slug in claimed:
            already_linked += 1
            continue
        if t.slug in anomalous:
            skipped += 1
            continue
        film = Film(clean_title(t.title), t.year, None, MC_MOVIE_URL.format(slug=t.slug))
        film_id = repo.create_film(film)
        if film_id is None:
            conflicts += 1
            detail = f"promotion of {t.title!r} ({t.year}) collides with existing key {film.key!r}"
            reviews.append(ReviewEntry("key-conflict", film_id=repo.film_id_by_key(film.key), value=t.slug, detail=detail))
            continue
        try:
            repo.set_external_id(film_id, AUTHORITY, t.slug, today)
        except sqlite3.IntegrityError:
            reviews.append(
                ReviewEntry("slug-conflict", film_id=film_id, value=t.slug, detail="slug already claimed by another film")
            )
            continue
        claimed.add(t.slug)
        promoted += 1
    if reviews:
        repo.append_reviews(AUTHORITY, reviews, today)
    return PromoteReport(0, n, len(candidates), promoted, already_linked, skipped, conflicts, match_report)
```

Add `Film` to the existing `from movie_brain.domain.models import …` line.

Note on review lifecycle: `match_archive` (which runs first, every time) clears unresolved entries for the authority and rewrites match anomalies; promotion then appends its own — so combined runs stay recompute-idempotent with no duplicate entries.

- [ ] **Step 4: Run the metacritic suite**

Run: `uv run pytest tests/step_defs/test_metacritic.py tests/unit -v`
Expected: PASS.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run mypy
git add src/movie_brain/application/metacritic.py tests/features/metacritic.feature tests/step_defs/test_metacritic.py
git commit -m "Mode-B promotion: top-N staged titles become guid films behind the match dedup guard"
```

---

### Task 3: Sync integration (the nightly dial)

**Files:**
- Modify: `src/movie_brain/application/sync.py`, `src/movie_brain/cli.py` (sync command only)
- Test: `tests/features/sync.feature`, `tests/step_defs/test_sync.py`

**Interfaces:**
- Consumes: `promote_top_n`, `PromoteReport`, `MC_TOP_N_KEY`, `DEFAULT_TOP_N` from Task 2; `CARDS_PER_PAGE` from `movie_brain.infrastructure.metacritic`.
- Produces: `sync(…, config_dir: Path | None = None, …)` keyword param; `SyncResult.mc_promoted: int = 0`.

- [ ] **Step 1: Write the failing scenarios**

Append to `tests/features/sync.feature`:

```gherkin
  Scenario: Sync promotes staged Metacritic titles into films
    Given the Criterion browse page exposes a token
    And the Criterion catalog has films "Alpha (1950)"
    And OMDb knows every film
    And the metacritic archive holds "Fresh Find" (2020) scored 95 as "fresh-find"
    When I sync with a metacritic archive
    Then the exit code is 0
    And the repository holds a film for key "fresh find (2020)"

  Scenario: A missing metacritic archive never breaks the sync
    Given the Criterion browse page exposes a token
    And the Criterion catalog has films "Alpha (1950)"
    And OMDb knows every film
    When I sync with a metacritic archive
    Then the exit code is 0
```

In `tests/step_defs/test_sync.py`: change the `ctx` fixture signature to `def ctx(repo, config_dir, nuxt_page):` and yield `"config_dir": config_dir, "nuxt_page": nuxt_page, "mc_cards": []` alongside the existing keys. Add:

```python
@given(
    parsers.re(
        r'the metacritic archive holds "(?P<title>[^"]+)" \((?P<year>\d+)\) scored (?P<score>\d+) as "(?P<slug>[^"]+)"'
    )
)
def metacritic_archive(ctx, title, year, score, slug):
    from movie_brain.infrastructure.metacritic import archive_dir, page_path

    ctx["mc_cards"].append((title, slug, int(year), int(score)))
    p = page_path(archive_dir(ctx["config_dir"]), 1)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(ctx["nuxt_page"](ctx["mc_cards"]))


@when("I sync with a metacritic archive")
def run_sync_with_archive(ctx):
    _run(ctx, config_dir=ctx["config_dir"])


@then(parsers.parse('the repository holds a film for key "{key}"'))
def holds_film_key(ctx, key):
    assert ctx["repo"].film_id_by_key(key) is not None
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/step_defs/test_sync.py -v`
Expected: new scenarios FAIL (`sync() got an unexpected keyword argument 'config_dir'`); existing PASS.

- [ ] **Step 3: Implement the sync step**

In `src/movie_brain/application/sync.py`:

- Imports: `from pathlib import Path`; `from movie_brain.application.metacritic import DEFAULT_TOP_N, MC_TOP_N_KEY, promote_top_n`; `from movie_brain.infrastructure.metacritic import CARDS_PER_PAGE`.
- `SyncResult`: add field `mc_promoted: int = 0` (after `tmdb_watchlist_refreshed`).
- `sync(…)` signature: add keyword param `config_dir: Path | None = None` (after `tmdb_token`).
- Immediately after the Criterion catalog block (after the `set_leaving` try/except, before the OMDb loop — promoted films must exist before OMDb/TMDB so they're covered the same night):

```python
    mc_promoted = 0
    if not ratings_only and config_dir is not None:
        try:
            n = int(repo.get_meta(MC_TOP_N_KEY) or DEFAULT_TOP_N)
            promote = promote_top_n(repo, config_dir, today, n, log=log)
            mc_promoted = promote.promoted
            if promote.exit_code == 0 and promote.available < promote.n:
                pages = -(-promote.n // CARDS_PER_PAGE)
                log(
                    f"metacritic archive holds {promote.available} of top-{promote.n} titles — "
                    f"run: movie-brain metacritic crawl --pages {pages}"
                )
        except Exception as exc:  # noqa: BLE001 — the dial must never break the sync
            log(f"metacritic promotion failed: {exc}")
```

- Final `return SyncResult(…)`: pass `mc_promoted` as the new field.

In `src/movie_brain/cli.py` `sync_cmd`: pass `config_dir=cfg.config_dir` to `sync(…)` and extend the summary print with `· promoted: {result.mc_promoted}`.

- [ ] **Step 4: Run the sync + cli suites**

Run: `uv run pytest tests/step_defs/test_sync.py tests/unit/test_cli.py -v`
Expected: PASS (existing sync scenarios pass `config_dir=None` implicitly — promotion skipped).

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run mypy
git add src/movie_brain/application/sync.py src/movie_brain/cli.py tests/features/sync.feature tests/step_defs/test_sync.py
git commit -m "Nightly sync runs the Mode-B dial from the offline archive, tripwired like TMDB"
```

---

### Task 4: `metacritic dial` CLI verb

**Files:**
- Modify: `src/movie_brain/cli.py`
- Test: `tests/unit/test_cli.py`

**Interfaces:**
- Consumes: `MC_TOP_N_KEY`, `DEFAULT_TOP_N` (Task 2), `Repository.set_meta`/`get_meta`/`staged_title_count` (Task 1), `archive_dir`/`archived_pages`/`CARDS_PER_PAGE` from `movie_brain.infrastructure.metacritic`.
- Produces: `movie-brain metacritic dial [N]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cli.py` (it uses `runner = CliRunner()` and the `config_dir` fixture; the autouse env fixture points the app's config dir at tmp):

```python
def test_metacritic_dial_shows_default_and_sets(config_dir):
    r = runner.invoke(app, ["metacritic", "dial"])
    assert r.exit_code == 0
    assert "100" in r.output  # DEFAULT_TOP_N

    r = runner.invoke(app, ["metacritic", "dial", "500"])
    assert r.exit_code == 0

    r = runner.invoke(app, ["metacritic", "dial"])
    assert "500" in r.output
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_cli.py -k dial -v`
Expected: FAIL — `No such command 'dial'` (non-zero exit code).

- [ ] **Step 3: Implement the command**

In `cli.py` (imports: add `DEFAULT_TOP_N, MC_TOP_N_KEY` to the `application.metacritic` import; add `from movie_brain.infrastructure.metacritic import CARDS_PER_PAGE, archive_dir, archived_pages`; add `Optional` usage via `int | None`):

```python
@metacritic_app.command("dial")
def metacritic_dial(
    n: Annotated[int | None, typer.Argument(min=1, help="New top-N; omit to show the current dial.")] = None,
) -> None:
    """Show or set N, the Mode-B discovery dial (promotion runs in the nightly sync)."""
    repo = _repo()
    if n is None:
        current = int(repo.get_meta(MC_TOP_N_KEY) or DEFAULT_TOP_N)
        pages = len(archived_pages(archive_dir(load_config().config_dir)))
        staged = repo.staged_title_count()
        console.print(f"top-N: {current} · archive: {pages} pages · staged titles: {staged}")
        if staged < current:
            need = -(-current // CARDS_PER_PAGE)
            console.print(f"archive may be short — run: movie-brain metacritic crawl --pages {need}")
        return
    repo.set_meta(MC_TOP_N_KEY, str(n))
    console.print(f"top-N set to {n} — applied on the next sync")
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_cli.py -v`
Expected: PASS.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run mypy
git add src/movie_brain/cli.py tests/unit/test_cli.py
git commit -m "metacritic dial: show/set the Mode-B top-N"
```

---

### Task 5: Quiet first provider check

**Files:**
- Modify: `src/movie_brain/infrastructure/database.py` (`films_for_watchlist_refresh`, `films_for_provider_refresh`), `src/movie_brain/application/availability.py` (`_refresh_pass`)
- Test: `tests/features/tmdb.feature`, `tests/step_defs/test_tmdb.py`; expect adjustments in `tests/step_defs/test_watchlist.py` / `watchlist.feature`

**Interfaces:**
- Consumes: existing `record_listing` (plain, no transition) and `record_listing_with_transition`.
- Produces: both refresh queries return `list[tuple[int, str, bool]]` — `(film_id, tmdb_id, first_check)` where `first_check = providers_checked_at IS NULL`.

- [ ] **Step 1: Write the failing scenario**

Append to `tests/features/tmdb.feature` (mirror that feature's existing given/when wording exactly — read the file first; the scenario below states the required behavior, its given steps must reuse the feature's existing vocabulary for seeding a matched film and TMDB provider responses):

```gherkin
  Scenario: A film's first provider check is baseline, not an arrival
    # …existing givens seeding one matched film whose providers return Max…
    When the availability step runs
    Then no availability transition is recorded

  Scenario: A service appearing on a later check is an arrival
    # …existing givens; first check runs, then Max appears on the second check…
    Then an availability transition for "max" is recorded
```

Add whatever `then` steps are missing, e.g.:

```python
@then("no availability transition is recorded")
def no_transitions(ctx):
    import sqlite3 as _sqlite3

    conn = _sqlite3.connect(ctx["repo"].db_path)
    count = conn.execute("SELECT COUNT(*) FROM availability_transitions").fetchone()[0]
    conn.close()
    assert count == 0
```

- [ ] **Step 2: Run to verify the new scenario fails**

Run: `uv run pytest tests/step_defs/test_tmdb.py -v`
Expected: new scenario FAILS (a transition IS currently recorded on first check).

- [ ] **Step 3: Implement**

`database.py` — both queries gain the flag and the tuple type:

```python
    def films_for_watchlist_refresh(self) -> list[tuple[int, str, bool]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT t.film_id, x.value, (t.providers_checked_at IS NULL) AS first_check FROM tmdb t "
                "JOIN external_ids x ON x.film_id = t.film_id AND x.authority = 'tmdb' "
                "JOIN watchlist w ON w.film_id = t.film_id "
                "WHERE t.found = 1 ORDER BY t.film_id"
            ).fetchall()
            return [(int(r["film_id"]), str(r["value"]), bool(r["first_check"])) for r in rows]
```

(`films_for_provider_refresh`: same `(t.providers_checked_at IS NULL) AS first_check` column and 3-tuple return.)

`availability.py` `_refresh_pass` — signature `films: list[tuple[int, str, bool]]`, loop head `for film_id, tmdb_id, first_check in films:`, and the listing write becomes:

```python
        for slug in sorted(slugs):
            if first_check:
                # First-ever observation of this film's providers: baseline, not a
                # transition — you can't detect an *arrival* without a prior look.
                repo.record_listing(film_id, slug, url, today)
            else:
                repo.record_listing_with_transition(film_id, slug, url, today)
```

- [ ] **Step 4: Run the full suite and adjust dependent tests**

Run: `uv run pytest`
Expected: tmdb/watchlist scenarios that asserted transitions (or `new_on`) after a film's FIRST provider check now fail. For each, the fix is to seed a prior observation before the pass under test — e.g. `ctx["repo"].record_tmdb_providers(fid, date(2026, 1, 1), "{}")` (any earlier date) so the tested check is no longer the first. Do NOT weaken assertions; the seeded-prior-check version tests the same arrival behavior. `tests/web/conftest.py` seeds transitions directly via `record_listing_with_transition` and is unaffected.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run mypy
git add -A src tests
git commit -m "First provider check is quiet baseline: transitions need a prior observation"
```

---

### Task 6: OMDb widening to discovery films

**Files:**
- Modify: `src/movie_brain/infrastructure/database.py`, `src/movie_brain/application/sync.py`
- Test: `tests/features/sync.feature`, `tests/step_defs/test_sync.py`

**Interfaces:**
- Consumes: Task 3's sync wiring (`config_dir`), `MC_MOVIE_URL` semantics (url built from slug).
- Produces: `films_needing_lookup_discovery(self, source: str, today: date) -> list[tuple[int, Film]]`.

- [ ] **Step 1: Write the failing scenario**

Append to `tests/features/sync.feature`:

```gherkin
  Scenario: Promoted films get OMDb ratings the same night
    Given the Criterion browse page exposes a token
    And the Criterion catalog has films "Alpha (1950)"
    And OMDb knows every film
    And the metacritic archive holds "Fresh Find" (2020) scored 95 as "fresh-find"
    When I sync with a metacritic archive
    Then the film for key "fresh find (2020)" has an OMDb rating
```

Step def:

```python
@then(parsers.parse('the film for key "{key}" has an OMDb rating'))
def film_has_omdb(ctx, key):
    fid = ctx["repo"].film_id_by_key(key)
    assert fid is not None
    import sqlite3 as _sqlite3

    conn = _sqlite3.connect(ctx["repo"].db_path)
    row = conn.execute("SELECT found FROM omdb WHERE film_id = ?", (fid,)).fetchone()
    conn.close()
    assert row is not None and row[0] == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/step_defs/test_sync.py -v -k "OMDb ratings the same night or promoted"`
Expected: FAIL — no omdb row for the promoted film (criterion-driven loop skips it).

- [ ] **Step 3: Implement**

`database.py`, next to `films_needing_lookup`:

```python
    def films_needing_lookup_discovery(self, source: str, today: date) -> list[tuple[int, Film]]:
        """Discovery films (no listing for `source`, i.e. never on Criterion) needing OMDb."""
        cutoff = (today - timedelta(days=MISS_RETRY_DAYS)).isoformat()
        with self._conn() as c:
            rows = c.execute(
                "SELECT f.id, f.title, f.year, x.value AS slug FROM films f "
                "LEFT JOIN external_ids x ON x.film_id = f.id AND x.authority = 'metacritic' "
                "WHERE NOT EXISTS (SELECT 1 FROM listings l WHERE l.film_id = f.id AND l.source = ?) "
                "AND (NOT EXISTS (SELECT 1 FROM omdb o WHERE o.film_id = f.id) "
                "OR EXISTS (SELECT 1 FROM omdb o WHERE o.film_id = f.id AND "
                "(o.needs_refresh = 1 OR (o.found = 0 AND (o.year_fallback = 0 OR o.looked_up <= ?))))) "
                "ORDER BY f.id",
                (source, cutoff),
            ).fetchall()
            return [
                (
                    int(r["id"]),
                    Film(
                        str(r["title"]),
                        r["year"],
                        None,
                        f"https://www.metacritic.com/movie/{r['slug']}/" if r["slug"] else "",
                    ),
                )
                for r in rows
            ]
```

`sync.py` OMDb loop head becomes:

```python
    lookup_queue = repo.films_needing_lookup(SOURCE, today) + repo.films_needing_lookup_discovery(SOURCE, today)
    for film_id, film in lookup_queue:
```

(Criterion-current films stay first in the queue; quota/tripwire logic unchanged.)

- [ ] **Step 4: Run the suite**

Run: `uv run pytest tests/step_defs -v`
Expected: PASS.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run mypy
git add src/movie_brain/infrastructure/database.py src/movie_brain/application/sync.py tests/features/sync.feature tests/step_defs/test_sync.py
git commit -m "OMDb loop covers discovery films: no-Criterion-listing films queue after criterion-current"
```

---

### Task 7: Source-agnostic view

**Files:**
- Modify: `src/movie_brain/infrastructure/database.py` (`_VIEW_SQL`, `list_views`, `_row_to_view`, `summary`), `src/movie_brain/domain/models.py` (`FilmView`), `src/movie_brain/application/export.py` (null-safe url)
- Test: `tests/unit/test_database.py`

**Interfaces:**
- Consumes: `create_film`, `set_external_id`, `upsert_mc_titles` (Task 1 / existing).
- Produces: `FilmView.url: str | None`; `FilmView.criterion: bool = True` (new last field); `summary()` gains key `"discovery"`; Task 8 relies on `criterion` and nullable `url` in `/api/films` JSON.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_database.py`:

```python
def test_list_views_includes_discovery_films_and_keeps_criterion_parity(repo):
    day = date(2026, 8, 19)
    # Criterion: Alpha current; Bravo departed-unrated (hidden); Echo departed-rated (shown).
    repo.record_catalog("criterion", [Film("Alpha", 1950, "Ann", "https://c/alpha"),
                                      Film("Bravo", 1960, "Bob", "https://c/bravo"),
                                      Film("Echo", 1990, "Eve", "https://c/echo")], date(2026, 1, 1))
    repo.record_catalog("criterion", [Film("Alpha", 1950, "Ann", "https://c/alpha")], day)
    repo.set_rating(repo.film_id_by_key("echo (1990)"), 8, day)
    # Discovery: Golf, no criterion listing, scraped metascore 88.
    gid = repo.create_film(Film("Golf", 2020, None, ""))
    repo.set_external_id(gid, "metacritic", "golf-2020", day)
    repo.upsert_mc_titles([McTitle("golf-2020", "Golf", 2020, 88, 1, 1)], day)

    views = {v.title: v for v in repo.list_views("criterion", day)}
    assert set(views) == {"Alpha", "Echo", "Golf"}  # Bravo (departed, unrated) stays hidden
    assert views["Alpha"].criterion is True and views["Alpha"].departed is False
    assert views["Echo"].criterion is True and views["Echo"].departed is True
    golf = views["Golf"]
    assert golf.criterion is False and golf.url is None and golf.departed is False
    assert golf.metacritic == 88 and golf.metacritic_url == "https://www.metacritic.com/movie/golf-2020/"
    assert repo.get_view(gid, day).title == "Golf"

    s = repo.summary("criterion")
    assert s["films"] == 2 and s["discovery"] == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_database.py -k discovery -v`
Expected: FAIL — Golf absent from `list_views` (inner join), no `criterion` attribute.

- [ ] **Step 3: Implement**

`models.py` — `FilmView.url: str | None` and append after `new_on`:

```python
    criterion: bool = True  # has a Criterion listing (current or departed); False = discovery-only
```

`database.py` — `_VIEW_SQL` becomes:

```python
_VIEW_SQL = """
SELECT f.id, f.title, f.year, f.director, l.url, o.language, o.imdb, o.rt,
       COALESCE(mc.score, o.metacritic) AS metacritic, x.value AS mc_slug, o.found,
       (o.film_id IS NULL) AS pending, l.leaving_date, l.first_seen, r.score,
       COALESCE(l.last_seen < (SELECT MAX(last_seen) FROM listings WHERE source = l.source), 0) AS departed,
       (l.film_id IS NOT NULL) AS criterion
FROM films f
LEFT JOIN listings l ON l.film_id = f.id AND l.source = ?
LEFT JOIN omdb o ON o.film_id = f.id
LEFT JOIN my_ratings r ON r.film_id = f.id
LEFT JOIN external_ids x ON x.film_id = f.id AND x.authority = 'metacritic'
LEFT JOIN metacritic mc ON mc.slug = x.value
"""
```

`list_views` WHERE becomes (params stay `(source, source)`):

```python
                _VIEW_SQL
                + "WHERE l.film_id IS NULL "
                + "OR l.last_seen = (SELECT MAX(last_seen) FROM listings WHERE source = ?) "
                + "OR r.score IS NOT NULL ORDER BY f.id",
```

`_row_to_view`: add `criterion=bool(row["criterion"])` to the constructed `FilmView`.

`summary()`:

```python
    def summary(self, source: str) -> dict[str, int]:
        views = self.list_views(source)
        crit = [v for v in views if v.criterion]
        return {
            "films": len(crit),
            "rated": sum(1 for v in crit if v.found is True),
            "pending": sum(1 for v in crit if v.pending),
            "unmatched": sum(1 for v in crit if v.found is False),
            "leaving": sum(1 for v in crit if v.leaving_date is not None),
            "mine": sum(1 for v in crit if v.my_rating is not None),
            "departed": sum(1 for v in crit if v.departed),
            "discovery": sum(1 for v in views if not v.criterion),
        }
```

`export.py` `write_csv` row: `v.url` → `v.url or ""` (the CSV now also includes discovery rows — intended: it exports the full view).

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest`
Expected: PASS (`tests/unit/test_export.py` and web API tests still hold — check any that assert exact summary dicts and add the `discovery: 0` key where needed).

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run mypy
git add -A src tests
git commit -m "View drives from films: LEFT-joined criterion listing, discovery films visible, parity kept"
```

---

### Task 8: Dashboard scope toggle

**Files:**
- Modify: `src/movie_brain/web/static/app.js`, `src/movie_brain/web/templates/index.html`, `tests/web/conftest.py`
- Test: `tests/web/test_api.py`, `tests/web/test_dashboard.py`

**Interfaces:**
- Consumes: Task 7's `criterion` / nullable `url` in film JSON.
- Produces: URL param `scope` (`criterion` default / `all`); `#scope-toggle` button; `#count-discovery` span.

- [ ] **Step 1: Seed a discovery film and write failing tests**

`tests/web/conftest.py` — imports gain `McTitle`; at the end of `seed(...)`:

```python
    # Golf: the one Mode-B discovery film — no Criterion listing, scraped metascore only.
    gid = repo.create_film(Film("Golf", 2020, None, ""))
    repo.set_external_id(gid, "metacritic", "golf-2020", TODAY)
    repo.upsert_mc_titles([McTitle("golf-2020", "Golf", 2020, 88, 1, 1)], TODAY)
```

`tests/web/test_api.py` (match its existing client/fixture style):

```python
def test_films_include_discovery_with_null_url(client):
    films = {f["title"]: f for f in client.get("/api/films").get_json()}
    golf = films["Golf"]
    assert golf["criterion"] is False and golf["url"] is None and golf["metacritic"] == 88
    assert films["Alpha"]["criterion"] is True
```

`tests/web/test_dashboard.py` (Playwright, uses the `dash`/`server` fixtures):

```python
def test_default_scope_hides_discovery(dash):
    assert dash.locator("tr[data-id]", has_text="Golf").count() == 0


def test_all_scope_reveals_discovery(page, server):
    page.goto(f"{server}/?scope=all&lang=any")
    page.wait_for_selector("#films tbody[data-count]")
    assert page.locator("tr[data-id]", has_text="Golf").count() == 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/web -v`
Expected: API test FAILS on missing `criterion`… actually passes after Task 7 — verify it PASSES; the two Playwright tests FAIL (`scope` unknown: Golf appears in default view / `?scope=all` has no effect yet — the first one fails because Golf leaks into the default view once `lang` filtering doesn't hide it; if it happens to pass due to the language default, keep it — it pins the parity contract). At minimum `test_all_scope_reveals_discovery` must fail before Step 3.

- [ ] **Step 3: Implement scope in the dashboard**

`index.html`:
- In the summary spans (after `count-departed`): `<span><b id="count-discovery">–</b> discovery</span>`
- First child of `<div id="chips">`: `<button id="scope-toggle" class="chip" title="Include films beyond Criterion">All films</button>`

`app.js`:
- `state`: add `scope: 'criterion',` after `chips`.
- `rowMatches` first line: `if (state.scope === 'criterion' && !f.criterion) return false;`
- `renderCounts`: scope the existing counts to Criterion films and add discovery:

```javascript
  function renderCounts() {
    const f = state.films.filter((x) => x.criterion);
    const n = (p) => f.filter(p).length;
    $('#count-films').textContent = f.length;
    $('#count-rated').textContent = n((x) => x.found === true);
    $('#count-pending').textContent = n((x) => x.pending);
    $('#count-unmatched').textContent = n((x) => x.found === false);
    $('#count-leaving').textContent = n((x) => x.leaving_date != null);
    $('#count-mine').textContent = n((x) => x.my_rating != null);
    $('#count-departed').textContent = n((x) => x.departed);
    $('#count-discovery').textContent = state.films.length - f.length;
  }
```

- `syncUrl`: after the chips line: `if (state.scope !== 'criterion') p.set('scope', 'all');`
- `readUrl`: after the chips line: `state.scope = p.get('scope') === 'all' ? 'all' : 'criterion';`
- `writeControlsFromState`: first line: `$('#scope-toggle').classList.toggle('active', state.scope === 'all');`
- Chips click handler — handle the toggle before the chip branches:

```javascript
    if (b.id === 'scope-toggle') state.scope = state.scope === 'all' ? 'criterion' : 'all';
    else if (b.id === 'chips-clear') state.chips.clear();
```

(`Clear` intentionally leaves scope alone — it's a scope, not a filter.)

- [ ] **Step 4: Run the web suite (Playwright needs chromium installed once)**

Run: `uv run pytest tests/web -v`
Expected: PASS. If pre-existing dashboard tests assert the "Showing X of Y" totals, Y grew by one (Golf) — update those exact strings; counts in `#count-*` are unchanged by design.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run mypy
git add src/movie_brain/web tests/web
git commit -m "Dashboard scope toggle: default keeps Criterion parity, All films reveals discovery"
```

---

### Task 9: Docs, gate, and landing

**Files:**
- Modify: `CLAUDE.md`, `docs/multiple-movie-services.md`
- Create: `docs/superpowers/handoffs/2026-08-23-phase6-handoff.md`

- [ ] **Step 1: Update CLAUDE.md**

- Commands block: add `uv run movie-brain metacritic dial [N]` with a one-liner ("show/set the Mode-B top-N; promotion runs in nightly sync").
- Sync flow: insert a step between the Criterion walk and the OMDb loop: offline Mode-B promotion (meta `mc_top_n`, default 100; match-first dedup guard; key/slug conflicts → `match_review`; archive shortfall logged; own tripwire; no scraping). Note the OMDb loop now also covers discovery films (no Criterion listing), and that a film's first TMDB provider check writes listings without transitions.
- Rules: the view drives from `films` with a LEFT criterion join — default dashboard scope `criterion` keeps parity, `scope=all` reveals discovery films; `FilmView.url` is nullable.

- [ ] **Step 2: Mark Phase 5 done in the roadmap**

In `docs/multiple-movie-services.md`: phase table row 5 → `Metacritic Mode B: top-N dial (start N=100) — **done**`; numbered item 5 gets `**Done (2026-08-23).**` prefix and a one-sentence "landed as" note (meta-resident N + nightly offline promotion + scope toggle + quiet first check + OMDb widening).

- [ ] **Step 3: Full gate**

Run: `uv run pytest && uv run ruff check . && uv run mypy`
Expected: all green (Playwright included).

- [ ] **Step 4: Write the Phase 6 handoff**

`docs/superpowers/handoffs/2026-08-23-phase6-handoff.md`, same shape as the Phase 5 one: status (what landed, gate result), what Phase 6 (full-service import pattern) builds on (source-agnostic view, `create_film`, quiet first check, the `movie_service` registry), decisions Phase 6 must make, parked items (carry forward Phase 4's parked list plus anything new, e.g. Metacritic US-re-release years reaching TMDB matching for promoted films — misses land in `match_review`), and an entry-point prompt.

- [ ] **Step 5: Commit docs**

```bash
git add CLAUDE.md docs
git commit -m "Docs: Phase 5 (Metacritic Mode B top-N dial) landed"
```

- [ ] **Step 6: Finish the branch**

Use superpowers:finishing-a-development-branch — merge to `main` (fast-forward preferred, matching prior phases), push, clean up the worktree.

---

## Self-review notes

- Spec coverage: promotion §1 → Tasks 1–2; sync §2 → Tasks 3–4; quiet first check §3 → Task 5; OMDb §4 → Task 6; view/dashboard §5 → Tasks 7–8; error handling is embedded per task; landing checklist → Task 9.
- Task 5's feature-file given-steps are intentionally bound to the existing tmdb.feature vocabulary (read before writing) — the required behavior and then-steps are fully specified here.
- Type ripples to watch in mypy: `films_for_*_refresh` 3-tuples (Task 5), `FilmView.url: str | None` consumers (export handled in Task 7).
