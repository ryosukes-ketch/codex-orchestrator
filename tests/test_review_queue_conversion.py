from app.intake.review_artifacts import intake_result_to_current_brief_artifact
from app.intake.service import IntakeAgent
from app.schemas.review_queue import ReviewQueueStatus
from app.services.management_review import build_management_review_summary
from app.services.review_packet import build_management_review_packet
from app.services.review_queue import review_packet_to_queue_item
from app.services.triage import TriageContext, triage_task


def test_review_packet_to_queue_item_preserves_governance_fields() -> None:
    packet = _build_packet(changed_areas={"policy"})
    queue_item = review_packet_to_queue_item(packet, item_id="rq_policy")

    assert queue_item.item_id == "rq_policy"
    assert queue_item.current_task == packet.current_task
    assert queue_item.risk_level == "high"
    assert queue_item.department_routing == "management_department"
    assert queue_item.hard_gate_status is True
    assert "policy_model_change" in queue_item.hard_gate_triggers
    assert queue_item.escalation_reason == "hard_gate_triggered"
    assert queue_item.escalation_reasons == ["hard_gate_triggered"]
    assert queue_item.recommendation == "REVIEW"
    assert queue_item.review_status == ReviewQueueStatus.PENDING


def test_review_packet_to_queue_item_supports_custom_status_and_timestamps() -> None:
    packet = _build_packet(changed_areas={"docs"})
    queue_item = review_packet_to_queue_item(
        packet,
        review_status=ReviewQueueStatus.IN_REVIEW,
        created_at="2026-03-25T10:00:00Z",
        updated_at="2026-03-25T11:00:00Z",
        note="Management review started.",
    )

    assert queue_item.recommendation == "GO"
    assert queue_item.review_status == ReviewQueueStatus.IN_REVIEW
    assert queue_item.created_at == "2026-03-25T10:00:00Z"
    assert queue_item.updated_at == "2026-03-25T11:00:00Z"
    assert queue_item.note == "Management review started."
    assert queue_item.related_project_id == packet.project_id


def test_review_packet_to_queue_item_preserves_multiple_escalation_reasons() -> None:
    packet = _build_packet(changed_areas={"policy"})
    packet = packet.model_copy(
        update={"escalation_reasons": ["hard_gate_triggered", "cross_department_routing"]}
    )
    queue_item = review_packet_to_queue_item(packet, item_id="rq_multi_reason")

    assert queue_item.item_id == "rq_multi_reason"
    assert queue_item.escalation_reason == "hard_gate_triggered"
    assert queue_item.escalation_reasons == [
        "hard_gate_triggered",
        "cross_department_routing",
    ]


def _build_packet(*, changed_areas: set[str]):
    agent = IntakeAgent()
    intake_result = agent.build_brief(
        "Title: Queue Bridge\n"
        "Scope: governance docs\n"
        "Constraints: no deps\n"
        "Success Criteria: tests pass\n"
        "Deadline: 2026-06-01"
    )
    current_brief = intake_result_to_current_brief_artifact(
        intake_result,
        brief_id="brief_queue_bridge",
        project_id="project_queue_bridge",
    )
    triage = triage_task(
        TriageContext(
            changed_areas=changed_areas,
            task_in_active_phase=True,
            verification_passed=True,
            ambiguous_scope=False,
        )
    )
    summary = build_management_review_summary(current_brief=current_brief, triage_result=triage)
    return build_management_review_packet(
        current_brief=current_brief,
        management_summary=summary,
        packet_id="packet_queue_bridge",
    )
