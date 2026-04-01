from app.intake.review_artifacts import (
    current_brief_to_management_review_input,
    intake_result_to_current_brief_artifact,
)
from app.intake.service import IntakeAgent


def test_intake_result_to_current_brief_artifact_maps_core_fields() -> None:
    agent = IntakeAgent()
    result = agent.build_brief(
        "Title: Intake Bridge\n"
        "Scope: intake conversion layer\n"
        "Constraints: python, no-deps\n"
        "Success Criteria: typed output, tests pass\n"
        "Deadline: 2026-05-01"
    )

    artifact = intake_result_to_current_brief_artifact(
        result,
        brief_id="brief_x",
        project_id="project_x",
    )

    assert artifact.brief_id == "brief_x"
    assert artifact.project_id == "project_x"
    assert artifact.requested_scope == ["intake conversion layer"]
    assert artifact.department_context.origin_department == "intake_department"
    assert artifact.department_context.candidate_routing == "progress_control_department"
    assert artifact.risk_snapshot.hard_gate_triggered is False


def test_management_review_input_marks_readiness_needs_clarification_when_missing_fields() -> None:
    agent = IntakeAgent()
    result = agent.build_brief("Build something useful.")

    artifact = intake_result_to_current_brief_artifact(
        result,
        brief_id="brief_need_clarify",
        project_id="project_need_clarify",
    )
    review_input = current_brief_to_management_review_input(
        artifact,
        reviewer_hint="management-review",
    )

    assert review_input.intake_readiness == "needs_clarification"
    assert review_input.intake_missing_fields
    assert review_input.candidate_routing_department == "progress_control_department"
    assert review_input.reviewer_hint == "management-review"


def test_management_review_input_ready_for_planning_when_no_missing_fields() -> None:
    agent = IntakeAgent()
    result = agent.build_brief(
        "Title: Complete Brief\n"
        "Scope: core workflow only\n"
        "Constraints: python\n"
        "Success Criteria: tests pass\n"
        "Deadline: 2026-06-01"
    )
    artifact = intake_result_to_current_brief_artifact(
        result,
        brief_id="brief_ready",
        project_id="project_ready",
        verification_plan=["python -m pytest -q tests/test_intake.py"],
    )
    review_input = current_brief_to_management_review_input(artifact)

    assert review_input.intake_readiness == "ready_for_planning"
    assert review_input.intake_missing_fields == []
    assert review_input.proposed_action_summary.startswith("Route to Progress Control")
    assert review_input.verification_plan == ["python -m pytest -q tests/test_intake.py"]


def test_intake_result_to_current_brief_artifact_explicit_empty_scope_overrides_are_respected(
) -> None:
    agent = IntakeAgent()
    result = agent.build_brief("Build something useful.")

    artifact = intake_result_to_current_brief_artifact(
        result,
        brief_id="brief_empty_scope",
        project_id="project_empty_scope",
        requested_scope=[],
        out_of_scope=[],
    )

    assert artifact.requested_scope == []
    assert artifact.out_of_scope == []
