from __future__ import annotations

from fastapi import APIRouter, Query, Request

from app.api.schemas import SignalResponse
from app.db.repositories import SignalRepository

router = APIRouter(tags=["signals"])


async def _list_signals(
    request: Request,
    *,
    limit: int,
    severity: str | None = None,
) -> list[SignalResponse]:
    runtime = request.app.state.runtime
    async with runtime.session_factory() as session:
        repo = SignalRepository(session)
        signals = await repo.list_recent(limit=limit, severity=severity)
        return [
            SignalResponse(
                signal_id=item.signal_id,
                release_id=item.release_id,
                market_ticker=item.market_ticker,
                signal_type=item.signal_type,
                score=item.score,
                severity=item.severity,
                reason_codes=item.reason_codes_json,
                emitted_at_utc=item.emitted_at_utc,
            )
            for item in signals
        ]


@router.get("/signals", response_model=list[SignalResponse])
async def signals(
    request: Request,
    limit: int = Query(default=20, ge=1, le=500),
    severity: str | None = Query(default=None),
) -> list[SignalResponse]:
    return await _list_signals(request, limit=limit, severity=severity)


@router.get("/signals/recent", response_model=list[SignalResponse])
async def recent_signals(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    severity: str | None = Query(default=None),
) -> list[SignalResponse]:
    return await _list_signals(request, limit=limit, severity=severity)
