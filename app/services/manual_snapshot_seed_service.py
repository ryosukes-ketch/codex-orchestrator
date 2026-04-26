from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import MarketRepository, SnapshotRepository
from app.utils.time import parse_iso_utc


@dataclass(frozen=True)
class ManualSnapshotSeedSummary:
    inserted: int
    updated: int
    skipped: int


class ManualSnapshotSeedService:
    async def seed_from_file(self, session: AsyncSession, file_path: Path) -> ManualSnapshotSeedSummary:
        payload = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
        entries = payload if isinstance(payload, list) else payload.get("snapshots", [])
        if not isinstance(entries, list):
            raise ValueError("manual snapshot seed file must contain a list or a top-level 'snapshots' list.")

        market_repo = MarketRepository(session)
        snapshot_repo = SnapshotRepository(session)
        inserted = 0
        updated = 0
        skipped = 0
        for index, item in enumerate(entries):
            if not isinstance(item, dict):
                raise ValueError(f"snapshot entry at index {index} must be an object.")
            parsed = _parse_snapshot_entry(item, index=index)

            market = await market_repo.get_by_ticker(parsed["market_ticker"])
            if market is None:
                raise ValueError(
                    f"snapshot entry at index {index} references unknown market_ticker: {parsed['market_ticker']}"
                )

            existing = await snapshot_repo.get_by_market_and_time(
                market_ticker=parsed["market_ticker"],
                captured_at_utc=parsed["captured_at_utc"],
            )
            if existing is not None and _same_snapshot_values(existing, parsed):
                skipped += 1
                continue

            await snapshot_repo.upsert_snapshot(
                market_ticker=parsed["market_ticker"],
                captured_at_utc=parsed["captured_at_utc"],
                yes_bid=parsed["yes_bid"],
                yes_ask=parsed["yes_ask"],
                mid=parsed["mid"],
                spread=parsed["spread"],
                last_price=parsed["last_price"],
                volume=parsed["volume"],
            )
            if existing is None:
                inserted += 1
            else:
                updated += 1

        await session.commit()
        return ManualSnapshotSeedSummary(inserted=inserted, updated=updated, skipped=skipped)


def _parse_snapshot_entry(item: dict[str, object], *, index: int) -> dict[str, Any]:
    market_ticker = str(item.get("market_ticker", "")).strip()
    if not market_ticker:
        raise ValueError(f"snapshot entry at index {index} is missing market_ticker.")

    captured_at_raw = str(item.get("captured_at_utc", "")).strip()
    if not captured_at_raw:
        raise ValueError(f"snapshot entry at index {index} is missing captured_at_utc.")
    try:
        captured_at_utc = parse_iso_utc(captured_at_raw)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"snapshot entry at index {index} has invalid captured_at_utc: {captured_at_raw}") from exc

    yes_bid = _parse_optional_float(item.get("yes_bid"), index=index, field_name="yes_bid")
    yes_ask = _parse_optional_float(item.get("yes_ask"), index=index, field_name="yes_ask")
    mid = _parse_optional_float(item.get("mid"), index=index, field_name="mid")
    spread = _parse_optional_float(item.get("spread"), index=index, field_name="spread")
    last_price = _parse_optional_float(item.get("last_price"), index=index, field_name="last_price")
    volume = _parse_optional_float(item.get("volume"), index=index, field_name="volume")
    if volume is None:
        volume = 0.0

    if mid is None and yes_bid is not None and yes_ask is not None:
        mid = (yes_bid + yes_ask) / 2.0
    if spread is None and yes_bid is not None and yes_ask is not None:
        spread = yes_ask - yes_bid

    return {
        "market_ticker": market_ticker,
        "captured_at_utc": captured_at_utc,
        "yes_bid": yes_bid,
        "yes_ask": yes_ask,
        "mid": mid,
        "spread": spread,
        "last_price": last_price,
        "volume": volume,
    }


def _parse_optional_float(value: object, *, index: int, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"snapshot entry at index {index} has invalid {field_name}: {value}") from exc


def _same_snapshot_values(existing: Any, parsed: dict[str, Any]) -> bool:
    return (
        existing.yes_bid == parsed["yes_bid"]
        and existing.yes_ask == parsed["yes_ask"]
        and existing.mid == parsed["mid"]
        and existing.spread == parsed["spread"]
        and existing.last_price == parsed["last_price"]
        and existing.volume == parsed["volume"]
    )
