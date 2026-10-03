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
