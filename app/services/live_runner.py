from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.adapters.bea_client import BEAClient
from app.adapters.bls_client import BLSClient
from app.adapters.fed_client import FedClient
from app.config import Settings
from app.db.repositories import MarketRepository, MonitorEventRepository, ReleaseRepository
from app.domain.enums import ReleaseType
from app.services.actual_parser import ActualParserService
from app.services.backfill_service import BackfillService
from app.services.calendar_ingestor import CalendarIngestor
from app.services.market_discovery import MarketDiscoveryService
from app.services.market_poller import MarketPollerService
from app.services.replay_service import ReplayService
from app.utils.release_urls import resolve_release_content_url
from app.utils.time import utc_now

LOGGER = logging.getLogger(__name__)


@dataclass
class LiveRunner:
    settings: Settings
    session_factory: async_sessionmaker
    calendar_ingestor: CalendarIngestor
    market_discovery: MarketDiscoveryService
    market_poller: MarketPollerService
    replay_service: ReplayService
    backfill_service: BackfillService
    actual_parser: ActualParserService
    bls_client: BLSClient
    bea_client: BEAClient
    fed_client: FedClient

    async def run_once(self, *, skip_remote_schedule_ingestion: bool = False) -> dict[str, int]:
        stats = {
            "releases_ingested": 0,
            "markets_discovered": 0,
            "snapshots_polled": 0,
            "signals_saved": 0,
            "signals_notified": 0,
        }
        if not skip_remote_schedule_ingestion:
            async with self.session_factory() as session:
                stats["releases_ingested"] = await self.calendar_ingestor.ingest(session)
        else:
            LOGGER.info("live_schedule_ingestion_skipped")

        if skip_remote_schedule_ingestion:
            async with self.session_factory() as session:
                release_repo = ReleaseRepository(session)
                seeded = await release_repo.list_upcoming(now_utc=utc_now(), limit=1)
                if not seeded:
                    raise RuntimeError(
                        "skip_remote_schedules is enabled but no seeded upcoming releases exist in release_calendar."
                    )

        async with self.session_factory() as session:
            stats["markets_discovered"] = await self.market_discovery.discover_and_store(session)

        now = utc_now()
        window = timedelta(minutes=self.settings.active_release_window_minutes)
        async with self.session_factory() as session:
            release_repo = ReleaseRepository(session)
            market_repo = MarketRepository(session)
            active_releases = await release_repo.list_between(now - window, now + window)
            tickers: set[str] = set()
            for release in active_releases:
                markets = await market_repo.list_for_release_type(release.release_type)
                for market in markets:
                    tickers.add(market.market_ticker)
            if tickers:
                stats["snapshots_polled"] = await self.market_poller.poll_and_store(session, sorted(tickers))

        async with self.session_factory() as session:
            release_repo = ReleaseRepository(session)
            active_releases = await release_repo.list_between(now - window, now + window)
            for release in active_releases:
                await self._ingest_actual_if_missing(session, release.release_id)
                result = await self.replay_service.replay_release(
                    session,
                    release.release_id,
                    send_notifications=True,
                )
                stats["signals_saved"] += result["signals_saved"]
                stats["signals_notified"] += result["signals_notified"]
        await self._record_live_cycle_success()
        return stats

    async def run_forever(self, *, skip_remote_schedule_ingestion: bool | None = None) -> None:
        while True:
            try:
                stats = await self.run_once(
                    skip_remote_schedule_ingestion=(
                        self.settings.skip_remote_schedule_ingestion
                        if skip_remote_schedule_ingestion is None
                        else skip_remote_schedule_ingestion
                    ),
                )
                LOGGER.info("live_cycle_complete", extra=stats)
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("live_cycle_failed", extra={"error": str(exc)})
            await asyncio.sleep(self.settings.poll_interval_seconds)

    async def _ingest_actual_if_missing(self, session, release_id: str) -> None:
        release_repo = ReleaseRepository(session)
        release = await release_repo.get_by_id(release_id)
        if release is None:
            return
        existing = await release_repo.get_actual(release_id)
        if existing is not None:
            return
        if release.scheduled_time_utc > utc_now():
            return
        raw_content: str | None = None
        parse_error: str | None = None
        try:
            source_url = resolve_release_content_url(
                release_type=release.release_type,
                release_id=release.release_id,
                existing_source_url=release.source_url,
            )
            if release.release_type in {ReleaseType.CPI.value, ReleaseType.NFP.value}:
                raw_content = await self.bls_client.fetch_release_page(source_url)
            elif release.release_type == ReleaseType.GDP_ADVANCE.value:
                raw_content = await self.bea_client.fetch_release_page(source_url)
            elif release.release_type == ReleaseType.FOMC.value:
                raw_content = await self.fed_client.fetch_statement_page(source_url)

            if raw_content is None:
                return
            parsed = self.actual_parser.parse(ReleaseType(release.release_type), raw_content)
            await release_repo.upsert_actual(
                release_id=release_id,
                actual_value_raw=parsed.actual_value_raw,
                actual_value_num=parsed.actual_value_num,
                parsed_payload_json=parsed.parsed_payload_json,
                parsed_at_utc=utc_now(),
            )
        except Exception as exc:  # noqa: BLE001
            parse_error = str(exc)
            LOGGER.warning(
                "actual_parse_failed",
                extra={"release_id": release_id, "release_type": release.release_type, "error": parse_error},
            )
            await release_repo.upsert_actual(
                release_id=release_id,
                actual_value_raw="parse_error",
                actual_value_num=None,
                parsed_payload_json={
                    "error": parse_error,
                    "release_type": release.release_type,
                    "raw_excerpt": (raw_content or "")[:800],
                },
                parsed_at_utc=utc_now(),
            )
        await session.commit()

    async def ingest_actual_if_missing(self, session, release_id: str) -> None:
        await self._ingest_actual_if_missing(session, release_id)

    async def _record_live_cycle_success(self) -> None:
        if not self.settings.monitoring_enabled:
            return
        try:
            now = utc_now()
            async with self.session_factory() as session:
                monitor_repo = MonitorEventRepository(session)
                await monitor_repo.record_live_cycle_success(now)
                await session.commit()
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("monitor_live_success_record_failed", extra={"error": str(exc)})
