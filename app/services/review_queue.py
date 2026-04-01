from uuid import uuid4

from app.schemas.management import ManagementReviewPacket
from app.schemas.review_queue import ReviewQueueItem, ReviewQueueStatus


def _normalize_values(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def review_packet_to_queue_item(
    packet: ManagementReviewPacket,
    *,
    item_id: str | None = None,
    review_status: ReviewQueueStatus = ReviewQueueStatus.PENDING,
    created_at: str | None = None,
    updated_at: str | None = None,
    note: str = "",
) -> ReviewQueueItem:
    escalation_reasons = _normalize_values(list(packet.escalation_reasons))
    escalation_reason = escalation_reasons[0] if escalation_reasons else None
    hard_gate_triggers = _normalize_values(list(packet.hard_gate_triggers))
    return ReviewQueueItem(
        item_id=item_id or f"rq-{uuid4().hex[:8]}",
        current_task=packet.current_task,
        risk_level=packet.risk_level,
        department_routing=packet.department_routing_recommendation,
        hard_gate_status=packet.hard_gate_status,
        hard_gate_triggers=hard_gate_triggers,
        escalation_reason=escalation_reason,
        escalation_reasons=escalation_reasons,
        recommendation=packet.recommendation,
        review_status=review_status,
        related_project_id=packet.project_id,
        related_brief_id=packet.brief_id,
        related_work_order_id=packet.work_order_id,
        created_at=created_at,
        updated_at=updated_at,
        note=note,
    )
