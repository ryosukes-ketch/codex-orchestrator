param(
    [string]$HandbookManifestPath = "",
    [string]$CadenceManifestPath = "",
    [string]$EndToEndEvidenceManifestPath = "",
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
    $resolvedOutputDir = Join-Path $repoRoot ("logs\ga-steady-state\phase22-closeout-{0}" -f $timestamp)
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = Resolve-OperatorAbsolutePath -Path $resolvedOutputDir -BasePath $repoRoot
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "phase22-steady-state-closeout.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}

if ([string]::IsNullOrWhiteSpace($SummaryOutPath)) {
    $SummaryOutPath = Join-Path $resolvedOutputDir "phase22-steady-state-closeout.summary.json"
} elseif (-not [System.IO.Path]::IsPathRooted($SummaryOutPath)) {
    $SummaryOutPath = Resolve-OperatorAbsolutePath -Path $SummaryOutPath -BasePath $repoRoot
}

$resolvedHandbookManifestPath = Resolve-OptionalPath -PathValue $HandbookManifestPath -BasePath $repoRoot
$resolvedCadenceManifestPath = Resolve-OptionalPath -PathValue $CadenceManifestPath -BasePath $repoRoot
$resolvedEndToEndManifestPath = Resolve-OptionalPath -PathValue $EndToEndEvidenceManifestPath -BasePath $repoRoot

$handbookOut = Join-Path $resolvedOutputDir "ga-steady-state-operations-handbook.manifest.json"
if ([string]::IsNullOrWhiteSpace($resolvedHandbookManifestPath) -or -not (Test-Path $resolvedHandbookManifestPath)) {
    & (Join-Path $PSScriptRoot "ga-steady-state-operations-handbook.ps1") `
        -OutputDir (Join-Path $resolvedOutputDir "handbook") `
        -OutPath $handbookOut `
        -SummaryOutPath (Join-Path $resolvedOutputDir "ga-steady-state-operations-handbook.summary.json")
    $resolvedHandbookManifestPath = $handbookOut
}

$cadenceOut = Join-Path $resolvedOutputDir "ga-release-ops-cadence-baseline.manifest.json"
if ([string]::IsNullOrWhiteSpace($resolvedCadenceManifestPath) -or -not (Test-Path $resolvedCadenceManifestPath)) {
    & (Join-Path $PSScriptRoot "ga-release-ops-cadence-baseline.ps1") `
        -OutputDir (Join-Path $resolvedOutputDir "cadence") `
        -OutPath $cadenceOut `
        -SummaryOutPath (Join-Path $resolvedOutputDir "ga-release-ops-cadence-baseline.summary.json")
    $resolvedCadenceManifestPath = $cadenceOut
}

$e2eOut = Join-Path $resolvedOutputDir "ga-end-to-end-operations-evidence.manifest.json"
if ([string]::IsNullOrWhiteSpace($resolvedEndToEndManifestPath) -or -not (Test-Path $resolvedEndToEndManifestPath)) {
    & (Join-Path $PSScriptRoot "ga-end-to-end-operations-evidence.ps1") `
        -LogsRoot $resolvedLogsRoot `
        -OutputDir (Join-Path $resolvedOutputDir "e2e") `
        -OutPath $e2eOut `
        -SummaryOutPath (Join-Path $resolvedOutputDir "ga-end-to-end-operations-evidence.summary.json")
    $resolvedEndToEndManifestPath = $e2eOut
}

$handbook = Read-OperatorJsonFile -Path $resolvedHandbookManifestPath
$cadence = Read-OperatorJsonFile -Path $resolvedCadenceManifestPath
$e2e = Read-OperatorJsonFile -Path $resolvedEndToEndManifestPath

if ([string]$handbook.bundle_type -ne "phase22_steady_state_operations_handbook") {
    Write-Error ("Unexpected handbook bundle_type: {0}" -f [string]$handbook.bundle_type)
    exit 1
}
if ([string]$cadence.bundle_type -ne "phase22_release_ops_cadence_baseline") {
    Write-Error ("Unexpected cadence bundle_type: {0}" -f [string]$cadence.bundle_type)
    exit 1
}
if ([string]$e2e.bundle_type -ne "phase22_end_to_end_operations_evidence") {
    Write-Error ("Unexpected end-to-end bundle_type: {0}" -f [string]$e2e.bundle_type)
    exit 1
}

$handbookDecision = ([string]$handbook.summary.handbook_decision).Trim().ToLowerInvariant()
$cadenceDecision = ([string]$cadence.summary.cadence_decision).Trim().ToLowerInvariant()
$e2eDecision = ([string]$e2e.summary.end_to_end_decision).Trim().ToLowerInvariant()

$closeoutDecision = "go"
$decisionReasons = New-Object System.Collections.Generic.List[string]
if (@($handbookDecision, $cadenceDecision, $e2eDecision) -contains "watch") {
    $closeoutDecision = "watch"
    $decisionReasons.Add("At least one steady-state package returned watch.") | Out-Null
} else {
    $decisionReasons.Add("Handbook, cadence, and end-to-end evidence packages are all go.") | Out-Null
}

$summary = [ordered]@{
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    handbook_decision = $handbookDecision
    cadence_decision = $cadenceDecision
    end_to_end_decision = $e2eDecision
    closeout_decision = $closeoutDecision
    steady_state_activation_ready = ($closeoutDecision -eq "go")
    closeout_decision_reasons = @($decisionReasons.ToArray())
}
Save-OperatorJson -Payload $summary -OutPath $SummaryOutPath

$manifest = [ordered]@{
    bundle_type = "phase22_steady_state_closeout"
    bundle_version = 1
    generated_at_utc = $summary.generated_at_utc
    summary = $summary
    source = [ordered]@{
        handbook_manifest_path = $resolvedHandbookManifestPath
        cadence_manifest_path = $resolvedCadenceManifestPath
        end_to_end_manifest_path = $resolvedEndToEndManifestPath
    }
}
Save-OperatorJson -Payload $manifest -OutPath $OutPath

$reportPath = Join-Path $resolvedOutputDir "phase22-steady-state-closeout.md"
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# Phase 22 Steady-State Closeout") | Out-Null
$lines.Add("") | Out-Null
$lines.Add(("- generated_at_utc: {0}" -f $summary.generated_at_utc)) | Out-Null
$lines.Add(("- handbook_decision: {0}" -f [string]$summary.handbook_decision)) | Out-Null
$lines.Add(("- cadence_decision: {0}" -f [string]$summary.cadence_decision)) | Out-Null
$lines.Add(("- end_to_end_decision: {0}" -f [string]$summary.end_to_end_decision)) | Out-Null
$lines.Add(("- closeout_decision: {0}" -f [string]$summary.closeout_decision)) | Out-Null
$lines.Add(("- steady_state_activation_ready: {0}" -f [string]$summary.steady_state_activation_ready)) | Out-Null
[System.IO.File]::WriteAllLines($reportPath, $lines, [System.Text.Encoding]::UTF8)

$archiveOutputPath = ""
if ($Zip) {
    $archiveOutputPath = $resolvedOutputDir.TrimEnd("\") + ".zip"
    if (Test-Path $archiveOutputPath) {
        Remove-Item -Path $archiveOutputPath -Force
    }
    Compress-Archive -Path (Join-Path $resolvedOutputDir "*") -DestinationPath $archiveOutputPath -Force
}

Write-Host "[done] phase22 steady-state closeout completed"
Write-Host ("  closeout_manifest       : {0}" -f $OutPath)
Write-Host ("  closeout_summary        : {0}" -f $SummaryOutPath)
Write-Host ("  steady_state_activation : {0}" -f [string]$summary.steady_state_activation_ready)
if (-not [string]::IsNullOrWhiteSpace($archiveOutputPath)) {
    Write-Host ("  archive                : {0}" -f $archiveOutputPath)
}

