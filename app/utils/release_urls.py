from __future__ import annotations

import re
from datetime import date

from app.domain.enums import ReleaseType


def bls_archive_url(series: str, release_date: date) -> str:
    return (
        "https://www.bls.gov/news.release/archives/"
        f"{series}_{release_date.strftime('%m%d%Y')}.htm"
    )


def fomc_statement_url(release_date: date) -> str:
    return (
        "https://www.federalreserve.gov/newsevents/pressreleases/"
        f"monetary{release_date.strftime('%Y%m%d')}a.htm"
    )


def gdp_reference_quarter_and_year(release_date: date) -> tuple[int, int]:
    month = release_date.month
    if month <= 3:
        return 4, release_date.year - 1
    if month <= 6:
        return 1, release_date.year
    if month <= 9:
        return 2, release_date.year
    return 3, release_date.year


def bea_gdp_advance_url(release_date: date) -> str:
    quarter, gdp_year = gdp_reference_quarter_and_year(release_date)
    quarter_name = {1: "first", 2: "second", 3: "third", 4: "fourth"}[quarter]
    slug = f"gross-domestic-product-{quarter_name}-quarter-{gdp_year}-advance-estimate"
    return f"https://www.bea.gov/news/{release_date.year}/{slug}"


def looks_like_schedule_url(url: str) -> bool:
    lowered = url.lower()
    return (
        "/schedule/" in lowered
        or lowered.endswith("/schedule")
        or "bea.gov/news/schedule" in lowered
        or "fomccalendars" in lowered
    )


def extract_release_date_from_id(release_id: str) -> date | None:
    match = re.search(r"(20\d{2}-\d{2}-\d{2})$", release_id)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def resolve_release_content_url(
    *,
    release_type: str,
    release_id: str,
    existing_source_url: str,
) -> str:
    if not looks_like_schedule_url(existing_source_url):
        return existing_source_url
    release_date = extract_release_date_from_id(release_id)
    if release_date is None:
        return existing_source_url
    if release_type == ReleaseType.CPI.value:
        return bls_archive_url("cpi", release_date)
    if release_type == ReleaseType.NFP.value:
        return bls_archive_url("empsit", release_date)
    if release_type == ReleaseType.GDP_ADVANCE.value:
        return bea_gdp_advance_url(release_date)
    if release_type == ReleaseType.FOMC.value:
        return fomc_statement_url(release_date)
    return existing_source_url
