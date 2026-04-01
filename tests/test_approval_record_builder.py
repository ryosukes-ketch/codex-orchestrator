import json
from pathlib import Path
from typing import Literal

import pytest

from app.services.activation_decision import DryRunActivationDecision
from app.services.approval_record_builder import (
    build_action_department_activation_approval_record,
)

RecommendationValue = Literal["GO", "PAUSE", "REVIEW"]
ApprovalStatusValue = Literal["approved", "pending", "withheld"]
_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_CASES = [
    pytest.param(
        "go",
        "docs/examples/action_department_activation_approval_record_example.json",
        False,
        None,
        id="go",
    ),
    pytest.param(
        "pause",
        "docs/examples/action_department_activation_approval_record_pause_example.json",
        True,
        None,
        id="pause",
    ),
    pytest.param(
        "review",
        "docs/examples/action_department_activation_approval_record_review_example.json",
        True,
        "Audit and Review Department",
        id="review",
    ),
]


def test_build_approval_record_go_mapping() -> None:
    projected = _make_projected_activation_decision(
        recommendation="GO",
        approval_status="approved",
        remaining_blockers=[],
        re_review_required=False,
        escalation_destination=None,
        rollback_disable_expectation=(
            "If any guardrail fails, disable limited live provider use immediately "
            "and route work to REVIEW."
        ),
    )

    record = build_action_department_activation_approval_record(
        projected_activation_decision=projected,
        activation_review_item_id="activation_review_20260325_go",
        related_project_id="project_001",
        related_activation_decision_id="act_decision_20260325_001",
    )

    assert record["recommendation"] == "GO"
    assert record["human_approval_status"]["status"] == "approved"
    assert record["management_review_status"]["review_outcome"] == "GO"
    assert (
        record["management_review_status"]["note"]
        == "GO for limited activation review path only."
    )
    assert record["blocker_notes"] == []
    assert record["autonomous_continuation_status"] == "not_approved"
    assert "autonomous continuation remains not approved" in record[
        "autonomous_continuation_note"
    ].lower()
    assert record["related_project_id"] == "project_001"
    assert record["related_activation_decision_id"] == "act_decision_20260325_001"


def test_build_approval_record_pause_mapping() -> None:
    projected = _make_projected_activation_decision(
        recommendation="PAUSE",
        approval_status="pending",
        remaining_blockers=["rollback_evidence_missing", "hard_gate_triggered"],
        re_review_required=True,
        escalation_destination=None,
        rollback_disable_expectation=(
            "Keep limited live provider use disabled until blockers are resolved and "
            "re-review is completed."
        ),
    )

    record = build_action_department_activation_approval_record(
        projected_activation_decision=projected,
        activation_review_item_id="activation_review_20260325_pause",
    )

    assert record["recommendation"] == "PAUSE"
    assert record["human_approval_status"]["status"] == "pending"
    assert record["management_review_status"]["review_outcome"] == "PAUSE"
    assert "re-review is completed" in record["management_review_status"]["note"]
    assert record["blocker_notes"] == ["rollback_evidence_missing", "hard_gate_triggered"]
    assert record["autonomous_continuation_status"] == "not_approved"
    assert "Complete re-review before continuation." in record[
        "follow_up_actions_before_broader_live_use"
    ]


def test_build_approval_record_review_mapping() -> None:
    projected = _make_projected_activation_decision(
        recommendation="REVIEW",
        approval_status="withheld",
        remaining_blockers=[
            "approval_flow_change",
            "hard_gate_triggered",
            "cross_department_routing",
        ],
        re_review_required=True,
        escalation_destination="Audit and Review Department",
        rollback_disable_expectation=(
            "Do not activate limited live provider use; maintain disabled state and route "
            "all related work through REVIEW escalation."
        ),
    )

    record = build_action_department_activation_approval_record(
        projected_activation_decision=projected,
        activation_review_item_id="activation_review_20260325_review",
    )

    assert record["recommendation"] == "REVIEW"
    assert record["human_approval_status"]["status"] == "withheld"
    assert record["management_review_status"]["review_outcome"] == "REVIEW"
    assert (
        record["management_review_status"]["note"]
        == "Escalate to Audit and Review Department for unresolved blocker set."
    )
    assert (
        "Audit and Review Department"
        in record["management_review_status"]["note"]
    )
    assert record["blocker_notes"] == [
        "approval_flow_change",
        "hard_gate_triggered",
        "cross_department_routing",
    ]
    assert record["autonomous_continuation_status"] == "not_approved"
    assert "no live provider activation" in " ".join(record["retained_constraints"]).lower()


def test_build_approval_record_review_requires_escalation_destination() -> None:
    projected = _make_projected_activation_decision(
        recommendation="REVIEW",
        approval_status="withheld",
        remaining_blockers=["approval_flow_change"],
        re_review_required=True,
        escalation_destination=None,
        rollback_disable_expectation=(
            "Do not activate limited live provider use; maintain disabled state and route "
            "all related work through REVIEW escalation."
        ),
    )

    with pytest.raises(
        ValueError,
        match="REVIEW recommendation requires explicit escalation destination.",
    ):
        build_action_department_activation_approval_record(
            projected_activation_decision=projected,
            activation_review_item_id="activation_review_20260325_review_missing_escalation",
        )


def test_build_approval_record_preserves_optional_metadata_ids() -> None:
    projected = _make_projected_activation_decision(
        recommendation="GO",
        approval_status="approved",
        remaining_blockers=[],
        re_review_required=False,
        escalation_destination=None,
        rollback_disable_expectation=(
            "If any guardrail fails, disable limited live provider use immediately "
            "and route work to REVIEW."
        ),
    )

    record = build_action_department_activation_approval_record(
        projected_activation_decision=projected,
        activation_review_item_id="activation_review_optional_ids_1",
        approval_record_id="approval_record_optional_ids_1",
        related_project_id="project_optional_ids_1",
        related_activation_decision_id="activation_decision_optional_ids_1",
        related_packet_id="packet_optional_ids_1",
        related_queue_item_id="queue_optional_ids_1",
    )

    assert record["approval_record_id"] == "approval_record_optional_ids_1"
    assert record["related_project_id"] == "project_optional_ids_1"
    assert (
        record["related_activation_decision_id"]
        == "activation_decision_optional_ids_1"
    )
    assert record["related_packet_id"] == "packet_optional_ids_1"
    assert record["related_queue_item_id"] == "queue_optional_ids_1"


def test_build_approval_record_uses_fallback_reviewer_and_default_rationale() -> None:
    projected = _make_projected_activation_decision(
        recommendation="PAUSE",
        approval_status="pending",
        remaining_blockers=["rollback_evidence_missing"],
        re_review_required=True,
        escalation_destination=None,
        rollback_disable_expectation=(
            "Keep limited live provider use disabled until blockers are resolved and "
            "re-review is completed."
        ),
    )

    record = build_action_department_activation_approval_record(
        projected_activation_decision=projected,
        activation_review_item_id="activation_review_fallback_fields_1",
    )

    first_approval = projected.human_approvals_recorded[0]
    assert (
        record["management_review_status"]["reviewer_id"] == first_approval["approver_id"]
    )
    assert (
        record["management_review_status"]["reviewer_type"]
        == first_approval["approver_type"]
    )
    assert (
        record["rationale"]
        == "Derived from projected activation decision in dry-run mode."
    )


def test_build_approval_record_review_follow_up_actions_include_escalation_destination() -> None:
    projected = _make_projected_activation_decision(
        recommendation="REVIEW",
        approval_status="withheld",
        remaining_blockers=["approval_flow_change", "hard_gate_triggered"],
        re_review_required=True,
        escalation_destination="Audit and Review Department",
        rollback_disable_expectation=(
            "Do not activate limited live provider use; maintain disabled state and route "
            "all related work through REVIEW escalation."
        ),
    )

    record = build_action_department_activation_approval_record(
        projected_activation_decision=projected,
        activation_review_item_id="activation_review_follow_up_review_1",
    )

    assert record["follow_up_actions_before_broader_live_use"] == [
        "Escalate to Audit and Review Department before activation reconsideration.",
        "Resolve retained blockers and resubmit through management review.",
    ]


@pytest.mark.parametrize(
    ("case_name", "example_path", "re_review_required", "escalation_destination"),
    CONTRACT_CASES,
)
def test_build_approval_record_contract_matches_examples(
    case_name: str,
    example_path: str,
    re_review_required: bool,
    escalation_destination: str | None,
) -> None:
    expected, projected, record = _build_contract_record_from_example(
        example_path=example_path,
        re_review_required=re_review_required,
        escalation_destination=escalation_destination,
    )

    assert record["recommendation"] == expected["recommendation"]
    assert (
        record["management_review_status"]["review_outcome"]
        == expected["management_review_status"]["review_outcome"]
    )
    assert (
        record["human_approval_status"]["status"]
        == expected["human_approval_status"]["status"]
    )
    assert record["blocker_notes"] == expected["blocker_notes"]
    assert (
        record["autonomous_continuation_status"]
        == expected["autonomous_continuation_status"]
    )

    if case_name == "go":
        assert (
            record["management_review_status"]["note"]
            == expected["management_review_status"]["note"]
        )
        assert (
            record["human_approval_status"]["status"]
            == projected.human_approvals_recorded[0]["status"]
        )
        assert (
            record["follow_up_actions_before_broader_live_use"]
            == expected["follow_up_actions_before_broader_live_use"]
        )
        assert "re-review" not in " ".join(
            record["follow_up_actions_before_broader_live_use"]
        ).lower()
        assert "Escalate to" not in record["management_review_status"]["note"]

    if case_name == "pause":
        assert "escalation_destination" not in record
        assert (
            record["rollback_disable_expectation"]
            == expected["rollback_disable_expectation"]
        )
        assert (
            len(record["follow_up_actions_before_broader_live_use"])
            == len(expected["follow_up_actions_before_broader_live_use"])
        )
        assert "re-review" in " ".join(
            record["follow_up_actions_before_broader_live_use"]
        ).lower()
        assert "re-review" in expected["rollback_disable_expectation"].lower()

    if case_name == "review":
        assert (
            record["management_review_status"]["note"]
            == expected["management_review_status"]["note"]
        )
        assert "Audit and Review Department" in record["management_review_status"]["note"]


def _build_contract_record_from_example(
    *,
    example_path: str,
    re_review_required: bool,
    escalation_destination: str | None,
) -> tuple[dict, DryRunActivationDecision, dict]:
    expected = _load_example_json(example_path)
    projected = _make_projected_activation_decision(
        recommendation=expected["recommendation"],
        approval_status=expected["human_approval_status"]["status"],
        remaining_blockers=expected["blocker_notes"],
        re_review_required=re_review_required,
        escalation_destination=escalation_destination,
        rollback_disable_expectation=expected["rollback_disable_expectation"],
    )
    record = build_action_department_activation_approval_record(
        projected_activation_decision=projected,
        activation_review_item_id=expected["activation_review_item_id"],
        reviewer_id=expected["management_review_status"]["reviewer_id"],
        reviewer_type=expected["management_review_status"]["reviewer_type"],
        rationale=expected["rationale"],
        related_project_id=expected["related_project_id"],
        related_activation_decision_id=expected["related_activation_decision_id"],
        related_packet_id=expected["related_packet_id"],
        related_queue_item_id=expected["related_queue_item_id"],
    )
    return expected, projected, record


def _make_projected_activation_decision(
    *,
    recommendation: RecommendationValue,
    approval_status: ApprovalStatusValue,
    remaining_blockers: list[str],
    re_review_required: bool,
    escalation_destination: str | None,
    rollback_disable_expectation: str,
) -> DryRunActivationDecision:
    return DryRunActivationDecision(
        activation_target={
            "department": "action_department",
            "provider_use_mode": "limited_live_provider_use",
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
        preconditions_satisfied=["management_review_packet validated"],
        remaining_blockers=remaining_blockers,
        human_approvals_recorded=[
            {
                "checkpoint": "limited_live_provider_use_activation",
                "status": approval_status,
                "approver_id": "mgmt-sonnet",
                "approver_type": "model",
                "note": "Derived from management decision artifact in dry-run mode.",
            }
        ],
        recommendation=recommendation,
        autonomous_continuation_status="not_approved",
        autonomous_continuation_note=(
            "Autonomous continuation remains not approved unless explicitly approved "
            "through the required governance process."
        ),
        rollback_disable_expectation=rollback_disable_expectation,
        escalation_destination=escalation_destination,
        re_review_required=re_review_required,
    )


def _load_example_json(relative_path: str) -> dict:
    return json.loads((_ROOT / relative_path).read_text(encoding="utf-8"))
