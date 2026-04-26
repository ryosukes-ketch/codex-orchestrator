param(
    [Parameter(Mandatory)]
    [string]$ProjectId,
    [string]$ApiBaseUrl = "http://127.0.0.1:8000",
    [string]$Authorization = "Bearer dev-approver-token",
    [string]$ResumeMode = "replanning",
    [string]$Reason = "Revision triggered by operator",
    [string]$TrendProvider = "mock",
    [int]$TimeoutSec = 0,
    [string]$OutPath = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. (Join-Path $PSScriptRoot "operator-common.ps1")
$effectiveTimeoutSec = Resolve-OperatorTimeoutSec -TimeoutSec $TimeoutSec

$validModes = @("replanning", "rebuilding", "rereview")
if ($ResumeMode -notin $validModes) {
    Write-Error ("Invalid ResumeMode '{0}'. Valid values: {1}" -f $ResumeMode, ($validModes -join ", "))
    exit 1
}

$payload = @{
    project_id       = $ProjectId
    resume_mode      = $ResumeMode
    reason           = $Reason
    trend_provider   = $TrendProvider
    approved_actions = @()
}

$url = $ApiBaseUrl.TrimEnd("/") + "/orchestrator/resume/revision"
Write-Host "[operator-revise] POST $url"
Write-Host "  project_id  : $ProjectId"
Write-Host "  resume_mode : $ResumeMode"
Write-Host "  reason      : $Reason"

$response = Invoke-OperatorApi `
    -Method "POST" `
    -ApiBaseUrl $ApiBaseUrl `
    -Path "/orchestrator/resume/revision" `
    -BodyObject $payload `
    -Authorization $Authorization `
    -ExpectedStatusCodes @(200) `
    -TimeoutSec $effectiveTimeoutSec

if ($null -eq $response.BodyJson) {
    Write-Error ("Revise succeeded but response body is not valid JSON: {0}" -f $response.BodyText)
    exit 1
}

$result = $response.BodyJson
$status = $result.summary.status

Write-Host ""
Write-Host "  status     : $status"

if ($result.summary.next_steps -and $result.summary.next_steps.Count -gt 0) {
    Write-Host "  next steps :"
    foreach ($step in $result.summary.next_steps) {
        Write-Host "    - $step"
    }
}

if (-not [string]::IsNullOrWhiteSpace($OutPath)) {
    Save-OperatorJson -Payload $result -OutPath $OutPath
    Write-Host "  out_path   : $OutPath"
}

Write-Host ""
Write-Host "[done] operator-revise: $ProjectId -> $status"
