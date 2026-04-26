"""Tests for OpenClawLLMClient (Gateway HTTP mode)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.llm.openclaw_client import OpenClawLLMClient


def _chat_payload(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


class TestOpenClawLLMClientComplete:
    def _client(
        self,
        *,
        agent_id: str = "default",
        base_url: str = "http://127.0.0.1:18789/v1",
        auth_token: str | None = None,
        backend_model: str | None = None,
        max_retries: int = 0,
        retry_backoff_seconds: float = 0.0,
        chat_failure_cooldown_seconds: float = 120.0,
    ) -> OpenClawLLMClient:
        return OpenClawLLMClient(
            agent_id=agent_id,
            base_url=base_url,
            auth_token=auth_token,
            backend_model=backend_model,
            timeout=5,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            chat_failure_cooldown_seconds=chat_failure_cooldown_seconds,
        )

    def _ok_response(self, content: str = '{"ok": true}') -> MagicMock:
        response = MagicMock()
        response.status_code = 200
        response.text = json.dumps(_chat_payload(content))
        response.raise_for_status.return_value = None
        response.json.return_value = _chat_payload(content)
        return response

    def _responses_ok_response(self, content: str = '{"ok": true}') -> MagicMock:
        response = MagicMock()
        response.status_code = 200
        response.text = json.dumps(
            {
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": content}],
                    }
                ]
            }
        )
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": content}],
                }
            ]
        }
        return response

    def test_returns_chat_message_content(self) -> None:
        client = self._client()
        with patch("httpx.post", return_value=self._ok_response('{"ok": true}')):
            result = client.complete("sys", "user")
        assert result == '{"ok": true}'
        metadata = client.pop_last_call_metadata()
        assert metadata["gateway_endpoint"] == "chat/completions"
        assert metadata["gateway_status_code"] == 200
        assert metadata["gateway_fallback_used"] is False
        assert metadata["response_mode"] == "json_text"
        assert metadata["gateway_content_kind"] == "json_text"

    def test_classifies_upstream_rejection_embedded_in_chat_content(self) -> None:
        client = self._client()
        rejection_text = (
            "LLM request rejected: Your credit balance is too low to access "
            "the Anthropic API. Please go to Plans & Billing to upgrade or purchase credits."
        )

        with patch("httpx.post", return_value=self._ok_response(rejection_text)):
            result = client.complete("sys", "user")

        assert result == rejection_text
        metadata = client.pop_last_call_metadata()
        assert metadata["gateway_endpoint"] == "chat/completions"
        assert metadata["gateway_success"] is True
        assert metadata["gateway_error_kind"] == "upstream_rejection"
        assert metadata["response_mode"] == "plain_text_upstream_rejection"
        assert metadata["gateway_content_kind"] == "upstream_rejection"
        assert metadata["gateway_upstream_rejection"] is True
        assert metadata["gateway_upstream_provider"] == "anthropic"
        assert metadata["gateway_upstream_rejection_reason"] == "credit_balance_too_low"

    def test_sends_expected_payload_and_headers(self) -> None:
        client = self._client(auth_token="gateway-token", backend_model="openai-codex/gpt-5.2")
        calls: list[dict] = []

        def fake_post(url: str, headers: dict, content: bytes, timeout: int):  # noqa: ANN001
            calls.append({"url": url, "headers": headers, "content": content, "timeout": timeout})
            return self._ok_response('{"status":"ok"}')

        with patch("httpx.post", side_effect=fake_post):
            client.complete("system text", "user text")

        assert len(calls) == 1
        call = calls[0]
        assert call["url"] == "http://127.0.0.1:18789/v1/chat/completions"
        assert call["headers"]["Authorization"] == "Bearer gateway-token"
        assert call["headers"]["x-openclaw-model"] == "openai-codex/gpt-5.2"
        body = json.loads(call["content"].decode())
        assert body["model"] == "openclaw/default"
        assert body["messages"][0]["content"] == "system text"
        assert body["messages"][1]["content"] == "user text"
        assert body["response_format"] == {"type": "json_object"}

    def test_raises_on_transport_error(self) -> None:
        client = self._client(max_retries=1)
        with patch(
            "httpx.post",
            side_effect=httpx.ConnectError(
                "connect failed",
                request=httpx.Request("POST", "http://127.0.0.1:18789/v1/chat/completions"),
            ),
        ):
            with pytest.raises(RuntimeError, match="request failed.*2 attempt"):
                client.complete("sys", "user")

    def test_raises_on_timeout(self) -> None:
        client = self._client(max_retries=1)
        with patch(
            "httpx.post",
            side_effect=httpx.TimeoutException("timeout"),
        ):
            with pytest.raises(RuntimeError, match="timed out.*attempts=2"):
                client.complete("sys", "user")

    def test_retries_chat_request_before_fallback_when_transport_recovers(self) -> None:
        client = self._client(max_retries=1, retry_backoff_seconds=0.0)
        timeout_exc = httpx.TimeoutException("timeout")
        chat_ok = self._ok_response('{"status":"ok"}')

        with patch("httpx.post", side_effect=[timeout_exc, chat_ok]) as mock_post:
            result = client.complete("sys", "user")

        assert result == '{"status":"ok"}'
        assert mock_post.call_count == 2

    def test_raises_on_http_error(self) -> None:
        client = self._client()
        response = self._ok_response()
        response.status_code = 401
        response.text = '{"error":"unauthorized"}'
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401",
            request=httpx.Request("POST", "http://127.0.0.1:18789/v1/chat/completions"),
            response=response,
        )
        with patch("httpx.post", return_value=response):
            with pytest.raises(RuntimeError, match="HTTP 401"):
                client.complete("sys", "user")

    def test_raises_on_non_json_output(self) -> None:
        client = self._client()
        response = self._ok_response()
        response.text = "not-json"
        response.json.side_effect = json.JSONDecodeError("bad", "x", 0)
        with patch("httpx.post", return_value=response):
            with pytest.raises(RuntimeError, match="non-JSON"):
                client.complete("sys", "user")

    def test_raises_on_unexpected_payload_shape(self) -> None:
        client = self._client()
        response = self._ok_response()
        response.text = '{"choices":[]}'
        response.json.return_value = {"choices": []}
        with patch("httpx.post", return_value=response):
            with pytest.raises(RuntimeError, match="Unexpected OpenClaw chat response structure"):
                client.complete("sys", "user")

    def test_falls_back_to_responses_when_chat_endpoint_is_404(self) -> None:
        client = self._client()

        chat_404 = self._ok_response()
        chat_404.status_code = 404
        chat_404.text = "Not Found"
        chat_404.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404",
            request=httpx.Request("POST", "http://127.0.0.1:18789/v1/chat/completions"),
            response=chat_404,
        )
        responses_ok = self._responses_ok_response('{"status":"ok"}')

        with patch("httpx.post", side_effect=[chat_404, responses_ok]) as mock_post:
            result = client.complete("sys", "user")
        assert result == '{"status":"ok"}'
        assert mock_post.call_count == 2
        metadata = client.pop_last_call_metadata()
        assert metadata["gateway_endpoint"] == "responses"
        assert metadata["gateway_fallback_used"] is True
        assert metadata["gateway_status_code"] == 200
        assert metadata["gateway_fallback_reason"] == "chat endpoint unavailable (HTTP 404)"

    def test_raises_clear_error_when_chat_404_and_responses_fail(self) -> None:
        client = self._client()

        chat_404 = self._ok_response()
        chat_404.status_code = 404
        chat_404.text = "Not Found"
        chat_404.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404",
            request=httpx.Request("POST", "http://127.0.0.1:18789/v1/chat/completions"),
            response=chat_404,
        )

        responses_404 = self._responses_ok_response()
        responses_404.status_code = 404
        responses_404.text = "Not Found"
        responses_404.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404",
            request=httpx.Request("POST", "http://127.0.0.1:18789/v1/responses"),
            response=responses_404,
        )

        with patch("httpx.post", side_effect=[chat_404, responses_404]):
            with pytest.raises(
                RuntimeError,
                match="chat endpoint is unavailable or unhealthy",
            ):
                client.complete("sys", "user")
        metadata = client.pop_last_call_metadata()
        assert metadata["gateway_endpoint"] == "responses"
        assert metadata["gateway_status_code"] == 404
        assert metadata["gateway_success"] is False
        assert metadata["gateway_error_kind"] == "http_status"

    def test_falls_back_to_responses_when_chat_times_out(self) -> None:
        client = self._client()
        timeout_exc = httpx.TimeoutException("timeout")
        responses_ok = self._responses_ok_response('{"status":"ok"}')

        with patch("httpx.post", side_effect=[timeout_exc, responses_ok]) as mock_post:
            result = client.complete("sys", "user")

        assert result == '{"status":"ok"}'
        assert mock_post.call_count == 2

    def test_falls_back_to_responses_when_chat_transport_fails(self) -> None:
        client = self._client()
        connect_exc = httpx.ConnectError(
            "connect failed",
            request=httpx.Request("POST", "http://127.0.0.1:18789/v1/chat/completions"),
        )
        responses_ok = self._responses_ok_response('{"status":"ok"}')

        with patch("httpx.post", side_effect=[connect_exc, responses_ok]) as mock_post:
            result = client.complete("sys", "user")

        assert result == '{"status":"ok"}'
        assert mock_post.call_count == 2

    def test_raises_clear_error_when_chat_and_responses_transport_fail(self) -> None:
        client = self._client()
        timeout_1 = httpx.TimeoutException("timeout")
        timeout_2 = httpx.TimeoutException("timeout")

        with patch("httpx.post", side_effect=[timeout_1, timeout_2]):
            with pytest.raises(
                RuntimeError,
                match="responses fallback also failed",
            ):
                client.complete("sys", "user")

    def test_chat_failure_sets_responses_cooldown_preference_for_next_call(self) -> None:
        client = self._client(chat_failure_cooldown_seconds=60.0)
        timeout_exc = httpx.TimeoutException("timeout")
        responses_ok_1 = self._responses_ok_response('{"status":"ok-1"}')
        responses_ok_2 = self._responses_ok_response('{"status":"ok-2"}')

        with patch(
            "httpx.post",
            side_effect=[timeout_exc, responses_ok_1, responses_ok_2],
        ) as mock_post:
            first = client.complete("sys", "user")
            second = client.complete("sys", "user")

        assert first == '{"status":"ok-1"}'
        assert second == '{"status":"ok-2"}'
        assert mock_post.call_count == 3

        first_url = mock_post.call_args_list[0].args[0]
        second_url = mock_post.call_args_list[1].args[0]
        third_url = mock_post.call_args_list[2].args[0]
        assert first_url.endswith("/chat/completions")
        assert second_url.endswith("/responses")
        assert third_url.endswith("/responses")
