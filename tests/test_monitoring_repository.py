from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.dialects import postgresql

from app.db.repositories import ReleaseRepository


class _ResultScalars:
    def all(self):
        return []


class _Result:
    def scalars(self):
        return _ResultScalars()


class _CaptureSession:
    def __init__(self) -> None:
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return _Result()


def _compile_sql(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


@pytest.mark.asyncio
async def test_list_due_for_actual_applies_recent_window_bounds() -> None:
    session = _CaptureSession()
    repo = ReleaseRepository(session)  # type: ignore[arg-type]
    due_before = datetime(2026, 6, 20, 0, 0, tzinfo=timezone.utc)
    await repo.list_due_for_actual(due_before_utc=due_before, limit=300)

    sql = _compile_sql(session.statement)
    compiled = session.statement.compile(dialect=postgresql.dialect())
    params = compiled.params

    assert "release_calendar.scheduled_time_utc <=" in sql
    assert "release_calendar.scheduled_time_utc >=" in sql
    assert due_before in params.values()
    assert due_before - timedelta(days=30) in params.values()

    old_release = due_before - timedelta(days=31)
    recent_release = due_before - timedelta(days=5)
    lower_bound = due_before - timedelta(days=30)
    assert old_release < lower_bound
    assert lower_bound <= recent_release <= due_before
