from app.providers.base import TrendProvider
from app.providers.mock_provider import MockTrendProvider
from app.schemas.trend import TrendAnalysisRequest, TrendAnalysisResult


class MockFallbackAdapterTrendProvider(TrendProvider):
    adapter_label: str = "Provider"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key
        self._fallback = MockTrendProvider()

    def analyze(self, request: TrendAnalysisRequest) -> TrendAnalysisResult:
        # Stub adapter: no live external call in MVP.
        result = self._fallback.analyze(request)
        result.provider = self.name
        suffix = (
            f" ({self.adapter_label} adapter currently running in mock fallback mode.)"
        )
        for candidate in result.candidate_trends:
            candidate.adoption_note += suffix
            candidate.confidence = min(candidate.confidence, 0.5)
        return result
