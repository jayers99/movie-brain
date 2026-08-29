# Curated top-N lists (v1) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `movie-brain lists import lists/cahiers-100.tsv --apply` links every entry it can prove belongs to an existing film and creates nothing; `movie-brain lists create cahiers-100 --apply` then mints the residue as keyed discovery films. The drawer shows "On lists: Cahiers du Cinéma 2008 #3". **Duplicate films are the failure this must not produce.**

**Architecture:** One new application module `application/lists.py` (a third sibling of `application/owned.py::import_owned` and `application/metacritic.py::promote_top_n` — it must read like them), one new infrastructure parser `infrastructure/listfile.py`, one migration, and a `services`-shaped read-model addition. The resolver (`domain/thumbprint.py`), the candidate fetcher (`infrastructure/thumbprint_fetch.py`) and the eval fixture are **not touched by this plan**.

**Tech Stack:** Python 3.12, uv, pytest + pytest-bdd, Typer CLI, SQLite via `infrastructure/database.Repository`, ruff + mypy, Playwright for the drawer test.

**Spec:** `docs/superpowers/specs/2026-08-28-curated-lists-design.md` (which supersedes §5 of the seed; the seed's §0/§4/§5.5/§5.6/§5.7/§6/§7/§8 remain binding).

## Global Constraints

- **Gates after every task** (all five green before the task is committed): `uv run pytest` · `uv run ruff check .` · `uv run mypy` · `uv run python scripts/thumbprint_benchmark.py --assert` (baseline **n=571 / WRONG=0 / 92.0% auto over 526**) · `uv run python scripts/matching_benchmark.py --assert-dominance`.
- This plan edits neither `domain/thumbprint.py` nor `infrastructure/thumbprint_fetch.py` nor the fixture, so **any movement in the thumbprint gate is a bug in the task**, not a new baseline.
- **NEVER hand-edit `scripts/eval/thumbprint_eval_v1.csv` or `scripts/eval/fixtures/cand_cache.json.gz`.** `application/eval_log.py::ratify` is the only writer, and no list-row resolution calls it.
- **Never run any command against the live database.** Every manual/CLI check sets `MOVIE_BRAIN_CONFIG_DIR` to a scratch directory — subagents included. Tests get it from the autouse `_isolate_env` fixture in `tests/conftest.py`.
- Reason strings from `resolve()` are contract text — never reword them, only wrap them.
- Markdown written by this plan is **never hard-wrapped**: one unbroken line per paragraph and list item.
- Commit messages: brief single line, focused on *why*. Branch is `feature/curated-lists`; **do not merge** without asking.
- **The importer never creates a film.** Only `lists create` does, and only in its own confirmed run.

---

### Task 1: Migration 013 + the list file parser

**Files:**
- Create: `migrations/013_film_lists.sql`
- Modify: `src/movie_brain/domain/models.py` (add `ListMeta`, `ListEntry`)
- Create: `src/movie_brain/infrastructure/listfile.py`
- Test: `tests/unit/test_listfile.py` (new)

**Interfaces:**
- Produces: `domain.models.ListMeta(slug, name, curator, published_year, source_url, ordered)`, `domain.models.ListEntry(rank, title_listed, director_listed)` — both frozen dataclasses.
- Produces: `infrastructure.listfile.ParsedList(meta: ListMeta, entries: tuple[ListEntry, ...])`, `parse_list_file(text: str) -> ParsedList`, `read_list_file(path: Path) -> ParsedList`, `class ListFileError(Exception)`.

- [ ] **Step 1: Write the failing tests** — `tests/unit/test_listfile.py`, covering: a full header block parses into `ListMeta`; `ordered: false` yields `ordered=False` and the default is `True`; a two-column row and an empty third column both give `director_listed=None`; blank lines and `#` lines after the header block are skipped; a title with a curly apostrophe (`Singin' in the Rain`) and `…` (`Madame de…`) survives byte-for-byte; `ListFileError` on a missing `slug`, a missing `name`, a non-integer rank, a duplicate rank, an empty title.

- [ ] **Step 2: Write `migrations/013_film_lists.sql`** — exactly the DDL in spec §3, wrapped in `BEGIN; … INSERT INTO schema_version (version) VALUES (13); COMMIT;`, with a leading comment naming the backlog item and the spec. Do not edit any applied migration.

- [ ] **Step 3: Implement the dataclasses and the parser.** Header block = `# key: value` lines before the first data row; keys `slug` (required), `name` (required), `curator`, `published`, `source`, `ordered`. Data rows split on `\t`. **No normalization of titles at parse time** — `title_listed`/`director_listed` are verbatim forever.

- [ ] **Step 4: Verify** — all five gates. Then, in a scratch config dir, `uv run movie-brain migrate` lists 013 as pending and `--apply` applies it and writes a backup.

- [ ] **Step 5: Commit** — "seed the list registry schema and its checked-in file format".

---

### Task 2: Repository surface + the one-query read model

**Files:**
- Modify: `src/movie_brain/infrastructure/database.py`
- Modify: `src/movie_brain/domain/models.py` (`FilmView.lists`)
- Test: `tests/unit/test_repository_lists.py` (new)

**Interfaces (all new on `Repository`):**
- `upsert_film_list(meta: ListMeta, today: date) -> None` — INSERT … ON CONFLICT(slug) DO UPDATE, refreshing metadata and `imported_at`.
- `upsert_list_entry(slug: str, entry: ListEntry) -> None` — ON CONFLICT(list_slug, rank) DO UPDATE of `title_listed`/`director_listed` only; **never clears an existing `film_id`**.
- `link_list_entry(slug: str, rank: int, film_id: int) -> None`
- `list_entries(slug: str) -> list[ListEntryRow]` — `(rank, film_id, title_listed, director_listed)`, ordered by rank.
- `film_list(slug: str) -> ListMeta | None`
- `film_rank_on_list(slug: str, film_id: int) -> int | None` — the duplicate-entry guard.
- Module-level `_LISTS_SQL` + `_lists_by_film(c) -> dict[int, list[dict[str, object]]]`, **copied verbatim in shape from `_SERVICES_SQL` + `_services_by_film`** (spec §8). One query for the whole view — never per film.
- `merge_film` gains `UPDATE film_list_entry SET film_id = ? WHERE film_id = ?` inside its existing transaction, counted into `MergeReport.moved['film_list_entry']`.

- [ ] **Step 1: Write the failing tests** — upsert idempotence (re-upserting an entry keeps its `film_id`); `film_rank_on_list` finds and misses; `_lists_by_film` returns one dict per film with several lists and **issues exactly one query** (assert via `sqlite3.Connection.set_trace_callback` or by asserting the function is called once per `list_views` call); `list_views`/`get_view` populate `FilmView.lists`; a merged-away film's entries appear under the survivor.

- [ ] **Step 2: Add `FilmView.lists: list[dict[str, object]] = field(default_factory=list)`** — placed with the other collection fields, documented as `[{slug, name, curator, published, rank}]`. `export csv` uses an explicit `COLUMNS` list so it needs no change; confirm that.

- [ ] **Step 3: Implement the repository methods**, wire `_lists_by_film` into both `list_views` and `get_view` alongside `services`, and add the `merge_film` statement.

- [ ] **Step 4: Verify** — all five gates.

- [ ] **Step 5: Commit** — "one query for list membership, because the table renders every film at once".

---

### Task 3: The resolution helpers — form ladder and the four gates

The heart of the accuracy test. Small, pure-ish, and unit-tested on their own before any import loop exists.

**Files:**
- Create: `src/movie_brain/application/lists.py`
- Test: `tests/unit/test_lists_resolution.py` (new)

**Interfaces:**
- `AUTHORITY = "list"`
- `entry_forms(title_listed: str) -> list[str]` — `parse_title(title).forms()` de-duplicated, primary form first.
- `resolve_entry(fetcher, entry: ListEntry) -> tuple[Verdict | None, str]` — **fallback-only ladder**: query the primary form; if the verdict is not `match`, try each remaining form in order and stop at the first `match`. Returns the primary form's verdict when nothing matches, and `(None, form)` when every lookup raised. `make_query(form, None, "list", director=entry.director_listed)` — **year is always `None`**. Catches `(CacheMiss, requests.RequestException, AuthError, QuotaExceeded)` per form and logs.
- `find_holder(repo, tmdb, verdict) -> tuple[int | None, str]` — gates 1/2/2b, returning the canonicalized film id and a short gate label (`"imdb tt…"`, `"tmdb 123"`, `"tmdb(find 3059)"`). Gate 1 `film_id_for_external("imdb", tt)`; gate 2 the winning candidate's `tmdb_id`; **gate 2b** — when the winner carries no `tmdb_id`, `tmdb.find_by_imdb(tt)` and check that holder. A tombstoned holder returns `(None, "tombstoned #N")` (the caller must distinguish this from a plain miss).
- `corpus_veto(index: CandidateIndex, forms: list[str]) -> list[Candidate]` — gate 3: **any** hit from `index.lookup(form)` for **any** form, de-duplicated by film id. A veto, not a matcher: a weak or ambiguous hit is reason enough.

- [ ] **Step 1: Write the failing tests** with an injected `_PoolFetcher`-style fake keyed on `q.title` (follow `tests/step_defs/test_thumbprint.py:393`): a single-form title issues exactly one query; a parenthetical title whose primary form misses falls back to base then alt; the ladder stops at the first `match`; a primary `match` is **never** overridden by a later form; gate 2b finds the holder when the winner is OMDb-only (`tmdb_id=None`) via a stub `find_by_imdb`; gate 3 vetoes on a hit for the alt form alone; a tombstoned holder is reported as tombstoned, not as a miss.

- [ ] **Step 2: Implement.** Keep the gate order and the early returns shaped like `owned.py` lines ~105-130 — read that block first.

- [ ] **Step 3: Verify** — all five gates.

- [ ] **Step 4: Commit** — "gate 2 was blind to an OMDb-only winner; ask TMDB for the mapping key_film already trusts".

---

### Task 4: `import_list` — phase 1, which creates nothing

**Files:**
- Modify: `src/movie_brain/application/lists.py`
- Test: `tests/features/lists.feature` + `tests/step_defs/test_lists.py` (new)

**Interfaces:**
- `EntryOutcome(rank, title_listed, director_listed, kind, film_id, tt, reason, form_used, detail)` — `kind` ∈ `linked | would-create | review | blocked | error`.
- `ListImportReport(exit_code, total, linked, would_create, review, blocked, errors, rows: list[EntryOutcome])`
- `import_list(repo, meta, entries, today, *, fetcher, tmdb, apply: bool, log) -> ListImportReport` — the loop in spec §5, verbatim.
- `queue_list_review_once(repo, entry: ReviewEntry, today) -> bool` — **list-local**, deduping on `reason + value` (not `reason + film_id`, which `application/availability.py::queue_review_once` uses and which would collapse every list row, since they all carry `film_id = NULL`). Consults `repo.resolved_review_keys("list")` so a `--dismiss` is permanent. Document that reason in a comment.
- `scorecard(rows) -> str` — spec §7's two-line-per-entry block, every entry, resolver reason verbatim.

- [ ] **Step 1: Write the failing scenarios** in `tests/features/lists.feature`, driven by an injected pool fake: link via gate 1; link via gate 2; link via gate 2b; gate-3 veto blocks and queues a `corpus-veto` row; a second rank resolving to an already-linked film blocks with `duplicate-entry`; a tombstoned holder blocks with `tombstoned-holder`; a resolver `review` verdict queues `unresolved` with its A/B/C candidates in the detail; a full-miss entry is reported `would-create` and **`films` gains no row**; a dry run writes **nothing at all** (no `film_list`, no entries, no reviews); re-import is idempotent — no duplicate review rows, and a linked entry triggers **no fetcher call** (assert on the fake's call log).

- [ ] **Step 2: Implement `import_list`.** `build_candidate_index(repo.films_for_matching())` **once**, before the loop. Every linked film gets `repo.add_claim(film_id, "list", f"{slug}#{rank}", entry.title_listed, first_seen=today.isoformat())`. Review rows: authority `list`, `value = f"{slug}#{rank}"`, `film_id = None`. A per-entry exception logs and counts `error` without aborting the run.

- [ ] **Step 3: Verify** — all five gates.

- [ ] **Step 4: Commit** — "phase 1 links and asks; it never mints a film".

---

### Task 5: `create_films` — phase 2, the only creation path

**Files:**
- Modify: `src/movie_brain/application/lists.py`
- Modify: `tests/features/lists.feature`, `tests/step_defs/test_lists.py`

**Interfaces:**
- `ListCreateReport(exit_code, total, created, keyed, linked, blocked, errors, rows: list[EntryOutcome])`
- `create_films(repo, slug, today, *, fetcher, tmdb, apply, log) -> ListCreateReport`

Worklist = entries with `film_id IS NULL` and **no** `list` review row (open **or** resolved) for their `slug#rank`. Each entry is **re-resolved** and re-gated at creation time — never trusting phase 1's verdict, the same re-derive rule the repair verbs follow. Outcomes: a holder now exists → link, no creation; gate 3 vetoes now → block + queue; the verdict is no longer `match` → block + queue; otherwise create.

The created `Film` takes **the winning candidate's title and year** (so the row matches the rest of the catalog and lands on the right year), `director_listed`, empty `url`; fall back to `title_listed` with year `None` when the winner carries neither. Check `film.key` against `repo.tombstoned_keys()` first; a `create_film` returning `None` (key collision) **blocks and queues** — it never adopts the colliding film. Then `key_film(repo, tmdb, film_id, verdict.tt, today, log, tmdb_id=winner.tmdb_id)`, so the film is born keyed exactly as Mode-B promotion does; a `held`/`error` result is logged and left for the next sync.

- [ ] **Step 1: Write the failing scenarios** — creates and keys a clean entry; links instead when a holder appeared since phase 1; blocks on a tombstoned key; blocks on a `create_film` key collision; skips a rank that has an open review row; skips a rank that has a **resolved** review row; a dry run creates nothing; nothing is ever written to the eval CSV (assert the file is byte-identical).

- [ ] **Step 2: Implement.**

- [ ] **Step 3: Verify** — all five gates.

- [ ] **Step 4: Commit** — "creation gets its own deliberate yes, and re-derives every gate at the moment it runs".

---

### Task 6: `review resolve` for `list` rows

**Files:**
- Modify: `src/movie_brain/application/review.py`
- Modify: `tests/features/review.feature`, `tests/step_defs/test_review.py`

A new `elif authority == LIST_AUTHORITY and value is not None:` branch, imported locally alongside the existing `MC_AUTHORITY`/`APPLE_AUTHORITY` locals to keep the import graph one-directional. `value` splits on the last `#` into `(slug, rank)`.

- `--film ID` → refuse if that film already sits at another rank on the same list (`film_rank_on_list`); otherwise `link_list_entry` + `add_claim`. Outcome `f"{value} → film {film_id}"`.
- `--create` → `create_film(Film(title_listed, None, director_listed, ""))` (unkeyed; the next sync keying step keys it, exactly like the apple-tv `--create` precedent), then link + claim. A key collision canonicalizes to the existing film and links to it, as the apple-tv branch already does.
- `--dismiss` → existing generic path; the entry stays unlinked forever.
- `--pick/--tt/--none` are **refused** on list rows by the existing guard — add a scenario asserting the error message, so the refusal is contract.

- [ ] **Step 1: Write the failing scenarios.**
- [ ] **Step 2: Implement.** Update `resolve_review`'s docstring to name the `list` authority.
- [ ] **Step 3: Verify** — all five gates.
- [ ] **Step 4: Commit** — "list rows drain like slug rows, because there is no film to key".

---

### Task 7: CLI wiring

**Files:**
- Modify: `src/movie_brain/cli.py`
- Test: covered by the pytest-bdd scenarios plus a scratch-dir smoke run

`lists_app = typer.Typer(help="Curated top-N lists: import a checked-in list file, create its missing films.")`, `app.add_typer(lists_app, name="lists")`.

- `lists import PATH [--apply]` — wires config → `session_fetcher` → `import_list`, `cache.save()` in a `finally` (the session cache, never the fixture), prints the scorecard then the tally, exits `report.exit_code`. Copy `owned_import`'s wiring block (`cli.py:235-261`) in shape.
- `lists create SLUG [--apply] [--yes]` — same wiring; `--yes` skips the per-run confirmation prompt, matching the `repair` verbs.

- [ ] **Step 1: Implement both commands.**
- [ ] **Step 2: Verify** — all five gates, plus a scratch-dir smoke run of both verbs' dry runs against an empty DB.
- [ ] **Step 3: Commit** — "two verbs, two deliberate yeses".

---

### Task 8: Drawer

**Files:**
- Modify: `src/movie_brain/web/static/app.js` (`detailHtml`)
- Test: `tests/web/test_dashboard.py` (Playwright), plus a Flask-client assertion that `/api/films/<id>` carries `lists`

One line beside "Also streaming on:", rendered from `d.lists`: `On lists: Cahiers du Cinéma 2008 #3`, joined with `, ` across lists. An unordered list (`ordered = 0`) renders without the `#rank`. No new endpoint and no server-side filtering — `app.js` already receives the full view JSON. No `/api/config` change.

- [ ] **Step 1: Write the failing tests.**
- [ ] **Step 2: Implement.**
- [ ] **Step 3: Verify** — all five gates (`uv run playwright install chromium` first if needed).
- [ ] **Step 4: Commit** — "the drawer is the whole point of v1".

---

### Task 9: The Cahiers file, docs, and the rehearsal

**Files:**
- Create: `lists/cahiers-100.tsv`
- Modify: `CLAUDE.md` (commands block + a Rules bullet), `docs/backlog.md` (tick item 10), `.claude/rules/` (a `lists.md` path-scoped rule, or a bullet added to `thumbprint.md` — prefer a new `lists.md` scoped to `application/lists.py` and `infrastructure/listfile.py`)

- [ ] **Step 1: Write `lists/cahiers-100.tsv`** from the seed appendix — header block per spec §4, then all 100 rows **verbatim including the source's typos** (`Howard Hawkes` #12, `Joseph Mankiewitz` #31, `Ernst Shoedsack` #55). Assert 100 rows and contiguous ranks 1–100.

- [ ] **Step 2: Rehearse on a scratch copy of the live DB.** `cp ~/.config/movie-brain/movie-brain.db "$SCRATCH/movie-brain.db"`, copy the two key files in, and set `MOVIE_BRAIN_CONFIG_DIR="$SCRATCH"` on **every** command. Run `migrate --apply`, then `lists import lists/cahiers-100.tsv --apply`, then `lists create cahiers-100` (dry run). **Expected, from the 2026-08-28 probe: 75 linked · 20 would-create · 5 review · 0 blocked · 0 error.** A materially different shape means something regressed — stop and report rather than proceeding.

- [ ] **Step 3: Hand the owner the full scorecard** — all 100 entries with the resolver's reason string — plus the tally, and **stop for an explicit yes** before anything runs live.

- [ ] **Step 4: Docs.** Add the two verbs to CLAUDE.md's command block with one-line contracts; add a Rules bullet covering: `list` review rows drain with `--film`/`--create`/`--dismiss` only; the importer never creates; the three gates plus 2b; the form ladder is fallback-only; list membership is fetched in one query and never denormalized onto `films`.

- [ ] **Step 5: Verify** — all five gates.

- [ ] **Step 6: Commit** — "the Cahiers 100 as a diffable artifact, and the contract that keeps it from minting twins".

---

### Task 10: Live run (owner-gated — do not start without an explicit yes)

- [ ] **Step 1:** Snapshot the live DB (`movie-brain.db.bak-pre-lists`), then `migrate --apply` (which writes its own backup).
- [ ] **Step 2:** `lists import lists/cahiers-100.tsv` (dry), show the scorecard, wait for yes, then `--apply`.
- [ ] **Step 3:** `lists create cahiers-100` (dry), show what would be created, wait for a **separate** yes, then `--apply`.
- [ ] **Step 4:** Report before/after counts, the open `review list --authority list` queue, and any `[partial]` line. Do not merge the branch without asking.
