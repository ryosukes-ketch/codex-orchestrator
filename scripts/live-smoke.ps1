param(
    [string]$ApiBaseUrl = "http://127.0.0.1:8000",
    [string]$Authorization = "Bearer dev-approver-token",
    [string]$ProjectId = "",
    [string]$ApprovalProjectId = "",
    [string]$RejectProjectId = "",
    [string]$RevisionProjectId = "",
    [string]$ReplanningProjectId = "",
    [string]$LogDir = "logs\operational-readiness",
    [int]$TimeoutSec = 20,
    [int]$AuditAfterTimeoutSec = 30,
    [int]$AuditAfterPollIntervalMs = 1000,
    [switch]$SkipPreflight,
    [switch]$NoRuff
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$ruffExe = Join-Path $repoRoot ".venv\Scripts\ruff.exe"
if (-not (Test-Path $ruffExe)) { $ruffExe = "ruff" }

if (-not [string]::IsNullOrWhiteSpace($ProjectId)) {
    if ([string]::IsNullOrWhiteSpace($ApprovalProjectId)) { $ApprovalProjectId = $ProjectId }
    if ([string]::IsNullOrWhiteSpace($RejectProjectId)) { $RejectProjectId = $ProjectId }
    if ([string]::IsNullOrWhiteSpace($RevisionProjectId)) { $RevisionProjectId = $ProjectId }
    if ([string]::IsNullOrWhiteSpace($ReplanningProjectId)) { $ReplanningProjectId = $ProjectId }
}

function Invoke-CurlJson {
    param(
        [string]$Method,
        [string]$Url,
        [string]$JsonBody = "",
        [string]$AuthHeader = ""
    )

    $headers = @{ "Content-Type" = "application/json" }
    if (-not [string]::IsNullOrWhiteSpace($AuthHeader)) {
        $headers["Authorization"] = $AuthHeader
    }

    $iwrParams = @{
        Uri             = $Url
        Method          = $Method
        Headers         = $headers
        UseBasicParsing = $true
    }
    if ($JsonBody -ne "") {
        $iwrParams["Body"] = [System.Text.Encoding]::UTF8.GetBytes($JsonBody)
    }

    try {
        $resp = Invoke-WebRequest @iwrParams
        return [pscustomobject]@{
            StatusCode = [int]$resp.StatusCode
            BodyText   = $resp.Content
        }
    } catch [System.Net.WebException] {
        $httpResp = $_.Exception.Response
        if ($null -ne $httpResp) {
            $statusCode = [int]$httpResp.StatusCode
            $stream     = $httpResp.GetResponseStream()
            $reader     = New-Object System.IO.StreamReader($stream)
            $bodyText   = $reader.ReadToEnd()
            return [pscustomobject]@{
                StatusCode = $statusCode
                BodyText   = $bodyText
            }
        }
        throw
    }
}

function Convert-BodyToJsonOrNull {
    param([string]$BodyText)

    if ([string]::IsNullOrWhiteSpace($BodyText)) {
        return $null
    }

    try {
        return ($BodyText | ConvertFrom-Json)
    } catch {
        return $null
    }
}

function Get-Audit {
    param([string]$FlowName, [string]$ProjectIdValue)

    $auditUrl = $ApiBaseUrl.TrimEnd("/") + "/projects/" + $ProjectIdValue + "/audit"
    $auditResponse = Invoke-CurlJson -Method "GET" -Url $auditUrl
    if ($auditResponse.StatusCode -ne 200) {
        throw ("Audit failed for {0}: {1} {2}" -f $FlowName, $auditResponse.StatusCode, $auditResponse.BodyText)
    }

    $auditJson = Convert-BodyToJsonOrNull -BodyText $auditResponse.BodyText
    if ($null -eq $auditJson) {
        throw ("Audit JSON parse failed for {0}: {1}" -f $FlowName, $auditResponse.BodyText)
    }

    if ($auditJson.project_id -ne $ProjectIdValue) {
        throw ("Audit project_id mismatch for {0}: expected {1}, got {2}" -f $FlowName, $ProjectIdValue, $auditJson.project_id)
    }

    return $auditJson
}

function Wait-ForAuditStatus {
    param(
        [string]$FlowName,
        [string]$ProjectIdValue,
        [string]$ExpectedStatus,
        [int]$StatusTimeoutSec = 30,
        [int]$PollIntervalMs = 1000
    )

    $start = Get-Date
    $attempt = 0
    $lastAudit = $null
    while ($true) {
        $attempt++
        $lastAudit = Get-Audit -FlowName $FlowName -ProjectIdValue $ProjectIdValue
        if ($lastAudit.status -eq $ExpectedStatus) {
            $elapsedSeconds = [math]::Round(((Get-Date) - $start).TotalSeconds, 3)
            return [pscustomobject]@{
                Matched = $true
                Attempts = $attempt
                ElapsedSeconds = $elapsedSeconds
                Audit = $lastAudit
            }
        }

        $elapsedSeconds = ((Get-Date) - $start).TotalSeconds
        if ($elapsedSeconds -ge $StatusTimeoutSec) {
            return [pscustomobject]@{
                Matched = $false
                Attempts = $attempt
                ElapsedSeconds = [math]::Round($elapsedSeconds, 3)
                Audit = $lastAudit
            }
        }

        Start-Sleep -Milliseconds $PollIntervalMs
    }
}

$records = New-Object System.Collections.Generic.List[object]

function Add-Record {
    param(
        [string]$Step,
        [string]$ProjectIdValue,
        [int]$StatusCode,
        [string]$Outcome,
        [string]$Details
    )

    $null = $records.Add([pscustomobject]@{
        timestamp = (Get-Date).ToString("s")
        step = $Step
        project_id = $ProjectIdValue
        status_code = $StatusCode
        outcome = $Outcome
        details = $Details
    })
}

if (-not $SkipPreflight) {
    & (Join-Path $repoRoot "scripts\preflight.ps1") -ApiBaseUrl $ApiBaseUrl -TimeoutSec $TimeoutSec
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$healthUrl = $ApiBaseUrl.TrimEnd("/") + "/health"
Write-Host "[1/4] live health"
$health = Invoke-CurlJson -Method "GET" -Url $healthUrl
if ($health.StatusCode -ne 200) {
    Write-Error ("Health endpoint returned {0}: {1}" -f $health.StatusCode, $health.BodyText)
    exit 1
}
if ($health.BodyText -notmatch '"status"\s*:\s*"ok"') {
    Write-Error ("Unexpected health payload: {0}" -f $health.BodyText)
    exit 1
}
Add-Record -Step "health" -ProjectIdValue "" -StatusCode $health.StatusCode -Outcome "ok" -Details "health check passed"

$flows = @(
    [pscustomobject]@{
        Name = "resume-approval"
        ProjectId = $ApprovalProjectId
        Path = "/orchestrator/resume/approval"
        ExpectedStatusAfter = "completed"
        Body = {
            param($projectIdArg)
            @{
                project_id = $projectIdArg
                approved_actions = @("external_api_send")
                actor = @{
                    actor_id = "u-1"
                    actor_role = "approver"
                    actor_type = "human"
                }
                note = "live smoke approval"
                trend_provider = "mock"
            } | ConvertTo-Json -Compress -Depth 10
        }
    },
    [pscustomobject]@{
        Name = "approval-reject"
        ProjectId = $RejectProjectId
        Path = "/orchestrator/approval/reject"
        ExpectedStatusAfter = "revision_requested"
        Body = {
            param($projectIdArg)
            @{
                project_id = $projectIdArg
                rejected_actions = @("external_api_send")
                actor = @{
                    actor_id = "u-2"
                    actor_role = "approver"
                    actor_type = "human"
                }
                reason = "Security policy"
                note = "live smoke reject"
            } | ConvertTo-Json -Compress -Depth 10
        }
    },
    [pscustomobject]@{
        Name = "resume-revision"
        ProjectId = $RevisionProjectId
        Path = "/orchestrator/resume/revision"
        ExpectedStatusAfter = "ready_for_planning"
        Body = {
            param($projectIdArg)
            @{
                project_id = $projectIdArg
                resume_mode = "replanning"
                actor = @{
                    actor_id = "u-3"
                    actor_role = "operator"
                    actor_type = "human"
                }
                reason = "Adjust architecture"
                trend_provider = "mock"
                approved_actions = @()
            } | ConvertTo-Json -Compress -Depth 10
        }
    },
    [pscustomobject]@{
        Name = "replanning-start"
        ProjectId = $ReplanningProjectId
        Path = "/orchestrator/replanning/start"
        ExpectedStatusAfter = "completed"
        Body = {
            param($projectIdArg)
            @{
                project_id = $projectIdArg
                actor = @{
                    actor_id = "u-3"
                    actor_role = "operator"
                    actor_type = "human"
                }
                note = "Start revised plan"
                trend_provider = "mock"
                approved_actions = @()
                reset_downstream_tasks = $true
            } | ConvertTo-Json -Compress -Depth 10
        }
    }
)

$activeFlows = @($flows | Where-Object { -not [string]::IsNullOrWhiteSpace($_.ProjectId) })

if ($activeFlows.Count -eq 0) {
    Write-Host "[2/4] schema-level live contract"
    foreach ($flow in $flows) {
        $url = $ApiBaseUrl.TrimEnd("/") + $flow.Path
        $response = Invoke-CurlJson -Method "POST" -Url $url -JsonBody "{}" -AuthHeader $Authorization

        if ($response.StatusCode -notin @(400, 401, 404, 409, 422)) {
            Write-Error ("Unexpected schema response for {0}: {1} {2}" -f $flow.Name, $response.StatusCode, $response.BodyText)
            exit 1
        }

        if ($response.StatusCode -eq 422) {
            if (($response.BodyText -notmatch "project_id") -and ($response.BodyText -notmatch "Field required")) {
                Write-Error ("422 without expected project_id hint for {0}: {1}" -f $flow.Name, $response.BodyText)
                exit 1
            }
        }

        Add-Record -Step $flow.Name -ProjectIdValue "" -StatusCode $response.StatusCode -Outcome "schema-check" -Details "empty-body contract check"
        Write-Host ("  [ok] {0} -> {1}" -f $flow.Name, $response.StatusCode)
    }
} else {
    Write-Host "[2/4] full live flow"
    foreach ($flow in $activeFlows) {
        $projectIdValue = $flow.ProjectId
        $body = & $flow.Body $projectIdValue

        Write-Host ("  [audit-before] {0} {1}" -f $flow.Name, $projectIdValue)
        $auditBefore = Get-Audit -FlowName ($flow.Name + "-before") -ProjectIdValue $projectIdValue
        Add-Record -Step ($flow.Name + "-audit-before") -ProjectIdValue $projectIdValue -StatusCode 200 -Outcome "ok" -Details ("status=" + $auditBefore.status)

        $url = $ApiBaseUrl.TrimEnd("/") + $flow.Path
        Write-Host ("  [request] {0} {1}" -f $flow.Name, $projectIdValue)
        $response = Invoke-CurlJson -Method "POST" -Url $url -JsonBody $body -AuthHeader $Authorization
        if ($response.StatusCode -ne 200) {
            Add-Record -Step $flow.Name -ProjectIdValue $projectIdValue -StatusCode $response.StatusCode -Outcome "failed" -Details $response.BodyText
            Write-Error ("Flow failed for {0}: {1} {2}" -f $flow.Name, $response.StatusCode, $response.BodyText)
            exit 1
        }

        $responseJson = Convert-BodyToJsonOrNull -BodyText $response.BodyText
        if ($null -eq $responseJson) {
            Write-Error ("Response JSON parse failed for {0}: {1}" -f $flow.Name, $response.BodyText)
            exit 1
        }

        if ($responseJson.summary.project_id -ne $projectIdValue) {
            Write-Error ("Summary project_id mismatch for {0}: expected {1}, got {2}" -f $flow.Name, $projectIdValue, $responseJson.summary.project_id)
            exit 1
        }

        Add-Record -Step $flow.Name -ProjectIdValue $projectIdValue -StatusCode 200 -Outcome "ok" -Details ("status=" + $responseJson.summary.status)

        Write-Host ("  [audit-after] {0} {1}" -f $flow.Name, $projectIdValue)
        $auditAfterResult = Wait-ForAuditStatus `
            -FlowName ($flow.Name + "-after") `
            -ProjectIdValue $projectIdValue `
            -ExpectedStatus $flow.ExpectedStatusAfter `
            -StatusTimeoutSec $AuditAfterTimeoutSec `
            -PollIntervalMs $AuditAfterPollIntervalMs
        $auditAfter = $auditAfterResult.Audit

        if (-not $auditAfterResult.Matched) {
            $failureDetails = (
                "expected_status={0} actual_status={1} attempts={2} waited_seconds={3} timeout_seconds={4}" -f
                $flow.ExpectedStatusAfter,
                $auditAfter.status,
                $auditAfterResult.Attempts,
                $auditAfterResult.ElapsedSeconds,
                $AuditAfterTimeoutSec
            )
            Add-Record -Step ($flow.Name + "-audit-after") -ProjectIdValue $projectIdValue -StatusCode 200 -Outcome "failed" -Details $failureDetails
            Write-Error (
                "Status assertion failed for {0}: expected [{1}] got [{2}] after {3}s ({4} attempts)." -f
                $flow.Name,
                $flow.ExpectedStatusAfter,
                $auditAfter.status,
                $auditAfterResult.ElapsedSeconds,
                $auditAfterResult.Attempts
            )
            exit 1
        }

        Add-Record -Step ($flow.Name + "-audit-after") -ProjectIdValue $projectIdValue -StatusCode 200 -Outcome "ok" -Details (
            "expected_status={0} actual_status={1} attempts={2} waited_seconds={3}" -f
            $flow.ExpectedStatusAfter,
            $auditAfter.status,
            $auditAfterResult.Attempts,
            $auditAfterResult.ElapsedSeconds
        )
        Write-Host ("  [ok] {0} -> 200 status={1}" -f $flow.Name, $auditAfter.status)
    }
}

Write-Host "[3/4] write log"
$logRoot = Join-Path $repoRoot $LogDir
New-Item -ItemType Directory -Force $logRoot | Out-Null
$logPath = Join-Path $logRoot ("live-smoke-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".json")
$records | ConvertTo-Json -Depth 10 | Set-Content $logPath -Encoding utf8
Write-Host ("  [ok] " + $logPath)

Write-Host "[4/4] ruff"
if (-not $NoRuff) {
    & $ruffExe "check" "app" "tests"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host "[done] live smoke passed"
