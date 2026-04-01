from app.providers.base import TrendProvider
from app.providers.factory import get_trend_provider
from app.schemas.trend import TrendAnalysisRequest, TrendWorkflowReport

PROVIDER_HINT_ALIASES = {
    "gemini-flash-latest": "gemini",
    "gemini-flash-lite-latest": "gemini",
    "grok-latest": "grok",
    "openai-latest": "openai",
}

TREND_GOVERNANCE_NOTE = (
    "Trend output is informational only and cannot self-authorize risky continuation."
)

TREND_NEXT_ACTION = (
    "Route findings to Progress Control and Management for GO/PAUSE/REVIEW governance."
)


def resolve_provider_hint(provider_hint: str) -> str:
    normalized = (provider_hint or "mock").strip().lower()
    return PROVIDER_HINT_ALIASES.get(normalized, normalized)


def run_trend_mock_workflow(
    request: TrendAnalysisRequest,
    *,
    provider_hint: str = "mock",
    provider: TrendProvider | None = None,
) -> TrendWorkflowReport:
    resolved_provider_name = resolve_provider_hint(provider_hint)
    trend_provider = provider or get_trend_provider(resolved_provider_name, strict=False)
    result = trend_provider.analyze(request)

    return TrendWorkflowReport(
        provider=result.provider,
        provider_hint=provider_hint,
        trend_topic=result.trend_topic,
        candidate_trends=result.candidate_trends[: request.max_items],
        governance_note=TREND_GOVERNANCE_NOTE,
        next_action_suggestion=TREND_NEXT_ACTION,
    )
