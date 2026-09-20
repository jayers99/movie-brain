# Trial log — a chip for films worth buying

Third trial of the version 2 process, upstream half only; stories first.

## Your active time

| When | What you did | Rough minutes |
|---|---|---|
| 2026-09-20 | described the chip and what it is for | 2–3 |
| 2026-09-20 | tried the mock-up, chose B: "option b is great. the new way of html stories and mockup for review is far superior" | unmeasured |

## Interruptions (each tagged by you: needed / not needed)

| # | What I brought you | Your tag |
|---|---|---|

## Surprises and corrections (misunderstood intent · implementation defect · changed preference · new opportunity)

| # | What | Kind |
|---|---|---|

## Probes used, and whether each changed a decision

| Probe | Decision it was meant to change | Did it? |
|---|---|---|
| Grounding on a read-only copy of the live records | what the four conditions mean in data, and how many films survive them | yes — 343 films, 33 of them already wishlisted: what to do with those is the one real design question, and it collides with ↑ ↓ stepping (a film that leaves the list mid-browse silences the arrows today). Also: no trailer link exists anywhere in movie-brain; "for sale" is only trustworthy as "holds a store id" |
| Headless rehearsal of the mock-up, every story, both variants | whether the numbers and film names in the stories are true | yes — every count and the first three films of each list were printed by the rehearsal and copied into the stories, not typed from memory |
| Six stories + one mock-up, two variants, three names (`mockup-1.html`) | A or B; the name; which stories are kept | yes — B, in one round, no change requests; he did not pick a name, so "Shop" stands as an agent default |
| Cold read-back of brief 0.9, checked against the code and the test suite | whether the brief carries the intent and its grounding is true | yes — 14 findings. Worst: the obvious JS mirror (`services.some(s => s.subscribed)`) would have emptied the list, because the Apple store row is itself subscribed; the shared test seed holds no film that matches the chip; and three owner-visible consequences of B nobody had looked at (no grey mark after closing on a wishlisted film, no way back to it under Shop, a failed click going silent if he has already stepped on). Cost to him: zero minutes |
