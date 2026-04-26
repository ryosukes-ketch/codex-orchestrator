import json

import httpx

from app.llm.base import LLMClient

_DEFAULT_TIMEOUT = 60
_API_URL = "https://api.anthropic.com/v1/messages"
_API_VERSION = "2023-06-01"


class AnthropicLLMClient(LLMClient):
    """Messages API via Anthropic."""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-haiku-4-5",
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout = timeout

    def complete(self, system: str, user: str) -> str:
        payload = {
            "model": self._model,
            "max_tokens": 2048,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        resp = httpx.post(
            _API_URL,
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": _API_VERSION,
                "Content-Type": "application/json",
            },
            content=json.dumps(payload).encode(),
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]
