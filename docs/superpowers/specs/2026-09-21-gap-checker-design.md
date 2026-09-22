# Gap checker — design

*2026-09-21. The "multi-agent adversarial" step of the stories-and-mock-up process (research note `docs/superpowers/research/2026-09-19-human-in-loop-diet-v2.md`, §6, deferred there; owner asked for it 2026-09-21). Decided on a back-test, not on argument: `docs/superpowers/research/2026-09-21-gap-checker-backtest/`.*

## 1. Purpose

Before anything reaches the owner — the story cards and mock-up first, the built feature second — a fresh agent that has seen none of the builder's reasoning checks the work against the real data, the real controls and the real plan, and writes down every gap with evidence. The owner's own time stays on stories, mock-ups and trying the thing; the edge cases he "rarely checks himself" get checked by something that does nothing else.

The owner's example of the gap it exists to catch: he assumed a second click on "Wishlist it" would take the film off again. The frozen brief listed "no un-wishlist" as one of twelve exclusions, he approved the list by reading it, and asked for the reversal the moment he saw the delivery. A checker that grids every new control ("what does a second click do?") and turns every exclusion he might bump into into a walkable story card would have put that in front of him as something to click, before any code.

## 2. What the back-test showed

Two fresh agents were handed the frozen brief, the mock-up and the plan of a past feature exactly as they stood at the freeze (a `git archive` of that commit, with the trial log removed, and the day's database backup), with no access to git history, later fixes, memory or credentials, and the four checks in §4. Scored against five defects that had reached the owner:

| Known miss | Found |
|---|---|
| No un-wishlist (exclusion he then wanted) | yes — the story card written in his voice |
| Scarlet Street: wishlisted by hand, no store id, showed nothing | partial — found the 201 no-store-id films get no button, not that a wishlisted one loses its heart |
| Wishlist read's answer has no `status` key (1,546 green tests, four reviews missed it) | yes, ranked first — pointed at the plan line that gated the read on `status` |
| Story 6's Owned chip is really three-way | yes — measured all three presses on the real chip |
| Pursued is not Out of the Past's real neighbour (unordered list) | yes — real order given with row numbers |

Five more findings were later proved right by history: the hand-set target a click would overwrite, the half-finished click that never gets a target, an add refusal treated as success (all three are what amendment 1.3 had to fix after the owner's hands-on test), the open film leaving the list when rated (became the Shop chip's variant B), the button on a removed store product (BUG-34). Noise: about 8 of 30 findings (mock-up hearts from a different day than the backup, a trial log the back-test itself had removed, cosmetic mock-up fidelity). Cost: 10 and 12 minutes of agent time; 0 minutes of the owner's.

The cold read-back already in the process is a different instrument — it checks the brief against itself. The gap checker checks the brief against the world. Together they would have caught every wishlist defect except the Scarlet Street heart.

## 3. Where it runs

| Point | Input | What it protects |
|---|---|---|
| **A — before the owner sees the stories and mock-up** | brief draft, mock-up page, plan if one exists, snapshot of the tree, copy of the live database | his mock-up round: every story true on the real dashboard, every new control gridded, every exclusion he might try walkable |
| **B — the cold read-back** (unchanged, already in the process) | the brief alone | the brief's internal consistency and its grounding claims |
| **C — after the build, before "try it"** | the feature branch, running on a migrated copy of the live database, the brief and its stories | his hands-on test: real service answers against the fixtures, edge states nobody pictured, keys and clicks out of order, every story replayed on the real app |
| Live-database steps | — | nothing added; the dry run and before/after already do this |

The ceremony scales as the process already does: a new feature runs A, B and C; a follow-up amendment runs C only; a tweak runs none.

## 4. The checker's job

One prompt file, `docs/superpowers/checks/gap-check.md`, holds the four checks (the back-test ran the wording in `research/2026-09-21-gap-checker-backtest/checker-prompt-as-run.md`; the repo copy is that text plus the point-C additions):

1. **Every story is true** — film names, counts, neighbours, sort order, chip states, service and ownership facts, against the real database and the real control, not the mock-up's imitation of it.
2. **Every new control is gridded** — second click, already-done state (the next morning), failure, reload, a film missing the data the control needs, a film that leaves the shown list while the control is in use. Each answer named with a real film.
3. **Every exclusion the owner might bump into is walkable** — a story card in his voice, not a line in a list.
4. **Every claim about an outside service is provenanced** — which real calls were seen, where the captured answer lives; a shape generalised from prose or another call is a finding, with what the tests will mock from it.

At point C, two more:

5. **Every story replayed on the real app** — the Playwright tests under the story names pass, and the story is also walked by hand on the running copy with the real film, screenshot kept.
6. **The fixtures against the real answers** — where credentials exist and the call is read-only, the checker makes the real call once and diffs its shape against the fixture; where the call writes or no credentials exist, it is named under "Not checked". Nothing is ever written to an external account and no credential is read by hand (the owner's standing rule).

Findings are ranked by the damage they would do at delivery; each carries kind, where, the claim quoted, evidence (a query and its rows, a screenshot, a code path — never a hunch), what the owner would see, and confidence. No cap — the back-test needed the tail to be ranked, not cut. Style notes and taste are not findings. A "Not checked" section closes every report.

## 5. Isolation

The checker is read-only and writes one file. It never sees the builder's conversation. It runs on a snapshot, never the working tree: `scripts/gap_check_snapshot.sh <commit-or-HEAD> <db-backup>` exports the tree with `git archive` into the session scratchpad beside a copy of the named database backup in its own config directory holding no `credentials.toml`, and prints the three paths the checker prompt needs. The checker is a fresh `general-purpose` subagent launched with those paths; it is told not to read outside them, not to run `git`, and where the dashboard may be started (a port range). At point C the snapshot is the feature branch and the database copy is migrated first, exactly as the hands-on trial is prepared today.

There is no agent-to-agent chat. The builder reads the findings file and answers it in the trial log.

## 6. Triage — what the builder does with findings

- Every finding is answered in the trial log: **fixed** (with the change), **story added** (a new walkable card), **declined** (with the reason — a false alarm, or a taste call that is the owner's), or **unverifiable** (carried into the delivery's "unverified" list).
- One fix wave, one scoped re-check of the fixed findings only. A finding still open after the second fix goes to the diagnostic checkpoint (v2 §5); the checker never loops.
- The owner sees findings only through their effects: story cards that changed or were added on the mock-up page, and a decision packet when a finding changes something he already approved. Otherwise one line at the foot of what he is handed: `Checked: N findings, F fixed, S stories added, D declined. Not checked: …`.

## 7. Measurement

Per feature, in the trial log, beside the counts it already keeps: findings by kind, how many were fixed / added / declined, minutes of agent time, and — the number that matters — defects the owner still found on the mock-up round and the hands-on test, sorted by the four kinds of correction. The checker is retired from a point when ten consecutive runs at that point find nothing the builder fixes; it is cut back if the owner's mock-up rounds slow down.

## 8. Non-goals

- No cross-lineage auditor, no read-only diff reviewer of raw/152's shape: the back-test's defects were not the kind a diff review catches. Either can be added later if the checker's yield falls.
- No caps on findings, no "three defects" rule.
- No change to the build process itself (TDD with stories as test names, the read-back, the fix wave), to the merge rule (his hands-on test before every merge) or to live-database gates.
- The checker judges true and complete; it never judges taste.

## 9. Deliverables

1. `docs/superpowers/checks/gap-check.md` — the prompt.
2. `scripts/gap_check_snapshot.sh` — the snapshot builder, with a smoke test that it exports a tree, copies a database and writes no credential.
3. `docs/superpowers/research/2026-09-21-gap-checker-backtest/` — the evidence, kept.
4. A "Gap check" section in each feature's trial log (there is no template; the four existing logs share their headings by convention, and this adds one) and a short note in `CLAUDE.md` so a fresh session runs it at A and C.
