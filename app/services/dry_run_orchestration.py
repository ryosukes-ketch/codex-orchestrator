from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from app.intake.review_artifacts import intake_result_to_current_brief_artifact
from app.intake.service import IntakeAgent
from app.schemas.brief import IntakeResult
from app.schemas.management import (
    CurrentBriefArtifact,
    ManagementReviewPacket,
    ManagementReviewSummary,
)
from app.schemas.management_decision import ManagementDecisionRecord
from app.schemas.review_queue import ReviewQueueItem
from app.schemas.trend import TrendWorkflowReport
from app.services.activation_decision import (
    DryRunActivationDecision,
    derive_dry_run_activation_decision,
)
from app.services.approval_record_builder import (
    build_action_department_activation_approval_record,
)
from app.services.management_review import build_management_review_summary
from app.services.review_packet import build_management_review_packet
from app.services.review_queue import review_packet_to_queue_item
from app.services.trend_workflow import run_trend_mock_workflow
from app.services.triage import TriageContext, TriageResult, triage_task
from app.services.work_order import WorkOrderDraft, build_work_order_draft

SIMULATION_NOTICE = (
    "Dry-run simulation only. This output cannot authorize risky continuation by itself."
)


@dataclass(frozen=True)
class DryRunOrchestrationRequest:
    user_request: str
    changed_areas: set[str] = field(default_factory=set)
    include_trend: bool = False
    trend_provider_hint: str = "mock"
    task_in_active_phase: bool = True
    verification_passed: bool = True
    ambiguous_scope: bool = False
    generate_work_order: bool = True
    project_id: str | None = None
    brief_id: str | None = None
    work_order_id: str | None = None
    current_task: str | None = None
    management_decision: ManagementDecisionRecord | None = None


@dataclass(frozen=True)
class DryRunDecisionProjection:
    decision: str
    rationale: str
    next_step: str
    autonomous_continuation_allowed: bool


@dataclass(frozen=True)
class DryRunOrchestrationResult:
    mode: str
    notice: str
    intake_result: IntakeResult
    current_brief: CurrentBriefArtifact
    triage_result: TriageResult
    trend_report: TrendWorkflowReport | None
    work_order: WorkOrderDraft | None
    management_summary: ManagementReviewSummary
    management_decision: ManagementDecisionRecord | None
    decision_projection: DryRunDecisionProjection
    projected_activation_decision: DryRunActivationDecision | None = None


def run_dry_run_orchestration(request: DryRunOrchestrationRequest) -> DryRunOrchestrationResult:
    intake_agent = IntakeAgent()
    intake_result = intake_agent.build_brief(request.user_request)

    project_id = request.project_id or f"dryrun-project-{uuid4().hex[:8]}"
    brief_id = request.brief_id or f"dryrun-brief-{uuid4().hex[:8]}"

    current_brief = intake_result_to_current_brief_artifact(
        intake_result,
        brief_id=brief_id,
        project_id=project_id,
        current_task=request.current_task,
    )

    triage_result = triage_task(
        TriageContext(
            changed_areas=set(request.changed_areas),
            task_in_active_phase=request.task_in_active_phase,
            verification_passed=request.verification_passed,
            ambiguous_scope=request.ambiguous_scope,
        )
    )

    trend_report = None
    if request.include_trend:
        trend_report = run_trend_mock_workflow(
            intake_result_to_trend_request(intake_result),
            provider_hint=request.trend_provider_hint,
        )

    work_order = None
    if request.generate_work_order:
        work_order = build_work_order_draft(
            triage_result,
            work_order_id=request.work_order_id or f"dryrun-wo-{uuid4().hex[:8]}",
            project_id=project_id,
            objective=current_brief.current_task,
        )

    management_summary = build_management_review_summary(
        current_brief=current_brief,
        triage_result=triage_result,
        trend_report=trend_report,
        work_order=work_order,
    )
    projected_activation_decision = build_projected_activation_decision(
        current_brief=current_brief,
        management_summary=management_summary,
        management_decision=request.management_decision,
    )
    decision_projection = project_dry_run_decision(
        management_summary=management_summary,
        management_decision=request.management_decision,
    )

    return DryRunOrchestrationResult(
        mode="dry_run",
        notice=SIMULATION_NOTICE,
        intake_result=intake_result,
        current_brief=current_brief,
        triage_result=triage_result,
        trend_report=trend_report,
        work_order=work_order,
        management_summary=management_summary,
        management_decision=request.management_decision,
        decision_projection=decision_projection,
        projected_activation_decision=projected_activation_decision,
    )


def intake_result_to_trend_request(intake_result: IntakeResult):
    from app.schemas.trend import TrendAnalysisRequest

    return TrendAnalysisRequest(
        trend_topic=intake_result.brief.objective,
        context=intake_result.brief.scope,
        max_items=3,
    )


def project_dry_run_decision(
    *,
    management_summary: ManagementReviewSummary,
    management_decision: ManagementDecisionRecord | None,
) -> DryRunDecisionProjection:
    if management_decision:
        decision = management_decision.decision
        rationale = management_decision.rationale
        candidate_next = (
            management_decision.approved_next_action or management_summary.proposed_action
        )
    else:
        decision = management_summary.decision_outcome
        rationale = "Derived from management summary recommendation."
        candidate_next = management_summary.proposed_action

    if decision == "REVIEW":
        return DryRunDecisionProjection(
            decision=decision,
            rationale=rationale,
            next_step="Escalate to Management/Audit review; do not continue autonomously.",
            autonomous_continuation_allowed=False,
        )

    if decision == "PAUSE":
        return DryRunDecisionProjection(
            decision=decision,
            rationale=rationale,
            next_step="Pause dry-run progression and resolve blockers before next simulation step.",
            autonomous_continuation_allowed=False,
        )

    if management_summary.required_review:
        return DryRunDecisionProjection(
            decision=decision,
            rationale=rationale,
            next_step=(
                "Management review is still required for this dry-run outcome; "
                "do not continue autonomously."
            ),
            autonomous_continuation_allowed=False,
        )

    if management_summary.hard_gate_triggered:
        return DryRunDecisionProjection(
            decision=decision,
            rationale=rationale,
            next_step=(
                "GO noted in dry-run, but hard gate remains active; "
                "keep management-led review path."
            ),
            autonomous_continuation_allowed=False,
        )

    return DryRunDecisionProjection(
        decision=decision,
        rationale=rationale,
        next_step=candidate_next,
        autonomous_continuation_allowed=True,
    )


def build_projected_activation_decision(
    *,
    current_brief: CurrentBriefArtifact,
    management_summary: ManagementReviewSummary,
    management_decision: ManagementDecisionRecord | None,
) -> DryRunActivationDecision:
    packet, queue_item, effective_decision = _normalize_activation_projection_inputs(
        current_brief=current_brief,
        management_summary=management_summary,
        management_decision=management_decision,
    )
    return derive_dry_run_activation_decision(
        management_review_packet=packet,
        review_queue_item=queue_item,
        management_decision=effective_decision,
    )


def _normalize_activation_projection_inputs(
    *,
    current_brief: CurrentBriefArtifact,
    management_summary: ManagementReviewSummary,
    management_decision: ManagementDecisionRecord | None,
) -> tuple[ManagementReviewPacket, ReviewQueueItem, ManagementDecisionRecord]:
    packet = build_management_review_packet(
        current_brief=current_brief,
        management_summary=management_summary,
    )
    queue_item = review_packet_to_queue_item(packet)
    effective_decision = management_decision or ManagementDecisionRecord(
        item_id=queue_item.item_id,
        decision=management_summary.decision_outcome,
        reviewer_id="dry-run-system",
        reviewer_type="system",
        rationale="Derived from management summary in dry-run mode.",
        approved_next_action=management_summary.proposed_action,
        related_project_id=management_summary.project_id,
        related_queue_item_id=queue_item.item_id,
        related_packet_id=packet.packet_id,
    )
    return packet, queue_item, effective_decision


def build_approval_record_builder_kwargs_from_projection(
    *,
    projected_activation_decision: DryRunActivationDecision,
    activation_review_item_id: str,
    management_decision: ManagementDecisionRecord | None,
    approval_record_id: str | None = None,
    related_project_id: str | None = None,
    related_activation_decision_id: str | None = None,
    related_packet_id: str | None = None,
    related_queue_item_id: str | None = None,
) -> dict[str, Any]:
    """Build deterministic kwargs for approval-record builder from projection context."""
    builder_kwargs: dict[str, Any] = {
        "projected_activation_decision": projected_activation_decision,
        "activation_review_item_id": activation_review_item_id,
    }
    if approval_record_id is not None:
        builder_kwargs["approval_record_id"] = approval_record_id
    if management_decision is not None:
        builder_kwargs["reviewer_id"] = management_decision.reviewer_id
        builder_kwargs["reviewer_type"] = management_decision.reviewer_type
        builder_kwargs["rationale"] = management_decision.rationale
    if related_project_id is not None:
        builder_kwargs["related_project_id"] = related_project_id
    if related_activation_decision_id is not None:
        builder_kwargs["related_activation_decision_id"] = related_activation_decision_id
    if related_packet_id is not None:
        builder_kwargs["related_packet_id"] = related_packet_id
    if related_queue_item_id is not None:
        builder_kwargs["related_queue_item_id"] = related_queue_item_id
    return builder_kwargs


def build_approval_record_from_projection_context(
    *,
    projected_activation_decision: DryRunActivationDecision,
    activation_review_item_id: str,
    management_decision: ManagementDecisionRecord | None,
    approval_record_id: str | None = None,
    related_project_id: str | None = None,
    related_activation_decision_id: str | None = None,
    related_packet_id: str | None = None,
    related_queue_item_id: str | None = None,
) -> dict[str, Any]:
    """Build deterministic approval record from projection context via normalized kwargs."""
    return build_action_department_activation_approval_record(
        **build_approval_record_builder_kwargs_from_projection(
            projected_activation_decision=projected_activation_decision,
            activation_review_item_id=activation_review_item_id,
            management_decision=management_decision,
            approval_record_id=approval_record_id,
            related_project_id=related_project_id,
            related_activation_decision_id=related_activation_decision_id,
            related_packet_id=related_packet_id,
            related_queue_item_id=related_queue_item_id,
        )
    )


def build_projected_artifact_pair_from_context(
    *,
    current_brief: CurrentBriefArtifact,
    management_summary: ManagementReviewSummary,
    management_decision: ManagementDecisionRecord | None,
    activation_review_item_id: str,
    approval_record_id: str | None = None,
    related_project_id: str | None = None,
    related_activation_decision_id: str | None = None,
    related_packet_id: str | None = None,
    related_queue_item_id: str | None = None,
) -> tuple[DryRunActivationDecision, dict[str, Any]]:
    """Build projected decision and approval record from one projection context."""
    projected_activation_decision = build_projected_activation_decision(
        current_brief=current_brief,
        management_summary=management_summary,
        management_decision=management_decision,
    )
    approval_record = build_approval_record_from_projection_context(
        projected_activation_decision=projected_activation_decision,
        activation_review_item_id=activation_review_item_id,
        management_decision=management_decision,
        approval_record_id=approval_record_id,
        related_project_id=related_project_id,
        related_activation_decision_id=related_activation_decision_id,
        related_packet_id=related_packet_id,
        related_queue_item_id=related_queue_item_id,
    )
    return projected_activation_decision, approval_record


def build_dry_run_artifact_bundle(
    *,
    orchestration_result: DryRunOrchestrationResult,
    activation_review_item_id: str,
    approval_record_id: str | None = None,
    related_project_id: str | None = None,
    related_activation_decision_id: str | None = None,
    related_packet_id: str | None = None,
    related_queue_item_id: str | None = None,
) -> dict[str, Any]:
    """Build projected artifact bundle for downstream handoff without control-path changes."""
    projected_activation_decision = orchestration_result.projected_activation_decision
    if projected_activation_decision is None:
        raise ValueError(
            "DryRunOrchestrationResult must include projected_activation_decision."
        )

    approval_record = build_approval_record_from_projection_context(
        projected_activation_decision=projected_activation_decision,
        activation_review_item_id=activation_review_item_id,
        management_decision=orchestration_result.management_decision,
        approval_record_id=approval_record_id,
        related_project_id=related_project_id,
        related_activation_decision_id=related_activation_decision_id,
        related_packet_id=related_packet_id,
        related_queue_item_id=related_queue_item_id,
    )
    return {
        "projected_activation_decision": projected_activation_decision,
        "approval_record": approval_record,
    }


def build_dry_run_handoff_envelope(
    *,
    artifact_bundle: dict[str, Any],
    related_project_id: str | None = None,
    related_activation_decision_id: str | None = None,
    related_packet_id: str | None = None,
    related_queue_item_id: str | None = None,
) -> dict[str, Any]:
    """Build pure handoff envelope by wrapping existing bundle artifacts and metadata IDs."""
    envelope: dict[str, Any] = {
        "projected_activation_decision": artifact_bundle["projected_activation_decision"],
        "approval_record": artifact_bundle["approval_record"],
    }
    if related_project_id is not None:
        envelope["related_project_id"] = related_project_id
    if related_activation_decision_id is not None:
        envelope["related_activation_decision_id"] = related_activation_decision_id
    if related_packet_id is not None:
        envelope["related_packet_id"] = related_packet_id
    if related_queue_item_id is not None:
        envelope["related_queue_item_id"] = related_queue_item_id
    return envelope


def build_dry_run_handoff_envelope_from_result(
    *,
    orchestration_result: DryRunOrchestrationResult,
    activation_review_item_id: str,
    approval_record_id: str | None = None,
    related_project_id: str | None = None,
    related_activation_decision_id: str | None = None,
    related_packet_id: str | None = None,
    related_queue_item_id: str | None = None,
) -> dict[str, Any]:
    """Build pure handoff envelope by composing existing dry-run bundle/envelope helpers."""
    artifact_bundle = build_dry_run_artifact_bundle(
        orchestration_result=orchestration_result,
        activation_review_item_id=activation_review_item_id,
        approval_record_id=approval_record_id,
        related_project_id=related_project_id,
        related_activation_decision_id=related_activation_decision_id,
        related_packet_id=related_packet_id,
        related_queue_item_id=related_queue_item_id,
    )
    return build_dry_run_handoff_envelope(
        artifact_bundle=artifact_bundle,
        related_project_id=related_project_id,
        related_activation_decision_id=related_activation_decision_id,
        related_packet_id=related_packet_id,
        related_queue_item_id=related_queue_item_id,
    )


def build_next_layer_intake_from_handoff_envelope(
    *,
    handoff_envelope: dict[str, Any],
) -> dict[str, Any]:
    """Build pure next-layer intake by selecting existing fields from handoff envelope."""
    intake: dict[str, Any] = {
        "projected_activation_decision": handoff_envelope["projected_activation_decision"],
        "approval_record": handoff_envelope["approval_record"],
    }
    if "related_project_id" in handoff_envelope:
        intake["related_project_id"] = handoff_envelope["related_project_id"]
    if "related_activation_decision_id" in handoff_envelope:
        intake["related_activation_decision_id"] = handoff_envelope[
            "related_activation_decision_id"
        ]
    if "related_packet_id" in handoff_envelope:
        intake["related_packet_id"] = handoff_envelope["related_packet_id"]
    if "related_queue_item_id" in handoff_envelope:
        intake["related_queue_item_id"] = handoff_envelope["related_queue_item_id"]
    return intake


def build_downstream_work_item_from_intake(
    *,
    next_layer_intake: dict[str, Any],
) -> dict[str, Any]:
    """Build pure downstream work item by selecting existing fields from next-layer intake."""
    work_item: dict[str, Any] = {
        "projected_activation_decision": next_layer_intake["projected_activation_decision"],
        "approval_record": next_layer_intake["approval_record"],
    }
    if "related_project_id" in next_layer_intake:
        work_item["related_project_id"] = next_layer_intake["related_project_id"]
    if "related_activation_decision_id" in next_layer_intake:
        work_item["related_activation_decision_id"] = next_layer_intake[
            "related_activation_decision_id"
        ]
    if "related_packet_id" in next_layer_intake:
        work_item["related_packet_id"] = next_layer_intake["related_packet_id"]
    if "related_queue_item_id" in next_layer_intake:
        work_item["related_queue_item_id"] = next_layer_intake["related_queue_item_id"]
    return work_item


def build_downstream_execution_intent_from_work_item(
    *,
    downstream_work_item: dict[str, Any],
) -> dict[str, Any]:
    """Build pure downstream execution intent by selecting existing work-item fields."""
    intent: dict[str, Any] = {
        "projected_activation_decision": downstream_work_item["projected_activation_decision"],
        "approval_record": downstream_work_item["approval_record"],
    }
    if "related_project_id" in downstream_work_item:
        intent["related_project_id"] = downstream_work_item["related_project_id"]
    if "related_activation_decision_id" in downstream_work_item:
        intent["related_activation_decision_id"] = downstream_work_item[
            "related_activation_decision_id"
        ]
    if "related_packet_id" in downstream_work_item:
        intent["related_packet_id"] = downstream_work_item["related_packet_id"]
    if "related_queue_item_id" in downstream_work_item:
        intent["related_queue_item_id"] = downstream_work_item["related_queue_item_id"]
    return intent


def build_execution_readiness_view_from_intent(
    *,
    downstream_execution_intent: dict[str, Any],
) -> dict[str, Any]:
    """Build pure execution readiness view by selecting existing intent fields."""
    readiness_view: dict[str, Any] = {
        "projected_activation_decision": downstream_execution_intent[
            "projected_activation_decision"
        ],
        "approval_record": downstream_execution_intent["approval_record"],
    }
    if "related_project_id" in downstream_execution_intent:
        readiness_view["related_project_id"] = downstream_execution_intent[
            "related_project_id"
        ]
    if "related_activation_decision_id" in downstream_execution_intent:
        readiness_view["related_activation_decision_id"] = downstream_execution_intent[
            "related_activation_decision_id"
        ]
    if "related_packet_id" in downstream_execution_intent:
        readiness_view["related_packet_id"] = downstream_execution_intent[
            "related_packet_id"
        ]
    if "related_queue_item_id" in downstream_execution_intent:
        readiness_view["related_queue_item_id"] = downstream_execution_intent[
            "related_queue_item_id"
        ]
    return readiness_view


def build_execution_readiness_assessment_from_view(
    *,
    execution_readiness_view: dict[str, Any],
) -> dict[str, Any]:
    """Build pure execution readiness assessment by selecting existing readiness-view fields."""
    assessment: dict[str, Any] = {
        "projected_activation_decision": execution_readiness_view[
            "projected_activation_decision"
        ],
        "approval_record": execution_readiness_view["approval_record"],
    }
    if "related_project_id" in execution_readiness_view:
        assessment["related_project_id"] = execution_readiness_view[
            "related_project_id"
        ]
    if "related_activation_decision_id" in execution_readiness_view:
        assessment["related_activation_decision_id"] = execution_readiness_view[
            "related_activation_decision_id"
        ]
    if "related_packet_id" in execution_readiness_view:
        assessment["related_packet_id"] = execution_readiness_view[
            "related_packet_id"
        ]
    if "related_queue_item_id" in execution_readiness_view:
        assessment["related_queue_item_id"] = execution_readiness_view[
            "related_queue_item_id"
        ]
    return assessment


def build_execution_readiness_signal_from_assessment(
    *,
    execution_readiness_assessment: dict[str, Any],
) -> dict[str, Any]:
    """Build pure execution readiness signal by selecting existing assessment fields."""
    signal: dict[str, Any] = {
        "projected_activation_decision": execution_readiness_assessment[
            "projected_activation_decision"
        ],
        "approval_record": execution_readiness_assessment["approval_record"],
    }
    if "related_project_id" in execution_readiness_assessment:
        signal["related_project_id"] = execution_readiness_assessment[
            "related_project_id"
        ]
    if "related_activation_decision_id" in execution_readiness_assessment:
        signal["related_activation_decision_id"] = execution_readiness_assessment[
            "related_activation_decision_id"
        ]
    if "related_packet_id" in execution_readiness_assessment:
        signal["related_packet_id"] = execution_readiness_assessment[
            "related_packet_id"
        ]
    if "related_queue_item_id" in execution_readiness_assessment:
        signal["related_queue_item_id"] = execution_readiness_assessment[
            "related_queue_item_id"
        ]
    return signal


def build_execution_readiness_outcome_from_signal(
    *,
    execution_readiness_signal: dict[str, Any],
) -> dict[str, Any]:
    """Build pure execution readiness outcome by selecting existing signal fields."""
    outcome: dict[str, Any] = {
        "projected_activation_decision": execution_readiness_signal[
            "projected_activation_decision"
        ],
        "approval_record": execution_readiness_signal["approval_record"],
    }
    if "related_project_id" in execution_readiness_signal:
        outcome["related_project_id"] = execution_readiness_signal[
            "related_project_id"
        ]
    if "related_activation_decision_id" in execution_readiness_signal:
        outcome["related_activation_decision_id"] = execution_readiness_signal[
            "related_activation_decision_id"
        ]
    if "related_packet_id" in execution_readiness_signal:
        outcome["related_packet_id"] = execution_readiness_signal[
            "related_packet_id"
        ]
    if "related_queue_item_id" in execution_readiness_signal:
        outcome["related_queue_item_id"] = execution_readiness_signal[
            "related_queue_item_id"
        ]
    return outcome


def build_downstream_consumer_payload_from_outcome(
    *,
    execution_readiness_outcome: dict[str, Any],
) -> dict[str, Any]:
    """Build pure downstream consumer payload by selecting existing outcome fields."""
    payload: dict[str, Any] = {
        "projected_activation_decision": execution_readiness_outcome[
            "projected_activation_decision"
        ],
        "approval_record": execution_readiness_outcome["approval_record"],
    }
    if "related_project_id" in execution_readiness_outcome:
        payload["related_project_id"] = execution_readiness_outcome[
            "related_project_id"
        ]
    if "related_activation_decision_id" in execution_readiness_outcome:
        payload["related_activation_decision_id"] = execution_readiness_outcome[
            "related_activation_decision_id"
        ]
    if "related_packet_id" in execution_readiness_outcome:
        payload["related_packet_id"] = execution_readiness_outcome[
            "related_packet_id"
        ]
    if "related_queue_item_id" in execution_readiness_outcome:
        payload["related_queue_item_id"] = execution_readiness_outcome[
            "related_queue_item_id"
        ]
    return payload


def build_consumer_receiver_intake_from_payload(
    *,
    downstream_consumer_payload: dict[str, Any],
) -> dict[str, Any]:
    """Build pure consumer-receiver intake by selecting existing consumer-payload fields."""
    intake: dict[str, Any] = {
        "projected_activation_decision": downstream_consumer_payload[
            "projected_activation_decision"
        ],
        "approval_record": downstream_consumer_payload["approval_record"],
    }
    if "related_project_id" in downstream_consumer_payload:
        intake["related_project_id"] = downstream_consumer_payload["related_project_id"]
    if "related_activation_decision_id" in downstream_consumer_payload:
        intake["related_activation_decision_id"] = downstream_consumer_payload[
            "related_activation_decision_id"
        ]
    if "related_packet_id" in downstream_consumer_payload:
        intake["related_packet_id"] = downstream_consumer_payload["related_packet_id"]
    if "related_queue_item_id" in downstream_consumer_payload:
        intake["related_queue_item_id"] = downstream_consumer_payload["related_queue_item_id"]
    return intake


def build_consumer_receiver_readiness_view_from_intake(
    *,
    consumer_receiver_intake: dict[str, Any],
) -> dict[str, Any]:
    """Build pure consumer-receiver readiness view by selecting existing intake fields."""
    readiness_view: dict[str, Any] = {
        "projected_activation_decision": consumer_receiver_intake[
            "projected_activation_decision"
        ],
        "approval_record": consumer_receiver_intake["approval_record"],
    }
    if "related_project_id" in consumer_receiver_intake:
        readiness_view["related_project_id"] = consumer_receiver_intake[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_receiver_intake:
        readiness_view["related_activation_decision_id"] = consumer_receiver_intake[
            "related_activation_decision_id"
        ]
    if "related_packet_id" in consumer_receiver_intake:
        readiness_view["related_packet_id"] = consumer_receiver_intake[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_receiver_intake:
        readiness_view["related_queue_item_id"] = consumer_receiver_intake[
            "related_queue_item_id"
        ]
    return readiness_view


def build_consumer_receiver_readiness_assessment_from_view(
    *,
    consumer_receiver_readiness_view: dict[str, Any],
) -> dict[str, Any]:
    """Build pure consumer-receiver readiness assessment from existing readiness-view fields."""
    assessment: dict[str, Any] = {
        "projected_activation_decision": consumer_receiver_readiness_view[
            "projected_activation_decision"
        ],
        "approval_record": consumer_receiver_readiness_view["approval_record"],
    }
    if "related_project_id" in consumer_receiver_readiness_view:
        assessment["related_project_id"] = consumer_receiver_readiness_view[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_receiver_readiness_view:
        assessment["related_activation_decision_id"] = consumer_receiver_readiness_view[
            "related_activation_decision_id"
        ]
    if "related_packet_id" in consumer_receiver_readiness_view:
        assessment["related_packet_id"] = consumer_receiver_readiness_view[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_receiver_readiness_view:
        assessment["related_queue_item_id"] = consumer_receiver_readiness_view[
            "related_queue_item_id"
        ]
    return assessment


def build_consumer_receiver_readiness_signal_from_assessment(
    *,
    consumer_receiver_readiness_assessment: dict[str, Any],
) -> dict[str, Any]:
    """Build pure consumer-receiver readiness signal from existing assessment fields."""
    signal: dict[str, Any] = {
        "projected_activation_decision": consumer_receiver_readiness_assessment[
            "projected_activation_decision"
        ],
        "approval_record": consumer_receiver_readiness_assessment["approval_record"],
    }
    if "related_project_id" in consumer_receiver_readiness_assessment:
        signal["related_project_id"] = consumer_receiver_readiness_assessment[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_receiver_readiness_assessment:
        signal["related_activation_decision_id"] = consumer_receiver_readiness_assessment[
            "related_activation_decision_id"
        ]
    if "related_packet_id" in consumer_receiver_readiness_assessment:
        signal["related_packet_id"] = consumer_receiver_readiness_assessment[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_receiver_readiness_assessment:
        signal["related_queue_item_id"] = consumer_receiver_readiness_assessment[
            "related_queue_item_id"
        ]
    return signal


def build_consumer_receiver_readiness_outcome_from_signal(
    *,
    consumer_receiver_readiness_signal: dict[str, Any],
) -> dict[str, Any]:
    """Build pure consumer-receiver readiness outcome from existing signal fields."""
    outcome: dict[str, Any] = {
        "projected_activation_decision": consumer_receiver_readiness_signal[
            "projected_activation_decision"
        ],
        "approval_record": consumer_receiver_readiness_signal["approval_record"],
    }
    if "related_project_id" in consumer_receiver_readiness_signal:
        outcome["related_project_id"] = consumer_receiver_readiness_signal[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_receiver_readiness_signal:
        outcome["related_activation_decision_id"] = consumer_receiver_readiness_signal[
            "related_activation_decision_id"
        ]
    if "related_packet_id" in consumer_receiver_readiness_signal:
        outcome["related_packet_id"] = consumer_receiver_readiness_signal[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_receiver_readiness_signal:
        outcome["related_queue_item_id"] = consumer_receiver_readiness_signal[
            "related_queue_item_id"
        ]
    return outcome


def build_consumer_receiver_delivery_payload_from_outcome(
    *,
    consumer_receiver_readiness_outcome: dict[str, Any],
) -> dict[str, Any]:
    """Build pure consumer-receiver delivery payload from existing outcome fields."""
    payload: dict[str, Any] = {
        "projected_activation_decision": consumer_receiver_readiness_outcome[
            "projected_activation_decision"
        ],
        "approval_record": consumer_receiver_readiness_outcome["approval_record"],
    }
    if "related_project_id" in consumer_receiver_readiness_outcome:
        payload["related_project_id"] = consumer_receiver_readiness_outcome[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_receiver_readiness_outcome:
        payload["related_activation_decision_id"] = consumer_receiver_readiness_outcome[
            "related_activation_decision_id"
        ]
    if "related_packet_id" in consumer_receiver_readiness_outcome:
        payload["related_packet_id"] = consumer_receiver_readiness_outcome[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_receiver_readiness_outcome:
        payload["related_queue_item_id"] = consumer_receiver_readiness_outcome[
            "related_queue_item_id"
        ]
    return payload


def build_consumer_receiver_delivery_packet_from_payload(
    *,
    consumer_receiver_delivery_payload: dict[str, Any],
) -> dict[str, Any]:
    """Build pure consumer-receiver delivery packet from existing delivery-payload fields."""
    packet: dict[str, Any] = {
        "projected_activation_decision": consumer_receiver_delivery_payload[
            "projected_activation_decision"
        ],
        "approval_record": consumer_receiver_delivery_payload["approval_record"],
    }
    if "related_project_id" in consumer_receiver_delivery_payload:
        packet["related_project_id"] = consumer_receiver_delivery_payload[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_receiver_delivery_payload:
        packet["related_activation_decision_id"] = consumer_receiver_delivery_payload[
            "related_activation_decision_id"
        ]
    if "related_packet_id" in consumer_receiver_delivery_payload:
        packet["related_packet_id"] = consumer_receiver_delivery_payload[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_receiver_delivery_payload:
        packet["related_queue_item_id"] = consumer_receiver_delivery_payload[
            "related_queue_item_id"
        ]
    return packet


def build_consumer_receiver_delivery_manifest_from_packet(
    *,
    consumer_receiver_delivery_packet: dict[str, Any],
) -> dict[str, Any]:
    """Build pure consumer-receiver delivery manifest from existing delivery-packet fields."""
    manifest: dict[str, Any] = {
        "projected_activation_decision": consumer_receiver_delivery_packet[
            "projected_activation_decision"
        ],
        "approval_record": consumer_receiver_delivery_packet["approval_record"],
    }
    if "related_project_id" in consumer_receiver_delivery_packet:
        manifest["related_project_id"] = consumer_receiver_delivery_packet[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_receiver_delivery_packet:
        manifest["related_activation_decision_id"] = consumer_receiver_delivery_packet[
            "related_activation_decision_id"
        ]
    if "related_packet_id" in consumer_receiver_delivery_packet:
        manifest["related_packet_id"] = consumer_receiver_delivery_packet[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_receiver_delivery_packet:
        manifest["related_queue_item_id"] = consumer_receiver_delivery_packet[
            "related_queue_item_id"
        ]
    return manifest


def build_consumer_receiver_readiness_classification_from_manifest(
    *,
    consumer_receiver_delivery_manifest: dict[str, Any],
) -> dict[str, Any]:
    """Build pure receiver readiness classification from existing delivery-manifest fields."""
    recommendation = consumer_receiver_delivery_manifest[
        "projected_activation_decision"
    ].recommendation
    classification_by_recommendation = {
        "GO": "ready",
        "PAUSE": "hold",
        "REVIEW": "needs_review",
    }
    classification: dict[str, Any] = {
        "projected_activation_decision": consumer_receiver_delivery_manifest[
            "projected_activation_decision"
        ],
        "approval_record": consumer_receiver_delivery_manifest["approval_record"],
        "receiver_readiness_classification": classification_by_recommendation[
            recommendation
        ],
    }
    if "related_project_id" in consumer_receiver_delivery_manifest:
        classification["related_project_id"] = consumer_receiver_delivery_manifest[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_receiver_delivery_manifest:
        classification["related_activation_decision_id"] = (
            consumer_receiver_delivery_manifest["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_receiver_delivery_manifest:
        classification["related_packet_id"] = consumer_receiver_delivery_manifest[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_receiver_delivery_manifest:
        classification["related_queue_item_id"] = consumer_receiver_delivery_manifest[
            "related_queue_item_id"
        ]
    return classification


def build_consumer_receiver_handling_directive_from_classification(
    *,
    consumer_receiver_readiness_classification: dict[str, Any],
) -> dict[str, Any]:
    """Build pure receiver handling directive from existing readiness classification."""
    handling_directive_by_classification = {
        "ready": "deliver",
        "hold": "defer",
        "needs_review": "route_for_review",
    }
    handling_directive: dict[str, Any] = {
        "projected_activation_decision": consumer_receiver_readiness_classification[
            "projected_activation_decision"
        ],
        "approval_record": consumer_receiver_readiness_classification["approval_record"],
        "receiver_readiness_classification": consumer_receiver_readiness_classification[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": handling_directive_by_classification[
            consumer_receiver_readiness_classification[
                "receiver_readiness_classification"
            ]
        ],
    }
    if "related_project_id" in consumer_receiver_readiness_classification:
        handling_directive["related_project_id"] = (
            consumer_receiver_readiness_classification["related_project_id"]
        )
    if "related_activation_decision_id" in consumer_receiver_readiness_classification:
        handling_directive["related_activation_decision_id"] = (
            consumer_receiver_readiness_classification["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_receiver_readiness_classification:
        handling_directive["related_packet_id"] = (
            consumer_receiver_readiness_classification["related_packet_id"]
        )
    if "related_queue_item_id" in consumer_receiver_readiness_classification:
        handling_directive["related_queue_item_id"] = (
            consumer_receiver_readiness_classification["related_queue_item_id"]
        )
    return handling_directive


def build_consumer_receiver_action_label_from_directive(
    *,
    consumer_receiver_handling_directive: dict[str, Any],
) -> dict[str, Any]:
    """Build pure receiver action label from existing handling directive."""
    action_label_by_handling_directive = {
        "deliver": "dispatch",
        "defer": "wait",
        "route_for_review": "review_queue",
    }
    action_label: dict[str, Any] = {
        "projected_activation_decision": consumer_receiver_handling_directive[
            "projected_activation_decision"
        ],
        "approval_record": consumer_receiver_handling_directive["approval_record"],
        "receiver_readiness_classification": consumer_receiver_handling_directive[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_receiver_handling_directive[
            "receiver_handling_directive"
        ],
        "receiver_action_label": action_label_by_handling_directive[
            consumer_receiver_handling_directive["receiver_handling_directive"]
        ],
    }
    if "related_project_id" in consumer_receiver_handling_directive:
        action_label["related_project_id"] = consumer_receiver_handling_directive[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_receiver_handling_directive:
        action_label["related_activation_decision_id"] = (
            consumer_receiver_handling_directive["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_receiver_handling_directive:
        action_label["related_packet_id"] = consumer_receiver_handling_directive[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_receiver_handling_directive:
        action_label["related_queue_item_id"] = consumer_receiver_handling_directive[
            "related_queue_item_id"
        ]
    return action_label


def build_consumer_receiver_dispatch_intent_from_action_label(
    *,
    consumer_receiver_action_label: dict[str, Any],
) -> dict[str, Any]:
    """Build pure receiver dispatch intent from existing action label."""
    dispatch_intent_by_action_label = {
        "dispatch": "send",
        "wait": "park",
        "review_queue": "review",
    }
    dispatch_intent: dict[str, Any] = {
        "projected_activation_decision": consumer_receiver_action_label[
            "projected_activation_decision"
        ],
        "approval_record": consumer_receiver_action_label["approval_record"],
        "receiver_readiness_classification": consumer_receiver_action_label[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_receiver_action_label[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_receiver_action_label["receiver_action_label"],
        "receiver_dispatch_intent": dispatch_intent_by_action_label[
            consumer_receiver_action_label["receiver_action_label"]
        ],
    }
    if "related_project_id" in consumer_receiver_action_label:
        dispatch_intent["related_project_id"] = consumer_receiver_action_label[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_receiver_action_label:
        dispatch_intent["related_activation_decision_id"] = (
            consumer_receiver_action_label["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_receiver_action_label:
        dispatch_intent["related_packet_id"] = consumer_receiver_action_label[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_receiver_action_label:
        dispatch_intent["related_queue_item_id"] = consumer_receiver_action_label[
            "related_queue_item_id"
        ]
    return dispatch_intent


def build_consumer_receiver_dispatch_mode_from_intent(
    *,
    consumer_receiver_dispatch_intent: dict[str, Any],
) -> dict[str, Any]:
    """Build pure receiver dispatch mode from existing dispatch intent."""
    dispatch_mode_by_dispatch_intent = {
        "send": "active",
        "park": "queued",
        "review": "review_pending",
    }
    dispatch_mode: dict[str, Any] = {
        "projected_activation_decision": consumer_receiver_dispatch_intent[
            "projected_activation_decision"
        ],
        "approval_record": consumer_receiver_dispatch_intent["approval_record"],
        "receiver_readiness_classification": consumer_receiver_dispatch_intent[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_receiver_dispatch_intent[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_receiver_dispatch_intent[
            "receiver_action_label"
        ],
        "receiver_dispatch_intent": consumer_receiver_dispatch_intent[
            "receiver_dispatch_intent"
        ],
        "receiver_dispatch_mode": dispatch_mode_by_dispatch_intent[
            consumer_receiver_dispatch_intent["receiver_dispatch_intent"]
        ],
    }
    if "related_project_id" in consumer_receiver_dispatch_intent:
        dispatch_mode["related_project_id"] = consumer_receiver_dispatch_intent[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_receiver_dispatch_intent:
        dispatch_mode["related_activation_decision_id"] = (
            consumer_receiver_dispatch_intent["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_receiver_dispatch_intent:
        dispatch_mode["related_packet_id"] = consumer_receiver_dispatch_intent[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_receiver_dispatch_intent:
        dispatch_mode["related_queue_item_id"] = consumer_receiver_dispatch_intent[
            "related_queue_item_id"
        ]
    return dispatch_mode


def build_consumer_receiver_release_gate_from_dispatch_mode(
    *,
    consumer_receiver_dispatch_mode: dict[str, Any],
) -> dict[str, Any]:
    """Build pure receiver release gate from existing dispatch mode."""
    release_gate_by_dispatch_mode = {
        "active": "open",
        "queued": "deferred",
        "review_pending": "blocked_for_review",
    }
    release_gate: dict[str, Any] = {
        "projected_activation_decision": consumer_receiver_dispatch_mode[
            "projected_activation_decision"
        ],
        "approval_record": consumer_receiver_dispatch_mode["approval_record"],
        "receiver_readiness_classification": consumer_receiver_dispatch_mode[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_receiver_dispatch_mode[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_receiver_dispatch_mode[
            "receiver_action_label"
        ],
        "receiver_dispatch_intent": consumer_receiver_dispatch_mode[
            "receiver_dispatch_intent"
        ],
        "receiver_dispatch_mode": consumer_receiver_dispatch_mode[
            "receiver_dispatch_mode"
        ],
        "receiver_release_gate": release_gate_by_dispatch_mode[
            consumer_receiver_dispatch_mode["receiver_dispatch_mode"]
        ],
    }
    if "related_project_id" in consumer_receiver_dispatch_mode:
        release_gate["related_project_id"] = consumer_receiver_dispatch_mode[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_receiver_dispatch_mode:
        release_gate["related_activation_decision_id"] = (
            consumer_receiver_dispatch_mode["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_receiver_dispatch_mode:
        release_gate["related_packet_id"] = consumer_receiver_dispatch_mode[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_receiver_dispatch_mode:
        release_gate["related_queue_item_id"] = consumer_receiver_dispatch_mode[
            "related_queue_item_id"
        ]
    return release_gate


def build_consumer_receiver_progress_state_from_release_gate(
    *,
    consumer_receiver_release_gate: dict[str, Any],
) -> dict[str, Any]:
    """Build pure receiver progress state from existing release gate."""
    progress_state_by_release_gate = {
        "open": "in_progress",
        "deferred": "pending",
        "blocked_for_review": "review_hold",
    }
    progress_state: dict[str, Any] = {
        "projected_activation_decision": consumer_receiver_release_gate[
            "projected_activation_decision"
        ],
        "approval_record": consumer_receiver_release_gate["approval_record"],
        "receiver_readiness_classification": consumer_receiver_release_gate[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_receiver_release_gate[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_receiver_release_gate[
            "receiver_action_label"
        ],
        "receiver_dispatch_intent": consumer_receiver_release_gate[
            "receiver_dispatch_intent"
        ],
        "receiver_dispatch_mode": consumer_receiver_release_gate[
            "receiver_dispatch_mode"
        ],
        "receiver_release_gate": consumer_receiver_release_gate["receiver_release_gate"],
        "receiver_progress_state": progress_state_by_release_gate[
            consumer_receiver_release_gate["receiver_release_gate"]
        ],
    }
    if "related_project_id" in consumer_receiver_release_gate:
        progress_state["related_project_id"] = consumer_receiver_release_gate[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_receiver_release_gate:
        progress_state["related_activation_decision_id"] = (
            consumer_receiver_release_gate["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_receiver_release_gate:
        progress_state["related_packet_id"] = consumer_receiver_release_gate[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_receiver_release_gate:
        progress_state["related_queue_item_id"] = consumer_receiver_release_gate[
            "related_queue_item_id"
        ]
    return progress_state


def build_consumer_receiver_progress_signal_from_state(
    *,
    consumer_receiver_progress_state: dict[str, Any],
) -> dict[str, Any]:
    """Build pure receiver progress signal from existing progress state."""
    progress_signal_by_progress_state = {
        "in_progress": "advance",
        "pending": "await",
        "review_hold": "review_wait",
    }
    progress_signal: dict[str, Any] = {
        "projected_activation_decision": consumer_receiver_progress_state[
            "projected_activation_decision"
        ],
        "approval_record": consumer_receiver_progress_state["approval_record"],
        "receiver_readiness_classification": consumer_receiver_progress_state[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_receiver_progress_state[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_receiver_progress_state[
            "receiver_action_label"
        ],
        "receiver_dispatch_intent": consumer_receiver_progress_state[
            "receiver_dispatch_intent"
        ],
        "receiver_dispatch_mode": consumer_receiver_progress_state[
            "receiver_dispatch_mode"
        ],
        "receiver_release_gate": consumer_receiver_progress_state[
            "receiver_release_gate"
        ],
        "receiver_progress_state": consumer_receiver_progress_state[
            "receiver_progress_state"
        ],
        "receiver_progress_signal": progress_signal_by_progress_state[
            consumer_receiver_progress_state["receiver_progress_state"]
        ],
    }
    if "related_project_id" in consumer_receiver_progress_state:
        progress_signal["related_project_id"] = consumer_receiver_progress_state[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_receiver_progress_state:
        progress_signal["related_activation_decision_id"] = (
            consumer_receiver_progress_state["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_receiver_progress_state:
        progress_signal["related_packet_id"] = consumer_receiver_progress_state[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_receiver_progress_state:
        progress_signal["related_queue_item_id"] = consumer_receiver_progress_state[
            "related_queue_item_id"
        ]
    return progress_signal


def build_consumer_receiver_progress_outcome_from_signal(
    *,
    consumer_receiver_progress_signal: dict[str, Any],
) -> dict[str, Any]:
    """Build pure receiver progress outcome from existing progress signal."""
    progress_outcome_by_progress_signal = {
        "advance": "moving",
        "await": "standing_by",
        "review_wait": "awaiting_review",
    }
    progress_outcome: dict[str, Any] = {
        "projected_activation_decision": consumer_receiver_progress_signal[
            "projected_activation_decision"
        ],
        "approval_record": consumer_receiver_progress_signal["approval_record"],
        "receiver_readiness_classification": consumer_receiver_progress_signal[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_receiver_progress_signal[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_receiver_progress_signal[
            "receiver_action_label"
        ],
        "receiver_dispatch_intent": consumer_receiver_progress_signal[
            "receiver_dispatch_intent"
        ],
        "receiver_dispatch_mode": consumer_receiver_progress_signal[
            "receiver_dispatch_mode"
        ],
        "receiver_release_gate": consumer_receiver_progress_signal[
            "receiver_release_gate"
        ],
        "receiver_progress_state": consumer_receiver_progress_signal[
            "receiver_progress_state"
        ],
        "receiver_progress_signal": consumer_receiver_progress_signal[
            "receiver_progress_signal"
        ],
        "receiver_progress_outcome": progress_outcome_by_progress_signal[
            consumer_receiver_progress_signal["receiver_progress_signal"]
        ],
    }
    if "related_project_id" in consumer_receiver_progress_signal:
        progress_outcome["related_project_id"] = consumer_receiver_progress_signal[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_receiver_progress_signal:
        progress_outcome["related_activation_decision_id"] = (
            consumer_receiver_progress_signal["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_receiver_progress_signal:
        progress_outcome["related_packet_id"] = consumer_receiver_progress_signal[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_receiver_progress_signal:
        progress_outcome["related_queue_item_id"] = consumer_receiver_progress_signal[
            "related_queue_item_id"
        ]
    return progress_outcome


def build_consumer_receiver_intervention_requirement_from_progress_outcome(
    *,
    consumer_receiver_progress_outcome: dict[str, Any],
) -> dict[str, Any]:
    """Build pure receiver intervention requirement from existing progress outcome."""
    intervention_requirement_by_progress_outcome = {
        "moving": "none",
        "standing_by": "monitor",
        "awaiting_review": "review_required",
    }
    intervention_requirement: dict[str, Any] = {
        "projected_activation_decision": consumer_receiver_progress_outcome[
            "projected_activation_decision"
        ],
        "approval_record": consumer_receiver_progress_outcome["approval_record"],
        "receiver_readiness_classification": consumer_receiver_progress_outcome[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_receiver_progress_outcome[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_receiver_progress_outcome[
            "receiver_action_label"
        ],
        "receiver_dispatch_intent": consumer_receiver_progress_outcome[
            "receiver_dispatch_intent"
        ],
        "receiver_dispatch_mode": consumer_receiver_progress_outcome[
            "receiver_dispatch_mode"
        ],
        "receiver_release_gate": consumer_receiver_progress_outcome[
            "receiver_release_gate"
        ],
        "receiver_progress_state": consumer_receiver_progress_outcome[
            "receiver_progress_state"
        ],
        "receiver_progress_signal": consumer_receiver_progress_outcome[
            "receiver_progress_signal"
        ],
        "receiver_progress_outcome": consumer_receiver_progress_outcome[
            "receiver_progress_outcome"
        ],
        "receiver_intervention_requirement": intervention_requirement_by_progress_outcome[
            consumer_receiver_progress_outcome["receiver_progress_outcome"]
        ],
    }
    if "related_project_id" in consumer_receiver_progress_outcome:
        intervention_requirement["related_project_id"] = (
            consumer_receiver_progress_outcome["related_project_id"]
        )
    if "related_activation_decision_id" in consumer_receiver_progress_outcome:
        intervention_requirement["related_activation_decision_id"] = (
            consumer_receiver_progress_outcome["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_receiver_progress_outcome:
        intervention_requirement["related_packet_id"] = (
            consumer_receiver_progress_outcome["related_packet_id"]
        )
    if "related_queue_item_id" in consumer_receiver_progress_outcome:
        intervention_requirement["related_queue_item_id"] = (
            consumer_receiver_progress_outcome["related_queue_item_id"]
        )
    return intervention_requirement


def build_consumer_receiver_attention_level_from_intervention_requirement(
    *,
    consumer_receiver_intervention_requirement: dict[str, Any],
) -> dict[str, Any]:
    """Build pure receiver attention level from existing intervention requirement."""
    attention_level_by_intervention_requirement = {
        "none": "low",
        "monitor": "medium",
        "review_required": "high",
    }
    attention_level: dict[str, Any] = {
        "projected_activation_decision": consumer_receiver_intervention_requirement[
            "projected_activation_decision"
        ],
        "approval_record": consumer_receiver_intervention_requirement["approval_record"],
        "receiver_readiness_classification": consumer_receiver_intervention_requirement[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_receiver_intervention_requirement[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_receiver_intervention_requirement[
            "receiver_action_label"
        ],
        "receiver_dispatch_intent": consumer_receiver_intervention_requirement[
            "receiver_dispatch_intent"
        ],
        "receiver_dispatch_mode": consumer_receiver_intervention_requirement[
            "receiver_dispatch_mode"
        ],
        "receiver_release_gate": consumer_receiver_intervention_requirement[
            "receiver_release_gate"
        ],
        "receiver_progress_state": consumer_receiver_intervention_requirement[
            "receiver_progress_state"
        ],
        "receiver_progress_signal": consumer_receiver_intervention_requirement[
            "receiver_progress_signal"
        ],
        "receiver_progress_outcome": consumer_receiver_intervention_requirement[
            "receiver_progress_outcome"
        ],
        "receiver_intervention_requirement": consumer_receiver_intervention_requirement[
            "receiver_intervention_requirement"
        ],
        "receiver_attention_level": attention_level_by_intervention_requirement[
            consumer_receiver_intervention_requirement[
                "receiver_intervention_requirement"
            ]
        ],
    }
    if "related_project_id" in consumer_receiver_intervention_requirement:
        attention_level["related_project_id"] = consumer_receiver_intervention_requirement[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_receiver_intervention_requirement:
        attention_level["related_activation_decision_id"] = (
            consumer_receiver_intervention_requirement["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_receiver_intervention_requirement:
        attention_level["related_packet_id"] = consumer_receiver_intervention_requirement[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_receiver_intervention_requirement:
        attention_level["related_queue_item_id"] = (
            consumer_receiver_intervention_requirement["related_queue_item_id"]
        )
    return attention_level


def build_consumer_receiver_notification_requirement_from_attention_level(
    *,
    consumer_receiver_attention_level: dict[str, Any],
) -> dict[str, Any]:
    """Build pure receiver notification requirement from existing attention level."""
    notification_requirement_by_attention_level = {
        "low": "none",
        "medium": "notify",
        "high": "escalate",
    }
    notification_requirement: dict[str, Any] = {
        "projected_activation_decision": consumer_receiver_attention_level[
            "projected_activation_decision"
        ],
        "approval_record": consumer_receiver_attention_level["approval_record"],
        "receiver_readiness_classification": consumer_receiver_attention_level[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_receiver_attention_level[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_receiver_attention_level[
            "receiver_action_label"
        ],
        "receiver_dispatch_intent": consumer_receiver_attention_level[
            "receiver_dispatch_intent"
        ],
        "receiver_dispatch_mode": consumer_receiver_attention_level[
            "receiver_dispatch_mode"
        ],
        "receiver_release_gate": consumer_receiver_attention_level[
            "receiver_release_gate"
        ],
        "receiver_progress_state": consumer_receiver_attention_level[
            "receiver_progress_state"
        ],
        "receiver_progress_signal": consumer_receiver_attention_level[
            "receiver_progress_signal"
        ],
        "receiver_progress_outcome": consumer_receiver_attention_level[
            "receiver_progress_outcome"
        ],
        "receiver_intervention_requirement": consumer_receiver_attention_level[
            "receiver_intervention_requirement"
        ],
        "receiver_attention_level": consumer_receiver_attention_level[
            "receiver_attention_level"
        ],
        "receiver_notification_requirement": notification_requirement_by_attention_level[
            consumer_receiver_attention_level["receiver_attention_level"]
        ],
    }
    if "related_project_id" in consumer_receiver_attention_level:
        notification_requirement["related_project_id"] = (
            consumer_receiver_attention_level["related_project_id"]
        )
    if "related_activation_decision_id" in consumer_receiver_attention_level:
        notification_requirement["related_activation_decision_id"] = (
            consumer_receiver_attention_level["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_receiver_attention_level:
        notification_requirement["related_packet_id"] = consumer_receiver_attention_level[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_receiver_attention_level:
        notification_requirement["related_queue_item_id"] = (
            consumer_receiver_attention_level["related_queue_item_id"]
        )
    return notification_requirement


def build_consumer_receiver_response_priority_from_notification_requirement(
    *,
    consumer_receiver_notification_requirement: dict[str, Any],
) -> dict[str, Any]:
    """Build pure receiver response priority from existing notification requirement."""
    response_priority_by_notification_requirement = {
        "none": "normal",
        "notify": "elevated",
        "escalate": "urgent",
    }
    response_priority: dict[str, Any] = {
        "projected_activation_decision": consumer_receiver_notification_requirement[
            "projected_activation_decision"
        ],
        "approval_record": consumer_receiver_notification_requirement["approval_record"],
        "receiver_readiness_classification": consumer_receiver_notification_requirement[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_receiver_notification_requirement[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_receiver_notification_requirement[
            "receiver_action_label"
        ],
        "receiver_dispatch_intent": consumer_receiver_notification_requirement[
            "receiver_dispatch_intent"
        ],
        "receiver_dispatch_mode": consumer_receiver_notification_requirement[
            "receiver_dispatch_mode"
        ],
        "receiver_release_gate": consumer_receiver_notification_requirement[
            "receiver_release_gate"
        ],
        "receiver_progress_state": consumer_receiver_notification_requirement[
            "receiver_progress_state"
        ],
        "receiver_progress_signal": consumer_receiver_notification_requirement[
            "receiver_progress_signal"
        ],
        "receiver_progress_outcome": consumer_receiver_notification_requirement[
            "receiver_progress_outcome"
        ],
        "receiver_intervention_requirement": consumer_receiver_notification_requirement[
            "receiver_intervention_requirement"
        ],
        "receiver_attention_level": consumer_receiver_notification_requirement[
            "receiver_attention_level"
        ],
        "receiver_notification_requirement": consumer_receiver_notification_requirement[
            "receiver_notification_requirement"
        ],
        "receiver_response_priority": response_priority_by_notification_requirement[
            consumer_receiver_notification_requirement["receiver_notification_requirement"]
        ],
    }
    if "related_project_id" in consumer_receiver_notification_requirement:
        response_priority["related_project_id"] = (
            consumer_receiver_notification_requirement["related_project_id"]
        )
    if "related_activation_decision_id" in consumer_receiver_notification_requirement:
        response_priority["related_activation_decision_id"] = (
            consumer_receiver_notification_requirement["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_receiver_notification_requirement:
        response_priority["related_packet_id"] = (
            consumer_receiver_notification_requirement["related_packet_id"]
        )
    if "related_queue_item_id" in consumer_receiver_notification_requirement:
        response_priority["related_queue_item_id"] = (
            consumer_receiver_notification_requirement["related_queue_item_id"]
        )
    return response_priority


def build_consumer_receiver_response_channel_from_priority(
    *,
    consumer_receiver_response_priority: dict[str, Any],
) -> dict[str, Any]:
    """Build pure receiver response channel from existing response priority."""
    response_channel_by_priority = {
        "normal": "standard_channel",
        "elevated": "priority_channel",
        "urgent": "escalation_channel",
    }
    response_channel: dict[str, Any] = {
        "projected_activation_decision": consumer_receiver_response_priority[
            "projected_activation_decision"
        ],
        "approval_record": consumer_receiver_response_priority["approval_record"],
        "receiver_readiness_classification": consumer_receiver_response_priority[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_receiver_response_priority[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_receiver_response_priority[
            "receiver_action_label"
        ],
        "receiver_dispatch_intent": consumer_receiver_response_priority[
            "receiver_dispatch_intent"
        ],
        "receiver_dispatch_mode": consumer_receiver_response_priority[
            "receiver_dispatch_mode"
        ],
        "receiver_release_gate": consumer_receiver_response_priority[
            "receiver_release_gate"
        ],
        "receiver_progress_state": consumer_receiver_response_priority[
            "receiver_progress_state"
        ],
        "receiver_progress_signal": consumer_receiver_response_priority[
            "receiver_progress_signal"
        ],
        "receiver_progress_outcome": consumer_receiver_response_priority[
            "receiver_progress_outcome"
        ],
        "receiver_intervention_requirement": consumer_receiver_response_priority[
            "receiver_intervention_requirement"
        ],
        "receiver_attention_level": consumer_receiver_response_priority[
            "receiver_attention_level"
        ],
        "receiver_notification_requirement": consumer_receiver_response_priority[
            "receiver_notification_requirement"
        ],
        "receiver_response_priority": consumer_receiver_response_priority[
            "receiver_response_priority"
        ],
        "receiver_response_channel": response_channel_by_priority[
            consumer_receiver_response_priority["receiver_response_priority"]
        ],
    }
    if "related_project_id" in consumer_receiver_response_priority:
        response_channel["related_project_id"] = consumer_receiver_response_priority[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_receiver_response_priority:
        response_channel["related_activation_decision_id"] = (
            consumer_receiver_response_priority["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_receiver_response_priority:
        response_channel["related_packet_id"] = consumer_receiver_response_priority[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_receiver_response_priority:
        response_channel["related_queue_item_id"] = consumer_receiver_response_priority[
            "related_queue_item_id"
        ]
    return response_channel


def build_consumer_receiver_response_route_from_channel(
    *,
    consumer_receiver_response_channel: dict[str, Any],
) -> dict[str, Any]:
    """Build pure receiver response route from existing response channel."""
    response_route_by_channel = {
        "standard_channel": "standard_route",
        "priority_channel": "priority_route",
        "escalation_channel": "escalation_route",
    }
    response_route: dict[str, Any] = {
        "projected_activation_decision": consumer_receiver_response_channel[
            "projected_activation_decision"
        ],
        "approval_record": consumer_receiver_response_channel["approval_record"],
        "receiver_readiness_classification": consumer_receiver_response_channel[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_receiver_response_channel[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_receiver_response_channel[
            "receiver_action_label"
        ],
        "receiver_dispatch_intent": consumer_receiver_response_channel[
            "receiver_dispatch_intent"
        ],
        "receiver_dispatch_mode": consumer_receiver_response_channel[
            "receiver_dispatch_mode"
        ],
        "receiver_release_gate": consumer_receiver_response_channel[
            "receiver_release_gate"
        ],
        "receiver_progress_state": consumer_receiver_response_channel[
            "receiver_progress_state"
        ],
        "receiver_progress_signal": consumer_receiver_response_channel[
            "receiver_progress_signal"
        ],
        "receiver_progress_outcome": consumer_receiver_response_channel[
            "receiver_progress_outcome"
        ],
        "receiver_intervention_requirement": consumer_receiver_response_channel[
            "receiver_intervention_requirement"
        ],
        "receiver_attention_level": consumer_receiver_response_channel[
            "receiver_attention_level"
        ],
        "receiver_notification_requirement": consumer_receiver_response_channel[
            "receiver_notification_requirement"
        ],
        "receiver_response_priority": consumer_receiver_response_channel[
            "receiver_response_priority"
        ],
        "receiver_response_channel": consumer_receiver_response_channel[
            "receiver_response_channel"
        ],
        "receiver_response_route": response_route_by_channel[
            consumer_receiver_response_channel["receiver_response_channel"]
        ],
    }
    if "related_project_id" in consumer_receiver_response_channel:
        response_route["related_project_id"] = consumer_receiver_response_channel[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_receiver_response_channel:
        response_route["related_activation_decision_id"] = (
            consumer_receiver_response_channel["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_receiver_response_channel:
        response_route["related_packet_id"] = consumer_receiver_response_channel[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_receiver_response_channel:
        response_route["related_queue_item_id"] = consumer_receiver_response_channel[
            "related_queue_item_id"
        ]
    return response_route


def build_consumer_receiver_followup_requirement_from_response_route(
    *,
    consumer_receiver_response_route: dict[str, Any],
) -> dict[str, Any]:
    """Build pure receiver follow-up requirement from existing response route."""
    followup_requirement_by_route = {
        "standard_route": "none",
        "priority_route": "follow_up",
        "escalation_route": "escalation_follow_up",
    }
    followup_requirement: dict[str, Any] = {
        "projected_activation_decision": consumer_receiver_response_route[
            "projected_activation_decision"
        ],
        "approval_record": consumer_receiver_response_route["approval_record"],
        "receiver_readiness_classification": consumer_receiver_response_route[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_receiver_response_route[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_receiver_response_route[
            "receiver_action_label"
        ],
        "receiver_dispatch_intent": consumer_receiver_response_route[
            "receiver_dispatch_intent"
        ],
        "receiver_dispatch_mode": consumer_receiver_response_route[
            "receiver_dispatch_mode"
        ],
        "receiver_release_gate": consumer_receiver_response_route[
            "receiver_release_gate"
        ],
        "receiver_progress_state": consumer_receiver_response_route[
            "receiver_progress_state"
        ],
        "receiver_progress_signal": consumer_receiver_response_route[
            "receiver_progress_signal"
        ],
        "receiver_progress_outcome": consumer_receiver_response_route[
            "receiver_progress_outcome"
        ],
        "receiver_intervention_requirement": consumer_receiver_response_route[
            "receiver_intervention_requirement"
        ],
        "receiver_attention_level": consumer_receiver_response_route[
            "receiver_attention_level"
        ],
        "receiver_notification_requirement": consumer_receiver_response_route[
            "receiver_notification_requirement"
        ],
        "receiver_response_priority": consumer_receiver_response_route[
            "receiver_response_priority"
        ],
        "receiver_response_channel": consumer_receiver_response_route[
            "receiver_response_channel"
        ],
        "receiver_response_route": consumer_receiver_response_route[
            "receiver_response_route"
        ],
        "receiver_followup_requirement": followup_requirement_by_route[
            consumer_receiver_response_route["receiver_response_route"]
        ],
    }
    if "related_project_id" in consumer_receiver_response_route:
        followup_requirement["related_project_id"] = consumer_receiver_response_route[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_receiver_response_route:
        followup_requirement["related_activation_decision_id"] = (
            consumer_receiver_response_route["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_receiver_response_route:
        followup_requirement["related_packet_id"] = consumer_receiver_response_route[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_receiver_response_route:
        followup_requirement["related_queue_item_id"] = consumer_receiver_response_route[
            "related_queue_item_id"
        ]
    return followup_requirement


def build_consumer_decision_surface_from_followup_requirement(
    *,
    consumer_receiver_followup_requirement: dict[str, Any],
) -> dict[str, Any]:
    """Build pure consumer decision surface from existing follow-up requirement."""
    consumer_decision_surface: dict[str, Any] = {
        "projected_activation_decision": consumer_receiver_followup_requirement[
            "projected_activation_decision"
        ],
        "approval_record": consumer_receiver_followup_requirement["approval_record"],
        "receiver_readiness_classification": consumer_receiver_followup_requirement[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_receiver_followup_requirement[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_receiver_followup_requirement[
            "receiver_action_label"
        ],
        "receiver_dispatch_intent": consumer_receiver_followup_requirement[
            "receiver_dispatch_intent"
        ],
        "receiver_dispatch_mode": consumer_receiver_followup_requirement[
            "receiver_dispatch_mode"
        ],
        "receiver_release_gate": consumer_receiver_followup_requirement[
            "receiver_release_gate"
        ],
        "receiver_progress_state": consumer_receiver_followup_requirement[
            "receiver_progress_state"
        ],
        "receiver_progress_signal": consumer_receiver_followup_requirement[
            "receiver_progress_signal"
        ],
        "receiver_progress_outcome": consumer_receiver_followup_requirement[
            "receiver_progress_outcome"
        ],
        "receiver_intervention_requirement": consumer_receiver_followup_requirement[
            "receiver_intervention_requirement"
        ],
        "receiver_attention_level": consumer_receiver_followup_requirement[
            "receiver_attention_level"
        ],
        "receiver_notification_requirement": consumer_receiver_followup_requirement[
            "receiver_notification_requirement"
        ],
        "receiver_response_priority": consumer_receiver_followup_requirement[
            "receiver_response_priority"
        ],
        "receiver_response_channel": consumer_receiver_followup_requirement[
            "receiver_response_channel"
        ],
        "receiver_response_route": consumer_receiver_followup_requirement[
            "receiver_response_route"
        ],
        "receiver_followup_requirement": consumer_receiver_followup_requirement[
            "receiver_followup_requirement"
        ],
    }
    if "related_project_id" in consumer_receiver_followup_requirement:
        consumer_decision_surface["related_project_id"] = (
            consumer_receiver_followup_requirement["related_project_id"]
        )
    if "related_activation_decision_id" in consumer_receiver_followup_requirement:
        consumer_decision_surface["related_activation_decision_id"] = (
            consumer_receiver_followup_requirement["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_receiver_followup_requirement:
        consumer_decision_surface["related_packet_id"] = (
            consumer_receiver_followup_requirement["related_packet_id"]
        )
    if "related_queue_item_id" in consumer_receiver_followup_requirement:
        consumer_decision_surface["related_queue_item_id"] = (
            consumer_receiver_followup_requirement["related_queue_item_id"]
        )
    return consumer_decision_surface


def build_consumer_decision_posture_from_surface(
    *,
    consumer_decision_surface: dict[str, Any],
) -> dict[str, Any]:
    """Build pure consumer decision posture from existing decision surface."""
    posture_by_followup_requirement = {
        "none": "observe",
        "follow_up": "engage",
        "escalation_follow_up": "escalate",
    }
    consumer_decision_posture: dict[str, Any] = {
        "projected_activation_decision": consumer_decision_surface[
            "projected_activation_decision"
        ],
        "approval_record": consumer_decision_surface["approval_record"],
        "receiver_readiness_classification": consumer_decision_surface[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_decision_surface[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_decision_surface["receiver_action_label"],
        "receiver_dispatch_intent": consumer_decision_surface["receiver_dispatch_intent"],
        "receiver_dispatch_mode": consumer_decision_surface["receiver_dispatch_mode"],
        "receiver_release_gate": consumer_decision_surface["receiver_release_gate"],
        "receiver_progress_state": consumer_decision_surface["receiver_progress_state"],
        "receiver_progress_signal": consumer_decision_surface["receiver_progress_signal"],
        "receiver_progress_outcome": consumer_decision_surface["receiver_progress_outcome"],
        "receiver_intervention_requirement": consumer_decision_surface[
            "receiver_intervention_requirement"
        ],
        "receiver_attention_level": consumer_decision_surface["receiver_attention_level"],
        "receiver_notification_requirement": consumer_decision_surface[
            "receiver_notification_requirement"
        ],
        "receiver_response_priority": consumer_decision_surface[
            "receiver_response_priority"
        ],
        "receiver_response_channel": consumer_decision_surface["receiver_response_channel"],
        "receiver_response_route": consumer_decision_surface["receiver_response_route"],
        "receiver_followup_requirement": consumer_decision_surface[
            "receiver_followup_requirement"
        ],
        "consumer_decision_posture": posture_by_followup_requirement[
            consumer_decision_surface["receiver_followup_requirement"]
        ],
    }
    if "related_project_id" in consumer_decision_surface:
        consumer_decision_posture["related_project_id"] = consumer_decision_surface[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_decision_surface:
        consumer_decision_posture["related_activation_decision_id"] = (
            consumer_decision_surface["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_decision_surface:
        consumer_decision_posture["related_packet_id"] = consumer_decision_surface[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_decision_surface:
        consumer_decision_posture["related_queue_item_id"] = consumer_decision_surface[
            "related_queue_item_id"
        ]
    return consumer_decision_posture


def build_consumer_action_requirement_from_posture(
    *,
    consumer_decision_posture: dict[str, Any],
) -> dict[str, Any]:
    """Build pure consumer action requirement from existing decision posture."""
    action_requirement_by_posture = {
        "observe": "no_action",
        "engage": "action_required",
        "escalate": "escalation_required",
    }
    consumer_action_requirement: dict[str, Any] = {
        "projected_activation_decision": consumer_decision_posture[
            "projected_activation_decision"
        ],
        "approval_record": consumer_decision_posture["approval_record"],
        "receiver_readiness_classification": consumer_decision_posture[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_decision_posture[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_decision_posture["receiver_action_label"],
        "receiver_dispatch_intent": consumer_decision_posture["receiver_dispatch_intent"],
        "receiver_dispatch_mode": consumer_decision_posture["receiver_dispatch_mode"],
        "receiver_release_gate": consumer_decision_posture["receiver_release_gate"],
        "receiver_progress_state": consumer_decision_posture["receiver_progress_state"],
        "receiver_progress_signal": consumer_decision_posture["receiver_progress_signal"],
        "receiver_progress_outcome": consumer_decision_posture["receiver_progress_outcome"],
        "receiver_intervention_requirement": consumer_decision_posture[
            "receiver_intervention_requirement"
        ],
        "receiver_attention_level": consumer_decision_posture["receiver_attention_level"],
        "receiver_notification_requirement": consumer_decision_posture[
            "receiver_notification_requirement"
        ],
        "receiver_response_priority": consumer_decision_posture[
            "receiver_response_priority"
        ],
        "receiver_response_channel": consumer_decision_posture["receiver_response_channel"],
        "receiver_response_route": consumer_decision_posture["receiver_response_route"],
        "receiver_followup_requirement": consumer_decision_posture[
            "receiver_followup_requirement"
        ],
        "consumer_decision_posture": consumer_decision_posture[
            "consumer_decision_posture"
        ],
        "consumer_action_requirement": action_requirement_by_posture[
            consumer_decision_posture["consumer_decision_posture"]
        ],
    }
    if "related_project_id" in consumer_decision_posture:
        consumer_action_requirement["related_project_id"] = consumer_decision_posture[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_decision_posture:
        consumer_action_requirement["related_activation_decision_id"] = (
            consumer_decision_posture["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_decision_posture:
        consumer_action_requirement["related_packet_id"] = consumer_decision_posture[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_decision_posture:
        consumer_action_requirement["related_queue_item_id"] = consumer_decision_posture[
            "related_queue_item_id"
        ]
    return consumer_action_requirement


def build_consumer_work_queue_assignment_from_action_requirement(
    *,
    consumer_action_requirement: dict[str, Any],
) -> dict[str, Any]:
    """Build pure consumer work-queue assignment from existing action requirement."""
    queue_assignment_by_action_requirement = {
        "no_action": "observation_queue",
        "action_required": "action_queue",
        "escalation_required": "escalation_queue",
    }
    consumer_work_queue_assignment: dict[str, Any] = {
        "projected_activation_decision": consumer_action_requirement[
            "projected_activation_decision"
        ],
        "approval_record": consumer_action_requirement["approval_record"],
        "receiver_readiness_classification": consumer_action_requirement[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_action_requirement[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_action_requirement["receiver_action_label"],
        "receiver_dispatch_intent": consumer_action_requirement["receiver_dispatch_intent"],
        "receiver_dispatch_mode": consumer_action_requirement["receiver_dispatch_mode"],
        "receiver_release_gate": consumer_action_requirement["receiver_release_gate"],
        "receiver_progress_state": consumer_action_requirement["receiver_progress_state"],
        "receiver_progress_signal": consumer_action_requirement["receiver_progress_signal"],
        "receiver_progress_outcome": consumer_action_requirement["receiver_progress_outcome"],
        "receiver_intervention_requirement": consumer_action_requirement[
            "receiver_intervention_requirement"
        ],
        "receiver_attention_level": consumer_action_requirement["receiver_attention_level"],
        "receiver_notification_requirement": consumer_action_requirement[
            "receiver_notification_requirement"
        ],
        "receiver_response_priority": consumer_action_requirement[
            "receiver_response_priority"
        ],
        "receiver_response_channel": consumer_action_requirement["receiver_response_channel"],
        "receiver_response_route": consumer_action_requirement["receiver_response_route"],
        "receiver_followup_requirement": consumer_action_requirement[
            "receiver_followup_requirement"
        ],
        "consumer_decision_posture": consumer_action_requirement[
            "consumer_decision_posture"
        ],
        "consumer_action_requirement": consumer_action_requirement[
            "consumer_action_requirement"
        ],
        "consumer_work_queue_assignment": queue_assignment_by_action_requirement[
            consumer_action_requirement["consumer_action_requirement"]
        ],
    }
    if "related_project_id" in consumer_action_requirement:
        consumer_work_queue_assignment["related_project_id"] = consumer_action_requirement[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_action_requirement:
        consumer_work_queue_assignment["related_activation_decision_id"] = (
            consumer_action_requirement["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_action_requirement:
        consumer_work_queue_assignment["related_packet_id"] = consumer_action_requirement[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_action_requirement:
        consumer_work_queue_assignment["related_queue_item_id"] = (
            consumer_action_requirement["related_queue_item_id"]
        )
    return consumer_work_queue_assignment


def build_consumer_processing_plan_from_work_queue_assignment(
    *,
    consumer_work_queue_assignment: dict[str, Any],
) -> dict[str, Any]:
    """Build pure consumer processing plan from existing work-queue assignment."""
    processing_plan_by_queue_assignment = {
        "observation_queue": "observe_only",
        "action_queue": "process_action",
        "escalation_queue": "process_escalation",
    }
    consumer_processing_plan: dict[str, Any] = {
        "projected_activation_decision": consumer_work_queue_assignment[
            "projected_activation_decision"
        ],
        "approval_record": consumer_work_queue_assignment["approval_record"],
        "receiver_readiness_classification": consumer_work_queue_assignment[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_work_queue_assignment[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_work_queue_assignment["receiver_action_label"],
        "receiver_dispatch_intent": consumer_work_queue_assignment[
            "receiver_dispatch_intent"
        ],
        "receiver_dispatch_mode": consumer_work_queue_assignment["receiver_dispatch_mode"],
        "receiver_release_gate": consumer_work_queue_assignment["receiver_release_gate"],
        "receiver_progress_state": consumer_work_queue_assignment["receiver_progress_state"],
        "receiver_progress_signal": consumer_work_queue_assignment[
            "receiver_progress_signal"
        ],
        "receiver_progress_outcome": consumer_work_queue_assignment[
            "receiver_progress_outcome"
        ],
        "receiver_intervention_requirement": consumer_work_queue_assignment[
            "receiver_intervention_requirement"
        ],
        "receiver_attention_level": consumer_work_queue_assignment["receiver_attention_level"],
        "receiver_notification_requirement": consumer_work_queue_assignment[
            "receiver_notification_requirement"
        ],
        "receiver_response_priority": consumer_work_queue_assignment[
            "receiver_response_priority"
        ],
        "receiver_response_channel": consumer_work_queue_assignment[
            "receiver_response_channel"
        ],
        "receiver_response_route": consumer_work_queue_assignment["receiver_response_route"],
        "receiver_followup_requirement": consumer_work_queue_assignment[
            "receiver_followup_requirement"
        ],
        "consumer_decision_posture": consumer_work_queue_assignment[
            "consumer_decision_posture"
        ],
        "consumer_action_requirement": consumer_work_queue_assignment[
            "consumer_action_requirement"
        ],
        "consumer_work_queue_assignment": consumer_work_queue_assignment[
            "consumer_work_queue_assignment"
        ],
        "consumer_processing_plan": processing_plan_by_queue_assignment[
            consumer_work_queue_assignment["consumer_work_queue_assignment"]
        ],
    }
    if "related_project_id" in consumer_work_queue_assignment:
        consumer_processing_plan["related_project_id"] = consumer_work_queue_assignment[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_work_queue_assignment:
        consumer_processing_plan["related_activation_decision_id"] = (
            consumer_work_queue_assignment["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_work_queue_assignment:
        consumer_processing_plan["related_packet_id"] = consumer_work_queue_assignment[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_work_queue_assignment:
        consumer_processing_plan["related_queue_item_id"] = (
            consumer_work_queue_assignment["related_queue_item_id"]
        )
    return consumer_processing_plan


def build_consumer_operator_requirement_from_processing_plan(
    *,
    consumer_processing_plan: dict[str, Any],
) -> dict[str, Any]:
    """Build pure consumer operator requirement from existing processing plan."""
    operator_requirement_by_processing_plan = {
        "observe_only": "none",
        "process_action": "operator_required",
        "process_escalation": "senior_operator_required",
    }
    consumer_operator_requirement: dict[str, Any] = {
        "projected_activation_decision": consumer_processing_plan[
            "projected_activation_decision"
        ],
        "approval_record": consumer_processing_plan["approval_record"],
        "receiver_readiness_classification": consumer_processing_plan[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_processing_plan[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_processing_plan["receiver_action_label"],
        "receiver_dispatch_intent": consumer_processing_plan["receiver_dispatch_intent"],
        "receiver_dispatch_mode": consumer_processing_plan["receiver_dispatch_mode"],
        "receiver_release_gate": consumer_processing_plan["receiver_release_gate"],
        "receiver_progress_state": consumer_processing_plan["receiver_progress_state"],
        "receiver_progress_signal": consumer_processing_plan["receiver_progress_signal"],
        "receiver_progress_outcome": consumer_processing_plan["receiver_progress_outcome"],
        "receiver_intervention_requirement": consumer_processing_plan[
            "receiver_intervention_requirement"
        ],
        "receiver_attention_level": consumer_processing_plan["receiver_attention_level"],
        "receiver_notification_requirement": consumer_processing_plan[
            "receiver_notification_requirement"
        ],
        "receiver_response_priority": consumer_processing_plan["receiver_response_priority"],
        "receiver_response_channel": consumer_processing_plan["receiver_response_channel"],
        "receiver_response_route": consumer_processing_plan["receiver_response_route"],
        "receiver_followup_requirement": consumer_processing_plan[
            "receiver_followup_requirement"
        ],
        "consumer_decision_posture": consumer_processing_plan["consumer_decision_posture"],
        "consumer_action_requirement": consumer_processing_plan[
            "consumer_action_requirement"
        ],
        "consumer_work_queue_assignment": consumer_processing_plan[
            "consumer_work_queue_assignment"
        ],
        "consumer_processing_plan": consumer_processing_plan["consumer_processing_plan"],
        "consumer_operator_requirement": operator_requirement_by_processing_plan[
            consumer_processing_plan["consumer_processing_plan"]
        ],
    }
    if "related_project_id" in consumer_processing_plan:
        consumer_operator_requirement["related_project_id"] = consumer_processing_plan[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_processing_plan:
        consumer_operator_requirement["related_activation_decision_id"] = (
            consumer_processing_plan["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_processing_plan:
        consumer_operator_requirement["related_packet_id"] = consumer_processing_plan[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_processing_plan:
        consumer_operator_requirement["related_queue_item_id"] = (
            consumer_processing_plan["related_queue_item_id"]
        )
    return consumer_operator_requirement


def build_consumer_assignment_lane_from_operator_requirement(
    *,
    consumer_operator_requirement: dict[str, Any],
) -> dict[str, Any]:
    """Build pure consumer assignment lane from existing operator requirement."""
    assignment_lane_by_operator_requirement = {
        "none": "self_service_lane",
        "operator_required": "operator_lane",
        "senior_operator_required": "senior_operator_lane",
    }
    consumer_assignment_lane: dict[str, Any] = {
        "projected_activation_decision": consumer_operator_requirement[
            "projected_activation_decision"
        ],
        "approval_record": consumer_operator_requirement["approval_record"],
        "receiver_readiness_classification": consumer_operator_requirement[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_operator_requirement[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_operator_requirement["receiver_action_label"],
        "receiver_dispatch_intent": consumer_operator_requirement["receiver_dispatch_intent"],
        "receiver_dispatch_mode": consumer_operator_requirement["receiver_dispatch_mode"],
        "receiver_release_gate": consumer_operator_requirement["receiver_release_gate"],
        "receiver_progress_state": consumer_operator_requirement["receiver_progress_state"],
        "receiver_progress_signal": consumer_operator_requirement["receiver_progress_signal"],
        "receiver_progress_outcome": consumer_operator_requirement[
            "receiver_progress_outcome"
        ],
        "receiver_intervention_requirement": consumer_operator_requirement[
            "receiver_intervention_requirement"
        ],
        "receiver_attention_level": consumer_operator_requirement["receiver_attention_level"],
        "receiver_notification_requirement": consumer_operator_requirement[
            "receiver_notification_requirement"
        ],
        "receiver_response_priority": consumer_operator_requirement[
            "receiver_response_priority"
        ],
        "receiver_response_channel": consumer_operator_requirement["receiver_response_channel"],
        "receiver_response_route": consumer_operator_requirement["receiver_response_route"],
        "receiver_followup_requirement": consumer_operator_requirement[
            "receiver_followup_requirement"
        ],
        "consumer_decision_posture": consumer_operator_requirement[
            "consumer_decision_posture"
        ],
        "consumer_action_requirement": consumer_operator_requirement[
            "consumer_action_requirement"
        ],
        "consumer_work_queue_assignment": consumer_operator_requirement[
            "consumer_work_queue_assignment"
        ],
        "consumer_processing_plan": consumer_operator_requirement[
            "consumer_processing_plan"
        ],
        "consumer_operator_requirement": consumer_operator_requirement[
            "consumer_operator_requirement"
        ],
        "consumer_assignment_lane": assignment_lane_by_operator_requirement[
            consumer_operator_requirement["consumer_operator_requirement"]
        ],
    }
    if "related_project_id" in consumer_operator_requirement:
        consumer_assignment_lane["related_project_id"] = consumer_operator_requirement[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_operator_requirement:
        consumer_assignment_lane["related_activation_decision_id"] = (
            consumer_operator_requirement["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_operator_requirement:
        consumer_assignment_lane["related_packet_id"] = consumer_operator_requirement[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_operator_requirement:
        consumer_assignment_lane["related_queue_item_id"] = (
            consumer_operator_requirement["related_queue_item_id"]
        )
    return consumer_assignment_lane


def build_consumer_service_tier_from_assignment_lane(
    *,
    consumer_assignment_lane: dict[str, Any],
) -> dict[str, Any]:
    """Build pure consumer service tier from existing assignment lane."""
    service_tier_by_assignment_lane = {
        "self_service_lane": "self_service",
        "operator_lane": "operator_managed",
        "senior_operator_lane": "senior_managed",
    }
    consumer_service_tier: dict[str, Any] = {
        "projected_activation_decision": consumer_assignment_lane[
            "projected_activation_decision"
        ],
        "approval_record": consumer_assignment_lane["approval_record"],
        "receiver_readiness_classification": consumer_assignment_lane[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_assignment_lane[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_assignment_lane["receiver_action_label"],
        "receiver_dispatch_intent": consumer_assignment_lane["receiver_dispatch_intent"],
        "receiver_dispatch_mode": consumer_assignment_lane["receiver_dispatch_mode"],
        "receiver_release_gate": consumer_assignment_lane["receiver_release_gate"],
        "receiver_progress_state": consumer_assignment_lane["receiver_progress_state"],
        "receiver_progress_signal": consumer_assignment_lane["receiver_progress_signal"],
        "receiver_progress_outcome": consumer_assignment_lane["receiver_progress_outcome"],
        "receiver_intervention_requirement": consumer_assignment_lane[
            "receiver_intervention_requirement"
        ],
        "receiver_attention_level": consumer_assignment_lane["receiver_attention_level"],
        "receiver_notification_requirement": consumer_assignment_lane[
            "receiver_notification_requirement"
        ],
        "receiver_response_priority": consumer_assignment_lane[
            "receiver_response_priority"
        ],
        "receiver_response_channel": consumer_assignment_lane["receiver_response_channel"],
        "receiver_response_route": consumer_assignment_lane["receiver_response_route"],
        "receiver_followup_requirement": consumer_assignment_lane[
            "receiver_followup_requirement"
        ],
        "consumer_decision_posture": consumer_assignment_lane["consumer_decision_posture"],
        "consumer_action_requirement": consumer_assignment_lane[
            "consumer_action_requirement"
        ],
        "consumer_work_queue_assignment": consumer_assignment_lane[
            "consumer_work_queue_assignment"
        ],
        "consumer_processing_plan": consumer_assignment_lane["consumer_processing_plan"],
        "consumer_operator_requirement": consumer_assignment_lane[
            "consumer_operator_requirement"
        ],
        "consumer_assignment_lane": consumer_assignment_lane["consumer_assignment_lane"],
        "consumer_service_tier": service_tier_by_assignment_lane[
            consumer_assignment_lane["consumer_assignment_lane"]
        ],
    }
    if "related_project_id" in consumer_assignment_lane:
        consumer_service_tier["related_project_id"] = consumer_assignment_lane[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_assignment_lane:
        consumer_service_tier["related_activation_decision_id"] = (
            consumer_assignment_lane["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_assignment_lane:
        consumer_service_tier["related_packet_id"] = consumer_assignment_lane[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_assignment_lane:
        consumer_service_tier["related_queue_item_id"] = consumer_assignment_lane[
            "related_queue_item_id"
        ]
    return consumer_service_tier


def build_consumer_sla_class_from_service_tier(
    *,
    consumer_service_tier: dict[str, Any],
) -> dict[str, Any]:
    """Build pure consumer SLA class from existing service tier."""
    sla_class_by_service_tier = {
        "self_service": "deferred",
        "operator_managed": "standard",
        "senior_managed": "priority",
    }
    consumer_sla_class: dict[str, Any] = {
        "projected_activation_decision": consumer_service_tier[
            "projected_activation_decision"
        ],
        "approval_record": consumer_service_tier["approval_record"],
        "receiver_readiness_classification": consumer_service_tier[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_service_tier[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_service_tier["receiver_action_label"],
        "receiver_dispatch_intent": consumer_service_tier["receiver_dispatch_intent"],
        "receiver_dispatch_mode": consumer_service_tier["receiver_dispatch_mode"],
        "receiver_release_gate": consumer_service_tier["receiver_release_gate"],
        "receiver_progress_state": consumer_service_tier["receiver_progress_state"],
        "receiver_progress_signal": consumer_service_tier["receiver_progress_signal"],
        "receiver_progress_outcome": consumer_service_tier["receiver_progress_outcome"],
        "receiver_intervention_requirement": consumer_service_tier[
            "receiver_intervention_requirement"
        ],
        "receiver_attention_level": consumer_service_tier["receiver_attention_level"],
        "receiver_notification_requirement": consumer_service_tier[
            "receiver_notification_requirement"
        ],
        "receiver_response_priority": consumer_service_tier["receiver_response_priority"],
        "receiver_response_channel": consumer_service_tier["receiver_response_channel"],
        "receiver_response_route": consumer_service_tier["receiver_response_route"],
        "receiver_followup_requirement": consumer_service_tier[
            "receiver_followup_requirement"
        ],
        "consumer_decision_posture": consumer_service_tier["consumer_decision_posture"],
        "consumer_action_requirement": consumer_service_tier[
            "consumer_action_requirement"
        ],
        "consumer_work_queue_assignment": consumer_service_tier[
            "consumer_work_queue_assignment"
        ],
        "consumer_processing_plan": consumer_service_tier["consumer_processing_plan"],
        "consumer_operator_requirement": consumer_service_tier[
            "consumer_operator_requirement"
        ],
        "consumer_assignment_lane": consumer_service_tier["consumer_assignment_lane"],
        "consumer_service_tier": consumer_service_tier["consumer_service_tier"],
        "consumer_sla_class": sla_class_by_service_tier[
            consumer_service_tier["consumer_service_tier"]
        ],
    }
    if "related_project_id" in consumer_service_tier:
        consumer_sla_class["related_project_id"] = consumer_service_tier[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_service_tier:
        consumer_sla_class["related_activation_decision_id"] = (
            consumer_service_tier["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_service_tier:
        consumer_sla_class["related_packet_id"] = consumer_service_tier[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_service_tier:
        consumer_sla_class["related_queue_item_id"] = consumer_service_tier[
            "related_queue_item_id"
        ]
    return consumer_sla_class


def build_consumer_response_window_from_sla_class(
    *,
    consumer_sla_class: dict[str, Any],
) -> dict[str, Any]:
    """Build pure consumer response window from existing SLA class."""
    response_window_by_sla_class = {
        "deferred": "backlog_window",
        "standard": "standard_window",
        "priority": "priority_window",
    }
    consumer_response_window: dict[str, Any] = {
        "projected_activation_decision": consumer_sla_class[
            "projected_activation_decision"
        ],
        "approval_record": consumer_sla_class["approval_record"],
        "receiver_readiness_classification": consumer_sla_class[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_sla_class[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_sla_class["receiver_action_label"],
        "receiver_dispatch_intent": consumer_sla_class["receiver_dispatch_intent"],
        "receiver_dispatch_mode": consumer_sla_class["receiver_dispatch_mode"],
        "receiver_release_gate": consumer_sla_class["receiver_release_gate"],
        "receiver_progress_state": consumer_sla_class["receiver_progress_state"],
        "receiver_progress_signal": consumer_sla_class["receiver_progress_signal"],
        "receiver_progress_outcome": consumer_sla_class["receiver_progress_outcome"],
        "receiver_intervention_requirement": consumer_sla_class[
            "receiver_intervention_requirement"
        ],
        "receiver_attention_level": consumer_sla_class["receiver_attention_level"],
        "receiver_notification_requirement": consumer_sla_class[
            "receiver_notification_requirement"
        ],
        "receiver_response_priority": consumer_sla_class["receiver_response_priority"],
        "receiver_response_channel": consumer_sla_class["receiver_response_channel"],
        "receiver_response_route": consumer_sla_class["receiver_response_route"],
        "receiver_followup_requirement": consumer_sla_class[
            "receiver_followup_requirement"
        ],
        "consumer_decision_posture": consumer_sla_class["consumer_decision_posture"],
        "consumer_action_requirement": consumer_sla_class[
            "consumer_action_requirement"
        ],
        "consumer_work_queue_assignment": consumer_sla_class[
            "consumer_work_queue_assignment"
        ],
        "consumer_processing_plan": consumer_sla_class["consumer_processing_plan"],
        "consumer_operator_requirement": consumer_sla_class[
            "consumer_operator_requirement"
        ],
        "consumer_assignment_lane": consumer_sla_class["consumer_assignment_lane"],
        "consumer_service_tier": consumer_sla_class["consumer_service_tier"],
        "consumer_sla_class": consumer_sla_class["consumer_sla_class"],
        "consumer_response_window": response_window_by_sla_class[
            consumer_sla_class["consumer_sla_class"]
        ],
    }
    if "related_project_id" in consumer_sla_class:
        consumer_response_window["related_project_id"] = consumer_sla_class[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_sla_class:
        consumer_response_window["related_activation_decision_id"] = (
            consumer_sla_class["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_sla_class:
        consumer_response_window["related_packet_id"] = consumer_sla_class[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_sla_class:
        consumer_response_window["related_queue_item_id"] = consumer_sla_class[
            "related_queue_item_id"
        ]
    return consumer_response_window


def build_consumer_timing_posture_from_response_window(
    *,
    consumer_response_window: dict[str, Any],
) -> dict[str, Any]:
    """Build pure consumer timing posture from existing response window."""
    timing_posture_by_response_window = {
        "backlog_window": "later",
        "standard_window": "scheduled",
        "priority_window": "immediate",
    }
    consumer_timing_posture: dict[str, Any] = {
        "projected_activation_decision": consumer_response_window[
            "projected_activation_decision"
        ],
        "approval_record": consumer_response_window["approval_record"],
        "receiver_readiness_classification": consumer_response_window[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_response_window[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_response_window["receiver_action_label"],
        "receiver_dispatch_intent": consumer_response_window["receiver_dispatch_intent"],
        "receiver_dispatch_mode": consumer_response_window["receiver_dispatch_mode"],
        "receiver_release_gate": consumer_response_window["receiver_release_gate"],
        "receiver_progress_state": consumer_response_window["receiver_progress_state"],
        "receiver_progress_signal": consumer_response_window["receiver_progress_signal"],
        "receiver_progress_outcome": consumer_response_window["receiver_progress_outcome"],
        "receiver_intervention_requirement": consumer_response_window[
            "receiver_intervention_requirement"
        ],
        "receiver_attention_level": consumer_response_window["receiver_attention_level"],
        "receiver_notification_requirement": consumer_response_window[
            "receiver_notification_requirement"
        ],
        "receiver_response_priority": consumer_response_window["receiver_response_priority"],
        "receiver_response_channel": consumer_response_window["receiver_response_channel"],
        "receiver_response_route": consumer_response_window["receiver_response_route"],
        "receiver_followup_requirement": consumer_response_window[
            "receiver_followup_requirement"
        ],
        "consumer_decision_posture": consumer_response_window["consumer_decision_posture"],
        "consumer_action_requirement": consumer_response_window[
            "consumer_action_requirement"
        ],
        "consumer_work_queue_assignment": consumer_response_window[
            "consumer_work_queue_assignment"
        ],
        "consumer_processing_plan": consumer_response_window["consumer_processing_plan"],
        "consumer_operator_requirement": consumer_response_window[
            "consumer_operator_requirement"
        ],
        "consumer_assignment_lane": consumer_response_window["consumer_assignment_lane"],
        "consumer_service_tier": consumer_response_window["consumer_service_tier"],
        "consumer_sla_class": consumer_response_window["consumer_sla_class"],
        "consumer_response_window": consumer_response_window["consumer_response_window"],
        "consumer_timing_posture": timing_posture_by_response_window[
            consumer_response_window["consumer_response_window"]
        ],
    }
    if "related_project_id" in consumer_response_window:
        consumer_timing_posture["related_project_id"] = consumer_response_window[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_response_window:
        consumer_timing_posture["related_activation_decision_id"] = (
            consumer_response_window["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_response_window:
        consumer_timing_posture["related_packet_id"] = consumer_response_window[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_response_window:
        consumer_timing_posture["related_queue_item_id"] = consumer_response_window[
            "related_queue_item_id"
        ]
    return consumer_timing_posture


def build_consumer_scheduling_commitment_from_timing_posture(
    *,
    consumer_timing_posture: dict[str, Any],
) -> dict[str, Any]:
    """Build pure consumer scheduling commitment from existing timing posture."""
    scheduling_commitment_by_timing_posture = {
        "later": "backlog_commitment",
        "scheduled": "scheduled_commitment",
        "immediate": "immediate_commitment",
    }
    consumer_scheduling_commitment: dict[str, Any] = {
        "projected_activation_decision": consumer_timing_posture[
            "projected_activation_decision"
        ],
        "approval_record": consumer_timing_posture["approval_record"],
        "receiver_readiness_classification": consumer_timing_posture[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_timing_posture[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_timing_posture["receiver_action_label"],
        "receiver_dispatch_intent": consumer_timing_posture["receiver_dispatch_intent"],
        "receiver_dispatch_mode": consumer_timing_posture["receiver_dispatch_mode"],
        "receiver_release_gate": consumer_timing_posture["receiver_release_gate"],
        "receiver_progress_state": consumer_timing_posture["receiver_progress_state"],
        "receiver_progress_signal": consumer_timing_posture["receiver_progress_signal"],
        "receiver_progress_outcome": consumer_timing_posture["receiver_progress_outcome"],
        "receiver_intervention_requirement": consumer_timing_posture[
            "receiver_intervention_requirement"
        ],
        "receiver_attention_level": consumer_timing_posture["receiver_attention_level"],
        "receiver_notification_requirement": consumer_timing_posture[
            "receiver_notification_requirement"
        ],
        "receiver_response_priority": consumer_timing_posture["receiver_response_priority"],
        "receiver_response_channel": consumer_timing_posture["receiver_response_channel"],
        "receiver_response_route": consumer_timing_posture["receiver_response_route"],
        "receiver_followup_requirement": consumer_timing_posture[
            "receiver_followup_requirement"
        ],
        "consumer_decision_posture": consumer_timing_posture["consumer_decision_posture"],
        "consumer_action_requirement": consumer_timing_posture[
            "consumer_action_requirement"
        ],
        "consumer_work_queue_assignment": consumer_timing_posture[
            "consumer_work_queue_assignment"
        ],
        "consumer_processing_plan": consumer_timing_posture["consumer_processing_plan"],
        "consumer_operator_requirement": consumer_timing_posture[
            "consumer_operator_requirement"
        ],
        "consumer_assignment_lane": consumer_timing_posture["consumer_assignment_lane"],
        "consumer_service_tier": consumer_timing_posture["consumer_service_tier"],
        "consumer_sla_class": consumer_timing_posture["consumer_sla_class"],
        "consumer_response_window": consumer_timing_posture["consumer_response_window"],
        "consumer_timing_posture": consumer_timing_posture["consumer_timing_posture"],
        "consumer_scheduling_commitment": scheduling_commitment_by_timing_posture[
            consumer_timing_posture["consumer_timing_posture"]
        ],
    }
    if "related_project_id" in consumer_timing_posture:
        consumer_scheduling_commitment["related_project_id"] = consumer_timing_posture[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_timing_posture:
        consumer_scheduling_commitment["related_activation_decision_id"] = (
            consumer_timing_posture["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_timing_posture:
        consumer_scheduling_commitment["related_packet_id"] = consumer_timing_posture[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_timing_posture:
        consumer_scheduling_commitment["related_queue_item_id"] = consumer_timing_posture[
            "related_queue_item_id"
        ]
    return consumer_scheduling_commitment


def build_consumer_execution_readiness_from_scheduling_commitment(
    *,
    consumer_scheduling_commitment: dict[str, Any],
) -> dict[str, Any]:
    """Build pure consumer execution readiness from existing scheduling commitment."""
    execution_readiness_by_scheduling_commitment = {
        "backlog_commitment": "deferred_readiness",
        "scheduled_commitment": "planned_readiness",
        "immediate_commitment": "ready_now",
    }
    consumer_execution_readiness: dict[str, Any] = {
        "projected_activation_decision": consumer_scheduling_commitment[
            "projected_activation_decision"
        ],
        "approval_record": consumer_scheduling_commitment["approval_record"],
        "receiver_readiness_classification": consumer_scheduling_commitment[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_scheduling_commitment[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_scheduling_commitment["receiver_action_label"],
        "receiver_dispatch_intent": consumer_scheduling_commitment[
            "receiver_dispatch_intent"
        ],
        "receiver_dispatch_mode": consumer_scheduling_commitment["receiver_dispatch_mode"],
        "receiver_release_gate": consumer_scheduling_commitment["receiver_release_gate"],
        "receiver_progress_state": consumer_scheduling_commitment[
            "receiver_progress_state"
        ],
        "receiver_progress_signal": consumer_scheduling_commitment[
            "receiver_progress_signal"
        ],
        "receiver_progress_outcome": consumer_scheduling_commitment[
            "receiver_progress_outcome"
        ],
        "receiver_intervention_requirement": consumer_scheduling_commitment[
            "receiver_intervention_requirement"
        ],
        "receiver_attention_level": consumer_scheduling_commitment[
            "receiver_attention_level"
        ],
        "receiver_notification_requirement": consumer_scheduling_commitment[
            "receiver_notification_requirement"
        ],
        "receiver_response_priority": consumer_scheduling_commitment[
            "receiver_response_priority"
        ],
        "receiver_response_channel": consumer_scheduling_commitment[
            "receiver_response_channel"
        ],
        "receiver_response_route": consumer_scheduling_commitment["receiver_response_route"],
        "receiver_followup_requirement": consumer_scheduling_commitment[
            "receiver_followup_requirement"
        ],
        "consumer_decision_posture": consumer_scheduling_commitment[
            "consumer_decision_posture"
        ],
        "consumer_action_requirement": consumer_scheduling_commitment[
            "consumer_action_requirement"
        ],
        "consumer_work_queue_assignment": consumer_scheduling_commitment[
            "consumer_work_queue_assignment"
        ],
        "consumer_processing_plan": consumer_scheduling_commitment[
            "consumer_processing_plan"
        ],
        "consumer_operator_requirement": consumer_scheduling_commitment[
            "consumer_operator_requirement"
        ],
        "consumer_assignment_lane": consumer_scheduling_commitment[
            "consumer_assignment_lane"
        ],
        "consumer_service_tier": consumer_scheduling_commitment["consumer_service_tier"],
        "consumer_sla_class": consumer_scheduling_commitment["consumer_sla_class"],
        "consumer_response_window": consumer_scheduling_commitment[
            "consumer_response_window"
        ],
        "consumer_timing_posture": consumer_scheduling_commitment[
            "consumer_timing_posture"
        ],
        "consumer_scheduling_commitment": consumer_scheduling_commitment[
            "consumer_scheduling_commitment"
        ],
        "consumer_execution_readiness": execution_readiness_by_scheduling_commitment[
            consumer_scheduling_commitment["consumer_scheduling_commitment"]
        ],
    }
    if "related_project_id" in consumer_scheduling_commitment:
        consumer_execution_readiness["related_project_id"] = (
            consumer_scheduling_commitment["related_project_id"]
        )
    if "related_activation_decision_id" in consumer_scheduling_commitment:
        consumer_execution_readiness["related_activation_decision_id"] = (
            consumer_scheduling_commitment["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_scheduling_commitment:
        consumer_execution_readiness["related_packet_id"] = consumer_scheduling_commitment[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_scheduling_commitment:
        consumer_execution_readiness["related_queue_item_id"] = (
            consumer_scheduling_commitment["related_queue_item_id"]
        )
    return consumer_execution_readiness


def build_consumer_dispatch_readiness_from_execution_readiness(
    *,
    consumer_execution_readiness: dict[str, Any],
) -> dict[str, Any]:
    """Build pure consumer dispatch readiness from existing execution readiness."""
    dispatch_readiness_by_execution_readiness = {
        "deferred_readiness": "parked",
        "planned_readiness": "prepared",
        "ready_now": "dispatch_ready",
    }
    consumer_dispatch_readiness: dict[str, Any] = {
        "projected_activation_decision": consumer_execution_readiness[
            "projected_activation_decision"
        ],
        "approval_record": consumer_execution_readiness["approval_record"],
        "receiver_readiness_classification": consumer_execution_readiness[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_execution_readiness[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_execution_readiness["receiver_action_label"],
        "receiver_dispatch_intent": consumer_execution_readiness[
            "receiver_dispatch_intent"
        ],
        "receiver_dispatch_mode": consumer_execution_readiness["receiver_dispatch_mode"],
        "receiver_release_gate": consumer_execution_readiness["receiver_release_gate"],
        "receiver_progress_state": consumer_execution_readiness["receiver_progress_state"],
        "receiver_progress_signal": consumer_execution_readiness[
            "receiver_progress_signal"
        ],
        "receiver_progress_outcome": consumer_execution_readiness[
            "receiver_progress_outcome"
        ],
        "receiver_intervention_requirement": consumer_execution_readiness[
            "receiver_intervention_requirement"
        ],
        "receiver_attention_level": consumer_execution_readiness[
            "receiver_attention_level"
        ],
        "receiver_notification_requirement": consumer_execution_readiness[
            "receiver_notification_requirement"
        ],
        "receiver_response_priority": consumer_execution_readiness[
            "receiver_response_priority"
        ],
        "receiver_response_channel": consumer_execution_readiness[
            "receiver_response_channel"
        ],
        "receiver_response_route": consumer_execution_readiness["receiver_response_route"],
        "receiver_followup_requirement": consumer_execution_readiness[
            "receiver_followup_requirement"
        ],
        "consumer_decision_posture": consumer_execution_readiness[
            "consumer_decision_posture"
        ],
        "consumer_action_requirement": consumer_execution_readiness[
            "consumer_action_requirement"
        ],
        "consumer_work_queue_assignment": consumer_execution_readiness[
            "consumer_work_queue_assignment"
        ],
        "consumer_processing_plan": consumer_execution_readiness[
            "consumer_processing_plan"
        ],
        "consumer_operator_requirement": consumer_execution_readiness[
            "consumer_operator_requirement"
        ],
        "consumer_assignment_lane": consumer_execution_readiness[
            "consumer_assignment_lane"
        ],
        "consumer_service_tier": consumer_execution_readiness["consumer_service_tier"],
        "consumer_sla_class": consumer_execution_readiness["consumer_sla_class"],
        "consumer_response_window": consumer_execution_readiness[
            "consumer_response_window"
        ],
        "consumer_timing_posture": consumer_execution_readiness[
            "consumer_timing_posture"
        ],
        "consumer_scheduling_commitment": consumer_execution_readiness[
            "consumer_scheduling_commitment"
        ],
        "consumer_execution_readiness": consumer_execution_readiness[
            "consumer_execution_readiness"
        ],
        "consumer_dispatch_readiness": dispatch_readiness_by_execution_readiness[
            consumer_execution_readiness["consumer_execution_readiness"]
        ],
    }
    if "related_project_id" in consumer_execution_readiness:
        consumer_dispatch_readiness["related_project_id"] = (
            consumer_execution_readiness["related_project_id"]
        )
    if "related_activation_decision_id" in consumer_execution_readiness:
        consumer_dispatch_readiness["related_activation_decision_id"] = (
            consumer_execution_readiness["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_execution_readiness:
        consumer_dispatch_readiness["related_packet_id"] = consumer_execution_readiness[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_execution_readiness:
        consumer_dispatch_readiness["related_queue_item_id"] = (
            consumer_execution_readiness["related_queue_item_id"]
        )
    return consumer_dispatch_readiness


def build_consumer_dispatch_authority_from_readiness(
    *,
    consumer_dispatch_readiness: dict[str, Any],
) -> dict[str, Any]:
    """Build pure consumer dispatch authority from existing dispatch readiness."""
    dispatch_authority_by_readiness = {
        "parked": "withhold",
        "prepared": "pre_authorize",
        "dispatch_ready": "authorize",
    }
    consumer_dispatch_authority: dict[str, Any] = {
        "projected_activation_decision": consumer_dispatch_readiness[
            "projected_activation_decision"
        ],
        "approval_record": consumer_dispatch_readiness["approval_record"],
        "receiver_readiness_classification": consumer_dispatch_readiness[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_dispatch_readiness[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_dispatch_readiness["receiver_action_label"],
        "receiver_dispatch_intent": consumer_dispatch_readiness["receiver_dispatch_intent"],
        "receiver_dispatch_mode": consumer_dispatch_readiness["receiver_dispatch_mode"],
        "receiver_release_gate": consumer_dispatch_readiness["receiver_release_gate"],
        "receiver_progress_state": consumer_dispatch_readiness["receiver_progress_state"],
        "receiver_progress_signal": consumer_dispatch_readiness[
            "receiver_progress_signal"
        ],
        "receiver_progress_outcome": consumer_dispatch_readiness[
            "receiver_progress_outcome"
        ],
        "receiver_intervention_requirement": consumer_dispatch_readiness[
            "receiver_intervention_requirement"
        ],
        "receiver_attention_level": consumer_dispatch_readiness[
            "receiver_attention_level"
        ],
        "receiver_notification_requirement": consumer_dispatch_readiness[
            "receiver_notification_requirement"
        ],
        "receiver_response_priority": consumer_dispatch_readiness[
            "receiver_response_priority"
        ],
        "receiver_response_channel": consumer_dispatch_readiness[
            "receiver_response_channel"
        ],
        "receiver_response_route": consumer_dispatch_readiness["receiver_response_route"],
        "receiver_followup_requirement": consumer_dispatch_readiness[
            "receiver_followup_requirement"
        ],
        "consumer_decision_posture": consumer_dispatch_readiness[
            "consumer_decision_posture"
        ],
        "consumer_action_requirement": consumer_dispatch_readiness[
            "consumer_action_requirement"
        ],
        "consumer_work_queue_assignment": consumer_dispatch_readiness[
            "consumer_work_queue_assignment"
        ],
        "consumer_processing_plan": consumer_dispatch_readiness[
            "consumer_processing_plan"
        ],
        "consumer_operator_requirement": consumer_dispatch_readiness[
            "consumer_operator_requirement"
        ],
        "consumer_assignment_lane": consumer_dispatch_readiness[
            "consumer_assignment_lane"
        ],
        "consumer_service_tier": consumer_dispatch_readiness["consumer_service_tier"],
        "consumer_sla_class": consumer_dispatch_readiness["consumer_sla_class"],
        "consumer_response_window": consumer_dispatch_readiness[
            "consumer_response_window"
        ],
        "consumer_timing_posture": consumer_dispatch_readiness[
            "consumer_timing_posture"
        ],
        "consumer_scheduling_commitment": consumer_dispatch_readiness[
            "consumer_scheduling_commitment"
        ],
        "consumer_execution_readiness": consumer_dispatch_readiness[
            "consumer_execution_readiness"
        ],
        "consumer_dispatch_readiness": consumer_dispatch_readiness[
            "consumer_dispatch_readiness"
        ],
        "consumer_dispatch_authority": dispatch_authority_by_readiness[
            consumer_dispatch_readiness["consumer_dispatch_readiness"]
        ],
    }
    if "related_project_id" in consumer_dispatch_readiness:
        consumer_dispatch_authority["related_project_id"] = consumer_dispatch_readiness[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_dispatch_readiness:
        consumer_dispatch_authority["related_activation_decision_id"] = (
            consumer_dispatch_readiness["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_dispatch_readiness:
        consumer_dispatch_authority["related_packet_id"] = consumer_dispatch_readiness[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_dispatch_readiness:
        consumer_dispatch_authority["related_queue_item_id"] = (
            consumer_dispatch_readiness["related_queue_item_id"]
        )
    return consumer_dispatch_authority


def build_consumer_dispatch_permission_from_authority(
    *,
    consumer_dispatch_authority: dict[str, Any],
) -> dict[str, Any]:
    """Build pure consumer dispatch permission from existing dispatch authority."""
    dispatch_permission_by_authority = {
        "withhold": "not_permitted",
        "pre_authorize": "conditionally_permitted",
        "authorize": "permitted",
    }
    consumer_dispatch_permission: dict[str, Any] = {
        "projected_activation_decision": consumer_dispatch_authority[
            "projected_activation_decision"
        ],
        "approval_record": consumer_dispatch_authority["approval_record"],
        "receiver_readiness_classification": consumer_dispatch_authority[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_dispatch_authority[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_dispatch_authority["receiver_action_label"],
        "receiver_dispatch_intent": consumer_dispatch_authority["receiver_dispatch_intent"],
        "receiver_dispatch_mode": consumer_dispatch_authority["receiver_dispatch_mode"],
        "receiver_release_gate": consumer_dispatch_authority["receiver_release_gate"],
        "receiver_progress_state": consumer_dispatch_authority["receiver_progress_state"],
        "receiver_progress_signal": consumer_dispatch_authority[
            "receiver_progress_signal"
        ],
        "receiver_progress_outcome": consumer_dispatch_authority[
            "receiver_progress_outcome"
        ],
        "receiver_intervention_requirement": consumer_dispatch_authority[
            "receiver_intervention_requirement"
        ],
        "receiver_attention_level": consumer_dispatch_authority[
            "receiver_attention_level"
        ],
        "receiver_notification_requirement": consumer_dispatch_authority[
            "receiver_notification_requirement"
        ],
        "receiver_response_priority": consumer_dispatch_authority[
            "receiver_response_priority"
        ],
        "receiver_response_channel": consumer_dispatch_authority[
            "receiver_response_channel"
        ],
        "receiver_response_route": consumer_dispatch_authority["receiver_response_route"],
        "receiver_followup_requirement": consumer_dispatch_authority[
            "receiver_followup_requirement"
        ],
        "consumer_decision_posture": consumer_dispatch_authority[
            "consumer_decision_posture"
        ],
        "consumer_action_requirement": consumer_dispatch_authority[
            "consumer_action_requirement"
        ],
        "consumer_work_queue_assignment": consumer_dispatch_authority[
            "consumer_work_queue_assignment"
        ],
        "consumer_processing_plan": consumer_dispatch_authority[
            "consumer_processing_plan"
        ],
        "consumer_operator_requirement": consumer_dispatch_authority[
            "consumer_operator_requirement"
        ],
        "consumer_assignment_lane": consumer_dispatch_authority[
            "consumer_assignment_lane"
        ],
        "consumer_service_tier": consumer_dispatch_authority["consumer_service_tier"],
        "consumer_sla_class": consumer_dispatch_authority["consumer_sla_class"],
        "consumer_response_window": consumer_dispatch_authority[
            "consumer_response_window"
        ],
        "consumer_timing_posture": consumer_dispatch_authority[
            "consumer_timing_posture"
        ],
        "consumer_scheduling_commitment": consumer_dispatch_authority[
            "consumer_scheduling_commitment"
        ],
        "consumer_execution_readiness": consumer_dispatch_authority[
            "consumer_execution_readiness"
        ],
        "consumer_dispatch_readiness": consumer_dispatch_authority[
            "consumer_dispatch_readiness"
        ],
        "consumer_dispatch_authority": consumer_dispatch_authority[
            "consumer_dispatch_authority"
        ],
        "consumer_dispatch_permission": dispatch_permission_by_authority[
            consumer_dispatch_authority["consumer_dispatch_authority"]
        ],
    }
    if "related_project_id" in consumer_dispatch_authority:
        consumer_dispatch_permission["related_project_id"] = consumer_dispatch_authority[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_dispatch_authority:
        consumer_dispatch_permission["related_activation_decision_id"] = (
            consumer_dispatch_authority["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_dispatch_authority:
        consumer_dispatch_permission["related_packet_id"] = consumer_dispatch_authority[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_dispatch_authority:
        consumer_dispatch_permission["related_queue_item_id"] = (
            consumer_dispatch_authority["related_queue_item_id"]
        )
    return consumer_dispatch_permission


def build_consumer_dispatch_clearance_from_permission(
    *,
    consumer_dispatch_permission: dict[str, Any],
) -> dict[str, Any]:
    """Build pure consumer dispatch clearance from existing dispatch permission."""
    dispatch_clearance_by_permission = {
        "not_permitted": "blocked",
        "conditionally_permitted": "gated",
        "permitted": "clear",
    }
    consumer_dispatch_clearance: dict[str, Any] = {
        "projected_activation_decision": consumer_dispatch_permission[
            "projected_activation_decision"
        ],
        "approval_record": consumer_dispatch_permission["approval_record"],
        "receiver_readiness_classification": consumer_dispatch_permission[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_dispatch_permission[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_dispatch_permission["receiver_action_label"],
        "receiver_dispatch_intent": consumer_dispatch_permission["receiver_dispatch_intent"],
        "receiver_dispatch_mode": consumer_dispatch_permission["receiver_dispatch_mode"],
        "receiver_release_gate": consumer_dispatch_permission["receiver_release_gate"],
        "receiver_progress_state": consumer_dispatch_permission["receiver_progress_state"],
        "receiver_progress_signal": consumer_dispatch_permission[
            "receiver_progress_signal"
        ],
        "receiver_progress_outcome": consumer_dispatch_permission[
            "receiver_progress_outcome"
        ],
        "receiver_intervention_requirement": consumer_dispatch_permission[
            "receiver_intervention_requirement"
        ],
        "receiver_attention_level": consumer_dispatch_permission[
            "receiver_attention_level"
        ],
        "receiver_notification_requirement": consumer_dispatch_permission[
            "receiver_notification_requirement"
        ],
        "receiver_response_priority": consumer_dispatch_permission[
            "receiver_response_priority"
        ],
        "receiver_response_channel": consumer_dispatch_permission[
            "receiver_response_channel"
        ],
        "receiver_response_route": consumer_dispatch_permission["receiver_response_route"],
        "receiver_followup_requirement": consumer_dispatch_permission[
            "receiver_followup_requirement"
        ],
        "consumer_decision_posture": consumer_dispatch_permission[
            "consumer_decision_posture"
        ],
        "consumer_action_requirement": consumer_dispatch_permission[
            "consumer_action_requirement"
        ],
        "consumer_work_queue_assignment": consumer_dispatch_permission[
            "consumer_work_queue_assignment"
        ],
        "consumer_processing_plan": consumer_dispatch_permission[
            "consumer_processing_plan"
        ],
        "consumer_operator_requirement": consumer_dispatch_permission[
            "consumer_operator_requirement"
        ],
        "consumer_assignment_lane": consumer_dispatch_permission[
            "consumer_assignment_lane"
        ],
        "consumer_service_tier": consumer_dispatch_permission["consumer_service_tier"],
        "consumer_sla_class": consumer_dispatch_permission["consumer_sla_class"],
        "consumer_response_window": consumer_dispatch_permission[
            "consumer_response_window"
        ],
        "consumer_timing_posture": consumer_dispatch_permission[
            "consumer_timing_posture"
        ],
        "consumer_scheduling_commitment": consumer_dispatch_permission[
            "consumer_scheduling_commitment"
        ],
        "consumer_execution_readiness": consumer_dispatch_permission[
            "consumer_execution_readiness"
        ],
        "consumer_dispatch_readiness": consumer_dispatch_permission[
            "consumer_dispatch_readiness"
        ],
        "consumer_dispatch_authority": consumer_dispatch_permission[
            "consumer_dispatch_authority"
        ],
        "consumer_dispatch_permission": consumer_dispatch_permission[
            "consumer_dispatch_permission"
        ],
        "consumer_dispatch_clearance": dispatch_clearance_by_permission[
            consumer_dispatch_permission["consumer_dispatch_permission"]
        ],
    }
    if "related_project_id" in consumer_dispatch_permission:
        consumer_dispatch_clearance["related_project_id"] = consumer_dispatch_permission[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_dispatch_permission:
        consumer_dispatch_clearance["related_activation_decision_id"] = (
            consumer_dispatch_permission["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_dispatch_permission:
        consumer_dispatch_clearance["related_packet_id"] = consumer_dispatch_permission[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_dispatch_permission:
        consumer_dispatch_clearance["related_queue_item_id"] = (
            consumer_dispatch_permission["related_queue_item_id"]
        )
    return consumer_dispatch_clearance


def build_consumer_release_decision_from_dispatch_clearance(
    *,
    consumer_dispatch_clearance: dict[str, Any],
) -> dict[str, Any]:
    """Build pure consumer release decision from existing dispatch clearance."""
    release_decision_by_clearance = {
        "blocked": "hold_release",
        "gated": "conditional_release",
        "clear": "release",
    }
    consumer_release_decision: dict[str, Any] = {
        "projected_activation_decision": consumer_dispatch_clearance[
            "projected_activation_decision"
        ],
        "approval_record": consumer_dispatch_clearance["approval_record"],
        "receiver_readiness_classification": consumer_dispatch_clearance[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_dispatch_clearance[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_dispatch_clearance["receiver_action_label"],
        "receiver_dispatch_intent": consumer_dispatch_clearance["receiver_dispatch_intent"],
        "receiver_dispatch_mode": consumer_dispatch_clearance["receiver_dispatch_mode"],
        "receiver_release_gate": consumer_dispatch_clearance["receiver_release_gate"],
        "receiver_progress_state": consumer_dispatch_clearance["receiver_progress_state"],
        "receiver_progress_signal": consumer_dispatch_clearance["receiver_progress_signal"],
        "receiver_progress_outcome": consumer_dispatch_clearance[
            "receiver_progress_outcome"
        ],
        "receiver_intervention_requirement": consumer_dispatch_clearance[
            "receiver_intervention_requirement"
        ],
        "receiver_attention_level": consumer_dispatch_clearance[
            "receiver_attention_level"
        ],
        "receiver_notification_requirement": consumer_dispatch_clearance[
            "receiver_notification_requirement"
        ],
        "receiver_response_priority": consumer_dispatch_clearance[
            "receiver_response_priority"
        ],
        "receiver_response_channel": consumer_dispatch_clearance[
            "receiver_response_channel"
        ],
        "receiver_response_route": consumer_dispatch_clearance["receiver_response_route"],
        "receiver_followup_requirement": consumer_dispatch_clearance[
            "receiver_followup_requirement"
        ],
        "consumer_decision_posture": consumer_dispatch_clearance[
            "consumer_decision_posture"
        ],
        "consumer_action_requirement": consumer_dispatch_clearance[
            "consumer_action_requirement"
        ],
        "consumer_work_queue_assignment": consumer_dispatch_clearance[
            "consumer_work_queue_assignment"
        ],
        "consumer_processing_plan": consumer_dispatch_clearance[
            "consumer_processing_plan"
        ],
        "consumer_operator_requirement": consumer_dispatch_clearance[
            "consumer_operator_requirement"
        ],
        "consumer_assignment_lane": consumer_dispatch_clearance[
            "consumer_assignment_lane"
        ],
        "consumer_service_tier": consumer_dispatch_clearance["consumer_service_tier"],
        "consumer_sla_class": consumer_dispatch_clearance["consumer_sla_class"],
        "consumer_response_window": consumer_dispatch_clearance["consumer_response_window"],
        "consumer_timing_posture": consumer_dispatch_clearance["consumer_timing_posture"],
        "consumer_scheduling_commitment": consumer_dispatch_clearance[
            "consumer_scheduling_commitment"
        ],
        "consumer_execution_readiness": consumer_dispatch_clearance[
            "consumer_execution_readiness"
        ],
        "consumer_dispatch_readiness": consumer_dispatch_clearance[
            "consumer_dispatch_readiness"
        ],
        "consumer_dispatch_authority": consumer_dispatch_clearance[
            "consumer_dispatch_authority"
        ],
        "consumer_dispatch_permission": consumer_dispatch_clearance[
            "consumer_dispatch_permission"
        ],
        "consumer_dispatch_clearance": consumer_dispatch_clearance[
            "consumer_dispatch_clearance"
        ],
        "consumer_release_decision": release_decision_by_clearance[
            consumer_dispatch_clearance["consumer_dispatch_clearance"]
        ],
    }
    if "related_project_id" in consumer_dispatch_clearance:
        consumer_release_decision["related_project_id"] = consumer_dispatch_clearance[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_dispatch_clearance:
        consumer_release_decision["related_activation_decision_id"] = (
            consumer_dispatch_clearance["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_dispatch_clearance:
        consumer_release_decision["related_packet_id"] = consumer_dispatch_clearance[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_dispatch_clearance:
        consumer_release_decision["related_queue_item_id"] = (
            consumer_dispatch_clearance["related_queue_item_id"]
        )
    return consumer_release_decision


def build_consumer_release_mode_from_release_decision(
    *,
    consumer_release_decision: dict[str, Any],
) -> dict[str, Any]:
    """Build pure consumer release mode from existing release decision."""
    release_mode_by_release_decision = {
        "hold_release": "hold_mode",
        "conditional_release": "guarded_mode",
        "release": "release_mode",
    }
    consumer_release_mode: dict[str, Any] = {
        "projected_activation_decision": consumer_release_decision[
            "projected_activation_decision"
        ],
        "approval_record": consumer_release_decision["approval_record"],
        "receiver_readiness_classification": consumer_release_decision[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_release_decision[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_release_decision["receiver_action_label"],
        "receiver_dispatch_intent": consumer_release_decision["receiver_dispatch_intent"],
        "receiver_dispatch_mode": consumer_release_decision["receiver_dispatch_mode"],
        "receiver_release_gate": consumer_release_decision["receiver_release_gate"],
        "receiver_progress_state": consumer_release_decision["receiver_progress_state"],
        "receiver_progress_signal": consumer_release_decision["receiver_progress_signal"],
        "receiver_progress_outcome": consumer_release_decision["receiver_progress_outcome"],
        "receiver_intervention_requirement": consumer_release_decision[
            "receiver_intervention_requirement"
        ],
        "receiver_attention_level": consumer_release_decision["receiver_attention_level"],
        "receiver_notification_requirement": consumer_release_decision[
            "receiver_notification_requirement"
        ],
        "receiver_response_priority": consumer_release_decision["receiver_response_priority"],
        "receiver_response_channel": consumer_release_decision["receiver_response_channel"],
        "receiver_response_route": consumer_release_decision["receiver_response_route"],
        "receiver_followup_requirement": consumer_release_decision[
            "receiver_followup_requirement"
        ],
        "consumer_decision_posture": consumer_release_decision["consumer_decision_posture"],
        "consumer_action_requirement": consumer_release_decision[
            "consumer_action_requirement"
        ],
        "consumer_work_queue_assignment": consumer_release_decision[
            "consumer_work_queue_assignment"
        ],
        "consumer_processing_plan": consumer_release_decision["consumer_processing_plan"],
        "consumer_operator_requirement": consumer_release_decision[
            "consumer_operator_requirement"
        ],
        "consumer_assignment_lane": consumer_release_decision["consumer_assignment_lane"],
        "consumer_service_tier": consumer_release_decision["consumer_service_tier"],
        "consumer_sla_class": consumer_release_decision["consumer_sla_class"],
        "consumer_response_window": consumer_release_decision["consumer_response_window"],
        "consumer_timing_posture": consumer_release_decision["consumer_timing_posture"],
        "consumer_scheduling_commitment": consumer_release_decision[
            "consumer_scheduling_commitment"
        ],
        "consumer_execution_readiness": consumer_release_decision[
            "consumer_execution_readiness"
        ],
        "consumer_dispatch_readiness": consumer_release_decision[
            "consumer_dispatch_readiness"
        ],
        "consumer_dispatch_authority": consumer_release_decision[
            "consumer_dispatch_authority"
        ],
        "consumer_dispatch_permission": consumer_release_decision[
            "consumer_dispatch_permission"
        ],
        "consumer_dispatch_clearance": consumer_release_decision[
            "consumer_dispatch_clearance"
        ],
        "consumer_release_decision": consumer_release_decision["consumer_release_decision"],
        "consumer_release_mode": release_mode_by_release_decision[
            consumer_release_decision["consumer_release_decision"]
        ],
    }
    if "related_project_id" in consumer_release_decision:
        consumer_release_mode["related_project_id"] = consumer_release_decision[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_release_decision:
        consumer_release_mode["related_activation_decision_id"] = (
            consumer_release_decision["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_release_decision:
        consumer_release_mode["related_packet_id"] = consumer_release_decision[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_release_decision:
        consumer_release_mode["related_queue_item_id"] = consumer_release_decision[
            "related_queue_item_id"
        ]
    return consumer_release_mode


def build_consumer_release_execution_requirement_from_release_mode(
    *,
    consumer_release_mode: dict[str, Any],
) -> dict[str, Any]:
    """Build pure consumer release execution requirement from existing release mode."""
    execution_requirement_by_release_mode = {
        "hold_mode": "do_not_execute",
        "guarded_mode": "execute_with_guard",
        "release_mode": "execute_release",
    }
    consumer_release_execution_requirement: dict[str, Any] = {
        "projected_activation_decision": consumer_release_mode[
            "projected_activation_decision"
        ],
        "approval_record": consumer_release_mode["approval_record"],
        "receiver_readiness_classification": consumer_release_mode[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_release_mode[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_release_mode["receiver_action_label"],
        "receiver_dispatch_intent": consumer_release_mode["receiver_dispatch_intent"],
        "receiver_dispatch_mode": consumer_release_mode["receiver_dispatch_mode"],
        "receiver_release_gate": consumer_release_mode["receiver_release_gate"],
        "receiver_progress_state": consumer_release_mode["receiver_progress_state"],
        "receiver_progress_signal": consumer_release_mode["receiver_progress_signal"],
        "receiver_progress_outcome": consumer_release_mode["receiver_progress_outcome"],
        "receiver_intervention_requirement": consumer_release_mode[
            "receiver_intervention_requirement"
        ],
        "receiver_attention_level": consumer_release_mode["receiver_attention_level"],
        "receiver_notification_requirement": consumer_release_mode[
            "receiver_notification_requirement"
        ],
        "receiver_response_priority": consumer_release_mode["receiver_response_priority"],
        "receiver_response_channel": consumer_release_mode["receiver_response_channel"],
        "receiver_response_route": consumer_release_mode["receiver_response_route"],
        "receiver_followup_requirement": consumer_release_mode[
            "receiver_followup_requirement"
        ],
        "consumer_decision_posture": consumer_release_mode["consumer_decision_posture"],
        "consumer_action_requirement": consumer_release_mode[
            "consumer_action_requirement"
        ],
        "consumer_work_queue_assignment": consumer_release_mode[
            "consumer_work_queue_assignment"
        ],
        "consumer_processing_plan": consumer_release_mode["consumer_processing_plan"],
        "consumer_operator_requirement": consumer_release_mode[
            "consumer_operator_requirement"
        ],
        "consumer_assignment_lane": consumer_release_mode["consumer_assignment_lane"],
        "consumer_service_tier": consumer_release_mode["consumer_service_tier"],
        "consumer_sla_class": consumer_release_mode["consumer_sla_class"],
        "consumer_response_window": consumer_release_mode["consumer_response_window"],
        "consumer_timing_posture": consumer_release_mode["consumer_timing_posture"],
        "consumer_scheduling_commitment": consumer_release_mode[
            "consumer_scheduling_commitment"
        ],
        "consumer_execution_readiness": consumer_release_mode[
            "consumer_execution_readiness"
        ],
        "consumer_dispatch_readiness": consumer_release_mode[
            "consumer_dispatch_readiness"
        ],
        "consumer_dispatch_authority": consumer_release_mode[
            "consumer_dispatch_authority"
        ],
        "consumer_dispatch_permission": consumer_release_mode[
            "consumer_dispatch_permission"
        ],
        "consumer_dispatch_clearance": consumer_release_mode[
            "consumer_dispatch_clearance"
        ],
        "consumer_release_decision": consumer_release_mode["consumer_release_decision"],
        "consumer_release_mode": consumer_release_mode["consumer_release_mode"],
        "consumer_release_execution_requirement": execution_requirement_by_release_mode[
            consumer_release_mode["consumer_release_mode"]
        ],
    }
    if "related_project_id" in consumer_release_mode:
        consumer_release_execution_requirement["related_project_id"] = consumer_release_mode[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_release_mode:
        consumer_release_execution_requirement["related_activation_decision_id"] = (
            consumer_release_mode["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_release_mode:
        consumer_release_execution_requirement["related_packet_id"] = consumer_release_mode[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_release_mode:
        consumer_release_execution_requirement["related_queue_item_id"] = consumer_release_mode[
            "related_queue_item_id"
        ]
    return consumer_release_execution_requirement


def build_consumer_release_execution_lane_from_execution_requirement(
    *,
    consumer_release_execution_requirement: dict[str, Any],
) -> dict[str, Any]:
    """Build pure consumer release execution lane from existing release execution requirement."""
    execution_lane_by_requirement = {
        "do_not_execute": "blocked_lane",
        "execute_with_guard": "guarded_lane",
        "execute_release": "release_lane",
    }
    consumer_release_execution_lane: dict[str, Any] = {
        "projected_activation_decision": consumer_release_execution_requirement[
            "projected_activation_decision"
        ],
        "approval_record": consumer_release_execution_requirement["approval_record"],
        "receiver_readiness_classification": consumer_release_execution_requirement[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_release_execution_requirement[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_release_execution_requirement[
            "receiver_action_label"
        ],
        "receiver_dispatch_intent": consumer_release_execution_requirement[
            "receiver_dispatch_intent"
        ],
        "receiver_dispatch_mode": consumer_release_execution_requirement[
            "receiver_dispatch_mode"
        ],
        "receiver_release_gate": consumer_release_execution_requirement[
            "receiver_release_gate"
        ],
        "receiver_progress_state": consumer_release_execution_requirement[
            "receiver_progress_state"
        ],
        "receiver_progress_signal": consumer_release_execution_requirement[
            "receiver_progress_signal"
        ],
        "receiver_progress_outcome": consumer_release_execution_requirement[
            "receiver_progress_outcome"
        ],
        "receiver_intervention_requirement": consumer_release_execution_requirement[
            "receiver_intervention_requirement"
        ],
        "receiver_attention_level": consumer_release_execution_requirement[
            "receiver_attention_level"
        ],
        "receiver_notification_requirement": consumer_release_execution_requirement[
            "receiver_notification_requirement"
        ],
        "receiver_response_priority": consumer_release_execution_requirement[
            "receiver_response_priority"
        ],
        "receiver_response_channel": consumer_release_execution_requirement[
            "receiver_response_channel"
        ],
        "receiver_response_route": consumer_release_execution_requirement[
            "receiver_response_route"
        ],
        "receiver_followup_requirement": consumer_release_execution_requirement[
            "receiver_followup_requirement"
        ],
        "consumer_decision_posture": consumer_release_execution_requirement[
            "consumer_decision_posture"
        ],
        "consumer_action_requirement": consumer_release_execution_requirement[
            "consumer_action_requirement"
        ],
        "consumer_work_queue_assignment": consumer_release_execution_requirement[
            "consumer_work_queue_assignment"
        ],
        "consumer_processing_plan": consumer_release_execution_requirement[
            "consumer_processing_plan"
        ],
        "consumer_operator_requirement": consumer_release_execution_requirement[
            "consumer_operator_requirement"
        ],
        "consumer_assignment_lane": consumer_release_execution_requirement[
            "consumer_assignment_lane"
        ],
        "consumer_service_tier": consumer_release_execution_requirement[
            "consumer_service_tier"
        ],
        "consumer_sla_class": consumer_release_execution_requirement["consumer_sla_class"],
        "consumer_response_window": consumer_release_execution_requirement[
            "consumer_response_window"
        ],
        "consumer_timing_posture": consumer_release_execution_requirement[
            "consumer_timing_posture"
        ],
        "consumer_scheduling_commitment": consumer_release_execution_requirement[
            "consumer_scheduling_commitment"
        ],
        "consumer_execution_readiness": consumer_release_execution_requirement[
            "consumer_execution_readiness"
        ],
        "consumer_dispatch_readiness": consumer_release_execution_requirement[
            "consumer_dispatch_readiness"
        ],
        "consumer_dispatch_authority": consumer_release_execution_requirement[
            "consumer_dispatch_authority"
        ],
        "consumer_dispatch_permission": consumer_release_execution_requirement[
            "consumer_dispatch_permission"
        ],
        "consumer_dispatch_clearance": consumer_release_execution_requirement[
            "consumer_dispatch_clearance"
        ],
        "consumer_release_decision": consumer_release_execution_requirement[
            "consumer_release_decision"
        ],
        "consumer_release_mode": consumer_release_execution_requirement[
            "consumer_release_mode"
        ],
        "consumer_release_execution_requirement": consumer_release_execution_requirement[
            "consumer_release_execution_requirement"
        ],
        "consumer_release_execution_lane": execution_lane_by_requirement[
            consumer_release_execution_requirement["consumer_release_execution_requirement"]
        ],
    }
    if "related_project_id" in consumer_release_execution_requirement:
        consumer_release_execution_lane["related_project_id"] = (
            consumer_release_execution_requirement["related_project_id"]
        )
    if "related_activation_decision_id" in consumer_release_execution_requirement:
        consumer_release_execution_lane["related_activation_decision_id"] = (
            consumer_release_execution_requirement["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_release_execution_requirement:
        consumer_release_execution_lane["related_packet_id"] = (
            consumer_release_execution_requirement["related_packet_id"]
        )
    if "related_queue_item_id" in consumer_release_execution_requirement:
        consumer_release_execution_lane["related_queue_item_id"] = (
            consumer_release_execution_requirement["related_queue_item_id"]
        )
    return consumer_release_execution_lane


def build_consumer_release_handling_intent_from_execution_lane(
    *,
    consumer_release_execution_lane: dict[str, Any],
) -> dict[str, Any]:
    """Build pure consumer release handling intent from existing release execution lane."""
    handling_intent_by_execution_lane = {
        "blocked_lane": "do_not_route",
        "guarded_lane": "route_with_guard",
        "release_lane": "route_for_release",
    }
    consumer_release_handling_intent: dict[str, Any] = {
        "projected_activation_decision": consumer_release_execution_lane[
            "projected_activation_decision"
        ],
        "approval_record": consumer_release_execution_lane["approval_record"],
        "receiver_readiness_classification": consumer_release_execution_lane[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_release_execution_lane[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_release_execution_lane["receiver_action_label"],
        "receiver_dispatch_intent": consumer_release_execution_lane[
            "receiver_dispatch_intent"
        ],
        "receiver_dispatch_mode": consumer_release_execution_lane["receiver_dispatch_mode"],
        "receiver_release_gate": consumer_release_execution_lane["receiver_release_gate"],
        "receiver_progress_state": consumer_release_execution_lane[
            "receiver_progress_state"
        ],
        "receiver_progress_signal": consumer_release_execution_lane[
            "receiver_progress_signal"
        ],
        "receiver_progress_outcome": consumer_release_execution_lane[
            "receiver_progress_outcome"
        ],
        "receiver_intervention_requirement": consumer_release_execution_lane[
            "receiver_intervention_requirement"
        ],
        "receiver_attention_level": consumer_release_execution_lane[
            "receiver_attention_level"
        ],
        "receiver_notification_requirement": consumer_release_execution_lane[
            "receiver_notification_requirement"
        ],
        "receiver_response_priority": consumer_release_execution_lane[
            "receiver_response_priority"
        ],
        "receiver_response_channel": consumer_release_execution_lane[
            "receiver_response_channel"
        ],
        "receiver_response_route": consumer_release_execution_lane[
            "receiver_response_route"
        ],
        "receiver_followup_requirement": consumer_release_execution_lane[
            "receiver_followup_requirement"
        ],
        "consumer_decision_posture": consumer_release_execution_lane[
            "consumer_decision_posture"
        ],
        "consumer_action_requirement": consumer_release_execution_lane[
            "consumer_action_requirement"
        ],
        "consumer_work_queue_assignment": consumer_release_execution_lane[
            "consumer_work_queue_assignment"
        ],
        "consumer_processing_plan": consumer_release_execution_lane[
            "consumer_processing_plan"
        ],
        "consumer_operator_requirement": consumer_release_execution_lane[
            "consumer_operator_requirement"
        ],
        "consumer_assignment_lane": consumer_release_execution_lane[
            "consumer_assignment_lane"
        ],
        "consumer_service_tier": consumer_release_execution_lane["consumer_service_tier"],
        "consumer_sla_class": consumer_release_execution_lane["consumer_sla_class"],
        "consumer_response_window": consumer_release_execution_lane[
            "consumer_response_window"
        ],
        "consumer_timing_posture": consumer_release_execution_lane[
            "consumer_timing_posture"
        ],
        "consumer_scheduling_commitment": consumer_release_execution_lane[
            "consumer_scheduling_commitment"
        ],
        "consumer_execution_readiness": consumer_release_execution_lane[
            "consumer_execution_readiness"
        ],
        "consumer_dispatch_readiness": consumer_release_execution_lane[
            "consumer_dispatch_readiness"
        ],
        "consumer_dispatch_authority": consumer_release_execution_lane[
            "consumer_dispatch_authority"
        ],
        "consumer_dispatch_permission": consumer_release_execution_lane[
            "consumer_dispatch_permission"
        ],
        "consumer_dispatch_clearance": consumer_release_execution_lane[
            "consumer_dispatch_clearance"
        ],
        "consumer_release_decision": consumer_release_execution_lane[
            "consumer_release_decision"
        ],
        "consumer_release_mode": consumer_release_execution_lane["consumer_release_mode"],
        "consumer_release_execution_requirement": consumer_release_execution_lane[
            "consumer_release_execution_requirement"
        ],
        "consumer_release_execution_lane": consumer_release_execution_lane[
            "consumer_release_execution_lane"
        ],
        "consumer_release_handling_intent": handling_intent_by_execution_lane[
            consumer_release_execution_lane["consumer_release_execution_lane"]
        ],
    }
    if "related_project_id" in consumer_release_execution_lane:
        consumer_release_handling_intent["related_project_id"] = (
            consumer_release_execution_lane["related_project_id"]
        )
    if "related_activation_decision_id" in consumer_release_execution_lane:
        consumer_release_handling_intent["related_activation_decision_id"] = (
            consumer_release_execution_lane["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_release_execution_lane:
        consumer_release_handling_intent["related_packet_id"] = (
            consumer_release_execution_lane["related_packet_id"]
        )
    if "related_queue_item_id" in consumer_release_execution_lane:
        consumer_release_handling_intent["related_queue_item_id"] = (
            consumer_release_execution_lane["related_queue_item_id"]
        )
    return consumer_release_handling_intent


def build_consumer_release_action_plan_from_handling_intent(
    *,
    consumer_release_handling_intent: dict[str, Any],
) -> dict[str, Any]:
    """Build pure consumer release action plan from existing release handling intent."""
    release_action_plan_by_handling_intent = {
        "do_not_route": "hold_plan",
        "route_with_guard": "guarded_release_plan",
        "route_for_release": "release_plan",
    }
    consumer_release_action_plan: dict[str, Any] = {
        "projected_activation_decision": consumer_release_handling_intent[
            "projected_activation_decision"
        ],
        "approval_record": consumer_release_handling_intent["approval_record"],
        "receiver_readiness_classification": consumer_release_handling_intent[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_release_handling_intent[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_release_handling_intent["receiver_action_label"],
        "receiver_dispatch_intent": consumer_release_handling_intent[
            "receiver_dispatch_intent"
        ],
        "receiver_dispatch_mode": consumer_release_handling_intent[
            "receiver_dispatch_mode"
        ],
        "receiver_release_gate": consumer_release_handling_intent["receiver_release_gate"],
        "receiver_progress_state": consumer_release_handling_intent[
            "receiver_progress_state"
        ],
        "receiver_progress_signal": consumer_release_handling_intent[
            "receiver_progress_signal"
        ],
        "receiver_progress_outcome": consumer_release_handling_intent[
            "receiver_progress_outcome"
        ],
        "receiver_intervention_requirement": consumer_release_handling_intent[
            "receiver_intervention_requirement"
        ],
        "receiver_attention_level": consumer_release_handling_intent[
            "receiver_attention_level"
        ],
        "receiver_notification_requirement": consumer_release_handling_intent[
            "receiver_notification_requirement"
        ],
        "receiver_response_priority": consumer_release_handling_intent[
            "receiver_response_priority"
        ],
        "receiver_response_channel": consumer_release_handling_intent[
            "receiver_response_channel"
        ],
        "receiver_response_route": consumer_release_handling_intent[
            "receiver_response_route"
        ],
        "receiver_followup_requirement": consumer_release_handling_intent[
            "receiver_followup_requirement"
        ],
        "consumer_decision_posture": consumer_release_handling_intent[
            "consumer_decision_posture"
        ],
        "consumer_action_requirement": consumer_release_handling_intent[
            "consumer_action_requirement"
        ],
        "consumer_work_queue_assignment": consumer_release_handling_intent[
            "consumer_work_queue_assignment"
        ],
        "consumer_processing_plan": consumer_release_handling_intent[
            "consumer_processing_plan"
        ],
        "consumer_operator_requirement": consumer_release_handling_intent[
            "consumer_operator_requirement"
        ],
        "consumer_assignment_lane": consumer_release_handling_intent[
            "consumer_assignment_lane"
        ],
        "consumer_service_tier": consumer_release_handling_intent["consumer_service_tier"],
        "consumer_sla_class": consumer_release_handling_intent["consumer_sla_class"],
        "consumer_response_window": consumer_release_handling_intent[
            "consumer_response_window"
        ],
        "consumer_timing_posture": consumer_release_handling_intent[
            "consumer_timing_posture"
        ],
        "consumer_scheduling_commitment": consumer_release_handling_intent[
            "consumer_scheduling_commitment"
        ],
        "consumer_execution_readiness": consumer_release_handling_intent[
            "consumer_execution_readiness"
        ],
        "consumer_dispatch_readiness": consumer_release_handling_intent[
            "consumer_dispatch_readiness"
        ],
        "consumer_dispatch_authority": consumer_release_handling_intent[
            "consumer_dispatch_authority"
        ],
        "consumer_dispatch_permission": consumer_release_handling_intent[
            "consumer_dispatch_permission"
        ],
        "consumer_dispatch_clearance": consumer_release_handling_intent[
            "consumer_dispatch_clearance"
        ],
        "consumer_release_decision": consumer_release_handling_intent[
            "consumer_release_decision"
        ],
        "consumer_release_mode": consumer_release_handling_intent[
            "consumer_release_mode"
        ],
        "consumer_release_execution_requirement": consumer_release_handling_intent[
            "consumer_release_execution_requirement"
        ],
        "consumer_release_execution_lane": consumer_release_handling_intent[
            "consumer_release_execution_lane"
        ],
        "consumer_release_handling_intent": consumer_release_handling_intent[
            "consumer_release_handling_intent"
        ],
        "consumer_release_action_plan": release_action_plan_by_handling_intent[
            consumer_release_handling_intent["consumer_release_handling_intent"]
        ],
    }
    if "related_project_id" in consumer_release_handling_intent:
        consumer_release_action_plan["related_project_id"] = (
            consumer_release_handling_intent["related_project_id"]
        )
    if "related_activation_decision_id" in consumer_release_handling_intent:
        consumer_release_action_plan["related_activation_decision_id"] = (
            consumer_release_handling_intent["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_release_handling_intent:
        consumer_release_action_plan["related_packet_id"] = (
            consumer_release_handling_intent["related_packet_id"]
        )
    if "related_queue_item_id" in consumer_release_handling_intent:
        consumer_release_action_plan["related_queue_item_id"] = (
            consumer_release_handling_intent["related_queue_item_id"]
        )
    return consumer_release_action_plan


def build_consumer_release_queue_from_action_plan(
    *,
    consumer_release_action_plan: dict[str, Any],
) -> dict[str, Any]:
    """Build pure consumer release queue from existing release action plan."""
    release_queue_by_action_plan = {
        "hold_plan": "hold_queue",
        "guarded_release_plan": "guarded_release_queue",
        "release_plan": "release_queue",
    }
    consumer_release_queue: dict[str, Any] = {
        "projected_activation_decision": consumer_release_action_plan[
            "projected_activation_decision"
        ],
        "approval_record": consumer_release_action_plan["approval_record"],
        "receiver_readiness_classification": consumer_release_action_plan[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_release_action_plan[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_release_action_plan["receiver_action_label"],
        "receiver_dispatch_intent": consumer_release_action_plan[
            "receiver_dispatch_intent"
        ],
        "receiver_dispatch_mode": consumer_release_action_plan["receiver_dispatch_mode"],
        "receiver_release_gate": consumer_release_action_plan["receiver_release_gate"],
        "receiver_progress_state": consumer_release_action_plan["receiver_progress_state"],
        "receiver_progress_signal": consumer_release_action_plan["receiver_progress_signal"],
        "receiver_progress_outcome": consumer_release_action_plan["receiver_progress_outcome"],
        "receiver_intervention_requirement": consumer_release_action_plan[
            "receiver_intervention_requirement"
        ],
        "receiver_attention_level": consumer_release_action_plan[
            "receiver_attention_level"
        ],
        "receiver_notification_requirement": consumer_release_action_plan[
            "receiver_notification_requirement"
        ],
        "receiver_response_priority": consumer_release_action_plan[
            "receiver_response_priority"
        ],
        "receiver_response_channel": consumer_release_action_plan[
            "receiver_response_channel"
        ],
        "receiver_response_route": consumer_release_action_plan["receiver_response_route"],
        "receiver_followup_requirement": consumer_release_action_plan[
            "receiver_followup_requirement"
        ],
        "consumer_decision_posture": consumer_release_action_plan[
            "consumer_decision_posture"
        ],
        "consumer_action_requirement": consumer_release_action_plan[
            "consumer_action_requirement"
        ],
        "consumer_work_queue_assignment": consumer_release_action_plan[
            "consumer_work_queue_assignment"
        ],
        "consumer_processing_plan": consumer_release_action_plan[
            "consumer_processing_plan"
        ],
        "consumer_operator_requirement": consumer_release_action_plan[
            "consumer_operator_requirement"
        ],
        "consumer_assignment_lane": consumer_release_action_plan[
            "consumer_assignment_lane"
        ],
        "consumer_service_tier": consumer_release_action_plan["consumer_service_tier"],
        "consumer_sla_class": consumer_release_action_plan["consumer_sla_class"],
        "consumer_response_window": consumer_release_action_plan["consumer_response_window"],
        "consumer_timing_posture": consumer_release_action_plan["consumer_timing_posture"],
        "consumer_scheduling_commitment": consumer_release_action_plan[
            "consumer_scheduling_commitment"
        ],
        "consumer_execution_readiness": consumer_release_action_plan[
            "consumer_execution_readiness"
        ],
        "consumer_dispatch_readiness": consumer_release_action_plan[
            "consumer_dispatch_readiness"
        ],
        "consumer_dispatch_authority": consumer_release_action_plan[
            "consumer_dispatch_authority"
        ],
        "consumer_dispatch_permission": consumer_release_action_plan[
            "consumer_dispatch_permission"
        ],
        "consumer_dispatch_clearance": consumer_release_action_plan[
            "consumer_dispatch_clearance"
        ],
        "consumer_release_decision": consumer_release_action_plan[
            "consumer_release_decision"
        ],
        "consumer_release_mode": consumer_release_action_plan["consumer_release_mode"],
        "consumer_release_execution_requirement": consumer_release_action_plan[
            "consumer_release_execution_requirement"
        ],
        "consumer_release_execution_lane": consumer_release_action_plan[
            "consumer_release_execution_lane"
        ],
        "consumer_release_handling_intent": consumer_release_action_plan[
            "consumer_release_handling_intent"
        ],
        "consumer_release_action_plan": consumer_release_action_plan[
            "consumer_release_action_plan"
        ],
        "consumer_release_queue": release_queue_by_action_plan[
            consumer_release_action_plan["consumer_release_action_plan"]
        ],
    }
    if "related_project_id" in consumer_release_action_plan:
        consumer_release_queue["related_project_id"] = consumer_release_action_plan[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_release_action_plan:
        consumer_release_queue["related_activation_decision_id"] = (
            consumer_release_action_plan["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_release_action_plan:
        consumer_release_queue["related_packet_id"] = consumer_release_action_plan[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_release_action_plan:
        consumer_release_queue["related_queue_item_id"] = consumer_release_action_plan[
            "related_queue_item_id"
        ]
    return consumer_release_queue


def build_consumer_release_priority_from_queue(
    *,
    consumer_release_queue: dict[str, Any],
) -> dict[str, Any]:
    """Build pure consumer release priority from existing release queue."""
    release_priority_by_queue = {
        "hold_queue": "low",
        "guarded_release_queue": "medium",
        "release_queue": "high",
    }
    consumer_release_priority: dict[str, Any] = {
        "projected_activation_decision": consumer_release_queue[
            "projected_activation_decision"
        ],
        "approval_record": consumer_release_queue["approval_record"],
        "receiver_readiness_classification": consumer_release_queue[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_release_queue[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_release_queue["receiver_action_label"],
        "receiver_dispatch_intent": consumer_release_queue["receiver_dispatch_intent"],
        "receiver_dispatch_mode": consumer_release_queue["receiver_dispatch_mode"],
        "receiver_release_gate": consumer_release_queue["receiver_release_gate"],
        "receiver_progress_state": consumer_release_queue["receiver_progress_state"],
        "receiver_progress_signal": consumer_release_queue["receiver_progress_signal"],
        "receiver_progress_outcome": consumer_release_queue["receiver_progress_outcome"],
        "receiver_intervention_requirement": consumer_release_queue[
            "receiver_intervention_requirement"
        ],
        "receiver_attention_level": consumer_release_queue["receiver_attention_level"],
        "receiver_notification_requirement": consumer_release_queue[
            "receiver_notification_requirement"
        ],
        "receiver_response_priority": consumer_release_queue["receiver_response_priority"],
        "receiver_response_channel": consumer_release_queue["receiver_response_channel"],
        "receiver_response_route": consumer_release_queue["receiver_response_route"],
        "receiver_followup_requirement": consumer_release_queue[
            "receiver_followup_requirement"
        ],
        "consumer_decision_posture": consumer_release_queue["consumer_decision_posture"],
        "consumer_action_requirement": consumer_release_queue[
            "consumer_action_requirement"
        ],
        "consumer_work_queue_assignment": consumer_release_queue[
            "consumer_work_queue_assignment"
        ],
        "consumer_processing_plan": consumer_release_queue["consumer_processing_plan"],
        "consumer_operator_requirement": consumer_release_queue[
            "consumer_operator_requirement"
        ],
        "consumer_assignment_lane": consumer_release_queue["consumer_assignment_lane"],
        "consumer_service_tier": consumer_release_queue["consumer_service_tier"],
        "consumer_sla_class": consumer_release_queue["consumer_sla_class"],
        "consumer_response_window": consumer_release_queue["consumer_response_window"],
        "consumer_timing_posture": consumer_release_queue["consumer_timing_posture"],
        "consumer_scheduling_commitment": consumer_release_queue[
            "consumer_scheduling_commitment"
        ],
        "consumer_execution_readiness": consumer_release_queue[
            "consumer_execution_readiness"
        ],
        "consumer_dispatch_readiness": consumer_release_queue[
            "consumer_dispatch_readiness"
        ],
        "consumer_dispatch_authority": consumer_release_queue[
            "consumer_dispatch_authority"
        ],
        "consumer_dispatch_permission": consumer_release_queue[
            "consumer_dispatch_permission"
        ],
        "consumer_dispatch_clearance": consumer_release_queue[
            "consumer_dispatch_clearance"
        ],
        "consumer_release_decision": consumer_release_queue["consumer_release_decision"],
        "consumer_release_mode": consumer_release_queue["consumer_release_mode"],
        "consumer_release_execution_requirement": consumer_release_queue[
            "consumer_release_execution_requirement"
        ],
        "consumer_release_execution_lane": consumer_release_queue[
            "consumer_release_execution_lane"
        ],
        "consumer_release_handling_intent": consumer_release_queue[
            "consumer_release_handling_intent"
        ],
        "consumer_release_action_plan": consumer_release_queue[
            "consumer_release_action_plan"
        ],
        "consumer_release_queue": consumer_release_queue["consumer_release_queue"],
        "consumer_release_priority": release_priority_by_queue[
            consumer_release_queue["consumer_release_queue"]
        ],
    }
    if "related_project_id" in consumer_release_queue:
        consumer_release_priority["related_project_id"] = consumer_release_queue[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_release_queue:
        consumer_release_priority["related_activation_decision_id"] = (
            consumer_release_queue["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_release_queue:
        consumer_release_priority["related_packet_id"] = consumer_release_queue[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_release_queue:
        consumer_release_priority["related_queue_item_id"] = consumer_release_queue[
            "related_queue_item_id"
        ]
    return consumer_release_priority


def build_consumer_release_window_from_priority(
    *,
    consumer_release_priority: dict[str, Any],
) -> dict[str, Any]:
    """Build pure consumer release window from existing release priority."""
    release_window_by_priority = {
        "low": "deferred_window",
        "medium": "controlled_window",
        "high": "immediate_window",
    }
    consumer_release_window: dict[str, Any] = {
        "projected_activation_decision": consumer_release_priority[
            "projected_activation_decision"
        ],
        "approval_record": consumer_release_priority["approval_record"],
        "receiver_readiness_classification": consumer_release_priority[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_release_priority[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_release_priority["receiver_action_label"],
        "receiver_dispatch_intent": consumer_release_priority["receiver_dispatch_intent"],
        "receiver_dispatch_mode": consumer_release_priority["receiver_dispatch_mode"],
        "receiver_release_gate": consumer_release_priority["receiver_release_gate"],
        "receiver_progress_state": consumer_release_priority["receiver_progress_state"],
        "receiver_progress_signal": consumer_release_priority["receiver_progress_signal"],
        "receiver_progress_outcome": consumer_release_priority["receiver_progress_outcome"],
        "receiver_intervention_requirement": consumer_release_priority[
            "receiver_intervention_requirement"
        ],
        "receiver_attention_level": consumer_release_priority["receiver_attention_level"],
        "receiver_notification_requirement": consumer_release_priority[
            "receiver_notification_requirement"
        ],
        "receiver_response_priority": consumer_release_priority[
            "receiver_response_priority"
        ],
        "receiver_response_channel": consumer_release_priority["receiver_response_channel"],
        "receiver_response_route": consumer_release_priority["receiver_response_route"],
        "receiver_followup_requirement": consumer_release_priority[
            "receiver_followup_requirement"
        ],
        "consumer_decision_posture": consumer_release_priority["consumer_decision_posture"],
        "consumer_action_requirement": consumer_release_priority[
            "consumer_action_requirement"
        ],
        "consumer_work_queue_assignment": consumer_release_priority[
            "consumer_work_queue_assignment"
        ],
        "consumer_processing_plan": consumer_release_priority["consumer_processing_plan"],
        "consumer_operator_requirement": consumer_release_priority[
            "consumer_operator_requirement"
        ],
        "consumer_assignment_lane": consumer_release_priority["consumer_assignment_lane"],
        "consumer_service_tier": consumer_release_priority["consumer_service_tier"],
        "consumer_sla_class": consumer_release_priority["consumer_sla_class"],
        "consumer_response_window": consumer_release_priority["consumer_response_window"],
        "consumer_timing_posture": consumer_release_priority["consumer_timing_posture"],
        "consumer_scheduling_commitment": consumer_release_priority[
            "consumer_scheduling_commitment"
        ],
        "consumer_execution_readiness": consumer_release_priority[
            "consumer_execution_readiness"
        ],
        "consumer_dispatch_readiness": consumer_release_priority[
            "consumer_dispatch_readiness"
        ],
        "consumer_dispatch_authority": consumer_release_priority[
            "consumer_dispatch_authority"
        ],
        "consumer_dispatch_permission": consumer_release_priority[
            "consumer_dispatch_permission"
        ],
        "consumer_dispatch_clearance": consumer_release_priority[
            "consumer_dispatch_clearance"
        ],
        "consumer_release_decision": consumer_release_priority["consumer_release_decision"],
        "consumer_release_mode": consumer_release_priority["consumer_release_mode"],
        "consumer_release_execution_requirement": consumer_release_priority[
            "consumer_release_execution_requirement"
        ],
        "consumer_release_execution_lane": consumer_release_priority[
            "consumer_release_execution_lane"
        ],
        "consumer_release_handling_intent": consumer_release_priority[
            "consumer_release_handling_intent"
        ],
        "consumer_release_action_plan": consumer_release_priority[
            "consumer_release_action_plan"
        ],
        "consumer_release_queue": consumer_release_priority["consumer_release_queue"],
        "consumer_release_priority": consumer_release_priority["consumer_release_priority"],
        "consumer_release_window": release_window_by_priority[
            consumer_release_priority["consumer_release_priority"]
        ],
    }
    if "related_project_id" in consumer_release_priority:
        consumer_release_window["related_project_id"] = consumer_release_priority[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_release_priority:
        consumer_release_window["related_activation_decision_id"] = (
            consumer_release_priority["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_release_priority:
        consumer_release_window["related_packet_id"] = consumer_release_priority[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_release_priority:
        consumer_release_window["related_queue_item_id"] = consumer_release_priority[
            "related_queue_item_id"
        ]
    return consumer_release_window


def build_consumer_release_schedule_from_window(
    *,
    consumer_release_window: dict[str, Any],
) -> dict[str, Any]:
    """Build pure consumer release schedule from existing release window."""
    release_schedule_by_window = {
        "deferred_window": "backlog_schedule",
        "controlled_window": "guarded_schedule",
        "immediate_window": "immediate_schedule",
    }
    consumer_release_schedule: dict[str, Any] = {
        "projected_activation_decision": consumer_release_window[
            "projected_activation_decision"
        ],
        "approval_record": consumer_release_window["approval_record"],
        "receiver_readiness_classification": consumer_release_window[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_release_window[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_release_window["receiver_action_label"],
        "receiver_dispatch_intent": consumer_release_window["receiver_dispatch_intent"],
        "receiver_dispatch_mode": consumer_release_window["receiver_dispatch_mode"],
        "receiver_release_gate": consumer_release_window["receiver_release_gate"],
        "receiver_progress_state": consumer_release_window["receiver_progress_state"],
        "receiver_progress_signal": consumer_release_window["receiver_progress_signal"],
        "receiver_progress_outcome": consumer_release_window["receiver_progress_outcome"],
        "receiver_intervention_requirement": consumer_release_window[
            "receiver_intervention_requirement"
        ],
        "receiver_attention_level": consumer_release_window["receiver_attention_level"],
        "receiver_notification_requirement": consumer_release_window[
            "receiver_notification_requirement"
        ],
        "receiver_response_priority": consumer_release_window[
            "receiver_response_priority"
        ],
        "receiver_response_channel": consumer_release_window["receiver_response_channel"],
        "receiver_response_route": consumer_release_window["receiver_response_route"],
        "receiver_followup_requirement": consumer_release_window[
            "receiver_followup_requirement"
        ],
        "consumer_decision_posture": consumer_release_window["consumer_decision_posture"],
        "consumer_action_requirement": consumer_release_window[
            "consumer_action_requirement"
        ],
        "consumer_work_queue_assignment": consumer_release_window[
            "consumer_work_queue_assignment"
        ],
        "consumer_processing_plan": consumer_release_window["consumer_processing_plan"],
        "consumer_operator_requirement": consumer_release_window[
            "consumer_operator_requirement"
        ],
        "consumer_assignment_lane": consumer_release_window["consumer_assignment_lane"],
        "consumer_service_tier": consumer_release_window["consumer_service_tier"],
        "consumer_sla_class": consumer_release_window["consumer_sla_class"],
        "consumer_response_window": consumer_release_window["consumer_response_window"],
        "consumer_timing_posture": consumer_release_window["consumer_timing_posture"],
        "consumer_scheduling_commitment": consumer_release_window[
            "consumer_scheduling_commitment"
        ],
        "consumer_execution_readiness": consumer_release_window[
            "consumer_execution_readiness"
        ],
        "consumer_dispatch_readiness": consumer_release_window[
            "consumer_dispatch_readiness"
        ],
        "consumer_dispatch_authority": consumer_release_window[
            "consumer_dispatch_authority"
        ],
        "consumer_dispatch_permission": consumer_release_window[
            "consumer_dispatch_permission"
        ],
        "consumer_dispatch_clearance": consumer_release_window[
            "consumer_dispatch_clearance"
        ],
        "consumer_release_decision": consumer_release_window["consumer_release_decision"],
        "consumer_release_mode": consumer_release_window["consumer_release_mode"],
        "consumer_release_execution_requirement": consumer_release_window[
            "consumer_release_execution_requirement"
        ],
        "consumer_release_execution_lane": consumer_release_window[
            "consumer_release_execution_lane"
        ],
        "consumer_release_handling_intent": consumer_release_window[
            "consumer_release_handling_intent"
        ],
        "consumer_release_action_plan": consumer_release_window[
            "consumer_release_action_plan"
        ],
        "consumer_release_queue": consumer_release_window["consumer_release_queue"],
        "consumer_release_priority": consumer_release_window["consumer_release_priority"],
        "consumer_release_window": consumer_release_window["consumer_release_window"],
        "consumer_release_schedule": release_schedule_by_window[
            consumer_release_window["consumer_release_window"]
        ],
    }
    if "related_project_id" in consumer_release_window:
        consumer_release_schedule["related_project_id"] = consumer_release_window[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_release_window:
        consumer_release_schedule["related_activation_decision_id"] = (
            consumer_release_window["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_release_window:
        consumer_release_schedule["related_packet_id"] = consumer_release_window[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_release_window:
        consumer_release_schedule["related_queue_item_id"] = consumer_release_window[
            "related_queue_item_id"
        ]
    return consumer_release_schedule


def build_consumer_release_readiness_from_schedule(
    *,
    consumer_release_schedule: dict[str, Any],
) -> dict[str, Any]:
    """Build pure consumer release readiness from existing release schedule."""
    release_readiness_by_schedule = {
        "backlog_schedule": "not_ready",
        "guarded_schedule": "prepared",
        "immediate_schedule": "ready",
    }
    consumer_release_readiness: dict[str, Any] = {
        "projected_activation_decision": consumer_release_schedule[
            "projected_activation_decision"
        ],
        "approval_record": consumer_release_schedule["approval_record"],
        "receiver_readiness_classification": consumer_release_schedule[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_release_schedule[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_release_schedule["receiver_action_label"],
        "receiver_dispatch_intent": consumer_release_schedule["receiver_dispatch_intent"],
        "receiver_dispatch_mode": consumer_release_schedule["receiver_dispatch_mode"],
        "receiver_release_gate": consumer_release_schedule["receiver_release_gate"],
        "receiver_progress_state": consumer_release_schedule["receiver_progress_state"],
        "receiver_progress_signal": consumer_release_schedule["receiver_progress_signal"],
        "receiver_progress_outcome": consumer_release_schedule["receiver_progress_outcome"],
        "receiver_intervention_requirement": consumer_release_schedule[
            "receiver_intervention_requirement"
        ],
        "receiver_attention_level": consumer_release_schedule[
            "receiver_attention_level"
        ],
        "receiver_notification_requirement": consumer_release_schedule[
            "receiver_notification_requirement"
        ],
        "receiver_response_priority": consumer_release_schedule[
            "receiver_response_priority"
        ],
        "receiver_response_channel": consumer_release_schedule[
            "receiver_response_channel"
        ],
        "receiver_response_route": consumer_release_schedule["receiver_response_route"],
        "receiver_followup_requirement": consumer_release_schedule[
            "receiver_followup_requirement"
        ],
        "consumer_decision_posture": consumer_release_schedule["consumer_decision_posture"],
        "consumer_action_requirement": consumer_release_schedule[
            "consumer_action_requirement"
        ],
        "consumer_work_queue_assignment": consumer_release_schedule[
            "consumer_work_queue_assignment"
        ],
        "consumer_processing_plan": consumer_release_schedule["consumer_processing_plan"],
        "consumer_operator_requirement": consumer_release_schedule[
            "consumer_operator_requirement"
        ],
        "consumer_assignment_lane": consumer_release_schedule["consumer_assignment_lane"],
        "consumer_service_tier": consumer_release_schedule["consumer_service_tier"],
        "consumer_sla_class": consumer_release_schedule["consumer_sla_class"],
        "consumer_response_window": consumer_release_schedule["consumer_response_window"],
        "consumer_timing_posture": consumer_release_schedule["consumer_timing_posture"],
        "consumer_scheduling_commitment": consumer_release_schedule[
            "consumer_scheduling_commitment"
        ],
        "consumer_execution_readiness": consumer_release_schedule[
            "consumer_execution_readiness"
        ],
        "consumer_dispatch_readiness": consumer_release_schedule[
            "consumer_dispatch_readiness"
        ],
        "consumer_dispatch_authority": consumer_release_schedule[
            "consumer_dispatch_authority"
        ],
        "consumer_dispatch_permission": consumer_release_schedule[
            "consumer_dispatch_permission"
        ],
        "consumer_dispatch_clearance": consumer_release_schedule[
            "consumer_dispatch_clearance"
        ],
        "consumer_release_decision": consumer_release_schedule[
            "consumer_release_decision"
        ],
        "consumer_release_mode": consumer_release_schedule["consumer_release_mode"],
        "consumer_release_execution_requirement": consumer_release_schedule[
            "consumer_release_execution_requirement"
        ],
        "consumer_release_execution_lane": consumer_release_schedule[
            "consumer_release_execution_lane"
        ],
        "consumer_release_handling_intent": consumer_release_schedule[
            "consumer_release_handling_intent"
        ],
        "consumer_release_action_plan": consumer_release_schedule[
            "consumer_release_action_plan"
        ],
        "consumer_release_queue": consumer_release_schedule["consumer_release_queue"],
        "consumer_release_priority": consumer_release_schedule[
            "consumer_release_priority"
        ],
        "consumer_release_window": consumer_release_schedule["consumer_release_window"],
        "consumer_release_schedule": consumer_release_schedule["consumer_release_schedule"],
        "consumer_release_readiness": release_readiness_by_schedule[
            consumer_release_schedule["consumer_release_schedule"]
        ],
    }
    if "related_project_id" in consumer_release_schedule:
        consumer_release_readiness["related_project_id"] = consumer_release_schedule[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_release_schedule:
        consumer_release_readiness["related_activation_decision_id"] = (
            consumer_release_schedule["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_release_schedule:
        consumer_release_readiness["related_packet_id"] = consumer_release_schedule[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_release_schedule:
        consumer_release_readiness["related_queue_item_id"] = consumer_release_schedule[
            "related_queue_item_id"
        ]
    return consumer_release_readiness


def build_consumer_release_authority_from_readiness(
    *,
    consumer_release_readiness: dict[str, Any],
) -> dict[str, Any]:
    """Build pure consumer release authority from existing release readiness."""
    release_authority_by_readiness = {
        "not_ready": "withhold",
        "prepared": "conditional_authority",
        "ready": "full_authority",
    }
    consumer_release_authority: dict[str, Any] = {
        "projected_activation_decision": consumer_release_readiness[
            "projected_activation_decision"
        ],
        "approval_record": consumer_release_readiness["approval_record"],
        "receiver_readiness_classification": consumer_release_readiness[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_release_readiness[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_release_readiness["receiver_action_label"],
        "receiver_dispatch_intent": consumer_release_readiness["receiver_dispatch_intent"],
        "receiver_dispatch_mode": consumer_release_readiness["receiver_dispatch_mode"],
        "receiver_release_gate": consumer_release_readiness["receiver_release_gate"],
        "receiver_progress_state": consumer_release_readiness["receiver_progress_state"],
        "receiver_progress_signal": consumer_release_readiness["receiver_progress_signal"],
        "receiver_progress_outcome": consumer_release_readiness["receiver_progress_outcome"],
        "receiver_intervention_requirement": consumer_release_readiness[
            "receiver_intervention_requirement"
        ],
        "receiver_attention_level": consumer_release_readiness[
            "receiver_attention_level"
        ],
        "receiver_notification_requirement": consumer_release_readiness[
            "receiver_notification_requirement"
        ],
        "receiver_response_priority": consumer_release_readiness[
            "receiver_response_priority"
        ],
        "receiver_response_channel": consumer_release_readiness[
            "receiver_response_channel"
        ],
        "receiver_response_route": consumer_release_readiness["receiver_response_route"],
        "receiver_followup_requirement": consumer_release_readiness[
            "receiver_followup_requirement"
        ],
        "consumer_decision_posture": consumer_release_readiness[
            "consumer_decision_posture"
        ],
        "consumer_action_requirement": consumer_release_readiness[
            "consumer_action_requirement"
        ],
        "consumer_work_queue_assignment": consumer_release_readiness[
            "consumer_work_queue_assignment"
        ],
        "consumer_processing_plan": consumer_release_readiness[
            "consumer_processing_plan"
        ],
        "consumer_operator_requirement": consumer_release_readiness[
            "consumer_operator_requirement"
        ],
        "consumer_assignment_lane": consumer_release_readiness["consumer_assignment_lane"],
        "consumer_service_tier": consumer_release_readiness["consumer_service_tier"],
        "consumer_sla_class": consumer_release_readiness["consumer_sla_class"],
        "consumer_response_window": consumer_release_readiness["consumer_response_window"],
        "consumer_timing_posture": consumer_release_readiness["consumer_timing_posture"],
        "consumer_scheduling_commitment": consumer_release_readiness[
            "consumer_scheduling_commitment"
        ],
        "consumer_execution_readiness": consumer_release_readiness[
            "consumer_execution_readiness"
        ],
        "consumer_dispatch_readiness": consumer_release_readiness[
            "consumer_dispatch_readiness"
        ],
        "consumer_dispatch_authority": consumer_release_readiness[
            "consumer_dispatch_authority"
        ],
        "consumer_dispatch_permission": consumer_release_readiness[
            "consumer_dispatch_permission"
        ],
        "consumer_dispatch_clearance": consumer_release_readiness[
            "consumer_dispatch_clearance"
        ],
        "consumer_release_decision": consumer_release_readiness[
            "consumer_release_decision"
        ],
        "consumer_release_mode": consumer_release_readiness["consumer_release_mode"],
        "consumer_release_execution_requirement": consumer_release_readiness[
            "consumer_release_execution_requirement"
        ],
        "consumer_release_execution_lane": consumer_release_readiness[
            "consumer_release_execution_lane"
        ],
        "consumer_release_handling_intent": consumer_release_readiness[
            "consumer_release_handling_intent"
        ],
        "consumer_release_action_plan": consumer_release_readiness[
            "consumer_release_action_plan"
        ],
        "consumer_release_queue": consumer_release_readiness["consumer_release_queue"],
        "consumer_release_priority": consumer_release_readiness[
            "consumer_release_priority"
        ],
        "consumer_release_window": consumer_release_readiness["consumer_release_window"],
        "consumer_release_schedule": consumer_release_readiness["consumer_release_schedule"],
        "consumer_release_readiness": consumer_release_readiness[
            "consumer_release_readiness"
        ],
        "consumer_release_authority": release_authority_by_readiness[
            consumer_release_readiness["consumer_release_readiness"]
        ],
    }
    if "related_project_id" in consumer_release_readiness:
        consumer_release_authority["related_project_id"] = consumer_release_readiness[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_release_readiness:
        consumer_release_authority["related_activation_decision_id"] = (
            consumer_release_readiness["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_release_readiness:
        consumer_release_authority["related_packet_id"] = consumer_release_readiness[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_release_readiness:
        consumer_release_authority["related_queue_item_id"] = consumer_release_readiness[
            "related_queue_item_id"
        ]
    return consumer_release_authority


def build_consumer_release_permission_from_authority(
    *,
    consumer_release_authority: dict[str, Any],
) -> dict[str, Any]:
    """Build pure consumer release permission from existing release authority."""
    release_permission_by_authority = {
        "withhold": "not_permitted",
        "conditional_authority": "conditionally_permitted",
        "full_authority": "permitted",
    }
    consumer_release_permission: dict[str, Any] = {
        "projected_activation_decision": consumer_release_authority[
            "projected_activation_decision"
        ],
        "approval_record": consumer_release_authority["approval_record"],
        "receiver_readiness_classification": consumer_release_authority[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_release_authority[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_release_authority["receiver_action_label"],
        "receiver_dispatch_intent": consumer_release_authority[
            "receiver_dispatch_intent"
        ],
        "receiver_dispatch_mode": consumer_release_authority["receiver_dispatch_mode"],
        "receiver_release_gate": consumer_release_authority["receiver_release_gate"],
        "receiver_progress_state": consumer_release_authority["receiver_progress_state"],
        "receiver_progress_signal": consumer_release_authority["receiver_progress_signal"],
        "receiver_progress_outcome": consumer_release_authority["receiver_progress_outcome"],
        "receiver_intervention_requirement": consumer_release_authority[
            "receiver_intervention_requirement"
        ],
        "receiver_attention_level": consumer_release_authority[
            "receiver_attention_level"
        ],
        "receiver_notification_requirement": consumer_release_authority[
            "receiver_notification_requirement"
        ],
        "receiver_response_priority": consumer_release_authority[
            "receiver_response_priority"
        ],
        "receiver_response_channel": consumer_release_authority[
            "receiver_response_channel"
        ],
        "receiver_response_route": consumer_release_authority["receiver_response_route"],
        "receiver_followup_requirement": consumer_release_authority[
            "receiver_followup_requirement"
        ],
        "consumer_decision_posture": consumer_release_authority[
            "consumer_decision_posture"
        ],
        "consumer_action_requirement": consumer_release_authority[
            "consumer_action_requirement"
        ],
        "consumer_work_queue_assignment": consumer_release_authority[
            "consumer_work_queue_assignment"
        ],
        "consumer_processing_plan": consumer_release_authority[
            "consumer_processing_plan"
        ],
        "consumer_operator_requirement": consumer_release_authority[
            "consumer_operator_requirement"
        ],
        "consumer_assignment_lane": consumer_release_authority["consumer_assignment_lane"],
        "consumer_service_tier": consumer_release_authority["consumer_service_tier"],
        "consumer_sla_class": consumer_release_authority["consumer_sla_class"],
        "consumer_response_window": consumer_release_authority["consumer_response_window"],
        "consumer_timing_posture": consumer_release_authority["consumer_timing_posture"],
        "consumer_scheduling_commitment": consumer_release_authority[
            "consumer_scheduling_commitment"
        ],
        "consumer_execution_readiness": consumer_release_authority[
            "consumer_execution_readiness"
        ],
        "consumer_dispatch_readiness": consumer_release_authority[
            "consumer_dispatch_readiness"
        ],
        "consumer_dispatch_authority": consumer_release_authority[
            "consumer_dispatch_authority"
        ],
        "consumer_dispatch_permission": consumer_release_authority[
            "consumer_dispatch_permission"
        ],
        "consumer_dispatch_clearance": consumer_release_authority[
            "consumer_dispatch_clearance"
        ],
        "consumer_release_decision": consumer_release_authority[
            "consumer_release_decision"
        ],
        "consumer_release_mode": consumer_release_authority["consumer_release_mode"],
        "consumer_release_execution_requirement": consumer_release_authority[
            "consumer_release_execution_requirement"
        ],
        "consumer_release_execution_lane": consumer_release_authority[
            "consumer_release_execution_lane"
        ],
        "consumer_release_handling_intent": consumer_release_authority[
            "consumer_release_handling_intent"
        ],
        "consumer_release_action_plan": consumer_release_authority[
            "consumer_release_action_plan"
        ],
        "consumer_release_queue": consumer_release_authority["consumer_release_queue"],
        "consumer_release_priority": consumer_release_authority[
            "consumer_release_priority"
        ],
        "consumer_release_window": consumer_release_authority["consumer_release_window"],
        "consumer_release_schedule": consumer_release_authority["consumer_release_schedule"],
        "consumer_release_readiness": consumer_release_authority[
            "consumer_release_readiness"
        ],
        "consumer_release_authority": consumer_release_authority[
            "consumer_release_authority"
        ],
        "consumer_release_permission": release_permission_by_authority[
            consumer_release_authority["consumer_release_authority"]
        ],
    }
    if "related_project_id" in consumer_release_authority:
        consumer_release_permission["related_project_id"] = consumer_release_authority[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_release_authority:
        consumer_release_permission["related_activation_decision_id"] = (
            consumer_release_authority["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_release_authority:
        consumer_release_permission["related_packet_id"] = consumer_release_authority[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_release_authority:
        consumer_release_permission["related_queue_item_id"] = consumer_release_authority[
            "related_queue_item_id"
        ]
    return consumer_release_permission


def build_consumer_release_clearance_from_permission(
    *,
    consumer_release_permission: dict[str, Any],
) -> dict[str, Any]:
    """Build pure consumer release clearance from existing release permission."""
    release_clearance_by_permission = {
        "not_permitted": "blocked",
        "conditionally_permitted": "gated",
        "permitted": "clear",
    }
    consumer_release_clearance: dict[str, Any] = {
        "projected_activation_decision": consumer_release_permission[
            "projected_activation_decision"
        ],
        "approval_record": consumer_release_permission["approval_record"],
        "receiver_readiness_classification": consumer_release_permission[
            "receiver_readiness_classification"
        ],
        "receiver_handling_directive": consumer_release_permission[
            "receiver_handling_directive"
        ],
        "receiver_action_label": consumer_release_permission["receiver_action_label"],
        "receiver_dispatch_intent": consumer_release_permission[
            "receiver_dispatch_intent"
        ],
        "receiver_dispatch_mode": consumer_release_permission["receiver_dispatch_mode"],
        "receiver_release_gate": consumer_release_permission["receiver_release_gate"],
        "receiver_progress_state": consumer_release_permission["receiver_progress_state"],
        "receiver_progress_signal": consumer_release_permission["receiver_progress_signal"],
        "receiver_progress_outcome": consumer_release_permission["receiver_progress_outcome"],
        "receiver_intervention_requirement": consumer_release_permission[
            "receiver_intervention_requirement"
        ],
        "receiver_attention_level": consumer_release_permission[
            "receiver_attention_level"
        ],
        "receiver_notification_requirement": consumer_release_permission[
            "receiver_notification_requirement"
        ],
        "receiver_response_priority": consumer_release_permission[
            "receiver_response_priority"
        ],
        "receiver_response_channel": consumer_release_permission[
            "receiver_response_channel"
        ],
        "receiver_response_route": consumer_release_permission["receiver_response_route"],
        "receiver_followup_requirement": consumer_release_permission[
            "receiver_followup_requirement"
        ],
        "consumer_decision_posture": consumer_release_permission[
            "consumer_decision_posture"
        ],
        "consumer_action_requirement": consumer_release_permission[
            "consumer_action_requirement"
        ],
        "consumer_work_queue_assignment": consumer_release_permission[
            "consumer_work_queue_assignment"
        ],
        "consumer_processing_plan": consumer_release_permission[
            "consumer_processing_plan"
        ],
        "consumer_operator_requirement": consumer_release_permission[
            "consumer_operator_requirement"
        ],
        "consumer_assignment_lane": consumer_release_permission["consumer_assignment_lane"],
        "consumer_service_tier": consumer_release_permission["consumer_service_tier"],
        "consumer_sla_class": consumer_release_permission["consumer_sla_class"],
        "consumer_response_window": consumer_release_permission["consumer_response_window"],
        "consumer_timing_posture": consumer_release_permission["consumer_timing_posture"],
        "consumer_scheduling_commitment": consumer_release_permission[
            "consumer_scheduling_commitment"
        ],
        "consumer_execution_readiness": consumer_release_permission[
            "consumer_execution_readiness"
        ],
        "consumer_dispatch_readiness": consumer_release_permission[
            "consumer_dispatch_readiness"
        ],
        "consumer_dispatch_authority": consumer_release_permission[
            "consumer_dispatch_authority"
        ],
        "consumer_dispatch_permission": consumer_release_permission[
            "consumer_dispatch_permission"
        ],
        "consumer_dispatch_clearance": consumer_release_permission[
            "consumer_dispatch_clearance"
        ],
        "consumer_release_decision": consumer_release_permission[
            "consumer_release_decision"
        ],
        "consumer_release_mode": consumer_release_permission["consumer_release_mode"],
        "consumer_release_execution_requirement": consumer_release_permission[
            "consumer_release_execution_requirement"
        ],
        "consumer_release_execution_lane": consumer_release_permission[
            "consumer_release_execution_lane"
        ],
        "consumer_release_handling_intent": consumer_release_permission[
            "consumer_release_handling_intent"
        ],
        "consumer_release_action_plan": consumer_release_permission[
            "consumer_release_action_plan"
        ],
        "consumer_release_queue": consumer_release_permission["consumer_release_queue"],
        "consumer_release_priority": consumer_release_permission[
            "consumer_release_priority"
        ],
        "consumer_release_window": consumer_release_permission["consumer_release_window"],
        "consumer_release_schedule": consumer_release_permission["consumer_release_schedule"],
        "consumer_release_readiness": consumer_release_permission[
            "consumer_release_readiness"
        ],
        "consumer_release_authority": consumer_release_permission[
            "consumer_release_authority"
        ],
        "consumer_release_permission": consumer_release_permission[
            "consumer_release_permission"
        ],
        "consumer_release_clearance": release_clearance_by_permission[
            consumer_release_permission["consumer_release_permission"]
        ],
    }
    if "related_project_id" in consumer_release_permission:
        consumer_release_clearance["related_project_id"] = consumer_release_permission[
            "related_project_id"
        ]
    if "related_activation_decision_id" in consumer_release_permission:
        consumer_release_clearance["related_activation_decision_id"] = (
            consumer_release_permission["related_activation_decision_id"]
        )
    if "related_packet_id" in consumer_release_permission:
        consumer_release_clearance["related_packet_id"] = consumer_release_permission[
            "related_packet_id"
        ]
    if "related_queue_item_id" in consumer_release_permission:
        consumer_release_clearance["related_queue_item_id"] = consumer_release_permission[
            "related_queue_item_id"
        ]
    return consumer_release_clearance
