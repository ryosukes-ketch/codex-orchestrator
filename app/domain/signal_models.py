from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.domain.enums import Severity, SignalType


class SignalDraft(BaseModel):
    release_id: str
    market_ticker: str
    signal_type: SignalType
    emitted_at_utc: datetime
    reason_codes: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)


class SignalRecord(BaseModel):
    signal_id: str
    release_id: str
    market_ticker: str
    signal_type: SignalType
    score: int
    severity: Severity
    reason_codes_json: list[str] = Field(default_factory=list)
    emitted_at_utc: datetime
