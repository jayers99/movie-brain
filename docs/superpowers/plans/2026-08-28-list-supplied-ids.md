# Curated lists: supplied IMDb ids — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `movie-brain lists import lists/bergan-100.tsv --apply` reads an optional fourth `tt` column, resolves every entry through the normal ladder anyway, reconciles the verdict against the supplied id, and reports the agreement rate — the measurement that is the point of the exercise. Then `lists create` mints the residue as it already does.

**Architecture:** One additive migration, one optional column threaded from the parser through `film_list_entry` to both verbs, and one reconciliation step between `resolve_entry` and `find_holder`. The resolver (`domain/thumbprint.py`), the fetcher (`infrastructure/thumbprint_fetch.py`), the eval fixture, and the four gates are **not touched**.

**Tech Stack:** Python 3.12, uv, pytest + pytest-bdd, Typer CLI, SQLite via `infrastructure/database.Repository`, ruff + mypy.

**Spec:** `docs/superpowers/specs/2026-08-28-list-supplied-ids-design.md` (an increment on `2026-08-28-curated-lists-design.md`, which stays binding).

## Global Constraints

- **Gates after every task**: `uv run pytest` · `uv run ruff check .` · `uv run mypy` · `uv run python scripts/thumbprint_benchmark.py --assert` (baseline **n=571 / WRONG=0 / 92.0% over 526**) · `uv run python scripts/matching_benchmark.py --assert-dominance`. Nothing in this plan touches `domain/thumbprint.py`, `infrastructure/thumbprint_fetch.py` or the fixture, so **any movement in the thumbprint gate is a bug in the task**.
- **NEVER hand-edit `scripts/eval/thumbprint_eval_v1.csv` or `scripts/eval/fixtures/cand_cache.json.gz`**, and **never auto-ratify an agreement into the eval CSV** (spec §2). `application/eval_log.py::ratify` stays the only writer, driven only by human `review resolve` verdicts.
- **Never run any command against the live database.** Every manual/CLI check sets `MOVIE_BRAIN_CONFIG_DIR` to a scratch directory under `/private/tmp/claude-501/-Users-jayers-code-movie-brain/dda96b72-43e7-425e-afde-45bf06a75a42/scratchpad/`.
- **The four gates are unchanged and run on every path, including a supplied id.** A supplied id settles *which work this is*; it says nothing about whether the catalog already holds that work. Weakening a gate because "the curator gave us the id" is the one change this plan must never make.
- Resolver reason strings are contract text — carried verbatim, never reworded.
- Never edit an applied migration. Films are immutable; collectors never delete.
- Markdown is never hard-wrapped. Commit messages: brief single line, focused on *why*.
- Branch `feature/list-supplied-ids`; **do not merge without asking**.

---

### Task 1: Migration 014 + the optional fourth column

**Files:**
- Create: `migrations/014_list_tt.sql`
- Modify: `src/movie_brain/domain/models.py` (`ListEntry.tt_listed`)
- Modify: `src/movie_brain/infrastructure/listfile.py`
- Modify: `src/movie_brain/infrastructure/database.py` (`upsert_list_entry`, `list_entries`, `ListEntryRow`)
- Test: `tests/unit/test_listfile.py`, `tests/unit/test_repository_lists.py`

**Interfaces:**
- `ListEntry(rank, title_listed, director_listed, tt_listed: str | None = None)` — defaulted, so Cahiers' three-column file and every existing caller keep working.
- `parse_list_file` accepts a fourth column; absent or empty → `None`; anything not matching `^tt\d+$` raises `ListFileError`.
- `film_list_entry.tt_listed TEXT` persisted by `upsert_list_entry` and returned by `list_entries`.

- [ ] **Step 1: Write the failing tests** — a four-column row parses; a three-column row still yields `tt_listed=None`; an empty fourth cell yields `None`; **mixed arity in one file** (some rows with an id, some without) parses; `tt123`, `0004972`, `ttabc` and a trailing-space id each raise `ListFileError`; the value round-trips through `upsert_list_entry` → `list_entries`; re-upserting a row **updates** `tt_listed` without clearing `film_id` (the existing guarantee must survive).
- [ ] **Step 2: Write `migrations/014_list_tt.sql`** — exactly spec §4, wrapped `BEGIN … INSERT INTO schema_version (version) VALUES (14); COMMIT;`, with a leading comment naming the spec.
- [ ] **Step 3: Implement.** Keep `title_listed`/`director_listed` verbatim as before; the id is the only new field and it is normalized only by validation, never rewritten.
- [ ] **Step 4: Verify** — all five gates, plus `migrate` listing 014 as pending then applying it in a scratch dir.
- [ ] **Step 5: Commit** — "a list that knows its own ids should not have to be guessed at".

---

### Task 2: Reconciliation, the review reason, and the agreement tally

The heart. Read `src/movie_brain/application/lists.py` in full first — this task inserts one step between `resolve_entry` and `find_holder` in **both** verbs, and must not disturb either.

**Files:**
- Modify: `src/movie_brain/application/lists.py`
- Test: `tests/features/lists.feature`, `tests/step_defs/test_lists.py`

**Interfaces:**
- `ID_DISAGREEMENT = "id-disagreement"` — the sixth `list` review reason.
- `reconcile(verdict: Verdict | None, tt_listed: str | None) -> tuple[str | None, str]` — pure. Returns `(tt_to_use, agreement)` where `agreement` is one of `""` (no id supplied), `"agree"`, `"disagree"`, `"supplied"`. Unit-testable without a repo, a fetcher or a clock; test it as a table.
- `EntryOutcome` gains `agreement: str = ""`, rendered as the `[id agrees]` / `[id supplied]` suffix (spec §6).
- Both report dataclasses gain `agree: int`, `disagree: int`, `supplied: int`, and `with_ids: int`.

Policy, verbatim from spec §5 — implement it as a table, not as nested conditionals:

| verdict | supplied | outcome |
|---|---|---|
| `match`, same tt | present | proceed on that tt, `agree` |
| `match`, different tt | present | **`id-disagreement` review row; never link, never create** |
| not a `match` | present | proceed on the **supplied** tt, `supplied` |
| any | absent | today's behaviour exactly |

- [ ] **Step 1: Write the failing tests.** Unit-table `reconcile` over all four rows plus `verdict=None`. Then scenarios: an agreeing id links exactly as it does today (assert the *same* film id as the no-id case, so "agreement" cannot mean "different path"); a disagreeing id queues `id-disagreement` and **creates nothing and links nothing** (assert `SELECT COUNT(*) FROM films` and the entry's `film_id IS NULL`); a supplied id on a resolver `review` verdict proceeds and links; a supplied id on a resolver `review` verdict with no holder reports `would-create`; **gate 3 still vetoes an entry whose id was supplied** (the gates-unchanged invariant — this is the scenario that stops a future reader "optimising" the gates away for id-bearing rows); a supplied id whose tt is already held by a tombstoned film still blocks; the tally line counts agree/disagree/supplied correctly and reports `of N with ids`.
- [ ] **Step 2: Implement** in `import_list`, then mirror into `create_films`. The two verbs' gate ladders already go through the shared `veto_forms`; keep the reconciliation equally shared rather than copied — a policy that drifts between the phases would make the rehearsal card lie, which is the defect the last round of this feature ended on.
- [ ] **Step 3: Verify** — all five gates.
- [ ] **Step 4: Commit** — "two sources disagreeing about identity is what a human is for".

---

### Task 3: `review resolve` and the scorecard tally line

**Files:**
- Modify: `src/movie_brain/application/review.py` (accept `id-disagreement` alongside the five existing `list` reasons)
- Modify: `src/movie_brain/application/lists.py` (`scorecard` tally line)
- Modify: `src/movie_brain/cli.py` if the tally needs a second print
- Test: `tests/features/review.feature`, `tests/step_defs/test_review.py`, `tests/unit/test_cli.py`

- [ ] **Step 1: Write the failing tests** — an `id-disagreement` row drains with `--film`, with `--create`, and with `--dismiss`; `--pick/--tt/--none` are still refused on it; the tally line renders only when at least one entry carried an id, and is absent otherwise; the tally line survives the CLI's `markup=False, soft_wrap=True` rendering (the regression that already bit once).
- [ ] **Step 2: Implement.**
- [ ] **Step 3: Verify** — all five gates.
- [ ] **Step 4: Commit** — "the agreement rate is the headline, so it has to print".

---

### Task 4: `lists/bergan-100.tsv`, docs, and the rehearsal

**Files:**
- Create: `lists/bergan-100.tsv`
- Modify: `.claude/rules/lists.md`, `CLAUDE.md` if the file-format line needs it

- [ ] **Step 1: Write the file.** Header per spec §S2: slug `bergan-100`, name `The Film Book Top 100`, curator `Ronald Bergan`, published `2011`, source `https://www.imdb.com/list/ls027443221/`, ordered `true`. 100 rows, `rank ⇥ title ⇥ director ⇥ tt`. **The ids and titles are supplied in the controller's dispatch — transcribe them exactly; do not re-fetch IMDb** (it 403s server-side, and a second extraction is a second chance to introduce a silent error). Assert 100 rows, contiguous ranks 1–100, every `tt` matching `^tt\d+$`, and no duplicate tt.
- [ ] **Step 2: Rehearse on a scratch copy of the live DB** — `MOVIE_BRAIN_CONFIG_DIR` on **every** command. `migrate --apply`, `lists import lists/bergan-100.tsv` (dry), `--apply`, `lists create bergan-100` (dry), `review list --authority list`. Save the full card to the workspace.

  **Expected gate coverage, measured read-only 2026-08-28: 14 link via gate 1 · 70 link via gate 2b · 16 absent.** So roughly 84 linked / 16 would-create. The **agreement rate is deliberately not predicted** — measuring it is the point, and a prediction would only anchor the reading. A materially different link shape (linked below 75, or would-create above 25) means something regressed: stop and report.
- [ ] **Step 3: Read every LINKED line and every disagreement yourself** and report anything where the film looks like a different work from the listed title. A wrong link is silent; the card is the only place it shows.
- [ ] **Step 4: Docs** — extend `.claude/rules/lists.md` with the fourth column, the reconciliation table, the never-auto-ratify rule, and the gates-unchanged invariant.
- [ ] **Step 5: Verify** — all five gates.
- [ ] **Step 6: Commit** — "Bergan's hundred, with the ids the resolver will be graded against".

---

### Task 5: Live run (owner-gated — do not start without an explicit yes)

- [ ] **Step 1:** Snapshot the live DB, then `migrate --apply`.
- [ ] **Step 2:** `lists import lists/bergan-100.tsv` dry, show the card **including the agreement line**, wait for yes, then `--apply`.
- [ ] **Step 3:** `lists create bergan-100` dry, show what would be created, wait for a **separate** yes, then `--apply`.
- [ ] **Step 4:** Report before/after counts, the agreement rate, the open review queue, and any `[partial]`. Do not merge without asking.
