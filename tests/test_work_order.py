from app.services.continuation import ContinuationDecision, ContinuationRisk, HardGateTrigger
from app.services.triage import (
    EscalationReason,
    RoutingDepartment,
    TriageContext,
    TriageResult,
    triage_task,
)
from app.services.work_order import build_work_order_draft


def test_build_work_order_draft_for_go_implementation_flow() -> None:
    triage = triage_task(
        TriageContext(
            changed_areas={"internal_refactor"},
            task_in_active_phase=True,
            verification_passed=True,
            ambiguous_scope=False,
        )
    )

    draft = build_work_order_draft(
        triage,
        work_order_id="wo_go",
        project_id="proj_1",
        objective="Apply a local code cleanup.",
    )

    assert draft.assigned_department == RoutingDepartment.IMPLEMENTATION
    assert draft.governance.decision_outcome == ContinuationDecision.GO
    assert draft.governance.risk_level == ContinuationRisk.MEDIUM
    assert draft.governance.management_review_required is False
    assert "Proceed with the smallest implementation change" in draft.next_action_suggestion


def test_build_work_order_draft_for_cross_department_requires_review() -> None:
    triage = triage_task(
        TriageContext(
            changed_areas={"cross_department"},
            task_in_active_phase=True,
            verification_passed=True,
            ambiguous_scope=False,
        )
    )

    draft = build_work_order_draft(
        triage,
        work_order_id="wo_review",
        project_id="proj_2",
        objective="Coordinate multi-department decision.",
    )

    assert draft.assigned_department == RoutingDepartment.MANAGEMENT
    assert draft.governance.decision_outcome == ContinuationDecision.REVIEW
    assert draft.governance.management_review_required is True
    assert draft.governance.escalation_reason == EscalationReason.CROSS_DEPARTMENT
    assert "Escalate to Management Department" in draft.next_action_suggestion


def test_build_work_order_draft_for_pause_keeps_progress_control_handoff() -> None:
    triage = triage_task(
        TriageContext(
            changed_areas={"internal_refactor"},
            task_in_active_phase=True,
            verification_passed=True,
            ambiguous_scope=True,
        )
    )

    draft = build_work_order_draft(
        triage,
        work_order_id="wo_pause",
        project_id="proj_3",
        objective="Implement task with unresolved ambiguity.",
    )

    assert draft.assigned_department == RoutingDepartment.PROGRESS_CONTROL
    assert draft.governance.decision_outcome == ContinuationDecision.PAUSE
    assert draft.governance.escalation_reason == EscalationReason.AMBIGUOUS_SCOPE
    assert "PAUSE and isolate blockers" in draft.next_action_suggestion


def test_work_order_payload_serializes_governance_fields() -> None:
    triage = triage_task(
        TriageContext(
            changed_areas={"approval"},
            task_in_active_phase=True,
            verification_passed=True,
            ambiguous_scope=False,
        )
    )
    draft = build_work_order_draft(
        triage,
        work_order_id="wo_payload",
        project_id="proj_4",
        objective="Attempt risky change without review.",
        verification_commands=["python -m pytest -q tests/test_triage.py"],
    )

    payload = draft.to_artifact_payload()
    governance = payload["governance"]

    assert payload["assigned_department"] == "management_department"
    assert governance["decision_outcome"] == "REVIEW"
    assert governance["risk_level"] == "high"
    assert governance["escalation_reason"] == "hard_gate_triggered"
    assert governance["management_review_required"] is True
    assert "approval_flow_change" in governance["hard_gate_triggers"]


def test_build_work_order_draft_for_go_action_flow() -> None:
    triage = triage_task(
        TriageContext(
            changed_areas={"docs"},
            task_in_active_phase=True,
            verification_passed=True,
            ambiguous_scope=False,
        )
    )

    draft = build_work_order_draft(
        triage,
        work_order_id="wo_action_go",
        project_id="proj_action",
        objective="Apply docs-only update.",
    )

    assert draft.assigned_department == RoutingDepartment.ACTION
    assert draft.governance.decision_outcome == ContinuationDecision.GO
    assert draft.governance.risk_level == ContinuationRisk.LOW
    assert draft.governance.management_review_required is False
    assert "Run low-risk Action Department support task" in draft.next_action_suggestion


def test_build_work_order_draft_preserves_metadata_and_optional_inputs() -> None:
    triage = triage_task(
        TriageContext(
            changed_areas={"internal_refactor"},
            task_in_active_phase=True,
            verification_passed=True,
            ambiguous_scope=False,
        )
    )

    draft = build_work_order_draft(
        triage,
        work_order_id="wo_meta_1",
        project_id="proj_meta_1",
        objective="Implement scoped refactor and verify.",
        title="Scoped refactor order",
        required_files=["app/services/work_order.py"],
        optional_files=["tests/test_work_order.py"],
        verification_commands=["python -m pytest -q tests/test_work_order.py"],
    )

    assert draft.work_order_id == "wo_meta_1"
    assert draft.project_id == "proj_meta_1"
    assert draft.title == "Scoped refactor order"
    assert draft.objective == "Implement scoped refactor and verify."
    assert draft.inputs.task_summary == "Implement scoped refactor and verify."
    assert draft.inputs.required_files == ["app/services/work_order.py"]
    assert draft.inputs.optional_files == ["tests/test_work_order.py"]
    assert draft.verification.commands == ["python -m pytest -q tests/test_work_order.py"]
    assert draft.verification.expected_result == "pass"
    assert draft.completion_criteria == [
        "Requested artifact exists",
        "No unrelated code change",
        "Verification passed",
    ]


def test_build_work_order_draft_snapshots_input_lists() -> None:
    triage = triage_task(
        TriageContext(
            changed_areas={"internal_refactor"},
            task_in_active_phase=True,
            verification_passed=True,
            ambiguous_scope=False,
        )
    )
    required_files = ["app/services/work_order.py"]
    optional_files = ["tests/test_work_order.py"]
    verification_commands = ["python -m pytest -q tests/test_work_order.py"]

    draft = build_work_order_draft(
        triage,
        work_order_id="wo_snapshot_1",
        project_id="proj_snapshot_1",
        objective="Snapshot caller list inputs.",
        required_files=required_files,
        optional_files=optional_files,
        verification_commands=verification_commands,
    )

    required_files.append("README.md")
    optional_files.append("docs/release_readiness.md")
    verification_commands.append("python -m ruff check app/services/work_order.py")

    assert draft.inputs.required_files == ["app/services/work_order.py"]
    assert draft.inputs.optional_files == ["tests/test_work_order.py"]
    assert draft.verification.commands == ["python -m pytest -q tests/test_work_order.py"]


def test_work_order_payload_sorts_hard_gate_triggers_and_preserves_ids() -> None:
    triage = TriageResult(
        risk_level=ContinuationRisk.HIGH,
        routing_target=RoutingDepartment.MANAGEMENT,
        escalation_reason=EscalationReason.HARD_GATE_TRIGGERED,
        escalation_likely_required=True,
        decision=ContinuationDecision.REVIEW,
        hard_gate_triggers={HardGateTrigger.POLICY_MODEL, HardGateTrigger.APPROVAL_FLOW},
    )

    draft = build_work_order_draft(
        triage,
        work_order_id="wo_sort_1",
        project_id="proj_sort_1",
        objective="Stabilize governance-sensitive flow.",
    )

    payload = draft.to_artifact_payload()

    assert payload["work_order_id"] == "wo_sort_1"
    assert payload["project_id"] == "proj_sort_1"
    assert payload["objective"] == "Stabilize governance-sensitive flow."
    assert payload["governance"]["hard_gate_triggers"] == [
        "approval_flow_change",
        "policy_model_change",
    ]


def test_build_work_order_draft_audit_review_route_requires_management_review() -> None:
    triage = TriageResult(
        risk_level=ContinuationRisk.MEDIUM,
        routing_target=RoutingDepartment.AUDIT_REVIEW,
        escalation_reason=EscalationReason.NONE,
        escalation_likely_required=False,
        decision=ContinuationDecision.GO,
        hard_gate_triggers=set(),
    )

    draft = build_work_order_draft(
        triage,
        work_order_id="wo_audit_route_1",
        project_id="proj_audit_route_1",
        objective="Route via audit review governance lane.",
    )

    assert draft.assigned_department == RoutingDepartment.AUDIT_REVIEW
    assert draft.governance.management_review_required is True
    assert (
        draft.next_action_suggestion
        == "Follow routed department instructions and keep GO/PAUSE/REVIEW governance intact."
    )
