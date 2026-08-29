# Best Source for a Canon Film — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every film a ranked answer to "what is the best place to watch this?", by recording every streaming provider TMDB reports and sorting a film's svod options on four keys.

**Architecture:** Three layers, in dependency order. (1) The data layer stops discarding availability: `TmdbProviders` learns `free` and `ads`, the write path unions all three buckets, and an unknown provider auto-registers as a `movie_service` with `subscribed = 0`. (2) `movie_service` gains two owner-set constants — `quality` and `has_apple_app` — written by exactly one verb. (3) A pure domain function ranks a film's svod options on `subscribed DESC, quality DESC, has_apple_app DESC, name ASC` and the read model exposes the winner as `FilmView.best_source`, computed on every read and never stored.

**Tech Stack:** Python 3, SQLite, Typer CLI, Flask + vanilla JS dashboard, pytest / pytest-bdd / Playwright, uv, ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-08-29-canon-best-source-design.md` (commit `76ae1c2`)

## Global Constraints

- **Never write to `~/.config/movie-brain/movie-brain.db` without rehearsing first** on a scratch copy with `MOVIE_BRAIN_CONFIG_DIR` set, and showing the owner the result. Task 9 is the only task that touches live data, and every step in it is gated.
- **Schema changes get a NEW migration that also inserts its own `schema_version` row.** Never edit an applied migration. Migration 017 is unclaimed; the live DB is at v16.
- **`movie-brain migrate --apply` is the only path that advances an existing DB.** `Repository(path)` raises `PendingMigrations` (CLI exit 2) when the DB is behind.
- **Films are immutable and collectors never delete.** Nothing in this plan deletes a film, a listing, or a review row.
- **Markdown is never hard-wrapped** — one unbroken line per paragraph, list item and blockquote.
- **Gates, run before every commit that touches matching or the read model:** `uv run pytest` · `uv run ruff check .` · `uv run mypy` · `uv run python scripts/thumbprint_benchmark.py --assert` (baseline **n=573 / WRONG=0 / 92.0% over 526**) · `uv run python scripts/matching_benchmark.py --assert-dominance` (apple review ceiling **6.0**).
- **Commit messages are a brief single line focused on "why", not "what".**

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `migrations/017_service_quality.sql` | Create — adds `movie_service.quality` and `movie_service.has_apple_app`, inserts `schema_version` 17 | 1 |
| `src/movie_brain/domain/models.py` | Modify — new `ServiceMeta` dataclass; `TmdbProviders` gains `free`, `ads`, `names`; `FilmView` gains `best_source` | 1, 3, 6 |
| `src/movie_brain/infrastructure/database.py` | Modify — service registry reads/writes, provider auto-registration, `_SERVICES_SQL` columns and order, `best_source` assembly | 1, 4, 6 |
| `src/movie_brain/cli.py` | Modify — new `services` Typer group | 2 |
| `src/movie_brain/infrastructure/tmdb.py` | Modify — `watch_providers` reads `free` and `ads` and carries provider names | 3 |
| `src/movie_brain/application/availability.py` | Modify — union the three buckets, auto-register unknown providers | 4 |
| `src/movie_brain/domain/watch.py` | Create — the pure ranking (`rank_key`, `watch_options`, `best_source`) | 5 |
| `src/movie_brain/domain/filters.py` | Modify — `acquisition_candidate` drops the rated and streamable exclusions | 8 |
| `src/movie_brain/web/static/app.js` | Modify — drawer "Best source" line, card badge, `acquire` chip mirror | 7, 8 |
| `src/movie_brain/web/templates/index.html` | Modify — chip label | 8 |
| `tests/unit/test_database.py`, `test_tmdb.py`, `test_availability.py`, `test_filters.py`, `test_cli.py` | Modify — unit coverage | 1-8 |
| `tests/unit/test_watch.py` | Create — the ranking's own tests | 5 |
| `tests/web/test_api.py` | Modify — `best_source` serialization | 6 |
| `CLAUDE.md`, `.claude/rules/` | Modify — record the new contract | 9 |

---

### Task 1: The two owner-set service constants

**Files:**
- Create: `migrations/017_service_quality.sql`
- Modify: `src/movie_brain/domain/models.py` (add `ServiceMeta` next to the other frozen dataclasses)
- Modify: `src/movie_brain/infrastructure/database.py` (registry reads and writes, near `provider_map` at line 1293)
- Test: `tests/unit/test_database.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ServiceMeta(slug: str, name: str, kind: str, subscribed: bool, region: str, quality: int, has_apple_app: bool)`; `Repository.movie_services() -> list[ServiceMeta]`; `Repository.movie_service(slug: str) -> ServiceMeta | None`; `Repository.set_service_quality(slug: str, quality: int) -> bool`; `Repository.set_service_apple_app(slug: str, has_app: bool) -> bool`; `Repository.set_service_subscribed(slug: str, subscribed: bool) -> bool`. All three setters return `False` for an unknown slug.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_database.py`:

```python
def test_migration_017_adds_service_constants_with_inert_defaults(repo):
    services = {s.slug: s for s in repo.movie_services()}
    assert services["criterion"].quality == 1
    assert services["criterion"].has_apple_app is False
    assert services["mubi"].quality == 1


def test_set_service_quality_writes_one_service_only(repo):
    assert repo.set_service_quality("criterion", 5) is True
    assert repo.movie_service("criterion").quality == 5
    assert repo.movie_service("mubi").quality == 1


def test_set_service_quality_accepts_zero(repo):
    assert repo.set_service_quality("mubi", 0) is True
    assert repo.movie_service("mubi").quality == 0


def test_set_service_apple_app_and_subscribed_round_trip(repo):
    assert repo.set_service_apple_app("criterion", True) is True
    assert repo.set_service_subscribed("mubi", True) is True
    assert repo.movie_service("criterion").has_apple_app is True
    assert repo.movie_service("mubi").subscribed is True


def test_setters_report_an_unknown_slug(repo):
    assert repo.set_service_quality("nope", 3) is False
    assert repo.set_service_apple_app("nope", True) is False
    assert repo.set_service_subscribed("nope", True) is False
    assert repo.movie_service("nope") is None


def test_movie_services_orders_best_first(repo):
    repo.set_service_quality("mubi", 9)
    repo.set_service_subscribed("mubi", True)
    slugs = [s.slug for s in repo.movie_services()]
    assert slugs[0] == "mubi"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_database.py -k "service_constants or set_service or movie_services_orders" -v`
Expected: FAIL with `AttributeError: 'Repository' object has no attribute 'movie_services'`.

- [ ] **Step 3: Write the migration**

Create `migrations/017_service_quality.sql`:

```sql
-- Best source for a canon film: the two owner-set per-service constants
-- (design docs/superpowers/specs/2026-08-29-canon-best-source-design.md §5, decisions C9 + C10).
-- `quality` is the owner's integer judgement of a service's transfer quality — resolution barely
-- varies across this canon, the restoration does, and no API exposes it. `has_apple_app` is C6's
-- preference as a boolean, ranked BELOW quality so it can only ever break a tie.
-- Both default to their inert value: with every service equal the ordering is the old one plus a
-- tiebreak, and the feature diverges only once the owner sets an opinion (the film_list.trust
-- precedent, migration 016). Only `movie-brain services` writes either column.
BEGIN;
ALTER TABLE movie_service ADD COLUMN quality INTEGER NOT NULL DEFAULT 1;
ALTER TABLE movie_service ADD COLUMN has_apple_app INTEGER NOT NULL DEFAULT 0;
INSERT INTO schema_version (version) VALUES (17);
COMMIT;
```

- [ ] **Step 4: Add the `ServiceMeta` dataclass**

In `src/movie_brain/domain/models.py`, beside the other frozen dataclasses:

```python
@dataclass(frozen=True)
class ServiceMeta:
    """One row of the service registry. `quality` and `has_apple_app` are owner-set constants
    written only by `movie-brain services` — see the canon-best-source design §5."""

    slug: str
    name: str
    kind: str
    subscribed: bool
    region: str
    quality: int
    has_apple_app: bool
```

- [ ] **Step 5: Add the registry reads and writes**

In `src/movie_brain/infrastructure/database.py`, import `ServiceMeta` alongside the other model imports, and add beside `provider_map` (line 1293):

```python
_SERVICE_SELECT = "SELECT slug, name, kind, subscribed, region, quality, has_apple_app FROM movie_service "


def _row_to_service(row: sqlite3.Row) -> ServiceMeta:
    return ServiceMeta(
        slug=str(row["slug"]),
        name=str(row["name"]),
        kind=str(row["kind"]),
        subscribed=bool(row["subscribed"]),
        region=str(row["region"]),
        quality=int(row["quality"]),
        has_apple_app=bool(row["has_apple_app"]),
    )
```

and, as methods on `Repository`:

```python
    def movie_services(self) -> list[ServiceMeta]:
        """Every registered service, best first — the display order for `movie-brain services`
        and the same four keys `domain/watch.py` ranks a film's options on."""
        with self._conn() as c:
            rows = c.execute(
                _SERVICE_SELECT + "ORDER BY subscribed DESC, quality DESC, has_apple_app DESC, name"
            ).fetchall()
            return [_row_to_service(r) for r in rows]

    def movie_service(self, slug: str) -> ServiceMeta | None:
        with self._conn() as c:
            row = c.execute(_SERVICE_SELECT + "WHERE slug = ?", (slug,)).fetchone()
            return None if row is None else _row_to_service(row)

    def _set_service_column(self, slug: str, column: str, value: int) -> bool:
        # column is never user input — the three public setters below name it literally.
        with self._conn() as c:
            cur = c.execute(f"UPDATE movie_service SET {column} = ? WHERE slug = ?", (value, slug))
            return cur.rowcount > 0

    def set_service_quality(self, slug: str, quality: int) -> bool:
        """The ONLY writer of `movie_service.quality`. False when the slug is unknown."""
        return self._set_service_column(slug, "quality", quality)

    def set_service_apple_app(self, slug: str, has_app: bool) -> bool:
        """The ONLY writer of `movie_service.has_apple_app`. False when the slug is unknown."""
        return self._set_service_column(slug, "has_apple_app", 1 if has_app else 0)

    def set_service_subscribed(self, slug: str, subscribed: bool) -> bool:
        """The ONLY writer of `movie_service.subscribed`. False when the slug is unknown."""
        return self._set_service_column(slug, "subscribed", 1 if subscribed else 0)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_database.py -v`
Expected: PASS, including the existing `test_migration_003_seeds_service_registry`.

- [ ] **Step 7: Run the full gates**

Run: `uv run pytest && uv run ruff check . && uv run mypy`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add migrations/017_service_quality.sql src/movie_brain/domain/models.py src/movie_brain/infrastructure/database.py tests/unit/test_database.py
git commit -m "a service's worth is the owner's judgement, not a number an API can sell us"
```

---

### Task 2: The `movie-brain services` verb

**Files:**
- Modify: `src/movie_brain/cli.py` (new Typer group; follow `lists_trust_cmd` at line 358 exactly)
- Test: `tests/unit/test_cli.py`

**Interfaces:**
- Consumes: `Repository.movie_services`, `movie_service`, `set_service_quality`, `set_service_apple_app`, `set_service_subscribed` (Task 1).
- Produces: CLI commands `movie-brain services list`, `services quality SLUG [N]`, `services apple SLUG [0|1]`, `services subscribe SLUG [0|1]`. Unknown slug exits 2 and prints the known slugs to stderr.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_cli.py`, following the file's existing `CliRunner` pattern:

```python
def test_services_list_prints_every_service(cli, config_dir):
    result = cli(["services", "list"])
    assert result.exit_code == 0
    assert "criterion" in result.stdout
    assert "quality 1" in result.stdout


def test_services_quality_sets_and_shows_one_service(cli, config_dir):
    assert cli(["services", "quality", "criterion", "5"]).exit_code == 0
    shown = cli(["services", "quality", "criterion"])
    assert shown.exit_code == 0
    assert "quality 5" in shown.stdout


def test_services_quality_accepts_zero(cli, config_dir):
    assert cli(["services", "quality", "mubi", "0"]).exit_code == 0
    assert "quality 0" in cli(["services", "quality", "mubi"]).stdout


def test_services_rejects_a_negative_quality(cli, config_dir):
    assert cli(["services", "quality", "mubi", "-1"]).exit_code != 0


def test_services_apple_and_subscribe_round_trip(cli, config_dir):
    assert cli(["services", "apple", "criterion", "1"]).exit_code == 0
    assert cli(["services", "subscribe", "mubi", "1"]).exit_code == 0
    listed = cli(["services", "list"]).stdout
    assert "apple-app yes" in listed
    assert "subscribed yes" in listed


def test_services_unknown_slug_exits_two(cli, config_dir):
    result = cli(["services", "quality", "nope", "3"])
    assert result.exit_code == 2
```

If `tests/unit/test_cli.py` has no `cli` fixture, add one that mirrors the file's existing invocation helper — a `CliRunner().invoke(app, argv)` with `MOVIE_BRAIN_CONFIG_DIR` pointed at the `config_dir` fixture.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_cli.py -k services -v`
Expected: FAIL — `No such command 'services'`.

- [ ] **Step 3: Implement the verb group**

In `src/movie_brain/cli.py`, beside the other `add_typer` calls (lines 53-69):

```python
services_app = typer.Typer(help="The service registry: quality, Apple TV app, subscription.")
app.add_typer(services_app, name="services")
```

and, beside `lists_trust_cmd`:

```python
def _service_line(m: ServiceMeta) -> str:
    return (
        f"{m.slug:<24} quality {m.quality}   "
        f"apple-app {'yes' if m.has_apple_app else 'no ':<3}   "
        f"subscribed {'yes' if m.subscribed else 'no ':<3}   {m.kind:<5} {m.name}"
    )


def _service_or_exit(repo: Repository, slug: str) -> ServiceMeta:
    meta = repo.movie_service(slug)
    if meta is None:
        known = ", ".join(m.slug for m in repo.movie_services()) or "no services registered"
        err.print(f"unknown service {slug!r} — known services: {known}")
        raise typer.Exit(2)
    return meta


@services_app.command("list")
def services_list_cmd() -> None:
    """Every registered service, best first on the same four keys that rank a film's options."""
    repo = _repo()
    services = repo.movie_services()
    if not services:
        console.print("no services registered")
        return
    for m in services:
        console.print(_service_line(m))


@services_app.command("quality")
def services_quality_cmd(
    slug: Annotated[str, typer.Argument(help="Service slug (e.g. criterion).")],
    n: Annotated[int | None, typer.Argument(min=0, help="New quality; 0 is legal (ranks last).")] = None,
) -> None:
    """Show or set one service's quality — the owner's judgement of its transfers.

    Nothing but this verb writes `movie_service.quality`, so provider auto-registration during
    sync can never reset it."""
    repo = _repo()
    meta = _service_or_exit(repo, slug)
    if n is None:
        console.print(_service_line(meta))
        return
    repo.set_service_quality(slug, n)
    console.print(f"{slug}: quality set to {n}")


@services_app.command("apple")
def services_apple_cmd(
    slug: Annotated[str, typer.Argument(help="Service slug (e.g. criterion).")],
    flag: Annotated[int | None, typer.Argument(min=0, max=1, help="1 = has an Apple TV app.")] = None,
) -> None:
    """Show or set whether a service has an Apple TV application (C6 — a tiebreak, never a veto)."""
    repo = _repo()
    meta = _service_or_exit(repo, slug)
    if flag is None:
        console.print(_service_line(meta))
        return
    repo.set_service_apple_app(slug, bool(flag))
    console.print(f"{slug}: apple-app set to {'yes' if flag else 'no'}")


@services_app.command("subscribe")
def services_subscribe_cmd(
    slug: Annotated[str, typer.Argument(help="Service slug (e.g. kanopy).")],
    flag: Annotated[int | None, typer.Argument(min=0, max=1, help="1 = I subscribe to this.")] = None,
) -> None:
    """Show or set whether the owner subscribes to a service — the top ranking key, and what
    decides whether a film counts as reachable."""
    repo = _repo()
    meta = _service_or_exit(repo, slug)
    if flag is None:
        console.print(_service_line(meta))
        return
    repo.set_service_subscribed(slug, bool(flag))
    console.print(f"{slug}: subscribed set to {'yes' if flag else 'no'}")
```

Import `ServiceMeta` from `movie_brain.domain.models` at the top of `cli.py`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_cli.py -k services -v`
Expected: PASS.

- [ ] **Step 5: Run the full gates**

Run: `uv run pytest && uv run ruff check . && uv run mypy`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/movie_brain/cli.py tests/unit/test_cli.py
git commit -m "one verb owns the registry, so a sync can never overwrite a judgement"
```

---

### Task 3: TMDB stops discarding `free` and `ads`

**Files:**
- Modify: `src/movie_brain/domain/models.py` (`TmdbProviders`, line 138)
- Modify: `src/movie_brain/infrastructure/tmdb.py` (`watch_providers`, line 111)
- Test: `tests/unit/test_tmdb.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `TmdbProviders(flatrate, rent, buy, link, payload, free=(), ads=(), names={})` — `free: tuple[int, ...]`, `ads: tuple[int, ...]`, `names: dict[int, str]` mapping every provider id seen in any bucket to its `provider_name`. The three new fields have defaults so existing constructions keep working.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_tmdb.py`, following the file's existing `responses` mocking pattern:

```python
def test_watch_providers_reads_free_and_ads_and_carries_names(tmdb_client):
    body = {
        "results": {
            "US": {
                "link": "https://www.themoviedb.org/movie/1/watch",
                "flatrate": [{"provider_id": 258, "provider_name": "Criterion Channel"}],
                "free": [{"provider_id": 191, "provider_name": "Kanopy"}],
                "ads": [{"provider_id": 73, "provider_name": "Tubi TV"}],
                "rent": [{"provider_id": 2, "provider_name": "Apple TV"}],
            }
        }
    }
    responses.add(responses.GET, f"{TMDB_API}/movie/1/watch/providers", json=body, status=200)
    p = tmdb_client.watch_providers(1)
    assert p.flatrate == (258,)
    assert p.free == (191,)
    assert p.ads == (73,)
    assert p.names[191] == "Kanopy"
    assert p.names[73] == "Tubi TV"
    assert p.names[258] == "Criterion Channel"


def test_watch_providers_tolerates_missing_buckets(tmdb_client):
    responses.add(responses.GET, f"{TMDB_API}/movie/2/watch/providers", json={"results": {}}, status=200)
    p = tmdb_client.watch_providers(2)
    assert p.flatrate == () and p.free == () and p.ads == ()
    assert p.names == {}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_tmdb.py -k watch_providers -v`
Expected: FAIL — `AttributeError: 'TmdbProviders' object has no attribute 'free'`.

- [ ] **Step 3: Widen the model**

In `src/movie_brain/domain/models.py`, replace the `TmdbProviders` body:

```python
@dataclass(frozen=True)
class TmdbProviders:
    """US watch-provider snapshot for one film; payload is the raw response text.

    `flatrate`, `free` and `ads` are three separate buckets that all mean "I can watch this"
    (design C2), and TMDB files the same service inconsistently across them — Kanopy's US
    catalogue is 16,817 titles under `free` and 9,241 under `flatrate` — so the write path
    unions them rather than choosing between them. `names` carries every seen provider's name
    so an unregistered provider can auto-register instead of being discarded.
    """

    flatrate: tuple[int, ...]
    rent: tuple[int, ...]
    buy: tuple[int, ...]
    link: str | None
    payload: str
    free: tuple[int, ...] = ()
    ads: tuple[int, ...] = ()
    names: dict[int, str] = field(default_factory=dict)
```

`field` is already imported in this module (`FilmView` uses it).

- [ ] **Step 4: Read the new buckets**

In `src/movie_brain/infrastructure/tmdb.py`, replace `watch_providers`:

```python
    def watch_providers(self, tmdb_id: int) -> TmdbProviders:
        resp = self._get(f"/movie/{tmdb_id}/watch/providers")
        us = resp.json().get("results", {}).get("US", {})
        names: dict[int, str] = {}

        def ids(kind: str) -> tuple[int, ...]:
            out = []
            for p in us.get(kind, []):
                pid = int(p["provider_id"])
                out.append(pid)
                if p.get("provider_name"):
                    names[pid] = str(p["provider_name"])
            return tuple(out)

        return TmdbProviders(
            flatrate=ids("flatrate"), rent=ids("rent"), buy=ids("buy"),
            free=ids("free"), ads=ids("ads"),
            link=us.get("link"), payload=resp.text, names=names,
        )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_tmdb.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/movie_brain/domain/models.py src/movie_brain/infrastructure/tmdb.py tests/unit/test_tmdb.py
git commit -m "TMDB files one service across three buckets, so read all three"
```

---

### Task 4: Record every provider, auto-registering unknown ones

**Files:**
- Modify: `src/movie_brain/infrastructure/database.py` (auto-registration, beside `provider_map` at line 1293)
- Modify: `src/movie_brain/application/availability.py` (`_refresh_pass`, line 219)
- Test: `tests/unit/test_database.py`, `tests/unit/test_availability.py`

**Interfaces:**
- Consumes: `TmdbProviders.free`, `.ads`, `.names` (Task 3); `ServiceMeta` (Task 1).
- Produces: `Repository.register_provider(provider_id: int, name: str) -> str` — returns the service slug the provider now maps to, creating the `movie_service` row (`kind='svod'`, `subscribed=0`, defaults for `quality`/`has_apple_app`) and the `service_provider` row when either is missing. Idempotent; never updates an existing `movie_service` row.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_database.py`:

```python
def test_register_provider_creates_an_unsubscribed_service(repo):
    slug = repo.register_provider(191, "Kanopy")
    assert slug == "kanopy"
    meta = repo.movie_service("kanopy")
    assert meta.subscribed is False and meta.kind == "svod"
    assert repo.provider_map()[191] == "kanopy"


def test_register_provider_is_idempotent_and_never_resets_the_owners_values(repo):
    repo.register_provider(191, "Kanopy")
    repo.set_service_quality("kanopy", 7)
    repo.set_service_subscribed("kanopy", True)
    assert repo.register_provider(191, "Kanopy") == "kanopy"
    meta = repo.movie_service("kanopy")
    assert meta.quality == 7 and meta.subscribed is True


def test_register_provider_maps_a_second_id_onto_an_existing_service(repo):
    # Two TMDB ids, one service — the shape migration 003 already uses for Peacock. Use ids the
    # seeded registry does NOT hold (it maps 2, 9, 11, 258, 350, 386, 387, 1899), because an
    # already-mapped id never reaches register_provider at all.
    assert repo.register_provider(1770, "Paramount Plus") == "paramount-plus"
    assert repo.register_provider(1853, "Paramount Plus") == "paramount-plus"
    assert repo.provider_map()[1770] == "paramount-plus"
    assert repo.provider_map()[1853] == "paramount-plus"
    assert len([s for s in repo.movie_services() if s.slug == "paramount-plus"]) == 1


def test_register_provider_slugifies_punctuation(repo):
    assert repo.register_provider(999, "Plex Channel") == "plex-channel"
    assert repo.register_provider(998, "AMC+ / Shudder") == "amc-shudder"
```

Add to `tests/unit/test_availability.py`, following that file's existing pattern for stubbing a `TmdbClient` and asserting written listings:

```python
def test_tmdb_step_records_free_and_ads_alongside_flatrate(repo, stub_tmdb, today):
    stub_tmdb.providers = TmdbProviders(
        flatrate=(1899,), rent=(), buy=(), link="https://x", payload="{}",
        free=(191,), ads=(73,),
        names={1899: "HBO Max", 191: "Kanopy", 73: "Tubi TV"},
    )
    tmdb_step(repo, stub_tmdb, today, log=lambda _: None)
    sources = {row.source for row in repo.listings_for_film(FILM_ID)}
    assert sources == {"max", "kanopy", "tubi-tv"}


def test_tmdb_step_never_records_criterion_from_tmdb(repo, stub_tmdb, today):
    stub_tmdb.providers = TmdbProviders(
        flatrate=(258,), rent=(), buy=(), link="https://x", payload="{}",
        names={258: "Criterion Channel"},
    )
    tmdb_step(repo, stub_tmdb, today, log=lambda _: None)
    assert {row.source for row in repo.listings_for_film(FILM_ID)} == set()
```

Match the fixture names and the listings-reading helper the existing tests in `tests/unit/test_availability.py` already use; if no `listings_for_film` helper exists, assert against a direct `SELECT source FROM listings WHERE film_id = ?` through the repo's connection, as the neighbouring tests do.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_database.py tests/unit/test_availability.py -k "register_provider or free_and_ads or never_records_criterion" -v`
Expected: FAIL — `AttributeError: 'Repository' object has no attribute 'register_provider'`.

- [ ] **Step 3: Implement auto-registration**

In `src/movie_brain/infrastructure/database.py`, beside `provider_map`:

```python
def service_slug(name: str) -> str:
    """A TMDB provider name as a registry slug: lowercase, runs of non-alphanumerics to one
    hyphen, no leading or trailing hyphen. 'Plex Channel' -> 'plex-channel'."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
```

and as a method on `Repository`:

```python
    def register_provider(self, provider_id: int, name: str) -> str:
        """Map a TMDB provider id onto a service, creating both rows when missing.

        Returns the slug. NEVER updates an existing `movie_service` row: the owner's
        `subscribed`, `quality` and `has_apple_app` are judgements, and this runs on every
        sync for every provider TMDB reports.
        """
        slug = service_slug(name)
        with self._conn() as c:
            c.execute(
                "INSERT OR IGNORE INTO movie_service (slug, name, kind, subscribed) VALUES (?, ?, 'svod', 0)",
                (slug, name),
            )
            c.execute(
                "INSERT OR IGNORE INTO service_provider (tmdb_provider_id, service_slug, label) VALUES (?, ?, ?)",
                (provider_id, slug, name),
            )
        return slug
```

Add `import re` to the module's imports if it is not already there.

- [ ] **Step 4: Union the buckets in the write path**

In `src/movie_brain/application/availability.py`, replace the single `slugs = {...}` line (line 219) inside `_refresh_pass`:

```python
        # C2: flatrate, free and ads all mean "I can watch this" — union them rather than
        # choosing. An unregistered provider auto-registers at subscribed=0 instead of being
        # discarded; `subscribed` is what decides everything downstream.
        streaming = (*providers.flatrate, *providers.free, *providers.ads)
        slugs = set()
        for pid in streaming:
            slug = pmap.get(pid)
            if slug is None:
                name = providers.names.get(pid)
                if name is None:
                    continue
                slug = repo.register_provider(pid, name)
                pmap[pid] = slug
            if slug != "criterion":
                slugs.add(slug)
```

The `criterion` exclusion is load-bearing and must stay: Criterion listings come from `record_catalog`, which uses the per-source `MAX(last_seen)` frontier rather than the TMDB refresh stamp.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_database.py tests/unit/test_availability.py -v`
Expected: PASS.

- [ ] **Step 6: Run the full gates**

Run: `uv run pytest && uv run ruff check . && uv run mypy && uv run python scripts/matching_benchmark.py --assert-dominance`
Expected: all pass; the matcher benchmark stays at or under the apple review ceiling of 6.0.

- [ ] **Step 7: Commit**

```bash
git add src/movie_brain/infrastructure/database.py src/movie_brain/application/availability.py tests/unit/
git commit -m "an unmapped provider was availability thrown away, not availability absent"
```

---

### Task 5: The ranking, as one pure function

**Files:**
- Create: `src/movie_brain/domain/watch.py`
- Test: `tests/unit/test_watch.py`

**Interfaces:**
- Consumes: `FilmView` (`services`, `criterion`, `departed`); `ServiceMeta` is NOT used here — the criterion option arrives as a plain dict so the domain keeps importing nothing but `domain`.
- Produces: `rank_key(option: dict[str, object]) -> tuple[int, int, int, str]` (ascending sort — best first); `watch_options(view: FilmView, criterion: dict[str, object] | None) -> list[dict[str, object]]`; `best_source(view: FilmView, criterion: dict[str, object] | None) -> dict[str, object] | None`. An option dict carries at least `{name, subscribed, kind, quality, has_apple_app}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_watch.py`:

```python
import pytest

from movie_brain.domain.models import FilmView
from movie_brain.domain.watch import best_source, rank_key, watch_options

CRITERION = {"name": "Criterion Channel", "subscribed": True, "kind": "svod", "quality": 5, "has_apple_app": True}


def svc(name, *, subscribed=True, kind="svod", quality=1, has_apple_app=False):
    return {"name": name, "subscribed": subscribed, "kind": kind, "quality": quality, "has_apple_app": has_apple_app}


def view(**kw) -> FilmView:
    base = dict(
        id=1, title="T", year=1950, director="D", url=None, language="French",
        imdb=None, rt=None, found=True, pending=False, leaving_date=None,
        first_seen="2026-01-01", my_rating=None,
    )
    base.update(kw)
    return FilmView(**base)


def test_subscribed_outranks_everything_else():
    v = view(services=[svc("Paid Better", subscribed=False, quality=9, has_apple_app=True), svc("Mine", quality=1)])
    assert best_source(v, None)["name"] == "Mine"


def test_quality_outranks_the_apple_app():
    v = view(services=[svc("Good Transfer", quality=5), svc("Has App", quality=1, has_apple_app=True)])
    assert best_source(v, None)["name"] == "Good Transfer"


def test_the_apple_app_breaks_a_tie_and_never_more():
    v = view(services=[svc("No App", quality=3), svc("App", quality=3, has_apple_app=True)])
    assert best_source(v, None)["name"] == "App"


def test_name_is_the_final_stable_tiebreak():
    v = view(services=[svc("Zed", quality=3), svc("Alpha", quality=3)])
    assert [o["name"] for o in watch_options(v, None)] == ["Alpha", "Zed"]


def test_monetization_tier_is_not_a_key():
    """C2: a free-with-ads service with a better transfer must be allowed to win."""
    v = view(services=[svc("Paid Flat", quality=2), svc("Free With Ads", quality=6)])
    assert best_source(v, None)["name"] == "Free With Ads"


def test_a_store_is_never_a_watch_option():
    v = view(services=[svc("Apple TV Store", kind="store", quality=9)])
    assert best_source(v, None) is None


def test_a_current_criterion_listing_joins_the_ranking():
    v = view(services=[svc("Tubi", quality=1)], criterion=True, departed=False)
    assert best_source(v, CRITERION)["name"] == "Criterion Channel"


def test_a_departed_criterion_listing_does_not():
    v = view(services=[svc("Tubi", quality=1)], criterion=True, departed=True)
    assert best_source(v, CRITERION)["name"] == "Tubi"


def test_a_film_with_no_criterion_listing_does_not_get_one():
    v = view(services=[svc("Tubi", quality=1)], criterion=False)
    assert best_source(v, CRITERION)["name"] == "Tubi"


def test_no_options_means_no_best_source():
    assert best_source(view(services=[], criterion=False), CRITERION) is None


def test_watch_options_does_not_mutate_the_view():
    original = svc("Tubi")
    v = view(services=[original], criterion=True, departed=False)
    watch_options(v, CRITERION)
    assert v.services == [original]
    assert len(v.services) == 1


def test_rank_key_is_ascending_best_first():
    assert rank_key(svc("A", quality=9)) < rank_key(svc("A", quality=1))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_watch.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'movie_brain.domain.watch'`.

- [ ] **Step 3: Write the ranking**

Create `src/movie_brain/domain/watch.py`:

```python
"""Ranking the places a film can be watched (design 2026-08-29-canon-best-source §5).

The best source is the first entry of a film's ranked svod set. Four keys decide it, in order:
subscribed (C3 — watch it once on something already paid for), quality (C7 via C9 — the owner's
hand-set per-service constant), an Apple TV app (C6 via C10 — a tiebreak, never a veto), and the
name, for stability.

The monetization tier is deliberately absent. C2 says flatrate, free and ads all mean "I can
watch this", so a free-with-ads service carrying a better transfer must be allowed to win.
`kind` keeps its other job — a `store` is a shop, not access, and is never a watch option.

`infrastructure/database.py::_SERVICES_SQL` orders `FilmView.services` on the same four keys;
`tests/unit/test_database.py::test_services_sql_order_matches_the_domain_ranking` is what keeps
the two in lockstep.
"""

from __future__ import annotations

from movie_brain.domain.models import FilmView

WatchOption = dict[str, object]


def rank_key(option: WatchOption) -> tuple[int, int, int, str]:
    """Ascending sort key — the smallest tuple is the BEST option, so `sorted` needs no reverse."""
    return (
        0 if option.get("subscribed") else 1,
        -int(option.get("quality") or 0),
        0 if option.get("has_apple_app") else 1,
        str(option.get("name") or ""),
    )


def watch_options(view: FilmView, criterion: WatchOption | None) -> list[WatchOption]:
    """Every svod place this film can be watched today, best first.

    `criterion` is the `movie_service` row for slug 'criterion', as a dict. Criterion is absent
    from `FilmView.services` because `_SERVICES_SQL` filters it out (`l.source != 'criterion'`) —
    the Criterion listing reaches the read model through `_VIEW_SQL`'s own LEFT JOIN instead — so
    a current listing is re-joined here rather than in SQL. Criterion covers 88 of the canon's
    200, so a ranking blind to it answers the wrong question for 44% of the set.
    """
    options: list[WatchOption] = [dict(s) for s in view.services if s.get("kind") == "svod"]
    if criterion is not None and view.criterion and not view.departed:
        options.append(dict(criterion))
    return sorted(options, key=rank_key)


def best_source(view: FilmView, criterion: WatchOption | None) -> WatchOption | None:
    """The single best place to watch this film, or None when nowhere streams it."""
    options = watch_options(view, criterion)
    return options[0] if options else None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_watch.py -v`
Expected: PASS, all 12.

- [ ] **Step 5: Run the full gates**

Run: `uv run pytest && uv run ruff check . && uv run mypy`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/movie_brain/domain/watch.py tests/unit/test_watch.py
git commit -m "best is a sort order over four keys, not a score nobody can explain"
```

---

### Task 6: `FilmView.best_source`, computed on every read

**Files:**
- Modify: `src/movie_brain/domain/models.py` (`FilmView`, after `criterion` at line 189)
- Modify: `src/movie_brain/infrastructure/database.py` (`_SERVICES_SQL` line 287, `_services_by_film` line 298, `_row_to_view` line 412, `list_views` line 2006, `get_view` line 2030)
- Test: `tests/unit/test_database.py`, `tests/web/test_api.py`

**Interfaces:**
- Consumes: `domain.watch.best_source`, `rank_key` (Task 5); `Repository.movie_service` (Task 1).
- Produces: `FilmView.best_source: dict[str, object] | None`, serialized into the dashboard's film JSON. `FilmView.services` entries gain `quality: int` and `has_apple_app: bool` alongside the existing `name`, `subscribed`, `kind`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_database.py`:

```python
def test_view_best_source_prefers_a_subscribed_service(repo, film_with_two_listings):
    repo.set_service_subscribed("max", True)
    repo.set_service_subscribed("mubi", False)
    view = repo.get_view(film_with_two_listings)
    assert view.best_source["name"] == "HBO Max"


def test_view_best_source_includes_a_current_criterion_listing(repo, criterion_film):
    repo.set_service_quality("criterion", 9)
    view = repo.get_view(criterion_film)
    assert view.best_source["name"] == "Criterion Channel"


def test_view_best_source_is_none_when_nothing_streams(repo, bare_film):
    assert repo.get_view(bare_film).best_source is None


def test_services_sql_order_matches_the_domain_ranking(repo, film_with_two_listings):
    """The lockstep guard: _SERVICES_SQL and domain/watch.py must agree, or the drawer's list
    and the badged winner would disagree with each other."""
    from movie_brain.domain.watch import rank_key

    repo.set_service_quality("max", 5)
    repo.set_service_quality("mubi", 9)
    repo.set_service_subscribed("mubi", True)
    services = repo.get_view(film_with_two_listings).services
    assert [s["name"] for s in services] == [s["name"] for s in sorted(services, key=rank_key)]
```

Build `film_with_two_listings`, `criterion_film` and `bare_film` as module-level fixtures in `tests/unit/test_database.py` using the helpers the file already uses to seed films and listings — a film with `max` and `mubi` listings stamped at today's date, a film with a current `criterion` listing, and a film with no listings at all.

Add to `tests/web/test_api.py`:

```python
def test_film_json_carries_best_source(client):
    films = client.get("/api/films").get_json()
    assert "best_source" in films[0]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_database.py -k best_source tests/web/test_api.py -k best_source -v`
Expected: FAIL — `AttributeError: 'FilmView' object has no attribute 'best_source'`.

- [ ] **Step 3: Add the field**

In `src/movie_brain/domain/models.py`, after `criterion` in `FilmView`:

```python
    # The single best place to watch this film today, or None when nowhere streams it —
    # {name, subscribed, kind, quality, has_apple_app}. Computed on every read by
    # domain/watch.py::best_source and NEVER denormalized onto films (design C11): a stored
    # winner would go stale the moment a merge re-points a listing, the same argument that
    # keeps the cross-list tally computed.
    best_source: dict[str, object] | None = None
```

- [ ] **Step 4: Carry the constants through the read model**

In `src/movie_brain/infrastructure/database.py`, replace `_SERVICES_SQL` and `_services_by_film`:

```python
_SERVICES_SQL = f"""
SELECT l.film_id, s.name, s.subscribed, s.kind, s.quality, s.has_apple_app FROM listings l
JOIN movie_service s ON s.slug = l.source
WHERE l.source != 'criterion'
  AND l.last_seen >= COALESCE(
      (SELECT value FROM meta WHERE key = '{TMDB_REFRESH_STAMP}'),
      (SELECT MAX(last_seen) FROM listings l2 WHERE l2.source = l.source))
ORDER BY l.film_id, s.subscribed DESC, s.quality DESC, s.has_apple_app DESC, s.name
"""


def _services_by_film(c: sqlite3.Connection) -> dict[int, list[dict[str, object]]]:
    out: dict[int, list[dict[str, object]]] = {}
    for r in c.execute(_SERVICES_SQL):
        out.setdefault(int(r["film_id"]), []).append(
            {
                "name": str(r["name"]),
                "subscribed": bool(r["subscribed"]),
                "kind": str(r["kind"]),
                "quality": int(r["quality"]),
                "has_apple_app": bool(r["has_apple_app"]),
            }
        )
    return out


def _criterion_option(c: sqlite3.Connection) -> dict[str, object] | None:
    """The `criterion` registry row as a watch option — read ONCE per view build, not per film."""
    row = c.execute(_SERVICE_SELECT + "WHERE slug = 'criterion'").fetchone()
    if row is None:
        return None
    return {
        "name": str(row["name"]),
        "subscribed": bool(row["subscribed"]),
        "kind": str(row["kind"]),
        "quality": int(row["quality"]),
        "has_apple_app": bool(row["has_apple_app"]),
    }
```

The `ORDER BY` drops `s.kind DESC` and must stay identical to `domain/watch.py::rank_key` — that is what the lockstep test asserts.

- [ ] **Step 5: Compute the winner in `_row_to_view`**

Add a keyword-only parameter and one line to `_row_to_view`:

```python
def _row_to_view(
    row: sqlite3.Row,
    services: list[dict[str, object]] | None = None,
    *,
    lists: list[dict[str, object]] | None = None,
    watchlisted: bool = False,
    new_on: list[dict[str, object]] | None = None,
    owned: bool = False,
    revisit: tuple[bool, str | None] = (False, None),
    audit: tuple[dict[str, object] | None, dict[str, object] | None] = (None, None),
    criterion_option: dict[str, object] | None = None,
) -> FilmView:
    view = FilmView(
        ...  # every existing argument unchanged
    )
    return replace(view, best_source=best_source(view, criterion_option))
```

Import `replace` from `dataclasses` and `best_source` from `movie_brain.domain.watch` at the top of the module. Building the view first and then filling `best_source` keeps the ranking reading the same `services` / `criterion` / `departed` the consumer will see, rather than a second copy of the arguments that could drift.

Then in `list_views`, read the option once and pass it to every row:

```python
            criterion_option = _criterion_option(c)
            return [
                _row_to_view(
                    r,
                    services.get(r["id"]),
                    lists=lists.get(r["id"]),
                    watchlisted=r["id"] in wl,
                    new_on=new_on.get(r["id"]),
                    owned=r["id"] in ow,
                    revisit=(r["id"] in rv, rv.get(r["id"])),
                    audit=au.get(r["id"], (None, None)),
                    criterion_option=criterion_option,
                )
                for r in rows
            ]
```

and add `criterion_option=_criterion_option(c),` to the `_row_to_view` call in `get_view`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_database.py tests/web/test_api.py -v`
Expected: PASS.

- [ ] **Step 7: Run the full gates**

Run: `uv run pytest && uv run ruff check . && uv run mypy && uv run python scripts/thumbprint_benchmark.py --assert && uv run python scripts/matching_benchmark.py --assert-dominance`
Expected: all pass; thumbprint stays at n=573 / WRONG=0 / 92.0% over 526.

- [ ] **Step 8: Commit**

```bash
git add src/movie_brain/domain/models.py src/movie_brain/infrastructure/database.py tests/unit/test_database.py tests/web/test_api.py
git commit -m "the winner is derived every read, because a stored one goes stale on the next merge"
```

---

### Task 7: Show the best source in the dashboard

**Files:**
- Modify: `src/movie_brain/web/static/app.js` (`rowHtml` line 130, `detailHtml` line 356)
- Test: `tests/web/test_dashboard.py` (the Playwright suite; create the file if it does not exist yet)

**Interfaces:**
- Consumes: `FilmView.best_source` (Task 6) as `f.best_source` in the film JSON.
- Produces: a `badge-watch` span on the row when `best_source.subscribed` is true, and a "Best source:" line in the drawer above "Also streaming on:".

- [ ] **Step 1: Write the failing Playwright test**

Add to `tests/web/test_dashboard.py`, following the file's existing seeded-live-server pattern:

```python
def test_drawer_names_the_best_source(page, live_server):
    page.goto(live_server.url)
    page.locator("tr[data-id] button.info").first.click()
    assert page.locator(".drawer .best-source").is_visible()
    assert "Best source:" in page.locator(".drawer .best-source").inner_text()


def test_a_reachable_film_carries_a_watch_badge(page, live_server):
    page.goto(live_server.url)
    assert page.locator("tr[data-id] .badge-watch").first.is_visible()
```

Seed the live-server fixture with at least one film holding a current listing on a subscribed service, so both assertions have a subject.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/web/test_dashboard.py -k "best_source or watch_badge" -v`
Expected: FAIL — the locators resolve to nothing.

(If Chromium is not installed: `uv run playwright install chromium`, once.)

- [ ] **Step 3: Badge the row**

In `src/movie_brain/web/static/app.js`, inside `rowHtml`, after the `badge-lists` clause:

```javascript
    const best = f.best_source;
    const watchBadge = best && best.subscribed
      ? ` <span class="badge-watch" title="Best source: ${esc(best.name)}">${esc(best.name)}</span>` : '';
```

and append `+ watchBadge` to the `title` expression.

- [ ] **Step 4: Name it in the drawer**

In `detailHtml`, add above the existing `streaming` line:

```javascript
    const bestLine = d.best_source
      ? `<p class="meta best-source">Best source: <b>${esc(d.best_source.name)}</b>${d.best_source.subscribed ? '' : ' (not subscribed)'}</p>`
      : '';
```

and insert `${bestLine}` into the returned template immediately before `${streaming ? ...}`.

- [ ] **Step 5: Style the badge**

In the dashboard stylesheet, beside the existing `.badge-lists` rule, add a `.badge-watch` rule using the same shape and a distinct hue.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/web/ -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/movie_brain/web/ tests/web/
git commit -m "the ordering is the reason, so show the winner rather than explain it"
```

---

### Task 8: Repair the `acquire` chip (spec §6)

**Files:**
- Modify: `src/movie_brain/domain/filters.py` (`acquisition_candidate`, line 69)
- Modify: `src/movie_brain/web/static/app.js` (`CHIP_PREDICATES.acquire`, line 45)
- Modify: `src/movie_brain/web/templates/index.html` (line 40)
- Test: `tests/unit/test_filters.py`

**Interfaces:**
- Consumes: `FilmView.best_source` (Task 6).
- Produces: `acquisition_candidate(view, today)` returns True for a film that is **not owned** and is canon-adjacent, regardless of rating or streaming availability. The chip key stays `acquire` — it is in the `CHIPS` tuple and in URL state, and renaming the key would break saved links. Only the button LABEL changes, to "Canon, not owned".

- [ ] **Step 1: Write the failing tests**

Replace the existing `acquisition_candidate` tests in `tests/unit/test_filters.py` with:

```python
def test_acquire_keeps_a_rated_film(): 
    """C5: 'a lot of them I already have seen once, I just want to re-watch them.'"""
    v = view(my_rating=8, metacritic=95, owned=False, criterion=False)
    assert acquisition_candidate(v, TODAY) is True


def test_acquire_keeps_a_streamable_film():
    """D1 reversed: a streamable canon film appears, badged, rather than being hidden."""
    v = view(metacritic=95, owned=False, criterion=False,
             services=[{"name": "Kanopy", "subscribed": True, "kind": "svod", "quality": 1, "has_apple_app": False}])
    assert acquisition_candidate(v, TODAY) is True


def test_acquire_keeps_a_film_on_the_criterion_channel():
    v = view(metacritic=95, owned=False, criterion=True, departed=False)
    assert acquisition_candidate(v, TODAY) is True


def test_acquire_drops_an_owned_film():
    v = view(metacritic=95, owned=True, criterion=False)
    assert acquisition_candidate(v, TODAY) is False


def test_acquire_drops_a_film_that_is_neither_canon_nor_acclaimed():
    v = view(metacritic=40, owned=False, criterion=False, lists=[])
    assert acquisition_candidate(v, TODAY) is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_filters.py -k acquire -v`
Expected: FAIL on the rated, streamable and Criterion cases — the current gate excludes all three.

- [ ] **Step 3: Rewrite the predicate**

In `src/movie_brain/domain/filters.py`:

```python
def acquisition_candidate(view: FilmView, _today: date) -> bool:
    """The canon shortlist I do not own yet.

    The working filter is "not yet BOUGHT", not "not yet seen" (C5): the owner has seen many of
    these once and wants to re-watch them, so a rating is not a reason to hide a film. Streaming
    availability is likewise not a reason (D1, reversed): a film streaming somewhere is still
    worth owning at $5 (C4), so it appears and the dashboard badges where to watch it instead of
    dropping it. `owned` is the only possession test, because possession is the only thing that
    settles the question.
    """
    if view.owned:
        return False
    return is_canon(view) or (view.metacritic is not None and view.metacritic >= TOP_MC)
```

- [ ] **Step 4: Mirror it in the JS and relabel the chip**

In `src/movie_brain/web/static/app.js`:

```javascript
    acquire: (f) => !f.owned
      && (isCanon(f) || (f.metacritic != null && f.metacritic >= state.cfg.canned_thresholds.top_mc)),
```

In `src/movie_brain/web/templates/index.html`, line 40:

```html
      <button class="chip" data-chip="acquire">Canon, not owned</button>
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_filters.py -v`
Expected: PASS. `test_chip_names_are_stable` must still pass — the `acquire` KEY is unchanged.

- [ ] **Step 6: Run the full gates**

Run: `uv run pytest && uv run ruff check . && uv run mypy`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/movie_brain/domain/filters.py src/movie_brain/web/ tests/unit/test_filters.py
git commit -m "the question was never whether I had seen it, only whether I own it"
```

---

### Task 9: Rehearse, then roll out to the live database

**Files:**
- Modify: `CLAUDE.md` (service registry bullet, `acquire` bullet, the new `services` verb in the command list)
- Create: `.claude/rules/watch.md` (path-scoped contract for `domain/watch.py`, `application/availability.py`, the service registry)

**Interfaces:**
- Consumes: everything above.
- Produces: a live DB at schema v17 with the owner's quality, Apple-app and subscription values set, and refreshed provider data covering all three buckets.

**This is the only task that touches live data. Every write step below is gated on the owner seeing the rehearsal result first.**

- [ ] **Step 1: Rehearse the migration on a scratch copy**

```bash
export SCRATCH="$(mktemp -d)"
cp ~/.config/movie-brain/movie-brain.db "$SCRATCH/movie-brain.db"
MOVIE_BRAIN_CONFIG_DIR="$SCRATCH" uv run movie-brain migrate
MOVIE_BRAIN_CONFIG_DIR="$SCRATCH" uv run movie-brain migrate --apply
MOVIE_BRAIN_CONFIG_DIR="$SCRATCH" uv run movie-brain services list
```
Expected: the dry run lists 017 as pending; `--apply` writes a backup into `$SCRATCH/backups/` and applies it; `services list` prints eight services, each at `quality 1` / `apple-app no`.

- [ ] **Step 2: Rehearse a provider refresh and count what the widened buckets add**

```bash
MOVIE_BRAIN_CONFIG_DIR="$SCRATCH" sqlite3 "$SCRATCH/movie-brain.db" \
  "SELECT COUNT(*) AS listings_before FROM listings; DELETE FROM meta WHERE key = 'tmdb_providers_refreshed_at';"
MOVIE_BRAIN_CONFIG_DIR="$SCRATCH" uv run movie-brain sync
MOVIE_BRAIN_CONFIG_DIR="$SCRATCH" sqlite3 "$SCRATCH/movie-brain.db" \
  "SELECT COUNT(*) FROM listings; SELECT slug, name FROM movie_service WHERE subscribed = 0 ORDER BY slug;"
```
Deleting the refresh stamp is what forces the full pass (~4,600 TMDB calls) to re-read every film under the new buckets; without it the new `free`/`ads` rows would trickle in over the following week. Expected: a substantially larger `listings` count and a list of newly auto-registered services including `kanopy`, `tubi-tv`, `fawesome`, `plex-channel` and `hoopla`.

- [ ] **Step 3: Show the owner the rehearsal result and STOP**

Report: listings before and after, the auto-registered service list, and the `movie-brain services list` output. **Do not proceed to Step 4 without an explicit yes.**

- [ ] **Step 4: Apply the migration live**

```bash
uv run movie-brain migrate
uv run movie-brain migrate --apply
```
Expected: a backup lands in `~/.config/movie-brain/backups/`, and the DB reaches v17.

- [ ] **Step 5: Set the owner's subscriptions**

Run one `services subscribe` per service the owner names — §4 records Criterion, Kanopy, Tubi and Fawesome, but confirm the list before running it, because the services only exist after Step 6's sync auto-registers them. If a slug is not yet registered, run Step 6 first and return here.

```bash
uv run movie-brain services subscribe kanopy 1
uv run movie-brain services subscribe tubi-tv 1
uv run movie-brain services subscribe fawesome 1
```

- [ ] **Step 6: Refresh providers live**

```bash
sqlite3 ~/.config/movie-brain/movie-brain.db "DELETE FROM meta WHERE key = 'tmdb_providers_refreshed_at';"
uv run movie-brain sync
```

- [ ] **Step 7: Set the quality and Apple-app constants**

Ask the owner for a value per service rather than inventing one — this is the judgement the whole feature rests on, and C9 exists precisely because no source can supply it. Then run one `services quality` and one `services apple` per service.

- [ ] **Step 8: Write the rule file**

Create `.claude/rules/watch.md` with a `paths:` frontmatter block naming `src/movie_brain/domain/watch.py`, `src/movie_brain/application/availability.py` and `src/movie_brain/infrastructure/database.py`, recording: the four ranking keys and their order; that the monetization tier is deliberately not a key (C2); that Criterion is re-joined in `watch_options` because `_SERVICES_SQL` filters it out; that `_SERVICES_SQL`'s `ORDER BY` and `rank_key` must stay in lockstep and which test guards that; that `movie-brain services` is the only writer of `quality`, `has_apple_app` and `subscribed`, and that `register_provider` must never update an existing `movie_service` row; and that `best_source` is computed on every read and must never be denormalized onto `films`.

- [ ] **Step 9: Update `CLAUDE.md`**

Add `movie-brain services …` to the command list; extend the `movie_service` bullet with the two new columns and their single writer; replace the `acquire` bullet's description with the new gate; and add a bullet for `best_source`.

- [ ] **Step 10: Commit**

```bash
git add CLAUDE.md .claude/rules/watch.md
git commit -m "record the contract the next session will otherwise have to re-derive"
```

---

## Self-Review

**Spec coverage.** §3's two gaps → Tasks 3 and 4. §4's record-every-provider, auto-registration and migration 017 → Tasks 1 and 4. §5's four keys, the two new columns, the single writer verb and the synthetic Criterion entry → Tasks 1, 2, 5 and 6. §5's "the ordering IS the reason" → Task 7. §5.1 is a record of rejected options and needs no task. §6's `acquire` repair and the D1 reversal → Task 8. C11 (computed, never stored) → Task 6. C12 (no cadence change) → no task by design; the only operational consequence is Task 9's refresh-stamp deletion. §8's gates appear in Global Constraints and in each task's gate step.

**Not covered, deliberately.** §7's out-of-scope list — non-US regions, rental prices, CheapCharts, `canon_score` changes, BFI Player, any portfolio feature, any second-source quality lookup.

**Open judgement calls the owner can overrule in one line.** The chip's new LABEL ("Canon, not owned") is my choice, not the spec's — the spec says only that "Worth buying" is wrong. The `services subscribe` subcommand is not named in the spec either, but §4 requires the owner to flip `subscribed` and no verb exists for it today; the alternative is hand-written SQL against the live DB.
