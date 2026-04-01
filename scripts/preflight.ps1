param(
    [string]$ApiBaseUrl = "http://127.0.0.1:8000",
    [int]$TimeoutSec = 10
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) { $pythonExe = "python" }

$verifyScript = Join-Path $repoRoot "scripts\verify.ps1"
$healthUrl = $ApiBaseUrl.TrimEnd("/") + "/health"

Write-Host "[1/5] Repository root check"
if (-not (Test-Path (Join-Path $repoRoot ".git"))) {
    Write-Error "Repository root check failed: $repoRoot"
    exit 1
}

Write-Host "[2/5] Python check"
& $pythonExe "--version"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[3/5] verify script check"
if (-not (Test-Path $verifyScript)) {
    Write-Error "Missing verify script: $verifyScript"
    exit 1
}

Write-Host "[4/5] /health check"
try {
    $health = Invoke-RestMethod -Uri $healthUrl -Method Get -TimeoutSec $TimeoutSec
} catch {
    Write-Error ("Health check failed at {0}: {1}" -f $healthUrl, $_.Exception.Message)
    exit 1
}

if ($null -eq $health) {
    Write-Error "Empty /health response from $healthUrl"
    exit 1
}

if ($health.PSObject.Properties.Name -contains "status") {
    if ($health.status -ne "ok") {
        Write-Error ("Unexpected /health status: {0}" -f ($health | ConvertTo-Json -Compress))
        exit 1
    }
}

Write-Host "[5/5] Preflight passed"
Write-Host ("Health endpoint: {0}" -f $healthUrl)
Write-Host ("Health payload : {0}" -f ($health | ConvertTo-Json -Compress))
