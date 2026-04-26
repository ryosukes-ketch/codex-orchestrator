param(
    [string]$SupportNormalizationManifestPath = "",
    [string]$BacklogExportManifestPath = "",
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

function Resolve-LatestManifestPath {
    param(
        [string]$SearchRoot,
        [string]$Filter
    )

    if (-not (Test-Path $SearchRoot)) {
        return ""
    }
    $latest = Get-ChildItem -Path $SearchRoot -Recurse -File -Filter $Filter |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($null -eq $latest) {
        return ""
    }
    return $latest.FullName
}

function Add-LedgerEntry {
    param(
        [System.Collections.Generic.List[object]]$List,
        [string]$EntryType,
        [string]$EntryId,
        [string]$Severity,
        [string]$Status,
        [string]$SourceManifestPath,
        [string]$Summary
    )

    $List.Add([ordered]@{
        entry_type = $EntryType
        entry_id = $EntryId
        severity = $Severity
        status = $Status
        source_manifest_path = $SourceManifestPath
        summary = $Summary
    }) | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$resolvedLogsRoot = Resolve-OperatorAbsolutePath -Path $LogsRoot -BasePath $repoRoot
$resolvedOutputDir = ([string]$OutputDir).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedOutputDir)) {
    $resolvedOutputDir = Join-Path $repoRoot ("logs\ga-compliance\incident-change-ledger-{0}" -f $timestamp)
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = Resolve-OperatorAbsolutePath -Path $resolvedOutputDir -BasePath $repoRoot
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "ga-incident-change-ledger.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}

if ([string]::IsNullOrWhiteSpace($SummaryOutPath)) {
    $SummaryOutPath = Join-Path $resolvedOutputDir "ga-incident-change-ledger.summary.json"
} elseif (-not [System.IO.Path]::IsPathRooted($SummaryOutPath)) {
    $SummaryOutPath = Resolve-OperatorAbsolutePath -Path $SummaryOutPath -BasePath $repoRoot
}

$resolvedSupportNormalizationPath = ([string]$SupportNormalizationManifestPath).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedSupportNormalizationPath)) {
    $resolvedSupportNormalizationPath = Resolve-LatestManifestPath `
        -SearchRoot (Join-Path $resolvedLogsRoot "ga-ops") `
        -Filter "ga-support-intake-normalization.manifest.json"
}
if (-not [string]::IsNullOrWhiteSpace($resolvedSupportNormalizationPath) -and -not [System.IO.Path]::IsPathRooted($resolvedSupportNormalizationPath)) {
    $resolvedSupportNormalizationPath = Resolve-OperatorAbsolutePath -Path $resolvedSupportNormalizationPath -BasePath $repoRoot
}

$resolvedBacklogExportPath = ([string]$BacklogExportManifestPath).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedBacklogExportPath)) {
    $resolvedBacklogExportPath = Resolve-LatestManifestPath `
        -SearchRoot (Join-Path $resolvedLogsRoot "post-launch-ops") `
        -Filter "post-launch-backlog-export.manifest.json"
}
if (-not [string]::IsNullOrWhiteSpace($resolvedBacklogExportPath) -and -not [System.IO.Path]::IsPathRooted($resolvedBacklogExportPath)) {
    $resolvedBacklogExportPath = Resolve-OperatorAbsolutePath -Path $resolvedBacklogExportPath -BasePath $repoRoot
}

$entries = New-Object System.Collections.Generic.List[object]

if (-not [string]::IsNullOrWhiteSpace($resolvedSupportNormalizationPath) -and (Test-Path $resolvedSupportNormalizationPath)) {
    $support = Read-OperatorJsonFile -Path $resolvedSupportNormalizationPath
    if ([string]$support.bundle_type -eq "phase20_support_intake_normalization") {
        Add-LedgerEntry `
            -List $entries `
            -EntryType "incident" `
            -EntryId "INC-SUPPORT-NORMALIZATION" `
            -Severity "medium" `
            -Status ([string]$support.summary.normalization_decision) `
            -SourceManifestPath $resolvedSupportNormalizationPath `
            -Summary ("blocking={0}, findings={1}, missing_fields={2}" -f [int]$support.summary.blocking_manifest_count, [int]$support.summary.finding_count_total, [int]$support.summary.missing_required_field_count)
    }
}

if (-not [string]::IsNullOrWhiteSpace($resolvedBacklogExportPath) -and (Test-Path $resolvedBacklogExportPath)) {
    $backlog = Read-OperatorJsonFile -Path $resolvedBacklogExportPath
    if ([string]$backlog.bundle_type -eq "phase13_post_launch_release_backlog_export") {
        Add-LedgerEntry `
            -List $entries `
            -EntryType "change" `
            -EntryId "CHG-POST-LAUNCH-BACKLOG" `
            -Severity "medium" `
            -Status "open" `
            -SourceManifestPath $resolvedBacklogExportPath `
            -Summary ("runbook={0}, product={1}, release={2}" -f [int]$backlog.summary.runbook_backlog_count, [int]$backlog.summary.product_backlog_count, [int]$backlog.summary.release_backlog_count)
    }
}

$incidentCount = @($entries | Where-Object { $_.entry_type -eq "incident" }).Count
$changeCount = @($entries | Where-Object { $_.entry_type -eq "change" }).Count
$decision = "go"
$decisionReasons = New-Object System.Collections.Generic.List[string]
if ($incidentCount -eq 0 -or $changeCount -eq 0) {
    $decision = "watch"
    $decisionReasons.Add("Incident/change ledger is missing one or more entry families.") | Out-Null
} else {
    $decisionReasons.Add("Incident and change ledger entries are both present.") | Out-Null
}

$summary = [ordered]@{
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    support_normalization_manifest_path = $resolvedSupportNormalizationPath
    backlog_export_manifest_path = $resolvedBacklogExportPath
    incident_entry_count = $incidentCount
    change_entry_count = $changeCount
    ledger_decision = $decision
    ledger_decision_reasons = @($decisionReasons.ToArray())
}
Save-OperatorJson -Payload $summary -OutPath $SummaryOutPath

$manifest = [ordered]@{
    bundle_type = "phase21_incident_change_ledger"
    bundle_version = 1
    generated_at_utc = $summary.generated_at_utc
    summary = $summary
    details = [ordered]@{
        entries = @($entries.ToArray())
        next_steps = @(
            "1) route watch/escalate ledger entries into quarterly governance reviews.",
            "2) link each ledger entry to audit traceability index IDs.",
            "3) preserve ledger snapshots in retention/export policy archives."
        )
    }
}
Save-OperatorJson -Payload $manifest -OutPath $OutPath

$reportPath = Join-Path $resolvedOutputDir "ga-incident-change-ledger.md"
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# GA Incident/Change Ledger") | Out-Null
$lines.Add("") | Out-Null
$lines.Add(("- generated_at_utc: {0}" -f $summary.generated_at_utc)) | Out-Null
$lines.Add(("- incident_entry_count: {0}" -f [int]$summary.incident_entry_count)) | Out-Null
$lines.Add(("- change_entry_count: {0}" -f [int]$summary.change_entry_count)) | Out-Null
$lines.Add(("- ledger_decision: {0}" -f [string]$summary.ledger_decision)) | Out-Null
[System.IO.File]::WriteAllLines($reportPath, $lines, [System.Text.Encoding]::UTF8)

$archiveOutputPath = ""
if ($Zip) {
    $archiveOutputPath = $resolvedOutputDir.TrimEnd("\") + ".zip"
    if (Test-Path $archiveOutputPath) {
        Remove-Item -Path $archiveOutputPath -Force
    }
    Compress-Archive -Path (Join-Path $resolvedOutputDir "*") -DestinationPath $archiveOutputPath -Force
}

Write-Host "[done] ga incident/change ledger completed"
Write-Host ("  ledger_manifest : {0}" -f $OutPath)
Write-Host ("  ledger_summary  : {0}" -f $SummaryOutPath)
Write-Host ("  decision        : {0}" -f [string]$summary.ledger_decision)
if (-not [string]::IsNullOrWhiteSpace($archiveOutputPath)) {
    Write-Host ("  archive         : {0}" -f $archiveOutputPath)
}

