# Task brief — a chip for films worth buying (backlog 25)

**Version 1.0 — frozen 2026-09-20.** You chose variant B on the mock-up [mockup-1.html](mockup-1.html) ("option b is great"). A cold read-back by a fresh agent reconstructed the intent correctly; its 14 findings are folded in below. From here the brief changes only by amendment. *Where the mock-up and this brief disagree, the brief wins.* Third trial of the process in `docs/superpowers/research/2026-09-19-human-in-loop-diet-v2.md`; stories first, as in "Find my row".

**Amendment 1.1 — 2026-09-24, from backlog 44 (brief `../2026-09-24-move-on/brief.md`).** Stories 3 and 4 are superseded: a wishlisted film still leaves the list the moment the click lands, but the drawer no longer stays on it — it moves on to the film that took its place, as ↓ would have (move-on story 1), and "I change my mind" is the undo line in the drawer it moved to (move-on story 6). The tests under those two names now assert the amended behaviour; `test_closing_on_a_film_that_left_the_list_leaves_no_mark` became `test_closing_after_a_move_on_marks_the_film_the_drawer_moved_to`.

## Your page

### The stories

All on your real catalogue (a copy from the morning of 2026-09-20). **You chose variant B: a film on your wishlist is decided, so it is not in the list.** The chip is called "Shop" — my pick of the three names offered; you did not pick another. (The mock-up's variant A, where wishlisted films stay with their heart, is set aside; the A notes below are kept only as the record of what you compared.)

| # | Story | A vs B |
|---|---|---|
| 1 | **One press finds the films worth buying.** I press Shop. The list drops from 5,007 films to 310 (A: 343): Army of Shadows, Pan's Labyrinth, Summer of Soul… None owned, none rated, none on a service I have, every one for sale on Apple. | counts differ |
| 2 | **Nothing I can already watch, nothing I have judged.** M is for sale on Apple, but it is on the Criterion Channel — not in the list. The Big Sleep I own — not in the list. The Long Goodbye I rated 7 — not in the list. Schindler's List is on Netflix, which is not one of my services — it IS in the list. | same |
| 3 | **I browse with the arrows and wishlist as I go.** With Shop on I open Army of Shadows and press ↓ to Pan's Labyrinth. I press ♡ Wishlist it. B: its row leaves the list behind the drawer — it is decided; the drawer stays on it, saying ♥ Wishlisted; I press ↓ and carry on to Summer of Soul. A: a heart appears on its row, nothing moves, ↓ carries on to Summer of Soul. | differs |
| 4 | **I change my mind.** Still in that drawer, I press ♥ Wishlisted. The film comes off my wishlist. B: its row comes straight back, in its old place, white. A: the heart leaves its row. | differs |
| 5 | **It stacks with my other chips.** I press Shop and On a list. 109 films are left (A: 129) — the canon I could buy — best first: Do the Right Thing, Nashville, The Narrow Margin. | counts differ |
| 6 | **The awkward one: a film already on my wishlist.** The Leopard has been on my CheapCharts wishlist for a while. B: it is not in the list — it is decided. A: it is in the list, at the very top, wearing its heart, with 32 other films I already wishlisted. | differs |

**Outcome.** One press turns the dashboard into a browse-to-buy queue: only films you could buy and have no other way to watch, so that ↑ ↓, the trailer and ♡ Wishlist it do the rest.

**What wins when things trade off.** The list holds only what is still undecided and actionable: every film in it shows the ♡ Wishlist it button. (Shows — not "is guaranteed to work": a film whose stored store id Apple has since removed answers "Couldn't reach CheapCharts.", and a film you wishlist on CheapCharts' own site stays in the list until the next reload.)

**What deliberately does not ship.** No "not interested" / pass button. No trailer link. No price, no sale flag, no sorting by price. No new page. No fix for the films Apple sells that the store lookup misses (backlog 23).

| Behaviour | Status |
|---|---|
| Not owned · not rated today · for sale on Apple (= holds a store id) | demonstrated — all three are on every film in today's payload |
| Not on a service I have (your 14, Criterion included) | demonstrated on the copy: 343 films qualify, 310 not yet wishlisted, 109 of those on a list |
| B: a film leaves the list the moment it is wishlisted, and ↑ ↓ carry on from where it was | simulated — today ↑ ↓ go quiet when the open film leaves the list; B changes that for every chip |
| The chip's name and its place in the bar (after Rewatch) | simulated; three names offered |

**What you will see at delivery.** The dashboard with the chip; the kept stories passing as tests under their own names; a plain list of anything unverified. Then you try it — including one real wishlist click while browsing — and only after your say-so is it merged. No database change.

## Builder's pages

**Decision provenance**

| Decision | Whose |
|---|---|
| The filter: not owned, not on a subscribed streaming service, for sale on Apple, not rated | your choice, 2026-09-20 |
| Variant B: a wishlisted film is not a candidate; it leaves the list the moment it is wishlisted and returns the moment it is un-wishlisted | your choice, 2026-09-20, on the mock-up |
| The name "Shop" | agent default — offered beside two others on the mock-up you approved, marked as my pick, not objected to; one word to change |
| "For sale on Apple" = the film holds an `itunes` store id — not TMDB's `apple-tv-store` listing (2 films differ) — so the list and the ♡ button can never disagree | agent default, named on the mock-up page |
| "A service I have" = a current listing on any `svod` service with `subscribed = 1`, plus a current Criterion Channel listing (departed does not count) | agent default — the same meaning the row's green badge already has |
| "Rated" = `my_rating` is set, 0 included; the 2004–08 stars do not count | agent default, named on the mock-up page |
| A plain chip (on / off), after Rewatch, before the list picker; stacks with every other chip; key in the URL like any chip; Clear resets it | agent default, shown in the mock-up |
| Default sort unchanged (Metacritic, then RT, then IMDb); with On a list also on, canon score leads as always | agent default |
| One predicate in `domain/filters.py`, mirrored in `app.js`'s `CHIP_PREDICATES`, button in `index.html` — the lockstep rule | agent default, not visible |
| ↑ ↓ continue from the open film's last index when it is no longer in the shown list (↓ = the film that took its place, ↑ = the one before) | agent default, shown in the mock-up |

**Added at the freeze, from the cold read-back (agent defaults; none shown in the mock-up unless said):**

| Decision | Note |
|---|---|
| Chip key `shop`, last in `_PREDICATES`; the button carries a tooltip like Rewatch's | not a taste call |
| Both mirrors are built from RAW fields — `services` entries with `kind == "svod"` and `subscribed`, or `criterion and not departed` — never from `best_source`: the Apple store row is itself `subscribed = 1` (a services test without the `svod` check would empty the list), and `best_source` is `None` in the Python unit tests, where a predicate reading it would pass vacuously | not visible |
| If you ever un-subscribe the Criterion Channel in the registry, this chip would still treat a Criterion film as watchable while the green badge would not | hypothetical; noted, not handled |
| ↑ ↓ after the open film has left the list: the dashboard remembers the open film's index (re-found BY ID on every filter pass while it is present, clamped to the list); ↓ opens the film now at that index — the one that took its place — and ↑ the one before it. A film that was never in the list (a pasted link to a wishlisted film with Shop on) leaves the arrows quiet, as today | shown in the mock-up for the wishlist case |
| While the open film is out of the list nothing is white; a click on any dimmed row still switches | as the mock-up behaved |
| Closing the drawer on a film that has left the list leaves NO grey mark — the mark rides with its film (find-my-row story 6) — so after wishlisting and closing, your place in the queue is not marked | **owner-visible; name at delivery** |
| Once you step away from a film you just wishlisted, Shop gives no way back to it (turn Shop off, or use the CheapCharts wishlist) | name at delivery |
| Pressing ↓ during "Reaching CheapCharts…" (5–10 s live) is fine: the earlier film leaves the list when its click lands, the white row stays on the film now open. If that earlier click FAILS, its "Couldn't reach CheapCharts." lands in a drawer no longer on screen — the film simply stays in the list with no heart | **silent failure; name at delivery** |
| The ↑ ↓ change is for every chip: rate the open film with Unrated on, or un-star it with Watchlist on, and ↓ carries on the same way | one non-Shop test proves it |
| Story 4 is tested as open → wishlist → un-wishlist with no step in between (story 3 ends on another film) | — |
| Tests: their own module server with a fresh `FakeAccount()` (the shared 10-film seed holds NO film that matches Shop, and giving one an id would break the reachable counts); the real numbers 5,007 / 310 / 109 cannot be tested and are re-cast on the seed | not visible |
| "No API change" means no route or field changes; `/api/config`'s chip list gains the key | — |

**Execution authority.** The builder may decide anything not visible. `domain/filters.py`, `app.js`, `index.html`, tests, plus the docs that go stale (`CLAUDE.md`, the backlog, two code comments). No schema, no route or field change, no CheapCharts call in any test. Not without a separate yes: merge, push.

**Repository grounding.** `domain/filters.py::_PREDICATES` / `CHIPS` (pinned by `tests/unit/test_filters.py::test_chip_names_are_stable`); `app.js::CHIP_PREDICATES`, `stepDrawer` (does nothing when `findIndex` is −1), `applyFilters`, the wishlist click handler (patches `film.wishlisted`, calls `applyFilters`, rewrites the slot); `updateFilmLocal` REPLACES the film object in `state.films`, so the open film must be tracked by id; `index.html` chips row (pinned by `test_chip_labels_and_order`); fakes in `tests/web/conftest.py` — `FakeAccount.add_item` / `remove_item` sleep 1 s (a deterministic busy window), add always fails for `DELTA_ITUNES`. Verified on the live copy: among films not owned, `best_source.subscribed` and the raw-fields test agree on all 5,007 films.
