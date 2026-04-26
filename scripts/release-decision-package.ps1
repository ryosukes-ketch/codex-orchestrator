param(
    [string]$ReleaseCandidateManifestPath = "",
    [string]$ReadinessManifestPath = "",
    [string]$OutputDir = "",
    [string]$OutPath = "",
    [string]$DecisionDocPath = "docs/release_go_hold_rollback_decision.md"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. (Join-Path $PSScriptRoot "operator-common.ps1")

function Resolve-CandidateManifestPath {
    param([string]$RequestedPath)

    $requested = ([string]$RequestedPath).Trim()
    if (-not [string]::IsNullOrWhiteSpace($requested)) {
        return (Resolve-OperatorAbsolutePath -Path $requested -BasePath $repoRoot)
    }

    $latest = Get-ChildItem -Path (Join-Path $repoRoot "logs\release-train") -Recurse -File -Filter "release-candidate.manifest.json" |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($null -eq $latest) {
        throw "No release-candidate manifest found under logs/release-train."
    }
    return $latest.FullName
}

function Resolve-ReadinessManifestPathInternal {
    param([string]$RequestedPath)

    $requested = ([string]$RequestedPath).Trim()
    if (-not [string]::IsNullOrWhiteSpace($requested)) {
        return (Resolve-OperatorAbsolutePath -Path $requested -BasePath $repoRoot)
    }

    $latest = Get-ChildItem -Path (Join-Path $repoRoot "logs\operational-readiness") -File -Filter "readiness-manifest-*.json" |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($null -eq $latest) {
        return ""
    }
    return $latest.FullName
}

$resolvedCandidatePath = Resolve-CandidateManifestPath -RequestedPath $ReleaseCandidateManifestPath
if (-not (Test-Path $resolvedCandidatePath)) {
    Write-Error ("Release candidate manifest not found: {0}" -f $resolvedCandidatePath)
    exit 1
}

$candidate = Read-OperatorJsonFile -Path $resolvedCandidatePath
if ([string]$candidate.bundle_type -ne "phase14_release_candidate_promotion") {
    Write-Error "Unexpected release candidate bundle_type."
    exit 1
}

$resolvedReadinessPath = Resolve-ReadinessManifestPathInternal -RequestedPath $ReadinessManifestPath
$readinessStatus = "unknown"
if (-not [string]::IsNullOrWhiteSpace($resolvedReadinessPath) -and (Test-Path $resolvedReadinessPath)) {
    $readiness = Read-OperatorJsonFile -Path $resolvedReadinessPath
    $summaryPath = Resolve-OperatorBundleArtifactPath -Manifest $readiness -ArtifactName "readiness_summary" -RepoRoot $repoRoot
    if (-not [string]::IsNullOrWhiteSpace($summaryPath) -and (Test-Path $summaryPath)) {
        try {
            $summary = Read-OperatorJsonFile -Path $summaryPath
            $statusRaw = [string]$summary.overall_status
            if ([string]::IsNullOrWhiteSpace($statusRaw)) {
                $statusRaw = [string]$summary.result
            }
            if (-not [string]::IsNullOrWhiteSpace($statusRaw)) {
                $readinessStatus = $statusRaw
            }
        } catch {
            $readinessStatus = "unknown"
        }
    }
}

$blockingCount = @($candidate.blocking_issues).Count
$holdReasonCount = @($candidate.hold_reasons).Count
$openP0 = Convert-OperatorToInt -Value $candidate.known_issue_impact.p0_open -Default 0
$openP1 = Convert-OperatorToInt -Value $candidate.known_issue_impact.p1_open -Default 0
$includedCount = @($candidate.included_items).Count

$decision = "GO"
$rollbackSignal = "hold_and_investigate"
$rationale = New-Object System.Collections.Generic.List[string]

if ($includedCount -eq 0) {
    $decision = "HOLD"
    $rollbackSignal = "hold_and_investigate"
    $rationale.Add("no included release candidate items") | Out-Null
}

if ($blockingCount -gt 0 -or $holdReasonCount -gt 0) {
    $decision = "HOLD"
    $rollbackSignal = "hold_and_investigate"
    $rationale.Add("candidate contains blocking issues or hold reasons") | Out-Null
}

if ($openP0 -gt 0) {
    $decision = "ROLLBACK_REQUIRED"
    $rollbackSignal = "rollback_required"
    $rationale.Add("open P0 known issue detected") | Out-Null
} elseif ($openP1 -gt 0 -and $decision -ne "ROLLBACK_REQUIRED") {
    $decision = "ROLLBACK_READY"
    $rollbackSignal = "rollback_recommended"
    $rationale.Add("open P1 known issue detected") | Out-Null
}

if ($readinessStatus -match "failed|error") {
    $decision = "HOLD"
    $rollbackSignal = "hold_and_investigate"
    $rationale.Add(("readiness status indicates failure: {0}" -f $readinessStatus)) | Out-Null
}

if ($rationale.Count -eq 0) {
    $rationale.Add("no blocking/hold condition detected under current candidate and known issue snapshot") | Out-Null
}

$resolvedOutputDir = ([string]$OutputDir).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedOutputDir)) {
    $resolvedOutputDir = Join-Path $repoRoot ("logs\release-train\decision-{0}" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = Resolve-OperatorAbsolutePath -Path $resolvedOutputDir -BasePath $repoRoot
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "release-decision-package.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}

$payload = [ordered]@{
    bundle_type = "phase14_release_decision_package"
    bundle_version = 1
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    source_release_candidate_manifest_path = $resolvedCandidatePath
    source_readiness_manifest_path = $resolvedReadinessPath
    readiness_status = $readinessStatus
    decision = $decision
    rollback_signal = $rollbackSignal
    rationale = @($rationale.ToArray())
    blocking_issue_count = $blockingCount
    hold_reason_count = $holdReasonCount
    known_issue_open_p0 = $openP0
    known_issue_open_p1 = $openP1
    included_item_count = $includedCount
    next_steps = @(
        "1) Assemble release notes with include/exclude/known-issue impact from candidate + decision.",
        "2) Route known issues to internal/operator/customer publication levels.",
        "3) Export release-train evidence package for staging record traceability."
    )
}

Save-OperatorJson -Payload $payload -OutPath $OutPath

$reportPath = Join-Path $resolvedOutputDir "release-decision-package.md"
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# Release Decision Package") | Out-Null
$lines.Add("") | Out-Null
$lines.Add(("- generated_at_utc: {0}" -f $payload.generated_at_utc)) | Out-Null
$lines.Add(("- decision: {0}" -f $decision)) | Out-Null
$lines.Add(("- rollback_signal: {0}" -f $rollbackSignal)) | Out-Null
$lines.Add(("- readiness_status: {0}" -f $readinessStatus)) | Out-Null
$lines.Add("") | Out-Null
$lines.Add("## Rationale") | Out-Null
foreach ($r in @($rationale.ToArray())) {
    $lines.Add(("- {0}" -f $r)) | Out-Null
}
[System.IO.File]::WriteAllLines($reportPath, $lines, [System.Text.Encoding]::UTF8)

if (-not [string]::IsNullOrWhiteSpace($DecisionDocPath)) {
    $resolvedDocPath = Resolve-OperatorAbsolutePath -Path $DecisionDocPath -BasePath $repoRoot
    $doc = New-Object System.Collections.Generic.List[string]
    $doc.Add("# Release Go/Hold/Rollback Decision (Phase 14 / p14_t2)") | Out-Null
    $doc.Add("") | Out-Null
    $doc.Add("## Purpose") | Out-Null
    $doc.Add("Derive deterministic GO/HOLD/ROLLBACK decision package from release candidate, readiness status, and known issue impact.") | Out-Null
    $doc.Add("") | Out-Null
    $doc.Add("## Latest metadata") | Out-Null
    $doc.Add(("- generated_at_utc: {0}" -f $payload.generated_at_utc)) | Out-Null
    $doc.Add(("- decision_manifest: {0}" -f (Get-OperatorRelativePath -Path $OutPath -RootPath $repoRoot))) | Out-Null
    $doc.Add(("- source_release_candidate_manifest: {0}" -f (Get-OperatorRelativePath -Path $resolvedCandidatePath -RootPath $repoRoot))) | Out-Null
    if (-not [string]::IsNullOrWhiteSpace($resolvedReadinessPath)) {
        $doc.Add(("- source_readiness_manifest: {0}" -f (Get-OperatorRelativePath -Path $resolvedReadinessPath -RootPath $repoRoot))) | Out-Null
    }
    $doc.Add(("- decision: {0}" -f $decision)) | Out-Null
    $doc.Add(("- rollback_signal: {0}" -f $rollbackSignal)) | Out-Null
    $doc.Add(("- readiness_status: {0}" -f $readinessStatus)) | Out-Null
    $doc.Add("") | Out-Null
    $doc.Add("## Rationale") | Out-Null
    foreach ($r in @($rationale.ToArray())) {
        $doc.Add(("- {0}" -f $r)) | Out-Null
    }
    [System.IO.File]::WriteAllLines($resolvedDocPath, $doc, [System.Text.Encoding]::UTF8)
}

Write-Host "[done] release decision package completed"
Write-Host ("  source_candidate : {0}" -f $resolvedCandidatePath)
Write-Host ("  decision         : {0}" -f $decision)
Write-Host ("  manifest         : {0}" -f $OutPath)
