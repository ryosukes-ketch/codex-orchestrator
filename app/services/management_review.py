from app.schemas.management import CurrentBriefArtifact, ManagementReviewSummary
from app.schemas.trend import TrendWorkflowReport
from app.services.continuation import ContinuationDecision, ContinuationRisk
from app.services.triage import TriageResult
from app.services.work_order import WorkOrderDraft


def build_management_review_summary(
    *,
    current_brief: CurrentBriefArtifact,
    triage_result: TriageResult | None = None,
    trend_report: TrendWorkflowReport | None = None,
    work_order: WorkOrderDraft | None = None,
) -> ManagementReviewSummary:
    decision = _select_decision(work_order, triage_result)
    risk_level = _select_risk_level(current_brief, triage_result, work_order)
    routing = _select_routing(current_brief, triage_result, work_order)
    hard_gate_triggers = _select_hard_gate_triggers(current_brief, triage_result, work_order)
    hard_gate_triggered = bool(hard_gate_triggers)
    proposed_action = _select_proposed_action(
        current_brief, triage_result, trend_report, work_order
    )
    required_review = _is_review_required(
        current_brief, triage_result, work_order, hard_gate_triggered
    )
    escalation_reason = _select_escalation_reason(triage_result, work_order)

    return ManagementReviewSummary(
        project_id=current_brief.project_id,
        brief_id=current_brief.brief_id,
        current_task=current_brief.current_task,
        decision_outcome=decision.value,
        risk_level=risk_level.value,
        department_routing=routing,
        hard_gate_triggered=hard_gate_triggered,
        hard_gate_triggers=hard_gate_triggers,
        proposed_action=proposed_action,
        required_review=required_review,
        escalation_reason=escalation_reason,
        trend_provider=trend_report.provider if trend_report else None,
        trend_candidate_count=len(trend_report.candidate_trends) if trend_report else 0,
        work_order_id=work_order.work_order_id if work_order else None,
    )


def _select_decision(
    work_order: WorkOrderDraft | None, triage_result: TriageResult | None
) -> ContinuationDecision:
    if work_order:
        return work_order.governance.decision_outcome
    if triage_result:
        return triage_result.decision
    return ContinuationDecision.PAUSE


def _select_risk_level(
    current_brief: CurrentBriefArtifact,
    triage_result: TriageResult | None,
    work_order: WorkOrderDraft | None,
) -> ContinuationRisk:
    if work_order:
        return work_order.governance.risk_level
    if triage_result:
        return triage_result.risk_level
    return ContinuationRisk(current_brief.risk_snapshot.risk_level)


def _select_routing(
    current_brief: CurrentBriefArtifact,
    triage_result: TriageResult | None,
    work_order: WorkOrderDraft | None,
) -> str:
    if work_order:
        return work_order.assigned_department.value
    if triage_result:
        return triage_result.routing_target.value
    return current_brief.department_context.candidate_routing


def _select_hard_gate_triggers(
    current_brief: CurrentBriefArtifact,
    triage_result: TriageResult | None,
    work_order: WorkOrderDraft | None,
) -> list[str]:
    if work_order:
        return sorted(trigger.value for trigger in work_order.governance.hard_gate_triggers)
    if triage_result:
        return sorted(trigger.value for trigger in triage_result.hard_gate_triggers)
    return sorted(current_brief.risk_snapshot.hard_gate_triggers)


def _select_proposed_action(
    current_brief: CurrentBriefArtifact,
    triage_result: TriageResult | None,
    trend_report: TrendWorkflowReport | None,
    work_order: WorkOrderDraft | None,
) -> str:
    if work_order:
        return work_order.next_action_suggestion
    if triage_result:
        if triage_result.decision == ContinuationDecision.REVIEW:
            return "Escalate to Management Department for REVIEW."
        if triage_result.decision == ContinuationDecision.PAUSE:
            return "Pause and isolate blockers before continuing."
    if trend_report:
        return trend_report.next_action_suggestion
    return current_brief.proposed_action.summary


def _is_review_required(
    current_brief: CurrentBriefArtifact,
    triage_result: TriageResult | None,
    work_order: WorkOrderDraft | None,
    hard_gate_triggered: bool,
) -> bool:
    if work_order:
        return work_order.governance.management_review_required
    if triage_result:
        return triage_result.decision == ContinuationDecision.REVIEW or (
            triage_result.escalation_likely_required
        )
    if current_brief.risk_snapshot.hard_gate_triggered or hard_gate_triggered:
        return True
    # Without triage/work-order context, keep summary conservative.
    return True


def _select_escalation_reason(
    triage_result: TriageResult | None, work_order: WorkOrderDraft | None
) -> str | None:
    if work_order:
        return work_order.governance.escalation_reason.value
    if triage_result:
        return triage_result.escalation_reason.value
    return None
