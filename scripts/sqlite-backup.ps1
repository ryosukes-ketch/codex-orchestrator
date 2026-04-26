param(
    [string]$SqliteDbPath = "",
    [string]$BackupDir = "",
    [string]$BackupPath = "",
    [string]$Label = "manual",
    [switch]$SkipVerify,
    [string]$OutPath = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. (Join-Path $repoRoot "scripts\sqlite-common.ps1")

$pythonExe = Get-SqlitePythonExe -RepoRoot $repoRoot
$resolvedDbPath = Resolve-SqliteDbPath -RepoRoot $repoRoot -SqliteDbPath $SqliteDbPath
if (-not (Test-Path $resolvedDbPath)) {
    Write-Error ("SQLite DB not found: {0}" -f $resolvedDbPath)
    exit 1
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$safeLabel = if ([string]::IsNullOrWhiteSpace($Label)) { "manual" } else { $Label.Trim().Replace(" ", "-") }

$resolvedBackupPath = ([string]$BackupPath).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedBackupPath)) {
    $backupRoot = Resolve-SqliteBackupDir -RepoRoot $repoRoot -BackupDir $BackupDir
    New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
    $dbBaseName = [System.IO.Path]::GetFileNameWithoutExtension($resolvedDbPath)
    $fileName = "{0}-backup-{1}-{2}.sqlite3" -f $dbBaseName, $timestamp, $safeLabel
    $resolvedBackupPath = Join-Path $backupRoot $fileName
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedBackupPath)) {
    $resolvedBackupPath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $resolvedBackupPath))
}

$backupParent = Split-Path -Parent $resolvedBackupPath
if (-not [string]::IsNullOrWhiteSpace($backupParent)) {
    New-Item -ItemType Directory -Force -Path $backupParent | Out-Null
}

Write-Host "[sqlite-backup] Creating SQLite backup snapshot..."
Write-Host ("  source  : {0}" -f $resolvedDbPath)
Write-Host ("  backup  : {0}" -f $resolvedBackupPath)

$backupResult = Invoke-SqliteBackupApi `
    -PythonExe $pythonExe `
    -SourceDbPath $resolvedDbPath `
    -BackupDbPath $resolvedBackupPath

if (-not $backupResult.ok) {
    Write-Error ("SQLite backup failed: {0}" -f ($backupResult | ConvertTo-Json -Compress))
    exit 1
}

$sourceHash = Get-SqliteFileHashWithRetry -Path $resolvedDbPath
$backupHash = Get-SqliteFileHashWithRetry -Path $resolvedBackupPath

$requiredTables = @(
    "projects",
    "tasks",
    "artifacts",
    "reviews",
    "checkpoints",
    "approvals",
    "project_history"
)

$sourceVerify = $null
$backupVerify = $null
if (-not $SkipVerify) {
    $sourceVerify = Invoke-SqliteVerifyReport `
        -PythonExe $pythonExe `
        -DbPath $resolvedDbPath `
        -RequiredTables $requiredTables
    $backupVerify = Invoke-SqliteVerifyReport `
        -PythonExe $pythonExe `
        -DbPath $resolvedBackupPath `
        -RequiredTables $requiredTables
}

$report = [ordered]@{
    operation = "sqlite_backup"
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    label = $safeLabel
    source_db_path = $resolvedDbPath
    backup_db_path = $resolvedBackupPath
    source_sha256 = $sourceHash
    backup_sha256 = $backupHash
    skip_verify = [bool]$SkipVerify
    verify = [ordered]@{
        source = $sourceVerify
        backup = $backupVerify
    }
}

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = $resolvedBackupPath + ".manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $OutPath))
}
Save-SqliteJson -Payload $report -OutPath $OutPath

if (-not $SkipVerify) {
    if (-not $sourceVerify.integrity_check_ok -or -not $backupVerify.integrity_check_ok) {
        Write-Error "SQLite integrity check failed during backup verification."
        Write-Host ("  manifest : {0}" -f $OutPath)
        exit 1
    }
    if ($sourceVerify.missing_required_tables.Count -gt 0 -or $backupVerify.missing_required_tables.Count -gt 0) {
        Write-Error "SQLite required table verification failed during backup."
        Write-Host ("  manifest : {0}" -f $OutPath)
        exit 1
    }
}

Write-Host "[done] sqlite-backup completed"
Write-Host ("  backup_db_path : {0}" -f $resolvedBackupPath)
Write-Host ("  manifest_path  : {0}" -f $OutPath)
