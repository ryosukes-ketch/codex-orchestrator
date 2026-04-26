from __future__ import annotations

import logging

import httpx
import pytest

from app.adapters.telegram_client import TelegramClient
from app.config import Settings


@pytest.mark.asyncio
async def test_telegram_token_is_redacted_in_logs(monkeypatch, caplog) -> None:
    token = "123456:SECRET_TOKEN"
    settings = Settings(
        DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/test",
        TELEGRAM_BOT_TOKEN=token,
        TELEGRAM_CHAT_ID="1234",
        MAX_RETRIES=0,
        BACKOFF_BASE_SECONDS=0.0,
    )
    client = TelegramClient(settings=settings)

    async def _raise_request(*args, **kwargs):
        raise httpx.ConnectError(f"failed to reach https://api.telegram.org/bot{token}/sendMessage")

    monkeypatch.setattr(client._client, "request", _raise_request)
    caplog.set_level(logging.ERROR)

    with pytest.raises(httpx.ConnectError):
        await client.send_message("hello")

    await client.close()
    assert token not in caplog.text
    error_records = [record for record in caplog.records if record.name == "app.adapters.telegram_client"]
    assert error_records
    for record in error_records:
        url = record.__dict__.get("url", "")
        error = record.__dict__.get("error", "")
        assert token not in str(url)
        assert token not in str(error)
    assert any("<redacted>" in str(record.__dict__.get("url", "")) for record in error_records)
