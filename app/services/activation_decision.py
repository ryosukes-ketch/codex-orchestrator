from dataclasses import dataclass
from typing import Any, Literal

from app.schemas.management import ManagementReviewPacket
from app.schemas.management_decision import ManagementDecisionRecord
from app.schemas.review_queue import ReviewQueueItem

DecisionValue = Literal["GO", "PAUSE", "REVIEW"]

_ACTION_DEPARTMENT = "action_department"
_LIMITED_LIVE_PROVIDER_USE = "limited_live_provider_use"
_ACTIVATION_CHECKPOINT = "limited_live_provider_use_activation"
_AUDIT_AND_REVIEW_DEPARTMENT = "Audit and Review Department"
_AUTONOMOUS_NOT_APPROVED = "not_approved"
_AUTONOMOUS_NOTE = (
    "Autonomous continuation remains not approved unless explicitly approved "
    "through the required governance process."
)


@dataclass(frozen=True)
class DryRunActivationDecision:
    activation_target: dict[str, Any]
    activation_scope: dict[str, list[str]]
    preconditions_satisfied: list[str]
    remaining_blockers: list[str]
    human_approvals_recorded: list[dict[str, str]]
    recommendation: DecisionValue
    autonomous_continuation_status: str
    autonomous_continuation_note: str
    rollback_disable_expectation: str
    escalation_destination: str | None = None
    re_review_required: bool = False


def derive_dry_run_activation_decision(
    *,
    management_review_packet: ManagementReviewPacket,
    review_queue_item: ReviewQueueItem,
    management_decision: ManagementDecisionRecord,
) -> DryRunActivationDecision:
    unresolved_blockers = _collect_unresolved_blockers(review_queue_item)
    recommendation: DecisionValue = management_decision.decision

    # Unresolved blockers prevent continuation even if management decision says GO.
    if recommendation == "GO" and unresolved_blockers:
        recommendation = "PAUSE"
    if recommendation == "GO" and management_review_packet.required_review:
        recommendation = "PAUSE"

    escalation_destination: str | None = None
    if recommendation == "REVIEW":
        escalation_destination = _AUDIT_AND_REVIEW_DEPARTMENT

    human_status = _human_status_for_decision(recommendation)
    rollback_expectation = _rollback_expectation_for_decision(recommendation)
    preconditions = _build_preconditions(
        unresolved_blockers=unresolved_blockers,
        management_review_packet=management_review_packet,
    )

    return DryRunActivationDecision(
        activation_target={
            "department": _ACTION_DEPARTMENT,
            "provider_use_mode": _LIMITED_LIVE_PROVIDER_USE,
            "provider_aliases": [
                "gemini-flash-lite-latest",
                "gemini-flash-latest",
            ],
        },
        activation_scope={
            "allowed_use_cases": [
                "low-risk extraction",
                "low-risk classification",
                "draft summarization for management review artifacts",
            ],
            "excluded_use_cases": [
                "final authority for risky continuation",
                "auth/approval/policy/audit decisions",
                "automatic autonomous continuation",
            ],
        },
        preconditions_satisfied=preconditions,
        remaining_blockers=unresolved_blockers,
        human_approvals_recorded=[
            {
                "checkpoint": _ACTIVATION_CHECKPOINT,
                "status": human_status,
                "approver_id": management_decision.reviewer_id,
                "approver_type": management_decision.reviewer_type,
                "note": "Derived from management decision artifact in dry-run mode.",
            }
        ],
        recommendation=recommendation,
        autonomous_continuation_status=_AUTONOMOUS_NOT_APPROVED,
        autonomous_continuation_note=_AUTONOMOUS_NOTE,
        rollback_disable_expectation=rollback_expectation,
        escalation_destination=escalation_destination,
        re_review_required=bool(unresolved_blockers) or recommendation in {"PAUSE", "REVIEW"},
    )


def _collect_unresolved_blockers(review_queue_item: ReviewQueueItem) -> list[str]:
    blockers: list[str] = []
    blockers.extend(review_queue_item.hard_gate_triggers)
    blockers.extend(review_queue_item.escalation_reasons)
    if review_queue_item.escalation_reason:
        blockers.append(review_queue_item.escalation_reason)
    if review_queue_item.hard_gate_status and not blockers:
        blockers.append("hard_gate_active")
    return _unique_preserve_order(blockers)


def _build_preconditions(
    *,
    unresolved_blockers: list[str],
    management_review_packet: ManagementReviewPacket,
) -> list[str]:
    preconditions = [
        "management_review_packet validated",
        "review_queue_item validated",
        "management_decision validated",
    ]
    if not unresolved_blockers and not management_review_packet.required_review:
        preconditions.append("no unresolved blockers detected")
    return preconditions


def _human_status_for_decision(decision: DecisionValue) -> str:
    if decision == "GO":
        return "approved"
    if decision == "PAUSE":
        return "pending"
    return "withheld"


def _rollback_expectation_for_decision(decision: DecisionValue) -> str:
    if decision == "GO":
        return (
            "If any guardrail fails, disable limited live provider use immediately "
            "and route work to REVIEW."
        )
    if decision == "PAUSE":
        return (
            "Keep limited live provider use disabled until blockers are resolved and "
            "re-review is completed."
        )
    return (
        "Do not activate limited live provider use; maintain disabled state and route "
        "all related work through REVIEW escalation."
    )


def _unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        normalized = value.strip()
        if not normalized:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result
