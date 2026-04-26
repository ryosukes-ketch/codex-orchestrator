param(
    [string]$LogsRoot = "logs",
    [int]$WindowDays = 7,
    [string]$OutputDir = "",
    [string]$TrendManifestPath = "",
    [string]$HardeningManifestPath = "",
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

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$resolvedOutputDir = ([string]$OutputDir).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedOutputDir)) {
    $resolvedOutputDir = Join-Path $repoRoot ("logs\ga-adoption\weekly-review-{0}" -f $timestamp)
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = Resolve-OperatorAbsolutePath -Path $resolvedOutputDir -BasePath $repoRoot
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "ga-weekly-reliability-review.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}

if ([string]::IsNullOrWhiteSpace($SummaryOutPath)) {
    $SummaryOutPath = Join-Path $resolvedOutputDir "ga-weekly-reliability-review.summary.json"
} elseif (-not [System.IO.Path]::IsPathRooted($SummaryOutPath)) {
    $SummaryOutPath = Resolve-OperatorAbsolutePath -Path $SummaryOutPath -BasePath $repoRoot
}

function Resolve-Or-GenerateTrendManifest {
    param(
        [string]$RequestedPath,
        [string]$RepoRoot,
        [string]$LogsRootValue,
        [int]$WindowDaysValue,
        [string]$OutputRoot
    )

    $requested = ([string]$RequestedPath).Trim()
    if (-not [string]::IsNullOrWhiteSpace($requested)) {
        $resolved = Resolve-OperatorAbsolutePath -Path $requested -BasePath $RepoRoot
        if (-not (Test-Path $resolved)) {
            throw ("Trend manifest path not found: {0}" -f $resolved)
        }
        return $resolved
    }

    $trendDir = Join-Path $OutputRoot "trend"
    New-Item -ItemType Directory -Force -Path $trendDir | Out-Null
    $generatedPath = Join-Path $trendDir "launch-week-trend.manifest.json"

    & (Join-Path $PSScriptRoot "launch-week-trend-review.ps1") `
        -LogsRoot $LogsRootValue `
        -WindowDays $WindowDaysValue `
        -OutputDir $trendDir `
        -OutPath $generatedPath
    if (-not $?) {
        throw "launch-week-trend-review.ps1 failed while generating trend manifest."
    }

    if (-not (Test-Path $generatedPath)) {
        throw ("Generated trend manifest not found: {0}" -f $generatedPath)
    }
    return $generatedPath
}

function Resolve-Or-GenerateHardeningManifest {
    param(
        [string]$RequestedPath,
        [string]$RepoRoot,
        [string]$TrendManifest,
        [int]$WindowDaysValue,
        [string]$LogsRootValue,
        [string]$OutputRoot
    )

    $requested = ([string]$RequestedPath).Trim()
    if (-not [string]::IsNullOrWhiteSpace($requested)) {
        $resolved = Resolve-OperatorAbsolutePath -Path $requested -BasePath $RepoRoot
        if (-not (Test-Path $resolved)) {
            throw ("Hardening manifest path not found: {0}" -f $resolved)
        }
        return $resolved
    }

    $hardeningDir = Join-Path $OutputRoot "hardening"
    New-Item -ItemType Directory -Force -Path $hardeningDir | Out-Null
    $generatedPath = Join-Path $hardeningDir "recurring-issue-hardening.manifest.json"

    & (Join-Path $PSScriptRoot "support-recurring-hardening.ps1") `
        -TrendManifestPath $TrendManifest `
        -LogsRoot $LogsRootValue `
        -WindowDays $WindowDaysValue `
        -OutputDir $hardeningDir `
        -OutPath $generatedPath
    if (-not $?) {
        throw "support-recurring-hardening.ps1 failed while generating recurring hardening manifest."
    }

    if (-not (Test-Path $generatedPath)) {
        throw ("Generated hardening manifest not found: {0}" -f $generatedPath)
    }
    return $generatedPath
}

function Get-ReliabilityRecommendation {
    param(
        [int]$P1ActionCount,
        [int]$RecurringCategoryCount,
        [int]$SchemaIssueCount
    )

    if ($P1ActionCount -gt 0 -or $SchemaIssueCount -gt 0) {
        return "urgent_hardening_cycle"
    }
    if ($RecurringCategoryCount -gt 0) {
        return "targeted_hardening_cycle"
    }
    return "monitor_only_cycle"
}

$resolvedTrendManifestPath = Resolve-Or-GenerateTrendManifest `
    -RequestedPath $TrendManifestPath `
    -RepoRoot $repoRoot `
    -LogsRootValue $LogsRoot `
    -WindowDaysValue $WindowDays `
    -OutputRoot $resolvedOutputDir
$trend = Read-OperatorJsonFile -Path $resolvedTrendManifestPath
if ([string]$trend.bundle_type -ne "phase12_launch_week_support_trend_review") {
    Write-Error ("Unsupported trend bundle_type [{0}] in {1}" -f ([string]$trend.bundle_type), $resolvedTrendManifestPath)
    exit 1
}

$resolvedHardeningManifestPath = Resolve-Or-GenerateHardeningManifest `
    -RequestedPath $HardeningManifestPath `
    -RepoRoot $repoRoot `
    -TrendManifest $resolvedTrendManifestPath `
    -WindowDaysValue $WindowDays `
    -LogsRootValue $LogsRoot `
    -OutputRoot $resolvedOutputDir
$hardening = Read-OperatorJsonFile -Path $resolvedHardeningManifestPath
if ([string]$hardening.bundle_type -ne "phase12_recurring_issue_pattern_hardening") {
    Write-Error ("Unsupported hardening bundle_type [{0}] in {1}" -f ([string]$hardening.bundle_type), $resolvedHardeningManifestPath)
    exit 1
}

$topCategories = @($trend.top_recurring_categories)
$hardeningActions = @($hardening.hardening_actions)
$p1Actions = @($hardeningActions | Where-Object { ([string]$_.priority).Trim().ToUpperInvariant() -eq "P1" })
$schemaIssueCount = Convert-OperatorToInt -Value $hardening.evidence_quality.schema_issue_count -Default 0
$supportBundleCount = Convert-OperatorToInt -Value $trend.support_bundle_count -Default 0

$recommendation = Get-ReliabilityRecommendation `
    -P1ActionCount $p1Actions.Count `
    -RecurringCategoryCount $topCategories.Count `
    -SchemaIssueCount $schemaIssueCount

$summary = [ordered]@{
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    support_bundle_count = $supportBundleCount
    top_recurring_category_count = $topCategories.Count
    hardening_action_count = $hardeningActions.Count
    p1_hardening_action_count = $p1Actions.Count
    schema_issue_count = $schemaIssueCount
    recommendation = $recommendation
}

$manifest = [ordered]@{
    bundle_type = "phase16_ga_weekly_reliability_review"
    bundle_version = 1
    generated_at_utc = $summary.generated_at_utc
    analysis_window_utc = $trend.analysis_window_utc
    summary = $summary
    source = [ordered]@{
        logs_root = (Resolve-OperatorAbsolutePath -Path $LogsRoot -BasePath $repoRoot)
        trend_manifest_path = $resolvedTrendManifestPath
        hardening_manifest_path = $resolvedHardeningManifestPath
    }
    details = [ordered]@{
        top_recurring_categories = $topCategories
        hardening_actions = $hardeningActions
        schema_issues = @($hardening.schema_issues)
        next_steps = @(
            "1) review p1_hardening_action_count and schema_issue_count in weekly reliability summary",
            "2) apply runbook deltas for top recurring categories before next GA-week cycle",
            "3) rerun ga-weekly-reliability-review.ps1 after support-cycle close and compare recommendation drift"
        )
    }
}

Save-OperatorJson -Payload $manifest -OutPath $OutPath
Save-OperatorJson -Payload $summary -OutPath $SummaryOutPath

$reportPath = Join-Path $resolvedOutputDir "ga-weekly-reliability-review.md"
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# GA Weekly Reliability Review") | Out-Null
$lines.Add("") | Out-Null
$lines.Add(("- generated_at_utc: {0}" -f $summary.generated_at_utc)) | Out-Null
$lines.Add(("- support_bundle_count: {0}" -f [int]$summary.support_bundle_count)) | Out-Null
$lines.Add(("- top_recurring_category_count: {0}" -f [int]$summary.top_recurring_category_count)) | Out-Null
$lines.Add(("- hardening_action_count: {0}" -f [int]$summary.hardening_action_count)) | Out-Null
$lines.Add(("- p1_hardening_action_count: {0}" -f [int]$summary.p1_hardening_action_count)) | Out-Null
$lines.Add(("- schema_issue_count: {0}" -f [int]$summary.schema_issue_count)) | Out-Null
$lines.Add(("- recommendation: {0}" -f [string]$summary.recommendation)) | Out-Null
$lines.Add("") | Out-Null
$lines.Add("## Source manifests") | Out-Null
$lines.Add(("- trend_manifest: {0}" -f (Get-OperatorRelativePath -Path $resolvedTrendManifestPath -RootPath $repoRoot))) | Out-Null
$lines.Add(("- hardening_manifest: {0}" -f (Get-OperatorRelativePath -Path $resolvedHardeningManifestPath -RootPath $repoRoot))) | Out-Null
$lines.Add(("- weekly_review_manifest: {0}" -f (Get-OperatorRelativePath -Path $OutPath -RootPath $repoRoot))) | Out-Null
$lines.Add(("- weekly_review_summary: {0}" -f (Get-OperatorRelativePath -Path $SummaryOutPath -RootPath $repoRoot))) | Out-Null
$lines.Add("") | Out-Null
$lines.Add("## Top recurring categories") | Out-Null
if ($topCategories.Count -eq 0) {
    $lines.Add("- none") | Out-Null
} else {
    foreach ($item in $topCategories) {
        $lines.Add(("- {0}: occurrences={1}, bundles={2}" -f ([string]$item.category), (Convert-OperatorToInt -Value $item.total_occurrences -Default 0), (Convert-OperatorToInt -Value $item.impacted_bundle_count -Default 0))) | Out-Null
    }
}
$lines.Add("") | Out-Null
$lines.Add("## P1 hardening actions") | Out-Null
if ($p1Actions.Count -eq 0) {
    $lines.Add("- none") | Out-Null
} else {
    foreach ($item in $p1Actions) {
        $lines.Add(("- {0}: {1}" -f ([string]$item.action_id), ([string]$item.runbook_delta))) | Out-Null
    }
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

Write-Host "[done] ga weekly reliability review completed"
Write-Host ("  trend_manifest     : {0}" -f $resolvedTrendManifestPath)
Write-Host ("  hardening_manifest : {0}" -f $resolvedHardeningManifestPath)
Write-Host ("  review_manifest    : {0}" -f $OutPath)
Write-Host ("  review_summary     : {0}" -f $SummaryOutPath)
Write-Host ("  recommendation     : {0}" -f [string]$summary.recommendation)
if (-not [string]::IsNullOrWhiteSpace($archiveOutputPath)) {
    Write-Host ("  archive            : {0}" -f $archiveOutputPath)
}
