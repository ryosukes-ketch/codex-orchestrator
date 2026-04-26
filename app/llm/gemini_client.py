import json

import httpx

from app.llm.base import LLMClient

_DEFAULT_TIMEOUT = 60
_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiLLMClient(LLMClient):
    """generateContent via Google Gemini API."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.0-flash",
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout = timeout

    def complete(self, system: str, user: str) -> str:
        url = f"{_BASE_URL}/{self._model}:generateContent"
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"parts": [{"text": user}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        }
        resp = httpx.post(
            url,
            params={"key": self._api_key},
            headers={"Content-Type": "application/json"},
            content=json.dumps(payload).encode(),
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
