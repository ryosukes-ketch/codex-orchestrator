"""Tests for manual-seed market handling in MarketPollerService.

Covers the dev-mode path where synthetic markets have future-dated snapshots
that must be recognised as existing regardless of their timestamp.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest

import app.services.market_poller as _mp_mod
from app.services.market_poller import MarketPollerService

# ---------------------------------------------------------------------------
# Fake collaborators
# ---------------------------------------------------------------------------

_FUTURE_TS = datetime.now(timezone.utc) + timedelta(days=1)
_PAST_TS = datetime.now(timezone.utc) - timedelta(hours=2)


def _manual_seed_market(ticker: str) -> SimpleNamespace:
    return SimpleNamespace(
        market_ticker=ticker,
        mapping_payload_json={"manual_seed": True},
    )


def _real_market(ticker: str) -> SimpleNamespace:
    return SimpleNamespace(
        market_ticker=ticker,
        mapping_payload_json={"manual_seed": False},
    )


class _FakeSnapshotRepo:
    """Controls which tickers have snapshots and at what timestamp."""

    def __init__(self, snapshots: dict[str, datetime | None]) -> None:
        self._snapshots = snapshots
        self.added: list[str] = []

    async def latest_snapshot_anytime(self, market_ticker: str) -> SimpleNamespace | None:
        ts = self._snapshots.get(market_ticker)
        if ts is None:
            return None
        return SimpleNamespace(market_ticker=market_ticker, captured_at_utc=ts)

    async def latest_snapshot_before(self, market_ticker: str, ts_utc: datetime) -> SimpleNamespace | None:
        raise AssertionError("latest_snapshot_before must NOT be called for manual-seed check")

    async def add_snapshot(self, **kwargs: Any) -> None:
        self.added.append(kwargs["market_ticker"])

    async def upsert_snapshot(self, **kwargs: Any) -> None:
        self.added.append(kwargs["market_ticker"])


class _FakeMarketRepo:
    def __init__(self, markets: dict[str, SimpleNamespace | None]) -> None:
        self._markets = markets

    async def get_by_ticker(self, ticker: str) -> SimpleNamespace | None:
        return self._markets.get(ticker)


class _FakeSession:
    async def commit(self) -> None:
        pass


class _FakeKalshiClient:
    """Should never be called during manual-seed path."""

    async def get_orderbook(self, ticker: str) -> dict:
        raise AssertionError(f"Kalshi orderbook must NOT be called for manual-seed market {ticker!r}")

    async def get_market(self, ticker: str) -> dict:
        raise AssertionError(f"Kalshi market detail must NOT be called for manual-seed market {ticker!r}")


# ---------------------------------------------------------------------------
# Patch helper
# ---------------------------------------------------------------------------

def _make_service() -> MarketPollerService:
    return MarketPollerService(kalshi_client=_FakeKalshiClient())  # type: ignore[arg-type]


async def _run_poll(
    service: MarketPollerService,
    tickers: list[str],
    snap_repo: _FakeSnapshotRepo,
    market_repo: _FakeMarketRepo,
    monkeypatch: pytest.MonkeyPatch,
) -> int:
    """Patch SnapshotRepository and MarketRepository at the market_poller import site."""
    monkeypatch.setattr(_mp_mod, "SnapshotRepository", lambda s: snap_repo)
    monkeypatch.setattr(_mp_mod, "MarketRepository", lambda s: market_repo)
    return await service.poll_and_store(_FakeSession(), tickers)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_future_dated_snapshot_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    """A manual-seed market whose only snapshots are future-dated must not raise RuntimeError."""
    ticker = "CPI-DEV-APR19-ABOVE-3.1"
    snap_repo = _FakeSnapshotRepo({ticker: _FUTURE_TS})
    market_repo = _FakeMarketRepo({ticker: _manual_seed_market(ticker)})
    service = _make_service()

    # Must not raise, and must not call Kalshi
    await _run_poll(service, [ticker], snap_repo, market_repo, monkeypatch)

    # No real snapshot was written
    assert ticker not in snap_repo.added


@pytest.mark.asyncio
async def test_past_dated_snapshot_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    """A manual-seed market with a past-dated snapshot also passes the existence check."""
    ticker = "CPI-DEV-APR18-ABOVE-3.1"
    snap_repo = _FakeSnapshotRepo({ticker: _PAST_TS})
    market_repo = _FakeMarketRepo({ticker: _manual_seed_market(ticker)})
    service = _make_service()

    await _run_poll(service, [ticker], snap_repo, market_repo, monkeypatch)
    assert ticker not in snap_repo.added


@pytest.mark.asyncio
async def test_missing_snapshot_raises_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A manual-seed market with no snapshot at all must still raise RuntimeError."""
    ticker = "CPI-DEV-NO-SNAP"
    snap_repo = _FakeSnapshotRepo({ticker: None})
    market_repo = _FakeMarketRepo({ticker: _manual_seed_market(ticker)})
    service = _make_service()

    with pytest.raises(RuntimeError, match="has no local snapshots"):
        await _run_poll(service, [ticker], snap_repo, market_repo, monkeypatch)


@pytest.mark.asyncio
async def test_mixed_manual_and_real_market(monkeypatch: pytest.MonkeyPatch) -> None:
    """When both a manual-seed and a real market are in tickers, only the real one calls Kalshi."""
    manual_ticker = "CPI-DEV-APR18-ABOVE-3.1"
    real_ticker = "CPI-REAL-MKT"

    snap_repo = _FakeSnapshotRepo({manual_ticker: _PAST_TS})
    market_repo = _FakeMarketRepo(
        {
            manual_ticker: _manual_seed_market(manual_ticker),
            real_ticker: _real_market(real_ticker),
        }
    )

    polled: list[str] = []

    class _TrackingKalshi:
        async def get_orderbook(self, ticker: str) -> dict:
            polled.append(ticker)
            return {}

        async def get_market(self, ticker: str) -> dict:
            return {"last_price": 0.5, "volume": 100}

    service = MarketPollerService(kalshi_client=_TrackingKalshi())  # type: ignore[arg-type]
    await _run_poll(service, [manual_ticker, real_ticker], snap_repo, market_repo, monkeypatch)

    # Manual-seed was skipped; real market was polled
    assert manual_ticker not in polled
    assert real_ticker in polled
