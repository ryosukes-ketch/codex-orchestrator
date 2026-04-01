from uuid import uuid4

from app.schemas.management import (
    BriefSummary,
    CurrentBriefArtifact,
    ManagementReviewPacket,
    ManagementReviewSummary,
)
from app.schemas.trend import TrendWorkflowReport
from app.services.management_review import build_management_review_summary
from app.services.triage import TriageResult
from app.services.work_order import WorkOrderDraft


def build_management_review_packet(
    *,
    current_brief: CurrentBriefArtifact,
    management_summary: ManagementReviewSummary,
    packet_id: str | None = None,
) -> ManagementReviewPacket:
    return ManagementReviewPacket(
        packet_id=packet_id or f"packet-{uuid4().hex[:8]}",
        project_id=management_summary.project_id,
        brief_id=management_summary.brief_id,
        current_task=management_summary.current_task,
        summarized_brief=BriefSummary(
            requested_scope=list(current_brief.requested_scope),
            out_of_scope=list(current_brief.out_of_scope),
            missing_fields=list(current_brief.intake_missing_fields),
            clarifying_questions=list(current_brief.clarifying_questions),
        ),
        risk_level=management_summary.risk_level,
        department_routing_recommendation=management_summary.department_routing,
        hard_gate_status=management_summary.hard_gate_triggered,
        hard_gate_triggers=list(management_summary.hard_gate_triggers),
        escalation_reasons=_build_escalation_reasons(management_summary),
        proposed_next_action=management_summary.proposed_action,
        recommendation=management_summary.decision_outcome,
        required_review=management_summary.required_review,
        work_order_id=management_summary.work_order_id,
        trend_provider=management_summary.trend_provider,
        trend_candidate_count=management_summary.trend_candidate_count,
    )


def build_management_review_packet_from_components(
    *,
    current_brief: CurrentBriefArtifact,
    triage_result: TriageResult | None = None,
    trend_report: TrendWorkflowReport | None = None,
    work_order: WorkOrderDraft | None = None,
    packet_id: str | None = None,
) -> ManagementReviewPacket:
    summary = build_management_review_summary(
        current_brief=current_brief,
        triage_result=triage_result,
        trend_report=trend_report,
        work_order=work_order,
    )
    return build_management_review_packet(
        current_brief=current_brief,
        management_summary=summary,
        packet_id=packet_id,
    )


def _build_escalation_reasons(summary: ManagementReviewSummary) -> list[str]:
    reasons: list[str] = []
    escalation_reason = (summary.escalation_reason or "").strip()
    if escalation_reason and escalation_reason.lower() != "none":
        reasons.append(escalation_reason)
    if summary.hard_gate_triggered and "hard_gate_triggered" not in reasons:
        reasons.append("hard_gate_triggered")
    if summary.required_review and summary.decision_outcome == "REVIEW" and not reasons:
        reasons.append("review_required")
    return reasons
