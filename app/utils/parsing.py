from __future__ import annotations

import re
from typing import Final

from app.domain.types import ContractThreshold

NUMBER_PATTERN: Final[re.Pattern[str]] = re.compile(r"(-?\d+(?:\.\d+)?)\s*(%|k|m)?", re.IGNORECASE)

ABOVE_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\b(?:above|over|greater than|more than|at least|>=?)\b", re.IGNORECASE),
    re.compile(r">\s*"),
)
BELOW_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\b(?:below|under|less than|fewer than|at most|<=?)\b", re.IGNORECASE),
    re.compile(r"<\s*"),
)


def parse_contract_threshold(text: str) -> ContractThreshold | None:
    normalized = text.strip().lower()
    comparator = _extract_comparator(normalized)
    if comparator is None:
        return None

    number_match = NUMBER_PATTERN.search(normalized)
    if not number_match:
        return None

    raw = float(number_match.group(1))
    unit = number_match.group(2)
    value = _scale_number(raw, unit)
    return ContractThreshold(comparator=comparator, value=value, unit=unit)


def _extract_comparator(text: str) -> str | None:
    if any(pattern.search(text) for pattern in ABOVE_PATTERNS):
        return "above"
    if any(pattern.search(text) for pattern in BELOW_PATTERNS):
        return "below"
    return None


def _scale_number(raw: float, unit: str | None) -> float:
    if unit is None:
        return raw
    unit_norm = unit.lower()
    if unit_norm == "k":
        return raw * 1_000
    if unit_norm == "m":
        return raw * 1_000_000
    return raw
