from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.services.market_poller import MarketPollerService


class _FakeSession:
    async def commit(self) -> None:
        return None


@pytest.mark.asyncio
async def test_poll_and_store_skips_remote_fetch_for_manual_seed_market(monkeypatch) -> None:
    calls = {"orderbook": 0, "market": 0}

    class _KalshiClient:
        async def get_orderbook(self, market_ticker: str):
            _ = market_ticker
            calls["orderbook"] += 1
            raise AssertionError("manual seed market should not request orderbook upstream")

        async def get_market(self, market_ticker: str):
            _ = market_ticker
            calls["market"] += 1
            raise AssertionError("manual seed market should not request market upstream")

    class _MarketRepo:
        def __init__(self, session) -> None:
            self.session = session

        async def get_by_ticker(self, market_ticker: str):
            _ = market_ticker
            return SimpleNamespace(mapping_payload_json={"manual_seed": True})

    class _SnapshotRepo:
        added_calls: list[dict[str, object]] = []

        def __init__(self, session) -> None:
            self.session = session

        async def latest_snapshot_anytime(self, market_ticker: str):
            _ = market_ticker
            return SimpleNamespace(
                market_ticker="CPI-DEV-1",
                captured_at_utc=datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc),
            )

        async def add_snapshot(self, **kwargs):
            self.__class__.added_calls.append(kwargs)

    monkeypatch.setattr("app.services.market_poller.MarketRepository", _MarketRepo)
    monkeypatch.setattr("app.services.market_poller.SnapshotRepository", _SnapshotRepo)

    service = MarketPollerService(_KalshiClient())  # type: ignore[arg-type]
    saved = await service.poll_and_store(_FakeSession(), ["CPI-DEV-1"])  # type: ignore[arg-type]

    assert saved == 0
    assert calls["orderbook"] == 0
    assert calls["market"] == 0
    assert _SnapshotRepo.added_calls == []


@pytest.mark.asyncio
async def test_poll_and_store_keeps_upstream_fetch_for_non_manual_markets(monkeypatch) -> None:
    calls = {"orderbook": 0, "market": 0}

    class _KalshiClient:
        async def get_orderbook(self, market_ticker: str):
            calls["orderbook"] += 1
            assert market_ticker == "CPI-REAL-1"
            return {"yes": {"bid": 0.40, "ask": 0.46}, "timestamp": "2026-04-01T12:00:30Z"}

        async def get_market(self, market_ticker: str):
            calls["market"] += 1
            assert market_ticker == "CPI-REAL-1"
            return {"last_price": 0.44, "volume": 123}

    class _MarketRepo:
        def __init__(self, session) -> None:
            self.session = session

        async def get_by_ticker(self, market_ticker: str):
            _ = market_ticker
            return SimpleNamespace(mapping_payload_json={"manual_seed": False})

    class _SnapshotRepo:
        added_calls: list[dict[str, object]] = []

        def __init__(self, session) -> None:
            self.session = session

        async def latest_snapshot_before(self, market_ticker: str, ts_utc: datetime):
            _ = market_ticker, ts_utc
            return None

        async def add_snapshot(self, **kwargs):
            self.__class__.added_calls.append(kwargs)

    monkeypatch.setattr("app.services.market_poller.MarketRepository", _MarketRepo)
    monkeypatch.setattr("app.services.market_poller.SnapshotRepository", _SnapshotRepo)

    service = MarketPollerService(_KalshiClient())  # type: ignore[arg-type]
    saved = await service.poll_and_store(_FakeSession(), ["CPI-REAL-1"])  # type: ignore[arg-type]

    assert saved == 1
    assert calls["orderbook"] == 1
    assert calls["market"] == 1
    assert len(_SnapshotRepo.added_calls) == 1
    saved_row = _SnapshotRepo.added_calls[0]
    assert saved_row["market_ticker"] == "CPI-REAL-1"
    assert saved_row["mid"] == pytest.approx(0.43)
    assert saved_row["spread"] == pytest.approx(0.06)


@pytest.mark.asyncio
async def test_poll_and_store_manual_seed_requires_local_snapshot(monkeypatch) -> None:
    calls = {"orderbook": 0, "market": 0}

    class _KalshiClient:
        async def get_orderbook(self, market_ticker: str):
            _ = market_ticker
            calls["orderbook"] += 1
            raise AssertionError("manual seed market should not request orderbook upstream")

        async def get_market(self, market_ticker: str):
            _ = market_ticker
            calls["market"] += 1
            raise AssertionError("manual seed market should not request market upstream")

    class _MarketRepo:
        def __init__(self, session) -> None:
            self.session = session

        async def get_by_ticker(self, market_ticker: str):
            _ = market_ticker
            return SimpleNamespace(mapping_payload_json={"manual_seed": True})

    class _SnapshotRepo:
        def __init__(self, session) -> None:
            self.session = session

        async def latest_snapshot_anytime(self, market_ticker: str):
            _ = market_ticker
            return None

        async def add_snapshot(self, **kwargs):
            _ = kwargs
            raise AssertionError("manual seed market should not save polled snapshots")

    monkeypatch.setattr("app.services.market_poller.MarketRepository", _MarketRepo)
    monkeypatch.setattr("app.services.market_poller.SnapshotRepository", _SnapshotRepo)

    service = MarketPollerService(_KalshiClient())  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="manual seeded market 'CPI-DEV-MISSING'.*seed-snapshots"):
        await service.poll_and_store(_FakeSession(), ["CPI-DEV-MISSING"])  # type: ignore[arg-type]

    assert calls["orderbook"] == 0
    assert calls["market"] == 0
