param(
    [string]$SummaryPath = "",
    [string]$BundleManifestPath = "",
    [string]$OutPath = "",
    [bool]$RequireAllCompleted = $true,
    [bool]$RequireAuditAssertions = $true,
    [bool]$RequireStageTelemetry = $false,
    [bool]$RequirePolicyAssertions = $false,
    [bool]$RequireAuthEvidence = $false,
    [string]$ExpectedAuthRoles = "",
    [string]$AuthPolicyMode = "",
    [switch]$Breakglass,
    [string]$BreakglassReason = "",
    [string]$BreakglassActor = "",
    [ValidateSet("normal", "strict", "breakglass")]
    [string]$PolicyMode = "",
    [switch]$EnforceModelAllowlist,
    [switch]$FailOnBackendOverrideMismatch,
    [int]$MaxStageFailures = -1,
    [int]$MaxStageFallbacks = -1,
    [int]$MaxLlmTransportFallbacks = -1
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. (Join-Path $PSScriptRoot "operator-common.ps1")

if ([string]::IsNullOrWhiteSpace($SummaryPath) -and [string]::IsNullOrWhiteSpace($BundleManifestPath)) {
    Write-Error "Either -SummaryPath or -BundleManifestPath is required."
    exit 1
}

if (-not [string]::IsNullOrWhiteSpace($SummaryPath) -and -not [string]::IsNullOrWhiteSpace($BundleManifestPath)) {
    Write-Error "Specify only one of -SummaryPath or -BundleManifestPath."
    exit 1
}

if (
    -not [string]::IsNullOrWhiteSpace($AuthPolicyMode) `
        -and $AuthPolicyMode -notin @("normal", "strict", "breakglass")
) {
    Write-Error ("Invalid AuthPolicyMode '{0}'. Valid values: normal, strict, breakglass" -f $AuthPolicyMode)
    exit 1
}

if (-not [string]::IsNullOrWhiteSpace($BundleManifestPath)) {
    $bundleManifest = Read-OperatorBundleManifest -Path $BundleManifestPath
    $SummaryPath = Resolve-OperatorBundlePrimarySummaryPath -Manifest $bundleManifest -RepoRoot $repoRoot
    if ([string]::IsNullOrWhiteSpace($SummaryPath)) {
        Write-Error ("Bundle manifest does not define a usable summary path: {0}" -f $BundleManifestPath)
        exit 1
    }
}

function Convert-ToNullableInt {
    param([object]$Value)

    if ($null -eq $Value) {
        return $null
    }
    if ($Value -is [int]) {
        return [int]$Value
    }
    $parsed = 0
    if ([int]::TryParse([string]$Value, [ref]$parsed)) {
        return $parsed
    }
    return $null
}

function Convert-ToNullableBool {
    param([object]$Value)

    if ($null -eq $Value) {
        return $null
    }
    if ($Value -is [bool]) {
        return [bool]$Value
    }
    $parsed = $false
    if ([bool]::TryParse([string]$Value, [ref]$parsed)) {
        return $parsed
    }
    return $null
}

function Convert-ToNullableString {
    param([object]$Value)

    if ($null -eq $Value) {
        return $null
    }
    $text = [string]$Value
    if ([string]::IsNullOrWhiteSpace($text)) {
        return $null
    }
    return $text
}

function Resolve-OperatorStatusSummaryPath {
    param([Parameter(Mandatory = $true)]$Source)

    $statusSummaryPath = Convert-ToNullableString -Value $Source.status_summary_path
    if ($statusSummaryPath) {
        return $statusSummaryPath
    }
    if ($null -ne $Source.files) {
        return Convert-ToNullableString -Value $Source.files.status_summary
    }
    return $null
}

function Resolve-OperatorAuditAssertPath {
    param([Parameter(Mandatory = $true)]$Source)

    $auditAssertPath = Convert-ToNullableString -Value $Source.audit_assert_path
    if ($auditAssertPath) {
        return $auditAssertPath
    }
    if ($null -ne $Source.files) {
        return Convert-ToNullableString -Value $Source.files.audit_assert
    }
    return $null
}

function Resolve-NullableIntValue {
    param(
        [object]$Primary,
        [object]$Fallback
    )

    $primaryValue = Convert-ToNullableInt -Value $Primary
    if ($null -ne $primaryValue) {
        return $primaryValue
    }
    return Convert-ToNullableInt -Value $Fallback
}

function Resolve-NullableBoolValue {
    param(
        [object]$Primary,
        [object]$Fallback
    )

    $primaryValue = Convert-ToNullableBool -Value $Primary
    if ($null -ne $primaryValue) {
        return $primaryValue
    }
    return Convert-ToNullableBool -Value $Fallback
}

function Resolve-ExpectedAuthRoles {
    param(
        [string]$InlineRaw,
        [object]$FallbackValues
    )

    $roles = New-Object System.Collections.Generic.List[string]
    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($InlineRaw)) {
        $candidates = @(
            $InlineRaw -split "," |
                ForEach-Object { ([string]$_).Trim().ToLowerInvariant() } |
                Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
        )
    } else {
        $candidates = @(
            @($FallbackValues) |
                ForEach-Object { ([string]$_).Trim().ToLowerInvariant() } |
                Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
        )
    }
    foreach ($candidate in $candidates) {
        if ($candidate -in @("operator", "approver") -and -not $roles.Contains($candidate)) {
            $roles.Add($candidate) | Out-Null
        }
    }
    return @($roles.ToArray())
}

function New-CycleGateView {
    param(
        [Parameter(Mandatory = $true)]$Source,
        [string]$SummaryPathValue = "",
        [string]$StatusSummaryPathValue = "",
        $StatusSummary = $null
    )

    $statusStageTotals = $null
    if ($StatusSummary) {
        $statusStageTotals = $StatusSummary.stage_totals
    }

    $finalStatus = Convert-ToNullableString -Value $Source.final_status
    if (-not $finalStatus) {
        $finalStatus = Convert-ToNullableString -Value $StatusSummary.status
    }

    $projectId = Convert-ToNullableString -Value $Source.project_id
    if (-not $projectId) {
        $projectId = Convert-ToNullableString -Value $StatusSummary.project_id
    }

    $stageTelemetrySource = Convert-ToNullableString -Value $Source.stage_telemetry_source
    if (-not $stageTelemetrySource) {
        $stageTelemetrySource = Convert-ToNullableString -Value $StatusSummary.telemetry_source
    }

    return [pscustomobject]@{
        mode = [string]$Source.mode
        project_id = $projectId
        final_status = $finalStatus
        audit_assert_passed = Convert-ToNullableBool -Value $Source.audit_assert_passed
        stage_runs = Resolve-NullableIntValue -Primary $Source.stage_runs -Fallback $statusStageTotals.total_stage_executions
        stage_failures = Resolve-NullableIntValue -Primary $Source.stage_failures -Fallback $statusStageTotals.total_failures
        stage_fallbacks = Resolve-NullableIntValue -Primary $Source.stage_fallbacks -Fallback $statusStageTotals.total_fallbacks
        stage_llm_transport_fallbacks = Resolve-NullableIntValue -Primary $Source.stage_llm_transport_fallbacks -Fallback $statusStageTotals.total_llm_transport_fallbacks
        stage_legacy_fallback_normalizations = Resolve-NullableIntValue -Primary $Source.stage_legacy_fallback_normalizations -Fallback $StatusSummary.telemetry_legacy_fallback_normalizations
        stage_telemetry_present = Resolve-NullableBoolValue -Primary $Source.stage_telemetry_present -Fallback $StatusSummary.telemetry_present
        stage_telemetry_source = $stageTelemetrySource
        summary_path = $SummaryPathValue
        status_summary_path = $StatusSummaryPathValue
        audit_assert_path = Resolve-OperatorAuditAssertPath -Source $Source
    }
}

function Resolve-SummaryType {
    param([Parameter(Mandatory = $true)]$Summary)

    $props = @($Summary.PSObject.Properties.Name)
    if ($props -contains "source_type" -and $props -contains "cycles") {
        return "handoff"
    }
    if ($props -contains "cycle_count" -and $props -contains "cycles") {
        return "suite"
    }
    if ($props -contains "project_id" -and $props -contains "mode") {
        return "cycle"
    }
    return "unknown"
}

function Resolve-CycleViews {
    param(
        [Parameter(Mandatory = $true)]$Summary,
        [Parameter(Mandatory = $true)][string]$SummaryType
    )

    $views = New-Object System.Collections.Generic.List[object]
    if ($SummaryType -eq "cycle") {
        $statusSummaryPath = Resolve-OperatorStatusSummaryPath -Source $Summary
        $statusSummary = $null
        if ($statusSummaryPath -and (Test-Path $statusSummaryPath)) {
            $statusSummary = Read-OperatorJsonFile -Path $statusSummaryPath
        }
        $views.Add((
            New-CycleGateView `
                -Source $Summary `
                -SummaryPathValue $SummaryPath `
                -StatusSummaryPathValue $statusSummaryPath `
                -StatusSummary $statusSummary
        )) | Out-Null
        return $views
    }

    foreach ($cycle in @($Summary.cycles)) {
        $resolved = $cycle
        $resolvedSummaryPath = ""
        $statusSummaryPath = Resolve-OperatorStatusSummaryPath -Source $cycle
        $statusSummary = $null
        $summaryPathCandidate = [string]$cycle.summary_path
        if (-not [string]::IsNullOrWhiteSpace($summaryPathCandidate) -and (Test-Path $summaryPathCandidate)) {
            $resolved = Read-OperatorJsonFile -Path $summaryPathCandidate
            $resolvedSummaryPath = $summaryPathCandidate
            $resolvedStatusSummaryPath = Resolve-OperatorStatusSummaryPath -Source $resolved
            if ($resolvedStatusSummaryPath) {
                $statusSummaryPath = $resolvedStatusSummaryPath
            }
        }
        if ($statusSummaryPath -and (Test-Path $statusSummaryPath)) {
            $statusSummary = Read-OperatorJsonFile -Path $statusSummaryPath
        }
        $views.Add((
            New-CycleGateView `
                -Source $resolved `
                -SummaryPathValue $resolvedSummaryPath `
                -StatusSummaryPathValue $statusSummaryPath `
                -StatusSummary $statusSummary
        )) | Out-Null
    }
    return $views
}

$summary = Read-OperatorJsonFile -Path $SummaryPath
$summaryType = Resolve-SummaryType -Summary $summary
if ($summaryType -eq "unknown") {
    Write-Error (
        "Unsupported summary shape at {0}. Expected cycle summary, suite summary, or handoff envelope." -f
        $SummaryPath
    )
    exit 1
}

$cycleViews = Resolve-CycleViews -Summary $summary -SummaryType $summaryType
if ($cycleViews.Count -eq 0) {
    Write-Error ("No cycles found in summary: {0}" -f $SummaryPath)
    exit 1
}

$totalStageRuns = 0
$totalStageFailures = 0
$totalStageFallbacks = 0
$totalLlmTransportFallbacks = 0
$totalLegacyFallbackNormalizations = 0
$telemetrySources = New-Object System.Collections.Generic.HashSet[string]
foreach ($cycle in $cycleViews) {
    if ($null -ne $cycle.stage_runs) { $totalStageRuns += [int]$cycle.stage_runs }
    if ($null -ne $cycle.stage_failures) { $totalStageFailures += [int]$cycle.stage_failures }
    if ($null -ne $cycle.stage_fallbacks) { $totalStageFallbacks += [int]$cycle.stage_fallbacks }
    if ($null -ne $cycle.stage_llm_transport_fallbacks) { $totalLlmTransportFallbacks += [int]$cycle.stage_llm_transport_fallbacks }
    if ($null -ne $cycle.stage_legacy_fallback_normalizations) {
        $totalLegacyFallbackNormalizations += [int]$cycle.stage_legacy_fallback_normalizations
    }
    $telemetrySource = [string]$cycle.stage_telemetry_source
    if (-not [string]::IsNullOrWhiteSpace($telemetrySource)) {
        $telemetrySources.Add($telemetrySource) | Out-Null
    }
}

if (($totalStageRuns -eq 0) -and ($summary.PSObject.Properties.Name -contains "total_stage_runs")) {
    $summaryRuns = Convert-ToNullableInt -Value $summary.total_stage_runs
    if ($null -ne $summaryRuns) { $totalStageRuns = $summaryRuns }
}
if (($totalStageFailures -eq 0) -and ($summary.PSObject.Properties.Name -contains "total_stage_failures")) {
    $summaryFailures = Convert-ToNullableInt -Value $summary.total_stage_failures
    if ($null -ne $summaryFailures) { $totalStageFailures = $summaryFailures }
}
if (($totalStageFallbacks -eq 0) -and ($summary.PSObject.Properties.Name -contains "total_stage_fallbacks")) {
    $summaryFallbacks = Convert-ToNullableInt -Value $summary.total_stage_fallbacks
    if ($null -ne $summaryFallbacks) { $totalStageFallbacks = $summaryFallbacks }
}
if (($totalLlmTransportFallbacks -eq 0) -and ($summary.PSObject.Properties.Name -contains "total_llm_transport_fallbacks")) {
    $summaryLlmFallbacks = Convert-ToNullableInt -Value $summary.total_llm_transport_fallbacks
    if ($null -ne $summaryLlmFallbacks) { $totalLlmTransportFallbacks = $summaryLlmFallbacks }
}
if (($totalLegacyFallbackNormalizations -eq 0) -and ($summary.PSObject.Properties.Name -contains "total_stage_legacy_fallback_normalizations")) {
    $summaryLegacyFallbackNormalizations = Convert-ToNullableInt -Value $summary.total_stage_legacy_fallback_normalizations
    if ($null -ne $summaryLegacyFallbackNormalizations) {
        $totalLegacyFallbackNormalizations = $summaryLegacyFallbackNormalizations
    }
}

$violations = New-Object System.Collections.Generic.List[string]
$policyViolations = New-Object System.Collections.Generic.List[string]
$denyReasons = New-Object System.Collections.Generic.List[string]
if ($RequireAllCompleted) {
    foreach ($cycle in $cycleViews) {
        if ([string]$cycle.final_status -ne "completed") {
            $violations.Add(
                ("cycle not completed: mode={0} project_id={1} final_status={2}" -f
                    $cycle.mode,
                    $cycle.project_id,
                    $cycle.final_status)
            ) | Out-Null
        }
    }
}

if ($RequireAuditAssertions) {
    foreach ($cycle in $cycleViews) {
        if ($cycle.audit_assert_passed -ne $true) {
            $violations.Add(
                ("audit assertions not passed: mode={0} project_id={1}" -f
                    $cycle.mode,
                    $cycle.project_id)
            ) | Out-Null
        }
    }
}

if ($RequireStageTelemetry) {
    foreach ($cycle in $cycleViews) {
        if ($cycle.stage_telemetry_present -ne $true) {
            $violations.Add(
                ("stage telemetry missing: mode={0} project_id={1}" -f
                    $cycle.mode,
                    $cycle.project_id)
            ) | Out-Null
        }
    }
}

if (
    $RequirePolicyAssertions `
        -or $RequireAuthEvidence `
        -or $EnforceModelAllowlist `
        -or $FailOnBackendOverrideMismatch `
        -or $Breakglass `
        -or -not [string]::IsNullOrWhiteSpace($PolicyMode) `
        -or -not [string]::IsNullOrWhiteSpace($AuthPolicyMode) `
        -or -not [string]::IsNullOrWhiteSpace($ExpectedAuthRoles)
) {
    foreach ($cycle in $cycleViews) {
        $auditAssertPath = [string]$cycle.audit_assert_path
        if ([string]::IsNullOrWhiteSpace($auditAssertPath)) {
            $policyViolations.Add(
                ("policy assertion evidence missing: mode={0} project_id={1}" -f
                    $cycle.mode,
                    $cycle.project_id)
            ) | Out-Null
            continue
        }
        if (-not (Test-Path $auditAssertPath)) {
            $policyViolations.Add(
                ("policy assertion file missing: mode={0} project_id={1} path={2}" -f
                    $cycle.mode,
                    $cycle.project_id,
                    $auditAssertPath)
            ) | Out-Null
            continue
        }

        $auditAssert = Read-OperatorJsonFile -Path $auditAssertPath
        if ([bool]$auditAssert.passed -ne $true) {
            $policyViolations.Add(
                ("policy assertion failed: mode={0} project_id={1}" -f
                    $cycle.mode,
                    $cycle.project_id)
            ) | Out-Null
            foreach ($errorText in @($auditAssert.errors)) {
                $normalizedError = Convert-ToNullableString -Value $errorText
                if ($normalizedError) {
                    if (-not $denyReasons.Contains($normalizedError)) {
                        $denyReasons.Add($normalizedError) | Out-Null
                    }
                    $policyViolations.Add(
                        ("policy deny reason: mode={0} project_id={1} reason={2}" -f
                            $cycle.mode,
                            $cycle.project_id,
                            $normalizedError)
                    ) | Out-Null
                }
            }
        }

        if (-not [string]::IsNullOrWhiteSpace($PolicyMode)) {
            if ([string]$auditAssert.policy_mode -ne $PolicyMode) {
                $policyViolations.Add(
                    ("policy mode mismatch: mode={0} project_id={1} expected={2} actual={3}" -f
                        $cycle.mode,
                        $cycle.project_id,
                        $PolicyMode,
                        [string]$auditAssert.policy_mode)
                ) | Out-Null
            }
        }

        if (-not [string]::IsNullOrWhiteSpace($AuthPolicyMode)) {
            if ([string]$auditAssert.auth_policy_mode -ne $AuthPolicyMode) {
                $policyViolations.Add(
                    ("auth policy mode mismatch: mode={0} project_id={1} expected={2} actual={3}" -f
                        $cycle.mode,
                        $cycle.project_id,
                        $AuthPolicyMode,
                        [string]$auditAssert.auth_policy_mode)
                ) | Out-Null
            }
        }

        if ($RequireAuthEvidence) {
            if ([bool]$auditAssert.auth_evidence_present -ne $true) {
                $policyViolations.Add(
                    ("auth evidence missing: mode={0} project_id={1}" -f
                        $cycle.mode,
                        $cycle.project_id)
                ) | Out-Null
            }
            $requiredRoles = Resolve-ExpectedAuthRoles `
                -InlineRaw $ExpectedAuthRoles `
                -FallbackValues $auditAssert.expected_auth_roles
            if ($requiredRoles.Count -eq 0) {
                $requiredRoles = @("approver")
            }
            foreach ($requiredRole in $requiredRoles) {
                $roleEvidence = $null
                if ($null -ne $auditAssert.auth_evidence -and $null -ne $auditAssert.auth_evidence.roles) {
                    $roleEvidence = $auditAssert.auth_evidence.roles.$requiredRole
                }
                if ($null -eq $roleEvidence -or [bool]$roleEvidence.evidence_present -ne $true) {
                    $policyViolations.Add(
                        ("auth role evidence missing: mode={0} project_id={1} role={2}" -f
                            $cycle.mode,
                            $cycle.project_id,
                            $requiredRole)
                    ) | Out-Null
                    continue
                }
                $roleSources = @($roleEvidence.auth_sources)
                $roleModes = @($roleEvidence.auth_modes)
                if ($roleSources.Count -eq 0) {
                    $policyViolations.Add(
                        ("auth source missing: mode={0} project_id={1} role={2}" -f
                            $cycle.mode,
                            $cycle.project_id,
                            $requiredRole)
                    ) | Out-Null
                }
                if ($roleModes.Count -eq 0) {
                    $policyViolations.Add(
                        ("auth mode missing: mode={0} project_id={1} role={2}" -f
                            $cycle.mode,
                            $cycle.project_id,
                            $requiredRole)
                    ) | Out-Null
                }
            }
        }

        if ($Breakglass) {
            if ([bool]$auditAssert.breakglass_used -ne $true) {
                $policyViolations.Add(
                    ("breakglass evidence missing: mode={0} project_id={1}" -f
                        $cycle.mode,
                        $cycle.project_id)
                ) | Out-Null
            }
            $resolvedBreakglassReason = Convert-ToNullableString -Value $auditAssert.breakglass_reason
            $resolvedBreakglassActor = Convert-ToNullableString -Value $auditAssert.breakglass_actor
            if ($null -eq $resolvedBreakglassReason) {
                $policyViolations.Add(
                    ("breakglass reason missing: mode={0} project_id={1}" -f
                        $cycle.mode,
                        $cycle.project_id)
                ) | Out-Null
            }
            if ($null -eq $resolvedBreakglassActor) {
                $policyViolations.Add(
                    ("breakglass actor missing: mode={0} project_id={1}" -f
                        $cycle.mode,
                        $cycle.project_id)
                ) | Out-Null
            }
            $requiredBreakglassReason = Convert-ToNullableString -Value $BreakglassReason
            if ($requiredBreakglassReason -and $resolvedBreakglassReason -ne $requiredBreakglassReason) {
                $policyViolations.Add(
                    ("breakglass reason mismatch: mode={0} project_id={1} expected={2} actual={3}" -f
                        $cycle.mode,
                        $cycle.project_id,
                        $requiredBreakglassReason,
                        $resolvedBreakglassReason)
                ) | Out-Null
            }
            $requiredBreakglassActor = Convert-ToNullableString -Value $BreakglassActor
            if ($requiredBreakglassActor -and $resolvedBreakglassActor -ne $requiredBreakglassActor) {
                $policyViolations.Add(
                    ("breakglass actor mismatch: mode={0} project_id={1} expected={2} actual={3}" -f
                        $cycle.mode,
                        $cycle.project_id,
                        $requiredBreakglassActor,
                        $resolvedBreakglassActor)
                ) | Out-Null
            }
        }

        if ($EnforceModelAllowlist -and [bool]$auditAssert.enforce_model_allowlist -ne $true) {
            $policyViolations.Add(
                ("allowlist enforcement missing: mode={0} project_id={1}" -f
                    $cycle.mode,
                    $cycle.project_id)
            ) | Out-Null
        }

        if (
            $FailOnBackendOverrideMismatch `
                -and [bool]$auditAssert.fail_on_backend_override_mismatch -ne $true
        ) {
            $policyViolations.Add(
                ("override mismatch deny missing: mode={0} project_id={1}" -f
                    $cycle.mode,
                    $cycle.project_id)
            ) | Out-Null
        }
    }
}

if ($MaxStageFailures -ge 0 -and $totalStageFailures -gt $MaxStageFailures) {
    $violations.Add(
        ("stage failures exceeded limit: total={0} limit={1}" -f
            $totalStageFailures,
            $MaxStageFailures)
    ) | Out-Null
}
if ($MaxStageFallbacks -ge 0 -and $totalStageFallbacks -gt $MaxStageFallbacks) {
    $violations.Add(
        ("stage fallbacks exceeded limit: total={0} limit={1}" -f
            $totalStageFallbacks,
            $MaxStageFallbacks)
    ) | Out-Null
}
if ($MaxLlmTransportFallbacks -ge 0 -and $totalLlmTransportFallbacks -gt $MaxLlmTransportFallbacks) {
    $violations.Add(
        ("llm transport fallbacks exceeded limit: total={0} limit={1}" -f
            $totalLlmTransportFallbacks,
            $MaxLlmTransportFallbacks)
    ) | Out-Null
}

foreach ($policyViolation in $policyViolations) {
    $violations.Add($policyViolation) | Out-Null
    if (-not $denyReasons.Contains($policyViolation)) {
        $denyReasons.Add($policyViolation) | Out-Null
    }
}

$passed = ($violations.Count -eq 0)
$resolvedExpectedAuthRolesForReport = Resolve-ExpectedAuthRoles `
    -InlineRaw $ExpectedAuthRoles `
    -FallbackValues @()
if ($RequireAuthEvidence -and $resolvedExpectedAuthRolesForReport.Count -eq 0) {
    $resolvedExpectedAuthRolesForReport = @("approver")
}
$stageGateBreakglassActor = ""
if (
    $Breakglass -or -not [string]::IsNullOrWhiteSpace(([string]$BreakglassActor).Trim())
) {
    if ([string]::IsNullOrWhiteSpace(([string]$BreakglassActor).Trim())) {
        $stageGateBreakglassActor = [Environment]::UserName
    } else {
        $stageGateBreakglassActor = ([string]$BreakglassActor).Trim()
    }
}
$report = [ordered]@{
    evaluated_at_utc = [DateTime]::UtcNow.ToString("o")
    summary_path = $SummaryPath
    summary_type = $summaryType
    require_all_completed = $RequireAllCompleted
    require_audit_assertions = $RequireAuditAssertions
    require_stage_telemetry = $RequireStageTelemetry
    require_policy_assertions = $RequirePolicyAssertions
    require_auth_evidence = $RequireAuthEvidence
    expected_auth_roles = @($resolvedExpectedAuthRolesForReport)
    auth_policy_mode = $AuthPolicyMode
    breakglass_used = [bool]$Breakglass
    breakglass_reason = ([string]$BreakglassReason).Trim()
    breakglass_actor = $stageGateBreakglassActor
    policy_mode = $PolicyMode
    enforce_model_allowlist = [bool]$EnforceModelAllowlist
    fail_on_backend_override_mismatch = [bool]$FailOnBackendOverrideMismatch
    max_stage_failures = $MaxStageFailures
    max_stage_fallbacks = $MaxStageFallbacks
    max_llm_transport_fallbacks = $MaxLlmTransportFallbacks
    passed = $passed
    cycle_count = $cycleViews.Count
    totals = [ordered]@{
        stage_runs = $totalStageRuns
        stage_failures = $totalStageFailures
        stage_fallbacks = $totalStageFallbacks
        llm_transport_fallbacks = $totalLlmTransportFallbacks
        legacy_fallback_normalizations = $totalLegacyFallbackNormalizations
        stage_telemetry_sources = @(Convert-OperatorSetToArray -Set $telemetrySources | Sort-Object)
    }
    cycles = @($cycleViews)
    deny_reason_count = $denyReasons.Count
    deny_reasons = @($denyReasons)
    violation_count = $violations.Count
    violations = @($violations)
}

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $OutPath = Join-Path $repoRoot ("logs\operator-gates\stage-gate-{0}.json" -f $stamp)
}
Save-OperatorJson -Payload $report -OutPath $OutPath

Write-Host "[operator-stage-gate]"
Write-Host ("  summary_type : {0}" -f $summaryType)
Write-Host ("  cycle_count  : {0}" -f $cycleViews.Count)
Write-Host ("  stage_runs   : {0}" -f $totalStageRuns)
Write-Host ("  failures     : {0}" -f $totalStageFailures)
Write-Host ("  fallbacks    : {0}" -f $totalStageFallbacks)
Write-Host ("  llm_fb       : {0}" -f $totalLlmTransportFallbacks)
if ($RequirePolicyAssertions -or $EnforceModelAllowlist -or $FailOnBackendOverrideMismatch) {
    Write-Host ("  policy_mode  : {0}" -f $(if ([string]::IsNullOrWhiteSpace($PolicyMode)) { "unset" } else { $PolicyMode }))
    Write-Host ("  allowlist    : {0}" -f [bool]$EnforceModelAllowlist)
    Write-Host ("  override_mis : {0}" -f [bool]$FailOnBackendOverrideMismatch)
}
if ($RequireAuthEvidence -or -not [string]::IsNullOrWhiteSpace($AuthPolicyMode) -or $Breakglass) {
    Write-Host ("  auth_policy  : {0}" -f $(if ([string]::IsNullOrWhiteSpace($AuthPolicyMode)) { "unset" } else { $AuthPolicyMode }))
    Write-Host ("  auth_require : {0}" -f [bool]$RequireAuthEvidence)
    Write-Host ("  breakglass   : {0}" -f [bool]$Breakglass)
}
if ($totalLegacyFallbackNormalizations -gt 0) {
    Write-Host ("  legacy_fix   : {0}" -f $totalLegacyFallbackNormalizations)
}
Write-Host ("  out_path     : {0}" -f $OutPath)
if ($passed) {
    Write-Host "[done] operator-stage-gate passed"
    exit 0
}

Write-Host "  [violations]"
foreach ($v in $violations) {
    Write-Host ("    - {0}" -f $v)
}
Write-Error "operator-stage-gate failed"
exit 1
