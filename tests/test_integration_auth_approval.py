from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import dependencies, routes
from app.api.dependencies import clear_auth_service_dependency_caches
from app.api.main import create_app
from app.api.runtime_bindings import bind_orchestrator_binding
from app.orchestrator.service import PMOrchestrator
from app.schemas.project import (
    ApprovalActionType,
    ApprovalRequest,
    ApprovalStatus,
    ProjectStatus,
    RevisionResumeMode,
)
from app.state.repository import InMemoryProjectRepository


def _clear_auth_caches() -> None:
    clear_auth_service_dependency_caches()


def _intake_brief(client: TestClient) -> dict:
    intake = client.post(
        "/intake/brief",
        json={
            "user_request": (
                "Title: Integration flow\n"
                "Scope: approval route behavior\n"
                "Constraints: python, fastapi\n"
                "Success Criteria: deterministic API behavior\n"
                "Deadline: 2026-06-15"
            )
        },
    )
    assert intake.status_code == 200
    return intake.json()["brief"]


def _run_waiting_approval_project(client: TestClient, project_policy: dict | None = None) -> str:
    run_payload: dict = {
        "brief": _intake_brief(client),
        "trend_provider": "gemini",
    }
    if project_policy is not None:
        run_payload["project_policy"] = project_policy
    run = client.post("/orchestrator/run", json=run_payload)
    assert run.status_code == 200
    project = run.json()
    assert project["summary"]["status"] == "waiting_approval"
    return project["record"]["project"]["id"]


def _run_completed_project(client: TestClient) -> str:
    run = client.post(
        "/orchestrator/run",
        json={"brief": _intake_brief(client), "trend_provider": "mock"},
    )
    assert run.status_code == 200
    project = run.json()
    assert project["summary"]["status"] == "completed"
    return project["record"]["project"]["id"]


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
    project = run.json()
    assert project["summary"]["status"] == "revision_requested"
    return project["record"]["project"]["id"]


def _client_with_shared_repository_and_seed(
    monkeypatch,
    repository: InMemoryProjectRepository,
    token_seed: str,
    *,
    dev_auth_enabled: str = "true",
) -> TestClient:
    monkeypatch.setenv("DEV_AUTH_ENABLED", dev_auth_enabled)
    monkeypatch.setenv("DEV_AUTH_TOKEN_SEED", token_seed)
    app = create_app()
    app_orchestrator = PMOrchestrator(repository=repository)
    bind_orchestrator_binding(app, orchestrator=app_orchestrator)
    return TestClient(app)


def _drop_app_auth_bindings(
    client: TestClient,
    *,
    drop_app_snapshot: bool = False,
    drop_state_bootstrap_snapshot: bool = False,
    drop_app_bootstrap_snapshot: bool = False,
) -> None:
    for attr in ("auth_service", "_initial_auth_service"):
        if hasattr(client.app.state, attr):
            delattr(client.app.state, attr)
    if drop_state_bootstrap_snapshot and hasattr(client.app.state, "_bootstrap_auth_service"):
        delattr(client.app.state, "_bootstrap_auth_service")
    if drop_app_snapshot and hasattr(client.app, "_initial_auth_service"):
        delattr(client.app, "_initial_auth_service")
    if drop_app_bootstrap_snapshot and hasattr(client.app, "_bootstrap_auth_service"):
        delattr(client.app, "_bootstrap_auth_service")


def _drop_app_orchestrator_bindings(
    client: TestClient,
    *,
    drop_app_snapshot: bool = False,
    drop_state_bootstrap_snapshot: bool = False,
    drop_app_bootstrap_snapshot: bool = False,
) -> None:
    if hasattr(client.app.state, "orchestrator"):
        delattr(client.app.state, "orchestrator")
    if hasattr(client.app.state, "_initial_orchestrator"):
        delattr(client.app.state, "_initial_orchestrator")
    if drop_state_bootstrap_snapshot and hasattr(client.app.state, "_bootstrap_orchestrator"):
        delattr(client.app.state, "_bootstrap_orchestrator")
    if drop_app_snapshot and hasattr(client.app, "_initial_orchestrator"):
        delattr(client.app, "_initial_orchestrator")
    if drop_app_bootstrap_snapshot and hasattr(client.app, "_bootstrap_orchestrator"):
        delattr(client.app, "_bootstrap_orchestrator")


def _drop_app_runtime_bindings(
    client: TestClient,
    *,
    drop_app_auth_snapshot: bool = False,
    drop_app_orchestrator_snapshot: bool = False,
    drop_state_bootstrap_snapshots: bool = False,
    drop_app_bootstrap_snapshots: bool = False,
) -> None:
    _drop_app_auth_bindings(
        client,
        drop_app_snapshot=drop_app_auth_snapshot,
        drop_state_bootstrap_snapshot=drop_state_bootstrap_snapshots,
        drop_app_bootstrap_snapshot=drop_app_bootstrap_snapshots,
    )
    _drop_app_orchestrator_bindings(
        client,
        drop_app_snapshot=drop_app_orchestrator_snapshot,
        drop_state_bootstrap_snapshot=drop_state_bootstrap_snapshots,
        drop_app_bootstrap_snapshot=drop_app_bootstrap_snapshots,
    )


def _request_for_client(client: TestClient) -> SimpleNamespace:
    return SimpleNamespace(app=client.app)


def _direct_outcome_with_authenticated_actor(
    client: TestClient,
    *,
    project_id: str,
    token: str | None,
    action,
) -> tuple[int, str]:
    request = _request_for_client(client)
    runtime_orchestrator = routes._get_orchestrator(request)
    auth_service = dependencies.get_auth_service_dependency(request)
    authorization = f"Bearer {token}" if token is not None else None
    try:
        result = routes._run_with_authenticated_actor(
            project_id=project_id,
            authorization=authorization,
            auth_service=auth_service,
            action=lambda actor: action(runtime_orchestrator, actor),
            orchestrator_instance=runtime_orchestrator,
        )
        return 200, result.summary.status.value
    except Exception as exc:
        mapped_exc = routes._map_exception_to_http_exception(exc)
        if mapped_exc is not None:
            return mapped_exc.status_code, str(mapped_exc.detail)
        raise


def _direct_resume_outcome(
    client: TestClient,
    *,
    project_id: str,
    token: str | None,
    approved_actions: list[str] | None = None,
    runtime_actor_ids_override: dict[str, list[str]] | None = None,
) -> tuple[int, str]:
    approved = approved_actions or ["external_api_send"]
    return _direct_outcome_with_authenticated_actor(
        client,
        project_id=project_id,
        token=token,
        action=lambda runtime_orchestrator, actor: runtime_orchestrator.resume_from_approval(
            project_id=project_id,
            approved_actions=approved,
            actor=actor,
            trend_provider_name="gemini",
            project_allowed_actor_ids_by_action=runtime_actor_ids_override,
        ),
    )


def _direct_revision_resume_outcome(
    client: TestClient,
    *,
    project_id: str,
    token: str | None,
    resume_mode: RevisionResumeMode,
    reason: str = "",
) -> tuple[int, str]:
    return _direct_outcome_with_authenticated_actor(
        client,
        project_id=project_id,
        token=token,
        action=lambda runtime_orchestrator, actor: runtime_orchestrator.resume_from_revision(
            project_id=project_id,
            resume_mode=resume_mode,
            actor=actor,
            reason=reason,
            trend_provider_name="mock",
        ),
    )


def _direct_replanning_start_outcome(
    client: TestClient,
    *,
    project_id: str,
    token: str | None,
    note: str = "",
) -> tuple[int, str]:
    return _direct_outcome_with_authenticated_actor(
        client,
        project_id=project_id,
        token=token,
        action=lambda runtime_orchestrator, actor: runtime_orchestrator.start_replanning(
            project_id=project_id,
            actor=actor,
            note=note,
            trend_provider_name="mock",
        ),
    )


def _direct_reject_outcome(
    client: TestClient,
    *,
    project_id: str,
    token: str | None,
    rejected_actions: list[str] | None = None,
    runtime_actor_ids_override: dict[str, list[str]] | None = None,
    reason: str = "direct rejection",
    note: str = "",
) -> tuple[int, str]:
    rejected = rejected_actions or ["external_api_send"]
    return _direct_outcome_with_authenticated_actor(
        client,
        project_id=project_id,
        token=token,
        action=lambda runtime_orchestrator, actor: runtime_orchestrator.reject_approval(
            project_id=project_id,
            rejected_actions=rejected,
            actor=actor,
            reason=reason,
            note=note,
            project_allowed_actor_ids_by_action=runtime_actor_ids_override,
        ),
    )


def test_auth_dependency_toggle_changes_route_protection(monkeypatch) -> None:
    try:
        monkeypatch.setenv("DEV_AUTH_ENABLED", "false")
        client_disabled = TestClient(create_app())
        project_id_disabled = _run_waiting_approval_project(client_disabled)
        resume_disabled = client_disabled.post(
            "/orchestrator/resume/approval",
            json={
                "project_id": project_id_disabled,
                "approved_actions": ["external_api_send"],
                "trend_provider": "gemini",
            },
        )
        assert resume_disabled.status_code == 200
        audit_disabled = client_disabled.get(f"/projects/{project_id_disabled}/audit").json()
        assert any(
            event["event_type"] == "actor_resolved" and event["actor"] == "auth-disabled"
            for event in audit_disabled["events"]
        )

        monkeypatch.setenv("DEV_AUTH_ENABLED", "true")
        client_enabled = TestClient(create_app())
        project_id_enabled = _run_waiting_approval_project(client_enabled)
        resume_enabled = client_enabled.post(
            "/orchestrator/resume/approval",
            json={
                "project_id": project_id_enabled,
                "approved_actions": ["external_api_send"],
                "trend_provider": "gemini",
            },
        )
        assert resume_enabled.status_code == 401
        audit_enabled = client_enabled.get(f"/projects/{project_id_enabled}/audit").json()
        assert any(
            event["event_type"] == "authentication_failed"
            for event in audit_enabled["events"]
        )
    finally:
        _clear_auth_caches()


def test_owner_policy_interacts_with_auth_actor_resolution(monkeypatch) -> None:
    client = TestClient(create_app())
    owner_only_policy = {
        "project_owner_actor_id": "owner-1",
        "strict_mode": True,
        "action_rules": {
            "external_api_send": {
                "allowed_roles": ["owner"],
            }
        },
    }
    try:
        _clear_auth_caches()
        monkeypatch.setenv("DEV_AUTH_ENABLED", "true")

        owner_project_id = _run_waiting_approval_project(client, owner_only_policy)
        owner_resume = client.post(
            "/orchestrator/resume/approval",
            json={
                "project_id": owner_project_id,
                "approved_actions": ["external_api_send"],
                "actor": {
                    "actor_id": "forged-owner",
                    "actor_role": "viewer",
                    "actor_type": "human",
                },
                "trend_provider": "gemini",
            },
            headers={"Authorization": "Bearer dev-owner-token"},
        )
        assert owner_resume.status_code == 200
        owner_audit = client.get(f"/projects/{owner_project_id}/audit").json()
        assert any(
            event["event_type"] == "actor_resolved" and event["actor"] == "owner-1"
            for event in owner_audit["events"]
        )

        approver_project_id = _run_waiting_approval_project(client, owner_only_policy)
        approver_resume = client.post(
            "/orchestrator/resume/approval",
            json={
                "project_id": approver_project_id,
                "approved_actions": ["external_api_send"],
                "trend_provider": "gemini",
            },
            headers={"Authorization": "Bearer dev-approver-token"},
        )
        assert approver_resume.status_code == 403
    finally:
        _clear_auth_caches()


def test_shared_repository_across_apps_keeps_auth_seed_isolated_and_records_auth_failures(
    monkeypatch,
) -> None:
    shared_repository = InMemoryProjectRepository()
    try:
        _clear_auth_caches()
        monkeypatch.setenv("DEV_AUTH_ENABLED", "true")
        monkeypatch.setenv("DEV_AUTH_TOKEN_SEED", "seed-one:approver-one:approver:human")
        app_one = create_app()
        app_one_orchestrator = PMOrchestrator(repository=shared_repository)
        bind_orchestrator_binding(app_one, orchestrator=app_one_orchestrator)
        client_one = TestClient(app_one)
        project_id = _run_waiting_approval_project(client_one)

        monkeypatch.setenv("DEV_AUTH_TOKEN_SEED", "seed-two:approver-two:approver:human")
        app_two = create_app()
        app_two_orchestrator = PMOrchestrator(repository=shared_repository)
        bind_orchestrator_binding(app_two, orchestrator=app_two_orchestrator)
        client_two = TestClient(app_two)

        failed_resume = client_two.post(
            "/orchestrator/resume/approval",
            json={
                "project_id": project_id,
                "approved_actions": ["external_api_send"],
                "trend_provider": "gemini",
            },
            headers={"Authorization": "Bearer seed-one"},
        )
        assert failed_resume.status_code == 401

        success_resume = client_one.post(
            "/orchestrator/resume/approval",
            json={
                "project_id": project_id,
                "approved_actions": ["external_api_send"],
                "trend_provider": "gemini",
            },
            headers={"Authorization": "Bearer seed-one"},
        )
        assert success_resume.status_code == 200
        assert success_resume.json()["summary"]["status"] == "completed"

        audit = client_two.get(f"/projects/{project_id}/audit").json()
        assert any(
            event["event_type"] == "authentication_failed"
            and event["reason"] == "Invalid bearer token."
            for event in audit["events"]
        )
    finally:
        _clear_auth_caches()


def test_shared_repository_status_precedence_401_404_403_409_across_fresh_apps(
    monkeypatch,
) -> None:
    shared_repository = InMemoryProjectRepository()
    owner_only_policy = {
        "project_owner_actor_id": "owner-1",
        "strict_mode": True,
        "action_rules": {
            "external_api_send": {
                "allowed_roles": ["owner"],
            }
        },
    }
    try:
        _clear_auth_caches()
        client_one = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "seed-one:approver-one:approver:human",
        )
        project_forbidden = _run_waiting_approval_project(client_one, owner_only_policy)
        project_conflict = _run_waiting_approval_project(client_one)
        rejected = client_one.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_conflict,
                "rejected_actions": ["external_api_send"],
                "reason": "prepare conflict state",
            },
            headers={"Authorization": "Bearer seed-one"},
        )
        assert rejected.status_code == 200
        assert rejected.json()["summary"]["status"] == "revision_requested"

        client_two = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "seed-two:approver-two:approver:human",
        )

        unauthorized_missing = client_two.post(
            "/orchestrator/resume/approval",
            json={"project_id": "missing-project", "approved_actions": ["external_api_send"]},
            headers={"Authorization": "Bearer seed-one"},
        )
        unauthorized_forbidden = client_two.post(
            "/orchestrator/resume/approval",
            json={"project_id": project_forbidden, "approved_actions": ["external_api_send"]},
            headers={"Authorization": "Bearer seed-one"},
        )
        unauthorized_conflict = client_two.post(
            "/orchestrator/resume/approval",
            json={"project_id": project_conflict, "approved_actions": ["external_api_send"]},
            headers={"Authorization": "Bearer seed-one"},
        )
        assert unauthorized_missing.status_code == 401
        assert unauthorized_forbidden.status_code == 401
        assert unauthorized_conflict.status_code == 401
        assert unauthorized_missing.json()["detail"] == "Invalid bearer token."

        missing = client_two.post(
            "/orchestrator/resume/approval",
            json={"project_id": "missing-project", "approved_actions": ["external_api_send"]},
            headers={"Authorization": "Bearer seed-two"},
        )
        forbidden = client_two.post(
            "/orchestrator/resume/approval",
            json={"project_id": project_forbidden, "approved_actions": ["external_api_send"]},
            headers={"Authorization": "Bearer seed-two"},
        )
        conflict = client_two.post(
            "/orchestrator/resume/approval",
            json={"project_id": project_conflict, "approved_actions": ["external_api_send"]},
            headers={"Authorization": "Bearer seed-two"},
        )
        assert missing.status_code == 404
        assert forbidden.status_code == 403
        assert conflict.status_code == 409
        assert "Project not found: missing-project" in missing.json()["detail"]
        assert "not allowed" in forbidden.json()["detail"]
        assert "external_api_send" in forbidden.json()["detail"]
        assert "current: revision_requested" in conflict.json()["detail"]

        forbidden_audit = client_two.get(f"/projects/{project_forbidden}/audit").json()
        conflict_audit = client_two.get(f"/projects/{project_conflict}/audit").json()
        assert len(
            [
                event
                for event in forbidden_audit["events"]
                if event["event_type"] == "authentication_failed"
            ]
        ) == 1
        assert len(
            [
                event
                for event in conflict_audit["events"]
                if event["event_type"] == "authentication_failed"
            ]
        ) == 1
    finally:
        _clear_auth_caches()


def test_api_and_direct_orchestrator_conflict_detail_match_after_reload_cycle(monkeypatch) -> None:
    shared_repository = InMemoryProjectRepository()
    try:
        _clear_auth_caches()
        client_one = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "seed-one:approver-one:approver:human",
        )
        project_id = _run_waiting_approval_project(client_one)
        rejected = client_one.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_id,
                "rejected_actions": ["external_api_send"],
                "reason": "prepare parity check",
            },
            headers={"Authorization": "Bearer seed-one"},
        )
        assert rejected.status_code == 200
        assert rejected.json()["summary"]["status"] == "revision_requested"

        client_two = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "seed-two:approver-two:approver:human",
        )
        runtime_orchestrator = client_two.app.state.orchestrator
        with pytest.raises(ValueError) as captured:
            runtime_orchestrator.resume_from_approval(
                project_id=project_id,
                approved_actions=["external_api_send"],
                actor="approver-two",
            )

        api_response = client_two.post(
            "/orchestrator/resume/approval",
            json={"project_id": project_id, "approved_actions": ["external_api_send"]},
            headers={"Authorization": "Bearer seed-two"},
        )
        assert api_response.status_code == 409
        assert api_response.json()["detail"] == str(captured.value)
    finally:
        _clear_auth_caches()


def test_shared_repository_protected_endpoints_keep_401_precedence_over_409_conflicts(
    monkeypatch,
) -> None:
    shared_repository = InMemoryProjectRepository()
    try:
        _clear_auth_caches()
        client_one = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "seed-one:approver-one:approver:human",
        )
        waiting_project = _run_waiting_approval_project(client_one)
        revision_project = _run_waiting_approval_project(client_one)
        completed_project = _run_completed_project(client_one)
        rejected = client_one.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": revision_project,
                "rejected_actions": ["external_api_send"],
                "reason": "prepare revision conflict",
            },
            headers={"Authorization": "Bearer seed-one"},
        )
        assert rejected.status_code == 200
        assert rejected.json()["summary"]["status"] == "revision_requested"

        client_two = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "seed-two:approver-two:approver:human",
        )

        cases = [
            (
                "/orchestrator/resume/approval",
                {
                    "project_id": revision_project,
                    "approved_actions": ["external_api_send"],
                    "trend_provider": "gemini",
                },
                "current: revision_requested",
            ),
            (
                "/orchestrator/approval/reject",
                {
                    "project_id": completed_project,
                    "rejected_actions": ["external_api_send"],
                    "reason": "reject after completion should conflict",
                },
                "current: completed",
            ),
            (
                "/orchestrator/resume/revision",
                {
                    "project_id": waiting_project,
                    "resume_mode": "replanning",
                    "reason": "resume revision from waiting should conflict",
                },
                "current: waiting_approval",
            ),
            (
                "/orchestrator/replanning/start",
                {
                    "project_id": waiting_project,
                    "note": "start replanning from waiting should conflict",
                },
                "current: waiting_approval",
            ),
        ]

        for path, payload, expected_conflict in cases:
            unauthorized = client_two.post(
                path,
                json=payload,
                headers={"Authorization": "Bearer seed-one"},
            )
            assert unauthorized.status_code == 401
            assert unauthorized.json()["detail"] == "Invalid bearer token."

            conflict = client_two.post(
                path,
                json=payload,
                headers={"Authorization": "Bearer seed-two"},
            )
            assert conflict.status_code == 409
            assert expected_conflict in conflict.json()["detail"]
    finally:
        _clear_auth_caches()


def test_owner_approver_viewer_precedence_matches_api_and_direct_after_reload(monkeypatch) -> None:
    shared_repository = InMemoryProjectRepository()
    owner_only_policy = {
        "project_owner_actor_id": "owner-1",
        "strict_mode": True,
        "action_rules": {
            "external_api_send": {
                "allowed_roles": ["owner"],
            }
        },
    }
    token_seed = (
        "owner-token:owner-1:owner:human,"
        "approver-token:approver-1:approver:human,"
        "viewer-token:viewer-1:viewer:human"
    )
    try:
        _clear_auth_caches()
        seed_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            token_seed,
        )
        api_owner_project = _run_waiting_approval_project(seed_client, owner_only_policy)
        api_approver_project = _run_waiting_approval_project(seed_client, owner_only_policy)
        api_viewer_project = _run_waiting_approval_project(seed_client, owner_only_policy)
        direct_owner_project = _run_waiting_approval_project(seed_client, owner_only_policy)
        direct_approver_project = _run_waiting_approval_project(seed_client, owner_only_policy)
        direct_viewer_project = _run_waiting_approval_project(seed_client, owner_only_policy)

        api_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            token_seed,
        )
        direct_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            token_seed,
        )

        api_owner = api_client.post(
            "/orchestrator/resume/approval",
            json={"project_id": api_owner_project, "approved_actions": ["external_api_send"]},
            headers={"Authorization": "Bearer owner-token"},
        )
        api_approver = api_client.post(
            "/orchestrator/resume/approval",
            json={"project_id": api_approver_project, "approved_actions": ["external_api_send"]},
            headers={"Authorization": "Bearer approver-token"},
        )
        api_viewer = api_client.post(
            "/orchestrator/resume/approval",
            json={"project_id": api_viewer_project, "approved_actions": ["external_api_send"]},
            headers={"Authorization": "Bearer viewer-token"},
        )
        assert api_owner.status_code == 200
        assert api_owner.json()["summary"]["status"] == ProjectStatus.COMPLETED.value
        assert api_approver.status_code == 403
        assert api_viewer.status_code == 403

        direct_owner_status, direct_owner_detail = _direct_resume_outcome(
            direct_client,
            project_id=direct_owner_project,
            token="owner-token",
        )
        direct_approver_status, direct_approver_detail = _direct_resume_outcome(
            direct_client,
            project_id=direct_approver_project,
            token="approver-token",
        )
        direct_viewer_status, direct_viewer_detail = _direct_resume_outcome(
            direct_client,
            project_id=direct_viewer_project,
            token="viewer-token",
        )
        assert (direct_owner_status, direct_owner_detail) == (200, ProjectStatus.COMPLETED.value)
        assert direct_approver_status == 403
        assert direct_viewer_status == 403
        assert api_approver.json()["detail"] == direct_approver_detail
        assert api_viewer.json()["detail"] == direct_viewer_detail
    finally:
        _clear_auth_caches()


def test_runtime_empty_override_denial_then_api_omitted_override_success_after_reload(
    monkeypatch,
) -> None:
    shared_repository = InMemoryProjectRepository()
    token_seed = "approver-token:approver-1:approver:human"
    try:
        _clear_auth_caches()
        seed_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            token_seed,
        )
        project_id = _run_waiting_approval_project(seed_client)

        direct_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            token_seed,
        )
        denied_status, denied_detail = _direct_resume_outcome(
            direct_client,
            project_id=project_id,
            token="approver-token",
            runtime_actor_ids_override={"external_api_send": []},
        )
        assert denied_status == 403
        assert "allowed actor IDs" in denied_detail

        api_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            token_seed,
        )
        resumed = api_client.post(
            "/orchestrator/resume/approval",
            json={
                "project_id": project_id,
                "approved_actions": ["external_api_send"],
                "trend_provider": "gemini",
            },
            headers={"Authorization": "Bearer approver-token"},
        )
        assert resumed.status_code == 200
        assert resumed.json()["summary"]["status"] == ProjectStatus.COMPLETED.value

        audit = api_client.get(f"/projects/{project_id}/audit").json()
        assert len(
            [
                event
                for event in audit["events"]
                if event["event_type"] == "policy_override_applied"
                and event["metadata"].get("policy_source") == "project_runtime_override"
            ]
        ) == 1
        assert len(
            [
                event
                for event in audit["events"]
                if event["event_type"] == "authorization_failed"
            ]
        ) == 1
    finally:
        _clear_auth_caches()


def test_body_actor_tampering_stays_ignored_after_reload_with_direct_parity(monkeypatch) -> None:
    shared_repository = InMemoryProjectRepository()
    owner_only_policy = {
        "project_owner_actor_id": "owner-1",
        "strict_mode": True,
        "action_rules": {
            "external_api_send": {
                "allowed_roles": ["owner"],
            }
        },
    }
    token_seed = "approver-token:approver-1:approver:human"
    try:
        _clear_auth_caches()
        seed_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            token_seed,
        )
        api_project = _run_waiting_approval_project(seed_client, owner_only_policy)
        direct_project = _run_waiting_approval_project(seed_client, owner_only_policy)

        api_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            token_seed,
        )
        tampered = api_client.post(
            "/orchestrator/resume/approval",
            json={
                "project_id": api_project,
                "approved_actions": ["external_api_send"],
                "actor": {
                    "actor_id": "forged-owner",
                    "actor_role": "owner",
                    "actor_type": "human",
                },
            },
            headers={"Authorization": "Bearer approver-token"},
        )
        assert tampered.status_code == 403

        direct_status, direct_detail = _direct_resume_outcome(
            api_client,
            project_id=direct_project,
            token="approver-token",
        )
        assert direct_status == 403
        assert tampered.json()["detail"] == direct_detail

        api_audit = api_client.get(f"/projects/{api_project}/audit").json()
        assert any(
            event["event_type"] == "actor_resolved" and event["actor"] == "approver-1"
            for event in api_audit["events"]
        )
    finally:
        _clear_auth_caches()


def test_malformed_auth_env_keeps_secure_default_across_shared_repo_reload(monkeypatch) -> None:
    shared_repository = InMemoryProjectRepository()
    token_seed = "seed-one:approver-one:approver:human"
    try:
        _clear_auth_caches()
        baseline_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            token_seed,
        )
        project_id = _run_waiting_approval_project(baseline_client)

        malformed_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "malformed-seed-without-colons",
            dev_auth_enabled="definitely-not-bool",
        )
        no_header = malformed_client.post(
            "/orchestrator/resume/approval",
            json={"project_id": project_id, "approved_actions": ["external_api_send"]},
        )
        assert no_header.status_code == 401
        assert no_header.json()["detail"] == "Missing Authorization header."

        default_seed_token = malformed_client.post(
            "/orchestrator/resume/approval",
            json={"project_id": project_id, "approved_actions": ["external_api_send"]},
            headers={"Authorization": "Bearer dev-approver-token"},
        )
        assert default_seed_token.status_code == 200
        assert default_seed_token.json()["summary"]["status"] == ProjectStatus.COMPLETED.value
    finally:
        _clear_auth_caches()


def test_auth_env_flip_keeps_api_and_direct_parity_with_shared_repository(monkeypatch) -> None:
    shared_repository = InMemoryProjectRepository()
    try:
        _clear_auth_caches()
        disabled_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "unused-seed:unused:approver:human",
            dev_auth_enabled="false",
        )
        api_project = _run_waiting_approval_project(disabled_client)
        direct_project = _run_waiting_approval_project(disabled_client)

        enabled_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "seed-two:approver-two:approver:human",
            dev_auth_enabled="true",
        )
        api_no_auth = enabled_client.post(
            "/orchestrator/resume/approval",
            json={"project_id": api_project, "approved_actions": ["external_api_send"]},
        )
        direct_no_auth_status, direct_no_auth_detail = _direct_resume_outcome(
            enabled_client,
            project_id=direct_project,
            token=None,
        )
        assert api_no_auth.status_code == 401
        assert direct_no_auth_status == 401
        assert api_no_auth.json()["detail"] == direct_no_auth_detail

        api_with_auth = enabled_client.post(
            "/orchestrator/resume/approval",
            json={"project_id": api_project, "approved_actions": ["external_api_send"]},
            headers={"Authorization": "Bearer seed-two"},
        )
        direct_with_auth_status, direct_with_auth_detail = _direct_resume_outcome(
            enabled_client,
            project_id=direct_project,
            token="seed-two",
        )
        assert api_with_auth.status_code == 200
        assert api_with_auth.json()["summary"]["status"] == ProjectStatus.COMPLETED.value
        assert (direct_with_auth_status, direct_with_auth_detail) == (
            200,
            ProjectStatus.COMPLETED.value,
        )
    finally:
        _clear_auth_caches()


def test_shared_repo_repeated_app_init_keeps_auth_contexts_isolated(monkeypatch) -> None:
    shared_repository = InMemoryProjectRepository()
    try:
        _clear_auth_caches()
        client_enabled_one = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "seed-one:approver-one:approver:human",
            dev_auth_enabled="true",
        )
        project_enabled_one_api = _run_waiting_approval_project(client_enabled_one)
        project_enabled_one_direct = _run_waiting_approval_project(client_enabled_one)

        client_disabled = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "unused-seed:unused:approver:human",
            dev_auth_enabled="false",
        )
        project_disabled = _run_waiting_approval_project(client_disabled)

        client_enabled_two = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "seed-two:approver-two:approver:human",
            dev_auth_enabled="true",
        )
        project_enabled_two_api = _run_waiting_approval_project(client_enabled_two)
        project_enabled_two_direct = _run_waiting_approval_project(client_enabled_two)

        enabled_one_no_header = client_enabled_one.post(
            "/orchestrator/resume/approval",
            json={"project_id": project_enabled_one_api, "approved_actions": ["external_api_send"]},
        )
        enabled_one_wrong_seed = client_enabled_one.post(
            "/orchestrator/resume/approval",
            json={"project_id": project_enabled_one_api, "approved_actions": ["external_api_send"]},
            headers={"Authorization": "Bearer seed-two"},
        )
        enabled_one_valid_seed = client_enabled_one.post(
            "/orchestrator/resume/approval",
            json={"project_id": project_enabled_one_api, "approved_actions": ["external_api_send"]},
            headers={"Authorization": "Bearer seed-one"},
        )

        enabled_two_no_header = client_enabled_two.post(
            "/orchestrator/resume/approval",
            json={"project_id": project_enabled_two_api, "approved_actions": ["external_api_send"]},
        )
        enabled_two_wrong_seed = client_enabled_two.post(
            "/orchestrator/resume/approval",
            json={"project_id": project_enabled_two_api, "approved_actions": ["external_api_send"]},
            headers={"Authorization": "Bearer seed-one"},
        )
        enabled_two_valid_seed = client_enabled_two.post(
            "/orchestrator/resume/approval",
            json={"project_id": project_enabled_two_api, "approved_actions": ["external_api_send"]},
            headers={"Authorization": "Bearer seed-two"},
        )

        disabled_without_header = client_disabled.post(
            "/orchestrator/resume/approval",
            json={"project_id": project_disabled, "approved_actions": ["external_api_send"]},
        )

        direct_enabled_one_valid = _direct_resume_outcome(
            client_enabled_one,
            project_id=project_enabled_one_direct,
            token="seed-one",
        )
        direct_enabled_two_valid = _direct_resume_outcome(
            client_enabled_two,
            project_id=project_enabled_two_direct,
            token="seed-two",
        )
        direct_enabled_two_invalid = _direct_resume_outcome(
            client_enabled_two,
            project_id=project_enabled_two_direct,
            token="seed-one",
        )

        assert enabled_one_no_header.status_code == 401
        assert enabled_one_wrong_seed.status_code == 401
        assert enabled_one_valid_seed.status_code == 200
        assert enabled_two_no_header.status_code == 401
        assert enabled_two_wrong_seed.status_code == 401
        assert enabled_two_valid_seed.status_code == 200
        assert disabled_without_header.status_code == 200
        assert direct_enabled_one_valid == (200, ProjectStatus.COMPLETED.value)
        assert direct_enabled_two_valid == (200, ProjectStatus.COMPLETED.value)
        assert direct_enabled_two_invalid[0] == 401
        assert direct_enabled_two_invalid[1] == "Invalid bearer token."
    finally:
        _clear_auth_caches()


def test_shared_repo_revision_retry_keeps_401_precedence_over_409_after_completion(
    monkeypatch,
) -> None:
    shared_repository = InMemoryProjectRepository()
    token_seed = (
        "seed-one:operator-one:operator:human,"
        "seed-two:operator-two:operator:human"
    )
    try:
        _clear_auth_caches()
        seed_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            token_seed,
        )
        project_id = _run_revision_requested_project(seed_client)
        completed = seed_client.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "rereview",
                "reason": "complete before parity checks",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer seed-one"},
        )
        assert completed.status_code == 200
        assert completed.json()["summary"]["status"] == ProjectStatus.COMPLETED.value

        client_two = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            token_seed,
        )
        unauthorized = client_two.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "rebuilding",
                "reason": "unauthorized should stay 401",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer invalid-seed"},
        )
        conflict = client_two.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "rebuilding",
                "reason": "valid token should hit completed conflict",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer seed-two"},
        )
        assert unauthorized.status_code == 401
        assert conflict.status_code == 409
        assert conflict.json()["detail"] == (
            "Project is not in revision_requested state (current: completed)."
        )

        direct_orchestrator = client_two.app.state.orchestrator
        with pytest.raises(ValueError) as captured:
            direct_orchestrator.resume_from_revision(
                project_id=project_id,
                resume_mode=RevisionResumeMode.REBUILDING,
                actor="operator-two",
                reason="direct parity conflict",
                trend_provider_name="mock",
            )
        assert conflict.json()["detail"] == str(captured.value)
    finally:
        _clear_auth_caches()


def test_shared_repo_revision_seed_isolation_across_fresh_apps(monkeypatch) -> None:
    shared_repository = InMemoryProjectRepository()
    try:
        _clear_auth_caches()
        client_one = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "seed-one:operator-one:operator:human",
        )
        project_id = _run_revision_requested_project(client_one)

        client_two = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "seed-two:operator-two:operator:human",
        )
        stale_token = client_two.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "rereview",
                "reason": "stale token should fail",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer seed-one"},
        )
        assert stale_token.status_code == 401

        valid_token = client_one.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "rereview",
                "reason": "valid token should complete",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer seed-one"},
        )
        assert valid_token.status_code == 200
        assert valid_token.json()["summary"]["status"] == ProjectStatus.COMPLETED.value

        audit = client_two.get(f"/projects/{project_id}/audit").json()
        assert len(
            [
                event
                for event in audit["events"]
                if event["event_type"] == "authentication_failed"
            ]
        ) == 1
    finally:
        _clear_auth_caches()


def test_shared_repo_completed_revision_branch_keeps_reject_precedence_stable_across_roles(
    monkeypatch,
) -> None:
    shared_repository = InMemoryProjectRepository()
    token_seed = (
        "owner-token:owner-1:owner:human,"
        "approver-token:approver-1:approver:human,"
        "viewer-token:viewer-1:viewer:human"
    )
    try:
        _clear_auth_caches()
        seed_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            token_seed,
        )
        project_id = _run_revision_requested_project(seed_client)
        completed = seed_client.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "rebuilding",
                "reason": "complete before reject precedence checks",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer approver-token"},
        )
        assert completed.status_code == 200
        assert completed.json()["summary"]["status"] == ProjectStatus.COMPLETED.value

        client_two = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            token_seed,
        )
        unauthorized = client_two.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_id,
                "rejected_actions": ["external_api_send"],
                "reason": "unauthorized reject should fail first",
            },
            headers={"Authorization": "Bearer invalid-token"},
        )
        owner_conflict = client_two.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_id,
                "rejected_actions": ["external_api_send"],
                "reason": "owner reject should conflict on completed state",
            },
            headers={"Authorization": "Bearer owner-token"},
        )
        viewer_conflict = client_two.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_id,
                "rejected_actions": ["external_api_send"],
                "reason": "viewer reject should conflict on completed state",
            },
            headers={"Authorization": "Bearer viewer-token"},
        )
        assert unauthorized.status_code == 401
        assert owner_conflict.status_code == 409
        assert viewer_conflict.status_code == 409
        assert owner_conflict.json()["detail"] == viewer_conflict.json()["detail"]
        assert "current: completed" in owner_conflict.json()["detail"]
    finally:
        _clear_auth_caches()


def test_shared_repo_app_scoped_auth_snapshot_prevents_seed_cache_bleed_when_state_missing(
    monkeypatch,
) -> None:
    shared_repository = InMemoryProjectRepository()
    try:
        _clear_auth_caches()
        client_one = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "seed-one:approver-one:approver:human",
            dev_auth_enabled="true",
        )
        project_one = _run_waiting_approval_project(client_one)

        client_two = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "seed-two:approver-two:approver:human",
            dev_auth_enabled="true",
        )
        project_two = _run_waiting_approval_project(client_two)

        delattr(client_one.app.state, "auth_service")
        delattr(client_two.app.state, "auth_service")

        client_one_wrong = client_one.post(
            "/orchestrator/resume/approval",
            json={"project_id": project_one, "approved_actions": ["external_api_send"]},
            headers={"Authorization": "Bearer seed-two"},
        )
        client_one_right = client_one.post(
            "/orchestrator/resume/approval",
            json={"project_id": project_one, "approved_actions": ["external_api_send"]},
            headers={"Authorization": "Bearer seed-one"},
        )
        client_two_wrong = client_two.post(
            "/orchestrator/resume/approval",
            json={"project_id": project_two, "approved_actions": ["external_api_send"]},
            headers={"Authorization": "Bearer seed-one"},
        )
        client_two_right = client_two.post(
            "/orchestrator/resume/approval",
            json={"project_id": project_two, "approved_actions": ["external_api_send"]},
            headers={"Authorization": "Bearer seed-two"},
        )

        assert client_one_wrong.status_code == 401
        assert client_one_right.status_code == 200
        assert client_two_wrong.status_code == 401
        assert client_two_right.status_code == 200
    finally:
        _clear_auth_caches()


def test_shared_repo_auth_mode_flip_preserves_app_mode_when_state_service_missing(
    monkeypatch,
) -> None:
    shared_repository = InMemoryProjectRepository()
    try:
        _clear_auth_caches()
        app_disabled = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "unused-seed:unused:approver:human",
            dev_auth_enabled="false",
        )
        project_disabled = _run_revision_requested_project(app_disabled)

        app_enabled = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "seed-two:operator-two:operator:human",
            dev_auth_enabled="true",
        )
        project_enabled = _run_revision_requested_project(app_enabled)

        delattr(app_disabled.app.state, "auth_service")
        delattr(app_enabled.app.state, "auth_service")

        disabled_no_header = app_disabled.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_disabled,
                "resume_mode": "rereview",
                "reason": "auth disabled should still resolve system actor",
                "trend_provider": "mock",
            },
        )
        enabled_no_header = app_enabled.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_enabled,
                "resume_mode": "rereview",
                "reason": "auth enabled without token should fail",
                "trend_provider": "mock",
            },
        )
        enabled_with_token = app_enabled.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_enabled,
                "resume_mode": "rereview",
                "reason": "auth enabled with valid token should complete",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer seed-two"},
        )

        assert disabled_no_header.status_code == 200
        assert enabled_no_header.status_code == 401
        assert enabled_with_token.status_code == 200
    finally:
        _clear_auth_caches()


def test_shared_repo_completed_revision_retry_precedence_consistent_across_roles(
    monkeypatch,
) -> None:
    shared_repository = InMemoryProjectRepository()
    token_seed = (
        "owner-token:owner-1:owner:human,"
        "approver-token:approver-1:approver:human,"
        "viewer-token:viewer-1:viewer:human,"
        "operator-token:operator-1:operator:human"
    )
    try:
        _clear_auth_caches()
        seed_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            token_seed,
        )
        project_id = _run_revision_requested_project(seed_client)
        completed = seed_client.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "rebuilding",
                "reason": "complete before role precedence checks",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer operator-token"},
        )
        assert completed.status_code == 200
        assert completed.json()["summary"]["status"] == ProjectStatus.COMPLETED.value

        client_two = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            token_seed,
        )
        unauthorized = client_two.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "rereview",
                "reason": "invalid token should stay unauthorized",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer invalid-token"},
        )
        owner_conflict = client_two.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "rereview",
                "reason": "owner should hit completed conflict",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer owner-token"},
        )
        approver_conflict = client_two.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "rereview",
                "reason": "approver should hit completed conflict",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer approver-token"},
        )
        viewer_conflict = client_two.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "rereview",
                "reason": "viewer should hit completed conflict",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer viewer-token"},
        )
        assert unauthorized.status_code == 401
        assert owner_conflict.status_code == 409
        assert approver_conflict.status_code == 409
        assert viewer_conflict.status_code == 409
        assert owner_conflict.json()["detail"] == approver_conflict.json()["detail"]
        assert approver_conflict.json()["detail"] == viewer_conflict.json()["detail"]

        parity_orchestrator = client_two.app.state.orchestrator
        with pytest.raises(ValueError) as captured:
            parity_orchestrator.resume_from_revision(
                project_id=project_id,
                resume_mode=RevisionResumeMode.REREVIEW,
                actor="viewer-1",
                reason="direct parity conflict",
                trend_provider_name="mock",
            )
        assert viewer_conflict.json()["detail"] == str(captured.value)
    finally:
        _clear_auth_caches()


def test_malformed_to_corrected_env_flip_keeps_revision_retry_parity_and_precedence(
    monkeypatch,
) -> None:
    shared_repository = InMemoryProjectRepository()
    try:
        _clear_auth_caches()
        malformed_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "malformed-seed-without-colons",
            dev_auth_enabled="definitely-not-bool",
        )
        project_id = _run_revision_requested_project(malformed_client)

        malformed_invalid = malformed_client.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "rereview",
                "reason": "invalid token on malformed app",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer invalid-token"},
        )
        malformed_complete = malformed_client.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "rereview",
                "reason": "complete using default malformed fallback seed",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer dev-operator-token"},
        )
        assert malformed_invalid.status_code == 401
        assert malformed_complete.status_code == 200
        assert malformed_complete.json()["summary"]["status"] == ProjectStatus.COMPLETED.value

        corrected_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "seed-two:operator-two:operator:human",
            dev_auth_enabled="true",
        )
        corrected_stale = corrected_client.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "rebuilding",
                "reason": "stale token after correction",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer dev-operator-token"},
        )
        corrected_conflict = corrected_client.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "rebuilding",
                "reason": "corrected token should hit completed conflict",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer seed-two"},
        )
        assert corrected_stale.status_code == 401
        assert corrected_conflict.status_code == 409
        assert "current: completed" in corrected_conflict.json()["detail"]

        direct_status, direct_detail = _direct_revision_resume_outcome(
            corrected_client,
            project_id=project_id,
            token="seed-two",
            resume_mode=RevisionResumeMode.REBUILDING,
            reason="direct parity after correction",
        )
        assert direct_status == 409
        assert direct_detail == corrected_conflict.json()["detail"]
    finally:
        _clear_auth_caches()


def test_corrected_env_app_state_missing_keeps_revision_auth_isolation_after_malformed(
    monkeypatch,
) -> None:
    shared_repository = InMemoryProjectRepository()
    try:
        _clear_auth_caches()
        malformed_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "malformed-seed-without-colons",
            dev_auth_enabled="definitely-not-bool",
        )
        project_one = _run_revision_requested_project(malformed_client)

        corrected_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "seed-two:operator-two:operator:human",
            dev_auth_enabled="true",
        )
        delattr(corrected_client.app.state, "auth_service")

        corrected_wrong = corrected_client.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_one,
                "resume_mode": "rereview",
                "reason": "wrong token with missing app state service",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer dev-operator-token"},
        )
        corrected_right = corrected_client.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_one,
                "resume_mode": "rereview",
                "reason": "right token with missing app state service",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer seed-two"},
        )
        assert corrected_wrong.status_code == 401
        assert corrected_right.status_code == 200
        assert corrected_right.json()["summary"]["status"] == ProjectStatus.COMPLETED.value

        project_two = _run_revision_requested_project(malformed_client)
        malformed_complete = malformed_client.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_two,
                "resume_mode": "rereview",
                "reason": "malformed app must keep default token map",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer dev-operator-token"},
        )
        assert malformed_complete.status_code == 200
    finally:
        _clear_auth_caches()


def test_corrected_env_role_permutations_after_malformed_flip_keep_event_stability(
    monkeypatch,
) -> None:
    shared_repository = InMemoryProjectRepository()
    try:
        _clear_auth_caches()
        malformed_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "malformed-seed-without-colons",
            dev_auth_enabled="definitely-not-bool",
        )
        project_id = _run_revision_requested_project(malformed_client)
        completed = malformed_client.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "rebuilding",
                "reason": "complete before corrected role permutations",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer dev-operator-token"},
        )
        assert completed.status_code == 200

        corrected_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            (
                "owner-token:owner-1:owner:human,"
                "approver-token:approver-1:approver:human,"
                "viewer-token:viewer-1:viewer:human"
            ),
            dev_auth_enabled="true",
        )
        unauthorized = corrected_client.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "rereview",
                "reason": "invalid token should remain unauthorized",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer invalid-token"},
        )
        owner_conflict = corrected_client.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "rereview",
                "reason": "owner conflict check",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer owner-token"},
        )
        approver_conflict = corrected_client.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "rereview",
                "reason": "approver conflict check",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer approver-token"},
        )
        viewer_conflict = corrected_client.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "rereview",
                "reason": "viewer conflict check",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer viewer-token"},
        )
        assert unauthorized.status_code == 401
        assert owner_conflict.status_code == 409
        assert approver_conflict.status_code == 409
        assert viewer_conflict.status_code == 409
        assert owner_conflict.json()["detail"] == approver_conflict.json()["detail"]
        assert approver_conflict.json()["detail"] == viewer_conflict.json()["detail"]

        audit = corrected_client.get(f"/projects/{project_id}/audit").json()
        assert len(
            [
                event
                for event in audit["events"]
                if event["event_type"] == "resume_triggered"
                and event["metadata"].get("mode") == "rebuilding"
            ]
        ) == 1
        assert len(
            [
                event
                for event in audit["events"]
                if event["event_type"] == "resume_triggered"
                and event["metadata"].get("mode") == "rereview"
            ]
        ) == 0
    finally:
        _clear_auth_caches()


def test_shared_repo_env_flip_app_snapshot_prevents_cross_app_seed_bleed_when_state_missing(
    monkeypatch,
) -> None:
    shared_repository = InMemoryProjectRepository()
    try:
        _clear_auth_caches()
        malformed_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "malformed-seed-without-colons",
            dev_auth_enabled="definitely-not-bool",
        )
        project_id = _run_revision_requested_project(malformed_client)

        corrected_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "seed-two:operator-two:operator:human",
            dev_auth_enabled="true",
        )
        assert corrected_client.app.state.orchestrator.repository is shared_repository
        _drop_app_runtime_bindings(corrected_client)

        _ = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "seed-three:operator-three:operator:human",
            dev_auth_enabled="true",
        )

        corrected_wrong = corrected_client.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "rereview",
                "reason": "seed-three should not bleed into seed-two app",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer seed-three"},
        )
        corrected_right = corrected_client.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "rereview",
                "reason": "seed-two snapshot should remain authoritative",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer seed-two"},
        )
        assert corrected_wrong.status_code == 401
        assert corrected_right.status_code == 200
        assert corrected_right.json()["summary"]["status"] == ProjectStatus.COMPLETED.value
        assert corrected_client.app.state.orchestrator.repository is shared_repository
        assert corrected_client.app.state.orchestrator is corrected_client.app._initial_orchestrator
        assert corrected_client.app.state.auth_service is corrected_client.app._initial_auth_service
        assert (
            corrected_client.app.state._initial_auth_service
            is corrected_client.app._initial_auth_service
        )

        api_conflict = corrected_client.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "rebuilding",
                "reason": "completed conflict parity after state restore",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer seed-two"},
        )
        direct_status, direct_detail = _direct_revision_resume_outcome(
            corrected_client,
            project_id=project_id,
            token="seed-two",
            resume_mode=RevisionResumeMode.REBUILDING,
            reason="direct conflict parity after state restore",
        )
        assert api_conflict.status_code == 409
        assert direct_status == 409
        assert direct_detail == api_conflict.json()["detail"]
    finally:
        _clear_auth_caches()


def test_env_flip_state_gaps_keep_replanning_start_auth_and_orchestrator_isolation(
    monkeypatch,
) -> None:
    shared_repository = InMemoryProjectRepository()
    try:
        _clear_auth_caches()
        malformed_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "malformed-seed-without-colons",
            dev_auth_enabled="definitely-not-bool",
        )
        project_id = _run_revision_requested_project(malformed_client)

        corrected_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "seed-two:operator-two:operator:human",
            dev_auth_enabled="true",
        )
        resume_replanning = corrected_client.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "replanning",
                "reason": "move into ready_for_planning before start",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer seed-two"},
        )
        assert resume_replanning.status_code == 200
        assert (
            resume_replanning.json()["summary"]["status"]
            == ProjectStatus.READY_FOR_PLANNING.value
        )

        _drop_app_runtime_bindings(corrected_client)

        _ = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "seed-three:operator-three:operator:human",
            dev_auth_enabled="true",
        )

        wrong_start = corrected_client.post(
            "/orchestrator/replanning/start",
            json={
                "project_id": project_id,
                "note": "seed-three should stay unauthorized for corrected app",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer seed-three"},
        )
        right_start = corrected_client.post(
            "/orchestrator/replanning/start",
            json={
                "project_id": project_id,
                "note": "seed-two should remain valid for corrected app",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer seed-two"},
        )
        assert wrong_start.status_code == 401
        assert right_start.status_code == 200
        assert right_start.json()["summary"]["status"] == ProjectStatus.COMPLETED.value
        assert corrected_client.app.state.orchestrator.repository is shared_repository
        assert corrected_client.app.state.orchestrator is corrected_client.app._initial_orchestrator
        assert corrected_client.app.state.auth_service is corrected_client.app._initial_auth_service

        audit = corrected_client.get(f"/projects/{project_id}/audit").json()
        assert len(
            [event for event in audit["events"] if event["event_type"] == "replanning_started"]
        ) == 1
    finally:
        _clear_auth_caches()


def test_env_flip_replanning_retry_role_permutations_keep_precedence_and_parity(
    monkeypatch,
) -> None:
    shared_repository = InMemoryProjectRepository()
    try:
        _clear_auth_caches()
        malformed_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "malformed-seed-without-colons",
            dev_auth_enabled="definitely-not-bool",
        )
        project_id = _run_revision_requested_project(malformed_client)

        corrected_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            (
                "owner-token:owner-1:owner:human,"
                "approver-token:approver-1:approver:human,"
                "viewer-token:viewer-1:viewer:human"
            ),
            dev_auth_enabled="true",
        )
        resume_replanning = corrected_client.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "replanning",
                "reason": "prepare replanning-start role parity checks",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer owner-token"},
        )
        assert resume_replanning.status_code == 200
        assert (
            resume_replanning.json()["summary"]["status"]
            == ProjectStatus.READY_FOR_PLANNING.value
        )

        _drop_app_runtime_bindings(corrected_client)

        invalid_start = corrected_client.post(
            "/orchestrator/replanning/start",
            json={
                "project_id": project_id,
                "note": "invalid token should remain unauthorized",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert invalid_start.status_code == 401

        owner_start = corrected_client.post(
            "/orchestrator/replanning/start",
            json={
                "project_id": project_id,
                "note": "owner starts replanning execution",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer owner-token"},
        )
        assert owner_start.status_code == 200
        assert owner_start.json()["summary"]["status"] == ProjectStatus.COMPLETED.value

        approver_retry = corrected_client.post(
            "/orchestrator/replanning/start",
            json={
                "project_id": project_id,
                "note": "approver retry should be idempotent after completion",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer approver-token"},
        )
        viewer_retry = corrected_client.post(
            "/orchestrator/replanning/start",
            json={
                "project_id": project_id,
                "note": "viewer retry should be idempotent after completion",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer viewer-token"},
        )
        invalid_after_completion = corrected_client.post(
            "/orchestrator/replanning/start",
            json={
                "project_id": project_id,
                "note": "invalid token should stay unauthorized after completion",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert approver_retry.status_code == 200
        assert viewer_retry.status_code == 200
        assert invalid_after_completion.status_code == 401
        assert approver_retry.json()["summary"]["status"] == ProjectStatus.COMPLETED.value
        assert viewer_retry.json()["summary"]["status"] == ProjectStatus.COMPLETED.value
        assert approver_retry.json()["summary"]["next_steps"] == viewer_retry.json()["summary"][
            "next_steps"
        ]

        direct_status, direct_detail = _direct_replanning_start_outcome(
            corrected_client,
            project_id=project_id,
            token="owner-token",
            note="direct replanning retry parity",
        )
        assert direct_status == 200
        assert direct_detail == ProjectStatus.COMPLETED.value

        assert corrected_client.app.state.orchestrator.repository is shared_repository
        assert corrected_client.app.state.orchestrator is corrected_client.app._initial_orchestrator
        assert corrected_client.app.state.auth_service is corrected_client.app._initial_auth_service

        audit = corrected_client.get(f"/projects/{project_id}/audit").json()
        assert len(
            [event for event in audit["events"] if event["event_type"] == "replanning_started"]
        ) == 1
    finally:
        _clear_auth_caches()


def test_shared_repo_mixed_approval_revision_retries_keep_precedence_and_parity(
    monkeypatch,
) -> None:
    shared_repository = InMemoryProjectRepository()
    owner_only_policy = {
        "project_owner_actor_id": "owner-1",
        "strict_mode": True,
        "action_rules": {
            "external_api_send": {"allowed_roles": ["owner"]},
            "bulk_modify": {"allowed_roles": ["owner"]},
            "destructive_change": {"allowed_roles": ["owner"]},
        },
    }
    seeded_roles = (
        "owner-token:owner-1:owner:human,"
        "approver-token:approver-1:approver:human,"
        "viewer-token:viewer-1:viewer:human"
    )
    try:
        _clear_auth_caches()
        client_one = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            seeded_roles,
            dev_auth_enabled="true",
        )
        project_id = _run_waiting_approval_project(client_one, owner_only_policy)

        unauthorized_reject = client_one.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_id,
                "rejected_actions": ["external_api_send"],
                "reason": "invalid token should fail before reject conflict checks",
            },
            headers={"Authorization": "Bearer invalid-token"},
        )
        forbidden_reject = client_one.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_id,
                "rejected_actions": ["external_api_send"],
                "reason": "viewer should not reject owner-only approval",
            },
            headers={"Authorization": "Bearer viewer-token"},
        )
        owner_reject = client_one.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_id,
                "rejected_actions": ["external_api_send"],
                "reason": "owner rejects approval and moves flow to revision",
                "note": "owner reject primary path",
            },
            headers={"Authorization": "Bearer owner-token"},
        )
        assert unauthorized_reject.status_code == 401
        assert forbidden_reject.status_code == 403
        assert owner_reject.status_code == 200
        assert owner_reject.json()["summary"]["status"] == ProjectStatus.REVISION_REQUESTED.value

        owner_reject_retry = client_one.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_id,
                "rejected_actions": ["external_api_send"],
                "reason": "owner retries reject after revision transition",
                "note": "retry reject same approval action",
            },
            headers={"Authorization": "Bearer owner-token"},
        )
        assert owner_reject_retry.status_code == 200
        assert (
            owner_reject_retry.json()["summary"]["status"]
            == ProjectStatus.REVISION_REQUESTED.value
        )

        retry_audit = client_one.get(f"/projects/{project_id}/audit").json()
        assert len(
            [event for event in retry_audit["events"] if event["event_type"] == "approval_rejected"]
        ) == 1
        rejected_approval = next(
            approval
            for approval in retry_audit["approvals"]
            if approval["action_type"] == "external_api_send"
        )
        assert (
            rejected_approval["decision_note"]
            == "owner rejects approval and moves flow to revision owner reject primary path"
        )
        rejected_event = next(
            event for event in retry_audit["events"] if event["event_type"] == "approval_rejected"
        )
        assert rejected_event["metadata"].get("note") == "owner reject primary path"

        client_two = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            seeded_roles,
            dev_auth_enabled="true",
        )
        _drop_app_runtime_bindings(client_two)

        invalid_revision = client_two.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "replanning",
                "reason": "invalid token should fail before revision conflict checks",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer invalid-token"},
        )
        owner_revision = client_two.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "replanning",
                "reason": "owner resumes revision into replanning lane",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer owner-token"},
        )
        owner_replanning_start = client_two.post(
            "/orchestrator/replanning/start",
            json={
                "project_id": project_id,
                "note": "owner starts replanning execution",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer owner-token"},
        )
        invalid_after_completion = client_two.post(
            "/orchestrator/resume/approval",
            json={
                "project_id": project_id,
                "approved_actions": ["external_api_send"],
                "trend_provider": "gemini",
            },
            headers={"Authorization": "Bearer invalid-token"},
        )
        approver_conflict = client_two.post(
            "/orchestrator/resume/approval",
            json={
                "project_id": project_id,
                "approved_actions": ["external_api_send"],
                "trend_provider": "gemini",
            },
            headers={"Authorization": "Bearer approver-token"},
        )
        viewer_conflict = client_two.post(
            "/orchestrator/resume/approval",
            json={
                "project_id": project_id,
                "approved_actions": ["external_api_send"],
                "trend_provider": "gemini",
            },
            headers={"Authorization": "Bearer viewer-token"},
        )
        assert invalid_revision.status_code == 401
        assert owner_revision.status_code == 200
        assert owner_revision.json()["summary"]["status"] == ProjectStatus.READY_FOR_PLANNING.value
        assert owner_replanning_start.status_code == 200
        assert owner_replanning_start.json()["summary"]["status"] == ProjectStatus.COMPLETED.value
        assert invalid_after_completion.status_code == 401
        assert approver_conflict.status_code == 409
        assert viewer_conflict.status_code == 409
        assert approver_conflict.json()["detail"] == viewer_conflict.json()["detail"]

        direct_status, direct_detail = _direct_resume_outcome(
            client_two,
            project_id=project_id,
            token="approver-token",
            approved_actions=["external_api_send"],
        )
        assert direct_status == 409
        assert direct_detail == approver_conflict.json()["detail"]

        assert client_two.app.state.orchestrator.repository is shared_repository
        assert client_two.app.state.orchestrator is client_two.app._initial_orchestrator
        assert client_two.app.state.auth_service is client_two.app._initial_auth_service

        final_audit = client_two.get(f"/projects/{project_id}/audit").json()
        assert len(
            [event for event in final_audit["events"] if event["event_type"] == "approval_rejected"]
        ) == 1
        assert len(
            [
                event
                for event in final_audit["events"]
                if event["event_type"] == "approval_rejected"
                and event["metadata"].get("note") == "owner reject primary path"
            ]
        ) == 1
        assert len(
            [
                event
                for event in final_audit["events"]
                if event["event_type"] == "resume_triggered"
                and event["metadata"].get("mode") == "replanning"
            ]
        ) == 1
    finally:
        _clear_auth_caches()


def test_shared_repo_state_gap_keeps_401_404_403_409_precedence_and_direct_parity(
    monkeypatch,
) -> None:
    shared_repository = InMemoryProjectRepository()
    owner_only_policy = {
        "project_owner_actor_id": "owner-1",
        "strict_mode": True,
        "action_rules": {
            "external_api_send": {
                "allowed_roles": ["owner"],
            }
        },
    }
    try:
        _clear_auth_caches()
        client_one = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "seed-one:approver-one:approver:human",
        )
        project_forbidden = _run_waiting_approval_project(client_one, owner_only_policy)
        project_conflict = _run_waiting_approval_project(client_one)
        rejected = client_one.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_conflict,
                "rejected_actions": ["external_api_send"],
                "reason": "prepare revision conflict for precedence state-gap variant",
            },
            headers={"Authorization": "Bearer seed-one"},
        )
        assert rejected.status_code == 200
        assert rejected.json()["summary"]["status"] == ProjectStatus.REVISION_REQUESTED.value

        client_two = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "seed-two:approver-two:approver:human",
        )
        _drop_app_runtime_bindings(client_two)

        unauthorized_missing = client_two.post(
            "/orchestrator/resume/approval",
            json={"project_id": "missing-project", "approved_actions": ["external_api_send"]},
            headers={"Authorization": "Bearer invalid-token"},
        )
        unauthorized_forbidden = client_two.post(
            "/orchestrator/resume/approval",
            json={"project_id": project_forbidden, "approved_actions": ["external_api_send"]},
            headers={"Authorization": "Bearer invalid-token"},
        )
        unauthorized_conflict = client_two.post(
            "/orchestrator/resume/approval",
            json={"project_id": project_conflict, "approved_actions": ["external_api_send"]},
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert unauthorized_missing.status_code == 401
        assert unauthorized_forbidden.status_code == 401
        assert unauthorized_conflict.status_code == 401

        missing = client_two.post(
            "/orchestrator/resume/approval",
            json={"project_id": "missing-project", "approved_actions": ["external_api_send"]},
            headers={"Authorization": "Bearer seed-two"},
        )
        forbidden = client_two.post(
            "/orchestrator/resume/approval",
            json={"project_id": project_forbidden, "approved_actions": ["external_api_send"]},
            headers={"Authorization": "Bearer seed-two"},
        )
        conflict = client_two.post(
            "/orchestrator/resume/approval",
            json={"project_id": project_conflict, "approved_actions": ["external_api_send"]},
            headers={"Authorization": "Bearer seed-two"},
        )
        assert missing.status_code == 404
        assert forbidden.status_code == 403
        assert conflict.status_code == 409
        assert "Project not found: missing-project" in missing.json()["detail"]
        assert "not allowed" in forbidden.json()["detail"]
        assert "current: revision_requested" in conflict.json()["detail"]

        direct_status, direct_detail = _direct_resume_outcome(
            client_two,
            project_id=project_conflict,
            token="seed-two",
            approved_actions=["external_api_send"],
        )
        assert direct_status == 409
        assert direct_detail == conflict.json()["detail"]

        assert client_two.app.state.orchestrator.repository is shared_repository
        assert client_two.app.state.orchestrator is client_two.app._initial_orchestrator
        assert client_two.app.state.auth_service is client_two.app._initial_auth_service
    finally:
        _clear_auth_caches()


def test_shared_repo_reject_state_gap_keeps_401_404_403_409_precedence_and_direct_parity(
    monkeypatch,
) -> None:
    shared_repository = InMemoryProjectRepository()
    owner_only_policy = {
        "project_owner_actor_id": "owner-1",
        "strict_mode": True,
        "action_rules": {
            "external_api_send": {
                "allowed_roles": ["owner"],
            }
        },
    }
    try:
        _clear_auth_caches()
        client_one = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "seed-one:approver-one:approver:human",
        )
        project_forbidden = _run_waiting_approval_project(client_one, owner_only_policy)
        project_conflict = _run_completed_project(client_one)

        client_two = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "seed-two:approver-two:approver:human",
        )
        _drop_app_runtime_bindings(client_two)

        unauthorized_missing = client_two.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": "missing-project",
                "rejected_actions": ["external_api_send"],
                "reason": "unauthorized missing should still be 401",
            },
            headers={"Authorization": "Bearer invalid-token"},
        )
        unauthorized_forbidden = client_two.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_forbidden,
                "rejected_actions": ["external_api_send"],
                "reason": "unauthorized forbidden should still be 401",
            },
            headers={"Authorization": "Bearer invalid-token"},
        )
        unauthorized_conflict = client_two.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_conflict,
                "rejected_actions": ["external_api_send"],
                "reason": "unauthorized conflict should still be 401",
            },
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert unauthorized_missing.status_code == 401
        assert unauthorized_forbidden.status_code == 401
        assert unauthorized_conflict.status_code == 401

        missing = client_two.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": "missing-project",
                "rejected_actions": ["external_api_send"],
                "reason": "valid token should surface 404 missing",
            },
            headers={"Authorization": "Bearer seed-two"},
        )
        forbidden = client_two.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_forbidden,
                "rejected_actions": ["external_api_send"],
                "reason": "valid token should surface 403 forbidden",
            },
            headers={"Authorization": "Bearer seed-two"},
        )
        conflict = client_two.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_conflict,
                "rejected_actions": ["external_api_send"],
                "reason": "valid token should surface 409 conflict",
            },
            headers={"Authorization": "Bearer seed-two"},
        )
        assert missing.status_code == 404
        assert forbidden.status_code == 403
        assert conflict.status_code == 409
        assert "Project not found: missing-project" in missing.json()["detail"]
        assert "not allowed" in forbidden.json()["detail"]
        assert "current: completed" in conflict.json()["detail"]

        direct_status, direct_detail = _direct_reject_outcome(
            client_two,
            project_id=project_conflict,
            token="seed-two",
            rejected_actions=["external_api_send"],
            reason="direct parity completed reject conflict",
        )
        assert direct_status == 409
        assert direct_detail == conflict.json()["detail"]
    finally:
        _clear_auth_caches()


def test_runtime_empty_override_reject_denial_then_api_omitted_success_after_reload(
    monkeypatch,
) -> None:
    shared_repository = InMemoryProjectRepository()
    token_seed = "approver-token:approver-1:approver:human"
    try:
        _clear_auth_caches()
        seed_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            token_seed,
        )
        project_id = _run_waiting_approval_project(seed_client)

        direct_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            token_seed,
        )
        denied_status, denied_detail = _direct_reject_outcome(
            direct_client,
            project_id=project_id,
            token="approver-token",
            rejected_actions=["external_api_send"],
            runtime_actor_ids_override={"external_api_send": []},
            reason="direct runtime override deny",
            note="direct override denial note",
        )
        assert denied_status == 403
        assert "allowed actor IDs" in denied_detail

        api_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            token_seed,
        )
        _drop_app_runtime_bindings(api_client)
        rejected = api_client.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_id,
                "rejected_actions": ["external_api_send"],
                "reason": "api reject after omitted override",
                "note": "api rejection note should persist",
            },
            headers={"Authorization": "Bearer approver-token"},
        )
        rejected_retry = api_client.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_id,
                "rejected_actions": ["external_api_send"],
                "reason": "api reject retry after revision state",
                "note": "retry note should not mutate first reject event",
            },
            headers={"Authorization": "Bearer approver-token"},
        )
        assert rejected.status_code == 200
        assert rejected_retry.status_code == 200
        assert rejected.json()["summary"]["status"] == ProjectStatus.REVISION_REQUESTED.value
        assert rejected_retry.json()["summary"]["status"] == ProjectStatus.REVISION_REQUESTED.value

        audit = api_client.get(f"/projects/{project_id}/audit").json()
        assert len(
            [
                event
                for event in audit["events"]
                if event["event_type"] == "policy_override_applied"
                and event["metadata"].get("policy_source") == "project_runtime_override"
            ]
        ) == 1
        assert len(
            [event for event in audit["events"] if event["event_type"] == "authorization_failed"]
        ) == 1
        rejected_events = [
            event for event in audit["events"] if event["event_type"] == "approval_rejected"
        ]
        assert len(rejected_events) == 1
        assert rejected_events[0]["metadata"].get("note") == "api rejection note should persist"
    finally:
        _clear_auth_caches()


def test_shared_repo_replanning_started_note_and_metadata_immutable_across_fresh_retries(
    monkeypatch,
) -> None:
    shared_repository = InMemoryProjectRepository()
    token_seed = (
        "owner-token:owner-1:owner:human,"
        "approver-token:approver-1:approver:human,"
        "viewer-token:viewer-1:viewer:human"
    )
    try:
        _clear_auth_caches()
        seed_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            token_seed,
        )
        project_id = _run_revision_requested_project(seed_client)
        resumed = seed_client.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "replanning",
                "reason": "prepare replanning start immutability checks",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer owner-token"},
        )
        assert resumed.status_code == 200
        assert resumed.json()["summary"]["status"] == ProjectStatus.READY_FOR_PLANNING.value

        first_start = seed_client.post(
            "/orchestrator/replanning/start",
            json={
                "project_id": project_id,
                "note": "  first replanning note  ",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer owner-token"},
        )
        assert first_start.status_code == 200
        assert first_start.json()["summary"]["status"] == ProjectStatus.COMPLETED.value

        retry_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            token_seed,
        )
        _drop_app_runtime_bindings(retry_client)
        invalid_retry = retry_client.post(
            "/orchestrator/replanning/start",
            json={
                "project_id": project_id,
                "note": "invalid retry should still be unauthorized",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer invalid-token"},
        )
        approver_retry = retry_client.post(
            "/orchestrator/replanning/start",
            json={
                "project_id": project_id,
                "note": "approver retry should be idempotent without mutating first note",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer approver-token"},
        )
        viewer_retry = retry_client.post(
            "/orchestrator/replanning/start",
            json={
                "project_id": project_id,
                "note": "viewer retry should also be idempotent",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer viewer-token"},
        )
        assert invalid_retry.status_code == 401
        assert approver_retry.status_code == 200
        assert viewer_retry.status_code == 200
        assert approver_retry.json()["summary"]["status"] == ProjectStatus.COMPLETED.value
        assert viewer_retry.json()["summary"]["status"] == ProjectStatus.COMPLETED.value

        direct_status, direct_detail = _direct_replanning_start_outcome(
            retry_client,
            project_id=project_id,
            token="owner-token",
            note="direct parity retry after completion",
        )
        assert direct_status == 200
        assert direct_detail == ProjectStatus.COMPLETED.value

        audit = retry_client.get(f"/projects/{project_id}/audit").json()
        replanning_started_events = [
            event for event in audit["events"] if event["event_type"] == "replanning_started"
        ]
        assert len(replanning_started_events) == 1
        assert replanning_started_events[0]["reason"] == "first replanning note"
        assert replanning_started_events[0]["metadata"].get("reset_downstream_tasks") is True
    finally:
        _clear_auth_caches()


def test_shared_repo_explicit_empty_override_then_omitted_override_mixed_actor_parity(
    monkeypatch,
) -> None:
    shared_repository = InMemoryProjectRepository()
    owner_only_policy = {
        "project_owner_actor_id": "owner-1",
        "strict_mode": True,
        "action_rules": {
            "external_api_send": {
                "allowed_roles": ["owner"],
            }
        },
    }
    token_seed = (
        "owner-token:owner-1:owner:human,"
        "approver-token:approver-1:approver:human,"
        "viewer-token:viewer-1:viewer:human"
    )
    try:
        _clear_auth_caches()
        seed_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            token_seed,
        )
        project_id = _run_waiting_approval_project(seed_client, owner_only_policy)

        direct_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            token_seed,
        )
        denied_status, denied_detail = _direct_resume_outcome(
            direct_client,
            project_id=project_id,
            token="owner-token",
            approved_actions=["external_api_send"],
            runtime_actor_ids_override={"external_api_send": []},
        )
        assert denied_status == 403
        assert "allowed actor IDs" in denied_detail

        api_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            token_seed,
        )
        _drop_app_runtime_bindings(api_client)

        invalid_before = api_client.post(
            "/orchestrator/resume/approval",
            json={
                "project_id": project_id,
                "approved_actions": ["external_api_send"],
                "trend_provider": "gemini",
            },
            headers={"Authorization": "Bearer invalid-token"},
        )
        owner_success = api_client.post(
            "/orchestrator/resume/approval",
            json={
                "project_id": project_id,
                "approved_actions": ["external_api_send"],
                "trend_provider": "gemini",
            },
            headers={"Authorization": "Bearer owner-token"},
        )
        approver_retry = api_client.post(
            "/orchestrator/resume/approval",
            json={
                "project_id": project_id,
                "approved_actions": ["external_api_send"],
                "trend_provider": "gemini",
            },
            headers={"Authorization": "Bearer approver-token"},
        )
        viewer_retry = api_client.post(
            "/orchestrator/resume/approval",
            json={
                "project_id": project_id,
                "approved_actions": ["external_api_send"],
                "trend_provider": "gemini",
            },
            headers={"Authorization": "Bearer viewer-token"},
        )
        invalid_after = api_client.post(
            "/orchestrator/resume/approval",
            json={
                "project_id": project_id,
                "approved_actions": ["external_api_send"],
                "trend_provider": "gemini",
            },
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert invalid_before.status_code == 401
        assert owner_success.status_code == 200
        assert owner_success.json()["summary"]["status"] == ProjectStatus.COMPLETED.value
        assert approver_retry.status_code == 200
        assert viewer_retry.status_code == 200
        assert invalid_after.status_code == 401
        assert approver_retry.json()["summary"]["status"] == ProjectStatus.COMPLETED.value
        assert viewer_retry.json()["summary"]["status"] == ProjectStatus.COMPLETED.value
        assert approver_retry.json()["summary"]["next_steps"] == viewer_retry.json()["summary"][
            "next_steps"
        ]

        direct_status, direct_detail = _direct_resume_outcome(
            api_client,
            project_id=project_id,
            token="approver-token",
            approved_actions=["external_api_send"],
        )
        assert direct_status == 200
        assert direct_detail == ProjectStatus.COMPLETED.value

        audit = api_client.get(f"/projects/{project_id}/audit").json()
        assert len(
            [
                event
                for event in audit["events"]
                if event["event_type"] == "policy_override_applied"
                and event["metadata"].get("policy_source") == "project_runtime_override"
            ]
        ) == 1
        assert len(
            [event for event in audit["events"] if event["event_type"] == "authorization_failed"]
        ) == 1
        assert len(
            [
                event
                for event in audit["events"]
                if event["event_type"] == "resume_triggered"
                and event["metadata"].get("mode") == "approval_resume"
            ]
        ) == 1
    finally:
        _clear_auth_caches()


def test_shared_repo_state_initial_orchestrator_snapshot_recovers_when_app_snapshot_missing(
    monkeypatch,
) -> None:
    shared_repository = InMemoryProjectRepository()
    try:
        _clear_auth_caches()
        client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "seed-one:approver-one:approver:human",
        )
        project_id = _run_waiting_approval_project(client)
        _drop_app_orchestrator_bindings(client, drop_app_snapshot=True)

        audit = client.get(f"/projects/{project_id}/audit")
        assert audit.status_code == 200
        assert client.app.state.orchestrator.repository is shared_repository
        assert client.app.state._initial_orchestrator is client.app.state.orchestrator
        assert client.app._initial_orchestrator is client.app.state.orchestrator
    finally:
        _clear_auth_caches()


def test_shared_repo_revision_state_gap_keeps_401_404_409_precedence_and_direct_parity(
    monkeypatch,
) -> None:
    shared_repository = InMemoryProjectRepository()
    try:
        _clear_auth_caches()
        client_one = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "seed-one:approver-one:approver:human",
        )
        waiting_project = _run_waiting_approval_project(client_one)

        client_two = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "seed-two:approver-two:approver:human",
        )
        _drop_app_runtime_bindings(client_two, drop_app_orchestrator_snapshot=True)

        unauthorized_missing = client_two.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": "missing-project",
                "resume_mode": "replanning",
                "reason": "unauthorized missing",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer invalid-token"},
        )
        unauthorized_conflict = client_two.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": waiting_project,
                "resume_mode": "replanning",
                "reason": "unauthorized conflict",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert unauthorized_missing.status_code == 401
        assert unauthorized_conflict.status_code == 401

        missing = client_two.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": "missing-project",
                "resume_mode": "replanning",
                "reason": "missing with valid token",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer seed-two"},
        )
        conflict = client_two.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": waiting_project,
                "resume_mode": "replanning",
                "reason": "conflict with valid token",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer seed-two"},
        )
        assert missing.status_code == 404
        assert conflict.status_code == 409
        assert "Project not found: missing-project" in missing.json()["detail"]
        assert "current: waiting_approval" in conflict.json()["detail"]

        direct_status, direct_detail = _direct_revision_resume_outcome(
            client_two,
            project_id=waiting_project,
            token="seed-two",
            resume_mode=RevisionResumeMode.REPLANNING,
            reason="direct conflict parity",
        )
        assert direct_status == 409
        assert direct_detail == conflict.json()["detail"]
        assert client_two.app.state.orchestrator.repository is shared_repository
    finally:
        _clear_auth_caches()


def test_shared_repo_replanning_start_state_gap_keeps_401_404_409_precedence_and_direct_parity(
    monkeypatch,
) -> None:
    shared_repository = InMemoryProjectRepository()
    try:
        _clear_auth_caches()
        client_one = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "seed-one:approver-one:approver:human",
        )
        waiting_project = _run_waiting_approval_project(client_one)

        client_two = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "seed-two:approver-two:approver:human",
        )
        _drop_app_runtime_bindings(client_two, drop_app_orchestrator_snapshot=True)

        unauthorized_missing = client_two.post(
            "/orchestrator/replanning/start",
            json={
                "project_id": "missing-project",
                "note": "unauthorized missing",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer invalid-token"},
        )
        unauthorized_conflict = client_two.post(
            "/orchestrator/replanning/start",
            json={
                "project_id": waiting_project,
                "note": "unauthorized conflict",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert unauthorized_missing.status_code == 401
        assert unauthorized_conflict.status_code == 401

        missing = client_two.post(
            "/orchestrator/replanning/start",
            json={
                "project_id": "missing-project",
                "note": "missing with valid token",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer seed-two"},
        )
        conflict = client_two.post(
            "/orchestrator/replanning/start",
            json={
                "project_id": waiting_project,
                "note": "conflict with valid token",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer seed-two"},
        )
        assert missing.status_code == 404
        assert conflict.status_code == 409
        assert "Project not found: missing-project" in missing.json()["detail"]
        assert "current: waiting_approval" in conflict.json()["detail"]

        direct_status, direct_detail = _direct_replanning_start_outcome(
            client_two,
            project_id=waiting_project,
            token="seed-two",
            note="direct conflict parity",
        )
        assert direct_status == 409
        assert direct_detail == conflict.json()["detail"]
        assert client_two.app.state.orchestrator.repository is shared_repository
    finally:
        _clear_auth_caches()


def test_malformed_to_corrected_env_flip_state_initial_orchestrator_parity_under_revision_retry(
    monkeypatch,
) -> None:
    shared_repository = InMemoryProjectRepository()
    try:
        _clear_auth_caches()
        malformed_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "malformed-seed-without-colons",
            dev_auth_enabled="definitely-not-bool",
        )
        project_id = _run_revision_requested_project(malformed_client)

        corrected_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "seed-two:operator-two:operator:human",
            dev_auth_enabled="true",
        )
        _drop_app_runtime_bindings(
            corrected_client,
            drop_app_orchestrator_snapshot=True,
        )

        corrected_wrong = corrected_client.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "rebuilding",
                "reason": "seed mismatch after corrected env flip",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer dev-operator-token"},
        )
        corrected_right = corrected_client.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "rebuilding",
                "reason": "corrected token after state snapshot recovery",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer seed-two"},
        )
        assert corrected_wrong.status_code == 401
        assert corrected_right.status_code == 200
        assert corrected_right.json()["summary"]["status"] == ProjectStatus.COMPLETED.value
        assert corrected_client.app.state.orchestrator.repository is shared_repository
    finally:
        _clear_auth_caches()


def test_shared_repo_bootstrap_snapshots_prevent_cross_app_seed_bleed_when_primary_bindings_missing(
    monkeypatch,
) -> None:
    shared_repository = InMemoryProjectRepository()
    try:
        _clear_auth_caches()
        client_one = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "seed-one:approver-one:approver:human",
        )
        project_id = _run_waiting_approval_project(client_one)

        _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "seed-two:approver-two:approver:human",
        )

        _drop_app_runtime_bindings(
            client_one,
            drop_app_auth_snapshot=True,
            drop_app_orchestrator_snapshot=True,
        )

        assert hasattr(client_one.app.state, "_bootstrap_auth_service")
        assert hasattr(client_one.app.state, "_bootstrap_orchestrator")

        wrong_seed = client_one.post(
            "/orchestrator/resume/approval",
            json={
                "project_id": project_id,
                "approved_actions": ["external_api_send"],
                "trend_provider": "gemini",
            },
            headers={"Authorization": "Bearer seed-two"},
        )
        right_seed = client_one.post(
            "/orchestrator/resume/approval",
            json={
                "project_id": project_id,
                "approved_actions": ["external_api_send"],
                "trend_provider": "gemini",
            },
            headers={"Authorization": "Bearer seed-one"},
        )
        assert wrong_seed.status_code == 401
        assert right_seed.status_code == 200
        assert right_seed.json()["summary"]["status"] == ProjectStatus.COMPLETED.value
        assert client_one.app.state.auth_service is client_one.app.state._bootstrap_auth_service
        assert client_one.app.state.orchestrator is client_one.app.state._bootstrap_orchestrator
        assert client_one.app.state.orchestrator.repository is shared_repository
    finally:
        _clear_auth_caches()


def test_shared_repo_bootstrap_only_state_gap_keeps_resume_approval_precedence_and_direct_parity(
    monkeypatch,
) -> None:
    shared_repository = InMemoryProjectRepository()
    owner_only_policy = {
        "project_owner_actor_id": "owner-1",
        "strict_mode": True,
        "action_rules": {
            "external_api_send": {
                "allowed_roles": ["owner"],
            }
        },
    }
    try:
        _clear_auth_caches()
        client_one = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "seed-one:owner-1:owner:human",
        )
        project_forbidden = _run_waiting_approval_project(client_one, owner_only_policy)
        project_conflict = _run_waiting_approval_project(client_one)
        rejected = client_one.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_conflict,
                "rejected_actions": ["external_api_send"],
                "reason": "prepare revision conflict for bootstrap-only state gap test",
            },
            headers={"Authorization": "Bearer seed-one"},
        )
        assert rejected.status_code == 200
        assert rejected.json()["summary"]["status"] == ProjectStatus.REVISION_REQUESTED.value

        client_two = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "seed-two:approver-two:approver:human",
        )
        _drop_app_runtime_bindings(
            client_two,
            drop_app_auth_snapshot=True,
            drop_app_orchestrator_snapshot=True,
        )

        assert hasattr(client_two.app.state, "_bootstrap_auth_service")
        assert hasattr(client_two.app.state, "_bootstrap_orchestrator")

        unauthorized_missing = client_two.post(
            "/orchestrator/resume/approval",
            json={"project_id": "missing-project", "approved_actions": ["external_api_send"]},
            headers={"Authorization": "Bearer invalid-token"},
        )
        unauthorized_forbidden = client_two.post(
            "/orchestrator/resume/approval",
            json={"project_id": project_forbidden, "approved_actions": ["external_api_send"]},
            headers={"Authorization": "Bearer invalid-token"},
        )
        unauthorized_conflict = client_two.post(
            "/orchestrator/resume/approval",
            json={"project_id": project_conflict, "approved_actions": ["external_api_send"]},
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert unauthorized_missing.status_code == 401
        assert unauthorized_forbidden.status_code == 401
        assert unauthorized_conflict.status_code == 401

        missing = client_two.post(
            "/orchestrator/resume/approval",
            json={"project_id": "missing-project", "approved_actions": ["external_api_send"]},
            headers={"Authorization": "Bearer seed-two"},
        )
        forbidden = client_two.post(
            "/orchestrator/resume/approval",
            json={"project_id": project_forbidden, "approved_actions": ["external_api_send"]},
            headers={"Authorization": "Bearer seed-two"},
        )
        conflict = client_two.post(
            "/orchestrator/resume/approval",
            json={"project_id": project_conflict, "approved_actions": ["external_api_send"]},
            headers={"Authorization": "Bearer seed-two"},
        )
        assert missing.status_code == 404
        assert forbidden.status_code == 403
        assert conflict.status_code == 409
        assert "Project not found: missing-project" in missing.json()["detail"]
        assert "current: revision_requested" in conflict.json()["detail"]

        direct_status, direct_detail = _direct_resume_outcome(
            client_two,
            project_id=project_conflict,
            token="seed-two",
            approved_actions=["external_api_send"],
        )
        assert direct_status == 409
        assert direct_detail == conflict.json()["detail"]
        assert client_two.app.state.auth_service is client_two.app.state._bootstrap_auth_service
        assert client_two.app.state.orchestrator is client_two.app.state._bootstrap_orchestrator
        assert client_two.app.state.orchestrator.repository is shared_repository
    finally:
        _clear_auth_caches()


def test_shared_repo_bootstrap_only_state_gap_keeps_reject_precedence_and_direct_parity(
    monkeypatch,
) -> None:
    shared_repository = InMemoryProjectRepository()
    owner_only_policy = {
        "project_owner_actor_id": "owner-1",
        "strict_mode": True,
        "action_rules": {
            "external_api_send": {
                "allowed_roles": ["owner"],
            }
        },
    }
    try:
        _clear_auth_caches()
        client_one = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "seed-one:owner-1:owner:human",
        )
        project_forbidden = _run_waiting_approval_project(client_one, owner_only_policy)
        project_conflict = _run_completed_project(client_one)

        client_two = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "seed-two:approver-two:approver:human",
        )
        _drop_app_runtime_bindings(
            client_two,
            drop_app_auth_snapshot=True,
            drop_app_orchestrator_snapshot=True,
        )

        unauthorized_missing = client_two.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": "missing-project",
                "rejected_actions": ["external_api_send"],
                "reason": "invalid token should keep 401 precedence for missing",
            },
            headers={"Authorization": "Bearer invalid-token"},
        )
        unauthorized_forbidden = client_two.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_forbidden,
                "rejected_actions": ["external_api_send"],
                "reason": "invalid token should keep 401 precedence for forbidden",
            },
            headers={"Authorization": "Bearer invalid-token"},
        )
        unauthorized_conflict = client_two.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_conflict,
                "rejected_actions": ["external_api_send"],
                "reason": "invalid token should keep 401 precedence for conflict",
            },
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert unauthorized_missing.status_code == 401
        assert unauthorized_forbidden.status_code == 401
        assert unauthorized_conflict.status_code == 401

        missing = client_two.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": "missing-project",
                "rejected_actions": ["external_api_send"],
                "reason": "valid token should surface 404 missing",
            },
            headers={"Authorization": "Bearer seed-two"},
        )
        forbidden = client_two.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_forbidden,
                "rejected_actions": ["external_api_send"],
                "reason": "valid token should surface 403 forbidden",
            },
            headers={"Authorization": "Bearer seed-two"},
        )
        conflict = client_two.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_conflict,
                "rejected_actions": ["external_api_send"],
                "reason": "valid token should surface 409 conflict",
            },
            headers={"Authorization": "Bearer seed-two"},
        )
        assert missing.status_code == 404
        assert forbidden.status_code == 403
        assert conflict.status_code == 409
        assert "Project not found: missing-project" in missing.json()["detail"]
        assert "current: completed" in conflict.json()["detail"]

        direct_status, direct_detail = _direct_reject_outcome(
            client_two,
            project_id=project_conflict,
            token="seed-two",
            rejected_actions=["external_api_send"],
            reason="direct reject conflict parity",
        )
        assert direct_status == 409
        assert direct_detail == conflict.json()["detail"]
        assert client_two.app.state.auth_service is client_two.app.state._bootstrap_auth_service
        assert client_two.app.state.orchestrator is client_two.app.state._bootstrap_orchestrator
        assert client_two.app.state.orchestrator.repository is shared_repository
    finally:
        _clear_auth_caches()


def test_shared_repo_bootstrap_only_gap_keeps_rebuilding_retry_event_immutable_across_roles(
    monkeypatch,
) -> None:
    shared_repository = InMemoryProjectRepository()
    token_seed = (
        "owner-token:owner-1:owner:human,"
        "approver-token:approver-1:approver:human,"
        "viewer-token:viewer-1:viewer:human"
    )
    try:
        _clear_auth_caches()
        seed_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            token_seed,
        )
        project_id = _run_revision_requested_project(seed_client)

        retry_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            token_seed,
        )
        _drop_app_runtime_bindings(
            retry_client,
            drop_app_auth_snapshot=True,
            drop_app_orchestrator_snapshot=True,
        )

        invalid_retry = retry_client.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "rebuilding",
                "reason": "invalid token retry should remain unauthorized",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer invalid-token"},
        )
        owner_resume = retry_client.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "rebuilding",
                "reason": "  first rebuilding resume reason should be preserved  ",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer owner-token"},
        )
        approver_retry = retry_client.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "rebuilding",
                "reason": "approver retry should be idempotent and not mutate first reason",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer approver-token"},
        )
        viewer_retry = retry_client.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "rebuilding",
                "reason": "viewer retry should be idempotent and not mutate first reason",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer viewer-token"},
        )
        assert invalid_retry.status_code == 401
        assert owner_resume.status_code == 200
        assert approver_retry.status_code == 200
        assert viewer_retry.status_code == 200
        assert owner_resume.json()["summary"]["status"] == ProjectStatus.COMPLETED.value
        assert approver_retry.json()["summary"]["status"] == ProjectStatus.COMPLETED.value
        assert viewer_retry.json()["summary"]["status"] == ProjectStatus.COMPLETED.value

        direct_status, direct_detail = _direct_revision_resume_outcome(
            retry_client,
            project_id=project_id,
            token="owner-token",
            resume_mode=RevisionResumeMode.REBUILDING,
            reason="direct rebuilding retry parity",
        )
        assert direct_status == 200
        assert direct_detail == ProjectStatus.COMPLETED.value

        audit = retry_client.get(f"/projects/{project_id}/audit").json()
        rebuilding_resume_events = [
            event
            for event in audit["events"]
            if event["event_type"] == "resume_triggered"
            and event["metadata"].get("mode") == RevisionResumeMode.REBUILDING.value
        ]
        assert len(rebuilding_resume_events) == 1
        assert (
            rebuilding_resume_events[0]["reason"]
            == "first rebuilding resume reason should be preserved"
        )
        assert retry_client.app.state.auth_service is retry_client.app.state._bootstrap_auth_service
        assert retry_client.app.state.orchestrator is retry_client.app.state._bootstrap_orchestrator
    finally:
        _clear_auth_caches()


def test_malformed_to_corrected_env_flip_bootstrap_only_gap_keeps_reject_retry_parity(
    monkeypatch,
) -> None:
    shared_repository = InMemoryProjectRepository()
    try:
        _clear_auth_caches()
        malformed_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "malformed-seed-without-colons",
            dev_auth_enabled="definitely-not-bool",
        )
        project_id = _run_waiting_approval_project(malformed_client)

        corrected_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "seed-two:approver-two:approver:human",
            dev_auth_enabled="true",
        )
        _drop_app_runtime_bindings(
            corrected_client,
            drop_app_auth_snapshot=True,
            drop_app_orchestrator_snapshot=True,
        )

        corrected_wrong = corrected_client.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_id,
                "rejected_actions": ["external_api_send"],
                "reason": "malformed-token actor should not pass after corrected env",
            },
            headers={"Authorization": "Bearer dev-approver-token"},
        )
        corrected_right = corrected_client.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_id,
                "rejected_actions": ["external_api_send"],
                "reason": "  corrected token reject reason should be preserved  ",
                "note": " first corrected reject note ",
            },
            headers={"Authorization": "Bearer seed-two"},
        )
        corrected_retry = corrected_client.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_id,
                "rejected_actions": ["external_api_send"],
                "reason": "retry after revision should be idempotent",
                "note": "retry note must not mutate first rejection note",
            },
            headers={"Authorization": "Bearer seed-two"},
        )
        assert corrected_wrong.status_code == 401
        assert corrected_right.status_code == 200
        assert corrected_retry.status_code == 200
        assert corrected_right.json()["summary"]["status"] == ProjectStatus.REVISION_REQUESTED.value
        assert corrected_retry.json()["summary"]["status"] == ProjectStatus.REVISION_REQUESTED.value

        direct_status, direct_detail = _direct_reject_outcome(
            corrected_client,
            project_id=project_id,
            token="seed-two",
            rejected_actions=["external_api_send"],
            reason="direct reject parity after corrected retry",
            note="direct retry note",
        )
        assert direct_status == 200
        assert direct_detail == ProjectStatus.REVISION_REQUESTED.value

        audit = corrected_client.get(f"/projects/{project_id}/audit").json()
        rejection_events = [
            event for event in audit["events"] if event["event_type"] == "approval_rejected"
        ]
        assert len(rejection_events) == 1
        assert rejection_events[0]["reason"] == "corrected token reject reason should be preserved"
        assert rejection_events[0]["metadata"].get("note") == "first corrected reject note"
    finally:
        _clear_auth_caches()


def test_shared_repo_bootstrap_only_gap_keeps_explicit_empty_override_vs_omitted_parity(
    monkeypatch,
) -> None:
    shared_repository = InMemoryProjectRepository()
    owner_only_policy = {
        "project_owner_actor_id": "owner-1",
        "strict_mode": True,
        "action_rules": {
            "external_api_send": {
                "allowed_roles": ["owner"],
            }
        },
    }
    token_seed = (
        "owner-token:owner-1:owner:human,"
        "approver-token:approver-1:approver:human,"
        "viewer-token:viewer-1:viewer:human"
    )
    try:
        _clear_auth_caches()
        seed_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            token_seed,
        )
        project_id = _run_waiting_approval_project(seed_client, owner_only_policy)

        direct_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            token_seed,
        )
        denied_status, denied_detail = _direct_resume_outcome(
            direct_client,
            project_id=project_id,
            token="owner-token",
            approved_actions=["external_api_send"],
            runtime_actor_ids_override={"external_api_send": []},
        )
        assert denied_status == 403
        assert "allowed actor IDs" in denied_detail

        api_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            token_seed,
        )
        _drop_app_runtime_bindings(
            api_client,
            drop_app_auth_snapshot=True,
            drop_app_orchestrator_snapshot=True,
        )

        invalid_before = api_client.post(
            "/orchestrator/resume/approval",
            json={
                "project_id": project_id,
                "approved_actions": ["external_api_send"],
                "trend_provider": "gemini",
            },
            headers={"Authorization": "Bearer invalid-token"},
        )
        owner_success = api_client.post(
            "/orchestrator/resume/approval",
            json={
                "project_id": project_id,
                "approved_actions": ["external_api_send"],
                "trend_provider": "gemini",
            },
            headers={"Authorization": "Bearer owner-token"},
        )
        approver_retry = api_client.post(
            "/orchestrator/resume/approval",
            json={
                "project_id": project_id,
                "approved_actions": ["external_api_send"],
                "trend_provider": "gemini",
            },
            headers={"Authorization": "Bearer approver-token"},
        )
        viewer_retry = api_client.post(
            "/orchestrator/resume/approval",
            json={
                "project_id": project_id,
                "approved_actions": ["external_api_send"],
                "trend_provider": "gemini",
            },
            headers={"Authorization": "Bearer viewer-token"},
        )
        invalid_after = api_client.post(
            "/orchestrator/resume/approval",
            json={
                "project_id": project_id,
                "approved_actions": ["external_api_send"],
                "trend_provider": "gemini",
            },
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert invalid_before.status_code == 401
        assert owner_success.status_code == 200
        assert approver_retry.status_code == 200
        assert viewer_retry.status_code == 200
        assert invalid_after.status_code == 401
        assert owner_success.json()["summary"]["status"] == ProjectStatus.COMPLETED.value
        assert approver_retry.json()["summary"]["status"] == ProjectStatus.COMPLETED.value
        assert viewer_retry.json()["summary"]["status"] == ProjectStatus.COMPLETED.value

        audit = api_client.get(f"/projects/{project_id}/audit").json()
        assert len(
            [
                event
                for event in audit["events"]
                if event["event_type"] == "policy_override_applied"
                and event["metadata"].get("policy_source") == "project_runtime_override"
            ]
        ) == 1
        assert len(
            [event for event in audit["events"] if event["event_type"] == "authorization_failed"]
        ) == 1
        assert len(
            [
                event
                for event in audit["events"]
                if event["event_type"] == "resume_triggered"
                and event["metadata"].get("mode") == "approval_resume"
            ]
        ) == 1
    finally:
        _clear_auth_caches()


def test_shared_repo_app_bootstrap_only_recovery_keeps_seed_parity_with_state_bootstrap_missing(
    monkeypatch,
) -> None:
    shared_repository = InMemoryProjectRepository()
    try:
        _clear_auth_caches()
        client_one = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "seed-one:approver-one:approver:human",
        )
        project_id = _run_waiting_approval_project(client_one)

        _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "seed-two:approver-two:approver:human",
        )

        _drop_app_runtime_bindings(
            client_one,
            drop_app_auth_snapshot=True,
            drop_app_orchestrator_snapshot=True,
            drop_state_bootstrap_snapshots=True,
        )

        assert hasattr(client_one.app, "_bootstrap_auth_service")
        assert hasattr(client_one.app, "_bootstrap_orchestrator")

        wrong_seed = client_one.post(
            "/orchestrator/resume/approval",
            json={
                "project_id": project_id,
                "approved_actions": ["external_api_send"],
                "trend_provider": "gemini",
            },
            headers={"Authorization": "Bearer seed-two"},
        )
        right_seed = client_one.post(
            "/orchestrator/resume/approval",
            json={
                "project_id": project_id,
                "approved_actions": ["external_api_send"],
                "trend_provider": "gemini",
            },
            headers={"Authorization": "Bearer seed-one"},
        )
        assert wrong_seed.status_code == 401
        assert right_seed.status_code == 200
        assert right_seed.json()["summary"]["status"] == ProjectStatus.COMPLETED.value
        assert client_one.app.state.auth_service is client_one.app._bootstrap_auth_service
        assert client_one.app.state.orchestrator is client_one.app._bootstrap_orchestrator
        assert client_one.app.state.orchestrator.repository is shared_repository
    finally:
        _clear_auth_caches()


def test_malformed_to_corrected_env_flip_app_bootstrap_only_gap_keeps_revision_retry_parity(
    monkeypatch,
) -> None:
    shared_repository = InMemoryProjectRepository()
    try:
        _clear_auth_caches()
        malformed_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "malformed-seed-without-colons",
            dev_auth_enabled="definitely-not-bool",
        )
        project_id = _run_revision_requested_project(malformed_client)

        corrected_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "seed-two:operator-two:operator:human",
            dev_auth_enabled="true",
        )
        _drop_app_runtime_bindings(
            corrected_client,
            drop_app_auth_snapshot=True,
            drop_app_orchestrator_snapshot=True,
            drop_state_bootstrap_snapshots=True,
        )

        corrected_wrong = corrected_client.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "rereview",
                "reason": "old malformed seed token should fail after corrected env",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer dev-operator-token"},
        )
        corrected_right = corrected_client.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "rereview",
                "reason": "corrected app bootstrap token should pass",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer seed-two"},
        )
        assert corrected_wrong.status_code == 401
        assert corrected_right.status_code == 200
        assert corrected_right.json()["summary"]["status"] == ProjectStatus.COMPLETED.value

        direct_status, direct_detail = _direct_revision_resume_outcome(
            corrected_client,
            project_id=project_id,
            token="seed-two",
            resume_mode=RevisionResumeMode.REREVIEW,
            reason="direct parity after corrected app-bootstrap gap",
        )
        assert direct_status == 200
        assert direct_detail == ProjectStatus.COMPLETED.value
        assert (
            corrected_client.app.state.auth_service
            is corrected_client.app._bootstrap_auth_service
        )
        assert (
            corrected_client.app.state.orchestrator is corrected_client.app._bootstrap_orchestrator
        )
        assert corrected_client.app.state.orchestrator.repository is shared_repository
    finally:
        _clear_auth_caches()


def test_malformed_to_corrected_env_flip_app_bootstrap_only_keeps_mixed_retry_subsequence_stable(
    monkeypatch,
) -> None:
    shared_repository = InMemoryProjectRepository()
    corrected_seed = (
        "approver-token:approver-1:approver:human,"
        "operator-token:operator-1:operator:human"
    )
    try:
        _clear_auth_caches()
        malformed_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "malformed-seed-without-colons",
            dev_auth_enabled="definitely-not-bool",
        )
        project_id = _run_waiting_approval_project(malformed_client)

        corrected_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            corrected_seed,
            dev_auth_enabled="true",
        )
        _drop_app_runtime_bindings(
            corrected_client,
            drop_app_auth_snapshot=True,
            drop_app_orchestrator_snapshot=True,
            drop_state_bootstrap_snapshots=True,
        )

        invalid_resume = corrected_client.post(
            "/orchestrator/resume/approval",
            json={
                "project_id": project_id,
                "approved_actions": ["external_api_send"],
                "trend_provider": "gemini",
            },
            headers={"Authorization": "Bearer dev-approver-token"},
        )
        approved = corrected_client.post(
            "/orchestrator/resume/approval",
            json={
                "project_id": project_id,
                "approved_actions": ["external_api_send"],
                "trend_provider": "gemini",
            },
            headers={"Authorization": "Bearer approver-token"},
        )
        rejected = corrected_client.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_id,
                "rejected_actions": ["external_api_send"],
                "reason": (
                    "reject after completion should conflict under corrected bootstrap fallback"
                ),
            },
            headers={"Authorization": "Bearer approver-token"},
        )
        assert invalid_resume.status_code == 401
        assert approved.status_code == 200
        assert approved.json()["summary"]["status"] == ProjectStatus.COMPLETED.value
        assert rejected.status_code == 409

        revision_project = _run_revision_requested_project(corrected_client)
        resumed = corrected_client.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": revision_project,
                "resume_mode": "replanning",
                "reason": "corrected bootstrap app should keep replanning path stable",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer operator-token"},
        )
        started = corrected_client.post(
            "/orchestrator/replanning/start",
            json={
                "project_id": revision_project,
                "note": "corrected bootstrap app starts replanning",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer operator-token"},
        )
        repeated_start = corrected_client.post(
            "/orchestrator/replanning/start",
            json={
                "project_id": revision_project,
                "note": "retry should stay idempotent and preserve first note",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer operator-token"},
        )
        assert resumed.status_code == 200
        assert started.status_code == 200
        assert repeated_start.status_code == 200
        assert resumed.json()["summary"]["status"] == ProjectStatus.READY_FOR_PLANNING.value
        assert started.json()["summary"]["status"] == ProjectStatus.COMPLETED.value
        assert repeated_start.json()["summary"]["status"] == ProjectStatus.COMPLETED.value

        direct_status, direct_detail = _direct_replanning_start_outcome(
            corrected_client,
            project_id=revision_project,
            token="operator-token",
            note="direct parity for corrected app-bootstrap replanning retry",
        )
        assert direct_status == 200
        assert direct_detail == ProjectStatus.COMPLETED.value

        audit = corrected_client.get(f"/projects/{revision_project}/audit").json()
        replanning_started_events = [
            event for event in audit["events"] if event["event_type"] == "replanning_started"
        ]
        resume_replanning_events = [
            event
            for event in audit["events"]
            if event["event_type"] == "resume_triggered"
            and event["metadata"].get("mode") == RevisionResumeMode.REPLANNING.value
        ]
        assert len(replanning_started_events) == 1
        assert len(resume_replanning_events) == 1
        assert (
            corrected_client.app.state.auth_service
            is corrected_client.app._bootstrap_auth_service
        )
        assert (
            corrected_client.app.state.orchestrator is corrected_client.app._bootstrap_orchestrator
        )
        assert corrected_client.app.state.orchestrator.repository is shared_repository
    finally:
        _clear_auth_caches()


def test_malformed_to_corrected_env_flip_app_bootstrap_only_keeps_override_parity_across_roles(
    monkeypatch,
) -> None:
    shared_repository = InMemoryProjectRepository()
    owner_policy = {
        "project_owner_actor_id": "owner-1",
        "strict_mode": True,
        "action_rules": {
            "external_api_send": {
                "allowed_roles": ["owner"],
            }
        },
    }
    corrected_seed = (
        "owner-token:owner-1:owner:human,"
        "approver-token:approver-1:approver:human,"
        "viewer-token:viewer-1:viewer:human"
    )
    try:
        _clear_auth_caches()
        malformed_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "malformed-seed-without-colons",
            dev_auth_enabled="definitely-not-bool",
        )
        project_id = _run_waiting_approval_project(malformed_client, owner_policy)

        corrected_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            corrected_seed,
            dev_auth_enabled="true",
        )
        _drop_app_runtime_bindings(
            corrected_client,
            drop_app_auth_snapshot=True,
            drop_app_orchestrator_snapshot=True,
            drop_state_bootstrap_snapshots=True,
        )

        denied_status, denied_detail = _direct_resume_outcome(
            corrected_client,
            project_id=project_id,
            token="owner-token",
            approved_actions=["external_api_send"],
            runtime_actor_ids_override={"external_api_send": []},
        )
        assert denied_status == 403
        assert "allowed actor IDs" in denied_detail

        invalid_before = corrected_client.post(
            "/orchestrator/resume/approval",
            json={
                "project_id": project_id,
                "approved_actions": ["external_api_send"],
                "trend_provider": "gemini",
            },
            headers={"Authorization": "Bearer invalid-token"},
        )
        owner_success = corrected_client.post(
            "/orchestrator/resume/approval",
            json={
                "project_id": project_id,
                "approved_actions": ["external_api_send"],
                "trend_provider": "gemini",
            },
            headers={"Authorization": "Bearer owner-token"},
        )
        approver_retry = corrected_client.post(
            "/orchestrator/resume/approval",
            json={
                "project_id": project_id,
                "approved_actions": ["external_api_send"],
                "trend_provider": "gemini",
            },
            headers={"Authorization": "Bearer approver-token"},
        )
        viewer_retry = corrected_client.post(
            "/orchestrator/resume/approval",
            json={
                "project_id": project_id,
                "approved_actions": ["external_api_send"],
                "trend_provider": "gemini",
            },
            headers={"Authorization": "Bearer viewer-token"},
        )
        invalid_after = corrected_client.post(
            "/orchestrator/resume/approval",
            json={
                "project_id": project_id,
                "approved_actions": ["external_api_send"],
                "trend_provider": "gemini",
            },
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert invalid_before.status_code == 401
        assert owner_success.status_code == 200
        assert approver_retry.status_code == 200
        assert viewer_retry.status_code == 200
        assert invalid_after.status_code == 401

        direct_status, direct_detail = _direct_resume_outcome(
            corrected_client,
            project_id=project_id,
            token="owner-token",
            approved_actions=["external_api_send"],
        )
        assert direct_status == 200
        assert direct_detail == ProjectStatus.COMPLETED.value

        audit = corrected_client.get(f"/projects/{project_id}/audit").json()
        assert len(
            [
                event
                for event in audit["events"]
                if event["event_type"] == "policy_override_applied"
                and event["metadata"].get("policy_source") == "project_runtime_override"
            ]
        ) == 1
        assert len(
            [event for event in audit["events"] if event["event_type"] == "authorization_failed"]
        ) == 1
        assert len(
            [
                event
                for event in audit["events"]
                if event["event_type"] == "resume_triggered"
                and event["metadata"].get("mode") == "approval_resume"
            ]
        ) == 1
        assert (
            corrected_client.app.state.auth_service
            is corrected_client.app._bootstrap_auth_service
        )
        assert (
            corrected_client.app.state.orchestrator is corrected_client.app._bootstrap_orchestrator
        )
    finally:
        _clear_auth_caches()


def test_app_bootstrap_only_combined_reject_resume_replanning_conflict_paths_keep_parity(
    monkeypatch,
) -> None:
    shared_repository = InMemoryProjectRepository()
    owner_policy = {
        "project_owner_actor_id": "owner-1",
        "strict_mode": True,
        "action_rules": {
            "external_api_send": {
                "allowed_roles": ["owner"],
            }
        },
    }
    token_seed = (
        "owner-token:owner-1:owner:human,"
        "approver-token:approver-1:approver:human,"
        "operator-token:operator-1:operator:human,"
        "viewer-token:viewer-1:viewer:human"
    )
    try:
        _clear_auth_caches()
        seed_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            token_seed,
        )
        project_id = _run_waiting_approval_project(seed_client, owner_policy)

        pre_invalid = seed_client.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_id,
                "rejected_actions": ["external_api_send"],
                "reason": "invalid actor should fail first",
            },
            headers={"Authorization": "Bearer invalid-token"},
        )
        pre_forbidden = seed_client.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_id,
                "rejected_actions": ["external_api_send"],
                "reason": "viewer reject should be forbidden by owner-only policy",
            },
            headers={"Authorization": "Bearer viewer-token"},
        )
        rejected = seed_client.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_id,
                "rejected_actions": ["external_api_send"],
                "reason": "owner reject moves project to revision lane",
                "note": "reject note should remain immutable",
            },
            headers={"Authorization": "Bearer owner-token"},
        )
        assert pre_invalid.status_code == 401
        assert pre_forbidden.status_code == 403
        assert rejected.status_code == 200
        assert rejected.json()["summary"]["status"] == ProjectStatus.REVISION_REQUESTED.value

        lifecycle_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            token_seed,
        )
        _drop_app_runtime_bindings(
            lifecycle_client,
            drop_app_auth_snapshot=True,
            drop_app_orchestrator_snapshot=True,
            drop_state_bootstrap_snapshots=True,
        )

        invalid_missing = lifecycle_client.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": "missing-project",
                "resume_mode": "replanning",
                "reason": "invalid missing should remain unauthorized",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer invalid-token"},
        )
        invalid_conflict = lifecycle_client.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "replanning",
                "reason": "invalid conflict should remain unauthorized",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer invalid-token"},
        )
        missing = lifecycle_client.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": "missing-project",
                "resume_mode": "replanning",
                "reason": "valid token should surface missing before conflict",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer operator-token"},
        )
        resumed = lifecycle_client.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "replanning",
                "reason": "operator resumes into replanning lane",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer operator-token"},
        )
        started = lifecycle_client.post(
            "/orchestrator/replanning/start",
            json={
                "project_id": project_id,
                "note": "operator starts replanning execution",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer operator-token"},
        )
        reject_conflict = lifecycle_client.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_id,
                "rejected_actions": ["external_api_send"],
                "reason": "reject should conflict once completed",
            },
            headers={"Authorization": "Bearer owner-token"},
        )
        resume_conflict = lifecycle_client.post(
            "/orchestrator/resume/approval",
            json={
                "project_id": project_id,
                "approved_actions": ["external_api_send"],
                "trend_provider": "gemini",
            },
            headers={"Authorization": "Bearer owner-token"},
        )
        assert invalid_missing.status_code == 401
        assert invalid_conflict.status_code == 401
        assert missing.status_code == 404
        assert resumed.status_code == 200
        assert started.status_code == 200
        assert reject_conflict.status_code == 409
        assert resume_conflict.status_code == 409
        assert resumed.json()["summary"]["status"] == ProjectStatus.READY_FOR_PLANNING.value
        assert started.json()["summary"]["status"] == ProjectStatus.COMPLETED.value
        assert "current: completed" in reject_conflict.json()["detail"]
        assert resume_conflict.json()["detail"] == "Action(s) already rejected: external_api_send"

        direct_reject_status, direct_reject_detail = _direct_reject_outcome(
            lifecycle_client,
            project_id=project_id,
            token="owner-token",
            rejected_actions=["external_api_send"],
            reason="direct reject conflict parity under bootstrap-only gap",
        )
        direct_resume_status, direct_resume_detail = _direct_resume_outcome(
            lifecycle_client,
            project_id=project_id,
            token="owner-token",
            approved_actions=["external_api_send"],
        )
        assert direct_reject_status == 409
        assert direct_reject_detail == reject_conflict.json()["detail"]
        assert direct_resume_status == 409
        assert direct_resume_detail == resume_conflict.json()["detail"]

        audit = lifecycle_client.get(f"/projects/{project_id}/audit").json()
        rejected_events = [
            event for event in audit["events"] if event["event_type"] == "approval_rejected"
        ]
        resume_replanning_events = [
            event
            for event in audit["events"]
            if event["event_type"] == "resume_triggered"
            and event["metadata"].get("mode") == RevisionResumeMode.REPLANNING.value
        ]
        replanning_started_events = [
            event for event in audit["events"] if event["event_type"] == "replanning_started"
        ]
        assert len(rejected_events) == 1
        assert len(resume_replanning_events) == 1
        assert len(replanning_started_events) == 1
        assert rejected_events[0]["metadata"].get("note") == "reject note should remain immutable"
        assert lifecycle_client.app.state.orchestrator.repository is shared_repository
        assert (
            lifecycle_client.app.state.auth_service is lifecycle_client.app._bootstrap_auth_service
        )
        assert (
            lifecycle_client.app.state.orchestrator
            is lifecycle_client.app._bootstrap_orchestrator
        )
    finally:
        _clear_auth_caches()


def test_malformed_to_corrected_env_flip_combined_conflict_paths_keep_app_bootstrap_parity(
    monkeypatch,
) -> None:
    shared_repository = InMemoryProjectRepository()
    corrected_seed = (
        "owner-token:owner-1:owner:human,"
        "operator-token:operator-1:operator:human,"
        "approver-token:approver-1:approver:human"
    )
    try:
        _clear_auth_caches()
        malformed_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "malformed-seed-without-colons",
            dev_auth_enabled="definitely-not-bool",
        )
        project_id = _run_waiting_approval_project(malformed_client)

        corrected_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            corrected_seed,
            dev_auth_enabled="true",
        )
        _drop_app_runtime_bindings(
            corrected_client,
            drop_app_auth_snapshot=True,
            drop_app_orchestrator_snapshot=True,
            drop_state_bootstrap_snapshots=True,
        )

        wrong_reject = corrected_client.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_id,
                "rejected_actions": ["external_api_send"],
                "reason": "legacy malformed token should fail after corrected env",
            },
            headers={"Authorization": "Bearer dev-approver-token"},
        )
        right_reject = corrected_client.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_id,
                "rejected_actions": ["external_api_send"],
                "reason": "corrected token reject should succeed",
                "note": "first corrected conflict path note",
            },
            headers={"Authorization": "Bearer approver-token"},
        )
        resumed = corrected_client.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "replanning",
                "reason": "operator moves corrected flow to replanning",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer operator-token"},
        )
        started = corrected_client.post(
            "/orchestrator/replanning/start",
            json={
                "project_id": project_id,
                "note": "corrected flow start note",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer operator-token"},
        )
        reject_conflict = corrected_client.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_id,
                "rejected_actions": ["external_api_send"],
                "reason": "completed reject conflict under corrected app-bootstrap fallback",
            },
            headers={"Authorization": "Bearer approver-token"},
        )
        missing_invalid = corrected_client.post(
            "/orchestrator/replanning/start",
            json={
                "project_id": "missing-project",
                "note": "missing invalid should stay unauthorized first",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer invalid-token"},
        )
        missing_valid = corrected_client.post(
            "/orchestrator/replanning/start",
            json={
                "project_id": "missing-project",
                "note": "missing valid should surface not found",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer operator-token"},
        )
        assert wrong_reject.status_code == 401
        assert right_reject.status_code == 200
        assert resumed.status_code == 200
        assert started.status_code == 200
        assert reject_conflict.status_code == 409
        assert missing_invalid.status_code == 401
        assert missing_valid.status_code == 404

        direct_resume_status, direct_resume_detail = _direct_revision_resume_outcome(
            corrected_client,
            project_id=project_id,
            token="operator-token",
            resume_mode=RevisionResumeMode.REPLANNING,
            reason="direct conflict-path parity under corrected app-bootstrap fallback",
        )
        direct_reject_status, direct_reject_detail = _direct_reject_outcome(
            corrected_client,
            project_id=project_id,
            token="approver-token",
            rejected_actions=["external_api_send"],
            reason="direct reject conflict after corrected flow completion",
        )
        assert direct_resume_status == 200
        assert direct_resume_detail == ProjectStatus.COMPLETED.value
        assert direct_reject_status == 409
        assert direct_reject_detail == reject_conflict.json()["detail"]

        audit = corrected_client.get(f"/projects/{project_id}/audit").json()
        rejected_events = [
            event for event in audit["events"] if event["event_type"] == "approval_rejected"
        ]
        replanning_resume_events = [
            event
            for event in audit["events"]
            if event["event_type"] == "resume_triggered"
            and event["metadata"].get("mode") == RevisionResumeMode.REPLANNING.value
        ]
        replanning_start_events = [
            event for event in audit["events"] if event["event_type"] == "replanning_started"
        ]
        assert len(rejected_events) == 1
        assert len(replanning_resume_events) == 1
        assert len(replanning_start_events) == 1
        assert rejected_events[0]["metadata"].get("note") == "first corrected conflict path note"
        assert corrected_client.app.state.orchestrator.repository is shared_repository
        assert (
            corrected_client.app.state.auth_service is corrected_client.app._bootstrap_auth_service
        )
        assert (
            corrected_client.app.state.orchestrator
            is corrected_client.app._bootstrap_orchestrator
        )
    finally:
        _clear_auth_caches()


def test_malformed_to_corrected_env_flip_app_bootstrap_only_keeps_cross_endpoint_precedence_stable(
    monkeypatch,
) -> None:
    shared_repository = InMemoryProjectRepository()
    corrected_seed = (
        "approver-token:approver-1:approver:human,"
        "operator-token:operator-1:operator:human"
    )
    try:
        _clear_auth_caches()
        malformed_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            "malformed-seed-without-colons",
            dev_auth_enabled="definitely-not-bool",
        )
        project_id = _run_waiting_approval_project(malformed_client)

        corrected_client = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            corrected_seed,
            dev_auth_enabled="true",
        )
        _drop_app_runtime_bindings(
            corrected_client,
            drop_app_auth_snapshot=True,
            drop_app_orchestrator_snapshot=True,
            drop_state_bootstrap_snapshots=True,
        )

        invalid_missing_revision = corrected_client.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": "missing-project",
                "resume_mode": "replanning",
                "reason": "invalid missing revision should remain unauthorized",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer invalid-token"},
        )
        invalid_conflict_revision = corrected_client.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "replanning",
                "reason": "invalid conflict revision should remain unauthorized",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer invalid-token"},
        )
        missing_revision = corrected_client.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": "missing-project",
                "resume_mode": "replanning",
                "reason": "valid missing revision should be not found",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer operator-token"},
        )
        conflict_revision = corrected_client.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "replanning",
                "reason": "valid conflict revision should be invalid state",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer operator-token"},
        )
        assert invalid_missing_revision.status_code == 401
        assert invalid_conflict_revision.status_code == 401
        assert missing_revision.status_code == 404
        assert conflict_revision.status_code == 409
        assert "current: waiting_approval" in conflict_revision.json()["detail"]

        rejected = corrected_client.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_id,
                "rejected_actions": ["external_api_send"],
                "reason": "corrected seed reject moves to revision requested",
                "note": "first cross-endpoint conflict note",
            },
            headers={"Authorization": "Bearer approver-token"},
        )
        invalid_replanning = corrected_client.post(
            "/orchestrator/replanning/start",
            json={
                "project_id": project_id,
                "note": "invalid replanning should remain unauthorized",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer invalid-token"},
        )
        conflict_replanning = corrected_client.post(
            "/orchestrator/replanning/start",
            json={
                "project_id": project_id,
                "note": "replanning start should conflict before ready_for_planning",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer operator-token"},
        )
        resumed = corrected_client.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "replanning",
                "reason": "resume revision into ready_for_planning",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer operator-token"},
        )
        started = corrected_client.post(
            "/orchestrator/replanning/start",
            json={
                "project_id": project_id,
                "note": "start replanning after revision resume",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer operator-token"},
        )
        assert rejected.status_code == 200
        assert invalid_replanning.status_code == 401
        assert conflict_replanning.status_code == 409
        assert resumed.status_code == 200
        assert started.status_code == 200
        assert resumed.json()["summary"]["status"] == ProjectStatus.READY_FOR_PLANNING.value
        assert started.json()["summary"]["status"] == ProjectStatus.COMPLETED.value

        reject_conflict = corrected_client.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_id,
                "rejected_actions": ["external_api_send"],
                "reason": "reject conflicts after completion",
            },
            headers={"Authorization": "Bearer approver-token"},
        )
        resume_conflict = corrected_client.post(
            "/orchestrator/resume/approval",
            json={
                "project_id": project_id,
                "approved_actions": ["external_api_send"],
                "trend_provider": "gemini",
            },
            headers={"Authorization": "Bearer approver-token"},
        )
        assert reject_conflict.status_code == 409
        assert resume_conflict.status_code == 409
        assert "current: completed" in reject_conflict.json()["detail"]
        assert resume_conflict.json()["detail"] == "Action(s) already rejected: external_api_send"

        direct_revision_status, direct_revision_detail = _direct_revision_resume_outcome(
            corrected_client,
            project_id=project_id,
            token="operator-token",
            resume_mode=RevisionResumeMode.REPLANNING,
            reason="direct revision parity after completion",
        )
        direct_replanning_status, direct_replanning_detail = _direct_replanning_start_outcome(
            corrected_client,
            project_id=project_id,
            token="operator-token",
            note="direct replanning parity after completion",
        )
        direct_reject_status, direct_reject_detail = _direct_reject_outcome(
            corrected_client,
            project_id=project_id,
            token="approver-token",
            rejected_actions=["external_api_send"],
            reason="direct reject conflict parity after completion",
        )
        assert direct_revision_status == 200
        assert direct_revision_detail == ProjectStatus.COMPLETED.value
        assert direct_replanning_status == 200
        assert direct_replanning_detail == ProjectStatus.COMPLETED.value
        assert direct_reject_status == 409
        assert direct_reject_detail == reject_conflict.json()["detail"]

        audit = corrected_client.get(f"/projects/{project_id}/audit").json()
        rejected_events = [
            event for event in audit["events"] if event["event_type"] == "approval_rejected"
        ]
        revision_resume_events = [
            event
            for event in audit["events"]
            if event["event_type"] == "resume_triggered"
            and event["metadata"].get("mode") == RevisionResumeMode.REPLANNING.value
        ]
        replanning_started_events = [
            event for event in audit["events"] if event["event_type"] == "replanning_started"
        ]
        assert len(rejected_events) == 1
        assert len(revision_resume_events) == 1
        assert len(replanning_started_events) == 1
        assert rejected_events[0]["metadata"].get("note") == "first cross-endpoint conflict note"
        assert corrected_client.app.state.orchestrator.repository is shared_repository
        assert (
            corrected_client.app.state.auth_service is corrected_client.app._bootstrap_auth_service
        )
        assert (
            corrected_client.app.state.orchestrator
            is corrected_client.app._bootstrap_orchestrator
        )
    finally:
        _clear_auth_caches()


def test_shared_repo_completed_approval_retry_for_rejected_action_keeps_conflict_detail_parity(
    monkeypatch,
) -> None:
    shared_repository = InMemoryProjectRepository()
    token_seed = (
        "approver-token:approver-1:approver:human,"
        "operator-token:operator-1:operator:human"
    )
    try:
        _clear_auth_caches()
        client_one = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            token_seed,
        )
        project_id = _run_waiting_approval_project(client_one)

        rejected = client_one.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_id,
                "rejected_actions": ["external_api_send"],
                "reason": "move to revision before completion parity check",
            },
            headers={"Authorization": "Bearer approver-token"},
        )
        resumed = client_one.post(
            "/orchestrator/resume/revision",
            json={
                "project_id": project_id,
                "resume_mode": "rebuilding",
                "reason": "finish flow after rejection",
                "trend_provider": "mock",
            },
            headers={"Authorization": "Bearer operator-token"},
        )
        assert rejected.status_code == 200
        assert resumed.status_code == 200
        assert resumed.json()["summary"]["status"] == ProjectStatus.COMPLETED.value

        client_two = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            token_seed,
        )
        unauthorized = client_two.post(
            "/orchestrator/resume/approval",
            json={
                "project_id": project_id,
                "approved_actions": ["external_api_send"],
                "trend_provider": "gemini",
            },
            headers={"Authorization": "Bearer invalid-token"},
        )
        conflict = client_two.post(
            "/orchestrator/resume/approval",
            json={
                "project_id": project_id,
                "approved_actions": ["external_api_send"],
                "trend_provider": "gemini",
            },
            headers={"Authorization": "Bearer approver-token"},
        )
        assert unauthorized.status_code == 401
        assert conflict.status_code == 409
        assert conflict.json()["detail"] == "Action(s) already rejected: external_api_send"

        direct_status, direct_detail = _direct_resume_outcome(
            client_two,
            project_id=project_id,
            token="approver-token",
            approved_actions=["external_api_send"],
        )
        assert direct_status == 409
        assert direct_detail == conflict.json()["detail"]

        audit = client_two.get(f"/projects/{project_id}/audit").json()
        rejected_events = [
            event for event in audit["events"] if event["event_type"] == "approval_rejected"
        ]
        approved_events = [
            event for event in audit["events"] if event["event_type"] == "approval_approved"
        ]
        assert len(rejected_events) == 1
        assert len(approved_events) == 0
    finally:
        _clear_auth_caches()


def test_shared_repo_revision_reject_retry_non_rejected_action_keeps_conflict_detail_parity(
    monkeypatch,
) -> None:
    shared_repository = InMemoryProjectRepository()
    token_seed = "approver-token:approver-1:approver:human"
    try:
        _clear_auth_caches()
        client_one = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            token_seed,
        )
        project_id = _run_waiting_approval_project(client_one)
        record = shared_repository.get(project_id)
        assert record is not None
        record.approvals.append(
            ApprovalRequest(
                id="approval-bulk-modify-reject-parity",
                action_type=ApprovalActionType.BULK_MODIFY,
                status=ApprovalStatus.PENDING,
                reason="Bulk modify requires explicit approval.",
                requested_by="system",
            )
        )
        shared_repository.save(record)

        partial = client_one.post(
            "/orchestrator/resume/approval",
            json={
                "project_id": project_id,
                "approved_actions": ["external_api_send"],
                "trend_provider": "gemini",
            },
            headers={"Authorization": "Bearer approver-token"},
        )
        first_reject = client_one.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_id,
                "rejected_actions": ["bulk_modify"],
                "reason": "reject remaining pending action",
            },
            headers={"Authorization": "Bearer approver-token"},
        )
        assert partial.status_code == 200
        assert partial.json()["summary"]["status"] == ProjectStatus.WAITING_APPROVAL.value
        assert first_reject.status_code == 200
        assert first_reject.json()["summary"]["status"] == ProjectStatus.REVISION_REQUESTED.value

        client_two = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            token_seed,
        )
        unauthorized = client_two.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_id,
                "rejected_actions": ["external_api_send"],
                "reason": "unauthorized reject should keep precedence",
            },
            headers={"Authorization": "Bearer invalid-token"},
        )
        conflict = client_two.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_id,
                "rejected_actions": ["external_api_send"],
                "reason": "already approved action should not map to idempotent reject",
            },
            headers={"Authorization": "Bearer approver-token"},
        )
        assert unauthorized.status_code == 401
        assert conflict.status_code == 409
        assert (
            conflict.json()["detail"]
            == "Cannot reject non-pending action(s): external_api_send"
        )

        direct_status, direct_detail = _direct_reject_outcome(
            client_two,
            project_id=project_id,
            token="approver-token",
            rejected_actions=["external_api_send"],
            reason="direct conflict parity for non-rejected action retry",
        )
        assert direct_status == 409
        assert direct_detail == conflict.json()["detail"]

        audit = client_two.get(f"/projects/{project_id}/audit").json()
        rejected_events = [
            event for event in audit["events"] if event["event_type"] == "approval_rejected"
        ]
        assert len(rejected_events) == 1
    finally:
        _clear_auth_caches()


def test_shared_repo_revision_non_pending_reject_keeps_401_over_409_and_cross_role_parity(
    monkeypatch,
) -> None:
    shared_repository = InMemoryProjectRepository()
    token_seed = (
        "approver-token:approver-1:approver:human,"
        "viewer-token:viewer-1:viewer:human"
    )
    try:
        _clear_auth_caches()
        client_one = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            token_seed,
        )
        project_id = _run_waiting_approval_project(client_one)
        record = shared_repository.get(project_id)
        assert record is not None
        record.approvals.append(
            ApprovalRequest(
                id="approval-bulk-modify-non-pending-precedence",
                action_type=ApprovalActionType.BULK_MODIFY,
                status=ApprovalStatus.PENDING,
                reason="Bulk modify requires explicit approval.",
                requested_by="system",
            )
        )
        shared_repository.save(record)

        partial = client_one.post(
            "/orchestrator/resume/approval",
            json={
                "project_id": project_id,
                "approved_actions": ["external_api_send"],
                "trend_provider": "gemini",
            },
            headers={"Authorization": "Bearer approver-token"},
        )
        rejected = client_one.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_id,
                "rejected_actions": ["bulk_modify"],
                "reason": "reject remaining pending action",
            },
            headers={"Authorization": "Bearer approver-token"},
        )
        assert partial.status_code == 200
        assert partial.json()["summary"]["status"] == ProjectStatus.WAITING_APPROVAL.value
        assert rejected.status_code == 200
        assert rejected.json()["summary"]["status"] == ProjectStatus.REVISION_REQUESTED.value

        client_two = _client_with_shared_repository_and_seed(
            monkeypatch,
            shared_repository,
            token_seed,
        )
        invalid = client_two.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_id,
                "rejected_actions": ["external_api_send"],
                "reason": "invalid token should keep 401 precedence",
            },
            headers={"Authorization": "Bearer invalid-token"},
        )
        approver_conflict = client_two.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_id,
                "rejected_actions": ["external_api_send"],
                "reason": "approver should hit non-pending conflict",
            },
            headers={"Authorization": "Bearer approver-token"},
        )
        viewer_conflict = client_two.post(
            "/orchestrator/approval/reject",
            json={
                "project_id": project_id,
                "rejected_actions": ["external_api_send"],
                "reason": "viewer should hit same non-pending conflict detail",
            },
            headers={"Authorization": "Bearer viewer-token"},
        )
        assert invalid.status_code == 401
        assert approver_conflict.status_code == 409
        assert viewer_conflict.status_code == 409
        assert (
            approver_conflict.json()["detail"]
            == "Cannot reject non-pending action(s): external_api_send"
        )
        assert approver_conflict.json()["detail"] == viewer_conflict.json()["detail"]

        approver_direct_status, approver_direct_detail = _direct_reject_outcome(
            client_two,
            project_id=project_id,
            token="approver-token",
            rejected_actions=["external_api_send"],
            reason="direct approver conflict parity for non-pending reject",
        )
        viewer_direct_status, viewer_direct_detail = _direct_reject_outcome(
            client_two,
            project_id=project_id,
            token="viewer-token",
            rejected_actions=["external_api_send"],
            reason="direct viewer conflict parity for non-pending reject",
        )
        assert approver_direct_status == 409
        assert viewer_direct_status == 409
        assert approver_direct_detail == approver_conflict.json()["detail"]
        assert viewer_direct_detail == viewer_conflict.json()["detail"]

        audit = client_two.get(f"/projects/{project_id}/audit").json()
        rejected_events = [
            event for event in audit["events"] if event["event_type"] == "approval_rejected"
        ]
        assert len(rejected_events) == 1
    finally:
        _clear_auth_caches()
