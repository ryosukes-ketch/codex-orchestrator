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

function Get-SeedMismatchAuditSnapshot {
    param(
        [string]$ApiBaseUrl,
        [string]$ProjectId
    )

    if ([string]::IsNullOrWhiteSpace($ProjectId)) {
        return $null
    }

    $auditUrl = $ApiBaseUrl.TrimEnd("/") + "/projects/" + $ProjectId + "/audit"
    $maxAttempts = 5
    for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
        try {
            $audit = Invoke-RestMethod -Uri $auditUrl -Method Get -TimeoutSec 30
            $events = @()
            if ($null -ne $audit -and $audit.PSObject.Properties.Name -contains "events") {
                $events = @($audit.events)
            }
            $stageEvents = @($events | Where-Object { [string]$_.event_type -eq "department_stage_executed" })

            $summaryStages = @()
            if ($null -ne $audit -and $audit.PSObject.Properties.Name -contains "department_stage_summary") {
                $summaryStages = @($audit.department_stage_summary)
            }

            $failingStagesFromSummary = @()
            foreach ($summaryStage in $summaryStages) {
                $failureCount = 0
                if ($summaryStage.PSObject.Properties.Name -contains "failure_count") {
                    $failureCount = [int]$summaryStage.failure_count
                }
                if ($failureCount -le 0) {
                    continue
                }
                $failureReasons = @()
                if ($summaryStage.PSObject.Properties.Name -contains "failure_reasons") {
                    $failureReasons = @($summaryStage.failure_reasons)
                }
                $failingStagesFromSummary += [ordered]@{
                    department = [string]$summaryStage.department
                    stage_name = [string]$summaryStage.stage_name
                    sequence = [int]$summaryStage.sequence
                    stage_success = $false
                    failure_reason = if ($failureReasons.Count -gt 0) { [string]$failureReasons[0] } else { "" }
                    effective_model = if ($summaryStage.PSObject.Properties.Name -contains "effective_models") { [string](@($summaryStage.effective_models) -join ",") } else { "" }
                    llm_endpoint = if ($summaryStage.PSObject.Properties.Name -contains "llm_endpoints") { [string](@($summaryStage.llm_endpoints) -join ",") } else { "" }
                }
            }

            $failingStagesFromEvents = @()
            foreach ($stageEvent in $stageEvents) {
                $failureReason = [string]$stageEvent.stage_failure_reason
                $isFailed = ($stageEvent.stage_success -eq $false) -or (-not [string]::IsNullOrWhiteSpace($failureReason))
                if (-not $isFailed) {
                    continue
                }
                $failingStagesFromEvents += [ordered]@{
                    department = [string]$stageEvent.department
                    stage_name = [string]$stageEvent.stage_name
                    sequence = [int]$stageEvent.sequence
                    stage_success = [bool]$stageEvent.stage_success
                    failure_reason = $failureReason
                    effective_model = [string]$stageEvent.effective_model
                    llm_endpoint = [string]$stageEvent.llm_endpoint
                }
            }

            $failingStages = @()
            if ($failingStagesFromSummary.Count -gt 0) {
                $failingStages = $failingStagesFromSummary
            } else {
                $failingStages = $failingStagesFromEvents
            }

            $shouldRetry = (
                [string]$audit.status -eq "in_progress" -and
                $stageEvents.Count -eq 0 -and
                $summaryStages.Count -eq 0 -and
                $attempt -lt $maxAttempts
            )
            if ($shouldRetry) {
                Start-Sleep -Seconds 1
                continue
            }

            return [ordered]@{
                fetched = $true
                attempts = $attempt
                audit_url = $auditUrl
                project_status = [string]$audit.status
                event_count = $events.Count
                department_stage_event_count = $stageEvents.Count
                department_stage_summary_count = $summaryStages.Count
                failing_stage_count = $failingStages.Count
                failing_stages = @($failingStages | Select-Object -First 5)
            }
        } catch {
            if ($attempt -lt $maxAttempts) {
                Start-Sleep -Seconds 1
                continue
            }
            return [ordered]@{
                fetched = $false
                attempts = $attempt
                audit_url = $auditUrl
                error = [string]$_.Exception.Message
            }
        }
    }

    return [ordered]@{
        fetched = $false
        attempts = $maxAttempts
        audit_url = $auditUrl
        error = "audit snapshot retry budget exhausted"
    }
}

function Write-SeedMismatchDiagnostic {
    param(
        [string]$Name,
        [string]$TrendProvider,
        [string]$ExpectedStatus,
        [object]$ResponsePayload,
        [string]$ApiBaseUrl
    )

    $summary = $null
    if ($null -ne $ResponsePayload -and $null -ne $ResponsePayload.summary) {
        $summary = $ResponsePayload.summary
    }
    $actualStatus = if ($null -ne $summary) { [string]$summary.status } else { "" }
    $projectId = if ($null -ne $summary) { [string]$summary.project_id } else { "" }
    $nextSteps = @()
    if ($null -ne $summary -and $summary.PSObject.Properties.Name -contains "next_steps") {
        $nextSteps = @($summary.next_steps)
    }
    $auditSnapshot = Get-SeedMismatchAuditSnapshot -ApiBaseUrl $ApiBaseUrl -ProjectId $projectId

    $logRoot = Join-Path $repoRoot $LogDir
    New-Item -ItemType Directory -Force -Path $logRoot | Out-Null
    $diagPath = Join-Path $logRoot ("full-live-flow-seed-mismatch-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".json")

    $diagnostic = [ordered]@{
        generated_at_utc = [DateTime]::UtcNow.ToString("o")
        seed_name = $Name
        expected_status = $ExpectedStatus
        actual_status = $actualStatus
        project_id = $projectId
        trend_provider = $TrendProvider
        brief = [ordered]@{
            objective = $Name
            raw_request = $Name
        }
        next_steps = @($nextSteps)
        response_summary = $summary
        audit_snapshot = $auditSnapshot
    }
    $diagnostic | ConvertTo-Json -Depth 12 | Set-Content -Path $diagPath -Encoding utf8

    Write-Host ""
    Write-Host "  [seed-mismatch]"
    Write-Host ("    seed_name      : {0}" -f $Name)
    Write-Host ("    expected_status: {0}" -f $ExpectedStatus)
    Write-Host ("    actual_status  : {0}" -f $actualStatus)
    Write-Host ("    project_id     : {0}" -f $projectId)
    Write-Host ("    trend_provider : {0}" -f $TrendProvider)
    Write-Host ("    brief_objective: {0}" -f $Name)
    if ($nextSteps.Count -gt 0) {
        Write-Host ("    next_steps     : {0}" -f ($nextSteps -join " | "))
    }
    if ($null -ne $auditSnapshot) {
        Write-Host ("    audit_fetched  : {0}" -f [string]$auditSnapshot.fetched)
        if ($auditSnapshot.fetched) {
            Write-Host ("    audit_status   : {0}" -f [string]$auditSnapshot.project_status)
            Write-Host ("    audit_stage_failures: {0}" -f [int]$auditSnapshot.failing_stage_count)
        } else {
            Write-Host ("    audit_error    : {0}" -f [string]$auditSnapshot.error)
        }
    }
    Write-Host ("    diagnostic_path: {0}" -f $diagPath)
    Write-Host ""

    return $diagPath
}

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
        $diagPath = Write-SeedMismatchDiagnostic `
            -Name $Name `
            -TrendProvider $TrendProvider `
            -ExpectedStatus $ExpectedStatus `
            -ResponsePayload $response `
            -ApiBaseUrl $ApiBaseUrl
        $nextStepsText = ""
        if ($response.summary.PSObject.Properties.Name -contains "next_steps") {
            $seedNextSteps = @($response.summary.next_steps)
            if ($seedNextSteps.Count -gt 0) {
                $nextStepsText = " Next steps: " + ($seedNextSteps -join " | ")
            }
        }
        $errorMessage = (
            "Unexpected seed status for {0}: expected {1}, got {2}, project_id={3}, trend_provider={4}, diagnostic={5}. " +
            "If expected waiting_approval, verify that trend_provider still triggers approval (model alias/approval path may have changed).{6}"
        ) -f
        $Name,
        $ExpectedStatus,
        $response.summary.status,
        $response.summary.project_id,
        $TrendProvider,
        $diagPath,
        $nextStepsText
        throw $errorMessage
    }

    return $response.summary
}

if (-not $SkipPreflight) {
    & (Join-Path $repoRoot "scripts\preflight.ps1") -ApiBaseUrl $ApiBaseUrl
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$seedTrendProvider = "gemini-flash-lite-latest"

Write-Host "[1/3] create deterministic seeds"
$approvalSeed = New-SeedProject -Name "full live flow approval seed" -TrendProvider $seedTrendProvider -SimulateReviewFailure $false -ExpectedStatus "waiting_approval"
$rejectSeed = New-SeedProject -Name "full live flow reject seed" -TrendProvider $seedTrendProvider -SimulateReviewFailure $false -ExpectedStatus "waiting_approval"

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
        trend_provider = $seedTrendProvider
    }
    reject_seed = @{
        project_id = $rejectSeed.project_id
        status = $rejectSeed.status
        trend_provider = $seedTrendProvider
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
