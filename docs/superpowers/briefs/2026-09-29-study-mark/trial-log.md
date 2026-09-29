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
