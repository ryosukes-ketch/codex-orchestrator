from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.domain.enums import MonitorStatus, MonitorType
from app.services.actual_parser import ActualParserService
from app.services.live_runner import LiveRunner
from app.services.monitoring_service import MonitoringService


class _FakeSession:
    async def commit(self) -> None:
        return None


class _SessionFactory:
    def __call__(self):
        return self

    async def __aenter__(self):
        return _FakeSession()

    async def __aexit__(self, exc_type, exc, tb):
        return None


class _CalendarIngestor:
    def __init__(self) -> None:
        self.calls = 0

    async def ingest(self, session) -> int:
        _ = session
        self.calls += 1
        return 1


class _MarketDiscovery:
    def __init__(self) -> None:
        self.calls = 0

    async def discover_and_store(self, session) -> int:
        _ = session
        self.calls += 1
        return 0


class _MarketPoller:
    async def poll_and_store(self, session, tickers) -> int:
        _ = session, tickers
        return 0


class _ReplayService:
    async def replay_release(self, session, release_id: str, send_notifications: bool = True):
        _ = session, release_id, send_notifications
        return {"signals_saved": 0, "signals_notified": 0}


class _NoopClient:
    async def fetch_release_page(self, url: str) -> str:
        _ = url
        return ""

    async def fetch_statement_page(self, path_or_url: str) -> str:
        _ = path_or_url
        return ""


def _runner(calendar_ingestor: _CalendarIngestor) -> LiveRunner:
    settings = Settings(
        DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/test",
        MONITORING_ENABLED=False,
    )
    return LiveRunner(
        settings=settings,
        session_factory=_SessionFactory(),  # type: ignore[arg-type]
        calendar_ingestor=calendar_ingestor,
        market_discovery=_MarketDiscovery(),
        market_poller=_MarketPoller(),
        replay_service=_ReplayService(),
        backfill_service=SimpleNamespace(),
        actual_parser=ActualParserService(),
        bls_client=_NoopClient(),
        bea_client=_NoopClient(),
        fed_client=_NoopClient(),
    )


@pytest.mark.asyncio
async def test_live_once_skip_remote_schedules_uses_seeded_rows(monkeypatch) -> None:
    class _ReleaseRepo:
        def __init__(self, session) -> None:
            self.session = session

        async def list_upcoming(self, now_utc: datetime, limit: int = 1):
            _ = now_utc, limit
            return [
                SimpleNamespace(
                    release_id="CPI-seeded-1",
                    release_type="CPI",
                    release_name="Consumer Price Index",
                    scheduled_time_utc=datetime(2026, 6, 11, 12, 30, tzinfo=timezone.utc),
                    source_url="manual://cpi-2026-06-11",
                    status="scheduled",
                )
            ]

        async def list_between(self, from_utc: datetime, to_utc: datetime):
            _ = from_utc, to_utc
            return []

    monkeypatch.setattr("app.services.live_runner.ReleaseRepository", _ReleaseRepo)

    calendar = _CalendarIngestor()
    runner = _runner(calendar)
    stats = await runner.run_once(skip_remote_schedule_ingestion=True)

    assert calendar.calls == 0
    assert stats["releases_ingested"] == 0
    assert stats["markets_discovered"] == 0


@pytest.mark.asyncio
async def test_live_once_skip_remote_schedules_requires_seeded_rows(monkeypatch) -> None:
    class _ReleaseRepo:
        def __init__(self, session) -> None:
            self.session = session

        async def list_upcoming(self, now_utc: datetime, limit: int = 1):
            _ = now_utc, limit
            return []

    monkeypatch.setattr("app.services.live_runner.ReleaseRepository", _ReleaseRepo)

    runner = _runner(_CalendarIngestor())
    with pytest.raises(RuntimeError, match="no seeded upcoming releases"):
        await runner.run_once(skip_remote_schedule_ingestion=True)


@pytest.mark.asyncio
async def test_live_cycle_stalled_resolves_after_successful_live_cycle(monkeypatch) -> None:
    base = datetime(2026, 4, 18, 1, 40, tzinfo=timezone.utc)
    dedupe_key = MonitorType.LIVE_CYCLE_STALLED.value
    events: dict[str, SimpleNamespace] = {
        dedupe_key: SimpleNamespace(
            dedupe_key=dedupe_key,
            monitor_type=dedupe_key,
            component="live_runner",
            severity="critical",
            status=MonitorStatus.OPEN.value,
            release_id=None,
            market_ticker=None,
            details_json={"last_live_cycle_success_at_utc": (base - timedelta(minutes=20)).isoformat()},
            updated_at_utc=base - timedelta(minutes=20),
            last_seen_at_utc=base - timedelta(minutes=20),
            resolved_at_utc=None,
        )
    }

    class _MonitorRepo:
        def __init__(self, session) -> None:
            self.session = session

        async def record_live_cycle_success(self, now_utc: datetime):
            event = events.get(dedupe_key)
            if event is None:
                event = SimpleNamespace(
                    dedupe_key=dedupe_key,
                    monitor_type=dedupe_key,
                        component="live_runner",
                        severity="critical",
                        status=MonitorStatus.RESOLVED.value,
                        release_id=None,
                        market_ticker=None,
                        details_json={},
                        updated_at_utc=now_utc,
                        last_seen_at_utc=now_utc,
                    resolved_at_utc=now_utc,
                )
                events[dedupe_key] = event
            event.status = MonitorStatus.RESOLVED.value
            event.details_json = {"last_live_cycle_success_at_utc": now_utc.isoformat()}
            event.updated_at_utc = now_utc
            event.last_seen_at_utc = now_utc
            event.resolved_at_utc = now_utc
            return event

        async def get_last_live_cycle_success_at(self):
            event = events.get(dedupe_key)
            if event is None:
                return None
            raw = event.details_json.get("last_live_cycle_success_at_utc")
            if not isinstance(raw, str):
                return None
            return datetime.fromisoformat(raw)

        async def resolve_event(self, *, dedupe_key: str, now_utc: datetime, details_json=None):
            event = events.get(dedupe_key)
            if event is None:
                return None
            event.status = MonitorStatus.RESOLVED.value
            event.updated_at_utc = now_utc
            event.last_seen_at_utc = now_utc
            event.resolved_at_utc = now_utc
            if details_json is not None:
                event.details_json = details_json
            return event

    class _ReleaseRepo:
        def __init__(self, session) -> None:
            self.session = session

        async def list_upcoming(self, now_utc: datetime, limit: int = 1):
            _ = now_utc, limit
            return [
                SimpleNamespace(
                    release_id="CPI-seeded-1",
                    release_type="CPI",
                    release_name="Consumer Price Index",
                    scheduled_time_utc=base + timedelta(hours=1),
                    source_url="manual://cpi-2026-04-18",
                    status="scheduled",
                )
            ]

        async def list_between(self, from_utc: datetime, to_utc: datetime):
            _ = from_utc, to_utc
            return []

    class _NoopTelegram:
        async def send_message(self, message: str, chat_id: str | None = None) -> bool:
            _ = message, chat_id
            return True

    monkeypatch.setattr("app.services.live_runner.ReleaseRepository", _ReleaseRepo)
    monkeypatch.setattr("app.services.live_runner.MonitorEventRepository", _MonitorRepo)
    monkeypatch.setattr("app.services.live_runner.utc_now", lambda: base)

    settings = Settings(
        DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/test",
        MONITORING_ENABLED=True,
    )
    runner = LiveRunner(
        settings=settings,
        session_factory=_SessionFactory(),  # type: ignore[arg-type]
        calendar_ingestor=_CalendarIngestor(),
        market_discovery=_MarketDiscovery(),
        market_poller=_MarketPoller(),
        replay_service=_ReplayService(),
        backfill_service=SimpleNamespace(),
        actual_parser=ActualParserService(),
        bls_client=_NoopClient(),
        bea_client=_NoopClient(),
        fed_client=_NoopClient(),
    )
    await runner.run_once(skip_remote_schedule_ingestion=True)
    assert events[dedupe_key].status == MonitorStatus.RESOLVED.value

    monitoring = MonitoringService(
        settings=settings,
        session_factory=_SessionFactory(),  # type: ignore[arg-type]
        telegram_client=_NoopTelegram(),
        calendar_ingestor=SimpleNamespace(ingest=lambda session: 0),
        market_discovery=SimpleNamespace(discover_and_store=lambda session: 0),
        live_runner=runner,
    )
    monitor_repo = _MonitorRepo(session=object())
    opened, resolved, alerts = await monitoring._rule_live_cycle_stalled(
        session=object(),
        monitor_repo=monitor_repo,
        now_utc=base + timedelta(minutes=1),
    )
    assert opened == 0
    assert resolved == 1
    assert alerts == 0
    assert events[dedupe_key].status == MonitorStatus.RESOLVED.value
