param(
    [string]$RetentionManifestPath = "",
    [string]$TraceabilityManifestPath = "",
    [string]$LedgerManifestPath = "",
    [string]$LogsRoot = "logs",
    [string]$OutputDir = "",
    [string]$OutPath = "",
    [string]$SummaryOutPath = "",
    [switch]$Zip
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. (Join-Path $PSScriptRoot "operator-common.ps1")

function Resolve-OptionalPath {
    param(
        [string]$PathValue,
        [string]$BasePath
    )
    $raw = ([string]$PathValue).Trim()
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return ""
    }
    return Resolve-OperatorAbsolutePath -Path $raw -BasePath $BasePath
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$resolvedLogsRoot = Resolve-OperatorAbsolutePath -Path $LogsRoot -BasePath $repoRoot
$resolvedOutputDir = ([string]$OutputDir).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedOutputDir)) {
    $resolvedOutputDir = Join-Path $repoRoot ("logs\ga-compliance\phase21-closeout-{0}" -f $timestamp)
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = Resolve-OperatorAbsolutePath -Path $resolvedOutputDir -BasePath $repoRoot
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "phase21-auditability-closeout.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}

if ([string]::IsNullOrWhiteSpace($SummaryOutPath)) {
    $SummaryOutPath = Join-Path $resolvedOutputDir "phase21-auditability-closeout.summary.json"
} elseif (-not [System.IO.Path]::IsPathRooted($SummaryOutPath)) {
    $SummaryOutPath = Resolve-OperatorAbsolutePath -Path $SummaryOutPath -BasePath $repoRoot
}

$resolvedRetentionManifestPath = Resolve-OptionalPath -PathValue $RetentionManifestPath -BasePath $repoRoot
$resolvedTraceabilityManifestPath = Resolve-OptionalPath -PathValue $TraceabilityManifestPath -BasePath $repoRoot
$resolvedLedgerManifestPath = Resolve-OptionalPath -PathValue $LedgerManifestPath -BasePath $repoRoot

$retentionOut = Join-Path $resolvedOutputDir "ga-artifact-retention-coverage.manifest.json"
if ([string]::IsNullOrWhiteSpace($resolvedRetentionManifestPath) -or -not (Test-Path $resolvedRetentionManifestPath)) {
    & (Join-Path $PSScriptRoot "ga-artifact-retention-coverage.ps1") `
        -LogsRoot $resolvedLogsRoot `
        -OutputDir (Join-Path $resolvedOutputDir "retention") `
        -OutPath $retentionOut `
        -SummaryOutPath (Join-Path $resolvedOutputDir "ga-artifact-retention-coverage.summary.json")
    $resolvedRetentionManifestPath = $retentionOut
}

$traceabilityOut = Join-Path $resolvedOutputDir "ga-audit-traceability-index.manifest.json"
if ([string]::IsNullOrWhiteSpace($resolvedTraceabilityManifestPath) -or -not (Test-Path $resolvedTraceabilityManifestPath)) {
    & (Join-Path $PSScriptRoot "ga-audit-traceability-index.ps1") `
        -RetentionManifestPath $resolvedRetentionManifestPath `
        -LogsRoot $resolvedLogsRoot `
        -OutputDir (Join-Path $resolvedOutputDir "traceability") `
        -OutPath $traceabilityOut `
        -SummaryOutPath (Join-Path $resolvedOutputDir "ga-audit-traceability-index.summary.json")
    $resolvedTraceabilityManifestPath = $traceabilityOut
}

$ledgerOut = Join-Path $resolvedOutputDir "ga-incident-change-ledger.manifest.json"
if ([string]::IsNullOrWhiteSpace($resolvedLedgerManifestPath) -or -not (Test-Path $resolvedLedgerManifestPath)) {
    & (Join-Path $PSScriptRoot "ga-incident-change-ledger.ps1") `
        -LogsRoot $resolvedLogsRoot `
        -OutputDir (Join-Path $resolvedOutputDir "ledger") `
        -OutPath $ledgerOut `
        -SummaryOutPath (Join-Path $resolvedOutputDir "ga-incident-change-ledger.summary.json")
    $resolvedLedgerManifestPath = $ledgerOut
}

$retention = Read-OperatorJsonFile -Path $resolvedRetentionManifestPath
$traceability = Read-OperatorJsonFile -Path $resolvedTraceabilityManifestPath
$ledger = Read-OperatorJsonFile -Path $resolvedLedgerManifestPath

if ([string]$retention.bundle_type -ne "phase21_artifact_retention_export_coverage") {
    Write-Error ("Unexpected retention bundle_type: {0}" -f [string]$retention.bundle_type)
    exit 1
}
if ([string]$traceability.bundle_type -ne "phase21_audit_traceability_index") {
    Write-Error ("Unexpected traceability bundle_type: {0}" -f [string]$traceability.bundle_type)
    exit 1
}
if ([string]$ledger.bundle_type -ne "phase21_incident_change_ledger") {
    Write-Error ("Unexpected ledger bundle_type: {0}" -f [string]$ledger.bundle_type)
    exit 1
}

$retentionDecision = ([string]$retention.summary.retention_decision).Trim().ToLowerInvariant()
$traceabilityDecision = ([string]$traceability.summary.traceability_decision).Trim().ToLowerInvariant()
$ledgerDecision = ([string]$ledger.summary.ledger_decision).Trim().ToLowerInvariant()

$closeoutDecision = "go"
$decisionReasons = New-Object System.Collections.Generic.List[string]
if (@($retentionDecision, $traceabilityDecision, $ledgerDecision) -contains "escalate") {
    $closeoutDecision = "escalate"
    $decisionReasons.Add("At least one compliance-lite package returned escalate.") | Out-Null
} elseif (@($retentionDecision, $traceabilityDecision, $ledgerDecision) -contains "watch") {
    $closeoutDecision = "watch"
    $decisionReasons.Add("At least one compliance-lite package returned watch.") | Out-Null
} else {
    $decisionReasons.Add("Retention, traceability, and ledger packages all returned go.") | Out-Null
}

$summary = [ordered]@{
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    retention_decision = $retentionDecision
    traceability_decision = $traceabilityDecision
    ledger_decision = $ledgerDecision
    closeout_decision = $closeoutDecision
    closeout_decision_reasons = @($decisionReasons.ToArray())
}
Save-OperatorJson -Payload $summary -OutPath $SummaryOutPath

$manifest = [ordered]@{
    bundle_type = "phase21_auditability_closeout"
    bundle_version = 1
    generated_at_utc = $summary.generated_at_utc
    summary = $summary
    source = [ordered]@{
        retention_manifest_path = $resolvedRetentionManifestPath
        traceability_manifest_path = $resolvedTraceabilityManifestPath
        ledger_manifest_path = $resolvedLedgerManifestPath
    }
}
Save-OperatorJson -Payload $manifest -OutPath $OutPath

$reportPath = Join-Path $resolvedOutputDir "phase21-auditability-closeout.md"
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# Phase 21 Auditability Closeout") | Out-Null
$lines.Add("") | Out-Null
$lines.Add(("- generated_at_utc: {0}" -f $summary.generated_at_utc)) | Out-Null
$lines.Add(("- retention_decision: {0}" -f [string]$summary.retention_decision)) | Out-Null
$lines.Add(("- traceability_decision: {0}" -f [string]$summary.traceability_decision)) | Out-Null
$lines.Add(("- ledger_decision: {0}" -f [string]$summary.ledger_decision)) | Out-Null
$lines.Add(("- closeout_decision: {0}" -f [string]$summary.closeout_decision)) | Out-Null
[System.IO.File]::WriteAllLines($reportPath, $lines, [System.Text.Encoding]::UTF8)

$archiveOutputPath = ""
if ($Zip) {
    $archiveOutputPath = $resolvedOutputDir.TrimEnd("\") + ".zip"
    if (Test-Path $archiveOutputPath) {
        Remove-Item -Path $archiveOutputPath -Force
    }
    Compress-Archive -Path (Join-Path $resolvedOutputDir "*") -DestinationPath $archiveOutputPath -Force
}

Write-Host "[done] phase21 auditability closeout completed"
Write-Host ("  closeout_manifest : {0}" -f $OutPath)
Write-Host ("  closeout_summary  : {0}" -f $SummaryOutPath)
Write-Host ("  closeout_decision : {0}" -f [string]$summary.closeout_decision)
if (-not [string]::IsNullOrWhiteSpace($archiveOutputPath)) {
    Write-Host ("  archive           : {0}" -f $archiveOutputPath)
}

