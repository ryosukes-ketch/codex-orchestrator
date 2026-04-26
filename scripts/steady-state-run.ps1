param(
    [ValidateSet("daily", "weekly")]
    [string]$Mode = "daily",
    [string]$LogsRoot = "logs",
    [string]$OutputDir = "",
    [string]$OutPath = "",
    [string]$SummaryOutPath = "",
    [string]$StatePath = "docs/steady_state_runtime_state.json",
    [string]$KnownIssuesPath = "docs/known_issues_register.md",
    [string]$StagingRecordPath = "docs/staging_execution_record.md",
    [string]$WatchlistOwnerAckPath = "docs/steady_state_watchlist_owner_ack.json",
    [int]$MaxConsecutiveEscalateCount = 3,
    [int]$MaxOwnerAssignmentPendingCount = 2,
    [switch]$Zip
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. (Join-Path $PSScriptRoot "operator-common.ps1")

function Get-SteadyStateRunnerExecutable {
    foreach ($candidate in @("pwsh", "powershell")) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($null -ne $cmd) {
            return $cmd.Source
        }
    }
    throw "PowerShell executable (pwsh/powershell) was not found."
}

function Resolve-SteadyOptionalPath {
    param(
        [string]$PathValue,
        [string]$BasePath
    )

    $raw = ([string]$PathValue).Trim()
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return ""
    }
    return Resolve-OperatorAbsolutePath -Path $raw -BasePath $BasePath
}

function New-SteadyDefaultState {
    return [ordered]@{
        last_run_at = ""
        last_status = "never"
        last_cycle_id = ""
        last_checkpoint_manifest = ""
        last_watchlist_manifest = ""
        last_known_issue_update = ""
        consecutive_escalate_count = 0
        open_watch_count = 0
        open_escalate_count = 0
        last_owner_assignment_pending_count = 0
        paused_reason = ""
        consecutive_external_blocker_count = 0
    }
}

function Read-SteadyStateFile {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        return (New-SteadyDefaultState)
    }

    try {
        $parsed = Read-OperatorJsonFile -Path $Path
    } catch {
        return (New-SteadyDefaultState)
    }

    $state = New-SteadyDefaultState
    foreach ($key in @($state.Keys)) {
        $value = Get-OperatorObjectPropertyValue -Object $parsed -Name $key
        if ($null -eq $value) {
            continue
        }
        switch ($key) {
            "consecutive_escalate_count" { $state[$key] = Convert-OperatorToInt -Value $value -Default 0 }
            "open_watch_count" { $state[$key] = Convert-OperatorToInt -Value $value -Default 0 }
            "open_escalate_count" { $state[$key] = Convert-OperatorToInt -Value $value -Default 0 }
            "last_owner_assignment_pending_count" { $state[$key] = Convert-OperatorToInt -Value $value -Default 0 }
            "consecutive_external_blocker_count" { $state[$key] = Convert-OperatorToInt -Value $value -Default 0 }
            default { $state[$key] = [string]$value }
        }
    }
    return $state
}

function Test-SteadyExternalBlockerMessage {
    param([string]$Text)

    $normalized = ([string]$Text).ToLowerInvariant()
    return (
        $normalized.Contains("openclaw") -or
        $normalized.Contains("provider") -or
        $normalized.Contains("credit_balance_too_low") -or
        $normalized.Contains("upstream_rejection") -or
        $normalized.Contains("llm_exception") -or
        $normalized.Contains("connection refused") -or
        $normalized.Contains("timed out")
    )
}

function Invoke-SteadyStateStep {
    param(
        [Parameter(Mandatory = $true)][string]$StepName,
        [Parameter(Mandatory = $true)][string]$ScriptPath,
        [Parameter(Mandatory = $true)][string[]]$Args,
        [Parameter(Mandatory = $true)][string]$RunnerExe,
        [Parameter(Mandatory = $true)][string]$StepLogPath
    )

    $commandArgs = @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        $ScriptPath
    ) + $Args

    $output = & $RunnerExe @commandArgs 2>&1
    $exitCode = $LASTEXITCODE
    $outputText = (@($output | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine).Trim()
    if ([string]::IsNullOrWhiteSpace($outputText)) {
        $outputText = ("[{0}] no output captured" -f $StepName)
    }
    [System.IO.File]::WriteAllText($StepLogPath, $outputText, [System.Text.Encoding]::UTF8)

    if ($exitCode -ne 0) {
        throw ("[{0}] failed (exit={1}). See {2}" -f $StepName, $exitCode, $StepLogPath)
    }

    return [ordered]@{
        step = $StepName
        script_path = $ScriptPath
        args = $Args
        log_path = $StepLogPath
    }
}

function Ensure-KnownIssueDocBaseline {
    param([string]$Path)

    if (Test-Path $Path) {
        return
    }
    $lines = @(
        "# Known Issues Register",
        "",
        "Track launch-phase known issues with deterministic ownership and status transitions.",
        "",
        "## Status vocabulary",
        '- `open`',
        '- `mitigated`',
        '- `resolved`',
        '- `accepted_risk`',
        "",
        "## Register",
        "",
        "| Issue ID | Title | Severity | Status | Owner | First Seen (UTC) | Workaround | Next Action |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
        "",
        "## Update log"
    )
    [System.IO.File]::WriteAllLines($Path, $lines, [System.Text.Encoding]::UTF8)
}

function Ensure-SteadyKnownIssueEntry {
    param(
        [string]$KnownIssuesFile,
        [string]$IssueId,
        [string]$Row,
        [string]$UpdateLogEntry
    )

    Ensure-KnownIssueDocBaseline -Path $KnownIssuesFile
    $content = Get-Content -Raw -Path $KnownIssuesFile
    $alreadyPresent = $content.Contains($IssueId)
    if (-not $alreadyPresent) {
        if ($content -match "(?ms)^## Update log") {
            $content = [regex]::Replace(
                $content,
                "(?ms)^## Update log",
                ($Row + [Environment]::NewLine + [Environment]::NewLine + "## Update log"),
                1
            )
        } else {
            $content = $content.TrimEnd() + [Environment]::NewLine + [Environment]::NewLine + $Row + [Environment]::NewLine
        }
    }

    if (-not $content.Contains($UpdateLogEntry)) {
        if ($content -match "(?ms)^## Update log\s*$") {
            $content = $content.TrimEnd() + [Environment]::NewLine + "- " + $UpdateLogEntry + [Environment]::NewLine
        } elseif ($content -match "(?ms)^## Update log") {
            $content = $content.TrimEnd() + [Environment]::NewLine + "- " + $UpdateLogEntry + [Environment]::NewLine
        } else {
            $content = $content.TrimEnd() + [Environment]::NewLine + [Environment]::NewLine + "## Update log" + [Environment]::NewLine + "- " + $UpdateLogEntry + [Environment]::NewLine
        }
    }
    [System.IO.File]::WriteAllText($KnownIssuesFile, $content, [System.Text.Encoding]::UTF8)
}

function Ensure-StagingDocBaseline {
    param([string]$Path)

    if (Test-Path $Path) {
        return
    }
    $baseline = @(
        "# Staging Execution Record",
        "",
        "## Runtime Loop Entries",
        ""
    )
    [System.IO.File]::WriteAllLines($Path, $baseline, [System.Text.Encoding]::UTF8)
}

$runnerExe = Get-SteadyStateRunnerExecutable
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$cycleId = ("steady-state-run-{0}" -f $timestamp)
$resolvedLogsRoot = Resolve-OperatorAbsolutePath -Path $LogsRoot -BasePath $repoRoot
$resolvedStatePath = Resolve-SteadyOptionalPath -PathValue $StatePath -BasePath $repoRoot
$resolvedKnownIssuesPath = Resolve-SteadyOptionalPath -PathValue $KnownIssuesPath -BasePath $repoRoot
$resolvedStagingPath = Resolve-SteadyOptionalPath -PathValue $StagingRecordPath -BasePath $repoRoot
$resolvedWatchlistOwnerAckPath = Resolve-SteadyOptionalPath -PathValue $WatchlistOwnerAckPath -BasePath $repoRoot

if ([string]::IsNullOrWhiteSpace($resolvedStatePath)) {
    $resolvedStatePath = Join-Path $repoRoot "docs\steady_state_runtime_state.json"
}
if ([string]::IsNullOrWhiteSpace($resolvedKnownIssuesPath)) {
    $resolvedKnownIssuesPath = Join-Path $repoRoot "docs\known_issues_register.md"
}
if ([string]::IsNullOrWhiteSpace($resolvedStagingPath)) {
    $resolvedStagingPath = Join-Path $repoRoot "docs\staging_execution_record.md"
}
if ([string]::IsNullOrWhiteSpace($resolvedWatchlistOwnerAckPath)) {
    $resolvedWatchlistOwnerAckPath = Join-Path $repoRoot "docs\steady_state_watchlist_owner_ack.json"
}

$resolvedOutputDir = ([string]$OutputDir).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedOutputDir)) {
    $resolvedOutputDir = Join-Path $repoRoot ("logs\ga-steady-state\runs\{0}" -f $timestamp)
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = Resolve-OperatorAbsolutePath -Path $resolvedOutputDir -BasePath $repoRoot
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "steady-state-run.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}
if ([string]::IsNullOrWhiteSpace($SummaryOutPath)) {
    $SummaryOutPath = Join-Path $resolvedOutputDir "steady-state-run.summary.json"
} elseif (-not [System.IO.Path]::IsPathRooted($SummaryOutPath)) {
    $SummaryOutPath = Resolve-OperatorAbsolutePath -Path $SummaryOutPath -BasePath $repoRoot
}

$lockPath = Join-Path $resolvedLogsRoot "ga-steady-state\steady-state-run.lock"
$lockAcquired = $false
trap {
    if ($lockAcquired -and (Test-Path $lockPath)) {
        Remove-Item -Path $lockPath -Force -ErrorAction SilentlyContinue
    }
    Write-Error $_
    throw $_
}
$preflightIssues = New-Object System.Collections.Generic.List[string]
$steps = New-Object System.Collections.Generic.List[object]
$knownIssueUpdates = New-Object System.Collections.Generic.List[object]
$recommendedActions = New-Object System.Collections.Generic.List[string]
$paused = $false
$pausedReason = ""
$failureClassification = "none"
$state = Read-SteadyStateFile -Path $resolvedStatePath

if (Test-Path $lockPath) {
    $preflightIssues.Add(("lock file exists: {0}" -f $lockPath)) | Out-Null
}

foreach ($required in @("docs\direction_guard.json", "docs\roadmap.json", "scripts\ga-steady-state-checkpoint-refresh.ps1", "scripts\ga-steady-state-escalation-watchlist-route.ps1")) {
    if (-not (Test-Path (Join-Path $repoRoot $required))) {
        $preflightIssues.Add(("missing required artifact: {0}" -f $required)) | Out-Null
    }
}

$direction = Read-OperatorJsonFile -Path (Join-Path $repoRoot "docs\direction_guard.json")
$roadmap = Read-OperatorJsonFile -Path (Join-Path $repoRoot "docs\roadmap.json")
if ([string]$direction.active_phase -ne "steady_state") {
    $preflightIssues.Add(("direction_guard.active_phase must be steady_state; got {0}" -f [string]$direction.active_phase)) | Out-Null
}
if ([string]$roadmap.current_phase -ne "steady_state") {
    $preflightIssues.Add(("roadmap.current_phase must be steady_state; got {0}" -f [string]$roadmap.current_phase)) | Out-Null
}

$steadyPhase = @($roadmap.phases | Where-Object { [string]$_.id -eq "steady_state" } | Select-Object -First 1)
if ($steadyPhase.Count -eq 0) {
    $preflightIssues.Add("roadmap is missing steady_state phase entry.") | Out-Null
} else {
    $phaseStatus = [string]$steadyPhase[0].status
    if ($phaseStatus -notin @("active", "done")) {
        $preflightIssues.Add(("steady_state phase status must be active/done; got {0}" -f $phaseStatus)) | Out-Null
    }
}

if ($preflightIssues.Count -gt 0) {
    $paused = $true
    $pausedReason = ("preflight_failed: " + (@($preflightIssues.ToArray()) -join "; "))
    $recommendedActions.Add("Resolve preflight issues before rerunning steady-state loop.") | Out-Null
} else {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $lockPath) | Out-Null
    [System.IO.File]::WriteAllText($lockPath, $cycleId, [System.Text.Encoding]::UTF8)
    $lockAcquired = $true
}

$cadenceManifestPath = ""
$cadenceSummaryPath = ""
$checkpointManifestPath = ""
$checkpointSummaryPath = ""
$watchlistManifestPath = ""
$watchlistSummaryPath = ""
$improvementManifestPath = ""
$improvementSummaryPath = ""
$burndownManifestPath = ""
$burndownSummaryPath = ""

try {
    if (-not $paused) {
        if ($Mode -eq "weekly") {
            $cadenceDir = Join-Path $resolvedOutputDir "cadence"
            $cadenceManifestPath = Join-Path $cadenceDir "ga-release-ops-cadence-baseline.manifest.json"
            $cadenceSummaryPath = Join-Path $cadenceDir "ga-release-ops-cadence-baseline.summary.json"
            $steps.Add((Invoke-SteadyStateStep `
                -StepName "cadence_baseline" `
                -ScriptPath (Join-Path $repoRoot "scripts\ga-release-ops-cadence-baseline.ps1") `
                -RunnerExe $runnerExe `
                -StepLogPath (Join-Path $resolvedOutputDir "step-cadence.log") `
                -Args @(
                    "-OutputDir", $cadenceDir,
                    "-OutPath", $cadenceManifestPath,
                    "-SummaryOutPath", $cadenceSummaryPath,
                    "-Zip"
                )
            )) | Out-Null
        }

        $checkpointDir = Join-Path $resolvedOutputDir "checkpoint"
        $checkpointManifestPath = Join-Path $checkpointDir "ga-steady-state-checkpoint-refresh.manifest.json"
        $checkpointSummaryPath = Join-Path $checkpointDir "ga-steady-state-checkpoint-refresh.summary.json"
        $steps.Add((Invoke-SteadyStateStep `
            -StepName "checkpoint_refresh" `
            -ScriptPath (Join-Path $repoRoot "scripts\ga-steady-state-checkpoint-refresh.ps1") `
            -RunnerExe $runnerExe `
            -StepLogPath (Join-Path $resolvedOutputDir "step-checkpoint.log") `
            -Args @(
                "-LogsRoot", $resolvedLogsRoot,
                "-OutputDir", $checkpointDir,
                "-OutPath", $checkpointManifestPath,
                "-SummaryOutPath", $checkpointSummaryPath,
                "-Zip"
            )
        )) | Out-Null

        $watchlistDir = Join-Path $resolvedOutputDir "watchlist"
        $watchlistManifestPath = Join-Path $watchlistDir "ga-steady-state-escalation-watchlist-route.manifest.json"
        $watchlistSummaryPath = Join-Path $watchlistDir "ga-steady-state-escalation-watchlist-route.summary.json"
        $watchlistArgs = @(
            "-CheckpointManifestPath", $checkpointManifestPath,
            "-LogsRoot", $resolvedLogsRoot,
            "-OutputDir", $watchlistDir,
            "-OutPath", $watchlistManifestPath,
            "-SummaryOutPath", $watchlistSummaryPath,
            "-Zip"
        )
        if (-not [string]::IsNullOrWhiteSpace([string]$state.last_watchlist_manifest) -and (Test-Path ([string]$state.last_watchlist_manifest))) {
            $watchlistArgs += @("-PreviousRoutingManifestPath", ([string]$state.last_watchlist_manifest))
        }
        if (Test-Path $resolvedWatchlistOwnerAckPath) {
            $watchlistArgs += @("-OwnerAckPath", $resolvedWatchlistOwnerAckPath)
        }
        $steps.Add((Invoke-SteadyStateStep `
            -StepName "watchlist_routing" `
            -ScriptPath (Join-Path $repoRoot "scripts\ga-steady-state-escalation-watchlist-route.ps1") `
            -RunnerExe $runnerExe `
            -StepLogPath (Join-Path $resolvedOutputDir "step-watchlist.log") `
            -Args $watchlistArgs
        )) | Out-Null

        if ($Mode -eq "weekly") {
            $improvementDir = Join-Path $resolvedOutputDir "improvement"
            $improvementManifestPath = Join-Path $improvementDir "ga-steady-state-improvement-backlog.manifest.json"
            $improvementSummaryPath = Join-Path $improvementDir "ga-steady-state-improvement-backlog.summary.json"
            $steps.Add((Invoke-SteadyStateStep `
                -StepName "improvement_backlog" `
                -ScriptPath (Join-Path $repoRoot "scripts\ga-steady-state-improvement-backlog.ps1") `
                -RunnerExe $runnerExe `
                -StepLogPath (Join-Path $resolvedOutputDir "step-improvement.log") `
                -Args @(
                    "-LogsRoot", $resolvedLogsRoot,
                    "-OutputDir", $improvementDir,
                    "-OutPath", $improvementManifestPath,
                    "-SummaryOutPath", $improvementSummaryPath,
                    "-Zip"
                )
            )) | Out-Null

            $burndownDir = Join-Path $resolvedOutputDir "burndown"
            $burndownManifestPath = Join-Path $burndownDir "ga-steady-state-burndown.manifest.json"
            $burndownSummaryPath = Join-Path $burndownDir "ga-steady-state-burndown.summary.json"
            $burndownArgs = @(
                "-LogsRoot", $resolvedLogsRoot,
                "-OutputDir", $burndownDir,
                "-OutPath", $burndownManifestPath,
                "-SummaryOutPath", $burndownSummaryPath,
                "-Zip"
            )
            if (-not [string]::IsNullOrWhiteSpace($improvementManifestPath)) {
                $burndownArgs += @("-ImprovementBacklogManifestPath", $improvementManifestPath)
            }
            $steps.Add((Invoke-SteadyStateStep `
                -StepName "burndown_tracking" `
                -ScriptPath (Join-Path $repoRoot "scripts\ga-steady-state-burndown.ps1") `
                -RunnerExe $runnerExe `
                -StepLogPath (Join-Path $resolvedOutputDir "step-burndown.log") `
                -Args $burndownArgs
            )) | Out-Null
        }
    }
} catch {
    $paused = $true
    $pausedReason = $_.Exception.Message
    $failureClassification = if (Test-SteadyExternalBlockerMessage -Text $pausedReason) { "external_blocker" } else { "local_failure" }
    $recommendedActions.Add("Inspect step logs under run output directory and classify recovery path.") | Out-Null
    if ($failureClassification -eq "external_blocker") {
        $recommendedActions.Add("Treat as external provider/runtime blocker and rerun after upstream remediation.") | Out-Null
    } else {
        $recommendedActions.Add("Fix local script/data issue and rerun steady-state loop.") | Out-Null
    }
}

$checkpointSummary = $null
$watchlistSummary = $null
$watchlistManifest = $null
if (-not $paused -and (Test-Path $checkpointSummaryPath)) {
    $checkpointSummary = Read-OperatorJsonFile -Path $checkpointSummaryPath
}
if (-not $paused -and (Test-Path $watchlistSummaryPath)) {
    $watchlistSummary = Read-OperatorJsonFile -Path $watchlistSummaryPath
}
if (-not $paused -and (Test-Path $watchlistManifestPath)) {
    $watchlistManifest = Read-OperatorJsonFile -Path $watchlistManifestPath
}

$overallCheckpointDecision = if ($null -ne $checkpointSummary) { [string]$checkpointSummary.overall_checkpoint_decision } else { "unknown" }
$overallWatchlistDecision = if ($null -ne $watchlistSummary) { [string]$watchlistSummary.overall_watchlist_decision } else { "unknown" }
$watchCount = if ($null -ne $watchlistSummary) { Convert-OperatorToInt -Value $watchlistSummary.decision_counts.watch -Default 0 } else { 0 }
$escalateCount = if ($null -ne $watchlistSummary) { Convert-OperatorToInt -Value $watchlistSummary.decision_counts.escalate -Default 0 } else { 0 }
$ownerAckAppliedCount = if ($null -ne $watchlistSummary) { Convert-OperatorToInt -Value $watchlistSummary.owner_ack_applied_count -Default 0 } else { 0 }
$ownerAssignmentPendingCount = 0
if ($null -ne $watchlistManifest) {
    $ownerAssignmentPendingCount = @(
        @($watchlistManifest.details.watchlist_items) |
            Where-Object { ([string]$_.status).Trim().ToLowerInvariant() -eq "owner_assignment_required" }
    ).Count
}

$consecutiveEscalate = if (
    ($overallCheckpointDecision -eq "escalate" -or $overallWatchlistDecision -eq "escalate") -and
    ($ownerAssignmentPendingCount -gt 0)
) {
    (Convert-OperatorToInt -Value $state.consecutive_escalate_count -Default 0) + 1
} else {
    0
}

$consecutiveExternalBlocker = if ($failureClassification -eq "external_blocker") {
    (Convert-OperatorToInt -Value $state.consecutive_external_blocker_count -Default 0) + 1
} else {
    0
}

if (-not $paused -and $consecutiveEscalate -ge $MaxConsecutiveEscalateCount) {
    $paused = $true
    $pausedReason = ("repeated escalation threshold reached: {0}/{1}" -f $consecutiveEscalate, $MaxConsecutiveEscalateCount)
    $failureClassification = "operational_threshold"
    $recommendedActions.Add("Escalation count threshold reached; run owner review before next automated cycle.") | Out-Null
}
if (-not $paused -and $ownerAssignmentPendingCount -gt $MaxOwnerAssignmentPendingCount) {
    $paused = $true
    $pausedReason = ("owner_assignment_pending threshold exceeded: {0}>{1}" -f $ownerAssignmentPendingCount, $MaxOwnerAssignmentPendingCount)
    $failureClassification = "operational_threshold"
    $recommendedActions.Add("Owner assignment pending threshold exceeded; assign owner and rerun routing.") | Out-Null
}
if (-not $paused -and $consecutiveExternalBlocker -ge 2) {
    $paused = $true
    $pausedReason = ("repeated external blocker threshold reached: {0}" -f $consecutiveExternalBlocker)
    $failureClassification = "external_blocker"
    $recommendedActions.Add("Repeated external blocker detected; wait for provider/runtime remediation.") | Out-Null
}

$knownIssueTouched = @()
if (-not $paused -and $ownerAssignmentPendingCount -gt 0) {
    $issueId = "KI-STEADY-RELEASE-OWNER-PENDING"
    $row = "| {0} | Release lane watchlist contains `owner_assignment_required` items in steady-state loop. | P2 | open | release_ops_owner | {1} | Maintain escalation watchlist routing and owner acknowledgment workflow. | Assign owner in release-ops meeting and rerun steady-state watchlist route. |" -f $issueId, [DateTime]::UtcNow.ToString("o")
    $log = ("{0}: Observed owner_assignment_required_count={1} in steady-state run {2}." -f (Get-Date -Format "yyyy-MM-dd"), $ownerAssignmentPendingCount, $cycleId)
    Ensure-SteadyKnownIssueEntry -KnownIssuesFile $resolvedKnownIssuesPath -IssueId $issueId -Row $row -UpdateLogEntry $log
    $knownIssueTouched += $issueId
}
if (-not $paused -and $consecutiveEscalate -ge 2) {
    $issueId = "KI-STEADY-REPEATED-ESCALATE"
    $row = "| {0} | Overall checkpoint/watchlist decision remains `escalate` across consecutive steady-state cycles. | P2 | open | steady_state_ops_owner | {1} | Continue cadence/checkpoint/watchlist loop with bounded remediation tracking. | Reduce escalate lane count or downgrade to watch before next checkpoint refresh. |" -f $issueId, [DateTime]::UtcNow.ToString("o")
    $log = ("{0}: consecutive_escalate_count={1} observed in steady-state run {2}." -f (Get-Date -Format "yyyy-MM-dd"), $consecutiveEscalate, $cycleId)
    Ensure-SteadyKnownIssueEntry -KnownIssuesFile $resolvedKnownIssuesPath -IssueId $issueId -Row $row -UpdateLogEntry $log
    $knownIssueTouched += $issueId
}

if ($knownIssueTouched.Count -gt 0) {
    $knownIssueUpdates.Add([ordered]@{
        updated_issue_ids = $knownIssueTouched
        known_issues_path = $resolvedKnownIssuesPath
        updated_at_utc = [DateTime]::UtcNow.ToString("o")
    }) | Out-Null
}

Ensure-StagingDocBaseline -Path $resolvedStagingPath
$stagingPreviewPath = Join-Path $resolvedOutputDir "staging_append_preview.md"
$stagingBlock = New-Object System.Collections.Generic.List[string]
$stagingBlock.Add(("## Steady-state runtime loop cycle ({0} +09:00)" -f (Get-Date -Format "yyyy-MM-dd"))) | Out-Null
$stagingBlock.Add("") | Out-Null
$stagingBlock.Add(('- cycle_id: `{0}`' -f $cycleId)) | Out-Null
$stagingBlock.Add(('- mode: `{0}`' -f $Mode)) | Out-Null
$stagingBlock.Add(('- paused: `{0}`' -f $paused.ToString().ToLowerInvariant())) | Out-Null
if (-not [string]::IsNullOrWhiteSpace($pausedReason)) {
    $stagingBlock.Add(('- paused_reason: `{0}`' -f $pausedReason)) | Out-Null
}
$stagingBlock.Add(('- checkpoint_decision: `{0}`' -f $overallCheckpointDecision)) | Out-Null
$stagingBlock.Add(('- watchlist_decision: `{0}`' -f $overallWatchlistDecision)) | Out-Null
$stagingBlock.Add(('- open_watch_count: `{0}`' -f $watchCount)) | Out-Null
$stagingBlock.Add(('- open_escalate_count: `{0}`' -f $escalateCount)) | Out-Null
$stagingBlock.Add(('- owner_assignment_pending_count: `{0}`' -f $ownerAssignmentPendingCount)) | Out-Null
$stagingBlock.Add(('- owner_ack_applied_count: `{0}`' -f $ownerAckAppliedCount)) | Out-Null
$stagingBlock.Add(('- consecutive_escalate_count: `{0}`' -f $consecutiveEscalate)) | Out-Null
$stagingBlock.Add(('- checkpoint_manifest: `{0}`' -f $checkpointManifestPath)) | Out-Null
$stagingBlock.Add(('- watchlist_manifest: `{0}`' -f $watchlistManifestPath)) | Out-Null
$stagingBlock.Add("") | Out-Null
$stagingBlock.Add("### Run artifacts") | Out-Null
$stagingBlock.Add(('- run_manifest: `{0}`' -f $OutPath)) | Out-Null
$stagingBlock.Add(('- run_summary: `{0}`' -f $SummaryOutPath)) | Out-Null
if ($knownIssueTouched.Count -gt 0) {
    $stagingBlock.Add(('- known_issue_updates: `{0}`' -f ($knownIssueTouched -join ", "))) | Out-Null
}
if ($recommendedActions.Count -gt 0) {
    $stagingBlock.Add("") | Out-Null
    $stagingBlock.Add("### Recommended actions") | Out-Null
    foreach ($action in @($recommendedActions.ToArray())) {
        $stagingBlock.Add(("- {0}" -f $action)) | Out-Null
    }
}

$previewText = (@($stagingBlock.ToArray()) -join [Environment]::NewLine)
[System.IO.File]::WriteAllText($stagingPreviewPath, $previewText + [Environment]::NewLine, [System.Text.Encoding]::UTF8)
[System.IO.File]::AppendAllText($resolvedStagingPath, [Environment]::NewLine + $previewText + [Environment]::NewLine, [System.Text.Encoding]::UTF8)

$state.last_run_at = [DateTime]::UtcNow.ToString("o")
$state.last_status = if ($paused) { "paused" } else { "ok" }
$state.last_cycle_id = $cycleId
$state.last_checkpoint_manifest = $checkpointManifestPath
$state.last_watchlist_manifest = $watchlistManifestPath
$state.last_known_issue_update = if ($knownIssueTouched.Count -gt 0) { [string]($knownIssueTouched -join ",") } else { "" }
$state.consecutive_escalate_count = $consecutiveEscalate
$state.open_watch_count = $watchCount
$state.open_escalate_count = $escalateCount
$state.last_owner_assignment_pending_count = $ownerAssignmentPendingCount
$state.paused_reason = if ($paused) { $pausedReason } else { "" }
$state.consecutive_external_blocker_count = $consecutiveExternalBlocker
Save-OperatorJson -Payload $state -OutPath $resolvedStatePath

$summary = [ordered]@{
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    cycle_id = $cycleId
    mode = $Mode
    paused = $paused
    paused_reason = $pausedReason
    failure_classification = $failureClassification
    overall_checkpoint_decision = $overallCheckpointDecision
    overall_watchlist_decision = $overallWatchlistDecision
    open_watch_count = $watchCount
    open_escalate_count = $escalateCount
    owner_assignment_pending_count = $ownerAssignmentPendingCount
    owner_ack_applied_count = $ownerAckAppliedCount
    consecutive_escalate_count = $consecutiveEscalate
    consecutive_external_blocker_count = $consecutiveExternalBlocker
    known_issue_update_count = $knownIssueTouched.Count
    state_path = $resolvedStatePath
}
Save-OperatorJson -Payload $summary -OutPath $SummaryOutPath

$manifest = [ordered]@{
    bundle_type = "steady_state_runtime_loop"
    bundle_version = 1
    generated_at_utc = $summary.generated_at_utc
    summary = $summary
    artifacts = [ordered]@{
        run_summary = New-OperatorManifestArtifactEntry -Path $SummaryOutPath -RepoRoot $repoRoot
        state_file = New-OperatorManifestArtifactEntry -Path $resolvedStatePath -RepoRoot $repoRoot
        checkpoint_manifest = New-OperatorManifestArtifactEntry -Path $checkpointManifestPath -RepoRoot $repoRoot
        watchlist_manifest = New-OperatorManifestArtifactEntry -Path $watchlistManifestPath -RepoRoot $repoRoot
        cadence_manifest = New-OperatorManifestArtifactEntry -Path $cadenceManifestPath -RepoRoot $repoRoot
        improvement_manifest = New-OperatorManifestArtifactEntry -Path $improvementManifestPath -RepoRoot $repoRoot
        burndown_manifest = New-OperatorManifestArtifactEntry -Path $burndownManifestPath -RepoRoot $repoRoot
        staging_append_preview = New-OperatorManifestArtifactEntry -Path $stagingPreviewPath -RepoRoot $repoRoot
        known_issue_updates = @($knownIssueUpdates.ToArray())
        steps = @($steps.ToArray())
    }
    details = [ordered]@{
        preflight_issues = @($preflightIssues.ToArray())
        recommended_human_actions = @($recommendedActions.ToArray())
    }
}
Save-OperatorJson -Payload $manifest -OutPath $OutPath

$archiveOutputPath = ""
if ($Zip) {
    $archiveOutputPath = $resolvedOutputDir.TrimEnd("\") + ".zip"
    if (Test-Path $archiveOutputPath) {
        Remove-Item -Path $archiveOutputPath -Force
    }
    Compress-Archive -Path (Join-Path $resolvedOutputDir "*") -DestinationPath $archiveOutputPath -Force
}

if (Test-Path $lockPath) {
    Remove-Item -Path $lockPath -Force -ErrorAction SilentlyContinue
}
$lockAcquired = $false

Write-Host "[done] steady-state runtime loop completed"
Write-Host ("  mode                  : {0}" -f $Mode)
Write-Host ("  paused                : {0}" -f $paused.ToString().ToLowerInvariant())
Write-Host ("  checkpoint_decision   : {0}" -f $overallCheckpointDecision)
Write-Host ("  watchlist_decision    : {0}" -f $overallWatchlistDecision)
Write-Host ("  known_issue_updates   : {0}" -f $knownIssueTouched.Count)
Write-Host ("  manifest              : {0}" -f $OutPath)
Write-Host ("  summary               : {0}" -f $SummaryOutPath)
if (-not [string]::IsNullOrWhiteSpace($archiveOutputPath)) {
    Write-Host ("  archive               : {0}" -f $archiveOutputPath)
}
