from app.schemas.brief import IntakeResult
from app.schemas.management import CurrentBriefArtifact, ManagementReviewInput, ProposedActionDraft


def intake_result_to_current_brief_artifact(
    intake_result: IntakeResult,
    *,
    brief_id: str,
    project_id: str,
    active_phase: str = "phase_4",
    current_task: str | None = None,
    requested_scope: list[str] | None = None,
    out_of_scope: list[str] | None = None,
    proposed_action_summary: str = "Route to Progress Control for triage and management review.",
    verification_plan: list[str] | None = None,
) -> CurrentBriefArtifact:
    derived_requested_scope = (
        list(requested_scope)
        if requested_scope is not None
        else _derive_requested_scope(intake_result)
    )
    derived_out_of_scope = (
        list(out_of_scope)
        if out_of_scope is not None
        else _derive_out_of_scope(intake_result)
    )
    verification_plan_snapshot = list(verification_plan or [])

    return CurrentBriefArtifact(
        brief_id=brief_id,
        project_id=project_id,
        active_phase=active_phase,
        current_task=current_task or intake_result.brief.objective,
        requested_scope=derived_requested_scope,
        out_of_scope=derived_out_of_scope,
        proposed_action=ProposedActionDraft(
            summary=proposed_action_summary,
            verification_plan=verification_plan_snapshot,
        ),
        intake_missing_fields=list(intake_result.missing_fields),
        clarifying_questions=list(intake_result.clarifying_questions),
    )


def current_brief_to_management_review_input(
    artifact: CurrentBriefArtifact,
    *,
    reviewer_hint: str | None = None,
    related_task_id: str | None = None,
) -> ManagementReviewInput:
    readiness = "needs_clarification" if artifact.intake_missing_fields else "ready_for_planning"
    return ManagementReviewInput(
        related_project_id=artifact.project_id,
        related_brief_id=artifact.brief_id,
        active_phase=artifact.active_phase,
        current_task=artifact.current_task,
        candidate_routing_department=artifact.department_context.candidate_routing,
        risk_level=artifact.risk_snapshot.risk_level,
        hard_gate_triggered=artifact.risk_snapshot.hard_gate_triggered,
        hard_gate_triggers=list(artifact.risk_snapshot.hard_gate_triggers),
        intake_readiness=readiness,
        intake_missing_fields=list(artifact.intake_missing_fields),
        clarifying_questions=list(artifact.clarifying_questions),
        proposed_action_summary=artifact.proposed_action.summary,
        verification_plan=list(artifact.proposed_action.verification_plan),
        reviewer_hint=reviewer_hint,
        related_task_id=related_task_id,
    )


def _derive_requested_scope(intake_result: IntakeResult) -> list[str]:
    if intake_result.brief.scope:
        return [intake_result.brief.scope]
    return [intake_result.brief.objective]


def _derive_out_of_scope(intake_result: IntakeResult) -> list[str]:
    if intake_result.missing_fields:
        return ["Final approval and detailed planning until missing fields are clarified."]
    return []
