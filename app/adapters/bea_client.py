from __future__ import annotations

import logging

import httpx

from app.adapters._http import request_with_backoff
from app.config import Settings, get_settings


class BEAClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.logger = logging.getLogger(__name__)
        self._client = httpx.AsyncClient(
            timeout=self.settings.request_timeout_seconds,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": f"{self.settings.bea_base_url}/",
            },
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def fetch_schedule_html(self) -> str:
        url = f"{self.settings.bea_base_url}/news/schedule"
        response = await request_with_backoff(
            self._client,
            "GET",
            url,
            max_retries=self.settings.max_retries,
            base_delay=self.settings.backoff_base_seconds,
            logger=self.logger,
        )
        return response.text

    async def fetch_release_page(self, path_or_url: str) -> str:
        url = path_or_url if path_or_url.startswith("http") else f"{self.settings.bea_base_url}{path_or_url}"
        response = await request_with_backoff(
            self._client,
            "GET",
            url,
            max_retries=self.settings.max_retries,
            base_delay=self.settings.backoff_base_seconds,
            logger=self.logger,
        )
        return response.text
