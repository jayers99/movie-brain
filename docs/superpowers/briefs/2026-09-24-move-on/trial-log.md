# Trial log — move on

Fourth trial of the version 2 process, upstream half; stories first, gap check at point A before the owner saw the page.

## Your active time

| When | What you did | Rough minutes |
|---|---|---|
| 2026-09-23 | asked for the behaviour (the Shop case) | 1 |
| 2026-09-24 | generalised it to any filter; asked for the best seed shape; pasted the entry prompt | 2–3 |
| 2026-09-24 | asked to see the page while the gap check was still running; walked it and chose B ("b") | unmeasured |

## Interruptions (each tagged by you: needed / not needed)

| # | What I brought you | Your tag |
|---|---|---|

## Decisions taken without asking (your standing rule: take the recommended answer and log it)

| # | Decision | Why |
|---|---|---|
| 1 | Story 5 reworded: on the real dashboard a chip cannot be pressed with the drawer open (the chips sit under the grey; the click closes the drawer). The story now pins exactly what find-my-row story 6 pinned, plus the close | the seed's wording described something the real control cannot do — same lesson as the three-way Owned chip last time |
| 2 | Story 8 added (the list runs out) | the seed named it in one line; it is an edge you can bump into, so it is a card you can walk |
| 3 | When the list runs out the drawer STAYS open (seed said: closes) | a drawer closing by itself is a jump; staying is the pasted-link state the dashboard already has, and the film's own control is where you would change your mind. Shown as story 8; named in the brief for you to overrule |
| 4 | Variant C is drawn as "one ↑ reaches the film that left" | the seed's third candidate was ↑, with the note that today ↑ lands on the film BEFORE the gap. As a home for "I change my mind" it only works if ↑ reaches the film that left, so that is what C shows; the note about the film before is what happens without C |
| 6 | The plan (`docs/superpowers/plans/2026-09-24-move-on.md`) went straight to the subagent-driven build without a plan review by him | his entry prompt fixed the sequence ("plan, subagent-driven build, …") and his standing rule sends implementation questions to the recommended answer; the stories are the contract he reviews |
| 5 | Recommendation: B, the undo line | visible, one click, says what happened, serves a rating and a star with the same line; C hides a rule inside a key whose hint reads "previous film"; A is today's route |

## Surprises and corrections (misunderstood intent · implementation defect · changed preference · new opportunity)

| # | What | Kind |
|---|---|---|
| 1 | The Shop list has changed since the Shop brief four days ago: Shoah is now first (it gained a store id), then Army of Shadows, Pan's Labyrinth, Summer of Soul, Nashville — 320 films, not 310. Stories 1 and 6 name today's order | none yet — grounding, before any build |
| 2 | BFI: Film Noir is unordered, so it sorts by Metacritic: Pursued (no Metascore) sits at index 48 between Where the Sidewalk Ends and 36th Precinct, not beside Out of the Past. The story names the real neighbours | the same trap the find-my-row trial log recorded |
| 3 | A first draft of the grounding picked the wrong list (`slant-noir-100`, the first slug containing "noir") and Pursued was "not on it". Caught because the story's film was missing from the list it names | agent slip, caught before the page was written |

## Probes used, and whether each changed a decision

| Probe | Decision it was meant to change | Did it? |
|---|---|---|
| The real dashboard on a read-only copy of this morning's database, driven by Playwright: the real order and count under Shop, Unrated by me, Watchlist, BFI: Film Noir, Owned on that list, and the real header counts | which films and neighbours the stories may name | yes — every name, neighbour and count in the stories was printed by the probe, not typed from memory |
| Reading the edit handlers in `app.js` | which drawer edits can drop a film at all | yes — three (rating, ★, ♡); the revisit flag, Unseen, Rank this and the verdict touch nothing a filter reads, so "any drawer write" in the seed narrows to three controls |
| Reading the backdrop's CSS and click handler | whether "a chip press with the drawer open" can happen | yes — it cannot; story 5 reworded (decision 1) |
| Headless rehearsal of the mock-up, every story in every variant, plus the step-away-during-the-call case | whether the page does what the cards say | see below |

## Gap check (point A)

Run on the 0.9 draft (commit 8cdedae), read-only on a snapshot and a database copy; the checker reproduced every name, neighbour and count in the eight stories on the real dashboard before listing what did not hold. He had already asked to see the page and chosen B while it ran, so the fixes below land in the 1.0 freeze rather than before his first look.

| # | Finding (kind) | Answer | Note |
|---|---|---|---|
| 1 | Undo of a wishlist landing after a step or a close made the mock-up's drawer jump back or reopen itself (gap-unpictured) | fixed | landing rule written into the brief and the mock-up: the row comes back at once; the drawer goes back only if it is still the drawer that carried the line; walkable from story 6's coach line |
| 2 | A failed Undo was words only (gap-unpictured) | fixed | the failure state is drawn (same words, Try again where Undo was) and walkable with a "pretend CheapCharts is down" switch on the page, which also fails the ♡ the way the real slot does |
| 3 | "Only the last edit has an Undo" was a list line, and it is the normal Shop workflow (exclusion-to-walk) | story added | story 9, in the checker's wording |
| 4 | Story 6 A said one click turns Shop off; on the real dashboard the first click only closes the drawer (story-untrue) | fixed | wording; A is set aside anyway |
| 5 | "Five to ten seconds" and the Undo's reverse call were uncited (provenance) | fixed / unverifiable | the stories now say "several seconds — an estimate, never timed"; the brief cites where the estimate comes from and says the real timing is measured at delivery by his own click. The duration itself cannot be verified in this trial: no credentials in any check environment, by design |
| 6 | Story 5 claimed "kept word for word"; the promise is the same, the words are not (story-untrue, low damage) | fixed | now "the same promise, its test re-run unchanged" |

Agent minutes: 35 · Findings: 6 · Fixed: 5 · Stories added: 1 · Declined: 0 · Not checked: any real CheapCharts call (no credentials); Back-button filter changes with a drawer opened from a link; the search box and column filters other than Title as drop-causing edits.

Re-check (scoped to the six, 14 agent minutes): 6 closed, 0 open. Three residuals, all fixed in the same commit: the landing rule now says "not stepped away or closed since pressing Undo" (a ↓ then ↑ back counts as stepping away — that is what the build's memory does); story 9's card is labelled "B only"; the last two unqualified "five to ten seconds" became "several seconds (untimed)".

## Delivery, 2026-09-24

Built test-first on `feature/STORY-44-move-on`: 21 Playwright tests in `tests/web/test_move_on.py` — the nine stories under their own names plus the brief's defaults and the five Review Focus lines — on their own 80-film server with a fresh fake wishlist account; four Shop chip tests amended (Shop brief 1.1). The load-bearing lines (the edit-path-only trigger, the landing rule's guard) were each proven by removing them. Whole suite 1827 passed (final head bfbc7d4), ruff clean; `mypy src` (the project's own scope, per `pyproject.toml`) carries one pre-existing error unrelated to this feature (`domain/search.py:296`, from the 2026-09-23 mpnet commit, a day before this branch); `mypy src tests` also surfaces pre-existing untyped-test debt across the whole suite, none of it introduced here. Interruptions during the build: **0**. Unverified: the real CheapCharts timing of a wishlist and its Undo (his click at the hands-on test); Safari; a window narrower than about 1,100 px.

## Gap check (point C)

Run on the branch head 67af1e0 (after the whole-branch review's fix wave) on a copy of the live database; the checker replayed the 20 tests (20 passed) and walked all nine stories by hand with the real films, 22 screenshots kept. Every count and neighbour held. The wishlist shapes could only be walked with a browser-side stub (no credentials, by design); the real add and remove are his click at the hands-on test.

| # | Finding (kind) | Answer | Note |
|---|---|---|---|
| 1 | Try again on a failed wishlist Undo showed "Couldn't reach CheapCharts." and "Reaching CheapCharts…" side by side while the retry ran (story-differs-on-screen) | fixed | the click now re-draws the whole line as the busy line, as the ♡ slot already did |
| 2 | An edit in the moved-to drawer that drops nothing left the EARLIER edit's Undo standing — rate The Conformist after un-starring Tokyo Story and the line still offered Tokyo Story's Undo (gap-unpictured) | fixed | ruling: the line belongs to the drawer's own last edit, so any edit landing in the open drawer retires it; pinned by `test_an_edit_that_drops_nothing_retires_the_earlier_undo`; brief decision row extended |
| 3 | Story 9's line reads with Summer of Soul's full title (story-differs-on-screen) | fixed | wording in the brief and the card; still one line |
| 4 | "Eight stories" survived in the delivery paragraph and the mock-up intro; screenshots not yet in the folder (story-untrue, low) | fixed | nine; screenshots committed (stories 2, 4, 6 in its rating shape — the wishlist shape needs his account) |

Agent minutes: 18 · Findings: 4 · Fixed: 4 · Stories added: 0 · Declined: 0 · Not checked: a real wishlist add or remove and its timing (no credentials in any check environment); a failed ★ Undo (only the rating variant was forced); Safari; narrow windows.

Re-check (scoped to the four, on the real app with the wishlist calls stubbed in the browser): 4 closed, 0 open; no breakage from the fix; a stale "stories 1, 4 and 6" in one decision row fixed after it.
