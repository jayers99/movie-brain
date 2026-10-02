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
