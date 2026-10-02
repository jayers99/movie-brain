# Criterion Relaunch — Plan C (directors) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A film that holds a Criterion mediaid and shows the owner NO director — no `films.director` and no OMDb director — takes the director Criterion's own record (JW Player) names; nothing anyone can already see ever changes. It runs as the last step of the catch-up chain and by hand as `movie-brain enrich criterion-directors [--apply]`.

**Architecture:** One repository read (`films_needing_criterion_director`, the worklist) and one guarded write (`fill_criterion_director`, an `UPDATE … WHERE director IS NULL AND no OMDb director`), one application use case (`application/criterion_directors.py::fill_criterion_directors`) that asks JW once per film through the `media(mediaid)` method `HttpCriterionSite` already has, a fifth step in `application/catch_up.py`, and a CLI verb. The JW site is built in `cli._catch_up_chain`, never in the application layer (the same reason that function builds the CheapCharts client). No stamp, no schema change.

**Tech Stack:** Python 3.12, requests, pytest + pytest-bdd, typer, SQLite via `Repository`.

**Spec:** `docs/superpowers/specs/2026-10-01-criterion-relaunch-design.md` — this plan builds §8 Plan C: D8, the §5 test "director filled once, only where neither ours nor OMDb's exists, never overwritten", the Failure-table row "Directors step fails → logged, swallowed (chain tripwire)", and the §6 doc lines for `enrich criterion-directors` and step 6's chain. Read beside it: `docs/superpowers/handoffs/2026-10-02-criterion-plan-c-handoff.md`. Story 9 of `docs/superpowers/briefs/2026-10-01-criterion-relaunch/brief.md` is this plan's.

## Global Constraints

- Worktree `/Users/jayers/code/movie-brain-dev`, branch `feature/STORY-50-criterion-plan-b` (head `74d257f` when this plan was written). Never touch `/Users/jayers/code/movie-brain`.
- No live database writes and no sync run against `~/.config/movie-brain` in this build. Tests use the `repo` / `config_dir` fixtures only.
- No schema change, no migration, no stamp (spec D8).
- Fill-only: `films.director` is written ONLY when it is NULL and the film's OMDb record names no director (`NULLIF(json_extract(o.payload, '$.Director'), 'N/A')` is NULL — the exact expression the dashboard's `COALESCE` uses, `database.py:331`). Never an empty string: `JwMedia.directors` joined with `", "`, and an empty tuple writes nothing (the rule `criterion_walk._director` follows).
- One JW call per film per run. A JW 404 or a JW failure for one film never stops the others; nothing in this step can change an exit code.
- Fixture SHAPES come from real captures: the JW records `tests/fixtures/criterion/jw-media.3ehCWylD.json` and `jw-media.5pVD2vhU.json` (asked 2026-10-02, prose blanked by `strip_descriptions.py`, committed with this plan) and the OMDb payloads `tests/fixtures/omdb/the-horse-in-focus.json` (`"Director":"N/A"`) and `mistress-dispeller.json` (`"Director":"Elizabeth Lo"`) copied from the live DB read-only, `Plot` blanked. Synthetic only where no real answer exists (404, failure, a record with no director, a director we hold).
- Every `.md` written: never hard-wrap prose (one paragraph = one line).
- Commits: one short line about WHY, then a blank line and `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- `uv run ruff check src tests` shows no NEW errors (16 pre-existing) before every commit; `uv run mypy src` shows only main's 3 pre-existing errors. Line length 120 in `src`; `tests/*` ignores E501.
- Before the first test run in a fresh shell: `cd /Users/jayers/code/movie-brain-dev && uv sync --extra semantic`. Baseline on `74d257f`: **2050 passed**, 4 pre-existing warnings.

## Review Focus

1. **The step runs before `criterion bridge --apply`** (today's live state: 0 mediaids) → films hold only old `http…` links; a reasonable person expects no JW call and nothing written, not a lookup by URL. Test in Task 1 (old links are not on the worklist).
2. **A film holding two mediaids** (Eve's Bayou #1150, Dr. Dolittle #1285, Darwin #759) → asked ONCE, by the lowest mediaid, never twice per run. Test in Task 1.
3. **OMDb's three ways of having no director** — no `omdb` row at all, a not-found row with a NULL payload (#735's shape), and `"Director":"N/A"` (#1766's shape) — all count as "no director shown". Test in Task 1.
4. **A merged-away or hidden holder** → never asked and never written (the dashboard never shows it). Test in Task 1.
5. **The film gained a director between the worklist read and the write** (an OMDb lookup or a human, in another process) → the guarded `UPDATE` writes nothing and the run says so. Test in Task 1 (`fill_criterion_director` returns False on a held director and on an OMDb director).

## Measured numbers this plan builds against (re-derived 2026-10-02, read-only)

Computed from the live DB (`sqlite3 … ?mode=ro`) joined to the bridge dry run's saved answers (`<config_dir>/criterion-bridge.jsonl`, 3,095 lines, classified with `criterion_site.classify_forward`) and `catalog-2026-10-01.json`. The worklist is empty on the live DB today (0 mediaids held); these are the films that WILL qualify once `criterion bridge --apply` runs.

| Fact | Number |
|---|---|
| Old links forwarding to a film / 404 / supplement | 2,836 / 250 / 9 |
| Films that will hold a mediaid (none disposed) | 2,833 |
| … of which `films.director` is NULL | 106 (105 in the Oct 1 catalog) |
| … of which the dashboard already shows OMDb's director (left untouched) | 103 |
| … of which show no director at all → the worklist | **3** |
| Empty-string `films.director` or OMDb `Director` anywhere | 0 |

The three (unchanged from spec D8 — the spec's 124 / 117 / 7 counted films before the bridge; the 4 others it named have no working link and depart, so they never hold a mediaid):

| Film | Mediaid | OMDb row | JW `director` (asked 2026-10-02) | Written |
|---|---|---|---|---|
| Keeping Secrets Will Destroy You #735 (2023) | `3ehCWylD` | not found, payload NULL | `["Ryan Daly","Will Oldham"]` | `Ryan Daly, Will Oldham` |
| The Horse in Focus #1766 (1956) | `5pVD2vhU` | `"Director":"N/A"` | `["Various"]` | `Various` (ruling C1) |
| The IX Olympiad in Amsterdam #1777 (1928) | `dYbj5nMq` | `"Director":"N/A"` | `["Various"]` | `Various` (ruling C1) |

Not knowable until the first walk: a film the walk CREATES takes Criterion's director at birth (D5); one whose JW record lists none joins this worklist and is asked again each run.

## Ledger — rulings this plan makes (surfaced to the owner on the plan page)

- **C1 (needs the owner's yes).** Criterion prints `Various` for two of the three (both Olympic compilation films). The step writes it as printed, so the dashboard shows "Various" where it shows a blank today, and those films leave the worklist. Why: it is what Criterion says, it is true of a compilation, and the walk already writes it for a film it creates (D5 uses the same join). Alternative: treat `Various` as no director — the two stay blank and are asked again every run, and the walk would need the same exception.
- **C2.** The step runs LAST in the chain (credits → vectors → store ids → trailers → directors): it feeds no other step and none feeds it. The chain's line gains `· directors: N of M` (filled of asked), `directors: skipped` when no JW site was handed in (a test or an application caller that passes none).
- **C3.** `enrich criterion-directors` is dry run by default (`--apply` writes), like every other `enrich` verb; the chain applies. The verb always exits 0, like `enrich credits` and `enrich trailers`.
- **C4.** A film holding two mediaids is asked by the lowest (`MIN(value)`), one call. No fallback to the second mediaid on a 404 or an empty answer — "one JW call per film per run" (D8).
- **C5.** No abort-after-N-failures: the worklist is a handful (3), each failure is logged and counted, and the film is asked again next run.
- **C6.** The fill guard lives in the `UPDATE` itself (director still NULL, OMDb still names none, at write time), so no race can overwrite a director someone now sees.
- **C7.** A disposed holder (merged away or hidden) is not on the worklist; a merge survivor that holds no mediaid itself is not either (the bridge binds canonical films, so this is 0 today).

## Plan B minors picked up

None: Plan C touches `catch_up.py`, `cli.py`'s chain builder and `enrich` group, `database.py` (two new methods) and `criterion_fakes.py` (one helper) — none of the deferred minors' code. They stay on the handoff's record.

---

## File map

| File | Responsibility |
|---|---|
| Modify `src/movie_brain/infrastructure/database.py` | `DirectorTarget`, `_NO_OMDB_DIRECTOR`, `films_needing_criterion_director`, `fill_criterion_director` |
| Create `tests/unit/test_criterion_directors_repository.py` | the worklist's edges and the guarded write |
| Create `src/movie_brain/application/criterion_directors.py` | `MediaSource`, `DirectorsReport`, `fill_criterion_directors` |
| Create `tests/features/criterion_directors.feature`, `tests/step_defs/test_criterion_directors.py` | story 9 as scenarios |
| Modify `tests/criterion_fakes.py` | `captured(mediaid)` — a JW record exactly as captured |
| Modify `src/movie_brain/application/catch_up.py` | the fifth step and its word in `line()` |
| Modify `tests/unit/test_catch_up.py` | order, line, skip and tripwire for the new step |
| Modify `src/movie_brain/cli.py` | `_catch_up_chain` hands in a JW site; `enrich criterion-directors` |
| Modify `tests/unit/test_cli.py` | the verb's dry run / apply; the chain receives a site |
| Modify `CLAUDE.md`, `.claude/rules/sync-flow.md`, `docs/backlog.md`, the spec | docs (Task 4) |

Already in the tree, committed with this plan: `tests/fixtures/criterion/jw-media.3ehCWylD.json`, `tests/fixtures/criterion/jw-media.5pVD2vhU.json`, `tests/fixtures/omdb/the-horse-in-focus.json`, `tests/fixtures/omdb/mistress-dispeller.json`, and the two JW captures under `docs/superpowers/research/2026-10-01-criterion-relaunch/`.

---

### Task 1: The worklist and the guarded write

**Files:**
- Modify: `src/movie_brain/infrastructure/database.py` (beside `CreditsTarget` near the top for the type; beside `criterion_review_values` (~line 967) for the methods)
- Test: `tests/unit/test_criterion_directors_repository.py`

**Interfaces:**
- Consumes: `Repository.create_film`, `set_external_id`, `upsert_omdb`, `tombstone_film`; `_NOT_DISPOSED` (`database.py:230`).
- Produces:
  - `class DirectorTarget(NamedTuple): film_id: int; title: str; mediaid: str`
  - `Repository.films_needing_criterion_director(self) -> list[DirectorTarget]` — ordered by film id.
  - `Repository.fill_criterion_director(self, film_id: int, director: str) -> bool` — True when the row was written.

Fixture arithmetic: every test film gets its own mediaid (UNIQUE(authority, value) across films). Test 1 seeds three films A/B/C with no omdb row / not-found row / N/A payload → worklist `[A, B, C]`. Test 2 seeds D (our director) and E (Elizabeth Lo from the Mistress Dispeller payload) → worklist `[]`. Test 3: one film with only `https://www.criterionchannel.com/trio`, one with no criterion id → `[]`. Test 4: one film holding `dYbj5nMq` and `5pVD2vhU` → one target, mediaid `5pVD2vhU` (`'5'` sorts before `'d'` in ASCII). Test 5: a tombstoned holder → `[]`. Test 6: fill A → True, `Ryan Daly, Will Oldham`; fill A again with `X` → False, unchanged; fill E → False, E stays NULL.

- [ ] **Step 1: Write the failing tests**

```python
"""The directors worklist (spec 2026-10-01 D8): films holding a Criterion mediaid whose director
the owner sees NOWHERE — no `films.director` and no OMDb director (the dashboard shows
`COALESCE(films.director, OMDb's)`). Payload shapes are real: `tests/fixtures/omdb/`."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from movie_brain.domain.models import Film, OmdbRating

OMDB = Path(__file__).parent.parent / "fixtures" / "omdb"
D = date(2026, 10, 3)


def _film(repo, title, mediaids, *, director=None, omdb=None):
    fid = repo.create_film(Film(title, 2000, director, ""))
    assert fid is not None
    for m in mediaids:
        repo.set_external_id(fid, "criterion", m, D)
    if omdb == "not-found":  # Keeping Secrets Will Destroy You #735: found = 0, payload NULL
        repo.upsert_omdb(fid, OmdbRating(None, None, False), D)
    elif omdb is not None:
        repo.upsert_omdb(fid, OmdbRating(5.3, None, True, payload=(OMDB / omdb).read_text()), D)
    return fid


def _director(repo, fid):
    with sqlite3.connect(repo.db_path) as c:
        return c.execute("SELECT director FROM films WHERE id = ?", (fid,)).fetchone()[0]


def test_no_omdb_row_a_not_found_row_and_na_all_show_no_director(repo):
    a = _film(repo, "No Omdb Row", ["aaaaaaa1"])
    b = _film(repo, "Keeping Secrets Will Destroy You", ["3ehCWylD"], omdb="not-found")
    c = _film(repo, "The Horse in Focus", ["5pVD2vhU"], omdb="the-horse-in-focus.json")
    got = repo.films_needing_criterion_director()
    assert [(t.film_id, t.mediaid) for t in got] == [(a, "aaaaaaa1"), (b, "3ehCWylD"), (c, "5pVD2vhU")]
    assert got[1].title == "Keeping Secrets Will Destroy You"


def test_a_director_anyone_can_see_keeps_the_film_off_the_worklist(repo):
    _film(repo, "Nadja", ["nadjaXX1"], director="Michael Almereyda")
    _film(repo, "Mistress Dispeller", ["vuGxAj8b"], omdb="mistress-dispeller.json")
    assert repo.films_needing_criterion_director() == []


def test_an_old_link_is_not_a_mediaid_so_nothing_qualifies_before_the_bridge(repo):
    _film(repo, "Trio", ["https://www.criterionchannel.com/trio"])
    _film(repo, "No Criterion Id", [])
    assert repo.films_needing_criterion_director() == []


def test_a_film_holding_two_mediaids_is_asked_once_by_the_lowest(repo):
    fid = _film(repo, "Two Cuts", ["dYbj5nMq", "5pVD2vhU"])
    got = repo.films_needing_criterion_director()
    assert [(t.film_id, t.mediaid) for t in got] == [(fid, "5pVD2vhU")]


def test_a_hidden_holder_is_never_asked(repo):
    fid = _film(repo, "Hidden", ["hiddenX1"])
    repo.tombstone_film(fid, D)
    assert repo.films_needing_criterion_director() == []


def test_the_write_lands_only_in_a_blank_no_one_fills(repo):
    a = _film(repo, "Keeping Secrets Will Destroy You", ["3ehCWylD"], omdb="not-found")
    e = _film(repo, "Mistress Dispeller", ["vuGxAj8b"], omdb="mistress-dispeller.json")
    assert repo.fill_criterion_director(a, "Ryan Daly, Will Oldham") is True
    assert _director(repo, a) == "Ryan Daly, Will Oldham"
    assert repo.fill_criterion_director(a, "X") is False  # ours now: never overwritten
    assert _director(repo, a) == "Ryan Daly, Will Oldham"
    assert repo.fill_criterion_director(e, "X") is False  # OMDb's shows: never shadowed
    assert _director(repo, e) is None
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/unit/test_criterion_directors_repository.py -q`
Expected: 6 FAIL with `AttributeError: 'Repository' object has no attribute 'films_needing_criterion_director'` (and `fill_criterion_director`).

- [ ] **Step 3: Implement**

Beside the other `NamedTuple` targets near the top of `database.py`:

```python
class DirectorTarget(NamedTuple):
    """One film the owner sees no director for, and the Criterion id to ask JW about (D8)."""

    film_id: int
    title: str
    mediaid: str
```

Beside `_NOT_DISPOSED` (`database.py:230`):

```python
# The film's OMDb record names no director: no row, a not-found row (payload NULL) or "N/A" —
# the exact expression the dashboard's COALESCE reads (`films_view`), so "no director" here is
# "no director on screen". `films.id` (not an alias) so the UPDATE can use it too.
_NO_OMDB_DIRECTOR = (
    "NOT EXISTS (SELECT 1 FROM omdb o WHERE o.film_id = films.id "
    "AND NULLIF(json_extract(o.payload, '$.Director'), 'N/A') IS NOT NULL)"
)
```

Beside `criterion_review_values`:

```python
    def films_needing_criterion_director(self) -> list[DirectorTarget]:
        """Films holding a Criterion mediaid whose director the owner sees nowhere: no
        `films.director` and no OMDb director (spec 2026-10-01 D8). Old `http…` links are not
        mediaids, so nothing qualifies before `criterion bridge --apply`. A film holding two
        mediaids is asked by the lowest — one JW call per film. Disposed films are not shown,
        so they are not asked. No stamp: a film JW names no director for comes back next run."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT films.id, films.title, MIN(x.value) AS mediaid FROM films "
                "JOIN external_ids x ON x.film_id = films.id AND x.authority = 'criterion' "
                "AND x.value NOT LIKE 'http%' "
                f"WHERE films.director IS NULL AND {_NO_OMDB_DIRECTOR} "
                "AND NOT EXISTS (SELECT 1 FROM film_disposition d WHERE d.film_id = films.id) "
                "GROUP BY films.id ORDER BY films.id"
            ).fetchall()
        return [DirectorTarget(int(r["id"]), str(r["title"]), str(r["mediaid"])) for r in rows]

    def fill_criterion_director(self, film_id: int, director: str) -> bool:
        """Write Criterion's director into a blank no one fills — guarded in the UPDATE itself,
        so a director that appeared since the worklist was read (ours or OMDb's) is never
        overwritten or shadowed. True when written."""
        if not director:
            raise ValueError("an empty director is never written — leave the film NULL")
        with self._conn() as c:
            cur = c.execute(
                f"UPDATE films SET director = ? WHERE id = ? AND director IS NULL AND {_NO_OMDB_DIRECTOR}",
                (director, film_id),
            )
            return cur.rowcount == 1
```

(`_NOT_DISPOSED` is written against the alias `f`; this query spells the same test against `films` because `_NO_OMDB_DIRECTOR` must also work inside the `UPDATE`, where SQLite has no alias.)

- [ ] **Step 4: Run them to verify they pass**

Run: `uv run pytest tests/unit/test_criterion_directors_repository.py -q`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
uv run ruff check src tests && git add src/movie_brain/infrastructure/database.py tests/unit/test_criterion_directors_repository.py
git commit -m "The directors worklist: films with a mediaid and no director on screen, written only into a blank no one fills

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `fill_criterion_directors` — story 9 as scenarios

**Files:**
- Create: `src/movie_brain/application/criterion_directors.py`
- Modify: `tests/criterion_fakes.py` (add `captured`)
- Create: `tests/features/criterion_directors.feature`, `tests/step_defs/test_criterion_directors.py`

**Interfaces:**
- Consumes: Task 1's `films_needing_criterion_director`, `fill_criterion_director`; `criterion_site.JwMedia`, `CriterionError`; `FakeSite` (its `media()` answers `media_by_id`, None for an absent id = JW's 404, raises `CriterionError` for `media_fails`; `media_calls` lists what was asked).
- Produces:
  - `class MediaSource(Protocol): def media(self, mediaid: str) -> JwMedia | None`
  - `@dataclass(frozen=True) class DirectorsReport: scanned: int = 0; filled: int = 0; no_director: int = 0; gone: int = 0; failed: int = 0`
  - `fill_criterion_directors(repo: Repository, site: MediaSource, *, apply: bool = False, log: Callable[[str], None] = _stderr) -> DirectorsReport`
  - `criterion_fakes.captured(mediaid: str) -> JwMedia`

Fixture arithmetic, per scenario (the report line is `scanned, filled, without a director, not on JW, failed`):
1. #735 → `1, 1, 0, 0, 0`; director `Ryan Daly, Will Oldham` (the capture's `["Ryan Daly","Will Oldham"]` joined).
2. #1766 with the N/A payload → director `Various` (capture `["Various"]`).
3. Mistress Dispeller (2025) with Elizabeth Lo's payload → not on the worklist: `0, 0, 0, 0, 0`, no JW call, `films.director` stays NULL.
4. Nadja (1994) held as "Michael Almereyda" → not on the worklist, no JW call, unchanged.
5. #735 run twice → JW asked about `3ehCWylD` once; the second report `0, 0, 0, 0, 0`.
6. #1777 with a record naming no director (`media_like(..., directors=())`, the capture with `"director": "[]"`) run twice → asked twice, NULL; each report `1, 0, 1, 0, 0`.
7. Three films created in order Gone Film (`goneXXX1`, absent → 404), Flaky Film (`flakyXX1`, in `media_fails`), #735 → `3, 1, 0, 1, 1`; JW asked `["goneXXX1", "flakyXX1", "3ehCWylD"]` in film-id order; #735 filled; the log names both failing ids.
8. #735 without apply → `1, 1, 0, 0, 0` (counted as it would be filled) and `films.director` still NULL.

- [ ] **Step 1: Add the capture helper to `tests/criterion_fakes.py`**

After `captured_media()`:

```python
def captured(mediaid: str) -> JwMedia:
    """A JW record exactly as JW answered (`tests/fixtures/criterion/jw-media.<mediaid>.json`):
    `3ehCWylD` and `5pVD2vhU` were asked on 2026-10-02 for the directors step (spec D8)."""
    return parse_media(json.loads((FIX / f"jw-media.{mediaid}.json").read_text()), mediaid)
```

- [ ] **Step 2: Write the feature**

`tests/features/criterion_directors.feature`:

```gherkin
Feature: Criterion's directors fill the blanks no one else fills

  The dashboard shows our director, else OMDb's. A film that holds a Criterion id
  and shows neither takes the director Criterion's own record (JW Player) names —
  only there, and never over a director anyone can already see (spec 2026-10-01 D8,
  story 9). It runs last in the catch-up chain and by hand as
  `enrich criterion-directors`. No stamp: a film JW names nobody for is asked again.

  Scenario: A film OMDb found nothing for takes Criterion's directors (Keeping Secrets Will Destroy You #735)
    Given the film "Keeping Secrets Will Destroy You" (2023) holds Criterion id "3ehCWylD"
    And OMDb found nothing for "Keeping Secrets Will Destroy You"
    And JW answers for "3ehCWylD" as captured on 2026-10-02
    When I fill Criterion directors with apply
    Then the director of "Keeping Secrets Will Destroy You" is "Ryan Daly, Will Oldham"
    And the report reads 1 scanned, 1 filled, 0 without a director, 0 not on JW, 0 failed

  Scenario: OMDb's "N/A" is no director (The Horse in Focus #1766)
    Given the film "The Horse in Focus" (1956) holds Criterion id "5pVD2vhU"
    And OMDb's record for "The Horse in Focus" is the captured "the-horse-in-focus.json"
    And JW answers for "5pVD2vhU" as captured on 2026-10-02
    When I fill Criterion directors with apply
    Then the director of "The Horse in Focus" is "Various"

  Scenario: A director OMDb shows is never replaced, and JW is not asked (story 9's 103)
    Given the film "Mistress Dispeller" (2025) holds Criterion id "vuGxAj8b"
    And OMDb's record for "Mistress Dispeller" is the captured "mistress-dispeller.json"
    And JW lists "vuGxAj8b" with director "Someone Else"
    When I fill Criterion directors with apply
    Then "Mistress Dispeller" has no director of its own
    And JW was asked about nothing
    And the report reads 0 scanned, 0 filled, 0 without a director, 0 not on JW, 0 failed

  Scenario: A director we hold is never overwritten
    Given the film "Nadja" (1994) directed by "Michael Almereyda" holds Criterion id "nadjaXX1"
    And JW lists "nadjaXX1" with director "Someone Else"
    When I fill Criterion directors with apply
    Then the director of "Nadja" is "Michael Almereyda"
    And JW was asked about nothing

  Scenario: A filled film is never asked again
    Given the film "Keeping Secrets Will Destroy You" (2023) holds Criterion id "3ehCWylD"
    And JW answers for "3ehCWylD" as captured on 2026-10-02
    When I fill Criterion directors with apply
    And I fill Criterion directors with apply
    Then JW was asked about "3ehCWylD" once
    And the report reads 0 scanned, 0 filled, 0 without a director, 0 not on JW, 0 failed

  Scenario: A record naming no director leaves the blank, and the next run asks again
    Given the film "The IX Olympiad in Amsterdam" (1928) holds Criterion id "dYbj5nMq"
    And JW lists "dYbj5nMq" with no director
    When I fill Criterion directors with apply
    And I fill Criterion directors with apply
    Then "The IX Olympiad in Amsterdam" has no director of its own
    And JW was asked about "dYbj5nMq" twice
    And the report reads 1 scanned, 0 filled, 1 without a director, 0 not on JW, 0 failed

  Scenario: A JW 404 for one film and a JW failure for another never stop the third
    Given the film "Gone Film" (1960) holds Criterion id "goneXXX1"
    And the film "Flaky Film" (1961) holds Criterion id "flakyXX1"
    And the film "Keeping Secrets Will Destroy You" (2023) holds Criterion id "3ehCWylD"
    And JW has no record of "goneXXX1"
    And JW fails for "flakyXX1"
    And JW answers for "3ehCWylD" as captured on 2026-10-02
    When I fill Criterion directors with apply
    Then the director of "Keeping Secrets Will Destroy You" is "Ryan Daly, Will Oldham"
    And JW was asked about "goneXXX1", "flakyXX1", "3ehCWylD" in that order
    And the report reads 3 scanned, 1 filled, 0 without a director, 1 not on JW, 1 failed
    And the log names "goneXXX1" and "flakyXX1"

  Scenario: A dry run asks and reports, and writes nothing
    Given the film "Keeping Secrets Will Destroy You" (2023) holds Criterion id "3ehCWylD"
    And JW answers for "3ehCWylD" as captured on 2026-10-02
    When I fill Criterion directors without applying
    Then "Keeping Secrets Will Destroy You" has no director of its own
    And the report reads 1 scanned, 1 filled, 0 without a director, 0 not on JW, 0 failed
```

- [ ] **Step 3: Write the step definitions**

`tests/step_defs/test_criterion_directors.py`:

```python
"""Criterion's directors (spec 2026-10-01 D8, story 9). Assertions read the DATABASE; JW is the
`FakeSite` carrying the real captured records, OMDb's payloads are real ones from the live DB."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest
from criterion_fakes import FakeSite, captured, media_like
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.criterion_directors import fill_criterion_directors
from movie_brain.domain.models import Film, OmdbRating

scenarios("../features/criterion_directors.feature")

OMDB = Path(__file__).parent.parent / "fixtures" / "omdb"
DAY = date(2026, 10, 3)
TIMES = {"once": 1, "twice": 2}


@pytest.fixture
def ctx(repo):
    return {"repo": repo, "site": FakeSite(), "films": {}, "reports": [], "logs": []}


def _seed(ctx, title, year, director, mediaid):
    fid = ctx["repo"].create_film(Film(title, year, director, ""))
    assert fid is not None
    ctx["repo"].set_external_id(fid, "criterion", mediaid, DAY)
    ctx["films"][title] = fid


def _director(ctx, title):
    with sqlite3.connect(ctx["repo"].db_path) as c:
        return c.execute("SELECT director FROM films WHERE id = ?", (ctx["films"][title],)).fetchone()[0]


# Given ---------------------------------------------------------------------


@given(parsers.parse('the film "{title}" ({year:d}) holds Criterion id "{mediaid}"'))
def film_holding(ctx, title, year, mediaid):
    _seed(ctx, title, year, None, mediaid)


@given(parsers.parse('the film "{title}" ({year:d}) directed by "{director}" holds Criterion id "{mediaid}"'))
def film_directed_holding(ctx, title, year, director, mediaid):
    _seed(ctx, title, year, director, mediaid)


@given(parsers.parse('OMDb found nothing for "{title}"'))
def omdb_not_found(ctx, title):
    ctx["repo"].upsert_omdb(ctx["films"][title], OmdbRating(None, None, False), DAY)


@given(parsers.parse('OMDb\'s record for "{title}" is the captured "{name}"'))
def omdb_captured(ctx, title, name):
    ctx["repo"].upsert_omdb(ctx["films"][title], OmdbRating(5.3, None, True, payload=(OMDB / name).read_text()), DAY)


@given(parsers.parse('JW answers for "{mediaid}" as captured on 2026-10-02'))
def jw_captured(ctx, mediaid):
    ctx["site"].media_by_id[mediaid] = captured(mediaid)


@given(parsers.parse('JW lists "{mediaid}" with director "{director}"'))
def jw_lists_director(ctx, mediaid, director):
    ctx["site"].media_by_id[mediaid] = media_like(mediaid, "Any Title", directors=(director,))


@given(parsers.parse('JW lists "{mediaid}" with no director'))
def jw_lists_none(ctx, mediaid):
    ctx["site"].media_by_id[mediaid] = media_like(mediaid, "Any Title", directors=())


@given(parsers.parse('JW has no record of "{mediaid}"'))
def jw_404(ctx, mediaid):
    ctx["site"].media_by_id.pop(mediaid, None)  # FakeSite answers an absent id like JW's 404


@given(parsers.parse('JW fails for "{mediaid}"'))
def jw_fails(ctx, mediaid):
    ctx["site"].media_fails.add(mediaid)


# When ----------------------------------------------------------------------


def _run(ctx, apply):
    report = fill_criterion_directors(ctx["repo"], ctx["site"], apply=apply, log=ctx["logs"].append)
    ctx["reports"].append(report)


@when("I fill Criterion directors with apply")
def fill_apply(ctx):
    _run(ctx, True)


@when("I fill Criterion directors without applying")
def fill_dry(ctx):
    _run(ctx, False)


# Then ----------------------------------------------------------------------


@then(parsers.parse('the director of "{title}" is "{director}"'))
def director_is(ctx, title, director):
    assert _director(ctx, title) == director


@then(parsers.parse('"{title}" has no director of its own'))
def no_director(ctx, title):
    assert _director(ctx, title) is None


@then("JW was asked about nothing")
def asked_nothing(ctx):
    assert ctx["site"].media_calls == []


@then(parsers.re(r'JW was asked about "(?P<mediaid>[^"]+)" (?P<times>once|twice)$'))
def asked_times(ctx, mediaid, times):
    assert ctx["site"].media_calls == [mediaid] * TIMES[times]


@then(parsers.parse('JW was asked about "{a}", "{b}", "{c}" in that order'))
def asked_in_order(ctx, a, b, c):
    assert ctx["site"].media_calls == [a, b, c]


@then(parsers.parse(
    "the report reads {scanned:d} scanned, {filled:d} filled, {none:d} without a director, "
    "{gone:d} not on JW, {failed:d} failed"
))
def report_reads(ctx, scanned, filled, none, gone, failed):
    r = ctx["reports"][-1]
    assert (r.scanned, r.filled, r.no_director, r.gone, r.failed) == (scanned, filled, none, gone, failed)


@then(parsers.parse('the log names "{a}" and "{b}"'))
def log_names(ctx, a, b):
    assert any(a in m for m in ctx["logs"]) and any(b in m for m in ctx["logs"])
```

Note for the implementer: the once/twice step is a regex on purpose — a plain `parsers.parse('JW was asked about "{mediaid}" {times}')` would ALSO match the in-that-order line (`{mediaid}` swallowing `goneXXX1", "flakyXX1", "3ehCWylD`), and pytest-bdd would be free to pick either.

- [ ] **Step 4: Run them to verify they fail**

Run: `uv run pytest tests/step_defs/test_criterion_directors.py -q`
Expected: collection ERROR, `ModuleNotFoundError: No module named 'movie_brain.application.criterion_directors'`.

- [ ] **Step 5: Implement `src/movie_brain/application/criterion_directors.py`**

```python
"""Criterion's directors (spec 2026-10-01 D8, story 9): a film that holds a Criterion mediaid and
shows the owner NO director — no `films.director` and no OMDb director, the two the dashboard's
COALESCE reads — takes the director Criterion's own JW Player record names. Nothing anyone can
already see ever changes: the worklist excludes it and the write is guarded again in the UPDATE.

One JW call per film per run, no stamp: the worklist is a handful (3 when measured on 2026-10-02),
and a film whose record names nobody is simply asked again next run. A JW 404 or failure for one
film never stops the others. It runs last in the catch-up chain (`catch_up.py`) under its own
tripwire, and by hand as `movie-brain enrich criterion-directors`."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from movie_brain.infrastructure.criterion_site import CriterionError, JwMedia
from movie_brain.infrastructure.database import Repository


class MediaSource(Protocol):
    """What the step needs of `HttpCriterionSite`: one film's JW record, None on JW's 404."""

    def media(self, mediaid: str) -> JwMedia | None: ...


@dataclass(frozen=True)
class DirectorsReport:
    scanned: int = 0
    filled: int = 0  # on a dry run: would be filled
    no_director: int = 0  # JW answered and names nobody: asked again next run
    gone: int = 0  # JW answered 404
    failed: int = 0  # JW did not answer usably: asked again next run


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


def fill_criterion_directors(
    repo: Repository, site: MediaSource, *, apply: bool = False, log: Callable[[str], None] = _stderr
) -> DirectorsReport:
    scanned = filled = no_director = gone = failed = 0
    for t in repo.films_needing_criterion_director():
        scanned += 1
        try:
            media = site.media(t.mediaid)
        except CriterionError as exc:
            log(f"  #{t.film_id} {t.title!r} ({t.mediaid}): JW lookup failed, asked again next run: {exc}")
            failed += 1
            continue
        if media is None:
            log(f"  #{t.film_id} {t.title!r} ({t.mediaid}): JW has no record of it")
            gone += 1
            continue
        # The join the walk uses for a film it creates (`criterion_walk._director`): never "".
        director = ", ".join(media.directors)
        if not director:
            log(f"  #{t.film_id} {t.title!r} ({t.mediaid}): JW names no director, asked again next run")
            no_director += 1
            continue
        if apply and not repo.fill_criterion_director(t.film_id, director):
            log(f"  #{t.film_id} {t.title!r}: gained a director since the worklist was read — left as it is")
            continue
        log(f"  #{t.film_id} {t.title!r}: {director}")
        filled += 1
    return DirectorsReport(scanned, filled, no_director, gone, failed)
```

- [ ] **Step 6: Run them to verify they pass**

Run: `uv run pytest tests/step_defs/test_criterion_directors.py tests/unit/test_criterion_directors_repository.py -q`
Expected: 14 passed (8 scenarios + 6 unit).

- [ ] **Step 7: Commit**

```bash
uv run ruff check src tests && git add src/movie_brain/application/criterion_directors.py tests/criterion_fakes.py tests/features/criterion_directors.feature tests/step_defs/test_criterion_directors.py
git commit -m "Directors from Criterion's own record fill only the blanks the owner sees; one bad answer never stops the rest

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The chain's fifth step and `enrich criterion-directors`

**Files:**
- Modify: `src/movie_brain/application/catch_up.py`
- Modify: `src/movie_brain/cli.py` (`_catch_up_chain` ~line 182; the `enrich` group after `enrich trailers` ~line 1752)
- Test: `tests/unit/test_catch_up.py`, `tests/unit/test_cli.py`

**Interfaces:**
- Consumes: Task 2's `MediaSource`, `DirectorsReport`, `fill_criterion_directors`; `criterion_site.HttpCriterionSite(session)`.
- Produces:
  - `CatchUpReport.directors: DirectorsReport | None = None` (last field); `line()` ends `· directors: {filled} of {scanned}` or `· directors: skipped`.
  - `catch_up(..., embedder, criterion: MediaSource | None = None, log)` — keyword, default None, so every existing caller is unchanged.
  - CLI: `movie-brain enrich criterion-directors [--apply]`.

Fixture arithmetic for `test_catch_up.py`: the fake directors step returns `DirectorsReport(scanned=3, filled=2, no_director=1)` → `directors: 2 of 3`. The existing first test's line becomes `credits: 3 · vectors: 2 · store ids: 1 of 3 · trailers: 2 of 3 · directors: 2 of 3`; the missing-dependency test's line becomes `credits: skipped · vectors: skipped · store ids: 1 of 3 · trailers: skipped · directors: skipped`.

- [ ] **Step 1: Update and add the chain tests in `tests/unit/test_catch_up.py`**

Add the import `from movie_brain.application.criterion_directors import DirectorsReport`. In the `calls` fixture, after the trailers line:

```python
    monkeypatch.setattr(module, "fill_criterion_directors", fake("directors", DirectorsReport(scanned=3, filled=2, no_director=1)))
```

Replace the three tests and add a fourth:

```python
def test_the_full_boat_runs_in_order_and_applies(repo, calls):
    report = catch_up(
        repo, D, tmdb=object(), cheapcharts=object(), itunes=object(), embedder=object(), criterion=object(),
        log=lambda m: None,
    )
    # The store id comes BEFORE the trailer (Apple's preview is found by store id), credits before
    # the vector (the vector is made from the prose credits bring). Directors feed nothing: last.
    assert [name for name, _ in calls] == ["credits", "embed", "store", "trailers", "directors"]
    assert all(kw["apply"] is True for _, kw in calls)
    assert (report.credits.enriched, report.embedded.embedded, report.store.resolved, report.trailers.with_youtube) == (3, 2, 1, 2)
    assert report.directors.filled == 2
    assert report.line() == "credits: 3 · vectors: 2 · store ids: 1 of 3 · trailers: 2 of 3 · directors: 2 of 3"


def test_a_missing_dependency_skips_its_steps_and_says_so(repo, calls):
    logged: list[str] = []
    report = catch_up(repo, D, tmdb=None, cheapcharts=object(), itunes=object(), embedder=None, log=logged.append)
    assert [name for name, _ in calls] == ["store"]
    assert report.credits is None and report.embedded is None and report.trailers is None and report.directors is None
    assert any("no TMDB token" in m for m in logged) and any("semantic" in m for m in logged)
    assert report.line() == "credits: skipped · vectors: skipped · store ids: 1 of 3 · trailers: skipped · directors: skipped"


def test_one_step_failing_never_stops_the_others(repo, calls, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("cheapcharts exploded")

    monkeypatch.setattr(module, "resolve_itunes_ids", boom)
    logged: list[str] = []
    report = catch_up(
        repo, D, tmdb=object(), cheapcharts=object(), itunes=object(), embedder=object(), criterion=object(),
        log=logged.append,
    )
    assert [name for name, _ in calls] == ["credits", "embed", "trailers", "directors"]
    assert report.store is None and any("store ids failed" in m and "exploded" in m for m in logged)


def test_the_directors_step_failing_is_logged_and_swallowed(repo, calls, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("jw exploded")

    monkeypatch.setattr(module, "fill_criterion_directors", boom)
    logged: list[str] = []
    report = catch_up(
        repo, D, tmdb=object(), cheapcharts=object(), itunes=object(), embedder=object(), criterion=object(),
        log=logged.append,
    )
    assert [name for name, _ in calls] == ["credits", "embed", "store", "trailers"]
    assert report.directors is None and any("criterion directors failed" in m and "jw exploded" in m for m in logged)
    assert report.line().endswith("· directors: skipped")
```

- [ ] **Step 2: Add the CLI tests to `tests/unit/test_cli.py`** (after `test_enrich_trailers_is_dry_run_by_default_and_prints_the_report`)

```python
def test_enrich_criterion_directors_is_dry_run_by_default_and_prints_the_report(config_dir, monkeypatch):
    from movie_brain.application.criterion_directors import DirectorsReport
    from movie_brain.infrastructure.criterion_site import HttpCriterionSite

    calls = {}

    def fake(repo, site, **kw):
        calls.update(kw, site=site)
        return DirectorsReport(scanned=3, filled=1, no_director=0, gone=1, failed=1)

    monkeypatch.setattr("movie_brain.cli.fill_criterion_directors", fake)
    r = runner.invoke(app, ["enrich", "criterion-directors"])
    assert r.exit_code == 0, r.output
    assert calls["apply"] is False and isinstance(calls["site"], HttpCriterionSite)
    assert "scanned: 3 · filled: 1 · no director: 0 · not on JW: 1 · failed: 1" in r.output and "dry run" in r.output

    r = runner.invoke(app, ["enrich", "criterion-directors", "--apply"])
    assert r.exit_code == 0, r.output
    assert calls["apply"] is True and "dry run" not in r.output


def test_the_catch_up_chain_hands_the_directors_step_a_jw_site(repo, monkeypatch):
    import movie_brain.cli as cli
    from movie_brain.application.catch_up import CatchUpReport
    from movie_brain.infrastructure.criterion_site import HttpCriterionSite

    seen = {}

    def fake_catch_up(repo, today, **kw):
        seen.update(kw)
        return CatchUpReport()

    monkeypatch.setattr(cli, "catch_up", fake_catch_up)
    cli._catch_up_chain()(repo, None)
    assert isinstance(seen["criterion"], HttpCriterionSite)
```

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest tests/unit/test_catch_up.py tests/unit/test_cli.py -q -k "catch_up or boat or dependency or failing or directors"`
Expected: FAIL — `AttributeError: <module 'movie_brain.application.catch_up'> has no attribute 'fill_criterion_directors'` from the fixture, and `No such command 'criterion-directors'`.

- [ ] **Step 4: Implement the chain step in `src/movie_brain/application/catch_up.py`**

In the module docstring, after the order block, add one line:

```
  … → directors       (Criterion's director into a blank no one fills — spec 2026-10-01 D8 — last: it feeds nothing)
```

Imports (alphabetical with the others):

```python
from movie_brain.application.criterion_directors import DirectorsReport, MediaSource, fill_criterion_directors
```

`CatchUpReport` gains its last field and `line()` its last word:

```python
@dataclass(frozen=True)
class CatchUpReport:
    """A step's report, or None when the step was skipped or failed."""

    credits: EnrichReport | None = None
    embedded: EmbedReport | None = None
    store: ResolveReport | None = None
    trailers: TrailerReport | None = None
    directors: DirectorsReport | None = None

    def line(self) -> str:
        t, d = self.trailers, self.directors
        return " · ".join([
            f"credits: {self.credits.enriched}" if self.credits else "credits: skipped",
            f"vectors: {self.embedded.embedded}" if self.embedded else "vectors: skipped",
            f"store ids: {self.store.resolved} of {self.store.scanned}" if self.store else "store ids: skipped",
            f"trailers: {t.with_youtube + t.apple_only} of {t.scanned}" if t else "trailers: skipped",
            f"directors: {d.filled} of {d.scanned}" if d else "directors: skipped",
        ])
```

`catch_up` gains the keyword and the step:

```python
def catch_up(
    repo: Repository,
    today: date,
    *,
    tmdb: TmdbClient | None,
    cheapcharts: CheapChartsClient | None,
    itunes: PreviewSource | None,
    embedder: Embedder | None,
    criterion: MediaSource | None = None,
    log: Callable[[str], None],
) -> CatchUpReport:
```

and, after the trailers step:

```python
    directors = None
    if criterion is not None:
        directors = step(
            "criterion directors", lambda: fill_criterion_directors(repo, criterion, apply=True, log=log)
        )
    return CatchUpReport(credits, embedded, store, trailers, directors)
```

(A keyword-only parameter with a default may precede one without in Python — `log` stays required.)

- [ ] **Step 5: Implement the CLI in `src/movie_brain/cli.py`**

Top-level imports (alphabetical with the others):

```python
import requests

from movie_brain.application.criterion_directors import fill_criterion_directors
from movie_brain.infrastructure.criterion_site import HttpCriterionSite
```

(`criterion_bridge_cmd`'s local `import requests` stays; it is now redundant but harmless — remove it only if ruff flags it.)

`_catch_up_chain`'s inner call gains one argument:

```python
    def chain(repo: Repository, tmdb: TmdbClient | None) -> CatchUpReport:
        return catch_up(
            repo, date.today(), tmdb=tmdb, cheapcharts=CheapChartsClient(), itunes=ItunesLookup(),
            embedder=embedder, criterion=HttpCriterionSite(requests.Session()), log=_plain,
        )
```

After `enrich_trailers_cmd`:

```python
@enrich_app.command("criterion-directors")
def enrich_criterion_directors_cmd(
    apply: Annotated[bool, typer.Option("--apply", help="Write the directors (default: dry-run).")] = False,
) -> None:
    """Fill a director from Criterion's own record (JW Player) for every film that holds a
    Criterion id and shows no director at all — neither ours nor OMDb's.

    One JW call per film; a director anyone can already see is never changed. A film Criterion
    names nobody for is asked again next time. Runs by itself at the tail of every sync (the
    catch-up chain); this verb is the same step by hand. Dry-run by default.
    """
    report = fill_criterion_directors(_repo(), HttpCriterionSite(requests.Session()), apply=apply, log=_plain)
    console.print(
        f"scanned: {report.scanned} · filled: {report.filled} · no director: {report.no_director}"
        f" · not on JW: {report.gone} · failed: {report.failed}"
        + ("" if apply else "   (dry run — nothing written)")
    )
```

Update the `CatchUpReport` mention in `_enrich_after_add`'s and `enrich all`'s docstrings only if they list the chain's steps by name: add "and Criterion directors" after "trailers".

- [ ] **Step 6: Run them to verify they pass, then the whole suite**

Run: `uv run pytest tests/unit/test_catch_up.py tests/unit/test_cli.py -q`
Expected: all pass.
Run: `uv run pytest -q`
Expected: **2050 + 6 + 8 + 1 + 2 = 2067 passed** (Task 1's 6, Task 2's 8 scenarios, the new catch-up test, the two CLI tests; the three rewritten catch-up tests replace themselves), 4 pre-existing warnings. If any other test asserted the chain's exact line (`grep -rn "trailers: skipped\|trailers: .* of" tests`), give its expected text the `· directors: …` suffix and say so in the ledger.
Run: `uv run mypy src` → only the 3 pre-existing errors. `uv run ruff check src tests` → no new errors.

- [ ] **Step 7: Commit**

```bash
git add src/movie_brain/application/catch_up.py src/movie_brain/cli.py tests/unit/test_catch_up.py tests/unit/test_cli.py
git commit -m "Criterion directors join the catch-up chain last and get their own enrich verb, so a blank fills without a hand run

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Docs, rules, backlog

**Files:**
- Modify: `CLAUDE.md`, `.claude/rules/sync-flow.md`, `docs/backlog.md` (item 50), `docs/superpowers/specs/2026-10-01-criterion-relaunch-design.md` (D8)

No code; no test. One paragraph = one line in every `.md`.

- [ ] **Step 1: `CLAUDE.md`** — after the `enrich trailers` command line, add:

```
uv run movie-brain enrich criterion-directors [--apply]     # Criterion's own director (JW Player record) for every film that holds a Criterion mediaid and shows NO director — neither `films.director` nor OMDb's; fill-only, a director anyone can see never changes; one JW call per film, no stamp (a film JW names nobody for is asked again); last step of the catch-up chain (spec 2026-10-01 D8); dry run by default
```

In the `sync` command line's comment, change `(credits → vectors → store ids → trailers)` to `(credits → vectors → store ids → trailers → Criterion directors)`; in the `enrich all` line, change `then credits, vectors, store ids, trailers` to `then credits, vectors, store ids, trailers, Criterion directors`.

- [ ] **Step 2: `.claude/rules/sync-flow.md`** — step 6: `credits → vectors → store ids → trailers` becomes `credits → vectors → store ids → trailers → Criterion directors (spec 2026-10-01 D8: `application/criterion_directors.py`, a film holding a mediaid with no `films.director` and no OMDb director takes the JW record's director, fill-only, guarded in the UPDATE; the JW site is built in `cli._catch_up_chain` like the CheapCharts client; no stamp)`. In "Enrichment on add", the chain sentence gains `→ Criterion directors (last: it feeds nothing)` and the printed line becomes `caught up — credits: N · vectors: N · store ids: N of M · trailers: N of M · directors: N of M`.

- [ ] **Step 3: spec D8** — append to the D8 paragraph: `Measured again 2026-10-02 against the bridge dry run (plan C): 2,833 films will hold a mediaid, 106 with NULL films.director, 103 of them showing OMDb's; the worklist is the same 3 (#735, #1766, #1777). JW names "Ryan Daly, Will Oldham" for #735 and "Various" for #1766 and #1777, written as printed (plan C ruling C1).` — adjust the ruling text to the owner's answer on C1.

- [ ] **Step 4: `docs/backlog.md` item 50** — replace `C — directors.` with `C — directors (plan `docs/superpowers/plans/2026-10-02-criterion-relaunch-plan-c.md`, built on the same branch, not merged).`

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md .claude/rules/sync-flow.md docs/backlog.md docs/superpowers/specs/2026-10-01-criterion-relaunch-design.md
git commit -m "Docs follow the directors step: the chain's fifth word, the verb, the re-measured worklist

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Final check (end of the build)

`uv run pytest -q` (2067 passed), `uv run mypy src` (3 pre-existing), `uv run ruff check src tests` (16 pre-existing), `uv run python scripts/thumbprint_benchmark.py --assert` (exit 0), then a whole-branch review of `74d257f..HEAD`. A READ-ONLY sanity run on a COPY of the live DB is allowed (`cp` into the scratchpad, `MOVIE_BRAIN_CONFIG_DIR=<copy dir> uv run movie-brain enrich criterion-directors` — dry run, expected `scanned: 0` since the copy holds no mediaids); never against `~/.config/movie-brain`.

## After the build (not in this session, each on the owner's yes)

1. Gap check point C on the branch head with a migrated database copy (two lineages if the pilot still runs).
2. Darwin #759 repair (owner ruling: two works) — designed, shown row by row, before the bridge apply.
3. Dated backup → `criterion bridge --apply` → before/after counts.
4. Dated backup → `sync` in the background → Criterion arrived / left / to review, the TMDB weekly refresh, and `directors: 3 of 3` on the caught-up line (#735 `Ryan Daly, Will Oldham`, #1766 and #1777 per ruling C1).
