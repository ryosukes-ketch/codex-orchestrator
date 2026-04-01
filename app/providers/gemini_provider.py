from app.providers.fallback_adapter import MockFallbackAdapterTrendProvider


class GeminiTrendProvider(MockFallbackAdapterTrendProvider):
    name = "gemini"
    adapter_label = "Gemini"
