from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import ReleaseRepository
from app.domain.enums import ReleaseType
from app.utils.time import parse_iso_utc

_NUMERIC_RELEASE_TYPES = {ReleaseType.CPI.value, ReleaseType.NFP.value, ReleaseType.GDP_ADVANCE.value}


@dataclass(frozen=True)
class ManualActualSeedSummary:
    inserted: int
    updated: int


class ManualActualSeedService:
    async def seed_from_file(self, session: AsyncSession, file_path: Path) -> ManualActualSeedSummary:
        payload = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
        entries = payload if isinstance(payload, list) else payload.get("actuals", [])
        if not isinstance(entries, list):
            raise ValueError("manual actual seed file must contain a list or a top-level 'actuals' list.")

        repo = ReleaseRepository(session)
        inserted = 0
        updated = 0
        for index, item in enumerate(entries):
            if not isinstance(item, dict):
                raise ValueError(f"actual entry at index {index} must be an object.")
            parsed = _parse_actual_entry(item, index=index)
            release = await _resolve_release(repo, parsed=parsed, index=index)
            existing_actual = await repo.get_actual(release.release_id)

            released_at_utc = parsed["released_at_utc"] or release.scheduled_time_utc
            actual_value_text = parsed["actual_value_text"]
            actual_value_num = parsed["actual_value_num"]
            actual_value_raw = actual_value_text if actual_value_text is not None else str(actual_value_num)

            payload_json = {
                "manual_seed": True,
                "release_type": parsed["release_type"],
                "release_name": release.release_name,
                "source_url": parsed["source_url"],
                "released_at_utc": released_at_utc.isoformat(),
                "status": parsed["status"],
            }
            if actual_value_text is not None:
                payload_json["actual_value_text"] = actual_value_text

            await repo.upsert_actual(
                release_id=release.release_id,
                actual_value_raw=actual_value_raw,
                actual_value_num=actual_value_num,
                parsed_payload_json=payload_json,
                parsed_at_utc=released_at_utc,
            )

            if existing_actual is None:
                inserted += 1
            else:
                updated += 1

        await session.commit()
        return ManualActualSeedSummary(inserted=inserted, updated=updated)


def _parse_actual_entry(item: dict[str, object], *, index: int) -> dict[str, Any]:
    release_type_raw = str(item.get("release_type", "")).strip()
    if not release_type_raw:
        raise ValueError(f"actual entry at index {index} is missing release_type.")
    try:
        release_type = ReleaseType(release_type_raw).value
    except ValueError as exc:
        raise ValueError(f"actual entry at index {index} has unsupported release_type: {release_type_raw}") from exc

    release_id = str(item.get("release_id", "")).strip() or None
    release_name = str(item.get("release_name", "")).strip() or None
    scheduled_raw = str(item.get("scheduled_time_utc", "")).strip() or None
    scheduled_time_utc = None
    if scheduled_raw is not None:
        try:
            scheduled_time_utc = parse_iso_utc(scheduled_raw)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"actual entry at index {index} has invalid scheduled_time_utc: {scheduled_raw}") from exc

    if release_id is None:
        if not release_name:
            raise ValueError(f"actual entry at index {index} must include release_name when release_id is absent.")
        if scheduled_time_utc is None:
            raise ValueError(f"actual entry at index {index} must include scheduled_time_utc when release_id is absent.")

    actual_value_num = _parse_optional_float(item.get("actual_value_num"), index=index)
    actual_value_text = str(item.get("actual_value_text", "")).strip() or None
    if actual_value_num is None and actual_value_text is None:
        raise ValueError(f"actual entry at index {index} must include actual_value_num or actual_value_text.")
    if release_type in _NUMERIC_RELEASE_TYPES and actual_value_num is None:
        raise ValueError(f"actual entry at index {index} requires actual_value_num for release_type {release_type}.")

    source_url = str(item.get("source_url", "")).strip() or "manual://actual/seeded-actual"
    released_at_raw = str(item.get("released_at_utc", "")).strip() or None
    released_at_utc = None
    if released_at_raw is not None:
        try:
            released_at_utc = parse_iso_utc(released_at_raw)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"actual entry at index {index} has invalid released_at_utc: {released_at_raw}") from exc
    status = str(item.get("status", "")).strip() or "released"

    return {
        "release_type": release_type,
        "release_id": release_id,
        "release_name": release_name,
        "scheduled_time_utc": scheduled_time_utc,
        "actual_value_num": actual_value_num,
        "actual_value_text": actual_value_text,
        "source_url": source_url,
        "released_at_utc": released_at_utc,
        "status": status,
    }


def _parse_optional_float(value: object, *, index: int) -> float | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"actual entry at index {index} has invalid actual_value_num: {value}") from exc


async def _resolve_release(repo: ReleaseRepository, *, parsed: dict[str, Any], index: int):
    release_id = parsed["release_id"]
    release = None
    if release_id is not None:
        release = await repo.get_by_id(release_id)
        if release is None:
            raise ValueError(f"actual entry at index {index} references unknown release_id: {release_id}")
    else:
        release = await repo.find_by_identity(
            release_type=parsed["release_type"],
            release_name=parsed["release_name"],
            scheduled_time_utc=parsed["scheduled_time_utc"],
        )
        if release is None:
            raise ValueError(
                "actual entry at index "
                f"{index} could not be matched to release_calendar by release_type + scheduled_time_utc + release_name."
            )
    if release.release_type != parsed["release_type"]:
        raise ValueError(
            f"actual entry at index {index} release_type mismatch: entry={parsed['release_type']} db={release.release_type}"
        )
    return release
