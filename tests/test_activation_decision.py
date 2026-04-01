import json
from pathlib import Path

import pytest

from app.schemas import ManagementDecisionRecord, ManagementReviewPacket, ReviewQueueItem
from app.services.activation_decision import derive_dry_run_activation_decision

_ROOT = Path(__file__).resolve().parents[1]


def test_derive_dry_run_activation_decision_go_path() -> None:
    packet, queue_item, decision = _load_management_examples()
    packet = packet.model_copy(
        update={
            "risk_level": "low",
            "hard_gate_status": False,
            "hard_gate_triggers": [],
            "escalation_reasons": [],
            "recommendation": "GO",
            "required_review": False,
        }
    )
    queue_item = queue_item.model_copy(
        update={
            "risk_level": "low",
            "hard_gate_status": False,
            "hard_gate_triggers": [],
            "escalation_reason": None,
            "escalation_reasons": [],
            "recommendation": "GO",
        }
    )
    decision = decision.model_copy(
        update={
            "decision": "GO",
            "rationale": "Low-risk and no unresolved blockers.",
            "follow_up_notes": [],
        }
    )

    activation_decision = derive_dry_run_activation_decision(
        management_review_packet=packet,
        review_queue_item=queue_item,
        management_decision=decision,
    )

    assert activation_decision.recommendation == "GO"
    assert activation_decision.remaining_blockers == []
    assert activation_decision.re_review_required is False
    assert activation_decision.escalation_destination is None
    assert activation_decision.autonomous_continuation_status == "not_approved"


def test_derive_dry_run_activation_decision_pause_path_preserves_blockers() -> None:
    packet, queue_item, decision = _load_management_examples()
    packet = packet.model_copy(
        update={
            "recommendation": "PAUSE",
            "required_review": True,
            "hard_gate_status": True,
            "hard_gate_triggers": ["rollback_evidence_missing"],
            "escalation_reasons": ["hard_gate_triggered"],
        }
    )
    queue_item = queue_item.model_copy(
        update={
            "recommendation": "PAUSE",
            "hard_gate_status": True,
            "hard_gate_triggers": ["rollback_evidence_missing"],
            "escalation_reason": "hard_gate_triggered",
            "escalation_reasons": ["hard_gate_triggered"],
        }
    )
    decision = decision.model_copy(
        update={
            "decision": "PAUSE",
            "rationale": "Pause until rollback evidence is complete.",
        }
    )

    activation_decision = derive_dry_run_activation_decision(
        management_review_packet=packet,
        review_queue_item=queue_item,
        management_decision=decision,
    )

    assert activation_decision.recommendation == "PAUSE"
    assert activation_decision.remaining_blockers == [
        "rollback_evidence_missing",
        "hard_gate_triggered",
    ]
    assert activation_decision.re_review_required is True
    assert "re-review is completed" in activation_decision.rollback_disable_expectation
    assert activation_decision.autonomous_continuation_status == "not_approved"


def test_derive_dry_run_activation_decision_review_path_has_escalation_destination() -> None:
    packet, queue_item, decision = _load_management_examples()

    activation_decision = derive_dry_run_activation_decision(
        management_review_packet=packet,
        review_queue_item=queue_item,
        management_decision=decision,
    )

    assert activation_decision.recommendation == "REVIEW"
    assert activation_decision.re_review_required is True
    assert activation_decision.escalation_destination == "Audit and Review Department"
    assert activation_decision.remaining_blockers != []
    assert (
        "route all related work through REVIEW"
        in activation_decision.rollback_disable_expectation
    )
    assert activation_decision.autonomous_continuation_status == "not_approved"


def test_derive_dry_run_activation_decision_go_with_blockers_downgrades_to_pause() -> None:
    packet, queue_item, decision = _load_management_examples()
    packet = packet.model_copy(update={"required_review": False})
    queue_item = queue_item.model_copy(
        update={
            "hard_gate_status": True,
            "hard_gate_triggers": ["hard_gate_triggered", "policy_model_change"],
            "escalation_reasons": ["hard_gate_triggered", "cross_department_routing"],
            "escalation_reason": "hard_gate_triggered",
        }
    )
    decision = decision.model_copy(update={"decision": "GO"})

    activation_decision = derive_dry_run_activation_decision(
        management_review_packet=packet,
        review_queue_item=queue_item,
        management_decision=decision,
    )

    assert activation_decision.recommendation == "PAUSE"
    assert activation_decision.remaining_blockers == [
        "hard_gate_triggered",
        "policy_model_change",
        "cross_department_routing",
    ]
    assert activation_decision.re_review_required is True
    assert activation_decision.human_approvals_recorded[0]["status"] == "pending"


def test_derive_dry_run_activation_decision_go_with_required_review_downgrades_to_pause() -> None:
    packet, queue_item, decision = _load_management_examples()
    packet = packet.model_copy(
        update={
            "required_review": True,
            "hard_gate_status": False,
            "hard_gate_triggers": [],
            "escalation_reasons": [],
        }
    )
    queue_item = queue_item.model_copy(
        update={
            "hard_gate_status": False,
            "hard_gate_triggers": [],
            "escalation_reason": None,
            "escalation_reasons": [],
        }
    )
    decision = decision.model_copy(update={"decision": "GO"})

    activation_decision = derive_dry_run_activation_decision(
        management_review_packet=packet,
        review_queue_item=queue_item,
        management_decision=decision,
    )

    assert activation_decision.recommendation == "PAUSE"
    assert activation_decision.remaining_blockers == []
    assert activation_decision.re_review_required is True
    assert "no unresolved blockers detected" not in activation_decision.preconditions_satisfied


def test_derive_dry_run_activation_decision_hard_gate_status_adds_fallback_blocker() -> None:
    packet, queue_item, decision = _load_management_examples()
    packet = packet.model_copy(update={"required_review": False})
    queue_item = queue_item.model_copy(
        update={
            "hard_gate_status": True,
            "hard_gate_triggers": [],
            "escalation_reason": None,
            "escalation_reasons": [],
        }
    )
    decision = decision.model_copy(update={"decision": "PAUSE"})

    activation_decision = derive_dry_run_activation_decision(
        management_review_packet=packet,
        review_queue_item=queue_item,
        management_decision=decision,
    )

    assert activation_decision.remaining_blockers == ["hard_gate_active"]


def test_derive_dry_run_activation_decision_ignores_empty_blocker_entries() -> None:
    packet, queue_item, decision = _load_management_examples()
    packet = packet.model_copy(update={"required_review": False})
    queue_item = queue_item.model_copy(
        update={
            "hard_gate_status": True,
            "hard_gate_triggers": ["", " approval_flow_change ", ""],
            "escalation_reason": " ",
            "escalation_reasons": ["", " hard_gate_triggered ", ""],
        }
    )
    decision = decision.model_copy(update={"decision": "PAUSE"})

    activation_decision = derive_dry_run_activation_decision(
        management_review_packet=packet,
        review_queue_item=queue_item,
        management_decision=decision,
    )

    assert activation_decision.remaining_blockers == [
        "approval_flow_change",
        "hard_gate_triggered",
    ]


def test_derive_dry_run_activation_decision_preserves_reviewer_metadata() -> None:
    packet, queue_item, decision = _load_management_examples()
    decision = decision.model_copy(
        update={
            "reviewer_id": "reviewer_custom_1",
            "reviewer_type": "management_delegate",
        }
    )

    activation_decision = derive_dry_run_activation_decision(
        management_review_packet=packet,
        review_queue_item=queue_item,
        management_decision=decision,
    )

    approval = activation_decision.human_approvals_recorded[0]
    assert approval["checkpoint"] == "limited_live_provider_use_activation"
    assert approval["approver_id"] == "reviewer_custom_1"
    assert approval["approver_type"] == "management_delegate"


@pytest.mark.parametrize(
    (
        "packet_updates",
        "queue_updates",
        "decision_updates",
        "expected_artifact_paths",
        "expected_remaining_blockers",
        "expected_re_review_required",
        "expected_escalation_destination",
    ),
    [
        (
            {
                "risk_level": "low",
                "hard_gate_status": False,
                "hard_gate_triggers": [],
                "escalation_reasons": [],
                "recommendation": "GO",
                "required_review": False,
            },
            {
                "risk_level": "low",
                "hard_gate_status": False,
                "hard_gate_triggers": [],
                "escalation_reason": None,
                "escalation_reasons": [],
                "recommendation": "GO",
            },
            {
                "decision": "GO",
                "rationale": "Low-risk and no unresolved blockers.",
                "follow_up_notes": [],
            },
            [
                "docs/examples/action_department_activation_decision_example.json",
                "docs/examples/action_department_activation_approval_record_example.json",
            ],
            [],
            False,
            None,
        ),
        (
            {
                "recommendation": "PAUSE",
                "required_review": True,
                "hard_gate_status": True,
                "hard_gate_triggers": ["rollback_evidence_missing"],
                "escalation_reasons": ["hard_gate_triggered"],
            },
            {
                "recommendation": "PAUSE",
                "hard_gate_status": True,
                "hard_gate_triggers": ["rollback_evidence_missing"],
                "escalation_reason": "hard_gate_triggered",
                "escalation_reasons": ["hard_gate_triggered"],
            },
            {
                "decision": "PAUSE",
                "rationale": "Pause until rollback evidence is complete.",
            },
            ["docs/examples/action_department_activation_approval_record_pause_example.json"],
            ["rollback_evidence_missing", "hard_gate_triggered"],
            True,
            None,
        ),
        (
            {},
            {},
            {},
            ["docs/examples/action_department_activation_approval_record_review_example.json"],
            ["approval_flow_change", "hard_gate_triggered", "cross_department_routing"],
            True,
            "Audit and Review Department",
        ),
    ],
)
def test_derive_dry_run_activation_decision_contract_matches_examples(
    packet_updates: dict,
    queue_updates: dict,
    decision_updates: dict,
    expected_artifact_paths: list[str],
    expected_remaining_blockers: list[str],
    expected_re_review_required: bool,
    expected_escalation_destination: str | None,
) -> None:
    packet, queue_item, decision = _load_management_examples()
    packet = packet.model_copy(update=packet_updates)
    queue_item = queue_item.model_copy(update=queue_updates)
    decision = decision.model_copy(update=decision_updates)

    activation_decision = derive_dry_run_activation_decision(
        management_review_packet=packet,
        review_queue_item=queue_item,
        management_decision=decision,
    )

    assert activation_decision.remaining_blockers == expected_remaining_blockers
    assert activation_decision.re_review_required is expected_re_review_required
    assert activation_decision.escalation_destination == expected_escalation_destination

    first_approval = activation_decision.human_approvals_recorded[0]
    for artifact_path in expected_artifact_paths:
        expected_payload = _load_example_json(artifact_path)
        assert activation_decision.recommendation == expected_payload["recommendation"]
        assert (
            activation_decision.autonomous_continuation_status
            == expected_payload["autonomous_continuation_status"]
        )
        assert first_approval["status"] == _extract_expected_status(expected_payload)


def _load_management_examples() -> tuple[
    ManagementReviewPacket, ReviewQueueItem, ManagementDecisionRecord
]:
    packet_payload = json.loads(
        (_ROOT / "docs/examples/management_review_packet_example.json").read_text(
            encoding="utf-8"
        )
    )
    queue_payload = json.loads(
        (_ROOT / "docs/examples/review_queue_item_example.json").read_text(encoding="utf-8")
    )
    decision_payload = json.loads(
        (_ROOT / "docs/examples/management_decision_example.json").read_text(
            encoding="utf-8"
        )
    )
    return (
        ManagementReviewPacket.model_validate(packet_payload),
        ReviewQueueItem.model_validate(queue_payload),
        ManagementDecisionRecord.model_validate(decision_payload),
    )


def _load_example_json(relative_path: str) -> dict:
    return json.loads((_ROOT / relative_path).read_text(encoding="utf-8"))


def _extract_expected_status(payload: dict) -> str:
    if "human_approvals_recorded" in payload:
        return payload["human_approvals_recorded"][0]["status"]
    return payload["human_approval_status"]["status"]
