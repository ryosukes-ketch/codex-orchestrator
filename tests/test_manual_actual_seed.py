from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.manual_actual_seed_service import ManualActualSeedService


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
        "CPI-2026-06-11": {
            "release_id": "CPI-2026-06-11",
            "release_type": "CPI",
            "release_name": "Consumer Price Index",
            "scheduled_time_utc": datetime(2026, 6, 11, 12, 30, tzinfo=timezone.utc),
            "source_url": "manual://release/cpi",
            "status": "scheduled",
        },
        "NFP-2026-06-05": {
            "release_id": "NFP-2026-06-05",
            "release_type": "NFP",
            "release_name": "Employment Situation",
            "scheduled_time_utc": datetime(2026, 6, 5, 12, 30, tzinfo=timezone.utc),
            "source_url": "manual://release/nfp",
            "status": "scheduled",
        },
        "GDP_ADVANCE-2026-06-25": {
            "release_id": "GDP_ADVANCE-2026-06-25",
            "release_type": "GDP_ADVANCE",
            "release_name": "GDP Advance Estimate",
            "scheduled_time_utc": datetime(2026, 6, 25, 12, 30, tzinfo=timezone.utc),
            "source_url": "manual://release/gdp",
            "status": "scheduled",
        },
        "FOMC-2026-06-17": {
            "release_id": "FOMC-2026-06-17",
            "release_type": "FOMC",
            "release_name": "FOMC Rate Decision",
            "scheduled_time_utc": datetime(2026, 6, 17, 18, 0, tzinfo=timezone.utc),
            "source_url": "manual://release/fomc",
            "status": "scheduled",
        },
    }
    actuals: dict[str, dict[str, object]] = {}
    return releases, actuals


def _build_fake_release_repo(releases: dict[str, dict[str, object]], actuals: dict[str, dict[str, object]]):
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

        async def get_actual(self, release_id: str):
            row = actuals.get(release_id)
            if row is None:
                return None
            return SimpleNamespace(**row)

        async def upsert_actual(self, **kwargs):
            actuals[kwargs["release_id"]] = kwargs

    return _ReleaseRepo


@pytest.mark.asyncio
async def test_manual_actual_seed_parses_yaml_and_upserts(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "manual_actuals.yaml"
    path.write_text(
        """
actuals:
  - release_type: CPI
    release_id: CPI-2026-06-11
    actual_value_num: 3.3
    source_url: manual://actual/cpi
  - release_type: FOMC
    release_id: FOMC-2026-06-17
    actual_value_text: "HOLD; target upper bound 4.50"
    source_url: manual://actual/fomc
        """.strip(),
        encoding="utf-8",
    )
    releases, actuals = _build_repo_stores()
    monkeypatch.setattr(
        "app.services.manual_actual_seed_service.ReleaseRepository",
        _build_fake_release_repo(releases, actuals),
    )

    service = ManualActualSeedService()
    first = await service.seed_from_file(_FakeSession(), path)
    second = await service.seed_from_file(_FakeSession(), path)

    assert first.inserted == 2
    assert first.updated == 0
    assert second.inserted == 0
    assert second.updated == 2
    assert actuals["CPI-2026-06-11"]["actual_value_num"] == 3.3
    assert actuals["FOMC-2026-06-17"]["actual_value_num"] is None
    assert actuals["FOMC-2026-06-17"]["actual_value_raw"] == "HOLD; target upper bound 4.50"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("release_type", "release_id", "release_name", "scheduled_time_utc", "value"),
    [
        ("CPI", "CPI-2026-06-11", "Consumer Price Index", "2026-06-11T12:30:00Z", 3.2),
        ("NFP", "NFP-2026-06-05", "Employment Situation", "2026-06-05T12:30:00Z", 175000),
        ("GDP_ADVANCE", "GDP_ADVANCE-2026-06-25", "GDP Advance Estimate", "2026-06-25T12:30:00Z", 2.4),
    ],
)
async def test_manual_actual_seed_numeric_path_for_supported_numeric_releases(
    monkeypatch,
    tmp_path: Path,
    release_type: str,
    release_id: str,
    release_name: str,
    scheduled_time_utc: str,
    value: float,
) -> None:
    path = tmp_path / "manual_actuals.yaml"
    path.write_text(
        f"""
actuals:
  - release_type: {release_type}
    release_name: "{release_name}"
    scheduled_time_utc: "{scheduled_time_utc}"
    actual_value_num: {value}
        """.strip(),
        encoding="utf-8",
    )
    releases, actuals = _build_repo_stores()
    monkeypatch.setattr(
        "app.services.manual_actual_seed_service.ReleaseRepository",
        _build_fake_release_repo(releases, actuals),
    )

    service = ManualActualSeedService()
    summary = await service.seed_from_file(_FakeSession(), path)

    assert summary.inserted == 1
    assert summary.updated == 0
    assert actuals[release_id]["actual_value_num"] == float(value)


@pytest.mark.asyncio
async def test_manual_actual_seed_cli_mode_prints_summary(monkeypatch, tmp_path: Path, capsys) -> None:
    path = tmp_path / "manual_actuals.yaml"
    path.write_text(
        """
actuals:
  - release_type: CPI
    release_id: CPI-2026-06-11
    actual_value_num: 3.4
        """.strip(),
        encoding="utf-8",
    )
    releases, actuals = _build_repo_stores()
    monkeypatch.setattr(
        "app.services.manual_actual_seed_service.ReleaseRepository",
        _build_fake_release_repo(releases, actuals),
    )

    from app.main import run_seed_actuals_mode

    runtime = SimpleNamespace(session_factory=_SessionFactory(_FakeSession()))
    await run_seed_actuals_mode(runtime, str(path))
    await run_seed_actuals_mode(runtime, str(path))

    output = capsys.readouterr().out
    assert "seed_actuals: inserted=1 updated=0" in output
    assert "seed_actuals: inserted=0 updated=1" in output


@pytest.mark.asyncio
async def test_manual_actual_seed_fails_when_release_match_missing(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "manual_actuals.yaml"
    path.write_text(
        """
actuals:
  - release_type: CPI
    release_name: Consumer Price Index
    scheduled_time_utc: "2027-01-01T12:30:00Z"
    actual_value_num: 3.1
        """.strip(),
        encoding="utf-8",
    )
    releases, actuals = _build_repo_stores()
    monkeypatch.setattr(
        "app.services.manual_actual_seed_service.ReleaseRepository",
        _build_fake_release_repo(releases, actuals),
    )

    service = ManualActualSeedService()
    with pytest.raises(ValueError, match="could not be matched to release_calendar"):
        await service.seed_from_file(_FakeSession(), path)


@pytest.mark.asyncio
async def test_manual_actual_seed_rejects_missing_numeric_value_for_cpi(tmp_path: Path) -> None:
    path = tmp_path / "manual_actuals.yaml"
    path.write_text(
        """
actuals:
  - release_type: CPI
    release_id: CPI-2026-06-11
    actual_value_text: "Only text is invalid for CPI"
        """.strip(),
        encoding="utf-8",
    )
    service = ManualActualSeedService()
    with pytest.raises(ValueError, match="requires actual_value_num"):
        await service.seed_from_file(_FakeSession(), path)
