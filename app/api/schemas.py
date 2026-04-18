from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    database_ok: bool
    time_utc: datetime


class ReleaseResponse(BaseModel):
    release_id: str
    release_type: str
    release_name: str
    scheduled_time_utc: datetime
    status: str


class SignalResponse(BaseModel):
    signal_id: str
    release_id: str
    market_ticker: str
    signal_type: str
    score: int
    severity: str
    reason_codes: list[str] = Field(default_factory=list)
    emitted_at_utc: datetime


class BackfillRequest(BaseModel):
    from_utc: datetime = Field(alias="from")
    to_utc: datetime = Field(alias="to")


class ReplayRequest(BaseModel):
    release_id: str


class JobResultResponse(BaseModel):
    status: str
    detail: dict[str, int]


class MonitoringStatusResponse(BaseModel):
    last_live_cycle_success_at_utc: datetime | None
    upcoming_release_count_7d: int
    open_critical_count: int
    open_warning_count: int
    last_notification_failure_at_utc: datetime | None
    last_actual_missing_at_utc: datetime | None
    status: str


class StatusResponse(BaseModel):
    latest_live_cycle_success_at_utc: datetime | None
    release_calendar_count: int
    release_actuals_count: int
    market_catalog_count: int
    market_snapshots_count: int
    signals_count: int
    open_monitor_events_count: int
    resolved_monitor_events_count: int
    monitoring_status: str
    skip_remote_schedule_ingestion: bool


class MonitorEventResponse(BaseModel):
    event_id: str
    created_at_utc: datetime
    updated_at_utc: datetime
    monitor_type: str
    component: str
    severity: str
    status: str
    dedupe_key: str
    title: str
    message: str
    release_id: str | None
    market_ticker: str | None
    details_json: dict[str, object]
    first_seen_at_utc: datetime
    last_seen_at_utc: datetime
    occurrence_count: int
    alert_sent_at_utc: datetime | None
    resolved_at_utc: datetime | None


class MonitorSummaryResponse(BaseModel):
    monitor_type: str
    status: str
    severity: str
    dedupe_key: str
    updated_at_utc: datetime
    resolved_at_utc: datetime | None
