param(
    [string]$BacklogExportManifestPath = "",
    [string]$KnownIssuesPath = "docs/known_issues_register.md",
    [string]$ReleaseId = "",
    [string]$ReleaseVersion = "",
    [string]$ReleaseOwner = "release_owner",
    [string]$OutputDir = "",
    [string]$OutPath = "",
    [string]$PromotionDocPath = "docs/release_candidate_promotion.md"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. (Join-Path $PSScriptRoot "operator-common.ps1")

function Resolve-BacklogManifestPath {
    param([string]$RequestedPath)

    $requested = ([string]$RequestedPath).Trim()
    if (-not [string]::IsNullOrWhiteSpace($requested)) {
        return (Resolve-OperatorAbsolutePath -Path $requested -BasePath $repoRoot)
    }

    $latest = Get-ChildItem -Path (Join-Path $repoRoot "logs\post-launch-ops") -Recurse -File -Filter "post-launch-backlog-export.manifest.json" |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($null -eq $latest) {
        throw "No post-launch-backlog-export manifest found under logs/post-launch-ops."
    }
    return $latest.FullName
}

function Get-KnownIssueImpact {
    param([string]$Content)

    $impact = [ordered]@{
        total = 0
        open = 0
        mitigated = 0
        resolved = 0
        accepted_risk = 0
        p0_open = 0
        p1_open = 0
        p2_open = 0
        p3_open = 0
    }

    foreach ($line in $Content -split "`n") {
        $trimmed = $line.Trim()
        if ($trimmed -notlike "| KI-*") {
            continue
        }

        $cells = @($trimmed.Split("|")) | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" }
        if ($cells.Count -lt 4) {
            continue
        }

        $severity = ([string]$cells[2]).Trim().ToUpperInvariant()
        $status = ([string]$cells[3]).Trim().ToLowerInvariant()

        $impact.total = [int]$impact.total + 1
        if ($impact.Contains($status)) {
            $impact[$status] = [int]$impact[$status] + 1
        }

        if ($status -eq "open") {
            switch ($severity) {
                "P0" { $impact.p0_open = [int]$impact.p0_open + 1 }
                "P1" { $impact.p1_open = [int]$impact.p1_open + 1 }
                "P2" { $impact.p2_open = [int]$impact.p2_open + 1 }
                "P3" { $impact.p3_open = [int]$impact.p3_open + 1 }
            }
        }
    }

    return $impact
}

$resolvedBacklogPath = Resolve-BacklogManifestPath -RequestedPath $BacklogExportManifestPath
if (-not (Test-Path $resolvedBacklogPath)) {
    Write-Error ("Backlog export manifest not found: {0}" -f $resolvedBacklogPath)
    exit 1
}

$backlog = Read-OperatorJsonFile -Path $resolvedBacklogPath
if ([string]$backlog.bundle_type -ne "phase13_post_launch_release_backlog_package") {
    Write-Error "Unexpected backlog export bundle_type."
    exit 1
}

$resolvedKnownIssuesPath = Resolve-OperatorAbsolutePath -Path $KnownIssuesPath -BasePath $repoRoot
$knownIssuesContent = if (Test-Path $resolvedKnownIssuesPath) { Get-Content -Raw -Path $resolvedKnownIssuesPath } else { "" }
$knownIssueImpact = Get-KnownIssueImpact -Content $knownIssuesContent

$resolvedOutputDir = ([string]$OutputDir).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedOutputDir)) {
    $resolvedOutputDir = Join-Path $repoRoot ("logs\release-train\candidate-{0}" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = Resolve-OperatorAbsolutePath -Path $resolvedOutputDir -BasePath $repoRoot
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "release-candidate.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}

$utcNow = [DateTime]::UtcNow
if ([string]::IsNullOrWhiteSpace($ReleaseId)) {
    $ReleaseId = "rel-{0}-001" -f $utcNow.ToString("yyyyMMdd")
}
if ([string]::IsNullOrWhiteSpace($ReleaseVersion)) {
    $ReleaseVersion = "1.14.0"
}

$included = New-Object System.Collections.Generic.List[object]
$excluded = New-Object System.Collections.Generic.List[object]
$blocking = New-Object System.Collections.Generic.List[object]
$holdReasons = New-Object System.Collections.Generic.List[string]

foreach ($candidate in @($backlog.release_candidates)) {
    $score = Convert-OperatorToInt -Value $candidate.score -Default 0
    $category = ([string]$candidate.category).Trim().ToLowerInvariant()

    $entry = [ordered]@{
        triage_id = [string]$candidate.triage_id
        category = [string]$candidate.category
        tier = [string]$candidate.tier
        score = $score
        lane = [string]$candidate.backlog_lane
        rationale = [string]$candidate.route_rationale
    }
    $included.Add($entry) | Out-Null

    if (($category -eq "runtime" -or $category -eq "provider_auth") -and $score -ge 15) {
        $blocking.Add([ordered]@{
            triage_id = [string]$candidate.triage_id
            reason = ("high-score {0} issue requires hold review" -f $category)
            score = $score
        }) | Out-Null
    }
}

foreach ($candidate in @($backlog.runbook_patches)) {
    $excluded.Add([ordered]@{
        triage_id = [string]$candidate.triage_id
        category = [string]$candidate.category
        reason = "runbook_patch queued outside release candidate payload"
    }) | Out-Null
}
foreach ($candidate in @($backlog.monitoring_only)) {
    $excluded.Add([ordered]@{
        triage_id = [string]$candidate.triage_id
        category = [string]$candidate.category
        reason = "monitoring_only"
    }) | Out-Null
}
foreach ($candidate in @($backlog.deferred_items)) {
    $excluded.Add([ordered]@{
        triage_id = [string]$candidate.triage_id
        category = [string]$candidate.category
        reason = "defer_accepted_risk"
    }) | Out-Null
}

if ($included.Count -eq 0) {
    $holdReasons.Add("no release candidates promoted from backlog export") | Out-Null
}
if ([int]$knownIssueImpact.p0_open -gt 0) {
    $holdReasons.Add("open P0 known issue present") | Out-Null
}
if ($blocking.Count -gt 0) {
    $holdReasons.Add("blocking runtime/provider candidate present") | Out-Null
}

$rolloutRecommendation = if ($holdReasons.Count -gt 0) { "hold_candidate" } else { "go_candidate" }

$payload = [ordered]@{
    bundle_type = "phase14_release_candidate_promotion"
    bundle_version = 1
    generated_at_utc = $utcNow.ToString("o")
    release_id = $ReleaseId
    release_version = $ReleaseVersion
    release_owner = $ReleaseOwner
    source_backlog_export_manifest_path = $resolvedBacklogPath
    source_known_issues_path = $resolvedKnownIssuesPath
    included_items = @($included.ToArray())
    excluded_items = @($excluded.ToArray())
    blocking_issues = @($blocking.ToArray())
    known_issue_impact = $knownIssueImpact
    hold_reasons = @($holdReasons.ToArray())
    rollout_recommendation = $rolloutRecommendation
    next_steps = @(
        "1) Build go/hold/rollback decision package from candidate + readiness + known issue impact.",
        "2) Assemble release notes and known issue publication routing.",
        "3) Export release-train evidence package for staging traceability."
    )
}

Save-OperatorJson -Payload $payload -OutPath $OutPath

$reportPath = Join-Path $resolvedOutputDir "release-candidate-promotion.md"
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# Release Candidate Promotion") | Out-Null
$lines.Add("") | Out-Null
$lines.Add(("- generated_at_utc: {0}" -f $payload.generated_at_utc)) | Out-Null
$lines.Add(("- release_id: {0}" -f $payload.release_id)) | Out-Null
$lines.Add(("- release_version: {0}" -f $payload.release_version)) | Out-Null
$lines.Add(("- included_items: {0}" -f $included.Count)) | Out-Null
$lines.Add(("- blocking_issues: {0}" -f $blocking.Count)) | Out-Null
$lines.Add(("- rollout_recommendation: {0}" -f $rolloutRecommendation)) | Out-Null
[System.IO.File]::WriteAllLines($reportPath, $lines, [System.Text.Encoding]::UTF8)

if (-not [string]::IsNullOrWhiteSpace($PromotionDocPath)) {
    $resolvedDocPath = Resolve-OperatorAbsolutePath -Path $PromotionDocPath -BasePath $repoRoot
    $doc = New-Object System.Collections.Generic.List[string]
    $doc.Add("# Release Candidate Promotion (Phase 14 / p14_t1)") | Out-Null
    $doc.Add("") | Out-Null
    $doc.Add("## Purpose") | Out-Null
    $doc.Add("Promote phase_13 backlog export outputs into an explicit release candidate manifest with include/exclude/blocking rationale.") | Out-Null
    $doc.Add("") | Out-Null
    $doc.Add("## Latest metadata") | Out-Null
    $doc.Add(("- generated_at_utc: {0}" -f $payload.generated_at_utc)) | Out-Null
    $doc.Add(("- release_candidate_manifest: {0}" -f (Get-OperatorRelativePath -Path $OutPath -RootPath $repoRoot))) | Out-Null
    $doc.Add(("- source_backlog_export_manifest: {0}" -f (Get-OperatorRelativePath -Path $resolvedBacklogPath -RootPath $repoRoot))) | Out-Null
    $doc.Add(("- included_items: {0}" -f $included.Count)) | Out-Null
    $doc.Add(("- excluded_items: {0}" -f $excluded.Count)) | Out-Null
    $doc.Add(("- blocking_issues: {0}" -f $blocking.Count)) | Out-Null
    $doc.Add(("- rollout_recommendation: {0}" -f $rolloutRecommendation)) | Out-Null
    $doc.Add("") | Out-Null
    $doc.Add("## Hold reasons") | Out-Null
    if ($holdReasons.Count -eq 0) {
        $doc.Add("- none") | Out-Null
    } else {
        foreach ($reason in @($holdReasons.ToArray())) {
            $doc.Add(("- {0}" -f $reason)) | Out-Null
        }
    }
    [System.IO.File]::WriteAllLines($resolvedDocPath, $doc, [System.Text.Encoding]::UTF8)
}

Write-Host "[done] release candidate promotion completed"
Write-Host ("  source_backlog_export : {0}" -f $resolvedBacklogPath)
Write-Host ("  included_items        : {0}" -f $included.Count)
Write-Host ("  blocking_issues       : {0}" -f $blocking.Count)
Write-Host ("  manifest              : {0}" -f $OutPath)
