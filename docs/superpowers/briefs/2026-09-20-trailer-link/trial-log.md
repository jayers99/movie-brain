# Trial log — a trailer link in the drawer

Fourth trial of the version 2 process, upstream half only; stories first.

## Your active time

| When | What you did | Rough minutes |
|---|---|---|
| 2026-09-20 | described the feature: the right trailer, a link in the drawer, a window over the whole browser, playing at once; asked first which source is reliable | 2–3 |
| 2026-09-20 | walked the mock-up, chose C-2: "c-2 mockup looks great. proceed" | unmeasured |
| 2026-09-20 | tried it on the copy of his catalogue: "looks great. call it complete success, merge and push" | unmeasured |

## Interruptions (each tagged by you: needed / not needed)

| # | What I brought you | Your tag |
|---|---|---|

## Surprises and corrections (misunderstood intent · implementation defect · changed preference · new opportunity)

| # | What | Kind |
|---|---|---|

## Probes used, and whether each changed a decision

| Probe | Decision it was meant to change | Did it? |
|---|---|---|
| Source measurement on 400 random live films (`scripts/discovery/trailer_spike.py`): TMDB typed videos, YouTube oEmbed check on every pick, iTunes lookup previews | which source plays, and whether one is enough | yes — neither alone: TMDB 61% overall but 89% on store films, Apple 92% on store films, 99% together; 243 of 244 picks alive and embeddable |
| One CheapCharts detail answer for three Shop films, its YouTube keys read back by title | why CheapCharts' trailers look bogus | yes — it is TMDB's first five videos with the type label ignored, so the fix is the label, not a different source |
| Other-language trailers on the 156 TMDB misses | whether to ask TMDB for every language | yes — only 12 rescued, some of them dubs: original language only |
| Headless rehearsal in real Chrome (default autoplay policy), all seven stories | whether a modal that autoplays with sound is feasible, and whether the story text is true | yes — feasible, plays unmuted after a click; trailer titles in the stories copied from the rehearsal; caught that YouTube's error callback can stay silent on a broken video (one run of three with the final code) |
| Seven stories + one mock-up: three link positions, two no-trailer treatments (`mockup-1.html`) | where the link sits; what a trailer-less film shows; whether Apple's previews pass | yes — C-2 in one round, no change requests; nothing raised against Apple's previews |
| Cold read-back of brief 0.95, checked against the code and the test suite | whether the brief carries the intent and its grounding is true | yes — 18 findings. Worst: Esc would have closed the drawer WITH the trailer, and the obvious test could not see it (the drawer closes through `history.back()`, which lands later); T right after ↓ would have played the PREVIOUS film's trailer; the brief's delivery order could not run (a pending migration stops every verb); an English teaser blocked a foreign film's own trailer; a TMDB 404 would have been retried for ever. Cost to him: zero minutes |

## Delivery, 2026-09-20

Built test-first on `feature/STORY-4-trailer-link`: the pick rule (9 unit tests, story 2 under its own name), the iTunes and TMDB adapters, the repository (worklist, write, merge, summary), 13 pytest-bdd scenarios for the lookup verb, the API key, and 21 Playwright tests — the seven stories under their own names plus the brief's named defaults — on their own server, YouTube's script routed to a stub and Apple's host to a request that never answers; two load-bearing lines (Esc taken ahead of the drawer's handler; T only for the film on screen) each proven by removing them. Whole suite 1,692 passed, ruff and mypy clean. Interruptions during the build: **0**.

On a migrated COPY of the live database the lookup ran for real: 4,947 films looked up, 3,318 with a YouTube trailer, 187 with Apple's preview only, 1,442 with nothing — **71% of the catalogue has a ▶ Trailer, and 2,551 of the 2,562 films Apple sells (99.6%)**; 0 failures. One film at a time it ran at about 65 films a minute (over an hour for the catalogue), so TMDB is now asked four films at a time: the last 4,300 films took about eight minutes. The real dashboard on that copy, in real Chrome against real YouTube and Apple: Cape Fear plays its Theatrical Trailer unmuted over the whole window (`delivery-story-1-playing.png`), the switch plays Apple's preview, Encore (no TMDB trailer) plays Apple's preview, Trio shows the search link, Esc leaves the drawer open. Unverified: Safari; whether Apple's previews are all trailers (he raised nothing on the two in the mock-up); a READY player that shows YouTube's own "unavailable" pane without reporting an error.

## Outcome

Merged to main 2026-09-20 (350413e) after his hands-on trial on a migrated copy, with no change requests: "looks great. call it complete success, merge and push". Migration 028 and the first `enrich trailers --apply` were then run on the live database. One mock-up round, one read-back, zero interruptions during the build.
