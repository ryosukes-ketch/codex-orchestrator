param(
    [string]$SqliteDbPath = "",
    [string]$BackupPath = "",
    [string]$BackupManifestPath = "",
    [switch]$Force,
    [switch]$SkipVerify,
    [switch]$SkipPreRestoreBackup,
    [string]$PreRestoreBackupDir = "",
    [string]$OutPath = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. (Join-Path $repoRoot "scripts\sqlite-common.ps1")

$pythonExe = Get-SqlitePythonExe -RepoRoot $repoRoot
$resolvedDbPath = Resolve-SqliteDbPath -RepoRoot $repoRoot -SqliteDbPath $SqliteDbPath

$resolvedBackupPath = ""
$resolvedManifestPath = ([string]$BackupManifestPath).Trim()
if (-not [string]::IsNullOrWhiteSpace($resolvedManifestPath)) {
    if (-not [System.IO.Path]::IsPathRooted($resolvedManifestPath)) {
        $resolvedManifestPath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $resolvedManifestPath))
    }
    if (-not (Test-Path $resolvedManifestPath)) {
        Write-Error ("Backup manifest not found: {0}" -f $resolvedManifestPath)
        exit 1
    }
    $manifest = Get-Content -Raw $resolvedManifestPath | ConvertFrom-Json
    $resolvedBackupPath = [string]$manifest.backup_db_path
}

if ([string]::IsNullOrWhiteSpace($resolvedBackupPath)) {
    $resolvedBackupPath = ([string]$BackupPath).Trim()
}
if ([string]::IsNullOrWhiteSpace($resolvedBackupPath)) {
    Write-Error "Provide -BackupPath or -BackupManifestPath."
    exit 1
}
if (-not [System.IO.Path]::IsPathRooted($resolvedBackupPath)) {
    $resolvedBackupPath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $resolvedBackupPath))
}
if (-not (Test-Path $resolvedBackupPath)) {
    Write-Error ("Backup DB not found: {0}" -f $resolvedBackupPath)
    exit 1
}

if ((Test-Path $resolvedDbPath) -and -not $Force) {
    Write-Error ("Target DB exists. Re-run with -Force: {0}" -f $resolvedDbPath)
    exit 1
}

$targetParent = Split-Path -Parent $resolvedDbPath
if (-not [string]::IsNullOrWhiteSpace($targetParent)) {
    New-Item -ItemType Directory -Force -Path $targetParent | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$preRestoreSnapshot = ""
if ((Test-Path $resolvedDbPath) -and -not $SkipPreRestoreBackup) {
    $preDir = Resolve-SqliteBackupDir -RepoRoot $repoRoot -BackupDir $PreRestoreBackupDir
    New-Item -ItemType Directory -Force -Path $preDir | Out-Null
    $dbBaseName = [System.IO.Path]::GetFileNameWithoutExtension($resolvedDbPath)
    $preRestoreSnapshot = Join-Path $preDir ("{0}-prerestore-{1}.sqlite3" -f $dbBaseName, $timestamp)
    Write-Host "[sqlite-restore] Creating pre-restore safety snapshot..."
    Invoke-SqliteBackupApi -PythonExe $pythonExe -SourceDbPath $resolvedDbPath -BackupDbPath $preRestoreSnapshot | Out-Null
}

Write-Host "[sqlite-restore] Restoring backup into target DB..."
Write-Host ("  backup : {0}" -f $resolvedBackupPath)
Write-Host ("  target : {0}" -f $resolvedDbPath)

$restoreResult = Invoke-SqliteBackupApi `
    -PythonExe $pythonExe `
    -SourceDbPath $resolvedBackupPath `
    -BackupDbPath $resolvedDbPath

if (-not $restoreResult.ok) {
    Write-Error ("SQLite restore failed: {0}" -f ($restoreResult | ConvertTo-Json -Compress))
    exit 1
}

$requiredTables = @(
    "projects",
    "tasks",
    "artifacts",
    "reviews",
    "checkpoints",
    "approvals",
    "project_history"
)

$verifyReport = $null
if (-not $SkipVerify) {
    $verifyReport = Invoke-SqliteVerifyReport `
        -PythonExe $pythonExe `
        -DbPath $resolvedDbPath `
        -RequiredTables $requiredTables
}

$restoredSha256 = ""
$restoredSha256Error = ""
try {
    $restoredSha256 = Get-SqliteFileHashWithRetry -Path $resolvedDbPath
} catch {
    $restoredSha256Error = $_.Exception.Message
}

$report = [ordered]@{
    operation = "sqlite_restore"
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    backup_db_path = $resolvedBackupPath
    backup_manifest_path = $resolvedManifestPath
    restored_db_path = $resolvedDbPath
    force = [bool]$Force
    skip_verify = [bool]$SkipVerify
    pre_restore_snapshot_path = $preRestoreSnapshot
    restored_sha256 = $restoredSha256
    restored_sha256_error = $restoredSha256Error
    verify = $verifyReport
}

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $restoreLogDir = Join-Path $repoRoot "logs/sqlite-restore"
    New-Item -ItemType Directory -Force -Path $restoreLogDir | Out-Null
    $OutPath = Join-Path $restoreLogDir ("restore-{0}.json" -f $timestamp)
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $OutPath))
}
Save-SqliteJson -Payload $report -OutPath $OutPath

if (-not $SkipVerify) {
    if (-not $verifyReport.integrity_check_ok) {
        Write-Error "SQLite restore verification failed: integrity_check is not ok."
        Write-Host ("  report_path : {0}" -f $OutPath)
        exit 1
    }
    if ($verifyReport.missing_required_tables.Count -gt 0) {
        Write-Error "SQLite restore verification failed: required tables are missing."
        Write-Host ("  report_path : {0}" -f $OutPath)
        exit 1
    }
}

Write-Host "[done] sqlite-restore completed"
Write-Host ("  restored_db_path : {0}" -f $resolvedDbPath)
Write-Host ("  report_path      : {0}" -f $OutPath)
if (-not [string]::IsNullOrWhiteSpace($preRestoreSnapshot)) {
    Write-Host ("  safety_snapshot  : {0}" -f $preRestoreSnapshot)
}
