from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import NotificationModel, SignalModel
from app.db.repositories import EvaluationRepository, MarketRepository, ReleaseRepository, SignalRepository, SnapshotRepository
from app.domain.enums import Severity, SignalType
from app.utils.math import abs_change, median_or_none
from app.utils.time import utc_now


class EvaluationService:
    async def evaluate_release(self, session: AsyncSession, release_id: str) -> dict[str, float]:
        release_repo = ReleaseRepository(session)
        signal_repo = SignalRepository(session)
        snapshot_repo = SnapshotRepository(session)
        market_repo = MarketRepository(session)
        eval_repo = EvaluationRepository(session)

        release = await release_repo.get_by_id(release_id)
        if release is None:
            return {}
        signals = await signal_repo.list_for_release(release_id)
        markets = await market_repo.list_for_release_type(release.release_type)
        market_tickers = [m.market_ticker for m in markets]

        evaluated = 0
        successes = 0
        critical_evaluated = 0
        critical_success = 0
        first_signal_delay: float | None = None

        for signal in signals:
            if first_signal_delay is None:
                first_signal_delay = (signal.emitted_at_utc - release.scheduled_time_utc).total_seconds()
            outcome = await self._evaluate_signal(
                session=session,
                signal=signal,
                snapshot_repo=snapshot_repo,
                market_tickers=market_tickers,
            )
            if outcome is None:
                continue
            evaluated += 1
            if outcome["success"]:
                successes += 1
            if signal.severity == Severity.CRITICAL.value:
                critical_evaluated += 1
                if outcome["success"]:
                    critical_success += 1
            await eval_repo.upsert_result(
                signal_id=signal.signal_id,
                horizon_sec=outcome["horizon_sec"],
                move_after_horizon=outcome["move_after_horizon"],
                success_bool=outcome["success"],
                evaluated_at_utc=utc_now(),
            )
        await session.commit()
        success_rate = successes / evaluated if evaluated else 0.0
        critical_rate = critical_success / critical_evaluated if critical_evaluated else 0.0
        high_or_above = [s for s in signals if s.severity in {Severity.HIGH.value, Severity.CRITICAL.value}]
        high_success = [
            s for s in high_or_above if await self._already_success(session, s.signal_id)
        ]
        high_success_rate = len(high_success) / len(high_or_above) if high_or_above else 0.0
        avg_notification_delay = await self._average_notification_delay_seconds(session, release_id)
        return {
            "success_rate_high_or_above": high_success_rate,
            "signal_count_per_event": float(len(signals)),
            "critical_signal_success_rate": critical_rate,
            "false_positive_rate_proxy": 1.0 - success_rate if evaluated else 0.0,
            "average_notification_delay": avg_notification_delay,
            "seconds_from_release_time_to_first_signal": float(first_signal_delay or 0.0),
        }

    async def _evaluate_signal(
        self,
        *,
        session: AsyncSession,
        signal: SignalModel,
        snapshot_repo: SnapshotRepository,
        market_tickers: list[str],
    ) -> dict[str, float | bool | int] | None:
        start = signal.emitted_at_utc
        if signal.signal_type == SignalType.RELEASE_SHOCK.value:
            horizon = 120
            end = start + timedelta(seconds=horizon)
            points = await snapshot_repo.list_snapshots(signal.market_ticker, start, end)
            if len(points) < 2:
                return None
            move = abs_change(points[0].mid, points[-1].mid)
            return {"horizon_sec": horizon, "move_after_horizon": move, "success": move >= 0.05}

        if signal.signal_type == SignalType.PRE_RELEASE_PRESSURE.value:
            horizon = 600
            end = start + timedelta(seconds=horizon)
            points = await snapshot_repo.list_snapshots(signal.market_ticker, start, end)
            if len(points) < 2:
                return None
            move = abs_change(points[0].mid, points[-1].mid)
            return {"horizon_sec": horizon, "move_after_horizon": move, "success": move >= 0.04}

        if signal.signal_type == SignalType.DELAYED_REPRICING.value:
            horizon = 600
            end = start + timedelta(seconds=horizon)
            target_points = await snapshot_repo.list_snapshots(signal.market_ticker, start, end)
            if len(target_points) < 2:
                return None
            start_mid = target_points[0].mid
            end_mid = target_points[-1].mid
            if start_mid is None or end_mid is None:
                return None
            peer_start: list[float | None] = []
            peer_end: list[float | None] = []
            for ticker in market_tickers:
                if ticker == signal.market_ticker:
                    continue
                peer_start_snap = await snapshot_repo.latest_snapshot_before(ticker, start)
                peer_end_snap = await snapshot_repo.latest_snapshot_before(ticker, end)
                peer_start.append(peer_start_snap.mid if peer_start_snap else None)
                peer_end.append(peer_end_snap.mid if peer_end_snap else None)
            start_median = median_or_none(peer_start)
            end_median = median_or_none(peer_end)
            if start_median is None or end_median is None:
                return None
            start_gap = abs(start_mid - start_median)
            end_gap = abs(end_mid - end_median)
            shrunk = end_gap <= start_gap * 0.5
            return {"horizon_sec": horizon, "move_after_horizon": start_gap - end_gap, "success": shrunk}
        return None

    async def _already_success(self, session: AsyncSession, signal_id: str) -> bool:
        from app.db.models import EvaluationResultModel

        stmt = (
            select(EvaluationResultModel.success_bool)
            .where(EvaluationResultModel.signal_id == signal_id)
            .order_by(EvaluationResultModel.evaluated_at_utc.desc())
            .limit(1)
        )
        row = await session.execute(stmt)
        value = row.scalar_one_or_none()
        return bool(value)

    async def _average_notification_delay_seconds(self, session: AsyncSession, release_id: str) -> float:
        stmt = (
            select(func.avg(func.extract("epoch", NotificationModel.sent_at_utc - SignalModel.emitted_at_utc)))
            .select_from(NotificationModel)
            .join(SignalModel, NotificationModel.signal_id == SignalModel.signal_id)
            .where(SignalModel.release_id == release_id)
        )
        row = await session.execute(stmt)
        value = row.scalar_one_or_none()
        return float(value or 0.0)
