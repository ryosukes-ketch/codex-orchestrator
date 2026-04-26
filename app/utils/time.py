from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc
ET = ZoneInfo("America/New_York")
JST = ZoneInfo("Asia/Tokyo")


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Naive datetime is not allowed")
    return value.astimezone(UTC)


def parse_iso_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return ensure_utc(parsed)


def et_to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=ET)
    return value.astimezone(UTC)


def fomc_statement_time_utc(meeting_date: date) -> datetime:
    et_dt = datetime.combine(meeting_date, time(hour=14, minute=0), tzinfo=ET)
    return et_dt.astimezone(UTC)


def to_display_timezone(value: datetime, tz_name: str) -> datetime:
    return ensure_utc(value).astimezone(ZoneInfo(tz_name))
