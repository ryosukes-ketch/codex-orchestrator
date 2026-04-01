from app.services.continuation import ContinuationDecision, ContinuationRisk, HardGateTrigger
from app.services.triage import (
    EscalationReason,
    RoutingDepartment,
    TriageContext,
    triage_task,
)


def test_triage_routes_low_risk_work_to_action_department() -> None:
    result = triage_task(
        TriageContext(
            changed_areas={"docs", "tests"},
            task_in_active_phase=True,
            verification_passed=True,
            ambiguous_scope=False,
        )
    )
    assert result.risk_level == ContinuationRisk.LOW
    assert result.routing_target == RoutingDepartment.ACTION
    assert result.decision == ContinuationDecision.GO
    assert result.escalation_reason == EscalationReason.NONE


def test_triage_requests_review_on_hard_gate() -> None:
    result = triage_task(
        TriageContext(
            changed_areas={"auth"},
            task_in_active_phase=True,
            verification_passed=True,
            ambiguous_scope=False,
        )
    )
    assert result.decision == ContinuationDecision.REVIEW
    assert result.risk_level == ContinuationRisk.HIGH
    assert result.routing_target == RoutingDepartment.MANAGEMENT
    assert result.escalation_reason == EscalationReason.HARD_GATE_TRIGGERED
    assert HardGateTrigger.AUTHENTICATION_BEHAVIOR in result.hard_gate_triggers


def test_triage_pauses_when_scope_is_ambiguous() -> None:
    result = triage_task(
        TriageContext(
            changed_areas={"classification"},
            task_in_active_phase=True,
            verification_passed=True,
            ambiguous_scope=True,
        )
    )
    assert result.decision == ContinuationDecision.PAUSE
    assert result.risk_level == ContinuationRisk.MEDIUM
    assert result.routing_target == RoutingDepartment.PROGRESS_CONTROL
    assert result.escalation_reason == EscalationReason.AMBIGUOUS_SCOPE


def test_triage_requests_review_for_phase_mismatch() -> None:
    result = triage_task(
        TriageContext(
            changed_areas={"docs"},
            task_in_active_phase=False,
            verification_passed=True,
            ambiguous_scope=False,
        )
    )
    assert result.decision == ContinuationDecision.REVIEW
    assert result.risk_level == ContinuationRisk.HIGH
    assert result.routing_target == RoutingDepartment.MANAGEMENT
    assert result.escalation_reason == EscalationReason.PHASE_MISMATCH


def test_low_cost_action_signal_cannot_override_hard_gate_review() -> None:
    result = triage_task(
        TriageContext(
            changed_areas={"summary", "classification", "approval"},
            task_in_active_phase=True,
            verification_passed=True,
            ambiguous_scope=False,
        )
    )
    assert result.decision == ContinuationDecision.REVIEW
    assert result.routing_target == RoutingDepartment.MANAGEMENT
    assert result.escalation_reason == EscalationReason.HARD_GATE_TRIGGERED
    assert HardGateTrigger.APPROVAL_FLOW in result.hard_gate_triggers


def test_auth_policy_and_approval_changes_always_require_review() -> None:
    for area in ("auth", "policy", "approval"):
        result = triage_task(
            TriageContext(
                changed_areas={area},
                task_in_active_phase=True,
                verification_passed=True,
                ambiguous_scope=False,
            )
        )
        assert result.decision == ContinuationDecision.REVIEW
        assert result.escalation_likely_required is True
        assert result.escalation_reason == EscalationReason.HARD_GATE_TRIGGERED


def test_latest_alias_style_suggestion_does_not_bypass_provider_contract_gate() -> None:
    result = triage_task(
        TriageContext(
            changed_areas={"classification", "provider_contract"},
            task_in_active_phase=True,
            verification_passed=True,
            ambiguous_scope=False,
        )
    )
    assert result.decision == ContinuationDecision.REVIEW
    assert result.risk_level == ContinuationRisk.HIGH
    assert HardGateTrigger.PROVIDER_CONTRACT in result.hard_gate_triggers


def test_medium_risk_ambiguous_work_does_not_auto_continue() -> None:
    result = triage_task(
        TriageContext(
            changed_areas={"internal_refactor"},
            task_in_active_phase=True,
            verification_passed=True,
            ambiguous_scope=True,
        )
    )
    assert result.decision == ContinuationDecision.PAUSE
    assert result.risk_level == ContinuationRisk.MEDIUM
    assert result.routing_target == RoutingDepartment.PROGRESS_CONTROL
    assert result.escalation_reason == EscalationReason.AMBIGUOUS_SCOPE


def test_cross_department_always_routes_to_management_review() -> None:
    result = triage_task(
        TriageContext(
            changed_areas={"docs", "cross_department"},
            task_in_active_phase=True,
            verification_passed=True,
            ambiguous_scope=False,
        )
    )
    assert result.decision == ContinuationDecision.REVIEW
    assert result.routing_target == RoutingDepartment.MANAGEMENT
    assert result.escalation_reason == EscalationReason.CROSS_DEPARTMENT


def test_triage_pauses_when_verification_is_unstable() -> None:
    result = triage_task(
        TriageContext(
            changed_areas={"internal_refactor"},
            task_in_active_phase=True,
            verification_passed=False,
            ambiguous_scope=False,
        )
    )

    assert result.decision == ContinuationDecision.PAUSE
    assert result.risk_level == ContinuationRisk.MEDIUM
    assert result.routing_target == RoutingDepartment.PROGRESS_CONTROL
    assert result.escalation_reason == EscalationReason.VERIFICATION_UNSTABLE
    assert result.escalation_likely_required is False
    assert result.hard_gate_triggers == set()


def test_triage_routes_non_low_risk_go_to_implementation() -> None:
    result = triage_task(
        TriageContext(
            changed_areas={"internal_refactor"},
            task_in_active_phase=True,
            verification_passed=True,
            ambiguous_scope=False,
        )
    )

    assert result.decision == ContinuationDecision.GO
    assert result.risk_level == ContinuationRisk.MEDIUM
    assert result.routing_target == RoutingDepartment.IMPLEMENTATION
    assert result.escalation_reason == EscalationReason.NONE
    assert result.escalation_likely_required is False
    assert result.hard_gate_triggers == set()


def test_triage_cross_department_priority_over_hard_gate_reason() -> None:
    result = triage_task(
        TriageContext(
            changed_areas={"cross_department", "approval"},
            task_in_active_phase=True,
            verification_passed=True,
            ambiguous_scope=False,
        )
    )

    assert result.decision == ContinuationDecision.REVIEW
    assert result.routing_target == RoutingDepartment.MANAGEMENT
    assert result.escalation_reason == EscalationReason.CROSS_DEPARTMENT
    assert HardGateTrigger.APPROVAL_FLOW in result.hard_gate_triggers


def test_triage_normalizes_changed_areas_for_cross_department_and_hard_gate_detection() -> None:
    result = triage_task(
        TriageContext(
            changed_areas={"  CROSS_DEPARTMENT  ", "  APPROVAL  "},
            task_in_active_phase=True,
            verification_passed=True,
            ambiguous_scope=False,
        )
    )

    assert result.decision == ContinuationDecision.REVIEW
    assert result.routing_target == RoutingDepartment.MANAGEMENT
    assert result.escalation_reason == EscalationReason.CROSS_DEPARTMENT
    assert HardGateTrigger.APPROVAL_FLOW in result.hard_gate_triggers


def test_triage_normalizes_low_risk_area_tokens_before_routing() -> None:
    result = triage_task(
        TriageContext(
            changed_areas={"  DOCS  ", " Tests "},
            task_in_active_phase=True,
            verification_passed=True,
            ambiguous_scope=False,
        )
    )

    assert result.decision == ContinuationDecision.GO
    assert result.routing_target == RoutingDepartment.ACTION
    assert result.risk_level == ContinuationRisk.LOW
