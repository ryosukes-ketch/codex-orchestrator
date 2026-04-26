param(
    [string]$OutputDir = "",
    [string]$OutPath = "",
    [string]$SummaryOutPath = "",
    [switch]$Zip
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. (Join-Path $PSScriptRoot "operator-common.ps1")

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$resolvedOutputDir = ([string]$OutputDir).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedOutputDir)) {
    $resolvedOutputDir = Join-Path $repoRoot ("logs\ga-steady-state\cadence-baseline-{0}" -f $timestamp)
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = Resolve-OperatorAbsolutePath -Path $resolvedOutputDir -BasePath $repoRoot
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "ga-release-ops-cadence-baseline.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}

if ([string]::IsNullOrWhiteSpace($SummaryOutPath)) {
    $SummaryOutPath = Join-Path $resolvedOutputDir "ga-release-ops-cadence-baseline.summary.json"
} elseif (-not [System.IO.Path]::IsPathRooted($SummaryOutPath)) {
    $SummaryOutPath = Resolve-OperatorAbsolutePath -Path $SummaryOutPath -BasePath $repoRoot
}

$cadence = @(
    [ordered]@{
        cadence = "weekly"
        owner = "operations"
        command = ".\scripts\ga-weekly-reliability-review.ps1 -WindowDays 7 -Zip"
        output_bundle = "phase16_ga_weekly_reliability_review"
    },
    [ordered]@{
        cadence = "monthly"
        owner = "customer_success"
        command = ".\scripts\ga-monthly-reliability-targets.ps1 -WindowDays 30 -Zip"
        output_bundle = "phase17_ga_monthly_reliability_target_package"
    },
    [ordered]@{
        cadence = "quarterly"
        owner = "governance"
        command = ".\scripts\ga-quarterly-review-package.ps1 -Zip"
        output_bundle = "phase18_quarterly_review_package"
    },
    [ordered]@{
        cadence = "release"
        owner = "release_manager"
        command = ".\scripts\release-train-evidence-export.ps1 -Zip"
        output_bundle = "phase14_release_train_evidence_export"
    }
)

$summary = [ordered]@{
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    cadence_count = $cadence.Count
    cadence_decision = "go"
}
Save-OperatorJson -Payload $summary -OutPath $SummaryOutPath

$manifest = [ordered]@{
    bundle_type = "phase22_release_ops_cadence_baseline"
    bundle_version = 1
    generated_at_utc = $summary.generated_at_utc
    summary = $summary
    details = [ordered]@{
        cadence_entries = $cadence
        next_steps = @(
            "1) apply cadence entries in steady-state operations handbook.",
            "2) ensure each cadence output is captured in retention/traceability index.",
            "3) include cadence baseline in phase22 closeout evidence."
        )
    }
}
Save-OperatorJson -Payload $manifest -OutPath $OutPath

$reportPath = Join-Path $resolvedOutputDir "ga-release-ops-cadence-baseline.md"
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# GA Release/Ops Cadence Baseline") | Out-Null
$lines.Add("") | Out-Null
$lines.Add(("- generated_at_utc: {0}" -f $summary.generated_at_utc)) | Out-Null
$lines.Add(("- cadence_count: {0}" -f [int]$summary.cadence_count)) | Out-Null
$lines.Add(("- cadence_decision: {0}" -f [string]$summary.cadence_decision)) | Out-Null
$lines.Add("") | Out-Null
$lines.Add("## Cadence entries") | Out-Null
foreach ($entry in @($cadence)) {
    $lines.Add(("- {0} ({1}) -> {2}" -f [string]$entry.cadence, [string]$entry.owner, [string]$entry.command)) | Out-Null
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

Write-Host "[done] ga release/ops cadence baseline completed"
Write-Host ("  cadence_manifest : {0}" -f $OutPath)
Write-Host ("  cadence_summary  : {0}" -f $SummaryOutPath)
if (-not [string]::IsNullOrWhiteSpace($archiveOutputPath)) {
    Write-Host ("  archive          : {0}" -f $archiveOutputPath)
}

