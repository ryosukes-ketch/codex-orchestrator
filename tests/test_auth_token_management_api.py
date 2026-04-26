import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import clear_auth_service_dependency_caches
from app.api.main import create_app


@pytest.fixture(autouse=True)
def _reset_auth_runtime() -> None:
    clear_auth_service_dependency_caches()
    yield
    clear_auth_service_dependency_caches()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _intake_brief(client: TestClient) -> dict:
    response = client.post(
        "/intake/brief",
        json={
            "user_request": (
                "Title: Auth management test\n"
                "Scope: validate commercial token lifecycle\n"
                "Constraints: python, fastapi\n"
                "Success Criteria: deterministic protected route auth\n"
                "Deadline: 2026-08-01"
            )
        },
    )
    assert response.status_code == 200
    return response.json()["brief"]


def _run_waiting_project(client: TestClient) -> str:
    response = client.post(
        "/orchestrator/run",
        json={"brief": _intake_brief(client), "trend_provider": "gemini"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["status"] == "waiting_approval"
    return payload["record"]["project"]["id"]


def _configure_commercial_auth(
    monkeypatch: pytest.MonkeyPatch,
    *,
    token_store_path: str,
    token_seed: str = (
        "commercial-admin:admin-1:admin:human,"
        "commercial-operator:ops-1:operator:human,"
        "commercial-approver:apr-1:approver:human"
    ),
) -> None:
    monkeypatch.setenv("AUTH_SERVICE_MODE", "commercial_token")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_TOKEN_SEED", token_seed)
    monkeypatch.setenv("AUTH_TOKEN_STORE_PATH", token_store_path)
    monkeypatch.setenv("DEV_AUTH_ENABLED", "false")


def test_auth_token_management_routes_require_commercial_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_SERVICE_MODE", "dev_token")
    monkeypatch.setenv("DEV_AUTH_ENABLED", "true")
    monkeypatch.setenv("DEV_AUTH_TOKEN_SEED", "dev-admin-token:admin-1:admin:human")

    client = TestClient(create_app())
    response = client.get("/auth/tokens", headers=_auth("dev-admin-token"))

    assert response.status_code == 409
    assert "AUTH_SERVICE_MODE=commercial_token" in response.json()["detail"]


def test_auth_token_list_requires_admin_role(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _configure_commercial_auth(
        monkeypatch,
        token_store_path=str(tmp_path / "commercial-token-store.json"),
    )
    client = TestClient(create_app())

    missing = client.get("/auth/tokens")
    not_admin = client.get("/auth/tokens", headers=_auth("commercial-operator"))
    admin = client.get("/auth/tokens", headers=_auth("commercial-admin"))

    assert missing.status_code == 401
    assert not_admin.status_code == 403
    assert admin.status_code == 200
    payload = admin.json()
    assert payload["auth_service_mode"] == "commercial_token"
    assert payload["managed_by_actor_id"] == "admin-1"
    assert payload["token_count"] >= 3
    assert payload["token_store_path"].endswith("commercial-token-store.json")


def test_auth_token_issue_and_revoke_affect_protected_approval_flow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _configure_commercial_auth(
        monkeypatch,
        token_store_path=str(tmp_path / "commercial-token-store.json"),
        token_seed="commercial-admin:admin-1:admin:human",
    )
    client = TestClient(create_app())

    issue = client.post(
        "/auth/tokens/issue",
        headers=_auth("commercial-admin"),
        json={
            "actor_id": "apr-2",
            "actor_role": "approver",
            "actor_type": "human",
            "token": "issued-approver-token",
            "description": "temporary approver",
        },
    )
    assert issue.status_code == 200

    project_id = _run_waiting_project(client)
    approved = client.post(
        "/orchestrator/resume/approval",
        headers=_auth("issued-approver-token"),
        json={
            "project_id": project_id,
            "approved_actions": ["external_api_send"],
            "trend_provider": "gemini",
        },
    )
    assert approved.status_code == 200
    assert approved.json()["summary"]["status"] == "completed"

    audit = client.get(f"/projects/{project_id}/audit")
    assert audit.status_code == 200
    assert any(
        event["event_type"] == "actor_resolved" and event["actor"] == "apr-2"
        for event in audit.json()["events"]
    )

    revoke = client.post(
        "/auth/tokens/revoke",
        headers=_auth("commercial-admin"),
        json={"token": "issued-approver-token"},
    )
    assert revoke.status_code == 200

    waiting_project = _run_waiting_project(client)
    rejected = client.post(
        "/orchestrator/resume/approval",
        headers=_auth("issued-approver-token"),
        json={
            "project_id": waiting_project,
            "approved_actions": ["external_api_send"],
            "trend_provider": "gemini",
        },
    )
    assert rejected.status_code == 401


def test_auth_token_rotate_invalidates_old_token_and_accepts_new_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _configure_commercial_auth(
        monkeypatch,
        token_store_path=str(tmp_path / "commercial-token-store.json"),
        token_seed="commercial-admin:admin-1:admin:human",
    )
    client = TestClient(create_app())

    issue = client.post(
        "/auth/tokens/issue",
        headers=_auth("commercial-admin"),
        json={
            "actor_id": "apr-rotate",
            "actor_role": "approver",
            "actor_type": "human",
            "token": "rotate-approver-token-v1",
        },
    )
    assert issue.status_code == 200

    rotate = client.post(
        "/auth/tokens/rotate",
        headers=_auth("commercial-admin"),
        json={
            "token": "rotate-approver-token-v1",
            "new_token": "rotate-approver-token-v2",
        },
    )
    assert rotate.status_code == 200
    rotate_payload = rotate.json()
    assert rotate_payload["old_token_preview"].startswith("rota")
    assert rotate_payload["token"] == "rotate-approver-token-v2"

    project_id = _run_waiting_project(client)
    old_token_response = client.post(
        "/orchestrator/resume/approval",
        headers=_auth("rotate-approver-token-v1"),
        json={
            "project_id": project_id,
            "approved_actions": ["external_api_send"],
            "trend_provider": "gemini",
        },
    )
    assert old_token_response.status_code == 401

    new_token_response = client.post(
        "/orchestrator/resume/approval",
        headers=_auth("rotate-approver-token-v2"),
        json={
            "project_id": project_id,
            "approved_actions": ["external_api_send"],
            "trend_provider": "gemini",
        },
    )
    assert new_token_response.status_code == 200
    assert new_token_response.json()["summary"]["status"] == "completed"
