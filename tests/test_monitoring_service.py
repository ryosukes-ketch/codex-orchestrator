from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.domain.enums import MonitorSeverity, MonitorStatus, MonitorType
from app.services.monitoring_service import MonitoringService


class _FakeTelegram:
    def __init__(self) -> None:
        self.calls: list[dict[str, str | None]] = []

    async def send_message(self, message: str, chat_id: str | None = None) -> bool:
        self.calls.append({"message": message, "chat_id": chat_id})
        return True


class _FakeMonitorRepo:
    def __init__(self) -> None:
        self.events: dict[str, SimpleNamespace] = {}

    async def get_by_dedupe_key(self, dedupe_key: str):
        return self.events.get(dedupe_key)

    async def upsert_open_event(self, **kwargs):
        dedupe_key = kwargs["dedupe_key"]
        existing = self.events.get(dedupe_key)
        if existing is None:
            event = SimpleNamespace(
                event_id=str(uuid.uuid4()),
                created_at_utc=kwargs["now_utc"],
                updated_at_utc=kwargs["now_utc"],
                monitor_type=kwargs["monitor_type"],
                component=kwargs["component"],
                severity=kwargs["severity"],
                status=MonitorStatus.OPEN.value,
                dedupe_key=dedupe_key,
                title=kwargs["title"],
                message=kwargs["message"],
                release_id=kwargs["release_id"],
                market_ticker=kwargs["market_ticker"],
                details_json=kwargs["details_json"],
                first_seen_at_utc=kwargs["now_utc"],
                last_seen_at_utc=kwargs["now_utc"],
                occurrence_count=1,
                alert_sent_at_utc=None,
                resolved_at_utc=None,
            )
            self.events[dedupe_key] = event
            return event
        existing.updated_at_utc = kwargs["now_utc"]
        existing.monitor_type = kwargs["monitor_type"]
        existing.component = kwargs["component"]
        existing.severity = kwargs["severity"]
        existing.status = MonitorStatus.OPEN.value
        existing.title = kwargs["title"]
        existing.message = kwargs["message"]
        existing.release_id = kwargs["release_id"]
        existing.market_ticker = kwargs["market_ticker"]
        existing.details_json = kwargs["details_json"]
        existing.last_seen_at_utc = kwargs["now_utc"]
        existing.occurrence_count += 1
        existing.resolved_at_utc = None
        return existing

    async def resolve_event(self, *, dedupe_key: str, now_utc: datetime, details_json=None):
        event = self.events.get(dedupe_key)
        if event is None:
            return None
        event.status = MonitorStatus.RESOLVED.value
        event.updated_at_utc = now_utc
        event.last_seen_at_utc = now_utc
        event.resolved_at_utc = now_utc
        if details_json is not None:
            event.details_json = details_json
        return event

    async def mark_alert_sent(self, dedupe_key: str, sent_at_utc: datetime) -> None:
        event = self.events[dedupe_key]
        event.alert_sent_at_utc = sent_at_utc
        event.updated_at_utc = sent_at_utc

    async def list_open_like(self, limit: int = 200):
        _ = limit
        return [
            item
            for item in self.events.values()
            if item.status in {MonitorStatus.OPEN.value, MonitorStatus.ACKNOWLEDGED.value, MonitorStatus.SUPPRESSED.value}
        ]

    async def count_open_by_severity(self, severity: str) -> int:
        return sum(
            1
            for item in self.events.values()
            if item.status == MonitorStatus.OPEN.value and item.severity == severity
        )

    async def is_open(self, dedupe_key: str) -> bool:
        event = self.events.get(dedupe_key)
        if event is None:
            return False
        return event.status in {MonitorStatus.OPEN.value, MonitorStatus.ACKNOWLEDGED.value, MonitorStatus.SUPPRESSED.value}

    async def get_last_live_cycle_success_at(self):
        event = self.events.get(MonitorType.LIVE_CYCLE_STALLED.value)
        if event is None:
            return None
        return datetime.fromisoformat(event.details_json["last_live_cycle_success_at_utc"])

    async def latest_last_seen_for_type(self, monitor_type: str):
        candidates = [item.last_seen_at_utc for item in self.events.values() if item.monitor_type == monitor_type]
        if not candidates:
            return None
        return max(candidates)


class _FakeLiveRunner:
    def __init__(self) -> None:
        self.actual_retry_calls = 0

    async def ingest_actual_if_missing(self, session, release_id: str) -> None:
        _ = session, release_id
        self.actual_retry_calls += 1


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


def _service(telegram: _FakeTelegram, live_runner: _FakeLiveRunner) -> MonitoringService:
    settings = Settings(
        DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/test",
        TELEGRAM_BOT_TOKEN="tkn",
        TELEGRAM_CHAT_ID="chat",
        MONITORING_TELEGRAM_CHAT_ID="monitor-chat",
        MONITORING_ALERT_COOLDOWN_CRITICAL_SECONDS=900,
        MONITORING_ACTUAL_MISSING_GRACE_SECONDS=300,
        MONITORING_NO_SIGNAL_GRACE_SECONDS=600,
        MONITORING_SIGNAL_BURST_THRESHOLD=30,
        MONITORING_SIGNAL_BURST_MARKET_THRESHOLD=5,
        MONITORING_NOTIFICATION_FAILURE_BURST_THRESHOLD=3,
    )
    return MonitoringService(
        settings=settings,
        session_factory=_SessionFactory(),  # type: ignore[arg-type]
        telegram_client=telegram,
        calendar_ingestor=SimpleNamespace(ingest=lambda session: None),
        market_discovery=SimpleNamespace(discover_and_store=lambda session: None),
        live_runner=live_runner,
    )


@pytest.mark.asyncio
async def test_monitor_critical_alert_cooldown_and_resend() -> None:
    telegram = _FakeTelegram()
    monitor_repo = _FakeMonitorRepo()
    service = _service(telegram=telegram, live_runner=_FakeLiveRunner())
    now = datetime.now(timezone.utc)

    await service._open_or_update_event(
        repo=monitor_repo,
        now_utc=now,
        monitor_type=MonitorType.NOTIFICATION_FAILURE_BURST,
        component="notification_service",
        severity=MonitorSeverity.CRITICAL,
        dedupe_key=MonitorType.NOTIFICATION_FAILURE_BURST.value,
        title="failure burst",
        message="failed notifications",
        details_json={"count": 3},
    )
    await service._open_or_update_event(
        repo=monitor_repo,
        now_utc=now + timedelta(minutes=1),
        monitor_type=MonitorType.NOTIFICATION_FAILURE_BURST,
        component="notification_service",
        severity=MonitorSeverity.CRITICAL,
        dedupe_key=MonitorType.NOTIFICATION_FAILURE_BURST.value,
        title="failure burst",
        message="failed notifications",
        details_json={"count": 4},
    )
    await service._open_or_update_event(
        repo=monitor_repo,
        now_utc=now + timedelta(minutes=16),
        monitor_type=MonitorType.NOTIFICATION_FAILURE_BURST,
        component="notification_service",
        severity=MonitorSeverity.CRITICAL,
        dedupe_key=MonitorType.NOTIFICATION_FAILURE_BURST.value,
        title="failure burst",
        message="failed notifications",
        details_json={"count": 5},
    )

    assert len(telegram.calls) == 2
    assert monitor_repo.events[MonitorType.NOTIFICATION_FAILURE_BURST.value].occurrence_count == 3


@pytest.mark.asyncio
async def test_actual_missing_retry_runs_once_within_window(monkeypatch) -> None:
    telegram = _FakeTelegram()
    live_runner = _FakeLiveRunner()
    service = _service(telegram=telegram, live_runner=live_runner)
    monitor_repo = _FakeMonitorRepo()
    now = datetime.now(timezone.utc)
    release = SimpleNamespace(
        release_id="CPI-2026-06-11",
        release_type="CPI",
        scheduled_time_utc=now - timedelta(minutes=7),
        source_url="https://www.bls.gov/news.release/archives/cpi_06112026.htm",
    )

    class _ReleaseRepo:
        def __init__(self, session) -> None:
            self.session = session

        async def list_due_for_actual(self, due_before_utc: datetime, limit: int = 500):
            _ = due_before_utc, limit
            return [release]

        async def get_actual(self, release_id: str):
            _ = release_id
            return None

    monkeypatch.setattr("app.services.monitoring_service.ReleaseRepository", _ReleaseRepo)

    await service._rule_actual_missing_after_release(session=object(), monitor_repo=monitor_repo, now_utc=now)
    await service._rule_actual_missing_after_release(
        session=object(),
        monitor_repo=monitor_repo,
        now_utc=now + timedelta(minutes=1),
    )

    assert live_runner.actual_retry_calls == 1
    key = f"{MonitorType.ACTUAL_MISSING_AFTER_RELEASE.value}:{release.release_id}"
    assert key in monitor_repo.events
    assert monitor_repo.events[key].status == MonitorStatus.OPEN.value


@pytest.mark.asyncio
async def test_actual_missing_rule_resolves_after_seeded_actual_available(monkeypatch) -> None:
    telegram = _FakeTelegram()
    service = _service(telegram=telegram, live_runner=_FakeLiveRunner())
    monitor_repo = _FakeMonitorRepo()
    now = datetime.now(timezone.utc)
    release = SimpleNamespace(
        release_id="CPI-2026-06-11",
        release_type="CPI",
        scheduled_time_utc=now - timedelta(minutes=7),
        source_url="manual://release/cpi",
    )
    actual_state = {"row": None}

    class _ReleaseRepo:
        def __init__(self, session) -> None:
            self.session = session

        async def list_due_for_actual(self, due_before_utc: datetime, limit: int = 500):
            _ = due_before_utc, limit
            return [release]

        async def get_actual(self, release_id: str):
            _ = release_id
            return actual_state["row"]

    monkeypatch.setattr("app.services.monitoring_service.ReleaseRepository", _ReleaseRepo)

    opened, resolved, _ = await service._rule_actual_missing_after_release(
        session=object(),
        monitor_repo=monitor_repo,
        now_utc=now,
    )
    assert opened == 1
    assert resolved == 0
    key = f"{MonitorType.ACTUAL_MISSING_AFTER_RELEASE.value}:{release.release_id}"
    assert monitor_repo.events[key].status == MonitorStatus.OPEN.value

    actual_state["row"] = SimpleNamespace(
        actual_value_raw="3.3",
        actual_value_num=3.3,
        parsed_payload_json={"manual_seed": True},
    )
    opened_after, resolved_after, _ = await service._rule_actual_missing_after_release(
        session=object(),
        monitor_repo=monitor_repo,
        now_utc=now + timedelta(minutes=1),
    )
    assert opened_after == 0
    assert resolved_after == 1
    assert monitor_repo.events[key].status == MonitorStatus.RESOLVED.value


@pytest.mark.asyncio
async def test_actual_missing_rule_treats_fomc_text_actual_as_available(monkeypatch) -> None:
    telegram = _FakeTelegram()
    service = _service(telegram=telegram, live_runner=_FakeLiveRunner())
    monitor_repo = _FakeMonitorRepo()
    now = datetime.now(timezone.utc)
    release = SimpleNamespace(
        release_id="FOMC-2026-06-17",
        release_type="FOMC",
        scheduled_time_utc=now - timedelta(minutes=7),
        source_url="manual://release/fomc",
    )

    class _ReleaseRepo:
        def __init__(self, session) -> None:
            self.session = session

        async def list_due_for_actual(self, due_before_utc: datetime, limit: int = 500):
            _ = due_before_utc, limit
            return [release]

        async def get_actual(self, release_id: str):
            _ = release_id
            return SimpleNamespace(
                actual_value_raw="HOLD; target upper bound 4.50",
                actual_value_num=None,
                parsed_payload_json={"manual_seed": True},
            )

    monkeypatch.setattr("app.services.monitoring_service.ReleaseRepository", _ReleaseRepo)

    opened, resolved, _ = await service._rule_actual_missing_after_release(
        session=object(),
        monitor_repo=monitor_repo,
        now_utc=now,
    )
    assert opened == 0
    assert resolved == 0
    key = f"{MonitorType.ACTUAL_MISSING_AFTER_RELEASE.value}:{release.release_id}"
    assert key not in monitor_repo.events


@pytest.mark.asyncio
async def test_upcoming_empty_self_heal_retry_once(monkeypatch) -> None:
    calendar_calls = {"count": 0}
    telegram = _FakeTelegram()
    service = _service(telegram=telegram, live_runner=_FakeLiveRunner())
    monitor_repo = _FakeMonitorRepo()
    now = datetime.now(timezone.utc)

    async def _ingest(_session):
        calendar_calls["count"] += 1
        return 0

    service.calendar_ingestor = SimpleNamespace(ingest=_ingest)

    class _ReleaseRepo:
        def __init__(self, session) -> None:
            self.session = session

        async def count_between(self, from_utc: datetime, to_utc: datetime) -> int:
            _ = from_utc, to_utc
            return 0

    monkeypatch.setattr("app.services.monitoring_service.ReleaseRepository", _ReleaseRepo)

    await service._rule_upcoming_releases_empty(session=object(), monitor_repo=monitor_repo, now_utc=now)
    await service._rule_upcoming_releases_empty(
        session=object(),
        monitor_repo=monitor_repo,
        now_utc=now + timedelta(minutes=5),
    )
    assert calendar_calls["count"] == 1


@pytest.mark.asyncio
async def test_upcoming_releases_present_resolves_empty_event(monkeypatch) -> None:
    telegram = _FakeTelegram()
    service = _service(telegram=telegram, live_runner=_FakeLiveRunner())
    monitor_repo = _FakeMonitorRepo()
    now = datetime.now(timezone.utc)
    dedupe_key = MonitorType.UPCOMING_RELEASES_EMPTY.value
    await monitor_repo.upsert_open_event(
        monitor_type=MonitorType.UPCOMING_RELEASES_EMPTY.value,
        component="calendar_ingestor",
        severity=MonitorSeverity.WARNING.value,
        dedupe_key=dedupe_key,
        title="No upcoming releases found",
        message="No release calendar entries found in the next 7 days.",
        release_id=None,
        market_ticker=None,
        details_json={"upcoming_release_count_7d": 0},
        now_utc=now - timedelta(minutes=1),
    )

    class _ReleaseRepo:
        def __init__(self, session) -> None:
            self.session = session

        async def count_between(self, from_utc: datetime, to_utc: datetime) -> int:
            _ = from_utc, to_utc
            return 1

    monkeypatch.setattr("app.services.monitoring_service.ReleaseRepository", _ReleaseRepo)

    opened, resolved, alerts = await service._rule_upcoming_releases_empty(
        session=object(),
        monitor_repo=monitor_repo,
        now_utc=now,
    )
    assert opened == 0
    assert resolved == 1
    assert alerts == 0
    assert monitor_repo.events[dedupe_key].status == MonitorStatus.RESOLVED.value


@pytest.mark.asyncio
async def test_no_signals_rule_opens_then_resolves(monkeypatch) -> None:
    telegram = _FakeTelegram()
    service = _service(telegram=telegram, live_runner=_FakeLiveRunner())
    monitor_repo = _FakeMonitorRepo()
    now = datetime.now(timezone.utc)
    release = SimpleNamespace(
        release_id="NFP-2026-06-12",
        release_type="NFP",
        scheduled_time_utc=now - timedelta(minutes=12),
        source_url="https://www.bls.gov/news.release/archives/empsit_06122026.htm",
    )
    signal_count_state = {"count": 0}

    class _ReleaseRepo:
        def __init__(self, session) -> None:
            self.session = session

        async def list_due_for_actual(self, due_before_utc: datetime, limit: int = 500):
            _ = due_before_utc, limit
            return [release]

        async def get_actual(self, release_id: str):
            _ = release_id
            return SimpleNamespace(actual_value_num=150000.0)

    class _MarketRepo:
        def __init__(self, session) -> None:
            self.session = session

        async def list_for_release_type(self, release_type: str):
            _ = release_type
            return [SimpleNamespace(market_ticker="NFP-MKT")]

    class _SignalRepo:
        def __init__(self, session) -> None:
            self.session = session

        async def count_for_release_between(self, release_id: str, start_utc: datetime, end_utc: datetime) -> int:
            _ = release_id, start_utc, end_utc
            return signal_count_state["count"]

    class _SnapshotRepo:
        def __init__(self, session) -> None:
            self.session = session

        async def count_for_markets_between(self, market_tickers, start_utc: datetime, end_utc: datetime) -> int:
            _ = market_tickers, start_utc, end_utc
            return 8

    monkeypatch.setattr("app.services.monitoring_service.ReleaseRepository", _ReleaseRepo)
    monkeypatch.setattr("app.services.monitoring_service.MarketRepository", _MarketRepo)
    monkeypatch.setattr("app.services.monitoring_service.SignalRepository", _SignalRepo)
    monkeypatch.setattr("app.services.monitoring_service.SnapshotRepository", _SnapshotRepo)

    await service._rule_no_signals_after_release(session=object(), monitor_repo=monitor_repo, now_utc=now)
    key = f"{MonitorType.NO_SIGNALS_AFTER_RELEASE.value}:{release.release_id}"
    assert monitor_repo.events[key].status == MonitorStatus.OPEN.value

    signal_count_state["count"] = 2
    _, resolved, _ = await service._rule_no_signals_after_release(
        session=object(), monitor_repo=monitor_repo, now_utc=now + timedelta(minutes=1)
    )
    assert resolved == 1
    assert monitor_repo.events[key].status == MonitorStatus.RESOLVED.value


@pytest.mark.asyncio
async def test_signal_burst_rule_detects_release_and_market(monkeypatch) -> None:
    telegram = _FakeTelegram()
    service = _service(telegram=telegram, live_runner=_FakeLiveRunner())
    monitor_repo = _FakeMonitorRepo()
    now = datetime.now(timezone.utc)
    release = SimpleNamespace(
        release_id="FOMC-2026-06-17",
        release_type="FOMC",
        scheduled_time_utc=now - timedelta(minutes=2),
    )

    class _ReleaseRepo:
        def __init__(self, session) -> None:
            self.session = session

        async def list_between(self, from_utc: datetime, to_utc: datetime):
            _ = from_utc, to_utc
            return [release]

    class _SignalRepo:
        def __init__(self, session) -> None:
            self.session = session

        async def count_for_release_between(self, release_id: str, start_utc: datetime, end_utc: datetime) -> int:
            _ = release_id, start_utc, end_utc
            return 35

        async def list_for_release(self, release_id: str):
            _ = release_id
            return [
                SimpleNamespace(
                    market_ticker="FOMC-MKT",
                    emitted_at_utc=now - timedelta(minutes=1),
                    severity="high",
                )
                for _ in range(5)
            ]

    monkeypatch.setattr("app.services.monitoring_service.ReleaseRepository", _ReleaseRepo)
    monkeypatch.setattr("app.services.monitoring_service.SignalRepository", _SignalRepo)

    opened, _, _ = await service._rule_signal_burst(session=object(), monitor_repo=monitor_repo, now_utc=now)
    assert opened >= 2
    assert f"{MonitorType.SIGNAL_BURST.value}:{release.release_id}" in monitor_repo.events
    assert f"{MonitorType.SIGNAL_BURST.value}:{release.release_id}:FOMC-MKT" in monitor_repo.events


@pytest.mark.asyncio
async def test_notification_failure_burst_opens_then_resolves(monkeypatch) -> None:
    telegram = _FakeTelegram()
    service = _service(telegram=telegram, live_runner=_FakeLiveRunner())
    monitor_repo = _FakeMonitorRepo()
    now = datetime.now(timezone.utc)
    failures = {"count": 3}

    class _NotificationRepo:
        def __init__(self, session) -> None:
            self.session = session

        async def count_failed_since(self, since_utc: datetime) -> int:
            _ = since_utc
            return failures["count"]

    monkeypatch.setattr("app.services.monitoring_service.NotificationRepository", _NotificationRepo)

    opened, _, _ = await service._rule_notification_failure_burst(
        session=object(),
        monitor_repo=monitor_repo,
        now_utc=now,
    )
    assert opened == 1
    assert monitor_repo.events[MonitorType.NOTIFICATION_FAILURE_BURST.value].status == MonitorStatus.OPEN.value

    failures["count"] = 0
    _, resolved, _ = await service._rule_notification_failure_burst(
        session=object(),
        monitor_repo=monitor_repo,
        now_utc=now + timedelta(minutes=1),
    )
    assert resolved == 1
    assert monitor_repo.events[MonitorType.NOTIFICATION_FAILURE_BURST.value].status == MonitorStatus.RESOLVED.value


@pytest.mark.asyncio
async def test_fallback_alert_is_suppressed_inside_cooldown(monkeypatch) -> None:
    telegram = _FakeTelegram()
    service = _service(telegram=telegram, live_runner=_FakeLiveRunner())

    async def _raise(*args, **kwargs):
        _ = args, kwargs
        raise RuntimeError("monitoring exploded")

    base = datetime(2026, 6, 20, 0, 0, tzinfo=timezone.utc)
    times = [base, base, base + timedelta(minutes=1), base + timedelta(minutes=1)]
    monkeypatch.setattr("app.services.monitoring_service.utc_now", lambda: times.pop(0))
    monkeypatch.setattr(service, "_evaluate_rules", _raise)

    first = await service.run_once()
    second = await service.run_once()
    assert first["status"] == "error"
    assert second["status"] == "error"
    assert len(telegram.calls) == 1


@pytest.mark.asyncio
async def test_fallback_alert_resends_after_cooldown(monkeypatch) -> None:
    telegram = _FakeTelegram()
    service = _service(telegram=telegram, live_runner=_FakeLiveRunner())

    async def _raise(*args, **kwargs):
        _ = args, kwargs
        raise RuntimeError("monitoring exploded")

    base = datetime(2026, 6, 20, 0, 0, tzinfo=timezone.utc)
    times = [
        base,
        base,
        base + timedelta(seconds=service.settings.monitoring_alert_cooldown_critical_seconds + 1),
        base + timedelta(seconds=service.settings.monitoring_alert_cooldown_critical_seconds + 1),
    ]
    monkeypatch.setattr("app.services.monitoring_service.utc_now", lambda: times.pop(0))
    monkeypatch.setattr(service, "_evaluate_rules", _raise)

    await service.run_once()
    await service.run_once()
    assert len(telegram.calls) == 2


@pytest.mark.asyncio
async def test_actual_parse_error_burst_counts_critical_alert(monkeypatch) -> None:
    telegram = _FakeTelegram()
    service = _service(telegram=telegram, live_runner=_FakeLiveRunner())
    monitor_repo = _FakeMonitorRepo()
    now = datetime.now(timezone.utc)
    releases = [
        SimpleNamespace(release_id="CPI-1", release_type="CPI"),
        SimpleNamespace(release_id="CPI-2", release_type="CPI"),
        SimpleNamespace(release_id="CPI-3", release_type="CPI"),
    ]

    class _ReleaseRepo:
        def __init__(self, session) -> None:
            self.session = session

        async def list_between(self, from_utc: datetime, to_utc: datetime):
            _ = from_utc, to_utc
            return releases

        async def get_actual(self, release_id: str):
            _ = release_id
            return SimpleNamespace(parsed_payload_json={"error": "parse failed"})

    monkeypatch.setattr("app.services.monitoring_service.ReleaseRepository", _ReleaseRepo)
    opened, _, alerts = await service._rule_actual_parse_error_burst(
        session=object(),
        monitor_repo=monitor_repo,
        now_utc=now,
    )
    assert opened == 1
    assert alerts == 1
