"""LLM client that routes calls through the local OpenClaw Gateway HTTP API.

Agent-first routing:
    model = "openclaw/<agent_id>"

Optional backend model override:
    x-openclaw-model: <provider/model>
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, ClassVar

import httpx

from app.llm.base import LLMClient

logger = logging.getLogger(__name__)

_UPSTREAM_REJECTION_MARKERS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:llm\s+)?request rejected\b", re.IGNORECASE),
    re.compile(r"\bcredit balance is too low\b", re.IGNORECASE),
    re.compile(r"\bplans?\s*&\s*billing\b", re.IGNORECASE),
    re.compile(r"\bpurchase credits?\b", re.IGNORECASE),
    re.compile(r"\bquota exceeded\b", re.IGNORECASE),
    re.compile(r"\brate limit(?:ed)?\b", re.IGNORECASE),
    re.compile(r"\baccess denied\b", re.IGNORECASE),
    re.compile(r"\bforbidden\b", re.IGNORECASE),
)

_UPSTREAM_PROVIDER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("anthropic", re.compile(r"\banthropic\b", re.IGNORECASE)),
    ("openai", re.compile(r"\bopenai\b", re.IGNORECASE)),
    ("gemini", re.compile(r"\b(?:gemini|google ai|google api)\b", re.IGNORECASE)),
    ("grok", re.compile(r"\b(?:grok|xai|x\.ai)\b", re.IGNORECASE)),
)

_UPSTREAM_REASON_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "credit_balance_too_low",
        re.compile(
            r"\bcredit balance is too low\b|\bplans?\s*&\s*billing\b|\bpurchase credits?\b",
            re.IGNORECASE,
        ),
    ),
    (
        "rate_limited",
        re.compile(
            r"\brate limit(?:ed)?\b|\btoo many requests\b|\bquota exceeded\b",
            re.IGNORECASE,
        ),
    ),
    (
        "authentication_failed",
        re.compile(
            r"\binvalid api key\b|\bauthentication failed\b|\bunauthorized\b",
            re.IGNORECASE,
        ),
    ),
    (
        "access_denied",
        re.compile(r"\baccess denied\b|\bforbidden\b|\bpermission denied\b", re.IGNORECASE),
    ),
    (
        "provider_unavailable",
        re.compile(
            r"\bservice unavailable\b|\boverloaded\b|\btemporarily unavailable\b",
            re.IGNORECASE,
        ),
    ),
)


def _classify_gateway_content(content: str) -> dict[str, Any]:
    cleaned = content.strip()
    if not cleaned:
        return {
            "response_mode": "empty_text",
            "gateway_content_kind": "empty_text",
        }

    try:
        parsed = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        parsed = None

    if isinstance(parsed, (dict, list)):
        return {
            "response_mode": "json_text",
            "gateway_content_kind": "json_text",
        }

    metadata: dict[str, Any] = {
        "response_mode": "plain_text",
        "gateway_content_kind": "plain_text",
    }
    if not any(pattern.search(cleaned) for pattern in _UPSTREAM_REJECTION_MARKERS):
        return metadata

    provider = ""
    for provider_name, pattern in _UPSTREAM_PROVIDER_PATTERNS:
        if pattern.search(cleaned):
            provider = provider_name
            break

    reason = "unknown_reason"
    for reason_name, pattern in _UPSTREAM_REASON_PATTERNS:
        if pattern.search(cleaned):
            reason = reason_name
            break

    metadata.update(
        {
            "response_mode": "plain_text_upstream_rejection",
            "gateway_content_kind": "upstream_rejection",
            "gateway_upstream_rejection": True,
            "gateway_upstream_provider": provider or "unknown_provider",
            "gateway_upstream_rejection_reason": reason,
            "gateway_error_kind": "upstream_rejection",
        }
    )
    return metadata


class OpenClawLLMClient(LLMClient):
    """Call OpenClaw Gateway to proxy requests through a configured agent.

    Args:
        agent_id: OpenClaw agent ID (for example "default" or "research").
        base_url: OpenClaw Gateway API base URL.
        auth_token: Optional gateway bearer token.
        backend_model: Optional backend override sent as x-openclaw-model.
        timeout: HTTP timeout in seconds.
    """

    DEFAULT_BASE_URL: ClassVar[str] = "http://127.0.0.1:18789/v1"
    DEFAULT_AGENT_ID: ClassVar[str] = "default"
    DEFAULT_TIMEOUT: ClassVar[int] = 60
    DEFAULT_MAX_RETRIES: ClassVar[int] = 1
    DEFAULT_RETRY_BACKOFF_SECONDS: ClassVar[float] = 0.75
    DEFAULT_CHAT_FAILURE_COOLDOWN_SECONDS: ClassVar[float] = 120.0

    def __init__(
        self,
        agent_id: str = DEFAULT_AGENT_ID,
        base_url: str = DEFAULT_BASE_URL,
        auth_token: str | None = None,
        backend_model: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
        chat_failure_cooldown_seconds: float = DEFAULT_CHAT_FAILURE_COOLDOWN_SECONDS,
    ) -> None:
        self._agent_id = agent_id
        self._base_url = base_url.rstrip("/")
        self._auth_token = auth_token
        self._backend_model = backend_model
        self._timeout = timeout
        self._max_retries = max(0, int(max_retries))
        self._retry_backoff_seconds = max(0.0, float(retry_backoff_seconds))
        self._chat_failure_cooldown_seconds = max(0.0, float(chat_failure_cooldown_seconds))
        self._prefer_responses_until = 0.0
        self._last_call_metadata: dict[str, Any] = {}

    def _mark_chat_unhealthy(self) -> None:
        if self._chat_failure_cooldown_seconds <= 0:
            return
        self._prefer_responses_until = (
            time.monotonic() + self._chat_failure_cooldown_seconds
        )

    def _clear_chat_unhealthy(self) -> None:
        self._prefer_responses_until = 0.0

    def _should_prefer_responses(self) -> bool:
        return time.monotonic() < self._prefer_responses_until

    def _set_last_call_metadata(
        self,
        *,
        endpoint: str,
        status_code: int,
        fallback_used: bool,
        success: bool,
        error_kind: str = "",
        fallback_reason: str = "",
        extra: dict[str, Any] | None = None,
    ) -> None:
        metadata: dict[str, Any] = {
            "provider": "openclaw",
            "model": f"openclaw/{self._agent_id}",
            "gateway_endpoint": endpoint,
            "gateway_status_code": status_code,
            "gateway_fallback_used": fallback_used,
            "gateway_success": success,
        }
        if self._backend_model:
            metadata["gateway_backend_override"] = self._backend_model
        if error_kind:
            metadata["gateway_error_kind"] = error_kind
        if fallback_reason:
            metadata["gateway_fallback_reason"] = fallback_reason
        if extra:
            for key, value in extra.items():
                if value is None:
                    continue
                if isinstance(value, str):
                    value = value.strip()
                    if not value:
                        continue
                metadata[key] = value
        self._last_call_metadata = metadata

    def pop_last_call_metadata(self) -> dict[str, Any]:
        snapshot = dict(self._last_call_metadata)
        self._last_call_metadata = {}
        return snapshot

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._auth_token:
            headers["Authorization"] = f"Bearer {self._auth_token}"
        if self._backend_model:
            headers["x-openclaw-model"] = self._backend_model
        return headers

    def _post_gateway(self, path: str, payload: dict) -> httpx.Response:
        url = f"{self._base_url}/{path.lstrip('/')}"
        logger.debug(
            "OpenClawLLMClient: POST %s model=%s backend_override=%s",
            url,
            payload.get("model", ""),
            bool(self._backend_model),
        )
        last_error: Exception | None = None
        attempts = self._max_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                return httpx.post(
                    url,
                    headers=self._headers(),
                    content=json.dumps(payload).encode(),
                    timeout=self._timeout,
                )
            except httpx.TimeoutException as exc:
                last_error = exc
                logger.warning(
                    "OpenClaw request timeout attempt=%s/%s url=%s",
                    attempt,
                    attempts,
                    url,
                )
            except httpx.RequestError as exc:
                last_error = exc
                logger.warning(
                    "OpenClaw request transport failure attempt=%s/%s url=%s error=%s",
                    attempt,
                    attempts,
                    url,
                    exc,
                )

            if attempt < attempts and self._retry_backoff_seconds > 0:
                time.sleep(self._retry_backoff_seconds)

        if isinstance(last_error, httpx.TimeoutException):
            raise RuntimeError(
                "OpenClaw Gateway timed out after "
                f"{self._timeout}s at {url} (attempts={attempts})"
            ) from last_error
        if isinstance(last_error, httpx.RequestError):
            raise RuntimeError(
                f"OpenClaw Gateway request failed at {url} after {attempts} attempt(s): "
                f"{last_error}. Ensure gateway is running and HTTP endpoints are enabled."
            ) from last_error
        raise RuntimeError(f"OpenClaw Gateway request failed at {url} (unknown transport error)")

    @staticmethod
    def _extract_chat_content(data: dict) -> str:
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(
                f"Unexpected OpenClaw chat response structure: {json.dumps(data)[:300]}"
            ) from exc
        if isinstance(content, str):
            return content
        raise RuntimeError(
            f"Unexpected OpenClaw content type: {type(content)!r}; expected string response"
        )

    @staticmethod
    def _extract_responses_content(data: dict) -> str:
        # OpenAI-compatible Responses API commonly returns either output_text
        # or a message/content structure inside output[].
        output_text = data.get("output_text")
        if isinstance(output_text, str) and output_text:
            return output_text

        output = data.get("output")
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    text_value = block.get("text") or block.get("output_text")
                    if isinstance(text_value, str) and text_value:
                        return text_value

        raise RuntimeError(
            f"Unexpected OpenClaw responses structure: {json.dumps(data)[:300]}"
        )

    def _complete_via_responses(
        self,
        system: str,
        user: str,
        *,
        fallback_reason: str,
        fallback_used: bool,
    ) -> str:
        responses_payload = {
            "model": f"openclaw/{self._agent_id}",
            "instructions": system,
            "input": user,
            "text": {"format": {"type": "json_object"}},
        }
        try:
            responses_response = self._post_gateway("responses", responses_payload)
        except RuntimeError as responses_transport_exc:
            self._set_last_call_metadata(
                endpoint="responses",
                status_code=0,
                fallback_used=fallback_used,
                success=False,
                error_kind="transport_error",
                fallback_reason=fallback_reason,
            )
            raise RuntimeError(
                "OpenClaw chat request failed and responses fallback also failed: "
                f"chat={fallback_reason}; responses={responses_transport_exc}"
            ) from responses_transport_exc

        try:
            responses_response.raise_for_status()
        except httpx.HTTPStatusError as responses_exc:
            body_excerpt = (responses_response.text or "")[:300]
            self._set_last_call_metadata(
                endpoint="responses",
                status_code=int(responses_response.status_code),
                fallback_used=fallback_used,
                success=False,
                error_kind="http_status",
                fallback_reason=fallback_reason,
            )
            raise RuntimeError(
                "OpenClaw chat endpoint is unavailable or unhealthy and "
                f"responses endpoint returned HTTP {responses_response.status_code}: "
                f"{body_excerpt}. Enable "
                "`gateway.http.endpoints.chatCompletions.enabled: true` "
                "or `gateway.http.endpoints.responses.enabled: true`."
            ) from responses_exc
        try:
            responses_data = responses_response.json()
        except json.JSONDecodeError as responses_json_exc:
            self._set_last_call_metadata(
                endpoint="responses",
                status_code=200,
                fallback_used=fallback_used,
                success=False,
                error_kind="non_json_response",
                fallback_reason=fallback_reason,
            )
            raise RuntimeError(
                "OpenClaw responses endpoint returned non-JSON output: "
                f"{(responses_response.text or '')[:200]}"
            ) from responses_json_exc
        content = self._extract_responses_content(responses_data)
        content_metadata = _classify_gateway_content(content)
        self._set_last_call_metadata(
            endpoint="responses",
            status_code=200,
            fallback_used=fallback_used,
            success=True,
            fallback_reason=fallback_reason,
            extra=content_metadata,
        )
        return content

    def complete(self, system: str, user: str) -> str:
        self._last_call_metadata = {}
        if self._should_prefer_responses():
            try:
                return self._complete_via_responses(
                    system,
                    user,
                    fallback_reason="chat endpoint in cooldown window",
                    fallback_used=False,
                )
            except RuntimeError as responses_exc:
                logger.warning(
                    "OpenClaw responses-preferred attempt failed; retrying chat path: %s",
                    responses_exc,
                )

        chat_payload = {
            "model": f"openclaw/{self._agent_id}",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
        }
        try:
            response = self._post_gateway("chat/completions", chat_payload)
        except RuntimeError as chat_transport_exc:
            logger.warning(
                "OpenClaw chat transport failed. Falling back to /v1/responses: %s",
                chat_transport_exc,
            )
            self._mark_chat_unhealthy()
            return self._complete_via_responses(
                system,
                user,
                fallback_reason=str(chat_transport_exc),
                fallback_used=True,
            )

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # OpenClaw can have chat endpoint disabled while responses endpoint
            # is enabled. Fall back to /v1/responses when chat returns 404.
            if response.status_code == 404:
                logger.warning(
                    "OpenClaw chat endpoint unavailable (404). "
                    "Falling back to /v1/responses."
                )
                self._mark_chat_unhealthy()
                return self._complete_via_responses(
                    system,
                    user,
                    fallback_reason="chat endpoint unavailable (HTTP 404)",
                    fallback_used=True,
                )

            body_excerpt = (response.text or "")[:300]
            self._set_last_call_metadata(
                endpoint="chat/completions",
                status_code=int(response.status_code),
                fallback_used=False,
                success=False,
                error_kind="http_status",
            )
            raise RuntimeError(
                f"OpenClaw Gateway returned HTTP {response.status_code}: {body_excerpt}"
            ) from exc

        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            self._set_last_call_metadata(
                endpoint="chat/completions",
                status_code=200,
                fallback_used=False,
                success=False,
                error_kind="non_json_response",
            )
            raise RuntimeError(
                f"OpenClaw Gateway returned non-JSON output: {(response.text or '')[:200]}"
            ) from exc

        self._clear_chat_unhealthy()
        try:
            content = self._extract_chat_content(data)
        except RuntimeError:
            self._set_last_call_metadata(
                endpoint="chat/completions",
                status_code=200,
                fallback_used=False,
                success=False,
                error_kind="invalid_payload",
            )
            raise
        content_metadata = _classify_gateway_content(content)
        self._set_last_call_metadata(
            endpoint="chat/completions",
            status_code=200,
            fallback_used=False,
            success=True,
            extra=content_metadata,
        )
        return content
