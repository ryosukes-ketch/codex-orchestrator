param(
    [string]$LogsRoot = "logs",
    [int]$WindowDays = 90,
    [string[]]$MonthlyManifestPaths = @(),
    [string]$OutputDir = "",
    [string]$OutPath = "",
    [string]$SummaryOutPath = "",
    [switch]$Zip
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. (Join-Path $PSScriptRoot "operator-common.ps1")

if ($WindowDays -lt 1) {
    Write-Error "-WindowDays must be >= 1."
    exit 1
}

function Resolve-OptionalArrayPaths {
    param(
        [string[]]$InputPaths,
        [string]$BasePath
    )

    $resolved = New-Object System.Collections.Generic.List[string]
    foreach ($value in @($InputPaths)) {
        foreach ($token in (([string]$value) -split ",")) {
            $trimmed = ([string]$token).Trim()
            if ([string]::IsNullOrWhiteSpace($trimmed)) {
                continue
            }
            $resolved.Add((Resolve-OperatorAbsolutePath -Path $trimmed -BasePath $BasePath)) | Out-Null
        }
    }
    return @($resolved.ToArray())
}

function Parse-UtcOrDefault {
    param(
        [string]$Value,
        [DateTime]$DefaultUtc
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $DefaultUtc
    }
    try {
        return ([DateTime]::Parse($Value).ToUniversalTime())
    } catch {
        return $DefaultUtc
    }
}

function Resolve-MonthlyManifestList {
    param(
        [string[]]$RequestedPaths,
        [string]$LogsRootPath,
        [DateTime]$WindowStartUtc,
        [DateTime]$WindowEndUtc
    )

    $explicit = @(
        @($RequestedPaths) |
            Where-Object { -not [string]::IsNullOrWhiteSpace(([string]$_).Trim()) }
    )
    if ($explicit.Count -gt 0) {
        return $explicit
    }

    $monthlyRoot = Join-Path $LogsRootPath "ga-adoption"
    if (-not (Test-Path $monthlyRoot)) {
        return @()
    }

    $resolved = New-Object System.Collections.Generic.List[string]
    foreach ($candidate in Get-ChildItem -Path $monthlyRoot -Recurse -File -Filter "ga-monthly-reliability-targets.manifest.json") {
        $payload = $null
        try {
            $payload = Read-OperatorJsonFile -Path $candidate.FullName
        } catch {
            continue
        }

        $generatedAtUtc = Parse-UtcOrDefault -Value ([string]$payload.generated_at_utc) -DefaultUtc $candidate.LastWriteTimeUtc
        if ($generatedAtUtc -lt $WindowStartUtc -or $generatedAtUtc -gt $WindowEndUtc) {
            continue
        }
        $resolved.Add($candidate.FullName) | Out-Null
    }
    return @($resolved.ToArray())
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$windowEndUtc = [DateTime]::UtcNow
$windowStartUtc = $windowEndUtc.AddDays(-1 * $WindowDays)

$resolvedOutputDir = ([string]$OutputDir).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedOutputDir)) {
    $resolvedOutputDir = Join-Path $repoRoot ("logs\ga-adoption\quarterly-reliability-{0}" -f $timestamp)
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = Resolve-OperatorAbsolutePath -Path $resolvedOutputDir -BasePath $repoRoot
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "ga-quarterly-reliability-governance.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}

if ([string]::IsNullOrWhiteSpace($SummaryOutPath)) {
    $SummaryOutPath = Join-Path $resolvedOutputDir "ga-quarterly-reliability-governance.summary.json"
} elseif (-not [System.IO.Path]::IsPathRooted($SummaryOutPath)) {
    $SummaryOutPath = Resolve-OperatorAbsolutePath -Path $SummaryOutPath -BasePath $repoRoot
}

$resolvedLogsRoot = Resolve-OperatorAbsolutePath -Path $LogsRoot -BasePath $repoRoot
$requestedMonthlyPaths = Resolve-OptionalArrayPaths -InputPaths $MonthlyManifestPaths -BasePath $repoRoot
$monthlyManifestPaths = Resolve-MonthlyManifestList `
    -RequestedPaths $requestedMonthlyPaths `
    -LogsRootPath $resolvedLogsRoot `
    -WindowStartUtc $windowStartUtc `
    -WindowEndUtc $windowEndUtc

if (@($monthlyManifestPaths).Count -eq 0) {
    Write-Error "No monthly reliability manifests were found in the requested window."
    exit 1
}

$monthlyEntries = New-Object System.Collections.Generic.List[object]
$decisionCounts = [ordered]@{
    go = 0
    watch = 0
    escalate = 0
}
$recommendationTotals = [ordered]@{
    urgent_hardening_cycle = 0
    targeted_hardening_cycle = 0
    monitor_only_cycle = 0
}
$healthScores = New-Object System.Collections.Generic.List[int]
$supportBundleCountTotal = 0
$hardeningActionCountTotal = 0
$overdueActionCountTotal = 0
$overdueP1CountTotal = 0
$knownIssueOpenLatest = 0
$knownIssueMitigatedLatest = 0
$knownIssueResolvedLatest = 0
$latestGeneratedAt = [DateTime]::MinValue

foreach ($path in @($monthlyManifestPaths)) {
    $resolvedPath = Resolve-OperatorAbsolutePath -Path $path -BasePath $repoRoot
    if (-not (Test-Path $resolvedPath)) {
        Write-Error ("Monthly manifest path not found: {0}" -f $resolvedPath)
        exit 1
    }

    $payload = Read-OperatorJsonFile -Path $resolvedPath
    if ([string]$payload.bundle_type -ne "phase17_ga_monthly_reliability_target_package") {
        Write-Error ("Unsupported monthly bundle_type [{0}] in {1}" -f ([string]$payload.bundle_type), $resolvedPath)
        exit 1
    }

    $generatedAtUtc = Parse-UtcOrDefault -Value ([string]$payload.generated_at_utc) -DefaultUtc (Get-Item $resolvedPath).LastWriteTimeUtc
    if ($generatedAtUtc -lt $windowStartUtc -or $generatedAtUtc -gt $windowEndUtc) {
        continue
    }

    $summary = $payload.summary
    $decision = ([string]$summary.monthly_decision).Trim().ToLowerInvariant()
    if ($decisionCounts.Contains($decision)) {
        $decisionCounts[$decision] = [int]$decisionCounts[$decision] + 1
    } else {
        $decisionCounts.watch = [int]$decisionCounts.watch + 1
    }

    $recommendationTotals.urgent_hardening_cycle += Convert-OperatorToInt -Value $summary.recommendation_counts.urgent_hardening_cycle -Default 0
    $recommendationTotals.targeted_hardening_cycle += Convert-OperatorToInt -Value $summary.recommendation_counts.targeted_hardening_cycle -Default 0
    $recommendationTotals.monitor_only_cycle += Convert-OperatorToInt -Value $summary.recommendation_counts.monitor_only_cycle -Default 0
    $supportBundleCountTotal += Convert-OperatorToInt -Value $summary.support_bundle_count_total -Default 0
    $hardeningActionCountTotal += Convert-OperatorToInt -Value $summary.hardening_action_count_total -Default 0
    $overdueActionCountTotal += Convert-OperatorToInt -Value $summary.closure_sla.overdue_action_count -Default 0
    $overdueP1CountTotal += Convert-OperatorToInt -Value $summary.closure_sla.overdue_p1_count -Default 0

    $healthScores.Add((Convert-OperatorToInt -Value $summary.reliability_health_score -Default 0)) | Out-Null

    if ($generatedAtUtc -ge $latestGeneratedAt) {
        $latestGeneratedAt = $generatedAtUtc
        $knownIssueOpenLatest = Convert-OperatorToInt -Value $summary.known_issue_snapshot.open -Default 0
        $knownIssueMitigatedLatest = Convert-OperatorToInt -Value $summary.known_issue_snapshot.mitigated -Default 0
        $knownIssueResolvedLatest = Convert-OperatorToInt -Value $summary.known_issue_snapshot.resolved -Default 0
    }

    $monthlyEntries.Add([ordered]@{
        path = $resolvedPath
        generated_at_utc = $generatedAtUtc.ToString("o")
        monthly_decision = $decision
        reliability_health_score = Convert-OperatorToInt -Value $summary.reliability_health_score -Default 0
        overdue_action_count = Convert-OperatorToInt -Value $summary.closure_sla.overdue_action_count -Default 0
        overdue_p1_count = Convert-OperatorToInt -Value $summary.closure_sla.overdue_p1_count -Default 0
    }) | Out-Null
}

if ($monthlyEntries.Count -eq 0) {
    Write-Error "No monthly reliability manifests fell within the requested window."
    exit 1
}

$avgHealth = 0
if ($healthScores.Count -gt 0) {
    $avgHealth = [int][Math]::Round(($healthScores | Measure-Object -Average).Average, 0)
}

$quarterlyDecision = "go"
$decisionReasons = New-Object System.Collections.Generic.List[string]
if ([int]$decisionCounts.escalate -gt 0 -or $overdueP1CountTotal -gt 0) {
    $quarterlyDecision = "escalate"
    $decisionReasons.Add("Escalation pressure exists in monthly decision outputs or overdue P1 carry-over.") | Out-Null
} elseif ([int]$decisionCounts.watch -gt 0 -or $overdueActionCountTotal -gt 0) {
    $quarterlyDecision = "watch"
    $decisionReasons.Add("Watch-level monthly decisions or overdue closure-SLA actions exist in the quarter.") | Out-Null
} else {
    $decisionReasons.Add("Quarterly monthly outputs show stable go-level reliability profile.") | Out-Null
}

$summary = [ordered]@{
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    analysis_window_utc = [ordered]@{
        start = $windowStartUtc.ToString("o")
        end = $windowEndUtc.ToString("o")
        days = $WindowDays
    }
    monthly_package_count = $monthlyEntries.Count
    monthly_decision_counts = $decisionCounts
    recommendation_totals = $recommendationTotals
    support_bundle_count_total = $supportBundleCountTotal
    hardening_action_count_total = $hardeningActionCountTotal
    closure_sla_overdue_action_count_total = $overdueActionCountTotal
    closure_sla_overdue_p1_count_total = $overdueP1CountTotal
    known_issue_open_latest = $knownIssueOpenLatest
    known_issue_mitigated_latest = $knownIssueMitigatedLatest
    known_issue_resolved_latest = $knownIssueResolvedLatest
    reliability_health_score_average = $avgHealth
    quarterly_decision = $quarterlyDecision
    quarterly_decision_reasons = @($decisionReasons.ToArray())
}

Save-OperatorJson -Payload $summary -OutPath $SummaryOutPath

$manifest = [ordered]@{
    bundle_type = "phase18_quarterly_reliability_governance"
    bundle_version = 1
    generated_at_utc = $summary.generated_at_utc
    summary = $summary
    source = [ordered]@{
        logs_root = $resolvedLogsRoot
        monthly_reliability_manifests = @($monthlyEntries.ToArray())
    }
    details = [ordered]@{
        decision_next_steps = @(
            "1) review monthly_decision_counts and overdue carry-over pressure before quarterly governance signoff",
            "2) route closure-SLA owner updates through ga-closure-sla-breach-route.ps1 outputs",
            "3) rerun quarterly package after monthly cycle close and compare decision drift"
        )
    }
}

Save-OperatorJson -Payload $manifest -OutPath $OutPath

$reportPath = Join-Path $resolvedOutputDir "ga-quarterly-reliability-governance.md"
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# GA Quarterly Reliability Governance") | Out-Null
$lines.Add("") | Out-Null
$lines.Add(("- generated_at_utc: {0}" -f $summary.generated_at_utc)) | Out-Null
$lines.Add(("- analysis_window_utc: {0} -> {1}" -f $summary.analysis_window_utc.start, $summary.analysis_window_utc.end)) | Out-Null
$lines.Add(("- monthly_package_count: {0}" -f [int]$summary.monthly_package_count)) | Out-Null
$lines.Add(("- support_bundle_count_total: {0}" -f [int]$summary.support_bundle_count_total)) | Out-Null
$lines.Add(("- hardening_action_count_total: {0}" -f [int]$summary.hardening_action_count_total)) | Out-Null
$lines.Add(("- closure_sla_overdue_action_count_total: {0}" -f [int]$summary.closure_sla_overdue_action_count_total)) | Out-Null
$lines.Add(("- reliability_health_score_average: {0}" -f [int]$summary.reliability_health_score_average)) | Out-Null
$lines.Add(("- quarterly_decision: {0}" -f [string]$summary.quarterly_decision)) | Out-Null
$lines.Add("") | Out-Null
$lines.Add("## Monthly decision counts") | Out-Null
$lines.Add(("- go: {0}" -f [int]$summary.monthly_decision_counts.go)) | Out-Null
$lines.Add(("- watch: {0}" -f [int]$summary.monthly_decision_counts.watch)) | Out-Null
$lines.Add(("- escalate: {0}" -f [int]$summary.monthly_decision_counts.escalate)) | Out-Null
$lines.Add("") | Out-Null
$lines.Add("## Decision reasons") | Out-Null
foreach ($reason in @($summary.quarterly_decision_reasons)) {
    $lines.Add(("- {0}" -f [string]$reason)) | Out-Null
}
[System.IO.File]::WriteAllLines($reportPath, $lines, [System.Text.Encoding]::UTF8)

$archiveOutputPath = ""
if ($Zip) {
    $archiveOutputPath = $resolvedOutputDir.TrimEnd("\") + ".zip"
    if (Test-Path $archiveOutputPath) {
        Remove-Item -Path $archiveOutputPath -Force
    }
    Compress-Archive -Path (Join-Path $resolvedOutputDir "*") -DestinationPath $archiveOutputPath -Force
}

Write-Host "[done] ga quarterly reliability governance completed"
Write-Host ("  quarterly_manifest : {0}" -f $OutPath)
Write-Host ("  quarterly_summary  : {0}" -f $SummaryOutPath)
Write-Host ("  quarterly_decision : {0}" -f [string]$summary.quarterly_decision)
if (-not [string]::IsNullOrWhiteSpace($archiveOutputPath)) {
    Write-Host ("  archive            : {0}" -f $archiveOutputPath)
}
