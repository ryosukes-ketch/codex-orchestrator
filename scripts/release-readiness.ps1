param(
    [string]$ApiBaseUrl = "http://127.0.0.1:8000",
    [switch]$SkipSmoke,
    [switch]$SkipVerify
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

Write-Host "[1/3] Preflight"
& (Join-Path $repoRoot "scripts\preflight.ps1") -ApiBaseUrl $ApiBaseUrl
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not $SkipSmoke) {
    Write-Host "[2/3] Smoke"
    & (Join-Path $repoRoot "scripts\smoke.ps1") -ApiBaseUrl $ApiBaseUrl
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if (-not $SkipVerify) {
    Write-Host "[3/3] Full verification"
    & (Join-Path $repoRoot "scripts\verify.ps1")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
