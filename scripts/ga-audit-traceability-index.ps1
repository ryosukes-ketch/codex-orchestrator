param(
    [string]$RetentionManifestPath = "",
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

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$resolvedLogsRoot = Resolve-OperatorAbsolutePath -Path $LogsRoot -BasePath $repoRoot
$resolvedOutputDir = ([string]$OutputDir).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedOutputDir)) {
    $resolvedOutputDir = Join-Path $repoRoot ("logs\ga-compliance\traceability-index-{0}" -f $timestamp)
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = Resolve-OperatorAbsolutePath -Path $resolvedOutputDir -BasePath $repoRoot
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "ga-audit-traceability-index.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}

if ([string]::IsNullOrWhiteSpace($SummaryOutPath)) {
    $SummaryOutPath = Join-Path $resolvedOutputDir "ga-audit-traceability-index.summary.json"
} elseif (-not [System.IO.Path]::IsPathRooted($SummaryOutPath)) {
    $SummaryOutPath = Resolve-OperatorAbsolutePath -Path $SummaryOutPath -BasePath $repoRoot
}

$resolvedRetentionManifestPath = ([string]$RetentionManifestPath).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedRetentionManifestPath)) {
    $resolvedRetentionManifestPath = Resolve-LatestManifestPath `
        -SearchRoot (Join-Path $resolvedLogsRoot "ga-compliance") `
        -Filter "ga-artifact-retention-coverage.manifest.json"
}
if ([string]::IsNullOrWhiteSpace($resolvedRetentionManifestPath)) {
    $resolvedRetentionManifestPath = Join-Path $resolvedOutputDir "ga-artifact-retention-coverage.manifest.json"
    & (Join-Path $PSScriptRoot "ga-artifact-retention-coverage.ps1") `
        -LogsRoot $resolvedLogsRoot `
        -OutputDir $resolvedOutputDir `
        -OutPath $resolvedRetentionManifestPath `
        -SummaryOutPath (Join-Path $resolvedOutputDir "ga-artifact-retention-coverage.summary.json")
}
if (-not [System.IO.Path]::IsPathRooted($resolvedRetentionManifestPath)) {
    $resolvedRetentionManifestPath = Resolve-OperatorAbsolutePath -Path $resolvedRetentionManifestPath -BasePath $repoRoot
}
if (-not (Test-Path $resolvedRetentionManifestPath)) {
    Write-Error ("Retention manifest not found: {0}" -f $resolvedRetentionManifestPath)
    exit 1
}

$retentionManifest = Read-OperatorJsonFile -Path $resolvedRetentionManifestPath
if ([string]$retentionManifest.bundle_type -ne "phase21_artifact_retention_export_coverage") {
    Write-Error ("Unsupported retention bundle_type [{0}] in {1}" -f ([string]$retentionManifest.bundle_type), $resolvedRetentionManifestPath)
    exit 1
}

$requiredTraceTypes = @(
    "readiness_manifest",
    "release_train_evidence",
    "phase20_closeout",
    "support_intake_manifest"
)

$traceEntries = @(
    [ordered]@{
        trace_type = "readiness_manifest"
        manifest_path = Resolve-LatestManifestPath -SearchRoot (Join-Path $resolvedLogsRoot "operational-readiness") -Filter "readiness-manifest-*.json"
    },
    [ordered]@{
        trace_type = "release_train_evidence"
        manifest_path = Resolve-LatestManifestPath -SearchRoot (Join-Path $resolvedLogsRoot "release-train") -Filter "release-train-evidence.manifest.json"
    },
    [ordered]@{
        trace_type = "phase20_closeout"
        manifest_path = Resolve-LatestManifestPath -SearchRoot (Join-Path $resolvedLogsRoot "ga-ops") -Filter "phase20-environment-support-closeout.manifest.json"
    },
    [ordered]@{
        trace_type = "support_intake_manifest"
        manifest_path = Resolve-LatestManifestPath -SearchRoot (Join-Path $resolvedLogsRoot "self-serve") -Filter "support-intake.manifest.json"
    },
    [ordered]@{
        trace_type = "phase19_closeout"
        manifest_path = Resolve-LatestManifestPath -SearchRoot (Join-Path $resolvedLogsRoot "ga-upgrade") -Filter "phase19-upgrade-evidence-closeout.manifest.json"
    }
)

$missingRequired = New-Object System.Collections.Generic.List[string]
foreach ($entry in @($traceEntries)) {
    if (-not [string]::IsNullOrWhiteSpace([string]$entry.manifest_path) -and -not [System.IO.Path]::IsPathRooted([string]$entry.manifest_path)) {
        $entry.manifest_path = Resolve-OperatorAbsolutePath -Path ([string]$entry.manifest_path) -BasePath $repoRoot
    }
    if ($requiredTraceTypes -contains [string]$entry.trace_type) {
        if ([string]::IsNullOrWhiteSpace([string]$entry.manifest_path) -or -not (Test-Path ([string]$entry.manifest_path))) {
            $missingRequired.Add([string]$entry.trace_type) | Out-Null
        }
    }
}

$decision = "go"
$decisionReasons = New-Object System.Collections.Generic.List[string]
if ($missingRequired.Count -gt 0) {
    $decision = "watch"
    $decisionReasons.Add(("Required traceability entries missing: {0}" -f (@($missingRequired.ToArray()) -join ","))) | Out-Null
} else {
    $decisionReasons.Add("All required traceability entries resolved.") | Out-Null
}

$summary = [ordered]@{
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    retention_manifest_path = $resolvedRetentionManifestPath
    trace_entry_count = @($traceEntries).Count
    required_trace_type_count = $requiredTraceTypes.Count
    missing_required_trace_count = $missingRequired.Count
    traceability_decision = $decision
    traceability_decision_reasons = @($decisionReasons.ToArray())
}
Save-OperatorJson -Payload $summary -OutPath $SummaryOutPath

$manifest = [ordered]@{
    bundle_type = "phase21_audit_traceability_index"
    bundle_version = 1
    generated_at_utc = $summary.generated_at_utc
    summary = $summary
    details = [ordered]@{
        required_trace_types = $requiredTraceTypes
        missing_required_trace_types = @($missingRequired.ToArray())
        trace_entries = $traceEntries
        next_steps = @(
            "1) populate missing trace types before compliance-lite closeout.",
            "2) connect traceability index with incident/change ledger package.",
            "3) retain index output in staging evidence closure."
        )
    }
}
Save-OperatorJson -Payload $manifest -OutPath $OutPath

$reportPath = Join-Path $resolvedOutputDir "ga-audit-traceability-index.md"
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# GA Audit Traceability Index") | Out-Null
$lines.Add("") | Out-Null
$lines.Add(("- generated_at_utc: {0}" -f $summary.generated_at_utc)) | Out-Null
$lines.Add(("- trace_entry_count: {0}" -f [int]$summary.trace_entry_count)) | Out-Null
$lines.Add(("- missing_required_trace_count: {0}" -f [int]$summary.missing_required_trace_count)) | Out-Null
$lines.Add(("- traceability_decision: {0}" -f [string]$summary.traceability_decision)) | Out-Null
[System.IO.File]::WriteAllLines($reportPath, $lines, [System.Text.Encoding]::UTF8)

$archiveOutputPath = ""
if ($Zip) {
    $archiveOutputPath = $resolvedOutputDir.TrimEnd("\") + ".zip"
    if (Test-Path $archiveOutputPath) {
        Remove-Item -Path $archiveOutputPath -Force
    }
    Compress-Archive -Path (Join-Path $resolvedOutputDir "*") -DestinationPath $archiveOutputPath -Force
}

Write-Host "[done] ga audit traceability index completed"
Write-Host ("  traceability_manifest : {0}" -f $OutPath)
Write-Host ("  traceability_summary  : {0}" -f $SummaryOutPath)
Write-Host ("  decision              : {0}" -f [string]$summary.traceability_decision)
if (-not [string]::IsNullOrWhiteSpace($archiveOutputPath)) {
    Write-Host ("  archive               : {0}" -f $archiveOutputPath)
}

