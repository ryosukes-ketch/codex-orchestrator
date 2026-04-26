param(
    [string]$SqliteDbPath = "",
    [string]$BackupDir = "",
    [string]$OutputDir = "",
    [string]$Label = "manual",
    [switch]$SkipVerify,
    [switch]$Zip,
    [string]$ArchivePath = "",
    [string]$OutPath = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. (Join-Path $repoRoot "scripts\sqlite-common.ps1")

$resolvedDbPath = Resolve-SqliteDbPath -RepoRoot $repoRoot -SqliteDbPath $SqliteDbPath
if (-not (Test-Path $resolvedDbPath)) {
    Write-Error ("SQLite DB not found: {0}" -f $resolvedDbPath)
    exit 1
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$safeLabel = if ([string]::IsNullOrWhiteSpace($Label)) { "manual" } else { $Label.Trim().Replace(" ", "-") }

$resolvedOutputDir = ([string]$OutputDir).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedOutputDir)) {
    $resolvedOutputDir = Join-Path $repoRoot ("logs\sqlite-exports\{0}-{1}" -f $timestamp, $safeLabel)
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $resolvedOutputDir))
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

$backupManifestPath = Join-Path $resolvedOutputDir "sqlite-backup.manifest.json"
$backupDbPath = Join-Path $resolvedOutputDir "sqlite-backup.sqlite3"
$backupArgs = @{
    SqliteDbPath = $resolvedDbPath
    BackupDir = $BackupDir
    BackupPath = $backupDbPath
    OutPath = $backupManifestPath
    Label = ("export-" + $safeLabel)
}
if ($SkipVerify) {
    $backupArgs.SkipVerify = $true
}

& (Join-Path $PSScriptRoot "sqlite-backup.ps1") @backupArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$verifyReportPath = ""
if (-not $SkipVerify) {
    $verifyReportPath = Join-Path $resolvedOutputDir "sqlite-verify.report.json"
    & (Join-Path $PSScriptRoot "sqlite-verify.ps1") `
        -SqliteDbPath $backupDbPath `
        -OutPath $verifyReportPath
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$sourceSha256 = Get-SqliteFileHashWithRetry -Path $resolvedDbPath
$backupSha256 = Get-SqliteFileHashWithRetry -Path $backupDbPath
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

$exportManifest = [ordered]@{
    bundle_type = "sqlite_export"
    bundle_version = 1
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    label = $safeLabel
    output_dir = $resolvedOutputDir
    source_db_path = $resolvedDbPath
    source_sha256 = $sourceSha256
    backup_db_path = $backupDbPath
    backup_sha256 = $backupSha256
    backup_manifest_path = $backupManifestPath
    skip_verify = [bool]$SkipVerify
    verify_report_path = $verifyReportPath
    archive_path = $archiveOutputPath
}

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "sqlite-export.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $OutPath))
}
Save-SqliteJson -Payload $exportManifest -OutPath $OutPath

Write-Host "[done] sqlite-export completed"
Write-Host ("  export_dir    : {0}" -f $resolvedOutputDir)
Write-Host ("  backup_db     : {0}" -f $backupDbPath)
Write-Host ("  backup_manifest: {0}" -f $backupManifestPath)
if (-not [string]::IsNullOrWhiteSpace($verifyReportPath)) {
    Write-Host ("  verify_report : {0}" -f $verifyReportPath)
}
if (-not [string]::IsNullOrWhiteSpace($archiveOutputPath)) {
    Write-Host ("  archive_path  : {0}" -f $archiveOutputPath)
}
Write-Host ("  export_manifest: {0}" -f $OutPath)
