# Study Mark Implementation Plan (backlog 48)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One mark on a viewing — `study`: there is a technique here to watch for a second time — set by `viewings add --study` or `viewings study VID [--off]`, shown as one word on the drawer's viewing line, found through the Watched chip's second state ("To study") and `viewings list --study`; nothing clears it but `--off`.

**Architecture:** Hexagonal, as the rest of the app: migration `032_viewing_study.sql` adds one column; `Repository` gains the mark's write and carries `study` through every viewing read; `application/viewings.py` gains the `study` use case and the flag on `log_viewing`; `cli.py` gains `viewings study` and `--study` / `--study` on `list`; `domain/filters.py` gains the `study` predicate; `app.js` / `index.html` turn Watched into a cycle chip and draw the word; `SKILL.md` gains the extraction rule.

**Tech Stack:** Python 3.12, typer, Flask, SQLite (migrations dir), pytest + pytest-bdd (`tests/features/*.feature` + `tests/step_defs/`), Playwright for `tests/web/`, vanilla JS in `static/app.js`.

**Spec:** `docs/superpowers/briefs/2026-09-29-study-mark/brief.md` (its Decisions table is the contract) and `mockup-1.html` (what he approves). Trial log: `trial-log.md` in the same folder.

## Global Constraints

- Migration number is **032** (`schema_version` 31 is applied live); `ALTER TABLE viewing ADD COLUMN study INTEGER NOT NULL DEFAULT 0;` plus `INSERT INTO schema_version (version) VALUES (32);` inside `BEGIN; … COMMIT;`. Never edit an applied migration; `migrate --apply` on the live DB needs the owner's separate yes.
- Every refusal writes nothing; the mark's write is inside the one `Repository._conn()` transaction the verb already uses.
- Exit codes: `0` written (including `already marked` / `already clear`), `2` refused (unknown viewing number), `3` unresolved (unchanged).
- `study` joins `CHIPS` at the END of the tuple (URL keys are stable; `test_chip_names_are_stable` is extended, never reordered).
- The Rewatch chip (`rewatch`), its label, tooltip and rule are untouched.
- Do NOT edit `docs/backlog.md` in this plan; the item-48 line is updated at merge time.
- No hard-wrapped prose in any `.md` you write (one paragraph per line).
- Commit after every task with a one-line "why" message ending in `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Review Focus

1. **`viewings study N` twice** → the second answers `already marked`, exit 0, and the tables are byte-for-byte unchanged; `--off` on a clear line likewise `already clear`. (Task 2.)
2. **`viewings add --study` on a day that already has a line** → the existing line is marked and the note appended (`ADDED-TO … · note N · study`); no second viewing row. (Task 2.)
3. **`viewings remove VID`** takes the mark with the row; `remove --note N` leaves it; `merge_film` keeps a marked loser's flag on the survivor's same-date line (OR of both sides). (Task 1.)
4. **The chip's three states** cycle off → `watched` → `study` → off in `index.html`'s `data-cycle`, the URL carries `chips=study`, and the empty state under `study` reads *Nothing marked for study yet.* (Task 4.)
5. **A film with a marked line and a later unmarked one** is still `study` (any line marked); the sort lead under `study` is last viewing desc, the same rule as `watched`. (Tasks 3, 4.)

---

### Task 1: Migration 032 and the repository

**Files:** create `migrations/032_viewing_study.sql`; modify `src/movie_brain/infrastructure/database.py` (`add_viewing` gains `study: bool = False`; new `set_study(viewing_id, on: bool) -> dict | None` returning `{film_id, title, watched_on, changed: bool}` or `None` for an unknown id; `viewings_for` entries gain `study`; `list_viewings` rows gain `study` and take `study_only: bool = False`; `_viewing_stats_by_film` returns `(last, n, any_study)` and `_view()` sets `study`; `merge_film`'s same-date collision ORs the flag); `src/movie_brain/domain/models.py` (`FilmView.study: bool = False`); tests `tests/unit/test_viewings_repository.py`.

- [ ] Write the failing tests: a created line with `study=True` reads back marked; `set_study` on/off/idempotent/unknown; `list_viewings(study_only=True)`; `remove_viewing` drops the row and its flag; `merge_film` keeps the flag on a same-date collision.
- [ ] Migration + repository changes; run the unit tests; commit.

### Task 2: The use cases and the verbs

**Files:** modify `src/movie_brain/application/viewings.py` (`log_viewing(..., study: bool = False)` appends `· study` to `LOGGED` / `ADDED-TO`; new `study(repo, viewing_id, off) -> Outcome` printing `STUDY     viewing #V (#id 'Title', date) · marked for study | mark cleared | already marked | already clear`, `REFUSED   no viewing #N — nothing written` exit 2; `listing(..., study_only)` inserts `study` after the service and says `no viewing marked for study`); `src/movie_brain/cli.py` (`--study` on `add`, new `viewings study VID [--off]`, `--study` on `list`); `tests/features/viewings.feature` + `tests/step_defs/test_viewings.py` (the `_HOW` regex gains ` for study`; new steps `I mark viewing N for study` / `I clear the study mark on viewing N`).

- [ ] Scenarios first: `--study` on a created line and an appended one; mark on, off, twice, unknown; `list --study`; `remove` drops the mark.
- [ ] Implement; run `uv run pytest tests/step_defs/test_viewings.py tests/unit -q`; commit.

### Task 3: The read side — API and domain filter

**Files:** modify `src/movie_brain/web/app.py` (nothing if `to_dict()` carries `study`; `/api/films/<id>` `viewings` entries carry `study` via `viewings_for`); `src/movie_brain/domain/filters.py` (`"study": lambda v, _: v.study`, appended last); `tests/unit/test_filters.py` (tuple extended; `study` is any marked line, never a rental; a film with `viewing_count > 0` and no mark is not `study`).

- [ ] Tests, then the predicate and the payload; commit.

### Task 4: The dashboard

**Files:** modify `src/movie_brain/web/templates/index.html` (the Watched button becomes `data-cycle="watched,study" data-labels="Watched|Watched|To study" data-group="watched"`, tooltip updated); `src/movie_brain/web/static/app.js` (`CHIP_PREDICATES.study = (f) => !!f.study`; the sort lead `state.chips.has('watched') || state.chips.has('study')`; the empty state text for `study`; `viewingLines` draws `<span class="sep">·</span> <span class="study">study</span>` after the service (or the date) when `v.study`; the focus refresh's `state.films[i]` patch adds `study`); `src/movie_brain/web/static/app.css` (`.study` badge as on the mock-up); `tests/web/test_viewing_log.py` (story 1: the line's word; story 4: the chip's three states, order, empty state; story 9: a removed line leaves both states; the focus refresh shows a mark set behind the page's back); the chip-order tests in `tests/web/test_dashboard.py` if any pin the Watched button's attributes.

- [ ] Tests first, then the JS/HTML/CSS; `uv run pytest tests/web/test_viewing_log.py -q`; commit.

### Task 5: The skill and the docs

**Files:** modify `.claude/skills/log-viewing/SKILL.md` (the study rule: explicit reason → `--study`; "mark X for study" about a past night → `viewings list --film ID` then `viewings study VID`; "done studying" / "clear the mark" → `--off`; praise alone → no mark, no question; either-way → one yes-or-no; a film with no line → "a viewing first"); `CLAUDE.md` (the `viewings add` line gains `--study`; new `viewings study VID [--off]` line; `viewings list [--study]`); `.claude/rules/viewings.md` (the mark's contract) and `.claude/rules/dashboard.md` (the Watched chip is a cycle chip now).

- [ ] Docs; `uv run pytest -q` whole suite; ruff + mypy; commit.
