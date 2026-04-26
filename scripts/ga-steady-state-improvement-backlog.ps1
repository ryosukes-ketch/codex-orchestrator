param(
    [string]$Phase20CloseoutManifestPath = "",
    [string]$Phase21CloseoutManifestPath = "",
    [string]$Phase22CloseoutManifestPath = "",
    [string]$LogsRoot = "logs",
    [int]$MaxBacklogItems = 20,
    [string]$OutputDir = "",
    [string]$OutPath = "",
    [string]$SummaryOutPath = "",
    [switch]$Zip
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. (Join-Path $PSScriptRoot "operator-common.ps1")

if ($MaxBacklogItems -lt 1) {
    Write-Error "-MaxBacklogItems must be >= 1."
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

function Add-BacklogItemFromManifest {
    param(
        [System.Collections.Generic.List[object]]$Items,
        [string]$ManifestPath,
        [string]$SourceBundleType,
        [string]$SourceDecision,
        [string]$Lane,
        [string[]]$Reasons
    )

    if ([string]::IsNullOrWhiteSpace($SourceDecision)) {
        return
    }
    $decision = $SourceDecision.Trim().ToLowerInvariant()
    if ($decision -eq "go") {
        return
    }

    $priority = if ($decision -eq "escalate") { "high" } else { "medium" }
    $summary = if ($Reasons.Count -gt 0) { $Reasons[0] } else { "Decision requires bounded operational follow-up." }
    $Items.Add([ordered]@{
        backlog_id = [Guid]::NewGuid().ToString()
        lane = $Lane
        source_bundle_type = $SourceBundleType
        source_manifest_path = $ManifestPath
        decision = $decision
        priority = $priority
        summary = $summary
        reasons = $Reasons
        status = "open"
        recommended_owner = switch ($Lane) {
            "environment_support" { "operations" }
            "auditability_retention" { "compliance_ops" }
            "steady_state_ops" { "release_ops" }
            default { "operations" }
        }
    }) | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$resolvedLogsRoot = Resolve-OperatorAbsolutePath -Path $LogsRoot -BasePath $repoRoot
$resolvedOutputDir = ([string]$OutputDir).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedOutputDir)) {
    $resolvedOutputDir = Join-Path $repoRoot ("logs\ga-steady-state\improvement-backlog-{0}" -f $timestamp)
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = Resolve-OperatorAbsolutePath -Path $resolvedOutputDir -BasePath $repoRoot
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "ga-steady-state-improvement-backlog.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}

if ([string]::IsNullOrWhiteSpace($SummaryOutPath)) {
    $SummaryOutPath = Join-Path $resolvedOutputDir "ga-steady-state-improvement-backlog.summary.json"
} elseif (-not [System.IO.Path]::IsPathRooted($SummaryOutPath)) {
    $SummaryOutPath = Resolve-OperatorAbsolutePath -Path $SummaryOutPath -BasePath $repoRoot
}

$resolvedPhase20Path = Resolve-OptionalPath -PathValue $Phase20CloseoutManifestPath -BasePath $repoRoot
if ([string]::IsNullOrWhiteSpace($resolvedPhase20Path)) {
    $resolvedPhase20Path = Resolve-LatestManifestPath -SearchRoot (Join-Path $resolvedLogsRoot "ga-ops") -Filter "phase20-environment-support-closeout.manifest.json"
}
$resolvedPhase21Path = Resolve-OptionalPath -PathValue $Phase21CloseoutManifestPath -BasePath $repoRoot
if ([string]::IsNullOrWhiteSpace($resolvedPhase21Path)) {
    $resolvedPhase21Path = Resolve-LatestManifestPath -SearchRoot (Join-Path $resolvedLogsRoot "ga-compliance") -Filter "phase21-auditability-closeout.manifest.json"
}
$resolvedPhase22Path = Resolve-OptionalPath -PathValue $Phase22CloseoutManifestPath -BasePath $repoRoot
if ([string]::IsNullOrWhiteSpace($resolvedPhase22Path)) {
    $resolvedPhase22Path = Resolve-LatestManifestPath -SearchRoot (Join-Path $resolvedLogsRoot "ga-steady-state") -Filter "phase22-steady-state-closeout.manifest.json"
}

$missingSources = New-Object System.Collections.Generic.List[string]
$backlogItems = New-Object System.Collections.Generic.List[object]

if (-not [string]::IsNullOrWhiteSpace($resolvedPhase20Path) -and (Test-Path $resolvedPhase20Path)) {
    $phase20 = Read-OperatorJsonFile -Path $resolvedPhase20Path
    $decision = [string]$phase20.summary.closeout_decision
    $reasons = Convert-ReasonsToArray -Value $phase20.summary.closeout_decision_reasons
    Add-BacklogItemFromManifest -Items $backlogItems -ManifestPath $resolvedPhase20Path -SourceBundleType ([string]$phase20.bundle_type) -SourceDecision $decision -Lane "environment_support" -Reasons $reasons
} else {
    $missingSources.Add("phase20_environment_support_closeout") | Out-Null
}

if (-not [string]::IsNullOrWhiteSpace($resolvedPhase21Path) -and (Test-Path $resolvedPhase21Path)) {
    $phase21 = Read-OperatorJsonFile -Path $resolvedPhase21Path
    $decision = [string]$phase21.summary.closeout_decision
    $reasons = Convert-ReasonsToArray -Value $phase21.summary.closeout_decision_reasons
    Add-BacklogItemFromManifest -Items $backlogItems -ManifestPath $resolvedPhase21Path -SourceBundleType ([string]$phase21.bundle_type) -SourceDecision $decision -Lane "auditability_retention" -Reasons $reasons
} else {
    $missingSources.Add("phase21_auditability_closeout") | Out-Null
}

if (-not [string]::IsNullOrWhiteSpace($resolvedPhase22Path) -and (Test-Path $resolvedPhase22Path)) {
    $phase22 = Read-OperatorJsonFile -Path $resolvedPhase22Path
    $decision = [string]$phase22.summary.closeout_decision
    $reasons = Convert-ReasonsToArray -Value $phase22.summary.closeout_decision_reasons
    Add-BacklogItemFromManifest -Items $backlogItems -ManifestPath $resolvedPhase22Path -SourceBundleType ([string]$phase22.bundle_type) -SourceDecision $decision -Lane "steady_state_ops" -Reasons $reasons
} else {
    $missingSources.Add("phase22_steady_state_closeout") | Out-Null
}

$itemsArray = @($backlogItems.ToArray())
if ($itemsArray.Count -gt $MaxBacklogItems) {
    $itemsArray = @($itemsArray | Select-Object -First $MaxBacklogItems)
}

$highPriorityCount = @($itemsArray | Where-Object { $_.priority -eq "high" }).Count
$mediumPriorityCount = @($itemsArray | Where-Object { $_.priority -eq "medium" }).Count
$decision = "go"
$decisionReasons = New-Object System.Collections.Generic.List[string]
if ($missingSources.Count -gt 0) {
    $decision = "watch"
    $decisionReasons.Add(("Missing closeout sources: {0}" -f (@($missingSources.ToArray()) -join ","))) | Out-Null
}
if ($itemsArray.Count -gt 0) {
    $decision = "watch"
    $decisionReasons.Add("One or more watch/escalate closeout outcomes require bounded steady-state backlog actions.") | Out-Null
}
if ($decisionReasons.Count -eq 0) {
    $decisionReasons.Add("No watch/escalate closeout outcomes detected across phase20-22 sources.") | Out-Null
}

$summary = [ordered]@{
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    source_manifest_paths = [ordered]@{
        phase20_closeout_manifest_path = $resolvedPhase20Path
        phase21_closeout_manifest_path = $resolvedPhase21Path
        phase22_closeout_manifest_path = $resolvedPhase22Path
    }
    backlog_item_count = $itemsArray.Count
    high_priority_count = $highPriorityCount
    medium_priority_count = $mediumPriorityCount
    missing_source_count = $missingSources.Count
    steady_state_improvement_decision = $decision
    steady_state_improvement_decision_reasons = @($decisionReasons.ToArray())
}
Save-OperatorJson -Payload $summary -OutPath $SummaryOutPath

$manifest = [ordered]@{
    bundle_type = "steady_state_improvement_backlog"
    bundle_version = 1
    generated_at_utc = $summary.generated_at_utc
    summary = $summary
    details = [ordered]@{
        backlog_items = $itemsArray
        missing_sources = @($missingSources.ToArray())
        next_steps = @(
            "1) route high-priority items into immediate operational mitigation lane.",
            "2) route medium-priority items into weekly reliability cycle.",
            "3) re-run this script after closeout updates and verify backlog count trend."
        )
    }
}
Save-OperatorJson -Payload $manifest -OutPath $OutPath

$reportPath = Join-Path $resolvedOutputDir "ga-steady-state-improvement-backlog.md"
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# GA Steady-State Improvement Backlog") | Out-Null
$lines.Add("") | Out-Null
$lines.Add(("- generated_at_utc: {0}" -f $summary.generated_at_utc)) | Out-Null
$lines.Add(("- backlog_item_count: {0}" -f [int]$summary.backlog_item_count)) | Out-Null
$lines.Add(("- high_priority_count: {0}" -f [int]$summary.high_priority_count)) | Out-Null
$lines.Add(("- medium_priority_count: {0}" -f [int]$summary.medium_priority_count)) | Out-Null
$lines.Add(("- missing_source_count: {0}" -f [int]$summary.missing_source_count)) | Out-Null
$lines.Add(("- steady_state_improvement_decision: {0}" -f [string]$summary.steady_state_improvement_decision)) | Out-Null
[System.IO.File]::WriteAllLines($reportPath, $lines, [System.Text.Encoding]::UTF8)

$archiveOutputPath = ""
if ($Zip) {
    $archiveOutputPath = $resolvedOutputDir.TrimEnd("\") + ".zip"
    if (Test-Path $archiveOutputPath) {
        Remove-Item -Path $archiveOutputPath -Force
    }
    Compress-Archive -Path (Join-Path $resolvedOutputDir "*") -DestinationPath $archiveOutputPath -Force
}

Write-Host "[done] ga steady-state improvement backlog completed"
Write-Host ("  backlog_manifest : {0}" -f $OutPath)
Write-Host ("  backlog_summary  : {0}" -f $SummaryOutPath)
Write-Host ("  decision         : {0}" -f [string]$summary.steady_state_improvement_decision)
if (-not [string]::IsNullOrWhiteSpace($archiveOutputPath)) {
    Write-Host ("  archive          : {0}" -f $archiveOutputPath)
}
