import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api import routes
from app.api.dependencies import get_auth_service_dependency
from app.api.main import create_app
from app.schemas.project import ActorContext, ActorRole, ActorType
from app.services.auth import AuthenticationError


class _StaticAuthService:
    def resolve_actor(self, authorization: str | None) -> ActorContext:
        if not authorization:
            raise AssertionError("authorization header is required in this test")
        return ActorContext(
            actor_id="approver-1",
            actor_role=ActorRole.APPROVER,
            actor_type=ActorType.HUMAN,
        )


class _RaisingOrchestrator:
    def __init__(self, method_name: str, exc: Exception) -> None:
        self.method_name = method_name
        self.exc = exc

    def record_authentication_success(self, project_id: str, actor) -> None:  # noqa: ANN001
        return None

    def record_authentication_failure(self, project_id: str, reason: str) -> None:
        return None

    def resume_from_approval(self, *args, **kwargs):  # noqa: ANN002, ANN003
        if self.method_name == "resume_from_approval":
            raise self.exc
        raise AssertionError("unexpected method call")

    def reject_approval(self, *args, **kwargs):  # noqa: ANN002, ANN003
        if self.method_name == "reject_approval":
            raise self.exc
        raise AssertionError("unexpected method call")

    def resume_from_revision(self, *args, **kwargs):  # noqa: ANN002, ANN003
        if self.method_name == "resume_from_revision":
            raise self.exc
        raise AssertionError("unexpected method call")

    def start_replanning(self, *args, **kwargs):  # noqa: ANN002, ANN003
        if self.method_name == "start_replanning":
            raise self.exc
        raise AssertionError("unexpected method call")

    def get_project_audit(self, project_id: str):
        if self.method_name == "get_project_audit":
            raise self.exc
        raise AssertionError("unexpected method call")

    def run(self, *args, **kwargs):  # noqa: ANN002, ANN003
        if self.method_name == "run":
            raise self.exc
        raise AssertionError("unexpected method call")


class _RecordingAuthFailureOrchestrator:
    def __init__(self) -> None:
        self.failure_reasons: list[str] = []
        self.called_method: str | None = None

    def record_authentication_success(self, project_id: str, actor) -> None:  # noqa: ANN001
        return None

    def record_authentication_failure(self, project_id: str, reason: str) -> None:
        self.failure_reasons.append(reason)

    def resume_from_approval(self, *args, **kwargs):  # noqa: ANN002, ANN003
        self.called_method = "resume_from_approval"
        raise AssertionError("protected action must not be called on auth failure")

    def reject_approval(self, *args, **kwargs):  # noqa: ANN002, ANN003
        self.called_method = "reject_approval"
        raise AssertionError("protected action must not be called on auth failure")

    def resume_from_revision(self, *args, **kwargs):  # noqa: ANN002, ANN003
        self.called_method = "resume_from_revision"
        raise AssertionError("protected action must not be called on auth failure")

    def start_replanning(self, *args, **kwargs):  # noqa: ANN002, ANN003
        self.called_method = "start_replanning"
        raise AssertionError("protected action must not be called on auth failure")


@pytest.mark.parametrize(
    ("method_name", "path", "payload", "requires_auth"),
    [
        (
            "run",
            "/orchestrator/run",
            {
                "brief": {
                    "title": "t",
                    "objective": "o",
                    "scope": "s",
                    "constraints": ["c"],
                    "success_criteria": ["x"],
                    "deadline": "2026-01-01",
                    "stakeholders": ["st"],
                    "assumptions": ["a"],
                    "raw_request": "r",
                },
                "trend_provider": "mock",
            },
            False,
        ),
        (
            "resume_from_approval",
            "/orchestrator/resume/approval",
            {"project_id": "proj", "approved_actions": ["external_api_send"]},
            True,
        ),
        (
            "reject_approval",
            "/orchestrator/approval/reject",
            {
                "project_id": "proj",
                "rejected_actions": ["external_api_send"],
                "reason": "manual reject",
            },
            True,
        ),
        (
            "resume_from_revision",
            "/orchestrator/resume/revision",
            {"project_id": "proj", "resume_mode": "replanning", "reason": "retry"},
            True,
        ),
        (
            "start_replanning",
            "/orchestrator/replanning/start",
            {"project_id": "proj", "note": "start"},
            True,
        ),
        ("get_project_audit", "/projects/proj/audit", None, False),
    ],
)
@pytest.mark.parametrize(
    ("exc", "expected_status"),
    [
        (LookupError("not found"), 404),
        (PermissionError("forbidden"), 403),
        (ValueError("conflict"), 409),
    ],
)
def test_route_error_mapping_integration(
    method_name: str,
    path: str,
    payload: dict | None,
    requires_auth: bool,
    exc: Exception,
    expected_status: int,
) -> None:
    app = create_app()
    app.state.orchestrator = _RaisingOrchestrator(method_name, exc)
    app.dependency_overrides[get_auth_service_dependency] = lambda: _StaticAuthService()
    client = TestClient(app)
    headers = {"Authorization": "Bearer dev-approver-token"} if requires_auth else None

    if payload is None:
        response = client.get(path, headers=headers)
    else:
        response = client.post(path, json=payload, headers=headers)

    assert response.status_code == expected_status
    assert response.json()["detail"] == str(exc)


def test_raise_route_http_error_passes_http_exception_through() -> None:
    exc = HTTPException(status_code=418, detail="teapot")

    with pytest.raises(HTTPException) as captured:
        routes._raise_route_http_error(exc)

    assert captured.value.status_code == 418
    assert captured.value.detail == "teapot"


def test_raise_route_http_error_reraises_unknown_exception() -> None:
    class _UnknownError(Exception):
        pass

    with pytest.raises(_UnknownError):
        routes._raise_route_http_error(_UnknownError("boom"))


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (
            "/orchestrator/resume/approval",
            {"project_id": "proj", "approved_actions": ["external_api_send"]},
        ),
        (
            "/orchestrator/approval/reject",
            {
                "project_id": "proj",
                "rejected_actions": ["external_api_send"],
                "reason": "manual reject",
            },
        ),
        (
            "/orchestrator/resume/revision",
            {"project_id": "proj", "resume_mode": "replanning", "reason": "retry"},
        ),
        (
            "/orchestrator/replanning/start",
            {"project_id": "proj", "note": "start"},
        ),
    ],
)
def test_protected_route_returns_401_on_authentication_failure_before_action(
    path: str,
    payload: dict,
) -> None:
    class _RejectingAuthService:
        def resolve_actor(self, authorization: str | None) -> ActorContext:
            raise AuthenticationError("Invalid bearer token.")

    orchestrator = _RecordingAuthFailureOrchestrator()
    app = create_app()
    app.state.orchestrator = orchestrator
    app.dependency_overrides[get_auth_service_dependency] = lambda: _RejectingAuthService()
    client = TestClient(app)

    response = client.post(path, json=payload, headers={"Authorization": "Bearer invalid-token"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid bearer token."
    assert orchestrator.failure_reasons == ["Invalid bearer token."]
    assert orchestrator.called_method is None
