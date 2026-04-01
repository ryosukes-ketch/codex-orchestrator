from app.schemas.review_queue import ReviewQueueItem, ReviewQueueStatus


def test_review_queue_item_minimum_required_fields() -> None:
    item = ReviewQueueItem(
        item_id="rq_1",
        current_task="Review risky task",
        risk_level="high",
        department_routing="management_department",
        hard_gate_status=True,
        recommendation="REVIEW",
    )

    assert item.item_id == "rq_1"
    assert item.review_status == ReviewQueueStatus.PENDING
    assert item.hard_gate_status is True
    assert item.recommendation == "REVIEW"
    assert item.hard_gate_triggers == []
    assert item.escalation_reasons == []


def test_review_queue_item_supports_review_lifecycle_status_values() -> None:
    item = ReviewQueueItem(
        item_id="rq_2",
        current_task="Assess cross-department request",
        risk_level="medium",
        department_routing="management_department",
        hard_gate_status=False,
        escalation_reason="cross_department_routing",
        recommendation="PAUSE",
        review_status=ReviewQueueStatus.IN_REVIEW,
    )

    assert item.review_status == ReviewQueueStatus.IN_REVIEW
    assert item.escalation_reason == "cross_department_routing"
    assert item.recommendation == "PAUSE"


def test_review_queue_item_supports_multiple_escalation_reasons() -> None:
    item = ReviewQueueItem(
        item_id="rq_3",
        current_task="Review policy and cross-department scope",
        risk_level="high",
        department_routing="management_department",
        hard_gate_status=True,
        escalation_reason="hard_gate_triggered",
        escalation_reasons=["hard_gate_triggered", "cross_department_routing"],
        recommendation="REVIEW",
    )

    assert item.escalation_reason == "hard_gate_triggered"
    assert item.escalation_reasons == ["hard_gate_triggered", "cross_department_routing"]


def test_review_queue_item_accepts_legacy_escalation_reason_only_payload() -> None:
    legacy_payload = {
        "item_id": "rq_legacy_1",
        "current_task": "Legacy queue item compatibility check",
        "risk_level": "high",
        "department_routing": "management_department",
        "hard_gate_status": True,
        "escalation_reason": "hard_gate_triggered",
        "recommendation": "REVIEW",
    }

    item = ReviewQueueItem.model_validate(legacy_payload)

    assert item.escalation_reason == "hard_gate_triggered"
    assert item.escalation_reasons == []
