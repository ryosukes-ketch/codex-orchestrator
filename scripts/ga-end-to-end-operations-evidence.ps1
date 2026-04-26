param(
    [string]$EnvironmentCloseoutManifestPath = "",
    [string]$AuditabilityCloseoutManifestPath = "",
    [string]$ReadinessManifestPath = "",
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
    $resolvedOutputDir = Join-Path $repoRoot ("logs\ga-steady-state\end-to-end-evidence-{0}" -f $timestamp)
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = Resolve-OperatorAbsolutePath -Path $resolvedOutputDir -BasePath $repoRoot
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "ga-end-to-end-operations-evidence.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}

if ([string]::IsNullOrWhiteSpace($SummaryOutPath)) {
    $SummaryOutPath = Join-Path $resolvedOutputDir "ga-end-to-end-operations-evidence.summary.json"
} elseif (-not [System.IO.Path]::IsPathRooted($SummaryOutPath)) {
    $SummaryOutPath = Resolve-OperatorAbsolutePath -Path $SummaryOutPath -BasePath $repoRoot
}

$resolvedEnvironmentCloseoutPath = ([string]$EnvironmentCloseoutManifestPath).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedEnvironmentCloseoutPath)) {
    $resolvedEnvironmentCloseoutPath = Resolve-LatestManifestPath `
        -SearchRoot (Join-Path $resolvedLogsRoot "ga-ops") `
        -Filter "phase20-environment-support-closeout.manifest.json"
}
if (-not [string]::IsNullOrWhiteSpace($resolvedEnvironmentCloseoutPath) -and -not [System.IO.Path]::IsPathRooted($resolvedEnvironmentCloseoutPath)) {
    $resolvedEnvironmentCloseoutPath = Resolve-OperatorAbsolutePath -Path $resolvedEnvironmentCloseoutPath -BasePath $repoRoot
}

$resolvedAuditabilityCloseoutPath = ([string]$AuditabilityCloseoutManifestPath).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedAuditabilityCloseoutPath)) {
    $resolvedAuditabilityCloseoutPath = Resolve-LatestManifestPath `
        -SearchRoot (Join-Path $resolvedLogsRoot "ga-compliance") `
        -Filter "phase21-auditability-closeout.manifest.json"
}
if (-not [string]::IsNullOrWhiteSpace($resolvedAuditabilityCloseoutPath) -and -not [System.IO.Path]::IsPathRooted($resolvedAuditabilityCloseoutPath)) {
    $resolvedAuditabilityCloseoutPath = Resolve-OperatorAbsolutePath -Path $resolvedAuditabilityCloseoutPath -BasePath $repoRoot
}

$resolvedReadinessPath = ([string]$ReadinessManifestPath).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedReadinessPath)) {
    $resolvedReadinessPath = Resolve-LatestManifestPath `
        -SearchRoot (Join-Path $resolvedLogsRoot "operational-readiness") `
        -Filter "readiness-manifest-*.json"
}
if (-not [string]::IsNullOrWhiteSpace($resolvedReadinessPath) -and -not [System.IO.Path]::IsPathRooted($resolvedReadinessPath)) {
    $resolvedReadinessPath = Resolve-OperatorAbsolutePath -Path $resolvedReadinessPath -BasePath $repoRoot
}

$requiredArtifacts = @(
    [ordered]@{ name = "phase20_closeout"; path = $resolvedEnvironmentCloseoutPath },
    [ordered]@{ name = "phase21_closeout"; path = $resolvedAuditabilityCloseoutPath },
    [ordered]@{ name = "readiness_manifest"; path = $resolvedReadinessPath }
)

$missingRequired = New-Object System.Collections.Generic.List[string]
foreach ($artifact in @($requiredArtifacts)) {
    if ([string]::IsNullOrWhiteSpace([string]$artifact.path) -or -not (Test-Path ([string]$artifact.path))) {
        $missingRequired.Add([string]$artifact.name) | Out-Null
    }
}

$decision = "go"
$decisionReasons = New-Object System.Collections.Generic.List[string]
if ($missingRequired.Count -gt 0) {
    $decision = "watch"
    $decisionReasons.Add(("Missing required end-to-end artifacts: {0}" -f (@($missingRequired.ToArray()) -join ","))) | Out-Null
} else {
    $decisionReasons.Add("All required end-to-end artifacts are available.") | Out-Null
}

$summary = [ordered]@{
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    required_artifact_count = $requiredArtifacts.Count
    missing_required_artifact_count = $missingRequired.Count
    end_to_end_decision = $decision
    end_to_end_decision_reasons = @($decisionReasons.ToArray())
}
Save-OperatorJson -Payload $summary -OutPath $SummaryOutPath

$manifest = [ordered]@{
    bundle_type = "phase22_end_to_end_operations_evidence"
    bundle_version = 1
    generated_at_utc = $summary.generated_at_utc
    summary = $summary
    details = [ordered]@{
        artifacts = $requiredArtifacts
        missing_required_artifacts = @($missingRequired.ToArray())
    }
}
Save-OperatorJson -Payload $manifest -OutPath $OutPath

$reportPath = Join-Path $resolvedOutputDir "ga-end-to-end-operations-evidence.md"
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# GA End-to-End Operations Evidence") | Out-Null
$lines.Add("") | Out-Null
$lines.Add(("- generated_at_utc: {0}" -f $summary.generated_at_utc)) | Out-Null
$lines.Add(("- required_artifact_count: {0}" -f [int]$summary.required_artifact_count)) | Out-Null
$lines.Add(("- missing_required_artifact_count: {0}" -f [int]$summary.missing_required_artifact_count)) | Out-Null
$lines.Add(("- end_to_end_decision: {0}" -f [string]$summary.end_to_end_decision)) | Out-Null
[System.IO.File]::WriteAllLines($reportPath, $lines, [System.Text.Encoding]::UTF8)

$archiveOutputPath = ""
if ($Zip) {
    $archiveOutputPath = $resolvedOutputDir.TrimEnd("\") + ".zip"
    if (Test-Path $archiveOutputPath) {
        Remove-Item -Path $archiveOutputPath -Force
    }
    Compress-Archive -Path (Join-Path $resolvedOutputDir "*") -DestinationPath $archiveOutputPath -Force
}

Write-Host "[done] ga end-to-end operations evidence completed"
Write-Host ("  evidence_manifest : {0}" -f $OutPath)
Write-Host ("  evidence_summary  : {0}" -f $SummaryOutPath)
Write-Host ("  decision          : {0}" -f [string]$summary.end_to_end_decision)
if (-not [string]::IsNullOrWhiteSpace($archiveOutputPath)) {
    Write-Host ("  archive           : {0}" -f $archiveOutputPath)
}
