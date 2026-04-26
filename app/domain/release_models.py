from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.domain.enums import ReleaseStatus, ReleaseType


class ReleaseCalendarEntry(BaseModel):
    release_id: str
    release_type: ReleaseType
    release_name: str
    scheduled_time_utc: datetime
    source_url: str
    status: ReleaseStatus = ReleaseStatus.SCHEDULED


class ReleaseActual(BaseModel):
    release_id: str
    actual_value_raw: str
    actual_value_num: float | None = None
    parsed_payload_json: dict[str, Any] = Field(default_factory=dict)
    parsed_at_utc: datetime
