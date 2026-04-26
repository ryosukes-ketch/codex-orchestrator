from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.domain.enums import ReleaseType
from app.services.actual_parser import ActualParserService
from app.services.calendar_ingestor import CalendarIngestor, _extract_fomc_dates
from app.services.live_runner import LiveRunner
from app.utils.release_urls import resolve_release_content_url


class _FakeBLSClient:
    def __init__(self, cpi_html: str = "", nfp_html: str = "") -> None:
        self._cpi_html = cpi_html
        self._nfp_html = nfp_html
        self.fetched_urls: list[str] = []

    async def fetch_cpi_schedule_html(self) -> str:
        return self._cpi_html

    async def fetch_nfp_schedule_html(self) -> str:
        return self._nfp_html

    async def fetch_release_page(self, url: str) -> str:
        self.fetched_urls.append(url)
        return (
            "<html><body>"
            "<p>The Consumer Price Index for All Urban Consumers increased 3.3 percent over the last 12 months.</p>"
            "</body></html>"
        )


class _FakeBEAClient:
    def __init__(self, html: str = "") -> None:
        self._html = html

    async def fetch_schedule_html(self) -> str:
        return self._html

    async def fetch_release_page(self, path_or_url: str) -> str:
        return "<html><body>Real gross domestic product increased at an annual rate of 2.7 percent.</body></html>"


class _FakeFedClient:
    def __init__(self, html: str = "") -> None:
        self._html = html

    async def fetch_fomc_calendar_html(self) -> str:
        return self._html

    async def fetch_statement_page(self, path_or_url: str) -> str:
        return "<html><body>The Committee decided to maintain the target range at 4.25 to 4.50 percent.</body></html>"


class _FakeRepo:
    def __init__(self) -> None:
        self.rows: list[dict[str, str]] = []

    async def upsert_release(self, **kwargs):
        self.rows.append(kwargs)


class _FakeSession:
    async def commit(self) -> None:
        return None


@pytest.mark.asyncio
async def test_calendar_ingestor_uses_release_content_urls() -> None:
    ingestor = CalendarIngestor(
        bls_client=_FakeBLSClient(
            cpi_html="Consumer Price Index April 10, 2026",
            nfp_html="Employment Situation May 1, 2026",
        ),
        bea_client=_FakeBEAClient(html="Gross Domestic Product June 25, 2026"),
        fed_client=_FakeFedClient(html="June 17-18, 2026"),
    )
    repo = _FakeRepo()
    await ingestor._ingest_cpi(repo)
    await ingestor._ingest_nfp(repo)
    await ingestor._ingest_gdp(repo)
    await ingestor._ingest_fomc(repo)

    source_by_type = {row["release_type"]: row["source_url"] for row in repo.rows}
    assert "schedule/news_release" not in source_by_type[ReleaseType.CPI.value]
    assert source_by_type[ReleaseType.CPI.value].endswith("/news.release/archives/cpi_04102026.htm")
    assert source_by_type[ReleaseType.NFP.value].endswith("/news.release/archives/empsit_05012026.htm")
    assert "gross-domestic-product" in source_by_type[ReleaseType.GDP_ADVANCE.value]
    assert source_by_type[ReleaseType.FOMC.value].endswith("/pressreleases/monetary20260618a.htm")


@pytest.mark.asyncio
async def test_live_actual_ingestion_resolves_schedule_url_to_release_content(monkeypatch) -> None:
    saved_actual: dict[str, object] = {}

    class _ReleaseRepo:
        def __init__(self, session) -> None:
            self.session = session

        async def get_by_id(self, release_id: str):
            return SimpleNamespace(
                release_id=release_id,
                release_type=ReleaseType.CPI.value,
                release_name="Consumer Price Index",
                scheduled_time_utc=datetime(2026, 4, 10, 12, 30, tzinfo=timezone.utc),
                source_url="https://www.bls.gov/schedule/news_release/",
            )

        async def get_actual(self, release_id: str):
            return None

        async def upsert_actual(self, **kwargs):
            saved_actual.update(kwargs)

    monkeypatch.setattr("app.services.live_runner.ReleaseRepository", _ReleaseRepo)
    fake_bls = _FakeBLSClient()
    runner = LiveRunner(
        settings=Settings(DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/test"),
        session_factory=None,  # not used by this direct call
        calendar_ingestor=None,  # not used
        market_discovery=None,  # not used
        market_poller=None,  # not used
        replay_service=None,  # not used
        backfill_service=None,  # not used
        actual_parser=ActualParserService(),
        bls_client=fake_bls,
        bea_client=_FakeBEAClient(),
        fed_client=_FakeFedClient(),
    )
    await runner._ingest_actual_if_missing(_FakeSession(), "CPI-2026-04-10")

    assert fake_bls.fetched_urls
    assert fake_bls.fetched_urls[0].endswith("/news.release/archives/cpi_04102026.htm")
    assert saved_actual["actual_value_num"] == 3.3


def test_fomc_date_extraction_prefers_contextual_year_over_first_year() -> None:
    html = """
    <div>Archive index 2023</div>
    <h2>Federal Open Market Committee 2026 Meeting Calendar</h2>
    <li>January 30-31</li>
    <li>March 18-19</li>
    """
    dates = _extract_fomc_dates(html)
    assert dates[0].isoformat() == "2026-01-31"
    assert dates[1].isoformat() == "2026-03-19"


def test_backward_compat_resolution_for_old_nfp_schedule_url() -> None:
    resolved = resolve_release_content_url(
        release_type=ReleaseType.NFP.value,
        release_id="NFP-2026-05-01",
        existing_source_url="https://www.bls.gov/schedule/news_release/empsit.htm",
    )
    assert resolved.endswith("/news.release/archives/empsit_05012026.htm")


def test_backward_compat_resolution_for_old_fomc_calendar_url() -> None:
    resolved = resolve_release_content_url(
        release_type=ReleaseType.FOMC.value,
        release_id="FOMC-2026-06-18",
        existing_source_url="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
    )
    assert resolved.endswith("/pressreleases/monetary20260618a.htm")


def test_backward_compat_resolution_for_old_bea_schedule_url() -> None:
    resolved = resolve_release_content_url(
        release_type=ReleaseType.GDP_ADVANCE.value,
        release_id="GDP_ADVANCE-2026-06-25",
        existing_source_url="https://www.bea.gov/news/schedule",
    )
    assert "gross-domestic-product-first-quarter-2026-advance-estimate" in resolved
