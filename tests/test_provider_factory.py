import pytest

from app.providers.factory import get_trend_provider
from app.providers.gemini_provider import GeminiTrendProvider
from app.providers.grok_provider import GrokTrendProvider
from app.providers.mock_provider import MockTrendProvider
from app.providers.openai_provider import OpenAITrendProvider


def test_get_trend_provider_returns_expected_provider_types() -> None:
    assert isinstance(get_trend_provider("gemini"), GeminiTrendProvider)
    assert isinstance(get_trend_provider("grok"), GrokTrendProvider)
    assert isinstance(get_trend_provider("openai"), OpenAITrendProvider)
    assert isinstance(get_trend_provider("mock"), MockTrendProvider)


def test_get_trend_provider_normalizes_name_and_falls_back_to_mock() -> None:
    assert isinstance(get_trend_provider("  GEMINI  "), GeminiTrendProvider)
    assert isinstance(get_trend_provider("gemini-flash-lite-latest"), GeminiTrendProvider)
    assert isinstance(get_trend_provider("grok-2-latest"), GrokTrendProvider)
    assert isinstance(get_trend_provider("gpt-4.1-mini"), OpenAITrendProvider)
    assert isinstance(get_trend_provider(""), MockTrendProvider)
    assert isinstance(get_trend_provider("   "), MockTrendProvider)
    assert isinstance(get_trend_provider("unknown-provider"), MockTrendProvider)


def test_get_trend_provider_reads_api_keys_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key-1")
    monkeypatch.setenv("GROK_API_KEY", "grok-key-1")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key-1")

    gemini = get_trend_provider("gemini")
    grok = get_trend_provider("grok")
    openai = get_trend_provider("openai")

    assert isinstance(gemini, GeminiTrendProvider)
    assert isinstance(grok, GrokTrendProvider)
    assert isinstance(openai, OpenAITrendProvider)
    assert gemini.api_key == "gemini-key-1"
    assert grok.api_key == "grok-key-1"
    assert openai.api_key == "openai-key-1"


def test_get_trend_provider_unknown_provider_raises_when_strict_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TREND_PROVIDER_STRICT", "true")

    with pytest.raises(ValueError, match="Unsupported trend provider"):
        get_trend_provider("unknown-provider")


def test_get_trend_provider_unknown_provider_raises_when_strict_env_is_malformed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TREND_PROVIDER_STRICT", "not-a-bool")

    with pytest.raises(ValueError, match="Unsupported trend provider"):
        get_trend_provider("unknown-provider")


def test_get_trend_provider_mock_is_allowed_when_strict_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TREND_PROVIDER_STRICT", "true")

    assert isinstance(get_trend_provider("mock"), MockTrendProvider)
    assert isinstance(get_trend_provider("   "), MockTrendProvider)


def test_get_trend_provider_strict_argument_overrides_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TREND_PROVIDER_STRICT", "true")

    mock_provider = get_trend_provider("unknown-provider", strict=False)
    assert isinstance(mock_provider, MockTrendProvider)

    with pytest.raises(ValueError, match="Unsupported trend provider"):
        get_trend_provider("unknown-provider", strict=True)
