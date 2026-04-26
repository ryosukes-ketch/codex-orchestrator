param(
    [string]$BriefPath = ".\examples\briefs\sample_brief.json",
    [string]$ApiBaseUrl = "http://127.0.0.1:8000",
    [string]$TrendProvider = "mock",
    [string]$ApprovedActions = "",
    [string]$OutPath = "",
    [int]$TimeoutSec = 0,
    [switch]$SimulateReviewFailure
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. (Join-Path $PSScriptRoot "operator-common.ps1")
$effectiveTimeoutSec = Resolve-OperatorTimeoutSec -TimeoutSec $TimeoutSec

$briefObj = Read-OperatorJsonFile -Path $BriefPath

$approvedList = @()
if (-not [string]::IsNullOrWhiteSpace($ApprovedActions)) {
    $approvedList = $ApprovedActions -split "," | ForEach-Object { $_.Trim() } | Where-Object { $_ }
}

$payload = @{
    brief                   = $briefObj
    trend_provider          = $TrendProvider
    approved_actions        = @($approvedList)
    simulate_review_failure = [bool]$SimulateReviewFailure
}

$url = $ApiBaseUrl.TrimEnd("/") + "/orchestrator/run"
Write-Host "[operator-run] POST $url"
Write-Host "  brief     : $BriefPath"
Write-Host "  provider  : $TrendProvider"

$response = Invoke-OperatorApi `
    -Method "POST" `
    -ApiBaseUrl $ApiBaseUrl `
    -Path "/orchestrator/run" `
    -BodyObject $payload `
    -ExpectedStatusCodes @(200) `
    -TimeoutSec $effectiveTimeoutSec

if ($null -eq $response.BodyJson) {
    Write-Error ("Run succeeded but response body is not valid JSON: {0}" -f $response.BodyText)
    exit 1
}

$result = $response.BodyJson
$projectId = $result.summary.project_id
$status = $result.summary.status

Write-Host ""
Write-Host "  project_id : $projectId"
Write-Host "  status     : $status"
Write-Host "  tasks done : $($result.summary.completed_tasks)"
Write-Host "  artifacts  : $($result.summary.artifact_count)"

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
Write-Host "[done] operator-run: project_id=$projectId status=$status"
