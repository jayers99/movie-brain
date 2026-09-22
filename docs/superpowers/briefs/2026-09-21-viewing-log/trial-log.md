# Trial log — a viewing log

First feature to run the gap checker (backlog 38) at point A, before the owner sees the stories and the mock-up. Chosen for that on 2026-09-21: the most controls to grid, the most exclusions he would bump into.

## Your active time

| When | What you did | Rough minutes |
|---|---|---|
| 2026-09-20 | described the log and what it is for; ruled the 0–10 stays per film | unmeasured |
| 2026-09-21 | picked the viewing log as the gap checker's first live test ("proceed with the viewing log") | 1 |

## Interruptions (each tagged by you: needed / not needed)

| # | What I brought you | Your tag |
|---|---|---|

## Surprises and corrections (misunderstood intent · implementation defect · changed preference · new opportunity)

| # | What | Kind |
|---|---|---|

## Probes used, and whether each changed a decision

| Probe | Decision it was meant to change | Did it? |
|---|---|---|
| Grounding on a read-only copy of the live records (the dashboard's own `/api/films/<id>` on a copy, plus `old_rating`, `unseen`, `my_ratings`) | which real films carry each story, and whether the drawer shows every rental | yes: three films hold two rental rows and the view keeps one; both Godzillas are owned AND unseen, which made story 5 sharper; 143 unseen films, so story 6 is common, not a corner |
| Headless rehearsal of the mock-up, every story, all three barometers, both month views | whether the page does what the stories say | run 2026-09-21 before the gap check; see below |
| Eight stories + one mock-up, three barometers, two month views (`mockup-1.html`) | A / B / C; 1 / 2; which stories are kept | pending: the page has not reached him |
| Gap check, point A (`docs/superpowers/checks/gap-check.md`, fresh agent on a snapshot of cd82765 + the live database) | what is untrue, unpictured or unwalkable before he reads it | yes: 16 findings, 12 agent minutes; two stories added (a rated film never logged; the morning after), story 6's ranker claim corrected, the date box's refusals and every failed write given an answer, Love and Anarchy's duplicate rental collapsed, After Hours drawn as gone from Criterion, the empty-chip state and the column sort made real on the mock-up. Cost to him: zero minutes |

## Gap check (point A)

Run 2026-09-21 on a snapshot of cd82765 with a copy of the live database (`scripts/gap_check_snapshot.sh HEAD … viewing-log-a`); the findings file is in the session scratchpad. Every finding answered; one fix wave (mock-up + brief), then a scoped re-check.

| # | Finding (kind) | Answer | Note |
|---|---|---|---|
| 1 | Story 6 says logging puts the film in the ranker; true for To Be or Not to Be only through its hidden Rank-this mark (story-untrue) | fixed | story 6 rewritten in brief and mock-up: the mark goes out; the ranker offers it because it is MARKED; a film neither owned, marked nor rated 6–10 is not in the pool. Mock-up now draws Rank this lit (real `rank_marked`) and the Tier row for tier films |
| 2 | Date box: moving a line onto a day that already has one, a future date, a blank (gap-unpictured) | fixed | rule added: refused with a toast, old date put back (mock-up does it; brief names 409 / 400) |
| 3 | Switching to B after *Didn't like* in C lit *Liked* (story-untrue, mock-up defect) | fixed | A/C and B are two views of one record: felt + tags ↔ step; story 3 now honestly shows B keeping one rung |
| 4 | Watched chip on an empty log: the real table would be blank (gap-unpictured) | fixed | agent default: an empty-result row for every chip set (*No film matches.*), *No viewing logged yet.* under Watched; mock-up text matched |
| 5 | The morning after is never pictured (gap-unpictured) | story added | story 10, walkable: the page moves to 2026-09-22 |
| 6 | Failed PUT / DELETE, note length (gap-unpictured) | fixed | decision table: snap back to what the server holds, toast per write, 200-character cap (`maxlength` on the mock-up) |
| 7 | Rated with no rental, 363 of 378 films, only a list line (exclusion-to-walk) | story added | story 9, Dragon Inn, in his voice as the checker wrote it |
| 8 | Love and Anarchy's two rows are one rental twice (story-untrue) | fixed | history collapses same-date same-stars rows; brief's count corrected (two real second rentals, one duplicate) |
| 9 | Rentals not counting as viewings only a panel line (exclusion-to-walk) | story added | folded into story 7: Switchblade Sisters is not in the Watched list |
| 10 | ✕ on a film's only line under Watched leaves the list mid-drawer (gap-unpictured) | fixed | story 7 names the Shop rule (row leaves, drawer stays, ↓ carries on); brief decision row |
| 11 | After Hours is gone from Criterion; mock-up drew it live (story-untrue) | fixed | mock-up draws the `gone` badge and *Gone from Criterion* from the real `departed` flag |
| 12 | Story 1's "nothing else changes" untrue under month view 2 (story-untrue) | fixed | story 1 names the Watched cell changing |
| 13 | "The export carries no played dates" not provenanced (provenance) | fixed | reworded: the export ASKS for name, year, duration only; whether TV.app would answer a played date was not tried |
| 14 | `set_unseen` drops placements only when marking (story-untrue, brief wording) | fixed | decision row corrected; I Am Cuba keeps tier 1 |
| 15 | "named below" pointed at nothing (gap-unpictured) | fixed | reload / persistence in the failed-save decision row |
| 16 | Column "sortable — simulated" did not sort; real sort's empties undescribed (gap-unpictured) | fixed | mock-up header sorts; never-logged films last both ways, in story 7 and the brief |

Agent minutes: 12 · Findings: 16 · Fixed: 13 · Stories added: 3 · Declined: 0 · Not checked: TV.app's played-date property (outside the snapshot); point C checks (nothing built); Seven Samurai was dropped from the mock-up (no story used it).
