from __future__ import annotations

import logging
from typing import Any

import httpx

from app.adapters._http import request_with_backoff
from app.config import Settings, get_settings


class KalshiClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.logger = logging.getLogger(__name__)
        self._client = httpx.AsyncClient(timeout=self.settings.request_timeout_seconds)

    async def close(self) -> None:
        await self._client.aclose()

    async def list_events(self, limit: int = 200) -> list[dict[str, Any]]:
        url = f"{self.settings.kalshi_base_url}/events"
        response = await request_with_backoff(
            self._client,
            "GET",
            url,
            params={"limit": limit},
            max_retries=self.settings.max_retries,
            base_delay=self.settings.backoff_base_seconds,
            logger=self.logger,
        )
        payload = response.json()
        return payload.get("events", payload.get("data", []))

    async def list_markets(self, event_ticker: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        url = f"{self.settings.kalshi_base_url}/markets"
        params: dict[str, Any] = {"limit": limit}
        if event_ticker:
            params["event_ticker"] = event_ticker
        response = await request_with_backoff(
            self._client,
            "GET",
            url,
            params=params,
            max_retries=self.settings.max_retries,
            base_delay=self.settings.backoff_base_seconds,
            logger=self.logger,
        )
        payload = response.json()
        return payload.get("markets", payload.get("data", []))

    async def get_orderbook(self, market_ticker: str) -> dict[str, Any]:
        url = f"{self.settings.kalshi_base_url}/markets/{market_ticker}/orderbook"
        response = await request_with_backoff(
            self._client,
            "GET",
            url,
            max_retries=self.settings.max_retries,
            base_delay=self.settings.backoff_base_seconds,
            logger=self.logger,
        )
        return response.json()

    async def get_market(self, market_ticker: str) -> dict[str, Any]:
        url = f"{self.settings.kalshi_base_url}/markets/{market_ticker}"
        response = await request_with_backoff(
            self._client,
            "GET",
            url,
            max_retries=self.settings.max_retries,
            base_delay=self.settings.backoff_base_seconds,
            logger=self.logger,
        )
        payload = response.json()
        return payload.get("market", payload)
