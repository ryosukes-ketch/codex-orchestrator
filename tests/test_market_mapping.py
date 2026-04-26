from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.market_discovery import MarketDiscoveryService


class _FakeKalshiClient:
    def __init__(self, markets: list[dict]) -> None:
        self._markets = markets

    async def list_markets(self, limit: int = 1000) -> list[dict]:
        return self._markets


@pytest.mark.asyncio
async def test_market_mapping_assigns_release_types(monkeypatch, fixtures_dir) -> None:
    markets = json.loads((fixtures_dir / "kalshi_markets.json").read_text(encoding="utf-8"))["markets"]
    client = _FakeKalshiClient(markets)
    service = MarketDiscoveryService(client, mapping_path=Path("config/market_mapping.yaml"))
    saved: list[dict] = []

    class _FakeRepo:
        def __init__(self, session) -> None:
            self.session = session

        async def upsert_market(self, **kwargs):
            saved.append(kwargs)

    class _FakeSession:
        async def commit(self) -> None:
            return None

    monkeypatch.setattr("app.services.market_discovery.MarketRepository", _FakeRepo)
    count = await service.discover_and_store(_FakeSession())
    assert count == 3
    mapped = {item["market_ticker"]: item for item in saved}
    assert mapped["CPI-APR26-ABOVE-3.1"]["release_type"] == "CPI"
    assert mapped["NFP-MAY26-ABOVE-150K"]["release_type"] == "NFP"
    assert mapped["SPORTS-IGNORE"]["release_type"] is None


def test_market_mapping_default_path_independent_of_cwd(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    service = MarketDiscoveryService(_FakeKalshiClient([]))
    assert service.mapping_path.exists()
    assert service.mapping_path.name == "market_mapping.yaml"
