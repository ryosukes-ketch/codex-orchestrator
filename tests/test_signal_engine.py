from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.domain.types import ContractThreshold
from app.services.signal_engine import SignalEngine


@dataclass
class _Snap:
    captured_at_utc: datetime
    mid: float | None
    spread: float | None
    volume: float | None = None


def _base_time() -> datetime:
    return datetime(2026, 4, 10, 12, 30, tzinfo=timezone.utc)


def test_pre_release_pressure_detected() -> None:
    release_time = _base_time()
    snaps = [
        _Snap(release_time - timedelta(minutes=59), 0.40, 0.02, 100),
        _Snap(release_time - timedelta(minutes=10), 0.45, 0.03, 120),
        _Snap(release_time - timedelta(minutes=1), 0.49, 0.02, 150),
    ]
    engine = SignalEngine()
    signals = engine.detect_signals(
        release_id="CPI-2026-04-10",
        release_time_utc=release_time,
        market_ticker="CPI-MKT",
        snapshots=snaps,
        group_snapshots={"CPI-MKT": snaps},
        threshold=None,
        actual_value_num=None,
    )
    assert any(s.signal_type.value == "PRE_RELEASE_PRESSURE" for s in signals)


def test_release_shock_detected() -> None:
    release_time = _base_time()
    snaps = [
        _Snap(release_time, 0.42, 0.02, 100),
        _Snap(release_time + timedelta(seconds=20), 0.50, 0.02, 103),
        _Snap(release_time + timedelta(seconds=90), 0.55, 0.03, 110),
    ]
    engine = SignalEngine()
    signals = engine.detect_signals(
        release_id="CPI-2026-04-10",
        release_time_utc=release_time,
        market_ticker="CPI-MKT",
        snapshots=snaps,
        group_snapshots={"CPI-MKT": snaps},
        threshold=None,
        actual_value_num=None,
    )
    assert any(s.signal_type.value == "RELEASE_SHOCK" for s in signals)


def test_delayed_repricing_detected() -> None:
    release_time = _base_time()
    target = [
        _Snap(release_time + timedelta(seconds=0), 0.40, 0.02, 100),
        _Snap(release_time + timedelta(seconds=30), 0.41, 0.02, 100),
        _Snap(release_time + timedelta(seconds=50), 0.42, 0.02, 100),
        _Snap(release_time + timedelta(seconds=80), 0.43, 0.02, 100),
    ]
    peer_a = [
        _Snap(release_time + timedelta(seconds=0), 0.55, 0.02, 100),
        _Snap(release_time + timedelta(seconds=30), 0.56, 0.02, 100),
        _Snap(release_time + timedelta(seconds=80), 0.58, 0.02, 100),
    ]
    peer_b = [
        _Snap(release_time + timedelta(seconds=0), 0.54, 0.02, 100),
        _Snap(release_time + timedelta(seconds=30), 0.57, 0.02, 100),
        _Snap(release_time + timedelta(seconds=80), 0.59, 0.02, 100),
    ]
    engine = SignalEngine()
    signals = engine.detect_signals(
        release_id="CPI-2026-04-10",
        release_time_utc=release_time,
        market_ticker="CPI-MKT",
        snapshots=target,
        group_snapshots={"CPI-MKT": target, "CPI-PEER-A": peer_a, "CPI-PEER-B": peer_b},
        threshold=ContractThreshold(comparator="above", value=3.1, unit="%"),
        actual_value_num=3.3,
    )
    delayed = [s for s in signals if s.signal_type.value == "DELAYED_REPRICING"]
    assert delayed
    assert delayed[0].metrics["interpreted_direction"] == "YES"
