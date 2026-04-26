param(
    [Parameter(Mandatory)]
    [string]$ProjectId,
    [string]$ApiBaseUrl = "http://127.0.0.1:8000",
    [string]$Authorization = "Bearer dev-approver-token",
    [string]$ApprovedActions = "external_api_send",
    [string]$Note = "Approved by operator",
    [string]$TrendProvider = "mock",
    [int]$TimeoutSec = 0,
    [string]$OutPath = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. (Join-Path $PSScriptRoot "operator-common.ps1")
$effectiveTimeoutSec = Resolve-OperatorTimeoutSec -TimeoutSec $TimeoutSec

$approvedList = $ApprovedActions -split "," | ForEach-Object { $_.Trim() } | Where-Object { $_ }

$payload = @{
    project_id       = $ProjectId
    approved_actions = @($approvedList)
    note             = $Note
    trend_provider   = $TrendProvider
}

$url = $ApiBaseUrl.TrimEnd("/") + "/orchestrator/resume/approval"
Write-Host "[operator-approve] POST $url"
Write-Host "  project_id : $ProjectId"
Write-Host "  actions    : $ApprovedActions"

$response = Invoke-OperatorApi `
    -Method "POST" `
    -ApiBaseUrl $ApiBaseUrl `
    -Path "/orchestrator/resume/approval" `
    -BodyObject $payload `
    -Authorization $Authorization `
    -ExpectedStatusCodes @(200) `
    -TimeoutSec $effectiveTimeoutSec

if ($null -eq $response.BodyJson) {
    Write-Error ("Approve succeeded but response body is not valid JSON: {0}" -f $response.BodyText)
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
Write-Host "[done] operator-approve: $ProjectId -> $status"
