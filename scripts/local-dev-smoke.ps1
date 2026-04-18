param(
    [string]$ApiBaseUrl = "http://127.0.0.1:8000",
    [switch]$CheckReadOnlyApi
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location D:\codex

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string]$Command
    )
    Write-Host $Label
    Invoke-Expression $Command
}

Invoke-Step -Label "[1/6] Seed releases" -Command "python -m app.main seed-releases --file .\config\manual_releases.yaml"
Invoke-Step -Label "[2/6] Seed actuals" -Command "python -m app.main seed-actuals --file .\config\manual_actuals.yaml"
Invoke-Step -Label "[3/6] Seed markets" -Command "python -m app.main seed-markets --file .\config\manual_markets.yaml"
Invoke-Step -Label "[4/6] Seed snapshots" -Command "python -m app.main seed-snapshots --file .\config\manual_snapshots.yaml"
Invoke-Step -Label "[5/6] Run live once in BLS-free dev mode" -Command "python -m app.main live --once --skip-remote-schedules"
Invoke-Step -Label "[6/6] Run monitor once" -Command "python -m app.main monitor --once"

Write-Host "`n[summary] Collecting local DB snapshot (best effort)"

$summaryPayload = $null
try {
    $summaryJson = @'
import asyncio
import json
from sqlalchemy import text

from app.config import get_settings
from app.db.session import get_session_factory

try:
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
except AttributeError:
    pass

async def _collect() -> dict:
    settings = get_settings()
    session_factory = get_session_factory(settings)
    async with session_factory() as session:
        table_counts = {}
        for table in ("release_calendar", "release_actuals", "market_catalog", "market_snapshots", "signals"):
            result = await session.execute(text(f"SELECT COUNT(*) FROM {table}"))
            table_counts[table] = int(result.scalar_one() or 0)

        open_result = await session.execute(
            text("SELECT COUNT(*) FROM monitor_events WHERE status IN ('open','acknowledged','suppressed')"),
        )
        resolved_result = await session.execute(
            text("SELECT COUNT(*) FROM monitor_events WHERE status = 'resolved'")
        )

        signal_rows = await session.execute(
            text(
                "SELECT release_id, market_ticker, signal_type, score, severity, emitted_at_utc "
                "FROM signals ORDER BY emitted_at_utc DESC LIMIT 5"
            )
        )
        open_event_rows = await session.execute(
            text(
                "SELECT monitor_type, status, severity, dedupe_key, updated_at_utc "
                "FROM monitor_events "
                "WHERE status IN ('open','acknowledged','suppressed') "
                "ORDER BY updated_at_utc DESC LIMIT 5"
            ),
        )

        return {
            "counts": {
                "release_calendar": table_counts["release_calendar"],
                "release_actuals": table_counts["release_actuals"],
                "market_catalog": table_counts["market_catalog"],
                "market_snapshots": table_counts["market_snapshots"],
                "signals": table_counts["signals"],
                "open_monitor_events": int(open_result.scalar_one() or 0),
                "resolved_monitor_events": int(resolved_result.scalar_one() or 0),
            },
            "latest_signals": [
                {
                    "release_id": row.release_id,
                    "market_ticker": row.market_ticker,
                    "signal_type": row.signal_type,
                    "score": row.score,
                    "severity": row.severity,
                    "emitted_at_utc": row.emitted_at_utc.isoformat() if row.emitted_at_utc else None,
                }
                for row in signal_rows
            ],
            "latest_open_monitor_events": [
                {
                    "monitor_type": row.monitor_type,
                    "status": row.status,
                    "severity": row.severity,
                    "dedupe_key": row.dedupe_key,
                    "updated_at_utc": row.updated_at_utc.isoformat() if row.updated_at_utc else None,
                }
                for row in open_event_rows
            ],
        }

summary = asyncio.run(_collect())
print(json.dumps(summary, ensure_ascii=True))
'@ | python - 2>$null

    if ($LASTEXITCODE -eq 0 -and $summaryJson) {
        $summaryPayload = $summaryJson | ConvertFrom-Json
    }
} catch {
    Write-Warning "Local DB summary unavailable: $($_.Exception.Message)"
}

if ($summaryPayload -ne $null) {
    Write-Host "`n=== Local Dev Smoke Summary ==="
    Write-Host ("release_calendar:      {0}" -f $summaryPayload.counts.release_calendar)
    Write-Host ("release_actuals:       {0}" -f $summaryPayload.counts.release_actuals)
    Write-Host ("market_catalog:        {0}" -f $summaryPayload.counts.market_catalog)
    Write-Host ("market_snapshots:      {0}" -f $summaryPayload.counts.market_snapshots)
    Write-Host ("signals:               {0}" -f $summaryPayload.counts.signals)
    Write-Host ("open monitor_events:   {0}" -f $summaryPayload.counts.open_monitor_events)
    Write-Host ("resolved monitor_events:{0}" -f $summaryPayload.counts.resolved_monitor_events)

    Write-Host "`nLatest signals (max 5):"
    if (($summaryPayload.latest_signals | Measure-Object).Count -eq 0) {
        Write-Host "  (none)"
    } else {
        foreach ($signal in $summaryPayload.latest_signals) {
            Write-Host ("  - {0} | {1} | {2} | score={3} | severity={4} | {5}" -f `
                $signal.release_id, $signal.market_ticker, $signal.signal_type, $signal.score, $signal.severity, $signal.emitted_at_utc)
        }
    }

    Write-Host "`nOpen monitor events (max 5):"
    if (($summaryPayload.latest_open_monitor_events | Measure-Object).Count -eq 0) {
        Write-Host "  (none)"
    } else {
        foreach ($event in $summaryPayload.latest_open_monitor_events) {
            Write-Host ("  - {0} | {1} | {2} | {3} | {4}" -f `
                $event.monitor_type, $event.status, $event.severity, $event.dedupe_key, $event.updated_at_utc)
        }
    }

    $apiChecksPassed = $true
    if ($CheckReadOnlyApi) {
        Write-Host ("`n[api] Checking read-only surfaces at {0}" -f $ApiBaseUrl)
        try {
            $statusResp = Invoke-RestMethod -Method Get -Uri ("{0}/status" -f $ApiBaseUrl)
            $monitorResp = Invoke-RestMethod -Method Get -Uri ("{0}/monitor?limit=5" -f $ApiBaseUrl)
            $signalsResp = Invoke-RestMethod -Method Get -Uri ("{0}/signals?limit=5" -f $ApiBaseUrl)

            $monitorCount = if ($monitorResp -is [System.Array]) { $monitorResp.Count } elseif ($null -eq $monitorResp) { 0 } else { 1 }
            $signalsCount = if ($signalsResp -is [System.Array]) { $signalsResp.Count } elseif ($null -eq $signalsResp) { 0 } else { 1 }

            Write-Host ("  /status  ok | monitoring_status={0} | signals_count={1}" -f $statusResp.monitoring_status, $statusResp.signals_count)
            Write-Host ("  /monitor ok | returned={0}" -f $monitorCount)
            Write-Host ("  /signals ok | returned={0}" -f $signalsCount)
        } catch {
            $apiChecksPassed = $false
            Write-Warning ("Read-only API surface check failed: {0}" -f $_.Exception.Message)
        }
    }

    $hasCoreSeeds = [int]$summaryPayload.counts.release_calendar -gt 0 -and `
        [int]$summaryPayload.counts.release_actuals -gt 0 -and `
        [int]$summaryPayload.counts.market_catalog -gt 0 -and `
        [int]$summaryPayload.counts.market_snapshots -gt 0
    $hasSignals = [int]$summaryPayload.counts.signals -gt 0
    if ($hasCoreSeeds -and $hasSignals -and $apiChecksPassed) {
        Write-Host "`nLOCAL DEV SMOKE: PASS"
    } else {
        Write-Host "`nLOCAL DEV SMOKE: REVIEW"
    }
} else {
    Write-Host "Local DB summary unavailable (best effort path)."
    Write-Host "`nLOCAL DEV SMOKE: REVIEW"
}
