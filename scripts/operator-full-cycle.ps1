param(
    [ValidateSet("approval", "reject-replan")]
    [string]$Mode = "approval",
    [string]$ApiBaseUrl = "http://127.0.0.1:8000",
    [string]$BriefPath = ".\examples\briefs\sample_brief.json",
    [string]$RunTrendProvider = "gemini-flash-lite-latest",
    [string]$AuthorizationApprover = "Bearer dev-approver-token",
    [string]$AuthorizationOperator = "Bearer dev-operator-token",
    [string]$ApproveActions = "external_api_send",
    [string]$ApproveNote = "Approved by operator full-cycle",
    [string]$ApproveTrendProvider = "mock",
    [string]$RejectActions = "external_api_send",
    [string]$RejectReason = "Security policy",
    [string]$RejectNote = "Rejected by operator full-cycle",
    [string]$RevisionMode = "replanning",
    [string]$RevisionReason = "Revision triggered by operator full-cycle",
    [string]$RevisionTrendProvider = "mock",
    [string]$ReplanNote = "Replanning started by operator full-cycle",
    [string]$ReplanTrendProvider = "mock",
    [int]$TimeoutSec = 0,
    [string]$OutputDir = "",
    [switch]$SkipStageReport,
    [switch]$SkipAuditAssertions,
    [switch]$FailOnFallback,
    [int]$MaxLlmTransportFallbacks = -1,
    [int]$MaxRevisionReplanAttempts = 1,
    [switch]$RequireStageTelemetry,
    [switch]$NoEventDerivedTelemetry,
    [string]$RequireDepartments = "",
    [switch]$RequireAuthEvidence,
    [string]$ExpectedAuthRoles = "",
    [string]$AuthPolicyMode = "",
    [switch]$Breakglass,
    [string]$BreakglassReason = "",
    [string]$BreakglassActor = "",
    [switch]$EnforceModelAllowlist,
    [ValidateSet("normal", "strict", "breakglass")]
    [string]$PolicyMode = "strict",
    [string]$ModelRoutingPolicyPath = ".\docs\model_routing_policy.json",
    [string]$AllowedEffectiveProviders = "",
    [string]$AllowedEffectiveModels = "",
    [string]$AllowedOpenClawAgents = "",
    [switch]$FailOnBackendOverrideMismatch
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. (Join-Path $PSScriptRoot "operator-common.ps1")
$effectiveTimeoutSec = Resolve-OperatorTimeoutSec -TimeoutSec $TimeoutSec

if (
    -not [string]::IsNullOrWhiteSpace($AuthPolicyMode) `
        -and $AuthPolicyMode -notin @("normal", "strict", "breakglass")
) {
    Write-Error ("Invalid AuthPolicyMode '{0}'. Valid values: normal, strict, breakglass" -f $AuthPolicyMode)
    exit 1
}
if ($MaxRevisionReplanAttempts -lt 1) {
    Write-Error "MaxRevisionReplanAttempts must be >= 1."
    exit 1
}

function Resolve-ExpectedAuthRolesForCycle {
    param(
        [bool]$RequireAuthEvidenceFlag,
        [string]$ExpectedAuthRolesRaw
    )

    $roles = New-Object System.Collections.Generic.List[string]
    if (-not [string]::IsNullOrWhiteSpace($ExpectedAuthRolesRaw)) {
        foreach ($role in @(
            $ExpectedAuthRolesRaw -split "," |
                ForEach-Object { ([string]$_).Trim().ToLowerInvariant() } |
                Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
        )) {
            if ($role -in @("operator", "approver") -and -not $roles.Contains($role)) {
                $roles.Add($role) | Out-Null
            }
        }
    }
    if ($RequireAuthEvidenceFlag -and $roles.Count -eq 0) {
        $roles.Add("approver") | Out-Null
    }
    return @($roles.ToArray())
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $repoRoot ("logs\operator-cycles\{0}-{1}" -f $stamp, $Mode)
}
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$runOutPath = Join-Path $OutputDir "run.json"
$statusOutPath = Join-Path $OutputDir "status.json"
$statusSummaryOutPath = Join-Path $OutputDir "status-summary.json"
$auditOutPath = Join-Path $OutputDir "audit.json"
$stageReportOutPath = Join-Path $OutputDir "stage-report.json"
$auditAssertOutPath = Join-Path $OutputDir "audit-assert.json"
$bundleManifestOutPath = Join-Path $OutputDir "bundle-manifest.json"
$summaryOutPath = Join-Path $OutputDir "summary.json"
$cycleViolations = New-Object System.Collections.Generic.List[string]
$requiredAuthRolesForCycle = Resolve-ExpectedAuthRolesForCycle `
    -RequireAuthEvidenceFlag $RequireAuthEvidence `
    -ExpectedAuthRolesRaw $ExpectedAuthRoles
$operatorAuthProbeRequired = (
    $Mode -eq "approval" `
        -and $RequireAuthEvidence `
        -and ($requiredAuthRolesForCycle -contains "operator")
)

Write-Host ("[operator-full-cycle] mode={0}" -f $Mode)
Write-Host ("  api_base_url : {0}" -f $ApiBaseUrl)
Write-Host ("  brief_path   : {0}" -f $BriefPath)
Write-Host ("  output_dir   : {0}" -f $OutputDir)

& (Join-Path $PSScriptRoot "operator-run.ps1") `
    -BriefPath $BriefPath `
    -ApiBaseUrl $ApiBaseUrl `
    -TrendProvider $RunTrendProvider `
    -TimeoutSec $effectiveTimeoutSec `
    -OutPath $runOutPath
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$runPayload = Read-OperatorJsonFile -Path $runOutPath
$projectId = [string]$runPayload.summary.project_id
$runStatus = [string]$runPayload.summary.status
if ([string]::IsNullOrWhiteSpace($projectId)) {
    Write-Error "operator-run response did not include summary.project_id"
    exit 1
}

if ($runStatus -ne "waiting_approval") {
    $runNextSteps = @($runPayload.summary.next_steps)
    $runNextStepsText = ""
    if ($runNextSteps.Count -gt 0) {
        $runNextStepsText = " Next steps: " + ($runNextSteps -join " | ")
    }
    Write-Error (
        "operator-run returned status '{0}', expected 'waiting_approval', project_id='{1}'. " +
        "Use a trend provider that enters approval gate (for example gemini-flash-lite-latest)." +
        "{2}" -f $runStatus, $projectId, $runNextStepsText
    )
    exit 1
}

$stepFiles = [ordered]@{
    run = $runOutPath
}

function Invoke-RevisionReplanAttempts {
    param(
        [Parameter(Mandatory = $true)][string]$ProjectIdValue,
        [Parameter(Mandatory = $true)][int]$AttemptLimit,
        [Parameter(Mandatory = $true)][string]$StepContext
    )

    $attemptsExecuted = 0
    $attemptStatuses = New-Object System.Collections.Generic.List[string]
    $finalStatus = ""
    $completed = $false

    for ($attempt = 1; $attempt -le $AttemptLimit; $attempt++) {
        $attemptsExecuted = $attempt
        $reviseOutPath = if ($attempt -eq 1) {
            Join-Path $OutputDir "revise.json"
        } else {
            Join-Path $OutputDir ("revise-attempt-{0}.json" -f $attempt)
        }
        $replanOutPath = if ($attempt -eq 1) {
            Join-Path $OutputDir "replan.json"
        } else {
            Join-Path $OutputDir ("replan-attempt-{0}.json" -f $attempt)
        }

        $revisionReasonForAttempt = if ($attempt -eq 1) {
            $RevisionReason
        } else {
            "{0} (retry attempt {1}/{2})" -f $RevisionReason, $attempt, $AttemptLimit
        }
        $replanNoteForAttempt = if ($attempt -eq 1) {
            $ReplanNote
        } else {
            "{0} (retry attempt {1}/{2})" -f $ReplanNote, $attempt, $AttemptLimit
        }

        & (Join-Path $PSScriptRoot "operator-revise.ps1") `
            -ProjectId $ProjectIdValue `
            -ApiBaseUrl $ApiBaseUrl `
            -Authorization $AuthorizationOperator `
            -ResumeMode $RevisionMode `
            -Reason $revisionReasonForAttempt `
            -TrendProvider $RevisionTrendProvider `
            -TimeoutSec $effectiveTimeoutSec `
            -OutPath $reviseOutPath
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

        & (Join-Path $PSScriptRoot "operator-replan.ps1") `
            -ProjectId $ProjectIdValue `
            -ApiBaseUrl $ApiBaseUrl `
            -Authorization $AuthorizationOperator `
            -Note $replanNoteForAttempt `
            -TrendProvider $ReplanTrendProvider `
            -TimeoutSec $effectiveTimeoutSec `
            -OutPath $replanOutPath
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

        if ($attempt -eq 1) {
            $stepFiles["revise"] = $reviseOutPath
            $stepFiles["replan"] = $replanOutPath
        } else {
            $stepFiles[("revise_attempt_{0}" -f $attempt)] = $reviseOutPath
            $stepFiles[("replan_attempt_{0}" -f $attempt)] = $replanOutPath
        }

        $replanPayload = Read-OperatorJsonFile -Path $replanOutPath
        $finalStatus = [string]$replanPayload.summary.status
        if ([string]::IsNullOrWhiteSpace($finalStatus)) {
            $finalStatus = [string]$replanPayload.status
        }
        if ([string]::IsNullOrWhiteSpace($finalStatus)) {
            $finalStatus = "unknown"
        }
        $attemptStatuses.Add($finalStatus) | Out-Null

        if ($finalStatus -eq "completed") {
            $completed = $true
            break
        }
        if ($finalStatus -ne "revision_requested") {
            Write-Host (
                "  [warn] {0} attempt {1}/{2} returned status '{3}' (expected completed/revision_requested)." -f
                $StepContext,
                $attempt,
                $AttemptLimit,
                $finalStatus
            )
            break
        }
        if ($attempt -lt $AttemptLimit) {
            Write-Host (
                "  [info] {0} attempt {1}/{2} ended with revision_requested; retrying revise+replan." -f
                $StepContext,
                $attempt,
                $AttemptLimit
            )
        }
    }

    return [pscustomobject]@{
        attempts_executed = $attemptsExecuted
        attempt_limit = $AttemptLimit
        completed = $completed
        final_status = $finalStatus
        statuses = @($attemptStatuses.ToArray())
    }
}

$revisionReplanAttemptResult = [pscustomobject]@{
    attempts_executed = 0
    attempt_limit = $MaxRevisionReplanAttempts
    completed = $false
    final_status = ""
    statuses = @()
}

if ($operatorAuthProbeRequired) {
    if ([string]::IsNullOrWhiteSpace(([string]$AuthorizationOperator).Trim())) {
        Write-Error (
            "Operator auth evidence is required but AuthorizationOperator is empty. " +
            "Provide -AuthorizationOperator with an operator bearer token."
        )
        exit 1
    }

    $operatorAuthProbeOutPath = Join-Path $OutputDir "operator-auth-probe.json"
    $operatorAuthProbePayload = @{
        project_id = $projectId
        resume_mode = $RevisionMode
        reason = "Operator auth evidence probe (no-op)"
        trend_provider = $RevisionTrendProvider
        approved_actions = @()
    }

    Write-Host "  [info] collecting operator auth evidence with protected no-op probe."
    $probeResponse = Invoke-OperatorApi `
        -Method "POST" `
        -ApiBaseUrl $ApiBaseUrl `
        -Path "/orchestrator/resume/revision" `
        -BodyObject $operatorAuthProbePayload `
        -Authorization $AuthorizationOperator `
        -ExpectedStatusCodes @(409) `
        -TimeoutSec $effectiveTimeoutSec

    $probeResult = [ordered]@{
        project_id = $projectId
        endpoint = "/orchestrator/resume/revision"
        expected_status_codes = @(409)
        status_code = [int]$probeResponse.StatusCode
        authorization_header_present = $true
        note = "No-op probe to emit operator authentication/authorization audit events."
        response_body = [string]$probeResponse.BodyText
    }
    Save-OperatorJson -Payload $probeResult -OutPath $operatorAuthProbeOutPath
    $stepFiles["operator_auth_probe"] = $operatorAuthProbeOutPath
}

if ($Mode -eq "approval") {
    $approveOutPath = Join-Path $OutputDir "approve.json"
    & (Join-Path $PSScriptRoot "operator-approve.ps1") `
        -ProjectId $projectId `
        -ApiBaseUrl $ApiBaseUrl `
        -Authorization $AuthorizationApprover `
        -ApprovedActions $ApproveActions `
        -Note $ApproveNote `
        -TrendProvider $ApproveTrendProvider `
        -TimeoutSec $effectiveTimeoutSec `
        -OutPath $approveOutPath
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $stepFiles["approve"] = $approveOutPath

    $approvePayload = Read-OperatorJsonFile -Path $approveOutPath
    $approveStatus = [string]$approvePayload.summary.status
    if ($approveStatus -eq "revision_requested") {
        Write-Host "  [info] approval path returned revision_requested; continuing via revise+replan attempts."
        $revisionReplanAttemptResult = Invoke-RevisionReplanAttempts `
            -ProjectIdValue $projectId `
            -AttemptLimit $MaxRevisionReplanAttempts `
            -StepContext "approval"
    }
} else {
    $rejectOutPath = Join-Path $OutputDir "reject.json"
    & (Join-Path $PSScriptRoot "operator-reject.ps1") `
        -ProjectId $projectId `
        -ApiBaseUrl $ApiBaseUrl `
        -Authorization $AuthorizationApprover `
        -RejectedActions $RejectActions `
        -Reason $RejectReason `
        -Note $RejectNote `
        -TimeoutSec $effectiveTimeoutSec `
        -OutPath $rejectOutPath
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    $stepFiles["reject"] = $rejectOutPath
    $revisionReplanAttemptResult = Invoke-RevisionReplanAttempts `
        -ProjectIdValue $projectId `
        -AttemptLimit $MaxRevisionReplanAttempts `
        -StepContext "reject-replan"
}

& (Join-Path $PSScriptRoot "operator-status.ps1") `
    -ProjectId $projectId `
    -ApiBaseUrl $ApiBaseUrl `
    -TimeoutSec $effectiveTimeoutSec `
    -OutPath $statusOutPath `
    -SummaryOutPath $statusSummaryOutPath
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$stepFiles["status"] = $statusOutPath
$stepFiles["status_summary"] = $statusSummaryOutPath

& (Join-Path $PSScriptRoot "operator-audit.ps1") `
    -ProjectId $projectId `
    -ApiBaseUrl $ApiBaseUrl `
    -Full `
    -TimeoutSec $effectiveTimeoutSec `
    -OutPath $auditOutPath
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$stepFiles["audit"] = $auditOutPath

if (-not $SkipStageReport) {
    $stageReportArgs = @{
        ProjectId = $projectId
        ApiBaseUrl = $ApiBaseUrl
        TimeoutSec = $effectiveTimeoutSec
        OutPath = $stageReportOutPath
    }
    if ($RequireStageTelemetry) {
        $stageReportArgs.RequireStageTelemetry = $true
    }
    if ($NoEventDerivedTelemetry) {
        $stageReportArgs.NoEventDerivedTelemetry = $true
    }

    & (Join-Path $PSScriptRoot "operator-stage-report.ps1") @stageReportArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $stepFiles["stage_report"] = $stageReportOutPath
}

$auditAssertPassed = $null
$auditAssertErrorCount = 0
$auditAssertErrors = @()
$auditAssertAuthEvidencePresent = $null
$auditAssertExpectedAuthRoles = @(
    Convert-OperatorToStringArray -Value $requiredAuthRolesForCycle
)
$auditAssertAuthPolicyMode = $AuthPolicyMode
$auditAssertBreakglassUsed = $false
$auditAssertBreakglassReason = ([string]$BreakglassReason).Trim()
$auditAssertBreakglassActor = ([string]$BreakglassActor).Trim()
if (-not $SkipAuditAssertions) {
    $assertArgs = @{
        ProjectId = $projectId
        ApiBaseUrl = $ApiBaseUrl
        ExpectedStatus = "completed"
        TimeoutSec = $effectiveTimeoutSec
        OutPath = $auditAssertOutPath
    }
    if (-not [string]::IsNullOrWhiteSpace($RequireDepartments)) {
        $assertArgs.RequireDepartments = $RequireDepartments
    }
    if ($FailOnFallback) {
        $assertArgs.FailOnFallback = $true
    }
    if ($MaxLlmTransportFallbacks -ge 0) {
        $assertArgs.MaxLlmTransportFallbacks = $MaxLlmTransportFallbacks
    }
    if ($RequireStageTelemetry) {
        $assertArgs.RequireStageTelemetry = $true
    }
    if ($RequireAuthEvidence) {
        $assertArgs.RequireAuthEvidence = $true
    }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedAuthRoles)) {
        $assertArgs.ExpectedAuthRoles = $ExpectedAuthRoles
    }
    if (-not [string]::IsNullOrWhiteSpace($AuthPolicyMode)) {
        $assertArgs.AuthPolicyMode = $AuthPolicyMode
    }
    if ($Breakglass) {
        $assertArgs.Breakglass = $true
    }
    if (-not [string]::IsNullOrWhiteSpace($BreakglassReason)) {
        $assertArgs.BreakglassReason = $BreakglassReason
    }
    if (-not [string]::IsNullOrWhiteSpace($BreakglassActor)) {
        $assertArgs.BreakglassActor = $BreakglassActor
    }
    if ($NoEventDerivedTelemetry) {
        $assertArgs.NoEventDerivedTelemetry = $true
    }
    if ($EnforceModelAllowlist) {
        $assertArgs.EnforceModelAllowlist = $true
    }
    $hasAllowlistInputs = $EnforceModelAllowlist `
        -or $FailOnBackendOverrideMismatch `
        -or (-not [string]::IsNullOrWhiteSpace($AllowedEffectiveProviders)) `
        -or (-not [string]::IsNullOrWhiteSpace($AllowedEffectiveModels)) `
        -or (-not [string]::IsNullOrWhiteSpace($AllowedOpenClawAgents))
    if ($hasAllowlistInputs) {
        if (-not [string]::IsNullOrWhiteSpace($PolicyMode)) {
            $assertArgs.PolicyMode = $PolicyMode
        }
        if (-not [string]::IsNullOrWhiteSpace($ModelRoutingPolicyPath)) {
            $assertArgs.ModelRoutingPolicyPath = $ModelRoutingPolicyPath
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($AllowedEffectiveProviders)) {
        $assertArgs.AllowedEffectiveProviders = $AllowedEffectiveProviders
    }
    if (-not [string]::IsNullOrWhiteSpace($AllowedEffectiveModels)) {
        $assertArgs.AllowedEffectiveModels = $AllowedEffectiveModels
    }
    if (-not [string]::IsNullOrWhiteSpace($AllowedOpenClawAgents)) {
        $assertArgs.AllowedOpenClawAgents = $AllowedOpenClawAgents
    }
    if ($FailOnBackendOverrideMismatch) {
        $assertArgs.FailOnBackendOverrideMismatch = $true
    }

    & (Join-Path $PSScriptRoot "operator-audit-assert.ps1") @assertArgs
    $auditAssertExit = $LASTEXITCODE

    $stepFiles["audit_assert"] = $auditAssertOutPath
    $auditAssertPayload = $null
    if (Test-Path $auditAssertOutPath) {
        $auditAssertPayload = Read-OperatorJsonFile -Path $auditAssertOutPath
    }
    if ($auditAssertPayload) {
        $auditAssertPassed = [bool]$auditAssertPayload.passed
        $auditAssertErrorCount = Convert-OperatorToInt -Value $auditAssertPayload.error_count -Default 0
        $auditAssertErrors = @($auditAssertPayload.errors)
        $auditAssertAuthEvidencePresent = Convert-OperatorToBool `
            -Value $auditAssertPayload.auth_evidence_present `
            -Default $false
        $auditAssertExpectedAuthRoles = @(
            Convert-OperatorToStringArray -Value $auditAssertPayload.expected_auth_roles
        )
        $auditAssertAuthPolicyMode = [string]$auditAssertPayload.auth_policy_mode
        $auditAssertBreakglassUsed = Convert-OperatorToBool `
            -Value $auditAssertPayload.breakglass_used `
            -Default $false
        $auditAssertBreakglassReason = [string]$auditAssertPayload.breakglass_reason
        $auditAssertBreakglassActor = [string]$auditAssertPayload.breakglass_actor
    } else {
        $auditAssertPassed = ($auditAssertExit -eq 0)
    }
    if ($auditAssertExit -ne 0 -or $auditAssertPassed -ne $true) {
        $cycleViolations.Add("operator-audit-assert reported policy/runtime violations") | Out-Null
        foreach ($errorLine in @($auditAssertErrors)) {
            $normalizedError = ([string]$errorLine).Trim()
            if (-not [string]::IsNullOrWhiteSpace($normalizedError)) {
                $cycleViolations.Add(("audit_assert_error: {0}" -f $normalizedError)) | Out-Null
            }
        }
    }
}

$statusPayload = Read-OperatorJsonFile -Path $statusOutPath
$statusSummaryPayload = $null
if (Test-Path $statusSummaryOutPath) {
    $statusSummaryPayload = Read-OperatorJsonFile -Path $statusSummaryOutPath
}
$auditPayload = Read-OperatorJsonFile -Path $auditOutPath
$stageReportPayload = $null
if ((-not $SkipStageReport) -and (Test-Path $stageReportOutPath)) {
    $stageReportPayload = Read-OperatorJsonFile -Path $stageReportOutPath
}
$stageTelemetrySource = "none"
$stageTelemetryPresent = $false
$stageTelemetryNotes = @()
$stageLegacyFallbackNormalizations = 0
$stageTotals = New-OperatorEmptyStageTotals
if ($stageReportPayload) {
    $stageTelemetrySource = [string]$stageReportPayload.telemetry_source
    if ([string]::IsNullOrWhiteSpace($stageTelemetrySource)) {
        $stageTelemetrySource = if ([bool]$stageReportPayload.telemetry_present) { "report" } else { "none" }
    }
    $stageTelemetryPresent = [bool]$stageReportPayload.telemetry_present
    $stageTelemetryNotes = @($stageReportPayload.telemetry_notes)
    $stageLegacyFallbackNormalizations = Convert-OperatorToInt `
        -Value $stageReportPayload.telemetry_legacy_fallback_normalizations `
        -Default 0
    if ($null -ne $stageReportPayload.stage_totals) {
        $stageTotals = $stageReportPayload.stage_totals
    }
} elseif ($statusSummaryPayload) {
    $stageTelemetrySource = [string]$statusSummaryPayload.telemetry_source
    if ([string]::IsNullOrWhiteSpace($stageTelemetrySource)) {
        $stageTelemetrySource = if ([bool]$statusSummaryPayload.telemetry_present) { "summary_derived" } else { "none" }
    }
    $stageTelemetryPresent = [bool]$statusSummaryPayload.telemetry_present
    $stageTelemetryNotes = @($statusSummaryPayload.telemetry_notes)
    $stageLegacyFallbackNormalizations = Convert-OperatorToInt `
        -Value $statusSummaryPayload.telemetry_legacy_fallback_normalizations `
        -Default 0
    if ($null -ne $statusSummaryPayload.stage_totals) {
        $stageTotals = $statusSummaryPayload.stage_totals
    }
} else {
    $derivedTelemetry = Get-OperatorStageTelemetry `
        -Audit $auditPayload `
        -AllowDerivedFromEvents:(-not $NoEventDerivedTelemetry)
    $stageTelemetrySource = [string]$derivedTelemetry.telemetry_source
    $stageTelemetryPresent = [bool]$derivedTelemetry.telemetry_present
    $stageTelemetryNotes = @($derivedTelemetry.notes)
    $stageLegacyFallbackNormalizations = Convert-OperatorToInt `
        -Value $derivedTelemetry.legacy_fallback_normalizations `
        -Default 0
    $stageTotals = $derivedTelemetry.stage_totals
}

$summary = [ordered]@{
    executed_at_utc = [DateTime]::UtcNow.ToString("o")
    mode = $Mode
    project_id = $projectId
    run_status = $runStatus
    final_status = [string]$auditPayload.status
    stage_runs = [int]$stageTotals.total_stage_executions
    stage_failures = [int]$stageTotals.total_failures
    stage_fallbacks = [int]$stageTotals.total_fallbacks
    stage_llm_transport_fallbacks = [int]$stageTotals.total_llm_transport_fallbacks
    stage_llm_endpoints_observed = @($stageTotals.llm_endpoints_observed)
    stage_telemetry_present = $stageTelemetryPresent
    stage_telemetry_source = $stageTelemetrySource
    stage_telemetry_notes = @($stageTelemetryNotes)
    stage_legacy_fallback_normalizations = $stageLegacyFallbackNormalizations
    audit_assert_passed = $auditAssertPassed
    audit_assert_error_count = $auditAssertErrorCount
    audit_assert_errors = @($auditAssertErrors)
    require_auth_evidence = [bool]$RequireAuthEvidence
    expected_auth_roles = @($auditAssertExpectedAuthRoles)
    auth_policy_mode = $auditAssertAuthPolicyMode
    auth_evidence_present = $auditAssertAuthEvidencePresent
    breakglass_used = $auditAssertBreakglassUsed
    breakglass_reason = $auditAssertBreakglassReason
    breakglass_actor = $auditAssertBreakglassActor
    policy_mode = $PolicyMode
    enforce_model_allowlist = [bool]$EnforceModelAllowlist
    fail_on_backend_override_mismatch = [bool]$FailOnBackendOverrideMismatch
    max_revision_replan_attempts = [int]$MaxRevisionReplanAttempts
    revision_replan_attempts_executed = [int]$revisionReplanAttemptResult.attempts_executed
    revision_replan_completed = [bool]$revisionReplanAttemptResult.completed
    revision_replan_final_status = [string]$revisionReplanAttemptResult.final_status
    revision_replan_statuses = @($revisionReplanAttemptResult.statuses)
    violation_count = $cycleViolations.Count
    violations = @($cycleViolations)
    output_dir = $OutputDir
    files = $stepFiles
}
$stepFiles["bundle_manifest"] = $bundleManifestOutPath

Save-OperatorJson -Payload $summary -OutPath $summaryOutPath

$manifestArtifacts = [ordered]@{}
foreach ($artifactEntry in $stepFiles.GetEnumerator()) {
    $artifactDetails = New-OperatorManifestArtifactEntry -Path ([string]$artifactEntry.Value) -RepoRoot $repoRoot
    if ($null -ne $artifactDetails) {
        $manifestArtifacts[[string]$artifactEntry.Key] = $artifactDetails
    }
}
$manifestArtifacts["summary"] = New-OperatorManifestArtifactEntry -Path $summaryOutPath -RepoRoot $repoRoot

$bundleManifest = [ordered]@{
    bundle_type = "cycle"
    bundle_version = 1
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    output_dir = Resolve-OperatorAbsolutePath -Path $OutputDir -BasePath $repoRoot
    output_dir_relative_to_repo = Get-OperatorRelativePath -Path $OutputDir -RootPath $repoRoot
    mode = $Mode
    project_id = $projectId
    run_status = $runStatus
    final_status = [string]$summary.final_status
    stage_telemetry_present = $stageTelemetryPresent
    stage_telemetry_source = $stageTelemetrySource
    stage_legacy_fallback_normalizations = $stageLegacyFallbackNormalizations
    require_auth_evidence = [bool]$RequireAuthEvidence
    expected_auth_roles = @($auditAssertExpectedAuthRoles)
    auth_policy_mode = $auditAssertAuthPolicyMode
    auth_evidence_present = $auditAssertAuthEvidencePresent
    breakglass_used = $auditAssertBreakglassUsed
    breakglass_reason = $auditAssertBreakglassReason
    breakglass_actor = $auditAssertBreakglassActor
    policy_mode = $PolicyMode
    enforce_model_allowlist = [bool]$EnforceModelAllowlist
    fail_on_backend_override_mismatch = [bool]$FailOnBackendOverrideMismatch
    max_revision_replan_attempts = [int]$MaxRevisionReplanAttempts
    revision_replan_attempts_executed = [int]$revisionReplanAttemptResult.attempts_executed
    revision_replan_completed = [bool]$revisionReplanAttemptResult.completed
    revision_replan_final_status = [string]$revisionReplanAttemptResult.final_status
    revision_replan_statuses = @($revisionReplanAttemptResult.statuses)
    violation_count = $cycleViolations.Count
    violations = @($cycleViolations)
    replay_defaults = [ordered]@{
        summary = "summary"
        status = "status"
        status_summary = "status_summary"
        audit = "audit"
        stage_report = "stage_report"
        audit_assert = "audit_assert"
    }
    artifacts = $manifestArtifacts
}
Save-OperatorJson -Payload $bundleManifest -OutPath $bundleManifestOutPath

Write-Host ""
Write-Host ("  project_id   : {0}" -f $projectId)
Write-Host ("  final_status : {0}" -f $summary.final_status)
Write-Host ("  stage_runs   : {0}" -f $summary.stage_runs)
Write-Host ("  telemetry    : {0}" -f $summary.stage_telemetry_source)
if ($summary.violation_count -gt 0) {
    Write-Host ("  violations   : {0}" -f $summary.violation_count)
}
if ($summary.stage_legacy_fallback_normalizations -gt 0) {
    Write-Host ("  legacy_fix   : {0}" -f $summary.stage_legacy_fallback_normalizations)
}
Write-Host ("  status_sum   : {0}" -f $statusSummaryOutPath)
Write-Host ("  manifest     : {0}" -f $bundleManifestOutPath)
Write-Host ("  summary_path : {0}" -f $summaryOutPath)
Write-Host ""
if ($cycleViolations.Count -gt 0) {
    Write-Host "  [violations]"
    foreach ($cycleViolation in $cycleViolations) {
        Write-Host ("    - {0}" -f $cycleViolation)
    }
    Write-Error "[operator-full-cycle] failed"
    exit 1
}

Write-Host "[done] operator-full-cycle completed"
