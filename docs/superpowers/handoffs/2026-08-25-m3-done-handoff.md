# Handoff: M3 (repair & merge surface) landed → next phase

**Written:** 2026-08-24, end of the M3 session. Read alongside
`docs/superpowers/specs/2026-08-23-matching-overhaul-design.md` (binding spec, M1–M3 Done
lines all filled in), `docs/superpowers/handoffs/2026-08-24-m3-matching-handoff.md` (the
M2→M3 handoff this one supersedes), and CLAUDE.md (updated on the M3 branch).

## Status — M3 is COMPLETE on `feature/M3-repair-surface`, NOT merged and NOT pushed

17 commits from `23b9e39` (plan + Tasks 1–9, the final docs commit, and the year-write-back fix). The worktree
lives at `.claude/worktrees/M3-repair-surface`. Suite, ruff, mypy, and
`scripts/matching_benchmark.py --assert-dominance` all green at the tip. Merging to `main`
and deleting the worktree is the first thing the next session should do (see
`superpowers:finishing-a-development-branch`).

**What landed, per verb:**

- **`film_disposition` ledger** (migration 008) + `merge_film` / `tombstone_film`
  primitives. `merged` aliases a losing identity to its survivor; `films_for_matching`
  returns the loser's title under the *ultimate* survivor's id (multi-hop chains resolve),
  so an ingester matching an old title lands on the canonical row. `tombstoned` hides the
  film and blocks re-creation. Every film read model carries the `_NOT_DISPOSED` guard.
  `merge_film` moves owned / watchlist / my_ratings / external_ids / listings / omdb /
  tmdb / availability_transitions to the survivor (survivor wins conflicts, listings widen
  to the union of both seen windows, the dropped loser values are recorded in the
  disposition note), resolves the **loser's** open reviews, drops the loser's
  needs_revisit flag, and **keeps the loser's `films` row** — collectors never delete.
- **`movie-brain repair dupes [--apply] [--yes]`** — norm-title + id-conflict audit,
  classified by TMDB-id equality (same id → twin, differing ids → distinct, any member
  without a tmdb id → undecided). Only TWIN groups merge, and only after confirmation.
- **`movie-brain repair links [--apply]`** — re-validates every stored TMDB link against
  TMDB's `title`/`original_title` (the Rambo/Vahşi Kan class from M2 finding 1); `--apply`
  clears confirmed-wrong links for rematch.
- **`movie-brain repair years [FILM_ID YEAR] [--apply]`** — open year-collisions + stale
  OMDb payloads worklist; `--apply` marks stale rows for refetch, or writes one manual
  year correction.
- **`movie-brain review list|resolve|revisits`** — the resolution surface. A resolved row
  is a **standing decision**: `suppress_resolved`, `rebuild_no_match_queue`, and
  `queue_review_once` all consult resolved rows and never re-queue one. Actions:
  `--film X` (match/merge into an existing film), `--tmdb-id X` (claim a TMDB id),
  `--create` (promote the staged Metacritic / owned Apple title into a real film),
  `--dismiss`. Resolution re-derives the conflict at resolution time rather than trusting
  the row's stored `value`.
- **Matcher rule banked** (`domain/matching.py`): a rerelease-annotated commerce year is
  not year evidence when an older same-title candidate also survives scoring — the matcher
  refuses and queues `rerelease-ambiguous` instead of matching the same-titled film sitting
  at the claimed year. This is the Metropolis case, now benchmark ground truth
  (`metropolis-rerelease-same-year-twin`).
- **Year write-back ignores dispositioned keys** (`Repository.update_film_year`): a
  merged-away key-holder is not a live identity, so it no longer blocks its own survivor
  from adopting the correct year; the dead key is retired in place (`key || ' #' || id`)
  because `films.key` is UNIQUE. A tombstoned holder still blocks by design — see the
  survivor-policy note.
- **Backlog item 9 shipped inside M3**: the `needs_revisit` drawer flag (own table, drawer
  toggle + its API the only UI writer, filter chip, `review revisits` worklist, cleared on
  review resolution / `repair years --apply` / merge-as-loser / tombstone).

## Live numbers (2026-08-24 run, backup `movie-brain.db.bak-pre-m3`)

| step | result |
|---|---|
| `repair dupes` dry-run | groups 68 (28 id-conflict + 40 norm-title) · twins 28 · distinct 24 · undecided 16 |
| stale-claim dismissals | 3 (reviews 3091, 3090, 3076 — films 4307, 4280, 2163) |
| `repair dupes --apply --yes` | **merged 25** · declined 0 |
| `repair years --apply` | open collisions 0 · **stale omdb 151 · refresh marked 151** |
| `repair links` | checked 4,246 · **suspects 134 · cleared 0** (deliberate — see worklist (c)) |
| remake creates | **23** (`review resolve … --create`, films **4673–4695**) |
| `sync` | films 3,049 · **looked up 174** · full walk · **tmdb matched 23** · promoted 0 |
| `rematch` run 1 | misses 383 → **11 rematched** / 369 still missed · year-checked 1,445 · adopted 0 · **5 year-collisions queued** (CLI printed 10 — re-detections, dedup guard kept 5) · **audit 0** |
| collision-probe fix + `rematch` run 2 | **adopted 5** · collisions queued 0 · **audit 0** — survivor years now canonical |
| queue hygiene | 16 merge-artifact rows dismissed (5 `year-collision` + 11 `id-conflict`) |
| benchmark | ground truth **26/26, 0 wrong-match** (baseline 14/26, 2 wrong) · `--assert-dominance` **exit 0** (mc review 3.1%, apple 4.8%) |
| dispositions | `merged` **25**, no tombstones |
| **owned on disposed films** | **0** ← the Done criterion |
| `repair dupes` re-run | **twins 0** · distinct 42 · undecided 20 |
| open reviews | **544 → 494** |

Open reviews after, by authority/reason:

```
apple-tv/year-drift             7
metacritic/ambiguous-title      7
metacritic/expected-miss       97
metacritic/film-multiple-slugs  3
metacritic/key-conflict         1
metacritic/slug-conflict        5
metacritic/year-gap             2
tmdb/no-match                 372
                        total 494
```

`tmdb/id-conflict` and `tmdb/year-collision` are both **empty** — the merge-artifact rows
were closed during this session's queue hygiene (see the survivor-policy note).

---

## YOUR REMAINING WORKLIST

Nothing here is blocking. Each item is a judgment call the CLI deliberately refuses to make
for you. Run everything from the repo root (or the worktree until it is merged).

### (a) 7 apple-tv `year-drift` rows

An owned Apple title whose year disagrees materially with the film it matched. Decide
per row whether it's the *same* film (Apple's track year is a remaster artifact → keep the
film, dismiss) or a *different* film (a genuine remake → create).

```
#2443  'Anna Karenina' (2012)   vs film 2610
#2444  'King Kong (1976)'       vs film 3253
#2445  'Hamlet' (1996)          vs film 2960
#2446  'The Fly' (1958)         vs film 4634
#2447  'Nosferatu' (2024)       vs film 4095
#2448  'The Mummy' (1932)       vs film 4494
#2449  'Scarface' (1983)        vs film 3382
```

```bash
uv run movie-brain review list --authority apple-tv          # re-read with full detail
uv run movie-brain review resolve 2443 --create              # different film → new row
uv run movie-brain review resolve 2443 --film 2610           # same film → attach owned mark
uv run movie-brain review resolve 2443 --dismiss --note "…"  # Apple year artifact, no change
```

My read (unverified — spot-check before acting): 2444 King Kong 1976, 2446 The Fly 1958,
2447 Nosferatu 2024, 2448 The Mummy 1932 and 2449 Scarface 1983 all look like **genuine
remakes** of a differently-dated film we already hold (`--create`); 2443 Anna Karenina 2012
and 2445 Hamlet 1996 are more likely correct matches with an Apple year artifact
(`--film`/`--dismiss`).

### (b) 20 undecided dup groups

Each has at least one member with **no TMDB id**, so `repair dupes` can't decide
twin-vs-distinct. Backfill the missing tmdb id (or eyeball the pair) and then either merge
or leave both.

```
beautyandthebeast   #2418 (1946, tmdb=-) | #3139 (1991, tmdb=10020, owned)
crisis              #1563 (1946, tmdb=30734) | #2488 (1963, tmdb=-)
dreams              #225  (2024, tmdb=1134463) | #2248 (1955, tmdb=-)
eva                 #1684 (1962, tmdb=-) | #2693 (1948, tmdb=-)        <- both missing
eyeswithoutaface    #1867 (1960, tmdb=31417) | #3393 (2003, tmdb=-)
ivitelloni          #1864 (1953, tmdb=12548, owned) | #3582 (2003, tmdb=-)
lallorona           #853  (2019, tmdb=617708) | #1419 (2003, tmdb=-)
lawrenceofarabia    #3086 (1962, tmdb=947, rated owned) | #4048 'Lawrence of Arabia (Restored Version)' (1989, tmdb=-, owned)
lola                #2325 (1961, tmdb=-) | #2965 (1981, tmdb=2264)
mafioso             #1436 (1962, tmdb=34866) | #3508 (2007, tmdb=-)
mother              #2653 (1952, tmdb=-) | #4684 'mother!' (2017, tmdb=381283)
overlord            #1942 (1975, tmdb=55343) | #3498 (2006, tmdb=-) | #4269 (2018, tmdb=438799, owned)
phoenix             #2030 (2014, tmdb=254578) | #2582 (1947, tmdb=-)
piccadilly          #1091 (1929, tmdb=51079) | #3459 (2004, tmdb=-)
pressure            #1305 (1976, tmdb=114072) | #1628 (2006, tmdb=-)
thebridge           #2555 (1959, tmdb=-) | #4084 (2006, tmdb=1666, owned)
thegoldrush         #2757 (1942, tmdb=-) | #3394 (1925, tmdb=962)
thestranger         #2683 (1991, tmdb=-) | #4691 (2022, tmdb=848791)
western             #1364 (2015, tmdb=-) | #4674 (2017, tmdb=452000)
wings               #2977 (1966, tmdb=-) | #4595 (1927, tmdb=28966, owned)
```

Clear twins to my eye: **lawrenceofarabia** (#4048 is a restoration of #3086 — the
"(Restored Version)" title and 1989 year are the giveaway), **eyeswithoutaface**,
**ivitelloni**, **mafioso**, **piccadilly** (each a 2003–07 trailing-whitespace twin of an
older Criterion row — the trailing space in the title is the tell, these are re-release
rows, not different films). Clear *distinct*: **mother** (Pudovkin/Naruse 1952 vs
Aronofsky's `mother!`), **thegoldrush** (1942 is the sound reissue — arguably a twin),
**western**, **thestranger**, **overlord** (three different films).

```bash
uv run movie-brain repair dupes                          # re-read the groups
uv run movie-brain review resolve <ID> --tmdb-id <TMDB>  # backfill from a no-match row, then re-run dupes
uv run movie-brain repair dupes --apply                  # per-group prompt (omit --yes)
```

### (c) 134 `repair links` suspects — **nothing was cleared**

`repair links` compares our title against TMDB's `title`/`original_title`, so it flags every
film we hold under a different-language or differently-punctuated name. The full list is in
`.superpowers/sdd/2026-08-24-m3-repair-surface/task-10a-report.md`. Two distinct
populations:

**~124 alternate-title false positives — do NOT clear.** English retitlings ("Apur Sansar"
→ *The World of Apu*), translated titles, subtitle variants ("The Fog of War" ↔ "The Fog of
War: Eleven Lessons…"), punctuation ("Mulholland Dr." ↔ "Mulholland Drive"). Clearing these
would throw away correct links.
*Follow-up:* teach `repair links` to accept an alternate-title whitelist (or query TMDB's
`/alternative_titles`) so these stop surfacing.

**6 clearly-wrong links — these DO need clearing:**

```
#341   'Cut the World' (2012)      → tmdb 72190  'World War Z' (2013)
#2939  'The River' (1951, Renoir)  → tmdb 30014  'House by the River' (1950, Lang)
#4257  'Us (2019)' (Peele)         → tmdb 1727534 'US Tour 2019: The Movie'
#4462  'A Fistful of Dollars'      → tmdb 10772  'Django' (both 1966, different films)
#4488  'West Side Story (2021)'    → tmdb 932104 "Something's Coming: West Side Story" (a doc)
#1689  'Factory' (1970)            → tmdb 252    'Willy Wonka and the Chocolate Factory'
```

**There is no per-film link-clear verb yet.** `repair links --apply` is all-or-nothing, and
running it would clear all 134. *Follow-up: add `repair links --film ID`* (small, obvious
addition to `application/repair.py`). Until then this needs a manual `DELETE FROM
external_ids WHERE film_id=? AND authority='tmdb'` against a backed-up DB, followed by
`uv run movie-brain rematch`.

Ambiguous, worth a look but low stakes: `#497` Year One → *Marriage: Year One*, `#876` 'Kid'
→ *The Karate Kid*, `#1351` Xiao Wu → *Pickpocket* (correct — the original title 小武
confirms it, TMDB's English label is just confusing), `#3703` Our Land, `#3734` April →
*April X*.

### (d) ~372 tmdb `no-match` rows

This is the long tail, and it is *supposed* to be large — the new matcher refuses rather
than guesses. Do **not** try to drain it by hand. Strategy, cheapest first:

1. **Leave it.** A no-match row costs nothing; the film is still visible and still gets OMDb
   data. The queue's job is to be *decidable*, not empty.
2. **Sample it for patterns.** `uv run movie-brain review list --reason no-match | head -60`
   — if a cluster shares a shape (shorts, TV specials, festival titles TMDB genuinely lacks),
   that's a matcher or scope insight, not 372 individual decisions.
3. **Spot-resolve the ones you care about** — a film you rated or own:
   `uv run movie-brain review resolve <ID> --tmdb-id <TMDB>` after looking it up.
4. **The real fix is the iTunes Search adapter** (next-phase candidate below): director- and
   runtime-confirmed evidence would auto-resolve a large slice of this queue.

### (e) The 3 dismissed stale-claim pairs

These were dismissed as "not a twin: stale pre-M1 claim" — in each, a *wrong* film is
holding the TMDB id the *right* film needs, so the right film can never match while the
claim stands. Current state:

```
#1689 'Factory' (1970)                        holds tmdb 252     ← WRONG (that's Willy Wonka)
#4307 'Willy Wonka and the Chocolate Factory' holds nothing      ← the real owner of 252
#4279 'Nymphomaniac: Volume I' (2013)         holds tmdb 249397  ← WRONG (that id is Vol. II)
#4280 'Nymphomaniac: Volume II' (2014)        holds nothing
#2162 'THE AMPUTEE: Version 2' (1974)         holds tmdb 48847
#2163 'THE AMPUTEE: Version 1' (1974)         holds nothing      (two cuts of one Lynch short — arguably fine as-is)
```

**Willy Wonka specifically**: clear the wrong link on **#1689** first, *then* re-run
`uv run movie-brain owned import` so the owned mark lands on #4307 and it can claim tmdb
252. Doing the import first will just re-hit the same conflict. Same shape for
Nymphomaniac (#4279 should hold Vol. I's id, not 249397).

### (f) merge-artifact review rows — **DONE, nothing for you here**

Closed during this session. Recorded so the numbers reconcile:

- **11 `tmdb/id-conflict`** rows (3084 #4088, 3086 #4096, 3087 #4119, 3092 #4315, 3093 #4330,
  3094 #4363, 3096 #4471, 3098 #4602, 3099 #4636, 3100 #4638, 3102 #4669) — each named a
  counterpart already merged into that same film, verified against `film_disposition`.
- **5 `tmdb/year-collision`** rows (4469–4473) — satisfied by the collision-probe fix below.

All 16 dismissed with `--note "counterpart already merged into this film"`. Both reasons now
sit at **zero** open rows.

*Riding note (not fixed):* `merge_film` resolves only the **loser's** open reviews. These 11
survived because they were filed against the film that became the **survivor**. A future
merge can reproduce the artifact — see next-phase candidate 4.

## Riding minors (deferred during M3 — all safe, none blocking)

From `.superpowers/sdd/2026-08-24-m3-repair-surface/progress.md`:

- **T1** — kept/dropped `external_ids` are stored as a list of single-key dicts; `full_note`
  is always JSON-wrapped even when nothing was dropped.
- **T2** — the brief's literal "tombstone of a Background film" scenario isn't exercised
  (±1 year tolerance interaction); `record_catalog` loads the full `film_disposition` table
  per call; alias rows of a former survivor that is *later* tombstoned would still surface
  under the tombstoned id (only the row's own `film_id` is checked); the chain walk isn't
  memoized.
- **T4** — scenario 2 doesn't exercise year adoption (same year); the slug-suppression
  scenario isn't load-bearing; `SLUG_REASONS`/`MERGE_REASONS` sit mid-file; `year-collision`
  holder `int(value)` isn't canonicalized; the film-guard now precedes the "review not open"
  check (error precedence change).
- **T5** — `_classify`'s `len>=2` guard is now redundant.
- **T6** — a non-numeric stored tmdb id counts toward the TMDB tripwire (plan-mandated).
- **T9** — step definitions are duplicated instead of living in
  `tests/step_defs/conftest.py`; `marked_on` and the PUT 400/404 branches are untested; a
  focusout-PUT vs toggle-POST race can toast a spurious "not flagged" error (state stays
  correct).

**Final review deferred minors** (final-review fix wave, 2026-08-24): `set_leaving` can't
reach a merged film's key (needs the same chain-walk `record_catalog` already does);
`watchlist_transitions_on` lacks a disposition guard; there's no Playwright test for the
revisit UI; `review.py`'s function-local import is a cycle-break that should extract a
`review_queue` module instead; `toggle_revisit` accepts disposed film ids (unreachable from
the UI today, but not guarded).

Carried over and still open from M2: rematch's pass-A tripwire early-returns before the
no-match rebuild (self-healing next run, but asymmetric); `collisions_queued`/`id_conflicts`
count *re-detections* per run, so the CLI wording reads as "newly queued" when it isn't
(this is exactly what produced the three "tmdb id conflict for …" lines in the M3 rematch
even though no row was queued); `TmdbArbiter` has no negative caching.

## Survivor-policy note (resolved — read for the reasoning)

`repair dupes` ranks survivors by `_rank`: **criterion > rated > owned > watchlisted >
omdb_found > lowest id**. Criterion always wins first, so the five affected pairs below were
never criterion-vs-owned — in each, *neither* side held a Criterion listing, so the tie broke
on the next tier down, **owned beating a plain (unrated, unwatchlisted) row**. That still let
an owned row win over a plain row even when the owned row carried a worse year — and Apple
track years are remaster-prone, so five survivors kept an artifact year at merge time:
Woodstock 2014 (not 1970), Monty Python and the Holy Grail 1999 (not 1975), The Last Picture
Show 2014 (not 1971), Dog Day Afternoon 2014 (not 1975), Ben-Hur 2001 (not 1959).

`rematch` pass B tried to correct all five and **was blocked by the merge itself** — the
one genuine defect the live run surfaced. In every case the "colliding" film was that
survivor's *own merged-away loser*: because collectors never delete, the loser's `films` row
survives with its original `key`, so `woodstock (1970)` was still occupied by #3150 and
#4315 could not take it. `update_film_year`'s collision probe treated any key-holder as a
live identity.

**Fixed in this milestone** (`Repository.update_film_year`):

- Exactly one holder no longer blocks: **this film's own merged-away loser**. Any other
  holder still blocks, reported under its *canonical* id — a loser merged into some other
  survivor names that survivor, so the year-collision review points at the live identity a
  human would have to reconcile.
- Because `films.key` is UNIQUE, the dead key is **retired in place** first, inside the same
  transaction: `UPDATE films SET key = key || ' #' || id`. The survivor then takes the clean
  key.
- A **tombstoned** holder still blocks, deliberately. `tombstoned_keys()` is the guard that
  stops `owned.py` and `metacritic.py` re-creating a tombstoned film, and that guard *is*
  the key — retiring it would silently disarm the tombstone. This is a deviation from the
  literal "merged-away/tombstoned" instruction, taken because the tombstone guard is
  load-bearing in both ingesters; it is pinned by
  `test_update_film_year_tombstoned_key_holder_still_blocks`.

`rematch` run 2 confirmed it live — **adopted 5, collisions queued 0, audit 0**:

```
adopted TMDB year 1970 for 'Woodstock' (was 2014)
adopted TMDB year 1975 for 'Monty Python and the Holy Grail' (was 1999)
adopted TMDB year 1971 for 'The Last Picture Show' (was 2014)
adopted TMDB year 1975 for 'Dog Day Afternoon' (was 2014)
adopted TMDB year 1959 for 'Ben-Hur' (was 2001)
```

Survivor rows now hold the canonical year and a clean key; the merged losers hold retired
keys (`woodstock (1970) #3150`, …). **No action needed from you** — the years in the
dashboard are correct.

## Backups

```
~/.config/movie-brain/movie-brain.db.bak-pre-m3              <- rollback point for this whole session
~/.config/movie-brain/movie-brain.db.bak-pre-metropolis-fix
~/.config/movie-brain/movie-brain.db.bak-pre-rematch
~/.config/movie-brain/movie-brain.db.bak-2026-08-23-pre-m2
~/.config/movie-brain/backups/                                <- automatic pre-migration snapshots (008, 009)
```

## First-run checks for the next session (2 minutes)

```bash
sqlite3 ~/.config/movie-brain/movie-brain.db "SELECT kind, COUNT(*) FROM film_disposition GROUP BY 1;"
# expect: merged|25  (a tombstoned row appearing means someone ran a tombstone — investigate)

sqlite3 ~/.config/movie-brain/movie-brain.db "SELECT COUNT(*) FROM owned o JOIN film_disposition d ON d.film_id = o.film_id;"
# expect: 0 — owned marks must stay on canonical rows. Non-zero means a merge or an
# `owned import` regressed the disposition guard.

uv run movie-brain repair dupes | tail -1
# expect: twins: 0 (new twins mean a fresh dup pair arrived — merge it)

uv run movie-brain review list | head -1
# expect: ~494 open, drifting only with new sync anomalies. tmdb/id-conflict and
# tmdb/year-collision should both be EMPTY — a year-collision reappearing on a merge
# survivor would mean the update_film_year disposition fix regressed.

uv run python scripts/matching_benchmark.py --assert-dominance | tail -1
# expect: PASS, gt-wrong=0
```

Syncs remain **manual by choice** (user decision 2026-08-24) — the launchd agent is
deliberately not installed. If a check needs fresh data, run `uv run movie-brain sync`
yourself; don't wait on a nightly job.

## Next-phase candidates

1. **iTunes Search API adapter** (the spec's tracked parallel track, and the highest-value
   item): director- and runtime-confirmed matching for Apple titles plus real store ids.
   This is the lever on worklist (d) — it would auto-resolve a meaningful slice of the 372
   no-match rows and retire the "Apple track year is remaster-prone" precedence hack.
2. **Default dashboard scope = Criterion + owned** — small UI decision, already tracked as
   out-of-scope in the spec. The scope toggle exists (`criterion` / `all`); this is just
   picking a better default now that discovery and owned films are first-class.
3. **`repair links --film ID`** — per-film link clear (worklist (c)); a handful of lines,
   and it unblocks the six known wrong links including the Willy Wonka chain in (e).
4. **Alternate-title whitelist for `repair links`** — so the ~124 legitimate retitlings stop
   drowning the six real problems. TMDB's `/alternative_titles` endpoint is the natural
   source.
5. **`merge_film` resolves the survivor's reviews too** — the 11 stale `id-conflict` rows
   cleaned up this session were filed against the film that became the *survivor*, and
   `merge_film` only resolves the *loser's*. Small, and it stops the class recurring.

## Entry-point prompt (paste into a fresh session)

> Post-M3 movie-brain. First: merge `feature/M3-repair-surface` to `main`, push, and delete
> the worktree (`superpowers:finishing-a-development-branch`) — M3 is complete and green but
> unmerged. Read `docs/superpowers/specs/2026-08-23-matching-overhaul-design.md` (M1–M3 Done
> lines filled), `docs/superpowers/handoffs/2026-08-25-m3-done-handoff.md`, and CLAUDE.md,
> then run that handoff's first-run checks (syncs are manual by choice). M3 landed the
> `film_disposition` ledger, `repair dupes|links|years`, the `review list|resolve|revisits`
> CLI, the needs-revisit drawer flag, and the rerelease-ambiguous matcher rule; the live run
> merged 25 twin groups, created 23 remakes, adopted 5 blocked survivor years after fixing
> `update_film_year`'s collision probe, and left open reviews at 494, all decidable by CLI. The handoff's worklist (a)–(e) is the user's, not yours to auto-drain ((f) is already closed). Next-phase
> candidates in priority order: the iTunes Search adapter (director-confirmed matching —
> the real lever on the 372-row no-match queue), `repair links --film ID` + an
> alternate-title whitelist, `merge_film` resolving the survivor's reviews (not just the
> loser's), and the default dashboard scope. Constraints: collectors never delete outside human-confirmed repair
> verbs; keep `scripts/matching_benchmark.py --assert-dominance` green; suite/ruff/mypy
> green. Use the superpowers flow: brainstorm → writing-plans → subagent-driven TDD in a
> fresh git worktree.
