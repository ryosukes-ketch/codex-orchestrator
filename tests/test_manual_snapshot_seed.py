from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.manual_snapshot_seed_service import ManualSnapshotSeedService


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
    markets: dict[str, dict[str, object]] = {
        "CPI-DEV-APR19-ABOVE-3.1": {"market_ticker": "CPI-DEV-APR19-ABOVE-3.1"},
        "FOMC-DEV-JUN17-HOLD": {"market_ticker": "FOMC-DEV-JUN17-HOLD"},
    }
    snapshots: dict[tuple[str, datetime], dict[str, object]] = {}
    return markets, snapshots


def _build_fake_repositories(markets: dict[str, dict[str, object]], snapshots: dict[tuple[str, datetime], dict[str, object]]):
    class _MarketRepo:
        def __init__(self, session) -> None:
            self.session = session

        async def get_by_ticker(self, market_ticker: str):
            row = markets.get(market_ticker)
            if row is None:
                return None
            return SimpleNamespace(**row)

    class _SnapshotRepo:
        def __init__(self, session) -> None:
            self.session = session

        async def get_by_market_and_time(self, market_ticker: str, captured_at_utc: datetime):
            row = snapshots.get((market_ticker, captured_at_utc))
            if row is None:
                return None
            return SimpleNamespace(**row)

        async def upsert_snapshot(self, **kwargs):
            snapshots[(kwargs["market_ticker"], kwargs["captured_at_utc"])] = kwargs

    return _MarketRepo, _SnapshotRepo


@pytest.mark.asyncio
async def test_manual_snapshot_seed_parses_and_computes_mid_spread(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "manual_snapshots.yaml"
    path.write_text(
        """
snapshots:
  - market_ticker: CPI-DEV-APR19-ABOVE-3.1
    captured_at_utc: "2026-04-19T12:20:00Z"
    yes_bid: 0.44
    yes_ask: 0.48
        """.strip(),
        encoding="utf-8",
    )
    markets, snapshots = _build_repo_stores()
    market_repo, snapshot_repo = _build_fake_repositories(markets, snapshots)
    monkeypatch.setattr("app.services.manual_snapshot_seed_service.MarketRepository", market_repo)
    monkeypatch.setattr("app.services.manual_snapshot_seed_service.SnapshotRepository", snapshot_repo)

    service = ManualSnapshotSeedService()
    summary = await service.seed_from_file(_FakeSession(), path)

    assert summary.inserted == 1
    assert summary.updated == 0
    assert summary.skipped == 0
    row = next(iter(snapshots.values()))
    assert row["mid"] == pytest.approx(0.46)
    assert row["spread"] == pytest.approx(0.04)
    assert row["volume"] == 0.0


@pytest.mark.asyncio
async def test_manual_snapshot_seed_duplicate_key_updates_not_duplicates(monkeypatch, tmp_path: Path) -> None:
    path_a = tmp_path / "snapshots_a.yaml"
    path_b = tmp_path / "snapshots_b.yaml"
    path_a.write_text(
        """
snapshots:
  - market_ticker: CPI-DEV-APR19-ABOVE-3.1
    captured_at_utc: "2026-04-19T12:29:00Z"
    yes_bid: 0.48
    yes_ask: 0.52
    volume: 170
        """.strip(),
        encoding="utf-8",
    )
    path_b.write_text(
        """
snapshots:
  - market_ticker: CPI-DEV-APR19-ABOVE-3.1
    captured_at_utc: "2026-04-19T12:29:00Z"
    yes_bid: 0.49
    yes_ask: 0.53
    volume: 180
        """.strip(),
        encoding="utf-8",
    )
    markets, snapshots = _build_repo_stores()
    market_repo, snapshot_repo = _build_fake_repositories(markets, snapshots)
    monkeypatch.setattr("app.services.manual_snapshot_seed_service.MarketRepository", market_repo)
    monkeypatch.setattr("app.services.manual_snapshot_seed_service.SnapshotRepository", snapshot_repo)
    service = ManualSnapshotSeedService()

    first = await service.seed_from_file(_FakeSession(), path_a)
    second = await service.seed_from_file(_FakeSession(), path_b)

    assert first.inserted == 1
    assert second.updated == 1
    assert len(snapshots) == 1
    row = next(iter(snapshots.values()))
    assert row["yes_bid"] == 0.49
    assert row["volume"] == 180.0


@pytest.mark.asyncio
async def test_manual_snapshot_seed_skips_noop_duplicate(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "manual_snapshots.yaml"
    path.write_text(
        """
snapshots:
  - market_ticker: CPI-DEV-APR19-ABOVE-3.1
    captured_at_utc: "2026-04-19T12:31:00Z"
    yes_bid: 0.54
    yes_ask: 0.58
    volume: 220
        """.strip(),
        encoding="utf-8",
    )
    markets, snapshots = _build_repo_stores()
    market_repo, snapshot_repo = _build_fake_repositories(markets, snapshots)
    monkeypatch.setattr("app.services.manual_snapshot_seed_service.MarketRepository", market_repo)
    monkeypatch.setattr("app.services.manual_snapshot_seed_service.SnapshotRepository", snapshot_repo)
    service = ManualSnapshotSeedService()

    await service.seed_from_file(_FakeSession(), path)
    second = await service.seed_from_file(_FakeSession(), path)

    assert second.inserted == 0
    assert second.updated == 0
    assert second.skipped == 1
    assert len(snapshots) == 1


@pytest.mark.asyncio
async def test_manual_snapshot_seed_fails_for_unknown_market(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "manual_snapshots.yaml"
    path.write_text(
        """
snapshots:
  - market_ticker: UNKNOWN-MKT
    captured_at_utc: "2026-04-19T12:31:00Z"
    yes_bid: 0.54
    yes_ask: 0.58
        """.strip(),
        encoding="utf-8",
    )
    markets, snapshots = _build_repo_stores()
    market_repo, snapshot_repo = _build_fake_repositories(markets, snapshots)
    monkeypatch.setattr("app.services.manual_snapshot_seed_service.MarketRepository", market_repo)
    monkeypatch.setattr("app.services.manual_snapshot_seed_service.SnapshotRepository", snapshot_repo)
    service = ManualSnapshotSeedService()

    with pytest.raises(ValueError, match="unknown market_ticker"):
        await service.seed_from_file(_FakeSession(), path)


@pytest.mark.asyncio
async def test_manual_snapshot_seed_cli_mode_prints_summary(monkeypatch, tmp_path: Path, capsys) -> None:
    path = tmp_path / "manual_snapshots.yaml"
    path.write_text(
        """
snapshots:
  - market_ticker: CPI-DEV-APR19-ABOVE-3.1
    captured_at_utc: "2026-04-19T12:31:00Z"
    yes_bid: 0.54
    yes_ask: 0.58
        """.strip(),
        encoding="utf-8",
    )
    markets, snapshots = _build_repo_stores()
    market_repo, snapshot_repo = _build_fake_repositories(markets, snapshots)
    monkeypatch.setattr("app.services.manual_snapshot_seed_service.MarketRepository", market_repo)
    monkeypatch.setattr("app.services.manual_snapshot_seed_service.SnapshotRepository", snapshot_repo)

    from app.main import run_seed_snapshots_mode

    runtime = SimpleNamespace(session_factory=_SessionFactory(_FakeSession()))
    await run_seed_snapshots_mode(runtime, str(path))
    await run_seed_snapshots_mode(runtime, str(path))

    output = capsys.readouterr().out
    assert "seed_snapshots: inserted=1 updated=0 skipped=0" in output
    assert "seed_snapshots: inserted=0 updated=0 skipped=1" in output


@pytest.mark.asyncio
async def test_seeded_snapshots_visible_to_downstream_signal_flow(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "manual_snapshots.yaml"
    release_time = datetime(2026, 4, 19, 12, 30, tzinfo=timezone.utc)
    path.write_text(
        f"""
snapshots:
  - market_ticker: CPI-DEV-APR19-ABOVE-3.1
    captured_at_utc: "{(release_time - timedelta(minutes=59)).isoformat().replace('+00:00', 'Z')}"
    yes_bid: 0.38
    yes_ask: 0.42
  - market_ticker: CPI-DEV-APR19-ABOVE-3.1
    captured_at_utc: "{(release_time - timedelta(minutes=10)).isoformat().replace('+00:00', 'Z')}"
    yes_bid: 0.44
    yes_ask: 0.48
  - market_ticker: CPI-DEV-APR19-ABOVE-3.1
    captured_at_utc: "{(release_time - timedelta(minutes=1)).isoformat().replace('+00:00', 'Z')}"
    yes_bid: 0.48
    yes_ask: 0.52
        """.strip(),
        encoding="utf-8",
    )
    markets, snapshots = _build_repo_stores()
    market_repo, snapshot_repo = _build_fake_repositories(markets, snapshots)
    monkeypatch.setattr("app.services.manual_snapshot_seed_service.MarketRepository", market_repo)
    monkeypatch.setattr("app.services.manual_snapshot_seed_service.SnapshotRepository", snapshot_repo)
    service = ManualSnapshotSeedService()
    await service.seed_from_file(_FakeSession(), path)

    from app.services.signal_engine import SignalEngine

    rows = [
        SimpleNamespace(**row)
        for _, row in sorted(snapshots.items(), key=lambda pair: pair[0][1])
    ]
    signals = SignalEngine().detect_signals(
        release_id="REL-CPI-1",
        release_time_utc=release_time,
        market_ticker="CPI-DEV-APR19-ABOVE-3.1",
        snapshots=rows,
        group_snapshots={"CPI-DEV-APR19-ABOVE-3.1": rows},
        threshold=None,
        actual_value_num=None,
    )
    assert any(item.signal_type.value == "PRE_RELEASE_PRESSURE" for item in signals)
