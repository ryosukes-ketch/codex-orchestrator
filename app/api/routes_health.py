from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import func, select, text

from app.api.schemas import HealthResponse, StatusResponse
from app.db.models import (
    MarketCatalogModel,
    MarketSnapshotModel,
    ReleaseActualModel,
    ReleaseCalendarModel,
    SignalModel,
)
from app.db.repositories import MonitorEventRepository
from app.domain.enums import MonitorStatus
from app.utils.time import utc_now

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    runtime = request.app.state.runtime
    async with runtime.session_factory() as session:
        await session.execute(text("SELECT 1"))
    return HealthResponse(status="ok", database_ok=True, time_utc=utc_now())


@router.get("/status", response_model=StatusResponse, tags=["status"])
async def status_summary(request: Request) -> StatusResponse:
    runtime = request.app.state.runtime
    try:
        async with runtime.session_factory() as session:
            await session.execute(text("SELECT 1"))
            monitor_repo = MonitorEventRepository(session)

            release_calendar_count = int((await session.execute(select(func.count(ReleaseCalendarModel.release_id)))).scalar_one())
            release_actuals_count = int((await session.execute(select(func.count(ReleaseActualModel.release_id)))).scalar_one())
            market_catalog_count = int((await session.execute(select(func.count(MarketCatalogModel.market_ticker)))).scalar_one())
            market_snapshots_count = int((await session.execute(select(func.count(MarketSnapshotModel.snapshot_id)))).scalar_one())
            signals_count = int((await session.execute(select(func.count(SignalModel.signal_id)))).scalar_one())

            open_monitor_events_count = await monitor_repo.count_by_statuses(
                [
                    MonitorStatus.OPEN.value,
                    MonitorStatus.ACKNOWLEDGED.value,
                    MonitorStatus.SUPPRESSED.value,
                ]
            )
            resolved_monitor_events_count = await monitor_repo.count_by_statuses([MonitorStatus.RESOLVED.value])
            latest_live_cycle_success_at_utc = await monitor_repo.get_last_live_cycle_success_at()

            monitoring_status_value = "unknown"
            monitoring_service = getattr(runtime, "monitoring_service", None)
            if monitoring_service is not None:
                monitoring_status_payload = await monitoring_service.get_status(session)
                monitoring_status_value = str(monitoring_status_payload.get("status", "unknown"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"status unavailable: {exc}",
        ) from exc

    return StatusResponse(
        latest_live_cycle_success_at_utc=latest_live_cycle_success_at_utc,
        release_calendar_count=release_calendar_count,
        release_actuals_count=release_actuals_count,
        market_catalog_count=market_catalog_count,
        market_snapshots_count=market_snapshots_count,
        signals_count=signals_count,
        open_monitor_events_count=open_monitor_events_count,
        resolved_monitor_events_count=resolved_monitor_events_count,
        monitoring_status=monitoring_status_value,
        skip_remote_schedule_ingestion=bool(runtime.settings.skip_remote_schedule_ingestion),
    )
