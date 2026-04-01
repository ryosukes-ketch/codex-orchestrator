# Dry-Run Management Review Flow Example

## Purpose
Show a repository-side dry-run flow that connects:
1. Review packet
2. Review queue item
3. Management decision record

This is an example flow only. It does not trigger live orchestration.

## Artifact chain
1. Review packet (input to management review):
   - `docs/examples/management_review_packet_example.json`
2. Queue item (derived and queued for management decision):
   - `docs/examples/review_queue_item_example.json`
3. Management decision record (review outcome for the queue item):
   - `docs/examples/management_decision_example.json`

## Linkage fields in this example
- `packet_id`: `packet_20260325_001` (packet artifact)
- `item_id`: `rq_20260325_001` (queue + decision artifacts)
- `related_packet_id`: `packet_20260325_001` (decision artifact)
- `related_queue_item_id`: `rq_20260325_001` (decision artifact)

## Governance interpretation
- Packet and queue recommendation in this example is `REVIEW` because hard gates are active.
- Management decision is also `REVIEW`, preserving stop-and-escalate behavior.

Important distinction:
- Management approval outcome (`GO` / `PAUSE` / `REVIEW`) is a governance decision record.
- Autonomous continuation eligibility is a separate check.
- Even if management outcome is `GO`, autonomous continuation must stay disallowed when
  `required_review=true` or hard-gate risk remains active.
