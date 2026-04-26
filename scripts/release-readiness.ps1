param(
    [string]$ApiBaseUrl = "http://127.0.0.1:8000",
    [string]$Authorization = "Bearer dev-approver-token",
    [string]$ProjectId = "",
    [string]$ApprovalProjectId = "",
    [string]$RejectProjectId = "",
    [string]$RevisionProjectId = "",
    [string]$ReplanningProjectId = "",
    [string]$LogDir = "logs\operational-readiness",
    [switch]$AutoSeedFullFlow,
    [switch]$SkipLiveSmoke,
    [switch]$SkipSmoke,
    [switch]$SkipResilience,
    [switch]$SkipVerify,
    [switch]$RunOperatorSuite,
    [switch]$RunOpenClawGatewayCheck,
    [string]$OperatorBriefPath = ".\examples\briefs\sample_brief.json",
    [string]$OperatorRunTrendProvider = "gemini-flash-lite-latest",
    [string]$OperatorAuthorizationOperator = "Bearer dev-operator-token",
    [string]$OperatorOutputDir = "",
    [switch]$OperatorSkipApprovalMode,
    [switch]$OperatorSkipRejectReplanMode,
    [switch]$OperatorFailOnFallback,
    [switch]$OperatorRequireStageTelemetry,
    [switch]$OperatorRequirePolicyAssertions,
    [switch]$OperatorRequireAuthEvidence,
    [string]$OperatorExpectedAuthRoles = "",
    [string]$OperatorAuthPolicyMode = "",
    [switch]$OperatorBreakglass,
    [string]$OperatorBreakglassReason = "",
    [string]$OperatorBreakglassActor = "",
    [int]$OperatorMaxStageFailures = -1,
    [int]$OperatorMaxStageFallbacks = -1,
    [int]$OperatorMaxLlmTransportFallbacks = -1,
    [int]$OperatorMaxRevisionReplanAttempts = 1,
    [ValidateSet("normal", "strict", "breakglass")]
    [string]$OperatorPolicyMode = "strict",
    [string]$OperatorModelRoutingPolicyPath = ".\docs\model_routing_policy.json",
    [switch]$OperatorEnforceModelAllowlist,
    [string]$OperatorAllowedEffectiveProviders = "",
    [string]$OperatorAllowedEffectiveModels = "",
    [string]$OperatorAllowedOpenClawAgents = "",
    [switch]$OperatorFailOnBackendOverrideMismatch,
    [string]$OpenClawGatewayBaseUrl = "",
    [string]$OpenClawGatewayAgentId = "codex-orchestrator",
    [string]$OpenClawBackendModel = "",
    [int]$OpenClawGatewayTimeoutSec = 0,
    [int]$OpenClawGatewayProbeTimeoutSec = 0,
    [string]$OpenClawEvidenceOutPath = "",
    [switch]$AppendOpenClawStagingRecord,
    [string]$OpenClawStagingRecordPath = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. (Join-Path $repoRoot "scripts\operator-common.ps1")
$runStamp = Get-Date -Format "yyyyMMdd-HHmmss"
$resolvedLogDir = Join-Path $repoRoot $LogDir
$readinessSummaryPath = Join-Path $resolvedLogDir ("readiness-summary-{0}.json" -f $runStamp)
$readinessManifestPath = Join-Path $resolvedLogDir ("readiness-manifest-{0}.json" -f $runStamp)
$readinessStages = [ordered]@{}
$readinessArtifacts = [ordered]@{}

function Get-LatestReadinessArtifact {
    param(
        [string]$Directory,
        [string]$Filter,
        [DateTime]$NotBeforeUtc
    )

    if ([string]::IsNullOrWhiteSpace($Directory) -or -not (Test-Path $Directory)) {
        return ""
    }

    $items = Get-ChildItem -Path $Directory -Filter $Filter -File -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTimeUtc -ge $NotBeforeUtc.AddSeconds(-2) } |
        Sort-Object LastWriteTimeUtc -Descending
    if ($items -and $items.Count -gt 0) {
        return $items[0].FullName
    }
    return ""
}

function Add-ReadinessArtifact {
    param(
        [string]$Name,
        [string]$Path
    )

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return
    }
    $artifactEntry = New-OperatorManifestArtifactEntry -Path $Path -RepoRoot $repoRoot
    if ($null -ne $artifactEntry) {
        $readinessArtifacts[$Name] = $artifactEntry
    }
}

$totalSteps = 1
if (-not $SkipLiveSmoke) { $totalSteps++ }
if (-not $SkipSmoke) { $totalSteps++ }
if (-not $SkipResilience) { $totalSteps++ }
if (-not $SkipVerify) { $totalSteps++ }
if ($RunOperatorSuite) { $totalSteps++ }
if ($RunOpenClawGatewayCheck) { $totalSteps++ }
$stepIndex = 1

Write-Host ("[{0}/{1}] Preflight" -f $stepIndex, $totalSteps)
$preflightStage = [ordered]@{
    executed = $true
    passed = $false
    script = "scripts\\preflight.ps1"
}
& (Join-Path $repoRoot "scripts\preflight.ps1") -ApiBaseUrl $ApiBaseUrl
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$preflightStage.passed = $true
$readinessStages["preflight"] = $preflightStage
$stepIndex++

if (-not $SkipLiveSmoke) {
    $liveSmokeStartedUtc = [DateTime]::UtcNow
    $liveSmokeStage = [ordered]@{
        executed = $true
        passed = $false
        mode = if ($AutoSeedFullFlow) { "auto_seed" } else { "manual" }
        script = if ($AutoSeedFullFlow) { "scripts\\full-live-flow.ps1" } else { "scripts\\live-smoke.ps1" }
    }
    if ($AutoSeedFullFlow) {
        Write-Host ("[{0}/{1}] Live smoke with automatic seeds" -f $stepIndex, $totalSteps)
        & (Join-Path $repoRoot "scripts\full-live-flow.ps1") -ApiBaseUrl $ApiBaseUrl -Authorization $Authorization -LogDir $LogDir -SkipPreflight
    } else {
        Write-Host ("[{0}/{1}] Live smoke" -f $stepIndex, $totalSteps)
        & (Join-Path $repoRoot "scripts\live-smoke.ps1") -ApiBaseUrl $ApiBaseUrl -Authorization $Authorization -ProjectId $ProjectId -ApprovalProjectId $ApprovalProjectId -RejectProjectId $RejectProjectId -RevisionProjectId $RevisionProjectId -ReplanningProjectId $ReplanningProjectId -LogDir $LogDir -SkipPreflight
    }
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $liveSmokeStage.passed = $true
    $liveSmokeLogPath = Get-LatestReadinessArtifact -Directory $resolvedLogDir -Filter "live-smoke-*.json" -NotBeforeUtc $liveSmokeStartedUtc
    if (-not [string]::IsNullOrWhiteSpace($liveSmokeLogPath)) {
        $liveSmokeStage.live_smoke_log_path = $liveSmokeLogPath
        Add-ReadinessArtifact -Name "live_smoke_log" -Path $liveSmokeLogPath
    }
    if ($AutoSeedFullFlow) {
        $seedLogPath = Get-LatestReadinessArtifact -Directory $resolvedLogDir -Filter "full-live-flow-seeds-*.json" -NotBeforeUtc $liveSmokeStartedUtc
        if (-not [string]::IsNullOrWhiteSpace($seedLogPath)) {
            $liveSmokeStage.seed_log_path = $seedLogPath
            Add-ReadinessArtifact -Name "full_live_flow_seed_log" -Path $seedLogPath
        }
    }
    $readinessStages["live_smoke"] = $liveSmokeStage
    $stepIndex++
}

if (-not $SkipSmoke) {
    Write-Host ("[{0}/{1}] Smoke" -f $stepIndex, $totalSteps)
    $smokeStage = [ordered]@{
        executed = $true
        passed = $false
        script = "scripts\\smoke.ps1"
    }
    & (Join-Path $repoRoot "scripts\smoke.ps1") -ApiBaseUrl $ApiBaseUrl -SkipPreflight
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $smokeStage.passed = $true
    $readinessStages["smoke"] = $smokeStage
    $stepIndex++
}

if (-not $SkipResilience) {
    Write-Host ("[{0}/{1}] Resilience" -f $stepIndex, $totalSteps)
    $resilienceStage = [ordered]@{
        executed = $true
        passed = $false
        script = "scripts\\resilience.ps1"
    }
    & (Join-Path $repoRoot "scripts\resilience.ps1") -ApiBaseUrl $ApiBaseUrl -SkipPreflight
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $resilienceStage.passed = $true
    $readinessStages["resilience"] = $resilienceStage
    $stepIndex++
}

if (-not $SkipVerify) {
    Write-Host ("[{0}/{1}] Full verification" -f $stepIndex, $totalSteps)
    $verifyStage = [ordered]@{
        executed = $true
        passed = $false
        script = "scripts\\verify.ps1"
    }
    & (Join-Path $repoRoot "scripts\verify.ps1")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $verifyStage.passed = $true
    $readinessStages["verify"] = $verifyStage
    $stepIndex++
}

if ($RunOperatorSuite) {
    if ($OperatorMaxRevisionReplanAttempts -lt 1) {
        Write-Error "OperatorMaxRevisionReplanAttempts must be >= 1."
        exit 1
    }
    Write-Host ("[{0}/{1}] Operator suite gate" -f $stepIndex, $totalSteps)
    $operatorSuiteStage = [ordered]@{
        executed = $true
        passed = $false
        script = "scripts\\operator-cycle-suite.ps1"
    }
    if ([string]::IsNullOrWhiteSpace($OperatorOutputDir)) {
        $OperatorOutputDir = Join-Path $resolvedLogDir ("operator-suite-{0}" -f $runStamp)
    }
    $suiteArgs = @{
        ApiBaseUrl = $ApiBaseUrl
        BriefPath = $OperatorBriefPath
        RunTrendProvider = $OperatorRunTrendProvider
        AuthorizationApprover = $Authorization
        AuthorizationOperator = $OperatorAuthorizationOperator
        FailOnStageGateViolation = $true
        MaxSuiteStageFailures = $OperatorMaxStageFailures
        MaxSuiteStageFallbacks = $OperatorMaxStageFallbacks
        MaxSuiteLlmTransportFallbacks = $OperatorMaxLlmTransportFallbacks
        MaxRevisionReplanAttempts = $OperatorMaxRevisionReplanAttempts
    }
    if (-not [string]::IsNullOrWhiteSpace($OperatorOutputDir)) {
        $suiteArgs.OutputDir = $OperatorOutputDir
    }
    if ($OperatorFailOnFallback) {
        $suiteArgs.FailOnFallback = $true
    }
    if ($OperatorSkipApprovalMode) {
        $suiteArgs.SkipApprovalMode = $true
    }
    if ($OperatorSkipRejectReplanMode) {
        $suiteArgs.SkipRejectReplanMode = $true
    }
    if ($OperatorRequireStageTelemetry) {
        $suiteArgs.RequireStageTelemetry = $true
    }
    if ($OperatorRequirePolicyAssertions) {
        $suiteArgs.RequirePolicyAssertions = $true
    }
    if ($OperatorRequireAuthEvidence) {
        $suiteArgs.RequireAuthEvidence = $true
    }
    if (-not [string]::IsNullOrWhiteSpace($OperatorExpectedAuthRoles)) {
        $suiteArgs.ExpectedAuthRoles = $OperatorExpectedAuthRoles
    }
    if (-not [string]::IsNullOrWhiteSpace($OperatorAuthPolicyMode)) {
        $suiteArgs.AuthPolicyMode = $OperatorAuthPolicyMode
    }
    if ($OperatorBreakglass) {
        $suiteArgs.Breakglass = $true
    }
    if (-not [string]::IsNullOrWhiteSpace($OperatorBreakglassReason)) {
        $suiteArgs.BreakglassReason = $OperatorBreakglassReason
    }
    if (-not [string]::IsNullOrWhiteSpace($OperatorBreakglassActor)) {
        $suiteArgs.BreakglassActor = $OperatorBreakglassActor
    }
    if (-not [string]::IsNullOrWhiteSpace($OperatorPolicyMode)) {
        $suiteArgs.PolicyMode = $OperatorPolicyMode
    }
    if (-not [string]::IsNullOrWhiteSpace($OperatorModelRoutingPolicyPath)) {
        $suiteArgs.ModelRoutingPolicyPath = $OperatorModelRoutingPolicyPath
    }
    if ($OperatorEnforceModelAllowlist) {
        $suiteArgs.EnforceModelAllowlist = $true
    }
    if (-not [string]::IsNullOrWhiteSpace($OperatorAllowedEffectiveProviders)) {
        $suiteArgs.AllowedEffectiveProviders = $OperatorAllowedEffectiveProviders
    }
    if (-not [string]::IsNullOrWhiteSpace($OperatorAllowedEffectiveModels)) {
        $suiteArgs.AllowedEffectiveModels = $OperatorAllowedEffectiveModels
    }
    if (-not [string]::IsNullOrWhiteSpace($OperatorAllowedOpenClawAgents)) {
        $suiteArgs.AllowedOpenClawAgents = $OperatorAllowedOpenClawAgents
    }
    if ($OperatorFailOnBackendOverrideMismatch) {
        $suiteArgs.FailOnBackendOverrideMismatch = $true
    }

    & (Join-Path $repoRoot "scripts\operator-cycle-suite.ps1") @suiteArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    $suiteManifestPath = Join-Path $OperatorOutputDir "bundle-manifest.json"
    $suiteManifest = $null
    if (Test-Path $suiteManifestPath) {
        $suiteManifest = Read-OperatorBundleManifest -Path $suiteManifestPath
        Write-Host ("  operator manifest: {0}" -f $suiteManifestPath)
        $operatorSuiteStage.suite_manifest_path = $suiteManifestPath
        Add-ReadinessArtifact -Name "operator_suite_manifest" -Path $suiteManifestPath
    }
    $suiteSummaryPath = if ($suiteManifest) {
        Resolve-OperatorBundlePrimarySummaryPath -Manifest $suiteManifest -RepoRoot $repoRoot
    } else {
        Join-Path $OperatorOutputDir "suite-summary.json"
    }
    if (Test-Path $suiteSummaryPath) {
        $suiteSummary = Read-OperatorJsonFile -Path $suiteSummaryPath
        $operatorSuiteStage.suite_summary_path = $suiteSummaryPath
        Add-ReadinessArtifact -Name "operator_suite_summary" -Path $suiteSummaryPath
        Write-Host ("  operator summary : {0}" -f $suiteSummaryPath)
        Write-Host ("  operator cycles  : {0}" -f [int]$suiteSummary.cycle_count)
        Write-Host ("  operator runs    : {0}" -f [int]$suiteSummary.total_stage_runs)
        Write-Host ("  operator fail    : {0}" -f [int]$suiteSummary.total_stage_failures)
        Write-Host ("  operator fb      : {0}" -f [int]$suiteSummary.total_stage_fallbacks)
        Write-Host ("  operator llm fb  : {0}" -f [int]$suiteSummary.total_llm_transport_fallbacks)
        if ($null -ne $suiteSummary.total_stage_legacy_fallback_normalizations -and [int]$suiteSummary.total_stage_legacy_fallback_normalizations -gt 0) {
            Write-Host ("  operator legacy  : {0}" -f [int]$suiteSummary.total_stage_legacy_fallback_normalizations)
        }
        if ($suiteSummary.stage_telemetry_sources -and $suiteSummary.stage_telemetry_sources.Count -gt 0) {
            Write-Host ("  operator source  : {0}" -f ($suiteSummary.stage_telemetry_sources -join ", "))
        }
        if ($suiteManifest -and $suiteManifest.cycles) {
            foreach ($cycle in @($suiteManifest.cycles)) {
                if ($cycle.status_summary_path) {
                    Write-Host ("  operator status  : {0} -> {1}" -f [string]$cycle.mode, [string]$cycle.status_summary_path)
                }
            }
        } elseif ($suiteSummary.files.status_summaries) {
            if ($suiteSummary.files.status_summaries -is [System.Collections.IDictionary]) {
                foreach ($statusSummaryKey in $suiteSummary.files.status_summaries.Keys) {
                    Write-Host ("  operator status  : {0} -> {1}" -f [string]$statusSummaryKey, [string]$suiteSummary.files.status_summaries[$statusSummaryKey])
                }
            } else {
                foreach ($statusSummaryEntry in $suiteSummary.files.status_summaries.PSObject.Properties) {
                    Write-Host ("  operator status  : {0} -> {1}" -f $statusSummaryEntry.Name, [string]$statusSummaryEntry.Value)
                }
            }
        } elseif ($suiteSummary.cycles) {
            foreach ($cycle in @($suiteSummary.cycles)) {
                if ($cycle.status_summary_path) {
                    Write-Host ("  operator status  : {0} -> {1}" -f [string]$cycle.mode, [string]$cycle.status_summary_path)
                }
            }
        }
        $stageGatePath = if ($suiteManifest) {
            Resolve-OperatorBundleArtifactPath -Manifest $suiteManifest -ArtifactName "stage_gate" -RepoRoot $repoRoot
        } else {
            [string]$suiteSummary.files.stage_gate
        }
        if (-not [string]::IsNullOrWhiteSpace($stageGatePath)) {
            Write-Host ("  operator gate    : {0}" -f $stageGatePath)
            $operatorSuiteStage.stage_gate_path = $stageGatePath
            Add-ReadinessArtifact -Name "operator_suite_stage_gate" -Path $stageGatePath
        }
        $handoffPath = if ($suiteManifest) {
            Resolve-OperatorBundleArtifactPath -Manifest $suiteManifest -ArtifactName "handoff_json" -RepoRoot $repoRoot
        } else {
            [string]$suiteSummary.files.handoff_json
        }
        if (-not [string]::IsNullOrWhiteSpace($handoffPath)) {
            Write-Host ("  operator handoff : {0}" -f $handoffPath)
            $operatorSuiteStage.handoff_json_path = $handoffPath
            Add-ReadinessArtifact -Name "operator_suite_handoff" -Path $handoffPath
        }
    }
    $operatorSuiteStage.passed = $true
    $readinessStages["operator_suite"] = $operatorSuiteStage
    $stepIndex++
}

if ($RunOpenClawGatewayCheck) {
    Write-Host ("[{0}/{1}] OpenClaw gateway check" -f $stepIndex, $totalSteps)
    $openClawStage = [ordered]@{
        executed = $true
        passed = $false
        script = "scripts\\openclaw-gateway-check.ps1"
    }
    $gatewayArgs = @{
        AgentId = $OpenClawGatewayAgentId
    }
    if (-not [string]::IsNullOrWhiteSpace($OpenClawGatewayBaseUrl)) {
        $gatewayArgs.GatewayBaseUrl = $OpenClawGatewayBaseUrl
    }
    if (-not [string]::IsNullOrWhiteSpace($OpenClawBackendModel)) {
        $gatewayArgs.BackendModel = $OpenClawBackendModel
    }
    if ($OpenClawGatewayTimeoutSec -gt 0) {
        $gatewayArgs.TimeoutSec = $OpenClawGatewayTimeoutSec
    }
    if ($OpenClawGatewayProbeTimeoutSec -gt 0) {
        $gatewayArgs.ProbeTimeoutSec = $OpenClawGatewayProbeTimeoutSec
    }
    if ([string]::IsNullOrWhiteSpace($OpenClawEvidenceOutPath)) {
        $OpenClawEvidenceOutPath = Join-Path $resolvedLogDir ("openclaw-gateway-check-{0}.json" -f $runStamp)
    }
    if (-not [string]::IsNullOrWhiteSpace($OpenClawEvidenceOutPath)) {
        $gatewayArgs.EvidenceOutPath = $OpenClawEvidenceOutPath
    }
    if ($AppendOpenClawStagingRecord) {
        $gatewayArgs.AppendStagingRecord = $true
        if (-not [string]::IsNullOrWhiteSpace($OpenClawStagingRecordPath)) {
            $gatewayArgs.StagingRecordPath = $OpenClawStagingRecordPath
        }
    }

    & (Join-Path $repoRoot "scripts\openclaw-gateway-check.ps1") @gatewayArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    if (-not [string]::IsNullOrWhiteSpace($OpenClawEvidenceOutPath)) {
        Write-Host ("  openclaw evidence : {0}" -f $OpenClawEvidenceOutPath)
        $openClawStage.evidence_path = $OpenClawEvidenceOutPath
        Add-ReadinessArtifact -Name "openclaw_evidence" -Path $OpenClawEvidenceOutPath
    }
    $openClawStage.passed = $true
    $readinessStages["openclaw_gateway_check"] = $openClawStage
}

$operatorBreakglassActorSummary = ""
if (
    $OperatorBreakglass -or -not [string]::IsNullOrWhiteSpace(([string]$OperatorBreakglassActor).Trim())
) {
    if ([string]::IsNullOrWhiteSpace(([string]$OperatorBreakglassActor).Trim())) {
        $operatorBreakglassActorSummary = [Environment]::UserName
    } else {
        $operatorBreakglassActorSummary = ([string]$OperatorBreakglassActor).Trim()
    }
}

$readinessSummary = [ordered]@{
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    run_stamp = $runStamp
    api_base_url = $ApiBaseUrl
    log_dir = Resolve-OperatorAbsolutePath -Path $resolvedLogDir -BasePath $repoRoot
    log_dir_relative_to_repo = Get-OperatorRelativePath -Path $resolvedLogDir -RootPath $repoRoot
    overall_passed = $true
    flags = [ordered]@{
        auto_seed_full_flow = [bool]$AutoSeedFullFlow
        skip_live_smoke = [bool]$SkipLiveSmoke
        skip_smoke = [bool]$SkipSmoke
        skip_resilience = [bool]$SkipResilience
        skip_verify = [bool]$SkipVerify
        run_operator_suite = [bool]$RunOperatorSuite
        run_openclaw_gateway_check = [bool]$RunOpenClawGatewayCheck
        operator_require_stage_telemetry = [bool]$OperatorRequireStageTelemetry
        operator_require_policy_assertions = [bool]$OperatorRequirePolicyAssertions
        operator_require_auth_evidence = [bool]$OperatorRequireAuthEvidence
        operator_expected_auth_roles = @(
            $OperatorExpectedAuthRoles -split "," |
                ForEach-Object { ([string]$_).Trim().ToLowerInvariant() } |
                Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
        )
        operator_auth_policy_mode = $OperatorAuthPolicyMode
        operator_breakglass = [bool]$OperatorBreakglass
        operator_breakglass_reason = ([string]$OperatorBreakglassReason).Trim()
        operator_breakglass_actor = $operatorBreakglassActorSummary
        operator_skip_approval_mode = [bool]$OperatorSkipApprovalMode
        operator_skip_reject_replan_mode = [bool]$OperatorSkipRejectReplanMode
        operator_authorization_operator_provided = -not [string]::IsNullOrWhiteSpace(([string]$OperatorAuthorizationOperator).Trim())
        operator_max_stage_failures = [int]$OperatorMaxStageFailures
        operator_max_stage_fallbacks = [int]$OperatorMaxStageFallbacks
        operator_max_llm_transport_fallbacks = [int]$OperatorMaxLlmTransportFallbacks
        operator_max_revision_replan_attempts = [int]$OperatorMaxRevisionReplanAttempts
        operator_policy_mode = $OperatorPolicyMode
        operator_enforce_model_allowlist = [bool]$OperatorEnforceModelAllowlist
        operator_fail_on_backend_override_mismatch = [bool]$OperatorFailOnBackendOverrideMismatch
    }
    stages = $readinessStages
}
Save-OperatorJson -Payload $readinessSummary -OutPath $readinessSummaryPath
Add-ReadinessArtifact -Name "readiness_summary" -Path $readinessSummaryPath

$readinessManifest = [ordered]@{
    bundle_type = "readiness"
    bundle_version = 1
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    run_stamp = $runStamp
    log_dir = Resolve-OperatorAbsolutePath -Path $resolvedLogDir -BasePath $repoRoot
    log_dir_relative_to_repo = Get-OperatorRelativePath -Path $resolvedLogDir -RootPath $repoRoot
    overall_passed = $true
    replay_defaults = [ordered]@{
        summary = "readiness_summary"
        operator_suite_manifest = "operator_suite_manifest"
        operator_suite_summary = "operator_suite_summary"
        openclaw_evidence = "openclaw_evidence"
    }
    stages = $readinessStages
    artifacts = $readinessArtifacts
}
Save-OperatorJson -Payload $readinessManifest -OutPath $readinessManifestPath

Write-Host ""
Write-Host ("  readiness summary  : {0}" -f $readinessSummaryPath)
Write-Host ("  readiness manifest : {0}" -f $readinessManifestPath)
Write-Host "All checks passed!"
