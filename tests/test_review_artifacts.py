from app.intake.review_artifacts import (
    current_brief_to_management_review_input,
    intake_result_to_current_brief_artifact,
)
from app.intake.service import IntakeAgent


def test_intake_result_to_current_brief_artifact_derives_scope_and_out_of_scope() -> None:
    agent = IntakeAgent()
    intake_result = agent.build_brief("Build something useful.")

    artifact = intake_result_to_current_brief_artifact(
        intake_result,
        brief_id="brief_derived_1",
        project_id="project_derived_1",
    )

    assert artifact.brief_id == "brief_derived_1"
    assert artifact.project_id == "project_derived_1"
    assert artifact.current_task == intake_result.brief.objective
    assert artifact.requested_scope == [intake_result.brief.objective]
    assert artifact.out_of_scope == [
        "Final approval and detailed planning until missing fields are clarified."
    ]
    assert artifact.intake_missing_fields == intake_result.missing_fields
    assert artifact.clarifying_questions == intake_result.clarifying_questions


def test_intake_result_to_current_brief_artifact_respects_explicit_overrides() -> None:
    agent = IntakeAgent()
    intake_result = agent.build_brief("Build something useful.")

    artifact = intake_result_to_current_brief_artifact(
        intake_result,
        brief_id="brief_override_1",
        project_id="project_override_1",
        active_phase="phase_custom",
        current_task="Custom current task.",
        requested_scope=["explicit_scope"],
        out_of_scope=["explicit_out_of_scope"],
        proposed_action_summary="Custom proposed action summary.",
        verification_plan=["python -m pytest -q tests/test_review_artifacts.py"],
    )

    assert artifact.active_phase == "phase_custom"
    assert artifact.current_task == "Custom current task."
    assert artifact.requested_scope == ["explicit_scope"]
    assert artifact.out_of_scope == ["explicit_out_of_scope"]
    assert artifact.proposed_action.summary == "Custom proposed action summary."
    assert artifact.proposed_action.verification_plan == [
        "python -m pytest -q tests/test_review_artifacts.py"
    ]


def test_intake_result_to_current_brief_artifact_preserves_explicit_empty_scope_overrides() -> None:
    agent = IntakeAgent()
    intake_result = agent.build_brief("Build something useful.")

    artifact = intake_result_to_current_brief_artifact(
        intake_result,
        brief_id="brief_override_empty_1",
        project_id="project_override_empty_1",
        requested_scope=[],
        out_of_scope=[],
    )

    assert artifact.requested_scope == []
    assert artifact.out_of_scope == []


def test_intake_result_to_current_brief_artifact_snapshots_verification_plan() -> None:
    agent = IntakeAgent()
    intake_result = agent.build_brief("Build something useful.")
    verification_plan = ["python -m pytest -q tests/test_review_artifacts.py"]

    artifact = intake_result_to_current_brief_artifact(
        intake_result,
        brief_id="brief_verify_snapshot_1",
        project_id="project_verify_snapshot_1",
        verification_plan=verification_plan,
    )
    verification_plan.append("python -m ruff check app/intake/review_artifacts.py")

    assert artifact.proposed_action.verification_plan == [
        "python -m pytest -q tests/test_review_artifacts.py"
    ]


def test_current_brief_to_management_review_input_preserves_fields_and_metadata() -> None:
    agent = IntakeAgent()
    intake_result = agent.build_brief("Build something useful.")
    artifact = intake_result_to_current_brief_artifact(
        intake_result,
        brief_id="brief_input_1",
        project_id="project_input_1",
        current_task="Current task from artifact.",
        proposed_action_summary="Escalate to management review.",
        verification_plan=["python -m pytest -q tests/test_management_review_summary.py"],
    )
    artifact = artifact.model_copy(
        update={
            "department_context": artifact.department_context.model_copy(
                update={"candidate_routing": "management_department"}
            ),
            "risk_snapshot": artifact.risk_snapshot.model_copy(
                update={
                    "risk_level": "high",
                    "hard_gate_triggered": True,
                    "hard_gate_triggers": ["approval_flow_change"],
                }
            ),
            "intake_missing_fields": ["scope"],
            "clarifying_questions": ["What is the in-scope boundary?"],
        }
    )

    review_input = current_brief_to_management_review_input(
        artifact,
        reviewer_hint="review-lead",
        related_task_id="task_123",
    )

    assert review_input.related_project_id == artifact.project_id
    assert review_input.related_brief_id == artifact.brief_id
    assert review_input.active_phase == artifact.active_phase
    assert review_input.current_task == artifact.current_task
    assert review_input.candidate_routing_department == "management_department"
    assert review_input.risk_level == "high"
    assert review_input.hard_gate_triggered is True
    assert review_input.hard_gate_triggers == ["approval_flow_change"]
    assert review_input.intake_readiness == "needs_clarification"
    assert review_input.intake_missing_fields == ["scope"]
    assert review_input.clarifying_questions == ["What is the in-scope boundary?"]
    assert review_input.proposed_action_summary == "Escalate to management review."
    assert review_input.verification_plan == [
        "python -m pytest -q tests/test_management_review_summary.py"
    ]
    assert review_input.reviewer_hint == "review-lead"
    assert review_input.related_task_id == "task_123"


def test_current_brief_to_management_review_input_copies_mutable_lists() -> None:
    agent = IntakeAgent()
    intake_result = agent.build_brief("Build something useful.")
    artifact = intake_result_to_current_brief_artifact(
        intake_result,
        brief_id="brief_copy_1",
        project_id="project_copy_1",
    )

    review_input = current_brief_to_management_review_input(artifact)
    review_input.intake_missing_fields.append("new_missing")
    review_input.clarifying_questions.append("new_question")
    review_input.hard_gate_triggers.append("new_gate")
    review_input.verification_plan.append("new_verification")

    assert artifact.intake_missing_fields == intake_result.missing_fields
    assert artifact.clarifying_questions == intake_result.clarifying_questions
    assert artifact.risk_snapshot.hard_gate_triggers == []
    assert artifact.proposed_action.verification_plan == []
