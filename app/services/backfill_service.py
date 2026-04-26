from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import ReleaseRepository
from app.services.replay_service import ReplayService


class BackfillService:
    def __init__(self, replay_service: ReplayService) -> None:
        self.replay_service = replay_service

    async def run(
        self,
        session: AsyncSession,
        from_utc: datetime,
        to_utc: datetime,
        *,
        send_notifications: bool = False,
    ) -> dict[str, int]:
        release_repo = ReleaseRepository(session)
        releases = await release_repo.list_between(from_utc, to_utc)
        total_saved = 0
        total_notified = 0
        for release in releases:
            result = await self.replay_service.replay_release(
                session,
                release.release_id,
                send_notifications=send_notifications,
            )
            total_saved += result["signals_saved"]
            total_notified += result["signals_notified"]
        return {"releases_processed": len(releases), "signals_saved": total_saved, "signals_notified": total_notified}
