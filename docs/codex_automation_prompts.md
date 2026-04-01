# Codex Automation Prompts

Use these prompt snippets for safe continuation runs. Customize only the task-specific part.

## 1) Safe continuation prompt
```text
Use $continue-workflow.

Goal:
Continue the next smallest valid task in the current roadmap phase.

Requirements:
- Read AGENTS.md, docs/direction_guard.json, docs/roadmap.json first.
- Inspect only minimum relevant files.
- Apply hard-gate checks before implementation.
- Return GO / PAUSE / REVIEW with reason.
- If GO, make the smallest useful change and run smallest relevant verification.
```

## 2) Docs-only continuation prompt
```text
Use $continue-workflow.

Goal:
Update repository documentation only.

Constraints:
- Do not change runtime behavior.
- Do not add dependencies.
- Keep wording aligned with AGENTS.md and direction_guard.
- End with explicit GO / PAUSE / REVIEW.
```

## 3) Test-hardening continuation prompt
```text
Use $continue-workflow.

Goal:
Add narrow tests for existing governance logic.

Constraints:
- Do not invent new semantics.
- Do not change auth/approval/policy/audit behavior.
- Add only minimal support code if strictly necessary.
- Run targeted tests first, then minimal lint.
```

## Mandatory stop conditions in prompts
Always include these stop conditions:
- "If hard gate triggers, return REVIEW and stop."
- "If verification fails and cause is unclear, return PAUSE."
- "Do not auto-continue risky work from low-cost model suggestions."

## Suggested response contract
Ask automation runs to return:
1. Active phase
2. Candidate next task
3. Files inspected
4. Planned change
5. Verification run
6. Decision (`GO` / `PAUSE` / `REVIEW`)
7. Reason
8. Result summary

