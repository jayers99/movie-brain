# Curated lists: supplied IMDb ids — design

**Date:** 2026-08-28 · **Status:** owner-confirmed on the two open questions; ready to spec into a plan. An increment on [2026-08-28-curated-lists-design.md](2026-08-28-curated-lists-design.md), which stays binding — this document changes only what it names.

**Why:** some list sources carry IMDb ids (the first is Ronald Bergan's *The Film Book* top 100, transcribed at `https://www.imdb.com/list/ls027443221/`). The v1 file format has no id column, so today those ids are thrown away and every entry is re-resolved from title and director alone.

## 1. What the owner decided (2026-08-28, do not relitigate)

| # | Question | Decision |
|---|---|---|
| S1 | How far should a supplied id be trusted? | **Run the resolver anyway and compare.** Not "trust the id and skip the resolver" (the cheap option), and not "trust it blindly". The full ladder runs, and the supplied id is weighed against the verdict. |
| S2 | Bergan registry metadata | name `The Film Book Top 100` · curator `Ronald Bergan` · published `2011` · source the IMDb list URL · ordered `true`. The IMDb user who transcribed it is not the curator. |

**S1 gives up the speed argument on purpose.** The tt column was proposed to skip ~100 multi-call resolutions per list; the owner chose to spend them. That is the right trade for this project, because it converts the import into something the cheap option cannot provide — see §2.

## 2. The point of the expensive option: a labelled test set

A list carrying ids is **external ground truth for the resolver**. Running both and comparing measures the resolver against an answer key it did not produce, on 100 canonical films, for free — which is precisely the accuracy test seed §0 asks for.

So the headline of a supplied-id import is not the link count; it is **the agreement rate**: how often the resolver, given only title and director, reached the id the curator supplied.

**Agreements are NEVER auto-ratified into `scripts/eval/thumbprint_eval_v1.csv`.** Two reasons, both standing project contracts: `application/eval_log.py::ratify` is the only writer and only human `review resolve` verdicts drive it, so the gate can never score itself; and a curator's id can simply be wrong. The rate is *reported*, and a disagreement becomes a review row a human can ratify through the existing path if they choose.

## 3. File format — an optional fourth column

```
# slug: bergan-100
# name: The Film Book Top 100
# curator: Ronald Bergan
# published: 2011
# source: https://www.imdb.com/list/ls027443221/
# ordered: true
1	The Birth of a Nation	D.W. Griffith	tt0004972
```

`rank ⇥ title ⇥ director ⇥ tt`, the fourth column optional **per row**, not per file — a source may carry ids for only some entries. A malformed id (anything not matching `tt\d+`) is a `ListFileError`, same as a bad rank: the file is hand-checked-in and a typo there is silent forever.

Cahiers' three-column file stays valid and unchanged.

## 4. Migration 014

```sql
BEGIN;
ALTER TABLE film_list_entry ADD COLUMN tt_listed TEXT;
INSERT INTO schema_version (version) VALUES (14);
COMMIT;
```

Additive, no rebuild, no backfill — Cahiers' 100 rows keep `tt_listed IS NULL`. The column records what the source claimed, forever, alongside `title_listed`/`director_listed`; a list is a historical artifact and the id is part of what it said.

(`rank_label`, for tied ranks on the Sight & Sound polls, is a separate later migration. Not in scope here.)

## 5. The comparison policy

Both verbs resolve as they do today. When `tt_listed` is present, the verdict and the supplied id are then reconciled:

| resolver verdict | supplied id | outcome |
|---|---|---|
| `match`, same tt | present | proceed on that tt — **`agree`**, the normal linked / would-create path |
| `match`, **different** tt | present | **`id-disagreement`** review row. Never link, never create. Two independent sources disagree about identity; that is exactly what a human is for. |
| not a `match` | present | proceed on the **supplied** tt — **`supplied`**. The id is evidence the resolver lacked, and it is what makes this column worth having: Cahiers left 5 entries unresolved that an id would have settled. |
| `match` | absent | today's behaviour, unchanged |
| not a `match` | absent | today's behaviour, unchanged |

The three gates plus 2b and gate 3's veto run **unchanged on every path**, including `supplied`. A supplied id shortens the argument about *which work this is*; it says nothing about whether the catalog already holds that work, which is the question the gates answer and the only thing standing between this feature and a duplicate film.

An `id-disagreement` row drains with the existing `--film` / `--create` / `--dismiss` verbs (design §1 A1 — a list entry still has no film to key, so `--pick/--tt/--none` remain refused).

## 6. Scorecard

Every entry keeps its two-line block. The supplied-id state is one suffix on the verdict line, and the reason string stays contract text:

```
#15   King Kong / Merian C. Cooper
      → LINKED  #4102 'King Kong' (1933) dir Merian C. Cooper  via tmdb(find 244) tt0024216  [director corroborated]  [id agrees]
#77   Heimat Fragments: The Women / Edgar Reitz
      → WOULD-CREATE tt0810894 'Heimat Fragments: The Women' (2006)  [no candidates]  [id supplied]
#42   Rebel Without a Cause / Nicholas Ray
      → REVIEW  id-disagreement: resolver tt0048545 [director corroborated] vs listed tt9999999
```

The tally gains one trailing line on a supplied-id import, and it is the deliverable of §2:

```
resolver vs supplied id:  agree 91 · disagree 2 · resolver had no verdict 7  (of 100 with ids)
```

## 7. Expected shape for Bergan (measured read-only, 2026-08-28)

Gate coverage was probed directly against the live catalog using the supplied ids alone:

| | n |
|---|---|
| link via gate 1 (a film holds that IMDb id) | 14 |
| link via gate 2b (`find_by_imdb` → TMDB id → holder) | **70** |
| absent, would create | 16 |
| supplied ids with no TMDB record at all | **0** |

The agreement rate is **not** predicted here — measuring it is the point of the run, and guessing it first would only anchor the reading.

Note what the 70 says: the catalog holds 4,495 TMDB ids against 807 IMDb ids, so gate 1 misses most of the time and **gate 2b carries this list**. That gate exists because of a single live case (*Intolerance*) found during the Cahiers rehearsal; here it does the bulk of the work.

## 8. Out of scope

`rank_label` and tied ranks · the `trust`/weight column and the weighted cross-list tally · any list beyond Bergan · re-fetching a list from its source URL · auto-ratifying agreements into the eval CSV (§2, deliberately never).

## 9. Gates (unchanged)

`uv run pytest` · `uv run ruff check .` · `uv run mypy` · `uv run python scripts/thumbprint_benchmark.py --assert` (baseline **n=571 / WRONG=0 / 92.0% over 526**) · `uv run python scripts/matching_benchmark.py --assert-dominance`. The eval CSV and the fixture are never hand-edited. Nothing here touches `domain/thumbprint.py` or `infrastructure/thumbprint_fetch.py`, so the thumbprint gate must not move.

## 10. Rehearsal

Same discipline as v1 (design §12): the whole import runs end to end against a **copy** of the live DB with `MOVIE_BRAIN_CONFIG_DIR` set on every command, the owner reads the full scorecard including the agreement line, and only then does anything run live — `lists import --apply` first, `lists create --apply` as a separate confirmed step.
