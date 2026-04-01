from app.schemas.trend import TrendAnalysisRequest, TrendAnalysisResult, TrendCandidate
from app.services.trend_workflow import (
    TREND_GOVERNANCE_NOTE,
    resolve_provider_hint,
    run_trend_mock_workflow,
)


class _StaticProvider:
    def analyze(self, request: TrendAnalysisRequest) -> TrendAnalysisResult:
        candidates = [
            TrendCandidate(
                name=f"candidate_{idx}",
                description=f"desc_{idx}",
                freshness=0.5,
                confidence=0.7,
                adoption_note=f"note_{idx}",
            )
            for idx in range(4)
        ]
        return TrendAnalysisResult(
            provider="static",
            trend_topic=request.trend_topic,
            candidate_trends=candidates,
        )


def test_run_trend_mock_workflow_with_default_mock_provider() -> None:
    report = run_trend_mock_workflow(
        TrendAnalysisRequest(
            trend_topic="agent governance",
            context="department handoff",
            max_items=2,
        )
    )

    assert report.provider == "mock"
    assert report.trend_topic == "agent governance"
    assert len(report.candidate_trends) == 2
    assert report.governance_note == TREND_GOVERNANCE_NOTE
    assert "GO/PAUSE/REVIEW" in report.next_action_suggestion
    for candidate in report.candidate_trends:
        assert 0.0 <= candidate.confidence <= 1.0
        assert 0.0 <= candidate.freshness <= 1.0
        assert candidate.adoption_note


def test_provider_hint_alias_uses_stub_provider_identity() -> None:
    report = run_trend_mock_workflow(
        TrendAnalysisRequest(trend_topic="trend safety", max_items=1),
        provider_hint="gemini-flash-latest",
    )

    assert report.provider == "gemini"
    assert report.provider_hint == "gemini-flash-latest"
    assert report.candidate_trends
    assert report.candidate_trends[0].adoption_note.endswith(
        "(Gemini adapter currently running in mock fallback mode.)"
    )


def test_unknown_provider_hint_falls_back_to_mock() -> None:
    report = run_trend_mock_workflow(
        TrendAnalysisRequest(trend_topic="fallback", max_items=1),
        provider_hint="unknown-provider",
    )

    assert report.provider == "mock"
    assert report.provider_hint == "unknown-provider"


def test_unknown_provider_hint_falls_back_to_mock_even_when_strict_env_enabled(
    monkeypatch,
) -> None:
    monkeypatch.setenv("TREND_PROVIDER_STRICT", "true")

    report = run_trend_mock_workflow(
        TrendAnalysisRequest(trend_topic="fallback", max_items=1),
        provider_hint="unknown-provider",
    )

    assert report.provider == "mock"
    assert report.provider_hint == "unknown-provider"


def test_resolve_provider_hint_for_latest_aliases() -> None:
    assert resolve_provider_hint("gemini-flash-lite-latest") == "gemini"
    assert resolve_provider_hint("grok-latest") == "grok"
    assert resolve_provider_hint("openai-latest") == "openai"


def test_resolve_provider_hint_normalizes_case_and_empty_string() -> None:
    assert resolve_provider_hint("GEMINI-FLASH-LATEST") == "gemini"
    assert resolve_provider_hint("") == "mock"


def test_run_trend_mock_workflow_with_injected_provider_truncates_candidates() -> None:
    report = run_trend_mock_workflow(
        TrendAnalysisRequest(trend_topic="injected", max_items=2),
        provider_hint="custom-provider-hint",
        provider=_StaticProvider(),
    )

    assert report.provider == "static"
    assert report.provider_hint == "custom-provider-hint"
    assert report.trend_topic == "injected"
    assert len(report.candidate_trends) == 2
    assert report.governance_note == TREND_GOVERNANCE_NOTE
    assert report.next_action_suggestion.startswith("Route findings to Progress Control")
