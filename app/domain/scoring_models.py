from __future__ import annotations

from pydantic import BaseModel, Field

from app.domain.enums import Severity


class ScoringInput(BaseModel):
    price_gap: float = 0.0
    speed_seconds: float = 120.0
    spread: float = 0.2
    liquidity_depth: float = 0.0
    confirmation_strength: float = 0.0
    event_importance: float = 1.0


class ScoredSignal(BaseModel):
    score: int
    severity: Severity
    components: dict[str, int] = Field(default_factory=dict)
