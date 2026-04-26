param(
    [string]$GaLaunchManifestPath = "",
    [string]$ReadinessManifestPath = "",
    [string]$BundleManifestPath = "",
    [string]$SupportBundleManifestPath = "",
    [string]$KnownIssuesPath = "docs/known_issues_register.md",
    [int]$WindowDays = 7,
    [string]$OutputDir = "",
    [switch]$Zip,
    [string]$ArchivePath = "",
    [string]$OutPath = "",
    [string]$SummaryOutPath = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. (Join-Path $PSScriptRoot "operator-common.ps1")

if ($WindowDays -lt 1) {
    Write-Error "-WindowDays must be >= 1."
    exit 1
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

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$resolvedOutputDir = ([string]$OutputDir).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedOutputDir)) {
    $resolvedOutputDir = Join-Path $repoRoot ("logs\ga-launch\early-ops-incident-loop-{0}" -f $timestamp)
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = Resolve-OperatorAbsolutePath -Path $resolvedOutputDir -BasePath $repoRoot
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "early-ops-incident-loop.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}

if ([string]::IsNullOrWhiteSpace($SummaryOutPath)) {
    $SummaryOutPath = Join-Path $resolvedOutputDir "early-ops-incident-summary.json"
} elseif (-not [System.IO.Path]::IsPathRooted($SummaryOutPath)) {
    $SummaryOutPath = Resolve-OperatorAbsolutePath -Path $SummaryOutPath -BasePath $repoRoot
}

$resolvedGaLaunchManifestPath = Resolve-OptionalPath -PathValue $GaLaunchManifestPath -BasePath $repoRoot
if ([string]::IsNullOrWhiteSpace($resolvedGaLaunchManifestPath)) {
    $resolvedGaLaunchManifestPath = Resolve-LatestManifestPath `
        -SearchRoot (Join-Path $repoRoot "logs\ga-launch") `
        -Filter "ga-launch-package.manifest.json"
}

$resolvedReadinessManifestPath = Resolve-OptionalPath -PathValue $ReadinessManifestPath -BasePath $repoRoot
$resolvedBundleManifestPath = Resolve-OptionalPath -PathValue $BundleManifestPath -BasePath $repoRoot
$resolvedSupportBundleManifestPath = Resolve-OptionalPath -PathValue $SupportBundleManifestPath -BasePath $repoRoot
$resolvedKnownIssuesPath = Resolve-OptionalPath -PathValue $KnownIssuesPath -BasePath $repoRoot

if (-not [string]::IsNullOrWhiteSpace($resolvedGaLaunchManifestPath) -and (Test-Path $resolvedGaLaunchManifestPath)) {
    $gaLaunchManifest = Read-OperatorJsonFile -Path $resolvedGaLaunchManifestPath
    if ([string]$gaLaunchManifest.bundle_type -ne "phase15_ga_launch_execution_package") {
        Write-Error ("Unexpected ga launch manifest bundle_type: {0}" -f [string]$gaLaunchManifest.bundle_type)
        exit 1
    }
}

if (
    [string]::IsNullOrWhiteSpace($resolvedSupportBundleManifestPath) `
        -and [string]::IsNullOrWhiteSpace($resolvedReadinessManifestPath) `
        -and [string]::IsNullOrWhiteSpace($resolvedBundleManifestPath)
) {
    $resolvedReadinessManifestPath = Resolve-LatestManifestPath `
        -SearchRoot (Join-Path $repoRoot "logs\operational-readiness") `
        -Filter "readiness-manifest-*.json"
}

$supportBundleOutputDir = Join-Path $resolvedOutputDir "support-bundle"
$supportBundleManifestPath = Join-Path $resolvedOutputDir "support-bundle.manifest.json"
if (-not [string]::IsNullOrWhiteSpace($resolvedSupportBundleManifestPath)) {
    $supportBundleManifestPath = $resolvedSupportBundleManifestPath
    if (-not (Test-Path $supportBundleManifestPath)) {
        Write-Error ("Support bundle manifest not found: {0}" -f $supportBundleManifestPath)
        exit 1
    }
} else {
    $supportArgs = @{
        OutputDir = $supportBundleOutputDir
        OutPath = $supportBundleManifestPath
    }
    if (-not [string]::IsNullOrWhiteSpace($resolvedReadinessManifestPath)) {
        $supportArgs.ReadinessManifestPath = $resolvedReadinessManifestPath
    }
    if (-not [string]::IsNullOrWhiteSpace($resolvedBundleManifestPath)) {
        $supportArgs.BundleManifestPath = $resolvedBundleManifestPath
    }
    & (Join-Path $PSScriptRoot "operator-support-bundle.ps1") @supportArgs
    if (-not $?) {
        exit 1
    }
}

$supportIntakeOutputDir = Join-Path $resolvedOutputDir "support-intake"
$supportIntakeManifestPath = Join-Path $resolvedOutputDir "support-intake.manifest.json"
$supportIntakeArgs = @{
    SupportBundleManifestPath = $supportBundleManifestPath
    OutputDir = $supportIntakeOutputDir
    OutPath = $supportIntakeManifestPath
}
& (Join-Path $PSScriptRoot "self-serve-support-intake.ps1") @supportIntakeArgs
if (-not $?) {
    exit 1
}

$trendOutputDir = Join-Path $resolvedOutputDir "launch-week-trend"
$trendManifestPath = Join-Path $resolvedOutputDir "launch-week-trend.manifest.json"
$trendArgs = @{
    WindowDays = $WindowDays
    OutputDir = $trendOutputDir
    OutPath = $trendManifestPath
    TrendDocPath = "docs/launch_week_support_trend_review.md"
    BacklogDocPath = "docs/launch_week_runbook_delta_backlog.md"
}
if (Test-Path (Split-Path -Parent $supportBundleManifestPath)) {
    $trendArgs.LogsRoot = (Split-Path -Parent $supportBundleManifestPath)
}
& (Join-Path $PSScriptRoot "launch-week-trend-review.ps1") @trendArgs
if (-not $?) {
    exit 1
}

$recurringOutputDir = Join-Path $resolvedOutputDir "recurring-hardening"
$recurringManifestPath = Join-Path $resolvedOutputDir "recurring-issue-hardening.manifest.json"
$recurringArgs = @{
    TrendManifestPath = $trendManifestPath
    OutputDir = $recurringOutputDir
    OutPath = $recurringManifestPath
    ReportDocPath = "docs/phase12_recurring_issue_hardening.md"
}
& (Join-Path $PSScriptRoot "support-recurring-hardening.ps1") @recurringArgs
if (-not $?) {
    exit 1
}

$supportBundle = Read-OperatorJsonFile -Path $supportBundleManifestPath
$supportIntake = Read-OperatorJsonFile -Path $supportIntakeManifestPath
$trend = Read-OperatorJsonFile -Path $trendManifestPath
$recurring = Read-OperatorJsonFile -Path $recurringManifestPath

$summary = [ordered]@{
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    support_bundle_classification_status = [string]$supportBundle.classification_status
    support_bundle_has_blocking_findings = Convert-OperatorToBool -Value $supportBundle.has_blocking_findings -Default $false
    support_bundle_finding_count = Convert-OperatorToInt -Value $supportBundle.finding_count -Default 0
    support_intake_classification_status = [string]$supportIntake.classification_status
    support_intake_finding_count = Convert-OperatorToInt -Value $supportIntake.finding_count -Default 0
    launch_week_support_bundle_count = Convert-OperatorToInt -Value $trend.support_bundle_count -Default 0
    launch_week_top_recurring_category_count = @($trend.top_recurring_categories).Count
    recurring_hardening_action_count = @($recurring.hardening_actions).Count
    recurring_signal_count = Convert-OperatorToInt -Value $recurring.recurring_signal_count -Default 0
}
Save-OperatorJson -Payload $summary -OutPath $SummaryOutPath

$archiveOutputPath = ""
if ($Zip) {
    $archiveOutputPath = ([string]$ArchivePath).Trim()
    if ([string]::IsNullOrWhiteSpace($archiveOutputPath)) {
        $archiveOutputPath = $resolvedOutputDir.TrimEnd("\") + ".zip"
    } elseif (-not [System.IO.Path]::IsPathRooted($archiveOutputPath)) {
        $archiveOutputPath = Resolve-OperatorAbsolutePath -Path $archiveOutputPath -BasePath $repoRoot
    }
    if (Test-Path $archiveOutputPath) {
        Remove-Item -Path $archiveOutputPath -Force
    }
    Compress-Archive -Path (Join-Path $resolvedOutputDir "*") -DestinationPath $archiveOutputPath -Force
}

$markdownPath = Join-Path $resolvedOutputDir "early-ops-incident-summary.md"
$markdown = New-Object System.Collections.Generic.List[string]
$markdown.Add("# Early Operations Incident Loop Summary") | Out-Null
$markdown.Add("") | Out-Null
$markdown.Add(("- generated_at_utc: {0}" -f $summary.generated_at_utc)) | Out-Null
$markdown.Add(("- support_bundle_classification_status: {0}" -f $summary.support_bundle_classification_status)) | Out-Null
$markdown.Add(("- support_bundle_has_blocking_findings: {0}" -f $summary.support_bundle_has_blocking_findings)) | Out-Null
$markdown.Add(("- support_bundle_finding_count: {0}" -f $summary.support_bundle_finding_count)) | Out-Null
$markdown.Add(("- launch_week_support_bundle_count: {0}" -f $summary.launch_week_support_bundle_count)) | Out-Null
$markdown.Add(("- launch_week_top_recurring_category_count: {0}" -f $summary.launch_week_top_recurring_category_count)) | Out-Null
$markdown.Add(("- recurring_hardening_action_count: {0}" -f $summary.recurring_hardening_action_count)) | Out-Null
$markdown.Add("") | Out-Null
$markdown.Add("## Artifacts") | Out-Null
$markdown.Add(("- support_bundle_manifest: {0}" -f (Get-OperatorRelativePath -Path $supportBundleManifestPath -RootPath $repoRoot))) | Out-Null
$markdown.Add(("- support_intake_manifest: {0}" -f (Get-OperatorRelativePath -Path $supportIntakeManifestPath -RootPath $repoRoot))) | Out-Null
$markdown.Add(("- launch_week_trend_manifest: {0}" -f (Get-OperatorRelativePath -Path $trendManifestPath -RootPath $repoRoot))) | Out-Null
$markdown.Add(("- recurring_hardening_manifest: {0}" -f (Get-OperatorRelativePath -Path $recurringManifestPath -RootPath $repoRoot))) | Out-Null
[System.IO.File]::WriteAllLines($markdownPath, $markdown, [System.Text.Encoding]::UTF8)

$manifest = [ordered]@{
    bundle_type = "phase15_early_operations_incident_loop"
    bundle_version = 1
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    output_dir = $resolvedOutputDir
    summary = $summary
    source_inputs = [ordered]@{
        ga_launch_manifest_path = $resolvedGaLaunchManifestPath
        readiness_manifest_path = $resolvedReadinessManifestPath
        bundle_manifest_path = $resolvedBundleManifestPath
        known_issues_path = $resolvedKnownIssuesPath
        window_days = $WindowDays
    }
    artifacts = [ordered]@{
        support_bundle_manifest = New-OperatorManifestArtifactEntry -Path $supportBundleManifestPath -RepoRoot $repoRoot
        support_intake_manifest = New-OperatorManifestArtifactEntry -Path $supportIntakeManifestPath -RepoRoot $repoRoot
        launch_week_trend_manifest = New-OperatorManifestArtifactEntry -Path $trendManifestPath -RepoRoot $repoRoot
        recurring_hardening_manifest = New-OperatorManifestArtifactEntry -Path $recurringManifestPath -RepoRoot $repoRoot
        incident_summary_json = New-OperatorManifestArtifactEntry -Path $SummaryOutPath -RepoRoot $repoRoot
        incident_summary_markdown = New-OperatorManifestArtifactEntry -Path $markdownPath -RepoRoot $repoRoot
    }
    archive_path = $archiveOutputPath
    next_steps = @(
        "1) Route recurring hardening outputs into hotfix/next-release stabilization.",
        "2) Record blocking findings and escalation ownership for launch-week operations.",
        "3) Attach incident loop package to phase15 closeout evidence."
    )
}

Save-OperatorJson -Payload $manifest -OutPath $OutPath

Write-Host "[done] early operations incident loop completed"
Write-Host ("  support_bundle : {0}" -f $supportBundleManifestPath)
Write-Host ("  trend_manifest : {0}" -f $trendManifestPath)
Write-Host ("  recurring      : {0}" -f $recurringManifestPath)
Write-Host ("  summary_json   : {0}" -f $SummaryOutPath)
Write-Host ("  manifest       : {0}" -f $OutPath)
