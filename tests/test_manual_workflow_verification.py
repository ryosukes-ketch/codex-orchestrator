from fastapi.testclient import TestClient

from app.api.main import create_app
from app.api.runtime_bindings import bind_orchestrator_binding
from app.orchestrator.service import PMOrchestrator
from app.schemas.project import (
    ApprovalActionType,
    ApprovalRequest,
    ApprovalStatus,
    RevisionResumeMode,
)
from app.state.repository import InMemoryProjectRepository


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _intake_brief(client: TestClient) -> dict:
    intake = client.post(
        "/intake/brief",
        json={
            "user_request": (
                "Title: Manual workflow\n"
                "Scope: runtime manual approval/revision flow\n"
                "Constraints: python, fastapi\n"
                "Success Criteria: deterministic transitions and audit events\n"
                "Deadline: 2026-07-10"
            )
        },
    )
    assert intake.status_code == 200
    return intake.json()["brief"]


def _run_waiting_project(client: TestClient) -> str:
    run = client.post(
        "/orchestrator/run",
        json={"brief": _intake_brief(client), "trend_provider": "gemini"},
    )
    assert run.status_code == 200
    payload = run.json()
    assert payload["summary"]["status"] == "waiting_approval"
    return payload["record"]["project"]["id"]


def _run_revision_requested_project(client: TestClient) -> str:
    run = client.post(
        "/orchestrator/run",
        json={
            "brief": _intake_brief(client),
            "trend_provider": "mock",
            "simulate_review_failure": True,
        },
    )
    assert run.status_code == 200
    payload = run.json()
    assert payload["summary"]["status"] == "revision_requested"
    return payload["record"]["project"]["id"]


def _client_with_shared_repository(repository: InMemoryProjectRepository) -> TestClient:
    app = create_app()
    app_orchestrator = PMOrchestrator(repository=repository)
    bind_orchestrator_binding(app, orchestrator=app_orchestrator)
    return TestClient(app)


def test_manual_reject_then_resume_approval_conflicts_and_revision_rebuild_completes() -> None:
    client = TestClient(create_app())
    project_id = _run_waiting_project(client)

    rejected = client.post(
        "/orchestrator/approval/reject",
        json={
            "project_id": project_id,
            "rejected_actions": ["external_api_send"],
            "reason": "Manual rejection for runtime verification.",
            "note": "reject-first path",
        },
        headers=_auth("dev-approver-token"),
    )
    assert rejected.status_code == 200
    assert rejected.json()["summary"]["status"] == "revision_requested"

    resume_after_reject = client.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": ["external_api_send"],
            "trend_provider": "gemini",
        },
        headers=_auth("dev-approver-token"),
    )
    assert resume_after_reject.status_code == 409
    assert "current: revision_requested" in resume_after_reject.json()["detail"]

    rebuilt = client.post(
        "/orchestrator/resume/revision",
        json={
            "project_id": project_id,
            "resume_mode": "rebuilding",
            "reason": "Rebuild after manual rejection.",
            "trend_provider": "mock",
        },
        headers=_auth("dev-operator-token"),
    )
    assert rebuilt.status_code == 200
    assert rebuilt.json()["summary"]["status"] == "completed"

    audit = client.get(f"/projects/{project_id}/audit")
    assert audit.status_code == 200
    events = audit.json()["events"]
    assert any(event["event_type"] == "approval_rejected" for event in events)
    assert any(
        event["event_type"] == "resume_triggered" and event["metadata"].get("mode") == "rebuilding"
        for event in events
    )


def test_manual_reject_endpoint_requires_authentication() -> None:
    client = TestClient(create_app())
    project_id = _run_waiting_project(client)

    rejected = client.post(
        "/orchestrator/approval/reject",
        json={
            "project_id": project_id,
            "rejected_actions": ["external_api_send"],
            "reason": "Unauthenticated reject should fail.",
        },
    )
    assert rejected.status_code == 401

    audit = client.get(f"/projects/{project_id}/audit")
    assert audit.status_code == 200
    assert any(
        event["event_type"] == "authentication_failed" for event in audit.json()["events"]
    )


def test_manual_resume_approval_with_unknown_action_returns_conflict_and_keeps_waiting() -> None:
    client = TestClient(create_app())
    project_id = _run_waiting_project(client)

    resumed = client.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": ["destructive_change"],
            "trend_provider": "gemini",
        },
        headers=_auth("dev-approver-token"),
    )
    assert resumed.status_code == 409

    audit = client.get(f"/projects/{project_id}/audit")
    assert audit.status_code == 200
    payload = audit.json()
    assert payload["status"] == "waiting_approval"
    assert any(
        event["event_type"] == "actor_resolved" and event["actor"] == "approver-1"
        for event in payload["events"]
    )


def test_manual_resume_approval_idempotent_then_reject_conflicts_on_completed() -> None:
    client = TestClient(create_app())
    project_id = _run_waiting_project(client)

    first_resume = client.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": ["external_api_send"],
            "trend_provider": "gemini",
        },
        headers=_auth("dev-approver-token"),
    )
    assert first_resume.status_code == 200
    assert first_resume.json()["summary"]["status"] == "completed"

    second_resume = client.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": ["external_api_send"],
            "trend_provider": "gemini",
        },
        headers=_auth("dev-approver-token"),
    )
    assert second_resume.status_code == 200
    assert second_resume.json()["summary"]["status"] == "completed"

    reject_after_completed = client.post(
        "/orchestrator/approval/reject",
        json={
            "project_id": project_id,
            "rejected_actions": ["external_api_send"],
            "reason": "should conflict after completion",
        },
        headers=_auth("dev-approver-token"),
    )
    assert reject_after_completed.status_code == 409
    assert "current: completed" in reject_after_completed.json()["detail"]

    audit = client.get(f"/projects/{project_id}/audit").json()
    approval_approved_events = [
        event for event in audit["events"] if event["event_type"] == "approval_approved"
    ]
    approval_rejected_events = [
        event for event in audit["events"] if event["event_type"] == "approval_rejected"
    ]
    assert len(approval_approved_events) == 1
    assert len(approval_rejected_events) == 0


def test_manual_revision_replanning_and_start_replanning_are_idempotent() -> None:
    client = TestClient(create_app())
    revision = client.post(
        "/orchestrator/run",
        json={
            "brief": _intake_brief(client),
            "trend_provider": "mock",
            "simulate_review_failure": True,
        },
    )
    assert revision.status_code == 200
    project_id = revision.json()["record"]["project"]["id"]

    first_ready = client.post(
        "/orchestrator/resume/revision",
        json={
            "project_id": project_id,
            "resume_mode": "replanning",
            "reason": "need replanning lane",
        },
        headers=_auth("dev-operator-token"),
    )
    assert first_ready.status_code == 200
    assert first_ready.json()["summary"]["status"] == "ready_for_planning"

    second_ready = client.post(
        "/orchestrator/resume/revision",
        json={
            "project_id": project_id,
            "resume_mode": "replanning",
            "reason": "need replanning lane",
        },
        headers=_auth("dev-operator-token"),
    )
    assert second_ready.status_code == 200
    assert second_ready.json()["summary"]["status"] == "ready_for_planning"

    first_start = client.post(
        "/orchestrator/replanning/start",
        json={
            "project_id": project_id,
            "note": "begin replanning execution",
            "trend_provider": "mock",
        },
        headers=_auth("dev-operator-token"),
    )
    assert first_start.status_code == 200
    assert first_start.json()["summary"]["status"] == "completed"

    second_start = client.post(
        "/orchestrator/replanning/start",
        json={
            "project_id": project_id,
            "note": "begin replanning execution",
            "trend_provider": "mock",
        },
        headers=_auth("dev-operator-token"),
    )
    assert second_start.status_code == 200
    assert second_start.json()["summary"]["status"] == "completed"

    audit = client.get(f"/projects/{project_id}/audit").json()
    replanning_resume_events = [
        event
        for event in audit["events"]
        if event["event_type"] == "resume_triggered"
        and event["metadata"].get("mode") == "replanning"
    ]
    replanning_start_events = [
        event for event in audit["events"] if event["event_type"] == "replanning_started"
    ]
    assert len(replanning_resume_events) == 1
    assert len(replanning_start_events) == 1


def test_manual_partial_approve_then_reject_remaining_moves_to_revision_with_consistent_audit(
) -> None:
    client = TestClient(create_app())
    project_id = _run_waiting_project(client)
    record = client.app.state.orchestrator.repository.get(project_id)
    assert record is not None
    record.approvals.append(
        ApprovalRequest(
            id="approval-bulk-modify-manual-mixed",
            action_type=ApprovalActionType.BULK_MODIFY,
            status=ApprovalStatus.PENDING,
            reason="Bulk modify requires explicit approval.",
            requested_by="system",
        )
    )
    client.app.state.orchestrator.repository.save(record)

    partial = client.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": ["external_api_send"],
            "trend_provider": "gemini",
        },
        headers=_auth("dev-approver-token"),
    )
    assert partial.status_code == 200
    assert partial.json()["summary"]["status"] == "waiting_approval"

    rejected = client.post(
        "/orchestrator/approval/reject",
        json={
            "project_id": project_id,
            "rejected_actions": ["bulk_modify"],
            "reason": "Reject remaining action after partial approval.",
        },
        headers=_auth("dev-approver-token"),
    )
    assert rejected.status_code == 200
    assert rejected.json()["summary"]["status"] == "revision_requested"

    resume_after_reject = client.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": ["bulk_modify"],
            "trend_provider": "gemini",
        },
        headers=_auth("dev-approver-token"),
    )
    assert resume_after_reject.status_code == 409
    assert "current: revision_requested" in resume_after_reject.json()["detail"]

    audit = client.get(f"/projects/{project_id}/audit")
    assert audit.status_code == 200
    events = audit.json()["events"]
    assert any(event["event_type"] == "approval_approved" for event in events)
    assert any(event["event_type"] == "approval_rejected" for event in events)
    assert any(
        event["event_type"] == "resume_triggered"
        and event["metadata"].get("mode") == "approval_resume_partial"
        for event in events
    )


def test_manual_partial_approve_flow_preserves_conflict_order_across_app_reloads() -> None:
    repository = InMemoryProjectRepository()
    client_one = _client_with_shared_repository(repository)
    project_id = _run_waiting_project(client_one)
    record = client_one.app.state.orchestrator.repository.get(project_id)
    assert record is not None
    record.approvals.append(
        ApprovalRequest(
            id="approval-bulk-modify-reload-partial-flow",
            action_type=ApprovalActionType.BULK_MODIFY,
            status=ApprovalStatus.PENDING,
            reason="Bulk modify requires explicit approval.",
            requested_by="system",
        )
    )
    client_one.app.state.orchestrator.repository.save(record)

    first_partial = client_one.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": ["external_api_send"],
            "trend_provider": "gemini",
        },
        headers=_auth("dev-approver-token"),
    )
    assert first_partial.status_code == 200
    assert first_partial.json()["summary"]["status"] == "waiting_approval"

    client_two = _client_with_shared_repository(repository)
    completed = client_two.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": ["bulk_modify"],
            "trend_provider": "gemini",
        },
        headers=_auth("dev-approver-token"),
    )
    assert completed.status_code == 200
    assert completed.json()["summary"]["status"] == "completed"

    client_three = _client_with_shared_repository(repository)
    reject_after_complete = client_three.post(
        "/orchestrator/approval/reject",
        json={
            "project_id": project_id,
            "rejected_actions": ["external_api_send"],
            "reason": "late reject should conflict",
        },
        headers=_auth("dev-approver-token"),
    )
    assert reject_after_complete.status_code == 409
    assert "current: completed" in reject_after_complete.json()["detail"]

    audit = client_three.get(f"/projects/{project_id}/audit")
    events = audit.json()["events"]
    partial_events = [
        event
        for event in events
        if event["event_type"] == "resume_triggered"
        and event["metadata"].get("mode") == "approval_resume_partial"
    ]
    approved_events = [
        event for event in events if event["event_type"] == "approval_approved"
    ]
    assert len(partial_events) == 1
    assert len(approved_events) == 2


def test_manual_partial_approve_retry_is_idempotent_across_app_reloads() -> None:
    repository = InMemoryProjectRepository()
    client_one = _client_with_shared_repository(repository)
    project_id = _run_waiting_project(client_one)
    record = client_one.app.state.orchestrator.repository.get(project_id)
    assert record is not None
    record.approvals.append(
        ApprovalRequest(
            id="approval-bulk-modify-reload-partial-idempotent",
            action_type=ApprovalActionType.BULK_MODIFY,
            status=ApprovalStatus.PENDING,
            reason="Bulk modify requires explicit approval.",
            requested_by="system",
        )
    )
    client_one.app.state.orchestrator.repository.save(record)

    partial_one = client_one.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": ["external_api_send"],
            "trend_provider": "gemini",
        },
        headers=_auth("dev-approver-token"),
    )
    assert partial_one.status_code == 200
    assert partial_one.json()["summary"]["status"] == "waiting_approval"

    client_two = _client_with_shared_repository(repository)
    partial_two = client_two.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": ["external_api_send"],
            "trend_provider": "gemini",
        },
        headers=_auth("dev-approver-token"),
    )
    assert partial_two.status_code == 200
    assert partial_two.json()["summary"]["status"] == "waiting_approval"

    audit = client_two.get(f"/projects/{project_id}/audit").json()
    partial_events = [
        event
        for event in audit["events"]
        if event["event_type"] == "resume_triggered"
        and event["metadata"].get("mode") == "approval_resume_partial"
    ]
    approved_events = [
        event for event in audit["events"] if event["event_type"] == "approval_approved"
    ]
    assert len(partial_events) == 1
    assert len(approved_events) == 1


def test_manual_reject_retry_and_conflict_detail_are_stable_across_app_reloads() -> None:
    repository = InMemoryProjectRepository()
    client_one = _client_with_shared_repository(repository)
    project_id = _run_waiting_project(client_one)

    rejected = client_one.post(
        "/orchestrator/approval/reject",
        json={
            "project_id": project_id,
            "rejected_actions": ["external_api_send"],
            "reason": "  reject across reload  ",
        },
        headers=_auth("dev-approver-token"),
    )
    assert rejected.status_code == 200
    assert rejected.json()["summary"]["status"] == "revision_requested"

    client_two = _client_with_shared_repository(repository)
    reject_retry = client_two.post(
        "/orchestrator/approval/reject",
        json={
            "project_id": project_id,
            "rejected_actions": ["external_api_send"],
            "reason": "reject retry",
        },
        headers=_auth("dev-approver-token"),
    )
    assert reject_retry.status_code == 200
    assert reject_retry.json()["summary"]["status"] == "revision_requested"

    resume_after_reject = client_two.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": ["external_api_send"],
            "trend_provider": "gemini",
        },
        headers=_auth("dev-approver-token"),
    )
    assert resume_after_reject.status_code == 409
    assert "current: revision_requested" in resume_after_reject.json()["detail"]

    audit = client_two.get(f"/projects/{project_id}/audit").json()
    rejected_events = [
        event for event in audit["events"] if event["event_type"] == "approval_rejected"
    ]
    assert len(rejected_events) == 1


def test_manual_revision_replanning_start_flow_stays_idempotent_across_app_reloads() -> None:
    repository = InMemoryProjectRepository()
    client_one = _client_with_shared_repository(repository)
    revision_run = client_one.post(
        "/orchestrator/run",
        json={
            "brief": _intake_brief(client_one),
            "trend_provider": "mock",
            "simulate_review_failure": True,
        },
    )
    assert revision_run.status_code == 200
    project_id = revision_run.json()["record"]["project"]["id"]

    ready = client_one.post(
        "/orchestrator/resume/revision",
        json={
            "project_id": project_id,
            "resume_mode": "replanning",
            "reason": "  prepare replanning after reload  ",
        },
        headers=_auth("dev-operator-token"),
    )
    assert ready.status_code == 200
    assert ready.json()["summary"]["status"] == "ready_for_planning"

    client_two = _client_with_shared_repository(repository)
    started = client_two.post(
        "/orchestrator/replanning/start",
        json={
            "project_id": project_id,
            "note": "  start replanning  ",
            "trend_provider": "mock",
        },
        headers=_auth("dev-operator-token"),
    )
    assert started.status_code == 200
    assert started.json()["summary"]["status"] == "completed"

    client_three = _client_with_shared_repository(repository)
    resume_retry = client_three.post(
        "/orchestrator/resume/revision",
        json={
            "project_id": project_id,
            "resume_mode": "replanning",
            "reason": "retry replanning resume",
        },
        headers=_auth("dev-operator-token"),
    )
    assert resume_retry.status_code == 200
    assert resume_retry.json()["summary"]["status"] == "completed"
    assert resume_retry.json()["summary"]["next_steps"] == [
        "Project already completed; revision resume request treated as idempotent."
    ]

    audit = client_three.get(f"/projects/{project_id}/audit").json()
    replanning_resume_events = [
        event
        for event in audit["events"]
        if event["event_type"] == "resume_triggered"
        and event["metadata"].get("mode") == "replanning"
    ]
    replanning_start_events = [
        event for event in audit["events"] if event["event_type"] == "replanning_started"
    ]
    assert len(replanning_resume_events) == 1
    assert len(replanning_start_events) == 1


def test_reject_retry_preserves_original_rejection_metadata_across_reloads() -> None:
    repository = InMemoryProjectRepository()
    client_one = _client_with_shared_repository(repository)
    project_id = _run_waiting_project(client_one)

    first_reject = client_one.post(
        "/orchestrator/approval/reject",
        json={
            "project_id": project_id,
            "rejected_actions": ["external_api_send"],
            "reason": "  initial rejection reason  ",
            "note": "  initial rejection note  ",
        },
        headers=_auth("dev-approver-token"),
    )
    assert first_reject.status_code == 200
    assert first_reject.json()["summary"]["status"] == "revision_requested"

    client_two = _client_with_shared_repository(repository)
    retry_reject = client_two.post(
        "/orchestrator/approval/reject",
        json={
            "project_id": project_id,
            "rejected_actions": ["external_api_send"],
            "reason": "  retry reason must not overwrite  ",
            "note": "  retry note must not overwrite  ",
        },
        headers=_auth("dev-approver-token"),
    )
    assert retry_reject.status_code == 200
    assert retry_reject.json()["summary"]["status"] == "revision_requested"

    audit = client_two.get(f"/projects/{project_id}/audit").json()
    rejected_events = [
        event for event in audit["events"] if event["event_type"] == "approval_rejected"
    ]
    assert len(rejected_events) == 1
    assert rejected_events[0]["reason"] == "initial rejection reason"
    assert rejected_events[0]["metadata"]["note"] == "initial rejection note"

    rejected_approval = next(
        approval
        for approval in audit["approvals"]
        if approval["action_type"] == "external_api_send"
    )
    assert rejected_approval["decision_note"] == "initial rejection reason initial rejection note"


def test_partial_retry_preserves_original_approval_metadata_across_reloads() -> None:
    repository = InMemoryProjectRepository()
    client_one = _client_with_shared_repository(repository)
    project_id = _run_waiting_project(client_one)
    record = client_one.app.state.orchestrator.repository.get(project_id)
    assert record is not None
    record.approvals.append(
        ApprovalRequest(
            id="approval-bulk-modify-reload-partial-metadata-stability",
            action_type=ApprovalActionType.BULK_MODIFY,
            status=ApprovalStatus.PENDING,
            reason="Bulk modify requires explicit approval.",
            requested_by="system",
        )
    )
    client_one.app.state.orchestrator.repository.save(record)

    first_partial = client_one.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": ["external_api_send"],
            "note": "  first partial note  ",
            "trend_provider": "gemini",
        },
        headers=_auth("dev-approver-token"),
    )
    assert first_partial.status_code == 200
    assert first_partial.json()["summary"]["status"] == "waiting_approval"

    client_two = _client_with_shared_repository(repository)
    retry_partial = client_two.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": ["external_api_send"],
            "note": "  retry note must not overwrite  ",
            "trend_provider": "gemini",
        },
        headers=_auth("dev-approver-token"),
    )
    assert retry_partial.status_code == 200
    assert retry_partial.json()["summary"]["status"] == "waiting_approval"

    audit = client_two.get(f"/projects/{project_id}/audit").json()
    approved_events = [
        event for event in audit["events"] if event["event_type"] == "approval_approved"
    ]
    partial_resume_events = [
        event
        for event in audit["events"]
        if event["event_type"] == "resume_triggered"
        and event["metadata"].get("mode") == "approval_resume_partial"
    ]
    assert len(approved_events) == 1
    assert len(partial_resume_events) == 1
    assert approved_events[0]["reason"] == "first partial note"
    assert partial_resume_events[0]["reason"] == "first partial note"

    approved_approval = next(
        approval
        for approval in audit["approvals"]
        if approval["action_type"] == "external_api_send"
    )
    assert approved_approval["decision_note"] == "first partial note"


def test_mixed_approval_revision_flow_preserves_event_order_across_app_reloads() -> None:
    repository = InMemoryProjectRepository()
    client_one = _client_with_shared_repository(repository)
    project_id = _run_waiting_project(client_one)
    record = client_one.app.state.orchestrator.repository.get(project_id)
    assert record is not None
    record.approvals.append(
        ApprovalRequest(
            id="approval-bulk-modify-reload-event-order",
            action_type=ApprovalActionType.BULK_MODIFY,
            status=ApprovalStatus.PENDING,
            reason="Bulk modify requires explicit approval.",
            requested_by="system",
        )
    )
    client_one.app.state.orchestrator.repository.save(record)

    partial = client_one.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": ["external_api_send"],
            "note": "partial approval note",
            "trend_provider": "gemini",
        },
        headers=_auth("dev-approver-token"),
    )
    assert partial.status_code == 200
    assert partial.json()["summary"]["status"] == "waiting_approval"

    client_two = _client_with_shared_repository(repository)
    rejected = client_two.post(
        "/orchestrator/approval/reject",
        json={
            "project_id": project_id,
            "rejected_actions": ["bulk_modify"],
            "reason": "reject remaining action for revision",
            "note": "revision requested note",
        },
        headers=_auth("dev-approver-token"),
    )
    assert rejected.status_code == 200
    assert rejected.json()["summary"]["status"] == "revision_requested"

    client_three = _client_with_shared_repository(repository)
    ready = client_three.post(
        "/orchestrator/resume/revision",
        json={
            "project_id": project_id,
            "resume_mode": "replanning",
            "reason": "move to ready_for_planning",
        },
        headers=_auth("dev-operator-token"),
    )
    assert ready.status_code == 200
    assert ready.json()["summary"]["status"] == "ready_for_planning"

    client_four = _client_with_shared_repository(repository)
    started = client_four.post(
        "/orchestrator/replanning/start",
        json={
            "project_id": project_id,
            "note": "start replanning execution",
            "trend_provider": "mock",
        },
        headers=_auth("dev-operator-token"),
    )
    assert started.status_code == 200
    assert started.json()["summary"]["status"] == "completed"

    audit = client_four.get(f"/projects/{project_id}/audit").json()
    assert len(
        [
            event
            for event in audit["events"]
            if event["event_type"] == "resume_triggered"
            and event["metadata"].get("mode") == "approval_resume_partial"
        ]
    ) == 1
    assert len(
        [
            event
            for event in audit["events"]
            if event["event_type"] == "approval_rejected"
            and event["metadata"].get("action_type") == "bulk_modify"
        ]
    ) == 1
    assert len(
        [
            event
            for event in audit["events"]
            if event["event_type"] == "resume_triggered"
            and event["metadata"].get("mode") == "replanning"
        ]
    ) == 1
    assert len(
        [event for event in audit["events"] if event["event_type"] == "replanning_started"]
    ) == 1

    ordered_markers: list[str] = []
    for event in audit["events"]:
        if event["event_type"] == "approval_approved" and event["metadata"].get("action_type") == (
            "external_api_send"
        ):
            ordered_markers.append("approval_approved_external")
        if event["event_type"] == "resume_triggered" and event["metadata"].get("mode") == (
            "approval_resume_partial"
        ):
            ordered_markers.append("resume_partial")
        if event["event_type"] == "approval_rejected" and event["metadata"].get("action_type") == (
            "bulk_modify"
        ):
            ordered_markers.append("approval_rejected_bulk")
        if (
            event["event_type"] == "resume_triggered"
            and event["metadata"].get("mode") == "replanning"
        ):
            ordered_markers.append("resume_replanning")
        if event["event_type"] == "replanning_started":
            ordered_markers.append("replanning_started")

    expected_order = [
        "approval_approved_external",
        "resume_partial",
        "approval_rejected_bulk",
        "resume_replanning",
        "replanning_started",
    ]
    marker_position = {marker: ordered_markers.index(marker) for marker in expected_order}
    assert marker_position["approval_approved_external"] < marker_position["resume_partial"]
    assert marker_position["resume_partial"] < marker_position["approval_rejected_bulk"]
    assert marker_position["approval_rejected_bulk"] < marker_position["resume_replanning"]
    assert marker_position["resume_replanning"] < marker_position["replanning_started"]


def test_api_direct_mixed_write_parity_preserves_conflict_detail_and_metadata() -> None:
    repository = InMemoryProjectRepository()
    api_client_one = _client_with_shared_repository(repository)
    project_id = _run_waiting_project(api_client_one)
    record = api_client_one.app.state.orchestrator.repository.get(project_id)
    assert record is not None
    record.approvals.append(
        ApprovalRequest(
            id="approval-bulk-modify-api-direct-mixed-parity",
            action_type=ApprovalActionType.BULK_MODIFY,
            status=ApprovalStatus.PENDING,
            reason="Bulk modify requires explicit approval.",
            requested_by="system",
        )
    )
    api_client_one.app.state.orchestrator.repository.save(record)

    partial = api_client_one.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": ["external_api_send"],
            "note": "api partial note",
            "trend_provider": "gemini",
        },
        headers=_auth("dev-approver-token"),
    )
    assert partial.status_code == 200
    assert partial.json()["summary"]["status"] == "waiting_approval"

    direct_orchestrator = PMOrchestrator(repository=repository)
    direct_rejected = direct_orchestrator.reject_approval(
        project_id=project_id,
        rejected_actions=["bulk_modify"],
        actor="approver-1",
        reason="direct reject remaining action",
        note="direct reject note",
    )
    assert direct_rejected.summary.status.value == "revision_requested"

    api_client_two = _client_with_shared_repository(repository)
    api_conflict = api_client_two.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": ["bulk_modify"],
            "trend_provider": "gemini",
        },
        headers=_auth("dev-approver-token"),
    )
    assert api_conflict.status_code == 409

    with_conflict = PMOrchestrator(repository=repository)
    try:
        with_conflict.resume_from_approval(
            project_id=project_id,
            approved_actions=["bulk_modify"],
            actor="approver-1",
            trend_provider_name="gemini",
        )
        raise AssertionError("expected ValueError conflict from direct orchestrator")
    except ValueError as exc:
        assert api_conflict.json()["detail"] == str(exc)

    audit = api_client_two.get(f"/projects/{project_id}/audit").json()
    external_approval = next(
        approval
        for approval in audit["approvals"]
        if approval["action_type"] == "external_api_send"
    )
    bulk_rejection = next(
        approval for approval in audit["approvals"] if approval["action_type"] == "bulk_modify"
    )
    assert external_approval["decision_note"] == "api partial note"
    assert bulk_rejection["decision_note"] == "direct reject remaining action direct reject note"


def test_api_retry_after_direct_reject_keeps_conflict_parity_and_single_rejection_event() -> None:
    repository = InMemoryProjectRepository()
    client_one = _client_with_shared_repository(repository)
    project_id = _run_waiting_project(client_one)

    direct_orchestrator = PMOrchestrator(repository=repository)
    direct_reject = direct_orchestrator.reject_approval(
        project_id=project_id,
        rejected_actions=["external_api_send"],
        actor="approver-1",
        reason="direct reject reason",
        note="direct reject note",
    )
    assert direct_reject.summary.status.value == "revision_requested"

    client_two = _client_with_shared_repository(repository)
    api_retry = client_two.post(
        "/orchestrator/approval/reject",
        json={
            "project_id": project_id,
            "rejected_actions": ["external_api_send"],
            "reason": "api retry reason should be ignored",
            "note": "api retry note should be ignored",
        },
        headers=_auth("dev-approver-token"),
    )
    assert api_retry.status_code == 200
    assert api_retry.json()["summary"]["status"] == "revision_requested"
    assert api_retry.json()["summary"]["next_steps"] == direct_reject.summary.next_steps

    audit = client_two.get(f"/projects/{project_id}/audit").json()
    rejected_events = [
        event for event in audit["events"] if event["event_type"] == "approval_rejected"
    ]
    assert len(rejected_events) == 1
    assert rejected_events[0]["reason"] == "direct reject reason"
    assert rejected_events[0]["metadata"]["note"] == "direct reject note"


def test_api_retry_after_direct_revision_resume_keeps_single_replanning_resume_event() -> None:
    repository = InMemoryProjectRepository()
    client_one = _client_with_shared_repository(repository)
    revision = client_one.post(
        "/orchestrator/run",
        json={
            "brief": _intake_brief(client_one),
            "trend_provider": "mock",
            "simulate_review_failure": True,
        },
    )
    assert revision.status_code == 200
    project_id = revision.json()["record"]["project"]["id"]

    direct_orchestrator = PMOrchestrator(repository=repository)
    direct_ready = direct_orchestrator.resume_from_revision(
        project_id=project_id,
        resume_mode=RevisionResumeMode.REPLANNING,
        actor="operator-1",
        reason="direct replanning reason",
    )
    assert direct_ready.summary.status.value == "ready_for_planning"

    client_two = _client_with_shared_repository(repository)
    api_retry = client_two.post(
        "/orchestrator/resume/revision",
        json={
            "project_id": project_id,
            "resume_mode": "replanning",
            "reason": "api retry reason should be ignored",
        },
        headers=_auth("dev-operator-token"),
    )
    assert api_retry.status_code == 200
    assert api_retry.json()["summary"]["status"] == "ready_for_planning"
    assert api_retry.json()["summary"]["next_steps"] == direct_ready.summary.next_steps

    audit = client_two.get(f"/projects/{project_id}/audit").json()
    replanning_resume_events = [
        event
        for event in audit["events"]
        if event["event_type"] == "resume_triggered"
        and event["metadata"].get("mode") == "replanning"
    ]
    assert len(replanning_resume_events) == 1
    assert replanning_resume_events[0]["reason"] == "direct replanning reason"


def test_api_direct_conflict_detail_matches_after_direct_replanning_start() -> None:
    repository = InMemoryProjectRepository()
    client_one = _client_with_shared_repository(repository)
    revision = client_one.post(
        "/orchestrator/run",
        json={
            "brief": _intake_brief(client_one),
            "trend_provider": "mock",
            "simulate_review_failure": True,
        },
    )
    assert revision.status_code == 200
    project_id = revision.json()["record"]["project"]["id"]

    ready = client_one.post(
        "/orchestrator/resume/revision",
        json={
            "project_id": project_id,
            "resume_mode": "replanning",
            "reason": "prepare replanning",
        },
        headers=_auth("dev-operator-token"),
    )
    assert ready.status_code == 200
    assert ready.json()["summary"]["status"] == "ready_for_planning"

    direct_orchestrator = PMOrchestrator(repository=repository)
    started = direct_orchestrator.start_replanning(
        project_id=project_id,
        actor="operator-1",
        note="direct replanning start",
        trend_provider_name="mock",
    )
    assert started.summary.status.value == "completed"

    client_two = _client_with_shared_repository(repository)
    api_conflict = client_two.post(
        "/orchestrator/resume/revision",
        json={
            "project_id": project_id,
            "resume_mode": "rebuilding",
            "reason": "api conflict parity check",
            "trend_provider": "mock",
        },
        headers=_auth("dev-operator-token"),
    )
    assert api_conflict.status_code == 409

    parity_orchestrator = PMOrchestrator(repository=repository)
    try:
        parity_orchestrator.resume_from_revision(
            project_id=project_id,
            resume_mode=RevisionResumeMode.REBUILDING,
            actor="operator-1",
            reason="direct conflict parity check",
            trend_provider_name="mock",
        )
        raise AssertionError("expected direct revision resume conflict")
    except ValueError as exc:
        assert api_conflict.json()["detail"] == str(exc)

    audit = client_two.get(f"/projects/{project_id}/audit").json()
    assert len(
        [event for event in audit["events"] if event["event_type"] == "replanning_started"]
    ) == 1
    assert len(
        [
            event
            for event in audit["events"]
            if event["event_type"] == "resume_triggered"
            and event["metadata"].get("mode") == "rebuilding"
        ]
    ) == 0


def test_api_retry_after_direct_rereview_keeps_single_resume_event_and_notes() -> None:
    repository = InMemoryProjectRepository()
    client_one = _client_with_shared_repository(repository)
    project_id = _run_revision_requested_project(client_one)

    direct_orchestrator = PMOrchestrator(repository=repository)
    direct_completed = direct_orchestrator.resume_from_revision(
        project_id=project_id,
        resume_mode=RevisionResumeMode.REREVIEW,
        actor="operator-1",
        reason="direct rereview reason",
        trend_provider_name="mock",
    )
    assert direct_completed.summary.status.value == "completed"

    client_two = _client_with_shared_repository(repository)
    api_retry = client_two.post(
        "/orchestrator/resume/revision",
        json={
            "project_id": project_id,
            "resume_mode": "rereview",
            "reason": "api retry reason should be ignored",
            "trend_provider": "mock",
        },
        headers=_auth("dev-operator-token"),
    )
    assert api_retry.status_code == 200
    assert api_retry.json()["summary"]["status"] == "completed"
    assert api_retry.json()["summary"]["next_steps"] == [
        "Project already completed; revision resume request treated as idempotent."
    ]

    audit = client_two.get(f"/projects/{project_id}/audit").json()
    rereview_events = [
        event
        for event in audit["events"]
        if event["event_type"] == "resume_triggered"
        and event["metadata"].get("mode") == "rereview"
    ]
    assert len(rereview_events) == 1
    assert rereview_events[0]["reason"] == "direct rereview reason"

    record = client_two.app.state.orchestrator.repository.get(project_id)
    assert record is not None
    task_note_by_id = {task.id: task.note for task in record.tasks}
    assert task_note_by_id["task-review"] == "direct rereview reason"
    assert task_note_by_id["task-build"] != "api retry reason should be ignored"


def test_api_retry_after_direct_rebuilding_keeps_single_resume_event_and_notes() -> None:
    repository = InMemoryProjectRepository()
    client_one = _client_with_shared_repository(repository)
    project_id = _run_revision_requested_project(client_one)

    direct_orchestrator = PMOrchestrator(repository=repository)
    direct_completed = direct_orchestrator.resume_from_revision(
        project_id=project_id,
        resume_mode=RevisionResumeMode.REBUILDING,
        actor="operator-1",
        reason="direct rebuilding reason",
        trend_provider_name="mock",
    )
    assert direct_completed.summary.status.value == "completed"

    client_two = _client_with_shared_repository(repository)
    api_retry = client_two.post(
        "/orchestrator/resume/revision",
        json={
            "project_id": project_id,
            "resume_mode": "rebuilding",
            "reason": "api retry reason should be ignored",
            "trend_provider": "mock",
        },
        headers=_auth("dev-operator-token"),
    )
    assert api_retry.status_code == 200
    assert api_retry.json()["summary"]["status"] == "completed"
    assert api_retry.json()["summary"]["next_steps"] == [
        "Project already completed; revision resume request treated as idempotent."
    ]

    audit = client_two.get(f"/projects/{project_id}/audit").json()
    rebuilding_events = [
        event
        for event in audit["events"]
        if event["event_type"] == "resume_triggered"
        and event["metadata"].get("mode") == "rebuilding"
    ]
    assert len(rebuilding_events) == 1
    assert rebuilding_events[0]["reason"] == "direct rebuilding reason"

    record = client_two.app.state.orchestrator.repository.get(project_id)
    assert record is not None
    task_note_by_id = {task.id: task.note for task in record.tasks}
    assert task_note_by_id["task-build"] == "direct rebuilding reason"
    assert task_note_by_id["task-review"] == "direct rebuilding reason"


def test_api_direct_reject_conflict_detail_matches_after_direct_rereview_or_rebuilding() -> None:
    repository = InMemoryProjectRepository()
    for mode_label, mode_value in (
        ("rereview", RevisionResumeMode.REREVIEW),
        ("rebuilding", RevisionResumeMode.REBUILDING),
    ):
        seed_client = _client_with_shared_repository(repository)
        project_id = _run_revision_requested_project(seed_client)

        direct_orchestrator = PMOrchestrator(repository=repository)
        completed = direct_orchestrator.resume_from_revision(
            project_id=project_id,
            resume_mode=mode_value,
            actor="operator-1",
            reason=f"direct {mode_label} reason",
            trend_provider_name="mock",
        )
        assert completed.summary.status.value == "completed"

        api_client = _client_with_shared_repository(repository)
        api_conflict = api_client.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_id,
                "rejected_actions": ["external_api_send"],
                "reason": f"api reject conflict after {mode_label}",
            },
            headers=_auth("dev-approver-token"),
        )
        assert api_conflict.status_code == 409

        parity_orchestrator = PMOrchestrator(repository=repository)
        try:
            parity_orchestrator.reject_approval(
                project_id=project_id,
                rejected_actions=["external_api_send"],
                actor="approver-1",
                reason=f"direct reject conflict after {mode_label}",
            )
            raise AssertionError("expected direct reject conflict")
        except ValueError as exc:
            assert api_conflict.json()["detail"] == str(exc)


def test_mixed_rereview_reload_followups_keep_event_subsequence_and_metadata_immutable() -> None:
    repository = InMemoryProjectRepository()
    seed_client = _client_with_shared_repository(repository)
    project_id = _run_revision_requested_project(seed_client)

    direct_orchestrator = PMOrchestrator(repository=repository)
    direct_completed = direct_orchestrator.resume_from_revision(
        project_id=project_id,
        resume_mode=RevisionResumeMode.REREVIEW,
        actor="operator-1",
        reason="cross-branch rereview reason",
        trend_provider_name="mock",
    )
    assert direct_completed.summary.status.value == "completed"

    api_client = _client_with_shared_repository(repository)
    rereview_retry = api_client.post(
        "/orchestrator/resume/revision",
        json={
            "project_id": project_id,
            "resume_mode": "rereview",
            "reason": "retry rereview should stay idempotent",
            "trend_provider": "mock",
        },
        headers=_auth("dev-operator-token"),
    )
    rebuilding_conflict = api_client.post(
        "/orchestrator/resume/revision",
        json={
            "project_id": project_id,
            "resume_mode": "rebuilding",
            "reason": "cross-branch retry should conflict",
            "trend_provider": "mock",
        },
        headers=_auth("dev-operator-token"),
    )
    approval_conflict = api_client.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": ["external_api_send"],
            "trend_provider": "mock",
        },
        headers=_auth("dev-approver-token"),
    )
    assert rereview_retry.status_code == 200
    assert rebuilding_conflict.status_code == 409
    assert approval_conflict.status_code == 409
    assert "current: completed" in rebuilding_conflict.json()["detail"]
    assert "current: completed" in approval_conflict.json()["detail"]

    audit = api_client.get(f"/projects/{project_id}/audit").json()
    rereview_events = [
        event
        for event in audit["events"]
        if event["event_type"] == "resume_triggered"
        and event["metadata"].get("mode") == "rereview"
    ]
    rebuilding_events = [
        event
        for event in audit["events"]
        if event["event_type"] == "resume_triggered"
        and event["metadata"].get("mode") == "rebuilding"
    ]
    assert len(rereview_events) == 1
    assert len(rebuilding_events) == 0

    markers: list[str] = []
    for event in audit["events"]:
        if (
            event["event_type"] == "resume_triggered"
            and event["metadata"].get("mode") == "rereview"
        ):
            markers.append("resume_rereview")
        if (
            event["event_type"] == "state_transition"
            and event["metadata"].get("from") == "revision_requested"
            and event["metadata"].get("to") == "in_progress"
        ):
            markers.append("transition_to_in_progress")
        if (
            event["event_type"] == "state_transition"
            and event["metadata"].get("from") == "in_progress"
            and event["metadata"].get("to") == "completed"
        ):
            markers.append("transition_to_completed")
    expected = ["resume_rereview", "transition_to_in_progress", "transition_to_completed"]
    positions = {name: markers.index(name) for name in expected}
    assert positions["resume_rereview"] < positions["transition_to_in_progress"]
    assert positions["transition_to_in_progress"] < positions["transition_to_completed"]

    mutable_metadata = rereview_events[0]["metadata"]
    mutable_metadata["mode"] = "tampered-mode"
    reread_audit = api_client.get(f"/projects/{project_id}/audit").json()
    reread_rereview_events = [
        event
        for event in reread_audit["events"]
        if event["event_type"] == "resume_triggered"
        and event["metadata"].get("mode") == "rereview"
    ]
    assert len(reread_rereview_events) == 1


def test_mixed_rebuilding_reload_followups_keep_notes_and_conflict_parity_stable() -> None:
    repository = InMemoryProjectRepository()
    seed_client = _client_with_shared_repository(repository)
    project_id = _run_revision_requested_project(seed_client)

    direct_orchestrator = PMOrchestrator(repository=repository)
    direct_completed = direct_orchestrator.resume_from_revision(
        project_id=project_id,
        resume_mode=RevisionResumeMode.REBUILDING,
        actor="operator-1",
        reason="cross-branch rebuilding reason",
        trend_provider_name="mock",
    )
    assert direct_completed.summary.status.value == "completed"

    api_client = _client_with_shared_repository(repository)
    rebuilding_retry = api_client.post(
        "/orchestrator/resume/revision",
        json={
            "project_id": project_id,
            "resume_mode": "rebuilding",
            "reason": "retry rebuilding should stay idempotent",
            "trend_provider": "mock",
        },
        headers=_auth("dev-operator-token"),
    )
    reject_conflict = api_client.post(
        "/orchestrator/approval/reject",
        json={
            "project_id": project_id,
            "rejected_actions": ["external_api_send"],
            "reason": "reject after rebuilding completion should conflict",
        },
        headers=_auth("dev-approver-token"),
    )
    approval_conflict = api_client.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": ["external_api_send"],
            "trend_provider": "mock",
        },
        headers=_auth("dev-approver-token"),
    )
    assert rebuilding_retry.status_code == 200
    assert reject_conflict.status_code == 409
    assert approval_conflict.status_code == 409

    parity_orchestrator = PMOrchestrator(repository=repository)
    try:
        parity_orchestrator.resume_from_approval(
            project_id=project_id,
            approved_actions=["external_api_send"],
            actor="approver-1",
            trend_provider_name="mock",
        )
        raise AssertionError("expected direct approval resume conflict")
    except ValueError as exc:
        assert approval_conflict.json()["detail"] == str(exc)

    audit = api_client.get(f"/projects/{project_id}/audit").json()
    rebuilding_events = [
        event
        for event in audit["events"]
        if event["event_type"] == "resume_triggered"
        and event["metadata"].get("mode") == "rebuilding"
    ]
    rejected_events = [
        event for event in audit["events"] if event["event_type"] == "approval_rejected"
    ]
    approved_events = [
        event for event in audit["events"] if event["event_type"] == "approval_approved"
    ]
    assert len(rebuilding_events) == 1
    assert len(rejected_events) == 0
    assert len(approved_events) == 0

    record = api_client.app.state.orchestrator.repository.get(project_id)
    assert record is not None
    task_note_by_id = {task.id: task.note for task in record.tasks}
    assert task_note_by_id["task-build"] == "cross-branch rebuilding reason"
    assert task_note_by_id["task-review"] == "cross-branch rebuilding reason"
