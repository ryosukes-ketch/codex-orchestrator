from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.telegram_client import TelegramClient
from app.config import Settings
from app.db.models import MonitorEventModel, ReleaseActualModel
from app.db.repositories import (
    MarketRepository,
    MonitorEventRepository,
    NotificationRepository,
    ReleaseRepository,
    SignalRepository,
    SnapshotRepository,
)
from app.domain.enums import MonitorSeverity, MonitorType
from app.utils.time import to_display_timezone, utc_now

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class MonitoringSummary:
    opened_or_updated: int
    resolved: int
    alerts_sent: int


class MonitoringService:
    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        telegram_client: TelegramClient,
        calendar_ingestor: Any,
        market_discovery: Any,
        live_runner: Any,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.telegram_client = telegram_client
        self.calendar_ingestor = calendar_ingestor
        self.market_discovery = market_discovery
        self.live_runner = live_runner
        self._last_fallback_alert_sent_at: datetime | None = None

    async def run_once(self) -> dict[str, Any]:
        if not self.settings.monitoring_enabled:
            return {"status": "disabled", "opened_or_updated": 0, "resolved": 0, "alerts_sent": 0}
        now = utc_now()
        try:
            async with self.session_factory() as session:
                summary = await self._evaluate_rules(session=session, now_utc=now)
                await session.commit()
                return {
                    "status": "ok",
                    "opened_or_updated": summary.opened_or_updated,
                    "resolved": summary.resolved,
                    "alerts_sent": summary.alerts_sent,
                }
        except Exception as exc:  # noqa: BLE001
            LOGGER.error("monitoring_tick_failed", extra={"error": str(exc), "error_type": type(exc).__name__})
            try:
                await self._send_fallback_alert(
                    title="Monitoring tick failed",
                    message=f"Monitoring loop failed: {exc}",
                    monitor_type=MonitorType.HEALTHCHECK_FAILURE.value,
                    component="monitoring_service",
                )
            except Exception as alert_exc:  # noqa: BLE001
                LOGGER.warning("monitoring_fallback_alert_failed", extra={"error": str(alert_exc)})
            return {"status": "error", "opened_or_updated": 0, "resolved": 0, "alerts_sent": 0}

    async def run_loop(self) -> None:
        while True:
            await self.run_once()
            await asyncio.sleep(self.settings.monitoring_interval_seconds)

    async def get_status(self, session: AsyncSession) -> dict[str, Any]:
        monitor_repo = MonitorEventRepository(session)
        release_repo = ReleaseRepository(session)
        notification_repo = NotificationRepository(session)
        now = utc_now()
        upcoming_count = await release_repo.count_between(now, now + timedelta(days=7))
        open_critical = await monitor_repo.count_open_by_severity(MonitorSeverity.CRITICAL.value)
        open_warning = await monitor_repo.count_open_by_severity(MonitorSeverity.WARNING.value)
        stalled_open = await monitor_repo.is_open(MonitorType.LIVE_CYCLE_STALLED.value)
        if stalled_open or open_critical >= 3:
            status_value = "critical"
        elif open_critical > 0:
            status_value = "degraded"
        else:
            status_value = "ok"
        return {
            "last_live_cycle_success_at_utc": await monitor_repo.get_last_live_cycle_success_at(),
            "upcoming_release_count_7d": upcoming_count,
            "open_critical_count": open_critical,
            "open_warning_count": open_warning,
            "last_notification_failure_at_utc": await notification_repo.last_failed_at(),
            "last_actual_missing_at_utc": await monitor_repo.latest_last_seen_for_type(
                MonitorType.ACTUAL_MISSING_AFTER_RELEASE.value
            ),
            "status": status_value,
        }

    async def list_recent_events(
        self,
        session: AsyncSession,
        *,
        limit: int,
        severity: str | None = None,
        monitor_type: str | None = None,
        status: str | None = None,
    ) -> list[MonitorEventModel]:
        repo = MonitorEventRepository(session)
        return await repo.list_recent(limit=limit, severity=severity, monitor_type=monitor_type, status=status)

    async def list_open_events(self, session: AsyncSession, limit: int = 200) -> list[MonitorEventModel]:
        repo = MonitorEventRepository(session)
        return await repo.list_open_like(limit=limit)

    async def _evaluate_rules(self, *, session: AsyncSession, now_utc: datetime) -> MonitoringSummary:
        opened_or_updated = 0
        resolved = 0
        alerts_sent = 0
        monitor_repo = MonitorEventRepository(session)

        self._log_rule_eval(MonitorType.HEALTHCHECK_FAILURE, "db")
        health_failed = False
        try:
            await session.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001
            health_failed = True
            if _looks_like_dependency_unavailable(exc):
                LOGGER.error("monitor_healthcheck_dependency_unavailable", extra={"component": "db", "error": str(exc)})
                raise
            result = await self._open_or_update_event(
                repo=monitor_repo,
                now_utc=now_utc,
                monitor_type=MonitorType.HEALTHCHECK_FAILURE,
                component="db",
                severity=MonitorSeverity.CRITICAL,
                dedupe_key=f"{MonitorType.HEALTHCHECK_FAILURE.value}:db",
                title="Database healthcheck failed",
                message="Failed database probe query in monitoring tick.",
                details_json={"error": str(exc)},
            )
            opened_or_updated += 1
            alerts_sent += int(result["alerted"])
        if not health_failed:
            resolved_event = await monitor_repo.resolve_event(
                dedupe_key=f"{MonitorType.HEALTHCHECK_FAILURE.value}:db",
                now_utc=now_utc,
                details_json={"message": "healthcheck recovered"},
            )
            if resolved_event is not None:
                LOGGER.info(
                    "monitor_event_resolved",
                    extra={"monitor_type": resolved_event.monitor_type, "component": resolved_event.component},
                )
                resolved += 1

        open_delta, resolve_delta, alerts_delta = await self._rule_live_cycle_stalled(session, monitor_repo, now_utc)
        opened_or_updated += open_delta
        resolved += resolve_delta
        alerts_sent += alerts_delta

        open_delta, resolve_delta, alerts_delta = await self._rule_upcoming_releases_empty(session, monitor_repo, now_utc)
        opened_or_updated += open_delta
        resolved += resolve_delta
        alerts_sent += alerts_delta

        open_delta, resolve_delta, alerts_delta = await self._rule_actual_missing_after_release(session, monitor_repo, now_utc)
        opened_or_updated += open_delta
        resolved += resolve_delta
        alerts_sent += alerts_delta

        open_delta, resolve_delta, alerts_delta = await self._rule_actual_parse_error_burst(session, monitor_repo, now_utc)
        opened_or_updated += open_delta
        resolved += resolve_delta
        alerts_sent += alerts_delta

        open_delta, resolve_delta, alerts_delta = await self._rule_market_discovery_empty(session, monitor_repo, now_utc)
        opened_or_updated += open_delta
        resolved += resolve_delta
        alerts_sent += alerts_delta

        open_delta, resolve_delta, alerts_delta = await self._rule_snapshot_collection_stalled(session, monitor_repo, now_utc)
        opened_or_updated += open_delta
        resolved += resolve_delta
        alerts_sent += alerts_delta

        open_delta, resolve_delta, alerts_delta = await self._rule_no_signals_after_release(session, monitor_repo, now_utc)
        opened_or_updated += open_delta
        resolved += resolve_delta
        alerts_sent += alerts_delta

        open_delta, resolve_delta, alerts_delta = await self._rule_signal_burst(session, monitor_repo, now_utc)
        opened_or_updated += open_delta
        resolved += resolve_delta
        alerts_sent += alerts_delta

        open_delta, resolve_delta, alerts_delta = await self._rule_notification_failure_burst(session, monitor_repo, now_utc)
        opened_or_updated += open_delta
        resolved += resolve_delta
        alerts_sent += alerts_delta

        return MonitoringSummary(opened_or_updated=opened_or_updated, resolved=resolved, alerts_sent=alerts_sent)

    async def _rule_live_cycle_stalled(
        self,
        session: AsyncSession,
        monitor_repo: MonitorEventRepository,
        now_utc: datetime,
    ) -> tuple[int, int, int]:
        self._log_rule_eval(MonitorType.LIVE_CYCLE_STALLED, "live_runner")
        _ = session
        last_success_at = await monitor_repo.get_last_live_cycle_success_at()
        if last_success_at is None:
            minutes_since = -1.0
        else:
            minutes_since = (now_utc - last_success_at).total_seconds() / 60.0
        if last_success_at is not None and minutes_since < 10:
            resolved_count = await self._resolve_event_with_log(
                repo=monitor_repo,
                dedupe_key=MonitorType.LIVE_CYCLE_STALLED.value,
                now_utc=now_utc,
                details_json={"last_live_cycle_success_at_utc": last_success_at.isoformat()},
            )
            return (0, resolved_count, 0)
        result = await self._open_or_update_event(
            repo=monitor_repo,
            now_utc=now_utc,
            monitor_type=MonitorType.LIVE_CYCLE_STALLED,
            component="live_runner",
            severity=MonitorSeverity.CRITICAL,
            dedupe_key=MonitorType.LIVE_CYCLE_STALLED.value,
            title="Live cycle appears stalled",
            message="No successful live cycle completion has been recorded in the last 10 minutes.",
            details_json={
                "last_success_at_utc": last_success_at.isoformat() if last_success_at else None,
                "minutes_since_last_success": minutes_since,
                "last_live_cycle_success_at_utc": last_success_at.isoformat() if last_success_at else None,
            },
        )
        return (1, 0, int(result["alerted"]))

    async def _rule_upcoming_releases_empty(
        self,
        session: AsyncSession,
        monitor_repo: MonitorEventRepository,
        now_utc: datetime,
    ) -> tuple[int, int, int]:
        self._log_rule_eval(MonitorType.UPCOMING_RELEASES_EMPTY, "calendar_ingestor")
        release_repo = ReleaseRepository(session)
        count_7d = await release_repo.count_between(now_utc, now_utc + timedelta(days=7))
        dedupe_key = MonitorType.UPCOMING_RELEASES_EMPTY.value
        if count_7d == 0:
            existing = await monitor_repo.get_by_dedupe_key(dedupe_key)
            retried = False
            if self._details_value(existing, "calendar_retry_at_utc") is None:
                await self._calendar_retry_with_logging(session)
                retried = True
                count_7d = await release_repo.count_between(now_utc, now_utc + timedelta(days=7))
            if count_7d == 0:
                details = {
                    "upcoming_release_count_7d": count_7d,
                    "calendar_retry_attempted": retried or bool(existing and existing.details_json.get("calendar_retry_at_utc")),
                    "calendar_retry_at_utc": now_utc.isoformat() if retried else self._details_value(existing, "calendar_retry_at_utc"),
                }
                result = await self._open_or_update_event(
                    repo=monitor_repo,
                    now_utc=now_utc,
                    monitor_type=MonitorType.UPCOMING_RELEASES_EMPTY,
                    component="calendar_ingestor",
                    severity=MonitorSeverity.WARNING,
                    dedupe_key=dedupe_key,
                    title="No upcoming releases found",
                    message="No release calendar entries found in the next 7 days.",
                    details_json=details,
                )
                return (1, 0, int(result["alerted"]))
        resolved_count = await self._resolve_event_with_log(
            repo=monitor_repo,
            dedupe_key=dedupe_key,
            now_utc=now_utc,
            details_json={"upcoming_release_count_7d": count_7d},
        )
        return (0, resolved_count, 0)

    async def _rule_actual_missing_after_release(
        self,
        session: AsyncSession,
        monitor_repo: MonitorEventRepository,
        now_utc: datetime,
    ) -> tuple[int, int, int]:
        self._log_rule_eval(MonitorType.ACTUAL_MISSING_AFTER_RELEASE, "actual_parser")
        release_repo = ReleaseRepository(session)
        due_before = now_utc - timedelta(seconds=self.settings.monitoring_actual_missing_grace_seconds)
        releases = await release_repo.list_due_for_actual(due_before_utc=due_before, limit=300)
        opened_or_updated = 0
        resolved = 0
        alerts = 0
        ten_minutes = 600
        for release in releases:
            actual = await release_repo.get_actual(release.release_id)
            dedupe_key = f"{MonitorType.ACTUAL_MISSING_AFTER_RELEASE.value}:{release.release_id}"
            if _actual_available_for_release(release.release_type, actual):
                resolved += await self._resolve_event_with_log(
                    repo=monitor_repo,
                    dedupe_key=dedupe_key,
                    now_utc=now_utc,
                )
                continue
            existing = await monitor_repo.get_by_dedupe_key(dedupe_key)
            retried = False
            if not self._has_retry_within(existing, "actual_retry_at_utc", cooldown_seconds=ten_minutes, now_utc=now_utc):
                retried = True
                await self._actual_retry_with_logging(session, release.release_id)
                actual = await release_repo.get_actual(release.release_id)
                if _actual_available_for_release(release.release_type, actual):
                    resolved += await self._resolve_event_with_log(
                        repo=monitor_repo,
                        dedupe_key=dedupe_key,
                        now_utc=now_utc,
                        details_json={"resolved_by_retry": True},
                    )
                    continue
            parse_error_present = _parse_error_present(actual)
            minutes_late = max(0.0, (now_utc - release.scheduled_time_utc).total_seconds() / 60.0)
            details_json = {
                "release_type": release.release_type,
                "scheduled_time_utc": release.scheduled_time_utc.isoformat(),
                "minutes_late": minutes_late,
                "source_url": release.source_url,
                "parse_error_present": parse_error_present,
                "actual_retry_at_utc": now_utc.isoformat() if retried else self._details_value(existing, "actual_retry_at_utc"),
            }
            result = await self._open_or_update_event(
                repo=monitor_repo,
                now_utc=now_utc,
                monitor_type=MonitorType.ACTUAL_MISSING_AFTER_RELEASE,
                component="actual_parser",
                severity=MonitorSeverity.CRITICAL,
                dedupe_key=dedupe_key,
                title=f"{release.release_type} actual value missing",
                message=f"Actual value still missing {int(minutes_late)} minutes after scheduled release.",
                release_id=release.release_id,
                details_json=details_json,
            )
            opened_or_updated += 1
            alerts += int(result["alerted"])
        return (opened_or_updated, resolved, alerts)

    async def _rule_actual_parse_error_burst(
        self,
        session: AsyncSession,
        monitor_repo: MonitorEventRepository,
        now_utc: datetime,
    ) -> tuple[int, int, int]:
        self._log_rule_eval(MonitorType.ACTUAL_PARSE_ERROR_BURST, "actual_parser")
        release_repo = ReleaseRepository(session)
        recent_releases = await release_repo.list_between(now_utc - timedelta(hours=24), now_utc)
        counts_by_type: dict[str, int] = {}
        for release in recent_releases:
            actual = await release_repo.get_actual(release.release_id)
            if not _parse_error_present(actual):
                continue
            counts_by_type[release.release_type] = counts_by_type.get(release.release_type, 0) + 1
        opened_or_updated = 0
        resolved = 0
        alerts = 0
        for release_type, count in counts_by_type.items():
            if count < 2:
                continue
            severity = MonitorSeverity.CRITICAL if count >= 3 else MonitorSeverity.WARNING
            dedupe_key = f"{MonitorType.ACTUAL_PARSE_ERROR_BURST.value}:{release_type}"
            result = await self._open_or_update_event(
                repo=monitor_repo,
                now_utc=now_utc,
                monitor_type=MonitorType.ACTUAL_PARSE_ERROR_BURST,
                component="actual_parser",
                severity=severity,
                dedupe_key=dedupe_key,
                title=f"{release_type} parse-error burst",
                message=f"{count} actual parse errors detected in the last 24h for {release_type}.",
                details_json={"release_type": release_type, "parse_error_count_24h": count},
            )
            opened_or_updated += 1
            alerts += int(result["alerted"])
        for release_type in ("FOMC", "CPI", "NFP", "GDP_ADVANCE"):
            if counts_by_type.get(release_type, 0) >= 2:
                continue
            dedupe_key = f"{MonitorType.ACTUAL_PARSE_ERROR_BURST.value}:{release_type}"
            resolved += await self._resolve_event_with_log(
                repo=monitor_repo,
                dedupe_key=dedupe_key,
                now_utc=now_utc,
            )
        return (opened_or_updated, resolved, alerts)

    async def _rule_market_discovery_empty(
        self,
        session: AsyncSession,
        monitor_repo: MonitorEventRepository,
        now_utc: datetime,
    ) -> tuple[int, int, int]:
        self._log_rule_eval(MonitorType.MARKET_DISCOVERY_EMPTY, "market_discovery")
        release_repo = ReleaseRepository(session)
        market_repo = MarketRepository(session)
        upcoming = await release_repo.list_between(now_utc, now_utc + timedelta(minutes=60))
        opened_or_updated = 0
        resolved = 0
        alerts = 0
        for release in upcoming:
            dedupe_key = f"{MonitorType.MARKET_DISCOVERY_EMPTY.value}:{release.release_id}"
            market_count = await market_repo.count_for_release_type(release.release_type)
            if market_count == 0:
                existing = await monitor_repo.get_by_dedupe_key(dedupe_key)
                retried = False
                if self._details_value(existing, "discovery_retry_at_utc") is None:
                    retried = True
                    await self._market_discovery_retry_with_logging(session)
                    market_count = await market_repo.count_for_release_type(release.release_type)
                if market_count == 0:
                    result = await self._open_or_update_event(
                        repo=monitor_repo,
                        now_utc=now_utc,
                        monitor_type=MonitorType.MARKET_DISCOVERY_EMPTY,
                        component="market_discovery",
                        severity=MonitorSeverity.WARNING,
                        dedupe_key=dedupe_key,
                        title=f"No mapped markets for {release.release_type}",
                        message="Release is within 60 minutes but mapped market catalog is empty.",
                        release_id=release.release_id,
                        details_json={
                            "release_type": release.release_type,
                            "market_count": market_count,
                            "discovery_retry_at_utc": now_utc.isoformat()
                            if retried
                            else self._details_value(existing, "discovery_retry_at_utc"),
                        },
                    )
                    opened_or_updated += 1
                    alerts += int(result["alerted"])
                    continue
            resolved += await self._resolve_event_with_log(
                repo=monitor_repo,
                dedupe_key=dedupe_key,
                now_utc=now_utc,
            )
        return (opened_or_updated, resolved, alerts)

    async def _rule_snapshot_collection_stalled(
        self,
        session: AsyncSession,
        monitor_repo: MonitorEventRepository,
        now_utc: datetime,
    ) -> tuple[int, int, int]:
        self._log_rule_eval(MonitorType.SNAPSHOT_COLLECTION_STALLED, "market_poller")
        release_repo = ReleaseRepository(session)
        market_repo = MarketRepository(session)
        snapshot_repo = SnapshotRepository(session)
        window = timedelta(minutes=self.settings.active_release_window_minutes)
        active_releases = await release_repo.list_between(now_utc - window, now_utc + window)
        opened_or_updated = 0
        resolved = 0
        alerts = 0
        for release in active_releases:
            dedupe_key = f"{MonitorType.SNAPSHOT_COLLECTION_STALLED.value}:{release.release_id}"
            markets = await market_repo.list_for_release_type(release.release_type)
            tickers = [item.market_ticker for item in markets]
            if not tickers:
                resolved += await self._resolve_event_with_log(
                    repo=monitor_repo,
                    dedupe_key=dedupe_key,
                    now_utc=now_utc,
                )
                continue
            recent_count = await snapshot_repo.count_for_markets_since(tickers, now_utc - timedelta(minutes=3))
            if recent_count == 0:
                result = await self._open_or_update_event(
                    repo=monitor_repo,
                    now_utc=now_utc,
                    monitor_type=MonitorType.SNAPSHOT_COLLECTION_STALLED,
                    component="market_poller",
                    severity=MonitorSeverity.CRITICAL,
                    dedupe_key=dedupe_key,
                    title=f"Snapshot collection stalled for {release.release_type}",
                    message="No new market snapshots were recorded in the last 3 minutes.",
                    release_id=release.release_id,
                    details_json={"market_count": len(tickers), "recent_snapshot_count": recent_count},
                )
                opened_or_updated += 1
                alerts += int(result["alerted"])
                continue
            resolved += await self._resolve_event_with_log(
                repo=monitor_repo,
                dedupe_key=dedupe_key,
                now_utc=now_utc,
            )
        return (opened_or_updated, resolved, alerts)

    async def _rule_no_signals_after_release(
        self,
        session: AsyncSession,
        monitor_repo: MonitorEventRepository,
        now_utc: datetime,
    ) -> tuple[int, int, int]:
        self._log_rule_eval(MonitorType.NO_SIGNALS_AFTER_RELEASE, "signal_engine")
        release_repo = ReleaseRepository(session)
        market_repo = MarketRepository(session)
        signal_repo = SignalRepository(session)
        snapshot_repo = SnapshotRepository(session)
        due_before = now_utc - timedelta(seconds=self.settings.monitoring_no_signal_grace_seconds)
        releases = await release_repo.list_due_for_actual(due_before_utc=due_before, limit=300)
        opened_or_updated = 0
        resolved = 0
        alerts = 0
        for release in releases:
            dedupe_key = f"{MonitorType.NO_SIGNALS_AFTER_RELEASE.value}:{release.release_id}"
            count_signals = await signal_repo.count_for_release_between(
                release.release_id,
                release.scheduled_time_utc,
                release.scheduled_time_utc + timedelta(seconds=self.settings.monitoring_no_signal_grace_seconds),
            )
            if count_signals > 0:
                resolved += await self._resolve_event_with_log(
                    repo=monitor_repo,
                    dedupe_key=dedupe_key,
                    now_utc=now_utc,
                )
                continue
            markets = await market_repo.list_for_release_type(release.release_type)
            tickers = [m.market_ticker for m in markets]
            snapshots = await snapshot_repo.count_for_markets_between(
                tickers,
                release.scheduled_time_utc - timedelta(minutes=60),
                release.scheduled_time_utc + timedelta(seconds=self.settings.monitoring_no_signal_grace_seconds),
            )
            actual = await release_repo.get_actual(release.release_id)
            result = await self._open_or_update_event(
                repo=monitor_repo,
                now_utc=now_utc,
                monitor_type=MonitorType.NO_SIGNALS_AFTER_RELEASE,
                component="signal_engine",
                severity=MonitorSeverity.WARNING,
                dedupe_key=dedupe_key,
                title=f"No signals after {release.release_type} release",
                message="No signals were generated after grace window elapsed.",
                release_id=release.release_id,
                details_json={
                    "snapshot_count": snapshots,
                    "market_count": len(tickers),
                    "actual_available": _actual_available_for_release(release.release_type, actual),
                },
            )
            opened_or_updated += 1
            alerts += int(result["alerted"])
        return (opened_or_updated, resolved, alerts)

    async def _rule_signal_burst(
        self,
        session: AsyncSession,
        monitor_repo: MonitorEventRepository,
        now_utc: datetime,
    ) -> tuple[int, int, int]:
        self._log_rule_eval(MonitorType.SIGNAL_BURST, "signal_engine")
        release_repo = ReleaseRepository(session)
        signal_repo = SignalRepository(session)
        releases = await release_repo.list_between(now_utc - timedelta(hours=24), now_utc + timedelta(minutes=10))
        opened_or_updated = 0
        resolved = 0
        alerts = 0
        for release in releases:
            window_end = release.scheduled_time_utc + timedelta(minutes=10)
            release_count = await signal_repo.count_for_release_between(
                release.release_id,
                release.scheduled_time_utc,
                window_end,
            )
            release_dedupe = f"{MonitorType.SIGNAL_BURST.value}:{release.release_id}"
            if release_count >= self.settings.monitoring_signal_burst_threshold:
                severity = (
                    MonitorSeverity.CRITICAL
                    if release_count >= max(self.settings.monitoring_signal_burst_threshold, 50)
                    else MonitorSeverity.WARNING
                )
                result = await self._open_or_update_event(
                    repo=monitor_repo,
                    now_utc=now_utc,
                    monitor_type=MonitorType.SIGNAL_BURST,
                    component="signal_engine",
                    severity=severity,
                    dedupe_key=release_dedupe,
                    title=f"Signal burst detected for {release.release_id}",
                    message=f"{release_count} signals detected within 10 minutes of release.",
                    release_id=release.release_id,
                    details_json={"release_signal_count_10m": release_count},
                )
                opened_or_updated += 1
                alerts += int(result["alerted"])
            else:
                resolved += await self._resolve_event_with_log(
                    repo=monitor_repo,
                    dedupe_key=release_dedupe,
                    now_utc=now_utc,
                )

            signals = await signal_repo.list_for_release(release.release_id)
            market_counts: dict[str, int] = {}
            for item in signals:
                if item.emitted_at_utc < release.scheduled_time_utc or item.emitted_at_utc > window_end:
                    continue
                if item.severity not in {"high", "critical"}:
                    continue
                market_counts[item.market_ticker] = market_counts.get(item.market_ticker, 0) + 1
            for market_ticker, count in market_counts.items():
                market_dedupe = f"{MonitorType.SIGNAL_BURST.value}:{release.release_id}:{market_ticker}"
                if count >= self.settings.monitoring_signal_burst_market_threshold:
                    severity = (
                        MonitorSeverity.CRITICAL
                        if count >= max(self.settings.monitoring_signal_burst_market_threshold, 10)
                        else MonitorSeverity.WARNING
                    )
                    result = await self._open_or_update_event(
                        repo=monitor_repo,
                        now_utc=now_utc,
                        monitor_type=MonitorType.SIGNAL_BURST,
                        component="signal_engine",
                        severity=severity,
                        dedupe_key=market_dedupe,
                        title=f"Signal burst detected for {market_ticker}",
                        message=f"{count} high/critical signals detected for market within 10 minutes.",
                        release_id=release.release_id,
                        market_ticker=market_ticker,
                        details_json={"market_signal_count_10m": count},
                    )
                    opened_or_updated += 1
                    alerts += int(result["alerted"])
                else:
                    resolved += await self._resolve_event_with_log(
                        repo=monitor_repo,
                        dedupe_key=market_dedupe,
                        now_utc=now_utc,
                    )
            open_like_events = await monitor_repo.list_open_like(limit=500)
            prefix = f"{MonitorType.SIGNAL_BURST.value}:{release.release_id}:"
            for event in open_like_events:
                if event.monitor_type != MonitorType.SIGNAL_BURST.value:
                    continue
                if not event.dedupe_key.startswith(prefix):
                    continue
                market_ticker = event.dedupe_key.replace(prefix, "", 1)
                if market_counts.get(market_ticker, 0) >= self.settings.monitoring_signal_burst_market_threshold:
                    continue
                resolved += await self._resolve_event_with_log(
                    repo=monitor_repo,
                    dedupe_key=event.dedupe_key,
                    now_utc=now_utc,
                )
        return (opened_or_updated, resolved, alerts)

    async def _rule_notification_failure_burst(
        self,
        session: AsyncSession,
        monitor_repo: MonitorEventRepository,
        now_utc: datetime,
    ) -> tuple[int, int, int]:
        self._log_rule_eval(MonitorType.NOTIFICATION_FAILURE_BURST, "notification_service")
        repo = NotificationRepository(session)
        recent_failed = await repo.count_failed_since(now_utc - timedelta(minutes=10))
        dedupe_key = MonitorType.NOTIFICATION_FAILURE_BURST.value
        if recent_failed >= self.settings.monitoring_notification_failure_burst_threshold:
            result = await self._open_or_update_event(
                repo=monitor_repo,
                now_utc=now_utc,
                monitor_type=MonitorType.NOTIFICATION_FAILURE_BURST,
                component="notification_service",
                severity=MonitorSeverity.CRITICAL,
                dedupe_key=dedupe_key,
                title="Notification failure burst",
                message=f"{recent_failed} failed notifications in last 10 minutes.",
                details_json={"failed_notification_count_10m": recent_failed},
            )
            return (1, 0, int(result["alerted"]))
        resolved_count = await self._resolve_event_with_log(
            repo=monitor_repo,
            dedupe_key=dedupe_key,
            now_utc=now_utc,
        )
        return (0, resolved_count, 0)

    async def _open_or_update_event(
        self,
        *,
        repo: MonitorEventRepository,
        now_utc: datetime,
        monitor_type: MonitorType,
        component: str,
        severity: MonitorSeverity,
        dedupe_key: str,
        title: str,
        message: str,
        details_json: dict[str, Any],
        release_id: str | None = None,
        market_ticker: str | None = None,
    ) -> dict[str, Any]:
        existing = await repo.get_by_dedupe_key(dedupe_key)
        event = await repo.upsert_open_event(
            monitor_type=monitor_type.value,
            component=component,
            severity=severity.value,
            dedupe_key=dedupe_key,
            title=title,
            message=message,
            release_id=release_id,
            market_ticker=market_ticker,
            details_json=details_json,
            now_utc=now_utc,
        )
        LOGGER.info(
            "monitor_event_opened" if existing is None else "monitor_event_updated",
            extra={
                "monitor_type": monitor_type.value,
                "severity": severity.value,
                "component": component,
                "dedupe_key": dedupe_key,
                "release_id": release_id,
                "market_ticker": market_ticker,
            },
        )
        alerted = False
        if severity == MonitorSeverity.CRITICAL:
            alerted = await self._maybe_send_critical_alert(repo=repo, event=event, now_utc=now_utc)
        return {"event": event, "alerted": alerted}

    async def _maybe_send_critical_alert(
        self,
        *,
        repo: MonitorEventRepository,
        event: MonitorEventModel,
        now_utc: datetime,
    ) -> bool:
        if event.severity != MonitorSeverity.CRITICAL.value:
            return False
        if event.alert_sent_at_utc is not None:
            elapsed = (now_utc - event.alert_sent_at_utc).total_seconds()
            if elapsed < self.settings.monitoring_alert_cooldown_critical_seconds:
                LOGGER.info(
                    "monitor_alert_skipped_cooldown",
                    extra={"dedupe_key": event.dedupe_key, "monitor_type": event.monitor_type},
                )
                return False
        chat_id = (self.settings.monitoring_telegram_chat_id or self.settings.telegram_chat_id).strip() or None
        text = self._format_monitor_alert(event)
        sent = await self.telegram_client.send_message(text, chat_id=chat_id)
        if sent:
            await repo.mark_alert_sent(event.dedupe_key, now_utc)
            LOGGER.info(
                "monitor_alert_sent",
                extra={"dedupe_key": event.dedupe_key, "monitor_type": event.monitor_type, "severity": event.severity},
            )
        return sent

    async def _send_fallback_alert(self, *, title: str, message: str, monitor_type: str, component: str) -> None:
        now_utc = utc_now()
        if self._last_fallback_alert_sent_at is not None:
            elapsed = (now_utc - self._last_fallback_alert_sent_at).total_seconds()
            if elapsed < self.settings.monitoring_alert_cooldown_critical_seconds:
                LOGGER.info(
                    "monitor_alert_skipped_cooldown",
                    extra={"monitor_type": monitor_type, "component": component, "dedupe_key": "fallback"},
                )
                return
        chat_id = (self.settings.monitoring_telegram_chat_id or self.settings.telegram_chat_id).strip() or None
        if chat_id is None:
            return
        first_seen = to_display_timezone(now_utc, self.settings.display_timezone).strftime("%Y-%m-%d %H:%M:%S %Z")
        payload = (
            f"[CRITICAL][{monitor_type}][{component}] {title} | {message} | "
            f"first_seen_at_jst={first_seen} | occurrence_count=1"
        )
        sent = await self.telegram_client.send_message(payload, chat_id=chat_id)
        if sent:
            self._last_fallback_alert_sent_at = now_utc

    async def _calendar_retry_with_logging(self, session: AsyncSession) -> None:
        LOGGER.info("monitor_self_heal_started", extra={"monitor_type": MonitorType.UPCOMING_RELEASES_EMPTY.value})
        try:
            await self.calendar_ingestor.ingest(session)
            LOGGER.info("monitor_self_heal_completed", extra={"monitor_type": MonitorType.UPCOMING_RELEASES_EMPTY.value})
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning(
                "monitor_self_heal_failed",
                extra={"monitor_type": MonitorType.UPCOMING_RELEASES_EMPTY.value, "error": str(exc)},
            )

    async def _actual_retry_with_logging(self, session: AsyncSession, release_id: str) -> None:
        LOGGER.info(
            "monitor_self_heal_started",
            extra={"monitor_type": MonitorType.ACTUAL_MISSING_AFTER_RELEASE.value, "release_id": release_id},
        )
        try:
            await self.live_runner.ingest_actual_if_missing(session, release_id)
            LOGGER.info(
                "monitor_self_heal_completed",
                extra={"monitor_type": MonitorType.ACTUAL_MISSING_AFTER_RELEASE.value, "release_id": release_id},
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning(
                "monitor_self_heal_failed",
                extra={
                    "monitor_type": MonitorType.ACTUAL_MISSING_AFTER_RELEASE.value,
                    "release_id": release_id,
                    "error": str(exc),
                },
            )

    async def _market_discovery_retry_with_logging(self, session: AsyncSession) -> None:
        LOGGER.info("monitor_self_heal_started", extra={"monitor_type": MonitorType.MARKET_DISCOVERY_EMPTY.value})
        try:
            await self.market_discovery.discover_and_store(session)
            LOGGER.info("monitor_self_heal_completed", extra={"monitor_type": MonitorType.MARKET_DISCOVERY_EMPTY.value})
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning(
                "monitor_self_heal_failed",
                extra={"monitor_type": MonitorType.MARKET_DISCOVERY_EMPTY.value, "error": str(exc)},
            )

    def _log_rule_eval(self, monitor_type: MonitorType, component: str) -> None:
        LOGGER.info(
            "monitor_rule_evaluated",
            extra={"monitor_type": monitor_type.value, "component": component},
        )

    async def _resolve_event_with_log(
        self,
        *,
        repo: MonitorEventRepository,
        dedupe_key: str,
        now_utc: datetime,
        details_json: dict[str, Any] | None = None,
    ) -> int:
        event = await repo.resolve_event(
            dedupe_key=dedupe_key,
            now_utc=now_utc,
            details_json=details_json,
        )
        if event is None:
            return 0
        LOGGER.info(
            "monitor_event_resolved",
            extra={
                "monitor_type": event.monitor_type,
                "severity": event.severity,
                "component": event.component,
                "dedupe_key": event.dedupe_key,
                "release_id": event.release_id,
                "market_ticker": event.market_ticker,
            },
        )
        return 1

    def _format_monitor_alert(self, event: MonitorEventModel) -> str:
        first_seen = to_display_timezone(event.first_seen_at_utc, self.settings.display_timezone).strftime(
            "%Y-%m-%d %H:%M:%S %Z"
        )
        last_seen = to_display_timezone(event.last_seen_at_utc, self.settings.display_timezone).strftime(
            "%Y-%m-%d %H:%M:%S %Z"
        )
        pieces = [
            f"[{event.severity.upper()}][{event.monitor_type}][{event.component}] {event.title}",
            event.message,
        ]
        if event.release_id:
            pieces.append(f"release_id={event.release_id}")
        if event.market_ticker:
            pieces.append(f"market_ticker={event.market_ticker}")
        pieces.append(f"first_seen_at_jst={first_seen}")
        pieces.append(f"last_seen_at_jst={last_seen}")
        pieces.append(f"occurrence_count={event.occurrence_count}")
        return " | ".join(pieces)

    @staticmethod
    def _has_retry_within(
        event: MonitorEventModel | None,
        key: str,
        *,
        cooldown_seconds: int,
        now_utc: datetime,
    ) -> bool:
        if event is None or not isinstance(event.details_json, dict):
            return False
        raw = event.details_json.get(key)
        if not isinstance(raw, str):
            return False
        try:
            retry_at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return False
        return (now_utc - retry_at).total_seconds() < cooldown_seconds

    @staticmethod
    def _details_value(event: MonitorEventModel | None, key: str) -> str | None:
        if event is None or not isinstance(event.details_json, dict):
            return None
        raw = event.details_json.get(key)
        return raw if isinstance(raw, str) else None


def _parse_error_present(actual: ReleaseActualModel | None) -> bool:
    if actual is None:
        return False
    payload = actual.parsed_payload_json
    return isinstance(payload, dict) and isinstance(payload.get("error"), str) and payload.get("error") != ""


def _actual_available_for_release(release_type: str, actual: ReleaseActualModel | None) -> bool:
    if actual is None:
        return False
    if actual.actual_value_num is not None:
        return True
    if release_type == "FOMC" and isinstance(actual.actual_value_raw, str) and actual.actual_value_raw.strip() != "":
        return True
    return False


def _looks_like_dependency_unavailable(exc: Exception) -> bool:
    lowered = str(exc).lower()
    return any(
        token in lowered
        for token in (
            "connection refused",
            "could not connect",
            "network connection was refused",
            "timed out",
            "connection is closed",
        )
    )
