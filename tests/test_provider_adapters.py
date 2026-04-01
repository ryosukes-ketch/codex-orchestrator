import pytest

from app.providers.gemini_provider import GeminiTrendProvider
from app.providers.grok_provider import GrokTrendProvider
from app.providers.mock_provider import MockTrendProvider
from app.providers.openai_provider import OpenAITrendProvider
from app.schemas.trend import TrendAnalysisRequest


@pytest.mark.parametrize(
    ("provider", "provider_name", "adoption_suffix"),
    [
        (
            GeminiTrendProvider(api_key="k1"),
            "gemini",
            "(Gemini adapter currently running in mock fallback mode.)",
        ),
        (
            GrokTrendProvider(api_key="k2"),
            "grok",
            "(Grok adapter currently running in mock fallback mode.)",
        ),
        (
            OpenAITrendProvider(api_key="k3"),
            "openai",
            "(OpenAI adapter currently running in mock fallback mode.)",
        ),
    ],
)
def test_adapter_providers_apply_fallback_contract(
    provider, provider_name: str, adoption_suffix: str
) -> None:
    report = provider.analyze(TrendAnalysisRequest(trend_topic="adapter", max_items=2))

    assert report.provider == provider_name
    assert report.trend_topic == "adapter"
    assert len(report.candidate_trends) == 2
    for candidate in report.candidate_trends:
        assert candidate.adoption_note.endswith(adoption_suffix)
        assert candidate.confidence <= 0.5


def test_mock_provider_analyze_respects_request_max_items() -> None:
    provider = MockTrendProvider()

    one_item = provider.analyze(TrendAnalysisRequest(trend_topic="mock-topic", max_items=1))
    two_items = provider.analyze(TrendAnalysisRequest(trend_topic="mock-topic", max_items=2))

    assert one_item.provider == "mock"
    assert one_item.trend_topic == "mock-topic"
    assert len(one_item.candidate_trends) == 1
    assert len(two_items.candidate_trends) == 2
