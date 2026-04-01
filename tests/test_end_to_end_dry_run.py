from app.schemas.management_decision import ManagementDecisionRecord
from app.services.activation_decision import derive_dry_run_activation_decision
from app.services.approval_record_builder import build_action_department_activation_approval_record
from app.services.continuation import ContinuationDecision
from app.services.dry_run_orchestration import (
    DryRunOrchestrationRequest,
    run_dry_run_orchestration,
)
from app.services.review_packet import build_management_review_packet
from app.services.review_queue import review_packet_to_queue_item
from app.services.triage import RoutingDepartment


def _request_text(title: str, scope: str) -> str:
    return (
        f"Title: {title}\n"
        f"Scope: {scope}\n"
        "Constraints: python, fastapi\n"
        "Success Criteria: deterministic tests, preserved contracts\n"
        "Deadline: 2026-06-01"
    )


def _management_decision(
    *,
    item_id: str,
    decision: str,
    project_id: str,
    packet_id: str,
    reviewer_id: str,
    rationale: str,
    approved_next_action: str,
) -> ManagementDecisionRecord:
    return ManagementDecisionRecord(
        item_id=item_id,
        decision=decision,
        reviewer_id=reviewer_id,
        reviewer_type="human",
        rationale=rationale,
        approved_next_action=approved_next_action,
        related_project_id=project_id,
        related_queue_item_id=item_id,
        related_packet_id=packet_id,
    )


def test_e2e_safe_docs_only_go_journey() -> None:
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=_request_text("Docs GO", "docs-only wording update"),
            changed_areas={"docs"},
            project_id="project_e2e_go",
            brief_id="brief_e2e_go",
            work_order_id="wo_e2e_go",
        )
    )

    packet = build_management_review_packet(
        current_brief=result.current_brief,
        management_summary=result.management_summary,
        packet_id="packet_e2e_go",
    )
    queue_item = review_packet_to_queue_item(packet, item_id="rq_e2e_go")
    decision = _management_decision(
        item_id=queue_item.item_id,
        decision="GO",
        project_id=result.current_brief.project_id,
        packet_id=packet.packet_id,
        reviewer_id="manager_go",
        rationale="Safe docs-only path.",
        approved_next_action="Proceed with docs-only update.",
    )
    projected = derive_dry_run_activation_decision(
        management_review_packet=packet,
        review_queue_item=queue_item,
        management_decision=decision,
    )
    approval_record = build_action_department_activation_approval_record(
        projected_activation_decision=projected,
        activation_review_item_id=queue_item.item_id,
        reviewer_id=decision.reviewer_id,
        reviewer_type=decision.reviewer_type,
        rationale=decision.rationale,
        related_project_id=result.current_brief.project_id,
        related_packet_id=packet.packet_id,
        related_queue_item_id=queue_item.item_id,
    )

    assert result.triage_result.decision == ContinuationDecision.GO
    assert result.triage_result.routing_target == RoutingDepartment.ACTION
    assert queue_item.recommendation == "GO"
    assert projected.recommendation == "GO"
    assert projected.remaining_blockers == []
    assert approval_record["recommendation"] == "GO"
    assert approval_record["human_approval_status"]["status"] == "approved"


def test_e2e_verification_unstable_pause_journey() -> None:
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=_request_text("Pause path", "verification recovery"),
            changed_areas={"docs"},
            verification_passed=False,
            project_id="project_e2e_pause",
            brief_id="brief_e2e_pause",
            work_order_id="wo_e2e_pause",
        )
    )

    packet = build_management_review_packet(
        current_brief=result.current_brief,
        management_summary=result.management_summary,
        packet_id="packet_e2e_pause",
    )
    queue_item = review_packet_to_queue_item(packet, item_id="rq_e2e_pause")
    decision = _management_decision(
        item_id=queue_item.item_id,
        decision="PAUSE",
        project_id=result.current_brief.project_id,
        packet_id=packet.packet_id,
        reviewer_id="manager_pause",
        rationale="Verification is unstable.",
        approved_next_action="Pause and isolate verification blockers.",
    )
    projected = derive_dry_run_activation_decision(
        management_review_packet=packet,
        review_queue_item=queue_item,
        management_decision=decision,
    )
    approval_record = build_action_department_activation_approval_record(
        projected_activation_decision=projected,
        activation_review_item_id=queue_item.item_id,
        reviewer_id=decision.reviewer_id,
        reviewer_type=decision.reviewer_type,
        rationale=decision.rationale,
    )

    assert result.triage_result.decision == ContinuationDecision.PAUSE
    assert result.triage_result.routing_target == RoutingDepartment.PROGRESS_CONTROL
    assert "verification_unstable" in projected.remaining_blockers
    assert projected.recommendation == "PAUSE"
    assert projected.re_review_required is True
    assert approval_record["recommendation"] == "PAUSE"
    assert approval_record["human_approval_status"]["status"] == "pending"


def test_e2e_approval_sensitive_review_journey() -> None:
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=_request_text("Approval review", "approval-flow hardening"),
            changed_areas={"approval"},
            include_trend=True,
            trend_provider_hint="gemini-flash-latest",
            project_id="project_e2e_review",
            brief_id="brief_e2e_review",
            work_order_id="wo_e2e_review",
        )
    )

    packet = build_management_review_packet(
        current_brief=result.current_brief,
        management_summary=result.management_summary,
        packet_id="packet_e2e_review",
    )
    queue_item = review_packet_to_queue_item(packet, item_id="rq_e2e_review")
    decision = _management_decision(
        item_id=queue_item.item_id,
        decision="REVIEW",
        project_id=result.current_brief.project_id,
        packet_id=packet.packet_id,
        reviewer_id="manager_review",
        rationale="Approval semantics are governance-sensitive.",
        approved_next_action="Escalate to audit and review.",
    )
    projected = derive_dry_run_activation_decision(
        management_review_packet=packet,
        review_queue_item=queue_item,
        management_decision=decision,
    )
    approval_record = build_action_department_activation_approval_record(
        projected_activation_decision=projected,
        activation_review_item_id=queue_item.item_id,
        reviewer_id=decision.reviewer_id,
        reviewer_type=decision.reviewer_type,
        rationale=decision.rationale,
    )

    assert result.trend_report is not None
    assert result.triage_result.decision == ContinuationDecision.REVIEW
    assert result.management_summary.required_review is True
    assert "approval_flow_change" in result.management_summary.hard_gate_triggers
    assert projected.recommendation == "REVIEW"
    assert projected.escalation_destination == "Audit and Review Department"
    assert approval_record["recommendation"] == "REVIEW"
    assert approval_record["human_approval_status"]["status"] == "withheld"


def test_e2e_go_input_downgraded_to_pause_when_blockers_remain() -> None:
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=_request_text("Downgrade blockers", "approval-flow patch"),
            changed_areas={"approval"},
            project_id="project_e2e_blocker_downgrade",
            brief_id="brief_e2e_blocker_downgrade",
            work_order_id="wo_e2e_blocker_downgrade",
        )
    )

    packet = build_management_review_packet(
        current_brief=result.current_brief,
        management_summary=result.management_summary,
        packet_id="packet_e2e_blocker_downgrade",
    )
    queue_item = review_packet_to_queue_item(packet, item_id="rq_e2e_blocker_downgrade")
    decision = _management_decision(
        item_id=queue_item.item_id,
        decision="GO",
        project_id=result.current_brief.project_id,
        packet_id=packet.packet_id,
        reviewer_id="manager_go_override",
        rationale="Attempt GO despite blockers.",
        approved_next_action="Proceed immediately.",
    )
    projected = derive_dry_run_activation_decision(
        management_review_packet=packet,
        review_queue_item=queue_item,
        management_decision=decision,
    )

    assert projected.remaining_blockers != []
    assert projected.recommendation == "PAUSE"
    assert projected.escalation_destination is None
    assert projected.re_review_required is True


def test_e2e_go_input_downgraded_to_pause_when_review_required_without_blockers() -> None:
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=_request_text("Required-review downgrade", "docs-only safe change"),
            changed_areas={"docs"},
            project_id="project_e2e_required_review",
            brief_id="brief_e2e_required_review",
            work_order_id="wo_e2e_required_review",
        )
    )

    base_packet = build_management_review_packet(
        current_brief=result.current_brief,
        management_summary=result.management_summary,
        packet_id="packet_e2e_required_review",
    )
    packet = base_packet.model_copy(
        update={
            "required_review": True,
            "hard_gate_status": False,
            "hard_gate_triggers": [],
            "escalation_reasons": [],
        }
    )
    queue_item = review_packet_to_queue_item(packet, item_id="rq_e2e_required_review")
    decision = _management_decision(
        item_id=queue_item.item_id,
        decision="GO",
        project_id=result.current_brief.project_id,
        packet_id=packet.packet_id,
        reviewer_id="manager_required_review",
        rationale="GO with additional review gate.",
        approved_next_action="Proceed after additional review.",
    )
    projected = derive_dry_run_activation_decision(
        management_review_packet=packet,
        review_queue_item=queue_item,
        management_decision=decision,
    )

    assert projected.remaining_blockers == []
    assert projected.recommendation == "PAUSE"
    assert projected.re_review_required is True


def test_e2e_trend_included_journey_with_work_order_disabled() -> None:
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=_request_text("Trend no work-order", "docs-only with trend signal"),
            changed_areas={"docs"},
            include_trend=True,
            trend_provider_hint="gemini-flash-lite-latest",
            generate_work_order=False,
            project_id="project_e2e_trend_only",
            brief_id="brief_e2e_trend_only",
        )
    )

    packet = build_management_review_packet(
        current_brief=result.current_brief,
        management_summary=result.management_summary,
        packet_id="packet_e2e_trend_only",
    )
    queue_item = review_packet_to_queue_item(packet, item_id="rq_e2e_trend_only")
    decision = _management_decision(
        item_id=queue_item.item_id,
        decision=packet.recommendation,
        project_id=result.current_brief.project_id,
        packet_id=packet.packet_id,
        reviewer_id="manager_trend_only",
        rationale="Trend-informed docs-only flow.",
        approved_next_action="Continue with trend-informed docs refinement.",
    )
    projected = derive_dry_run_activation_decision(
        management_review_packet=packet,
        review_queue_item=queue_item,
        management_decision=decision,
    )

    assert result.trend_report is not None
    assert result.work_order is None
    assert packet.work_order_id is None
    assert queue_item.related_work_order_id is None
    assert packet.trend_provider == result.trend_report.provider
    assert packet.trend_candidate_count == len(result.trend_report.candidate_trends)
    assert projected.recommendation == "GO"
