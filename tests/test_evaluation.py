from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import SignalModel
from app.services.evaluation_service import EvaluationService


@dataclass
class _Snap:
    captured_at_utc: datetime
    mid: float | None


class _SnapshotRepo:
    def __init__(self, payload: dict[str, list[_Snap]]) -> None:
        self.payload = payload

    async def list_snapshots(self, market_ticker: str, start: datetime, end: datetime):
        return [s for s in self.payload[market_ticker] if start <= s.captured_at_utc <= end]

    async def latest_snapshot_before(self, market_ticker: str, ts_utc: datetime):
        points = [s for s in self.payload[market_ticker] if s.captured_at_utc <= ts_utc]
        return max(points, key=lambda p: p.captured_at_utc) if points else None


@pytest.mark.asyncio
async def test_release_shock_evaluation_success() -> None:
    base = datetime(2026, 4, 10, 12, 30, tzinfo=timezone.utc)
    service = EvaluationService()
    signal = SignalModel(
        signal_id="s1",
        release_id="r1",
        market_ticker="m1",
        signal_type="RELEASE_SHOCK",
        score=80,
        severity="critical",
        reason_codes_json=[],
        metrics_json={},
        emitted_at_utc=base,
    )
    snapshot_repo = _SnapshotRepo(
        {"m1": [_Snap(base, 0.40), _Snap(base + timedelta(seconds=120), 0.47)]}
    )
    outcome = await service._evaluate_signal(  # noqa: SLF001
        session=None,
        signal=signal,
        snapshot_repo=snapshot_repo,
        market_tickers=["m1"],
    )
    assert outcome is not None
    assert outcome["success"] is True


@pytest.mark.asyncio
async def test_delayed_repricing_evaluation_success() -> None:
    base = datetime(2026, 4, 10, 12, 30, tzinfo=timezone.utc)
    service = EvaluationService()
    signal = SignalModel(
        signal_id="s2",
        release_id="r1",
        market_ticker="m1",
        signal_type="DELAYED_REPRICING",
        score=70,
        severity="high",
        reason_codes_json=[],
        metrics_json={},
        emitted_at_utc=base,
    )
    snapshot_repo = _SnapshotRepo(
        {
            "m1": [_Snap(base, 0.30), _Snap(base + timedelta(seconds=600), 0.48)],
            "m2": [_Snap(base, 0.55), _Snap(base + timedelta(seconds=600), 0.52)],
            "m3": [_Snap(base, 0.56), _Snap(base + timedelta(seconds=600), 0.51)],
        }
    )
    outcome = await service._evaluate_signal(  # noqa: SLF001
        session=None,
        signal=signal,
        snapshot_repo=snapshot_repo,
        market_tickers=["m1", "m2", "m3"],
    )
    assert outcome is not None
    assert outcome["success"] is True


@pytest.mark.asyncio
async def test_pre_release_pressure_evaluation_success() -> None:
    base = datetime(2026, 4, 10, 12, 20, tzinfo=timezone.utc)
    service = EvaluationService()
    signal = SignalModel(
        signal_id="s3",
        release_id="r1",
        market_ticker="m1",
        signal_type="PRE_RELEASE_PRESSURE",
        score=60,
        severity="medium",
        reason_codes_json=[],
        metrics_json={},
        emitted_at_utc=base,
    )
    snapshot_repo = _SnapshotRepo(
        {"m1": [_Snap(base, 0.40), _Snap(base + timedelta(seconds=600), 0.45)]}
    )
    outcome = await service._evaluate_signal(  # noqa: SLF001
        session=None,
        signal=signal,
        snapshot_repo=snapshot_repo,
        market_tickers=["m1"],
    )
    assert outcome is not None
    assert outcome["horizon_sec"] == 600
    assert outcome["success"] is True
