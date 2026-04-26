from __future__ import annotations

from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.db.models import MarketCatalogModel
from app.db.repositories import MarketRepository


class _Result:
    def scalar_one_or_none(self):
        return None


class _CaptureSession:
    def __init__(self) -> None:
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return _Result()


def test_market_catalog_title_and_subtitle_are_text_columns() -> None:
    title_type = MarketCatalogModel.__table__.columns["title"].type
    subtitle_type = MarketCatalogModel.__table__.columns["subtitle"].type

    assert isinstance(title_type, sa.Text)
    assert isinstance(subtitle_type, sa.Text)
    assert getattr(title_type, "length", None) is None
    assert getattr(subtitle_type, "length", None) is None


@pytest.mark.asyncio
async def test_upsert_market_keeps_long_title_payload() -> None:
    session = _CaptureSession()
    repo = MarketRepository(session)  # type: ignore[arg-type]
    long_title = "X" * 1200
    long_subtitle = "Y" * 900
    now = datetime.now(timezone.utc)

    await repo.upsert_market(
        market_ticker="CPI-LONG-TITLE",
        platform="kalshi",
        title=long_title,
        subtitle=long_subtitle,
        close_time_utc=now,
        status="open",
        release_type="CPI",
        mapping_confidence=0.9,
        mapping_payload_json={"source": "test"},
    )

    compiled = session.statement.compile(dialect=postgresql.dialect())
    param_values = list(compiled.params.values())

    assert long_title in param_values
    assert long_subtitle in param_values
    assert len(long_title) > 512
    assert len(long_subtitle) > 512
