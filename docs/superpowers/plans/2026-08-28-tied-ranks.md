# Curated lists: tied ranks — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a list whose ranks tie can be imported at all. `film_list_entry.rank` becomes the entry's unique position, a new `rank_label` carries what the poll printed, and the drawer and scorecard show the label. This unblocks both Sight & Sound polls, which are ~250 films sharing ~80 distinct rank values.

**Architecture:** One additive migration, one parser change (column one is the printed rank; position comes from line order), one column threaded through the one-query read model to the drawer, and a label-aware `#N` in the scorecard. The resolver, the fetcher, the four gates and the reconciliation policy are **not touched**.

**Tech Stack:** Python 3.12, uv, pytest + pytest-bdd, Typer CLI, SQLite via `infrastructure/database.Repository`, ruff + mypy, Playwright for the drawer test.

**Spec:** `docs/superpowers/specs/2026-08-28-tied-ranks-design.md`. Both earlier specs stay binding: `2026-08-28-curated-lists-design.md` and `2026-08-28-list-supplied-ids-design.md`.

## Global Constraints

- **Gates after every task**: `uv run pytest` · `uv run ruff check .` · `uv run mypy` · `uv run python scripts/thumbprint_benchmark.py --assert` (baseline **n=571 / WRONG=0 / 92.0% over 526**) · `uv run python scripts/matching_benchmark.py --assert-dominance`. Nothing here touches `domain/thumbprint.py`, `infrastructure/thumbprint_fetch.py` or the fixture, so **any movement in the thumbprint gate is a bug in the task**.
- **NEVER hand-edit `scripts/eval/thumbprint_eval_v1.csv` or `scripts/eval/fixtures/cand_cache.json.gz`.**
- **Never run any command against the live database.** Every manual/CLI check sets `MOVIE_BRAIN_CONFIG_DIR` to a scratch directory under `/private/tmp/claude-501/-Users-jayers-code-movie-brain/dda96b72-43e7-425e-afde-45bf06a75a42/scratchpad/`. The live DB is at schema v15 only after task 4's owner-gated run; until then it stays at v14 with two lists and 4,703 films.
- **`lists/cahiers-100.tsv` and `lists/bergan-100.tsv` are checked in and imported live. They must keep parsing byte-identically and must produce `rank_label IS NULL` for all 200 rows.** A change that alters how they parse is a defect, not a migration.
- **A tie is a display fact, not an identity fact.** Nothing in this plan may touch the four gates, the reconciliation policy, `find_holder`, `corpus_veto`, or `film_rank_on_list`'s duplicate-entry guard.
- Never edit an applied migration (013 and 014 are applied live). Films are immutable; collectors never delete.
- Markdown is never hard-wrapped. Commit messages: brief single line, focused on *why*.
- Branch `feature/tied-ranks`; **do not merge without asking**.

---

### Task 1: Migration 015 + the label-aware parser

**Files:**
- Create: `migrations/015_rank_label.sql`
- Modify: `src/movie_brain/domain/models.py` (`ListEntry.rank_label`)
- Modify: `src/movie_brain/infrastructure/listfile.py`
- Modify: `src/movie_brain/infrastructure/database.py` (`upsert_list_entry`, `list_entries`, `ListEntryRow`)
- Test: `tests/unit/test_listfile.py`, `tests/unit/test_repository_lists.py`

**Interfaces:**
- `ListEntry(rank, title_listed, director_listed, tt_listed=None, rank_label: str | None = None)` — defaulted, appended last, so every existing positional caller is untouched.
- `parse_list_file`: the first cell is the **printed rank**; `entry.rank` is the 1-based index of the data row; `rank_label` is the printed cell when it differs from `str(rank)`, else `None`.
- A label is `=?\d+` and nothing else — anything else raises `ListFileError`.
- The labels' numeric parts must be **non-decreasing** down the file, else `ListFileError`.
- `film_list_entry.rank_label TEXT` persisted by `upsert_list_entry`, returned by `list_entries`.

- [ ] **Step 1: Write the failing tests** — `1,2,3` yields ranks 1,2,3 with `rank_label` all `None` (the existing-file guarantee); `=243` repeated three times yields ranks 1,2,3 with label `=243` on each; a mixed file (`1,2,=3,=3,5`) assigns positions 1-5 and labels only where they differ; **a decreasing sequence raises** (`=243` then `=225` — the reversed-BFI-page case, name the test for it); `250,249,248` raises; `abc`, `=`, `-1`, `3.5`, `= 243` each raise; ranks are contiguous 1..N **by construction** so a gap is now impossible; the round-trip through `upsert_list_entry` → `list_entries`; and a regression test that **the two real checked-in files still parse to 100 rows each with every `rank_label` `None`**.
- [ ] **Step 2: Write `migrations/015_rank_label.sql`** — exactly spec §2, wrapped BEGIN/COMMIT with the `schema_version` row and a leading comment naming the spec.
- [ ] **Step 3: Implement.** The duplicate-rank check is replaced by the non-decreasing check; do not keep both.
- [ ] **Step 4: Verify** — all five gates, plus `migrate` listing 015 as pending then applying it in a scratch dir.
- [ ] **Step 5: Commit** — "a critics' poll ties its ranks, so rank cannot be the thing that makes an entry addressable".

---

### Task 2: The read model, the drawer, and the scorecard

**Files:**
- Modify: `src/movie_brain/infrastructure/database.py` (`_LISTS_SQL`, `_lists_by_film`)
- Modify: `src/movie_brain/domain/models.py` (`FilmView.lists` shape comment)
- Modify: `src/movie_brain/web/static/app.js`
- Modify: `src/movie_brain/application/lists.py` (`scorecard`'s `#N` prefix)
- Test: `tests/unit/test_repository_lists.py`, `tests/web/`, `tests/features/lists.feature` or `tests/unit/test_cli.py` for the scorecard

**Interfaces:**
- `_LISTS_SQL` selects `e.rank_label`; each dict becomes `{slug, name, curator, published, ordered, rank, rank_label}`.
- The drawer renders `rank_label ?? rank`, and still renders no rank at all for an unordered list.
- `scorecard` prints the label where there is one, so the card matches the poll.

- [ ] **Step 1: Write the failing tests** — `_lists_by_film` carries `rank_label` and **still issues exactly one query** (the standing §5.7 constraint — keep the existing trace-callback assertion honest, do not weaken it); `/api/films/<id>` carries `rank_label`; a Playwright assertion that a tied entry's drawer row reads `#=243` and an untied one still reads `#3`; an unordered list still shows no rank; the scorecard prints `#=243` for a labelled entry.
- [ ] **Step 2: Implement.**
- [ ] **Step 3: Verify** — all five gates.
- [ ] **Step 4: Commit** — "show the rank the poll printed, not the one we counted".

---

### Task 3: Docs

**Files:**
- Modify: `.claude/rules/lists.md`, `CLAUDE.md`

- [ ] **Step 1:** Extend `.claude/rules/lists.md`: column one is the printed rank and `rank` is line order; `rank_label` is stored only when it differs; the non-decreasing check and *why* it exists (the BFI page lists 250→1 by default); a tie is a display fact and touches no gate. Match the file's dense single-line-bullet voice; never hard-wrap.
- [ ] **Step 2:** `CLAUDE.md` — one line on the format, in the established style.
- [ ] **Step 3: Verify** — all five gates.
- [ ] **Step 4: Commit** — "the check that stops a poll being imported upside down".

---

### Task 4: Sight & Sound 2022 — extract and rehearse (owner-gated before anything live)

The capability is worthless until a tied list actually goes through it. This task proves it; the live run needs the owner's yes.

- [ ] **Step 1: Extract** the 2022 poll from `https://www.bfi.org.uk/sight-and-sound/greatest-films-all-time` into `lists/sight-and-sound-2022.tsv`. **The page defaults to 250 → 1: extract in 1 → 250 order.** IMDb ids are not on the page, so this is a three-column file — title, director and the printed rank only. Registry: name `The Greatest Films of All Time`, curator `Sight & Sound`, published `2022`, ordered `true`. Assert the file parses, the labels are non-decreasing, and the row count matches what the page claims.
- [ ] **Step 2: Rehearse** on a scratch copy of the live DB with `MOVIE_BRAIN_CONFIG_DIR` set on **every** command: `migrate --apply`, `lists import` dry, `--apply`, `lists create` dry, `review list --authority list`. Save the full card.

  **No link/create prediction is offered.** This list has titles, directors AND years — better input than either previous list — but it is 250 entries and ~2.5× the size, and the catalog now holds both earlier lists. Report the numbers; do not measure them against a guess.
- [ ] **Step 3:** Read every LINKED line and every blocked row. Report anything where the film looks like a different work. Note especially how many of the 250 are absent, since that is the creation-compounding number the seed warned about.
- [ ] **Step 4:** Hand the owner the card and **stop**. The live run and the merge are theirs.
