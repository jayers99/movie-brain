# Thumbprint T2 handoff — edition-year films + A/B/C review flow

**Written:** 2026-08-25, end of the T1 session. **For:** a fresh session. **Status of the
repo:** `main` @ `5f2431d`, clean, pushed. **Status of the live DB:** schema v11, claims
backfilled, all 85 raw `Title (YYYY)` films retired; snapshot `movie-brain.db.bak-post-t1`.

## Read first (in this order)
1. `CLAUDE.md` + `.claude/rules/thumbprint.md` (the resolver is DARK; gate before change).
2. `docs/superpowers/research/2026-08-25-thumbprint-design.md` — binding memo (§1 identity,
   §2 grammar, §4 A/B/C contract, §7 migration steps, §8 owner decisions).
3. `docs/superpowers/specs/2026-08-25-thumbprint-resolver-design.md` + the plan
   `docs/superpowers/plans/2026-08-25-thumbprint-t1-resolver.md` (status note at the top has
   every live number from T1).

## What T1 delivered (don't rebuild)
- `domain/thumbprint.py`: `parse_title` (editions / embedded year / alt titles), `make_query`,
  `resolve()` = ALG3. `infrastructure/thumbprint_fetch.py`: `CandidateCache` + `CandidateFetcher`
  (same key scheme offline and live). `application/thumbprint.py`: `backfill_claims`,
  `review_detail(verdict)` (the one JSON format for A/B/C rows). `application/repair.py`:
  `repair_twins`. Migration 011: `claim` table, `films.title_norm`, `films.kind`.
- Gate: `uv run python scripts/thumbprint_benchmark.py --assert` → n=482, 0 wrong, 94.8% auto.
- Live: 5,419 claims (criterion 3,050 / metacritic 1,511 / apple 858, 70 with `edition_label`,
  **0 with `edition_year`**); dispositions 102; open reviews: tmdb `no-match` 225, metacritic
  `expected-miss` 96, apple-tv `year-drift` 51, + 18 small metacritic reasons.

## T2 scope (memo step 2 + the review flow it needs)

### A. The 16 edition-year films (memo said 15; live count today is 16)
Films whose `films.year` is an edition/re-release year, keyed by eval group C (`verified`).
Read-only check today — **10 of them have an undisposed clean twin of the same work already
in the DB**, so step 2 is mostly *merge into the work + carry the edition on the claim*, not
a year edit:

| film | films.year | work year | tt | clean twin in DB |
|---|---|---|---|---|
| #3393 Eyes Without a Face [re-release] | 2003 | 1960 | tt0053459 | #1867 |
| #3459 Piccadilly [re-release] | 2004 | 1929 | tt0020269 | #1091 |
| #3498 Overlord [re-release] | 2006 | 1975 | tt0073502 | #1942 (NOT #4269 = 2018 remake) |
| #3508 Mafioso [re-release] | 2007 | 1962 | tt0056210 | #1436 |
| #3582 I Vitelloni [re-release] | 2003 | 1953 | tt0046521 | #1864 |
| #3745 The Umbrellas of Cherbourg (re-released) | 2004 | 1964 | tt0058450 | #2324 |
| #4048 Lawrence of Arabia (Restored Version) | 1989 | 1962 | tt0056172 | #3086 |
| #4303 Goodfellas (Remastered Feature) | 2015 | 1990 | tt0099685 | #3276 |
| #4599 The Exorcist: Extended Director's Cut | 2000 | 1973 | tt0070047 | #4598 |
| #3517 Donnie Darko: The Director's Cut | 2004 | 2001 | tt0246578 | #4404 is *another edition* (Anniversary Special Edition, 2001) — two edition rows, no plain work row |
| #3461 Quai des Orfèvres [re-release] | 2002 | 1947 | tt0039739 | none (alt title Jenny Lamour) |
| #3999 How the Grinch Stole Christmas: The Ultimate Edition | 2015 | 2000 | tt0170016 | none |
| #4070 Phantasm: Remastered | 2016 | 1979 | tt0079714 | none |
| #4293 Ghost In the Shell (25th Anniversary Edition) | 1996 | 1995 | tt0113568 | none |
| #4409 Blade Runner (The Final Cut) | 2007 | 1982 | tt0083658 | none (the memo's worked example) |
| #1909 SCENES FROM A MARRIAGE: Theatrical Version | 1973 | 1974 | tt6725014 | none — owner Q2: theatrical film is a distinct work from the TV series `tt0070644`; check whether a series row exists before touching |

None of the 16 has a TMDB link. Two shapes of fix, both through the existing verbs:
- **twin exists** → `merge_film(edition → work)`; the edition's claim moves to the work, then
  set `claim.edition_year = old films.year`. (Overlord: pick #1942, never #4269.)
- **no twin** → the edition row *becomes* the work: retitle to `parse_title().base`,
  `films.year` → work year (via `update_film_year`, which already handles key collisions),
  `external_ids imdb` = tt, `claim.edition_year` = old year. Donnie Darko: merge one edition
  into the other and retitle the survivor "Donnie Darko" 2001.
- Guard: eval group C is the contract — a film whose computed action disagrees with its
  `expected_tt` is skipped loudly (same pattern as `repair twins` csv-mismatch).

### B. Schema for step 2
- `external_ids` PK `(film_id, authority)` must loosen so a work can carry several claims per
  authority (memo §1 — first needed when two Apple editions of one work share a film). Claims
  already allow it; `external_ids` still does not. New migration 012; keep
  `UNIQUE(authority, value)`. Wrap in BEGIN/COMMIT; table rebuild (SQLite can't drop a PK).
- Consider `claim.edition_year` writer on the repo (`set_claim_edition_year(claim_id, year)`).

### C. `review resolve --pick A|B|C | --tt X | --none` (memo §4)
Not built. `review_detail()` already produces the JSON; T2 adds: `review list` rendering the
A/B/C table from `detail`, `resolve` actions that write `external_ids imdb/tmdb` and append an
eval row `(title_ingested, year, source → tt, verified_by=human)`. This is the drain for the
38 `proposed` eval rows (owner Q1) and for step 3's 45 A/B/C cases — build it in T2 so step 3
has somewhere to land. Stays per-authority; `--none` = verified unkeyed (standing decision).

## Process rules that held in T1 (keep them)
- Spec → plan → code (TDD) → **rehearse on a scratch copy of the live DB**
  (`cp ~/.config/movie-brain/movie-brain.db $SCRATCH/; cp -r appletv $SCRATCH/;
  MOVIE_BRAIN_CONFIG_DIR=$SCRATCH uv run movie-brain …`) → show the dry run → owner **yes** →
  apply in batches (`--limit N`, `--yes` only as the stand-in for the interactive prompt after
  approval) → paste before/after counts. The scratch rehearsal caught three real bugs in T1.
- Never edit the eval CSV to make the gate green. Never run `repair twins --apply` again
  expecting work (idempotent, 0 groups).
- Use `_plain` (no Rich markup) for any log line that starts with `[verdict]`.

## Paste-ready entry prompt
> T2 of the thumbprint work: read `docs/superpowers/handoffs/2026-08-25-thumbprint-t2-handoff.md`,
> the memo `docs/superpowers/research/2026-08-25-thumbprint-design.md` (§1, §4, §7 step 2, §8)
> and CLAUDE.md. Write the T2 spec (16 edition-year films → work identity with
> `claim.edition_year`; migration 012 loosening `external_ids` PK; `review resolve
> --pick/--tt/--none` + A/B/C `review list`), then the plan. Gate stays green. No live-DB writes
> without scratch rehearsal → announce → approve → diff, one batch at a time. Resolver stays dark.
