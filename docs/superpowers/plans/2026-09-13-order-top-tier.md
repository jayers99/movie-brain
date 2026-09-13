# Order the Top Tier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A second mode on `/rank`, "Order tier 1", that strict-orders the live session's tier 1 films by binary insertion, one `Better` click per verdict, and writes bare ranks for that tier into the ranker's saved list.

**Architecture:** Three new tables (migration 023) behind `Repository` methods; a pure insertion search `order_step` in `domain/rank.py` whose bounds are derived from the verdict log on every request (no stored lo/hi); three use-case functions in `application/rank.py` beside the tiering ones, sharing the session, the seed, the one undo slot and the save; three routes; and a tab on the existing page that reuses the pair component. `set_unseen` and `merge_film` learn the three tables.

**Tech Stack:** Python 3.12, Flask, SQLite, pytest + pytest-bdd + Playwright, vanilla JS. Run everything with `uv run`.

**Spec:** `docs/superpowers/specs/2026-09-13-order-top-tier-design.md` — the plan argues from the spec; read both. The tiering spec it extends is `docs/superpowers/specs/2026-09-13-tier-ranker-design.md`.

## Global Constraints

- The tier being ordered is the live session's tier 1 (`rank_placement.tier = 1`, any `how`), never the saved list (O2). `ORDER_TIER = 1` is one constant in `application/rank.py`; the `tier` column exists in all three tables but no route or control takes a tier (O9).
- Verdict vocabulary on the wire and in the log: `better` / `worse`, meaning the CANDIDATE is better/worse than the film it was shown. No `same` (O4).
- Slots are the k+1 gaps of a k-film order, 0-based in the domain; `rank_order.position` is 1-based and dense per (session, tier). Inserting at slot s writes position s+1 and shifts every position ≥ s+1 up by one.
- Bounds derive from the log on every request; `lo > hi` raises `ValueError` in the domain and is reported as `corrupt` by the use case, never a 500 (spec §4.1, §4.3).
- Removal of a film from the order (drawer unseen, merge) deletes every `rank_order_comparison` row naming it as candidate OR other, in every session, and compacts positions (spec §4.4).
- One undo slot: `rank_session.last_action` gains `"mode": "tiers" | "order"`. Order-mode kinds are `order_verdict` (with `comparison_id` and `inserted: bool`) and `order_defer` (O8).
- Save writes the same slug `my-owned-tiers` through the same `replace_list_entries`; tier 1's ordered films are lines 1..k bare, the unordered rest tied at `=k+1` (a lone unordered film bare), tiers 2–5 unchanged; with no film ordered the output is byte-for-byte today's (spec §4.5).
- One concretisation of the spec, recorded here: spec §6 says `GET /api/rank/order` answers 409 with no open session. Every existing `/api/rank/*` route that needs a session answers **404** through `_session()`; the order routes use the same helper and the same 404. Task 7 amends the spec line.
- Markdown written by this plan (`CLAUDE.md`, `docs/backlog.md`, the spec) is never hard-wrapped: one paragraph per line.
- Every task ends green on `uv run pytest -q` (~40 s), `uv run ruff check .` and `uv run mypy`. Commit messages: one line, the "why", plus the attribution trailer the session reminder gives.
- The application layer imports no `sqlite3`.

---

## File structure

| File | Responsibility |
|---|---|
| `migrations/023_order_top_tier.sql` | `rank_order`, `rank_order_comparison`, `rank_order_deferral` (spec §3). |
| `src/movie_brain/domain/rank.py` | Adds `Probe`, `Insert`, `order_step`; `tiered_entries` gains an `order` argument. |
| `src/movie_brain/infrastructure/database.py` | Order methods in the tier-ranker section; `set_unseen` cascade; `merge_film` moves. |
| `src/movie_brain/application/rank.py` | `ORDER_TIER`, `_order_queue`, `order_state`, `order_verdict`, `order_pass`; `undo` and `save_list` learn the order. |
| `src/movie_brain/web/app.py` | `GET /api/rank/order`, `POST /api/rank/order/verdict`, `POST /api/rank/order/pass`. |
| `src/movie_brain/web/templates/rank.html`, `static/rank.js`, `static/rank.css` | Tabs, order-mode pair, progress line, done/no-session sections. |
| `tests/unit/test_rank.py` | `order_step` table; `tiered_entries` with an order. |
| `tests/unit/test_rank_repository.py` | Order methods, `set_unseen` cascade, `merge_film` moves (appended). |
| `tests/features/rank_order.feature`, `tests/step_defs/test_rank_order.py` | Use-case scenarios (new files, self-contained steps). |
| `tests/web/test_api.py` | Route tests (appended). |
| `tests/web/test_rank_page.py` | Playwright flow (extended at the end). |
| `CLAUDE.md`, `docs/backlog.md`, the spec | Docs. |

---

### Task 0: Branch and commit the pending work

**Files:** none new. The working tree holds two uncommitted changes from the same session: the one-click "Have not seen" (rank.js, rank.css, the tiering spec's D9 amendment, `tests/web/test_rank_page.py`) and the new spec.

- [ ] **Step 1: Branch from main**

```bash
git checkout -b feature/STORY-16-order-top-tier
```

- [ ] **Step 2: Commit the one-click unseen change**

```bash
git add src/movie_brain/web/static/rank.js src/movie_brain/web/static/rank.css tests/web/test_rank_page.py docs/superpowers/specs/2026-09-13-tier-ranker-design.md
git commit -m "Have not seen sends the pass itself: a mark that needs a confirming Pass is a click the owner found pointless in practice"
```

- [ ] **Step 3: Commit the spec and this plan**

```bash
git add docs/superpowers/specs/2026-09-13-order-top-tier-design.md docs/superpowers/plans/2026-09-13-order-top-tier.md
git commit -m "spec + plan: strict-order tier 1 by log-derived binary insertion (backlog 16)"
```

---

### Task 1: Migration 023 and the repository's order methods

**Files:**
- Create: `migrations/023_order_top_tier.sql`
- Modify: `src/movie_brain/infrastructure/database.py` (the "tier ranker" section after `rank_deferrals`, and `set_unseen`)
- Test: `tests/unit/test_rank_repository.py` (append)

**Interfaces:**
- Consumes: `Repository.create_rank_session(source, seed, anchors, placements, today) -> int`, `set_unseen(film_id, unseen, today, note=None)`, `rank_placements(session_id)`.
- Produces (all on `Repository`):
  - `rank_order(session_id: int, tier: int) -> list[int]` — film ids by position.
  - `insert_ordered(session_id: int, tier: int, film_id: int, slot: int, today: date) -> None` — 0-based slot.
  - `remove_ordered(film_id: int, session_id: int | None = None) -> int` — rows deleted, positions compacted; every session unless one is named.
  - `append_order_comparison(session_id: int, tier: int, film_id: int, other_film_id: int, verdict: str, today: date) -> int`
  - `order_verdicts_for(session_id: int, film_id: int) -> list[tuple[int, str]]` — `(other_film_id, verdict)` in log order.
  - `films_with_order_verdicts(session_id: int) -> set[int]`
  - `delete_order_comparison(comparison_id: int) -> None`
  - `defer_order_film(session_id: int, film_id: int, stamp: str) -> None`, `undefer_order_film(session_id: int, film_id: int) -> None`, `order_deferrals(session_id: int) -> dict[int, str]`
  - `set_unseen` additionally removes the film from every order, deletes every order comparison naming it on either side, and its order deferrals.

- [ ] **Step 1: Write the failing repository tests**

Append to `tests/unit/test_rank_repository.py`:

```python
def _order_session(repo, n=4):
    """A session whose tier 1 holds n seeded films; returns (sid, [film ids])."""
    ids = [_film(repo, f"T{i}", 1950 + i) for i in range(n)]
    sid = repo.create_rank_session("owned", 1, {1: ids[0]}, {i: 1 for i in ids}, D)
    return sid, ids


def test_insert_ordered_keeps_positions_dense_and_shifts_later_rows(repo):
    sid, (a, b, c, d) = _order_session(repo)
    repo.insert_ordered(sid, 1, a, 0, D)          # [a]
    repo.insert_ordered(sid, 1, b, 1, D)          # [a, b]  (append)
    repo.insert_ordered(sid, 1, c, 0, D)          # [c, a, b]
    repo.insert_ordered(sid, 1, d, 2, D)          # [c, a, d, b]
    assert repo.rank_order(sid, 1) == [c, a, d, b]
    with repo._conn() as conn:
        rows = conn.execute(
            "SELECT position FROM rank_order WHERE session_id = ? ORDER BY position", (sid,)
        ).fetchall()
    assert [r["position"] for r in rows] == [1, 2, 3, 4]
    assert repo.rank_order(sid, 2) == []


def test_remove_ordered_compacts_and_scopes_to_a_session(repo):
    sid, (a, b, c, _) = _order_session(repo)
    other = repo.create_rank_session("list", 2, {1: a}, {a: 1, b: 1}, D)   # a second source: "owned" allows one open session
    for s in (sid, other):
        repo.insert_ordered(s, 1, a, 0, D)
        repo.insert_ordered(s, 1, b, 1, D)
    repo.insert_ordered(sid, 1, c, 2, D)
    assert repo.remove_ordered(a, sid) == 1
    assert repo.rank_order(sid, 1) == [b, c] and repo.rank_order(other, 1) == [a, b]
    assert repo.remove_ordered(b) == 2   # every session
    assert repo.rank_order(sid, 1) == [c] and repo.rank_order(other, 1) == [a]
    assert repo.remove_ordered(999) == 0


def test_order_comparisons_log_in_order_and_delete_by_id(repo):
    sid, (a, b, c, _) = _order_session(repo)
    i1 = repo.append_order_comparison(sid, 1, c, a, "better", D)
    i2 = repo.append_order_comparison(sid, 1, c, b, "worse", D)
    assert repo.order_verdicts_for(sid, c) == [(a, "better"), (b, "worse")]
    assert repo.films_with_order_verdicts(sid) == {c}
    repo.delete_order_comparison(i2)
    assert repo.order_verdicts_for(sid, c) == [(a, "better")]
    assert i1 < i2


def test_order_deferrals_round_trip(repo):
    sid, (a, b, _, _) = _order_session(repo)
    repo.defer_order_film(sid, a, "2026-09-13")
    repo.defer_order_film(sid, b, "2026-09-14")
    assert repo.order_deferrals(sid) == {a: "2026-09-13", b: "2026-09-14"}
    repo.undefer_order_film(sid, a)
    assert repo.order_deferrals(sid) == {b: "2026-09-14"}
    assert repo.rank_deferrals(sid) == {}   # the tiering's own table is untouched


def test_marking_unseen_removes_the_film_from_the_order_and_every_verdict_naming_it(repo):
    sid, (a, b, c, d) = _order_session(repo)
    repo.insert_ordered(sid, 1, a, 0, D)
    repo.insert_ordered(sid, 1, b, 1, D)
    repo.insert_ordered(sid, 1, c, 2, D)
    repo.append_order_comparison(sid, 1, d, b, "better", D)   # d mid-search, against b
    repo.append_order_comparison(sid, 1, b, a, "worse", D)    # b's own old verdict
    repo.defer_order_film(sid, b, "2026-09-13")
    repo.set_unseen(b, True, D)
    assert repo.rank_order(sid, 1) == [a, c]
    assert repo.order_verdicts_for(sid, d) == []   # the verdict AGAINST b is gone too
    assert repo.order_verdicts_for(sid, b) == []
    assert repo.order_deferrals(sid) == {}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/unit/test_rank_repository.py -q -k "ordered or order_ or naming_it"`
Expected: FAIL with `AttributeError: 'Repository' object has no attribute 'insert_ordered'` (and the `set_unseen` test fails on the missing table).

- [ ] **Step 3: Write the migration**

Create `migrations/023_order_top_tier.sql`:

```sql
-- Order inside a tier (spec docs/superpowers/specs/2026-09-13-order-top-tier-design.md §3).
-- Three tables beside 022's six: the order itself (dense positions per session+tier), the
-- insertion search's append-only log (its ONLY state — bounds are derived from it on every
-- read), and the order-mode Pass. All film-scoped; merge_film moves them survivor-wins.
BEGIN;
CREATE TABLE rank_order (
    session_id INTEGER NOT NULL REFERENCES rank_session(id),
    tier       INTEGER NOT NULL CHECK (tier BETWEEN 1 AND 5),
    film_id    INTEGER NOT NULL REFERENCES films(id),
    position   INTEGER NOT NULL CHECK (position >= 1),
    ordered_on TEXT    NOT NULL,
    PRIMARY KEY (session_id, film_id),
    UNIQUE (session_id, tier, position)
);
CREATE TABLE rank_order_comparison (
    id            INTEGER PRIMARY KEY,
    session_id    INTEGER NOT NULL REFERENCES rank_session(id),
    tier          INTEGER NOT NULL CHECK (tier BETWEEN 1 AND 5),
    film_id       INTEGER NOT NULL REFERENCES films(id),
    other_film_id INTEGER NOT NULL REFERENCES films(id),
    verdict       TEXT    NOT NULL CHECK (verdict IN ('better', 'worse')),
    decided_on    TEXT    NOT NULL
);
CREATE INDEX rank_order_comparison_film ON rank_order_comparison(session_id, film_id, id);
CREATE INDEX rank_order_comparison_other ON rank_order_comparison(other_film_id);
CREATE TABLE rank_order_deferral (
    session_id  INTEGER NOT NULL REFERENCES rank_session(id),
    film_id     INTEGER NOT NULL REFERENCES films(id),
    deferred_on TEXT    NOT NULL,
    PRIMARY KEY (session_id, film_id)
);
INSERT INTO schema_version (version) VALUES (23);
COMMIT;
```

- [ ] **Step 4: Add the repository methods**

In `src/movie_brain/infrastructure/database.py`, directly after `rank_deferrals` (before `set_last_action`), add:

```python
    # order inside a tier (spec 2026-09-13-order-top-tier §3) ------------------
    def rank_order(self, session_id: int, tier: int) -> list[int]:
        """The tier's film ids by position, 1..k dense."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT film_id FROM rank_order WHERE session_id = ? AND tier = ? ORDER BY position",
                (session_id, tier),
            ).fetchall()
            return [int(r["film_id"]) for r in rows]

    def insert_ordered(self, session_id: int, tier: int, film_id: int, slot: int, today: date) -> None:
        """Insert at a 0-based slot (position slot+1); every row at or after it moves up one.
        The UNIQUE on position means the shift must run highest-first, one row at a time —
        a single `SET position = position + 1` collides row by row under SQLite."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT film_id, position FROM rank_order WHERE session_id = ? AND tier = ? AND position > ? "
                "ORDER BY position DESC",
                (session_id, tier, slot),
            ).fetchall()
            for r in rows:
                c.execute(
                    "UPDATE rank_order SET position = ? WHERE session_id = ? AND film_id = ?",
                    (int(r["position"]) + 1, session_id, int(r["film_id"])),
                )
            c.execute(
                "INSERT INTO rank_order (session_id, tier, film_id, position, ordered_on) VALUES (?, ?, ?, ?, ?)",
                (session_id, tier, film_id, slot + 1, today.isoformat()),
            )

    @staticmethod
    def _remove_ordered(c: sqlite3.Connection, film_id: int, session_id: int | None = None) -> int:
        """Delete the film's order row(s) and close each gap, lowest-first so no UNIQUE collides."""
        where, args = ("WHERE film_id = ?", [film_id]) if session_id is None else (
            "WHERE film_id = ? AND session_id = ?", [film_id, session_id]
        )
        rows = c.execute(f"SELECT session_id, tier, position FROM rank_order {where}", args).fetchall()
        for r in rows:
            sid, tier, pos = int(r["session_id"]), int(r["tier"]), int(r["position"])
            c.execute("DELETE FROM rank_order WHERE session_id = ? AND film_id = ?", (sid, film_id))
            later = c.execute(
                "SELECT film_id, position FROM rank_order WHERE session_id = ? AND tier = ? AND position > ? "
                "ORDER BY position",
                (sid, tier, pos),
            ).fetchall()
            for r2 in later:
                c.execute(
                    "UPDATE rank_order SET position = ? WHERE session_id = ? AND film_id = ?",
                    (int(r2["position"]) - 1, sid, int(r2["film_id"])),
                )
        return len(rows)

    def remove_ordered(self, film_id: int, session_id: int | None = None) -> int:
        with self._conn() as c:
            return self._remove_ordered(c, film_id, session_id)

    def append_order_comparison(
        self, session_id: int, tier: int, film_id: int, other_film_id: int, verdict: str, today: date
    ) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO rank_order_comparison (session_id, tier, film_id, other_film_id, verdict, decided_on) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, tier, film_id, other_film_id, verdict, today.isoformat()),
            )
            assert cur.lastrowid is not None
            return int(cur.lastrowid)

    def order_verdicts_for(self, session_id: int, film_id: int) -> list[tuple[int, str]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT other_film_id, verdict FROM rank_order_comparison "
                "WHERE session_id = ? AND film_id = ? ORDER BY id",
                (session_id, film_id),
            ).fetchall()
            return [(int(r["other_film_id"]), str(r["verdict"])) for r in rows]

    def films_with_order_verdicts(self, session_id: int) -> set[int]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT DISTINCT film_id FROM rank_order_comparison WHERE session_id = ?", (session_id,)
            ).fetchall()
            return {int(r["film_id"]) for r in rows}

    def delete_order_comparison(self, comparison_id: int) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM rank_order_comparison WHERE id = ?", (comparison_id,))

    def defer_order_film(self, session_id: int, film_id: int, stamp: str) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO rank_order_deferral (session_id, film_id, deferred_on) VALUES (?, ?, ?)",
                (session_id, film_id, stamp),
            )

    def undefer_order_film(self, session_id: int, film_id: int) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM rank_order_deferral WHERE session_id = ? AND film_id = ?", (session_id, film_id))

    def order_deferrals(self, session_id: int) -> dict[int, str]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT film_id, deferred_on FROM rank_order_deferral WHERE session_id = ?", (session_id,)
            ).fetchall()
            return {int(r["film_id"]): str(r["deferred_on"]) for r in rows}

    @staticmethod
    def _purge_order_rows(c: sqlite3.Connection, film_id: int) -> None:
        """Everything the order knows about a film that has left it (spec §4.4): its row in
        every session (gaps closed), every verdict naming it on EITHER side, its deferrals."""
        Repository._remove_ordered(c, film_id)
        c.execute("DELETE FROM rank_order_comparison WHERE film_id = ? OR other_film_id = ?", (film_id, film_id))
        c.execute("DELETE FROM rank_order_deferral WHERE film_id = ?", (film_id,))
```

Then in `set_unseen`, after the two existing `DELETE FROM rank_placement` / `rank_comparison` lines inside `if unseen:`, add:

```python
                self._purge_order_rows(c, film_id)
```

and extend its docstring: "... and, since migration 023, drops it from every tier order together with every order verdict naming it on either side (order spec §4.4)."

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/unit/test_rank_repository.py -q`
Expected: all pass (the new five plus the existing ones).

- [ ] **Step 6: Full gate and commit**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy`
Expected: green.

```bash
git add migrations/023_order_top_tier.sql src/movie_brain/infrastructure/database.py tests/unit/test_rank_repository.py
git commit -m "migration 023: the tier order, its log and its deferrals; unseen purges a film from the order on both sides so derived bounds can never cross"
```

---

### Task 2: The insertion search and the ordered save (`domain/rank.py`)

**Files:**
- Modify: `src/movie_brain/domain/rank.py`
- Test: `tests/unit/test_rank.py`

**Interfaces:**
- Produces: `Probe(film_id: int)`, `Insert(slot: int)` frozen dataclasses; `order_step(order: Sequence[int], verdicts: Iterable[tuple[int, str]]) -> Probe | Insert`; `tiered_entries(placed: Iterable[Placed], order: Mapping[int, int] | None = None) -> list[TieredEntry]` where `order` maps film id → 1-based position.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_rank.py` (extend the import from `movie_brain.domain.rank` with `Insert, Probe, order_step`):

```python
def test_order_step_inserts_the_first_film_without_a_click():
    assert order_step([], []) == Insert(0)


def test_order_step_probes_the_only_film_then_inserts_either_side():
    assert order_step([10], []) == Probe(10)
    assert order_step([10], [(10, "better")]) == Insert(0)
    assert order_step([10], [(10, "worse")]) == Insert(1)


def test_order_step_halves_the_slot_range_each_verdict():
    order = [1, 2, 3, 4, 5]                       # slots 0..5
    assert order_step(order, []) == Probe(3)      # (0+5)//2 = 2 → film 3
    assert order_step(order, [(3, "worse")]) == Probe(5)            # lo=3, hi=5 → index 4
    assert order_step(order, [(3, "worse"), (5, "better")]) == Probe(4)   # lo=3, hi=4 → index 3
    assert order_step(order, [(3, "worse"), (5, "better"), (4, "worse")]) == Insert(4)
    assert order_step(order, [(3, "better")]) == Probe(2)           # lo=0, hi=2 → index 1
    assert order_step(order, [(3, "better"), (2, "better"), (1, "better")]) == Insert(0)


def test_order_step_ignores_a_verdict_against_a_film_no_longer_in_the_order():
    assert order_step([1, 2], [(99, "better")]) == Probe(2)


def test_order_step_raises_on_crossed_bounds_or_an_unknown_verdict():
    assert order_step([1, 2, 3], [(3, "better"), (1, "worse")]) == Probe(2)   # hi=2, lo=1: not crossed
    with pytest.raises(ValueError):
        order_step([1, 2, 3], [(1, "better"), (3, "worse")])   # hi=0, lo=3: crossed
    with pytest.raises(ValueError):
        order_step([1], [(1, "same")])


def test_tiered_entries_with_an_order_ranks_tier_1_bare_then_ties_the_rest():
    placed = [
        Placed(11, 1, "Zulu", "Z"),
        Placed(12, 1, "Alpha", "A"),
        Placed(13, 1, "Mike", "M"),
        Placed(14, 1, "Bravo", "B"),
        Placed(20, 2, "Two", None),
        Placed(50, 5, "Solo", None),
    ]
    got = tiered_entries(placed, {13: 1, 11: 2})
    assert [(e.rank, e.film_id, e.rank_label) for e in got] == [
        (1, 13, None),      # ordered: Mike at position 1
        (2, 11, None),      # ordered: Zulu at position 2
        (3, 12, "=3"),      # unordered tier 1, by title, tied at the first unordered line
        (4, 14, "=3"),
        (5, 20, None),
        (6, 50, None),
    ]


def test_tiered_entries_with_a_lone_unordered_film_leaves_it_bare():
    placed = [Placed(11, 1, "Zulu", None), Placed(12, 1, "Alpha", None)]
    got = tiered_entries(placed, {11: 1})
    assert [(e.rank, e.film_id, e.rank_label) for e in got] == [(1, 11, None), (2, 12, None)]


def test_tiered_entries_without_an_order_is_unchanged():
    placed = [Placed(11, 1, "Zulu", None), Placed(12, 1, "Alpha", None)]
    assert tiered_entries(placed) == tiered_entries(placed, {})
    assert [e.rank_label for e in tiered_entries(placed)] == ["=1", "=1"]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_rank.py -q -k "order_step or with_an_order or lone_unordered or without_an_order"`
Expected: FAIL with `ImportError: cannot import name 'Insert'`.

- [ ] **Step 3: Implement**

In `src/movie_brain/domain/rank.py`, after `next_step`, add:

```python
@dataclass(frozen=True)
class Probe:
    """Show the candidate against this ordered film (order spec §4.1)."""

    film_id: int


@dataclass(frozen=True)
class Insert:
    """The candidate's slot is pinned: 0-based gap in the order (0 = before everything)."""

    slot: int


def order_step(order: Sequence[int], verdicts: Iterable[tuple[int, str]]) -> Probe | Insert:
    """Binary insertion with bounds derived from the log (order spec §4.1, O5).

    `order` is the tier's film ids by position; `verdicts` the candidate's logged
    (other_film_id, verdict) pairs. `better` caps the slot at that film's index, `worse`
    floors it at index + 1. A verdict against a film no longer in the order is ignored
    (§4.3 says why one can only exist transiently). Crossed bounds cannot arise by
    construction; if they do, the log is corrupt and this raises like `next_step`.
    """
    index = {fid: i for i, fid in enumerate(order)}
    lo, hi = 0, len(order)
    for other, verdict in verdicts:
        i = index.get(other)
        if i is None:
            continue
        if verdict == "better":
            hi = min(hi, i)
        elif verdict == "worse":
            lo = max(lo, i + 1)
        else:
            raise ValueError(f"illegal order verdict {verdict!r}")
    if lo > hi:
        raise ValueError(f"crossed order bounds lo={lo} hi={hi}")
    if lo == hi:
        return Insert(lo)
    return Probe(order[(lo + hi) // 2])
```

Replace `tiered_entries` with:

```python
def tiered_entries(placed: Iterable[Placed], order: Mapping[int, int] | None = None) -> list[TieredEntry]:
    """The saved list's lines (tier spec §7, order spec §4.5): tier asc; inside a tier the
    ordered films first by position with bare labels, then the rest by title tied at the
    first unordered line (`=N`) when two or more, bare when one. With no order this is
    byte-for-byte the tiering's own output."""
    positions = dict(order or {})
    by_tier: dict[int, list[Placed]] = {}
    for p in placed:
        by_tier.setdefault(p.tier, []).append(p)
    out: list[TieredEntry] = []
    line = 0
    for tier in sorted(by_tier):
        members = by_tier[tier]
        ordered = sorted((p for p in members if p.film_id in positions), key=lambda p: positions[p.film_id])
        rest = sorted(
            (p for p in members if p.film_id not in positions), key=lambda p: (p.title.casefold(), p.film_id)
        )
        for p in ordered:
            line += 1
            out.append(TieredEntry(line, p.film_id, p.title, p.director, None))
        first_rest = line + 1
        for p in rest:
            line += 1
            out.append(TieredEntry(line, p.film_id, p.title, p.director, f"={first_rest}" if len(rest) > 1 else None))
    return out
```

- [ ] **Step 4: Run the domain tests**

Run: `uv run pytest tests/unit/test_rank.py -q`
Expected: all pass, including the pre-existing `test_tiered_entries_label_ties_and_leave_singletons_bare`.

- [ ] **Step 5: Full gate and commit**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy`

```bash
git add src/movie_brain/domain/rank.py tests/unit/test_rank.py
git commit -m "order_step derives the insertion slot from the verdict log, and the save ranks an ordered tier bare before its tied remainder"
```

---

### Task 3: `merge_film` moves the three tables

**Files:**
- Modify: `src/movie_brain/infrastructure/database.py` (`merge_film`, the ranker block)
- Test: `tests/unit/test_rank_repository.py` (append)

**Interfaces:**
- Consumes: Task 1's `_remove_ordered`, `_purge_order_rows`, `rank_order`, `order_verdicts_for`, `order_deferrals`.

- [ ] **Step 1: Write the failing tests**

```python
def test_merge_moves_the_order_survivor_wins_and_compacts(repo):
    a, b = _film(repo, "Alpha", 1950), _film(repo, "Alpha", 1951)
    c = _film(repo, "Gamma", 1960)
    sid = repo.create_rank_session("owned", 1, {1: a}, {a: 1, b: 1, c: 1}, D)
    repo.insert_ordered(sid, 1, a, 0, D)
    repo.insert_ordered(sid, 1, b, 1, D)
    repo.insert_ordered(sid, 1, c, 2, D)          # [a, b, c]
    repo.defer_order_film(sid, b, "2026-09-13")
    repo.merge_film(b, a, D)
    assert repo.rank_order(sid, 1) == [a, c]      # survivor's row wins, loser's dropped, gap closed
    assert repo.order_deferrals(sid) == {a: "2026-09-13"}
    other = repo.create_rank_session("list", 2, {1: c}, {c: 1}, D)   # a second session: loser only
    d, e = _film(repo, "Delta", 1970), _film(repo, "Delta", 1971)
    repo.insert_ordered(other, 1, e, 0, D)
    repo.merge_film(e, d, D)
    assert repo.rank_order(other, 1) == [d]       # loser's row moves when the survivor has none


def test_merge_repoints_order_verdicts_and_drops_self_comparisons(repo):
    a, b = _film(repo, "Alpha", 1950), _film(repo, "Alpha", 1951)
    c, x = _film(repo, "Gamma", 1960), _film(repo, "Xi", 1970)
    sid = repo.create_rank_session("owned", 1, {1: a}, {a: 1, b: 1, c: 1, x: 1}, D)
    repo.append_order_comparison(sid, 1, c, b, "better", D)   # c judged against the loser → re-points to a
    repo.append_order_comparison(sid, 1, b, x, "worse", D)    # loser mid-search → moves (survivor has none)
    repo.append_order_comparison(sid, 1, a, b, "worse", D)    # survivor judged against loser → would be a vs a
    report = repo.merge_film(b, a, D)
    assert repo.order_verdicts_for(sid, c) == [(a, "better")]
    # a already had a candidate row (a-vs-b), so b's own row is DROPPED, not moved (survivor
    # wins per session); the a-vs-b row re-points to a-vs-a and is then deleted. Two drops.
    assert repo.order_verdicts_for(sid, a) == []
    assert repo.order_verdicts_for(sid, b) == []
    assert report.dropped.get("rank_order_comparison") == 2


def test_merge_drops_losers_order_verdicts_when_survivor_is_also_mid_insertion(repo):
    a, b = _film(repo, "Alpha", 1950), _film(repo, "Alpha", 1951)
    x = _film(repo, "Xi", 1970)
    sid = repo.create_rank_session("owned", 1, {1: x}, {a: 1, b: 1, x: 1}, D)
    repo.append_order_comparison(sid, 1, a, x, "better", D)
    repo.append_order_comparison(sid, 1, b, x, "worse", D)
    repo.merge_film(b, a, D)
    assert repo.order_verdicts_for(sid, a) == [(x, "better")]   # its OWN log, untouched
    assert repo.order_verdicts_for(sid, b) == []


def test_merge_onto_an_unseen_survivor_purges_the_losers_order_rows(repo):
    a, b = _film(repo, "Alpha", 1950), _film(repo, "Alpha", 1951)
    x = _film(repo, "Xi", 1970)
    sid = repo.create_rank_session("owned", 1, {1: x}, {b: 1, x: 1}, D)
    repo.insert_ordered(sid, 1, x, 0, D)
    repo.insert_ordered(sid, 1, b, 1, D)
    repo.append_order_comparison(sid, 1, b, x, "worse", D)
    repo.set_unseen(a, True, D)
    repo.merge_film(b, a, D)
    assert repo.rank_order(sid, 1) == [x]
    assert repo.order_verdicts_for(sid, a) == [] and repo.order_verdicts_for(sid, b) == []
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_rank_repository.py -q -k "merge and order"`
Expected: FAIL (order rows still name the loser; `rank_order` still lists `b`).

- [ ] **Step 3: Implement in `merge_film`**

In the ranker block of `merge_film`:

1. Change the per-session survivor-wins loop's tuple from `("rank_placement", "rank_deferral")` to `("rank_placement", "rank_deferral", "rank_order_deferral")`.
2. Directly after that loop (before the `rank_anchor` update), add:

```python
            # rank_order (order spec §4.4): per session, the survivor's row wins and the loser's
            # is dropped with its gap closed; where the survivor has none, the loser's moves.
            for row in c.execute("SELECT session_id FROM rank_order WHERE film_id = ?", (loser_id,)).fetchall():
                sid = int(row["session_id"])
                twin = c.execute(
                    "SELECT 1 FROM rank_order WHERE session_id = ? AND film_id = ?", (sid, survivor_id)
                ).fetchone()
                if twin:
                    self._remove_ordered(c, loser_id, sid)
                    dropped["rank_order"] = dropped.get("rank_order", 0) + 1
                else:
                    c.execute(
                        "UPDATE rank_order SET film_id = ? WHERE session_id = ? AND film_id = ?",
                        (survivor_id, sid, loser_id),
                    )
                    moved["rank_order"] = moved.get("rank_order", 0) + 1
```

3. Directly after the existing `rank_comparison` candidate-side loop and its `anchor_film_id` re-point, add the same shape for the order log:

```python
            # rank_order_comparison: candidate side survivor-wins per session (a concatenated
            # log could cross the derived bounds); other side re-points unconditionally; a row
            # that would then compare the survivor with itself audits nothing and is deleted.
            for row in c.execute(
                "SELECT DISTINCT session_id FROM rank_order_comparison WHERE film_id = ?", (loser_id,)
            ).fetchall():
                sid = int(row["session_id"])
                twin = c.execute(
                    "SELECT 1 FROM rank_order_comparison WHERE session_id = ? AND film_id = ? LIMIT 1",
                    (sid, survivor_id),
                ).fetchone()
                if twin is not None:
                    n = c.execute(
                        "DELETE FROM rank_order_comparison WHERE session_id = ? AND film_id = ?", (sid, loser_id)
                    ).rowcount
                    dropped["rank_order_comparison"] = dropped.get("rank_order_comparison", 0) + n
                else:
                    n = c.execute(
                        "UPDATE rank_order_comparison SET film_id = ? WHERE session_id = ? AND film_id = ?",
                        (survivor_id, sid, loser_id),
                    ).rowcount
                    moved["rank_order_comparison"] = moved.get("rank_order_comparison", 0) + n
            n = c.execute(
                "UPDATE rank_order_comparison SET other_film_id = ? WHERE other_film_id = ?", (survivor_id, loser_id)
            ).rowcount
            if n:
                moved["rank_order_comparison"] = moved.get("rank_order_comparison", 0) + n
            n = c.execute(
                "DELETE FROM rank_order_comparison WHERE film_id = ? AND other_film_id = ?", (survivor_id, survivor_id)
            ).rowcount
            if n:
                dropped["rank_order_comparison"] = dropped.get("rank_order_comparison", 0) + n
```

4. In the "survivor is unseen" purge block (`if c.execute("SELECT 1 FROM unseen WHERE film_id = ?", (survivor_id,))...`), add after the two deletes:

```python
                self._purge_order_rows(c, survivor_id)
```

The second test's arithmetic: the a-vs-b row has `a` as candidate, so the candidate-side loop leaves it; `a` therefore already holds a log in the session, so the loser's b-vs-x row is dropped (count 1); the other-side re-point turns a-vs-b into a-vs-a, which the final delete removes (count 2).

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_rank_repository.py -q`
Expected: pass.

- [ ] **Step 5: Full gate and commit**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy`

```bash
git add src/movie_brain/infrastructure/database.py tests/unit/test_rank_repository.py
git commit -m "merge_film moves the tier order survivor-wins and never leaves a verdict that compares a film with itself"
```

---

### Task 4: The use case (`application/rank.py`) with pytest-bdd scenarios

**Files:**
- Modify: `src/movie_brain/application/rank.py`
- Create: `tests/features/rank_order.feature`, `tests/step_defs/test_rank_order.py`

**Interfaces:**
- Consumes: Task 1's repository methods; Task 2's `order_step`, `Probe`, `Insert`, `tiered_entries(placed, order)`; existing `_session`, `_film`, `order_queue`, `session_state`, `record_verdict`, `save_list`, `undo`.
- Produces:
  - `ORDER_TIER: int = 1`
  - `order_state(repo, source, today) -> dict[str, object]` with keys `tier`, `ordered`, `remaining`, `pair` (`{candidate, other, position, of, asked}` or `None`), `done`, `can_undo`, `corrupt`. 404 via `_session` when no session is open.
  - `order_verdict(repo, source, film_id, other_film_id, verdict, today) -> dict[str, object]` (returns `order_state`).
  - `order_pass(repo, source, film_id, today) -> dict[str, object]` (returns `order_state`).
  - `undo` returns `order_state` when the undone action's `mode` is `order`, else `session_state`.

- [ ] **Step 1: Write the feature file**

Create `tests/features/rank_order.feature`:

```gherkin
Feature: Order tier 1 — strict order inside the top tier by binary insertion

  Background:
    Given owned films rated "Alpha" 10, "Beta" 10, "Gamma" 10, "Delta" 10, "Nine" 9, "Eight" 8, "Seven" 7, "Four" 4
    And an owned unrated film "Uno"
    And a started tiering session

  Scenario: The first tier 1 film is ordered without a click and the second is asked against it
    Then 1 film is ordered and 3 remain to order
    And the order pair shows position 1 of 1

  Scenario: Answering better every time puts each film at the top
    When I answer better in order mode until the candidate is inserted
    Then the last inserted film is at position 1
    When I answer better in order mode until the candidate is inserted
    Then the last inserted film is at position 1
    And 3 films are ordered

  Scenario: Answering worse every time appends each film
    When I answer worse in order mode until the candidate is inserted
    Then the last inserted film is at position 2
    When I answer worse in order mode until the candidate is inserted
    Then the last inserted film is at position 3

  Scenario: Every film ordered means done, and a later tier 1 placement reopens the queue
    When I answer better in order mode until the candidate is inserted
    And I answer better in order mode until the candidate is inserted
    And I answer better in order mode until the candidate is inserted
    Then the order is done with 4 films ordered
    When "Uno" is tiered into tier 1
    Then 4 films are ordered and 1 remains to order

  Scenario: A stale order verdict is refused
    Then answering better against a film that is not the shown one is refused with 409

  Scenario: Pass in order mode defers the candidate to the back
    When I pass in order mode
    Then the deferred film comes last in the order queue

  Scenario: Undo reverts an order verdict, an insertion and a deferral, one level deep
    When I answer worse in order mode
    Then 2 films are ordered
    When I undo
    Then 1 film is ordered and the same candidate is asked with 0 verdicts
    When I pass in order mode
    And I undo
    Then nothing is deferred in order mode
    And undoing again is refused with 409

  Scenario: One undo slot serves both modes
    When I answer worse in order mode
    And I answer better, better in tiering mode
    And I undo
    Then the tiering candidate is unplaced again
    And 2 films are ordered
    And undoing again is refused with 409

  Scenario: Marking an ordered film unseen from the drawer removes it and every verdict naming it
    When I answer worse in order mode
    And I answer worse in order mode until the candidate is inserted
    Then 3 films are ordered
    When I answer better in order mode
    And the film at position 2 is marked unseen from the drawer
    Then 2 films are ordered
    And the current candidate has 0 verdicts

  Scenario: Saving writes tier 1's order bare, the rest of tier 1 tied, and the other tiers as before
    When I answer worse in order mode
    And I save the list as "Mine"
    Then the list "my-owned-tiers" has 8 entries
    And entries 1 and 2 carry no label
    And entries 3 and 4 carry label "=3"
    And entry 5 is "Nine" with no label

  Scenario: Order state needs an open session
    Given the session is finished
    Then reading the order state is refused with 404
```

- [ ] **Step 2: Write the step definitions**

Create `tests/step_defs/test_rank_order.py`:

```python
from __future__ import annotations

from datetime import date

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.rank import (
    ORDER_TIER,
    RankError,
    order_pass,
    order_state,
    order_verdict,
    proposal,
    record_verdict,
    save_list,
    session_state,
    start_session,
    undo,
)
from movie_brain.domain.models import Film

scenarios("../features/rank_order.feature")
TODAY = date(2026, 9, 13)
SRC = "owned"


@pytest.fixture
def ctx(repo, tmp_path):
    return {"repo": repo, "ids": {}, "lists_dir": tmp_path / "lists"}


def _id(ctx, title):
    return ctx["ids"][title]


def _sid(ctx):
    return ctx["repo"].open_rank_session(SRC).id


def _order(ctx):
    return order_state(ctx["repo"], SRC, TODAY)


@given(parsers.parse('owned films rated "Alpha" {a:d}, "Beta" {b:d}, "Gamma" {c:d}, "Delta" {d:d}, "Nine" {e:d}, "Eight" {f:d}, "Seven" {g:d}, "Four" {h:d}'))
def rated(ctx, a, b, c, d, e, f, g, h):
    for title, score in (("Alpha", a), ("Beta", b), ("Gamma", c), ("Delta", d), ("Nine", e), ("Eight", f), ("Seven", g), ("Four", h)):
        fid = ctx["repo"].create_film(Film(title, 1950, "Dir", ""))
        ctx["repo"].mark_owned(fid, TODAY)
        ctx["repo"].set_rating(fid, score, TODAY)
        ctx["ids"][title] = fid


@given(parsers.parse('an owned unrated film "{title}"'))
def unrated(ctx, title):
    fid = ctx["repo"].create_film(Film(title, 1960, "Dir", ""))
    ctx["repo"].mark_owned(fid, TODAY)
    ctx["ids"][title] = fid


@given("a started tiering session")
def start(ctx):
    p = proposal(ctx["repo"], SRC)["proposal"]
    start_session(ctx["repo"], SRC, {t: p[t]["film_id"] for t in range(1, 6)}, TODAY)


@then(parsers.parse("{n:d} film is ordered and {m:d} remain to order"))
@then(parsers.parse("{n:d} films are ordered and {m:d} remain to order"))
@then(parsers.parse("{n:d} films are ordered and {m:d} remains to order"))
def ordered_and_remaining(ctx, n, m):
    s = _order(ctx)
    assert (s["ordered"], s["remaining"]) == (n, m)


@then(parsers.parse("{n:d} films are ordered"))
@then(parsers.parse("{n:d} film is ordered"))
def ordered_count(ctx, n):
    assert _order(ctx)["ordered"] == n


@then(parsers.parse("the order pair shows position {p:d} of {k:d}"))
def pair_position(ctx, p, k):
    pair = _order(ctx)["pair"]
    assert (pair["position"], pair["of"]) == (p, k)


def _answer_once(ctx, verdict):
    pair = _order(ctx)["pair"]
    assert pair is not None, "no order pair to answer"
    ctx["last_candidate"] = pair["candidate"]["film_id"]
    order_verdict(ctx["repo"], SRC, pair["candidate"]["film_id"], pair["other"]["film_id"], verdict, TODAY)


@when(parsers.parse("I answer {verdict} in order mode until the candidate is inserted"))
def answer_until_inserted(ctx, verdict):
    cand = _order(ctx)["pair"]["candidate"]["film_id"]
    for _ in range(10):
        _answer_once(ctx, verdict)
        if cand in ctx["repo"].rank_order(_sid(ctx), ORDER_TIER):
            return
    raise AssertionError("ten verdicts and still not inserted")


@when(parsers.parse("I answer {verdict} in order mode"))
def answer_once(ctx, verdict):
    _answer_once(ctx, verdict)


@then(parsers.parse("the last inserted film is at position {p:d}"))
def inserted_at(ctx, p):
    order = ctx["repo"].rank_order(_sid(ctx), ORDER_TIER)
    assert order.index(ctx["last_candidate"]) + 1 == p


@then(parsers.parse("the order is done with {n:d} films ordered"))
def order_done(ctx, n):
    s = _order(ctx)
    assert s["done"] is True and s["ordered"] == n and s["pair"] is None


@when(parsers.parse('"{title}" is tiered into tier 1'))
def tier_into_1(ctx, title):
    # The tiering's own path: better than tier 3's anchor, better than tier 2's → tier 1.
    for _ in range(2):
        s = session_state(ctx["repo"], SRC, TODAY)
        assert s["pair"]["candidate"]["film_id"] == _id(ctx, title)
        record_verdict(ctx["repo"], SRC, _id(ctx, title), s["pair"]["tier"], "better", TODAY)
    assert ctx["repo"].rank_placements(_sid(ctx))[_id(ctx, title)][0] == 1


@then(parsers.parse("answering better against a film that is not the shown one is refused with {status:d}"))
def stale_order_verdict(ctx, status):
    pair = _order(ctx)["pair"]
    wrong_other = next(i for i in ctx["ids"].values() if i not in (pair["other"]["film_id"], pair["candidate"]["film_id"]))
    with pytest.raises(RankError) as e:
        order_verdict(ctx["repo"], SRC, pair["candidate"]["film_id"], wrong_other, "better", TODAY)
    assert e.value.status == status


@when("I pass in order mode")
def pass_order(ctx):
    pair = _order(ctx)["pair"]
    ctx["last_candidate"] = pair["candidate"]["film_id"]
    order_pass(ctx["repo"], SRC, pair["candidate"]["film_id"], TODAY)


@then("the deferred film comes last in the order queue")
def deferred_last(ctx):
    repo = ctx["repo"]
    assert ctx["last_candidate"] in repo.order_deferrals(_sid(ctx))
    s = _order(ctx)
    assert s["pair"]["candidate"]["film_id"] != ctx["last_candidate"]
    # Insert everything else with one click each; the deferred film is the last candidate.
    for _ in range(10):
        s = _order(ctx)
        if s["pair"]["candidate"]["film_id"] == ctx["last_candidate"]:
            break
        order_verdict(repo, SRC, s["pair"]["candidate"]["film_id"], s["pair"]["other"]["film_id"], "better", TODAY)
    assert _order(ctx)["pair"]["candidate"]["film_id"] == ctx["last_candidate"]
    assert _order(ctx)["remaining"] == 1


@when("I undo")
def do_undo(ctx):
    undo(ctx["repo"], SRC, TODAY)


@then(parsers.parse("{n:d} film is ordered and the same candidate is asked with {v:d} verdicts"))
def same_candidate(ctx, n, v):
    s = _order(ctx)
    assert s["ordered"] == n and s["pair"]["candidate"]["film_id"] == ctx["last_candidate"]
    assert len(s["pair"]["asked"]) == v


@then("nothing is deferred in order mode")
def nothing_deferred(ctx):
    assert ctx["repo"].order_deferrals(_sid(ctx)) == {}


@then(parsers.parse("undoing again is refused with {status:d}"))
def undo_refused(ctx, status):
    with pytest.raises(RankError) as e:
        undo(ctx["repo"], SRC, TODAY)
    assert e.value.status == status


@when(parsers.parse("I answer {verdicts} in tiering mode"))
def answer_tiering(ctx, verdicts):
    for v in [x.strip() for x in verdicts.split(",")]:
        s = session_state(ctx["repo"], SRC, TODAY)
        ctx["tiering_candidate"] = s["pair"]["candidate"]["film_id"]
        record_verdict(ctx["repo"], SRC, s["pair"]["candidate"]["film_id"], s["pair"]["tier"], v, TODAY)


@then("the tiering candidate is unplaced again")
def tiering_unplaced(ctx):
    assert ctx["tiering_candidate"] not in ctx["repo"].rank_placements(_sid(ctx))


@when(parsers.parse("the film at position {p:d} is marked unseen from the drawer"))
def unseen_at_position(ctx, p):
    fid = ctx["repo"].rank_order(_sid(ctx), ORDER_TIER)[p - 1]
    ctx["repo"].set_unseen(fid, True, TODAY)


@then(parsers.parse("the current candidate has {n:d} verdicts"))
def candidate_verdicts(ctx, n):
    s = _order(ctx)
    assert len(s["pair"]["asked"]) == n


@when(parsers.parse('I save the list as "{name}"'))
def save(ctx, name):
    ctx["lists_dir"].mkdir(exist_ok=True)
    save_list(ctx["repo"], SRC, name, TODAY, ctx["lists_dir"])


@then(parsers.parse('the list "{slug}" has {n:d} entries'))
def list_has(ctx, slug, n):
    assert len(ctx["repo"].list_entries(slug)) == n


@then(parsers.parse("entries {a:d} and {b:d} carry no label"))
def entries_bare(ctx, a, b):
    rows = ctx["repo"].list_entries("my-owned-tiers")
    assert rows[a - 1].rank_label is None and rows[b - 1].rank_label is None


@then(parsers.parse('entries {a:d} and {b:d} carry label "{label}"'))
def entries_tied(ctx, a, b, label):
    rows = ctx["repo"].list_entries("my-owned-tiers")
    assert rows[a - 1].rank_label == label and rows[b - 1].rank_label == label


@then(parsers.parse('entry {n:d} is "{title}" with no label'))
def entry_is(ctx, n, title):
    row = ctx["repo"].list_entries("my-owned-tiers")[n - 1]
    assert row.film_id == _id(ctx, title) and row.rank_label is None


@given("the session is finished")
def finish(ctx):
    with ctx["repo"]._conn() as c:
        c.execute("UPDATE rank_session SET finished_on = ? WHERE id = ?", (TODAY.isoformat(), _sid(ctx)))


@then(parsers.parse("reading the order state is refused with {status:d}"))
def order_refused(ctx, status):
    with pytest.raises(RankError) as e:
        order_state(ctx["repo"], SRC, TODAY)
    assert e.value.status == status
```

Fixture arithmetic, so nobody has to rediscover it: four 10s (Alpha, Beta, Gamma, Delta) seed tier 1; the proposal picks one of them as the tier 1 anchor (an anchor is still a tier 1 placement, so it is in the order queue like the others). On the first `order_state` the queue's head is inserted at position 1 without a click (O7), leaving 3. "Uno" is the only unrated film, so it is the tiering's sole candidate; two `better`s land it in tier 1 (`better, better` → Place(1)). The save scenario: after one `worse` the order holds 2 films (the free first + one appended), 2 tier 1 films unordered → 8 entries: lines 1–2 bare, 3–4 `=3`, then Nine (tier 2, alone → bare), Eight, Seven, Four.

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/step_defs/test_rank_order.py -q`
Expected: FAIL with `ImportError: cannot import name 'ORDER_TIER'`.

- [ ] **Step 4: Implement the use case**

In `src/movie_brain/application/rank.py`:

Extend the `movie_brain.domain.rank` import with `Insert, order_step`. Add after `RankError`:

```python
ORDER_TIER = 1  # the one tier the order mode exposes (order spec O9)
```

Add after `session_state`:

```python
def _order_queue(repo: Repository, s: RankSession) -> list[int]:
    """Order spec §4.2: the session's tier 1 placements not yet ordered, mid-insertion films
    first, then the seeded shuffle, order-mode deferrals last. Derived per request."""
    placed = repo.rank_placements(s.id)
    ordered = set(repo.rank_order(s.id, ORDER_TIER))
    unseen = repo.unseen_film_ids()
    disposed = repo.disposed_film_ids()
    ids = [
        fid
        for fid, (tier, _) in placed.items()
        if tier == ORDER_TIER and fid not in ordered and fid not in unseen and fid not in disposed
    ]
    deferred = repo.order_deferrals(s.id)
    queue = order_queue(s.seed, ids, deferred)
    in_progress = repo.films_with_order_verdicts(s.id)
    lead = [i for i in queue if i in in_progress and i not in deferred]
    return lead + [i for i in queue if i not in lead]


def order_state(repo: Repository, source: str, today: date) -> dict[str, object]:
    s = _session(repo, source)
    order = repo.rank_order(s.id, ORDER_TIER)
    queue = _order_queue(repo, s)
    pair: dict[str, object] | None = None
    corrupt: list[int] = []
    while queue:
        cand = queue[0]
        verdicts = repo.order_verdicts_for(s.id, cand)
        try:
            step = order_step(order, verdicts)
        except ValueError:
            corrupt.append(cand)  # never a 500: skipped, nothing written (order spec §4.1)
            queue = queue[1:]
            continue
        if isinstance(step, Insert):
            # O7 (an empty order takes its first film with no click) and the self-heal for a
            # crash between the last append and the insert both land here.
            repo.insert_ordered(s.id, ORDER_TIER, cand, step.slot, today)
            order = repo.rank_order(s.id, ORDER_TIER)
            queue = queue[1:]
            continue
        pair = {
            "candidate": _film(repo, cand),
            "other": _film(repo, step.film_id),
            "position": order.index(step.film_id) + 1,
            "of": len(order),
            "asked": [[other, v] for other, v in verdicts],
        }
        break
    return {
        "tier": ORDER_TIER,
        "ordered": len(order),
        "remaining": len(queue),
        "pair": pair,
        "done": not queue,
        "can_undo": s.last_action is not None,
        "corrupt": corrupt,
    }


def _current_order_pair(repo: Repository, source: str, today: date) -> tuple[RankSession, dict[str, object]]:
    s = _session(repo, source)
    pair = order_state(repo, source, today)["pair"]
    if not isinstance(pair, dict):
        raise RankError(409, "no current pair")
    return s, pair


def order_verdict(
    repo: Repository, source: str, film_id: int, other_film_id: int, verdict: str, today: date
) -> dict[str, object]:
    if verdict not in VERDICTS:
        raise RankError(400, f"verdict must be one of {', '.join(VERDICTS)}")
    s, pair = _current_order_pair(repo, source, today)
    cand, other = pair["candidate"], pair["other"]
    assert isinstance(cand, dict) and isinstance(other, dict)
    if cand["film_id"] != film_id or other["film_id"] != other_film_id:
        raise RankError(409, "that pair is no longer current")
    cid = repo.append_order_comparison(s.id, ORDER_TIER, film_id, other_film_id, verdict, today)
    step = order_step(repo.rank_order(s.id, ORDER_TIER), repo.order_verdicts_for(s.id, film_id))
    inserted = isinstance(step, Insert)
    if isinstance(step, Insert):
        repo.insert_ordered(s.id, ORDER_TIER, film_id, step.slot, today)
    repo.set_last_action(
        s.id,
        {"mode": "order", "kind": "order_verdict", "film_id": film_id, "comparison_id": cid, "inserted": inserted},
    )
    return order_state(repo, source, today)


def order_pass(repo: Repository, source: str, film_id: int, today: date) -> dict[str, object]:
    s, pair = _current_order_pair(repo, source, today)
    cand = pair["candidate"]
    assert isinstance(cand, dict)
    if cand["film_id"] != film_id:
        raise RankError(409, "that candidate is no longer current")
    repo.defer_order_film(s.id, film_id, today.isoformat())
    repo.set_last_action(s.id, {"mode": "order", "kind": "order_defer", "film_id": film_id})
    return order_state(repo, source, today)
```

In `undo`, add two branches before `repo.set_last_action(s.id, None)` and make the return mode-aware:

```python
    elif kind == "order_verdict":
        comparison_id = action["comparison_id"]
        assert isinstance(comparison_id, int)
        repo.delete_order_comparison(comparison_id)
        if action.get("inserted"):
            repo.remove_ordered(fid, s.id)   # the film leads the order queue again with one verdict fewer
    elif kind == "order_defer":
        repo.undefer_order_film(s.id, fid)
    repo.set_last_action(s.id, None)
    if action.get("mode") == "order":
        return order_state(repo, source, today)
    return session_state(repo, source, today)
```

Also stamp the tiering's own actions with their mode so the record is symmetrical: in `record_verdict` and both `set_last_action` calls of `pass_film`, add `"mode": "tiers"` to the dict (the tiering's `undo` branches key on `kind`, so nothing else changes).

In `save_list`, replace the `entries = tiered_entries(...)` call with:

```python
    order = {fid: pos for pos, fid in enumerate(repo.rank_order(s.id, ORDER_TIER), start=1)}
    entries = tiered_entries(
        (Placed(fid, tier, facts[fid][0], facts[fid][2]) for fid, (tier, _) in placed.items() if fid in facts),
        order,
    )
```

- [ ] **Step 5: Run the scenarios**

Run: `uv run pytest tests/step_defs/test_rank_order.py tests/step_defs/test_rank.py -q`
Expected: all pass. If "Answering worse every time appends each film" fails on position, check `insert_ordered`'s `position > slot` filter against the domain's 0-based slot: slot k (append) shifts nothing.

- [ ] **Step 6: Full gate and commit**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy`

```bash
git add src/movie_brain/application/rank.py tests/features/rank_order.feature tests/step_defs/test_rank_order.py
git commit -m "order mode: the pair, the verdict, the pass and the save derive tier 1's order from the log and share the session's one undo slot"
```

---

### Task 5: The API routes

**Files:**
- Modify: `src/movie_brain/web/app.py` (after `rank_save`)
- Test: `tests/web/test_api.py` (append, using the existing `rank_client` fixture and `_start`)

**Interfaces:**
- Consumes: Task 4's `order_state`, `order_verdict`, `order_pass`.
- Produces: `GET /api/rank/order`, `POST /api/rank/order/verdict`, `POST /api/rank/order/pass`.

- [ ] **Step 1: Write the failing route tests**

```python
def test_rank_order_needs_a_session_then_serves_the_first_pair_after_a_tier_1_placement(rank_client):
    client, ids = rank_client
    assert client.get("/api/rank/order").status_code == 404
    state = _start(client)
    # Seeds put one film (Ten) in tier 1: ordered free at position 1, nothing to ask.
    o = client.get("/api/rank/order").get_json()
    assert (o["tier"], o["ordered"], o["remaining"], o["done"], o["pair"]) == (1, 1, 0, True, None)
    cand = state["pair"]["candidate"]["film_id"]
    client.post("/api/rank/verdict", json={"film_id": cand, "anchor_tier": 3, "verdict": "better"})
    client.post("/api/rank/verdict", json={"film_id": cand, "anchor_tier": 2, "verdict": "better"})
    o = client.get("/api/rank/order").get_json()
    assert o["pair"]["candidate"]["film_id"] == cand and o["pair"]["other"]["film_id"] == ids["Ten"]
    assert (o["pair"]["position"], o["pair"]["of"], o["remaining"]) == (1, 1, 1)


def test_rank_order_verdict_inserts_refuses_stale_and_undo_returns_order_state(rank_client):
    client, ids = rank_client
    state = _start(client)
    cand = state["pair"]["candidate"]["film_id"]
    client.post("/api/rank/verdict", json={"film_id": cand, "anchor_tier": 3, "verdict": "better"})
    client.post("/api/rank/verdict", json={"film_id": cand, "anchor_tier": 2, "verdict": "better"})
    r = client.post("/api/rank/order/verdict", json={"film_id": cand, "other_film_id": ids["Nine"], "verdict": "better"})
    assert r.status_code == 409
    r = client.post("/api/rank/order/verdict", json={"film_id": cand, "other_film_id": ids["Ten"], "verdict": "same"})
    assert r.status_code == 400
    r = client.post("/api/rank/order/verdict", json={"film_id": "x"})
    assert r.status_code == 400
    r = client.post("/api/rank/order/verdict", json={"film_id": cand, "other_film_id": ids["Ten"], "verdict": "better"})
    body = r.get_json()
    assert r.status_code == 200 and body["ordered"] == 2 and body["done"] is True and body["can_undo"] is True
    r = client.post("/api/rank/undo")
    body = r.get_json()
    assert r.status_code == 200 and body["ordered"] == 1 and body["pair"]["candidate"]["film_id"] == cand


def test_rank_order_pass_defers_and_checks_its_shape(rank_client):
    client, ids = rank_client
    state = _start(client)
    cand = state["pair"]["candidate"]["film_id"]
    client.post("/api/rank/verdict", json={"film_id": cand, "anchor_tier": 3, "verdict": "better"})
    client.post("/api/rank/verdict", json={"film_id": cand, "anchor_tier": 2, "verdict": "better"})
    assert client.post("/api/rank/order/pass", json={"nope": 1}).status_code == 400
    assert client.post("/api/rank/order/pass", json={"film_id": ids["Ten"]}).status_code == 409
    r = client.post("/api/rank/order/pass", json={"film_id": cand})
    # The deferred film is the only one left, so it comes straight back — but it IS deferred.
    assert r.status_code == 200 and r.get_json()["pair"]["candidate"]["film_id"] == cand
    assert r.get_json()["can_undo"] is True
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/web/test_api.py -q -k rank_order`
Expected: FAIL with 404 on `/api/rank/order/verdict` (route missing) after the first assertion passes trivially.

- [ ] **Step 3: Add the routes**

In `create_app`, after `rank_save`:

```python
    @app.get("/api/rank/order")
    def rank_order_state() -> Response:
        return jsonify(ranker.order_state(repo, RANK_SOURCE, today()))

    @app.post("/api/rank/order/verdict")
    def rank_order_verdict() -> Response:
        body = _json_object()
        film_id, other_film_id = body.get("film_id"), body.get("other_film_id")
        if not isinstance(film_id, int) or not isinstance(other_film_id, int):
            raise RankError(
                400, 'body must be JSON {"film_id": int, "other_film_id": int, "verdict": "better"|"worse"}'
            )
        return jsonify(
            ranker.order_verdict(repo, RANK_SOURCE, film_id, other_film_id, str(body.get("verdict")), today())
        )

    @app.post("/api/rank/order/pass")
    def rank_order_pass() -> Response:
        body = _json_object()
        film_id = body.get("film_id")
        if not isinstance(film_id, int):
            raise RankError(400, 'body must be JSON {"film_id": int}')
        return jsonify(ranker.order_pass(repo, RANK_SOURCE, film_id, today()))
```

- [ ] **Step 4: Run the route tests**

Run: `uv run pytest tests/web/test_api.py -q -k rank`
Expected: pass.

- [ ] **Step 5: Full gate and commit**

```bash
git add src/movie_brain/web/app.py tests/web/test_api.py
git commit -m "three order routes beside the tiering's, same body check, same 404 for a missing session"
```

---

### Task 6: The page — tabs and order mode

**Files:**
- Modify: `src/movie_brain/web/templates/rank.html`, `src/movie_brain/web/static/rank.js`, `src/movie_brain/web/static/rank.css`
- Test: `tests/web/test_rank_page.py` (extend the end of `test_rank_flow`)

**Interfaces:**
- Consumes: Task 5's routes. `GET /api/rank/order` → `{tier, ordered, remaining, pair: {candidate, other, position, of, asked} | null, done, can_undo}`.

- [ ] **Step 1: Extend the Playwright flow**

At the end of `test_rank_flow` (after the picker assertion), append:

```python
    # --- Order tier 1 ------------------------------------------------------------------
    # Tier 1 holds Ten (seed) and `first` (placed above). Switching tabs orders the queue's
    # head for free (O7) and asks the other film against it: "Position 1 of 1".
    page.goto(rank_server + "/rank")
    page.click('.tab[data-mode="order"]')
    page.wait_for_selector('#rank[data-state="order"]')
    assert page.url.endswith("#order")
    expect(page.locator(".side.anchor .heading")).to_have_text("Position 1 of 1")
    expect(page.locator("#ordered")).to_have_text("1")
    expect(page.locator("#order-remaining")).to_have_text("1")
    expect(page.locator(".side button.unseen")).to_have_count(0)   # no Have-not-seen in order mode
    top = page.locator(".side.candidate .title").inner_text()
    page.keyboard.press("1")   # inert here
    expect(page.locator(".side.candidate .title")).to_have_text(top)
    page.keyboard.press("ArrowLeft")   # candidate better → slot 0
    page.wait_for_selector('#rank[data-state="order_done"]')
    expect(page.locator("#ordered")).to_have_text("2")
    page.keyboard.press("u")
    page.wait_for_selector('#rank[data-state="order"]')
    expect(page.locator(".side.candidate .title")).to_have_text(top)
    page.keyboard.press("ArrowLeft")
    page.wait_for_selector('#rank[data-state="order_done"]')
    page.reload()
    page.wait_for_selector('#rank[data-state="order_done"]')   # the hash keeps the mode
    page.click("#save")
    expect(page.locator("#note")).to_contain_text("saved")
    page.goto(rank_server + "/")
    page.wait_for_selector("#films tbody[data-count]")
    value = page.locator("#list-picker option", has_text="Mine (").get_attribute("value")
    page.select_option("#list-picker", value)
    expect(page.locator("#films tbody tr[data-id]").first).to_contain_text(top)   # bare rank 1 sorts first
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/web/test_rank_page.py -q`
Expected: FAIL at `page.click('.tab[data-mode="order"]')` (no such element).

- [ ] **Step 3: Template**

In `rank.html`, replace the `<header class="top">` block with:

```html
  <header class="top">
    <h1><a href="/">movie-brain</a> · rank</h1>
    <nav class="tabs" aria-label="Mode">
      <button class="tab" data-mode="tiers">Tiers</button>
      <button class="tab" data-mode="order">Order tier 1</button>
    </nav>
    <div id="note" class="note" aria-live="polite"></div>
    <div id="progress" hidden>
      <span class="tiers-only"><b id="placed">–</b> placed</span>
      <span class="tiers-only"><b id="remaining">–</b> remaining</span>
      <span class="tiers-only"><b id="unseen-count">–</b> unseen</span>
      <span class="tally tiers-only"><span data-tier="1">–</span><span data-tier="2">–</span><span data-tier="3">–</span><span data-tier="4">–</span><span data-tier="5">–</span></span>
      <span class="order-only"><b id="ordered">–</b> ordered</span>
      <span class="order-only"><b id="order-remaining">–</b> remaining</span>
      <button id="undo" class="chip" title="Undo the last click (U)">Undo</button>
      <span class="save-row"><input id="list-name" placeholder="My owned films, tiered"><button id="save" class="chip">Save as list</button></span>
    </div>
  </header>
```

and add two sections inside `<main id="rank">` after `#done`:

```html
    <section id="order-empty" hidden><p>Start a tiering session first — the order lives inside it.</p></section>
    <section id="order-done" hidden><p>Every tier 1 film is ordered. Save the list above.</p></section>
```

- [ ] **Step 4: Stylesheet**

Append to `rank.css`:

```css
.tabs { display:flex; gap:6px; margin:2px 0 6px; }
.tab { border:1px solid var(--line); background:var(--chip); border-radius:6px; padding:3px 10px; cursor:pointer; font:inherit; }
.tab[aria-current="true"] { background:var(--chip-on); color:#fff; border-color:var(--chip-on); }
```

- [ ] **Step 5: Script**

In `rank.js`, make these edits (each is a small, located change):

1. State and mode helper — replace `const state = { session: null, details: {} };` with:

```js
  const state = { session: null, order: null, details: {} };
  // Two modes on one page (order spec O3): the hash carries the mode so a reload stays put.
  const mode = () => (location.hash === '#order' ? 'order' : 'tiers');
  const setMode = (m) => { if (mode() !== m) location.hash = m === 'order' ? '#order' : ''; };
```

2. `show` — replace with:

```js
  const show = (which) => {
    for (const id of ['setup', 'pair', 'done', 'order-empty', 'order-done']) $('#' + id).hidden = id !== which;
    $('#progress').hidden = !state.session || !state.session.session;
    for (const el of document.querySelectorAll('.tiers-only')) el.hidden = mode() !== 'tiers';
    for (const el of document.querySelectorAll('.order-only')) el.hidden = mode() !== 'order';
    for (const t of document.querySelectorAll('.tab')) t.setAttribute('aria-current', String(t.dataset.mode === mode()));
  };
```

3. `sideHtml` — change the signature to `(side, d, heading, opts = { unseen: true })` and build the buttons and title from the flag:

```js
    const unseenBtn = opts.unseen ? `<button class="chip unseen" data-side="${side}" title="${side === 'candidate' ? '1' : '2'}">Have not seen</button>` : '';
    const titleHtml = opts.unseen ? `<button class="title-unseen" data-side="${side}">${esc(d.title)}</button>` : esc(d.title);
    return `<div class="heading">${esc(heading)}</div>
      <div class="buttons"><button class="chip primary better" data-side="${side}" title="${side === 'candidate' ? '←' : '→'}">Better</button>${unseenBtn}</div>
      ${poster}
      <div class="title">${titleHtml}</div>
      <div class="meta">${esc(dirYear)}</div>
      <dl class="prompt">${prompts}</dl>`;
```

4. After `renderPair`, add:

```js
  const renderOrderPair = async () => {
    const p = state.order.pair;
    const [c, o] = await Promise.all([detail(p.candidate.film_id), detail(p.other.film_id)]);
    $('.side.candidate').innerHTML = sideHtml('candidate', c, 'Candidate', { unseen: false });
    $('.side.anchor').innerHTML = sideHtml('anchor', o, `Position ${p.position} of ${p.of}`, { unseen: false });
    show('pair');
    main.dataset.state = 'order';
  };
```

5. `renderProgress` — after the tally loop, add:

```js
    if (state.order) { $('#ordered').textContent = state.order.ordered; $('#order-remaining').textContent = state.order.remaining; }
    $('#undo').disabled = !(mode() === 'order' && state.order ? state.order.can_undo : s.can_undo);
```

(and delete the existing `$('#undo').disabled = !s.can_undo;` line).

6. `refresh` — replace with:

```js
  const refresh = async () => {
    state.session = await api('GET', '/api/rank/session');
    state.order = null;
    const s = state.session;
    if (mode() === 'order') {
      if (!s.session) { show('order-empty'); main.dataset.state = 'order_nosession'; return; }
      state.order = await api('GET', '/api/rank/order');
      renderProgress();
      if (state.order.done) { show('order-done'); main.dataset.state = 'order_done'; return; }
      return renderOrderPair();
    }
    renderProgress();
    if (!s.session) return renderSetup([1, 2, 3, 4, 5], 'Confirm or swap the five anchors, then start.');
    if (s.needs_anchor.length) return renderSetup(s.needs_anchor, 'That anchor is out. Pick a replacement for the tier.');
    if (s.done) { show('done'); main.dataset.state = 'done'; return; }
    return renderPair();
  };
```

7. `verdict`, `pass`, `unseen` — make them mode-aware:

```js
  const verdict = async (side) => {
    if (mode() === 'order') {
      const o = state.order; if (!o || !o.pair) return;
      await api('POST', '/api/rank/order/verdict', { film_id: o.pair.candidate.film_id, other_film_id: o.pair.other.film_id, verdict: side === 'candidate' ? 'better' : 'worse' });
      return refresh();
    }
    const s = state.session; if (!s || !s.pair) return;
    await api('POST', '/api/rank/verdict', { film_id: s.pair.candidate.film_id, anchor_tier: s.pair.tier, verdict: side === 'candidate' ? 'better' : 'worse' });
    await refresh();
  };
  const pass = async (unseen = {}) => {
    if (mode() === 'order') {
      const o = state.order; if (!o || !o.pair) return;
      await api('POST', '/api/rank/order/pass', { film_id: o.pair.candidate.film_id });
      return refresh();
    }
    const s = state.session; if (!s || !s.pair) return;
    await api('POST', '/api/rank/pass', { film_id: s.pair.candidate.film_id, candidate_unseen: unseen.candidate === true, anchor_unseen: unseen.anchor === true });
    await refresh();
  };
  const unseen = (side) => (mode() === 'order' ? Promise.resolve() : pass({ [side]: true }));   // O6: inert in order mode
```

8. Tabs and hash — add before the `keydown` listener:

```js
  for (const t of document.querySelectorAll('.tab')) t.addEventListener('click', () => setMode(t.dataset.mode));
  window.addEventListener('hashchange', () => enqueue(refresh));
```

9. `keydown` guard — change `main.dataset.state !== 'pair'` to `!['pair', 'order'].includes(main.dataset.state)`.

- [ ] **Step 6: Run the Playwright test, then the whole suite**

Run: `uv run pytest tests/web/test_rank_page.py -q`
Expected: pass. Then `uv run pytest -q && uv run ruff check . && uv run mypy` — green.

- [ ] **Step 7: Commit**

```bash
git add src/movie_brain/web/templates/rank.html src/movie_brain/web/static/rank.js src/movie_brain/web/static/rank.css tests/web/test_rank_page.py
git commit -m "Order tier 1 is a tab on the rank page: same pair, same keys, the hash keeps the mode across a reload"
```

---

### Task 7: Documentation

**Files:**
- Modify: `CLAUDE.md` (the **Tier ranker** bullet), `docs/backlog.md` (item 16), `docs/superpowers/specs/2026-09-13-order-top-tier-design.md` (§6 status line and the 404 concretisation)

- [ ] **Step 1: CLAUDE.md** — append to the end of the Tier ranker bullet (one paragraph, no hard wraps):

> **Order tier 1** (spec `docs/superpowers/specs/2026-09-13-order-top-tier-design.md`, migration 023): a second tab on `/rank` (hash `#order`) strict-orders the LIVE session's tier 1 by binary insertion — `domain/rank.py::order_step(order, verdicts)` derives the slot bounds from the candidate's logged `(other_film_id, verdict)` pairs on every read, never from stored lo/hi (`better` caps the slot at that film's index, `worse` floors it at index + 1; a crossed bound is a corrupt log, raised in the domain and reported as `corrupt` by the use case, never a 500). Tables `rank_order` (dense 1..k positions per session + tier, shifted one row at a time because of the UNIQUE), `rank_order_comparison` (append-only, the search's only state) and `rank_order_deferral` (order-mode Pass, separate from the tiering's). `ORDER_TIER = 1` in `application/rank.py` is the only tier exposed. The first film into an empty order is inserted with no click on the next read. `set_unseen` and `merge_film` purge a departing film from the order AND every verdict naming it on either side (`_purge_order_rows`), which is what keeps derived bounds consistent. One undo slot for the page: `last_action` carries `mode`. Save writes tier 1's ordered films as bare lines 1..k, the unordered rest tied at `=k+1` (a lone one bare), tiers 2–5 unchanged. No `Have not seen` in order mode; `1`/`2` are inert there. Routes `GET /api/rank/order`, `POST /api/rank/order/verdict`, `POST /api/rank/order/pass`; a missing session is 404 like every other rank route.

- [ ] **Step 2: backlog** — tick item 16 and append: "— shipped 2026-09-13 (order spec + migration 023); the click count actually spent is recorded in `tier-ranker-done` memory once the owner finishes."

- [ ] **Step 3: spec** — change `**Status:** approved design, awaiting plan` to `**Status:** implemented 2026-09-13 (plan docs/superpowers/plans/2026-09-13-order-top-tier.md)`, and in §6 change `GET /api/rank/order` … `409 with no open session` to `404 with no open session, through the same helper every other rank route uses`.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md docs/backlog.md docs/superpowers/specs/2026-09-13-order-top-tier-design.md
git commit -m "docs: the tier order's contract where the next session will look for it"
```

---

### Task 8: Apply live and hand off

**Files:** none in the repo (live DB only). The owner's live session is open with 93 films in tier 1 (2026-09-13 evening).

- [ ] **Step 1: Migrate the live DB** — `uv run movie-brain migrate` (dry run, expect `023_order_top_tier.sql` pending), then `uv run movie-brain migrate --apply` (a backup lands in `<config_dir>/backups/`).
- [ ] **Step 2: Smoke** — `uv run movie-brain dashboard`, open `http://127.0.0.1:5556/rank#order`, confirm: the progress line reads `1 ordered · 92 remaining` (the free first insertion), the right column is headed `Position 1 of 1`, `1`/`2` do nothing, `←` inserts and the next pair appears, `U` brings the pair back, the Tiers tab still serves the tiering pair with its own counts, and Save then the dashboard's picker shows the list with bare ranks for the ordered films.
- [ ] **Step 3: Report** the first pair to the owner; the owner runs the ordering themselves. Then merge the branch to main (`superpowers:finishing-a-development-branch`), push, and update memory `tier-ranker-done` with: migration 023 applied live, never re-run; the order mode is live; click count pending.
