# Curated lists: trust and the cross-list tally — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** each film card shows how many curated lists it appears on, an "on 2+ lists" chip narrows the table to that shortlist, and `movie-brain lists trust` records which lists the owner actually rates. This delivers §5.7 of the original curated-lists design, which three earlier increments were built not to preclude.

**Architecture:** One additive registry column, one CLI verb, one column threaded through the existing one-query read model, one client-side badge, and one canned-filter predicate wired the way `domain/filters.py` already mandates. No resolver, no gates, no matching.

**Tech Stack:** Python 3.12, uv, pytest + pytest-bdd, Typer CLI, SQLite via `infrastructure/database.Repository`, ruff + mypy, Playwright.

**Spec:** `docs/superpowers/specs/2026-08-29-list-trust-and-tally-design.md`. All three earlier list specs stay binding.

## Global Constraints

- **Gates after every task**: `uv run pytest` · `uv run ruff check .` · `uv run mypy` · `uv run python scripts/thumbprint_benchmark.py --assert` (baseline **n=571 / WRONG=0 / 92.0% over 526**) · `uv run python scripts/matching_benchmark.py --assert-dominance`. Nothing in this plan touches `domain/thumbprint.py`, `infrastructure/thumbprint_fetch.py` or the fixture, so **any movement in the thumbprint gate is a bug in the task**.
- **NEVER hand-edit `scripts/eval/thumbprint_eval_v1.csv` or `scripts/eval/fixtures/cand_cache.json.gz`.**
- **Never run any command against the live database.** It is at schema v15 with 4,703+29 films and three lists (`cahiers-100`, `bergan-100`, `sight-and-sound-2022`) holding 464 entries, 459 of them linked. Every manual/CLI check sets `MOVIE_BRAIN_CONFIG_DIR` to a scratch dir under `/private/tmp/claude-501/-Users-jayers-code-movie-brain/dda96b72-43e7-425e-afde-45bf06a75a42/scratchpad/`.
- **The one-query constraint is the standing rule of this whole feature** (original design §5.7 constraint 1): the dashboard renders ~4,700 films at once, so list membership is fetched in ONE query for the whole view, never per film. There is a `set_trace_callback` test asserting exactly one query — it must stay as written, not be weakened.
- **Never denormalize the tally onto `films`** (§5.7 constraint 3). The count is derived client-side from `FilmView.lists`, which the view already carries.
- **Canned filters obey CLAUDE.md exactly:** thresholds and chip names live ONLY in `domain/filters.py`; JS reads thresholds from `/api/config`; `CHIP_PREDICATES` in `app.js` and the chip buttons in `index.html` stay in lockstep with `_PREDICATES`.
- Nothing but the new CLI verb writes `film_list.trust` — not `lists import`, not `lists create`, so a re-import never resets a judgement.
- Never edit an applied migration (013, 014, 015 are all applied live). Films are immutable.
- Markdown is never hard-wrapped. Commit messages: brief single line, focused on *why*.
- Branch `feature/list-trust`; **do not merge without asking**.

---

### Task 1: Migration 016, the registry column, and the `lists trust` verb

**Files:**
- Create: `migrations/016_list_trust.sql`
- Modify: `src/movie_brain/domain/models.py` (`ListMeta.trust`)
- Modify: `src/movie_brain/infrastructure/database.py` (`upsert_film_list`, `film_list`, a `film_lists()` reader, `set_list_trust`)
- Modify: `src/movie_brain/cli.py` (`lists trust`)
- Test: `tests/unit/test_repository_lists.py`, `tests/unit/test_cli.py`

**Interfaces:**
- `film_list.trust INTEGER NOT NULL DEFAULT 1` — spec §3 verbatim.
- `Repository.film_lists() -> list[ListMeta]` — every list, for the no-argument display.
- `Repository.set_list_trust(slug: str, trust: int) -> bool` — `False` when the slug is unknown.
- `movie-brain lists trust [SLUG] [N]` — no args prints every list with its trust, **ordered by trust descending then slug**; `SLUG N` sets one. `N` must be a non-negative integer (**0 is legal** and means "visible in the drawer, scores nothing"). An unknown slug errors and names the known ones.

**The trap:** `ListMeta` is what `upsert_film_list` writes on **every** `lists import`. If `trust` becomes a field that the importer writes, a re-import silently resets the owner's judgement to 1. Decide deliberately where `trust` lives on the read path versus the write path, and **pin it with a test that imports a list, sets trust to 9, re-imports, and asserts the trust is still 9.**

- [ ] **Step 1: Write the failing tests** — the column defaults to 1 for the three existing rows; `set_list_trust` returns False on an unknown slug; 0 is accepted; a negative value is rejected at the CLI; `film_lists()` orders by trust desc then slug; **and the re-import-preserves-trust test above**.
- [ ] **Step 2: Write `migrations/016_list_trust.sql`** — exactly spec §3, BEGIN/COMMIT, `schema_version` row, leading comment naming the spec.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Verify** — all five gates, plus a scratch-dir `migrate --apply` and a `lists trust` round trip.
- [ ] **Step 5: Commit** — "a judgement about a list must survive re-importing it".

---

### Task 2: The read model, the badge, and the chip

**Files:**
- Modify: `src/movie_brain/infrastructure/database.py` (`_LISTS_SQL`, `_lists_by_film`)
- Modify: `src/movie_brain/domain/models.py` (`FilmView.lists` shape comment)
- Modify: `src/movie_brain/domain/filters.py` (`MULTI_LIST`, the predicate, `thresholds()`)
- Modify: `src/movie_brain/web/static/app.js`, `src/movie_brain/web/templates/index.html`
- Test: `tests/unit/test_repository_lists.py`, `tests/unit/test_filters.py` (or wherever `_PREDICATES` is tested), `tests/web/`

**Interfaces:**
- `_LISTS_SQL` selects `l.trust`; each dict becomes `{slug, name, curator, published, ordered, trust, rank, rank_label}`.
- `MULTI_LIST = 2`; `thresholds()` exports it as `multi_list`; `_PREDICATES["multi_list"]` is `len(v.lists) >= MULTI_LIST`.
- `CHIP_PREDICATES.multi_list` reads `state.cfg.canned_thresholds.multi_list` — **never a hardcoded 2 in the JS**.
- The card badge reads `3 lists` / `1 list`, rendered only when the film is on at least one list, derived from `f.lists.length`.
- The drawer's "On lists:" line orders by **trust descending, then name** — the only place trust is visible.

- [ ] **Step 1: Write the failing tests** — `_lists_by_film` carries `trust` and **still issues exactly one query**; `/api/config` exposes `multi_list`; `/api/config`'s `chips` list includes `multi_list`; the predicate matches a film on two lists and not one on one; a Playwright assertion that the badge reads `3 lists` on a film on three and is absent on a film on none; a Playwright assertion that the chip narrows the table; the drawer orders its lists by trust.
- [ ] **Step 2: Implement.** Keep `CHIP_PREDICATES`, `_PREDICATES` and the `index.html` buttons in lockstep — that lockstep is a CLAUDE.md rule, and a chip present in one and missing in another is a silent dead control.
- [ ] **Step 3: Verify** — all five gates (`uv run playwright install chromium` first if the browser is missing).
- [ ] **Step 4: Commit** — "the tally is the reason the corpus was worth building".

---

### Task 3: Docs, and a scratch rehearsal against the real catalog

**Files:**
- Modify: `.claude/rules/lists.md`, `CLAUDE.md`

- [ ] **Step 1: Docs.** `.claude/rules/lists.md`: `trust` defaults to 1 so the weighted tally starts identical to the raw count; only `lists trust` writes it and a re-import must never reset it; the tally is computed from `FilmView.lists` and is NEVER denormalized onto `films`; the chip counts lists rather than weight, so a film does not leave the shortlist when a list is downgraded. `CLAUDE.md`: the new verb in the commands block, and the chip in the canned-filter bullet. Match the established voice; never hard-wrap.
- [ ] **Step 2: Rehearse on a scratch copy of the live DB** — `MOVIE_BRAIN_CONFIG_DIR` on **every** command. `migrate --apply`, `lists trust` (expect all three at 1), set Cahiers to 10 and Bergan to 9, `lists trust` again, then re-run `lists import lists/cahiers-100.tsv --apply` and confirm Cahiers is **still 10**. Report the counts of films on 3, 2 and 1 lists.
- [ ] **Step 3:** Serve the dashboard against the scratch copy and confirm by screenshot that the badge renders and the chip filters. Report what you saw.
- [ ] **Step 4: Verify** — all five gates.
- [ ] **Step 5: Commit** — "what the chip counts, and what trust does not touch".

---

### Task 4: Live (owner-gated — do not start without an explicit yes)

- [ ] **Step 1:** Snapshot the live DB, then `migrate --apply`.
- [ ] **Step 2:** Report the tally distribution, then stop for the owner to choose trust values — Moviewise's ordering ranks Cahiers first and Bergan second, but ranks the Sight & Sound **1992** poll, not the 2022 one that is imported, so 2022's value is the owner's alone.
- [ ] **Step 3:** Apply the chosen values and report before/after. Do not merge without asking.of
