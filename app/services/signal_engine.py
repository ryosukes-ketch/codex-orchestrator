from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.domain.enums import SignalType
from app.domain.signal_models import SignalDraft
from app.domain.types import ContractThreshold
from app.services.actual_parser import ActualParserService
from app.utils.math import abs_change, median_or_none


class SignalEngine:
    def __init__(self, actual_parser: ActualParserService | None = None) -> None:
        self.actual_parser = actual_parser or ActualParserService()

    def detect_signals(
        self,
        *,
        release_id: str,
        release_time_utc: datetime,
        market_ticker: str,
        snapshots: list[Any],
        group_snapshots: dict[str, list[Any]],
        threshold: ContractThreshold | None,
        actual_value_num: float | None,
        interpreted_direction_override: str | None = None,
    ) -> list[SignalDraft]:
        out: list[SignalDraft] = []
        out.extend(
            self._detect_pre_release(
                release_id=release_id,
                release_time_utc=release_time_utc,
                market_ticker=market_ticker,
                snapshots=snapshots,
            )
        )
        out.extend(
            self._detect_release_shock(
                release_id=release_id,
                release_time_utc=release_time_utc,
                market_ticker=market_ticker,
                snapshots=snapshots,
            )
        )
        delayed = self._detect_delayed_repricing(
            release_id=release_id,
            release_time_utc=release_time_utc,
            market_ticker=market_ticker,
            snapshots=snapshots,
            group_snapshots=group_snapshots,
            threshold=threshold,
            actual_value_num=actual_value_num,
            interpreted_direction_override=interpreted_direction_override,
        )
        if delayed:
            out.append(delayed)
        return out

    def _detect_pre_release(
        self,
        *,
        release_id: str,
        release_time_utc: datetime,
        market_ticker: str,
        snapshots: list[Any],
    ) -> list[SignalDraft]:
        start = release_time_utc - timedelta(minutes=60)
        end = release_time_utc - timedelta(minutes=1)
        points = _windowed_valid_snapshots(snapshots, start, end)
        if len(points) < 2:
            return []
        first = points[0]
        last = points[-1]
        near_10m = _first_at_or_after(points, release_time_utc - timedelta(minutes=10)) or first
        change_60 = abs_change(last.mid, first.mid)
        change_10 = abs_change(last.mid, near_10m.mid)
        if change_60 + 1e-9 >= 0.08 and change_10 + 1e-9 >= 0.04:
            return [
                SignalDraft(
                    release_id=release_id,
                    market_ticker=market_ticker,
                    signal_type=SignalType.PRE_RELEASE_PRESSURE,
                    emitted_at_utc=last.captured_at_utc,
                    reason_codes=["pre_release_60m_move", "pre_release_10m_move"],
                    metrics={
                        "change_60m": change_60,
                        "change_10m": change_10,
                        "spread": last.spread,
                        "current_mid": last.mid,
                    },
                )
            ]
        return []

    def _detect_release_shock(
        self,
        *,
        release_id: str,
        release_time_utc: datetime,
        market_ticker: str,
        snapshots: list[Any],
    ) -> list[SignalDraft]:
        end = release_time_utc + timedelta(seconds=120)
        points = _windowed_valid_snapshots(snapshots, release_time_utc, end)
        if len(points) < 2:
            return []
        p0 = points[0]
        p30 = _last_before_or_equal(points, release_time_utc + timedelta(seconds=30)) or p0
        p120 = points[-1]
        change_30 = abs_change(p30.mid, p0.mid)
        change_120 = abs_change(p120.mid, p0.mid)
        volume_change = (p120.volume or 0.0) - (p0.volume or 0.0)
        confirmed = volume_change > 0 or change_30 >= 0.08
        if confirmed and (change_30 >= 0.06 or change_120 >= 0.10):
            return [
                SignalDraft(
                    release_id=release_id,
                    market_ticker=market_ticker,
                    signal_type=SignalType.RELEASE_SHOCK,
                    emitted_at_utc=p120.captured_at_utc,
                    reason_codes=["release_shock_price_move", "release_shock_confirmation"],
                    metrics={
                        "change_30s": change_30,
                        "change_120s": change_120,
                        "volume_delta": volume_change,
                        "spread": p120.spread,
                        "current_mid": p120.mid,
                    },
                )
            ]
        return []

    def _detect_delayed_repricing(
        self,
        *,
        release_id: str,
        release_time_utc: datetime,
        market_ticker: str,
        snapshots: list[Any],
        group_snapshots: dict[str, list[Any]],
        threshold: ContractThreshold | None,
        actual_value_num: float | None,
        interpreted_direction_override: str | None,
    ) -> SignalDraft | None:
        interpreted_direction = interpreted_direction_override or self.actual_parser.interpret_contract_direction(
            actual_value_num, threshold
        )
        if interpreted_direction is None:
            return None
        end = release_time_utc + timedelta(seconds=600)
        target_points = _windowed_valid_snapshots(snapshots, release_time_utc, end)
        if len(target_points) < 2:
            return None

        lag_start: datetime | None = None
        max_gap = 0.0
        max_lag_duration = 0.0
        latest_point = target_points[-1]
        for point in target_points:
            peers = []
            for ticker, series in group_snapshots.items():
                if ticker == market_ticker:
                    continue
                peer_point = _last_before_or_equal(series, point.captured_at_utc)
                if peer_point and peer_point.mid is not None:
                    peers.append(peer_point.mid)
            group_median = median_or_none(peers)
            if group_median is None or point.mid is None:
                continue
            gap = abs(point.mid - group_median)
            max_gap = max(max_gap, gap)
            lagging = (interpreted_direction == "YES" and point.mid < group_median) or (
                interpreted_direction == "NO" and point.mid > group_median
            )
            if lagging and gap >= 0.07:
                if lag_start is None:
                    lag_start = point.captured_at_utc
                lag_duration = (point.captured_at_utc - lag_start).total_seconds()
                max_lag_duration = max(max_lag_duration, lag_duration)
            else:
                lag_start = None

        if max_gap >= 0.07 and max_lag_duration >= 45:
            return SignalDraft(
                release_id=release_id,
                market_ticker=market_ticker,
                signal_type=SignalType.DELAYED_REPRICING,
                emitted_at_utc=latest_point.captured_at_utc,
                reason_codes=["delayed_repricing_gap", "delayed_repricing_lag_duration"],
                metrics={
                    "gap_to_group_median": max_gap,
                    "lag_duration_seconds": max_lag_duration,
                    "interpreted_direction": interpreted_direction,
                    "actual_value_num": actual_value_num,
                    "spread": latest_point.spread,
                    "current_mid": latest_point.mid,
                },
            )
        return None


def _windowed_valid_snapshots(snapshots: list[Any], start: datetime, end: datetime) -> list[Any]:
    points = [
        s
        for s in snapshots
        if start <= s.captured_at_utc <= end and s.mid is not None and s.spread is not None and s.spread <= 0.20
    ]
    points.sort(key=lambda item: item.captured_at_utc)
    return points


def _last_before_or_equal(snapshots: list[Any], cutoff: datetime) -> Any | None:
    selected = [s for s in snapshots if s.captured_at_utc <= cutoff]
    if not selected:
        return None
    return max(selected, key=lambda item: item.captured_at_utc)


def _first_at_or_after(snapshots: list[Any], start: datetime) -> Any | None:
    selected = [s for s in snapshots if s.captured_at_utc >= start]
    if not selected:
        return None
    return min(selected, key=lambda item: item.captured_at_utc)
