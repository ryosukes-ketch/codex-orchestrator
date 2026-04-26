param(
    [string]$EnvPath = ".env",
    [string]$OutPath = "",
    [switch]$RequireGatewayCheck,
    [string]$GatewayAgentId = "codex-orchestrator",
    [string]$GatewayBackendModel = "openai-codex/gpt-5.2",
    [int]$GatewayTimeoutSec = 20,
    [int]$GatewayProbeTimeoutSec = 10
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

function Parse-EnvFile {
    param([string]$Path)

    $map = @{}
    if (-not (Test-Path $Path)) {
        return $map
    }

    foreach ($line in Get-Content -Path $Path -Encoding utf8) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        if ($line.TrimStart().StartsWith("#")) { continue }
        if ($line -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
            $map[$Matches[1]] = $Matches[2].Trim()
        }
    }
    return $map
}

function Resolve-Setting {
    param(
        [string]$Name,
        [hashtable]$EnvMap,
        [string]$DefaultValue = ""
    )

    $processValue = [System.Environment]::GetEnvironmentVariable($Name, "Process")
    if (-not [string]::IsNullOrWhiteSpace($processValue)) {
        return $processValue.Trim()
    }
    if ($EnvMap.ContainsKey($Name)) {
        $value = [string]$EnvMap[$Name]
        return $value.Trim()
    }
    return $DefaultValue
}

function Add-Check {
    param(
        [System.Collections.Generic.List[object]]$Checks,
        [string]$Name,
        [bool]$Passed,
        [string]$Details
    )

    $Checks.Add([ordered]@{
        name = $Name
        passed = $Passed
        details = $Details
    }) | Out-Null
}

function Save-Report {
    param(
        [object]$Report,
        [string]$Path
    )

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return
    }
    $parent = Split-Path -Parent $Path
    if (-not [string]::IsNullOrWhiteSpace($parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    $Report | ConvertTo-Json -Depth 30 | Set-Content -Path $Path -Encoding utf8
}

function Test-WriteableDirectory {
    param([string]$DirectoryPath)

    try {
        New-Item -ItemType Directory -Force -Path $DirectoryPath | Out-Null
        $probePath = Join-Path $DirectoryPath ("write-probe-" + [guid]::NewGuid().ToString("N") + ".tmp")
        "ok" | Set-Content -Path $probePath -Encoding utf8
        Remove-Item -Path $probePath -Force -ErrorAction SilentlyContinue
        return $true
    } catch {
        return $false
    }
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$resolvedOutPath = $OutPath
if ([string]::IsNullOrWhiteSpace($resolvedOutPath)) {
    $resolvedOutPath = Join-Path $repoRoot ("logs\operational-readiness\self-serve-preflight-{0}.json" -f $timestamp)
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutPath)) {
    $resolvedOutPath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $resolvedOutPath))
}

$resolvedEnvPath = $EnvPath
if (-not [System.IO.Path]::IsPathRooted($resolvedEnvPath)) {
    $resolvedEnvPath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $resolvedEnvPath))
}

$checks = New-Object System.Collections.Generic.List[object]
$envMap = Parse-EnvFile -Path $resolvedEnvPath

Add-Check -Checks $checks -Name "repo_root" -Passed (Test-Path $repoRoot) -Details $repoRoot
Add-Check -Checks $checks -Name "env_file_exists" -Passed (Test-Path $resolvedEnvPath) -Details $resolvedEnvPath

$requiredKeys = @(
    "STATE_BACKEND",
    "STATE_BACKEND_STRICT",
    "SQLITE_DB_PATH",
    "SQLITE_BACKUP_DIR",
    "OPERATOR_API_TIMEOUT_SECONDS"
)

$missingKeys = New-Object System.Collections.Generic.List[string]
foreach ($key in $requiredKeys) {
    $value = Resolve-Setting -Name $key -EnvMap $envMap
    if ([string]::IsNullOrWhiteSpace($value)) {
        $missingKeys.Add($key) | Out-Null
    }
}
Add-Check `
    -Checks $checks `
    -Name "required_keys_present" `
    -Passed ($missingKeys.Count -eq 0) `
    -Details ("missing=" + (@($missingKeys.ToArray()) -join ","))

$stateBackend = Resolve-Setting -Name "STATE_BACKEND" -EnvMap $envMap
$stateBackendStrict = Resolve-Setting -Name "STATE_BACKEND_STRICT" -EnvMap $envMap
$sqliteDbPath = Resolve-Setting -Name "SQLITE_DB_PATH" -EnvMap $envMap
$sqliteBackupDir = Resolve-Setting -Name "SQLITE_BACKUP_DIR" -EnvMap $envMap
$operatorTimeout = Resolve-Setting -Name "OPERATOR_API_TIMEOUT_SECONDS" -EnvMap $envMap
$openclawBaseUrl = Resolve-Setting -Name "OPENCLAW_BASE_URL" -EnvMap $envMap

Add-Check `
    -Checks $checks `
    -Name "state_backend_sqlite" `
    -Passed ($stateBackend.Trim().ToLowerInvariant() -eq "sqlite") `
    -Details ("state_backend=" + $stateBackend)

$strictNormalized = $stateBackendStrict.Trim().ToLowerInvariant()
$strictPassed = ($strictNormalized -eq "true" -or $strictNormalized -eq "1")
Add-Check `
    -Checks $checks `
    -Name "state_backend_strict_true" `
    -Passed $strictPassed `
    -Details ("state_backend_strict=" + $stateBackendStrict)

$sqliteDbResolved = $sqliteDbPath
if (-not [System.IO.Path]::IsPathRooted($sqliteDbResolved)) {
    $sqliteDbResolved = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $sqliteDbResolved))
}
$sqliteDbDir = Split-Path -Parent $sqliteDbResolved
$dbWriteable = $false
if (-not [string]::IsNullOrWhiteSpace($sqliteDbDir)) {
    $dbWriteable = Test-WriteableDirectory -DirectoryPath $sqliteDbDir
}
Add-Check -Checks $checks -Name "sqlite_db_dir_writeable" -Passed $dbWriteable -Details $sqliteDbDir

$sqliteBackupResolved = $sqliteBackupDir
if (-not [System.IO.Path]::IsPathRooted($sqliteBackupResolved)) {
    $sqliteBackupResolved = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $sqliteBackupResolved))
}
$backupWriteable = Test-WriteableDirectory -DirectoryPath $sqliteBackupResolved
Add-Check -Checks $checks -Name "sqlite_backup_dir_writeable" -Passed $backupWriteable -Details $sqliteBackupResolved

$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    $pythonExe = "python"
}
$pythonOk = $true
try {
    & $pythonExe "--version" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        $pythonOk = $false
    }
} catch {
    $pythonOk = $false
}
Add-Check -Checks $checks -Name "python_available" -Passed $pythonOk -Details $pythonExe

$requiredScripts = @(
    "scripts\start-server.ps1",
    "scripts\release-readiness.ps1",
    "scripts\sqlite-backup.ps1",
    "scripts\sqlite-restore.ps1",
    "scripts\sqlite-verify.ps1",
    "scripts\sqlite-export.ps1",
    "scripts\operator-support-bundle.ps1"
)
$missingScripts = @()
foreach ($scriptPath in $requiredScripts) {
    if (-not (Test-Path (Join-Path $repoRoot $scriptPath))) {
        $missingScripts += $scriptPath
    }
}
Add-Check `
    -Checks $checks `
    -Name "required_scripts_present" `
    -Passed ($missingScripts.Count -eq 0) `
    -Details ("missing=" + ($missingScripts -join ","))

if ($RequireGatewayCheck) {
    $gatewayScript = Join-Path $repoRoot "scripts\openclaw-gateway-check.ps1"
    $gatewayOk = $true
    $gatewayDetails = "skipped"
    if (-not (Test-Path $gatewayScript)) {
        $gatewayOk = $false
        $gatewayDetails = "openclaw-gateway-check.ps1 not found"
    } else {
        try {
            $gatewayOutput = & $gatewayScript `
                -AgentId $GatewayAgentId `
                -BackendModel $GatewayBackendModel `
                -TimeoutSec $GatewayTimeoutSec `
                -ProbeTimeoutSec $GatewayProbeTimeoutSec 2>&1 | Out-String
            if ($LASTEXITCODE -ne 0) {
                $gatewayOk = $false
                $gatewayDetails = ($gatewayOutput.Trim())
            } else {
                $gatewayDetails = "gateway check passed"
            }
        } catch {
            $gatewayOk = $false
            $gatewayDetails = $_.Exception.Message
        }
    }
    Add-Check `
        -Checks $checks `
        -Name "openclaw_gateway_check" `
        -Passed $gatewayOk `
        -Details $gatewayDetails
}

$failedChecks = @($checks | Where-Object { -not $_.passed })
$status = if ($failedChecks.Count -eq 0) { "pass" } else { "fail" }

$report = [ordered]@{
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    repo_root = $repoRoot
    env_path = $resolvedEnvPath
    status = $status
    failed_check_count = $failedChecks.Count
    resolved = [ordered]@{
        state_backend = $stateBackend
        state_backend_strict = $stateBackendStrict
        sqlite_db_path = $sqliteDbResolved
        sqlite_backup_dir = $sqliteBackupResolved
        operator_api_timeout_seconds = $operatorTimeout
        openclaw_base_url = $openclawBaseUrl
        require_gateway_check = [bool]$RequireGatewayCheck
    }
    checks = @($checks.ToArray())
    next_steps = @(
        "1) Fix failing checks listed in this report.",
        "2) Re-run scripts\\self-serve-preflight.ps1.",
        "3) Run scripts\\release-readiness.ps1 once preflight passes."
    )
}

Save-Report -Report $report -Path $resolvedOutPath
Write-Host ("[self-serve-preflight] status={0}" -f $status)
Write-Host ("[self-serve-preflight] report={0}" -f $resolvedOutPath)

if ($failedChecks.Count -gt 0) {
    foreach ($check in $failedChecks) {
        Write-Host ("  [fail] {0}: {1}" -f [string]$check.name, [string]$check.details)
    }
    exit 1
}

Write-Host "[done] self-serve preflight passed"
