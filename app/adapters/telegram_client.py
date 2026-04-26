from __future__ import annotations

import logging

import httpx

from app.adapters._http import request_with_backoff
from app.config import Settings, get_settings


class TelegramClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.logger = logging.getLogger(__name__)
        self._client = httpx.AsyncClient(timeout=self.settings.request_timeout_seconds)

    async def close(self) -> None:
        await self._client.aclose()

    async def send_message(self, message: str, chat_id: str | None = None) -> bool:
        target_chat_id = (chat_id or self.settings.telegram_chat_id).strip()
        if not self.settings.telegram_bot_token or not target_chat_id:
            self.logger.warning("telegram_config_missing")
            return False
        token = self.settings.telegram_bot_token
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        response = await request_with_backoff(
            self._client,
            "POST",
            url,
            json={"chat_id": target_chat_id, "text": message},
            max_retries=self.settings.max_retries,
            base_delay=self.settings.backoff_base_seconds,
            logger=self.logger,
            log_url="https://api.telegram.org/bot<redacted>/sendMessage",
            redact_values=(token,),
        )
        payload = response.json()
        return bool(payload.get("ok"))
