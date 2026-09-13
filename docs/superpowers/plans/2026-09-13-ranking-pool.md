# Ranking Pool (Phase A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the ranker's pool a defined fact (owned ∪ "Rank this" ∪ rated 6–10, minus 0–5, disposed and unseen), seed rated films on read, expose "Rank this" in the drawer, and let the order mode strict-order tier 2 beside tier 1.

**Architecture:** One repository method defines the pool and every reader in `application/rank.py` uses it; a `_seed_new` helper runs at the top of both state reads; `rank_mark` is a one-row table on the watchlist pattern with a drawer toggle and one route; the order use case, routes and page take a `tier` in `ORDER_TIERS = (1, 2)`. No change to the search, the tables from 022/023, or `my_ratings`.

**Tech Stack:** Python 3.12, Flask, SQLite, pytest + pytest-bdd + Playwright, vanilla JS. Run everything with `uv run`.

**Spec:** `docs/superpowers/specs/2026-09-13-ranking-pool-design.md` — the plan argues from the spec; read both. Its parents: `2026-09-13-tier-ranker-design.md`, `2026-09-13-order-top-tier-design.md`.

## Global Constraints

- Pool (spec P1): owned OR `rank_mark` OR `my_ratings.score` in 6..10; minus `film_disposition`, minus `unseen`, minus any film whose score is 0..5 (the low score excludes even an owned or marked film). ONE definition, `Repository.rank_pool_film_ids()`.
- Seed map (P4): `tier_for_score`: 10→1, 9→2, 8→3, 7→4, 6→5; a score below 6 raises `ValueError`. `pool_seed_films()` never returns one.
- Seed on read (P3): `_seed_new` places every `pool_seed_films()` film with no placement, `how = 'seed'`, before either queue is derived, in `session_state` AND `order_state`.
- Order tiers (P5): `ORDER_TIERS = (1, 2)`; the tier is an argument on `order_state`, `order_verdict`, `order_pass`; a tier outside it is 400; `last_action` order kinds carry `tier`; `save_list` passes the union of both tiers' `{film_id: position}` maps.
- `rank_mark`: `set_rank_mark` and the drawer toggle are the only writers; `merge_film` moves it survivor-wins via `_ONE_ROW_TABLES`; `set_unseen` does not touch it.
- Source key `owned`, slug `my-owned-tiers` unchanged; `DEFAULT_LIST_NAME["owned"]` → `"My films, tiered"` and the `#list-name` placeholder follows.
- `my_ratings` is never written by this phase (tiering D2 still holds).
- Fixture change that ripples: every seeded fixture film scored 4 becomes 6 (`"Four", 4` → `"Six", 6`), or the tier 5 anchor disappears and every rank scenario breaks. Task 3 does the sweep BEFORE Task 4 changes behaviour.
- Migration `024_rank_mark.sql`, BEGIN/COMMIT, inserts `schema_version` 24; applied migrations untouched.
- Every task ends green on `uv run pytest -q` (~55 s), `uv run ruff check .`, `uv run mypy`. Markdown never hard-wrapped. Commit messages: one line, the "why", plus the session's attribution trailer.
- The application layer imports no `sqlite3`.

---

## File structure

| File | Responsibility |
|---|---|
| `migrations/024_rank_mark.sql` | `rank_mark` table. |
| `src/movie_brain/infrastructure/database.py` | `rank_pool_film_ids`, `pool_seed_films` (replaces `owned_seed_films`), `rank_mark_film_ids`, `set_rank_mark`, `rank_mark` in `_ONE_ROW_TABLES`, `FilmView.rank_marked` wiring. |
| `src/movie_brain/domain/models.py` | `FilmView.rank_marked: bool`. |
| `src/movie_brain/domain/rank.py` | `tier_for_score` raises below 6; `ORDER_TIERS`; `DEFAULT_LIST_NAME`. |
| `src/movie_brain/application/rank.py` | pool everywhere, `_seed_new`, tier-parameterised order functions, `undo` tier, `save_list` both tiers. |
| `src/movie_brain/web/app.py` | `tier` on the three order routes; `PUT /api/films/<id>/rank-mark`. |
| `src/movie_brain/web/static/rank.js`, `templates/rank.html` | third tab, `#order-1`/`#order-2`, tier in every order call, progress label. |
| `src/movie_brain/web/static/app.js` | drawer `Rank this` toggle. |
| Tests | `tests/unit/test_rank.py`, `tests/unit/test_rank_repository.py`, `tests/features/rank_pool.feature` + `tests/step_defs/test_rank_pool.py` (new), `tests/features/rank_order.feature` + step defs (tier 2), `tests/web/test_api.py`, `tests/web/test_rank_page.py`, `tests/web/test_dashboard.py`; the four fixture sites in Task 3. |
| `CLAUDE.md`, `docs/backlog.md`, the two ranker specs | Docs. |

---

### Task 0: Branch

- [ ] `git checkout -b feature/STORY-17-ranking-pool` from main (main is at aa94133 or later; suite green).
- [x] The spec and this plan are already committed on main (2026-09-13); branch from that commit.

---

### Task 1: Migration 024, the pool, and the mark (repository)

**Files:** create `migrations/024_rank_mark.sql`; modify `src/movie_brain/infrastructure/database.py`, `src/movie_brain/domain/models.py`; test `tests/unit/test_rank_repository.py`.

**Interfaces produced:**
- `Repository.rank_mark_film_ids() -> set[int]`
- `Repository.set_rank_mark(film_id: int, marked: bool, today: date) -> bool | None` (None = unknown film; idempotent)
- `Repository.rank_pool_film_ids() -> set[int]` (spec §4.1)
- `Repository.pool_seed_films() -> list[SeedFilm]` (pool ∩ rated 6–10; `owned_seed_films` deleted, every caller updated in Task 4 — until then keep `owned_seed_films` as a thin alias returning `pool_seed_films()` so the suite stays green)
- `FilmView.rank_marked: bool` served on every view.

- [ ] **Step 1: Failing tests** (append; `_film`, `_owned_rated`, `D` exist in the file):

```python
def test_rank_mark_round_trips_and_reports_missing(repo):
    a = _film(repo, "Alpha", 1950)
    assert repo.set_rank_mark(a, True, D) is True
    assert repo.rank_mark_film_ids() == {a}
    assert repo.get_view(a, D).rank_marked is True
    assert repo.set_rank_mark(a, True, D) is True   # idempotent
    assert repo.set_rank_mark(a, False, D) is False
    assert repo.rank_mark_film_ids() == set()
    assert repo.set_rank_mark(999, True, D) is None


def test_rank_pool_is_owned_or_marked_or_rated_6_plus_minus_low_scores_unseen_and_disposed(repo):
    owned = _film(repo, "Owned", 1950); repo.mark_owned(owned, D)
    marked = _film(repo, "Marked", 1951); repo.set_rank_mark(marked, True, D)
    rated6 = _film(repo, "Rated6", 1952); repo.set_rating(rated6, 6, D)
    rated5 = _film(repo, "Rated5", 1953); repo.set_rating(rated5, 5, D)
    owned0 = _film(repo, "Owned0", 1954); repo.mark_owned(owned0, D); repo.set_rating(owned0, 0, D)
    marked4 = _film(repo, "Marked4", 1955); repo.set_rank_mark(marked4, True, D); repo.set_rating(marked4, 4, D)
    unseen_owned = _film(repo, "UnseenOwned", 1956); repo.mark_owned(unseen_owned, D); repo.set_unseen(unseen_owned, True, D)
    gone = _film(repo, "Gone", 1957); repo.mark_owned(gone, D); repo.tombstone_film(gone, D)
    _film(repo, "Nobody", 1958)
    assert repo.rank_pool_film_ids() == {owned, marked, rated6}


def test_pool_seed_films_is_pool_and_rated_6_plus(repo):
    a = _owned_rated(repo, "Alpha", 1950, 10, imdb=8.1)
    b = _film(repo, "Bravo", 1960); repo.set_rating(b, 8, D)          # rated, not owned: in
    c = _owned_rated(repo, "Charlie", 1970, 5)                        # owned but 5: out
    d = _film(repo, "Delta", 1980); repo.set_rank_mark(d, True, D)   # marked, unrated: not a seed
    e = _owned_rated(repo, "Echo", 1990, 7); repo.set_unseen(e, True, D)
    got = {s.film_id: s for s in repo.pool_seed_films()}
    assert set(got) == {a, b}
    assert got[a].score == 10 and got[a].imdb == 8.1 and got[b].imdb is None


def test_merge_moves_rank_mark_survivor_wins(repo):
    a, b = _film(repo, "Alpha", 1950), _film(repo, "Alpha", 1951)
    repo.set_rank_mark(b, True, D)
    repo.merge_film(b, a, D)
    assert repo.rank_mark_film_ids() == {a}
    c, d = _film(repo, "Beta", 1960), _film(repo, "Beta", 1961)
    repo.set_rank_mark(c, True, D); repo.set_rank_mark(d, True, D)
    report = repo.merge_film(d, c, D)
    assert report.dropped.get("rank_mark") == 1 and repo.rank_mark_film_ids() == {a, c}
```

Also update `test_owned_seed_films_is_owned_and_rated_minus_unseen` to call `pool_seed_films()` (same expectations) and delete the old name's use.

- [ ] **Step 2:** `uv run pytest tests/unit/test_rank_repository.py -q -k "rank_mark or pool"` → FAIL (`AttributeError`).

- [ ] **Step 3: Migration**

```sql
-- "Rank this" (spec 2026-09-13-ranking-pool §3, P2): the ranker pool's entry ticket for a film the
-- owner does not own. Watchlist pattern: one row per film, the drawer toggle and set_rank_mark
-- the only writers, never touched by sync. merge_film moves it survivor-wins (_ONE_ROW_TABLES).
BEGIN;
CREATE TABLE rank_mark (
    film_id   INTEGER PRIMARY KEY REFERENCES films(id),
    marked_on TEXT NOT NULL
);
INSERT INTO schema_version (version) VALUES (24);
COMMIT;
```

- [ ] **Step 4: Repository.** Add `"rank_mark"` to `_ONE_ROW_TABLES` (`database.py:192-200`). In `merge_film`'s `_ONE_ROW_TABLES` loop add `elif table == "rank_mark": kept[table] = {"marked_on": loser_row["marked_on"]}`. Add `FilmView.rank_marked: bool = False` in `domain/models.py` beside `unseen` (line 333), and a `rank_marked: bool = False` parameter to `_row_to_view` (line ~530) wired to `rank_marked=rank_marked` (line ~561); find where `unseen` is computed for views (grep `_unseen_ids(` — both `get_view` and `list_views` build the set once and pass `unseen=film_id in set`) and do the same with a `_rank_mark_ids(c)` helper beside `_unseen_ids` (line 483). Then, in the tier-ranker section after `set_unseen`:

```python
    # rank_mark ("Rank this", ranking-pool spec P2) ------------------------------
    def rank_mark_film_ids(self) -> set[int]:
        with self._conn() as c:
            return _rank_mark_ids(c)

    def set_rank_mark(self, film_id: int, marked: bool, today: date) -> bool | None:
        """Idempotent set/clear; None when the film does not exist. Touches nothing else:
        a marked film that is unseen or scored 0–5 is simply outside the pool (P1)."""
        with self._conn() as c:
            if c.execute("SELECT 1 FROM films WHERE id = ?", (film_id,)).fetchone() is None:
                return None
            if marked:
                c.execute("INSERT OR IGNORE INTO rank_mark (film_id, marked_on) VALUES (?, ?)", (film_id, today.isoformat()))
                return True
            c.execute("DELETE FROM rank_mark WHERE film_id = ?", (film_id,))
            return False

    # the pool (ranking-pool spec §4.1, P1) ---------------------------------------
    _POOL_SQL = (
        "SELECT f.id FROM films f "
        "LEFT JOIN my_ratings r ON r.film_id = f.id "
        "WHERE " + _NOT_DISPOSED + " "
        "AND NOT EXISTS (SELECT 1 FROM unseen u WHERE u.film_id = f.id) "
        "AND (r.score IS NULL OR r.score >= 6) "
        "AND (EXISTS (SELECT 1 FROM owned o WHERE o.film_id = f.id) "
        "     OR EXISTS (SELECT 1 FROM rank_mark m WHERE m.film_id = f.id) "
        "     OR r.score >= 6)"
    )

    def rank_pool_film_ids(self) -> set[int]:
        """Owned ∪ marked ∪ rated 6–10, minus disposed, unseen and any film scored 0–5 — the ONE
        definition of who the ranker asks and seeds."""
        with self._conn() as c:
            return {int(r["id"]) for r in c.execute(self._POOL_SQL)}

    def pool_seed_films(self) -> list[SeedFilm]:
        """Pool ∩ rated 6–10: the seed placements and anchor pool (P3, P4)."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT f.id, f.title, f.year, r.score, o2.imdb FROM films f "
                "JOIN my_ratings r ON r.film_id = f.id LEFT JOIN omdb o2 ON o2.film_id = f.id "
                "WHERE f.id IN (" + self._POOL_SQL + ") AND r.score >= 6 ORDER BY f.id"
            ).fetchall()
            return [SeedFilm(int(r["id"]), int(r["score"]), r["imdb"], str(r["title"]), r["year"]) for r in rows]

    def owned_seed_films(self) -> list[SeedFilm]:  # transitional alias, removed in Task 4
        return self.pool_seed_films()
```

`_NOT_DISPOSED` (`database.py:212`) references the alias `f`, which the pool SQL uses. The `unseen` view wiring to mirror for `rank_marked`: `list_views` builds `un = _unseen_ids(c)` once (`database.py:3223`) and passes `unseen=r["id"] in un` (`:3236`); `get_view` passes `unseen=row["id"] in _unseen_ids(c)` (`:3260`). Add `_rank_mark_ids(c)` beside `_unseen_ids` (`:483`) and the same two call sites with `rank_marked=`.

- [ ] **Step 5:** focused tests green; full gate; commit: `"migration 024 + the pool: one definition of who the ranker asks, and Rank this as a film's ticket into it"`.

---

### Task 2: The seed map's bottom (`domain/rank.py`)

**Files:** `src/movie_brain/domain/rank.py`, `tests/unit/test_rank.py`.

- [ ] **Step 1:** Replace the parametrised `test_seed_mapping` cases with `[(10, 1), (9, 2), (8, 3), (7, 4), (6, 5)]` and add:

```python
@pytest.mark.parametrize("score", [5, 4, 0])
def test_scores_below_six_do_not_seed(score):
    with pytest.raises(ValueError):
        tier_for_score(score)


def test_order_tiers_and_default_name():
    assert ORDER_TIERS == (1, 2)
    assert DEFAULT_LIST_NAME["owned"] == "My films, tiered"
```

- [ ] **Step 2:** FAIL. **Step 3:**

```python
def tier_for_score(score: int) -> int:
    """Seed mapping (ranking-pool spec P4): 10→1, 9→2, 8→3, 7→4, 6→5. A score below 6 is not a
    ranker film at all (5 = watched, indifferent; 1–4 disliked; 0 not interested) and raises."""
    if score >= 10:
        return 1
    if score == 9:
        return 2
    if score == 8:
        return 3
    if score == 7:
        return 4
    if score == 6:
        return 5
    raise ValueError(f"a score of {score} does not seed a tier")


ORDER_TIERS: tuple[int, ...] = (1, 2)  # the tiers the order mode exposes (ranking-pool spec P5)
DEFAULT_LIST_NAME: dict[str, str] = {"owned": "My films, tiered"}
```

Also `propose_anchors` calls `tier_for_score(f.score)` on every seed — seeds are now always ≥ 6, fine. Update its docstring's `TIER_MIDDLE` comment if it mentions `≤6`.

- [ ] **Step 4:** the suite will now FAIL in the feature/api/page fixtures that seed a 4 (expected — Task 3 fixes them). Run only `uv run pytest tests/unit -q` here (green), lint, commit: `"a score below six no longer seeds a tier: those films are outside the ranker by the owner's definition"`.

---

### Task 3: Fixture sweep — the tier 5 seed becomes a 6 (batched)

**Files:** `tests/features/rank.feature:4`, `tests/step_defs/test_rank.py` (the `rated` given's parse pattern and every `"Four"` reference: the proposal step, `tier5_bare`, anchor names in scenarios), `tests/features/rank_order.feature:4` and `tests/step_defs/test_rank_order.py` (the `rated` given), `tests/web/test_api.py:405` (`rank_client`), `tests/web/test_rank_page.py:22` (`seed`), `tests/unit/test_rank.py` (`propose_anchors` tests if they use a 4).

- [ ] Replace `"Four", 4` / `"Four" 4` / `Four` with `"Six", 6` / `Six` at every site above. In `tests/unit/test_rank.py::test_propose_anchors_picks_nearest_middle_then_imdb_then_title` the fixture has `SeedFilm(4, 4, 7.0, "Four", 1961)` beside `SeedFilm(3, 6, 7.0, "Six", 1960)` to exercise the tier 5 tie-break; `propose_anchors` calls `tier_for_score` on every seed, so a 4 now raises. Change that seed to score 6 with a title that loses the tie-break (`SeedFilm(4, 6, 7.0, "Zix", 1961)`) and keep the assertion that "Six" wins; the scenario text "the proposal is Ten, Nine, Eight, Seven, Four" becomes "…, Six"; `tier5_bare` asserts `_id(ctx, "Six")`. Grep afterwards: `grep -rn '"Four"' tests/` must be empty.
- [ ] `uv run pytest -q` green (no behaviour change: a 6 seeds tier 5 exactly as a 4 did), lint, commit: `"fixtures seed tier 5 with a 6, since a 4 no longer seeds at all"`.

---

### Task 4: The use case — pool, seed on read, order tier 2, save both tiers

**Files:** `src/movie_brain/application/rank.py`; `tests/features/rank_pool.feature` + `tests/step_defs/test_rank_pool.py` (new); `tests/features/rank_order.feature` + `tests/step_defs/test_rank_order.py` (tier 2 scenarios); `tests/step_defs/test_rank_order.py` callers of `order_*` gain a `tier` argument (`ORDER_TIER` → pass `1`).

**Interfaces produced:** `order_state(repo, source, tier, today)`, `order_verdict(repo, source, tier, film_id, other_film_id, verdict, today)`, `order_pass(repo, source, tier, film_id, today)`; `_seed_new(repo, s, today) -> int` (films seeded); `ORDER_TIER` removed, `ORDER_TIERS` imported from the domain.

- [ ] **Step 1: New feature file** `tests/features/rank_pool.feature`:

```gherkin
Feature: The ranking pool — who the ranker asks and seeds

  Background:
    Given owned films rated "Ten" 10, "Nine" 9, "Eight" 8, "Seven" 7, "Six" 6
    And an owned unrated film "Uno"
    And a started tiering session

  Scenario: A rated film the owner does not own seeds into its tier on the first read and is never asked
    Given a film "Stream" rated 8, not owned
    Then "Stream" is placed in tier 3 as a seed
    And "Stream" is not in the queue

  Scenario: Low scores keep a film out, owned or not
    Given an owned film "Meh" rated 4
    And an owned film "Nope" rated 0
    And a film "Cold" rated 5, not owned
    Then none of "Meh", "Nope", "Cold" is placed or queued

  Scenario: A film rated after the session started seeds on the next read
    Given a film "Late" not owned
    When "Late" is rated 9
    Then "Late" is placed in tier 2 as a seed

  Scenario: A marked unrated film is asked, and unmarking removes it
    Given a film "Pick" not owned
    When "Pick" is marked Rank this
    Then "Pick" is in the queue
    When "Pick" is unmarked
    Then "Pick" is not in the queue

  Scenario: A marked film with a low score stays out
    Given a film "Marked4" rated 4, not owned
    When "Marked4" is marked Rank this
    Then "Marked4" is not in the queue

  Scenario: The proposal's fallback offers a marked film
    Given "Seven" is re-rated 8
    And a film "Pick" not owned
    When "Pick" is marked Rank this
    Then tier 4's choices include "Pick"

  Scenario: A newly seeded ten joins tier 1's order queue
    Given a film "Top" rated 10, not owned
    Then the tier 1 order has 1 film and 1 remaining
```

Step defs: self-contained like `test_rank_order.py`; "a started tiering session" uses `proposal` + `start_session` on the five seeds; `_state` = `session_state`; "is placed in tier N as a seed" reads `repo.rank_placements(sid)[fid] == (N, "seed")` AFTER calling `session_state` once (seed on read); "in the queue" = candidate appears among `session_state` pairs when iterated through with `pass_film` deferrals — simplest: assert `_id in ctx` of `application.rank._queue(repo, s)` (import the private helper; acceptable in a step def, note it); "tier 1 order has N film and M remaining" = `order_state(repo, SRC, 1, TODAY)["ordered"] == 1 and ["remaining"] == 1` (Ten was free-inserted, Top queued). The fallback scenario: re-rate Seven to 8 empties tier 4's seeds, so `proposal()["choices"][4]` is the fallback list — assert `"Pick"` is in it.

- [ ] **Step 2: Extend `rank_order.feature`** with:

```gherkin
  Scenario: Tier 2 has its own order, queue, deferral and undo
    Then the tier 2 order has 1 film and 0 remaining
    When "Nine" is joined in tier 2 by "Nine-b" rated 9, not owned
    Then the tier 2 order has 1 film and 1 remaining
    When I answer worse in tier 2 order mode
    Then the tier 2 order has 2 films and 0 remaining
    And the tier 1 order still has 1 film and 3 remaining
    When I undo
    Then the tier 2 order has 1 film and 1 remaining
    When I pass in tier 2 order mode
    Then "Nine-b" is deferred in tier 2

  Scenario: An order tier outside 1 and 2 is refused
    Then reading the tier 3 order is refused with 400

  Scenario: Saving writes both ordered tiers bare
    When I answer worse in order mode
    And "Nine" is joined in tier 2 by "Nine-b" rated 9, not owned
    And I answer worse in tier 2 order mode
    And I save the list as "Mine"
    Then entries 1 and 2 carry no label
    And entries 5 and 6 carry no label
```

(Fixture arithmetic for the last: tier 1 = Alpha/Beta/Gamma/Delta → 2 ordered bare + 2 tied `=3` = lines 1–4; tier 2 = Nine, Nine-b both ordered → lines 5–6 bare; then Eight, Seven, Six.) Existing steps `I answer … in order mode`, `I pass in order mode`, `I undo` take tier 1; add tier-2 variants that call the same functions with `tier=2`.

- [ ] **Step 3:** FAIL on the new steps/imports.

- [ ] **Step 4: Implement.** In `application/rank.py`:
  - Replace every `repo.owned_film_ids()` with `repo.rank_pool_film_ids()` (proposal fallback line 64, `start_session` line 88, `_queue` line 129, `swap_anchor` line 407); the `unseen` count (line 188) becomes `len(unseen_ids & (repo.owned_film_ids() | repo.rank_mark_film_ids()))`. Replace `repo.owned_seed_films()` with `repo.pool_seed_films()` (lines 48, 95) and delete the transitional alias from the repository.
  - Add and call `_seed_new`:

```python
def _seed_new(repo: Repository, s: RankSession, today: date) -> int:
    """Seed on read (ranking-pool spec P3): every pool film rated 6–10 with no placement in
    this session is placed in its tier as a seed. A film rated after the session started, or
    admitted by a widened pool, is never asked."""
    placed = repo.rank_placements(s.id)
    n = 0
    for f in repo.pool_seed_films():
        if f.film_id not in placed:
            repo.place_film(s.id, f.film_id, tier_for_score(f.score), "seed", today)
            n += 1
    return n
```

  called as the first thing after the session is resolved in `session_state` (after `if s is None: return {"session": None}`) and in `order_state` (after `_session`).
  - Order tier: `ORDER_TIER` → `from movie_brain.domain.rank import ORDER_TIERS`; `_order_queue(repo, s, tier)`, `order_state(repo, source, tier, today)` (raise `RankError(400, "tier must be 1 or 2")` when `tier not in ORDER_TIERS`), `_current_order_pair(repo, source, tier, today)`, `order_verdict(repo, source, tier, film_id, other_film_id, verdict, today)`, `order_pass(repo, source, tier, film_id, today)`; every `ORDER_TIER` inside them becomes `tier`; the two order `last_action` dicts gain `"tier": tier`; in `undo`, the `order_verdict` branch calls `repo.remove_ordered(fid, s.id)` unchanged (it removes the film's row whatever the tier — `rank_order`'s PK is `(session_id, film_id)`) and the mode-aware return uses `order_state(repo, source, int(action["tier"]), today)`.
  - `save_list`: `order = {}`; `for t in ORDER_TIERS: order.update({fid: pos for pos, fid in enumerate(repo.rank_order(s.id, t), start=1)})`.
  - Update `tests/step_defs/test_rank_order.py` and `tests/web/test_api.py` callers to pass the tier (Task 5 handles the routes; here only the direct calls).

- [ ] **Step 5:** `uv run pytest tests/step_defs -q` green; full gate; commit: `"the ranker reads one pool, seeds rated films on read, and orders tier 2 beside tier 1"`.

---

### Task 5: Routes

**Files:** `src/movie_brain/web/app.py`; `tests/web/test_api.py`.

- [ ] **Step 1: Tests.** Extend the three `test_rank_order_*` tests: GET with `?tier=1`; bodies with `"tier": 1`; add `assert client.get("/api/rank/order?tier=3").status_code == 400` and `assert client.get("/api/rank/order").status_code == 400` (tier required). Add:

```python
def test_rank_mark_toggle_route(client, repo):
    trio = repo.film_id_by_key("trio (1950)")
    r = client.put(f"/api/films/{trio}/rank-mark", json={"marked": True})
    assert r.status_code == 200 and r.get_json() == {"marked": True}
    assert client.get(f"/api/films/{trio}").get_json()["rank_marked"] is True
    assert client.put(f"/api/films/{trio}/rank-mark", json={"marked": False}).get_json() == {"marked": False}
    assert client.put(f"/api/films/{trio}/rank-mark", json={}).status_code == 400
    assert client.put("/api/films/999/rank-mark", json={"marked": True}).status_code == 404
```

- [ ] **Step 2:** FAIL. **Step 3:** In the three order routes read `tier`: GET from `request.args.get("tier")` (int or 400 `'tier query parameter must be 1 or 2'`), POSTs from the body (`isinstance(tier, int)` else 400 with the message extended by `"tier": int`); pass it through. Add after `put_unseen`:

```python
    @app.put("/api/films/<int:film_id>/rank-mark")
    def put_rank_mark(film_id: int) -> tuple[Response, int]:
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not isinstance(body.get("marked"), bool):
            return jsonify({"error": 'body must be JSON {"marked": bool}'}), 400
        result = repo.set_rank_mark(film_id, body["marked"], today())
        if result is None:
            return jsonify({"error": "not found"}), 404
        return jsonify({"marked": result}), 200
```

- [ ] **Step 4:** green; full gate; commit: `"the order routes take a tier, and Rank this has its route"`.

---

### Task 6: The page and the drawer

**Files:** `src/movie_brain/web/static/rank.js`, `templates/rank.html`, `static/app.js`; `tests/web/test_rank_page.py`, `tests/web/test_dashboard.py`.

- [ ] **Step 1: Tests.** In `test_rank_flow` change `page.click('.tab[data-mode="order"]')` to `'.tab[data-mode="order-1"]'`, `page.url.endswith("#order")` → `"#order-1"`, and append after the tier 1 done state: click `.tab[data-mode="order-2"]`, expect `#rank[data-state="order"]` or `order_done` (Nine is alone in tier 2 → free-inserted → `order_done`), expect `#ordered` "1", then `page.goto(rank_server + "/rank#order")` and expect the tier 1 tab `aria-current="true"` (legacy hash maps to tier 1). In `test_dashboard.py` add `test_drawer_rank_this_toggle_round_trips` mirroring `test_drawer_unseen_toggle_round_trips` (lines 1151–1167) with `button.rank-toggle`.

- [ ] **Step 2:** FAIL. **Step 3: `rank.html`:** tabs become `data-mode="tiers"`, `data-mode="order-1"` ("Order tier 1"), `data-mode="order-2"` ("Order tier 2"); the order-only progress span reads `<span class="order-only"><b id="ordered">–</b> ordered in tier <b id="order-tier">–</b></span>`; `#list-name` placeholder "My films, tiered". **`rank.js`:**

```js
  // Modes: 'tiers', 'order-1', 'order-2'. '#order' (pre-phase-A bookmarks) reads as tier 1.
  const mode = () => { const h = location.hash; if (h === '#order' || h === '#order-1') return 'order-1'; if (h === '#order-2') return 'order-2'; return 'tiers'; };
  const isOrder = () => mode().startsWith('order-');
  const orderTier = () => Number(mode().slice(6)) || 1;
  const setMode = (m) => { if (mode() !== m) location.hash = m === 'tiers' ? '' : `#${m}`; };
```

Replace every `mode() === 'order'` with `isOrder()`; the GET becomes `` api('GET', `/api/rank/order?tier=${orderTier()}`) ``; both POST bodies gain `tier: orderTier()`; `renderProgress` sets `$('#order-tier').textContent = orderTier()`; `show()`'s `.order-only` check uses `isOrder()`; `#order-done`'s copy becomes "Every film in this tier is ordered. Save the list above."

**`app.js`:** in the drawer's `unseen-row` add `<button class="rank-toggle" data-id="${d.id}" aria-pressed="${d.rank_marked ? 'true' : 'false'}" title="Rank this film (puts it in the ranker's pool)">Rank this</button>`; add a click handler beside the unseen one (lines 692–702) hitting `/api/films/${id}/rank-mark` with `{marked: next}` and mirroring `film.rank_marked`.

- [ ] **Step 4:** Playwright green; full gate; commit: `"two ordered tiers on the rank page, and Rank this in the drawer"`.

---

### Task 7: Documentation

- [ ] `CLAUDE.md` tier-ranker bullet (one line): the pool definition and its single method; seed on read; the seed map's bottom (6→5, below raises, never seeded); `rank_mark` (migration 024, drawer + `set_rank_mark` only writers, `_ONE_ROW_TABLES`); `ORDER_TIERS = (1, 2)` and the `tier` on the order routes/hash; `DEFAULT_LIST_NAME` "My films, tiered"; "the ranker still never writes `my_ratings` — Phase B (ratings follow the ranking) reverses D2 deliberately".
- [ ] `docs/backlog.md`: new item "Phase B — ratings follow the ranking + Unseen chip" summarising R3/R4 of the brainstorm (the switch, 11 − tier, hand-set 0–5, the watch queue chip).
- [ ] Order spec O9 line: "tier 2 exposed 2026-09-13 (ranking-pool spec P5)". Ranking-pool spec status → implemented.
- [ ] Commit: `"docs: the pool, the seed map's bottom, Rank this and the second ordered tier, where the next session will look"`.

---

### Task 8: Apply live and hand off (owner present)

- [ ] `uv run movie-brain migrate` (dry run: 024 pending) → `uv run movie-brain migrate --apply`.
- [ ] List the seven rows before touching them:

```sql
SELECT p.film_id, f.title, r.score, p.tier, p.how FROM rank_placement p JOIN films f ON f.id = p.film_id
JOIN my_ratings r ON r.film_id = f.id WHERE p.session_id = 1 AND p.how = 'seed' AND r.score <= 5;
```

Expect exactly: Bill & Ted's Excellent Adventure 0, Dr. No 0, Goldfinger 0, Sullivan's Travels 0, Wings of Desire 0, West Side Story 4, Inglourious Basterds 4. Confirm with the owner ONCE, then `DELETE FROM rank_placement WHERE session_id = 1 AND film_id IN (…)`. Also confirm none of them holds a `rank_order` or `rank_order_comparison` row (they are tier 5; expect none).
- [ ] Restart the dashboard; smoke: `GET /api/rank/session` → `placed` = 716 − 7 + 76 = 785, `remaining` 0; `GET /api/rank/order?tier=1` → the two non-owned tens now in the queue (remaining grew by 2); `?tier=2` → one free insertion, `1 ordered`; the drawer of a non-owned film shows "Rank this".
- [ ] Merge to main, push if the owner says so, update memory (`tier-ranker-done`): 024 applied, never re-run; Phase B next.
