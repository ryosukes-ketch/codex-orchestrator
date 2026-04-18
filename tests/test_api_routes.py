from __future__ import annotations

import os
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient


class _FakeSession:
    async def execute(self, _query):
        query = str(_query)
        if "count(" in query and "FROM release_calendar" in query:
            return _FakeResult(2)
        if "count(" in query and "FROM release_actuals" in query:
            return _FakeResult(1)
        if "count(" in query and "FROM market_catalog" in query:
            return _FakeResult(3)
        if "count(" in query and "FROM market_snapshots" in query:
            return _FakeResult(4)
        if "count(" in query and "FROM signals" in query:
            return _FakeResult(2)
        return _FakeResult(1)

    async def commit(self):
        return None


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one(self):
        return self._value


class _SessionFactory:
    def __call__(self):
        return self

    async def __aenter__(self):
        return _FakeSession()

    async def __aexit__(self, exc_type, exc, tb):
        return None


def test_api_routes(monkeypatch) -> None:
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres:postgres@localhost:5432/macro_release_scanner_test"
    os.environ["API_WRITE_TOKEN"] = "write-token"
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()

    async def _list_upcoming(self, now_utc, limit=100):
        return [
            SimpleNamespace(
                release_id="CPI-2026-04-10",
                release_type="CPI",
                release_name="Consumer Price Index",
                scheduled_time_utc=datetime(2026, 4, 10, 12, 30, tzinfo=timezone.utc),
                status="scheduled",
            )
        ]

    async def _list_recent(self, limit=100, severity=None):
        _ = severity
        return [
            SimpleNamespace(
                signal_id="s1",
                release_id="CPI-2026-04-10",
                market_ticker="CPI-MKT",
                signal_type="DELAYED_REPRICING",
                score=72,
                severity="high",
                reason_codes_json=["delayed_repricing_gap"],
                emitted_at_utc=datetime(2026, 4, 10, 12, 31, tzinfo=timezone.utc),
            )
        ]

    async def _count_by_statuses(self, statuses):
        return 2 if "resolved" in statuses else 1

    async def _get_last_live_cycle_success_at(self):
        return datetime(2026, 4, 10, 12, 32, tzinfo=timezone.utc)

    monkeypatch.setattr("app.api.routes_releases.ReleaseRepository.list_upcoming", _list_upcoming)
    monkeypatch.setattr("app.api.routes_signals.SignalRepository.list_recent", _list_recent)
    monkeypatch.setattr("app.api.routes_health.MonitorEventRepository.count_by_statuses", _count_by_statuses)
    monkeypatch.setattr(
        "app.api.routes_health.MonitorEventRepository.get_last_live_cycle_success_at",
        _get_last_live_cycle_success_at,
    )

    class _BackfillSvc:
        async def run(self, session, from_utc, to_utc, send_notifications=False):
            return {"releases_processed": 1, "signals_saved": 2, "signals_notified": 0}

    class _ReplaySvc:
        async def replay_release(self, session, release_id, send_notifications=False):
            return {"signals_saved": 1, "signals_notified": 0}

    class _MonitoringSvc:
        async def get_status(self, session):
            _ = session
            return {"status": "degraded"}

    app.state.runtime = SimpleNamespace(
        session_factory=_SessionFactory(),
        backfill_service=_BackfillSvc(),
        replay_service=_ReplaySvc(),
        monitoring_service=_MonitoringSvc(),
        settings=SimpleNamespace(skip_remote_schedule_ingestion=True),
    )
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    releases = client.get("/releases/upcoming")
    assert releases.status_code == 200
    assert releases.json()[0]["release_type"] == "CPI"

    signals = client.get("/signals/recent")
    assert signals.status_code == 200
    assert signals.json()[0]["signal_type"] == "DELAYED_REPRICING"
    signals_alias = client.get("/signals")
    assert signals_alias.status_code == 200
    assert signals_alias.json()[0]["signal_id"] == "s1"

    status_summary = client.get("/status")
    assert status_summary.status_code == 200
    payload = status_summary.json()
    assert payload["release_calendar_count"] == 2
    assert payload["signals_count"] == 2
    assert payload["monitoring_status"] == "degraded"
    assert payload["skip_remote_schedule_ingestion"] is True

    auth = {"Authorization": "Bearer write-token"}
    wrong_auth = {"Authorization": "Bearer wrong-token"}
    backfill = client.post(
        "/jobs/backfill",
        json={"from": "2026-01-01T00:00:00Z", "to": "2026-02-01T00:00:00Z"},
        headers=auth,
    )
    assert backfill.status_code == 200
    assert backfill.json()["detail"]["releases_processed"] == 1

    replay = client.post("/jobs/replay", json={"release_id": "CPI-2026-04-10"}, headers=auth)
    assert replay.status_code == 200

    unauthorized = client.post("/jobs/replay", json={"release_id": "CPI-2026-04-10"})
    assert unauthorized.status_code == 401
    wrong = client.post("/jobs/replay", json={"release_id": "CPI-2026-04-10"}, headers=wrong_auth)
    assert wrong.status_code == 401
