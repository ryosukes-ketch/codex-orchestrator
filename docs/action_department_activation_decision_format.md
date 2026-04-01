# Action Department Activation Decision Format

## Purpose
Define a repository-side decision artifact for Management Department judgment on whether
limited live provider use may begin for Action Department.

This artifact is for dry-run/operational governance recording only.
It does not trigger live provider activation by itself.

## Required fields
- `activation_target`: target department and provider usage boundary
- `activation_scope`: explicit limited scope for allowed provider use
- `preconditions_satisfied`: checklist of prerequisites that are already met
- `remaining_blockers`: blockers that still prevent activation (empty list allowed)
- `human_approvals_recorded`: explicit approval checkpoints and status
- `recommendation`: `GO` / `PAUSE` / `REVIEW`
- `autonomous_continuation_status`: explicit status for autonomous continuation eligibility
- `rollback_disable_expectation`: rollback/disable instruction if guardrails fail

## Optional fields
- `activation_decision_id`
- `related_project_id`
- `related_packet_id`
- `related_queue_item_id`
- `reviewer_id`
- `reviewer_type`
- `rationale`
- `follow_up_actions_before_broader_live_use`
- `decided_at`

## Governance rules
- Activation approval is not equivalent to autonomous continuation approval.
- Latest-alias Action Department outputs remain advisory for risky or governance-sensitive work.
- Hard-gate-first escalation remains mandatory.
- If guardrails fail post-activation, disable limited live provider use and return `REVIEW`.

## Shared governance boundary
Use the following canonical boundary statements in dry-run activation companion flows:

- Activation decision artifacts are advisory-only until the required governance checkpoint is completed.
- Unresolved blockers prevent activation from continuing.
- A paused activation path requires blocker clearance and re-review before continuation.
- A review path must identify an explicit escalation destination.
- Activation approval and autonomous continuation approval are separate decisions.
- Autonomous continuation remains not approved unless explicitly approved through the required governance process.

## Related artifacts
- `docs/management_readiness_checklist.md`
- `docs/model_governance_policy.md`
- `docs/management_decision_format.md`
- `docs/examples/management_review_flow_example.md`

## Example
- `docs/examples/action_department_activation_decision_example.json`
