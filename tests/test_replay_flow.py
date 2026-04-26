from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from app.services.actual_parser import ActualParserService
from app.services.replay_service import ReplayService
from app.services.scoring_engine import ScoringEngine
from app.services.signal_engine import SignalEngine


@dataclass
class _Release:
    release_id: str
    release_type: str
    release_name: str
    scheduled_time_utc: datetime


@dataclass
class _Actual:
    release_id: str
    actual_value_num: float | None
    actual_value_raw: str = ""
    parsed_payload_json: dict | None = None


@dataclass
class _Market:
    market_ticker: str
    mapping_payload_json: dict


@dataclass
class _Snap:
    captured_at_utc: datetime
    mid: float | None
    spread: float | None
    volume: float | None


class _FakeSession:
    async def commit(self):
        return None


@pytest.mark.asyncio
async def test_replay_flow_deterministic(monkeypatch) -> None:
    base = datetime(2026, 4, 10, 12, 30, tzinfo=timezone.utc)
    release = _Release("CPI-2026-04-10", "CPI", "CPI", base)
    actual = _Actual("CPI-2026-04-10", 3.3, actual_value_raw="3.3", parsed_payload_json={})
    markets = [
        _Market("CPI-PEER-1", {"threshold": {"comparator": "above", "value": 3.1, "unit": "%"}}),
        _Market("CPI-PEER-2", {"threshold": {"comparator": "above", "value": 3.1, "unit": "%"}}),
        _Market("CPI-TARGET", {"threshold": {"comparator": "above", "value": 3.1, "unit": "%"}}),
    ]
    snapshots = {
        "CPI-TARGET": [
            _Snap(base + timedelta(seconds=0), 0.40, 0.02, 100),
            _Snap(base + timedelta(seconds=30), 0.41, 0.02, 101),
            _Snap(base + timedelta(seconds=60), 0.42, 0.02, 102),
            _Snap(base + timedelta(seconds=80), 0.43, 0.02, 103),
        ],
        "CPI-PEER-1": [
            _Snap(base + timedelta(seconds=0), 0.56, 0.02, 100),
            _Snap(base + timedelta(seconds=80), 0.57, 0.02, 103),
        ],
        "CPI-PEER-2": [
            _Snap(base + timedelta(seconds=0), 0.55, 0.02, 100),
            _Snap(base + timedelta(seconds=80), 0.58, 0.02, 103),
        ],
    }
    saved: list[dict] = []
    snapshot_call_order: list[str] = []

    class _ReleaseRepo:
        def __init__(self, session):
            self.session = session

        async def get_by_id(self, release_id: str):
            return release

        async def get_actual(self, release_id: str):
            return actual

    class _MarketRepo:
        def __init__(self, session):
            self.session = session

        async def list_for_release_type(self, release_type: str):
            return markets

    class _SnapshotRepo:
        def __init__(self, session):
            self.session = session

        async def list_snapshots(self, market_ticker: str, start, end):
            snapshot_call_order.append(market_ticker)
            return snapshots.get(market_ticker, [])

    class _SignalRepo:
        def __init__(self, session):
            self.session = session

        async def upsert_signal(self, **kwargs):
            saved.append(kwargs)

        async def get_by_id(self, signal_id: str):
            return None

    class _EvalService:
        async def evaluate_release(self, session, release_id: str):
            return {"ok": 1}

    monkeypatch.setattr("app.services.replay_service.ReleaseRepository", _ReleaseRepo)
    monkeypatch.setattr("app.services.replay_service.MarketRepository", _MarketRepo)
    monkeypatch.setattr("app.services.replay_service.SnapshotRepository", _SnapshotRepo)
    monkeypatch.setattr("app.services.replay_service.SignalRepository", _SignalRepo)

    replay = ReplayService(
        signal_engine=SignalEngine(actual_parser=ActualParserService()),
        scoring_engine=ScoringEngine(),
        evaluation_service=_EvalService(),
    )
    result = await replay.replay_release(_FakeSession(), "CPI-2026-04-10")
    assert result["signals_saved"] >= 1
    assert saved
    assert saved[0]["release_id"] == "CPI-2026-04-10"
    assert snapshot_call_order[:3] == sorted(snapshot_call_order[:3])


@pytest.mark.asyncio
async def test_replay_flow_manual_seeded_cpi_market_uses_manual_release_link_and_threshold(monkeypatch) -> None:
    base = datetime(2026, 4, 19, 12, 30, tzinfo=timezone.utc)
    release = _Release("REL-CPI-1", "CPI", "CPI Dev Seed Near Term", base)
    actual = _Actual("REL-CPI-1", 3.3, actual_value_raw="3.3", parsed_payload_json={"actual_value_text": "3.3"})
    markets = [
        _Market(
            "CPI-MANUAL-TARGET",
            {
                "manual_seed": True,
                "release_id": "REL-CPI-1",
                "threshold": {"comparator": "above", "value": 3.1, "unit": "%"},
            },
        ),
        _Market(
            "CPI-MANUAL-OTHER-RELEASE",
            {
                "manual_seed": True,
                "release_id": "REL-CPI-OTHER",
                "threshold": {"comparator": "above", "value": 3.1, "unit": "%"},
            },
        ),
    ]
    snapshots = {
        "CPI-MANUAL-TARGET": [
            _Snap(base - timedelta(minutes=59), 0.40, 0.02, 100),
            _Snap(base - timedelta(minutes=10), 0.45, 0.02, 120),
            _Snap(base - timedelta(minutes=1), 0.49, 0.02, 140),
        ],
        "CPI-MANUAL-OTHER-RELEASE": [
            _Snap(base - timedelta(minutes=59), 0.20, 0.02, 50),
            _Snap(base - timedelta(minutes=1), 0.21, 0.02, 60),
        ],
    }
    saved: list[dict] = []

    class _ReleaseRepo:
        def __init__(self, session):
            self.session = session

        async def get_by_id(self, release_id: str):
            return release

        async def get_actual(self, release_id: str):
            return actual

    class _MarketRepo:
        def __init__(self, session):
            self.session = session

        async def list_for_release_type(self, release_type: str):
            return markets

    class _SnapshotRepo:
        def __init__(self, session):
            self.session = session

        async def list_snapshots(self, market_ticker: str, start, end):
            _ = start, end
            return snapshots.get(market_ticker, [])

    class _SignalRepo:
        def __init__(self, session):
            self.session = session

        async def upsert_signal(self, **kwargs):
            saved.append(kwargs)

        async def get_by_id(self, signal_id: str):
            return None

    class _EvalService:
        async def evaluate_release(self, session, release_id: str):
            return {"ok": 1}

    monkeypatch.setattr("app.services.replay_service.ReleaseRepository", _ReleaseRepo)
    monkeypatch.setattr("app.services.replay_service.MarketRepository", _MarketRepo)
    monkeypatch.setattr("app.services.replay_service.SnapshotRepository", _SnapshotRepo)
    monkeypatch.setattr("app.services.replay_service.SignalRepository", _SignalRepo)

    replay = ReplayService(
        signal_engine=SignalEngine(actual_parser=ActualParserService()),
        scoring_engine=ScoringEngine(),
        evaluation_service=_EvalService(),
    )
    result = await replay.replay_release(_FakeSession(), "REL-CPI-1")
    assert result["signals_saved"] >= 1
    assert saved
    assert all(item["market_ticker"] == "CPI-MANUAL-TARGET" for item in saved)


@pytest.mark.asyncio
async def test_replay_flow_manual_seeded_fomc_text_contract_interpretation(monkeypatch) -> None:
    base = datetime(2026, 6, 17, 18, 0, tzinfo=timezone.utc)
    release = _Release("REL-FOMC-1", "FOMC", "FOMC June 2026", base)
    actual = _Actual(
        "REL-FOMC-1",
        None,
        actual_value_raw="HOLD; target upper bound 4.50",
        parsed_payload_json={"actual_value_text": "HOLD; target upper bound 4.50"},
    )
    markets = [
        _Market(
            "FOMC-MANUAL-TARGET",
            {
                "manual_seed": True,
                "release_id": "REL-FOMC-1",
                "contract_interpretation": "FOMC decision hold",
            },
        ),
        _Market("FOMC-MANUAL-PEER-A", {"manual_seed": True, "release_id": "REL-FOMC-1"}),
        _Market("FOMC-MANUAL-PEER-B", {"manual_seed": True, "release_id": "REL-FOMC-1"}),
    ]
    snapshots = {
        "FOMC-MANUAL-TARGET": [
            _Snap(base + timedelta(seconds=0), 0.40, 0.02, 100),
            _Snap(base + timedelta(seconds=30), 0.41, 0.02, 101),
            _Snap(base + timedelta(seconds=60), 0.42, 0.02, 102),
            _Snap(base + timedelta(seconds=80), 0.43, 0.02, 103),
        ],
        "FOMC-MANUAL-PEER-A": [
            _Snap(base + timedelta(seconds=0), 0.56, 0.02, 100),
            _Snap(base + timedelta(seconds=80), 0.57, 0.02, 103),
        ],
        "FOMC-MANUAL-PEER-B": [
            _Snap(base + timedelta(seconds=0), 0.55, 0.02, 100),
            _Snap(base + timedelta(seconds=80), 0.58, 0.02, 103),
        ],
    }
    saved: list[dict] = []

    class _ReleaseRepo:
        def __init__(self, session):
            self.session = session

        async def get_by_id(self, release_id: str):
            return release

        async def get_actual(self, release_id: str):
            return actual

    class _MarketRepo:
        def __init__(self, session):
            self.session = session

        async def list_for_release_type(self, release_type: str):
            return markets

    class _SnapshotRepo:
        def __init__(self, session):
            self.session = session

        async def list_snapshots(self, market_ticker: str, start, end):
            _ = start, end
            return snapshots.get(market_ticker, [])

    class _SignalRepo:
        def __init__(self, session):
            self.session = session

        async def upsert_signal(self, **kwargs):
            saved.append(kwargs)

        async def get_by_id(self, signal_id: str):
            return None

    class _EvalService:
        async def evaluate_release(self, session, release_id: str):
            return {"ok": 1}

    monkeypatch.setattr("app.services.replay_service.ReleaseRepository", _ReleaseRepo)
    monkeypatch.setattr("app.services.replay_service.MarketRepository", _MarketRepo)
    monkeypatch.setattr("app.services.replay_service.SnapshotRepository", _SnapshotRepo)
    monkeypatch.setattr("app.services.replay_service.SignalRepository", _SignalRepo)

    replay = ReplayService(
        signal_engine=SignalEngine(actual_parser=ActualParserService()),
        scoring_engine=ScoringEngine(),
        evaluation_service=_EvalService(),
    )
    result = await replay.replay_release(_FakeSession(), "REL-FOMC-1")
    assert result["signals_saved"] >= 1
    assert any(item["signal_type"] == "DELAYED_REPRICING" for item in saved)


@pytest.mark.asyncio
async def test_replay_flow_malformed_manual_metadata_does_not_crash(monkeypatch) -> None:
    base = datetime(2026, 4, 19, 12, 30, tzinfo=timezone.utc)
    release = _Release("REL-CPI-1", "CPI", "CPI Dev Seed Near Term", base)
    actual = _Actual("REL-CPI-1", 3.3, actual_value_raw="3.3", parsed_payload_json={"actual_value_text": "3.3"})
    markets = [
        _Market(
            "CPI-MALFORMED",
            {
                "manual_seed": True,
                "release_id": "REL-CPI-1",
                "threshold": "bad-threshold-shape",
            },
        ),
    ]
    snapshots = {
        "CPI-MALFORMED": [
            _Snap(base - timedelta(minutes=59), 0.40, 0.02, 100),
            _Snap(base - timedelta(minutes=10), 0.45, 0.02, 120),
            _Snap(base - timedelta(minutes=1), 0.49, 0.02, 140),
        ],
    }

    class _ReleaseRepo:
        def __init__(self, session):
            self.session = session

        async def get_by_id(self, release_id: str):
            return release

        async def get_actual(self, release_id: str):
            return actual

    class _MarketRepo:
        def __init__(self, session):
            self.session = session

        async def list_for_release_type(self, release_type: str):
            return markets

    class _SnapshotRepo:
        def __init__(self, session):
            self.session = session

        async def list_snapshots(self, market_ticker: str, start, end):
            _ = start, end
            return snapshots.get(market_ticker, [])

    class _SignalRepo:
        def __init__(self, session):
            self.session = session

        async def upsert_signal(self, **kwargs):
            return None

        async def get_by_id(self, signal_id: str):
            return None

    class _EvalService:
        async def evaluate_release(self, session, release_id: str):
            return {"ok": 1}

    monkeypatch.setattr("app.services.replay_service.ReleaseRepository", _ReleaseRepo)
    monkeypatch.setattr("app.services.replay_service.MarketRepository", _MarketRepo)
    monkeypatch.setattr("app.services.replay_service.SnapshotRepository", _SnapshotRepo)
    monkeypatch.setattr("app.services.replay_service.SignalRepository", _SignalRepo)

    replay = ReplayService(
        signal_engine=SignalEngine(actual_parser=ActualParserService()),
        scoring_engine=ScoringEngine(),
        evaluation_service=_EvalService(),
    )
    result = await replay.replay_release(_FakeSession(), "REL-CPI-1")
    assert result["signals_saved"] >= 1
