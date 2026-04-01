from app.providers.fallback_adapter import MockFallbackAdapterTrendProvider


class OpenAITrendProvider(MockFallbackAdapterTrendProvider):
    name = "openai"
    adapter_label = "OpenAI"
