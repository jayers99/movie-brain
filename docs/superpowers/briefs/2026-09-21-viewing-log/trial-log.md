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

### Scoped re-check (point A, same day)

Relaunched with `Re-check only findings: 1–16` on a snapshot of ce0d6fc. About 6 agent minutes. **13 of 16 closed.** Three were still open, all mock-up defects in the fix itself, not in the brief:

| # | Still open because | Answer |
|---|---|---|
| 3 | B lit *Liked* for C's *Didn't finish*, and *Didn't like* after story 8's tag-then-felt walk: the mock-up stored a step and the felt handler ignored the tags | fixed: B's rung is now DERIVED from felt + tags on every draw, never stored (brief decision row says so); rehearsed both walks |
| 10 | the mock-up's ↓ after ✕ under Watched went to the top of the list, not the gap | fixed: the mock-up keeps the open film's index like the real `openIndex`; rehearsed: ✕ on the third film, ↓ opens the film that took its place |
| 13 | the mock-up panel still carried the round-1 wording | fixed: panel matches the brief |

Two seams it also saw, both fixed: the brief's two API rows disagreed on a same-day POST (now: POST on a held date answers 409, the strip's same-day edit is a PUT on today's line); the panel said "the ranker does not move" while story 6 said the film rejoins its queue (now: placements and tiers do not move, a pooled film rejoins the queue).

The spec says the checker never loops, so these three were verified by the builder's own headless rehearsal, not a third run; they are listed here as the diagnostic-checkpoint items and closed. Owner cost across both runs: zero minutes.

**Summary line for the owner:** Checked: 16 findings, 13 fixed, 3 stories added, 0 declined. Not checked: whether TV.app can answer a played date; everything point C covers (nothing is built yet).

## Round 2 (2026-09-27)

The owner picked the story up again ("let's shape backlog item 27") and reshaped the entry path in a spoken brain dump; three rulings followed (title-only ladder, words stored in the database, proceed to stories). `shaping.md` §7 has the record; `brief-2.md` and `mockup-2.html` are the round-2 page.

### Your active time (round 2)

| When | What you did | Rough minutes |
|---|---|---|
| 2026-09-27 | brain dump in a user-story voice (dictation through the agent → deterministic commands); ruled the identification ladder; picked database storage; "proceed" | unmeasured, under 15 |

### Probes used (round 2)

| Probe | Decision it was meant to change | Did it? |
|---|---|---|
| Copy of the live database + its dashboard (`/api/films/<id>` for the story films) | which real films carry each story; what the drawer shows today | yes: The Blue Angel is watchlisted and has a 2006 rental (story 1 shows both); Sans Soleil is already rated 9 and in tier 2 (story 6 became "move it", not "place it"); two Solaris, both unrated |
| `films add` dry runs on the copy (tt0018737, tt0022183, tt0019415, tt0019648) | which film the catalogue truly lacks for story 4 | yes: Pandora's Box is HELD under a curly apostrophe (the ladder normalises because of it); Mädchen in Uniform WOULD-CREATE |
| Headless rehearsal of `mockup-2.html`, every story, every turn | whether the page does what the stories say | run before the gap check: 10 stories, 81 turns, no page errors; chip order, empty state and column sort checked |

### Gap check (point A, round 2)

Run 2026-09-27 on a snapshot of 1bb93ea with a copy of the live database (`scripts/gap_check_snapshot.sh HEAD … viewing-log-r2-a`); the findings file is in the session scratchpad. Every finding answered; one fix wave (brief 2.0 → 2.1, mock-up, four stories added), then a scoped re-check.

| # | Finding (kind) | Answer | Note |
|---|---|---|---|
| 1 | Every Criterion command names `criterion-channel`; the registry slug is `criterion` (story-untrue) | fixed | slug corrected everywhere; the panel and the decision table list the real slugs |
| 2 | The real drawer and table never refresh after the CLI writes; the mock-up shows them changing (story-untrue) | fixed | decision added: the page re-fetches the open film on window focus / visibilitychange and patches its row; story 1 now says "switch back to the browser and the drawer has refreshed itself"; the mock-up's sys beat says which page updates when |
| 3 | `title_norm` is NULL for 729 visible films incl. Solaris 2002, so the ladder as written finds one Solaris (story-untrue) | fixed | the ladder no longer reads the column: one normaliser (`thumbprint.title_norm`) applied to the dictated title and every candidate's stored title at query time; grounding corrected; a test named for the empty-column case |
| 4 | A stale drawer signal can log the wrong work (73 same-title groups); `viewings open` after a browser close prints the last film (story-untrue) | fixed | the signal is a 30-second heartbeat trusted for two minutes, so a closed browser reports nothing; the same-title-live-drawer case is named on the panel as the owner's ruling and its accepted risk (say the year or director) |
| 5 | Merged losers share titles with 18 live films; the ladder says nothing about them (gap-unpictured) | fixed | candidates are canonical films only (no merged / tombstone disposition); grounding names the 18 |
| 6 | "Blue Angel" / "Godzilla versus Gigan" → NO-FILM → the skill proposes creating a held film (exclusion-to-walk) | story added | story 11: NO-FILM lists the nearest titles (the search bar's title stage), the agent asks "this one?", `films add` only when none fits; `HELD` named as the backstop |
| 7 | Two normalisers named; they disagree on 120 films (gap-unpictured) | fixed | one function, both sides, at query time (see 3); `norm_title` struck from the ladder row |
| 8 | The mock-up's rating box is read-only; the real one is a writer the brief does not retire (story-untrue) | fixed | the box stays a writer (decision row); the mock-up's box and rows are editable again, the left-out note says so |
| 9 | "Apple TV", "HBO", "Max" name two or three slugs; the skill never asks (gap-unpictured) | fixed | mapping rule through the film (owned → store, streams on Apple TV+ → plus; two fits or none → ask); story 7 gains the beat that says it |
| 10 | A double bill, a sentence with no title, a second service for a logged day — no answer (gap-unpictured) | story added | story 12, the checker's three cards: two commands; ask before any rating; a line's service is never overwritten (the mock-up's imitation had overwritten it — fixed) |
| 11 | No way to remove one note (exclusion-to-walk) | story added | `viewings remove VID --note N` added to the verb (one flag, cheaper than explaining it away); story 13 |
| 12 | Import request, a plan, an essay: only lines in "Not in this build" (exclusion-to-walk) | story added | story 14, the checker's three cards; the watchlist star stays the drawer's only writer |
| 13 | The `films add --apply` transcript was not captured from a real run; the dry run's answer not filed (provenance) | fixed | CREATED lines rewritten to the verb's own format from `films.py` / `cli.py` / `catch_up.line()` and labelled as such on the page (no real film is created without his yes); the four dry runs filed in `films-add-dry-runs-2026-09-27.txt`; the missing-keys refusal named in the panel and the skill row; the mock-up mints #5432 (max id 5,431) |
| 14 | 24 hidden films are loggable but unshowable under Watched (gap-unpictured) | fixed | the read model's filter widens to current-or-rated-or-viewed; decision row + a web test |
| 15 | "ALL rental rows" puts Love & Anarchy's duplicate back (story-untrue) | fixed | same-date same-stars rows collapse (round 1's rule restored) in the decision row, the API row and the panel |
| 16 | The rating rule contradicts stories 1 and 5 ("about a six", "Ten.") (gap-unpictured) | fixed | rule reworded: one whole number however hedged is written; two numbers or a fraction is a question |
| 17 | Header reachable count, a future-dated line after story 8, director "from TMDB at creation" (story-untrue, small) | fixed | header 5,074; the mock-up's clock only moves forward (story 8 leaves the page on the 28th); director arrives with OMDb, wording fixed |

Agent minutes: 30 · Findings: 17 · Fixed: 13 · Stories added: 4 · Declined: 0 · Not checked: the drawer signal across two databases (nothing built); TMDB's answer beyond the dry run's own line; the Watched column in the filter header row; everything point C covers.

### Scoped re-check (point A, round 2, same day)

Relaunched with `Re-check only findings: 1–17` on a snapshot of d6c5437. About 10 agent minutes. **15 of 17 closed.** Two halves still open and three defects the fixes had introduced, all fixed in 2.2 and verified by the builder's own headless rehearsal (the checker never loops), listed as the diagnostic-checkpoint items and closed:

| # | Still open because | Answer |
|---|---|---|
| 6 | the "versus" half: the real `title_hits("Godzilla versus Gigan")` returns nothing (FTS ANDs every word, no title holds "versus"); the mock-up's own word filter hid it | fixed: the nearest-title lookup drops articles and vs/versus before asking `title_hits`, then falls back to a normalised substring; the decision row says so and names the failing call |
| 13 | the CREATED line: `films.py` appends the keying status and `keying.py::KEYED_OK` is `matched` / `adopted` / `collision`, so a real run prints `… (1931)  matched`, not `keyed` | fixed: mock-up and grounding read `matched`; the grounding names the three statuses |
| A | story 13 walked after story 12 removed note 4 (the Kanopy remark) while the owner asked to scratch the Jannings one | fixed: the story finds the Jannings note by content and removes THAT number; the card says `--note N` |
| B | story 14 said Solaris (2002) was open one turn before the page opened it | fixed: the beats reordered |
| C | the reworded "two numbers → ask" rule would make story 2's "tier one … tier two" a question | fixed: the rule is "a number offered as a rating"; tiers, years and counts stay in the note (panel + decision row) |

Owner cost across both runs: zero minutes.

**Summary line for the owner:** Checked: 17 findings, 13 fixed, 4 stories added, 0 declined; re-check closed 15, the last 2 and 3 fix-introduced slips fixed and rehearsed. Not checked: the drawer signal across two databases and everything point C covers (nothing is built yet).

**Built 2026-09-27** on `feature/STORY-27-viewing-log`, plan `docs/superpowers/plans/2026-09-27-viewing-log.md`; point C gap check next, on a migrated copy, before the owner's hands-on test.
