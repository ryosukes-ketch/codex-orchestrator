param(
    [string]$ProjectId = "",
    [string]$ApiBaseUrl = "http://127.0.0.1:8000",
    [int]$TimeoutSec = 0,
    [string]$OutPath = "",
    [string]$AuditJsonPath = "",
    [string]$SummaryOutPath = "",
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
    Write-Host ("[operator-status] LOAD {0}" -f $AuditJsonPath)
    $audit = Read-OperatorJsonFile -Path $AuditJsonPath
} else {
    $url = $ApiBaseUrl.TrimEnd("/") + "/projects/" + $ProjectId + "/audit"
    Write-Host "[operator-status] GET $url"

    $response = Invoke-OperatorApi `
        -Method "GET" `
        -ApiBaseUrl $ApiBaseUrl `
        -Path ("/projects/" + $ProjectId + "/audit") `
        -ExpectedStatusCodes @(200) `
        -TimeoutSec $effectiveTimeoutSec

    if ($null -eq $response.BodyJson) {
        Write-Error ("Status check succeeded but response body is not valid JSON: {0}" -f $response.BodyText)
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
$stageTotals = $telemetry.stage_totals
$telemetryPresent = [bool]$telemetry.telemetry_present
$telemetrySource = [string]$telemetry.telemetry_source
$telemetryNotes = @($telemetry.notes)
$legacyFallbackNormalizations = Convert-OperatorToInt `
    -Value $telemetry.legacy_fallback_normalizations `
    -Default 0

Write-Host ""
Write-Host "  project_id  : $($audit.project_id)"
Write-Host "  status            : $($audit.status)"
Write-Host "  checkpoints : $($audit.checkpoints.Count)"
Write-Host "  approvals   : $($audit.approvals.Count)"
Write-Host "  reviews     : $($audit.reviews.Count)"
Write-Host "  events      : $($audit.events.Count)"

if ($telemetryPresent) {
    Write-Host "  stage runs  : $($stageTotals.total_stage_executions)"
    Write-Host "  stage ok    : $($stageTotals.total_successes)"
    Write-Host "  stage fail  : $($stageTotals.total_failures)"
    Write-Host "  stage fb    : $($stageTotals.total_fallbacks)"
    Write-Host "  llm fb      : $($stageTotals.total_llm_transport_fallbacks)"
    if ($legacyFallbackNormalizations -gt 0) {
        Write-Host "  legacy fix  : $legacyFallbackNormalizations"
    }
    Write-Host ("  telemetry   : {0}" -f $telemetrySource)
    if ($stageTotals.departments_covered -and $stageTotals.departments_covered.Count -gt 0) {
        Write-Host ("  stage depts : {0}" -f ($stageTotals.departments_covered -join ", "))
    }
    if ($stageTotals.llm_endpoints_observed -and $stageTotals.llm_endpoints_observed.Count -gt 0) {
        Write-Host ("  stage ep    : {0}" -f ($stageTotals.llm_endpoints_observed -join ", "))
    }
} else {
    Write-Host ("  telemetry   : {0}" -f $telemetrySource)
}

foreach ($note in $telemetryNotes) {
    Write-Host ("  note        : {0}" -f $note)
}

if ($audit.approvals -and $audit.approvals.Count -gt 0) {
    Write-Host "  [approvals]"
    foreach ($ap in $audit.approvals) {
        Write-Host ("    action={0} status={1}" -f $ap.action_type, $ap.status)
    }
}

if (-not [string]::IsNullOrWhiteSpace($OutPath)) {
    Save-OperatorJson -Payload $audit -OutPath $OutPath
    Write-Host "  out_path    : $OutPath"
}

$summaryPayload = [ordered]@{
    project_id = [string]$audit.project_id
    status = [string]$audit.status
    checkpoints = @($audit.checkpoints).Count
    approvals = @($audit.approvals).Count
    reviews = @($audit.reviews).Count
    events = @($audit.events).Count
    telemetry_present = $telemetryPresent
    telemetry_source = $telemetrySource
    telemetry_notes = $telemetryNotes
    telemetry_legacy_fallback_normalizations = $legacyFallbackNormalizations
    stage_totals = $stageTotals
    approval_statuses = @(
        @($audit.approvals) | ForEach-Object {
            [pscustomobject]@{
                action = [string]$_.action_type
                status = [string]$_.status
            }
        }
    )
}
if (-not [string]::IsNullOrWhiteSpace($SummaryOutPath)) {
    Save-OperatorJson -Payload $summaryPayload -OutPath $SummaryOutPath
    Write-Host "  summary_out : $SummaryOutPath"
}

Write-Host ""
Write-Host "[done] operator-status: $($audit.project_id) -> $($audit.status)"
