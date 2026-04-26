from __future__ import annotations

from app.domain.enums import Severity
from app.domain.scoring_models import ScoredSignal, ScoringInput
from app.utils.math import clamp


class ScoringEngine:
    def score(self, scoring_input: ScoringInput) -> ScoredSignal:
        price_gap_score = int(clamp(scoring_input.price_gap / 0.12, 0.0, 1.0) * 40)
        speed_score = int(clamp((600.0 - scoring_input.speed_seconds) / 600.0, 0.0, 1.0) * 20)
        liquidity_score = int(clamp((0.2 - scoring_input.spread) / 0.2, 0.0, 1.0) * 15)
        confirmation_score = int(clamp(scoring_input.confirmation_strength, 0.0, 1.0) * 15)
        event_importance_score = int(clamp(scoring_input.event_importance, 0.0, 1.0) * 10)
        total = price_gap_score + speed_score + liquidity_score + confirmation_score + event_importance_score
        severity = self._severity_for_score(total)
        components = {
            "price_gap_score": price_gap_score,
            "speed_score": speed_score,
            "liquidity_score": liquidity_score,
            "confirmation_score": confirmation_score,
            "event_importance_score": event_importance_score,
        }
        return ScoredSignal(score=total, severity=severity, components=components)

    @staticmethod
    def _severity_for_score(score: int) -> Severity:
        if score >= 80:
            return Severity.CRITICAL
        if score >= 65:
            return Severity.HIGH
        if score >= 50:
            return Severity.MEDIUM
        return Severity.LOW
