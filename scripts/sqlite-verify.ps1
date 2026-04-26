param(
    [string]$SqliteDbPath = "",
    [string]$RequiredTables = "projects,tasks,artifacts,reviews,checkpoints,approvals,project_history",
    [switch]$FailOnMissingRequiredTables,
    [string]$OutPath = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. (Join-Path $repoRoot "scripts\sqlite-common.ps1")

$pythonExe = Get-SqlitePythonExe -RepoRoot $repoRoot
$resolvedDbPath = Resolve-SqliteDbPath -RepoRoot $repoRoot -SqliteDbPath $SqliteDbPath
$required = @(
    $RequiredTables -split "," |
        ForEach-Object { ([string]$_).Trim() } |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
)

Write-Host "[sqlite-verify] Inspecting SQLite state backend file..."
Write-Host ("  db_path        : {0}" -f $resolvedDbPath)
Write-Host ("  required_tables: {0}" -f (($required -join ", ")))

$report = Invoke-SqliteVerifyReport `
    -PythonExe $pythonExe `
    -DbPath $resolvedDbPath `
    -RequiredTables $required

$verification = [ordered]@{
    operation = "sqlite_verify"
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    report = $report
}

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $verifyDir = Join-Path $repoRoot "logs/sqlite-verify"
    New-Item -ItemType Directory -Force -Path $verifyDir | Out-Null
    $OutPath = Join-Path $verifyDir ("verify-{0}.json" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $OutPath))
}
Save-SqliteJson -Payload $verification -OutPath $OutPath

$missingRequired = ($report.missing_required_tables | Measure-Object).Count -gt 0
$integrityOk = [bool]$report.integrity_check_ok
$quickOk = [bool]$report.quick_check_ok

$shouldFailOnRequired = $FailOnMissingRequiredTables.IsPresent
if (-not $shouldFailOnRequired -and $required.Count -gt 0) {
    $shouldFailOnRequired = $true
}

Write-Host ("  exists         : {0}" -f [bool]$report.exists)
Write-Host ("  table_count    : {0}" -f [int]$report.table_count)
Write-Host ("  integrity_check: {0}" -f [string]$report.integrity_check_result)
Write-Host ("  quick_check    : {0}" -f [string]$report.quick_check_result)
Write-Host ("  report_path    : {0}" -f $OutPath)

if (-not [bool]$report.exists) {
    Write-Error ("SQLite DB not found: {0}" -f $resolvedDbPath)
    exit 1
}
if (-not $integrityOk -or -not $quickOk) {
    Write-Error "SQLite integrity/quick check failed."
    exit 1
}
if ($shouldFailOnRequired -and $missingRequired) {
    Write-Error (
        "Missing required tables: {0}" -f
        ([string]::Join(", ", @($report.missing_required_tables)))
    )
    exit 1
}

Write-Host "[done] sqlite-verify passed"
