from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.domain.enums import MarketStatus, Platform, ReleaseType


class MarketCandidate(BaseModel):
    market_ticker: str
    platform: Platform = Platform.KALSHI
    title: str
    subtitle: str | None = None
    close_time_utc: datetime | None = None
    status: MarketStatus = MarketStatus.UNKNOWN
    release_type: ReleaseType | None = None
    mapping_confidence: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class OrderbookSnapshot(BaseModel):
    market_ticker: str
    captured_at_utc: datetime
    yes_bid: float | None = None
    yes_ask: float | None = None
    mid: float | None = None
    spread: float | None = None
    last_price: float | None = None
    volume: float | None = None
