from __future__ import annotations

from statistics import median


def normalize_mid(
    yes_bid: float | None, yes_ask: float | None, last_price: float | None
) -> float | None:
    if yes_bid is not None and yes_ask is not None:
        return round((yes_bid + yes_ask) / 2, 6)
    if last_price is not None:
        return round(last_price, 6)
    return None


def compute_spread(yes_bid: float | None, yes_ask: float | None) -> float | None:
    if yes_bid is None or yes_ask is None:
        return None
    return round(abs(yes_ask - yes_bid), 6)


def abs_change(a: float | None, b: float | None) -> float:
    if a is None or b is None:
        return 0.0
    return abs(a - b)


def median_or_none(values: list[float | None]) -> float | None:
    cleaned = [v for v in values if v is not None]
    if not cleaned:
        return None
    return float(median(cleaned))


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
