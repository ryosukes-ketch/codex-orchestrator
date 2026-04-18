from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, desc, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    EvaluationResultModel,
    MarketCatalogModel,
    MarketSnapshotModel,
    MonitorEventModel,
    NotificationModel,
    ReleaseActualModel,
    ReleaseCalendarModel,
    SignalModel,
)
from app.domain.enums import DeliveryStatus, MonitorSeverity, MonitorStatus, MonitorType, Severity
from app.utils.time import utc_now


class ReleaseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert_release(
        self,
        release_id: str,
        release_type: str,
        release_name: str,
        scheduled_time_utc: datetime,
        source_url: str,
        status: str,
    ) -> None:
        stmt = insert(ReleaseCalendarModel).values(
            release_id=release_id,
            release_type=release_type,
            release_name=release_name,
            scheduled_time_utc=scheduled_time_utc,
            source_url=source_url,
            status=status,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[ReleaseCalendarModel.release_id],
            set_={
                "release_type": release_type,
                "release_name": release_name,
                "scheduled_time_utc": scheduled_time_utc,
                "source_url": source_url,
                "status": status,
            },
        )
        await self.session.execute(stmt)

    async def list_upcoming(self, now_utc: datetime, limit: int = 100) -> list[ReleaseCalendarModel]:
        stmt = (
            select(ReleaseCalendarModel)
            .where(ReleaseCalendarModel.scheduled_time_utc >= now_utc)
            .order_by(ReleaseCalendarModel.scheduled_time_utc.asc())
            .limit(limit)
        )
        rows = await self.session.execute(stmt)
        return list(rows.scalars().all())

    async def get_by_id(self, release_id: str) -> ReleaseCalendarModel | None:
        stmt = select(ReleaseCalendarModel).where(ReleaseCalendarModel.release_id == release_id)
        row = await self.session.execute(stmt)
        return row.scalar_one_or_none()

    async def find_by_identity(
        self,
        *,
        release_type: str,
        release_name: str,
        scheduled_time_utc: datetime,
    ) -> ReleaseCalendarModel | None:
        stmt = select(ReleaseCalendarModel).where(
            and_(
                ReleaseCalendarModel.release_type == release_type,
                ReleaseCalendarModel.release_name == release_name,
                ReleaseCalendarModel.scheduled_time_utc == scheduled_time_utc,
            )
        )
        row = await self.session.execute(stmt)
        return row.scalar_one_or_none()

    async def list_between(self, from_utc: datetime, to_utc: datetime) -> list[ReleaseCalendarModel]:
        stmt = (
            select(ReleaseCalendarModel)
            .where(
                and_(
                    ReleaseCalendarModel.scheduled_time_utc >= from_utc,
                    ReleaseCalendarModel.scheduled_time_utc <= to_utc,
                )
            )
            .order_by(ReleaseCalendarModel.scheduled_time_utc.asc())
        )
        row = await self.session.execute(stmt)
        return list(row.scalars().all())

    async def count_between(self, from_utc: datetime, to_utc: datetime) -> int:
        stmt = select(func.count(ReleaseCalendarModel.release_id)).where(
            and_(
                ReleaseCalendarModel.scheduled_time_utc >= from_utc,
                ReleaseCalendarModel.scheduled_time_utc <= to_utc,
            )
        )
        row = await self.session.execute(stmt)
        return int(row.scalar_one() or 0)

    async def list_due_for_actual(self, due_before_utc: datetime, limit: int = 500) -> list[ReleaseCalendarModel]:
        lower_bound = due_before_utc - timedelta(days=30)
        stmt = (
            select(ReleaseCalendarModel)
            .where(
                and_(
                    ReleaseCalendarModel.scheduled_time_utc <= due_before_utc,
                    ReleaseCalendarModel.scheduled_time_utc >= lower_bound,
                )
            )
            .order_by(ReleaseCalendarModel.scheduled_time_utc.desc())
            .limit(limit)
        )
        row = await self.session.execute(stmt)
        return list(row.scalars().all())

    async def upsert_actual(
        self,
        release_id: str,
        actual_value_raw: str,
        actual_value_num: float | None,
        parsed_payload_json: dict[str, Any],
        parsed_at_utc: datetime,
    ) -> None:
        stmt = insert(ReleaseActualModel).values(
            release_id=release_id,
            actual_value_raw=actual_value_raw,
            actual_value_num=actual_value_num,
            parsed_payload_json=parsed_payload_json,
            parsed_at_utc=parsed_at_utc,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[ReleaseActualModel.release_id],
            set_={
                "actual_value_raw": actual_value_raw,
                "actual_value_num": actual_value_num,
                "parsed_payload_json": parsed_payload_json,
                "parsed_at_utc": parsed_at_utc,
            },
        )
        await self.session.execute(stmt)

    async def get_actual(self, release_id: str) -> ReleaseActualModel | None:
        stmt = select(ReleaseActualModel).where(ReleaseActualModel.release_id == release_id)
        row = await self.session.execute(stmt)
        return row.scalar_one_or_none()


class MarketRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert_market(
        self,
        market_ticker: str,
        platform: str,
        title: str,
        subtitle: str | None,
        close_time_utc: datetime | None,
        status: str,
        release_type: str | None,
        mapping_confidence: float,
        mapping_payload_json: dict[str, Any],
    ) -> None:
        stmt = insert(MarketCatalogModel).values(
            market_ticker=market_ticker,
            platform=platform,
            title=title,
            subtitle=subtitle,
            close_time_utc=close_time_utc,
            status=status,
            release_type=release_type,
            mapping_confidence=mapping_confidence,
            mapping_payload_json=mapping_payload_json,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[MarketCatalogModel.market_ticker],
            set_={
                "platform": platform,
                "title": title,
                "subtitle": subtitle,
                "close_time_utc": close_time_utc,
                "status": status,
                "release_type": release_type,
                "mapping_confidence": mapping_confidence,
                "mapping_payload_json": mapping_payload_json,
            },
        )
        await self.session.execute(stmt)

    async def list_for_release_type(self, release_type: str) -> list[MarketCatalogModel]:
        stmt = (
            select(MarketCatalogModel)
            .where(MarketCatalogModel.release_type == release_type)
            .order_by(MarketCatalogModel.market_ticker.asc())
        )
        row = await self.session.execute(stmt)
        return list(row.scalars().all())

    async def get_by_ticker(self, market_ticker: str) -> MarketCatalogModel | None:
        stmt = select(MarketCatalogModel).where(MarketCatalogModel.market_ticker == market_ticker)
        row = await self.session.execute(stmt)
        return row.scalar_one_or_none()

    async def count_for_release_type(self, release_type: str) -> int:
        stmt = select(func.count(MarketCatalogModel.market_ticker)).where(MarketCatalogModel.release_type == release_type)
        row = await self.session.execute(stmt)
        return int(row.scalar_one() or 0)


class SnapshotRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_market_and_time(
        self,
        market_ticker: str,
        captured_at_utc: datetime,
    ) -> MarketSnapshotModel | None:
        stmt = select(MarketSnapshotModel).where(
            and_(
                MarketSnapshotModel.market_ticker == market_ticker,
                MarketSnapshotModel.captured_at_utc == captured_at_utc,
            )
        )
        row = await self.session.execute(stmt)
        return row.scalar_one_or_none()

    async def add_snapshot(
        self,
        market_ticker: str,
        captured_at_utc: datetime,
        yes_bid: float | None,
        yes_ask: float | None,
        mid: float | None,
        spread: float | None,
        last_price: float | None,
        volume: float | None,
    ) -> None:
        stmt = insert(MarketSnapshotModel).values(
            market_ticker=market_ticker,
            captured_at_utc=captured_at_utc,
            yes_bid=yes_bid,
            yes_ask=yes_ask,
            mid=mid,
            spread=spread,
            last_price=last_price,
            volume=volume,
        )
        stmt = stmt.on_conflict_do_nothing(
            index_elements=[MarketSnapshotModel.market_ticker, MarketSnapshotModel.captured_at_utc]
        )
        await self.session.execute(stmt)

    async def upsert_snapshot(
        self,
        market_ticker: str,
        captured_at_utc: datetime,
        yes_bid: float | None,
        yes_ask: float | None,
        mid: float | None,
        spread: float | None,
        last_price: float | None,
        volume: float | None,
    ) -> None:
        stmt = insert(MarketSnapshotModel).values(
            market_ticker=market_ticker,
            captured_at_utc=captured_at_utc,
            yes_bid=yes_bid,
            yes_ask=yes_ask,
            mid=mid,
            spread=spread,
            last_price=last_price,
            volume=volume,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[MarketSnapshotModel.market_ticker, MarketSnapshotModel.captured_at_utc],
            set_={
                "yes_bid": yes_bid,
                "yes_ask": yes_ask,
                "mid": mid,
                "spread": spread,
                "last_price": last_price,
                "volume": volume,
            },
        )
        await self.session.execute(stmt)

    async def list_snapshots(
        self,
        market_ticker: str,
        start_utc: datetime,
        end_utc: datetime,
    ) -> list[MarketSnapshotModel]:
        stmt = (
            select(MarketSnapshotModel)
            .where(
                and_(
                    MarketSnapshotModel.market_ticker == market_ticker,
                    MarketSnapshotModel.captured_at_utc >= start_utc,
                    MarketSnapshotModel.captured_at_utc <= end_utc,
                )
            )
            .order_by(MarketSnapshotModel.captured_at_utc.asc())
        )
        row = await self.session.execute(stmt)
        return list(row.scalars().all())

    async def latest_snapshot_before(
        self, market_ticker: str, ts_utc: datetime
    ) -> MarketSnapshotModel | None:
        stmt = (
            select(MarketSnapshotModel)
            .where(
                and_(
                    MarketSnapshotModel.market_ticker == market_ticker,
                    MarketSnapshotModel.captured_at_utc <= ts_utc,
                )
            )
            .order_by(MarketSnapshotModel.captured_at_utc.desc())
            .limit(1)
        )
        row = await self.session.execute(stmt)
        return row.scalar_one_or_none()

    async def latest_snapshot_anytime(self, market_ticker: str) -> MarketSnapshotModel | None:
        """Return the most recent snapshot for a market regardless of timestamp.

        Used for manual-seed market existence checks where seeded snapshots
        may carry future timestamps relative to the current dev run time.
        """
        stmt = (
            select(MarketSnapshotModel)
            .where(MarketSnapshotModel.market_ticker == market_ticker)
            .order_by(MarketSnapshotModel.captured_at_utc.desc())
            .limit(1)
        )
        row = await self.session.execute(stmt)
        return row.scalar_one_or_none()

    async def count_for_markets_since(self, market_tickers: list[str], since_utc: datetime) -> int:
        if not market_tickers:
            return 0
        stmt = select(func.count(MarketSnapshotModel.snapshot_id)).where(
            and_(
                MarketSnapshotModel.market_ticker.in_(market_tickers),
                MarketSnapshotModel.captured_at_utc >= since_utc,
            )
        )
        row = await self.session.execute(stmt)
        return int(row.scalar_one() or 0)

    async def count_for_markets_between(
        self,
        market_tickers: list[str],
        start_utc: datetime,
        end_utc: datetime,
    ) -> int:
        if not market_tickers:
            return 0
        stmt = select(func.count(MarketSnapshotModel.snapshot_id)).where(
            and_(
                MarketSnapshotModel.market_ticker.in_(market_tickers),
                MarketSnapshotModel.captured_at_utc >= start_utc,
                MarketSnapshotModel.captured_at_utc <= end_utc,
            )
        )
        row = await self.session.execute(stmt)
        return int(row.scalar_one() or 0)


class SignalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert_signal(
        self,
        signal_id: str,
        release_id: str,
        market_ticker: str,
        signal_type: str,
        score: int,
        severity: str,
        reason_codes_json: list[str],
        metrics_json: dict[str, Any],
        emitted_at_utc: datetime,
    ) -> None:
        stmt = insert(SignalModel).values(
            signal_id=signal_id,
            release_id=release_id,
            market_ticker=market_ticker,
            signal_type=signal_type,
            score=score,
            severity=severity,
            reason_codes_json=reason_codes_json,
            metrics_json=metrics_json,
            emitted_at_utc=emitted_at_utc,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[SignalModel.signal_id],
            set_={
                "score": score,
                "severity": severity,
                "reason_codes_json": reason_codes_json,
                "metrics_json": metrics_json,
                "emitted_at_utc": emitted_at_utc,
            },
        )
        await self.session.execute(stmt)

    async def list_recent(self, limit: int = 100, severity: str | None = None) -> list[SignalModel]:
        stmt = select(SignalModel)
        if severity:
            stmt = stmt.where(SignalModel.severity == severity)
        stmt = stmt.order_by(SignalModel.emitted_at_utc.desc()).limit(limit)
        row = await self.session.execute(stmt)
        return list(row.scalars().all())

    async def get_by_id(self, signal_id: str) -> SignalModel | None:
        stmt = select(SignalModel).where(SignalModel.signal_id == signal_id)
        row = await self.session.execute(stmt)
        return row.scalar_one_or_none()

    async def list_for_release(self, release_id: str) -> list[SignalModel]:
        stmt = (
            select(SignalModel)
            .where(SignalModel.release_id == release_id)
            .order_by(SignalModel.emitted_at_utc.asc())
        )
        row = await self.session.execute(stmt)
        return list(row.scalars().all())

    async def count_for_release_between(self, release_id: str, start_utc: datetime, end_utc: datetime) -> int:
        stmt = select(func.count(SignalModel.signal_id)).where(
            and_(
                SignalModel.release_id == release_id,
                SignalModel.emitted_at_utc >= start_utc,
                SignalModel.emitted_at_utc <= end_utc,
            )
        )
        row = await self.session.execute(stmt)
        return int(row.scalar_one() or 0)

    async def count_high_or_critical_for_market_between(
        self,
        release_id: str,
        market_ticker: str,
        start_utc: datetime,
        end_utc: datetime,
    ) -> int:
        stmt = select(func.count(SignalModel.signal_id)).where(
            and_(
                SignalModel.release_id == release_id,
                SignalModel.market_ticker == market_ticker,
                SignalModel.emitted_at_utc >= start_utc,
                SignalModel.emitted_at_utc <= end_utc,
                SignalModel.severity.in_([Severity.HIGH.value, Severity.CRITICAL.value]),
            )
        )
        row = await self.session.execute(stmt)
        return int(row.scalar_one() or 0)


class NotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_notification(
        self,
        notification_id: str,
        signal_id: str,
        channel: str,
        sent_at_utc: datetime,
        delivery_status: str,
        payload_json: dict[str, Any],
    ) -> None:
        stmt = insert(NotificationModel).values(
            notification_id=notification_id,
            signal_id=signal_id,
            channel=channel,
            sent_at_utc=sent_at_utc,
            delivery_status=delivery_status,
            payload_json=payload_json,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[NotificationModel.signal_id, NotificationModel.channel],
            set_={
                "notification_id": notification_id,
                "sent_at_utc": sent_at_utc,
                "delivery_status": delivery_status,
                "payload_json": payload_json,
            },
            where=NotificationModel.delivery_status == DeliveryStatus.FAILED.value,
        )
        await self.session.execute(stmt)

    async def has_recent_for_market(self, market_ticker: str, cooldown_seconds: int) -> bool:
        threshold = utc_now() - timedelta(seconds=cooldown_seconds)
        stmt = (
            select(NotificationModel.notification_id)
            .join(SignalModel, NotificationModel.signal_id == SignalModel.signal_id)
            .where(
                and_(
                    SignalModel.market_ticker == market_ticker,
                    NotificationModel.sent_at_utc >= threshold,
                    NotificationModel.delivery_status == DeliveryStatus.SENT.value,
                )
            )
            .limit(1)
        )
        row = await self.session.execute(stmt)
        return row.scalar_one_or_none() is not None

    async def has_duplicate_in_cooldown(
        self,
        release_id: str,
        signal_type: str,
        market_ticker: str,
        cooldown_seconds: int,
    ) -> bool:
        threshold = utc_now() - timedelta(seconds=cooldown_seconds)
        stmt = (
            select(NotificationModel.notification_id)
            .join(SignalModel, NotificationModel.signal_id == SignalModel.signal_id)
            .where(
                and_(
                    SignalModel.release_id == release_id,
                    SignalModel.signal_type == signal_type,
                    SignalModel.market_ticker == market_ticker,
                    NotificationModel.sent_at_utc >= threshold,
                    NotificationModel.delivery_status == DeliveryStatus.SENT.value,
                )
            )
            .limit(1)
        )
        row = await self.session.execute(stmt)
        return row.scalar_one_or_none() is not None

    async def count_failed_since(self, since_utc: datetime) -> int:
        stmt = select(func.count(NotificationModel.notification_id)).where(
            and_(
                NotificationModel.delivery_status == DeliveryStatus.FAILED.value,
                NotificationModel.sent_at_utc >= since_utc,
            )
        )
        row = await self.session.execute(stmt)
        return int(row.scalar_one() or 0)

    async def last_failed_at(self) -> datetime | None:
        stmt = (
            select(NotificationModel.sent_at_utc)
            .where(NotificationModel.delivery_status == DeliveryStatus.FAILED.value)
            .order_by(NotificationModel.sent_at_utc.desc())
            .limit(1)
        )
        row = await self.session.execute(stmt)
        return row.scalar_one_or_none()


class EvaluationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert_result(
        self,
        signal_id: str,
        horizon_sec: int,
        move_after_horizon: float,
        success_bool: bool,
        evaluated_at_utc: datetime,
    ) -> None:
        stmt = insert(EvaluationResultModel).values(
            signal_id=signal_id,
            horizon_sec=horizon_sec,
            move_after_horizon=move_after_horizon,
            success_bool=success_bool,
            evaluated_at_utc=evaluated_at_utc,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[EvaluationResultModel.signal_id, EvaluationResultModel.horizon_sec],
            set_={
                "move_after_horizon": move_after_horizon,
                "success_bool": success_bool,
                "evaluated_at_utc": evaluated_at_utc,
            },
        )
        await self.session.execute(stmt)


class MonitorEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_dedupe_key(self, dedupe_key: str) -> MonitorEventModel | None:
        stmt = select(MonitorEventModel).where(MonitorEventModel.dedupe_key == dedupe_key)
        row = await self.session.execute(stmt)
        return row.scalar_one_or_none()

    async def upsert_open_event(
        self,
        *,
        monitor_type: str,
        component: str,
        severity: str,
        dedupe_key: str,
        title: str,
        message: str,
        release_id: str | None,
        market_ticker: str | None,
        details_json: dict[str, Any],
        now_utc: datetime,
    ) -> MonitorEventModel:
        stmt = insert(MonitorEventModel).values(
            event_id=str(uuid.uuid4()),
            created_at_utc=now_utc,
            updated_at_utc=now_utc,
            monitor_type=monitor_type,
            component=component,
            severity=severity,
            status=MonitorStatus.OPEN.value,
            dedupe_key=dedupe_key,
            title=title,
            message=message,
            release_id=release_id,
            market_ticker=market_ticker,
            details_json=details_json,
            first_seen_at_utc=now_utc,
            last_seen_at_utc=now_utc,
            occurrence_count=1,
            alert_sent_at_utc=None,
            resolved_at_utc=None,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[MonitorEventModel.dedupe_key],
            set_={
                "updated_at_utc": now_utc,
                "monitor_type": monitor_type,
                "component": component,
                "severity": severity,
                "status": MonitorStatus.OPEN.value,
                "title": title,
                "message": message,
                "release_id": release_id,
                "market_ticker": market_ticker,
                "details_json": details_json,
                "last_seen_at_utc": now_utc,
                "occurrence_count": MonitorEventModel.occurrence_count + 1,
                "resolved_at_utc": None,
            },
        )
        await self.session.execute(stmt)
        event = await self.get_by_dedupe_key(dedupe_key)
        if event is None:
            raise RuntimeError(f"failed to upsert monitor event: {dedupe_key}")
        return event

    async def upsert_resolved_event(
        self,
        *,
        monitor_type: str,
        component: str,
        severity: str,
        dedupe_key: str,
        title: str,
        message: str,
        details_json: dict[str, Any],
        now_utc: datetime,
    ) -> MonitorEventModel:
        stmt = insert(MonitorEventModel).values(
            event_id=str(uuid.uuid4()),
            created_at_utc=now_utc,
            updated_at_utc=now_utc,
            monitor_type=monitor_type,
            component=component,
            severity=severity,
            status=MonitorStatus.RESOLVED.value,
            dedupe_key=dedupe_key,
            title=title,
            message=message,
            release_id=None,
            market_ticker=None,
            details_json=details_json,
            first_seen_at_utc=now_utc,
            last_seen_at_utc=now_utc,
            occurrence_count=1,
            alert_sent_at_utc=None,
            resolved_at_utc=now_utc,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[MonitorEventModel.dedupe_key],
            set_={
                "updated_at_utc": now_utc,
                "monitor_type": monitor_type,
                "component": component,
                "severity": severity,
                "status": MonitorStatus.RESOLVED.value,
                "title": title,
                "message": message,
                "details_json": details_json,
                "last_seen_at_utc": now_utc,
                "resolved_at_utc": now_utc,
            },
        )
        await self.session.execute(stmt)
        event = await self.get_by_dedupe_key(dedupe_key)
        if event is None:
            raise RuntimeError(f"failed to resolve monitor event: {dedupe_key}")
        return event

    async def resolve_event(
        self,
        *,
        dedupe_key: str,
        now_utc: datetime,
        details_json: dict[str, Any] | None = None,
    ) -> MonitorEventModel | None:
        event = await self.get_by_dedupe_key(dedupe_key)
        if event is None:
            return None
        event.status = MonitorStatus.RESOLVED.value
        event.updated_at_utc = now_utc
        event.last_seen_at_utc = now_utc
        event.resolved_at_utc = now_utc
        if details_json is not None:
            event.details_json = details_json
        await self.session.flush()
        return event

    async def mark_alert_sent(self, dedupe_key: str, sent_at_utc: datetime) -> None:
        event = await self.get_by_dedupe_key(dedupe_key)
        if event is None:
            return
        event.alert_sent_at_utc = sent_at_utc
        event.updated_at_utc = sent_at_utc
        await self.session.flush()

    async def list_recent(
        self,
        *,
        limit: int,
        severity: str | None = None,
        monitor_type: str | None = None,
        status: str | None = None,
    ) -> list[MonitorEventModel]:
        stmt = select(MonitorEventModel)
        if severity:
            stmt = stmt.where(MonitorEventModel.severity == severity)
        if monitor_type:
            stmt = stmt.where(MonitorEventModel.monitor_type == monitor_type)
        if status:
            stmt = stmt.where(MonitorEventModel.status == status)
        stmt = stmt.order_by(desc(MonitorEventModel.created_at_utc)).limit(limit)
        row = await self.session.execute(stmt)
        return list(row.scalars().all())

    async def list_open_like(self, limit: int = 200) -> list[MonitorEventModel]:
        stmt = (
            select(MonitorEventModel)
            .where(
                MonitorEventModel.status.in_(
                    [
                        MonitorStatus.OPEN.value,
                        MonitorStatus.ACKNOWLEDGED.value,
                        MonitorStatus.SUPPRESSED.value,
                    ]
                )
            )
            .order_by(desc(MonitorEventModel.last_seen_at_utc))
            .limit(limit)
        )
        row = await self.session.execute(stmt)
        return list(row.scalars().all())

    async def count_open_by_severity(self, severity: str) -> int:
        stmt = select(func.count(MonitorEventModel.event_id)).where(
            and_(
                MonitorEventModel.status == MonitorStatus.OPEN.value,
                MonitorEventModel.severity == severity,
            )
        )
        row = await self.session.execute(stmt)
        return int(row.scalar_one() or 0)

    async def count_by_statuses(self, statuses: list[str]) -> int:
        if not statuses:
            return 0
        stmt = select(func.count(MonitorEventModel.event_id)).where(MonitorEventModel.status.in_(statuses))
        row = await self.session.execute(stmt)
        return int(row.scalar_one() or 0)

    async def get_last_live_cycle_success_at(self) -> datetime | None:
        event = await self.get_by_dedupe_key(MonitorType.LIVE_CYCLE_STALLED.value)
        if event is None:
            return None
        raw = event.details_json.get("last_live_cycle_success_at_utc") if isinstance(event.details_json, dict) else None
        if not isinstance(raw, str):
            return None
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None

    async def latest_last_seen_for_type(self, monitor_type: str) -> datetime | None:
        stmt = (
            select(MonitorEventModel.last_seen_at_utc)
            .where(MonitorEventModel.monitor_type == monitor_type)
            .order_by(MonitorEventModel.last_seen_at_utc.desc())
            .limit(1)
        )
        row = await self.session.execute(stmt)
        return row.scalar_one_or_none()

    async def is_open(self, dedupe_key: str) -> bool:
        stmt = select(MonitorEventModel.status).where(MonitorEventModel.dedupe_key == dedupe_key).limit(1)
        row = await self.session.execute(stmt)
        status = row.scalar_one_or_none()
        return status in {MonitorStatus.OPEN.value, MonitorStatus.ACKNOWLEDGED.value, MonitorStatus.SUPPRESSED.value}

    async def record_live_cycle_success(self, now_utc: datetime) -> MonitorEventModel:
        return await self.upsert_resolved_event(
            monitor_type=MonitorType.LIVE_CYCLE_STALLED.value,
            component="live_runner",
            severity=MonitorSeverity.CRITICAL.value,
            dedupe_key=MonitorType.LIVE_CYCLE_STALLED.value,
            title="Live cycle running normally",
            message="Live cycle completed successfully.",
            details_json={"last_live_cycle_success_at_utc": now_utc.isoformat()},
            now_utc=now_utc,
        )
