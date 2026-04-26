from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.manual_market_seed_service import ManualMarketSeedService


class _FakeSession:
    async def commit(self) -> None:
        return None


class _SessionFactory:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    def __call__(self):
        return self

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return None


def _build_repo_stores():
    releases: dict[str, dict[str, object]] = {
        "REL-CPI-1": {
            "release_id": "REL-CPI-1",
            "release_type": "CPI",
            "release_name": "CPI Dev Seed Near Term",
            "scheduled_time_utc": datetime(2026, 4, 19, 12, 30, tzinfo=timezone.utc),
            "source_url": "manual://release/cpi",
            "status": "scheduled",
        },
        "REL-FOMC-1": {
            "release_id": "REL-FOMC-1",
            "release_type": "FOMC",
            "release_name": "FOMC June 2026",
            "scheduled_time_utc": datetime(2026, 6, 17, 18, 0, tzinfo=timezone.utc),
            "source_url": "manual://release/fomc",
            "status": "scheduled",
        },
    }
    markets: dict[str, dict[str, object]] = {}
    return releases, markets


def _build_fake_repositories(releases: dict[str, dict[str, object]], markets: dict[str, dict[str, object]]):
    class _ReleaseRepo:
        def __init__(self, session) -> None:
            self.session = session

        async def get_by_id(self, release_id: str):
            row = releases.get(release_id)
            if row is None:
                return None
            return SimpleNamespace(**row)

        async def find_by_identity(self, *, release_type: str, release_name: str, scheduled_time_utc: datetime):
            for row in releases.values():
                if (
                    row["release_type"] == release_type
                    and row["release_name"] == release_name
                    and row["scheduled_time_utc"] == scheduled_time_utc
                ):
                    return SimpleNamespace(**row)
            return None

    class _MarketRepo:
        def __init__(self, session) -> None:
            self.session = session

        async def get_by_ticker(self, market_ticker: str):
            row = markets.get(market_ticker)
            if row is None:
                return None
            return SimpleNamespace(**row)

        async def upsert_market(self, **kwargs):
            markets[kwargs["market_ticker"]] = kwargs

    return _ReleaseRepo, _MarketRepo


@pytest.mark.asyncio
async def test_manual_market_seed_parses_yaml_and_upserts(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "manual_markets.yaml"
    path.write_text(
        """
markets:
  - market_ticker: CPI-DEV-1
    title: "Will CPI print above 3.1%?"
    close_time_utc: "2026-04-19T13:00:00Z"
    release_id: REL-CPI-1
    source_url: manual://market/cpi-dev-1
    mapping_payload_json:
      threshold:
        comparator: above
        value: 3.1
  - market_ticker: FOMC-DEV-1
    title: "Will FOMC June 2026 hold rates?"
    close_time_utc: "2026-06-17T18:10:00Z"
    release_type: FOMC
    release_name: FOMC June 2026
    scheduled_time_utc: "2026-06-17T18:00:00Z"
    status: open
        """.strip(),
        encoding="utf-8",
    )
    releases, markets = _build_repo_stores()
    release_repo, market_repo = _build_fake_repositories(releases, markets)
    monkeypatch.setattr("app.services.manual_market_seed_service.ReleaseRepository", release_repo)
    monkeypatch.setattr("app.services.manual_market_seed_service.MarketRepository", market_repo)

    service = ManualMarketSeedService()
    first = await service.seed_from_file(_FakeSession(), path)
    second = await service.seed_from_file(_FakeSession(), path)

    assert first.inserted == 2
    assert first.updated == 0
    assert second.inserted == 0
    assert second.updated == 2
    assert markets["CPI-DEV-1"]["release_type"] == "CPI"
    assert markets["CPI-DEV-1"]["status"] == "active"
    assert markets["CPI-DEV-1"]["mapping_confidence"] == 1.0
    assert markets["CPI-DEV-1"]["mapping_payload_json"]["release_id"] == "REL-CPI-1"
    assert markets["FOMC-DEV-1"]["release_type"] == "FOMC"


@pytest.mark.asyncio
async def test_manual_market_seed_cli_mode_prints_summary(monkeypatch, tmp_path: Path, capsys) -> None:
    path = tmp_path / "manual_markets.yaml"
    path.write_text(
        """
markets:
  - market_ticker: CPI-DEV-CLI
    title: "Will CPI print above 3.0%?"
    close_time_utc: "2026-04-19T13:00:00Z"
    release_id: REL-CPI-1
        """.strip(),
        encoding="utf-8",
    )
    releases, markets = _build_repo_stores()
    release_repo, market_repo = _build_fake_repositories(releases, markets)
    monkeypatch.setattr("app.services.manual_market_seed_service.ReleaseRepository", release_repo)
    monkeypatch.setattr("app.services.manual_market_seed_service.MarketRepository", market_repo)

    from app.main import run_seed_markets_mode

    runtime = SimpleNamespace(session_factory=_SessionFactory(_FakeSession()))
    await run_seed_markets_mode(runtime, str(path))
    await run_seed_markets_mode(runtime, str(path))

    output = capsys.readouterr().out
    assert "seed_markets: inserted=1 updated=0" in output
    assert "seed_markets: inserted=0 updated=1" in output


@pytest.mark.asyncio
async def test_manual_market_seed_fails_for_unknown_release_id(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "manual_markets.yaml"
    path.write_text(
        """
markets:
  - market_ticker: CPI-DEV-UNKNOWN
    title: "Will CPI print above 3.0%?"
    release_id: REL-DOES-NOT-EXIST
        """.strip(),
        encoding="utf-8",
    )
    releases, markets = _build_repo_stores()
    release_repo, market_repo = _build_fake_repositories(releases, markets)
    monkeypatch.setattr("app.services.manual_market_seed_service.ReleaseRepository", release_repo)
    monkeypatch.setattr("app.services.manual_market_seed_service.MarketRepository", market_repo)

    service = ManualMarketSeedService()
    with pytest.raises(ValueError, match="unknown release_id"):
        await service.seed_from_file(_FakeSession(), path)


@pytest.mark.asyncio
async def test_manual_market_seed_uses_release_type_from_release_reference(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "manual_markets.yaml"
    path.write_text(
        """
markets:
  - market_ticker: CPI-DEV-AUTO-TYPE
    title: "Will CPI print above 3.0%?"
    release_id: REL-CPI-1
        """.strip(),
        encoding="utf-8",
    )
    releases, markets = _build_repo_stores()
    release_repo, market_repo = _build_fake_repositories(releases, markets)
    monkeypatch.setattr("app.services.manual_market_seed_service.ReleaseRepository", release_repo)
    monkeypatch.setattr("app.services.manual_market_seed_service.MarketRepository", market_repo)

    service = ManualMarketSeedService()
    summary = await service.seed_from_file(_FakeSession(), path)

    assert summary.inserted == 1
    assert summary.updated == 0
    assert markets["CPI-DEV-AUTO-TYPE"]["release_type"] == "CPI"


@pytest.mark.asyncio
async def test_manual_market_seeded_payload_supports_downstream_threshold_use(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "manual_markets.yaml"
    path.write_text(
        """
markets:
  - market_ticker: CPI-DEV-THRESHOLD
    title: "Will CPI print above 3.1%?"
    release_id: REL-CPI-1
    mapping_payload_json:
      threshold:
        comparator: above
        value: 3.1
        unit: "%"
        """.strip(),
        encoding="utf-8",
    )
    releases, markets = _build_repo_stores()
    release_repo, market_repo = _build_fake_repositories(releases, markets)
    monkeypatch.setattr("app.services.manual_market_seed_service.ReleaseRepository", release_repo)
    monkeypatch.setattr("app.services.manual_market_seed_service.MarketRepository", market_repo)

    service = ManualMarketSeedService()
    await service.seed_from_file(_FakeSession(), path)

    from app.services.replay_service import _threshold_from_mapping

    threshold = _threshold_from_mapping(markets["CPI-DEV-THRESHOLD"]["mapping_payload_json"])
    assert threshold is not None
    assert threshold.comparator == "above"
    assert threshold.value == 3.1
