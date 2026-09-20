# Task brief — "Find my row" (backlog 24)

**Version 1.1 — amended 2026-09-20 after your first use (story 7, below; 1.0 frozen the same day).** You chose variant C on the mock-up [mockup-1.html](mockup-1.html) ("Good work. Option C looks great."). A cold read-back by a fresh agent reconstructed the intent correctly and found 18 things, all folded in below; one of them corrects story 6 (see the note under the stories). From here the brief changes only by amendment (1.1, 1.2 …). *Where the mock-up and this brief disagree, the brief wins.* Second trial of the process in `docs/superpowers/research/2026-09-19-human-in-loop-diet-v2.md`. The one thing this trial changes on purpose: **the stories come first** — first on this page, first on the mock-up page, and each one can be walked in the mock-up with one click. The stories you keep become the automated tests, word for word.

## Your page

### The stories

All six happen on your real *BFI: Film Noir* list. **You chose variant C, so all six ship.** ("Works in" records which mock-up variant showed each: **A** = white while open · **B** = A, and the row stays marked after you close · **C** = B, plus ↑ ↓ to step through films.)

| # | Story | Works in |
|---|---|---|
| 1 | **I can see my row while the drawer is open.** I am going down BFI: Film Noir and click Out of the Past. The drawer opens and the list behind it goes grey — except the Out of the Past row, which stays white. I can see exactly where I am. | A B C |
| 2 | **I can get back to where I was.** I close the drawer. The row I just had open is still marked, so my eye lands on it and I carry on to Pursued, the next film down. | B C |
| 3 | **There is one mark, and it moves.** I open Pursued. The mark leaves Out of the Past and sits on Pursued. Only one row is ever marked — it always means "the last film I looked at". | B C |
| 4 | **I scroll away and come back.** With the mark on Out of the Past I scroll up to M at the top of the list, then back down. The mark is still there. | B C |
| 5 | **I step through films without closing.** With the drawer open on Out of the Past I press ↓. The drawer changes to Pursued, the white row moves down with it, and the list scrolls to keep it in view. ↑ goes back. | C |
| 6 | **The awkward one: my marked film leaves the list.** The mark is on Pursued, which I do not own. I press the Owned chip. Pursued drops out of the list, so no row is marked — and nothing jumps. I click the chip round to off again: the mark is back on Pursued. | B C |
| 7 | **One click switches films** *(amendment 1.1 — your words after using it: "it takes two clicks where it should take one")*. The drawer is open on Out of the Past. I click another film's row in the grey behind it. The drawer changes to that film at once and the white row moves there — no closing, no second click. | added after delivery |

*Story 6, corrected after the read-back:* the mock-up's Owned chip had two states; the real one has three (off → Owned → Not owned → off), so "press Owned again" became "click the chip round to off". Pursued is in fact back, and marked, one click earlier, under Not owned. And "nothing jumps" means movie-brain never moves the list; when a list gets shorter than where you were, the browser itself pulls you up to its end, as today.

**Outcome.** When clicking through films, never lose your place in the list — while the drawer is open, and (stories 2–4) after it closes.

**What wins when things trade off.** Quiet. One row looks different; nothing else on the page changes.

**Why it is more than the white row.** Your request was the white row (story 1). Your *reason* was "difficult to get back to where I was" — and that moment comes after the drawer closes, when nothing is dimmed and a white row is invisible on a white page. Hence the mark (stories 2–4 and 6), and, by your choice of C, the stepping (story 5).

**What deliberately does not ship.** No trail of every film you opened. No scrolling the list to a film opened from a link or the Back button (a click or a step nudges the list only as far as needed to show the whole row). No mark that survives a reload or travels in a copied address. No change to the drawer itself beyond one small grey hint, "↑ ↓ previous / next film", beside the ✕. No other keys (no j/k, no Home/End, no page-at-a-time).

| Behaviour | Status |
|---|---|
| The open row stays white above the dim | demonstrated in the mock-up with the real dashboard's own colours, dim and drawer; the real drawer must move one layer up so the white row cannot paint over it |
| The mark survives scrolling | simulated — the real list draws only the rows on screen and redraws as you scroll; ordinary to build |
| The mark after closing (grey fill, dark bar at the left edge) | simulated; approved as shown in the mock-up you chose — the exact grey and bar width stay a preference |
| ↑ ↓ stepping, with the Back button still behaving | simulated; the real drawer keeps browser history per opened film, so this is the one part with real build risk |

**What you will see at delivery.** The dashboard running with the change (on your live data, read-only — nothing in this feature writes); the kept stories passing as tests under their own names; screenshots of stories 1, 2 and 6; a plain list of anything unverified. Then you try it; only after your say-so is it merged. No database change is involved.

## Builder's pages

**Decision provenance**

| Decision | Whose |
|---|---|
| The open film's row stays white behind the drawer | your choice, 2026-09-20 |
| Variant C: white while open + marked after close + ↑ ↓ stepping | your choice, 2026-09-20, on the mock-up (I recommended B; C is B plus stepping) |
| The after-close mark is a grey fill (`#f2f2f2`, the chip colour) with a 4px dark bar at the row's left edge; in B and C the white row carries the same bar | agent default — shown in the chosen mock-up, not objected to |
| The white row is not clickable; a click on it closes the drawer like any other click outside it | agent default (keeps "click outside closes" whole, and stops the list scrolling under an open drawer) |
| One mark only; it means "the last film I opened"; opening another film moves it | agent default, story 3 |
| The mark lives in memory only: not in the URL, gone on reload; Clear does not remove it | agent default — it is a bookmark, not a filter |
| A marked film that is filtered out shows no mark and moves nothing; it returns with the film | agent default, story 6 |
| Opening a film from a URL or the Back button never scrolls the list | agent default |
| The mark is drawn by the row renderer from state, so virtual scrolling cannot lose it | agent default, not visible |
| ↑ ↓ are inert while typing in an input, textarea or select; they stop at the ends of the shown list; they follow the list exactly as it is filtered and sorted on screen; they do nothing when the drawer is closed (the page scrolls as today) | agent default — the first two were listed on the mock-up page |
| ↑ ↓ do nothing when the open film is not in the shown list (opened from a link while a filter hides it) | agent default, NOT shown in the mock-up |
| A step scrolls the list only as far as needed to keep the white row fully visible below the sticky header; the drawer itself starts at its top for each film | agent default — shown in the mock-up |
| **Back button after stepping:** a step REPLACES the open film in the browser history instead of adding to it, so one Back (or ✕ / Esc / a click outside) closes the drawer however many films were stepped through, and the address bar always names the film on screen | agent default, NOT shown in the mock-up — name it at delivery |
| Fast repeated presses: the white row moves at once on every press; only the last film's details are drawn (the existing `drawerSeq` guard) | agent default |

**Added at the freeze, from the cold read-back (all agent defaults, none shown in the mock-up unless said):**

| Decision | Note |
|---|---|
| While the drawer is open, ↑ ↓ (without Cmd / Alt / Ctrl / Shift) always belong to stepping — also at the ends of the list and when the open film is not in the shown list, where they do nothing | **cost to name at delivery:** the arrow keys no longer scroll the drawer's own content; the wheel, Space and Page Down still do |
| A film opened from a link or the Back button sets the mark too; the first ↓ after opening a far-off film jumps the list to its neighbour | name at delivery |
| If the open film drops out of the list while its drawer is open (you un-star it with the Watchlist chip on, or rate it with "Unrated" on), the white row goes and ↑ ↓ go quiet until you close | quiet over clever; name at delivery |
| A drawer opened from a pasted link, stepped, then closed: Back reopens the LAST film stepped to, not the link's film | accepted; name at delivery |
| Sorting, searching or picking a list moves nothing: the mark rides with its film; rating a film in its row does not move the mark | — |
| A row is lifted white only while it sits wholly below the sticky two-row header (decided per redraw, so it can never paint over the header); a click on a half-hidden row nudges it clear first | not visible otherwise |
| A step whose film cannot be loaded puts the white row, the address and the mark back on the film still on screen, and shows the existing "Film not found" toast | — |
| While the drawer is open a row click does nothing (today a keyboard Enter on a focused ⓘ could push a second history entry) | — |
| The hint beside ✕ lives in `templates/index.html`; the drawer's `h2` gets right padding so a long title cannot run under it; the toast moves above the drawer's new layer | widens the authority below by one file |
| State: a separate `state.mark`; a row is white when `id === state.openFilm` AND the drawer is showing (`readUrl` sets `openFilm` before the drawer exists); `hideDrawer` is the one close choke point and redraws rows; a step sets `openFilm` at once, computes the next step from it, and rewrites the URL with `replaceState` (guarded — Safari throws past 100 calls in 30 s) leaving `drawerOpenPushed` alone — `openDrawer(id, false)` must NOT be reused for a step, it would break the Back button | not visible |
| Step scrolling is arithmetic (`index × ROW_H` against the header's height), because the target row may not be in the DOM | not visible |
| Tests: a separate ~80-film server fixture on one ordered list, with M first and Out of the Past / Pursued side by side deep enough (index ≥ 30) to be evicted from the DOM; never grow the shared 10-film `seed()`. Story 4 asserts the row really left the DOM. Story 1 asserts real paint — a screenshot pixel of the open row is white while its neighbour is dimmed — not just z-index numbers | not visible |

**Amendment 1.1 (2026-09-20, authorised by your request; the behaviour is your choice, the rest are agent defaults, none previewed — a follow-up from use gets light ceremony):**

| Decision | Whose |
|---|---|
| A click on another film's dimmed row switches the drawer to it instead of closing | your choice |
| A switch behaves exactly like a ↑ ↓ step: the film is replaced in the browser history, so one Back / ✕ / Esc still closes the drawer however many films were clicked through | agent default — name at delivery |
| Anywhere in the row counts: under the dim a title link or a rating box is just the row (it switches; it does not open Criterion or take a rating) | agent default — name at delivery |
| Every other click on the grey still closes: the page header, the chips, the column headers (even with rows scrolled beneath them), empty space, and the white row itself | agent default |
| The mouse pointer turns into a hand over a dimmed row, and nowhere else on the grey — the one hint that rows are now live. Dimmed rows do not light up on hover | agent default — name at delivery |

**Taste boundaries.** Hard: standing dashboard preferences — filled means active, no glyphs, nothing else on the page moves. Preference: the mark's exact grey and bar width.

**Execution authority.** The builder may decide anything not visible. `app.js`, `app.css`, `templates/index.html` (the hint only) and the Playwright suite only; no schema, no API, no live-database step. Not without a separate yes: merge, push.

**Repository grounding.** `static/app.css`: `#drawer-backdrop` z-index 3, `#drawer` z-index 4, `tbody tr:hover` `#fafafa`, page `--bg:#fff`. `static/app.js`: `rowHtml` builds each `<tr data-id>`; `renderRows` redraws the visible window on every scroll; `openDrawer` / `closeDrawer` / `hideDrawer` own `state.openFilm` and the history bookkeeping (`drawerOpenPushed`); the `tbody` click handler ignores `a, input`. Tests: `tests/web/test_dashboard.py` (Playwright against a seeded server). Also: `#toast` z-index 5; sticky `thead th` in two rows (`top:0`, `top:31px`); `readUrl`, `syncUrl` and the person-link handler also touch `state.openFilm`; neither `openDrawer` nor `hideDrawer` redraws rows today; `openDrawer` never resets the drawer's scroll. Mock-up lesson worth keeping: a row class named `bar` collided with the MOCK-UP's own `.bar` rule (the dashboard has none) and wrecked the row's layout — caught by rehearsing the mock-up headlessly before showing it; keep the specific names `lit`, `marked`, `edge`.

**Recovery.** Done = every kept story passes as a Playwright test named after it, the whole suite, ruff and mypy are green, and the owner has tried it.
