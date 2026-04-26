param(
    [string]$GatewayBaseUrl = "",
    [string]$AgentId = "default",
    [string]$BackendModel = "",
    [string]$AuthToken = "",
    [string]$Prompt = "Return a JSON object with fields: status, agent_id.",
    [int]$TimeoutSec = 0,
    [int]$ProbeTimeoutSec = 0,
    [string]$EvidenceOutPath = "",
    [string]$StagingRecordPath = "",
    [string]$VerifiedBy = "Codex unattended run",
    [switch]$NoResponsesFallback,
    [switch]$NoAppendStagingRecord
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if ([string]::IsNullOrWhiteSpace($EvidenceOutPath)) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $EvidenceOutPath = Join-Path $repoRoot ("logs\staging\openclaw-gateway-check-{0}.json" -f $stamp)
}

$checkArgs = @{}
if (-not [string]::IsNullOrWhiteSpace($GatewayBaseUrl)) {
    $checkArgs.GatewayBaseUrl = $GatewayBaseUrl
}
if (-not [string]::IsNullOrWhiteSpace($AgentId)) {
    $checkArgs.AgentId = $AgentId
}
if (-not [string]::IsNullOrWhiteSpace($BackendModel)) {
    $checkArgs.BackendModel = $BackendModel
}
if (-not [string]::IsNullOrWhiteSpace($AuthToken)) {
    $checkArgs.AuthToken = $AuthToken
}
if (-not [string]::IsNullOrWhiteSpace($Prompt)) {
    $checkArgs.Prompt = $Prompt
}
if ($TimeoutSec -gt 0) {
    $checkArgs.TimeoutSec = $TimeoutSec
}
if ($ProbeTimeoutSec -gt 0) {
    $checkArgs.ProbeTimeoutSec = $ProbeTimeoutSec
}
$checkArgs.EvidenceOutPath = $EvidenceOutPath
if (-not [string]::IsNullOrWhiteSpace($StagingRecordPath)) {
    $checkArgs.StagingRecordPath = $StagingRecordPath
}
if (-not [string]::IsNullOrWhiteSpace($VerifiedBy)) {
    $checkArgs.VerifiedBy = $VerifiedBy
}

if (-not $NoAppendStagingRecord) {
    $checkArgs.AppendStagingRecord = $true
}
if ($NoResponsesFallback) {
    $checkArgs.NoResponsesFallback = $true
}

& (Join-Path $PSScriptRoot "openclaw-gateway-check.ps1") @checkArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host "[done] openclaw evidence capture completed"
Write-Host ("  evidence_path: {0}" -f $EvidenceOutPath)
