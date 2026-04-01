# Management Department Runbook

## Purpose
Define the manual operational handoff for Management Department review (e.g. Claude Sonnet or human reviewer).

## Ownership
- Management Department owns non-trivial governance decisions.
- Action/low-cost model outputs are advisory only.
- Risky continuation cannot be auto-approved by cheap model suggestions.

## Artifact read order (required)
1. `AGENTS.md`
2. `docs/direction_guard.json`
3. `docs/roadmap.json`
4. `docs/current_brief_template.json` compatible artifact (`CurrentBriefArtifact`)
5. `ManagementReviewSummary` / `ManagementReviewPacket` outputs
6. `docs/current_work_order_template.json` compatible artifact (`WorkOrderDraft`) if present
7. `docs/review_decision_template.md` for final recording

## How to interpret review packets
Primary fields:
- `current_task`
- `risk_level`
- `department_routing_recommendation`
- `hard_gate_status`
- `hard_gate_triggers`
- `escalation_reasons`
- `proposed_next_action`
- `recommendation` (`GO` / `PAUSE` / `REVIEW`)
- `required_review`

Interpretation rules:
- Treat packet recommendation as input, not final authority.
- If `hard_gate_status=true`, decision should default to `REVIEW` unless explicit management override is documented.
- If `required_review=true`, do not issue autonomous GO without explicit reasoning.

## Decision behavior

### Return GO only when all are true
- task is inside active roadmap phase
- no hard-gate trigger is active
- no auth/approval/policy/audit/schema/dependency/direction change is implied
- proposed action is small and verification is clear

### Return PAUSE when
- next valid step is unclear
- verification status is unknown or unstable
- request is likely valid but local clarification is still needed

### Return REVIEW when
- any hard gate is triggered
- cross-department coordination is required
- ambiguity affects governance correctness
- escalation_reason indicates risk (`hard_gate_triggered`, `cross_department_routing`, etc.)

## Escalation handling
- If task touches auth/approval/policy/audit/schema/dependency/security boundaries:
  - return `REVIEW`
  - record why escalation is mandatory
  - hand off to Management + Audit/Review path
- If roadmap or architecture reinterpretation is needed:
  - return `REVIEW` and stop implementation continuation

## Ambiguity and cross-department work
- Ambiguous medium-risk work should not auto-continue; prefer `PAUSE` or `REVIEW`.
- Cross-department requests should be routed to management-level review before implementation resumes.
- Require explicit owner department for next step.

## Minimal output contract for management decision
Record decisions using:
- decision (`GO` / `PAUSE` / `REVIEW`)
- reason
- approved scope
- blocked scope
- escalation destination (if REVIEW)
- required verification before next handoff

Template reference:
- `docs/review_decision_template.md`

## Prompt pack references
- `docs/management_department_prompt.md` (operational prompt pack for consistent Management review)
- `docs/examples/management_review_session_example.md` (concrete session example with decision record shape)
- `docs/examples/action_department_activation_flow_example.md` (manual flow for limited live provider activation review)
