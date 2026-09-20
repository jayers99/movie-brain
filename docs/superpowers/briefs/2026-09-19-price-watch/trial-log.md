# Trial log — price watch

First trial of the version 2 process. Upstream half only. Times are rough, read from the session clock; uncertainty is a few minutes either way.

## Your active time

| When | What you did | Rough minutes |
|---|---|---|
| 2026-09-19 | chose the feature ("2") | under 1 |
| 2026-09-19 | looked at the three rough structures, set them aside, dictated his own design | roughly 5–10, unmeasured |
| 2026-09-19 | tried the three mock-ups, chose 3, flagged the missing wishlisted row | about 3 (18:06 → 18:09 by the screen clock) |
| 2026-09-19 | looked at round 2, approved it, ruled on the one-off low | a few, unmeasured |

## Friction (time of his that bought nothing)

| # | What happened | Cause |
|---|---|---|
| 1 | Two attempts at observing his manual wishlist add captured nothing: he did the add somewhere other than the tab I was recording. Roughly 10 of his minutes. | Mine. The extension opens its tab group in a SEPARATE Chrome window, and I told him to look for "a tab", never "a different window". My first instructions also assumed he knew why I was asking. |
| 2 | Third attempt also captured nothing. Chrome holds exactly one CheapCharts tab (the one I opened, in his main 11-tab window); the page header there reads "Login / Register" on a fresh load while he reports being logged in. I could not reconcile the two, and stopped rather than ask a fourth time. About 15–20 of his minutes in total, zero information gained. | Mine: the observation step was under-prepared — I never checked how the extension's tab and his login state would line up before asking for his time. Lesson for the process: a probe that needs the owner's hands must be rehearsed by the agent first, as far as it can be, and must state its purpose in the first sentence. |

## Interruptions (each tagged by you: needed / not needed)

| # | What I brought you | Your tag |
|---|---|---|
| 1 | The browser-watching exercise: add a film by hand while I record the traffic (three tries, ~20 min, captured nothing) | **not needed** |
| 2 | Fill in `credentials.toml` with his CheapCharts email and password | **needed** |
| 3 | Permission for the one real proving write (Nashville at $5.99) | **not needed** — his tag. Reading: once he had said "the software adds the item" and supplied credentials, a single proving add of a film from his own queue did not warrant a stop. Narrow lesson, not a standing grant: the brief still requires a yes for real-wishlist writes during the build |

**Score so far: 3 interruptions, 1 needed.**

## Surprises and corrections (sorted: misunderstood intent · implementation defect · changed preference · new opportunity)

| # | What | Kind |
|---|---|---|
| 1 | My three rough structures (chip / Buy Queue page / CLI report) all overshot: he wanted one row mark and one drawer button. I carried the August "ranked queue" framing forward without checking it still held. | misunderstood intent — caught at the sketch stage, before any build |
| 2 | Target rule changed from "exact low" to "low + $1" | changed preference |
| 3 | Round 1 of the mock-ups never showed a film that was ALREADY wishlisted in the list — I left it out to avoid inventing facts about his wishlist, and lost the main thing he needed to see. Fixed in round 2 with rows marked "pretend". | implementation defect in the preview — caught by him on first look |
| 4 | He said "yes, go with the fallback" and then, on using the fallback preview, rejected it outright: "I'm expecting the software to add the wishlisted item and populate the price." His yes was to words he had not pictured; my description of the fallback was not concrete enough to refuse. | misunderstood intent — caught by the real-feel preview, before any build. This is the exact failure the process exists to catch: a typed yes was not agreement; the clickable thing was |
| 5 | He overruled his own August rule and my browser plan in one message: credentials go in one config file keyed by site; everything is driven from Python; "driving a browser is definitely the dumb solution"; find out whether the site has an API. It does — I found it in fifteen minutes by reading the site's own script, something I could have done BEFORE spending his time on three browser-observation attempts. | misunderstood intent (mine: I treated the August rule as fixed and never asked whether it still held) + a process lesson: exhaust what the agent can research alone before asking for the owner's hands |
| 6 | On first sight of the delivery he asked for the one thing the frozen brief listed as deliberately not shipping: an un-wishlist. "There is no way to unwhishlist it. it should be reversable." The line sat in a list of twelve exclusions he approved by reading, never by using — the same failure as correction 4: words he had not pictured. Built the same evening as amendment 1.2. | changed preference or misunderstood intent — his to tag; caught at delivery, before the hands-on test |
| 7 | His hands-on test: no film already on his wishlist got a heart. Every wishlist read failed against the real API while every write worked — the read's answer has no `status` field, the brief had generalised one from the write calls, and every test mocked the read from that prose. 1,546 green tests, three reviews and a final review all missed it, because all of them checked the code against the same wrong sentence. Found in his first minutes with the real thing; fixed as amendment 1.3, which also stops any click from writing before a successful read. | implementation defect — caught by the hands-on test, before any merge. Process lesson: a fixture for an external answer must be captured from the real answer, and "proven against the real account" in a brief must say WHICH calls' answers were actually seen |
| 8 | Second hands-on finding: Scarlet Street, wishlisted by hand long ago, showed no heart and no button — movie-brain held no store id for it, so nothing matched. The brief's Prerequisite had named the missing store ids but only as "no button", and I never asked what a wishlisted film WITHOUT one would look like: nothing at all, silently. Fixed as amendment 1.4 (the wishlist's own store ids are joined to films by IMDb id). | implementation defect (an unexamined consequence of a known prerequisite) — caught by the hands-on test, before any merge |

## Probes used, and whether each changed a decision

| Probe | Decision it was meant to change | Did it? |
|---|---|---|
| Grounding on code and live records | whether the August design still fits reality | yes — the queue was 87% unpriced because the store lookup was stale; two one-off lows challenge the "exact low" rule |
| Three rough structures (`sketches.html`) | where the feature lives | yes — not by being picked: all three were rejected, and rejecting them drew out his actual design in one message |
| Three realistic clickable mock-ups (`mockups.html`) | wording, mark style, whether numbers show before the click | yes — he chose 3 (icon, links row, no prices), against my recommendation of 2 |
| Round 2 of mock-up 3 (`mockup-3.html`) | how an already-wishlisted row and drawer look; badge order | yes — approved: "the rest of that mockup looks great"; three agent defaults shown and not objected to |
| Counterexample: Do the Right Thing ($2.99 once, $4.99 thirty-two times) | whether the target rule survives a one-off low | yes — a real decision came out of it: he kept his rule as is ($3.99), against my recommendation. The probe did its job either way: the choice is now his, on the record, not my silent default |
| Observing one manual wishlist add (three attempts) | whether a silent one-click add is possible | no information — see Friction. Decision made anyway: he chose the fallback ("yes, go with the fallback") |
| Fallback preview, two ways (`mockup-4-fallback.html`) — really copies the target and really opens CheapCharts | when the heart appears; failure wording; how a heart comes off | yes, and a bigger one than intended: using it showed him the fallback is not what he wants at all. The software must do the add itself |
| Reading the site's own JavaScript for its API (agent alone, no owner time) | whether a Python-only add is possible | yes — login, add, set-price, remove and read-wishlist calls all found; invalid-token error shape confirmed live. Unproven until run with real credentials |
| Read-only run against his real account (he filled in the credentials file; about 2 of his minutes) | whether Python can log in and read the wishlist | yes — both demonstrated. First attempt failed on my side (the site hashes the password before sending; found in its code, fixed, second attempt worked). 195 wishlisted films, 86 known to movie-brain |
| One real write, with his explicit yes: Nashville added at $5.99 | whether Python can add a film and set its target | yes — proven; wishlist 195 → 196, target reads back as $5.99. First call was refused (the API wants `itemType=buymovies`, and said so); nothing was written by the failed call |
| Second cold read-back, on brief 0.9 | whether the final brief alone carries the intent | yes — reconstruction correct; found 4 contradictions (all mock-up-vs-brief drift, fixed by a precedence rule and wording) and 3 real gaps: a half-finished click left a wrong target (default changed), build-time access to his real account was unstated (now forbidden), and my credentials-file default was scope creep against "simplicity wins" (moved to its own chore). Honest latency (5–10 s, not the preview's 0.9 s) now stated. Cost to him: zero minutes. Brief frozen as 1.0 |
| Cold read-back of brief 0.4 by a fresh agent | whether the brief alone carries the intent | yes — reconstruction was right, but it found 5 contradictions (worst: my price tooltip broke his "no prices" rule; "delivery on live data" broke "no live migration") and the crux I had under-stated: a server-side write needs his session cookie, which his own rule forbids. Cost to him: zero minutes. Brief → 0.5 |
| One public, unauthenticated price-history read (Do the Right Thing) at plan time — no account involved | the exact `priceHdEvolution` format, which the brief gave only as `date:±price~…` | yes — the sign turned out to be the direction of the change, not part of the price; a parser built on the brief's wording alone would have had to guess. Cost to him: zero minutes |

## Probes skipped, and why

| Probe | Why skipped |
|---|---|
| Outcome map | the outcome is already on record in your own words (08-29 handoff) |
| Visual-feel alternatives | too early — structure first |
