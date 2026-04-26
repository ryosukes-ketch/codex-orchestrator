param(
    [string]$ReadinessManifestPath = "",
    [string]$BundleManifestPath = "",
    [string]$SupportIntakeManifestPath = "",
    [string]$PreflightReportPath = "",
    [string]$UpdateGuardManifestPath = "",
    [string]$OutputDir = "",
    [switch]$Zip,
    [string]$ArchivePath = "",
    [string]$OutPath = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if (
    [string]::IsNullOrWhiteSpace($ReadinessManifestPath) `
        -and [string]::IsNullOrWhiteSpace($BundleManifestPath)
) {
    Write-Error "Provide -ReadinessManifestPath or -BundleManifestPath."
    exit 1
}

if (
    -not [string]::IsNullOrWhiteSpace($ReadinessManifestPath) `
        -and -not [string]::IsNullOrWhiteSpace($BundleManifestPath)
) {
    Write-Error "Specify only one of -ReadinessManifestPath or -BundleManifestPath."
    exit 1
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$resolvedOutputDir = ([string]$OutputDir).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedOutputDir)) {
    $resolvedOutputDir = Join-Path $repoRoot ("logs\self-serve\handoff-package-{0}" -f $timestamp)
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $resolvedOutputDir))
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

function Resolve-OptionalPath {
    param([string]$PathValue)
    if ([string]::IsNullOrWhiteSpace($PathValue)) {
        return ""
    }
    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return [System.IO.Path]::GetFullPath($PathValue)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $repoRoot $PathValue))
}

$resolvedReadinessManifestPath = Resolve-OptionalPath -PathValue $ReadinessManifestPath
$resolvedBundleManifestPath = Resolve-OptionalPath -PathValue $BundleManifestPath
$resolvedPreflightReportPath = Resolve-OptionalPath -PathValue $PreflightReportPath
$resolvedUpdateGuardManifestPath = Resolve-OptionalPath -PathValue $UpdateGuardManifestPath

$resolvedSupportIntakeManifestPath = Resolve-OptionalPath -PathValue $SupportIntakeManifestPath
if ([string]::IsNullOrWhiteSpace($resolvedSupportIntakeManifestPath)) {
    $generatedSupportDir = Join-Path $resolvedOutputDir "support-intake"
    $generatedSupportManifest = Join-Path $resolvedOutputDir "support-intake.manifest.json"
    $supportArgs = @{
        OutputDir = $generatedSupportDir
        OutPath = $generatedSupportManifest
    }
    if (-not [string]::IsNullOrWhiteSpace($resolvedReadinessManifestPath)) {
        $supportArgs.ReadinessManifestPath = $resolvedReadinessManifestPath
    }
    if (-not [string]::IsNullOrWhiteSpace($resolvedBundleManifestPath)) {
        $supportArgs.BundleManifestPath = $resolvedBundleManifestPath
    }
    & (Join-Path $PSScriptRoot "self-serve-support-intake.ps1") @supportArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $resolvedSupportIntakeManifestPath = $generatedSupportManifest
}

if (-not (Test-Path $resolvedSupportIntakeManifestPath)) {
    Write-Error ("Support intake manifest not found: {0}" -f $resolvedSupportIntakeManifestPath)
    exit 1
}

$supportIntakeManifest = Get-Content -Raw $resolvedSupportIntakeManifestPath | ConvertFrom-Json
$blockingFindings = [bool]$supportIntakeManifest.has_blocking_findings

$hasReadiness = (-not [string]::IsNullOrWhiteSpace($resolvedReadinessManifestPath) -and (Test-Path $resolvedReadinessManifestPath))
$hasBundle = (-not [string]::IsNullOrWhiteSpace($resolvedBundleManifestPath) -and (Test-Path $resolvedBundleManifestPath))
$hasPreflight = (-not [string]::IsNullOrWhiteSpace($resolvedPreflightReportPath) -and (Test-Path $resolvedPreflightReportPath))
$hasUpdateGuard = (-not [string]::IsNullOrWhiteSpace($resolvedUpdateGuardManifestPath) -and (Test-Path $resolvedUpdateGuardManifestPath))

$requiredScripts = @(
    "scripts\self-serve-preflight.ps1",
    "scripts\self-serve-update-guard.ps1",
    "scripts\self-serve-support-intake.ps1",
    "scripts\sqlite-backup.ps1",
    "scripts\sqlite-restore.ps1",
    "scripts\sqlite-verify.ps1",
    "scripts\sqlite-export.ps1",
    "scripts\release-readiness.ps1"
)
$missingScripts = @()
foreach ($scriptPath in $requiredScripts) {
    if (-not (Test-Path (Join-Path $repoRoot $scriptPath))) {
        $missingScripts += $scriptPath
    }
}
$hasRequiredScripts = ($missingScripts.Count -eq 0)

$acceptanceChecks = [ordered]@{
    source_manifest_present = ($hasReadiness -or $hasBundle)
    support_intake_present = $true
    support_intake_blocking_findings = $blockingFindings
    required_scripts_present = $hasRequiredScripts
    preflight_report_present = $hasPreflight
    update_guard_manifest_present = $hasUpdateGuard
}

$acceptanceStatus = if (
    $acceptanceChecks.source_manifest_present `
        -and $acceptanceChecks.support_intake_present `
        -and $acceptanceChecks.required_scripts_present `
        -and -not $acceptanceChecks.support_intake_blocking_findings
) {
    "ready_for_handoff"
} else {
    "review_required"
}

$markdownPath = Join-Path $resolvedOutputDir "handoff-package.md"
$mdLines = @(
    "# Self-Serve Handoff Package",
    "",
    ("- generated_at_utc: {0}" -f [DateTime]::UtcNow.ToString("o")),
    ("- acceptance_status: {0}" -f $acceptanceStatus),
    "",
    "## Acceptance checks",
    ("- source_manifest_present: {0}" -f $acceptanceChecks.source_manifest_present),
    ("- support_intake_present: {0}" -f $acceptanceChecks.support_intake_present),
    ("- support_intake_blocking_findings: {0}" -f $acceptanceChecks.support_intake_blocking_findings),
    ("- required_scripts_present: {0}" -f $acceptanceChecks.required_scripts_present),
    ("- preflight_report_present: {0}" -f $acceptanceChecks.preflight_report_present),
    ("- update_guard_manifest_present: {0}" -f $acceptanceChecks.update_guard_manifest_present),
    "",
    "## Source artifacts"
)
if ($hasReadiness) { $mdLines += ("- readiness_manifest: {0}" -f $resolvedReadinessManifestPath) }
if ($hasBundle) { $mdLines += ("- bundle_manifest: {0}" -f $resolvedBundleManifestPath) }
$mdLines += ("- support_intake_manifest: {0}" -f $resolvedSupportIntakeManifestPath)
if ($hasPreflight) { $mdLines += ("- preflight_report: {0}" -f $resolvedPreflightReportPath) }
if ($hasUpdateGuard) { $mdLines += ("- update_guard_manifest: {0}" -f $resolvedUpdateGuardManifestPath) }
if (-not $hasRequiredScripts) {
    $mdLines += ""
    $mdLines += "## Missing scripts"
    foreach ($scriptPath in $missingScripts) {
        $mdLines += ("- {0}" -f $scriptPath)
    }
}
[System.IO.File]::WriteAllLines($markdownPath, $mdLines, [System.Text.Encoding]::UTF8)

$archiveOutputPath = ""
if ($Zip) {
    $archiveOutputPath = ([string]$ArchivePath).Trim()
    if ([string]::IsNullOrWhiteSpace($archiveOutputPath)) {
        $archiveOutputPath = $resolvedOutputDir.TrimEnd("\") + ".zip"
    } elseif (-not [System.IO.Path]::IsPathRooted($archiveOutputPath)) {
        $archiveOutputPath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $archiveOutputPath))
    }
    if (Test-Path $archiveOutputPath) {
        Remove-Item -Path $archiveOutputPath -Force
    }
    Compress-Archive -Path (Join-Path $resolvedOutputDir "*") -DestinationPath $archiveOutputPath -Force
}

$manifest = [ordered]@{
    bundle_type = "self_serve_handoff_package"
    bundle_version = 1
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    output_dir = $resolvedOutputDir
    acceptance_status = $acceptanceStatus
    acceptance_checks = $acceptanceChecks
    source_artifacts = [ordered]@{
        readiness_manifest_path = $resolvedReadinessManifestPath
        bundle_manifest_path = $resolvedBundleManifestPath
        support_intake_manifest_path = $resolvedSupportIntakeManifestPath
        preflight_report_path = $resolvedPreflightReportPath
        update_guard_manifest_path = $resolvedUpdateGuardManifestPath
    }
    support_intake_summary = [ordered]@{
        classification_status = [string]$supportIntakeManifest.classification_status
        has_blocking_findings = [bool]$supportIntakeManifest.has_blocking_findings
        finding_count = [int]$supportIntakeManifest.finding_count
    }
    missing_scripts = @($missingScripts)
    handoff_markdown_path = $markdownPath
    archive_path = $archiveOutputPath
}

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "handoff-package.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $OutPath))
}
$manifest | ConvertTo-Json -Depth 20 | Set-Content -Path $OutPath -Encoding utf8

Write-Host "[done] self-serve-handoff-package completed"
Write-Host ("  acceptance_status       : {0}" -f $acceptanceStatus)
Write-Host ("  output_dir              : {0}" -f $resolvedOutputDir)
Write-Host ("  support_intake_manifest : {0}" -f $resolvedSupportIntakeManifestPath)
Write-Host ("  handoff_manifest        : {0}" -f $OutPath)
if (-not [string]::IsNullOrWhiteSpace($archiveOutputPath)) {
    Write-Host ("  archive_path            : {0}" -f $archiveOutputPath)
}
