# Trial log — move on

Fourth trial of the version 2 process, upstream half; stories first, gap check at point A before the owner saw the page.

## Your active time

| When | What you did | Rough minutes |
|---|---|---|
| 2026-09-23 | asked for the behaviour (the Shop case) | 1 |
| 2026-09-24 | generalised it to any filter; asked for the best seed shape; pasted the entry prompt | 2–3 |

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

(pending)
