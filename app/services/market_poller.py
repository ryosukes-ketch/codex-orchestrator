from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.kalshi_client import KalshiClient
from app.db.repositories import MarketRepository, SnapshotRepository
from app.utils.math import compute_spread, normalize_mid
from app.utils.time import ensure_utc, utc_now

LOGGER = logging.getLogger(__name__)


class MarketPollerService:
    def __init__(self, kalshi_client: KalshiClient) -> None:
        self.kalshi_client = kalshi_client

    async def poll_and_store(self, session: AsyncSession, market_tickers: list[str]) -> int:
        repo = SnapshotRepository(session)
        market_repo = MarketRepository(session)
        count = 0
        for ticker in market_tickers:
            market = await market_repo.get_by_ticker(ticker)
            if market is not None and _is_manual_seed_market(getattr(market, "mapping_payload_json", None)):
                latest_snapshot = await repo.latest_snapshot_anytime(ticker)
                if latest_snapshot is None:
                    raise RuntimeError(
                        f"manual seeded market '{ticker}' has no local snapshots; "
                        "seed snapshots first via 'python -m app.main seed-snapshots --file ...'."
                    )
                LOGGER.info("manual_seed_market_remote_poll_skipped", extra={"market_ticker": ticker})
                continue
            snapshot = await self.poll_once(ticker)
            await repo.add_snapshot(
                market_ticker=ticker,
                captured_at_utc=snapshot["captured_at_utc"],
                yes_bid=snapshot["yes_bid"],
                yes_ask=snapshot["yes_ask"],
                mid=snapshot["mid"],
                spread=snapshot["spread"],
                last_price=snapshot["last_price"],
                volume=snapshot["volume"],
            )
            count += 1
        await session.commit()
        return count

    async def poll_once(self, market_ticker: str) -> dict[str, Any]:
        orderbook_payload = await self.kalshi_client.get_orderbook(market_ticker)
        market_payload = await self.kalshi_client.get_market(market_ticker)
        yes_bid, yes_ask = _extract_best_yes_prices(orderbook_payload)
        last_price = _to_float(market_payload.get("last_price"))
        volume = _to_float(market_payload.get("volume"))
        mid = normalize_mid(yes_bid, yes_ask, last_price)
        spread = compute_spread(yes_bid, yes_ask)
        captured_at = ensure_utc(_extract_timestamp(orderbook_payload) or utc_now())
        return {
            "market_ticker": market_ticker,
            "captured_at_utc": captured_at,
            "yes_bid": yes_bid,
            "yes_ask": yes_ask,
            "mid": mid,
            "spread": spread,
            "last_price": last_price,
            "volume": volume,
        }


def _extract_best_yes_prices(payload: dict[str, Any]) -> tuple[float | None, float | None]:
    yes = payload.get("yes")
    if isinstance(yes, dict):
        return _to_float(yes.get("bid")), _to_float(yes.get("ask"))
    if isinstance(yes, list) and yes:
        bids = [_to_float(item[0] if isinstance(item, list) else item.get("price")) for item in yes]
        clean_bids = [v for v in bids if v is not None]
        return (max(clean_bids) if clean_bids else None, min(clean_bids) if clean_bids else None)

    bids_payload = payload.get("bids") or payload.get("yes_bids") or []
    asks_payload = payload.get("asks") or payload.get("yes_asks") or []
    best_bid = _extract_best_side_price(bids_payload, prefer_max=True)
    best_ask = _extract_best_side_price(asks_payload, prefer_max=False)
    return best_bid, best_ask


def _extract_best_side_price(raw: Any, prefer_max: bool) -> float | None:
    prices: list[float] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, list) and item:
                value = _to_float(item[0])
            elif isinstance(item, dict):
                value = _to_float(item.get("price"))
            else:
                value = None
            if value is not None:
                prices.append(value)
    if not prices:
        return None
    return max(prices) if prefer_max else min(prices)


def _extract_timestamp(payload: dict[str, Any]) -> datetime | None:
    raw = payload.get("timestamp") or payload.get("ts")
    if raw in (None, ""):
        return None
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(float(raw), tz=utc_now().tzinfo)
    if isinstance(raw, str):
        try:
            return ensure_utc(datetime.fromisoformat(raw.replace("Z", "+00:00")))
        except ValueError:
            LOGGER.warning("unable_to_parse_timestamp", extra={"raw_value": raw})
            return None
    return None


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _is_manual_seed_market(mapping_payload_json: Any) -> bool:
    if not isinstance(mapping_payload_json, dict):
        return False
    value = mapping_payload_json.get("manual_seed")
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return False
