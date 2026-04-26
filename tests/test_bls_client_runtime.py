from __future__ import annotations

import pytest

from app.adapters.bls_client import BLSClient
from app.config import Settings


class _Response:
    def __init__(self, text: str = "<html></html>") -> None:
        self.text = text


@pytest.mark.asyncio
async def test_bls_client_uses_browser_like_headers(monkeypatch) -> None:
    settings = Settings(
        DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/test",
        BLS_BASE_URL="https://www.bls.gov",
    )
    captured: dict[str, object] = {}

    async def _fake_request_with_backoff(client, method, url, **kwargs):
        _ = kwargs
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = {k.lower(): v for k, v in client.headers.items()}
        captured["follow_redirects"] = client.follow_redirects
        return _Response("<html>ok</html>")

    monkeypatch.setattr("app.adapters.bls_client.request_with_backoff", _fake_request_with_backoff)
    client = BLSClient(settings=settings)
    try:
        html = await client.fetch_cpi_schedule_html()
    finally:
        await client.close()

    assert html == "<html>ok</html>"
    assert captured["method"] == "GET"
    assert str(captured["url"]).endswith("/schedule/news_release/")
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert "mozilla" in str(headers["user-agent"]).lower()
    assert "text/html" in str(headers["accept"]).lower()
    assert str(headers["accept-language"]).lower().startswith("en-us")
    assert str(headers["referer"]).startswith("https://www.bls.gov/")
    assert captured["follow_redirects"] is True
