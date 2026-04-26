from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.db.models import MarketCatalogModel, ReleaseActualModel, ReleaseCalendarModel, SignalModel
from app.services.notification_service import NotificationService


class _FakeTelegram:
    def __init__(self) -> None:
        self.calls = 0

    async def send_message(self, message: str) -> bool:
        self.calls += 1
        return True


class _FakeSession:
    async def commit(self) -> None:
        return None


@pytest.mark.asyncio
async def test_notification_cooldown_blocks_send(monkeypatch) -> None:
    telegram = _FakeTelegram()
    service = NotificationService(telegram_client=telegram, display_timezone="Asia/Tokyo")

    class _Repo:
        def __init__(self, session) -> None:
            self.session = session

        async def has_recent_for_market(self, market_ticker: str, cooldown_seconds: int) -> bool:
            return True

        async def has_duplicate_in_cooldown(
            self, release_id: str, signal_type: str, market_ticker: str, cooldown_seconds: int
        ) -> bool:
            return False

        async def create_notification(self, **kwargs):
            return None

    monkeypatch.setattr("app.services.notification_service.NotificationRepository", _Repo)
    signal = SignalModel(
        signal_id="s1",
        release_id="r1",
        market_ticker="m1",
        signal_type="DELAYED_REPRICING",
        score=70,
        severity="high",
        reason_codes_json=["a"],
        metrics_json={"spread": 0.01, "current_mid": 0.5},
        emitted_at_utc=datetime.now(timezone.utc),
    )
    release = ReleaseCalendarModel(
        release_id="r1",
        release_type="CPI",
        release_name="CPI",
        scheduled_time_utc=datetime.now(timezone.utc),
        source_url="https://example.com",
        status="scheduled",
    )
    market = MarketCatalogModel(
        market_ticker="m1",
        platform="kalshi",
        title="CPI > 3.1%",
        subtitle=None,
        close_time_utc=None,
        status="open",
        release_type="CPI",
        mapping_confidence=0.9,
        mapping_payload_json={},
    )
    actual = ReleaseActualModel(
        release_id="r1",
        actual_value_raw="3.3",
        actual_value_num=3.3,
        parsed_payload_json={},
        parsed_at_utc=datetime.now(timezone.utc),
    )
    sent = await service.maybe_send_signal_notification(_FakeSession(), signal, release, market, actual)
    assert sent is False
    assert telegram.calls == 0
