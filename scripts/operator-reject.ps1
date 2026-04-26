param(
    [Parameter(Mandatory)]
    [string]$ProjectId,
    [Parameter(Mandatory)]
    [string]$Reason,
    [string]$ApiBaseUrl = "http://127.0.0.1:8000",
    [string]$Authorization = "Bearer dev-approver-token",
    [string]$RejectedActions = "external_api_send",
    [string]$Note = "",
    [int]$TimeoutSec = 0,
    [string]$OutPath = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. (Join-Path $PSScriptRoot "operator-common.ps1")
$effectiveTimeoutSec = Resolve-OperatorTimeoutSec -TimeoutSec $TimeoutSec

$rejectedList = $RejectedActions -split "," | ForEach-Object { $_.Trim() } | Where-Object { $_ }

$payload = @{
    project_id       = $ProjectId
    rejected_actions = @($rejectedList)
    reason           = $Reason
    note             = $Note
}

$url = $ApiBaseUrl.TrimEnd("/") + "/orchestrator/approval/reject"
Write-Host "[operator-reject] POST $url"
Write-Host "  project_id : $ProjectId"
Write-Host "  reason     : $Reason"
Write-Host "  actions    : $RejectedActions"

$response = Invoke-OperatorApi `
    -Method "POST" `
    -ApiBaseUrl $ApiBaseUrl `
    -Path "/orchestrator/approval/reject" `
    -BodyObject $payload `
    -Authorization $Authorization `
    -ExpectedStatusCodes @(200) `
    -TimeoutSec $effectiveTimeoutSec

if ($null -eq $response.BodyJson) {
    Write-Error ("Reject succeeded but response body is not valid JSON: {0}" -f $response.BodyText)
    exit 1
}

$result = $response.BodyJson
$status = $result.summary.status

Write-Host ""
Write-Host "  status     : $status"

if (-not [string]::IsNullOrWhiteSpace($OutPath)) {
    Save-OperatorJson -Payload $result -OutPath $OutPath
    Write-Host "  out_path   : $OutPath"
}

Write-Host ""
Write-Host "[done] operator-reject: $ProjectId -> $status"
