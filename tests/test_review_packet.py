from app.intake.review_artifacts import intake_result_to_current_brief_artifact
from app.intake.service import IntakeAgent
from app.services.management_review import build_management_review_summary
from app.services.review_packet import (
    build_management_review_packet,
    build_management_review_packet_from_components,
)
from app.services.triage import TriageContext, triage_task
from app.services.work_order import build_work_order_draft


def test_build_management_review_packet_from_summary_review_case() -> None:
    current_brief = _build_brief_artifact("Harden policy checks")
    triage = triage_task(
        TriageContext(
            changed_areas={"policy"},
            task_in_active_phase=True,
            verification_passed=True,
            ambiguous_scope=False,
        )
    )
    summary = build_management_review_summary(
        current_brief=current_brief,
        triage_result=triage,
    )

    packet = build_management_review_packet(
        current_brief=current_brief,
        management_summary=summary,
        packet_id="packet_review",
    )

    assert packet.packet_id == "packet_review"
    assert packet.current_task == summary.current_task
    assert packet.recommendation == "REVIEW"
    assert packet.risk_level == "high"
    assert packet.department_routing_recommendation == "management_department"
    assert packet.hard_gate_status is True
    assert "policy_model_change" in packet.hard_gate_triggers
    assert "hard_gate_triggered" in packet.escalation_reasons
    assert packet.required_review is True


def test_build_management_review_packet_from_components_go_case() -> None:
    current_brief = _build_brief_artifact(
        "Title: Docs task\n"
        "Scope: docs only\n"
        "Constraints: none\n"
        "Success Criteria: docs updated\n"
        "Deadline: 2026-06-01"
    )
    triage = triage_task(
        TriageContext(
            changed_areas={"docs"},
            task_in_active_phase=True,
            verification_passed=True,
            ambiguous_scope=False,
        )
    )
    work_order = build_work_order_draft(
        triage,
        work_order_id="wo_packet_go",
        project_id=current_brief.project_id,
        objective=current_brief.current_task,
    )

    packet = build_management_review_packet_from_components(
        current_brief=current_brief,
        triage_result=triage,
        work_order=work_order,
        packet_id="packet_go",
    )

    assert packet.packet_id == "packet_go"
    assert packet.recommendation == "GO"
    assert packet.required_review is False
    assert packet.department_routing_recommendation == "action_department"
    assert packet.work_order_id == "wo_packet_go"
    assert packet.summarized_brief.requested_scope
    assert packet.proposed_next_action == work_order.next_action_suggestion


def test_build_management_review_packet_from_components_matches_direct_composition() -> None:
    current_brief = _build_brief_artifact("Validate packet composition parity.")
    triage = triage_task(
        TriageContext(
            changed_areas={"policy"},
            task_in_active_phase=True,
            verification_passed=True,
            ambiguous_scope=False,
        )
    )

    expected_summary = build_management_review_summary(
        current_brief=current_brief,
        triage_result=triage,
    )
    expected_packet = build_management_review_packet(
        current_brief=current_brief,
        management_summary=expected_summary,
        packet_id="packet_equivalence",
    )

    packet = build_management_review_packet_from_components(
        current_brief=current_brief,
        triage_result=triage,
        packet_id="packet_equivalence",
    )

    assert packet.model_dump() == expected_packet.model_dump()


def test_build_management_review_packet_preserves_brief_and_summary_metadata() -> None:
    current_brief = _build_brief_artifact("Preserve packet metadata and brief details.")
    current_brief = current_brief.model_copy(
        update={
            "requested_scope": ["scope_a", "scope_b"],
            "out_of_scope": ["out_x"],
            "intake_missing_fields": ["deadline"],
            "clarifying_questions": ["Who approves the release?"],
        }
    )
    triage = triage_task(
        TriageContext(
            changed_areas={"docs"},
            task_in_active_phase=True,
            verification_passed=True,
            ambiguous_scope=False,
        )
    )
    work_order = build_work_order_draft(
        triage,
        work_order_id="wo_packet_metadata",
        project_id=current_brief.project_id,
        objective=current_brief.current_task,
    )

    summary = build_management_review_summary(
        current_brief=current_brief,
        triage_result=triage,
        work_order=work_order,
    )

    packet = build_management_review_packet(
        current_brief=current_brief,
        management_summary=summary,
        packet_id="packet_metadata",
    )

    assert packet.packet_id == "packet_metadata"
    assert packet.project_id == summary.project_id
    assert packet.brief_id == summary.brief_id
    assert packet.current_task == summary.current_task
    assert packet.risk_level == summary.risk_level
    assert packet.department_routing_recommendation == summary.department_routing
    assert packet.hard_gate_status == summary.hard_gate_triggered
    assert packet.hard_gate_triggers == summary.hard_gate_triggers
    assert packet.proposed_next_action == summary.proposed_action
    assert packet.recommendation == summary.decision_outcome
    assert packet.required_review == summary.required_review
    assert packet.work_order_id == summary.work_order_id
    assert packet.trend_provider == summary.trend_provider
    assert packet.trend_candidate_count == summary.trend_candidate_count
    assert packet.summarized_brief.requested_scope == current_brief.requested_scope
    assert packet.summarized_brief.out_of_scope == current_brief.out_of_scope
    assert packet.summarized_brief.missing_fields == current_brief.intake_missing_fields
    assert packet.summarized_brief.clarifying_questions == current_brief.clarifying_questions


def test_build_management_review_packet_adds_review_required_reason_when_needed() -> None:
    current_brief = _build_brief_artifact("Freeze review-required escalation fallback.")
    summary = build_management_review_summary(current_brief=current_brief)
    summary = summary.model_copy(
        update={
            "decision_outcome": "REVIEW",
            "required_review": True,
            "hard_gate_triggered": False,
            "hard_gate_triggers": [],
            "escalation_reason": "none",
        }
    )

    packet = build_management_review_packet(
        current_brief=current_brief,
        management_summary=summary,
        packet_id="packet_review_required_fallback",
    )

    assert packet.escalation_reasons == ["review_required"]


def test_build_management_review_packet_normalizes_escalation_reason_whitespace() -> None:
    current_brief = _build_brief_artifact("Normalize escalation reason whitespace.")
    summary = build_management_review_summary(current_brief=current_brief)
    summary = summary.model_copy(
        update={
            "decision_outcome": "REVIEW",
            "required_review": True,
            "hard_gate_triggered": False,
            "hard_gate_triggers": [],
            "escalation_reason": " cross_department_routing ",
        }
    )

    packet = build_management_review_packet(
        current_brief=current_brief,
        management_summary=summary,
        packet_id="packet_escalation_whitespace",
    )

    assert packet.escalation_reasons == ["cross_department_routing"]


def _build_brief_artifact(user_request: str):
    agent = IntakeAgent()
    intake_result = agent.build_brief(user_request)
    return intake_result_to_current_brief_artifact(
        intake_result,
        brief_id="brief_packet",
        project_id="project_packet",
    )
