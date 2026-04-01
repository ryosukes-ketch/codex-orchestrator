# Management Decision Format

## Purpose
Define a minimal repository-side record format for Management Department outcomes.

This structure records decisions. It does not apply decisions automatically.

## Required fields
- `item_id`: decision target identifier (e.g. review queue item id).
- `decision`: `GO` / `PAUSE` / `REVIEW`.
- `reviewer_id`: reviewer identity placeholder.
- `rationale`: explicit reason for the decision.

## Optional fields
- `reviewer_type`: `human` / `model` / `system` / `unknown`.
- `constraints`: constraints attached to the decision.
- `follow_up_notes`: required follow-up notes.
- `approved_next_action`: explicitly approved next action text.
- `decided_at`: timestamp placeholder.
- `related_project_id`
- `related_queue_item_id`
- `related_packet_id`

## Governance rules
- Record format is for auditability and handoff clarity.
- `GO` must include clear rationale and bounded next action.
- `PAUSE` should describe blocker and re-entry condition.
- `REVIEW` should indicate escalation or unresolved governance risk.
- Decision records do not bypass hard-gate checks.

## Related schema
- `app/schemas/management_decision.py` (`ManagementDecisionRecord`)

## Example
- `docs/examples/management_decision_example.json`

