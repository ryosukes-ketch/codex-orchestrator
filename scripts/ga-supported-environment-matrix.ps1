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
    $resolvedOutputDir = Join-Path $repoRoot ("logs\ga-ops\environment-matrix-{0}" -f $timestamp)
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = Resolve-OperatorAbsolutePath -Path $resolvedOutputDir -BasePath $repoRoot
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "ga-supported-environment-matrix.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}

if ([string]::IsNullOrWhiteSpace($SummaryOutPath)) {
    $SummaryOutPath = Join-Path $resolvedOutputDir "ga-supported-environment-matrix.summary.json"
} elseif (-not [System.IO.Path]::IsPathRooted($SummaryOutPath)) {
    $SummaryOutPath = Resolve-OperatorAbsolutePath -Path $SummaryOutPath -BasePath $repoRoot
}

$supported = @(
    [ordered]@{
        environment_id = "win11_ps7_sqlite_openclaw"
        os = "Windows 11"
        shell = "PowerShell 7.x"
        python = "3.10-3.12"
        state_backend = "sqlite"
        openclaw_profile = "codex-orchestrator/default profile"
        support_level = "supported"
        notes = "Primary self-serve target profile."
    },
    [ordered]@{
        environment_id = "win10_ps5_sqlite_openclaw"
        os = "Windows 10"
        shell = "Windows PowerShell 5.1"
        python = "3.10-3.12"
        state_backend = "sqlite"
        openclaw_profile = "codex-orchestrator/default profile"
        support_level = "supported_with_notes"
        notes = "Supported with higher latency variance; use timeout guidance from runbook."
    }
)

$unsupported = @(
    [ordered]@{
        environment_id = "linux_local_profile"
        reason = "Windows/PowerShell operator script contract is required for the current commercial ops baseline."
    },
    [ordered]@{
        environment_id = "multi_instance_sqlite"
        reason = "SQLite mode is single-operator oriented and not optimized for high concurrency."
    },
    [ordered]@{
        environment_id = "no_openclaw_profile"
        reason = "Commercial baseline assumes OpenClaw-routed operator model path."
    }
)

$summary = [ordered]@{
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    supported_environment_count = $supported.Count
    unsupported_environment_count = $unsupported.Count
    compatibility_baseline_decision = "go"
}
Save-OperatorJson -Payload $summary -OutPath $SummaryOutPath

$manifest = [ordered]@{
    bundle_type = "phase20_supported_environment_matrix"
    bundle_version = 1
    generated_at_utc = $summary.generated_at_utc
    summary = $summary
    details = [ordered]@{
        supported_environments = $supported
        unsupported_environments = $unsupported
        next_steps = @(
            "1) run ga-compatibility-preflight.ps1 to validate local runtime contracts against this matrix.",
            "2) run ga-support-intake-normalization.ps1 to verify intake-scale consistency.",
            "3) keep runbook support matrix synchronized with this manifest."
        )
    }
}
Save-OperatorJson -Payload $manifest -OutPath $OutPath

$reportPath = Join-Path $resolvedOutputDir "ga-supported-environment-matrix.md"
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# GA Supported Environment Matrix") | Out-Null
$lines.Add("") | Out-Null
$lines.Add(("- generated_at_utc: {0}" -f $summary.generated_at_utc)) | Out-Null
$lines.Add(("- supported_environment_count: {0}" -f [int]$summary.supported_environment_count)) | Out-Null
$lines.Add(("- unsupported_environment_count: {0}" -f [int]$summary.unsupported_environment_count)) | Out-Null
$lines.Add(("- compatibility_baseline_decision: {0}" -f [string]$summary.compatibility_baseline_decision)) | Out-Null
$lines.Add("") | Out-Null
$lines.Add("## Supported environments") | Out-Null
foreach ($entry in @($supported)) {
    $lines.Add(("- {0}: {1} / {2} / python {3} / {4}" -f [string]$entry.environment_id, [string]$entry.os, [string]$entry.shell, [string]$entry.python, [string]$entry.state_backend)) | Out-Null
}
$lines.Add("") | Out-Null
$lines.Add("## Unsupported environments") | Out-Null
foreach ($entry in @($unsupported)) {
    $lines.Add(("- {0}: {1}" -f [string]$entry.environment_id, [string]$entry.reason)) | Out-Null
}
[System.IO.File]::WriteAllLines($reportPath, $lines, [System.Text.Encoding]::UTF8)

$archiveOutputPath = ""
if ($Zip) {
    $archiveOutputPath = $resolvedOutputDir.TrimEnd("\") + ".zip"
    if (Test-Path $archiveOutputPath) {
        Remove-Item -Path $archiveOutputPath -Force
    }
    Compress-Archive -Path (Join-Path $resolvedOutputDir "*") -DestinationPath $archiveOutputPath -Force
}

Write-Host "[done] ga supported environment matrix completed"
Write-Host ("  matrix_manifest  : {0}" -f $OutPath)
Write-Host ("  matrix_summary   : {0}" -f $SummaryOutPath)
if (-not [string]::IsNullOrWhiteSpace($archiveOutputPath)) {
    Write-Host ("  archive          : {0}" -f $archiveOutputPath)
}

