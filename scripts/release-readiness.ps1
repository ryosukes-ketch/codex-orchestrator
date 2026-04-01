param(
    [string]$ApiBaseUrl = "http://127.0.0.1:8000",
    [string]$Authorization = "Bearer dev-approver-token",
    [string]$ProjectId = "",
    [string]$ApprovalProjectId = "",
    [string]$RejectProjectId = "",
    [string]$RevisionProjectId = "",
    [string]$ReplanningProjectId = "",
    [string]$LogDir = "logs\operational-readiness",
    [switch]$AutoSeedFullFlow,
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
    if ($AutoSeedFullFlow) {
        Write-Host "[2/5] Live smoke with automatic seeds"
        & (Join-Path $repoRoot "scripts\full-live-flow.ps1") -ApiBaseUrl $ApiBaseUrl -Authorization $Authorization -LogDir $LogDir -SkipPreflight
    } else {
        Write-Host "[2/5] Live smoke"
        & (Join-Path $repoRoot "scripts\live-smoke.ps1") -ApiBaseUrl $ApiBaseUrl -Authorization $Authorization -ProjectId $ProjectId -ApprovalProjectId $ApprovalProjectId -RejectProjectId $RejectProjectId -RevisionProjectId $RevisionProjectId -ReplanningProjectId $ReplanningProjectId -LogDir $LogDir -SkipPreflight
    }
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
