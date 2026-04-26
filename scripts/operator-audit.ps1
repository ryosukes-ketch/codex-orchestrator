param(
    [string]$ProjectId = "",
    [string]$ApiBaseUrl = "http://127.0.0.1:8000",
    [string]$AuditJsonPath = "",
    [string]$BundleManifestPath = "",
    [string]$OutPath = "",
    [switch]$Full,
    [int]$TimeoutSec = 0
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. (Join-Path $PSScriptRoot "operator-common.ps1")
$effectiveTimeoutSec = Resolve-OperatorTimeoutSec -TimeoutSec $TimeoutSec

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
    Write-Host ("[operator-audit] LOAD {0}" -f $AuditJsonPath)
    $audit = Read-OperatorJsonFile -Path $AuditJsonPath
} else {
    $url = $ApiBaseUrl.TrimEnd("/") + "/projects/" + $ProjectId + "/audit"
    Write-Host "[operator-audit] GET $url"

    $response = Invoke-OperatorApi `
        -Method "GET" `
        -ApiBaseUrl $ApiBaseUrl `
        -Path ("/projects/" + $ProjectId + "/audit") `
        -ExpectedStatusCodes @(200) `
        -TimeoutSec $effectiveTimeoutSec

    if ($null -eq $response.BodyJson) {
        Write-Error ("Audit request succeeded but response body is not valid JSON: {0}" -f $response.BodyText)
        exit 1
    }
    $audit = $response.BodyJson
}

if ([string]$audit.project_id -ne $ProjectId) {
    Write-Error ("Project ID mismatch: expected={0} actual={1}" -f $ProjectId, [string]$audit.project_id)
    exit 1
}
$telemetry = Get-OperatorStageTelemetry -Audit $audit -AllowDerivedFromEvents
$stageSummary = @($telemetry.stage_summary)
$stageTotals = $telemetry.stage_totals
$telemetrySource = [string]$telemetry.telemetry_source
$telemetryNotes = @($telemetry.notes)
$legacyFallbackNormalizations = Convert-OperatorToInt `
    -Value $telemetry.legacy_fallback_normalizations `
    -Default 0

Write-Host ""
Write-Host "========================================="
Write-Host "  PROJECT AUDIT"
Write-Host "========================================="
Write-Host "  project_id : $($audit.project_id)"
Write-Host "  status     : $($audit.status)"
Write-Host ""

if ($telemetry.telemetry_present) {
    $totals = $stageTotals
    $llmFallbacks = if ($null -ne $totals.total_llm_transport_fallbacks) { $totals.total_llm_transport_fallbacks } else { 0 }
    Write-Host "  [Department Stage Totals]"
    Write-Host ("    runs={0} success={1} failure={2} fallback={3} llm_fb={4}" -f $totals.total_stage_executions, $totals.total_successes, $totals.total_failures, $totals.total_fallbacks, $llmFallbacks)
    if ($legacyFallbackNormalizations -gt 0) {
        Write-Host ("    legacy_fix={0}" -f $legacyFallbackNormalizations)
    }
    Write-Host ("    source: {0}" -f $telemetrySource)
    if ($totals.departments_covered -and $totals.departments_covered.Count -gt 0) {
        Write-Host ("    departments: {0}" -f ($totals.departments_covered -join ", "))
    }
    if ($totals.llm_endpoints_observed -and $totals.llm_endpoints_observed.Count -gt 0) {
        Write-Host ("    endpoints: {0}" -f ($totals.llm_endpoints_observed -join ", "))
    }
    Write-Host ""
}
foreach ($note in $telemetryNotes) {
    Write-Host ("  [note] {0}" -f $note)
}
if ($telemetryNotes.Count -gt 0) {
    Write-Host ""
}

if ($audit.checkpoints -and $audit.checkpoints.Count -gt 0) {
    Write-Host "  [Checkpoints]"
    foreach ($cp in $audit.checkpoints) {
        $approvedStr = if ($cp.approved) { "yes" } else { "no" }
        Write-Host ("    {0}: approved={1} approver={2}" -f $cp.name, $approvedStr, $cp.approver)
        if ($cp.note) { Write-Host ("      note: {0}" -f $cp.note) }
    }
    Write-Host ""
}

if ($audit.approvals -and $audit.approvals.Count -gt 0) {
    Write-Host "  [Approvals]"
    foreach ($ap in $audit.approvals) {
        Write-Host ("    action={0} status={1}" -f $ap.action_type, $ap.status)
        if ($ap.reason) { Write-Host ("      reason: {0}" -f $ap.reason) }
        if ($ap.decision_note) { Write-Host ("      note  : {0}" -f $ap.decision_note) }
    }
    Write-Host ""
}

if ($audit.reviews -and $audit.reviews.Count -gt 0) {
    Write-Host "  [Reviews]"
    foreach ($rv in $audit.reviews) {
        Write-Host ("    task={0} verdict={1}" -f $rv.task_id, $rv.verdict)
        if ($rv.findings -and $rv.findings.Count -gt 0) {
            foreach ($f in $rv.findings) { Write-Host ("      - {0}" -f $f) }
        }
    }
    Write-Host ""
}

if ($stageSummary -and $stageSummary.Count -gt 0) {
    Write-Host "  [Department Stage Summary]"
    foreach ($stage in $stageSummary) {
        Write-Host (
            "    {0}#{1} {2} : runs={3} success={4} failure={5} fallback={6}" -f
            $stage.department,
            $stage.sequence,
            $stage.stage_name,
            $stage.execution_count,
            $stage.success_count,
            $stage.failure_count,
            $stage.fallback_count
        )
        if ($stage.failure_reasons -and $stage.failure_reasons.Count -gt 0) {
            Write-Host ("      failure_reasons: {0}" -f ($stage.failure_reasons -join ", "))
        }
        if ($stage.effective_models -and $stage.effective_models.Count -gt 0) {
            Write-Host ("      models: {0}" -f ($stage.effective_models -join ", "))
        }
        if ($stage.llm_endpoints -and $stage.llm_endpoints.Count -gt 0) {
            Write-Host ("      endpoints: {0}" -f ($stage.llm_endpoints -join ", "))
        }
        if ($stage.llm_content_kinds -and $stage.llm_content_kinds.Count -gt 0) {
            Write-Host ("      content_kinds: {0}" -f ($stage.llm_content_kinds -join ", "))
        }
        if ($stage.llm_backend_overrides -and $stage.llm_backend_overrides.Count -gt 0) {
            Write-Host ("      backend_overrides: {0}" -f ($stage.llm_backend_overrides -join ", "))
        }
        if ($stage.llm_upstream_providers -and $stage.llm_upstream_providers.Count -gt 0) {
            Write-Host ("      upstream_providers: {0}" -f ($stage.llm_upstream_providers -join ", "))
        }
        if ($stage.llm_upstream_rejection_reasons -and $stage.llm_upstream_rejection_reasons.Count -gt 0) {
            Write-Host ("      upstream_rejections: {0}" -f ($stage.llm_upstream_rejection_reasons -join ", "))
        }
        if ($stage.llm_backend_override_mismatches -and $stage.llm_backend_override_mismatches.Count -gt 0) {
            Write-Host ("      backend_override_mismatches: {0}" -f ($stage.llm_backend_override_mismatches -join ", "))
        }
        if ($stage.llm_transport_fallback_count -gt 0) {
            Write-Host ("      llm_transport_fallbacks: {0}" -f $stage.llm_transport_fallback_count)
        }
    }
    Write-Host ""
}

if ($Full) {
    Write-Host "  [State History]"
    foreach ($h in $audit.history) { Write-Host "    $h" }
    Write-Host ""

    Write-Host "  [Events]"
    foreach ($ev in $audit.events) {
        Write-Host ("    [{0}] {1} by {2} ({3})" -f $ev.timestamp, $ev.event_type, $ev.actor, $ev.actor_role)
        if ($ev.reason) { Write-Host ("      reason: {0}" -f $ev.reason) }
    }
    Write-Host ""
}

Write-Host "========================================="

if (-not [string]::IsNullOrWhiteSpace($OutPath)) {
    Save-OperatorJson -Payload $audit -OutPath $OutPath
    Write-Host "  out_path : $OutPath"
}

Write-Host "[done] operator-audit: $($audit.project_id) status=$($audit.status)"
