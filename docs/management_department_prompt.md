# Management Department Prompt Pack

## Purpose
Reusable prompt guidance for Management Department review (Claude Sonnet or human equivalent) under repository governance.

This artifact supports decision quality and consistency. It does not automate approval.

## 1) What to read first
Read in this order:
1. `AGENTS.md`
2. `docs/direction_guard.json`
3. `docs/roadmap.json`
4. `docs/management_department_runbook.md`
5. Current review artifacts (when present):
   - current brief artifact (`CurrentBriefArtifact`-compatible)
   - management review packet (`ManagementReviewPacket`)
   - review queue item (`ReviewQueueItem`)
6. `docs/management_decision_format.md`

## 2) What to verify
- task is inside active roadmap phase
- hard-gate status and trigger list are explicit
- routing recommendation is consistent with risk level
- proposed action is bounded and testable
- recommendation (`GO` / `PAUSE` / `REVIEW`) is justified

Governance priorities:
1. correctness
2. safety/policy integrity
3. maintainability
4. architecture consistency

## 3) What requires immediate REVIEW
Return `REVIEW` immediately if any hard gate applies, including:
- auth/authz behavior changes
- approval flow or policy/strict mode changes
- actor trust model changes
- audit semantics changes
- schema/migration changes
- dependency addition requirement
- architecture direction or roadmap phase change requirement
- security boundary or external contract concerns

Cross-department ambiguity also requires `REVIEW`.

## 4) When GO is allowed
Return `GO` only when all are true:
- no hard gate triggered
- in active roadmap phase
- no dependency/migration/architecture change needed
- scope is small and explicit
- verification path is clear and local

## 5) When PAUSE is required
Return `PAUSE` when:
- likely valid task but blocker remains local and unresolved
- verification status is unclear or unstable
- next smallest safe step is not yet concrete

## 6) How to format the final decision
Use this structure:
1. Current task
2. Risk level
3. Department routing recommendation
4. Hard gate status (with triggers)
5. Proposed action
6. Decision: `GO` / `PAUSE` / `REVIEW`
7. Rationale
8. Approved next action (or blocked scope)
9. Follow-up constraints

Decision content must align with `ManagementDecisionRecord`:
- `item_id`
- `decision`
- `reviewer_id`
- `reviewer_type`
- `rationale`
- optional constraints/follow-ups/approved_next_action

## 7) How to avoid accidental authorization of risky work
- Apply hard gates before model judgment.
- Treat Action Department and latest aliases (`gemini-flash-lite-latest`, `gemini-flash-latest`) as advisory only.
- Never treat latest-alias output as final authority for risky continuation.
- Preserve the distinction:
  - Management approval outcome (`GO`/`PAUSE`/`REVIEW`)
  - Autonomous continuation eligibility

Important:
- Even with management decision `GO`, autonomous continuation remains disallowed when review is still required (`required_review=true`) or hard gates remain active.

## 8) How to hand result back to repository artifacts
1. Record the narrative review using `docs/review_decision_template.md`.
2. Record structured outcome in `ManagementDecisionRecord`-compatible format.
3. Keep any queue linkage fields (`related_queue_item_id`, `related_packet_id`) when available.
4. If decision is `REVIEW`, specify escalation destination and stop autonomous continuation.
