param(
    [string]$EnvironmentMatrixManifestPath = "",
    [string]$CompatibilityManifestPath = "",
    [string]$SupportNormalizationManifestPath = "",
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
    $resolvedOutputDir = Join-Path $repoRoot ("logs\ga-ops\phase20-closeout-{0}" -f $timestamp)
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = Resolve-OperatorAbsolutePath -Path $resolvedOutputDir -BasePath $repoRoot
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "phase20-environment-support-closeout.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}

if ([string]::IsNullOrWhiteSpace($SummaryOutPath)) {
    $SummaryOutPath = Join-Path $resolvedOutputDir "phase20-environment-support-closeout.summary.json"
} elseif (-not [System.IO.Path]::IsPathRooted($SummaryOutPath)) {
    $SummaryOutPath = Resolve-OperatorAbsolutePath -Path $SummaryOutPath -BasePath $repoRoot
}

$resolvedMatrixManifestPath = Resolve-OptionalPath -PathValue $EnvironmentMatrixManifestPath -BasePath $repoRoot
$resolvedCompatibilityManifestPath = Resolve-OptionalPath -PathValue $CompatibilityManifestPath -BasePath $repoRoot
$resolvedSupportNormalizationManifestPath = Resolve-OptionalPath -PathValue $SupportNormalizationManifestPath -BasePath $repoRoot

$matrixManifestPath = Join-Path $resolvedOutputDir "ga-supported-environment-matrix.manifest.json"
if ([string]::IsNullOrWhiteSpace($resolvedMatrixManifestPath) -or -not (Test-Path $resolvedMatrixManifestPath)) {
    & (Join-Path $PSScriptRoot "ga-supported-environment-matrix.ps1") `
        -OutputDir (Join-Path $resolvedOutputDir "matrix") `
        -OutPath $matrixManifestPath `
        -SummaryOutPath (Join-Path $resolvedOutputDir "ga-supported-environment-matrix.summary.json")
    $resolvedMatrixManifestPath = $matrixManifestPath
}

$compatManifestPath = Join-Path $resolvedOutputDir "ga-compatibility-preflight.manifest.json"
if ([string]::IsNullOrWhiteSpace($resolvedCompatibilityManifestPath) -or -not (Test-Path $resolvedCompatibilityManifestPath)) {
    & (Join-Path $PSScriptRoot "ga-compatibility-preflight.ps1") `
        -EnvironmentMatrixManifestPath $resolvedMatrixManifestPath `
        -LogsRoot $resolvedLogsRoot `
        -OutputDir (Join-Path $resolvedOutputDir "preflight") `
        -OutPath $compatManifestPath `
        -SummaryOutPath (Join-Path $resolvedOutputDir "ga-compatibility-preflight.summary.json")
    $resolvedCompatibilityManifestPath = $compatManifestPath
}

$normalizationManifestPath = Join-Path $resolvedOutputDir "ga-support-intake-normalization.manifest.json"
if ([string]::IsNullOrWhiteSpace($resolvedSupportNormalizationManifestPath) -or -not (Test-Path $resolvedSupportNormalizationManifestPath)) {
    & (Join-Path $PSScriptRoot "ga-support-intake-normalization.ps1") `
        -LogsRoot $resolvedLogsRoot `
        -WindowDays 30 `
        -OutputDir (Join-Path $resolvedOutputDir "support-intake") `
        -OutPath $normalizationManifestPath `
        -SummaryOutPath (Join-Path $resolvedOutputDir "ga-support-intake-normalization.summary.json")
    $resolvedSupportNormalizationManifestPath = $normalizationManifestPath
}

$matrix = Read-OperatorJsonFile -Path $resolvedMatrixManifestPath
$preflight = Read-OperatorJsonFile -Path $resolvedCompatibilityManifestPath
$normalization = Read-OperatorJsonFile -Path $resolvedSupportNormalizationManifestPath

if ([string]$matrix.bundle_type -ne "phase20_supported_environment_matrix") {
    Write-Error ("Unexpected matrix bundle_type: {0}" -f [string]$matrix.bundle_type)
    exit 1
}
if ([string]$preflight.bundle_type -ne "phase20_compatibility_preflight_report") {
    Write-Error ("Unexpected compatibility bundle_type: {0}" -f [string]$preflight.bundle_type)
    exit 1
}
if ([string]$normalization.bundle_type -ne "phase20_support_intake_normalization") {
    Write-Error ("Unexpected support normalization bundle_type: {0}" -f [string]$normalization.bundle_type)
    exit 1
}

$matrixDecision = ([string]$matrix.summary.compatibility_baseline_decision).Trim().ToLowerInvariant()
$preflightDecision = ([string]$preflight.summary.compatibility_decision).Trim().ToLowerInvariant()
$normalizationDecision = ([string]$normalization.summary.normalization_decision).Trim().ToLowerInvariant()

$closeoutDecision = "go"
$decisionReasons = New-Object System.Collections.Generic.List[string]
if (@($matrixDecision, $preflightDecision, $normalizationDecision) -contains "escalate") {
    $closeoutDecision = "escalate"
    $decisionReasons.Add("At least one phase20 package returned escalate.") | Out-Null
} elseif (@($matrixDecision, $preflightDecision, $normalizationDecision) -contains "watch") {
    $closeoutDecision = "watch"
    $decisionReasons.Add("At least one phase20 package returned watch.") | Out-Null
} else {
    $decisionReasons.Add("All phase20 packages returned go.") | Out-Null
}

$summary = [ordered]@{
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    matrix_decision = $matrixDecision
    compatibility_decision = $preflightDecision
    support_normalization_decision = $normalizationDecision
    closeout_decision = $closeoutDecision
    closeout_decision_reasons = @($decisionReasons.ToArray())
}
Save-OperatorJson -Payload $summary -OutPath $SummaryOutPath

$manifest = [ordered]@{
    bundle_type = "phase20_environment_support_closeout"
    bundle_version = 1
    generated_at_utc = $summary.generated_at_utc
    summary = $summary
    source = [ordered]@{
        matrix_manifest_path = $resolvedMatrixManifestPath
        compatibility_manifest_path = $resolvedCompatibilityManifestPath
        support_normalization_manifest_path = $resolvedSupportNormalizationManifestPath
    }
    details = [ordered]@{
        next_steps = @(
            "1) if closeout_decision is watch/escalate, resolve listed package findings before phase_21 activation evidence capture.",
            "2) publish environment/support baseline docs and support intake field standards.",
            "3) attach closeout manifest path to staging execution record."
        )
    }
}
Save-OperatorJson -Payload $manifest -OutPath $OutPath

$reportPath = Join-Path $resolvedOutputDir "phase20-environment-support-closeout.md"
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# Phase 20 Environment and Support Closeout") | Out-Null
$lines.Add("") | Out-Null
$lines.Add(("- generated_at_utc: {0}" -f $summary.generated_at_utc)) | Out-Null
$lines.Add(("- matrix_decision: {0}" -f [string]$summary.matrix_decision)) | Out-Null
$lines.Add(("- compatibility_decision: {0}" -f [string]$summary.compatibility_decision)) | Out-Null
$lines.Add(("- support_normalization_decision: {0}" -f [string]$summary.support_normalization_decision)) | Out-Null
$lines.Add(("- closeout_decision: {0}" -f [string]$summary.closeout_decision)) | Out-Null
$lines.Add("") | Out-Null
$lines.Add("## Decision reasons") | Out-Null
foreach ($reason in @($summary.closeout_decision_reasons)) {
    $lines.Add(("- {0}" -f [string]$reason)) | Out-Null
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

Write-Host "[done] phase20 environment/support closeout completed"
Write-Host ("  closeout_manifest : {0}" -f $OutPath)
Write-Host ("  closeout_summary  : {0}" -f $SummaryOutPath)
Write-Host ("  closeout_decision : {0}" -f [string]$summary.closeout_decision)
if (-not [string]::IsNullOrWhiteSpace($archiveOutputPath)) {
    Write-Host ("  archive           : {0}" -f $archiveOutputPath)
}

