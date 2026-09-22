# Findings — "Find my row" brief 1.0 + mockup-1.html (gap check, 2026-09-21)

Checked against the snapshot at `bt/findrow` (feature not yet built there) and the database copy at `bt/cfg-findrow/movie-brain.db`, with the real dashboard run on port 5801 (stopped). Scripts and screenshots: `bt/findrow-check1.py` … `check4.py`, `bt/findrow-real-list-around-ootp.png`, `bt/findrow-real-ootp-drawer.png`, `bt/findrow-real-ootp-1440x800.png`.

---

## 1. Stories 2, 4 and 5 name neighbours the real list does not have — BFI: Film Noir is an UNORDERED list

- **Kind:** story-untrue
- **Where:** brief stories 2, 4, 5 (and the narrative of 3); mock-up stories 2, 4, 5 and the mock-up's whole table order
- **Claim:** Story 2: "I carry on to **Pursued, the next film down**." Story 4: "I scroll up to **M at the top of the list**." Story 5: "I press ↓. The drawer changes to **Pursued**." Mock-up header: "showing 45 of 45 (the first 45 of the list's 100)" — the mock-up draws the list in file order, M first, Out of the Past (rank 36) directly above Pursued (rank 37).
- **Evidence:**
  - `film_list` row: `bfi-100-film-noirs | BFI: Film Noir | … | ordered = 0`. The API confirms it on Out of the Past's own payload: `('bfi-100-film-noirs', ordered=False, rank=36)`.
  - `app.js::listRank` returns `null` for an unordered list, so `compare` falls through to the default hierarchy (Metacritic desc → RT desc → IMDb desc → title). Real order with the list picked (`findrow-check1.py`, `window.MB.state.filtered`): row 1 Touch of Evil; row 22 The Asphalt Jungle; **row 23 Out of the Past; row 24 The Postman Always Rings Twice**; … **row 43 M**; … row 48 Where the Sidewalk Ends; **row 49 Pursued**; row 50 36th Precinct. Screenshot `findrow-real-list-around-ootp.png` shows Out of the Past between The Asphalt Jungle and The Postman Always Rings Twice.
  - Out of the Past and Pursued are 26 rows (936 px) apart; the table viewport is 751 px at 1500×900, so Pursued is off-screen when Out of the Past is on it.
  - Brief line 74 plans the test fixture as "one **ordered** list, with M first and Out of the Past / Pursued side by side" — the tests would pass on a fixture shaped like the mock-up, not like the owner's list, so the discrepancy survives "the kept stories passing as tests".
- **What the owner would see at delivery:** he picks BFI: Film Noir, opens Out of the Past, presses ↓ and gets The Postman Always Rings Twice; Pursued is not the next film, and M is 20 rows below him, not at the top.
- **Confidence:** high

## 2. The commonest use — rating a film under "Unrated by me" — makes the open film leave the list, and then the feature goes dark: not a story, not walkable

- **Kind:** exclusion-to-walk (also gap-unpictured: "film that LEAVES the shown list while the control is in use")
- **Where:** brief, builder's page, "Added at the freeze" row 3 ("If the open film drops out of the list while its drawer is open … the white row goes and ↑ ↓ go quiet until you close — quiet over clever; name at delivery") and decision row "↑ ↓ do nothing when the open film is not in the shown list … NOT shown in the mock-up". Nothing on the owner's page; no story card; no mock-up path.
- **Claim:** the white row goes, ↑ ↓ go quiet, and (by the story-6 rule) a film not in the list carries no mark after close.
- **Evidence:**
  - Code path: the drawer's own `My rating` box is `input.rating[data-id]` (`detailHtml`, app.js:643); `commitRating` → `updateFilmLocal` → `applyFilters()` (app.js:471-476), which recomputes `state.filtered`. With the Rated chip on "Unrated by me" (`unrated: f.my_rating == null`, app.js:50) the film is dropped from the list the moment the rating lands.
  - Real data: 91 of the 100 BFI noir films are unrated (9 have `my_ratings` rows: Maltese Falcon 10, Double Indemnity 10, Gun Crazy 8, Sunset Boulevard 10, The Killing 9, The Long Goodbye 7, Chinatown 8, Taxi Driver 8, L.A. Confidential 6). Out of the Past (#3831) is unrated and owned — the film the stories are built on.
  - The mock-up's only chip is Owned and its drawer has no rating box (`left-out` stub), so the owner cannot reach this state by walking it.
- **What the owner would see at delivery:** going down "Unrated by me" on BFI noir, he opens Out of the Past, types 8 in the drawer, presses ↓ — nothing happens; he closes — no row is marked anywhere; the very "where was I" moment the feature exists for is the one where it shows nothing.
- **Story card that should exist (owner's voice):** *"I rate a film while I am stepping. Rated is on 'Unrated by me' and I am going down BFI: Film Noir. I open Out of the Past, give it an 8 in the drawer. It is rated now, so it leaves the list. What happens to the white row, to ↓, and to the mark when I close?"* — with the answer the owner has chosen shown in the mock-up.
- **Confidence:** high

## 3. Story 6's "nothing jumps or scrolls" is false — the list jumps in the mock-up AND on the real dashboard

- **Kind:** story-untrue
- **Where:** brief story 6; mock-up story 6
- **Claim:** "I press the Owned chip. Pursued drops out of the list, so no row is marked — **and nothing jumps or scrolls.**"
- **Evidence (`findrow-check3.py`):**
  - Mock-up, Walk it on story 6 then press Owned: `#wrap.scrollTop` 1032 → **0**; 45 rows → 11. The list snaps to the top because 11 rows (396 px) no longer fill the 593 px viewport.
  - Real dashboard, list picked, scrolled to Pursued (scrollTop 1353), press Owned: scrollTop 1353 → **108**; "Showing 100" → "Showing 22". Same clamp: `applyFilters` → `renderRows` keeps `wrap.scrollTop`, but the browser clamps it to the new, shorter content.
- **What the owner would see at delivery:** he presses Owned and the list jumps to (near) the top — the opposite of the sentence he approved and the test would be written from.
- **Confidence:** high

## 4. Story 6's second press is not "off" — the real Owned chip is a three-way cycle

- **Kind:** story-untrue
- **Where:** brief story 6; mock-up story 6 and `#chip-owned`
- **Claim:** "I press Owned again: the mark is back on Pursued." The mock-up's chip is a two-state toggle (`state.owned = !state.owned`, mockup line 244) and reads "Owned" throughout.
- **Evidence:** real chip markup `data-cycle="owned,not_owned" data-labels="Owned|Owned|Not owned"` (`findrow-check1.py` CHIPS). Measured (`findrow-check3.py`): 1st press → label "Owned", filled, Showing 22, Pursued gone, Out of the Past present; **2nd press → label "Not owned", filled, Showing 78, Pursued back, Out of the Past GONE**, URL `chips=not_owned`; 3rd press → off, Showing 100.
- **What the owner would see at delivery:** the mark does come back on Pursued after the second press, but the chip is still filled and now reads "Not owned", the owned films (including Out of the Past from stories 1–5) have vanished, and a third press is needed to get his list back — none of which the mock-up showed.
- **Confidence:** high

## 5. "↑ ↓ no longer scroll the drawer" is a real loss on real drawers, and the mock-up's drawer can never show it

- **Kind:** exclusion-to-walk
- **Where:** brief, builder's page, "Added at the freeze" row 1 ("cost to name at delivery: the arrow keys no longer scroll the drawer's own content; the wheel, Space and Page Down still do"). Owner's page: not mentioned; mock-up panel says only "The list still cannot be scrolled while the drawer is open (except in C, where ↑ ↓ scroll it for you)".
- **Evidence (`findrow-check4.py`, viewport 1440×800):**
  - Real drawers that overflow with the cast collapsed: Touch of Evil 871/800, The Long Goodbye 823/800 (2 of 13 sampled BFI noir films); Out of the Past overflows once "⋯ N more" cast is opened (874/800).
  - Today, after a click inside the drawer, ↓ ×3 scrolls the drawer: `#drawer.scrollTop` 0 → 74. So the arrows are a working way to read a long drawer now.
  - The mock-up drawer is an overview-only stub: `scrollHeight == clientHeight` (700/700), so pressing ↓ in the mock-up never had a drawer to scroll — the owner has not experienced the trade.
- **What the owner would see at delivery:** on Touch of Evil he opens the full cast, presses ↓ to read the bottom of it, and the drawer switches to The Maltese Falcon instead.
- **Story card that should exist (owner's voice):** *"I want to read the rest of a long drawer. Touch of Evil's cast is longer than my window. I press ↓ to see the rest — and the drawer changes to the next film. To read the rest I use the wheel, Space or Page Down."*
- **Confidence:** high

## 6. Back after stepping reopens the last stepped film with the list not scrolled to it — "name at delivery", not walkable

- **Kind:** exclusion-to-walk
- **Where:** brief owner's page "No scrolling the list to a film opened from a link or the Back button"; builder's page rows "Back button after stepping … NOT shown in the mock-up — name it at delivery", "A film opened from a link or the Back button sets the mark too; the first ↓ after opening a far-off film jumps the list to its neighbour — name at delivery", "A drawer opened from a pasted link, stepped, then closed: Back reopens the LAST film stepped to — accepted; name at delivery".
- **Evidence:** the mock-up has no history at all (`openDrawer`/`closeDrawer` touch neither `pushState` nor `popstate`, mockup lines 227-235), so none of the three Back behaviours can be walked. On the real dashboard `popstate` → `openDrawer(state.openFilm, false)` (app.js:863) and nothing scrolls the list. With the list picked, Out of the Past is row 23 (~828 px down); a drawer reopened by Back after the page has been scrolled back to the top leaves its white row off-screen, and the brief's own rule says the first ↓ then "jumps the list to its neighbour".
- **What the owner would see at delivery:** he steps Out of the Past → Postman → They Live by Night, closes with ✕, then presses Back expecting Out of the Past: the drawer reopens on They Live by Night, no white row is in view, and his first ↓ yanks the list somewhere he did not choose.
- **Story card that should exist (owner's voice):** *"I press Back after stepping. I opened Out of the Past, pressed ↓ twice, and closed the drawer. I press the browser's Back button. The drawer comes back on the last film I stepped to, not Out of the Past; the list does not move to it; ↓ from there scrolls the list to its neighbour."*
- **Confidence:** high (behaviour is by the brief's own rules; the exact film on reopen depends on the build)

## 7. The mark's reload rule is a list line, and reload is a daily reflex

- **Kind:** exclusion-to-walk
- **Where:** brief owner's page "No mark that survives a reload or travels in a copied address"; mock-up panel bullet 3. No story, no Walk it (the mock-up cannot be reloaded into a state).
- **Evidence:** `readUrl` rebuilds all state from the URL (app.js:200-221) and the brief keeps `state.mark` out of it (decision row "The mark lives in memory only"); a `film=` link reopens the drawer via `onBoot` (app.js:866) and nothing scrolls the list to the row.
- **What the owner would see at delivery:** after a reload the grey row is gone and, if the drawer was open, it reopens with the list at the top and the white row off-screen.
- **Story card that should exist (owner's voice):** *"I reload the page. The mark was on Out of the Past. I reload (or open the same address in a new tab). The mark is gone; if the drawer was open, it reopens but the list starts at the top."*
- **Confidence:** medium (the behaviour is certain; how often it bites is a judgement)

## 8. Three hearts in the mock-up are not on the wishlist mirror in this day's database

- **Kind:** story-untrue (mock-up data claim)
- **Where:** mock-up panel: "Real in this mock-up: the 45 films, their years, directors, scores, list counts, owned marks, services and hearts — read from a copy of your database today."
- **Evidence (`findrow-check2.py`, `sqlite3`):** mock-up `wishlisted: true` for Scarlet Street (#4807), He Walked by Night (#4893), Criss Cross (#4895); `/api/films` and `cheapcharts_wishlist` say false for all three (the table holds 53 films; of the 45, only The Lady from Shanghai #4808 and Born to Kill #4882 are in it). Every other field of the 45 rows matched the real payload exactly, including the badge rule (`best_source` shown only when subscribed and not owned).
- **What the owner would see at delivery:** two fewer hearts among the 45 than the mock-up showed — cosmetic, but it is the one line in the mock-up that says "real".
- **Confidence:** medium (hearts refresh from CheapCharts on every dashboard start, so the mock-up may have been built from a different read than this copy)

## 9. In the mock-up any click on a row opens the drawer; on the real dashboard a Criterion film's title is a link that leaves the page

- **Kind:** story-untrue
- **Where:** mock-up `#tbody` click handler (lines 238-241: only `input` is ignored); story 4 sends the owner to M.
- **Evidence:** real `rowHtml` renders the title as `<a href=… target="_blank">` when `f.url` is set (app.js:146) and the `tbody` click handler ignores `a, input` (app.js:718). Among the 45 mock-up films, M, La bête humaine, Le jour se lève, Detour and Odd Man Out carry Criterion URLs (`findrow-check2.py` LINK lines). Out of the Past and Pursued do not, so stories 1–3 and 5–6 are unaffected.
- **What the owner would see at delivery:** clicking on the word "M" opens criterionchannel.com in a new tab and no drawer, mark or white row appears; clicking the same row's year or director opens the drawer.
- **Confidence:** high (pre-existing behaviour, but the mock-up imitates the row click without it)

## 10. The mock-up's "the list cannot be scrolled while the drawer is open" is not today's behaviour

- **Kind:** story-untrue (a grounding claim)
- **Where:** mock-up panel bullet 2: "The list still cannot be scrolled while the drawer is open (except in C, where ↑ ↓ scroll it for you)."
- **Evidence (`findrow-check3.py`):** real dashboard, drawer opened by a row click, ↓ ×3: `#table-wrap.scrollTop` 592 → 712 — the arrows scroll the dimmed list behind the drawer today (the drawer stayed at 0). This is what stepping replaces, and it is a point in the feature's favour, but the sentence the owner read is wrong about the starting point.
- **What the owner would see at delivery:** nothing new — only that the "before" he was told does not match what his dashboard did.
- **Confidence:** high

---

## Not checked

- **The white row's paint and z-index, the mark's grey, the hint, the step scrolling, `replaceState` and the Back bookkeeping:** the snapshot predates the build (`app.js` has no `lit`/`marked`/`state.mark`), so every behaviour above is judged from the brief's rules, the existing code paths and the data — not from a running implementation.
- **Safari's `replaceState` throttle (brief line 72):** Chromium only was available.
- **Whether CheapCharts' live wishlist matches the local mirror** (finding 8): no credentials, by design.
- **The narrow-window case** (mock-up panel bullet 4): not exercised; nothing in the stories depends on it.
- **The owner's real viewport size:** drawer overflow (finding 5) was measured at 1440×800 and 1500×900; on a taller window fewer drawers overflow, on a laptop more do.
- **Check 4 (outside-service provenance):** the feature makes no claim about any external service; nothing to provenance.
