# Trial log — a viewing log

First feature to run the gap checker (backlog 38) at point A, before the owner sees the stories and the mock-up. Chosen for that on 2026-09-21: the most controls to grid, the most exclusions he would bump into.

## Your active time

| When | What you did | Rough minutes |
|---|---|---|
| 2026-09-20 | described the log and what it is for; ruled the 0–10 stays per film | unmeasured |
| 2026-09-21 | picked the viewing log as the gap checker's first live test ("proceed with the viewing log") | 1 |

## Interruptions (each tagged by you: needed / not needed)

| # | What I brought you | Your tag |
|---|---|---|

## Surprises and corrections (misunderstood intent · implementation defect · changed preference · new opportunity)

| # | What | Kind |
|---|---|---|

## Probes used, and whether each changed a decision

| Probe | Decision it was meant to change | Did it? |
|---|---|---|
| Grounding on a read-only copy of the live records (the dashboard's own `/api/films/<id>` on a copy, plus `old_rating`, `unseen`, `my_ratings`) | which real films carry each story, and whether the drawer shows every rental | yes: three films hold two rental rows and the view keeps one; both Godzillas are owned AND unseen, which made story 5 sharper; 143 unseen films, so story 6 is common, not a corner |
| Headless rehearsal of the mock-up, every story, all three barometers, both month views | whether the page does what the stories say | run 2026-09-21 before the gap check; see below |
| Eight stories + one mock-up, three barometers, two month views (`mockup-1.html`) | A / B / C; 1 / 2; which stories are kept | pending: the page has not reached him |
| Gap check, point A (`docs/superpowers/checks/gap-check.md`, fresh agent on a snapshot of cd82765 + the live database) | what is untrue, unpictured or unwalkable before he reads it | yes: 16 findings, 12 agent minutes; two stories added (a rated film never logged; the morning after), story 6's ranker claim corrected, the date box's refusals and every failed write given an answer, Love and Anarchy's duplicate rental collapsed, After Hours drawn as gone from Criterion, the empty-chip state and the column sort made real on the mock-up. Cost to him: zero minutes |

## Gap check (point A)

Run 2026-09-21 on a snapshot of cd82765 with a copy of the live database (`scripts/gap_check_snapshot.sh HEAD … viewing-log-a`); the findings file is in the session scratchpad. Every finding answered; one fix wave (mock-up + brief), then a scoped re-check.

| # | Finding (kind) | Answer | Note |
|---|---|---|---|
| 1 | Story 6 says logging puts the film in the ranker; true for To Be or Not to Be only through its hidden Rank-this mark (story-untrue) | fixed | story 6 rewritten in brief and mock-up: the mark goes out; the ranker offers it because it is MARKED; a film neither owned, marked nor rated 6–10 is not in the pool. Mock-up now draws Rank this lit (real `rank_marked`) and the Tier row for tier films |
| 2 | Date box: moving a line onto a day that already has one, a future date, a blank (gap-unpictured) | fixed | rule added: refused with a toast, old date put back (mock-up does it; brief names 409 / 400) |
| 3 | Switching to B after *Didn't like* in C lit *Liked* (story-untrue, mock-up defect) | fixed | A/C and B are two views of one record: felt + tags ↔ step; story 3 now honestly shows B keeping one rung |
| 4 | Watched chip on an empty log: the real table would be blank (gap-unpictured) | fixed | agent default: an empty-result row for every chip set (*No film matches.*), *No viewing logged yet.* under Watched; mock-up text matched |
| 5 | The morning after is never pictured (gap-unpictured) | story added | story 10, walkable: the page moves to 2026-09-22 |
| 6 | Failed PUT / DELETE, note length (gap-unpictured) | fixed | decision table: snap back to what the server holds, toast per write, 200-character cap (`maxlength` on the mock-up) |
| 7 | Rated with no rental, 363 of 378 films, only a list line (exclusion-to-walk) | story added | story 9, Dragon Inn, in his voice as the checker wrote it |
| 8 | Love and Anarchy's two rows are one rental twice (story-untrue) | fixed | history collapses same-date same-stars rows; brief's count corrected (two real second rentals, one duplicate) |
| 9 | Rentals not counting as viewings only a panel line (exclusion-to-walk) | story added | folded into story 7: Switchblade Sisters is not in the Watched list |
| 10 | ✕ on a film's only line under Watched leaves the list mid-drawer (gap-unpictured) | fixed | story 7 names the Shop rule (row leaves, drawer stays, ↓ carries on); brief decision row |
| 11 | After Hours is gone from Criterion; mock-up drew it live (story-untrue) | fixed | mock-up draws the `gone` badge and *Gone from Criterion* from the real `departed` flag |
| 12 | Story 1's "nothing else changes" untrue under month view 2 (story-untrue) | fixed | story 1 names the Watched cell changing |
| 13 | "The export carries no played dates" not provenanced (provenance) | fixed | reworded: the export ASKS for name, year, duration only; whether TV.app would answer a played date was not tried |
| 14 | `set_unseen` drops placements only when marking (story-untrue, brief wording) | fixed | decision row corrected; I Am Cuba keeps tier 1 |
| 15 | "named below" pointed at nothing (gap-unpictured) | fixed | reload / persistence in the failed-save decision row |
| 16 | Column "sortable — simulated" did not sort; real sort's empties undescribed (gap-unpictured) | fixed | mock-up header sorts; never-logged films last both ways, in story 7 and the brief |

Agent minutes: 12 · Findings: 16 · Fixed: 13 · Stories added: 3 · Declined: 0 · Not checked: TV.app's played-date property (outside the snapshot); point C checks (nothing built); Seven Samurai was dropped from the mock-up (no story used it).

### Scoped re-check (point A, same day)

Relaunched with `Re-check only findings: 1–16` on a snapshot of ce0d6fc. About 6 agent minutes. **13 of 16 closed.** Three were still open, all mock-up defects in the fix itself, not in the brief:

| # | Still open because | Answer |
|---|---|---|
| 3 | B lit *Liked* for C's *Didn't finish*, and *Didn't like* after story 8's tag-then-felt walk: the mock-up stored a step and the felt handler ignored the tags | fixed: B's rung is now DERIVED from felt + tags on every draw, never stored (brief decision row says so); rehearsed both walks |
| 10 | the mock-up's ↓ after ✕ under Watched went to the top of the list, not the gap | fixed: the mock-up keeps the open film's index like the real `openIndex`; rehearsed: ✕ on the third film, ↓ opens the film that took its place |
| 13 | the mock-up panel still carried the round-1 wording | fixed: panel matches the brief |

Two seams it also saw, both fixed: the brief's two API rows disagreed on a same-day POST (now: POST on a held date answers 409, the strip's same-day edit is a PUT on today's line); the panel said "the ranker does not move" while story 6 said the film rejoins its queue (now: placements and tiers do not move, a pooled film rejoins the queue).

The spec says the checker never loops, so these three were verified by the builder's own headless rehearsal, not a third run; they are listed here as the diagnostic-checkpoint items and closed. Owner cost across both runs: zero minutes.

**Summary line for the owner:** Checked: 16 findings, 13 fixed, 3 stories added, 0 declined. Not checked: whether TV.app can answer a played date; everything point C covers (nothing is built yet).

## Round 2 (2026-09-27)

The owner picked the story up again ("let's shape backlog item 27") and reshaped the entry path in a spoken brain dump; three rulings followed (title-only ladder, words stored in the database, proceed to stories). `shaping.md` §7 has the record; `brief-2.md` and `mockup-2.html` are the round-2 page.

### Your active time (round 2)

| When | What you did | Rough minutes |
|---|---|---|
| 2026-09-27 | brain dump in a user-story voice (dictation through the agent → deterministic commands); ruled the identification ladder; picked database storage; "proceed" | unmeasured, under 15 |

### Probes used (round 2)

| Probe | Decision it was meant to change | Did it? |
|---|---|---|
| Copy of the live database + its dashboard (`/api/films/<id>` for the story films) | which real films carry each story; what the drawer shows today | yes: The Blue Angel is watchlisted and has a 2006 rental (story 1 shows both); Sans Soleil is already rated 9 and in tier 2 (story 6 became "move it", not "place it"); two Solaris, both unrated |
| `films add` dry runs on the copy (tt0018737, tt0022183, tt0019415, tt0019648) | which film the catalogue truly lacks for story 4 | yes: Pandora's Box is HELD under a curly apostrophe (the ladder normalises because of it); Mädchen in Uniform WOULD-CREATE |
| Headless rehearsal of `mockup-2.html`, every story, every turn | whether the page does what the stories say | run before the gap check: 10 stories, 81 turns, no page errors; chip order, empty state and column sort checked |

### Gap check (point A, round 2)

Run 2026-09-27 on a snapshot of 1bb93ea with a copy of the live database (`scripts/gap_check_snapshot.sh HEAD … viewing-log-r2-a`); the findings file is in the session scratchpad. Every finding answered; one fix wave (brief 2.0 → 2.1, mock-up, four stories added), then a scoped re-check.

| # | Finding (kind) | Answer | Note |
|---|---|---|---|
| 1 | Every Criterion command names `criterion-channel`; the registry slug is `criterion` (story-untrue) | fixed | slug corrected everywhere; the panel and the decision table list the real slugs |
| 2 | The real drawer and table never refresh after the CLI writes; the mock-up shows them changing (story-untrue) | fixed | decision added: the page re-fetches the open film on window focus / visibilitychange and patches its row; story 1 now says "switch back to the browser and the drawer has refreshed itself"; the mock-up's sys beat says which page updates when |
| 3 | `title_norm` is NULL for 729 visible films incl. Solaris 2002, so the ladder as written finds one Solaris (story-untrue) | fixed | the ladder no longer reads the column: one normaliser (`thumbprint.title_norm`) applied to the dictated title and every candidate's stored title at query time; grounding corrected; a test named for the empty-column case |
| 4 | A stale drawer signal can log the wrong work (73 same-title groups); `viewings open` after a browser close prints the last film (story-untrue) | fixed | the signal is a 30-second heartbeat trusted for two minutes, so a closed browser reports nothing; the same-title-live-drawer case is named on the panel as the owner's ruling and its accepted risk (say the year or director) |
| 5 | Merged losers share titles with 18 live films; the ladder says nothing about them (gap-unpictured) | fixed | candidates are canonical films only (no merged / tombstone disposition); grounding names the 18 |
| 6 | "Blue Angel" / "Godzilla versus Gigan" → NO-FILM → the skill proposes creating a held film (exclusion-to-walk) | story added | story 11: NO-FILM lists the nearest titles (the search bar's title stage), the agent asks "this one?", `films add` only when none fits; `HELD` named as the backstop |
| 7 | Two normalisers named; they disagree on 120 films (gap-unpictured) | fixed | one function, both sides, at query time (see 3); `norm_title` struck from the ladder row |
| 8 | The mock-up's rating box is read-only; the real one is a writer the brief does not retire (story-untrue) | fixed | the box stays a writer (decision row); the mock-up's box and rows are editable again, the left-out note says so |
| 9 | "Apple TV", "HBO", "Max" name two or three slugs; the skill never asks (gap-unpictured) | fixed | mapping rule through the film (owned → store, streams on Apple TV+ → plus; two fits or none → ask); story 7 gains the beat that says it |
| 10 | A double bill, a sentence with no title, a second service for a logged day — no answer (gap-unpictured) | story added | story 12, the checker's three cards: two commands; ask before any rating; a line's service is never overwritten (the mock-up's imitation had overwritten it — fixed) |
| 11 | No way to remove one note (exclusion-to-walk) | story added | `viewings remove VID --note N` added to the verb (one flag, cheaper than explaining it away); story 13 |
| 12 | Import request, a plan, an essay: only lines in "Not in this build" (exclusion-to-walk) | story added | story 14, the checker's three cards; the watchlist star stays the drawer's only writer |
| 13 | The `films add --apply` transcript was not captured from a real run; the dry run's answer not filed (provenance) | fixed | CREATED lines rewritten to the verb's own format from `films.py` / `cli.py` / `catch_up.line()` and labelled as such on the page (no real film is created without his yes); the four dry runs filed in `films-add-dry-runs-2026-09-27.txt`; the missing-keys refusal named in the panel and the skill row; the mock-up mints #5432 (max id 5,431) |
| 14 | 24 hidden films are loggable but unshowable under Watched (gap-unpictured) | fixed | the read model's filter widens to current-or-rated-or-viewed; decision row + a web test |
| 15 | "ALL rental rows" puts Love & Anarchy's duplicate back (story-untrue) | fixed | same-date same-stars rows collapse (round 1's rule restored) in the decision row, the API row and the panel |
| 16 | The rating rule contradicts stories 1 and 5 ("about a six", "Ten.") (gap-unpictured) | fixed | rule reworded: one whole number however hedged is written; two numbers or a fraction is a question |
| 17 | Header reachable count, a future-dated line after story 8, director "from TMDB at creation" (story-untrue, small) | fixed | header 5,074; the mock-up's clock only moves forward (story 8 leaves the page on the 28th); director arrives with OMDb, wording fixed |

Agent minutes: 30 · Findings: 17 · Fixed: 13 · Stories added: 4 · Declined: 0 · Not checked: the drawer signal across two databases (nothing built); TMDB's answer beyond the dry run's own line; the Watched column in the filter header row; everything point C covers.

### Scoped re-check (point A, round 2, same day)

Relaunched with `Re-check only findings: 1–17` on a snapshot of d6c5437. About 10 agent minutes. **15 of 17 closed.** Two halves still open and three defects the fixes had introduced, all fixed in 2.2 and verified by the builder's own headless rehearsal (the checker never loops), listed as the diagnostic-checkpoint items and closed:

| # | Still open because | Answer |
|---|---|---|
| 6 | the "versus" half: the real `title_hits("Godzilla versus Gigan")` returns nothing (FTS ANDs every word, no title holds "versus"); the mock-up's own word filter hid it | fixed: the nearest-title lookup drops articles and vs/versus before asking `title_hits`, then falls back to a normalised substring; the decision row says so and names the failing call |
| 13 | the CREATED line: `films.py` appends the keying status and `keying.py::KEYED_OK` is `matched` / `adopted` / `collision`, so a real run prints `… (1931)  matched`, not `keyed` | fixed: mock-up and grounding read `matched`; the grounding names the three statuses |
| A | story 13 walked after story 12 removed note 4 (the Kanopy remark) while the owner asked to scratch the Jannings one | fixed: the story finds the Jannings note by content and removes THAT number; the card says `--note N` |
| B | story 14 said Solaris (2002) was open one turn before the page opened it | fixed: the beats reordered |
| C | the reworded "two numbers → ask" rule would make story 2's "tier one … tier two" a question | fixed: the rule is "a number offered as a rating"; tiers, years and counts stay in the note (panel + decision row) |

Owner cost across both runs: zero minutes.

**Summary line for the owner:** Checked: 17 findings, 13 fixed, 4 stories added, 0 declined; re-check closed 15, the last 2 and 3 fix-introduced slips fixed and rehearsed. Not checked: the drawer signal across two databases and everything point C covers (nothing is built yet).

**Built 2026-09-27** on `feature/STORY-27-viewing-log`, plan `docs/superpowers/plans/2026-09-27-viewing-log.md`; point C gap check next, on a migrated copy, before the owner's hands-on test.

### Rehearsal on a copy (2026-09-27)

Whole suite, run once before the rehearsal, from the worktree: `uv run pytest -q` → `1876 passed, 1 skipped, 2 warnings in 148.04s (0:02:28)`.

Scratch copy built under the session scratchpad (`$S`), never `~/.config/movie-brain` itself: `cp` of `movie-brain.db`, `tmdb-read-token.txt` and `omdb-api-key.txt` only (never `credentials.toml`), every verb below run with `MOVIE_BRAIN_CONFIG_DIR="$S"`. Expected facts checked against the copy first: #3390 The Blue Angel (1930), #2979 Solaris (1972), #5235 Solaris (2002), #3002 Pandora's Box with the curly apostrophe stored, service slugs `kino-film-collection` and `criterion` — all confirmed by a direct `sqlite3` read of the copy before running any verb.

```
$ MOVIE_BRAIN_CONFIG_DIR="$S" uv run movie-brain migrate --apply
pending: 031_viewing.sql
applied 1 migration(s)
```

```
$ MOVIE_BRAIN_CONFIG_DIR="$S" uv run movie-brain viewings open
OPEN      nothing — no drawer has reported in for two minutes (closed, or the dashboard is not running)
```

```
$ MOVIE_BRAIN_CONFIG_DIR="$S" uv run movie-brain viewings add --title "The Blue Angel" --service kino-film-collection --rate 6 --text - <<'EOF'
I just watched The Blue Angel. The restoration job on it is really good, and I'm watching it on Kino Collection. I would say I'll rate this one about a six.
EOF
LOGGED    #3390 'The Blue Angel' (1930) · 2026-09-27 · kino-film-collection · viewing #1 · the one film with that title · rated 6
```

```
$ MOVIE_BRAIN_CONFIG_DIR="$S" uv run movie-brain viewings add --title "Solaris" --text - <<'EOF'
tonight
EOF
AMBIGUOUS 2 films titled 'Solaris' — nothing written
  #2979  Solaris (1972)  Andrei Tarkovsky  Criterion Channel
  #5235  Solaris (2002)  Steven Soderbergh
  say which: --film ID or --year YYYY
(exit 3)
```

```
$ MOVIE_BRAIN_CONFIG_DIR="$S" uv run movie-brain viewings add --title "Blue Angel" --text - <<'EOF'
dropped the article
EOF
NO-FILM   no film titled 'Blue Angel' — nothing written
  nearest: #3390 The Blue Angel (1930)
  say --film ID if one of these is it; otherwise films add ttNNN mints a new film
(exit 3)
```

```
$ MOVIE_BRAIN_CONFIG_DIR="$S" uv run movie-brain viewings add --title "pandora's box" --text - <<'EOF'
curly apostrophe in the catalogue
EOF
LOGGED    #3002 'Pandora's Box' (1929) · 2026-09-27 · viewing #2 · the one film with that title
```

(No `--service`/`--rate` given for Pandora's Box, so the line carries neither — the ladder still matched the straight-apostrophe dictation to the film held under the curly one.)

```
$ MOVIE_BRAIN_CONFIG_DIR="$S" uv run movie-brain viewings list --since 2026-09-01
2026-09-27  #3002  Pandora's Box (1929)  1 note
2026-09-27  #3390  The Blue Angel (1930)  kino-film-collection  1 note  rated 6
```

All six lines matched the brief's expected wording and exit codes exactly (character-for-character on the ones the brief spelled out in full).

**Dashboard check, port 5712.** Found an unrelated `movie-brain dashboard` already running against the live config from the main checkout (default port, someone else's session) — left untouched; started a second instance on the scratch copy: `MOVIE_BRAIN_CONFIG_DIR="$S" uv run movie-brain dashboard --port 5712`. Opened `http://127.0.0.1:5712/?film=3390` with Playwright (chromium). The drawer's Watched block rendered as:

```
<span class="lbl">Watched:</span> <ul class="viewings"><li class="viewing">2026-09-27 · Kino Film Collection · <details class="note"><summary>"I just watched The Blue Angel. The restora…"</summary><span class="txt">I just watched The Blue Angel. The restoration job on it is really good, and I'm watching it on Kino Collection. I would say I'll rate this one about a six.</span></details></li><li class="rental">2006-12-26 · rented · <span class="old-stars" aria-label="4 of 5 stars">★★★★☆</span></li></ul>
```

Today's line sits above the 2006-12-26 rental line as expected. The rating input (`#drawer input.rating`) read `6`. From a second process (a `subprocess.run` launched from inside the same Playwright script while the page stayed open, so the heartbeat PUT to `/api/drawer` was live), `MOVIE_BRAIN_CONFIG_DIR="$S" uv run movie-brain viewings open` printed:

```
OPEN      #3390 'The Blue Angel' (1930)
```

— matching the brief exactly. Server stopped afterward: `pkill -f "movie-brain dashboard --port 5712"`.

### Gap check (point C)

Run 2026-09-27 on the same migrated copy; the findings file is in the session scratchpad (`FINDINGS.md`, 12 findings with evidence). Every finding answered; one fix wave, no re-check requested.

| # | Finding (kind) | Answer | Note |
|---|---|---|---|
| 1 | A removed viewing's number is handed to the next viewing, so a repeated `remove` deletes a different film's evening (gap-unpictured) | fixed | migration 031 edited (legitimate — unapplied to any real database, unmerged branch): both `viewing.id` and `artefact.id` gained `AUTOINCREMENT`; `remove_viewing`/`remove_artefact` now also return the film's title and the `REMOVED` lines name it |
| 2 | "Say the year or the director and rung 1 is skipped" is only true for the year (story-untrue) | fixed | wording only — brief-2.md's open-film-signal row and the mock-up's panel sentence now say only a year skips rung 1; a director makes the agent confirm the open film first; SKILL.md gained the confirmation rule (no `--director` flag added) |
| 3 | Story 13's note number cannot be read anywhere (gap-unpictured) | fixed | `viewings list --film ID` now numbers every viewing's notes underneath it; SKILL.md points at it before any `remove --note N` |
| 4 | Story 1's starting state and story 10's count are already out of date on this copy (story-untrue) | fixed | changed story cards 1 and 10, and the grounding paragraph's rated/unseen counts |
| 5 | Switching back to the browser collapses the note he opened and moves the drawer's scroll (story-differs-on-screen) | fixed | `refreshOpenFilm` now diffs `my_rating`/`unseen`/`watchlisted`/`last_watched`/`viewing_count`/`rank_tier`/`viewings` against what is already drawn and skips the redraw when nothing changed; when it does redraw, `drawer.scrollTop` is saved and restored |
| 6 | The skill does not carry story 14's three answers (exclusion-to-walk) | fixed | new SKILL.md section "Sentences that are not viewings" (an import request, a plan, a long piece); the frontmatter trigger narrowed so "I want to watch" does not match |
| 7 | `--film` silently wins over a `--title` that names another film (gap-unpictured) | fixed | `log_viewing` refuses (`REFUSED --film ID is 'Title' (Year), not '…'`) when the two disagree past `title_norm` containment |
| 8 | A second service on the same night is dropped without a word (gap-unpictured) | fixed | `ViewingWrite` carries the service the line ends up with; the `ADDED-TO` line now says `· service kept: X (Y noted)` when a differing `--service` was given |
| 9 | `viewings list` and the Watched chip are not "the same rows" (story-differs-on-screen) | fixed | wording only — brief-2.md story 9, CLAUDE.md's command line and the mock-up's story 9 text now say "the same films, one row per viewing…, each row carrying the film's standing rating" |
| 10 | The director column in AMBIGUOUS lists is often "—" (gap-unpictured) | fixed | `_candidate` falls back to `Repository.film_credits(film_id).director` when `films.director` is NULL, the same fallback the drawer uses |
| 11 | A dictation after midnight is dated tomorrow (gap-unpictured) | fixed | SKILL.md only: between midnight and ~5 AM, "tonight"/"just watched" means yesterday, pass `--on` and say so |
| 12 | Small differences between the refusals and the mock-up's transcript (fixture-mismatch) | fixed | `--rate` is now parsed by the CLI itself so a bad value (`7.5`, out of range) answers our own `REFUSED` line, never typer's boxed error; `REMOVED` lines carry the title (finding 1); a bad `--note N` now says how many notes the line has |

Agent minutes: 40 · Findings: 12 · Fixed: 12 · Stories added: 0 · Declined: 0 · Not checked: TMDB/OMDb through `films add` (no keys on the copy); the skill driven by a live agent; heartbeat in a background tab; a real date change.

**Changed story cards:** stories 1, 9, 10 and the panel sentence on rung 1.

### Scoped re-check (point C, same day)

Relaunched with `Re-check only findings: 1–12` on a snapshot of 2d04c89 with a fresh copy migrated by the corrected 031. About 11 agent minutes; 37 story tests passed; all 14 mock-up stories walked with no page error. **9 of 12 closed** (1, 3, 5, 6, 7, 8, 10, 11, 12 — every behavioural fix reproduced on fresh evidence). Three were leftover wording in places the fix wave missed, fixed by the builder and verified by grep and a fresh mock-up rehearsal (the checker never loops):

| # | Still open because | Answer |
|---|---|---|
| 2 | `brief-2.md`'s open-film-signal row still said "saying the year or director skips rung 1" | fixed: the row now matches the panel and the skill (a year skips rung 1; a named director makes the agent confirm the open film) |
| 4 | the mock-up's header, panel and story-10 card still said 394 rated (the counter script too) | fixed: 396 everywhere the page says it (the copy meanwhile holds 397 — he rated one more film the same afternoon; the page states a day, not a live count) |
| 9 | story 9's scripted reply still said "the same rows" | fixed: "the same films … one row per viewing here" |

Owner cost across point C: zero minutes.

**Summary line for the owner (point C):** Checked: 12 findings, 12 fixed (3 changed story cards: 1, 9, 10, plus the panel sentence on rung 1), 0 declined; re-check closed 9, the 3 wording leftovers fixed and rehearsed. Not checked: TMDB and OMDb through `films add` (no keys on the copy), the skill driven by a live agent, the heartbeat in a background tab, a real date change.
