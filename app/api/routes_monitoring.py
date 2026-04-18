from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.api.schemas import MonitorEventResponse, MonitoringStatusResponse, MonitorSummaryResponse

router = APIRouter(tags=["monitoring"])


def _require_monitoring_service(request: Request):
    runtime = request.app.state.runtime
    monitoring_service = getattr(runtime, "monitoring_service", None)
    if monitoring_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Monitoring service is not configured.",
        )
    return runtime, monitoring_service


@router.get("/monitoring/status", response_model=MonitoringStatusResponse)
async def monitoring_status(request: Request) -> MonitoringStatusResponse:
    runtime, monitoring_service = _require_monitoring_service(request)
    async with runtime.session_factory() as session:
        payload = await monitoring_service.get_status(session)
    return MonitoringStatusResponse(**payload)


@router.get("/monitoring/events/recent", response_model=list[MonitorEventResponse])
async def monitoring_recent_events(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    severity: str | None = Query(default=None),
    monitor_type: str | None = Query(default=None),
    status_value: str | None = Query(default=None, alias="status"),
) -> list[MonitorEventResponse]:
    runtime, monitoring_service = _require_monitoring_service(request)
    async with runtime.session_factory() as session:
        events = await monitoring_service.list_recent_events(
            session,
            limit=limit,
            severity=severity,
            monitor_type=monitor_type,
            status=status_value,
        )
    return [
        MonitorEventResponse(
            event_id=item.event_id,
            created_at_utc=item.created_at_utc,
            updated_at_utc=item.updated_at_utc,
            monitor_type=item.monitor_type,
            component=item.component,
            severity=item.severity,
            status=item.status,
            dedupe_key=item.dedupe_key,
            title=item.title,
            message=item.message,
            release_id=item.release_id,
            market_ticker=item.market_ticker,
            details_json=item.details_json,
            first_seen_at_utc=item.first_seen_at_utc,
            last_seen_at_utc=item.last_seen_at_utc,
            occurrence_count=item.occurrence_count,
            alert_sent_at_utc=item.alert_sent_at_utc,
            resolved_at_utc=item.resolved_at_utc,
        )
        for item in events
    ]


@router.get("/monitoring/events/open", response_model=list[MonitorEventResponse])
async def monitoring_open_events(
    request: Request,
    limit: int = Query(default=200, ge=1, le=500),
) -> list[MonitorEventResponse]:
    runtime, monitoring_service = _require_monitoring_service(request)
    async with runtime.session_factory() as session:
        events = await monitoring_service.list_open_events(session, limit=limit)
    return [
        MonitorEventResponse(
            event_id=item.event_id,
            created_at_utc=item.created_at_utc,
            updated_at_utc=item.updated_at_utc,
            monitor_type=item.monitor_type,
            component=item.component,
            severity=item.severity,
            status=item.status,
            dedupe_key=item.dedupe_key,
            title=item.title,
            message=item.message,
            release_id=item.release_id,
            market_ticker=item.market_ticker,
            details_json=item.details_json,
            first_seen_at_utc=item.first_seen_at_utc,
            last_seen_at_utc=item.last_seen_at_utc,
            occurrence_count=item.occurrence_count,
            alert_sent_at_utc=item.alert_sent_at_utc,
            resolved_at_utc=item.resolved_at_utc,
        )
        for item in events
    ]


@router.get("/monitor", response_model=list[MonitorSummaryResponse])
async def monitor(
    request: Request,
    limit: int = Query(default=20, ge=1, le=500),
) -> list[MonitorSummaryResponse]:
    runtime, monitoring_service = _require_monitoring_service(request)
    async with runtime.session_factory() as session:
        events = await monitoring_service.list_open_events(session, limit=limit)
    return [
        MonitorSummaryResponse(
            monitor_type=item.monitor_type,
            status=item.status,
            severity=item.severity,
            dedupe_key=item.dedupe_key,
            updated_at_utc=item.updated_at_utc,
            resolved_at_utc=item.resolved_at_utc,
        )
        for item in events
    ]
