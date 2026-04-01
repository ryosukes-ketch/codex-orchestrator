from typing import Any

from app.services.activation_decision import DryRunActivationDecision

_DEFAULT_RATIONALE = "Derived from projected activation decision in dry-run mode."
_RETAINED_CONSTRAINTS_BY_DECISION = {
    "GO": [
        "latest-alias outputs remain advisory-only for risky work",
        "hard-gate-first REVIEW escalation remains mandatory",
        "external sends and production-impacting actions remain separately approval-gated",
    ],
    "PAUSE": [
        "latest-alias outputs remain advisory-only for risky work",
        "hard-gate-first REVIEW escalation remains mandatory",
    ],
    "REVIEW": [
        "latest-alias outputs remain advisory-only for risky work",
        "no live provider activation while hard-gate concerns remain unresolved",
    ],
}


def build_action_department_activation_approval_record(
    *,
    projected_activation_decision: DryRunActivationDecision,
    activation_review_item_id: str,
    approval_record_id: str | None = None,
    reviewer_id: str | None = None,
    reviewer_type: str | None = None,
    rationale: str | None = None,
    related_project_id: str | None = None,
    related_activation_decision_id: str | None = None,
    related_packet_id: str | None = None,
    related_queue_item_id: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic approval-record artifact from projected activation data."""
    recommendation = projected_activation_decision.recommendation
    first_approval = projected_activation_decision.human_approvals_recorded[0]
    escalation_destination = projected_activation_decision.escalation_destination

    if recommendation == "REVIEW" and not escalation_destination:
        raise ValueError(
            "REVIEW recommendation requires explicit escalation destination."
        )

    resolved_reviewer_id = reviewer_id or first_approval.get("approver_id", "unknown-reviewer")
    resolved_reviewer_type = reviewer_type or first_approval.get(
        "approver_type", "unknown-type"
    )
    management_note = _management_review_note_for_decision(
        recommendation=recommendation,
        escalation_destination=escalation_destination,
        re_review_required=projected_activation_decision.re_review_required,
    )

    record: dict[str, Any] = {
        "approval_record_id": approval_record_id
        or f"approval_record_for_{activation_review_item_id}",
        "activation_review_item_id": activation_review_item_id,
        "activation_target": projected_activation_decision.activation_target,
        "activation_scope": projected_activation_decision.activation_scope,
        "human_approval_status": {
            "status": first_approval.get("status", "pending"),
            "checkpoint": first_approval.get(
                "checkpoint", "limited_live_provider_use_activation"
            ),
            "approver_id": first_approval.get("approver_id", "unknown-reviewer"),
            "note": first_approval.get(
                "note", "Derived from projected activation decision."
            ),
        },
        "management_review_status": {
            "status": "completed",
            "reviewer_id": resolved_reviewer_id,
            "reviewer_type": resolved_reviewer_type,
            "review_outcome": recommendation,
            "note": management_note,
        },
        "recommendation": recommendation,
        "autonomous_continuation_status": (
            projected_activation_decision.autonomous_continuation_status
        ),
        "autonomous_continuation_note": projected_activation_decision.autonomous_continuation_note,
        "retained_constraints": _RETAINED_CONSTRAINTS_BY_DECISION[recommendation],
        "blocker_notes": list(projected_activation_decision.remaining_blockers),
        "rollback_disable_expectation": projected_activation_decision.rollback_disable_expectation,
        "follow_up_actions_before_broader_live_use": _follow_up_actions_for_decision(
            recommendation=recommendation,
            escalation_destination=escalation_destination,
            re_review_required=projected_activation_decision.re_review_required,
        ),
        "rationale": rationale or _DEFAULT_RATIONALE,
    }

    if related_project_id is not None:
        record["related_project_id"] = related_project_id
    if related_activation_decision_id is not None:
        record["related_activation_decision_id"] = related_activation_decision_id
    if related_packet_id is not None:
        record["related_packet_id"] = related_packet_id
    if related_queue_item_id is not None:
        record["related_queue_item_id"] = related_queue_item_id

    return record


def _management_review_note_for_decision(
    *,
    recommendation: str,
    escalation_destination: str | None,
    re_review_required: bool,
) -> str:
    if recommendation == "GO":
        return "GO for limited activation review path only."
    if recommendation == "PAUSE":
        if re_review_required:
            return "Pause until blockers are resolved and re-review is completed."
        return "Pause until blockers are resolved."
    return (
        f"Escalate to {escalation_destination} for unresolved blocker set."
    )


def _follow_up_actions_for_decision(
    *,
    recommendation: str,
    escalation_destination: str | None,
    re_review_required: bool,
) -> list[str]:
    if recommendation == "GO":
        return [
            "Complete authn/policy hardening backlog",
            "Run rollback drills for limited live provider incidents",
            "Document broadened live-use criteria with Management + Audit sign-off",
        ]
    if recommendation == "PAUSE":
        actions = ["Resolve remaining blockers before activation reconsideration."]
        if re_review_required:
            actions.append("Complete re-review before continuation.")
        return actions
    return [
        f"Escalate to {escalation_destination} before activation reconsideration.",
        "Resolve retained blockers and resubmit through management review.",
    ]
