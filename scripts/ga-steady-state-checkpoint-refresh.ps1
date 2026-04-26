param(
    [string]$MonthlyCheckpointManifestPath = "",
    [string]$QuarterlyCheckpointManifestPath = "",
    [string]$ReleaseCheckpointManifestPath = "",
    [string]$PreviousCheckpointManifestPath = "",
    [string]$LogsRoot = "logs",
    [string]$OutputDir = "",
    [string]$OutPath = "",
    [string]$SummaryOutPath = "",
    [switch]$Zip
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. (Join-Path $PSScriptRoot "operator-common.ps1")

function Resolve-LatestManifestPath {
    param(
        [string]$SearchRoot,
        [string]$Filter
    )

    if (-not (Test-Path $SearchRoot)) {
        return ""
    }
    $latest = Get-ChildItem -Path $SearchRoot -Recurse -File -Filter $Filter |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($null -eq $latest) {
        return ""
    }
    return $latest.FullName
}

function Resolve-OptionalPath {
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

function Convert-ReasonsToArray {
    param([object]$Value)

    if ($null -eq $Value) {
        return @()
    }
    if ($Value -is [string]) {
        if ([string]::IsNullOrWhiteSpace($Value)) {
            return @()
        }
        return @([string]$Value)
    }
    if ($Value -is [System.Collections.IEnumerable]) {
        $items = New-Object System.Collections.Generic.List[string]
        foreach ($entry in @($Value)) {
            $text = ([string]$entry).Trim()
            if ([string]::IsNullOrWhiteSpace($text)) {
                continue
            }
            $items.Add($text) | Out-Null
        }
        return @($items.ToArray())
    }
    return @(([string]$Value).Trim())
}

function Convert-ToCheckpointDecision {
    param(
        [string]$RawDecision,
        [string]$Lane
    )

    $raw = ([string]$RawDecision).Trim()
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return "watch"
    }

    $normalized = $raw.ToLowerInvariant()
    if ($Lane -eq "release") {
        switch ($normalized) {
            "go" { return "go" }
            "hold" { return "escalate" }
            "rollback_required" { return "escalate" }
            "rollback ready" { return "watch" }
            "rollback_ready" { return "watch" }
            default { }
        }
    }

    switch ($normalized) {
        "go" { return "go" }
        "pass" { return "go" }
        "green" { return "go" }
        "watch" { return "watch" }
        "monitor" { return "watch" }
        "rollback_ready" { return "watch" }
        "escalate" { return "escalate" }
        "hold" { return "escalate" }
        "rollback_required" { return "escalate" }
        "fail" { return "escalate" }
        "failed" { return "escalate" }
        default { return "watch" }
    }
}

function Get-DecisionValueAndReasons {
    param(
        [object]$Manifest,
        [string]$Lane
    )

    $summary = $Manifest.summary
    $rawDecision = ""
    $reasons = @()
    switch ($Lane) {
        "monthly" {
            $rawDecision = [string]$summary.monthly_decision
            $reasons = Convert-ReasonsToArray -Value $summary.monthly_decision_reasons
        }
        "quarterly" {
            $rawDecision = [string]$summary.quarterly_review_decision
            $reasons = Convert-ReasonsToArray -Value $summary.quarterly_review_decision_reasons
        }
        "release" {
            $rawDecision = [string]$summary.decision
            $reasons = Convert-ReasonsToArray -Value $summary.decision_reasons
            if ($reasons.Count -eq 0) {
                $reasons = Convert-ReasonsToArray -Value $Manifest.next_steps
            }
        }
        default {
            $rawDecision = ""
            $reasons = @()
        }
    }
    return [ordered]@{
        raw_decision = $rawDecision
        reasons = $reasons
        checkpoint_decision = Convert-ToCheckpointDecision -RawDecision $rawDecision -Lane $Lane
    }
}

function Convert-DecisionToScore {
    param([string]$Decision)
    $normalized = ([string]$Decision).Trim().ToLowerInvariant()
    switch ($normalized) {
        "go" { return 2 }
        "watch" { return 1 }
        "escalate" { return 0 }
        default { return 1 }
    }
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$resolvedLogsRoot = Resolve-OperatorAbsolutePath -Path $LogsRoot -BasePath $repoRoot
$resolvedOutputDir = ([string]$OutputDir).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedOutputDir)) {
    $resolvedOutputDir = Join-Path $repoRoot ("logs\ga-steady-state\checkpoint-refresh-{0}" -f $timestamp)
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = Resolve-OperatorAbsolutePath -Path $resolvedOutputDir -BasePath $repoRoot
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "ga-steady-state-checkpoint-refresh.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}

if ([string]::IsNullOrWhiteSpace($SummaryOutPath)) {
    $SummaryOutPath = Join-Path $resolvedOutputDir "ga-steady-state-checkpoint-refresh.summary.json"
} elseif (-not [System.IO.Path]::IsPathRooted($SummaryOutPath)) {
    $SummaryOutPath = Resolve-OperatorAbsolutePath -Path $SummaryOutPath -BasePath $repoRoot
}

$resolvedMonthlyPath = Resolve-OptionalPath -PathValue $MonthlyCheckpointManifestPath -BasePath $repoRoot
if ([string]::IsNullOrWhiteSpace($resolvedMonthlyPath)) {
    $resolvedMonthlyPath = Resolve-LatestManifestPath -SearchRoot (Join-Path $resolvedLogsRoot "ga-adoption") -Filter "ga-monthly-reliability-targets.manifest.json"
}
$resolvedQuarterlyPath = Resolve-OptionalPath -PathValue $QuarterlyCheckpointManifestPath -BasePath $repoRoot
if ([string]::IsNullOrWhiteSpace($resolvedQuarterlyPath)) {
    $resolvedQuarterlyPath = Resolve-LatestManifestPath -SearchRoot (Join-Path $resolvedLogsRoot "ga-adoption") -Filter "ga-quarterly-review-package.manifest.json"
}
$resolvedReleasePath = Resolve-OptionalPath -PathValue $ReleaseCheckpointManifestPath -BasePath $repoRoot
if ([string]::IsNullOrWhiteSpace($resolvedReleasePath)) {
    $resolvedReleasePath = Resolve-LatestManifestPath -SearchRoot (Join-Path $resolvedLogsRoot "release-train") -Filter "release-train-evidence.manifest.json"
}

$resolvedPreviousCheckpointPath = Resolve-OptionalPath -PathValue $PreviousCheckpointManifestPath -BasePath $repoRoot
if ([string]::IsNullOrWhiteSpace($resolvedPreviousCheckpointPath)) {
    $previousCandidates = @(
        Get-ChildItem -Path (Join-Path $resolvedLogsRoot "ga-steady-state") -Recurse -File -Filter "ga-steady-state-checkpoint-refresh.manifest.json" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTimeUtc -Descending
    )
    if ($previousCandidates.Count -gt 0) {
        $resolvedPreviousCheckpointPath = $previousCandidates[0].FullName
    }
}

$missingCheckpoints = New-Object System.Collections.Generic.List[string]
$checkpoints = New-Object System.Collections.Generic.List[object]
$decisionCounts = [ordered]@{
    go = 0
    watch = 0
    escalate = 0
}

function Add-Checkpoint {
    param(
        [string]$Lane,
        [string]$PathValue
    )

    if ([string]::IsNullOrWhiteSpace($PathValue) -or -not (Test-Path $PathValue)) {
        $missingCheckpoints.Add($Lane) | Out-Null
        return
    }

    $manifest = Read-OperatorJsonFile -Path $PathValue
    $decisionInfo = Get-DecisionValueAndReasons -Manifest $manifest -Lane $Lane
    $checkpointDecision = [string]$decisionInfo.checkpoint_decision
    if (-not $decisionCounts.Contains($checkpointDecision)) {
        $decisionCounts[$checkpointDecision] = 0
    }
    $decisionCounts[$checkpointDecision] = [int]$decisionCounts[$checkpointDecision] + 1
    $checkpoints.Add([ordered]@{
        checkpoint_lane = $Lane
        source_manifest_path = $PathValue
        source_bundle_type = [string]$manifest.bundle_type
        source_generated_at_utc = [string]$manifest.generated_at_utc
        raw_decision = [string]$decisionInfo.raw_decision
        checkpoint_decision = $checkpointDecision
        decision_reasons = @($decisionInfo.reasons)
    }) | Out-Null
}

Add-Checkpoint -Lane "monthly" -PathValue $resolvedMonthlyPath
Add-Checkpoint -Lane "quarterly" -PathValue $resolvedQuarterlyPath
Add-Checkpoint -Lane "release" -PathValue $resolvedReleasePath

$overallDecision = "go"
$overallReasons = New-Object System.Collections.Generic.List[string]
if ($missingCheckpoints.Count -gt 0) {
    $overallDecision = "watch"
    $overallReasons.Add(("Missing checkpoint manifests: {0}" -f (@($missingCheckpoints.ToArray()) -join ","))) | Out-Null
}
if ([int]$decisionCounts.escalate -gt 0) {
    $overallDecision = "escalate"
    $overallReasons.Add("One or more checkpoint lanes reported escalate-level decision.") | Out-Null
} elseif ([int]$decisionCounts.watch -gt 0 -and $overallDecision -ne "escalate") {
    $overallDecision = "watch"
    $overallReasons.Add("One or more checkpoint lanes remain in watch posture.") | Out-Null
}
if ($overallReasons.Count -eq 0) {
    $overallReasons.Add("All checkpoint lanes are in go posture.") | Out-Null
}

$monthlyDecision = "missing"
$quarterlyDecision = "missing"
$releaseDecision = "missing"
foreach ($entry in @($checkpoints.ToArray())) {
    switch ([string]$entry.checkpoint_lane) {
        "monthly" { $monthlyDecision = [string]$entry.checkpoint_decision }
        "quarterly" { $quarterlyDecision = [string]$entry.checkpoint_decision }
        "release" { $releaseDecision = [string]$entry.checkpoint_decision }
    }
}

$previousDecision = ""
$decisionDelta = "unknown"
if (-not [string]::IsNullOrWhiteSpace($resolvedPreviousCheckpointPath) -and (Test-Path $resolvedPreviousCheckpointPath)) {
    $previous = Read-OperatorJsonFile -Path $resolvedPreviousCheckpointPath
    if ([string]$previous.bundle_type -eq "steady_state_checkpoint_refresh") {
        $previousDecision = [string]$previous.summary.overall_checkpoint_decision
        $previousScore = Convert-DecisionToScore -Decision $previousDecision
        $currentScore = Convert-DecisionToScore -Decision $overallDecision
        if ($currentScore -gt $previousScore) {
            $decisionDelta = "improved"
        } elseif ($currentScore -lt $previousScore) {
            $decisionDelta = "regressed"
        } else {
            $decisionDelta = "stable"
        }
    }
}

$summary = [ordered]@{
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    source_manifest_paths = [ordered]@{
        monthly_checkpoint_manifest_path = $resolvedMonthlyPath
        quarterly_checkpoint_manifest_path = $resolvedQuarterlyPath
        release_checkpoint_manifest_path = $resolvedReleasePath
    }
    previous_checkpoint_manifest_path = $resolvedPreviousCheckpointPath
    checkpoint_count = $checkpoints.Count
    missing_checkpoint_count = $missingCheckpoints.Count
    checkpoint_decision_counts = $decisionCounts
    monthly_checkpoint_decision = $monthlyDecision
    quarterly_checkpoint_decision = $quarterlyDecision
    release_checkpoint_decision = $releaseDecision
    overall_checkpoint_decision = $overallDecision
    overall_checkpoint_decision_reasons = @($overallReasons.ToArray())
    previous_overall_checkpoint_decision = $previousDecision
    overall_checkpoint_decision_delta = $decisionDelta
}
Save-OperatorJson -Payload $summary -OutPath $SummaryOutPath

$manifest = [ordered]@{
    bundle_type = "steady_state_checkpoint_refresh"
    bundle_version = 1
    generated_at_utc = $summary.generated_at_utc
    summary = $summary
    details = [ordered]@{
        checkpoints = @($checkpoints.ToArray())
        missing_checkpoints = @($missingCheckpoints.ToArray())
        next_steps = @(
            "1) if overall_checkpoint_decision=escalate, trigger immediate release-ops escalation and owner assignment.",
            "2) if overall_checkpoint_decision=watch, continue bounded monthly/quarterly/release checkpoint monitoring.",
            "3) rerun checkpoint refresh after checkpoint source updates and compare decision delta."
        )
    }
}
Save-OperatorJson -Payload $manifest -OutPath $OutPath

$reportPath = Join-Path $resolvedOutputDir "ga-steady-state-checkpoint-refresh.md"
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# GA Steady-State Checkpoint Refresh") | Out-Null
$lines.Add("") | Out-Null
$lines.Add(("- generated_at_utc: {0}" -f $summary.generated_at_utc)) | Out-Null
$lines.Add(("- monthly_checkpoint_decision: {0}" -f [string]$summary.monthly_checkpoint_decision)) | Out-Null
$lines.Add(("- quarterly_checkpoint_decision: {0}" -f [string]$summary.quarterly_checkpoint_decision)) | Out-Null
$lines.Add(("- release_checkpoint_decision: {0}" -f [string]$summary.release_checkpoint_decision)) | Out-Null
$lines.Add(("- overall_checkpoint_decision: {0}" -f [string]$summary.overall_checkpoint_decision)) | Out-Null
$lines.Add(("- overall_checkpoint_decision_delta: {0}" -f [string]$summary.overall_checkpoint_decision_delta)) | Out-Null
[System.IO.File]::WriteAllLines($reportPath, $lines, [System.Text.Encoding]::UTF8)

$archiveOutputPath = ""
if ($Zip) {
    $archiveOutputPath = $resolvedOutputDir.TrimEnd("\") + ".zip"
    if (Test-Path $archiveOutputPath) {
        Remove-Item -Path $archiveOutputPath -Force
    }
    Compress-Archive -Path (Join-Path $resolvedOutputDir "*") -DestinationPath $archiveOutputPath -Force
}

Write-Host "[done] ga steady-state checkpoint refresh completed"
Write-Host ("  checkpoint_manifest : {0}" -f $OutPath)
Write-Host ("  checkpoint_summary  : {0}" -f $SummaryOutPath)
Write-Host ("  decision            : {0}" -f [string]$summary.overall_checkpoint_decision)
if (-not [string]::IsNullOrWhiteSpace($archiveOutputPath)) {
    Write-Host ("  archive             : {0}" -f $archiveOutputPath)
}
