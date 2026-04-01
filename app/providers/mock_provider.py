from app.providers.base import TrendProvider
from app.schemas.trend import (
    TrendAnalysisRequest,
    TrendAnalysisResult,
    TrendCandidate,
    TrendEvidence,
)


class MockTrendProvider(TrendProvider):
    name = "mock"

    def analyze(self, request: TrendAnalysisRequest) -> TrendAnalysisResult:
        topic = request.trend_topic
        candidates = [
            TrendCandidate(
                name=f"{topic} workflow automation",
                description="Growing use of workflow-native AI agents for repeatable delivery.",
                evidence=[
                    TrendEvidence(
                        source="mock_report",
                        title="Mock trend summary",
                        snippet="Teams are adopting reusable orchestration patterns.",
                    )
                ],
                freshness=0.72,
                confidence=0.68,
                adoption_note="Start with one narrow workflow and add guardrails before expansion.",
            ),
            TrendCandidate(
                name=f"{topic} retrieval quality controls",
                description="Focus on evidence quality and freshness scoring in trend pipelines.",
                evidence=[
                    TrendEvidence(
                        source="mock_briefing",
                        title="Mock evidence set",
                        snippet="Confidence signals are being standardized across providers.",
                    )
                ],
                freshness=0.64,
                confidence=0.62,
                adoption_note=(
                    "Define confidence thresholds before using trend output in decisions."
                ),
            ),
        ][: request.max_items]

        return TrendAnalysisResult(
            provider=self.name,
            trend_topic=topic,
            candidate_trends=candidates,
        )
