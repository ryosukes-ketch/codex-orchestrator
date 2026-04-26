from __future__ import annotations

import logging
import re
from datetime import date, datetime, time, timezone

from dateutil import parser as date_parser
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.bea_client import BEAClient
from app.adapters.bls_client import BLSClient
from app.adapters.fed_client import FedClient
from app.db.repositories import ReleaseRepository
from app.domain.enums import ReleaseStatus, ReleaseType
from app.utils.release_urls import bea_gdp_advance_url, bls_archive_url, fomc_statement_url
from app.utils.time import ET, fomc_statement_time_utc

LOGGER = logging.getLogger(__name__)


class CalendarIngestor:
    def __init__(self, bls_client: BLSClient, bea_client: BEAClient, fed_client: FedClient) -> None:
        self.bls_client = bls_client
        self.bea_client = bea_client
        self.fed_client = fed_client

    async def ingest(self, session: AsyncSession) -> int:
        repo = ReleaseRepository(session)
        total = 0
        total += await self._ingest_cpi(repo)
        total += await self._ingest_nfp(repo)
        total += await self._ingest_gdp(repo)
        total += await self._ingest_fomc(repo)
        await session.commit()
        return total

    async def _ingest_cpi(self, repo: ReleaseRepository) -> int:
        html = await self.bls_client.fetch_cpi_schedule_html()
        entries = _extract_schedule_dates(html, keywords=("consumer price index", "cpi"))
        count = 0
        for dt in entries:
            scheduled = datetime.combine(dt, time(hour=8, minute=30), tzinfo=ET).astimezone(timezone.utc)
            release_id = f"CPI-{dt.isoformat()}"
            await repo.upsert_release(
                release_id=release_id,
                release_type=ReleaseType.CPI.value,
                release_name="Consumer Price Index",
                scheduled_time_utc=scheduled,
                source_url=bls_archive_url("cpi", dt),
                status=ReleaseStatus.SCHEDULED.value,
            )
            count += 1
        return count

    async def _ingest_nfp(self, repo: ReleaseRepository) -> int:
        html = await self.bls_client.fetch_nfp_schedule_html()
        entries = _extract_schedule_dates(html, keywords=("employment situation", "nonfarm payroll"))
        count = 0
        for dt in entries:
            scheduled = datetime.combine(dt, time(hour=8, minute=30), tzinfo=ET).astimezone(timezone.utc)
            release_id = f"NFP-{dt.isoformat()}"
            await repo.upsert_release(
                release_id=release_id,
                release_type=ReleaseType.NFP.value,
                release_name="Employment Situation",
                scheduled_time_utc=scheduled,
                source_url=bls_archive_url("empsit", dt),
                status=ReleaseStatus.SCHEDULED.value,
            )
            count += 1
        return count

    async def _ingest_gdp(self, repo: ReleaseRepository) -> int:
        html = await self.bea_client.fetch_schedule_html()
        entries = _extract_schedule_dates(html, keywords=("gross domestic product", "gdp"))
        count = 0
        for dt in entries:
            scheduled = datetime.combine(dt, time(hour=8, minute=30), tzinfo=ET).astimezone(timezone.utc)
            release_id = f"GDP_ADVANCE-{dt.isoformat()}"
            await repo.upsert_release(
                release_id=release_id,
                release_type=ReleaseType.GDP_ADVANCE.value,
                release_name="GDP Advance Estimate",
                scheduled_time_utc=scheduled,
                source_url=bea_gdp_advance_url(dt),
                status=ReleaseStatus.SCHEDULED.value,
            )
            count += 1
        return count

    async def _ingest_fomc(self, repo: ReleaseRepository) -> int:
        html = await self.fed_client.fetch_fomc_calendar_html()
        entries = _extract_fomc_dates(html)
        count = 0
        for dt in entries:
            scheduled = fomc_statement_time_utc(dt)
            release_id = f"FOMC-{dt.isoformat()}"
            await repo.upsert_release(
                release_id=release_id,
                release_type=ReleaseType.FOMC.value,
                release_name="FOMC Rate Decision",
                scheduled_time_utc=scheduled,
                source_url=fomc_statement_url(dt),
                status=ReleaseStatus.SCHEDULED.value,
            )
            count += 1
        return count


def _extract_schedule_dates(html: str, keywords: tuple[str, ...]) -> list[date]:
    lowered = html.lower()
    if not any(keyword in lowered for keyword in keywords):
        LOGGER.warning("schedule_keywords_missing", extra={"keywords": list(keywords)})
    date_pattern = re.compile(r"([A-Z][a-z]+\s+\d{1,2},\s+\d{4})")
    seen: set[date] = set()
    for match in date_pattern.finditer(html):
        try:
            parsed = date_parser.parse(match.group(1)).date()
        except (ValueError, TypeError):
            continue
        seen.add(parsed)
    return sorted(seen)


def _extract_fomc_dates(html: str) -> list[date]:
    fallback_year = _extract_fomc_fallback_year(html)
    # Example fragments: "January 30-31", "March 19-20"
    pattern = re.compile(
        r"([A-Z][a-z]+)\s+(\d{1,2})(?:\s*[-–]\s*(\d{1,2}))?(?:,\s*(20\d{2}))?",
        re.IGNORECASE,
    )
    seen: set[date] = set()
    for month, day_a, day_b, maybe_year in pattern.findall(html):
        year = int(maybe_year) if maybe_year else fallback_year
        decision_day = int(day_b) if day_b else int(day_a)
        try:
            parsed = date_parser.parse(f"{month} {decision_day}, {year}").date()
        except ValueError:
            continue
        seen.add(parsed)
    return sorted(seen)


def _extract_fomc_fallback_year(html: str) -> int:
    contextual_patterns = (
        r"(?is)federal open market committee[^0-9]{0,160}(20\d{2})",
        r"(?is)fomc[^0-9]{0,100}(20\d{2})",
        r"(?is)<h[1-6][^>]*>[^<]*(20\d{2})[^<]*fomc[^<]*</h[1-6]>",
        r"(?is)<h[1-6][^>]*>[^<]*fomc[^<]*(20\d{2})[^<]*</h[1-6]>",
    )
    for pattern in contextual_patterns:
        match = re.search(pattern, html)
        if match:
            return int(match.group(1))

    all_years = [int(value) for value in re.findall(r"(20\d{2})", html)]
    if all_years:
        return max(all_years)
    return datetime.now().year
