# Review of the proposed development workflow

2026-09-19 · Sidecar for the writing agent · Proposal only; no workflow rules changed.

Reviewed: [2026-09-19-human-in-loop-diet.md](2026-09-19-human-in-loop-diet.md), Halo [152](</Users/jayers/code/praxis-workspace/praxis-halo/raw/152-two-agent-partnership.md>) and [155](</Users/jayers/code/praxis-workspace/praxis-halo/raw/155-upstream-intent-synthesis-spec-driven-agentic-engi.md>).

This review evaluates the draft's reasoning and operating design. It does not independently validate its transcript classifications or the reports' external citations. Recommendations below are design hypotheses to trial, not research-established thresholds.

## Main judgment

Keep the central move: spend human attention on concrete intent and taste decisions before substantial implementation, then let agents handle the engineering. The real-data preview, distinction between “wrong” and “more,” and removal of routine implementation questions are the strongest parts.

The draft currently specifies a presentation ritual more precisely than it specifies the context that must survive handoff. Three breadboards, zero marked rows, and a quiet mock review can all occur while the builder still misunderstands the product. Meanwhile, “anything visible → escalate” and “never re-ask” pull in opposite directions. Neither gives an agent enough judgment to run for long.

**The next revision should define what the builder knows, what it may decide, what evidence demonstrates completion, and exactly when new evidence warrants returning to the human.** Optimize total human effort through acceptance and early use, not silence after handoff or length of agent runtime.

## 1. Replace the silence-based stop signal with demonstrated understanding

**Draft anchors: §4.3 and §5.1's “Approved story page = unambiguous intent.”**

The draft correctly doubts a bare “yes,” then treats zero change requests and zero marked rows as stronger proof. Those can also mean fatigue, incomplete inspection, or acceptance of a plausible default. “You cannot name a missing story” asks the human to recall unspecified requirements—the very burden this process is meant to remove.

Use a small set of concrete checks instead:

- The agent restates the intended user outcome, the most important tradeoff, and what deliberately will not ship.
- The human tries a representative journey in the preview, including one consequential awkward case. Their normal actions and corrections are the input; do not turn this into an exam or ask them to execute a test suite.
- The agent probes the highest-impact assumption with a counterexample: “Here is what happens when there is no direct film link.” The human reacts to the behavior.
- Before building, the executor reconstructs the outcome, constraints, delegated choices, and acceptance evidence from the handoff alone. It flags contradictions or missing dependencies. A plausible read-back is a diagnostic, not a guarantee.

Handoff is ready when consequential intent questions are resolved, remaining uncertainty has explicit owners and defaults, and the builder can explain how it will demonstrate the outcome. Silence never changes an assumption into an approved decision.

## 2. Make each upfront interaction earn its cost

**Draft anchors: §4.1, §4.4, §4.8.**

The proposed new-feature path still contains many required human gates. An outcome tree, three breadboards, example table, taste comparison, real-data mock, missing-story question, and approval may simply replace one expensive ceremony with another.

Choose the next artifact according to the uncertainty it can resolve:

| Uncertainty | Useful probe | Skip when |
|---|---|---|
| What problem is worth solving? | Short outcome map or comparison with the current workflow | Outcome is already clear |
| Where should the interaction live? | Two or three meaningfully different structures | Existing structure is explicitly retained |
| What should happen? | Concrete examples and a counterexample | Behavior is unchanged |
| How should it feel? | Realistic visual or interactive alternatives | Existing approved pattern applies |
| Can it work with actual data? | Read-only sample or bounded technical spike | Relevant capability is already demonstrated |

Every proposed question or artifact should have an agent-side answer to: “What decision will this change, and what would happen if we skipped it?” Keep that reasoning out of the human's routine reading burden.

Do not make “new feature” automatically mean the full sequence, or “follow-up” automatically mean examples only. A follow-up can change the core interaction or create a migration; a new feature can reuse a settled pattern. Route by uncertainty, consequence, and reversibility.

Allow “none,” “combine these parts,” and “keep the existing behavior.” Do not force a winner among three agent-generated candidates. Stable option names aid comparison across rounds; shuffling every presentation can add orientation work. A neutral first comparison is a reasonable experiment, but the observed recommendation acceptance rate does not establish that labels caused the choices. Humans may rationally delegate. Offer a recommendation when requested or when the human explicitly delegates that choice.

## 3. Add feasibility checks before the preview becomes a promise

**Draft anchor: §4.5's service example.**

“The film's own page, not a search” and “the good restoration wins” depend on data the implementation may not possess. A compelling mock can hide this. The resulting argument after handoff would be about feasibility even though it feels like broken intent.

Before requesting commitment to such behavior, the agent checks representative records and available integration capabilities. Mark each preview behavior as demonstrated, simulated, or unresolved. Use a read-only snapshot or fixture with known provenance where practical. Mutating interactions can update local mock state; a clickable preview must not accidentally perform real purchases or production writes.

Use fidelity appropriate to the question. Rough structures are useful for navigation decisions; typography, hierarchy, motion, density, and keyboard behavior need a more realistic slice. “Low fidelity first” should be a useful default, not a ban on the medium needed to judge taste.

## 4. Make the handoff a compact decision record with executable evidence

**Draft anchors: §4.1 step 11 and §6.**

The most important artifact is currently described in a sentence. Expand this before expanding the agent architecture. Keep one authoritative task brief, with linked previews and evidence, rather than several independently edited versions of the same requirements.

Suggested minimum contents:

1. **Outcome and priority:** who is trying to do what; what matters most when tradeoffs arise.
2. **Scope and non-goals:** observable behavior included, excluded, and intentionally unchanged.
3. **Chosen experience:** versioned preview, representative data, and the key decisions it embodies.
4. **Acceptance examples:** normal behavior, important failure/recovery behavior, and the evidence each requires.
5. **Decision provenance:** explicit human choices versus agent defaults versus unresolved assumptions. Record why rejected alternatives were rejected when that reason could prevent drift.
6. **Taste boundaries:** scoped examples and anti-examples; hard requirements distinguished from preferences.
7. **Execution authority:** choices agents may make, limits they must respect, actions already authorized, and actions that require a separate decision.
8. **Repository grounding:** relevant components, existing conventions, validated dependencies, test commands, and known baseline failures. The agent gathers this; the human should not author it.
9. **Recovery and completion:** how work resumes after interruption, what constitutes done, and what the human will see at delivery.

Use simple traceability where valuable: decision D3 → preview state → acceptance example E4 → verification evidence. Human review sees a short behavior summary and consequential changes, not the implementation plan or this entire checklist.

Freeze a version of agreed intent, not reality. New evidence can amend it. Preserve the original decision and record the changed assumption, consequence, and authority for the amendment. Do not silently rewrite the specification to match the implementation.

## 5. Define an autonomy boundary that tolerates ordinary judgment

**Draft anchor: §5.2.**

“Anything you would see” is too broad: almost every UI implementation fills small gaps in a mock. “Never re-ask” is too strict: a previously harmless dependency choice can acquire a licensing, cost, or product consequence. The correct target is **zero unnecessary re-escalations**, not zero escalation regardless of evidence.

Replace the rule with:

> Within approved outcomes, constraints, and delegated tolerances, decide and continue. Return a decision only when new evidence invalidates a material assumption, changes an approved behavior or tradeoff, exceeds granted authority, or prevents trustworthy verification.

Examples:

- Minor spacing that follows the approved component system: decide and continue.
- No direct title URL exists for a service: use the approved fallback if present; otherwise return the visible tradeoff.
- A new helper or internal algorithm: decide within established constraints.
- A storage or dependency change: assess actual compatibility, rollback, operational cost, and authority; the category alone does not make it safe to batch.

When escalation is necessary, deliver the smallest decision packet: what was discovered, which expectation it affects, a concrete example or preview, the recommended response, and what independent work can continue. Evidence need not be a pass/fail test when the issue is a product tradeoff.

Historical approval counts suggest candidates for explicit standing authority; they do not themselves grant it. Keep implementation readiness, merge authority, and production/data-change authority distinct. The draft calls final merge approval wasteful, then restores it in §5.1 without resolving the policy.

## 6. Long runs need checkpoints and resumption, not just a final auditor

**Draft anchor: §5.1.**

A long implementation can be composed of short, internally verified slices. The human need not supervise each slice. Have the builder first complete a thin end-to-end path tied to an approved example, then continue through remaining work while maintaining compact state:

- current task-brief version and repository revision;
- completed outcomes with evidence;
- open assumptions, blockers, and decisions made within authority;
- next action and last verified checkpoint.

At each meaningful slice, check acceptance behavior and scope drift. On restart, reconcile this record with the actual repository. A final report must identify unverified behavior rather than convert missing evidence into success.

Replace “two failed fixes means the approach is wrong; discard branch” with a bounded diagnostic checkpoint. Two failures do not prove the approach is wrong. Preserve useful work and reproduction evidence, examine whether the fault is implementation, environment, specification, or the test, then change approach or escalate according to impact. Bound total repair effort and repeated failures, not just exchanges whose counters can reset. No automatic branch destruction.

## 7. Broaden the auditor's evidence while narrowing its job

**Draft anchors: §5.1, §5.3, §5.4.**

Execution evidence is excellent for runtime defects. It cannot be the only admissible objection. A missing search box, scope violation, misleading fallback, inaccessible control, or exposed sensitive value can be demonstrated by a requirement comparison, screenshot, static path, or focused inspection. Rejecting those because no failing script exists would exclude the intent failures this workflow is designed to catch.

Require **specific evidence and consequence**. Use a runnable reproduction where appropriate. Separate correctness findings, intent deviations, and optional preferences; suppress unsolicited preference churn without suppressing explicit taste requirements.

The auditor needs the relevant code and execution environment, task brief, preview, and original acceptance examples—not merely a diff and the builder's paraphrase. Independent context should remove persuasion from the builder's conversation, not remove product intent. Give the auditor an isolated scratch area to execute tests while preserving a single integration writer.

Do not make the approved example rows the entire test suite. They anchor expected behavior; agents must derive boundary, regression, and integration checks. Plain-language examples are not executable until their bindings actually test the intended behavior. Nor does token compliance prove taste alignment.

Cap the summary at three top findings if useful, but retain every known material defect. A run with no executed evidence is incomplete on that run; waiting for three rubber stamps is not a verification gate. Conversely, zero defects found can mean the builder did good work. Judge audit value by risk coverage, unique useful findings, false positives, and human cost—not yield alone.

Keep model lineage and coordination technology out of the central hypothesis. First establish whether this shaping and handoff process works. “Agents that talk are less reliable than one” is too universal for the evidence presented. Bounded evidence exchange is the mechanism worth testing; file storage alone does not prevent debate loops.

## 8. Store taste as contextual learning, not rigid commands

**Draft anchor: §4.6.**

“Too many” does not always mean “cap and show N more.” It could mean duplicates, irrelevant content, excessive choices, or poor grouping. “Don't show that” does not invariably authorize retaining the data. A removed scope toggle is a rejected design in a particular context, not necessarily a universal ban on toggles.

For reusable preferences, retain the example, context, inferred reason, confidence, and known exception. Apply explicit project-wide preferences directly. Keep inferences provisional until supported or confirmed. After a correction, update both the affected artifact and its verification path; a taste file no executing agent reads changes nothing.

The human remains free to think aloud, compose, ask, or delegate. “You recognise, you never compose” is a useful service aspiration but an unnecessarily restrictive rule for the person being served.

## 9. Pilot the upstream hypothesis without confounding it with everything else

**Draft anchors: §1 and §7.**

The reported 37 hours are capped response gaps, not measured attention. The displayed phase shares total 86%; identify the remaining share. Preserve these as directional observations with extraction/classification provenance, not precision measurements. “Backend work never had this problem” should become “no such case was identified in this sample.”

Trial the new shaping/handoff method while holding the downstream execution approach reasonably stable. Adding a new auditor at the same time makes attribution harder. A single baseline feature is a useful rehearsal, not a reliable comparator. Recent comparable tasks may be enough for an initial baseline; do not require another cumbersome old-style feature solely for measurement.

Use a lightweight record across several comparable tasks:

| Measure | Purpose |
|---|---|
| Total active human minutes: shaping + interruptions + acceptance + early corrections | Detect effort merely moved upstream |
| Unnecessary interruptions and material intent/taste surprises | Test handoff quality |
| Accepted outcome and defects found during a consistent early-use window | Prevent apparent savings through reduced quality |
| Elapsed delivery time and agent cost | Detect excessive automation overhead |

Approximate timers or end-of-session estimates are acceptable; label uncertainty. Categorize corrections as misunderstood intent, implementation defect, changed preference, or newly discovered opportunity. Classification is not always binary or obvious.

One expensive feature should trigger inspection, not automatic abandonment. Simplify a step when it repeatedly costs attention without changing decisions or catching consequential surprises. Increase autonomous scope gradually after successful handoffs. Trust should follow observed delivery, not document length.

## Requested next revision

1. Retain the historical diagnosis, real-data preview, and “wrong” versus “more” distinction, with the evidence caveats above.
2. Replace the fixed upfront ceremony with uncertainty-driven probes and a concrete handoff-readiness test.
3. Make the task brief, decision authority, and bounded amendment process the core of the proposal.
4. Replace the absolute audit, visibility, re-asking, and two-fix rules.
5. Add one complete worked example from initial intent through preview, human correction, approved handoff, autonomous decision, justified escalation, and final evidence. The service-link example is promising because it exposes real data dependencies.
6. Present the pilot as a proposed operating experiment. Do not install standing workflow overrides from this critique or treat historical “proceed” answers as new authority.

The desired experience: the human makes a few consequential choices with concrete material, sees those choices reflected back accurately, and hands over a bounded outcome. The agent then works through ordinary engineering uncertainty, returns only genuinely new decisions, and delivers evidence that the chosen experience survived implementation.
