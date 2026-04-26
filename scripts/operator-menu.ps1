param(
    [string]$ApiBaseUrl = "http://127.0.0.1:8000",
    [string]$Authorization = "Bearer dev-approver-token"
)

$ErrorActionPreference = "SilentlyContinue"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. (Join-Path $repoRoot "scripts\operator-common.ps1")

function Show-Header {
    param([string]$Section = "")
    Clear-Host
    Write-Host ""
    Write-Host "  ============================================" -ForegroundColor Cyan
    Write-Host "    CODEX  Operator  Menu" -ForegroundColor Cyan
    Write-Host "  ============================================" -ForegroundColor Cyan
    Write-Host ("  Server : {0}" -f $ApiBaseUrl) -ForegroundColor DarkGray
    Write-Host ("  Auth   : {0}" -f $Authorization) -ForegroundColor DarkGray
    if ($Section) {
        Write-Host ("  >> {0}" -f $Section) -ForegroundColor Yellow
    }
    Write-Host ""
}

function Wait-Enter {
    Write-Host ""
    Write-Host "  -- Press Enter to return to menu --" -ForegroundColor DarkGray
    [void][System.Console]::ReadLine()
}

function Read-Input {
    param([string]$Label, [string]$Default = "")
    if ($Default) {
        $prompt = ("  {0} [{1}]" -f $Label, $Default)
    } else {
        $prompt = ("  {0}" -f $Label)
    }
    $value = (Read-Host $prompt).Trim()
    if ([string]::IsNullOrWhiteSpace($value)) { return $Default }
    return $value
}

function Resolve-ReadinessReplayContext {
    param([string]$ReadinessManifestPath)

    if ([string]::IsNullOrWhiteSpace($ReadinessManifestPath)) {
        return $null
    }

    $readinessContext = Resolve-ReadinessBundleContext `
        -ReadinessManifestPath $ReadinessManifestPath `
        -RepoRoot $repoRoot
    $suiteContext = $null
    if (-not [string]::IsNullOrWhiteSpace($readinessContext.operator_suite_manifest_path)) {
        $suiteContext = Resolve-OperatorSuiteBundleContext `
            -BundleManifestPath $readinessContext.operator_suite_manifest_path `
            -RepoRoot $repoRoot
    }

    return [pscustomobject]@{
        readiness = $readinessContext
        suite = $suiteContext
    }
}

function Select-CycleContextFromSuite {
    param(
        [Parameter(Mandatory = $true)]$SuiteContext,
        [string]$Mode = ""
    )

    $cycles = @($SuiteContext.cycles)
    if ($cycles.Count -lt 1) {
        throw "Suite manifest does not contain any cycles."
    }

    if ([string]::IsNullOrWhiteSpace($Mode)) {
        if ($cycles.Count -eq 1) {
            return $cycles[0]
        }

        Write-Host ""
        Write-Host "  Cycle modes available:" -ForegroundColor DarkGray
        foreach ($cycle in $cycles) {
            Write-Host ("    - {0} (project_id={1})" -f $cycle.mode, $cycle.project_id) -ForegroundColor DarkGray
        }
        $Mode = Read-Input "Cycle mode" ([string]$cycles[0].mode)
    }

    foreach ($cycle in $cycles) {
        if ([string]$cycle.mode -eq $Mode) {
            return $cycle
        }
    }

    throw ("Cycle mode not found in suite manifest: {0}" -f $Mode)
}

function Resolve-MenuCycleSelection {
    param(
        [string]$ReadinessManifestPath,
        [string]$CycleBundleManifestPath,
        [string]$CycleMode = ""
    )

    if (-not [string]::IsNullOrWhiteSpace($ReadinessManifestPath)) {
        $replay = Resolve-ReadinessReplayContext -ReadinessManifestPath $ReadinessManifestPath
        if ($null -eq $replay.suite) {
            throw "Readiness manifest does not include operator suite bundle artifacts."
        }
        $cycle = Select-CycleContextFromSuite -SuiteContext $replay.suite -Mode $CycleMode
        return [pscustomobject]@{
            readiness = $replay.readiness
            suite = $replay.suite
            cycle = $cycle
            bundle_manifest_path = [string]$cycle.bundle_manifest_path
            project_id = [string]$cycle.project_id
        }
    }

    if ([string]::IsNullOrWhiteSpace($CycleBundleManifestPath)) {
        return $null
    }

    $cycleContext = Resolve-CycleBundleContext -BundleManifestPath $CycleBundleManifestPath
    return [pscustomobject]@{
        readiness = $null
        suite = $null
        cycle = $cycleContext
        bundle_manifest_path = [string]$cycleContext.manifest_path
        project_id = [string]$cycleContext.project_id
    }
}

function Show-ReadinessReplaySummary {
    param([Parameter(Mandatory = $true)]$ReplayContext)

    Write-Host ("  readiness manifest : {0}" -f $ReplayContext.readiness.manifest_path) -ForegroundColor DarkGray
    if (-not [string]::IsNullOrWhiteSpace($ReplayContext.readiness.summary_path)) {
        Write-Host ("  readiness summary  : {0}" -f $ReplayContext.readiness.summary_path) -ForegroundColor DarkGray
    }
    if (-not [string]::IsNullOrWhiteSpace($ReplayContext.readiness.live_smoke_log_path)) {
        Write-Host ("  live smoke log     : {0}" -f $ReplayContext.readiness.live_smoke_log_path) -ForegroundColor DarkGray
    }
    if (-not [string]::IsNullOrWhiteSpace($ReplayContext.readiness.seed_log_path)) {
        Write-Host ("  seed log           : {0}" -f $ReplayContext.readiness.seed_log_path) -ForegroundColor DarkGray
    }
    if ($null -ne $ReplayContext.suite) {
        Write-Host ("  suite manifest     : {0}" -f $ReplayContext.suite.manifest_path) -ForegroundColor DarkGray
        if (-not [string]::IsNullOrWhiteSpace($ReplayContext.suite.summary_path)) {
            Write-Host ("  suite summary      : {0}" -f $ReplayContext.suite.summary_path) -ForegroundColor DarkGray
        }
        if (-not [string]::IsNullOrWhiteSpace($ReplayContext.suite.stage_gate_path)) {
            Write-Host ("  suite stage gate   : {0}" -f $ReplayContext.suite.stage_gate_path) -ForegroundColor DarkGray
        }
        if (-not [string]::IsNullOrWhiteSpace($ReplayContext.suite.handoff_json_path)) {
            Write-Host ("  suite handoff json : {0}" -f $ReplayContext.suite.handoff_json_path) -ForegroundColor DarkGray
        }
    }
}

function Test-ServerHealth {
    try {
        $resp = Invoke-WebRequest -Uri ($ApiBaseUrl + "/health") -UseBasicParsing -TimeoutSec 2
        return ($resp.StatusCode -eq 200 -and $resp.Content -match '"ok"')
    } catch {
        return $false
    }
}

function Show-ServerStatus {
    if (Test-ServerHealth) {
        Write-Host "  [server] RUNNING  $ApiBaseUrl" -ForegroundColor Green
    } else {
        Write-Host "  [server] NOT RUNNING  -- Select [1] to start" -ForegroundColor Red
    }
    Write-Host ""
}

# ---- main loop --------------------------------------------------------------

while ($true) {
    Show-Header
    Show-ServerStatus

    Write-Host "  +------------------------------------------+"
    Write-Host "  |  [1] Start Server  (new window)          |"
    Write-Host "  |  [2] Readiness Gate                      |"
    Write-Host "  +------------------------------------------+"
    Write-Host "  |  [3] Run New Project                     |"
    Write-Host "  |  [4] Check Status                        |"
    Write-Host "  |  [5] Approve                             |"
    Write-Host "  |  [6] Reject                              |"
    Write-Host "  |  [7] Revise  (replanning/rebuilding/...)  |"
    Write-Host "  |  [8] Replan                              |"
    Write-Host "  |  [9] Full Audit                          |"
    Write-Host "  | [10] Full Cycle (approval)               |"
    Write-Host "  | [11] Full Cycle (reject->replan)         |"
    Write-Host "  | [12] Audit Assert                         |"
    Write-Host "  | [13] Cycle Suite (both paths)             |"
    Write-Host "  | [14] Handoff Envelope (from summary)      |"
    Write-Host "  | [15] Stage Gate (from summary)            |"
    Write-Host "  | [16] Readiness + Operator Suite           |"
    Write-Host "  | [17] Stage Report                         |"
    Write-Host "  | [18] OpenClaw Gateway Check               |"
    Write-Host "  | [19] Readiness Replay Summary             |"
    Write-Host "  +------------------------------------------+"
    Write-Host "  |  [0] Exit                                |"
    Write-Host "  +------------------------------------------+"
    Write-Host ""
    $choice = (Read-Host "  Choice").Trim()

    switch ($choice) {

        "1" {
            Show-Header "Start Server"
            Write-Host "  Opening server in a new window..." -ForegroundColor Yellow
            Start-Process powershell.exe -ArgumentList (
                "-NoProfile -ExecutionPolicy Bypass -File `"{0}`"" -f (Join-Path $repoRoot "scripts\start-server.ps1")
            )
            Write-Host "  Done. Wait a few seconds, then run Readiness Gate [2]."
            Wait-Enter
        }

        "2" {
            Show-Header "Readiness Gate"
            & (Join-Path $repoRoot "scripts\release-readiness.ps1") `
                -AutoSeedFullFlow `
                -Authorization $Authorization `
                -ApiBaseUrl $ApiBaseUrl
            Wait-Enter
        }

        "3" {
            Show-Header "Run New Project"
            Write-Host "  Required : Brief file path, Trend provider"
            Write-Host "  Tip: copy brief_template.json, fill in objective + raw_request" -ForegroundColor DarkGray
            Write-Host ""
            $briefPath = Read-Input "Brief file path" ".\examples\briefs\sample_brief.json"
            Write-Host ""
            Write-Host "  Trend provider options:" -ForegroundColor DarkGray
            Write-Host "    mock                     no API key required, no approval gate" -ForegroundColor DarkGray
            Write-Host "    gemini-flash-lite-latest  GEMINI_API_KEY required, approval gate" -ForegroundColor DarkGray
            Write-Host "    openai                   OPENAI_API_KEY required, approval gate" -ForegroundColor DarkGray
            $provider = Read-Input "Trend provider" "gemini-flash-lite-latest"
            Write-Host ""
            & (Join-Path $repoRoot "scripts\operator-run.ps1") `
                -BriefPath $briefPath `
                -TrendProvider $provider `
                -ApiBaseUrl $ApiBaseUrl
            Wait-Enter
        }

        "4" {
            Show-Header "Check Status"
            Write-Host "  Required : Project ID OR cycle/readiness bundle manifest"
            Write-Host "  Optional : Audit JSON input path / summary output path / strict telemetry"
            Write-Host ""
            $readinessManifestPath = Read-Input "Readiness manifest path (blank to skip)" ""
            $bundleManifestPath = Read-Input "Cycle bundle manifest path (blank to skip)" ""
            $bundleContext = $null
            if (
                -not [string]::IsNullOrWhiteSpace($readinessManifestPath) `
                    -or -not [string]::IsNullOrWhiteSpace($bundleManifestPath)
            ) {
                try {
                    $bundleContext = Resolve-MenuCycleSelection `
                        -ReadinessManifestPath $readinessManifestPath `
                        -CycleBundleManifestPath $bundleManifestPath
                    if ($null -ne $bundleContext.readiness) {
                        Show-ReadinessReplaySummary -ReplayContext ([pscustomobject]@{
                            readiness = $bundleContext.readiness
                            suite = $bundleContext.suite
                        })
                    }
                    Write-Host ("  cycle bundle: {0}" -f $bundleContext.bundle_manifest_path) -ForegroundColor DarkGray
                    Write-Host ("  cycle mode  : {0}" -f $bundleContext.cycle.mode) -ForegroundColor DarkGray
                } catch {
                    Write-Host ("  bundle error: {0}" -f $_.Exception.Message) -ForegroundColor Red
                    Wait-Enter
                    continue
                }
            }
            $id = Read-Input "Project ID" ($bundleContext.project_id)
            $auditIn = Read-Input "Audit JSON input path (blank=API fetch)" ""
            $summaryOut = Read-Input "Summary output path (blank to skip)" ""
            $noDerivedRaw = Read-Input "Disable event-derived telemetry? (y/N)" "N"
            if (-not [string]::IsNullOrWhiteSpace($id)) {
                Write-Host ""
                $params = @{
                    ProjectId = $id
                    ApiBaseUrl = $ApiBaseUrl
                }
                if ($null -ne $bundleContext) { $params.BundleManifestPath = $bundleContext.bundle_manifest_path }
                if (-not [string]::IsNullOrWhiteSpace($auditIn)) { $params.AuditJsonPath = $auditIn }
                if (-not [string]::IsNullOrWhiteSpace($summaryOut)) { $params.SummaryOutPath = $summaryOut }
                if ($noDerivedRaw -match "^(?i:y|yes)$") { $params.NoEventDerivedTelemetry = $true }
                & (Join-Path $repoRoot "scripts\operator-status.ps1") @params
            }
            Wait-Enter
        }

        "5" {
            Show-Header "Approve"
            Write-Host "  Required : Project ID"
            Write-Host "  Optional : Approval note, Trend provider (for post-approval run)"
            Write-Host ""
            $id   = Read-Input "Project ID"
            $note = Read-Input "Approval note" "Approved by operator"
            $prov = Read-Input "Trend provider (post-approval)" "mock"
            if (-not [string]::IsNullOrWhiteSpace($id)) {
                Write-Host ""
                & (Join-Path $repoRoot "scripts\operator-approve.ps1") `
                    -ProjectId $id `
                    -Authorization $Authorization `
                    -Note $note `
                    -TrendProvider $prov `
                    -ApiBaseUrl $ApiBaseUrl
            }
            Wait-Enter
        }

        "6" {
            Show-Header "Reject"
            Write-Host "  Required : Project ID, Reason"
            Write-Host ""
            $id     = Read-Input "Project ID"
            $reason = Read-Input "Reason"
            if (-not [string]::IsNullOrWhiteSpace($id) -and -not [string]::IsNullOrWhiteSpace($reason)) {
                Write-Host ""
                & (Join-Path $repoRoot "scripts\operator-reject.ps1") `
                    -ProjectId $id `
                    -Reason $reason `
                    -Authorization $Authorization `
                    -ApiBaseUrl $ApiBaseUrl
            }
            Wait-Enter
        }

        "7" {
            Show-Header "Revise"
            Write-Host "  Required : Project ID"
            Write-Host "  Optional : ResumeMode, Reason"
            Write-Host ""
            $id = Read-Input "Project ID"
            Write-Host ""
            Write-Host "  ResumeMode options:" -ForegroundColor DarkGray
            Write-Host "    replanning   redo the planning phase (-> ready_for_planning)" -ForegroundColor DarkGray
            Write-Host "    rebuilding   redo the build phase" -ForegroundColor DarkGray
            Write-Host "    rereview     redo the review phase" -ForegroundColor DarkGray
            $mode   = Read-Input "ResumeMode" "replanning"
            $reason = Read-Input "Reason" "Revision triggered by operator"
            if (-not [string]::IsNullOrWhiteSpace($id)) {
                Write-Host ""
                & (Join-Path $repoRoot "scripts\operator-revise.ps1") `
                    -ProjectId $id `
                    -ResumeMode $mode `
                    -Reason $reason `
                    -Authorization $Authorization `
                    -ApiBaseUrl $ApiBaseUrl
            }
            Wait-Enter
        }

        "8" {
            Show-Header "Replan"
            Write-Host "  Required : Project ID"
            Write-Host "  Optional : Note"
            Write-Host ""
            $id   = Read-Input "Project ID"
            $note = Read-Input "Note" "Replanning started by operator"
            if (-not [string]::IsNullOrWhiteSpace($id)) {
                Write-Host ""
                & (Join-Path $repoRoot "scripts\operator-replan.ps1") `
                    -ProjectId $id `
                    -Note $note `
                    -Authorization $Authorization `
                    -ApiBaseUrl $ApiBaseUrl
            }
            Wait-Enter
        }

        "9" {
            Show-Header "Full Audit"
            Write-Host "  Required : Project ID OR cycle/readiness bundle manifest"
            Write-Host "  Optional : Audit JSON input path, Output file path"
            Write-Host ""
            $readinessManifestPath = Read-Input "Readiness manifest path (blank to skip)" ""
            $bundleManifestPath = Read-Input "Cycle bundle manifest path (blank to skip)" ""
            $bundleContext = $null
            if (
                -not [string]::IsNullOrWhiteSpace($readinessManifestPath) `
                    -or -not [string]::IsNullOrWhiteSpace($bundleManifestPath)
            ) {
                try {
                    $bundleContext = Resolve-MenuCycleSelection `
                        -ReadinessManifestPath $readinessManifestPath `
                        -CycleBundleManifestPath $bundleManifestPath
                    if ($null -ne $bundleContext.readiness) {
                        Show-ReadinessReplaySummary -ReplayContext ([pscustomobject]@{
                            readiness = $bundleContext.readiness
                            suite = $bundleContext.suite
                        })
                    }
                    Write-Host ("  cycle bundle: {0}" -f $bundleContext.bundle_manifest_path) -ForegroundColor DarkGray
                } catch {
                    Write-Host ("  bundle error: {0}" -f $_.Exception.Message) -ForegroundColor Red
                    Wait-Enter
                    continue
                }
            }
            $id      = Read-Input "Project ID" ($bundleContext.project_id)
            $auditIn = Read-Input "Audit JSON input path (blank=API fetch)" ""
            $outPath = Read-Input "Output file path (blank to skip)" ""
            if (-not [string]::IsNullOrWhiteSpace($id)) {
                Write-Host ""
                $params = @{
                    ProjectId = $id
                    Full = $true
                    ApiBaseUrl = $ApiBaseUrl
                }
                if ($null -ne $bundleContext) { $params.BundleManifestPath = $bundleContext.bundle_manifest_path }
                if (-not [string]::IsNullOrWhiteSpace($auditIn)) { $params.AuditJsonPath = $auditIn }
                if (-not [string]::IsNullOrWhiteSpace($outPath)) { $params.OutPath = $outPath }
                & (Join-Path $repoRoot "scripts\operator-audit.ps1") @params
            }
            Wait-Enter
        }

        "10" {
            Show-Header "Full Cycle (approval)"
            Write-Host "  Required : Brief file path"
            Write-Host "  Optional : Output directory"
            Write-Host ""
            $briefPath = Read-Input "Brief file path" ".\examples\briefs\sample_brief.json"
            $outDir = Read-Input "Output directory (blank=auto)" ""
            Write-Host ""
            if ([string]::IsNullOrWhiteSpace($outDir)) {
                & (Join-Path $repoRoot "scripts\operator-full-cycle.ps1") `
                    -Mode "approval" `
                    -BriefPath $briefPath `
                    -ApiBaseUrl $ApiBaseUrl `
                    -AuthorizationApprover $Authorization
            } else {
                & (Join-Path $repoRoot "scripts\operator-full-cycle.ps1") `
                    -Mode "approval" `
                    -BriefPath $briefPath `
                    -ApiBaseUrl $ApiBaseUrl `
                    -AuthorizationApprover $Authorization `
                    -OutputDir $outDir
            }
            Wait-Enter
        }

        "11" {
            Show-Header "Full Cycle (reject->replan)"
            Write-Host "  Required : Brief file path"
            Write-Host "  Optional : Output directory"
            Write-Host ""
            $briefPath = Read-Input "Brief file path" ".\examples\briefs\sample_brief.json"
            $outDir = Read-Input "Output directory (blank=auto)" ""
            Write-Host ""
            if ([string]::IsNullOrWhiteSpace($outDir)) {
                & (Join-Path $repoRoot "scripts\operator-full-cycle.ps1") `
                    -Mode "reject-replan" `
                    -BriefPath $briefPath `
                    -ApiBaseUrl $ApiBaseUrl `
                    -AuthorizationApprover $Authorization
            } else {
                & (Join-Path $repoRoot "scripts\operator-full-cycle.ps1") `
                    -Mode "reject-replan" `
                    -BriefPath $briefPath `
                    -ApiBaseUrl $ApiBaseUrl `
                    -AuthorizationApprover $Authorization `
                    -OutputDir $outDir
            }
            Wait-Enter
        }

        "12" {
            Show-Header "Audit Assert"
            Write-Host "  Required : Project ID OR cycle/readiness bundle manifest"
            Write-Host "  Optional : Expected status / fail on fallback / max llm fallback / audit JSON"
            Write-Host ""
            $readinessManifestPath = Read-Input "Readiness manifest path (blank to skip)" ""
            $bundleManifestPath = Read-Input "Cycle bundle manifest path (blank to skip)" ""
            $bundleContext = $null
            if (
                -not [string]::IsNullOrWhiteSpace($readinessManifestPath) `
                    -or -not [string]::IsNullOrWhiteSpace($bundleManifestPath)
            ) {
                try {
                    $bundleContext = Resolve-MenuCycleSelection `
                        -ReadinessManifestPath $readinessManifestPath `
                        -CycleBundleManifestPath $bundleManifestPath
                    if ($null -ne $bundleContext.readiness) {
                        Show-ReadinessReplaySummary -ReplayContext ([pscustomobject]@{
                            readiness = $bundleContext.readiness
                            suite = $bundleContext.suite
                        })
                    }
                    Write-Host ("  cycle bundle: {0}" -f $bundleContext.bundle_manifest_path) -ForegroundColor DarkGray
                } catch {
                    Write-Host ("  bundle error: {0}" -f $_.Exception.Message) -ForegroundColor Red
                    Wait-Enter
                    continue
                }
            }
            $id = Read-Input "Project ID" ($bundleContext.project_id)
            $expected = Read-Input "Expected status" "completed"
            $failFallbackRaw = Read-Input "Fail on fallback? (y/N)" "N"
            $maxLlmFallbackRaw = Read-Input "Max LLM transport fallbacks (-1 = ignore)" "-1"
            $auditIn = Read-Input "Audit JSON input path (blank=API fetch)" ""
            $noDerivedRaw = Read-Input "Disable event-derived telemetry? (y/N)" "N"
            if (-not [string]::IsNullOrWhiteSpace($id)) {
                Write-Host ""
                $params = @{
                    ProjectId = $id
                    ApiBaseUrl = $ApiBaseUrl
                    ExpectedStatus = $expected
                    MaxLlmTransportFallbacks = [int]$maxLlmFallbackRaw
                }
                if ($null -ne $bundleContext) { $params.BundleManifestPath = $bundleContext.bundle_manifest_path }
                if (-not [string]::IsNullOrWhiteSpace($auditIn)) { $params.AuditJsonPath = $auditIn }
                if ($failFallbackRaw -match "^(?i:y|yes)$") {
                    $params.FailOnFallback = $true
                }
                if ($noDerivedRaw -match "^(?i:y|yes)$") {
                    $params.NoEventDerivedTelemetry = $true
                }
                & (Join-Path $repoRoot "scripts\operator-audit-assert.ps1") @params
            }
            Wait-Enter
        }

        "13" {
            Show-Header "Cycle Suite (both paths)"
            Write-Host "  Required : Brief file path"
            Write-Host "  Optional : Output directory"
            Write-Host "  Optional : Require stage telemetry / max llm fallback"
            Write-Host ""
            $briefPath = Read-Input "Brief file path" ".\examples\briefs\sample_brief.json"
            $outDir = Read-Input "Output directory (blank=auto)" ""
            $requireTelemetryRaw = Read-Input "Require stage telemetry? (y/N)" "N"
            $maxLlmFallbackRaw = Read-Input "Max suite LLM transport fallbacks (-1 = ignore)" "-1"
            Write-Host ""
            $params = @{
                BriefPath = $briefPath
                ApiBaseUrl = $ApiBaseUrl
                AuthorizationApprover = $Authorization
                MaxSuiteLlmTransportFallbacks = [int]$maxLlmFallbackRaw
            }
            if ($requireTelemetryRaw -match "^(?i:y|yes)$") {
                $params.RequireStageTelemetry = $true
            }
            if ([string]::IsNullOrWhiteSpace($outDir)) {
                & (Join-Path $repoRoot "scripts\operator-cycle-suite.ps1") @params
            } else {
                $params.OutputDir = $outDir
                & (Join-Path $repoRoot "scripts\operator-cycle-suite.ps1") @params
            }
            Wait-Enter
        }

        "14" {
            Show-Header "Handoff Envelope"
            Write-Host "  Required : Readiness manifest OR Bundle manifest OR Cycle summary path OR Suite summary path"
            Write-Host "  Optional : Output JSON path"
            Write-Host ""
            $readinessManifestPath = Read-Input "Readiness manifest path (blank to skip)" ""
            $bundleManifestPath = Read-Input "Bundle manifest path (blank to skip)" ""
            $cyclePath = Read-Input "Cycle summary path (blank to skip)" ""
            $suitePath = Read-Input "Suite summary path (blank to skip)" ""
            $outPath = Read-Input "Output JSON path (blank=auto)" ""
            Write-Host ""
            if (-not [string]::IsNullOrWhiteSpace($readinessManifestPath)) {
                try {
                    $replay = Resolve-ReadinessReplayContext -ReadinessManifestPath $readinessManifestPath
                    Show-ReadinessReplaySummary -ReplayContext $replay
                    $bundleManifestPath = $replay.suite.manifest_path
                } catch {
                    Write-Host ("  readiness error: {0}" -f $_.Exception.Message) -ForegroundColor Red
                    Wait-Enter
                    continue
                }
            }
            if (
                -not [string]::IsNullOrWhiteSpace($bundleManifestPath) `
                    -or -not [string]::IsNullOrWhiteSpace($cyclePath) `
                    -or -not [string]::IsNullOrWhiteSpace($suitePath)
            ) {
                $params = @{}
                if (-not [string]::IsNullOrWhiteSpace($bundleManifestPath)) { $params.BundleManifestPath = $bundleManifestPath }
                if (-not [string]::IsNullOrWhiteSpace($cyclePath)) { $params.CycleSummaryPath = $cyclePath }
                if (-not [string]::IsNullOrWhiteSpace($suitePath)) { $params.SuiteSummaryPath = $suitePath }
                if (-not [string]::IsNullOrWhiteSpace($outPath)) { $params.OutPath = $outPath }
                & (Join-Path $repoRoot "scripts\operator-handoff-envelope.ps1") @params
            }
            Wait-Enter
        }

        "15" {
            Show-Header "Stage Gate"
            Write-Host "  Required : Readiness manifest OR Bundle manifest OR Summary path (cycle/suite/handoff)"
            Write-Host "  Optional : Max failures / Max fallbacks / Max LLM transport fallbacks"
            Write-Host ""
            $readinessManifestPath = Read-Input "Readiness manifest path (blank to skip)" ""
            $bundleManifestPath = Read-Input "Bundle manifest path (blank to skip)" ""
            $summaryPath = Read-Input "Summary path"
            $maxFailuresRaw = Read-Input "Max stage failures (-1 = ignore)" "-1"
            $maxFallbacksRaw = Read-Input "Max stage fallbacks (-1 = ignore)" "-1"
            $maxLlmFallbacksRaw = Read-Input "Max LLM transport fallbacks (-1 = ignore)" "-1"
            $requireTelemetryRaw = Read-Input "Require stage telemetry? (y/N)" "N"
            $failOnViolationRaw = Read-Input "Fail on violations? (Y/n)" "Y"
            if (-not [string]::IsNullOrWhiteSpace($readinessManifestPath)) {
                try {
                    $replay = Resolve-ReadinessReplayContext -ReadinessManifestPath $readinessManifestPath
                    Show-ReadinessReplaySummary -ReplayContext $replay
                    $bundleManifestPath = $replay.suite.manifest_path
                } catch {
                    Write-Host ("  readiness error: {0}" -f $_.Exception.Message) -ForegroundColor Red
                    Wait-Enter
                    continue
                }
            }
            if (
                -not [string]::IsNullOrWhiteSpace($summaryPath) `
                    -or -not [string]::IsNullOrWhiteSpace($bundleManifestPath)
            ) {
                Write-Host ""
                $params = @{
                    MaxStageFailures = [int]$maxFailuresRaw
                    MaxStageFallbacks = [int]$maxFallbacksRaw
                    MaxLlmTransportFallbacks = [int]$maxLlmFallbacksRaw
                    RequireAllCompleted = $true
                    RequireAuditAssertions = $true
                }
                if (-not [string]::IsNullOrWhiteSpace($bundleManifestPath)) {
                    $params.BundleManifestPath = $bundleManifestPath
                } else {
                    $params.SummaryPath = $summaryPath
                }
                if ($requireTelemetryRaw -match "^(?i:y|yes)$") {
                    $params.RequireStageTelemetry = $true
                }
                & (Join-Path $repoRoot "scripts\operator-stage-gate.ps1") @params
                if (($LASTEXITCODE -ne 0) -and ($failOnViolationRaw -match "^(?i:y|yes)$")) {
                    Write-Host "  Stage gate failed." -ForegroundColor Red
                }
            }
            Wait-Enter
        }

        "16" {
            Show-Header "Readiness + Operator Suite"
            Write-Host "  Optional : strict stage telemetry / fallback budget / gateway check"
            Write-Host ""
            $requireTelemetryRaw = Read-Input "Require stage telemetry? (y/N)" "N"
            $maxFallbacksRaw = Read-Input "Max suite stage fallbacks (-1 = ignore)" "-1"
            $maxLlmFallbacksRaw = Read-Input "Max suite LLM transport fallbacks (-1 = ignore)" "-1"
            $runGatewayCheckRaw = Read-Input "Run OpenClaw gateway check after suite? (y/N)" "N"
            Write-Host ""
            $params = @{
                AutoSeedFullFlow = $true
                Authorization = $Authorization
                ApiBaseUrl = $ApiBaseUrl
                RunOperatorSuite = $true
                OperatorMaxStageFallbacks = [int]$maxFallbacksRaw
                OperatorMaxLlmTransportFallbacks = [int]$maxLlmFallbacksRaw
            }
            if ($requireTelemetryRaw -match "^(?i:y|yes)$") {
                $params.OperatorRequireStageTelemetry = $true
            }
            if ($runGatewayCheckRaw -match "^(?i:y|yes)$") {
                $params.RunOpenClawGatewayCheck = $true
            }
            & (Join-Path $repoRoot "scripts\release-readiness.ps1") @params
            Wait-Enter
        }

        "17" {
            Show-Header "Stage Report"
            Write-Host "  Required : Project ID OR cycle/readiness bundle manifest"
            Write-Host "  Optional : Audit JSON input path / require telemetry"
            Write-Host ""
            $readinessManifestPath = Read-Input "Readiness manifest path (blank to skip)" ""
            $bundleManifestPath = Read-Input "Cycle bundle manifest path (blank to skip)" ""
            $bundleContext = $null
            if (
                -not [string]::IsNullOrWhiteSpace($readinessManifestPath) `
                    -or -not [string]::IsNullOrWhiteSpace($bundleManifestPath)
            ) {
                try {
                    $bundleContext = Resolve-MenuCycleSelection `
                        -ReadinessManifestPath $readinessManifestPath `
                        -CycleBundleManifestPath $bundleManifestPath
                    if ($null -ne $bundleContext.readiness) {
                        Show-ReadinessReplaySummary -ReplayContext ([pscustomobject]@{
                            readiness = $bundleContext.readiness
                            suite = $bundleContext.suite
                        })
                    }
                    Write-Host ("  cycle bundle: {0}" -f $bundleContext.bundle_manifest_path) -ForegroundColor DarkGray
                } catch {
                    Write-Host ("  bundle error: {0}" -f $_.Exception.Message) -ForegroundColor Red
                    Wait-Enter
                    continue
                }
            }
            $id = Read-Input "Project ID" ($bundleContext.project_id)
            $auditIn = Read-Input "Audit JSON input path (blank=API fetch)" ""
            $requireTelemetryRaw = Read-Input "Require stage telemetry? (y/N)" "N"
            $noDerivedRaw = Read-Input "Disable event-derived telemetry? (y/N)" "N"
            $outPath = Read-Input "Output file path (blank to skip)" ""
            if (-not [string]::IsNullOrWhiteSpace($id)) {
                Write-Host ""
                $params = @{
                    ProjectId = $id
                    ApiBaseUrl = $ApiBaseUrl
                }
                if ($null -ne $bundleContext) { $params.BundleManifestPath = $bundleContext.bundle_manifest_path }
                if (-not [string]::IsNullOrWhiteSpace($auditIn)) { $params.AuditJsonPath = $auditIn }
                if ($requireTelemetryRaw -match "^(?i:y|yes)$") { $params.RequireStageTelemetry = $true }
                if ($noDerivedRaw -match "^(?i:y|yes)$") { $params.NoEventDerivedTelemetry = $true }
                if (-not [string]::IsNullOrWhiteSpace($outPath)) { $params.OutPath = $outPath }
                & (Join-Path $repoRoot "scripts\operator-stage-report.ps1") @params
            }
            Wait-Enter
        }

        "18" {
            Show-Header "OpenClaw Gateway Check"
            Write-Host "  Optional : Base URL / Agent ID / Backend override / staging append"
            Write-Host ""
            $baseUrl = Read-Input "Gateway Base URL" ""
            $agentId = Read-Input "Agent ID" "default"
            $backend = Read-Input "Backend override (blank=none)" ""
            $timeoutRaw = Read-Input "TimeoutSec (0=env/default)" "0"
            $probeRaw = Read-Input "ProbeTimeoutSec (0=env/default)" "0"
            $appendRecordRaw = Read-Input "Append staging record? (y/N)" "N"
            $evidencePath = Read-Input "Evidence output path (blank=auto)" ""

            $params = @{
                AgentId = $agentId
                TimeoutSec = [int]$timeoutRaw
                ProbeTimeoutSec = [int]$probeRaw
            }
            if (-not [string]::IsNullOrWhiteSpace($baseUrl)) { $params.GatewayBaseUrl = $baseUrl }
            if (-not [string]::IsNullOrWhiteSpace($backend)) { $params.BackendModel = $backend }
            if (-not [string]::IsNullOrWhiteSpace($evidencePath)) { $params.EvidenceOutPath = $evidencePath }
            if ($appendRecordRaw -match "^(?i:y|yes)$") { $params.AppendStagingRecord = $true }

            & (Join-Path $repoRoot "scripts\openclaw-gateway-check.ps1") @params
            Wait-Enter
        }

        "19" {
            Show-Header "Readiness Replay Summary"
            Write-Host "  Required : readiness-manifest path"
            Write-Host ""
            $readinessManifestPath = Read-Input "Readiness manifest path"
            if (-not [string]::IsNullOrWhiteSpace($readinessManifestPath)) {
                try {
                    $replay = Resolve-ReadinessReplayContext -ReadinessManifestPath $readinessManifestPath
                    Show-ReadinessReplaySummary -ReplayContext $replay
                    if ($null -ne $replay.suite -and $replay.suite.cycles.Count -gt 0) {
                        Write-Host ""
                        Write-Host "  cycle manifests:" -ForegroundColor Yellow
                        foreach ($cycle in @($replay.suite.cycles)) {
                            Write-Host (
                                "    - {0} (project_id={1}) -> {2}" -f
                                $cycle.mode,
                                $cycle.project_id,
                                $cycle.bundle_manifest_path
                            ) -ForegroundColor DarkGray
                        }
                    }
                } catch {
                    Write-Host ("  readiness error: {0}" -f $_.Exception.Message) -ForegroundColor Red
                }
            }
            Wait-Enter
        }

        "0" {
            Write-Host ""
            Write-Host "  Goodbye." -ForegroundColor DarkGray
            Write-Host ""
            exit 0
        }

        default {
            Write-Host ("  Unknown: {0}" -f $choice) -ForegroundColor Red
            Start-Sleep -Milliseconds 700
        }
    }
}
