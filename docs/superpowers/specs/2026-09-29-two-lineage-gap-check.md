---
title: Two-Lineage Gap Check — a dual-run pilot at point C
type: cycle
status: seed
tags: [gap-checker, experiment, cross-lineage, verification]
sources: []
derivative: extracted
origin_path: wiki/(extracted)
origin_repo: praxis-halo
origin_sha256: 942f3fd692a929c27156fea59b85cb211dcca40d088a326afa1f385f7c5db3e5
scrub_rules: handoff/scrub-rules/wiki-two-agent-pilot.distill.md
scrub_rules_sha256: 942f3fd692a929c27156fea59b85cb211dcca40d088a326afa1f385f7c5db3e5
scrubbed_on: 2026-09-29
handoff_bundle: two-agent-pilot
---

# Two-Lineage Gap Check — a dual-run pilot at point C

**Question.** Does a gap checker of a different model lineage (OpenAI, via Codex CLI) find real defects at point C that the same-lineage checker (a fresh Claude subagent) misses, and at what cost in triage time and owner minutes? A private research report on dual-agent software architectures (30 sources) predicts lineage diversity pays only on high-uncertainty, broad-surface work, and names the conditions under which a second agent lowers throughput. The gap-checker spec deliberately left the cross-lineage auditor unbuilt: "either can be added later if the checker's yield falls." This pilot measures instead of assuming.

**Prior review of this design.** A first draft swapped the checker outright for three features. Codex CLI reviewed that draft cold and returned five objections, all accepted: the swap removed the Claude counterfactual that the stop rules need; it confounded lineage with harness; three features is a smoke test, not evidence (the report's rule is ten); the baseline was a single run; and counting findings rewards a noisy auditor over one that prevents escaped defects. The design below is the amended one. One thing the review said not to water down: the file-only, no-chat handoff.

## Design: dual-run, blind compare

1. **Preflight, before feature one.** From a gap-check snapshot directory, confirm that `codex exec -s read-only` can: read only the snapshot and the config copy; run sqlite against the database copy; start the dashboard in the agreed port range; drive it with Playwright; write screenshots and a findings file. Record each failure as *harness*, never as *model*. If the preflight fails, fix the launcher or stop; do not run the pilot on a checker that cannot reach the app.
2. **Point C, both checkers, same inputs.** Same `gap-check.md` prompt, same snapshot, same migrated database copy, same port-range convention. The Claude checker runs exactly as today. The Codex checker runs as one subprocess: `codex exec -C <snapshot> -s read-only -m <model> --skip-git-repo-check --output-last-message <findings-codex.md> - < <prompt>`. Neither checker sees the builder's conversation or the other's findings. Neither writes into the repository.
3. **Blind compare before any fix.** Merge the two findings files, de-duplicate, and label every finding one of: `both` · `claude-only` · `codex-only` · `duplicate` · `false-positive` · `unverifiable` · `true-declined` (real, not worth fixing). Then one fix wave and one scoped re-check, as the spec already runs them. No agent chat at any step.
4. **Record per feature.** Counts per label; builder triage minutes; owner minutes spent on anything the checkers produced; and, after the owner's hands-on test, escaped defects the owner still found. The primary number is accepted fixes per owner minute, not findings.
5. **Point A stays single-lineage** for the pilot. One variable at a time.

## Reading the result

- **Three features = feasibility and cost only.** Report whether the Codex run completes, how long each side takes, and cost per true finding. Do **not** read zero `codex-only` true findings across three features as evidence against cross-lineage checking; the report's zero-yield rule needs ten consecutive tasks.
- **Continue to ten** if the preflight passed and the cost per `codex-only` true finding is at or below the Claude checker's cost per true finding.
- **Stop and revert to single lineage** on any of: owner minutes on checker output exceed two per feature; Codex misses more than 80% of the Claude checker's confirmed findings on the same snapshot; ten consecutive features with no `codex-only` true finding.
- **Swap roles instead of stopping** if `codex-only` true findings consistently exceed `claude-only` ones: the second lineage becomes the default checker and Claude the dual-run comparator.

## Not built, on purpose

No MCP server, no agent-to-agent protocol, no diff reviewer, no findings cap, no synchronous exchange between checkers or between a checker and the builder. Files in, a subprocess, a file out. Add any of these only if the pilot's own numbers ask for it.
