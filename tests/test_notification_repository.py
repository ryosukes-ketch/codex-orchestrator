from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, insert
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import MarketCatalogModel, NotificationModel, ReleaseCalendarModel, SignalModel
from app.db.repositories import NotificationRepository
from app.domain.enums import DeliveryStatus


class _Result:
    def scalar_one_or_none(self):
        return None


class _CaptureSession:
    def __init__(self) -> None:
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return _Result()


def _compile_sql(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
        )
    )


def _async_test_database_url() -> str | None:
    raw = os.getenv("TEST_DATABASE_URL", "").strip()
    if not raw:
        return None
    if raw.startswith("postgresql+asyncpg://"):
        return raw
    if raw.startswith("postgresql://"):
        return raw.replace("postgresql://", "postgresql+asyncpg://", 1)
    return raw


@pytest.mark.asyncio
async def test_market_cooldown_filters_to_sent_only() -> None:
    session = _CaptureSession()
    repo = NotificationRepository(session)
    await repo.has_recent_for_market("CPI-MKT", cooldown_seconds=300)
    sql = _compile_sql(session.statement)
    assert "notifications.delivery_status = %(delivery_status_1)s" in sql
    compiled = session.statement.compile(dialect=postgresql.dialect())
    assert compiled.params["delivery_status_1"] == DeliveryStatus.SENT.value


@pytest.mark.asyncio
async def test_duplicate_cooldown_filters_to_sent_only() -> None:
    session = _CaptureSession()
    repo = NotificationRepository(session)
    await repo.has_duplicate_in_cooldown("r1", "DELAYED_REPRICING", "CPI-MKT", cooldown_seconds=300)
    sql = _compile_sql(session.statement)
    assert "notifications.delivery_status = %(delivery_status_1)s" in sql
    compiled = session.statement.compile(dialect=postgresql.dialect())
    assert compiled.params["delivery_status_1"] == DeliveryStatus.SENT.value


@pytest.mark.asyncio
async def test_failed_notification_can_be_retried_with_upsert() -> None:
    session = _CaptureSession()
    repo = NotificationRepository(session)
    await repo.create_notification(
        notification_id="n1",
        signal_id="s1",
        channel="telegram",
        sent_at_utc=datetime.now(timezone.utc),
        delivery_status=DeliveryStatus.SENT.value,
        payload_json={"ok": True},
    )
    sql = _compile_sql(session.statement)
    assert "ON CONFLICT (signal_id, channel) DO UPDATE" in sql
    compiled = session.statement.compile(dialect=postgresql.dialect())
    assert "WHERE notifications.delivery_status" in sql
    assert compiled.params["delivery_status_1"] == DeliveryStatus.FAILED.value


@pytest.mark.asyncio
@pytest.mark.skipif(
    not _async_test_database_url(),
    reason="Set TEST_DATABASE_URL to run behavioral notification cooldown test.",
)
async def test_cooldown_behavior_ignores_skipped_notifications() -> None:
    engine = create_async_engine(_async_test_database_url() or "")
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    sent_suffix = str(uuid.uuid4())[:8]
    skipped_suffix = str(uuid.uuid4())[:8]
    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        sent_release_id = f"CPI-2026-04-10-{sent_suffix}"
        sent_market = f"CPI-SENT-{sent_suffix}"
        sent_signal = f"signal-sent-{sent_suffix}"
        skipped_release_id = f"CPI-2026-04-11-{skipped_suffix}"
        skipped_market = f"CPI-SKIPPED-{skipped_suffix}"
        skipped_signal = f"signal-skipped-{skipped_suffix}"

        await session.execute(
            insert(ReleaseCalendarModel).values(
                release_id=sent_release_id,
                release_type="CPI",
                release_name="CPI",
                scheduled_time_utc=now,
                source_url="https://example.com/a",
                status="scheduled",
            )
        )
        await session.execute(
            insert(ReleaseCalendarModel).values(
                release_id=skipped_release_id,
                release_type="CPI",
                release_name="CPI",
                scheduled_time_utc=now,
                source_url="https://example.com/b",
                status="scheduled",
            )
        )
        await session.execute(
            insert(MarketCatalogModel).values(
                market_ticker=sent_market,
                platform="kalshi",
                title="sent market",
                subtitle="",
                close_time_utc=now,
                status="open",
                release_type="CPI",
                mapping_confidence=1.0,
                mapping_payload_json={},
            )
        )
        await session.execute(
            insert(MarketCatalogModel).values(
                market_ticker=skipped_market,
                platform="kalshi",
                title="skipped market",
                subtitle="",
                close_time_utc=now,
                status="open",
                release_type="CPI",
                mapping_confidence=1.0,
                mapping_payload_json={},
            )
        )
        await session.execute(
            insert(SignalModel).values(
                signal_id=sent_signal,
                release_id=sent_release_id,
                market_ticker=sent_market,
                signal_type="DELAYED_REPRICING",
                score=70,
                severity="high",
                reason_codes_json=[],
                metrics_json={},
                emitted_at_utc=now,
            )
        )
        await session.execute(
            insert(SignalModel).values(
                signal_id=skipped_signal,
                release_id=skipped_release_id,
                market_ticker=skipped_market,
                signal_type="DELAYED_REPRICING",
                score=70,
                severity="high",
                reason_codes_json=[],
                metrics_json={},
                emitted_at_utc=now,
            )
        )
        await session.execute(
            insert(NotificationModel).values(
                notification_id=f"notif-sent-{sent_suffix}",
                signal_id=sent_signal,
                channel="telegram",
                sent_at_utc=now,
                delivery_status=DeliveryStatus.SENT.value,
                payload_json={"status": "sent"},
            )
        )
        await session.execute(
            insert(NotificationModel).values(
                notification_id=f"notif-skipped-{skipped_suffix}",
                signal_id=skipped_signal,
                channel="telegram",
                sent_at_utc=now,
                delivery_status=DeliveryStatus.SKIPPED.value,
                payload_json={"status": "skipped"},
            )
        )
        await session.commit()

        repo = NotificationRepository(session)
        assert await repo.has_recent_for_market(sent_market, cooldown_seconds=300) is True
        assert await repo.has_recent_for_market(skipped_market, cooldown_seconds=300) is False
        assert await repo.has_duplicate_in_cooldown(
            sent_release_id, "DELAYED_REPRICING", sent_market, cooldown_seconds=300
        ) is True
        assert await repo.has_duplicate_in_cooldown(
            skipped_release_id, "DELAYED_REPRICING", skipped_market, cooldown_seconds=300
        ) is False
        await session.execute(delete(NotificationModel).where(NotificationModel.signal_id.in_([sent_signal, skipped_signal])))
        await session.execute(delete(SignalModel).where(SignalModel.signal_id.in_([sent_signal, skipped_signal])))
        await session.execute(delete(MarketCatalogModel).where(MarketCatalogModel.market_ticker.in_([sent_market, skipped_market])))
        await session.execute(
            delete(ReleaseCalendarModel).where(ReleaseCalendarModel.release_id.in_([sent_release_id, skipped_release_id]))
        )
        await session.commit()

    await engine.dispose()
