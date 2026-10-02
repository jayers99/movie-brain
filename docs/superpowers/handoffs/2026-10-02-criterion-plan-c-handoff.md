# Criterion relaunch — handoff into Plan C

*2026-10-02. From the session that wrote and built Plan B. Read beside the spec (`../specs/2026-10-01-criterion-relaunch-design.md`, D8 and §8) and the Plan B plan (`../plans/2026-10-02-criterion-relaunch-plan-b.md`, the format to follow) before writing Plan C.*

## State

- Branch `feature/STORY-50-criterion-plan-b` (worktree `/Users/jayers/code/movie-brain-dev`), head `b5ae07d` before this handoff. Plan A (`3e5fd90..700938c`) and Plan B (`e95bd2f..b5ae07d`) are built and reviewed; nothing is merged into main or pushed. Owner ruling 2026-10-02: KEEP the branch as-is; Plan C is built on it.
- Full suite 2050 passed (4 pre-existing warnings); `mypy src` shows only main's 3 pre-existing errors; `ruff check src tests` shows 16 pre-existing errors (the gate is "no NEW errors"); `scripts/thumbprint_benchmark.py --assert` exits 0.
- No live database write and no sync run has happened since rollout step 2 (the bridge dry run, 2026-10-02). Live sync still fails at Criterion until rollout steps 3–4.
- Owner rulings during Plan B: L1 option 1 — on the human `review resolve --create/--tt` paths for a `criterion` row, gate 3 (`corpus_veto`) warns and never refuses (written into spec D9). Darwin #759 is TWO works (see Rollout below).

## What Plan C is (spec D8, unchanged)

A new catch-up-chain step, `criterion directors`, plus the CLI verb `enrich criterion-directors` that runs it by hand. It fills `films.director` from the JW Player record ONLY for films that hold a Criterion mediaid, have a NULL `films.director`, AND have no OMDb director — so no director the owner can already see ever changes. Fill-only, one JW call per film per run, NO stamp and no schema change (a film Criterion gives no director for is simply asked again next run). Its own tripwire: a failure is logged and swallowed, never changes an exit code (chain contract, `.claude/rules/sync-flow.md` step 6). Story 9 in `../briefs/2026-10-01-criterion-relaunch/brief.md` is the owner-visible outcome: Keeping Secrets Will Destroy You #735, The Horse in Focus #1766, The IX Olympiad in Amsterdam #1777 gain Criterion's director; the 117 films that show OMDb's stay exactly as they are.

Spec §5 test for it: "director filled once, only where neither ours nor OMDb's exists, never overwritten". Add: the CLI verb runs the same step; a JW 404 or a JW failure for one film never stops the others; a film whose JW record lists no director is left NULL and asked again next run (never written as an empty string — `JwMedia.directors` is a tuple, join with `", "` and write NULL when empty, the same rule `criterion_walk._director` follows).

## What Plan B left for Plan C to build on

- `infrastructure/criterion_site.py`: `fetch_media(session, mediaid, pacer, sleep) -> JwMedia | None` (None only on a JW 404; network/5xx/empty playlist raise `CriterionError`), `parse_media(body, mediaid)`, `HttpCriterionSite(session, sleep)` with `.media(mediaid)` on the JW pacer (0.25 s). `JwMedia.directors` is decoded from JW's JSON-encoded string.
- `Repository.criterion_mediaid_holders() -> dict[str, int]` (mediaid → canonical film; old `http…` links excluded). The worklist needs a NEW repository read: films holding a non-`http` criterion external id, `films.director IS NULL`, not disposed, and no OMDb director — the OMDb director is `NULLIF(json_extract(o.payload, '$.Director'), 'N/A')` (the expression `films_for_matching` already uses); a film with no `omdb` row has none. Pick one mediaid per film deterministically (a film may hold two: Eve's Bayou #1150, Dr. Dolittle #1285).
- `application/catch_up.py`: `catch_up(...)` runs credits → vectors → store ids → trailers, each through `step(name, run)` under its own tripwire, and `CatchUpReport.line()` prints `credits: N · vectors: N · store ids: N of M · trailers: N of M` (`skipped` when a step did not run). The new step joins this chain (it needs no TMDB token; it needs a JW session — build it in `cli._catch_up_chain`, never in the application layer, the same reason that function builds the CheapCharts client). Decide its position in the chain and its word in `line()` in the plan.
- `cli.py`: the `enrich` typer group already has `credits`, `all`, `trailers`; add `criterion-directors`. `_enrich_after_add` / `enrich all` run the chain through `sync(skip_catalog=True, catch_up=...)`.
- Test fakes: `tests/criterion_fakes.py` (`FakeSite`, `media_like(mediaid, title, directors=(), title_original=None)` built from the real JW capture, `captured_media()`, `mediaid_for`, `seed_known`). Fixture shapes must come from the real captures in `tests/fixtures/criterion/`.

## Re-derive before planning (read-only on the live DB)

Spec D8's counts (124 / 117 / 7 / 3 qualify) were measured 2026-10-01, BEFORE the bridge binds mediaids. The worklist only exists after `criterion bridge --apply`, so on today's live DB no film qualifies yet. Re-derive read-only (`sqlite3 -readonly "file:…?mode=ro"`) from the dry-run observation file `<config_dir>/criterion-bridge.jsonl` joined to the films: which films WILL hold a mediaid, have NULL `films.director` and no OMDb director, and whether #735, #1766, #1777 are still the three. Put the numbers in the plan.

## Deferred minors from Plan B's ledger (the ledger itself was deleted at finish; this is its record)

Final review triaged all of these as not blocking. Pick any up only if Plan C touches the same code.

- Reader: playlist items in `fetch_leaving` are not `isinstance(dict)`-guarded (a non-dict entry raises AttributeError, caught by the walk's soft leaving step); `_soonest` treats a past day of the current month as 0 months ahead; no test pins which pacer `HttpCriterionSite` uses per host; `HttpCriterionSite.leaving()` does not pass `today`.
- Gate ladder: the `add_by_id` post-create race message no longer names the holder; `gate_ladder` tests miss the `find_by_imdb`/`movie_facts` weather path, the non-match ValueError and the `films add` dry-run key collision.
- Walk: the staged `KEY_COLLISION` branch is effectively unreachable (the staged-title veto fires first); a non-weather resolver exception fails the whole walk (documented, conservative); a blocked first item for a tt is not reserved, so a second mediaid of the same work gets its own review row; a mediaid held by a film the owner later tombstones is still listed nightly (hidden by `_NOT_DISPOSED`); leaving labels join through `external_ids.film_id`, not the canonical film.
- Sync / CLI: `--full` is still refused together with `--ratings-only` although it does nothing; tmdb/watchlist test Backgrounds leave seeded films behind when a scenario relists.
- Review: the criterion `--none`/`--pick`/`--tmdb-id` refusals and the `--create`/`--tt` gate refusals other than key collision are untested; `--create` with a resolver tt commits the film before keying (the `films add` precedent).
- Fresh-database edge of the 30-day quiet-rejoin window: with no prior Criterion listings the window's metas are written by the SECOND walk (no live impact — the live DB has VHX history).
- Commit `f30d5bc` carries a `Claude Haiku 4.5` co-author trailer instead of the required one (cosmetic, unpushed).

## Rollout after Plan C (spec §6, every step one at a time on the owner's yes)

1. Gap check point C (`../checks/README.md`) on the branch head with a migrated database copy — two lineages if the pilot is still running.
2. **Darwin #759 repair, before the bridge is applied.** Owner ruling 2026-10-02: two works. #760 "Darwin, What?" was merged into #759 "Darwin, What? What?" on 2026-08-24 by `repair dupes` only because both resolved to TMDB 703322, which is "Darwin, What?"; JW lists them under different `criterion_id`s (34345 `9DlZ3IcB` "Darwin, What?" / 34346 `HjxbRX53` "Darwin, What? What?"), different credits and release dates. There is no un-merge verb: design the smallest live repair (which film keeps which TMDB id and which old link, what happens to #760's disposition), show the owner the exact change and rows, wait for yes. Without it the bridge binds both mediaids onto #759.
3. Dated backup → `criterion bridge --apply` (answers older than 24 h are re-asked, ~30 min, in the builder's background shell) → before/after counts. No `id-conflict` dismissals are expected (0 clashes).
4. Dated backup → `sync` in the background → Criterion arrived / left / to review (expect up to ~284 departures, ~67 October arrivals, 215 lookups; a film carried all along whose new id binds late rejoins quietly within 30 days of the first walk), the TMDB weekly refresh, and Plan C's directors filled.

## Entry prompt for the next session

> Criterion relaunch, Plan C (backlog 50): write the plan, then build it subagent-driven. Work ONLY in the worktree /Users/jayers/code/movie-brain-dev on branch feature/STORY-50-criterion-plan-b (Plans A and B built, not merged, not pushed). Never touch /Users/jayers/code/movie-brain. Read first: docs/superpowers/handoffs/2026-10-02-criterion-plan-c-handoff.md, then the spec's D8 and §8, then docs/superpowers/plans/2026-10-02-criterion-relaunch-plan-b.md for the format, then .claude/rules/sync-flow.md (the catch-up chain contract). Re-derive the directors worklist read-only first. Show me the plan in plain language (an HTML page) and wait for my yes before building. No live database writes and no sync run in this session.
