from __future__ import annotations

from fastapi import APIRouter, Query, Request

from app.api.schemas import ReleaseResponse
from app.db.repositories import ReleaseRepository
from app.utils.time import utc_now

router = APIRouter(tags=["releases"])


@router.get("/releases/upcoming", response_model=list[ReleaseResponse])
async def upcoming_releases(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
) -> list[ReleaseResponse]:
    runtime = request.app.state.runtime
    async with runtime.session_factory() as session:
        repo = ReleaseRepository(session)
        releases = await repo.list_upcoming(utc_now(), limit=limit)
        return [
            ReleaseResponse(
                release_id=item.release_id,
                release_type=item.release_type,
                release_name=item.release_name,
                scheduled_time_utc=item.scheduled_time_utc,
                status=item.status,
            )
            for item in releases
        ]
