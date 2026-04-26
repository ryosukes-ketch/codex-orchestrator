from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import MarketRepository, ReleaseRepository
from app.domain.enums import ReleaseType
from app.utils.time import parse_iso_utc


@dataclass(frozen=True)
class ManualMarketSeedSummary:
    inserted: int
    updated: int


class ManualMarketSeedService:
    async def seed_from_file(self, session: AsyncSession, file_path: Path) -> ManualMarketSeedSummary:
        payload = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
        entries = payload if isinstance(payload, list) else payload.get("markets", [])
        if not isinstance(entries, list):
            raise ValueError("manual market seed file must contain a list or a top-level 'markets' list.")

        market_repo = MarketRepository(session)
        release_repo = ReleaseRepository(session)
        inserted = 0
        updated = 0
        for index, item in enumerate(entries):
            if not isinstance(item, dict):
                raise ValueError(f"market entry at index {index} must be an object.")
            parsed = _parse_market_entry(item, index=index)
            release = await _resolve_release(release_repo, parsed=parsed, index=index)

            release_type = parsed["release_type"]
            if release is not None:
                if release_type is not None and release_type != release.release_type:
                    raise ValueError(
                        f"market entry at index {index} release_type mismatch: entry={release_type} db={release.release_type}"
                    )
                release_type = release.release_type
            if release_type is None:
                raise ValueError(
                    f"market entry at index {index} must include release_type or a release reference for association."
                )

            mapping_payload_json = dict(parsed["mapping_payload_json"])
            mapping_payload_json.setdefault("manual_seed", True)
            if parsed["source_url"]:
                mapping_payload_json.setdefault("source", parsed["source_url"])
            if release is not None:
                mapping_payload_json["release_id"] = release.release_id
                mapping_payload_json.setdefault("release_name", release.release_name)
                mapping_payload_json.setdefault("scheduled_time_utc", release.scheduled_time_utc.isoformat())

            existing = await market_repo.get_by_ticker(parsed["market_ticker"])
            await market_repo.upsert_market(
                market_ticker=parsed["market_ticker"],
                platform=parsed["platform"],
                title=parsed["title"],
                subtitle=parsed["subtitle"],
                close_time_utc=parsed["close_time_utc"],
                status=parsed["status"],
                release_type=release_type,
                mapping_confidence=parsed["mapping_confidence"],
                mapping_payload_json=mapping_payload_json,
            )
            if existing is None:
                inserted += 1
            else:
                updated += 1

        await session.commit()
        return ManualMarketSeedSummary(inserted=inserted, updated=updated)


def _parse_market_entry(item: dict[str, object], *, index: int) -> dict[str, Any]:
    market_ticker = str(item.get("market_ticker", "")).strip()
    if not market_ticker:
        raise ValueError(f"market entry at index {index} is missing market_ticker.")

    platform = str(item.get("platform", "")).strip().lower() or "kalshi"
    title = str(item.get("title", "")).strip()
    if not title:
        raise ValueError(f"market entry at index {index} is missing title.")
    subtitle = str(item.get("subtitle", "")).strip() or None

    close_time_utc_raw = str(item.get("close_time_utc", "")).strip() or None
    close_time_utc = None
    if close_time_utc_raw is not None:
        try:
            close_time_utc = parse_iso_utc(close_time_utc_raw)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"market entry at index {index} has invalid close_time_utc: {close_time_utc_raw}") from exc

    release_type_raw = str(item.get("release_type", "")).strip() or None
    release_type = None
    if release_type_raw is not None:
        try:
            release_type = ReleaseType(release_type_raw).value
        except ValueError as exc:
            raise ValueError(f"market entry at index {index} has unsupported release_type: {release_type_raw}") from exc

    release_id = str(item.get("release_id", "")).strip() or None
    release_name = str(item.get("release_name", "")).strip() or None
    scheduled_raw = str(item.get("scheduled_time_utc", "")).strip() or None
    scheduled_time_utc = None
    if scheduled_raw is not None:
        try:
            scheduled_time_utc = parse_iso_utc(scheduled_raw)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"market entry at index {index} has invalid scheduled_time_utc: {scheduled_raw}") from exc

    if release_id is None and (release_name is not None or scheduled_time_utc is not None):
        if release_type is None or release_name is None or scheduled_time_utc is None:
            raise ValueError(
                f"market entry at index {index} must include release_type + release_name + "
                "scheduled_time_utc for fallback release matching."
            )

    mapping_confidence_raw = item.get("mapping_confidence", 1.0)
    try:
        mapping_confidence = float(mapping_confidence_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"market entry at index {index} has invalid mapping_confidence: {mapping_confidence_raw}"
        ) from exc

    mapping_payload_json_raw = item.get("mapping_payload_json")
    if mapping_payload_json_raw is None:
        mapping_payload_json: dict[str, Any] = {}
    elif isinstance(mapping_payload_json_raw, dict):
        mapping_payload_json = dict(mapping_payload_json_raw)
    else:
        raise ValueError(f"market entry at index {index} has invalid mapping_payload_json (must be object).")

    status = str(item.get("status", "")).strip().lower() or "active"
    source_url = str(item.get("source_url", "")).strip() or None

    return {
        "market_ticker": market_ticker,
        "platform": platform,
        "title": title,
        "subtitle": subtitle,
        "close_time_utc": close_time_utc,
        "status": status,
        "release_type": release_type,
        "release_id": release_id,
        "release_name": release_name,
        "scheduled_time_utc": scheduled_time_utc,
        "mapping_confidence": mapping_confidence,
        "mapping_payload_json": mapping_payload_json,
        "source_url": source_url,
    }


async def _resolve_release(repo: ReleaseRepository, *, parsed: dict[str, Any], index: int):
    if parsed["release_id"] is not None:
        release = await repo.get_by_id(parsed["release_id"])
        if release is None:
            raise ValueError(f"market entry at index {index} references unknown release_id: {parsed['release_id']}")
        return release

    if parsed["release_type"] is not None and parsed["release_name"] is not None and parsed["scheduled_time_utc"] is not None:
        release = await repo.find_by_identity(
            release_type=parsed["release_type"],
            release_name=parsed["release_name"],
            scheduled_time_utc=parsed["scheduled_time_utc"],
        )
        if release is None:
            raise ValueError(
                "market entry at index "
                f"{index} could not be matched to release_calendar by release_type + scheduled_time_utc + release_name."
            )
        return release

    return None
