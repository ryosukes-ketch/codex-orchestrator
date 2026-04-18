from __future__ import annotations

import os
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import create_app


class _FakeSession:
    async def execute(self, _query):
        return None

    async def commit(self):
        return None


class _SessionFactory:
    def __call__(self):
        return self

    async def __aenter__(self):
        return _FakeSession()

    async def __aexit__(self, exc_type, exc, tb):
        return None


class _FakeMonitoringService:
    async def get_status(self, session):
        _ = session
        return {
            "last_live_cycle_success_at_utc": datetime(2026, 6, 11, 12, 30, tzinfo=timezone.utc),
            "upcoming_release_count_7d": 4,
            "open_critical_count": 1,
            "open_warning_count": 2,
            "last_notification_failure_at_utc": datetime(2026, 6, 11, 12, 35, tzinfo=timezone.utc),
            "last_actual_missing_at_utc": datetime(2026, 6, 11, 12, 37, tzinfo=timezone.utc),
            "status": "degraded",
        }

    async def list_recent_events(self, session, *, limit: int, severity=None, monitor_type=None, status=None):
        _ = session, limit, severity, monitor_type, status
        return [
            SimpleNamespace(
                event_id="e1",
                created_at_utc=datetime(2026, 6, 11, 12, 30, tzinfo=timezone.utc),
                updated_at_utc=datetime(2026, 6, 11, 12, 31, tzinfo=timezone.utc),
                monitor_type="ACTUAL_MISSING_AFTER_RELEASE",
                component="actual_parser",
                severity="critical",
                status="open",
                dedupe_key="ACTUAL_MISSING_AFTER_RELEASE:CPI-2026-06-11",
                title="missing actual",
                message="actual missing",
                release_id="CPI-2026-06-11",
                market_ticker=None,
                details_json={"minutes_late": 7},
                first_seen_at_utc=datetime(2026, 6, 11, 12, 30, tzinfo=timezone.utc),
                last_seen_at_utc=datetime(2026, 6, 11, 12, 31, tzinfo=timezone.utc),
                occurrence_count=2,
                alert_sent_at_utc=datetime(2026, 6, 11, 12, 30, tzinfo=timezone.utc),
                resolved_at_utc=None,
            )
        ]

    async def list_open_events(self, session, limit: int = 200):
        return await self.list_recent_events(session, limit=limit)


def test_monitoring_routes() -> None:
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres:postgres@localhost:5432/macro_release_scanner_test"
    from app.config import get_settings

    get_settings.cache_clear()
    app = create_app()
    app.state.runtime = SimpleNamespace(
        session_factory=_SessionFactory(),
        monitoring_service=_FakeMonitoringService(),
    )
    client = TestClient(app)

    status_response = client.get("/monitoring/status")
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "degraded"
    assert status_response.json()["open_critical_count"] == 1

    recent_response = client.get(
        "/monitoring/events/recent",
        params={"limit": 10, "severity": "critical", "status": "open"},
    )
    assert recent_response.status_code == 200
    assert recent_response.json()[0]["monitor_type"] == "ACTUAL_MISSING_AFTER_RELEASE"

    open_response = client.get("/monitoring/events/open")
    assert open_response.status_code == 200
    assert open_response.json()[0]["status"] == "open"

    monitor_response = client.get("/monitor", params={"limit": 5})
    assert monitor_response.status_code == 200
    assert monitor_response.json()[0]["monitor_type"] == "ACTUAL_MISSING_AFTER_RELEASE"
    assert monitor_response.json()[0]["dedupe_key"].startswith("ACTUAL_MISSING_AFTER_RELEASE")
