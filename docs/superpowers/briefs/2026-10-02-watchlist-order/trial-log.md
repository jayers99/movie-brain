# Trial log — Watchlist order (backlog 46)

2026-10-02: brief 0.9 and mockup-1 drafted from the five grill rulings; gap check point A next.

## Gap check (point A)

| # | Finding (kind) | Answer | Note |
|---|---|---|---|
| 1 | Panel says story 8 / "flip 8" for the On-a-list call, which is story 5 (story-untrue) | fixed | panel now says story 5, "flip 5" |
| 2 | Picked list and word search hide the arrows, not walkable (exclusion-to-walk) | story added | stories 11 and 12; mock-up gained a live list picker and search bar |
| 3 | ↑ ↓ in the open drawer step to another film; "no keys" not shown (exclusion-to-walk) | story added | story 9 reworded; owner ruling 6 (keys move the marked film with the drawer closed) became story 10 |
| 4 | No answer for a failed move, a reload, or variant B's pending presses (gap-unpictured) | story added | story 14 + "pretend the server is down" switch; brief says saved at every move; B's pending presses settle before any other click (the mock-up used to discard them on a chip or sort) |
| 5 | Un-star then re-star with Watchlist off sends the film to the top (gap-unpictured) | story added | story 13: a re-star in the same drawer returns the film to its place |
| 6 | "Only the film I moved moves" untrue under a swap (story-untrue) | fixed | a move is now an insert past the visible neighbour; story 4's ending and the trade-off line changed |
| 7 | Mock-up rows show a ★ badge the real rows lack, real badges missing (story-untrue) | fixed | rows now carry the real badges (lists, owned, best subscribed source, ♥) and the real RT % / IMDb formats |
| 8 | Chip order differs from the real bar (story-untrue) | fixed | Reachable, Rated, Criterion, Watchlist, Owned, On a list, Shop, Watched |
| 9 | A merge removes a watchlist row with no rule for its position (gap-unpictured) | fixed | Builder's pages: survivor's place wins, loser's row taken over if the survivor has none, never a hole |

Agent minutes: 5 · Findings: 9 · Fixed: 5 · Stories added: 4 · Declined: 0 · Not checked: check 4 (no outside service), variant B on the real app, checks 5–6 (point C only).

## Gap check (point A) — scoped re-check

1, 3, 5, 7, 8, 9 hold. 2 holds; 4 and 6 held in logic. The fixes introduced five defects:

| # | Finding (kind) | Answer | Note |
|---|---|---|---|
| N1 | List picker drawn left of the chips, labelled "All films"; real one sits before Clear, "— all films —", "My Ranking (N)" (story-untrue) | fixed | |
| N2 | The mark is never cleared (app.js sets `state.mark`, nothing unsets it), so once any drawer has been opened, plain ↑ ↓ under Watchlist always move a film (gap-unpictured) | fixed by the owner | ruling 7 (three-state row click), story 11 |
| N3 | Two fast failed presses leave the film one place moved (gap-unpictured) | fixed | rollback restores the last server-confirmed order |
| N4 | Un-star, step away and back, re-star → top, against the brief's "same drawer" rule (story-untrue) | fixed | the remembered place survives steps; only closing forgets |
| N5 | Leftover "swap" wording; story 2's "nothing else moves" (story-untrue) | fixed | also the MC "—" for a missing score |

Agent minutes: 3 · Re-check findings: 5 new · Fixed: 4 · Fixed by an owner ruling: 1. Per the checks README, no second re-check; anything left goes to the owner or the diagnostic checkpoint.

2026-10-02: owner chose variant A ("option a").

## Two-lineage gap check of brief 1.0 (point A, owner's request)

Codex (gpt-6-astra, high, 714 s, 11 findings) and Fable (7 findings) on the same snapshot of 1.0 (commit on `feature/STORY-46-watchlist-order`) and the 10 AM database copy; neither saw the other or this log.

| Finding | Label | Answer | Note |
|---|---|---|---|
| A click on another dimmed row steps the real drawer; the mock-up closed it (codex F6, fable 3) | both | fixed | stories 9, 11, 14 |
| Watched + Watchlist unpictured; 0 films today (codex F5, fable 6) | both | story added | 16 |
| Drag-and-drop only a line (codex F10, fable 5) | both | story added | 17 |
| "To top" only a line (codex F11, fable 7) | both | story added | 18 |
| Failed save lost a starred film from the saved order; retry jumped Lord of the Flies (F1) | codex-only | fixed | mock-up bug; builder: a failed write re-reads the server's order |
| Second un-star in one visit forgets the first's place (F2) | codex-only | fixed | per-film memory anchored to a neighbour; story 14 |
| Saved order / next morning not walkable (F3) | codex-only | story added | 19 + reload button |
| Keys inside the rating box; rating the marked film (F4) | codex-only | story added | 20; rating box now live in the mock-up |
| MC sort tie order differs from the real one (F7) | codex-only | fixed | title tie-break, reversed with the direction |
| Ruling 4 still says "swap" (F8) | codex-only | fixed | annotated with the 1.0 amendment |
| Hidden ninth film has no card (F9) | codex-only | story added | 21 |
| An arrow press moves the mark; brief silent (fable 1) | fable-only | fixed | story 10 + builder: a press sets `state.mark` (my call, flagged) |
| `director:` correction line with "undo" (fable 2) | fable-only | fixed | story 13 + note line in the mock-up |
| ⓘ on a marked row under the three-state click (fable 4) | fable-only | fixed | ⓘ always opens (my call, flagged); story 11 |
| Undo after a fresh star in between, index stale by one (fable "not checked") | fable-only | fixed | Undo anchors to the neighbour it sat above |

Codex 11 · Fable 7 · both 4 · codex-only 7 · fable-only 3 (+1 from its Not-checked) · false-positive 0 · declined 0. Fixed 9 · stories added 6. Brief → amendment 1.1.

2026-10-02: owner approved amendment 1.1 and kept the four calls (cards 10, 11, 14, 20) — "1". Brief frozen at 1.1.

## Gap check (point C) — two lineages

Claude (opus, 3 findings) and Codex (gpt-6-astra, high, 1086 s, 6 findings) on the same snapshot of the branch head and a fresh copy of the live database migrated to schema 33; neither saw the other.

| Finding | Label | Answer | Note |
|---|---|---|---|
| Story 14 untrue on the real catalogue: Title filter `fr` holds 133 films; ↓ from Capturing the Friedmans reaches Silent Friend (Claude 1, Codex F1) | both | fixed | story 14 rewritten on the real neighbours Intolerance and Moonlight (full list, no filter); test rewritten |
| An arrow press marks the film, so the next click on that row lets go instead of opening (Claude 2) | claude-only | fixed | ruling: only a mark left by closing the drawer is let go; a pressed mark opens on click — new story 22, flagged to the owner |
| Story 20's test leaves a move in flight at teardown, flaked once (Claude 3) | claude-only | fixed | the test waits for the saved order; fixed waits replaced by polling |
| Moves still queued are lost by a reload in that instant (Codex F2) | codex-only | declined | the local server answers each move in milliseconds; a reload has to beat it, and only a held request (as the checker staged) makes that reachable — story 19 stays |
| A star whose follow-up order read fails sorts the film last (Codex F3) | codex-only | fixed | the star answer now carries the whole order; no second request |
| A film un-starred elsewhere stays listed and marked after a failed move (Codex F4) | codex-only | fixed | the server's order is now the watchlist's membership truth on the page |
| The first click after typing a column filter does nothing (Codex F5) | codex-only | fixed | pre-existing on the dashboard (noted 2026-09-24); the filter's change event no longer re-renders when nothing changed |
| The mock-up's Watched chip is two-state; the real one cycles Watched → To study → off (Codex F6) | codex-only | fixed | mock-up chip and card 16's coach line |

Claude 3 · Codex 6 · both 1 · claude-only 2 · codex-only 5 · false-positive 0 · declined 1. Brief → amendment 1.2.

## Hands-on (point C copy, port 5557)

2026-10-02: owner walked the migrated copy — "looks good comit merge push". Story 22's call (a pressed mark opens on click) stands.
