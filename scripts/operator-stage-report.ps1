param(
    [string]$ProjectId = "",
    [string]$ApiBaseUrl = "http://127.0.0.1:8000",
    [int]$TimeoutSec = 0,
    [string]$OutPath = "",
    [switch]$RequireStageTelemetry,
    [string]$AuditJsonPath = "",
    [string]$BundleManifestPath = "",
    [switch]$NoEventDerivedTelemetry
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
    $audit = Read-OperatorJsonFile -Path $AuditJsonPath
} else {
    $response = Invoke-OperatorApi `
        -Method "GET" `
        -ApiBaseUrl $ApiBaseUrl `
        -Path ("/projects/" + $ProjectId + "/audit") `
        -ExpectedStatusCodes @(200) `
        -TimeoutSec $effectiveTimeoutSec

    if ($null -eq $response.BodyJson) {
        Write-Error ("Stage report request succeeded but response body is not valid JSON: {0}" -f $response.BodyText)
        exit 1
    }
    $audit = $response.BodyJson
}

if ([string]$audit.project_id -ne $ProjectId) {
    Write-Error ("Project ID mismatch: expected={0} actual={1}" -f $ProjectId, [string]$audit.project_id)
    exit 1
}
$telemetry = Get-OperatorStageTelemetry `
    -Audit $audit `
    -AllowDerivedFromEvents:(-not $NoEventDerivedTelemetry)
$telemetryPresent = [bool]$telemetry.telemetry_present
$telemetrySource = [string]$telemetry.telemetry_source
$telemetryNotes = @($telemetry.notes)
$legacyFallbackNormalizations = Convert-OperatorToInt `
    -Value $telemetry.legacy_fallback_normalizations `
    -Default 0
$stages = @($telemetry.stage_summary)
$totals = $telemetry.stage_totals

if (-not $telemetryPresent -and $RequireStageTelemetry) {
    Write-Error (
        "Stage telemetry is missing from audit payload (source={0}). " +
        "Enable events/summary telemetry or remove -RequireStageTelemetry." -f $telemetrySource
    )
    exit 1
}

$failing = @($stages | Where-Object { $_.failure_count -gt 0 } | Sort-Object department, sequence, stage_name)
$fallback = @($stages | Where-Object { $_.fallback_count -gt 0 } | Sort-Object department, sequence, stage_name)

Write-Host "[operator-stage-report]"
Write-Host "  project_id : $($audit.project_id)"
Write-Host "  status     : $($audit.status)"
Write-Host "  runs       : $($totals.total_stage_executions)"
Write-Host "  success    : $($totals.total_successes)"
Write-Host "  failure    : $($totals.total_failures)"
Write-Host "  fallback   : $($totals.total_fallbacks)"
Write-Host "  llm_fb     : $($totals.total_llm_transport_fallbacks)"
if ($legacyFallbackNormalizations -gt 0) {
    Write-Host "  legacy_fix : $legacyFallbackNormalizations"
}
Write-Host "  telemetry  : $telemetrySource"
if ($totals.departments_covered -and $totals.departments_covered.Count -gt 0) {
    Write-Host ("  departments: {0}" -f ($totals.departments_covered -join ", "))
}
if ($totals.llm_endpoints_observed -and $totals.llm_endpoints_observed.Count -gt 0) {
    Write-Host ("  endpoints  : {0}" -f ($totals.llm_endpoints_observed -join ", "))
}
foreach ($note in $telemetryNotes) {
    Write-Host ("  note       : {0}" -f $note)
}

if ($failing.Count -gt 0) {
    Write-Host "  [failing stages]"
    foreach ($stage in $failing) {
        $reasons = if ($stage.failure_reasons -and $stage.failure_reasons.Count -gt 0) {
            $stage.failure_reasons -join ", "
        } else {
            "(none)"
        }
        Write-Host ("    {0}#{1} {2} failure={3} reasons={4}" -f $stage.department, $stage.sequence, $stage.stage_name, $stage.failure_count, $reasons)
    }
}

if ($fallback.Count -gt 0) {
    Write-Host "  [fallback stages]"
    foreach ($stage in $fallback) {
        Write-Host ("    {0}#{1} {2} fallback={3}" -f $stage.department, $stage.sequence, $stage.stage_name, $stage.fallback_count)
        if ($stage.llm_transport_fallback_count -gt 0) {
            Write-Host ("      llm_transport_fallbacks={0}" -f $stage.llm_transport_fallback_count)
        }
        if ($stage.llm_endpoints -and $stage.llm_endpoints.Count -gt 0) {
            Write-Host ("      endpoints={0}" -f ($stage.llm_endpoints -join ", "))
        }
        if ($stage.llm_content_kinds -and $stage.llm_content_kinds.Count -gt 0) {
            Write-Host ("      content_kinds={0}" -f ($stage.llm_content_kinds -join ", "))
        }
        if ($stage.llm_backend_overrides -and $stage.llm_backend_overrides.Count -gt 0) {
            Write-Host ("      backend_overrides={0}" -f ($stage.llm_backend_overrides -join ", "))
        }
        if ($stage.llm_upstream_providers -and $stage.llm_upstream_providers.Count -gt 0) {
            Write-Host ("      upstream_providers={0}" -f ($stage.llm_upstream_providers -join ", "))
        }
        if ($stage.llm_upstream_rejection_reasons -and $stage.llm_upstream_rejection_reasons.Count -gt 0) {
            Write-Host ("      upstream_rejections={0}" -f ($stage.llm_upstream_rejection_reasons -join ", "))
        }
        if ($stage.llm_backend_override_mismatches -and $stage.llm_backend_override_mismatches.Count -gt 0) {
            Write-Host ("      backend_override_mismatches={0}" -f ($stage.llm_backend_override_mismatches -join ", "))
        }
    }
}

$report = [pscustomobject]@{
    project_id = $audit.project_id
    status = $audit.status
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    telemetry_present = $telemetryPresent
    telemetry_source = $telemetrySource
    telemetry_notes = $telemetryNotes
    telemetry_legacy_fallback_normalizations = $legacyFallbackNormalizations
    stage_totals = $totals
    stages = $stages
    failing_stages = $failing
    fallback_stages = $fallback
}

if (-not [string]::IsNullOrWhiteSpace($OutPath)) {
    Save-OperatorJson -Payload $report -OutPath $OutPath
    Write-Host "  out_path   : $OutPath"
}

Write-Host "[done] operator-stage-report: $($audit.project_id)"
