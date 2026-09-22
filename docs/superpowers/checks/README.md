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
