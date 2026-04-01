import pytest

from app.intake.review_artifacts import intake_result_to_current_brief_artifact
from app.intake.service import IntakeAgent
from app.services.management_review import build_management_review_summary
from app.services.review_packet import build_management_review_packet
from app.services.review_queue import review_packet_to_queue_item
from app.services.triage import TriageContext, triage_task
from app.services.work_order import build_work_order_draft


@pytest.mark.parametrize(
    ("changed_areas", "verification_passed", "expected_recommendation"),
    [
        ({"docs"}, True, "GO"),
        ({"implementation"}, False, "PAUSE"),
        ({"policy"}, True, "REVIEW"),
    ],
)
def test_review_packet_to_queue_item_preserves_go_pause_review_parity(
    changed_areas: set[str],
    verification_passed: bool,
    expected_recommendation: str,
) -> None:
    packet = _build_packet(
        changed_areas=changed_areas,
        verification_passed=verification_passed,
    )

    queue_item = review_packet_to_queue_item(
        packet,
        item_id=f"rq_parity_{expected_recommendation.lower()}",
    )

    assert queue_item.item_id == f"rq_parity_{expected_recommendation.lower()}"
    assert queue_item.recommendation == expected_recommendation
    assert queue_item.current_task == packet.current_task
    assert queue_item.risk_level == packet.risk_level
    assert queue_item.department_routing == packet.department_routing_recommendation
    assert queue_item.hard_gate_status == packet.hard_gate_status
    assert queue_item.hard_gate_triggers == packet.hard_gate_triggers


def test_review_packet_to_queue_item_preserves_related_metadata_and_defaults() -> None:
    packet = _build_packet(changed_areas={"docs"}, verification_passed=True, with_work_order=True)

    queue_item = review_packet_to_queue_item(packet, item_id="rq_metadata_1")

    assert queue_item.item_id == "rq_metadata_1"
    assert queue_item.related_project_id == packet.project_id
    assert queue_item.related_brief_id == packet.brief_id
    assert queue_item.related_work_order_id == packet.work_order_id
    assert queue_item.created_at is None
    assert queue_item.updated_at is None
    assert queue_item.note == ""


def test_review_packet_to_queue_item_with_empty_escalation_reasons_sets_none() -> None:
    packet = _build_packet(changed_areas={"docs"}, verification_passed=True)
    packet = packet.model_copy(update={"escalation_reasons": []})

    queue_item = review_packet_to_queue_item(packet, item_id="rq_no_escalation_1")

    assert queue_item.item_id == "rq_no_escalation_1"
    assert queue_item.escalation_reasons == []
    assert queue_item.escalation_reason is None


def test_review_packet_to_queue_item_normalizes_empty_and_duplicate_reasons_and_triggers() -> None:
    packet = _build_packet(changed_areas={"docs"}, verification_passed=True)
    packet = packet.model_copy(
        update={
            "hard_gate_triggers": [
                "",
                " approval_flow_change ",
                "approval_flow_change",
                "   ",
            ],
            "escalation_reasons": [
                "",
                " hard_gate_triggered ",
                "hard_gate_triggered",
                " ",
            ],
        }
    )

    queue_item = review_packet_to_queue_item(packet, item_id="rq_normalize_1")

    assert queue_item.item_id == "rq_normalize_1"
    assert queue_item.hard_gate_triggers == ["approval_flow_change"]
    assert queue_item.escalation_reasons == ["hard_gate_triggered"]
    assert queue_item.escalation_reason == "hard_gate_triggered"


def _build_packet(
    *,
    changed_areas: set[str],
    verification_passed: bool = True,
    with_work_order: bool = False,
):
    agent = IntakeAgent()
    intake_result = agent.build_brief(
        "Title: Queue Contract\n"
        "Scope: review queue projection\n"
        "Constraints: no runtime changes\n"
        "Success Criteria: tests pass\n"
        "Deadline: 2026-06-01"
    )
    current_brief = intake_result_to_current_brief_artifact(
        intake_result,
        brief_id="brief_queue_contract",
        project_id="project_queue_contract",
    )
    triage = triage_task(
        TriageContext(
            changed_areas=changed_areas,
            task_in_active_phase=True,
            verification_passed=verification_passed,
            ambiguous_scope=False,
        )
    )
    work_order = None
    if with_work_order:
        work_order = build_work_order_draft(
            triage,
            work_order_id="wo_queue_contract_1",
            project_id=current_brief.project_id,
            objective=current_brief.current_task,
        )
    summary = build_management_review_summary(
        current_brief=current_brief,
        triage_result=triage,
        work_order=work_order,
    )
    return build_management_review_packet(
        current_brief=current_brief,
        management_summary=summary,
        packet_id="packet_queue_contract_1",
    )
