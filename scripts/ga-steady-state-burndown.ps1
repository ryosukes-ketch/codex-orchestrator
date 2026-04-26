param(
    [string]$ImprovementBacklogManifestPath = "",
    [string]$PreviousBurndownManifestPath = "",
    [string]$LogsRoot = "logs",
    [int]$MaxOpenPreview = 10,
    [string]$OutputDir = "",
    [string]$OutPath = "",
    [string]$SummaryOutPath = "",
    [switch]$Zip
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. (Join-Path $PSScriptRoot "operator-common.ps1")

if ($MaxOpenPreview -lt 1) {
    Write-Error "-MaxOpenPreview must be >= 1."
    exit 1
}

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

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$resolvedLogsRoot = Resolve-OperatorAbsolutePath -Path $LogsRoot -BasePath $repoRoot
$resolvedOutputDir = ([string]$OutputDir).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedOutputDir)) {
    $resolvedOutputDir = Join-Path $repoRoot ("logs\ga-steady-state\burndown-{0}" -f $timestamp)
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = Resolve-OperatorAbsolutePath -Path $resolvedOutputDir -BasePath $repoRoot
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "ga-steady-state-burndown.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}

if ([string]::IsNullOrWhiteSpace($SummaryOutPath)) {
    $SummaryOutPath = Join-Path $resolvedOutputDir "ga-steady-state-burndown.summary.json"
} elseif (-not [System.IO.Path]::IsPathRooted($SummaryOutPath)) {
    $SummaryOutPath = Resolve-OperatorAbsolutePath -Path $SummaryOutPath -BasePath $repoRoot
}

$resolvedBacklogPath = Resolve-OptionalPath -PathValue $ImprovementBacklogManifestPath -BasePath $repoRoot
if ([string]::IsNullOrWhiteSpace($resolvedBacklogPath)) {
    $resolvedBacklogPath = Resolve-LatestManifestPath `
        -SearchRoot (Join-Path $resolvedLogsRoot "ga-steady-state") `
        -Filter "ga-steady-state-improvement-backlog.manifest.json"
}
if ([string]::IsNullOrWhiteSpace($resolvedBacklogPath) -or -not (Test-Path $resolvedBacklogPath)) {
    Write-Error "Improvement backlog manifest not found."
    exit 1
}

$resolvedPreviousBurndownPath = Resolve-OptionalPath -PathValue $PreviousBurndownManifestPath -BasePath $repoRoot
if ([string]::IsNullOrWhiteSpace($resolvedPreviousBurndownPath)) {
    $candidates = @(
        Get-ChildItem -Path (Join-Path $resolvedLogsRoot "ga-steady-state") -Recurse -File -Filter "ga-steady-state-burndown.manifest.json" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTimeUtc -Descending
    )
    if ($candidates.Count -gt 0) {
        $resolvedPreviousBurndownPath = $candidates[0].FullName
    }
}

$backlog = Read-OperatorJsonFile -Path $resolvedBacklogPath
if ([string]$backlog.bundle_type -ne "steady_state_improvement_backlog") {
    Write-Error ("Unsupported backlog bundle_type [{0}] in {1}" -f [string]$backlog.bundle_type, $resolvedBacklogPath)
    exit 1
}

$items = @($backlog.details.backlog_items)
$openItems = New-Object System.Collections.Generic.List[object]
$closedItems = New-Object System.Collections.Generic.List[object]
foreach ($item in $items) {
    $status = ([string]$item.status).Trim().ToLowerInvariant()
    if ([string]::IsNullOrWhiteSpace($status)) {
        $status = "open"
    }
    if ($status -eq "closed" -or $status -eq "done") {
        $closedItems.Add($item) | Out-Null
    } else {
        $openItems.Add($item) | Out-Null
    }
}

$previousOpenCount = 0
$previousPathUsed = ""
if (-not [string]::IsNullOrWhiteSpace($resolvedPreviousBurndownPath) -and (Test-Path $resolvedPreviousBurndownPath)) {
    $previous = Read-OperatorJsonFile -Path $resolvedPreviousBurndownPath
    if ([string]$previous.bundle_type -eq "steady_state_burndown_tracking") {
        $previousOpenCount = Convert-OperatorToInt -Value $previous.summary.open_item_count -Default 0
        $previousPathUsed = $resolvedPreviousBurndownPath
    }
}

$openCount = $openItems.Count
$closedCount = $closedItems.Count
$deltaOpen = $openCount - $previousOpenCount
$closedSincePrevious = 0
if ($previousPathUsed -ne "") {
    $closedSincePrevious = [Math]::Max(0, ($previousOpenCount - $openCount))
}

$decision = "go"
$decisionReasons = New-Object System.Collections.Generic.List[string]
if ($openCount -eq 0) {
    $decision = "go"
    $decisionReasons.Add("No open steady-state backlog items remain.") | Out-Null
} elseif ($previousPathUsed -ne "" -and $previousOpenCount -gt 0 -and $deltaOpen -ge 0) {
    $decision = "escalate"
    $decisionReasons.Add("Open backlog is not trending down from previous burndown snapshot.") | Out-Null
} else {
    $decision = "watch"
    $decisionReasons.Add("Open backlog remains; continue bounded burn-down cycle.") | Out-Null
}

$openPreview = @($openItems.ToArray() | Select-Object -First $MaxOpenPreview)

$summary = [ordered]@{
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    improvement_backlog_manifest_path = $resolvedBacklogPath
    previous_burndown_manifest_path = $previousPathUsed
    open_item_count = $openCount
    closed_item_count = $closedCount
    previous_open_item_count = $previousOpenCount
    delta_open_item_count = $deltaOpen
    closed_since_previous_count = $closedSincePrevious
    burndown_decision = $decision
    burndown_decision_reasons = @($decisionReasons.ToArray())
}
Save-OperatorJson -Payload $summary -OutPath $SummaryOutPath

$manifest = [ordered]@{
    bundle_type = "steady_state_burndown_tracking"
    bundle_version = 1
    generated_at_utc = $summary.generated_at_utc
    summary = $summary
    details = [ordered]@{
        open_items_preview = $openPreview
        next_steps = @(
            "1) assign owners for all open items with status=open.",
            "2) close at least one open item before the next burndown run.",
            "3) keep burndown trend evidence in staging execution records."
        )
    }
}
Save-OperatorJson -Payload $manifest -OutPath $OutPath

$reportPath = Join-Path $resolvedOutputDir "ga-steady-state-burndown.md"
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# GA Steady-State Burndown Tracking") | Out-Null
$lines.Add("") | Out-Null
$lines.Add(("- generated_at_utc: {0}" -f $summary.generated_at_utc)) | Out-Null
$lines.Add(("- open_item_count: {0}" -f [int]$summary.open_item_count)) | Out-Null
$lines.Add(("- closed_item_count: {0}" -f [int]$summary.closed_item_count)) | Out-Null
$lines.Add(("- previous_open_item_count: {0}" -f [int]$summary.previous_open_item_count)) | Out-Null
$lines.Add(("- delta_open_item_count: {0}" -f [int]$summary.delta_open_item_count)) | Out-Null
$lines.Add(("- burndown_decision: {0}" -f [string]$summary.burndown_decision)) | Out-Null
[System.IO.File]::WriteAllLines($reportPath, $lines, [System.Text.Encoding]::UTF8)

$archiveOutputPath = ""
if ($Zip) {
    $archiveOutputPath = $resolvedOutputDir.TrimEnd("\") + ".zip"
    if (Test-Path $archiveOutputPath) {
        Remove-Item -Path $archiveOutputPath -Force
    }
    Compress-Archive -Path (Join-Path $resolvedOutputDir "*") -DestinationPath $archiveOutputPath -Force
}

Write-Host "[done] ga steady-state burndown completed"
Write-Host ("  burndown_manifest : {0}" -f $OutPath)
Write-Host ("  burndown_summary  : {0}" -f $SummaryOutPath)
Write-Host ("  decision          : {0}" -f [string]$summary.burndown_decision)
if (-not [string]::IsNullOrWhiteSpace($archiveOutputPath)) {
    Write-Host ("  archive           : {0}" -f $archiveOutputPath)
}
