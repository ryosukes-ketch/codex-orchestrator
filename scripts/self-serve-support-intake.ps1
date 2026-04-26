param(
    [string]$ReadinessManifestPath = "",
    [string]$BundleManifestPath = "",
    [string]$SupportBundleManifestPath = "",
    [string]$OutputDir = "",
    [switch]$Zip,
    [string]$ArchivePath = "",
    [string]$OutPath = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if (
    -not [string]::IsNullOrWhiteSpace($SupportBundleManifestPath) `
        -and (
            -not [string]::IsNullOrWhiteSpace($ReadinessManifestPath) `
                -or -not [string]::IsNullOrWhiteSpace($BundleManifestPath)
        )
) {
    Write-Error "When -SupportBundleManifestPath is provided, do not combine with -ReadinessManifestPath or -BundleManifestPath."
    exit 1
}

if (
    [string]::IsNullOrWhiteSpace($SupportBundleManifestPath) `
        -and [string]::IsNullOrWhiteSpace($ReadinessManifestPath) `
        -and [string]::IsNullOrWhiteSpace($BundleManifestPath)
) {
    Write-Error "Provide -SupportBundleManifestPath, -ReadinessManifestPath, or -BundleManifestPath."
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
    $resolvedOutputDir = Join-Path $repoRoot ("logs\self-serve\support-intake-{0}" -f $timestamp)
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $resolvedOutputDir))
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

$resolvedSupportManifest = ""
if (-not [string]::IsNullOrWhiteSpace($SupportBundleManifestPath)) {
    $resolvedSupportManifest = $SupportBundleManifestPath
    if (-not [System.IO.Path]::IsPathRooted($resolvedSupportManifest)) {
        $resolvedSupportManifest = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $resolvedSupportManifest))
    }
    if (-not (Test-Path $resolvedSupportManifest)) {
        Write-Error ("Support bundle manifest not found: {0}" -f $resolvedSupportManifest)
        exit 1
    }
} else {
    $supportDir = Join-Path $resolvedOutputDir "support-bundle"
    $resolvedSupportManifest = Join-Path $resolvedOutputDir "support-bundle.manifest.json"
    $supportArgs = @{
        OutputDir = $supportDir
        OutPath = $resolvedSupportManifest
    }
    if (-not [string]::IsNullOrWhiteSpace($ReadinessManifestPath)) {
        $supportArgs.ReadinessManifestPath = $ReadinessManifestPath
    }
    if (-not [string]::IsNullOrWhiteSpace($BundleManifestPath)) {
        $supportArgs.BundleManifestPath = $BundleManifestPath
    }
    & (Join-Path $PSScriptRoot "operator-support-bundle.ps1") @supportArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$supportManifest = Get-Content -Raw $resolvedSupportManifest | ConvertFrom-Json
$classificationPath = [string]$supportManifest.failure_classification_json_path
if ([string]::IsNullOrWhiteSpace($classificationPath)) {
    Write-Error ("failure_classification_json_path missing in support bundle manifest: {0}" -f $resolvedSupportManifest)
    exit 1
}
if (-not [System.IO.Path]::IsPathRooted($classificationPath)) {
    $classificationPath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $classificationPath))
}
if (-not (Test-Path $classificationPath)) {
    Write-Error ("Failure classification JSON not found: {0}" -f $classificationPath)
    exit 1
}

$classificationPayload = Get-Content -Raw $classificationPath | ConvertFrom-Json
$requiredAttachments = @(
    $resolvedSupportManifest,
    $classificationPath,
    [string]$supportManifest.replay_export_manifest_path
) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }

$intake = [ordered]@{
    bundle_type = "self_serve_support_intake"
    bundle_version = 1
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    support_bundle_manifest_path = $resolvedSupportManifest
    failure_classification_json_path = $classificationPath
    classification_status = [string]$classificationPayload.classification_status
    has_blocking_findings = [bool]$classificationPayload.has_blocking_findings
    finding_count = [int]$classificationPayload.finding_count
    category_counts = $classificationPayload.category_counts
    severity_counts = $classificationPayload.severity_counts
    required_attachments = @($requiredAttachments)
    redaction_policy = @(
        "Do not include API keys, bearer tokens, or credential files in support uploads.",
        "Provide manifest/summary/classification artifacts first; include raw logs only when requested.",
        "Share sqlite backups only via approved secure channel."
    )
    intake_questions = @(
        "What command was executed immediately before failure?",
        "Which manifest path is the source of truth for this incident?",
        "Has rollback been executed? If yes, include restore report path.",
        "Were strict policy assertions enabled during this run?"
    )
}

$markdownPath = Join-Path $resolvedOutputDir "support-intake.md"
$mdLines = @(
    "# Self-Serve Support Intake",
    "",
    ("- generated_at_utc: {0}" -f $intake.generated_at_utc),
    ("- classification_status: {0}" -f $intake.classification_status),
    ("- has_blocking_findings: {0}" -f $intake.has_blocking_findings),
    ("- finding_count: {0}" -f $intake.finding_count),
    "",
    "## Required attachments"
)
foreach ($attachment in @($intake.required_attachments)) {
    $mdLines += ("- {0}" -f [string]$attachment)
}
$mdLines += ""
$mdLines += "## Redaction policy"
foreach ($line in @($intake.redaction_policy)) {
    $mdLines += ("- {0}" -f [string]$line)
}
$mdLines += ""
$mdLines += "## Intake questions"
foreach ($line in @($intake.intake_questions)) {
    $mdLines += ("- {0}" -f [string]$line)
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
    bundle_type = "self_serve_support_intake_manifest"
    bundle_version = 1
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    output_dir = $resolvedOutputDir
    support_intake_markdown_path = $markdownPath
    support_bundle_manifest_path = $resolvedSupportManifest
    failure_classification_json_path = $classificationPath
    classification_status = $intake.classification_status
    has_blocking_findings = $intake.has_blocking_findings
    finding_count = $intake.finding_count
    category_counts = $intake.category_counts
    severity_counts = $intake.severity_counts
    required_attachments = $intake.required_attachments
    archive_path = $archiveOutputPath
}

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "support-intake.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $OutPath))
}
$manifest | ConvertTo-Json -Depth 20 | Set-Content -Path $OutPath -Encoding utf8

Write-Host "[done] self-serve-support-intake completed"
Write-Host ("  output_dir                : {0}" -f $resolvedOutputDir)
Write-Host ("  support_bundle_manifest   : {0}" -f $resolvedSupportManifest)
Write-Host ("  classification_json       : {0}" -f $classificationPath)
Write-Host ("  intake_manifest           : {0}" -f $OutPath)
if (-not [string]::IsNullOrWhiteSpace($archiveOutputPath)) {
    Write-Host ("  archive_path              : {0}" -f $archiveOutputPath)
}
