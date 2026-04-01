# Review Queue Format

## Purpose
Define a minimal repository-side queue item structure for work waiting on Management Department decisions.

This is a coordination artifact only. It is not a live queue system.

## Field contract
- `item_id` (required): unique queue item identifier.
- `current_task` (required): short task statement under review.
- `risk_level` (required): `low` / `medium` / `high`.
- `department_routing` (required): candidate owner department.
- `hard_gate_status` (required): whether hard gate triggers are present.
- `hard_gate_triggers` (optional): list of trigger identifiers.
- `escalation_reason` (optional): primary escalation reason code or note.
- `escalation_reasons` (optional): full list of escalation reasons when multiple apply.
- `recommendation` (required): `GO` / `PAUSE` / `REVIEW`.
- `review_status` (required): queue lifecycle status.
  - `pending`
  - `in_review`
  - `resolved`
  - `escalated`

Optional linking fields:
- `related_project_id`
- `related_brief_id`
- `related_work_order_id`
- `created_at`
- `updated_at`
- `note`

## Operational rules
- Queue items do not replace governance decisions.
- `hard_gate_status=true` should normally route to `REVIEW`.
- Latest alias or cheap-model suggestions cannot override queue escalation signals.
- Final non-trivial decision authority remains with Management Department.
- For backward compatibility, `escalation_reason` remains available as a primary reason while
  `escalation_reasons` preserves the full reason list.
- Legacy payload compatibility: if `escalation_reason` is present and `escalation_reasons` is
  omitted, the item is accepted with normalized behavior:
  `escalation_reason` is preserved and `escalation_reasons` defaults to `[]`.

## Related schema
- `app/schemas/review_queue.py` (`ReviewQueueItem`, `ReviewQueueStatus`)

## Example
- `docs/examples/review_queue_item_example.json`
