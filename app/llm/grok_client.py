from app.llm.openai_client import OpenAILLMClient

_GROK_BASE_URL = "https://api.x.ai/v1"


class GrokLLMClient(OpenAILLMClient):
    """Grok via xAI API (OpenAI-compatible endpoint)."""

    def __init__(self, api_key: str, model: str = "grok-3-mini", **kwargs) -> None:
        super().__init__(api_key=api_key, model=model, base_url=_GROK_BASE_URL, **kwargs)
