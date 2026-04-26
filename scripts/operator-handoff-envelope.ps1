param(
    [string]$CycleSummaryPath = "",
    [string]$SuiteSummaryPath = "",
    [string]$BundleManifestPath = "",
    [string]$OutPath = "",
    [string]$MarkdownOutPath = "",
    [string]$VerifiedBy = "Codex unattended run"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. (Join-Path $PSScriptRoot "operator-common.ps1")

if (
    [string]::IsNullOrWhiteSpace($CycleSummaryPath) `
        -and [string]::IsNullOrWhiteSpace($SuiteSummaryPath) `
        -and [string]::IsNullOrWhiteSpace($BundleManifestPath)
) {
    Write-Error "Either -CycleSummaryPath, -SuiteSummaryPath, or -BundleManifestPath is required."
    exit 1
}

if (
    @(
        @($CycleSummaryPath, $SuiteSummaryPath, $BundleManifestPath) |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    ).Count -gt 1
) {
    Write-Error "Specify only one of -CycleSummaryPath, -SuiteSummaryPath, or -BundleManifestPath."
    exit 1
}

function Resolve-OptionalJson {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $null
    }
    if (-not (Test-Path $Path)) {
        return $null
    }
    try {
        return Read-OperatorJsonFile -Path $Path
    } catch {
        return $null
    }
}

function Convert-ToObjectArray {
    param([object]$Value)

    if ($null -eq $Value) {
        return @()
    }
    if ($Value -is [string]) {
        return @($Value)
    }
    if ($Value -is [System.Collections.IDictionary]) {
        return @($Value)
    }

    $items = New-Object System.Collections.Generic.List[object]
    if ($Value -is [System.Collections.IEnumerable]) {
        foreach ($entry in $Value) {
            $items.Add($entry) | Out-Null
        }
    } else {
        $items.Add($Value) | Out-Null
    }
    if ($items.Count -eq 0) {
        return @()
    }
    return @($items.ToArray())
}

function New-CycleEnvelope {
    param(
        [Parameter(Mandatory = $true)]$CycleSummary,
        [string]$SummaryPath = ""
    )

    $files = $CycleSummary.files
    $audit = Resolve-OptionalJson -Path ([string]$files.audit)
    $stageReport = Resolve-OptionalJson -Path ([string]$files.stage_report)
    $auditAssert = Resolve-OptionalJson -Path ([string]$files.audit_assert)
    $statusSummaryPath = [string]$files.status_summary
    if ([string]::IsNullOrWhiteSpace($statusSummaryPath)) {
        $statusSummaryPath = [string]$CycleSummary.status_summary_path
    }
    $statusSummary = Resolve-OptionalJson -Path $statusSummaryPath

    $departmentsCovered = @()
    $approvals = @()
    $eventsCount = $null
    if ($audit) {
        $eventsCount = @($audit.events).Count
        $approvals = Convert-ToObjectArray -Value $audit.approvals
        $departmentsCovered = Convert-ToObjectArray -Value $audit.department_stage_totals.departments_covered
    }
    if (($departmentsCovered.Count -eq 0) -and $statusSummary -and $statusSummary.stage_totals) {
        $departmentsCovered = Convert-ToObjectArray -Value $statusSummary.stage_totals.departments_covered
    }
    if (($departmentsCovered.Count -eq 0) -and $stageReport -and $stageReport.stage_totals) {
        $departmentsCovered = Convert-ToObjectArray -Value $stageReport.stage_totals.departments_covered
    }
    if (($approvals.Count -eq 0) -and $statusSummary -and $statusSummary.approval_statuses) {
        $approvals = @($statusSummary.approval_statuses | ForEach-Object {
            [pscustomobject]@{
                action_type = [string]$_.action
                status = [string]$_.status
            }
        })
    }
    if ($null -eq $eventsCount -and $statusSummary -and $null -ne $statusSummary.events) {
        $eventsCount = Convert-OperatorToInt -Value $statusSummary.events -Default 0
    }

    $stageRuns = Convert-OperatorToInt -Value $CycleSummary.stage_runs -Default 0
    $stageFailures = Convert-OperatorToInt -Value $CycleSummary.stage_failures -Default 0
    $stageFallbacks = Convert-OperatorToInt -Value $CycleSummary.stage_fallbacks -Default 0
    $stageLlmTransportFallbacks = Convert-OperatorToInt -Value $CycleSummary.stage_llm_transport_fallbacks -Default 0
    if ($stageReport) {
        $stageRuns = [int]$stageReport.stage_totals.total_stage_executions
        $stageFailures = [int]$stageReport.stage_totals.total_failures
        $stageFallbacks = [int]$stageReport.stage_totals.total_fallbacks
        $stageLlmTransportFallbacks = [int]$stageReport.stage_totals.total_llm_transport_fallbacks
    } elseif ($statusSummary -and $statusSummary.stage_totals) {
        $stageRuns = [int]$statusSummary.stage_totals.total_stage_executions
        $stageFailures = [int]$statusSummary.stage_totals.total_failures
        $stageFallbacks = [int]$statusSummary.stage_totals.total_fallbacks
        $stageLlmTransportFallbacks = [int]$statusSummary.stage_totals.total_llm_transport_fallbacks
    }

    $stageTelemetrySource = [string]$CycleSummary.stage_telemetry_source
    if ([string]::IsNullOrWhiteSpace($stageTelemetrySource) -and $statusSummary) {
        $stageTelemetrySource = [string]$statusSummary.telemetry_source
    }

    $stageTelemetryPresent = [bool]$CycleSummary.stage_telemetry_present
    if (($stageTelemetryPresent -ne $true) -and $statusSummary) {
        $stageTelemetryPresent = [bool]$statusSummary.telemetry_present
    }

    $stageTelemetryNotes = @($CycleSummary.stage_telemetry_notes)
    if (($stageTelemetryNotes.Count -eq 0) -and $statusSummary) {
        $stageTelemetryNotes = @($statusSummary.telemetry_notes)
    }

    $stageLegacyFallbackNormalizations = Convert-OperatorToInt `
        -Value $CycleSummary.stage_legacy_fallback_normalizations `
        -Default 0
    if (($stageLegacyFallbackNormalizations -eq 0) -and $statusSummary) {
        $stageLegacyFallbackNormalizations = Convert-OperatorToInt `
            -Value $statusSummary.telemetry_legacy_fallback_normalizations `
            -Default 0
    }

    $projectId = [string]$CycleSummary.project_id
    if ([string]::IsNullOrWhiteSpace($projectId) -and $statusSummary) {
        $projectId = [string]$statusSummary.project_id
    }
    $finalStatus = [string]$CycleSummary.final_status
    if ([string]::IsNullOrWhiteSpace($finalStatus) -and $statusSummary) {
        $finalStatus = [string]$statusSummary.status
    }

    return [pscustomobject]@{
        mode = [string]$CycleSummary.mode
        project_id = $projectId
        final_status = $finalStatus
        run_status = [string]$CycleSummary.run_status
        audit_assert_passed = [bool]$CycleSummary.audit_assert_passed
        audit_assert_error_count = if ($auditAssert) { [int]$auditAssert.error_count } else { $null }
        stage_runs = $stageRuns
        stage_failures = $stageFailures
        stage_fallbacks = $stageFallbacks
        stage_llm_transport_fallbacks = $stageLlmTransportFallbacks
        stage_legacy_fallback_normalizations = $stageLegacyFallbackNormalizations
        stage_telemetry_source = $stageTelemetrySource
        stage_telemetry_present = $stageTelemetryPresent
        stage_telemetry_notes = @($stageTelemetryNotes)
        departments_covered = $departmentsCovered
        approvals = @($approvals | ForEach-Object {
            [pscustomobject]@{
                action = [string]$_.action_type
                status = [string]$_.status
            }
        })
        events_count = $eventsCount
        summary_path = $SummaryPath
        status_summary_path = $statusSummaryPath
        files = $files
    }
}

function Save-MarkdownEnvelope {
    param(
        [object]$Envelope,
        [string]$Path
    )

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return
    }

    $parent = Split-Path -Parent $Path
    if (-not [string]::IsNullOrWhiteSpace($parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }

    $lines = New-Object System.Collections.Generic.List[string]
    $null = $lines.Add("# Operator Handoff Envelope")
    $null = $lines.Add("")
    $null = $lines.Add(("- generated_at_utc: {0}" -f $Envelope.generated_at_utc))
    $null = $lines.Add(("- source_type: {0}" -f $Envelope.source_type))
    $null = $lines.Add(("- verified_by: {0}" -f $Envelope.verified_by))
    $null = $lines.Add(("- all_completed: {0}" -f $Envelope.all_completed))
    $null = $lines.Add(("- all_audit_assertions_passed: {0}" -f $Envelope.all_audit_assertions_passed))
    $null = $lines.Add(("- total_stage_runs: {0}" -f $Envelope.total_stage_runs))
    $null = $lines.Add(("- total_stage_failures: {0}" -f $Envelope.total_stage_failures))
    $null = $lines.Add(("- total_stage_fallbacks: {0}" -f $Envelope.total_stage_fallbacks))
    $null = $lines.Add(("- total_llm_transport_fallbacks: {0}" -f $Envelope.total_llm_transport_fallbacks))
    if ($Envelope.total_stage_legacy_fallback_normalizations -gt 0) {
        $null = $lines.Add(("- total_stage_legacy_fallback_normalizations: {0}" -f $Envelope.total_stage_legacy_fallback_normalizations))
    }
    if ($Envelope.stage_telemetry_sources -and $Envelope.stage_telemetry_sources.Count -gt 0) {
        $null = $lines.Add(("- stage_telemetry_sources: {0}" -f ($Envelope.stage_telemetry_sources -join ", ")))
    }
    $null = $lines.Add("")
    $null = $lines.Add("## Cycles")
    $null = $lines.Add("")
    foreach ($cycle in @($Envelope.cycles)) {
        $null = $lines.Add(("- mode={0} project_id={1} final_status={2} stage_runs={3} stage_failures={4} stage_fallbacks={5} llm_transport_fallbacks={6} legacy_fallback_normalizations={7} telemetry={8} status_summary={9}" -f
            $cycle.mode,
            $cycle.project_id,
            $cycle.final_status,
            $cycle.stage_runs,
            $cycle.stage_failures,
            $cycle.stage_fallbacks,
            $cycle.stage_llm_transport_fallbacks,
            $cycle.stage_legacy_fallback_normalizations,
            $cycle.stage_telemetry_source,
            $cycle.status_summary_path))
    }
    $null = $lines.Add("")
    $null = $lines.Add("## Risks")
    $null = $lines.Add("")
    foreach ($risk in @($Envelope.risks)) {
        $null = $lines.Add(("- {0}" -f $risk))
    }
    $null = $lines.Add("")
    $null = $lines.Add("## Next Actions")
    $null = $lines.Add("")
    foreach ($action in @($Envelope.next_actions)) {
        $null = $lines.Add(("- {0}" -f $action))
    }

    $text = $lines -join "`r`n"
    Set-Content -Path $Path -Value $text -Encoding utf8
}

$cycleSummaries = New-Object System.Collections.Generic.List[object]

if (-not [string]::IsNullOrWhiteSpace($BundleManifestPath)) {
    $bundleManifest = Read-OperatorBundleManifest -Path $BundleManifestPath
    $bundleType = [string](Get-OperatorObjectPropertyValue -Object $bundleManifest -Name "bundle_type")
    if ($bundleType -eq "cycle") {
        $CycleSummaryPath = Resolve-OperatorBundlePrimarySummaryPath -Manifest $bundleManifest -RepoRoot $repoRoot
    } elseif ($bundleType -eq "suite") {
        $SuiteSummaryPath = Resolve-OperatorBundlePrimarySummaryPath -Manifest $bundleManifest -RepoRoot $repoRoot
    } else {
        Write-Error ("Unsupported bundle manifest type for handoff: {0}" -f $bundleType)
        exit 1
    }
}

if (-not [string]::IsNullOrWhiteSpace($CycleSummaryPath)) {
    $cycleSummary = Read-OperatorJsonFile -Path $CycleSummaryPath
    $cycleEnvelope = New-CycleEnvelope -CycleSummary $cycleSummary -SummaryPath $CycleSummaryPath
    $null = $cycleSummaries.Add($cycleEnvelope)
    $sourceType = "cycle"
} else {
    $suiteSummary = Read-OperatorJsonFile -Path $SuiteSummaryPath
    $sourceType = "suite"
    foreach ($cycle in @($suiteSummary.cycles)) {
        $path = [string]$cycle.summary_path
        if ([string]::IsNullOrWhiteSpace($path) -or -not (Test-Path $path)) {
            continue
        }
        $cycleSummary = Read-OperatorJsonFile -Path $path
        $cycleEnvelope = New-CycleEnvelope -CycleSummary $cycleSummary -SummaryPath $path
        $null = $cycleSummaries.Add($cycleEnvelope)
    }
}

if ($cycleSummaries.Count -eq 0) {
    Write-Error "No cycle summaries were resolved for handoff envelope."
    exit 1
}

$allCompleted = $true
$allAuditAssertPassed = $true
$totalStageRuns = 0
$totalStageFailures = 0
$totalStageFallbacks = 0
$totalLlmTransportFallbacks = 0
$totalLegacyFallbackNormalizations = 0
$projectIds = New-Object System.Collections.Generic.HashSet[string]
$deptSet = New-Object System.Collections.Generic.HashSet[string]
$telemetrySourceSet = New-Object System.Collections.Generic.HashSet[string]

foreach ($cycle in $cycleSummaries) {
    if ([string]$cycle.final_status -ne "completed") {
        $allCompleted = $false
    }
    if (-not [bool]$cycle.audit_assert_passed) {
        $allAuditAssertPassed = $false
    }
    if ($null -ne $cycle.stage_runs) { $totalStageRuns += [int]$cycle.stage_runs }
    if ($null -ne $cycle.stage_failures) { $totalStageFailures += [int]$cycle.stage_failures }
    if ($null -ne $cycle.stage_fallbacks) { $totalStageFallbacks += [int]$cycle.stage_fallbacks }
    if ($null -ne $cycle.stage_llm_transport_fallbacks) { $totalLlmTransportFallbacks += [int]$cycle.stage_llm_transport_fallbacks }
    if ($null -ne $cycle.stage_legacy_fallback_normalizations) {
        $totalLegacyFallbackNormalizations += [int]$cycle.stage_legacy_fallback_normalizations
    }
    if (-not [string]::IsNullOrWhiteSpace([string]$cycle.project_id)) {
        $projectIds.Add([string]$cycle.project_id) | Out-Null
    }
    foreach ($dept in @($cycle.departments_covered)) {
        if (-not [string]::IsNullOrWhiteSpace([string]$dept)) {
            $deptSet.Add([string]$dept) | Out-Null
        }
    }
    $telemetrySource = [string]$cycle.stage_telemetry_source
    if (-not [string]::IsNullOrWhiteSpace($telemetrySource)) {
        $telemetrySourceSet.Add($telemetrySource) | Out-Null
    }
}

$risks = New-Object System.Collections.Generic.List[string]
if (-not $allCompleted) {
    $risks.Add("One or more cycles are not completed.")
}
if (-not $allAuditAssertPassed) {
    $risks.Add("Audit assertions failed for one or more cycles.")
}
if ($totalStageFallbacks -gt 0) {
    $risks.Add(("Stage fallback observed ({0}); investigate provider/model JSON compliance if strict behavior is required." -f $totalStageFallbacks))
}
if ($totalLlmTransportFallbacks -gt 0) {
    $risks.Add(("LLM transport fallback observed ({0}); monitor gateway endpoint health and provider availability." -f $totalLlmTransportFallbacks))
}
if ($totalLegacyFallbackNormalizations -gt 0) {
    $risks.Add((
        "Legacy fallback-only stage events were normalized ({0}); current report is backward-compatible, " +
        "but restart on the current server build is recommended to emit native totals/summary telemetry." -f
        $totalLegacyFallbackNormalizations
    ))
}
if ($risks.Count -eq 0) {
    $risks.Add("No blocking risks detected in offline envelope checks.")
}

$nextActions = New-Object System.Collections.Generic.List[string]
$nextActions.Add('.\scripts\release-readiness.ps1 -AutoSeedFullFlow -Authorization "Bearer dev-approver-token"')
if (-not $allCompleted -or -not $allAuditAssertPassed) {
    $nextActions.Add("Re-run operator-full-cycle for failed mode and inspect audit-assert errors.")
}
if ($totalLegacyFallbackNormalizations -gt 0) {
    $nextActions.Add("Restart the current API build and re-run operator evidence to replace legacy event-derived telemetry with native totals.")
}
$nextActions.Add("If OpenClaw live validation is in scope, re-run .\\scripts\\openclaw-evidence-capture.ps1 after endpoint enablement.")

$envelope = [pscustomobject]@{
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    source_type = $sourceType
    verified_by = $VerifiedBy
    all_completed = $allCompleted
    all_audit_assertions_passed = $allAuditAssertPassed
    project_ids = Convert-ToObjectArray -Value $projectIds
    departments_covered = Convert-ToObjectArray -Value $deptSet
    stage_telemetry_sources = Convert-ToObjectArray -Value $telemetrySourceSet
    total_stage_runs = $totalStageRuns
    total_stage_failures = $totalStageFailures
    total_stage_fallbacks = $totalStageFallbacks
    total_llm_transport_fallbacks = $totalLlmTransportFallbacks
    total_stage_legacy_fallback_normalizations = $totalLegacyFallbackNormalizations
    cycles = Convert-ToObjectArray -Value $cycleSummaries
    risks = Convert-ToObjectArray -Value $risks
    next_actions = Convert-ToObjectArray -Value $nextActions
}

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $OutPath = Join-Path $repoRoot ("logs\operator-handoff\handoff-envelope-{0}.json" -f $stamp)
}
Save-OperatorJson -Payload $envelope -OutPath $OutPath

if ([string]::IsNullOrWhiteSpace($MarkdownOutPath)) {
    $baseName = [System.IO.Path]::GetFileNameWithoutExtension($OutPath)
    $MarkdownOutPath = Join-Path ([System.IO.Path]::GetDirectoryName($OutPath)) ($baseName + ".md")
}
Save-MarkdownEnvelope -Envelope $envelope -Path $MarkdownOutPath

Write-Host "[operator-handoff-envelope]"
Write-Host ("  source_type  : {0}" -f $sourceType)
Write-Host ("  cycles       : {0}" -f $cycleSummaries.Count)
Write-Host ("  all_completed: {0}" -f $allCompleted)
Write-Host ("  audit_assert : {0}" -f $allAuditAssertPassed)
Write-Host ("  llm_fb       : {0}" -f $totalLlmTransportFallbacks)
Write-Host ("  json_path    : {0}" -f $OutPath)
Write-Host ("  markdown_path: {0}" -f $MarkdownOutPath)
Write-Host "[done] operator-handoff-envelope completed"
