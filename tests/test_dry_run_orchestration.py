import json
from dataclasses import replace
from pathlib import Path
from typing import Literal

import pytest

from app.schemas.management_decision import ManagementDecisionRecord
from app.services.activation_decision import derive_dry_run_activation_decision
from app.services.approval_record_builder import (
    build_action_department_activation_approval_record,
)
from app.services.continuation import ContinuationDecision
from app.services.dry_run_orchestration import (
    SIMULATION_NOTICE,
    DryRunOrchestrationRequest,
    _normalize_activation_projection_inputs,
    build_approval_record_builder_kwargs_from_projection,
    build_approval_record_from_projection_context,
    build_consumer_action_requirement_from_posture,
    build_consumer_assignment_lane_from_operator_requirement,
    build_consumer_decision_posture_from_surface,
    build_consumer_decision_surface_from_followup_requirement,
    build_consumer_dispatch_authority_from_readiness,
    build_consumer_dispatch_clearance_from_permission,
    build_consumer_dispatch_permission_from_authority,
    build_consumer_dispatch_readiness_from_execution_readiness,
    build_consumer_execution_readiness_from_scheduling_commitment,
    build_consumer_operator_requirement_from_processing_plan,
    build_consumer_processing_plan_from_work_queue_assignment,
    build_consumer_receiver_action_label_from_directive,
    build_consumer_receiver_attention_level_from_intervention_requirement,
    build_consumer_receiver_delivery_manifest_from_packet,
    build_consumer_receiver_delivery_packet_from_payload,
    build_consumer_receiver_delivery_payload_from_outcome,
    build_consumer_receiver_dispatch_intent_from_action_label,
    build_consumer_receiver_dispatch_mode_from_intent,
    build_consumer_receiver_followup_requirement_from_response_route,
    build_consumer_receiver_handling_directive_from_classification,
    build_consumer_receiver_intake_from_payload,
    build_consumer_receiver_intervention_requirement_from_progress_outcome,
    build_consumer_receiver_notification_requirement_from_attention_level,
    build_consumer_receiver_progress_outcome_from_signal,
    build_consumer_receiver_progress_signal_from_state,
    build_consumer_receiver_progress_state_from_release_gate,
    build_consumer_receiver_readiness_assessment_from_view,
    build_consumer_receiver_readiness_classification_from_manifest,
    build_consumer_receiver_readiness_outcome_from_signal,
    build_consumer_receiver_readiness_signal_from_assessment,
    build_consumer_receiver_readiness_view_from_intake,
    build_consumer_receiver_release_gate_from_dispatch_mode,
    build_consumer_receiver_response_channel_from_priority,
    build_consumer_receiver_response_priority_from_notification_requirement,
    build_consumer_receiver_response_route_from_channel,
    build_consumer_release_action_plan_from_handling_intent,
    build_consumer_release_authority_from_readiness,
    build_consumer_release_clearance_from_permission,
    build_consumer_release_decision_from_dispatch_clearance,
    build_consumer_release_execution_lane_from_execution_requirement,
    build_consumer_release_execution_requirement_from_release_mode,
    build_consumer_release_handling_intent_from_execution_lane,
    build_consumer_release_mode_from_release_decision,
    build_consumer_release_permission_from_authority,
    build_consumer_release_priority_from_queue,
    build_consumer_release_queue_from_action_plan,
    build_consumer_release_readiness_from_schedule,
    build_consumer_release_schedule_from_window,
    build_consumer_release_window_from_priority,
    build_consumer_response_window_from_sla_class,
    build_consumer_scheduling_commitment_from_timing_posture,
    build_consumer_service_tier_from_assignment_lane,
    build_consumer_sla_class_from_service_tier,
    build_consumer_timing_posture_from_response_window,
    build_consumer_work_queue_assignment_from_action_requirement,
    build_downstream_consumer_payload_from_outcome,
    build_downstream_execution_intent_from_work_item,
    build_downstream_work_item_from_intake,
    build_dry_run_artifact_bundle,
    build_dry_run_handoff_envelope,
    build_dry_run_handoff_envelope_from_result,
    build_execution_readiness_assessment_from_view,
    build_execution_readiness_outcome_from_signal,
    build_execution_readiness_signal_from_assessment,
    build_execution_readiness_view_from_intent,
    build_next_layer_intake_from_handoff_envelope,
    build_projected_activation_decision,
    build_projected_artifact_pair_from_context,
    intake_result_to_trend_request,
    project_dry_run_decision,
    run_dry_run_orchestration,
)

_ROOT = Path(__file__).resolve().parents[1]

# General Constants
RequestKwargs = dict[str, object]
RecommendationValue = Literal["GO", "PAUSE", "REVIEW"]
ApprovalStatusValue = Literal["approved", "pending", "withheld"]
ParityReviewerSource = Literal["top", "management_review_status"]
AUDIT_AND_REVIEW_DEPARTMENT = "Audit and Review Department"
AUTONOMOUS_NOT_APPROVED = "not_approved"
FALLBACK_REVIEWER_ID = "dry-run-system"
FALLBACK_REVIEWER_TYPE = "system"
APPROVER_ID_KEY = "approver_id"
APPROVER_TYPE_KEY = "approver_type"
STATUS_KEY = "status"

# Mapping Case Constants
# Fallback Status Mapping Cases
FALLBACK_STATUS_CASES = [
    pytest.param(
        {
            "user_request": "Low-risk docs-only change for fallback GO path.",
            "changed_areas": {"docs"},
        },
        "GO",
        "approved",
        None,
        False,
        None,
        id="fallback-go",
    ),
    pytest.param(
        {
            "user_request": "Pause required until verification stabilizes.",
            "changed_areas": {"docs"},
            "verification_passed": False,
        },
        "PAUSE",
        "pending",
        None,
        True,
        "verification_unstable",
        id="fallback-pause",
    ),
    pytest.param(
        {
            "user_request": "Review required for approval-related change.",
            "changed_areas": {"approval"},
        },
        "REVIEW",
        "withheld",
        AUDIT_AND_REVIEW_DEPARTMENT,
        True,
        "approval_flow_change",
        id="fallback-review",
    ),
]

# Explicit Status Mapping Cases
EXPLICIT_STATUS_CASES = [
    pytest.param(
        {
            "user_request": "Low-risk docs-only change with no blockers.",
            "changed_areas": {"docs"},
        },
        ManagementDecisionRecord(
            item_id="rq_go_status_projection_1",
            decision="GO",
            reviewer_id="manager-go-status",
            reviewer_type="human",
            rationale="Explicit GO status mapping check.",
            approved_next_action="Proceed in dry-run mode.",
        ),
        "GO",
        "approved",
        None,
        id="explicit-go",
    ),
    pytest.param(
        {
            "user_request": "Pause until approval-related blockers are cleared.",
            "changed_areas": {"approval"},
        },
        ManagementDecisionRecord(
            item_id="rq_pause_status_projection_1",
            decision="PAUSE",
            reviewer_id="manager-pause-status",
            reviewer_type="human",
            rationale="Explicit PAUSE status mapping check.",
            approved_next_action="Keep paused until blockers are resolved.",
        ),
        "PAUSE",
        "pending",
        None,
        id="explicit-pause",
    ),
    pytest.param(
        {
            "user_request": (
                "Title: Approval review\n"
                "Scope: dry-run governance projection\n"
                "Constraints: no runtime changes\n"
                "Success Criteria: explicit escalation destination\n"
                "Deadline: 2026-05-01"
            ),
            "changed_areas": {"docs"},
        },
        ManagementDecisionRecord(
            item_id="rq_review_status_projection_1",
            decision="REVIEW",
            reviewer_id="manager-review-status",
            reviewer_type="human",
            rationale="Explicit REVIEW status mapping check.",
            approved_next_action="Escalate to audit and review before any continuation.",
        ),
        "REVIEW",
        "withheld",
        AUDIT_AND_REVIEW_DEPARTMENT,
        id="explicit-review",
    ),
]

PARITY_CASES = [
    pytest.param(
        "review",
        "Review required for parity validation.",
        frozenset({"approval"}),
        "docs/examples/action_department_activation_approval_record_review_example.json",
        "management_review_status",
        id="parity-review",
    ),
    pytest.param(
        "go",
        "Low-risk docs-only change for GO parity validation.",
        frozenset({"docs"}),
        "docs/examples/action_department_activation_decision_example.json",
        "top",
        id="parity-go",
    ),
    pytest.param(
        "pause",
        "Pause required for parity validation.",
        frozenset({"approval"}),
        "docs/examples/action_department_activation_approval_record_pause_example.json",
        "management_review_status",
        id="parity-pause",
    ),
]

SEAM_CASES = [
    pytest.param(
        "go",
        "Low-risk docs-only change for seam GO validation.",
        frozenset({"docs"}),
        "docs/examples/action_department_activation_approval_record_example.json",
        None,
        id="seam-go",
    ),
    pytest.param(
        "pause",
        "Pause required for seam PAUSE validation.",
        frozenset({"approval"}),
        "docs/examples/action_department_activation_approval_record_pause_example.json",
        None,
        id="seam-pause",
    ),
    pytest.param(
        "review",
        "Review required for seam REVIEW validation.",
        frozenset({"approval"}),
        "docs/examples/action_department_activation_approval_record_review_example.json",
        AUDIT_AND_REVIEW_DEPARTMENT,
        id="seam-review",
    ),
]

ARTIFACT_PAIR_CASES = [
    pytest.param(
        "go",
        "Low-risk docs-only change for artifact-pair GO contract validation.",
        frozenset({"docs"}),
        "docs/examples/action_department_activation_decision_example.json",
        "docs/examples/action_department_activation_approval_record_example.json",
        id="artifact-pair-go",
    ),
    pytest.param(
        "pause",
        "Pause required for artifact-pair PAUSE contract validation.",
        frozenset({"approval"}),
        "docs/examples/action_department_activation_approval_record_pause_example.json",
        "docs/examples/action_department_activation_approval_record_pause_example.json",
        id="artifact-pair-pause",
    ),
    pytest.param(
        "review",
        "Review required for artifact-pair REVIEW contract validation.",
        frozenset({"approval"}),
        "docs/examples/action_department_activation_approval_record_review_example.json",
        "docs/examples/action_department_activation_approval_record_review_example.json",
        id="artifact-pair-review",
    ),
]

PASS_THROUGH_FALLBACK_CASES = [
    pytest.param(
        "activation_review_related_ids_1",
        {
            "related_project_id": "project_related_001",
            "related_packet_id": "packet_related_001",
            "related_queue_item_id": "queue_related_001",
        },
        {
            "related_project_id": "project_related_001",
            "related_packet_id": "packet_related_001",
            "related_queue_item_id": "queue_related_001",
        },
        id="related-project-packet-queue",
    ),
    pytest.param(
        "activation_review_related_activation_ids_1",
        {
            "approval_record_id": "approval_record_001",
            "related_activation_decision_id": "activation_decision_001",
        },
        {
            "approval_record_id": "approval_record_001",
            "related_activation_decision_id": "activation_decision_001",
        },
        id="approval-record-and-related-activation-decision",
    ),
]

PROJECTION_CONTEXT_PARITY_CASES = [
    pytest.param("GO", {"docs"}, id="projection-context-parity-go"),
    pytest.param("PAUSE", {"approval"}, id="projection-context-parity-pause"),
    pytest.param("REVIEW", {"approval"}, id="projection-context-parity-review"),
]

COMPOSITION_PARITY_CASES = [
    pytest.param(
        "GO",
        "Low-risk docs-only change for artifact-pair composition GO parity validation.",
        frozenset({"docs"}),
        id="composition-parity-go",
    ),
    pytest.param(
        "PAUSE",
        "Pause-required change for artifact-pair composition PAUSE parity validation.",
        frozenset({"approval"}),
        id="composition-parity-pause",
    ),
    pytest.param(
        "REVIEW",
        "Review-required change for artifact-pair composition REVIEW parity validation.",
        frozenset({"approval"}),
        id="composition-parity-review",
    ),
]


def test_dry_run_orchestration_low_risk_go_flow_with_work_order() -> None:
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=(
                "Title: Docs update\n"
                "Scope: docs only\n"
                "Constraints: none\n"
                "Success Criteria: clear docs\n"
                "Deadline: 2026-05-01"
            ),
            changed_areas={"docs"},
        )
    )

    assert result.mode == "dry_run"
    assert result.triage_result.decision == ContinuationDecision.GO
    assert result.work_order is not None
    assert result.management_summary.decision_outcome == "GO"
    assert result.management_summary.department_routing == "action_department"
    assert result.management_summary.required_review is False


def test_dry_run_orchestration_governance_sensitive_flow_surfaces_review() -> None:
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request="Harden approval behavior",
            changed_areas={"approval"},
            include_trend=True,
            trend_provider_hint="gemini-flash-latest",
        )
    )

    assert result.triage_result.decision == ContinuationDecision.REVIEW
    assert result.work_order is not None
    assert result.work_order.governance.management_review_required is True
    assert result.management_summary.decision_outcome == "REVIEW"
    assert result.management_summary.required_review is True
    assert "approval_flow_change" in result.management_summary.hard_gate_triggers


def test_dry_run_orchestration_can_emit_trend_backed_summary_without_work_order() -> None:
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request="Evaluate trend analysis workflow",
            changed_areas={"internal_refactor"},
            include_trend=True,
            trend_provider_hint="gemini-flash-lite-latest",
            generate_work_order=False,
        )
    )

    assert result.work_order is None
    assert result.trend_report is not None
    assert result.trend_report.provider == "gemini"
    assert result.management_summary.trend_provider == "gemini"
    assert result.management_summary.work_order_id is None
    assert "GO/PAUSE/REVIEW" in result.management_summary.proposed_action


def test_dry_run_orchestration_auth_policy_approval_requests_require_review() -> None:
    for risky_area in ("auth", "approval", "policy"):
        result = run_dry_run_orchestration(
            DryRunOrchestrationRequest(
                user_request=f"Handle risky area: {risky_area}",
                changed_areas={risky_area},
                include_trend=False,
            )
        )

        assert result.triage_result.decision == ContinuationDecision.REVIEW
        assert result.management_summary.decision_outcome == "REVIEW"
        assert result.management_summary.required_review is True
        assert result.management_summary.department_routing == "management_department"


def test_dry_run_orchestration_cross_department_requests_require_review() -> None:
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request="Coordinate across departments",
            changed_areas={"cross_department"},
            include_trend=False,
        )
    )

    assert result.triage_result.decision == ContinuationDecision.REVIEW
    assert result.management_summary.decision_outcome == "REVIEW"
    assert result.management_summary.required_review is True
    assert result.management_summary.department_routing == "management_department"


def test_latest_alias_trend_hint_does_not_override_review_trigger() -> None:
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request="Auth hardening proposal",
            changed_areas={"auth"},
            include_trend=True,
            trend_provider_hint="gemini-flash-latest",
        )
    )

    assert result.trend_report is not None
    assert result.trend_report.provider == "gemini"
    assert result.triage_result.decision == ContinuationDecision.REVIEW
    assert result.management_summary.decision_outcome == "REVIEW"
    assert result.management_summary.required_review is True


def test_dry_run_orchestration_applies_management_go_decision_for_safe_case() -> None:
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request="Update docs safely",
            changed_areas={"docs"},
            management_decision=ManagementDecisionRecord(
                item_id="rq_go_1",
                decision="GO",
                reviewer_id="manager-1",
                reviewer_type="human",
                rationale="Docs-only and low-risk.",
                approved_next_action="Proceed with docs update in simulation.",
            ),
        )
    )

    assert result.management_decision is not None
    assert result.decision_projection.decision == "GO"
    assert result.decision_projection.autonomous_continuation_allowed is True
    assert result.decision_projection.next_step == "Proceed with docs update in simulation."


def test_dry_run_orchestration_go_decision_does_not_auto_continue_when_review_required() -> None:
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request="Coordinate cross-department plan",
            changed_areas={"cross_department"},
            management_decision=ManagementDecisionRecord(
                item_id="rq_go_cross_1",
                decision="GO",
                reviewer_id="manager-2",
                reviewer_type="human",
                rationale="GO noted but management wants controlled continuation.",
                approved_next_action="Continue only after explicit management checkpoint.",
            ),
        )
    )

    assert result.management_summary.required_review is True
    assert result.decision_projection.decision == "GO"
    assert result.decision_projection.autonomous_continuation_allowed is False
    assert "do not continue autonomously" in result.decision_projection.next_step.lower()


def test_dry_run_orchestration_review_decision_remains_non_autonomous_for_risky_case() -> None:
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request="Change approval behavior",
            changed_areas={"approval"},
            management_decision=ManagementDecisionRecord(
                item_id="rq_review_1",
                decision="REVIEW",
                reviewer_id="mgmt-sonnet",
                reviewer_type="model",
                rationale="Approval flow is governance-sensitive.",
                approved_next_action="Do not execute until review completes.",
            ),
        )
    )

    assert result.triage_result.decision == ContinuationDecision.REVIEW
    assert result.management_summary.hard_gate_triggered is True
    assert result.decision_projection.decision == "REVIEW"
    assert result.decision_projection.autonomous_continuation_allowed is False
    assert "do not continue autonomously" in result.decision_projection.next_step.lower()


def test_dry_run_orchestration_exposes_read_only_activation_projection() -> None:
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=(
                "Title: Docs update\n"
                "Scope: docs only\n"
                "Constraints: none\n"
                "Success Criteria: clear docs\n"
                "Deadline: 2026-05-01"
            ),
            changed_areas={"docs"},
        )
    )

    assert result.projected_activation_decision is not None
    assert result.projected_activation_decision.recommendation in {"GO", "PAUSE", "REVIEW"}
    assert (
        result.projected_activation_decision.autonomous_continuation_status
        == AUTONOMOUS_NOT_APPROVED
    )
    # Projection Is Read-Only Metadata and Does Not Alter Orchestration Control Behavior
    assert result.decision_projection.autonomous_continuation_allowed is True


def _build_projection_test_summary():
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request="Low-risk docs-only change for decision projection helper coverage.",
            changed_areas={"docs"},
            include_trend=False,
            generate_work_order=False,
        )
    )
    return result.management_summary


def test_project_dry_run_decision_review_returns_fixed_escalation_message() -> None:
    summary = _build_projection_test_summary().model_copy(
        update={
            "decision_outcome": "REVIEW",
            "required_review": False,
            "hard_gate_triggered": False,
        }
    )
    management_decision = ManagementDecisionRecord(
        item_id="rq_projection_review_1",
        decision="REVIEW",
        reviewer_id="manager-review-projection",
        reviewer_type="human",
        rationale="Review path should always stay non-autonomous.",
        approved_next_action="This should be ignored for REVIEW.",
    )

    projection = project_dry_run_decision(
        management_summary=summary, management_decision=management_decision
    )

    assert projection.decision == "REVIEW"
    assert projection.rationale == management_decision.rationale
    assert (
        projection.next_step
        == "Escalate to Management/Audit review; do not continue autonomously."
    )
    assert projection.autonomous_continuation_allowed is False


def test_project_dry_run_decision_pause_returns_fixed_pause_message() -> None:
    summary = _build_projection_test_summary().model_copy(
        update={"decision_outcome": "PAUSE", "required_review": False, "hard_gate_triggered": False}
    )
    management_decision = ManagementDecisionRecord(
        item_id="rq_projection_pause_1",
        decision="PAUSE",
        reviewer_id="manager-pause-projection",
        reviewer_type="human",
        rationale="Pause path should always stay non-autonomous.",
        approved_next_action="This should be ignored for PAUSE.",
    )

    projection = project_dry_run_decision(
        management_summary=summary, management_decision=management_decision
    )

    assert projection.decision == "PAUSE"
    assert projection.rationale == management_decision.rationale
    assert (
        projection.next_step
        == "Pause dry-run progression and resolve blockers before next simulation step."
    )
    assert projection.autonomous_continuation_allowed is False


def test_project_dry_run_decision_go_with_required_review_remains_non_autonomous() -> None:
    summary = _build_projection_test_summary().model_copy(
        update={"decision_outcome": "GO", "required_review": True, "hard_gate_triggered": False}
    )
    management_decision = ManagementDecisionRecord(
        item_id="rq_projection_go_required_review_1",
        decision="GO",
        reviewer_id="manager-go-required-review",
        reviewer_type="human",
        rationale="GO must still wait for management review in this scenario.",
        approved_next_action="Proceed after review.",
    )

    projection = project_dry_run_decision(
        management_summary=summary, management_decision=management_decision
    )

    assert projection.decision == "GO"
    assert projection.rationale == management_decision.rationale
    assert (
        projection.next_step
        == (
            "Management review is still required for this dry-run outcome; "
            "do not continue autonomously."
        )
    )
    assert projection.autonomous_continuation_allowed is False


def test_project_dry_run_decision_go_with_hard_gate_remains_non_autonomous() -> None:
    summary = _build_projection_test_summary().model_copy(
        update={"decision_outcome": "GO", "required_review": False, "hard_gate_triggered": True}
    )
    management_decision = ManagementDecisionRecord(
        item_id="rq_projection_go_hard_gate_1",
        decision="GO",
        reviewer_id="manager-go-hard-gate",
        reviewer_type="human",
        rationale="GO cannot continue while hard gate is active.",
        approved_next_action="Proceed after hard-gate removal.",
    )

    projection = project_dry_run_decision(
        management_summary=summary, management_decision=management_decision
    )

    assert projection.decision == "GO"
    assert projection.rationale == management_decision.rationale
    assert (
        projection.next_step
        == "GO noted in dry-run, but hard gate remains active; keep management-led review path."
    )
    assert projection.autonomous_continuation_allowed is False


def test_project_dry_run_decision_clean_go_uses_management_next_action() -> None:
    summary = _build_projection_test_summary().model_copy(
        update={
            "decision_outcome": "GO",
            "required_review": False,
            "hard_gate_triggered": False,
            "proposed_action": "Summary fallback action.",
        }
    )
    management_decision = ManagementDecisionRecord(
        item_id="rq_projection_go_clean_1",
        decision="GO",
        reviewer_id="manager-go-clean-projection",
        reviewer_type="human",
        rationale="Clean GO path should use explicit management next action.",
        approved_next_action="Management-approved next action.",
    )

    projection = project_dry_run_decision(
        management_summary=summary, management_decision=management_decision
    )

    assert projection.decision == "GO"
    assert projection.rationale == management_decision.rationale
    assert projection.next_step == "Management-approved next action."
    assert projection.autonomous_continuation_allowed is True


def test_project_dry_run_decision_clean_go_falls_back_to_summary_proposed_action() -> None:
    summary = _build_projection_test_summary().model_copy(
        update={
            "decision_outcome": "GO",
            "required_review": False,
            "hard_gate_triggered": False,
            "proposed_action": "Summary proposed fallback action.",
        }
    )
    management_decision = ManagementDecisionRecord(
        item_id="rq_projection_go_fallback_1",
        decision="GO",
        reviewer_id="manager-go-fallback-projection",
        reviewer_type="human",
        rationale="Fallback path should use summary proposed action when empty.",
        approved_next_action="",
    )

    projection = project_dry_run_decision(
        management_summary=summary, management_decision=management_decision
    )

    assert projection.decision == "GO"
    assert projection.next_step == summary.proposed_action
    assert projection.autonomous_continuation_allowed is True


def test_project_dry_run_decision_without_management_decision_uses_fallback_rationale() -> None:
    summary = _build_projection_test_summary().model_copy(
        update={
            "decision_outcome": "GO",
            "required_review": False,
            "hard_gate_triggered": False,
            "proposed_action": "Summary-only action.",
        }
    )

    projection = project_dry_run_decision(management_summary=summary, management_decision=None)

    assert projection.decision == "GO"
    assert projection.rationale == "Derived from management summary recommendation."
    assert projection.next_step == "Summary-only action."
    assert projection.autonomous_continuation_allowed is True

# Fallback Projection Tests
def test_build_projected_activation_decision_uses_system_reviewer_fallback() -> None:
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=(
                "Title: Docs update\n"
                "Scope: docs only\n"
                "Constraints: none\n"
                "Success Criteria: clear docs\n"
                "Deadline: 2026-05-01"
            ),
            changed_areas={"docs"},
        )
    )

    projected_once = build_projected_activation_decision(
        current_brief=result.current_brief,
        management_summary=result.management_summary,
        management_decision=None,
    )
    projected_twice = build_projected_activation_decision(
        current_brief=result.current_brief,
        management_summary=result.management_summary,
        management_decision=None,
    )

    first_approval = projected_once.human_approvals_recorded[0]
    assert projected_once == projected_twice
    assert projected_once.recommendation in {"GO", "PAUSE", "REVIEW"}
    assert projected_once.autonomous_continuation_status == AUTONOMOUS_NOT_APPROVED
    assert first_approval[APPROVER_ID_KEY] == FALLBACK_REVIEWER_ID
    assert first_approval[APPROVER_TYPE_KEY] == FALLBACK_REVIEWER_TYPE


@pytest.mark.parametrize(
    (
        "request_kwargs",
        "expected_recommendation",
        "expected_status",
        "expected_escalation_destination",
        "expected_re_review_required",
        "expected_blocker",
    ),
    FALLBACK_STATUS_CASES,
)
def test_build_projected_activation_decision_fallback_status_mapping(
    request_kwargs: RequestKwargs,
    expected_recommendation: RecommendationValue,
    expected_status: ApprovalStatusValue,
    expected_escalation_destination: str | None,
    expected_re_review_required: bool,
    expected_blocker: str | None,
) -> None:
    result = run_dry_run_orchestration(DryRunOrchestrationRequest(**request_kwargs))

    projected = build_projected_activation_decision(
        current_brief=result.current_brief,
        management_summary=result.management_summary,
        management_decision=None,
    )

    first_approval = projected.human_approvals_recorded[0]
    assert result.management_decision is None
    assert result.management_summary.decision_outcome == expected_recommendation
    assert projected.recommendation == expected_recommendation
    assert projected.re_review_required is expected_re_review_required
    assert projected.escalation_destination == expected_escalation_destination
    assert first_approval[STATUS_KEY] == expected_status
    assert first_approval[APPROVER_ID_KEY] == FALLBACK_REVIEWER_ID
    assert first_approval[APPROVER_TYPE_KEY] == FALLBACK_REVIEWER_TYPE
    assert projected.autonomous_continuation_status == AUTONOMOUS_NOT_APPROVED
    if expected_blocker is None:
        assert projected.remaining_blockers == []
    else:
        assert expected_blocker in projected.remaining_blockers

# Explicit Projection Tests
def test_build_projected_activation_decision_uses_given_management_reviewer() -> None:
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=(
                "Title: Docs update\n"
                "Scope: docs only\n"
                "Constraints: none\n"
                "Success Criteria: clear docs\n"
                "Deadline: 2026-05-01"
            ),
            changed_areas={"docs"},
        )
    )
    management_decision = ManagementDecisionRecord(
        item_id="rq_go_projection_1",
        decision="GO",
        reviewer_id="manager-explicit",
        reviewer_type="human",
        rationale="Explicit management decision for projection test.",
        approved_next_action="Proceed in dry-run only.",
    )

    projected = build_projected_activation_decision(
        current_brief=result.current_brief,
        management_summary=result.management_summary,
        management_decision=management_decision,
    )

    first_approval = projected.human_approvals_recorded[0]
    assert projected.recommendation in {"GO", "PAUSE", "REVIEW"}
    assert projected.autonomous_continuation_status == AUTONOMOUS_NOT_APPROVED
    assert first_approval[APPROVER_ID_KEY] == "manager-explicit"
    assert first_approval[APPROVER_TYPE_KEY] == "human"
    assert first_approval[APPROVER_ID_KEY] != FALLBACK_REVIEWER_ID


@pytest.mark.parametrize(
    (
        "request_kwargs",
        "management_decision",
        "expected_recommendation",
        "expected_status",
        "expected_escalation_destination",
    ),
    EXPLICIT_STATUS_CASES,
)
def test_build_projected_activation_decision_explicit_status_mapping(
    request_kwargs: RequestKwargs,
    management_decision: ManagementDecisionRecord,
    expected_recommendation: RecommendationValue,
    expected_status: ApprovalStatusValue,
    expected_escalation_destination: str | None,
) -> None:
    result = run_dry_run_orchestration(DryRunOrchestrationRequest(**request_kwargs))

    projected = build_projected_activation_decision(
        current_brief=result.current_brief,
        management_summary=result.management_summary,
        management_decision=management_decision,
    )

    first_approval = projected.human_approvals_recorded[0]
    assert projected.recommendation == expected_recommendation
    assert first_approval[STATUS_KEY] == expected_status
    assert first_approval[APPROVER_ID_KEY] == management_decision.reviewer_id
    assert first_approval[APPROVER_TYPE_KEY] == management_decision.reviewer_type
    assert first_approval[APPROVER_ID_KEY] != FALLBACK_REVIEWER_ID
    assert projected.escalation_destination == expected_escalation_destination
    assert projected.autonomous_continuation_status == AUTONOMOUS_NOT_APPROVED


def test_build_projected_activation_decision_review_contract_matches_examples() -> None:
    expected_review_payload, projected = _build_projected_contract_from_examples(
        expected_payload_path="docs/examples/action_department_activation_approval_record_review_example.json",
        update={
            "reviewer_id": "manager-review-contract",
            "reviewer_type": "human",
        },
        user_request="Review required for approval-flow contract validation.",
        changed_areas={"approval"},
    )

    first_approval = projected.human_approvals_recorded[0]
    expected_escalation_destination = AUDIT_AND_REVIEW_DEPARTMENT
    assert expected_escalation_destination in expected_review_payload["management_review_status"][
        "note"
    ]
    assert projected.recommendation == expected_review_payload["recommendation"]
    assert projected.escalation_destination == expected_escalation_destination
    assert first_approval[STATUS_KEY] == expected_review_payload["human_approval_status"]["status"]
    assert (
        projected.autonomous_continuation_status
        == expected_review_payload["autonomous_continuation_status"]
    )


def test_intake_result_to_trend_request_maps_objective_scope_and_max_items() -> None:
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request="Trend request mapping verification task.",
            changed_areas={"docs"},
            include_trend=False,
            generate_work_order=False,
        )
    )

    trend_request = intake_result_to_trend_request(result.intake_result)

    assert trend_request.trend_topic == result.intake_result.brief.objective
    assert trend_request.context == result.intake_result.brief.scope
    assert trend_request.max_items == 3


def test_run_dry_run_orchestration_without_trend_keeps_trend_report_none() -> None:
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request="No trend report expected when include_trend is false.",
            changed_areas={"docs"},
            include_trend=False,
        )
    )

    assert result.trend_report is None


def test_run_dry_run_orchestration_preserves_explicit_ids() -> None:
    management_decision = ManagementDecisionRecord(
        item_id="rq_explicit_ids_1",
        decision="GO",
        reviewer_id="manager-explicit-ids",
        reviewer_type="human",
        rationale="Explicit id passthrough contract validation.",
        approved_next_action="Proceed with explicit-id dry-run.",
    )
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request="Explicit id passthrough verification.",
            changed_areas={"docs"},
            project_id="project_explicit_1",
            brief_id="brief_explicit_1",
            work_order_id="wo_explicit_1",
            management_decision=management_decision,
        )
    )

    assert result.mode == "dry_run"
    assert result.notice == SIMULATION_NOTICE
    assert result.current_brief.project_id == "project_explicit_1"
    assert result.current_brief.brief_id == "brief_explicit_1"
    assert result.management_summary.project_id == "project_explicit_1"
    assert result.management_summary.brief_id == "brief_explicit_1"
    assert result.work_order is not None
    assert result.work_order.project_id == "project_explicit_1"
    assert result.work_order.work_order_id == "wo_explicit_1"
    assert result.projected_activation_decision is not None
    assert result.decision_projection is not None


def test_run_dry_run_orchestration_preserves_management_decision_reference() -> None:
    management_decision = ManagementDecisionRecord(
        item_id="rq_management_passthrough_1",
        decision="GO",
        reviewer_id="manager-reference-preserve",
        reviewer_type="human",
        rationale="Management decision object passthrough verification.",
        approved_next_action="Proceed with explicit management decision.",
    )
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request="Management decision passthrough verification.",
            changed_areas={"docs"},
            management_decision=management_decision,
        )
    )

    expected_projection = project_dry_run_decision(
        management_summary=result.management_summary, management_decision=management_decision
    )
    assert result.management_decision is management_decision
    assert result.decision_projection == expected_projection


@pytest.mark.parametrize(
    (
        "case_name",
        "user_request",
        "changed_areas",
        "expected_payload_path",
        "reviewer_source",
    ),
    PARITY_CASES,
)
def test_build_projected_activation_decision_parity_with_derive(
    case_name: str,
    user_request: str,
    changed_areas: frozenset[str],
    expected_payload_path: str,
    reviewer_source: ParityReviewerSource,
) -> None:
    expected_payload = json.loads((_ROOT / expected_payload_path).read_text(encoding="utf-8"))
    management_decision_payload = json.loads(
        (_ROOT / "docs/examples/management_decision_example.json").read_text(encoding="utf-8")
    )
    reviewer_data = (
        expected_payload
        if reviewer_source == "top"
        else expected_payload["management_review_status"]
    )
    management_decision = ManagementDecisionRecord.model_validate(
        management_decision_payload
    ).model_copy(
        update={
            "decision": expected_payload["recommendation"],
            "reviewer_id": reviewer_data["reviewer_id"],
            "reviewer_type": reviewer_data["reviewer_type"],
            "rationale": expected_payload["rationale"],
        }
    )

    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=user_request,
            changed_areas=set(changed_areas),
        )
    )
    projected = build_projected_activation_decision(
        current_brief=result.current_brief,
        management_summary=result.management_summary,
        management_decision=management_decision,
    )
    packet, queue_item, normalized_management_decision = _normalize_activation_projection_inputs(
        current_brief=result.current_brief,
        management_summary=result.management_summary,
        management_decision=management_decision,
    )
    derived = derive_dry_run_activation_decision(
        management_review_packet=packet,
        review_queue_item=queue_item,
        management_decision=normalized_management_decision,
    )

    projected_first_approval = projected.human_approvals_recorded[0]
    derived_first_approval = derived.human_approvals_recorded[0]
    assert projected.recommendation == expected_payload["recommendation"], case_name
    assert projected.recommendation == derived.recommendation
    assert projected.remaining_blockers == derived.remaining_blockers
    assert projected.re_review_required is derived.re_review_required
    assert projected.escalation_destination == derived.escalation_destination
    assert projected_first_approval[STATUS_KEY] == derived_first_approval[STATUS_KEY]
    assert (
        projected.autonomous_continuation_status
        == derived.autonomous_continuation_status
    )


def test_build_projected_activation_decision_go_contract_matches_examples() -> None:
    expected_go_payload, projected = _build_projected_contract_from_examples(
        expected_payload_path="docs/examples/action_department_activation_decision_example.json",
        update={
            "decision": "GO",
            "reviewer_id": "mgmt-sonnet",
            "reviewer_type": "model",
            "rationale": (
                "Limited scope can start under strict advisory-only and "
                "hard-gate constraints."
            ),
        },
        user_request="Low-risk docs-only change for GO contract validation.",
        changed_areas={"docs"},
    )

    first_approval = projected.human_approvals_recorded[0]
    assert projected.recommendation == expected_go_payload["recommendation"]
    assert projected.remaining_blockers == expected_go_payload["remaining_blockers"]
    assert projected.re_review_required is False
    assert projected.escalation_destination is None
    assert (
        first_approval[STATUS_KEY]
        == expected_go_payload["human_approvals_recorded"][0]["status"]
    )
    assert (
        projected.autonomous_continuation_status
        == expected_go_payload["autonomous_continuation_status"]
    )


def test_build_projected_activation_decision_pause_contract_matches_examples() -> None:
    expected_pause_payload, projected = _build_projected_contract_from_examples(
        expected_payload_path="docs/examples/action_department_activation_approval_record_pause_example.json",
        update={
            "decision": "PAUSE",
            "reviewer_id": "manager-pause-contract",
            "reviewer_type": "human",
            "rationale": "Activation cannot proceed until operational safeguards are demonstrated.",
        },
        user_request="Pause required for approval-flow contract validation.",
        changed_areas={"approval"},
    )

    first_approval = projected.human_approvals_recorded[0]
    assert projected.recommendation == expected_pause_payload["recommendation"]
    assert projected.remaining_blockers == ["approval_flow_change", "hard_gate_triggered"]
    assert projected.re_review_required is True
    assert projected.escalation_destination is None
    assert first_approval[STATUS_KEY] == expected_pause_payload["human_approval_status"]["status"]
    assert (
        projected.autonomous_continuation_status
        == expected_pause_payload["autonomous_continuation_status"]
    )


@pytest.mark.parametrize(
    (
        "case_name",
        "user_request",
        "changed_areas",
        "expected_payload_path",
        "expected_escalation_destination",
    ),
    SEAM_CASES,
)
def test_projection_to_approval_record_seam_matches_examples_contract(
    case_name: str,
    user_request: str,
    changed_areas: frozenset[str],
    expected_payload_path: str,
    expected_escalation_destination: str | None,
) -> None:
    expected_payload = json.loads((_ROOT / expected_payload_path).read_text(encoding="utf-8"))
    management_decision_payload = json.loads(
        (_ROOT / "docs/examples/management_decision_example.json").read_text(encoding="utf-8")
    )
    management_decision = ManagementDecisionRecord.model_validate(
        management_decision_payload
    ).model_copy(
        update={
            "decision": expected_payload["recommendation"],
            "reviewer_id": expected_payload["management_review_status"]["reviewer_id"],
            "reviewer_type": expected_payload["management_review_status"]["reviewer_type"],
            "rationale": expected_payload["rationale"],
        }
    )

    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=user_request,
            changed_areas=set(changed_areas),
        )
    )
    projected = build_projected_activation_decision(
        current_brief=result.current_brief,
        management_summary=result.management_summary,
        management_decision=management_decision,
    )
    record = build_approval_record_from_projection_context(
        projected_activation_decision=projected,
        activation_review_item_id=expected_payload["activation_review_item_id"],
        management_decision=management_decision,
        related_project_id=expected_payload["related_project_id"],
        related_activation_decision_id=expected_payload["related_activation_decision_id"],
        related_packet_id=expected_payload["related_packet_id"],
        related_queue_item_id=expected_payload["related_queue_item_id"],
    )
    builder_kwargs = build_approval_record_builder_kwargs_from_projection(
        projected_activation_decision=projected,
        activation_review_item_id=expected_payload["activation_review_item_id"],
        management_decision=management_decision,
        related_project_id=expected_payload["related_project_id"],
        related_activation_decision_id=expected_payload["related_activation_decision_id"],
        related_packet_id=expected_payload["related_packet_id"],
        related_queue_item_id=expected_payload["related_queue_item_id"],
    )

    assert builder_kwargs["projected_activation_decision"] is projected
    assert (
        builder_kwargs["activation_review_item_id"]
        == expected_payload["activation_review_item_id"]
    )
    assert builder_kwargs["reviewer_id"] == management_decision.reviewer_id
    assert builder_kwargs["reviewer_type"] == management_decision.reviewer_type
    assert builder_kwargs["rationale"] == management_decision.rationale
    assert record["recommendation"] == projected.recommendation
    assert record["recommendation"] == expected_payload["recommendation"], case_name
    assert (
        record["management_review_status"]["review_outcome"]
        == expected_payload["management_review_status"]["review_outcome"]
    )
    assert record["human_approval_status"]["status"] == projected.human_approvals_recorded[0][
        STATUS_KEY
    ]
    assert (
        record["human_approval_status"]["status"]
        == expected_payload["human_approval_status"]["status"]
    )
    assert record["blocker_notes"] == projected.remaining_blockers
    assert (len(record["blocker_notes"]) > 0) is (len(expected_payload["blocker_notes"]) > 0)
    assert (
        record["autonomous_continuation_status"]
        == projected.autonomous_continuation_status
    )
    assert (
        record["autonomous_continuation_status"]
        == expected_payload["autonomous_continuation_status"]
    )
    assert (
        record["rollback_disable_expectation"]
        == expected_payload["rollback_disable_expectation"]
    )

    if expected_escalation_destination is None:
        assert "Escalate to" not in record["management_review_status"]["note"]
    else:
        assert expected_escalation_destination in record["management_review_status"]["note"]
        assert (
            record["management_review_status"]["note"]
            == expected_payload["management_review_status"]["note"]
        )


@pytest.mark.parametrize(
    (
        "case_name",
        "user_request",
        "changed_areas",
        "expected_projected_payload_path",
        "expected_record_payload_path",
    ),
    ARTIFACT_PAIR_CASES,
)
def test_build_projected_artifact_pair_from_context_matches_examples_contract(
    case_name: str,
    user_request: str,
    changed_areas: frozenset[str],
    expected_projected_payload_path: str,
    expected_record_payload_path: str,
) -> None:
    expected_projected_payload = json.loads(
        (_ROOT / expected_projected_payload_path).read_text(encoding="utf-8")
    )
    expected_record_payload = json.loads(
        (_ROOT / expected_record_payload_path).read_text(encoding="utf-8")
    )
    management_decision_payload = json.loads(
        (_ROOT / "docs/examples/management_decision_example.json").read_text(encoding="utf-8")
    )
    management_decision = ManagementDecisionRecord.model_validate(
        management_decision_payload
    ).model_copy(
        update={
            "decision": expected_record_payload["recommendation"],
            "reviewer_id": expected_record_payload["management_review_status"]["reviewer_id"],
            "reviewer_type": expected_record_payload["management_review_status"]["reviewer_type"],
            "rationale": expected_record_payload["rationale"],
        }
    )

    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=user_request,
            changed_areas=set(changed_areas),
        )
    )
    projected, record = build_projected_artifact_pair_from_context(
        current_brief=result.current_brief,
        management_summary=result.management_summary,
        management_decision=management_decision,
        activation_review_item_id=expected_record_payload["activation_review_item_id"],
        related_project_id=expected_record_payload["related_project_id"],
        related_activation_decision_id=expected_record_payload[
            "related_activation_decision_id"
        ],
        related_packet_id=expected_record_payload["related_packet_id"],
        related_queue_item_id=expected_record_payload["related_queue_item_id"],
    )

    if "human_approvals_recorded" in expected_projected_payload:
        expected_projected_status = expected_projected_payload["human_approvals_recorded"][0][
            "status"
        ]
    else:
        expected_projected_status = expected_projected_payload["human_approval_status"][
            "status"
        ]

    assert projected.recommendation == expected_projected_payload["recommendation"], case_name
    assert projected.human_approvals_recorded[0][STATUS_KEY] == expected_projected_status
    assert (
        projected.autonomous_continuation_status
        == expected_projected_payload["autonomous_continuation_status"]
    )
    assert record["recommendation"] == expected_record_payload["recommendation"], case_name
    assert (
        record["management_review_status"]["review_outcome"]
        == expected_record_payload["management_review_status"]["review_outcome"]
    )
    assert (
        record["human_approval_status"]["status"]
        == expected_record_payload["human_approval_status"]["status"]
    )
    assert (
        record["autonomous_continuation_status"]
        == expected_record_payload["autonomous_continuation_status"]
    )
    assert record["recommendation"] == projected.recommendation
    assert record["human_approval_status"]["status"] == projected.human_approvals_recorded[0][
        STATUS_KEY
    ]
    assert (
        record["autonomous_continuation_status"]
        == projected.autonomous_continuation_status
    )


@pytest.mark.parametrize(
    ("decision", "changed_areas"),
    PROJECTION_CONTEXT_PARITY_CASES,
)
def test_build_approval_record_from_projection_context_matches_direct_builder_path(
    decision: RecommendationValue,
    changed_areas: set[str],
) -> None:
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request="Low-risk docs-only change for projection-context parity validation.",
            changed_areas=changed_areas,
        )
    )
    management_decision = ManagementDecisionRecord(
        item_id="rq_projection_context_parity_1",
        decision=decision,
        reviewer_id="manager-projection-context",
        reviewer_type="human",
        rationale="Parity check for projection-context record helper.",
        approved_next_action="Proceed in dry-run mode only.",
    )
    projected = build_projected_activation_decision(
        current_brief=result.current_brief,
        management_summary=result.management_summary,
        management_decision=management_decision,
    )

    record_via_context_helper = build_approval_record_from_projection_context(
        projected_activation_decision=projected,
        activation_review_item_id="activation_review_projection_context_parity_1",
        management_decision=management_decision,
        approval_record_id="approval_record_projection_context_parity_1",
        related_project_id="project_projection_context_parity_1",
        related_activation_decision_id="activation_decision_projection_context_parity_1",
        related_packet_id="packet_projection_context_parity_1",
        related_queue_item_id="queue_projection_context_parity_1",
    )
    record_via_direct_builder = build_action_department_activation_approval_record(
        **build_approval_record_builder_kwargs_from_projection(
            projected_activation_decision=projected,
            activation_review_item_id="activation_review_projection_context_parity_1",
            management_decision=management_decision,
            approval_record_id="approval_record_projection_context_parity_1",
            related_project_id="project_projection_context_parity_1",
            related_activation_decision_id="activation_decision_projection_context_parity_1",
            related_packet_id="packet_projection_context_parity_1",
            related_queue_item_id="queue_projection_context_parity_1",
        )
    )

    assert record_via_context_helper == record_via_direct_builder


@pytest.mark.parametrize(
    ("decision", "user_request", "changed_areas"),
    COMPOSITION_PARITY_CASES,
)
def test_build_projected_artifact_pair_from_context_matches_direct_composition_path(
    decision: RecommendationValue,
    user_request: str,
    changed_areas: frozenset[str],
) -> None:
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=user_request,
            changed_areas=set(changed_areas),
        )
    )
    management_decision = ManagementDecisionRecord(
        item_id="rq_artifact_pair_composition_parity_1",
        decision=decision,
        reviewer_id="manager-artifact-pair",
        reviewer_type="human",
        rationale="Composition parity check for artifact-pair helper.",
        approved_next_action="Escalate to audit and review before any continuation.",
    )

    pair_projected, pair_record = build_projected_artifact_pair_from_context(
        current_brief=result.current_brief,
        management_summary=result.management_summary,
        management_decision=management_decision,
        activation_review_item_id="activation_review_artifact_pair_parity_1",
        approval_record_id="approval_record_artifact_pair_parity_1",
        related_project_id="project_artifact_pair_parity_1",
        related_activation_decision_id="activation_decision_artifact_pair_parity_1",
        related_packet_id="packet_artifact_pair_parity_1",
        related_queue_item_id="queue_artifact_pair_parity_1",
    )

    direct_projected = build_projected_activation_decision(
        current_brief=result.current_brief,
        management_summary=result.management_summary,
        management_decision=management_decision,
    )
    direct_record = build_approval_record_from_projection_context(
        projected_activation_decision=direct_projected,
        activation_review_item_id="activation_review_artifact_pair_parity_1",
        management_decision=management_decision,
        approval_record_id="approval_record_artifact_pair_parity_1",
        related_project_id="project_artifact_pair_parity_1",
        related_activation_decision_id="activation_decision_artifact_pair_parity_1",
        related_packet_id="packet_artifact_pair_parity_1",
        related_queue_item_id="queue_artifact_pair_parity_1",
    )

    assert pair_projected == direct_projected
    assert pair_record == direct_record


@pytest.mark.parametrize(
    ("decision", "user_request", "changed_areas"),
    COMPOSITION_PARITY_CASES,
)
def test_build_dry_run_artifact_bundle_matches_existing_helper_outputs(
    decision: RecommendationValue,
    user_request: str,
    changed_areas: frozenset[str],
) -> None:
    management_decision = ManagementDecisionRecord(
        item_id="rq_artifact_bundle_equivalence_1",
        decision=decision,
        reviewer_id="manager-artifact-bundle",
        reviewer_type="human",
        rationale="Equivalence check for dry-run artifact bundle helper.",
        approved_next_action="Escalate to audit and review before any continuation.",
    )
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=user_request,
            changed_areas=set(changed_areas),
            management_decision=management_decision,
        )
    )

    bundle = build_dry_run_artifact_bundle(
        orchestration_result=result,
        activation_review_item_id="activation_review_artifact_bundle_equivalence_1",
        approval_record_id="approval_record_artifact_bundle_equivalence_1",
        related_project_id="project_artifact_bundle_equivalence_1",
        related_activation_decision_id="activation_decision_artifact_bundle_equivalence_1",
        related_packet_id="packet_artifact_bundle_equivalence_1",
        related_queue_item_id="queue_artifact_bundle_equivalence_1",
    )
    expected_projected = build_projected_activation_decision(
        current_brief=result.current_brief,
        management_summary=result.management_summary,
        management_decision=management_decision,
    )
    expected_record = build_approval_record_from_projection_context(
        projected_activation_decision=expected_projected,
        activation_review_item_id="activation_review_artifact_bundle_equivalence_1",
        management_decision=management_decision,
        approval_record_id="approval_record_artifact_bundle_equivalence_1",
        related_project_id="project_artifact_bundle_equivalence_1",
        related_activation_decision_id="activation_decision_artifact_bundle_equivalence_1",
        related_packet_id="packet_artifact_bundle_equivalence_1",
        related_queue_item_id="queue_artifact_bundle_equivalence_1",
    )

    assert bundle["projected_activation_decision"] == expected_projected
    assert bundle["approval_record"] == expected_record


@pytest.mark.parametrize(
    ("decision", "user_request", "changed_areas"),
    COMPOSITION_PARITY_CASES,
)
def test_build_dry_run_handoff_envelope_matches_bundle_artifacts_and_metadata(
    decision: RecommendationValue,
    user_request: str,
    changed_areas: frozenset[str],
) -> None:
    management_decision = ManagementDecisionRecord(
        item_id="rq_handoff_envelope_equivalence_1",
        decision=decision,
        reviewer_id="manager-handoff-envelope",
        reviewer_type="human",
        rationale="Equivalence check for dry-run handoff envelope helper.",
        approved_next_action="Escalate to audit and review before any continuation.",
    )
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=user_request,
            changed_areas=set(changed_areas),
            management_decision=management_decision,
        )
    )
    artifact_bundle = build_dry_run_artifact_bundle(
        orchestration_result=result,
        activation_review_item_id="activation_review_handoff_envelope_equivalence_1",
        approval_record_id="approval_record_handoff_envelope_equivalence_1",
        related_project_id="project_handoff_envelope_equivalence_1",
        related_activation_decision_id="activation_decision_handoff_envelope_equivalence_1",
        related_packet_id="packet_handoff_envelope_equivalence_1",
        related_queue_item_id="queue_handoff_envelope_equivalence_1",
    )

    envelope = build_dry_run_handoff_envelope(
        artifact_bundle=artifact_bundle,
        related_project_id="project_handoff_envelope_metadata_1",
        related_activation_decision_id="activation_decision_handoff_envelope_metadata_1",
        related_packet_id="packet_handoff_envelope_metadata_1",
        related_queue_item_id="queue_handoff_envelope_metadata_1",
    )

    assert (
        envelope["projected_activation_decision"]
        == artifact_bundle["projected_activation_decision"]
    )
    assert envelope["approval_record"] == artifact_bundle["approval_record"]
    assert envelope["related_project_id"] == "project_handoff_envelope_metadata_1"
    assert (
        envelope["related_activation_decision_id"]
        == "activation_decision_handoff_envelope_metadata_1"
    )
    assert envelope["related_packet_id"] == "packet_handoff_envelope_metadata_1"
    assert envelope["related_queue_item_id"] == "queue_handoff_envelope_metadata_1"


@pytest.mark.parametrize(
    ("decision", "user_request", "changed_areas"),
    COMPOSITION_PARITY_CASES,
)
def test_build_dry_run_handoff_envelope_from_result_matches_existing_composition_path(
    decision: RecommendationValue,
    user_request: str,
    changed_areas: frozenset[str],
) -> None:
    management_decision = ManagementDecisionRecord(
        item_id="rq_handoff_envelope_from_result_parity_1",
        decision=decision,
        reviewer_id="manager-handoff-envelope-from-result",
        reviewer_type="human",
        rationale="Parity check for result-to-handoff-envelope composition helper.",
        approved_next_action="Escalate to audit and review before any continuation.",
    )
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=user_request,
            changed_areas=set(changed_areas),
            management_decision=management_decision,
        )
    )

    actual_envelope = build_dry_run_handoff_envelope_from_result(
        orchestration_result=result,
        activation_review_item_id="activation_review_handoff_from_result_parity_1",
        approval_record_id="approval_record_handoff_from_result_parity_1",
        related_project_id="project_handoff_from_result_parity_1",
        related_activation_decision_id="activation_decision_handoff_from_result_parity_1",
        related_packet_id="packet_handoff_from_result_parity_1",
        related_queue_item_id="queue_handoff_from_result_parity_1",
    )
    expected_envelope = build_dry_run_handoff_envelope(
        artifact_bundle=build_dry_run_artifact_bundle(
            orchestration_result=result,
            activation_review_item_id="activation_review_handoff_from_result_parity_1",
            approval_record_id="approval_record_handoff_from_result_parity_1",
            related_project_id="project_handoff_from_result_parity_1",
            related_activation_decision_id="activation_decision_handoff_from_result_parity_1",
            related_packet_id="packet_handoff_from_result_parity_1",
            related_queue_item_id="queue_handoff_from_result_parity_1",
        ),
        related_project_id="project_handoff_from_result_parity_1",
        related_activation_decision_id="activation_decision_handoff_from_result_parity_1",
        related_packet_id="packet_handoff_from_result_parity_1",
        related_queue_item_id="queue_handoff_from_result_parity_1",
    )

    assert actual_envelope == expected_envelope


@pytest.mark.parametrize(
    ("decision", "user_request", "changed_areas"),
    COMPOSITION_PARITY_CASES,
)
def test_build_next_layer_intake_from_handoff_envelope_matches_handoff_envelope(
    decision: RecommendationValue,
    user_request: str,
    changed_areas: frozenset[str],
) -> None:
    management_decision = ManagementDecisionRecord(
        item_id="rq_next_layer_intake_parity_1",
        decision=decision,
        reviewer_id="manager-next-layer-intake",
        reviewer_type="human",
        rationale="Parity check for next-layer intake helper.",
        approved_next_action="Escalate to audit and review before any continuation.",
    )
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=user_request,
            changed_areas=set(changed_areas),
            management_decision=management_decision,
        )
    )
    handoff_envelope = build_dry_run_handoff_envelope_from_result(
        orchestration_result=result,
        activation_review_item_id="activation_review_next_layer_intake_parity_1",
        approval_record_id="approval_record_next_layer_intake_parity_1",
        related_project_id="project_next_layer_intake_parity_1",
        related_activation_decision_id="activation_decision_next_layer_intake_parity_1",
        related_packet_id="packet_next_layer_intake_parity_1",
        related_queue_item_id="queue_next_layer_intake_parity_1",
    )

    intake = build_next_layer_intake_from_handoff_envelope(
        handoff_envelope=handoff_envelope
    )

    assert (
        intake["projected_activation_decision"]
        == handoff_envelope["projected_activation_decision"]
    )
    assert intake["approval_record"] == handoff_envelope["approval_record"]
    assert intake["related_project_id"] == handoff_envelope["related_project_id"]
    assert (
        intake["related_activation_decision_id"]
        == handoff_envelope["related_activation_decision_id"]
    )
    assert intake["related_packet_id"] == handoff_envelope["related_packet_id"]
    assert intake["related_queue_item_id"] == handoff_envelope["related_queue_item_id"]


@pytest.mark.parametrize(
    ("decision", "user_request", "changed_areas"),
    COMPOSITION_PARITY_CASES,
)
def test_build_downstream_work_item_from_intake_matches_next_layer_intake(
    decision: RecommendationValue,
    user_request: str,
    changed_areas: frozenset[str],
) -> None:
    management_decision = ManagementDecisionRecord(
        item_id="rq_downstream_work_item_parity_1",
        decision=decision,
        reviewer_id="manager-downstream-work-item",
        reviewer_type="human",
        rationale="Parity check for downstream work-item helper.",
        approved_next_action="Escalate to audit and review before any continuation.",
    )
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=user_request,
            changed_areas=set(changed_areas),
            management_decision=management_decision,
        )
    )
    handoff_envelope = build_dry_run_handoff_envelope_from_result(
        orchestration_result=result,
        activation_review_item_id="activation_review_downstream_work_item_parity_1",
        approval_record_id="approval_record_downstream_work_item_parity_1",
        related_project_id="project_downstream_work_item_parity_1",
        related_activation_decision_id="activation_decision_downstream_work_item_parity_1",
        related_packet_id="packet_downstream_work_item_parity_1",
        related_queue_item_id="queue_downstream_work_item_parity_1",
    )
    intake = build_next_layer_intake_from_handoff_envelope(
        handoff_envelope=handoff_envelope
    )

    work_item = build_downstream_work_item_from_intake(next_layer_intake=intake)

    assert work_item["projected_activation_decision"] == intake["projected_activation_decision"]
    assert work_item["approval_record"] == intake["approval_record"]
    assert work_item["related_project_id"] == intake["related_project_id"]
    assert work_item["related_activation_decision_id"] == intake["related_activation_decision_id"]
    assert work_item["related_packet_id"] == intake["related_packet_id"]
    assert work_item["related_queue_item_id"] == intake["related_queue_item_id"]


@pytest.mark.parametrize(
    ("decision", "user_request", "changed_areas"),
    COMPOSITION_PARITY_CASES,
)
def test_build_downstream_execution_intent_from_work_item_matches_work_item(
    decision: RecommendationValue,
    user_request: str,
    changed_areas: frozenset[str],
) -> None:
    management_decision = ManagementDecisionRecord(
        item_id="rq_downstream_execution_intent_parity_1",
        decision=decision,
        reviewer_id="manager-downstream-execution-intent",
        reviewer_type="human",
        rationale="Parity check for downstream execution intent helper.",
        approved_next_action="Escalate to audit and review before any continuation.",
    )
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=user_request,
            changed_areas=set(changed_areas),
            management_decision=management_decision,
        )
    )
    handoff_envelope = build_dry_run_handoff_envelope_from_result(
        orchestration_result=result,
        activation_review_item_id="activation_review_downstream_execution_intent_parity_1",
        approval_record_id="approval_record_downstream_execution_intent_parity_1",
        related_project_id="project_downstream_execution_intent_parity_1",
        related_activation_decision_id="activation_decision_downstream_execution_intent_parity_1",
        related_packet_id="packet_downstream_execution_intent_parity_1",
        related_queue_item_id="queue_downstream_execution_intent_parity_1",
    )
    intake = build_next_layer_intake_from_handoff_envelope(
        handoff_envelope=handoff_envelope
    )
    work_item = build_downstream_work_item_from_intake(next_layer_intake=intake)

    intent = build_downstream_execution_intent_from_work_item(
        downstream_work_item=work_item
    )

    assert intent["projected_activation_decision"] == work_item["projected_activation_decision"]
    assert intent["approval_record"] == work_item["approval_record"]
    assert intent["related_project_id"] == work_item["related_project_id"]
    assert (
        intent["related_activation_decision_id"]
        == work_item["related_activation_decision_id"]
    )
    assert intent["related_packet_id"] == work_item["related_packet_id"]
    assert intent["related_queue_item_id"] == work_item["related_queue_item_id"]
    assert (
        intent["projected_activation_decision"].recommendation
        == work_item["projected_activation_decision"].recommendation
    )
    assert (
        intent["projected_activation_decision"].escalation_destination
        == work_item["projected_activation_decision"].escalation_destination
    )
    assert (
        intent["projected_activation_decision"].autonomous_continuation_status
        == work_item["projected_activation_decision"].autonomous_continuation_status
    )
    assert (
        intent["approval_record"]["human_approval_status"]["status"]
        == work_item["approval_record"]["human_approval_status"]["status"]
    )


@pytest.mark.parametrize(
    ("decision", "user_request", "changed_areas"),
    COMPOSITION_PARITY_CASES,
)
def test_build_execution_readiness_view_from_intent_matches_execution_intent(
    decision: RecommendationValue,
    user_request: str,
    changed_areas: frozenset[str],
) -> None:
    management_decision = ManagementDecisionRecord(
        item_id="rq_execution_readiness_view_parity_1",
        decision=decision,
        reviewer_id="manager-execution-readiness-view",
        reviewer_type="human",
        rationale="Parity check for execution readiness view helper.",
        approved_next_action="Escalate to audit and review before any continuation.",
    )
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=user_request,
            changed_areas=set(changed_areas),
            management_decision=management_decision,
        )
    )
    handoff_envelope = build_dry_run_handoff_envelope_from_result(
        orchestration_result=result,
        activation_review_item_id="activation_review_execution_readiness_view_parity_1",
        approval_record_id="approval_record_execution_readiness_view_parity_1",
        related_project_id="project_execution_readiness_view_parity_1",
        related_activation_decision_id="activation_decision_execution_readiness_view_parity_1",
        related_packet_id="packet_execution_readiness_view_parity_1",
        related_queue_item_id="queue_execution_readiness_view_parity_1",
    )
    intake = build_next_layer_intake_from_handoff_envelope(
        handoff_envelope=handoff_envelope
    )
    work_item = build_downstream_work_item_from_intake(next_layer_intake=intake)
    intent = build_downstream_execution_intent_from_work_item(
        downstream_work_item=work_item
    )

    readiness_view = build_execution_readiness_view_from_intent(
        downstream_execution_intent=intent
    )

    assert (
        readiness_view["projected_activation_decision"]
        == intent["projected_activation_decision"]
    )
    assert readiness_view["approval_record"] == intent["approval_record"]
    assert readiness_view["related_project_id"] == intent["related_project_id"]
    assert (
        readiness_view["related_activation_decision_id"]
        == intent["related_activation_decision_id"]
    )
    assert readiness_view["related_packet_id"] == intent["related_packet_id"]
    assert readiness_view["related_queue_item_id"] == intent["related_queue_item_id"]
    assert (
        readiness_view["projected_activation_decision"].recommendation
        == intent["projected_activation_decision"].recommendation
    )
    assert (
        readiness_view["projected_activation_decision"].escalation_destination
        == intent["projected_activation_decision"].escalation_destination
    )
    assert (
        readiness_view["projected_activation_decision"].autonomous_continuation_status
        == intent["projected_activation_decision"].autonomous_continuation_status
    )
    assert (
        readiness_view["approval_record"]["human_approval_status"]["status"]
        == intent["approval_record"]["human_approval_status"]["status"]
    )


@pytest.mark.parametrize(
    ("decision", "user_request", "changed_areas"),
    COMPOSITION_PARITY_CASES,
)
def test_build_execution_readiness_assessment_from_view_matches_readiness_view(
    decision: RecommendationValue,
    user_request: str,
    changed_areas: frozenset[str],
) -> None:
    management_decision = ManagementDecisionRecord(
        item_id="rq_execution_readiness_assessment_parity_1",
        decision=decision,
        reviewer_id="manager-execution-readiness-assessment",
        reviewer_type="human",
        rationale="Parity check for execution readiness assessment helper.",
        approved_next_action="Escalate to audit and review before any continuation.",
    )
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=user_request,
            changed_areas=set(changed_areas),
            management_decision=management_decision,
        )
    )
    handoff_envelope = build_dry_run_handoff_envelope_from_result(
        orchestration_result=result,
        activation_review_item_id="activation_review_execution_readiness_assessment_parity_1",
        approval_record_id="approval_record_execution_readiness_assessment_parity_1",
        related_project_id="project_execution_readiness_assessment_parity_1",
        related_activation_decision_id=(
            "activation_decision_execution_readiness_assessment_parity_1"
        ),
        related_packet_id="packet_execution_readiness_assessment_parity_1",
        related_queue_item_id="queue_execution_readiness_assessment_parity_1",
    )
    intake = build_next_layer_intake_from_handoff_envelope(
        handoff_envelope=handoff_envelope
    )
    work_item = build_downstream_work_item_from_intake(next_layer_intake=intake)
    intent = build_downstream_execution_intent_from_work_item(
        downstream_work_item=work_item
    )
    readiness_view = build_execution_readiness_view_from_intent(
        downstream_execution_intent=intent
    )

    assessment = build_execution_readiness_assessment_from_view(
        execution_readiness_view=readiness_view
    )

    assert (
        assessment["projected_activation_decision"]
        == readiness_view["projected_activation_decision"]
    )
    assert assessment["approval_record"] == readiness_view["approval_record"]
    assert assessment["related_project_id"] == readiness_view["related_project_id"]
    assert (
        assessment["related_activation_decision_id"]
        == readiness_view["related_activation_decision_id"]
    )
    assert assessment["related_packet_id"] == readiness_view["related_packet_id"]
    assert assessment["related_queue_item_id"] == readiness_view["related_queue_item_id"]
    assert (
        assessment["projected_activation_decision"].recommendation
        == readiness_view["projected_activation_decision"].recommendation
    )
    assert (
        assessment["projected_activation_decision"].escalation_destination
        == readiness_view["projected_activation_decision"].escalation_destination
    )
    assert (
        assessment["projected_activation_decision"].autonomous_continuation_status
        == readiness_view["projected_activation_decision"].autonomous_continuation_status
    )
    assert (
        assessment["approval_record"]["human_approval_status"]["status"]
        == readiness_view["approval_record"]["human_approval_status"]["status"]
    )


@pytest.mark.parametrize(
    ("decision", "user_request", "changed_areas"),
    COMPOSITION_PARITY_CASES,
)
def test_build_execution_readiness_signal_from_assessment_matches_assessment(
    decision: RecommendationValue,
    user_request: str,
    changed_areas: frozenset[str],
) -> None:
    management_decision = ManagementDecisionRecord(
        item_id="rq_execution_readiness_signal_parity_1",
        decision=decision,
        reviewer_id="manager-execution-readiness-signal",
        reviewer_type="human",
        rationale="Parity check for execution readiness signal helper.",
        approved_next_action="Escalate to audit and review before any continuation.",
    )
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=user_request,
            changed_areas=set(changed_areas),
            management_decision=management_decision,
        )
    )
    handoff_envelope = build_dry_run_handoff_envelope_from_result(
        orchestration_result=result,
        activation_review_item_id="activation_review_execution_readiness_signal_parity_1",
        approval_record_id="approval_record_execution_readiness_signal_parity_1",
        related_project_id="project_execution_readiness_signal_parity_1",
        related_activation_decision_id="activation_decision_execution_readiness_signal_parity_1",
        related_packet_id="packet_execution_readiness_signal_parity_1",
        related_queue_item_id="queue_execution_readiness_signal_parity_1",
    )
    intake = build_next_layer_intake_from_handoff_envelope(
        handoff_envelope=handoff_envelope
    )
    work_item = build_downstream_work_item_from_intake(next_layer_intake=intake)
    intent = build_downstream_execution_intent_from_work_item(
        downstream_work_item=work_item
    )
    readiness_view = build_execution_readiness_view_from_intent(
        downstream_execution_intent=intent
    )
    assessment = build_execution_readiness_assessment_from_view(
        execution_readiness_view=readiness_view
    )

    signal = build_execution_readiness_signal_from_assessment(
        execution_readiness_assessment=assessment
    )

    assert (
        signal["projected_activation_decision"]
        == assessment["projected_activation_decision"]
    )
    assert signal["approval_record"] == assessment["approval_record"]
    assert signal["related_project_id"] == assessment["related_project_id"]
    assert (
        signal["related_activation_decision_id"]
        == assessment["related_activation_decision_id"]
    )
    assert signal["related_packet_id"] == assessment["related_packet_id"]
    assert signal["related_queue_item_id"] == assessment["related_queue_item_id"]
    assert (
        signal["projected_activation_decision"].recommendation
        == assessment["projected_activation_decision"].recommendation
    )
    assert (
        signal["projected_activation_decision"].escalation_destination
        == assessment["projected_activation_decision"].escalation_destination
    )
    assert (
        signal["projected_activation_decision"].autonomous_continuation_status
        == assessment["projected_activation_decision"].autonomous_continuation_status
    )
    assert (
        signal["approval_record"]["human_approval_status"]["status"]
        == assessment["approval_record"]["human_approval_status"]["status"]
    )


@pytest.mark.parametrize(
    ("decision", "user_request", "changed_areas"),
    COMPOSITION_PARITY_CASES,
)
def test_build_execution_readiness_outcome_from_signal_matches_signal(
    decision: RecommendationValue,
    user_request: str,
    changed_areas: frozenset[str],
) -> None:
    management_decision = ManagementDecisionRecord(
        item_id="rq_execution_readiness_outcome_parity_1",
        decision=decision,
        reviewer_id="manager-execution-readiness-outcome",
        reviewer_type="human",
        rationale="Parity check for execution readiness outcome helper.",
        approved_next_action="Escalate to audit and review before any continuation.",
    )
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=user_request,
            changed_areas=set(changed_areas),
            management_decision=management_decision,
        )
    )
    handoff_envelope = build_dry_run_handoff_envelope_from_result(
        orchestration_result=result,
        activation_review_item_id="activation_review_execution_readiness_outcome_parity_1",
        approval_record_id="approval_record_execution_readiness_outcome_parity_1",
        related_project_id="project_execution_readiness_outcome_parity_1",
        related_activation_decision_id="activation_decision_execution_readiness_outcome_parity_1",
        related_packet_id="packet_execution_readiness_outcome_parity_1",
        related_queue_item_id="queue_execution_readiness_outcome_parity_1",
    )
    intake = build_next_layer_intake_from_handoff_envelope(
        handoff_envelope=handoff_envelope
    )
    work_item = build_downstream_work_item_from_intake(next_layer_intake=intake)
    intent = build_downstream_execution_intent_from_work_item(
        downstream_work_item=work_item
    )
    readiness_view = build_execution_readiness_view_from_intent(
        downstream_execution_intent=intent
    )
    assessment = build_execution_readiness_assessment_from_view(
        execution_readiness_view=readiness_view
    )
    signal = build_execution_readiness_signal_from_assessment(
        execution_readiness_assessment=assessment
    )

    outcome = build_execution_readiness_outcome_from_signal(
        execution_readiness_signal=signal
    )

    assert (
        outcome["projected_activation_decision"]
        == signal["projected_activation_decision"]
    )
    assert outcome["approval_record"] == signal["approval_record"]
    assert outcome["related_project_id"] == signal["related_project_id"]
    assert (
        outcome["related_activation_decision_id"]
        == signal["related_activation_decision_id"]
    )
    assert outcome["related_packet_id"] == signal["related_packet_id"]
    assert outcome["related_queue_item_id"] == signal["related_queue_item_id"]
    assert (
        outcome["projected_activation_decision"].recommendation
        == signal["projected_activation_decision"].recommendation
    )
    assert (
        outcome["projected_activation_decision"].escalation_destination
        == signal["projected_activation_decision"].escalation_destination
    )
    assert (
        outcome["projected_activation_decision"].autonomous_continuation_status
        == signal["projected_activation_decision"].autonomous_continuation_status
    )
    assert (
        outcome["approval_record"]["human_approval_status"]["status"]
        == signal["approval_record"]["human_approval_status"]["status"]
    )


@pytest.mark.parametrize(
    ("decision", "user_request", "changed_areas"),
    COMPOSITION_PARITY_CASES,
)
def test_build_downstream_consumer_payload_from_outcome_matches_outcome(
    decision: RecommendationValue,
    user_request: str,
    changed_areas: frozenset[str],
) -> None:
    management_decision = ManagementDecisionRecord(
        item_id="rq_downstream_consumer_payload_parity_1",
        decision=decision,
        reviewer_id="manager-downstream-consumer-payload",
        reviewer_type="human",
        rationale="Parity check for downstream consumer payload helper.",
        approved_next_action="Escalate to audit and review before any continuation.",
    )
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=user_request,
            changed_areas=set(changed_areas),
            management_decision=management_decision,
        )
    )
    handoff_envelope = build_dry_run_handoff_envelope_from_result(
        orchestration_result=result,
        activation_review_item_id="activation_review_downstream_consumer_payload_parity_1",
        approval_record_id="approval_record_downstream_consumer_payload_parity_1",
        related_project_id="project_downstream_consumer_payload_parity_1",
        related_activation_decision_id="activation_decision_downstream_consumer_payload_parity_1",
        related_packet_id="packet_downstream_consumer_payload_parity_1",
        related_queue_item_id="queue_downstream_consumer_payload_parity_1",
    )
    intake = build_next_layer_intake_from_handoff_envelope(
        handoff_envelope=handoff_envelope
    )
    work_item = build_downstream_work_item_from_intake(next_layer_intake=intake)
    intent = build_downstream_execution_intent_from_work_item(
        downstream_work_item=work_item
    )
    readiness_view = build_execution_readiness_view_from_intent(
        downstream_execution_intent=intent
    )
    assessment = build_execution_readiness_assessment_from_view(
        execution_readiness_view=readiness_view
    )
    signal = build_execution_readiness_signal_from_assessment(
        execution_readiness_assessment=assessment
    )
    outcome = build_execution_readiness_outcome_from_signal(
        execution_readiness_signal=signal
    )

    payload = build_downstream_consumer_payload_from_outcome(
        execution_readiness_outcome=outcome
    )

    assert payload["projected_activation_decision"] == outcome["projected_activation_decision"]
    assert payload["approval_record"] == outcome["approval_record"]
    assert payload["related_project_id"] == outcome["related_project_id"]
    assert (
        payload["related_activation_decision_id"] == outcome["related_activation_decision_id"]
    )
    assert payload["related_packet_id"] == outcome["related_packet_id"]
    assert payload["related_queue_item_id"] == outcome["related_queue_item_id"]
    assert (
        payload["projected_activation_decision"].recommendation
        == outcome["projected_activation_decision"].recommendation
    )
    assert (
        payload["projected_activation_decision"].escalation_destination
        == outcome["projected_activation_decision"].escalation_destination
    )
    assert (
        payload["projected_activation_decision"].autonomous_continuation_status
        == outcome["projected_activation_decision"].autonomous_continuation_status
    )
    assert (
        payload["approval_record"]["human_approval_status"]["status"]
        == outcome["approval_record"]["human_approval_status"]["status"]
    )


@pytest.mark.parametrize(
    ("decision", "user_request", "changed_areas"),
    COMPOSITION_PARITY_CASES,
)
def test_build_consumer_receiver_intake_from_payload_matches_payload(
    decision: RecommendationValue,
    user_request: str,
    changed_areas: frozenset[str],
) -> None:
    management_decision = ManagementDecisionRecord(
        item_id="rq_consumer_receiver_intake_parity_1",
        decision=decision,
        reviewer_id="manager-consumer-receiver-intake",
        reviewer_type="human",
        rationale="Parity check for consumer receiver intake helper.",
        approved_next_action="Escalate to audit and review before any continuation.",
    )
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=user_request,
            changed_areas=set(changed_areas),
            management_decision=management_decision,
        )
    )
    handoff_envelope = build_dry_run_handoff_envelope_from_result(
        orchestration_result=result,
        activation_review_item_id="activation_review_consumer_receiver_intake_parity_1",
        approval_record_id="approval_record_consumer_receiver_intake_parity_1",
        related_project_id="project_consumer_receiver_intake_parity_1",
        related_activation_decision_id="activation_decision_consumer_receiver_intake_parity_1",
        related_packet_id="packet_consumer_receiver_intake_parity_1",
        related_queue_item_id="queue_consumer_receiver_intake_parity_1",
    )
    intake = build_next_layer_intake_from_handoff_envelope(
        handoff_envelope=handoff_envelope
    )
    work_item = build_downstream_work_item_from_intake(next_layer_intake=intake)
    intent = build_downstream_execution_intent_from_work_item(
        downstream_work_item=work_item
    )
    readiness_view = build_execution_readiness_view_from_intent(
        downstream_execution_intent=intent
    )
    assessment = build_execution_readiness_assessment_from_view(
        execution_readiness_view=readiness_view
    )
    signal = build_execution_readiness_signal_from_assessment(
        execution_readiness_assessment=assessment
    )
    outcome = build_execution_readiness_outcome_from_signal(
        execution_readiness_signal=signal
    )
    payload = build_downstream_consumer_payload_from_outcome(
        execution_readiness_outcome=outcome
    )

    receiver_intake = build_consumer_receiver_intake_from_payload(
        downstream_consumer_payload=payload
    )

    assert (
        receiver_intake["projected_activation_decision"]
        == payload["projected_activation_decision"]
    )
    assert receiver_intake["approval_record"] == payload["approval_record"]
    assert receiver_intake["related_project_id"] == payload["related_project_id"]
    assert (
        receiver_intake["related_activation_decision_id"]
        == payload["related_activation_decision_id"]
    )
    assert receiver_intake["related_packet_id"] == payload["related_packet_id"]
    assert receiver_intake["related_queue_item_id"] == payload["related_queue_item_id"]
    assert (
        receiver_intake["projected_activation_decision"].recommendation
        == payload["projected_activation_decision"].recommendation
    )
    assert (
        receiver_intake["projected_activation_decision"].escalation_destination
        == payload["projected_activation_decision"].escalation_destination
    )
    assert (
        receiver_intake["projected_activation_decision"].autonomous_continuation_status
        == payload["projected_activation_decision"].autonomous_continuation_status
    )
    assert (
        receiver_intake["approval_record"]["human_approval_status"]["status"]
        == payload["approval_record"]["human_approval_status"]["status"]
    )


@pytest.mark.parametrize(
    ("decision", "user_request", "changed_areas"),
    COMPOSITION_PARITY_CASES,
)
def test_build_consumer_receiver_readiness_view_from_intake_matches_intake(
    decision: RecommendationValue,
    user_request: str,
    changed_areas: frozenset[str],
) -> None:
    management_decision = ManagementDecisionRecord(
        item_id="rq_consumer_receiver_readiness_view_parity_1",
        decision=decision,
        reviewer_id="manager-consumer-receiver-readiness-view",
        reviewer_type="human",
        rationale="Parity check for consumer receiver readiness view helper.",
        approved_next_action="Escalate to audit and review before any continuation.",
    )
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=user_request,
            changed_areas=set(changed_areas),
            management_decision=management_decision,
        )
    )
    handoff_envelope = build_dry_run_handoff_envelope_from_result(
        orchestration_result=result,
        activation_review_item_id="activation_review_consumer_receiver_readiness_view_parity_1",
        approval_record_id="approval_record_consumer_receiver_readiness_view_parity_1",
        related_project_id="project_consumer_receiver_readiness_view_parity_1",
        related_activation_decision_id=(
            "activation_decision_consumer_receiver_readiness_view_parity_1"
        ),
        related_packet_id="packet_consumer_receiver_readiness_view_parity_1",
        related_queue_item_id="queue_consumer_receiver_readiness_view_parity_1",
    )
    intake = build_next_layer_intake_from_handoff_envelope(
        handoff_envelope=handoff_envelope
    )
    work_item = build_downstream_work_item_from_intake(next_layer_intake=intake)
    intent = build_downstream_execution_intent_from_work_item(
        downstream_work_item=work_item
    )
    readiness_view = build_execution_readiness_view_from_intent(
        downstream_execution_intent=intent
    )
    assessment = build_execution_readiness_assessment_from_view(
        execution_readiness_view=readiness_view
    )
    signal = build_execution_readiness_signal_from_assessment(
        execution_readiness_assessment=assessment
    )
    outcome = build_execution_readiness_outcome_from_signal(
        execution_readiness_signal=signal
    )
    payload = build_downstream_consumer_payload_from_outcome(
        execution_readiness_outcome=outcome
    )
    receiver_intake = build_consumer_receiver_intake_from_payload(
        downstream_consumer_payload=payload
    )

    receiver_readiness_view = build_consumer_receiver_readiness_view_from_intake(
        consumer_receiver_intake=receiver_intake
    )

    assert (
        receiver_readiness_view["projected_activation_decision"]
        == receiver_intake["projected_activation_decision"]
    )
    assert receiver_readiness_view["approval_record"] == receiver_intake["approval_record"]
    assert receiver_readiness_view["related_project_id"] == receiver_intake["related_project_id"]
    assert (
        receiver_readiness_view["related_activation_decision_id"]
        == receiver_intake["related_activation_decision_id"]
    )
    assert receiver_readiness_view["related_packet_id"] == receiver_intake["related_packet_id"]
    assert (
        receiver_readiness_view["related_queue_item_id"]
        == receiver_intake["related_queue_item_id"]
    )
    assert (
        receiver_readiness_view["projected_activation_decision"].recommendation
        == receiver_intake["projected_activation_decision"].recommendation
    )
    assert (
        receiver_readiness_view["projected_activation_decision"].escalation_destination
        == receiver_intake["projected_activation_decision"].escalation_destination
    )
    assert (
        receiver_readiness_view["projected_activation_decision"].autonomous_continuation_status
        == receiver_intake["projected_activation_decision"].autonomous_continuation_status
    )
    assert (
        receiver_readiness_view["approval_record"]["human_approval_status"]["status"]
        == receiver_intake["approval_record"]["human_approval_status"]["status"]
    )


@pytest.mark.parametrize(
    ("decision", "user_request", "changed_areas"),
    COMPOSITION_PARITY_CASES,
)
def test_build_consumer_receiver_readiness_assessment_from_view_matches_view(
    decision: RecommendationValue,
    user_request: str,
    changed_areas: frozenset[str],
) -> None:
    management_decision = ManagementDecisionRecord(
        item_id="rq_consumer_receiver_readiness_assessment_parity_1",
        decision=decision,
        reviewer_id="manager-consumer-receiver-readiness-assessment",
        reviewer_type="human",
        rationale="Parity check for consumer receiver readiness assessment helper.",
        approved_next_action="Escalate to audit and review before any continuation.",
    )
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=user_request,
            changed_areas=set(changed_areas),
            management_decision=management_decision,
        )
    )
    handoff_envelope = build_dry_run_handoff_envelope_from_result(
        orchestration_result=result,
        activation_review_item_id=(
            "activation_review_consumer_receiver_readiness_assessment_parity_1"
        ),
        approval_record_id="approval_record_consumer_receiver_readiness_assessment_parity_1",
        related_project_id="project_consumer_receiver_readiness_assessment_parity_1",
        related_activation_decision_id=(
            "activation_decision_consumer_receiver_readiness_assessment_parity_1"
        ),
        related_packet_id="packet_consumer_receiver_readiness_assessment_parity_1",
        related_queue_item_id="queue_consumer_receiver_readiness_assessment_parity_1",
    )
    intake = build_next_layer_intake_from_handoff_envelope(
        handoff_envelope=handoff_envelope
    )
    work_item = build_downstream_work_item_from_intake(next_layer_intake=intake)
    intent = build_downstream_execution_intent_from_work_item(
        downstream_work_item=work_item
    )
    readiness_view = build_execution_readiness_view_from_intent(
        downstream_execution_intent=intent
    )
    assessment = build_execution_readiness_assessment_from_view(
        execution_readiness_view=readiness_view
    )
    signal = build_execution_readiness_signal_from_assessment(
        execution_readiness_assessment=assessment
    )
    outcome = build_execution_readiness_outcome_from_signal(
        execution_readiness_signal=signal
    )
    payload = build_downstream_consumer_payload_from_outcome(
        execution_readiness_outcome=outcome
    )
    receiver_intake = build_consumer_receiver_intake_from_payload(
        downstream_consumer_payload=payload
    )
    receiver_readiness_view = build_consumer_receiver_readiness_view_from_intake(
        consumer_receiver_intake=receiver_intake
    )

    receiver_readiness_assessment = build_consumer_receiver_readiness_assessment_from_view(
        consumer_receiver_readiness_view=receiver_readiness_view
    )

    assert (
        receiver_readiness_assessment["projected_activation_decision"]
        == receiver_readiness_view["projected_activation_decision"]
    )
    assert (
        receiver_readiness_assessment["approval_record"]
        == receiver_readiness_view["approval_record"]
    )
    assert (
        receiver_readiness_assessment["related_project_id"]
        == receiver_readiness_view["related_project_id"]
    )
    assert (
        receiver_readiness_assessment["related_activation_decision_id"]
        == receiver_readiness_view["related_activation_decision_id"]
    )
    assert (
        receiver_readiness_assessment["related_packet_id"]
        == receiver_readiness_view["related_packet_id"]
    )
    assert (
        receiver_readiness_assessment["related_queue_item_id"]
        == receiver_readiness_view["related_queue_item_id"]
    )
    assert (
        receiver_readiness_assessment["projected_activation_decision"].recommendation
        == receiver_readiness_view["projected_activation_decision"].recommendation
    )
    assert (
        receiver_readiness_assessment["projected_activation_decision"].escalation_destination
        == receiver_readiness_view["projected_activation_decision"].escalation_destination
    )
    assert (
        receiver_readiness_assessment[
            "projected_activation_decision"
        ].autonomous_continuation_status
        == receiver_readiness_view[
            "projected_activation_decision"
        ].autonomous_continuation_status
    )
    assert (
        receiver_readiness_assessment["approval_record"]["human_approval_status"]["status"]
        == receiver_readiness_view["approval_record"]["human_approval_status"]["status"]
    )


@pytest.mark.parametrize(
    ("decision", "user_request", "changed_areas"),
    COMPOSITION_PARITY_CASES,
)
def test_build_consumer_receiver_readiness_signal_from_assessment_matches_assessment(
    decision: RecommendationValue,
    user_request: str,
    changed_areas: frozenset[str],
) -> None:
    management_decision = ManagementDecisionRecord(
        item_id="rq_consumer_receiver_readiness_signal_parity_1",
        decision=decision,
        reviewer_id="manager-consumer-receiver-readiness-signal",
        reviewer_type="human",
        rationale="Parity check for consumer receiver readiness signal helper.",
        approved_next_action="Escalate to audit and review before any continuation.",
    )
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=user_request,
            changed_areas=set(changed_areas),
            management_decision=management_decision,
        )
    )
    handoff_envelope = build_dry_run_handoff_envelope_from_result(
        orchestration_result=result,
        activation_review_item_id=(
            "activation_review_consumer_receiver_readiness_signal_parity_1"
        ),
        approval_record_id="approval_record_consumer_receiver_readiness_signal_parity_1",
        related_project_id="project_consumer_receiver_readiness_signal_parity_1",
        related_activation_decision_id=(
            "activation_decision_consumer_receiver_readiness_signal_parity_1"
        ),
        related_packet_id="packet_consumer_receiver_readiness_signal_parity_1",
        related_queue_item_id="queue_consumer_receiver_readiness_signal_parity_1",
    )
    intake = build_next_layer_intake_from_handoff_envelope(
        handoff_envelope=handoff_envelope
    )
    work_item = build_downstream_work_item_from_intake(next_layer_intake=intake)
    intent = build_downstream_execution_intent_from_work_item(
        downstream_work_item=work_item
    )
    readiness_view = build_execution_readiness_view_from_intent(
        downstream_execution_intent=intent
    )
    assessment = build_execution_readiness_assessment_from_view(
        execution_readiness_view=readiness_view
    )
    signal = build_execution_readiness_signal_from_assessment(
        execution_readiness_assessment=assessment
    )
    outcome = build_execution_readiness_outcome_from_signal(
        execution_readiness_signal=signal
    )
    payload = build_downstream_consumer_payload_from_outcome(
        execution_readiness_outcome=outcome
    )
    receiver_intake = build_consumer_receiver_intake_from_payload(
        downstream_consumer_payload=payload
    )
    receiver_readiness_view = build_consumer_receiver_readiness_view_from_intake(
        consumer_receiver_intake=receiver_intake
    )
    receiver_readiness_assessment = build_consumer_receiver_readiness_assessment_from_view(
        consumer_receiver_readiness_view=receiver_readiness_view
    )

    receiver_readiness_signal = build_consumer_receiver_readiness_signal_from_assessment(
        consumer_receiver_readiness_assessment=receiver_readiness_assessment
    )

    assert (
        receiver_readiness_signal["projected_activation_decision"]
        == receiver_readiness_assessment["projected_activation_decision"]
    )
    assert (
        receiver_readiness_signal["approval_record"]
        == receiver_readiness_assessment["approval_record"]
    )
    assert (
        receiver_readiness_signal["related_project_id"]
        == receiver_readiness_assessment["related_project_id"]
    )
    assert (
        receiver_readiness_signal["related_activation_decision_id"]
        == receiver_readiness_assessment["related_activation_decision_id"]
    )
    assert (
        receiver_readiness_signal["related_packet_id"]
        == receiver_readiness_assessment["related_packet_id"]
    )
    assert (
        receiver_readiness_signal["related_queue_item_id"]
        == receiver_readiness_assessment["related_queue_item_id"]
    )
    assert (
        receiver_readiness_signal["projected_activation_decision"].recommendation
        == receiver_readiness_assessment["projected_activation_decision"].recommendation
    )
    assert (
        receiver_readiness_signal["projected_activation_decision"].escalation_destination
        == receiver_readiness_assessment["projected_activation_decision"].escalation_destination
    )
    assert (
        receiver_readiness_signal[
            "projected_activation_decision"
        ].autonomous_continuation_status
        == receiver_readiness_assessment[
            "projected_activation_decision"
        ].autonomous_continuation_status
    )
    assert (
        receiver_readiness_signal["approval_record"]["human_approval_status"]["status"]
        == receiver_readiness_assessment["approval_record"]["human_approval_status"]["status"]
    )


@pytest.mark.parametrize(
    ("decision", "user_request", "changed_areas"),
    COMPOSITION_PARITY_CASES,
)
def test_build_consumer_receiver_readiness_outcome_from_signal_matches_signal(
    decision: RecommendationValue,
    user_request: str,
    changed_areas: frozenset[str],
) -> None:
    management_decision = ManagementDecisionRecord(
        item_id="rq_consumer_receiver_readiness_outcome_parity_1",
        decision=decision,
        reviewer_id="manager-consumer-receiver-readiness-outcome",
        reviewer_type="human",
        rationale="Parity check for consumer receiver readiness outcome helper.",
        approved_next_action="Escalate to audit and review before any continuation.",
    )
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=user_request,
            changed_areas=set(changed_areas),
            management_decision=management_decision,
        )
    )
    handoff_envelope = build_dry_run_handoff_envelope_from_result(
        orchestration_result=result,
        activation_review_item_id=(
            "activation_review_consumer_receiver_readiness_outcome_parity_1"
        ),
        approval_record_id="approval_record_consumer_receiver_readiness_outcome_parity_1",
        related_project_id="project_consumer_receiver_readiness_outcome_parity_1",
        related_activation_decision_id=(
            "activation_decision_consumer_receiver_readiness_outcome_parity_1"
        ),
        related_packet_id="packet_consumer_receiver_readiness_outcome_parity_1",
        related_queue_item_id="queue_consumer_receiver_readiness_outcome_parity_1",
    )
    intake = build_next_layer_intake_from_handoff_envelope(
        handoff_envelope=handoff_envelope
    )
    work_item = build_downstream_work_item_from_intake(next_layer_intake=intake)
    intent = build_downstream_execution_intent_from_work_item(
        downstream_work_item=work_item
    )
    readiness_view = build_execution_readiness_view_from_intent(
        downstream_execution_intent=intent
    )
    assessment = build_execution_readiness_assessment_from_view(
        execution_readiness_view=readiness_view
    )
    signal = build_execution_readiness_signal_from_assessment(
        execution_readiness_assessment=assessment
    )
    outcome = build_execution_readiness_outcome_from_signal(
        execution_readiness_signal=signal
    )
    payload = build_downstream_consumer_payload_from_outcome(
        execution_readiness_outcome=outcome
    )
    receiver_intake = build_consumer_receiver_intake_from_payload(
        downstream_consumer_payload=payload
    )
    receiver_readiness_view = build_consumer_receiver_readiness_view_from_intake(
        consumer_receiver_intake=receiver_intake
    )
    receiver_readiness_assessment = build_consumer_receiver_readiness_assessment_from_view(
        consumer_receiver_readiness_view=receiver_readiness_view
    )
    receiver_readiness_signal = build_consumer_receiver_readiness_signal_from_assessment(
        consumer_receiver_readiness_assessment=receiver_readiness_assessment
    )

    receiver_readiness_outcome = build_consumer_receiver_readiness_outcome_from_signal(
        consumer_receiver_readiness_signal=receiver_readiness_signal
    )

    assert (
        receiver_readiness_outcome["projected_activation_decision"]
        == receiver_readiness_signal["projected_activation_decision"]
    )
    assert (
        receiver_readiness_outcome["approval_record"]
        == receiver_readiness_signal["approval_record"]
    )
    assert (
        receiver_readiness_outcome["related_project_id"]
        == receiver_readiness_signal["related_project_id"]
    )
    assert (
        receiver_readiness_outcome["related_activation_decision_id"]
        == receiver_readiness_signal["related_activation_decision_id"]
    )
    assert (
        receiver_readiness_outcome["related_packet_id"]
        == receiver_readiness_signal["related_packet_id"]
    )
    assert (
        receiver_readiness_outcome["related_queue_item_id"]
        == receiver_readiness_signal["related_queue_item_id"]
    )
    assert (
        receiver_readiness_outcome["projected_activation_decision"].recommendation
        == receiver_readiness_signal["projected_activation_decision"].recommendation
    )
    assert (
        receiver_readiness_outcome["projected_activation_decision"].escalation_destination
        == receiver_readiness_signal["projected_activation_decision"].escalation_destination
    )
    assert (
        receiver_readiness_outcome[
            "projected_activation_decision"
        ].autonomous_continuation_status
        == receiver_readiness_signal[
            "projected_activation_decision"
        ].autonomous_continuation_status
    )
    assert (
        receiver_readiness_outcome["approval_record"]["human_approval_status"]["status"]
        == receiver_readiness_signal["approval_record"]["human_approval_status"]["status"]
    )


@pytest.mark.parametrize(
    ("decision", "user_request", "changed_areas"),
    COMPOSITION_PARITY_CASES,
)
def test_build_consumer_receiver_delivery_payload_from_outcome_matches_outcome(
    decision: RecommendationValue,
    user_request: str,
    changed_areas: frozenset[str],
) -> None:
    management_decision = ManagementDecisionRecord(
        item_id="rq_consumer_receiver_delivery_payload_parity_1",
        decision=decision,
        reviewer_id="manager-consumer-receiver-delivery-payload",
        reviewer_type="human",
        rationale="Parity check for consumer receiver delivery payload helper.",
        approved_next_action="Escalate to audit and review before any continuation.",
    )
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=user_request,
            changed_areas=set(changed_areas),
            management_decision=management_decision,
        )
    )
    handoff_envelope = build_dry_run_handoff_envelope_from_result(
        orchestration_result=result,
        activation_review_item_id=(
            "activation_review_consumer_receiver_delivery_payload_parity_1"
        ),
        approval_record_id="approval_record_consumer_receiver_delivery_payload_parity_1",
        related_project_id="project_consumer_receiver_delivery_payload_parity_1",
        related_activation_decision_id=(
            "activation_decision_consumer_receiver_delivery_payload_parity_1"
        ),
        related_packet_id="packet_consumer_receiver_delivery_payload_parity_1",
        related_queue_item_id="queue_consumer_receiver_delivery_payload_parity_1",
    )
    intake = build_next_layer_intake_from_handoff_envelope(
        handoff_envelope=handoff_envelope
    )
    work_item = build_downstream_work_item_from_intake(next_layer_intake=intake)
    intent = build_downstream_execution_intent_from_work_item(
        downstream_work_item=work_item
    )
    readiness_view = build_execution_readiness_view_from_intent(
        downstream_execution_intent=intent
    )
    assessment = build_execution_readiness_assessment_from_view(
        execution_readiness_view=readiness_view
    )
    signal = build_execution_readiness_signal_from_assessment(
        execution_readiness_assessment=assessment
    )
    outcome = build_execution_readiness_outcome_from_signal(
        execution_readiness_signal=signal
    )
    payload = build_downstream_consumer_payload_from_outcome(
        execution_readiness_outcome=outcome
    )
    receiver_intake = build_consumer_receiver_intake_from_payload(
        downstream_consumer_payload=payload
    )
    receiver_readiness_view = build_consumer_receiver_readiness_view_from_intake(
        consumer_receiver_intake=receiver_intake
    )
    receiver_readiness_assessment = build_consumer_receiver_readiness_assessment_from_view(
        consumer_receiver_readiness_view=receiver_readiness_view
    )
    receiver_readiness_signal = build_consumer_receiver_readiness_signal_from_assessment(
        consumer_receiver_readiness_assessment=receiver_readiness_assessment
    )
    receiver_readiness_outcome = build_consumer_receiver_readiness_outcome_from_signal(
        consumer_receiver_readiness_signal=receiver_readiness_signal
    )

    receiver_delivery_payload = build_consumer_receiver_delivery_payload_from_outcome(
        consumer_receiver_readiness_outcome=receiver_readiness_outcome
    )

    assert (
        receiver_delivery_payload["projected_activation_decision"]
        == receiver_readiness_outcome["projected_activation_decision"]
    )
    assert (
        receiver_delivery_payload["approval_record"]
        == receiver_readiness_outcome["approval_record"]
    )
    assert (
        receiver_delivery_payload["related_project_id"]
        == receiver_readiness_outcome["related_project_id"]
    )
    assert (
        receiver_delivery_payload["related_activation_decision_id"]
        == receiver_readiness_outcome["related_activation_decision_id"]
    )
    assert (
        receiver_delivery_payload["related_packet_id"]
        == receiver_readiness_outcome["related_packet_id"]
    )
    assert (
        receiver_delivery_payload["related_queue_item_id"]
        == receiver_readiness_outcome["related_queue_item_id"]
    )
    assert (
        receiver_delivery_payload["projected_activation_decision"].recommendation
        == receiver_readiness_outcome["projected_activation_decision"].recommendation
    )
    assert (
        receiver_delivery_payload["projected_activation_decision"].escalation_destination
        == receiver_readiness_outcome["projected_activation_decision"].escalation_destination
    )
    assert (
        receiver_delivery_payload[
            "projected_activation_decision"
        ].autonomous_continuation_status
        == receiver_readiness_outcome[
            "projected_activation_decision"
        ].autonomous_continuation_status
    )
    assert (
        receiver_delivery_payload["approval_record"]["human_approval_status"]["status"]
        == receiver_readiness_outcome["approval_record"]["human_approval_status"]["status"]
    )


@pytest.mark.parametrize(
    ("decision", "user_request", "changed_areas"),
    COMPOSITION_PARITY_CASES,
)
def test_build_consumer_receiver_delivery_packet_from_payload_matches_payload(
    decision: RecommendationValue,
    user_request: str,
    changed_areas: frozenset[str],
) -> None:
    management_decision = ManagementDecisionRecord(
        item_id="rq_consumer_receiver_delivery_packet_parity_1",
        decision=decision,
        reviewer_id="manager-consumer-receiver-delivery-packet",
        reviewer_type="human",
        rationale="Parity check for consumer receiver delivery packet helper.",
        approved_next_action="Escalate to audit and review before any continuation.",
    )
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=user_request,
            changed_areas=set(changed_areas),
            management_decision=management_decision,
        )
    )
    handoff_envelope = build_dry_run_handoff_envelope_from_result(
        orchestration_result=result,
        activation_review_item_id=(
            "activation_review_consumer_receiver_delivery_packet_parity_1"
        ),
        approval_record_id="approval_record_consumer_receiver_delivery_packet_parity_1",
        related_project_id="project_consumer_receiver_delivery_packet_parity_1",
        related_activation_decision_id=(
            "activation_decision_consumer_receiver_delivery_packet_parity_1"
        ),
        related_packet_id="packet_consumer_receiver_delivery_packet_parity_1",
        related_queue_item_id="queue_consumer_receiver_delivery_packet_parity_1",
    )
    intake = build_next_layer_intake_from_handoff_envelope(
        handoff_envelope=handoff_envelope
    )
    work_item = build_downstream_work_item_from_intake(next_layer_intake=intake)
    intent = build_downstream_execution_intent_from_work_item(
        downstream_work_item=work_item
    )
    readiness_view = build_execution_readiness_view_from_intent(
        downstream_execution_intent=intent
    )
    assessment = build_execution_readiness_assessment_from_view(
        execution_readiness_view=readiness_view
    )
    signal = build_execution_readiness_signal_from_assessment(
        execution_readiness_assessment=assessment
    )
    outcome = build_execution_readiness_outcome_from_signal(
        execution_readiness_signal=signal
    )
    payload = build_downstream_consumer_payload_from_outcome(
        execution_readiness_outcome=outcome
    )
    receiver_intake = build_consumer_receiver_intake_from_payload(
        downstream_consumer_payload=payload
    )
    receiver_readiness_view = build_consumer_receiver_readiness_view_from_intake(
        consumer_receiver_intake=receiver_intake
    )
    receiver_readiness_assessment = build_consumer_receiver_readiness_assessment_from_view(
        consumer_receiver_readiness_view=receiver_readiness_view
    )
    receiver_readiness_signal = build_consumer_receiver_readiness_signal_from_assessment(
        consumer_receiver_readiness_assessment=receiver_readiness_assessment
    )
    receiver_readiness_outcome = build_consumer_receiver_readiness_outcome_from_signal(
        consumer_receiver_readiness_signal=receiver_readiness_signal
    )
    receiver_delivery_payload = build_consumer_receiver_delivery_payload_from_outcome(
        consumer_receiver_readiness_outcome=receiver_readiness_outcome
    )

    receiver_delivery_packet = build_consumer_receiver_delivery_packet_from_payload(
        consumer_receiver_delivery_payload=receiver_delivery_payload
    )

    assert (
        receiver_delivery_packet["projected_activation_decision"]
        == receiver_delivery_payload["projected_activation_decision"]
    )
    assert (
        receiver_delivery_packet["approval_record"]
        == receiver_delivery_payload["approval_record"]
    )
    assert (
        receiver_delivery_packet["related_project_id"]
        == receiver_delivery_payload["related_project_id"]
    )
    assert (
        receiver_delivery_packet["related_activation_decision_id"]
        == receiver_delivery_payload["related_activation_decision_id"]
    )
    assert (
        receiver_delivery_packet["related_packet_id"]
        == receiver_delivery_payload["related_packet_id"]
    )
    assert (
        receiver_delivery_packet["related_queue_item_id"]
        == receiver_delivery_payload["related_queue_item_id"]
    )
    assert (
        receiver_delivery_packet["projected_activation_decision"].recommendation
        == receiver_delivery_payload["projected_activation_decision"].recommendation
    )
    assert (
        receiver_delivery_packet["projected_activation_decision"].escalation_destination
        == receiver_delivery_payload["projected_activation_decision"].escalation_destination
    )
    assert (
        receiver_delivery_packet[
            "projected_activation_decision"
        ].autonomous_continuation_status
        == receiver_delivery_payload[
            "projected_activation_decision"
        ].autonomous_continuation_status
    )
    assert (
        receiver_delivery_packet["approval_record"]["human_approval_status"]["status"]
        == receiver_delivery_payload["approval_record"]["human_approval_status"]["status"]
    )


@pytest.mark.parametrize(
    ("decision", "user_request", "changed_areas"),
    COMPOSITION_PARITY_CASES,
)
def test_build_consumer_receiver_delivery_manifest_from_packet_matches_packet(
    decision: RecommendationValue,
    user_request: str,
    changed_areas: frozenset[str],
) -> None:
    management_decision = ManagementDecisionRecord(
        item_id="rq_consumer_receiver_delivery_manifest_parity_1",
        decision=decision,
        reviewer_id="manager-consumer-receiver-delivery-manifest",
        reviewer_type="human",
        rationale="Parity check for consumer receiver delivery manifest helper.",
        approved_next_action="Escalate to audit and review before any continuation.",
    )
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=user_request,
            changed_areas=set(changed_areas),
            management_decision=management_decision,
        )
    )
    handoff_envelope = build_dry_run_handoff_envelope_from_result(
        orchestration_result=result,
        activation_review_item_id=(
            "activation_review_consumer_receiver_delivery_manifest_parity_1"
        ),
        approval_record_id="approval_record_consumer_receiver_delivery_manifest_parity_1",
        related_project_id="project_consumer_receiver_delivery_manifest_parity_1",
        related_activation_decision_id=(
            "activation_decision_consumer_receiver_delivery_manifest_parity_1"
        ),
        related_packet_id="packet_consumer_receiver_delivery_manifest_parity_1",
        related_queue_item_id="queue_consumer_receiver_delivery_manifest_parity_1",
    )
    intake = build_next_layer_intake_from_handoff_envelope(
        handoff_envelope=handoff_envelope
    )
    work_item = build_downstream_work_item_from_intake(next_layer_intake=intake)
    intent = build_downstream_execution_intent_from_work_item(
        downstream_work_item=work_item
    )
    readiness_view = build_execution_readiness_view_from_intent(
        downstream_execution_intent=intent
    )
    assessment = build_execution_readiness_assessment_from_view(
        execution_readiness_view=readiness_view
    )
    signal = build_execution_readiness_signal_from_assessment(
        execution_readiness_assessment=assessment
    )
    outcome = build_execution_readiness_outcome_from_signal(
        execution_readiness_signal=signal
    )
    payload = build_downstream_consumer_payload_from_outcome(
        execution_readiness_outcome=outcome
    )
    receiver_intake = build_consumer_receiver_intake_from_payload(
        downstream_consumer_payload=payload
    )
    receiver_readiness_view = build_consumer_receiver_readiness_view_from_intake(
        consumer_receiver_intake=receiver_intake
    )
    receiver_readiness_assessment = build_consumer_receiver_readiness_assessment_from_view(
        consumer_receiver_readiness_view=receiver_readiness_view
    )
    receiver_readiness_signal = build_consumer_receiver_readiness_signal_from_assessment(
        consumer_receiver_readiness_assessment=receiver_readiness_assessment
    )
    receiver_readiness_outcome = build_consumer_receiver_readiness_outcome_from_signal(
        consumer_receiver_readiness_signal=receiver_readiness_signal
    )
    receiver_delivery_payload = build_consumer_receiver_delivery_payload_from_outcome(
        consumer_receiver_readiness_outcome=receiver_readiness_outcome
    )
    receiver_delivery_packet = build_consumer_receiver_delivery_packet_from_payload(
        consumer_receiver_delivery_payload=receiver_delivery_payload
    )

    receiver_delivery_manifest = build_consumer_receiver_delivery_manifest_from_packet(
        consumer_receiver_delivery_packet=receiver_delivery_packet
    )

    assert (
        receiver_delivery_manifest["projected_activation_decision"]
        == receiver_delivery_packet["projected_activation_decision"]
    )
    assert (
        receiver_delivery_manifest["approval_record"]
        == receiver_delivery_packet["approval_record"]
    )
    assert (
        receiver_delivery_manifest["related_project_id"]
        == receiver_delivery_packet["related_project_id"]
    )
    assert (
        receiver_delivery_manifest["related_activation_decision_id"]
        == receiver_delivery_packet["related_activation_decision_id"]
    )
    assert (
        receiver_delivery_manifest["related_packet_id"]
        == receiver_delivery_packet["related_packet_id"]
    )
    assert (
        receiver_delivery_manifest["related_queue_item_id"]
        == receiver_delivery_packet["related_queue_item_id"]
    )
    assert (
        receiver_delivery_manifest["projected_activation_decision"].recommendation
        == receiver_delivery_packet["projected_activation_decision"].recommendation
    )
    assert (
        receiver_delivery_manifest["projected_activation_decision"].escalation_destination
        == receiver_delivery_packet["projected_activation_decision"].escalation_destination
    )
    assert (
        receiver_delivery_manifest[
            "projected_activation_decision"
        ].autonomous_continuation_status
        == receiver_delivery_packet[
            "projected_activation_decision"
        ].autonomous_continuation_status
    )
    assert (
        receiver_delivery_manifest["approval_record"]["human_approval_status"]["status"]
        == receiver_delivery_packet["approval_record"]["human_approval_status"]["status"]
    )


@pytest.mark.parametrize(
    ("decision", "user_request", "changed_areas"),
    COMPOSITION_PARITY_CASES,
)
def test_build_consumer_receiver_readiness_classification_from_manifest_matches_manifest(
    decision: RecommendationValue,
    user_request: str,
    changed_areas: frozenset[str],
) -> None:
    expected_classification = {
        "GO": "ready",
        "PAUSE": "hold",
        "REVIEW": "needs_review",
    }[decision]
    management_decision = ManagementDecisionRecord(
        item_id="rq_consumer_receiver_readiness_classification_parity_1",
        decision=decision,
        reviewer_id="manager-consumer-receiver-readiness-classification",
        reviewer_type="human",
        rationale="Parity check for consumer receiver readiness classification helper.",
        approved_next_action="Escalate to audit and review before any continuation.",
    )
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=user_request,
            changed_areas=set(changed_areas),
            management_decision=management_decision,
        )
    )
    handoff_envelope = build_dry_run_handoff_envelope_from_result(
        orchestration_result=result,
        activation_review_item_id=(
            "activation_review_consumer_receiver_readiness_classification_parity_1"
        ),
        approval_record_id=(
            "approval_record_consumer_receiver_readiness_classification_parity_1"
        ),
        related_project_id="project_consumer_receiver_readiness_classification_parity_1",
        related_activation_decision_id=(
            "activation_decision_consumer_receiver_readiness_classification_parity_1"
        ),
        related_packet_id="packet_consumer_receiver_readiness_classification_parity_1",
        related_queue_item_id="queue_consumer_receiver_readiness_classification_parity_1",
    )
    intake = build_next_layer_intake_from_handoff_envelope(
        handoff_envelope=handoff_envelope
    )
    work_item = build_downstream_work_item_from_intake(next_layer_intake=intake)
    intent = build_downstream_execution_intent_from_work_item(
        downstream_work_item=work_item
    )
    readiness_view = build_execution_readiness_view_from_intent(
        downstream_execution_intent=intent
    )
    assessment = build_execution_readiness_assessment_from_view(
        execution_readiness_view=readiness_view
    )
    signal = build_execution_readiness_signal_from_assessment(
        execution_readiness_assessment=assessment
    )
    outcome = build_execution_readiness_outcome_from_signal(
        execution_readiness_signal=signal
    )
    payload = build_downstream_consumer_payload_from_outcome(
        execution_readiness_outcome=outcome
    )
    receiver_intake = build_consumer_receiver_intake_from_payload(
        downstream_consumer_payload=payload
    )
    receiver_readiness_view = build_consumer_receiver_readiness_view_from_intake(
        consumer_receiver_intake=receiver_intake
    )
    receiver_readiness_assessment = build_consumer_receiver_readiness_assessment_from_view(
        consumer_receiver_readiness_view=receiver_readiness_view
    )
    receiver_readiness_signal = build_consumer_receiver_readiness_signal_from_assessment(
        consumer_receiver_readiness_assessment=receiver_readiness_assessment
    )
    receiver_readiness_outcome = build_consumer_receiver_readiness_outcome_from_signal(
        consumer_receiver_readiness_signal=receiver_readiness_signal
    )
    receiver_delivery_payload = build_consumer_receiver_delivery_payload_from_outcome(
        consumer_receiver_readiness_outcome=receiver_readiness_outcome
    )
    receiver_delivery_packet = build_consumer_receiver_delivery_packet_from_payload(
        consumer_receiver_delivery_payload=receiver_delivery_payload
    )
    receiver_delivery_manifest = build_consumer_receiver_delivery_manifest_from_packet(
        consumer_receiver_delivery_packet=receiver_delivery_packet
    )

    receiver_readiness_classification = (
        build_consumer_receiver_readiness_classification_from_manifest(
            consumer_receiver_delivery_manifest=receiver_delivery_manifest
        )
    )

    assert (
        receiver_readiness_classification["projected_activation_decision"]
        == receiver_delivery_manifest["projected_activation_decision"]
    )
    assert (
        receiver_readiness_classification["approval_record"]
        == receiver_delivery_manifest["approval_record"]
    )
    assert (
        receiver_readiness_classification["related_project_id"]
        == receiver_delivery_manifest["related_project_id"]
    )
    assert (
        receiver_readiness_classification["related_activation_decision_id"]
        == receiver_delivery_manifest["related_activation_decision_id"]
    )
    assert (
        receiver_readiness_classification["related_packet_id"]
        == receiver_delivery_manifest["related_packet_id"]
    )
    assert (
        receiver_readiness_classification["related_queue_item_id"]
        == receiver_delivery_manifest["related_queue_item_id"]
    )
    assert (
        receiver_readiness_classification[
            "receiver_readiness_classification"
        ]
        == expected_classification
    )
    assert (
        receiver_readiness_classification["projected_activation_decision"].recommendation
        == receiver_delivery_manifest["projected_activation_decision"].recommendation
    )
    assert (
        receiver_readiness_classification[
            "projected_activation_decision"
        ].escalation_destination
        == receiver_delivery_manifest["projected_activation_decision"].escalation_destination
    )
    assert (
        receiver_readiness_classification[
            "projected_activation_decision"
        ].autonomous_continuation_status
        == receiver_delivery_manifest[
            "projected_activation_decision"
        ].autonomous_continuation_status
    )
    assert (
        receiver_readiness_classification["approval_record"]["human_approval_status"]["status"]
        == receiver_delivery_manifest["approval_record"]["human_approval_status"]["status"]
    )


@pytest.mark.parametrize(
    ("decision", "user_request", "changed_areas"),
    COMPOSITION_PARITY_CASES,
)
def test_build_consumer_receiver_handling_directive_from_classification_matches_classification(
    decision: RecommendationValue,
    user_request: str,
    changed_areas: frozenset[str],
) -> None:
    expected_classification = {
        "GO": "ready",
        "PAUSE": "hold",
        "REVIEW": "needs_review",
    }[decision]
    expected_handling_directive = {
        "ready": "deliver",
        "hold": "defer",
        "needs_review": "route_for_review",
    }[expected_classification]
    management_decision = ManagementDecisionRecord(
        item_id="rq_consumer_receiver_handling_directive_parity_1",
        decision=decision,
        reviewer_id="manager-consumer-receiver-handling-directive",
        reviewer_type="human",
        rationale="Parity check for consumer receiver handling directive helper.",
        approved_next_action="Escalate to audit and review before any continuation.",
    )
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=user_request,
            changed_areas=set(changed_areas),
            management_decision=management_decision,
        )
    )
    handoff_envelope = build_dry_run_handoff_envelope_from_result(
        orchestration_result=result,
        activation_review_item_id=(
            "activation_review_consumer_receiver_handling_directive_parity_1"
        ),
        approval_record_id=(
            "approval_record_consumer_receiver_handling_directive_parity_1"
        ),
        related_project_id="project_consumer_receiver_handling_directive_parity_1",
        related_activation_decision_id=(
            "activation_decision_consumer_receiver_handling_directive_parity_1"
        ),
        related_packet_id="packet_consumer_receiver_handling_directive_parity_1",
        related_queue_item_id="queue_consumer_receiver_handling_directive_parity_1",
    )
    intake = build_next_layer_intake_from_handoff_envelope(
        handoff_envelope=handoff_envelope
    )
    work_item = build_downstream_work_item_from_intake(next_layer_intake=intake)
    intent = build_downstream_execution_intent_from_work_item(
        downstream_work_item=work_item
    )
    readiness_view = build_execution_readiness_view_from_intent(
        downstream_execution_intent=intent
    )
    assessment = build_execution_readiness_assessment_from_view(
        execution_readiness_view=readiness_view
    )
    signal = build_execution_readiness_signal_from_assessment(
        execution_readiness_assessment=assessment
    )
    outcome = build_execution_readiness_outcome_from_signal(
        execution_readiness_signal=signal
    )
    payload = build_downstream_consumer_payload_from_outcome(
        execution_readiness_outcome=outcome
    )
    receiver_intake = build_consumer_receiver_intake_from_payload(
        downstream_consumer_payload=payload
    )
    receiver_readiness_view = build_consumer_receiver_readiness_view_from_intake(
        consumer_receiver_intake=receiver_intake
    )
    receiver_readiness_assessment = build_consumer_receiver_readiness_assessment_from_view(
        consumer_receiver_readiness_view=receiver_readiness_view
    )
    receiver_readiness_signal = build_consumer_receiver_readiness_signal_from_assessment(
        consumer_receiver_readiness_assessment=receiver_readiness_assessment
    )
    receiver_readiness_outcome = build_consumer_receiver_readiness_outcome_from_signal(
        consumer_receiver_readiness_signal=receiver_readiness_signal
    )
    receiver_delivery_payload = build_consumer_receiver_delivery_payload_from_outcome(
        consumer_receiver_readiness_outcome=receiver_readiness_outcome
    )
    receiver_delivery_packet = build_consumer_receiver_delivery_packet_from_payload(
        consumer_receiver_delivery_payload=receiver_delivery_payload
    )
    receiver_delivery_manifest = build_consumer_receiver_delivery_manifest_from_packet(
        consumer_receiver_delivery_packet=receiver_delivery_packet
    )
    receiver_readiness_classification = (
        build_consumer_receiver_readiness_classification_from_manifest(
            consumer_receiver_delivery_manifest=receiver_delivery_manifest
        )
    )

    receiver_handling_directive = (
        build_consumer_receiver_handling_directive_from_classification(
            consumer_receiver_readiness_classification=receiver_readiness_classification
        )
    )

    assert (
        receiver_handling_directive["projected_activation_decision"]
        == receiver_readiness_classification["projected_activation_decision"]
    )
    assert (
        receiver_handling_directive["approval_record"]
        == receiver_readiness_classification["approval_record"]
    )
    assert (
        receiver_handling_directive["receiver_readiness_classification"]
        == receiver_readiness_classification["receiver_readiness_classification"]
    )
    assert (
        receiver_handling_directive["related_project_id"]
        == receiver_readiness_classification["related_project_id"]
    )
    assert (
        receiver_handling_directive["related_activation_decision_id"]
        == receiver_readiness_classification["related_activation_decision_id"]
    )
    assert (
        receiver_handling_directive["related_packet_id"]
        == receiver_readiness_classification["related_packet_id"]
    )
    assert (
        receiver_handling_directive["related_queue_item_id"]
        == receiver_readiness_classification["related_queue_item_id"]
    )
    assert (
        receiver_handling_directive["receiver_readiness_classification"]
        == expected_classification
    )
    assert (
        receiver_handling_directive["receiver_handling_directive"]
        == expected_handling_directive
    )


@pytest.mark.parametrize(
    ("decision", "user_request", "changed_areas"),
    COMPOSITION_PARITY_CASES,
)
def test_build_consumer_receiver_action_label_from_directive_matches_directive(
    decision: RecommendationValue,
    user_request: str,
    changed_areas: frozenset[str],
) -> None:
    expected_classification = {
        "GO": "ready",
        "PAUSE": "hold",
        "REVIEW": "needs_review",
    }[decision]
    expected_handling_directive = {
        "ready": "deliver",
        "hold": "defer",
        "needs_review": "route_for_review",
    }[expected_classification]
    expected_action_label = {
        "deliver": "dispatch",
        "defer": "wait",
        "route_for_review": "review_queue",
    }[expected_handling_directive]
    management_decision = ManagementDecisionRecord(
        item_id="rq_consumer_receiver_action_label_parity_1",
        decision=decision,
        reviewer_id="manager-consumer-receiver-action-label",
        reviewer_type="human",
        rationale="Parity check for consumer receiver action label helper.",
        approved_next_action="Escalate to audit and review before any continuation.",
    )
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=user_request,
            changed_areas=set(changed_areas),
            management_decision=management_decision,
        )
    )
    handoff_envelope = build_dry_run_handoff_envelope_from_result(
        orchestration_result=result,
        activation_review_item_id=(
            "activation_review_consumer_receiver_action_label_parity_1"
        ),
        approval_record_id="approval_record_consumer_receiver_action_label_parity_1",
        related_project_id="project_consumer_receiver_action_label_parity_1",
        related_activation_decision_id=(
            "activation_decision_consumer_receiver_action_label_parity_1"
        ),
        related_packet_id="packet_consumer_receiver_action_label_parity_1",
        related_queue_item_id="queue_consumer_receiver_action_label_parity_1",
    )
    intake = build_next_layer_intake_from_handoff_envelope(
        handoff_envelope=handoff_envelope
    )
    work_item = build_downstream_work_item_from_intake(next_layer_intake=intake)
    intent = build_downstream_execution_intent_from_work_item(
        downstream_work_item=work_item
    )
    readiness_view = build_execution_readiness_view_from_intent(
        downstream_execution_intent=intent
    )
    assessment = build_execution_readiness_assessment_from_view(
        execution_readiness_view=readiness_view
    )
    signal = build_execution_readiness_signal_from_assessment(
        execution_readiness_assessment=assessment
    )
    outcome = build_execution_readiness_outcome_from_signal(
        execution_readiness_signal=signal
    )
    payload = build_downstream_consumer_payload_from_outcome(
        execution_readiness_outcome=outcome
    )
    receiver_intake = build_consumer_receiver_intake_from_payload(
        downstream_consumer_payload=payload
    )
    receiver_readiness_view = build_consumer_receiver_readiness_view_from_intake(
        consumer_receiver_intake=receiver_intake
    )
    receiver_readiness_assessment = build_consumer_receiver_readiness_assessment_from_view(
        consumer_receiver_readiness_view=receiver_readiness_view
    )
    receiver_readiness_signal = build_consumer_receiver_readiness_signal_from_assessment(
        consumer_receiver_readiness_assessment=receiver_readiness_assessment
    )
    receiver_readiness_outcome = build_consumer_receiver_readiness_outcome_from_signal(
        consumer_receiver_readiness_signal=receiver_readiness_signal
    )
    receiver_delivery_payload = build_consumer_receiver_delivery_payload_from_outcome(
        consumer_receiver_readiness_outcome=receiver_readiness_outcome
    )
    receiver_delivery_packet = build_consumer_receiver_delivery_packet_from_payload(
        consumer_receiver_delivery_payload=receiver_delivery_payload
    )
    receiver_delivery_manifest = build_consumer_receiver_delivery_manifest_from_packet(
        consumer_receiver_delivery_packet=receiver_delivery_packet
    )
    receiver_readiness_classification = (
        build_consumer_receiver_readiness_classification_from_manifest(
            consumer_receiver_delivery_manifest=receiver_delivery_manifest
        )
    )
    receiver_handling_directive = (
        build_consumer_receiver_handling_directive_from_classification(
            consumer_receiver_readiness_classification=receiver_readiness_classification
        )
    )

    receiver_action_label = build_consumer_receiver_action_label_from_directive(
        consumer_receiver_handling_directive=receiver_handling_directive
    )

    assert (
        receiver_action_label["projected_activation_decision"]
        == receiver_handling_directive["projected_activation_decision"]
    )
    assert (
        receiver_action_label["approval_record"]
        == receiver_handling_directive["approval_record"]
    )
    assert (
        receiver_action_label["receiver_readiness_classification"]
        == receiver_handling_directive["receiver_readiness_classification"]
    )
    assert (
        receiver_action_label["receiver_handling_directive"]
        == receiver_handling_directive["receiver_handling_directive"]
    )
    assert (
        receiver_action_label["related_project_id"]
        == receiver_handling_directive["related_project_id"]
    )
    assert (
        receiver_action_label["related_activation_decision_id"]
        == receiver_handling_directive["related_activation_decision_id"]
    )
    assert (
        receiver_action_label["related_packet_id"]
        == receiver_handling_directive["related_packet_id"]
    )
    assert (
        receiver_action_label["related_queue_item_id"]
        == receiver_handling_directive["related_queue_item_id"]
    )
    assert (
        receiver_action_label["receiver_readiness_classification"]
        == expected_classification
    )
    assert (
        receiver_action_label["receiver_handling_directive"]
        == expected_handling_directive
    )
    assert receiver_action_label["receiver_action_label"] == expected_action_label


@pytest.mark.parametrize(
    ("decision", "user_request", "changed_areas"),
    COMPOSITION_PARITY_CASES,
)
def test_build_consumer_receiver_dispatch_intent_from_action_label_matches_action_label(
    decision: RecommendationValue,
    user_request: str,
    changed_areas: frozenset[str],
) -> None:
    expected_classification = {
        "GO": "ready",
        "PAUSE": "hold",
        "REVIEW": "needs_review",
    }[decision]
    expected_handling_directive = {
        "ready": "deliver",
        "hold": "defer",
        "needs_review": "route_for_review",
    }[expected_classification]
    expected_action_label = {
        "deliver": "dispatch",
        "defer": "wait",
        "route_for_review": "review_queue",
    }[expected_handling_directive]
    expected_dispatch_intent = {
        "dispatch": "send",
        "wait": "park",
        "review_queue": "review",
    }[expected_action_label]
    management_decision = ManagementDecisionRecord(
        item_id="rq_consumer_receiver_dispatch_intent_parity_1",
        decision=decision,
        reviewer_id="manager-consumer-receiver-dispatch-intent",
        reviewer_type="human",
        rationale="Parity check for consumer receiver dispatch intent helper.",
        approved_next_action="Escalate to audit and review before any continuation.",
    )
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=user_request,
            changed_areas=set(changed_areas),
            management_decision=management_decision,
        )
    )
    handoff_envelope = build_dry_run_handoff_envelope_from_result(
        orchestration_result=result,
        activation_review_item_id=(
            "activation_review_consumer_receiver_dispatch_intent_parity_1"
        ),
        approval_record_id="approval_record_consumer_receiver_dispatch_intent_parity_1",
        related_project_id="project_consumer_receiver_dispatch_intent_parity_1",
        related_activation_decision_id=(
            "activation_decision_consumer_receiver_dispatch_intent_parity_1"
        ),
        related_packet_id="packet_consumer_receiver_dispatch_intent_parity_1",
        related_queue_item_id="queue_consumer_receiver_dispatch_intent_parity_1",
    )
    intake = build_next_layer_intake_from_handoff_envelope(
        handoff_envelope=handoff_envelope
    )
    work_item = build_downstream_work_item_from_intake(next_layer_intake=intake)
    intent = build_downstream_execution_intent_from_work_item(
        downstream_work_item=work_item
    )
    readiness_view = build_execution_readiness_view_from_intent(
        downstream_execution_intent=intent
    )
    assessment = build_execution_readiness_assessment_from_view(
        execution_readiness_view=readiness_view
    )
    signal = build_execution_readiness_signal_from_assessment(
        execution_readiness_assessment=assessment
    )
    outcome = build_execution_readiness_outcome_from_signal(
        execution_readiness_signal=signal
    )
    payload = build_downstream_consumer_payload_from_outcome(
        execution_readiness_outcome=outcome
    )
    receiver_intake = build_consumer_receiver_intake_from_payload(
        downstream_consumer_payload=payload
    )
    receiver_readiness_view = build_consumer_receiver_readiness_view_from_intake(
        consumer_receiver_intake=receiver_intake
    )
    receiver_readiness_assessment = build_consumer_receiver_readiness_assessment_from_view(
        consumer_receiver_readiness_view=receiver_readiness_view
    )
    receiver_readiness_signal = build_consumer_receiver_readiness_signal_from_assessment(
        consumer_receiver_readiness_assessment=receiver_readiness_assessment
    )
    receiver_readiness_outcome = build_consumer_receiver_readiness_outcome_from_signal(
        consumer_receiver_readiness_signal=receiver_readiness_signal
    )
    receiver_delivery_payload = build_consumer_receiver_delivery_payload_from_outcome(
        consumer_receiver_readiness_outcome=receiver_readiness_outcome
    )
    receiver_delivery_packet = build_consumer_receiver_delivery_packet_from_payload(
        consumer_receiver_delivery_payload=receiver_delivery_payload
    )
    receiver_delivery_manifest = build_consumer_receiver_delivery_manifest_from_packet(
        consumer_receiver_delivery_packet=receiver_delivery_packet
    )
    receiver_readiness_classification = (
        build_consumer_receiver_readiness_classification_from_manifest(
            consumer_receiver_delivery_manifest=receiver_delivery_manifest
        )
    )
    receiver_handling_directive = (
        build_consumer_receiver_handling_directive_from_classification(
            consumer_receiver_readiness_classification=receiver_readiness_classification
        )
    )
    receiver_action_label = build_consumer_receiver_action_label_from_directive(
        consumer_receiver_handling_directive=receiver_handling_directive
    )

    receiver_dispatch_intent = build_consumer_receiver_dispatch_intent_from_action_label(
        consumer_receiver_action_label=receiver_action_label
    )

    assert (
        receiver_dispatch_intent["projected_activation_decision"]
        == receiver_action_label["projected_activation_decision"]
    )
    assert receiver_dispatch_intent["approval_record"] == receiver_action_label["approval_record"]
    assert (
        receiver_dispatch_intent["receiver_readiness_classification"]
        == receiver_action_label["receiver_readiness_classification"]
    )
    assert (
        receiver_dispatch_intent["receiver_handling_directive"]
        == receiver_action_label["receiver_handling_directive"]
    )
    assert (
        receiver_dispatch_intent["receiver_action_label"]
        == receiver_action_label["receiver_action_label"]
    )
    assert (
        receiver_dispatch_intent["related_project_id"]
        == receiver_action_label["related_project_id"]
    )
    assert (
        receiver_dispatch_intent["related_activation_decision_id"]
        == receiver_action_label["related_activation_decision_id"]
    )
    assert (
        receiver_dispatch_intent["related_packet_id"]
        == receiver_action_label["related_packet_id"]
    )
    assert (
        receiver_dispatch_intent["related_queue_item_id"]
        == receiver_action_label["related_queue_item_id"]
    )
    assert (
        receiver_dispatch_intent["receiver_readiness_classification"] == expected_classification
    )
    assert (
        receiver_dispatch_intent["receiver_handling_directive"] == expected_handling_directive
    )
    assert receiver_dispatch_intent["receiver_action_label"] == expected_action_label
    assert receiver_dispatch_intent["receiver_dispatch_intent"] == expected_dispatch_intent


@pytest.mark.parametrize(
    ("decision", "user_request", "changed_areas"),
    COMPOSITION_PARITY_CASES,
)
def test_build_consumer_receiver_dispatch_mode_from_intent_matches_intent(
    decision: RecommendationValue,
    user_request: str,
    changed_areas: frozenset[str],
) -> None:
    expected_classification = {
        "GO": "ready",
        "PAUSE": "hold",
        "REVIEW": "needs_review",
    }[decision]
    expected_handling_directive = {
        "ready": "deliver",
        "hold": "defer",
        "needs_review": "route_for_review",
    }[expected_classification]
    expected_action_label = {
        "deliver": "dispatch",
        "defer": "wait",
        "route_for_review": "review_queue",
    }[expected_handling_directive]
    expected_dispatch_intent = {
        "dispatch": "send",
        "wait": "park",
        "review_queue": "review",
    }[expected_action_label]
    expected_dispatch_mode = {
        "send": "active",
        "park": "queued",
        "review": "review_pending",
    }[expected_dispatch_intent]
    management_decision = ManagementDecisionRecord(
        item_id="rq_consumer_receiver_dispatch_mode_parity_1",
        decision=decision,
        reviewer_id="manager-consumer-receiver-dispatch-mode",
        reviewer_type="human",
        rationale="Parity check for consumer receiver dispatch mode helper.",
        approved_next_action="Escalate to audit and review before any continuation.",
    )
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=user_request,
            changed_areas=set(changed_areas),
            management_decision=management_decision,
        )
    )
    handoff_envelope = build_dry_run_handoff_envelope_from_result(
        orchestration_result=result,
        activation_review_item_id=(
            "activation_review_consumer_receiver_dispatch_mode_parity_1"
        ),
        approval_record_id="approval_record_consumer_receiver_dispatch_mode_parity_1",
        related_project_id="project_consumer_receiver_dispatch_mode_parity_1",
        related_activation_decision_id=(
            "activation_decision_consumer_receiver_dispatch_mode_parity_1"
        ),
        related_packet_id="packet_consumer_receiver_dispatch_mode_parity_1",
        related_queue_item_id="queue_consumer_receiver_dispatch_mode_parity_1",
    )
    intake = build_next_layer_intake_from_handoff_envelope(
        handoff_envelope=handoff_envelope
    )
    work_item = build_downstream_work_item_from_intake(next_layer_intake=intake)
    intent = build_downstream_execution_intent_from_work_item(
        downstream_work_item=work_item
    )
    readiness_view = build_execution_readiness_view_from_intent(
        downstream_execution_intent=intent
    )
    assessment = build_execution_readiness_assessment_from_view(
        execution_readiness_view=readiness_view
    )
    signal = build_execution_readiness_signal_from_assessment(
        execution_readiness_assessment=assessment
    )
    outcome = build_execution_readiness_outcome_from_signal(
        execution_readiness_signal=signal
    )
    payload = build_downstream_consumer_payload_from_outcome(
        execution_readiness_outcome=outcome
    )
    receiver_intake = build_consumer_receiver_intake_from_payload(
        downstream_consumer_payload=payload
    )
    receiver_readiness_view = build_consumer_receiver_readiness_view_from_intake(
        consumer_receiver_intake=receiver_intake
    )
    receiver_readiness_assessment = build_consumer_receiver_readiness_assessment_from_view(
        consumer_receiver_readiness_view=receiver_readiness_view
    )
    receiver_readiness_signal = build_consumer_receiver_readiness_signal_from_assessment(
        consumer_receiver_readiness_assessment=receiver_readiness_assessment
    )
    receiver_readiness_outcome = build_consumer_receiver_readiness_outcome_from_signal(
        consumer_receiver_readiness_signal=receiver_readiness_signal
    )
    receiver_delivery_payload = build_consumer_receiver_delivery_payload_from_outcome(
        consumer_receiver_readiness_outcome=receiver_readiness_outcome
    )
    receiver_delivery_packet = build_consumer_receiver_delivery_packet_from_payload(
        consumer_receiver_delivery_payload=receiver_delivery_payload
    )
    receiver_delivery_manifest = build_consumer_receiver_delivery_manifest_from_packet(
        consumer_receiver_delivery_packet=receiver_delivery_packet
    )
    receiver_readiness_classification = (
        build_consumer_receiver_readiness_classification_from_manifest(
            consumer_receiver_delivery_manifest=receiver_delivery_manifest
        )
    )
    receiver_handling_directive = (
        build_consumer_receiver_handling_directive_from_classification(
            consumer_receiver_readiness_classification=receiver_readiness_classification
        )
    )
    receiver_action_label = build_consumer_receiver_action_label_from_directive(
        consumer_receiver_handling_directive=receiver_handling_directive
    )
    receiver_dispatch_intent = build_consumer_receiver_dispatch_intent_from_action_label(
        consumer_receiver_action_label=receiver_action_label
    )

    receiver_dispatch_mode = build_consumer_receiver_dispatch_mode_from_intent(
        consumer_receiver_dispatch_intent=receiver_dispatch_intent
    )

    assert (
        receiver_dispatch_mode["projected_activation_decision"]
        == receiver_dispatch_intent["projected_activation_decision"]
    )
    assert receiver_dispatch_mode["approval_record"] == receiver_dispatch_intent["approval_record"]
    assert (
        receiver_dispatch_mode["receiver_readiness_classification"]
        == receiver_dispatch_intent["receiver_readiness_classification"]
    )
    assert (
        receiver_dispatch_mode["receiver_handling_directive"]
        == receiver_dispatch_intent["receiver_handling_directive"]
    )
    assert (
        receiver_dispatch_mode["receiver_action_label"]
        == receiver_dispatch_intent["receiver_action_label"]
    )
    assert (
        receiver_dispatch_mode["receiver_dispatch_intent"]
        == receiver_dispatch_intent["receiver_dispatch_intent"]
    )
    assert (
        receiver_dispatch_mode["related_project_id"]
        == receiver_dispatch_intent["related_project_id"]
    )
    assert (
        receiver_dispatch_mode["related_activation_decision_id"]
        == receiver_dispatch_intent["related_activation_decision_id"]
    )
    assert (
        receiver_dispatch_mode["related_packet_id"]
        == receiver_dispatch_intent["related_packet_id"]
    )
    assert (
        receiver_dispatch_mode["related_queue_item_id"]
        == receiver_dispatch_intent["related_queue_item_id"]
    )
    assert (
        receiver_dispatch_mode["receiver_readiness_classification"] == expected_classification
    )
    assert (
        receiver_dispatch_mode["receiver_handling_directive"] == expected_handling_directive
    )
    assert receiver_dispatch_mode["receiver_action_label"] == expected_action_label
    assert receiver_dispatch_mode["receiver_dispatch_intent"] == expected_dispatch_intent
    assert receiver_dispatch_mode["receiver_dispatch_mode"] == expected_dispatch_mode


@pytest.mark.parametrize(
    ("decision", "user_request", "changed_areas"),
    COMPOSITION_PARITY_CASES,
)
def test_build_consumer_receiver_release_gate_from_dispatch_mode_matches_dispatch_mode(
    decision: RecommendationValue,
    user_request: str,
    changed_areas: frozenset[str],
) -> None:
    expected_classification = {
        "GO": "ready",
        "PAUSE": "hold",
        "REVIEW": "needs_review",
    }[decision]
    expected_handling_directive = {
        "ready": "deliver",
        "hold": "defer",
        "needs_review": "route_for_review",
    }[expected_classification]
    expected_action_label = {
        "deliver": "dispatch",
        "defer": "wait",
        "route_for_review": "review_queue",
    }[expected_handling_directive]
    expected_dispatch_intent = {
        "dispatch": "send",
        "wait": "park",
        "review_queue": "review",
    }[expected_action_label]
    expected_dispatch_mode = {
        "send": "active",
        "park": "queued",
        "review": "review_pending",
    }[expected_dispatch_intent]
    expected_release_gate = {
        "active": "open",
        "queued": "deferred",
        "review_pending": "blocked_for_review",
    }[expected_dispatch_mode]
    management_decision = ManagementDecisionRecord(
        item_id="rq_consumer_receiver_release_gate_parity_1",
        decision=decision,
        reviewer_id="manager-consumer-receiver-release-gate",
        reviewer_type="human",
        rationale="Parity check for consumer receiver release gate helper.",
        approved_next_action="Escalate to audit and review before any continuation.",
    )
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=user_request,
            changed_areas=set(changed_areas),
            management_decision=management_decision,
        )
    )
    handoff_envelope = build_dry_run_handoff_envelope_from_result(
        orchestration_result=result,
        activation_review_item_id=(
            "activation_review_consumer_receiver_release_gate_parity_1"
        ),
        approval_record_id="approval_record_consumer_receiver_release_gate_parity_1",
        related_project_id="project_consumer_receiver_release_gate_parity_1",
        related_activation_decision_id=(
            "activation_decision_consumer_receiver_release_gate_parity_1"
        ),
        related_packet_id="packet_consumer_receiver_release_gate_parity_1",
        related_queue_item_id="queue_consumer_receiver_release_gate_parity_1",
    )
    intake = build_next_layer_intake_from_handoff_envelope(
        handoff_envelope=handoff_envelope
    )
    work_item = build_downstream_work_item_from_intake(next_layer_intake=intake)
    intent = build_downstream_execution_intent_from_work_item(
        downstream_work_item=work_item
    )
    readiness_view = build_execution_readiness_view_from_intent(
        downstream_execution_intent=intent
    )
    assessment = build_execution_readiness_assessment_from_view(
        execution_readiness_view=readiness_view
    )
    signal = build_execution_readiness_signal_from_assessment(
        execution_readiness_assessment=assessment
    )
    outcome = build_execution_readiness_outcome_from_signal(
        execution_readiness_signal=signal
    )
    payload = build_downstream_consumer_payload_from_outcome(
        execution_readiness_outcome=outcome
    )
    receiver_intake = build_consumer_receiver_intake_from_payload(
        downstream_consumer_payload=payload
    )
    receiver_readiness_view = build_consumer_receiver_readiness_view_from_intake(
        consumer_receiver_intake=receiver_intake
    )
    receiver_readiness_assessment = build_consumer_receiver_readiness_assessment_from_view(
        consumer_receiver_readiness_view=receiver_readiness_view
    )
    receiver_readiness_signal = build_consumer_receiver_readiness_signal_from_assessment(
        consumer_receiver_readiness_assessment=receiver_readiness_assessment
    )
    receiver_readiness_outcome = build_consumer_receiver_readiness_outcome_from_signal(
        consumer_receiver_readiness_signal=receiver_readiness_signal
    )
    receiver_delivery_payload = build_consumer_receiver_delivery_payload_from_outcome(
        consumer_receiver_readiness_outcome=receiver_readiness_outcome
    )
    receiver_delivery_packet = build_consumer_receiver_delivery_packet_from_payload(
        consumer_receiver_delivery_payload=receiver_delivery_payload
    )
    receiver_delivery_manifest = build_consumer_receiver_delivery_manifest_from_packet(
        consumer_receiver_delivery_packet=receiver_delivery_packet
    )
    receiver_readiness_classification = (
        build_consumer_receiver_readiness_classification_from_manifest(
            consumer_receiver_delivery_manifest=receiver_delivery_manifest
        )
    )
    receiver_handling_directive = (
        build_consumer_receiver_handling_directive_from_classification(
            consumer_receiver_readiness_classification=receiver_readiness_classification
        )
    )
    receiver_action_label = build_consumer_receiver_action_label_from_directive(
        consumer_receiver_handling_directive=receiver_handling_directive
    )
    receiver_dispatch_intent = build_consumer_receiver_dispatch_intent_from_action_label(
        consumer_receiver_action_label=receiver_action_label
    )
    receiver_dispatch_mode = build_consumer_receiver_dispatch_mode_from_intent(
        consumer_receiver_dispatch_intent=receiver_dispatch_intent
    )

    receiver_release_gate = build_consumer_receiver_release_gate_from_dispatch_mode(
        consumer_receiver_dispatch_mode=receiver_dispatch_mode
    )

    assert (
        receiver_release_gate["projected_activation_decision"]
        == receiver_dispatch_mode["projected_activation_decision"]
    )
    assert receiver_release_gate["approval_record"] == receiver_dispatch_mode["approval_record"]
    assert (
        receiver_release_gate["receiver_readiness_classification"]
        == receiver_dispatch_mode["receiver_readiness_classification"]
    )
    assert (
        receiver_release_gate["receiver_handling_directive"]
        == receiver_dispatch_mode["receiver_handling_directive"]
    )
    assert (
        receiver_release_gate["receiver_action_label"]
        == receiver_dispatch_mode["receiver_action_label"]
    )
    assert (
        receiver_release_gate["receiver_dispatch_intent"]
        == receiver_dispatch_mode["receiver_dispatch_intent"]
    )
    assert (
        receiver_release_gate["receiver_dispatch_mode"]
        == receiver_dispatch_mode["receiver_dispatch_mode"]
    )
    assert (
        receiver_release_gate["related_project_id"]
        == receiver_dispatch_mode["related_project_id"]
    )
    assert (
        receiver_release_gate["related_activation_decision_id"]
        == receiver_dispatch_mode["related_activation_decision_id"]
    )
    assert (
        receiver_release_gate["related_packet_id"]
        == receiver_dispatch_mode["related_packet_id"]
    )
    assert (
        receiver_release_gate["related_queue_item_id"]
        == receiver_dispatch_mode["related_queue_item_id"]
    )
    assert (
        receiver_release_gate["receiver_readiness_classification"]
        == expected_classification
    )
    assert (
        receiver_release_gate["receiver_handling_directive"] == expected_handling_directive
    )
    assert receiver_release_gate["receiver_action_label"] == expected_action_label
    assert receiver_release_gate["receiver_dispatch_intent"] == expected_dispatch_intent
    assert receiver_release_gate["receiver_dispatch_mode"] == expected_dispatch_mode
    assert receiver_release_gate["receiver_release_gate"] == expected_release_gate


@pytest.mark.parametrize(
    ("decision", "user_request", "changed_areas"),
    COMPOSITION_PARITY_CASES,
)
def test_build_consumer_receiver_progress_state_from_release_gate_matches_release_gate(
    decision: RecommendationValue,
    user_request: str,
    changed_areas: frozenset[str],
) -> None:
    expected_classification = {
        "GO": "ready",
        "PAUSE": "hold",
        "REVIEW": "needs_review",
    }[decision]
    expected_handling_directive = {
        "ready": "deliver",
        "hold": "defer",
        "needs_review": "route_for_review",
    }[expected_classification]
    expected_action_label = {
        "deliver": "dispatch",
        "defer": "wait",
        "route_for_review": "review_queue",
    }[expected_handling_directive]
    expected_dispatch_intent = {
        "dispatch": "send",
        "wait": "park",
        "review_queue": "review",
    }[expected_action_label]
    expected_dispatch_mode = {
        "send": "active",
        "park": "queued",
        "review": "review_pending",
    }[expected_dispatch_intent]
    expected_release_gate = {
        "active": "open",
        "queued": "deferred",
        "review_pending": "blocked_for_review",
    }[expected_dispatch_mode]
    expected_progress_state = {
        "open": "in_progress",
        "deferred": "pending",
        "blocked_for_review": "review_hold",
    }[expected_release_gate]
    management_decision = ManagementDecisionRecord(
        item_id="rq_consumer_receiver_progress_state_parity_1",
        decision=decision,
        reviewer_id="manager-consumer-receiver-progress-state",
        reviewer_type="human",
        rationale="Parity check for consumer receiver progress state helper.",
        approved_next_action="Escalate to audit and review before any continuation.",
    )
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=user_request,
            changed_areas=set(changed_areas),
            management_decision=management_decision,
        )
    )
    handoff_envelope = build_dry_run_handoff_envelope_from_result(
        orchestration_result=result,
        activation_review_item_id=(
            "activation_review_consumer_receiver_progress_state_parity_1"
        ),
        approval_record_id="approval_record_consumer_receiver_progress_state_parity_1",
        related_project_id="project_consumer_receiver_progress_state_parity_1",
        related_activation_decision_id=(
            "activation_decision_consumer_receiver_progress_state_parity_1"
        ),
        related_packet_id="packet_consumer_receiver_progress_state_parity_1",
        related_queue_item_id="queue_consumer_receiver_progress_state_parity_1",
    )
    intake = build_next_layer_intake_from_handoff_envelope(
        handoff_envelope=handoff_envelope
    )
    work_item = build_downstream_work_item_from_intake(next_layer_intake=intake)
    intent = build_downstream_execution_intent_from_work_item(
        downstream_work_item=work_item
    )
    readiness_view = build_execution_readiness_view_from_intent(
        downstream_execution_intent=intent
    )
    assessment = build_execution_readiness_assessment_from_view(
        execution_readiness_view=readiness_view
    )
    signal = build_execution_readiness_signal_from_assessment(
        execution_readiness_assessment=assessment
    )
    outcome = build_execution_readiness_outcome_from_signal(
        execution_readiness_signal=signal
    )
    payload = build_downstream_consumer_payload_from_outcome(
        execution_readiness_outcome=outcome
    )
    receiver_intake = build_consumer_receiver_intake_from_payload(
        downstream_consumer_payload=payload
    )
    receiver_readiness_view = build_consumer_receiver_readiness_view_from_intake(
        consumer_receiver_intake=receiver_intake
    )
    receiver_readiness_assessment = build_consumer_receiver_readiness_assessment_from_view(
        consumer_receiver_readiness_view=receiver_readiness_view
    )
    receiver_readiness_signal = build_consumer_receiver_readiness_signal_from_assessment(
        consumer_receiver_readiness_assessment=receiver_readiness_assessment
    )
    receiver_readiness_outcome = build_consumer_receiver_readiness_outcome_from_signal(
        consumer_receiver_readiness_signal=receiver_readiness_signal
    )
    receiver_delivery_payload = build_consumer_receiver_delivery_payload_from_outcome(
        consumer_receiver_readiness_outcome=receiver_readiness_outcome
    )
    receiver_delivery_packet = build_consumer_receiver_delivery_packet_from_payload(
        consumer_receiver_delivery_payload=receiver_delivery_payload
    )
    receiver_delivery_manifest = build_consumer_receiver_delivery_manifest_from_packet(
        consumer_receiver_delivery_packet=receiver_delivery_packet
    )
    receiver_readiness_classification = (
        build_consumer_receiver_readiness_classification_from_manifest(
            consumer_receiver_delivery_manifest=receiver_delivery_manifest
        )
    )
    receiver_handling_directive = (
        build_consumer_receiver_handling_directive_from_classification(
            consumer_receiver_readiness_classification=receiver_readiness_classification
        )
    )
    receiver_action_label = build_consumer_receiver_action_label_from_directive(
        consumer_receiver_handling_directive=receiver_handling_directive
    )
    receiver_dispatch_intent = build_consumer_receiver_dispatch_intent_from_action_label(
        consumer_receiver_action_label=receiver_action_label
    )
    receiver_dispatch_mode = build_consumer_receiver_dispatch_mode_from_intent(
        consumer_receiver_dispatch_intent=receiver_dispatch_intent
    )
    receiver_release_gate = build_consumer_receiver_release_gate_from_dispatch_mode(
        consumer_receiver_dispatch_mode=receiver_dispatch_mode
    )

    receiver_progress_state = build_consumer_receiver_progress_state_from_release_gate(
        consumer_receiver_release_gate=receiver_release_gate
    )

    assert (
        receiver_progress_state["projected_activation_decision"]
        == receiver_release_gate["projected_activation_decision"]
    )
    assert receiver_progress_state["approval_record"] == receiver_release_gate["approval_record"]
    assert (
        receiver_progress_state["receiver_readiness_classification"]
        == receiver_release_gate["receiver_readiness_classification"]
    )
    assert (
        receiver_progress_state["receiver_handling_directive"]
        == receiver_release_gate["receiver_handling_directive"]
    )
    assert (
        receiver_progress_state["receiver_action_label"]
        == receiver_release_gate["receiver_action_label"]
    )
    assert (
        receiver_progress_state["receiver_dispatch_intent"]
        == receiver_release_gate["receiver_dispatch_intent"]
    )
    assert (
        receiver_progress_state["receiver_dispatch_mode"]
        == receiver_release_gate["receiver_dispatch_mode"]
    )
    assert (
        receiver_progress_state["receiver_release_gate"]
        == receiver_release_gate["receiver_release_gate"]
    )
    assert (
        receiver_progress_state["related_project_id"]
        == receiver_release_gate["related_project_id"]
    )
    assert (
        receiver_progress_state["related_activation_decision_id"]
        == receiver_release_gate["related_activation_decision_id"]
    )
    assert (
        receiver_progress_state["related_packet_id"]
        == receiver_release_gate["related_packet_id"]
    )
    assert (
        receiver_progress_state["related_queue_item_id"]
        == receiver_release_gate["related_queue_item_id"]
    )
    assert (
        receiver_progress_state["receiver_readiness_classification"]
        == expected_classification
    )
    assert (
        receiver_progress_state["receiver_handling_directive"] == expected_handling_directive
    )
    assert receiver_progress_state["receiver_action_label"] == expected_action_label
    assert receiver_progress_state["receiver_dispatch_intent"] == expected_dispatch_intent
    assert receiver_progress_state["receiver_dispatch_mode"] == expected_dispatch_mode
    assert receiver_progress_state["receiver_release_gate"] == expected_release_gate
    assert receiver_progress_state["receiver_progress_state"] == expected_progress_state


@pytest.mark.parametrize(
    ("decision", "user_request", "changed_areas"),
    COMPOSITION_PARITY_CASES,
)
def test_build_consumer_receiver_progress_signal_from_state_matches_state(
    decision: RecommendationValue,
    user_request: str,
    changed_areas: frozenset[str],
) -> None:
    expected_classification = {
        "GO": "ready",
        "PAUSE": "hold",
        "REVIEW": "needs_review",
    }[decision]
    expected_handling_directive = {
        "ready": "deliver",
        "hold": "defer",
        "needs_review": "route_for_review",
    }[expected_classification]
    expected_action_label = {
        "deliver": "dispatch",
        "defer": "wait",
        "route_for_review": "review_queue",
    }[expected_handling_directive]
    expected_dispatch_intent = {
        "dispatch": "send",
        "wait": "park",
        "review_queue": "review",
    }[expected_action_label]
    expected_dispatch_mode = {
        "send": "active",
        "park": "queued",
        "review": "review_pending",
    }[expected_dispatch_intent]
    expected_release_gate = {
        "active": "open",
        "queued": "deferred",
        "review_pending": "blocked_for_review",
    }[expected_dispatch_mode]
    expected_progress_state = {
        "open": "in_progress",
        "deferred": "pending",
        "blocked_for_review": "review_hold",
    }[expected_release_gate]
    expected_progress_signal = {
        "in_progress": "advance",
        "pending": "await",
        "review_hold": "review_wait",
    }[expected_progress_state]
    management_decision = ManagementDecisionRecord(
        item_id="rq_consumer_receiver_progress_signal_parity_1",
        decision=decision,
        reviewer_id="manager-consumer-receiver-progress-signal",
        reviewer_type="human",
        rationale="Parity check for consumer receiver progress signal helper.",
        approved_next_action="Escalate to audit and review before any continuation.",
    )
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=user_request,
            changed_areas=set(changed_areas),
            management_decision=management_decision,
        )
    )
    handoff_envelope = build_dry_run_handoff_envelope_from_result(
        orchestration_result=result,
        activation_review_item_id=(
            "activation_review_consumer_receiver_progress_signal_parity_1"
        ),
        approval_record_id="approval_record_consumer_receiver_progress_signal_parity_1",
        related_project_id="project_consumer_receiver_progress_signal_parity_1",
        related_activation_decision_id=(
            "activation_decision_consumer_receiver_progress_signal_parity_1"
        ),
        related_packet_id="packet_consumer_receiver_progress_signal_parity_1",
        related_queue_item_id="queue_consumer_receiver_progress_signal_parity_1",
    )
    intake = build_next_layer_intake_from_handoff_envelope(
        handoff_envelope=handoff_envelope
    )
    work_item = build_downstream_work_item_from_intake(next_layer_intake=intake)
    intent = build_downstream_execution_intent_from_work_item(
        downstream_work_item=work_item
    )
    readiness_view = build_execution_readiness_view_from_intent(
        downstream_execution_intent=intent
    )
    assessment = build_execution_readiness_assessment_from_view(
        execution_readiness_view=readiness_view
    )
    signal = build_execution_readiness_signal_from_assessment(
        execution_readiness_assessment=assessment
    )
    outcome = build_execution_readiness_outcome_from_signal(
        execution_readiness_signal=signal
    )
    payload = build_downstream_consumer_payload_from_outcome(
        execution_readiness_outcome=outcome
    )
    receiver_intake = build_consumer_receiver_intake_from_payload(
        downstream_consumer_payload=payload
    )
    receiver_readiness_view = build_consumer_receiver_readiness_view_from_intake(
        consumer_receiver_intake=receiver_intake
    )
    receiver_readiness_assessment = build_consumer_receiver_readiness_assessment_from_view(
        consumer_receiver_readiness_view=receiver_readiness_view
    )
    receiver_readiness_signal = build_consumer_receiver_readiness_signal_from_assessment(
        consumer_receiver_readiness_assessment=receiver_readiness_assessment
    )
    receiver_readiness_outcome = build_consumer_receiver_readiness_outcome_from_signal(
        consumer_receiver_readiness_signal=receiver_readiness_signal
    )
    receiver_delivery_payload = build_consumer_receiver_delivery_payload_from_outcome(
        consumer_receiver_readiness_outcome=receiver_readiness_outcome
    )
    receiver_delivery_packet = build_consumer_receiver_delivery_packet_from_payload(
        consumer_receiver_delivery_payload=receiver_delivery_payload
    )
    receiver_delivery_manifest = build_consumer_receiver_delivery_manifest_from_packet(
        consumer_receiver_delivery_packet=receiver_delivery_packet
    )
    receiver_readiness_classification = (
        build_consumer_receiver_readiness_classification_from_manifest(
            consumer_receiver_delivery_manifest=receiver_delivery_manifest
        )
    )
    receiver_handling_directive = (
        build_consumer_receiver_handling_directive_from_classification(
            consumer_receiver_readiness_classification=receiver_readiness_classification
        )
    )
    receiver_action_label = build_consumer_receiver_action_label_from_directive(
        consumer_receiver_handling_directive=receiver_handling_directive
    )
    receiver_dispatch_intent = build_consumer_receiver_dispatch_intent_from_action_label(
        consumer_receiver_action_label=receiver_action_label
    )
    receiver_dispatch_mode = build_consumer_receiver_dispatch_mode_from_intent(
        consumer_receiver_dispatch_intent=receiver_dispatch_intent
    )
    receiver_release_gate = build_consumer_receiver_release_gate_from_dispatch_mode(
        consumer_receiver_dispatch_mode=receiver_dispatch_mode
    )
    receiver_progress_state = build_consumer_receiver_progress_state_from_release_gate(
        consumer_receiver_release_gate=receiver_release_gate
    )

    receiver_progress_signal = build_consumer_receiver_progress_signal_from_state(
        consumer_receiver_progress_state=receiver_progress_state
    )

    assert (
        receiver_progress_signal["projected_activation_decision"]
        == receiver_progress_state["projected_activation_decision"]
    )
    assert receiver_progress_signal["approval_record"] == receiver_progress_state["approval_record"]
    assert (
        receiver_progress_signal["receiver_readiness_classification"]
        == receiver_progress_state["receiver_readiness_classification"]
    )
    assert (
        receiver_progress_signal["receiver_handling_directive"]
        == receiver_progress_state["receiver_handling_directive"]
    )
    assert (
        receiver_progress_signal["receiver_action_label"]
        == receiver_progress_state["receiver_action_label"]
    )
    assert (
        receiver_progress_signal["receiver_dispatch_intent"]
        == receiver_progress_state["receiver_dispatch_intent"]
    )
    assert (
        receiver_progress_signal["receiver_dispatch_mode"]
        == receiver_progress_state["receiver_dispatch_mode"]
    )
    assert (
        receiver_progress_signal["receiver_release_gate"]
        == receiver_progress_state["receiver_release_gate"]
    )
    assert (
        receiver_progress_signal["receiver_progress_state"]
        == receiver_progress_state["receiver_progress_state"]
    )
    assert (
        receiver_progress_signal["related_project_id"]
        == receiver_progress_state["related_project_id"]
    )
    assert (
        receiver_progress_signal["related_activation_decision_id"]
        == receiver_progress_state["related_activation_decision_id"]
    )
    assert (
        receiver_progress_signal["related_packet_id"]
        == receiver_progress_state["related_packet_id"]
    )
    assert (
        receiver_progress_signal["related_queue_item_id"]
        == receiver_progress_state["related_queue_item_id"]
    )
    assert (
        receiver_progress_signal["receiver_readiness_classification"]
        == expected_classification
    )
    assert (
        receiver_progress_signal["receiver_handling_directive"] == expected_handling_directive
    )
    assert receiver_progress_signal["receiver_action_label"] == expected_action_label
    assert receiver_progress_signal["receiver_dispatch_intent"] == expected_dispatch_intent
    assert receiver_progress_signal["receiver_dispatch_mode"] == expected_dispatch_mode
    assert receiver_progress_signal["receiver_release_gate"] == expected_release_gate
    assert receiver_progress_signal["receiver_progress_state"] == expected_progress_state
    assert receiver_progress_signal["receiver_progress_signal"] == expected_progress_signal


@pytest.mark.parametrize(
    ("decision", "user_request", "changed_areas"),
    COMPOSITION_PARITY_CASES,
)
def test_build_consumer_receiver_progress_outcome_from_signal_matches_signal(
    decision: RecommendationValue,
    user_request: str,
    changed_areas: frozenset[str],
) -> None:
    expected_classification = {
        "GO": "ready",
        "PAUSE": "hold",
        "REVIEW": "needs_review",
    }[decision]
    expected_handling_directive = {
        "ready": "deliver",
        "hold": "defer",
        "needs_review": "route_for_review",
    }[expected_classification]
    expected_action_label = {
        "deliver": "dispatch",
        "defer": "wait",
        "route_for_review": "review_queue",
    }[expected_handling_directive]
    expected_dispatch_intent = {
        "dispatch": "send",
        "wait": "park",
        "review_queue": "review",
    }[expected_action_label]
    expected_dispatch_mode = {
        "send": "active",
        "park": "queued",
        "review": "review_pending",
    }[expected_dispatch_intent]
    expected_release_gate = {
        "active": "open",
        "queued": "deferred",
        "review_pending": "blocked_for_review",
    }[expected_dispatch_mode]
    expected_progress_state = {
        "open": "in_progress",
        "deferred": "pending",
        "blocked_for_review": "review_hold",
    }[expected_release_gate]
    expected_progress_signal = {
        "in_progress": "advance",
        "pending": "await",
        "review_hold": "review_wait",
    }[expected_progress_state]
    expected_progress_outcome = {
        "advance": "moving",
        "await": "standing_by",
        "review_wait": "awaiting_review",
    }[expected_progress_signal]
    management_decision = ManagementDecisionRecord(
        item_id="rq_consumer_receiver_progress_outcome_parity_1",
        decision=decision,
        reviewer_id="manager-consumer-receiver-progress-outcome",
        reviewer_type="human",
        rationale="Parity check for consumer receiver progress outcome helper.",
        approved_next_action="Escalate to audit and review before any continuation.",
    )
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=user_request,
            changed_areas=set(changed_areas),
            management_decision=management_decision,
        )
    )
    handoff_envelope = build_dry_run_handoff_envelope_from_result(
        orchestration_result=result,
        activation_review_item_id=(
            "activation_review_consumer_receiver_progress_outcome_parity_1"
        ),
        approval_record_id="approval_record_consumer_receiver_progress_outcome_parity_1",
        related_project_id="project_consumer_receiver_progress_outcome_parity_1",
        related_activation_decision_id=(
            "activation_decision_consumer_receiver_progress_outcome_parity_1"
        ),
        related_packet_id="packet_consumer_receiver_progress_outcome_parity_1",
        related_queue_item_id="queue_consumer_receiver_progress_outcome_parity_1",
    )
    intake = build_next_layer_intake_from_handoff_envelope(
        handoff_envelope=handoff_envelope
    )
    work_item = build_downstream_work_item_from_intake(next_layer_intake=intake)
    intent = build_downstream_execution_intent_from_work_item(
        downstream_work_item=work_item
    )
    readiness_view = build_execution_readiness_view_from_intent(
        downstream_execution_intent=intent
    )
    assessment = build_execution_readiness_assessment_from_view(
        execution_readiness_view=readiness_view
    )
    signal = build_execution_readiness_signal_from_assessment(
        execution_readiness_assessment=assessment
    )
    outcome = build_execution_readiness_outcome_from_signal(
        execution_readiness_signal=signal
    )
    payload = build_downstream_consumer_payload_from_outcome(
        execution_readiness_outcome=outcome
    )
    receiver_intake = build_consumer_receiver_intake_from_payload(
        downstream_consumer_payload=payload
    )
    receiver_readiness_view = build_consumer_receiver_readiness_view_from_intake(
        consumer_receiver_intake=receiver_intake
    )
    receiver_readiness_assessment = build_consumer_receiver_readiness_assessment_from_view(
        consumer_receiver_readiness_view=receiver_readiness_view
    )
    receiver_readiness_signal = build_consumer_receiver_readiness_signal_from_assessment(
        consumer_receiver_readiness_assessment=receiver_readiness_assessment
    )
    receiver_readiness_outcome = build_consumer_receiver_readiness_outcome_from_signal(
        consumer_receiver_readiness_signal=receiver_readiness_signal
    )
    receiver_delivery_payload = build_consumer_receiver_delivery_payload_from_outcome(
        consumer_receiver_readiness_outcome=receiver_readiness_outcome
    )
    receiver_delivery_packet = build_consumer_receiver_delivery_packet_from_payload(
        consumer_receiver_delivery_payload=receiver_delivery_payload
    )
    receiver_delivery_manifest = build_consumer_receiver_delivery_manifest_from_packet(
        consumer_receiver_delivery_packet=receiver_delivery_packet
    )
    receiver_readiness_classification = (
        build_consumer_receiver_readiness_classification_from_manifest(
            consumer_receiver_delivery_manifest=receiver_delivery_manifest
        )
    )
    receiver_handling_directive = (
        build_consumer_receiver_handling_directive_from_classification(
            consumer_receiver_readiness_classification=receiver_readiness_classification
        )
    )
    receiver_action_label = build_consumer_receiver_action_label_from_directive(
        consumer_receiver_handling_directive=receiver_handling_directive
    )
    receiver_dispatch_intent = build_consumer_receiver_dispatch_intent_from_action_label(
        consumer_receiver_action_label=receiver_action_label
    )
    receiver_dispatch_mode = build_consumer_receiver_dispatch_mode_from_intent(
        consumer_receiver_dispatch_intent=receiver_dispatch_intent
    )
    receiver_release_gate = build_consumer_receiver_release_gate_from_dispatch_mode(
        consumer_receiver_dispatch_mode=receiver_dispatch_mode
    )
    receiver_progress_state = build_consumer_receiver_progress_state_from_release_gate(
        consumer_receiver_release_gate=receiver_release_gate
    )
    receiver_progress_signal = build_consumer_receiver_progress_signal_from_state(
        consumer_receiver_progress_state=receiver_progress_state
    )

    receiver_progress_outcome = build_consumer_receiver_progress_outcome_from_signal(
        consumer_receiver_progress_signal=receiver_progress_signal
    )

    assert (
        receiver_progress_outcome["projected_activation_decision"]
        == receiver_progress_signal["projected_activation_decision"]
    )
    assert (
        receiver_progress_outcome["approval_record"]
        == receiver_progress_signal["approval_record"]
    )
    assert (
        receiver_progress_outcome["receiver_readiness_classification"]
        == receiver_progress_signal["receiver_readiness_classification"]
    )
    assert (
        receiver_progress_outcome["receiver_handling_directive"]
        == receiver_progress_signal["receiver_handling_directive"]
    )
    assert (
        receiver_progress_outcome["receiver_action_label"]
        == receiver_progress_signal["receiver_action_label"]
    )
    assert (
        receiver_progress_outcome["receiver_dispatch_intent"]
        == receiver_progress_signal["receiver_dispatch_intent"]
    )
    assert (
        receiver_progress_outcome["receiver_dispatch_mode"]
        == receiver_progress_signal["receiver_dispatch_mode"]
    )
    assert (
        receiver_progress_outcome["receiver_release_gate"]
        == receiver_progress_signal["receiver_release_gate"]
    )
    assert (
        receiver_progress_outcome["receiver_progress_state"]
        == receiver_progress_signal["receiver_progress_state"]
    )
    assert (
        receiver_progress_outcome["receiver_progress_signal"]
        == receiver_progress_signal["receiver_progress_signal"]
    )
    assert (
        receiver_progress_outcome["related_project_id"]
        == receiver_progress_signal["related_project_id"]
    )
    assert (
        receiver_progress_outcome["related_activation_decision_id"]
        == receiver_progress_signal["related_activation_decision_id"]
    )
    assert (
        receiver_progress_outcome["related_packet_id"]
        == receiver_progress_signal["related_packet_id"]
    )
    assert (
        receiver_progress_outcome["related_queue_item_id"]
        == receiver_progress_signal["related_queue_item_id"]
    )
    assert (
        receiver_progress_outcome["receiver_readiness_classification"]
        == expected_classification
    )
    assert (
        receiver_progress_outcome["receiver_handling_directive"] == expected_handling_directive
    )
    assert receiver_progress_outcome["receiver_action_label"] == expected_action_label
    assert receiver_progress_outcome["receiver_dispatch_intent"] == expected_dispatch_intent
    assert receiver_progress_outcome["receiver_dispatch_mode"] == expected_dispatch_mode
    assert receiver_progress_outcome["receiver_release_gate"] == expected_release_gate
    assert receiver_progress_outcome["receiver_progress_state"] == expected_progress_state
    assert receiver_progress_outcome["receiver_progress_signal"] == expected_progress_signal
    assert receiver_progress_outcome["receiver_progress_outcome"] == expected_progress_outcome


@pytest.mark.parametrize(
    ("decision", "user_request", "changed_areas"),
    COMPOSITION_PARITY_CASES,
)
def test_build_consumer_receiver_intervention_requirement_from_progress_outcome_matches_outcome(
    decision: RecommendationValue,
    user_request: str,
    changed_areas: frozenset[str],
) -> None:
    expected_classification = {
        "GO": "ready",
        "PAUSE": "hold",
        "REVIEW": "needs_review",
    }[decision]
    expected_handling_directive = {
        "ready": "deliver",
        "hold": "defer",
        "needs_review": "route_for_review",
    }[expected_classification]
    expected_action_label = {
        "deliver": "dispatch",
        "defer": "wait",
        "route_for_review": "review_queue",
    }[expected_handling_directive]
    expected_dispatch_intent = {
        "dispatch": "send",
        "wait": "park",
        "review_queue": "review",
    }[expected_action_label]
    expected_dispatch_mode = {
        "send": "active",
        "park": "queued",
        "review": "review_pending",
    }[expected_dispatch_intent]
    expected_release_gate = {
        "active": "open",
        "queued": "deferred",
        "review_pending": "blocked_for_review",
    }[expected_dispatch_mode]
    expected_progress_state = {
        "open": "in_progress",
        "deferred": "pending",
        "blocked_for_review": "review_hold",
    }[expected_release_gate]
    expected_progress_signal = {
        "in_progress": "advance",
        "pending": "await",
        "review_hold": "review_wait",
    }[expected_progress_state]
    expected_progress_outcome = {
        "advance": "moving",
        "await": "standing_by",
        "review_wait": "awaiting_review",
    }[expected_progress_signal]
    expected_intervention_requirement = {
        "moving": "none",
        "standing_by": "monitor",
        "awaiting_review": "review_required",
    }[expected_progress_outcome]
    management_decision = ManagementDecisionRecord(
        item_id="rq_consumer_receiver_intervention_requirement_parity_1",
        decision=decision,
        reviewer_id="manager-consumer-receiver-intervention-requirement",
        reviewer_type="human",
        rationale="Parity check for receiver intervention requirement helper.",
        approved_next_action="Escalate to audit and review before any continuation.",
    )
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=user_request,
            changed_areas=set(changed_areas),
            management_decision=management_decision,
        )
    )
    handoff_envelope = build_dry_run_handoff_envelope_from_result(
        orchestration_result=result,
        activation_review_item_id=(
            "activation_review_consumer_receiver_intervention_requirement_parity_1"
        ),
        approval_record_id=(
            "approval_record_consumer_receiver_intervention_requirement_parity_1"
        ),
        related_project_id="project_consumer_receiver_intervention_requirement_parity_1",
        related_activation_decision_id=(
            "activation_decision_consumer_receiver_intervention_requirement_parity_1"
        ),
        related_packet_id="packet_consumer_receiver_intervention_requirement_parity_1",
        related_queue_item_id="queue_consumer_receiver_intervention_requirement_parity_1",
    )
    intake = build_next_layer_intake_from_handoff_envelope(
        handoff_envelope=handoff_envelope
    )
    work_item = build_downstream_work_item_from_intake(next_layer_intake=intake)
    intent = build_downstream_execution_intent_from_work_item(
        downstream_work_item=work_item
    )
    readiness_view = build_execution_readiness_view_from_intent(
        downstream_execution_intent=intent
    )
    assessment = build_execution_readiness_assessment_from_view(
        execution_readiness_view=readiness_view
    )
    signal = build_execution_readiness_signal_from_assessment(
        execution_readiness_assessment=assessment
    )
    outcome = build_execution_readiness_outcome_from_signal(
        execution_readiness_signal=signal
    )
    payload = build_downstream_consumer_payload_from_outcome(
        execution_readiness_outcome=outcome
    )
    receiver_intake = build_consumer_receiver_intake_from_payload(
        downstream_consumer_payload=payload
    )
    receiver_readiness_view = build_consumer_receiver_readiness_view_from_intake(
        consumer_receiver_intake=receiver_intake
    )
    receiver_readiness_assessment = build_consumer_receiver_readiness_assessment_from_view(
        consumer_receiver_readiness_view=receiver_readiness_view
    )
    receiver_readiness_signal = build_consumer_receiver_readiness_signal_from_assessment(
        consumer_receiver_readiness_assessment=receiver_readiness_assessment
    )
    receiver_readiness_outcome = build_consumer_receiver_readiness_outcome_from_signal(
        consumer_receiver_readiness_signal=receiver_readiness_signal
    )
    receiver_delivery_payload = build_consumer_receiver_delivery_payload_from_outcome(
        consumer_receiver_readiness_outcome=receiver_readiness_outcome
    )
    receiver_delivery_packet = build_consumer_receiver_delivery_packet_from_payload(
        consumer_receiver_delivery_payload=receiver_delivery_payload
    )
    receiver_delivery_manifest = build_consumer_receiver_delivery_manifest_from_packet(
        consumer_receiver_delivery_packet=receiver_delivery_packet
    )
    receiver_readiness_classification = (
        build_consumer_receiver_readiness_classification_from_manifest(
            consumer_receiver_delivery_manifest=receiver_delivery_manifest
        )
    )
    receiver_handling_directive = (
        build_consumer_receiver_handling_directive_from_classification(
            consumer_receiver_readiness_classification=receiver_readiness_classification
        )
    )
    receiver_action_label = build_consumer_receiver_action_label_from_directive(
        consumer_receiver_handling_directive=receiver_handling_directive
    )
    receiver_dispatch_intent = build_consumer_receiver_dispatch_intent_from_action_label(
        consumer_receiver_action_label=receiver_action_label
    )
    receiver_dispatch_mode = build_consumer_receiver_dispatch_mode_from_intent(
        consumer_receiver_dispatch_intent=receiver_dispatch_intent
    )
    receiver_release_gate = build_consumer_receiver_release_gate_from_dispatch_mode(
        consumer_receiver_dispatch_mode=receiver_dispatch_mode
    )
    receiver_progress_state = build_consumer_receiver_progress_state_from_release_gate(
        consumer_receiver_release_gate=receiver_release_gate
    )
    receiver_progress_signal = build_consumer_receiver_progress_signal_from_state(
        consumer_receiver_progress_state=receiver_progress_state
    )
    receiver_progress_outcome = build_consumer_receiver_progress_outcome_from_signal(
        consumer_receiver_progress_signal=receiver_progress_signal
    )

    receiver_intervention_requirement = (
        build_consumer_receiver_intervention_requirement_from_progress_outcome(
            consumer_receiver_progress_outcome=receiver_progress_outcome
        )
    )

    assert (
        receiver_intervention_requirement["projected_activation_decision"]
        == receiver_progress_outcome["projected_activation_decision"]
    )
    assert (
        receiver_intervention_requirement["approval_record"]
        == receiver_progress_outcome["approval_record"]
    )
    assert (
        receiver_intervention_requirement["receiver_readiness_classification"]
        == receiver_progress_outcome["receiver_readiness_classification"]
    )
    assert (
        receiver_intervention_requirement["receiver_handling_directive"]
        == receiver_progress_outcome["receiver_handling_directive"]
    )
    assert (
        receiver_intervention_requirement["receiver_action_label"]
        == receiver_progress_outcome["receiver_action_label"]
    )
    assert (
        receiver_intervention_requirement["receiver_dispatch_intent"]
        == receiver_progress_outcome["receiver_dispatch_intent"]
    )
    assert (
        receiver_intervention_requirement["receiver_dispatch_mode"]
        == receiver_progress_outcome["receiver_dispatch_mode"]
    )
    assert (
        receiver_intervention_requirement["receiver_release_gate"]
        == receiver_progress_outcome["receiver_release_gate"]
    )
    assert (
        receiver_intervention_requirement["receiver_progress_state"]
        == receiver_progress_outcome["receiver_progress_state"]
    )
    assert (
        receiver_intervention_requirement["receiver_progress_signal"]
        == receiver_progress_outcome["receiver_progress_signal"]
    )
    assert (
        receiver_intervention_requirement["receiver_progress_outcome"]
        == receiver_progress_outcome["receiver_progress_outcome"]
    )
    assert (
        receiver_intervention_requirement["related_project_id"]
        == receiver_progress_outcome["related_project_id"]
    )
    assert (
        receiver_intervention_requirement["related_activation_decision_id"]
        == receiver_progress_outcome["related_activation_decision_id"]
    )
    assert (
        receiver_intervention_requirement["related_packet_id"]
        == receiver_progress_outcome["related_packet_id"]
    )
    assert (
        receiver_intervention_requirement["related_queue_item_id"]
        == receiver_progress_outcome["related_queue_item_id"]
    )
    assert (
        receiver_intervention_requirement["receiver_readiness_classification"]
        == expected_classification
    )
    assert (
        receiver_intervention_requirement["receiver_handling_directive"]
        == expected_handling_directive
    )
    assert receiver_intervention_requirement["receiver_action_label"] == expected_action_label
    assert (
        receiver_intervention_requirement["receiver_dispatch_intent"]
        == expected_dispatch_intent
    )
    assert receiver_intervention_requirement["receiver_dispatch_mode"] == expected_dispatch_mode
    assert receiver_intervention_requirement["receiver_release_gate"] == expected_release_gate
    assert (
        receiver_intervention_requirement["receiver_progress_state"] == expected_progress_state
    )
    assert (
        receiver_intervention_requirement["receiver_progress_signal"]
        == expected_progress_signal
    )
    assert (
        receiver_intervention_requirement["receiver_progress_outcome"]
        == expected_progress_outcome
    )
    assert (
        receiver_intervention_requirement["receiver_intervention_requirement"]
        == expected_intervention_requirement
    )


@pytest.mark.parametrize(
    ("decision", "user_request", "changed_areas"),
    COMPOSITION_PARITY_CASES,
)
def test_build_consumer_receiver_attention_level_from_intervention_requirement_matches_requirement(
    decision: RecommendationValue,
    user_request: str,
    changed_areas: frozenset[str],
) -> None:
    expected_classification = {
        "GO": "ready",
        "PAUSE": "hold",
        "REVIEW": "needs_review",
    }[decision]
    expected_handling_directive = {
        "ready": "deliver",
        "hold": "defer",
        "needs_review": "route_for_review",
    }[expected_classification]
    expected_action_label = {
        "deliver": "dispatch",
        "defer": "wait",
        "route_for_review": "review_queue",
    }[expected_handling_directive]
    expected_dispatch_intent = {
        "dispatch": "send",
        "wait": "park",
        "review_queue": "review",
    }[expected_action_label]
    expected_dispatch_mode = {
        "send": "active",
        "park": "queued",
        "review": "review_pending",
    }[expected_dispatch_intent]
    expected_release_gate = {
        "active": "open",
        "queued": "deferred",
        "review_pending": "blocked_for_review",
    }[expected_dispatch_mode]
    expected_progress_state = {
        "open": "in_progress",
        "deferred": "pending",
        "blocked_for_review": "review_hold",
    }[expected_release_gate]
    expected_progress_signal = {
        "in_progress": "advance",
        "pending": "await",
        "review_hold": "review_wait",
    }[expected_progress_state]
    expected_progress_outcome = {
        "advance": "moving",
        "await": "standing_by",
        "review_wait": "awaiting_review",
    }[expected_progress_signal]
    expected_intervention_requirement = {
        "moving": "none",
        "standing_by": "monitor",
        "awaiting_review": "review_required",
    }[expected_progress_outcome]
    expected_attention_level = {
        "none": "low",
        "monitor": "medium",
        "review_required": "high",
    }[expected_intervention_requirement]
    management_decision = ManagementDecisionRecord(
        item_id="rq_consumer_receiver_attention_level_parity_1",
        decision=decision,
        reviewer_id="manager-consumer-receiver-attention-level",
        reviewer_type="human",
        rationale="Parity check for receiver attention level helper.",
        approved_next_action="Escalate to audit and review before any continuation.",
    )
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=user_request,
            changed_areas=set(changed_areas),
            management_decision=management_decision,
        )
    )
    handoff_envelope = build_dry_run_handoff_envelope_from_result(
        orchestration_result=result,
        activation_review_item_id=(
            "activation_review_consumer_receiver_attention_level_parity_1"
        ),
        approval_record_id="approval_record_consumer_receiver_attention_level_parity_1",
        related_project_id="project_consumer_receiver_attention_level_parity_1",
        related_activation_decision_id=(
            "activation_decision_consumer_receiver_attention_level_parity_1"
        ),
        related_packet_id="packet_consumer_receiver_attention_level_parity_1",
        related_queue_item_id="queue_consumer_receiver_attention_level_parity_1",
    )
    intake = build_next_layer_intake_from_handoff_envelope(
        handoff_envelope=handoff_envelope
    )
    work_item = build_downstream_work_item_from_intake(next_layer_intake=intake)
    intent = build_downstream_execution_intent_from_work_item(
        downstream_work_item=work_item
    )
    readiness_view = build_execution_readiness_view_from_intent(
        downstream_execution_intent=intent
    )
    assessment = build_execution_readiness_assessment_from_view(
        execution_readiness_view=readiness_view
    )
    signal = build_execution_readiness_signal_from_assessment(
        execution_readiness_assessment=assessment
    )
    outcome = build_execution_readiness_outcome_from_signal(
        execution_readiness_signal=signal
    )
    payload = build_downstream_consumer_payload_from_outcome(
        execution_readiness_outcome=outcome
    )
    receiver_intake = build_consumer_receiver_intake_from_payload(
        downstream_consumer_payload=payload
    )
    receiver_readiness_view = build_consumer_receiver_readiness_view_from_intake(
        consumer_receiver_intake=receiver_intake
    )
    receiver_readiness_assessment = build_consumer_receiver_readiness_assessment_from_view(
        consumer_receiver_readiness_view=receiver_readiness_view
    )
    receiver_readiness_signal = build_consumer_receiver_readiness_signal_from_assessment(
        consumer_receiver_readiness_assessment=receiver_readiness_assessment
    )
    receiver_readiness_outcome = build_consumer_receiver_readiness_outcome_from_signal(
        consumer_receiver_readiness_signal=receiver_readiness_signal
    )
    receiver_delivery_payload = build_consumer_receiver_delivery_payload_from_outcome(
        consumer_receiver_readiness_outcome=receiver_readiness_outcome
    )
    receiver_delivery_packet = build_consumer_receiver_delivery_packet_from_payload(
        consumer_receiver_delivery_payload=receiver_delivery_payload
    )
    receiver_delivery_manifest = build_consumer_receiver_delivery_manifest_from_packet(
        consumer_receiver_delivery_packet=receiver_delivery_packet
    )
    receiver_readiness_classification = (
        build_consumer_receiver_readiness_classification_from_manifest(
            consumer_receiver_delivery_manifest=receiver_delivery_manifest
        )
    )
    receiver_handling_directive = (
        build_consumer_receiver_handling_directive_from_classification(
            consumer_receiver_readiness_classification=receiver_readiness_classification
        )
    )
    receiver_action_label = build_consumer_receiver_action_label_from_directive(
        consumer_receiver_handling_directive=receiver_handling_directive
    )
    receiver_dispatch_intent = build_consumer_receiver_dispatch_intent_from_action_label(
        consumer_receiver_action_label=receiver_action_label
    )
    receiver_dispatch_mode = build_consumer_receiver_dispatch_mode_from_intent(
        consumer_receiver_dispatch_intent=receiver_dispatch_intent
    )
    receiver_release_gate = build_consumer_receiver_release_gate_from_dispatch_mode(
        consumer_receiver_dispatch_mode=receiver_dispatch_mode
    )
    receiver_progress_state = build_consumer_receiver_progress_state_from_release_gate(
        consumer_receiver_release_gate=receiver_release_gate
    )
    receiver_progress_signal = build_consumer_receiver_progress_signal_from_state(
        consumer_receiver_progress_state=receiver_progress_state
    )
    receiver_progress_outcome = build_consumer_receiver_progress_outcome_from_signal(
        consumer_receiver_progress_signal=receiver_progress_signal
    )
    receiver_intervention_requirement = (
        build_consumer_receiver_intervention_requirement_from_progress_outcome(
            consumer_receiver_progress_outcome=receiver_progress_outcome
        )
    )
    receiver_attention_level = (
        build_consumer_receiver_attention_level_from_intervention_requirement(
            consumer_receiver_intervention_requirement=receiver_intervention_requirement
        )
    )

    assert (
        receiver_attention_level["projected_activation_decision"]
        == receiver_intervention_requirement["projected_activation_decision"]
    )
    assert (
        receiver_attention_level["approval_record"]
        == receiver_intervention_requirement["approval_record"]
    )
    assert (
        receiver_attention_level["receiver_readiness_classification"]
        == receiver_intervention_requirement["receiver_readiness_classification"]
    )
    assert (
        receiver_attention_level["receiver_handling_directive"]
        == receiver_intervention_requirement["receiver_handling_directive"]
    )
    assert (
        receiver_attention_level["receiver_action_label"]
        == receiver_intervention_requirement["receiver_action_label"]
    )
    assert (
        receiver_attention_level["receiver_dispatch_intent"]
        == receiver_intervention_requirement["receiver_dispatch_intent"]
    )
    assert (
        receiver_attention_level["receiver_dispatch_mode"]
        == receiver_intervention_requirement["receiver_dispatch_mode"]
    )
    assert (
        receiver_attention_level["receiver_release_gate"]
        == receiver_intervention_requirement["receiver_release_gate"]
    )
    assert (
        receiver_attention_level["receiver_progress_state"]
        == receiver_intervention_requirement["receiver_progress_state"]
    )
    assert (
        receiver_attention_level["receiver_progress_signal"]
        == receiver_intervention_requirement["receiver_progress_signal"]
    )
    assert (
        receiver_attention_level["receiver_progress_outcome"]
        == receiver_intervention_requirement["receiver_progress_outcome"]
    )
    assert (
        receiver_attention_level["receiver_intervention_requirement"]
        == receiver_intervention_requirement["receiver_intervention_requirement"]
    )
    assert (
        receiver_attention_level["related_project_id"]
        == receiver_intervention_requirement["related_project_id"]
    )
    assert (
        receiver_attention_level["related_activation_decision_id"]
        == receiver_intervention_requirement["related_activation_decision_id"]
    )
    assert (
        receiver_attention_level["related_packet_id"]
        == receiver_intervention_requirement["related_packet_id"]
    )
    assert (
        receiver_attention_level["related_queue_item_id"]
        == receiver_intervention_requirement["related_queue_item_id"]
    )
    assert (
        receiver_attention_level["receiver_readiness_classification"]
        == expected_classification
    )
    assert (
        receiver_attention_level["receiver_handling_directive"]
        == expected_handling_directive
    )
    assert receiver_attention_level["receiver_action_label"] == expected_action_label
    assert receiver_attention_level["receiver_dispatch_intent"] == expected_dispatch_intent
    assert receiver_attention_level["receiver_dispatch_mode"] == expected_dispatch_mode
    assert receiver_attention_level["receiver_release_gate"] == expected_release_gate
    assert receiver_attention_level["receiver_progress_state"] == expected_progress_state
    assert receiver_attention_level["receiver_progress_signal"] == expected_progress_signal
    assert receiver_attention_level["receiver_progress_outcome"] == expected_progress_outcome
    assert (
        receiver_attention_level["receiver_intervention_requirement"]
        == expected_intervention_requirement
    )
    assert receiver_attention_level["receiver_attention_level"] == expected_attention_level


@pytest.mark.parametrize(
    ("decision", "expected_attention_level", "expected_notification_requirement"),
    [
        pytest.param("GO", "low", "none", id="go"),
        pytest.param("PAUSE", "medium", "notify", id="pause"),
        pytest.param("REVIEW", "high", "escalate", id="review"),
    ],
)
def test_build_consumer_receiver_notification_requirement_from_attention_level_matches_level(
    decision: RecommendationValue,
    expected_attention_level: str,
    expected_notification_requirement: str,
) -> None:
    expected_classification = {
        "GO": "ready",
        "PAUSE": "hold",
        "REVIEW": "needs_review",
    }[decision]
    expected_handling_directive = {
        "ready": "deliver",
        "hold": "defer",
        "needs_review": "route_for_review",
    }[expected_classification]
    expected_action_label = {
        "deliver": "dispatch",
        "defer": "wait",
        "route_for_review": "review_queue",
    }[expected_handling_directive]
    expected_dispatch_intent = {
        "dispatch": "send",
        "wait": "park",
        "review_queue": "review",
    }[expected_action_label]
    expected_dispatch_mode = {
        "send": "active",
        "park": "queued",
        "review": "review_pending",
    }[expected_dispatch_intent]
    expected_release_gate = {
        "active": "open",
        "queued": "deferred",
        "review_pending": "blocked_for_review",
    }[expected_dispatch_mode]
    expected_progress_state = {
        "open": "in_progress",
        "deferred": "pending",
        "blocked_for_review": "review_hold",
    }[expected_release_gate]
    expected_progress_signal = {
        "in_progress": "advance",
        "pending": "await",
        "review_hold": "review_wait",
    }[expected_progress_state]
    expected_progress_outcome = {
        "advance": "moving",
        "await": "standing_by",
        "review_wait": "awaiting_review",
    }[expected_progress_signal]
    expected_intervention_requirement = {
        "moving": "none",
        "standing_by": "monitor",
        "awaiting_review": "review_required",
    }[expected_progress_outcome]
    attention_level_by_intervention_requirement = {
        "none": "low",
        "monitor": "medium",
        "review_required": "high",
    }
    assert (
        attention_level_by_intervention_requirement[expected_intervention_requirement]
        == expected_attention_level
    )
    consumer_receiver_attention_level = {
        "projected_activation_decision": {"recommendation": decision},
        "approval_record": {
            "human_approval_status": {
                "status": {
                    "GO": "approved",
                    "PAUSE": "pending",
                    "REVIEW": "withheld",
                }[decision]
            }
        },
        "receiver_readiness_classification": expected_classification,
        "receiver_handling_directive": expected_handling_directive,
        "receiver_action_label": expected_action_label,
        "receiver_dispatch_intent": expected_dispatch_intent,
        "receiver_dispatch_mode": expected_dispatch_mode,
        "receiver_release_gate": expected_release_gate,
        "receiver_progress_state": expected_progress_state,
        "receiver_progress_signal": expected_progress_signal,
        "receiver_progress_outcome": expected_progress_outcome,
        "receiver_intervention_requirement": expected_intervention_requirement,
        "receiver_attention_level": expected_attention_level,
        "related_project_id": "project_consumer_receiver_notification_requirement_1",
        "related_activation_decision_id": (
            "activation_decision_consumer_receiver_notification_requirement_1"
        ),
        "related_packet_id": "packet_consumer_receiver_notification_requirement_1",
        "related_queue_item_id": (
            "queue_consumer_receiver_notification_requirement_1"
        ),
    }

    receiver_notification_requirement = (
        build_consumer_receiver_notification_requirement_from_attention_level(
            consumer_receiver_attention_level=consumer_receiver_attention_level
        )
    )

    assert (
        receiver_notification_requirement["projected_activation_decision"]
        == consumer_receiver_attention_level["projected_activation_decision"]
    )
    assert (
        receiver_notification_requirement["approval_record"]
        == consumer_receiver_attention_level["approval_record"]
    )
    assert (
        receiver_notification_requirement["receiver_readiness_classification"]
        == consumer_receiver_attention_level["receiver_readiness_classification"]
    )
    assert (
        receiver_notification_requirement["receiver_handling_directive"]
        == consumer_receiver_attention_level["receiver_handling_directive"]
    )
    assert (
        receiver_notification_requirement["receiver_action_label"]
        == consumer_receiver_attention_level["receiver_action_label"]
    )
    assert (
        receiver_notification_requirement["receiver_dispatch_intent"]
        == consumer_receiver_attention_level["receiver_dispatch_intent"]
    )
    assert (
        receiver_notification_requirement["receiver_dispatch_mode"]
        == consumer_receiver_attention_level["receiver_dispatch_mode"]
    )
    assert (
        receiver_notification_requirement["receiver_release_gate"]
        == consumer_receiver_attention_level["receiver_release_gate"]
    )
    assert (
        receiver_notification_requirement["receiver_progress_state"]
        == consumer_receiver_attention_level["receiver_progress_state"]
    )
    assert (
        receiver_notification_requirement["receiver_progress_signal"]
        == consumer_receiver_attention_level["receiver_progress_signal"]
    )
    assert (
        receiver_notification_requirement["receiver_progress_outcome"]
        == consumer_receiver_attention_level["receiver_progress_outcome"]
    )
    assert (
        receiver_notification_requirement["receiver_intervention_requirement"]
        == consumer_receiver_attention_level["receiver_intervention_requirement"]
    )
    assert (
        receiver_notification_requirement["receiver_attention_level"]
        == consumer_receiver_attention_level["receiver_attention_level"]
    )
    assert (
        receiver_notification_requirement["related_project_id"]
        == consumer_receiver_attention_level["related_project_id"]
    )
    assert (
        receiver_notification_requirement["related_activation_decision_id"]
        == consumer_receiver_attention_level["related_activation_decision_id"]
    )
    assert (
        receiver_notification_requirement["related_packet_id"]
        == consumer_receiver_attention_level["related_packet_id"]
    )
    assert (
        receiver_notification_requirement["related_queue_item_id"]
        == consumer_receiver_attention_level["related_queue_item_id"]
    )
    assert (
        receiver_notification_requirement["receiver_notification_requirement"]
        == expected_notification_requirement
    )


@pytest.mark.parametrize(
    (
        "decision",
        "expected_attention_level",
        "expected_notification_requirement",
        "expected_response_priority",
    ),
    [
        pytest.param("GO", "low", "none", "normal", id="go"),
        pytest.param("PAUSE", "medium", "notify", "elevated", id="pause"),
        pytest.param("REVIEW", "high", "escalate", "urgent", id="review"),
    ],
)
def test_response_priority_from_notification_requirement_matches_requirement(
    decision: RecommendationValue,
    expected_attention_level: str,
    expected_notification_requirement: str,
    expected_response_priority: str,
) -> None:
    expected_classification = {
        "GO": "ready",
        "PAUSE": "hold",
        "REVIEW": "needs_review",
    }[decision]
    expected_handling_directive = {
        "ready": "deliver",
        "hold": "defer",
        "needs_review": "route_for_review",
    }[expected_classification]
    expected_action_label = {
        "deliver": "dispatch",
        "defer": "wait",
        "route_for_review": "review_queue",
    }[expected_handling_directive]
    expected_dispatch_intent = {
        "dispatch": "send",
        "wait": "park",
        "review_queue": "review",
    }[expected_action_label]
    expected_dispatch_mode = {
        "send": "active",
        "park": "queued",
        "review": "review_pending",
    }[expected_dispatch_intent]
    expected_release_gate = {
        "active": "open",
        "queued": "deferred",
        "review_pending": "blocked_for_review",
    }[expected_dispatch_mode]
    expected_progress_state = {
        "open": "in_progress",
        "deferred": "pending",
        "blocked_for_review": "review_hold",
    }[expected_release_gate]
    expected_progress_signal = {
        "in_progress": "advance",
        "pending": "await",
        "review_hold": "review_wait",
    }[expected_progress_state]
    expected_progress_outcome = {
        "advance": "moving",
        "await": "standing_by",
        "review_wait": "awaiting_review",
    }[expected_progress_signal]
    expected_intervention_requirement = {
        "moving": "none",
        "standing_by": "monitor",
        "awaiting_review": "review_required",
    }[expected_progress_outcome]
    attention_level_by_intervention_requirement = {
        "none": "low",
        "monitor": "medium",
        "review_required": "high",
    }
    notification_requirement_by_attention_level = {
        "low": "none",
        "medium": "notify",
        "high": "escalate",
    }
    assert (
        attention_level_by_intervention_requirement[expected_intervention_requirement]
        == expected_attention_level
    )
    assert (
        notification_requirement_by_attention_level[expected_attention_level]
        == expected_notification_requirement
    )
    consumer_receiver_notification_requirement = {
        "projected_activation_decision": {"recommendation": decision},
        "approval_record": {
            "human_approval_status": {
                "status": {
                    "GO": "approved",
                    "PAUSE": "pending",
                    "REVIEW": "withheld",
                }[decision]
            }
        },
        "receiver_readiness_classification": expected_classification,
        "receiver_handling_directive": expected_handling_directive,
        "receiver_action_label": expected_action_label,
        "receiver_dispatch_intent": expected_dispatch_intent,
        "receiver_dispatch_mode": expected_dispatch_mode,
        "receiver_release_gate": expected_release_gate,
        "receiver_progress_state": expected_progress_state,
        "receiver_progress_signal": expected_progress_signal,
        "receiver_progress_outcome": expected_progress_outcome,
        "receiver_intervention_requirement": expected_intervention_requirement,
        "receiver_attention_level": expected_attention_level,
        "receiver_notification_requirement": expected_notification_requirement,
        "related_project_id": "project_consumer_receiver_response_priority_1",
        "related_activation_decision_id": (
            "activation_decision_consumer_receiver_response_priority_1"
        ),
        "related_packet_id": "packet_consumer_receiver_response_priority_1",
        "related_queue_item_id": "queue_consumer_receiver_response_priority_1",
    }

    receiver_response_priority = (
        build_consumer_receiver_response_priority_from_notification_requirement(
            consumer_receiver_notification_requirement=(
                consumer_receiver_notification_requirement
            )
        )
    )

    assert (
        receiver_response_priority["projected_activation_decision"]
        == consumer_receiver_notification_requirement["projected_activation_decision"]
    )
    assert (
        receiver_response_priority["approval_record"]
        == consumer_receiver_notification_requirement["approval_record"]
    )
    assert (
        receiver_response_priority["receiver_readiness_classification"]
        == consumer_receiver_notification_requirement["receiver_readiness_classification"]
    )
    assert (
        receiver_response_priority["receiver_handling_directive"]
        == consumer_receiver_notification_requirement["receiver_handling_directive"]
    )
    assert (
        receiver_response_priority["receiver_action_label"]
        == consumer_receiver_notification_requirement["receiver_action_label"]
    )
    assert (
        receiver_response_priority["receiver_dispatch_intent"]
        == consumer_receiver_notification_requirement["receiver_dispatch_intent"]
    )
    assert (
        receiver_response_priority["receiver_dispatch_mode"]
        == consumer_receiver_notification_requirement["receiver_dispatch_mode"]
    )
    assert (
        receiver_response_priority["receiver_release_gate"]
        == consumer_receiver_notification_requirement["receiver_release_gate"]
    )
    assert (
        receiver_response_priority["receiver_progress_state"]
        == consumer_receiver_notification_requirement["receiver_progress_state"]
    )
    assert (
        receiver_response_priority["receiver_progress_signal"]
        == consumer_receiver_notification_requirement["receiver_progress_signal"]
    )
    assert (
        receiver_response_priority["receiver_progress_outcome"]
        == consumer_receiver_notification_requirement["receiver_progress_outcome"]
    )
    assert (
        receiver_response_priority["receiver_intervention_requirement"]
        == consumer_receiver_notification_requirement["receiver_intervention_requirement"]
    )
    assert (
        receiver_response_priority["receiver_attention_level"]
        == consumer_receiver_notification_requirement["receiver_attention_level"]
    )
    assert (
        receiver_response_priority["receiver_notification_requirement"]
        == consumer_receiver_notification_requirement[
            "receiver_notification_requirement"
        ]
    )
    assert (
        receiver_response_priority["related_project_id"]
        == consumer_receiver_notification_requirement["related_project_id"]
    )
    assert (
        receiver_response_priority["related_activation_decision_id"]
        == consumer_receiver_notification_requirement["related_activation_decision_id"]
    )
    assert (
        receiver_response_priority["related_packet_id"]
        == consumer_receiver_notification_requirement["related_packet_id"]
    )
    assert (
        receiver_response_priority["related_queue_item_id"]
        == consumer_receiver_notification_requirement["related_queue_item_id"]
    )
    assert (
        receiver_response_priority["receiver_response_priority"]
        == expected_response_priority
    )


@pytest.mark.parametrize(
    (
        "decision",
        "expected_attention_level",
        "expected_notification_requirement",
        "expected_response_priority",
        "expected_response_channel",
    ),
    [
        pytest.param("GO", "low", "none", "normal", "standard_channel", id="go"),
        pytest.param(
            "PAUSE",
            "medium",
            "notify",
            "elevated",
            "priority_channel",
            id="pause",
        ),
        pytest.param(
            "REVIEW",
            "high",
            "escalate",
            "urgent",
            "escalation_channel",
            id="review",
        ),
    ],
)
def test_response_channel_from_priority_matches_priority(
    decision: RecommendationValue,
    expected_attention_level: str,
    expected_notification_requirement: str,
    expected_response_priority: str,
    expected_response_channel: str,
) -> None:
    expected_classification = {
        "GO": "ready",
        "PAUSE": "hold",
        "REVIEW": "needs_review",
    }[decision]
    expected_handling_directive = {
        "ready": "deliver",
        "hold": "defer",
        "needs_review": "route_for_review",
    }[expected_classification]
    expected_action_label = {
        "deliver": "dispatch",
        "defer": "wait",
        "route_for_review": "review_queue",
    }[expected_handling_directive]
    expected_dispatch_intent = {
        "dispatch": "send",
        "wait": "park",
        "review_queue": "review",
    }[expected_action_label]
    expected_dispatch_mode = {
        "send": "active",
        "park": "queued",
        "review": "review_pending",
    }[expected_dispatch_intent]
    expected_release_gate = {
        "active": "open",
        "queued": "deferred",
        "review_pending": "blocked_for_review",
    }[expected_dispatch_mode]
    expected_progress_state = {
        "open": "in_progress",
        "deferred": "pending",
        "blocked_for_review": "review_hold",
    }[expected_release_gate]
    expected_progress_signal = {
        "in_progress": "advance",
        "pending": "await",
        "review_hold": "review_wait",
    }[expected_progress_state]
    expected_progress_outcome = {
        "advance": "moving",
        "await": "standing_by",
        "review_wait": "awaiting_review",
    }[expected_progress_signal]
    expected_intervention_requirement = {
        "moving": "none",
        "standing_by": "monitor",
        "awaiting_review": "review_required",
    }[expected_progress_outcome]
    attention_level_by_intervention_requirement = {
        "none": "low",
        "monitor": "medium",
        "review_required": "high",
    }
    notification_requirement_by_attention_level = {
        "low": "none",
        "medium": "notify",
        "high": "escalate",
    }
    response_priority_by_notification_requirement = {
        "none": "normal",
        "notify": "elevated",
        "escalate": "urgent",
    }
    assert (
        attention_level_by_intervention_requirement[expected_intervention_requirement]
        == expected_attention_level
    )
    assert (
        notification_requirement_by_attention_level[expected_attention_level]
        == expected_notification_requirement
    )
    assert (
        response_priority_by_notification_requirement[expected_notification_requirement]
        == expected_response_priority
    )
    consumer_receiver_response_priority = {
        "projected_activation_decision": {"recommendation": decision},
        "approval_record": {
            "human_approval_status": {
                "status": {
                    "GO": "approved",
                    "PAUSE": "pending",
                    "REVIEW": "withheld",
                }[decision]
            }
        },
        "receiver_readiness_classification": expected_classification,
        "receiver_handling_directive": expected_handling_directive,
        "receiver_action_label": expected_action_label,
        "receiver_dispatch_intent": expected_dispatch_intent,
        "receiver_dispatch_mode": expected_dispatch_mode,
        "receiver_release_gate": expected_release_gate,
        "receiver_progress_state": expected_progress_state,
        "receiver_progress_signal": expected_progress_signal,
        "receiver_progress_outcome": expected_progress_outcome,
        "receiver_intervention_requirement": expected_intervention_requirement,
        "receiver_attention_level": expected_attention_level,
        "receiver_notification_requirement": expected_notification_requirement,
        "receiver_response_priority": expected_response_priority,
        "related_project_id": "project_consumer_receiver_response_channel_1",
        "related_activation_decision_id": (
            "activation_decision_consumer_receiver_response_channel_1"
        ),
        "related_packet_id": "packet_consumer_receiver_response_channel_1",
        "related_queue_item_id": "queue_consumer_receiver_response_channel_1",
    }

    receiver_response_channel = build_consumer_receiver_response_channel_from_priority(
        consumer_receiver_response_priority=consumer_receiver_response_priority
    )

    assert (
        receiver_response_channel["projected_activation_decision"]
        == consumer_receiver_response_priority["projected_activation_decision"]
    )
    assert (
        receiver_response_channel["approval_record"]
        == consumer_receiver_response_priority["approval_record"]
    )
    assert (
        receiver_response_channel["receiver_readiness_classification"]
        == consumer_receiver_response_priority["receiver_readiness_classification"]
    )
    assert (
        receiver_response_channel["receiver_handling_directive"]
        == consumer_receiver_response_priority["receiver_handling_directive"]
    )
    assert (
        receiver_response_channel["receiver_action_label"]
        == consumer_receiver_response_priority["receiver_action_label"]
    )
    assert (
        receiver_response_channel["receiver_dispatch_intent"]
        == consumer_receiver_response_priority["receiver_dispatch_intent"]
    )
    assert (
        receiver_response_channel["receiver_dispatch_mode"]
        == consumer_receiver_response_priority["receiver_dispatch_mode"]
    )
    assert (
        receiver_response_channel["receiver_release_gate"]
        == consumer_receiver_response_priority["receiver_release_gate"]
    )
    assert (
        receiver_response_channel["receiver_progress_state"]
        == consumer_receiver_response_priority["receiver_progress_state"]
    )
    assert (
        receiver_response_channel["receiver_progress_signal"]
        == consumer_receiver_response_priority["receiver_progress_signal"]
    )
    assert (
        receiver_response_channel["receiver_progress_outcome"]
        == consumer_receiver_response_priority["receiver_progress_outcome"]
    )
    assert (
        receiver_response_channel["receiver_intervention_requirement"]
        == consumer_receiver_response_priority["receiver_intervention_requirement"]
    )
    assert (
        receiver_response_channel["receiver_attention_level"]
        == consumer_receiver_response_priority["receiver_attention_level"]
    )
    assert (
        receiver_response_channel["receiver_notification_requirement"]
        == consumer_receiver_response_priority["receiver_notification_requirement"]
    )
    assert (
        receiver_response_channel["receiver_response_priority"]
        == consumer_receiver_response_priority["receiver_response_priority"]
    )
    assert (
        receiver_response_channel["related_project_id"]
        == consumer_receiver_response_priority["related_project_id"]
    )
    assert (
        receiver_response_channel["related_activation_decision_id"]
        == consumer_receiver_response_priority["related_activation_decision_id"]
    )
    assert (
        receiver_response_channel["related_packet_id"]
        == consumer_receiver_response_priority["related_packet_id"]
    )
    assert (
        receiver_response_channel["related_queue_item_id"]
        == consumer_receiver_response_priority["related_queue_item_id"]
    )
    assert (
        receiver_response_channel["receiver_response_channel"] == expected_response_channel
    )


@pytest.mark.parametrize(
    (
        "decision",
        "expected_attention_level",
        "expected_notification_requirement",
        "expected_response_priority",
        "expected_response_channel",
        "expected_response_route",
    ),
    [
        pytest.param(
            "GO",
            "low",
            "none",
            "normal",
            "standard_channel",
            "standard_route",
            id="go",
        ),
        pytest.param(
            "PAUSE",
            "medium",
            "notify",
            "elevated",
            "priority_channel",
            "priority_route",
            id="pause",
        ),
        pytest.param(
            "REVIEW",
            "high",
            "escalate",
            "urgent",
            "escalation_channel",
            "escalation_route",
            id="review",
        ),
    ],
)
def test_response_route_from_channel_matches_channel(
    decision: RecommendationValue,
    expected_attention_level: str,
    expected_notification_requirement: str,
    expected_response_priority: str,
    expected_response_channel: str,
    expected_response_route: str,
) -> None:
    expected_classification = {
        "GO": "ready",
        "PAUSE": "hold",
        "REVIEW": "needs_review",
    }[decision]
    expected_handling_directive = {
        "ready": "deliver",
        "hold": "defer",
        "needs_review": "route_for_review",
    }[expected_classification]
    expected_action_label = {
        "deliver": "dispatch",
        "defer": "wait",
        "route_for_review": "review_queue",
    }[expected_handling_directive]
    expected_dispatch_intent = {
        "dispatch": "send",
        "wait": "park",
        "review_queue": "review",
    }[expected_action_label]
    expected_dispatch_mode = {
        "send": "active",
        "park": "queued",
        "review": "review_pending",
    }[expected_dispatch_intent]
    expected_release_gate = {
        "active": "open",
        "queued": "deferred",
        "review_pending": "blocked_for_review",
    }[expected_dispatch_mode]
    expected_progress_state = {
        "open": "in_progress",
        "deferred": "pending",
        "blocked_for_review": "review_hold",
    }[expected_release_gate]
    expected_progress_signal = {
        "in_progress": "advance",
        "pending": "await",
        "review_hold": "review_wait",
    }[expected_progress_state]
    expected_progress_outcome = {
        "advance": "moving",
        "await": "standing_by",
        "review_wait": "awaiting_review",
    }[expected_progress_signal]
    expected_intervention_requirement = {
        "moving": "none",
        "standing_by": "monitor",
        "awaiting_review": "review_required",
    }[expected_progress_outcome]
    attention_level_by_intervention_requirement = {
        "none": "low",
        "monitor": "medium",
        "review_required": "high",
    }
    notification_requirement_by_attention_level = {
        "low": "none",
        "medium": "notify",
        "high": "escalate",
    }
    response_priority_by_notification_requirement = {
        "none": "normal",
        "notify": "elevated",
        "escalate": "urgent",
    }
    response_channel_by_priority = {
        "normal": "standard_channel",
        "elevated": "priority_channel",
        "urgent": "escalation_channel",
    }
    assert (
        attention_level_by_intervention_requirement[expected_intervention_requirement]
        == expected_attention_level
    )
    assert (
        notification_requirement_by_attention_level[expected_attention_level]
        == expected_notification_requirement
    )
    assert (
        response_priority_by_notification_requirement[expected_notification_requirement]
        == expected_response_priority
    )
    assert response_channel_by_priority[expected_response_priority] == expected_response_channel
    consumer_receiver_response_channel = {
        "projected_activation_decision": {"recommendation": decision},
        "approval_record": {
            "human_approval_status": {
                "status": {
                    "GO": "approved",
                    "PAUSE": "pending",
                    "REVIEW": "withheld",
                }[decision]
            }
        },
        "receiver_readiness_classification": expected_classification,
        "receiver_handling_directive": expected_handling_directive,
        "receiver_action_label": expected_action_label,
        "receiver_dispatch_intent": expected_dispatch_intent,
        "receiver_dispatch_mode": expected_dispatch_mode,
        "receiver_release_gate": expected_release_gate,
        "receiver_progress_state": expected_progress_state,
        "receiver_progress_signal": expected_progress_signal,
        "receiver_progress_outcome": expected_progress_outcome,
        "receiver_intervention_requirement": expected_intervention_requirement,
        "receiver_attention_level": expected_attention_level,
        "receiver_notification_requirement": expected_notification_requirement,
        "receiver_response_priority": expected_response_priority,
        "receiver_response_channel": expected_response_channel,
        "related_project_id": "project_consumer_receiver_response_route_1",
        "related_activation_decision_id": (
            "activation_decision_consumer_receiver_response_route_1"
        ),
        "related_packet_id": "packet_consumer_receiver_response_route_1",
        "related_queue_item_id": "queue_consumer_receiver_response_route_1",
    }

    receiver_response_route = build_consumer_receiver_response_route_from_channel(
        consumer_receiver_response_channel=consumer_receiver_response_channel
    )

    assert (
        receiver_response_route["projected_activation_decision"]
        == consumer_receiver_response_channel["projected_activation_decision"]
    )
    assert (
        receiver_response_route["approval_record"]
        == consumer_receiver_response_channel["approval_record"]
    )
    assert (
        receiver_response_route["receiver_readiness_classification"]
        == consumer_receiver_response_channel["receiver_readiness_classification"]
    )
    assert (
        receiver_response_route["receiver_handling_directive"]
        == consumer_receiver_response_channel["receiver_handling_directive"]
    )
    assert (
        receiver_response_route["receiver_action_label"]
        == consumer_receiver_response_channel["receiver_action_label"]
    )
    assert (
        receiver_response_route["receiver_dispatch_intent"]
        == consumer_receiver_response_channel["receiver_dispatch_intent"]
    )
    assert (
        receiver_response_route["receiver_dispatch_mode"]
        == consumer_receiver_response_channel["receiver_dispatch_mode"]
    )
    assert (
        receiver_response_route["receiver_release_gate"]
        == consumer_receiver_response_channel["receiver_release_gate"]
    )
    assert (
        receiver_response_route["receiver_progress_state"]
        == consumer_receiver_response_channel["receiver_progress_state"]
    )
    assert (
        receiver_response_route["receiver_progress_signal"]
        == consumer_receiver_response_channel["receiver_progress_signal"]
    )
    assert (
        receiver_response_route["receiver_progress_outcome"]
        == consumer_receiver_response_channel["receiver_progress_outcome"]
    )
    assert (
        receiver_response_route["receiver_intervention_requirement"]
        == consumer_receiver_response_channel["receiver_intervention_requirement"]
    )
    assert (
        receiver_response_route["receiver_attention_level"]
        == consumer_receiver_response_channel["receiver_attention_level"]
    )
    assert (
        receiver_response_route["receiver_notification_requirement"]
        == consumer_receiver_response_channel["receiver_notification_requirement"]
    )
    assert (
        receiver_response_route["receiver_response_priority"]
        == consumer_receiver_response_channel["receiver_response_priority"]
    )
    assert (
        receiver_response_route["receiver_response_channel"]
        == consumer_receiver_response_channel["receiver_response_channel"]
    )
    assert (
        receiver_response_route["related_project_id"]
        == consumer_receiver_response_channel["related_project_id"]
    )
    assert (
        receiver_response_route["related_activation_decision_id"]
        == consumer_receiver_response_channel["related_activation_decision_id"]
    )
    assert (
        receiver_response_route["related_packet_id"]
        == consumer_receiver_response_channel["related_packet_id"]
    )
    assert (
        receiver_response_route["related_queue_item_id"]
        == consumer_receiver_response_channel["related_queue_item_id"]
    )
    assert receiver_response_route["receiver_response_route"] == expected_response_route


@pytest.mark.parametrize(
    (
        "decision",
        "expected_attention_level",
        "expected_notification_requirement",
        "expected_response_priority",
        "expected_response_channel",
        "expected_response_route",
        "expected_followup_requirement",
    ),
    [
        pytest.param(
            "GO",
            "low",
            "none",
            "normal",
            "standard_channel",
            "standard_route",
            "none",
            id="go",
        ),
        pytest.param(
            "PAUSE",
            "medium",
            "notify",
            "elevated",
            "priority_channel",
            "priority_route",
            "follow_up",
            id="pause",
        ),
        pytest.param(
            "REVIEW",
            "high",
            "escalate",
            "urgent",
            "escalation_channel",
            "escalation_route",
            "escalation_follow_up",
            id="review",
        ),
    ],
)
def test_followup_requirement_from_response_route_matches_route(
    decision: RecommendationValue,
    expected_attention_level: str,
    expected_notification_requirement: str,
    expected_response_priority: str,
    expected_response_channel: str,
    expected_response_route: str,
    expected_followup_requirement: str,
) -> None:
    expected_classification = {
        "GO": "ready",
        "PAUSE": "hold",
        "REVIEW": "needs_review",
    }[decision]
    expected_handling_directive = {
        "ready": "deliver",
        "hold": "defer",
        "needs_review": "route_for_review",
    }[expected_classification]
    expected_action_label = {
        "deliver": "dispatch",
        "defer": "wait",
        "route_for_review": "review_queue",
    }[expected_handling_directive]
    expected_dispatch_intent = {
        "dispatch": "send",
        "wait": "park",
        "review_queue": "review",
    }[expected_action_label]
    expected_dispatch_mode = {
        "send": "active",
        "park": "queued",
        "review": "review_pending",
    }[expected_dispatch_intent]
    expected_release_gate = {
        "active": "open",
        "queued": "deferred",
        "review_pending": "blocked_for_review",
    }[expected_dispatch_mode]
    expected_progress_state = {
        "open": "in_progress",
        "deferred": "pending",
        "blocked_for_review": "review_hold",
    }[expected_release_gate]
    expected_progress_signal = {
        "in_progress": "advance",
        "pending": "await",
        "review_hold": "review_wait",
    }[expected_progress_state]
    expected_progress_outcome = {
        "advance": "moving",
        "await": "standing_by",
        "review_wait": "awaiting_review",
    }[expected_progress_signal]
    expected_intervention_requirement = {
        "moving": "none",
        "standing_by": "monitor",
        "awaiting_review": "review_required",
    }[expected_progress_outcome]
    attention_level_by_intervention_requirement = {
        "none": "low",
        "monitor": "medium",
        "review_required": "high",
    }
    notification_requirement_by_attention_level = {
        "low": "none",
        "medium": "notify",
        "high": "escalate",
    }
    response_priority_by_notification_requirement = {
        "none": "normal",
        "notify": "elevated",
        "escalate": "urgent",
    }
    response_channel_by_priority = {
        "normal": "standard_channel",
        "elevated": "priority_channel",
        "urgent": "escalation_channel",
    }
    followup_requirement_by_route = {
        "standard_route": "none",
        "priority_route": "follow_up",
        "escalation_route": "escalation_follow_up",
    }
    assert (
        attention_level_by_intervention_requirement[expected_intervention_requirement]
        == expected_attention_level
    )
    assert (
        notification_requirement_by_attention_level[expected_attention_level]
        == expected_notification_requirement
    )
    assert (
        response_priority_by_notification_requirement[expected_notification_requirement]
        == expected_response_priority
    )
    assert response_channel_by_priority[expected_response_priority] == expected_response_channel
    assert followup_requirement_by_route[expected_response_route] == expected_followup_requirement
    consumer_receiver_response_route = {
        "projected_activation_decision": {"recommendation": decision},
        "approval_record": {
            "human_approval_status": {
                "status": {
                    "GO": "approved",
                    "PAUSE": "pending",
                    "REVIEW": "withheld",
                }[decision]
            }
        },
        "receiver_readiness_classification": expected_classification,
        "receiver_handling_directive": expected_handling_directive,
        "receiver_action_label": expected_action_label,
        "receiver_dispatch_intent": expected_dispatch_intent,
        "receiver_dispatch_mode": expected_dispatch_mode,
        "receiver_release_gate": expected_release_gate,
        "receiver_progress_state": expected_progress_state,
        "receiver_progress_signal": expected_progress_signal,
        "receiver_progress_outcome": expected_progress_outcome,
        "receiver_intervention_requirement": expected_intervention_requirement,
        "receiver_attention_level": expected_attention_level,
        "receiver_notification_requirement": expected_notification_requirement,
        "receiver_response_priority": expected_response_priority,
        "receiver_response_channel": expected_response_channel,
        "receiver_response_route": expected_response_route,
        "related_project_id": "project_consumer_receiver_followup_requirement_1",
        "related_activation_decision_id": (
            "activation_decision_consumer_receiver_followup_requirement_1"
        ),
        "related_packet_id": "packet_consumer_receiver_followup_requirement_1",
        "related_queue_item_id": "queue_consumer_receiver_followup_requirement_1",
    }

    receiver_followup_requirement = (
        build_consumer_receiver_followup_requirement_from_response_route(
            consumer_receiver_response_route=consumer_receiver_response_route
        )
    )

    assert (
        receiver_followup_requirement["projected_activation_decision"]
        == consumer_receiver_response_route["projected_activation_decision"]
    )
    assert (
        receiver_followup_requirement["approval_record"]
        == consumer_receiver_response_route["approval_record"]
    )
    assert (
        receiver_followup_requirement["receiver_readiness_classification"]
        == consumer_receiver_response_route["receiver_readiness_classification"]
    )
    assert (
        receiver_followup_requirement["receiver_handling_directive"]
        == consumer_receiver_response_route["receiver_handling_directive"]
    )
    assert (
        receiver_followup_requirement["receiver_action_label"]
        == consumer_receiver_response_route["receiver_action_label"]
    )
    assert (
        receiver_followup_requirement["receiver_dispatch_intent"]
        == consumer_receiver_response_route["receiver_dispatch_intent"]
    )
    assert (
        receiver_followup_requirement["receiver_dispatch_mode"]
        == consumer_receiver_response_route["receiver_dispatch_mode"]
    )
    assert (
        receiver_followup_requirement["receiver_release_gate"]
        == consumer_receiver_response_route["receiver_release_gate"]
    )
    assert (
        receiver_followup_requirement["receiver_progress_state"]
        == consumer_receiver_response_route["receiver_progress_state"]
    )
    assert (
        receiver_followup_requirement["receiver_progress_signal"]
        == consumer_receiver_response_route["receiver_progress_signal"]
    )
    assert (
        receiver_followup_requirement["receiver_progress_outcome"]
        == consumer_receiver_response_route["receiver_progress_outcome"]
    )
    assert (
        receiver_followup_requirement["receiver_intervention_requirement"]
        == consumer_receiver_response_route["receiver_intervention_requirement"]
    )
    assert (
        receiver_followup_requirement["receiver_attention_level"]
        == consumer_receiver_response_route["receiver_attention_level"]
    )
    assert (
        receiver_followup_requirement["receiver_notification_requirement"]
        == consumer_receiver_response_route["receiver_notification_requirement"]
    )
    assert (
        receiver_followup_requirement["receiver_response_priority"]
        == consumer_receiver_response_route["receiver_response_priority"]
    )
    assert (
        receiver_followup_requirement["receiver_response_channel"]
        == consumer_receiver_response_route["receiver_response_channel"]
    )
    assert (
        receiver_followup_requirement["receiver_response_route"]
        == consumer_receiver_response_route["receiver_response_route"]
    )
    assert (
        receiver_followup_requirement["related_project_id"]
        == consumer_receiver_response_route["related_project_id"]
    )
    assert (
        receiver_followup_requirement["related_activation_decision_id"]
        == consumer_receiver_response_route["related_activation_decision_id"]
    )
    assert (
        receiver_followup_requirement["related_packet_id"]
        == consumer_receiver_response_route["related_packet_id"]
    )
    assert (
        receiver_followup_requirement["related_queue_item_id"]
        == consumer_receiver_response_route["related_queue_item_id"]
    )
    assert (
        receiver_followup_requirement["receiver_followup_requirement"]
        == expected_followup_requirement
    )


@pytest.mark.parametrize(
    (
        "decision",
        "expected_attention_level",
        "expected_notification_requirement",
        "expected_response_priority",
        "expected_response_channel",
        "expected_response_route",
        "expected_followup_requirement",
    ),
    [
        pytest.param(
            "GO",
            "low",
            "none",
            "normal",
            "standard_channel",
            "standard_route",
            "none",
            id="go",
        ),
        pytest.param(
            "PAUSE",
            "medium",
            "notify",
            "elevated",
            "priority_channel",
            "priority_route",
            "follow_up",
            id="pause",
        ),
        pytest.param(
            "REVIEW",
            "high",
            "escalate",
            "urgent",
            "escalation_channel",
            "escalation_route",
            "escalation_follow_up",
            id="review",
        ),
    ],
)
def test_consumer_decision_surface_from_followup_requirement_matches_followup_requirement(
    decision: RecommendationValue,
    expected_attention_level: str,
    expected_notification_requirement: str,
    expected_response_priority: str,
    expected_response_channel: str,
    expected_response_route: str,
    expected_followup_requirement: str,
) -> None:
    expected_classification = {
        "GO": "ready",
        "PAUSE": "hold",
        "REVIEW": "needs_review",
    }[decision]
    expected_handling_directive = {
        "ready": "deliver",
        "hold": "defer",
        "needs_review": "route_for_review",
    }[expected_classification]
    expected_action_label = {
        "deliver": "dispatch",
        "defer": "wait",
        "route_for_review": "review_queue",
    }[expected_handling_directive]
    expected_dispatch_intent = {
        "dispatch": "send",
        "wait": "park",
        "review_queue": "review",
    }[expected_action_label]
    expected_dispatch_mode = {
        "send": "active",
        "park": "queued",
        "review": "review_pending",
    }[expected_dispatch_intent]
    expected_release_gate = {
        "active": "open",
        "queued": "deferred",
        "review_pending": "blocked_for_review",
    }[expected_dispatch_mode]
    expected_progress_state = {
        "open": "in_progress",
        "deferred": "pending",
        "blocked_for_review": "review_hold",
    }[expected_release_gate]
    expected_progress_signal = {
        "in_progress": "advance",
        "pending": "await",
        "review_hold": "review_wait",
    }[expected_progress_state]
    expected_progress_outcome = {
        "advance": "moving",
        "await": "standing_by",
        "review_wait": "awaiting_review",
    }[expected_progress_signal]
    expected_intervention_requirement = {
        "moving": "none",
        "standing_by": "monitor",
        "awaiting_review": "review_required",
    }[expected_progress_outcome]
    attention_level_by_intervention_requirement = {
        "none": "low",
        "monitor": "medium",
        "review_required": "high",
    }
    notification_requirement_by_attention_level = {
        "low": "none",
        "medium": "notify",
        "high": "escalate",
    }
    response_priority_by_notification_requirement = {
        "none": "normal",
        "notify": "elevated",
        "escalate": "urgent",
    }
    response_channel_by_priority = {
        "normal": "standard_channel",
        "elevated": "priority_channel",
        "urgent": "escalation_channel",
    }
    followup_requirement_by_route = {
        "standard_route": "none",
        "priority_route": "follow_up",
        "escalation_route": "escalation_follow_up",
    }
    assert (
        attention_level_by_intervention_requirement[expected_intervention_requirement]
        == expected_attention_level
    )
    assert (
        notification_requirement_by_attention_level[expected_attention_level]
        == expected_notification_requirement
    )
    assert (
        response_priority_by_notification_requirement[expected_notification_requirement]
        == expected_response_priority
    )
    assert response_channel_by_priority[expected_response_priority] == expected_response_channel
    assert followup_requirement_by_route[expected_response_route] == expected_followup_requirement
    consumer_receiver_followup_requirement = {
        "projected_activation_decision": {"recommendation": decision},
        "approval_record": {
            "human_approval_status": {
                "status": {
                    "GO": "approved",
                    "PAUSE": "pending",
                    "REVIEW": "withheld",
                }[decision]
            }
        },
        "receiver_readiness_classification": expected_classification,
        "receiver_handling_directive": expected_handling_directive,
        "receiver_action_label": expected_action_label,
        "receiver_dispatch_intent": expected_dispatch_intent,
        "receiver_dispatch_mode": expected_dispatch_mode,
        "receiver_release_gate": expected_release_gate,
        "receiver_progress_state": expected_progress_state,
        "receiver_progress_signal": expected_progress_signal,
        "receiver_progress_outcome": expected_progress_outcome,
        "receiver_intervention_requirement": expected_intervention_requirement,
        "receiver_attention_level": expected_attention_level,
        "receiver_notification_requirement": expected_notification_requirement,
        "receiver_response_priority": expected_response_priority,
        "receiver_response_channel": expected_response_channel,
        "receiver_response_route": expected_response_route,
        "receiver_followup_requirement": expected_followup_requirement,
        "related_project_id": "project_consumer_decision_surface_1",
        "related_activation_decision_id": "activation_decision_consumer_decision_surface_1",
        "related_packet_id": "packet_consumer_decision_surface_1",
        "related_queue_item_id": "queue_consumer_decision_surface_1",
    }

    consumer_decision_surface = build_consumer_decision_surface_from_followup_requirement(
        consumer_receiver_followup_requirement=consumer_receiver_followup_requirement
    )

    assert consumer_decision_surface == consumer_receiver_followup_requirement


@pytest.mark.parametrize(
    (
        "decision",
        "expected_attention_level",
        "expected_notification_requirement",
        "expected_response_priority",
        "expected_response_channel",
        "expected_response_route",
        "expected_followup_requirement",
        "expected_consumer_decision_posture",
    ),
    [
        pytest.param(
            "GO",
            "low",
            "none",
            "normal",
            "standard_channel",
            "standard_route",
            "none",
            "observe",
            id="go",
        ),
        pytest.param(
            "PAUSE",
            "medium",
            "notify",
            "elevated",
            "priority_channel",
            "priority_route",
            "follow_up",
            "engage",
            id="pause",
        ),
        pytest.param(
            "REVIEW",
            "high",
            "escalate",
            "urgent",
            "escalation_channel",
            "escalation_route",
            "escalation_follow_up",
            "escalate",
            id="review",
        ),
    ],
)
def test_consumer_decision_posture_from_surface_matches_surface(
    decision: RecommendationValue,
    expected_attention_level: str,
    expected_notification_requirement: str,
    expected_response_priority: str,
    expected_response_channel: str,
    expected_response_route: str,
    expected_followup_requirement: str,
    expected_consumer_decision_posture: str,
) -> None:
    expected_classification = {
        "GO": "ready",
        "PAUSE": "hold",
        "REVIEW": "needs_review",
    }[decision]
    expected_handling_directive = {
        "ready": "deliver",
        "hold": "defer",
        "needs_review": "route_for_review",
    }[expected_classification]
    expected_action_label = {
        "deliver": "dispatch",
        "defer": "wait",
        "route_for_review": "review_queue",
    }[expected_handling_directive]
    expected_dispatch_intent = {
        "dispatch": "send",
        "wait": "park",
        "review_queue": "review",
    }[expected_action_label]
    expected_dispatch_mode = {
        "send": "active",
        "park": "queued",
        "review": "review_pending",
    }[expected_dispatch_intent]
    expected_release_gate = {
        "active": "open",
        "queued": "deferred",
        "review_pending": "blocked_for_review",
    }[expected_dispatch_mode]
    expected_progress_state = {
        "open": "in_progress",
        "deferred": "pending",
        "blocked_for_review": "review_hold",
    }[expected_release_gate]
    expected_progress_signal = {
        "in_progress": "advance",
        "pending": "await",
        "review_hold": "review_wait",
    }[expected_progress_state]
    expected_progress_outcome = {
        "advance": "moving",
        "await": "standing_by",
        "review_wait": "awaiting_review",
    }[expected_progress_signal]
    expected_intervention_requirement = {
        "moving": "none",
        "standing_by": "monitor",
        "awaiting_review": "review_required",
    }[expected_progress_outcome]
    attention_level_by_intervention_requirement = {
        "none": "low",
        "monitor": "medium",
        "review_required": "high",
    }
    notification_requirement_by_attention_level = {
        "low": "none",
        "medium": "notify",
        "high": "escalate",
    }
    response_priority_by_notification_requirement = {
        "none": "normal",
        "notify": "elevated",
        "escalate": "urgent",
    }
    response_channel_by_priority = {
        "normal": "standard_channel",
        "elevated": "priority_channel",
        "urgent": "escalation_channel",
    }
    followup_requirement_by_route = {
        "standard_route": "none",
        "priority_route": "follow_up",
        "escalation_route": "escalation_follow_up",
    }
    posture_by_followup_requirement = {
        "none": "observe",
        "follow_up": "engage",
        "escalation_follow_up": "escalate",
    }
    assert (
        attention_level_by_intervention_requirement[expected_intervention_requirement]
        == expected_attention_level
    )
    assert (
        notification_requirement_by_attention_level[expected_attention_level]
        == expected_notification_requirement
    )
    assert (
        response_priority_by_notification_requirement[expected_notification_requirement]
        == expected_response_priority
    )
    assert response_channel_by_priority[expected_response_priority] == expected_response_channel
    assert followup_requirement_by_route[expected_response_route] == expected_followup_requirement
    assert (
        posture_by_followup_requirement[expected_followup_requirement]
        == expected_consumer_decision_posture
    )
    consumer_decision_surface = {
        "projected_activation_decision": {"recommendation": decision},
        "approval_record": {
            "human_approval_status": {
                "status": {
                    "GO": "approved",
                    "PAUSE": "pending",
                    "REVIEW": "withheld",
                }[decision]
            }
        },
        "receiver_readiness_classification": expected_classification,
        "receiver_handling_directive": expected_handling_directive,
        "receiver_action_label": expected_action_label,
        "receiver_dispatch_intent": expected_dispatch_intent,
        "receiver_dispatch_mode": expected_dispatch_mode,
        "receiver_release_gate": expected_release_gate,
        "receiver_progress_state": expected_progress_state,
        "receiver_progress_signal": expected_progress_signal,
        "receiver_progress_outcome": expected_progress_outcome,
        "receiver_intervention_requirement": expected_intervention_requirement,
        "receiver_attention_level": expected_attention_level,
        "receiver_notification_requirement": expected_notification_requirement,
        "receiver_response_priority": expected_response_priority,
        "receiver_response_channel": expected_response_channel,
        "receiver_response_route": expected_response_route,
        "receiver_followup_requirement": expected_followup_requirement,
        "related_project_id": "project_consumer_decision_posture_1",
        "related_activation_decision_id": "activation_decision_consumer_decision_posture_1",
        "related_packet_id": "packet_consumer_decision_posture_1",
        "related_queue_item_id": "queue_consumer_decision_posture_1",
    }

    consumer_decision_posture = build_consumer_decision_posture_from_surface(
        consumer_decision_surface=consumer_decision_surface
    )

    assert (
        consumer_decision_posture["projected_activation_decision"]
        == consumer_decision_surface["projected_activation_decision"]
    )
    assert consumer_decision_posture["approval_record"] == consumer_decision_surface[
        "approval_record"
    ]
    assert (
        consumer_decision_posture["receiver_readiness_classification"]
        == consumer_decision_surface["receiver_readiness_classification"]
    )
    assert (
        consumer_decision_posture["receiver_handling_directive"]
        == consumer_decision_surface["receiver_handling_directive"]
    )
    assert (
        consumer_decision_posture["receiver_action_label"]
        == consumer_decision_surface["receiver_action_label"]
    )
    assert (
        consumer_decision_posture["receiver_dispatch_intent"]
        == consumer_decision_surface["receiver_dispatch_intent"]
    )
    assert (
        consumer_decision_posture["receiver_dispatch_mode"]
        == consumer_decision_surface["receiver_dispatch_mode"]
    )
    assert (
        consumer_decision_posture["receiver_release_gate"]
        == consumer_decision_surface["receiver_release_gate"]
    )
    assert (
        consumer_decision_posture["receiver_progress_state"]
        == consumer_decision_surface["receiver_progress_state"]
    )
    assert (
        consumer_decision_posture["receiver_progress_signal"]
        == consumer_decision_surface["receiver_progress_signal"]
    )
    assert (
        consumer_decision_posture["receiver_progress_outcome"]
        == consumer_decision_surface["receiver_progress_outcome"]
    )
    assert (
        consumer_decision_posture["receiver_intervention_requirement"]
        == consumer_decision_surface["receiver_intervention_requirement"]
    )
    assert (
        consumer_decision_posture["receiver_attention_level"]
        == consumer_decision_surface["receiver_attention_level"]
    )
    assert (
        consumer_decision_posture["receiver_notification_requirement"]
        == consumer_decision_surface["receiver_notification_requirement"]
    )
    assert (
        consumer_decision_posture["receiver_response_priority"]
        == consumer_decision_surface["receiver_response_priority"]
    )
    assert (
        consumer_decision_posture["receiver_response_channel"]
        == consumer_decision_surface["receiver_response_channel"]
    )
    assert (
        consumer_decision_posture["receiver_response_route"]
        == consumer_decision_surface["receiver_response_route"]
    )
    assert (
        consumer_decision_posture["receiver_followup_requirement"]
        == consumer_decision_surface["receiver_followup_requirement"]
    )
    assert (
        consumer_decision_posture["related_project_id"]
        == consumer_decision_surface["related_project_id"]
    )
    assert (
        consumer_decision_posture["related_activation_decision_id"]
        == consumer_decision_surface["related_activation_decision_id"]
    )
    assert (
        consumer_decision_posture["related_packet_id"]
        == consumer_decision_surface["related_packet_id"]
    )
    assert (
        consumer_decision_posture["related_queue_item_id"]
        == consumer_decision_surface["related_queue_item_id"]
    )
    assert (
        consumer_decision_posture["consumer_decision_posture"]
        == expected_consumer_decision_posture
    )


@pytest.mark.parametrize(
    (
        "decision",
        "expected_attention_level",
        "expected_notification_requirement",
        "expected_response_priority",
        "expected_response_channel",
        "expected_response_route",
        "expected_followup_requirement",
        "expected_consumer_decision_posture",
        "expected_consumer_action_requirement",
    ),
    [
        pytest.param(
            "GO",
            "low",
            "none",
            "normal",
            "standard_channel",
            "standard_route",
            "none",
            "observe",
            "no_action",
            id="go",
        ),
        pytest.param(
            "PAUSE",
            "medium",
            "notify",
            "elevated",
            "priority_channel",
            "priority_route",
            "follow_up",
            "engage",
            "action_required",
            id="pause",
        ),
        pytest.param(
            "REVIEW",
            "high",
            "escalate",
            "urgent",
            "escalation_channel",
            "escalation_route",
            "escalation_follow_up",
            "escalate",
            "escalation_required",
            id="review",
        ),
    ],
)
def test_consumer_action_requirement_from_posture_matches_posture(
    decision: RecommendationValue,
    expected_attention_level: str,
    expected_notification_requirement: str,
    expected_response_priority: str,
    expected_response_channel: str,
    expected_response_route: str,
    expected_followup_requirement: str,
    expected_consumer_decision_posture: str,
    expected_consumer_action_requirement: str,
) -> None:
    expected_classification = {
        "GO": "ready",
        "PAUSE": "hold",
        "REVIEW": "needs_review",
    }[decision]
    expected_handling_directive = {
        "ready": "deliver",
        "hold": "defer",
        "needs_review": "route_for_review",
    }[expected_classification]
    expected_action_label = {
        "deliver": "dispatch",
        "defer": "wait",
        "route_for_review": "review_queue",
    }[expected_handling_directive]
    expected_dispatch_intent = {
        "dispatch": "send",
        "wait": "park",
        "review_queue": "review",
    }[expected_action_label]
    expected_dispatch_mode = {
        "send": "active",
        "park": "queued",
        "review": "review_pending",
    }[expected_dispatch_intent]
    expected_release_gate = {
        "active": "open",
        "queued": "deferred",
        "review_pending": "blocked_for_review",
    }[expected_dispatch_mode]
    expected_progress_state = {
        "open": "in_progress",
        "deferred": "pending",
        "blocked_for_review": "review_hold",
    }[expected_release_gate]
    expected_progress_signal = {
        "in_progress": "advance",
        "pending": "await",
        "review_hold": "review_wait",
    }[expected_progress_state]
    expected_progress_outcome = {
        "advance": "moving",
        "await": "standing_by",
        "review_wait": "awaiting_review",
    }[expected_progress_signal]
    expected_intervention_requirement = {
        "moving": "none",
        "standing_by": "monitor",
        "awaiting_review": "review_required",
    }[expected_progress_outcome]
    attention_level_by_intervention_requirement = {
        "none": "low",
        "monitor": "medium",
        "review_required": "high",
    }
    notification_requirement_by_attention_level = {
        "low": "none",
        "medium": "notify",
        "high": "escalate",
    }
    response_priority_by_notification_requirement = {
        "none": "normal",
        "notify": "elevated",
        "escalate": "urgent",
    }
    response_channel_by_priority = {
        "normal": "standard_channel",
        "elevated": "priority_channel",
        "urgent": "escalation_channel",
    }
    followup_requirement_by_route = {
        "standard_route": "none",
        "priority_route": "follow_up",
        "escalation_route": "escalation_follow_up",
    }
    posture_by_followup_requirement = {
        "none": "observe",
        "follow_up": "engage",
        "escalation_follow_up": "escalate",
    }
    action_requirement_by_posture = {
        "observe": "no_action",
        "engage": "action_required",
        "escalate": "escalation_required",
    }
    assert (
        attention_level_by_intervention_requirement[expected_intervention_requirement]
        == expected_attention_level
    )
    assert (
        notification_requirement_by_attention_level[expected_attention_level]
        == expected_notification_requirement
    )
    assert (
        response_priority_by_notification_requirement[expected_notification_requirement]
        == expected_response_priority
    )
    assert response_channel_by_priority[expected_response_priority] == expected_response_channel
    assert followup_requirement_by_route[expected_response_route] == expected_followup_requirement
    assert (
        posture_by_followup_requirement[expected_followup_requirement]
        == expected_consumer_decision_posture
    )
    assert (
        action_requirement_by_posture[expected_consumer_decision_posture]
        == expected_consumer_action_requirement
    )
    consumer_decision_posture = {
        "projected_activation_decision": {"recommendation": decision},
        "approval_record": {
            "human_approval_status": {
                "status": {
                    "GO": "approved",
                    "PAUSE": "pending",
                    "REVIEW": "withheld",
                }[decision]
            }
        },
        "receiver_readiness_classification": expected_classification,
        "receiver_handling_directive": expected_handling_directive,
        "receiver_action_label": expected_action_label,
        "receiver_dispatch_intent": expected_dispatch_intent,
        "receiver_dispatch_mode": expected_dispatch_mode,
        "receiver_release_gate": expected_release_gate,
        "receiver_progress_state": expected_progress_state,
        "receiver_progress_signal": expected_progress_signal,
        "receiver_progress_outcome": expected_progress_outcome,
        "receiver_intervention_requirement": expected_intervention_requirement,
        "receiver_attention_level": expected_attention_level,
        "receiver_notification_requirement": expected_notification_requirement,
        "receiver_response_priority": expected_response_priority,
        "receiver_response_channel": expected_response_channel,
        "receiver_response_route": expected_response_route,
        "receiver_followup_requirement": expected_followup_requirement,
        "consumer_decision_posture": expected_consumer_decision_posture,
        "related_project_id": "project_consumer_action_requirement_1",
        "related_activation_decision_id": "activation_decision_consumer_action_requirement_1",
        "related_packet_id": "packet_consumer_action_requirement_1",
        "related_queue_item_id": "queue_consumer_action_requirement_1",
    }

    consumer_action_requirement = build_consumer_action_requirement_from_posture(
        consumer_decision_posture=consumer_decision_posture
    )

    assert (
        consumer_action_requirement["projected_activation_decision"]
        == consumer_decision_posture["projected_activation_decision"]
    )
    assert consumer_action_requirement["approval_record"] == consumer_decision_posture[
        "approval_record"
    ]
    assert (
        consumer_action_requirement["receiver_readiness_classification"]
        == consumer_decision_posture["receiver_readiness_classification"]
    )
    assert (
        consumer_action_requirement["receiver_handling_directive"]
        == consumer_decision_posture["receiver_handling_directive"]
    )
    assert (
        consumer_action_requirement["receiver_action_label"]
        == consumer_decision_posture["receiver_action_label"]
    )
    assert (
        consumer_action_requirement["receiver_dispatch_intent"]
        == consumer_decision_posture["receiver_dispatch_intent"]
    )
    assert (
        consumer_action_requirement["receiver_dispatch_mode"]
        == consumer_decision_posture["receiver_dispatch_mode"]
    )
    assert (
        consumer_action_requirement["receiver_release_gate"]
        == consumer_decision_posture["receiver_release_gate"]
    )
    assert (
        consumer_action_requirement["receiver_progress_state"]
        == consumer_decision_posture["receiver_progress_state"]
    )
    assert (
        consumer_action_requirement["receiver_progress_signal"]
        == consumer_decision_posture["receiver_progress_signal"]
    )
    assert (
        consumer_action_requirement["receiver_progress_outcome"]
        == consumer_decision_posture["receiver_progress_outcome"]
    )
    assert (
        consumer_action_requirement["receiver_intervention_requirement"]
        == consumer_decision_posture["receiver_intervention_requirement"]
    )
    assert (
        consumer_action_requirement["receiver_attention_level"]
        == consumer_decision_posture["receiver_attention_level"]
    )
    assert (
        consumer_action_requirement["receiver_notification_requirement"]
        == consumer_decision_posture["receiver_notification_requirement"]
    )
    assert (
        consumer_action_requirement["receiver_response_priority"]
        == consumer_decision_posture["receiver_response_priority"]
    )
    assert (
        consumer_action_requirement["receiver_response_channel"]
        == consumer_decision_posture["receiver_response_channel"]
    )
    assert (
        consumer_action_requirement["receiver_response_route"]
        == consumer_decision_posture["receiver_response_route"]
    )
    assert (
        consumer_action_requirement["receiver_followup_requirement"]
        == consumer_decision_posture["receiver_followup_requirement"]
    )
    assert (
        consumer_action_requirement["consumer_decision_posture"]
        == consumer_decision_posture["consumer_decision_posture"]
    )
    assert (
        consumer_action_requirement["related_project_id"]
        == consumer_decision_posture["related_project_id"]
    )
    assert (
        consumer_action_requirement["related_activation_decision_id"]
        == consumer_decision_posture["related_activation_decision_id"]
    )
    assert (
        consumer_action_requirement["related_packet_id"]
        == consumer_decision_posture["related_packet_id"]
    )
    assert (
        consumer_action_requirement["related_queue_item_id"]
        == consumer_decision_posture["related_queue_item_id"]
    )
    assert (
        consumer_action_requirement["consumer_action_requirement"]
        == expected_consumer_action_requirement
    )


@pytest.mark.parametrize(
    (
        "decision",
        "expected_attention_level",
        "expected_notification_requirement",
        "expected_response_priority",
        "expected_response_channel",
        "expected_response_route",
        "expected_followup_requirement",
        "expected_consumer_decision_posture",
        "expected_consumer_action_requirement",
        "expected_consumer_work_queue_assignment",
    ),
    [
        pytest.param(
            "GO",
            "low",
            "none",
            "normal",
            "standard_channel",
            "standard_route",
            "none",
            "observe",
            "no_action",
            "observation_queue",
            id="go",
        ),
        pytest.param(
            "PAUSE",
            "medium",
            "notify",
            "elevated",
            "priority_channel",
            "priority_route",
            "follow_up",
            "engage",
            "action_required",
            "action_queue",
            id="pause",
        ),
        pytest.param(
            "REVIEW",
            "high",
            "escalate",
            "urgent",
            "escalation_channel",
            "escalation_route",
            "escalation_follow_up",
            "escalate",
            "escalation_required",
            "escalation_queue",
            id="review",
        ),
    ],
)
def test_consumer_work_queue_assignment_from_action_requirement_matches_action_requirement(
    decision: RecommendationValue,
    expected_attention_level: str,
    expected_notification_requirement: str,
    expected_response_priority: str,
    expected_response_channel: str,
    expected_response_route: str,
    expected_followup_requirement: str,
    expected_consumer_decision_posture: str,
    expected_consumer_action_requirement: str,
    expected_consumer_work_queue_assignment: str,
) -> None:
    expected_classification = {
        "GO": "ready",
        "PAUSE": "hold",
        "REVIEW": "needs_review",
    }[decision]
    expected_handling_directive = {
        "ready": "deliver",
        "hold": "defer",
        "needs_review": "route_for_review",
    }[expected_classification]
    expected_action_label = {
        "deliver": "dispatch",
        "defer": "wait",
        "route_for_review": "review_queue",
    }[expected_handling_directive]
    expected_dispatch_intent = {
        "dispatch": "send",
        "wait": "park",
        "review_queue": "review",
    }[expected_action_label]
    expected_dispatch_mode = {
        "send": "active",
        "park": "queued",
        "review": "review_pending",
    }[expected_dispatch_intent]
    expected_release_gate = {
        "active": "open",
        "queued": "deferred",
        "review_pending": "blocked_for_review",
    }[expected_dispatch_mode]
    expected_progress_state = {
        "open": "in_progress",
        "deferred": "pending",
        "blocked_for_review": "review_hold",
    }[expected_release_gate]
    expected_progress_signal = {
        "in_progress": "advance",
        "pending": "await",
        "review_hold": "review_wait",
    }[expected_progress_state]
    expected_progress_outcome = {
        "advance": "moving",
        "await": "standing_by",
        "review_wait": "awaiting_review",
    }[expected_progress_signal]
    expected_intervention_requirement = {
        "moving": "none",
        "standing_by": "monitor",
        "awaiting_review": "review_required",
    }[expected_progress_outcome]
    attention_level_by_intervention_requirement = {
        "none": "low",
        "monitor": "medium",
        "review_required": "high",
    }
    notification_requirement_by_attention_level = {
        "low": "none",
        "medium": "notify",
        "high": "escalate",
    }
    response_priority_by_notification_requirement = {
        "none": "normal",
        "notify": "elevated",
        "escalate": "urgent",
    }
    response_channel_by_priority = {
        "normal": "standard_channel",
        "elevated": "priority_channel",
        "urgent": "escalation_channel",
    }
    followup_requirement_by_route = {
        "standard_route": "none",
        "priority_route": "follow_up",
        "escalation_route": "escalation_follow_up",
    }
    posture_by_followup_requirement = {
        "none": "observe",
        "follow_up": "engage",
        "escalation_follow_up": "escalate",
    }
    action_requirement_by_posture = {
        "observe": "no_action",
        "engage": "action_required",
        "escalate": "escalation_required",
    }
    queue_assignment_by_action_requirement = {
        "no_action": "observation_queue",
        "action_required": "action_queue",
        "escalation_required": "escalation_queue",
    }
    assert (
        attention_level_by_intervention_requirement[expected_intervention_requirement]
        == expected_attention_level
    )
    assert (
        notification_requirement_by_attention_level[expected_attention_level]
        == expected_notification_requirement
    )
    assert (
        response_priority_by_notification_requirement[expected_notification_requirement]
        == expected_response_priority
    )
    assert response_channel_by_priority[expected_response_priority] == expected_response_channel
    assert followup_requirement_by_route[expected_response_route] == expected_followup_requirement
    assert (
        posture_by_followup_requirement[expected_followup_requirement]
        == expected_consumer_decision_posture
    )
    assert (
        action_requirement_by_posture[expected_consumer_decision_posture]
        == expected_consumer_action_requirement
    )
    assert (
        queue_assignment_by_action_requirement[expected_consumer_action_requirement]
        == expected_consumer_work_queue_assignment
    )
    consumer_action_requirement = {
        "projected_activation_decision": {"recommendation": decision},
        "approval_record": {
            "human_approval_status": {
                "status": {
                    "GO": "approved",
                    "PAUSE": "pending",
                    "REVIEW": "withheld",
                }[decision]
            }
        },
        "receiver_readiness_classification": expected_classification,
        "receiver_handling_directive": expected_handling_directive,
        "receiver_action_label": expected_action_label,
        "receiver_dispatch_intent": expected_dispatch_intent,
        "receiver_dispatch_mode": expected_dispatch_mode,
        "receiver_release_gate": expected_release_gate,
        "receiver_progress_state": expected_progress_state,
        "receiver_progress_signal": expected_progress_signal,
        "receiver_progress_outcome": expected_progress_outcome,
        "receiver_intervention_requirement": expected_intervention_requirement,
        "receiver_attention_level": expected_attention_level,
        "receiver_notification_requirement": expected_notification_requirement,
        "receiver_response_priority": expected_response_priority,
        "receiver_response_channel": expected_response_channel,
        "receiver_response_route": expected_response_route,
        "receiver_followup_requirement": expected_followup_requirement,
        "consumer_decision_posture": expected_consumer_decision_posture,
        "consumer_action_requirement": expected_consumer_action_requirement,
        "related_project_id": "project_consumer_work_queue_assignment_1",
        "related_activation_decision_id": (
            "activation_decision_consumer_work_queue_assignment_1"
        ),
        "related_packet_id": "packet_consumer_work_queue_assignment_1",
        "related_queue_item_id": "queue_consumer_work_queue_assignment_1",
    }

    consumer_work_queue_assignment = (
        build_consumer_work_queue_assignment_from_action_requirement(
            consumer_action_requirement=consumer_action_requirement
        )
    )

    assert (
        consumer_work_queue_assignment["projected_activation_decision"]
        == consumer_action_requirement["projected_activation_decision"]
    )
    assert consumer_work_queue_assignment["approval_record"] == consumer_action_requirement[
        "approval_record"
    ]
    assert (
        consumer_work_queue_assignment["receiver_readiness_classification"]
        == consumer_action_requirement["receiver_readiness_classification"]
    )
    assert (
        consumer_work_queue_assignment["receiver_handling_directive"]
        == consumer_action_requirement["receiver_handling_directive"]
    )
    assert (
        consumer_work_queue_assignment["receiver_action_label"]
        == consumer_action_requirement["receiver_action_label"]
    )
    assert (
        consumer_work_queue_assignment["receiver_dispatch_intent"]
        == consumer_action_requirement["receiver_dispatch_intent"]
    )
    assert (
        consumer_work_queue_assignment["receiver_dispatch_mode"]
        == consumer_action_requirement["receiver_dispatch_mode"]
    )
    assert (
        consumer_work_queue_assignment["receiver_release_gate"]
        == consumer_action_requirement["receiver_release_gate"]
    )
    assert (
        consumer_work_queue_assignment["receiver_progress_state"]
        == consumer_action_requirement["receiver_progress_state"]
    )
    assert (
        consumer_work_queue_assignment["receiver_progress_signal"]
        == consumer_action_requirement["receiver_progress_signal"]
    )
    assert (
        consumer_work_queue_assignment["receiver_progress_outcome"]
        == consumer_action_requirement["receiver_progress_outcome"]
    )
    assert (
        consumer_work_queue_assignment["receiver_intervention_requirement"]
        == consumer_action_requirement["receiver_intervention_requirement"]
    )
    assert (
        consumer_work_queue_assignment["receiver_attention_level"]
        == consumer_action_requirement["receiver_attention_level"]
    )
    assert (
        consumer_work_queue_assignment["receiver_notification_requirement"]
        == consumer_action_requirement["receiver_notification_requirement"]
    )
    assert (
        consumer_work_queue_assignment["receiver_response_priority"]
        == consumer_action_requirement["receiver_response_priority"]
    )
    assert (
        consumer_work_queue_assignment["receiver_response_channel"]
        == consumer_action_requirement["receiver_response_channel"]
    )
    assert (
        consumer_work_queue_assignment["receiver_response_route"]
        == consumer_action_requirement["receiver_response_route"]
    )
    assert (
        consumer_work_queue_assignment["receiver_followup_requirement"]
        == consumer_action_requirement["receiver_followup_requirement"]
    )
    assert (
        consumer_work_queue_assignment["consumer_decision_posture"]
        == consumer_action_requirement["consumer_decision_posture"]
    )
    assert (
        consumer_work_queue_assignment["consumer_action_requirement"]
        == consumer_action_requirement["consumer_action_requirement"]
    )
    assert (
        consumer_work_queue_assignment["related_project_id"]
        == consumer_action_requirement["related_project_id"]
    )
    assert (
        consumer_work_queue_assignment["related_activation_decision_id"]
        == consumer_action_requirement["related_activation_decision_id"]
    )
    assert (
        consumer_work_queue_assignment["related_packet_id"]
        == consumer_action_requirement["related_packet_id"]
    )
    assert (
        consumer_work_queue_assignment["related_queue_item_id"]
        == consumer_action_requirement["related_queue_item_id"]
    )
    assert (
        consumer_work_queue_assignment["consumer_work_queue_assignment"]
        == expected_consumer_work_queue_assignment
    )


@pytest.mark.parametrize(
    (
        "decision",
        "expected_attention_level",
        "expected_notification_requirement",
        "expected_response_priority",
        "expected_response_channel",
        "expected_response_route",
        "expected_followup_requirement",
        "expected_consumer_decision_posture",
        "expected_consumer_action_requirement",
        "expected_consumer_work_queue_assignment",
        "expected_consumer_processing_plan",
    ),
    [
        pytest.param(
            "GO",
            "low",
            "none",
            "normal",
            "standard_channel",
            "standard_route",
            "none",
            "observe",
            "no_action",
            "observation_queue",
            "observe_only",
            id="go",
        ),
        pytest.param(
            "PAUSE",
            "medium",
            "notify",
            "elevated",
            "priority_channel",
            "priority_route",
            "follow_up",
            "engage",
            "action_required",
            "action_queue",
            "process_action",
            id="pause",
        ),
        pytest.param(
            "REVIEW",
            "high",
            "escalate",
            "urgent",
            "escalation_channel",
            "escalation_route",
            "escalation_follow_up",
            "escalate",
            "escalation_required",
            "escalation_queue",
            "process_escalation",
            id="review",
        ),
    ],
)
def test_consumer_processing_plan_from_work_queue_assignment_matches_work_queue_assignment(
    decision: RecommendationValue,
    expected_attention_level: str,
    expected_notification_requirement: str,
    expected_response_priority: str,
    expected_response_channel: str,
    expected_response_route: str,
    expected_followup_requirement: str,
    expected_consumer_decision_posture: str,
    expected_consumer_action_requirement: str,
    expected_consumer_work_queue_assignment: str,
    expected_consumer_processing_plan: str,
) -> None:
    expected_classification = {
        "GO": "ready",
        "PAUSE": "hold",
        "REVIEW": "needs_review",
    }[decision]
    expected_handling_directive = {
        "ready": "deliver",
        "hold": "defer",
        "needs_review": "route_for_review",
    }[expected_classification]
    expected_action_label = {
        "deliver": "dispatch",
        "defer": "wait",
        "route_for_review": "review_queue",
    }[expected_handling_directive]
    expected_dispatch_intent = {
        "dispatch": "send",
        "wait": "park",
        "review_queue": "review",
    }[expected_action_label]
    expected_dispatch_mode = {
        "send": "active",
        "park": "queued",
        "review": "review_pending",
    }[expected_dispatch_intent]
    expected_release_gate = {
        "active": "open",
        "queued": "deferred",
        "review_pending": "blocked_for_review",
    }[expected_dispatch_mode]
    expected_progress_state = {
        "open": "in_progress",
        "deferred": "pending",
        "blocked_for_review": "review_hold",
    }[expected_release_gate]
    expected_progress_signal = {
        "in_progress": "advance",
        "pending": "await",
        "review_hold": "review_wait",
    }[expected_progress_state]
    expected_progress_outcome = {
        "advance": "moving",
        "await": "standing_by",
        "review_wait": "awaiting_review",
    }[expected_progress_signal]
    expected_intervention_requirement = {
        "moving": "none",
        "standing_by": "monitor",
        "awaiting_review": "review_required",
    }[expected_progress_outcome]
    attention_level_by_intervention_requirement = {
        "none": "low",
        "monitor": "medium",
        "review_required": "high",
    }
    notification_requirement_by_attention_level = {
        "low": "none",
        "medium": "notify",
        "high": "escalate",
    }
    response_priority_by_notification_requirement = {
        "none": "normal",
        "notify": "elevated",
        "escalate": "urgent",
    }
    response_channel_by_priority = {
        "normal": "standard_channel",
        "elevated": "priority_channel",
        "urgent": "escalation_channel",
    }
    followup_requirement_by_route = {
        "standard_route": "none",
        "priority_route": "follow_up",
        "escalation_route": "escalation_follow_up",
    }
    posture_by_followup_requirement = {
        "none": "observe",
        "follow_up": "engage",
        "escalation_follow_up": "escalate",
    }
    action_requirement_by_posture = {
        "observe": "no_action",
        "engage": "action_required",
        "escalate": "escalation_required",
    }
    queue_assignment_by_action_requirement = {
        "no_action": "observation_queue",
        "action_required": "action_queue",
        "escalation_required": "escalation_queue",
    }
    processing_plan_by_queue_assignment = {
        "observation_queue": "observe_only",
        "action_queue": "process_action",
        "escalation_queue": "process_escalation",
    }
    assert (
        attention_level_by_intervention_requirement[expected_intervention_requirement]
        == expected_attention_level
    )
    assert (
        notification_requirement_by_attention_level[expected_attention_level]
        == expected_notification_requirement
    )
    assert (
        response_priority_by_notification_requirement[expected_notification_requirement]
        == expected_response_priority
    )
    assert response_channel_by_priority[expected_response_priority] == expected_response_channel
    assert followup_requirement_by_route[expected_response_route] == expected_followup_requirement
    assert (
        posture_by_followup_requirement[expected_followup_requirement]
        == expected_consumer_decision_posture
    )
    assert (
        action_requirement_by_posture[expected_consumer_decision_posture]
        == expected_consumer_action_requirement
    )
    assert (
        queue_assignment_by_action_requirement[expected_consumer_action_requirement]
        == expected_consumer_work_queue_assignment
    )
    assert (
        processing_plan_by_queue_assignment[expected_consumer_work_queue_assignment]
        == expected_consumer_processing_plan
    )
    consumer_work_queue_assignment = {
        "projected_activation_decision": {"recommendation": decision},
        "approval_record": {
            "human_approval_status": {
                "status": {
                    "GO": "approved",
                    "PAUSE": "pending",
                    "REVIEW": "withheld",
                }[decision]
            }
        },
        "receiver_readiness_classification": expected_classification,
        "receiver_handling_directive": expected_handling_directive,
        "receiver_action_label": expected_action_label,
        "receiver_dispatch_intent": expected_dispatch_intent,
        "receiver_dispatch_mode": expected_dispatch_mode,
        "receiver_release_gate": expected_release_gate,
        "receiver_progress_state": expected_progress_state,
        "receiver_progress_signal": expected_progress_signal,
        "receiver_progress_outcome": expected_progress_outcome,
        "receiver_intervention_requirement": expected_intervention_requirement,
        "receiver_attention_level": expected_attention_level,
        "receiver_notification_requirement": expected_notification_requirement,
        "receiver_response_priority": expected_response_priority,
        "receiver_response_channel": expected_response_channel,
        "receiver_response_route": expected_response_route,
        "receiver_followup_requirement": expected_followup_requirement,
        "consumer_decision_posture": expected_consumer_decision_posture,
        "consumer_action_requirement": expected_consumer_action_requirement,
        "consumer_work_queue_assignment": expected_consumer_work_queue_assignment,
        "related_project_id": "project_consumer_processing_plan_1",
        "related_activation_decision_id": "activation_decision_consumer_processing_plan_1",
        "related_packet_id": "packet_consumer_processing_plan_1",
        "related_queue_item_id": "queue_consumer_processing_plan_1",
    }

    consumer_processing_plan = build_consumer_processing_plan_from_work_queue_assignment(
        consumer_work_queue_assignment=consumer_work_queue_assignment
    )

    assert (
        consumer_processing_plan["projected_activation_decision"]
        == consumer_work_queue_assignment["projected_activation_decision"]
    )
    assert consumer_processing_plan["approval_record"] == consumer_work_queue_assignment[
        "approval_record"
    ]
    assert (
        consumer_processing_plan["receiver_readiness_classification"]
        == consumer_work_queue_assignment["receiver_readiness_classification"]
    )
    assert (
        consumer_processing_plan["receiver_handling_directive"]
        == consumer_work_queue_assignment["receiver_handling_directive"]
    )
    assert (
        consumer_processing_plan["receiver_action_label"]
        == consumer_work_queue_assignment["receiver_action_label"]
    )
    assert (
        consumer_processing_plan["receiver_dispatch_intent"]
        == consumer_work_queue_assignment["receiver_dispatch_intent"]
    )
    assert (
        consumer_processing_plan["receiver_dispatch_mode"]
        == consumer_work_queue_assignment["receiver_dispatch_mode"]
    )
    assert (
        consumer_processing_plan["receiver_release_gate"]
        == consumer_work_queue_assignment["receiver_release_gate"]
    )
    assert (
        consumer_processing_plan["receiver_progress_state"]
        == consumer_work_queue_assignment["receiver_progress_state"]
    )
    assert (
        consumer_processing_plan["receiver_progress_signal"]
        == consumer_work_queue_assignment["receiver_progress_signal"]
    )
    assert (
        consumer_processing_plan["receiver_progress_outcome"]
        == consumer_work_queue_assignment["receiver_progress_outcome"]
    )
    assert (
        consumer_processing_plan["receiver_intervention_requirement"]
        == consumer_work_queue_assignment["receiver_intervention_requirement"]
    )
    assert (
        consumer_processing_plan["receiver_attention_level"]
        == consumer_work_queue_assignment["receiver_attention_level"]
    )
    assert (
        consumer_processing_plan["receiver_notification_requirement"]
        == consumer_work_queue_assignment["receiver_notification_requirement"]
    )
    assert (
        consumer_processing_plan["receiver_response_priority"]
        == consumer_work_queue_assignment["receiver_response_priority"]
    )
    assert (
        consumer_processing_plan["receiver_response_channel"]
        == consumer_work_queue_assignment["receiver_response_channel"]
    )
    assert (
        consumer_processing_plan["receiver_response_route"]
        == consumer_work_queue_assignment["receiver_response_route"]
    )
    assert (
        consumer_processing_plan["receiver_followup_requirement"]
        == consumer_work_queue_assignment["receiver_followup_requirement"]
    )
    assert (
        consumer_processing_plan["consumer_decision_posture"]
        == consumer_work_queue_assignment["consumer_decision_posture"]
    )
    assert (
        consumer_processing_plan["consumer_action_requirement"]
        == consumer_work_queue_assignment["consumer_action_requirement"]
    )
    assert (
        consumer_processing_plan["consumer_work_queue_assignment"]
        == consumer_work_queue_assignment["consumer_work_queue_assignment"]
    )
    assert (
        consumer_processing_plan["related_project_id"]
        == consumer_work_queue_assignment["related_project_id"]
    )
    assert (
        consumer_processing_plan["related_activation_decision_id"]
        == consumer_work_queue_assignment["related_activation_decision_id"]
    )
    assert (
        consumer_processing_plan["related_packet_id"]
        == consumer_work_queue_assignment["related_packet_id"]
    )
    assert (
        consumer_processing_plan["related_queue_item_id"]
        == consumer_work_queue_assignment["related_queue_item_id"]
    )
    assert (
        consumer_processing_plan["consumer_processing_plan"]
        == expected_consumer_processing_plan
    )


@pytest.mark.parametrize(
    (
        "decision",
        "expected_attention_level",
        "expected_notification_requirement",
        "expected_response_priority",
        "expected_response_channel",
        "expected_response_route",
        "expected_followup_requirement",
        "expected_consumer_decision_posture",
        "expected_consumer_action_requirement",
        "expected_consumer_work_queue_assignment",
        "expected_consumer_processing_plan",
        "expected_consumer_operator_requirement",
    ),
    [
        pytest.param(
            "GO",
            "low",
            "none",
            "normal",
            "standard_channel",
            "standard_route",
            "none",
            "observe",
            "no_action",
            "observation_queue",
            "observe_only",
            "none",
            id="go",
        ),
        pytest.param(
            "PAUSE",
            "medium",
            "notify",
            "elevated",
            "priority_channel",
            "priority_route",
            "follow_up",
            "engage",
            "action_required",
            "action_queue",
            "process_action",
            "operator_required",
            id="pause",
        ),
        pytest.param(
            "REVIEW",
            "high",
            "escalate",
            "urgent",
            "escalation_channel",
            "escalation_route",
            "escalation_follow_up",
            "escalate",
            "escalation_required",
            "escalation_queue",
            "process_escalation",
            "senior_operator_required",
            id="review",
        ),
    ],
)
def test_consumer_operator_requirement_from_processing_plan_matches_processing_plan(
    decision: RecommendationValue,
    expected_attention_level: str,
    expected_notification_requirement: str,
    expected_response_priority: str,
    expected_response_channel: str,
    expected_response_route: str,
    expected_followup_requirement: str,
    expected_consumer_decision_posture: str,
    expected_consumer_action_requirement: str,
    expected_consumer_work_queue_assignment: str,
    expected_consumer_processing_plan: str,
    expected_consumer_operator_requirement: str,
) -> None:
    expected_classification = {
        "GO": "ready",
        "PAUSE": "hold",
        "REVIEW": "needs_review",
    }[decision]
    expected_handling_directive = {
        "ready": "deliver",
        "hold": "defer",
        "needs_review": "route_for_review",
    }[expected_classification]
    expected_action_label = {
        "deliver": "dispatch",
        "defer": "wait",
        "route_for_review": "review_queue",
    }[expected_handling_directive]
    expected_dispatch_intent = {
        "dispatch": "send",
        "wait": "park",
        "review_queue": "review",
    }[expected_action_label]
    expected_dispatch_mode = {
        "send": "active",
        "park": "queued",
        "review": "review_pending",
    }[expected_dispatch_intent]
    expected_release_gate = {
        "active": "open",
        "queued": "deferred",
        "review_pending": "blocked_for_review",
    }[expected_dispatch_mode]
    expected_progress_state = {
        "open": "in_progress",
        "deferred": "pending",
        "blocked_for_review": "review_hold",
    }[expected_release_gate]
    expected_progress_signal = {
        "in_progress": "advance",
        "pending": "await",
        "review_hold": "review_wait",
    }[expected_progress_state]
    expected_progress_outcome = {
        "advance": "moving",
        "await": "standing_by",
        "review_wait": "awaiting_review",
    }[expected_progress_signal]
    expected_intervention_requirement = {
        "moving": "none",
        "standing_by": "monitor",
        "awaiting_review": "review_required",
    }[expected_progress_outcome]
    attention_level_by_intervention_requirement = {
        "none": "low",
        "monitor": "medium",
        "review_required": "high",
    }
    notification_requirement_by_attention_level = {
        "low": "none",
        "medium": "notify",
        "high": "escalate",
    }
    response_priority_by_notification_requirement = {
        "none": "normal",
        "notify": "elevated",
        "escalate": "urgent",
    }
    response_channel_by_priority = {
        "normal": "standard_channel",
        "elevated": "priority_channel",
        "urgent": "escalation_channel",
    }
    followup_requirement_by_route = {
        "standard_route": "none",
        "priority_route": "follow_up",
        "escalation_route": "escalation_follow_up",
    }
    posture_by_followup_requirement = {
        "none": "observe",
        "follow_up": "engage",
        "escalation_follow_up": "escalate",
    }
    action_requirement_by_posture = {
        "observe": "no_action",
        "engage": "action_required",
        "escalate": "escalation_required",
    }
    queue_assignment_by_action_requirement = {
        "no_action": "observation_queue",
        "action_required": "action_queue",
        "escalation_required": "escalation_queue",
    }
    processing_plan_by_queue_assignment = {
        "observation_queue": "observe_only",
        "action_queue": "process_action",
        "escalation_queue": "process_escalation",
    }
    operator_requirement_by_processing_plan = {
        "observe_only": "none",
        "process_action": "operator_required",
        "process_escalation": "senior_operator_required",
    }
    assert (
        attention_level_by_intervention_requirement[expected_intervention_requirement]
        == expected_attention_level
    )
    assert (
        notification_requirement_by_attention_level[expected_attention_level]
        == expected_notification_requirement
    )
    assert (
        response_priority_by_notification_requirement[expected_notification_requirement]
        == expected_response_priority
    )
    assert response_channel_by_priority[expected_response_priority] == expected_response_channel
    assert followup_requirement_by_route[expected_response_route] == expected_followup_requirement
    assert (
        posture_by_followup_requirement[expected_followup_requirement]
        == expected_consumer_decision_posture
    )
    assert (
        action_requirement_by_posture[expected_consumer_decision_posture]
        == expected_consumer_action_requirement
    )
    assert (
        queue_assignment_by_action_requirement[expected_consumer_action_requirement]
        == expected_consumer_work_queue_assignment
    )
    assert (
        processing_plan_by_queue_assignment[expected_consumer_work_queue_assignment]
        == expected_consumer_processing_plan
    )
    assert (
        operator_requirement_by_processing_plan[expected_consumer_processing_plan]
        == expected_consumer_operator_requirement
    )
    consumer_processing_plan = {
        "projected_activation_decision": {"recommendation": decision},
        "approval_record": {
            "human_approval_status": {
                "status": {
                    "GO": "approved",
                    "PAUSE": "pending",
                    "REVIEW": "withheld",
                }[decision]
            }
        },
        "receiver_readiness_classification": expected_classification,
        "receiver_handling_directive": expected_handling_directive,
        "receiver_action_label": expected_action_label,
        "receiver_dispatch_intent": expected_dispatch_intent,
        "receiver_dispatch_mode": expected_dispatch_mode,
        "receiver_release_gate": expected_release_gate,
        "receiver_progress_state": expected_progress_state,
        "receiver_progress_signal": expected_progress_signal,
        "receiver_progress_outcome": expected_progress_outcome,
        "receiver_intervention_requirement": expected_intervention_requirement,
        "receiver_attention_level": expected_attention_level,
        "receiver_notification_requirement": expected_notification_requirement,
        "receiver_response_priority": expected_response_priority,
        "receiver_response_channel": expected_response_channel,
        "receiver_response_route": expected_response_route,
        "receiver_followup_requirement": expected_followup_requirement,
        "consumer_decision_posture": expected_consumer_decision_posture,
        "consumer_action_requirement": expected_consumer_action_requirement,
        "consumer_work_queue_assignment": expected_consumer_work_queue_assignment,
        "consumer_processing_plan": expected_consumer_processing_plan,
        "related_project_id": "project_consumer_operator_requirement_1",
        "related_activation_decision_id": "activation_decision_consumer_operator_requirement_1",
        "related_packet_id": "packet_consumer_operator_requirement_1",
        "related_queue_item_id": "queue_consumer_operator_requirement_1",
    }

    consumer_operator_requirement = build_consumer_operator_requirement_from_processing_plan(
        consumer_processing_plan=consumer_processing_plan
    )

    assert (
        consumer_operator_requirement["projected_activation_decision"]
        == consumer_processing_plan["projected_activation_decision"]
    )
    assert consumer_operator_requirement["approval_record"] == consumer_processing_plan[
        "approval_record"
    ]
    assert (
        consumer_operator_requirement["receiver_readiness_classification"]
        == consumer_processing_plan["receiver_readiness_classification"]
    )
    assert (
        consumer_operator_requirement["receiver_handling_directive"]
        == consumer_processing_plan["receiver_handling_directive"]
    )
    assert (
        consumer_operator_requirement["receiver_action_label"]
        == consumer_processing_plan["receiver_action_label"]
    )
    assert (
        consumer_operator_requirement["receiver_dispatch_intent"]
        == consumer_processing_plan["receiver_dispatch_intent"]
    )
    assert (
        consumer_operator_requirement["receiver_dispatch_mode"]
        == consumer_processing_plan["receiver_dispatch_mode"]
    )
    assert (
        consumer_operator_requirement["receiver_release_gate"]
        == consumer_processing_plan["receiver_release_gate"]
    )
    assert (
        consumer_operator_requirement["receiver_progress_state"]
        == consumer_processing_plan["receiver_progress_state"]
    )
    assert (
        consumer_operator_requirement["receiver_progress_signal"]
        == consumer_processing_plan["receiver_progress_signal"]
    )
    assert (
        consumer_operator_requirement["receiver_progress_outcome"]
        == consumer_processing_plan["receiver_progress_outcome"]
    )
    assert (
        consumer_operator_requirement["receiver_intervention_requirement"]
        == consumer_processing_plan["receiver_intervention_requirement"]
    )
    assert (
        consumer_operator_requirement["receiver_attention_level"]
        == consumer_processing_plan["receiver_attention_level"]
    )
    assert (
        consumer_operator_requirement["receiver_notification_requirement"]
        == consumer_processing_plan["receiver_notification_requirement"]
    )
    assert (
        consumer_operator_requirement["receiver_response_priority"]
        == consumer_processing_plan["receiver_response_priority"]
    )
    assert (
        consumer_operator_requirement["receiver_response_channel"]
        == consumer_processing_plan["receiver_response_channel"]
    )
    assert (
        consumer_operator_requirement["receiver_response_route"]
        == consumer_processing_plan["receiver_response_route"]
    )
    assert (
        consumer_operator_requirement["receiver_followup_requirement"]
        == consumer_processing_plan["receiver_followup_requirement"]
    )
    assert (
        consumer_operator_requirement["consumer_decision_posture"]
        == consumer_processing_plan["consumer_decision_posture"]
    )
    assert (
        consumer_operator_requirement["consumer_action_requirement"]
        == consumer_processing_plan["consumer_action_requirement"]
    )
    assert (
        consumer_operator_requirement["consumer_work_queue_assignment"]
        == consumer_processing_plan["consumer_work_queue_assignment"]
    )
    assert (
        consumer_operator_requirement["consumer_processing_plan"]
        == consumer_processing_plan["consumer_processing_plan"]
    )
    assert (
        consumer_operator_requirement["related_project_id"]
        == consumer_processing_plan["related_project_id"]
    )
    assert (
        consumer_operator_requirement["related_activation_decision_id"]
        == consumer_processing_plan["related_activation_decision_id"]
    )
    assert (
        consumer_operator_requirement["related_packet_id"]
        == consumer_processing_plan["related_packet_id"]
    )
    assert (
        consumer_operator_requirement["related_queue_item_id"]
        == consumer_processing_plan["related_queue_item_id"]
    )
    assert (
        consumer_operator_requirement["consumer_operator_requirement"]
        == expected_consumer_operator_requirement
    )


@pytest.mark.parametrize(
    (
        "decision",
        "expected_attention_level",
        "expected_notification_requirement",
        "expected_response_priority",
        "expected_response_channel",
        "expected_response_route",
        "expected_followup_requirement",
        "expected_consumer_decision_posture",
        "expected_consumer_action_requirement",
        "expected_consumer_work_queue_assignment",
        "expected_consumer_processing_plan",
        "expected_consumer_operator_requirement",
        "expected_consumer_assignment_lane",
    ),
    [
        pytest.param(
            "GO",
            "low",
            "none",
            "normal",
            "standard_channel",
            "standard_route",
            "none",
            "observe",
            "no_action",
            "observation_queue",
            "observe_only",
            "none",
            "self_service_lane",
            id="go",
        ),
        pytest.param(
            "PAUSE",
            "medium",
            "notify",
            "elevated",
            "priority_channel",
            "priority_route",
            "follow_up",
            "engage",
            "action_required",
            "action_queue",
            "process_action",
            "operator_required",
            "operator_lane",
            id="pause",
        ),
        pytest.param(
            "REVIEW",
            "high",
            "escalate",
            "urgent",
            "escalation_channel",
            "escalation_route",
            "escalation_follow_up",
            "escalate",
            "escalation_required",
            "escalation_queue",
            "process_escalation",
            "senior_operator_required",
            "senior_operator_lane",
            id="review",
        ),
    ],
)
def test_consumer_assignment_lane_from_operator_requirement_matches_operator_requirement(
    decision: RecommendationValue,
    expected_attention_level: str,
    expected_notification_requirement: str,
    expected_response_priority: str,
    expected_response_channel: str,
    expected_response_route: str,
    expected_followup_requirement: str,
    expected_consumer_decision_posture: str,
    expected_consumer_action_requirement: str,
    expected_consumer_work_queue_assignment: str,
    expected_consumer_processing_plan: str,
    expected_consumer_operator_requirement: str,
    expected_consumer_assignment_lane: str,
) -> None:
    expected_classification = {
        "GO": "ready",
        "PAUSE": "hold",
        "REVIEW": "needs_review",
    }[decision]
    expected_handling_directive = {
        "ready": "deliver",
        "hold": "defer",
        "needs_review": "route_for_review",
    }[expected_classification]
    expected_action_label = {
        "deliver": "dispatch",
        "defer": "wait",
        "route_for_review": "review_queue",
    }[expected_handling_directive]
    expected_dispatch_intent = {
        "dispatch": "send",
        "wait": "park",
        "review_queue": "review",
    }[expected_action_label]
    expected_dispatch_mode = {
        "send": "active",
        "park": "queued",
        "review": "review_pending",
    }[expected_dispatch_intent]
    expected_release_gate = {
        "active": "open",
        "queued": "deferred",
        "review_pending": "blocked_for_review",
    }[expected_dispatch_mode]
    expected_progress_state = {
        "open": "in_progress",
        "deferred": "pending",
        "blocked_for_review": "review_hold",
    }[expected_release_gate]
    expected_progress_signal = {
        "in_progress": "advance",
        "pending": "await",
        "review_hold": "review_wait",
    }[expected_progress_state]
    expected_progress_outcome = {
        "advance": "moving",
        "await": "standing_by",
        "review_wait": "awaiting_review",
    }[expected_progress_signal]
    expected_intervention_requirement = {
        "moving": "none",
        "standing_by": "monitor",
        "awaiting_review": "review_required",
    }[expected_progress_outcome]
    attention_level_by_intervention_requirement = {
        "none": "low",
        "monitor": "medium",
        "review_required": "high",
    }
    notification_requirement_by_attention_level = {
        "low": "none",
        "medium": "notify",
        "high": "escalate",
    }
    response_priority_by_notification_requirement = {
        "none": "normal",
        "notify": "elevated",
        "escalate": "urgent",
    }
    response_channel_by_priority = {
        "normal": "standard_channel",
        "elevated": "priority_channel",
        "urgent": "escalation_channel",
    }
    followup_requirement_by_route = {
        "standard_route": "none",
        "priority_route": "follow_up",
        "escalation_route": "escalation_follow_up",
    }
    posture_by_followup_requirement = {
        "none": "observe",
        "follow_up": "engage",
        "escalation_follow_up": "escalate",
    }
    action_requirement_by_posture = {
        "observe": "no_action",
        "engage": "action_required",
        "escalate": "escalation_required",
    }
    queue_assignment_by_action_requirement = {
        "no_action": "observation_queue",
        "action_required": "action_queue",
        "escalation_required": "escalation_queue",
    }
    processing_plan_by_queue_assignment = {
        "observation_queue": "observe_only",
        "action_queue": "process_action",
        "escalation_queue": "process_escalation",
    }
    operator_requirement_by_processing_plan = {
        "observe_only": "none",
        "process_action": "operator_required",
        "process_escalation": "senior_operator_required",
    }
    assignment_lane_by_operator_requirement = {
        "none": "self_service_lane",
        "operator_required": "operator_lane",
        "senior_operator_required": "senior_operator_lane",
    }
    assert (
        attention_level_by_intervention_requirement[expected_intervention_requirement]
        == expected_attention_level
    )
    assert (
        notification_requirement_by_attention_level[expected_attention_level]
        == expected_notification_requirement
    )
    assert (
        response_priority_by_notification_requirement[expected_notification_requirement]
        == expected_response_priority
    )
    assert response_channel_by_priority[expected_response_priority] == expected_response_channel
    assert followup_requirement_by_route[expected_response_route] == expected_followup_requirement
    assert (
        posture_by_followup_requirement[expected_followup_requirement]
        == expected_consumer_decision_posture
    )
    assert (
        action_requirement_by_posture[expected_consumer_decision_posture]
        == expected_consumer_action_requirement
    )
    assert (
        queue_assignment_by_action_requirement[expected_consumer_action_requirement]
        == expected_consumer_work_queue_assignment
    )
    assert (
        processing_plan_by_queue_assignment[expected_consumer_work_queue_assignment]
        == expected_consumer_processing_plan
    )
    assert (
        operator_requirement_by_processing_plan[expected_consumer_processing_plan]
        == expected_consumer_operator_requirement
    )
    assert (
        assignment_lane_by_operator_requirement[expected_consumer_operator_requirement]
        == expected_consumer_assignment_lane
    )
    consumer_operator_requirement = {
        "projected_activation_decision": {"recommendation": decision},
        "approval_record": {
            "human_approval_status": {
                "status": {
                    "GO": "approved",
                    "PAUSE": "pending",
                    "REVIEW": "withheld",
                }[decision]
            }
        },
        "receiver_readiness_classification": expected_classification,
        "receiver_handling_directive": expected_handling_directive,
        "receiver_action_label": expected_action_label,
        "receiver_dispatch_intent": expected_dispatch_intent,
        "receiver_dispatch_mode": expected_dispatch_mode,
        "receiver_release_gate": expected_release_gate,
        "receiver_progress_state": expected_progress_state,
        "receiver_progress_signal": expected_progress_signal,
        "receiver_progress_outcome": expected_progress_outcome,
        "receiver_intervention_requirement": expected_intervention_requirement,
        "receiver_attention_level": expected_attention_level,
        "receiver_notification_requirement": expected_notification_requirement,
        "receiver_response_priority": expected_response_priority,
        "receiver_response_channel": expected_response_channel,
        "receiver_response_route": expected_response_route,
        "receiver_followup_requirement": expected_followup_requirement,
        "consumer_decision_posture": expected_consumer_decision_posture,
        "consumer_action_requirement": expected_consumer_action_requirement,
        "consumer_work_queue_assignment": expected_consumer_work_queue_assignment,
        "consumer_processing_plan": expected_consumer_processing_plan,
        "consumer_operator_requirement": expected_consumer_operator_requirement,
        "related_project_id": "project_consumer_assignment_lane_1",
        "related_activation_decision_id": "activation_decision_consumer_assignment_lane_1",
        "related_packet_id": "packet_consumer_assignment_lane_1",
        "related_queue_item_id": "queue_consumer_assignment_lane_1",
    }

    consumer_assignment_lane = build_consumer_assignment_lane_from_operator_requirement(
        consumer_operator_requirement=consumer_operator_requirement
    )

    assert (
        consumer_assignment_lane["projected_activation_decision"]
        == consumer_operator_requirement["projected_activation_decision"]
    )
    assert consumer_assignment_lane["approval_record"] == consumer_operator_requirement[
        "approval_record"
    ]
    assert (
        consumer_assignment_lane["receiver_readiness_classification"]
        == consumer_operator_requirement["receiver_readiness_classification"]
    )
    assert (
        consumer_assignment_lane["receiver_handling_directive"]
        == consumer_operator_requirement["receiver_handling_directive"]
    )
    assert (
        consumer_assignment_lane["receiver_action_label"]
        == consumer_operator_requirement["receiver_action_label"]
    )
    assert (
        consumer_assignment_lane["receiver_dispatch_intent"]
        == consumer_operator_requirement["receiver_dispatch_intent"]
    )
    assert (
        consumer_assignment_lane["receiver_dispatch_mode"]
        == consumer_operator_requirement["receiver_dispatch_mode"]
    )
    assert (
        consumer_assignment_lane["receiver_release_gate"]
        == consumer_operator_requirement["receiver_release_gate"]
    )
    assert (
        consumer_assignment_lane["receiver_progress_state"]
        == consumer_operator_requirement["receiver_progress_state"]
    )
    assert (
        consumer_assignment_lane["receiver_progress_signal"]
        == consumer_operator_requirement["receiver_progress_signal"]
    )
    assert (
        consumer_assignment_lane["receiver_progress_outcome"]
        == consumer_operator_requirement["receiver_progress_outcome"]
    )
    assert (
        consumer_assignment_lane["receiver_intervention_requirement"]
        == consumer_operator_requirement["receiver_intervention_requirement"]
    )
    assert (
        consumer_assignment_lane["receiver_attention_level"]
        == consumer_operator_requirement["receiver_attention_level"]
    )
    assert (
        consumer_assignment_lane["receiver_notification_requirement"]
        == consumer_operator_requirement["receiver_notification_requirement"]
    )
    assert (
        consumer_assignment_lane["receiver_response_priority"]
        == consumer_operator_requirement["receiver_response_priority"]
    )
    assert (
        consumer_assignment_lane["receiver_response_channel"]
        == consumer_operator_requirement["receiver_response_channel"]
    )
    assert (
        consumer_assignment_lane["receiver_response_route"]
        == consumer_operator_requirement["receiver_response_route"]
    )
    assert (
        consumer_assignment_lane["receiver_followup_requirement"]
        == consumer_operator_requirement["receiver_followup_requirement"]
    )
    assert (
        consumer_assignment_lane["consumer_decision_posture"]
        == consumer_operator_requirement["consumer_decision_posture"]
    )
    assert (
        consumer_assignment_lane["consumer_action_requirement"]
        == consumer_operator_requirement["consumer_action_requirement"]
    )
    assert (
        consumer_assignment_lane["consumer_work_queue_assignment"]
        == consumer_operator_requirement["consumer_work_queue_assignment"]
    )
    assert (
        consumer_assignment_lane["consumer_processing_plan"]
        == consumer_operator_requirement["consumer_processing_plan"]
    )
    assert (
        consumer_assignment_lane["consumer_operator_requirement"]
        == consumer_operator_requirement["consumer_operator_requirement"]
    )
    assert (
        consumer_assignment_lane["related_project_id"]
        == consumer_operator_requirement["related_project_id"]
    )
    assert (
        consumer_assignment_lane["related_activation_decision_id"]
        == consumer_operator_requirement["related_activation_decision_id"]
    )
    assert (
        consumer_assignment_lane["related_packet_id"]
        == consumer_operator_requirement["related_packet_id"]
    )
    assert (
        consumer_assignment_lane["related_queue_item_id"]
        == consumer_operator_requirement["related_queue_item_id"]
    )
    assert (
        consumer_assignment_lane["consumer_assignment_lane"]
        == expected_consumer_assignment_lane
    )


@pytest.mark.parametrize(
    (
        "decision",
        "expected_attention_level",
        "expected_notification_requirement",
        "expected_response_priority",
        "expected_response_channel",
        "expected_response_route",
        "expected_followup_requirement",
        "expected_consumer_decision_posture",
        "expected_consumer_action_requirement",
        "expected_consumer_work_queue_assignment",
        "expected_consumer_processing_plan",
        "expected_consumer_operator_requirement",
        "expected_consumer_assignment_lane",
        "expected_consumer_service_tier",
    ),
    [
        pytest.param(
            "GO",
            "low",
            "none",
            "normal",
            "standard_channel",
            "standard_route",
            "none",
            "observe",
            "no_action",
            "observation_queue",
            "observe_only",
            "none",
            "self_service_lane",
            "self_service",
            id="go",
        ),
        pytest.param(
            "PAUSE",
            "medium",
            "notify",
            "elevated",
            "priority_channel",
            "priority_route",
            "follow_up",
            "engage",
            "action_required",
            "action_queue",
            "process_action",
            "operator_required",
            "operator_lane",
            "operator_managed",
            id="pause",
        ),
        pytest.param(
            "REVIEW",
            "high",
            "escalate",
            "urgent",
            "escalation_channel",
            "escalation_route",
            "escalation_follow_up",
            "escalate",
            "escalation_required",
            "escalation_queue",
            "process_escalation",
            "senior_operator_required",
            "senior_operator_lane",
            "senior_managed",
            id="review",
        ),
    ],
)
def test_consumer_service_tier_from_assignment_lane_matches_assignment_lane(
    decision: RecommendationValue,
    expected_attention_level: str,
    expected_notification_requirement: str,
    expected_response_priority: str,
    expected_response_channel: str,
    expected_response_route: str,
    expected_followup_requirement: str,
    expected_consumer_decision_posture: str,
    expected_consumer_action_requirement: str,
    expected_consumer_work_queue_assignment: str,
    expected_consumer_processing_plan: str,
    expected_consumer_operator_requirement: str,
    expected_consumer_assignment_lane: str,
    expected_consumer_service_tier: str,
) -> None:
    expected_classification = {
        "GO": "ready",
        "PAUSE": "hold",
        "REVIEW": "needs_review",
    }[decision]
    expected_handling_directive = {
        "ready": "deliver",
        "hold": "defer",
        "needs_review": "route_for_review",
    }[expected_classification]
    expected_action_label = {
        "deliver": "dispatch",
        "defer": "wait",
        "route_for_review": "review_queue",
    }[expected_handling_directive]
    expected_dispatch_intent = {
        "dispatch": "send",
        "wait": "park",
        "review_queue": "review",
    }[expected_action_label]
    expected_dispatch_mode = {
        "send": "active",
        "park": "queued",
        "review": "review_pending",
    }[expected_dispatch_intent]
    expected_release_gate = {
        "active": "open",
        "queued": "deferred",
        "review_pending": "blocked_for_review",
    }[expected_dispatch_mode]
    expected_progress_state = {
        "open": "in_progress",
        "deferred": "pending",
        "blocked_for_review": "review_hold",
    }[expected_release_gate]
    expected_progress_signal = {
        "in_progress": "advance",
        "pending": "await",
        "review_hold": "review_wait",
    }[expected_progress_state]
    expected_progress_outcome = {
        "advance": "moving",
        "await": "standing_by",
        "review_wait": "awaiting_review",
    }[expected_progress_signal]
    expected_intervention_requirement = {
        "moving": "none",
        "standing_by": "monitor",
        "awaiting_review": "review_required",
    }[expected_progress_outcome]
    attention_level_by_intervention_requirement = {
        "none": "low",
        "monitor": "medium",
        "review_required": "high",
    }
    notification_requirement_by_attention_level = {
        "low": "none",
        "medium": "notify",
        "high": "escalate",
    }
    response_priority_by_notification_requirement = {
        "none": "normal",
        "notify": "elevated",
        "escalate": "urgent",
    }
    response_channel_by_priority = {
        "normal": "standard_channel",
        "elevated": "priority_channel",
        "urgent": "escalation_channel",
    }
    followup_requirement_by_route = {
        "standard_route": "none",
        "priority_route": "follow_up",
        "escalation_route": "escalation_follow_up",
    }
    posture_by_followup_requirement = {
        "none": "observe",
        "follow_up": "engage",
        "escalation_follow_up": "escalate",
    }
    action_requirement_by_posture = {
        "observe": "no_action",
        "engage": "action_required",
        "escalate": "escalation_required",
    }
    queue_assignment_by_action_requirement = {
        "no_action": "observation_queue",
        "action_required": "action_queue",
        "escalation_required": "escalation_queue",
    }
    processing_plan_by_queue_assignment = {
        "observation_queue": "observe_only",
        "action_queue": "process_action",
        "escalation_queue": "process_escalation",
    }
    operator_requirement_by_processing_plan = {
        "observe_only": "none",
        "process_action": "operator_required",
        "process_escalation": "senior_operator_required",
    }
    assignment_lane_by_operator_requirement = {
        "none": "self_service_lane",
        "operator_required": "operator_lane",
        "senior_operator_required": "senior_operator_lane",
    }
    service_tier_by_assignment_lane = {
        "self_service_lane": "self_service",
        "operator_lane": "operator_managed",
        "senior_operator_lane": "senior_managed",
    }
    assert (
        attention_level_by_intervention_requirement[expected_intervention_requirement]
        == expected_attention_level
    )
    assert (
        notification_requirement_by_attention_level[expected_attention_level]
        == expected_notification_requirement
    )
    assert (
        response_priority_by_notification_requirement[expected_notification_requirement]
        == expected_response_priority
    )
    assert response_channel_by_priority[expected_response_priority] == expected_response_channel
    assert followup_requirement_by_route[expected_response_route] == expected_followup_requirement
    assert (
        posture_by_followup_requirement[expected_followup_requirement]
        == expected_consumer_decision_posture
    )
    assert (
        action_requirement_by_posture[expected_consumer_decision_posture]
        == expected_consumer_action_requirement
    )
    assert (
        queue_assignment_by_action_requirement[expected_consumer_action_requirement]
        == expected_consumer_work_queue_assignment
    )
    assert (
        processing_plan_by_queue_assignment[expected_consumer_work_queue_assignment]
        == expected_consumer_processing_plan
    )
    assert (
        operator_requirement_by_processing_plan[expected_consumer_processing_plan]
        == expected_consumer_operator_requirement
    )
    assert (
        assignment_lane_by_operator_requirement[expected_consumer_operator_requirement]
        == expected_consumer_assignment_lane
    )
    assert (
        service_tier_by_assignment_lane[expected_consumer_assignment_lane]
        == expected_consumer_service_tier
    )
    consumer_assignment_lane = {
        "projected_activation_decision": {"recommendation": decision},
        "approval_record": {
            "human_approval_status": {
                "status": {
                    "GO": "approved",
                    "PAUSE": "pending",
                    "REVIEW": "withheld",
                }[decision]
            }
        },
        "receiver_readiness_classification": expected_classification,
        "receiver_handling_directive": expected_handling_directive,
        "receiver_action_label": expected_action_label,
        "receiver_dispatch_intent": expected_dispatch_intent,
        "receiver_dispatch_mode": expected_dispatch_mode,
        "receiver_release_gate": expected_release_gate,
        "receiver_progress_state": expected_progress_state,
        "receiver_progress_signal": expected_progress_signal,
        "receiver_progress_outcome": expected_progress_outcome,
        "receiver_intervention_requirement": expected_intervention_requirement,
        "receiver_attention_level": expected_attention_level,
        "receiver_notification_requirement": expected_notification_requirement,
        "receiver_response_priority": expected_response_priority,
        "receiver_response_channel": expected_response_channel,
        "receiver_response_route": expected_response_route,
        "receiver_followup_requirement": expected_followup_requirement,
        "consumer_decision_posture": expected_consumer_decision_posture,
        "consumer_action_requirement": expected_consumer_action_requirement,
        "consumer_work_queue_assignment": expected_consumer_work_queue_assignment,
        "consumer_processing_plan": expected_consumer_processing_plan,
        "consumer_operator_requirement": expected_consumer_operator_requirement,
        "consumer_assignment_lane": expected_consumer_assignment_lane,
        "related_project_id": "project_consumer_service_tier_1",
        "related_activation_decision_id": "activation_decision_consumer_service_tier_1",
        "related_packet_id": "packet_consumer_service_tier_1",
        "related_queue_item_id": "queue_consumer_service_tier_1",
    }

    consumer_service_tier = build_consumer_service_tier_from_assignment_lane(
        consumer_assignment_lane=consumer_assignment_lane
    )

    assert (
        consumer_service_tier["projected_activation_decision"]
        == consumer_assignment_lane["projected_activation_decision"]
    )
    assert consumer_service_tier["approval_record"] == consumer_assignment_lane[
        "approval_record"
    ]
    assert (
        consumer_service_tier["receiver_readiness_classification"]
        == consumer_assignment_lane["receiver_readiness_classification"]
    )
    assert (
        consumer_service_tier["receiver_handling_directive"]
        == consumer_assignment_lane["receiver_handling_directive"]
    )
    assert (
        consumer_service_tier["receiver_action_label"]
        == consumer_assignment_lane["receiver_action_label"]
    )
    assert (
        consumer_service_tier["receiver_dispatch_intent"]
        == consumer_assignment_lane["receiver_dispatch_intent"]
    )
    assert (
        consumer_service_tier["receiver_dispatch_mode"]
        == consumer_assignment_lane["receiver_dispatch_mode"]
    )
    assert (
        consumer_service_tier["receiver_release_gate"]
        == consumer_assignment_lane["receiver_release_gate"]
    )
    assert (
        consumer_service_tier["receiver_progress_state"]
        == consumer_assignment_lane["receiver_progress_state"]
    )
    assert (
        consumer_service_tier["receiver_progress_signal"]
        == consumer_assignment_lane["receiver_progress_signal"]
    )
    assert (
        consumer_service_tier["receiver_progress_outcome"]
        == consumer_assignment_lane["receiver_progress_outcome"]
    )
    assert (
        consumer_service_tier["receiver_intervention_requirement"]
        == consumer_assignment_lane["receiver_intervention_requirement"]
    )
    assert (
        consumer_service_tier["receiver_attention_level"]
        == consumer_assignment_lane["receiver_attention_level"]
    )
    assert (
        consumer_service_tier["receiver_notification_requirement"]
        == consumer_assignment_lane["receiver_notification_requirement"]
    )
    assert (
        consumer_service_tier["receiver_response_priority"]
        == consumer_assignment_lane["receiver_response_priority"]
    )
    assert (
        consumer_service_tier["receiver_response_channel"]
        == consumer_assignment_lane["receiver_response_channel"]
    )
    assert (
        consumer_service_tier["receiver_response_route"]
        == consumer_assignment_lane["receiver_response_route"]
    )
    assert (
        consumer_service_tier["receiver_followup_requirement"]
        == consumer_assignment_lane["receiver_followup_requirement"]
    )
    assert (
        consumer_service_tier["consumer_decision_posture"]
        == consumer_assignment_lane["consumer_decision_posture"]
    )
    assert (
        consumer_service_tier["consumer_action_requirement"]
        == consumer_assignment_lane["consumer_action_requirement"]
    )
    assert (
        consumer_service_tier["consumer_work_queue_assignment"]
        == consumer_assignment_lane["consumer_work_queue_assignment"]
    )
    assert (
        consumer_service_tier["consumer_processing_plan"]
        == consumer_assignment_lane["consumer_processing_plan"]
    )
    assert (
        consumer_service_tier["consumer_operator_requirement"]
        == consumer_assignment_lane["consumer_operator_requirement"]
    )
    assert (
        consumer_service_tier["consumer_assignment_lane"]
        == consumer_assignment_lane["consumer_assignment_lane"]
    )
    assert (
        consumer_service_tier["related_project_id"]
        == consumer_assignment_lane["related_project_id"]
    )
    assert (
        consumer_service_tier["related_activation_decision_id"]
        == consumer_assignment_lane["related_activation_decision_id"]
    )
    assert (
        consumer_service_tier["related_packet_id"]
        == consumer_assignment_lane["related_packet_id"]
    )
    assert (
        consumer_service_tier["related_queue_item_id"]
        == consumer_assignment_lane["related_queue_item_id"]
    )
    assert (
        consumer_service_tier["consumer_service_tier"] == expected_consumer_service_tier
    )


@pytest.mark.parametrize(
    (
        "decision",
        "expected_attention_level",
        "expected_notification_requirement",
        "expected_response_priority",
        "expected_response_channel",
        "expected_response_route",
        "expected_followup_requirement",
        "expected_consumer_decision_posture",
        "expected_consumer_action_requirement",
        "expected_consumer_work_queue_assignment",
        "expected_consumer_processing_plan",
        "expected_consumer_operator_requirement",
        "expected_consumer_assignment_lane",
        "expected_consumer_service_tier",
        "expected_consumer_sla_class",
    ),
    [
        pytest.param(
            "GO",
            "low",
            "none",
            "normal",
            "standard_channel",
            "standard_route",
            "none",
            "observe",
            "no_action",
            "observation_queue",
            "observe_only",
            "none",
            "self_service_lane",
            "self_service",
            "deferred",
            id="go",
        ),
        pytest.param(
            "PAUSE",
            "medium",
            "notify",
            "elevated",
            "priority_channel",
            "priority_route",
            "follow_up",
            "engage",
            "action_required",
            "action_queue",
            "process_action",
            "operator_required",
            "operator_lane",
            "operator_managed",
            "standard",
            id="pause",
        ),
        pytest.param(
            "REVIEW",
            "high",
            "escalate",
            "urgent",
            "escalation_channel",
            "escalation_route",
            "escalation_follow_up",
            "escalate",
            "escalation_required",
            "escalation_queue",
            "process_escalation",
            "senior_operator_required",
            "senior_operator_lane",
            "senior_managed",
            "priority",
            id="review",
        ),
    ],
)
def test_consumer_sla_class_from_service_tier_matches_service_tier(
    decision: RecommendationValue,
    expected_attention_level: str,
    expected_notification_requirement: str,
    expected_response_priority: str,
    expected_response_channel: str,
    expected_response_route: str,
    expected_followup_requirement: str,
    expected_consumer_decision_posture: str,
    expected_consumer_action_requirement: str,
    expected_consumer_work_queue_assignment: str,
    expected_consumer_processing_plan: str,
    expected_consumer_operator_requirement: str,
    expected_consumer_assignment_lane: str,
    expected_consumer_service_tier: str,
    expected_consumer_sla_class: str,
) -> None:
    expected_classification = {
        "GO": "ready",
        "PAUSE": "hold",
        "REVIEW": "needs_review",
    }[decision]
    expected_handling_directive = {
        "ready": "deliver",
        "hold": "defer",
        "needs_review": "route_for_review",
    }[expected_classification]
    expected_action_label = {
        "deliver": "dispatch",
        "defer": "wait",
        "route_for_review": "review_queue",
    }[expected_handling_directive]
    expected_dispatch_intent = {
        "dispatch": "send",
        "wait": "park",
        "review_queue": "review",
    }[expected_action_label]
    expected_dispatch_mode = {
        "send": "active",
        "park": "queued",
        "review": "review_pending",
    }[expected_dispatch_intent]
    expected_release_gate = {
        "active": "open",
        "queued": "deferred",
        "review_pending": "blocked_for_review",
    }[expected_dispatch_mode]
    expected_progress_state = {
        "open": "in_progress",
        "deferred": "pending",
        "blocked_for_review": "review_hold",
    }[expected_release_gate]
    expected_progress_signal = {
        "in_progress": "advance",
        "pending": "await",
        "review_hold": "review_wait",
    }[expected_progress_state]
    expected_progress_outcome = {
        "advance": "moving",
        "await": "standing_by",
        "review_wait": "awaiting_review",
    }[expected_progress_signal]
    expected_intervention_requirement = {
        "moving": "none",
        "standing_by": "monitor",
        "awaiting_review": "review_required",
    }[expected_progress_outcome]
    attention_level_by_intervention_requirement = {
        "none": "low",
        "monitor": "medium",
        "review_required": "high",
    }
    notification_requirement_by_attention_level = {
        "low": "none",
        "medium": "notify",
        "high": "escalate",
    }
    response_priority_by_notification_requirement = {
        "none": "normal",
        "notify": "elevated",
        "escalate": "urgent",
    }
    response_channel_by_priority = {
        "normal": "standard_channel",
        "elevated": "priority_channel",
        "urgent": "escalation_channel",
    }
    followup_requirement_by_route = {
        "standard_route": "none",
        "priority_route": "follow_up",
        "escalation_route": "escalation_follow_up",
    }
    posture_by_followup_requirement = {
        "none": "observe",
        "follow_up": "engage",
        "escalation_follow_up": "escalate",
    }
    action_requirement_by_posture = {
        "observe": "no_action",
        "engage": "action_required",
        "escalate": "escalation_required",
    }
    queue_assignment_by_action_requirement = {
        "no_action": "observation_queue",
        "action_required": "action_queue",
        "escalation_required": "escalation_queue",
    }
    processing_plan_by_queue_assignment = {
        "observation_queue": "observe_only",
        "action_queue": "process_action",
        "escalation_queue": "process_escalation",
    }
    operator_requirement_by_processing_plan = {
        "observe_only": "none",
        "process_action": "operator_required",
        "process_escalation": "senior_operator_required",
    }
    assignment_lane_by_operator_requirement = {
        "none": "self_service_lane",
        "operator_required": "operator_lane",
        "senior_operator_required": "senior_operator_lane",
    }
    service_tier_by_assignment_lane = {
        "self_service_lane": "self_service",
        "operator_lane": "operator_managed",
        "senior_operator_lane": "senior_managed",
    }
    sla_class_by_service_tier = {
        "self_service": "deferred",
        "operator_managed": "standard",
        "senior_managed": "priority",
    }
    assert (
        attention_level_by_intervention_requirement[expected_intervention_requirement]
        == expected_attention_level
    )
    assert (
        notification_requirement_by_attention_level[expected_attention_level]
        == expected_notification_requirement
    )
    assert (
        response_priority_by_notification_requirement[expected_notification_requirement]
        == expected_response_priority
    )
    assert response_channel_by_priority[expected_response_priority] == expected_response_channel
    assert followup_requirement_by_route[expected_response_route] == expected_followup_requirement
    assert (
        posture_by_followup_requirement[expected_followup_requirement]
        == expected_consumer_decision_posture
    )
    assert (
        action_requirement_by_posture[expected_consumer_decision_posture]
        == expected_consumer_action_requirement
    )
    assert (
        queue_assignment_by_action_requirement[expected_consumer_action_requirement]
        == expected_consumer_work_queue_assignment
    )
    assert (
        processing_plan_by_queue_assignment[expected_consumer_work_queue_assignment]
        == expected_consumer_processing_plan
    )
    assert (
        operator_requirement_by_processing_plan[expected_consumer_processing_plan]
        == expected_consumer_operator_requirement
    )
    assert (
        assignment_lane_by_operator_requirement[expected_consumer_operator_requirement]
        == expected_consumer_assignment_lane
    )
    assert (
        service_tier_by_assignment_lane[expected_consumer_assignment_lane]
        == expected_consumer_service_tier
    )
    assert sla_class_by_service_tier[expected_consumer_service_tier] == expected_consumer_sla_class
    consumer_service_tier = {
        "projected_activation_decision": {"recommendation": decision},
        "approval_record": {
            "human_approval_status": {
                "status": {
                    "GO": "approved",
                    "PAUSE": "pending",
                    "REVIEW": "withheld",
                }[decision]
            }
        },
        "receiver_readiness_classification": expected_classification,
        "receiver_handling_directive": expected_handling_directive,
        "receiver_action_label": expected_action_label,
        "receiver_dispatch_intent": expected_dispatch_intent,
        "receiver_dispatch_mode": expected_dispatch_mode,
        "receiver_release_gate": expected_release_gate,
        "receiver_progress_state": expected_progress_state,
        "receiver_progress_signal": expected_progress_signal,
        "receiver_progress_outcome": expected_progress_outcome,
        "receiver_intervention_requirement": expected_intervention_requirement,
        "receiver_attention_level": expected_attention_level,
        "receiver_notification_requirement": expected_notification_requirement,
        "receiver_response_priority": expected_response_priority,
        "receiver_response_channel": expected_response_channel,
        "receiver_response_route": expected_response_route,
        "receiver_followup_requirement": expected_followup_requirement,
        "consumer_decision_posture": expected_consumer_decision_posture,
        "consumer_action_requirement": expected_consumer_action_requirement,
        "consumer_work_queue_assignment": expected_consumer_work_queue_assignment,
        "consumer_processing_plan": expected_consumer_processing_plan,
        "consumer_operator_requirement": expected_consumer_operator_requirement,
        "consumer_assignment_lane": expected_consumer_assignment_lane,
        "consumer_service_tier": expected_consumer_service_tier,
        "related_project_id": "project_consumer_sla_class_1",
        "related_activation_decision_id": "activation_decision_consumer_sla_class_1",
        "related_packet_id": "packet_consumer_sla_class_1",
        "related_queue_item_id": "queue_consumer_sla_class_1",
    }

    consumer_sla_class = build_consumer_sla_class_from_service_tier(
        consumer_service_tier=consumer_service_tier
    )

    assert (
        consumer_sla_class["projected_activation_decision"]
        == consumer_service_tier["projected_activation_decision"]
    )
    assert consumer_sla_class["approval_record"] == consumer_service_tier["approval_record"]
    assert (
        consumer_sla_class["receiver_readiness_classification"]
        == consumer_service_tier["receiver_readiness_classification"]
    )
    assert (
        consumer_sla_class["receiver_handling_directive"]
        == consumer_service_tier["receiver_handling_directive"]
    )
    assert (
        consumer_sla_class["receiver_action_label"]
        == consumer_service_tier["receiver_action_label"]
    )
    assert (
        consumer_sla_class["receiver_dispatch_intent"]
        == consumer_service_tier["receiver_dispatch_intent"]
    )
    assert (
        consumer_sla_class["receiver_dispatch_mode"]
        == consumer_service_tier["receiver_dispatch_mode"]
    )
    assert (
        consumer_sla_class["receiver_release_gate"]
        == consumer_service_tier["receiver_release_gate"]
    )
    assert (
        consumer_sla_class["receiver_progress_state"]
        == consumer_service_tier["receiver_progress_state"]
    )
    assert (
        consumer_sla_class["receiver_progress_signal"]
        == consumer_service_tier["receiver_progress_signal"]
    )
    assert (
        consumer_sla_class["receiver_progress_outcome"]
        == consumer_service_tier["receiver_progress_outcome"]
    )
    assert (
        consumer_sla_class["receiver_intervention_requirement"]
        == consumer_service_tier["receiver_intervention_requirement"]
    )
    assert (
        consumer_sla_class["receiver_attention_level"]
        == consumer_service_tier["receiver_attention_level"]
    )
    assert (
        consumer_sla_class["receiver_notification_requirement"]
        == consumer_service_tier["receiver_notification_requirement"]
    )
    assert (
        consumer_sla_class["receiver_response_priority"]
        == consumer_service_tier["receiver_response_priority"]
    )
    assert (
        consumer_sla_class["receiver_response_channel"]
        == consumer_service_tier["receiver_response_channel"]
    )
    assert (
        consumer_sla_class["receiver_response_route"]
        == consumer_service_tier["receiver_response_route"]
    )
    assert (
        consumer_sla_class["receiver_followup_requirement"]
        == consumer_service_tier["receiver_followup_requirement"]
    )
    assert (
        consumer_sla_class["consumer_decision_posture"]
        == consumer_service_tier["consumer_decision_posture"]
    )
    assert (
        consumer_sla_class["consumer_action_requirement"]
        == consumer_service_tier["consumer_action_requirement"]
    )
    assert (
        consumer_sla_class["consumer_work_queue_assignment"]
        == consumer_service_tier["consumer_work_queue_assignment"]
    )
    assert (
        consumer_sla_class["consumer_processing_plan"]
        == consumer_service_tier["consumer_processing_plan"]
    )
    assert (
        consumer_sla_class["consumer_operator_requirement"]
        == consumer_service_tier["consumer_operator_requirement"]
    )
    assert (
        consumer_sla_class["consumer_assignment_lane"]
        == consumer_service_tier["consumer_assignment_lane"]
    )
    assert (
        consumer_sla_class["consumer_service_tier"]
        == consumer_service_tier["consumer_service_tier"]
    )
    assert (
        consumer_sla_class["related_project_id"] == consumer_service_tier["related_project_id"]
    )
    assert (
        consumer_sla_class["related_activation_decision_id"]
        == consumer_service_tier["related_activation_decision_id"]
    )
    assert (
        consumer_sla_class["related_packet_id"] == consumer_service_tier["related_packet_id"]
    )
    assert (
        consumer_sla_class["related_queue_item_id"]
        == consumer_service_tier["related_queue_item_id"]
    )
    assert consumer_sla_class["consumer_sla_class"] == expected_consumer_sla_class


@pytest.mark.parametrize(
    (
        "decision",
        "expected_attention_level",
        "expected_notification_requirement",
        "expected_response_priority",
        "expected_response_channel",
        "expected_response_route",
        "expected_followup_requirement",
        "expected_consumer_decision_posture",
        "expected_consumer_action_requirement",
        "expected_consumer_work_queue_assignment",
        "expected_consumer_processing_plan",
        "expected_consumer_operator_requirement",
        "expected_consumer_assignment_lane",
        "expected_consumer_service_tier",
        "expected_consumer_sla_class",
        "expected_consumer_response_window",
    ),
    [
        pytest.param(
            "GO",
            "low",
            "none",
            "normal",
            "standard_channel",
            "standard_route",
            "none",
            "observe",
            "no_action",
            "observation_queue",
            "observe_only",
            "none",
            "self_service_lane",
            "self_service",
            "deferred",
            "backlog_window",
            id="go",
        ),
        pytest.param(
            "PAUSE",
            "medium",
            "notify",
            "elevated",
            "priority_channel",
            "priority_route",
            "follow_up",
            "engage",
            "action_required",
            "action_queue",
            "process_action",
            "operator_required",
            "operator_lane",
            "operator_managed",
            "standard",
            "standard_window",
            id="pause",
        ),
        pytest.param(
            "REVIEW",
            "high",
            "escalate",
            "urgent",
            "escalation_channel",
            "escalation_route",
            "escalation_follow_up",
            "escalate",
            "escalation_required",
            "escalation_queue",
            "process_escalation",
            "senior_operator_required",
            "senior_operator_lane",
            "senior_managed",
            "priority",
            "priority_window",
            id="review",
        ),
    ],
)
def test_consumer_response_window_from_sla_class_matches_sla_class(
    decision: RecommendationValue,
    expected_attention_level: str,
    expected_notification_requirement: str,
    expected_response_priority: str,
    expected_response_channel: str,
    expected_response_route: str,
    expected_followup_requirement: str,
    expected_consumer_decision_posture: str,
    expected_consumer_action_requirement: str,
    expected_consumer_work_queue_assignment: str,
    expected_consumer_processing_plan: str,
    expected_consumer_operator_requirement: str,
    expected_consumer_assignment_lane: str,
    expected_consumer_service_tier: str,
    expected_consumer_sla_class: str,
    expected_consumer_response_window: str,
) -> None:
    expected_classification = {
        "GO": "ready",
        "PAUSE": "hold",
        "REVIEW": "needs_review",
    }[decision]
    expected_handling_directive = {
        "ready": "deliver",
        "hold": "defer",
        "needs_review": "route_for_review",
    }[expected_classification]
    expected_action_label = {
        "deliver": "dispatch",
        "defer": "wait",
        "route_for_review": "review_queue",
    }[expected_handling_directive]
    expected_dispatch_intent = {
        "dispatch": "send",
        "wait": "park",
        "review_queue": "review",
    }[expected_action_label]
    expected_dispatch_mode = {
        "send": "active",
        "park": "queued",
        "review": "review_pending",
    }[expected_dispatch_intent]
    expected_release_gate = {
        "active": "open",
        "queued": "deferred",
        "review_pending": "blocked_for_review",
    }[expected_dispatch_mode]
    expected_progress_state = {
        "open": "in_progress",
        "deferred": "pending",
        "blocked_for_review": "review_hold",
    }[expected_release_gate]
    expected_progress_signal = {
        "in_progress": "advance",
        "pending": "await",
        "review_hold": "review_wait",
    }[expected_progress_state]
    expected_progress_outcome = {
        "advance": "moving",
        "await": "standing_by",
        "review_wait": "awaiting_review",
    }[expected_progress_signal]
    expected_intervention_requirement = {
        "moving": "none",
        "standing_by": "monitor",
        "awaiting_review": "review_required",
    }[expected_progress_outcome]
    attention_level_by_intervention_requirement = {
        "none": "low",
        "monitor": "medium",
        "review_required": "high",
    }
    notification_requirement_by_attention_level = {
        "low": "none",
        "medium": "notify",
        "high": "escalate",
    }
    response_priority_by_notification_requirement = {
        "none": "normal",
        "notify": "elevated",
        "escalate": "urgent",
    }
    response_channel_by_priority = {
        "normal": "standard_channel",
        "elevated": "priority_channel",
        "urgent": "escalation_channel",
    }
    followup_requirement_by_route = {
        "standard_route": "none",
        "priority_route": "follow_up",
        "escalation_route": "escalation_follow_up",
    }
    posture_by_followup_requirement = {
        "none": "observe",
        "follow_up": "engage",
        "escalation_follow_up": "escalate",
    }
    action_requirement_by_posture = {
        "observe": "no_action",
        "engage": "action_required",
        "escalate": "escalation_required",
    }
    queue_assignment_by_action_requirement = {
        "no_action": "observation_queue",
        "action_required": "action_queue",
        "escalation_required": "escalation_queue",
    }
    processing_plan_by_queue_assignment = {
        "observation_queue": "observe_only",
        "action_queue": "process_action",
        "escalation_queue": "process_escalation",
    }
    operator_requirement_by_processing_plan = {
        "observe_only": "none",
        "process_action": "operator_required",
        "process_escalation": "senior_operator_required",
    }
    assignment_lane_by_operator_requirement = {
        "none": "self_service_lane",
        "operator_required": "operator_lane",
        "senior_operator_required": "senior_operator_lane",
    }
    service_tier_by_assignment_lane = {
        "self_service_lane": "self_service",
        "operator_lane": "operator_managed",
        "senior_operator_lane": "senior_managed",
    }
    sla_class_by_service_tier = {
        "self_service": "deferred",
        "operator_managed": "standard",
        "senior_managed": "priority",
    }
    response_window_by_sla_class = {
        "deferred": "backlog_window",
        "standard": "standard_window",
        "priority": "priority_window",
    }
    assert (
        attention_level_by_intervention_requirement[expected_intervention_requirement]
        == expected_attention_level
    )
    assert (
        notification_requirement_by_attention_level[expected_attention_level]
        == expected_notification_requirement
    )
    assert (
        response_priority_by_notification_requirement[expected_notification_requirement]
        == expected_response_priority
    )
    assert response_channel_by_priority[expected_response_priority] == expected_response_channel
    assert followup_requirement_by_route[expected_response_route] == expected_followup_requirement
    assert (
        posture_by_followup_requirement[expected_followup_requirement]
        == expected_consumer_decision_posture
    )
    assert (
        action_requirement_by_posture[expected_consumer_decision_posture]
        == expected_consumer_action_requirement
    )
    assert (
        queue_assignment_by_action_requirement[expected_consumer_action_requirement]
        == expected_consumer_work_queue_assignment
    )
    assert (
        processing_plan_by_queue_assignment[expected_consumer_work_queue_assignment]
        == expected_consumer_processing_plan
    )
    assert (
        operator_requirement_by_processing_plan[expected_consumer_processing_plan]
        == expected_consumer_operator_requirement
    )
    assert (
        assignment_lane_by_operator_requirement[expected_consumer_operator_requirement]
        == expected_consumer_assignment_lane
    )
    assert (
        service_tier_by_assignment_lane[expected_consumer_assignment_lane]
        == expected_consumer_service_tier
    )
    assert sla_class_by_service_tier[expected_consumer_service_tier] == expected_consumer_sla_class
    assert (
        response_window_by_sla_class[expected_consumer_sla_class]
        == expected_consumer_response_window
    )
    consumer_sla_class = {
        "projected_activation_decision": {"recommendation": decision},
        "approval_record": {
            "human_approval_status": {
                "status": {
                    "GO": "approved",
                    "PAUSE": "pending",
                    "REVIEW": "withheld",
                }[decision]
            }
        },
        "receiver_readiness_classification": expected_classification,
        "receiver_handling_directive": expected_handling_directive,
        "receiver_action_label": expected_action_label,
        "receiver_dispatch_intent": expected_dispatch_intent,
        "receiver_dispatch_mode": expected_dispatch_mode,
        "receiver_release_gate": expected_release_gate,
        "receiver_progress_state": expected_progress_state,
        "receiver_progress_signal": expected_progress_signal,
        "receiver_progress_outcome": expected_progress_outcome,
        "receiver_intervention_requirement": expected_intervention_requirement,
        "receiver_attention_level": expected_attention_level,
        "receiver_notification_requirement": expected_notification_requirement,
        "receiver_response_priority": expected_response_priority,
        "receiver_response_channel": expected_response_channel,
        "receiver_response_route": expected_response_route,
        "receiver_followup_requirement": expected_followup_requirement,
        "consumer_decision_posture": expected_consumer_decision_posture,
        "consumer_action_requirement": expected_consumer_action_requirement,
        "consumer_work_queue_assignment": expected_consumer_work_queue_assignment,
        "consumer_processing_plan": expected_consumer_processing_plan,
        "consumer_operator_requirement": expected_consumer_operator_requirement,
        "consumer_assignment_lane": expected_consumer_assignment_lane,
        "consumer_service_tier": expected_consumer_service_tier,
        "consumer_sla_class": expected_consumer_sla_class,
        "related_project_id": "project_consumer_response_window_1",
        "related_activation_decision_id": "activation_decision_consumer_response_window_1",
        "related_packet_id": "packet_consumer_response_window_1",
        "related_queue_item_id": "queue_consumer_response_window_1",
    }

    consumer_response_window = build_consumer_response_window_from_sla_class(
        consumer_sla_class=consumer_sla_class
    )

    assert (
        consumer_response_window["projected_activation_decision"]
        == consumer_sla_class["projected_activation_decision"]
    )
    assert consumer_response_window["approval_record"] == consumer_sla_class[
        "approval_record"
    ]
    assert (
        consumer_response_window["receiver_readiness_classification"]
        == consumer_sla_class["receiver_readiness_classification"]
    )
    assert (
        consumer_response_window["receiver_handling_directive"]
        == consumer_sla_class["receiver_handling_directive"]
    )
    assert (
        consumer_response_window["receiver_action_label"]
        == consumer_sla_class["receiver_action_label"]
    )
    assert (
        consumer_response_window["receiver_dispatch_intent"]
        == consumer_sla_class["receiver_dispatch_intent"]
    )
    assert (
        consumer_response_window["receiver_dispatch_mode"]
        == consumer_sla_class["receiver_dispatch_mode"]
    )
    assert (
        consumer_response_window["receiver_release_gate"]
        == consumer_sla_class["receiver_release_gate"]
    )
    assert (
        consumer_response_window["receiver_progress_state"]
        == consumer_sla_class["receiver_progress_state"]
    )
    assert (
        consumer_response_window["receiver_progress_signal"]
        == consumer_sla_class["receiver_progress_signal"]
    )
    assert (
        consumer_response_window["receiver_progress_outcome"]
        == consumer_sla_class["receiver_progress_outcome"]
    )
    assert (
        consumer_response_window["receiver_intervention_requirement"]
        == consumer_sla_class["receiver_intervention_requirement"]
    )
    assert (
        consumer_response_window["receiver_attention_level"]
        == consumer_sla_class["receiver_attention_level"]
    )
    assert (
        consumer_response_window["receiver_notification_requirement"]
        == consumer_sla_class["receiver_notification_requirement"]
    )
    assert (
        consumer_response_window["receiver_response_priority"]
        == consumer_sla_class["receiver_response_priority"]
    )
    assert (
        consumer_response_window["receiver_response_channel"]
        == consumer_sla_class["receiver_response_channel"]
    )
    assert (
        consumer_response_window["receiver_response_route"]
        == consumer_sla_class["receiver_response_route"]
    )
    assert (
        consumer_response_window["receiver_followup_requirement"]
        == consumer_sla_class["receiver_followup_requirement"]
    )
    assert (
        consumer_response_window["consumer_decision_posture"]
        == consumer_sla_class["consumer_decision_posture"]
    )
    assert (
        consumer_response_window["consumer_action_requirement"]
        == consumer_sla_class["consumer_action_requirement"]
    )
    assert (
        consumer_response_window["consumer_work_queue_assignment"]
        == consumer_sla_class["consumer_work_queue_assignment"]
    )
    assert (
        consumer_response_window["consumer_processing_plan"]
        == consumer_sla_class["consumer_processing_plan"]
    )
    assert (
        consumer_response_window["consumer_operator_requirement"]
        == consumer_sla_class["consumer_operator_requirement"]
    )
    assert (
        consumer_response_window["consumer_assignment_lane"]
        == consumer_sla_class["consumer_assignment_lane"]
    )
    assert (
        consumer_response_window["consumer_service_tier"]
        == consumer_sla_class["consumer_service_tier"]
    )
    assert (
        consumer_response_window["consumer_sla_class"] == consumer_sla_class["consumer_sla_class"]
    )
    assert (
        consumer_response_window["related_project_id"] == consumer_sla_class["related_project_id"]
    )
    assert (
        consumer_response_window["related_activation_decision_id"]
        == consumer_sla_class["related_activation_decision_id"]
    )
    assert (
        consumer_response_window["related_packet_id"] == consumer_sla_class["related_packet_id"]
    )
    assert (
        consumer_response_window["related_queue_item_id"]
        == consumer_sla_class["related_queue_item_id"]
    )
    assert (
        consumer_response_window["consumer_response_window"]
        == expected_consumer_response_window
    )


@pytest.mark.parametrize(
    (
        "decision",
        "expected_attention_level",
        "expected_notification_requirement",
        "expected_response_priority",
        "expected_response_channel",
        "expected_response_route",
        "expected_followup_requirement",
        "expected_consumer_decision_posture",
        "expected_consumer_action_requirement",
        "expected_consumer_work_queue_assignment",
        "expected_consumer_processing_plan",
        "expected_consumer_operator_requirement",
        "expected_consumer_assignment_lane",
        "expected_consumer_service_tier",
        "expected_consumer_sla_class",
        "expected_consumer_response_window",
        "expected_consumer_timing_posture",
    ),
    [
        pytest.param(
            "GO",
            "low",
            "none",
            "normal",
            "standard_channel",
            "standard_route",
            "none",
            "observe",
            "no_action",
            "observation_queue",
            "observe_only",
            "none",
            "self_service_lane",
            "self_service",
            "deferred",
            "backlog_window",
            "later",
            id="go",
        ),
        pytest.param(
            "PAUSE",
            "medium",
            "notify",
            "elevated",
            "priority_channel",
            "priority_route",
            "follow_up",
            "engage",
            "action_required",
            "action_queue",
            "process_action",
            "operator_required",
            "operator_lane",
            "operator_managed",
            "standard",
            "standard_window",
            "scheduled",
            id="pause",
        ),
        pytest.param(
            "REVIEW",
            "high",
            "escalate",
            "urgent",
            "escalation_channel",
            "escalation_route",
            "escalation_follow_up",
            "escalate",
            "escalation_required",
            "escalation_queue",
            "process_escalation",
            "senior_operator_required",
            "senior_operator_lane",
            "senior_managed",
            "priority",
            "priority_window",
            "immediate",
            id="review",
        ),
    ],
)
def test_consumer_timing_posture_from_response_window_matches_response_window(
    decision: RecommendationValue,
    expected_attention_level: str,
    expected_notification_requirement: str,
    expected_response_priority: str,
    expected_response_channel: str,
    expected_response_route: str,
    expected_followup_requirement: str,
    expected_consumer_decision_posture: str,
    expected_consumer_action_requirement: str,
    expected_consumer_work_queue_assignment: str,
    expected_consumer_processing_plan: str,
    expected_consumer_operator_requirement: str,
    expected_consumer_assignment_lane: str,
    expected_consumer_service_tier: str,
    expected_consumer_sla_class: str,
    expected_consumer_response_window: str,
    expected_consumer_timing_posture: str,
) -> None:
    expected_classification = {
        "GO": "ready",
        "PAUSE": "hold",
        "REVIEW": "needs_review",
    }[decision]
    expected_handling_directive = {
        "ready": "deliver",
        "hold": "defer",
        "needs_review": "route_for_review",
    }[expected_classification]
    expected_action_label = {
        "deliver": "dispatch",
        "defer": "wait",
        "route_for_review": "review_queue",
    }[expected_handling_directive]
    expected_dispatch_intent = {
        "dispatch": "send",
        "wait": "park",
        "review_queue": "review",
    }[expected_action_label]
    expected_dispatch_mode = {
        "send": "active",
        "park": "queued",
        "review": "review_pending",
    }[expected_dispatch_intent]
    expected_release_gate = {
        "active": "open",
        "queued": "deferred",
        "review_pending": "blocked_for_review",
    }[expected_dispatch_mode]
    expected_progress_state = {
        "open": "in_progress",
        "deferred": "pending",
        "blocked_for_review": "review_hold",
    }[expected_release_gate]
    expected_progress_signal = {
        "in_progress": "advance",
        "pending": "await",
        "review_hold": "review_wait",
    }[expected_progress_state]
    expected_progress_outcome = {
        "advance": "moving",
        "await": "standing_by",
        "review_wait": "awaiting_review",
    }[expected_progress_signal]
    expected_intervention_requirement = {
        "moving": "none",
        "standing_by": "monitor",
        "awaiting_review": "review_required",
    }[expected_progress_outcome]
    attention_level_by_intervention_requirement = {
        "none": "low",
        "monitor": "medium",
        "review_required": "high",
    }
    notification_requirement_by_attention_level = {
        "low": "none",
        "medium": "notify",
        "high": "escalate",
    }
    response_priority_by_notification_requirement = {
        "none": "normal",
        "notify": "elevated",
        "escalate": "urgent",
    }
    response_channel_by_priority = {
        "normal": "standard_channel",
        "elevated": "priority_channel",
        "urgent": "escalation_channel",
    }
    followup_requirement_by_route = {
        "standard_route": "none",
        "priority_route": "follow_up",
        "escalation_route": "escalation_follow_up",
    }
    posture_by_followup_requirement = {
        "none": "observe",
        "follow_up": "engage",
        "escalation_follow_up": "escalate",
    }
    action_requirement_by_posture = {
        "observe": "no_action",
        "engage": "action_required",
        "escalate": "escalation_required",
    }
    queue_assignment_by_action_requirement = {
        "no_action": "observation_queue",
        "action_required": "action_queue",
        "escalation_required": "escalation_queue",
    }
    processing_plan_by_queue_assignment = {
        "observation_queue": "observe_only",
        "action_queue": "process_action",
        "escalation_queue": "process_escalation",
    }
    operator_requirement_by_processing_plan = {
        "observe_only": "none",
        "process_action": "operator_required",
        "process_escalation": "senior_operator_required",
    }
    assignment_lane_by_operator_requirement = {
        "none": "self_service_lane",
        "operator_required": "operator_lane",
        "senior_operator_required": "senior_operator_lane",
    }
    service_tier_by_assignment_lane = {
        "self_service_lane": "self_service",
        "operator_lane": "operator_managed",
        "senior_operator_lane": "senior_managed",
    }
    sla_class_by_service_tier = {
        "self_service": "deferred",
        "operator_managed": "standard",
        "senior_managed": "priority",
    }
    response_window_by_sla_class = {
        "deferred": "backlog_window",
        "standard": "standard_window",
        "priority": "priority_window",
    }
    timing_posture_by_response_window = {
        "backlog_window": "later",
        "standard_window": "scheduled",
        "priority_window": "immediate",
    }
    assert (
        attention_level_by_intervention_requirement[expected_intervention_requirement]
        == expected_attention_level
    )
    assert (
        notification_requirement_by_attention_level[expected_attention_level]
        == expected_notification_requirement
    )
    assert (
        response_priority_by_notification_requirement[expected_notification_requirement]
        == expected_response_priority
    )
    assert response_channel_by_priority[expected_response_priority] == expected_response_channel
    assert followup_requirement_by_route[expected_response_route] == expected_followup_requirement
    assert (
        posture_by_followup_requirement[expected_followup_requirement]
        == expected_consumer_decision_posture
    )
    assert (
        action_requirement_by_posture[expected_consumer_decision_posture]
        == expected_consumer_action_requirement
    )
    assert (
        queue_assignment_by_action_requirement[expected_consumer_action_requirement]
        == expected_consumer_work_queue_assignment
    )
    assert (
        processing_plan_by_queue_assignment[expected_consumer_work_queue_assignment]
        == expected_consumer_processing_plan
    )
    assert (
        operator_requirement_by_processing_plan[expected_consumer_processing_plan]
        == expected_consumer_operator_requirement
    )
    assert (
        assignment_lane_by_operator_requirement[expected_consumer_operator_requirement]
        == expected_consumer_assignment_lane
    )
    assert (
        service_tier_by_assignment_lane[expected_consumer_assignment_lane]
        == expected_consumer_service_tier
    )
    assert sla_class_by_service_tier[expected_consumer_service_tier] == expected_consumer_sla_class
    assert (
        response_window_by_sla_class[expected_consumer_sla_class]
        == expected_consumer_response_window
    )
    assert (
        timing_posture_by_response_window[expected_consumer_response_window]
        == expected_consumer_timing_posture
    )
    consumer_response_window = {
        "projected_activation_decision": {"recommendation": decision},
        "approval_record": {
            "human_approval_status": {
                "status": {
                    "GO": "approved",
                    "PAUSE": "pending",
                    "REVIEW": "withheld",
                }[decision]
            }
        },
        "receiver_readiness_classification": expected_classification,
        "receiver_handling_directive": expected_handling_directive,
        "receiver_action_label": expected_action_label,
        "receiver_dispatch_intent": expected_dispatch_intent,
        "receiver_dispatch_mode": expected_dispatch_mode,
        "receiver_release_gate": expected_release_gate,
        "receiver_progress_state": expected_progress_state,
        "receiver_progress_signal": expected_progress_signal,
        "receiver_progress_outcome": expected_progress_outcome,
        "receiver_intervention_requirement": expected_intervention_requirement,
        "receiver_attention_level": expected_attention_level,
        "receiver_notification_requirement": expected_notification_requirement,
        "receiver_response_priority": expected_response_priority,
        "receiver_response_channel": expected_response_channel,
        "receiver_response_route": expected_response_route,
        "receiver_followup_requirement": expected_followup_requirement,
        "consumer_decision_posture": expected_consumer_decision_posture,
        "consumer_action_requirement": expected_consumer_action_requirement,
        "consumer_work_queue_assignment": expected_consumer_work_queue_assignment,
        "consumer_processing_plan": expected_consumer_processing_plan,
        "consumer_operator_requirement": expected_consumer_operator_requirement,
        "consumer_assignment_lane": expected_consumer_assignment_lane,
        "consumer_service_tier": expected_consumer_service_tier,
        "consumer_sla_class": expected_consumer_sla_class,
        "consumer_response_window": expected_consumer_response_window,
        "related_project_id": "project_consumer_timing_posture_1",
        "related_activation_decision_id": "activation_decision_consumer_timing_posture_1",
        "related_packet_id": "packet_consumer_timing_posture_1",
        "related_queue_item_id": "queue_consumer_timing_posture_1",
    }

    consumer_timing_posture = build_consumer_timing_posture_from_response_window(
        consumer_response_window=consumer_response_window
    )

    assert (
        consumer_timing_posture["projected_activation_decision"]
        == consumer_response_window["projected_activation_decision"]
    )
    assert consumer_timing_posture["approval_record"] == consumer_response_window[
        "approval_record"
    ]
    assert (
        consumer_timing_posture["receiver_readiness_classification"]
        == consumer_response_window["receiver_readiness_classification"]
    )
    assert (
        consumer_timing_posture["receiver_handling_directive"]
        == consumer_response_window["receiver_handling_directive"]
    )
    assert (
        consumer_timing_posture["receiver_action_label"]
        == consumer_response_window["receiver_action_label"]
    )
    assert (
        consumer_timing_posture["receiver_dispatch_intent"]
        == consumer_response_window["receiver_dispatch_intent"]
    )
    assert (
        consumer_timing_posture["receiver_dispatch_mode"]
        == consumer_response_window["receiver_dispatch_mode"]
    )
    assert (
        consumer_timing_posture["receiver_release_gate"]
        == consumer_response_window["receiver_release_gate"]
    )
    assert (
        consumer_timing_posture["receiver_progress_state"]
        == consumer_response_window["receiver_progress_state"]
    )
    assert (
        consumer_timing_posture["receiver_progress_signal"]
        == consumer_response_window["receiver_progress_signal"]
    )
    assert (
        consumer_timing_posture["receiver_progress_outcome"]
        == consumer_response_window["receiver_progress_outcome"]
    )
    assert (
        consumer_timing_posture["receiver_intervention_requirement"]
        == consumer_response_window["receiver_intervention_requirement"]
    )
    assert (
        consumer_timing_posture["receiver_attention_level"]
        == consumer_response_window["receiver_attention_level"]
    )
    assert (
        consumer_timing_posture["receiver_notification_requirement"]
        == consumer_response_window["receiver_notification_requirement"]
    )
    assert (
        consumer_timing_posture["receiver_response_priority"]
        == consumer_response_window["receiver_response_priority"]
    )
    assert (
        consumer_timing_posture["receiver_response_channel"]
        == consumer_response_window["receiver_response_channel"]
    )
    assert (
        consumer_timing_posture["receiver_response_route"]
        == consumer_response_window["receiver_response_route"]
    )
    assert (
        consumer_timing_posture["receiver_followup_requirement"]
        == consumer_response_window["receiver_followup_requirement"]
    )
    assert (
        consumer_timing_posture["consumer_decision_posture"]
        == consumer_response_window["consumer_decision_posture"]
    )
    assert (
        consumer_timing_posture["consumer_action_requirement"]
        == consumer_response_window["consumer_action_requirement"]
    )
    assert (
        consumer_timing_posture["consumer_work_queue_assignment"]
        == consumer_response_window["consumer_work_queue_assignment"]
    )
    assert (
        consumer_timing_posture["consumer_processing_plan"]
        == consumer_response_window["consumer_processing_plan"]
    )
    assert (
        consumer_timing_posture["consumer_operator_requirement"]
        == consumer_response_window["consumer_operator_requirement"]
    )
    assert (
        consumer_timing_posture["consumer_assignment_lane"]
        == consumer_response_window["consumer_assignment_lane"]
    )
    assert (
        consumer_timing_posture["consumer_service_tier"]
        == consumer_response_window["consumer_service_tier"]
    )
    assert (
        consumer_timing_posture["consumer_sla_class"]
        == consumer_response_window["consumer_sla_class"]
    )
    assert (
        consumer_timing_posture["consumer_response_window"]
        == consumer_response_window["consumer_response_window"]
    )
    assert (
        consumer_timing_posture["related_project_id"]
        == consumer_response_window["related_project_id"]
    )
    assert (
        consumer_timing_posture["related_activation_decision_id"]
        == consumer_response_window["related_activation_decision_id"]
    )
    assert (
        consumer_timing_posture["related_packet_id"]
        == consumer_response_window["related_packet_id"]
    )
    assert (
        consumer_timing_posture["related_queue_item_id"]
        == consumer_response_window["related_queue_item_id"]
    )
    assert (
        consumer_timing_posture["consumer_timing_posture"]
        == expected_consumer_timing_posture
    )


@pytest.mark.parametrize(
    (
        "decision",
        "expected_attention_level",
        "expected_notification_requirement",
        "expected_response_priority",
        "expected_response_channel",
        "expected_response_route",
        "expected_followup_requirement",
        "expected_consumer_decision_posture",
        "expected_consumer_action_requirement",
        "expected_consumer_work_queue_assignment",
        "expected_consumer_processing_plan",
        "expected_consumer_operator_requirement",
        "expected_consumer_assignment_lane",
        "expected_consumer_service_tier",
        "expected_consumer_sla_class",
        "expected_consumer_response_window",
        "expected_consumer_timing_posture",
        "expected_consumer_scheduling_commitment",
    ),
    [
        pytest.param(
            "GO",
            "low",
            "none",
            "normal",
            "standard_channel",
            "standard_route",
            "none",
            "observe",
            "no_action",
            "observation_queue",
            "observe_only",
            "none",
            "self_service_lane",
            "self_service",
            "deferred",
            "backlog_window",
            "later",
            "backlog_commitment",
            id="go",
        ),
        pytest.param(
            "PAUSE",
            "medium",
            "notify",
            "elevated",
            "priority_channel",
            "priority_route",
            "follow_up",
            "engage",
            "action_required",
            "action_queue",
            "process_action",
            "operator_required",
            "operator_lane",
            "operator_managed",
            "standard",
            "standard_window",
            "scheduled",
            "scheduled_commitment",
            id="pause",
        ),
        pytest.param(
            "REVIEW",
            "high",
            "escalate",
            "urgent",
            "escalation_channel",
            "escalation_route",
            "escalation_follow_up",
            "escalate",
            "escalation_required",
            "escalation_queue",
            "process_escalation",
            "senior_operator_required",
            "senior_operator_lane",
            "senior_managed",
            "priority",
            "priority_window",
            "immediate",
            "immediate_commitment",
            id="review",
        ),
    ],
)
def test_consumer_scheduling_commitment_from_timing_posture_matches_timing_posture(
    decision: RecommendationValue,
    expected_attention_level: str,
    expected_notification_requirement: str,
    expected_response_priority: str,
    expected_response_channel: str,
    expected_response_route: str,
    expected_followup_requirement: str,
    expected_consumer_decision_posture: str,
    expected_consumer_action_requirement: str,
    expected_consumer_work_queue_assignment: str,
    expected_consumer_processing_plan: str,
    expected_consumer_operator_requirement: str,
    expected_consumer_assignment_lane: str,
    expected_consumer_service_tier: str,
    expected_consumer_sla_class: str,
    expected_consumer_response_window: str,
    expected_consumer_timing_posture: str,
    expected_consumer_scheduling_commitment: str,
) -> None:
    expected_classification = {
        "GO": "ready",
        "PAUSE": "hold",
        "REVIEW": "needs_review",
    }[decision]
    expected_handling_directive = {
        "ready": "deliver",
        "hold": "defer",
        "needs_review": "route_for_review",
    }[expected_classification]
    expected_action_label = {
        "deliver": "dispatch",
        "defer": "wait",
        "route_for_review": "review_queue",
    }[expected_handling_directive]
    expected_dispatch_intent = {
        "dispatch": "send",
        "wait": "park",
        "review_queue": "review",
    }[expected_action_label]
    expected_dispatch_mode = {
        "send": "active",
        "park": "queued",
        "review": "review_pending",
    }[expected_dispatch_intent]
    expected_release_gate = {
        "active": "open",
        "queued": "deferred",
        "review_pending": "blocked_for_review",
    }[expected_dispatch_mode]
    expected_progress_state = {
        "open": "in_progress",
        "deferred": "pending",
        "blocked_for_review": "review_hold",
    }[expected_release_gate]
    expected_progress_signal = {
        "in_progress": "advance",
        "pending": "await",
        "review_hold": "review_wait",
    }[expected_progress_state]
    expected_progress_outcome = {
        "advance": "moving",
        "await": "standing_by",
        "review_wait": "awaiting_review",
    }[expected_progress_signal]
    expected_intervention_requirement = {
        "moving": "none",
        "standing_by": "monitor",
        "awaiting_review": "review_required",
    }[expected_progress_outcome]
    attention_level_by_intervention_requirement = {
        "none": "low",
        "monitor": "medium",
        "review_required": "high",
    }
    notification_requirement_by_attention_level = {
        "low": "none",
        "medium": "notify",
        "high": "escalate",
    }
    response_priority_by_notification_requirement = {
        "none": "normal",
        "notify": "elevated",
        "escalate": "urgent",
    }
    response_channel_by_priority = {
        "normal": "standard_channel",
        "elevated": "priority_channel",
        "urgent": "escalation_channel",
    }
    followup_requirement_by_route = {
        "standard_route": "none",
        "priority_route": "follow_up",
        "escalation_route": "escalation_follow_up",
    }
    posture_by_followup_requirement = {
        "none": "observe",
        "follow_up": "engage",
        "escalation_follow_up": "escalate",
    }
    action_requirement_by_posture = {
        "observe": "no_action",
        "engage": "action_required",
        "escalate": "escalation_required",
    }
    queue_assignment_by_action_requirement = {
        "no_action": "observation_queue",
        "action_required": "action_queue",
        "escalation_required": "escalation_queue",
    }
    processing_plan_by_queue_assignment = {
        "observation_queue": "observe_only",
        "action_queue": "process_action",
        "escalation_queue": "process_escalation",
    }
    operator_requirement_by_processing_plan = {
        "observe_only": "none",
        "process_action": "operator_required",
        "process_escalation": "senior_operator_required",
    }
    assignment_lane_by_operator_requirement = {
        "none": "self_service_lane",
        "operator_required": "operator_lane",
        "senior_operator_required": "senior_operator_lane",
    }
    service_tier_by_assignment_lane = {
        "self_service_lane": "self_service",
        "operator_lane": "operator_managed",
        "senior_operator_lane": "senior_managed",
    }
    sla_class_by_service_tier = {
        "self_service": "deferred",
        "operator_managed": "standard",
        "senior_managed": "priority",
    }
    response_window_by_sla_class = {
        "deferred": "backlog_window",
        "standard": "standard_window",
        "priority": "priority_window",
    }
    timing_posture_by_response_window = {
        "backlog_window": "later",
        "standard_window": "scheduled",
        "priority_window": "immediate",
    }
    scheduling_commitment_by_timing_posture = {
        "later": "backlog_commitment",
        "scheduled": "scheduled_commitment",
        "immediate": "immediate_commitment",
    }
    assert (
        attention_level_by_intervention_requirement[expected_intervention_requirement]
        == expected_attention_level
    )
    assert (
        notification_requirement_by_attention_level[expected_attention_level]
        == expected_notification_requirement
    )
    assert (
        response_priority_by_notification_requirement[expected_notification_requirement]
        == expected_response_priority
    )
    assert response_channel_by_priority[expected_response_priority] == expected_response_channel
    assert followup_requirement_by_route[expected_response_route] == expected_followup_requirement
    assert (
        posture_by_followup_requirement[expected_followup_requirement]
        == expected_consumer_decision_posture
    )
    assert (
        action_requirement_by_posture[expected_consumer_decision_posture]
        == expected_consumer_action_requirement
    )
    assert (
        queue_assignment_by_action_requirement[expected_consumer_action_requirement]
        == expected_consumer_work_queue_assignment
    )
    assert (
        processing_plan_by_queue_assignment[expected_consumer_work_queue_assignment]
        == expected_consumer_processing_plan
    )
    assert (
        operator_requirement_by_processing_plan[expected_consumer_processing_plan]
        == expected_consumer_operator_requirement
    )
    assert (
        assignment_lane_by_operator_requirement[expected_consumer_operator_requirement]
        == expected_consumer_assignment_lane
    )
    assert (
        service_tier_by_assignment_lane[expected_consumer_assignment_lane]
        == expected_consumer_service_tier
    )
    assert sla_class_by_service_tier[expected_consumer_service_tier] == expected_consumer_sla_class
    assert (
        response_window_by_sla_class[expected_consumer_sla_class]
        == expected_consumer_response_window
    )
    assert (
        timing_posture_by_response_window[expected_consumer_response_window]
        == expected_consumer_timing_posture
    )
    assert (
        scheduling_commitment_by_timing_posture[expected_consumer_timing_posture]
        == expected_consumer_scheduling_commitment
    )
    consumer_timing_posture = {
        "projected_activation_decision": {"recommendation": decision},
        "approval_record": {
            "human_approval_status": {
                "status": {
                    "GO": "approved",
                    "PAUSE": "pending",
                    "REVIEW": "withheld",
                }[decision]
            }
        },
        "receiver_readiness_classification": expected_classification,
        "receiver_handling_directive": expected_handling_directive,
        "receiver_action_label": expected_action_label,
        "receiver_dispatch_intent": expected_dispatch_intent,
        "receiver_dispatch_mode": expected_dispatch_mode,
        "receiver_release_gate": expected_release_gate,
        "receiver_progress_state": expected_progress_state,
        "receiver_progress_signal": expected_progress_signal,
        "receiver_progress_outcome": expected_progress_outcome,
        "receiver_intervention_requirement": expected_intervention_requirement,
        "receiver_attention_level": expected_attention_level,
        "receiver_notification_requirement": expected_notification_requirement,
        "receiver_response_priority": expected_response_priority,
        "receiver_response_channel": expected_response_channel,
        "receiver_response_route": expected_response_route,
        "receiver_followup_requirement": expected_followup_requirement,
        "consumer_decision_posture": expected_consumer_decision_posture,
        "consumer_action_requirement": expected_consumer_action_requirement,
        "consumer_work_queue_assignment": expected_consumer_work_queue_assignment,
        "consumer_processing_plan": expected_consumer_processing_plan,
        "consumer_operator_requirement": expected_consumer_operator_requirement,
        "consumer_assignment_lane": expected_consumer_assignment_lane,
        "consumer_service_tier": expected_consumer_service_tier,
        "consumer_sla_class": expected_consumer_sla_class,
        "consumer_response_window": expected_consumer_response_window,
        "consumer_timing_posture": expected_consumer_timing_posture,
        "related_project_id": "project_consumer_scheduling_commitment_1",
        "related_activation_decision_id": "activation_decision_consumer_scheduling_commitment_1",
        "related_packet_id": "packet_consumer_scheduling_commitment_1",
        "related_queue_item_id": "queue_consumer_scheduling_commitment_1",
    }

    consumer_scheduling_commitment = (
        build_consumer_scheduling_commitment_from_timing_posture(
            consumer_timing_posture=consumer_timing_posture
        )
    )

    assert (
        consumer_scheduling_commitment["projected_activation_decision"]
        == consumer_timing_posture["projected_activation_decision"]
    )
    assert consumer_scheduling_commitment["approval_record"] == consumer_timing_posture[
        "approval_record"
    ]
    assert (
        consumer_scheduling_commitment["receiver_readiness_classification"]
        == consumer_timing_posture["receiver_readiness_classification"]
    )
    assert (
        consumer_scheduling_commitment["receiver_handling_directive"]
        == consumer_timing_posture["receiver_handling_directive"]
    )
    assert (
        consumer_scheduling_commitment["receiver_action_label"]
        == consumer_timing_posture["receiver_action_label"]
    )
    assert (
        consumer_scheduling_commitment["receiver_dispatch_intent"]
        == consumer_timing_posture["receiver_dispatch_intent"]
    )
    assert (
        consumer_scheduling_commitment["receiver_dispatch_mode"]
        == consumer_timing_posture["receiver_dispatch_mode"]
    )
    assert (
        consumer_scheduling_commitment["receiver_release_gate"]
        == consumer_timing_posture["receiver_release_gate"]
    )
    assert (
        consumer_scheduling_commitment["receiver_progress_state"]
        == consumer_timing_posture["receiver_progress_state"]
    )
    assert (
        consumer_scheduling_commitment["receiver_progress_signal"]
        == consumer_timing_posture["receiver_progress_signal"]
    )
    assert (
        consumer_scheduling_commitment["receiver_progress_outcome"]
        == consumer_timing_posture["receiver_progress_outcome"]
    )
    assert (
        consumer_scheduling_commitment["receiver_intervention_requirement"]
        == consumer_timing_posture["receiver_intervention_requirement"]
    )
    assert (
        consumer_scheduling_commitment["receiver_attention_level"]
        == consumer_timing_posture["receiver_attention_level"]
    )
    assert (
        consumer_scheduling_commitment["receiver_notification_requirement"]
        == consumer_timing_posture["receiver_notification_requirement"]
    )
    assert (
        consumer_scheduling_commitment["receiver_response_priority"]
        == consumer_timing_posture["receiver_response_priority"]
    )
    assert (
        consumer_scheduling_commitment["receiver_response_channel"]
        == consumer_timing_posture["receiver_response_channel"]
    )
    assert (
        consumer_scheduling_commitment["receiver_response_route"]
        == consumer_timing_posture["receiver_response_route"]
    )
    assert (
        consumer_scheduling_commitment["receiver_followup_requirement"]
        == consumer_timing_posture["receiver_followup_requirement"]
    )
    assert (
        consumer_scheduling_commitment["consumer_decision_posture"]
        == consumer_timing_posture["consumer_decision_posture"]
    )
    assert (
        consumer_scheduling_commitment["consumer_action_requirement"]
        == consumer_timing_posture["consumer_action_requirement"]
    )
    assert (
        consumer_scheduling_commitment["consumer_work_queue_assignment"]
        == consumer_timing_posture["consumer_work_queue_assignment"]
    )
    assert (
        consumer_scheduling_commitment["consumer_processing_plan"]
        == consumer_timing_posture["consumer_processing_plan"]
    )
    assert (
        consumer_scheduling_commitment["consumer_operator_requirement"]
        == consumer_timing_posture["consumer_operator_requirement"]
    )
    assert (
        consumer_scheduling_commitment["consumer_assignment_lane"]
        == consumer_timing_posture["consumer_assignment_lane"]
    )
    assert (
        consumer_scheduling_commitment["consumer_service_tier"]
        == consumer_timing_posture["consumer_service_tier"]
    )
    assert (
        consumer_scheduling_commitment["consumer_sla_class"]
        == consumer_timing_posture["consumer_sla_class"]
    )
    assert (
        consumer_scheduling_commitment["consumer_response_window"]
        == consumer_timing_posture["consumer_response_window"]
    )
    assert (
        consumer_scheduling_commitment["consumer_timing_posture"]
        == consumer_timing_posture["consumer_timing_posture"]
    )
    assert (
        consumer_scheduling_commitment["related_project_id"]
        == consumer_timing_posture["related_project_id"]
    )
    assert (
        consumer_scheduling_commitment["related_activation_decision_id"]
        == consumer_timing_posture["related_activation_decision_id"]
    )
    assert (
        consumer_scheduling_commitment["related_packet_id"]
        == consumer_timing_posture["related_packet_id"]
    )
    assert (
        consumer_scheduling_commitment["related_queue_item_id"]
        == consumer_timing_posture["related_queue_item_id"]
    )
    assert (
        consumer_scheduling_commitment["consumer_scheduling_commitment"]
        == expected_consumer_scheduling_commitment
    )


@pytest.mark.parametrize(
    (
        "decision",
        "expected_attention_level",
        "expected_notification_requirement",
        "expected_response_priority",
        "expected_response_channel",
        "expected_response_route",
        "expected_followup_requirement",
        "expected_consumer_decision_posture",
        "expected_consumer_action_requirement",
        "expected_consumer_work_queue_assignment",
        "expected_consumer_processing_plan",
        "expected_consumer_operator_requirement",
        "expected_consumer_assignment_lane",
        "expected_consumer_service_tier",
        "expected_consumer_sla_class",
        "expected_consumer_response_window",
        "expected_consumer_timing_posture",
        "expected_consumer_scheduling_commitment",
        "expected_consumer_execution_readiness",
    ),
    [
        pytest.param(
            "GO",
            "low",
            "none",
            "normal",
            "standard_channel",
            "standard_route",
            "none",
            "observe",
            "no_action",
            "observation_queue",
            "observe_only",
            "none",
            "self_service_lane",
            "self_service",
            "deferred",
            "backlog_window",
            "later",
            "backlog_commitment",
            "deferred_readiness",
            id="go",
        ),
        pytest.param(
            "PAUSE",
            "medium",
            "notify",
            "elevated",
            "priority_channel",
            "priority_route",
            "follow_up",
            "engage",
            "action_required",
            "action_queue",
            "process_action",
            "operator_required",
            "operator_lane",
            "operator_managed",
            "standard",
            "standard_window",
            "scheduled",
            "scheduled_commitment",
            "planned_readiness",
            id="pause",
        ),
        pytest.param(
            "REVIEW",
            "high",
            "escalate",
            "urgent",
            "escalation_channel",
            "escalation_route",
            "escalation_follow_up",
            "escalate",
            "escalation_required",
            "escalation_queue",
            "process_escalation",
            "senior_operator_required",
            "senior_operator_lane",
            "senior_managed",
            "priority",
            "priority_window",
            "immediate",
            "immediate_commitment",
            "ready_now",
            id="review",
        ),
    ],
)
def test_consumer_execution_readiness_from_scheduling_commitment_matches_scheduling_commitment(
    decision: RecommendationValue,
    expected_attention_level: str,
    expected_notification_requirement: str,
    expected_response_priority: str,
    expected_response_channel: str,
    expected_response_route: str,
    expected_followup_requirement: str,
    expected_consumer_decision_posture: str,
    expected_consumer_action_requirement: str,
    expected_consumer_work_queue_assignment: str,
    expected_consumer_processing_plan: str,
    expected_consumer_operator_requirement: str,
    expected_consumer_assignment_lane: str,
    expected_consumer_service_tier: str,
    expected_consumer_sla_class: str,
    expected_consumer_response_window: str,
    expected_consumer_timing_posture: str,
    expected_consumer_scheduling_commitment: str,
    expected_consumer_execution_readiness: str,
) -> None:
    expected_classification = {
        "GO": "ready",
        "PAUSE": "hold",
        "REVIEW": "needs_review",
    }[decision]
    expected_handling_directive = {
        "ready": "deliver",
        "hold": "defer",
        "needs_review": "route_for_review",
    }[expected_classification]
    expected_action_label = {
        "deliver": "dispatch",
        "defer": "wait",
        "route_for_review": "review_queue",
    }[expected_handling_directive]
    expected_dispatch_intent = {
        "dispatch": "send",
        "wait": "park",
        "review_queue": "review",
    }[expected_action_label]
    expected_dispatch_mode = {
        "send": "active",
        "park": "queued",
        "review": "review_pending",
    }[expected_dispatch_intent]
    expected_release_gate = {
        "active": "open",
        "queued": "deferred",
        "review_pending": "blocked_for_review",
    }[expected_dispatch_mode]
    expected_progress_state = {
        "open": "in_progress",
        "deferred": "pending",
        "blocked_for_review": "review_hold",
    }[expected_release_gate]
    expected_progress_signal = {
        "in_progress": "advance",
        "pending": "await",
        "review_hold": "review_wait",
    }[expected_progress_state]
    expected_progress_outcome = {
        "advance": "moving",
        "await": "standing_by",
        "review_wait": "awaiting_review",
    }[expected_progress_signal]
    expected_intervention_requirement = {
        "moving": "none",
        "standing_by": "monitor",
        "awaiting_review": "review_required",
    }[expected_progress_outcome]
    attention_level_by_intervention_requirement = {
        "none": "low",
        "monitor": "medium",
        "review_required": "high",
    }
    notification_requirement_by_attention_level = {
        "low": "none",
        "medium": "notify",
        "high": "escalate",
    }
    response_priority_by_notification_requirement = {
        "none": "normal",
        "notify": "elevated",
        "escalate": "urgent",
    }
    response_channel_by_priority = {
        "normal": "standard_channel",
        "elevated": "priority_channel",
        "urgent": "escalation_channel",
    }
    followup_requirement_by_route = {
        "standard_route": "none",
        "priority_route": "follow_up",
        "escalation_route": "escalation_follow_up",
    }
    posture_by_followup_requirement = {
        "none": "observe",
        "follow_up": "engage",
        "escalation_follow_up": "escalate",
    }
    action_requirement_by_posture = {
        "observe": "no_action",
        "engage": "action_required",
        "escalate": "escalation_required",
    }
    queue_assignment_by_action_requirement = {
        "no_action": "observation_queue",
        "action_required": "action_queue",
        "escalation_required": "escalation_queue",
    }
    processing_plan_by_queue_assignment = {
        "observation_queue": "observe_only",
        "action_queue": "process_action",
        "escalation_queue": "process_escalation",
    }
    operator_requirement_by_processing_plan = {
        "observe_only": "none",
        "process_action": "operator_required",
        "process_escalation": "senior_operator_required",
    }
    assignment_lane_by_operator_requirement = {
        "none": "self_service_lane",
        "operator_required": "operator_lane",
        "senior_operator_required": "senior_operator_lane",
    }
    service_tier_by_assignment_lane = {
        "self_service_lane": "self_service",
        "operator_lane": "operator_managed",
        "senior_operator_lane": "senior_managed",
    }
    sla_class_by_service_tier = {
        "self_service": "deferred",
        "operator_managed": "standard",
        "senior_managed": "priority",
    }
    response_window_by_sla_class = {
        "deferred": "backlog_window",
        "standard": "standard_window",
        "priority": "priority_window",
    }
    timing_posture_by_response_window = {
        "backlog_window": "later",
        "standard_window": "scheduled",
        "priority_window": "immediate",
    }
    scheduling_commitment_by_timing_posture = {
        "later": "backlog_commitment",
        "scheduled": "scheduled_commitment",
        "immediate": "immediate_commitment",
    }
    execution_readiness_by_scheduling_commitment = {
        "backlog_commitment": "deferred_readiness",
        "scheduled_commitment": "planned_readiness",
        "immediate_commitment": "ready_now",
    }
    assert (
        attention_level_by_intervention_requirement[expected_intervention_requirement]
        == expected_attention_level
    )
    assert (
        notification_requirement_by_attention_level[expected_attention_level]
        == expected_notification_requirement
    )
    assert (
        response_priority_by_notification_requirement[expected_notification_requirement]
        == expected_response_priority
    )
    assert response_channel_by_priority[expected_response_priority] == expected_response_channel
    assert followup_requirement_by_route[expected_response_route] == expected_followup_requirement
    assert (
        posture_by_followup_requirement[expected_followup_requirement]
        == expected_consumer_decision_posture
    )
    assert (
        action_requirement_by_posture[expected_consumer_decision_posture]
        == expected_consumer_action_requirement
    )
    assert (
        queue_assignment_by_action_requirement[expected_consumer_action_requirement]
        == expected_consumer_work_queue_assignment
    )
    assert (
        processing_plan_by_queue_assignment[expected_consumer_work_queue_assignment]
        == expected_consumer_processing_plan
    )
    assert (
        operator_requirement_by_processing_plan[expected_consumer_processing_plan]
        == expected_consumer_operator_requirement
    )
    assert (
        assignment_lane_by_operator_requirement[expected_consumer_operator_requirement]
        == expected_consumer_assignment_lane
    )
    assert (
        service_tier_by_assignment_lane[expected_consumer_assignment_lane]
        == expected_consumer_service_tier
    )
    assert sla_class_by_service_tier[expected_consumer_service_tier] == expected_consumer_sla_class
    assert (
        response_window_by_sla_class[expected_consumer_sla_class]
        == expected_consumer_response_window
    )
    assert (
        timing_posture_by_response_window[expected_consumer_response_window]
        == expected_consumer_timing_posture
    )
    assert (
        scheduling_commitment_by_timing_posture[expected_consumer_timing_posture]
        == expected_consumer_scheduling_commitment
    )
    assert (
        execution_readiness_by_scheduling_commitment[expected_consumer_scheduling_commitment]
        == expected_consumer_execution_readiness
    )
    consumer_scheduling_commitment = {
        "projected_activation_decision": {"recommendation": decision},
        "approval_record": {
            "human_approval_status": {
                "status": {
                    "GO": "approved",
                    "PAUSE": "pending",
                    "REVIEW": "withheld",
                }[decision]
            }
        },
        "receiver_readiness_classification": expected_classification,
        "receiver_handling_directive": expected_handling_directive,
        "receiver_action_label": expected_action_label,
        "receiver_dispatch_intent": expected_dispatch_intent,
        "receiver_dispatch_mode": expected_dispatch_mode,
        "receiver_release_gate": expected_release_gate,
        "receiver_progress_state": expected_progress_state,
        "receiver_progress_signal": expected_progress_signal,
        "receiver_progress_outcome": expected_progress_outcome,
        "receiver_intervention_requirement": expected_intervention_requirement,
        "receiver_attention_level": expected_attention_level,
        "receiver_notification_requirement": expected_notification_requirement,
        "receiver_response_priority": expected_response_priority,
        "receiver_response_channel": expected_response_channel,
        "receiver_response_route": expected_response_route,
        "receiver_followup_requirement": expected_followup_requirement,
        "consumer_decision_posture": expected_consumer_decision_posture,
        "consumer_action_requirement": expected_consumer_action_requirement,
        "consumer_work_queue_assignment": expected_consumer_work_queue_assignment,
        "consumer_processing_plan": expected_consumer_processing_plan,
        "consumer_operator_requirement": expected_consumer_operator_requirement,
        "consumer_assignment_lane": expected_consumer_assignment_lane,
        "consumer_service_tier": expected_consumer_service_tier,
        "consumer_sla_class": expected_consumer_sla_class,
        "consumer_response_window": expected_consumer_response_window,
        "consumer_timing_posture": expected_consumer_timing_posture,
        "consumer_scheduling_commitment": expected_consumer_scheduling_commitment,
        "related_project_id": "project_consumer_execution_readiness_1",
        "related_activation_decision_id": "activation_decision_consumer_execution_readiness_1",
        "related_packet_id": "packet_consumer_execution_readiness_1",
        "related_queue_item_id": "queue_consumer_execution_readiness_1",
    }

    consumer_execution_readiness = (
        build_consumer_execution_readiness_from_scheduling_commitment(
            consumer_scheduling_commitment=consumer_scheduling_commitment
        )
    )

    assert (
        consumer_execution_readiness["projected_activation_decision"]
        == consumer_scheduling_commitment["projected_activation_decision"]
    )
    assert consumer_execution_readiness["approval_record"] == consumer_scheduling_commitment[
        "approval_record"
    ]
    assert (
        consumer_execution_readiness["receiver_readiness_classification"]
        == consumer_scheduling_commitment["receiver_readiness_classification"]
    )
    assert (
        consumer_execution_readiness["receiver_handling_directive"]
        == consumer_scheduling_commitment["receiver_handling_directive"]
    )
    assert (
        consumer_execution_readiness["receiver_action_label"]
        == consumer_scheduling_commitment["receiver_action_label"]
    )
    assert (
        consumer_execution_readiness["receiver_dispatch_intent"]
        == consumer_scheduling_commitment["receiver_dispatch_intent"]
    )
    assert (
        consumer_execution_readiness["receiver_dispatch_mode"]
        == consumer_scheduling_commitment["receiver_dispatch_mode"]
    )
    assert (
        consumer_execution_readiness["receiver_release_gate"]
        == consumer_scheduling_commitment["receiver_release_gate"]
    )
    assert (
        consumer_execution_readiness["receiver_progress_state"]
        == consumer_scheduling_commitment["receiver_progress_state"]
    )
    assert (
        consumer_execution_readiness["receiver_progress_signal"]
        == consumer_scheduling_commitment["receiver_progress_signal"]
    )
    assert (
        consumer_execution_readiness["receiver_progress_outcome"]
        == consumer_scheduling_commitment["receiver_progress_outcome"]
    )
    assert (
        consumer_execution_readiness["receiver_intervention_requirement"]
        == consumer_scheduling_commitment["receiver_intervention_requirement"]
    )
    assert (
        consumer_execution_readiness["receiver_attention_level"]
        == consumer_scheduling_commitment["receiver_attention_level"]
    )
    assert (
        consumer_execution_readiness["receiver_notification_requirement"]
        == consumer_scheduling_commitment["receiver_notification_requirement"]
    )
    assert (
        consumer_execution_readiness["receiver_response_priority"]
        == consumer_scheduling_commitment["receiver_response_priority"]
    )
    assert (
        consumer_execution_readiness["receiver_response_channel"]
        == consumer_scheduling_commitment["receiver_response_channel"]
    )
    assert (
        consumer_execution_readiness["receiver_response_route"]
        == consumer_scheduling_commitment["receiver_response_route"]
    )
    assert (
        consumer_execution_readiness["receiver_followup_requirement"]
        == consumer_scheduling_commitment["receiver_followup_requirement"]
    )
    assert (
        consumer_execution_readiness["consumer_decision_posture"]
        == consumer_scheduling_commitment["consumer_decision_posture"]
    )
    assert (
        consumer_execution_readiness["consumer_action_requirement"]
        == consumer_scheduling_commitment["consumer_action_requirement"]
    )
    assert (
        consumer_execution_readiness["consumer_work_queue_assignment"]
        == consumer_scheduling_commitment["consumer_work_queue_assignment"]
    )
    assert (
        consumer_execution_readiness["consumer_processing_plan"]
        == consumer_scheduling_commitment["consumer_processing_plan"]
    )
    assert (
        consumer_execution_readiness["consumer_operator_requirement"]
        == consumer_scheduling_commitment["consumer_operator_requirement"]
    )
    assert (
        consumer_execution_readiness["consumer_assignment_lane"]
        == consumer_scheduling_commitment["consumer_assignment_lane"]
    )
    assert (
        consumer_execution_readiness["consumer_service_tier"]
        == consumer_scheduling_commitment["consumer_service_tier"]
    )
    assert (
        consumer_execution_readiness["consumer_sla_class"]
        == consumer_scheduling_commitment["consumer_sla_class"]
    )
    assert (
        consumer_execution_readiness["consumer_response_window"]
        == consumer_scheduling_commitment["consumer_response_window"]
    )
    assert (
        consumer_execution_readiness["consumer_timing_posture"]
        == consumer_scheduling_commitment["consumer_timing_posture"]
    )
    assert (
        consumer_execution_readiness["consumer_scheduling_commitment"]
        == consumer_scheduling_commitment["consumer_scheduling_commitment"]
    )
    assert (
        consumer_execution_readiness["related_project_id"]
        == consumer_scheduling_commitment["related_project_id"]
    )
    assert (
        consumer_execution_readiness["related_activation_decision_id"]
        == consumer_scheduling_commitment["related_activation_decision_id"]
    )
    assert (
        consumer_execution_readiness["related_packet_id"]
        == consumer_scheduling_commitment["related_packet_id"]
    )
    assert (
        consumer_execution_readiness["related_queue_item_id"]
        == consumer_scheduling_commitment["related_queue_item_id"]
    )
    assert (
        consumer_execution_readiness["consumer_execution_readiness"]
        == expected_consumer_execution_readiness
    )


@pytest.mark.parametrize(
    (
        "decision",
        "expected_attention_level",
        "expected_notification_requirement",
        "expected_response_priority",
        "expected_response_channel",
        "expected_response_route",
        "expected_followup_requirement",
        "expected_consumer_decision_posture",
        "expected_consumer_action_requirement",
        "expected_consumer_work_queue_assignment",
        "expected_consumer_processing_plan",
        "expected_consumer_operator_requirement",
        "expected_consumer_assignment_lane",
        "expected_consumer_service_tier",
        "expected_consumer_sla_class",
        "expected_consumer_response_window",
        "expected_consumer_timing_posture",
        "expected_consumer_scheduling_commitment",
        "expected_consumer_execution_readiness",
        "expected_consumer_dispatch_readiness",
    ),
    [
        pytest.param(
            "GO",
            "low",
            "none",
            "normal",
            "standard_channel",
            "standard_route",
            "none",
            "observe",
            "no_action",
            "observation_queue",
            "observe_only",
            "none",
            "self_service_lane",
            "self_service",
            "deferred",
            "backlog_window",
            "later",
            "backlog_commitment",
            "deferred_readiness",
            "parked",
            id="go",
        ),
        pytest.param(
            "PAUSE",
            "medium",
            "notify",
            "elevated",
            "priority_channel",
            "priority_route",
            "follow_up",
            "engage",
            "action_required",
            "action_queue",
            "process_action",
            "operator_required",
            "operator_lane",
            "operator_managed",
            "standard",
            "standard_window",
            "scheduled",
            "scheduled_commitment",
            "planned_readiness",
            "prepared",
            id="pause",
        ),
        pytest.param(
            "REVIEW",
            "high",
            "escalate",
            "urgent",
            "escalation_channel",
            "escalation_route",
            "escalation_follow_up",
            "escalate",
            "escalation_required",
            "escalation_queue",
            "process_escalation",
            "senior_operator_required",
            "senior_operator_lane",
            "senior_managed",
            "priority",
            "priority_window",
            "immediate",
            "immediate_commitment",
            "ready_now",
            "dispatch_ready",
            id="review",
        ),
    ],
)
def test_consumer_dispatch_readiness_from_execution_readiness_matches_execution_readiness(
    decision: RecommendationValue,
    expected_attention_level: str,
    expected_notification_requirement: str,
    expected_response_priority: str,
    expected_response_channel: str,
    expected_response_route: str,
    expected_followup_requirement: str,
    expected_consumer_decision_posture: str,
    expected_consumer_action_requirement: str,
    expected_consumer_work_queue_assignment: str,
    expected_consumer_processing_plan: str,
    expected_consumer_operator_requirement: str,
    expected_consumer_assignment_lane: str,
    expected_consumer_service_tier: str,
    expected_consumer_sla_class: str,
    expected_consumer_response_window: str,
    expected_consumer_timing_posture: str,
    expected_consumer_scheduling_commitment: str,
    expected_consumer_execution_readiness: str,
    expected_consumer_dispatch_readiness: str,
) -> None:
    expected_classification = {
        "GO": "ready",
        "PAUSE": "hold",
        "REVIEW": "needs_review",
    }[decision]
    expected_handling_directive = {
        "ready": "deliver",
        "hold": "defer",
        "needs_review": "route_for_review",
    }[expected_classification]
    expected_action_label = {
        "deliver": "dispatch",
        "defer": "wait",
        "route_for_review": "review_queue",
    }[expected_handling_directive]
    expected_dispatch_intent = {
        "dispatch": "send",
        "wait": "park",
        "review_queue": "review",
    }[expected_action_label]
    expected_dispatch_mode = {
        "send": "active",
        "park": "queued",
        "review": "review_pending",
    }[expected_dispatch_intent]
    expected_release_gate = {
        "active": "open",
        "queued": "deferred",
        "review_pending": "blocked_for_review",
    }[expected_dispatch_mode]
    expected_progress_state = {
        "open": "in_progress",
        "deferred": "pending",
        "blocked_for_review": "review_hold",
    }[expected_release_gate]
    expected_progress_signal = {
        "in_progress": "advance",
        "pending": "await",
        "review_hold": "review_wait",
    }[expected_progress_state]
    expected_progress_outcome = {
        "advance": "moving",
        "await": "standing_by",
        "review_wait": "awaiting_review",
    }[expected_progress_signal]
    expected_intervention_requirement = {
        "moving": "none",
        "standing_by": "monitor",
        "awaiting_review": "review_required",
    }[expected_progress_outcome]
    attention_level_by_intervention_requirement = {
        "none": "low",
        "monitor": "medium",
        "review_required": "high",
    }
    notification_requirement_by_attention_level = {
        "low": "none",
        "medium": "notify",
        "high": "escalate",
    }
    response_priority_by_notification_requirement = {
        "none": "normal",
        "notify": "elevated",
        "escalate": "urgent",
    }
    response_channel_by_priority = {
        "normal": "standard_channel",
        "elevated": "priority_channel",
        "urgent": "escalation_channel",
    }
    followup_requirement_by_route = {
        "standard_route": "none",
        "priority_route": "follow_up",
        "escalation_route": "escalation_follow_up",
    }
    posture_by_followup_requirement = {
        "none": "observe",
        "follow_up": "engage",
        "escalation_follow_up": "escalate",
    }
    action_requirement_by_posture = {
        "observe": "no_action",
        "engage": "action_required",
        "escalate": "escalation_required",
    }
    queue_assignment_by_action_requirement = {
        "no_action": "observation_queue",
        "action_required": "action_queue",
        "escalation_required": "escalation_queue",
    }
    processing_plan_by_queue_assignment = {
        "observation_queue": "observe_only",
        "action_queue": "process_action",
        "escalation_queue": "process_escalation",
    }
    operator_requirement_by_processing_plan = {
        "observe_only": "none",
        "process_action": "operator_required",
        "process_escalation": "senior_operator_required",
    }
    assignment_lane_by_operator_requirement = {
        "none": "self_service_lane",
        "operator_required": "operator_lane",
        "senior_operator_required": "senior_operator_lane",
    }
    service_tier_by_assignment_lane = {
        "self_service_lane": "self_service",
        "operator_lane": "operator_managed",
        "senior_operator_lane": "senior_managed",
    }
    sla_class_by_service_tier = {
        "self_service": "deferred",
        "operator_managed": "standard",
        "senior_managed": "priority",
    }
    response_window_by_sla_class = {
        "deferred": "backlog_window",
        "standard": "standard_window",
        "priority": "priority_window",
    }
    timing_posture_by_response_window = {
        "backlog_window": "later",
        "standard_window": "scheduled",
        "priority_window": "immediate",
    }
    scheduling_commitment_by_timing_posture = {
        "later": "backlog_commitment",
        "scheduled": "scheduled_commitment",
        "immediate": "immediate_commitment",
    }
    execution_readiness_by_scheduling_commitment = {
        "backlog_commitment": "deferred_readiness",
        "scheduled_commitment": "planned_readiness",
        "immediate_commitment": "ready_now",
    }
    dispatch_readiness_by_execution_readiness = {
        "deferred_readiness": "parked",
        "planned_readiness": "prepared",
        "ready_now": "dispatch_ready",
    }
    assert (
        attention_level_by_intervention_requirement[expected_intervention_requirement]
        == expected_attention_level
    )
    assert (
        notification_requirement_by_attention_level[expected_attention_level]
        == expected_notification_requirement
    )
    assert (
        response_priority_by_notification_requirement[expected_notification_requirement]
        == expected_response_priority
    )
    assert response_channel_by_priority[expected_response_priority] == expected_response_channel
    assert followup_requirement_by_route[expected_response_route] == expected_followup_requirement
    assert (
        posture_by_followup_requirement[expected_followup_requirement]
        == expected_consumer_decision_posture
    )
    assert (
        action_requirement_by_posture[expected_consumer_decision_posture]
        == expected_consumer_action_requirement
    )
    assert (
        queue_assignment_by_action_requirement[expected_consumer_action_requirement]
        == expected_consumer_work_queue_assignment
    )
    assert (
        processing_plan_by_queue_assignment[expected_consumer_work_queue_assignment]
        == expected_consumer_processing_plan
    )
    assert (
        operator_requirement_by_processing_plan[expected_consumer_processing_plan]
        == expected_consumer_operator_requirement
    )
    assert (
        assignment_lane_by_operator_requirement[expected_consumer_operator_requirement]
        == expected_consumer_assignment_lane
    )
    assert (
        service_tier_by_assignment_lane[expected_consumer_assignment_lane]
        == expected_consumer_service_tier
    )
    assert sla_class_by_service_tier[expected_consumer_service_tier] == expected_consumer_sla_class
    assert (
        response_window_by_sla_class[expected_consumer_sla_class]
        == expected_consumer_response_window
    )
    assert (
        timing_posture_by_response_window[expected_consumer_response_window]
        == expected_consumer_timing_posture
    )
    assert (
        scheduling_commitment_by_timing_posture[expected_consumer_timing_posture]
        == expected_consumer_scheduling_commitment
    )
    assert (
        execution_readiness_by_scheduling_commitment[expected_consumer_scheduling_commitment]
        == expected_consumer_execution_readiness
    )
    assert (
        dispatch_readiness_by_execution_readiness[expected_consumer_execution_readiness]
        == expected_consumer_dispatch_readiness
    )
    consumer_execution_readiness = {
        "projected_activation_decision": {"recommendation": decision},
        "approval_record": {
            "human_approval_status": {
                "status": {
                    "GO": "approved",
                    "PAUSE": "pending",
                    "REVIEW": "withheld",
                }[decision]
            }
        },
        "receiver_readiness_classification": expected_classification,
        "receiver_handling_directive": expected_handling_directive,
        "receiver_action_label": expected_action_label,
        "receiver_dispatch_intent": expected_dispatch_intent,
        "receiver_dispatch_mode": expected_dispatch_mode,
        "receiver_release_gate": expected_release_gate,
        "receiver_progress_state": expected_progress_state,
        "receiver_progress_signal": expected_progress_signal,
        "receiver_progress_outcome": expected_progress_outcome,
        "receiver_intervention_requirement": expected_intervention_requirement,
        "receiver_attention_level": expected_attention_level,
        "receiver_notification_requirement": expected_notification_requirement,
        "receiver_response_priority": expected_response_priority,
        "receiver_response_channel": expected_response_channel,
        "receiver_response_route": expected_response_route,
        "receiver_followup_requirement": expected_followup_requirement,
        "consumer_decision_posture": expected_consumer_decision_posture,
        "consumer_action_requirement": expected_consumer_action_requirement,
        "consumer_work_queue_assignment": expected_consumer_work_queue_assignment,
        "consumer_processing_plan": expected_consumer_processing_plan,
        "consumer_operator_requirement": expected_consumer_operator_requirement,
        "consumer_assignment_lane": expected_consumer_assignment_lane,
        "consumer_service_tier": expected_consumer_service_tier,
        "consumer_sla_class": expected_consumer_sla_class,
        "consumer_response_window": expected_consumer_response_window,
        "consumer_timing_posture": expected_consumer_timing_posture,
        "consumer_scheduling_commitment": expected_consumer_scheduling_commitment,
        "consumer_execution_readiness": expected_consumer_execution_readiness,
        "related_project_id": "project_consumer_dispatch_readiness_1",
        "related_activation_decision_id": "activation_decision_consumer_dispatch_readiness_1",
        "related_packet_id": "packet_consumer_dispatch_readiness_1",
        "related_queue_item_id": "queue_consumer_dispatch_readiness_1",
    }

    consumer_dispatch_readiness = (
        build_consumer_dispatch_readiness_from_execution_readiness(
            consumer_execution_readiness=consumer_execution_readiness
        )
    )

    assert (
        consumer_dispatch_readiness["projected_activation_decision"]
        == consumer_execution_readiness["projected_activation_decision"]
    )
    assert consumer_dispatch_readiness["approval_record"] == consumer_execution_readiness[
        "approval_record"
    ]
    assert (
        consumer_dispatch_readiness["receiver_readiness_classification"]
        == consumer_execution_readiness["receiver_readiness_classification"]
    )
    assert (
        consumer_dispatch_readiness["receiver_handling_directive"]
        == consumer_execution_readiness["receiver_handling_directive"]
    )
    assert (
        consumer_dispatch_readiness["receiver_action_label"]
        == consumer_execution_readiness["receiver_action_label"]
    )
    assert (
        consumer_dispatch_readiness["receiver_dispatch_intent"]
        == consumer_execution_readiness["receiver_dispatch_intent"]
    )
    assert (
        consumer_dispatch_readiness["receiver_dispatch_mode"]
        == consumer_execution_readiness["receiver_dispatch_mode"]
    )
    assert (
        consumer_dispatch_readiness["receiver_release_gate"]
        == consumer_execution_readiness["receiver_release_gate"]
    )
    assert (
        consumer_dispatch_readiness["receiver_progress_state"]
        == consumer_execution_readiness["receiver_progress_state"]
    )
    assert (
        consumer_dispatch_readiness["receiver_progress_signal"]
        == consumer_execution_readiness["receiver_progress_signal"]
    )
    assert (
        consumer_dispatch_readiness["receiver_progress_outcome"]
        == consumer_execution_readiness["receiver_progress_outcome"]
    )
    assert (
        consumer_dispatch_readiness["receiver_intervention_requirement"]
        == consumer_execution_readiness["receiver_intervention_requirement"]
    )
    assert (
        consumer_dispatch_readiness["receiver_attention_level"]
        == consumer_execution_readiness["receiver_attention_level"]
    )
    assert (
        consumer_dispatch_readiness["receiver_notification_requirement"]
        == consumer_execution_readiness["receiver_notification_requirement"]
    )
    assert (
        consumer_dispatch_readiness["receiver_response_priority"]
        == consumer_execution_readiness["receiver_response_priority"]
    )
    assert (
        consumer_dispatch_readiness["receiver_response_channel"]
        == consumer_execution_readiness["receiver_response_channel"]
    )
    assert (
        consumer_dispatch_readiness["receiver_response_route"]
        == consumer_execution_readiness["receiver_response_route"]
    )
    assert (
        consumer_dispatch_readiness["receiver_followup_requirement"]
        == consumer_execution_readiness["receiver_followup_requirement"]
    )
    assert (
        consumer_dispatch_readiness["consumer_decision_posture"]
        == consumer_execution_readiness["consumer_decision_posture"]
    )
    assert (
        consumer_dispatch_readiness["consumer_action_requirement"]
        == consumer_execution_readiness["consumer_action_requirement"]
    )
    assert (
        consumer_dispatch_readiness["consumer_work_queue_assignment"]
        == consumer_execution_readiness["consumer_work_queue_assignment"]
    )
    assert (
        consumer_dispatch_readiness["consumer_processing_plan"]
        == consumer_execution_readiness["consumer_processing_plan"]
    )
    assert (
        consumer_dispatch_readiness["consumer_operator_requirement"]
        == consumer_execution_readiness["consumer_operator_requirement"]
    )
    assert (
        consumer_dispatch_readiness["consumer_assignment_lane"]
        == consumer_execution_readiness["consumer_assignment_lane"]
    )
    assert (
        consumer_dispatch_readiness["consumer_service_tier"]
        == consumer_execution_readiness["consumer_service_tier"]
    )
    assert (
        consumer_dispatch_readiness["consumer_sla_class"]
        == consumer_execution_readiness["consumer_sla_class"]
    )
    assert (
        consumer_dispatch_readiness["consumer_response_window"]
        == consumer_execution_readiness["consumer_response_window"]
    )
    assert (
        consumer_dispatch_readiness["consumer_timing_posture"]
        == consumer_execution_readiness["consumer_timing_posture"]
    )
    assert (
        consumer_dispatch_readiness["consumer_scheduling_commitment"]
        == consumer_execution_readiness["consumer_scheduling_commitment"]
    )
    assert (
        consumer_dispatch_readiness["consumer_execution_readiness"]
        == consumer_execution_readiness["consumer_execution_readiness"]
    )
    assert (
        consumer_dispatch_readiness["related_project_id"]
        == consumer_execution_readiness["related_project_id"]
    )
    assert (
        consumer_dispatch_readiness["related_activation_decision_id"]
        == consumer_execution_readiness["related_activation_decision_id"]
    )
    assert (
        consumer_dispatch_readiness["related_packet_id"]
        == consumer_execution_readiness["related_packet_id"]
    )
    assert (
        consumer_dispatch_readiness["related_queue_item_id"]
        == consumer_execution_readiness["related_queue_item_id"]
    )
    assert (
        consumer_dispatch_readiness["consumer_dispatch_readiness"]
        == expected_consumer_dispatch_readiness
    )


@pytest.mark.parametrize(
    (
        "decision",
        "expected_attention_level",
        "expected_notification_requirement",
        "expected_response_priority",
        "expected_response_channel",
        "expected_response_route",
        "expected_followup_requirement",
        "expected_consumer_decision_posture",
        "expected_consumer_action_requirement",
        "expected_consumer_work_queue_assignment",
        "expected_consumer_processing_plan",
        "expected_consumer_operator_requirement",
        "expected_consumer_assignment_lane",
        "expected_consumer_service_tier",
        "expected_consumer_sla_class",
        "expected_consumer_response_window",
        "expected_consumer_timing_posture",
        "expected_consumer_scheduling_commitment",
        "expected_consumer_execution_readiness",
        "expected_consumer_dispatch_readiness",
        "expected_consumer_dispatch_authority",
    ),
    [
        pytest.param(
            "GO",
            "low",
            "none",
            "normal",
            "standard_channel",
            "standard_route",
            "none",
            "observe",
            "no_action",
            "observation_queue",
            "observe_only",
            "none",
            "self_service_lane",
            "self_service",
            "deferred",
            "backlog_window",
            "later",
            "backlog_commitment",
            "deferred_readiness",
            "parked",
            "withhold",
            id="go",
        ),
        pytest.param(
            "PAUSE",
            "medium",
            "notify",
            "elevated",
            "priority_channel",
            "priority_route",
            "follow_up",
            "engage",
            "action_required",
            "action_queue",
            "process_action",
            "operator_required",
            "operator_lane",
            "operator_managed",
            "standard",
            "standard_window",
            "scheduled",
            "scheduled_commitment",
            "planned_readiness",
            "prepared",
            "pre_authorize",
            id="pause",
        ),
        pytest.param(
            "REVIEW",
            "high",
            "escalate",
            "urgent",
            "escalation_channel",
            "escalation_route",
            "escalation_follow_up",
            "escalate",
            "escalation_required",
            "escalation_queue",
            "process_escalation",
            "senior_operator_required",
            "senior_operator_lane",
            "senior_managed",
            "priority",
            "priority_window",
            "immediate",
            "immediate_commitment",
            "ready_now",
            "dispatch_ready",
            "authorize",
            id="review",
        ),
    ],
)
def test_consumer_dispatch_authority_from_readiness_matches_dispatch_readiness(
    decision: RecommendationValue,
    expected_attention_level: str,
    expected_notification_requirement: str,
    expected_response_priority: str,
    expected_response_channel: str,
    expected_response_route: str,
    expected_followup_requirement: str,
    expected_consumer_decision_posture: str,
    expected_consumer_action_requirement: str,
    expected_consumer_work_queue_assignment: str,
    expected_consumer_processing_plan: str,
    expected_consumer_operator_requirement: str,
    expected_consumer_assignment_lane: str,
    expected_consumer_service_tier: str,
    expected_consumer_sla_class: str,
    expected_consumer_response_window: str,
    expected_consumer_timing_posture: str,
    expected_consumer_scheduling_commitment: str,
    expected_consumer_execution_readiness: str,
    expected_consumer_dispatch_readiness: str,
    expected_consumer_dispatch_authority: str,
) -> None:
    expected_classification = {
        "GO": "ready",
        "PAUSE": "hold",
        "REVIEW": "needs_review",
    }[decision]
    expected_handling_directive = {
        "ready": "deliver",
        "hold": "defer",
        "needs_review": "route_for_review",
    }[expected_classification]
    expected_action_label = {
        "deliver": "dispatch",
        "defer": "wait",
        "route_for_review": "review_queue",
    }[expected_handling_directive]
    expected_dispatch_intent = {
        "dispatch": "send",
        "wait": "park",
        "review_queue": "review",
    }[expected_action_label]
    expected_dispatch_mode = {
        "send": "active",
        "park": "queued",
        "review": "review_pending",
    }[expected_dispatch_intent]
    expected_release_gate = {
        "active": "open",
        "queued": "deferred",
        "review_pending": "blocked_for_review",
    }[expected_dispatch_mode]
    expected_progress_state = {
        "open": "in_progress",
        "deferred": "pending",
        "blocked_for_review": "review_hold",
    }[expected_release_gate]
    expected_progress_signal = {
        "in_progress": "advance",
        "pending": "await",
        "review_hold": "review_wait",
    }[expected_progress_state]
    expected_progress_outcome = {
        "advance": "moving",
        "await": "standing_by",
        "review_wait": "awaiting_review",
    }[expected_progress_signal]
    expected_intervention_requirement = {
        "moving": "none",
        "standing_by": "monitor",
        "awaiting_review": "review_required",
    }[expected_progress_outcome]
    attention_level_by_intervention_requirement = {
        "none": "low",
        "monitor": "medium",
        "review_required": "high",
    }
    notification_requirement_by_attention_level = {
        "low": "none",
        "medium": "notify",
        "high": "escalate",
    }
    response_priority_by_notification_requirement = {
        "none": "normal",
        "notify": "elevated",
        "escalate": "urgent",
    }
    response_channel_by_priority = {
        "normal": "standard_channel",
        "elevated": "priority_channel",
        "urgent": "escalation_channel",
    }
    followup_requirement_by_route = {
        "standard_route": "none",
        "priority_route": "follow_up",
        "escalation_route": "escalation_follow_up",
    }
    posture_by_followup_requirement = {
        "none": "observe",
        "follow_up": "engage",
        "escalation_follow_up": "escalate",
    }
    action_requirement_by_posture = {
        "observe": "no_action",
        "engage": "action_required",
        "escalate": "escalation_required",
    }
    queue_assignment_by_action_requirement = {
        "no_action": "observation_queue",
        "action_required": "action_queue",
        "escalation_required": "escalation_queue",
    }
    processing_plan_by_queue_assignment = {
        "observation_queue": "observe_only",
        "action_queue": "process_action",
        "escalation_queue": "process_escalation",
    }
    operator_requirement_by_processing_plan = {
        "observe_only": "none",
        "process_action": "operator_required",
        "process_escalation": "senior_operator_required",
    }
    assignment_lane_by_operator_requirement = {
        "none": "self_service_lane",
        "operator_required": "operator_lane",
        "senior_operator_required": "senior_operator_lane",
    }
    service_tier_by_assignment_lane = {
        "self_service_lane": "self_service",
        "operator_lane": "operator_managed",
        "senior_operator_lane": "senior_managed",
    }
    sla_class_by_service_tier = {
        "self_service": "deferred",
        "operator_managed": "standard",
        "senior_managed": "priority",
    }
    response_window_by_sla_class = {
        "deferred": "backlog_window",
        "standard": "standard_window",
        "priority": "priority_window",
    }
    timing_posture_by_response_window = {
        "backlog_window": "later",
        "standard_window": "scheduled",
        "priority_window": "immediate",
    }
    scheduling_commitment_by_timing_posture = {
        "later": "backlog_commitment",
        "scheduled": "scheduled_commitment",
        "immediate": "immediate_commitment",
    }
    execution_readiness_by_scheduling_commitment = {
        "backlog_commitment": "deferred_readiness",
        "scheduled_commitment": "planned_readiness",
        "immediate_commitment": "ready_now",
    }
    dispatch_readiness_by_execution_readiness = {
        "deferred_readiness": "parked",
        "planned_readiness": "prepared",
        "ready_now": "dispatch_ready",
    }
    dispatch_authority_by_readiness = {
        "parked": "withhold",
        "prepared": "pre_authorize",
        "dispatch_ready": "authorize",
    }
    assert (
        attention_level_by_intervention_requirement[expected_intervention_requirement]
        == expected_attention_level
    )
    assert (
        notification_requirement_by_attention_level[expected_attention_level]
        == expected_notification_requirement
    )
    assert (
        response_priority_by_notification_requirement[expected_notification_requirement]
        == expected_response_priority
    )
    assert response_channel_by_priority[expected_response_priority] == expected_response_channel
    assert followup_requirement_by_route[expected_response_route] == expected_followup_requirement
    assert (
        posture_by_followup_requirement[expected_followup_requirement]
        == expected_consumer_decision_posture
    )
    assert (
        action_requirement_by_posture[expected_consumer_decision_posture]
        == expected_consumer_action_requirement
    )
    assert (
        queue_assignment_by_action_requirement[expected_consumer_action_requirement]
        == expected_consumer_work_queue_assignment
    )
    assert (
        processing_plan_by_queue_assignment[expected_consumer_work_queue_assignment]
        == expected_consumer_processing_plan
    )
    assert (
        operator_requirement_by_processing_plan[expected_consumer_processing_plan]
        == expected_consumer_operator_requirement
    )
    assert (
        assignment_lane_by_operator_requirement[expected_consumer_operator_requirement]
        == expected_consumer_assignment_lane
    )
    assert (
        service_tier_by_assignment_lane[expected_consumer_assignment_lane]
        == expected_consumer_service_tier
    )
    assert sla_class_by_service_tier[expected_consumer_service_tier] == expected_consumer_sla_class
    assert (
        response_window_by_sla_class[expected_consumer_sla_class]
        == expected_consumer_response_window
    )
    assert (
        timing_posture_by_response_window[expected_consumer_response_window]
        == expected_consumer_timing_posture
    )
    assert (
        scheduling_commitment_by_timing_posture[expected_consumer_timing_posture]
        == expected_consumer_scheduling_commitment
    )
    assert (
        execution_readiness_by_scheduling_commitment[expected_consumer_scheduling_commitment]
        == expected_consumer_execution_readiness
    )
    assert (
        dispatch_readiness_by_execution_readiness[expected_consumer_execution_readiness]
        == expected_consumer_dispatch_readiness
    )
    assert (
        dispatch_authority_by_readiness[expected_consumer_dispatch_readiness]
        == expected_consumer_dispatch_authority
    )
    consumer_dispatch_readiness = {
        "projected_activation_decision": {"recommendation": decision},
        "approval_record": {
            "human_approval_status": {
                "status": {
                    "GO": "approved",
                    "PAUSE": "pending",
                    "REVIEW": "withheld",
                }[decision]
            }
        },
        "receiver_readiness_classification": expected_classification,
        "receiver_handling_directive": expected_handling_directive,
        "receiver_action_label": expected_action_label,
        "receiver_dispatch_intent": expected_dispatch_intent,
        "receiver_dispatch_mode": expected_dispatch_mode,
        "receiver_release_gate": expected_release_gate,
        "receiver_progress_state": expected_progress_state,
        "receiver_progress_signal": expected_progress_signal,
        "receiver_progress_outcome": expected_progress_outcome,
        "receiver_intervention_requirement": expected_intervention_requirement,
        "receiver_attention_level": expected_attention_level,
        "receiver_notification_requirement": expected_notification_requirement,
        "receiver_response_priority": expected_response_priority,
        "receiver_response_channel": expected_response_channel,
        "receiver_response_route": expected_response_route,
        "receiver_followup_requirement": expected_followup_requirement,
        "consumer_decision_posture": expected_consumer_decision_posture,
        "consumer_action_requirement": expected_consumer_action_requirement,
        "consumer_work_queue_assignment": expected_consumer_work_queue_assignment,
        "consumer_processing_plan": expected_consumer_processing_plan,
        "consumer_operator_requirement": expected_consumer_operator_requirement,
        "consumer_assignment_lane": expected_consumer_assignment_lane,
        "consumer_service_tier": expected_consumer_service_tier,
        "consumer_sla_class": expected_consumer_sla_class,
        "consumer_response_window": expected_consumer_response_window,
        "consumer_timing_posture": expected_consumer_timing_posture,
        "consumer_scheduling_commitment": expected_consumer_scheduling_commitment,
        "consumer_execution_readiness": expected_consumer_execution_readiness,
        "consumer_dispatch_readiness": expected_consumer_dispatch_readiness,
        "related_project_id": "project_consumer_dispatch_authority_1",
        "related_activation_decision_id": "activation_decision_consumer_dispatch_authority_1",
        "related_packet_id": "packet_consumer_dispatch_authority_1",
        "related_queue_item_id": "queue_consumer_dispatch_authority_1",
    }

    consumer_dispatch_authority = build_consumer_dispatch_authority_from_readiness(
        consumer_dispatch_readiness=consumer_dispatch_readiness
    )

    assert (
        consumer_dispatch_authority["projected_activation_decision"]
        == consumer_dispatch_readiness["projected_activation_decision"]
    )
    assert consumer_dispatch_authority["approval_record"] == consumer_dispatch_readiness[
        "approval_record"
    ]
    assert (
        consumer_dispatch_authority["receiver_readiness_classification"]
        == consumer_dispatch_readiness["receiver_readiness_classification"]
    )
    assert (
        consumer_dispatch_authority["receiver_handling_directive"]
        == consumer_dispatch_readiness["receiver_handling_directive"]
    )
    assert (
        consumer_dispatch_authority["receiver_action_label"]
        == consumer_dispatch_readiness["receiver_action_label"]
    )
    assert (
        consumer_dispatch_authority["receiver_dispatch_intent"]
        == consumer_dispatch_readiness["receiver_dispatch_intent"]
    )
    assert (
        consumer_dispatch_authority["receiver_dispatch_mode"]
        == consumer_dispatch_readiness["receiver_dispatch_mode"]
    )
    assert (
        consumer_dispatch_authority["receiver_release_gate"]
        == consumer_dispatch_readiness["receiver_release_gate"]
    )
    assert (
        consumer_dispatch_authority["receiver_progress_state"]
        == consumer_dispatch_readiness["receiver_progress_state"]
    )
    assert (
        consumer_dispatch_authority["receiver_progress_signal"]
        == consumer_dispatch_readiness["receiver_progress_signal"]
    )
    assert (
        consumer_dispatch_authority["receiver_progress_outcome"]
        == consumer_dispatch_readiness["receiver_progress_outcome"]
    )
    assert (
        consumer_dispatch_authority["receiver_intervention_requirement"]
        == consumer_dispatch_readiness["receiver_intervention_requirement"]
    )
    assert (
        consumer_dispatch_authority["receiver_attention_level"]
        == consumer_dispatch_readiness["receiver_attention_level"]
    )
    assert (
        consumer_dispatch_authority["receiver_notification_requirement"]
        == consumer_dispatch_readiness["receiver_notification_requirement"]
    )
    assert (
        consumer_dispatch_authority["receiver_response_priority"]
        == consumer_dispatch_readiness["receiver_response_priority"]
    )
    assert (
        consumer_dispatch_authority["receiver_response_channel"]
        == consumer_dispatch_readiness["receiver_response_channel"]
    )
    assert (
        consumer_dispatch_authority["receiver_response_route"]
        == consumer_dispatch_readiness["receiver_response_route"]
    )
    assert (
        consumer_dispatch_authority["receiver_followup_requirement"]
        == consumer_dispatch_readiness["receiver_followup_requirement"]
    )
    assert (
        consumer_dispatch_authority["consumer_decision_posture"]
        == consumer_dispatch_readiness["consumer_decision_posture"]
    )
    assert (
        consumer_dispatch_authority["consumer_action_requirement"]
        == consumer_dispatch_readiness["consumer_action_requirement"]
    )
    assert (
        consumer_dispatch_authority["consumer_work_queue_assignment"]
        == consumer_dispatch_readiness["consumer_work_queue_assignment"]
    )
    assert (
        consumer_dispatch_authority["consumer_processing_plan"]
        == consumer_dispatch_readiness["consumer_processing_plan"]
    )
    assert (
        consumer_dispatch_authority["consumer_operator_requirement"]
        == consumer_dispatch_readiness["consumer_operator_requirement"]
    )
    assert (
        consumer_dispatch_authority["consumer_assignment_lane"]
        == consumer_dispatch_readiness["consumer_assignment_lane"]
    )
    assert (
        consumer_dispatch_authority["consumer_service_tier"]
        == consumer_dispatch_readiness["consumer_service_tier"]
    )
    assert (
        consumer_dispatch_authority["consumer_sla_class"]
        == consumer_dispatch_readiness["consumer_sla_class"]
    )
    assert (
        consumer_dispatch_authority["consumer_response_window"]
        == consumer_dispatch_readiness["consumer_response_window"]
    )
    assert (
        consumer_dispatch_authority["consumer_timing_posture"]
        == consumer_dispatch_readiness["consumer_timing_posture"]
    )
    assert (
        consumer_dispatch_authority["consumer_scheduling_commitment"]
        == consumer_dispatch_readiness["consumer_scheduling_commitment"]
    )
    assert (
        consumer_dispatch_authority["consumer_execution_readiness"]
        == consumer_dispatch_readiness["consumer_execution_readiness"]
    )
    assert (
        consumer_dispatch_authority["consumer_dispatch_readiness"]
        == consumer_dispatch_readiness["consumer_dispatch_readiness"]
    )
    assert (
        consumer_dispatch_authority["related_project_id"]
        == consumer_dispatch_readiness["related_project_id"]
    )
    assert (
        consumer_dispatch_authority["related_activation_decision_id"]
        == consumer_dispatch_readiness["related_activation_decision_id"]
    )
    assert (
        consumer_dispatch_authority["related_packet_id"]
        == consumer_dispatch_readiness["related_packet_id"]
    )
    assert (
        consumer_dispatch_authority["related_queue_item_id"]
        == consumer_dispatch_readiness["related_queue_item_id"]
    )
    assert (
        consumer_dispatch_authority["consumer_dispatch_authority"]
        == expected_consumer_dispatch_authority
    )


@pytest.mark.parametrize(
    (
        "decision",
        "expected_attention_level",
        "expected_notification_requirement",
        "expected_response_priority",
        "expected_response_channel",
        "expected_response_route",
        "expected_followup_requirement",
        "expected_consumer_decision_posture",
        "expected_consumer_action_requirement",
        "expected_consumer_work_queue_assignment",
        "expected_consumer_processing_plan",
        "expected_consumer_operator_requirement",
        "expected_consumer_assignment_lane",
        "expected_consumer_service_tier",
        "expected_consumer_sla_class",
        "expected_consumer_response_window",
        "expected_consumer_timing_posture",
        "expected_consumer_scheduling_commitment",
        "expected_consumer_execution_readiness",
        "expected_consumer_dispatch_readiness",
        "expected_consumer_dispatch_authority",
        "expected_consumer_dispatch_permission",
    ),
    [
        pytest.param(
            "GO",
            "low",
            "none",
            "normal",
            "standard_channel",
            "standard_route",
            "none",
            "observe",
            "no_action",
            "observation_queue",
            "observe_only",
            "none",
            "self_service_lane",
            "self_service",
            "deferred",
            "backlog_window",
            "later",
            "backlog_commitment",
            "deferred_readiness",
            "parked",
            "withhold",
            "not_permitted",
            id="go",
        ),
        pytest.param(
            "PAUSE",
            "medium",
            "notify",
            "elevated",
            "priority_channel",
            "priority_route",
            "follow_up",
            "engage",
            "action_required",
            "action_queue",
            "process_action",
            "operator_required",
            "operator_lane",
            "operator_managed",
            "standard",
            "standard_window",
            "scheduled",
            "scheduled_commitment",
            "planned_readiness",
            "prepared",
            "pre_authorize",
            "conditionally_permitted",
            id="pause",
        ),
        pytest.param(
            "REVIEW",
            "high",
            "escalate",
            "urgent",
            "escalation_channel",
            "escalation_route",
            "escalation_follow_up",
            "escalate",
            "escalation_required",
            "escalation_queue",
            "process_escalation",
            "senior_operator_required",
            "senior_operator_lane",
            "senior_managed",
            "priority",
            "priority_window",
            "immediate",
            "immediate_commitment",
            "ready_now",
            "dispatch_ready",
            "authorize",
            "permitted",
            id="review",
        ),
    ],
)
def test_consumer_dispatch_permission_from_authority_matches_dispatch_authority(
    decision: RecommendationValue,
    expected_attention_level: str,
    expected_notification_requirement: str,
    expected_response_priority: str,
    expected_response_channel: str,
    expected_response_route: str,
    expected_followup_requirement: str,
    expected_consumer_decision_posture: str,
    expected_consumer_action_requirement: str,
    expected_consumer_work_queue_assignment: str,
    expected_consumer_processing_plan: str,
    expected_consumer_operator_requirement: str,
    expected_consumer_assignment_lane: str,
    expected_consumer_service_tier: str,
    expected_consumer_sla_class: str,
    expected_consumer_response_window: str,
    expected_consumer_timing_posture: str,
    expected_consumer_scheduling_commitment: str,
    expected_consumer_execution_readiness: str,
    expected_consumer_dispatch_readiness: str,
    expected_consumer_dispatch_authority: str,
    expected_consumer_dispatch_permission: str,
) -> None:
    expected_classification = {
        "GO": "ready",
        "PAUSE": "hold",
        "REVIEW": "needs_review",
    }[decision]
    expected_handling_directive = {
        "ready": "deliver",
        "hold": "defer",
        "needs_review": "route_for_review",
    }[expected_classification]
    expected_action_label = {
        "deliver": "dispatch",
        "defer": "wait",
        "route_for_review": "review_queue",
    }[expected_handling_directive]
    expected_dispatch_intent = {
        "dispatch": "send",
        "wait": "park",
        "review_queue": "review",
    }[expected_action_label]
    expected_dispatch_mode = {
        "send": "active",
        "park": "queued",
        "review": "review_pending",
    }[expected_dispatch_intent]
    expected_release_gate = {
        "active": "open",
        "queued": "deferred",
        "review_pending": "blocked_for_review",
    }[expected_dispatch_mode]
    expected_progress_state = {
        "open": "in_progress",
        "deferred": "pending",
        "blocked_for_review": "review_hold",
    }[expected_release_gate]
    expected_progress_signal = {
        "in_progress": "advance",
        "pending": "await",
        "review_hold": "review_wait",
    }[expected_progress_state]
    expected_progress_outcome = {
        "advance": "moving",
        "await": "standing_by",
        "review_wait": "awaiting_review",
    }[expected_progress_signal]
    expected_intervention_requirement = {
        "moving": "none",
        "standing_by": "monitor",
        "awaiting_review": "review_required",
    }[expected_progress_outcome]
    attention_level_by_intervention_requirement = {
        "none": "low",
        "monitor": "medium",
        "review_required": "high",
    }
    notification_requirement_by_attention_level = {
        "low": "none",
        "medium": "notify",
        "high": "escalate",
    }
    response_priority_by_notification_requirement = {
        "none": "normal",
        "notify": "elevated",
        "escalate": "urgent",
    }
    response_channel_by_priority = {
        "normal": "standard_channel",
        "elevated": "priority_channel",
        "urgent": "escalation_channel",
    }
    followup_requirement_by_route = {
        "standard_route": "none",
        "priority_route": "follow_up",
        "escalation_route": "escalation_follow_up",
    }
    posture_by_followup_requirement = {
        "none": "observe",
        "follow_up": "engage",
        "escalation_follow_up": "escalate",
    }
    action_requirement_by_posture = {
        "observe": "no_action",
        "engage": "action_required",
        "escalate": "escalation_required",
    }
    queue_assignment_by_action_requirement = {
        "no_action": "observation_queue",
        "action_required": "action_queue",
        "escalation_required": "escalation_queue",
    }
    processing_plan_by_queue_assignment = {
        "observation_queue": "observe_only",
        "action_queue": "process_action",
        "escalation_queue": "process_escalation",
    }
    operator_requirement_by_processing_plan = {
        "observe_only": "none",
        "process_action": "operator_required",
        "process_escalation": "senior_operator_required",
    }
    assignment_lane_by_operator_requirement = {
        "none": "self_service_lane",
        "operator_required": "operator_lane",
        "senior_operator_required": "senior_operator_lane",
    }
    service_tier_by_assignment_lane = {
        "self_service_lane": "self_service",
        "operator_lane": "operator_managed",
        "senior_operator_lane": "senior_managed",
    }
    sla_class_by_service_tier = {
        "self_service": "deferred",
        "operator_managed": "standard",
        "senior_managed": "priority",
    }
    response_window_by_sla_class = {
        "deferred": "backlog_window",
        "standard": "standard_window",
        "priority": "priority_window",
    }
    timing_posture_by_response_window = {
        "backlog_window": "later",
        "standard_window": "scheduled",
        "priority_window": "immediate",
    }
    scheduling_commitment_by_timing_posture = {
        "later": "backlog_commitment",
        "scheduled": "scheduled_commitment",
        "immediate": "immediate_commitment",
    }
    execution_readiness_by_scheduling_commitment = {
        "backlog_commitment": "deferred_readiness",
        "scheduled_commitment": "planned_readiness",
        "immediate_commitment": "ready_now",
    }
    dispatch_readiness_by_execution_readiness = {
        "deferred_readiness": "parked",
        "planned_readiness": "prepared",
        "ready_now": "dispatch_ready",
    }
    dispatch_authority_by_readiness = {
        "parked": "withhold",
        "prepared": "pre_authorize",
        "dispatch_ready": "authorize",
    }
    dispatch_permission_by_authority = {
        "withhold": "not_permitted",
        "pre_authorize": "conditionally_permitted",
        "authorize": "permitted",
    }
    assert (
        attention_level_by_intervention_requirement[expected_intervention_requirement]
        == expected_attention_level
    )
    assert (
        notification_requirement_by_attention_level[expected_attention_level]
        == expected_notification_requirement
    )
    assert (
        response_priority_by_notification_requirement[expected_notification_requirement]
        == expected_response_priority
    )
    assert response_channel_by_priority[expected_response_priority] == expected_response_channel
    assert followup_requirement_by_route[expected_response_route] == expected_followup_requirement
    assert (
        posture_by_followup_requirement[expected_followup_requirement]
        == expected_consumer_decision_posture
    )
    assert (
        action_requirement_by_posture[expected_consumer_decision_posture]
        == expected_consumer_action_requirement
    )
    assert (
        queue_assignment_by_action_requirement[expected_consumer_action_requirement]
        == expected_consumer_work_queue_assignment
    )
    assert (
        processing_plan_by_queue_assignment[expected_consumer_work_queue_assignment]
        == expected_consumer_processing_plan
    )
    assert (
        operator_requirement_by_processing_plan[expected_consumer_processing_plan]
        == expected_consumer_operator_requirement
    )
    assert (
        assignment_lane_by_operator_requirement[expected_consumer_operator_requirement]
        == expected_consumer_assignment_lane
    )
    assert (
        service_tier_by_assignment_lane[expected_consumer_assignment_lane]
        == expected_consumer_service_tier
    )
    assert sla_class_by_service_tier[expected_consumer_service_tier] == expected_consumer_sla_class
    assert (
        response_window_by_sla_class[expected_consumer_sla_class]
        == expected_consumer_response_window
    )
    assert (
        timing_posture_by_response_window[expected_consumer_response_window]
        == expected_consumer_timing_posture
    )
    assert (
        scheduling_commitment_by_timing_posture[expected_consumer_timing_posture]
        == expected_consumer_scheduling_commitment
    )
    assert (
        execution_readiness_by_scheduling_commitment[expected_consumer_scheduling_commitment]
        == expected_consumer_execution_readiness
    )
    assert (
        dispatch_readiness_by_execution_readiness[expected_consumer_execution_readiness]
        == expected_consumer_dispatch_readiness
    )
    assert (
        dispatch_authority_by_readiness[expected_consumer_dispatch_readiness]
        == expected_consumer_dispatch_authority
    )
    assert (
        dispatch_permission_by_authority[expected_consumer_dispatch_authority]
        == expected_consumer_dispatch_permission
    )
    consumer_dispatch_authority = {
        "projected_activation_decision": {"recommendation": decision},
        "approval_record": {
            "human_approval_status": {
                "status": {
                    "GO": "approved",
                    "PAUSE": "pending",
                    "REVIEW": "withheld",
                }[decision]
            }
        },
        "receiver_readiness_classification": expected_classification,
        "receiver_handling_directive": expected_handling_directive,
        "receiver_action_label": expected_action_label,
        "receiver_dispatch_intent": expected_dispatch_intent,
        "receiver_dispatch_mode": expected_dispatch_mode,
        "receiver_release_gate": expected_release_gate,
        "receiver_progress_state": expected_progress_state,
        "receiver_progress_signal": expected_progress_signal,
        "receiver_progress_outcome": expected_progress_outcome,
        "receiver_intervention_requirement": expected_intervention_requirement,
        "receiver_attention_level": expected_attention_level,
        "receiver_notification_requirement": expected_notification_requirement,
        "receiver_response_priority": expected_response_priority,
        "receiver_response_channel": expected_response_channel,
        "receiver_response_route": expected_response_route,
        "receiver_followup_requirement": expected_followup_requirement,
        "consumer_decision_posture": expected_consumer_decision_posture,
        "consumer_action_requirement": expected_consumer_action_requirement,
        "consumer_work_queue_assignment": expected_consumer_work_queue_assignment,
        "consumer_processing_plan": expected_consumer_processing_plan,
        "consumer_operator_requirement": expected_consumer_operator_requirement,
        "consumer_assignment_lane": expected_consumer_assignment_lane,
        "consumer_service_tier": expected_consumer_service_tier,
        "consumer_sla_class": expected_consumer_sla_class,
        "consumer_response_window": expected_consumer_response_window,
        "consumer_timing_posture": expected_consumer_timing_posture,
        "consumer_scheduling_commitment": expected_consumer_scheduling_commitment,
        "consumer_execution_readiness": expected_consumer_execution_readiness,
        "consumer_dispatch_readiness": expected_consumer_dispatch_readiness,
        "consumer_dispatch_authority": expected_consumer_dispatch_authority,
        "related_project_id": "project_consumer_dispatch_permission_1",
        "related_activation_decision_id": "activation_decision_consumer_dispatch_permission_1",
        "related_packet_id": "packet_consumer_dispatch_permission_1",
        "related_queue_item_id": "queue_consumer_dispatch_permission_1",
    }

    consumer_dispatch_permission = build_consumer_dispatch_permission_from_authority(
        consumer_dispatch_authority=consumer_dispatch_authority
    )

    assert (
        consumer_dispatch_permission["projected_activation_decision"]
        == consumer_dispatch_authority["projected_activation_decision"]
    )
    assert consumer_dispatch_permission["approval_record"] == consumer_dispatch_authority[
        "approval_record"
    ]
    assert (
        consumer_dispatch_permission["receiver_readiness_classification"]
        == consumer_dispatch_authority["receiver_readiness_classification"]
    )
    assert (
        consumer_dispatch_permission["receiver_handling_directive"]
        == consumer_dispatch_authority["receiver_handling_directive"]
    )
    assert (
        consumer_dispatch_permission["receiver_action_label"]
        == consumer_dispatch_authority["receiver_action_label"]
    )
    assert (
        consumer_dispatch_permission["receiver_dispatch_intent"]
        == consumer_dispatch_authority["receiver_dispatch_intent"]
    )
    assert (
        consumer_dispatch_permission["receiver_dispatch_mode"]
        == consumer_dispatch_authority["receiver_dispatch_mode"]
    )
    assert (
        consumer_dispatch_permission["receiver_release_gate"]
        == consumer_dispatch_authority["receiver_release_gate"]
    )
    assert (
        consumer_dispatch_permission["receiver_progress_state"]
        == consumer_dispatch_authority["receiver_progress_state"]
    )
    assert (
        consumer_dispatch_permission["receiver_progress_signal"]
        == consumer_dispatch_authority["receiver_progress_signal"]
    )
    assert (
        consumer_dispatch_permission["receiver_progress_outcome"]
        == consumer_dispatch_authority["receiver_progress_outcome"]
    )
    assert (
        consumer_dispatch_permission["receiver_intervention_requirement"]
        == consumer_dispatch_authority["receiver_intervention_requirement"]
    )
    assert (
        consumer_dispatch_permission["receiver_attention_level"]
        == consumer_dispatch_authority["receiver_attention_level"]
    )
    assert (
        consumer_dispatch_permission["receiver_notification_requirement"]
        == consumer_dispatch_authority["receiver_notification_requirement"]
    )
    assert (
        consumer_dispatch_permission["receiver_response_priority"]
        == consumer_dispatch_authority["receiver_response_priority"]
    )
    assert (
        consumer_dispatch_permission["receiver_response_channel"]
        == consumer_dispatch_authority["receiver_response_channel"]
    )
    assert (
        consumer_dispatch_permission["receiver_response_route"]
        == consumer_dispatch_authority["receiver_response_route"]
    )
    assert (
        consumer_dispatch_permission["receiver_followup_requirement"]
        == consumer_dispatch_authority["receiver_followup_requirement"]
    )
    assert (
        consumer_dispatch_permission["consumer_decision_posture"]
        == consumer_dispatch_authority["consumer_decision_posture"]
    )
    assert (
        consumer_dispatch_permission["consumer_action_requirement"]
        == consumer_dispatch_authority["consumer_action_requirement"]
    )
    assert (
        consumer_dispatch_permission["consumer_work_queue_assignment"]
        == consumer_dispatch_authority["consumer_work_queue_assignment"]
    )
    assert (
        consumer_dispatch_permission["consumer_processing_plan"]
        == consumer_dispatch_authority["consumer_processing_plan"]
    )
    assert (
        consumer_dispatch_permission["consumer_operator_requirement"]
        == consumer_dispatch_authority["consumer_operator_requirement"]
    )
    assert (
        consumer_dispatch_permission["consumer_assignment_lane"]
        == consumer_dispatch_authority["consumer_assignment_lane"]
    )
    assert (
        consumer_dispatch_permission["consumer_service_tier"]
        == consumer_dispatch_authority["consumer_service_tier"]
    )
    assert (
        consumer_dispatch_permission["consumer_sla_class"]
        == consumer_dispatch_authority["consumer_sla_class"]
    )
    assert (
        consumer_dispatch_permission["consumer_response_window"]
        == consumer_dispatch_authority["consumer_response_window"]
    )
    assert (
        consumer_dispatch_permission["consumer_timing_posture"]
        == consumer_dispatch_authority["consumer_timing_posture"]
    )
    assert (
        consumer_dispatch_permission["consumer_scheduling_commitment"]
        == consumer_dispatch_authority["consumer_scheduling_commitment"]
    )
    assert (
        consumer_dispatch_permission["consumer_execution_readiness"]
        == consumer_dispatch_authority["consumer_execution_readiness"]
    )
    assert (
        consumer_dispatch_permission["consumer_dispatch_readiness"]
        == consumer_dispatch_authority["consumer_dispatch_readiness"]
    )
    assert (
        consumer_dispatch_permission["consumer_dispatch_authority"]
        == consumer_dispatch_authority["consumer_dispatch_authority"]
    )
    assert (
        consumer_dispatch_permission["related_project_id"]
        == consumer_dispatch_authority["related_project_id"]
    )
    assert (
        consumer_dispatch_permission["related_activation_decision_id"]
        == consumer_dispatch_authority["related_activation_decision_id"]
    )
    assert (
        consumer_dispatch_permission["related_packet_id"]
        == consumer_dispatch_authority["related_packet_id"]
    )
    assert (
        consumer_dispatch_permission["related_queue_item_id"]
        == consumer_dispatch_authority["related_queue_item_id"]
    )
    assert (
        consumer_dispatch_permission["consumer_dispatch_permission"]
        == expected_consumer_dispatch_permission
    )


@pytest.mark.parametrize(
    ("decision", "expected_consumer_dispatch_permission", "expected_consumer_dispatch_clearance"),
    [
        pytest.param("GO", "not_permitted", "blocked", id="go"),
        pytest.param("PAUSE", "conditionally_permitted", "gated", id="pause"),
        pytest.param("REVIEW", "permitted", "clear", id="review"),
    ],
)
def test_consumer_dispatch_clearance_from_permission_matches_dispatch_permission(
    decision: RecommendationValue,
    expected_consumer_dispatch_permission: str,
    expected_consumer_dispatch_clearance: str,
) -> None:
    expected_classification = {
        "GO": "ready",
        "PAUSE": "hold",
        "REVIEW": "needs_review",
    }[decision]
    expected_handling_directive = {
        "ready": "deliver",
        "hold": "defer",
        "needs_review": "route_for_review",
    }[expected_classification]
    expected_action_label = {
        "deliver": "dispatch",
        "defer": "wait",
        "route_for_review": "review_queue",
    }[expected_handling_directive]
    expected_dispatch_intent = {
        "dispatch": "send",
        "wait": "park",
        "review_queue": "review",
    }[expected_action_label]
    expected_dispatch_mode = {
        "send": "active",
        "park": "queued",
        "review": "review_pending",
    }[expected_dispatch_intent]
    expected_release_gate = {
        "active": "open",
        "queued": "deferred",
        "review_pending": "blocked_for_review",
    }[expected_dispatch_mode]
    expected_progress_state = {
        "open": "in_progress",
        "deferred": "pending",
        "blocked_for_review": "review_hold",
    }[expected_release_gate]
    expected_progress_signal = {
        "in_progress": "advance",
        "pending": "await",
        "review_hold": "review_wait",
    }[expected_progress_state]
    expected_progress_outcome = {
        "advance": "moving",
        "await": "standing_by",
        "review_wait": "awaiting_review",
    }[expected_progress_signal]
    expected_intervention_requirement = {
        "moving": "none",
        "standing_by": "monitor",
        "awaiting_review": "review_required",
    }[expected_progress_outcome]
    expected_attention_level = {
        "none": "low",
        "monitor": "medium",
        "review_required": "high",
    }[expected_intervention_requirement]
    expected_notification_requirement = {
        "low": "none",
        "medium": "notify",
        "high": "escalate",
    }[expected_attention_level]
    expected_response_priority = {
        "none": "normal",
        "notify": "elevated",
        "escalate": "urgent",
    }[expected_notification_requirement]
    expected_response_channel = {
        "normal": "standard_channel",
        "elevated": "priority_channel",
        "urgent": "escalation_channel",
    }[expected_response_priority]
    expected_response_route = {
        "standard_channel": "standard_route",
        "priority_channel": "priority_route",
        "escalation_channel": "escalation_route",
    }[expected_response_channel]
    expected_followup_requirement = {
        "standard_route": "none",
        "priority_route": "follow_up",
        "escalation_route": "escalation_follow_up",
    }[expected_response_route]
    expected_consumer_decision_posture = {
        "none": "observe",
        "follow_up": "engage",
        "escalation_follow_up": "escalate",
    }[expected_followup_requirement]
    expected_consumer_action_requirement = {
        "observe": "no_action",
        "engage": "action_required",
        "escalate": "escalation_required",
    }[expected_consumer_decision_posture]
    expected_consumer_work_queue_assignment = {
        "no_action": "observation_queue",
        "action_required": "action_queue",
        "escalation_required": "escalation_queue",
    }[expected_consumer_action_requirement]
    expected_consumer_processing_plan = {
        "observation_queue": "observe_only",
        "action_queue": "process_action",
        "escalation_queue": "process_escalation",
    }[expected_consumer_work_queue_assignment]
    expected_consumer_operator_requirement = {
        "observe_only": "none",
        "process_action": "operator_required",
        "process_escalation": "senior_operator_required",
    }[expected_consumer_processing_plan]
    expected_consumer_assignment_lane = {
        "none": "self_service_lane",
        "operator_required": "operator_lane",
        "senior_operator_required": "senior_operator_lane",
    }[expected_consumer_operator_requirement]
    expected_consumer_service_tier = {
        "self_service_lane": "self_service",
        "operator_lane": "operator_managed",
        "senior_operator_lane": "senior_managed",
    }[expected_consumer_assignment_lane]
    expected_consumer_sla_class = {
        "self_service": "deferred",
        "operator_managed": "standard",
        "senior_managed": "priority",
    }[expected_consumer_service_tier]
    expected_consumer_response_window = {
        "deferred": "backlog_window",
        "standard": "standard_window",
        "priority": "priority_window",
    }[expected_consumer_sla_class]
    expected_consumer_timing_posture = {
        "backlog_window": "later",
        "standard_window": "scheduled",
        "priority_window": "immediate",
    }[expected_consumer_response_window]
    expected_consumer_scheduling_commitment = {
        "later": "backlog_commitment",
        "scheduled": "scheduled_commitment",
        "immediate": "immediate_commitment",
    }[expected_consumer_timing_posture]
    expected_consumer_execution_readiness = {
        "backlog_commitment": "deferred_readiness",
        "scheduled_commitment": "planned_readiness",
        "immediate_commitment": "ready_now",
    }[expected_consumer_scheduling_commitment]
    expected_consumer_dispatch_readiness = {
        "deferred_readiness": "parked",
        "planned_readiness": "prepared",
        "ready_now": "dispatch_ready",
    }[expected_consumer_execution_readiness]
    expected_consumer_dispatch_authority = {
        "parked": "withhold",
        "prepared": "pre_authorize",
        "dispatch_ready": "authorize",
    }[expected_consumer_dispatch_readiness]
    assert (
        {
            "withhold": "not_permitted",
            "pre_authorize": "conditionally_permitted",
            "authorize": "permitted",
        }[expected_consumer_dispatch_authority]
        == expected_consumer_dispatch_permission
    )
    assert (
        {
            "not_permitted": "blocked",
            "conditionally_permitted": "gated",
            "permitted": "clear",
        }[expected_consumer_dispatch_permission]
        == expected_consumer_dispatch_clearance
    )

    consumer_dispatch_permission = {
        "projected_activation_decision": {"recommendation": decision},
        "approval_record": {
            "human_approval_status": {
                "status": {
                    "GO": "approved",
                    "PAUSE": "pending",
                    "REVIEW": "withheld",
                }[decision]
            }
        },
        "receiver_readiness_classification": expected_classification,
        "receiver_handling_directive": expected_handling_directive,
        "receiver_action_label": expected_action_label,
        "receiver_dispatch_intent": expected_dispatch_intent,
        "receiver_dispatch_mode": expected_dispatch_mode,
        "receiver_release_gate": expected_release_gate,
        "receiver_progress_state": expected_progress_state,
        "receiver_progress_signal": expected_progress_signal,
        "receiver_progress_outcome": expected_progress_outcome,
        "receiver_intervention_requirement": expected_intervention_requirement,
        "receiver_attention_level": expected_attention_level,
        "receiver_notification_requirement": expected_notification_requirement,
        "receiver_response_priority": expected_response_priority,
        "receiver_response_channel": expected_response_channel,
        "receiver_response_route": expected_response_route,
        "receiver_followup_requirement": expected_followup_requirement,
        "consumer_decision_posture": expected_consumer_decision_posture,
        "consumer_action_requirement": expected_consumer_action_requirement,
        "consumer_work_queue_assignment": expected_consumer_work_queue_assignment,
        "consumer_processing_plan": expected_consumer_processing_plan,
        "consumer_operator_requirement": expected_consumer_operator_requirement,
        "consumer_assignment_lane": expected_consumer_assignment_lane,
        "consumer_service_tier": expected_consumer_service_tier,
        "consumer_sla_class": expected_consumer_sla_class,
        "consumer_response_window": expected_consumer_response_window,
        "consumer_timing_posture": expected_consumer_timing_posture,
        "consumer_scheduling_commitment": expected_consumer_scheduling_commitment,
        "consumer_execution_readiness": expected_consumer_execution_readiness,
        "consumer_dispatch_readiness": expected_consumer_dispatch_readiness,
        "consumer_dispatch_authority": expected_consumer_dispatch_authority,
        "consumer_dispatch_permission": expected_consumer_dispatch_permission,
        "related_project_id": "project_consumer_dispatch_clearance_1",
        "related_activation_decision_id": "activation_decision_consumer_dispatch_clearance_1",
        "related_packet_id": "packet_consumer_dispatch_clearance_1",
        "related_queue_item_id": "queue_consumer_dispatch_clearance_1",
    }

    consumer_dispatch_clearance = build_consumer_dispatch_clearance_from_permission(
        consumer_dispatch_permission=consumer_dispatch_permission
    )

    passthrough_keys = [
        "projected_activation_decision",
        "approval_record",
        "receiver_readiness_classification",
        "receiver_handling_directive",
        "receiver_action_label",
        "receiver_dispatch_intent",
        "receiver_dispatch_mode",
        "receiver_release_gate",
        "receiver_progress_state",
        "receiver_progress_signal",
        "receiver_progress_outcome",
        "receiver_intervention_requirement",
        "receiver_attention_level",
        "receiver_notification_requirement",
        "receiver_response_priority",
        "receiver_response_channel",
        "receiver_response_route",
        "receiver_followup_requirement",
        "consumer_decision_posture",
        "consumer_action_requirement",
        "consumer_work_queue_assignment",
        "consumer_processing_plan",
        "consumer_operator_requirement",
        "consumer_assignment_lane",
        "consumer_service_tier",
        "consumer_sla_class",
        "consumer_response_window",
        "consumer_timing_posture",
        "consumer_scheduling_commitment",
        "consumer_execution_readiness",
        "consumer_dispatch_readiness",
        "consumer_dispatch_authority",
        "consumer_dispatch_permission",
        "related_project_id",
        "related_activation_decision_id",
        "related_packet_id",
        "related_queue_item_id",
    ]
    for key in passthrough_keys:
        assert consumer_dispatch_clearance[key] == consumer_dispatch_permission[key]
    assert (
        consumer_dispatch_clearance["consumer_dispatch_clearance"]
        == expected_consumer_dispatch_clearance
    )


@pytest.mark.parametrize(
    ("decision", "expected_consumer_dispatch_clearance", "expected_consumer_release_decision"),
    [
        pytest.param("GO", "blocked", "hold_release", id="go"),
        pytest.param("PAUSE", "gated", "conditional_release", id="pause"),
        pytest.param("REVIEW", "clear", "release", id="review"),
    ],
)
def test_consumer_release_decision_from_dispatch_clearance_matches_dispatch_clearance(
    decision: RecommendationValue,
    expected_consumer_dispatch_clearance: str,
    expected_consumer_release_decision: str,
) -> None:
    expected_classification = {
        "GO": "ready",
        "PAUSE": "hold",
        "REVIEW": "needs_review",
    }[decision]
    expected_handling_directive = {
        "ready": "deliver",
        "hold": "defer",
        "needs_review": "route_for_review",
    }[expected_classification]
    expected_action_label = {
        "deliver": "dispatch",
        "defer": "wait",
        "route_for_review": "review_queue",
    }[expected_handling_directive]
    expected_dispatch_intent = {
        "dispatch": "send",
        "wait": "park",
        "review_queue": "review",
    }[expected_action_label]
    expected_dispatch_mode = {
        "send": "active",
        "park": "queued",
        "review": "review_pending",
    }[expected_dispatch_intent]
    expected_release_gate = {
        "active": "open",
        "queued": "deferred",
        "review_pending": "blocked_for_review",
    }[expected_dispatch_mode]
    expected_progress_state = {
        "open": "in_progress",
        "deferred": "pending",
        "blocked_for_review": "review_hold",
    }[expected_release_gate]
    expected_progress_signal = {
        "in_progress": "advance",
        "pending": "await",
        "review_hold": "review_wait",
    }[expected_progress_state]
    expected_progress_outcome = {
        "advance": "moving",
        "await": "standing_by",
        "review_wait": "awaiting_review",
    }[expected_progress_signal]
    expected_intervention_requirement = {
        "moving": "none",
        "standing_by": "monitor",
        "awaiting_review": "review_required",
    }[expected_progress_outcome]
    expected_attention_level = {
        "none": "low",
        "monitor": "medium",
        "review_required": "high",
    }[expected_intervention_requirement]
    expected_notification_requirement = {
        "low": "none",
        "medium": "notify",
        "high": "escalate",
    }[expected_attention_level]
    expected_response_priority = {
        "none": "normal",
        "notify": "elevated",
        "escalate": "urgent",
    }[expected_notification_requirement]
    expected_response_channel = {
        "normal": "standard_channel",
        "elevated": "priority_channel",
        "urgent": "escalation_channel",
    }[expected_response_priority]
    expected_response_route = {
        "standard_channel": "standard_route",
        "priority_channel": "priority_route",
        "escalation_channel": "escalation_route",
    }[expected_response_channel]
    expected_followup_requirement = {
        "standard_route": "none",
        "priority_route": "follow_up",
        "escalation_route": "escalation_follow_up",
    }[expected_response_route]
    expected_consumer_decision_posture = {
        "none": "observe",
        "follow_up": "engage",
        "escalation_follow_up": "escalate",
    }[expected_followup_requirement]
    expected_consumer_action_requirement = {
        "observe": "no_action",
        "engage": "action_required",
        "escalate": "escalation_required",
    }[expected_consumer_decision_posture]
    expected_consumer_work_queue_assignment = {
        "no_action": "observation_queue",
        "action_required": "action_queue",
        "escalation_required": "escalation_queue",
    }[expected_consumer_action_requirement]
    expected_consumer_processing_plan = {
        "observation_queue": "observe_only",
        "action_queue": "process_action",
        "escalation_queue": "process_escalation",
    }[expected_consumer_work_queue_assignment]
    expected_consumer_operator_requirement = {
        "observe_only": "none",
        "process_action": "operator_required",
        "process_escalation": "senior_operator_required",
    }[expected_consumer_processing_plan]
    expected_consumer_assignment_lane = {
        "none": "self_service_lane",
        "operator_required": "operator_lane",
        "senior_operator_required": "senior_operator_lane",
    }[expected_consumer_operator_requirement]
    expected_consumer_service_tier = {
        "self_service_lane": "self_service",
        "operator_lane": "operator_managed",
        "senior_operator_lane": "senior_managed",
    }[expected_consumer_assignment_lane]
    expected_consumer_sla_class = {
        "self_service": "deferred",
        "operator_managed": "standard",
        "senior_managed": "priority",
    }[expected_consumer_service_tier]
    expected_consumer_response_window = {
        "deferred": "backlog_window",
        "standard": "standard_window",
        "priority": "priority_window",
    }[expected_consumer_sla_class]
    expected_consumer_timing_posture = {
        "backlog_window": "later",
        "standard_window": "scheduled",
        "priority_window": "immediate",
    }[expected_consumer_response_window]
    expected_consumer_scheduling_commitment = {
        "later": "backlog_commitment",
        "scheduled": "scheduled_commitment",
        "immediate": "immediate_commitment",
    }[expected_consumer_timing_posture]
    expected_consumer_execution_readiness = {
        "backlog_commitment": "deferred_readiness",
        "scheduled_commitment": "planned_readiness",
        "immediate_commitment": "ready_now",
    }[expected_consumer_scheduling_commitment]
    expected_consumer_dispatch_readiness = {
        "deferred_readiness": "parked",
        "planned_readiness": "prepared",
        "ready_now": "dispatch_ready",
    }[expected_consumer_execution_readiness]
    expected_consumer_dispatch_authority = {
        "parked": "withhold",
        "prepared": "pre_authorize",
        "dispatch_ready": "authorize",
    }[expected_consumer_dispatch_readiness]
    expected_consumer_dispatch_permission = {
        "withhold": "not_permitted",
        "pre_authorize": "conditionally_permitted",
        "authorize": "permitted",
    }[expected_consumer_dispatch_authority]
    assert (
        {
            "not_permitted": "blocked",
            "conditionally_permitted": "gated",
            "permitted": "clear",
        }[expected_consumer_dispatch_permission]
        == expected_consumer_dispatch_clearance
    )
    assert (
        {
            "blocked": "hold_release",
            "gated": "conditional_release",
            "clear": "release",
        }[expected_consumer_dispatch_clearance]
        == expected_consumer_release_decision
    )

    consumer_dispatch_clearance = {
        "projected_activation_decision": {"recommendation": decision},
        "approval_record": {
            "human_approval_status": {
                "status": {
                    "GO": "approved",
                    "PAUSE": "pending",
                    "REVIEW": "withheld",
                }[decision]
            }
        },
        "receiver_readiness_classification": expected_classification,
        "receiver_handling_directive": expected_handling_directive,
        "receiver_action_label": expected_action_label,
        "receiver_dispatch_intent": expected_dispatch_intent,
        "receiver_dispatch_mode": expected_dispatch_mode,
        "receiver_release_gate": expected_release_gate,
        "receiver_progress_state": expected_progress_state,
        "receiver_progress_signal": expected_progress_signal,
        "receiver_progress_outcome": expected_progress_outcome,
        "receiver_intervention_requirement": expected_intervention_requirement,
        "receiver_attention_level": expected_attention_level,
        "receiver_notification_requirement": expected_notification_requirement,
        "receiver_response_priority": expected_response_priority,
        "receiver_response_channel": expected_response_channel,
        "receiver_response_route": expected_response_route,
        "receiver_followup_requirement": expected_followup_requirement,
        "consumer_decision_posture": expected_consumer_decision_posture,
        "consumer_action_requirement": expected_consumer_action_requirement,
        "consumer_work_queue_assignment": expected_consumer_work_queue_assignment,
        "consumer_processing_plan": expected_consumer_processing_plan,
        "consumer_operator_requirement": expected_consumer_operator_requirement,
        "consumer_assignment_lane": expected_consumer_assignment_lane,
        "consumer_service_tier": expected_consumer_service_tier,
        "consumer_sla_class": expected_consumer_sla_class,
        "consumer_response_window": expected_consumer_response_window,
        "consumer_timing_posture": expected_consumer_timing_posture,
        "consumer_scheduling_commitment": expected_consumer_scheduling_commitment,
        "consumer_execution_readiness": expected_consumer_execution_readiness,
        "consumer_dispatch_readiness": expected_consumer_dispatch_readiness,
        "consumer_dispatch_authority": expected_consumer_dispatch_authority,
        "consumer_dispatch_permission": expected_consumer_dispatch_permission,
        "consumer_dispatch_clearance": expected_consumer_dispatch_clearance,
        "related_project_id": "project_consumer_release_decision_1",
        "related_activation_decision_id": "activation_decision_consumer_release_decision_1",
        "related_packet_id": "packet_consumer_release_decision_1",
        "related_queue_item_id": "queue_consumer_release_decision_1",
    }

    consumer_release_decision = build_consumer_release_decision_from_dispatch_clearance(
        consumer_dispatch_clearance=consumer_dispatch_clearance
    )

    passthrough_keys = [
        "projected_activation_decision",
        "approval_record",
        "receiver_readiness_classification",
        "receiver_handling_directive",
        "receiver_action_label",
        "receiver_dispatch_intent",
        "receiver_dispatch_mode",
        "receiver_release_gate",
        "receiver_progress_state",
        "receiver_progress_signal",
        "receiver_progress_outcome",
        "receiver_intervention_requirement",
        "receiver_attention_level",
        "receiver_notification_requirement",
        "receiver_response_priority",
        "receiver_response_channel",
        "receiver_response_route",
        "receiver_followup_requirement",
        "consumer_decision_posture",
        "consumer_action_requirement",
        "consumer_work_queue_assignment",
        "consumer_processing_plan",
        "consumer_operator_requirement",
        "consumer_assignment_lane",
        "consumer_service_tier",
        "consumer_sla_class",
        "consumer_response_window",
        "consumer_timing_posture",
        "consumer_scheduling_commitment",
        "consumer_execution_readiness",
        "consumer_dispatch_readiness",
        "consumer_dispatch_authority",
        "consumer_dispatch_permission",
        "consumer_dispatch_clearance",
        "related_project_id",
        "related_activation_decision_id",
        "related_packet_id",
        "related_queue_item_id",
    ]
    for key in passthrough_keys:
        assert consumer_release_decision[key] == consumer_dispatch_clearance[key]
    assert (
        consumer_release_decision["consumer_release_decision"]
        == expected_consumer_release_decision
    )


@pytest.mark.parametrize(
    (
        "decision",
        "expected_consumer_dispatch_clearance",
        "expected_consumer_release_decision",
        "expected_consumer_release_mode",
        "expected_consumer_release_execution_requirement",
    ),
    [
        pytest.param(
            "GO",
            "blocked",
            "hold_release",
            "hold_mode",
            "do_not_execute",
            id="go",
        ),
        pytest.param(
            "PAUSE",
            "gated",
            "conditional_release",
            "guarded_mode",
            "execute_with_guard",
            id="pause",
        ),
        pytest.param(
            "REVIEW",
            "clear",
            "release",
            "release_mode",
            "execute_release",
            id="review",
        ),
    ],
)
def test_consumer_release_execution_requirement_from_release_mode_matches_release_mode(
    decision: RecommendationValue,
    expected_consumer_dispatch_clearance: str,
    expected_consumer_release_decision: str,
    expected_consumer_release_mode: str,
    expected_consumer_release_execution_requirement: str,
) -> None:
    expected_classification = {
        "GO": "ready",
        "PAUSE": "hold",
        "REVIEW": "needs_review",
    }[decision]
    expected_handling_directive = {
        "ready": "deliver",
        "hold": "defer",
        "needs_review": "route_for_review",
    }[expected_classification]
    expected_action_label = {
        "deliver": "dispatch",
        "defer": "wait",
        "route_for_review": "review_queue",
    }[expected_handling_directive]
    expected_dispatch_intent = {
        "dispatch": "send",
        "wait": "park",
        "review_queue": "review",
    }[expected_action_label]
    expected_dispatch_mode = {
        "send": "active",
        "park": "queued",
        "review": "review_pending",
    }[expected_dispatch_intent]
    expected_release_gate = {
        "active": "open",
        "queued": "deferred",
        "review_pending": "blocked_for_review",
    }[expected_dispatch_mode]
    expected_progress_state = {
        "open": "in_progress",
        "deferred": "pending",
        "blocked_for_review": "review_hold",
    }[expected_release_gate]
    expected_progress_signal = {
        "in_progress": "advance",
        "pending": "await",
        "review_hold": "review_wait",
    }[expected_progress_state]
    expected_progress_outcome = {
        "advance": "moving",
        "await": "standing_by",
        "review_wait": "awaiting_review",
    }[expected_progress_signal]
    expected_intervention_requirement = {
        "moving": "none",
        "standing_by": "monitor",
        "awaiting_review": "review_required",
    }[expected_progress_outcome]
    expected_attention_level = {
        "none": "low",
        "monitor": "medium",
        "review_required": "high",
    }[expected_intervention_requirement]
    expected_notification_requirement = {
        "low": "none",
        "medium": "notify",
        "high": "escalate",
    }[expected_attention_level]
    expected_response_priority = {
        "none": "normal",
        "notify": "elevated",
        "escalate": "urgent",
    }[expected_notification_requirement]
    expected_response_channel = {
        "normal": "standard_channel",
        "elevated": "priority_channel",
        "urgent": "escalation_channel",
    }[expected_response_priority]
    expected_response_route = {
        "standard_channel": "standard_route",
        "priority_channel": "priority_route",
        "escalation_channel": "escalation_route",
    }[expected_response_channel]
    expected_followup_requirement = {
        "standard_route": "none",
        "priority_route": "follow_up",
        "escalation_route": "escalation_follow_up",
    }[expected_response_route]
    expected_consumer_decision_posture = {
        "none": "observe",
        "follow_up": "engage",
        "escalation_follow_up": "escalate",
    }[expected_followup_requirement]
    expected_consumer_action_requirement = {
        "observe": "no_action",
        "engage": "action_required",
        "escalate": "escalation_required",
    }[expected_consumer_decision_posture]
    expected_consumer_work_queue_assignment = {
        "no_action": "observation_queue",
        "action_required": "action_queue",
        "escalation_required": "escalation_queue",
    }[expected_consumer_action_requirement]
    expected_consumer_processing_plan = {
        "observation_queue": "observe_only",
        "action_queue": "process_action",
        "escalation_queue": "process_escalation",
    }[expected_consumer_work_queue_assignment]
    expected_consumer_operator_requirement = {
        "observe_only": "none",
        "process_action": "operator_required",
        "process_escalation": "senior_operator_required",
    }[expected_consumer_processing_plan]
    expected_consumer_assignment_lane = {
        "none": "self_service_lane",
        "operator_required": "operator_lane",
        "senior_operator_required": "senior_operator_lane",
    }[expected_consumer_operator_requirement]
    expected_consumer_service_tier = {
        "self_service_lane": "self_service",
        "operator_lane": "operator_managed",
        "senior_operator_lane": "senior_managed",
    }[expected_consumer_assignment_lane]
    expected_consumer_sla_class = {
        "self_service": "deferred",
        "operator_managed": "standard",
        "senior_managed": "priority",
    }[expected_consumer_service_tier]
    expected_consumer_response_window = {
        "deferred": "backlog_window",
        "standard": "standard_window",
        "priority": "priority_window",
    }[expected_consumer_sla_class]
    expected_consumer_timing_posture = {
        "backlog_window": "later",
        "standard_window": "scheduled",
        "priority_window": "immediate",
    }[expected_consumer_response_window]
    expected_consumer_scheduling_commitment = {
        "later": "backlog_commitment",
        "scheduled": "scheduled_commitment",
        "immediate": "immediate_commitment",
    }[expected_consumer_timing_posture]
    expected_consumer_execution_readiness = {
        "backlog_commitment": "deferred_readiness",
        "scheduled_commitment": "planned_readiness",
        "immediate_commitment": "ready_now",
    }[expected_consumer_scheduling_commitment]
    expected_consumer_dispatch_readiness = {
        "deferred_readiness": "parked",
        "planned_readiness": "prepared",
        "ready_now": "dispatch_ready",
    }[expected_consumer_execution_readiness]
    expected_consumer_dispatch_authority = {
        "parked": "withhold",
        "prepared": "pre_authorize",
        "dispatch_ready": "authorize",
    }[expected_consumer_dispatch_readiness]
    expected_consumer_dispatch_permission = {
        "withhold": "not_permitted",
        "pre_authorize": "conditionally_permitted",
        "authorize": "permitted",
    }[expected_consumer_dispatch_authority]
    assert (
        {
            "not_permitted": "blocked",
            "conditionally_permitted": "gated",
            "permitted": "clear",
        }[expected_consumer_dispatch_permission]
        == expected_consumer_dispatch_clearance
    )
    assert (
        {
            "blocked": "hold_release",
            "gated": "conditional_release",
            "clear": "release",
        }[expected_consumer_dispatch_clearance]
        == expected_consumer_release_decision
    )
    assert (
        {
            "hold_release": "hold_mode",
            "conditional_release": "guarded_mode",
            "release": "release_mode",
        }[expected_consumer_release_decision]
        == expected_consumer_release_mode
    )
    assert (
        {
            "hold_mode": "do_not_execute",
            "guarded_mode": "execute_with_guard",
            "release_mode": "execute_release",
        }[expected_consumer_release_mode]
        == expected_consumer_release_execution_requirement
    )

    consumer_release_mode = {
        "projected_activation_decision": {"recommendation": decision},
        "approval_record": {
            "human_approval_status": {
                "status": {
                    "GO": "approved",
                    "PAUSE": "pending",
                    "REVIEW": "withheld",
                }[decision]
            }
        },
        "receiver_readiness_classification": expected_classification,
        "receiver_handling_directive": expected_handling_directive,
        "receiver_action_label": expected_action_label,
        "receiver_dispatch_intent": expected_dispatch_intent,
        "receiver_dispatch_mode": expected_dispatch_mode,
        "receiver_release_gate": expected_release_gate,
        "receiver_progress_state": expected_progress_state,
        "receiver_progress_signal": expected_progress_signal,
        "receiver_progress_outcome": expected_progress_outcome,
        "receiver_intervention_requirement": expected_intervention_requirement,
        "receiver_attention_level": expected_attention_level,
        "receiver_notification_requirement": expected_notification_requirement,
        "receiver_response_priority": expected_response_priority,
        "receiver_response_channel": expected_response_channel,
        "receiver_response_route": expected_response_route,
        "receiver_followup_requirement": expected_followup_requirement,
        "consumer_decision_posture": expected_consumer_decision_posture,
        "consumer_action_requirement": expected_consumer_action_requirement,
        "consumer_work_queue_assignment": expected_consumer_work_queue_assignment,
        "consumer_processing_plan": expected_consumer_processing_plan,
        "consumer_operator_requirement": expected_consumer_operator_requirement,
        "consumer_assignment_lane": expected_consumer_assignment_lane,
        "consumer_service_tier": expected_consumer_service_tier,
        "consumer_sla_class": expected_consumer_sla_class,
        "consumer_response_window": expected_consumer_response_window,
        "consumer_timing_posture": expected_consumer_timing_posture,
        "consumer_scheduling_commitment": expected_consumer_scheduling_commitment,
        "consumer_execution_readiness": expected_consumer_execution_readiness,
        "consumer_dispatch_readiness": expected_consumer_dispatch_readiness,
        "consumer_dispatch_authority": expected_consumer_dispatch_authority,
        "consumer_dispatch_permission": expected_consumer_dispatch_permission,
        "consumer_dispatch_clearance": expected_consumer_dispatch_clearance,
        "consumer_release_decision": expected_consumer_release_decision,
        "consumer_release_mode": expected_consumer_release_mode,
        "related_project_id": "project_consumer_release_execution_requirement_1",
        "related_activation_decision_id": (
            "activation_decision_consumer_release_execution_requirement_1"
        ),
        "related_packet_id": "packet_consumer_release_execution_requirement_1",
        "related_queue_item_id": "queue_consumer_release_execution_requirement_1",
    }

    consumer_release_execution_requirement = (
        build_consumer_release_execution_requirement_from_release_mode(
            consumer_release_mode=consumer_release_mode
        )
    )

    passthrough_keys = [
        "projected_activation_decision",
        "approval_record",
        "receiver_readiness_classification",
        "receiver_handling_directive",
        "receiver_action_label",
        "receiver_dispatch_intent",
        "receiver_dispatch_mode",
        "receiver_release_gate",
        "receiver_progress_state",
        "receiver_progress_signal",
        "receiver_progress_outcome",
        "receiver_intervention_requirement",
        "receiver_attention_level",
        "receiver_notification_requirement",
        "receiver_response_priority",
        "receiver_response_channel",
        "receiver_response_route",
        "receiver_followup_requirement",
        "consumer_decision_posture",
        "consumer_action_requirement",
        "consumer_work_queue_assignment",
        "consumer_processing_plan",
        "consumer_operator_requirement",
        "consumer_assignment_lane",
        "consumer_service_tier",
        "consumer_sla_class",
        "consumer_response_window",
        "consumer_timing_posture",
        "consumer_scheduling_commitment",
        "consumer_execution_readiness",
        "consumer_dispatch_readiness",
        "consumer_dispatch_authority",
        "consumer_dispatch_permission",
        "consumer_dispatch_clearance",
        "consumer_release_decision",
        "consumer_release_mode",
        "related_project_id",
        "related_activation_decision_id",
        "related_packet_id",
        "related_queue_item_id",
    ]
    for key in passthrough_keys:
        assert consumer_release_execution_requirement[key] == consumer_release_mode[key]
    assert (
        consumer_release_execution_requirement["consumer_release_execution_requirement"]
        == expected_consumer_release_execution_requirement
    )


@pytest.mark.parametrize(
    (
        "decision",
        "expected_consumer_dispatch_clearance",
        "expected_consumer_release_decision",
        "expected_consumer_release_mode",
        "expected_consumer_release_execution_requirement",
        "expected_consumer_release_execution_lane",
    ),
    [
        pytest.param(
            "GO",
            "blocked",
            "hold_release",
            "hold_mode",
            "do_not_execute",
            "blocked_lane",
            id="go",
        ),
        pytest.param(
            "PAUSE",
            "gated",
            "conditional_release",
            "guarded_mode",
            "execute_with_guard",
            "guarded_lane",
            id="pause",
        ),
        pytest.param(
            "REVIEW",
            "clear",
            "release",
            "release_mode",
            "execute_release",
            "release_lane",
            id="review",
        ),
    ],
)
def test_consumer_release_execution_lane_from_execution_requirement_matches_execution_requirement(
    decision: RecommendationValue,
    expected_consumer_dispatch_clearance: str,
    expected_consumer_release_decision: str,
    expected_consumer_release_mode: str,
    expected_consumer_release_execution_requirement: str,
    expected_consumer_release_execution_lane: str,
) -> None:
    expected_classification = {
        "GO": "ready",
        "PAUSE": "hold",
        "REVIEW": "needs_review",
    }[decision]
    expected_handling_directive = {
        "ready": "deliver",
        "hold": "defer",
        "needs_review": "route_for_review",
    }[expected_classification]
    expected_action_label = {
        "deliver": "dispatch",
        "defer": "wait",
        "route_for_review": "review_queue",
    }[expected_handling_directive]
    expected_dispatch_intent = {
        "dispatch": "send",
        "wait": "park",
        "review_queue": "review",
    }[expected_action_label]
    expected_dispatch_mode = {
        "send": "active",
        "park": "queued",
        "review": "review_pending",
    }[expected_dispatch_intent]
    expected_release_gate = {
        "active": "open",
        "queued": "deferred",
        "review_pending": "blocked_for_review",
    }[expected_dispatch_mode]
    expected_progress_state = {
        "open": "in_progress",
        "deferred": "pending",
        "blocked_for_review": "review_hold",
    }[expected_release_gate]
    expected_progress_signal = {
        "in_progress": "advance",
        "pending": "await",
        "review_hold": "review_wait",
    }[expected_progress_state]
    expected_progress_outcome = {
        "advance": "moving",
        "await": "standing_by",
        "review_wait": "awaiting_review",
    }[expected_progress_signal]
    expected_intervention_requirement = {
        "moving": "none",
        "standing_by": "monitor",
        "awaiting_review": "review_required",
    }[expected_progress_outcome]
    expected_attention_level = {
        "none": "low",
        "monitor": "medium",
        "review_required": "high",
    }[expected_intervention_requirement]
    expected_notification_requirement = {
        "low": "none",
        "medium": "notify",
        "high": "escalate",
    }[expected_attention_level]
    expected_response_priority = {
        "none": "normal",
        "notify": "elevated",
        "escalate": "urgent",
    }[expected_notification_requirement]
    expected_response_channel = {
        "normal": "standard_channel",
        "elevated": "priority_channel",
        "urgent": "escalation_channel",
    }[expected_response_priority]
    expected_response_route = {
        "standard_channel": "standard_route",
        "priority_channel": "priority_route",
        "escalation_channel": "escalation_route",
    }[expected_response_channel]
    expected_followup_requirement = {
        "standard_route": "none",
        "priority_route": "follow_up",
        "escalation_route": "escalation_follow_up",
    }[expected_response_route]
    expected_consumer_decision_posture = {
        "none": "observe",
        "follow_up": "engage",
        "escalation_follow_up": "escalate",
    }[expected_followup_requirement]
    expected_consumer_action_requirement = {
        "observe": "no_action",
        "engage": "action_required",
        "escalate": "escalation_required",
    }[expected_consumer_decision_posture]
    expected_consumer_work_queue_assignment = {
        "no_action": "observation_queue",
        "action_required": "action_queue",
        "escalation_required": "escalation_queue",
    }[expected_consumer_action_requirement]
    expected_consumer_processing_plan = {
        "observation_queue": "observe_only",
        "action_queue": "process_action",
        "escalation_queue": "process_escalation",
    }[expected_consumer_work_queue_assignment]
    expected_consumer_operator_requirement = {
        "observe_only": "none",
        "process_action": "operator_required",
        "process_escalation": "senior_operator_required",
    }[expected_consumer_processing_plan]
    expected_consumer_assignment_lane = {
        "none": "self_service_lane",
        "operator_required": "operator_lane",
        "senior_operator_required": "senior_operator_lane",
    }[expected_consumer_operator_requirement]
    expected_consumer_service_tier = {
        "self_service_lane": "self_service",
        "operator_lane": "operator_managed",
        "senior_operator_lane": "senior_managed",
    }[expected_consumer_assignment_lane]
    expected_consumer_sla_class = {
        "self_service": "deferred",
        "operator_managed": "standard",
        "senior_managed": "priority",
    }[expected_consumer_service_tier]
    expected_consumer_response_window = {
        "deferred": "backlog_window",
        "standard": "standard_window",
        "priority": "priority_window",
    }[expected_consumer_sla_class]
    expected_consumer_timing_posture = {
        "backlog_window": "later",
        "standard_window": "scheduled",
        "priority_window": "immediate",
    }[expected_consumer_response_window]
    expected_consumer_scheduling_commitment = {
        "later": "backlog_commitment",
        "scheduled": "scheduled_commitment",
        "immediate": "immediate_commitment",
    }[expected_consumer_timing_posture]
    expected_consumer_execution_readiness = {
        "backlog_commitment": "deferred_readiness",
        "scheduled_commitment": "planned_readiness",
        "immediate_commitment": "ready_now",
    }[expected_consumer_scheduling_commitment]
    expected_consumer_dispatch_readiness = {
        "deferred_readiness": "parked",
        "planned_readiness": "prepared",
        "ready_now": "dispatch_ready",
    }[expected_consumer_execution_readiness]
    expected_consumer_dispatch_authority = {
        "parked": "withhold",
        "prepared": "pre_authorize",
        "dispatch_ready": "authorize",
    }[expected_consumer_dispatch_readiness]
    expected_consumer_dispatch_permission = {
        "withhold": "not_permitted",
        "pre_authorize": "conditionally_permitted",
        "authorize": "permitted",
    }[expected_consumer_dispatch_authority]
    assert (
        {
            "not_permitted": "blocked",
            "conditionally_permitted": "gated",
            "permitted": "clear",
        }[expected_consumer_dispatch_permission]
        == expected_consumer_dispatch_clearance
    )
    assert (
        {
            "blocked": "hold_release",
            "gated": "conditional_release",
            "clear": "release",
        }[expected_consumer_dispatch_clearance]
        == expected_consumer_release_decision
    )
    assert (
        {
            "hold_release": "hold_mode",
            "conditional_release": "guarded_mode",
            "release": "release_mode",
        }[expected_consumer_release_decision]
        == expected_consumer_release_mode
    )
    assert (
        {
            "hold_mode": "do_not_execute",
            "guarded_mode": "execute_with_guard",
            "release_mode": "execute_release",
        }[expected_consumer_release_mode]
        == expected_consumer_release_execution_requirement
    )
    assert (
        {
            "do_not_execute": "blocked_lane",
            "execute_with_guard": "guarded_lane",
            "execute_release": "release_lane",
        }[expected_consumer_release_execution_requirement]
        == expected_consumer_release_execution_lane
    )

    consumer_release_execution_requirement = {
        "projected_activation_decision": {"recommendation": decision},
        "approval_record": {
            "human_approval_status": {
                "status": {
                    "GO": "approved",
                    "PAUSE": "pending",
                    "REVIEW": "withheld",
                }[decision]
            }
        },
        "receiver_readiness_classification": expected_classification,
        "receiver_handling_directive": expected_handling_directive,
        "receiver_action_label": expected_action_label,
        "receiver_dispatch_intent": expected_dispatch_intent,
        "receiver_dispatch_mode": expected_dispatch_mode,
        "receiver_release_gate": expected_release_gate,
        "receiver_progress_state": expected_progress_state,
        "receiver_progress_signal": expected_progress_signal,
        "receiver_progress_outcome": expected_progress_outcome,
        "receiver_intervention_requirement": expected_intervention_requirement,
        "receiver_attention_level": expected_attention_level,
        "receiver_notification_requirement": expected_notification_requirement,
        "receiver_response_priority": expected_response_priority,
        "receiver_response_channel": expected_response_channel,
        "receiver_response_route": expected_response_route,
        "receiver_followup_requirement": expected_followup_requirement,
        "consumer_decision_posture": expected_consumer_decision_posture,
        "consumer_action_requirement": expected_consumer_action_requirement,
        "consumer_work_queue_assignment": expected_consumer_work_queue_assignment,
        "consumer_processing_plan": expected_consumer_processing_plan,
        "consumer_operator_requirement": expected_consumer_operator_requirement,
        "consumer_assignment_lane": expected_consumer_assignment_lane,
        "consumer_service_tier": expected_consumer_service_tier,
        "consumer_sla_class": expected_consumer_sla_class,
        "consumer_response_window": expected_consumer_response_window,
        "consumer_timing_posture": expected_consumer_timing_posture,
        "consumer_scheduling_commitment": expected_consumer_scheduling_commitment,
        "consumer_execution_readiness": expected_consumer_execution_readiness,
        "consumer_dispatch_readiness": expected_consumer_dispatch_readiness,
        "consumer_dispatch_authority": expected_consumer_dispatch_authority,
        "consumer_dispatch_permission": expected_consumer_dispatch_permission,
        "consumer_dispatch_clearance": expected_consumer_dispatch_clearance,
        "consumer_release_decision": expected_consumer_release_decision,
        "consumer_release_mode": expected_consumer_release_mode,
        "consumer_release_execution_requirement": (
            expected_consumer_release_execution_requirement
        ),
        "related_project_id": "project_consumer_release_execution_lane_1",
        "related_activation_decision_id": (
            "activation_decision_consumer_release_execution_lane_1"
        ),
        "related_packet_id": "packet_consumer_release_execution_lane_1",
        "related_queue_item_id": "queue_consumer_release_execution_lane_1",
    }

    consumer_release_execution_lane = (
        build_consumer_release_execution_lane_from_execution_requirement(
            consumer_release_execution_requirement=consumer_release_execution_requirement
        )
    )

    passthrough_keys = [
        "projected_activation_decision",
        "approval_record",
        "receiver_readiness_classification",
        "receiver_handling_directive",
        "receiver_action_label",
        "receiver_dispatch_intent",
        "receiver_dispatch_mode",
        "receiver_release_gate",
        "receiver_progress_state",
        "receiver_progress_signal",
        "receiver_progress_outcome",
        "receiver_intervention_requirement",
        "receiver_attention_level",
        "receiver_notification_requirement",
        "receiver_response_priority",
        "receiver_response_channel",
        "receiver_response_route",
        "receiver_followup_requirement",
        "consumer_decision_posture",
        "consumer_action_requirement",
        "consumer_work_queue_assignment",
        "consumer_processing_plan",
        "consumer_operator_requirement",
        "consumer_assignment_lane",
        "consumer_service_tier",
        "consumer_sla_class",
        "consumer_response_window",
        "consumer_timing_posture",
        "consumer_scheduling_commitment",
        "consumer_execution_readiness",
        "consumer_dispatch_readiness",
        "consumer_dispatch_authority",
        "consumer_dispatch_permission",
        "consumer_dispatch_clearance",
        "consumer_release_decision",
        "consumer_release_mode",
        "consumer_release_execution_requirement",
        "related_project_id",
        "related_activation_decision_id",
        "related_packet_id",
        "related_queue_item_id",
    ]
    for key in passthrough_keys:
        assert consumer_release_execution_lane[key] == consumer_release_execution_requirement[
            key
        ]
    assert (
        consumer_release_execution_lane["consumer_release_execution_lane"]
        == expected_consumer_release_execution_lane
    )


@pytest.mark.parametrize(
    (
        "decision",
        "expected_consumer_dispatch_clearance",
        "expected_consumer_release_decision",
        "expected_consumer_release_mode",
        "expected_consumer_release_execution_requirement",
        "expected_consumer_release_execution_lane",
        "expected_consumer_release_handling_intent",
    ),
    [
        pytest.param(
            "GO",
            "blocked",
            "hold_release",
            "hold_mode",
            "do_not_execute",
            "blocked_lane",
            "do_not_route",
            id="go",
        ),
        pytest.param(
            "PAUSE",
            "gated",
            "conditional_release",
            "guarded_mode",
            "execute_with_guard",
            "guarded_lane",
            "route_with_guard",
            id="pause",
        ),
        pytest.param(
            "REVIEW",
            "clear",
            "release",
            "release_mode",
            "execute_release",
            "release_lane",
            "route_for_release",
            id="review",
        ),
    ],
)
def test_consumer_release_handling_intent_from_execution_lane_matches_execution_lane(
    decision: RecommendationValue,
    expected_consumer_dispatch_clearance: str,
    expected_consumer_release_decision: str,
    expected_consumer_release_mode: str,
    expected_consumer_release_execution_requirement: str,
    expected_consumer_release_execution_lane: str,
    expected_consumer_release_handling_intent: str,
) -> None:
    expected_classification = {
        "GO": "ready",
        "PAUSE": "hold",
        "REVIEW": "needs_review",
    }[decision]
    expected_handling_directive = {
        "ready": "deliver",
        "hold": "defer",
        "needs_review": "route_for_review",
    }[expected_classification]
    expected_action_label = {
        "deliver": "dispatch",
        "defer": "wait",
        "route_for_review": "review_queue",
    }[expected_handling_directive]
    expected_dispatch_intent = {
        "dispatch": "send",
        "wait": "park",
        "review_queue": "review",
    }[expected_action_label]
    expected_dispatch_mode = {
        "send": "active",
        "park": "queued",
        "review": "review_pending",
    }[expected_dispatch_intent]
    expected_release_gate = {
        "active": "open",
        "queued": "deferred",
        "review_pending": "blocked_for_review",
    }[expected_dispatch_mode]
    expected_progress_state = {
        "open": "in_progress",
        "deferred": "pending",
        "blocked_for_review": "review_hold",
    }[expected_release_gate]
    expected_progress_signal = {
        "in_progress": "advance",
        "pending": "await",
        "review_hold": "review_wait",
    }[expected_progress_state]
    expected_progress_outcome = {
        "advance": "moving",
        "await": "standing_by",
        "review_wait": "awaiting_review",
    }[expected_progress_signal]
    expected_intervention_requirement = {
        "moving": "none",
        "standing_by": "monitor",
        "awaiting_review": "review_required",
    }[expected_progress_outcome]
    expected_attention_level = {
        "none": "low",
        "monitor": "medium",
        "review_required": "high",
    }[expected_intervention_requirement]
    expected_notification_requirement = {
        "low": "none",
        "medium": "notify",
        "high": "escalate",
    }[expected_attention_level]
    expected_response_priority = {
        "none": "normal",
        "notify": "elevated",
        "escalate": "urgent",
    }[expected_notification_requirement]
    expected_response_channel = {
        "normal": "standard_channel",
        "elevated": "priority_channel",
        "urgent": "escalation_channel",
    }[expected_response_priority]
    expected_response_route = {
        "standard_channel": "standard_route",
        "priority_channel": "priority_route",
        "escalation_channel": "escalation_route",
    }[expected_response_channel]
    expected_followup_requirement = {
        "standard_route": "none",
        "priority_route": "follow_up",
        "escalation_route": "escalation_follow_up",
    }[expected_response_route]
    expected_consumer_decision_posture = {
        "none": "observe",
        "follow_up": "engage",
        "escalation_follow_up": "escalate",
    }[expected_followup_requirement]
    expected_consumer_action_requirement = {
        "observe": "no_action",
        "engage": "action_required",
        "escalate": "escalation_required",
    }[expected_consumer_decision_posture]
    expected_consumer_work_queue_assignment = {
        "no_action": "observation_queue",
        "action_required": "action_queue",
        "escalation_required": "escalation_queue",
    }[expected_consumer_action_requirement]
    expected_consumer_processing_plan = {
        "observation_queue": "observe_only",
        "action_queue": "process_action",
        "escalation_queue": "process_escalation",
    }[expected_consumer_work_queue_assignment]
    expected_consumer_operator_requirement = {
        "observe_only": "none",
        "process_action": "operator_required",
        "process_escalation": "senior_operator_required",
    }[expected_consumer_processing_plan]
    expected_consumer_assignment_lane = {
        "none": "self_service_lane",
        "operator_required": "operator_lane",
        "senior_operator_required": "senior_operator_lane",
    }[expected_consumer_operator_requirement]
    expected_consumer_service_tier = {
        "self_service_lane": "self_service",
        "operator_lane": "operator_managed",
        "senior_operator_lane": "senior_managed",
    }[expected_consumer_assignment_lane]
    expected_consumer_sla_class = {
        "self_service": "deferred",
        "operator_managed": "standard",
        "senior_managed": "priority",
    }[expected_consumer_service_tier]
    expected_consumer_response_window = {
        "deferred": "backlog_window",
        "standard": "standard_window",
        "priority": "priority_window",
    }[expected_consumer_sla_class]
    expected_consumer_timing_posture = {
        "backlog_window": "later",
        "standard_window": "scheduled",
        "priority_window": "immediate",
    }[expected_consumer_response_window]
    expected_consumer_scheduling_commitment = {
        "later": "backlog_commitment",
        "scheduled": "scheduled_commitment",
        "immediate": "immediate_commitment",
    }[expected_consumer_timing_posture]
    expected_consumer_execution_readiness = {
        "backlog_commitment": "deferred_readiness",
        "scheduled_commitment": "planned_readiness",
        "immediate_commitment": "ready_now",
    }[expected_consumer_scheduling_commitment]
    expected_consumer_dispatch_readiness = {
        "deferred_readiness": "parked",
        "planned_readiness": "prepared",
        "ready_now": "dispatch_ready",
    }[expected_consumer_execution_readiness]
    expected_consumer_dispatch_authority = {
        "parked": "withhold",
        "prepared": "pre_authorize",
        "dispatch_ready": "authorize",
    }[expected_consumer_dispatch_readiness]
    expected_consumer_dispatch_permission = {
        "withhold": "not_permitted",
        "pre_authorize": "conditionally_permitted",
        "authorize": "permitted",
    }[expected_consumer_dispatch_authority]
    assert (
        {
            "not_permitted": "blocked",
            "conditionally_permitted": "gated",
            "permitted": "clear",
        }[expected_consumer_dispatch_permission]
        == expected_consumer_dispatch_clearance
    )
    assert (
        {
            "blocked": "hold_release",
            "gated": "conditional_release",
            "clear": "release",
        }[expected_consumer_dispatch_clearance]
        == expected_consumer_release_decision
    )
    assert (
        {
            "hold_release": "hold_mode",
            "conditional_release": "guarded_mode",
            "release": "release_mode",
        }[expected_consumer_release_decision]
        == expected_consumer_release_mode
    )
    assert (
        {
            "hold_mode": "do_not_execute",
            "guarded_mode": "execute_with_guard",
            "release_mode": "execute_release",
        }[expected_consumer_release_mode]
        == expected_consumer_release_execution_requirement
    )
    assert (
        {
            "do_not_execute": "blocked_lane",
            "execute_with_guard": "guarded_lane",
            "execute_release": "release_lane",
        }[expected_consumer_release_execution_requirement]
        == expected_consumer_release_execution_lane
    )
    assert (
        {
            "blocked_lane": "do_not_route",
            "guarded_lane": "route_with_guard",
            "release_lane": "route_for_release",
        }[expected_consumer_release_execution_lane]
        == expected_consumer_release_handling_intent
    )

    consumer_release_execution_lane = {
        "projected_activation_decision": {"recommendation": decision},
        "approval_record": {
            "human_approval_status": {
                "status": {
                    "GO": "approved",
                    "PAUSE": "pending",
                    "REVIEW": "withheld",
                }[decision]
            }
        },
        "receiver_readiness_classification": expected_classification,
        "receiver_handling_directive": expected_handling_directive,
        "receiver_action_label": expected_action_label,
        "receiver_dispatch_intent": expected_dispatch_intent,
        "receiver_dispatch_mode": expected_dispatch_mode,
        "receiver_release_gate": expected_release_gate,
        "receiver_progress_state": expected_progress_state,
        "receiver_progress_signal": expected_progress_signal,
        "receiver_progress_outcome": expected_progress_outcome,
        "receiver_intervention_requirement": expected_intervention_requirement,
        "receiver_attention_level": expected_attention_level,
        "receiver_notification_requirement": expected_notification_requirement,
        "receiver_response_priority": expected_response_priority,
        "receiver_response_channel": expected_response_channel,
        "receiver_response_route": expected_response_route,
        "receiver_followup_requirement": expected_followup_requirement,
        "consumer_decision_posture": expected_consumer_decision_posture,
        "consumer_action_requirement": expected_consumer_action_requirement,
        "consumer_work_queue_assignment": expected_consumer_work_queue_assignment,
        "consumer_processing_plan": expected_consumer_processing_plan,
        "consumer_operator_requirement": expected_consumer_operator_requirement,
        "consumer_assignment_lane": expected_consumer_assignment_lane,
        "consumer_service_tier": expected_consumer_service_tier,
        "consumer_sla_class": expected_consumer_sla_class,
        "consumer_response_window": expected_consumer_response_window,
        "consumer_timing_posture": expected_consumer_timing_posture,
        "consumer_scheduling_commitment": expected_consumer_scheduling_commitment,
        "consumer_execution_readiness": expected_consumer_execution_readiness,
        "consumer_dispatch_readiness": expected_consumer_dispatch_readiness,
        "consumer_dispatch_authority": expected_consumer_dispatch_authority,
        "consumer_dispatch_permission": expected_consumer_dispatch_permission,
        "consumer_dispatch_clearance": expected_consumer_dispatch_clearance,
        "consumer_release_decision": expected_consumer_release_decision,
        "consumer_release_mode": expected_consumer_release_mode,
        "consumer_release_execution_requirement": (
            expected_consumer_release_execution_requirement
        ),
        "consumer_release_execution_lane": expected_consumer_release_execution_lane,
        "related_project_id": "project_consumer_release_handling_intent_1",
        "related_activation_decision_id": (
            "activation_decision_consumer_release_handling_intent_1"
        ),
        "related_packet_id": "packet_consumer_release_handling_intent_1",
        "related_queue_item_id": "queue_consumer_release_handling_intent_1",
    }

    consumer_release_handling_intent = (
        build_consumer_release_handling_intent_from_execution_lane(
            consumer_release_execution_lane=consumer_release_execution_lane
        )
    )

    passthrough_keys = [
        "projected_activation_decision",
        "approval_record",
        "receiver_readiness_classification",
        "receiver_handling_directive",
        "receiver_action_label",
        "receiver_dispatch_intent",
        "receiver_dispatch_mode",
        "receiver_release_gate",
        "receiver_progress_state",
        "receiver_progress_signal",
        "receiver_progress_outcome",
        "receiver_intervention_requirement",
        "receiver_attention_level",
        "receiver_notification_requirement",
        "receiver_response_priority",
        "receiver_response_channel",
        "receiver_response_route",
        "receiver_followup_requirement",
        "consumer_decision_posture",
        "consumer_action_requirement",
        "consumer_work_queue_assignment",
        "consumer_processing_plan",
        "consumer_operator_requirement",
        "consumer_assignment_lane",
        "consumer_service_tier",
        "consumer_sla_class",
        "consumer_response_window",
        "consumer_timing_posture",
        "consumer_scheduling_commitment",
        "consumer_execution_readiness",
        "consumer_dispatch_readiness",
        "consumer_dispatch_authority",
        "consumer_dispatch_permission",
        "consumer_dispatch_clearance",
        "consumer_release_decision",
        "consumer_release_mode",
        "consumer_release_execution_requirement",
        "consumer_release_execution_lane",
        "related_project_id",
        "related_activation_decision_id",
        "related_packet_id",
        "related_queue_item_id",
    ]
    for key in passthrough_keys:
        assert consumer_release_handling_intent[key] == consumer_release_execution_lane[key]
    assert (
        consumer_release_handling_intent["consumer_release_handling_intent"]
        == expected_consumer_release_handling_intent
    )


@pytest.mark.parametrize(
    (
        "decision",
        "expected_consumer_dispatch_clearance",
        "expected_consumer_release_decision",
        "expected_consumer_release_mode",
        "expected_consumer_release_execution_requirement",
        "expected_consumer_release_execution_lane",
        "expected_consumer_release_handling_intent",
        "expected_consumer_release_action_plan",
    ),
    [
        pytest.param(
            "GO",
            "blocked",
            "hold_release",
            "hold_mode",
            "do_not_execute",
            "blocked_lane",
            "do_not_route",
            "hold_plan",
            id="go",
        ),
        pytest.param(
            "PAUSE",
            "gated",
            "conditional_release",
            "guarded_mode",
            "execute_with_guard",
            "guarded_lane",
            "route_with_guard",
            "guarded_release_plan",
            id="pause",
        ),
        pytest.param(
            "REVIEW",
            "clear",
            "release",
            "release_mode",
            "execute_release",
            "release_lane",
            "route_for_release",
            "release_plan",
            id="review",
        ),
    ],
)
def test_consumer_release_action_plan_from_handling_intent_matches_handling_intent(
    decision: RecommendationValue,
    expected_consumer_dispatch_clearance: str,
    expected_consumer_release_decision: str,
    expected_consumer_release_mode: str,
    expected_consumer_release_execution_requirement: str,
    expected_consumer_release_execution_lane: str,
    expected_consumer_release_handling_intent: str,
    expected_consumer_release_action_plan: str,
) -> None:
    expected_classification = {
        "GO": "ready",
        "PAUSE": "hold",
        "REVIEW": "needs_review",
    }[decision]
    expected_handling_directive = {
        "ready": "deliver",
        "hold": "defer",
        "needs_review": "route_for_review",
    }[expected_classification]
    expected_action_label = {
        "deliver": "dispatch",
        "defer": "wait",
        "route_for_review": "review_queue",
    }[expected_handling_directive]
    expected_dispatch_intent = {
        "dispatch": "send",
        "wait": "park",
        "review_queue": "review",
    }[expected_action_label]
    expected_dispatch_mode = {
        "send": "active",
        "park": "queued",
        "review": "review_pending",
    }[expected_dispatch_intent]
    expected_release_gate = {
        "active": "open",
        "queued": "deferred",
        "review_pending": "blocked_for_review",
    }[expected_dispatch_mode]
    expected_progress_state = {
        "open": "in_progress",
        "deferred": "pending",
        "blocked_for_review": "review_hold",
    }[expected_release_gate]
    expected_progress_signal = {
        "in_progress": "advance",
        "pending": "await",
        "review_hold": "review_wait",
    }[expected_progress_state]
    expected_progress_outcome = {
        "advance": "moving",
        "await": "standing_by",
        "review_wait": "awaiting_review",
    }[expected_progress_signal]
    expected_intervention_requirement = {
        "moving": "none",
        "standing_by": "monitor",
        "awaiting_review": "review_required",
    }[expected_progress_outcome]
    expected_attention_level = {
        "none": "low",
        "monitor": "medium",
        "review_required": "high",
    }[expected_intervention_requirement]
    expected_notification_requirement = {
        "low": "none",
        "medium": "notify",
        "high": "escalate",
    }[expected_attention_level]
    expected_response_priority = {
        "none": "normal",
        "notify": "elevated",
        "escalate": "urgent",
    }[expected_notification_requirement]
    expected_response_channel = {
        "normal": "standard_channel",
        "elevated": "priority_channel",
        "urgent": "escalation_channel",
    }[expected_response_priority]
    expected_response_route = {
        "standard_channel": "standard_route",
        "priority_channel": "priority_route",
        "escalation_channel": "escalation_route",
    }[expected_response_channel]
    expected_followup_requirement = {
        "standard_route": "none",
        "priority_route": "follow_up",
        "escalation_route": "escalation_follow_up",
    }[expected_response_route]
    expected_consumer_decision_posture = {
        "none": "observe",
        "follow_up": "engage",
        "escalation_follow_up": "escalate",
    }[expected_followup_requirement]
    expected_consumer_action_requirement = {
        "observe": "no_action",
        "engage": "action_required",
        "escalate": "escalation_required",
    }[expected_consumer_decision_posture]
    expected_consumer_work_queue_assignment = {
        "no_action": "observation_queue",
        "action_required": "action_queue",
        "escalation_required": "escalation_queue",
    }[expected_consumer_action_requirement]
    expected_consumer_processing_plan = {
        "observation_queue": "observe_only",
        "action_queue": "process_action",
        "escalation_queue": "process_escalation",
    }[expected_consumer_work_queue_assignment]
    expected_consumer_operator_requirement = {
        "observe_only": "none",
        "process_action": "operator_required",
        "process_escalation": "senior_operator_required",
    }[expected_consumer_processing_plan]
    expected_consumer_assignment_lane = {
        "none": "self_service_lane",
        "operator_required": "operator_lane",
        "senior_operator_required": "senior_operator_lane",
    }[expected_consumer_operator_requirement]
    expected_consumer_service_tier = {
        "self_service_lane": "self_service",
        "operator_lane": "operator_managed",
        "senior_operator_lane": "senior_managed",
    }[expected_consumer_assignment_lane]
    expected_consumer_sla_class = {
        "self_service": "deferred",
        "operator_managed": "standard",
        "senior_managed": "priority",
    }[expected_consumer_service_tier]
    expected_consumer_response_window = {
        "deferred": "backlog_window",
        "standard": "standard_window",
        "priority": "priority_window",
    }[expected_consumer_sla_class]
    expected_consumer_timing_posture = {
        "backlog_window": "later",
        "standard_window": "scheduled",
        "priority_window": "immediate",
    }[expected_consumer_response_window]
    expected_consumer_scheduling_commitment = {
        "later": "backlog_commitment",
        "scheduled": "scheduled_commitment",
        "immediate": "immediate_commitment",
    }[expected_consumer_timing_posture]
    expected_consumer_execution_readiness = {
        "backlog_commitment": "deferred_readiness",
        "scheduled_commitment": "planned_readiness",
        "immediate_commitment": "ready_now",
    }[expected_consumer_scheduling_commitment]
    expected_consumer_dispatch_readiness = {
        "deferred_readiness": "parked",
        "planned_readiness": "prepared",
        "ready_now": "dispatch_ready",
    }[expected_consumer_execution_readiness]
    expected_consumer_dispatch_authority = {
        "parked": "withhold",
        "prepared": "pre_authorize",
        "dispatch_ready": "authorize",
    }[expected_consumer_dispatch_readiness]
    expected_consumer_dispatch_permission = {
        "withhold": "not_permitted",
        "pre_authorize": "conditionally_permitted",
        "authorize": "permitted",
    }[expected_consumer_dispatch_authority]
    assert (
        {
            "not_permitted": "blocked",
            "conditionally_permitted": "gated",
            "permitted": "clear",
        }[expected_consumer_dispatch_permission]
        == expected_consumer_dispatch_clearance
    )
    assert (
        {
            "blocked": "hold_release",
            "gated": "conditional_release",
            "clear": "release",
        }[expected_consumer_dispatch_clearance]
        == expected_consumer_release_decision
    )
    assert (
        {
            "hold_release": "hold_mode",
            "conditional_release": "guarded_mode",
            "release": "release_mode",
        }[expected_consumer_release_decision]
        == expected_consumer_release_mode
    )
    assert (
        {
            "hold_mode": "do_not_execute",
            "guarded_mode": "execute_with_guard",
            "release_mode": "execute_release",
        }[expected_consumer_release_mode]
        == expected_consumer_release_execution_requirement
    )
    assert (
        {
            "do_not_execute": "blocked_lane",
            "execute_with_guard": "guarded_lane",
            "execute_release": "release_lane",
        }[expected_consumer_release_execution_requirement]
        == expected_consumer_release_execution_lane
    )
    assert (
        {
            "blocked_lane": "do_not_route",
            "guarded_lane": "route_with_guard",
            "release_lane": "route_for_release",
        }[expected_consumer_release_execution_lane]
        == expected_consumer_release_handling_intent
    )
    assert (
        {
            "do_not_route": "hold_plan",
            "route_with_guard": "guarded_release_plan",
            "route_for_release": "release_plan",
        }[expected_consumer_release_handling_intent]
        == expected_consumer_release_action_plan
    )

    consumer_release_handling_intent = {
        "projected_activation_decision": {"recommendation": decision},
        "approval_record": {
            "human_approval_status": {
                "status": {
                    "GO": "approved",
                    "PAUSE": "pending",
                    "REVIEW": "withheld",
                }[decision]
            }
        },
        "receiver_readiness_classification": expected_classification,
        "receiver_handling_directive": expected_handling_directive,
        "receiver_action_label": expected_action_label,
        "receiver_dispatch_intent": expected_dispatch_intent,
        "receiver_dispatch_mode": expected_dispatch_mode,
        "receiver_release_gate": expected_release_gate,
        "receiver_progress_state": expected_progress_state,
        "receiver_progress_signal": expected_progress_signal,
        "receiver_progress_outcome": expected_progress_outcome,
        "receiver_intervention_requirement": expected_intervention_requirement,
        "receiver_attention_level": expected_attention_level,
        "receiver_notification_requirement": expected_notification_requirement,
        "receiver_response_priority": expected_response_priority,
        "receiver_response_channel": expected_response_channel,
        "receiver_response_route": expected_response_route,
        "receiver_followup_requirement": expected_followup_requirement,
        "consumer_decision_posture": expected_consumer_decision_posture,
        "consumer_action_requirement": expected_consumer_action_requirement,
        "consumer_work_queue_assignment": expected_consumer_work_queue_assignment,
        "consumer_processing_plan": expected_consumer_processing_plan,
        "consumer_operator_requirement": expected_consumer_operator_requirement,
        "consumer_assignment_lane": expected_consumer_assignment_lane,
        "consumer_service_tier": expected_consumer_service_tier,
        "consumer_sla_class": expected_consumer_sla_class,
        "consumer_response_window": expected_consumer_response_window,
        "consumer_timing_posture": expected_consumer_timing_posture,
        "consumer_scheduling_commitment": expected_consumer_scheduling_commitment,
        "consumer_execution_readiness": expected_consumer_execution_readiness,
        "consumer_dispatch_readiness": expected_consumer_dispatch_readiness,
        "consumer_dispatch_authority": expected_consumer_dispatch_authority,
        "consumer_dispatch_permission": expected_consumer_dispatch_permission,
        "consumer_dispatch_clearance": expected_consumer_dispatch_clearance,
        "consumer_release_decision": expected_consumer_release_decision,
        "consumer_release_mode": expected_consumer_release_mode,
        "consumer_release_execution_requirement": (
            expected_consumer_release_execution_requirement
        ),
        "consumer_release_execution_lane": expected_consumer_release_execution_lane,
        "consumer_release_handling_intent": expected_consumer_release_handling_intent,
        "related_project_id": "project_consumer_release_action_plan_1",
        "related_activation_decision_id": (
            "activation_decision_consumer_release_action_plan_1"
        ),
        "related_packet_id": "packet_consumer_release_action_plan_1",
        "related_queue_item_id": "queue_consumer_release_action_plan_1",
    }

    consumer_release_action_plan = build_consumer_release_action_plan_from_handling_intent(
        consumer_release_handling_intent=consumer_release_handling_intent
    )

    passthrough_keys = [
        "projected_activation_decision",
        "approval_record",
        "receiver_readiness_classification",
        "receiver_handling_directive",
        "receiver_action_label",
        "receiver_dispatch_intent",
        "receiver_dispatch_mode",
        "receiver_release_gate",
        "receiver_progress_state",
        "receiver_progress_signal",
        "receiver_progress_outcome",
        "receiver_intervention_requirement",
        "receiver_attention_level",
        "receiver_notification_requirement",
        "receiver_response_priority",
        "receiver_response_channel",
        "receiver_response_route",
        "receiver_followup_requirement",
        "consumer_decision_posture",
        "consumer_action_requirement",
        "consumer_work_queue_assignment",
        "consumer_processing_plan",
        "consumer_operator_requirement",
        "consumer_assignment_lane",
        "consumer_service_tier",
        "consumer_sla_class",
        "consumer_response_window",
        "consumer_timing_posture",
        "consumer_scheduling_commitment",
        "consumer_execution_readiness",
        "consumer_dispatch_readiness",
        "consumer_dispatch_authority",
        "consumer_dispatch_permission",
        "consumer_dispatch_clearance",
        "consumer_release_decision",
        "consumer_release_mode",
        "consumer_release_execution_requirement",
        "consumer_release_execution_lane",
        "consumer_release_handling_intent",
        "related_project_id",
        "related_activation_decision_id",
        "related_packet_id",
        "related_queue_item_id",
    ]
    for key in passthrough_keys:
        assert consumer_release_action_plan[key] == consumer_release_handling_intent[key]
    assert (
        consumer_release_action_plan["consumer_release_action_plan"]
        == expected_consumer_release_action_plan
    )


def _build_consumer_release_action_plan_for_decision(
    decision: RecommendationValue,
) -> dict[str, object]:
    classification_by_decision = {
        "GO": "ready",
        "PAUSE": "hold",
        "REVIEW": "needs_review",
    }
    approval_status_by_decision = {
        "GO": "approved",
        "PAUSE": "pending",
        "REVIEW": "withheld",
    }
    consumer_receiver_readiness_classification = {
        "projected_activation_decision": {"recommendation": decision},
        "approval_record": {
            "human_approval_status": {
                "status": approval_status_by_decision[decision],
            }
        },
        "receiver_readiness_classification": classification_by_decision[decision],
        "related_project_id": "project_consumer_release_batch_bundle_1",
        "related_activation_decision_id": (
            "activation_decision_consumer_release_batch_bundle_1"
        ),
        "related_packet_id": "packet_consumer_release_batch_bundle_1",
        "related_queue_item_id": "queue_consumer_release_batch_bundle_1",
    }
    consumer_receiver_handling_directive = (
        build_consumer_receiver_handling_directive_from_classification(
            consumer_receiver_readiness_classification=(
                consumer_receiver_readiness_classification
            )
        )
    )
    consumer_receiver_action_label = (
        build_consumer_receiver_action_label_from_directive(
            consumer_receiver_handling_directive=consumer_receiver_handling_directive
        )
    )
    consumer_receiver_dispatch_intent = (
        build_consumer_receiver_dispatch_intent_from_action_label(
            consumer_receiver_action_label=consumer_receiver_action_label
        )
    )
    consumer_receiver_dispatch_mode = build_consumer_receiver_dispatch_mode_from_intent(
        consumer_receiver_dispatch_intent=consumer_receiver_dispatch_intent
    )
    consumer_receiver_release_gate = (
        build_consumer_receiver_release_gate_from_dispatch_mode(
            consumer_receiver_dispatch_mode=consumer_receiver_dispatch_mode
        )
    )
    consumer_receiver_progress_state = (
        build_consumer_receiver_progress_state_from_release_gate(
            consumer_receiver_release_gate=consumer_receiver_release_gate
        )
    )
    consumer_receiver_progress_signal = build_consumer_receiver_progress_signal_from_state(
        consumer_receiver_progress_state=consumer_receiver_progress_state
    )
    consumer_receiver_progress_outcome = (
        build_consumer_receiver_progress_outcome_from_signal(
            consumer_receiver_progress_signal=consumer_receiver_progress_signal
        )
    )
    consumer_receiver_intervention_requirement = (
        build_consumer_receiver_intervention_requirement_from_progress_outcome(
            consumer_receiver_progress_outcome=consumer_receiver_progress_outcome
        )
    )
    consumer_receiver_attention_level = (
        build_consumer_receiver_attention_level_from_intervention_requirement(
            consumer_receiver_intervention_requirement=(
                consumer_receiver_intervention_requirement
            )
        )
    )
    consumer_receiver_notification_requirement = (
        build_consumer_receiver_notification_requirement_from_attention_level(
            consumer_receiver_attention_level=consumer_receiver_attention_level
        )
    )
    consumer_receiver_response_priority = (
        build_consumer_receiver_response_priority_from_notification_requirement(
            consumer_receiver_notification_requirement=(
                consumer_receiver_notification_requirement
            )
        )
    )
    consumer_receiver_response_channel = (
        build_consumer_receiver_response_channel_from_priority(
            consumer_receiver_response_priority=consumer_receiver_response_priority
        )
    )
    consumer_receiver_response_route = build_consumer_receiver_response_route_from_channel(
        consumer_receiver_response_channel=consumer_receiver_response_channel
    )
    consumer_receiver_followup_requirement = (
        build_consumer_receiver_followup_requirement_from_response_route(
            consumer_receiver_response_route=consumer_receiver_response_route
        )
    )
    consumer_decision_surface = build_consumer_decision_surface_from_followup_requirement(
        consumer_receiver_followup_requirement=consumer_receiver_followup_requirement
    )
    consumer_decision_posture = build_consumer_decision_posture_from_surface(
        consumer_decision_surface=consumer_decision_surface
    )
    consumer_action_requirement = build_consumer_action_requirement_from_posture(
        consumer_decision_posture=consumer_decision_posture
    )
    consumer_work_queue_assignment = (
        build_consumer_work_queue_assignment_from_action_requirement(
            consumer_action_requirement=consumer_action_requirement
        )
    )
    consumer_processing_plan = build_consumer_processing_plan_from_work_queue_assignment(
        consumer_work_queue_assignment=consumer_work_queue_assignment
    )
    consumer_operator_requirement = (
        build_consumer_operator_requirement_from_processing_plan(
            consumer_processing_plan=consumer_processing_plan
        )
    )
    consumer_assignment_lane = build_consumer_assignment_lane_from_operator_requirement(
        consumer_operator_requirement=consumer_operator_requirement
    )
    consumer_service_tier = build_consumer_service_tier_from_assignment_lane(
        consumer_assignment_lane=consumer_assignment_lane
    )
    consumer_sla_class = build_consumer_sla_class_from_service_tier(
        consumer_service_tier=consumer_service_tier
    )
    consumer_response_window = build_consumer_response_window_from_sla_class(
        consumer_sla_class=consumer_sla_class
    )
    consumer_timing_posture = build_consumer_timing_posture_from_response_window(
        consumer_response_window=consumer_response_window
    )
    consumer_scheduling_commitment = (
        build_consumer_scheduling_commitment_from_timing_posture(
            consumer_timing_posture=consumer_timing_posture
        )
    )
    consumer_execution_readiness = (
        build_consumer_execution_readiness_from_scheduling_commitment(
            consumer_scheduling_commitment=consumer_scheduling_commitment
        )
    )
    consumer_dispatch_readiness = (
        build_consumer_dispatch_readiness_from_execution_readiness(
            consumer_execution_readiness=consumer_execution_readiness
        )
    )
    consumer_dispatch_authority = build_consumer_dispatch_authority_from_readiness(
        consumer_dispatch_readiness=consumer_dispatch_readiness
    )
    consumer_dispatch_permission = build_consumer_dispatch_permission_from_authority(
        consumer_dispatch_authority=consumer_dispatch_authority
    )
    consumer_dispatch_clearance = build_consumer_dispatch_clearance_from_permission(
        consumer_dispatch_permission=consumer_dispatch_permission
    )
    consumer_release_decision = build_consumer_release_decision_from_dispatch_clearance(
        consumer_dispatch_clearance=consumer_dispatch_clearance
    )
    consumer_release_mode = build_consumer_release_mode_from_release_decision(
        consumer_release_decision=consumer_release_decision
    )
    consumer_release_execution_requirement = (
        build_consumer_release_execution_requirement_from_release_mode(
            consumer_release_mode=consumer_release_mode
        )
    )
    consumer_release_execution_lane = (
        build_consumer_release_execution_lane_from_execution_requirement(
            consumer_release_execution_requirement=consumer_release_execution_requirement
        )
    )
    consumer_release_handling_intent = (
        build_consumer_release_handling_intent_from_execution_lane(
            consumer_release_execution_lane=consumer_release_execution_lane
        )
    )
    return build_consumer_release_action_plan_from_handling_intent(
        consumer_release_handling_intent=consumer_release_handling_intent
    )


@pytest.mark.parametrize(
    ("decision", "expected_consumer_release_queue"),
    [
        pytest.param("GO", "hold_queue", id="go"),
        pytest.param("PAUSE", "guarded_release_queue", id="pause"),
        pytest.param("REVIEW", "release_queue", id="review"),
    ],
)
def test_consumer_release_queue_from_action_plan_matches_action_plan(
    decision: RecommendationValue,
    expected_consumer_release_queue: str,
) -> None:
    consumer_release_action_plan = _build_consumer_release_action_plan_for_decision(decision)
    consumer_release_queue = build_consumer_release_queue_from_action_plan(
        consumer_release_action_plan=consumer_release_action_plan
    )

    for key, value in consumer_release_action_plan.items():
        assert consumer_release_queue[key] == value
    assert consumer_release_queue["consumer_release_queue"] == expected_consumer_release_queue


@pytest.mark.parametrize(
    ("decision", "expected_consumer_release_priority"),
    [
        pytest.param("GO", "low", id="go"),
        pytest.param("PAUSE", "medium", id="pause"),
        pytest.param("REVIEW", "high", id="review"),
    ],
)
def test_consumer_release_priority_from_queue_matches_queue(
    decision: RecommendationValue,
    expected_consumer_release_priority: str,
) -> None:
    consumer_release_action_plan = _build_consumer_release_action_plan_for_decision(decision)
    consumer_release_queue = build_consumer_release_queue_from_action_plan(
        consumer_release_action_plan=consumer_release_action_plan
    )
    consumer_release_priority = build_consumer_release_priority_from_queue(
        consumer_release_queue=consumer_release_queue
    )

    for key, value in consumer_release_queue.items():
        assert consumer_release_priority[key] == value
    assert (
        consumer_release_priority["consumer_release_priority"]
        == expected_consumer_release_priority
    )


@pytest.mark.parametrize(
    ("decision", "expected_consumer_release_window"),
    [
        pytest.param("GO", "deferred_window", id="go"),
        pytest.param("PAUSE", "controlled_window", id="pause"),
        pytest.param("REVIEW", "immediate_window", id="review"),
    ],
)
def test_consumer_release_window_from_priority_matches_priority(
    decision: RecommendationValue,
    expected_consumer_release_window: str,
) -> None:
    consumer_release_action_plan = _build_consumer_release_action_plan_for_decision(decision)
    consumer_release_queue = build_consumer_release_queue_from_action_plan(
        consumer_release_action_plan=consumer_release_action_plan
    )
    consumer_release_priority = build_consumer_release_priority_from_queue(
        consumer_release_queue=consumer_release_queue
    )
    consumer_release_window = build_consumer_release_window_from_priority(
        consumer_release_priority=consumer_release_priority
    )

    for key, value in consumer_release_priority.items():
        assert consumer_release_window[key] == value
    assert consumer_release_window["consumer_release_window"] == expected_consumer_release_window


def _build_consumer_release_window_for_decision(
    decision: RecommendationValue,
) -> dict[str, object]:
    consumer_release_action_plan = _build_consumer_release_action_plan_for_decision(decision)
    consumer_release_queue = build_consumer_release_queue_from_action_plan(
        consumer_release_action_plan=consumer_release_action_plan
    )
    consumer_release_priority = build_consumer_release_priority_from_queue(
        consumer_release_queue=consumer_release_queue
    )
    return build_consumer_release_window_from_priority(
        consumer_release_priority=consumer_release_priority
    )


@pytest.mark.parametrize(
    ("decision", "expected_consumer_release_schedule"),
    [
        pytest.param("GO", "backlog_schedule", id="go"),
        pytest.param("PAUSE", "guarded_schedule", id="pause"),
        pytest.param("REVIEW", "immediate_schedule", id="review"),
    ],
)
def test_consumer_release_schedule_from_window_matches_window(
    decision: RecommendationValue,
    expected_consumer_release_schedule: str,
) -> None:
    consumer_release_window = _build_consumer_release_window_for_decision(decision)
    consumer_release_schedule = build_consumer_release_schedule_from_window(
        consumer_release_window=consumer_release_window
    )

    for key, value in consumer_release_window.items():
        assert consumer_release_schedule[key] == value
    assert (
        consumer_release_schedule["consumer_release_schedule"]
        == expected_consumer_release_schedule
    )


@pytest.mark.parametrize(
    ("decision", "expected_consumer_release_readiness"),
    [
        pytest.param("GO", "not_ready", id="go"),
        pytest.param("PAUSE", "prepared", id="pause"),
        pytest.param("REVIEW", "ready", id="review"),
    ],
)
def test_consumer_release_readiness_from_schedule_matches_schedule(
    decision: RecommendationValue,
    expected_consumer_release_readiness: str,
) -> None:
    consumer_release_window = _build_consumer_release_window_for_decision(decision)
    consumer_release_schedule = build_consumer_release_schedule_from_window(
        consumer_release_window=consumer_release_window
    )
    consumer_release_readiness = build_consumer_release_readiness_from_schedule(
        consumer_release_schedule=consumer_release_schedule
    )

    for key, value in consumer_release_schedule.items():
        assert consumer_release_readiness[key] == value
    assert (
        consumer_release_readiness["consumer_release_readiness"]
        == expected_consumer_release_readiness
    )


@pytest.mark.parametrize(
    ("decision", "expected_consumer_release_authority"),
    [
        pytest.param("GO", "withhold", id="go"),
        pytest.param("PAUSE", "conditional_authority", id="pause"),
        pytest.param("REVIEW", "full_authority", id="review"),
    ],
)
def test_consumer_release_authority_from_readiness_matches_readiness(
    decision: RecommendationValue,
    expected_consumer_release_authority: str,
) -> None:
    consumer_release_window = _build_consumer_release_window_for_decision(decision)
    consumer_release_schedule = build_consumer_release_schedule_from_window(
        consumer_release_window=consumer_release_window
    )
    consumer_release_readiness = build_consumer_release_readiness_from_schedule(
        consumer_release_schedule=consumer_release_schedule
    )
    consumer_release_authority = build_consumer_release_authority_from_readiness(
        consumer_release_readiness=consumer_release_readiness
    )

    for key, value in consumer_release_readiness.items():
        assert consumer_release_authority[key] == value
    assert (
        consumer_release_authority["consumer_release_authority"]
        == expected_consumer_release_authority
    )


@pytest.mark.parametrize(
    ("decision", "expected_consumer_release_permission"),
    [
        pytest.param("GO", "not_permitted", id="go"),
        pytest.param("PAUSE", "conditionally_permitted", id="pause"),
        pytest.param("REVIEW", "permitted", id="review"),
    ],
)
def test_consumer_release_permission_from_authority_matches_authority(
    decision: RecommendationValue,
    expected_consumer_release_permission: str,
) -> None:
    consumer_release_window = _build_consumer_release_window_for_decision(decision)
    consumer_release_schedule = build_consumer_release_schedule_from_window(
        consumer_release_window=consumer_release_window
    )
    consumer_release_readiness = build_consumer_release_readiness_from_schedule(
        consumer_release_schedule=consumer_release_schedule
    )
    consumer_release_authority = build_consumer_release_authority_from_readiness(
        consumer_release_readiness=consumer_release_readiness
    )
    consumer_release_permission = build_consumer_release_permission_from_authority(
        consumer_release_authority=consumer_release_authority
    )

    for key, value in consumer_release_authority.items():
        assert consumer_release_permission[key] == value
    assert (
        consumer_release_permission["consumer_release_permission"]
        == expected_consumer_release_permission
    )


@pytest.mark.parametrize(
    ("decision", "expected_consumer_release_clearance"),
    [
        pytest.param("GO", "blocked", id="go"),
        pytest.param("PAUSE", "gated", id="pause"),
        pytest.param("REVIEW", "clear", id="review"),
    ],
)
def test_consumer_release_clearance_from_permission_matches_permission(
    decision: RecommendationValue,
    expected_consumer_release_clearance: str,
) -> None:
    consumer_release_window = _build_consumer_release_window_for_decision(decision)
    consumer_release_schedule = build_consumer_release_schedule_from_window(
        consumer_release_window=consumer_release_window
    )
    consumer_release_readiness = build_consumer_release_readiness_from_schedule(
        consumer_release_schedule=consumer_release_schedule
    )
    consumer_release_authority = build_consumer_release_authority_from_readiness(
        consumer_release_readiness=consumer_release_readiness
    )
    consumer_release_permission = build_consumer_release_permission_from_authority(
        consumer_release_authority=consumer_release_authority
    )
    consumer_release_clearance = build_consumer_release_clearance_from_permission(
        consumer_release_permission=consumer_release_permission
    )

    for key, value in consumer_release_permission.items():
        assert consumer_release_clearance[key] == value
    assert (
        consumer_release_clearance["consumer_release_clearance"]
        == expected_consumer_release_clearance
    )


def test_consumer_release_decision_raises_key_error_for_unknown_dispatch_clearance() -> None:
    with pytest.raises(KeyError):
        build_consumer_release_decision_from_dispatch_clearance(
            consumer_dispatch_clearance={
                "projected_activation_decision": {"recommendation": "GO"},
                "approval_record": {"human_approval_status": {"status": "approved"}},
                "receiver_readiness_classification": "ready",
                "receiver_handling_directive": "deliver",
                "receiver_action_label": "dispatch",
                "receiver_dispatch_intent": "send",
                "receiver_dispatch_mode": "active",
                "receiver_release_gate": "open",
                "receiver_progress_state": "in_progress",
                "receiver_progress_signal": "advance",
                "receiver_progress_outcome": "moving",
                "receiver_intervention_requirement": "none",
                "receiver_attention_level": "low",
                "receiver_notification_requirement": "none",
                "receiver_response_priority": "normal",
                "receiver_response_channel": "standard_channel",
                "receiver_response_route": "standard_route",
                "receiver_followup_requirement": "none",
                "consumer_decision_posture": "observe",
                "consumer_action_requirement": "no_action",
                "consumer_work_queue_assignment": "observation_queue",
                "consumer_processing_plan": "observe_only",
                "consumer_operator_requirement": "none",
                "consumer_assignment_lane": "self_service_lane",
                "consumer_service_tier": "self_service",
                "consumer_sla_class": "deferred",
                "consumer_response_window": "backlog_window",
                "consumer_timing_posture": "later",
                "consumer_scheduling_commitment": "backlog_commitment",
                "consumer_execution_readiness": "deferred_readiness",
                "consumer_dispatch_readiness": "parked",
                "consumer_dispatch_authority": "withhold",
                "consumer_dispatch_permission": "not_permitted",
                "consumer_dispatch_clearance": "unknown_dispatch_clearance",
            }
        )


def test_consumer_release_mode_raises_key_error_for_unknown_release_decision() -> None:
    with pytest.raises(KeyError):
        build_consumer_release_mode_from_release_decision(
            consumer_release_decision={
                "projected_activation_decision": {"recommendation": "GO"},
                "approval_record": {"human_approval_status": {"status": "approved"}},
                "receiver_readiness_classification": "ready",
                "receiver_handling_directive": "deliver",
                "receiver_action_label": "dispatch",
                "receiver_dispatch_intent": "send",
                "receiver_dispatch_mode": "active",
                "receiver_release_gate": "open",
                "receiver_progress_state": "in_progress",
                "receiver_progress_signal": "advance",
                "receiver_progress_outcome": "moving",
                "receiver_intervention_requirement": "none",
                "receiver_attention_level": "low",
                "receiver_notification_requirement": "none",
                "receiver_response_priority": "normal",
                "receiver_response_channel": "standard_channel",
                "receiver_response_route": "standard_route",
                "receiver_followup_requirement": "none",
                "consumer_decision_posture": "observe",
                "consumer_action_requirement": "no_action",
                "consumer_work_queue_assignment": "observation_queue",
                "consumer_processing_plan": "observe_only",
                "consumer_operator_requirement": "none",
                "consumer_assignment_lane": "self_service_lane",
                "consumer_service_tier": "self_service",
                "consumer_sla_class": "deferred",
                "consumer_response_window": "backlog_window",
                "consumer_timing_posture": "later",
                "consumer_scheduling_commitment": "backlog_commitment",
                "consumer_execution_readiness": "deferred_readiness",
                "consumer_dispatch_readiness": "parked",
                "consumer_dispatch_authority": "withhold",
                "consumer_dispatch_permission": "not_permitted",
                "consumer_dispatch_clearance": "blocked",
                "consumer_release_decision": "unknown_release_decision",
            }
        )


def test_consumer_release_execution_requirement_raises_key_error_for_unknown_release_mode() -> None:
    with pytest.raises(KeyError):
        build_consumer_release_execution_requirement_from_release_mode(
            consumer_release_mode={
                "projected_activation_decision": {"recommendation": "GO"},
                "approval_record": {"human_approval_status": {"status": "approved"}},
                "receiver_readiness_classification": "ready",
                "receiver_handling_directive": "deliver",
                "receiver_action_label": "dispatch",
                "receiver_dispatch_intent": "send",
                "receiver_dispatch_mode": "active",
                "receiver_release_gate": "open",
                "receiver_progress_state": "in_progress",
                "receiver_progress_signal": "advance",
                "receiver_progress_outcome": "moving",
                "receiver_intervention_requirement": "none",
                "receiver_attention_level": "low",
                "receiver_notification_requirement": "none",
                "receiver_response_priority": "normal",
                "receiver_response_channel": "standard_channel",
                "receiver_response_route": "standard_route",
                "receiver_followup_requirement": "none",
                "consumer_decision_posture": "observe",
                "consumer_action_requirement": "no_action",
                "consumer_work_queue_assignment": "observation_queue",
                "consumer_processing_plan": "observe_only",
                "consumer_operator_requirement": "none",
                "consumer_assignment_lane": "self_service_lane",
                "consumer_service_tier": "self_service",
                "consumer_sla_class": "deferred",
                "consumer_response_window": "backlog_window",
                "consumer_timing_posture": "later",
                "consumer_scheduling_commitment": "backlog_commitment",
                "consumer_execution_readiness": "deferred_readiness",
                "consumer_dispatch_readiness": "parked",
                "consumer_dispatch_authority": "withhold",
                "consumer_dispatch_permission": "not_permitted",
                "consumer_dispatch_clearance": "blocked",
                "consumer_release_decision": "hold_release",
                "consumer_release_mode": "unknown_release_mode",
            }
        )


def test_consumer_release_execution_lane_raises_key_error_for_unknown_requirement() -> None:
    with pytest.raises(KeyError):
        build_consumer_release_execution_lane_from_execution_requirement(
            consumer_release_execution_requirement={
                "projected_activation_decision": {"recommendation": "GO"},
                "approval_record": {"human_approval_status": {"status": "approved"}},
                "receiver_readiness_classification": "ready",
                "receiver_handling_directive": "deliver",
                "receiver_action_label": "dispatch",
                "receiver_dispatch_intent": "send",
                "receiver_dispatch_mode": "active",
                "receiver_release_gate": "open",
                "receiver_progress_state": "in_progress",
                "receiver_progress_signal": "advance",
                "receiver_progress_outcome": "moving",
                "receiver_intervention_requirement": "none",
                "receiver_attention_level": "low",
                "receiver_notification_requirement": "none",
                "receiver_response_priority": "normal",
                "receiver_response_channel": "standard_channel",
                "receiver_response_route": "standard_route",
                "receiver_followup_requirement": "none",
                "consumer_decision_posture": "observe",
                "consumer_action_requirement": "no_action",
                "consumer_work_queue_assignment": "observation_queue",
                "consumer_processing_plan": "observe_only",
                "consumer_operator_requirement": "none",
                "consumer_assignment_lane": "self_service_lane",
                "consumer_service_tier": "self_service",
                "consumer_sla_class": "deferred",
                "consumer_response_window": "backlog_window",
                "consumer_timing_posture": "later",
                "consumer_scheduling_commitment": "backlog_commitment",
                "consumer_execution_readiness": "deferred_readiness",
                "consumer_dispatch_readiness": "parked",
                "consumer_dispatch_authority": "withhold",
                "consumer_dispatch_permission": "not_permitted",
                "consumer_dispatch_clearance": "blocked",
                "consumer_release_decision": "hold_release",
                "consumer_release_mode": "hold_mode",
                "consumer_release_execution_requirement": (
                    "unknown_release_execution_requirement"
                ),
            }
        )


def test_consumer_release_handling_intent_raises_key_error_for_unknown_execution_lane() -> None:
    with pytest.raises(KeyError):
        build_consumer_release_handling_intent_from_execution_lane(
            consumer_release_execution_lane={
                "projected_activation_decision": {"recommendation": "GO"},
                "approval_record": {"human_approval_status": {"status": "approved"}},
                "receiver_readiness_classification": "ready",
                "receiver_handling_directive": "deliver",
                "receiver_action_label": "dispatch",
                "receiver_dispatch_intent": "send",
                "receiver_dispatch_mode": "active",
                "receiver_release_gate": "open",
                "receiver_progress_state": "in_progress",
                "receiver_progress_signal": "advance",
                "receiver_progress_outcome": "moving",
                "receiver_intervention_requirement": "none",
                "receiver_attention_level": "low",
                "receiver_notification_requirement": "none",
                "receiver_response_priority": "normal",
                "receiver_response_channel": "standard_channel",
                "receiver_response_route": "standard_route",
                "receiver_followup_requirement": "none",
                "consumer_decision_posture": "observe",
                "consumer_action_requirement": "no_action",
                "consumer_work_queue_assignment": "observation_queue",
                "consumer_processing_plan": "observe_only",
                "consumer_operator_requirement": "none",
                "consumer_assignment_lane": "self_service_lane",
                "consumer_service_tier": "self_service",
                "consumer_sla_class": "deferred",
                "consumer_response_window": "backlog_window",
                "consumer_timing_posture": "later",
                "consumer_scheduling_commitment": "backlog_commitment",
                "consumer_execution_readiness": "deferred_readiness",
                "consumer_dispatch_readiness": "parked",
                "consumer_dispatch_authority": "withhold",
                "consumer_dispatch_permission": "not_permitted",
                "consumer_dispatch_clearance": "blocked",
                "consumer_release_decision": "hold_release",
                "consumer_release_mode": "hold_mode",
                "consumer_release_execution_requirement": "do_not_execute",
                "consumer_release_execution_lane": "unknown_release_execution_lane",
            }
        )


def test_consumer_release_action_plan_raises_key_error_for_unknown_handling_intent() -> None:
    with pytest.raises(KeyError):
        build_consumer_release_action_plan_from_handling_intent(
            consumer_release_handling_intent={
                "projected_activation_decision": {"recommendation": "GO"},
                "approval_record": {"human_approval_status": {"status": "approved"}},
                "receiver_readiness_classification": "ready",
                "receiver_handling_directive": "deliver",
                "receiver_action_label": "dispatch",
                "receiver_dispatch_intent": "send",
                "receiver_dispatch_mode": "active",
                "receiver_release_gate": "open",
                "receiver_progress_state": "in_progress",
                "receiver_progress_signal": "advance",
                "receiver_progress_outcome": "moving",
                "receiver_intervention_requirement": "none",
                "receiver_attention_level": "low",
                "receiver_notification_requirement": "none",
                "receiver_response_priority": "normal",
                "receiver_response_channel": "standard_channel",
                "receiver_response_route": "standard_route",
                "receiver_followup_requirement": "none",
                "consumer_decision_posture": "observe",
                "consumer_action_requirement": "no_action",
                "consumer_work_queue_assignment": "observation_queue",
                "consumer_processing_plan": "observe_only",
                "consumer_operator_requirement": "none",
                "consumer_assignment_lane": "self_service_lane",
                "consumer_service_tier": "self_service",
                "consumer_sla_class": "deferred",
                "consumer_response_window": "backlog_window",
                "consumer_timing_posture": "later",
                "consumer_scheduling_commitment": "backlog_commitment",
                "consumer_execution_readiness": "deferred_readiness",
                "consumer_dispatch_readiness": "parked",
                "consumer_dispatch_authority": "withhold",
                "consumer_dispatch_permission": "not_permitted",
                "consumer_dispatch_clearance": "blocked",
                "consumer_release_decision": "hold_release",
                "consumer_release_mode": "hold_mode",
                "consumer_release_execution_requirement": "do_not_execute",
                "consumer_release_execution_lane": "blocked_lane",
                "consumer_release_handling_intent": "unknown_release_handling_intent",
            }
        )


def test_consumer_release_queue_raises_key_error_for_unknown_action_plan() -> None:
    consumer_release_action_plan = _build_consumer_release_action_plan_for_decision("GO")
    consumer_release_action_plan["consumer_release_action_plan"] = (
        "unknown_consumer_release_action_plan"
    )

    with pytest.raises(KeyError):
        build_consumer_release_queue_from_action_plan(
            consumer_release_action_plan=consumer_release_action_plan
        )


def test_consumer_release_priority_raises_key_error_for_unknown_release_queue() -> None:
    consumer_release_action_plan = _build_consumer_release_action_plan_for_decision("GO")
    consumer_release_queue = build_consumer_release_queue_from_action_plan(
        consumer_release_action_plan=consumer_release_action_plan
    )
    consumer_release_queue["consumer_release_queue"] = "unknown_consumer_release_queue"

    with pytest.raises(KeyError):
        build_consumer_release_priority_from_queue(
            consumer_release_queue=consumer_release_queue
        )


def test_consumer_release_window_raises_key_error_for_unknown_release_priority() -> None:
    consumer_release_action_plan = _build_consumer_release_action_plan_for_decision("GO")
    consumer_release_queue = build_consumer_release_queue_from_action_plan(
        consumer_release_action_plan=consumer_release_action_plan
    )
    consumer_release_priority = build_consumer_release_priority_from_queue(
        consumer_release_queue=consumer_release_queue
    )
    consumer_release_priority["consumer_release_priority"] = (
        "unknown_consumer_release_priority"
    )

    with pytest.raises(KeyError):
        build_consumer_release_window_from_priority(
            consumer_release_priority=consumer_release_priority
        )


def test_consumer_release_schedule_raises_key_error_for_unknown_release_window() -> None:
    consumer_release_window = _build_consumer_release_window_for_decision("GO")
    consumer_release_window["consumer_release_window"] = "unknown_consumer_release_window"

    with pytest.raises(KeyError):
        build_consumer_release_schedule_from_window(
            consumer_release_window=consumer_release_window
        )


def test_consumer_release_readiness_raises_key_error_for_unknown_release_schedule() -> None:
    consumer_release_window = _build_consumer_release_window_for_decision("GO")
    consumer_release_schedule = build_consumer_release_schedule_from_window(
        consumer_release_window=consumer_release_window
    )
    consumer_release_schedule["consumer_release_schedule"] = (
        "unknown_consumer_release_schedule"
    )

    with pytest.raises(KeyError):
        build_consumer_release_readiness_from_schedule(
            consumer_release_schedule=consumer_release_schedule
        )


def test_consumer_release_authority_raises_key_error_for_unknown_release_readiness() -> None:
    consumer_release_window = _build_consumer_release_window_for_decision("GO")
    consumer_release_schedule = build_consumer_release_schedule_from_window(
        consumer_release_window=consumer_release_window
    )
    consumer_release_readiness = build_consumer_release_readiness_from_schedule(
        consumer_release_schedule=consumer_release_schedule
    )
    consumer_release_readiness["consumer_release_readiness"] = (
        "unknown_consumer_release_readiness"
    )

    with pytest.raises(KeyError):
        build_consumer_release_authority_from_readiness(
            consumer_release_readiness=consumer_release_readiness
        )


def test_consumer_release_permission_raises_key_error_for_unknown_release_authority() -> None:
    consumer_release_window = _build_consumer_release_window_for_decision("GO")
    consumer_release_schedule = build_consumer_release_schedule_from_window(
        consumer_release_window=consumer_release_window
    )
    consumer_release_readiness = build_consumer_release_readiness_from_schedule(
        consumer_release_schedule=consumer_release_schedule
    )
    consumer_release_authority = build_consumer_release_authority_from_readiness(
        consumer_release_readiness=consumer_release_readiness
    )
    consumer_release_authority["consumer_release_authority"] = (
        "unknown_consumer_release_authority"
    )

    with pytest.raises(KeyError):
        build_consumer_release_permission_from_authority(
            consumer_release_authority=consumer_release_authority
        )


def test_consumer_release_clearance_raises_key_error_for_unknown_release_permission() -> None:
    consumer_release_window = _build_consumer_release_window_for_decision("GO")
    consumer_release_schedule = build_consumer_release_schedule_from_window(
        consumer_release_window=consumer_release_window
    )
    consumer_release_readiness = build_consumer_release_readiness_from_schedule(
        consumer_release_schedule=consumer_release_schedule
    )
    consumer_release_authority = build_consumer_release_authority_from_readiness(
        consumer_release_readiness=consumer_release_readiness
    )
    consumer_release_permission = build_consumer_release_permission_from_authority(
        consumer_release_authority=consumer_release_authority
    )
    consumer_release_permission["consumer_release_permission"] = (
        "unknown_consumer_release_permission"
    )

    with pytest.raises(KeyError):
        build_consumer_release_clearance_from_permission(
            consumer_release_permission=consumer_release_permission
        )


def test_consumer_dispatch_clearance_raises_key_error_for_unknown_dispatch_permission() -> None:
    with pytest.raises(KeyError):
        build_consumer_dispatch_clearance_from_permission(
            consumer_dispatch_permission={
                "projected_activation_decision": {"recommendation": "GO"},
                "approval_record": {"human_approval_status": {"status": "approved"}},
                "receiver_readiness_classification": "ready",
                "receiver_handling_directive": "deliver",
                "receiver_action_label": "dispatch",
                "receiver_dispatch_intent": "send",
                "receiver_dispatch_mode": "active",
                "receiver_release_gate": "open",
                "receiver_progress_state": "in_progress",
                "receiver_progress_signal": "advance",
                "receiver_progress_outcome": "moving",
                "receiver_intervention_requirement": "none",
                "receiver_attention_level": "low",
                "receiver_notification_requirement": "none",
                "receiver_response_priority": "normal",
                "receiver_response_channel": "standard_channel",
                "receiver_response_route": "standard_route",
                "receiver_followup_requirement": "none",
                "consumer_decision_posture": "observe",
                "consumer_action_requirement": "no_action",
                "consumer_work_queue_assignment": "observation_queue",
                "consumer_processing_plan": "observe_only",
                "consumer_operator_requirement": "none",
                "consumer_assignment_lane": "self_service_lane",
                "consumer_service_tier": "self_service",
                "consumer_sla_class": "deferred",
                "consumer_response_window": "backlog_window",
                "consumer_timing_posture": "later",
                "consumer_scheduling_commitment": "backlog_commitment",
                "consumer_execution_readiness": "deferred_readiness",
                "consumer_dispatch_readiness": "parked",
                "consumer_dispatch_authority": "withhold",
                "consumer_dispatch_permission": "unknown_dispatch_permission",
            }
        )


def test_consumer_dispatch_permission_raises_key_error_for_unknown_dispatch_authority() -> None:
    with pytest.raises(KeyError):
        build_consumer_dispatch_permission_from_authority(
            consumer_dispatch_authority={
                "projected_activation_decision": {"recommendation": "GO"},
                "approval_record": {"human_approval_status": {"status": "approved"}},
                "receiver_readiness_classification": "ready",
                "receiver_handling_directive": "deliver",
                "receiver_action_label": "dispatch",
                "receiver_dispatch_intent": "send",
                "receiver_dispatch_mode": "active",
                "receiver_release_gate": "open",
                "receiver_progress_state": "in_progress",
                "receiver_progress_signal": "advance",
                "receiver_progress_outcome": "moving",
                "receiver_intervention_requirement": "none",
                "receiver_attention_level": "low",
                "receiver_notification_requirement": "none",
                "receiver_response_priority": "normal",
                "receiver_response_channel": "standard_channel",
                "receiver_response_route": "standard_route",
                "receiver_followup_requirement": "none",
                "consumer_decision_posture": "observe",
                "consumer_action_requirement": "no_action",
                "consumer_work_queue_assignment": "observation_queue",
                "consumer_processing_plan": "observe_only",
                "consumer_operator_requirement": "none",
                "consumer_assignment_lane": "self_service_lane",
                "consumer_service_tier": "self_service",
                "consumer_sla_class": "deferred",
                "consumer_response_window": "backlog_window",
                "consumer_timing_posture": "later",
                "consumer_scheduling_commitment": "backlog_commitment",
                "consumer_execution_readiness": "deferred_readiness",
                "consumer_dispatch_readiness": "parked",
                "consumer_dispatch_authority": "unknown_dispatch_authority",
            }
        )


def test_consumer_dispatch_authority_raises_key_error_for_unknown_dispatch_readiness() -> None:
    with pytest.raises(KeyError):
        build_consumer_dispatch_authority_from_readiness(
            consumer_dispatch_readiness={
                "projected_activation_decision": {"recommendation": "GO"},
                "approval_record": {"human_approval_status": {"status": "approved"}},
                "receiver_readiness_classification": "ready",
                "receiver_handling_directive": "deliver",
                "receiver_action_label": "dispatch",
                "receiver_dispatch_intent": "send",
                "receiver_dispatch_mode": "active",
                "receiver_release_gate": "open",
                "receiver_progress_state": "in_progress",
                "receiver_progress_signal": "advance",
                "receiver_progress_outcome": "moving",
                "receiver_intervention_requirement": "none",
                "receiver_attention_level": "low",
                "receiver_notification_requirement": "none",
                "receiver_response_priority": "normal",
                "receiver_response_channel": "standard_channel",
                "receiver_response_route": "standard_route",
                "receiver_followup_requirement": "none",
                "consumer_decision_posture": "observe",
                "consumer_action_requirement": "no_action",
                "consumer_work_queue_assignment": "observation_queue",
                "consumer_processing_plan": "observe_only",
                "consumer_operator_requirement": "none",
                "consumer_assignment_lane": "self_service_lane",
                "consumer_service_tier": "self_service",
                "consumer_sla_class": "deferred",
                "consumer_response_window": "backlog_window",
                "consumer_timing_posture": "later",
                "consumer_scheduling_commitment": "backlog_commitment",
                "consumer_execution_readiness": "deferred_readiness",
                "consumer_dispatch_readiness": "unknown_dispatch_readiness",
            }
        )


def test_consumer_dispatch_readiness_raises_key_error_for_unknown_execution_readiness() -> None:
    with pytest.raises(KeyError):
        build_consumer_dispatch_readiness_from_execution_readiness(
            consumer_execution_readiness={
                "projected_activation_decision": {"recommendation": "GO"},
                "approval_record": {"human_approval_status": {"status": "approved"}},
                "receiver_readiness_classification": "ready",
                "receiver_handling_directive": "deliver",
                "receiver_action_label": "dispatch",
                "receiver_dispatch_intent": "send",
                "receiver_dispatch_mode": "active",
                "receiver_release_gate": "open",
                "receiver_progress_state": "in_progress",
                "receiver_progress_signal": "advance",
                "receiver_progress_outcome": "moving",
                "receiver_intervention_requirement": "none",
                "receiver_attention_level": "low",
                "receiver_notification_requirement": "none",
                "receiver_response_priority": "normal",
                "receiver_response_channel": "standard_channel",
                "receiver_response_route": "standard_route",
                "receiver_followup_requirement": "none",
                "consumer_decision_posture": "observe",
                "consumer_action_requirement": "no_action",
                "consumer_work_queue_assignment": "observation_queue",
                "consumer_processing_plan": "observe_only",
                "consumer_operator_requirement": "none",
                "consumer_assignment_lane": "self_service_lane",
                "consumer_service_tier": "self_service",
                "consumer_sla_class": "deferred",
                "consumer_response_window": "backlog_window",
                "consumer_timing_posture": "later",
                "consumer_scheduling_commitment": "backlog_commitment",
                "consumer_execution_readiness": "unknown_execution_readiness",
            }
        )


def test_consumer_execution_readiness_raises_key_error_for_unknown_scheduling_commitment() -> None:
    with pytest.raises(KeyError):
        build_consumer_execution_readiness_from_scheduling_commitment(
            consumer_scheduling_commitment={
                "projected_activation_decision": {"recommendation": "GO"},
                "approval_record": {"human_approval_status": {"status": "approved"}},
                "receiver_readiness_classification": "ready",
                "receiver_handling_directive": "deliver",
                "receiver_action_label": "dispatch",
                "receiver_dispatch_intent": "send",
                "receiver_dispatch_mode": "active",
                "receiver_release_gate": "open",
                "receiver_progress_state": "in_progress",
                "receiver_progress_signal": "advance",
                "receiver_progress_outcome": "moving",
                "receiver_intervention_requirement": "none",
                "receiver_attention_level": "low",
                "receiver_notification_requirement": "none",
                "receiver_response_priority": "normal",
                "receiver_response_channel": "standard_channel",
                "receiver_response_route": "standard_route",
                "receiver_followup_requirement": "none",
                "consumer_decision_posture": "observe",
                "consumer_action_requirement": "no_action",
                "consumer_work_queue_assignment": "observation_queue",
                "consumer_processing_plan": "observe_only",
                "consumer_operator_requirement": "none",
                "consumer_assignment_lane": "self_service_lane",
                "consumer_service_tier": "self_service",
                "consumer_sla_class": "deferred",
                "consumer_response_window": "backlog_window",
                "consumer_timing_posture": "later",
                "consumer_scheduling_commitment": "unknown_scheduling_commitment",
            }
        )


def test_consumer_scheduling_commitment_raises_key_error_for_unknown_timing_posture() -> None:
    with pytest.raises(KeyError):
        build_consumer_scheduling_commitment_from_timing_posture(
            consumer_timing_posture={
                "projected_activation_decision": {"recommendation": "GO"},
                "approval_record": {"human_approval_status": {"status": "approved"}},
                "receiver_readiness_classification": "ready",
                "receiver_handling_directive": "deliver",
                "receiver_action_label": "dispatch",
                "receiver_dispatch_intent": "send",
                "receiver_dispatch_mode": "active",
                "receiver_release_gate": "open",
                "receiver_progress_state": "in_progress",
                "receiver_progress_signal": "advance",
                "receiver_progress_outcome": "moving",
                "receiver_intervention_requirement": "none",
                "receiver_attention_level": "low",
                "receiver_notification_requirement": "none",
                "receiver_response_priority": "normal",
                "receiver_response_channel": "standard_channel",
                "receiver_response_route": "standard_route",
                "receiver_followup_requirement": "none",
                "consumer_decision_posture": "observe",
                "consumer_action_requirement": "no_action",
                "consumer_work_queue_assignment": "observation_queue",
                "consumer_processing_plan": "observe_only",
                "consumer_operator_requirement": "none",
                "consumer_assignment_lane": "self_service_lane",
                "consumer_service_tier": "self_service",
                "consumer_sla_class": "deferred",
                "consumer_response_window": "backlog_window",
                "consumer_timing_posture": "unknown_timing_posture",
            }
        )


def test_consumer_timing_posture_raises_key_error_for_unknown_response_window() -> None:
    with pytest.raises(KeyError):
        build_consumer_timing_posture_from_response_window(
            consumer_response_window={
                "projected_activation_decision": {"recommendation": "GO"},
                "approval_record": {"human_approval_status": {"status": "approved"}},
                "receiver_readiness_classification": "ready",
                "receiver_handling_directive": "deliver",
                "receiver_action_label": "dispatch",
                "receiver_dispatch_intent": "send",
                "receiver_dispatch_mode": "active",
                "receiver_release_gate": "open",
                "receiver_progress_state": "in_progress",
                "receiver_progress_signal": "advance",
                "receiver_progress_outcome": "moving",
                "receiver_intervention_requirement": "none",
                "receiver_attention_level": "low",
                "receiver_notification_requirement": "none",
                "receiver_response_priority": "normal",
                "receiver_response_channel": "standard_channel",
                "receiver_response_route": "standard_route",
                "receiver_followup_requirement": "none",
                "consumer_decision_posture": "observe",
                "consumer_action_requirement": "no_action",
                "consumer_work_queue_assignment": "observation_queue",
                "consumer_processing_plan": "observe_only",
                "consumer_operator_requirement": "none",
                "consumer_assignment_lane": "self_service_lane",
                "consumer_service_tier": "self_service",
                "consumer_sla_class": "deferred",
                "consumer_response_window": "unknown_response_window",
            }
        )


def test_consumer_response_window_raises_key_error_for_unknown_sla_class() -> None:
    with pytest.raises(KeyError):
        build_consumer_response_window_from_sla_class(
            consumer_sla_class={
                "projected_activation_decision": {"recommendation": "GO"},
                "approval_record": {"human_approval_status": {"status": "approved"}},
                "receiver_readiness_classification": "ready",
                "receiver_handling_directive": "deliver",
                "receiver_action_label": "dispatch",
                "receiver_dispatch_intent": "send",
                "receiver_dispatch_mode": "active",
                "receiver_release_gate": "open",
                "receiver_progress_state": "in_progress",
                "receiver_progress_signal": "advance",
                "receiver_progress_outcome": "moving",
                "receiver_intervention_requirement": "none",
                "receiver_attention_level": "low",
                "receiver_notification_requirement": "none",
                "receiver_response_priority": "normal",
                "receiver_response_channel": "standard_channel",
                "receiver_response_route": "standard_route",
                "receiver_followup_requirement": "none",
                "consumer_decision_posture": "observe",
                "consumer_action_requirement": "no_action",
                "consumer_work_queue_assignment": "observation_queue",
                "consumer_processing_plan": "observe_only",
                "consumer_operator_requirement": "none",
                "consumer_assignment_lane": "self_service_lane",
                "consumer_service_tier": "self_service",
                "consumer_sla_class": "unknown_sla_class",
            }
        )


def test_consumer_sla_class_raises_key_error_for_unknown_service_tier() -> None:
    with pytest.raises(KeyError):
        build_consumer_sla_class_from_service_tier(
            consumer_service_tier={
                "projected_activation_decision": {"recommendation": "GO"},
                "approval_record": {"human_approval_status": {"status": "approved"}},
                "receiver_readiness_classification": "ready",
                "receiver_handling_directive": "deliver",
                "receiver_action_label": "dispatch",
                "receiver_dispatch_intent": "send",
                "receiver_dispatch_mode": "active",
                "receiver_release_gate": "open",
                "receiver_progress_state": "in_progress",
                "receiver_progress_signal": "advance",
                "receiver_progress_outcome": "moving",
                "receiver_intervention_requirement": "none",
                "receiver_attention_level": "low",
                "receiver_notification_requirement": "none",
                "receiver_response_priority": "normal",
                "receiver_response_channel": "standard_channel",
                "receiver_response_route": "standard_route",
                "receiver_followup_requirement": "none",
                "consumer_decision_posture": "observe",
                "consumer_action_requirement": "no_action",
                "consumer_work_queue_assignment": "observation_queue",
                "consumer_processing_plan": "observe_only",
                "consumer_operator_requirement": "none",
                "consumer_assignment_lane": "self_service_lane",
                "consumer_service_tier": "unknown_service_tier",
            }
        )


def test_consumer_service_tier_raises_key_error_for_unknown_assignment_lane() -> None:
    with pytest.raises(KeyError):
        build_consumer_service_tier_from_assignment_lane(
            consumer_assignment_lane={
                "projected_activation_decision": {"recommendation": "GO"},
                "approval_record": {"human_approval_status": {"status": "approved"}},
                "receiver_readiness_classification": "ready",
                "receiver_handling_directive": "deliver",
                "receiver_action_label": "dispatch",
                "receiver_dispatch_intent": "send",
                "receiver_dispatch_mode": "active",
                "receiver_release_gate": "open",
                "receiver_progress_state": "in_progress",
                "receiver_progress_signal": "advance",
                "receiver_progress_outcome": "moving",
                "receiver_intervention_requirement": "none",
                "receiver_attention_level": "low",
                "receiver_notification_requirement": "none",
                "receiver_response_priority": "normal",
                "receiver_response_channel": "standard_channel",
                "receiver_response_route": "standard_route",
                "receiver_followup_requirement": "none",
                "consumer_decision_posture": "observe",
                "consumer_action_requirement": "no_action",
                "consumer_work_queue_assignment": "observation_queue",
                "consumer_processing_plan": "observe_only",
                "consumer_operator_requirement": "none",
                "consumer_assignment_lane": "unknown_assignment_lane",
            }
        )


def test_consumer_assignment_lane_raises_key_error_for_unknown_operator_requirement() -> None:
    with pytest.raises(KeyError):
        build_consumer_assignment_lane_from_operator_requirement(
            consumer_operator_requirement={
                "projected_activation_decision": {"recommendation": "GO"},
                "approval_record": {"human_approval_status": {"status": "approved"}},
                "receiver_readiness_classification": "ready",
                "receiver_handling_directive": "deliver",
                "receiver_action_label": "dispatch",
                "receiver_dispatch_intent": "send",
                "receiver_dispatch_mode": "active",
                "receiver_release_gate": "open",
                "receiver_progress_state": "in_progress",
                "receiver_progress_signal": "advance",
                "receiver_progress_outcome": "moving",
                "receiver_intervention_requirement": "none",
                "receiver_attention_level": "low",
                "receiver_notification_requirement": "none",
                "receiver_response_priority": "normal",
                "receiver_response_channel": "standard_channel",
                "receiver_response_route": "standard_route",
                "receiver_followup_requirement": "none",
                "consumer_decision_posture": "observe",
                "consumer_action_requirement": "no_action",
                "consumer_work_queue_assignment": "observation_queue",
                "consumer_processing_plan": "observe_only",
                "consumer_operator_requirement": "unknown_operator_requirement",
            }
        )


def test_consumer_operator_requirement_raises_key_error_for_unknown_processing_plan() -> None:
    with pytest.raises(KeyError):
        build_consumer_operator_requirement_from_processing_plan(
            consumer_processing_plan={
                "projected_activation_decision": {"recommendation": "GO"},
                "approval_record": {"human_approval_status": {"status": "approved"}},
                "receiver_readiness_classification": "ready",
                "receiver_handling_directive": "deliver",
                "receiver_action_label": "dispatch",
                "receiver_dispatch_intent": "send",
                "receiver_dispatch_mode": "active",
                "receiver_release_gate": "open",
                "receiver_progress_state": "in_progress",
                "receiver_progress_signal": "advance",
                "receiver_progress_outcome": "moving",
                "receiver_intervention_requirement": "none",
                "receiver_attention_level": "low",
                "receiver_notification_requirement": "none",
                "receiver_response_priority": "normal",
                "receiver_response_channel": "standard_channel",
                "receiver_response_route": "standard_route",
                "receiver_followup_requirement": "none",
                "consumer_decision_posture": "observe",
                "consumer_action_requirement": "no_action",
                "consumer_work_queue_assignment": "observation_queue",
                "consumer_processing_plan": "unknown_processing_plan",
            }
        )


def test_consumer_processing_plan_raises_key_error_for_unknown_work_queue_assignment() -> None:
    with pytest.raises(KeyError):
        build_consumer_processing_plan_from_work_queue_assignment(
            consumer_work_queue_assignment={
                "projected_activation_decision": {"recommendation": "GO"},
                "approval_record": {"human_approval_status": {"status": "approved"}},
                "receiver_readiness_classification": "ready",
                "receiver_handling_directive": "deliver",
                "receiver_action_label": "dispatch",
                "receiver_dispatch_intent": "send",
                "receiver_dispatch_mode": "active",
                "receiver_release_gate": "open",
                "receiver_progress_state": "in_progress",
                "receiver_progress_signal": "advance",
                "receiver_progress_outcome": "moving",
                "receiver_intervention_requirement": "none",
                "receiver_attention_level": "low",
                "receiver_notification_requirement": "none",
                "receiver_response_priority": "normal",
                "receiver_response_channel": "standard_channel",
                "receiver_response_route": "standard_route",
                "receiver_followup_requirement": "none",
                "consumer_decision_posture": "observe",
                "consumer_action_requirement": "no_action",
                "consumer_work_queue_assignment": "unknown_work_queue_assignment",
            }
        )


def test_consumer_work_queue_assignment_raises_key_error_for_unknown_action_requirement() -> None:
    with pytest.raises(KeyError):
        build_consumer_work_queue_assignment_from_action_requirement(
            consumer_action_requirement={
                "projected_activation_decision": {"recommendation": "GO"},
                "approval_record": {"human_approval_status": {"status": "approved"}},
                "receiver_readiness_classification": "ready",
                "receiver_handling_directive": "deliver",
                "receiver_action_label": "dispatch",
                "receiver_dispatch_intent": "send",
                "receiver_dispatch_mode": "active",
                "receiver_release_gate": "open",
                "receiver_progress_state": "in_progress",
                "receiver_progress_signal": "advance",
                "receiver_progress_outcome": "moving",
                "receiver_intervention_requirement": "none",
                "receiver_attention_level": "low",
                "receiver_notification_requirement": "none",
                "receiver_response_priority": "normal",
                "receiver_response_channel": "standard_channel",
                "receiver_response_route": "standard_route",
                "receiver_followup_requirement": "none",
                "consumer_decision_posture": "observe",
                "consumer_action_requirement": "unknown_action_requirement",
            }
        )


def test_consumer_action_requirement_raises_key_error_for_unknown_decision_posture() -> None:
    with pytest.raises(KeyError):
        build_consumer_action_requirement_from_posture(
            consumer_decision_posture={
                "projected_activation_decision": {"recommendation": "GO"},
                "approval_record": {"human_approval_status": {"status": "approved"}},
                "receiver_readiness_classification": "ready",
                "receiver_handling_directive": "deliver",
                "receiver_action_label": "dispatch",
                "receiver_dispatch_intent": "send",
                "receiver_dispatch_mode": "active",
                "receiver_release_gate": "open",
                "receiver_progress_state": "in_progress",
                "receiver_progress_signal": "advance",
                "receiver_progress_outcome": "moving",
                "receiver_intervention_requirement": "none",
                "receiver_attention_level": "low",
                "receiver_notification_requirement": "none",
                "receiver_response_priority": "normal",
                "receiver_response_channel": "standard_channel",
                "receiver_response_route": "standard_route",
                "receiver_followup_requirement": "none",
                "consumer_decision_posture": "unknown_decision_posture",
            }
        )


def test_consumer_decision_posture_raises_key_error_for_unknown_followup_requirement() -> None:
    with pytest.raises(KeyError):
        build_consumer_decision_posture_from_surface(
            consumer_decision_surface={
                "projected_activation_decision": {"recommendation": "GO"},
                "approval_record": {"human_approval_status": {"status": "approved"}},
                "receiver_readiness_classification": "ready",
                "receiver_handling_directive": "deliver",
                "receiver_action_label": "dispatch",
                "receiver_dispatch_intent": "send",
                "receiver_dispatch_mode": "active",
                "receiver_release_gate": "open",
                "receiver_progress_state": "in_progress",
                "receiver_progress_signal": "advance",
                "receiver_progress_outcome": "moving",
                "receiver_intervention_requirement": "none",
                "receiver_attention_level": "low",
                "receiver_notification_requirement": "none",
                "receiver_response_priority": "normal",
                "receiver_response_channel": "standard_channel",
                "receiver_response_route": "standard_route",
                "receiver_followup_requirement": "unknown_followup_requirement",
            }
        )


def test_receiver_readiness_classification_raises_key_error_for_unknown_recommendation() -> None:
    with pytest.raises(KeyError):
        build_consumer_receiver_readiness_classification_from_manifest(
            consumer_receiver_delivery_manifest={
                "projected_activation_decision": type(
                    "ProjectedActivationDecisionStub",
                    (),
                    {"recommendation": "unknown_recommendation"},
                )(),
                "approval_record": {"human_approval_status": {"status": "approved"}},
            }
        )


def test_receiver_handling_directive_unknown_readiness_raises_key_error() -> None:
    with pytest.raises(KeyError):
        build_consumer_receiver_handling_directive_from_classification(
            consumer_receiver_readiness_classification={
                "projected_activation_decision": {"recommendation": "GO"},
                "approval_record": {"human_approval_status": {"status": "approved"}},
                "receiver_readiness_classification": "unknown_readiness_classification",
            }
        )


def test_receiver_action_label_raises_key_error_for_unknown_handling_directive() -> None:
    with pytest.raises(KeyError):
        build_consumer_receiver_action_label_from_directive(
            consumer_receiver_handling_directive={
                "projected_activation_decision": {"recommendation": "GO"},
                "approval_record": {"human_approval_status": {"status": "approved"}},
                "receiver_readiness_classification": "ready",
                "receiver_handling_directive": "unknown_handling_directive",
            }
        )


def test_receiver_dispatch_intent_raises_key_error_for_unknown_action_label() -> None:
    with pytest.raises(KeyError):
        build_consumer_receiver_dispatch_intent_from_action_label(
            consumer_receiver_action_label={
                "projected_activation_decision": {"recommendation": "GO"},
                "approval_record": {"human_approval_status": {"status": "approved"}},
                "receiver_readiness_classification": "ready",
                "receiver_handling_directive": "deliver",
                "receiver_action_label": "unknown_action_label",
            }
        )


def test_receiver_dispatch_mode_raises_key_error_for_unknown_dispatch_intent() -> None:
    with pytest.raises(KeyError):
        build_consumer_receiver_dispatch_mode_from_intent(
            consumer_receiver_dispatch_intent={
                "projected_activation_decision": {"recommendation": "GO"},
                "approval_record": {"human_approval_status": {"status": "approved"}},
                "receiver_readiness_classification": "ready",
                "receiver_handling_directive": "deliver",
                "receiver_action_label": "dispatch",
                "receiver_dispatch_intent": "unknown_dispatch_intent",
            }
        )


def test_receiver_release_gate_raises_key_error_for_unknown_dispatch_mode() -> None:
    with pytest.raises(KeyError):
        build_consumer_receiver_release_gate_from_dispatch_mode(
            consumer_receiver_dispatch_mode={
                "projected_activation_decision": {"recommendation": "GO"},
                "approval_record": {"human_approval_status": {"status": "approved"}},
                "receiver_readiness_classification": "ready",
                "receiver_handling_directive": "deliver",
                "receiver_action_label": "dispatch",
                "receiver_dispatch_intent": "send",
                "receiver_dispatch_mode": "unknown_dispatch_mode",
            }
        )


def test_receiver_progress_state_raises_key_error_for_unknown_release_gate() -> None:
    with pytest.raises(KeyError):
        build_consumer_receiver_progress_state_from_release_gate(
            consumer_receiver_release_gate={
                "projected_activation_decision": {"recommendation": "GO"},
                "approval_record": {"human_approval_status": {"status": "approved"}},
                "receiver_readiness_classification": "ready",
                "receiver_handling_directive": "deliver",
                "receiver_action_label": "dispatch",
                "receiver_dispatch_intent": "send",
                "receiver_dispatch_mode": "active",
                "receiver_release_gate": "unknown_release_gate",
            }
        )


def test_receiver_progress_signal_raises_key_error_for_unknown_progress_state() -> None:
    with pytest.raises(KeyError):
        build_consumer_receiver_progress_signal_from_state(
            consumer_receiver_progress_state={
                "projected_activation_decision": {"recommendation": "GO"},
                "approval_record": {"human_approval_status": {"status": "approved"}},
                "receiver_readiness_classification": "ready",
                "receiver_handling_directive": "deliver",
                "receiver_action_label": "dispatch",
                "receiver_dispatch_intent": "send",
                "receiver_dispatch_mode": "active",
                "receiver_release_gate": "open",
                "receiver_progress_state": "unknown_progress_state",
            }
        )


def test_receiver_progress_outcome_raises_key_error_for_unknown_progress_signal() -> None:
    with pytest.raises(KeyError):
        build_consumer_receiver_progress_outcome_from_signal(
            consumer_receiver_progress_signal={
                "projected_activation_decision": {"recommendation": "GO"},
                "approval_record": {"human_approval_status": {"status": "approved"}},
                "receiver_readiness_classification": "ready",
                "receiver_handling_directive": "deliver",
                "receiver_action_label": "dispatch",
                "receiver_dispatch_intent": "send",
                "receiver_dispatch_mode": "active",
                "receiver_release_gate": "open",
                "receiver_progress_state": "in_progress",
                "receiver_progress_signal": "unknown_progress_signal",
            }
        )


def test_receiver_intervention_requirement_raises_key_error_for_unknown_progress_outcome() -> None:
    with pytest.raises(KeyError):
        build_consumer_receiver_intervention_requirement_from_progress_outcome(
            consumer_receiver_progress_outcome={
                "projected_activation_decision": {"recommendation": "GO"},
                "approval_record": {"human_approval_status": {"status": "approved"}},
                "receiver_readiness_classification": "ready",
                "receiver_handling_directive": "deliver",
                "receiver_action_label": "dispatch",
                "receiver_dispatch_intent": "send",
                "receiver_dispatch_mode": "active",
                "receiver_release_gate": "open",
                "receiver_progress_state": "in_progress",
                "receiver_progress_signal": "advance",
                "receiver_progress_outcome": "unknown_progress_outcome",
            }
        )


def test_response_route_raises_key_error_for_unknown_response_channel() -> None:
    with pytest.raises(KeyError):
        build_consumer_receiver_response_route_from_channel(
            consumer_receiver_response_channel={
                "projected_activation_decision": {"recommendation": "GO"},
                "approval_record": {"human_approval_status": {"status": "approved"}},
                "receiver_readiness_classification": "ready",
                "receiver_handling_directive": "deliver",
                "receiver_action_label": "dispatch",
                "receiver_dispatch_intent": "send",
                "receiver_dispatch_mode": "active",
                "receiver_release_gate": "open",
                "receiver_progress_state": "in_progress",
                "receiver_progress_signal": "advance",
                "receiver_progress_outcome": "moving",
                "receiver_intervention_requirement": "none",
                "receiver_attention_level": "low",
                "receiver_notification_requirement": "none",
                "receiver_response_priority": "normal",
                "receiver_response_channel": "unknown_response_channel",
            }
        )


def test_followup_requirement_raises_key_error_for_unknown_response_route() -> None:
    with pytest.raises(KeyError):
        build_consumer_receiver_followup_requirement_from_response_route(
            consumer_receiver_response_route={
                "projected_activation_decision": {"recommendation": "GO"},
                "approval_record": {"human_approval_status": {"status": "approved"}},
                "receiver_readiness_classification": "ready",
                "receiver_handling_directive": "deliver",
                "receiver_action_label": "dispatch",
                "receiver_dispatch_intent": "send",
                "receiver_dispatch_mode": "active",
                "receiver_release_gate": "open",
                "receiver_progress_state": "in_progress",
                "receiver_progress_signal": "advance",
                "receiver_progress_outcome": "moving",
                "receiver_intervention_requirement": "none",
                "receiver_attention_level": "low",
                "receiver_notification_requirement": "none",
                "receiver_response_priority": "normal",
                "receiver_response_channel": "standard_channel",
                "receiver_response_route": "unknown_response_route",
            }
        )


def test_response_priority_raises_key_error_for_unknown_notification_requirement() -> None:
    with pytest.raises(KeyError):
        build_consumer_receiver_response_priority_from_notification_requirement(
            consumer_receiver_notification_requirement={
                "projected_activation_decision": {"recommendation": "GO"},
                "approval_record": {"human_approval_status": {"status": "approved"}},
                "receiver_readiness_classification": "ready",
                "receiver_handling_directive": "deliver",
                "receiver_action_label": "dispatch",
                "receiver_dispatch_intent": "send",
                "receiver_dispatch_mode": "active",
                "receiver_release_gate": "open",
                "receiver_progress_state": "in_progress",
                "receiver_progress_signal": "advance",
                "receiver_progress_outcome": "moving",
                "receiver_intervention_requirement": "none",
                "receiver_attention_level": "low",
                "receiver_notification_requirement": "unknown_notification_requirement",
            }
        )


def test_response_channel_raises_key_error_for_unknown_response_priority() -> None:
    with pytest.raises(KeyError):
        build_consumer_receiver_response_channel_from_priority(
            consumer_receiver_response_priority={
                "projected_activation_decision": {"recommendation": "GO"},
                "approval_record": {"human_approval_status": {"status": "approved"}},
                "receiver_readiness_classification": "ready",
                "receiver_handling_directive": "deliver",
                "receiver_action_label": "dispatch",
                "receiver_dispatch_intent": "send",
                "receiver_dispatch_mode": "active",
                "receiver_release_gate": "open",
                "receiver_progress_state": "in_progress",
                "receiver_progress_signal": "advance",
                "receiver_progress_outcome": "moving",
                "receiver_intervention_requirement": "none",
                "receiver_attention_level": "low",
                "receiver_notification_requirement": "none",
                "receiver_response_priority": "unknown_response_priority",
            }
        )


def test_notification_requirement_raises_key_error_for_unknown_attention_level() -> None:
    with pytest.raises(KeyError):
        build_consumer_receiver_notification_requirement_from_attention_level(
            consumer_receiver_attention_level={
                "projected_activation_decision": {"recommendation": "GO"},
                "approval_record": {"human_approval_status": {"status": "approved"}},
                "receiver_readiness_classification": "ready",
                "receiver_handling_directive": "deliver",
                "receiver_action_label": "dispatch",
                "receiver_dispatch_intent": "send",
                "receiver_dispatch_mode": "active",
                "receiver_release_gate": "open",
                "receiver_progress_state": "in_progress",
                "receiver_progress_signal": "advance",
                "receiver_progress_outcome": "moving",
                "receiver_intervention_requirement": "none",
                "receiver_attention_level": "unknown_attention_level",
            }
        )


def test_attention_level_raises_key_error_for_unknown_intervention_requirement() -> None:
    with pytest.raises(KeyError):
        build_consumer_receiver_attention_level_from_intervention_requirement(
            consumer_receiver_intervention_requirement={
                "projected_activation_decision": {"recommendation": "GO"},
                "approval_record": {"human_approval_status": {"status": "approved"}},
                "receiver_readiness_classification": "ready",
                "receiver_handling_directive": "deliver",
                "receiver_action_label": "dispatch",
                "receiver_dispatch_intent": "send",
                "receiver_dispatch_mode": "active",
                "receiver_release_gate": "open",
                "receiver_progress_state": "in_progress",
                "receiver_progress_signal": "advance",
                "receiver_progress_outcome": "moving",
                "receiver_intervention_requirement": "unknown_requirement",
            }
        )


def test_build_dry_run_artifact_bundle_requires_projected_activation_decision() -> None:
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=(
                "Low-risk docs-only change for artifact bundle negative boundary validation."
            ),
            changed_areas={"docs"},
        )
    )
    result_without_projection = replace(result, projected_activation_decision=None)

    with pytest.raises(
        ValueError,
        match="DryRunOrchestrationResult must include projected_activation_decision.",
    ):
        build_dry_run_artifact_bundle(
            orchestration_result=result_without_projection,
            activation_review_item_id="activation_review_artifact_bundle_missing_projection_1",
        )


def test_build_dry_run_handoff_envelope_from_result_propagates_bundle_value_error() -> None:
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=(
                "Low-risk docs-only change for handoff envelope negative boundary validation."
            ),
            changed_areas={"docs"},
        )
    )
    result_without_projection = replace(result, projected_activation_decision=None)

    with pytest.raises(
        ValueError,
        match="DryRunOrchestrationResult must include projected_activation_decision.",
    ):
        build_dry_run_handoff_envelope_from_result(
            orchestration_result=result_without_projection,
            activation_review_item_id="activation_review_handoff_missing_projection_1",
        )


def test_build_dry_run_artifact_bundle_allows_empty_activation_review_item_id() -> None:
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=(
                "Low-risk docs-only change for activation_review_item_id boundary validation."
            ),
            changed_areas={"docs"},
        )
    )

    bundle = build_dry_run_artifact_bundle(
        orchestration_result=result,
        activation_review_item_id="",
    )

    assert bundle["approval_record"]["activation_review_item_id"] == ""


def test_builder_kwargs_omit_reviewer_fields_without_management_decision() -> None:
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request="Low-risk docs-only change for helper fallback shape validation.",
            changed_areas={"docs"},
        )
    )
    projected = result.projected_activation_decision
    assert projected is not None

    builder_kwargs = build_approval_record_builder_kwargs_from_projection(
        projected_activation_decision=projected,
        activation_review_item_id="activation_review_fallback_shape_1",
        management_decision=None,
        related_project_id="project_001",
    )

    assert (
        builder_kwargs["projected_activation_decision"] is projected
    )
    assert builder_kwargs["activation_review_item_id"] == "activation_review_fallback_shape_1"
    assert builder_kwargs["related_project_id"] == "project_001"
    assert "reviewer_id" not in builder_kwargs
    assert "reviewer_type" not in builder_kwargs
    assert "rationale" not in builder_kwargs


@pytest.mark.parametrize(
    ("activation_review_item_id", "pass_through_kwargs", "expected_pairs"),
    PASS_THROUGH_FALLBACK_CASES,
)
def test_builder_kwargs_preserve_pass_through_fields_without_management_decision(
    activation_review_item_id: str,
    pass_through_kwargs: dict[str, str],
    expected_pairs: dict[str, str],
) -> None:
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request="Low-risk docs-only change for helper id pass-through validation.",
            changed_areas={"docs"},
        )
    )
    projected = result.projected_activation_decision
    assert projected is not None

    builder_kwargs = build_approval_record_builder_kwargs_from_projection(
        projected_activation_decision=projected,
        activation_review_item_id=activation_review_item_id,
        management_decision=None,
        **pass_through_kwargs,
    )

    assert all(
        builder_kwargs[key] == expected_value for key, expected_value in expected_pairs.items()
    )


def _build_projected_contract_from_examples(
    *,
    expected_payload_path: str,
    update: dict[str, str],
    user_request: str,
    changed_areas: set[str],
) -> tuple[dict, object]:
    expected_payload = json.loads((_ROOT / expected_payload_path).read_text(encoding="utf-8"))
    management_decision_payload = json.loads(
        (_ROOT / "docs/examples/management_decision_example.json").read_text(encoding="utf-8")
    )
    management_decision = ManagementDecisionRecord.model_validate(
        management_decision_payload
    ).model_copy(update=update)
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(user_request=user_request, changed_areas=changed_areas)
    )
    projected = build_projected_activation_decision(
        current_brief=result.current_brief,
        management_summary=result.management_summary,
        management_decision=management_decision,
    )
    return expected_payload, projected


def test_build_projected_activation_decision_clean_go_remains_go() -> None:
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request="Low-risk docs-only change with no blockers.",
            changed_areas={"docs"},
        )
    )
    management_decision = ManagementDecisionRecord(
        item_id="rq_go_clean_projection_1",
        decision="GO",
        reviewer_id="manager-go-clean",
        reviewer_type="human",
        rationale="Low-risk scope with no unresolved blockers.",
        approved_next_action="Proceed in dry-run mode.",
    )

    projected = build_projected_activation_decision(
        current_brief=result.current_brief,
        management_summary=result.management_summary,
        management_decision=management_decision,
    )

    first_approval = projected.human_approvals_recorded[0]
    assert result.management_summary.required_review is False
    assert management_decision.decision == "GO"
    assert projected.recommendation == "GO"
    assert projected.remaining_blockers == []
    assert projected.re_review_required is False
    assert projected.escalation_destination is None
    assert projected.autonomous_continuation_status == AUTONOMOUS_NOT_APPROVED
    assert first_approval[APPROVER_ID_KEY] == "manager-go-clean"
    assert first_approval[APPROVER_TYPE_KEY] == "human"
    assert first_approval[APPROVER_ID_KEY] != FALLBACK_REVIEWER_ID


def test_build_projected_activation_decision_go_with_blockers_downgrades_to_pause() -> None:
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request="GO decision should pause while approval blockers remain.",
            changed_areas={"approval"},
        )
    )
    management_decision = ManagementDecisionRecord(
        item_id="rq_go_blocked_projection_1",
        decision="GO",
        reviewer_id="manager-go-blocked",
        reviewer_type="human",
        rationale="GO can proceed only after blocker clearance.",
        approved_next_action="Proceed after blockers are removed.",
    )

    projected = build_projected_activation_decision(
        current_brief=result.current_brief,
        management_summary=result.management_summary,
        management_decision=management_decision,
    )

    first_approval = projected.human_approvals_recorded[0]
    assert management_decision.decision == "GO"
    assert projected.recommendation == "PAUSE"
    assert "approval_flow_change" in projected.remaining_blockers
    assert projected.re_review_required is True
    assert projected.autonomous_continuation_status == AUTONOMOUS_NOT_APPROVED
    assert first_approval[APPROVER_ID_KEY] == "manager-go-blocked"
    assert first_approval[APPROVER_TYPE_KEY] == "human"
    assert first_approval[APPROVER_ID_KEY] != FALLBACK_REVIEWER_ID


def test_build_projected_activation_decision_pause_preserves_blockers_and_re_review() -> None:
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request="Pause until approval-related blockers are cleared.",
            changed_areas={"approval"},
        )
    )
    management_decision = ManagementDecisionRecord(
        item_id="rq_pause_projection_1",
        decision="PAUSE",
        reviewer_id="manager-pause",
        reviewer_type="human",
        rationale="Pause path requires blocker retention and re-review.",
        approved_next_action="Keep paused until blockers are resolved.",
    )

    projected = build_projected_activation_decision(
        current_brief=result.current_brief,
        management_summary=result.management_summary,
        management_decision=management_decision,
    )

    first_approval = projected.human_approvals_recorded[0]
    assert projected.recommendation == "PAUSE"
    assert projected.re_review_required is True
    assert "approval_flow_change" in projected.remaining_blockers
    assert projected.autonomous_continuation_status == AUTONOMOUS_NOT_APPROVED
    assert first_approval[APPROVER_ID_KEY] == "manager-pause"
    assert first_approval[APPROVER_TYPE_KEY] == "human"
    assert first_approval[APPROVER_ID_KEY] != FALLBACK_REVIEWER_ID


def test_build_projected_activation_decision_review_has_escalation_destination() -> None:
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=(
                "Title: Approval review\n"
                "Scope: dry-run governance projection\n"
                "Constraints: no runtime changes\n"
                "Success Criteria: explicit escalation destination\n"
                "Deadline: 2026-05-01"
            ),
            changed_areas={"docs"},
        )
    )
    management_decision = ManagementDecisionRecord(
        item_id="rq_review_projection_1",
        decision="REVIEW",
        reviewer_id="manager-review",
        reviewer_type="human",
        rationale="Explicit review path for governance-sensitive handling.",
        approved_next_action="Escalate to audit and review before any continuation.",
    )

    projected = build_projected_activation_decision(
        current_brief=result.current_brief,
        management_summary=result.management_summary,
        management_decision=management_decision,
    )

    first_approval = projected.human_approvals_recorded[0]
    assert projected.recommendation == "REVIEW"
    assert projected.escalation_destination == AUDIT_AND_REVIEW_DEPARTMENT
    assert projected.autonomous_continuation_status == AUTONOMOUS_NOT_APPROVED
    assert first_approval[APPROVER_ID_KEY] == "manager-review"
    assert first_approval[APPROVER_TYPE_KEY] == "human"
    assert first_approval[APPROVER_ID_KEY] != FALLBACK_REVIEWER_ID


def test_run_dry_run_orchestration_normalizes_powershell_backtick_newlines() -> None:
    result = run_dry_run_orchestration(
        DryRunOrchestrationRequest(
            user_request=(
                "Title: Docs update`n"
                "Scope: docs only`n"
                "Constraints: none`n"
                "Success Criteria: clear docs`n"
                "Deadline: 2026-05-01"
            ),
            changed_areas={"docs"},
            include_trend=False,
            generate_work_order=False,
        )
    )

    payload = result.current_brief.model_dump_json()
    assert "Docs update" in payload
    assert "docs only" in payload
    assert "2026-05-01" in payload
    assert "`n" not in payload

