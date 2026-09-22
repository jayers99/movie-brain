# Findings — "Wishlist it" brief (2026-09-19-price-watch), gap check 2026-09-21

Checked against the snapshot in `bt/wishlist` and the database copy in `bt/cfg-wishlist` (schema 26, 5,156 films, 2,368 `itunes` ids on 2,368 films). The real dashboard was run on port 5701; `/api/films` is saved at `bt/films-wishlist.json`, drawer and row screenshots under `bt/shots-wishlist/`. The builder's plan `docs/superpowers/plans/2026-09-19-wishlist-it.md` is in the snapshot and is cited where it shows what the build will actually mock or do.

Ranked by the damage each would do at delivery.

---

## 1. The wishlist READ's answer shape is generalised from the write calls, and every heart and every click depends on it

- **Kind:** provenance
- **Where:** brief "The account API — proven end to end", the *Read* bullet; plan Task 3 fixtures (lines 976, 1429) and `CheapChartsAccount._wishlist` (line 1195)
- **Claim:** "answers JSON `{status: "success"|"error", message, …}` with HTTP 200 even on error" — stated once for every call — and for the read only "`results.movies[] = {idInStore, initialPriceValue, initialHdPriceValue, customPrice?}`. A bad token answers `status: error`".
- **Evidence:** The only instrument is `scripts/discovery/cheapcharts_wishlist_probe.py`, which prints `json.dumps(redact(data))[:1200]` to the terminal (line 146) and saves nothing; no captured answer exists anywhere in the project or config directory (`grep -rn getShortItemList` finds only the probe, the brief and the plan). The brief's `trial-log.md`, where "state lives", is absent from the folder (see finding 13). What was seen for a SUCCESSFUL read is therefore a redacted, 1,200-character-truncated terminal line that nobody can re-inspect; the `status` key on the success read is inferred from the error read and the write calls. The plan builds on the inference: its read fixture is `{"status": "success", "results": {"movies": [{"idInStore": 273058482, …}]}}` (line 976) and `_wishlist()` returns an answer only `if data.get("status") == "success"` (line 1195) — for the read as for the writes.
- **What the owner would see at delivery:** if the real success read carries no `status` key (or a different one), every dashboard start logs a failed refresh, no film ever gets a heart, and every click ends in "Couldn't reach CheapCharts." while the tests are green.
- **Confidence:** high that the shape is unprovenanced and that the build mocks it from prose; the real shape itself is not verifiable here (no account).

## 2. 201 films whose drawer says Apple sells them get no button and no explanation — the largest "no button" state, and it is not the one the mock-up walks

- **Kind:** gap-unpictured
- **Where:** brief "What ships" (drawer bullet), acceptance row *La Dolce Vita* ("Apple does not sell it: no button, nothing said"), decision row "The button appears only when the film holds a store id (`itunes`)", "Prerequisite"; mock-up 3 story *La Dolce Vita*
- **Claim:** the only no-button states pictured are "you own it" (The Big Sleep) and "Apple does not sell it" (La Dolce Vita).
- **Evidence:** `films-wishlist.json`: 201 non-owned films have a TMDB Apple-store listing (`services` entry with `kind == 'store'`) and NO `itunes` id; 198 of them are on a list; 96 of the 231 buy-queue films are in this state. Their REAL drawer already says "Buy on: Apple TV Store (iTunes)" and links "Find on CheapCharts ↗" — screenshot `shots-wishlist/drawer-producers.png` (The Producers 1968, #4854: `meta: ['Watch on Kanopy ↗', …, 'Buy on: Apple TV Store (iTunes)'] | links: TMDB ↗ Find on CheapCharts ↗`) and `drawer-performance.png` (Performance. 1970, #4797: `meta: ['Buy on: Apple TV Store (iTunes)'] | links: TMDB ↗ Find on CheapCharts ↗`). La Dolce Vita (#3163) by contrast has no store listing at all (`meta: []`, links `TMDB ↗`), so the mock-up's "nothing said" story is a different, smaller state. The brief's prerequisite says "most films will show no button" but never shows him what such a drawer looks like or that it will say "Buy on: Apple TV Store" right above the missing button.
- **What the owner would see at delivery:** he opens Shanghai Express, The Wrong Man or Performance., reads "Buy on: Apple TV Store (iTunes)" and "Find on CheapCharts ↗", finds no "♡ Wishlist it", and has no story that told him this is expected.
- **Confidence:** high

## 3. Performance. — the "target above today's price" case the brief says he saw — has no store id, so it shows no button

- **Kind:** story-untrue
- **Where:** brief decision row "Lowest + $1 is set even when it is at or above today's price (Performance.: $4.99 today, target $5.99) — you saw this case in the second preview"; mockups.html "Performance." row
- **Claim:** Performance. is a live example of the click's behaviour.
- **Evidence:** `sqlite3`: `4797|Performance.|1970|lists 1|owned 0|itunes NULL|store 1`; `/api/films` `cheapcharts_url: None`; real drawer links row is `TMDB ↗ Find on CheapCharts ↗` (`shots-wishlist/drawer-performance.png`). Under the brief's own rule the button appears only with an `itunes` id.
- **What the owner would see at delivery:** he opens Performance. to try the case he was shown and finds no button until a separate `cheapcharts resolve --apply` he has not yet agreed to.
- **Confidence:** high

## 4. A film he wishlisted by hand since the last read shows the button, and a click overwrites his hand-set target

- **Kind:** gap-unpictured
- **Where:** brief decision rows "A click always means 'on my wishlist at lowest + $1': it sends the add AND the set-target call every time, and treats 'already on the wishlist' from the add as fine … The button never appears on a film the last wishlist read already holds, so old hand-set targets are not touched" and "Hearts are refreshed from CheapCharts when the dashboard starts and after every add"
- **Claim:** hand-set targets are safe because the button never appears on a wishlisted film.
- **Evidence:** the two rows together: hearts are only as fresh as the last read (dashboard start or the last add), and a click on a button-showing film sends set-target unconditionally. A film he adds on CheapCharts' phone app at a chosen target while the dashboard has been open since morning still shows "♡ Wishlist it"; the plan's `wishlist_film` (lines 1533–1553) checks the LOCAL heart only, then adds and sets the target. The brief's own second read-back flagged the inverse risk ("could silently leave a film at the wrong target") and the fix moved the risk to this side without a story.
- **What the owner would see at delivery:** a film he priced by hand at, say, $9.99 on his phone shows the button in the drawer; one click, and CheapCharts now holds lowest + $1, with nothing on screen saying the target moved.
- **Confidence:** high (from the brief's own rules); the frequency depends on how often he hand-adds, which is his habit per the outcome paragraph.

## 5. The morning after a half-finished click: heart, "♥ Wishlisted", no button — and no target, for ever

- **Kind:** gap-unpictured
- **Where:** brief decision row "a half-finished click (added, target not set) is repaired by 'Try again'. Nothing is marked wishlisted until both calls succeed"; row "Hearts are refreshed … when the dashboard starts"
- **Claim:** the half-finished state is repaired by Try again.
- **Evidence:** only if he presses Try again in that sitting. If he does not (closes the laptop on "Couldn't reach CheapCharts."), the next dashboard start reads the wishlist, which now holds the film (the add succeeded) → `replace_wishlist` hearts it → the drawer shows "♥ Wishlisted" and no button → the target is never set, and by the brief's "no changing the target of a film already on your wishlist" there is no path in movie-brain to set it. Neither the brief nor mock-up 3 pictures this state.
- **What the owner would see at delivery:** a hearted film that CheapCharts will alert on at its default (or no) target, indistinguishable on screen from a film wishlisted at lowest + $1.
- **Confidence:** high

## 6. The failure state is not in the approved mock-up, and its one line is untrue for the failures that will recur

- **Kind:** gap-unpictured
- **Where:** brief acceptance row "CheapCharts unreachable, or your password no longer works → 'Couldn't reach CheapCharts.' with a 'Try again' button"; decision rows "Failure wording … shown once, inside a preview you rejected for other reasons" and "with no history at all, the click fails with the same failure line"; mock-up 3 (no failure anywhere)
- **Claim:** one failure line covers every failure.
- **Evidence:** mock-up 3's script has no failure branch (`renderDrawer`, lines 90–101); the wording exists only in `mockup-4-fallback.html` line 118, the preview "rejected on first use". The plan confirms the line is used for every cause: "One line whatever went wrong — offline, a refused password, no price history — and nothing is marked" (line 1651). For a film with no price history, or one whose stored id is a product Apple pulled (finding 7), CheapCharts WAS reached and answered; "Try again" repeats the same calls and fails the same way every time — the grid's "second press" answer is an infinite loop with a false diagnosis.
- **What the owner would see at delivery:** "Couldn't reach CheapCharts." on a film while every other film wishlists fine; he retries, gets the same line, and cannot tell a dead network from a film that can never be wishlisted.
- **Confidence:** high that it is unpictured and the line is shared; which real films have no history is not verifiable here.

## 7. The button appears on films whose stored store id is a product Apple has removed — Control (2007) is one

- **Kind:** gap-unpictured
- **Where:** brief decision row "The button appears only when the film holds a store id (`itunes`)"; behaviour table "Knowing whether Apple sells the film at all — demonstrated"
- **Claim:** a store id means Apple sells it, so the button is shown.
- **Evidence:** `docs/backlog.md` line 7: after the 2026-09-07 recheck "183 dead ids left (the title search confirmed nothing) … the rest (`Control` 2007) are genuinely gone from the store". `sqlite3`: `24|Control|2007|itunes 444642901|store 0|owned 0` — the dead id is still stored, so `cheapcharts_url` is set and the button rule fires. 129 non-owned films hold an id and no TMDB store listing (`films-wishlist.json`), the population where the dead ids sit. Nothing in the brief says what the click does for a removed product (DetailData may still answer history; the add's answer for a removed product was never exercised).
- **What the owner would see at delivery:** "♡ Wishlist it" on Control, a click, "Reaching CheapCharts…", then either a wishlist entry for a product he cannot buy or the failure line — with no story for either.
- **Confidence:** medium-high (Control is named as gone in the backlog; the click's outcome on it is untested).

## 8. "♥ Wishlisted" does nothing when clicked — but the last time he saw that text it was a button that removed the heart

- **Kind:** exclusion-to-walk
- **Where:** brief "What deliberately does not ship … no un-wishlist button"; mock-up 3 story *Nashville* ("Its drawer has no button — it says ♥ Wishlisted where the button would be"); mockup-4-fallback variant A ("click ♥ Wishlisted in the drawer to take the heart off again", line 63 and the `data-act="unwish"` button, line 117)
- **Claim:** the exclusion is a line in a list; the mock-up shows the mark but never says it is inert or where removal happens.
- **Evidence:** mock-up 3 renders `<span class="done">♥ Wishlisted</span>` (line 93) with no handler; mockup-4 A rendered the same words as `<button class="linkish" data-act="unwish">` and its "Try this" step 4 had him click it. Real films: Nashville #3128 and The Leopard #3085 are the two that will show the mark on day one.
- **Story card that should exist (owner's voice):** "Nashville is already on my wishlist, so its drawer says ♥ Wishlisted. I click it — nothing happens; it is a mark, not a button. To take Nashville off, I open CheapCharts ↗ beside it and remove it there. The heart on the row stays until the next time I start the dashboard."
- **Confidence:** high

## 9. A film he removes or buys on CheapCharts keeps its heart until the next dashboard start — a consequence line, not a card

- **Kind:** exclusion-to-walk
- **Where:** brief "What deliberately does not ship … no scheduled refresh"; decision rows "Hearts are refreshed … when the dashboard starts and after every add … Consequence you may notice: a film you remove or buy on CheapCharts keeps its heart until the next dashboard start" and "A wishlist read replaces the local hearts wholesale"
- **Claim:** disclosed as a consequence in the decision table; no story card and nothing in mock-up 3.
- **Evidence:** mock-up 3 has no removal path and no restart; the memory note says the owner runs the dashboard by hand (no launchd), so "next start" may be days. The verb `movie-brain cheapcharts wishlist` is named only inside that row.
- **Story card that should exist:** "I bought Tokyo Story on my phone at lunch. Back at the dashboard, Tokyo Story still shows ♥ and its drawer still says ♥ Wishlisted. That is stale until I restart the dashboard or run `movie-brain cheapcharts wishlist`; nothing in the page refreshes it for me."
- **Confidence:** high

## 10. Two owned films will show a heart and "♥ Wishlisted", contradicting the only owned card he has walked

- **Kind:** gap-unpictured
- **Where:** brief decision row "A film you own that is on your CheapCharts wishlist still shows the heart, and its drawer shows '♥ Wishlisted' — agent default, NOT shown in any preview — two such films exist today"; mock-up 3 story *The Big Sleep* ("you own it. No heart, and no button — there is nothing to buy")
- **Claim:** the brief admits the gap and defers it to the hands-on test.
- **Evidence:** the brief's own row. 842 owned films hold a store id (`films-wishlist.json`), so the class is large even if two are hearted today; the two titles are not identifiable here (no wishlist data). The Big Sleep card teaches "owned = no heart", which those two rows will break.
- **What the owner would see at delivery:** an "owned" pill followed by a heart on a film he already bought, after a mock-up that told him owned films carry no heart.
- **Confidence:** high (from the brief), which films: not checked

## 11. The add's answer for a film already on the wishlist was never observed, yet the Try-again design rests on it

- **Kind:** provenance
- **Where:** brief decision row "sends the add AND the set-target call every time, and treats 'already on the wishlist' from the add as fine"; API section *Add* bullet
- **Claim:** the add answers something recognisable as "already on the wishlist".
- **Evidence:** the probe added Nashville exactly once ("the wishlist went from 195 to 196"); the plan states it outright: "The API's exact answer for a film already on the wishlist was never observed; whatever it says…" (line 1019) and its fixture is `{"status": "error", "message": "whatever it says"}` (line 1022). The client therefore treats EVERY refused add as "probably already there" (`add_item` docstring, lines 1174–1181) and goes on to set the target, trusting the read-back to decide.
- **What the build's tests will mock:** an add refusal with invented wording; a refusal for any other reason (a removed product, a wrong `idInStore`) is indistinguishable and is followed by a set-target call on a product that is not on the list.
- **Confidence:** high

## 12. The price-history format, the SD fallback and the "ten films" reads have no script and no capture in the repository

- **Kind:** provenance
- **Where:** brief "Repository grounding" (`priceHdEvolution` `date:±price~…`), behaviour table "Knowing a film's lowest price ever — demonstrated — read from CheapCharts for ten films", decision row "A film with no HD price history uses the standard-definition history"
- **Claim:** the low is computed from `priceHdEvolution`; SD history is the fallback.
- **Evidence:** `scripts/discovery/` holds no price-history script; `grep -rn DetailData` in the snapshot hits only the brief, the plan and August's spec/handoff. The brief gives `date:±price` without saying what the sign means; the plan discovered at plan time that "the sign is the DIRECTION of the change … a parser built on the brief's wording alone would have had to guess" (lines 690, 1879, 1887) and names the SD field `priceSdEvolution`, which the brief never names. No film with an empty HD history and a non-empty SD one is recorded as seen anywhere.
- **What the build's tests will mock:** `priceHdEvolution`/`priceSdEvolution` strings written from the plan's one Do-the-Right-Thing read; the SD-only branch and the no-history branch are built from prose.
- **Confidence:** high that the captures are absent; medium on consequence (the plan's one live read corrected the worst of it).

## 13. `trial-log.md` and the research note the brief and kickoff point to do not exist in the folder

- **Kind:** provenance
- **Where:** brief "Recovery" ("State lives in this brief, [trial-log.md](trial-log.md) and the memory note"), brief line 3 (`docs/superpowers/research/2026-09-19-human-in-loop-diet-v2.md`), kickoff step 3 ("`trial-log.md` — what went wrong upstream")
- **Claim:** the log of what was seen and what went wrong is on disk beside the brief.
- **Evidence:** `ls docs/superpowers/briefs/2026-09-19-price-watch/` → `brief.md kickoff.md mockup-3.html mockup-4-fallback.html mockups.html sketches.html`; `ls docs/superpowers/research/` → four thumbprint files only. The plan's Task 9 tells the builder to "Append a row to the 'Probes used' table of `trial-log.md`" (line 1884).
- **What the owner would see at delivery:** the "plain list of anything I could not verify" has no upstream record to reconcile against, and the delivery scorecard the kickoff promises has no file to land in.
- **Confidence:** high

## 14. Closing the drawer during "Reaching CheapCharts…" and reopening the film shows "♡ Wishlist it" again

- **Kind:** gap-unpictured
- **Where:** brief drawer bullet ("the button reads 'Reaching CheapCharts…' and cannot be clicked twice"); mock-up 3 (0.9 s delay, the drawer cannot be closed)
- **Claim:** the click cannot be doubled.
- **Evidence:** the wait is 5–10 s; Esc, ✕ or the backdrop close the real drawer (`app.js` `closeDrawer`, `hideDrawer` sets `body.innerHTML = ''`). The busy state lives only in the detached button; reopening the same film re-fetches `/api/films/<id>`, which reads the local table, not in-flight requests, so the button renders fresh. A second click starts a second server call (the plan's route lock serialises them, line 474). Real film: The Leopard #3085 — click, press Esc at once, click its row again.
- **What the owner would see at delivery:** a button that says it cannot be clicked twice, clicked twice, with two "Reaching CheapCharts…" waits and a target set twice.
- **Confidence:** medium (harmless in effect if finding 11's read-back holds; unpictured either way)

## 15. The real drawer already has a ★ "watchlist" toggle beside the title; the mock-up drawer hides it, and the three example films are all starred

- **Kind:** gap-unpictured
- **Where:** mock-up 3 drawer (`renderDrawer`, no `<h2>` toggles); brief "What ships" (drawer bullet)
- **Claim:** the drawer of a wishlist candidate looks like the mock-up.
- **Evidence:** real `#drawer h2` for The Leopard reads `The Leopard ★⚐` (filled star = on movie-brain's own watchlist; screenshot `shots-wishlist/drawer-leopard.png`); `/api/films`: The Leopard, Nashville and Tokyo Story all `watchlisted: true`; 10 of the 13 starred films are button candidates. The owner has not pictured "★ watchlist" and "♡ Wishlist it" in the same drawer.
- **What the owner would see at delivery:** a filled ★ next to the title and a "♡ Wishlist it" button two lines lower on the same film, with no word on how the two lists differ.
- **Confidence:** medium (a vocabulary collision; every fact is real)

## 16. The mock-up's owned drawer omits the "Buy on: Apple TV Store" line and the CheapCharts link the real owned drawer shows

- **Kind:** story-untrue
- **Where:** mock-up 3 story *The Big Sleep* ("there is nothing to buy") and `renderDrawer` line 98 (`f.sold && !f.owned` gates the Buy-on line)
- **Claim:** an owned film's drawer shows "Owned on Apple TV ↗" and nothing about buying.
- **Evidence:** real drawer for The Big Sleep #3704: `meta: ['Owned on Apple TV ↗', 'Buy on: Apple TV Store (iTunes)'] | links: TMDB ↗ CheapCharts ↗` (`shots-wishlist/drawer-bigsleep.png`).
- **What the owner would see at delivery:** "Buy on: Apple TV Store" and a CheapCharts link on a film he owns, and no button — a drawer that looks like finding 2's, not like the card he walked.
- **Confidence:** high

## 17. Mock-up 3's Do the Right Thing card points at a terminal question the page never answers

- **Kind:** story-untrue
- **Where:** mock-up 3 panel row *Do the Right Thing* ("the awkward one — see my question in the terminal")
- **Claim:** none on the page; the ruling ($3.99, a one-off low counts) lives only in the brief's acceptance table.
- **Evidence:** mockup-3.html line 63; brief acceptance row *Do the Right Thing*.
- **What the owner would see at delivery:** re-walking the approved mock-up, he meets a card with no story, for the film whose target rule he had to rule on.
- **Confidence:** high

## 18. The badge list in the brief omits the "5★ then" / "1★ then" pill, which 20 button candidates carry between "owned" and the service badge

- **Kind:** story-untrue
- **Where:** brief "What ships" list bullet ("after the film's other badges (list count, owned, streaming service)")
- **Claim:** those three are the badges a heart follows.
- **Evidence:** `app.js` `rowHtml` (lines 153–156) orders `gone` → `N lists` → `owned` → old-rating pill → service badge; real row for I Am Cuba #668: `I Am Cuba 1 list 5★ then Criterion Channel` (`shots-wishlist/row-iamcuba.png`); 20 candidates carry a 5★/1★ pill (`films-wishlist.json`). The heart still comes last, so the "after" claim holds; the picture he approved never showed a row with four pills.
- **What the owner would see at delivery:** `1 list · 5★ then · Criterion Channel · ♥` on I Am Cuba — one more pill than any mock-up row.
- **Confidence:** high, low damage

## 19. There is no way to see the hearted films together — "no chip" is a list line only

- **Kind:** exclusion-to-walk
- **Where:** brief "What deliberately does not ship … No chip"
- **Claim:** disclosed as an exclusion; no card.
- **Evidence:** the bar's chips are fixed in `index.html`/`CHIP_PREDICATES` (`app.js` lines 47–63); `wishlisted` is not among them and the plan adds none. About 86 hearts on day one, spread over 5,000 rows in metacritic order.
- **Story card that should exist:** "I want to see everything I have hearted. There is no Wishlist chip and no column: the hearts are only visible row by row as I scroll or search. If I want the list, it is on CheapCharts."
- **Confidence:** medium (whether he will reach for a chip is a guess; that there is none is not)

## 20. 129 films show the button with no "Buy on" line above it

- **Kind:** gap-unpictured
- **Where:** brief decision row "The button appears only when the film holds a store id"; mock-up 3 (every button film also shows "Buy on: Apple TV Store (iTunes)")
- **Claim:** implicit — a button film looks like The Leopard's drawer.
- **Evidence:** `films-wishlist.json`: 129 non-owned films hold an `itunes` id and no TMDB store listing (e.g. Encore 1951 #4, Pauline at the Beach 1983 #74); `app.js` line 631 renders "Buy on" only from `services`, and line 634 renders "CheapCharts ↗" from the id — so the drawer will read `TMDB ↗ CheapCharts ↗ ♡ Wishlist it` with no store line. Some of these are TMDB lag, some are the dead ids of finding 7.
- **What the owner would see at delivery:** a Wishlist button on a film whose drawer never says Apple sells it.
- **Confidence:** high, low damage

---

## Not checked

- **The wishlist itself.** No credentials exist here and none were sought, so "195 films, 86 known", which two owned films are hearted, and whether Nashville/The Leopard read back as wishlisted could not be verified; hearts on day one depend on the read in finding 1.
- **The real answer shapes** (login, read, add, set-target, DetailData) — nothing in the two directories captures one; findings 1, 11 and 12 are about that absence, not about the shapes' truth.
- **Which real films have no price history** (finding 6's permanent failure) and what the click does on a removed product (finding 7) — both need the live API.
- **Whether Apple truly does not sell La Dolce Vita** — the DB holds no store listing and no id, consistent with the card; the sketches' probe is the only source.
- **The 5–10 s click on the real drawer** — the feature is not built in this snapshot; the drawer-closed-mid-click behaviour in finding 14 is read from `app.js`'s existing `hideDrawer`/`openDrawer` and the plan's handler, not observed.
- **Row and drawer rendering after the build** — screenshots are of the existing dashboard (pre-feature); badge order and link rows are real, hearts and buttons are inferred from the plan's markup.
