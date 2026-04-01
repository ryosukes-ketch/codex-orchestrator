param(
    [string]$ApiBaseUrl = "http://127.0.0.1:8000",
    [string]$Authorization = "Bearer dev-approver-token",
    [string]$LogDir = "logs\operational-readiness",
    [switch]$SkipPreflight,
    [switch]$NoRuff
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

function New-SeedProject {
    param(
        [string]$Name,
        [string]$TrendProvider,
        [bool]$SimulateReviewFailure,
        [string]$ExpectedStatus
    )

    $body = @{
        brief = @{
            objective = $Name
            raw_request = $Name
        }
        trend_provider = $TrendProvider
        approved_actions = @()
        simulate_review_failure = $SimulateReviewFailure
    } | ConvertTo-Json -Compress -Depth 10

    $response = Invoke-RestMethod -Uri ($ApiBaseUrl.TrimEnd("/") + "/orchestrator/run") -Method Post -ContentType "application/json" -Body $body

    if ($null -eq $response.summary) {
        throw ("Missing summary in seed response for {0}" -f $Name)
    }

    if ([string]::IsNullOrWhiteSpace($response.summary.project_id)) {
        throw ("Missing project_id in seed response for {0}" -f $Name)
    }

    if ($response.summary.status -ne $ExpectedStatus) {
        throw ("Unexpected seed status for {0}: expected {1}, got {2}" -f $Name, $ExpectedStatus, $response.summary.status)
    }

    return $response.summary
}

if (-not $SkipPreflight) {
    & (Join-Path $repoRoot "scripts\preflight.ps1") -ApiBaseUrl $ApiBaseUrl
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host "[1/3] create deterministic seeds"
$approvalSeed = New-SeedProject -Name "full live flow approval seed" -TrendProvider "gemini-flash-lite-latest" -SimulateReviewFailure $false -ExpectedStatus "waiting_approval"
$rejectSeed = New-SeedProject -Name "full live flow reject seed" -TrendProvider "gemini-flash-lite-latest" -SimulateReviewFailure $false -ExpectedStatus "waiting_approval"

Write-Host ("  approval seed : {0} [{1}]" -f $approvalSeed.project_id, $approvalSeed.status)
Write-Host ("  reject seed   : {0} [{1}]" -f $rejectSeed.project_id, $rejectSeed.status)

Write-Host "[2/3] write seed log"
$logRoot = Join-Path $repoRoot $LogDir
New-Item -ItemType Directory -Force $logRoot | Out-Null
$seedLogPath = Join-Path $logRoot ("full-live-flow-seeds-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".json")
@{
    approval_seed = @{
        project_id = $approvalSeed.project_id
        status = $approvalSeed.status
        trend_provider = "gemini-flash-lite-latest"
    }
    reject_seed = @{
        project_id = $rejectSeed.project_id
        status = $rejectSeed.status
        trend_provider = "gemini-flash-lite-latest"
    }
} | ConvertTo-Json -Depth 10 | Set-Content $seedLogPath -Encoding utf8
Write-Host ("  [ok] " + $seedLogPath)

Write-Host "[3/3] run live smoke with generated seeds"
if ($NoRuff) {
    & (Join-Path $repoRoot "scripts\live-smoke.ps1") -ApiBaseUrl $ApiBaseUrl -Authorization $Authorization -ApprovalProjectId $approvalSeed.project_id -RejectProjectId $rejectSeed.project_id -RevisionProjectId $rejectSeed.project_id -ReplanningProjectId $rejectSeed.project_id -LogDir $LogDir -SkipPreflight -NoRuff
} else {
    & (Join-Path $repoRoot "scripts\live-smoke.ps1") -ApiBaseUrl $ApiBaseUrl -Authorization $Authorization -ApprovalProjectId $approvalSeed.project_id -RejectProjectId $rejectSeed.project_id -RevisionProjectId $rejectSeed.project_id -ReplanningProjectId $rejectSeed.project_id -LogDir $LogDir -SkipPreflight
}

if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[done] full-live-flow passed"
