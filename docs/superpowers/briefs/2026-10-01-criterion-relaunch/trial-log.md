# Criterion relaunch — trial log

## Gap check (point A)

Snapshot `fbd134c` + a copy of the live DB (2026-10-01). The checker could not write its findings file (subagent write refusal); the builder saved its hand-back verbatim into the run's `FINDINGS.md`.

| # | Finding (kind) | Answer | Note |
|---|---|---|---|
| 1 | "124 directors come back" — 117 already show OMDb's; D8 would change them (story-untrue) | fixed | D8 fills only where neither `films.director` nor OMDb's exists (7); story 9 rewritten |
| 2 | One JW failure stops the whole sync, maybe nightly (gap-unpictured) | fixed + decision packet | JW 404 is now an answer (review row `no-record`, walk carries on; captured 404 shape); a network failure still fails the walk; whether the rest of sync runs after a Criterion failure goes to the owner |
| 3 | Story 7 example Les 3 boutons is keyed (story-untrue) | fixed | example dropped; story names the two real routes (non-match, JW 404) |
| 4 | Leaving chain uncaptured (provenance) | fixed | `home-2026-10-01.html`, `leaving-october-31.html`, `jw-playlist.0WbeKrrA.full.json` (28) captured by `probe_captures.py` |
| 5 | Catalog provenanced from one trimmed page; drift facts unsaved (provenance) | fixed | full walk `catalog-2026-10-01.json`, last page `all-films-results.lastpage.json` (key absent), `drift.tsv` via `probe_drift.py` (97/72/9, 43 departed, 68 404, 4 supplements), junk years listed |
| 6 | Bridge drift list needs the catalog (gap-unpictured) | fixed | D3: the bridge walks the catalog once first |
| 7 | Story 1 counts have no design (story-untrue) | fixed | D11: `SyncResult.criterion_arrived/departed/reviews` + one CLI line |
| 8 | A failed leaving call leaves 39 departed films labelled "September 30" (gap-unpictured) | fixed + story added | D6 clears `leaving_date` on every Criterion listing the walk did not stamp; story 11 |
| 9 | `--create` / `--dismiss` unspecified; dismissed mediaid looked up nightly (gap-unpictured) | fixed | D9: `--create` mints under Criterion's title/year/director and keys; D5: dismissed/open mediaids skipped with no JW call |
| 10 | Link forms unconfirmed (provenance) | fixed | `/films/<id>` 308 → slugged page 200 captured; `/search?q=` renders client-side, so `search_url` stays unset (rollout step removed) |
| 11 | Supplements vanish, no story (exclusion-to-walk) | story added | story 15 (Contras' City #351) |
| 12 | `--full` no-op, no story (exclusion-to-walk) | story added | story 16; help text named in D11 |
| 13 | New titles never reach the dashboard, no story (exclusion-to-walk) | story added | story 17 (Riotsville, U.S.A. #130); the search claim the checker suggested was not verified, so it was left out |
| 14 | Story 4 "since October 1" shows the sync date (story-untrue) | fixed | story 4 says arrivals are dated by the sync that saw them |
| 15 | Review queueing outside the single transaction (story-untrue) | fixed | D6: open/resolved check in staging, insert inside `record_criterion_walk` |

Agent minutes: 6 · Findings: 15 · Fixed: 12 · Stories added: 4 (two with fixes) · Declined: 0 · Not checked: 429 behaviour (never seen), two leaving pages at once

### Scoped re-check (snapshot dc4f3c0)

Closed: 2, 3, 4, 5, 6, 7, 8, 9, 14, 15. Still open: 1 (only 3 of the 7 director-less films are still on Criterion), 10 (the 308 and 404 answers were console output only). New from the fix wave: A — the home page also links the undated `/discover/leaving-soon`; B — `--create` on a `no-record` row had no data to mint from; C — `--create` skipped the gates, and a no-token night queued permanent review rows; D — the departure estimate over-counted and missed multi-part works collapsing onto one mediaid; E — the bridge's 21 minutes counted sleeps only.

Answered before the owner's review (not re-checked again, per the one-re-check rule — point C covers them): 1 fixed (D8 names the 3 films; story 9); 10 fixed (`probe-captures-output.txt`); A fixed (D7: dated pages only); B fixed (review `detail` carries what Criterion showed; `--create` mints from it); C fixed (`--create` runs the D5 gate ladder; no-token nights skip without a review row); D fixed (D13 rewritten, multi-part works → `held` reviews, story 18 added); E fixed (25–30 minutes).

## Gap check (point C) — two lineages, snapshot 4754c6c

Snapshot: `git archive 4754c6c` + a read-only copy of the live DB taken 2026-10-02 (schema 32, no migration on the branch) + the bridge observation file. No credentials. The Claude checker applied the bridge and walked the live site (no TMDB token) on a private copy of the copy; the Codex checker stayed on the unbridged copy and replayed read-only.

| # | Finding (kind) | Source | Label | Answer | Note |
|---|---|---|---|---|---|
| 1 | Departed films vanish from the dashboard unless rated or viewed — Some Came Running #33 (watchlisted), The Man Who Fell to Earth #1703 (owned), the 15 episode films, ~209 in all; stories 5, 15, 18 say "show departed" (story-untrue) | claude 1 · codex 1, 5, 17 | both | fixed (story) | Owner ruling 2026-10-02: "If I've rated them, you mark as departed and keep the record. If I haven't rated them, they just disappear." The rule (`list_views`: current, rated or viewed) stays; stories 5, 15, 18 now say the film leaves the dashboard |
| 2 | Story 2's drift counts 97/72/9 are the 293-link sample; the full dry run prints 214 (99 year · 105 title · 10 both) (story-untrue) | claude 2 · codex 9 | both | fixed (story) | |
| 3 | "Various" for #1766/#1777 unpictured in story 9 (gap-unpictured) | claude 3 · codex 10 | both | fixed (story) | Owner chose plan C ruling C1 option 1 on 2026-10-02 |
| 4 | Two-id films link the wrong version after the bridge — Dr. Dolittle English → German, Eve's Bayou → director's cut (story-differs-on-screen) | claude 4 | claude-only | fixed | the bridge keeps the listing URL of the old link the film already showed |
| 5 | A departed film's "Open on Criterion" opens a 404 (gap-unpictured) | claude 5 | claude-only | declined | dashboard change out of scope (spec §7); the owner kept the departed rule as it was; noted for the backlog |
| 6 | `--create` warns, not refuses, on a resemblance (story-untrue) | claude 6 · codex 4 | both | fixed (story) | owner ruling L1 (Plan B); story 7 now says so |
| 7 | No unbind verb; the dry run does not name the two-id films (exclusion-to-walk) | claude 7 · codex 3 (part) | both | fixed (naming) / declined (verb) | the dry run names each two-id film; a wrong binding is repaired by hand, one at a time |
| 8 | `review list` shows a Criterion row as a bare mediaid, no title/year/director (story-untrue) | codex 2 | codex-only | fixed | |
| 9 | The brief's apply path omits the Darwin repair (gap-unpictured) | codex 3 | codex-only | fixed (story) | story 2 names the repair before `--apply` |
| 10 | Review rows are one per mediaid, not one per film (story-untrue) | codex 6 | codex-only | fixed (story) | |
| 11 | Eve's Bayou reads "Leaving" while the director's cut stays (gap-unpictured) | codex 7 | codex-only | true-declined | Plan B ruling L2 |
| 12 | Story 1's sync is refused until the bridge is applied (gap-unpictured) | codex 8 | codex-only | fixed (story) | stories 1–2 put the bridge first |
| 13 | Command states not walkable (repeat / failure / next morning) (gap-unpictured) | codex 10 | codex-only | true-declined | terminal feature, no mock-up by design; outcomes are in the stories and the BDD scenarios |
| 14 | No Playwright replay of the stories on a post-sync catalogue (gap-unpictured) | codex 11 | codex-only | true-declined | the owner's hands-on test is that replay |
| 15 | #1777's JW answer has no saved capture (provenance) | codex 12 | codex-only | fixed | `jw-media.dYbj5nMq.json` captured |
| 16–21 | Exclusion stories 12, 13, 14, 15, 17, 16 have no walkable card (exclusion-to-walk) | codex 13–16, 18, 19 | codex-only | true-declined | each is already a story card stating the outcome; nothing to click for a terminal feature |
