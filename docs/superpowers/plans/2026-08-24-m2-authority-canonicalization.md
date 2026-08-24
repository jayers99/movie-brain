# M2 — Authority Canonicalization + Rematch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire a real TMDB-backed `Arbiter`, adopt the shared matcher in the TMDB match step with year write-back (commerce years canonicalized to TMDB's original year, key collisions queued as `year-collision`), and ship a one-shot idempotent `movie-brain rematch` CLI verb covering all TMDB misses and non-Criterion year disagreements.

**Architecture:** All matching stays in `domain/matching.py`'s `match_candidates` core (M1). M2 adds: an infrastructure `TmdbArbiter` (cached TMDB search answering "same-titled film near claimed year?"), commerce-year policy + arbiter pass-through in the `pick_tmdb_match`/`match_film` wrappers, a shared `record_tmdb_match` write path in `application/availability.py` (external-id claim → found flag → commerce year write-back), and `application/rematch.py` orchestrating the one-shot pass. Collectors never delete; every anomaly queues to `match_review`.

**Tech Stack:** Python 3.12, uv, pytest + pytest-bdd (`responses` for HTTP), Typer CLI, SQLite.

**Spec:** `docs/superpowers/specs/2026-08-23-matching-overhaul-design.md` (binding, M1 Done line filled). Handoff: `docs/superpowers/handoffs/2026-08-23-m2-matching-handoff.md`.

## Global Constraints

- Collectors never delete: films/listings/review rows are never removed by any code in this plan (`replace_unresolved_reviews` recomputes derived queue state only, and only for its own reason when scoped).
- `scripts/matching_benchmark.py --assert-dominance` must exit 0 after every task that touches `domain/matching.py`, and at the end.
- `uv run pytest`, `uv run ruff check .`, `uv run mypy` green at every commit.
- `films.guid` is identity; `films.year` updates ONLY through the new `update_film_year` (authority canonicalization, spec principle 5) — importers still never edit year on matched films.
- Key collision on year write-back → `year-collision` review row under authority `tmdb`, film untouched.
- Quiet first-check semantics unchanged: rematch never sets `providers_checked_at`, so newly matched films get baseline (no-transition) listing writes on their first provider fetch.
- New review reasons introduced here: `year-collision`, `id-conflict` (authority `tmdb`). Existing: `no-match` (tmdb), `year-gap` (metacritic).
- Live state facts (verified 2026-08-23/24): film 3086 (Lawrence of Arabia) is ALREADY matched to tmdb 947 by the first live sync — no longer a rematch target; misses are now 486 (`tmdb.found=0`); every film has a `tmdb` row; non-Criterion films: 1,592; 25 open `year-gap` rows under `metacritic`.

## Execution session notes

- Work in a fresh worktree off `main` (superpowers:using-git-worktrees), branch `feature/M2-authority-canonicalization`.
- The live DB at `~/.config/movie-brain/` is NOT touched until the final task (post-merge live run). Tests use temp dirs (existing `repo` fixture).
- A pre-M2 DB backup already exists: `~/.config/movie-brain/movie-brain.db.bak-2026-08-23-pre-m2`.

---

### Task 1: Tri-state Arbiter (domain) + `TmdbArbiter` + `movie_year` (infrastructure)

**Files:**
- Modify: `src/movie_brain/domain/matching.py` (Arbiter type + `match_candidates` arbiter branch, ~lines 158–160 and 311–317)
- Modify: `src/movie_brain/infrastructure/tmdb.py`
- Test: `tests/unit/test_matching.py`, `tests/unit/test_tmdb.py`

**Interfaces:**
- Consumes: M1's `Arbiter = Callable[[str, int], bool]`, `TmdbClient.search`, `norm_title`, `split_annotations`, `TmdbCandidate`.
- Produces: `Arbiter = Callable[[str, int], bool | None]` (None = unavailable → verdict falls back to `review("year-gap")`); `TmdbArbiter` class (`seed(title, candidates)`, `__call__(title, claimed_year) -> bool | None`); `TmdbClient.movie_year(tmdb_id: int) -> int | None`.

The arbiter answers spec principle 4. `None` (network failure) must degrade to the no-arbiter behavior — a `year-gap` review — never an exception escaping into a sync step.

- [ ] **Step 1: Write failing unit tests**

In `tests/unit/test_matching.py` (append; reuse the file's existing helpers for building `MatchQuery`/`CandidateIndex` — adapt constructor calls to the local style already present):

```python
def test_arbiter_unavailable_falls_back_to_year_gap_review():
    index = CandidateIndex([Candidate(id=1, title="Stop Making Sense", year=1984)])
    query = MatchQuery(title="Stop Making Sense", year=2023, year_kind=YearKind.COMMERCE)
    verdict = match_candidates(query, index, arbiter=lambda t, y: None)
    assert verdict.kind == "review" and verdict.reason == "year-gap"
```

In `tests/unit/test_tmdb.py` (append; the file already uses `responses` and `TMDB_API`):

```python
def make_result(tmdb_id, title, year, popularity=1.0):
    return {"id": tmdb_id, "title": title, "original_title": title,
            "release_date": f"{year}-01-01", "popularity": popularity}


@responses.activate
def test_arbiter_hit_when_same_title_near_claimed_year():
    responses.get(f"{TMDB_API}/search/movie",
                  json={"results": [make_result(653, "Nosferatu", 1922), make_result(426063, "Nosferatu", 2024)]})
    arbiter = TmdbArbiter(TmdbClient("tok"))
    assert arbiter("Nosferatu", 2024) is True
    assert arbiter("Nosferatu", 1970) is False  # cached: still exactly 1 HTTP call
    assert len(responses.calls) == 1


@responses.activate
def test_arbiter_seed_avoids_network():
    arbiter = TmdbArbiter(TmdbClient("tok"))
    arbiter.seed("Stop Making Sense", [TmdbCandidate(606, "Stop Making Sense", "Stop Making Sense", 1984, 5.0)])
    assert arbiter("Stop Making Sense", 2023) is False
    assert len(responses.calls) == 0


@responses.activate
def test_arbiter_network_failure_returns_none():
    responses.get(f"{TMDB_API}/search/movie", body=requests.ConnectionError("boom"))
    arbiter = TmdbArbiter(TmdbClient("tok"))
    assert arbiter("Vertigo", 1996) is None


@responses.activate
def test_movie_year_parses_release_date():
    responses.get(f"{TMDB_API}/movie/947", json={"id": 947, "release_date": "1962-12-11"})
    assert TmdbClient("tok").movie_year(947) == 1962


@responses.activate
def test_movie_year_missing_date_is_none():
    responses.get(f"{TMDB_API}/movie/947", json={"id": 947, "release_date": ""})
    assert TmdbClient("tok").movie_year(947) is None
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/unit/test_tmdb.py tests/unit/test_matching.py -q` → FAIL (`TmdbArbiter`/`movie_year` undefined; arbiter-None test fails on truthiness).

- [ ] **Step 3: Implement**

`domain/matching.py` — change the type alias and the arbiter branch in `match_candidates`:

```python
# (title, claimed_year) -> same-titled film exists near claimed_year.
# None = the authority is unreachable right now: fall back to the year-gap review,
# never guess and never let an infrastructure failure escape the verdict.
Arbiter = Callable[[str, int], bool | None]
```

```python
    if result.gap and not (rerelease_hint or result.corroborated):
        if arbiter is not None:
            claimed_year = query.year if query.year is not None else 0
            hit = arbiter(query.title, claimed_year)
            if hit is None:
                return MatchVerdict(kind="review", reason="year-gap")
            if hit:
                return MatchVerdict(kind="review", reason="remake-suspected")
            return MatchVerdict(kind="match", film_id=winner.id)
        return MatchVerdict(kind="review", reason="year-gap")
```

`infrastructure/tmdb.py` — add after `TmdbClient`:

```python
class TmdbArbiter:
    """Spec principle 4: does TMDB know a same-titled film near the claimed year?

    One cached search per normalized title; ``seed()`` lets a match step donate a
    search it already performed so arbitration costs no extra API call for that
    title. Network failure answers ``None`` (arbiter unavailable) — the core then
    falls back to a year-gap review instead of guessing.
    """

    def __init__(self, client: TmdbClient) -> None:
        self._client = client
        self._cache: dict[str, list[TmdbCandidate]] = {}

    def seed(self, title: str, candidates: list[TmdbCandidate]) -> None:
        self._cache[norm_title(title)] = candidates

    def __call__(self, title: str, claimed_year: int) -> bool | None:
        key = norm_title(title)
        if key not in self._cache:
            try:
                self._cache[key] = self._client.search(title)
            except (AuthError, requests.RequestException):
                return None
        stripped = norm_title(split_annotations(title)[0])
        for c in self._cache[key]:
            if c.year is None or abs(c.year - claimed_year) > 1:
                continue
            if any(norm_title(split_annotations(t)[0]) == stripped for t in (c.title, c.original_title)):
                return True
        return False
```

Add to `TmdbClient`:

```python
    def movie_year(self, tmdb_id: int) -> int | None:
        d = self._get(f"/movie/{tmdb_id}").json().get("release_date") or ""
        return int(d[:4]) if len(d) >= 4 and d[:4].isdigit() else None
```

Imports needed in `tmdb.py`: `from movie_brain.domain.matching import norm_title, split_annotations` (infrastructure may import domain — dependencies point inward).

- [ ] **Step 4: Run** — `uv run pytest tests/unit/test_tmdb.py tests/unit/test_matching.py -q` → PASS.
- [ ] **Step 5: Gates** — `uv run pytest -q && uv run ruff check . && uv run mypy && uv run python scripts/matching_benchmark.py --assert-dominance` → all green.
- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat: tri-state Arbiter + cached TmdbArbiter and movie_year adapter"`

---

### Task 2: Commerce-year + arbiter policy in `pick_tmdb_match` and `match_film`

**Files:**
- Modify: `src/movie_brain/domain/matching.py` (`pick_tmdb_match` ~line 454, `match_film` ~line 400)
- Test: `tests/unit/test_matching.py`

**Interfaces:**
- Consumes: Task 1's tri-state `Arbiter`.
- Produces:
  - `pick_tmdb_match(title, year, candidates, *, commerce_year: bool = False, arbiter: Arbiter | None = None) -> int | None` — commerce_year switches the query to `YearKind.COMMERCE`; defaults preserve M1 behavior exactly (benchmark baseline untouched).
  - `match_film(mc_title, mc_year, candidates, *, arbiter: Arbiter | None = None) -> MatchResult` — pass-through to `match_candidates`.

No director/runtime params on `pick_tmdb_match`: TMDB search results carry neither, so the evidence can't fire — YAGNI.

- [ ] **Step 1: Write failing tests** (append to `tests/unit/test_matching.py`):

```python
def _tc(tmdb_id, title, year, popularity=1.0):
    return TmdbCandidate(tmdb_id, title, title, year, popularity)


def test_pick_tmdb_commerce_rerelease_matches_original_when_no_remake():
    # Stop Making Sense: commerce-created with the 2023 re-release year; TMDB only
    # knows the 1984 original → arbiter finds nothing near 2023 → match it.
    cands = [_tc(606, "Stop Making Sense", 1984)]
    arbiter = lambda t, y: False  # noqa: E731
    assert pick_tmdb_match("Stop Making Sense", 2023, cands, commerce_year=True, arbiter=arbiter) == 606


def test_pick_tmdb_commerce_gap_without_arbiter_is_a_miss():
    cands = [_tc(606, "Stop Making Sense", 1984)]
    assert pick_tmdb_match("Stop Making Sense", 2023, cands, commerce_year=True) is None


def test_pick_tmdb_commerce_remake_suspected_is_a_miss():
    cands = [_tc(606, "Stop Making Sense", 1984)]
    assert pick_tmdb_match("Stop Making Sense", 2023, cands, commerce_year=True, arbiter=lambda t, y: True) is None


def test_pick_tmdb_database_band_unchanged():
    # Criterion-walked films keep the tight band: a 2-year gap disqualifies.
    cands = [_tc(947, "Lawrence of Arabia", 1962)]
    assert pick_tmdb_match("Lawrence of Arabia", 1962, cands) == 947
    assert pick_tmdb_match("Lawrence of Arabia", 1964, cands) is None


def test_match_film_arbiter_resolves_year_gap():
    # Tokyo Story class: MC's 1972 US release vs our 1953 film — the arbiter says
    # no same-titled film exists near 1972, so the gap is a re-release: match.
    index = CandidateIndex([Candidate(id=7, title="Tokyo Story", year=1953)])
    assert match_film("Tokyo Story", 1972, index).winner is None  # no arbiter: review
    result = match_film("Tokyo Story", 1972, index, arbiter=lambda t, y: False)
    assert result.winner == 7
    hit = match_film("Tokyo Story", 1972, index, arbiter=lambda t, y: True)
    assert hit.winner is None and hit.reason == "remake-suspected"
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/unit/test_matching.py -q` → FAIL (unexpected keyword arguments).

- [ ] **Step 3: Implement**

```python
def pick_tmdb_match(
    title: str,
    year: int | None,
    candidates: list[TmdbCandidate],
    *,
    commerce_year: bool = False,
    arbiter: Arbiter | None = None,
) -> int | None:
    """Pick the TMDB movie a film refers to, or None for the review queue.

    Criterion-walked films carry original years (tight ``DATABASE`` band).
    ``commerce_year=True`` is for films created by a commerce source (Metacritic
    promotion, Apple owned import) whose stored year may be a re-release date:
    the ``COMMERCE`` band makes a trailing gap neutral, and the ``arbiter``
    (principle 4) decides whether that gap hides a remake (miss → review queue)
    or a re-release (match the original). Each TMDB result is indexed under both
    its title and original_title so either can earn the title score; popularity
    breaks ties. The old title-blind "first of top-3 within ±1 year" fallback is
    deliberately gone — it was the Lawrence-of-Arabia-to-731627 wrong-match vector.
    """
    index = CandidateIndex()
    for c in candidates:
        index.add(Candidate(id=c.tmdb_id, title=c.title, year=c.year, popularity=c.popularity))
        index.add(Candidate(id=c.tmdb_id, title=c.original_title, year=c.year, popularity=c.popularity))
    query = MatchQuery(
        title=title, year=year, year_kind=YearKind.COMMERCE if commerce_year else YearKind.DATABASE
    )
    verdict = match_candidates(query, index, popularity_tiebreak=True, arbiter=arbiter)
    return verdict.film_id if verdict.kind == "match" else None
```

`match_film`: add keyword-only `arbiter: Arbiter | None = None`, pass `arbiter=arbiter` in its `match_candidates` call. Docstring: note the arbiter auto-resolves the year-gap band (Tokyo Story class) when wired.

- [ ] **Step 4: Run** — `uv run pytest tests/unit/test_matching.py -q` → PASS.
- [ ] **Step 5: Gates** — full suite + ruff + mypy + `uv run python scripts/matching_benchmark.py --assert-dominance` → green.
- [ ] **Step 6: Commit** — `git commit -am "feat: commerce-year + arbiter policy in TMDB and Metacritic wrappers"`

---

### Task 3: Repository additions

**Files:**
- Modify: `src/movie_brain/infrastructure/database.py`
- Test: `tests/unit/test_database.py`

**Interfaces:**
- Consumes: existing `films`, `listings`, `tmdb`, `external_ids`, `match_review` tables; `film_key` from `movie_brain.domain.models`.
- Produces (all on `Repository`):
  - `class TmdbMatchTarget(NamedTuple): film_id: int; title: str; year: int | None; commerce: bool` (module level, next to `FilmRow`)
  - `films_needing_tmdb_match() -> list[TmdbMatchTarget]` (CHANGED return type; `commerce` = no criterion listing)
  - `films_tmdb_missed_targets() -> list[TmdbMatchTarget]` (found=0 rows, same shape)
  - `commerce_films_with_tmdb() -> list[tuple[int, str, int | None, str]]` — (film_id, title, year, tmdb_value) for non-Criterion films with a tmdb external id
  - `update_film_year(film_id: int, year: int) -> int | None` — recomputes key; returns colliding film id (nothing written) or None (updated)
  - `film_id_for_external(authority: str, value: str) -> int | None`
  - `replace_unresolved_reviews(authority, entries, created, *, reason: str | None = None)` — when reason given, deletes/replaces only that reason's unresolved rows

No schema change — no migration.

- [ ] **Step 1: Write failing tests** (append to `tests/unit/test_database.py`; use the file's existing `repo` fixture and seeding helpers — adapt to local style):

```python
def test_films_needing_tmdb_match_flags_commerce(repo):
    a = repo.upsert_film(Film("Trio", 1950, None, "https://c/trio"))
    repo.record_listing(a, "criterion", "https://c/trio", date(2026, 8, 24))
    b = repo.upsert_film(Film("Stop Making Sense", 2023, None, "https://mc/sms"))
    targets = {t.film_id: t for t in repo.films_needing_tmdb_match()}
    assert targets[a].commerce is False
    assert targets[b].commerce is True


def test_update_film_year_recomputes_key(repo):
    fid = repo.upsert_film(Film("Stop Making Sense", 2023, None, "u"))
    assert repo.update_film_year(fid, 1984) is None
    assert repo.film_id_by_key("stop making sense (1984)") == fid
    assert repo.film_id_by_key("stop making sense (2023)") is None


def test_update_film_year_collision_returns_twin_and_writes_nothing(repo):
    orig = repo.upsert_film(Film("Nosferatu", 1922, None, "u1"))
    twin = repo.upsert_film(Film("Nosferatu", 1979, None, "u2"))
    assert repo.update_film_year(twin, 1922) == orig
    assert repo.film_id_by_key("nosferatu (1979)") == twin  # untouched


def test_replace_unresolved_reviews_reason_scope(repo):
    d = date(2026, 8, 24)
    repo.append_reviews("tmdb", [ReviewEntry("year-collision", film_id=1)], d)
    repo.replace_unresolved_reviews("tmdb", [ReviewEntry("no-match", film_id=2)], d, reason="no-match")
    reasons = sorted(r["reason"] for r in repo.open_reviews("tmdb"))
    assert reasons == ["no-match", "year-collision"]


def test_commerce_films_with_tmdb_excludes_criterion(repo):
    d = date(2026, 8, 24)
    a = repo.upsert_film(Film("Trio", 1950, None, "u1"))
    repo.record_listing(a, "criterion", "u1", d)
    repo.set_external_id(a, "tmdb", "11", d)
    b = repo.upsert_film(Film("Stop Making Sense", 2023, None, "u2"))
    repo.set_external_id(b, "tmdb", "606", d)
    assert repo.commerce_films_with_tmdb() == [(b, "Stop Making Sense", 2023, "606")]
    assert repo.film_id_for_external("tmdb", "606") == b
    assert repo.film_id_for_external("tmdb", "999") is None
```

Also update any existing tests/steps that consume `films_needing_tmdb_match()` tuples (grep for it) to the NamedTuple shape.

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/unit/test_database.py -q`.

- [ ] **Step 3: Implement**

```python
class TmdbMatchTarget(NamedTuple):
    """One film awaiting a TMDB match, with the policy bit the wrapper needs."""

    film_id: int
    title: str
    year: int | None
    commerce: bool  # no criterion listing → commerce-created; year is COMMERCE band


_TMDB_TARGET_SELECT = (
    "SELECT f.id, f.title, f.year, "
    "NOT EXISTS (SELECT 1 FROM listings l WHERE l.film_id = f.id AND l.source = 'criterion') AS commerce "
    "FROM films f "
)
```

```python
    def films_needing_tmdb_match(self) -> list[TmdbMatchTarget]:
        with self._conn() as c:
            rows = c.execute(
                _TMDB_TARGET_SELECT
                + "WHERE NOT EXISTS (SELECT 1 FROM tmdb t WHERE t.film_id = f.id) ORDER BY f.id"
            ).fetchall()
            return [TmdbMatchTarget(int(r["id"]), str(r["title"]), r["year"], bool(r["commerce"])) for r in rows]

    def films_tmdb_missed_targets(self) -> list[TmdbMatchTarget]:
        with self._conn() as c:
            rows = c.execute(
                _TMDB_TARGET_SELECT + "JOIN tmdb t ON t.film_id = f.id WHERE t.found = 0 ORDER BY f.id"
            ).fetchall()
            return [TmdbMatchTarget(int(r["id"]), str(r["title"]), r["year"], bool(r["commerce"])) for r in rows]

    def commerce_films_with_tmdb(self) -> list[tuple[int, str, int | None, str]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT f.id, f.title, f.year, x.value FROM films f "
                "JOIN external_ids x ON x.film_id = f.id AND x.authority = 'tmdb' "
                "WHERE NOT EXISTS (SELECT 1 FROM listings l WHERE l.film_id = f.id AND l.source = 'criterion') "
                "ORDER BY f.id"
            ).fetchall()
            return [(int(r["id"]), str(r["title"]), r["year"], str(r["value"])) for r in rows]

    def update_film_year(self, film_id: int, year: int) -> int | None:
        """Adopt an authority year: rewrite films.year and recompute key.

        Returns the id of a film already holding the recomputed key — the
        detected-twin case; the caller queues a year-collision review and this
        film stays untouched (never overwrite, collectors never delete).
        """
        with self._conn() as c:
            row = c.execute("SELECT title FROM films WHERE id = ?", (film_id,)).fetchone()
            new_key = film_key(str(row["title"]), year)
            clash = c.execute("SELECT id FROM films WHERE key = ? AND id != ?", (new_key, film_id)).fetchone()
            if clash is not None:
                return int(clash["id"])
            c.execute("UPDATE films SET year = ?, key = ? WHERE id = ?", (year, new_key, film_id))
            return None

    def film_id_for_external(self, authority: str, value: str) -> int | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT film_id FROM external_ids WHERE authority = ? AND value = ?", (authority, value)
            ).fetchone()
            return None if row is None else int(row["film_id"])
```

`replace_unresolved_reviews` gains keyword-only `reason: str | None = None`:

```python
    def replace_unresolved_reviews(
        self, authority: str, entries: list[ReviewEntry], created: date, *, reason: str | None = None
    ) -> None:
        # Derived state, recomputed per match run — the immutability rule binds films, not
        # this queue. reason scopes the replace so recomputing one reason's rows (tmdb
        # no-match) can't wipe durable rows queued under the same authority (year-collision).
        with self._conn() as c:
            if reason is None:
                c.execute("DELETE FROM match_review WHERE authority = ? AND resolved = 0", (authority,))
            else:
                c.execute(
                    "DELETE FROM match_review WHERE authority = ? AND resolved = 0 AND reason = ?",
                    (authority, reason),
                )
            for e in entries:
                c.execute(
                    "INSERT INTO match_review (authority, film_id, value, reason, detail, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (authority, e.film_id, e.value, e.reason, e.detail, created.isoformat()),
                )
```

Import `film_key` alongside the existing `movie_brain.domain.models` imports. Update `application/availability.py`'s loop destructuring minimally so the suite compiles (full adoption is Task 4): `for film_id, title, year in ...` → `for target in ...` with `target.film_id`/`target.title`/`target.year`.

- [ ] **Step 4: Run** — `uv run pytest -q` → PASS (fix any callers the grep found).
- [ ] **Step 5: Gates** — ruff + mypy + benchmark gate → green.
- [ ] **Step 6: Commit** — `git commit -am "feat: repository support for year write-back and rematch targeting"`

---

### Task 4: TMDB step adopts the shared matcher + year write-back

**Files:**
- Modify: `src/movie_brain/application/availability.py`
- Test: `tests/features/tmdb.feature`, `tests/step_defs/test_tmdb.py`

**Interfaces:**
- Consumes: `TmdbArbiter` (Task 1), `pick_tmdb_match(..., commerce_year=, arbiter=)` (Task 2), `TmdbMatchTarget`, `update_film_year`, `film_id_for_external`, reason-scoped `replace_unresolved_reviews` (Task 3).
- Produces: `record_tmdb_match(repo, target: TmdbMatchTarget, winner_id: int, winner_year: int | None, today: date, log) -> str` returning `"matched" | "id-conflict"` — the single TMDB match write path, reused verbatim by Task 6's rematch. Also `queue_review_once(repo, authority, entry, today) -> bool` (append iff no open row with same reason+film_id).

- [ ] **Step 1: Write failing BDD scenarios** (append to `tests/features/tmdb.feature`):

```gherkin
  Scenario: A commerce film with a re-release year matches the original and adopts its year
    Given a commerce film "Stop Making Sense" from 2023
    And TMDB knows "Stop Making Sense" as id 606 released 1984
    When I sync with a TMDB token
    Then "Stop Making Sense (1984)" has external id "606" for authority "tmdb"
    And the film "Stop Making Sense" has year 1984 and key "stop making sense (1984)"
    And TMDB search was called exactly 2 times

  Scenario: Year write-back that collides with an existing key queues year-collision
    Given a commerce film "Nosferatu" from 2024
    And the Criterion catalog has films "Nosferatu (1922)"
    And TMDB knows "Nosferatu" as id 653 released 1922
    When I sync with a TMDB token
    Then the film "Nosferatu" from 2024 still has year 2024
    And the tmdb review queue holds a "year-collision" entry
    When I sync with a TMDB token again the next day
    Then the tmdb review queue holds 1 "year-collision" entries

  Scenario: A criterion film never gets a year write-back
    Given TMDB knows "Trio" as id 11 released 1949
    And TMDB streams id 11 on providers 1899 and 258
    When I sync with a TMDB token
    Then the film "Trio" from 1950 still has year 1950

  Scenario: A commerce film whose TMDB id is already claimed queues id-conflict
    Given the Criterion catalog has films "Trio (1950)"
    And a commerce film "Trio" from 1950 titled distinctly
    And TMDB knows "Trio" as id 11 released 1950
    When I sync with a TMDB token
    Then the tmdb review queue holds a "id-conflict" entry
```

Notes for the step author (implement in `tests/step_defs/test_tmdb.py`, following the file's existing callback style):
- `Given a commerce film "T" from Y` → `ctx["repo"].upsert_film(Film("T", Y, None, "https://mc/t"))` (no criterion listing → commerce).
- `TMDB knows "T" as id N released Y` → register the search callback to answer title `T` with one result `{id: N, title: T, original_title: T, release_date: "Y-01-01", popularity: 5.0}`. Reuse/extend the existing `tmdb_knows` machinery — it likely needs a variant where the search-result year differs from the film's stored year.
- "search called exactly 2 times" in the first scenario = the step's own search + the arbiter's cached search happens to be seeded, so actually expect **1**; assert whatever the seeded implementation yields and pin it (the point is: no unbounded extra calls). Verify against the implementation and set the exact number.
- The id-conflict scenario needs two films that both match id 11; simplest is a commerce twin with the same title matched after the criterion film claims the id ("titled distinctly" = give it URL-only distinction but same title/year is impossible under key UNIQUE — use year 1951 with commerce band, or title "Trio " variant; the step author picks the minimal seeding that makes both films resolve to id 11, e.g. commerce film "Trio" from 1952 whose gap the arbiter clears).
- New Then steps: film year/key assertion via direct `sqlite3` query on `ctx["repo"]` DB (existing steps already do raw queries); review-queue-by-reason count via `repo.open_reviews("tmdb")`.

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/step_defs/test_tmdb.py -q` → new scenarios FAIL.

- [ ] **Step 3: Implement in `availability.py`**

```python
def queue_review_once(repo: Repository, authority: str, entry: ReviewEntry, today: date) -> bool:
    """Append a durable review row unless an open one with the same reason+film already exists.

    Durable reasons (year-collision, id-conflict) survive the per-run no-match rebuild,
    so idempotent passes must not stack duplicates.
    """
    for r in repo.open_reviews(authority):
        if r["reason"] == entry.reason and r["film_id"] == entry.film_id:
            return False
    repo.append_reviews(authority, [entry], today)
    return True


def record_tmdb_match(
    repo: Repository,
    target: TmdbMatchTarget,
    winner_id: int,
    winner_year: int | None,
    today: date,
    log: Callable[[str], None],
) -> str:
    """The one TMDB match write path: claim the id, flag found, canonicalize the year.

    Commerce-created films adopt TMDB's original year (spec principle 5) — a key
    collision is a detected twin and queues year-collision instead of overwriting.
    Returns "matched" or "id-conflict".
    """
    try:
        repo.set_external_id(target.film_id, TMDB_AUTHORITY, str(winner_id), today)
    except sqlite3.IntegrityError:
        holder = repo.film_id_for_external(TMDB_AUTHORITY, str(winner_id))
        log(f"tmdb id conflict for {target.title!r}: id {winner_id} already claimed by film {holder}")
        repo.upsert_tmdb(target.film_id, found=False, looked_up=today)
        queue_review_once(
            repo,
            TMDB_AUTHORITY,
            ReviewEntry(
                "id-conflict",
                film_id=target.film_id,
                value=str(winner_id),
                detail=f"{target.title!r} ({target.year}) vs film {holder} — same tmdb id, likely twins",
            ),
            today,
        )
        return "id-conflict"
    repo.upsert_tmdb(target.film_id, found=True, looked_up=today)
    if target.commerce and winner_year is not None and winner_year != target.year:
        clash = repo.update_film_year(target.film_id, winner_year)
        if clash is not None:
            queue_review_once(
                repo,
                TMDB_AUTHORITY,
                ReviewEntry(
                    "year-collision",
                    film_id=target.film_id,
                    value=str(clash),
                    detail=f"{target.title!r}: adopting {winner_year} over {target.year} "
                    f"collides with film {clash} — merge candidate",
                ),
                today,
            )
        else:
            log(f"adopted TMDB year {winner_year} for {target.title!r} (was {target.year})")
    return "matched"
```

Rework the match loop in `tmdb_step`:

```python
    arbiter = TmdbArbiter(client)
    for target in repo.films_needing_tmdb_match():
        if consecutive >= MAX_CONSECUTIVE_FAILURES:
            log("TMDB searches failing repeatedly — stopping; next run resumes.")
            aborted = True
            break
        try:
            candidates = client.search(target.title)
        except AuthError as exc:
            log(f"TMDB rejected the token: {exc}")
            return TmdbStepResult(matched, missed, refreshed)
        except requests.RequestException as exc:
            log(f"TMDB search failed for {target.title!r}: {exc}")
            consecutive += 1
            continue
        consecutive = 0
        arbiter.seed(target.title, candidates)
        winner = pick_tmdb_match(
            target.title,
            target.year,
            candidates,
            commerce_year=target.commerce,
            arbiter=arbiter if target.commerce else None,
        )
        if winner is None:
            repo.upsert_tmdb(target.film_id, found=False, looked_up=today)
            missed += 1
        else:
            winner_year = next((c.year for c in candidates if c.tmdb_id == winner), None)
            if record_tmdb_match(repo, target, winner, winner_year, today, log) == "matched":
                matched += 1
            else:
                missed += 1
```

And scope the queue rebuild: `repo.replace_unresolved_reviews(TMDB_AUTHORITY, [...no-match entries...], today, reason="no-match")`.

Imports: `TmdbArbiter`, `TmdbMatchTarget`, `ReviewEntry`, `pick_tmdb_match` (already), `sqlite3` (already).

- [ ] **Step 4: Run** — `uv run pytest tests/step_defs/test_tmdb.py tests/step_defs/test_sync.py -q` → PASS (fix pre-existing scenarios if the arbiter's extra search call changes call-count assertions — seeding should keep them stable; pin exact counts).
- [ ] **Step 5: Gates** — full suite + ruff + mypy + benchmark gate → green.
- [ ] **Step 6: Commit** — `git commit -am "feat: TMDB step adopts shared matcher with arbitration and year write-back"`

---

### Task 5: Arbiter wiring into Metacritic promotion (sync path only)

**Files:**
- Modify: `src/movie_brain/application/metacritic.py` (`match_archive`, `promote_top_n`)
- Modify: `src/movie_brain/application/sync.py` (build client/arbiter once, pass to promotion and tmdb_step)
- Test: `tests/features/metacritic.feature` + `tests/step_defs/test_metacritic.py` (or unit tests in `tests/unit/test_metacritic.py` if the feature file doesn't exercise promotion with HTTP mocks — follow where existing promotion tests live)

**Interfaces:**
- Consumes: `match_film(..., arbiter=)` (Task 2), `TmdbArbiter` (Task 1).
- Produces: `match_archive(repo, config_dir, today, *, arbiter: Arbiter | None = None, log=...)`, `promote_top_n(repo, config_dir, today, n, *, arbiter: Arbiter | None = None, log=...)`; `sync` passes a shared `TmdbArbiter` when a token exists.

Rationale (handoff, "intentional behavior changes"): the Tokyo-Story-class `year-gap` reviews are what "M2's arbiter wiring is what auto-resolves"; with the arbiter, those staged titles match their original film, the slug gets claimed, and the stale `year-gap` rows drop out of the recomputed queue on the same run. The `metacritic match` CLI verb stays offline (no arbiter) — only sync, which already talks to TMDB, wires it. Arbiter unavailability (tri-state None) degrades to the M1 year-gap review — promotion can never break on TMDB weather.

- [ ] **Step 1: Write failing test.** Follow the existing metacritic test conventions; the essential behavior, as a unit-style test if BDD plumbing is heavy (place it where the current `match_archive` tests live):

```python
def test_match_archive_arbiter_resolves_year_gap(repo, tmp_path):
    # staged: "Tokyo Story" (1972) in the archive; film: Tokyo Story (1953).
    # Arbiter finds no same-titled film near 1972 → slug claimed, no year-gap row.
    ...build a one-page archive fixture the way existing match_archive tests do...
    fid = repo.upsert_film(Film("Tokyo Story", 1953, None, "u"))
    report = match_archive(repo, config_dir, date(2026, 8, 24), arbiter=lambda t, y: False)
    assert repo.external_ids_for(fid)["metacritic"] == "tokyo-story"
    assert not [r for r in repo.open_reviews("metacritic") if r["reason"] == "year-gap"]


def test_match_archive_arbiter_hit_keeps_review(repo, tmp_path):
    ...same fixture...
    repo.upsert_film(Film("Tokyo Story", 1953, None, "u"))
    match_archive(repo, config_dir, date(2026, 8, 24), arbiter=lambda t, y: True)
    assert [r for r in repo.open_reviews("metacritic") if r["reason"] == "year-gap"]
```

(The second assertion queues under the existing `year-gap` reason regardless of `remake-suspected` vs `year-gap` verdict — see Step 3.)

- [ ] **Step 2: Run to verify failure** — unexpected keyword `arbiter`.

- [ ] **Step 3: Implement.**
  - `match_archive`: add keyword-only `arbiter: Arbiter | None = None`; the match call becomes `match_film(t.title, t.year, index, arbiter=arbiter)`. The review branch already queues any non-tie reason under `"year-gap"` — keep that (a `remake-suspected` verdict lands as a `year-gap` row with the reason in `detail`, which `promote_top_n` skips identically; introducing a new MC reason is M3 queue-hygiene territory).
  - `promote_top_n`: add keyword-only `arbiter: Arbiter | None = None`, pass through to `match_archive`.
  - `sync.py`: before the promotion block, build once:

```python
    tmdb_client = TmdbClient(tmdb_token, session=session) if tmdb_token else None
    arbiter = TmdbArbiter(tmdb_client) if tmdb_client is not None else None
```

  Pass `arbiter=arbiter` into `promote_top_n`, and reuse `tmdb_client` in the tmdb_step call (`tmdb_step(repo, tmdb_client, today, log=log)` — drop the inline `TmdbClient(...)` construction). Import `TmdbArbiter` in sync.py.
  - `tmdb_step` may optionally accept the shared arbiter (`tmdb_step(repo, client, today, *, arbiter=None, log=...)`, constructing its own when None) so sync's promotion cache carries over — do this; it's one parameter and halves duplicate searches.

- [ ] **Step 4: Run** — targeted tests then `uv run pytest -q` → PASS. Watch for sync scenarios that assumed promotion makes zero HTTP calls; offline paths (no token, `metacritic match` verb) must still make none.
- [ ] **Step 5: Gates** — ruff + mypy + benchmark gate → green.
- [ ] **Step 6: Commit** — `git commit -am "feat: sync promotion arbitrates Metacritic year gaps via TMDB"`

---

### Task 6: `movie-brain rematch` — one-shot idempotent rematch pass

**Files:**
- Create: `src/movie_brain/application/rematch.py`
- Modify: `src/movie_brain/cli.py`
- Test: `tests/features/rematch.feature` (create), `tests/step_defs/test_rematch.py` (create), `tests/unit/test_cli.py` (token-missing exit)

**Interfaces:**
- Consumes: `films_tmdb_missed_targets`, `commerce_films_with_tmdb`, `films_tmdb_missed`, `update_film_year` (Task 3); `record_tmdb_match`, `queue_review_once`, `TMDB_AUTHORITY` (Task 4); `TmdbArbiter`, `TmdbClient.movie_year` (Task 1); `pick_tmdb_match` (Task 2).
- Produces: `rematch(repo, client, today, *, log=_stderr) -> RematchReport` and CLI verb `movie-brain rematch`.

```python
@dataclass(frozen=True)
class RematchReport:
    exit_code: int          # 0 ok · 1 tripwired (partial, safe to re-run) · 2 auth
    misses: int             # pass A targets (found=0 at start)
    rematched: int
    still_missed: int
    id_conflicts: int
    checked: int            # pass B non-criterion films year-checked
    years_adopted: int
    collisions_queued: int
    uncorrected: int        # audit: mismatches seen but neither adopted nor queued (skips)
```

- [ ] **Step 1: Write failing BDD** — `tests/features/rematch.feature`:

```gherkin
Feature: Rematch pass
  A one-shot, idempotent repair verb: re-run the shared matcher over every TMDB miss
  and reconcile every non-Criterion film's year against TMDB. Collectors never delete.

  Background:
    Given a fresh repository

  Scenario: A missed commerce film is rematched and adopts TMDB's original year
    Given a commerce film "Stop Making Sense" from 2023 marked as a TMDB miss
    And TMDB knows "Stop Making Sense" as id 606 released 1984
    When I run rematch
    Then "Stop Making Sense (1984)" has external id "606" for authority "tmdb"
    And the film "Stop Making Sense" has year 1984
    And the rematch report says 1 rematched and 1 year adopted

  Scenario: Rematch is idempotent
    Given a commerce film "Stop Making Sense" from 2023 marked as a TMDB miss
    And TMDB knows "Stop Making Sense" as id 606 released 1984
    When I run rematch
    And I run rematch again
    Then the second report says 0 rematched and 0 years adopted
    And the tmdb review queue holds 0 "year-collision" entries

  Scenario: A matched non-criterion film with a disagreeing year adopts the TMDB year
    Given a commerce film "Beauty and the Beast" from 2002 already matched to TMDB id 194
    And TMDB movie 194 was released in 1946
    When I run rematch
    Then the film "Beauty and the Beast" has year 1946
    And the rematch report says 1 checked and 1 year adopted

  Scenario: A year adoption that collides queues one merge candidate, even across runs
    Given a commerce film "Nosferatu" from 2024 already matched to TMDB id 653
    And a film "Nosferatu" from 1922 exists
    And TMDB movie 653 was released in 1922
    When I run rematch
    And I run rematch again
    Then the film "Nosferatu" from 2024 still has year 2024
    And the tmdb review queue holds 1 "year-collision" entries

  Scenario: Criterion films are never year-checked
    Given a criterion film "Trio" from 1950 already matched to TMDB id 11
    When I run rematch
    Then the rematch report says 0 checked
    And TMDB movie details were fetched 0 times

  Scenario: A still-unmatched film stays in the no-match queue
    Given a commerce film "Obscurity" from 1999 marked as a TMDB miss
    And TMDB has no results for any search
    When I run rematch
    Then the rematch report says 0 rematched and 1 still missed
    And the tmdb review queue holds 1 "no-match" entries
```

Step defs (`tests/step_defs/test_rematch.py`): copy the `responses.RequestsMock` fixture pattern from `test_tmdb.py`; seed films directly via `Repository` (`upsert_film`, `record_listing` for criterion, `upsert_tmdb(found=False/True)`, `set_external_id`); register `/search/movie` and `/movie/{id}` callbacks; call `rematch(repo, TmdbClient("tok"), TODAY)` in the When steps, stashing each report.

- [ ] **Step 2: Run to verify failure** — module `movie_brain.application.rematch` doesn't exist.

- [ ] **Step 3: Implement `application/rematch.py`**

```python
from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import requests

from movie_brain.application.availability import (
    MAX_CONSECUTIVE_FAILURES,
    TMDB_AUTHORITY,
    queue_review_once,
    record_tmdb_match,
)
from movie_brain.domain.matching import pick_tmdb_match
from movie_brain.domain.models import ReviewEntry
from movie_brain.infrastructure.database import Repository
from movie_brain.infrastructure.tmdb import AuthError, TmdbArbiter, TmdbClient


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


@dataclass(frozen=True)
class RematchReport:
    exit_code: int
    misses: int
    rematched: int
    still_missed: int
    id_conflicts: int
    checked: int
    years_adopted: int
    collisions_queued: int
    uncorrected: int


def rematch(
    repo: Repository, client: TmdbClient, today: date, *, log: Callable[[str], None] = _stderr
) -> RematchReport:
    """One-shot, idempotent: rematch every TMDB miss, reconcile every non-Criterion year.

    Pass A re-runs the shared matcher (commerce-tolerant, arbitrated) over tmdb.found=0
    films. Pass B fresh-checks TMDB's release year for every matched non-Criterion film
    and adopts disagreements through the same write-back path the sync uses. Provider
    fetches are NOT done here — newly matched films keep providers_checked_at NULL, so
    their first nightly provider pass stays a quiet baseline, not a transition storm.
    """
    arbiter = TmdbArbiter(client)
    misses = repo.films_tmdb_missed_targets()
    rematched = still_missed = id_conflicts = 0
    consecutive = 0
    for target in misses:
        if consecutive >= MAX_CONSECUTIVE_FAILURES:
            log("TMDB failing repeatedly — stopping; rematch is safe to re-run.")
            return RematchReport(1, len(misses), rematched, still_missed, id_conflicts, 0, 0, 0, 0)
        try:
            candidates = client.search(target.title)
        except AuthError as exc:
            log(f"TMDB rejected the token: {exc}")
            return RematchReport(2, len(misses), rematched, still_missed, id_conflicts, 0, 0, 0, 0)
        except requests.RequestException as exc:
            log(f"TMDB search failed for {target.title!r}: {exc}")
            consecutive += 1
            continue
        consecutive = 0
        arbiter.seed(target.title, candidates)
        winner = pick_tmdb_match(
            target.title,
            target.year,
            candidates,
            commerce_year=target.commerce,
            arbiter=arbiter if target.commerce else None,
        )
        if winner is None:
            repo.upsert_tmdb(target.film_id, found=False, looked_up=today)
            still_missed += 1
            continue
        winner_year = next((c.year for c in candidates if c.tmdb_id == winner), None)
        if record_tmdb_match(repo, target, winner, winner_year, today, log) == "matched":
            rematched += 1
        else:
            id_conflicts += 1

    checked = years_adopted = collisions_queued = uncorrected = 0
    for film_id, title, year, tmdb_value in repo.commerce_films_with_tmdb():
        if consecutive >= MAX_CONSECUTIVE_FAILURES:
            log("TMDB failing repeatedly — stopping; rematch is safe to re-run.")
            break
        try:
            tmdb_year = client.movie_year(int(tmdb_value))
        except (AuthError, requests.RequestException) as exc:
            log(f"TMDB details failed for film {film_id}: {exc}")
            consecutive += 1
            uncorrected += 1
            continue
        except ValueError:
            log(f"invalid tmdb id {tmdb_value!r} for film {film_id}")
            uncorrected += 1
            continue
        consecutive = 0
        checked += 1
        if tmdb_year is None or year == tmdb_year:
            continue
        clash = repo.update_film_year(film_id, tmdb_year)
        if clash is None:
            log(f"adopted TMDB year {tmdb_year} for {title!r} (was {year})")
            years_adopted += 1
        else:
            collisions_queued += 1
            queue_review_once(
                repo,
                TMDB_AUTHORITY,
                ReviewEntry(
                    "year-collision",
                    film_id=film_id,
                    value=str(clash),
                    detail=f"{title!r}: adopting {tmdb_year} over {year} collides with film {clash} — merge candidate",
                ),
                today,
            )

    repo.replace_unresolved_reviews(
        TMDB_AUTHORITY,
        [ReviewEntry("no-match", film_id=fid, detail=f"{t} ({y})") for fid, t, y in repo.films_tmdb_missed()],
        today,
        reason="no-match",
    )
    tripwired = consecutive >= MAX_CONSECUTIVE_FAILURES
    return RematchReport(
        1 if tripwired else 0,
        len(misses),
        rematched,
        still_missed,
        id_conflicts,
        checked,
        years_adopted,
        collisions_queued,
        uncorrected,
    )
```

Note on idempotency of `queue_review_once` in `record_tmdb_match`: already dedup-guarded (Task 4). Pass-B collision films re-check every run (their year still disagrees) but the guard keeps the queue at one row.

CLI (`cli.py`):

```python
@app.command()
def rematch_cmd() -> None: ...
```

— register as `@app.command("rematch")`, body:

```python
@app.command("rematch")
def rematch_cmd() -> None:
    """One-shot repair: rematch TMDB misses, reconcile non-Criterion years (idempotent)."""
    from movie_brain.application.rematch import rematch
    from movie_brain.infrastructure.tmdb import TmdbClient

    cfg = load_config()
    token = load_tmdb_token(cfg)
    if not token:
        err.print(f"no TMDB token: set MOVIE_BRAIN_TMDB_TOKEN or write {cfg.tmdb_token_file}")
        raise typer.Exit(2)
    report = rematch(_repo(), TmdbClient(token), date.today())
    console.print(
        f"misses: {report.misses} · rematched: {report.rematched} · still missed: {report.still_missed} · "
        f"id conflicts: {report.id_conflicts}"
    )
    console.print(
        f"year-checked: {report.checked} · adopted: {report.years_adopted} · "
        f"collisions queued: {report.collisions_queued}"
    )
    console.print(f"audit: {report.uncorrected} uncorrected non-criterion year mismatches outside the merge queue")
    raise typer.Exit(report.exit_code)
```

Add a `tests/unit/test_cli.py` case following its existing runner pattern: `rematch` with no token exits 2.

- [ ] **Step 4: Run** — `uv run pytest tests/step_defs/test_rematch.py tests/unit/test_cli.py -q` → PASS.
- [ ] **Step 5: Gates** — full suite + ruff + mypy + benchmark gate → green.
- [ ] **Step 6: Commit** — `git commit -am "feat: one-shot idempotent rematch verb (misses + year reconciliation)"`

---

### Task 7: Docs, final gates, merge, live run, spec Done line, M3 handoff

**Files:**
- Modify: `CLAUDE.md` (Commands block: add `uv run movie-brain rematch`; sync-flow step 4: promotion arbitrates year-gaps via TMDB when a token is present — no metacritic.com scraping, ever; step 6: shared matcher + arbiter + commerce year write-back; Rules: year truth-holder gains "TMDB write-back canonicalizes commerce years; `year-collision` = merge candidate")
- Modify: `docs/superpowers/specs/2026-08-23-matching-overhaul-design.md` (M2 Done line)
- Create: `docs/superpowers/handoffs/2026-08-24-m3-matching-handoff.md`

- [ ] **Step 1: Update CLAUDE.md** per above; keep edits surgical.
- [ ] **Step 2: Final gates in the worktree** — `uv run pytest -q && uv run ruff check . && uv run mypy && uv run python scripts/matching_benchmark.py --assert-dominance` → all green (Playwright included).
- [ ] **Step 3: Merge** — superpowers:finishing-a-development-branch; fast-forward `main`, delete branch/worktree, push.
- [ ] **Step 4: Live run (from `main`, real config):**
  - `cp ~/.config/movie-brain/movie-brain.db ~/.config/movie-brain/movie-brain.db.bak-pre-rematch`
  - `uv run movie-brain rematch` — expect: a chunk of the 486 misses matched (commerce band + arbiter unlocks re-release-year films), years adopted on non-Criterion films, collisions queued, audit line `0 uncorrected`.
  - Verify Done criterion (audit): rematch exit 0 and `uncorrected == 0`; spot checks —
    `sqlite3 ~/.config/movie-brain/movie-brain.db "SELECT COUNT(*) FROM tmdb WHERE found=0;"` (should drop),
    `"SELECT reason, COUNT(*) FROM match_review WHERE authority='tmdb' AND resolved=0 GROUP BY 1;"`,
    Lawrence: `"SELECT value FROM external_ids WHERE film_id=3086 AND authority='tmdb';"` → `947` (already true; must survive).
  - Run `uv run movie-brain sync` once: the promotion arbiter should drain the 25 metacritic `year-gap` rows (claimed slugs → recompute drops them); confirm with `"SELECT COUNT(*) FROM match_review WHERE authority='metacritic' AND reason='year-gap' AND resolved=0;"`.
  - Re-run `uv run movie-brain rematch` once more to demonstrate idempotency live (0 rematched / 0 adopted deltas).
- [ ] **Step 5: Fill the spec's M2 Done line** with the real numbers (misses before/after, years adopted, collisions queued, year-gap queue drained, audit=0, benchmark numbers).
- [ ] **Step 6: Write the M3 handoff** (`docs/superpowers/handoffs/2026-08-24-m3-matching-handoff.md`) covering: M2 result summary + live numbers; M3 scope from the spec (repair dupes with alias/tombstone migration, repair years, review resolution CLI); carried data debt (49 dup groups, 7 apple-tv year-drifts, remaining tmdb queue incl. new `year-collision`/`id-conflict` merge candidates — these feed repair dupes; OMDb payloads fetched under pre-write-back years may need a refetch pass — flag for M3 triage; launchd agent was NOT installed as of 2026-08-24 — user decision pending); first-run checks for M3; entry-point prompt.
- [ ] **Step 7: Commit + push docs** — `git commit -am "docs: M2 done — authority canonicalization live; M3 handoff" && git push`

---

## Self-Review (performed at write time)

- **Spec coverage:** M2 bullet 1 (shared matcher in TMDB step + arbiter) → Tasks 1, 2, 4; principle-4 arbitration → Tasks 1, 2; the handoff's Tokyo-Story auto-resolution promise → Task 5; bullet 2 (year write-back + `year-collision`) → Tasks 3, 4; bullet 3 (rematch verb) → Task 6; Done criterion (live audit) → Task 7. Quiet first-check semantics → rematch never touches `providers_checked_at` (Task 6 docstring + no provider fetches).
- **Type consistency:** `TmdbMatchTarget(film_id, title, year, commerce)` used identically in Tasks 3, 4, 6; `record_tmdb_match(repo, target, winner_id, winner_year, today, log) -> str` consistent between Tasks 4 and 6; tri-state `Arbiter` consistent across Tasks 1, 2, 5.
- **Known judgment calls (decided, do not relitigate):** arbiter wired into sync's promotion but NOT the offline `metacritic match` verb; `id-conflict` review rows added (twin evidence for M3); no director/runtime params on `pick_tmdb_match` (TMDB search carries neither).
