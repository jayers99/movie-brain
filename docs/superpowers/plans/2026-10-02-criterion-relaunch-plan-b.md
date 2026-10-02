# Criterion Relaunch — Plan B (the walk) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `movie-brain sync` walk the relaunched Criterion Channel again: match every catalog item to a film by its Criterion id (mediaid), list known films, send unknown ones through JW Player → the thumbprint resolver → the `films add` gate ladder, write everything in ONE transaction, and let a human settle what the walk could not place with `review resolve`.

**Architecture:** A new application use case `application/criterion_walk.py::walk_criterion` stages the whole walk with no writes (catalog → per-item identity decision → leaving labels), hands one `CriterionWalk` value to ONE new repository method `record_criterion_walk` (single transaction), then keys the films it created. `sync()` calls it in place of the VHX steps 1–3 and catches any failure so the rest of the night still runs (exit 1). The `films add` ladder is factored into `application/films.py::gate_ladder`, shared by `films add`, the walk and the new `application/criterion_review.py` (review resolution for `criterion` rows). The dead VHX reader goes.

**Tech Stack:** Python 3.12, requests, `responses`, pytest + pytest-bdd, typer, SQLite via `Repository`.

**Spec:** `docs/superpowers/specs/2026-10-01-criterion-relaunch-design.md` (this plan builds §8 Plan B: D2, D4–D6, D9–D13, the §5 Sync and Review tests, the §6 doc updates). Read beside it: `docs/superpowers/handoffs/2026-10-02-criterion-plan-b-handoff.md` — its measured numbers SUPERSEDE the spec's sampled ones. Plan A (the adapter this plan consumes): `docs/superpowers/plans/2026-10-01-criterion-relaunch-plan-a.md`. Stories: `docs/superpowers/briefs/2026-10-01-criterion-relaunch/brief.md` (stories 1, 3–8, 10, 11, 13, 15–18 are this plan's; story 9 is Plan C's).

## Global Constraints

- Worktree `/Users/jayers/code/movie-brain-dev`, branch `feature/STORY-50-criterion-plan-b` (cut from Plan A's head `700938c`). Never touch `/Users/jayers/code/movie-brain`.
- No live database writes and no sync run against `~/.config/movie-brain` in this build. Tests use the `repo` / `config_dir` fixtures only.
- No schema change, no migration (spec D2: the mediaid is a claim-authority `external_ids` row beside the old URL rows).
- `films.title` / `films.year` of an existing film are never written by the walk; `films.director` of an existing film is never written by the walk (D4). A film the walk CREATES takes TMDB's title and year and Criterion's director (D5).
- The walk matches a catalog item to a film by mediaid FIRST; `film_key` never matches a Criterion item again (D2).
- Fixture SHAPES come from the real captures in `tests/fixtures/criterion/` (copied from `docs/superpowers/research/2026-10-01-criterion-relaunch/` by Plan A). A JW record in a test is the captured `jw-media.L5Z3RaiC.json` with named fields changed. Synthetic only where no real answer exists (half-walk failure, write failure, held-by-other, 429). IMDb ids in tests are synthetic `tt9000xxx`; mediaids are the real ones where the film is named in the spec or handoff.
- Resolver reason strings and `find_holder` labels are contract text — never reword them (`.claude/rules/thumbprint.md`, `.claude/rules/lists.md`).
- Every `.md` written: never hard-wrap prose (one paragraph = one line).
- Commits: one short line about WHY, then a blank line and `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- `uv run ruff check src tests` is clean before every commit (line length 120 in `src`; `tests/*` ignores E501). The plan's code was written by hand, not machine-formatted: wrap any `src` line ruff flags, change nothing else.
- Before the first test run in a fresh shell: `cd /Users/jayers/code/movie-brain-dev && uv sync --extra semantic` (a bare `uv sync` removes the semantic extra). Baseline on `26e167e`: **1985 passed**. `mypy src` shows only main's 3 pre-existing errors.

## Review Focus

1. **The owner runs `sync` before `criterion bridge --apply`** (the dry run has been done, the apply has not) → no film holds a mediaid yet, so every listed film would read as departed and all ~3,000 catalog items as unknown. A reasonable person expects the walk to refuse and say why, writing nothing. Test in Task 4 (`walk_criterion` raises `CriterionError` naming the bridge; nothing written).
2. **A second walk on the same day** → departs nothing and re-arrives nothing (currency is date-grained, D6). Test in Task 3.
3. **A mediaid that sits on a merged-away film** (a merge after the bridge) → the item is listed on the merge survivor, never re-bound and never twinned. Test in Task 3 (`criterion_mediaid_holders` canonicalises).
4. **A leaving page names a mediaid no film holds** (a new film the walk skipped tonight, or one whose review is open) → no label is written anywhere and nothing fails. Test in Task 3.
5. **A JW record with an empty director list** (`"director": "[]"`) → the resolver query and the created film carry `None`, never an empty string. Test in Task 4.

## Measured numbers this plan builds against (handoff 2026-10-02, full bridge dry run)

| Fact | Number |
|---|---|
| Old links forwarding to a film | 2,836 |
| Old links now 404 / now supplements | 250 / 9 |
| Clashes (`held`) | 0 → no `id-conflict` review rows will exist after `--apply` |
| Films binding two different mediaids | 3 (Eve's Bayou #1150, Dr. Dolittle #1285, Darwin #759) |
| Films left with no working link | 241 (49 rated, 0 watchlisted, 0 viewed) |
| Films bridged to a mediaid not in the Oct 1 catalog | 43 (computed 2026-10-02 from the observation file against `catalog-2026-10-01.json`) |
| Catalog films no film will hold after `--apply` (asked about on the first walk) | 215 (same computation) |
| Multi-part episode films (#1368–1372, #1579–1582, #1720, #2067–2071) | all 15 now answer 404 → they depart; no `id-conflict` rows |

First-walk expectation (replaces spec D13's): ~67 arrivals with an October licence; departures up to ~284 (241 + 43), fewer where D5 rejoins a 404 film through its new mediaid (Grey Gardens #1817, Mirror #2476, Being Frank #3076, Factory #1689, Fanny and Alexander #3091); 215 JW lookups + resolver runs.

## Ledger — rulings this plan makes (surfaced to the owner on the plan page)

- **L1 (needs the owner's yes — departs from spec D9's text).** On the HUMAN paths (`review resolve --create` and `--tt` on a `criterion` row) gate 3 (`corpus_veto`) WARNS and does not refuse. Gates 1/2/2b, the tombstone and the `films.key` collision still refuse. Why: gate 3 is year-blind, so a remake never gets past it — The Beast (2023) is vetoed by any "The Beast" we hold, and its row would be undrainable except by `--dismiss`. The walk (no human) keeps gate 3 as a refusal. Alternative: follow D9 literally and accept that such rows can only be dismissed or `--film`-linked.
- **L2.** A film listed under two mediaids where only one is on a leaving page is labelled leaving (Eve's Bayou: the theatrical cut leaves Oct 31, the director's cut stays). Story 6 names Eve's Bayou among the 28.
- **L3.** The walk's gate 3 also asks Criterion's printed title and JW's original title, not only TMDB's (refusing direction only).
- **L4.** `films add` now reports a `films.key` collision on the DRY RUN too (the shared ladder checks the key before writing); before, only `--apply` found it.
- **L5.** Two new works whose titles resemble each other in one walk: the second becomes a `corpus-veto` review row (the staged-title check runs before the staged-key check).
- **L6.** A leaving playlist with a second page fails the leaving step (labels kept, D7) instead of being followed — no real two-page answer exists to build from.
- **L7.** The walk refuses outright when films are listed on Criterion but none holds a mediaid (Review Focus 1).
- **L8.** `sync()` loses `delay_s`, `force_full`, `max_age_days`; `SyncResult` loses `full_walk` and gains `criterion_walked`, `criterion_failed`, `criterion_arrived`, `criterion_departed`, `criterion_reviews`, `criterion_skipped`. The CLI line is spec D11's, plus `· not asked tonight N` only when N > 0.
- **L9.** Unknown items are checked for a resolver BEFORE the JW call: a night with no TMDB token makes no JW calls at all.
- **L10.** Parked findings from Plan A's reviews are all handled here: site pages on the site's pace (Task 1), earliest leaving date wins (Task 1), >500 playlist raises (Task 1), the production `assert` goes (Task 1), a non-object JSON body raises `CriterionError` (Task 1), the third claim-value shape is written into `thumbprint.md` (Task 8), a tombstoned film never binds in the bridge + a progress line every 250 links (Task 7). `asked_at` stays the run's start time: it only makes freshness conservative.

## Open question for the owner (kept until answered; blocks rollout step 3, not this build)

Darwin #759 bound two mediaids (`darwin-what` → `9DlZ3IcB`, `darwin-what-what` → `HjxbRX53`). Evidence gathered 2026-10-02 (read-only): JW lists two records with different `criterion_id` (34345, 34346), different directors credit (Rossellini alone / Rossellini and Magid) and different release dates (2020-01-01 / 2020-04-06), both 480 s. #760 "Darwin, What?" was merged into #759 "Darwin, What? What?" on 2026-08-24 by `repair dupes` only because both resolved to TMDB 703322, which is "Darwin, What?". Recommendation: two works. The code in this plan is the same either way (one film holding two mediaids is handled generically); the answer decides a one-at-a-time live repair before `--apply`.

---

## File map

| File | Responsibility |
|---|---|
| Modify `src/movie_brain/infrastructure/criterion_site.py` | `parse_media`, `HttpCriterionSite`, `CRITERION_FILM_URL`, `_json_object`; `fetch_leaving` hardening |
| Modify `src/movie_brain/application/films.py` | `Ladder`, `gate_ladder` (the shared creating gates), `add_by_id` on top of it |
| Modify `src/movie_brain/domain/models.py` | `NewFilm`, `WalkListing`, `CriterionWalk`, `WalkWrite` |
| Modify `src/movie_brain/infrastructure/database.py` | `criterion_mediaid_holders`, `criterion_review_values`, `bind_criterion_mediaid`, `create_criterion_film`, `record_criterion_walk` + three static helpers |
| Create `src/movie_brain/application/criterion_walk.py` | `walk_criterion`, `WalkReport`, `CriterionSite`, `criterion_detail`, `parse_criterion_detail` |
| Modify `src/movie_brain/application/sync.py` | the walk replaces steps 1–3; `SyncResult` fields |
| Delete `src/movie_brain/infrastructure/criterion.py`, `tests/unit/test_criterion.py` | the dead VHX reader (D11) |
| Create `src/movie_brain/application/criterion_review.py` | `resolve_criterion_row` (D9) |
| Modify `src/movie_brain/application/review.py` | route `criterion` rows |
| Modify `src/movie_brain/cli.py` | sync line, `--full` help, `review resolve` enrichment after a criterion `--tt` creation, bridge progress |
| Modify `src/movie_brain/application/criterion_bridge.py` | tombstoned films never bind; progress callback |
| Modify `src/movie_brain/application/repair.py` | D12: the Criterion re-key blocker goes |
| Create `tests/criterion_fakes.py` | `FakeSite`, `media_like`, `captured_media`, `mediaid_for`, `seed_known` |
| Create `tests/unit/test_gate_ladder.py`, `tests/unit/test_criterion_walk_repository.py` | ladder + repository tests |
| Create `tests/features/criterion_walk.feature`, `tests/features/criterion_review.feature`, `tests/step_defs/test_criterion_walk.py` | walk + review scenarios (one step module binds both feature files) |
| Rewrite `tests/features/sync.feature`, `tests/step_defs/test_sync.py` | sync integration over HTTP with the real capture shapes |
| Modify `tests/step_defs/test_tmdb.py`, `tests/step_defs/test_watchlist.py`, `tests/features/tmdb.feature`, `tests/features/watchlist.feature` | Criterion becomes a `FakeSite` listing known films |
| Modify `tests/unit/test_criterion_site.py`, `tests/unit/test_cli.py`, `tests/unit/test_thumbprint.py`, `tests/unit/test_criterion_bridge_file.py`, `tests/features/criterion_bridge.feature`, `tests/step_defs/test_criterion_bridge.py` | per task |
| Modify `CLAUDE.md`, `.claude/rules/sync-flow.md`, `.claude/rules/thumbprint.md`, `.claude/rules/identity.md`, `.claude/rules/lists.md`, the spec, the brief, `docs/backlog.md` | Task 8 |

---

### Task 1: Adapter hardening, `parse_media`, `HttpCriterionSite`

**Files:**
- Modify: `src/movie_brain/infrastructure/criterion_site.py`
- Test: `tests/unit/test_criterion_site.py`

**Interfaces:**
- Consumes: Plan A's `fetch_catalog`, `fetch_media`, `fetch_leaving`, `_get`, `Pacer`.
- Produces:
  - `CRITERION_FILM_URL = BASE + "/films/{}"`
  - `def parse_media(body: dict[str, Any], mediaid: str) -> JwMedia` (raises `CriterionError` on an empty playlist)
  - `def fetch_leaving(session, pacer=None, sleep=time.sleep, *, site_pacer: Pacer | None = None, today: date | None = None) -> Leaving`
  - `class HttpCriterionSite` with `__init__(self, session: requests.Session, sleep: Callable[[float], None] = time.sleep)`, `catalog() -> list[CatalogItem]`, `media(mediaid: str) -> JwMedia | None`, `leaving() -> Leaving`

- [ ] **Step 1: Write the failing tests**

Add to the imports at the top of `tests/unit/test_criterion_site.py` (keep the existing ones):

```python
from datetime import date

from movie_brain.infrastructure.criterion_site import (
    CRITERION_FILM_URL,
    HttpCriterionSite,
    parse_media,
)
```

Append to `tests/unit/test_criterion_site.py`:

```python
# --- Plan B: parked findings from Plan A's reviews, and the walk's site object -------------


@responses.activate
def test_a_catalog_body_that_is_a_list_raises_criterion_error():
    responses.get(CATALOG_URL, json=[])
    with pytest.raises(CriterionError, match="JSON object"):
        fetch_catalog(requests.Session(), sleep=_no_sleep)


@responses.activate
def test_a_media_body_that_is_a_list_raises_criterion_error():
    responses.get(JW_MEDIA_URL.format("L5Z3RaiC"), json=[])
    with pytest.raises(CriterionError, match="JSON object"):
        fetch_media(requests.Session(), "L5Z3RaiC", sleep=_no_sleep)


@responses.activate
def test_site_pages_wait_the_site_pace_and_the_playlist_the_jw_pace():
    _leaving_mocks()
    site_sleeps: list[float] = []
    jw_sleeps: list[float] = []
    fetch_leaving(
        requests.Session(),
        pacer=Pacer(0.25, sleep=jw_sleeps.append, clock=lambda: 0.0),
        sleep=_no_sleep,
        site_pacer=Pacer(1.0, sleep=site_sleeps.append, clock=lambda: 0.0),
    )
    assert site_sleeps == [1.0]  # home page, then the dated page one site-second later
    assert jw_sleeps == []  # one playlist call: nothing to wait for


def _playlist_page(pid: str) -> str:
    # The RSC payload escapes its quotes; this is the token the parser reads, verbatim.
    return '<script>p(\\"playlistID\\":\\"' + pid + '\\")</script>'


@responses.activate
def test_a_film_on_two_dated_pages_keeps_the_sooner_date():
    # 'august' sorts before 'september', so the old last-page-wins code labelled September 30.
    responses.get(BASE + "/", body='<a href="/discover/leaving-august-31"></a><a href="/discover/leaving-september-30"></a>')
    one = _load("jw-playlist.0WbeKrrA.full.json")
    one["playlist"] = one["playlist"][:1]  # Zabriskie Point, Tg73fdO2
    for slug, pid in (("leaving-august-31", "AugPl001"), ("leaving-september-30", "SepPl001")):
        responses.get(BASE + "/discover/" + slug, body=_playlist_page(pid))
        responses.get(JW_PLAYLIST_URL.format(pid), json=one)
    result = fetch_leaving(requests.Session(), sleep=_no_sleep, today=date(2026, 8, 20))
    assert result.labels == {"Tg73fdO2": "August 31"}


@responses.activate
def test_a_playlist_with_a_next_page_raises_rather_than_cut_it_short():
    playlist = _load("jw-playlist.0WbeKrrA.full.json")
    playlist["links"]["next"] = playlist["links"]["first"].replace("page_offset=1", "page_offset=501")
    responses.get(BASE + "/", body=(FIX / "home-2026-10-01.html").read_text())
    responses.get(BASE + "/discover/leaving-october-31", body=(FIX / "leaving-october-31.html").read_text())
    responses.get(JW_PLAYLIST_URL.format("0WbeKrrA"), json=playlist)
    with pytest.raises(CriterionError, match="next page"):
        fetch_leaving(requests.Session(), sleep=_no_sleep)


def test_parse_media_reads_the_captured_record():
    m = parse_media(_load("jw-media.L5Z3RaiC.json"), "L5Z3RaiC")
    assert (m.mediaid, m.title, m.directors, m.criterion_id) == (
        "L5Z3RaiC", "2 or 3 Things I Know About Her", ("Jean-Luc Godard",), "1333",
    )
    assert m.title_original == "2 ou 3 choses que je sais d'elle"


def test_parse_media_with_an_empty_playlist_raises():
    with pytest.raises(CriterionError, match="empty playlist"):
        parse_media({"playlist": []}, "L5Z3RaiC")


@responses.activate
def test_the_http_site_answers_the_walk_through_the_three_readers():
    last = _load("all-films-results.lastpage.json")
    last["total"] = len(last["items"])  # served as the only page
    responses.get(CATALOG_URL, json=last)
    responses.get(JW_MEDIA_URL.format("L5Z3RaiC"), json=_load("jw-media.L5Z3RaiC.json"))
    responses.get(BASE + "/", body='<html><a href="/discover/leaving-soon"></a></html>')
    site = HttpCriterionSite(requests.Session(), sleep=_no_sleep)
    films = {i["mediaid"] for i in last["items"] if i["contentType"] == "film"}
    assert {c.mediaid for c in site.catalog()} == films
    assert site.media("L5Z3RaiC").directors == ("Jean-Luc Godard",)
    assert site.leaving().labels == {}


def test_a_new_films_link_is_its_bare_film_page():
    assert CRITERION_FILM_URL.format("gpRRkq27") == "https://www.criterionchannel.com/films/gpRRkq27"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd /Users/jayers/code/movie-brain-dev && uv run pytest tests/unit/test_criterion_site.py -q`
Expected: collection error — `ImportError: cannot import name 'CRITERION_FILM_URL'`.

- [ ] **Step 3: Implement**

In `src/movie_brain/infrastructure/criterion_site.py`:

After `BRIDGE_DELAY_S = 0.4` add:

```python
CRITERION_FILM_URL = BASE + "/films/{}"  # a new film's listing link; the site 308s it to the slugged page (D10)
```

Add this helper right after `_blank`:

```python
def _json_object(resp: requests.Response, what: str) -> dict[str, Any]:
    """The body as a JSON object, or CriterionError — never an AttributeError further down."""
    try:
        body = resp.json()
    except (ValueError, requests.exceptions.JSONDecodeError) as exc:
        raise CriterionError(f"{what}: malformed JSON — {exc}") from exc
    if not isinstance(body, dict):
        raise CriterionError(f"{what}: expected a JSON object, got {type(body).__name__}")
    return body
```

In `fetch_catalog`, replace

```python
        try:
            body = resp.json()
        except (ValueError, requests.exceptions.JSONDecodeError) as exc:
            raise CriterionError(f"catalog: malformed JSON — {exc}") from exc
```

with

```python
        body = _json_object(resp, "catalog")
```

Replace the whole of `fetch_media` with these two functions:

```python
def parse_media(body: dict[str, Any], mediaid: str) -> JwMedia:
    """One JW `/v2/media/<id>` answer → the fields the walk reads. An empty playlist raises."""
    playlist = body.get("playlist") or []
    if not playlist or not isinstance(playlist[0], dict):
        raise CriterionError(f"jw media {mediaid}: empty playlist")
    item = playlist[0]
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
    return parse_media(_json_object(resp, f"jw media {mediaid}"), mediaid)
```

Add after `_expiry_label`:

```python
def _soonest(label: str, today: date) -> tuple[int, int]:
    """Order key for a leaving label: months ahead of today's month, then the day. Of two dated
    pages naming one film, the one that comes first is the useful date."""
    month, day = label.split()
    return ((_MONTHS.index(month.lower()) + 1 - today.month) % 12, int(day))
```

Replace the whole of `fetch_leaving` with:

```python
def fetch_leaving(
    session: requests.Session,
    pacer: Pacer | None = None,
    sleep: Callable[[float], None] = time.sleep,
    *,
    site_pacer: Pacer | None = None,
    today: date | None = None,
) -> Leaving:
    """Labels from every DATED leaving page the home page links (D7). The label is the page's
    own slug; each film's `license_end_date_time` is only a cross-check, reported on mismatch.
    criterionchannel.com pages wait the site's pace (`site_pacer`), the JW playlists JW's
    (`pacer`). A film on two dated pages keeps the sooner date. A playlist with a next page
    raises: no two-page answer has ever been captured, so the walk keeps last-known labels."""
    pacer = pacer or Pacer(JW_DELAY_S, sleep=sleep)
    site_pacer = site_pacer or Pacer(CATALOG_DELAY_S, sleep=sleep)
    today = today or date.today()
    home = _get(session, BASE + "/", site_pacer, sleep)
    if home.status_code != 200:
        raise CriterionError(f"home page: HTTP {home.status_code}")
    pages = sorted({(path, label) for path, slug in _DATED.findall(home.text) if (label := label_from_slug(slug))})
    labels: dict[str, str] = {}
    mismatches: list[str] = []
    for path, label in pages:
        page = _get(session, BASE + path, site_pacer, sleep)
        if page.status_code != 200:
            raise CriterionError(f"{path}: HTTP {page.status_code}")
        pids = list(dict.fromkeys(_PLAYLIST_ID.findall(page.text)))
        if not pids:
            raise CriterionError(f"{path}: no playlistID found")
        for pid in pids:
            pl = _get(session, JW_PLAYLIST_URL.format(pid), pacer, sleep, params={"page_limit": 500})
            if pl.status_code != 200:
                raise CriterionError(f"playlist {pid}: HTTP {pl.status_code}")
            body = _json_object(pl, f"playlist {pid}")
            if (body.get("links") or {}).get("next"):
                raise CriterionError(f"playlist {pid}: more than 500 films — the next page is not read")
            for item in body.get("playlist") or []:
                mediaid = item.get("mediaid")
                if not mediaid:
                    continue
                held = labels.get(mediaid)
                if held is None or _soonest(label, today) < _soonest(held, today):
                    labels[mediaid] = label
                expiry = _expiry_label(item.get("license_end_date_time"))
                if expiry is not None and expiry != label:
                    mismatches.append(f"{mediaid} {item.get('title')!r}: page says {label}, expiry says {expiry}")
    return Leaving(labels, tuple(mismatches))
```

Append at the end of the module:

```python
class HttpCriterionSite:
    """The live site behind the nightly walk: one pacer per host — www.criterionchannel.com
    (the catalog and the leaving pages, 1 s apart) and cdn.jwplayer.com (0.25 s apart)."""

    def __init__(self, session: requests.Session, sleep: Callable[[float], None] = time.sleep) -> None:
        self.session = session
        self.sleep = sleep
        self.site_pacer = Pacer(CATALOG_DELAY_S, sleep=sleep)
        self.jw_pacer = Pacer(JW_DELAY_S, sleep=sleep)

    def catalog(self) -> list[CatalogItem]:
        return fetch_catalog(self.session, self.site_pacer, self.sleep)

    def media(self, mediaid: str) -> JwMedia | None:
        return fetch_media(self.session, mediaid, self.jw_pacer, self.sleep)

    def leaving(self) -> Leaving:
        return fetch_leaving(self.session, self.jw_pacer, self.sleep, site_pacer=self.site_pacer)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_criterion_site.py tests/step_defs/test_criterion_bridge.py -q`
Expected: all pass (Plan A's leaving tests still pass: their single dated page is unaffected).

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/infrastructure/criterion_site.py tests/unit/test_criterion_site.py
git commit -m "Criterion reader: one pacer per host, the sooner leaving date wins, odd answers raise CriterionError — Plan A's parked findings, before the walk relies on them

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The shared gate ladder (`films add` factored)

**Files:**
- Modify: `src/movie_brain/application/films.py`
- Test: `tests/unit/test_gate_ladder.py` (create); `tests/features/films.feature` must stay green unchanged

**Interfaces:**
- Consumes: `lists.find_holder`, `lists.corpus_veto`, `lists._veto_label`, `lists._film_label`, `lists._catalog`, `lists._key_new_film`, `matching.CandidateIndex`, `thumbprint.Verdict`.
- Produces (in `application/films.py`):
  - constants `CORPUS_VETO = "corpus-veto"`, `TOMBSTONED_HOLDER = "tombstoned-holder"`, `KEY_COLLISION = "key-collision"`, `NOT_A_FILM = "not-a-film"`
  - `@dataclass(frozen=True) class Ladder: kind: str; detail: str; reason: str = ""; holder: int | None = None; tmdb_id: int | None = None; title: str = ""; year: int | None = None; vetoed: str = ""`
  - `def gate_ladder(repo: Repository, tmdb: TmdbClient, verdict: Verdict, *, index: CandidateIndex, catalog: dict[int, tuple[str, int | None, str | None]], extra_forms: Sequence[str] = (), veto: bool = True, log: Callable[[str], None] = _stderr) -> Ladder` — `kind` ∈ `held | clear | blocked | weather`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_gate_ladder.py`:

```python
"""The creating gates, shared by `films add`, the Criterion walk and `review resolve` on a
criterion row (spec 2026-10-01 D5/D9). TMDB is the list tests' StubTmdb; ids are synthetic."""

from __future__ import annotations

from datetime import date

from lists_fakes import StubTmdb

from movie_brain.application.films import (
    CORPUS_VETO,
    KEY_COLLISION,
    NOT_A_FILM,
    TOMBSTONED_HOLDER,
    gate_ladder,
)
from movie_brain.application.lists import _catalog
from movie_brain.domain.matching import build_candidate_index
from movie_brain.domain.models import Film
from movie_brain.domain.thumbprint import Verdict
from movie_brain.infrastructure.tmdb import TmdbFacts

DAY = date(2026, 10, 3)


def _tmdb(tt="tt9000009", tid=909, title="The Glass Orchard", year=1961):
    t = StubTmdb(by_imdb={tt: tid})
    t.facts[tid] = TmdbFacts(tt, title, title, (), year, 90)
    return t


def _ladder(repo, tmdb, tt, **kw):
    rows = repo.films_for_matching()
    return gate_ladder(
        repo, tmdb, Verdict("match", tt, "test", ()),
        index=build_candidate_index(rows), catalog=_catalog(repo, rows), log=lambda _m: None, **kw,
    )


def test_a_film_holding_the_id_is_the_holder(repo):
    fid = repo.create_film(Film("Harbour Lights", 1972, None, ""))
    repo.set_external_id(fid, "imdb", "tt9000002", DAY)
    lad = _ladder(repo, _tmdb(), "tt9000002")
    assert (lad.kind, lad.holder) == ("held", fid)


def test_a_failed_gate_2b_is_weather_not_a_verdict(repo):
    assert _ladder(repo, StubTmdb(raises=True), "tt9000009").kind == "weather"


def test_an_id_tmdb_does_not_know_as_a_film_is_refused(repo):
    lad = _ladder(repo, StubTmdb(), "tt9000010")
    assert (lad.kind, lad.reason) == ("blocked", NOT_A_FILM)


def test_every_gate_clear_names_tmdbs_title_and_year(repo):
    lad = _ladder(repo, _tmdb(), "tt9000009")
    assert (lad.kind, lad.title, lad.year, lad.tmdb_id, lad.vetoed) == ("clear", "The Glass Orchard", 1961, 909, "")


def test_an_extra_form_widens_gate_3(repo):
    repo.create_film(Film("Le Verger de verre", 1961, None, ""))
    assert _ladder(repo, _tmdb(), "tt9000009").kind == "clear"
    lad = _ladder(repo, _tmdb(), "tt9000009", extra_forms=("Le Verger de verre",))
    assert (lad.kind, lad.reason) == ("blocked", CORPUS_VETO)


def test_with_the_veto_off_a_resemblance_is_reported_not_refused(repo):
    repo.create_film(Film("The Glass Orchard", 1999, None, ""))  # a remake: same title, other year
    lad = _ladder(repo, _tmdb(), "tt9000009", veto=False)
    assert lad.kind == "clear" and "'The Glass Orchard' (1999)" in lad.vetoed


def test_a_key_another_film_holds_is_a_collision_naming_it(repo):
    fid = repo.create_film(Film("The Glass Orchard", 1961, None, ""))
    lad = _ladder(repo, _tmdb(), "tt9000009", veto=False)
    assert (lad.kind, lad.reason, lad.holder) == ("blocked", KEY_COLLISION, fid)


def test_a_tombstoned_key_is_refused(repo):
    fid = repo.create_film(Film("The Glass Orchard", 1961, None, ""))
    repo.tombstone_film(fid, DAY, note="hidden by hand")
    lad = _ladder(repo, _tmdb(), "tt9000009")
    assert (lad.kind, lad.reason) == ("blocked", TOMBSTONED_HOLDER)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/unit/test_gate_ladder.py -q`
Expected: `ImportError: cannot import name 'CORPUS_VETO' from 'movie_brain.application.films'`.

- [ ] **Step 3: Implement**

Replace the whole of `src/movie_brain/application/films.py` with:

```python
"""Add one film by its IMDb id — the hand path for a film no source has brought in yet — and
the creating gates every caller shares.

Nothing in `add_by_id` resolves a title: the owner supplies the id, and the id settles WHICH
work is meant. It never settles whether the catalog already holds that work, so `gate_ladder`
decides that (`find_holder` for gates 1/2b, `corpus_veto` for gate 3, the tombstone and
`films.key` checks), exactly as `oldratings create --line --tt` does it. The film is minted
under TMDB's own title and year and is born keyed; a keying failure never undoes the creation,
the next sync retries. Dry run by default, and a dry run writes nothing. No claim row: there is
no ingester here whose title the resolver should later read back.

`gate_ladder` has three callers (spec 2026-10-01 D5/D9): `films add`, the Criterion walk
(`criterion_walk.py`, where a resolver verdict supplies the id) and `review resolve --tt` on a
criterion row (`criterion_review.py`, where the owner does). On a human path gate 3 is passed
`veto=False`: its hits are reported, not a refusal — a human choosing is what gate 3 exists to
summon (Plan B ledger L1).
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date

import requests

from movie_brain.application.lists import (
    KEYED_OK,
    _catalog,
    _film_label,
    _key_new_film,
    _veto_label,
    corpus_veto,
    find_holder,
)
from movie_brain.domain.matching import CandidateIndex, build_candidate_index
from movie_brain.domain.models import Film
from movie_brain.domain.thumbprint import Verdict
from movie_brain.infrastructure.database import Repository
from movie_brain.infrastructure.tmdb import AuthError, TmdbClient

_TT = re.compile(r"tt\d{7,}")

# Review reasons a `blocked` ladder names (the Criterion walk queues them verbatim).
CORPUS_VETO = "corpus-veto"
TOMBSTONED_HOLDER = "tombstoned-holder"
KEY_COLLISION = "key-collision"
NOT_A_FILM = "not-a-film"


class AddError(Exception):
    """A refusal to even try — nothing was asked, nothing was touched."""


@dataclass(frozen=True)
class AddOutcome:
    kind: str  # "created" | "would-create" | "held" | "blocked" | "error"
    detail: str
    film_id: int | None = None

    @property
    def exit_code(self) -> int:
        return 1 if self.kind == "error" else 0


@dataclass(frozen=True)
class Ladder:
    """What the creating gates say about one work.

    `held` — a film already holds it (`holder`); `clear` — every gate passed: mint under
    `title`/`year`, born keyed to `tmdb_id`; `blocked` — a durable refusal, `reason` is the
    review reason; `weather` — a TMDB call failed, so the holder is unknown, not disproved:
    ask again later, never a review row. `vetoed` carries gate 3's hits when `veto=False` let
    them through."""

    kind: str
    detail: str
    reason: str = ""
    holder: int | None = None
    tmdb_id: int | None = None
    title: str = ""
    year: int | None = None
    vetoed: str = ""


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


def gate_ladder(
    repo: Repository,
    tmdb: TmdbClient,
    verdict: Verdict,
    *,
    index: CandidateIndex,
    catalog: dict[int, tuple[str, int | None, str | None]],
    extra_forms: Sequence[str] = (),
    veto: bool = True,
    log: Callable[[str], None] = _stderr,
) -> Ladder:
    """Gates 1/2/2b, then TMDB's own title and year, gate 3, the tombstoned key and the
    `films.key` collision — in that order, writing nothing. `extra_forms` widens gate 3 with the
    caller's own titles for the work (Criterion's printed and original titles)."""
    tt = verdict.tt
    if verdict.kind != "match" or tt is None:
        raise ValueError("the gate ladder starts from a matched IMDb id")
    holder, label = find_holder(repo, tmdb, verdict, log)
    if label == "tmdb lookup failed":
        return Ladder("weather", "gate 2b: tmdb lookup failed — holder unknown")
    if holder is None and label.startswith("tombstoned"):
        return Ladder("blocked", f"tombstoned-holder  {label}", TOMBSTONED_HOLDER)
    if holder is not None:
        return Ladder("held", f"{_film_label(catalog, holder)} already holds {tt}  via {label}", holder=holder)

    try:
        tmdb_id = tmdb.find_by_imdb(tt)
        facts = tmdb.movie_facts(tmdb_id) if tmdb_id is not None else None
    except (requests.RequestException, AuthError) as exc:
        return Ladder("weather", f"tmdb lookup failed for {tt}: {exc}")
    if tmdb_id is None or facts is None:
        return Ladder("blocked", f"TMDB does not know {tt} as a film", NOT_A_FILM)
    film = Film(facts.title, facts.year, None, "")
    wanted = f"{tt} {facts.title!r} ({facts.year or '-'})"
    forms = list(dict.fromkeys(t for t in (facts.title, facts.original_title, *extra_forms) if t))
    hits = corpus_veto(index, forms)
    vetoed = ""
    if hits:
        if veto:
            return Ladder("blocked", f"corpus-veto  {_veto_label(hits)}  wanted {wanted}", CORPUS_VETO)
        vetoed = _veto_label(hits)
    if film.key in repo.tombstoned_keys():
        return Ladder("blocked", f"tombstoned-holder  key {film.key!r} is tombstoned", TOMBSTONED_HOLDER)
    clash = repo.film_id_by_key(film.key)
    if clash is not None:
        clash = repo.canonical_film_id(clash)
        return Ladder(
            "blocked", f"key-collision  {film.key!r} is held by {_film_label(catalog, clash)}", KEY_COLLISION,
            holder=clash,
        )
    return Ladder("clear", wanted, tmdb_id=tmdb_id, title=facts.title, year=facts.year, vetoed=vetoed)


def add_by_id(
    repo: Repository,
    tt: str,
    today: date,
    *,
    tmdb: TmdbClient | None,
    apply: bool = False,
    log: Callable[[str], None] = _stderr,
) -> AddOutcome:
    if not _TT.fullmatch(tt):
        raise AddError(f"{tt!r} is not an IMDb id (tt1234567)")
    if tmdb is None:
        raise AddError("no TMDB client — gate 2b cannot run, so creation would be unguarded")

    film_rows = repo.films_for_matching()
    lad = gate_ladder(
        repo, tmdb, Verdict("match", tt, "id supplied by hand", ()),
        index=build_candidate_index(film_rows), catalog=_catalog(repo, film_rows), log=log,
    )
    if lad.kind == "weather":
        return AddOutcome("error", lad.detail)
    if lad.kind == "held":
        return AddOutcome("held", lad.detail, lad.holder)
    if lad.kind == "blocked":
        return AddOutcome("blocked", lad.detail)
    if not apply:
        return AddOutcome("would-create", lad.detail)

    film = Film(lad.title, lad.year, None, "")
    film_id = repo.create_film(film)
    if film_id is None:  # the key appeared between the gate and the write
        return AddOutcome("blocked", f"key-collision  {film.key!r} appeared during the add")
    status = _key_new_film(repo, tmdb, film_id, tt, lad.tmdb_id, today, log)
    keyed = status if status in KEYED_OK else f"{status} (the next sync retries)"
    return AddOutcome("created", f"#{film_id} {lad.detail}  {keyed}", film_id)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_gate_ladder.py tests/step_defs/test_films.py -q && uv run mypy src/movie_brain/application/films.py`
Expected: all pass; mypy clean for this file.

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/application/films.py tests/unit/test_gate_ladder.py
git commit -m "One creating-gate ladder for films add, the Criterion walk and review resolution, so the three can never disagree about whether we already hold a work

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 3: The walk's value types and its one-transaction write

**Files:**
- Modify: `src/movie_brain/domain/models.py` (append after `BridgeTarget`)
- Modify: `src/movie_brain/infrastructure/database.py` (imports; new methods right after `record_bridge`)
- Test: `tests/unit/test_criterion_walk_repository.py` (create)

**Interfaces:**
- Consumes: `CRITERION_FILM_URL` (Task 1), `Repository._write_listing`, `Repository._canonical_in`, `edition_label`.
- Produces:
  - `domain.models.NewFilm(title: str, year: int | None, director: str | None, tt: str, tmdb_id: int | None)` with `.key`
  - `domain.models.WalkListing(mediaid: str, title: str, year: int | None, film_id: int | None = None, new: int | None = None, bind: bool = False)`
  - `domain.models.CriterionWalk(listings: tuple[WalkListing, ...], created: tuple[NewFilm, ...] = (), reviews: tuple[ReviewEntry, ...] = (), leaving: dict[str, str] | None = None)`
  - `domain.models.WalkWrite(arrived: int, departed: int, created: tuple[tuple[int, NewFilm], ...])`
  - `Repository.criterion_mediaid_holders() -> dict[str, int]` (mediaid → canonical film; old `http…` links excluded)
  - `Repository.criterion_review_values() -> set[str]` (every value a criterion review row names, open or resolved)
  - `Repository.bind_criterion_mediaid(film_id: int, mediaid: str, title: str, year: int | None, seen: date) -> None` (raises `sqlite3.IntegrityError` when another film holds the mediaid)
  - `Repository.create_criterion_film(film: Film, mediaid: str, title: str, year: int | None, seen: date) -> int | None`
  - `Repository.record_criterion_walk(walk: CriterionWalk, seen: date) -> WalkWrite`
  - static `Repository._walk_leaving(c, leaving: dict[str, str] | None, day: str) -> None` (the last step of the write; tests monkeypatch it to inject a late failure)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_criterion_walk_repository.py`:

```python
"""`record_criterion_walk` and its neighbours (spec 2026-10-01 D2, D4, D6, D7, D10). Films are
seeded as the bridge leaves them: holding their mediaid, listed on the last VHX walk (LAST)."""

from __future__ import annotations

import sqlite3
from datetime import date

import pytest

from movie_brain.domain.models import CriterionWalk, Film, NewFilm, ReviewEntry, WalkListing
from movie_brain.infrastructure.database import Repository

LAST = date(2026, 9, 20)  # the last VHX walk: every seeded listing's last_seen, so the frontier
TODAY = date(2026, 10, 3)
SITE = "https://www.criterionchannel.com"
TABLES = ("films", "listings", "external_ids", "claim", "match_review", "availability_transitions", "meta")


def _q(repo, sql, *args):
    conn = sqlite3.connect(repo.db_path)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def _dump(repo):
    return {t: _q(repo, f"SELECT * FROM {t} ORDER BY rowid") for t in TABLES}


def _listed(repo, title, year, mediaids, *, on=LAST, url=None):
    fid = repo.create_film(Film(title, year, None, ""))
    for m in mediaids:
        repo.set_external_id(fid, "criterion", m, on)
    repo.record_listing(fid, "criterion", url or f"{SITE}/films/{mediaids[0]}/x", on)
    return fid


def _label(repo, fid, label):
    conn = sqlite3.connect(repo.db_path)
    conn.execute("UPDATE listings SET leaving_date = ? WHERE film_id = ? AND source = 'criterion'", (label, fid))
    conn.commit()
    conn.close()


def _labels(repo):
    return dict(_q(repo, "SELECT film_id, leaving_date FROM listings WHERE source = 'criterion'"))


def _item(fid, mediaid, title="T", year=None):
    return WalkListing(mediaid, title, year, film_id=fid)


def _walk(*listings, created=(), reviews=(), leaving=None):
    return CriterionWalk(tuple(listings), tuple(created), tuple(reviews), leaving)


def test_one_film_under_two_mediaids_is_one_listing_two_claims_and_no_arrival(repo):
    # Eve's Bayou #1150: theatrical 6tfyfj2f and director's cut gOkSarah, both bound by the bridge.
    fid = _listed(repo, "Eve's Bayou", 1997, ["6tfyfj2f", "gOkSarah"], url=f"{SITE}/films/6tfyfj2f/eves-bayou")
    wrote = repo.record_criterion_walk(
        _walk(_item(fid, "gOkSarah", "EVE’S BAYOU: Director’s Cut", 2022), _item(fid, "6tfyfj2f", "Eve’s Bayou", 1997)),
        TODAY,
    )
    assert (wrote.arrived, wrote.departed) == (0, 0)  # listed on LAST = the frontier: still current
    assert _q(repo, "SELECT url, last_seen FROM listings WHERE film_id = ?", fid) == [
        (f"{SITE}/films/6tfyfj2f/eves-bayou", "2026-10-03")
    ]
    assert sorted(_q(repo, "SELECT value, title_ingested, year_claimed FROM claim WHERE film_id = ?", fid)) == [
        ("6tfyfj2f", "Eve’s Bayou", 1997),
        ("gOkSarah", "EVE’S BAYOU: Director’s Cut", 2022),
    ]
    assert _q(repo, "SELECT COUNT(*) FROM availability_transitions") == [(0,)]


def test_a_listing_older_than_the_frontier_arrives_again(repo):
    old = _listed(repo, "Old Friend", 1960, ["OldFrnd1"], on=date(2026, 9, 1))  # departed before LAST
    cur = _listed(repo, "Current", 1970, ["Current1"])
    wrote = repo.record_criterion_walk(_walk(_item(old, "OldFrnd1"), _item(cur, "Current1")), TODAY)
    assert (wrote.arrived, wrote.departed) == (1, 0)
    assert _q(repo, "SELECT film_id, source, appeared_on FROM availability_transitions") == [
        (old, "criterion", "2026-10-03")
    ]


def test_a_new_film_is_born_holding_its_mediaid_its_claim_and_the_bare_link(repo):
    nf = NewFilm("Two or Three Things I Know About Her", 1967, "Jean-Luc Godard", "tt9000304", 8072)
    wrote = repo.record_criterion_walk(
        _walk(WalkListing("L5Z3RaiC", "2 or 3 Things I Know About Her", 1967, new=0, bind=True), created=(nf,)),
        TODAY,
    )
    ((fid, made),) = wrote.created
    assert made == nf and wrote.arrived == 1  # no listing before: an insert is an arrival
    assert _q(repo, "SELECT title, year, director FROM films WHERE id = ?", fid) == [
        ("Two or Three Things I Know About Her", 1967, "Jean-Luc Godard")
    ]
    assert ("criterion", "L5Z3RaiC") in repo.external_ids_all(fid)
    assert _q(repo, "SELECT film_id, title_ingested, year_claimed FROM claim WHERE value = 'L5Z3RaiC'") == [
        (fid, "2 or 3 Things I Know About Her", 1967)
    ]
    assert _q(repo, "SELECT url FROM listings WHERE film_id = ?", fid) == [(f"{SITE}/films/L5Z3RaiC",)]


def test_departures_are_current_listings_left_unstamped_and_a_same_day_walk_moves_nothing(repo):
    nadja = _listed(repo, "Nadja", 1994, ["7xCZH5br"])
    gone = _listed(repo, "Some Came Running", 1958, ["SmCmRn58"])
    first = repo.record_criterion_walk(_walk(_item(nadja, "7xCZH5br")), TODAY)
    assert (first.arrived, first.departed) == (0, 1)
    assert _q(repo, "SELECT last_seen FROM listings WHERE film_id = ?", gone) == [("2026-09-20",)]
    again = repo.record_criterion_walk(_walk(_item(nadja, "7xCZH5br")), TODAY)
    assert (again.arrived, again.departed) == (0, 0)  # Review Focus 2: currency is date-grained
    assert _q(repo, "SELECT COUNT(*) FROM films WHERE id = ?", gone) == [(1,)]  # departed is display, not delete


def test_leaving_labels_are_keyed_by_mediaid_and_replace_old_ones(repo):
    z = _listed(repo, "Zabriskie Point", 1970, ["Tg73fdO2"])
    n = _listed(repo, "Nadja", 1994, ["7xCZH5br"])
    _label(repo, n, "September 30")
    leaving = {"Tg73fdO2": "October 31", "NoOne001": "October 31"}  # Review Focus 4: nobody holds NoOne001
    repo.record_criterion_walk(_walk(_item(z, "Tg73fdO2"), _item(n, "7xCZH5br"), leaving=leaving), TODAY)
    assert _labels(repo) == {z: "October 31", n: None}


def test_unreadable_leaving_pages_keep_listed_labels_and_clear_departed_ones(repo):
    z = _listed(repo, "Zabriskie Point", 1970, ["Tg73fdO2"])
    s = _listed(repo, "Some Came Running", 1958, ["SmCmRn58"])
    _label(repo, z, "October 31")
    _label(repo, s, "September 30")
    repo.record_criterion_walk(_walk(_item(z, "Tg73fdO2"), leaving=None), TODAY)
    assert _labels(repo) == {z: "October 31", s: None}  # story 11: a film that left loses its label tonight


@pytest.mark.parametrize("stored", [f"{SITE}/nadja", f"{SITE}/films/Other001/nadja"])
def test_a_link_not_on_tonights_mediaid_becomes_the_bare_film_page(repo, stored):
    fid = _listed(repo, "Nadja", 1994, ["7xCZH5br"], url=stored)
    repo.record_criterion_walk(_walk(_item(fid, "7xCZH5br")), TODAY)
    assert _q(repo, "SELECT url FROM listings WHERE film_id = ?", fid) == [(f"{SITE}/films/7xCZH5br",)]


def test_review_rows_and_the_fetch_stamp_land_in_the_same_write(repo):
    repo.record_criterion_walk(_walk(reviews=(ReviewEntry("no-record", None, "Gh0stEnt", "{}"),)), TODAY)
    assert [(r["reason"], r["film_id"], r["value"]) for r in repo.open_reviews("criterion")] == [
        ("no-record", None, "Gh0stEnt")
    ]
    assert repo.criterion_review_values() == {"Gh0stEnt"}
    assert repo.get_meta("films_fetched_at") == "2026-10-03"


def test_a_failure_late_in_the_write_rolls_everything_back(repo, monkeypatch):
    fid = _listed(repo, "Nadja", 1994, ["7xCZH5br"])
    before = _dump(repo)

    def boom(c, leaving, day):
        raise RuntimeError("disk full")

    monkeypatch.setattr(Repository, "_walk_leaving", staticmethod(boom))
    walk = _walk(
        _item(fid, "7xCZH5br", "Nadja", 1995),
        WalkListing("L5Z3RaiC", "2 or 3 Things I Know About Her", 1967, new=0, bind=True),
        created=(NewFilm("Two or Three Things I Know About Her", 1967, None, "tt9000304", 8072),),
        reviews=(ReviewEntry("no-record", None, "Gh0stEnt", "{}"),),
    )
    with pytest.raises(RuntimeError, match="disk full"):
        repo.record_criterion_walk(walk, TODAY)
    assert _dump(repo) == before


def test_holders_are_canonical_and_ignore_old_links(repo):
    # Review Focus 3: a mediaid left on a merged-away film is listed on its survivor.
    survivor = repo.create_film(Film("Mirror", 1975, None, ""))
    loser = repo.create_film(Film("Zerkalo", 1975, None, ""))
    repo.set_external_id(loser, "criterion", "Mirr0r75", LAST)
    repo.set_external_id(loser, "criterion", f"{SITE}/mirror", LAST)
    conn = sqlite3.connect(repo.db_path)
    conn.execute(
        "INSERT INTO film_disposition (film_id, kind, survivor_id, note, created_at) "
        "VALUES (?, 'merged', ?, 'test', '2026-10-01')",
        (loser, survivor),
    )
    conn.commit()
    conn.close()
    assert repo.criterion_mediaid_holders() == {"Mirr0r75": survivor}


def test_binding_and_creating_by_hand_respect_the_one_holder_rule(repo):
    _listed(repo, "Nadja", 1994, ["7xCZH5br"])
    other = repo.create_film(Film("Nadja Twin", 1994, None, ""))
    with pytest.raises(sqlite3.IntegrityError):
        repo.bind_criterion_mediaid(other, "7xCZH5br", "Nadja", 1995, TODAY)
    new = repo.create_criterion_film(
        Film("K-ON! The Movie", 2011, "Naoko Yamada", ""), "VBLiQBrA", "K-ON! The Movie", 2011, TODAY
    )
    assert new is not None and ("criterion", "VBLiQBrA") in repo.external_ids_all(new)
    assert repo.create_criterion_film(Film("K-ON! The Movie", 2011, None, ""), "Other001", "x", 2011, TODAY) is None
    assert repo.film_id_for_external("criterion", "Other001") is None  # a refused create writes nothing
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/unit/test_criterion_walk_repository.py -q`
Expected: `ImportError: cannot import name 'CriterionWalk' from 'movie_brain.domain.models'`.

- [ ] **Step 3: Implement the value types**

Append to `src/movie_brain/domain/models.py`, right after the `BridgeTarget` class:

```python
@dataclass(frozen=True)
class NewFilm:
    """A film the Criterion walk will create (spec D5): TMDB's title and year, Criterion's
    director, the resolver's IMDb id and TMDB id to key it with once it exists."""

    title: str
    year: int | None
    director: str | None
    tt: str
    tmdb_id: int | None

    @property
    def key(self) -> str:
        return film_key(self.title, self.year)


@dataclass(frozen=True)
class WalkListing:
    """One catalog item the walk lists, with what Criterion printed for it (the claim). `film_id`
    is the canonical film the mediaid names, or None when the item names `created[new]`. `bind`:
    this walk gives that film the mediaid (it was unknown this morning)."""

    mediaid: str
    title: str
    year: int | None
    film_id: int | None = None
    new: int | None = None
    bind: bool = False


@dataclass(frozen=True)
class CriterionWalk:
    """Everything one walk will write, staged with no writes (spec D6). `leaving` None = the
    leaving pages could not be read tonight: keep the last-known labels (D7)."""

    listings: tuple[WalkListing, ...]
    created: tuple[NewFilm, ...] = ()
    reviews: tuple[ReviewEntry, ...] = ()
    leaving: dict[str, str] | None = None


@dataclass(frozen=True)
class WalkWrite:
    arrived: int
    departed: int
    created: tuple[tuple[int, NewFilm], ...]  # (new film id, what it was staged as) — for keying
```

- [ ] **Step 4: Implement the repository methods**

In `src/movie_brain/infrastructure/database.py`:

Add `from urllib.parse import urlparse` to the stdlib imports, add `CriterionWalk`, `NewFilm` and `WalkWrite` to the `from movie_brain.domain.models import (...)` list, and add after the `from movie_brain.infrastructure.cheapcharts import product_url` line:

```python
from movie_brain.infrastructure.criterion_site import CRITERION_FILM_URL
```

Insert right after the `record_bridge` method:

```python
    # the Criterion walk (spec 2026-10-01 D2, D4, D6, D7, D10) ---------------------------
    def criterion_mediaid_holders(self) -> dict[str, int]:
        """mediaid → the CANONICAL film holding it. Old `http…` links are not mediaids. Every
        film is read, disposed included — the UNIQUE guard is blind to dispositions — and a
        merged-away holder answers as its survivor, so the walk lists the live identity."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT film_id, value FROM external_ids WHERE authority = 'criterion' AND value NOT LIKE 'http%'"
            ).fetchall()
            return {str(r["value"]): self._canonical_in(c, int(r["film_id"])) for r in rows}

    def criterion_review_values(self) -> set[str]:
        """Every value a criterion review row names, open or resolved: an unknown mediaid in this
        set is a human's (open = waiting for him, resolved = a standing decision), so the walk
        never asks JW about it again (D5)."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT DISTINCT value FROM match_review WHERE authority = 'criterion' AND value IS NOT NULL"
            ).fetchall()
            return {str(r["value"]) for r in rows}

    @staticmethod
    def _criterion_id(c: sqlite3.Connection, film_id: int, mediaid: str, day: str) -> None:
        # Claim authority (migration 012): several per film are legal; UNIQUE(authority, value)
        # still raises when ANOTHER film holds the mediaid.
        c.execute(
            "INSERT INTO external_ids (film_id, authority, value, first_seen) VALUES (?, 'criterion', ?, ?) "
            "ON CONFLICT(film_id, authority, value) DO NOTHING",
            (film_id, mediaid, day),
        )

    @staticmethod
    def _criterion_claim(
        c: sqlite3.Connection, film_id: int, mediaid: str, title: str, year: int | None, day: str
    ) -> None:
        # D4: what Criterion printed goes in the claim, never on the film; INSERT OR IGNORE keeps
        # the FIRST title and year seen for a mediaid.
        c.execute(
            "INSERT OR IGNORE INTO claim (film_id, authority, value, title_ingested, year_claimed, "
            "edition_label, first_seen) VALUES (?, 'criterion', ?, ?, ?, ?, ?)",
            (film_id, mediaid, title, year, edition_label(title), day),
        )

    def bind_criterion_mediaid(self, film_id: int, mediaid: str, title: str, year: int | None, seen: date) -> None:
        """`review resolve` on a criterion row: the mediaid and Criterion's claim on one film,
        together. Raises IntegrityError when another film holds the mediaid."""
        day = seen.isoformat()
        with self._conn() as c:
            self._criterion_id(c, film_id, mediaid, day)
            self._criterion_claim(c, film_id, mediaid, title, year, day)

    def create_criterion_film(self, film: Film, mediaid: str, title: str, year: int | None, seen: date) -> int | None:
        """`review resolve --create/--tt` on a criterion row: a new film born holding its mediaid
        and Criterion's claim, in ONE transaction. None on a `films.key` collision — nothing written."""
        day = seen.isoformat()
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO films (guid, title, year, director, key) VALUES (?, ?, ?, ?, ?) ON CONFLICT(key) DO NOTHING",
                (str(uuid.uuid4()), film.title, film.year, film.director, film.key),
            )
            if cur.rowcount == 0:
                return None
            film_id = int(c.execute("SELECT id FROM films WHERE key = ?", (film.key,)).fetchone()["id"])
            self._criterion_id(c, film_id, mediaid, day)
            self._criterion_claim(c, film_id, mediaid, title, year, day)
            return film_id

    @staticmethod
    def _criterion_listing_url(c: sqlite3.Connection, film_id: int, mediaids: list[str]) -> str:
        """D10: keep a stored link already on one of tonight's mediaids (the bridge's slugged
        `/films/<id>/<slug>`); otherwise the bare `/films/<id>`, which the site forwards."""
        row = c.execute("SELECT url FROM listings WHERE film_id = ? AND source = 'criterion'", (film_id,)).fetchone()
        if row is not None:
            path = urlparse(str(row["url"])).path
            if any(path == f"/films/{m}" or path.startswith(f"/films/{m}/") for m in mediaids):
                return str(row["url"])
        return CRITERION_FILM_URL.format(mediaids[0])

    @staticmethod
    def _walk_leaving(c: sqlite3.Connection, leaving: dict[str, str] | None, day: str) -> None:
        """D7, the write's last step. A listing this walk did not stamp never keeps a Leaving
        label. With labels in hand they replace the old ones, keyed by mediaid; None (the
        leaving pages failed tonight) keeps the labels of the films still listed."""
        c.execute("UPDATE listings SET leaving_date = NULL WHERE source = 'criterion' AND last_seen < ?", (day,))
        if leaving is None:
            return
        c.execute("UPDATE listings SET leaving_date = NULL WHERE source = 'criterion'")
        for mediaid, label in leaving.items():
            c.execute(
                "UPDATE listings SET leaving_date = ? WHERE source = 'criterion' AND last_seen = ? "
                "AND film_id IN (SELECT film_id FROM external_ids WHERE authority = 'criterion' AND value = ?)",
                (label, day, mediaid),
            )

    def record_criterion_walk(self, walk: CriterionWalk, seen: date) -> WalkWrite:
        """The walk's whole write in ONE transaction (spec D6): new films, mediaids, claims,
        listings against the pre-batch currency frontier, review rows, leaving labels and
        `films_fetched_at`. Any failure rolls every row back: Criterion is then exactly as it was.

        A film listed under two mediaids tonight (Eve's Bayou: theatrical and director's cut)
        gets ONE listing — listings are per film × source — and both claims; its listing is
        written once, so the second item can never count as an arrival."""
        day = seen.isoformat()
        with self._conn() as c:
            row = c.execute("SELECT MAX(last_seen) AS m FROM listings WHERE source = 'criterion'").fetchone()
            frontier = None if row["m"] is None else str(row["m"])
            new_ids: list[int] = []
            for nf in walk.created:
                cur = c.execute(
                    "INSERT INTO films (guid, title, year, director, key) VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(key) DO NOTHING",
                    (str(uuid.uuid4()), nf.title, nf.year, nf.director, nf.key),
                )
                if cur.rowcount == 0:  # staging checked the key; only a concurrent writer gets here
                    raise sqlite3.IntegrityError(f"films.key {nf.key!r} was taken during the walk")
                new_ids.append(int(c.execute("SELECT id FROM films WHERE key = ?", (nf.key,)).fetchone()["id"]))
            mediaids: dict[int, list[str]] = {}
            for wl in walk.listings:
                film_id = new_ids[wl.new] if wl.new is not None else wl.film_id
                if film_id is None:
                    raise ValueError(f"walk listing {wl.mediaid} names no film")
                if wl.bind:
                    self._criterion_id(c, film_id, wl.mediaid, day)
                self._criterion_claim(c, film_id, wl.mediaid, wl.title, wl.year, day)
                mediaids.setdefault(film_id, []).append(wl.mediaid)
            arrived = 0
            for film_id, ids in mediaids.items():
                url = self._criterion_listing_url(c, film_id, ids)
                if self._write_listing(c, film_id, "criterion", url, day, frontier):
                    arrived += 1
            for e in walk.reviews:
                c.execute(
                    "INSERT INTO match_review (authority, film_id, value, reason, detail, created_at) "
                    "VALUES ('criterion', ?, ?, ?, ?, ?)",
                    (e.film_id, e.value, e.reason, e.detail, day),
                )
            departed = 0
            if frontier is not None and frontier < day:
                departed = int(
                    c.execute(
                        "SELECT COUNT(*) AS n FROM listings WHERE source = 'criterion' AND last_seen = ?", (frontier,)
                    ).fetchone()["n"]
                )
            c.execute(
                "INSERT INTO meta (key, value) VALUES ('films_fetched_at', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (day,),
            )
            self._walk_leaving(c, walk.leaving, day)
        return WalkWrite(arrived, departed, tuple(zip(new_ids, walk.created, strict=True)))
```

Note: `_walk_leaving` is deliberately the LAST statement inside the `with`, so a test that makes it raise proves every earlier statement rolls back.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_criterion_walk_repository.py tests/unit/test_database.py -q && uv run mypy src/movie_brain/infrastructure/database.py src/movie_brain/domain/models.py`
Expected: all pass; no new mypy errors.

- [ ] **Step 6: Commit**

```bash
git add src/movie_brain/domain/models.py src/movie_brain/infrastructure/database.py tests/unit/test_criterion_walk_repository.py
git commit -m "The Criterion walk writes in one transaction, one listing per film however many ids it holds — so a broken night changes nothing and Eve's Bayou never twins or arrives falsely

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: `walk_criterion` — staging, reservations, the review envelope

**Files:**
- Create: `src/movie_brain/application/criterion_walk.py`
- Create: `tests/criterion_fakes.py`
- Create: `tests/features/criterion_walk.feature`, `tests/step_defs/test_criterion_walk.py`

**Interfaces:**
- Consumes: `HttpCriterionSite`'s three methods' shapes (Task 1), `gate_ladder` + reason constants (Task 2), `CriterionWalk`/`WalkListing`/`NewFilm` + `record_criterion_walk`/`criterion_mediaid_holders`/`criterion_review_values` (Task 3), `lists._catalog`, `lists._key_new_film`, `lists.corpus_veto`, `thumbprint.review_detail`.
- Produces (in `application/criterion_walk.py`):
  - `AUTHORITY = "criterion"`, `NO_MATCH = "no-match"`, `NO_RECORD = "no-record"`
  - `class CriterionSite(Protocol)`: `catalog() -> list[CatalogItem]`, `media(mediaid: str) -> JwMedia | None`, `leaving() -> Leaving`
  - `@dataclass(frozen=True) class WalkReport: arrived: int = 0; departed: int = 0; reviews: int = 0; created: int = 0; skipped: int = 0; waiting: int = 0`
  - `def walk_criterion(repo: Repository, site: CriterionSite, fetcher: CandidateFetcher | None, tmdb: TmdbClient | None, today: date, *, log: Callable[[str], None] = _stderr) -> WalkReport` — raises on any failure before or inside the write (the caller catches)
  - `def criterion_detail(item: CatalogItem, media: JwMedia | None, *, reason: str, verdict: Verdict | None = None, query: Query | None = None, tt: str | None = None, refused: str | None = None) -> str`
  - `def parse_criterion_detail(detail: str | None) -> dict[str, Any] | None` — the `criterion` block of a row's detail (keys `mediaid`, `title`, `year`, `duration_s`, and when JW answered `director` (list), `title_original`, `criterion_id`; `tt` when the resolver matched; `refused` when a gate refused)
- Produces (in `tests/criterion_fakes.py`): `FakeSite` (attributes `items`, `media_by_id`, `media_fails`, `leaving_labels` — `None` makes `leaving()` raise —, `catalog_fails`, `calls`; property `media_calls`), `captured_media()`, `media_like(mediaid, title, directors=(), title_original=None)`, `mediaid_for(title)`, `seed_known(repo, films, seen) -> list[CatalogItem]`

- [ ] **Step 1: Write the test fakes**

Create `tests/criterion_fakes.py`:

```python
"""Injected fakes for the Criterion walk tests (spec 2026-10-01 §5).

`FakeSite` stands where `HttpCriterionSite` stands in `sync()`. Its JW records are the real
captured answer (`tests/fixtures/criterion/jw-media.L5Z3RaiC.json`) with named fields changed,
parsed by the real `parse_media` — no record shape is invented here. Catalog items are the
adapter's own `CatalogItem`, the shape `fetch_catalog` returns."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Iterable
from datetime import date
from pathlib import Path

from movie_brain.domain.models import Film
from movie_brain.infrastructure.criterion_site import CatalogItem, CriterionError, JwMedia, Leaving, parse_media

FIX = Path(__file__).parent / "fixtures" / "criterion"
_CAPTURE = json.loads((FIX / "jw-media.L5Z3RaiC.json").read_text())


def captured_media() -> JwMedia:
    """The 2 or 3 Things I Know About Her record exactly as JW answered on 2026-10-01."""
    return parse_media(copy.deepcopy(_CAPTURE), "L5Z3RaiC")


def media_like(mediaid: str, title: str, directors: Iterable[str] = (), title_original: str | None = None) -> JwMedia:
    body = copy.deepcopy(_CAPTURE)
    body["playlist"][0].update(
        {
            "mediaid": mediaid,
            "title": title,
            "title_original": title_original or title,
            "director": json.dumps(list(directors)),  # JW stores the list as a JSON string
        }
    )
    return parse_media(body, mediaid)


def mediaid_for(title: str) -> str:
    """A stable 8-character mediaid for a test film the spec does not name."""
    return hashlib.sha1(title.encode()).hexdigest()[:8]


def seed_known(repo, films: Iterable[Film], seen: date) -> list[CatalogItem]:
    """Films as `criterion bridge --apply` leaves them — each holding its mediaid — and the
    catalog items that list them, so a walk treats every one as KNOWN."""
    items = []
    for f in films:
        fid = repo.upsert_film(f)
        m = mediaid_for(f.title)
        repo.set_external_id(fid, "criterion", m, seen)
        items.append(CatalogItem(m, f.title, f.year, 5400))
    return items


class FakeSite:
    def __init__(self) -> None:
        self.items: list[CatalogItem] = []
        self.media_by_id: dict[str, JwMedia] = {}  # a mediaid not here answers like JW's 404
        self.media_fails: set[str] = set()
        self.leaving_labels: dict[str, str] | None = {}  # None: the leaving pages cannot be read
        self.catalog_fails = False
        self.calls: list[str] = []

    def catalog(self) -> list[CatalogItem]:
        self.calls.append("catalog")
        if self.catalog_fails:
            raise CriterionError("catalog: HTTP 500")
        return list(self.items)

    def media(self, mediaid: str) -> JwMedia | None:
        self.calls.append(f"media:{mediaid}")
        if mediaid in self.media_fails:
            raise CriterionError(f"jw media {mediaid}: HTTP 503")
        return self.media_by_id.get(mediaid)

    def leaving(self) -> Leaving:
        self.calls.append("leaving")
        if self.leaving_labels is None:
            raise CriterionError("home page: HTTP 500")
        return Leaving(dict(self.leaving_labels), ())

    @property
    def media_calls(self) -> list[str]:
        return [c.removeprefix("media:") for c in self.calls if c.startswith("media:")]
```

- [ ] **Step 2: Write the failing scenarios**

Create `tests/features/criterion_walk.feature`. Fixture arithmetic is in the comments: every seeded listing is dated 2026-09-20 (the last VHX walk, so the currency frontier) and the walk runs on 2026-10-03; a film with no Criterion listing before the walk counts as an arrival when listed.

```gherkin
Feature: The Criterion walk — a catalog item IS the film holding its mediaid (spec 2026-10-01 D2, D4–D7, D10)
  Only a mediaid no film holds is asked about: JW Player, the thumbprint resolver, then the
  gates `films add` runs. Everything is written in one transaction, or nothing is.

  Scenario: A film Criterion re-dated stays my film (Nadja #3057, story 3)
    # listed on the frontier and re-stamped: not an arrival, nothing departs
    Given the last walk listed "Nadja" (1994) as "7xCZH5br"
    And the film "Nadja" is rated 5
    And Criterion lists "Nadja" (1995) as "7xCZH5br"
    When the walk runs
    Then the walk reports arrived 0, left 0, to review 0
    And there is 1 film titled "Nadja"
    And the film "Nadja" has year 1994 and rating 5
    And the film "Nadja" is current on Criterion
    And the film "Nadja" has a criterion claim "7xCZH5br" titled "Nadja" for 1995
    And JW Player was asked 0 times in all

  Scenario: A film I hold that Criterion just added joins it (Barry Lyndon #3433, story 4)
    # no Criterion listing before → one arrival; gate 1 finds the holder, so TMDB is never asked
    Given a film "Barry Lyndon" (1975) holding imdb "tt9000433"
    And Criterion lists "Barry Lyndon" (1975) as "aAUEybAm"
    And JW knows "aAUEybAm" as "Barry Lyndon" directed by "Stanley Kubrick"
    And the resolver matches "Barry Lyndon" to "tt9000433" (tmdb 9433) directed by "Stanley Kubrick"
    When the walk runs
    Then the walk reports arrived 1, left 0, to review 0
    And no film was created
    And there is 1 film titled "Barry Lyndon"
    And the film "Barry Lyndon" holds criterion id "aAUEybAm"
    And the film "Barry Lyndon" arrived on Criterion today

  Scenario: A film new to Criterion and to me is born holding its mediaid, under TMDB's title
    Given Criterion lists "2 or 3 Things I Know About Her" (1967) as "L5Z3RaiC"
    And JW knows "L5Z3RaiC" as captured
    And the resolver matches "2 or 3 Things I Know About Her" to "tt9000304" (tmdb 8072) directed by "Jean-Luc Godard"
    And TMDB knows "tt9000304" as film 8072 "Two or Three Things I Know About Her" (1967)
    When the walk runs
    Then the walk reports arrived 1, left 0, to review 0
    And the walk created 1 film
    And the film "Two or Three Things I Know About Her" holds criterion id "L5Z3RaiC"
    And the film "Two or Three Things I Know About Her" has year 1967 and director "Jean-Luc Godard"
    And the film "Two or Three Things I Know About Her" holds imdb "tt9000304"
    And the film "Two or Three Things I Know About Her" has a criterion claim "L5Z3RaiC" titled "2 or 3 Things I Know About Her" for 1967
    And the film "Two or Three Things I Know About Her" is listed at "https://www.criterionchannel.com/films/L5Z3RaiC"

  Scenario: A film the resolver cannot place waits for me as one review row (story 7)
    Given Criterion lists "K-ON! The Movie" (2011) as "VBLiQBrA"
    And JW knows "VBLiQBrA" as "K-ON! The Movie" directed by "Naoko Yamada"
    And the resolver finds nothing for "K-ON! The Movie"
    When the walk runs
    Then the walk reports arrived 0, left 0, to review 1
    And no film was created
    And there is 1 open criterion "no-match" review for "VBLiQBrA"
    And that review shows Criterion's title "K-ON! The Movie", year 2011 and director "Naoko Yamada"

  Scenario: Two mediaids the resolver cannot tell apart are two rows; a rerun adds none and asks nothing
    Given Criterion lists "Dr. Dolittle" (1923) as "YM0kT8PG"
    And Criterion lists "Dr. Dolittle" (1923) as "BgC4kIqZ"
    And JW knows "YM0kT8PG" as "Dr. Dolittle" directed by "Lotte Reiniger"
    And JW knows "BgC4kIqZ" as "Dr. Dolittle" directed by "Lotte Reiniger"
    And the resolver finds two works named "Dr. Dolittle" (1923)
    When the walk runs
    And the walk runs again the next day
    Then there is 1 open criterion "no-match" review for "YM0kT8PG"
    And there is 1 open criterion "no-match" review for "BgC4kIqZ"
    And JW Player was asked 2 times in all

  Scenario: Two mediaids naming one work become ONE new film holding both (The Beast 2023)
    # the second item joins the film the first one reserved: one creation, one listing, one arrival
    Given Criterion lists "The Beast" (2023) as "1n2wLfer"
    And Criterion lists "The Beast" (2023) as "7G9Sr5tL"
    And JW knows "1n2wLfer" as "The Beast" directed by "Bertrand Bonello"
    And JW knows "7G9Sr5tL" as "The Beast" directed by "Bertrand Bonello"
    And the resolver matches "The Beast" to "tt9000301" (tmdb 9301) directed by "Bertrand Bonello"
    And TMDB knows "tt9000301" as film 9301 "The Beast" (2023)
    When the walk runs
    Then the walk reports arrived 1, left 0, to review 0
    And the walk created 1 film
    And the film "The Beast" holds criterion ids "1n2wLfer" and "7G9Sr5tL"
    And the film "The Beast" has 1 Criterion listing

  Scenario: Eve's Bayou — one film holding two listed mediaids is ONE listing, never a twin or a false arrival
    Given the last walk listed "Eve's Bayou" (1997) as "6tfyfj2f"
    And the film "Eve's Bayou" also holds criterion id "gOkSarah"
    And Criterion lists "Eve’s Bayou" (1997) as "6tfyfj2f"
    And Criterion lists "EVE’S BAYOU: Director’s Cut" (2022) as "gOkSarah"
    When the walk runs
    Then the walk reports arrived 0, left 0, to review 0
    And there is 1 film titled "Eve's Bayou"
    And the film "Eve's Bayou" has 1 Criterion listing
    And the film "Eve's Bayou" has 2 criterion claims
    And no film arrived on Criterion today

  Scenario: A second mediaid that resolves to a film already listed joins it without an arrival
    # the director's cut is unknown; the resolver names Eve's Bayou's own IMDb id (director corroborates
    # across the 1997/2022 years), gate 1 finds the holder, and the film keeps its one listing
    Given the last walk listed "Eve's Bayou" (1997) as "6tfyfj2f"
    And the film "Eve's Bayou" also holds imdb "tt9000150"
    And Criterion lists "Eve’s Bayou" (1997) as "6tfyfj2f"
    And Criterion lists "EVE’S BAYOU: Director’s Cut" (2022) as "gOkSarah"
    And JW knows "gOkSarah" as "EVE’S BAYOU: Director’s Cut" directed by "Kasi Lemmons"
    And the resolver matches "EVE’S BAYOU: Director’s Cut" to "tt9000150" (tmdb 9150) directed by "Kasi Lemmons"
    When the walk runs
    Then the walk reports arrived 0, left 0, to review 0
    And there is 1 film titled "Eve's Bayou"
    And the film "Eve's Bayou" holds criterion ids "6tfyfj2f" and "gOkSarah"
    And the film "Eve's Bayou" has 1 Criterion listing
    And no film arrived on Criterion today

  Scenario: A film that left is departed, kept, and loses its Leaving label (Some Came Running #33, stories 5 and 11)
    Given the last walk listed "Some Came Running" (1958) as "SmCmRn58"
    And the last walk listed "Nadja" (1994) as "7xCZH5br"
    And the film "Some Came Running" is on the watchlist
    And the film "Some Came Running" is leaving "September 30"
    And Criterion lists "Nadja" (1994) as "7xCZH5br"
    When the walk runs
    Then the walk reports arrived 0, left 1, to review 0
    And the film "Some Came Running" is not current on Criterion
    And the film "Some Came Running" is not leaving
    And the film "Some Came Running" is still on the watchlist

  Scenario: The dated leaving page relabels the films it names (story 6)
    Given the last walk listed "Zabriskie Point" (1970) as "Tg73fdO2"
    And the last walk listed "Nadja" (1994) as "7xCZH5br"
    And the film "Nadja" is leaving "September 30"
    And Criterion lists "Zabriskie Point" (1970) as "Tg73fdO2"
    And Criterion lists "Nadja" (1994) as "7xCZH5br"
    And the leaving page lists "Tg73fdO2" for "October 31"
    When the walk runs
    Then the film "Zabriskie Point" is leaving "October 31"
    And the film "Nadja" is not leaving

  Scenario: Leaving pages that cannot be read keep the labels of the films still listed
    Given the last walk listed "Zabriskie Point" (1970) as "Tg73fdO2"
    And the last walk listed "Some Came Running" (1958) as "SmCmRn58"
    And the film "Zabriskie Point" is leaving "October 31"
    And the film "Some Came Running" is leaving "September 30"
    And Criterion lists "Zabriskie Point" (1970) as "Tg73fdO2"
    And the leaving pages cannot be read
    When the walk runs
    Then the film "Zabriskie Point" is leaving "October 31"
    And the film "Some Came Running" is not leaving

  Scenario: A JW Player "no such id" is one review row and the walk carries on
    Given the last walk listed "Nadja" (1994) as "7xCZH5br"
    And Criterion lists "Nadja" (1994) as "7xCZH5br"
    And Criterion lists "Ghost Entry" (2020) as "Gh0stEnt"
    When the walk runs
    Then the walk reports arrived 0, left 0, to review 1
    And there is 1 open criterion "no-record" review for "Gh0stEnt"
    And the film "Nadja" is current on Criterion

  Scenario: A JW Player failure fails the walk and writes nothing (story 8)
    Given the last walk listed "Nadja" (1994) as "7xCZH5br"
    And Criterion lists "Nadja" (1995) as "7xCZH5br"
    And Criterion lists "Ghost Entry" (2020) as "Gh0stEnt"
    And JW fails for "Gh0stEnt"
    When the walk runs and fails
    Then Criterion is exactly as it was before the walk

  Scenario: A failure late in the write leaves Criterion exactly as it was
    Given the last walk listed "Nadja" (1994) as "7xCZH5br"
    And Criterion lists "Nadja" (1995) as "7xCZH5br"
    And Criterion lists "Ghost Entry" (2020) as "Gh0stEnt"
    And the walk's write fails at its last step
    When the walk runs and fails
    Then Criterion is exactly as it was before the walk

  Scenario: A mediaid the owner dismissed is never asked about again
    Given Criterion lists "Ghost Entry" (2020) as "Gh0stEnt"
    When the walk runs
    And the owner dismisses the criterion review for "Gh0stEnt"
    And the walk runs again the next day
    Then JW Player was asked 1 time in all
    And there is no open criterion review for "Gh0stEnt"

  Scenario: A held mediaid is listed on its holder whatever review rows mention it
    Given the last walk listed "Test Pattern" (2019) as "gpRRkq27"
    And a film "Test Pattern Twin" (2019) holding no ids
    And an open criterion "id-conflict" review names "gpRRkq27" for "Test Pattern Twin"
    And Criterion lists "Test Pattern" (2021) as "gpRRkq27"
    When the walk runs
    Then the film "Test Pattern" is current on Criterion
    And JW Player was asked 0 times in all

  Scenario: A resolver lookup that fails is weather — no review row, and the next walk resolves it
    Given Criterion lists "2 or 3 Things I Know About Her" (1967) as "L5Z3RaiC"
    And JW knows "L5Z3RaiC" as captured
    And the resolver matches "2 or 3 Things I Know About Her" to "tt9000304" (tmdb 8072) directed by "Jean-Luc Godard"
    And TMDB knows "tt9000304" as film 8072 "Two or Three Things I Know About Her" (1967)
    And the resolver is offline for "2 or 3 Things I Know About Her"
    When the walk runs
    Then the walk reports arrived 0, left 0, to review 0
    And the walk did not ask about 1 film tonight
    And no film was created
    When the resolver comes back
    And the walk runs again the next day
    Then the walk created 1 film

  Scenario: Without a resolver, new films wait unasked and known films still refresh
    Given the last walk listed "Nadja" (1994) as "7xCZH5br"
    And Criterion lists "Nadja" (1994) as "7xCZH5br"
    And Criterion lists "2 or 3 Things I Know About Her" (1967) as "L5Z3RaiC"
    And JW knows "L5Z3RaiC" as captured
    When the walk runs without a TMDB token
    Then the walk reports arrived 0, left 0, to review 0
    And the walk did not ask about 1 film tonight
    And JW Player was asked 0 times in all
    And the film "Nadja" is current on Criterion

  Scenario: A film I hold under no ids is reachable only by a human (K-ON! #142)
    Given a film "K-ON! The Movie" (2011) holding no ids
    And Criterion lists "K-ON! The Movie" (2011) as "VBLiQBrA"
    And JW knows "VBLiQBrA" as "K-ON! The Movie" directed by "Naoko Yamada"
    And the resolver matches "K-ON! The Movie" to "tt9000142" (tmdb 9142) directed by "Naoko Yamada"
    And TMDB knows "tt9000142" as film 9142 "K-ON! The Movie" (2011)
    When the walk runs
    Then the walk reports arrived 0, left 0, to review 1
    And no film was created
    And there is 1 open criterion "corpus-veto" review for "VBLiQBrA"
    And the film "K-ON! The Movie" holds no criterion id

  Scenario: Two new works whose titles collide — the first is created, the second waits (ledger L5)
    Given Criterion lists "Le Trou" (1960) as "LeTrou60"
    And Criterion lists "The Hole" (1960) as "TheHole6"
    And JW knows "LeTrou60" as "Le Trou" directed by "Jacques Becker"
    And JW knows "TheHole6" as "The Hole" directed by "Jacques Becker"
    And the resolver matches "Le Trou" to "tt9000501" (tmdb 9501) directed by "Jacques Becker"
    And the resolver matches "The Hole" to "tt9000502" (tmdb 9502) directed by "Jacques Becker"
    And TMDB knows "tt9000501" as film 9501 "The Hole" (1960)
    And TMDB knows "tt9000502" as film 9502 "The Hole" (1960)
    When the walk runs
    Then the walk created 1 film
    And the walk reports arrived 1, left 0, to review 1
    And there is 1 open criterion "corpus-veto" review for "TheHole6"

  Scenario: A tombstoned holder is never relisted by a new mediaid
    Given a film "Trash Humpers" (2009) holding imdb "tt9000601"
    And the film "Trash Humpers" is tombstoned
    And Criterion lists "Trash Humpers" (2009) as "TrshHump"
    And JW knows "TrshHump" as "Trash Humpers" directed by "Harmony Korine"
    And the resolver matches "Trash Humpers" to "tt9000601" (tmdb 9601) directed by "Harmony Korine"
    When the walk runs
    Then there is 1 open criterion "tombstoned-holder" review for "TrshHump"
    And no film was created

  Scenario: A bridged film keeps its slugged link; an old-style link becomes the film's new page (story 10)
    Given the last walk listed "Test Pattern" (2019) as "gpRRkq27" at "https://www.criterionchannel.com/films/gpRRkq27/test-pattern"
    And the last walk listed "Nadja" (1994) as "7xCZH5br" at "https://www.criterionchannel.com/nadja"
    And Criterion lists "Test Pattern" (2021) as "gpRRkq27"
    And Criterion lists "Nadja" (1995) as "7xCZH5br"
    When the walk runs
    Then the film "Test Pattern" is listed at "https://www.criterionchannel.com/films/gpRRkq27/test-pattern"
    And the film "Nadja" is listed at "https://www.criterionchannel.com/films/7xCZH5br"

  Scenario: A walk before the bridge's apply refuses and writes nothing (Review Focus 1, ledger L7)
    Given the last walk listed "Nadja" (1994) under its old link only
    And Criterion lists "Nadja" (1995) as "7xCZH5br"
    When the walk runs and fails
    Then the walk failure names "criterion bridge --apply"
    And Criterion is exactly as it was before the walk
    And Criterion was never asked for its catalog

  Scenario: A JW record with no director gives the new film no director, never an empty one (Review Focus 5)
    Given Criterion lists "Untitled Short" (2020) as "UntShort"
    And JW knows "UntShort" as "Untitled Short" with no director
    And the resolver matches "Untitled Short" (2020) to "tt9000801" (tmdb 9801) with no director
    And TMDB knows "tt9000801" as film 9801 "Untitled Short" (2020)
    When the walk runs
    Then the walk created 1 film
    And the resolver was asked about "Untitled Short" with no director
    And the film "Untitled Short" has no director
```

Create `tests/step_defs/test_criterion_walk.py`:

```python
"""The Criterion walk (spec 2026-10-01 D2, D4–D7, D10) and, from Task 6, review resolution of
criterion rows (D9). Assertions read the DATABASE; the site, the resolver and TMDB are fakes."""

from __future__ import annotations

import re
import sqlite3
from datetime import date, timedelta

import pytest
from criterion_fakes import FakeSite, captured_media, media_like
from lists_fakes import RecordingFetcher, StubTmdb, candidate
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.criterion_walk import parse_criterion_detail, walk_criterion
from movie_brain.application.review import resolve_review
from movie_brain.domain.models import Film, ReviewEntry
from movie_brain.domain.thumbprint import parse_title
from movie_brain.infrastructure.criterion_site import CatalogItem
from movie_brain.infrastructure.database import Repository
from movie_brain.infrastructure.tmdb import TmdbFacts

scenarios("../features/criterion_walk.feature")

LAST = date(2026, 9, 20)  # the last VHX walk: every seeded listing's last_seen
TODAY = date(2026, 10, 3)
SITE = "https://www.criterionchannel.com"
TABLES = (
    "films", "listings", "external_ids", "claim", "match_review",
    "availability_transitions", "meta", "my_ratings", "watchlist",
)


@pytest.fixture
def ctx(repo, monkeypatch):
    return {
        "repo": repo, "site": FakeSite(), "fetcher": RecordingFetcher(), "tmdb": StubTmdb(),
        "day": TODAY, "monkeypatch": monkeypatch, "reports": [], "error": None, "before": None,
        "logs": [], "refusal": None,
    }


def _q(ctx, sql, *args):
    conn = sqlite3.connect(ctx["repo"].db_path)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def _fid(ctx, title, year=None):
    rows = _q(ctx, "SELECT id FROM films WHERE title = ?" + (" AND year = ?" if year else ""), title,
              *([year] if year else []))
    assert len(rows) == 1, f"{len(rows)} films titled {title!r}"
    return rows[0][0]


def _snapshot(ctx):
    return {t: _q(ctx, f"SELECT * FROM {t} ORDER BY rowid") for t in TABLES}


def _open_rows(ctx, mediaid, reason=None):
    return [
        r for r in ctx["repo"].open_reviews("criterion")
        if r["value"] == mediaid and (reason is None or r["reason"] == reason)
    ]


# --- the catalog as we hold it -------------------------------------------------------------


@given(parsers.re(
    r'the last walk listed "(?P<title>[^"]+)" \((?P<year>\d{4})\) as "(?P<mediaid>\w{8})"'
    r'(?: at "(?P<url>[^"]+)")?'
))
def last_walk_listed(ctx, title, year, mediaid, url):
    repo = ctx["repo"]
    fid = repo.create_film(Film(title, int(year), None, ""))
    repo.set_external_id(fid, "criterion", mediaid, LAST)
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    repo.record_listing(fid, "criterion", url or f"{SITE}/films/{mediaid}/{slug}", LAST)


@given(parsers.parse('the last walk listed "{title}" ({year:d}) under its old link only'))
def last_walk_old_link(ctx, title, year):
    repo = ctx["repo"]
    fid = repo.create_film(Film(title, year, None, ""))
    old = f"{SITE}/{title.lower()}"
    repo.set_external_id(fid, "criterion", old, LAST)
    repo.record_listing(fid, "criterion", old, LAST)


@given(parsers.parse('a film "{title}" ({year:d}) holding imdb "{tt}"'))
def film_with_imdb(ctx, title, year, tt):
    fid = ctx["repo"].create_film(Film(title, year, None, ""))
    ctx["repo"].set_external_id(fid, "imdb", tt, LAST)


@given(parsers.parse('a film "{title}" ({year:d}) holding no ids'))
def film_bare(ctx, title, year):
    ctx["repo"].create_film(Film(title, year, None, ""))


@given(parsers.parse('the film "{title}" also holds criterion id "{mediaid}"'))
def also_mediaid(ctx, title, mediaid):
    ctx["repo"].set_external_id(_fid(ctx, title), "criterion", mediaid, LAST)


@given(parsers.parse('the film "{title}" also holds imdb "{tt}"'))
def also_imdb(ctx, title, tt):
    ctx["repo"].set_external_id(_fid(ctx, title), "imdb", tt, LAST)


@given(parsers.parse('the film "{title}" is rated {score:d}'))
def rated(ctx, title, score):
    ctx["repo"].set_rating(_fid(ctx, title), score, LAST)


@given(parsers.parse('the film "{title}" is on the watchlist'))
def watchlisted(ctx, title):
    ctx["repo"].toggle_watchlist(_fid(ctx, title), LAST)


@given(parsers.parse('the film "{title}" is leaving "{label}"'))
def leaving(ctx, title, label):
    conn = sqlite3.connect(ctx["repo"].db_path)
    conn.execute(
        "UPDATE listings SET leaving_date = ? WHERE film_id = ? AND source = 'criterion'", (label, _fid(ctx, title))
    )
    conn.commit()
    conn.close()


@given(parsers.parse('the film "{title}" is tombstoned'))
def tombstoned(ctx, title):
    ctx["repo"].tombstone_film(_fid(ctx, title), LAST, note="hidden by hand")


@given(parsers.parse('an open criterion "{reason}" review names "{mediaid}" for "{title}"'))
def open_row(ctx, reason, mediaid, title):
    ctx["repo"].append_reviews("criterion", [ReviewEntry(reason, _fid(ctx, title), mediaid, "{}")], LAST)


# --- the site, the resolver, TMDB ---------------------------------------------------------


@given(parsers.parse('Criterion lists "{title}" ({year:d}) as "{mediaid}"'))
def lists_item(ctx, title, year, mediaid):
    ctx["site"].items.append(CatalogItem(mediaid, title, year, 5400))


@given(parsers.parse('JW knows "{mediaid}" as captured'))
def jw_captured(ctx, mediaid):
    ctx["site"].media_by_id[mediaid] = captured_media()


@given(parsers.parse('JW knows "{mediaid}" as "{title}" directed by "{director}"'))
def jw_knows(ctx, mediaid, title, director):
    ctx["site"].media_by_id[mediaid] = media_like(mediaid, title, (director,))


@given(parsers.parse('JW knows "{mediaid}" as "{title}" with no director'))
def jw_knows_no_director(ctx, mediaid, title):
    ctx["site"].media_by_id[mediaid] = media_like(mediaid, title, ())


@given(parsers.parse('JW fails for "{mediaid}"'))
def jw_fails(ctx, mediaid):
    ctx["site"].media_fails.add(mediaid)


@given(parsers.parse('the leaving page lists "{mediaid}" for "{label}"'))
def leaving_page(ctx, mediaid, label):
    ctx["site"].leaving_labels[mediaid] = label


@given("the leaving pages cannot be read")
def leaving_down(ctx):
    ctx["site"].leaving_labels = None


def _q_title(title):
    """The title the resolver is asked about: `make_query` parses the printed title first."""
    return parse_title(title).title


@given(parsers.parse('the resolver matches "{title}" to "{tt}" (tmdb {tid:d}) directed by "{director}"'))
def resolver_matches(ctx, title, tt, tid, director):
    ctx["fetcher"].by_title[_q_title(title)] = [candidate(tt, tid, _q_title(title), None, director)]


@given(parsers.parse('the resolver matches "{title}" ({year:d}) to "{tt}" (tmdb {tid:d}) with no director'))
def resolver_matches_no_director(ctx, title, year, tt, tid):
    ctx["fetcher"].by_title[_q_title(title)] = [candidate(tt, tid, _q_title(title), year, "")]


@given(parsers.parse('the resolver finds two works named "{title}" ({year:d})'))
def resolver_two(ctx, title, year):
    t = _q_title(title)
    ctx["fetcher"].by_title[t] = [candidate("tt9000401", 9401, t, year, ""), candidate("tt9000402", 9402, t, year, "")]


@given(parsers.parse('the resolver finds nothing for "{title}"'))
def resolver_nothing(ctx, title):
    ctx["fetcher"].by_title.pop(_q_title(title), None)


@given(parsers.parse('the resolver is offline for "{title}"'))
def resolver_offline(ctx, title):
    ctx["fetcher"].offline.add(_q_title(title))


@given(parsers.parse('TMDB knows "{tt}" as film {tid:d} "{title}" ({year:d})'))
def tmdb_knows(ctx, tt, tid, title, year):
    ctx["tmdb"].by_imdb[tt] = tid
    ctx["tmdb"].facts[tid] = TmdbFacts(tt, title, title, (), year, 90)


@given("the walk's write fails at its last step")
def write_fails(ctx):
    def boom(c, leaving, day):
        raise RuntimeError("disk full")

    ctx["monkeypatch"].setattr(Repository, "_walk_leaving", staticmethod(boom))


# --- running it ----------------------------------------------------------------------------


def _walk(ctx, *, token=True):
    ctx["reports"].append(
        walk_criterion(
            ctx["repo"], ctx["site"], ctx["fetcher"] if token else None, ctx["tmdb"] if token else None,
            ctx["day"], log=ctx["logs"].append,
        )
    )


@when("the walk runs")
def walk_runs(ctx):
    _walk(ctx)


@when("the walk runs again the next day")
def walk_next_day(ctx):
    ctx["day"] = ctx["day"] + timedelta(days=1)
    _walk(ctx)


@when("the walk runs without a TMDB token")
def walk_no_token(ctx):
    _walk(ctx, token=False)


@when("the walk runs and fails")
def walk_fails(ctx):
    ctx["before"] = _snapshot(ctx)
    with pytest.raises(Exception) as caught:  # noqa: PT011 — any failure: the point is what it left behind
        _walk(ctx)
    ctx["error"] = caught.value


@when("the resolver comes back")
def resolver_back(ctx):
    ctx["fetcher"].offline.clear()


@when(parsers.parse('the owner dismisses the criterion review for "{mediaid}"'))
def owner_dismisses(ctx, mediaid):
    (row,) = _open_rows(ctx, mediaid)
    resolve_review(ctx["repo"], int(row["id"]), today=ctx["day"], dismiss=True)


# --- outcomes ------------------------------------------------------------------------------


def _report(ctx):
    return ctx["reports"][-1]


@then(parsers.parse("the walk reports arrived {a:d}, left {d:d}, to review {r:d}"))
def reports(ctx, a, d, r):
    rep = _report(ctx)
    assert (rep.arrived, rep.departed, rep.reviews) == (a, d, r), rep


@then(parsers.parse("the walk created {n:d} film"))
def created_n(ctx, n):
    assert _report(ctx).created == n


@then("no film was created")
def created_none(ctx):
    assert _report(ctx).created == 0


@then(parsers.parse("the walk did not ask about {n:d} film tonight"))
def skipped_n(ctx, n):
    assert _report(ctx).skipped == n


@then(parsers.parse('there is {n:d} film titled "{title}"'))
def n_titled(ctx, n, title):
    assert _q(ctx, "SELECT COUNT(*) FROM films WHERE title = ?", title) == [(n,)]


@then(parsers.parse('the film "{title}" has year {year:d} and rating {score:d}'))
def year_and_rating(ctx, title, year, score):
    fid = _fid(ctx, title)
    assert _q(ctx, "SELECT year FROM films WHERE id = ?", fid) == [(year,)]
    assert _q(ctx, "SELECT score FROM my_ratings WHERE film_id = ?", fid) == [(score,)]


@then(parsers.parse('the film "{title}" has year {year:d} and director "{director}"'))
def year_and_director(ctx, title, year, director):
    assert _q(ctx, "SELECT year, director FROM films WHERE id = ?", _fid(ctx, title)) == [(year, director)]


@then(parsers.parse('the film "{title}" has no director'))
def no_director(ctx, title):
    assert _q(ctx, "SELECT director FROM films WHERE id = ?", _fid(ctx, title)) == [(None,)]


@then(parsers.parse('the film "{title}" is current on Criterion'))
def current(ctx, title):
    assert _fid(ctx, title) in {i for i, _ in ctx["repo"].current_films("criterion")}


@then(parsers.parse('the film "{title}" is not current on Criterion'))
def not_current(ctx, title):
    assert _fid(ctx, title) not in {i for i, _ in ctx["repo"].current_films("criterion")}


@then(parsers.parse('the film "{title}" holds criterion id "{mediaid}"'))
def holds_mediaid(ctx, title, mediaid):
    assert ("criterion", mediaid) in ctx["repo"].external_ids_all(_fid(ctx, title))


@then(parsers.parse('the film "{title}" holds criterion ids "{a}" and "{b}"'))
def holds_two(ctx, title, a, b):
    ids = ctx["repo"].external_ids_all(_fid(ctx, title))
    assert ("criterion", a) in ids and ("criterion", b) in ids


@then(parsers.parse('the film "{title}" holds no criterion id'))
def holds_none(ctx, title):
    assert not [v for a, v in ctx["repo"].external_ids_all(_fid(ctx, title)) if a == "criterion"]


@then(parsers.parse('the film "{title}" holds imdb "{tt}"'))
def holds_imdb(ctx, title, tt):
    assert ctx["repo"].external_ids_for(_fid(ctx, title)).get("imdb") == tt


@then(parsers.parse('the film "{title}" has a criterion claim "{mediaid}" titled "{claimed}" for {year:d}'))
def has_claim(ctx, title, mediaid, claimed, year):
    assert _q(ctx, "SELECT film_id, title_ingested, year_claimed FROM claim WHERE authority = 'criterion' "
                   "AND value = ?", mediaid) == [(_fid(ctx, title), claimed, year)]


@then(parsers.parse('the film "{title}" has {n:d} criterion claims'))
def n_claims(ctx, title, n):
    assert _q(ctx, "SELECT COUNT(*) FROM claim WHERE authority = 'criterion' AND film_id = ?", _fid(ctx, title)) == [(n,)]


@then(parsers.parse('the film "{title}" has {n:d} Criterion listing'))
def n_listings(ctx, title, n):
    assert _q(ctx, "SELECT COUNT(*) FROM listings WHERE source = 'criterion' AND film_id = ?", _fid(ctx, title)) == [(n,)]


@then(parsers.parse('the film "{title}" is listed at "{url}"'))
def listed_at(ctx, title, url):
    assert _q(ctx, "SELECT url FROM listings WHERE source = 'criterion' AND film_id = ?", _fid(ctx, title)) == [(url,)]


@then(parsers.parse('the film "{title}" arrived on Criterion today'))
def arrived_today(ctx, title):
    assert _q(ctx, "SELECT COUNT(*) FROM availability_transitions WHERE film_id = ? AND source = 'criterion' "
                   "AND appeared_on = ?", _fid(ctx, title), ctx["day"].isoformat()) == [(1,)]


@then("no film arrived on Criterion today")
def none_arrived(ctx):
    assert _q(ctx, "SELECT COUNT(*) FROM availability_transitions WHERE appeared_on = ?", ctx["day"].isoformat()) == [(0,)]


@then(parsers.parse('the film "{title}" is leaving "{label}"'))
def is_leaving(ctx, title, label):
    assert _q(ctx, "SELECT leaving_date FROM listings WHERE source = 'criterion' AND film_id = ?", _fid(ctx, title)) == [(label,)]


@then(parsers.parse('the film "{title}" is not leaving'))
def not_leaving(ctx, title):
    assert _q(ctx, "SELECT leaving_date FROM listings WHERE source = 'criterion' AND film_id = ?", _fid(ctx, title)) == [(None,)]


@then(parsers.parse('the film "{title}" is still on the watchlist'))
def still_watchlisted(ctx, title):
    assert _fid(ctx, title) in ctx["repo"].watchlist_film_ids()


@then(parsers.parse('there is {n:d} open criterion "{reason}" review for "{mediaid}"'))
def n_open(ctx, n, reason, mediaid):
    assert len(_open_rows(ctx, mediaid, reason)) == n


@then(parsers.parse('there is no open criterion review for "{mediaid}"'))
def none_open(ctx, mediaid):
    assert _open_rows(ctx, mediaid) == []


@then(parsers.parse("that review shows Criterion's title \"{title}\", year {year:d} and director \"{director}\""))
def review_shows(ctx, title, year, director):
    (row,) = ctx["repo"].open_reviews("criterion")
    crit = parse_criterion_detail(str(row["detail"]))
    assert crit is not None
    assert (crit["title"], crit["year"], crit["director"]) == (title, year, [director])


@then(parsers.re(r"JW Player was asked (?P<n>\d+) times? in all"))
def jw_asked(ctx, n):
    assert len(ctx["site"].media_calls) == int(n), ctx["site"].media_calls


@then("Criterion was never asked for its catalog")
def no_catalog_call(ctx):
    assert "catalog" not in ctx["site"].calls


@then(parsers.parse('the walk failure names "{text}"'))
def failure_names(ctx, text):
    assert text in str(ctx["error"])


@then("Criterion is exactly as it was before the walk")
def unchanged(ctx):
    assert _snapshot(ctx) == ctx["before"]


@then(parsers.parse('the resolver was asked about "{title}" with no director'))
def asked_no_director(ctx, title):
    q = next(q for q in ctx["fetcher"].queries if q.title == _q_title(title))
    assert q.director is None
```

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest tests/step_defs/test_criterion_walk.py -q`
Expected: `ModuleNotFoundError: No module named 'movie_brain.application.criterion_walk'`.

- [ ] **Step 4: Implement**

Create `src/movie_brain/application/criterion_walk.py`:

```python
"""The nightly Criterion walk after the 2026-10 relaunch (spec 2026-10-01 D2, D4–D7, D10).

Identity is the mediaid: a catalog item whose mediaid a film holds IS that film, whatever title
or year Criterion prints for it now — our title and year stay, Criterion's go in the claim (D4).
Only a mediaid NO film holds is asked about: its JW Player record, the thumbprint resolver, then
the gate ladder `films add` runs (D5). Every network call happens before anything is written;
the write is ONE transaction (`Repository.record_criterion_walk`, D6), so a failure anywhere
leaves Criterion exactly as it was. The films it created are keyed afterwards, and a keying
failure never undoes a creation — the next sync's keying step retries.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

import requests

from movie_brain.application.films import CORPUS_VETO, KEY_COLLISION, gate_ladder
from movie_brain.application.lists import _catalog, _key_new_film, corpus_veto
from movie_brain.application.thumbprint import review_detail
from movie_brain.domain.matching import Candidate as CorpusCandidate
from movie_brain.domain.matching import CandidateIndex, build_candidate_index
from movie_brain.domain.models import CriterionWalk, NewFilm, ReviewEntry, WalkListing
from movie_brain.domain.thumbprint import Query, Verdict, make_query, resolve
from movie_brain.infrastructure.criterion_site import CatalogItem, CriterionError, JwMedia, Leaving
from movie_brain.infrastructure.database import Repository
from movie_brain.infrastructure.omdb import QuotaExceeded
from movie_brain.infrastructure.thumbprint_fetch import CacheMiss, CandidateFetcher
from movie_brain.infrastructure.tmdb import AuthError, TmdbClient

AUTHORITY = "criterion"
NO_MATCH = "no-match"
NO_RECORD = "no-record"
# The resolver's and TMDB's weather: never a verdict, so never a review row (D5).
WEATHER = (CacheMiss, requests.RequestException, AuthError, QuotaExceeded)


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


class CriterionSite(Protocol):
    def catalog(self) -> list[CatalogItem]: ...

    def media(self, mediaid: str) -> JwMedia | None: ...

    def leaving(self) -> Leaving: ...


@dataclass(frozen=True)
class WalkReport:
    arrived: int = 0
    departed: int = 0
    reviews: int = 0
    created: int = 0
    skipped: int = 0  # unknown items not asked about tonight: no resolver, or its lookups failed
    waiting: int = 0  # unknown items a review row already covers (open, or a standing decision)


def criterion_detail(
    item: CatalogItem,
    media: JwMedia | None,
    *,
    reason: str,
    verdict: Verdict | None = None,
    query: Query | None = None,
    tt: str | None = None,
    refused: str | None = None,
) -> str:
    """D5: the resolver's own review envelope (`review_detail` — reason, A/B/C, query) EXTENDED
    with what Criterion showed. It is what the owner reads to choose `--film X`, and what
    `review resolve --create` mints from (never a refetch: a `no-record` id would 404 again)."""
    body: dict[str, Any] = (
        json.loads(review_detail(verdict, query)) if verdict is not None else {"reason": reason, "candidates": []}
    )
    crit: dict[str, Any] = {
        "mediaid": item.mediaid, "title": item.title, "year": item.year, "duration_s": item.duration_s,
    }
    if media is not None:
        crit.update(director=list(media.directors), title_original=media.title_original, criterion_id=media.criterion_id)
    if tt is not None:
        crit["tt"] = tt
    if refused is not None:
        crit["refused"] = refused
    body["criterion"] = crit
    return json.dumps(body, ensure_ascii=False)


def parse_criterion_detail(detail: str | None) -> dict[str, Any] | None:
    """The `criterion` block of a row's detail, or None. `review resolve` appends ` [note]`
    after the JSON, so the body is read up to its last brace (as `parse_review_detail` does)."""
    if not detail or not detail.lstrip().startswith("{"):
        return None
    try:
        obj = json.loads(detail[: detail.rfind("}") + 1])
    except ValueError:
        return None
    crit = obj.get("criterion") if isinstance(obj, dict) else None
    return crit if isinstance(crit, dict) else None


def _director(media: JwMedia) -> str | None:
    return ", ".join(media.directors) or None


def _forms(item: CatalogItem, media: JwMedia) -> list[str]:
    """Criterion's own names for the work, which widen gate 3 (ledger L3)."""
    return list(dict.fromkeys(t for t in (item.title, media.title_original or "") if t))


def _review(reason: str, item: CatalogItem, media: JwMedia | None, **kw: Any) -> ReviewEntry:
    return ReviewEntry(reason, None, item.mediaid, criterion_detail(item, media, reason=reason, **kw))


def _leaving(site: CriterionSite, log: Callable[[str], None]) -> dict[str, str] | None:
    try:
        leaving = site.leaving()
    except Exception as exc:  # noqa: BLE001 — D7: a leaving failure keeps last-known labels, never aborts
        log(f"criterion: leaving pages unreadable, keeping last-known labels: {exc}")
        return None
    for line in leaving.mismatches:
        log(f"criterion: leaving date cross-check: {line}")
    return dict(leaving.labels)


def walk_criterion(
    repo: Repository,
    site: CriterionSite,
    fetcher: CandidateFetcher | None,
    tmdb: TmdbClient | None,
    today: date,
    *,
    log: Callable[[str], None] = _stderr,
) -> WalkReport:
    """One walk: stage everything (network only), write it in one transaction, key what it made.

    Raises on any failure before or inside the write; the caller (sync) catches it and carries
    on with the rest of the night. Per catalog item, in catalog order:
    1. a mediaid some film holds → that film (whatever review rows mention the mediaid);
    2. a mediaid any criterion review row names (open or resolved) → left to the human, no JW call;
    3. no resolver tonight (no TMDB token or no OMDb key) → skipped, asked again next walk;
    4. JW's record: 404 → a `no-record` review row; a failure → the walk fails (D6);
    5. the resolver: weather → skipped; no match → a `no-match` row carrying the A/B/C envelope;
    6. a match on a tt this walk is already creating → joins that staged film (The Beast 2023);
    7. the gate ladder: a holder → joins it; a refusal → a review row named by the gate;
       weather → skipped; clear → staged for creation unless it resembles (gate 3 over this
       walk's own staged titles) or keys like a film this walk is already creating → review.
    """
    holders = repo.criterion_mediaid_holders()
    if not holders and repo.current_films(AUTHORITY):
        raise CriterionError(
            "films are listed on Criterion but none holds a Criterion id yet — "
            "run `movie-brain criterion bridge --apply` before the first walk"
        )
    items = site.catalog()
    covered = repo.criterion_review_values()
    film_rows = repo.films_for_matching()
    index = build_candidate_index(film_rows)
    catalog = _catalog(repo, film_rows)

    listings: list[WalkListing] = []
    created: list[NewFilm] = []
    reviews: list[ReviewEntry] = []
    reserved: dict[str, int] = {}  # tt → index into `created`
    staged_keys: set[str] = set()
    staged = CandidateIndex()  # gate 3 over the films this walk is about to create
    skipped = waiting = 0
    for item in items:
        holder = holders.get(item.mediaid)
        if holder is not None:
            listings.append(WalkListing(item.mediaid, item.title, item.year, film_id=holder))
            continue
        if item.mediaid in covered:
            waiting += 1
            continue
        if fetcher is None or tmdb is None:
            skipped += 1
            continue
        media = site.media(item.mediaid)
        if media is None:
            reviews.append(_review(NO_RECORD, item, None))
            continue
        q = make_query(item.title, item.year, "criterion", director=_director(media))
        try:
            verdict = resolve(q, fetcher.fetch(q))
        except WEATHER as exc:
            log(f"criterion: resolver lookup failed for {item.title!r} ({item.mediaid}), asked again next walk: {exc}")
            skipped += 1
            continue
        if verdict.kind != "match" or verdict.tt is None:
            reviews.append(_review(NO_MATCH, item, media, verdict=verdict, query=q))
            continue
        if verdict.tt in reserved:
            listings.append(WalkListing(item.mediaid, item.title, item.year, new=reserved[verdict.tt], bind=True))
            continue
        forms = _forms(item, media)
        lad = gate_ladder(repo, tmdb, verdict, index=index, catalog=catalog, extra_forms=forms, log=log)
        if lad.kind == "weather":
            log(f"criterion: {lad.detail} for {item.title!r} ({item.mediaid}), asked again next walk")
            skipped += 1
            continue
        if lad.kind == "held":
            listings.append(WalkListing(item.mediaid, item.title, item.year, film_id=lad.holder, bind=True))
            continue
        if lad.kind == "blocked":
            reviews.append(
                _review(lad.reason, item, media, verdict=verdict, query=q, tt=verdict.tt, refused=lad.detail)
            )
            continue
        new = NewFilm(lad.title, lad.year, _director(media), verdict.tt, lad.tmdb_id)
        clash = corpus_veto(staged, [lad.title, *forms])
        if clash or new.key in staged_keys:
            refused = f"this walk is already creating a film like {lad.title!r} ({lad.year or '-'})"
            reason = CORPUS_VETO if clash else KEY_COLLISION
            reviews.append(_review(reason, item, media, verdict=verdict, query=q, tt=verdict.tt, refused=refused))
            continue
        reserved[verdict.tt] = len(created)
        staged_keys.add(new.key)
        for title in dict.fromkeys((lad.title, *forms)):
            staged.add(CorpusCandidate(id=-(len(created) + 1), title=title, year=lad.year))
        listings.append(WalkListing(item.mediaid, item.title, item.year, new=len(created), bind=True))
        created.append(new)

    leaving = _leaving(site, log)
    wrote = repo.record_criterion_walk(
        CriterionWalk(tuple(listings), tuple(created), tuple(reviews), leaving), today
    )
    for film_id, new in wrote.created:
        _key_new_film(repo, tmdb, film_id, new.tt, new.tmdb_id, today, log)
    return WalkReport(wrote.arrived, wrote.departed, len(reviews), len(created), skipped, waiting)
```

- [ ] **Step 5: Run the scenarios to verify they pass**

Run: `uv run pytest tests/step_defs/test_criterion_walk.py -q && uv run mypy src/movie_brain/application/criterion_walk.py`
Expected: 24 passed; mypy clean for this file. If a resolver scenario stays `review` instead of `match`, print `resolve(q, pool)` in a REPL against the step's candidate before changing anything — the candidate shapes above follow `domain/thumbprint.py::resolve`'s "director corroborated" and "exact title + year + agreement" rules, and the rules are contract (never edit them to pass a test).

- [ ] **Step 6: Commit**

```bash
git add src/movie_brain/application/criterion_walk.py tests/criterion_fakes.py tests/features/criterion_walk.feature tests/step_defs/test_criterion_walk.py
git commit -m "The Criterion walk matches by mediaid and only asks about ids no film holds, so a renamed film stays the owner's and a new one goes through the same gates as films add

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Sync walks the new site; the VHX reader goes

**Files:**
- Modify: `src/movie_brain/application/sync.py`, `src/movie_brain/cli.py`
- Delete: `src/movie_brain/infrastructure/criterion.py`, `tests/unit/test_criterion.py`
- Rewrite: `tests/features/sync.feature`, `tests/step_defs/test_sync.py`
- Modify: `tests/step_defs/test_tmdb.py`, `tests/step_defs/test_watchlist.py`, `tests/features/tmdb.feature`, `tests/features/watchlist.feature`, `tests/unit/test_cli.py`

**Interfaces:**
- Consumes: `walk_criterion`, `WalkReport`, `CriterionSite` (Task 4); `HttpCriterionSite` (Task 1); `FakeSite`, `seed_known`, `mediaid_for` (Task 4's `tests/criterion_fakes.py`).
- Produces:
  - `sync(repo, api_key, today, *, session=None, ratings_only=False, tmdb_token=None, config_dir=None, notifier=None, fetcher=None, skip_catalog=False, catch_up=None, site: CriterionSite | None = None, log=_stderr) -> SyncResult` — `delay_s`, `force_full`, `max_age_days` are gone (ledger L8)
  - `SyncResult(exit_code, films, looked_up, quota_hit, failing, tmdb_matched=0, tmdb_missed=0, tmdb_refreshed=0, tmdb_watchlist_refreshed=0, mc_promoted=0, tmdb_first_checked=0, tmdb_reviewed=0, omdb_unkeyed=0, catch_up=None, criterion_walked=False, criterion_failed=False, criterion_arrived=0, criterion_departed=0, criterion_reviews=0, criterion_skipped=0)` — `full_walk` is gone
  - `cli._criterion_line(result: SyncResult) -> str | None`

Retired deliberately (spec §5): `tests/unit/test_criterion.py` (the VHX adapter's tests); the sync.feature scenarios "Unchanged page 1 within 7 days reuses the stored catalog", "A changed page 1 forces a full walk", "A year-less duplicate page merges into the titled film", "Year-less duplicates keep the cheap page-1 check working", "--full always walks"; "Catalog failure leaves the database untouched" is replaced by "A catalog failure writes nothing for Criterion, and the rest of the night still runs". `domain/models.merge_yearless` and its unit tests stay (D11).

- [ ] **Step 1: Rewrite the sync scenarios (failing)**

Replace the whole of `tests/features/sync.feature` with the text below. Fixture arithmetic: "Criterion lists my films X" seeds X as the bridge leaves it (holding its mediaid) with NO listing unless "the last walk listed X" put one there N days before TODAY (2026-08-19); a film listed for the first time counts as an arrival.

```gherkin
Feature: Daily sync
  Walk the Criterion catalog by mediaid (spec 2026-10-01), then the rest of the night: Metacritic
  promotion, keying, OMDb ratings, TMDB availability, the catch-up chain. One source's weather
  never breaks another: a failed Criterion walk writes nothing for Criterion, the rest still runs,
  and the sync exits 1.

  Background:
    Given a fresh repository
    And the Criterion home page links no dated leaving page

  Scenario: Sync lists the films Criterion carries and fills their ratings (story 1)
    # two films seeded with no listing: both arrive
    Given Criterion lists my films "Trio (1950)" and "Quartet (1948)"
    And OMDb knows every film
    And the resolver keys every film
    When I sync
    Then the exit code is 0
    And 2 films are current
    And 2 films have OMDb ratings
    And films_fetched_at is today
    And the sync reports criterion arrived 2, left 0, to review 0

  Scenario: A film Criterion dropped is departed, kept, and loses its Leaving label (stories 5 and 11)
    # both listed 9 days ago (the frontier); only Nadja is re-stamped
    Given the last walk listed "Some Came Running (1958)" and "Nadja (1994)" 9 days ago
    And "Some Came Running (1958)" is leaving "September 30"
    And Criterion lists my films "Nadja (1994)"
    And OMDb knows every film
    When I sync
    Then the exit code is 0
    And 1 films are current
    And "Some Came Running (1958)" is still in the database
    And "Some Came Running (1958)" is not leaving
    And the sync reports criterion arrived 0, left 1, to review 0

  Scenario: A departed rated film is kept and shown as departed
    Given the last walk listed "Trio (1950)" and "Quartet (1948)" 9 days ago
    And I have rated "Quartet (1948)"
    And Criterion lists my films "Trio (1950)"
    And OMDb knows every film
    When I sync
    Then "Quartet (1948)" is in the dashboard marked departed

  Scenario: A watchlisted film arriving on Criterion fires the one summary notification
    # Trio is re-stamped (no arrival); Barry Lyndon had no listing (one arrival, watchlisted)
    Given the last walk listed "Trio (1950)" 2 days ago
    And "Barry Lyndon (1975)" is on the watchlist
    And Criterion lists my films "Trio (1950)" and "Barry Lyndon (1975)"
    And OMDb knows every film
    When I sync with a notifier
    Then one notification was sent naming "Barry Lyndon on Criterion Channel"
    And the sync reports criterion arrived 1, left 0, to review 0

  Scenario: The Leaving chip gets October's list from the dated leaving page (story 6)
    # the captured playlist names 28 films; Zabriskie Point is the only one we hold
    Given Criterion calls "Zabriskie Point (1970)" "Tg73fdO2"
    And the last walk listed "Zabriskie Point (1970)" and "Nadja (1994)" 2 days ago
    And "Nadja (1994)" is leaving "September 30"
    And Criterion lists my films "Zabriskie Point (1970)" and "Nadja (1994)"
    And the Criterion home page links the October 31 leaving page
    And OMDb knows every film
    When I sync
    Then "Zabriskie Point (1970)" is leaving "October 31"
    And "Nadja (1994)" is not leaving

  Scenario: A leaving page that cannot be read keeps the labels of the films still listed
    Given the last walk listed "Trio (1950)" 2 days ago
    And "Trio (1950)" is leaving "August 31"
    And Criterion lists my films "Trio (1950)"
    And the Criterion home page answers 500
    And OMDb knows every film
    When I sync
    Then the exit code is 0
    And "Trio (1950)" is leaving "August 31"

  Scenario: A catalog failure writes nothing for Criterion, and the rest of the night still runs (story 8)
    Given the last walk listed "Trio (1950)" 2 days ago
    And "Trio (1950)" is already keyed to imdb "tt0037800"
    And the Criterion catalog answers 500
    And OMDb knows every film
    When I sync
    Then the exit code is 1
    And the sync reports the Criterion walk failed
    And 1 films are current
    And 1 films have OMDb ratings

  Scenario: A JW Player failure for a new film writes nothing for Criterion, and the rest still runs (story 8)
    Given the last walk listed "Trio (1950)" 2 days ago
    And "Trio (1950)" is already keyed to imdb "tt0037800"
    And Criterion lists my films "Trio (1950)"
    And Criterion also lists a new film "2 or 3 Things I Know About Her" (1967) as "L5Z3RaiC"
    And JW Player answers 500 for "L5Z3RaiC"
    And the resolver finds nothing
    And OMDb knows every film
    When I sync
    Then the exit code is 1
    And the sync reports the Criterion walk failed
    And 1 films have OMDb ratings
    And there are 0 open criterion reviews
    And the Criterion listing of "Trio (1950)" was last seen 2 days ago

  Scenario: A failure late in the walk's write is caught before the rest of the night runs (story 8)
    Given the last walk listed "Trio (1950)" 2 days ago
    And "Trio (1950)" is already keyed to imdb "tt0037800"
    And Criterion lists my films "Trio (1950)"
    And OMDb knows every film
    And the walk's write fails at its last step
    When I sync
    Then the exit code is 1
    And when the keying step began, Criterion was exactly as it was before the sync
    And 1 films have OMDb ratings

  Scenario: A series is never a film (Lone Wolf and Cub, story 18)
    # Sword of Vengeance holds only its old link (the episodes now 404): it departs; Trio arrives
    Given the last walk listed "Lone Wolf and Cub: Sword of Vengeance (1972)" 2 days ago under its old link
    And Criterion lists my films "Trio (1950)"
    And the catalog also carries the series "Lone Wolf and Cub" as "rLiSVzkD"
    And OMDb knows every film
    When I sync
    Then no film is titled "Lone Wolf and Cub"
    And there are 0 open criterion reviews
    And the sync reports criterion arrived 1, left 1, to review 0

  Scenario: A new film the resolver cannot place becomes one review row, asked about once (story 7)
    Given Criterion lists my films "Trio (1950)"
    And Criterion also lists a new film "2 or 3 Things I Know About Her" (1967) as "L5Z3RaiC"
    And JW Player serves its captured record for "L5Z3RaiC"
    And the resolver finds nothing
    And OMDb knows every film
    When I sync
    Then there is 1 open criterion "no-match" review for "L5Z3RaiC"
    And the sync reports criterion arrived 1, left 0, to review 1
    When I sync again the next day
    Then there is 1 open criterion "no-match" review for "L5Z3RaiC"
    And JW Player was asked about "L5Z3RaiC" 1 time

  Scenario: --ratings-only skips Criterion
    Given the last walk listed "Trio (1950)" 2 days ago
    And "Trio (1950)" is already keyed to imdb "tt0037800"
    And OMDb knows every film
    When I sync with --ratings-only
    Then the exit code is 0
    And Criterion was never contacted
    And 1 films have OMDb ratings

  Scenario: The catch-up chain runs at the tail of a sync, after identity, ratings and availability
    Given Criterion lists my films "Trio (1950)" and "Quartet (1948)"
    And OMDb knows every film
    And the resolver keys every film
    When I sync with a catch-up chain
    Then the exit code is 0
    And the catch-up chain ran once, after 2 films had OMDb ratings
    And the sync result carries the catch-up report

  Scenario: A catch-up chain that blows up never changes the sync's outcome
    Given Criterion lists my films "Trio (1950)" and "Quartet (1948)"
    And OMDb knows every film
    And the resolver keys every film
    When I sync with a catch-up chain that fails
    Then the exit code is 0
    And 2 films have OMDb ratings

  Scenario: --ratings-only runs no catch-up
    Given the last walk listed "Trio (1950)" 2 days ago
    And "Trio (1950)" is already keyed to imdb "tt0037800"
    And OMDb knows every film
    When I sync with --ratings-only and a catch-up chain
    Then the exit code is 0
    And the catch-up chain never ran

  Scenario: Enriching after an add skips Criterion but keys, rates and catches up
    Given the last walk listed "Trio (1950)" 2 days ago
    And OMDb knows every film
    And the resolver keys every film
    When I run the after-add enrichment with a catch-up chain
    Then the exit code is 0
    And Criterion was never contacted
    And 1 films have OMDb ratings
    And the catch-up chain ran once, after 1 films had OMDb ratings

  Scenario: --ratings-only without a stored catalog fails
    When I sync with --ratings-only
    Then the exit code is 1

  Scenario: OMDb quota stops lookups but keeps what was fetched
    Given Criterion lists my films "Trio (1950)" and "Quartet (1948)"
    And OMDb answers once then reports the request limit
    And the resolver keys every film
    When I sync
    Then the exit code is 0
    And the quota flag is set
    And 1 films have OMDb ratings

  Scenario: OMDb rejects the key
    Given Criterion lists my films "Trio (1950)"
    And OMDb rejects the API key
    And the resolver keys every film
    When I sync
    Then the exit code is 2

  Scenario: Repeated OMDb failures stop lookups but keep what was fetched
    Given Criterion lists my films "Trio (1950)" and "Quartet (1948)" and "Third (1960)" and "Fourth (1970)" and "Fifth (1980)" and "Sixth (1990)" and "Seventh (2000)"
    And OMDb answers once then errors repeatedly
    And the resolver keys every film
    When I sync
    Then the exit code is 0
    And the failing flag is set
    And 1 films have OMDb ratings

  Scenario: Sync promotes staged Metacritic titles into films
    Given Criterion lists my films "Alpha (1950)"
    And OMDb knows every film
    And the metacritic archive holds "Fresh Find" (2020) scored 95 as "fresh-find"
    When I sync with a metacritic archive
    Then the exit code is 0
    And the repository holds a film for key "fresh find (2020)"

  Scenario: A missing metacritic archive never breaks the sync
    Given Criterion lists my films "Alpha (1950)"
    And OMDb knows every film
    When I sync with a metacritic archive
    Then the exit code is 0

  Scenario: Promoted films get OMDb ratings the same night
    Given Criterion lists my films "Alpha (1950)"
    And OMDb knows every film
    And the resolver keys every film
    And the metacritic archive holds "Fresh Find" (2020) scored 95 as "fresh-find"
    When I sync with a metacritic archive
    Then the film for key "fresh find (2020)" has an OMDb rating
```

Replace the whole of `tests/step_defs/test_sync.py` with:

```python
"""Sync over HTTP with the real capture shapes (tests/fixtures/criterion/): the catalog, the
home page, the leaving page, the JW playlist and the JW media record are served by `responses`
and read by the real `HttpCriterionSite` (no pacing sleeps)."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest
import requests
import responses
from criterion_fakes import mediaid_for
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application import sync as sync_module
from movie_brain.application.sync import SOURCE, SyncResult, sync
from movie_brain.domain.models import Film
from movie_brain.domain.thumbprint import Candidate
from movie_brain.infrastructure.criterion_site import (
    BASE,
    CATALOG_URL,
    JW_PLAYLIST_URL,
    HttpCriterionSite,
)
from movie_brain.infrastructure.database import Repository
from movie_brain.infrastructure.omdb import OMDB_URL
from movie_brain.infrastructure.tmdb import TMDB_API

scenarios("../features/sync.feature")

TODAY = date(2026, 8, 19)
FOUND = {"Response": "True", "imdbRating": "7.0", "Language": "English", "Ratings": []}
LIMIT = {"Response": "False", "Error": "Request limit reached!"}
FIX = Path(__file__).parent.parent / "fixtures" / "criterion"
HOME_NO_DATED = '<html><a href="/discover/leaving-soon">Leaving soon</a></html>'
JW_MEDIA = re.compile(r"https://cdn\.jwplayer\.com/v2/media/(\w+)")
TABLES = ("films", "listings", "external_ids", "claim", "match_review", "availability_transitions")


def _load(name):
    return json.loads((FIX / name).read_text())


def parse_titles(text: str) -> list[Film]:
    films = []
    for m in re.finditer(r'"([^"(]+) \((\d{4})\)"', text):
        title, year = m.group(1), int(m.group(2))
        films.append(Film(title, year, "Someone", f"https://www.criterionchannel.com/{title.lower()}"))
    return films


def _q(ctx, sql, *args):
    conn = sqlite3.connect(ctx["repo"].db_path)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def _snapshot(ctx):
    return {t: _q(ctx, f"SELECT * FROM {t} ORDER BY rowid") for t in TABLES}


@pytest.fixture
def ctx(repo, config_dir, nuxt_page, monkeypatch):
    rs = responses.RequestsMock(assert_all_requests_are_fired=False)
    rs.start()
    world = {
        "items": [],  # dicts in the captured catalog-item shape
        "catalog_status": 200,
        "home": HOME_NO_DATED,
        "home_status": 200,
        "jw": {},  # mediaid → captured-shape body
        "jw_status": {},
        "jw_calls": [],
    }

    def catalog_cb(request):
        if world["catalog_status"] != 200:
            return (world["catalog_status"], {}, "boom")
        body = _load("all-films-results.lastpage.json")  # the real last page: no next key
        body["items"] = list(world["items"])
        body["total"] = len(body["items"])
        return (200, {}, json.dumps(body))

    def jw_cb(request):
        mediaid = JW_MEDIA.match(request.url).group(1)
        world["jw_calls"].append(mediaid)
        if mediaid in world["jw_status"]:
            return (world["jw_status"][mediaid], {}, "boom")
        if mediaid not in world["jw"]:
            return (404, {}, json.dumps({"message": f"['{mediaid}']: id not found in index."}))
        return (200, {}, json.dumps(world["jw"][mediaid]))

    rs.add_callback(responses.GET, CATALOG_URL, callback=catalog_cb)
    rs.add_callback(responses.GET, BASE + "/", callback=lambda r: (world["home_status"], {}, world["home"]))
    rs.add_callback(responses.GET, JW_MEDIA, callback=jw_cb)
    yield {
        "repo": repo, "rs": rs, "result": None, "config_dir": config_dir, "nuxt_page": nuxt_page,
        "mc_cards": [], "world": world, "ids": {}, "monkeypatch": monkeypatch, "day": TODAY,
    }
    rs.stop()
    rs.reset()


def _mediaid(ctx, title):
    return ctx["ids"].get(title) or mediaid_for(title)


def _item(mediaid, title, year):
    return {"contentType": "film", "duration": 5400, "mediaid": mediaid, "release_date": f"{year}-01-01", "title": title}


def _fid(ctx, title_year):
    f = parse_titles(f'"{title_year}"')[0]
    return ctx["repo"].film_id_by_key(f.key)


@given("a fresh repository")
def fresh(ctx):
    pass


@given("the Criterion home page links no dated leaving page")
def home_no_dated(ctx):
    ctx["world"]["home"] = HOME_NO_DATED


@given("the Criterion home page links the October 31 leaving page")
def home_dated(ctx):
    ctx["world"]["home"] = (FIX / "home-2026-10-01.html").read_text()
    ctx["rs"].get(BASE + "/discover/leaving-october-31", body=(FIX / "leaving-october-31.html").read_text())
    ctx["rs"].get(JW_PLAYLIST_URL.format("0WbeKrrA"), json=_load("jw-playlist.0WbeKrrA.full.json"))


@given("the Criterion home page answers 500")
def home_500(ctx):
    ctx["world"]["home_status"] = 500


@given("the Criterion catalog answers 500")
def catalog_500(ctx):
    ctx["world"]["catalog_status"] = 500


@given(parsers.parse('Criterion calls "{title_year}" "{mediaid}"'))
def criterion_calls(ctx, title_year, mediaid):
    ctx["ids"][parse_titles(f'"{title_year}"')[0].title] = mediaid


def _seed(ctx, films):
    """As `criterion bridge --apply` leaves them: each film holds its mediaid."""
    for f in films:
        fid = ctx["repo"].upsert_film(f)
        ctx["repo"].set_external_id(fid, "criterion", _mediaid(ctx, f.title), TODAY - timedelta(days=30))


@given(parsers.re(r"the last walk listed (?P<films>.+?) (?P<days>\d+) days ago(?P<old> under its old link)?$"))
def last_walk(ctx, films, days, old):
    flist = parse_titles(films)
    walked = TODAY - timedelta(days=int(days))
    if old:
        ctx["repo"].record_catalog(SOURCE, flist, walked)  # the VHX-era shape: old link, no mediaid
    else:
        _seed(ctx, flist)
        for f in flist:
            m = _mediaid(ctx, f.title)
            ctx["repo"].record_listing(_fid(ctx, f"{f.title} ({f.year})"), SOURCE, f"{BASE}/films/{m}/x", walked)
    ctx["repo"].set_meta("films_fetched_at", walked.isoformat())


@given(parsers.parse("Criterion lists my films {films}"))
def lists_my_films(ctx, films):
    flist = parse_titles(films)
    _seed(ctx, flist)
    ctx["world"]["items"] = [_item(_mediaid(ctx, f.title), f.title, f.year) for f in flist]


@given(parsers.parse('Criterion also lists a new film "{title}" ({year:d}) as "{mediaid}"'))
def lists_new(ctx, title, year, mediaid):
    ctx["world"]["items"].append(_item(mediaid, title, year))


@given(parsers.parse('the catalog also carries the series "{title}" as "{mediaid}"'))
def lists_series(ctx, title, mediaid):
    ctx["world"]["items"].append(
        {"contentType": "series", "duration": 0, "mediaid": mediaid, "release_date": "1972-01-01", "title": title}
    )


@given(parsers.parse('JW Player serves its captured record for "{mediaid}"'))
def jw_captured(ctx, mediaid):
    ctx["world"]["jw"][mediaid] = _load(f"jw-media.{mediaid}.json")


@given(parsers.parse('JW Player answers 500 for "{mediaid}"'))
def jw_500(ctx, mediaid):
    ctx["world"]["jw_status"][mediaid] = 500


@given(parsers.parse('"{title_year}" is leaving "{label}"'))
def is_leaving_given(ctx, title_year, label):
    conn = sqlite3.connect(ctx["repo"].db_path)
    conn.execute("UPDATE listings SET leaving_date = ? WHERE film_id = ? AND source = 'criterion'",
                 (label, _fid(ctx, title_year)))
    conn.commit()
    conn.close()


@given(parsers.parse('"{title_year}" is on the watchlist'))
def on_watchlist(ctx, title_year):
    f = parse_titles(f'"{title_year}"')[0]
    fid = ctx["repo"].film_id_by_key(f.key) or ctx["repo"].create_film(f)
    ctx["repo"].toggle_watchlist(fid, TODAY)


@given(parsers.parse('I have rated "{title}"'))
def rated(ctx, title):
    assert ctx["repo"].set_rating(_fid(ctx, title), 7, TODAY) is True


@given("OMDb knows every film")
def omdb_ok(ctx):
    ctx["rs"].get(OMDB_URL, json=FOUND)


@given("the resolver keys every film")
def resolver_keys_all(ctx):
    """A pool that answers any query with a synthetic keyed candidate, so the OMDb loop
    has an IMDb id to look up (T5: no id, no OMDb record)."""

    class AllFetcher:
        def fetch(self, q):
            tt = f"tt{abs(hash(q.title)) % 9000000:07d}"
            tid = abs(hash(q.title)) % 90000
            # release_date echoes the query's own year — a commerce (no-listing) film like a
            # Metacritic promotion gets its year adopted from this TMDB response (key_film →
            # movie_year), so a mismatched hardcoded year here would rename its key underfoot.
            ctx["rs"].add(
                responses.GET, f"{TMDB_API}/movie/{tid}", json={"id": tid, "release_date": f"{q.year or 1900}-01-01"}
            )
            return [Candidate(tt, tid, (q.title,), q.year, "Someone", 100, 5000, "movie", True, True)]

    ctx["pool"] = AllFetcher()


@given("the resolver finds nothing")
def resolver_nothing(ctx):
    class EmptyFetcher:
        def fetch(self, q):
            return []

    ctx["pool"] = EmptyFetcher()


@given(parsers.parse('"{title_year}" is already keyed to imdb "{tt}"'))
def already_keyed(ctx, title_year, tt):
    """A film keyed on a prior night — `--ratings-only` never keys, so a ratings-only scenario
    needs its film pre-keyed to have anything for the OMDb-by-id loop to look up."""
    ctx["repo"].set_external_id(_fid(ctx, title_year), "imdb", tt, TODAY)


@given("OMDb answers once then reports the request limit")
def omdb_quota(ctx):
    ctx["rs"].get(OMDB_URL, json=FOUND)
    ctx["rs"].get(OMDB_URL, json=LIMIT, status=401)


@given("OMDb rejects the API key")
def omdb_auth(ctx):
    ctx["rs"].get(OMDB_URL, json={"Response": "False", "Error": "Invalid API key!"}, status=401)


@given("OMDb answers once then errors repeatedly")
def omdb_repeated_failures(ctx):
    calls = {"n": 0}

    def cb(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return (200, {}, json.dumps(FOUND))
        return (500, {}, "boom")

    ctx["rs"].add_callback(responses.GET, OMDB_URL, callback=cb)


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


@given("the walk's write fails at its last step")
def write_fails(ctx):
    def boom(c, leaving, day):
        raise RuntimeError("disk full")

    ctx["monkeypatch"].setattr(Repository, "_walk_leaving", staticmethod(boom))
    real_key_films = sync_module.key_films

    def watching_key_films(*args, **kwargs):
        ctx["at_keying"] = _snapshot(ctx)
        return real_key_films(*args, **kwargs)

    ctx["monkeypatch"].setattr(sync_module, "key_films", watching_key_films)


def _run(ctx, **kw):
    ctx["before"] = _snapshot(ctx)
    ctx["result"] = sync(
        ctx["repo"],
        "key",
        ctx["day"],
        session=requests.Session(),
        site=HttpCriterionSite(requests.Session(), sleep=lambda _s: None),
        log=lambda m: None,
        fetcher=ctx.get("pool"),
        tmdb_token="tok" if ctx.get("pool") else None,
        **kw,
    )


@when("I sync")
def run_sync(ctx):
    _run(ctx)


@when("I sync again the next day")
def run_sync_next_day(ctx):
    ctx["day"] = ctx["day"] + timedelta(days=1)
    _run(ctx)


@when("I sync with a metacritic archive")
def run_sync_with_archive(ctx):
    _run(ctx, config_dir=ctx["config_dir"])


@when("I sync with a notifier")
def run_sync_notify(ctx):
    ctx["sent"] = []
    _run(ctx, notifier=lambda t, b: ctx["sent"].append((t, b)))


def _chain(ctx, fail=False):
    from movie_brain.application.catch_up import CatchUpReport

    def chain(repo, tmdb):
        ctx.setdefault("chain_runs", []).append(repo.summary("criterion")["rated"])
        if fail:
            raise RuntimeError("chain exploded")
        return CatchUpReport()

    return chain


@when("I sync with a catch-up chain")
def run_with_chain(ctx):
    _run(ctx, catch_up=_chain(ctx))


@when("I sync with a catch-up chain that fails")
def run_with_failing_chain(ctx):
    _run(ctx, catch_up=_chain(ctx, fail=True))


@when("I sync with --ratings-only and a catch-up chain")
def run_ro_with_chain(ctx):
    _run(ctx, ratings_only=True, catch_up=_chain(ctx))


@when("I run the after-add enrichment with a catch-up chain")
def run_after_add(ctx):
    _run(ctx, skip_catalog=True, catch_up=_chain(ctx))


@when("I sync with --ratings-only")
def run_ro(ctx):
    _run(ctx, ratings_only=True)


@then(parsers.parse("the catch-up chain ran once, after {n:d} films had OMDb ratings"))
def chain_ran(ctx, n):
    assert ctx.get("chain_runs") == [n]


@then("the catch-up chain never ran")
def chain_never(ctx):
    assert "chain_runs" not in ctx


@then("the sync result carries the catch-up report")
def result_carries(ctx):
    assert ctx["result"].catch_up is not None


@then(parsers.parse("the exit code is {code:d}"))
def exit_code(ctx, code):
    assert isinstance(ctx["result"], SyncResult)
    assert ctx["result"].exit_code == code


@then(parsers.parse("the sync reports criterion arrived {a:d}, left {d:d}, to review {r:d}"))
def criterion_counts(ctx, a, d, r):
    res = ctx["result"]
    assert res.criterion_walked is True
    assert (res.criterion_arrived, res.criterion_departed, res.criterion_reviews) == (a, d, r)


@then("the sync reports the Criterion walk failed")
def criterion_failed(ctx):
    assert ctx["result"].criterion_failed is True and ctx["result"].criterion_walked is False


@then("Criterion was never contacted")
def no_criterion(ctx):
    assert not any(
        c.request.url.startswith((BASE, "https://cdn.jwplayer.com")) for c in ctx["rs"].calls
    )


@then(parsers.parse("{n:d} films are current"))
def n_current(ctx, n):
    assert len(ctx["repo"].current_films(SOURCE)) == n


@then(parsers.parse("{n:d} films have OMDb ratings"))
def n_rated(ctx, n):
    assert sum(1 for v in ctx["repo"].list_views(SOURCE) if v.found is True) == n


@then("films_fetched_at is today")
def fetched_today(ctx):
    assert ctx["repo"].get_meta("films_fetched_at") == TODAY.isoformat()


@then(parsers.parse('"{title_year}" is leaving "{label}"'))
def is_leaving(ctx, title_year, label):
    assert ctx["repo"].get_view(_fid(ctx, title_year)).leaving_date == label


@then(parsers.parse('"{title_year}" is not leaving'))
def not_leaving(ctx, title_year):
    assert _q(ctx, "SELECT leaving_date FROM listings WHERE film_id = ? AND source = 'criterion'",
              _fid(ctx, title_year)) == [(None,)]


@then(parsers.parse('"{title_year}" is still in the database'))
def film_kept(ctx, title_year):
    assert _fid(ctx, title_year) is not None


@then(parsers.parse('"{title_year}" is in the dashboard marked departed'))
def film_departed(ctx, title_year):
    f = parse_titles(f'"{title_year}"')[0]
    views = {v.title: v.departed for v in ctx["repo"].list_views(SOURCE)}
    assert views.get(f.title) is True


@then(parsers.parse('one notification was sent naming "{text}"'))
def one_notification(ctx, text):
    assert len(ctx["sent"]) == 1 and text in ctx["sent"][0][1]


@then(parsers.parse("there are {n:d} open criterion reviews"))
def n_open_criterion(ctx, n):
    assert len(ctx["repo"].open_reviews("criterion")) == n


@then(parsers.parse('there is {n:d} open criterion "{reason}" review for "{mediaid}"'))
def n_open_reason(ctx, n, reason, mediaid):
    rows = [r for r in ctx["repo"].open_reviews("criterion") if r["reason"] == reason and r["value"] == mediaid]
    assert len(rows) == n


@then(parsers.parse('the Criterion listing of "{title_year}" was last seen {days:d} days ago'))
def last_seen(ctx, title_year, days):
    assert _q(ctx, "SELECT last_seen FROM listings WHERE film_id = ? AND source = 'criterion'",
              _fid(ctx, title_year)) == [((TODAY - timedelta(days=days)).isoformat(),)]


@then("when the keying step began, Criterion was exactly as it was before the sync")
def unchanged_at_keying(ctx):
    assert ctx["at_keying"] == ctx["before"]


@then(parsers.parse('no film is titled "{title}"'))
def no_film_titled(ctx, title):
    assert _q(ctx, "SELECT COUNT(*) FROM films WHERE title = ?", title) == [(0,)]


@then(parsers.parse('JW Player was asked about "{mediaid}" {n:d} time'))
def jw_asked(ctx, mediaid, n):
    assert ctx["world"]["jw_calls"].count(mediaid) == n


@then("the quota flag is set")
def quota_flag(ctx):
    assert ctx["result"].quota_hit is True


@then("the failing flag is set")
def failing_flag(ctx):
    assert ctx["result"].failing is True


@then(parsers.parse('the repository holds a film for key "{key}"'))
def holds_film_key(ctx, key):
    assert ctx["repo"].film_id_by_key(key) is not None


@then(parsers.parse('the film for key "{key}" has an OMDb rating'))
def film_has_omdb(ctx, key):
    fid = ctx["repo"].film_id_by_key(key)
    assert fid is not None
    assert _q(ctx, "SELECT found FROM omdb WHERE film_id = ?", fid) == [(1,)]
```

Note for the implementer: the "--ratings-only without a stored catalog fails" scenario has no Criterion films at all, so the walk's bridge guard (Task 4) never fires in this file: every scenario that lists films seeds their mediaids first.

- [ ] **Step 2: Move the TMDB and watchlist suites onto a fake site**

These two suites test the TMDB step, not Criterion; their catalog becomes a `FakeSite` listing films seeded as the bridge leaves them.

In `tests/features/tmdb.feature` and `tests/features/watchlist.feature`, delete the Background line `    And the Criterion browse page exposes a token`.

In `tests/step_defs/test_tmdb.py`:
- Delete the import `from movie_brain.infrastructure.criterion import API_URL, BROWSE_URL`, add `from criterion_fakes import FakeSite, seed_known` (third-party block, beside `pytest`), and delete the `movie_item` function.
- Replace the `ctx` fixture, the `token` step and the `catalog` step with:

```python
@pytest.fixture
def ctx(repo, monkeypatch):
    rs = responses.RequestsMock(assert_all_requests_are_fired=False)
    rs.start()
    site = FakeSite()
    # These scenarios test the TMDB step. Criterion is a fake listing the films a scenario
    # names, each holding its mediaid as `criterion bridge --apply` leaves it.
    monkeypatch.setattr("movie_brain.application.sync.HttpCriterionSite", lambda *a, **kw: site)
    yield {"repo": repo, "rs": rs, "result": None, "flags": {}, "site": site}
    rs.stop()
    rs.reset()


@given(parsers.parse("the Criterion catalog has films {films}"))
def catalog(ctx, films):
    ctx["site"].items = seed_known(ctx["repo"], parse_titles(films), TODAY - timedelta(days=30))
```

In `tests/step_defs/test_watchlist.py` make the same three changes (delete the `criterion` import and `movie_item`, add `from criterion_fakes import FakeSite, seed_known`, and replace `ctx`, `token` and `catalog` with exactly the two definitions above — the `ctx` dict there also keeps its `"flags": {}` key).

- [ ] **Step 3: Update the CLI tests (failing)**

In `tests/unit/test_cli.py`, replace `test_sync_propagates_exit_code` with:

```python
def test_sync_propagates_exit_code_and_keeps_full_as_a_habit(config_dir, monkeypatch):
    (config_dir / "omdb-api-key.txt").write_text("k")
    calls = {}

    def fake_sync(repo, api_key, today, **kw):
        calls.update(kw, api_key=api_key)
        return SyncResult(1, 0, 0, False, False)

    monkeypatch.setattr("movie_brain.cli.sync", fake_sync)
    r = runner.invoke(app, ["sync", "--full"])
    assert r.exit_code == 1
    assert "force_full" not in calls and calls["ratings_only"] is False and calls["api_key"] == "k"


def test_sync_prints_the_criterion_line(config_dir, monkeypatch):
    (config_dir / "omdb-api-key.txt").write_text("k")
    monkeypatch.setattr(
        "movie_brain.cli.sync",
        lambda repo, api_key, today, **kw: SyncResult(
            0, 10, 2, False, False, criterion_walked=True, criterion_arrived=3, criterion_departed=2,
            criterion_reviews=1,
        ),
    )
    r = runner.invoke(app, ["sync"])
    assert r.exit_code == 0, r.output
    assert "criterion — arrived 3 · left 2 · to review 1" in r.output
    assert "full walk" not in r.output and "not asked" not in r.output


def test_sync_says_when_the_criterion_walk_failed(config_dir, monkeypatch):
    (config_dir / "omdb-api-key.txt").write_text("k")
    monkeypatch.setattr(
        "movie_brain.cli.sync",
        lambda repo, api_key, today, **kw: SyncResult(1, 10, 2, False, False, criterion_failed=True),
    )
    r = runner.invoke(app, ["sync"])
    assert r.exit_code == 1
    assert "nothing written for Criterion" in r.output
```

and in `_capture_sync` change `SyncResult(0, False, 10, 2, False, False, catch_up=...)` to `SyncResult(0, 10, 2, False, False, catch_up=...)`.

- [ ] **Step 4: Run them to verify they fail**

Run: `uv run pytest tests/step_defs/test_sync.py tests/step_defs/test_tmdb.py tests/step_defs/test_watchlist.py tests/unit/test_cli.py -q -x`
Expected: FAIL — `sync()` got an unexpected keyword argument `site` (or `SyncResult` positional mismatch).

- [ ] **Step 5: Implement `sync.py`**

Replace the whole of `src/movie_brain/application/sync.py` with:

```python
from __future__ import annotations

import sqlite3
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

import requests

from movie_brain.application.availability import TmdbStepResult, tmdb_step
from movie_brain.application.catch_up import CatchUpReport
from movie_brain.application.criterion_walk import CriterionSite, WalkReport, walk_criterion
from movie_brain.application.keying import KeyStepResult, key_films
from movie_brain.application.metacritic import DEFAULT_TOP_N, MC_TOP_N_KEY, promote_top_n
from movie_brain.infrastructure.criterion_site import HttpCriterionSite
from movie_brain.infrastructure.database import Repository
from movie_brain.infrastructure.metacritic import CARDS_PER_PAGE
from movie_brain.infrastructure.omdb import AuthError, OmdbClient, QuotaExceeded
from movie_brain.infrastructure.thumbprint_fetch import CandidateFetcher, session_fetcher
from movie_brain.infrastructure.tmdb import AuthError as TmdbAuthError
from movie_brain.infrastructure.tmdb import TmdbArbiter, TmdbClient

SOURCE = "criterion"
MAX_CONSECUTIVE_FAILURES = 5


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


@dataclass(frozen=True)
class SyncResult:
    exit_code: int
    films: int
    looked_up: int
    quota_hit: bool
    failing: bool
    tmdb_matched: int = 0
    tmdb_missed: int = 0
    tmdb_refreshed: int = 0
    tmdb_watchlist_refreshed: int = 0
    mc_promoted: int = 0
    tmdb_first_checked: int = 0
    tmdb_reviewed: int = 0  # films the resolver sent to a durable A/B/C review row
    omdb_unkeyed: int = 0  # films skipped by the OMDb loop for holding no IMDb id (never title-searched)
    catch_up: CatchUpReport | None = None  # the chain at the tail (credits, vectors, store ids, trailers)
    criterion_walked: bool = False  # the Criterion walk ran and committed tonight
    criterion_failed: bool = False  # it ran and wrote nothing (spec D6); the rest of the night still ran
    criterion_arrived: int = 0
    criterion_departed: int = 0
    criterion_reviews: int = 0
    criterion_skipped: int = 0  # new films not asked about tonight (no resolver, or its lookups failed)


def _with_walk(result: SyncResult, walk: WalkReport | None, failed: bool) -> SyncResult:
    if walk is None:
        return replace(result, criterion_failed=failed)
    return replace(
        result,
        criterion_walked=True,
        criterion_arrived=walk.arrived,
        criterion_departed=walk.departed,
        criterion_reviews=walk.reviews,
        criterion_skipped=walk.skipped,
    )


def _resolve_imdb_id(
    repo: Repository, tmdb: TmdbClient | None, film_id: int, today: date, log: Callable[[str], None]
) -> str | None:
    """IMDb id for a film: stored `imdb` external id, else resolved once via its TMDB link
    and stored. None (no link, TMDB has none, or TMDB weather) → the OMDb loop skips this film
    for the run (counted in `SyncResult.omdb_unkeyed`) instead of falling back to a title
    search; OMDb is fetched by IMDb id only (thumbprint T5)."""
    ids = repo.external_ids_for(film_id)
    if "imdb" in ids:
        return ids["imdb"]
    if tmdb is None or "tmdb" not in ids:
        return None
    try:
        imdb_id = tmdb.imdb_id(int(ids["tmdb"]))
    except (requests.RequestException, TmdbAuthError) as exc:
        log(f"imdb id lookup failed for film {film_id}: {exc}")
        return None
    if imdb_id is None:
        return None
    try:
        repo.set_external_id(film_id, "imdb", imdb_id, today)
    except sqlite3.IntegrityError:
        holder = repo.film_id_for_external("imdb", imdb_id)
        log(f"imdb id {imdb_id} already claimed by film {holder}; film {film_id} skipped this run (unkeyed)")
        return None
    return imdb_id


def sync(
    repo: Repository,
    api_key: str,
    today: date,
    *,
    session: requests.Session | None = None,
    ratings_only: bool = False,
    tmdb_token: str | None = None,
    config_dir: Path | None = None,
    notifier: Callable[[str, str], None] | None = None,
    fetcher: CandidateFetcher | None = None,
    skip_catalog: bool = False,
    catch_up: Callable[[Repository, TmdbClient | None], CatchUpReport | None] | None = None,
    site: CriterionSite | None = None,
    log: Callable[[str], None] = _stderr,
) -> SyncResult:
    """One night. Step 1 is the Criterion walk (`application/criterion_walk.py`, spec 2026-10-01):
    every catalog item matched to a film by its mediaid, unknown ones resolved and gated, all of it
    written in one transaction. A walk that fails writes nothing for Criterion; the rest of the
    night still runs and the sync exits 1 (D6 — one source's weather never breaks another). Every
    sync walks the whole catalog: there is no cheap check any more (D11).

    `skip_catalog` is the AFTER-ADD mode (owner ruling 2026-09-20: a film gets its full
    enrichment when it is added): a verb that has just created films runs everything a sync does
    to a new film — keying, OMDb, the provider first-check, the catch-up chain — without walking
    Criterion, promoting Metacritic titles or starting the weekly provider refresh. `catch_up` is
    the chain itself (`application/catch_up.py`), handed in by the CLI so that nothing here builds
    a CheapCharts client or loads a model; it runs last, under its own tripwire. `site` is the
    Criterion site the walk reads (default: the live `HttpCriterionSite` on `session`)."""
    session = session or requests.Session()
    if ratings_only and not repo.current_films(SOURCE):
        log("no stored catalog — run once without --ratings-only first")
        return SyncResult(1, 0, 0, False, False)

    tmdb_client = TmdbClient(tmdb_token, session=session) if tmdb_token else None
    arbiter = TmdbArbiter(tmdb_client) if tmdb_client is not None else None
    omdb_client = OmdbClient(api_key, session=session)
    cache = None
    if fetcher is None and config_dir is not None:
        fetcher, cache = session_fetcher(config_dir, tmdb_client, omdb_client)

    walk: WalkReport | None = None
    walk_failed = False
    if not ratings_only and not skip_catalog:
        try:
            walk = walk_criterion(repo, site or HttpCriterionSite(session), fetcher, tmdb_client, today, log=log)
        except Exception as exc:  # noqa: BLE001 — one source's weather never breaks another (spec D6)
            walk_failed = True
            log(f"criterion walk failed — nothing written for Criterion; the rest of the sync runs: {exc}")

    mc_promoted = 0
    if not ratings_only and not skip_catalog and config_dir is not None:
        try:
            n = int(repo.get_meta(MC_TOP_N_KEY) or DEFAULT_TOP_N)
            promote = promote_top_n(
                repo, config_dir, today, n, arbiter=arbiter, fetcher=fetcher, tmdb=tmdb_client, log=log
            )
            mc_promoted = promote.promoted
            if promote.exit_code == 0 and promote.available < promote.n:
                pages = -(-promote.n // CARDS_PER_PAGE)
                log(
                    f"metacritic archive holds {promote.available} of top-{promote.n} titles — "
                    f"run: movie-brain metacritic crawl --pages {pages}"
                )
        except Exception as exc:  # noqa: BLE001 — the dial must never break the sync
            log(f"metacritic promotion failed: {exc}")

    # Keying runs BEFORE the OMDb loop: a film keyed this run is looked up by its own IMDb
    # id in the same run, instead of waiting for the next one (thumbprint T5, memo step 5).
    keyed = KeyStepResult()
    if not ratings_only:
        try:
            keyed = key_films(repo, fetcher, tmdb_client, today, log)
        except Exception as exc:  # noqa: BLE001 — keying must never break the rest of the sync
            log(f"keying step failed: {exc}")
    if cache is not None and cache.misses:
        cache.save()

    looked_up = 0
    unkeyed = 0
    quota_hit = False
    consecutive = 0
    lookup_queue = repo.films_needing_lookup(SOURCE, today) + repo.films_needing_lookup_discovery(SOURCE, today)
    for film_id, film in lookup_queue:
        if quota_hit or consecutive >= MAX_CONSECUTIVE_FAILURES:
            break
        try:
            imdb_id = _resolve_imdb_id(repo, tmdb_client, film_id, today, log)
            if imdb_id is None:
                # An unkeyed work is never enriched by title search (memo §1): OMDb's `t=`
                # accepted stubs for films it did not have. The film re-enters this queue
                # every run at zero API cost until the resolver keys it.
                unkeyed += 1
                continue
            rating = omdb_client.lookup_by_imdb(imdb_id)
        except QuotaExceeded:
            quota_hit = True
            continue
        except AuthError as exc:
            log(f"OMDb rejected the API key: {exc}")
            return _with_walk(
                SyncResult(2, len(repo.current_films(SOURCE)), looked_up, False, False, mc_promoted=mc_promoted),
                walk,
                walk_failed,
            )
        except requests.RequestException as exc:
            log(f"lookup failed for {film.title!r}: {exc}")
            consecutive += 1
            continue
        repo.upsert_omdb(film_id, rating, today)
        looked_up += 1
        consecutive = 0

    failing = consecutive >= MAX_CONSECUTIVE_FAILURES
    if quota_hit:
        log("OMDb daily quota reached — partial ratings saved; next run resumes.")
    if failing:
        log("OMDb lookups failing repeatedly — partial ratings saved; next run resumes.")

    tmdb = TmdbStepResult()
    if ratings_only:
        log("ratings-only run — skipping TMDB availability step")
    elif tmdb_client is None:
        log("no TMDB token — skipping availability step")
    else:
        try:
            tmdb = tmdb_step(repo, tmdb_client, today, weekly=not skip_catalog, log=log)
        except Exception as exc:  # noqa: BLE001 — one source failing must never break the others
            log(f"TMDB availability step failed: {exc}")

    caught_up = None
    if catch_up is not None and not ratings_only:
        try:
            caught_up = catch_up(repo, tmdb_client)
        except Exception as exc:  # noqa: BLE001 — the chain must never change the sync's outcome
            log(f"catch-up chain failed: {exc}")

    if notifier is not None:
        try:
            arrivals = repo.watchlist_transitions_on(today)
            if arrivals:
                listed = " · ".join(f"{title} on {service}" for title, service in arrivals[:4])
                if len(arrivals) > 4:
                    listed += f" · … and {len(arrivals) - 4} more"
                noun = "arrival" if len(arrivals) == 1 else "arrivals"
                notifier("movie-brain", f"{len(arrivals)} watchlist {noun}: {listed}")
        except Exception as exc:  # noqa: BLE001 — alerts must never affect the sync outcome
            log(f"notification failed: {exc}")

    return _with_walk(
        SyncResult(
            1 if walk_failed else 0,
            len(repo.current_films(SOURCE)),
            looked_up,
            quota_hit,
            failing,
            tmdb_matched=keyed.keyed,
            tmdb_missed=keyed.reviewed + keyed.held + keyed.failed,
            tmdb_refreshed=tmdb.refreshed,
            tmdb_watchlist_refreshed=tmdb.watchlist_refreshed,
            mc_promoted=mc_promoted,
            tmdb_first_checked=tmdb.first_checked,
            tmdb_reviewed=keyed.reviewed,
            omdb_unkeyed=unkeyed,
            catch_up=caught_up,
        ),
        walk,
        walk_failed,
    )
```

- [ ] **Step 6: Implement the CLI**

In `src/movie_brain/cli.py`, replace `sync_cmd` (the whole function) with:

```python
def _criterion_line(result: SyncResult) -> str | None:
    """Spec D11's one line, plus how many new films waited unasked when there were any."""
    if result.criterion_failed:
        return "criterion — the walk failed; nothing written for Criterion (the reason is above)"
    if not result.criterion_walked:
        return None
    line = (
        f"criterion — arrived {result.criterion_arrived} · left {result.criterion_departed} · "
        f"to review {result.criterion_reviews}"
    )
    if result.criterion_skipped:
        line += f" · not asked tonight {result.criterion_skipped}"
    return line


@app.command("sync")
def sync_cmd(
    full: Annotated[
        bool, typer.Option("--full", help="Kept for habit — every sync walks the whole catalog.")
    ] = False,
    ratings_only: Annotated[
        bool, typer.Option("--ratings-only", help="Skip Criterion; refresh OMDb ratings only.")
    ] = False,
) -> None:
    """Refresh the catalog and OMDb ratings."""
    if full and ratings_only:
        err.print("--full and --ratings-only are mutually exclusive")
        raise typer.Exit(2)
    cfg = load_config()
    api_key = load_api_key(cfg)
    if not api_key:
        err.print(f"no OMDb key: set OMDB_API_KEY or write {cfg.key_file}")
        raise typer.Exit(2)
    result = sync(
        _repo(),
        api_key,
        date.today(),
        ratings_only=ratings_only,
        tmdb_token=load_tmdb_token(cfg),
        config_dir=cfg.config_dir,
        notifier=notify,
        catch_up=_catch_up_chain(),
    )
    console.print(
        f"films: {result.films} · looked up: {result.looked_up} · "
        f"availability refreshed: {result.tmdb_refreshed} · promoted: {result.mc_promoted} · "
        f"keyed: {result.tmdb_matched} · review: {result.tmdb_reviewed}"
    )
    line = _criterion_line(result)
    if line is not None:
        console.print(line, markup=False, highlight=False)
    if result.catch_up is not None:
        console.print(f"caught up — {result.catch_up.line()}")
    raise typer.Exit(result.exit_code)
```

Make sure `SyncResult` is imported in `cli.py` from `movie_brain.application.sync` (it is imported beside `sync` today; add it if not).

- [ ] **Step 7: Delete the VHX reader and its tests**

```bash
git rm src/movie_brain/infrastructure/criterion.py tests/unit/test_criterion.py
grep -rn "infrastructure.criterion import\|infrastructure import criterion\b\|merge_yearless\|films_raw_total\|full_walk\|force_full" src tests scripts
```

Expected grep output: only `src/movie_brain/domain/models.py` (the `merge_yearless` definition) and `tests/unit/test_models.py` (its tests) — both stay (D11). Anything else is a leftover to remove.

- [ ] **Step 8: Run the suites to verify they pass**

Run: `uv run pytest tests/step_defs/test_sync.py tests/step_defs/test_tmdb.py tests/step_defs/test_watchlist.py tests/unit/test_cli.py tests/step_defs/test_criterion_walk.py -q && uv run mypy src`
Expected: all pass; mypy shows only main's 3 pre-existing errors.

- [ ] **Step 9: Run the whole suite**

Run: `uv run pytest -q`
Expected: green. The count moves from 1985: −the deleted `test_criterion.py` tests and −5 retired sync scenarios, + Tasks 1–5's new tests. Record the number in the ledger.

- [ ] **Step 10: Commit**

```bash
git add -A src/movie_brain/application/sync.py src/movie_brain/cli.py tests/features/sync.feature tests/step_defs/test_sync.py tests/step_defs/test_tmdb.py tests/step_defs/test_watchlist.py tests/features/tmdb.feature tests/features/watchlist.feature tests/unit/test_cli.py
git commit -m "Sync walks the relaunched Criterion site again, and a failed walk no longer stops the rest of the night — story 1 and story 8

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: `review resolve` on a criterion row

**Files:**
- Create: `src/movie_brain/application/criterion_review.py`
- Modify: `src/movie_brain/application/review.py`, `src/movie_brain/cli.py`
- Create: `tests/features/criterion_review.feature`
- Modify: `tests/step_defs/test_criterion_walk.py` (second `scenarios(...)` line + new steps), `tests/unit/test_cli.py`

**Interfaces:**
- Consumes: `gate_ladder` (Task 2), `bind_criterion_mediaid`, `create_criterion_film` (Task 3), `parse_criterion_detail`, `AUTHORITY` (Task 4), `lists.find_holder`, `lists.corpus_veto`, `lists._veto_label`, `lists._catalog`, `lists._key_new_film`.
- Produces: `def resolve_criterion_row(repo: Repository, row: dict[str, object], *, today: date, film_id: int | None = None, create: bool = False, tt: str | None = None, client: TmdbClient | None = None, warn: Callable[[str], None]) -> str` — raises `ValueError` on every refusal (the CLI prints it, exit 1, the row stays open); an outcome that created a film starts with `created film `.

- [ ] **Step 1: Write the failing scenarios**

Create `tests/features/criterion_review.feature`:

```gherkin
Feature: Settling a criterion review row (spec 2026-10-01 D9, story 7)
  `--film`, `--create` and `--tt` give a film the mediaid, so the next walk lists it there;
  `--dismiss` is a standing decision. A gate that finds a holder refuses, naming the film.
  On these human paths a mere resemblance (gate 3) warns and never refuses (ledger L1).

  Scenario: --film gives that film the mediaid, and the next walk lists it there
    Given a film "Ghost Entry" (2020) holding no ids
    And Criterion lists "Ghost Entry" (2020) as "Gh0stEnt"
    When the walk runs
    And the owner resolves the review for "Gh0stEnt" with --film "Ghost Entry"
    And the walk runs again the next day
    Then the film "Ghost Entry" holds criterion id "Gh0stEnt"
    And the film "Ghost Entry" has a criterion claim "Gh0stEnt" titled "Ghost Entry" for 2020
    And the film "Ghost Entry" is current on Criterion
    And the film "Ghost Entry" arrived on Criterion today
    And there is no open criterion review for "Gh0stEnt"

  Scenario: --film on the bridge's id-conflict row is refused, naming the film that holds the id
    Given the last walk listed "Test Pattern" (2019) as "gpRRkq27"
    And a film "Test Pattern Twin" (2019) holding no ids
    And an open criterion "id-conflict" review names "gpRRkq27" for "Test Pattern Twin"
    When the owner resolves the review for "gpRRkq27" with --film "Test Pattern Twin"
    Then the resolution is refused naming the film "Test Pattern"
    And there is 1 open criterion "id-conflict" review for "gpRRkq27"

  Scenario: --create mints the film under Criterion's title, year and director; the next walk lists it
    Given Criterion lists "K-ON! The Movie" (2011) as "VBLiQBrA"
    And JW knows "VBLiQBrA" as "K-ON! The Movie" directed by "Naoko Yamada"
    And the resolver finds nothing for "K-ON! The Movie"
    When the walk runs
    And the owner resolves the review for "VBLiQBrA" with --create
    And the walk runs again the next day
    Then there is 1 film titled "K-ON! The Movie"
    And the film "K-ON! The Movie" has year 2011 and director "Naoko Yamada"
    And the film "K-ON! The Movie" holds criterion id "VBLiQBrA"
    And the film "K-ON! The Movie" arrived on Criterion today

  Scenario: --create is refused naming the film that already holds the key; the row stays open
    Given a film "K-ON! The Movie" (2011) holding no ids
    And Criterion lists "K-ON! The Movie" (2011) as "VBLiQBrA"
    And JW knows "VBLiQBrA" as "K-ON! The Movie" directed by "Naoko Yamada"
    And the resolver finds nothing for "K-ON! The Movie"
    When the walk runs
    And the owner resolves the review for "VBLiQBrA" with --create
    Then the resolution is refused naming the film "K-ON! The Movie"
    And there is 1 open criterion "no-match" review for "VBLiQBrA"
    And there is 1 film titled "K-ON! The Movie"

  Scenario: --tt naming a film I hold binds the mediaid to it
    Given a film "Barry Lyndon" (1975) holding imdb "tt9000433"
    And Criterion lists "Barry Lyndon" (1975) as "aAUEybAm"
    And JW knows "aAUEybAm" as "Barry Lyndon" directed by "Stanley Kubrick"
    And the resolver finds nothing for "Barry Lyndon"
    When the walk runs
    And the owner resolves the review for "aAUEybAm" with --tt "tt9000433"
    Then there is 1 film titled "Barry Lyndon"
    And the film "Barry Lyndon" holds criterion id "aAUEybAm"
    And there is no open criterion review for "aAUEybAm"

  Scenario: --tt naming a work I lack creates it under TMDB's title, born keyed
    Given Criterion lists "Le Trou" (1960) as "LeTrou60"
    And JW knows "LeTrou60" as "Le Trou" directed by "Jacques Becker"
    And the resolver finds nothing for "Le Trou"
    And TMDB knows "tt9000501" as film 9501 "The Hole" (1960)
    When the walk runs
    And the owner resolves the review for "LeTrou60" with --tt "tt9000501"
    Then the film "The Hole" holds criterion id "LeTrou60"
    And the film "The Hole" holds imdb "tt9000501"
    And the film "The Hole" has year 1960 and director "Jacques Becker"
    And the film "The Hole" has a criterion claim "LeTrou60" titled "Le Trou" for 1960

  Scenario: A resemblance does not stop the owner — gate 3 warns on a human path (ledger L1, The Beast 2023)
    Given a film "The Beast" (1975) holding no ids
    And Criterion lists "The Beast" (2023) as "1n2wLfer"
    And JW knows "1n2wLfer" as "The Beast" directed by "Bertrand Bonello"
    And the resolver matches "The Beast" to "tt9000301" (tmdb 9301) directed by "Bertrand Bonello"
    And TMDB knows "tt9000301" as film 9301 "The Beast" (2023)
    When the walk runs
    Then there is 1 open criterion "corpus-veto" review for "1n2wLfer"
    When the owner resolves the review for "1n2wLfer" with --create
    Then there are 2 films titled "The Beast"
    And the resolution warned that it resembles "'The Beast' (1975)"
    And the 2023 film "The Beast" holds criterion id "1n2wLfer"
    And the 2023 film "The Beast" holds imdb "tt9000301"

  Scenario: --none is refused on a criterion row
    Given Criterion lists "Ghost Entry" (2020) as "Gh0stEnt"
    When the walk runs
    And the owner resolves the review for "Gh0stEnt" with --none
    Then the resolution is refused
    And there is 1 open criterion "no-record" review for "Gh0stEnt"
```

In `tests/step_defs/test_criterion_walk.py`, add under the existing `scenarios(...)` line:

```python
scenarios("../features/criterion_review.feature")
```

and append these steps:

```python
# --- review resolution (Task 6) ------------------------------------------------------------


def _resolve(ctx, mediaid, **kw):
    (row,) = _open_rows(ctx, mediaid)
    ctx["warnings"] = []
    try:
        ctx["outcome"] = resolve_review(
            ctx["repo"], int(row["id"]), today=ctx["day"], client=ctx["tmdb"], warn=ctx["warnings"].append, **kw
        )
    except ValueError as exc:
        ctx["refusal"] = str(exc)


@when(parsers.parse('the owner resolves the review for "{mediaid}" with --film "{title}"'))
def resolve_film(ctx, mediaid, title):
    _resolve(ctx, mediaid, film_id=_fid(ctx, title))


@when(parsers.parse('the owner resolves the review for "{mediaid}" with --create'))
def resolve_create(ctx, mediaid):
    _resolve(ctx, mediaid, create=True)


@when(parsers.parse('the owner resolves the review for "{mediaid}" with --tt "{tt}"'))
def resolve_tt(ctx, mediaid, tt):
    _resolve(ctx, mediaid, tt=tt)


@when(parsers.parse('the owner resolves the review for "{mediaid}" with --none'))
def resolve_none(ctx, mediaid):
    _resolve(ctx, mediaid, none=True)


@then(parsers.parse('the resolution is refused naming the film "{title}"'))
def refused_naming(ctx, title):
    assert ctx["refusal"] is not None and f"film {_fid(ctx, title)}" in ctx["refusal"], ctx["refusal"]


@then("the resolution is refused")
def refused(ctx):
    assert ctx["refusal"] is not None


@then(parsers.parse('the resolution warned that it resembles "{text}"'))
def warned(ctx, text):
    assert any("gate 3" in w and text in w for w in ctx["warnings"]), ctx["warnings"]


@then(parsers.parse('there are {n:d} films titled "{title}"'))
def n_films_titled(ctx, n, title):
    assert _q(ctx, "SELECT COUNT(*) FROM films WHERE title = ?", title) == [(n,)]


@then(parsers.parse('the {year:d} film "{title}" holds criterion id "{mediaid}"'))
def year_film_mediaid(ctx, year, title, mediaid):
    assert ("criterion", mediaid) in ctx["repo"].external_ids_all(_fid(ctx, title, year))


@then(parsers.parse('the {year:d} film "{title}" holds imdb "{tt}"'))
def year_film_imdb(ctx, year, title, tt):
    assert ctx["repo"].external_ids_for(_fid(ctx, title, year)).get("imdb") == tt
```

Add to `tests/unit/test_cli.py`:

```python
def test_review_resolve_tt_that_creates_a_criterion_film_enriches_it(config_dir, monkeypatch):
    (config_dir / "omdb-api-key.txt").write_text("k")
    calls: list[dict] = []
    _capture_sync(monkeypatch, calls)
    monkeypatch.setattr(
        "movie_brain.cli.resolve_review",
        lambda repo, rid, **kw: "created film 12 'The Hole' (1960) from LeTrou60, keyed",
    )
    r = runner.invoke(app, ["review", "resolve", "7", "--tt", "tt9000501"])
    assert r.exit_code == 0, r.output
    assert len(calls) == 1 and calls[0]["skip_catalog"] is True
    monkeypatch.setattr("movie_brain.cli.resolve_review", lambda repo, rid, **kw: "keyed imdb tt1 tmdb 2")
    r = runner.invoke(app, ["review", "resolve", "7", "--tt", "tt0000001"])
    assert r.exit_code == 0 and len(calls) == 1  # keying an existing film is not an add
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/step_defs/test_criterion_walk.py tests/unit/test_cli.py -q -k "review or resolve or criterion"`
Expected: FAIL — the `--film` scenario resolves through the generic path and raises `criterion/no-record rows accept only --dismiss`; the CLI test makes no enrichment call.

- [ ] **Step 3: Implement**

Create `src/movie_brain/application/criterion_review.py`:

```python
"""`review resolve` on a `criterion` row (spec 2026-10-01 D9).

A criterion row names a mediaid the walk could not place (`value`) and no film (`film_id`
NULL) — except the bridge's `id-conflict` rows, which name the claimant film and accept
`--dismiss` only. Everything is re-derived at resolution time: the holder is asked again and
the gates run again. `--film X` binds the mediaid and Criterion's claim to X; `--tt` runs the
`films add` ladder from the owner's id (a holder → bound there; clear → created under TMDB's
title and year with Criterion's director, born holding the mediaid, keyed); `--create` mints
under Criterion's own title, year and director, read from the row's detail (never a refetch: a
`no-record` id would 404 again). The next walk lists the film — its mediaid is now known.

On these HUMAN paths gate 3 warns and never refuses (Plan B ledger L1): gate 3 is year-blind, so
a remake would never get past it, and a human choosing is what gate 3 exists to summon. Gates
1/2/2b, the tombstone and the `films.key` collision still refuse, naming the film.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import date
from typing import Any

from movie_brain.application.criterion_walk import AUTHORITY, parse_criterion_detail
from movie_brain.application.films import gate_ladder
from movie_brain.application.lists import _catalog, _key_new_film, _veto_label, corpus_veto, find_holder
from movie_brain.domain.matching import build_candidate_index
from movie_brain.domain.models import Film
from movie_brain.domain.thumbprint import Verdict
from movie_brain.infrastructure.database import Repository
from movie_brain.infrastructure.tmdb import TmdbClient

ID_CONFLICT = "id-conflict"
_GATE3 = "gate 3 (a human is choosing, so not a refusal): resembles "


def _title_year(crit: dict[str, Any], mediaid: str) -> tuple[str, int | None]:
    year = crit.get("year")
    return str(crit.get("title") or mediaid), int(year) if year is not None else None


def _director(crit: dict[str, Any]) -> str | None:
    return ", ".join(str(d) for d in crit.get("director") or []) or None


def _forms(crit: dict[str, Any]) -> list[str]:
    return [str(t) for t in dict.fromkeys((crit.get("title"), crit.get("title_original"))) if t]


def _bind(repo: Repository, film_id: int, mediaid: str, crit: dict[str, Any], today: date) -> None:
    title, year = _title_year(crit, mediaid)
    try:
        repo.bind_criterion_mediaid(film_id, mediaid, title, year, today)
    except sqlite3.IntegrityError as exc:
        holder = repo.film_id_for_external(AUTHORITY, mediaid)
        raise ValueError(f"{mediaid} is already held by film {holder}") from exc


def _from_tt(
    repo: Repository, mediaid: str, crit: dict[str, Any], tt: str, client: TmdbClient | None, today: date,
    warn: Callable[[str], None],
) -> str:
    if client is None:
        raise ValueError("--tt on a criterion row needs a TMDB token (gate 2b)")
    rows = repo.films_for_matching()
    lad = gate_ladder(
        repo, client, Verdict("match", tt, "id supplied by hand", ()),
        index=build_candidate_index(rows), catalog=_catalog(repo, rows), extra_forms=_forms(crit), veto=False,
        log=warn,
    )
    if lad.kind == "weather":
        raise ValueError(f"{lad.detail} — nothing written, try again")
    if lad.kind == "blocked":
        raise ValueError(lad.detail)
    if lad.vetoed:
        warn(_GATE3 + lad.vetoed)
    if lad.kind == "held":
        if lad.holder is None:
            raise ValueError(lad.detail)
        _bind(repo, lad.holder, mediaid, crit, today)
        return f"{mediaid} → film {lad.holder} (holds {tt})"
    title, year = _title_year(crit, mediaid)
    film = Film(lad.title, lad.year, _director(crit), "")
    new_id = repo.create_criterion_film(film, mediaid, title, year, today)
    if new_id is None:
        raise ValueError(f"key {film.key!r} appeared during the resolution — nothing written")
    status = _key_new_film(repo, client, new_id, tt, lad.tmdb_id, today, warn)
    return f"created film {new_id} {lad.title!r} ({lad.year or '-'}) from {mediaid}, {status}"


def _create(
    repo: Repository, mediaid: str, crit: dict[str, Any], client: TmdbClient | None, today: date,
    warn: Callable[[str], None],
) -> str:
    if not crit.get("title"):
        raise ValueError("this row holds no Criterion title to mint from — use --film or --tt")
    title, year = _title_year(crit, mediaid)
    film = Film(title, year, _director(crit), "")
    found = crit.get("tt")
    if found:
        if client is None:
            raise ValueError("--create on a row the resolver keyed needs a TMDB token (gate 2b)")
        holder, label = find_holder(repo, client, Verdict("match", str(found), "resolver", ()), warn)
        if label == "tmdb lookup failed":
            raise ValueError("gate 2b: tmdb lookup failed — nothing written, try again")
        if holder is None and label.startswith("tombstoned"):
            raise ValueError(f"tombstoned-holder  {label}")
        if holder is not None:
            raise ValueError(f"film {holder} already holds {found} — use --film {holder}")
    if film.key in repo.tombstoned_keys():
        raise ValueError(f"tombstoned-holder  key {film.key!r} is tombstoned")
    clash = repo.film_id_by_key(film.key)
    if clash is not None:
        clash = repo.canonical_film_id(clash)
        raise ValueError(f"film {clash} already holds the key {film.key!r} — use --film {clash}")
    hits = corpus_veto(build_candidate_index(repo.films_for_matching()), _forms(crit))
    if hits:
        warn(_GATE3 + _veto_label(hits))
    new_id = repo.create_criterion_film(film, mediaid, title, year, today)
    if new_id is None:
        raise ValueError(f"key {film.key!r} appeared during the resolution — nothing written")
    if found:
        _key_new_film(repo, client, new_id, str(found), None, today, warn)
    return f"created film {new_id} {title!r} ({year or '-'}) from {mediaid}"


def resolve_criterion_row(
    repo: Repository,
    row: dict[str, object],
    *,
    today: date,
    film_id: int | None = None,
    create: bool = False,
    tt: str | None = None,
    client: TmdbClient | None = None,
    warn: Callable[[str], None],
) -> str:
    """One resolution of one open criterion row; raises ValueError on every refusal."""
    mediaid = str(row["value"])
    if str(row["reason"]) == ID_CONFLICT:
        holder = repo.film_id_for_external(AUTHORITY, mediaid)
        raise ValueError(f"{mediaid} is held by film {holder} — an id-conflict row accepts --dismiss only")
    crit = parse_criterion_detail(str(row["detail"]) if row["detail"] else None) or {}
    if film_id is not None:
        _bind(repo, film_id, mediaid, crit, today)
        return f"{mediaid} → film {film_id}"
    if tt is not None:
        return _from_tt(repo, mediaid, crit, tt, client, today, warn)
    if create:
        return _create(repo, mediaid, crit, client, today, warn)
    raise ValueError("criterion rows accept --film, --create, --tt or --dismiss")
```

In `src/movie_brain/application/review.py`, inside `resolve_review`:

1. Add to the block of local imports at the top of the function body:

```python
    from movie_brain.application.criterion_review import resolve_criterion_row
    from movie_brain.application.criterion_walk import AUTHORITY as CRITERION_AUTHORITY
```

2. Replace

```python
    if dismiss:
        outcome = "dismissed"
    elif pick is not None or tt is not None or none:
```

with

```python
    if dismiss:
        outcome = "dismissed"
    elif authority == CRITERION_AUTHORITY:
        # Spec D9: a mediaid, not a film — --pick/--none key a film, and --tmdb-id claims one.
        if pick is not None or none or tmdb_id is not None or series:
            raise ValueError("criterion rows accept --film, --create, --tt or --dismiss")
        if value is None:
            raise ValueError(f"criterion review {review_id} names no id")
        outcome = resolve_criterion_row(
            repo, row, today=today, film_id=film_id, create=create, tt=tt, client=client, warn=warn
        )
    elif pick is not None or tt is not None or none:
```

3. Append to the function's docstring, as its last paragraph:

```
    A `criterion` row (spec 2026-10-01 D9) names a Criterion mediaid the walk could not place:
    `--film` binds it to that film, `--tt` runs the `films add` ladder from the given id and
    `--create` mints from the row's own Criterion facts (`application/criterion_review.py`); the
    bridge's `id-conflict` rows accept `--dismiss` only. The next walk lists whatever film now
    holds the mediaid.
```

In `src/movie_brain/cli.py`, `review_resolve`: change the `--film` and `--tt` help strings to

```python
    film: Annotated[
        int | None, typer.Option("--film", help="Match to / merge into this film id (criterion rows: give it the id).")
    ] = None,
```

```python
    tt: Annotated[
        str | None,
        typer.Option("--tt", help="Key the film to this IMDb id (criterion rows: add or find the work by it)."),
    ] = None,
```

and replace its last two lines

```python
    if create:
        _enrich_after_add(repo, 1)
```

with

```python
    if create or outcome.startswith("created film"):
        _enrich_after_add(repo, 1)
```

- [ ] **Step 4: Run them to verify they pass**

Run: `uv run pytest tests/step_defs/test_criterion_walk.py tests/step_defs/test_review.py tests/unit/test_cli.py -q && uv run mypy src`
Expected: all pass; mypy shows only main's 3 pre-existing errors.

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/application/criterion_review.py src/movie_brain/application/review.py src/movie_brain/cli.py tests/features/criterion_review.feature tests/step_defs/test_criterion_walk.py tests/unit/test_cli.py
git commit -m "A Criterion film the walk could not place is settled by hand with --film, --tt or --create and is listed by the next walk — story 7

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: The lifted re-key blocker (D12) and the bridge's parked findings

**Files:**
- Modify: `src/movie_brain/application/repair.py` (`_edition_blockers`, ~line 740)
- Modify: `tests/unit/test_thumbprint.py` (~line 343)
- Modify: `src/movie_brain/application/criterion_bridge.py`, `src/movie_brain/cli.py` (`criterion_bridge_cmd`)
- Modify: `tests/features/criterion_bridge.feature`, `tests/step_defs/test_criterion_bridge.py`, `tests/unit/test_criterion_bridge_file.py`

**Interfaces:**
- Produces: `criterion_bridge.PROGRESS_EVERY = 250`; `run_bridge(..., progress: Callable[[str], None] | None = None)`; outcome kind `tombstoned` in `BridgeReport.counts`.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_thumbprint.py`, replace `test_audit_editions_defers_a_film_criterion_still_lists` with:

```python
def test_audit_editions_no_longer_defers_a_film_criterion_lists(repo):
    """Spec 2026-10-01 D12: the walk matches Criterion by mediaid, never `films.key`, so
    re-keying a Criterion-listed film can no longer mint a duplicate on the next walk."""
    from datetime import date

    from movie_brain.application.repair import EditionContract, audit_editions
    from movie_brain.domain.models import Film

    fid = _edition_film(repo, "SCENES FROM A MARRIAGE: Theatrical Version", 1973)
    repo.record_catalog(
        "criterion",
        [Film("SCENES FROM A MARRIAGE: Theatrical Version", 1973, None, "https://c/sfam")],
        date(2026, 8, 25),
    )
    contract = {fid: EditionContract(fid, "Scenes from a Marriage", 1974, "tt6725014", "133919")}
    (g,) = audit_editions(repo, contract)
    assert "criterion listing" not in g.detail
```

Append to `tests/features/criterion_bridge.feature`:

```gherkin
  Scenario: A tombstoned film never gains a new id (Plan A review, parked)
    Given a Criterion film "Hidden Film" (1960) at old link "hidden-film"
    And the old link "hidden-film" forwards to "/films/H1dden01/hidden-film"
    And the film "Hidden Film" is tombstoned
    When I run the bridge with apply
    Then the film "Hidden Film" holds no criterion id
    And the bridge counted 1 "tombstoned"
```

Add to `tests/step_defs/test_criterion_bridge.py`:

```python
@given(parsers.parse('the film "{title}" is tombstoned'))
def tombstoned(ctx, title):
    ctx["repo"].tombstone_film(_fid(ctx, title), date(2026, 9, 21), note="hidden by hand")
```

Append to `tests/unit/test_criterion_bridge_file.py`:

```python
def test_the_bridge_reports_progress_while_it_asks(repo, config_dir, monkeypatch):
    from datetime import UTC, date, datetime

    from movie_brain.application import criterion_bridge
    from movie_brain.domain.models import Film
    from movie_brain.infrastructure.criterion_site import Forward

    monkeypatch.setattr(criterion_bridge, "PROGRESS_EVERY", 2)
    for slug in ("a-film", "b-film", "c-film"):
        repo.record_catalog(
            "criterion", [Film(slug, 1960, None, f"https://www.criterionchannel.com/{slug}")], date(2026, 9, 20)
        )
    lines: list[str] = []
    criterion_bridge.run_bridge(
        repo, config_dir, [], lambda url: Forward(404, None, None, "gone"),
        datetime(2026, 10, 2, 9, 0, tzinfo=UTC), apply=False, retry=False, progress=lines.append,
    )
    assert lines == ["asked 2 links so far (3 stored)"]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/unit/test_thumbprint.py tests/step_defs/test_criterion_bridge.py tests/unit/test_criterion_bridge_file.py -q`
Expected: three failures — the blocker is still in `g.detail`; the tombstoned film is bound (`counted 0 "tombstoned"`); `run_bridge() got an unexpected keyword argument 'progress'`.

- [ ] **Step 3: Implement**

In `src/movie_brain/application/repair.py`, `_edition_blockers`, delete these lines (and nothing else):

```python
        if repo.has_listing(rekey_id, "criterion"):
            # `record_catalog` upserts ON CONFLICT(films.key): re-keying a film Criterion still
            # lists makes the next walk mint a fresh film under the old key and strand this one.
            # Deferred to the ingester switch, where the resolver — not the key — owns identity.
            blockers.append("criterion listing — re-key deferred to the ingester switch")
```

In `src/movie_brain/application/criterion_bridge.py`:

- After `FRESH_FOR = timedelta(hours=24)` add `PROGRESS_EVERY = 250  # one line per this many links asked: the run takes about half an hour`.
- Add the parameter `progress: Callable[[str], None] | None = None,` after `retry: bool,` in `run_bridge`'s signature.
- Replace

```python
        f = ask(t.url)
        o = Observation(t.url, t.film_id, f.status, f.location, now.isoformat())
```

with

```python
        f = ask(t.url)
        asked += 1
        if progress is not None and asked % PROGRESS_EVERY == 0:
            progress(f"asked {asked} links so far ({len(targets)} stored)")
        o = Observation(t.url, t.film_id, f.status, f.location, now.isoformat())
```

  and add `asked = 0` on the line before `for t in targets:` (the first loop, the asking one).
- Before `counts: dict[str, int] = {}` add:

```python
    # Targets are canonical films, so a disposed one is tombstoned: a film the owner hid never
    # gains an id (Plan A review, parked; 0 such old links live on 2026-10-02).
    hidden = repo.disposed_film_ids()
```

- In the classification loop replace

```python
        kind = f.kind
        if kind == "film":
```

with

```python
        kind = f.kind
        if kind == "film" and t.film_id in hidden:
            kind = "tombstoned"
        if kind == "film":
```

In `src/movie_brain/cli.py`, `criterion_bridge_cmd`: pass `progress=lambda m: console.print(m, markup=False, highlight=False),` to `run_bridge`, and in the counts line add `+ (f" · tombstoned {c['tombstoned']}" if c.get("tombstoned") else "")` immediately before the existing `+ (f" · two ids {report.multi}" ...)` term.

- [ ] **Step 4: Run them to verify they pass**

Run: `uv run pytest tests/unit/test_thumbprint.py tests/step_defs/test_criterion_bridge.py tests/unit/test_criterion_bridge_file.py tests/step_defs/test_thumbprint_editions.py -q && uv run python scripts/thumbprint_benchmark.py --assert`
Expected: all pass; the benchmark gate exits 0 unchanged (no resolver code changed).

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/application/repair.py tests/unit/test_thumbprint.py src/movie_brain/application/criterion_bridge.py src/movie_brain/cli.py tests/features/criterion_bridge.feature tests/step_defs/test_criterion_bridge.py tests/unit/test_criterion_bridge_file.py
git commit -m "Criterion-listed films can be re-keyed again now the walk matches by id, and the bridge never gives a hidden film an id and says how far it has got

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Docs, rules, the spec's superseded numbers, backlog

**Files:**
- Modify: `CLAUDE.md`, `.claude/rules/sync-flow.md`, `.claude/rules/thumbprint.md`, `.claude/rules/identity.md`, `.claude/rules/lists.md`, `docs/superpowers/specs/2026-10-01-criterion-relaunch-design.md`, `docs/superpowers/briefs/2026-10-01-criterion-relaunch/brief.md`, `docs/backlog.md`

No code; every paragraph one unbroken line (never hard-wrap prose).

- [ ] **Step 1: `CLAUDE.md`**

1. In the sync command line (`uv run movie-brain sync [--full|--ratings-only] …`), replace the comment's opening `# refresh catalog + OMDb ratings,` with `# walk the Criterion catalog by mediaid (spec 2026-10-01; one transaction, a failed walk writes nothing for Criterion and the rest of the night still runs, exit 1; prints criterion — arrived N · left N · to review N), then OMDb ratings,` and append ` ; --full is kept for habit and does nothing (every sync walks the whole catalog)`.
2. In the `criterion bridge` line, replace the final sentence `Sync still uses the dead VHX reader until Plan B` with `a tombstoned film never gains an id; prints a progress line every 250 links. The nightly walk (Plan B) needs it applied first: with Criterion films listed and none holding a mediaid, the walk refuses`.
3. In the `review resolve` line, append ` ; a criterion row (a Criterion mediaid the walk could not place) takes --film X (bind it to X), --tt ttNNN (the films add ladder from that id), --create (mint from the row's Criterion title/year/director) or --dismiss (never asked again); a bridge id-conflict row takes --dismiss only; on these human paths gate 3 warns, never refuses`.
4. Replace the "### Sync flow" paragraph with:

```
Eight-step contract (the Criterion walk by mediaid → Mode-B promotion (resolve-first) + metacritic claims → keying (`key_films`) → OMDb by IMDb id only → TMDB providers/notifications → the catch-up chain) lives in `.claude/rules/sync-flow.md`, loaded when you work in `application/sync.py`, `criterion_walk.py`, `availability.py`, or `metacritic.py`. The walk (`application/criterion_walk.py`, spec `docs/superpowers/specs/2026-10-01-criterion-relaunch-design.md`) lists a catalog item on the film holding its mediaid; only an unknown mediaid is looked up (JW Player → the thumbprint resolver → `films.gate_ladder`), and the whole walk is one `record_criterion_walk` transaction. Keying runs before the OMDb loop so a film keyed tonight gets its OMDb record by IMDb id tonight; a film with no IMDb id is skipped and counted in `SyncResult.omdb_unkeyed` rather than looked up by title.
```

- [ ] **Step 2: `.claude/rules/sync-flow.md`**

1. Add `  - src/movie_brain/application/criterion_walk.py` to the frontmatter `paths:` list (and split the existing run-together `metacritic.py  - …catch_up.py` line into two list items while there).
2. Replace steps 1–3 with ONE step 1, and renumber steps 4–8 as 2–6:

```
1. The Criterion walk (`application/criterion_walk.py::walk_criterion`, spec 2026-10-01 D2/D4–D7/D10; the reader is `infrastructure/criterion_site.py`, the VHX reader and its cheap check are gone). It refuses outright when films are listed on Criterion but none holds a mediaid (`criterion bridge --apply` not yet run). The catalog (`/api/all-films/results`, every page, `contentType == film` only) is matched by mediaid FIRST — an item whose mediaid a film holds IS that film (`criterion_mediaid_holders`, canonical), whatever Criterion now prints: our `films.title`/`year`/`director` never change, Criterion's title and year go in a `claim` row (value = the mediaid, INSERT OR IGNORE). An unknown mediaid that any criterion review row names (open or resolved) is skipped with no call; with no resolver (no TMDB token or OMDb key) it is skipped unasked; otherwise its JW record is fetched (404 → a `no-record` review row; a failure → the walk fails), the resolver runs on Criterion's title/year/director (weather → skipped, asked next walk; no match → a `no-match` row with the A/B/C envelope), and a match runs `films.gate_ladder` (gates 1/2/2b, gate 3 over TMDB's + Criterion's titles, the tombstone, the `films.key` collision): a holder joins, a refusal is a review row named by the gate, a clear verdict is staged for creation — RESERVED by tt (a second item naming it joins: one film, two mediaids), by key and by title (a second item colliding goes to review). Leaving labels come from the dated leaving pages, keyed by mediaid (soft: a failure keeps the labels). Then ONE transaction, `Repository.record_criterion_walk`: new films (TMDB's title/year, Criterion's director), mediaids, claims, one listing per film (however many mediaids it holds, so never a twin or a false arrival) against the pre-batch currency frontier, review rows, leaving labels (a listing the walk did not stamp loses its label), `films_fetched_at`. New films are then keyed through `_key_new_film`. ANY failure in the walk → nothing written for Criterion, the rest of the sync runs, exit 1 (`SyncResult.criterion_failed`). Counts: `SyncResult.criterion_arrived/departed/reviews/skipped`.
```

3. In the (renumbered) OMDb step, replace `Tripwires: a catalog failure leaves the DB untouched;` with `Tripwires: a failed Criterion walk leaves Criterion untouched and the rest of the sync runs (exit 1);`.

- [ ] **Step 3: `.claude/rules/thumbprint.md`**

1. In the claims bullet, replace ``— `record_catalog` (criterion, inline against its own open cursor),`` with ``— the Criterion walk (`record_criterion_walk`, value = the mediaid, Criterion's printed title/year, INSERT OR IGNORE so the first title seen stays; `record_catalog` still writes the old-URL claim for the legacy import),`` and append to the same bullet: `Criterion claim values come in three shapes: the old \`criterionchannel.com/<slug>\` URL (VHX era), the 8-character mediaid (the walk), and — only if \`thumbprint backfill\` is re-run after \`criterion bridge --apply\` — the new \`/films/<mediaid>/<slug>\` listing URL (backfill copies \`listings.url\`). \`film_query\` reads a film's FIRST criterion claim, which for a bridged film is the old-URL claim: intended, our year is the truth-holder.`
2. In the `repair editions` bullet, replace the sentence beginning `A film that carries a Criterion listing is never re-keyed:` through `— that group is a \`conflict\` deferred to the ingester switch.` with `Since the Criterion walk matches by mediaid (spec 2026-10-01 D12) a Criterion-listed film is re-keyed like any other: the old \`ON CONFLICT(films.key)\` twin hazard died with the VHX walk.`

- [ ] **Step 4: `.claude/rules/identity.md` and `.claude/rules/lists.md`**

Append to `identity.md`:

```
- Criterion identity (spec `docs/superpowers/specs/2026-10-01-criterion-relaunch-design.md`, 2026-10): a Criterion film's identity is its mediaid, an `external_ids` row (authority `criterion`, claim authority, beside the old URL rows which stay). The walk never matches by `films.key` or title and never writes our title, year or director: Criterion's printed title/year are a claim. A criterion review row (authority `criterion`, `film_id` NULL, `value` = the mediaid; reasons `no-match`, `no-record`, `corpus-veto`, `tombstoned-holder`, `key-collision`, `not-a-film`) is a standing decision once resolved: the walk never asks JW about that mediaid again. The bridge's `id-conflict` rows (film = the claimant) accept `--dismiss` only and are never routed through the TMDB merge reasons.
```

In `lists.md`, in the "Old ratings" bullet, replace `— not abstracted, there is no third caller.` with `— not abstracted. The creating gates themselves have one shared form since 2026-10 (\`application/films.py::gate_ladder\`, called by \`films add\`, the Criterion walk and \`review resolve\` on a criterion row — on that human path gate 3 warns instead of refusing); \`old_ratings.py\` still calls the list helpers directly.`

- [ ] **Step 5: The spec's superseded numbers, the brief, the backlog**

In `docs/superpowers/specs/2026-10-01-criterion-relaunch-design.md`:

1. Replace the whole D13 paragraph with:

```
**D13 — First run.** Real arrivals fire transitions and the normal watchlist notification; departures are a display state as today (`_LISTING_CURRENT`), never an event. Measured expectation (the full bridge dry run of 2026-10-02, `../handoffs/2026-10-02-criterion-plan-b-handoff.md`, superseding the 293-link sample this paragraph first used): ~67 arrivals whose licence started in October; departures up to ~284 — 241 films left with no working link (250 old URLs now 404, 9 now supplements; 49 of them rated, none watchlisted or viewed) plus 43 bridged to a mediaid not in the October 1 catalog (the 39 "September 30" films among them) — fewer in practice where D5 rejoins a 404 film through its new mediaid (Grey Gardens #1817, Mirror #2476, Being Frank #3076, Factory #1689, Fanny and Alexander #3091); the unkeyed K-ON! #142 goes to review instead. 215 catalog films hold no mediaid after the bridge and are looked up on that first walk. All 15 multi-part episode films (Agnès de ci de là Varda #1368–1372, Four Journeys into Mystic Time #1579–1582, Lone Wolf and Cub #1720, #2067–2071) now answer 404, so the bridge binds none of them and no `id-conflict` row is queued; series are excluded (D1), so all 15 depart; none is rated, watchlisted or viewed. Three films bind two different mediaids (Eve's Bayou #1150 theatrical + director's cut, Dr. Dolittle #1285 English + German, Darwin #759 — whether Darwin's two are one work is the owner's call before `--apply`); the walk gives each ONE listing.
```

2. In §6 Rollout, replace step 3 with `3. \`criterion bridge --apply\` (answers older than 24 hours are asked again, ~30 min) → before/after counts. No \`id-conflict\` dismissals are expected (0 clashes in the full dry run).`
3. At the end of D9 append: ` Owner ruling 2026-10-02 (Plan B ledger L1): on these human paths gate 3 WARNS and does not refuse — gate 3 is year-blind, so a remake (The Beast 2023 beside The Beast 1975) could otherwise only be dismissed; the walk keeps gate 3 as a refusal.` — ONLY if the owner said yes to L1; if he chose the literal D9, leave D9 as it is and change Task 6 (`veto=True` in `_from_tt`, refuse on hits in `_create`) before this step.

In `docs/superpowers/briefs/2026-10-01-criterion-relaunch/brief.md`, story 18: replace `all lead to one Criterion series item each. movie-brain tracks films, not series, so` with `no longer have film pages (their old links now answer 404; Criterion sells each set as one "series" item). movie-brain tracks films, not series, so`.

In `docs/backlog.md`, item 50: replace `B — the new walk;` with `B — the new walk (plan \`docs/superpowers/plans/2026-10-02-criterion-relaunch-plan-b.md\`, built on \`feature/STORY-50-criterion-plan-b\`, not merged);`.

- [ ] **Step 6: Check and commit**

Run: `grep -n "VHX reader until Plan B\|deferred to the ingester switch\|68 old URLs\|12 dismissals" CLAUDE.md .claude/rules/*.md docs/superpowers/specs/2026-10-01-criterion-relaunch-design.md` — expected: no output. Then `uv run pytest -q` — expected: green (no code changed in this task).

```bash
git add CLAUDE.md .claude/rules docs/superpowers/specs/2026-10-01-criterion-relaunch-design.md docs/superpowers/briefs/2026-10-01-criterion-relaunch/brief.md docs/backlog.md
git commit -m "Docs and rules follow the walk: identity by mediaid, the eight-step sync, the measured first-run numbers in place of the sampled ones

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Final check (end of the build)

Run: `uv run pytest -q && uv run ruff check src tests && uv run mypy src && uv run python scripts/thumbprint_benchmark.py --assert`
Expected: suite green (record the count beside 1985), ruff clean, mypy shows only main's 3 pre-existing errors, the benchmark gate exits 0. Then a whole-branch review (superpowers:requesting-code-review) against this plan and the spec.

## After the build (not in this session)

- Gap check point C runs after Plan C (directors), before rollout step 3 (spec §8).
- Rollout steps 3–4 stay one at a time on the owner's yes, after Plan C: dated copy → `criterion bridge --apply` → dated copy → `sync` in the background → arrivals / departures / reviews reported apart from TMDB counts. Darwin's answer settles first.
