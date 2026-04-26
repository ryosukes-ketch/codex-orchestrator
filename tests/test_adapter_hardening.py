"""Tests for adapter header hardening and request_with_backoff 4xx non-retry behaviour.

Covers:
- FedClient uses browser-like headers and follow_redirects=True
- BEAClient uses browser-like headers and follow_redirects=True
- request_with_backoff does NOT retry on 4xx (client errors)
- request_with_backoff DOES retry on 5xx (server errors)
"""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

import app.adapters._http as _http_mod
from app.adapters._http import request_with_backoff
from app.adapters.bea_client import BEAClient
from app.adapters.fed_client import FedClient
from app.config import Settings

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_TEST_SETTINGS = Settings(
    DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/test",
    FED_BASE_URL="https://www.federalreserve.gov",
    BEA_BASE_URL="https://www.bea.gov",
)


class _OkResponse:
    text = "<html>ok</html>"


# ---------------------------------------------------------------------------
# FedClient header tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fed_client_uses_browser_like_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def _fake(client, method, url, **kwargs):
        captured["headers"] = {k.lower(): v for k, v in client.headers.items()}
        captured["follow_redirects"] = client.follow_redirects
        return _OkResponse()

    monkeypatch.setattr("app.adapters.fed_client.request_with_backoff", _fake)
    client = FedClient(settings=_TEST_SETTINGS)
    try:
        await client.fetch_fomc_calendar_html()
    finally:
        await client.close()

    h = captured["headers"]
    assert isinstance(h, dict)
    assert "mozilla" in str(h["user-agent"]).lower()
    assert "text/html" in str(h["accept"]).lower()
    assert str(h["accept-language"]).lower().startswith("en-us")
    assert str(h["referer"]).startswith("https://www.federalreserve.gov/")
    assert captured["follow_redirects"] is True


# ---------------------------------------------------------------------------
# BEAClient header tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bea_client_uses_browser_like_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def _fake(client, method, url, **kwargs):
        captured["headers"] = {k.lower(): v for k, v in client.headers.items()}
        captured["follow_redirects"] = client.follow_redirects
        return _OkResponse()

    monkeypatch.setattr("app.adapters.bea_client.request_with_backoff", _fake)
    client = BEAClient(settings=_TEST_SETTINGS)
    try:
        await client.fetch_schedule_html()
    finally:
        await client.close()

    h = captured["headers"]
    assert isinstance(h, dict)
    assert "mozilla" in str(h["user-agent"]).lower()
    assert "text/html" in str(h["accept"]).lower()
    assert str(h["accept-language"]).lower().startswith("en-us")
    assert str(h["referer"]).startswith("https://www.bea.gov/")
    assert captured["follow_redirects"] is True


# ---------------------------------------------------------------------------
# request_with_backoff 4xx non-retry tests
# ---------------------------------------------------------------------------


def _make_status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.com/test")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(
        f"HTTP {status_code}",
        request=request,
        response=response,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [400, 403, 404, 422, 429])
async def test_4xx_is_not_retried(status_code: int) -> None:
    """4xx responses must raise immediately without any retry sleep."""
    call_count = 0
    exc = _make_status_error(status_code)

    async def _failing_request(**_kwargs):  # noqa: ANN003
        nonlocal call_count
        call_count += 1
        raise exc

    fake_client = MagicMock(spec=httpx.AsyncClient)
    fake_client.request = AsyncMock(side_effect=_failing_request)

    logger = logging.getLogger("test")
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await request_with_backoff(
            fake_client,
            "GET",
            "https://example.com/test",
            max_retries=3,
            base_delay=0.0,
            logger=logger,
        )

    assert exc_info.value is exc
    # Must have been called exactly once — no retries
    assert call_count == 1


@pytest.mark.asyncio
async def test_5xx_is_retried_up_to_max(monkeypatch: pytest.MonkeyPatch) -> None:
    """5xx responses must be retried up to max_retries before raising."""
    call_count = 0
    exc = _make_status_error(503)

    async def _failing_request(**_kwargs):  # noqa: ANN003
        nonlocal call_count
        call_count += 1
        raise exc

    # Skip actual sleep so the test runs instantly
    monkeypatch.setattr(_http_mod.asyncio, "sleep", AsyncMock())

    fake_client = MagicMock(spec=httpx.AsyncClient)
    fake_client.request = AsyncMock(side_effect=_failing_request)

    logger = logging.getLogger("test")
    with pytest.raises(httpx.HTTPStatusError):
        await request_with_backoff(
            fake_client,
            "GET",
            "https://example.com/test",
            max_retries=2,
            base_delay=1.0,
            logger=logger,
        )

    # 1 initial + 2 retries = 3 total calls
    assert call_count == 3


@pytest.mark.asyncio
async def test_success_after_5xx_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Request succeeds after one transient 5xx, returning the response."""
    call_count = 0
    exc = _make_status_error(500)

    ok_response = MagicMock(spec=httpx.Response)
    ok_response.raise_for_status = MagicMock()  # does not raise

    async def _flaky_request(**_kwargs):  # noqa: ANN003
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise exc
        return ok_response

    monkeypatch.setattr(_http_mod.asyncio, "sleep", AsyncMock())

    fake_client = MagicMock(spec=httpx.AsyncClient)
    fake_client.request = AsyncMock(side_effect=_flaky_request)

    logger = logging.getLogger("test")
    result = await request_with_backoff(
        fake_client,
        "GET",
        "https://example.com/test",
        max_retries=2,
        base_delay=1.0,
        logger=logger,
    )

    assert result is ok_response
    assert call_count == 2
