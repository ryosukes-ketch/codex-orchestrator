from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from app.domain.enums import DecisionClassification, ReleaseType
from app.domain.types import ContractThreshold

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ParsedActual:
    actual_value_raw: str
    actual_value_num: float | None
    parsed_payload_json: dict[str, Any]


class ActualParserService:
    """Deterministic parser for official release payloads.

    Notes:
    - Parsing is regex-based and intentionally strict to keep behavior deterministic.
    - Upstream HTML/template changes may require fixture updates.
    """

    CPI_PATTERN = re.compile(
        r"(?:12-month|year-over-year|YoY)[^0-9-]{0,25}(-?\d+(?:\.\d+)?)\s*%",
        re.IGNORECASE | re.DOTALL,
    )
    CPI_FALLBACK_PATTERN = re.compile(
        r"(?:all items|consumer price index)[^.]{0,180}(?:increased|decreased)\s+(-?\d+(?:\.\d+)?)\s*percent",
        re.IGNORECASE,
    )
    NFP_PATTERN = re.compile(
        r"total nonfarm payroll employment\s+(increased|decreased)\s+by\s+([0-9,]+)",
        re.IGNORECASE,
    )
    GDP_PATTERN = re.compile(
        r"real gross domestic product[^.]{0,160}annual rate of\s+(-?\d+(?:\.\d+)?)\s*percent",
        re.IGNORECASE | re.DOTALL,
    )
    FOMC_RANGE_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(?:to|-)\s*(\d+(?:\.\d+)?)\s*percent", re.IGNORECASE)
    FOMC_HIKE_PATTERNS = (
        re.compile(r"decided to raise the target range", re.IGNORECASE),
        re.compile(r"raised the target range", re.IGNORECASE),
        re.compile(r"increased the target range", re.IGNORECASE),
    )
    FOMC_CUT_PATTERNS = (
        re.compile(r"decided to lower the target range", re.IGNORECASE),
        re.compile(r"lowered the target range", re.IGNORECASE),
        re.compile(r"reduced the target range", re.IGNORECASE),
        re.compile(r"cut the target range", re.IGNORECASE),
    )

    def parse(self, release_type: ReleaseType, content: str) -> ParsedActual:
        if release_type == ReleaseType.CPI:
            return self._parse_cpi(content)
        if release_type == ReleaseType.NFP:
            return self._parse_nfp(content)
        if release_type == ReleaseType.GDP_ADVANCE:
            return self._parse_gdp(content)
        if release_type == ReleaseType.FOMC:
            return self._parse_fomc(content)
        raise ValueError(f"Unsupported release type: {release_type.value}")

    def _parse_cpi(self, content: str) -> ParsedActual:
        match = self.CPI_PATTERN.search(content) or self.CPI_FALLBACK_PATTERN.search(content)
        if not match:
            raise ValueError("Failed to parse CPI headline YoY")
        value = float(match.group(1))
        return ParsedActual(
            actual_value_raw=match.group(0),
            actual_value_num=value,
            parsed_payload_json={"headline_cpi_yoy": value},
        )

    def _parse_nfp(self, content: str) -> ParsedActual:
        match = self.NFP_PATTERN.search(content)
        if not match:
            raise ValueError("Failed to parse NFP headline payroll change")
        direction, raw_value = match.groups()
        base = float(raw_value.replace(",", ""))
        value = -base if direction.lower() == "decreased" else base
        return ParsedActual(
            actual_value_raw=match.group(0),
            actual_value_num=value,
            parsed_payload_json={"nonfarm_payroll_change": value},
        )

    def _parse_gdp(self, content: str) -> ParsedActual:
        match = self.GDP_PATTERN.search(content)
        if not match:
            raise ValueError("Failed to parse GDP advance annualized real growth")
        value = float(match.group(1))
        return ParsedActual(
            actual_value_raw=match.group(0),
            actual_value_num=value,
            parsed_payload_json={"annualized_real_gdp_growth_advance": value},
        )

    def _parse_fomc(self, content: str) -> ParsedActual:
        classification = self._classify_fomc_decision(content)
        range_match = self.FOMC_RANGE_PATTERN.search(content)
        upper = float(range_match.group(2)) if range_match else None
        payload = {
            "decision_classification": classification.value,
            "target_upper_bound": upper,
        }
        return ParsedActual(
            actual_value_raw=classification.value,
            actual_value_num=upper,
            parsed_payload_json=payload,
        )

    def _classify_fomc_decision(self, content: str) -> DecisionClassification:
        if any(pattern.search(content) for pattern in self.FOMC_HIKE_PATTERNS):
            return DecisionClassification.HIKE
        if any(pattern.search(content) for pattern in self.FOMC_CUT_PATTERNS):
            return DecisionClassification.CUT
        return DecisionClassification.HOLD

    def interpret_contract_direction(
        self, actual_value_num: float | None, threshold: ContractThreshold | None
    ) -> str | None:
        if actual_value_num is None or threshold is None:
            LOGGER.warning("actual_direction_missing_context")
            return None
        if threshold.comparator == "above":
            return "YES" if actual_value_num > threshold.value else "NO"
        if threshold.comparator == "below":
            return "YES" if actual_value_num < threshold.value else "NO"
        return None
