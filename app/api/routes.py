from collections.abc import Callable
from typing import TypeVar

from fastapi import APIRouter, Depends, HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.dependencies import get_auth_service_dependency
from app.api.runtime_bindings import resolve_orchestrator_binding
from app.intake.service import IntakeAgent
from app.orchestrator.service import PMOrchestrator
from app.schemas.api import (
    ApprovalRejectRequest,
    ApprovalResumeRequest,
    AuthTokenIssueRequest,
    AuthTokenIssueResponse,
    AuthTokenListResponse,
    AuthTokenRevokeRequest,
    AuthTokenRevokeResponse,
    AuthTokenRotateRequest,
    AuthTokenRotateResponse,
    IntakeBriefRequest,
    OrchestratorRunRequest,
    ReplanningStartRequest,
    RevisionResumeRequest,
)
from app.schemas.brief import IntakeResult
from app.schemas.project import ActorContext, ActorRole, OrchestrationResult, ProjectAudit
from app.services.auth import AuthenticationError, AuthService, CommercialTokenAuthService

router = APIRouter()
intake_agent = IntakeAgent()
orchestrator = PMOrchestrator()
_T = TypeVar("_T")
bearer_auth = HTTPBearer(auto_error=False)


def reset_orchestrator_runtime() -> PMOrchestrator:
    global orchestrator
    orchestrator = PMOrchestrator()
    return orchestrator


def _get_orchestrator(request: Request | None = None) -> PMOrchestrator:
    return resolve_orchestrator_binding(request, fallback_resolver=lambda: orchestrator)


def _resolve_authenticated_actor(
    auth_service: AuthService,
    authorization: str | None,
    project_id: str,
    orchestrator_instance: PMOrchestrator | None = None,
) -> ActorContext:
    runtime_orchestrator = orchestrator_instance or orchestrator
    auth_source, auth_mode = _derive_auth_context(authorization)
    try:
        actor = auth_service.resolve_actor(authorization)
        runtime_orchestrator.record_authentication_success(
            project_id=project_id,
            actor=actor,
            auth_source=auth_source,
            auth_mode=auth_mode,
        )
        return actor
    except AuthenticationError as exc:
        runtime_orchestrator.record_authentication_failure(
            project_id=project_id,
            reason=str(exc),
            auth_source=auth_source,
            auth_mode=auth_mode,
        )
        _raise_route_http_error(exc)


def _authorization_header_from_credentials(
    credentials: HTTPAuthorizationCredentials | None,
) -> str | None:
    if credentials is None:
        return None
    return f"{credentials.scheme} {credentials.credentials}"


def _derive_auth_context(authorization: str | None) -> tuple[str, str]:
    if authorization is None or authorization.strip() == "":
        return ("none", "none")
    parts = authorization.strip().split(None, 1)
    if not parts:
        return ("none", "none")
    scheme = parts[0].lower()
    if scheme == "bearer":
        return ("token", "bearer")
    return ("header", scheme)


def _map_exception_to_http_exception(exc: Exception) -> HTTPException | None:
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, AuthenticationError):
        return HTTPException(status_code=401, detail=str(exc))
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=409, detail=str(exc))
    return None


def _raise_route_http_error(exc: Exception) -> None:
    mapped_exc = _map_exception_to_http_exception(exc)
    if mapped_exc is not None:
        raise mapped_exc from exc
    raise exc


def _run_with_route_error_mapping(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except Exception as exc:
        _raise_route_http_error(exc)


def _run_with_authenticated_actor(
    *,
    project_id: str,
    authorization: str | None,
    auth_service: AuthService,
    action: Callable[[ActorContext], _T],
    orchestrator_instance: PMOrchestrator | None = None,
) -> _T:
    return _run_with_route_error_mapping(
        lambda: action(
            _resolve_authenticated_actor(
                auth_service=auth_service,
                authorization=authorization,
                project_id=project_id,
                orchestrator_instance=orchestrator_instance,
            )
        )
    )


def _run_protected_orchestrator_action(
    *,
    request: Request,
    project_id: str,
    authorization: str | None,
    auth_service: AuthService,
    action: Callable[[PMOrchestrator, ActorContext], OrchestrationResult],
) -> OrchestrationResult:
    runtime_orchestrator = _get_orchestrator(request)
    return _run_with_authenticated_actor(
        project_id=project_id,
        authorization=authorization,
        auth_service=auth_service,
        action=lambda actor: action(runtime_orchestrator, actor),
        orchestrator_instance=runtime_orchestrator,
    )


def _resolve_admin_actor_for_auth_management(
    *,
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
    auth_service: AuthService,
) -> tuple[CommercialTokenAuthService, ActorContext]:
    runtime_orchestrator = _get_orchestrator(request)
    actor = _resolve_authenticated_actor(
        auth_service=auth_service,
        authorization=_authorization_header_from_credentials(credentials),
        project_id="__auth_token_management__",
        orchestrator_instance=runtime_orchestrator,
    )
    if actor.actor_role != ActorRole.ADMIN:
        raise PermissionError("Admin role is required for auth token management.")
    if not isinstance(auth_service, CommercialTokenAuthService):
        raise ValueError(
            "Auth token management endpoints require AUTH_SERVICE_MODE=commercial_token."
        )
    return (auth_service, actor)


def _run_orchestrator_action(
    *,
    request: Request,
    action: Callable[[PMOrchestrator], _T],
) -> _T:
    runtime_orchestrator = _get_orchestrator(request)
    return _run_with_route_error_mapping(lambda: action(runtime_orchestrator))


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/intake/brief", response_model=IntakeResult)
def intake_brief(payload: IntakeBriefRequest) -> IntakeResult:
    return intake_agent.build_brief(payload.user_request)


@router.post("/orchestrator/run", response_model=OrchestrationResult)
def orchestrator_run(payload: OrchestratorRunRequest, request: Request) -> OrchestrationResult:
    return _run_orchestrator_action(
        request=request,
        action=lambda runtime_orchestrator: runtime_orchestrator.run(
            payload.brief,
            project_policy=payload.project_policy,
            trend_provider_name=payload.trend_provider,
            approved_actions=payload.approved_actions,
            simulate_review_failure=payload.simulate_review_failure,
        ),
    )


@router.get("/auth/tokens", response_model=AuthTokenListResponse)
def list_auth_tokens(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_auth),
    auth_service: AuthService = Depends(get_auth_service_dependency),
) -> AuthTokenListResponse:
    commercial_auth_service, actor = _run_with_route_error_mapping(
        lambda: _resolve_admin_actor_for_auth_management(
            request=request,
            credentials=credentials,
            auth_service=auth_service,
        )
    )
    token_descriptors = [
        {
            **descriptor,
            "actor_role": descriptor["actor_role"].lower(),
            "actor_type": descriptor["actor_type"].lower(),
        }
        for descriptor in commercial_auth_service.list_token_descriptors()
    ]
    return AuthTokenListResponse(
        auth_service_mode=commercial_auth_service.service_mode,
        token_store_path=commercial_auth_service.token_store_path,
        managed_by_actor_id=actor.actor_id,
        token_count=len(token_descriptors),
        tokens=token_descriptors,
    )


@router.post("/auth/tokens/issue", response_model=AuthTokenIssueResponse)
def issue_auth_token(
    payload: AuthTokenIssueRequest,
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_auth),
    auth_service: AuthService = Depends(get_auth_service_dependency),
) -> AuthTokenIssueResponse:
    commercial_auth_service, actor = _run_with_route_error_mapping(
        lambda: _resolve_admin_actor_for_auth_management(
            request=request,
            credentials=credentials,
            auth_service=auth_service,
        )
    )
    issued = _run_with_route_error_mapping(
        lambda: commercial_auth_service.issue_token(
            actor_id=payload.actor_id,
            actor_role=payload.actor_role,
            actor_type=payload.actor_type,
            token=payload.token,
            description=payload.description,
        )
    )
    return AuthTokenIssueResponse(
        auth_service_mode=commercial_auth_service.service_mode,
        token_store_path=commercial_auth_service.token_store_path,
        managed_by_actor_id=actor.actor_id,
        token=issued["token"],
        token_preview=issued["token_preview"],
        token_fingerprint=issued["token_fingerprint"],
        actor=issued["actor"],
        created_at=issued.get("created_at", ""),
        updated_at=issued.get("updated_at", ""),
        description=issued.get("description", ""),
    )


@router.post("/auth/tokens/revoke", response_model=AuthTokenRevokeResponse)
def revoke_auth_token(
    payload: AuthTokenRevokeRequest,
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_auth),
    auth_service: AuthService = Depends(get_auth_service_dependency),
) -> AuthTokenRevokeResponse:
    commercial_auth_service, actor = _run_with_route_error_mapping(
        lambda: _resolve_admin_actor_for_auth_management(
            request=request,
            credentials=credentials,
            auth_service=auth_service,
        )
    )
    revoked = _run_with_route_error_mapping(
        lambda: commercial_auth_service.revoke_token(token=payload.token)
    )
    return AuthTokenRevokeResponse(
        auth_service_mode=commercial_auth_service.service_mode,
        token_store_path=commercial_auth_service.token_store_path,
        managed_by_actor_id=actor.actor_id,
        token_preview=revoked["token_preview"],
        token_fingerprint=revoked["token_fingerprint"],
        actor=revoked["actor"],
        created_at=revoked.get("created_at", ""),
        updated_at=revoked.get("updated_at", ""),
        description=revoked.get("description", ""),
        revoked_at=revoked["revoked_at"],
    )


@router.post("/auth/tokens/rotate", response_model=AuthTokenRotateResponse)
def rotate_auth_token(
    payload: AuthTokenRotateRequest,
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_auth),
    auth_service: AuthService = Depends(get_auth_service_dependency),
) -> AuthTokenRotateResponse:
    commercial_auth_service, actor = _run_with_route_error_mapping(
        lambda: _resolve_admin_actor_for_auth_management(
            request=request,
            credentials=credentials,
            auth_service=auth_service,
        )
    )
    rotated = _run_with_route_error_mapping(
        lambda: commercial_auth_service.rotate_token(
            token=payload.token,
            new_token=payload.new_token,
        )
    )
    return AuthTokenRotateResponse(
        auth_service_mode=commercial_auth_service.service_mode,
        token_store_path=commercial_auth_service.token_store_path,
        managed_by_actor_id=actor.actor_id,
        old_token_preview=rotated["old_token_preview"],
        old_token_fingerprint=rotated["old_token_fingerprint"],
        token=rotated["token"],
        token_preview=rotated["token_preview"],
        token_fingerprint=rotated["token_fingerprint"],
        actor=rotated["actor"],
        created_at=rotated.get("created_at", ""),
        updated_at=rotated.get("updated_at", ""),
        description=rotated.get("description", ""),
    )


@router.post("/orchestrator/resume/approval", response_model=OrchestrationResult)
def resume_approval(
    payload: ApprovalResumeRequest,
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_auth),
    auth_service: AuthService = Depends(get_auth_service_dependency),
) -> OrchestrationResult:
    return _run_protected_orchestrator_action(
        request=request,
        project_id=payload.project_id,
        authorization=_authorization_header_from_credentials(credentials),
        auth_service=auth_service,
        action=lambda runtime_orchestrator, actor: runtime_orchestrator.resume_from_approval(
            project_id=payload.project_id,
            approved_actions=payload.approved_actions,
            actor=actor,
            note=payload.note,
            trend_provider_name=payload.trend_provider,
        ),
    )


@router.post("/orchestrator/approval/reject", response_model=OrchestrationResult)
def reject_approval(
    payload: ApprovalRejectRequest,
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_auth),
    auth_service: AuthService = Depends(get_auth_service_dependency),
) -> OrchestrationResult:
    return _run_protected_orchestrator_action(
        request=request,
        project_id=payload.project_id,
        authorization=_authorization_header_from_credentials(credentials),
        auth_service=auth_service,
        action=lambda runtime_orchestrator, actor: runtime_orchestrator.reject_approval(
            project_id=payload.project_id,
            rejected_actions=payload.rejected_actions,
            actor=actor,
            reason=payload.reason,
            note=payload.note,
        ),
    )


@router.post("/orchestrator/resume/revision", response_model=OrchestrationResult)
def resume_revision(
    payload: RevisionResumeRequest,
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_auth),
    auth_service: AuthService = Depends(get_auth_service_dependency),
) -> OrchestrationResult:
    return _run_protected_orchestrator_action(
        request=request,
        project_id=payload.project_id,
        authorization=_authorization_header_from_credentials(credentials),
        auth_service=auth_service,
        action=lambda runtime_orchestrator, actor: runtime_orchestrator.resume_from_revision(
            project_id=payload.project_id,
            resume_mode=payload.resume_mode,
            actor=actor,
            reason=payload.reason,
            trend_provider_name=payload.trend_provider,
            approved_actions=payload.approved_actions,
        ),
    )


@router.post("/orchestrator/replanning/start", response_model=OrchestrationResult)
def start_replanning(
    payload: ReplanningStartRequest,
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_auth),
    auth_service: AuthService = Depends(get_auth_service_dependency),
) -> OrchestrationResult:
    return _run_protected_orchestrator_action(
        request=request,
        project_id=payload.project_id,
        authorization=_authorization_header_from_credentials(credentials),
        auth_service=auth_service,
        action=lambda runtime_orchestrator, actor: runtime_orchestrator.start_replanning(
            project_id=payload.project_id,
            actor=actor,
            note=payload.note,
            trend_provider_name=payload.trend_provider,
            approved_actions=payload.approved_actions,
            reset_downstream_tasks=payload.reset_downstream_tasks,
        ),
    )


@router.get("/projects/{project_id}/audit", response_model=ProjectAudit)
def project_audit(project_id: str, request: Request) -> ProjectAudit:
    return _run_orchestrator_action(
        request=request,
        action=lambda runtime_orchestrator: runtime_orchestrator.get_project_audit(project_id),
    )
