from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.manual_release_seed_service import ManualReleaseSeedService


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


@pytest.mark.asyncio
async def test_manual_seed_service_parses_yaml_and_upserts(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "manual_releases.yaml"
    path.write_text(
        """
releases:
  - release_type: CPI
    release_name: Consumer Price Index
    scheduled_time_utc: "2026-06-11T21:30:00+09:00"
    source_url: "manual://cpi"
  - release_type: FOMC
    release_name: FOMC Rate Decision
    scheduled_time_utc: "2026-06-17T18:00:00Z"
    source_url: "manual://fomc"
        """.strip(),
        encoding="utf-8",
    )
    store: dict[str, dict[str, object]] = {}

    class _ReleaseRepo:
        def __init__(self, session) -> None:
            self.session = session

        async def get_by_id(self, release_id: str):
            row = store.get(release_id)
            if row is None:
                return None
            return SimpleNamespace(**row)

        async def upsert_release(self, **kwargs):
            store[kwargs["release_id"]] = kwargs

    monkeypatch.setattr("app.services.manual_release_seed_service.ReleaseRepository", _ReleaseRepo)
    service = ManualReleaseSeedService()
    session = _FakeSession()

    first = await service.seed_from_file(session, path)
    second = await service.seed_from_file(session, path)

    assert first.inserted == 2
    assert first.updated == 0
    assert second.inserted == 0
    assert second.updated == 2
    assert len(store) == 2
    rows = list(store.values())
    assert all(str(row["release_type"]) in {"CPI", "FOMC"} for row in rows)
    cpi_row = next(row for row in rows if row["release_type"] == "CPI")
    assert cpi_row["scheduled_time_utc"] == datetime(2026, 6, 11, 12, 30, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_manual_seed_cli_mode_prints_summary(monkeypatch, tmp_path: Path, capsys) -> None:
    path = tmp_path / "manual_releases.yaml"
    path.write_text(
        """
releases:
  - release_type: NFP
    release_name: Employment Situation
    scheduled_time_utc: "2026-06-05T12:30:00Z"
    source_url: "manual://nfp"
        """.strip(),
        encoding="utf-8",
    )
    store: dict[str, dict[str, object]] = {}

    class _ReleaseRepo:
        def __init__(self, session) -> None:
            self.session = session

        async def get_by_id(self, release_id: str):
            row = store.get(release_id)
            if row is None:
                return None
            return SimpleNamespace(**row)

        async def upsert_release(self, **kwargs):
            store[kwargs["release_id"]] = kwargs

    monkeypatch.setattr("app.services.manual_release_seed_service.ReleaseRepository", _ReleaseRepo)

    from app.main import run_seed_releases_mode

    runtime = SimpleNamespace(session_factory=_SessionFactory(_FakeSession()))
    await run_seed_releases_mode(runtime, str(path))
    await run_seed_releases_mode(runtime, str(path))

    output = capsys.readouterr().out
    assert "seed_releases: inserted=1 updated=0" in output
    assert "seed_releases: inserted=0 updated=1" in output


@pytest.mark.asyncio
async def test_manual_seed_rejects_unsupported_release_type(tmp_path: Path) -> None:
    path = tmp_path / "manual_releases.yaml"
    path.write_text(
        """
releases:
  - release_type: PPI
    release_name: Producer Price Index
    scheduled_time_utc: "2026-06-11T12:30:00Z"
    source_url: "manual://ppi"
        """.strip(),
        encoding="utf-8",
    )
    service = ManualReleaseSeedService()
    with pytest.raises(ValueError, match="unsupported release_type"):
        await service.seed_from_file(_FakeSession(), path)
