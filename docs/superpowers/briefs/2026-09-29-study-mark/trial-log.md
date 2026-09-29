# Trial log — the study mark (backlog 48)

Fifth trial of the version 2 process; the first whose point C is a dual run (Claude checker + Codex checker, spec `docs/superpowers/specs/2026-09-29-two-lineage-gap-check.md`). Point A stays single-lineage.

## Your active time

| When | What you did | Rough minutes |
|---|---|---|
| 2026-09-28 | asked for the tag, in one paragraph (backlog 48) | 1 |
| 2026-09-29 | pasted the entry prompt (the handoff + this feature) | 1 |

## Interruptions (each tagged by you: needed / not needed)

| # | What I brought you | Your tag |
|---|---|---|

## Decisions taken without asking (your standing rule: take the recommended answer and log it)

| # | Decision | Why |
|---|---|---|
| 1 | The word is **study** (line `study`, chip state "To study", flag `--study`, verb `viewings study`) | your seed's shortlist was "study", "re-see", "look again"; "Rewatch" is taken by the 2004–08 chip; "study" is your own gloss ("a subject of analysis") and is one word that reads on a line and in a chip |
| 2 | The mark is a column on `viewing` (migration 032), the film-level view is a read | the log's rule and the seed's own preference; one tag does not justify a table |
| 3 | Two setters: `--study` on `viewings add` (created or appended line) and `viewings study VID [--off]` for a past line by number | The General's mark is retroactive — the request came from a note already logged; reaching a past line through `add --on` would invent words you did not say |
| 4 | The Watched chip cycles (Watched → To study → off) instead of a new chip | a film to study is by definition watched; the bar already has four three-way chips; no new button in the row |
| 5 | The skill sets the mark only on an explicit reason to go back; never from praise; a sentence that could go either way gets one yes-or-no question | your seed's open question; a wrong mark is a wrong study list, and the question costs one word |
| 6 | Nothing clears the mark but `--off`; a second viewing touches no other line; `remove VID` takes the mark with the line | your seed's line ("a later viewing clears nothing by itself") |
| 7 | The Rewatch chip is untouched, name included | renaming it is a separate decision you have not asked for; the exclusion is walked as story 8 |
| 8 | No row badge, no column | the chip state is the finder; the row already carries the Watched date |
| 9 | The plan goes straight to the build without a plan review by you | your entry prompt fixed the sequence; the stories are the contract you review |
| 10 | Codex launcher: `-s read-only` replaced by `danger-full-access` on the throwaway snapshot root, reasoning effort `high`, `--ephemeral` | preflight runs 1–2 (below): read-only cannot run `uv`, write a screenshot or a findings file; workspace-write cannot bind the dashboard's port or launch chromium (its seatbelt denies the mach bootstrap). The snapshot is a git-archive plus a database copy with no credentials, never the repository, so "neither writes into the repository" holds by the same means it holds for the Claude subagent — the prompt and the snapshot, not an OS sandbox; `low` is the config default for chat and would handicap the second lineage against a Claude subagent at the session's own effort |
| 11 | Codex checker's port range 5710–5719, the Claude checker keeps 5700–5709 | the two run at the same time on the same snapshot |

## Surprises and corrections (misunderstood intent · implementation defect · changed preference · new opportunity)

| # | What | Kind |
|---|---|---|
| 1 | Migration 031 IS applied live (schema 31, 11 viewings, 7 notes) — the session memory said it was not; the live steps owed from the viewing log are done | stale memory, corrected before any planning |
| 2 | The default Codex model in the owner's config is `gpt-6-astra` — the "Astral" he remembered this morning when asking what the gap checker was | none |

## Probes used, and whether each changed a decision

| Probe | Decision it was meant to change | Did it? |
|---|---|---|
| The real dashboard on a copy of this morning's database, driven by Playwright: header counts, the Watched chip's order (11 films), the Rewatch chip's count and first five, The General's drawer line | which films, neighbours and counts the stories may name | yes — every name and count in the stories was printed by the probe |
| `viewings list --film 4698` and `viewings list` on the copy | the exact shape of the lines the mock-up imitates | yes — the mock-up prints the real format, `study` inserted after the service |
| `sqlite_sequence` on the copy | the viewing numbers the stories name (#12, #13, #14) | yes |

## Codex preflight (2026-09-29, before feature one)

Snapshot: `scripts/gap_check_snapshot.sh HEAD ~/.config/movie-brain/movie-brain.db codex-preflight` (commit 40ac06a, the live database copied). Prompt: `docs/superpowers/checks/preflight-codex.md`. Model `gpt-6-astra`, effort `high`, Codex CLI 0.159.0.

| Run | Sandbox | Elapsed | Steps ok | Failures (all harness) |
|---|---|---|---|---|
| 1 | `read-only`, `-C <project>` (the page's command) | 78 s | 1 read, 2 sqlite (films=5403, schema=31) | 3 dashboard: `uv` cannot initialise its cache (`~/.cache/uv … Operation not permitted`); 4 playwright: same, no browser; 5 write: `operation not permitted`; 6 stop: nothing to stop, port check `PermissionError` |
| 2 | `workspace-write`, `-C <snapshot root>`, `UV_CACHE_DIR` inside the root | 86 s | 1, 2, 5 write | 3 dashboard: the server exits `Operation not permitted` (cannot bind its port); 4 playwright: chromium's mach bootstrap denied (`Permission denied (1100)`); 6 stop: nothing to stop |
| 3 | `danger-full-access`, `-C <snapshot root>` | 76 s | all six (5251 films on port 5710; drawer opened on Fanny and Alexander; 177 KB screenshot; scratch file; server stopped, port free) | none |

**Preflight passed on run 3.** The full record is `docs/superpowers/checks/codex-preflight-2026-09-29.md`; the launcher's default sandbox is now `danger-full-access` (decision 10).

## Gap check (point A)

Run 2026-09-29 on a snapshot of 5678c82 (the 0.9 draft) with a copy of the live database (`scripts/gap_check_snapshot.sh HEAD … study-mark-a`), a fresh Claude subagent, single lineage as the pilot prescribes; the findings file is in the session scratchpad. The checker replayed the header counts, the Watched chip's eleven, the Rewatch chip's 34 and The General's drawer line on the real page before listing what did not hold. Every finding answered; one fix wave (brief 0.9 → 1.0, mock-up, one verb line, the skill), then a scoped re-check.

| # | Finding (kind) | Answer | Note |
|---|---|---|---|
| 1 | `viewings list --film ID` prints no viewing number, so the stories' `viewings study 2` has nothing to read `2` off (story-untrue) | fixed | with `--film`, every row now ends `viewing #N` (the plain listing is unchanged); scenario pinned; CLAUDE.md, the brief's decision row and grounding, and the skill say so |
| 2 | Story 1 drops the reason he said while story 7 keeps the same kind of words; the rule cannot tell them apart (gap-unpictured) | fixed | the rule is now "his words decide the verb": a sentence naming the reason goes through `viewings add --on <that night> --study --text -` (the words kept as a note, the mark with them — story 1 rewritten: ADDED-TO note 3 · study); bare words ("mark it", "clear it", "done with that one") go by number through `viewings study VID [--off]` (stories 5, 6, 10); skill, decisions table and panel reworded |
| 3 | A viewing or mark made with the drawer closed reaches the Watched / To study list only after a reload; story 4 never says so (story-untrue) | fixed | wording: story 4 opens with the reload and names the rule (only the OPEN film refreshes on focus — the viewing log's contract since it shipped); an exclusion line names it; the grounding names `refreshOpenFilm`'s early return and that `openDrawer` never patches the list; the mock-up's story 4 has a reload beat |
| 4 | The focus refresh's row patch omits `study`, so stories 5 and 9 ("leaves To study") depended on a line the brief did not name (gap-unpictured) | fixed | built in task 4 before the finding arrived (`state.films[i]` patch carries `study`; pinned by `test_study_story_9_a_removed_line_leaves_to_study_and_the_drawer_stays_open`); the brief's drawer decision and status table now name the patch |
| 5 | The `study` word in the drawer looks like a pressed chip and does nothing when clicked (exclusion-to-walk) | story added | story 10, in the checker's wording; the mock-up's pill answers a click with the reason |
| 6 | Nothing in the film's row shows the mark (exclusion-to-walk) | story added | story 11, in the checker's wording |
| 7 | The mock-up's LOGGED line for story 5 says "the one film with that title" with The General's drawer open; rung 1 prints "matched the open film" (story-untrue, low) | fixed | the mock-up prints rung 1's words when the film is open; story 5's card says so |
| 8 | The mock-up's Intolerance row is not today's Intolerance (rated 2, 3 lists, RT 98) (story-untrue) | fixed | the row and the grounding read from the running copy; story 6 says "rated 2 last month, on the watchlist" — the builder's slip: one of eighteen rows was typed, not probed |

Agent minutes: 11 · Findings: 8 · Fixed: 6 · Stories added: 2 · Declined: 0 · Not checked: the skill's reading of the sentences (by hand at point C); `merge_film` and the API shapes (nothing built at point A); the new chip state, empty state and drawer word on the real page (point C).

### Scoped re-check (point A, same day)

Relaunched with `Re-check only findings: 1–8` on a snapshot of ba2f11d (the branch head after the fix wave, so the checker could run the real verbs and the real chip). About 11 agent minutes; the feature's 224 tests passed on the snapshot. **8 of 8 closed** — each with fresh evidence: the `viewing #N` rows, story 1 and 7 run for real (`ADDED-TO … note 3 · study` / `note 2 · study`), the reload measured (Watched 11 → 12), stories 5 and 9 replayed on the real page, the word clicked, the row read, rung 1's line, today's Intolerance. One NEW low finding (9): in story 5 The General is the last row under To study, so after `--off` ↓ from the gap does nothing on the real page (↑ works) while the mock-up's ↓ opened The Cameraman — fixed: the mock-up's gap rule now clamps as the real `trackOpenIndex` does, and story 5 says which arrow works and why.

Owner cost across both runs: zero minutes.

**Summary line for the owner:** Checked: 8 findings, 6 fixed, 2 stories added, 0 declined; re-check closed all 8, one new slip in the mock-up's arrow rule fixed. Not checked: the skill's reading of your sentences (by hand at point C).

## Gap check (point C) — the pilot's first dual run

Run 2026-09-29 on the branch head 70e13e0 with a fresh copy of the live database migrated to 032 (`scratchpad/point-c-db`): two snapshots built by `scripts/gap_check_snapshot.sh` from the same commit and the same file (`cmp` identical), one per checker, so neither could see the other's writes. Same `gap-check.md`, filled identically (only the paths, the port range and the findings name differ). Claude: a fresh `general-purpose` subagent, ports 5700–5709, 14 agent minutes (12:07–12:21), 7 findings, 19 screenshots. Codex: `scripts/gap_check_codex.sh` (`gpt-6-astra`, effort high, full access), ports 5710–5719, 817 s elapsed (13.6 min), 14 findings, 27 screenshots — it opened the copy read-only and worked on an in-memory backup, so its copy's SHA-256 was unchanged; the Claude copy was written to. One harness slip on the Codex side: the launcher pointed `--output-last-message` at the findings path, so Codex's one-line sign-off overwrote the file it had written; the 14 findings were recovered verbatim from the log's heredoc (`FINDINGS-codex.recovered.md`) and the launcher now keeps the last message beside the findings. Both files were read in full before any fix; the labels below were assigned first (12:17–12:23, six builder minutes), the fix wave after (12:24–13:05, about forty builder minutes: two code fixes with tests, eleven named tests, the brief reordered to thirteen stories, the mock-up rebuilt with a stale-list simulation and a persistent log, the skill and the docs).

**Blind compare.** C = the Claude checker's number, F = the Codex checker's.

| # | Finding | Label | Answer |
|---|---|---|---|
| C2 · F5 | "the eleven stories passing as tests under their own names" is untrue — only stories 1, 4 and 9 have named tests (story-untrue) | both | fixed — tests named after every story, the CLI stories as scenarios carrying their number |
| C3 · F8 | the mock-up toasts an explanation when the word `study` is clicked; the real page does nothing and says nothing (story-differs-on-screen) | both | fixed — the toast leaves the mock-up; the coach line explains; the real page stays silent, as the story says |
| C4 · F6 | walked in order, stories 10 and 11 silently re-mark The General and re-log The Cameraman in their setup, and story 11 then shows three films where the card says two (story-untrue) | both | fixed — the stories reordered so that walking them in order needs no silent setup (the row story and the click story sit before the clear; the removal last), every card's starting state true in sequence |
| C1 | the builder's own story-5 screenshot shows one Watched line where the story says two — taken without logging the second watch (story-differs-on-screen) | claude-only | fixed — retaken from the story's own sequence |
| C5 | `viewings add --study` on an already-marked line still prints `· study` as if it set the mark, unlike `viewings study` → `already marked` (gap-unpictured) | claude-only | fixed — the tail says `· study` only when this command set the mark, `· already marked` otherwise |
| C6 | `--no-note --study` yields a line of just `2026-09-29 · study`, unpictured, and one command does what the skill describes as two steps (gap-unpictured, low) | claude-only | true-declined — a date and the mark is exactly what that sentence asks for; the decisions table now says the line may be date + word alone, and the skill says the one-command form |
| C7 | story 11 says the row's badges are "lists and the old stars"; the green best-source pill is there too (story-differs-on-screen) | claude-only | fixed — wording |
| F1 | opening a newly logged film's drawer does not bring its row or chip membership up to date — "on the next reload or drawer open" is half untrue: `openDrawer` never patches the list and the focus refresh then sees nothing changed (story-differs-on-screen) | codex-only | fixed — `openDrawer` now patches the film's row from the detail it fetched (rating, unseen, last watched, count, study, star) and re-applies the filters, so "drawer open" is true; pinned by a test; the same half-truth had stood in the viewing log's own contract since 09-27 |
| F2 | a film with two marked nights: `--off` on one leaves it under To study, and nothing pictures or rules it (gap-unpictured) | codex-only | fixed — the skill's rule: "done with X / clear X" clears EVERY marked line of that film (each by number) and says how many; the decisions table and the clear story say so |
| F3 | a failed detail refresh after a successful clear leaves the drawer marked and silent (gap-unpictured) | codex-only | true-declined — the focus refresh is best-effort and retries on every focus; a toast on a failed refresh would fire on every alt-tab while the server is down; the brief's failure line now names it |
| F4 | repeating the reason-bearing sentence appends the same reason again as a new note (gap-unpictured) | codex-only | true-declined — the log stores what is said, whole, every time (the viewing log's own rule); only the bare re-mark changes nothing; story 6's card now says so |
| F7 | To study plus Rewatch together: the real page says "No film matches." while the mock-up says "Nothing marked for study yet." (story-differs-on-screen) | codex-only | fixed — the mock-up's empty-state rule mirrors the real one (any film marked at all) |
| F9 | the closed-drawer stale list cannot be walked: the mock-up's list is always current, the "reload" beat is text (exclusion-to-walk) | codex-only | fixed — the mock-up now keeps a film logged with the drawer closed OUT of the list until a reload or its drawer opens, exactly as the real page does after F1; story 4 walks it (Sherlock's new line missing until the reload) |
| F10 | persistence after reload is narrated, and a real reload of the mock-up resets it (gap-unpictured) | codex-only | fixed — the mock-up keeps its log in the browser's session storage, so a real reload shows what was logged; a Reset button starts over |
| F11 | `remove --note N` leaving the mark is prose only (gap-unpictured) | codex-only | fixed — the removal story first scratches the reason note and shows the mark staying |
| F12 | `already clear` is mentioned but never played (gap-unpictured) | codex-only | fixed — a beat in the not-there story clears The General a second time |
| F13 | asking for a second or named tag has no refusal story (exclusion-to-walk) | codex-only | story added — in the checker's wording |
| F14 | the analysis-loop exclusion has no attempted-action story (exclusion-to-walk) | codex-only | story added — in the checker's wording |

Counts: both 3 · claude-only 4 · codex-only 11 · duplicate 0 · false-positive 0 · unverifiable 0 · true-declined 3 (C6, F3, F4). Every finding on both sides held on the evidence; none was a hunch. Codex's confirmed findings covered 3 of the Claude checker's 7 (43%, so the 80%-miss stop rule is nowhere near); Codex-only true findings 11 against Claude-only 4 — one feature, no conclusion drawn (three features = feasibility and cost only). Escaped defects after the owner's hands-on test: to be filled in.

**Fix wave (point C).** Code: `ViewingWrite.study_set` and the add's tail (`· study` / `· already marked`, C5); `openDrawer` patches the film's row from the detail it fetched and re-runs the filters BEFORE the open film is set (so `applyFilters`' own URL sync cannot pin `film=` on the previous history entry — found by the first red run of the story-2 test) (F1). Tests: every story with a behaviour is pinned under its number — scenarios 2, 4, 7, 8, 9, 11 in `viewings.feature`, page tests 1, 2, 4, 5, 6, 7, 10, 11 in `test_viewing_log.py` (C2/F5); whole suite green after the wave. Brief 1.1: thirteen stories in an order that walks straight through (C4/F6) — row and click stories before the clear, the removal last, a note removal in it (F11), `already clear` played (F12), the repeat-reason words and the `--no-note --study` form (F4, C6), the "done with X clears every marked line" rule (F2), the drawer-open truth (F1), the failed-refresh line (F3), stories 12 and 13 (F13, F14), the best-source pill (C7). Mock-up: no toast on the word (C3/F8); the list is stale for a film logged with the drawer closed until a reload beat or its drawer opens, as the real page is (F9); the log survives a real reload through session storage, with a Reset button (F10); the empty state mirrors the real rule (F7); `matched the open film` when the film is open; story 12's premise no longer needs a silent re-mark. Screenshot for story 7 retaken from the story's own sequence (C1). Skill: the clear-every-line rule, the one-command date-and-mark form, the `already marked` tail.

Agent minutes: Claude 14 · Codex 13.6 (elapsed) · Findings: 7 + 14 = 21, of which 3 both · Fixed: 13 (incl. the 3 both) · Stories added: 2 · Declined: 3 (true, with reasons) · Builder triage: 6 min · Builder fix wave: ~40 min · Owner minutes on checker output: 0 · Not checked: the skill driven by a live agent (by hand at his test); check 6 (no credentials in either snapshot; no external call in the feature); `merge_film` on the copy.
