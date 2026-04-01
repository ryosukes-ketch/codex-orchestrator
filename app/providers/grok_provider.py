from app.providers.fallback_adapter import MockFallbackAdapterTrendProvider


class GrokTrendProvider(MockFallbackAdapterTrendProvider):
    name = "grok"
    adapter_label = "Grok"
