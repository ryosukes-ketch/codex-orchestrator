param(
    [Parameter(Mandatory)]
    [string]$ProjectId,
    [string]$ApiBaseUrl = "http://127.0.0.1:8000",
    [string]$Authorization = "Bearer dev-approver-token",
    [string]$Note = "Replanning started by operator",
    [string]$TrendProvider = "mock",
    [switch]$NoResetTasks,
    [int]$TimeoutSec = 0,
    [string]$OutPath = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. (Join-Path $PSScriptRoot "operator-common.ps1")
$effectiveTimeoutSec = Resolve-OperatorTimeoutSec -TimeoutSec $TimeoutSec

$payload = @{
    project_id             = $ProjectId
    note                   = $Note
    trend_provider         = $TrendProvider
    approved_actions       = @()
    reset_downstream_tasks = (-not $NoResetTasks)
}

$url = $ApiBaseUrl.TrimEnd("/") + "/orchestrator/replanning/start"
Write-Host "[operator-replan] POST $url"
Write-Host "  project_id   : $ProjectId"
Write-Host "  note         : $Note"
Write-Host "  reset_tasks  : $(-not $NoResetTasks)"

$response = Invoke-OperatorApi `
    -Method "POST" `
    -ApiBaseUrl $ApiBaseUrl `
    -Path "/orchestrator/replanning/start" `
    -BodyObject $payload `
    -Authorization $Authorization `
    -ExpectedStatusCodes @(200) `
    -TimeoutSec $effectiveTimeoutSec

if ($null -eq $response.BodyJson) {
    Write-Error ("Replan succeeded but response body is not valid JSON: {0}" -f $response.BodyText)
    exit 1
}

$result = $response.BodyJson
$status = $result.summary.status

Write-Host ""
Write-Host "  status     : $status"
Write-Host "  tasks done : $($result.summary.completed_tasks)"
Write-Host "  artifacts  : $($result.summary.artifact_count)"

if (-not [string]::IsNullOrWhiteSpace($OutPath)) {
    Save-OperatorJson -Payload $result -OutPath $OutPath
    Write-Host "  out_path   : $OutPath"
}

Write-Host ""
Write-Host "[done] operator-replan: $ProjectId -> $status"
