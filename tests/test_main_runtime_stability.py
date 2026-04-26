from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.main import _close_runtime_safely, _redact_sensitive_url, _run_command_with_cleanup


@pytest.mark.asyncio
async def test_close_runtime_safely_swallows_event_loop_closed_error() -> None:
    class _Runtime:
        async def close(self) -> None:
            raise RuntimeError("Event loop is closed")

    await _close_runtime_safely(_Runtime())  # does not raise


@pytest.mark.asyncio
async def test_monitor_command_error_still_runs_cleanup_once() -> None:
    calls = {"close": 0}

    class _MonitoringService:
        async def run_once(self) -> dict[str, str]:
            return {"status": "error"}

    class _Runtime:
        monitoring_service = _MonitoringService()

        async def close(self) -> None:
            calls["close"] += 1

    args = SimpleNamespace(command="monitor", once=True)
    with pytest.raises(RuntimeError, match="monitor mode failed"):
        await _run_command_with_cleanup(_Runtime(), args)
    assert calls["close"] == 1


def test_redact_sensitive_url_masks_telegram_token() -> None:
    raw = "https://api.telegram.org/bot123456:SECRET/sendMessage"
    assert _redact_sensitive_url(raw) == "https://api.telegram.org/bot<redacted>/sendMessage"
