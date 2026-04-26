param(
    [string]$LogsRoot = "logs",
    [string]$QuarterlyReviewManifestPath = "",
    [string]$KnownIssuesPath = "docs/known_issues_register.md",
    [string]$ReadinessManifestPath = "",
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
$resolvedLogsRoot = Resolve-OperatorAbsolutePath -Path $LogsRoot -BasePath $repoRoot

$resolvedOutputDir = ([string]$OutputDir).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedOutputDir)) {
    $resolvedOutputDir = Join-Path $repoRoot ("logs\ga-upgrade\phase19-closeout-{0}" -f $timestamp)
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = Resolve-OperatorAbsolutePath -Path $resolvedOutputDir -BasePath $repoRoot
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "phase19-upgrade-evidence-closeout.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}

if ([string]::IsNullOrWhiteSpace($SummaryOutPath)) {
    $SummaryOutPath = Join-Path $resolvedOutputDir "phase19-upgrade-evidence-closeout.summary.json"
} elseif (-not [System.IO.Path]::IsPathRooted($SummaryOutPath)) {
    $SummaryOutPath = Resolve-OperatorAbsolutePath -Path $SummaryOutPath -BasePath $repoRoot
}

$impactManifestPath = Join-Path $resolvedOutputDir "ga-upgrade-impact-matrix.manifest.json"
$impactSummaryPath = Join-Path $resolvedOutputDir "ga-upgrade-impact-matrix.summary.json"
& (Join-Path $PSScriptRoot "ga-upgrade-impact-matrix.ps1") `
    -QuarterlyReviewManifestPath $QuarterlyReviewManifestPath `
    -KnownIssuesPath $KnownIssuesPath `
    -LogsRoot $resolvedLogsRoot `
    -OutputDir $resolvedOutputDir `
    -OutPath $impactManifestPath `
    -SummaryOutPath $impactSummaryPath

$rehearsalManifestPath = Join-Path $resolvedOutputDir "ga-migration-rehearsal-package.manifest.json"
$rehearsalSummaryPath = Join-Path $resolvedOutputDir "ga-migration-rehearsal-package.summary.json"
& (Join-Path $PSScriptRoot "ga-migration-rehearsal-package.ps1") `
    -UpgradeImpactManifestPath $impactManifestPath `
    -ReadinessManifestPath $ReadinessManifestPath `
    -LogsRoot $resolvedLogsRoot `
    -OutputDir $resolvedOutputDir `
    -OutPath $rehearsalManifestPath `
    -SummaryOutPath $rehearsalSummaryPath

$rollbackManifestPath = Join-Path $resolvedOutputDir "ga-upgrade-rollback-safety.manifest.json"
$rollbackSummaryPath = Join-Path $resolvedOutputDir "ga-upgrade-rollback-safety.summary.json"
& (Join-Path $PSScriptRoot "ga-upgrade-rollback-safety.ps1") `
    -UpgradeImpactManifestPath $impactManifestPath `
    -MigrationRehearsalManifestPath $rehearsalManifestPath `
    -LogsRoot $resolvedLogsRoot `
    -OutputDir $resolvedOutputDir `
    -OutPath $rollbackManifestPath `
    -SummaryOutPath $rollbackSummaryPath

$impact = Read-OperatorJsonFile -Path $impactManifestPath
$rehearsal = Read-OperatorJsonFile -Path $rehearsalManifestPath
$rollback = Read-OperatorJsonFile -Path $rollbackManifestPath

$closeoutDecision = "go"
$decisionReasons = New-Object System.Collections.Generic.List[string]
if ([string]$impact.summary.upgrade_impact_decision -ne "go") {
    $closeoutDecision = "watch"
    $decisionReasons.Add("Upgrade impact matrix is not go.") | Out-Null
}
if (-not (Convert-OperatorToBool -Value $rehearsal.summary.rehearsal_ready -Default $false)) {
    $closeoutDecision = "watch"
    $decisionReasons.Add("Migration rehearsal package is not ready.") | Out-Null
}
if ([string]$rollback.summary.rollback_safety_decision -ne "go") {
    $closeoutDecision = "watch"
    $decisionReasons.Add("Rollback safety package is not go.") | Out-Null
}
if ($decisionReasons.Count -eq 0) {
    $decisionReasons.Add("Upgrade impact, migration rehearsal, and rollback safety packages are in go state.") | Out-Null
}

$summary = [ordered]@{
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    impact_decision = [string]$impact.summary.upgrade_impact_decision
    rehearsal_decision = [string]$rehearsal.summary.rehearsal_decision
    rollback_decision = [string]$rollback.summary.rollback_safety_decision
    closeout_decision = $closeoutDecision
    closeout_decision_reasons = @($decisionReasons.ToArray())
}

Save-OperatorJson -Payload $summary -OutPath $SummaryOutPath

$manifest = [ordered]@{
    bundle_type = "phase19_upgrade_evidence_closeout"
    bundle_version = 1
    generated_at_utc = $summary.generated_at_utc
    summary = $summary
    source = [ordered]@{
        impact_manifest_path = $impactManifestPath
        rehearsal_manifest_path = $rehearsalManifestPath
        rollback_manifest_path = $rollbackManifestPath
    }
    details = [ordered]@{
        next_steps = @(
            "1) if closeout_decision=watch, resolve listed reasons before release-train promotion.",
            "2) attach closeout manifest to release governance decision package.",
            "3) rerun closeout package after each quarterly review refresh."
        )
    }
}

Save-OperatorJson -Payload $manifest -OutPath $OutPath

$reportPath = Join-Path $resolvedOutputDir "phase19-upgrade-evidence-closeout.md"
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# Phase 19 Upgrade Evidence Closeout") | Out-Null
$lines.Add("") | Out-Null
$lines.Add(("- generated_at_utc: {0}" -f $summary.generated_at_utc)) | Out-Null
$lines.Add(("- impact_decision: {0}" -f [string]$summary.impact_decision)) | Out-Null
$lines.Add(("- rehearsal_decision: {0}" -f [string]$summary.rehearsal_decision)) | Out-Null
$lines.Add(("- rollback_decision: {0}" -f [string]$summary.rollback_decision)) | Out-Null
$lines.Add(("- closeout_decision: {0}" -f [string]$summary.closeout_decision)) | Out-Null
$lines.Add("") | Out-Null
$lines.Add("## Decision reasons") | Out-Null
foreach ($reason in @($summary.closeout_decision_reasons)) {
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

Write-Host "[done] ga upgrade evidence closeout completed"
Write-Host ("  closeout_manifest : {0}" -f $OutPath)
Write-Host ("  closeout_summary  : {0}" -f $SummaryOutPath)
Write-Host ("  closeout_decision : {0}" -f [string]$summary.closeout_decision)
if (-not [string]::IsNullOrWhiteSpace($archiveOutputPath)) {
    Write-Host ("  archive           : {0}" -f $archiveOutputPath)
}
