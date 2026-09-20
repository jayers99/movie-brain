# Trial log — find my row

Second trial of the version 2 process. Upstream half only. The deliberate change from trial one: user stories are made prominent — first in the brief, first on the mock-up page, each walkable in the mock-up with one click, each becoming a test under its own name.

## Your active time

| When | What you did | Rough minutes |
|---|---|---|
| 2026-09-20 | described the feature and asked for stories + mock-ups | 1–2 |
| 2026-09-20 | tried the mock-up, chose C ("Good work. Option C looks great.") | unmeasured — about 13 minutes between my message and his reply, idle time included |

## Interruptions (each tagged by you: needed / not needed)

| # | What I brought you | Your tag |
|---|---|---|

## Surprises and corrections (misunderstood intent · implementation defect · changed preference · new opportunity)

| # | What | Kind |
|---|---|---|
| 1 | Story 6 as he saw it said "press Owned again: the mark is back". The real chip is three-way, so the second press is Not owned, not off. Reworded at the freeze; the behaviour he approved is unchanged. | implementation defect in the preview — caught by the read-back, before any build |
| 2 | On the real dashboard BFI: Film Noir is an UNORDERED list, so it sorts by Metacritic and Out of the Past's neighbour is The Postman Always Rings Twice — not Pursued, as every story says. The mock-up showed the list in file order. The behaviour is unaffected (the tests run the stories word for word on an ordered list), but a story that names a real ORDER has to be checked against the real sort, exactly like a real film or a real control. Found while taking the delivery screenshots. | implementation defect in the preview — caught at delivery, harmless |

## Delivery, 2026-09-20

Built test-first on `feature/STORY-24-find-my-row` (c58d256): 19 new Playwright tests — the six stories under their own names plus the brief's defaults — the three guard tests that passed before the feature existed were each proven by removing their guard; whole suite 1,599 passed, ruff and mypy clean. Walked on a scratch copy of the live data; screenshots `delivery-story-*.png` beside this file. Interruptions during the build: **0**. Unverified: Safari (only Chromium was driven); a window narrower than about 1,100 px; how the grey mark reads on his own screen.

## Probes used, and whether each changed a decision

| Probe | Decision it was meant to change | Did it? |
|---|---|---|
| Grounding on the real CSS and a read-only copy of the live records | whether "make the row white" means what it says | yes — the page is already white and the drawer dims it, so "white" means "not dimmed", and it cannot exist after the drawer closes; that is where variants B and C come from |
| Headless rehearsal of the mock-up before showing it (agent alone) | whether the white-row technique works with the real dashboard's layers | yes — it works only with the drawer moved one layer up; it also caught a class-name collision that wrecked the open row's layout |
| Six stories + one mock-up, three variants (`mockup-1.html`) | which variant; whether the after-close mark looks right; which stories are kept | yes — he chose C, against my recommendation of B; one round, no change requests |
| Cold read-back of brief 0.9 by a fresh agent, which then checked the brief against `app.js`, `app.css` and the test suite | whether the brief alone carries the intent and its grounding is true | yes — reconstruction correct; 18 findings. Worst: reusing `openDrawer(id, false)` for a step would have silently broken the Back button; story 6 misread the three-way Owned chip (my mock-up's chip had two states — a story naming a real CONTROL needs checking against the real control, same lesson as real films); the 10-film test seed cannot evict a row from the DOM, so stories 4 and 5 would have passed vacuously. Cost to him: zero minutes. Brief frozen as 1.0 |
