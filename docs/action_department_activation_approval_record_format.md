# Action Department Activation Approval Record Format

## Purpose
Define a repository-side record artifact for manual activation approval outcomes
for limited live provider use in Action Department.

This artifact records governance outcomes only.
It does not execute provider activation.

## Required fields
- `activation_review_item_id`: identity of the activation review item.
- `activation_target`: target department/provider boundary.
- `activation_scope`: bounded allowed scope for limited live provider use.
- `human_approval_status`: explicit human checkpoint status.
- `management_review_status`: explicit management review completion/status.
- `recommendation`: `GO` / `PAUSE` / `REVIEW`.
- `autonomous_continuation_status`: explicit autonomous continuation eligibility status.
- `retained_constraints`: constraints that remain in force after approval outcome.
- `rollback_disable_expectation`: required rollback/disable behavior if guardrails fail.
- `follow_up_actions_before_broader_live_use`: required follow-up actions list.

## Optional fields
- `approval_record_id`
- `reviewer_id`
- `reviewer_type`
- `approval_timestamp`
- `related_project_id`
- `related_activation_decision_id`
- `related_packet_id`
- `related_queue_item_id`
- `blocker_notes`
- `rationale`

## Governance rules
- Activation approval is not equivalent to autonomous continuation approval.
- Human approval status and management review status must both be explicit.
- Cheap/latest-alias action-model output remains advisory-only for risky work.
- If blockers remain unresolved, recommendation should be `PAUSE` or `REVIEW`.
- If post-activation guardrails fail, disable limited live provider use and escalate.
- For shared boundary constraints, follow `docs/action_department_activation_decision_format.md` (`## Shared governance boundary`).

## Related artifacts
- `docs/action_department_activation_decision_format.md`
- `docs/examples/action_department_activation_decision_example.json`
- `docs/examples/action_department_activation_flow_example.md`
- `docs/management_readiness_checklist.md`
- `docs/management_decision_format.md`

## Example
- `docs/examples/action_department_activation_approval_record_example.json`
- `docs/examples/action_department_activation_approval_record_pause_example.json`
- `docs/examples/action_department_activation_approval_record_review_example.json`

## Lifecycle variants (manual outcomes)
- `GO`: activation may be considered in bounded scope, but autonomous continuation can remain `not_approved`.
- `PAUSE`: blockers or missing evidence prevent activation; keep limited live use disabled.
- `REVIEW`: unresolved governance risk requires escalation before activation can be reconsidered.
