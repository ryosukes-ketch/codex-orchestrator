from __future__ import annotations

from app.domain.scoring_models import ScoringInput
from app.services.scoring_engine import ScoringEngine


def test_scoring_engine_critical_bucket() -> None:
    engine = ScoringEngine()
    scored = engine.score(
        ScoringInput(
            price_gap=0.12,
            speed_seconds=10,
            spread=0.01,
            liquidity_depth=100,
            confirmation_strength=1.0,
            event_importance=1.0,
        )
    )
    assert scored.score >= 80
    assert scored.severity.value == "critical"


def test_scoring_engine_low_bucket() -> None:
    engine = ScoringEngine()
    scored = engine.score(
        ScoringInput(
            price_gap=0.01,
            speed_seconds=590,
            spread=0.2,
            liquidity_depth=0,
            confirmation_strength=0.0,
            event_importance=0.2,
        )
    )
    assert scored.score < 50
    assert scored.severity.value == "low"
