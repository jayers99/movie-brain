# Checks

Fresh-agent checks a session runs BY HAND at fixed points of a feature. Each is a prompt file here; the session launches a `general-purpose` subagent with the prompt and the paths, reads the findings file, and answers every finding in the feature's trial log. The checker never sees the session's conversation, git history or a credential.

## Gap check (`gap-check.md`)

Spec: `../specs/2026-09-21-gap-checker-design.md`. Evidence: `../research/2026-09-21-gap-checker-backtest/` — run cold on two past features' frozen briefs, it found 4 of 5 defects that had reached the owner, and 5 more that later fixes proved right, in 10–12 agent minutes each.

**Point A — before the stories and mock-up reach the owner.** Commit the draft brief and mock-up first (the snapshot is a commit, never the working tree), then:

    scripts/gap_check_snapshot.sh HEAD ~/.config/movie-brain/movie-brain.db <feature>-a

Launch one `general-purpose` subagent whose prompt is `gap-check.md` with the Paths block filled from the script's three lines, `Point: A`, the brief folder and a free port range (5700–5709 is the convention). Wait for the findings file.

**Point C — after the build, before the owner's hands-on test.** Migrate a copy of the live database the way the hands-on trial is prepared, then:

    scripts/gap_check_snapshot.sh <branch-head> <migrated-copy.db> <feature>-c

Same launch with `Point: C`. If the owner's `credentials.toml` should be available for check 6, copy it into the CONFIG directory yourself, by name, mode 600 — the script never does, and only for a feature whose read-only calls are worth diffing against their fixtures.

**Triage.** In the feature's `trial-log.md`, a section per run:

    ## Gap check (point A | C)

    | # | Finding (kind) | Answer | Note |
    |---|---|---|---|
    | 1 | … | fixed / story added / declined / unverifiable | … |

    Agent minutes: N · Findings: N · Fixed: N · Stories added: N · Declined: N · Not checked: …

One fix wave, then one scoped re-check of the fixed findings only (relaunch with the same prompt plus the line `Re-check only findings: 1, 4, 7`). Anything still open after that goes to the diagnostic checkpoint (research note v2 §5). The owner sees only the story cards that changed, a decision packet if a finding touches something he approved, and the one summary line at the foot of the delivery.

**Retire** a point when ten consecutive runs at that point produce nothing the builder fixes; cut it back if the owner's mock-up rounds slow down. Ceremony scales as the process already does: a new feature runs A and C, a follow-up amendment runs C only, a tweak runs neither.

## Second lineage at point C (pilot, since 2026-09-29)

Spec: `../specs/2026-09-29-two-lineage-gap-check.md`. Preflight record: `codex-preflight-2026-09-29.md`. For the pilot's features, point C runs TWICE on the same snapshot, the same migrated copy and the same prompt: the Claude subagent exactly as above (ports 5700–5709), and a Codex CLI subprocess through `scripts/gap_check_codex.sh` (ports 5710–5719, findings in `FINDINGS-codex.md` beside the Claude one):

    scripts/gap_check_codex.sh --point C --feature <feature> --project <P> --config <C> --findings <root>/FINDINGS-codex.md

The launcher fills the same `gap-check.md` (the filled copy is kept as `FINDINGS-codex.md.prompt.md`, Codex's output as `.log`), prepares the snapshot's virtualenv once, and runs `codex exec` with `--output-last-message` so the checker's last message IS the findings file. Its default sandbox is `danger-full-access` (see the preflight record: no sandboxed mode can bind the dashboard's port or launch chromium), so the checker is held by the prompt and the snapshot, as the Claude one is. `--recheck "1, 4"` appends the scoped re-check line; `--model`, `--effort`, `--sandbox` override the defaults (`gpt-6-astra`, `high`).

Neither checker sees the other's findings. Before any fix, the builder merges the two files, de-duplicates, and labels every finding `both` · `claude-only` · `codex-only` · `duplicate` · `false-positive` · `unverifiable` · `true-declined` in the trial log, then runs one fix wave and one scoped re-check as usual. Per feature the trial log records: counts per label, builder triage minutes, owner minutes on anything the checkers produced, elapsed time per side, and — after the hands-on test — escaped defects the owner still found. Point A stays single-lineage. Stop rules and the reading of three features are the spec's.
