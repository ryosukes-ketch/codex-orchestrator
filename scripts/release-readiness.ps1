param(
    [string]$ApiBaseUrl = "http://127.0.0.1:8000",
    [string]$ProjectId = "",
    [switch]$SkipLiveSmoke,
    [switch]$SkipSmoke,
    [switch]$SkipResilience,
    [switch]$SkipVerify
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

Write-Host "[1/5] Preflight"
& (Join-Path $repoRoot "scripts\preflight.ps1") -ApiBaseUrl $ApiBaseUrl
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not $SkipLiveSmoke) {
    Write-Host "[2/5] Live smoke"
    & (Join-Path $repoRoot "scripts\live-smoke.ps1") -ApiBaseUrl $ApiBaseUrl -ProjectId $ProjectId -SkipPreflight
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if (-not $SkipSmoke) {
    Write-Host "[3/5] Smoke"
    & (Join-Path $repoRoot "scripts\smoke.ps1") -ApiBaseUrl $ApiBaseUrl -SkipPreflight
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if (-not $SkipResilience) {
    Write-Host "[4/5] Resilience"
    & (Join-Path $repoRoot "scripts\resilience.ps1") -ApiBaseUrl $ApiBaseUrl -SkipPreflight
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if (-not $SkipVerify) {
    Write-Host "[5/5] Full verification"
    & (Join-Path $repoRoot "scripts\verify.ps1")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
