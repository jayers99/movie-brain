# Criterion Relaunch — Plan A (new reader + bridge) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the new Criterion Channel reader (catalog list, JW Player film record, dated leaving page) and the one-shot `movie-brain criterion bridge [--apply] [--retry]` verb that records each stored film's new Criterion id (its *mediaid*), without touching `sync`.

**Architecture:** A NEW infrastructure module `infrastructure/criterion_site.py` holds the three fetchers plus the old-link `HEAD`; the dead VHX module `infrastructure/criterion.py` stays untouched until Plan B, so `sync` and its tests keep importing it. The bridge is an application use case (`application/criterion_bridge.py`) that walks the catalog once for its drift table, asks each stored old URL where it now forwards, keeps every answer in an observation file under the config dir, and on `--apply` writes the mediaids, the listing URLs and any clash review rows in ONE repository transaction.

**Tech Stack:** Python 3.12, requests, `responses` (HTTP mocking), pytest + pytest-bdd, typer, SQLite via `Repository`.

**Spec:** `docs/superpowers/specs/2026-10-01-criterion-relaunch-design.md` (this plan builds §8 Plan A: D1, D3, D7's parser, the JW media fetcher). Stories: `docs/superpowers/briefs/2026-10-01-criterion-relaunch/brief.md` (story 2 is this plan's). Real captured answers: `docs/superpowers/research/2026-10-01-criterion-relaunch/`.

## Global Constraints

- `USER_AGENT = "movie-brain/0.1 (personal watchlist tool)"` on every request (reuse the constant from `infrastructure/criterion.py` by copying the same string; do not import the dead module).
- Catalog calls ≥ 1 s apart; bridge `HEAD`s 0.4 s apart; JW calls ≥ 0.25 s apart. Pace with `movie_brain.infrastructure.cheapcharts.Pacer` (generic clock-based pacer already in the repo).
- 429 → exponential backoff, three tries (sleeps 2 s, 4 s, 8 s through the injected `sleep`), then raise `CriterionError`.
- No network in tests: every HTTP call is mocked with `responses`. Fixture SHAPES come from the real captures (copied into `tests/fixtures/criterion/`), never invented; synthetic data only where no real answer exists (429, half-written observation file, held-by-other).
- No schema change, no migration. No change to `application/sync.py`, `infrastructure/criterion.py`, `tests/unit/test_criterion.py`, `tests/step_defs/test_sync.py`.
- Our `films.title` / `films.year` are never written by anything in this plan.
- Every `.md` written: never hard-wrap prose (one paragraph = one line).
- Commits: one short line about WHY, ending with the `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` trailer. Branch: `feature/STORY-50-criterion-relaunch` (worktree `/Users/jayers/code/movie-brain-dev`).
- Before the first test run in a fresh worktree: `uv sync --extra semantic` (a bare `uv sync` removes the semantic extra).

## Review Focus

1. **The forwarding address comes back absolute or relative** (`https://www.criterionchannel.com/films/X/slug` or `/films/X/slug`, with or without a trailing slash) → the mediaid is parsed the same either way. Test in Task 4.
2. **The run is interrupted halfway (Ctrl-C, laptop sleeps)** → every answer already received is on disk (one line appended and flushed per answer) and a rerun asks only the rest. Test in Task 6.
3. **The observation file's last line is half-written** (killed mid-write) → that line is ignored and its URL asked again; the rest of the file still counts. Test in Task 5.
4. **The old URL sits on a film that was later merged** → the mediaid is written on the merge survivor (canonical film), and the clash check compares canonical films. Test in Task 7.
5. **One film holds two old URLs that forward to the same mediaid** (12 such films live, e.g. Eve's Bayou #1150) → one id row, no review row, no error. Test in Task 7.

---

## File map

| File | Responsibility |
|---|---|
| Create `src/movie_brain/infrastructure/criterion_site.py` | HTTP reader for the new site: `fetch_catalog`, `fetch_media`, `fetch_leaving`, `head_old_url`, the dataclasses they return, `CriterionError` |
| Create `src/movie_brain/application/criterion_bridge.py` | The bridge use case: observation file, classification, drift table, apply |
| Modify `src/movie_brain/infrastructure/database.py` | Two methods: `criterion_old_urls()`, `record_bridge(...)` |
| Modify `src/movie_brain/cli.py` | `criterion` typer group + `bridge` command |
| Create `tests/fixtures/criterion/*` | Copies of the real captures the tests read |
| Create `tests/unit/test_criterion_site.py` | Adapter tests |
| Create `tests/features/criterion_bridge.feature`, `tests/step_defs/test_criterion_bridge.py` | Bridge scenarios |
| Modify `tests/unit/test_cli.py` | CLI wiring test |
| Modify `CLAUDE.md`, `docs/backlog.md` | The new verb line; backlog item 50 |

---

### Task 1: Fixtures + the catalog walk

**Files:**
- Create: `tests/fixtures/criterion/` (copies), `src/movie_brain/infrastructure/criterion_site.py`, `tests/unit/test_criterion_site.py`

**Interfaces:**
- Produces:
  - `class CriterionError(Exception)`
  - `@dataclass(frozen=True) class CatalogItem: mediaid: str; title: str; year: int | None; duration_s: int`
  - `def fetch_catalog(session: requests.Session, pacer: Pacer | None = None, sleep: Callable[[float], None] = time.sleep) -> list[CatalogItem]`
  - constants `BASE = "https://www.criterionchannel.com"`, `CATALOG_URL = BASE + "/api/all-films/results"`, `USER_AGENT`

- [ ] **Step 1: Copy the real captures into test fixtures**

```bash
cd /Users/jayers/code/movie-brain-dev
mkdir -p tests/fixtures/criterion
R=docs/superpowers/research/2026-10-01-criterion-relaunch
cp "$R/all-films-results.page1.trimmed.json" "$R/all-films-results.lastpage.json" "$R/jw-media.L5Z3RaiC.json" "$R/jw-playlist.0WbeKrrA.full.json" "$R/home-2026-10-01.html" "$R/leaving-october-31.html" tests/fixtures/criterion/
ls tests/fixtures/criterion
```

Expected: the six files listed.

- [ ] **Step 2: Write the failing catalog tests**

Create `tests/unit/test_criterion_site.py`:

```python
"""The new Criterion Channel reader (2026-10 relaunch). Fixture shapes are the real captures in
tests/fixtures/criterion/ (copied from docs/superpowers/research/2026-10-01-criterion-relaunch/)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import requests
import responses

from movie_brain.infrastructure.cheapcharts import Pacer
from movie_brain.infrastructure.criterion_site import (
    CATALOG_URL,
    CatalogItem,
    CriterionError,
    fetch_catalog,
)

FIX = Path(__file__).parent.parent / "fixtures" / "criterion"


def _load(name: str):
    return json.loads((FIX / name).read_text())


def _page(items, next_key, total):
    """A catalog page in the captured shape: next key present on every page but the last."""
    first = _load("all-films-results.page1.trimmed.json")
    body = copy.deepcopy(first)
    body["items"] = items
    body["total"] = total
    if next_key is None:
        body["paging"] = {"page_limit": 200}  # the real last page: the key is ABSENT
    else:
        body["paging"] = {"next_pagination_key": next_key, "page_limit": 200}
    return body


def _no_sleep(_s):
    return None


@responses.activate
def test_walks_every_page_until_the_key_is_absent():
    first = _load("all-films-results.page1.trimmed.json")["items"]
    last = _load("all-films-results.lastpage.json")["items"]
    total = len(first) + len(last)
    responses.get(CATALOG_URL, json=_page(first, "2", total))
    responses.get(CATALOG_URL, json=_page(last, None, total))
    items = fetch_catalog(requests.Session(), sleep=_no_sleep)
    assert len(items) == total
    assert items[0] == CatalogItem("L5Z3RaiC", "2 or 3 Things I Know About Her", 1967, 5245)
    assert responses.calls[1].request.params == {"page_limit": "200", "pagination_key": "2"}


@responses.activate
def test_series_count_toward_total_but_are_not_films():
    film = {"contentType": "film", "duration": 100, "mediaid": "AAAAAAAA", "release_date": "1972-01-01", "title": "A"}
    series = {"contentType": "series", "duration": 0, "mediaid": "rLiSVzkD", "release_date": "1972-01-01", "title": "Lone Wolf and Cub"}
    responses.get(CATALOG_URL, json=_page([film, series], None, 2))
    items = fetch_catalog(requests.Session(), sleep=_no_sleep)
    assert [i.mediaid for i in items] == ["AAAAAAAA"]


@responses.activate
def test_a_repeated_mediaid_keeps_the_first():
    bad_timing = {"contentType": "film", "duration": 1439, "mediaid": "2hBeeBd5", "release_date": "1982-01-01", "title": "Bad Timing"}
    responses.get(CATALOG_URL, json=_page([bad_timing, dict(bad_timing)], None, 2))
    assert [i.title for i in fetch_catalog(requests.Session(), sleep=_no_sleep)] == ["Bad Timing"]


@responses.activate
def test_junk_years_become_none():
    items = [
        {"contentType": "film", "duration": 247, "mediaid": "dhNWDlG0", "release_date": "0-01-01", "title": "Another World"},
        {"contentType": "film", "duration": 3308, "mediaid": "olgaplBp", "release_date": "2915-01-01", "title": "The Universe Is Out There"},
    ]
    responses.get(CATALOG_URL, json=_page(items, None, 2))
    assert [i.year for i in fetch_catalog(requests.Session(), sleep=_no_sleep)] == [None, None]


@responses.activate
def test_raw_count_short_of_total_aborts():
    first = _load("all-films-results.page1.trimmed.json")["items"]
    responses.get(CATALOG_URL, json=_page(first, None, 3042))
    with pytest.raises(CriterionError, match="3042"):
        fetch_catalog(requests.Session(), sleep=_no_sleep)


@responses.activate
def test_a_repeated_cursor_aborts():
    first = _load("all-films-results.page1.trimmed.json")["items"]
    responses.get(CATALOG_URL, json=_page(first, "2", 99))
    responses.get(CATALOG_URL, json=_page(first, "2", 99))
    with pytest.raises(CriterionError, match="repeated"):
        fetch_catalog(requests.Session(), sleep=_no_sleep)


@responses.activate
def test_an_empty_page_aborts():
    responses.get(CATALOG_URL, json=_page([], None, 0))
    with pytest.raises(CriterionError, match="empty"):
        fetch_catalog(requests.Session(), sleep=_no_sleep)


@responses.activate
def test_429_backs_off_three_times_then_fails():
    for _ in range(4):
        responses.get(CATALOG_URL, status=429)
    slept: list[float] = []
    with pytest.raises(CriterionError, match="429"):
        fetch_catalog(requests.Session(), pacer=Pacer(0), sleep=slept.append)  # Pacer(0): only back-off sleeps
    assert slept == [2, 4, 8]


@responses.activate
def test_429_then_success_carries_on():
    first = _load("all-films-results.page1.trimmed.json")["items"]
    responses.get(CATALOG_URL, status=429)
    responses.get(CATALOG_URL, json=_page(first, None, len(first)))
    assert len(fetch_catalog(requests.Session(), sleep=_no_sleep)) == len(first)


@responses.activate
def test_sends_the_user_agent():
    first = _load("all-films-results.page1.trimmed.json")["items"]
    responses.get(CATALOG_URL, json=_page(first, None, len(first)))
    fetch_catalog(requests.Session(), sleep=_no_sleep)
    assert responses.calls[0].request.headers["User-Agent"] == "movie-brain/0.1 (personal watchlist tool)"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_criterion_site.py -q`
Expected: collection ERROR, `ModuleNotFoundError: No module named 'movie_brain.infrastructure.criterion_site'`.

- [ ] **Step 4: Write the catalog walk**

Create `src/movie_brain/infrastructure/criterion_site.py`:

```python
"""The Criterion Channel after its 2026-10-01 relaunch (Next.js + JW Player).

Real answers seen on 2026-10-01 live in docs/superpowers/research/2026-10-01-criterion-relaunch/;
the spec is docs/superpowers/specs/2026-10-01-criterion-relaunch-design.md (D1, D3, D7)."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

import requests

from movie_brain.infrastructure.cheapcharts import Pacer

BASE = "https://www.criterionchannel.com"
CATALOG_URL = f"{BASE}/api/all-films/results"
USER_AGENT = "movie-brain/0.1 (personal watchlist tool)"
PAGE_LIMIT = 200
CATALOG_DELAY_S = 1.0
BACKOFF_S = (2, 4, 8)


class CriterionError(Exception):
    """The site did not answer usably: the walk must write nothing."""


@dataclass(frozen=True)
class CatalogItem:
    mediaid: str
    title: str
    year: int | None
    duration_s: int


def _year(release_date: str | None) -> int | None:
    """`release_date` is always `YYYY-01-01` in the list; `0-01-01` and `2915-01-01` were seen."""
    try:
        y = int(str(release_date or "").split("-")[0])
    except ValueError:
        return None
    return y if 1880 <= y <= date.today().year + 2 else None


def _get(
    session: requests.Session,
    url: str,
    pacer: Pacer,
    sleep: Callable[[float], None],
    params: dict[str, Any] | None = None,
    allow_redirects: bool = True,
) -> requests.Response:
    """One paced GET with the 429 back-off. Network errors and 5xx raise CriterionError."""
    for attempt in range(len(BACKOFF_S) + 1):
        pacer.wait()
        try:
            resp = session.get(
                url, params=params, headers={"User-Agent": USER_AGENT}, timeout=30, allow_redirects=allow_redirects
            )
        except requests.RequestException as exc:
            raise CriterionError(f"{url}: {exc}") from exc
        if resp.status_code != 429:
            if resp.status_code >= 500:
                raise CriterionError(f"{url}: HTTP {resp.status_code}")
            return resp
        if attempt < len(BACKOFF_S):
            sleep(BACKOFF_S[attempt])
    raise CriterionError(f"{url}: still 429 after {len(BACKOFF_S)} back-offs")


def fetch_catalog(
    session: requests.Session, pacer: Pacer | None = None, sleep: Callable[[float], None] = time.sleep
) -> list[CatalogItem]:
    """Every FILM in the catalog (D1). Series are counted against `total` but never returned;
    a repeated mediaid keeps its first item (Bad Timing is listed twice under one id)."""
    pacer = pacer or Pacer(CATALOG_DELAY_S, sleep=sleep)
    raw: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    key: str | None = None
    total: int | None = None
    while True:
        params: dict[str, Any] = {"page_limit": PAGE_LIMIT}
        if key is not None:
            params["pagination_key"] = key
        resp = _get(session, CATALOG_URL, pacer, sleep, params=params)
        if resp.status_code != 200:
            raise CriterionError(f"catalog: HTTP {resp.status_code}")
        body = resp.json()
        items = body.get("items") or []
        if not items:
            raise CriterionError("catalog: empty page — site changed?")
        raw.extend(items)
        total = body.get("total")
        key = (body.get("paging") or {}).get("next_pagination_key")
        if not key:
            break
        if key in seen_keys:
            raise CriterionError(f"catalog: repeated cursor {key!r}")
        seen_keys.add(key)
    if total != len(raw):
        raise CriterionError(f"catalog: walked {len(raw)} items, site says total {total}")
    films: list[CatalogItem] = []
    taken: set[str] = set()
    for it in raw:
        if it.get("contentType") != "film" or it.get("mediaid") in taken:
            continue
        taken.add(it["mediaid"])
        films.append(CatalogItem(it["mediaid"], it["title"], _year(it.get("release_date")), int(it.get("duration") or 0)))
    return films
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_criterion_site.py -q`
Expected: `10 passed`.

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/criterion tests/unit/test_criterion_site.py src/movie_brain/infrastructure/criterion_site.py
git commit -m "Read the relaunched Criterion catalog: no token, so the walk works again

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The JW Player film record

**Files:**
- Modify: `src/movie_brain/infrastructure/criterion_site.py`
- Test: `tests/unit/test_criterion_site.py`

**Interfaces:**
- Consumes: `_get`, `CriterionError`, `USER_AGENT` (Task 1)
- Produces:
  - `JW_MEDIA_URL = "https://cdn.jwplayer.com/v2/media/{}"`
  - `@dataclass(frozen=True) class JwMedia: mediaid: str; title: str; title_original: str | None; release_date: str | None; directors: tuple[str, ...]; criterion_id: str | None; license_start: str | None; license_end: str | None; content_type: str`
  - `def fetch_media(session: requests.Session, mediaid: str, pacer: Pacer | None = None, sleep: Callable[[float], None] = time.sleep) -> JwMedia | None` — `None` means JW answered 404 (an answer); network/5xx/429-exhausted raise `CriterionError`.

- [ ] **Step 1: Write the failing tests** (append to `tests/unit/test_criterion_site.py`; add `JW_MEDIA_URL, JwMedia, fetch_media` to the import list)

```python
@responses.activate
def test_media_record_decodes_its_json_string_lists():
    responses.get(JW_MEDIA_URL.format("L5Z3RaiC"), json=_load("jw-media.L5Z3RaiC.json"))
    m = fetch_media(requests.Session(), "L5Z3RaiC", sleep=_no_sleep)
    assert m == JwMedia(
        mediaid="L5Z3RaiC",
        title="2 or 3 Things I Know About Her",
        title_original="2 ou 3 choses que je sais d'elle",
        release_date="1967-03-17",
        directors=("Jean-Luc Godard",),
        criterion_id="1333",
        license_start="2019-04-08T04:00:00Z",
        license_end=None,
        content_type="film",
    )


@responses.activate
def test_media_404_is_an_answer_not_an_error():
    responses.get(JW_MEDIA_URL.format("ZZZZZZZZ"), status=404, json={"message": "['ZZZZZZZZ']: id not found in index."})
    assert fetch_media(requests.Session(), "ZZZZZZZZ", sleep=_no_sleep) is None


@responses.activate
def test_media_5xx_is_weather():
    responses.get(JW_MEDIA_URL.format("L5Z3RaiC"), status=503)
    with pytest.raises(CriterionError):
        fetch_media(requests.Session(), "L5Z3RaiC", sleep=_no_sleep)


@responses.activate
def test_media_with_a_broken_director_string_has_no_directors():
    body = _load("jw-media.L5Z3RaiC.json")
    body["playlist"][0]["director"] = "not json"
    responses.get(JW_MEDIA_URL.format("L5Z3RaiC"), json=body)
    assert fetch_media(requests.Session(), "L5Z3RaiC", sleep=_no_sleep).directors == ()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_criterion_site.py -q -k media`
Expected: ImportError for `JW_MEDIA_URL`.

- [ ] **Step 3: Implement** (append to `criterion_site.py`; add `import json` at the top)

```python
JW_MEDIA_URL = "https://cdn.jwplayer.com/v2/media/{}"
JW_DELAY_S = 0.25


@dataclass(frozen=True)
class JwMedia:
    mediaid: str
    title: str
    title_original: str | None
    release_date: str | None
    directors: tuple[str, ...]
    criterion_id: str | None
    license_start: str | None
    license_end: str | None
    content_type: str


def _json_list(raw: object) -> tuple[str, ...]:
    """JW stores `director`, `country`, `language`, `starring` as JSON-encoded STRINGS."""
    if not isinstance(raw, str) or not raw:
        return ()
    try:
        value = json.loads(raw)
    except ValueError:
        return ()
    return tuple(str(v) for v in value) if isinstance(value, list) else ()


def _blank(raw: object) -> str | None:
    return str(raw) if raw not in (None, "") else None


def fetch_media(
    session: requests.Session, mediaid: str, pacer: Pacer | None = None, sleep: Callable[[float], None] = time.sleep
) -> JwMedia | None:
    """One film's JW record. None = JW answered 404 (no such id) — an answer, not weather."""
    pacer = pacer or Pacer(JW_DELAY_S, sleep=sleep)
    resp = _get(session, JW_MEDIA_URL.format(mediaid), pacer, sleep)
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        raise CriterionError(f"jw media {mediaid}: HTTP {resp.status_code}")
    item = (resp.json().get("playlist") or [{}])[0]
    return JwMedia(
        mediaid=str(item.get("mediaid") or mediaid),
        title=str(item.get("title") or ""),
        title_original=_blank(item.get("title_original")),
        release_date=_blank(item.get("release_date")),
        directors=_json_list(item.get("director")),
        criterion_id=_blank(item.get("criterion_id")),
        license_start=_blank(item.get("license_start_date_time")),
        license_end=_blank(item.get("license_end_date_time")),
        content_type=str(item.get("contentType") or ""),
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/test_criterion_site.py -q`
Expected: `14 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/infrastructure/criterion_site.py tests/unit/test_criterion_site.py
git commit -m "Read a film's JW Player record, treating its 404 as an answer so one missing id never fails a night

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The dated leaving page

**Files:**
- Modify: `src/movie_brain/infrastructure/criterion_site.py`
- Test: `tests/unit/test_criterion_site.py`

**Interfaces:**
- Consumes: `_get`, `CriterionError`, `BASE` (Task 1)
- Produces:
  - `JW_PLAYLIST_URL = "https://cdn.jwplayer.com/v2/playlists/{}"`
  - `@dataclass(frozen=True) class Leaving: labels: dict[str, str]; mismatches: tuple[str, ...]` — `labels` maps mediaid → label like `"October 31"`; an EMPTY dict means the home page loaded and linked no dated leaving page (authoritative: clear all labels in Plan B). Any failed call raises `CriterionError` (Plan B keeps the old labels).
  - `def label_from_slug(slug: str) -> str | None` (`"leaving-october-31"` → `"October 31"`; undated slugs → `None`)
  - `def fetch_leaving(session: requests.Session, pacer: Pacer | None = None, sleep: Callable[[float], None] = time.sleep) -> Leaving`

- [ ] **Step 1: Write the failing tests** (append; add the new names to the import)

```python
def test_label_from_slug_reads_dated_pages_only():
    assert label_from_slug("leaving-october-31") == "October 31"
    assert label_from_slug("leaving-november-1") == "November 1"
    assert label_from_slug("leaving-soon") is None
    assert label_from_slug("leaving-octember-31") is None


def _leaving_mocks(home=None):
    responses.get(BASE + "/", body=home if home is not None else (FIX / "home-2026-10-01.html").read_text())
    responses.get(BASE + "/discover/leaving-october-31", body=(FIX / "leaving-october-31.html").read_text())
    responses.get(JW_PLAYLIST_URL.format("0WbeKrrA"), json=_load("jw-playlist.0WbeKrrA.full.json"))


@responses.activate
def test_leaving_reads_the_dated_page_and_ignores_leaving_soon():
    _leaving_mocks()
    result = fetch_leaving(requests.Session(), sleep=_no_sleep)
    assert len(result.labels) == 28
    assert set(result.labels.values()) == {"October 31"}
    assert result.mismatches == ()  # EST-midnight expiries (04:59:59Z) still read October 31
    assert not any("leaving-soon" in c.request.url for c in responses.calls)


@responses.activate
def test_home_page_without_a_dated_link_is_an_authoritative_empty():
    responses.get(BASE + "/", body='<html><a href="/discover/leaving-soon"></a></html>')
    assert fetch_leaving(requests.Session(), sleep=_no_sleep).labels == {}


@responses.activate
def test_a_failed_leaving_page_raises():
    responses.get(BASE + "/", body=(FIX / "home-2026-10-01.html").read_text())
    responses.get(BASE + "/discover/leaving-october-31", status=500)
    with pytest.raises(CriterionError):
        fetch_leaving(requests.Session(), sleep=_no_sleep)


@responses.activate
def test_an_expiry_on_another_day_is_reported_not_trusted():
    playlist = _load("jw-playlist.0WbeKrrA.full.json")
    playlist["playlist"][0]["license_end_date_time"] = "2026-12-01T04:59:59Z"
    responses.get(BASE + "/", body=(FIX / "home-2026-10-01.html").read_text())
    responses.get(BASE + "/discover/leaving-october-31", body=(FIX / "leaving-october-31.html").read_text())
    responses.get(JW_PLAYLIST_URL.format("0WbeKrrA"), json=playlist)
    result = fetch_leaving(requests.Session(), sleep=_no_sleep)
    first = playlist["playlist"][0]["mediaid"]
    assert result.labels[first] == "October 31"
    assert len(result.mismatches) == 1 and first in result.mismatches[0]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_criterion_site.py -q -k "leaving or slug"`
Expected: ImportError for `label_from_slug`.

- [ ] **Step 3: Implement** (append; add `import re` and `from datetime import datetime, timedelta, timezone` at the top)

```python
JW_PLAYLIST_URL = "https://cdn.jwplayer.com/v2/playlists/{}"
_DATED = re.compile(r'href="(/discover/(leaving-[a-z]+-\d{1,2}))"')
_PLAYLIST_ID = re.compile(r'\\"playlistID\\":\\"([A-Za-z0-9]{8})\\"')
_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august",
           "september", "october", "november", "december")
_EST = timezone(timedelta(hours=-5))  # Criterion sets some expiries at EST midnight all year


@dataclass(frozen=True)
class Leaving:
    labels: dict[str, str]
    mismatches: tuple[str, ...]


def label_from_slug(slug: str) -> str | None:
    m = re.fullmatch(r"leaving-([a-z]+)-(\d{1,2})", slug)
    if not m or m.group(1) not in _MONTHS:
        return None
    return f"{m.group(1).capitalize()} {int(m.group(2))}"


def _expiry_label(license_end: str | None) -> str | None:
    if not license_end:
        return None
    try:
        moment = datetime.fromisoformat(license_end.replace("Z", "+00:00")).astimezone(_EST)
    except ValueError:
        return None
    return f"{moment.strftime('%B')} {moment.day}"


def fetch_leaving(
    session: requests.Session, pacer: Pacer | None = None, sleep: Callable[[float], None] = time.sleep
) -> Leaving:
    """Labels from every DATED leaving page the home page links (D7). The label is the page's
    own slug; each film's `license_end_date_time` is only a cross-check, reported on mismatch."""
    pacer = pacer or Pacer(JW_DELAY_S, sleep=sleep)
    home = _get(session, BASE + "/", pacer, sleep)
    if home.status_code != 200:
        raise CriterionError(f"home page: HTTP {home.status_code}")
    pages = sorted({(path, slug) for path, slug in _DATED.findall(home.text) if label_from_slug(slug)})
    labels: dict[str, str] = {}
    mismatches: list[str] = []
    for path, slug in pages:
        label = label_from_slug(slug)
        assert label is not None
        page = _get(session, BASE + path, pacer, sleep)
        if page.status_code != 200:
            raise CriterionError(f"{path}: HTTP {page.status_code}")
        for pid in dict.fromkeys(_PLAYLIST_ID.findall(page.text)):
            pl = _get(session, JW_PLAYLIST_URL.format(pid), pacer, sleep, params={"page_limit": 500})
            if pl.status_code != 200:
                raise CriterionError(f"playlist {pid}: HTTP {pl.status_code}")
            for item in pl.json().get("playlist") or []:
                mediaid = item.get("mediaid")
                if not mediaid:
                    continue
                labels[mediaid] = label
                expiry = _expiry_label(item.get("license_end_date_time"))
                if expiry is not None and expiry != label:
                    mismatches.append(f"{mediaid} {item.get('title')!r}: page says {label}, expiry says {expiry}")
    return Leaving(labels, tuple(mismatches))
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/test_criterion_site.py -q`
Expected: `19 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/infrastructure/criterion_site.py tests/unit/test_criterion_site.py
git commit -m "Read leaving dates from the dated leaving page's own name, so EST-set expiries never shift a label

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Asking an old link where it forwards

**Files:**
- Modify: `src/movie_brain/infrastructure/criterion_site.py`
- Test: `tests/unit/test_criterion_site.py`

**Interfaces:**
- Consumes: `USER_AGENT`, `CriterionError`
- Produces:
  - `@dataclass(frozen=True) class Forward: status: int | None; location: str | None; mediaid: str | None; kind: str` — `kind` ∈ `"film"` (307/308 to `/films/<id>/…`), `"supplement"` (to `/supplements/…`), `"gone"` (404), `"retry"` (anything else, incl. a network error: `status is None`)
  - `def classify_forward(status: int | None, location: str | None) -> Forward`
  - `def head_old_url(session: requests.Session, url: str, pacer: Pacer) -> Forward` — never raises; a network error is a `retry` Forward.

- [ ] **Step 1: Write the failing tests** (append; import `Forward, classify_forward, head_old_url`)

```python
@pytest.mark.parametrize(
    "location",
    [
        "/films/gpRRkq27/test-pattern",
        "https://www.criterionchannel.com/films/gpRRkq27/test-pattern",
        "/films/gpRRkq27",
        "/films/gpRRkq27/",
    ],
)
def test_a_film_forward_yields_its_mediaid_absolute_or_relative(location):
    f = classify_forward(307, location)
    assert (f.kind, f.mediaid) == ("film", "gpRRkq27")


def test_a_supplement_forward_has_no_film():
    f = classify_forward(307, "/supplements/3ekwz1ry/contras-city")
    assert (f.kind, f.mediaid) == ("supplement", None)


def test_404_is_gone_and_anything_else_is_retry():
    assert classify_forward(404, None).kind == "gone"
    assert classify_forward(200, None).kind == "retry"
    assert classify_forward(None, None).kind == "retry"
    assert classify_forward(307, "/somewhere-else").kind == "retry"


@responses.activate
def test_head_does_not_follow_the_redirect():
    responses.head("https://www.criterionchannel.com/test-pattern", status=307,
                   headers={"Location": "/films/gpRRkq27/test-pattern"})
    f = head_old_url(requests.Session(), "https://www.criterionchannel.com/test-pattern", Pacer(0))
    assert f == Forward(307, "/films/gpRRkq27/test-pattern", "gpRRkq27", "film")
    assert len(responses.calls) == 1


@responses.activate
def test_head_network_error_is_retry():
    responses.head("https://www.criterionchannel.com/x", body=requests.ConnectionError("down"))
    assert head_old_url(requests.Session(), "https://www.criterionchannel.com/x", Pacer(0)).kind == "retry"
```


- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_criterion_site.py -q -k "forward or head"`
Expected: ImportError for `classify_forward`.

- [ ] **Step 3: Implement** (append; `from urllib.parse import urlparse` at the top)

```python
BRIDGE_DELAY_S = 0.4
_FILM_PATH = re.compile(r"^/films/([A-Za-z0-9]{8})(?:/|$)")


@dataclass(frozen=True)
class Forward:
    status: int | None
    location: str | None
    mediaid: str | None
    kind: str  # film | supplement | gone | retry


def classify_forward(status: int | None, location: str | None) -> Forward:
    path = urlparse(location).path if location else ""
    if status in (301, 302, 307, 308):
        m = _FILM_PATH.match(path)
        if m:
            return Forward(status, location, m.group(1), "film")
        if path.startswith("/supplements/"):
            return Forward(status, location, None, "supplement")
    if status == 404:
        return Forward(status, location, None, "gone")
    return Forward(status, location, None, "retry")


def head_old_url(session: requests.Session, url: str, pacer: Pacer) -> Forward:
    """Where an old `criterionchannel.com/<slug>` link forwards now (D3). Never follows, never raises."""
    pacer.wait()
    try:
        resp = session.head(url, headers={"User-Agent": USER_AGENT}, timeout=30, allow_redirects=False)
    except requests.RequestException:
        return Forward(None, None, None, "retry")
    return classify_forward(resp.status_code, resp.headers.get("Location"))
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/test_criterion_site.py -q`
Expected: `28 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/infrastructure/criterion_site.py tests/unit/test_criterion_site.py
git commit -m "Ask an old Criterion link where it forwards: the forwarding address carries the film's new id

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: The observation file

**Files:**
- Create: `src/movie_brain/application/criterion_bridge.py`
- Test: `tests/unit/test_criterion_bridge_file.py`

**Interfaces:**
- Consumes: `Forward`, `classify_forward` (Task 4)
- Produces:
  - `BRIDGE_FILE = "criterion-bridge.jsonl"`
  - `@dataclass class Observation: url: str; film_id: int; status: int | None; location: str | None; asked_at: str; applied: bool = False` with property `forward -> Forward` (via `classify_forward(status, location)`)
  - `def load_observations(path: Path) -> dict[str, Observation]` — later lines for the same URL win; a line that is not valid JSON or lacks a key is skipped
  - `def append_observation(path: Path, obs: Observation) -> None` — appends one JSON line and flushes it to disk
  - `def rewrite_observations(path: Path, observations: Iterable[Observation]) -> None` — atomic replace (write `*.tmp`, `os.replace`)
  - `def is_fresh(obs: Observation, now: datetime) -> bool` — `asked_at` within 24 hours

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_criterion_bridge_file.py`:

```python
from datetime import datetime, timedelta, timezone

from movie_brain.application.criterion_bridge import (
    Observation,
    append_observation,
    is_fresh,
    load_observations,
    rewrite_observations,
)

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)


def _obs(url, **kw):
    base = dict(url=url, film_id=56, status=307, location="/films/gpRRkq27/test-pattern", asked_at=NOW.isoformat())
    base.update(kw)
    return Observation(**base)


def test_append_then_load_round_trips(tmp_path):
    p = tmp_path / "criterion-bridge.jsonl"
    append_observation(p, _obs("https://www.criterionchannel.com/test-pattern"))
    got = load_observations(p)
    assert got["https://www.criterionchannel.com/test-pattern"].forward.mediaid == "gpRRkq27"


def test_a_half_written_last_line_is_ignored(tmp_path):
    p = tmp_path / "criterion-bridge.jsonl"
    append_observation(p, _obs("https://www.criterionchannel.com/a"))
    with p.open("a") as fh:
        fh.write('{"url": "https://www.criterionchannel.com/b", "film_id": 7, "sta')
    assert set(load_observations(p)) == {"https://www.criterionchannel.com/a"}


def test_a_later_line_for_the_same_url_wins(tmp_path):
    p = tmp_path / "criterion-bridge.jsonl"
    append_observation(p, _obs("https://www.criterionchannel.com/a", status=None, location=None))
    append_observation(p, _obs("https://www.criterionchannel.com/a"))
    assert load_observations(p)["https://www.criterionchannel.com/a"].forward.kind == "film"


def test_rewrite_replaces_the_whole_file(tmp_path):
    p = tmp_path / "criterion-bridge.jsonl"
    append_observation(p, _obs("https://www.criterionchannel.com/a"))
    rewrite_observations(p, [_obs("https://www.criterionchannel.com/a", applied=True)])
    assert load_observations(p)["https://www.criterionchannel.com/a"].applied is True
    assert not (tmp_path / "criterion-bridge.jsonl.tmp").exists()


def test_freshness_is_24_hours():
    assert is_fresh(_obs("u", asked_at=(NOW - timedelta(hours=23)).isoformat()), NOW)
    assert not is_fresh(_obs("u", asked_at=(NOW - timedelta(hours=25)).isoformat()), NOW)


def test_missing_file_is_empty(tmp_path):
    assert load_observations(tmp_path / "nope.jsonl") == {}
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_criterion_bridge_file.py -q`
Expected: `ModuleNotFoundError: No module named 'movie_brain.application.criterion_bridge'`.

- [ ] **Step 3: Implement**

Create `src/movie_brain/application/criterion_bridge.py`:

```python
"""`criterion bridge`: give every stored Criterion film its new id (spec D3).

Each stored old link (`criterionchannel.com/<slug>`) still forwards to `/films/<mediaid>/<slug>`.
The dry run asks every link and keeps the answers in `<config_dir>/criterion-bridge.jsonl`
(the OBSERVATION file — nothing in the database); `--apply` replays answers younger than 24
hours, writes the database in ONE transaction, and only then marks the lines `applied`."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

from movie_brain.infrastructure.criterion_site import Forward, classify_forward

BRIDGE_FILE = "criterion-bridge.jsonl"
FRESH_FOR = timedelta(hours=24)


@dataclass
class Observation:
    url: str
    film_id: int
    status: int | None
    location: str | None
    asked_at: str
    applied: bool = False

    @property
    def forward(self) -> Forward:
        return classify_forward(self.status, self.location)


def load_observations(path: Path) -> dict[str, Observation]:
    out: dict[str, Observation] = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        try:
            raw = json.loads(line)
            obs = Observation(
                url=str(raw["url"]), film_id=int(raw["film_id"]), status=raw["status"],
                location=raw["location"], asked_at=str(raw["asked_at"]), applied=bool(raw.get("applied", False)),
            )
        except (ValueError, KeyError, TypeError):
            continue  # a half-written line from an interrupted run: that URL is asked again
        out[obs.url] = obs
    return out


def append_observation(path: Path, obs: Observation) -> None:
    with path.open("a") as fh:
        fh.write(json.dumps(asdict(obs)) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def rewrite_observations(path: Path, observations: Iterable[Observation]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w") as fh:
        for obs in observations:
            fh.write(json.dumps(asdict(obs)) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def is_fresh(obs: Observation, now: datetime) -> bool:
    try:
        asked = datetime.fromisoformat(obs.asked_at)
    except ValueError:
        return False
    return now - asked < FRESH_FOR
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/test_criterion_bridge_file.py -q`
Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/application/criterion_bridge.py tests/unit/test_criterion_bridge_file.py
git commit -m "Keep every bridge answer on disk as it arrives, so an interrupted 30-minute run resumes instead of restarting

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Repository — the old links and the one-transaction write

**Files:**
- Modify: `src/movie_brain/infrastructure/database.py` (add two methods to `Repository`, next to `external_id_holders`, ~line 907)
- Test: `tests/unit/test_database.py` (append)

**Interfaces:**
- Consumes: existing `_conn`, `_canonical_in(c, film_id)`, `ReviewEntry` (`domain/models.py`)
- Produces:
  - `@dataclass(frozen=True) class BridgeTarget: film_id: int; url: str; title: str; year: int | None` (in `domain/models.py`, next to `ReviewEntry`) — `film_id` is the CANONICAL film
  - `Repository.criterion_old_urls() -> list[BridgeTarget]` — every `external_ids` row with authority `criterion` whose value starts with `http`, ordered by canonical film id then url
  - `Repository.record_bridge(bindings: list[tuple[int, str, str]], reviews: list[ReviewEntry], seen: date) -> None` — each binding is `(film_id, mediaid, listing_url)`: inserts `external_ids(film_id, 'criterion', mediaid)` (`ON CONFLICT(film_id, authority, value) DO NOTHING`), sets that film's `criterion` listing `url` to `listing_url` when the film has a criterion listing, and inserts every review row into `match_review` (authority `criterion`) — all in ONE `with self._conn()`; any exception rolls the whole batch back.

- [ ] **Step 1: Write the failing tests** (append to `tests/unit/test_database.py`; add imports `from movie_brain.domain.models import BridgeTarget, ReviewEntry` if not present)

```python
def test_criterion_old_urls_lists_urls_only_by_canonical_film(repo):
    d = date(2026, 9, 20)
    repo.record_catalog("criterion", [Film("Test Pattern", 2019, None, "https://www.criterionchannel.com/test-pattern")], d)
    fid = repo.film_id_by_key(Film("Test Pattern", 2019, None, "").key)
    repo.set_external_id(fid, "criterion", "gpRRkq27", d)  # an id row is not an old URL
    assert repo.criterion_old_urls() == [
        BridgeTarget(fid, "https://www.criterionchannel.com/test-pattern", "Test Pattern", 2019)
    ]


def test_criterion_old_urls_follow_a_merge_to_the_survivor(repo):
    d = date(2026, 9, 20)
    repo.record_catalog("criterion", [Film("Eve's Bayou", 1997, None, "https://www.criterionchannel.com/eves-bayou")], d)
    survivor = repo.film_id_by_key(Film("Eve's Bayou", 1997, None, "").key)
    loser = repo.create_film(Film("EVE'S BAYOU: Director's Cut", 1997, None, ""))
    repo.set_external_id(loser, "criterion", "https://www.criterionchannel.com/eves-bayou-directors-cut", d)
    repo.merge_film(loser, survivor, d)
    assert {t.film_id for t in repo.criterion_old_urls()} == {survivor}


def test_record_bridge_writes_ids_listing_urls_and_reviews_together(repo):
    d = date(2026, 9, 20)
    repo.record_catalog("criterion", [Film("Test Pattern", 2019, None, "https://www.criterionchannel.com/test-pattern")], d)
    fid = repo.film_id_by_key(Film("Test Pattern", 2019, None, "").key)
    other = repo.create_film(Film("Somebody Else", 2001, None, ""))
    repo.record_bridge(
        [(fid, "gpRRkq27", "https://www.criterionchannel.com/films/gpRRkq27/test-pattern")],
        [ReviewEntry("id-conflict", other, "gpRRkq27", '{"holder": %d}' % fid)],
        date(2026, 10, 2),
    )
    assert ("criterion", "gpRRkq27") in repo.external_ids_all(fid)
    conn = sqlite3.connect(repo.db_path)
    url = conn.execute("SELECT url FROM listings WHERE film_id = ? AND source = 'criterion'", (fid,)).fetchone()[0]
    assert url == "https://www.criterionchannel.com/films/gpRRkq27/test-pattern"
    assert [r["reason"] for r in repo.open_reviews("criterion")] == ["id-conflict"]


def test_record_bridge_is_all_or_nothing(repo):
    d = date(2026, 9, 20)
    a = repo.create_film(Film("A", 2001, None, ""))
    b = repo.create_film(Film("B", 2002, None, ""))
    repo.set_external_id(b, "criterion", "SAMEID00", d)
    with pytest.raises(sqlite3.IntegrityError):
        repo.record_bridge([(a, "AAAAAAAA", "u1"), (a, "SAMEID00", "u2")], [], d)  # second binding clashes
    assert ("criterion", "AAAAAAAA") not in repo.external_ids_all(a)


def test_record_bridge_same_film_same_id_twice_is_one_row(repo):
    d = date(2026, 9, 20)
    a = repo.create_film(Film("A", 2001, None, ""))
    repo.record_bridge([(a, "AAAAAAAA", "u1"), (a, "AAAAAAAA", "u1")], [], d)
    assert repo.external_ids_all(a).count(("criterion", "AAAAAAAA")) == 1
```

(`test_database.py` already imports `sqlite3`, `pytest`, `date`, `Film`; check with `head -30 tests/unit/test_database.py` and add whichever is missing. `film_id_by_key` already exists on `Repository`.)

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_database.py -q -k "criterion_old_urls or record_bridge"`
Expected: ImportError for `BridgeTarget`.

- [ ] **Step 3: Implement**

In `src/movie_brain/domain/models.py`, after `ReviewEntry`:

```python
@dataclass(frozen=True)
class BridgeTarget:
    """One stored old Criterion link and the canonical film that holds it (spec D3)."""

    film_id: int
    url: str
    title: str
    year: int | None
```

In `src/movie_brain/infrastructure/database.py`, import `BridgeTarget` alongside `ReviewEntry`, and add after `external_id_holders`:

```python
    def criterion_old_urls(self) -> list[BridgeTarget]:
        """Every stored old Criterion link (an `http…` value; a bare mediaid is not one), on its
        CANONICAL film, ordered by that film then the link — the bridge's deterministic order."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT film_id, value FROM external_ids WHERE authority = 'criterion' AND value LIKE 'http%'"
            ).fetchall()
            out: list[BridgeTarget] = []
            for r in rows:
                fid = self._canonical_in(c, int(r["film_id"]))
                f = c.execute("SELECT title, year FROM films WHERE id = ?", (fid,)).fetchone()
                out.append(BridgeTarget(fid, str(r["value"]), str(f["title"]), f["year"]))
            return sorted(out, key=lambda t: (t.film_id, t.url))

    def record_bridge(self, bindings: list[tuple[int, str, str]], reviews: list[ReviewEntry], seen: date) -> None:
        """The bridge's whole write in ONE transaction: mediaid ids, the forwarded listing URL,
        and the clash review rows. Any failure rolls every row back."""
        day = seen.isoformat()
        with self._conn() as c:
            for film_id, mediaid, listing_url in bindings:
                c.execute(
                    "INSERT INTO external_ids (film_id, authority, value, first_seen) VALUES (?, 'criterion', ?, ?) "
                    "ON CONFLICT(film_id, authority, value) DO NOTHING",
                    (film_id, mediaid, day),
                )
                c.execute(
                    "UPDATE listings SET url = ? WHERE film_id = ? AND source = 'criterion'", (listing_url, film_id)
                )
            for e in reviews:
                c.execute(
                    "INSERT INTO match_review (authority, film_id, value, reason, detail, created_at) "
                    "VALUES ('criterion', ?, ?, ?, ?, ?)",
                    (e.film_id, e.value, e.reason, e.detail, day),
                )
```

Check `_conn` rolls back on exception: it commits only after `yield` returns, and `conn.close()` without commit discards the transaction — so an exception mid-loop leaves nothing. No change needed.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/test_database.py -q -k "criterion_old_urls or record_bridge"`
Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/domain/models.py src/movie_brain/infrastructure/database.py tests/unit/test_database.py
git commit -m "Repository: list stored old Criterion links by canonical film, and write a bridge in one transaction

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: The bridge use case

**Files:**
- Modify: `src/movie_brain/application/criterion_bridge.py`
- Create: `tests/features/criterion_bridge.feature`, `tests/step_defs/test_criterion_bridge.py`

**Interfaces:**
- Consumes: `Repository.criterion_old_urls`, `Repository.record_bridge`, `Repository.external_id_holders`, `Repository.canonical_film_id`, `Repository.open_reviews`, `Repository.resolved_review_keys`, `Repository.external_ids_all` (existing), Task 5's file helpers, `CatalogItem`, `Forward`
- Produces:
  - `@dataclass class BridgeReport: counts: dict[str, int]; drift: list[DriftLine]; reviews: int; applied: bool; reopened: int`  (`counts` keys: `film`, `same-film`, `held`, `supplement`, `gone`, `retry`)
  - `@dataclass(frozen=True) class DriftLine: film_id: int; title: str; year: int | None; cat_title: str; cat_year: int | None; kind: str` (`kind` ∈ `title`, `year`, `both`)
  - `def run_bridge(repo: Repository, config_dir: Path, catalog: list[CatalogItem], ask: Callable[[str], Forward], now: datetime, apply: bool, retry: bool) -> BridgeReport`

Behaviour (spec D3), exactly:
1. Load observations. For every `applied` line, check the database still holds `('criterion', mediaid)` on that film (`external_ids_all`); if not, set `applied = False` (count it in `reopened`).
2. For each `BridgeTarget` in `criterion_old_urls()` order: reuse its observation when one exists AND (`apply` is False or `is_fresh(obs, now)`) AND NOT (`retry` and `obs.forward.kind == "retry"`); otherwise call `ask(url)` and `append_observation` the new answer immediately (stamped `now`). An observation's `film_id` is refreshed to the target's canonical id.
3. Classify in order. `holders = repo.external_id_holders("criterion")` mapped through `canonical_film_id`, plus every mediaid bound earlier in this run. For a `film` forward: holder absent → bind (and record `holder = this film`); holder is this film → `same-film` (no write, no review); holder another film → `held`: one `ReviewEntry("id-conflict", film_id=claimant, value=mediaid, detail=json.dumps({"holder": holder_id, "url": url}))`, skipped when an open review with the same (reason, film_id, value) exists or the same key is in `resolved_review_keys("criterion")`.
4. Drift: for each bound or same-film line whose mediaid is in `catalog`, compare `(title, year)` with the catalog item's; differences make a `DriftLine`.
5. `apply=False` → nothing written to the database; return the report.
6. `apply=True` → `repo.record_bridge(bindings, reviews, now.date())` where `listing_url = BASE + urlparse(location).path` (absolute); then mark every line that produced a binding or a `same-film` as `applied=True` and `rewrite_observations`.

- [ ] **Step 1: Write the feature file**

Create `tests/features/criterion_bridge.feature`:

```gherkin
Feature: Criterion bridge — give every stored film its new Criterion id before the first new sync

  Background:
    Given a Criterion film "Test Pattern" (2019) at old link "test-pattern"
    And the old link "test-pattern" forwards to "/films/gpRRkq27/test-pattern"
    And the catalog lists "gpRRkq27" as "Test Pattern" (2021)

  Scenario: A dry run asks every link, keeps the answers, and writes nothing
    When I run the bridge
    Then the bridge counted 1 "film"
    And the drift shows "Test Pattern" 2019 → 2021 as "year"
    And the film "Test Pattern" holds no criterion id
    And the observation file has 1 line

  Scenario: Apply records the id and the new link, and never changes the title or year
    When I run the bridge with apply
    Then the film "Test Pattern" holds criterion id "gpRRkq27"
    And the film "Test Pattern" is listed at "https://www.criterionchannel.com/films/gpRRkq27/test-pattern"
    And the film "Test Pattern" is still 2019

  Scenario: Apply within a day replays the dry run's answers without asking again
    When I run the bridge
    And I run the bridge with apply
    Then the site was asked 1 time

  Scenario: An interrupted run resumes where it stopped
    Given a Criterion film "Bigger Than Life" (1956) at old link "bigger-than-life"
    And the old link "bigger-than-life" forwards to "/films/Ab12Cd34/bigger-than-life"
    And the first run is interrupted after 1 answer
    When I run the bridge
    Then the site was asked 2 times

  Scenario: A link that now leads nowhere, and one that became an extra, write nothing
    Given a Criterion film "Yam daabo" (1987) at old link "yam-daabo"
    And the old link "yam-daabo" answers 404
    And a Criterion film "Contras' City" (1969) at old link "contras-city"
    And the old link "contras-city" forwards to "/supplements/3ekwz1ry/contras-city"
    When I run the bridge with apply
    Then the bridge counted 1 "gone"
    And the bridge counted 1 "supplement"
    And the film "Yam daabo" holds no criterion id

  Scenario: An id another film already holds is a clash for review, never a merge
    Given a Criterion film "Lone Wolf and Cub: Sword of Vengeance" (1972) at old link "sword-of-vengeance"
    And the old link "sword-of-vengeance" forwards to "/films/rLiSVzkD/lone-wolf-and-cub"
    And a Criterion film "Lone Wolf and Cub: Baby Cart at the River Styx" (1972) at old link "river-styx"
    And the old link "river-styx" forwards to "/films/rLiSVzkD/lone-wolf-and-cub"
    When I run the bridge with apply
    Then the bridge counted 1 "held"
    And there is 1 open criterion "id-conflict" review
    When I run the bridge with apply
    Then there is 1 open criterion "id-conflict" review

  Scenario: Two old links on one film that reach the same id are one row and no clash
    Given the film "Test Pattern" also holds old link "test-pattern-1"
    And the old link "test-pattern-1" forwards to "https://www.criterionchannel.com/films/gpRRkq27/test-pattern"
    When I run the bridge with apply
    Then the bridge counted 1 "same-film"
    And there are 0 open criterion "id-conflict" reviews

  Scenario: A link that failed is asked again only with --retry
    Given a Criterion film "Penkelemes" (2025) at old link "penkelemes"
    And the old link "penkelemes" fails
    When I run the bridge
    And the old link "penkelemes" forwards to "/films/Pk00Pk00/penkelmes"
    And I run the bridge
    Then the bridge counted 1 "retry"
    When I run the bridge with retry
    Then the bridge counted 0 "retry"

  Scenario: A restored backup re-opens lines the database no longer holds
    When I run the bridge with apply
    And the database loses the criterion id "gpRRkq27"
    And I run the bridge
    Then the bridge reopened 1 line
```

- [ ] **Step 2: Write the step definitions**

Create `tests/step_defs/test_criterion_bridge.py`:

```python
"""`criterion bridge`: assertions read the DATABASE and the observation file."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.criterion_bridge import BRIDGE_FILE, load_observations, run_bridge
from movie_brain.domain.models import Film
from movie_brain.infrastructure.criterion_site import CatalogItem, Forward, classify_forward

scenarios("../features/criterion_bridge.feature")

SITE = "https://www.criterionchannel.com/"
NOW = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)


class Interrupted(Exception):
    pass


@pytest.fixture
def ctx(repo, config_dir):
    return {"repo": repo, "dir": config_dir, "answers": {}, "catalog": [], "asks": 0, "stop_after": None}


def _fid(ctx, title):
    conn = sqlite3.connect(ctx["repo"].db_path)
    try:
        return conn.execute("SELECT id FROM films WHERE title = ?", (title,)).fetchone()[0]
    finally:
        conn.close()


def _ask(ctx):
    def ask(url: str) -> Forward:
        if ctx["stop_after"] is not None and ctx["asks"] >= ctx["stop_after"]:
            raise Interrupted
        ctx["asks"] += 1
        status, location = ctx["answers"][url]
        return classify_forward(status, location)

    return ask


def _run(ctx, apply=False, retry=False):
    ctx["report"] = run_bridge(
        ctx["repo"], ctx["dir"], ctx["catalog"], _ask(ctx), NOW, apply=apply, retry=retry
    )


@given(parsers.parse('a Criterion film "{title}" ({year:d}) at old link "{slug}"'))
def crit_film(ctx, title, year, slug):
    ctx["repo"].record_catalog("criterion", [Film(title, year, None, SITE + slug)], date(2026, 9, 20))


@given(parsers.parse('the film "{title}" also holds old link "{slug}"'))
def second_link(ctx, title, slug):
    ctx["repo"].set_external_id(_fid(ctx, title), "criterion", SITE + slug, date(2026, 9, 20))


@given(parsers.parse('the old link "{slug}" forwards to "{location}"'))
@when(parsers.parse('the old link "{slug}" forwards to "{location}"'))
def forwards(ctx, slug, location):
    ctx["answers"][SITE + slug] = (307, location)


@given(parsers.parse('the old link "{slug}" answers 404'))
def answers_404(ctx, slug):
    ctx["answers"][SITE + slug] = (404, None)


@given(parsers.parse('the old link "{slug}" fails'))
def fails(ctx, slug):
    ctx["answers"][SITE + slug] = (None, None)


@given(parsers.parse('the catalog lists "{mediaid}" as "{title}" ({year:d})'))
def catalog_lists(ctx, mediaid, title, year):
    ctx["catalog"].append(CatalogItem(mediaid, title, year, 5000))


@given(parsers.parse("the first run is interrupted after {n:d} answer"))
def interrupted(ctx, n):
    ctx["stop_after"] = n
    with pytest.raises(Interrupted):
        _run(ctx)
    ctx["stop_after"] = None


@when("I run the bridge")
def run_dry(ctx):
    _run(ctx)


@when("I run the bridge with apply")
def run_apply(ctx):
    _run(ctx, apply=True)


@when("I run the bridge with retry")
def run_retry(ctx):
    _run(ctx, retry=True)


@when(parsers.parse('the database loses the criterion id "{mediaid}"'))
def loses_id(ctx, mediaid):
    conn = sqlite3.connect(ctx["repo"].db_path)
    conn.execute("DELETE FROM external_ids WHERE authority = 'criterion' AND value = ?", (mediaid,))
    conn.commit()
    conn.close()


@then(parsers.parse('the bridge counted {n:d} "{kind}"'))
def counted(ctx, n, kind):
    assert ctx["report"].counts.get(kind, 0) == n, ctx["report"].counts


@then(parsers.parse('the drift shows "{title}" {old:d} → {new:d} as "{kind}"'))
def drift(ctx, title, old, new, kind):
    assert [(d.title, d.year, d.cat_year, d.kind) for d in ctx["report"].drift] == [(title, old, new, kind)]


@then(parsers.parse('the film "{title}" holds no criterion id'))
def no_id(ctx, title):
    ids = ctx["repo"].external_ids_all(_fid(ctx, title))
    assert not [v for a, v in ids if a == "criterion" and not v.startswith("http")]


@then(parsers.parse('the film "{title}" holds criterion id "{mediaid}"'))
def holds_id(ctx, title, mediaid):
    assert ("criterion", mediaid) in ctx["repo"].external_ids_all(_fid(ctx, title))


@then(parsers.parse('the film "{title}" is listed at "{url}"'))
def listed_at(ctx, title, url):
    conn = sqlite3.connect(ctx["repo"].db_path)
    got = conn.execute(
        "SELECT url FROM listings WHERE film_id = ? AND source = 'criterion'", (_fid(ctx, title),)
    ).fetchone()[0]
    conn.close()
    assert got == url


@then(parsers.parse('the film "{title}" is still {year:d}'))
def still_year(ctx, title, year):
    conn = sqlite3.connect(ctx["repo"].db_path)
    got = conn.execute("SELECT year FROM films WHERE id = ?", (_fid(ctx, title),)).fetchone()[0]
    conn.close()
    assert got == year


@then(parsers.parse("the observation file has {n:d} line"))
def file_lines(ctx, n):
    assert len(load_observations(ctx["dir"] / BRIDGE_FILE)) == n


@then(parsers.parse("the site was asked {n:d} time"))
@then(parsers.parse("the site was asked {n:d} times"))
def asked(ctx, n):
    assert ctx["asks"] == n


@then(parsers.parse('there is {n:d} open criterion "{reason}" review'))
@then(parsers.parse('there are {n:d} open criterion "{reason}" reviews'))
def open_reviews(ctx, n, reason):
    assert len([r for r in ctx["repo"].open_reviews("criterion") if r["reason"] == reason]) == n


@then(parsers.parse("the bridge reopened {n:d} line"))
def reopened(ctx, n):
    assert ctx["report"].reopened == n
```

Note on the interrupted scenario's arithmetic: the Background creates Test Pattern (lower film id) and the scenario adds Bigger Than Life. The interrupted run asks Test Pattern (asks = 1) and raises before Bigger Than Life. The resumed dry run reuses Test Pattern's saved answer and asks only Bigger Than Life (asks = 2). `ctx["asks"]` counts successful asks across both runs → **2**.

Note on the retry scenario: run 1 records `penkelemes` as `retry`; the `When` step then changes the site's answer; run 2 (plain) reuses the saved `retry` answer → counts 1 `retry`; run 3 with `retry=True` asks again → film → 0 `retry`.

Note on "Apply within a day replays": run 1 (dry) asks 1; run 2 (apply, same `NOW`) finds a fresh observation → asks 0 → total **1**.

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/step_defs/test_criterion_bridge.py -q`
Expected: ImportError for `run_bridge`.

- [ ] **Step 4: Implement `run_bridge`** (append to `application/criterion_bridge.py`; add imports `from collections.abc import Callable`, `from urllib.parse import urlparse`, `from movie_brain.domain.models import ReviewEntry`, `from movie_brain.infrastructure.criterion_site import BASE, CatalogItem`, `from movie_brain.infrastructure.database import Repository`)

```python
@dataclass(frozen=True)
class DriftLine:
    film_id: int
    title: str
    year: int | None
    cat_title: str
    cat_year: int | None
    kind: str  # title | year | both


@dataclass
class BridgeReport:
    counts: dict[str, int]
    drift: list[DriftLine]
    reviews: int
    applied: bool
    reopened: int


def run_bridge(
    repo: Repository,
    config_dir: Path,
    catalog: list[CatalogItem],
    ask: Callable[[str], Forward],
    now: datetime,
    apply: bool,
    retry: bool,
) -> BridgeReport:
    path = config_dir / BRIDGE_FILE
    obs = load_observations(path)

    reopened = 0
    for o in obs.values():
        if o.applied and o.forward.mediaid and ("criterion", o.forward.mediaid) not in repo.external_ids_all(o.film_id):
            o.applied = False
            reopened += 1

    targets = repo.criterion_old_urls()
    for t in targets:
        o = obs.get(t.url)
        reuse = o is not None and (not apply or is_fresh(o, now)) and not (retry and o.forward.kind == "retry")
        if reuse:
            assert o is not None
            o.film_id = t.film_id
            continue
        f = ask(t.url)
        o = Observation(t.url, t.film_id, f.status, f.location, now.isoformat())
        append_observation(path, o)
        obs[t.url] = o

    holders = {v: repo.canonical_film_id(fid) for v, fid in repo.external_id_holders("criterion").items()
               if not v.startswith("http")}
    open_keys = {(str(r["reason"]), r["film_id"], r["value"]) for r in repo.open_reviews("criterion")}
    decided = repo.resolved_review_keys("criterion")
    by_mediaid = {c.mediaid: c for c in catalog}
    titles = {t.film_id: (t.title, t.year) for t in targets}

    counts: dict[str, int] = {}
    bindings: list[tuple[int, str, str]] = []
    bound_urls: list[str] = []
    reviews: list[ReviewEntry] = []
    drift: list[DriftLine] = []
    for t in targets:
        o = obs[t.url]
        f = o.forward
        kind = f.kind
        if kind == "film":
            assert f.mediaid is not None
            holder = holders.get(f.mediaid)
            if holder is None:
                holders[f.mediaid] = t.film_id
                bindings.append((t.film_id, f.mediaid, BASE + urlparse(f.location).path))
                bound_urls.append(t.url)
            elif holder == t.film_id:
                kind = "same-film"
                bound_urls.append(t.url)
            else:
                kind = "held"
                key = ("id-conflict", t.film_id, f.mediaid)
                if key not in open_keys and key not in decided:
                    open_keys.add(key)
                    reviews.append(ReviewEntry("id-conflict", t.film_id, f.mediaid,
                                               json.dumps({"holder": holder, "url": t.url})))
            if kind in ("film", "same-film") and f.mediaid in by_mediaid:
                cat = by_mediaid[f.mediaid]
                title, year = titles[t.film_id]
                diff_t, diff_y = cat.title != title, cat.year != year
                if diff_t or diff_y:
                    dk = "both" if diff_t and diff_y else ("title" if diff_t else "year")
                    if not any(d.film_id == t.film_id for d in drift):
                        drift.append(DriftLine(t.film_id, title, year, cat.title, cat.year, dk))
        counts[kind] = counts.get(kind, 0) + 1

    if apply:
        repo.record_bridge(bindings, reviews, now.date())
        for url in bound_urls:
            obs[url].applied = True
        rewrite_observations(path, obs.values())
    return BridgeReport(counts, drift, len(reviews), apply, reopened)
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/step_defs/test_criterion_bridge.py -q`
Expected: `9 passed`.

- [ ] **Step 6: Run the whole suite for regressions**

Run: `uv run pytest -q -x`
Expected: all pass (sync and the old Criterion tests untouched).

- [ ] **Step 7: Commit**

```bash
git add src/movie_brain/application/criterion_bridge.py tests/features/criterion_bridge.feature tests/step_defs/test_criterion_bridge.py
git commit -m "Bridge every stored Criterion link to its new id, clashes to review, titles and years untouched

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: The CLI verb, docs, backlog

**Files:**
- Modify: `src/movie_brain/cli.py` (new typer group after `services_app`, ~line 110; command near `films add`, ~line 677)
- Modify: `tests/unit/test_cli.py`, `CLAUDE.md`, `docs/backlog.md`

**Interfaces:**
- Consumes: `fetch_catalog`, `head_old_url`, `CriterionError`, `BRIDGE_DELAY_S` (criterion_site), `run_bridge`, `BridgeReport` (criterion_bridge), `Pacer`
- Produces: `movie-brain criterion bridge [--apply] [--retry]`; exit 0 on success, 1 when the catalog walk fails (nothing asked, nothing written).

Output shape (stdout, plain, no Rich markup):

```
DRY RUN — nothing written (add --apply)
links: 3095 · film 2871 · same film 12 · clash 12 · extra 4 · gone 68 · retry 0 · reopened 0
drift: 178 films (97 year · 72 title · 9 both)
  #56     Test Pattern (2019)  →  Test Pattern (2021)  year
  ...
```

With `--apply` the first line is `APPLIED — ids written, N clash reviews queued`.

- [ ] **Step 1: Write the failing CLI test** (append to `tests/unit/test_cli.py`)

```python
def test_criterion_bridge_wires_the_use_case(config_dir, monkeypatch):
    from movie_brain.application.criterion_bridge import BridgeReport, DriftLine

    seen = {}

    def fake_catalog(session, **kw):
        return []

    def fake_run(repo, cfg_dir, catalog, ask, now, apply, retry):
        seen.update(apply=apply, retry=retry, cfg_dir=cfg_dir)
        return BridgeReport({"film": 1}, [DriftLine(56, "Test Pattern", 2019, "Test Pattern", 2021, "year")], 0, apply, 0)

    monkeypatch.setattr("movie_brain.infrastructure.criterion_site.fetch_catalog", fake_catalog)
    monkeypatch.setattr("movie_brain.application.criterion_bridge.run_bridge", fake_run)
    r = runner.invoke(app, ["criterion", "bridge"])
    assert r.exit_code == 0, r.output
    assert seen == {"apply": False, "retry": False, "cfg_dir": config_dir}
    assert "DRY RUN" in r.output and "#56" in r.output and "2019" in r.output and "2021" in r.output


def test_criterion_bridge_catalog_failure_exits_1(config_dir, monkeypatch):
    from movie_brain.infrastructure.criterion_site import CriterionError

    def boom(session, **kw):
        raise CriterionError("catalog: empty page")

    monkeypatch.setattr("movie_brain.infrastructure.criterion_site.fetch_catalog", boom)
    r = runner.invoke(app, ["criterion", "bridge", "--apply"])
    assert r.exit_code == 1
    assert "empty page" in r.output
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_cli.py -q -k criterion_bridge`
Expected: exit code 2 ("No such command 'criterion'").

- [ ] **Step 3: Implement**

In `src/movie_brain/cli.py`, after the `services_app` lines (~110):

```python
criterion_app = typer.Typer(help="Criterion Channel after the 2026-10 relaunch: bridge stored films to their new ids.")
app.add_typer(criterion_app, name="criterion")
```

and near `films add` (~677):

```python
@criterion_app.command("bridge")
def criterion_bridge_cmd(
    apply: Annotated[bool, typer.Option("--apply", help="Write the ids (default: dry run, answers kept on disk).")] = False,
    retry: Annotated[bool, typer.Option("--retry", help="Ask again the links whose last answer failed.")] = False,
) -> None:
    """Give every stored Criterion film its new id, by asking each old link where it forwards.

    One catalog walk (for the drift table), then one quick check per old link, 0.4 s apart —
    about 25–30 minutes. Answers are kept in <config_dir>/criterion-bridge.jsonl, so an
    interrupted run resumes and an --apply within a day replays them without asking again."""
    from datetime import datetime, timezone

    import requests

    from movie_brain.application import criterion_bridge
    from movie_brain.infrastructure import criterion_site
    from movie_brain.infrastructure.cheapcharts import Pacer

    cfg = load_config()
    repo = _repo()
    session = requests.Session()
    try:
        catalog = criterion_site.fetch_catalog(session)
    except criterion_site.CriterionError as exc:
        console.print(f"FAILED    catalog walk: {exc} — nothing asked, nothing written", markup=False, highlight=False)
        raise typer.Exit(1) from exc
    pacer = Pacer(criterion_site.BRIDGE_DELAY_S)
    report = criterion_bridge.run_bridge(
        repo, cfg.config_dir, catalog,
        lambda url: criterion_site.head_old_url(session, url, pacer),
        datetime.now(timezone.utc), apply=apply, retry=retry,
    )
    c = report.counts
    head = (f"APPLIED — ids written, {report.reviews} clash reviews queued" if apply
            else "DRY RUN — nothing written (add --apply)")
    console.print(head, markup=False, highlight=False)
    console.print(
        f"links: {sum(c.values())} · film {c.get('film', 0)} · same film {c.get('same-film', 0)} · "
        f"clash {c.get('held', 0)} · extra {c.get('supplement', 0)} · gone {c.get('gone', 0)} · "
        f"retry {c.get('retry', 0)} · reopened {report.reopened}",
        markup=False, highlight=False,
    )
    kinds = {k: sum(1 for d in report.drift if d.kind == k) for k in ("year", "title", "both")}
    console.print(
        f"drift: {len(report.drift)} films ({kinds['year']} year · {kinds['title']} title · {kinds['both']} both)",
        markup=False, highlight=False,
    )
    for d in report.drift:
        console.print(
            f"  #{d.film_id:<6} {d.title} ({d.year})  →  {d.cat_title} ({d.cat_year})  {d.kind}",
            markup=False, highlight=False, soft_wrap=True,
        )
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/test_cli.py -q -k criterion_bridge`
Expected: `2 passed`.

- [ ] **Step 5: Docs**

In `CLAUDE.md`, in the Commands block, add one line directly after the `films add` line:

```
uv run movie-brain criterion bridge [--apply] [--retry]     # one-shot after Criterion's 2026-10-01 relaunch (backlog 50, spec docs/superpowers/specs/2026-10-01-criterion-relaunch-design.md D3): walks the new catalog once for a drift table, then asks every stored old `criterionchannel.com/<slug>` link where it forwards (0.4 s apart, ~25–30 min) and records the film's new id (`external_ids` authority `criterion`, an 8-character mediaid beside the old URL rows); answers kept in <config_dir>/criterion-bridge.jsonl so a stopped run resumes and `--apply` within 24 h replays them; titles and years never change; an id another film holds queues an `id-conflict` review (dismiss only), never a merge; `--retry` re-asks failed links; dry run by default. Sync still uses the dead VHX reader until Plan B
```

In `docs/backlog.md`, append item 50 at the end of the numbered list (one unbroken line):

```
50. [ ] **Criterion relaunch** — the Criterion Channel left VHX for a Next.js + JW Player site on 2026-10-01 and sync stopped at `no window.TOKEN`. Seed, spec, brief and gap check A: `docs/superpowers/specs/2026-10-01-criterion-relaunch-seed.md`, `…-design.md`, `docs/superpowers/briefs/2026-10-01-criterion-relaunch/`; plain-language plan page published for the owner. Identity moves to Criterion's own id (mediaid) because 178 films were re-titled or re-dated in the move. Built in three plans in rollout order (branch `feature/STORY-50-criterion-relaunch`): A — new reader + `criterion bridge` (plan `docs/superpowers/plans/2026-10-01-criterion-relaunch-plan-a.md`); B — the new walk; C — directors.
```

- [ ] **Step 6: Whole suite, lint, types**

Run: `uv run pytest -q && uv run ruff check src tests && uv run mypy src`
Expected: all pass, no lint or type errors. (If the repo has no mypy config, `uv run mypy src` may be absent — then run only pytest and ruff, and say so in the hand-back.)

- [ ] **Step 7: Commit**

```bash
git add src/movie_brain/cli.py tests/unit/test_cli.py CLAUDE.md docs/backlog.md
git commit -m "criterion bridge verb: the owner can see every renamed film before any id is written

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## After the plan (not tasks — the owner's steps)

Rollout steps 1–2 may run as soon as this plan is merged into the branch, on the owner's yes: a dated copy of the live DB, then `uv run movie-brain criterion bridge` (dry run, ~25–30 min, in the builder's background shell, output to a log; `pgrep` first). The dry run writes only `<config_dir>/criterion-bridge.jsonl`. `--apply` is rollout step 3 and waits for Plans B and C and gap check point C (spec §8).
