from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.enums import ReleaseType


@dataclass(frozen=True, slots=True)
class ContractThreshold:
    comparator: str
    value: float
    unit: str | None = None


@dataclass(frozen=True, slots=True)
class MarketMatchResult:
    release_type: ReleaseType
    market_ticker: str
    confidence: float
    interpretation: str
    direction_if_yes: str
    threshold: ContractThreshold | None


@dataclass(frozen=True, slots=True)
class PricePoint:
    ts: datetime
    mid: float | None
    spread: float | None
    volume: float | None
