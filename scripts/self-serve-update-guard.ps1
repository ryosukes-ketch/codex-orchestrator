param(
    [string]$SqliteDbPath = "",
    [string]$BackupDir = "",
    [string]$ReadinessManifestPath = "",
    [string]$BundleManifestPath = "",
    [string]$OutputDir = "",
    [switch]$Zip,
    [string]$ArchivePath = "",
    [string]$OutPath = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if (
    -not [string]::IsNullOrWhiteSpace($ReadinessManifestPath) `
        -and -not [string]::IsNullOrWhiteSpace($BundleManifestPath)
) {
    Write-Error "Specify only one of -ReadinessManifestPath or -BundleManifestPath."
    exit 1
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$resolvedOutputDir = ([string]$OutputDir).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedOutputDir)) {
    $resolvedOutputDir = Join-Path $repoRoot ("logs\self-serve\update-guard-{0}" -f $timestamp)
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $resolvedOutputDir))
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

$verifyReportPath = Join-Path $resolvedOutputDir "sqlite-verify.report.json"
$backupManifestPath = Join-Path $resolvedOutputDir "sqlite-backup.manifest.json"
$exportDir = Join-Path $resolvedOutputDir "sqlite-export"
$exportManifestPath = Join-Path $resolvedOutputDir "sqlite-export.manifest.json"
$replayManifestPath = Join-Path $resolvedOutputDir "replay-export.manifest.json"
$replayDir = Join-Path $resolvedOutputDir "replay-export"

$verifyArgs = @{
    SqliteDbPath = $SqliteDbPath
    OutPath = $verifyReportPath
}
& (Join-Path $PSScriptRoot "sqlite-verify.ps1") @verifyArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$backupArgs = @{
    SqliteDbPath = $SqliteDbPath
    BackupDir = $BackupDir
    Label = "self-serve-pre-update"
    OutPath = $backupManifestPath
}
& (Join-Path $PSScriptRoot "sqlite-backup.ps1") @backupArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$exportArgs = @{
    SqliteDbPath = $SqliteDbPath
    BackupDir = $BackupDir
    OutputDir = $exportDir
    Label = "self-serve-pre-update"
    OutPath = $exportManifestPath
}
& (Join-Path $PSScriptRoot "sqlite-export.ps1") @exportArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$replayGenerated = $false
if (
    -not [string]::IsNullOrWhiteSpace($ReadinessManifestPath) `
        -or -not [string]::IsNullOrWhiteSpace($BundleManifestPath)
) {
    $replayArgs = @{
        OutputDir = $replayDir
        OutPath = $replayManifestPath
    }
    if (-not [string]::IsNullOrWhiteSpace($ReadinessManifestPath)) {
        $replayArgs.ReadinessManifestPath = $ReadinessManifestPath
    }
    if (-not [string]::IsNullOrWhiteSpace($BundleManifestPath)) {
        $replayArgs.BundleManifestPath = $BundleManifestPath
    }
    & (Join-Path $PSScriptRoot "operator-replay-export.ps1") @replayArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $replayGenerated = $true
}

$archiveOutputPath = ""
if ($Zip) {
    $archiveOutputPath = ([string]$ArchivePath).Trim()
    if ([string]::IsNullOrWhiteSpace($archiveOutputPath)) {
        $archiveOutputPath = $resolvedOutputDir.TrimEnd("\") + ".zip"
    } elseif (-not [System.IO.Path]::IsPathRooted($archiveOutputPath)) {
        $archiveOutputPath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $archiveOutputPath))
    }
    if (Test-Path $archiveOutputPath) {
        Remove-Item -Path $archiveOutputPath -Force
    }
    Compress-Archive -Path (Join-Path $resolvedOutputDir "*") -DestinationPath $archiveOutputPath -Force
}

$manifest = [ordered]@{
    bundle_type = "self_serve_update_guard"
    bundle_version = 1
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    output_dir = $resolvedOutputDir
    sqlite_verify_report_path = $verifyReportPath
    sqlite_backup_manifest_path = $backupManifestPath
    sqlite_export_manifest_path = $exportManifestPath
    replay_export_manifest_path = if ($replayGenerated) { $replayManifestPath } else { "" }
    replay_generated = $replayGenerated
    archive_path = $archiveOutputPath
    next_steps = @(
        "1) Keep sqlite backup/export manifests before update execution.",
        "2) Run update operation.",
        "3) Run sqlite-verify and release-readiness post-update checks.",
        "4) If regression is detected, restore via sqlite-restore using backup manifest."
    )
}

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "update-guard.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $OutPath))
}

$parent = Split-Path -Parent $OutPath
if (-not [string]::IsNullOrWhiteSpace($parent)) {
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
}
$manifest | ConvertTo-Json -Depth 20 | Set-Content -Path $OutPath -Encoding utf8

Write-Host "[done] self-serve-update-guard completed"
Write-Host ("  output_dir               : {0}" -f $resolvedOutputDir)
Write-Host ("  sqlite_verify_report     : {0}" -f $verifyReportPath)
Write-Host ("  sqlite_backup_manifest   : {0}" -f $backupManifestPath)
Write-Host ("  sqlite_export_manifest   : {0}" -f $exportManifestPath)
if ($replayGenerated) {
    Write-Host ("  replay_export_manifest   : {0}" -f $replayManifestPath)
}
if (-not [string]::IsNullOrWhiteSpace($archiveOutputPath)) {
    Write-Host ("  archive_path             : {0}" -f $archiveOutputPath)
}
Write-Host ("  manifest                 : {0}" -f $OutPath)
