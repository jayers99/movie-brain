# Task brief — "Wishlist it" (backlog 3, the remaining half)

**Version 1.3 — amended 2026-09-19 after the hands-on test (1.2 at delivery; 1.1 during the build; 1.0 frozen the same day).** Everything that depends on CheapCharts is proven against your real account; the on-screen parts are simulated in the preview you approved. A second cold read-back by a fresh agent reconstructed the intent correctly; its findings are folded in below. From here the brief changes only by amendment (1.1, 1.2 …): the original decision stays, with what changed and who authorised it. First trial of the process in `docs/superpowers/research/2026-09-19-human-in-loop-diet-v2.md`: upstream half only; the build process is unchanged; your hands-on test comes before any merge.

## Your page

**Outcome.** From inside movie-brain, put a film on your CheapCharts wishlist with one click, at a sensible target price, and see on the list which films are already there. The chore this removes (your words, 08-29) is the *pair* of steps: look up a film's price floor, then hand-enter it as the target on CheapCharts. The wishlist itself stays on CheapCharts — it alerts your phone and makes buying easy.

**What wins when things trade off.** Simplicity. "It couldn't be more simple."

**What ships.**

- **On the list:** a small heart after the film's other badges (list count, owned, streaming service) when the film is on your CheapCharts wishlist. Every other row shows nothing new. Films you wishlisted before today get their heart too.
- **In the drawer:** for a film that is not wishlisted, one button in the links row, next to the CheapCharts link — "♡ Wishlist it". On click, **the software itself** adds the film to your CheapCharts wishlist and sets the target to **the film's lowest price ever, plus one dollar**. No tab opens; there is nothing for you to type or paste. While it works — about five to ten seconds, because CheapCharts has to be asked several things one after another — the button reads "Reaching CheapCharts…" and cannot be clicked twice. Then it becomes "♥ Wishlisted" and the heart appears on the row.
- **No prices shown anywhere.**

**What deliberately does not ship.** No chip, no Buy Queue page, no command-line report, no "buy now" or "not sold on Apple" sections, no price or price history on screen, no alerts of our own, no scheduled refresh, no browser being driven, no button that opens CheapCharts for you to finish the job, no changing the target of a film already on your wishlist, no un-wishlist button.

**The preview you approved:** [mockup-3.html](mockup-3.html), round 2 — "the rest of that mockup looks great" (2026-09-19). *Where the mock-up and this brief disagree, the brief wins:* the mock-up was approved before The Leopard and Nashville were really added to your wishlist, so it still shows The Leopard with a button, and its two hearted rows are pretend. Set aside along the way: [sketches.html](sketches.html) (three larger structures), [mockups.html](mockups.html) (you chose 3 of 3), [mockup-4-fallback.html](mockup-4-fallback.html) (the open-a-tab fallback — rejected on first use).

| Behaviour | Status |
|---|---|
| Knowing a film's lowest price ever | demonstrated — read from CheapCharts for ten films |
| Knowing whether Apple sells the film at all | demonstrated |
| Logging in to CheapCharts from Python with the details in your config file | demonstrated on your real account |
| Reading your existing wishlist | demonstrated — 195 films then, 86 of them known to movie-brain, so about 86 hearts on day one |
| Adding a film and setting its target, from Python | **demonstrated on your real account, with your yes:** Nashville, added at $5.99 on 2026-09-19; the wishlist went from 195 to 196 films and reads back the $5.99 target |
| The heart, the button, the button turning into "♥ Wishlisted" | simulated in the approved preview; ordinary to build |

**Acceptance examples (prices read from CheapCharts 2026-09-19).**

| Film | Lowest ever | Expected |
|---|---|---|
| Do the Right Thing | $2.99 (once; $4.99 thirty-two times) | click → added at **$3.99** — your ruling: a one-off low still counts |
| Mulholland Dr. | $7.99 (once) | click → added at $8.99 |
| The Leopard | — | already on your wishlist (your hand-add, $5.99): heart on its row after "3 lists"; its drawer shows "♥ Wishlisted", no button |
| Nashville | — | already on your wishlist (the proving add, $5.99): heart, no button |
| Tokyo Story | — | streaming on Criterion *and* sold on Apple: once wishlisted, the heart comes last, after the list count and the service badge |
| The Big Sleep | — | you own it: no button. (No heart either, because it is not on your wishlist) |
| La Dolce Vita | — | Apple does not sell it: no button, nothing said |
| CheapCharts unreachable, or your password no longer works | — | the links row says "Couldn't reach CheapCharts." with a "Try again" button; nothing is marked |

**What you will see at delivery.** The dashboard running on a *scratch copy* of your live data (the feature needs a schema change, and changing the live database is a separate decision of yours); the examples above passing as tests; a short spoken summary; and a plain list of anything I could not verify. Then you try it yourself — including one real click on a film of your choosing — and only after your say-so is the live database migrated and the work merged.

## Builder's pages

**Decision provenance**

| Decision | Whose |
|---|---|
| A row mark plus one drawer button — nothing else | your choice, 2026-09-19 |
| Mock-up 3: heart icon, button in the links row, no prices | your choice (against my recommendation of mock-up 2) |
| Target = lowest price ever + $1; a low that happened only once still counts | your choice (the second against my recommendation); supersedes August's D4 |
| The software performs the add itself; opening CheapCharts for you to finish is not acceptable | your choice — "I'm expecting the software to add the wishlisted item and populate the price" |
| Credentials for every site live in ONE config file outside the repo, keyed by site with username and password; the code reads it; nothing secret in the code | your choice — supersedes August's "never handle credentials" (spec §6) |
| Everything driven from Python; no browser launched or remote-controlled | your choice — "driving a browser is definitely the dumb solution" |
| How to do it in Python | delegated to the builder by you. Chosen: plain HTTP calls with `requests` to the site's own API |
| The wishlist lives on CheapCharts; nothing scheduled | your choices, 08-29 (D8, D6) |
| The heart comes last among the badges · an already-wishlisted drawer shows "♥ Wishlisted" where the button was · owned or unsold film: no button, no message | agent defaults, shown in the approved preview, not objected to |
| Failure wording: "Couldn't reach CheapCharts." + "Try again" | agent default — shown once, inside a preview you rejected for other reasons; confirm at your hands-on test |
| While the add runs (about 5–10 s: price history, login if needed, add, set target, each paced) the button reads "Reaching CheapCharts…" and is disabled | the wording was shown in the approved preview and not objected to; the preview's 0.9 s delay was NOT realistic — say so at delivery |
| The heart's tooltip says "On your CheapCharts wishlist" — never a price | agent default (a price tooltip was withdrawn: it broke "no prices anywhere") |
| A film you own that is on your CheapCharts wishlist still shows the heart, and its drawer shows "♥ Wishlisted" | agent default, NOT shown in any preview — two such films exist today, so point them out at the hands-on test |
| Hearts are refreshed from CheapCharts when the dashboard starts and after every add; if CheapCharts cannot be reached, the dashboard starts anyway with the last known hearts. Also a verb, `movie-brain cheapcharts wishlist` | agent default. Consequence you may notice: a film you remove or buy on CheapCharts keeps its heart until the next dashboard start |
| A click always means "on my wishlist at lowest + $1": it sends the add AND the set-target call every time, and treats "already on the wishlist" from the add as fine. So a half-finished click (added, target not set) is repaired by "Try again". Nothing is marked wishlisted until both calls succeed | agent default (replaces an earlier default that left an existing target alone — the second read-back showed that could silently leave a film at the wrong target). The button never appears on a film the last wishlist read already holds, so old hand-set targets are not touched; bulk-correcting old targets (August's D7) stays out of scope |
| Lowest + $1 is set even when it is at or above today's price (Performance.: $4.99 today, target $5.99) | agent default — you saw this case in the second preview and did not object |
| A film with no HD price history uses the standard-definition history; with no history at all, the click fails with the same failure line and nothing is marked | agent default |
| A wishlist read replaces the local hearts wholesale: a film you removed or bought on CheapCharts loses its heart at the next read | agent default |
| Both the standard and the HD target are set to the same value | agent default — it is what the proving add did |
| The lowest price is fetched at the moment of the click (HD purchase history), never stored; no price table | agent default |
| "Wishlisted" lives in its own small table with exactly two writers: the button and the wishlist read; `merge_film` moves it survivor-wins | agent default |
| The button appears only when the film holds a store id (`itunes`) | agent default — hence the prerequisite below |
| The file is `<config_dir>/credentials.toml`, mode 600, read with `tomllib`: section `[cheapcharts]`, keys `username` and `password` (already created and filled in by you) | agent default |
| Moving the OMDb and TMDB keys into the same file is NOT part of this feature — it is a separate small chore (backlog 21), so that the nightly-sync key path is not disturbed by a drawer button | agent default — your "for all API calls" stands; only the timing is mine, after the read-back flagged the regression risk against "simplicity wins" |
| The session token is kept in memory only; an expired or missing one triggers a fresh login | agent default |

**Taste boundaries.** Hard: nothing new on a row that is not wishlisted; no prices on screen; the button's wording "♡ Wishlist it" / "♥ Wishlisted". Standing dashboard preferences apply. Preference, not requirement: the heart's colour and size (the preview used `#c2410c`, 13px).

**Execution authority.** The builder may decide anything not visible and not touching your CheapCharts account or the live database. Code may read `credentials.toml`, but no credential, session token, customer id, username or email may ever be printed, logged, copied into a fixture or committed; tests mock HTTP with `responses`, as the repo already does. **During the build nothing touches your real CheapCharts account at all — not even a login or a read;** every test mocks HTTP. The first real login and read happen at your hands-on test, started by you. Not without a separate yes from you: any write to your real CheapCharts wishlist, `cheapcharts resolve --apply`, any migration on the live database, a merge, a push.

**Prerequisite (your separate decision).** Only 31 of the 231 films in your buy queue held a store id on 2026-09-19, because `cheapcharts resolve` has not been run since the newer lists were imported; a read-only probe found 91 more are sold. Until that run, most films will show no button. It writes to the live database.

**Repository grounding.** `infrastructure/cheapcharts.py` (client, 1.5 s pacing, `RateLimited` on 429, `Referer` header). `DetailData.php?store=itunes&country=us&itemType=movies&idInStore=<id>` returns `priceHdEvolution` (`date:±price~…`; the low is computed from it, never taken from a flag). `external_ids` authority `itunes` is the join. Row badges: `static/app.js` near `badge-lists` / `badge-owned` / `badge-watch`; drawer links row: the `p.links` block. User-response tables follow the `watchlist` pattern. Schema change → new migration 027; never edit an applied one; `migrate --apply` is the only path on the live database. Gates: `uv run pytest`, `ruff check`, `mypy`, both benchmarks.

**The account API — proven end to end 2026-09-19.** Base `https://buster.cheapcharts.de/v1/`; form-encoded POSTs; answers JSON `{status: "success"|"error", message, …}` with HTTP 200 even on error.

- Login: `POST Account.php`, body `country=us, action=login, email=<username>, password=<SHA-256 HEX digest of the plain password>, origin=website, appEntity=cc_main_website` → `additionalInfo.sessionToken` (the message may read "already logged in" and still be a success). The response also carries a customer id, username and email — never log it.
- Read: `POST Wishlist.php?country=us&store=itunes&action=getShortItemList_v2`, body `sessionToken=<…>` → `results.movies[] = {idInStore, initialPriceValue, initialHdPriceValue, customPrice?}`. A bad token answers `status: error`, "Couldn't load user. DeviceId or sessionToken unknown".
- Add: `…&action=addItem&itemType=buymovies&idInStore=<itunes id>` → "Item added…". **`itemType` must be `buymovies`** — `movies` is refused with a message listing the legal values.
- Target: `…&action=changeInitPrice&itemType=buymovies&idInStore=<id>&customPrice=<p>&customPriceHd=<p>` → "init price was changed to …"; reads back as `initialPriceValue` / `initialHdPriceValue` with `customPrice: true`.
- Remove (seen in the site's code, not exercised): `…&action=removeItem&itemType=buymovies&idInStore=<id>`.
- Probe: `scripts/discovery/cheapcharts_wishlist_probe.py` (`read` writes nothing; `add` / `remove` write to the real wishlist).

**Recovery.** State lives in this brief, [trial-log.md](trial-log.md) and the memory note `price-watch-trial`. Nothing is built; no branch exists yet. August's reasoning, where still relevant: `docs/superpowers/specs/2026-08-29-on-sale-canon-acquisition-design.md` (its §4 "join problem" and §6 browser rules are both overturned).

## Amendments

**1.1 — 2026-09-19, by the builder, under the execution authority (none of these is visible on screen or touches the account beyond what 1.0 approved).** New agent defaults:

| Decision | Whose |
|---|---|
| A click is believed only when CheapCharts reads it back: after add + set-target the wishlist is read, the hearts are replaced from it, and the film is marked only if the read holds it. If that read fails, an ACCEPTED add is believed; a refused one is not | agent default — 1.0's "treat already-on-the-wishlist as fine" could not be built as written, because the API's answer for that case was never observed. A refused add no longer stops the click; the set-target call and the read-back decide |
| The table is `cheapcharts_wishlist` (migration 027); a film holding several store ids is hearted by any of them, and the button wishlists the same product the CheapCharts link opens | agent default |
| Errors from the account carry our own wording only, never the API's text — the login answer holds the account's email | agent default |
| With no usable `[cheapcharts]` section, the dashboard starts with the last known hearts and says "wishlist: off"; the button still shows, and a click ends in the ordinary failure line | agent default |
| `movie-brain cheapcharts wishlist` has no dry run: it never writes to the account, and its one local write is the same refresh every dashboard start performs | agent default |
| Calls to CheapCharts are paced 1.5 s apart on a clock, shared between the price read and the account, so a dashboard idle for an hour does not wait before its first call | agent default |
| One click at a time: a second click anywhere waits for the first to finish | agent default |

Format note for the record: `priceHdEvolution` entries are `date:±price` where the sign is the DIRECTION of the change, not part of the price; the oldest entry has no sign (read from the public endpoint 2026-09-19, no account involved).

**1.2 — 2026-09-19, by the owner, on first sight of the delivery:** "there is no way to unwhishlist it. it should be reversable". This supersedes 1.0's "no un-wishlist button" (What deliberately does not ship) and 1.0's "exactly two writers".

| Decision | Whose |
|---|---|
| The click is reversible | your choice, 2026-09-19 |
| In the drawer the "♥ Wishlisted" mark IS the button: one click removes the film from your CheapCharts wishlist, the button goes back to "♡ Wishlist it" (an owned film's slot just empties) and the heart leaves the row. Its tooltip reads "Remove from your CheapCharts wishlist". No confirmation step — a mistaken click is undone by one more click | agent default, NOT previewed — look at it in the hands-on test |
| Taking a film off and putting it back sets the target to lowest + $1 again, so a target you had set by hand on CheapCharts is not restored | agent default — a consequence of "a click always means lowest + $1" |
| Removal follows the add's truth rule: remove, read the wishlist back, the read decides; if the read fails an accepted remove is believed. A failure is the same line, and "Try again" repeats the removal | agent default |
| A film you own that is on your wishlist can be taken off the same way (it cannot be put back from here: owned films get no add button) | agent default |
| The remove call (`removeItem`) was seen in the site's code and never run against your account; its first real run is your hands-on test | fact, stated so it is not a surprise |

**1.3 — 2026-09-19, by the builder, after your hands-on test found that films already on your wishlist got no heart.** Cause: the wishlist read's answer carries no `status` field (add, set-target and remove do), my code demanded one, and every test had mocked the read from the brief's wording instead of from a real answer — so every read failed while every write worked. Supersedes 1.1's first row and 1.2's truth-rule row.

| Decision | Whose |
|---|---|
| Every click READS your wishlist first and refreshes the hearts from it. If the read fails, nothing is written — not to CheapCharts, not locally — and you see the ordinary failure line | agent default (replaces "read back after the write; if that fails, believe an accepted add") |
| A film the read shows is already on your wishlist WITH a target — set by hand or by us — just gets its heart; its target is never touched. This is what protects a hand-set target even when the local hearts are stale | agent default — it enforces 1.0's "old hand-set targets are not touched" at the moment of the click instead of trusting the last read |
| A film already there WITHOUT a target (a half-finished earlier click) gets its target set, nothing else | agent default |
| An add or a remove CheapCharts refuses is a failure; there is no fallback that believes a write without proof | agent default |
| The terminal names why a read or a click failed (our own wording only — never anything CheapCharts said); the on-screen line stays "Couldn't reach CheapCharts." | agent default |
| Test fixtures for a CheapCharts answer are built from the real answer's shape (ids invented), never from prose | process rule, from this defect |

Correction to "The account API" above, for the record: the Read answers `{results: {ebooks[], movies[], tv[]}, originRequest, responseTimestamp}` with NO `status` key; `idInStore` is a string; `customPrice` is absent when no target is set; `initialPriceValue` may be `-1`.
