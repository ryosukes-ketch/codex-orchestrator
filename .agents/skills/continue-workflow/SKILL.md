---
name: continue-workflow
description: Use this skill when the user asks to continue work, keep building, decide the next step, or determine whether implementation should proceed under the current project direction. Do not use this skill for brand-new project discovery, unrelated debugging, or broad architecture redesign.
---

# Continue Workflow

## Goal
Continue implementation safely and consistently without drifting from project direction.

## Inputs
Before doing anything, read:
- `AGENTS.md`
- `docs/direction_guard.json`
- `docs/roadmap.json`

Also inspect any files directly relevant to the active phase and task.

## Required decision process
Always follow this order:

1. Determine the active phase from `docs/roadmap.json`.
2. Identify the next smallest unfinished task in the active phase.
3. Check whether the task is allowed by `docs/direction_guard.json`.
4. Inspect only the minimum relevant code and docs.
5. Propose the smallest valid implementation step.
6. Run the smallest relevant verification.
7. Return one of:
   - GO
   - PAUSE
   - REVIEW

## Decision rules

### Return GO only if all are true
- The task is clearly within the active roadmap phase.
- The task does not require changing project direction.
- The task does not require new dependencies.
- The task does not require schema, auth, approval, or policy redesign.
- Relevant checks pass or are expected to pass with a small local change.

### Return PAUSE if any are true
- Verification currently fails and the cause is not yet isolated.
- The next valid step is unclear from the roadmap or codebase.
- The task is probably valid but should not continue until a local issue is resolved.

### Return REVIEW if any are true
- The change needs a roadmap update.
- The change needs architecture review.
- The change touches auth, approval, policy, security, or migrations in a meaningful way.
- The change needs a new dependency.
- The task appears to conflict with project direction.

## Output format
Always respond in this structure:

1. Active phase
2. Candidate next task
3. Files inspected
4. Planned change
5. Verification run
6. Decision: GO / PAUSE / REVIEW
7. Reason
8. If GO: perform the change and summarize the result
9. If PAUSE or REVIEW: stop and explain the smallest blocking issue

## Constraints
- Do not broaden scope.
- Do not silently reprioritize phases.
- Do not skip tests after meaningful code changes.
- Do not modify secrets or credential files.
- Do not claim a task is complete without verification.

## Preferred behavior
Be conservative.
Choose the smallest valid next step.
Preserve existing tested behavior unless the roadmap explicitly says to change it.