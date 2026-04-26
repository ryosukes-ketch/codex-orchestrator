from __future__ import annotations

import argparse
import asyncio
import re
from contextlib import asynccontextmanager

try:
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
except AttributeError:
    pass
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable

import httpx
import uvicorn
from fastapi import FastAPI

from app.adapters.bea_client import BEAClient
from app.adapters.bls_client import BLSClient
from app.adapters.fed_client import FedClient
from app.adapters.kalshi_client import KalshiClient
from app.adapters.telegram_client import TelegramClient
from app.api.routes_health import router as health_router
from app.api.routes_jobs import router as jobs_router
from app.api.routes_monitoring import router as monitoring_router
from app.api.routes_releases import router as releases_router
from app.api.routes_signals import router as signals_router
from app.config import Settings, get_settings
from app.db.session import get_session_factory
from app.logging import configure_logging
from app.services.actual_parser import ActualParserService
from app.services.backfill_service import BackfillService
from app.services.calendar_ingestor import CalendarIngestor
from app.services.evaluation_service import EvaluationService
from app.services.live_runner import LiveRunner
from app.services.manual_actual_seed_service import ManualActualSeedService
from app.services.manual_market_seed_service import ManualMarketSeedService
from app.services.manual_release_seed_service import ManualReleaseSeedService
from app.services.manual_snapshot_seed_service import ManualSnapshotSeedService
from app.services.market_discovery import MarketDiscoveryService
from app.services.market_poller import MarketPollerService
from app.services.monitoring_service import MonitoringService
from app.services.notification_service import NotificationService
from app.services.replay_service import ReplayService
from app.services.scoring_engine import ScoringEngine
from app.services.signal_engine import SignalEngine
from app.utils.time import parse_iso_utc

LOGGER = logging.getLogger(__name__)


@dataclass
class RuntimeContainer:
    settings: Settings
    session_factory: object
    live_runner: LiveRunner
    replay_service: ReplayService
    backfill_service: BackfillService
    kalshi_client: KalshiClient
    bls_client: BLSClient
    bea_client: BEAClient
    fed_client: FedClient
    telegram_client: TelegramClient
    monitoring_service: MonitoringService

    async def close(self) -> None:
        await _safe_async_close(self.kalshi_client.close, "kalshi_client")
        await _safe_async_close(self.bls_client.close, "bls_client")
        await _safe_async_close(self.bea_client.close, "bea_client")
        await _safe_async_close(self.fed_client.close, "fed_client")
        await _safe_async_close(self.telegram_client.close, "telegram_client")


async def _safe_async_close(close_fn: Callable[[], Awaitable[None]], resource_name: str) -> None:
    try:
        await close_fn()
    except RuntimeError as exc:
        if "event loop is closed" in str(exc).lower():
            LOGGER.warning("runtime_close_resource_loop_closed", extra={"resource": resource_name, "error": str(exc)})
            return
        LOGGER.warning("runtime_close_resource_runtime_error", extra={"resource": resource_name, "error": str(exc)})
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("runtime_close_resource_failed", extra={"resource": resource_name, "error": str(exc)})


def create_runtime(settings: Settings | None = None) -> RuntimeContainer:
    cfg = settings or get_settings()
    session_factory = get_session_factory(cfg)
    kalshi_client = KalshiClient(cfg)
    bls_client = BLSClient(cfg)
    bea_client = BEAClient(cfg)
    fed_client = FedClient(cfg)
    telegram_client = TelegramClient(cfg)

    actual_parser = ActualParserService()
    signal_engine = SignalEngine(actual_parser=actual_parser)
    scoring_engine = ScoringEngine()
    notification_service = NotificationService(
        telegram_client=telegram_client,
        display_timezone=cfg.display_timezone,
    )
    evaluation_service = EvaluationService()
    replay_service = ReplayService(
        signal_engine=signal_engine,
        scoring_engine=scoring_engine,
        evaluation_service=evaluation_service,
        notification_service=notification_service,
    )
    backfill_service = BackfillService(replay_service=replay_service)
    live_runner = LiveRunner(
        settings=cfg,
        session_factory=session_factory,
        calendar_ingestor=CalendarIngestor(bls_client=bls_client, bea_client=bea_client, fed_client=fed_client),
        market_discovery=MarketDiscoveryService(kalshi_client=kalshi_client),
        market_poller=MarketPollerService(kalshi_client=kalshi_client),
        replay_service=replay_service,
        backfill_service=backfill_service,
        actual_parser=actual_parser,
        bls_client=bls_client,
        bea_client=bea_client,
        fed_client=fed_client,
    )
    monitoring_service = MonitoringService(
        settings=cfg,
        session_factory=session_factory,
        telegram_client=telegram_client,
        calendar_ingestor=live_runner.calendar_ingestor,
        market_discovery=live_runner.market_discovery,
        live_runner=live_runner,
    )
    return RuntimeContainer(
        settings=cfg,
        session_factory=session_factory,
        live_runner=live_runner,
        replay_service=replay_service,
        backfill_service=backfill_service,
        kalshi_client=kalshi_client,
        bls_client=bls_client,
        bea_client=bea_client,
        fed_client=fed_client,
        telegram_client=telegram_client,
        monitoring_service=monitoring_service,
    )


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    runtime = create_runtime(settings)

    @asynccontextmanager
    async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        await _close_runtime_safely(runtime)

    app = FastAPI(title="Macro Release Scanner v1.0", version="1.0.0", lifespan=_lifespan)
    app.state.runtime = runtime
    app.include_router(health_router)
    app.include_router(releases_router)
    app.include_router(signals_router)
    app.include_router(jobs_router)
    app.include_router(monitoring_router)

    return app


app = create_app()


async def run_live_mode(
    runtime: RuntimeContainer,
    once: bool = False,
    *,
    skip_remote_schedules_override: bool = False,
) -> None:
    effective_skip = runtime.settings.skip_remote_schedule_ingestion or skip_remote_schedules_override
    if once:
        await runtime.live_runner.run_once(skip_remote_schedule_ingestion=effective_skip)
        return
    await runtime.live_runner.run_forever(skip_remote_schedule_ingestion=effective_skip)


async def run_backfill_mode(runtime: RuntimeContainer, from_value: str, to_value: str) -> None:
    from_utc = parse_iso_utc(from_value)
    to_utc = parse_iso_utc(to_value)
    async with runtime.session_factory() as session:
        await runtime.backfill_service.run(session, from_utc, to_utc, send_notifications=False)


async def run_replay_mode(runtime: RuntimeContainer, release_id: str) -> None:
    async with runtime.session_factory() as session:
        await runtime.replay_service.replay_release(session, release_id, send_notifications=False)


async def run_monitor_mode(runtime: RuntimeContainer, once: bool) -> None:
    if once:
        result = await runtime.monitoring_service.run_once()
        if result.get("status") == "error":
            raise RuntimeError("monitor mode failed: dependencies unavailable (database or external upstream).")
        return
    await runtime.monitoring_service.run_loop()


async def run_seed_releases_mode(runtime: RuntimeContainer, file_path: str) -> None:
    service = ManualReleaseSeedService()
    async with runtime.session_factory() as session:
        summary = await service.seed_from_file(session, Path(file_path))
    print(f"seed_releases: inserted={summary.inserted} updated={summary.updated}")


async def run_seed_actuals_mode(runtime: RuntimeContainer, file_path: str) -> None:
    service = ManualActualSeedService()
    async with runtime.session_factory() as session:
        summary = await service.seed_from_file(session, Path(file_path))
    print(f"seed_actuals: inserted={summary.inserted} updated={summary.updated}")


async def run_seed_markets_mode(runtime: RuntimeContainer, file_path: str) -> None:
    service = ManualMarketSeedService()
    async with runtime.session_factory() as session:
        summary = await service.seed_from_file(session, Path(file_path))
    print(f"seed_markets: inserted={summary.inserted} updated={summary.updated}")


async def run_seed_snapshots_mode(runtime: RuntimeContainer, file_path: str) -> None:
    service = ManualSnapshotSeedService()
    async with runtime.session_factory() as session:
        summary = await service.seed_from_file(session, Path(file_path))
    print(f"seed_snapshots: inserted={summary.inserted} updated={summary.updated} skipped={summary.skipped}")


async def _close_runtime_safely(runtime: RuntimeContainer) -> None:
    try:
        await runtime.close()
    except RuntimeError as exc:
        if "event loop is closed" in str(exc).lower():
            LOGGER.warning("runtime_close_skipped_loop_closed", extra={"error": str(exc)})
            return
        LOGGER.warning("runtime_close_runtime_error", extra={"error": str(exc)})
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("runtime_close_failed", extra={"error": str(exc)})


async def _run_command_with_cleanup(runtime: RuntimeContainer, args: argparse.Namespace) -> None:
    try:
        if args.command == "live":
            await run_live_mode(
                runtime,
                once=args.once,
                skip_remote_schedules_override=bool(getattr(args, "skip_remote_schedules", False)),
            )
        elif args.command == "backfill":
            await run_backfill_mode(runtime, args.from_utc, args.to_utc)
        elif args.command == "replay":
            await run_replay_mode(runtime, args.release_id)
        elif args.command == "monitor":
            await run_monitor_mode(runtime, once=args.once)
        elif args.command == "seed-releases":
            await run_seed_releases_mode(runtime, args.file)
        elif args.command == "seed-actuals":
            await run_seed_actuals_mode(runtime, args.file)
        elif args.command == "seed-markets":
            await run_seed_markets_mode(runtime, args.file)
        elif args.command == "seed-snapshots":
            await run_seed_snapshots_mode(runtime, args.file)
    finally:
        await _close_runtime_safely(runtime)


def _redact_sensitive_url(url: str) -> str:
    return re.sub(r"(https://api\.telegram\.org/bot)[^/]+(/sendMessage)", r"\1<redacted>\2", url)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="macro-release-scanner")
    sub = parser.add_subparsers(dest="command", required=True)

    live = sub.add_parser("live", help="Run live scanner loop.")
    live.add_argument("--once", action="store_true", help="Run one live cycle and exit.")
    live.add_argument(
        "--skip-remote-schedules",
        action="store_true",
        help="Skip remote schedule ingestion and use existing seeded release_calendar rows.",
    )

    backfill = sub.add_parser("backfill", help="Run backfill replay in range.")
    backfill.add_argument("--from", dest="from_utc", required=True)
    backfill.add_argument("--to", dest="to_utc", required=True)

    replay = sub.add_parser("replay", help="Run replay for a release.")
    replay.add_argument("--release-id", required=True)

    monitor = sub.add_parser("monitor", help="Run monitoring checks.")
    mode = monitor.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--loop", action="store_true")

    api = sub.add_parser("api", help="Run API server.")
    api.add_argument("--host", default="0.0.0.0")
    api.add_argument("--port", type=int, default=8000)

    seed = sub.add_parser("seed-releases", help="Seed release_calendar rows from a manual file.")
    seed.add_argument("--file", required=True, help="Path to YAML file with manual release entries.")

    seed_actuals = sub.add_parser("seed-actuals", help="Seed release_actuals rows from a manual file.")
    seed_actuals.add_argument("--file", required=True, help="Path to YAML file with manual actual entries.")

    seed_markets = sub.add_parser("seed-markets", help="Seed market_catalog rows from a manual file.")
    seed_markets.add_argument("--file", required=True, help="Path to YAML file with manual market entries.")

    seed_snapshots = sub.add_parser("seed-snapshots", help="Seed market_snapshots rows from a manual file.")
    seed_snapshots.add_argument("--file", required=True, help="Path to YAML file with manual snapshot entries.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "api":
        settings = get_settings()
        configure_logging(settings.log_level)
        uvicorn.run("app.macro_pulser.main:app", host=args.host, port=args.port, reload=False)
        return

    runtime = create_runtime(get_settings())
    configure_logging(runtime.settings.log_level)
    try:
        asyncio.run(_run_command_with_cleanup(runtime, args))
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, httpx.HTTPStatusError):
            raw_url = str(exc.request.url)
            safe_url = _redact_sensitive_url(raw_url)
            safe_error = str(exc).replace(raw_url, safe_url)
            LOGGER.error(
                "command_failed_upstream_http",
                extra={
                    "command": args.command,
                    "status_code": exc.response.status_code,
                    "url": safe_url,
                    "error": safe_error,
                },
            )
        else:
            LOGGER.error("command_failed", extra={"command": args.command, "error": str(exc)})
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
