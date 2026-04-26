from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import ReleaseRepository
from app.domain.enums import ReleaseStatus, ReleaseType
from app.utils.idempotency import stable_hash
from app.utils.time import parse_iso_utc


@dataclass(frozen=True)
class ManualReleaseSeedSummary:
    inserted: int
    updated: int


class ManualReleaseSeedService:
    async def seed_from_file(self, session: AsyncSession, file_path: Path) -> ManualReleaseSeedSummary:
        payload = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
        entries = payload if isinstance(payload, list) else payload.get("releases", [])
        if not isinstance(entries, list):
            raise ValueError("manual release seed file must contain a list or a top-level 'releases' list.")

        repo = ReleaseRepository(session)
        inserted = 0
        updated = 0
        for index, item in enumerate(entries):
            if not isinstance(item, dict):
                raise ValueError(f"release entry at index {index} must be an object.")
            parsed = _parse_seed_entry(item, index=index)
            existing = await repo.get_by_id(parsed["release_id"])
            await repo.upsert_release(
                release_id=parsed["release_id"],
                release_type=parsed["release_type"],
                release_name=parsed["release_name"],
                scheduled_time_utc=parsed["scheduled_time_utc"],
                source_url=parsed["source_url"],
                status=parsed["status"],
            )
            if existing is None:
                inserted += 1
            else:
                updated += 1

        await session.commit()
        return ManualReleaseSeedSummary(inserted=inserted, updated=updated)


def _parse_seed_entry(item: dict[str, object], *, index: int) -> dict[str, object]:
    release_type_raw = str(item.get("release_type", "")).strip()
    if not release_type_raw:
        raise ValueError(f"release entry at index {index} is missing release_type.")
    try:
        release_type = ReleaseType(release_type_raw).value
    except ValueError as exc:
        raise ValueError(f"release entry at index {index} has unsupported release_type: {release_type_raw}") from exc

    release_name = str(item.get("release_name", "")).strip()
    if not release_name:
        raise ValueError(f"release entry at index {index} is missing release_name.")

    scheduled_raw = str(item.get("scheduled_time_utc", "")).strip()
    if not scheduled_raw:
        raise ValueError(f"release entry at index {index} is missing scheduled_time_utc.")
    try:
        scheduled_time_utc = parse_iso_utc(scheduled_raw)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"release entry at index {index} has invalid scheduled_time_utc: {scheduled_raw}") from exc

    source_url = str(item.get("source_url", "")).strip() or "manual://seeded-release"
    status = str(item.get("status", "")).strip() or ReleaseStatus.SCHEDULED.value
    release_id = _manual_release_id(
        release_type=release_type,
        release_name=release_name,
        scheduled_time_utc_iso=scheduled_time_utc.isoformat(),
    )
    return {
        "release_id": release_id,
        "release_type": release_type,
        "release_name": release_name,
        "scheduled_time_utc": scheduled_time_utc,
        "source_url": source_url,
        "status": status,
    }


def _manual_release_id(*, release_type: str, release_name: str, scheduled_time_utc_iso: str) -> str:
    suffix = stable_hash(release_type, scheduled_time_utc_iso, release_name)[:12]
    return f"{release_type}-{suffix}"
