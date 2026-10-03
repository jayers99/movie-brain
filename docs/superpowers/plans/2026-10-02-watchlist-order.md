# Watchlist Order Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The watchlist gets a saved hand order the owner nudges one place at a time — ▲ ▼ in the row, or ↑ ↓ on the marked film — and the row click becomes three-state (open → close keeping the mark → let go).

**Architecture:** Migration 033 adds `watchlist.position` (dense 1…n, seeded in today's default order). The repository owns every position write (star at the top, a put-back above a remembered neighbour, un-star closes the gap, a move re-inserts past one visible neighbour, a merge never leaves a hole); the API exposes them; `FilmView.watchlist_position` carries the order to `app.js`, whose `compare()` leads with it whenever the Watchlist chip is on and nothing else owns the order. Moves are optimistic in the browser and re-read from the server on failure.

**Tech Stack:** Python 3 / SQLite (migrations in `migrations/NNN_*.sql`), Flask (`web/app.py`), vanilla JS (`web/static/app.js`), pytest + Playwright (`tests/web/`).

**Spec:** `docs/superpowers/briefs/2026-10-02-watchlist-order/brief.md` (amendment 1.1, frozen) — read it first; the stories there are the acceptance tests. The mock-up `mockup-1.html` beside it shows the intended behaviour; where they disagree the brief wins.

## Global Constraints

- Watchlist only. `rank_order` / `my-owned-tiers` (My Ranking) are NOT touched (brief ruling 1).
- A fresh star inserts at position 1 (ruling 2). A put-back (re-star within one drawer visit, or the move-on line's Undo) inserts ABOVE the film it sat above, anchored to that neighbour, not to an index (stories 7, 14).
- Migration seed = today's default order: `COALESCE(scraped metacritic, omdb.metacritic)` desc, then `omdb.rt` desc, then `omdb.imdb` desc, missing after present, then title (case-insensitive), then film id (ruling 3).
- A move re-inserts the film just past ONE visible neighbour; every other film keeps its relative order (story 4). Never a swap.
- Hand order shows when: Watchlist chip on AND no column sort AND no picked list AND no RANKED search (`state.search.rank` null). It leads ahead of On a list's canon score and Watched's last-watched (story 5, story 16).
- Arrows (▲ ▼) appear only in hand order; while the drawer is open they are hidden (visibility), the column keeps its width so nothing under the dim shifts.
- Keys: plain ↑ ↓ (no modifier), drawer closed, hand order, the marked film in the shown list, focus NOT in input/select/textarea → move the marked film; otherwise today's behaviour. Drawer open → ↑ ↓ step the drawer, unchanged (ruling 6, stories 9, 10, 20).
- A ▲ ▼ press sets `state.mark` to that film (story 10).
- Three-state row click, dashboard-wide: drawer closed, click on the row carrying `state.mark` (not on ⓘ, not on a link or input) → `state.mark = null`; ⓘ always opens (ruling 7, story 11).
- Failure toast text: `Could not save the order` (story 15).
- Migration rules (CLAUDE.md): new `migrations/033_watchlist_position.sql`, wrapped in BEGIN/COMMIT, inserts its `schema_version` row; never edit an applied migration.
- Commits: brief single line, the "why"; end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Out-of-order responses from rapid key presses** — three fast ↑ presses fire three POSTs; an older response must never overwrite a newer optimistic order (pinned in Task 4 by `test_three_fast_presses_land_three_places`).
2. **A move whose neighbour is no longer starred** (another tab un-starred it) — the server answers 409 and the client re-reads the order instead of guessing (Task 2 `test_move_past_a_film_not_on_the_watchlist_is_409`, Task 4 failure path).
3. **A put-back whose remembered neighbour has since been un-starred** — insert falls back to the end of the list rather than raising (Task 1 `test_put_back_above_a_vanished_neighbour_goes_last`).
4. **The hidden ninth film** (starred, departed, unrated; absent from `/api/films`) — every move steps over it and it keeps its position; the client never needs to know it exists (Task 1 `test_move_steps_over_a_film_the_client_cannot_see`, Task 4 story 21).
5. **Keys while typing** — ↑ ↓ inside the rating box, a column filter or the search bar must never move a film (Task 5 story 20).

---

## File map

| File | Change |
|---|---|
| `migrations/033_watchlist_position.sql` | new: column + seed |
| `src/movie_brain/infrastructure/database.py` | `_watchlist_positions`, `toggle_watchlist` (returns a result with `below`, takes a put-back anchor), `move_watchlist`, `watchlist_order`, merge keeps positions dense, views carry `watchlist_position` |
| `src/movie_brain/domain/models.py` | `FilmView.watchlist_position: int \| None = None` |
| `src/movie_brain/web/app.py` | watchlist toggle accepts `{"restore": true, "before": id\|null}` and returns `below`; `POST /api/watchlist/move`; `GET /api/watchlist/order` |
| `src/movie_brain/web/templates/index.html` | `<col class="col-move">` + two `<th class="c-move">` |
| `src/movie_brain/web/static/app.css` | move column + buttons |
| `src/movie_brain/web/static/app.js` | `handOrderOn()`, `compare()`, move cell, press/keys/failure, three-state click, star memory |
| `tests/unit/test_watchlist_order.py` | new: repository + migration |
| `tests/web/test_api.py` | adjust the toggle round trip; new API tests |
| `tests/web/test_watchlist_order.py` | new: the 21 stories on their own seeded server |
| `.claude/rules/dashboard.md`, `docs/backlog.md`, `CLAUDE.md` | docs |

---

### Task 1: Migration 033 and the repository's position writes

**Files:**
- Create: `migrations/033_watchlist_position.sql`
- Modify: `src/movie_brain/infrastructure/database.py` (around 551 `_watchlist_ids`, 2721–2734 watchlist section, 3783–3800 merge, 4240–4310 views), `src/movie_brain/domain/models.py:429`
- Test: `tests/unit/test_watchlist_order.py`

**Interfaces:**
- Produces:
  - `Repository.toggle_watchlist(film_id: int, today: date, *, put_back: bool = False, before: int | None = None) -> WatchlistToggle | None` where `@dataclass(frozen=True) class WatchlistToggle: watchlisted: bool; below: int | None = None` (in `database.py`, next to the method). `below` is set only on an un-star: the film that sat right below it, or `None` if it was last. `put_back=True` on a star inserts directly above `before` (or last when `before` is None or no longer starred); `put_back=False` inserts at 1. Returns `None` for an unknown film.
  - `Repository.move_watchlist(film_id: int, past: int, direction: str) -> list[int] | None` — `direction` is `"up"` or `"down"`; returns the full order (film ids by position) or `None` when either film is not on the watchlist or they are the same film.
  - `Repository.watchlist_order() -> list[int]`
  - `FilmView.watchlist_position: int | None`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_watchlist_order.py
"""Backlog 46 — the watchlist's hand order (brief 2026-10-02-watchlist-order, amendment 1.1)."""
import sqlite3
from datetime import date

from movie_brain.domain.models import Film, OmdbRating
from movie_brain.infrastructure.database import Repository

TODAY = date(2026, 10, 2)


def _film(repo: Repository, title: str, mc: int | None = None, rt: int | None = None, imdb: float | None = None) -> int:
    fid = repo.create_film(Film(title, 1950, "Dir", ""))
    assert fid is not None
    repo.upsert_omdb(fid, OmdbRating(imdb, rt, True, "English", "{}", metacritic=mc), TODAY)
    return fid


def _star_all(repo: Repository, *ids: int) -> None:
    for fid in reversed(ids):          # each fresh star goes to the top, so star bottom-first
        assert repo.toggle_watchlist(fid, TODAY).watchlisted


def test_a_fresh_star_goes_to_the_top(repo):
    a, b = _film(repo, "A"), _film(repo, "B")
    repo.toggle_watchlist(a, TODAY)
    repo.toggle_watchlist(b, TODAY)
    assert repo.watchlist_order() == [b, a]


def test_an_unstar_closes_the_gap_and_names_the_film_below(repo):
    a, b, c = _film(repo, "A"), _film(repo, "B"), _film(repo, "C")
    _star_all(repo, a, b, c)
    res = repo.toggle_watchlist(b, TODAY)
    assert (res.watchlisted, res.below) == (False, c)
    assert repo.watchlist_order() == [a, c]
    assert [v.watchlist_position for v in repo.list_views("criterion", TODAY) if v.watchlisted] == [1, 2]
    assert repo.toggle_watchlist(c, TODAY).below is None   # it was last


def test_a_put_back_returns_above_its_neighbour_even_after_other_stars(repo):
    a, b, c, d = (_film(repo, t) for t in "ABCD")
    _star_all(repo, a, b, c)
    below = repo.toggle_watchlist(b, TODAY).below            # b sat above c
    repo.toggle_watchlist(d, TODAY)                          # a fresh star in between: d goes first
    repo.toggle_watchlist(b, TODAY, put_back=True, before=below)
    assert repo.watchlist_order() == [d, a, b, c]


def test_put_back_above_a_vanished_neighbour_goes_last(repo):
    a, b, c = (_film(repo, t) for t in "ABC")
    _star_all(repo, a, b, c)
    below = repo.toggle_watchlist(b, TODAY).below            # c
    repo.toggle_watchlist(c, TODAY)                          # c leaves too
    repo.toggle_watchlist(b, TODAY, put_back=True, before=below)
    assert repo.watchlist_order() == [a, b]


def test_move_steps_past_one_neighbour_and_nothing_else_changes_places(repo):
    ids = [_film(repo, t) for t in ("Henry", "OotP", "YF", "SomeCame", "LotF")]
    _star_all(repo, *ids)
    henry, ootp, yf, some, lotf = ids
    # Under a chip YF and SomeCame are hidden: OotP's visible neighbour below is LotF.
    assert repo.move_watchlist(ootp, lotf, "down") == [henry, yf, some, lotf, ootp]
    assert repo.move_watchlist(ootp, henry, "up") == [ootp, henry, yf, some, lotf]


def test_move_steps_over_a_film_the_client_cannot_see(repo):
    ids = [_film(repo, t) for t in ("YF", "SomeCame", "LotF")]
    _star_all(repo, *ids)
    yf, some, lotf = ids
    assert repo.move_watchlist(lotf, yf, "up") == [lotf, yf, some]


def test_move_refuses_a_film_off_the_watchlist(repo):
    a, b, c = (_film(repo, t) for t in "ABC")
    _star_all(repo, a, b)
    assert repo.move_watchlist(a, c, "down") is None
    assert repo.move_watchlist(c, a, "up") is None
    assert repo.move_watchlist(a, a, "up") is None
    assert repo.watchlist_order() == [a, b]


def test_merge_keeps_the_order_dense(repo):
    a, b, c = (_film(repo, t) for t in "ABC")
    _star_all(repo, a, b, c)
    d = _film(repo, "D")                       # unstarred survivor takes the loser's place
    repo.merge_film(b, d, TODAY)
    assert repo.watchlist_order() == [a, d, c]
    repo.merge_film(a, c, TODAY)               # starred survivor keeps its own place; the gap closes
    assert repo.watchlist_order() == [d, c]
    with sqlite3.connect(repo.db_path) as conn:
        assert [r[0] for r in conn.execute("SELECT position FROM watchlist ORDER BY position")] == [1, 2]


def test_migration_033_seeds_todays_default_order(tmp_path):
    db = tmp_path / "movie-brain.db"
    repo = Repository(db)
    lotf = _film(repo, "Lord of the Flies", mc=67, rt=92, imdb=6.9)
    intol = _film(repo, "Intolerance", mc=99, rt=98, imdb=7.7)
    moon = _film(repo, "Moonlight", mc=99, rt=98, imdb=7.4)
    henry = _film(repo, "The Wonderful Story of Henry Sugar", mc=85, rt=95, imdb=7.4)
    ootp = _film(repo, "Out of the Past", mc=85, rt=87, imdb=8.0)
    nomc = _film(repo, "Ugetsu", mc=None, rt=100, imdb=8.1)
    for fid in (lotf, intol, moon, henry, ootp, nomc):
        repo.toggle_watchlist(fid, TODAY)
    with sqlite3.connect(db) as conn:          # rewind to schema 32: drop the column, forget 033
        conn.execute("ALTER TABLE watchlist DROP COLUMN position")
        conn.execute("DELETE FROM schema_version WHERE version = 33")
    Repository(db, migrate=True)
    assert Repository(db).watchlist_order() == [intol, moon, henry, ootp, lotf, nomc]
```

Before writing the migration test, check the `Repository.__init__` signature (`grep -n "def __init__" -A3 src/movie_brain/infrastructure/database.py`) for the keyword that applies pending migrations (`init_db(db_path, apply=migrate)` at line 674 says it is `migrate`) and the attribute that holds the path (use it in place of `repo.db_path` if it is named differently). If the `repo` fixture in `tests/conftest.py` is not a fresh `Repository`, build one from `tmp_path` the same way.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_watchlist_order.py -q`
Expected: FAIL — `toggle_watchlist` returns a bool (`AttributeError: 'bool' object has no attribute 'watchlisted'`), `watchlist_order` / `move_watchlist` do not exist.

- [ ] **Step 3: Write the migration**

```sql
-- migrations/033_watchlist_position.sql
-- Backlog 46 (brief docs/superpowers/briefs/2026-10-02-watchlist-order/brief.md, amendment 1.1).
-- The watchlist gains the owner's hand order: a dense 1…n `position`, written only by the
-- repository (a fresh star at 1, a put-back above its remembered neighbour, an un-star closing the
-- gap, a move past one visible neighbour, a merge never leaving a hole). Seeded in the dashboard's
-- default order at the time of the migration — Metacritic (scraped over OMDb), then RT, then IMDb,
-- each descending with missing last, then title, then id — so nothing on screen moves on day one.
BEGIN;
ALTER TABLE watchlist ADD COLUMN position INTEGER;
CREATE TEMP TABLE _wl_seed AS
SELECT w.film_id,
       ROW_NUMBER() OVER (ORDER BY
           (COALESCE(mc.score, o.metacritic) IS NULL), COALESCE(mc.score, o.metacritic) DESC,
           (o.rt IS NULL), o.rt DESC,
           (o.imdb IS NULL), o.imdb DESC,
           f.title COLLATE NOCASE, f.id) AS rn
FROM watchlist w
JOIN films f ON f.id = w.film_id
LEFT JOIN omdb o ON o.film_id = f.id
LEFT JOIN (SELECT e.film_id, e.value FROM external_ids e WHERE e.authority = 'metacritic'
           AND NOT EXISTS (SELECT 1 FROM external_ids e2 WHERE e2.film_id = e.film_id AND e2.authority = 'metacritic'
             AND (e2.first_seen < e.first_seen OR (e2.first_seen = e.first_seen AND e2.value < e.value)))) x
       ON x.film_id = f.id
LEFT JOIN metacritic mc ON mc.slug = x.value;
UPDATE watchlist SET position = (SELECT rn FROM _wl_seed s WHERE s.film_id = watchlist.film_id);
DROP TABLE _wl_seed;
INSERT INTO schema_version (version) VALUES (33);
COMMIT;
```

The `LEFT JOIN (…) x` is `_MC_SLUG_SQL` (database.py:338) copied verbatim; the scraped `metacritic` table's score column is `score` (database.py:349 `COALESCE(mc.score, o.metacritic)`).

- [ ] **Step 4: Implement the repository**

Replace `_watchlist_ids` (database.py:551) with a positions map and keep a thin wrapper for any other caller:

```python
def _watchlist_positions(c: sqlite3.Connection) -> dict[int, int]:
    return {int(r["film_id"]): int(r["position"]) for r in c.execute("SELECT film_id, position FROM watchlist")}


def _watchlist_ids(c: sqlite3.Connection) -> set[int]:
    return set(_watchlist_positions(c))
```

In `list_views` and `get_view` (≈4257, ≈4301) read `wl = _watchlist_positions(c)` and pass `watchlist_position=wl.get(r["id"])` to `_row_to_view`; add the `watchlist_position: int | None = None` keyword to `_row_to_view` (≈606) and hand it to `FilmView`. In `models.py` add, under `watchlisted` (line 429):

```python
    watchlist_position: int | None = None  # the owner's hand order, 1 = top (backlog 46); None when not starred
```

Replace the watchlist section (2721–2734):

```python
    # watchlist --------------------------------------------------------
    # The hand order (backlog 46): `position` is dense 1…n and every write below keeps it so.
    def _wl_order(self, c: sqlite3.Connection) -> list[int]:
        return [int(r["film_id"]) for r in c.execute("SELECT film_id FROM watchlist ORDER BY position, film_id")]

    def _wl_write(self, c: sqlite3.Connection, order: list[int]) -> None:
        for pos, fid in enumerate(order, start=1):
            c.execute("UPDATE watchlist SET position = ? WHERE film_id = ?", (pos, fid))

    def toggle_watchlist(
        self, film_id: int, today: date, *, put_back: bool = False, before: int | None = None
    ) -> WatchlistToggle | None:
        with self._conn() as c:
            if c.execute("SELECT 1 FROM films WHERE id = ?", (film_id,)).fetchone() is None:
                return None
            order = self._wl_order(c)
            if film_id not in order:
                if put_back:
                    at = order.index(before) if before in order else len(order)
                else:
                    at = 0
                order.insert(at, film_id)
                c.execute("INSERT INTO watchlist (film_id, added_on, position) VALUES (?, ?, 0)", (film_id, today.isoformat()))
                self._wl_write(c, order)
                return WatchlistToggle(True)
            i = order.index(film_id)
            below = order[i + 1] if i + 1 < len(order) else None
            del order[i]
            c.execute("DELETE FROM watchlist WHERE film_id = ?", (film_id,))
            self._wl_write(c, order)
            return WatchlistToggle(False, below)

    def move_watchlist(self, film_id: int, past: int, direction: str) -> list[int] | None:
        """Re-insert `film_id` just past `past` — above it for "up", below it for "down". Every
        other film keeps its relative order (story 4); films the client cannot see are stepped over."""
        if film_id == past or direction not in ("up", "down"):
            return None
        with self._conn() as c:
            order = self._wl_order(c)
            if film_id not in order or past not in order:
                return None
            order.remove(film_id)
            at = order.index(past)
            order.insert(at if direction == "up" else at + 1, film_id)
            self._wl_write(c, order)
            return order

    def watchlist_order(self) -> list[int]:
        with self._conn() as c:
            return self._wl_order(c)

    def watchlist_film_ids(self) -> set[int]:
        with self._conn() as c:
            return {int(r["film_id"]) for r in c.execute("SELECT film_id FROM watchlist")}
```

Add the result type near the top-level dataclasses of `database.py` (beside `MergeReport`):

```python
@dataclass(frozen=True)
class WatchlistToggle:
    watchlisted: bool
    below: int | None = None  # on an un-star: the film that sat right below it (None = it was last)
```

In `merge_film` (≈3783), after the `_ONE_ROW_TABLES` loop and still inside the same `with self._conn() as c:`, close any hole:

```python
            # Backlog 46: a moved row keeps the loser's position, a dropped one leaves a hole —
            # renumber so the hand order stays dense 1…n.
            self._wl_write(c, self._wl_order(c))
```

Then fix every other caller of `toggle_watchlist` (`grep -rn "toggle_watchlist(" src tests`): tests that assert on its truthiness now read `.watchlisted`; seeds that only call it keep working (the return value is ignored).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_watchlist_order.py tests/unit/test_database.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add migrations/033_watchlist_position.sql src/movie_brain/infrastructure/database.py src/movie_brain/domain/models.py tests/unit/test_watchlist_order.py
git commit -m "Watchlist order: a saved hand position the repository keeps dense"
```

---

### Task 2: The API

**Files:**
- Modify: `src/movie_brain/web/app.py:108-113`
- Test: `tests/web/test_api.py:240-250` (adjust) and new tests in the same file

**Interfaces:**
- Consumes: `Repository.toggle_watchlist(...) -> WatchlistToggle | None`, `move_watchlist`, `watchlist_order` (Task 1).
- Produces:
  - `POST /api/films/<id>/watchlist` — optional JSON body `{"restore": true, "before": <id|null>}`; answers `{"watchlisted": true}` on a star, `{"watchlisted": false, "below": <id|null>}` on an un-star; 404 unknown film.
  - `POST /api/watchlist/move` — JSON `{"film_id": int, "past": int, "dir": "up"|"down"}` → 200 `{"order": [ids]}`; 409 `{"error": "not on the watchlist"}` when either film is not starred; 400 on a malformed body.
  - `GET /api/watchlist/order` → `{"order": [ids]}`.
  - `/api/films` rows carry `watchlist_position` (comes free with `FilmView`; check `asdict`/serialisation picks it up).

- [ ] **Step 1: Write the failing tests**

Replace `test_watchlist_toggle_round_trip` and add:

```python
def test_watchlist_toggle_round_trip(client):
    films = client.get("/api/films").get_json()
    fid = films[0]["id"]
    assert client.post(f"/api/films/{fid}/watchlist").get_json() == {"watchlisted": True}
    assert client.get(f"/api/films/{fid}").get_json()["watchlisted"] is True
    assert client.post(f"/api/films/{fid}/watchlist").get_json() == {"watchlisted": False, "below": None}


def test_films_carry_the_watchlist_position(client):
    a, b = (f["id"] for f in client.get("/api/films").get_json()[:2])
    client.post(f"/api/films/{a}/watchlist")
    client.post(f"/api/films/{b}/watchlist")
    pos = {f["id"]: f["watchlist_position"] for f in client.get("/api/films").get_json()}
    assert (pos[b], pos[a]) == (1, 2)


def test_move_answers_the_whole_order(client):
    a, b, c = (f["id"] for f in client.get("/api/films").get_json()[:3])
    for fid in (c, b, a):
        client.post(f"/api/films/{fid}/watchlist")
    r = client.post("/api/watchlist/move", json={"film_id": a, "past": c, "dir": "down"})
    assert r.status_code == 200 and r.get_json() == {"order": [b, c, a]}
    assert client.get("/api/watchlist/order").get_json() == {"order": [b, c, a]}


def test_move_past_a_film_not_on_the_watchlist_is_409(client):
    a, b = (f["id"] for f in client.get("/api/films").get_json()[:2])
    client.post(f"/api/films/{a}/watchlist")
    r = client.post("/api/watchlist/move", json={"film_id": a, "past": b, "dir": "up"})
    assert r.status_code == 409


def test_move_with_a_bad_body_is_400(client):
    assert client.post("/api/watchlist/move", json={"film_id": "x"}).status_code == 400
    assert client.post("/api/watchlist/move", json={"film_id": 1, "past": 2, "dir": "sideways"}).status_code == 400


def test_a_put_back_returns_above_its_neighbour(client):
    a, b, c = (f["id"] for f in client.get("/api/films").get_json()[:3])
    for fid in (c, b, a):
        client.post(f"/api/films/{fid}/watchlist")
    below = client.post(f"/api/films/{b}/watchlist").get_json()["below"]
    assert below == c
    assert client.post(f"/api/films/{b}/watchlist", json={"restore": True, "before": below}).get_json() == {"watchlisted": True}
    assert client.get("/api/watchlist/order").get_json() == {"order": [a, b, c]}
```

If the `client` fixture's seed has fewer than three films in `/api/films`, seed the extra films inside the test with `repo.create_film` the way the fixture does (`tests/web/test_api.py:12`).

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/web/test_api.py -q -k "watchlist or move or put_back"`
Expected: FAIL — `/api/watchlist/move` 404s, the un-star answer lacks `below`.

- [ ] **Step 3: Implement**

```python
    @app.post("/api/films/<int:film_id>/watchlist")
    def toggle_watchlist(film_id: int) -> tuple[Response, int]:
        body = request.get_json(silent=True) or {}
        restore = body.get("restore") is True
        before = body.get("before")
        if before is not None and not isinstance(before, int):
            return jsonify({"error": "before must be a film id or null"}), 400
        res = repo.toggle_watchlist(film_id, today(), put_back=restore, before=before)
        if res is None:
            return jsonify({"error": "no such film"}), 404
        if res.watchlisted:
            return jsonify({"watchlisted": True}), 200
        return jsonify({"watchlisted": False, "below": res.below}), 200

    # Backlog 46: the hand order. A move re-inserts the film just past ONE neighbour the client can
    # see; the answer is the whole order, so the client never has to infer hidden films' places.
    @app.post("/api/watchlist/move")
    def move_watchlist() -> tuple[Response, int]:
        body = request.get_json(silent=True) or {}
        film_id, past, direction = body.get("film_id"), body.get("past"), body.get("dir")
        if not isinstance(film_id, int) or not isinstance(past, int) or direction not in ("up", "down"):
            return jsonify({"error": "film_id, past and dir (up|down) are required"}), 400
        order = repo.move_watchlist(film_id, past, direction)
        if order is None:
            return jsonify({"error": "not on the watchlist"}), 409
        return jsonify({"order": order}), 200

    @app.get("/api/watchlist/order")
    def watchlist_order() -> tuple[Response, int]:
        return jsonify({"order": repo.watchlist_order()}), 200
```

Keep the existing 404 error body if the old route already had a specific one (read lines 108–113 first and keep its wording).

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/web/test_api.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/web/app.py tests/web/test_api.py
git commit -m "Watchlist order: move and put-back endpoints, the order in every film row"
```

---

### Task 3: Hand order on screen — the sort and the ▲ ▼ column

**Files:**
- Modify: `src/movie_brain/web/static/app.js` (`compare()` ≈92–125, `rowHtml()` ≈180–200, `renderRows()` ≈202, empty-state colspans 205/209), `src/movie_brain/web/templates/index.html:42-71`, `src/movie_brain/web/static/app.css`
- Create: `tests/web/test_watchlist_order.py` (seed + stories 1–6, 8, 12, 13, 15, 16, 17, 18, 21)

**Interfaces:**
- Consumes: `watchlist_position` on each film row; `POST /api/watchlist/move`; `GET /api/watchlist/order` (Task 2).
- Produces (later tasks call these): `handOrderOn(): boolean`; `moveFilm(id: number, dir: -1|1): void` — optimistic step past the next VISIBLE film, sets `state.mark = id`, POSTs, applies the answer, and on failure re-reads the order and toasts `Could not save the order`.

- [ ] **Step 1: Write the seed and the failing story tests**

```python
# tests/web/test_watchlist_order.py
"""Watchlist order (brief docs/superpowers/briefs/2026-10-02-watchlist-order/brief.md, amendment 1.1).

Each story test carries the brief's story number and title. They run on their OWN server seeded
with the owner's real watchlist as it stood on 2026-10-02 (same titles, same default order, same
ratings and list memberships that the stories name), plus fillers, so the brief's counts hold:
8 starred films showing, 9 in the table (Some Came Running is starred, departed and unrated).
"""
import socket
import tempfile
import threading
import time
from collections.abc import Generator
from datetime import date
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from movie_brain.domain.models import Film, ListEntry, ListMeta, OmdbRating
from movie_brain.infrastructure.database import Repository
from movie_brain.web.app import create_app

TODAY = date(2026, 10, 2)
OLD = date(2026, 9, 20)
# (title, year, director, mc, rt, imdb, my_rating, starred, lists) — the starred rows are in the
# real default order, which is also the seeded hand order.
NAMED = [
    ("Intolerance", 1916, "D.W. Griffith", 99, 98, 7.7, 2, True, 3),
    ("Moonlight", 2016, "Barry Jenkins", 99, 98, 7.4, None, True, 1),
    ("The Shop Around the Corner", 1940, "Ernst Lubitsch", 96, 99, 8.0, None, True, 0),
    ("Capturing the Friedmans", 2003, "Andrew Jarecki", 90, 97, 7.6, None, True, 1),
    ("The Wonderful Story of Henry Sugar", 2023, "Wes Anderson", 85, 95, 7.4, None, True, 0),
    ("Out of the Past", 1947, "Jacques Tourneur", 85, 87, 8.0, None, True, 6),
    ("Young Frankenstein", 1974, "Mel Brooks", 83, 95, 8.0, 9, True, 3),
    ("Lord of the Flies", 1963, "Peter Brook", 67, 92, 6.9, None, True, 0),
    ("Ugetsu", 1953, "Kenji Mizoguchi", None, 100, 8.1, None, False, 2),
]
WATCHLIST = [t[0] for t in NAMED if t[7]]
FILLERS = 20


def seed_order(repo: Repository) -> dict[str, int]:
    ids: dict[str, int] = {}
    for title, year, director, mc, rt, imdb, rating, _starred, _lists in NAMED:
        fid = repo.create_film(Film(title, year, director, ""))
        assert fid is not None
        ids[title] = fid
        repo.upsert_omdb(fid, OmdbRating(imdb, rt, True, "English", "{}", metacritic=mc), TODAY)
        if rating is not None:
            repo.set_rating(fid, rating, TODAY)
    # Some Came Running: on the Criterion Channel at the old walk, gone from today's — departed,
    # unrated, never viewed, so the catalogue hides it everywhere (story 21).
    repo.record_catalog("criterion", [Film("Some Came Running", 1958, "Vincente Minnelli", "https://c/scr")], OLD)
    repo.record_catalog("criterion", [Film("Filler Current", 1960, "Dir", "https://c/fc")], TODAY)
    scr = repo.film_id_by_key("some came running (1958)")
    assert scr is not None
    ids["Some Came Running"] = scr
    repo.upsert_omdb(scr, OmdbRating(7.2, 78, True, "English", "{}", metacritic=68), TODAY)
    for n in range(1, FILLERS + 1):
        fid = repo.create_film(Film(f"Shadow {n:02d}", 1930 + n, "Dir", ""))
        assert fid is not None
        repo.upsert_omdb(fid, OmdbRating(6.0, 50, True, "English", "{}", metacritic=10 + n), TODAY)
    # Star bottom-first so the fresh-star-at-top rule leaves the real order; the hidden film sits
    # between Young Frankenstein and Lord of the Flies, where the migration's seed put it.
    order = WATCHLIST[:7] + ["Some Came Running"] + WATCHLIST[7:]
    for title in reversed(order):
        repo.toggle_watchlist(ids[title], TODAY)
    # List memberships the stories count (On a list: 5 starred films) — one list per needed count.
    for k in range(1, 7):
        repo.upsert_film_list(ListMeta(f"l{k}", f"List {k}", None, None, None, False), TODAY)
    for title, *_rest, lists in NAMED:
        for k in range(1, lists + 1):
            rank = ids[title]
            repo.upsert_list_entry(f"l{k}", ListEntry(rank, title, "Dir"))
            repo.link_list_entry(f"l{k}", rank, ids[title])
    # My Ranking (story 12): Out of the Past 123rd, Young Frankenstein 142nd — ordered.
    repo.upsert_film_list(ListMeta("my-owned-tiers", "My Ranking", "me", 2026, None, True), TODAY)
    repo.upsert_list_entry("my-owned-tiers", ListEntry(123, "Out of the Past", "Dir"))
    repo.link_list_entry("my-owned-tiers", 123, ids["Out of the Past"])
    repo.upsert_list_entry("my-owned-tiers", ListEntry(142, "Young Frankenstein", "Dir"))
    repo.link_list_entry("my-owned-tiers", 142, ids["Young Frankenstein"])
    return ids


@pytest.fixture
def order_server() -> Generator[tuple[str, dict[str, int], Repository], None, None]:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    with tempfile.TemporaryDirectory() as tmp:
        repo = Repository(Path(tmp) / "order-movie-brain.db")
        ids = seed_order(repo)
        app = create_app(repo, today=lambda: TODAY)
        threading.Thread(target=lambda: app.run(host="127.0.0.1", port=port, use_reloader=False), daemon=True).start()
        time.sleep(0.5)
        yield f"http://127.0.0.1:{port}", ids, repo


@pytest.fixture
def dash(page: Page, order_server) -> Page:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(order_server[0] + "/?chips=watchlist")
    page.wait_for_selector("#films tbody[data-count]")
    return page


WATCHLIST_CHIP = '#chips .chip[data-chip="watchlist"]'
RATED_CHIP = '#chips .chip[data-group="rated"]'
ONLIST_CHIP = '#chips .chip[data-chip="multi_list"]'
WATCHED_CHIP = '#chips .chip[data-group="watched"]'


def titles(page: Page) -> list[str]:
    return [t.strip() for t in page.locator("#films tbody tr[data-id] td.c-title").evaluate_all("els => els.map(e => e.firstChild.textContent)")]


def row(page: Page, title: str):
    return page.locator("#films tbody tr[data-id]").filter(has=page.locator(f'td.c-title:text-is("{title}")'))


def press(page: Page, title: str, arrow: str, times: int = 1) -> None:
    for _ in range(times):
        row(page, title).locator(f"td.c-move button.{arrow}").click()


def saved(order_server) -> list[str]:
    _url, ids, repo = order_server
    names = {v: k for k, v in ids.items()}
    return [names[i] for i in repo.watchlist_order()]


def test_story_1_my_watchlist_in_my_order(dash: Page):
    expect(dash.locator("#films tbody tr[data-id]")).to_have_count(8)
    assert titles(dash) == WATCHLIST
    expect(row(dash, "Intolerance").locator("button.up")).to_be_disabled()
    expect(row(dash, "Lord of the Flies").locator("button.down")).to_be_disabled()
    expect(row(dash, "Moonlight").locator("button.up")).to_be_enabled()


def test_story_2_out_of_the_past_goes_first(dash: Page, order_server):
    press(dash, "Out of the Past", "up", 5)
    expect(dash.locator("#films tbody tr[data-id]").first).to_contain_text("Out of the Past")
    assert titles(dash)[:3] == ["Out of the Past", "Intolerance", "Moonlight"]
    expect(row(dash, "Out of the Past")).to_have_class("marked")
    dash.wait_for_timeout(300)
    assert saved(order_server)[0] == "Out of the Past"


def test_story_3_one_too_far(dash: Page, order_server):
    press(dash, "Out of the Past", "up", 6)          # one press too many is impossible: ▲ greys at the top
    press(dash, "Out of the Past", "down", 1)
    assert titles(dash)[:2] == ["Intolerance", "Out of the Past"]


def test_story_4_with_a_chip_on_it_steps_past_what_i_can_see(dash: Page, order_server):
    dash.locator(RATED_CHIP).click()                 # Unrated by me
    expect(dash.locator("#films tbody tr[data-id]")).to_have_count(6)
    press(dash, "Out of the Past", "down")
    dash.locator(RATED_CHIP).click(); dash.locator(RATED_CHIP).click()   # off
    assert titles(dash)[-4:] == ["The Wonderful Story of Henry Sugar", "Young Frankenstein", "Lord of the Flies", "Out of the Past"]
    dash.wait_for_timeout(300)
    assert saved(order_server)[-5:] == ["The Wonderful Story of Henry Sugar", "Young Frankenstein", "Some Came Running", "Lord of the Flies", "Out of the Past"]


def test_story_5_on_a_list_keeps_my_order(dash: Page):
    dash.locator(ONLIST_CHIP).click()
    assert titles(dash) == ["Intolerance", "Moonlight", "Capturing the Friedmans", "Out of the Past", "Young Frankenstein"]
    expect(dash.locator("td.c-move button.up").first).to_be_visible()


def test_story_6_a_column_sort_hides_the_arrows(dash: Page):
    mc = dash.locator('th.sortable[data-col="metacritic"]')
    mc.click()
    expect(dash.locator("td.c-move:visible")).to_have_count(0)
    mc.click(); mc.click()
    expect(dash.locator("td.c-move:visible")).to_have_count(8)
    assert titles(dash) == WATCHLIST


def test_story_8_a_new_star_goes_to_the_top(dash: Page):
    dash.locator(WATCHLIST_CHIP).click()             # off
    dash.locator("#f-title").fill("ugetsu")
    row(dash, "Ugetsu").locator(".c-year").click()
    dash.locator("#drawer .watch-toggle").click()
    expect(dash.locator("#drawer .watch-toggle")).to_have_text("★")
    dash.locator("#drawer-close").click()
    dash.locator("#f-title").fill("")
    dash.locator(WATCHLIST_CHIP).click()
    assert titles(dash)[:2] == ["Ugetsu", "Intolerance"]


def test_story_12_a_picked_list_hides_the_arrows(dash: Page):
    dash.locator("#list-picker").select_option("my-owned-tiers")
    assert titles(dash) == ["Out of the Past", "Young Frankenstein"]
    expect(dash.locator("td.c-move:visible")).to_have_count(0)
    dash.locator("#list-picker").select_option("")
    expect(dash.locator("td.c-move:visible")).to_have_count(8)


def test_story_13_a_word_search_hides_them_director_does_not(dash: Page):
    bar = dash.locator("#search")
    bar.fill("out of the past"); bar.press("Enter")
    expect(dash.locator("td.c-move:visible")).to_have_count(0)
    bar.fill(""); bar.press("Enter")
    expect(dash.locator("td.c-move:visible")).to_have_count(8)
    bar.fill("director:tourneur"); bar.press("Enter")
    expect(dash.locator("#films tbody tr[data-id]")).to_have_count(1)
    expect(row(dash, "Out of the Past").locator("button.up")).to_be_disabled()
    expect(row(dash, "Out of the Past").locator("button.down")).to_be_disabled()


def test_story_15_a_move_that_does_not_save(dash: Page):
    dash.route("**/api/watchlist/move", lambda r: r.fulfill(status=500, body="{}"))
    press(dash, "Out of the Past", "up")
    expect(dash.locator("#toast")).to_contain_text("Could not save the order")
    dash.wait_for_timeout(300)
    assert titles(dash) == WATCHLIST


def test_story_16_watched_and_watchlist_together(dash: Page):
    dash.locator(WATCHED_CHIP).click()
    expect(dash.locator("#films tbody tr.empty-state")).to_be_visible()
    dash.locator(WATCHED_CHIP).click(); dash.locator(WATCHED_CHIP).click()
    assert titles(dash) == WATCHLIST


def test_story_17_i_try_to_drag_a_row(dash: Page):
    src = row(dash, "Out of the Past").locator(".c-year")
    dst = row(dash, "Intolerance").locator(".c-year")
    src.drag_to(dst)
    if dash.locator("#drawer").is_visible():
        dash.locator("#drawer-close").click()
    assert titles(dash) == WATCHLIST


def test_story_18_straight_to_the_top(dash: Page):
    press(dash, "Lord of the Flies", "up", 7)
    assert titles(dash)[0] == "Lord of the Flies"
    expect(row(dash, "Lord of the Flies").locator("button.up")).to_be_disabled()


def test_story_21_the_starred_film_i_cannot_see(dash: Page, order_server):
    dash.locator("#f-title").fill("some")
    expect(dash.locator("#films tbody tr[data-id]")).to_have_count(0)
    dash.locator("#f-title").fill("")
    press(dash, "Lord of the Flies", "up")
    dash.wait_for_timeout(300)
    assert saved(order_server)[-3:] == ["Lord of the Flies", "Young Frankenstein", "Some Came Running"]
```

Before running, read three real selectors and fix the tests if they differ: the search bar's id (`grep -n 'id="search' src/movie_brain/web/templates/index.html`), the toast element's id (`grep -n "function toast" -A4 src/movie_brain/web/static/app.js`) and the list picker's id (`#list-picker`, index.html:36). Story 21's expected tail follows from the rule: Lord of the Flies steps past Young Frankenstein (its visible neighbour above) and lands above it, so the hidden film stays below both.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/web/test_watchlist_order.py -q`
Expected: FAIL — no `td.c-move` in any row; story 1's order may already pass (it is today's default order — that is ruling 3).

- [ ] **Step 3: Implement the markup and styles**

`index.html`: add `<col class="col-move">` FIRST in the colgroup, `<th class="c-move" aria-label="My order"></th>` first in `tr.labels`, `<th class="c-move"></th>` first in `tr.filters`.

`app.css`:

```css
/* Backlog 46: the hand-order column — present only while the list is in my order. */
col.col-move { width:64px; }
#films:not(.hand-order) col.col-move { width:0; }
#films:not(.hand-order) .c-move { display:none; }
#films.drawer-up .c-move button { visibility:hidden; }   /* the drawer covers the list: no arrows, nothing shifts */
td.c-move { padding:0 4px; text-align:center; }
td.c-move button { border:1px solid var(--line); background:var(--bg); border-radius:4px; width:22px; height:22px; padding:0; font-size:11px; line-height:20px; cursor:pointer; color:var(--fg); }
td.c-move button:hover { background:var(--chip); }
td.c-move button[disabled] { color:#cfcfcf; cursor:default; border-color:#f0f0f0; background:var(--bg); }
```

- [ ] **Step 4: Implement the sort, the cell, and the move**

In `app.js`, beside `listRank` (≈36):

```js
  // Backlog 46: the watchlist's hand order is what's shown when the Watchlist chip is on and
  // nothing else owns the order — no column sort, no picked list, no ranked word search.
  const handOrderOn = () => state.chips.has('watchlist') && !state.sort && !state.list
    && !(state.search && state.search.rank);
```

In `compare()`, inside `if (!state.sort) {`, AFTER the `state.list` block and BEFORE the `multi_list` block:

```js
      if (handOrderOn()) {  // my order leads ahead of On a list and Watched (brief stories 5, 16)
        const pa = a.watchlist_position ?? Infinity, pb = b.watchlist_position ?? Infinity;
        if (pa !== pb) return pa - pb;
      }
```

In `rowHtml(f, i)`, prepend the move cell to the returned `<tr>` (before `<td class="c-title">`):

```js
    const n = state.filtered.length;
    const move = `<td class="c-move"><button class="up" data-id="${f.id}" title="Move up one" aria-label="Move up one"${i <= 0 ? ' disabled' : ''}>▲</button> <button class="down" data-id="${f.id}" title="Move down one" aria-label="Move down one"${i >= n - 1 ? ' disabled' : ''}>▼</button></td>`;
```

and emit `${move}` as the first cell. In `renderRows()`, before writing `tbody.innerHTML`, sync the table's classes, and raise both empty-state `colspan="10"` to `colspan="11"`:

```js
    table.classList.toggle('hand-order', handOrderOn());
    table.classList.toggle('drawer-up', !drawer.hidden);
```

(`table` = the `#films` element; if no such const exists, add `const table = $('#films');` next to `tbody`.)

The move itself, after `trackOpenIndex` (≈130):

```js
  // ---- Backlog 46: moving a film in my order ----
  // Optimistic: the row moves at once (a fractional position sorts it past its neighbour), then the
  // server's whole order replaces every position. Only the newest answer counts, so fast presses
  // never land out of order; a failure re-reads the order and says so.
  let moveSeq = 0;
  function applyOrder(order) {
    const pos = new Map(order.map((id, k) => [id, k + 1]));
    for (const f of state.films) f.watchlist_position = pos.get(f.id) ?? null;
  }
  async function moveFilm(id, dir) {
    const i = state.filtered.findIndex((f) => f.id === id), j = i + dir;
    if (i < 0 || j < 0 || j >= state.filtered.length) return;
    const film = state.filtered[i], past = state.filtered[j];
    film.watchlist_position = past.watchlist_position + (dir < 0 ? -0.5 : 0.5);
    state.mark = id;
    applyFilters();
    revealRow(state.filtered.findIndex((f) => f.id === id));
    const seq = ++moveSeq;
    const r = await fetch('/api/watchlist/move', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ film_id: id, past: past.id, dir: dir < 0 ? 'up' : 'down' }) }).catch(() => null);
    if (r && r.ok) {
      const { order } = await r.json();
      if (seq === moveSeq) { applyOrder(order); applyFilters(); }
      return;
    }
    toast('Could not save the order');
    const back = await fetch('/api/watchlist/order').catch(() => null);
    if (back && back.ok && seq === moveSeq) { applyOrder((await back.json()).order); applyFilters(); }
  }
  tbody.addEventListener('click', (e) => {
    const b = e.target.closest('td.c-move button'); if (!b) return;
    e.stopPropagation();
    if (!b.disabled && drawer.hidden) moveFilm(+b.dataset.id, b.classList.contains('up') ? -1 : 1);
  }, true);
```

(Registered in the capture phase so the row's own click handler — which opens the drawer — never sees an arrow press. If `revealRow` takes an index and scrolls only when needed, this keeps the moved row in view; read its definition first.)

A star from the drawer must keep positions current: in the `.watch-toggle` handler (≈1083), after `film.watchlisted = watchlisted;`, re-read the order once (positions of every starred film shift on a star or an un-star):

```js
      const o = await fetch('/api/watchlist/order').catch(() => null);
      if (o && o.ok) applyOrder((await o.json()).order);
```

(Task 6 replaces this handler's body; keep this re-read there too.)

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest tests/web/test_watchlist_order.py -q`
Expected: PASS. Then the neighbours this touches: `uv run pytest tests/web/test_find_my_row.py tests/web/test_move_on.py tests/web/test_dashboard.py -q` — expected PASS; a failure that counts `td` cells or reads `td:first-child` is answered by updating the test to the new first column, never by moving the column.

- [ ] **Step 6: Commit**

```bash
git add src/movie_brain/web tests/web/test_watchlist_order.py
git commit -m "Watchlist order: my order leads under the Watchlist chip, one press one place"
```

---

### Task 4: The keys move the marked film

**Files:**
- Modify: `src/movie_brain/web/static/app.js` (the drawer keydown handler ≈1242)
- Test: `tests/web/test_watchlist_order.py` (stories 9, 10, 19, 20 + the Review Focus race test)

**Interfaces:**
- Consumes: `handOrderOn()`, `moveFilm(id, dir)` (Task 3), `state.mark`.

- [ ] **Step 1: Write the failing tests**

```python
def close_drawer_on_grey(page: Page) -> None:
    box = page.locator("#table-wrap").bounding_box()
    page.mouse.click(box["x"] + 30, box["y"] + box["height"] - 10)   # below the last row: no row there
    expect(page.locator("#drawer")).to_be_hidden()


def test_story_9_the_drawer_is_open_keys_step_they_do_not_move(dash: Page):
    row(dash, "Intolerance").locator(".c-year").click()
    dash.keyboard.press("ArrowDown")
    expect(dash.locator("#drawer h2")).to_contain_text("Moonlight")
    row(dash, "The Shop Around the Corner").locator(".c-year").click(force=True)
    expect(dash.locator("#drawer h2")).to_contain_text("The Shop Around the Corner")
    close_drawer_on_grey(dash)
    expect(row(dash, "The Shop Around the Corner")).to_have_class("marked")
    assert titles(dash) == WATCHLIST


def test_story_10_keys_move_the_marked_film(dash: Page):
    row(dash, "Out of the Past").locator(".c-year").click()
    dash.locator("#drawer-close").click()
    for _ in range(3):
        dash.keyboard.press("ArrowUp")
    assert titles(dash)[2] == "Out of the Past"
    expect(row(dash, "Out of the Past")).to_have_class("marked")
    press(dash, "Moonlight", "down")
    dash.keyboard.press("ArrowDown")
    assert titles(dash).index("Moonlight") == 3


def test_three_fast_presses_land_three_places(dash: Page, order_server):
    dash.route("**/api/watchlist/move", lambda r: (time.sleep(0.3), r.continue_()))
    row(dash, "Out of the Past").locator(".c-year").click()
    dash.locator("#drawer-close").click()
    for _ in range(3):
        dash.keyboard.press("ArrowUp")
    dash.wait_for_timeout(1500)
    assert titles(dash)[2] == "Out of the Past"
    assert saved(order_server)[2] == "Out of the Past"


def test_story_19_the_next_morning(dash: Page, order_server):
    press(dash, "Out of the Past", "up", 5)
    dash.wait_for_timeout(300)
    dash.reload(); dash.wait_for_selector("#films tbody[data-count]")
    assert titles(dash)[0] == "Out of the Past"
    expect(dash.locator("#films tbody tr.marked")).to_have_count(0)
    dash.keyboard.press("ArrowDown")
    assert titles(dash)[0] == "Out of the Past"


def test_story_20_typing_a_rating_rating_the_marked_film(dash: Page):
    dash.locator(RATED_CHIP).click()                      # Unrated by me
    press(dash, "Out of the Past", "up")                  # marks it (story 10's rule) and moves it
    before = titles(dash)
    box = row(dash, "Out of the Past").locator("input.rating")
    box.click(); dash.keyboard.press("ArrowUp"); dash.keyboard.press("ArrowDown")
    assert titles(dash) == before
    box.fill("8"); box.press("Enter")
    expect(row(dash, "Out of the Past")).to_have_count(0)
    dash.locator(RATED_CHIP).click(); dash.locator(RATED_CHIP).click()
    expect(row(dash, "Out of the Past")).to_have_class("marked")
    dash.locator("body").click(position={"x": 5, "y": 5})
    i = titles(dash).index("Out of the Past")
    dash.keyboard.press("ArrowUp")
    assert titles(dash).index("Out of the Past") == i - 1
```

`dash.locator("body").click(position=…)` must land on nothing that opens or filters; if the top-left corner is the page header, pick another blank point and say so in the test's comment.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/web/test_watchlist_order.py -q -k "story_9 or story_10 or story_19 or story_20 or fast"`
Expected: stories 10, 20 and the race test FAIL (↑ scrolls); 9 and 19 may already pass.

- [ ] **Step 3: Implement**

Replace the keydown handler (≈1242):

```js
  // While the drawer is open the plain arrow keys belong to stepping (so they no longer scroll the
  // drawer's own content; the wheel, Space and Page Down still do). With the drawer closed and the
  // list in my order (backlog 46), they move the marked film one place, the mark riding with it.
  // Typing and modified arrows are left alone everywhere.
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    if (e.metaKey || e.altKey || e.ctrlKey || e.shiftKey) return;
    if (e.target.matches('input, textarea, select')) return;
    const dir = e.key === 'ArrowDown' ? 1 : -1;
    if (!drawer.hidden) { e.preventDefault(); stepDrawer(dir); return; }
    if (!handOrderOn() || state.mark == null || !state.filtered.some((f) => f.id === state.mark)) return;
    e.preventDefault();
    moveFilm(state.mark, dir);
  });
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/web/test_watchlist_order.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/web/static/app.js tests/web/test_watchlist_order.py
git commit -m "Watchlist order: with the drawer closed, the arrow keys move the marked film"
```

---

### Task 5: The three-state row click and ⓘ

**Files:**
- Modify: `src/movie_brain/web/static/app.js` (tbody click ≈1052)
- Test: `tests/web/test_watchlist_order.py` (story 11), `tests/web/test_find_my_row.py` (any test that clicks a marked row to reopen it)

- [ ] **Step 1: Write the failing test**

```python
def test_story_11_click_click_click_open_close_let_go(dash: Page):
    cell = row(dash, "Out of the Past").locator(".c-year")
    cell.click()
    expect(dash.locator("#drawer")).to_be_visible()
    cell.click(force=True)                             # its own row, through the grey: closes
    expect(dash.locator("#drawer")).to_be_hidden()
    expect(row(dash, "Out of the Past")).to_have_class("marked")
    cell.click()                                       # third click: let go
    expect(dash.locator("#films tbody tr.marked")).to_have_count(0)
    expect(dash.locator("#drawer")).to_be_hidden()
    before = titles(dash)
    dash.keyboard.press("ArrowDown")
    assert titles(dash) == before
    cell.click()                                       # fourth: opens again
    expect(dash.locator("#drawer")).to_be_visible()
    dash.locator("#drawer-close").click()
    row(dash, "Out of the Past").locator("button.info").click()   # ⓘ on the marked row opens
    expect(dash.locator("#drawer")).to_be_visible()
```

If `cell.click(force=True)` on the lit row does not reach the backdrop (the lit row is `pointer-events:none`, so the click should fall through to `#drawer-backdrop`), click the backdrop at the cell's coordinates with `dash.mouse.click`.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/web/test_watchlist_order.py -q -k story_11`
Expected: FAIL at the third click (the drawer opens again).

- [ ] **Step 3: Implement**

```js
  tbody.addEventListener('click', (e) => {
    if (e.target.closest('a, input')) return;
    if (!drawer.hidden) return; // a keyboard Enter on a still-focused ⓘ would push a second history entry
    const tr = e.target.closest('tr[data-id]'); if (!tr) return;
    const id = +tr.dataset.id;
    // Backlog 46 ruling 7: a click on the marked row lets go of the mark (open → close → let go);
    // the ⓘ button always opens, marked or not.
    if (id === state.mark && !e.target.closest('button.info')) { state.mark = null; renderRows(); return; }
    revealRow(state.filtered.findIndex((f) => f.id === id)); // a half-hidden row is shown whole first
    openDrawer(id);
  });
```

Then run `uv run pytest tests/web/test_find_my_row.py -q`. A find-my-row test that clicks the marked row expecting the drawer is now asserting the old behaviour: change it to click ⓘ (or to click twice) and note "backlog 46 ruling 7" in the test's comment.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/web/test_watchlist_order.py tests/web/test_find_my_row.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/web/static/app.js tests/web
git commit -m "Row click becomes three-state so the mark can be let go; the info button always opens"
```

---

### Task 6: Stars put back within one drawer visit keep their place

**Files:**
- Modify: `src/movie_brain/web/static/app.js` (the `.watch-toggle` handler ≈1083, `hideDrawer` ≈769)
- Test: `tests/web/test_watchlist_order.py` (stories 7, 14)

**Interfaces:**
- Consumes: `POST /api/films/<id>/watchlist` with `{"restore": true, "before": id|null}` and its `below` answer (Task 2); `applyOrder` (Task 3).

- [ ] **Step 1: Write the failing tests**

```python
def test_story_7_take_one_off_change_my_mind(dash: Page, order_server):
    row(dash, "Capturing the Friedmans").locator(".c-year").click()
    dash.locator("#drawer .watch-toggle").click()
    expect(dash.locator("#drawer h2")).to_contain_text("The Wonderful Story of Henry Sugar")
    expect(dash.locator("#drawer .moved-on")).to_contain_text("Took Capturing the Friedmans off your watchlist")
    dash.locator("#drawer .moved-on button.undo").click()
    dash.wait_for_timeout(300)
    dash.locator("#drawer-close").click()
    assert titles(dash)[3] == "Capturing the Friedmans"
    assert saved(order_server)[3] == "Capturing the Friedmans"


def test_story_14_stars_off_and_on_in_one_drawer_visit(dash: Page, order_server):
    dash.locator(WATCHLIST_CHIP).click()             # off
    dash.locator("#f-title").fill("fr")
    row(dash, "Capturing the Friedmans").locator(".c-year").click()
    toggle = dash.locator("#drawer .watch-toggle")
    toggle.click(); expect(toggle).to_have_text("☆")
    dash.keyboard.press("ArrowDown"); expect(dash.locator("#drawer h2")).to_contain_text("Young Frankenstein")
    toggle.click(); expect(toggle).to_have_text("☆")
    dash.keyboard.press("ArrowUp"); expect(dash.locator("#drawer h2")).to_contain_text("Capturing the Friedmans")
    toggle.click(); expect(toggle).to_have_text("★")
    dash.keyboard.press("ArrowDown")
    toggle.click(); expect(toggle).to_have_text("★")
    dash.locator("#drawer-close").click()
    dash.locator("#f-title").fill("")
    dash.locator(WATCHLIST_CHIP).click()
    assert titles(dash)[3] == "Capturing the Friedmans" and titles(dash)[6] == "Young Frankenstein"
    # After the drawer closed, a star is fresh: off and on again in a NEW visit goes to the top.
    row(dash, "Moonlight").locator(".c-year").click()
    toggle.click()                                   # the drawer moves on (move-on); this visit remembers Moonlight
    dash.locator("#drawer-close").click()            # closing ends the visit and forgets it
    dash.locator(WATCHLIST_CHIP).click()             # off, to find Moonlight again
    dash.locator("#f-title").fill("moonlight")
    row(dash, "Moonlight").locator(".c-year").click()
    toggle.click(); expect(toggle).to_have_text("★")
    dash.locator("#drawer-close").click()
    dash.locator("#f-title").fill("")
    dash.locator(WATCHLIST_CHIP).click()
    assert titles(dash)[0] == "Moonlight"
```

The film just below Young Frankenstein in the saved order is the hidden Some Came Running; the put-back must anchor on it (the server's `below`), which is why the test asserts 7th and not 6th or 8th.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/web/test_watchlist_order.py -q -k "story_7 or story_14"`
Expected: FAIL — both films return at the top.

- [ ] **Step 3: Implement**

Next to `movedOn` (≈984) add the memory and clear it in `hideDrawer` (the one close choke point):

```js
  // Backlog 46: films un-starred during THIS drawer visit → the film each sat above. A star put
  // back before the drawer closes (however it stepped) returns there; closing forgets.
  const starMemory = new Map();
```

In `hideDrawer`, after `movedOn = null;` add `starMemory.clear();`.

Replace the `.watch-toggle` handler body:

```js
  body.addEventListener('click', async (e) => {
    const b = e.target.closest('.watch-toggle'); if (!b) return;
    const id = +b.dataset.id;
    const toggle = (putBack) => fetch(`/api/films/${id}/watchlist`, { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(putBack ? { restore: true, before: starMemory.get(id) ?? null } : {}) }).catch(() => null);
    const r = await toggle(starMemory.has(id));
    if (!r || !r.ok) { toast('Could not update watchlist'); return; }
    const res = await r.json();
    if (res.watchlisted) starMemory.delete(id); else starMemory.set(id, res.below ?? null);
    b.textContent = res.watchlisted ? '★' : '☆';
    const o = await fetch('/api/watchlist/order').catch(() => null);
    if (o && o.ok) applyOrder((await o.json()).order);
    const film = state.films.find((f) => f.id === id);
    if (film) {
      film.watchlisted = res.watchlisted; applyFilters();
      const below = res.below ?? null;
      moveOnIfLeft({ film: film.id, slow: false,
        label: res.watchlisted ? `Starred ${film.title}` : `Took ${film.title} off your watchlist`,
        undo: async () => {
          const r2 = await fetch(`/api/films/${film.id}/watchlist`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(res.watchlisted ? {} : { restore: true, before: below }) }).catch(() => null);
          if (!r2 || !r2.ok) { toast('Could not update watchlist'); return false; }
          const j = await r2.json(), f = state.films.find((x) => x.id === film.id);
          if (j.watchlisted) starMemory.delete(film.id);
          const o2 = await fetch('/api/watchlist/order').catch(() => null);
          if (o2 && o2.ok) applyOrder((await o2.json()).order);
          if (f) { f.watchlisted = j.watchlisted; applyFilters(); }
          return true;
        } });
    }
  });
```

Check that `moveOnIfLeft` / the move-on step does NOT call `hideDrawer` (it calls `moveDrawerTo`), so a move-on keeps the visit — and the memory — alive; `test_story_7` proves it.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/web/test_watchlist_order.py tests/web/test_move_on.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/web/static/app.js tests/web/test_watchlist_order.py
git commit -m "Watchlist order: a star put back within one drawer visit returns to its place"
```

---

### Task 7: Docs and the whole suite

**Files:**
- Modify: `.claude/rules/dashboard.md`, `CLAUDE.md` (Commands/Rules prose only where the watchlist is described), `docs/backlog.md` (row 46 + item 46 → BUILT, awaiting hands-on)

- [ ] **Step 1: Write the contract into `.claude/rules/dashboard.md`** — a "Watchlist order (backlog 46)" section: the eight rulings of brief 1.1, the single writer of `watchlist.position` (the repository; the drawer ★ and the row arrows / keys are the only callers), the three-state row click, and the hand-order condition (`handOrderOn`). Keep each paragraph one unbroken line (owner's markdown rule).

- [ ] **Step 2: Run the whole suite and the linters**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy src`
Expected: PASS (mypy carries one pre-existing error at `domain/search.py:296`; anything else is ours to fix).

- [ ] **Step 3: Commit**

```bash
git add .claude/rules/dashboard.md CLAUDE.md docs/backlog.md
git commit -m "Watchlist order: the contract in the dashboard rules; backlog 46 built"
```

---

## After the tasks (not a subagent task)

1. Gap check point C (`docs/superpowers/checks/README.md`): migrate a COPY of the live database, `scripts/gap_check_snapshot.sh <branch-head> <migrated-copy.db> watchlist-order-c`, run the Claude checker (and Codex per the two-lineage pilot), answer every finding in `trial-log.md`, one fix wave, one scoped re-check.
2. Hands-on test on that migrated copy by the owner. Never `migrate --apply` on the live database without his yes.
