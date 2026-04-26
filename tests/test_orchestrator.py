import pytest

from app.llm.base import LLMClient
from app.llm.mock_client import MockLLMClient
from app.llm.openclaw_client import OpenClawLLMClient
from app.llm.registry import DepartmentRegistry
from app.orchestrator.service import PMOrchestrator
from app.schemas.brief import ProjectBrief
from app.schemas.project import (
    ActorContext,
    ActorRole,
    ApprovalActionType,
    ApprovalRequest,
    ApprovalStatus,
    Department,
    HistoryEventType,
    ProjectPolicy,
    ProjectPolicyActionRule,
    ProjectStatus,
    RevisionResumeMode,
    TaskStatus,
)


def _brief() -> ProjectBrief:
    return ProjectBrief(
        title="Scaffold project",
        objective="Create a minimal AI work system scaffold",
        scope="backend core only",
        constraints=["python", "fastapi"],
        success_criteria=["health endpoint", "tests pass"],
        deadline="2026-04-30",
        stakeholders=["platform team"],
        assumptions=["MVP first"],
        raw_request="Create a minimal AI work system scaffold",
    )


def _approver() -> ActorContext:
    return ActorContext(actor_id="approver-1", actor_role=ActorRole.APPROVER)


def _admin() -> ActorContext:
    return ActorContext(actor_id="admin-1", actor_role=ActorRole.ADMIN)


def _operator() -> ActorContext:
    return ActorContext(actor_id="operator-1", actor_role=ActorRole.OPERATOR)


def _viewer() -> ActorContext:
    return ActorContext(actor_id="viewer-1", actor_role=ActorRole.VIEWER)


def _task_by_id(result, task_id: str):
    return next(task for task in result.record.tasks if task.id == task_id)


def test_orchestrator_completes_with_mock_provider() -> None:
    orchestrator = PMOrchestrator()
    result = orchestrator.run(_brief(), trend_provider_name="mock")

    assert result.summary.status == ProjectStatus.COMPLETED
    assert result.summary.completed_tasks == 5
    assert result.summary.artifact_count >= 4
    assert any(a.artifact_type == "trend_analysis" for a in result.record.artifacts)


def test_orchestrator_waits_for_external_provider_approval() -> None:
    orchestrator = PMOrchestrator()
    result = orchestrator.run(_brief(), trend_provider_name="gemini")

    assert result.summary.status == ProjectStatus.WAITING_APPROVAL
    assert any(task.status == TaskStatus.WAITING_APPROVAL for task in result.record.tasks)


def test_orchestrator_waits_for_approval_when_using_gemini_alias_provider_name() -> None:
    orchestrator = PMOrchestrator()
    result = orchestrator.run(_brief(), trend_provider_name="gemini-flash-lite-latest")

    assert result.summary.status == ProjectStatus.WAITING_APPROVAL
    assert any(task.status == TaskStatus.WAITING_APPROVAL for task in result.record.tasks)


def test_orchestrator_unknown_provider_falls_back_to_mock_when_non_strict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TREND_PROVIDER_STRICT", "false")
    orchestrator = PMOrchestrator()

    result = orchestrator.run(_brief(), trend_provider_name="unknown-provider")

    assert result.summary.status == ProjectStatus.COMPLETED


def test_orchestrator_unknown_provider_raises_when_strict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TREND_PROVIDER_STRICT", "true")
    orchestrator = PMOrchestrator()

    with pytest.raises(ValueError, match="Unsupported trend provider"):
        orchestrator.run(_brief(), trend_provider_name="unknown-provider")


def test_orchestrator_unknown_provider_raises_when_strict_env_is_malformed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TREND_PROVIDER_STRICT", "not-a-bool")
    orchestrator = PMOrchestrator()

    with pytest.raises(ValueError, match="Unsupported trend provider"):
        orchestrator.run(_brief(), trend_provider_name="unknown-provider")


def test_orchestrator_whitespace_provider_name_treated_as_mock_when_strict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TREND_PROVIDER_STRICT", "true")
    orchestrator = PMOrchestrator()

    result = orchestrator.run(_brief(), trend_provider_name="   ")

    assert result.summary.status == ProjectStatus.COMPLETED


def test_orchestrator_mock_provider_still_runs_when_strict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TREND_PROVIDER_STRICT", "true")
    orchestrator = PMOrchestrator()

    result = orchestrator.run(_brief(), trend_provider_name="mock")

    assert result.summary.status == ProjectStatus.COMPLETED


def test_resume_from_approval_completes_project() -> None:
    orchestrator = PMOrchestrator()
    waiting = orchestrator.run(_brief(), trend_provider_name="gemini")

    resumed = orchestrator.resume_from_approval(
        project_id=waiting.record.project.id,
        approved_actions=["external_api_send"],
        actor=_approver(),
        note="approved external request",
        trend_provider_name="gemini",
    )

    assert resumed.summary.status == ProjectStatus.COMPLETED
    assert any(
        event.event_type == HistoryEventType.APPROVAL_APPROVED for event in resumed.record.events
    )


def test_resume_from_approval_repeated_after_completion_is_idempotent() -> None:
    orchestrator = PMOrchestrator()
    waiting = orchestrator.run(_brief(), trend_provider_name="gemini")
    project_id = waiting.record.project.id

    first = orchestrator.resume_from_approval(
        project_id=project_id,
        approved_actions=["external_api_send"],
        actor=_approver(),
        trend_provider_name="gemini",
    )
    assert first.summary.status == ProjectStatus.COMPLETED

    second = orchestrator.resume_from_approval(
        project_id=project_id,
        approved_actions=["external_api_send"],
        actor=_approver(),
        trend_provider_name="gemini",
    )

    assert second.summary.status == ProjectStatus.COMPLETED
    assert second.summary.next_steps == [
        "Project already completed; approval resume request treated as idempotent."
    ]
    audit = orchestrator.get_project_audit(project_id)
    approval_approved_events = [
        event for event in audit.events if event.event_type == HistoryEventType.APPROVAL_APPROVED
    ]
    assert len(approval_approved_events) == 1


def test_resume_from_approval_trims_note_for_approval_and_audit_events() -> None:
    orchestrator = PMOrchestrator()
    waiting = orchestrator.run(_brief(), trend_provider_name="gemini")
    project_id = waiting.record.project.id

    resumed = orchestrator.resume_from_approval(
        project_id=project_id,
        approved_actions=["external_api_send"],
        actor=_approver(),
        note="  approved external request  ",
        trend_provider_name="gemini",
    )
    assert resumed.summary.status == ProjectStatus.COMPLETED

    audit = orchestrator.get_project_audit(project_id)
    approved_request = next(
        approval
        for approval in audit.approvals
        if approval.action_type == ApprovalActionType.EXTERNAL_API_SEND
    )
    assert approved_request.decision_note == "approved external request"

    approval_event = next(
        event for event in audit.events if event.event_type == HistoryEventType.APPROVAL_APPROVED
    )
    resume_event = next(
        event
        for event in audit.events
        if event.event_type == HistoryEventType.RESUME_TRIGGERED
        and event.metadata.get("mode") == "approval_resume"
    )
    assert approval_event.reason == "approved external request"
    assert resume_event.reason == "approved external request"


def test_resume_from_approval_rejects_invalid_state() -> None:
    orchestrator = PMOrchestrator()
    completed = orchestrator.run(_brief(), trend_provider_name="mock")

    with pytest.raises(ValueError, match="current: completed"):
        orchestrator.resume_from_approval(
            project_id=completed.record.project.id,
            approved_actions=["external_api_send"],
            actor=_approver(),
        )


def test_resume_from_approval_invalid_state_takes_precedence_over_invalid_action_value() -> None:
    orchestrator = PMOrchestrator()
    waiting = orchestrator.run(_brief(), trend_provider_name="gemini")
    rejected = orchestrator.reject_approval(
        project_id=waiting.record.project.id,
        rejected_actions=["external_api_send"],
        actor=_approver(),
        reason="reject before invalid resume",
    )

    with pytest.raises(ValueError, match="current: revision_requested"):
        orchestrator.resume_from_approval(
            project_id=rejected.record.project.id,
            approved_actions=["not_real_action"],
            actor=_approver(),
        )


def test_resume_from_approval_completed_rejected_action_returns_specific_conflict_detail() -> None:
    orchestrator = PMOrchestrator()
    waiting = orchestrator.run(_brief(), trend_provider_name="gemini")
    project_id = waiting.record.project.id

    rejected = orchestrator.reject_approval(
        project_id=project_id,
        rejected_actions=["external_api_send"],
        actor=_approver(),
        reason="reject before completed retry",
    )
    assert rejected.summary.status == ProjectStatus.REVISION_REQUESTED

    completed = orchestrator.resume_from_revision(
        project_id=project_id,
        resume_mode=RevisionResumeMode.REBUILDING,
        actor=_operator(),
        reason="complete after rejection",
        trend_provider_name="mock",
    )
    assert completed.summary.status == ProjectStatus.COMPLETED

    with pytest.raises(ValueError, match="Action\\(s\\) already rejected: external_api_send"):
        orchestrator.resume_from_approval(
            project_id=project_id,
            approved_actions=["external_api_send"],
            actor=_approver(),
        )


def test_resume_from_approval_rejects_unauthorized_role() -> None:
    orchestrator = PMOrchestrator()
    waiting = orchestrator.run(_brief(), trend_provider_name="gemini")

    with pytest.raises(PermissionError):
        orchestrator.resume_from_approval(
            project_id=waiting.record.project.id,
            approved_actions=["external_api_send"],
            actor=_viewer(),
            trend_provider_name="gemini",
        )

    audit = orchestrator.get_project_audit(waiting.record.project.id)
    assert any(event.event_type == HistoryEventType.AUTHORIZATION_FAILED for event in audit.events)


def test_resume_from_approval_viewer_denied_even_when_runtime_allowlist_includes_viewer() -> None:
    orchestrator = PMOrchestrator()
    waiting = orchestrator.run(_brief(), trend_provider_name="gemini")

    with pytest.raises(PermissionError):
        orchestrator.resume_from_approval(
            project_id=waiting.record.project.id,
            approved_actions=["external_api_send"],
            actor=_viewer(),
            trend_provider_name="gemini",
            project_allowed_actor_ids_by_action={"external_api_send": ["viewer-1"]},
        )

    audit = orchestrator.get_project_audit(waiting.record.project.id)
    assert any(event.event_type == HistoryEventType.AUTHORIZATION_FAILED for event in audit.events)
    assert not any(
        event.event_type == HistoryEventType.POLICY_OVERRIDE_APPLIED for event in audit.events
    )


def test_resume_from_approval_requires_all_pending_actions() -> None:
    orchestrator = PMOrchestrator()
    waiting = orchestrator.run(_brief(), trend_provider_name="gemini")

    with pytest.raises(ValueError):
        orchestrator.resume_from_approval(
            project_id=waiting.record.project.id,
            approved_actions=[],
            actor=_approver(),
        )


def test_reject_approval_moves_to_revision_requested() -> None:
    orchestrator = PMOrchestrator()
    waiting = orchestrator.run(_brief(), trend_provider_name="gemini")

    rejected = orchestrator.reject_approval(
        project_id=waiting.record.project.id,
        rejected_actions=["external_api_send"],
        actor=_approver(),
        reason="External access denied",
    )

    assert rejected.summary.status == ProjectStatus.REVISION_REQUESTED
    assert any(
        event.event_type == HistoryEventType.APPROVAL_REJECTED
        for event in rejected.record.events
    )


def test_reject_approval_auto_closes_other_pending_actions_when_subset_is_rejected() -> None:
    orchestrator = PMOrchestrator()
    waiting = orchestrator.run(_brief(), trend_provider_name="gemini")
    project_id = waiting.record.project.id
    record = orchestrator.repository.get(project_id)
    assert record is not None
    record.approvals.append(
        ApprovalRequest(
            id="approval-bulk-modify-reject-subset",
            action_type=ApprovalActionType.BULK_MODIFY,
            status=ApprovalStatus.PENDING,
            reason="Bulk modify requires explicit approval.",
            requested_by="system",
        )
    )
    orchestrator.repository.save(record)

    rejected = orchestrator.reject_approval(
        project_id=project_id,
        rejected_actions=["external_api_send"],
        actor=_approver(),
        reason="Reject one action and close remainder",
    )
    assert rejected.summary.status == ProjectStatus.REVISION_REQUESTED

    audit = orchestrator.get_project_audit(project_id)
    approval_status_by_action = {
        approval.action_type: approval.status for approval in audit.approvals
    }
    assert (
        approval_status_by_action[ApprovalActionType.EXTERNAL_API_SEND]
        == ApprovalStatus.REJECTED
    )
    assert approval_status_by_action[ApprovalActionType.BULK_MODIFY] == ApprovalStatus.REJECTED

    rejected_events = [
        event for event in audit.events if event.event_type == HistoryEventType.APPROVAL_REJECTED
    ]
    assert len(rejected_events) == 2
    assert any(event.metadata.get("auto_closed") is True for event in rejected_events)


def test_reject_approval_subset_requires_authorization_for_all_pending_actions() -> None:
    orchestrator = PMOrchestrator()
    waiting = orchestrator.run(_brief(), trend_provider_name="gemini")
    project_id = waiting.record.project.id
    record = orchestrator.repository.get(project_id)
    assert record is not None
    record.approvals.append(
        ApprovalRequest(
            id="approval-production-admin-only-reject-subset",
            action_type=ApprovalActionType.PRODUCTION_AFFECTING_CHANGE,
            status=ApprovalStatus.PENDING,
            reason="Production change requires admin approval.",
            requested_by="system",
        )
    )
    orchestrator.repository.save(record)

    with pytest.raises(PermissionError):
        orchestrator.reject_approval(
            project_id=project_id,
            rejected_actions=["external_api_send"],
            actor=_approver(),
            reason="Reject subset without admin role.",
        )

    audit = orchestrator.get_project_audit(project_id)
    assert audit.status == ProjectStatus.WAITING_APPROVAL
    assert any(
        event.event_type == HistoryEventType.AUTHORIZATION_FAILED
        and event.metadata.get("action_type") == "production_affecting_change"
        for event in audit.events
    )


def test_reject_approval_repeated_after_revision_requested_is_idempotent() -> None:
    orchestrator = PMOrchestrator()
    waiting = orchestrator.run(_brief(), trend_provider_name="gemini")
    project_id = waiting.record.project.id

    first = orchestrator.reject_approval(
        project_id=project_id,
        rejected_actions=["external_api_send"],
        actor=_approver(),
        reason="External access denied",
    )
    assert first.summary.status == ProjectStatus.REVISION_REQUESTED

    second = orchestrator.reject_approval(
        project_id=project_id,
        rejected_actions=["external_api_send"],
        actor=_approver(),
        reason="External access denied",
    )

    assert second.summary.status == ProjectStatus.REVISION_REQUESTED
    audit = orchestrator.get_project_audit(project_id)
    approval_rejected_events = [
        event for event in audit.events if event.event_type == HistoryEventType.APPROVAL_REJECTED
    ]
    assert len(approval_rejected_events) == 1


def test_reject_approval_revision_requested_non_rejected_action_returns_specific_conflict_detail(
) -> None:
    orchestrator = PMOrchestrator()
    waiting = orchestrator.run(_brief(), trend_provider_name="gemini")
    project_id = waiting.record.project.id
    record = orchestrator.repository.get(project_id)
    assert record is not None
    record.approvals.append(
        ApprovalRequest(
            id="approval-bulk-modify-revision-non-rejected-conflict",
            action_type=ApprovalActionType.BULK_MODIFY,
            status=ApprovalStatus.PENDING,
            reason="Bulk modify requires explicit approval.",
            requested_by="system",
        )
    )
    orchestrator.repository.save(record)

    partial = orchestrator.resume_from_approval(
        project_id=project_id,
        approved_actions=["external_api_send"],
        actor=_approver(),
        trend_provider_name="gemini",
    )
    assert partial.summary.status == ProjectStatus.WAITING_APPROVAL

    rejected = orchestrator.reject_approval(
        project_id=project_id,
        rejected_actions=["bulk_modify"],
        actor=_approver(),
        reason="reject remaining pending action",
    )
    assert rejected.summary.status == ProjectStatus.REVISION_REQUESTED

    with pytest.raises(
        ValueError,
        match="Cannot reject non-pending action\\(s\\): external_api_send",
    ):
        orchestrator.reject_approval(
            project_id=project_id,
            rejected_actions=["external_api_send"],
            actor=_approver(),
            reason="reject already-approved action should not map to revision idempotency",
        )


def test_reject_approval_trims_reason_and_note_in_recorded_artifacts() -> None:
    orchestrator = PMOrchestrator()
    waiting = orchestrator.run(_brief(), trend_provider_name="gemini")
    project_id = waiting.record.project.id

    rejected = orchestrator.reject_approval(
        project_id=project_id,
        rejected_actions=["external_api_send"],
        actor=_approver(),
        reason="  External access denied  ",
        note="  escalated to revision lane  ",
    )
    assert rejected.summary.status == ProjectStatus.REVISION_REQUESTED

    review_task = _task_by_id(rejected, "task-trend")
    assert review_task.note == "External access denied"

    audit = orchestrator.get_project_audit(project_id)
    rejected_request = next(
        approval
        for approval in audit.approvals
        if approval.action_type == ApprovalActionType.EXTERNAL_API_SEND
    )
    assert rejected_request.decision_note == "External access denied escalated to revision lane"

    reject_event = next(
        event for event in audit.events if event.event_type == HistoryEventType.APPROVAL_REJECTED
    )
    assert reject_event.reason == "External access denied"
    assert reject_event.metadata.get("note") == "escalated to revision lane"


def test_reject_approval_requires_reason() -> None:
    orchestrator = PMOrchestrator()
    waiting = orchestrator.run(_brief(), trend_provider_name="gemini")

    with pytest.raises(ValueError):
        orchestrator.reject_approval(
            project_id=waiting.record.project.id,
            rejected_actions=["external_api_send"],
            actor=_approver(),
            reason="",
        )


def test_reject_approval_invalid_state_takes_precedence_over_invalid_action_value() -> None:
    orchestrator = PMOrchestrator()
    completed = orchestrator.run(_brief(), trend_provider_name="mock")

    with pytest.raises(ValueError, match="current: completed"):
        orchestrator.reject_approval(
            project_id=completed.record.project.id,
            rejected_actions=["not_real_action"],
            actor=_approver(),
            reason="invalid state first",
        )


def test_reject_approval_rejects_unauthorized_role() -> None:
    orchestrator = PMOrchestrator()
    waiting = orchestrator.run(_brief(), trend_provider_name="gemini")

    with pytest.raises(PermissionError):
        orchestrator.reject_approval(
            project_id=waiting.record.project.id,
            rejected_actions=["external_api_send"],
            actor=_viewer(),
            reason="viewer cannot reject approvals",
        )

    audit = orchestrator.get_project_audit(waiting.record.project.id)
    assert any(event.event_type == HistoryEventType.AUTHORIZATION_FAILED for event in audit.events)


def test_reject_approval_runtime_override_denies_and_records_override_event() -> None:
    orchestrator = PMOrchestrator()
    waiting = orchestrator.run(_brief(), trend_provider_name="gemini")

    with pytest.raises(PermissionError):
        orchestrator.reject_approval(
            project_id=waiting.record.project.id,
            rejected_actions=["external_api_send"],
            actor=_approver(),
            reason="runtime override denies this actor",
            project_allowed_actor_ids_by_action={"external_api_send": ["another-approver"]},
        )

    audit = orchestrator.get_project_audit(waiting.record.project.id)
    assert any(
        event.event_type == HistoryEventType.POLICY_OVERRIDE_APPLIED for event in audit.events
    )


def test_resume_from_approval_runtime_empty_allowlist_denies_and_records_override_event() -> None:
    orchestrator = PMOrchestrator()
    waiting = orchestrator.run(_brief(), trend_provider_name="gemini")

    with pytest.raises(PermissionError):
        orchestrator.resume_from_approval(
            project_id=waiting.record.project.id,
            approved_actions=["external_api_send"],
            actor=_approver(),
            trend_provider_name="gemini",
            project_allowed_actor_ids_by_action={"external_api_send": []},
        )

    audit = orchestrator.get_project_audit(waiting.record.project.id)
    assert any(
        event.event_type == HistoryEventType.POLICY_OVERRIDE_APPLIED for event in audit.events
    )
    assert any(
        event.event_type == HistoryEventType.AUTHORIZATION_FAILED
        and event.metadata.get("policy_source") == "project_runtime_override"
        for event in audit.events
    )


def test_resume_from_approval_runtime_override_key_normalization_applies() -> None:
    orchestrator = PMOrchestrator()
    waiting = orchestrator.run(_brief(), trend_provider_name="gemini")

    with pytest.raises(PermissionError):
        orchestrator.resume_from_approval(
            project_id=waiting.record.project.id,
            approved_actions=["external_api_send"],
            actor=_approver(),
            trend_provider_name="gemini",
            project_allowed_actor_ids_by_action={"  EXTERNAL_API_SEND  ": ["another-approver"]},
        )

    audit = orchestrator.get_project_audit(waiting.record.project.id)
    assert any(
        event.event_type == HistoryEventType.AUTHORIZATION_FAILED
        and event.metadata.get("policy_source") == "project_runtime_override"
        for event in audit.events
    )


def test_resume_from_approval_authorizes_multiple_actions_in_deterministic_order() -> None:
    orchestrator = PMOrchestrator()
    waiting = orchestrator.run(_brief(), trend_provider_name="gemini")
    project_id = waiting.record.project.id
    record = orchestrator.repository.get(project_id)
    assert record is not None
    record.approvals.append(
        ApprovalRequest(
            id="approval-bulk-modify",
            action_type=ApprovalActionType.BULK_MODIFY,
            status=ApprovalStatus.PENDING,
            reason="Bulk modify requires explicit approval.",
            requested_by="system",
        )
    )
    orchestrator.repository.save(record)

    resumed = orchestrator.resume_from_approval(
        project_id=project_id,
        approved_actions=["external_api_send", "bulk_modify"],
        actor=_approver(),
        trend_provider_name="gemini",
    )

    assert resumed.summary.status == ProjectStatus.COMPLETED
    audit = orchestrator.get_project_audit(project_id)
    authorization_granted_events = [
        event
        for event in audit.events
        if event.event_type == HistoryEventType.AUTHORIZATION_GRANTED
    ]
    assert len(authorization_granted_events) == 2
    assert [
        event.metadata.get("action_type") for event in authorization_granted_events
    ] == ["bulk_modify", "external_api_send"]


def test_resume_from_approval_supports_partial_approval_until_all_pending_actions_are_approved(
) -> None:
    orchestrator = PMOrchestrator()
    waiting = orchestrator.run(_brief(), trend_provider_name="gemini")
    project_id = waiting.record.project.id
    record = orchestrator.repository.get(project_id)
    assert record is not None
    record.approvals.append(
        ApprovalRequest(
            id="approval-bulk-modify-partial",
            action_type=ApprovalActionType.BULK_MODIFY,
            status=ApprovalStatus.PENDING,
            reason="Bulk modify requires explicit approval.",
            requested_by="system",
        )
    )
    orchestrator.repository.save(record)

    partial = orchestrator.resume_from_approval(
        project_id=project_id,
        approved_actions=["external_api_send"],
        actor=_approver(),
        trend_provider_name="gemini",
    )
    assert partial.summary.status == ProjectStatus.WAITING_APPROVAL
    assert partial.summary.next_steps[0] == "Approve remaining action(s): bulk_modify."

    completed = orchestrator.resume_from_approval(
        project_id=project_id,
        approved_actions=["bulk_modify"],
        actor=_approver(),
        trend_provider_name="gemini",
    )
    assert completed.summary.status == ProjectStatus.COMPLETED

    audit = orchestrator.get_project_audit(project_id)
    partial_resume_events = [
        event
        for event in audit.events
        if event.event_type == HistoryEventType.RESUME_TRIGGERED
        and event.metadata.get("mode") == "approval_resume_partial"
    ]
    assert len(partial_resume_events) == 1


def test_resume_from_approval_repeated_partial_call_is_idempotent_without_duplicate_partial_event(
) -> None:
    orchestrator = PMOrchestrator()
    waiting = orchestrator.run(_brief(), trend_provider_name="gemini")
    project_id = waiting.record.project.id
    record = orchestrator.repository.get(project_id)
    assert record is not None
    record.approvals.append(
        ApprovalRequest(
            id="approval-bulk-modify-partial-repeat",
            action_type=ApprovalActionType.BULK_MODIFY,
            status=ApprovalStatus.PENDING,
            reason="Bulk modify requires explicit approval.",
            requested_by="system",
        )
    )
    orchestrator.repository.save(record)

    first_partial = orchestrator.resume_from_approval(
        project_id=project_id,
        approved_actions=["external_api_send"],
        actor=_approver(),
        trend_provider_name="gemini",
    )
    assert first_partial.summary.status == ProjectStatus.WAITING_APPROVAL

    second_partial = orchestrator.resume_from_approval(
        project_id=project_id,
        approved_actions=["external_api_send"],
        actor=_approver(),
        trend_provider_name="gemini",
    )
    assert second_partial.summary.status == ProjectStatus.WAITING_APPROVAL

    audit = orchestrator.get_project_audit(project_id)
    partial_resume_events = [
        event
        for event in audit.events
        if event.event_type == HistoryEventType.RESUME_TRIGGERED
        and event.metadata.get("mode") == "approval_resume_partial"
    ]
    approval_approved_events = [
        event for event in audit.events if event.event_type == HistoryEventType.APPROVAL_APPROVED
    ]
    assert len(partial_resume_events) == 1
    assert len(approval_approved_events) == 1

    approval_requested_events = [
        event for event in audit.events if event.event_type == HistoryEventType.APPROVAL_REQUESTED
    ]
    requested_action_types = [
        event.metadata.get("action_type")
        for event in approval_requested_events
    ]
    assert len(requested_action_types) == len(set(requested_action_types))

    approval_action_types = [approval.action_type.value for approval in audit.approvals]
    assert len(approval_action_types) == len(set(approval_action_types))

def test_resume_from_approval_partial_next_step_includes_all_remaining_actions() -> None:
    orchestrator = PMOrchestrator()
    waiting = orchestrator.run(_brief(), trend_provider_name="gemini")
    project_id = waiting.record.project.id
    record = orchestrator.repository.get(project_id)
    assert record is not None
    record.approvals.extend(
        [
            ApprovalRequest(
                id="approval-bulk-modify-partial-next-steps",
                action_type=ApprovalActionType.BULK_MODIFY,
                status=ApprovalStatus.PENDING,
                reason="Bulk modify requires explicit approval.",
                requested_by="system",
            ),
            ApprovalRequest(
                id="approval-destructive-change-partial-next-steps",
                action_type=ApprovalActionType.DESTRUCTIVE_CHANGE,
                status=ApprovalStatus.PENDING,
                reason="Destructive change requires explicit approval.",
                requested_by="system",
            ),
        ]
    )
    orchestrator.repository.save(record)

    partial = orchestrator.resume_from_approval(
        project_id=project_id,
        approved_actions=["external_api_send"],
        actor=_approver(),
        trend_provider_name="gemini",
    )
    assert partial.summary.status == ProjectStatus.WAITING_APPROVAL
    assert partial.summary.next_steps[0] == (
        "Approve remaining action(s): bulk_modify, destructive_change."
    )
    assert partial.summary.next_steps[1] == (
        'Call approval resume API with `approved_actions=["bulk_modify", "destructive_change"]`.'
    )


def test_revision_replanning_moves_to_ready_for_planning() -> None:
    orchestrator = PMOrchestrator()
    revision = orchestrator.run(
        _brief(),
        trend_provider_name="mock",
        simulate_review_failure=True,
    )

    resumed = orchestrator.resume_from_revision(
        project_id=revision.record.project.id,
        resume_mode=RevisionResumeMode.REPLANNING,
        actor=_operator(),
        reason="Adjust task decomposition",
    )

    assert resumed.summary.status == ProjectStatus.READY_FOR_PLANNING


def test_resume_from_revision_replanning_repeated_in_ready_state_is_idempotent() -> None:
    orchestrator = PMOrchestrator()
    revision = orchestrator.run(
        _brief(),
        trend_provider_name="mock",
        simulate_review_failure=True,
    )

    first = orchestrator.resume_from_revision(
        project_id=revision.record.project.id,
        resume_mode=RevisionResumeMode.REPLANNING,
        actor=_operator(),
        reason="Need replan",
    )
    assert first.summary.status == ProjectStatus.READY_FOR_PLANNING

    second = orchestrator.resume_from_revision(
        project_id=revision.record.project.id,
        resume_mode=RevisionResumeMode.REPLANNING,
        actor=_operator(),
        reason="Need replan",
    )
    assert second.summary.status == ProjectStatus.READY_FOR_PLANNING
    assert second.summary.next_steps == [
        "Call replanning start API to begin execution from ready_for_planning."
    ]

    audit = orchestrator.get_project_audit(revision.record.project.id)
    replanning_resume_events = [
        event
        for event in audit.events
        if event.event_type == HistoryEventType.RESUME_TRIGGERED
        and event.metadata.get("mode") == "replanning"
    ]
    assert len(replanning_resume_events) == 1


def test_start_replanning_from_ready_for_planning() -> None:
    orchestrator = PMOrchestrator()
    revision = orchestrator.run(
        _brief(),
        trend_provider_name="mock",
        simulate_review_failure=True,
    )
    replanning_ready = orchestrator.resume_from_revision(
        project_id=revision.record.project.id,
        resume_mode=RevisionResumeMode.REPLANNING,
        actor=_operator(),
        reason="Need replan",
    )

    restarted = orchestrator.start_replanning(
        project_id=replanning_ready.record.project.id,
        actor=_operator(),
        note="Start replanning execution",
        trend_provider_name="mock",
    )

    assert restarted.summary.status == ProjectStatus.COMPLETED
    assert any(
        event.event_type == HistoryEventType.REPLANNING_STARTED
        for event in restarted.record.events
    )


def test_start_replanning_repeated_after_completion_is_idempotent() -> None:
    orchestrator = PMOrchestrator()
    revision = orchestrator.run(
        _brief(),
        trend_provider_name="mock",
        simulate_review_failure=True,
    )
    replanning_ready = orchestrator.resume_from_revision(
        project_id=revision.record.project.id,
        resume_mode=RevisionResumeMode.REPLANNING,
        actor=_operator(),
        reason="Need replan",
    )
    first = orchestrator.start_replanning(
        project_id=replanning_ready.record.project.id,
        actor=_operator(),
        note="Start replanning execution",
        trend_provider_name="mock",
    )
    assert first.summary.status == ProjectStatus.COMPLETED

    second = orchestrator.start_replanning(
        project_id=replanning_ready.record.project.id,
        actor=_operator(),
        note="retry start",
        trend_provider_name="mock",
    )
    assert second.summary.status == ProjectStatus.COMPLETED
    assert second.summary.next_steps == [
        "Project already completed; replanning start request treated as idempotent."
    ]

    audit = orchestrator.get_project_audit(replanning_ready.record.project.id)
    replanning_start_events = [
        event for event in audit.events if event.event_type == HistoryEventType.REPLANNING_STARTED
    ]
    assert len(replanning_start_events) == 1


def test_start_replanning_rejects_invalid_state() -> None:
    orchestrator = PMOrchestrator()
    completed = orchestrator.run(_brief(), trend_provider_name="mock")

    with pytest.raises(ValueError):
        orchestrator.start_replanning(
            project_id=completed.record.project.id,
            actor=_operator(),
            note="invalid state call",
        )


def test_revision_rebuilding_resets_only_build_downstream_notes() -> None:
    orchestrator = PMOrchestrator()
    revision = orchestrator.run(
        _brief(),
        trend_provider_name="mock",
        simulate_review_failure=True,
    )

    rebuilt = orchestrator.resume_from_revision(
        project_id=revision.record.project.id,
        resume_mode=RevisionResumeMode.REBUILDING,
        actor=_operator(),
        reason="Rebuild only after failed review",
    )

    assert rebuilt.summary.status == ProjectStatus.COMPLETED
    assert _task_by_id(rebuilt, "task-design").note == ""
    assert _task_by_id(rebuilt, "task-build").note == "Rebuild only after failed review"
    assert _task_by_id(rebuilt, "task-trend").note == "Rebuild only after failed review"
    assert _task_by_id(rebuilt, "task-review").note == "Rebuild only after failed review"


def test_resume_from_revision_rebuilding_repeated_after_completion_is_idempotent() -> None:
    orchestrator = PMOrchestrator()
    revision = orchestrator.run(
        _brief(),
        trend_provider_name="mock",
        simulate_review_failure=True,
    )

    first = orchestrator.resume_from_revision(
        project_id=revision.record.project.id,
        resume_mode=RevisionResumeMode.REBUILDING,
        actor=_operator(),
        reason="Rebuild only after failed review",
    )
    assert first.summary.status == ProjectStatus.COMPLETED

    second = orchestrator.resume_from_revision(
        project_id=revision.record.project.id,
        resume_mode=RevisionResumeMode.REBUILDING,
        actor=_operator(),
        reason="Rebuild only after failed review",
    )
    assert second.summary.status == ProjectStatus.COMPLETED
    assert second.summary.next_steps == [
        "Project already completed; revision resume request treated as idempotent."
    ]

    audit = orchestrator.get_project_audit(revision.record.project.id)
    rebuilding_resume_events = [
        event
        for event in audit.events
        if event.event_type == HistoryEventType.RESUME_TRIGGERED
        and event.metadata.get("mode") == "rebuilding"
    ]
    assert len(rebuilding_resume_events) == 1


def test_revision_rereview_resets_only_review_note() -> None:
    orchestrator = PMOrchestrator()
    revision = orchestrator.run(
        _brief(),
        trend_provider_name="mock",
        simulate_review_failure=True,
    )

    rereviewed = orchestrator.resume_from_revision(
        project_id=revision.record.project.id,
        resume_mode=RevisionResumeMode.REREVIEW,
        actor=_operator(),
        reason="Re-run review with fixes applied",
    )

    assert rereviewed.summary.status == ProjectStatus.COMPLETED
    assert _task_by_id(rereviewed, "task-design").note == ""
    assert _task_by_id(rereviewed, "task-build").note == ""
    assert _task_by_id(rereviewed, "task-trend").note == ""
    assert _task_by_id(rereviewed, "task-review").note == "Re-run review with fixes applied"


def test_resume_from_revision_rereview_repeated_after_completion_is_idempotent() -> None:
    orchestrator = PMOrchestrator()
    revision = orchestrator.run(
        _brief(),
        trend_provider_name="mock",
        simulate_review_failure=True,
    )

    first = orchestrator.resume_from_revision(
        project_id=revision.record.project.id,
        resume_mode=RevisionResumeMode.REREVIEW,
        actor=_operator(),
        reason="Re-run review with fixes applied",
    )
    assert first.summary.status == ProjectStatus.COMPLETED

    second = orchestrator.resume_from_revision(
        project_id=revision.record.project.id,
        resume_mode=RevisionResumeMode.REREVIEW,
        actor=_operator(),
        reason="Re-run review with fixes applied",
    )
    assert second.summary.status == ProjectStatus.COMPLETED
    assert second.summary.next_steps == [
        "Project already completed; revision resume request treated as idempotent."
    ]

    audit = orchestrator.get_project_audit(revision.record.project.id)
    rereview_resume_events = [
        event
        for event in audit.events
        if event.event_type == HistoryEventType.RESUME_TRIGGERED
        and event.metadata.get("mode") == "rereview"
    ]
    assert len(rereview_resume_events) == 1


def test_start_replanning_without_downstream_reset_preserves_task_notes() -> None:
    orchestrator = PMOrchestrator()
    revision = orchestrator.run(
        _brief(),
        trend_provider_name="mock",
        simulate_review_failure=True,
    )
    replanning_ready = orchestrator.resume_from_revision(
        project_id=revision.record.project.id,
        resume_mode=RevisionResumeMode.REPLANNING,
        actor=_operator(),
        reason="prepare for manual replanning",
    )

    restarted = orchestrator.start_replanning(
        project_id=replanning_ready.record.project.id,
        actor=_operator(),
        note="restart without reset",
        trend_provider_name="mock",
        reset_downstream_tasks=False,
    )

    assert restarted.summary.status == ProjectStatus.COMPLETED
    assert _task_by_id(restarted, "task-design").note == "prepare for manual replanning"
    assert _task_by_id(restarted, "task-build").note == "prepare for manual replanning"
    assert _task_by_id(restarted, "task-trend").note == "prepare for manual replanning"
    assert _task_by_id(restarted, "task-review").note == "prepare for manual replanning"
    assert any(
        event.event_type == HistoryEventType.REPLANNING_STARTED
        and event.metadata.get("reset_downstream_tasks") is False
        for event in restarted.record.events
    )


def test_role_rule_production_change_admin_only() -> None:
    orchestrator = PMOrchestrator()
    waiting = orchestrator.run(_brief(), trend_provider_name="gemini")

    with pytest.raises(PermissionError):
        orchestrator.resume_from_approval(
            project_id=waiting.record.project.id,
            approved_actions=["external_api_send"],
            actor=_operator(),
            trend_provider_name="gemini",
            project_allowed_actor_ids_by_action={"external_api_send": ["another-id"]},
        )

    # sanity check: admin can pass project-level allow-list when actor id matches
    approved = orchestrator.resume_from_approval(
        project_id=waiting.record.project.id,
        approved_actions=["external_api_send"],
        actor=_admin(),
        trend_provider_name="gemini",
        project_allowed_actor_ids_by_action={"external_api_send": ["admin-1"]},
    )
    assert approved.summary.status == ProjectStatus.COMPLETED


def test_project_policy_strict_mode_requires_explicit_action_policy() -> None:
    orchestrator = PMOrchestrator()
    policy = ProjectPolicy(strict_mode=True, project_owner_actor_id="owner-1", action_rules={})
    waiting = orchestrator.run(
        _brief(),
        project_policy=policy,
        trend_provider_name="gemini",
    )

    with pytest.raises(PermissionError):
        orchestrator.resume_from_approval(
            project_id=waiting.record.project.id,
            approved_actions=["external_api_send"],
            actor=_approver(),
            trend_provider_name="gemini",
        )


def test_project_policy_override_allows_specific_actor() -> None:
    orchestrator = PMOrchestrator()
    policy = ProjectPolicy(
        strict_mode=True,
        project_owner_actor_id="owner-1",
        action_rules={
            "external_api_send": ProjectPolicyActionRule(
                allowed_roles=[ActorRole.APPROVER],
                allowed_actor_ids=["approver-1"],
            )
        },
    )
    waiting = orchestrator.run(
        _brief(),
        project_policy=policy,
        trend_provider_name="gemini",
    )

    approved = orchestrator.resume_from_approval(
        project_id=waiting.record.project.id,
        approved_actions=["external_api_send"],
        actor=_approver(),
        trend_provider_name="gemini",
    )
    assert approved.summary.status == ProjectStatus.COMPLETED


def test_audit_contains_structured_history() -> None:
    orchestrator = PMOrchestrator()
    result = orchestrator.run(_brief(), trend_provider_name="mock")

    audit = orchestrator.get_project_audit(result.record.project.id)
    assert audit.project_id == result.record.project.id
    assert audit.events
    first_event = audit.events[0]
    assert first_event.event_type == HistoryEventType.STATE_TRANSITION
    assert first_event.actor_role is not None


def test_audit_contains_internal_stage_events_for_all_department_pipelines() -> None:
    orchestrator = PMOrchestrator()
    result = orchestrator.run(_brief(), trend_provider_name="mock")

    audit = orchestrator.get_project_audit(result.record.project.id)
    stage_events = [
        event
        for event in audit.events
        if event.event_type == HistoryEventType.DEPARTMENT_STAGE_EXECUTED
    ]
    assert stage_events

    research_events = [
        event for event in stage_events if event.metadata.get("department") == "research"
    ]
    design_events = [
        event for event in stage_events if event.metadata.get("department") == "design"
    ]
    build_events = [event for event in stage_events if event.metadata.get("department") == "build"]
    review_events = [
        event for event in stage_events if event.metadata.get("department") == "review"
    ]

    assert [event.metadata.get("stage_name") for event in research_events] == [
        "ScopeFraming",
        "EvidenceDraft",
        "RiskChallenge",
    ]
    assert [event.metadata.get("sequence") for event in research_events] == [1, 2, 3]
    assert [event.metadata.get("parent_stage_name") for event in research_events] == [
        "",
        "ScopeFraming",
        "EvidenceDraft",
    ]

    assert [event.metadata.get("stage_name") for event in design_events] == [
        "ArchitectureDraft",
        "ConstraintCheck",
        "DecisionFinalizer",
    ]
    assert [event.metadata.get("sequence") for event in design_events] == [1, 2, 3]
    assert [event.metadata.get("parent_stage_name") for event in design_events] == [
        "",
        "ArchitectureDraft",
        "ConstraintCheck",
    ]

    assert [event.metadata.get("stage_name") for event in build_events] == [
        "Architect",
        "Coder",
        "Tester",
    ]
    assert [event.metadata.get("sequence") for event in build_events] == [1, 2, 3]
    assert [event.metadata.get("parent_stage_name") for event in build_events] == [
        "",
        "Architect",
        "Coder",
    ]

    assert [event.metadata.get("stage_name") for event in review_events] == [
        "InitialReview",
        "CounterCheck",
        "FinalJudgment",
    ]
    assert [event.metadata.get("sequence") for event in review_events] == [1, 2, 3]
    assert [event.metadata.get("parent_stage_name") for event in review_events] == [
        "",
        "InitialReview",
        "CounterCheck",
    ]

    for event in research_events + design_events + build_events + review_events:
        assert event.metadata.get("effective_provider") == "mock"
        assert event.metadata.get("effective_model") == "mock"
        assert event.metadata.get("llm_response_mode") in {"fixed", "schema_aware_default"}
        assert isinstance(event.metadata.get("fallback_used"), bool)
        assert isinstance(event.metadata.get("stage_success"), bool)
        if event.metadata.get("stage_success") is False:
            assert event.metadata.get("stage_failure_reason", "") != ""

    summary = audit.department_stage_summary
    assert summary
    assert len(summary) == 12
    totals = audit.department_stage_totals
    assert totals.total_stage_executions == 12
    assert totals.total_successes + totals.total_failures == totals.total_stage_executions
    assert sorted(totals.departments_covered) == ["build", "design", "research", "review"]
    assert totals.total_llm_transport_fallbacks >= 0
    assert isinstance(totals.llm_endpoints_observed, list)
    architect = next(
        item
        for item in summary
        if item.department == "build" and item.stage_name == "Architect"
    )
    assert architect.sequence == 1
    assert architect.execution_count == 1
    assert architect.success_count + architect.failure_count == architect.execution_count
    assert 0 <= architect.fallback_count <= architect.execution_count
    assert "mock" in architect.effective_providers
    assert "mock" in architect.effective_models
    assert "schema_aware_default" in architect.llm_response_modes


def test_audit_stage_events_include_failure_reason_when_llm_stage_fails() -> None:
    class _FailingLLM(LLMClient):
        def complete(self, system: str, user: str) -> str:
            raise RuntimeError("forced-failure")

    registry = DepartmentRegistry(
        clients={
            Department.RESEARCH: _FailingLLM(),
            Department.DESIGN: MockLLMClient(),
            Department.BUILD: MockLLMClient(),
            Department.REVIEW: MockLLMClient(),
        }
    )
    orchestrator = PMOrchestrator(department_registry=registry)

    result = orchestrator.run(_brief(), trend_provider_name="mock")
    assert result.summary.status == ProjectStatus.COMPLETED

    audit = orchestrator.get_project_audit(result.record.project.id)
    research_stage_events = [
        event
        for event in audit.events
        if event.event_type == HistoryEventType.DEPARTMENT_STAGE_EXECUTED
        and event.metadata.get("department") == "research"
    ]
    assert len(research_stage_events) == 3
    assert all(event.metadata.get("stage_success") is False for event in research_stage_events)
    assert all(event.metadata.get("fallback_used") is True for event in research_stage_events)
    assert all(
        event.metadata.get("stage_failure_reason") == "llm_exception:RuntimeError"
        for event in research_stage_events
    )

    summary = [
        item for item in audit.department_stage_summary if item.department == "research"
    ]
    assert len(summary) == 3
    totals = audit.department_stage_totals
    assert totals.total_stage_executions == 12
    assert totals.total_failures >= 3
    assert totals.has_failures is True
    assert totals.has_fallbacks is True
    assert all(item.execution_count == 1 for item in summary)
    assert all(item.success_count == 0 for item in summary)
    assert all(item.failure_count == 1 for item in summary)
    assert all(item.fallback_count == 1 for item in summary)
    assert all("llm_exception:RuntimeError" in item.failure_reasons for item in summary)


def test_audit_stage_events_capture_openclaw_upstream_rejection_metadata() -> None:
    class _RejectionLLM(OpenClawLLMClient):
        def __init__(self) -> None:
            super().__init__(agent_id="default", base_url="http://127.0.0.1:18789/v1")

        def complete(self, system: str, user: str) -> str:
            self._last_call_metadata = {
                "gateway_endpoint": "chat/completions",
                "gateway_status_code": 200,
                "gateway_fallback_used": False,
                "gateway_error_kind": "upstream_rejection",
                "gateway_content_kind": "upstream_rejection",
                "gateway_backend_override": "openai-codex/gpt-5.2",
                "gateway_upstream_rejection": True,
                "gateway_upstream_provider": "anthropic",
                "gateway_upstream_rejection_reason": "credit_balance_too_low",
                "response_mode": "plain_text_upstream_rejection",
            }
            return (
                "LLM request rejected: Your credit balance is too low to access "
                "the Anthropic API. Please go to Plans & Billing to upgrade or purchase credits."
            )

    registry = DepartmentRegistry(
        clients={
            Department.RESEARCH: _RejectionLLM(),
            Department.DESIGN: MockLLMClient(),
            Department.BUILD: MockLLMClient(),
            Department.REVIEW: MockLLMClient(),
        }
    )
    orchestrator = PMOrchestrator(department_registry=registry)

    result = orchestrator.run(_brief(), trend_provider_name="mock")
    assert result.summary.status == ProjectStatus.IN_PROGRESS
    assert result.summary.artifact_count == 0
    assert (
        "Resolve the OpenClaw upstream provider credit/policy blocker."
        in result.summary.next_steps
    )
    assert _task_by_id(result, "task-research").status == TaskStatus.BLOCKED
    assert _task_by_id(result, "task-design").status == TaskStatus.PENDING

    audit = orchestrator.get_project_audit(result.record.project.id)
    research_stage_events = [
        event
        for event in audit.events
        if event.event_type == HistoryEventType.DEPARTMENT_STAGE_EXECUTED
        and event.metadata.get("department") == "research"
    ]
    assert len(research_stage_events) == 3
    assert all(
        event.metadata.get("stage_failure_reason")
        == "upstream_rejection:anthropic:credit_balance_too_low"
        for event in research_stage_events
    )
    assert all(
        event.metadata.get("llm_error_kind") == "upstream_rejection"
        for event in research_stage_events
    )
    assert all(
        event.metadata.get("llm_content_kind") == "upstream_rejection"
        for event in research_stage_events
    )
    assert all(
        event.metadata.get("llm_backend_override") == "openai-codex/gpt-5.2"
        for event in research_stage_events
    )
    assert all(
        event.metadata.get("llm_upstream_provider") == "anthropic"
        for event in research_stage_events
    )
    assert all(
        event.metadata.get("llm_upstream_rejection_reason") == "credit_balance_too_low"
        for event in research_stage_events
    )

    summary = [
        item for item in audit.department_stage_summary if item.department == "research"
    ]
    assert len(summary) == 3
    assert all(
        "upstream_rejection:anthropic:credit_balance_too_low" in item.failure_reasons
        for item in summary
    )
    assert all("upstream_rejection" in item.llm_error_kinds for item in summary)
    assert all("plain_text_upstream_rejection" in item.llm_response_modes for item in summary)


def test_openclaw_all_stage_non_json_response_blocks_instead_of_persisting_fallback_artifact(
) -> None:
    class _PlainTextOpenClawLLM(OpenClawLLMClient):
        def __init__(self) -> None:
            super().__init__(agent_id="default", base_url="http://127.0.0.1:18789/v1")

        def complete(self, system: str, user: str) -> str:
            self._last_call_metadata = {
                "gateway_endpoint": "chat/completions",
                "gateway_status_code": 200,
                "gateway_fallback_used": False,
                "gateway_content_kind": "plain_text",
                "response_mode": "plain_text",
            }
            return "this is not json"

    registry = DepartmentRegistry(
        clients={
            Department.RESEARCH: _PlainTextOpenClawLLM(),
            Department.DESIGN: MockLLMClient(),
            Department.BUILD: MockLLMClient(),
            Department.REVIEW: MockLLMClient(),
        }
    )
    orchestrator = PMOrchestrator(department_registry=registry)

    result = orchestrator.run(_brief(), trend_provider_name="mock")

    assert result.summary.status == ProjectStatus.IN_PROGRESS
    assert result.summary.artifact_count == 0
    assert _task_by_id(result, "task-research").status == TaskStatus.BLOCKED
    assert (
        "Restore valid JSON output from the OpenClaw department stages before retrying."
        in result.summary.next_steps
    )

    audit = orchestrator.get_project_audit(result.record.project.id)
    research_stage_events = [
        event
        for event in audit.events
        if event.event_type == HistoryEventType.DEPARTMENT_STAGE_EXECUTED
        and event.metadata.get("department") == "research"
    ]
    assert len(research_stage_events) == 3
    assert all(
        event.metadata.get("stage_failure_reason") == "non_json_response"
        for event in research_stage_events
    )


def test_review_receives_live_run_evidence_artifact() -> None:
    class _CaptureReviewLLM(MockLLMClient):
        def __init__(self) -> None:
            super().__init__()
            self.prompts: list[str] = []

        def complete(self, system: str, user: str) -> str:
            self.prompts.append(user)
            return super().complete(system, user)

    review_llm = _CaptureReviewLLM()
    registry = DepartmentRegistry(
        clients={
            Department.RESEARCH: MockLLMClient(),
            Department.DESIGN: MockLLMClient(),
            Department.BUILD: MockLLMClient(),
            Department.REVIEW: review_llm,
        }
    )
    orchestrator = PMOrchestrator(department_registry=registry)

    result = orchestrator.run(_brief(), trend_provider_name="mock")

    assert result.summary.status == ProjectStatus.COMPLETED
    assert review_llm.prompts
    review_prompt = review_llm.prompts[0]
    assert "live_run_evidence" in review_prompt
    assert "\"stage_totals\"" in review_prompt
    assert "\"artifact_count_before_review\"" in review_prompt
    assert "\"department_stage_executed_events\"" in review_prompt
    assert "\"post_run_artifact_map\"" in review_prompt


def test_non_blocking_changes_requested_is_normalized_to_approved() -> None:
    class _StructuredPipelineLLM(LLMClient):
        def complete(self, system: str, user: str) -> str:
            lowered = system.lower()
            if any(
                marker in lowered
                for marker in ("research planner", "research analyst", "risk challenger")
            ):
                return (
                    '{"summary":"research","risks":["none"],"assumptions":["bounded"],'
                    '"research_areas":["core"]}'
                )
            if any(
                marker in lowered
                for marker in (
                    "solution architect drafting",
                    "constraint auditor",
                    "technical decision finalizer",
                )
            ):
                return (
                    '{"architecture":"arch","components":["api"],"constraints":["python"],'
                    '"technical_decisions":["typed-models"]}'
                )
            if "software architect" in lowered:
                return (
                    '{"architecture":"arch","components":["api"],"interfaces":["http"],'
                    '"risks":["low"]}'
                )
            if "senior software engineer" in lowered:
                return (
                    '{"status":"ready","scope":"backend","implementation_steps":["code"],'
                    '"estimated_effort":"small","corrections":[]}'
                )
            if "qa engineer" in lowered:
                return (
                    '{"status":"ready","scope":"backend","implementation_steps":["test"],'
                    '"estimated_effort":"small","risks":["low"],"test_strategy":["unit"]}'
                )
            return '{"verdict":"approved","findings":[],"summary":"ok"}'

    class _NonBlockingReviewLLM(LLMClient):
        def complete(self, system: str, user: str) -> str:
            return (
                '{"verdict":"changes_requested","findings":["Consider tightening wording '
                'in summary."],"summary":"Non-blocking polish only."}'
            )

    registry = DepartmentRegistry(
        clients={
            Department.RESEARCH: _StructuredPipelineLLM(),
            Department.DESIGN: _StructuredPipelineLLM(),
            Department.BUILD: _StructuredPipelineLLM(),
            Department.REVIEW: _NonBlockingReviewLLM(),
        }
    )
    orchestrator = PMOrchestrator(department_registry=registry)

    result = orchestrator.run(_brief(), trend_provider_name="mock")

    assert result.summary.status == ProjectStatus.COMPLETED
    review = result.record.reviews[-1]
    assert review.verdict == "approved"
    assert any(item.startswith("[non_blocking]") for item in review.findings)


def test_non_blocking_changes_requested_after_reject_replan_is_normalized_to_approved() -> None:
    class _StructuredPipelineLLM(LLMClient):
        def complete(self, system: str, user: str) -> str:
            lowered = system.lower()
            if any(
                marker in lowered
                for marker in ("research planner", "research analyst", "risk challenger")
            ):
                return (
                    '{"summary":"research","risks":["none"],"assumptions":["bounded"],'
                    '"research_areas":["core"]}'
                )
            if any(
                marker in lowered
                for marker in (
                    "solution architect drafting",
                    "constraint auditor",
                    "technical decision finalizer",
                )
            ):
                return (
                    '{"architecture":"arch","components":["api"],"constraints":["python"],'
                    '"technical_decisions":["typed-models"]}'
                )
            if "software architect" in lowered:
                return (
                    '{"architecture":"arch","components":["api"],"interfaces":["http"],'
                    '"risks":["low"]}'
                )
            if "senior software engineer" in lowered:
                return (
                    '{"status":"ready","scope":"backend","implementation_steps":["code"],'
                    '"estimated_effort":"small","corrections":[]}'
                )
            if "qa engineer" in lowered:
                return (
                    '{"status":"ready","scope":"backend","implementation_steps":["test"],'
                    '"estimated_effort":"small","risks":["low"],"test_strategy":["unit"]}'
                )
            return '{"verdict":"approved","findings":[],"summary":"ok"}'

    class _RejectPathNonBlockingReviewLLM(LLMClient):
        def complete(self, system: str, user: str) -> str:
            return (
                '{"verdict":"changes_requested","findings":["Blocking: Missing standalone '
                'live-path reject artifact bundle in review snapshot."],'
                '"summary":"Reject-path evidence is not bundled as standalone artifacts."}'
            )

    registry = DepartmentRegistry(
        clients={
            Department.RESEARCH: _StructuredPipelineLLM(),
            Department.DESIGN: _StructuredPipelineLLM(),
            Department.BUILD: _StructuredPipelineLLM(),
            Department.REVIEW: _RejectPathNonBlockingReviewLLM(),
        }
    )
    orchestrator = PMOrchestrator(department_registry=registry)

    waiting = orchestrator.run(_brief(), trend_provider_name="gemini-flash-lite-latest")
    assert waiting.summary.status == ProjectStatus.WAITING_APPROVAL

    rejected = orchestrator.reject_approval(
        project_id=waiting.record.project.id,
        rejected_actions=["external_api_send"],
        actor=_approver(),
        reason="Security policy",
        note="Reject for revision lane",
    )
    assert rejected.summary.status == ProjectStatus.REVISION_REQUESTED

    resumed = orchestrator.resume_from_revision(
        project_id=waiting.record.project.id,
        resume_mode=RevisionResumeMode.REPLANNING,
        actor=_operator(),
        reason="Resume replanning after rejection",
        trend_provider_name="mock",
    )
    assert resumed.summary.status == ProjectStatus.READY_FOR_PLANNING

    replanned = orchestrator.start_replanning(
        project_id=waiting.record.project.id,
        actor=_operator(),
        note="Restart replanning",
        trend_provider_name="mock",
    )

    assert replanned.summary.status == ProjectStatus.COMPLETED
    review = replanned.record.reviews[-1]
    assert review.verdict == "approved"
    assert any(item.startswith("[non_blocking]") for item in review.findings)


def test_blocking_changes_requested_keeps_revision_requested_status() -> None:
    class _StructuredPipelineLLM(LLMClient):
        def complete(self, system: str, user: str) -> str:
            lowered = system.lower()
            if any(
                marker in lowered
                for marker in ("research planner", "research analyst", "risk challenger")
            ):
                return (
                    '{"summary":"research","risks":["none"],"assumptions":["bounded"],'
                    '"research_areas":["core"]}'
                )
            if any(
                marker in lowered
                for marker in (
                    "solution architect drafting",
                    "constraint auditor",
                    "technical decision finalizer",
                )
            ):
                return (
                    '{"architecture":"arch","components":["api"],"constraints":["python"],'
                    '"technical_decisions":["typed-models"]}'
                )
            if "software architect" in lowered:
                return (
                    '{"architecture":"arch","components":["api"],"interfaces":["http"],'
                    '"risks":["low"]}'
                )
            if "senior software engineer" in lowered:
                return (
                    '{"status":"ready","scope":"backend","implementation_steps":["code"],'
                    '"estimated_effort":"small","corrections":[]}'
                )
            if "qa engineer" in lowered:
                return (
                    '{"status":"ready","scope":"backend","implementation_steps":["test"],'
                    '"estimated_effort":"small","risks":["low"],"test_strategy":["unit"]}'
                )
            return '{"verdict":"approved","findings":[],"summary":"ok"}'

    class _BlockingReviewLLM(LLMClient):
        def complete(self, system: str, user: str) -> str:
            return (
                '{"verdict":"changes_requested","findings":["Security vulnerability found '
                'in build output."],"summary":"Blocking defect."}'
            )

    registry = DepartmentRegistry(
        clients={
            Department.RESEARCH: _StructuredPipelineLLM(),
            Department.DESIGN: _StructuredPipelineLLM(),
            Department.BUILD: _StructuredPipelineLLM(),
            Department.REVIEW: _BlockingReviewLLM(),
        }
    )
    orchestrator = PMOrchestrator(department_registry=registry)

    result = orchestrator.run(_brief(), trend_provider_name="mock")

    assert result.summary.status == ProjectStatus.REVISION_REQUESTED
    assert result.record.reviews[-1].verdict == "changes_requested"


def test_coerce_actor_from_none_string_and_context() -> None:
    orchestrator = PMOrchestrator()

    from_none = orchestrator._coerce_actor(None)
    assert from_none.actor_id == "unknown"
    assert from_none.actor_role == ActorRole.OPERATOR

    from_string = orchestrator._coerce_actor("operator-x", default_role=ActorRole.APPROVER)
    assert from_string.actor_id == "operator-x"
    assert from_string.actor_role == ActorRole.APPROVER

    from_whitespace = orchestrator._coerce_actor("   ", default_role=ActorRole.OPERATOR)
    assert from_whitespace.actor_id == "unknown"
    assert from_whitespace.actor_role == ActorRole.OPERATOR

    context = _viewer()
    from_context = orchestrator._coerce_actor(context, default_role=ActorRole.ADMIN)
    assert from_context == context


def test_parse_approved_actions_supports_enum_and_string() -> None:
    orchestrator = PMOrchestrator()

    parsed = orchestrator._parse_approved_actions(
        [ApprovalActionType.EXTERNAL_API_SEND, "production_affecting_change"]
    )

    assert parsed == {
        ApprovalActionType.EXTERNAL_API_SEND,
        ApprovalActionType.PRODUCTION_AFFECTING_CHANGE,
    }


def test_parse_approved_actions_strips_whitespace_for_string_values() -> None:
    orchestrator = PMOrchestrator()

    parsed = orchestrator._parse_approved_actions([" external_api_send "])

    assert parsed == {ApprovalActionType.EXTERNAL_API_SEND}


def test_parse_approved_actions_normalizes_case_for_string_values() -> None:
    orchestrator = PMOrchestrator()

    parsed = orchestrator._parse_approved_actions(["EXTERNAL_API_SEND", "Bulk_Modify"])

    assert parsed == {
        ApprovalActionType.EXTERNAL_API_SEND,
        ApprovalActionType.BULK_MODIFY,
    }


def test_parse_approved_actions_rejects_non_string_non_enum_values() -> None:
    orchestrator = PMOrchestrator()

    with pytest.raises(ValueError, match="Unsupported approval action value"):
        orchestrator._parse_approved_actions([123])  # type: ignore[list-item]


def test_parse_approved_actions_rejects_blank_string_values() -> None:
    orchestrator = PMOrchestrator()

    with pytest.raises(ValueError, match="Unsupported approval action value"):
        orchestrator._parse_approved_actions(["   "])


def test_parse_approved_actions_rejects_unknown_string_values_with_stable_message() -> None:
    orchestrator = PMOrchestrator()

    with pytest.raises(ValueError, match="Unsupported approval action value"):
        orchestrator._parse_approved_actions(["not_real_action"])


def test_parse_approved_actions_returns_empty_set_for_none_or_empty() -> None:
    orchestrator = PMOrchestrator()

    assert orchestrator._parse_approved_actions(None) == set()
    assert orchestrator._parse_approved_actions([]) == set()


def test_record_event_snapshots_metadata_dictionary() -> None:
    orchestrator = PMOrchestrator()
    result = orchestrator.run(_brief(), trend_provider_name="mock")
    metadata = {"marker": "before"}

    orchestrator._record_event(
        result.record,
        event_type=HistoryEventType.RESUME_TRIGGERED,
        actor=_operator(),
        metadata=metadata,
    )
    metadata["marker"] = "after"

    assert result.record.events[-1].metadata == {"marker": "before"}


def test_record_event_deep_snapshots_nested_metadata_dictionary() -> None:
    orchestrator = PMOrchestrator()
    result = orchestrator.run(_brief(), trend_provider_name="mock")
    metadata = {"outer": {"marker": "before"}}

    orchestrator._record_event(
        result.record,
        event_type=HistoryEventType.RESUME_TRIGGERED,
        actor=_operator(),
        metadata=metadata,
    )
    metadata["outer"]["marker"] = "after"

    assert result.record.events[-1].metadata == {"outer": {"marker": "before"}}


