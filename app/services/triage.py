from dataclasses import dataclass, field
from enum import Enum

from app.services.continuation import (
    ContinuationContext,
    ContinuationDecision,
    ContinuationRisk,
    HardGateTrigger,
    assess_continuation,
    detect_hard_gate_triggers,
)


class RoutingDepartment(str, Enum):
    MANAGEMENT = "management_department"
    PROGRESS_CONTROL = "progress_control_department"
    ACTION = "action_department"
    IMPLEMENTATION = "implementation_department"
    AUDIT_REVIEW = "audit_review_department"


class EscalationReason(str, Enum):
    NONE = "none"
    HARD_GATE_TRIGGERED = "hard_gate_triggered"
    PHASE_MISMATCH = "phase_mismatch"
    VERIFICATION_UNSTABLE = "verification_unstable"
    AMBIGUOUS_SCOPE = "ambiguous_scope"
    CROSS_DEPARTMENT = "cross_department_routing"


LOW_RISK_AREAS = {"docs", "formatting", "tests", "summary", "classification", "extraction"}


@dataclass(frozen=True)
class TriageContext:
    changed_areas: set[str] = field(default_factory=set)
    task_in_active_phase: bool = True
    verification_passed: bool = True
    ambiguous_scope: bool = False


@dataclass(frozen=True)
class TriageResult:
    risk_level: ContinuationRisk
    routing_target: RoutingDepartment
    escalation_reason: EscalationReason
    escalation_likely_required: bool
    decision: ContinuationDecision
    hard_gate_triggers: set[HardGateTrigger] = field(default_factory=set)


def triage_task(context: TriageContext) -> TriageResult:
    normalized_areas = {
        area.strip().lower()
        for area in context.changed_areas
        if isinstance(area, str) and area.strip()
    }
    hard_gates = detect_hard_gate_triggers(normalized_areas)
    continuation = assess_continuation(
        ContinuationContext(
            task_in_active_phase=context.task_in_active_phase,
            next_step_clear=not context.ambiguous_scope,
            verification_passed=context.verification_passed,
            hard_gate_triggers=hard_gates,
        )
    )

    if "cross_department" in normalized_areas:
        return TriageResult(
            risk_level=ContinuationRisk.HIGH,
            routing_target=RoutingDepartment.MANAGEMENT,
            escalation_reason=EscalationReason.CROSS_DEPARTMENT,
            escalation_likely_required=True,
            decision=ContinuationDecision.REVIEW,
            hard_gate_triggers=hard_gates,
        )

    if hard_gates:
        return TriageResult(
            risk_level=ContinuationRisk.HIGH,
            routing_target=RoutingDepartment.MANAGEMENT,
            escalation_reason=EscalationReason.HARD_GATE_TRIGGERED,
            escalation_likely_required=True,
            decision=ContinuationDecision.REVIEW,
            hard_gate_triggers=hard_gates,
        )

    if not context.task_in_active_phase:
        return TriageResult(
            risk_level=ContinuationRisk.HIGH,
            routing_target=RoutingDepartment.MANAGEMENT,
            escalation_reason=EscalationReason.PHASE_MISMATCH,
            escalation_likely_required=True,
            decision=ContinuationDecision.REVIEW,
            hard_gate_triggers=hard_gates,
        )

    if not context.verification_passed:
        return TriageResult(
            risk_level=ContinuationRisk.MEDIUM,
            routing_target=RoutingDepartment.PROGRESS_CONTROL,
            escalation_reason=EscalationReason.VERIFICATION_UNSTABLE,
            escalation_likely_required=False,
            decision=ContinuationDecision.PAUSE,
            hard_gate_triggers=hard_gates,
        )

    if context.ambiguous_scope:
        return TriageResult(
            risk_level=ContinuationRisk.MEDIUM,
            routing_target=RoutingDepartment.PROGRESS_CONTROL,
            escalation_reason=EscalationReason.AMBIGUOUS_SCOPE,
            escalation_likely_required=False,
            decision=ContinuationDecision.PAUSE,
            hard_gate_triggers=hard_gates,
        )

    if normalized_areas and normalized_areas.issubset(LOW_RISK_AREAS):
        return TriageResult(
            risk_level=ContinuationRisk.LOW,
            routing_target=RoutingDepartment.ACTION,
            escalation_reason=EscalationReason.NONE,
            escalation_likely_required=False,
            decision=ContinuationDecision.GO,
            hard_gate_triggers=hard_gates,
        )

    if continuation.decision == ContinuationDecision.GO:
        return TriageResult(
            risk_level=ContinuationRisk.MEDIUM,
            routing_target=RoutingDepartment.IMPLEMENTATION,
            escalation_reason=EscalationReason.NONE,
            escalation_likely_required=False,
            decision=ContinuationDecision.GO,
            hard_gate_triggers=hard_gates,
        )

    # defensive fallback for future context expansion
    return TriageResult(
        risk_level=ContinuationRisk.MEDIUM,
        routing_target=RoutingDepartment.PROGRESS_CONTROL,
        escalation_reason=EscalationReason.AMBIGUOUS_SCOPE,
        escalation_likely_required=False,
        decision=ContinuationDecision.PAUSE,
        hard_gate_triggers=hard_gates,
    )
