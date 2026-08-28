# Thumbprint T5 handoff — memo step 5: switch the ingesters to `resolve()`

**Written:** 2026-08-28, end of the T4 session. **Branch:** `feature/T4-thumbprint-nomatch` (merge
pending owner's word). **Live DB:** schema v12; snapshot `movie-brain.db.bak-pre-t4`.

## What T4 delivered (don't rebuild)
- `movie-brain repair nomatch [--apply] [--yes] [--limit N]` (`application/repair_keys.py`, which
  also now holds `repair_disagreements`): worklist = open `tmdb/no-match` rows (+ promoted rows as
  `review-open`); verdicts `keyed / unlinked / linked / match / review / review-open / conflict`;
  `review` promotes the SAME row to durable `no-match-reviewed` (`Repository.promote_review`);
  `collision` counts as applied; `--apply` ends with `rebuild_no_match_queue`; session candidate
  cache `<config_dir>/nomatch-cache.json.gz` (fixture never written).
- `rebuild_no_match_queue` treats a resolved `no-match-reviewed` row as a standing decision.
- `review resolve --pick` falls back to `find_by_imdb` for an OMDb-only candidate.
- Spec/plan/rules: `docs/superpowers/specs/2026-08-27-thumbprint-t4-nomatch-design.md`,
  `docs/superpowers/plans/2026-08-27-thumbprint-t4-nomatch.md`, `.claude/rules/thumbprint.md`.

## Live numbers (2026-08-28, after apply + drain + 2 syncs, 0 conflicts)
| what | before | after |
|---|---|---|
| open `no-match` | 201 | **10** (9 twin `conflict`s: #142/#421 dubbed versions, #955, #2163, #2271, #2757, #3966, #4316, #4487 — each holds an id its twin already holds → merge path, not keying; + #180 *endings* imdb-only, no TMDB record) |
| open `no-match-reviewed` | — | **48** (deliberately left open, see below) |
| external ids imdb / tmdb | 661 / 4,347 | 778 / 4,476 |
| `tmdb.found=0` | 211 | ~80 |
| eval CSV | 529 rows | 558 rows (+29 `F-human`: 9 `--pick`, 8 `--tt`, 12 `--none`) |
| gate | n=528 / 0 / 92.0 % | n=557 / 0 / **87.3 % — FAILS the 90 % auto floor** (selection bias: ratified rows are the resolver's residue by construction; owner decision pending — see below) |

Auto matches (99) were spot-checked by the owner from a table (all approved); 6 commerce films
adopted TMDB's original year (Apple/MC years were re-release dates).

## Open decision: the auto-rate floor
Proposed: score `F-human` rows for WRONG only and exclude them from the auto-rate denominator
(auto rate over believed/verified rows = 92.0 %); alternatively lower the floor. Whatever is
chosen, update `.claude/rules/thumbprint.md`'s baseline line and `scripts/thumbprint_benchmark.py`.

## The 48 open `no-match-reviewed` rows (step-5 material)
- Series / episodes (Q2 `kind=series`, key by IMDb series id): Dekalog #3082, Small Axe ×3
  (#3140/#3373/#3604), Hollow Crown ×4 (#4399/#4400/#4445/#4501), Agnès de ci de là Varda ×5,
  When the Levees Broke #3430, Dr. Dolittle ×3 (#1284–#1286, Reiniger — TMDB 283246 is the whole).
- Multi-part one work: La Roue parts 2–4 (#799–#801; part 1 keyed tt0014417), Lemmings 1&2
  (#376/#388, Haneke TV — TMDB search misses), No Place Like Home #1 and #2 (#1418).
- Edition of an existing unkeyed work: #2355 *The Killing of a Chinese Bookie: 1978 Version* →
  work #2841 (1976, unkeyed) — needs a merge path for colon-form editions.
- Real films TMDB/IMDb index poorly (`--tt` once ids are confirmed): Farewell My Love #605,
  The Short and Curlies #1799, You Were Like a Wild Chrysanthemum #2332, Solfatara #1318, The Hall
  of Lost Footsteps #1696, Haiti: The Way to Freedom #149, Artaud Double Bill #1026, Max by Marcel
  #1622, Le chien du Monsieur Michel #1551, Africa the Jungle… #1044, Symbiopsychotaxiplasm: Two
  Takes #2920, Egungun #848, Convergences #834, Another World #342, Free #444, Truth #764, First
  #1739, Spacewoman #425, Big Ben Beat #426, Opened Ending #437, Aerie #450, ping pong… #468,
  Europe Endless 1 #350, I Held the Truth #773, Marseille (keyed), Life on the CAPS (keyed).
- `review list --reason no-match-reviewed` renders them with A/B/C where candidates exist.

## Traps learned in T4
- zsh does not word-split `$var` in `for`/`set --` — resolve rows one call per line.
- Rich wraps piped stderr at 80 cols: use `COLUMNS=600` when capturing verb logs to parse.
- `review resolve --tt` writes the imdb id BEFORE `record_tmdb_match`; an `id-conflict` there
  leaves the tt on the film and queues an id-conflict row → resolve THAT row with `--film <holder>`
  (Eve's Bayou #269 → #1150 went this way).
- `--none` is permanent ("no such work"): only for supplements/programmes/videos, never for a real
  film the index merely misses.
- Curly apostrophes: search films by `title_norm`, not `lower(title)`.

## Step 5 shape (memo §7)
Switch the Criterion walk, Mode-B promotion and `owned import` to `resolve()` behind the gate;
expected end state of the director-less residue ≈25 verified-unkeyed + ≈35 keyed. Keep the
one-at-a-time rehearsal protocol (scratch `MOVIE_BRAIN_CONFIG_DIR`, simulated sync, owner yes).
