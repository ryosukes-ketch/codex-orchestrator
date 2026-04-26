param(
    [string]$UpgradeImpactManifestPath = "",
    [string]$ReadinessManifestPath = "",
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
    $resolvedOutputDir = Join-Path $repoRoot ("logs\ga-upgrade\migration-rehearsal-{0}" -f $timestamp)
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = Resolve-OperatorAbsolutePath -Path $resolvedOutputDir -BasePath $repoRoot
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "ga-migration-rehearsal-package.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}

if ([string]::IsNullOrWhiteSpace($SummaryOutPath)) {
    $SummaryOutPath = Join-Path $resolvedOutputDir "ga-migration-rehearsal-package.summary.json"
} elseif (-not [System.IO.Path]::IsPathRooted($SummaryOutPath)) {
    $SummaryOutPath = Resolve-OperatorAbsolutePath -Path $SummaryOutPath -BasePath $repoRoot
}

$impactRoot = Join-Path $resolvedLogsRoot "ga-upgrade"
$resolvedImpactManifestPath = Resolve-Or-DiscoverPath `
    -RequestedPath $UpgradeImpactManifestPath `
    -RootPath $impactRoot `
    -Filter "ga-upgrade-impact-matrix.manifest.json" `
    -Label "Upgrade impact manifest"

$readinessRoot = Join-Path $resolvedLogsRoot "operational-readiness"
$resolvedReadinessManifestPath = Resolve-Or-DiscoverPath `
    -RequestedPath $ReadinessManifestPath `
    -RootPath $readinessRoot `
    -Filter "readiness-manifest-*.json" `
    -Label "Readiness manifest"

$impactManifest = Read-OperatorJsonFile -Path $resolvedImpactManifestPath
if ([string]$impactManifest.bundle_type -ne "phase19_upgrade_impact_matrix") {
    Write-Error ("Unsupported impact matrix bundle_type [{0}] in {1}" -f ([string]$impactManifest.bundle_type), $resolvedImpactManifestPath)
    exit 1
}

$readinessManifest = Read-OperatorJsonFile -Path $resolvedReadinessManifestPath
$readinessDecision = ([string]$readinessManifest.summary.readiness_decision).Trim().ToUpperInvariant()
if ([string]::IsNullOrWhiteSpace($readinessDecision)) {
    $readinessDecision = "UNKNOWN"
}

$backupScriptPath = Join-Path $repoRoot "scripts/sqlite-backup.ps1"
$restoreScriptPath = Join-Path $repoRoot "scripts/sqlite-restore.ps1"
$verifyScriptPath = Join-Path $repoRoot "scripts/sqlite-verify.ps1"
$exportScriptPath = Join-Path $repoRoot "scripts/sqlite-export.ps1"

$rehearsalSteps = @(
    [ordered]@{
        step = 1
        name = "backup"
        command = ".\scripts\sqlite-backup.ps1 -Zip"
        required = $true
        script_present = Test-Path $backupScriptPath
    },
    [ordered]@{
        step = 2
        name = "verify_pre_migration"
        command = ".\scripts\sqlite-verify.ps1"
        required = $true
        script_present = Test-Path $verifyScriptPath
    },
    [ordered]@{
        step = 3
        name = "export_snapshot"
        command = ".\scripts\sqlite-export.ps1"
        required = $true
        script_present = Test-Path $exportScriptPath
    },
    [ordered]@{
        step = 4
        name = "restore_rehearsal"
        command = ".\scripts\sqlite-restore.ps1 -BackupZipPath <path> -Force"
        required = $true
        script_present = Test-Path $restoreScriptPath
    }
)

$missingStepScripts = @($rehearsalSteps | Where-Object { -not (Convert-OperatorToBool -Value $_.script_present -Default $false) })
$rehearsalReady = $missingStepScripts.Count -eq 0
$rehearsalDecision = "go"
$decisionReasons = New-Object System.Collections.Generic.List[string]
if (-not $rehearsalReady) {
    $rehearsalDecision = "watch"
    $decisionReasons.Add("At least one required sqlite operation script is missing for rehearsal.") | Out-Null
}
if ($readinessDecision -ne "GO") {
    $rehearsalDecision = "watch"
    $decisionReasons.Add("Readiness decision is not GO; run readiness remediation before migration rehearsal.") | Out-Null
}
if ($decisionReasons.Count -eq 0) {
    $decisionReasons.Add("Prerequisite scripts and readiness signal are available for migration rehearsal.") | Out-Null
}

$summary = [ordered]@{
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    source_upgrade_impact_manifest_path = $resolvedImpactManifestPath
    source_readiness_manifest_path = $resolvedReadinessManifestPath
    readiness_decision = $readinessDecision
    upgrade_impact_decision = [string]$impactManifest.summary.upgrade_impact_decision
    rehearsal_ready = $rehearsalReady
    missing_required_script_count = $missingStepScripts.Count
    rehearsal_step_count = $rehearsalSteps.Count
    rehearsal_decision = $rehearsalDecision
    rehearsal_decision_reasons = @($decisionReasons.ToArray())
}

Save-OperatorJson -Payload $summary -OutPath $SummaryOutPath

$manifest = [ordered]@{
    bundle_type = "phase19_migration_rehearsal_package"
    bundle_version = 1
    generated_at_utc = $summary.generated_at_utc
    summary = $summary
    source = [ordered]@{
        upgrade_impact_manifest_path = $resolvedImpactManifestPath
        readiness_manifest_path = $resolvedReadinessManifestPath
    }
    details = [ordered]@{
        rehearsal_steps = @($rehearsalSteps)
        missing_required_scripts = @(
            $missingStepScripts | ForEach-Object { [string]$_.name }
        )
        next_steps = @(
            "1) run rehearsal steps in order on a non-production copy.",
            "2) verify sqlite integrity after restore before upgrade promotion.",
            "3) attach rehearsal outputs to ga-upgrade-evidence-closeout.ps1 bundle."
        )
    }
}

Save-OperatorJson -Payload $manifest -OutPath $OutPath

$reportPath = Join-Path $resolvedOutputDir "ga-migration-rehearsal-package.md"
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# GA Migration Rehearsal Package") | Out-Null
$lines.Add("") | Out-Null
$lines.Add(("- generated_at_utc: {0}" -f $summary.generated_at_utc)) | Out-Null
$lines.Add(("- readiness_decision: {0}" -f [string]$summary.readiness_decision)) | Out-Null
$lines.Add(("- rehearsal_ready: {0}" -f [string]$summary.rehearsal_ready)) | Out-Null
$lines.Add(("- missing_required_script_count: {0}" -f [int]$summary.missing_required_script_count)) | Out-Null
$lines.Add(("- rehearsal_decision: {0}" -f [string]$summary.rehearsal_decision)) | Out-Null
$lines.Add("") | Out-Null
$lines.Add("## Steps") | Out-Null
foreach ($step in $rehearsalSteps) {
    $lines.Add(("- step {0} [{1}] required={2} script_present={3}" -f [int]$step.step, [string]$step.name, [string]$step.required, [string]$step.script_present)) | Out-Null
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

Write-Host "[done] ga migration rehearsal package completed"
Write-Host ("  rehearsal_manifest : {0}" -f $OutPath)
Write-Host ("  rehearsal_summary  : {0}" -f $SummaryOutPath)
Write-Host ("  rehearsal_decision : {0}" -f [string]$summary.rehearsal_decision)
if (-not [string]::IsNullOrWhiteSpace($archiveOutputPath)) {
    Write-Host ("  archive            : {0}" -f $archiveOutputPath)
}
