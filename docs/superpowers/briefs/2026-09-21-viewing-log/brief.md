# Task brief — a viewing log (backlog 27)

**Version 0.9 — draft, 2026-09-21, not yet seen by the owner.** First feature to run the gap checker at point A (`docs/superpowers/checks/gap-check.md`) before the stories and the mock-up reach him. Stories first, as in "Find my row", the Shop chip and the trailer link. *Where the mock-up and this brief disagree, the brief wins.*

## Your page

### The stories

All on your real catalogue (a copy from the evening of 2026-09-21). The barometer's shape is the one open question, offered as three variants on the mock-up [mockup-1.html](mockup-1.html); the stories read the same under all three except where marked.

| # | Story | Variants |
|---|---|---|
| 1 | **A casual watch tonight, in two clicks.** I watched Modern Times on the Criterion Channel tonight. I open it and press Liked. A line appears: *today · Liked*. That is the whole record: no rating, no rank, no note. The rating box stays empty; nothing else on the page changes. | B: any step |
| 2 | **A rewatch of a film I rented in 2005.** I Am Cuba: 5★ when I rented it on 2005-01-12, a 9 this year. Watched again tonight. I press Liked, then *worth comparing*. The history reads *today · Liked · worth comparing* above *2005-01-12 · rented · ★★★★★*. Switchblade Sisters, rented twice (2006-12-15 and 2008-04-11), shows both rentals where today's drawer shows only the later one. | B: one step, no tag |
| 3 | **Disliked, but worth study.** After Hours: 3★ in 2005, a 4 this year. Watched again, still not enjoyed, but worth taking apart. A and C say it: *Didn't like · worth deep analysis*. B cannot: one rung. The 4 stays a 4 either way. | differs |
| 4 | **Watched last Saturday.** I saw La haine on Saturday and forgot. I press Liked today, then change the date on the line to 2026-09-19. The line moves to Saturday. | same |
| 5 | **I logged the wrong film.** Godzilla vs. Gigan and Godzilla vs. Hedorah: both owned, both marked Unseen. I watched Hedorah but logged Gigan. ✕ on Gigan's line, then log Hedorah. Gigan's Unseen mark went out when I logged it and does not come back by itself; the Unseen button is right there. | same |
| 6 | **A "have not seen" film gets watched.** To Be or Not to Be is marked Unseen (marked 2026-09-20). I press Liked: the line appears and the Unseen mark goes out, so the ranker will offer it. The film stays unrated until I type a number, as today. | same |
| 7 | **What did I watch this month?** I press the new Watched chip. The list is the films I logged, most recent viewing first; La haine's Saturday line puts it below the ones watched today. Variant 2 adds a *Watched* column with each film's last date. Variant 1 has the chip alone. | month view 1 / 2 |
| 8 | **I change my mind about tonight.** Back on Modern Times the same evening: I pressed Liked but it was more. I press *worth a rewatch* on the line; the line says both. In B another step replaces the first. Either way one line: a second press today never makes a second viewing. | differs |

**Outcome.** Every film you watch gets a dated line in its drawer with the smallest possible verdict, and one chip answers "what have I watched lately". The 0–10 stays what it is today: a standing judgement per film, edited in the rating box. The long-term film-education programme (notes, taste clustering, the study loop) can hang off this record later; none of it ships now.

**The one question for you.** The barometer's shape, on the mock-up: **A** felt (Didn't like / Liked) plus any of three *worth* tags; **B** your single five-step ladder; **C** A plus *Didn't finish*, whose line takes no tags because a bail is not a verdict. My pick is C, for the reason on the page. "None of these" is a fine answer. A second, smaller pick: the Watched chip alone (**1**) or the chip plus a *Watched* column (**2**, my pick).

**What wins when things trade off.** The record is per viewing and cheap: date, barometer, an optional short note. It never writes a rating, and a rating never writes a viewing. The one side effect of logging is that the film's Unseen mark clears (a watched film is seen); removing a viewing restores nothing.

**What deliberately does not ship.** Moving the 0–10 into the log. Sealed recall, the notes-versus-critics loop, a rating history. Any import: no Apple TV played dates (the export carries none), no Letterboxd or Trakt, no viewing dates invented for the 378 rated films (their `rated_at` is a rating date, 266 of them the August import's stamp). Copying the 2004–08 rentals into the new table: they show in the history by a read-side union and `oldratings` stays their only writer. Dictation or formatting in the note. Phase B. A "this month" count in the header.

| Behaviour | Status |
|---|---|
| The drawer's Watched block, its strip and its lines, under all three barometer shapes | simulated on the mock-up with the real films' real facts (rentals, stars, ratings, Unseen marks) |
| Logging clears Unseen; removing restores nothing | simulated; the Unseen button on the mock-up is live |
| One line per day; a same-day press edits | simulated |
| The 2004–08 rentals in the history, both rows of a twice-rented film | demonstrated on the copy: 3 films hold two rows (A Night at the Opera, Love and Anarchy, Switchblade Sisters); today's drawer shows one, the later rental |
| Watched chip: films with ≥1 logged viewing, newest first; stacks with every chip | simulated (nothing is logged yet, so the live count is 0 by construction) |
| Watched column (variant 2), sortable | simulated |
| Persistence across reload, a failed save's red toast | not on the mock-up: named below |

**What you will see at delivery.** The dashboard with the block, the chip (and the column, if 2); the eight stories passing as Playwright tests under their own names; one migration (`030_viewing.sql`, applied by `migrate --apply` after your yes, with the automatic backup); a plain list of anything unverified. Then you try it, and only after your say-so is it merged.

## Builder's pages

**Decision provenance**

| Decision | Whose |
|---|---|
| The record: one film → many viewings, each date + barometer + optional note | your request, 2026-09-20 |
| The 0–10 stays per film and is untouched; ranker, chips, header counts, export untouched | your ruling, 2026-09-20 |
| The barometer's shape (A / B / C) | **yours, on the mock-up** |
| Watched chip alone or with a column (1 / 2) | **yours, on the mock-up** |
| The block sits in the drawer's ratings block, directly under My rating, above the critics' line; the strip logs TODAY with one click, the line then takes the date, tags and note | agent default, shown in the mock-up |
| One line per calendar day: a strip press when today's line exists edits it (felt / step); another date is another line; the date box moves a line | agent default, shown in the mock-up (story 8) |
| Logging a viewing clears the film's Unseen mark through the existing `set_unseen` path (which also drops rank placements, as today's Unseen button does); removing a viewing restores nothing | agent default, shown in the mock-up (stories 5, 6) |
| The "Me, 2004–08" line is replaced by the history list; rentals are greyed, read-only, newest first, every row of a twice-rented film shown; the Rewatch chip and the table's stars badge keep reading `old_rating` exactly as today | agent default, shown in the mock-up (story 2) |
| Rentals do not count as viewings for the Watched chip or the column | agent default, named on the mock-up page |
| Watched chip: plain (on / off), after Shop, before the list picker; while on the default sort leads with last viewing desc (the On-a-list precedent); key `watched` in the URL like any chip; Clear resets it | agent default, shown in the mock-up |
| Variant 2's column: `Watched`, last viewing date, after My Rating, sortable; empty for every film until something is logged | agent default, shown in the mock-up |
| Storage: table `viewing` (`id` PK, `film_id` FK not unique, `watched_on`, the barometer columns the chosen variant needs, `note`, `logged_on`), migration 030; `merge_film` re-points viewings with a plain UPDATE, `_ONE_ROW_TABLES` untouched (many rows per film) | agent default, not visible |
| API: `POST /api/films/<id>/viewings` (creates today's or the given date's line; a same-day POST updates), `PUT /api/viewings/<vid>` (date, barometer, note), `DELETE /api/viewings/<vid>`; `/api/films/<id>` gains detail-only `viewings` (with the rental rows as `kind: rental`, read-only); `/api/films` gains `last_watched` and `viewing_count` | agent default, not visible |
| A failed save: the red toast the rating box uses, no line drawn (`Could not log the viewing`); the line is drawn from the server's answer, never optimistically | agent default, named on the mock-up page |
| Sync, `enrich`, every import verb: never write `viewing` | agent default (the watchlist pattern) |
| A tombstoned or merged-away film: viewings follow the survivor on merge; a tombstone keeps them (immutable films) | agent default, not visible |

**Execution authority.** The builder may decide anything not visible. `migrations/030_viewing.sql`, `infrastructure/database.py`, `domain/models.py` (`FilmView.last_watched`, `viewing_count`), `domain/filters.py` (`watched`), `web/app.py`, `app.js`, `index.html`, `app.css`, tests, plus the docs that go stale (`CLAUDE.md` commands, `.claude/rules/dashboard.md`, the backlog). Not without a separate yes: `migrate --apply` on the live database, merge, push.

**Repository grounding.** `app.js::renderDrawer` ratings block (`My rating` input, `oldLine` from `d.old_rating`, `criticsLine`, `listsLine`); `database.py::_old_rating_by_film` keeps ONE row per film for the view (latest rental, ties to the higher line), which is why today's drawer shows one rental; `old_rating` holds 203 rows, 139 linked to 136 films, three films twice; `unseen` holds 143 films, `set_unseen` is the one writer and also clears rank placements; `my_ratings` holds 378 rows, all `rated_at` in 2026-08/09; `filters.py::_PREDICATES` / `CHIPS` pinned by `test_chip_names_are_stable`, `index.html` chips row pinned by `test_chip_labels_and_order`, `app.js::CHIP_PREDICATES` and the `multi_list` sort hook in `applyFilters`; `_ONE_ROW_TABLES` in `merge_film` is for single-row tables only. Story films verified on the live copy 2026-09-21: Modern Times #2397 (Criterion, unrated), I Am Cuba #668 (5★ 2005-01-12, rated 9), After Hours #1203 (3★ 2005-02-07, rated 4, no service I have), La haine #3023 (Criterion, unrated), Godzilla vs. Gigan #1477 and Godzilla vs. Hedorah #1478 (both owned, both unseen), To Be or Not to Be #1057 (Criterion, unseen since 2026-09-20), Switchblade Sisters #4164 (4★ 2006-12-15 and 4★ 2008-04-11, rated 9, owned).
