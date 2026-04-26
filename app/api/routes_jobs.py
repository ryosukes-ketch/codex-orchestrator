from __future__ import annotations

import secrets

from fastapi import APIRouter, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.schemas import BackfillRequest, JobResultResponse, ReplayRequest
from app.config import get_settings

router = APIRouter(tags=["jobs"])
bearer_auth = HTTPBearer(auto_error=False)


def _require_write_job_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
) -> None:
    configured_token = _resolve_write_token(request)
    if not configured_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Write jobs are disabled: API_WRITE_TOKEN is not configured.",
        )
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Authorization header.")
    if credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization must be Bearer token.")
    provided = credentials.credentials.strip()
    if not provided or not secrets.compare_digest(provided, configured_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token.")


def _resolve_write_token(request: Request) -> str:
    runtime = getattr(request.app.state, "runtime", None)
    runtime_settings = getattr(runtime, "settings", None)
    token = getattr(runtime_settings, "api_write_token", "") if runtime_settings else ""
    if token:
        return str(token).strip()
    return get_settings().api_write_token.strip()


@router.post("/jobs/backfill", response_model=JobResultResponse)
async def backfill_job(
    request: Request,
    payload: BackfillRequest,
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_auth),
) -> JobResultResponse:
    _require_write_job_token(request, credentials)
    runtime = request.app.state.runtime
    if payload.to_utc <= payload.from_utc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="`to` must be later than `from`.")
    async with runtime.session_factory() as session:
        detail = await runtime.backfill_service.run(session, payload.from_utc, payload.to_utc)
    return JobResultResponse(status="ok", detail=detail)


@router.post("/jobs/replay", response_model=JobResultResponse)
async def replay_job(
    request: Request,
    payload: ReplayRequest,
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_auth),
) -> JobResultResponse:
    _require_write_job_token(request, credentials)
    runtime = request.app.state.runtime
    async with runtime.session_factory() as session:
        detail = await runtime.replay_service.replay_release(session, payload.release_id)
    if detail["signals_saved"] == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="release not found or no markets.")
    return JobResultResponse(status="ok", detail=detail)
