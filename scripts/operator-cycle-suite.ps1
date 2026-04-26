param(
    [string]$ApiBaseUrl = "http://127.0.0.1:8000",
    [string]$BriefPath = ".\examples\briefs\sample_brief.json",
    [string]$RunTrendProvider = "gemini-flash-lite-latest",
    [string]$AuthorizationApprover = "Bearer dev-approver-token",
    [string]$AuthorizationOperator = "Bearer dev-operator-token",
    [int]$TimeoutSec = 0,
    [string]$OutputDir = "",
    [switch]$SkipApprovalMode,
    [switch]$SkipRejectReplanMode,
    [switch]$SkipStageReport,
    [switch]$SkipAuditAssertions,
    [switch]$FailOnFallback,
    [switch]$RequireStageTelemetry,
    [string]$RequireDepartments = "",
    [switch]$SkipHandoffEnvelope,
    [switch]$SkipStageGate,
    [switch]$FailOnStageGateViolation,
    [int]$MaxSuiteStageFailures = -1,
    [int]$MaxSuiteStageFallbacks = -1,
    [int]$MaxSuiteLlmTransportFallbacks = -1,
    [int]$MaxRevisionReplanAttempts = 1,
    [switch]$RequirePolicyAssertions,
    [switch]$RequireAuthEvidence,
    [string]$ExpectedAuthRoles = "",
    [string]$AuthPolicyMode = "",
    [switch]$Breakglass,
    [string]$BreakglassReason = "",
    [string]$BreakglassActor = "",
    [ValidateSet("normal", "strict", "breakglass")]
    [string]$PolicyMode = "strict",
    [string]$ModelRoutingPolicyPath = ".\docs\model_routing_policy.json",
    [switch]$EnforceModelAllowlist,
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

$modes = New-Object System.Collections.Generic.List[string]
if (-not $SkipApprovalMode) { $modes.Add("approval") | Out-Null }
if (-not $SkipRejectReplanMode) { $modes.Add("reject-replan") | Out-Null }
if ($modes.Count -eq 0) {
    Write-Error "No suite modes selected. Remove skip flags."
    exit 1
}

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $OutputDir = Join-Path $repoRoot ("logs\operator-suites\{0}" -f $stamp)
}
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

Write-Host "[operator-cycle-suite]"
Write-Host ("  api_base_url : {0}" -f $ApiBaseUrl)
Write-Host ("  brief_path   : {0}" -f $BriefPath)
Write-Host ("  output_dir   : {0}" -f $OutputDir)
Write-Host ("  modes        : {0}" -f ($modes -join ", "))

$cycleEntries = New-Object System.Collections.Generic.List[object]
$allCompleted = $true
$allAuditAssertionsPassed = $true
$totalStageRuns = 0
$totalStageFailures = 0
$totalStageFallbacks = 0
$totalLlmTransportFallbacks = 0
$totalLegacyFallbackNormalizations = 0
$totalRevisionReplanAttempts = 0
$anyRevisionReplanAttempted = $false
$allRevisionReplanCompleted = $true
$telemetrySources = New-Object System.Collections.Generic.HashSet[string]
$cycleManifestPaths = [ordered]@{}
$suiteBreakglassActor = ""
if (
    $Breakglass -or -not [string]::IsNullOrWhiteSpace(([string]$BreakglassActor).Trim())
) {
    if ([string]::IsNullOrWhiteSpace(([string]$BreakglassActor).Trim())) {
        $suiteBreakglassActor = [Environment]::UserName
    } else {
        $suiteBreakglassActor = ([string]$BreakglassActor).Trim()
    }
}

foreach ($mode in $modes) {
    $modeDir = Join-Path $OutputDir $mode
    $args = @{
        Mode = $mode
        ApiBaseUrl = $ApiBaseUrl
        BriefPath = $BriefPath
        RunTrendProvider = $RunTrendProvider
        AuthorizationApprover = $AuthorizationApprover
        AuthorizationOperator = $AuthorizationOperator
        TimeoutSec = $effectiveTimeoutSec
        OutputDir = $modeDir
    }
    if ($SkipStageReport) { $args.SkipStageReport = $true }
    if ($SkipAuditAssertions) { $args.SkipAuditAssertions = $true }
    if ($FailOnFallback) { $args.FailOnFallback = $true }
    if ($MaxSuiteLlmTransportFallbacks -ge 0) { $args.MaxLlmTransportFallbacks = $MaxSuiteLlmTransportFallbacks }
    $args.MaxRevisionReplanAttempts = $MaxRevisionReplanAttempts
    if ($RequireStageTelemetry) { $args.RequireStageTelemetry = $true }
    if ($RequireAuthEvidence) { $args.RequireAuthEvidence = $true }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedAuthRoles)) { $args.ExpectedAuthRoles = $ExpectedAuthRoles }
    if (-not [string]::IsNullOrWhiteSpace($AuthPolicyMode)) { $args.AuthPolicyMode = $AuthPolicyMode }
    if ($Breakglass) { $args.Breakglass = $true }
    if (-not [string]::IsNullOrWhiteSpace($BreakglassReason)) { $args.BreakglassReason = $BreakglassReason }
    if (-not [string]::IsNullOrWhiteSpace($BreakglassActor)) { $args.BreakglassActor = $BreakglassActor }
    if (-not [string]::IsNullOrWhiteSpace($RequireDepartments)) { $args.RequireDepartments = $RequireDepartments }
    if ($EnforceModelAllowlist) { $args.EnforceModelAllowlist = $true }
    if (-not [string]::IsNullOrWhiteSpace($PolicyMode)) { $args.PolicyMode = $PolicyMode }
    if (-not [string]::IsNullOrWhiteSpace($ModelRoutingPolicyPath)) { $args.ModelRoutingPolicyPath = $ModelRoutingPolicyPath }
    if (-not [string]::IsNullOrWhiteSpace($AllowedEffectiveProviders)) { $args.AllowedEffectiveProviders = $AllowedEffectiveProviders }
    if (-not [string]::IsNullOrWhiteSpace($AllowedEffectiveModels)) { $args.AllowedEffectiveModels = $AllowedEffectiveModels }
    if (-not [string]::IsNullOrWhiteSpace($AllowedOpenClawAgents)) { $args.AllowedOpenClawAgents = $AllowedOpenClawAgents }
    if ($FailOnBackendOverrideMismatch) { $args.FailOnBackendOverrideMismatch = $true }

    & (Join-Path $PSScriptRoot "operator-full-cycle.ps1") @args
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    $summaryPath = Join-Path $modeDir "summary.json"
    $summary = Read-OperatorJsonFile -Path $summaryPath
    $statusSummaryPath = [string]$summary.files.status_summary
    $cycleManifestPath = [string]$summary.files.bundle_manifest

    if ([string]$summary.final_status -ne "completed") {
        $allCompleted = $false
    }
    if (-not $SkipAuditAssertions -and -not [bool]$summary.audit_assert_passed) {
        $allAuditAssertionsPassed = $false
    }

    if ($null -ne $summary.stage_runs) { $totalStageRuns += [int]$summary.stage_runs }
    if ($null -ne $summary.stage_failures) { $totalStageFailures += [int]$summary.stage_failures }
    if ($null -ne $summary.stage_fallbacks) { $totalStageFallbacks += [int]$summary.stage_fallbacks }
    if ($null -ne $summary.stage_llm_transport_fallbacks) { $totalLlmTransportFallbacks += [int]$summary.stage_llm_transport_fallbacks }
    if ($null -ne $summary.stage_legacy_fallback_normalizations) {
        $totalLegacyFallbackNormalizations += [int]$summary.stage_legacy_fallback_normalizations
    }
    $revisionReplanAttemptsForCycle = Convert-OperatorToInt `
        -Value $summary.revision_replan_attempts_executed `
        -Default 0
    $revisionReplanCompletedForCycle = Convert-OperatorToBool `
        -Value $summary.revision_replan_completed `
        -Default $false
    $totalRevisionReplanAttempts += $revisionReplanAttemptsForCycle
    if ($revisionReplanAttemptsForCycle -gt 0) {
        $anyRevisionReplanAttempted = $true
        if (-not $revisionReplanCompletedForCycle) {
            $allRevisionReplanCompleted = $false
        }
    }
    $telemetrySource = [string]$summary.stage_telemetry_source
    if (-not [string]::IsNullOrWhiteSpace($telemetrySource)) {
        $telemetrySources.Add($telemetrySource) | Out-Null
    }

    $cycleEntry = [pscustomobject]@{
        mode = $mode
        summary_path = $summaryPath
        status_summary_path = $statusSummaryPath
        audit_assert_path = [string]$summary.files.audit_assert
        bundle_manifest_path = $cycleManifestPath
        project_id = [string]$summary.project_id
        final_status = [string]$summary.final_status
        audit_assert_passed = $summary.audit_assert_passed
        audit_assert_error_count = $summary.audit_assert_error_count
        stage_runs = $summary.stage_runs
        stage_failures = $summary.stage_failures
        stage_fallbacks = $summary.stage_fallbacks
        stage_llm_transport_fallbacks = $summary.stage_llm_transport_fallbacks
        stage_legacy_fallback_normalizations = $summary.stage_legacy_fallback_normalizations
        stage_telemetry_source = $summary.stage_telemetry_source
        stage_telemetry_present = $summary.stage_telemetry_present
        require_auth_evidence = [bool]$summary.require_auth_evidence
        expected_auth_roles = @($summary.expected_auth_roles)
        auth_policy_mode = [string]$summary.auth_policy_mode
        auth_evidence_present = $summary.auth_evidence_present
        breakglass_used = [bool]$summary.breakglass_used
        breakglass_reason = [string]$summary.breakglass_reason
        breakglass_actor = [string]$summary.breakglass_actor
        policy_mode = $summary.policy_mode
        enforce_model_allowlist = $summary.enforce_model_allowlist
        fail_on_backend_override_mismatch = $summary.fail_on_backend_override_mismatch
        max_revision_replan_attempts = Convert-OperatorToInt `
            -Value $summary.max_revision_replan_attempts `
            -Default $MaxRevisionReplanAttempts
        revision_replan_attempts_executed = $revisionReplanAttemptsForCycle
        revision_replan_completed = $revisionReplanCompletedForCycle
        revision_replan_final_status = [string]$summary.revision_replan_final_status
        revision_replan_statuses = @($summary.revision_replan_statuses)
        violation_count = $summary.violation_count
        violations = @($summary.violations)
    }
    $cycleEntries.Add($cycleEntry) | Out-Null
    if (-not [string]::IsNullOrWhiteSpace($cycleManifestPath)) {
        $cycleManifestPaths[$mode] = $cycleManifestPath
    }
}

$suiteSummary = [pscustomobject]@{
    executed_at_utc = [DateTime]::UtcNow.ToString("o")
    api_base_url = $ApiBaseUrl
    brief_path = $BriefPath
    output_dir = $OutputDir
    run_trend_provider = $RunTrendProvider
    modes = @($modes.ToArray())
    cycle_count = $cycleEntries.Count
    all_completed = $allCompleted
    all_audit_assertions_passed = $allAuditAssertionsPassed
    total_stage_runs = $totalStageRuns
    total_stage_failures = $totalStageFailures
    total_stage_fallbacks = $totalStageFallbacks
    total_llm_transport_fallbacks = $totalLlmTransportFallbacks
    total_stage_legacy_fallback_normalizations = $totalLegacyFallbackNormalizations
    max_revision_replan_attempts = [int]$MaxRevisionReplanAttempts
    total_revision_replan_attempts = $totalRevisionReplanAttempts
    any_revision_replan_attempted = $anyRevisionReplanAttempted
    all_revision_replan_completed = if ($anyRevisionReplanAttempted) { $allRevisionReplanCompleted } else { $true }
    stage_telemetry_sources = @(Convert-OperatorSetToArray -Set $telemetrySources | Sort-Object)
    require_auth_evidence = [bool]$RequireAuthEvidence
    expected_auth_roles = @(
        $ExpectedAuthRoles -split "," |
            ForEach-Object { ([string]$_).Trim().ToLowerInvariant() } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
    auth_policy_mode = $AuthPolicyMode
    breakglass_used = [bool]$Breakglass
    breakglass_reason = ([string]$BreakglassReason).Trim()
    breakglass_actor = $suiteBreakglassActor
    cycles = @($cycleEntries.ToArray())
    stage_gate_passed = $null
    files = @{}
}

$suiteSummaryPath = Join-Path $OutputDir "suite-summary.json"
$suiteManifestPath = Join-Path $OutputDir "bundle-manifest.json"
Save-OperatorJson -Payload $suiteSummary -OutPath $suiteSummaryPath

$handoffJsonPath = $null
$handoffMarkdownPath = $null
$stageGatePath = $null
$stageGatePassed = $null
if (-not $SkipHandoffEnvelope) {
    $handoffJsonPath = Join-Path $OutputDir "suite-handoff.json"
    $handoffMarkdownPath = Join-Path $OutputDir "suite-handoff.md"
    & (Join-Path $PSScriptRoot "operator-handoff-envelope.ps1") `
        -SuiteSummaryPath $suiteSummaryPath `
        -OutPath $handoffJsonPath `
        -MarkdownOutPath $handoffMarkdownPath `
        -VerifiedBy "operator-cycle-suite"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if (-not $SkipStageGate) {
    $stageGatePath = Join-Path $OutputDir "suite-stage-gate.json"
    & (Join-Path $PSScriptRoot "operator-stage-gate.ps1") `
        -SummaryPath $suiteSummaryPath `
        -OutPath $stageGatePath `
        -RequireAllCompleted $true `
        -RequireAuditAssertions (-not $SkipAuditAssertions) `
        -RequireStageTelemetry $RequireStageTelemetry `
        -RequirePolicyAssertions $RequirePolicyAssertions `
        -RequireAuthEvidence $RequireAuthEvidence `
        -ExpectedAuthRoles $ExpectedAuthRoles `
        -AuthPolicyMode $AuthPolicyMode `
        -Breakglass:$Breakglass `
        -BreakglassReason $BreakglassReason `
        -BreakglassActor $BreakglassActor `
        -PolicyMode $PolicyMode `
        -EnforceModelAllowlist:$EnforceModelAllowlist `
        -FailOnBackendOverrideMismatch:$FailOnBackendOverrideMismatch `
        -MaxStageFailures $MaxSuiteStageFailures `
        -MaxStageFallbacks $MaxSuiteStageFallbacks `
        -MaxLlmTransportFallbacks $MaxSuiteLlmTransportFallbacks
    $stageGateExit = $LASTEXITCODE
    if (Test-Path $stageGatePath) {
        $stageGatePayload = Read-OperatorJsonFile -Path $stageGatePath
        $stageGatePassed = [bool]$stageGatePayload.passed
    } else {
        $stageGatePassed = ($stageGateExit -eq 0)
    }
    if ($stageGateExit -ne 0) {
        if ($FailOnStageGateViolation) {
            exit $stageGateExit
        }
        Write-Warning "Stage gate reported violations; continuing because -FailOnStageGateViolation was not set."
    }
}

$suiteSummary.stage_gate_passed = $stageGatePassed
$suiteSummary.files = [ordered]@{
    suite_summary = $suiteSummaryPath
}
$suiteSummary.files["bundle_manifest"] = $suiteManifestPath
$statusSummaryPaths = [ordered]@{}
foreach ($cycle in @($cycleEntries.ToArray())) {
    if (-not [string]::IsNullOrWhiteSpace([string]$cycle.status_summary_path)) {
        $statusSummaryPaths[[string]$cycle.mode] = [string]$cycle.status_summary_path
    }
}
if ($statusSummaryPaths.Count -gt 0) {
    $suiteSummary.files["status_summaries"] = $statusSummaryPaths
}
if ($cycleManifestPaths.Count -gt 0) {
    $suiteSummary.files["cycle_manifests"] = $cycleManifestPaths
}
if ($handoffJsonPath) {
    $suiteSummary.files["handoff_json"] = $handoffJsonPath
    $suiteSummary.files["handoff_markdown"] = $handoffMarkdownPath
}
if ($stageGatePath) {
    $suiteSummary.files["stage_gate"] = $stageGatePath
}
Save-OperatorJson -Payload $suiteSummary -OutPath $suiteSummaryPath

$suiteManifestArtifacts = [ordered]@{
    suite_summary = New-OperatorManifestArtifactEntry -Path $suiteSummaryPath -RepoRoot $repoRoot
}
if ($handoffJsonPath) {
    $suiteManifestArtifacts["handoff_json"] = New-OperatorManifestArtifactEntry -Path $handoffJsonPath -RepoRoot $repoRoot
    $suiteManifestArtifacts["handoff_markdown"] = New-OperatorManifestArtifactEntry -Path $handoffMarkdownPath -RepoRoot $repoRoot
}
if ($stageGatePath) {
    $suiteManifestArtifacts["stage_gate"] = New-OperatorManifestArtifactEntry -Path $stageGatePath -RepoRoot $repoRoot
}
$suiteManifestArtifacts["bundle_manifest"] = New-OperatorManifestArtifactEntry -Path $suiteManifestPath -RepoRoot $repoRoot

$suiteManifestCycles = @(
    @($cycleEntries.ToArray()) | ForEach-Object {
        [ordered]@{
            mode = [string]$_.mode
            project_id = [string]$_.project_id
            final_status = [string]$_.final_status
            summary_path = Resolve-OperatorAbsolutePath -Path ([string]$_.summary_path) -BasePath $repoRoot
            summary_relative_path = Get-OperatorRelativePath -Path ([string]$_.summary_path) -RootPath $repoRoot
            status_summary_path = Resolve-OperatorAbsolutePath -Path ([string]$_.status_summary_path) -BasePath $repoRoot
            status_summary_relative_path = Get-OperatorRelativePath -Path ([string]$_.status_summary_path) -RootPath $repoRoot
            audit_assert_path = Resolve-OperatorAbsolutePath -Path ([string]$_.audit_assert_path) -BasePath $repoRoot
            audit_assert_relative_path = Get-OperatorRelativePath -Path ([string]$_.audit_assert_path) -RootPath $repoRoot
            bundle_manifest_path = Resolve-OperatorAbsolutePath -Path ([string]$_.bundle_manifest_path) -BasePath $repoRoot
            bundle_manifest_relative_path = Get-OperatorRelativePath -Path ([string]$_.bundle_manifest_path) -RootPath $repoRoot
            stage_telemetry_source = [string]$_.stage_telemetry_source
            stage_telemetry_present = [bool]$_.stage_telemetry_present
            require_auth_evidence = [bool]$_.require_auth_evidence
            expected_auth_roles = @($_.expected_auth_roles)
            auth_policy_mode = [string]$_.auth_policy_mode
            auth_evidence_present = $_.auth_evidence_present
            breakglass_used = [bool]$_.breakglass_used
            breakglass_reason = [string]$_.breakglass_reason
            breakglass_actor = [string]$_.breakglass_actor
            policy_mode = [string]$_.policy_mode
            enforce_model_allowlist = [bool]$_.enforce_model_allowlist
            fail_on_backend_override_mismatch = [bool]$_.fail_on_backend_override_mismatch
            max_revision_replan_attempts = [int]$_.max_revision_replan_attempts
            revision_replan_attempts_executed = [int]$_.revision_replan_attempts_executed
            revision_replan_completed = [bool]$_.revision_replan_completed
            revision_replan_final_status = [string]$_.revision_replan_final_status
            revision_replan_statuses = @($_.revision_replan_statuses)
        }
    }
)

$suiteManifest = [ordered]@{
    bundle_type = "suite"
    bundle_version = 1
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    output_dir = Resolve-OperatorAbsolutePath -Path $OutputDir -BasePath $repoRoot
    output_dir_relative_to_repo = Get-OperatorRelativePath -Path $OutputDir -RootPath $repoRoot
    cycle_count = $suiteSummary.cycle_count
    all_completed = $suiteSummary.all_completed
    all_audit_assertions_passed = $suiteSummary.all_audit_assertions_passed
    stage_gate_passed = $suiteSummary.stage_gate_passed
    max_revision_replan_attempts = [int]$suiteSummary.max_revision_replan_attempts
    total_revision_replan_attempts = [int]$suiteSummary.total_revision_replan_attempts
    any_revision_replan_attempted = [bool]$suiteSummary.any_revision_replan_attempted
    all_revision_replan_completed = [bool]$suiteSummary.all_revision_replan_completed
    require_auth_evidence = $suiteSummary.require_auth_evidence
    expected_auth_roles = @($suiteSummary.expected_auth_roles)
    auth_policy_mode = $suiteSummary.auth_policy_mode
    breakglass_used = $suiteSummary.breakglass_used
    breakglass_reason = $suiteSummary.breakglass_reason
    breakglass_actor = $suiteSummary.breakglass_actor
    replay_defaults = [ordered]@{
        suite_summary = "suite_summary"
        handoff_json = "handoff_json"
        stage_gate = "stage_gate"
    }
    cycles = $suiteManifestCycles
    artifacts = $suiteManifestArtifacts
}
Save-OperatorJson -Payload $suiteManifest -OutPath $suiteManifestPath

Write-Host ""
Write-Host ("  cycle_count  : {0}" -f $suiteSummary.cycle_count)
Write-Host ("  all_completed: {0}" -f $suiteSummary.all_completed)
Write-Host ("  stage_runs   : {0}" -f $suiteSummary.total_stage_runs)
Write-Host ("  llm_fb       : {0}" -f $suiteSummary.total_llm_transport_fallbacks)
if ([int]$suiteSummary.total_revision_replan_attempts -gt 0) {
    Write-Host (
        "  revise+replan: attempts={0} completed={1}" -f
        [int]$suiteSummary.total_revision_replan_attempts,
        [bool]$suiteSummary.all_revision_replan_completed
    )
}
if ($suiteSummary.total_stage_legacy_fallback_normalizations -gt 0) {
    Write-Host ("  legacy_fix   : {0}" -f $suiteSummary.total_stage_legacy_fallback_normalizations)
}
if ($suiteSummary.stage_telemetry_sources -and $suiteSummary.stage_telemetry_sources.Count -gt 0) {
    Write-Host ("  telemetry    : {0}" -f ($suiteSummary.stage_telemetry_sources -join ", "))
}
if ($suiteSummary.files.status_summaries) {
    if ($suiteSummary.files.status_summaries -is [System.Collections.IDictionary]) {
        foreach ($statusSummaryKey in $suiteSummary.files.status_summaries.Keys) {
            Write-Host ("  status_sum   : {0} -> {1}" -f [string]$statusSummaryKey, [string]$suiteSummary.files.status_summaries[$statusSummaryKey])
        }
    } else {
        foreach ($statusSummaryEntry in $suiteSummary.files.status_summaries.PSObject.Properties) {
            Write-Host ("  status_sum   : {0} -> {1}" -f $statusSummaryEntry.Name, [string]$statusSummaryEntry.Value)
        }
    }
}
Write-Host ("  summary_path : {0}" -f $suiteSummaryPath)
Write-Host ("  manifest     : {0}" -f $suiteManifestPath)
if ($handoffJsonPath) {
    Write-Host ("  handoff_json : {0}" -f $handoffJsonPath)
    Write-Host ("  handoff_md   : {0}" -f $handoffMarkdownPath)
}
if ($stageGatePath) {
    Write-Host ("  stage_gate   : {0} (passed={1})" -f $stageGatePath, $stageGatePassed)
}
Write-Host ""
Write-Host "[done] operator-cycle-suite completed"
