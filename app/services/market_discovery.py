from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from dateutil import parser as date_parser
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.kalshi_client import KalshiClient
from app.db.repositories import MarketRepository
from app.domain.enums import Platform, ReleaseType
from app.utils.parsing import parse_contract_threshold

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class MappingRule:
    release_type: ReleaseType
    market_match_keywords: list[str]
    market_exclude_keywords: list[str]
    contract_interpretation: str
    direction_if_yes: str
    threshold_parser: str
    priority: int


class MarketDiscoveryService:
    def __init__(
        self,
        kalshi_client: KalshiClient,
        mapping_path: Path | None = None,
    ) -> None:
        self.kalshi_client = kalshi_client
        self.mapping_path = mapping_path or _default_mapping_path()
        self._rules = self._load_mapping_rules()

    def _load_mapping_rules(self) -> list[MappingRule]:
        raw = yaml.safe_load(self.mapping_path.read_text(encoding="utf-8"))
        rules: list[MappingRule] = []
        for item in raw.get("mappings", []):
            rules.append(
                MappingRule(
                    release_type=ReleaseType(item["release_type"]),
                    market_match_keywords=[k.lower() for k in item.get("market_match_keywords", [])],
                    market_exclude_keywords=[k.lower() for k in item.get("market_exclude_keywords", [])],
                    contract_interpretation=item.get("contract_interpretation", ""),
                    direction_if_yes=item.get("direction_if_yes", "UP"),
                    threshold_parser=item.get("threshold_parser", "basic"),
                    priority=int(item.get("priority", 1)),
                )
            )
        return rules

    async def discover_and_store(self, session: AsyncSession) -> int:
        markets = await self.kalshi_client.list_markets(limit=1000)
        repo = MarketRepository(session)
        stored = 0
        for market in markets:
            title = str(market.get("title", "")).strip()
            subtitle = str(market.get("subtitle", "")).strip() or None
            text = f"{title} {subtitle or ''}".lower()
            matched_rule, confidence = self._select_rule(text)
            threshold = parse_contract_threshold(text) if matched_rule else None
            if matched_rule and matched_rule.threshold_parser != "none" and threshold is None:
                confidence -= 0.2
            confidence = max(0.0, min(confidence, 1.0))
            release_type = matched_rule.release_type.value if matched_rule and confidence >= 0.55 else None
            payload = {
                "contract_interpretation": matched_rule.contract_interpretation if matched_rule else "",
                "direction_if_yes": matched_rule.direction_if_yes if matched_rule else "",
                "threshold": (
                    {
                        "comparator": threshold.comparator,
                        "value": threshold.value,
                        "unit": threshold.unit,
                    }
                    if threshold
                    else None
                ),
                "priority": matched_rule.priority if matched_rule else 0,
            }
            await repo.upsert_market(
                market_ticker=str(market.get("ticker") or market.get("market_ticker")),
                platform=Platform.KALSHI.value,
                title=title,
                subtitle=subtitle,
                close_time_utc=_parse_optional_datetime(market.get("close_time")),
                status=str(market.get("status", "unknown")).lower(),
                release_type=release_type,
                mapping_confidence=confidence,
                mapping_payload_json=payload,
            )
            stored += 1
        await session.commit()
        return stored

    def _select_rule(self, normalized_text: str) -> tuple[MappingRule | None, float]:
        best_rule: MappingRule | None = None
        best_confidence = 0.0
        for rule in self._rules:
            if any(excluded in normalized_text for excluded in rule.market_exclude_keywords):
                continue
            keyword_hits = sum(1 for k in rule.market_match_keywords if k in normalized_text)
            if keyword_hits == 0:
                continue
            confidence = min(1.0, 0.35 + (keyword_hits / max(1, len(rule.market_match_keywords))) * 0.5)
            confidence += min(0.15, rule.priority * 0.02)
            if confidence > best_confidence:
                best_confidence = confidence
                best_rule = rule
        return best_rule, best_confidence


def _parse_optional_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return date_parser.parse(str(value))
    except (ValueError, TypeError):
        LOGGER.warning("unable_to_parse_market_close_time", extra={"raw_value": str(value)})
        return None


def _default_mapping_path() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / "config" / "market_mapping.yaml"
