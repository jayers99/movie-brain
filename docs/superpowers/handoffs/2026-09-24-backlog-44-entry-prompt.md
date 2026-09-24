# Entry prompt — backlog 44 (drawer edit drops the film → selection moves on)

Paste the block below into a fresh session in `~/code/movie-brain`.

---

Backlog item 44: when a drawer edit makes the open film drop out of the current filtered results, the selection should move to the next film in the list. Start this phase.

Read first, in this order: `docs/backlog.md` item 44 (the owner's wording and the seed shape — the trigger is the WRITE, never the filter), `.claude/rules/dashboard.md` (find-my-row contract: story 6 "nothing jumps" on a chip press is a standing promise), `docs/superpowers/briefs/2026-09-20-find-my-row/brief.md` and its `mockup-1.html` (the stories + Walk-it mock-up format the owner called "far superior"), `docs/superpowers/briefs/2026-09-20-shop-chip/brief.md` story 4 (the undo that loses its home), and `src/movie_brain/web/static/app.js` around `openIndex`, `trackOpenIndex`, `moveDrawerTo` and `stepDrawer`.

This session's deliverable is the brief and the mock-up page, not code: a `docs/superpowers/briefs/2026-09-24-move-on/brief.md` with the seven stories from the seed on real films, real controls and the real sort order, and a `mockup-1.html` with Walk-it buttons that show the three candidate homes for "I change my mind" after the drawer has moved on (row mark with the chip off · undo line in the drawer that moved · ↑ lands on the film before). Then run the gap check at point A (`docs/superpowers/checks/README.md`, snapshot via `scripts/gap_check_snapshot.sh`) and answer every finding in the trial log before I see the page. Show me the stories and the mock-up; I pick the undo variant on the page, with one token. Only after that: plan, subagent-driven build, stories pinned as Playwright tests beside `tests/web/test_find_my_row.py` on its own 80-film server, gap check at point C, then my hands-on test.

Ask me nothing that has a recommended answer; take the recommended one and log it.
