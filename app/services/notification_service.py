from __future__ import annotations

import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.telegram_client import TelegramClient
from app.db.models import MarketCatalogModel, ReleaseActualModel, ReleaseCalendarModel, SignalModel
from app.db.repositories import NotificationRepository
from app.domain.enums import DeliveryStatus, NotificationChannel, Severity
from app.utils.time import to_display_timezone, utc_now


class NotificationService:
    def __init__(self, telegram_client: TelegramClient, display_timezone: str) -> None:
        self.telegram_client = telegram_client
        self.display_timezone = display_timezone
        self.cooldown_seconds = 300

    async def maybe_send_signal_notification(
        self,
        session: AsyncSession,
        signal: SignalModel,
        release: ReleaseCalendarModel,
        market: MarketCatalogModel,
        actual: ReleaseActualModel | None,
    ) -> bool:
        if signal.severity not in {Severity.MEDIUM.value, Severity.HIGH.value, Severity.CRITICAL.value}:
            return False

        repo = NotificationRepository(session)
        in_market_cooldown = await repo.has_recent_for_market(signal.market_ticker, self.cooldown_seconds)
        is_duplicate = await repo.has_duplicate_in_cooldown(
            signal.release_id,
            signal.signal_type,
            signal.market_ticker,
            self.cooldown_seconds,
        )
        if in_market_cooldown or is_duplicate:
            await repo.create_notification(
                notification_id=str(uuid.uuid4()),
                signal_id=signal.signal_id,
                channel=NotificationChannel.TELEGRAM.value,
                sent_at_utc=utc_now(),
                delivery_status=DeliveryStatus.SKIPPED.value,
                payload_json={"reason": "cooldown", "market_cooldown": in_market_cooldown, "duplicate": is_duplicate},
            )
            await session.commit()
            return False

        payload = self._build_payload(signal, release, market, actual)
        message = self._format_message(payload)
        sent = await self.telegram_client.send_message(message)
        await repo.create_notification(
            notification_id=str(uuid.uuid4()),
            signal_id=signal.signal_id,
            channel=NotificationChannel.TELEGRAM.value,
            sent_at_utc=utc_now(),
            delivery_status=DeliveryStatus.SENT.value if sent else DeliveryStatus.FAILED.value,
            payload_json=payload,
        )
        await session.commit()
        return sent

    def _build_payload(
        self,
        signal: SignalModel,
        release: ReleaseCalendarModel,
        market: MarketCatalogModel,
        actual: ReleaseActualModel | None,
    ) -> dict[str, object]:
        metrics = signal.metrics_json or {}
        event_time_jst = to_display_timezone(release.scheduled_time_utc, self.display_timezone).strftime(
            "%Y-%m-%d %H:%M:%S %Z"
        )
        payload = {
            "release_type": release.release_type,
            "release_name": release.release_name,
            "event_time_jst": event_time_jst,
            "signal_type": signal.signal_type,
            "severity": signal.severity,
            "market_ticker": signal.market_ticker,
            "market_title": market.title,
            "current_mid": metrics.get("current_mid"),
            "change_30s": metrics.get("change_30s"),
            "spread": metrics.get("spread"),
            "actual_value": actual.actual_value_num if actual else None,
            "interpreted_direction": metrics.get("interpreted_direction", ""),
            "reason_codes": signal.reason_codes_json,
            "dashboard_url": "",
        }
        return payload

    def _format_message(self, payload: dict[str, object]) -> str:
        headline = (
            f"[{str(payload['severity']).upper()}]"
            f"[{payload['release_type']}]"
            f"[{str(payload['signal_type']).replace('_', ' ').title()}] "
            f"{payload['market_title']}"
        )
        body = (
            f"mid={payload['current_mid']} | actual={payload['actual_value']} | "
            f"direction={payload['interpreted_direction']} | spread={payload['spread']}"
        )
        reasons = f"reasons={','.join(payload['reason_codes'])}"  # type: ignore[arg-type]
        structured = json.dumps(payload, ensure_ascii=True)
        return f"{headline}\n{body}\n{reasons}\n{structured}"
