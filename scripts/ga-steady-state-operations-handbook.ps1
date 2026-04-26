param(
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
$resolvedOutputDir = ([string]$OutputDir).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedOutputDir)) {
    $resolvedOutputDir = Join-Path $repoRoot ("logs\ga-steady-state\operations-handbook-{0}" -f $timestamp)
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = Resolve-OperatorAbsolutePath -Path $resolvedOutputDir -BasePath $repoRoot
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "ga-steady-state-operations-handbook.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}

if ([string]::IsNullOrWhiteSpace($SummaryOutPath)) {
    $SummaryOutPath = Join-Path $resolvedOutputDir "ga-steady-state-operations-handbook.summary.json"
} elseif (-not [System.IO.Path]::IsPathRooted($SummaryOutPath)) {
    $SummaryOutPath = Resolve-OperatorAbsolutePath -Path $SummaryOutPath -BasePath $repoRoot
}

$requiredDocs = @(
    "README.md",
    "docs/operator_workflow_runbook.md",
    "docs/operational_startup_runbook.md",
    "docs/operational_readiness_runbook.md",
    "docs/phase20_environment_compatibility_support.md",
    "docs/phase21_auditability_retention_governance.md",
    "docs/phase22_steady_state_operations_closure.md",
    "docs/steady_state_operations_handbook.md",
    "docs/release_ops_cadence_baseline.md"
)

$missingDocs = New-Object System.Collections.Generic.List[string]
foreach ($path in @($requiredDocs)) {
    if (-not (Test-Path (Resolve-OperatorAbsolutePath -Path $path -BasePath $repoRoot))) {
        $missingDocs.Add($path) | Out-Null
    }
}

$decision = "go"
$decisionReasons = New-Object System.Collections.Generic.List[string]
if ($missingDocs.Count -gt 0) {
    $decision = "watch"
    $decisionReasons.Add(("Missing handbook docs: {0}" -f (@($missingDocs.ToArray()) -join ","))) | Out-Null
} else {
    $decisionReasons.Add("All required steady-state handbook docs are present.") | Out-Null
}

$summary = [ordered]@{
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    required_doc_count = $requiredDocs.Count
    missing_doc_count = $missingDocs.Count
    handbook_decision = $decision
    handbook_decision_reasons = @($decisionReasons.ToArray())
}
Save-OperatorJson -Payload $summary -OutPath $SummaryOutPath

$manifest = [ordered]@{
    bundle_type = "phase22_steady_state_operations_handbook"
    bundle_version = 1
    generated_at_utc = $summary.generated_at_utc
    summary = $summary
    details = [ordered]@{
        required_docs = $requiredDocs
        missing_docs = @($missingDocs.ToArray())
    }
}
Save-OperatorJson -Payload $manifest -OutPath $OutPath

$reportPath = Join-Path $resolvedOutputDir "ga-steady-state-operations-handbook.md"
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# GA Steady-State Operations Handbook Package") | Out-Null
$lines.Add("") | Out-Null
$lines.Add(("- generated_at_utc: {0}" -f $summary.generated_at_utc)) | Out-Null
$lines.Add(("- required_doc_count: {0}" -f [int]$summary.required_doc_count)) | Out-Null
$lines.Add(("- missing_doc_count: {0}" -f [int]$summary.missing_doc_count)) | Out-Null
$lines.Add(("- handbook_decision: {0}" -f [string]$summary.handbook_decision)) | Out-Null
[System.IO.File]::WriteAllLines($reportPath, $lines, [System.Text.Encoding]::UTF8)

$archiveOutputPath = ""
if ($Zip) {
    $archiveOutputPath = $resolvedOutputDir.TrimEnd("\") + ".zip"
    if (Test-Path $archiveOutputPath) {
        Remove-Item -Path $archiveOutputPath -Force
    }
    Compress-Archive -Path (Join-Path $resolvedOutputDir "*") -DestinationPath $archiveOutputPath -Force
}

Write-Host "[done] ga steady-state operations handbook package completed"
Write-Host ("  handbook_manifest : {0}" -f $OutPath)
Write-Host ("  handbook_summary  : {0}" -f $SummaryOutPath)
Write-Host ("  decision          : {0}" -f [string]$summary.handbook_decision)
if (-not [string]::IsNullOrWhiteSpace($archiveOutputPath)) {
    Write-Host ("  archive           : {0}" -f $archiveOutputPath)
}

