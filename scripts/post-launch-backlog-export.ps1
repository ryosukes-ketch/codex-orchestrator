param(
    [string]$RoutingManifestPath = "",
    [string]$OutputDir = "",
    [string]$OutPath = "",
    [string]$BacklogDocPath = "docs/post_launch_release_backlog_flow.md"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. (Join-Path $PSScriptRoot "operator-common.ps1")

function Resolve-RoutingManifestPath {
    param([string]$RequestedPath)

    $requested = ([string]$RequestedPath).Trim()
    if (-not [string]::IsNullOrWhiteSpace($requested)) {
        return (Resolve-OperatorAbsolutePath -Path $requested -BasePath $repoRoot)
    }

    $latest = Get-ChildItem -Path (Join-Path $repoRoot "logs\post-launch-ops") -Recurse -File -Filter "known-issue-routing.manifest.json" |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($null -eq $latest) {
        throw "No known-issue-routing manifest found under logs/post-launch-ops."
    }
    return $latest.FullName
}

$resolvedRoutingPath = Resolve-RoutingManifestPath -RequestedPath $RoutingManifestPath
if (-not (Test-Path $resolvedRoutingPath)) {
    Write-Error ("Routing manifest not found: {0}" -f $resolvedRoutingPath)
    exit 1
}

$routing = Read-OperatorJsonFile -Path $resolvedRoutingPath
if ([string]$routing.bundle_type -ne "phase13_known_issue_routing") {
    Write-Error "Unexpected known-issue routing manifest bundle_type."
    exit 1
}

$resolvedOutputDir = ([string]$OutputDir).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedOutputDir)) {
    $resolvedOutputDir = Join-Path $repoRoot ("logs\post-launch-ops\post-launch-backlog-export-{0}" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = Resolve-OperatorAbsolutePath -Path $resolvedOutputDir -BasePath $repoRoot
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "post-launch-backlog-export.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}

$releaseCandidates = New-Object System.Collections.Generic.List[object]
$runbookPatches = New-Object System.Collections.Generic.List[object]
$monitoringOnly = New-Object System.Collections.Generic.List[object]
$deferred = New-Object System.Collections.Generic.List[object]

foreach ($item in @($routing.routing_items)) {
    $route = ([string]$item.route).Trim().ToLowerInvariant()
    $entry = [ordered]@{
        triage_id = [string]$item.triage_id
        category = [string]$item.category
        score = Convert-OperatorToInt -Value $item.score -Default 0
        tier = [string]$item.tier
        route = [string]$item.route
        route_rationale = [string]$item.route_rationale
    }

    switch ($route) {
        "hotfix_candidate" {
            $entry.backlog_lane = "hotfix"
            $releaseCandidates.Add($entry) | Out-Null
        }
        "next_release_candidate" {
            $entry.backlog_lane = "next_release"
            $releaseCandidates.Add($entry) | Out-Null
        }
        "runbook_patch" {
            $runbookPatches.Add($entry) | Out-Null
        }
        "defer_accepted_risk" {
            $deferred.Add($entry) | Out-Null
        }
        default {
            $monitoringOnly.Add($entry) | Out-Null
        }
    }
}

$summary = [ordered]@{
    release_candidate_count = $releaseCandidates.Count
    runbook_patch_count = $runbookPatches.Count
    monitoring_only_count = $monitoringOnly.Count
    deferred_count = $deferred.Count
}

$payload = [ordered]@{
    bundle_type = "phase13_post_launch_release_backlog_package"
    bundle_version = 1
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    source_known_issue_routing_manifest_path = $resolvedRoutingPath
    summary = $summary
    release_candidates = @($releaseCandidates.ToArray())
    runbook_patches = @($runbookPatches.ToArray())
    monitoring_only = @($monitoringOnly.ToArray())
    deferred_items = @($deferred.ToArray())
    next_steps = @(
        "1) Review hotfix and next_release lanes in launch governance meeting.",
        "2) Apply runbook_patch entries to bounded docs updates.",
        "3) Keep monitoring/deferred entries in weekly support trend cadence."
    )
}

Save-OperatorJson -Payload $payload -OutPath $OutPath

$reportMarkdownPath = Join-Path $resolvedOutputDir "post-launch-backlog-export.md"
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# Post-Launch Backlog Export") | Out-Null
$lines.Add("") | Out-Null
$lines.Add(("- generated_at_utc: {0}" -f $payload.generated_at_utc)) | Out-Null
$lines.Add(("- source_routing_manifest: {0}" -f (Get-OperatorRelativePath -Path $resolvedRoutingPath -RootPath $repoRoot))) | Out-Null
$lines.Add("") | Out-Null
$lines.Add("## Summary") | Out-Null
foreach ($entry in $summary.GetEnumerator()) {
    $lines.Add(("- {0}: {1}" -f [string]$entry.Key, [int]$entry.Value)) | Out-Null
}
$lines.Add("") | Out-Null
$lines.Add("## Release candidates") | Out-Null
if ($releaseCandidates.Count -eq 0) {
    $lines.Add("- none") | Out-Null
} else {
    foreach ($item in @($releaseCandidates.ToArray())) {
        $lines.Add(("- {0} [{1}] lane={2} score={3}" -f [string]$item.triage_id, [string]$item.category, [string]$item.backlog_lane, [int]$item.score)) | Out-Null
    }
}
[System.IO.File]::WriteAllLines($reportMarkdownPath, $lines, [System.Text.Encoding]::UTF8)

if (-not [string]::IsNullOrWhiteSpace($BacklogDocPath)) {
    $resolvedDocPath = Resolve-OperatorAbsolutePath -Path $BacklogDocPath -BasePath $repoRoot
    $docLines = New-Object System.Collections.Generic.List[string]
    $docLines.Add("# Post-Launch Release Backlog Flow (Phase 13 / p13_t4)") | Out-Null
    $docLines.Add("") | Out-Null
    $docLines.Add("## Purpose") | Out-Null
    $docLines.Add("Connect post-launch routed issues to release/hotfix/runbook backlog lanes with deterministic evidence exports.") | Out-Null
    $docLines.Add("") | Out-Null
    $docLines.Add("## Latest metadata") | Out-Null
    $docLines.Add(("- generated_at_utc: {0}" -f $payload.generated_at_utc)) | Out-Null
    $docLines.Add(("- backlog_export_manifest: {0}" -f (Get-OperatorRelativePath -Path $OutPath -RootPath $repoRoot))) | Out-Null
    $docLines.Add(("- source_known_issue_routing_manifest: {0}" -f (Get-OperatorRelativePath -Path $resolvedRoutingPath -RootPath $repoRoot))) | Out-Null
    $docLines.Add("") | Out-Null
    $docLines.Add("## Summary") | Out-Null
    foreach ($entry in $summary.GetEnumerator()) {
        $docLines.Add(("- {0}: {1}" -f [string]$entry.Key, [int]$entry.Value)) | Out-Null
    }
    $docLines.Add("") | Out-Null
    $docLines.Add("## Next actions") | Out-Null
    foreach ($step in @($payload.next_steps)) {
        $docLines.Add(("- {0}" -f [string]$step)) | Out-Null
    }
    [System.IO.File]::WriteAllLines($resolvedDocPath, $docLines, [System.Text.Encoding]::UTF8)
}

Write-Host "[done] post-launch backlog export completed"
Write-Host ("  routing_manifest : {0}" -f $resolvedRoutingPath)
Write-Host ("  release_candidates: {0}" -f $releaseCandidates.Count)
Write-Host ("  manifest         : {0}" -f $OutPath)
Write-Host ("  report_markdown  : {0}" -f $reportMarkdownPath)
if (-not [string]::IsNullOrWhiteSpace($BacklogDocPath)) {
    Write-Host ("  backlog_doc      : {0}" -f (Resolve-OperatorAbsolutePath -Path $BacklogDocPath -BasePath $repoRoot))
}
