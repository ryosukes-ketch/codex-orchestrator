import os

from app.providers.base import TrendProvider
from app.providers.gemini_provider import GeminiTrendProvider
from app.providers.grok_provider import GrokTrendProvider
from app.providers.mock_provider import MockTrendProvider
from app.providers.openai_provider import OpenAITrendProvider
from app.runtime_flags import parse_strict_env_flag


def get_trend_provider(name: str, *, strict: bool | None = None) -> TrendProvider:
    normalized = ((name or "").strip().lower() or "mock")
    strict_mode = (
        strict
        if strict is not None
        else parse_strict_env_flag(os.getenv("TREND_PROVIDER_STRICT"))
    )
    if normalized == "mock":
        return MockTrendProvider()
    if normalized == "gemini" or normalized.startswith("gemini-"):
        return GeminiTrendProvider(api_key=os.getenv("GEMINI_API_KEY"))
    if normalized == "grok" or normalized.startswith("grok-"):
        return GrokTrendProvider(api_key=os.getenv("GROK_API_KEY"))
    if normalized == "openai" or normalized.startswith("openai-") or normalized.startswith("gpt-"):
        return OpenAITrendProvider(api_key=os.getenv("OPENAI_API_KEY"))
    if strict_mode:
        raise ValueError(f"Unsupported trend provider: {name}")
    return MockTrendProvider()
