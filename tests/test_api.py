import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import clear_auth_service_dependency_caches
from app.api.main import app
from app.schemas.project import ApprovalActionType, ApprovalRequest, ApprovalStatus

client = TestClient(app)


def _actor(actor_id: str, actor_role: str) -> dict[str, str]:
    return {
        "actor_id": actor_id,
        "actor_role": actor_role,
        "actor_type": "human",
    }


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _reset_auth_service_runtime(monkeypatch: pytest.MonkeyPatch):
    clear_auth_service_dependency_caches()
    monkeypatch.setenv("DEV_AUTH_ENABLED", "true")
    monkeypatch.delenv("DEV_AUTH_TOKEN_SEED", raising=False)
    yield
    clear_auth_service_dependency_caches()


def _intake_brief() -> dict:
    intake = client.post(
        "/intake/brief",
        json={
            "user_request": (
                "Title: Internal AI system\n"
                "Scope: backend skeleton\n"
                "Constraints: python, fastapi\n"
                "Success Criteria: health endpoint, tests\n"
                "Deadline: 2026-05-01"
            )
        },
    )
    return intake.json()["brief"]



def test_intake_brief_normalizes_powershell_backtick_newlines() -> None:
    intake = client.post(
        "/intake/brief",
        json={
            "user_request": (
                "Title: Internal AI system`n"
                "Scope: backend skeleton`n"
                "Constraints: python, fastapi`n"
                "Success Criteria: health endpoint, tests`n"
                "Deadline: 2026-05-01"
            )
        },
    )
    assert intake.status_code == 200
    brief = intake.json()["brief"]
    assert brief["title"] == "Internal AI system"
    assert brief["scope"] == "backend skeleton"
    assert brief["constraints"] == ["python", "fastapi"]
    assert brief["success_criteria"] == ["health endpoint", "tests"]
    assert brief["deadline"] == "2026-05-01"
    assert "`n" not in brief["raw_request"]

def _task_note(payload: dict, task_id: str) -> str:
    return next(task["note"] for task in payload["record"]["tasks"] if task["id"] == task_id)


def _runtime_orchestrator():
    return client.app.state.orchestrator


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_orchestrator_endpoint() -> None:
    run = client.post(
        "/orchestrator/run",
        json={"brief": _intake_brief(), "trend_provider": "mock"},
    )
    assert run.status_code == 200
    payload = run.json()
    assert payload["summary"]["status"] == "completed"


def test_orchestrator_endpoint_waits_for_approval_with_gemini_alias_provider() -> None:
    run = client.post(
        "/orchestrator/run",
        json={"brief": _intake_brief(), "trend_provider": "gemini-flash-lite-latest"},
    )
    assert run.status_code == 200
    payload = run.json()
    assert payload["summary"]["status"] == "waiting_approval"


def test_orchestrator_endpoint_unknown_provider_returns_conflict_when_strict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TREND_PROVIDER_STRICT", "true")

    run = client.post(
        "/orchestrator/run",
        json={"brief": _intake_brief(), "trend_provider": "unknown-provider"},
    )

    assert run.status_code == 409
    assert run.json()["detail"] == "Unsupported trend provider: unknown-provider"


def test_orchestrator_endpoint_unknown_provider_returns_conflict_when_strict_env_is_malformed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TREND_PROVIDER_STRICT", "not-a-bool")

    run = client.post(
        "/orchestrator/run",
        json={"brief": _intake_brief(), "trend_provider": "unknown-provider"},
    )

    assert run.status_code == 409
    assert run.json()["detail"] == "Unsupported trend provider: unknown-provider"


def test_orchestrator_endpoint_whitespace_provider_treated_as_mock_when_strict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TREND_PROVIDER_STRICT", "true")

    run = client.post(
        "/orchestrator/run",
        json={"brief": _intake_brief(), "trend_provider": "   "},
    )

    assert run.status_code == 200
    assert run.json()["summary"]["status"] == "completed"


def test_orchestrator_endpoint_mock_provider_runs_when_strict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TREND_PROVIDER_STRICT", "true")

    run = client.post(
        "/orchestrator/run",
        json={"brief": _intake_brief(), "trend_provider": "mock"},
    )

    assert run.status_code == 200
    assert run.json()["summary"]["status"] == "completed"


def test_orchestrator_endpoint_unknown_provider_falls_back_to_mock_when_non_strict() -> None:
    run = client.post(
        "/orchestrator/run",
        json={"brief": _intake_brief(), "trend_provider": "unknown-provider"},
    )

    assert run.status_code == 200
    assert run.json()["summary"]["status"] == "completed"


def test_resume_approval_endpoint_success() -> None:
    waiting = client.post(
        "/orchestrator/run",
        json={"brief": _intake_brief(), "trend_provider": "gemini"},
    )
    project_id = waiting.json()["record"]["project"]["id"]

    resumed = client.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": ["external_api_send"],
            "actor": _actor("approver-1", "approver"),
            "note": "approved",
            "trend_provider": "gemini",
        },
        headers=_auth("dev-approver-token"),
    )
    assert resumed.status_code == 200
    assert resumed.json()["summary"]["status"] == "completed"
    approval_checkpoint = next(
        checkpoint
        for checkpoint in resumed.json()["record"]["checkpoints"]
        if checkpoint["id"] == f"checkpoint-approval-{project_id}"
    )
    assert approval_checkpoint["approved"] is True
    assert approval_checkpoint["approver"] == "approver-1"


def test_resume_approval_endpoint_repeated_after_completion_is_idempotent() -> None:
    waiting = client.post(
        "/orchestrator/run",
        json={"brief": _intake_brief(), "trend_provider": "gemini"},
    )
    project_id = waiting.json()["record"]["project"]["id"]

    first = client.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": ["external_api_send"],
            "trend_provider": "gemini",
        },
        headers=_auth("dev-approver-token"),
    )
    assert first.status_code == 200
    assert first.json()["summary"]["status"] == "completed"

    second = client.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": ["external_api_send"],
            "trend_provider": "gemini",
        },
        headers=_auth("dev-approver-token"),
    )
    assert second.status_code == 200
    payload = second.json()
    assert payload["summary"]["status"] == "completed"
    assert payload["summary"]["next_steps"] == [
        "Project already completed; approval resume request treated as idempotent."
    ]

    audit = client.get(f"/projects/{project_id}/audit")
    approval_approved_events = [
        event
        for event in audit.json()["events"]
        if event["event_type"] == "approval_approved"
    ]
    assert len(approval_approved_events) == 1
    approval_checkpoints = [
        checkpoint
        for checkpoint in audit.json()["checkpoints"]
        if checkpoint["id"] == f"checkpoint-approval-{project_id}"
    ]
    assert len(approval_checkpoints) == 1

    approval_requested_events = [
        event
        for event in audit.json()["events"]
        if event["event_type"] == "approval_requested"
    ]
    requested_action_types = [
        event["metadata"].get("action_type")
        for event in approval_requested_events
    ]
    assert len(requested_action_types) == len(set(requested_action_types))

    approval_action_types = [
        approval["action_type"]
        for approval in audit.json()["approvals"]
    ]
    assert len(approval_action_types) == len(set(approval_action_types))


def test_resume_approval_accepts_whitespace_wrapped_action_names() -> None:
    waiting = client.post(
        "/orchestrator/run",
        json={"brief": _intake_brief(), "trend_provider": "gemini"},
    )
    project_id = waiting.json()["record"]["project"]["id"]

    resumed = client.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": [" external_api_send "],
            "trend_provider": "gemini",
        },
        headers=_auth("dev-approver-token"),
    )
    assert resumed.status_code == 200
    assert resumed.json()["summary"]["status"] == "completed"


def test_resume_approval_accepts_case_insensitive_action_names() -> None:
    waiting = client.post(
        "/orchestrator/run",
        json={"brief": _intake_brief(), "trend_provider": "gemini"},
    )
    project_id = waiting.json()["record"]["project"]["id"]

    resumed = client.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": ["EXTERNAL_API_SEND"],
            "trend_provider": "gemini",
        },
        headers=_auth("dev-approver-token"),
    )
    assert resumed.status_code == 200
    assert resumed.json()["summary"]["status"] == "completed"


def test_resume_approval_endpoint_supports_partial_approval_until_all_pending_actions_are_approved(
) -> None:
    waiting = client.post(
        "/orchestrator/run",
        json={"brief": _intake_brief(), "trend_provider": "gemini"},
    )
    project_id = waiting.json()["record"]["project"]["id"]
    record = _runtime_orchestrator().repository.get(project_id)
    assert record is not None
    record.approvals.append(
        ApprovalRequest(
            id="approval-bulk-modify-api-partial",
            action_type=ApprovalActionType.BULK_MODIFY,
            status=ApprovalStatus.PENDING,
            reason="Bulk modify requires explicit approval.",
            requested_by="system",
        )
    )
    _runtime_orchestrator().repository.save(record)

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
    partial_payload = partial.json()
    assert partial_payload["summary"]["status"] == "waiting_approval"
    assert partial_payload["summary"]["next_steps"][0] == (
        "Approve remaining action(s): bulk_modify."
    )

    completed = client.post(
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

    audit = client.get(f"/projects/{project_id}/audit")
    partial_resume_events = [
        event
        for event in audit.json()["events"]
        if event["event_type"] == "resume_triggered"
        and event["metadata"].get("mode") == "approval_resume_partial"
    ]
    assert len(partial_resume_events) == 1


def test_resume_approval_endpoint_repeated_partial_call_is_idempotent(
) -> None:
    waiting = client.post(
        "/orchestrator/run",
        json={"brief": _intake_brief(), "trend_provider": "gemini"},
    )
    project_id = waiting.json()["record"]["project"]["id"]
    record = _runtime_orchestrator().repository.get(project_id)
    assert record is not None
    record.approvals.append(
        ApprovalRequest(
            id="approval-bulk-modify-api-partial-repeat",
            action_type=ApprovalActionType.BULK_MODIFY,
            status=ApprovalStatus.PENDING,
            reason="Bulk modify requires explicit approval.",
            requested_by="system",
        )
    )
    _runtime_orchestrator().repository.save(record)

    first_partial = client.post(
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

    second_partial = client.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": ["external_api_send"],
            "trend_provider": "gemini",
        },
        headers=_auth("dev-approver-token"),
    )
    assert second_partial.status_code == 200
    assert second_partial.json()["summary"]["status"] == "waiting_approval"

    audit = client.get(f"/projects/{project_id}/audit")
    partial_resume_events = [
        event
        for event in audit.json()["events"]
        if event["event_type"] == "resume_triggered"
        and event["metadata"].get("mode") == "approval_resume_partial"
    ]
    approval_approved_events = [
        event
        for event in audit.json()["events"]
        if event["event_type"] == "approval_approved"
    ]
    assert len(partial_resume_events) == 1
    assert len(approval_approved_events) == 1


def test_resume_approval_endpoint_partial_next_step_includes_all_remaining_actions() -> None:
    waiting = client.post(
        "/orchestrator/run",
        json={"brief": _intake_brief(), "trend_provider": "gemini"},
    )
    project_id = waiting.json()["record"]["project"]["id"]
    record = _runtime_orchestrator().repository.get(project_id)
    assert record is not None
    record.approvals.extend(
        [
            ApprovalRequest(
                id="approval-bulk-modify-api-partial-next-steps",
                action_type=ApprovalActionType.BULK_MODIFY,
                status=ApprovalStatus.PENDING,
                reason="Bulk modify requires explicit approval.",
                requested_by="system",
            ),
            ApprovalRequest(
                id="approval-destructive-change-api-partial-next-steps",
                action_type=ApprovalActionType.DESTRUCTIVE_CHANGE,
                status=ApprovalStatus.PENDING,
                reason="Destructive change requires explicit approval.",
                requested_by="system",
            ),
        ]
    )
    _runtime_orchestrator().repository.save(record)

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
    partial_payload = partial.json()
    assert partial_payload["summary"]["status"] == "waiting_approval"
    assert partial_payload["summary"]["next_steps"][0] == (
        "Approve remaining action(s): bulk_modify, destructive_change."
    )
    assert partial_payload["summary"]["next_steps"][1] == (
        'Call approval resume API with `approved_actions=["bulk_modify", "destructive_change"]`.'
    )


def test_resume_approval_returns_conflict_for_invalid_action_value() -> None:
    waiting = client.post(
        "/orchestrator/run",
        json={"brief": _intake_brief(), "trend_provider": "gemini"},
    )
    project_id = waiting.json()["record"]["project"]["id"]

    resumed = client.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": ["not_real_action"],
            "trend_provider": "gemini",
        },
        headers=_auth("dev-approver-token"),
    )
    assert resumed.status_code == 409
    assert "Unsupported approval action value" in resumed.json()["detail"]


def test_resume_approval_invalid_state_takes_precedence_over_invalid_action_value() -> None:
    waiting = client.post(
        "/orchestrator/run",
        json={"brief": _intake_brief(), "trend_provider": "gemini"},
    )
    project_id = waiting.json()["record"]["project"]["id"]
    rejected = client.post(
        "/orchestrator/approval/reject",
        json={
            "project_id": project_id,
            "rejected_actions": ["external_api_send"],
            "reason": "reject first",
        },
        headers=_auth("dev-approver-token"),
    )
    assert rejected.status_code == 200

    resumed = client.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": ["not_real_action"],
            "trend_provider": "gemini",
        },
        headers=_auth("dev-approver-token"),
    )
    assert resumed.status_code == 409
    assert "current: revision_requested" in resumed.json()["detail"]


def test_resume_approval_endpoint_authorization_failure() -> None:
    waiting = client.post(
        "/orchestrator/run",
        json={"brief": _intake_brief(), "trend_provider": "gemini"},
    )
    project_id = waiting.json()["record"]["project"]["id"]

    resumed = client.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": ["external_api_send"],
            "actor": _actor("viewer-1", "viewer"),
            "trend_provider": "gemini",
        },
        headers=_auth("dev-viewer-token"),
    )
    assert resumed.status_code == 403


def test_resume_approval_endpoint_rejects_unauthenticated() -> None:
    waiting = client.post(
        "/orchestrator/run",
        json={"brief": _intake_brief(), "trend_provider": "gemini"},
    )
    project_id = waiting.json()["record"]["project"]["id"]

    resumed = client.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": ["external_api_send"],
        },
    )
    assert resumed.status_code == 401
    audit = client.get(f"/projects/{project_id}/audit")
    assert any(
        event["event_type"] == "authentication_failed"
        for event in audit.json()["events"]
    )


def test_reject_approval_endpoint() -> None:
    waiting = client.post(
        "/orchestrator/run",
        json={"brief": _intake_brief(), "trend_provider": "gemini"},
    )
    project_id = waiting.json()["record"]["project"]["id"]

    rejected = client.post(
        "/orchestrator/approval/reject",
        json={
            "project_id": project_id,
            "rejected_actions": ["external_api_send"],
            "actor": _actor("approver-1", "approver"),
            "reason": "External call denied",
        },
        headers=_auth("dev-approver-token"),
    )
    assert rejected.status_code == 200
    assert rejected.json()["summary"]["status"] == "revision_requested"
    approval_checkpoint = next(
        checkpoint
        for checkpoint in rejected.json()["record"]["checkpoints"]
        if checkpoint["id"] == f"checkpoint-approval-{project_id}"
    )
    assert approval_checkpoint["approved"] is False
    assert approval_checkpoint["approver"] == "approver-1"


def test_reject_approval_endpoint_auto_closes_other_pending_actions_when_subset_is_rejected(
) -> None:
    waiting = client.post(
        "/orchestrator/run",
        json={"brief": _intake_brief(), "trend_provider": "gemini"},
    )
    project_id = waiting.json()["record"]["project"]["id"]
    record = _runtime_orchestrator().repository.get(project_id)
    assert record is not None
    record.approvals.append(
        ApprovalRequest(
            id="approval-bulk-modify-api-reject-subset",
            action_type=ApprovalActionType.BULK_MODIFY,
            status=ApprovalStatus.PENDING,
            reason="Bulk modify requires explicit approval.",
            requested_by="system",
        )
    )
    _runtime_orchestrator().repository.save(record)

    rejected = client.post(
        "/orchestrator/approval/reject",
        json={
            "project_id": project_id,
            "rejected_actions": ["external_api_send"],
            "reason": "Reject one action and close remainder",
        },
        headers=_auth("dev-approver-token"),
    )
    assert rejected.status_code == 200
    assert rejected.json()["summary"]["status"] == "revision_requested"

    audit = client.get(f"/projects/{project_id}/audit").json()
    approval_status_by_action = {
        approval["action_type"]: approval["status"] for approval in audit["approvals"]
    }
    assert approval_status_by_action["external_api_send"] == "rejected"
    assert approval_status_by_action["bulk_modify"] == "rejected"

    rejected_events = [
        event for event in audit["events"] if event["event_type"] == "approval_rejected"
    ]
    assert len(rejected_events) == 2
    assert any(event["metadata"].get("auto_closed") is True for event in rejected_events)


def test_reject_approval_endpoint_subset_requires_authorization_for_all_pending_actions(
) -> None:
    waiting = client.post(
        "/orchestrator/run",
        json={"brief": _intake_brief(), "trend_provider": "gemini"},
    )
    project_id = waiting.json()["record"]["project"]["id"]
    record = _runtime_orchestrator().repository.get(project_id)
    assert record is not None
    record.approvals.append(
        ApprovalRequest(
            id="approval-production-admin-only-api-reject-subset",
            action_type=ApprovalActionType.PRODUCTION_AFFECTING_CHANGE,
            status=ApprovalStatus.PENDING,
            reason="Production change requires admin approval.",
            requested_by="system",
        )
    )
    _runtime_orchestrator().repository.save(record)

    rejected = client.post(
        "/orchestrator/approval/reject",
        json={
            "project_id": project_id,
            "rejected_actions": ["external_api_send"],
            "reason": "Reject subset without admin role.",
        },
        headers=_auth("dev-approver-token"),
    )
    assert rejected.status_code == 403

    audit = client.get(f"/projects/{project_id}/audit").json()
    assert audit["status"] == "waiting_approval"
    assert any(
        event["event_type"] == "authorization_failed"
        and event["metadata"].get("action_type") == "production_affecting_change"
        for event in audit["events"]
    )


def test_reject_approval_endpoint_repeated_is_idempotent() -> None:
    waiting = client.post(
        "/orchestrator/run",
        json={"brief": _intake_brief(), "trend_provider": "gemini"},
    )
    project_id = waiting.json()["record"]["project"]["id"]

    first = client.post(
        "/orchestrator/approval/reject",
        json={
            "project_id": project_id,
            "rejected_actions": ["external_api_send"],
            "reason": "External call denied",
        },
        headers=_auth("dev-approver-token"),
    )
    assert first.status_code == 200
    assert first.json()["summary"]["status"] == "revision_requested"

    second = client.post(
        "/orchestrator/approval/reject",
        json={
            "project_id": project_id,
            "rejected_actions": ["external_api_send"],
            "reason": "External call denied",
        },
        headers=_auth("dev-approver-token"),
    )
    assert second.status_code == 200
    assert second.json()["summary"]["status"] == "revision_requested"

    audit = client.get(f"/projects/{project_id}/audit")
    approval_rejected_events = [
        event
        for event in audit.json()["events"]
        if event["event_type"] == "approval_rejected"
    ]
    assert len(approval_rejected_events) == 1


def test_reject_approval_endpoint_trims_reason_and_note_in_audit() -> None:
    waiting = client.post(
        "/orchestrator/run",
        json={"brief": _intake_brief(), "trend_provider": "gemini"},
    )
    project_id = waiting.json()["record"]["project"]["id"]

    rejected = client.post(
        "/orchestrator/approval/reject",
        json={
            "project_id": project_id,
            "rejected_actions": ["external_api_send"],
            "reason": "  External call denied  ",
            "note": "  escalated to revision lane  ",
        },
        headers=_auth("dev-approver-token"),
    )
    assert rejected.status_code == 200
    payload = rejected.json()
    assert payload["summary"]["status"] == "revision_requested"
    trend_task_note = _task_note(payload, "task-trend")
    assert trend_task_note == "External call denied"

    audit = client.get(f"/projects/{project_id}/audit").json()
    rejected_approval = next(
        approval
        for approval in audit["approvals"]
        if approval["action_type"] == "external_api_send"
    )
    assert (
        rejected_approval["decision_note"] == "External call denied escalated to revision lane"
    )

    rejected_event = next(
        event for event in audit["events"] if event["event_type"] == "approval_rejected"
    )
    assert rejected_event["reason"] == "External call denied"
    assert rejected_event["metadata"].get("note") == "escalated to revision lane"


def test_reject_approval_invalid_state_takes_precedence_over_invalid_action_value() -> None:
    completed = client.post(
        "/orchestrator/run",
        json={"brief": _intake_brief(), "trend_provider": "mock"},
    )
    project_id = completed.json()["record"]["project"]["id"]

    rejected = client.post(
        "/orchestrator/approval/reject",
        json={
            "project_id": project_id,
            "rejected_actions": ["not_real_action"],
            "reason": "invalid state first",
        },
        headers=_auth("dev-approver-token"),
    )
    assert rejected.status_code == 409
    assert "current: completed" in rejected.json()["detail"]


def test_reject_approval_defaults_to_pending_actions_when_actions_omitted() -> None:
    waiting = client.post(
        "/orchestrator/run",
        json={"brief": _intake_brief(), "trend_provider": "gemini"},
    )
    project_id = waiting.json()["record"]["project"]["id"]

    rejected = client.post(
        "/orchestrator/approval/reject",
        json={
            "project_id": project_id,
            "reason": "reject all pending by default",
        },
        headers=_auth("dev-approver-token"),
    )
    assert rejected.status_code == 200
    assert rejected.json()["summary"]["status"] == "revision_requested"


def test_resume_approval_requires_actions_when_omitted() -> None:
    waiting = client.post(
        "/orchestrator/run",
        json={"brief": _intake_brief(), "trend_provider": "gemini"},
    )
    project_id = waiting.json()["record"]["project"]["id"]

    resumed = client.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "trend_provider": "gemini",
        },
        headers=_auth("dev-approver-token"),
    )
    assert resumed.status_code == 409
    assert resumed.json()["detail"] == "approved_actions is required."


def test_resume_revision_then_start_replanning() -> None:
    revision = client.post(
        "/orchestrator/run",
        json={
            "brief": _intake_brief(),
            "trend_provider": "mock",
            "simulate_review_failure": True,
        },
    )
    project_id = revision.json()["record"]["project"]["id"]

    ready = client.post(
        "/orchestrator/resume/revision",
        json={
            "project_id": project_id,
            "resume_mode": "replanning",
            "actor": _actor("operator-1", "operator"),
            "reason": "Need replanning",
        },
        headers=_auth("dev-operator-token"),
    )
    assert ready.status_code == 200
    assert ready.json()["summary"]["status"] == "ready_for_planning"

    start = client.post(
        "/orchestrator/replanning/start",
        json={
            "project_id": project_id,
            "actor": _actor("operator-1", "operator"),
            "note": "execute replanning",
            "trend_provider": "mock",
        },
        headers=_auth("dev-operator-token"),
    )
    assert start.status_code == 200
    assert start.json()["summary"]["status"] == "completed"
    assert start.json()["summary"]["artifact_count"] == 4
    artifact_ids = [artifact["id"] for artifact in start.json()["record"]["artifacts"]]
    assert len(artifact_ids) == len(set(artifact_ids))
    assert sorted(artifact["task_id"] for artifact in start.json()["record"]["artifacts"]) == [
        "task-build",
        "task-design",
        "task-research",
        "task-trend",
    ]


def test_resume_revision_replanning_endpoint_repeated_in_ready_state_is_idempotent() -> None:
    revision = client.post(
        "/orchestrator/run",
        json={
            "brief": _intake_brief(),
            "trend_provider": "mock",
            "simulate_review_failure": True,
        },
    )
    project_id = revision.json()["record"]["project"]["id"]

    first = client.post(
        "/orchestrator/resume/revision",
        json={
            "project_id": project_id,
            "resume_mode": "replanning",
            "reason": "Need replanning",
        },
        headers=_auth("dev-operator-token"),
    )
    assert first.status_code == 200
    assert first.json()["summary"]["status"] == "ready_for_planning"

    second = client.post(
        "/orchestrator/resume/revision",
        json={
            "project_id": project_id,
            "resume_mode": "replanning",
            "reason": "Need replanning",
        },
        headers=_auth("dev-operator-token"),
    )
    assert second.status_code == 200
    payload = second.json()
    assert payload["summary"]["status"] == "ready_for_planning"
    assert payload["summary"]["next_steps"] == [
        "Call replanning start API to begin execution from ready_for_planning."
    ]

    audit = client.get(f"/projects/{project_id}/audit")
    replanning_resume_events = [
        event
        for event in audit.json()["events"]
        if event["event_type"] == "resume_triggered"
        and event["metadata"].get("mode") == "replanning"
    ]
    assert len(replanning_resume_events) == 1


def test_start_replanning_invalid_state() -> None:
    completed = client.post(
        "/orchestrator/run",
        json={"brief": _intake_brief(), "trend_provider": "mock"},
    )
    project_id = completed.json()["record"]["project"]["id"]

    start = client.post(
        "/orchestrator/replanning/start",
        json={
            "project_id": project_id,
            "actor": _actor("operator-1", "operator"),
            "note": "should fail",
        },
        headers=_auth("dev-operator-token"),
    )
    assert start.status_code == 409


def test_start_replanning_repeated_after_completion_is_idempotent() -> None:
    revision = client.post(
        "/orchestrator/run",
        json={
            "brief": _intake_brief(),
            "trend_provider": "mock",
            "simulate_review_failure": True,
        },
    )
    project_id = revision.json()["record"]["project"]["id"]
    ready = client.post(
        "/orchestrator/resume/revision",
        json={
            "project_id": project_id,
            "resume_mode": "replanning",
            "reason": "Need replanning",
        },
        headers=_auth("dev-operator-token"),
    )
    assert ready.status_code == 200

    first = client.post(
        "/orchestrator/replanning/start",
        json={
            "project_id": project_id,
            "note": "start replanning",
            "trend_provider": "mock",
        },
        headers=_auth("dev-operator-token"),
    )
    assert first.status_code == 200
    assert first.json()["summary"]["status"] == "completed"

    second = client.post(
        "/orchestrator/replanning/start",
        json={
            "project_id": project_id,
            "note": "retry replanning start",
            "trend_provider": "mock",
        },
        headers=_auth("dev-operator-token"),
    )
    assert second.status_code == 200
    payload = second.json()
    assert payload["summary"]["status"] == "completed"
    assert payload["summary"]["next_steps"] == [
        "Project already completed; replanning start request treated as idempotent."
    ]

    audit = client.get(f"/projects/{project_id}/audit")
    replanning_start_events = [
        event
        for event in audit.json()["events"]
        if event["event_type"] == "replanning_started"
    ]
    assert len(replanning_start_events) == 1
    delivery_checkpoints = [
        checkpoint
        for checkpoint in audit.json()["checkpoints"]
        if checkpoint["id"] == f"checkpoint-{project_id}"
    ]
    assert len(delivery_checkpoints) == 1
    delivery_checkpoints = [
        checkpoint
        for checkpoint in audit.json()["checkpoints"]
        if checkpoint["id"] == f"checkpoint-{project_id}"
    ]
    assert len(delivery_checkpoints) == 1


def test_resume_revision_rebuilding_path() -> None:
    revision = client.post(
        "/orchestrator/run",
        json={
            "brief": _intake_brief(),
            "trend_provider": "mock",
            "simulate_review_failure": True,
        },
    )
    project_id = revision.json()["record"]["project"]["id"]

    resumed = client.post(
        "/orchestrator/resume/revision",
        json={
            "project_id": project_id,
            "resume_mode": "rebuilding",
            "reason": "Rebuild only",
        },
        headers=_auth("dev-operator-token"),
    )
    assert resumed.status_code == 200
    payload = resumed.json()
    assert payload["summary"]["status"] == "completed"
    assert _task_note(payload, "task-build") == "Rebuild only"
    assert _task_note(payload, "task-review") == "Rebuild only"


def test_resume_revision_rebuilding_endpoint_repeated_after_completion_is_idempotent() -> None:
    revision = client.post(
        "/orchestrator/run",
        json={
            "brief": _intake_brief(),
            "trend_provider": "mock",
            "simulate_review_failure": True,
        },
    )
    project_id = revision.json()["record"]["project"]["id"]

    first = client.post(
        "/orchestrator/resume/revision",
        json={
            "project_id": project_id,
            "resume_mode": "rebuilding",
            "reason": "Rebuild only",
        },
        headers=_auth("dev-operator-token"),
    )
    assert first.status_code == 200
    assert first.json()["summary"]["status"] == "completed"

    second = client.post(
        "/orchestrator/resume/revision",
        json={
            "project_id": project_id,
            "resume_mode": "rebuilding",
            "reason": "Rebuild only",
        },
        headers=_auth("dev-operator-token"),
    )
    assert second.status_code == 200
    payload = second.json()
    assert payload["summary"]["status"] == "completed"
    assert payload["summary"]["next_steps"] == [
        "Project already completed; revision resume request treated as idempotent."
    ]

    audit = client.get(f"/projects/{project_id}/audit")
    rebuilding_resume_events = [
        event
        for event in audit.json()["events"]
        if event["event_type"] == "resume_triggered"
        and event["metadata"].get("mode") == "rebuilding"
    ]
    assert len(rebuilding_resume_events) == 1


def test_resume_revision_rereview_path() -> None:
    revision = client.post(
        "/orchestrator/run",
        json={
            "brief": _intake_brief(),
            "trend_provider": "mock",
            "simulate_review_failure": True,
        },
    )
    project_id = revision.json()["record"]["project"]["id"]

    resumed = client.post(
        "/orchestrator/resume/revision",
        json={
            "project_id": project_id,
            "resume_mode": "rereview",
            "reason": "Re-run review",
        },
        headers=_auth("dev-operator-token"),
    )
    assert resumed.status_code == 200
    payload = resumed.json()
    assert payload["summary"]["status"] == "completed"
    assert _task_note(payload, "task-review") == "Re-run review"
    assert _task_note(payload, "task-build") == ""


def test_resume_revision_rereview_endpoint_repeated_after_completion_is_idempotent() -> None:
    revision = client.post(
        "/orchestrator/run",
        json={
            "brief": _intake_brief(),
            "trend_provider": "mock",
            "simulate_review_failure": True,
        },
    )
    project_id = revision.json()["record"]["project"]["id"]

    first = client.post(
        "/orchestrator/resume/revision",
        json={
            "project_id": project_id,
            "resume_mode": "rereview",
            "reason": "Re-run review",
        },
        headers=_auth("dev-operator-token"),
    )
    assert first.status_code == 200
    assert first.json()["summary"]["status"] == "completed"

    second = client.post(
        "/orchestrator/resume/revision",
        json={
            "project_id": project_id,
            "resume_mode": "rereview",
            "reason": "Re-run review",
        },
        headers=_auth("dev-operator-token"),
    )
    assert second.status_code == 200
    payload = second.json()
    assert payload["summary"]["status"] == "completed"
    assert payload["summary"]["next_steps"] == [
        "Project already completed; revision resume request treated as idempotent."
    ]

    audit = client.get(f"/projects/{project_id}/audit")
    rereview_resume_events = [
        event
        for event in audit.json()["events"]
        if event["event_type"] == "resume_triggered"
        and event["metadata"].get("mode") == "rereview"
    ]
    assert len(rereview_resume_events) == 1


def test_start_replanning_without_reset_preserves_existing_notes() -> None:
    revision = client.post(
        "/orchestrator/run",
        json={
            "brief": _intake_brief(),
            "trend_provider": "mock",
            "simulate_review_failure": True,
        },
    )
    project_id = revision.json()["record"]["project"]["id"]
    ready = client.post(
        "/orchestrator/resume/revision",
        json={
            "project_id": project_id,
            "resume_mode": "replanning",
            "reason": "Prepare lane",
        },
        headers=_auth("dev-operator-token"),
    )
    assert ready.status_code == 200

    restarted = client.post(
        "/orchestrator/replanning/start",
        json={
            "project_id": project_id,
            "note": "do not reset",
            "trend_provider": "mock",
            "reset_downstream_tasks": False,
        },
        headers=_auth("dev-operator-token"),
    )
    assert restarted.status_code == 200
    payload = restarted.json()
    assert payload["summary"]["status"] == "completed"
    assert _task_note(payload, "task-design") == "Prepare lane"
    assert _task_note(payload, "task-build") == "Prepare lane"


def test_project_audit_endpoint_contains_events() -> None:
    run = client.post(
        "/orchestrator/run",
        json={"brief": _intake_brief(), "trend_provider": "mock"},
    )
    project_id = run.json()["record"]["project"]["id"]

    audit = client.get(f"/projects/{project_id}/audit")
    assert audit.status_code == 200
    payload = audit.json()
    assert payload["project_id"] == project_id
    assert payload["events"]


def test_project_audit_endpoint_returns_404_for_missing_project() -> None:
    audit = client.get("/projects/missing-project/audit")
    assert audit.status_code == 404
    assert "Project not found: missing-project" in audit.json()["detail"]


@pytest.mark.parametrize(
    ("path", "payload", "token"),
    [
        (
            "/orchestrator/resume/approval",
            {"project_id": "missing-project", "approved_actions": ["external_api_send"]},
            "dev-approver-token",
        ),
        (
            "/orchestrator/approval/reject",
            {
                "project_id": "missing-project",
                "rejected_actions": ["external_api_send"],
                "reason": "missing project test",
            },
            "dev-approver-token",
        ),
        (
            "/orchestrator/resume/revision",
            {"project_id": "missing-project", "resume_mode": "replanning", "reason": "retry"},
            "dev-operator-token",
        ),
        (
            "/orchestrator/replanning/start",
            {"project_id": "missing-project", "note": "retry"},
            "dev-operator-token",
        ),
    ],
)
def test_protected_endpoints_return_404_for_missing_project(
    path: str,
    payload: dict,
    token: str,
) -> None:
    response = client.post(path, json=payload, headers=_auth(token))

    assert response.status_code == 404
    assert "Project not found: missing-project" in response.json()["detail"]


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (
            "/orchestrator/resume/approval",
            {"project_id": "missing-project", "approved_actions": ["external_api_send"]},
        ),
        (
            "/orchestrator/approval/reject",
            {
                "project_id": "missing-project",
                "rejected_actions": ["external_api_send"],
                "reason": "missing project test",
            },
        ),
        (
            "/orchestrator/resume/revision",
            {"project_id": "missing-project", "resume_mode": "replanning", "reason": "retry"},
        ),
        (
            "/orchestrator/replanning/start",
            {"project_id": "missing-project", "note": "retry"},
        ),
    ],
)
def test_protected_endpoints_return_401_before_missing_project_lookup_when_token_invalid(
    path: str,
    payload: dict,
) -> None:
    response = client.post(path, json=payload, headers=_auth("invalid-token"))

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid bearer token."


def test_body_actor_tampering_is_ignored() -> None:
    waiting = client.post(
        "/orchestrator/run",
        json={"brief": _intake_brief(), "trend_provider": "gemini"},
    )
    project_id = waiting.json()["record"]["project"]["id"]

    resumed = client.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": ["external_api_send"],
            "actor": _actor("forged-admin", "admin"),
            "trend_provider": "gemini",
        },
        headers=_auth("dev-approver-token"),
    )
    assert resumed.status_code == 200
    audit = client.get(f"/projects/{project_id}/audit")
    assert any(
        event["event_type"] == "actor_resolved" and event["actor"] == "approver-1"
        for event in audit.json()["events"]
    )


def test_reject_approval_body_actor_tampering_is_ignored() -> None:
    waiting = client.post(
        "/orchestrator/run",
        json={"brief": _intake_brief(), "trend_provider": "gemini"},
    )
    project_id = waiting.json()["record"]["project"]["id"]

    rejected = client.post(
        "/orchestrator/approval/reject",
        json={
            "project_id": project_id,
            "rejected_actions": ["external_api_send"],
            "actor": _actor("forged-admin", "admin"),
            "reason": "deny external call",
        },
        headers=_auth("dev-approver-token"),
    )
    assert rejected.status_code == 200
    audit = client.get(f"/projects/{project_id}/audit")
    assert any(
        event["event_type"] == "actor_resolved" and event["actor"] == "approver-1"
        for event in audit.json()["events"]
    )


def test_resume_revision_body_actor_tampering_is_ignored() -> None:
    revision = client.post(
        "/orchestrator/run",
        json={
            "brief": _intake_brief(),
            "trend_provider": "mock",
            "simulate_review_failure": True,
        },
    )
    project_id = revision.json()["record"]["project"]["id"]

    resumed = client.post(
        "/orchestrator/resume/revision",
        json={
            "project_id": project_id,
            "resume_mode": "replanning",
            "actor": _actor("forged-admin", "admin"),
            "reason": "resume with forged actor body",
        },
        headers=_auth("dev-operator-token"),
    )
    assert resumed.status_code == 200
    audit = client.get(f"/projects/{project_id}/audit")
    assert any(
        event["event_type"] == "actor_resolved" and event["actor"] == "operator-1"
        for event in audit.json()["events"]
    )


def test_start_replanning_body_actor_tampering_is_ignored() -> None:
    revision = client.post(
        "/orchestrator/run",
        json={
            "brief": _intake_brief(),
            "trend_provider": "mock",
            "simulate_review_failure": True,
        },
    )
    project_id = revision.json()["record"]["project"]["id"]
    ready = client.post(
        "/orchestrator/resume/revision",
        json={
            "project_id": project_id,
            "resume_mode": "replanning",
            "reason": "prepare start",
        },
        headers=_auth("dev-operator-token"),
    )
    assert ready.status_code == 200

    started = client.post(
        "/orchestrator/replanning/start",
        json={
            "project_id": project_id,
            "actor": _actor("forged-admin", "admin"),
            "note": "start with forged body actor",
        },
        headers=_auth("dev-operator-token"),
    )
    assert started.status_code == 200
    audit = client.get(f"/projects/{project_id}/audit")
    assert any(
        event["event_type"] == "actor_resolved" and event["actor"] == "operator-1"
        for event in audit.json()["events"]
    )


def test_reject_approval_with_unknown_action_returns_conflict_and_keeps_waiting() -> None:
    waiting = client.post(
        "/orchestrator/run",
        json={"brief": _intake_brief(), "trend_provider": "gemini"},
    )
    project_id = waiting.json()["record"]["project"]["id"]

    rejected = client.post(
        "/orchestrator/approval/reject",
        json={
            "project_id": project_id,
            "rejected_actions": ["destructive_change"],
            "reason": "reject unknown action",
        },
        headers=_auth("dev-approver-token"),
    )
    assert rejected.status_code == 409

    audit = client.get(f"/projects/{project_id}/audit")
    assert audit.status_code == 200
    payload = audit.json()
    assert payload["status"] == "waiting_approval"
    assert any(
        event["event_type"] == "actor_resolved" and event["actor"] == "approver-1"
        for event in payload["events"]
    )


def test_project_policy_override_blocks_unlisted_actor() -> None:
    waiting = client.post(
        "/orchestrator/run",
        json={
            "brief": _intake_brief(),
            "trend_provider": "gemini",
            "project_policy": {
                "project_owner_actor_id": "owner-1",
                "strict_mode": True,
                "action_rules": {
                    "external_api_send": {
                        "allowed_roles": ["approver"],
                        "allowed_actor_ids": ["another-approver"],
                    }
                },
            },
        },
    )
    project_id = waiting.json()["record"]["project"]["id"]

    resumed = client.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": ["external_api_send"],
        },
        headers=_auth("dev-approver-token"),
    )
    assert resumed.status_code == 403


def test_project_policy_override_allows_listed_actor() -> None:
    waiting = client.post(
        "/orchestrator/run",
        json={
            "brief": _intake_brief(),
            "trend_provider": "gemini",
            "project_policy": {
                "project_owner_actor_id": "owner-1",
                "strict_mode": True,
                "action_rules": {
                    "external_api_send": {
                        "allowed_roles": ["approver"],
                        "allowed_actor_ids": ["approver-1"],
                    }
                },
            },
        },
    )
    project_id = waiting.json()["record"]["project"]["id"]

    resumed = client.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": ["external_api_send"],
            "trend_provider": "gemini",
        },
        headers=_auth("dev-approver-token"),
    )
    assert resumed.status_code == 200
    assert resumed.json()["summary"]["status"] == "completed"

