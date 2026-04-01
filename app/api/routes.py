from collections.abc import Callable
from typing import TypeVar

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.api.dependencies import get_auth_service_dependency
from app.api.runtime_bindings import resolve_orchestrator_binding
from app.intake.service import IntakeAgent
from app.orchestrator.service import PMOrchestrator
from app.schemas.api import (
    ApprovalRejectRequest,
    ApprovalResumeRequest,
    IntakeBriefRequest,
    OrchestratorRunRequest,
    ReplanningStartRequest,
    RevisionResumeRequest,
)
from app.schemas.brief import IntakeResult
from app.schemas.project import ActorContext, OrchestrationResult, ProjectAudit
from app.services.auth import AuthenticationError, DevTokenAuthService

router = APIRouter()
intake_agent = IntakeAgent()
orchestrator = PMOrchestrator()
_T = TypeVar("_T")


def reset_orchestrator_runtime() -> PMOrchestrator:
    global orchestrator
    orchestrator = PMOrchestrator()
    return orchestrator


def _get_orchestrator(request: Request | None = None) -> PMOrchestrator:
    return resolve_orchestrator_binding(request, fallback_resolver=lambda: orchestrator)


def _resolve_authenticated_actor(
    auth_service: DevTokenAuthService,
    authorization: str | None,
    project_id: str,
    orchestrator_instance: PMOrchestrator | None = None,
) -> ActorContext:
    runtime_orchestrator = orchestrator_instance or orchestrator
    try:
        actor = auth_service.resolve_actor(authorization)
        runtime_orchestrator.record_authentication_success(project_id=project_id, actor=actor)
        return actor
    except AuthenticationError as exc:
        runtime_orchestrator.record_authentication_failure(project_id=project_id, reason=str(exc))
        _raise_route_http_error(exc)


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
    auth_service: DevTokenAuthService,
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
    auth_service: DevTokenAuthService,
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


@router.post("/orchestrator/resume/approval", response_model=OrchestrationResult)
def resume_approval(
    payload: ApprovalResumeRequest,
    request: Request,
    authorization: str | None = Header(default=None),
    auth_service: DevTokenAuthService = Depends(get_auth_service_dependency),
) -> OrchestrationResult:
    return _run_protected_orchestrator_action(
        request=request,
        project_id=payload.project_id,
        authorization=authorization,
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
    authorization: str | None = Header(default=None),
    auth_service: DevTokenAuthService = Depends(get_auth_service_dependency),
) -> OrchestrationResult:
    return _run_protected_orchestrator_action(
        request=request,
        project_id=payload.project_id,
        authorization=authorization,
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
    authorization: str | None = Header(default=None),
    auth_service: DevTokenAuthService = Depends(get_auth_service_dependency),
) -> OrchestrationResult:
    return _run_protected_orchestrator_action(
        request=request,
        project_id=payload.project_id,
        authorization=authorization,
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
    authorization: str | None = Header(default=None),
    auth_service: DevTokenAuthService = Depends(get_auth_service_dependency),
) -> OrchestrationResult:
    return _run_protected_orchestrator_action(
        request=request,
        project_id=payload.project_id,
        authorization=authorization,
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
