from app.schemas.management_decision import ManagementDecisionRecord


def test_management_decision_record_minimum_fields() -> None:
    record = ManagementDecisionRecord(
        item_id="rq_1",
        decision="REVIEW",
        reviewer_id="mgmt-user",
        rationale="Hard gate triggered; escalate for review.",
    )

    assert record.item_id == "rq_1"
    assert record.decision == "REVIEW"
    assert record.reviewer_type == "unknown"
    assert record.constraints == []
    assert record.follow_up_notes == []


def test_management_decision_record_supports_constraints_and_references() -> None:
    record = ManagementDecisionRecord(
        item_id="rq_2",
        decision="GO",
        reviewer_id="manager-1",
        reviewer_type="human",
        rationale="Low-risk docs-only patch is acceptable.",
        constraints=["Do not modify runtime behavior."],
        follow_up_notes=["Run targeted tests before merge."],
        approved_next_action="Implement docs patch and submit verification output.",
        decided_at="2026-03-25T12:30:00Z",
        related_project_id="project_123",
        related_queue_item_id="rq_2",
        related_packet_id="packet_2",
    )

    assert record.decision == "GO"
    assert record.reviewer_type == "human"
    assert record.constraints == ["Do not modify runtime behavior."]
    assert record.follow_up_notes == ["Run targeted tests before merge."]
    assert record.related_packet_id == "packet_2"
