param(
    [string]$ProjectId = "",
    [string]$ApiBaseUrl = "http://127.0.0.1:8000",
    [string]$ExpectedStatus = "",
    [switch]$FailOnStageFailure,
    [switch]$FailOnFallback,
    [int]$MaxLlmTransportFallbacks = -1,
    [switch]$RequireStageTelemetry,
    [switch]$NoEventDerivedTelemetry,
    [string]$RequireDepartments = "",
    [switch]$RequireAuthEvidence,
    [string]$ExpectedAuthRoles = "",
    [ValidateSet("normal", "strict", "breakglass")]
    [string]$AuthPolicyMode = "strict",
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
    [switch]$FailOnBackendOverrideMismatch,
    [int]$TimeoutSec = 0,
    [string]$AuditJsonPath = "",
    [string]$BundleManifestPath = "",
    [string]$OutPath = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. (Join-Path $PSScriptRoot "operator-common.ps1")
$effectiveTimeoutSec = Resolve-OperatorTimeoutSec -TimeoutSec $TimeoutSec

function Convert-ToLoweredSet {
    param([string[]]$Values)

    $set = New-Object System.Collections.Generic.HashSet[string]
    foreach ($value in @($Values)) {
        if ($null -eq $value) { continue }
        $normalized = ([string]$value).Trim().ToLowerInvariant()
        if (-not [string]::IsNullOrWhiteSpace($normalized)) {
            $set.Add($normalized) | Out-Null
        }
    }
    return $set
}

function Convert-ToDelimitedValues {
    param([string]$Raw)

    if ([string]::IsNullOrWhiteSpace($Raw)) {
        return @()
    }
    return @(
        $Raw -split "," |
            ForEach-Object { ([string]$_).Trim() } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
}

function Get-PolicyModeNode {
    param(
        [string]$Path,
        [string]$Mode
    )

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $null
    }
    if (-not (Test-Path $Path)) {
        return $null
    }
    $policy = Read-OperatorJsonFile -Path $Path
    if ($null -eq $policy) {
        return $null
    }
    if ($null -eq $policy.live_run_policy -or $null -eq $policy.live_run_policy.modes) {
        return $null
    }
    return $policy.live_run_policy.modes.$Mode
}

function Resolve-AllowlistSet {
    param(
        [string]$InlineRaw,
        [object]$PolicyValues
    )

    $inlineValues = Convert-ToDelimitedValues -Raw $InlineRaw
    if ($inlineValues.Count -gt 0) {
        return Convert-ToLoweredSet -Values $inlineValues
    }
    return Convert-ToLoweredSet -Values @($PolicyValues)
}

function Resolve-AuthRoleList {
    param([string]$Raw)

    if ([string]::IsNullOrWhiteSpace($Raw)) {
        return @()
    }
    $roles = New-Object System.Collections.Generic.List[string]
    foreach ($role in @(
        $Raw -split "," |
            ForEach-Object { ([string]$_).Trim().ToLowerInvariant() } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )) {
        if ($roles.Contains($role)) {
            continue
        }
        if ($role -in @("operator", "approver")) {
            $roles.Add($role) | Out-Null
        }
    }
    return @($roles.ToArray())
}

function Get-OpenClawAgentIdsFromModels {
    param([System.Collections.Generic.HashSet[string]]$Models)

    $agents = New-Object System.Collections.Generic.HashSet[string]
    foreach ($model in $Models) {
        if (-not $model.StartsWith("openclaw/")) { continue }
        $agentSegment = $model.Substring("openclaw/".Length)
        if ($agentSegment.Contains("@")) {
            $agentSegment = $agentSegment.Split("@", 2)[0]
        }
        $normalized = $agentSegment.Trim().ToLowerInvariant()
        if (-not [string]::IsNullOrWhiteSpace($normalized)) {
            $agents.Add($normalized) | Out-Null
        }
    }
    return $agents
}

if ([string]::IsNullOrWhiteSpace($ProjectId) -and [string]::IsNullOrWhiteSpace($BundleManifestPath)) {
    Write-Error "Either -ProjectId or -BundleManifestPath is required."
    exit 1
}

if (-not [string]::IsNullOrWhiteSpace($BundleManifestPath)) {
    $bundleContext = Resolve-OperatorCycleBundleContext -BundleManifestPath $BundleManifestPath -RepoRoot $repoRoot
    if ([string]::IsNullOrWhiteSpace($ProjectId)) {
        $ProjectId = [string]$bundleContext.project_id
    } elseif (
        -not [string]::IsNullOrWhiteSpace([string]$bundleContext.project_id) `
            -and [string]$bundleContext.project_id -ne $ProjectId
    ) {
        Write-Error (
            "Project ID mismatch between -ProjectId ({0}) and cycle bundle manifest ({1})." -f
            $ProjectId,
            [string]$bundleContext.project_id
        )
        exit 1
    }
    if ([string]::IsNullOrWhiteSpace($AuditJsonPath)) {
        $AuditJsonPath = [string]$bundleContext.audit_path
    }
}

if ([string]::IsNullOrWhiteSpace($ProjectId)) {
    Write-Error "Project ID could not be resolved."
    exit 1
}

$audit = $null
if (-not [string]::IsNullOrWhiteSpace($AuditJsonPath)) {
    $audit = Read-OperatorJsonFile -Path $AuditJsonPath
} else {
    $response = Invoke-OperatorApi `
        -Method "GET" `
        -ApiBaseUrl $ApiBaseUrl `
        -Path ("/projects/" + $ProjectId + "/audit") `
        -ExpectedStatusCodes @(200) `
        -TimeoutSec $effectiveTimeoutSec

    if ($null -eq $response.BodyJson) {
        Write-Error ("Audit assertion request succeeded but response body is not valid JSON: {0}" -f $response.BodyText)
        exit 1
    }
    $audit = $response.BodyJson
}
$errors = New-Object System.Collections.Generic.List[string]
$warnings = New-Object System.Collections.Generic.List[string]

if ([string]$audit.project_id -ne $ProjectId) {
    $errors.Add(("project_id mismatch: expected={0} actual={1}" -f $ProjectId, [string]$audit.project_id))
}

if (-not [string]::IsNullOrWhiteSpace($ExpectedStatus)) {
    if ([string]$audit.status -ne $ExpectedStatus) {
        $errors.Add(("status mismatch: expected={0} actual={1}" -f $ExpectedStatus, [string]$audit.status))
    }
}

$telemetry = Get-OperatorStageTelemetry `
    -Audit $audit `
    -AllowDerivedFromEvents:(-not $NoEventDerivedTelemetry)
$summary = @($telemetry.stage_summary)
$totals = $telemetry.stage_totals
$telemetryPresent = [bool]$telemetry.telemetry_present
$telemetrySource = [string]$telemetry.telemetry_source
$telemetryNotes = @($telemetry.notes)
$legacyFallbackNormalizations = Convert-OperatorToInt `
    -Value $telemetry.legacy_fallback_normalizations `
    -Default 0

if (-not $telemetryPresent) {
    if ($RequireStageTelemetry) {
        $errors.Add(("stage telemetry is missing from audit payload (source={0})" -f $telemetrySource))
    } else {
        $warnings.Add(("stage telemetry is missing from audit payload (source={0})" -f $telemetrySource))
    }
}
foreach ($note in $telemetryNotes) {
    $warnings.Add(("telemetry note: {0}" -f $note))
}
if ($legacyFallbackNormalizations -gt 0) {
    $warnings.Add((
        "telemetry normalized legacy fallback-only stage events: count={0}" -f
        $legacyFallbackNormalizations
    ))
}

$sumExec = 0
$sumSuccess = 0
$sumFailure = 0
$sumFallback = 0
$sumLlmTransportFallback = 0
$keys = New-Object System.Collections.Generic.HashSet[string]

foreach ($stage in $summary) {
    $sumExec += [int]$stage.execution_count
    $sumSuccess += [int]$stage.success_count
    $sumFailure += [int]$stage.failure_count
    $sumFallback += [int]$stage.fallback_count
    if ($null -ne $stage.llm_transport_fallback_count) {
        $sumLlmTransportFallback += [int]$stage.llm_transport_fallback_count
    }

    $compositeKey = ("{0}|{1}|{2}" -f [string]$stage.department, [string]$stage.sequence, [string]$stage.stage_name)
    if (-not $keys.Add($compositeKey)) {
        $errors.Add(("duplicate stage summary key detected: {0}" -f $compositeKey))
    }

    if (([int]$stage.success_count + [int]$stage.failure_count) -ne [int]$stage.execution_count) {
        $errors.Add((
            "stage count mismatch: {0} success+failure={1} execution={2}" -f
            $compositeKey,
            ([int]$stage.success_count + [int]$stage.failure_count),
            [int]$stage.execution_count
        ))
    }

    if ($FailOnStageFailure -and [int]$stage.failure_count -gt 0) {
        $errors.Add(("stage failure detected: {0} failure_count={1}" -f $compositeKey, [int]$stage.failure_count))
    }
    if (-not $FailOnStageFailure -and [int]$stage.failure_count -gt 0) {
        $warnings.Add(("stage failure observed: {0} failure_count={1}" -f $compositeKey, [int]$stage.failure_count))
    }
}

if ([int]$totals.total_stage_executions -ne $sumExec) {
    $errors.Add(("totals mismatch: total_stage_executions expected_sum={0} actual={1}" -f $sumExec, [int]$totals.total_stage_executions))
}
if ([int]$totals.total_successes -ne $sumSuccess) {
    $errors.Add(("totals mismatch: total_successes expected_sum={0} actual={1}" -f $sumSuccess, [int]$totals.total_successes))
}
if ([int]$totals.total_failures -ne $sumFailure) {
    $errors.Add(("totals mismatch: total_failures expected_sum={0} actual={1}" -f $sumFailure, [int]$totals.total_failures))
}
if ([int]$totals.total_fallbacks -ne $sumFallback) {
    $errors.Add(("totals mismatch: total_fallbacks expected_sum={0} actual={1}" -f $sumFallback, [int]$totals.total_fallbacks))
}
if ([int]$totals.total_llm_transport_fallbacks -ne $sumLlmTransportFallback) {
    $errors.Add(("totals mismatch: total_llm_transport_fallbacks expected_sum={0} actual={1}" -f $sumLlmTransportFallback, [int]$totals.total_llm_transport_fallbacks))
}

$hasFailures = ([int]$totals.total_failures -gt 0)
$hasFallbacks = ([int]$totals.total_fallbacks -gt 0)
if ([bool]$totals.has_failures -ne $hasFailures) {
    $errors.Add(("flag mismatch: has_failures expected={0} actual={1}" -f $hasFailures, [bool]$totals.has_failures))
}
if ([bool]$totals.has_fallbacks -ne $hasFallbacks) {
    $errors.Add(("flag mismatch: has_fallbacks expected={0} actual={1}" -f $hasFallbacks, [bool]$totals.has_fallbacks))
}

if ($FailOnFallback -and $hasFallbacks) {
    $errors.Add(("fallback detected: total_fallbacks={0}" -f [int]$totals.total_fallbacks))
}
if (-not $FailOnFallback -and $hasFallbacks) {
    $warnings.Add(("fallback observed: total_fallbacks={0}" -f [int]$totals.total_fallbacks))
}
if ($MaxLlmTransportFallbacks -ge 0 -and [int]$totals.total_llm_transport_fallbacks -gt $MaxLlmTransportFallbacks) {
    $errors.Add(("llm transport fallback exceeded limit: total_llm_transport_fallbacks={0} limit={1}" -f [int]$totals.total_llm_transport_fallbacks, $MaxLlmTransportFallbacks))
}

if (-not [string]::IsNullOrWhiteSpace($RequireDepartments)) {
    $required = $RequireDepartments -split "," | ForEach-Object { $_.Trim().ToLowerInvariant() } | Where-Object { $_ }
    $covered = @($totals.departments_covered | ForEach-Object { ([string]$_).ToLowerInvariant() })
    foreach ($dept in $required) {
        if ($covered -notcontains $dept) {
            $errors.Add(("required department not covered: {0}" -f $dept))
        }
    }
}

$breakglassReasonValue = ([string]$BreakglassReason).Trim()
$breakglassActorValue = ([string]$BreakglassActor).Trim()
$effectiveBreakglass = ($Breakglass -or ($AuthPolicyMode -eq "breakglass"))
if ([string]::IsNullOrWhiteSpace($breakglassActorValue)) {
    if ($effectiveBreakglass) {
        $breakglassActorValue = [Environment]::UserName
    } else {
        $breakglassActorValue = ""
    }
}
if ($effectiveBreakglass -and [string]::IsNullOrWhiteSpace($breakglassReasonValue)) {
    $errors.Add("breakglass reason is required when breakglass mode is enabled")
}

$authEvidence = Get-OperatorAuthEvidence -Audit $audit
$requiredAuthRoles = Resolve-AuthRoleList -Raw $ExpectedAuthRoles
if ($requiredAuthRoles.Count -eq 0 -and $RequireAuthEvidence) {
    $requiredAuthRoles = @("approver")
}
if ($RequireAuthEvidence) {
    foreach ($requiredRole in $requiredAuthRoles) {
        $roleEvidence = $authEvidence.roles.$requiredRole
        if ($null -eq $roleEvidence -or -not [bool]$roleEvidence.evidence_present) {
            $errors.Add(("required auth evidence missing: role={0}" -f $requiredRole))
            continue
        }
        if ($roleEvidence.auth_sources.Count -eq 0) {
            $errors.Add(("required auth source missing: role={0}" -f $requiredRole))
        }
        if ($roleEvidence.auth_modes.Count -eq 0) {
            $errors.Add(("required auth mode missing: role={0}" -f $requiredRole))
        }
    }
    if (
        $AuthPolicyMode -eq "strict" `
            -and ($requiredAuthRoles -contains "operator") `
            -and ($requiredAuthRoles -contains "approver")
    ) {
        $operatorEvidence = $authEvidence.roles.operator
        $approverEvidence = $authEvidence.roles.approver
        if (
            $operatorEvidence `
                -and $approverEvidence `
                -and [bool]$operatorEvidence.evidence_present `
                -and [bool]$approverEvidence.evidence_present
        ) {
            foreach ($operatorIdentity in @($operatorEvidence.identities)) {
                if ($approverEvidence.identities -contains $operatorIdentity) {
                    $errors.Add(("auth boundary violation: operator/approver identity overlap ({0})" -f $operatorIdentity))
                }
            }
        }
    }
}

$policyNode = Get-PolicyModeNode -Path $ModelRoutingPolicyPath -Mode $PolicyMode
$effectiveAllowlistEnforced = [bool]$EnforceModelAllowlist
$denyBackendOverrideMismatch = [bool]$FailOnBackendOverrideMismatch

$policyProviders = @()
$policyModels = @()
$policyAgents = @()
if ($null -ne $policyNode) {
    $policyProviders = @($policyNode.allowed_effective_providers)
    $policyModels = @($policyNode.allowed_effective_models)
    $policyAgents = @($policyNode.allowed_openclaw_agents)
}
$allowedProvidersSet = Resolve-AllowlistSet -InlineRaw $AllowedEffectiveProviders -PolicyValues $policyProviders
$allowedModelsSet = Resolve-AllowlistSet -InlineRaw $AllowedEffectiveModels -PolicyValues $policyModels
$allowedAgentsSet = Resolve-AllowlistSet -InlineRaw $AllowedOpenClawAgents -PolicyValues $policyAgents

$observedProvidersSet = New-Object System.Collections.Generic.HashSet[string]
$observedModelsSet = New-Object System.Collections.Generic.HashSet[string]
$observedOverrideMismatches = New-Object System.Collections.Generic.HashSet[string]
foreach ($stage in $summary) {
    foreach ($provider in @($stage.effective_providers)) {
        $normalizedProvider = ([string]$provider).Trim().ToLowerInvariant()
        if (-not [string]::IsNullOrWhiteSpace($normalizedProvider)) {
            $observedProvidersSet.Add($normalizedProvider) | Out-Null
        }
    }
    foreach ($model in @($stage.effective_models)) {
        $normalizedModel = ([string]$model).Trim().ToLowerInvariant()
        if (-not [string]::IsNullOrWhiteSpace($normalizedModel)) {
            $observedModelsSet.Add($normalizedModel) | Out-Null
        }
    }
    foreach ($mismatch in @($stage.llm_backend_override_mismatches)) {
        $normalizedMismatch = ([string]$mismatch).Trim().ToLowerInvariant()
        if (-not [string]::IsNullOrWhiteSpace($normalizedMismatch)) {
            $observedOverrideMismatches.Add($normalizedMismatch) | Out-Null
        }
    }
}
$observedAgentsSet = Get-OpenClawAgentIdsFromModels -Models $observedModelsSet

if ($effectiveAllowlistEnforced) {
    if ($allowedProvidersSet.Count -eq 0) {
        $errors.Add("model allowlist enforcement enabled but allowed_effective_providers is empty")
    }
    if ($allowedModelsSet.Count -eq 0) {
        $errors.Add("model allowlist enforcement enabled but allowed_effective_models is empty")
    }
    foreach ($provider in $observedProvidersSet) {
        if (-not $allowedProvidersSet.Contains($provider)) {
            $errors.Add(("effective provider not allowlisted: {0}" -f $provider))
        }
    }
    foreach ($model in $observedModelsSet) {
        if (-not $allowedModelsSet.Contains($model)) {
            $errors.Add(("effective model not allowlisted: {0}" -f $model))
        }
    }
    foreach ($agent in $observedAgentsSet) {
        if ($allowedAgentsSet.Count -gt 0 -and -not $allowedAgentsSet.Contains($agent)) {
            $errors.Add(("openclaw agent not allowlisted: {0}" -f $agent))
        }
    }
}

if ($denyBackendOverrideMismatch -and $observedOverrideMismatches.Count -gt 0) {
    $errors.Add((
        "backend override mismatch observed: {0}" -f
        ((Convert-OperatorSetToArray -Set $observedOverrideMismatches | Sort-Object) -join ", ")
    ))
}

$report = [ordered]@{
    project_id = [string]$audit.project_id
    status = [string]$audit.status
    asserted_at_utc = [DateTime]::UtcNow.ToString("o")
    expected_status = $ExpectedStatus
    fail_on_stage_failure = [bool]$FailOnStageFailure
    fail_on_fallback = [bool]$FailOnFallback
    max_llm_transport_fallbacks = [int]$MaxLlmTransportFallbacks
    require_stage_telemetry = [bool]$RequireStageTelemetry
    require_departments = $RequireDepartments
    require_auth_evidence = [bool]$RequireAuthEvidence
    expected_auth_roles = @($requiredAuthRoles)
    auth_policy_mode = $AuthPolicyMode
    breakglass_used = $effectiveBreakglass
    breakglass_reason = $breakglassReasonValue
    breakglass_actor = $breakglassActorValue
    auth_evidence_present = [bool]$authEvidence.overall_auth_evidence_present
    auth_evidence = $authEvidence
    policy_mode = $PolicyMode
    enforce_model_allowlist = $effectiveAllowlistEnforced
    fail_on_backend_override_mismatch = $denyBackendOverrideMismatch
    model_routing_policy_path = $ModelRoutingPolicyPath
    allowed_effective_providers = @(Convert-OperatorSetToArray -Set $allowedProvidersSet | Sort-Object)
    allowed_effective_models = @(Convert-OperatorSetToArray -Set $allowedModelsSet | Sort-Object)
    allowed_openclaw_agents = @(Convert-OperatorSetToArray -Set $allowedAgentsSet | Sort-Object)
    observed_effective_providers = @(Convert-OperatorSetToArray -Set $observedProvidersSet | Sort-Object)
    observed_effective_models = @(Convert-OperatorSetToArray -Set $observedModelsSet | Sort-Object)
    observed_openclaw_agents = @(Convert-OperatorSetToArray -Set $observedAgentsSet | Sort-Object)
    observed_backend_override_mismatches = @(
        Convert-OperatorSetToArray -Set $observedOverrideMismatches | Sort-Object
    )
    telemetry_present = $telemetryPresent
    telemetry_source = $telemetrySource
    telemetry_notes = $telemetryNotes
    telemetry_legacy_fallback_normalizations = $legacyFallbackNormalizations
    stage_totals = $totals
    stage_summary_count = $summary.Count
    error_count = $errors.Count
    warning_count = $warnings.Count
    errors = @($errors)
    warnings = @($warnings)
    passed = ($errors.Count -eq 0)
}

if (-not [string]::IsNullOrWhiteSpace($OutPath)) {
    Save-OperatorJson -Payload $report -OutPath $OutPath
}

Write-Host "[operator-audit-assert]"
Write-Host ("  project_id    : {0}" -f $report.project_id)
Write-Host ("  status        : {0}" -f $report.status)
Write-Host ("  stage_runs    : {0}" -f [int]$totals.total_stage_executions)
Write-Host ("  failures      : {0}" -f [int]$totals.total_failures)
Write-Host ("  fallbacks     : {0}" -f [int]$totals.total_fallbacks)
Write-Host ("  llm_fb        : {0}" -f [int]$totals.total_llm_transport_fallbacks)
if ($legacyFallbackNormalizations -gt 0) {
    Write-Host ("  legacy_fix    : {0}" -f $legacyFallbackNormalizations)
}
Write-Host ("  telemetry     : {0}" -f $telemetrySource)
Write-Host ("  policy_mode   : {0}" -f $PolicyMode)
Write-Host ("  allowlist     : {0}" -f $effectiveAllowlistEnforced)
Write-Host ("  override_mis  : {0}" -f $denyBackendOverrideMismatch)
Write-Host ("  auth_policy   : {0}" -f $AuthPolicyMode)
Write-Host ("  auth_required : {0}" -f [bool]$RequireAuthEvidence)
Write-Host ("  breakglass    : {0}" -f $effectiveBreakglass)
if (-not [string]::IsNullOrWhiteSpace($OutPath)) {
    Write-Host ("  out_path      : {0}" -f $OutPath)
}

if ($warnings.Count -gt 0) {
    Write-Host "  [warnings]"
    foreach ($warning in $warnings) {
        Write-Host ("    - {0}" -f $warning)
    }
}

if ($errors.Count -gt 0) {
    Write-Host "  [errors]"
    foreach ($errLine in $errors) {
        Write-Host ("    - {0}" -f $errLine)
    }
    Write-Error "[operator-audit-assert] failed"
    exit 1
}

Write-Host "[done] operator-audit-assert passed"
