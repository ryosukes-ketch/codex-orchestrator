# Management Review Session Example

## Input snapshot (abridged)
- current task: "Adjust approval authorization behavior"
- risk level: `high`
- department routing recommendation: `management_department`
- hard gate status: `true`
- hard gate triggers: `["authorization_behavior_change"]`
- proposed action: "Patch authorization checks and update tests"
- packet recommendation: `REVIEW`
- required_review: `true`

## Management review output
1. Current task: Adjust approval authorization behavior
2. Risk level: high
3. Department routing recommendation: management_department
4. Hard gate status: true (`authorization_behavior_change`)
5. Proposed action: patch authorization checks and update tests
6. Decision: REVIEW
7. Rationale: Authorization semantics are governance-sensitive and must not auto-continue.
8. Approved next action: Prepare docs/test impact analysis only; no runtime auth change yet.
9. Follow-up constraints:
   - no auth runtime behavior change without explicit reviewed plan
   - include Audit and Review Department in escalation path

## Structured decision record example
```json
{
  "item_id": "rq_20260325_020",
  "decision": "REVIEW",
  "reviewer_id": "mgmt-sonnet",
  "reviewer_type": "model",
  "rationale": "Authorization behavior change hit hard-gate boundary.",
  "constraints": [
    "No auth runtime behavior change in autonomous path."
  ],
  "follow_up_notes": [
    "Escalate to Audit and Review Department."
  ],
  "approved_next_action": "Prepare a bounded review plan only.",
  "related_queue_item_id": "rq_20260325_020",
  "related_packet_id": "packet_20260325_020"
}
```

## Autonomous continuation reminder
- This review outcome does not grant autonomous continuation for governance-sensitive work.
- `REVIEW` remains a stop-and-escalate decision.
