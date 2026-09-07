# Drawer Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the film drawer so it answers, in order, what the film is (TMDB overview, full cast and writers from `film_credit`), how good it is (my rating, IMDb/Metacritic/RT, lists with the canon score), where to watch it (one link that lands on the service's own title search), and where else it is — with every person name a one-click filter on the table.

**Architecture:** Two pure domain additions (`watch_url` in `domain/watch.py`, `domain/credits.py` shaping `film_credit` rows into `FilmCredits`), one inert migration (`movie_service.search_url`, owner-set through a new `services url` verb), a read-model change that resolves `best_source.url` at view-build time while keeping URLs off the list payload, a detail-only extension of `/api/films/<id>` (`credits`, `overview`, `tmdb_url`), and a rewritten `detailHtml` in `app.js` plus one delegated click handler for person links. Nothing touches identity, keying, matching, the table, chips or the list picker.

**Tech Stack:** Python 3.12, SQLite (stdlib), Flask, Typer + Rich, pytest, Playwright (Chromium), vanilla JS.

**Spec:** `docs/superpowers/specs/2026-09-07-drawer-redesign-design.md` (D1–D10, §3–§7). Mockup: `.superpowers/brainstorm/51519-1788804473/content/drawer-layout-v3.html` (git-ignored, on the owner's machine).

## Global Constraints

- **Schema change = new numbered migration** `migrations/021_service_search_url.sql`, wrapped in `BEGIN/COMMIT`, inserting its own `schema_version` row (`INSERT INTO schema_version (version) VALUES (21);`). Never edit an applied migration. `movie-brain migrate --apply` is the only path that advances the live DB, and it is a separate owner yes (Task 7).
- **Nothing here is identity.** No `KEY_AUTHORITY`, no `external_ids` write, no change to keying, matching, the thumbprint resolver or `films.guid`. `person` stays a join.
- **`movie-brain services url` is the ONLY writer of `movie_service.search_url`**, exactly as `quality`/`has_apple_app`/`subscribed` have one writer each. `register_provider` keeps its two `INSERT OR IGNORE` statements and never names the column.
- **The list payload does not grow (spec D10).** `/api/films` entries' `services` dicts keep exactly `{name, subscribed, kind, quality, has_apple_app}`; `best_source` gains `url` and nothing else; `credits`, `overview` and `tmdb_url` ride ONLY on `/api/films/<id>`.
- **`best_source` stays computed on every read, never stored** (watch.md C11). `watch_url` is called at view-build time; nothing is written.
- **The `_SERVICES_SQL` ORDER BY stays in lockstep with `domain/watch.py::rank_key`** — this plan adds columns to its SELECT list and touches nothing in its ORDER BY. `test_services_sql_order_matches_the_domain_ranking` must keep passing.
- **Drawer rules that must survive** (memory `dashboard-ui-preferences`): a person link touches no chip, column filter, language or list; no glyphs or tooltips added to explain state; Clear still resets everything.
- **Verbatim copy:** the watch line reads `Watch on <name> ↗` (with ` (not subscribed)` after the name when unsubscribed) or `Owned on Apple TV ↗`; the TMDB link reads `TMDB ↗`; the cast disclosure reads `⋯ N more` closed and `⋯ fewer` open; the lists line ends `· canon score N.N`.
- **Markdown prose is never hard-wrapped** (owner's global rule) — applies to Task 7's doc edits. Repair with `~/code/praxis-workspace/praxis-halo/bin/unwrap-md <file>`.
- **Commit messages:** one line, the *why*, plus the two trailers: `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01QTtV1aGf3Fe1Gkuvov7WJh`.
- **`uv run` only.** Never bare `python`/`pytest`. Full gate before every commit: `uv run pytest -q && uv run ruff check . && uv run mypy`.
- Work on branch `feature/drawer-redesign` off a clean, current `main`.
- **Every live-DB step is a separate owner yes** (`one-at-a-time`): `migrate --apply` and each `services url` in Task 7.

---

## File structure

| File | Responsibility in this plan |
|------|-----------------------------|
| `src/movie_brain/domain/models.py` | `ServiceMeta.search_url`; new `CastEntry`, `WriterEntry`, `FilmCredits` (+ `to_dict`) |
| `src/movie_brain/domain/watch.py` | `watch_url(option, title)` — template → listing → None |
| `src/movie_brain/domain/credits.py` (new) | `writer_label`, `build_credits` — pure shaping of credit rows |
| `migrations/021_service_search_url.sql` (new) | the inert column |
| `src/movie_brain/infrastructure/database.py` | `_SERVICE_SELECT`/`_row_to_service` read the column; `set_service_search_url`; `_SERVICES_SQL` + `_services_by_film` + `_service_option` carry the two private URL keys; `_row_to_view` resolves `best_source.url` and strips them; `film_credits`, `overview_for` |
| `src/movie_brain/cli.py` | `services url SLUG [TEMPLATE]`; `_service_line` shows a set template |
| `src/movie_brain/web/app.py` | detail endpoint adds `credits`, `overview`, `tmdb_url` |
| `src/movie_brain/web/static/app.js` | `detailHtml` rewritten to spec §3; `castHtml`, `writerHtml`, `personLink`; the `a.person` click handler |
| `src/movie_brain/web/static/app.css` | 760px drawer, ratings block, person links, cast disclosure columns |
| `tests/unit/test_watch.py`, `tests/unit/test_credits.py` (new), `tests/unit/test_database.py`, `tests/unit/test_cli.py`, `tests/web/test_api.py`, `tests/web/conftest.py`, `tests/web/test_dashboard.py` | tests per task |
| `CLAUDE.md`, `.claude/rules/watch.md`, `docs/backlog.md` | Task 7 |

## Fixture arithmetic — read before Tasks 5 and 6

The Playwright seed (`tests/web/conftest.py`) changes in Task 5. Every expected string below follows from these rows; if a test disagrees with this table, the test is wrong.

**Alpha** (owned, Criterion, English, imdb 8.5, rt 95, mc 92, my rating 9, lists backlog-10 / sight-sound-2022 #2 / cahiers-100 #3) gets credits: overview `A private eye in the Sternwood house.` (already there), eight cast rows in billing order — Humphrey Bogart as Philip Marlowe, Lauren Bacall as Vivian Rutledge, John Ridgely as Eddie Mars, Martha Vickers as Carmen, Louis Jean Heydt as Joe Brody, Charles Waldron as The General, Regis Toomey as Bernie Ohls, Sonia Darrin as Agnes (uncredited) — and crew Howard Hawks (Director), Leigh Brackett (Screenplay), Raymond Chandler (Novel). None of the new names shares a trigram with `bogrt`/`bogxrtq` (the correction tests) or contains `alpha`/`hawks`/`marlowe` (the count tests), so every existing search count is unchanged.

- Inline cast: `Humphrey Bogart, Lauren Bacall, John Ridgely, Martha Vickers, Louis Jean Heydt, Charles Waldron`; disclosure `⋯ 2 more`; expanded list of 8, first `Humphrey Bogart as Philip Marlowe`, last `Sonia Darrin as Agnes (uncredited)`.
- Writer row: `Leigh Brackett, Raymond Chandler (novel)`.
- Director link text `Ann` (Criterion's director string, what the table shows); its query `director: "Howard Hawks"` (the TMDB credit) matches Alpha and Bravo → count 2; with the Owned chip on → 1.
- Critics line: `IMDb 8.5 · Metacritic 92 · Rotten Tomatoes 95%`.
- Canon score: Backlog Ten is unordered, trust 7 → 7.0; Sight & Sound 2022 has 2 entries (Charlie #1, Alpha #2), trust 5 → 5 × (1 − (2−1)/2) = 2.5; cahiers-100 has 2 entries (Charlie #1, Alpha #3), trust 1 → 1 × (1 − (3−1)/2) = 0. **Total 9.5.**
- Watch line: owned → `Owned on Apple TV ↗`, href `https://tv.apple.com/search?term=Alpha` (no template on `apple-tv-store` in the seed, so the hardcoded fallback).
- Links row: `Open on Criterion ↗` (`https://c/alpha`), `TMDB ↗` (`https://www.themoviedb.org/movie/910`), `CheapCharts ↗`.

**Bravo** (unowned, five svod services, best source Apple TV+ by name tiebreak): the seed sets `apple-tv-plus`'s template to `https://tv.apple.com/search?term={title}` → `Watch on Apple TV+ ↗`, href `https://tv.apple.com/search?term=Bravo`.

**Charlie** (Criterion only, no template on `criterion`): `Watch on Criterion Channel ↗`, href `https://c/charlie` (the listing URL fallback).

**Echo** (never enriched): its OMDb payload gains `"Plot":"An echo.","Actors":"Ed Actor, Flo Actor","Writer":"Gus Writer (screenplay)"` → summary `An echo.` (OMDb fallback), cast `Ed Actor, Flo Actor` with bare queries (`actor: Ed Actor`), writer `Gus Writer (screenplay)` with query `writer: Gus Writer`, no disclosure, no `a.tmdb-link`.

**Golf** (discovery film, metacritic slug, no tmdb id, no listings): no watch line, no `a.tmdb-link`, no Metacritic link anywhere.

---

### Task 0: Branch

- [ ] **Step 1: Create the branch off a clean, current `main`**

```bash
git status -sb          # expect: ## main...origin/main, clean
git checkout -b feature/drawer-redesign
```

---

### Task 1: Pure domain — `watch_url`, `domain/credits.py`, the credit models

**Files:**
- Modify: `src/movie_brain/domain/models.py` (after `ServiceMeta`, ~line 200)
- Modify: `src/movie_brain/domain/watch.py` (append)
- Create: `src/movie_brain/domain/credits.py`
- Test: `tests/unit/test_watch.py` (append), `tests/unit/test_credits.py` (new)

**Interfaces:**
- Produces: `watch_url(option: WatchOption, title: str) -> str | None`; `writer_label(name: str, jobs: Sequence[str]) -> str`; `build_credits(rows: Iterable[tuple[str, str, str, str, str]]) -> FilmCredits | None` where a row is `(kind, name, character, job, department)`; `FilmCredits(director, cast, writers).to_dict()` → `{"director": str|None, "cast": [{"name","character"}], "writers": [{"name","label"}]}`; `ServiceMeta.search_url: str | None = None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_watch.py`:

```python
from movie_brain.domain.watch import watch_url


def test_watch_url_fills_the_template_with_the_encoded_title():
    assert watch_url({"search_url": "https://play.max.com/search?q={title}"}, "Two Listings") == "https://play.max.com/search?q=Two%20Listings"
    assert watch_url({"search_url": "https://x/s?q={title}"}, "Fast & Furious") == "https://x/s?q=Fast%20%26%20Furious"


def test_watch_url_falls_back_to_the_listing_url():
    assert watch_url({"search_url": None, "listing_url": "https://c/alpha"}, "Alpha") == "https://c/alpha"
    assert watch_url({"search_url": "", "listing_url": "https://c/alpha"}, "Alpha") == "https://c/alpha"


def test_watch_url_is_none_when_nothing_is_known():
    assert watch_url({"name": "Kanopy"}, "Alpha") is None
```

Create `tests/unit/test_credits.py`:

```python
from movie_brain.domain.credits import build_credits, writer_label
from movie_brain.domain.models import CastEntry, WriterEntry


def test_screenplay_and_writer_print_bare():
    assert writer_label("Leigh Brackett", ["Screenplay"]) == "Leigh Brackett"
    assert writer_label("Ann", ["Writer"]) == "Ann"
    assert writer_label("William Faulkner", ["Story", "Screenplay"]) == "William Faulkner"


def test_other_jobs_are_tagged_lowercase_deduplicated_and_joined():
    assert writer_label("Raymond Chandler", ["Novel"]) == "Raymond Chandler (novel)"
    assert writer_label("X", ["Story", "Adaptation", "Story"]) == "X (story/adaptation)"
    assert writer_label("Y", [""]) == "Y"


ROWS = [
    ("cast", "Humphrey Bogart", "Philip Marlowe", "", ""),
    ("cast", "Lauren Bacall", "", "", ""),
    ("crew", "Howard Hawks", "", "Director", "Directing"),
    ("crew", "Leigh Brackett", "", "Screenplay", "Writing"),
    ("crew", "Raymond Chandler", "", "Novel", "Writing"),
    ("crew", "William Faulkner", "", "Story", "Writing"),
    ("crew", "William Faulkner", "", "Screenplay", "Writing"),
    ("crew", "Sid Hickox", "", "Director of Photography", "Camera"),
]


def test_build_credits_shapes_director_cast_and_writers_in_order():
    fc = build_credits(ROWS)
    assert fc is not None
    assert fc.director == "Howard Hawks"
    assert fc.cast == (CastEntry("Humphrey Bogart", "Philip Marlowe"), CastEntry("Lauren Bacall", ""))
    # one entry per person, first-seen order, Faulkner's Story folded into his bare Screenplay label
    assert fc.writers == (
        WriterEntry("Leigh Brackett", "Leigh Brackett"),
        WriterEntry("Raymond Chandler", "Raymond Chandler (novel)"),
        WriterEntry("William Faulkner", "William Faulkner"),
    )


def test_build_credits_is_none_without_rows():
    assert build_credits([]) is None


def test_to_dict_is_the_api_shape():
    fc = build_credits(ROWS[:1])
    assert fc is not None
    assert fc.to_dict() == {
        "director": None,
        "cast": [{"name": "Humphrey Bogart", "character": "Philip Marlowe"}],
        "writers": [],
    }
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/unit/test_watch.py tests/unit/test_credits.py -q`
Expected: ImportError on `watch_url` / `movie_brain.domain.credits`.

- [ ] **Step 3: Models**

In `src/movie_brain/domain/models.py`, add `search_url: str | None = None` as the LAST field of `ServiceMeta` (after `has_apple_app`), with the comment `# title-search template with a {title} placeholder; migration 021, written only by 'services url'`. Then add, directly after the `ServiceMeta` class:

```python
@dataclass(frozen=True)
class CastEntry:
    name: str
    character: str  # '' when TMDB lists no role


@dataclass(frozen=True)
class WriterEntry:
    name: str
    label: str  # domain/credits.py::writer_label — the name alone, or "Name (novel)"


@dataclass(frozen=True)
class FilmCredits:
    """The drawer's credit rows for one film, built by domain/credits.py::build_credits from
    `film_credit` rows. Detail-only: never part of FilmView or the list payload (drawer
    redesign spec D10)."""

    director: str | None
    cast: tuple[CastEntry, ...]
    writers: tuple[WriterEntry, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "director": self.director,
            "cast": [{"name": c.name, "character": c.character} for c in self.cast],
            "writers": [{"name": w.name, "label": w.label} for w in self.writers],
        }
```

- [ ] **Step 4: `watch_url`**

In `src/movie_brain/domain/watch.py` add `from urllib.parse import quote` to the imports and append:

```python
def watch_url(option: WatchOption, title: str) -> str | None:
    """Where "Watch on <name>" lands (drawer-redesign spec D6/D7).

    The service's own title search when the registry holds a `search_url` template (owner-set,
    `movie-brain services url`), else the listing's stored URL — Criterion's direct page, or
    TMDB's watch page for a provider-fed service, which is one click from the service — else
    nothing. The title is percent-encoded with no safe characters, so "Two Listings" fills as
    Two%20Listings and an ampersand cannot split the query string.
    """
    template = option.get("search_url")
    if template:
        return str(template).replace("{title}", quote(title, safe=""))
    listing = option.get("listing_url")
    return str(listing) if listing else None
```

- [ ] **Step 5: `domain/credits.py`**

```python
"""Credit rows for the drawer (drawer-redesign spec §3, D2/D3).

Pure: takes the `film_credit` rows the repository reads — cast first in billing order, then
crew in TMDB's order — and shapes them into the three rows the drawer prints. Nothing here
is identity: `person` is a join, never a KEY_AUTHORITY.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from movie_brain.domain.models import CastEntry, FilmCredits, WriterEntry

BARE_JOBS = frozenset({"Screenplay", "Writer"})
WRITING_DEPARTMENT = "Writing"
DIRECTOR_JOB = "Director"

CreditRow = tuple[str, str, str, str, str]  # (kind, name, character, job, department)


def writer_label(name: str, jobs: Sequence[str]) -> str:
    """"Leigh Brackett" for a screenwriter, "Raymond Chandler (novel)" for anyone else (D3).

    A person credited with Screenplay or Writer prints bare whatever else they did; other jobs
    are lowercased, deduplicated in first-seen order and joined with "/"."""
    if any(j in BARE_JOBS for j in jobs):
        return name
    tagged = "/".join(dict.fromkeys(j.lower() for j in jobs if j))
    return f"{name} ({tagged})" if tagged else name


def build_credits(rows: Iterable[CreditRow]) -> FilmCredits | None:
    """Shape ordered credit rows into director / cast / writers.

    Cast keeps its billing order; the director is the first `Director` crew row; writers are
    every Writing-department row, ONE entry per person in first-seen order, labelled by
    `writer_label`. None when there are no rows at all — the drawer then falls back to OMDb's
    comma-separated strings.
    """
    cast: list[CastEntry] = []
    director: str | None = None
    writer_jobs: dict[str, list[str]] = {}
    seen = False
    for kind, name, character, job, department in rows:
        seen = True
        if kind == "cast":
            cast.append(CastEntry(name, character))
        elif job == DIRECTOR_JOB and director is None:
            director = name
        elif department == WRITING_DEPARTMENT:
            writer_jobs.setdefault(name, []).append(job)
    if not seen:
        return None
    writers = tuple(WriterEntry(n, writer_label(n, jobs)) for n, jobs in writer_jobs.items())
    return FilmCredits(director, tuple(cast), writers)
```

- [ ] **Step 6: Run the tests, lint, types**

Run: `uv run pytest tests/unit/test_watch.py tests/unit/test_credits.py -q && uv run ruff check . && uv run mypy`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/movie_brain/domain/models.py src/movie_brain/domain/watch.py src/movie_brain/domain/credits.py tests/unit/test_watch.py tests/unit/test_credits.py
git commit -m "a watch link and a writer label are rules, so they live in the domain before anything reads them

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01QTtV1aGf3Fe1Gkuvov7WJh"
```

---

### Task 2: Migration 021, `set_service_search_url`, `services url`

**Files:**
- Create: `migrations/021_service_search_url.sql`
- Modify: `src/movie_brain/infrastructure/database.py` (`_SERVICE_SELECT` ~line 339, `_row_to_service` ~385, `_set_service_column` ~1865 and the setters after it)
- Modify: `src/movie_brain/cli.py` (`_service_line` ~409, the `services` group after `services_subscribe_cmd` ~485)
- Test: `tests/unit/test_database.py` (append), `tests/unit/test_cli.py` (append after the services tests ~line 825)

**Interfaces:**
- Consumes: `ServiceMeta.search_url` (Task 1).
- Produces: `Repository.set_service_search_url(slug: str, template: str | None) -> bool` (False = unknown slug; `None` or `""` stores NULL); `Repository.movie_service(slug).search_url`; CLI `services url SLUG [TEMPLATE]` where `-` clears.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_database.py`:

```python
def test_migration_021_adds_the_search_url_to_the_registry(repo):
    with sqlite3.connect(repo.db_path) as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(movie_service)")}
        assert "search_url" in cols
        assert c.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] >= 21
    assert repo.movie_service("max").search_url is None  # inert by default


def test_set_service_search_url_round_trips_and_clears(repo):
    assert repo.set_service_search_url("max", "https://play.max.com/search?q={title}")
    assert repo.movie_service("max").search_url == "https://play.max.com/search?q={title}"
    assert repo.set_service_search_url("max", None)
    assert repo.movie_service("max").search_url is None
    assert repo.set_service_search_url("max", "https://play.max.com/search?q={title}")
    assert repo.set_service_search_url("max", "")  # empty clears too
    assert repo.movie_service("max").search_url is None
    assert not repo.set_service_search_url("no-such-service", "https://x/{title}")


def test_register_provider_never_touches_a_search_url(repo):
    """The nightly sync calls register_provider for every provider TMDB reports; the owner's
    template must survive it exactly as quality/has_apple_app/subscribed do."""
    repo.set_service_search_url("mubi", "https://mubi.com/search?q={title}")
    assert repo.register_provider(11, "MUBI") == "mubi"
    assert repo.movie_service("mubi").search_url == "https://mubi.com/search?q={title}"
```

Append to `tests/unit/test_cli.py`:

```python
def test_services_url_sets_shows_lists_and_clears(config_dir):
    tpl = "https://play.max.com/search?q={title}"
    assert runner.invoke(app, ["services", "url", "max", tpl]).exit_code == 0
    assert tpl in runner.invoke(app, ["services", "url", "max"]).output
    assert tpl in runner.invoke(app, ["services", "list"]).output
    assert runner.invoke(app, ["services", "url", "max", "-"]).exit_code == 0
    assert "falls back" in runner.invoke(app, ["services", "url", "max"]).output


def test_services_url_requires_the_title_placeholder(config_dir):
    r = runner.invoke(app, ["services", "url", "max", "https://play.max.com/search"])
    assert r.exit_code == 2
    assert "{title}" in r.output


def test_services_url_unknown_slug_exits_2(config_dir):
    assert runner.invoke(app, ["services", "url", "nope", "https://x/{title}"]).exit_code == 2
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/unit/test_database.py -k "search_url or migration_021" tests/unit/test_cli.py -k services_url -q`
Expected: the migration test fails on the missing column; the others on missing attributes / `No such command 'url'`.

- [ ] **Step 3: The migration**

Create `migrations/021_service_search_url.sql`:

```sql
-- The drawer's one watch link (drawer-redesign spec D6/D7): "Watch on HBO Max ↗" must land on
-- HBO Max, and a TMDB-fed listing only ever holds themoviedb.org's watch page for the film, never
-- a service URL. `search_url` is the service's own title-search template with a `{title}`
-- placeholder — an owner-set registry fact like `quality` and `has_apple_app` (migration 017),
-- written by `movie-brain services url` and by nothing else. NULL default so the feature ships
-- inert: with no template the link falls back to the listing's stored URL.
BEGIN;
ALTER TABLE movie_service ADD COLUMN search_url TEXT;
INSERT INTO schema_version (version) VALUES (21);
COMMIT;
```

- [ ] **Step 4: Repository**

In `database.py`:

```python
_SERVICE_SELECT = "SELECT slug, name, kind, subscribed, region, quality, has_apple_app, search_url FROM movie_service "
```

In `_row_to_service` add `search_url=row["search_url"],` (SQLite returns `None` for NULL; the column is TEXT so no cast is needed — but write `str(row["search_url"]) if row["search_url"] else None` for mypy).

Widen `_set_service_column`'s signature to `value: int | str | None` and add after `set_service_subscribed`:

```python
    def set_service_search_url(self, slug: str, template: str | None) -> bool:
        """The ONLY writer of `movie_service.search_url` (migration 021). None or "" clears it.
        False when the slug is unknown."""
        return self._set_service_column(slug, "search_url", template or None)
```

- [ ] **Step 5: CLI**

In `cli.py`, change `_service_line` to append the template when one is set:

```python
def _service_line(m: ServiceMeta) -> str:
    line = (
        f"{m.slug:<24} quality {m.quality}   "
        f"apple-app {'yes' if m.has_apple_app else 'no':<3}   "
        f"subscribed {'yes' if m.subscribed else 'no':<3}   {m.kind:<5} {m.name}"
    )
    return f"{line}   url {m.search_url}" if m.search_url else line
```

In `services_list_cmd`, print each line with `console.print(_service_line(m), soft_wrap=True)` — Rich folds long words at 80 columns in a non-TTY (the test runner), and a folded URL would break the substring assertions. Add after `services_subscribe_cmd`:

```python
@services_app.command("url")
def services_url_cmd(
    slug: Annotated[str, typer.Argument(help="Service slug (e.g. max).")],
    template: Annotated[
        str | None, typer.Argument(help="Title-search URL with a {title} placeholder; `-` clears it.")
    ] = None,
) -> None:
    """Show or set one service's title-search template — where the drawer's "Watch on <service>"
    link lands. With no template the link falls back to the listing's stored URL (Criterion's
    own page; TMDB's watch page for provider-fed services).

    Nothing but this verb writes `movie_service.search_url`, so provider auto-registration
    during sync can never reset it."""
    repo = _repo()
    meta = _service_or_exit(repo, slug)
    if template is None:
        console.print(_service_line(meta), soft_wrap=True)
        if not meta.search_url:
            console.print("  url (none — the watch link falls back to the listing URL)")
        return
    if template == "-":
        repo.set_service_search_url(slug, None)
        console.print(f"{slug}: url cleared")
        return
    if "{title}" not in template:
        err.print("the template must contain {title} — e.g. https://play.max.com/search?q={title}", soft_wrap=True)
        raise typer.Exit(2)
    repo.set_service_search_url(slug, template)
    console.print(f"{slug}: url set to {template}", soft_wrap=True)
```

Rich treats `[...]` as markup; braces are plain text, so `{title}` prints as typed.

- [ ] **Step 6: Run the tests, lint, types**

Run: `uv run pytest tests/unit/test_database.py tests/unit/test_cli.py -q && uv run ruff check . && uv run mypy`
Expected: all pass (the whole of both files, not just the new tests — `_SERVICE_SELECT` feeds every registry read).

- [ ] **Step 7: Commit**

```bash
git add migrations/021_service_search_url.sql src/movie_brain/infrastructure/database.py src/movie_brain/cli.py tests/unit/test_database.py tests/unit/test_cli.py
git commit -m "where a service's search page lives is a registry fact, so it gets the fourth owner column and its own verb

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01QTtV1aGf3Fe1Gkuvov7WJh"
```

---

### Task 3: `best_source.url` in the read model, URLs kept off `services`

**Files:**
- Modify: `src/movie_brain/infrastructure/database.py` (`_SERVICES_SQL` ~313, `_services_by_film` ~324, `_service_option` ~342, `_row_to_view` ~488–530)
- Test: `tests/unit/test_database.py` (append after `test_services_sql_order_matches_the_domain_ranking`), `tests/web/test_api.py` (append)

**Interfaces:**
- Consumes: `watch_url` (Task 1).
- Produces: `FilmView.best_source` dict = `{name, subscribed, kind, quality, has_apple_app, url}`; `FilmView.services` entries unchanged; module constant `_PRIVATE_OPTION_KEYS` and helper `_public_option`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_database.py`:

```python
def test_best_source_url_fills_the_registry_template(repo, film_with_two_listings):
    repo.set_service_subscribed("max", True)
    repo.set_service_subscribed("mubi", False)
    repo.set_service_search_url("max", "https://play.max.com/search?q={title}")
    assert repo.get_view(film_with_two_listings).best_source["url"] == "https://play.max.com/search?q=Two%20Listings"


def test_best_source_url_falls_back_to_the_listing_url(repo, film_with_two_listings):
    repo.set_service_subscribed("max", True)
    repo.set_service_subscribed("mubi", False)
    assert repo.get_view(film_with_two_listings).best_source["url"] == "https://tmdb/w/max"


def test_criterion_best_source_lands_on_the_channel_page(repo, criterion_film):
    """Criterion is re-joined at the ranking site (watch.md); its landing page is the film's own
    listing URL from _VIEW_SQL, not a template."""
    assert repo.get_view(criterion_film).best_source["url"] == "https://c/criterion-film"


def test_owned_best_source_url_follows_the_store_template(repo, film_with_two_listings):
    repo.mark_owned(film_with_two_listings, date(2026, 8, 29))
    assert repo.get_view(film_with_two_listings).best_source["url"] is None
    repo.set_service_search_url("apple-tv-store", "https://tv.apple.com/search?term={title}")
    assert repo.get_view(film_with_two_listings).best_source["url"] == "https://tv.apple.com/search?term=Two%20Listings"


def test_services_entries_never_carry_urls(repo, film_with_two_listings):
    """Spec D10: 14,717 listings × a URL would put ~1 MB on the list payload."""
    view = repo.get_view(film_with_two_listings)
    assert view.services
    assert all(set(s) == {"name", "subscribed", "kind", "quality", "has_apple_app"} for s in view.services)
    assert set(view.best_source) == {"name", "subscribed", "kind", "quality", "has_apple_app", "url"}
    listed = next(v for v in repo.list_views("criterion") if v.id == film_with_two_listings)
    assert all(set(s) == {"name", "subscribed", "kind", "quality", "has_apple_app"} for s in listed.services)
    assert listed.best_source["url"] == view.best_source["url"]
```

Append to `tests/web/test_api.py` (after `test_film_json_carries_best_source`):

```python
def test_list_payload_carries_the_watch_url_only_on_best_source(client, repo):
    trio = repo.film_id_by_key("trio (1950)")
    repo.record_listing(trio, "max", "https://tmdb/w/trio", D)
    repo.set_service_search_url("max", "https://play.max.com/search?q={title}")
    films = {x["title"]: x for x in client.get("/api/films").get_json()}
    assert films["Trio"]["best_source"]["url"] == "https://play.max.com/search?q=Trio"
    assert all("listing_url" not in s and "search_url" not in s for s in films["Trio"]["services"])
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/unit/test_database.py -k "best_source_url or never_carry_urls or lands_on_the_channel" tests/web/test_api.py -k watch_url -q`
Expected: KeyError `'url'`.

- [ ] **Step 3: Carry the two private keys through the option dicts**

In `database.py`, change `_SERVICES_SQL`'s SELECT list only (ORDER BY untouched):

```python
_SERVICES_SQL = f"""
SELECT l.film_id, s.name, s.subscribed, s.kind, s.quality, s.has_apple_app, s.search_url, l.url AS listing_url
FROM listings l
JOIN movie_service s ON s.slug = l.source
WHERE l.source != 'criterion'
  AND l.last_seen >= COALESCE(
      (SELECT value FROM meta WHERE key = '{TMDB_REFRESH_STAMP}'),
      (SELECT MAX(last_seen) FROM listings l2 WHERE l2.source = l.source))
ORDER BY l.film_id, s.subscribed DESC, s.quality DESC, s.has_apple_app DESC, s.name
"""

# `search_url` and `listing_url` ride on an option ONLY so the ranking can build the watch
# link; `_row_to_view` strips them from FilmView.services (drawer-redesign spec D10 — 14,717
# listings × a URL would put ~1 MB on the list payload) and keeps the resolved `url` on
# best_source alone.
_PRIVATE_OPTION_KEYS = frozenset({"search_url", "listing_url"})


def _public_option(option: dict[str, object]) -> dict[str, object]:
    return {k: v for k, v in option.items() if k not in _PRIVATE_OPTION_KEYS}
```

In `_services_by_film`'s appended dict add `"search_url": r["search_url"], "listing_url": str(r["listing_url"]),`. In `_service_option`'s returned dict add `"search_url": row["search_url"], "listing_url": None,` (a registry row has no listing of its own; Criterion's is supplied per film below, the store's stays None so an owned film's link is the store template or the drawer's fallback).

- [ ] **Step 4: Resolve the URL in `_row_to_view` and strip the keys**

Import `best_source, watch_url` from `movie_brain.domain.watch` (the module already imports `best_source`). Replace the final `return replace(view, best_source=best_source(view, criterion_option, store_option))` with:

```python
    # The Criterion option's landing page is this film's own listing URL (the LEFT JOIN in
    # _VIEW_SQL); a fresh dict per film, never a mutation of the option shared across the build.
    if criterion_option is not None:
        criterion_option = {**criterion_option, "listing_url": row["url"]}
    winner = best_source(view, criterion_option, store_option)
    if winner is not None:
        winner = {**_public_option(winner), "url": watch_url(winner, view.title)}
    return replace(view, services=[_public_option(s) for s in view.services], best_source=winner)
```

- [ ] **Step 5: Run the whole unit + web API suite, lint, types**

Run: `uv run pytest tests/unit tests/web/test_api.py -q && uv run ruff check . && uv run mypy`
Expected: all pass, including `test_services_sql_order_matches_the_domain_ranking` and every existing `best_source` test.

- [ ] **Step 6: Commit**

```bash
git add src/movie_brain/infrastructure/database.py tests/unit/test_database.py tests/web/test_api.py
git commit -m "the best source now knows where it lives, and the list payload never carries the address

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01QTtV1aGf3Fe1Gkuvov7WJh"
```

---

### Task 4: `film_credits`, `overview_for`, and the detail endpoint

**Files:**
- Modify: `src/movie_brain/infrastructure/database.py` (after `credits_for` ~line 1279)
- Modify: `src/movie_brain/web/app.py` (`film_detail`, lines 34–46)
- Test: `tests/unit/test_database.py` (append), `tests/web/test_api.py` (append after `_enrich_trio`)

**Interfaces:**
- Consumes: `build_credits`, `FilmCredits` (Task 1).
- Produces: `Repository.film_credits(film_id) -> FilmCredits | None`; `Repository.overview_for(film_id) -> str | None`; `GET /api/films/<id>` JSON gains `credits` (dict or null), `overview` (string or null), `tmdb_url` (`https://www.themoviedb.org/movie/<tmdb id>` or null). The existing `credits_for` (tuples, used by the enrichment tests and merge) is NOT changed.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_database.py` (the `_credits` helper near line 1785 and `CrewRow`/`Film` imports already exist there):

```python
def test_film_credits_shapes_the_drawer_rows(repo):
    day = date(2026, 9, 7)
    fid = repo.create_film(Film("The Big Sleep", 1946, "Howard Hawks", ""))
    repo.set_external_id(fid, "tmdb", "910", day)
    repo.write_credits(fid, _credits(crew=(
        CrewRow(2636, "Howard Hawks", "Director", "Directing"),
        CrewRow(4301, "Leigh Brackett", "Screenplay", "Writing"),
        CrewRow(4302, "William Faulkner", "Story", "Writing"),
        CrewRow(4302, "William Faulkner", "Screenplay", "Writing"),
        CrewRow(4303, "Raymond Chandler", "Novel", "Writing"),
    )), day)
    fc = repo.film_credits(fid)
    assert fc is not None
    assert fc.director == "Howard Hawks"
    assert [(c.name, c.character) for c in fc.cast] == [
        ("Humphrey Bogart", "Philip Marlowe"), ("Lauren Bacall", "Vivian Sternwood Rutledge"),
    ]
    assert [w.label for w in fc.writers] == ["Leigh Brackett", "William Faulkner", "Raymond Chandler (novel)"]
    assert repo.overview_for(fid) == _credits().overview


def test_film_credits_and_overview_are_none_for_an_unenriched_film(repo):
    fid = repo.create_film(Film("Bare", 2000, None, ""))
    assert repo.film_credits(fid) is None
    assert repo.overview_for(fid) is None
```

Append to `tests/web/test_api.py` after `_enrich_trio`:

```python
def test_detail_carries_credits_overview_and_the_tmdb_link(client, repo):
    trio = _enrich_trio(repo)
    body = client.get(f"/api/films/{trio}").get_json()
    assert body["overview"] == "Three tales of a private eye."
    assert body["tmdb_url"] == "https://www.themoviedb.org/movie/3"
    assert body["credits"] == {
        "director": "Ken",
        "cast": [{"name": "Humphrey Bogart", "character": "Philip Marlowe"}],
        "writers": [],
    }
    assert "credits" not in client.get("/api/films").get_json()[0]  # detail-only (spec D10)


def test_detail_of_an_unenriched_film_has_null_credits(client):
    fid = next(x["id"] for x in client.get("/api/films").get_json() if x["title"] == "Quartet")
    body = client.get(f"/api/films/{fid}").get_json()
    assert body["credits"] is None and body["overview"] is None and body["tmdb_url"] is None
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/unit/test_database.py -k film_credits tests/web/test_api.py -k "detail_carries or unenriched" -q`
Expected: AttributeError `film_credits` / KeyError `overview`.

- [ ] **Step 3: Repository**

After `credits_for` in `database.py` (import `build_credits` from `movie_brain.domain.credits` and `FilmCredits` from `movie_brain.domain.models`):

```python
    def film_credits(self, film_id: int) -> FilmCredits | None:
        """The drawer's credit rows — cast in billing order, then crew in TMDB's order — shaped
        by domain/credits.py::build_credits. None when the film was never enriched, so the
        drawer falls back to OMDb's strings. `credits_for` (tuples) stays for the enrichment
        tests and merge; this is the display shape."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT fc.kind, p.name, fc.character, fc.job, fc.department FROM film_credit fc "
                "JOIN person p ON p.id = fc.person_id WHERE fc.film_id = ? ORDER BY fc.kind, fc.ord, p.name",
                (film_id,),
            ).fetchall()
        return build_credits(
            (str(r["kind"]), str(r["name"]), str(r["character"]), str(r["job"]), str(r["department"])) for r in rows
        )

    def overview_for(self, film_id: int) -> str | None:
        """TMDB's overview from `film_text`, or None when absent or empty (drawer spec D1)."""
        with self._conn() as c:
            row = c.execute("SELECT overview FROM film_text WHERE film_id = ?", (film_id,)).fetchone()
        return str(row["overview"]) if row is not None and row["overview"] else None
```

`ORDER BY fc.kind` puts `cast` before `crew` alphabetically — the same trick `credits_for` relies on.

- [ ] **Step 4: Endpoint**

Replace the final `return` of `film_detail` in `app.py`:

```python
        ids = repo.external_ids_for(film_id)
        credits = repo.film_credits(film_id)
        return jsonify({
            **view.to_dict(),
            "payload": payload,
            # Detail-only (spec D10): credits and prose never ride on /api/films.
            "credits": credits.to_dict() if credits is not None else None,
            "overview": repo.overview_for(film_id),
            "tmdb_url": f"https://www.themoviedb.org/movie/{ids['tmdb']}" if "tmdb" in ids else None,
        }), 200
```

- [ ] **Step 5: Run, lint, types**

Run: `uv run pytest tests/unit/test_database.py tests/web/test_api.py -q && uv run ruff check . && uv run mypy`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/movie_brain/infrastructure/database.py src/movie_brain/web/app.py tests/unit/test_database.py tests/web/test_api.py
git commit -m "the drawer reads its cast from the credits table, and only the drawer pays for it

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01QTtV1aGf3Fe1Gkuvov7WJh"
```

---

### Task 5: The drawer — layout, summary, ratings block, watch line, links, width

**Files:**
- Modify: `tests/web/conftest.py` (Echo's payload ~line 60; the `_credits` helper and Alpha's `write_credits` ~lines 163–173; one `set_service_search_url` after the Bravo listings ~line 82)
- Modify: `src/movie_brain/web/static/app.js` (`detailHtml` and the helpers above it, lines ~462–527)
- Modify: `src/movie_brain/web/static/app.css` (`#drawer` rules ~line 55 and appended rules)
- Test: `tests/web/test_dashboard.py` (four existing assertions updated, new tests appended)

**Interfaces:**
- Consumes: detail JSON `credits`, `overview`, `tmdb_url` (Task 4); `best_source.url` (Task 3).
- Produces: DOM contract the Task 6 tests rely on — `#drawer-body div.meta a.person` (director), `dd.dd-cast` holding either plain links or `<div class="cast"><span class="cast-inline">…</span> <details class="svc-more cast-more"><summary>…</summary><ul class="cast-full"><li>…</li></ul></details></div>`, `dd.dd-writer`, every person link `a.person[data-query]`, `.ratings` with `.critics`/`.on-lists`/`.canon-score`, `p.best-source` holding `a.watch-link` or `a.owned-link`, `p.links` holding `a.criterion-link` / `a.tmdb-link` / `a.cheapcharts-link`.

- [ ] **Step 1: Seed changes**

In `tests/web/conftest.py`:

1. Echo's OMDb row becomes
```python
    repo.upsert_omdb(
        ids["echo (1990)"],
        OmdbRating(7.0, 60, True, "English, Spanish",
                   '{"Title":"Echo","Plot":"An echo.","Actors":"Ed Actor, Flo Actor","Writer":"Gus Writer (screenplay)"}',
                   metacritic=70),
        TODAY,
    )
```
with the comment `# Echo is never enriched: the drawer's OMDb fallbacks (plot, bare-query cast and writer links) are proved on it.`

2. After the Bravo listings loop add:
```python
    # Bravo's best source is Apple TV+ (name tiebreak); its template makes the drawer's watch link
    # a real title search. `criterion` deliberately gets none, so Charlie proves the listing-URL fallback.
    repo.set_service_search_url("apple-tv-plus", "https://tv.apple.com/search?term={title}")
```

3. Give the `_credits` helper a `crew` keyword and Alpha eight cast rows plus two writers:
```python
    def _credits(tmdb_id: int, title: str, overview: str, cast: tuple[CastRow, ...],
                 crew: tuple[CrewRow, ...] = (CrewRow(2636, "Howard Hawks", "Director", "Directing"),)) -> TmdbCredits:
        return TmdbCredits(
            tmdb_id=tmdb_id, imdb_id=None, title=title, original_title=title, year=None, runtime_min=None,
            alt_titles=(), overview=overview, tagline=None, genres=("Mystery",), keywords=("film noir",),
            cast=cast, crew=crew,
        )

    repo.set_external_id(ids["alpha (1950)"], "tmdb", "910", TODAY)
    repo.set_external_id(ids["bravo (1960)"], "tmdb", "911", TODAY)
    # Alpha carries eight billed actors (the drawer shows six, then "⋯ 2 more" with roles) and a
    # screenwriter plus a novelist (the writer label branch). No new name shares a trigram with
    # `bogrt`/`bogxrtq` or contains alpha/hawks/marlowe, so every search count above stays put.
    repo.write_credits(ids["alpha (1950)"], _credits(910, "Alpha", "A private eye in the Sternwood house.", (
        CastRow(4110, "Humphrey Bogart", "Philip Marlowe", 0),
        CastRow(4201, "Lauren Bacall", "Vivian Rutledge", 1),
        CastRow(4202, "John Ridgely", "Eddie Mars", 2),
        CastRow(4203, "Martha Vickers", "Carmen", 3),
        CastRow(4204, "Louis Jean Heydt", "Joe Brody", 4),
        CastRow(4205, "Charles Waldron", "The General", 5),
        CastRow(4206, "Regis Toomey", "Bernie Ohls", 6),
        CastRow(4207, "Sonia Darrin", "Agnes (uncredited)", 7),
    ), crew=(
        CrewRow(2636, "Howard Hawks", "Director", "Directing"),
        CrewRow(4301, "Leigh Brackett", "Screenplay", "Writing"),
        CrewRow(4302, "Raymond Chandler", "Novel", "Writing"),
    )), TODAY)
```
Bravo's `write_credits` call stays exactly as it is (Jane Bogart, Ke$1ha, Hawks via the default crew).

- [ ] **Step 2: Run the existing web suite to see which tests the seed alone moves**

Run: `uv run pytest tests/web -q`
Expected: still green — the seed changes add rows the current drawer does not read (it shows OMDb's `Actors`, which Alpha lacks) and Echo's new payload keys are only rendered by the new code. If anything fails here, the fixture arithmetic above is wrong; fix the seed, not the test.

- [ ] **Step 3: Write the failing Playwright tests**

Update four existing assertions in `tests/web/test_dashboard.py`:

- `test_drawer_opens_from_info_button_and_restores_url` (~line 290): the selector `a.criterion:not(.owned-link):not(.cheapcharts-link)` becomes `a.criterion-link`.
- `test_drawer_names_the_best_source` (~line 560): `"Best source: Apple TV+"` becomes `"Watch on Apple TV+"`.
- `test_an_owned_film_answers_with_the_store_it_was_bought_from` (~line 567): the expectation becomes `expect(dash.locator("#drawer .best-source")).to_contain_text("Owned on Apple TV")` and the docstring's last clause becomes `and still answers with the Apple TV library link, because the owner already has it.`
- `test_drawer_shows_owned_link` (~line 770) stays as is — `a.owned-link` now lives on the watch line and its href still contains `tv.apple.com/search`.

Append:

```python
# ---- drawer redesign (spec docs/superpowers/specs/2026-09-07-drawer-redesign-design.md) ----


def _open(dash: Page, title: str):
    dash.locator("tbody tr", has_text=title).first.click()
    body = dash.locator("#drawer-body")
    expect(body).to_contain_text(title)  # populated — a negative assertion on an empty drawer passes vacuously
    return body


def test_drawer_is_760_wide(dash: Page):
    _open(dash, "Alpha")
    assert dash.locator("#drawer").bounding_box()["width"] == 760


def test_drawer_summary_prefers_the_tmdb_overview(dash: Page):
    body = _open(dash, "Alpha")
    expect(body.locator("p").first).to_have_text("A private eye in the Sternwood house.")  # TMDB, not OMDb's "A plot."
    expect(body.locator("pre.raw")).to_contain_text('"Plot": "A plot."')  # OMDb still in the raw payload


def test_drawer_summary_falls_back_to_the_omdb_plot(dash: Page):
    body = _open(dash, "Echo")  # never enriched
    expect(body.locator("p").first).to_have_text("An echo.")


def test_drawer_sections_run_facts_cast_writer_ratings_then_watch(dash: Page):
    body = _open(dash, "Alpha")
    expect(body).to_contain_text("Owned on Apple TV")
    text = body.inner_text()
    marks = ["Language", "Cast", "Writer", "My rating", "IMDb 8.5 · Metacritic 92 · Rotten Tomatoes 95%",
             "On lists: Backlog Ten", "Owned on Apple TV", "Also streaming on", "Open on Criterion", "Raw OMDb payload"]
    positions = [text.index(m) for m in marks]
    assert positions == sorted(positions), list(zip(marks, positions))


def test_drawer_on_lists_line_ends_with_the_canon_score(dash: Page):
    body = _open(dash, "Alpha")
    # Backlog Ten unordered, trust 7 → 7. Sight & Sound 2022: 2 entries, Alpha #2, trust 5 → 5 × (1 − 1/2) = 2.5.
    # cahiers-100: 2 entries, Alpha #3, trust 1 → 1 × (1 − 2/2) = 0. Total 9.5.
    expect(body.locator(".canon-score")).to_have_text("· canon score 9.5")


def test_drawer_ratings_block_notes_a_pending_lookup(dash: Page):
    body = _open(dash, "Delta")  # no OMDb row
    expect(body.locator(".ratings")).to_contain_text("OMDb lookup pending.")
    assert body.locator(".ratings .critics").count() == 0


def test_watch_link_fills_the_services_template(dash: Page):
    clear_lang(dash)
    body = _open(dash, "Bravo")
    link = body.locator(".best-source a.watch-link")
    expect(link).to_have_text("Watch on Apple TV+ ↗")
    expect(link).to_have_attribute("href", "https://tv.apple.com/search?term=Bravo")


def test_watch_link_falls_back_to_the_criterion_page(dash: Page):
    body = _open(dash, "Charlie")
    link = body.locator(".best-source a.watch-link")
    expect(link).to_have_text("Watch on Criterion Channel ↗")
    expect(link).to_have_attribute("href", "https://c/charlie")


def test_owned_film_links_to_the_apple_tv_library_search(dash: Page):
    body = _open(dash, "Alpha")
    link = body.locator(".best-source a.owned-link")
    expect(link).to_have_text("Owned on Apple TV ↗")
    expect(link).to_have_attribute("href", "https://tv.apple.com/search?term=Alpha")


def test_discovery_film_without_listings_has_no_watch_line(dash: Page):
    body = _open(dash, "Golf")
    assert body.locator(".best-source").count() == 0


def test_drawer_links_row_has_tmdb_and_no_metacritic(dash: Page):
    body = _open(dash, "Alpha")
    expect(body.locator("a.tmdb-link")).to_have_text("TMDB ↗")
    expect(body.locator("a.tmdb-link")).to_have_attribute("href", "https://www.themoviedb.org/movie/910")
    dash.keyboard.press("Escape")
    body = _open(dash, "Golf")  # holds a metacritic slug and no tmdb id
    expect(body).not_to_contain_text("Metacritic ↗")
    assert body.locator("a.tmdb-link").count() == 0
```

- [ ] **Step 4: Run them to verify they fail**

Run: `uv run pytest tests/web/test_dashboard.py -k "drawer or watch_link or owned_film or discovery_film" -q`
Expected: the new tests fail on missing classes/text; the four updated ones fail on the old copy.

- [ ] **Step 5: `app.js` — helpers and the new `detailHtml`**

Replace everything from `const TOP_SERVICES = 3;` (line 4) through the end of `detailHtml` (the line `${d.leaving_date ? ... : ''}\`;` and its closing `}`) as follows. Line 4 becomes two constants:

```js
  const TOP_SERVICES = 3;  // drawer: services shown before the ⋯ more disclosure
  const TOP_CAST = 6;      // drawer: cast names shown inline before the ⋯ more disclosure (drawer spec D2)
```

Then, directly above `function detailHtml(d)` (after `renderAudit`), add:

```js
  // A person link (drawer spec D4): the click handler below reads data-query and searches it,
  // closing the drawer. `exact` names come from TMDB credits and are quoted — exact, never
  // corrected — because they come from the same person table the search resolves against;
  // OMDb-fallback names are bare so the fuzzy stage can bridge a spelling drift. `shown` is the
  // link text, `queried` the name in the query (they differ for the director: the table's
  // Criterion string is shown, the TMDB Director credit is searched).
  const personLink = (field, shown, exact, queried = shown) => {
    const query = exact ? `${field}: "${queried.replace(/"/g, '')}"` : `${field}: ${queried}`;
    return `<a class="person" href="#" data-query="${esc(query)}">${esc(shown)}</a>`;
  };
  function castHtml(d, p) {
    const cast = (d.credits && d.credits.cast) || [];
    if (cast.length) {
      const inline = cast.slice(0, TOP_CAST).map((c) => personLink('actor', c.name, true)).join(', ');
      if (cast.length <= TOP_CAST) return inline;
      // Six bare names inline; the disclosure lists EVERYONE with their role, one per line, and
      // CSS hides the inline six while it is open (spec §3 "Cast row").
      const full = cast.map((c) => `<li>${personLink('actor', c.name, true)}${c.character ? ` as ${esc(c.character)}` : ''}</li>`).join('');
      return `<div class="cast"><span class="cast-inline">${inline}</span> <details class="svc-more cast-more"><summary><span class="when-closed">⋯ ${cast.length - TOP_CAST} more</span><span class="when-open">⋯ fewer</span></summary><ul class="cast-full">${full}</ul></details></div>`;
    }
    if (p.Actors && p.Actors !== 'N/A') return p.Actors.split(', ').map((n) => personLink('actor', n, false)).join(', ');
    return '';
  }
  function writerHtml(d, p) {
    const writers = (d.credits && d.credits.writers) || [];
    // label is "Name" or "Name (novel)" (domain/credits.py::writer_label): link the name, keep the tag as text.
    if (writers.length) return writers.map((w) => personLink('writer', w.name, true) + esc(w.label.slice(w.name.length))).join(', ');
    if (p.Writer && p.Writer !== 'N/A') {
      return p.Writer.split(', ').map((part) => {
        const name = part.replace(/\s*\(.*\)\s*$/, '');   // OMDb's "(screenplay)" / "(novel)" suffixes stay as text
        return personLink('writer', name, false) + esc(part.slice(name.length));
      }).join(', ');
    }
    return '';
  }
```

And `detailHtml` in full:

```js
  function detailHtml(d) {
    const p = d.payload || {};
    const poster = p.Poster && p.Poster !== 'N/A' ? `<img class="poster" src="${esc(p.Poster)}" alt="">` : '';
    // Summary: TMDB's overview first, OMDb's short plot only when there is none (spec D1).
    const summary = d.overview || (p.Plot && p.Plot !== 'N/A' ? p.Plot : '');
    const fields = [['Genre', esc(p.Genre)], ['Runtime', esc(p.Runtime)], ['Rated', esc(p.Rated)], ['Country', esc(p.Country)],
      ['Language', esc(d.language)], ['Awards', esc(p.Awards)], ['Cast', castHtml(d, p)], ['Writer', writerHtml(d, p)]]
      .filter(([, v]) => v && v !== 'N/A').map(([k, v]) => `<dt>${k}</dt><dd class="dd-${k.toLowerCase()}">${v}</dd>`).join('');
    const svc = d.services || [];
    // Services arrive already ranked (subscribed, quality, Apple TV app, name — see
    // domain/watch.py). A film can carry dozens of them, so show the best few and put the
    // rest behind a native <details> disclosure: no filtering, because a service you rate
    // badly is still the answer when it is the only place a film exists.
    const collapse = (names) => names.length <= TOP_SERVICES ? names.join(', ')
      : `${names.slice(0, TOP_SERVICES).join(', ')} <details class="svc-more"><summary>⋯ ${names.length - TOP_SERVICES} more</summary><span class="svc-rest">, ${names.slice(TOP_SERVICES).join(', ')}</span></details>`;
    const streaming = collapse(svc.filter((s) => s.kind !== 'store')
      .map((s) => s.subscribed ? esc(s.name) : `${esc(s.name)} (not subscribed)`));
    const buyable = collapse(svc.filter((s) => s.kind === 'store').map((s) => esc(s.name)));
    const newOn = (d.new_on || []).map((t) => `${esc(t.name)} since ${esc(t.appeared_on)}`).join(', ');
    const lists = (d.lists || []).map((l) => {
      const label = esc(l.name);  // the same name the picker shows, so the two agree
      // rank_label is the cell AS PRINTED, so a tie arrives as "=54"; the drawer shows the
      // number alone (#54) — whether the placing was tied is not what this line is for.
      const rank = String(l.rank_label ?? l.rank).replace(/^=/, '');
      return l.ordered ? `${label} #${esc(rank)}` : label;
    }).join(', ');
    // Ratings block (spec D5): the same three numbers the table columns show, never OMDb's
    // Ratings array; then the lists line with the canon score the On-a-list sort uses.
    const critics = [
      d.imdb != null ? `IMDb <b>${d.imdb.toFixed(1)}</b>` : '',
      d.metacritic != null ? `Metacritic <b>${esc(d.metacritic)}</b>` : '',
      d.rt != null ? `Rotten Tomatoes <b>${esc(d.rt)}%</b>` : '',
    ].filter(Boolean).join(' · ');
    const criticsLine = critics ? `<div class="row critics">${critics}</div>`
      : d.pending ? '<div class="row note">OMDb lookup pending.</div>'
      : d.found === false ? '<div class="row note">No OMDb match.</div>' : '';
    const listsLine = lists ? `<div class="row on-lists">On lists: ${lists} <span class="canon-score">· canon score ${canonScore(d).toFixed(1)}</span></div>` : '';
    // The one watch link (spec D6/D7). Possession short-circuits the ranking in domain/watch.py,
    // so an owned film's best_source is the store row and its url the store's template when set;
    // the Apple TV library search is the fallback that predates the template.
    const bs = d.best_source;
    let watchLine = '';
    if (d.owned) {
      const href = (bs && bs.url) || `https://tv.apple.com/search?term=${encodeURIComponent(d.title)}`;
      watchLine = `<p class="meta best-source"><a class="owned-link" href="${esc(href)}" target="_blank" rel="noopener">Owned on Apple TV ↗</a></p>`;
    } else if (bs) {
      const label = `Watch on <b>${esc(bs.name)}</b>${bs.subscribed ? '' : ' (not subscribed)'} ↗`;
      watchLine = `<p class="meta best-source">${bs.url ? `<a class="watch-link" href="${esc(bs.url)}" target="_blank" rel="noopener">${label}</a>` : label}</p>`;
    }
    const credited = d.credits && d.credits.director;
    const director = d.director ? personLink('director', d.director, !!credited, credited || d.director) : '—';
    return `<h2>${esc(d.title)} <button class="watch-toggle" data-id="${d.id}" title="Toggle watchlist" aria-label="Toggle watchlist">${d.watchlisted ? '★' : '☆'}</button><button class="revisit-toggle" data-id="${d.id}" title="Toggle needs-revisit" aria-label="Toggle needs-revisit">${d.needs_revisit ? '⚑' : '⚐'}</button></h2>
      ${d.needs_revisit ? `<input class="revisit-note" data-id="${d.id}" placeholder="what looks wrong?" value="${esc(d.revisit_note || '')}">` : ''}
      ${renderAudit(d)}
      <div class="meta">${fmt(d.year)} · ${director}${d.departed ? ' · <b>Gone from Criterion</b>' : ''}</div>
      ${summary ? `<p>${poster}${esc(summary)}</p>` : poster}
      <dl>${fields}</dl>
      <div class="ratings">
        <div class="row">My rating: <input class="rating" maxlength="2" data-id="${d.id}" value="${d.my_rating ?? ''}" aria-label="My rating"></div>
        ${criticsLine}${listsLine}
      </div>
      ${watchLine}
      ${newOn ? `<p class="meta new-on">New on: ${newOn}</p>` : ''}
      ${streaming ? `<p class="meta">Also streaming on: ${streaming}</p>` : ''}
      ${buyable ? `<p class="meta">Buy on: ${buyable}</p>` : ''}
      <p class="links">${d.url ? `<a class="criterion criterion-link" href="${esc(d.url)}" target="_blank" rel="noopener">Open on Criterion ↗</a>` : ''}
        ${d.tmdb_url ? ` <a class="criterion tmdb-link" href="${esc(d.tmdb_url)}" target="_blank" rel="noopener">TMDB ↗</a>` : ''}
        ${d.cheapcharts_url
          ? ` <a class="criterion cheapcharts-link" href="${esc(d.cheapcharts_url)}" target="_blank" rel="noopener">CheapCharts ↗</a>`
          : buyable ? ` <a class="criterion cheapcharts-link" href="https://www.cheapcharts.com/us/search;q=${encodeURIComponent(d.title)};t=all" target="_blank" rel="noopener">Find on CheapCharts ↗</a>` : ''}</p>
      <details><summary>Raw OMDb payload</summary><pre class="raw">${esc(d.payload ? JSON.stringify(d.payload, null, 2) : 'null')}</pre></details>
      ${d.leaving_date ? `<p class="meta leaving"><b>Leaving ${esc(d.leaving_date)}</b></p>` : ''}`;
  }
```

What went away: the `sources` `<ul>` (OMDb's Ratings array), the `Open on Metacritic` link, the `My rating` input in the links row, the `Owned on Apple TV` link in the links row, the old `Best source:` line. `canonScore` is the existing function at the top of the file. The `input.rating` handlers (`commitRating`, keydown/focusout on `input.rating`) match by class and keep working.

- [ ] **Step 6: `app.css`**

Change the `#drawer` rule's width to `width:min(760px, 100vw);` (spec D9). Append:

```css
/* Drawer redesign (2026-09-07): person links, the ratings block, the cast disclosure. */
#drawer a.person { color:#1a56db; text-decoration:none; border-bottom:1px dotted #1a56db; }
#drawer a.person:hover { border-bottom-style:solid; }
#drawer .ratings { border-top:1px solid var(--line); border-bottom:1px solid var(--line); padding:8px 0; margin:12px 0; }
#drawer .ratings .row { margin:3px 0; }
#drawer .ratings .note, #drawer .canon-score { color:var(--muted); }
#drawer .best-source a { color:inherit; }
#drawer p.links a { margin-right:6px; }
/* Open = the whole cast, one per line, roles throughout; the inline six hide while it is open. */
#drawer .cast:has(.cast-more[open]) .cast-inline { display:none; }
.cast-more[open] { display:block; }
.cast-more > summary .when-open { display:none; }
.cast-more[open] > summary .when-closed { display:none; }
.cast-more[open] > summary .when-open { display:inline; }
#drawer ul.cast-full { margin:4px 0 0; padding:0; list-style:none; columns:2; column-gap:24px; }
#drawer ul.cast-full li { break-inside:avoid; margin:1px 0; }
```

- [ ] **Step 7: Run the whole web suite, then everything**

Run: `uv run pytest tests/web -q`
Expected: green, including the poster-alignment test (the summary is still the first `<p>` and holds the poster), the "Leaving" last-child test, the on-lists tests (their `to_contain_text` strings are prefixes of the new line) and the services tests. Then `uv run pytest -q && uv run ruff check . && uv run mypy`.

- [ ] **Step 8: Look at it**

`uv run movie-brain dashboard` is NOT run against the live DB here (the live DB is behind on migration 021 until Task 7 and `Repository` would refuse to open it). Instead run the seeded server: `uv run pytest tests/web/test_dashboard.py -k drawer_is_760 --headed` opens Chromium on the fixture for a glance; skip if headed mode is unavailable.

- [ ] **Step 9: Commit**

```bash
git add tests/web/conftest.py src/movie_brain/web/static/app.js src/movie_brain/web/static/app.css tests/web/test_dashboard.py
git commit -m "the drawer answers what, how good, where, in that order, with one link that lands on the service

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01QTtV1aGf3Fe1Gkuvov7WJh"
```

---

### Task 6: Cast disclosure and person links — the interactions

**Files:**
- Modify: `src/movie_brain/web/static/app.js` (after `hideDrawer`, ~line 532)
- Test: `tests/web/test_dashboard.py` (append)

**Interfaces:**
- Consumes: the DOM contract from Task 5; `hideDrawer`, `drawerSeq`, `drawerOpenPushed`, `state.q`, `searchEl`, `searchTimer`, `syncUrl`, `runSearch` — all already in `app.js`.
- Produces: clicking `#drawer-body a.person` closes the drawer, sets the bar to its `data-query`, runs the search, pushes one history entry (`q=` set, `film=` absent).

- [ ] **Step 1: Write the failing tests**

Append to `tests/web/test_dashboard.py`:

```python
def _settled(dash: Page) -> None:
    dash.wait_for_function("document.querySelector('#search').dataset.settled === document.querySelector('#search').value")


def test_cast_row_shows_six_names_then_everyone_with_roles(dash: Page):
    body = _open(dash, "Alpha")
    inline = body.locator(".cast-inline")
    expect(inline).to_have_text("Humphrey Bogart, Lauren Bacall, John Ridgely, Martha Vickers, Louis Jean Heydt, Charles Waldron")
    summary = body.locator(".cast-more summary")
    expect(summary).to_have_text("⋯ 2 more", use_inner_text=True)  # innerText: the hidden "⋯ fewer" span is not rendered
    expect(body.locator(".cast-full")).not_to_be_visible()  # a closed <details> still holds its text — test VISIBILITY (watch.md)
    summary.click()
    expect(body.locator(".cast-full")).to_be_visible()
    expect(inline).not_to_be_visible()
    expect(summary).to_have_text("⋯ fewer", use_inner_text=True)
    items = body.locator(".cast-full li")
    expect(items).to_have_count(8)
    expect(items.nth(0)).to_have_text("Humphrey Bogart as Philip Marlowe")
    expect(items.nth(7)).to_have_text("Sonia Darrin as Agnes (uncredited)")


def test_writer_row_labels_the_novelist_and_links_the_name(dash: Page):
    body = _open(dash, "Alpha")
    expect(body.locator("dd.dd-writer")).to_have_text("Leigh Brackett, Raymond Chandler (novel)")
    expect(body.locator("dd.dd-writer a.person").nth(1)).to_have_text("Raymond Chandler")
    expect(body.locator("dd.dd-writer a.person").nth(1)).to_have_attribute("data-query", 'writer: "Raymond Chandler"')


def test_unenriched_film_falls_back_to_omdb_names_with_bare_queries(dash: Page):
    body = _open(dash, "Echo")
    expect(body.locator("dd.dd-cast")).to_have_text("Ed Actor, Flo Actor")
    expect(body.locator("dd.dd-cast a.person").first).to_have_attribute("data-query", "actor: Ed Actor")
    expect(body.locator("dd.dd-writer")).to_have_text("Gus Writer (screenplay)")
    expect(body.locator("dd.dd-writer a.person")).to_have_attribute("data-query", "writer: Gus Writer")
    assert body.locator(".cast-more").count() == 0


def test_cast_link_closes_the_drawer_and_searches_the_exact_name(dash: Page):
    body = _open(dash, "Alpha")
    body.locator("a.person", has_text="Lauren Bacall").click()
    expect(dash.locator("#drawer")).to_be_hidden()
    expect(dash.locator("#search")).to_have_value('actor: "Lauren Bacall"')
    _settled(dash)
    assert count(dash) == 1
    assert "q=" in dash.url and "film=" not in dash.url
    dash.go_back()  # the open-drawer entry is still behind the search: Back reopens the film
    expect(dash.locator("#drawer h2")).to_contain_text("Alpha")


def test_director_link_searches_the_tmdb_credit_and_keeps_a_set_chip(dash: Page):
    # Alpha's Criterion director string is "Ann" (shown); its TMDB Director credit is Howard Hawks
    # (searched), who also directs Bravo.
    body = _open(dash, "Alpha")
    link = body.locator("div.meta a.person")
    expect(link).to_have_text("Ann")
    link.click()
    expect(dash.locator("#search")).to_have_value('director: "Howard Hawks"')
    _settled(dash)
    assert count(dash) == 2  # Alpha and Bravo
    _search(dash, "")
    cycle(dash, "owned")  # Owned on — Alpha only
    assert count(dash) == 1
    _open(dash, "Alpha").locator("div.meta a.person").click()
    _settled(dash)
    assert count(dash) == 1  # the chip the owner set survived the link (the list-picker ruling)
    expect(dash.locator('.chip[data-group="owned"]')).to_have_class(re.compile(r"\bactive\b"))


def test_writer_link_searches_the_writer_field(dash: Page):
    _open(dash, "Alpha").locator("a.person", has_text="Raymond Chandler").click()
    expect(dash.locator("#search")).to_have_value('writer: "Raymond Chandler"')
    _settled(dash)
    assert count(dash) == 1
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/web/test_dashboard.py -k "cast_row or writer_row or unenriched_film or cast_link or director_link or writer_link" -q`
Expected: the three render tests PASS already (Task 5 built the markup); the three link tests fail — the drawer stays open and the bar stays empty.

- [ ] **Step 3: The click handler**

In `app.js`, after `hideDrawer` (and before `openDrawer`), add:

```js
  // Person links (drawer spec D4). Close WITHOUT walking history back: closeDrawer() would call
  // history.back(), and the popstate handler then re-reads state from the previous URL, wiping
  // the query set here (spec §4's ordering hazard). Pushing a fresh entry instead leaves the
  // open-drawer entry behind it, so Back reopens the film — the undo the spec asks for. Touches
  // no chip, column filter, language or list (the list-picker ruling).
  body.addEventListener('click', (e) => {
    const a = e.target.closest('a.person'); if (!a) return;
    e.preventDefault();
    if (searchTimer) clearTimeout(searchTimer);
    drawerSeq++;              // supersede any in-flight open
    hideDrawer();
    drawerOpenPushed = false;
    state.q = a.dataset.query;
    searchEl.value = state.q;
    delete searchEl.dataset.settled;
    syncUrl(true);
    runSearch();
  });
```

`searchTimer`, `searchEl`, `runSearch` and `syncUrl` are declared earlier in the file (the power-search block sits above the drawer block); `drawerSeq`/`drawerOpenPushed` are the `let`s declared just above `hideDrawer`. If the handler lands before those `let`s, move it below them — a `let` in the temporal dead zone throws at click time.

- [ ] **Step 4: Run the web suite, then everything**

Run: `uv run pytest tests/web -q`, then `uv run pytest -q && uv run ruff check . && uv run mypy`.
Expected: all green. If `test_cast_link_closes_the_drawer…`'s `go_back` step fails, the URL push happened before `hideDrawer` cleared `state.openFilm` — `syncUrl` encodes `state.openFilm`, so `hideDrawer()` must run first, as written.

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/web/static/app.js tests/web/test_dashboard.py
git commit -m "every name in the drawer is a filter now, and clicking one never undoes a chip the owner set

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01QTtV1aGf3Fe1Gkuvov7WJh"
```

---

### Task 7: Docs, the live steps, finishing

**Files:**
- Modify: `CLAUDE.md` (Commands `services` line; the `movie_service` bullet; the `FilmView.best_source` bullet; a new drawer bullet after the `needs_revisit` bullet; the migration mention in the `Data` section is unchanged)
- Modify: `.claude/rules/watch.md` (two bullets)
- Modify: `docs/backlog.md` (items 4 and 14)

- [ ] **Step 1: CLAUDE.md**

Commands block — replace the `services` line with (one line, no wrap):

```
uv run movie-brain services list | quality SLUG [N] | apple SLUG [0|1] | subscribe SLUG [0|1] | url SLUG [TEMPLATE|-]   # the service registry, best first on the same four keys that rank a film's options; the ONLY writer of `movie_service.quality` (0 legal — ranks last), `has_apple_app`, `subscribed` and `search_url` (migration 021: the service's title-search template with a `{title}` placeholder — where the drawer's "Watch on <service>" link lands; `-` clears it, and with none set the link falls back to the listing's stored URL); a bare slug shows one service, an unknown slug exits 2
```

`movie_service` bullet — after "the owner's two hand-set ranking constants, written by `movie-brain services` and by nothing else" add "; migration 021 adds a third owner column, `search_url TEXT` NULL, same single writer, not a ranking key".

`FilmView.best_source` bullet — after "The card badges the winner only when it is subscribed; the drawer prints it either way." replace with "The card badges the winner only when it is subscribed; the drawer links it either way: `best_source` carries `url`, resolved on every read by `domain/watch.py::watch_url` — the service's `search_url` template with the percent-encoded title filled in, else the listing's stored URL (Criterion's direct page, joined per film from `_VIEW_SQL`; TMDB's watch page for provider-fed services), else null. `_SERVICES_SQL` reads `search_url` and `l.url AS listing_url` onto the option dicts ONLY for that resolution; `_row_to_view` strips both (`_PRIVATE_OPTION_KEYS`) so `FilmView.services` entries stay `{name, subscribed, kind, quality, has_apple_app}` and the list payload never carries a URL (drawer spec D10)."

New bullet after the `needs_revisit` bullet, one paragraph, no hard wraps, covering: the 2026-09-07 drawer redesign (spec `docs/superpowers/specs/2026-09-07-drawer-redesign-design.md`) — 760px; order title → year · director → TMDB overview beside the poster (OMDb plot only when there is none, D1) → facts → Cast → Writer → ratings block (My rating, then `IMDb · Metacritic · Rotten Tomatoes` from the FilmView numbers the table shows, then On lists ending `· canon score N.N`) → the one watch line (`Watch on <best source> ↗` to `best_source.url`; `Owned on Apple TV ↗` for owned films, the store template or the Apple TV search fallback) → New on / Also streaming on / Buy on → links row (`Open on Criterion ↗`, `TMDB ↗` from the film's tmdb external id, CheapCharts; the Metacritic link is gone, `FilmView.metacritic_url` stays) → raw payload → Leaving; credits are DETAIL-ONLY — `/api/films/<id>` returns `credits` (`domain/credits.py::build_credits` over `Repository.film_credits`: director, cast in TMDB billing order `ord`, writers one per person labelled by `writer_label` — bare for Screenplay/Writer, `(novel)` otherwise), `overview` and `tmdb_url`, and `/api/films` does not grow; Cast shows six bare names then `⋯ N more`, which opens every entry as `Name as Role` one per line in two columns while CSS (`:has`) hides the inline six; never-enriched films fall back to OMDb's `Actors`/`Writer` strings; every name is `a.person[data-query]` — TMDB names quoted (exact, never corrected), OMDb-fallback names bare (fuzzy), the director link shows the table's Criterion string and searches the TMDB Director credit — and a click closes the drawer WITHOUT `closeDrawer()`'s `history.back()` (its popstate would re-read the old URL and wipe the query), pushes one entry with `q=` and no `film=`, runs the search and touches no chip, column filter, language or list; Playwright pins: `test_drawer_sections_run_facts_cast_writer_ratings_then_watch`, `test_cast_row_shows_six_names_then_everyone_with_roles`, `test_cast_link_closes_the_drawer_and_searches_the_exact_name`, `test_director_link_searches_the_tmdb_credit_and_keeps_a_set_chip`.

- [ ] **Step 2: `.claude/rules/watch.md`**

Add to the `movie-brain services` bullet: "Migration 021 adds `search_url` (TEXT, NULL) under the same rule — `set_service_search_url` is its only writer, `register_provider` still names none of the four." Add a new bullet at the end: "**`best_source` carries `url`, resolved on every read by `watch_url(option, title)` and never stored:** the registry template with the percent-encoded title, else the listing URL (Criterion's own page — the option is rebuilt per film with `listing_url = row['url']`, never by mutating the shared registry dict — or TMDB's watch page), else None. `_SERVICES_SQL` gained two SELECT columns for this and NOTHING in its ORDER BY; `_row_to_view` strips `search_url`/`listing_url` (`_PRIVATE_OPTION_KEYS`) from every `services` entry so the list payload stays URL-free (drawer spec D10, `test_services_entries_never_carry_urls`)."

- [ ] **Step 3: `docs/backlog.md`**

Item 14 becomes `[x]` with an appended sentence: "— shipped 2026-09-07 (drawer redesign spec): links are built on `film_credit` names (quoted, exact), OMDb strings only as the never-enriched fallback (bare), and the click pushes a fresh history entry rather than walking back, which is what keeps the query from being wiped." Item 4: append "**Cast/metadata half shipped 2026-09-07** (full TMDB cast with roles, writers, TMDB overview, TMDB link, one watch link that lands on the service's search — `services url`); still open: the trailer link and critic-review links."

- [ ] **Step 4: Verify prose is unwrapped, run everything, commit**

```bash
~/code/praxis-workspace/praxis-halo/bin/unwrap-md CLAUDE.md .claude/rules/watch.md docs/backlog.md
uv run pytest -q && uv run ruff check . && uv run mypy
git add CLAUDE.md .claude/rules/watch.md docs/backlog.md
git commit -m "the rules should say the drawer's credits are detail-only and why a person link never walks history back

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01QTtV1aGf3Fe1Gkuvov7WJh"
```

- [ ] **Step 5: Finish the branch, then the live steps — each one waits for its own owner yes (`one-at-a-time`)**

Invoke `superpowers:finishing-a-development-branch` (the owner has always chosen "merge locally", then `git push origin main`). Then, on `main`, against `~/.config/movie-brain/movie-brain.db`, announce each before running and never run two on one yes:

1. `uv run movie-brain migrate` (dry run, lists `021_service_search_url.sql`) then, on a yes, `uv run movie-brain migrate --apply` — a backup lands in `<config_dir>/backups/` first.
2. `uv run movie-brain services list` — unchanged output plus no `url` anywhere yet.
3. Templates, one verb per yes, for the subscribed services the owner names. Candidates to confirm with the owner (the search-page URLs are the owner's to verify in a browser first): `criterion` `https://www.criterionchannel.com/search?q={title}`, `max` `https://play.max.com/search?q={title}`, `apple-tv-plus` and `apple-tv-store` `https://tv.apple.com/search?term={title}`, `peacock` `https://www.peacocktv.com/search?q={title}`, `prime-video` `https://www.amazon.com/s?k={title}&i=instant-video`, `kanopy` `https://www.kanopy.com/en/search?query={title}`. Criterion's is optional — its listing URL is already the film's own page and is the better landing.
4. `uv run movie-brain dashboard`, owner-driven UAT on The Big Sleep (#3704): overview beside poster, six names then 42 more with roles, `Leigh Brackett, William Faulkner, Jules Furthman, Raymond Chandler (novel)`, ratings block `IMDb 7.9 · Metacritic 86 · Rotten Tomatoes 96%`, lists line ending `· canon score 9.8`, a Bacall click filtering the table, the watch link on a subscribed film landing on that service. Record what the owner says under the spec's §2 table as a UAT line.

---

## Self-review

**Spec coverage.** D1 summary → Task 5 (`summary`, two tests). D2 cast from `film_credit`, six then everyone with roles, two columns → Tasks 4–6. D3 writers → Task 1 (`writer_label`), Task 4 (`film_credits`), Task 6 test. D4 person links, quoted vs bare, no control touched, director credit-vs-display → Task 5 markup + Task 6 handler and tests. D5 ratings block position and content → Task 5. D6 watch line, owned fallback → Tasks 3 and 5. D7 migration 021, `services url`, fallback to listing URL → Tasks 2–3. D8 links row, TMDB link, Metacritic gone, `metacritic_url` kept → Tasks 4–5 (`tmdb_url`) and the existing `test_api` assertion on `metacritic_url` untouched. D9 760px → Task 5. D10 detail-only credits, URL-free `services` → Tasks 3–4 with tests in both layers. §4's ordering hazard → Task 6's handler comment and `go_back` test. §5's test list → every item has a test above. §6 out of scope respected: no trailer, no table/chip/picker change. §7 docs → Task 7.

**Spec deviations, logged.** The spec names the repository read `credits_for`; that name already exists (tuples, used by enrichment tests and merge), so this plan adds `film_credits` beside it and leaves `credits_for` alone — Task 7's CLAUDE.md bullet says so. The spec says "OMDb lookup pending." replaces the critics line; the plan renders it as a `.note` row inside the ratings block (same copy, one container) so `div.meta` stays unique for the existing strict-mode locator.

**Placeholders.** None — every step carries its code and expected strings; every expected string traces to the fixture arithmetic section.

**Type consistency.** `watch_url(option, title)` (Task 1) is what `_row_to_view` calls (Task 3). `build_credits` takes `(kind, name, character, job, department)` (Task 1) and `film_credits` selects exactly those five in that order (Task 4). `FilmCredits.to_dict()` (Task 1) produces the `credits` shape the API test asserts (Task 4) and `castHtml`/`writerHtml` read (`credits.cast[].name/.character`, `credits.writers[].name/.label`, `credits.director`) (Task 5). `set_service_search_url(slug, template)` (Task 2) is called with `None`, `""` and a template in Tasks 2, 3 and 5's seed. `_public_option`/`_PRIVATE_OPTION_KEYS` (Task 3) are referenced by name in Task 7's docs. Test helpers `_open` (Task 5) and `_settled` (Task 6) are defined before use; `count`, `cycle`, `clear_lang`, `_search` already exist in `test_dashboard.py`; `re` is already imported there.
