param(
    [string]$UpgradeImpactManifestPath = "",
    [string]$MigrationRehearsalManifestPath = "",
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

function Resolve-Or-DiscoverPath {
    param(
        [string]$RequestedPath,
        [string]$RootPath,
        [string]$Filter,
        [string]$Label
    )

    $requested = ([string]$RequestedPath).Trim()
    if (-not [string]::IsNullOrWhiteSpace($requested)) {
        $resolved = Resolve-OperatorAbsolutePath -Path $requested -BasePath $repoRoot
        if (-not (Test-Path $resolved)) {
            throw ("{0} path not found: {1}" -f $Label, $resolved)
        }
        return $resolved
    }

    if (-not (Test-Path $RootPath)) {
        throw ("{0} discovery root not found: {1}" -f $Label, $RootPath)
    }
    $latest = Get-ChildItem -Path $RootPath -Recurse -File -Filter $Filter |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($null -eq $latest) {
        throw ("No {0} file found with filter [{1}]." -f $Label, $Filter)
    }
    return $latest.FullName
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$resolvedLogsRoot = Resolve-OperatorAbsolutePath -Path $LogsRoot -BasePath $repoRoot

$resolvedOutputDir = ([string]$OutputDir).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedOutputDir)) {
    $resolvedOutputDir = Join-Path $repoRoot ("logs\ga-upgrade\rollback-safety-{0}" -f $timestamp)
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = Resolve-OperatorAbsolutePath -Path $resolvedOutputDir -BasePath $repoRoot
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "ga-upgrade-rollback-safety.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}

if ([string]::IsNullOrWhiteSpace($SummaryOutPath)) {
    $SummaryOutPath = Join-Path $resolvedOutputDir "ga-upgrade-rollback-safety.summary.json"
} elseif (-not [System.IO.Path]::IsPathRooted($SummaryOutPath)) {
    $SummaryOutPath = Resolve-OperatorAbsolutePath -Path $SummaryOutPath -BasePath $repoRoot
}

$upgradeRoot = Join-Path $resolvedLogsRoot "ga-upgrade"
$resolvedImpactManifestPath = Resolve-Or-DiscoverPath `
    -RequestedPath $UpgradeImpactManifestPath `
    -RootPath $upgradeRoot `
    -Filter "ga-upgrade-impact-matrix.manifest.json" `
    -Label "Upgrade impact manifest"

$resolvedRehearsalManifestPath = Resolve-Or-DiscoverPath `
    -RequestedPath $MigrationRehearsalManifestPath `
    -RootPath $upgradeRoot `
    -Filter "ga-migration-rehearsal-package.manifest.json" `
    -Label "Migration rehearsal manifest"

$impactManifest = Read-OperatorJsonFile -Path $resolvedImpactManifestPath
$rehearsalManifest = Read-OperatorJsonFile -Path $resolvedRehearsalManifestPath
if ([string]$impactManifest.bundle_type -ne "phase19_upgrade_impact_matrix") {
    Write-Error ("Unsupported impact matrix bundle_type [{0}] in {1}" -f ([string]$impactManifest.bundle_type), $resolvedImpactManifestPath)
    exit 1
}
if ([string]$rehearsalManifest.bundle_type -ne "phase19_migration_rehearsal_package") {
    Write-Error ("Unsupported migration rehearsal bundle_type [{0}] in {1}" -f ([string]$rehearsalManifest.bundle_type), $resolvedRehearsalManifestPath)
    exit 1
}

$controls = @(
    [ordered]@{ control_id = "backup_before_upgrade"; required = $true; status = "enforced"; evidence = ".\scripts\sqlite-backup.ps1 -Zip" },
    [ordered]@{ control_id = "restore_rehearsal_before_go"; required = $true; status = "enforced"; evidence = ".\scripts\sqlite-restore.ps1 -BackupZipPath <path> -Force" },
    [ordered]@{ control_id = "sqlite_verify_after_restore"; required = $true; status = "enforced"; evidence = ".\scripts\sqlite-verify.ps1" },
    [ordered]@{ control_id = "state_export_for_support"; required = $true; status = "enforced"; evidence = ".\scripts\sqlite-export.ps1" }
)

$rehearsalReady = Convert-OperatorToBool -Value $rehearsalManifest.summary.rehearsal_ready -Default $false
$impactDecision = ([string]$impactManifest.summary.upgrade_impact_decision).Trim().ToLowerInvariant()

$rollbackDecision = "go"
$decisionReasons = New-Object System.Collections.Generic.List[string]
if (-not $rehearsalReady) {
    $rollbackDecision = "watch"
    $decisionReasons.Add("Migration rehearsal package is not ready; rollback readiness cannot be promoted.") | Out-Null
}
if ($impactDecision -ne "go") {
    $rollbackDecision = "watch"
    $decisionReasons.Add("Upgrade impact matrix is not in go state; guarded rollback posture required.") | Out-Null
}
if ($decisionReasons.Count -eq 0) {
    $decisionReasons.Add("Upgrade impact and migration rehearsal both satisfy rollback-safety preconditions.") | Out-Null
}

$summary = [ordered]@{
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    source_upgrade_impact_manifest_path = $resolvedImpactManifestPath
    source_migration_rehearsal_manifest_path = $resolvedRehearsalManifestPath
    upgrade_impact_decision = $impactDecision
    rehearsal_ready = $rehearsalReady
    required_control_count = $controls.Count
    rollback_safety_decision = $rollbackDecision
    rollback_safety_decision_reasons = @($decisionReasons.ToArray())
}

Save-OperatorJson -Payload $summary -OutPath $SummaryOutPath

$manifest = [ordered]@{
    bundle_type = "phase19_upgrade_rollback_safety"
    bundle_version = 1
    generated_at_utc = $summary.generated_at_utc
    summary = $summary
    source = [ordered]@{
        upgrade_impact_manifest_path = $resolvedImpactManifestPath
        migration_rehearsal_manifest_path = $resolvedRehearsalManifestPath
    }
    details = [ordered]@{
        rollback_controls = $controls
        next_steps = @(
            "1) keep backup + export artifacts together with release package artifacts.",
            "2) require restore rehearsal evidence before any production-like migration run.",
            "3) rerun rollback safety package after each release-train candidate promotion."
        )
    }
}

Save-OperatorJson -Payload $manifest -OutPath $OutPath

$reportPath = Join-Path $resolvedOutputDir "ga-upgrade-rollback-safety.md"
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# GA Upgrade Rollback Safety") | Out-Null
$lines.Add("") | Out-Null
$lines.Add(("- generated_at_utc: {0}" -f $summary.generated_at_utc)) | Out-Null
$lines.Add(("- upgrade_impact_decision: {0}" -f [string]$summary.upgrade_impact_decision)) | Out-Null
$lines.Add(("- rehearsal_ready: {0}" -f [string]$summary.rehearsal_ready)) | Out-Null
$lines.Add(("- rollback_safety_decision: {0}" -f [string]$summary.rollback_safety_decision)) | Out-Null
$lines.Add("") | Out-Null
$lines.Add("## Required controls") | Out-Null
foreach ($control in $controls) {
    $lines.Add(("- {0}: status={1}" -f [string]$control.control_id, [string]$control.status)) | Out-Null
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

Write-Host "[done] ga upgrade rollback safety completed"
Write-Host ("  rollback_manifest : {0}" -f $OutPath)
Write-Host ("  rollback_summary  : {0}" -f $SummaryOutPath)
Write-Host ("  rollback_decision : {0}" -f [string]$summary.rollback_safety_decision)
if (-not [string]::IsNullOrWhiteSpace($archiveOutputPath)) {
    Write-Host ("  archive           : {0}" -f $archiveOutputPath)
}
