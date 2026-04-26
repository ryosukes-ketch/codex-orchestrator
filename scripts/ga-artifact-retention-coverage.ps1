param(
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

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$resolvedLogsRoot = Resolve-OperatorAbsolutePath -Path $LogsRoot -BasePath $repoRoot
$resolvedOutputDir = ([string]$OutputDir).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedOutputDir)) {
    $resolvedOutputDir = Join-Path $repoRoot ("logs\ga-compliance\retention-coverage-{0}" -f $timestamp)
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = Resolve-OperatorAbsolutePath -Path $resolvedOutputDir -BasePath $repoRoot
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "ga-artifact-retention-coverage.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}

if ([string]::IsNullOrWhiteSpace($SummaryOutPath)) {
    $SummaryOutPath = Join-Path $resolvedOutputDir "ga-artifact-retention-coverage.summary.json"
} elseif (-not [System.IO.Path]::IsPathRooted($SummaryOutPath)) {
    $SummaryOutPath = Resolve-OperatorAbsolutePath -Path $SummaryOutPath -BasePath $repoRoot
}

$retentionPolicy = @(
    [ordered]@{ artifact_family = "readiness"; retention_days = 90; export_required = $true; root = "operational-readiness" },
    [ordered]@{ artifact_family = "operator_cycles"; retention_days = 60; export_required = $true; root = "operator-cycles" },
    [ordered]@{ artifact_family = "operator_suites"; retention_days = 90; export_required = $true; root = "operator-suites" },
    [ordered]@{ artifact_family = "support_bundles"; retention_days = 90; export_required = $true; root = "self-serve" },
    [ordered]@{ artifact_family = "release_train"; retention_days = 180; export_required = $true; root = "release-train" },
    [ordered]@{ artifact_family = "ga_ops"; retention_days = 180; export_required = $true; root = "ga-ops" },
    [ordered]@{ artifact_family = "ga_compliance"; retention_days = 180; export_required = $true; root = "ga-compliance" }
)

$coverageRows = New-Object System.Collections.Generic.List[object]
$missingCoverageCount = 0
foreach ($policy in @($retentionPolicy)) {
    $root = Join-Path $resolvedLogsRoot ([string]$policy.root)
    $manifestCount = 0
    if (Test-Path $root) {
        $manifestCount = @(
            Get-ChildItem -Path $root -Recurse -File -Filter "*.manifest.json" -ErrorAction SilentlyContinue
        ).Count
    }
    if ($manifestCount -eq 0 -and (Convert-OperatorToBool -Value $policy.export_required -Default $false)) {
        $missingCoverageCount += 1
    }
    $coverageRows.Add([ordered]@{
        artifact_family = [string]$policy.artifact_family
        root = $root
        retention_days = Convert-OperatorToInt -Value $policy.retention_days -Default 0
        export_required = Convert-OperatorToBool -Value $policy.export_required -Default $false
        manifest_count = $manifestCount
    }) | Out-Null
}

$decision = "go"
$decisionReasons = New-Object System.Collections.Generic.List[string]
if ($missingCoverageCount -gt 0) {
    $decision = "watch"
    $decisionReasons.Add("One or more required artifact families do not yet have manifest coverage under logs root.") | Out-Null
} else {
    $decisionReasons.Add("All required artifact families have manifest coverage in logs root.") | Out-Null
}

$summary = [ordered]@{
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    logs_root = $resolvedLogsRoot
    artifact_family_count = $coverageRows.Count
    missing_required_coverage_count = $missingCoverageCount
    retention_decision = $decision
    retention_decision_reasons = @($decisionReasons.ToArray())
}
Save-OperatorJson -Payload $summary -OutPath $SummaryOutPath

$manifest = [ordered]@{
    bundle_type = "phase21_artifact_retention_export_coverage"
    bundle_version = 1
    generated_at_utc = $summary.generated_at_utc
    summary = $summary
    details = [ordered]@{
        retention_policy = $retentionPolicy
        coverage_rows = @($coverageRows.ToArray())
        next_steps = @(
            "1) fill missing required artifact families before compliance-lite closeout.",
            "2) generate audit traceability index from latest manifest roots.",
            "3) route unresolved retention gaps into incident/change ledger."
        )
    }
}
Save-OperatorJson -Payload $manifest -OutPath $OutPath

$reportPath = Join-Path $resolvedOutputDir "ga-artifact-retention-coverage.md"
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# GA Artifact Retention and Export Coverage") | Out-Null
$lines.Add("") | Out-Null
$lines.Add(("- generated_at_utc: {0}" -f $summary.generated_at_utc)) | Out-Null
$lines.Add(("- logs_root: {0}" -f $summary.logs_root)) | Out-Null
$lines.Add(("- artifact_family_count: {0}" -f [int]$summary.artifact_family_count)) | Out-Null
$lines.Add(("- missing_required_coverage_count: {0}" -f [int]$summary.missing_required_coverage_count)) | Out-Null
$lines.Add(("- retention_decision: {0}" -f [string]$summary.retention_decision)) | Out-Null
[System.IO.File]::WriteAllLines($reportPath, $lines, [System.Text.Encoding]::UTF8)

$archiveOutputPath = ""
if ($Zip) {
    $archiveOutputPath = $resolvedOutputDir.TrimEnd("\") + ".zip"
    if (Test-Path $archiveOutputPath) {
        Remove-Item -Path $archiveOutputPath -Force
    }
    Compress-Archive -Path (Join-Path $resolvedOutputDir "*") -DestinationPath $archiveOutputPath -Force
}

Write-Host "[done] ga artifact retention/export coverage completed"
Write-Host ("  retention_manifest : {0}" -f $OutPath)
Write-Host ("  retention_summary  : {0}" -f $SummaryOutPath)
Write-Host ("  decision           : {0}" -f [string]$summary.retention_decision)
if (-not [string]::IsNullOrWhiteSpace($archiveOutputPath)) {
    Write-Host ("  archive            : {0}" -f $archiveOutputPath)
}

